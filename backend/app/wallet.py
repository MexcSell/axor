"""Wallets: each user's Bittensor wallets, tracked by their public SS58 addresses only.

- A wallet is a name (the btcli wallet name), a coldkey address and any number of named hotkey addresses.
  Seed phrases, private keys and wallet files never reach the server: anything that looks like one is refused.
- The page shows each wallet's free balance, its stake per subnet and hotkey (alpha, marked to TAO at the
  collector's prices), the hotkeys the coldkey owns on chain, and every subnet each hotkey is registered on (UID).
- Transactions (wallet_tx.py): stake, unstake, move stake, unstake all and send TAO are built here from the public
  addresses, signed in the user's browser wallet extension (Talisman, SubWallet, Polkadot.js, Bittensor) and
  submitted by Scout. The keys stay in the extension; each transaction also has its btcli command.
- Runbooks: per subnet, the user's choices for the command builder (wallet, hotkey, network, stake amount,
  which steps to show) plus their own extra steps (e.g. an agent upload). The page fills btcli commands from them,
  which the user runs on their own machine.
- Terminal (wallet_term.py): the real btcli, read-only, in a sandbox per user that holds the tracked wallets as
  public keys only. Commands that sign open the matching transaction sheet instead.
- Chain reads use a connection of their own (not the collector's) and are cached per coldkey for a minute. Subnet
  names and alpha prices come from the collector, or from the chain until its first snapshot lands.
- WALLET_CHAIN_FACTORY ("module:function", given the network) supplies the chain client instead of bt.Subtensor,
  so tests can run the wallet against a scripted chain.
"""
import hashlib, importlib, json, logging, os, re, threading, time

import bittensor as bt
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

log = logging.getLogger("wallet")
RAO = 1e9
MAX_WALLETS = 20
MAX_HOTKEYS = 16
MAX_STEPS = 12
CACHE_SEC = 60
NETWORKS = ("finney", "test")
NAME = re.compile(r"[A-Za-z0-9_.-]{1,32}")
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
SECRET_HINT = ("That looks like a seed phrase or private key. AXoR only needs public SS58 addresses (they start with 5). "
               "Never paste a recovery phrase into any website. If you did, move your funds to a new wallet.")

def valid_ss58(s):
    """A 32-byte public key in SS58 (any network prefix below 64) with a correct blake2b checksum."""
    if not isinstance(s, str) or not 46 <= len(s) <= 48 or any(c not in B58 for c in s): return False
    n = 0
    for c in s: n = n * 58 + B58.index(c)
    raw = n.to_bytes(35, "big") if n.bit_length() <= 280 else b""
    if len(raw) != 35 or raw[0] >= 64: return False
    return hashlib.blake2b(b"SS58PRE" + raw[:33], digest_size=64).digest()[:2] == raw[33:]

def looks_secret(s):
    """12+ dictionary-like words in a row (a mnemonic) or 32 bytes of hex (a raw private key / seed)."""
    s = s or ""
    return bool(re.search(r"(?:\b[a-z]{3,8}\b[\s,]+){11,}\b[a-z]{3,8}\b", s) or re.search(r"\b(0x)?[0-9a-fA-F]{64}\b", s))

def _name(s, what):
    s = (s or "").strip()
    if not NAME.fullmatch(s): raise HTTPException(400, f"{what} must be 1–32 characters: letters, digits, _ . -")
    return s

def _addr(s, what):
    s = (s or "").strip()
    if looks_secret(s): raise HTTPException(400, SECRET_HINT)
    if not valid_ss58(s): raise HTTPException(400, f"{what} isn't a valid SS58 address. Copy it from `btcli wallet list`.")
    return s

class HotkeyIn(BaseModel):
    name: str
    ss58: str

class WalletIn(BaseModel):
    name: str
    coldkey: str
    hotkeys: list[HotkeyIn] = []
    note: str = Field("", max_length=300)

class StepIn(BaseModel):
    title: str = Field("", max_length=120)
    cmd: str = Field(..., max_length=2000)

class RunbookIn(BaseModel):
    wallet_id: int | None = None
    hotkey: str | None = None
    network: str = "finney"
    amount: float | None = Field(None, ge=0, le=1e6)
    prefix: str = Field("", max_length=300)
    hidden: list[str] = []
    steps: list[StepIn] = []

def subtensor(network):
    """A chain client: bt.Subtensor, or the WALLET_CHAIN_FACTORY one (tests)."""
    if os.getenv("WALLET_CHAIN_FACTORY"):
        mod, fn = os.getenv("WALLET_CHAIN_FACTORY").split(":")
        return getattr(importlib.import_module(mod), fn)(network)
    return bt.Subtensor(network)

