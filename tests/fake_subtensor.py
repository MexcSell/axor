"""A scripted Bittensor chain for testing the Wallets tab offline: WALLET_CHAIN_FACTORY=fake_subtensor:factory.

It answers the reads the wallet makes (balances, stake, hotkeys, quotes, a metagraph per subnet, delegates, prices
and names) and the SDK calls transactions use (plan, prepare_call, submit_signature). Every coldkey starts with
12.5 τ free and stake on SN19 and SN64 through the first validator; submitted transactions change that state, so
the page shows the new balances. A signature of all zero bytes is rejected like a bad signature on chain.
"""
import hashlib, threading, time
from types import SimpleNamespace as NS

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
RAO = 10**9

def ss58(pub, prefix=42):
    raw = bytes([prefix]) + pub
    raw += hashlib.blake2b(b"SS58PRE" + raw, digest_size=64).digest()[:2]
    n, out = int.from_bytes(raw, "big"), ""
    while n: n, r = divmod(n, 58); out = B58[r] + out
    return out

def key(seed): return ss58(hashlib.sha256(seed.encode()).digest())

class Bal:
    def __init__(self, tao): self.rao = int(round(tao * RAO))
    def __repr__(self): return f"τ{self.rao / RAO:.9f}"

NAMES = {0: "Root", 1: "Apex", 8: "Proprietary Trading", 19: "Inference", 62: "Ridges", 64: "Chutes"}
PRICE = {0: 1.0, 1: 0.0062, 8: 0.032, 19: 0.0904, 62: 0.041, 64: 0.115}
POOL_TAO = {0: 1e12, 1: 4200.0, 8: 9100.0, 19: 15300.0, 62: 12800.0, 64: 61000.0}  # for slippage
VALIDATORS = ["Northwind", "Lumen", "Granite", "Helix", "Aurora", "Cobalt", "Juniper", "Vertex"]
VKEYS = {v: key("validator-" + v) for v in VALIDATORS}
TAKE = {v: t for v, t in zip(VALIDATORS, (0.09, 0.18, 0.18, 0.05, 0.12, 0.18, 0.1, 0.15))}
STATE, LOCK = {}, threading.Lock()  # coldkey -> {"free": τ, "stake": {(netuid, hotkey): amount}}

def account(cold):
    return STATE.setdefault(cold, {"free": 12.5, "stake": {(19, VKEYS["Northwind"]): 220.0, (64, VKEYS["Northwind"]): 31.5, (0, VKEYS["Helix"]): 2.0}})

def quote(netuid, tao_in=None, alpha_in=None):
    p, pool = PRICE[netuid], POOL_TAO[netuid]
    if tao_in is not None:
        fee = tao_in * 0.0005
        ideal = (tao_in - fee) / p
        got = ideal * pool / (pool + tao_in)
        return NS(tao=Bal(tao_in - fee), alpha=Bal(got), tao_fee=Bal(fee), alpha_fee=Bal(0), tao_slippage=Bal(0), alpha_slippage=Bal(ideal - got))
    fee = alpha_in * 0.0005
    ideal = (alpha_in - fee) * p
    got = ideal * pool / (pool + ideal)
    return NS(tao=Bal(got), alpha=Bal(alpha_in - fee), tao_fee=Bal(0), alpha_fee=Bal(fee), tao_slippage=Bal(ideal - got), alpha_slippage=Bal(0))

def amount(v, default):
    if v == "all" or v is None: return default
    return v.rao / RAO if hasattr(v, "rao") else float(v)

