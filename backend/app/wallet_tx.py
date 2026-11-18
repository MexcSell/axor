"""Wallet transactions: stake, unstake, move stake, unstake all and send TAO, signed in the user's browser wallet.

Scout builds each transaction from public addresses with the bittensor SDK's intents, the user's wallet extension
(Talisman, SubWallet, Polkadot.js, Bittensor) shows and signs it, and Scout submits the signature. Keys never reach
Scout: the coldkey is an address-only signer here that refuses to sign.
- review: checks the request against the chain (free balance, the position, the chain's minimum stake: the SDK's
  plan doesn't), quotes the swap, and plans it (fee, effects, warnings; staking is slippage-protected at the
  tolerance the user picks). Returns the review and a token for this user, kept 20 minutes.
- prepare: the unsigned extrinsic for a token, with a fresh nonce and a mortal era (about 25 minutes to sign).
  A review older than 3 minutes is refused (409) so the page quotes again before the wallet opens.
- submit: the wallet's signature for that payload; Scout waits for the block and keeps the outcome as activity
  (and in the audit log). A token submits once.
- validators: a subnet's validators (permit holders by stake, with name, take and dividend share) to stake with.
Every review also carries the btcli command that does the same thing on the user's own machine.
"""
import logging, secrets, threading, time

from bittensor.intents import REGISTRY
from bittensor.result import BittensorError, ConnectionNotReady, RpcConnectionError
from fastapi import HTTPException
from pydantic import BaseModel, Field

from .wallet import RAO, SECRET_HINT, _addr, looks_secret, pubkey, subtensor

log = logging.getLogger("wallet.tx")
TOKEN_TTL = 20 * 60   # seconds a review's token lasts
FRESH = 180           # older reviews are quoted again before the wallet signs
MIN_STAKE = 0.002     # the chain's minimum stake or unstake, in TAO (plus the swap fee)
HEADROOM = 0.001      # TAO kept back for fees when spending "everything"
RATE = 30             # reviews per minute per user
VAL_TTL, TAKE_TTL, MAX_VALIDATORS = 300, 1800, 64
OPS = {"stake": "add_stake", "unstake": "remove_stake", "move": "move_stake", "unstake_all": "unstake_all", "send": "transfer"}
TITLE = {"stake": "Stake", "unstake": "Unstake", "move": "Move stake", "unstake_all": "Unstake all", "send": "Send"}

class TxIn(BaseModel):
    wallet_id: int
    op: str                          # stake | unstake | move | unstake_all | send
    netuid: int | None = None        # stake, unstake, move: the subnet (move: where it is now)
    hotkey: str | None = None        # the validator to stake with, or the position's hotkey
    dest_netuid: int | None = None   # move: to this subnet
    dest_hotkey: str | None = None   # move: to this validator
    dest: str | None = None          # send: the destination coldkey
    amount: float | None = Field(None, gt=0, le=1e9)  # TAO for stake and send, alpha for unstake and move
    all: bool = False                # everything: the free balance (minus fees) or the whole position
    slippage: float = Field(1.0, ge=0.1, le=20)       # percent the price may move before the swap fails

class TokenIn(BaseModel):
    token: str = Field(..., max_length=64)

class SignedIn(TokenIn):
    signature: str = Field(..., max_length=200)

class Watch:
    """The coldkey as an address-only signer: enough for the SDK to plan and prepare, never to sign."""
    crypto_type = 1  # sr25519; an ed25519 wallet's 65-byte signature says so itself

    def __init__(self, ss58): self.ss58_address, self.public_key = ss58, pubkey(ss58)

    def sign(self, payload): raise PermissionError("AXoR holds no keys: the browser wallet signs.")

def _need(value, what):
    if value is None: raise HTTPException(400, f"Pick {what}.")
    return value

def _offline(e):
    """A connection problem rather than a refused request."""
    return isinstance(e, (RpcConnectionError, ConnectionNotReady, OSError, TimeoutError))

def _tao(b):
    """A Balance (or None) in TAO."""
    return None if b is None else (b.rao / RAO if hasattr(b, "rao") else float(b))