def pubkey(ss58):
    """The 32-byte public key inside a valid SS58 address."""
    n = 0
    for c in ss58: n = n * 58 + B58.index(c)
    return n.to_bytes(35, "big")[1:33]

class Chain:
    """Its own Subtensor connection, used one call at a time, with a short per-coldkey cache."""
    def __init__(self, network):
        self.network, self._st, self.lock, self.cache, self._market = network, None, threading.Lock(), {}, (0, None)

    def read(self, name, **p):
        with self.lock:
            try:
                if self._st is None: self._st = subtensor(self.network)
                return self._st.read(name, **p)
            except Exception:
                self._st = None  # reconnect next time
                raise

    def market(self):
        """Subnet names and alpha prices from the chain, for when the collector has no snapshot yet (cached a minute)."""
        at, m = self._market
        if m is None or time.time() - at > CACHE_SEC:
            try: m = {"price": dict(self.read("alpha_prices")), "names": dict(self.read("subnet_names"))}
            except Exception as e:
                log.warning("market read failed: %r", e)
                m = m or {"price": {}, "names": {}}
            self._market = (time.time(), m)
        return m

    def account(self, coldkey, hotkeys, fresh=False):
        """Free balance, stake positions, owned hotkeys and each hotkey's registrations ({netuid: uid})."""
        hit = self.cache.get(coldkey)
        if hit and not fresh and time.time() - hit[0] < CACHE_SEC and set(hotkeys) <= set(hit[1]["regs"]): return hit[1]
        free = self.read("balance", coldkey_ss58=coldkey).rao / RAO
        stake = [{"netuid": p.netuid, "hotkey": p.hotkey, "amount": p.stake.rao / RAO, "registered": bool(p.is_registered)}
                 for p in self.read("stake_for_coldkey", coldkey_ss58=coldkey) if p.stake.rao]
        owned = list(self.read("owned_hotkeys", coldkey_ss58=coldkey) or [])
        regs = {}
        for hk in list(dict.fromkeys([*hotkeys, *owned]))[:max(MAX_HOTKEYS, len(hotkeys))]:
            regs[hk] = {n: self.read("uid", hotkey_ss58=hk, netuid=n) for n in self.read("netuids_for_hotkey", hotkey_ss58=hk) or []}
        out = {"free": free, "stake": stake, "owned": owned, "regs": regs, "at": time.time()}
        self.cache[coldkey] = (time.time(), out)
        return out