class FakeSubtensor:
    def __init__(self, network): self.network = network

    # ---- reads ----
    def read(self, name, **p):
        if name == "balance": return Bal(account(p["coldkey_ss58"])["free"])
        if name == "stake_for_coldkey":
            a = account(p["coldkey_ss58"])
            return [NS(netuid=n, hotkey=h, stake=Bal(v), is_registered=False) for (n, h), v in sorted(a["stake"].items()) if v > 0]
        if name == "owned_hotkeys": return []
        if name == "netuids_for_hotkey": return []
        if name == "uid": return None
        if name == "existential_deposit": return Bal(0.0000005)
        if name == "alpha_prices": return dict(PRICE)
        if name == "subnet_names": return dict(NAMES)
        if name == "quote_stake": return quote(p["netuid"], tao_in=p["amount_tao"])
        if name == "quote_unstake": return quote(p["netuid"], alpha_in=p["amount_alpha"])
        if name == "delegates":
            time.sleep(0.2)  # the real read is slow
            return [NS(hotkey=VKEYS[v], take=TAKE[v], nominators=40 + i * 7) for i, v in enumerate(VALIDATORS)]
        if name == "metagraph":
            n = p["netuid"]
            if n not in NAMES: raise ValueError(f"subnet {n} does not exist")
            hk = [VKEYS[v] for v in VALIDATORS] + [key(f"miner-{n}-{i}") for i in range(8)]
            stake = [int((900000 - i * 95000) * RAO) for i in range(8)] + [int(1.5 * RAO)] * 8
            return {"hotkeys": hk, "coldkeys": [key("owner-" + h) for h in hk], "validator_permit": [True] * 7 + [False] * 9,
                    "identities": [{"name": v} for v in VALIDATORS] + [None] * 8, "total_stake": stake, "alpha_stake": stake,
                    "alpha_dividends_per_hotkey": [(h, 1000 - i * 90 if i < 7 else 0) for i, h in enumerate(hk)]}
        raise KeyError(name)

    # ---- the SDK's transaction calls ----
    def plan(self, intent, wallet):
        cold = wallet.ss58_address
        f = {k: getattr(intent, k) for k in intent.__dataclass_fields__ if not k.isupper()}
        op = intent.op
        fee = {"add_stake": 0.00085, "remove_stake": 0.00065, "move_stake": 0.0011, "unstake_all": 0.00008, "transfer": 0.00008}[op]
        tol = f.get("rate_tolerance") or 0.05
        effects = {"add_stake": lambda: f"stake {f['amount_tao']} to {f['hotkey_ss58']} on netuid {f['netuid']} (fails if price moves >{tol:.2%})",
                   "remove_stake": lambda: f"unstake {f['amount_alpha']} from {f['hotkey_ss58']} on netuid {f['netuid']} (fails if price moves >{tol:.2%})",
                   "move_stake": lambda: f"move {f['amount_alpha']} from netuid {f['origin_netuid']} to netuid {f['dest_netuid']} (fails if price ratio moves >{tol:.2%})",
                   "unstake_all": lambda: f"unstake ALL from {f['hotkey_ss58']}",
                   "transfer": lambda: f"transfer {f['amount_tao']} to {f['dest_ss58']}"}[op]()
        warnings = ["removes the entire stake from this hotkey"] if op == "unstake_all" else []
        call = NS(op=op, args=f, cold=cold, data=b"\x07" + op.encode())
        return NS(op=op, call=call, fee=Bal(fee), effects=[effects], warnings=warnings, violations=[], ok=True, args=f, signer_address=cold)

    def prepare_call(self, call, *, address, **kw):
        return NS(call=call, address=address, payload_json={
            "address": address, "blockHash": "0x" + "ab" * 32, "genesisHash": "0x2f0555cc76fc2840a25a6ea3b9637146806f1f44b090c175ffde2a7e5ab36c03",
            "method": "0x" + call.data.hex(), "nonce": "0x00000007", "specVersion": "0x000001e6", "tip": "0x" + "00" * 16,
            "transactionVersion": "0x00000001", "era": "0x8606", "version": 4,
            "signedExtensions": ["CheckNonZeroSender", "CheckSpecVersion", "CheckTxVersion", "CheckGenesis", "CheckMortality", "CheckNonce",
                                 "CheckWeight", "ChargeTransactionPayment", "SubtensorTransactionExtension", "CheckMetadataHash"], "mode": 0})

    def submit_signature(self, unsigned, signature, **kw):
        sig = signature if isinstance(signature, bytes) else bytes.fromhex(signature.removeprefix("0x"))
        if not any(sig[1:] if len(sig) == 65 else sig):
            raise Exception("RPC error 1010: Invalid Transaction: Transaction has a bad signature")
        time.sleep(0.3)  # a block
        c = unsigned.call
        a, f = account(c.cold), c.args
        with LOCK:
            if c.op == "add_stake":
                tao = amount(f["amount_tao"], a["free"] - 0.001)
                if tao > a["free"]: return NS(success=False, message="Insufficient balance", error="SubtensorModule.NotEnoughBalanceToStake", extrinsic_id=None, explorer_url=None, fee=None, block_hash=None, data={})
                a["free"] -= tao + 0.00085
                k = (f["netuid"], f["hotkey_ss58"]); a["stake"][k] = a["stake"].get(k, 0) + quote(f["netuid"], tao_in=tao).alpha.rao / RAO
            elif c.op == "remove_stake":
                k = (f["netuid"], f["hotkey_ss58"]); al = amount(f["amount_alpha"], a["stake"].get(k, 0))
                a["stake"][k] = a["stake"].get(k, 0) - al; a["free"] += quote(f["netuid"], alpha_in=al).tao.rao / RAO - 0.00065
            elif c.op == "move_stake":
                k = (f["origin_netuid"], f["origin_hotkey_ss58"]); al = amount(f["amount_alpha"], a["stake"].get(k, 0))
                a["stake"][k] -= al
                tao = quote(f["origin_netuid"], alpha_in=al).tao.rao / RAO
                d = (f["dest_netuid"], f["dest_hotkey_ss58"]); a["stake"][d] = a["stake"].get(d, 0) + quote(f["dest_netuid"], tao_in=tao).alpha.rao / RAO
            elif c.op == "unstake_all":
                for k in [k for k in a["stake"] if k[1] == f["hotkey_ss58"]]:
                    a["free"] += quote(k[0], alpha_in=a["stake"].pop(k)).tao.rao / RAO
            elif c.op == "transfer":
                tao = amount(f["amount_tao"], a["free"] - 0.001); a["free"] -= tao + 0.00008
                account(f["dest_ss58"])["free"] += tao
        block = 9389200 + int(time.time()) % 1000
        return NS(success=True, message="Included in block", block_hash="0x" + "cd" * 32, extrinsic_id=f"{block}-0004",
                  explorer_url=f"https://taomarketcap.com/extrinsic/{block}-0004", fee=Bal(0.00085), error=None, data={})

def factory(network):
    return FakeSubtensor(network)