class Transactions:
    def __init__(self, db, wallets):
        self.db, self.w = db, wallets
        self.lock, self._st = threading.Lock(), None          # reviews and payloads
        self.sub_lock, self._sub = threading.Lock(), None     # submissions (they wait for a block)
        self.pending, self.hits, self._vals, self._takes, self._ed = {}, {}, {}, (0, {}), None
        self._warming = False
        db.q("""CREATE TABLE IF NOT EXISTS wallet_txs (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, wallet_id INTEGER, op TEXT, title TEXT, detail TEXT,
                  amount REAL, unit TEXT, netuid INTEGER, status TEXT, extrinsic_id TEXT, extrinsic_hash TEXT, explorer_url TEXT,
                  fee REAL, error TEXT, created REAL)""")

    # ---------- chain access ----------
    def _call(self, fn, submit=False):
        lock, attr = (self.sub_lock, "_sub") if submit else (self.lock, "_st")
        with lock:
            try:
                if getattr(self, attr) is None: setattr(self, attr, subtensor(self.w.chain.network))
                return fn(getattr(self, attr))
            except Exception:
                setattr(self, attr, None)  # reconnect next time
                raise

    def _existential(self):
        if self._ed is None:
            try: self._ed = _tao(self.w.chain.read("existential_deposit"))
            except Exception: return 0.0000005
        return self._ed

    # ---------- validators ----------
    def _take_map(self):
        """Each delegate's take, from one slow read (seconds) cached half an hour."""
        at, takes = self._takes
        if time.time() - at < TAKE_TTL and takes: return takes
        try:
            takes = {d.hotkey: {"take": float(d.take), "nominators": d.nominators if isinstance(d.nominators, int) else len(d.nominators or [])}
                     for d in self.w.chain.read("delegates")}
            self._takes = (time.time(), takes)
        except Exception as e:
            log.warning("delegates read failed: %r", e)
        return takes

    def warm(self):
        """Read the delegates in the background so the first validator list doesn't wait for them."""
        if self._warming or self._takes[1]: return
        self._warming = True
        def go():
            try: self._take_map()
            finally: self._warming = False
        threading.Thread(target=go, daemon=True).start()

    def validators(self, netuid):
        self.w.known_subnet(netuid)
        hit = self._vals.get(netuid)
        if hit and time.time() - hit[0] < VAL_TTL: return hit[1]
        try: m = self.w.chain.read("metagraph", netuid=netuid)
        except Exception as e:
            log.warning("metagraph read failed for SN%s: %r", netuid, e)
            raise HTTPException(503, "Couldn't read this subnet's validators from the chain right now.")
        takes = self._take_map() if not self._warming else self._takes[1]
        div = dict(m.get("alpha_dividends_per_hotkey") or [])
        total = sum(div.values()) or 1
        ids = m.get("identities") or []
        rows = []
        for i, hk in enumerate(m["hotkeys"]):
            if not m["validator_permit"][i]: continue
            name = ((ids[i] if i < len(ids) else None) or {}).get("name") or None
            t = takes.get(hk) or {}
            rows.append({"hotkey": hk, "uid": i, "name": name, "stake": m["total_stake"][i] / RAO, "dividends": div.get(hk, 0) / total,
                         "take": t.get("take"), "nominators": t.get("nominators")})
        rows.sort(key=lambda r: -r["stake"])
        out = {"netuid": netuid, "validators": rows[:MAX_VALIDATORS], "count": len(rows), "takes": bool(takes)}
        if takes: self._vals[netuid] = (time.time(), out)
        return out

    # ---------- review ----------
    def _rate(self, me):
        now = time.time()
        hits = [t for t in self.hits.get(me["id"], []) if now - t < 60]
        if len(hits) >= RATE: raise HTTPException(429, "That's a lot of reviews. Wait a minute and try again.")
        self.hits[me["id"]] = hits + [now]

    def _gc(self):
        now = time.time()
        for k in [k for k, p in self.pending.items() if now - p["created"] > TOKEN_TTL]: self.pending.pop(k, None)

    def review(self, me, b: TxIn):
        self._rate(me); self._gc()
        if b.op not in OPS: raise HTTPException(400, "Unknown operation.")
        w = next((x for x in self.w._rows(me) if x["id"] == b.wallet_id), None)
        if not w: raise HTTPException(404, "That wallet doesn't exist.")
        cold, labels = w["coldkey"], {h["ss58"]: h["name"] for h in w["hotkeys"]}
        try: acct = self.w.chain.account(cold, list(labels), fresh=True)
        except Exception as e:
            log.warning("account read failed for %s: %r", cold, e)
            raise HTTPException(503, "Couldn't read this wallet from the chain right now. Try again in a minute.")
        free, tol = acct["free"], round(b.slippage / 100, 4)
        amount = None if b.all else b.amount
        if not b.all and amount is None and b.op != "unstake_all": raise HTTPException(400, "Enter an amount.")
        pos = lambda n, hk: next((p for p in acct["stake"] if p["netuid"] == n and p["hotkey"] == hk), None)
        blocks, warns, info = [], [], {}

        if b.op == "stake":
            n = _need(b.netuid, "a subnet"); self.w.known_subnet(n)
            hk = _addr(_need(b.hotkey, "a validator"), "The validator's hotkey")
            spend = amount if amount is not None else max(0.0, free - self._existential() - HEADROOM)
            if amount is not None and amount < MIN_STAKE: raise HTTPException(400, f"The chain's minimum stake is {MIN_STAKE} τ.")
            args = dict(hotkey_ss58=hk, netuid=n, amount_tao="all" if b.all else amount, slippage_protection=True, rate_tolerance=tol)
            info.update(netuid=n, hotkey=hk, amount=spend, unit="tao")
        elif b.op in ("unstake", "move"):
            n = _need(b.netuid, "a position"); hk = _addr(_need(b.hotkey, "a position"), "The position's hotkey")
            p = pos(n, hk)
            if not p: raise HTTPException(400, f"This wallet has no stake on SN{n} with that hotkey.")
            if amount is not None and amount > p["amount"] * (1 + 1e-9): raise HTTPException(400, f"That's more than the position: {p['amount']:,.4f} {'α' if n else 'τ'}.")
            info.update(netuid=n, hotkey=hk, amount=amount if amount is not None else p["amount"], unit="alpha" if n else "tao", position=p["amount"])
            if b.op == "unstake":
                args = dict(hotkey_ss58=hk, netuid=n, amount_alpha="all" if b.all else amount, slippage_protection=True, rate_tolerance=tol)
            else:
                dn = _need(b.dest_netuid, "where to move it"); self.w.known_subnet(dn)
                dhk = _addr(_need(b.dest_hotkey, "a validator to move it to"), "The destination validator's hotkey")
                if dn == n and dhk == hk: raise HTTPException(400, "Pick another subnet or validator: that's where the stake already is.")
                args = dict(origin_hotkey_ss58=hk, origin_netuid=n, dest_hotkey_ss58=dhk, dest_netuid=dn,
                            amount_alpha="all" if b.all else amount, slippage_protection=True, rate_tolerance=tol)
                info.update(dest_netuid=dn, dest_hotkey=dhk)
        elif b.op == "unstake_all":
            hk = _addr(_need(b.hotkey, "a hotkey"), "The hotkey")
            ps = [p for p in acct["stake"] if p["hotkey"] == hk]
            if not ps: raise HTTPException(400, "This wallet has no stake with that hotkey.")
            args = dict(hotkey_ss58=hk)
            info.update(hotkey=hk, positions=[{"netuid": p["netuid"], "amount": p["amount"]} for p in ps])
        else:  # send
            if looks_secret(b.dest or ""): raise HTTPException(400, SECRET_HINT)
            dest = _addr(_need(b.dest, "who to send to"), "The destination")
            if pubkey(dest) == pubkey(cold): raise HTTPException(400, "That's this wallet's own address.")
            spend = amount if amount is not None else max(0.0, free - self._existential() - HEADROOM)
            args = dict(dest_ss58=dest, amount_tao="all" if b.all else amount, keep_alive=True)
            info.update(dest=dest, amount=spend, unit="tao")

        try:
            plan = self._call(lambda st: st.plan(REGISTRY[OPS[b.op]](**args), Watch(cold)))
        except Exception as e:
            log.warning("plan failed (%s): %r", b.op, e)
            if _offline(e) or not isinstance(e, (ValueError, TypeError, BittensorError)):
                raise HTTPException(503, "Couldn't reach the chain to prepare this. Try again in a minute.")
            raise HTTPException(400, str(e)[:300])
        fee = _tao(plan.fee) or 0.0
        ed = self._existential()
        if b.op in ("stake", "send") and not b.all and info["amount"] + fee > free - ed:
            blocks.append(f"Not enough free balance: {free:,.6f} τ free, and this needs {info['amount'] + fee:,.6f} τ with the fee"
                          + (" (a wallet keeps a tiny balance to stay open)." if info["amount"] + fee <= free else "."))
        elif b.op in ("stake", "send") and b.all and info["amount"] <= (MIN_STAKE if b.op == "stake" else 0):
            blocks.append("Nothing to spend: the free balance only covers the fee.")
        elif fee > free:
            warns.append(f"The network fee (about {fee:,.6f} τ) is normally paid from free balance, which has {free:,.6f} τ.")
        blocks += [str(v) for v in plan.violations or []]
        quote = self._quote(b.op, info)
        token = secrets.token_urlsafe(24)
        review = {"token": token, "op": b.op, "title": TITLE[b.op], "wallet": {"id": w["id"], "name": w["name"], "coldkey": cold},
                  **info, "all": b.all, "slippage": b.slippage, "fee": fee, "free": free, "quote": quote,
                  "effects": list(plan.effects or []), "warnings": warns + list(plan.warnings or []), "blocks": blocks, "ok": not blocks and bool(plan.ok),
                  "command": command(b.op, w, info, b.all, tol, self.w.chain.network), "fresh_for": FRESH, "expires_in": TOKEN_TTL}
        self.pending[token] = {"user": me["id"], "username": me["username"], "wallet_id": w["id"], "coldkey": cold, "plan": plan,
                               "review": review, "created": time.time(), "unsigned": None}
        return review

    def _quote(self, op, i):
        """What the swap gives back, for the review (None when the chain can't quote it)."""
        try:
            if op == "stake" and i["amount"] > 0:
                q = self.w.quote(i["netuid"], i["amount"], "stake")
                return {"receive": q["alpha"], "unit": "alpha" if i["netuid"] else "tao", "impact": q["impact"], "price": q["price"]}
            if op == "unstake" and i["amount"] > 0:
                q = self.w.quote(i["netuid"], i["amount"], "unstake")
                return {"receive": q["tao"], "unit": "tao", "impact": q["impact"], "price": q["price"]}
            if op == "move" and i["amount"] > 0:
                if i["netuid"] == i["dest_netuid"]: return {"receive": i["amount"], "unit": i["unit"], "impact": 0, "price": None}
                out = self.w.quote(i["netuid"], i["amount"], "unstake") if i["netuid"] else {"tao": i["amount"], "impact": 0}
                into = self.w.quote(i["dest_netuid"], out["tao"], "stake") if i["dest_netuid"] else {"alpha": out["tao"], "impact": 0}
                return {"receive": into["alpha"], "unit": "alpha" if i["dest_netuid"] else "tao", "impact": 1 - (1 - out["impact"]) * (1 - into["impact"]),
                        "via_tao": out["tao"], "price": None}
        except HTTPException:
            return None
        return None

    def _token(self, me, token):
        self._gc()
        p = self.pending.get(token)
        if not p or p["user"] != me["id"]: raise HTTPException(404, "This review expired. Review the transaction again.")
        return p

    # ---------- prepare and submit ----------
    def prepare(self, me, token):
        p = self._token(me, token)
        if not p["review"]["ok"]: raise HTTPException(400, "Fix what the review flagged first.")
        if time.time() - p["created"] > FRESH: raise HTTPException(409, "Prices may have moved since this review. Quoting again…")
        try: u = self._call(lambda st: st.prepare_call(p["plan"].call, address=p["coldkey"]))
        except Exception as e:
            log.warning("prepare failed: %r", e)
            raise HTTPException(503, "Couldn't reach the chain to prepare this. Try again in a minute.")
        p["unsigned"] = u
        return {"payload": u.payload_json, "address": p["coldkey"]}

    def submit(self, me, token, signature, ip=""):
        p = self._token(me, token)
        if p["unsigned"] is None: raise HTTPException(400, "Prepare the transaction first.")
        sig = signature.strip().removeprefix("0x")
        try: raw = bytes.fromhex(sig)
        except ValueError: raise HTTPException(400, "The wallet returned a signature AXoR can't read.")
        if len(raw) not in (64, 65): raise HTTPException(400, "The wallet returned a signature of the wrong length.")
        self.pending.pop(token, None)  # one submission per review, whatever happens next
        r = p["review"]
        try:
            res = self._call(lambda st: st.submit_signature(p["unsigned"], raw, wait_for_inclusion=True, wait_for_finalization=False), submit=True)
            ok, message, err = bool(res.success), res.message or "", None if res.success else (str(res.error or res.message) or "The chain rejected it.")
            ext = {"extrinsic_id": res.extrinsic_id, "explorer_url": res.explorer_url, "fee": _tao(res.fee), "block_hash": res.block_hash,
                   "extrinsic_hash": getattr(res, "extrinsic_hash", None) or (res.data or {}).get("extrinsic_hash")}
        except Exception as e:
            log.warning("submit failed (%s): %r", r["op"], e)
            ok, message, err, ext = False, "", friendly(e), {"extrinsic_id": None, "explorer_url": None, "fee": None, "block_hash": None, "extrinsic_hash": None}
        self.w.chain.cache.pop(p["coldkey"], None)  # balances changed
        detail = describe(r)
        self.db.q("""INSERT INTO wallet_txs (user_id, wallet_id, op, title, detail, amount, unit, netuid, status, extrinsic_id, extrinsic_hash,
                     explorer_url, fee, error, created) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (me["id"], p["wallet_id"], r["op"], r["title"], detail, r.get("amount"), r.get("unit"), r.get("netuid"), "ok" if ok else "failed",
                   ext["extrinsic_id"], ext["extrinsic_hash"], ext["explorer_url"], ext["fee"], err, time.time()))
        self.db.log("wallet.tx" if ok else "wallet.tx_fail", me["username"], r["wallet"]["coldkey"], ip, f"{detail}{' · ' + ext['extrinsic_id'] if ext['extrinsic_id'] else ''}{' · ' + err if err else ''}"[:300])
        return {"ok": ok, "message": message, "error": err, **ext, "title": r["title"], "detail": detail, "activity": self.activity(me, p["wallet_id"])}

    def activity(self, me, wallet_id=None):
        q, args = "SELECT * FROM wallet_txs WHERE user_id=?", [me["id"]]
        if wallet_id is not None: q, args = q + " AND wallet_id=?", args + [wallet_id]
        return [{k: r[k] for k in ("id", "wallet_id", "op", "title", "detail", "amount", "unit", "netuid", "status", "extrinsic_id", "extrinsic_hash",
                                   "explorer_url", "fee", "error", "created")}
                for r in self.db.q(q + " ORDER BY id DESC LIMIT 50", tuple(args))]

def friendly(e):
    """A chain or RPC error, in words."""
    s = str(e)
    for k, msg in (("bad signature", "The signature didn't match: the wallet signed for another account or network."),
                   ("Invalid Transaction", "The chain refused the transaction" + (f" ({s.split(':', 1)[-1].strip()[:120]})" if ":" in s else ".")),
                   ("Stale", "The transaction went stale (another one from this wallet went first). Review it again."),
                   ("Outdated", "The transaction went stale (another one from this wallet went first). Review it again."),
                   ("Inability to pay", "Not enough free balance to pay the fee."),
                   ("ancient", "The signature took too long: the transaction expired. Review it again.")):
        if k.lower() in s.lower(): return msg
    return s[:300] or "The chain rejected the transaction."

def describe(r):
    """One line for the activity list and the audit log."""
    a, u = r.get("amount"), "α" if r.get("unit") == "alpha" else "τ"
    amt = "everything" if r.get("all") and r["op"] != "unstake_all" else (f"{a:,.6g} {u}" if a is not None else "")
    short = lambda x: f"{x[:5]}…{x[-4:]}" if x else ""
    if r["op"] == "stake": return f"Stake {amt} on SN{r['netuid']} with {short(r['hotkey'])}"
    if r["op"] == "unstake": return f"Unstake {amt} from SN{r['netuid']} ({short(r['hotkey'])})"
    if r["op"] == "move": return f"Move {amt} from SN{r['netuid']} to SN{r['dest_netuid']} ({short(r['dest_hotkey'])})"
    if r["op"] == "unstake_all": return f"Unstake everything from {short(r['hotkey'])} ({len(r.get('positions') or [])} subnets)"
    return f"Send {amt} to {short(r['dest'])}"

def command(op, w, i, all_, tol, network):
    """The btcli command (the SDK's) that does the same from the user's own machine."""
    net = network if network in ("finney", "test") else "finney"
    base = f"--wallet {w['name']} --network {net}"
    amt = lambda flag: "--all" if all_ else f"{flag} {i['amount']:.9g}"
    if op == "stake": return f"btcli stake add {base} --hotkey {i['hotkey']} --netuid {i['netuid']} {amt('--amount-tao')} --rate-tolerance {tol}"
    if op == "unstake": return f"btcli stake remove {base} --hotkey {i['hotkey']} --netuid {i['netuid']} {amt('--amount-alpha')} --rate-tolerance {tol}"
    if op == "move": return (f"btcli stake move {base} --origin-hotkey {i['hotkey']} --origin-netuid {i['netuid']} --dest-hotkey {i['dest_hotkey']} "
                             f"--dest-netuid {i['dest_netuid']} {amt('--amount-alpha')} --rate-tolerance {tol}")
    if op == "unstake_all": return f"btcli stake unstake-all {base} --hotkey {i['hotkey']}"
    return f"btcli wallet transfer {base} --dest {i['dest']} {amt('--amount-tao')}"