class Wallets:
    def __init__(self, db, data, network):
        self.db, self.data, self.chain = db, data, Chain(network)
        db.q("""CREATE TABLE IF NOT EXISTS wallets (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, coldkey TEXT, hotkeys TEXT, note TEXT, created REAL)""")
        db.q("CREATE TABLE IF NOT EXISTS wallet_runbooks (user_id INTEGER, netuid INTEGER, data TEXT, updated REAL, PRIMARY KEY (user_id, netuid))")

    def _rows(self, me):
        return [{**w, "hotkeys": json.loads(w["hotkeys"] or "[]")}
                for w in self.db.q("SELECT id, name, coldkey, hotkeys, note, created FROM wallets WHERE user_id=? ORDER BY created", (me["id"],))]

    def _wallet(self, me, wid):
        w = self.db.q("SELECT id FROM wallets WHERE id=? AND user_id=?", (wid, me["id"]), one=True)
        if not w: raise HTTPException(404, "That wallet doesn't exist.")

    def view(self, me, fresh=False):
        s = self.data()
        return {"wallets": [self._enrich(w, s, fresh) for w in self._rows(me)], "tao_usd": s.get("tao_usd"), "networks": NETWORKS,
                "network": self.chain.network if self.chain.network in NETWORKS else "finney"}

    def _enrich(self, w, s, fresh=False):
        """One stored wallet plus what the chain says about it, marked to TAO at the collector's prices."""
        price = {r["netuid"]: r["price"] for r in s["subnets"]}
        names = {r["netuid"]: r["name"] for r in s["subnets"]}
        if not s["subnets"]:  # the collector's first snapshot hasn't landed: ask the chain
            m = self.chain.market()
            price, names = m["price"], {n: v for n, v in m["names"].items() if n}
        paid = {p["hotkey"]: (r["netuid"], p) for r in s["subnets"] for p in r.get("top_payees") or []}
        try:
            a = self.chain.account(w["coldkey"], [h["ss58"] for h in w["hotkeys"]], fresh)
        except Exception as e:
            log.warning("wallet read failed for %s: %r", w["coldkey"], e)
            return {**w, "error": "Couldn't read this wallet from the chain right now. Try again in a minute."}
        label = {h["ss58"]: h["name"] for h in w["hotkeys"]}
        stake = []
        for p in a["stake"]:
            px = 1.0 if p["netuid"] == 0 else price.get(p["netuid"])
            stake.append({**p, "subnet": names.get(p["netuid"], "Root" if p["netuid"] == 0 else f"SN{p['netuid']}"),
                          "hotkey_name": label.get(p["hotkey"]), "tao": None if px is None else p["amount"] * px})
        stake.sort(key=lambda p: -(p["tao"] or 0))
        hks = [{"name": label.get(hk), "ss58": hk, "owned": hk in a["owned"], "declared": hk in label,
                "registrations": [{"netuid": n, "subnet": names.get(n, f"SN{n}"), "uid": uid,
                                   "tao_day": paid[hk][1]["tao_day"] if paid.get(hk, (None,))[0] == n else None}
                                  for n, uid in sorted(regs.items())]}
               for hk, regs in a["regs"].items()]
        hks.sort(key=lambda h: (not h["declared"], not h["registrations"], h["name"] or "~"))
        staked = sum(p["tao"] or 0 for p in stake)
        return {**w, "free": a["free"], "staked_tao": staked, "total_tao": a["free"] + staked,
                "stake": stake, "hotkey_info": hks, "read_at": a["at"]}

    def save(self, me, w: WalletIn, wid=None):
        if looks_secret(w.note): raise HTTPException(400, SECRET_HINT)
        name, cold = _name(w.name, "Wallet name"), _addr(w.coldkey, "The coldkey")
        if len(w.hotkeys) > MAX_HOTKEYS: raise HTTPException(400, f"Up to {MAX_HOTKEYS} hotkeys per wallet.")
        hks, seen = [], set()
        for h in w.hotkeys:
            hn = _name(h.name, "Hotkey name")
            if hn in seen: raise HTTPException(400, f"Two hotkeys are named “{hn}”.")
            seen.add(hn)
            hks.append({"name": hn, "ss58": _addr(h.ss58, f"Hotkey “{hn}”")})
        if wid is None:
            n = self.db.q("SELECT COUNT(*) n FROM wallets WHERE user_id=?", (me["id"],), one=True)["n"]
            if n >= MAX_WALLETS: raise HTTPException(400, f"You can track up to {MAX_WALLETS} wallets.")
            self.db.q("INSERT INTO wallets (user_id, name, coldkey, hotkeys, note, created) VALUES (?,?,?,?,?,?)",
                      (me["id"], name, cold, json.dumps(hks), w.note.strip(), time.time()))
        else:
            self._wallet(me, wid)
            self.db.q("UPDATE wallets SET name=?, coldkey=?, hotkeys=?, note=? WHERE id=? AND user_id=?",
                      (name, cold, json.dumps(hks), w.note.strip(), wid, me["id"]))
        self.chain.cache.pop(cold, None)
        return self.view(me)

    def delete(self, me, wid):
        self._wallet(me, wid)
        self.db.q("DELETE FROM wallets WHERE id=? AND user_id=?", (wid, me["id"]))
        return self.view(me)

    def known_subnet(self, netuid):
        """A subnet the collector knows (any netuid before its first snapshot: the chain checks those)."""
        subs = self.data()["subnets"]
        if not 0 <= netuid < 65536 or (subs and netuid != 0 and not any(r["netuid"] == netuid for r in subs)):
            raise HTTPException(404, "That subnet doesn't exist.")

    def quote(self, netuid, amount, side="stake"):
        """A swap quote: staking `amount` TAO (side stake) or unstaking `amount` alpha (side unstake)."""
        self.known_subnet(netuid)
        if not 0 < amount <= 1e9: raise HTTPException(400, "Enter an amount above 0.")
        if netuid == 0:  # root stake is TAO: no pool, no slippage
            return {"netuid": 0, "side": side, "tao": amount, "alpha": amount, "fee_tao": 0, "fee_alpha": 0, "slippage_alpha": 0, "slippage_tao": 0, "price": 1.0, "impact": 0}
        try: q = self.chain.read("quote_stake" if side == "stake" else "quote_unstake", netuid=netuid, **({"amount_tao": amount} if side == "stake" else {"amount_alpha": amount}))
        except Exception as e:
            log.warning("%s quote failed: %r", side, e)
            raise HTTPException(503, "Couldn't get a quote from the chain right now.")
        r = lambda b: b.rao / RAO
        tao, alpha = (amount, r(q.alpha)) if side == "stake" else (r(q.tao), amount)
        slip = r(q.alpha_slippage) if side == "stake" else r(q.tao_slippage)
        out = r(q.alpha) if side == "stake" else r(q.tao)
        return {"netuid": netuid, "side": side, "tao": tao, "alpha": alpha, "fee_tao": r(q.tao_fee), "fee_alpha": r(q.alpha_fee),
                "slippage_alpha": r(q.alpha_slippage), "slippage_tao": r(q.tao_slippage), "price": tao / alpha if alpha else None,
                "impact": slip / (out + slip) if out + slip else 0}

    def runbook(self, me, netuid):
        r = self.db.q("SELECT data, updated FROM wallet_runbooks WHERE user_id=? AND netuid=?", (me["id"], netuid), one=True)
        return {"netuid": netuid, **(json.loads(r["data"]) if r else {}), "updated": r and r["updated"]}

    def save_runbook(self, me, netuid, b: RunbookIn):
        if not any(r["netuid"] == netuid for r in self.data()["subnets"]): raise HTTPException(404, "That subnet doesn't exist.")
        if b.network not in NETWORKS: raise HTTPException(400, "Network must be finney or test.")
        if b.wallet_id is not None: self._wallet(me, b.wallet_id)
        if b.hotkey: _name(b.hotkey, "Hotkey name")
        if len(b.steps) > MAX_STEPS: raise HTTPException(400, f"Up to {MAX_STEPS} custom steps.")
        if any(looks_secret(x) for x in [b.prefix, *(s.title for s in b.steps), *(s.cmd for s in b.steps)]): raise HTTPException(400, SECRET_HINT)
        data = b.model_dump()
        data["steps"] = [s for s in data["steps"] if s["cmd"].strip()]
        data["hidden"] = [h for h in data["hidden"] if NAME.fullmatch(h)][:20]
        self.db.q("INSERT OR REPLACE INTO wallet_runbooks (user_id, netuid, data, updated) VALUES (?,?,?,?)",
                  (me["id"], netuid, json.dumps(data), time.time()))
        return self.runbook(me, netuid)

class TermIn(BaseModel):
    line: str = Field(..., max_length=500)
    wallet_id: int | None = None
    cols: int = Field(110, ge=40, le=400)  # the terminal's width in characters

def build(db, require, data, ip=lambda req: "", data_dir=None):
    from .wallet_term import COMPLETE, FLAGS, Btcli
    from .wallet_tx import SignedIn, TokenIn, Transactions, TxIn
    r = APIRouter(prefix="/api/wallet")
    w = Wallets(db, data, os.getenv("SUBTENSOR_NETWORK", "finney"))
    t = Btcli(w, data_dir or os.getenv("DATA_DIR", "var"))
    tx = Transactions(db, w)
    r.state = {"wallets": w, "terminal": t, "tx": tx}

    @r.get("")
    def view(req: Request, refresh: bool = False):
        me = require(req)
        out = w.view(me, refresh)
        if out["wallets"]: tx.warm()
        return out

    # ---------- transactions: reviewed here, signed in the browser wallet, submitted here ----------
    @r.get("/validators")
    def validators(netuid: int, req: Request):
        require(req)
        return tx.validators(netuid)

    @r.post("/tx/review")
    def review(b: TxIn, req: Request):
        return tx.review(require(req), b)

    @r.post("/tx/prepare")
    def prepare(b: TokenIn, req: Request):
        return tx.prepare(require(req), b.token)

    @r.post("/tx/submit")
    def submit(b: SignedIn, req: Request):
        return tx.submit(require(req), b.token, b.signature, ip(req))

    @r.get("/activity")
    def activity(req: Request, wallet_id: int | None = None):
        return tx.activity(require(req), wallet_id)

    @r.post("")
    def add(x: WalletIn, req: Request):
        return w.save(require(req), x)

    @r.put("/{wid}")
    def update(wid: int, x: WalletIn, req: Request):
        return w.save(require(req), x, wid)

    @r.delete("/{wid}")
    def delete(wid: int, req: Request):
        return w.delete(require(req), wid)

    @r.get("/quote")
    def quote(netuid: int, amount: float, req: Request, side: str = "stake"):
        require(req)
        if side not in ("stake", "unstake"): raise HTTPException(400, "side is stake or unstake.")
        return w.quote(netuid, amount, side)

    @r.post("/term")
    def term(b: TermIn, req: Request):
        return t.run(require(req), b.line, b.wallet_id, b.cols)

    @r.get("/term")
    def term_info(req: Request):
        """What Tab completes, and where commands run."""
        require(req)
        return {"commands": COMPLETE, "flags": FLAGS, "network": w.chain.network, "btcli": bool(t.exe), "version": getattr(bt, "__version__", "")}

    @r.get("/runbook/{netuid}")
    def runbook(netuid: int, req: Request):
        return w.runbook(require(req), netuid)

    @r.put("/runbook/{netuid}")
    def save_runbook(netuid: int, b: RunbookIn, req: Request):
        return w.save_runbook(require(req), netuid, b)

    return r
