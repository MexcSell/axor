"""Live on-chain collector: reads every subnet's metagraph from a Subtensor node on a loop,
derives miner economics, and keeps a 7-day history (backfilled from an archive node at start)."""
import json, logging, statistics, threading, time, urllib.request
from datetime import datetime, timezone

import bittensor as bt

from . import risk
from .store import Store

log = logging.getLogger("collector")
RAO = 1e9
DAY_BLOCKS = 7200
BLOCK_SEC = 12

def miner_emissions(raw):
    """Per-UID miner share of last-epoch emission (alpha rao), split out from validator dividends."""
    em, inc, div = raw["emission"], raw["incentives"], raw["dividends"]
    pure = [(e, i) for e, i, d in zip(em, inc, div) if i > 0 and d == 0]
    s_e, s_i = sum(e for e, _ in pure), sum(i for _, i in pure)
    k = s_e / s_i if s_i else None
    out = []
    for e, i, d in zip(em, inc, div):
        if i == 0: out.append(0.0)
        elif d == 0: out.append(float(e))
        elif k is not None: out.append(i * k)
        else: out.append(float(e) * i / (i + d))
    return out

def _text(v):
    if isinstance(v, (list, tuple)):
        return bytes(v).decode(errors="replace")
    return v or ""

def _f(x):
    """Plain float from SDK values that may be Balance-like dicts or ints."""
    if isinstance(x, dict):
        x = x.get("bits", x.get("value", 0))
    return float(x or 0)

class Collector:
    def __init__(self, store: Store, knowledge, seed=None, network="finney", archive="archive", interval=180):
        self.store, self.k, self.network, self.archive, self.interval = store, knowledge, network, archive, interval
        self.seed = {r["netuid"]: r for r in (seed or {}).get("rows", [])}
        self.seed_block = (seed or {}).get("head_block")
        self.state = {"block": None, "updated": None, "tao_usd": None, "subnets": [], "status": "starting"}
        self.version = 0
        self.cond = threading.Condition()
        self._usd_at = 0
        self._wake = threading.Event()
        self._st = None

    # ---------- lifecycle ----------
    def start(self):
        threading.Thread(target=self._loop, daemon=True, name="collector").start()
        threading.Thread(target=self.backfill, daemon=True, name="backfill").start()

    def _loop(self):
        while True:
            t = time.time()
            try:
                self.collect()
            except Exception as e:
                log.exception("collect failed")
                self.state["status"] = f"error: {e!r}"[:200]
                self._st = None
            self._wake.wait(max(15, self.interval - (time.time() - t)))
            self._wake.clear()

    def wait(self, version, timeout=25):
        with self.cond:
            self.cond.wait_for(lambda: self.version != version, timeout)
            return self.version

    def client(self):
        if self._st is None:
            self._st = bt.Subtensor(self.network)
        return self._st

    # ---------- price ----------
    def tao_usd(self):
        if time.time() - self._usd_at > 300:
            try:
                req = urllib.request.Request("https://api.coingecko.com/api/v3/simple/price?ids=bittensor&vs_currencies=usd",
                                             headers={"User-Agent": "subnet-scout"})
                self.state["tao_usd"] = json.load(urllib.request.urlopen(req, timeout=10))["bittensor"]["usd"]
                self._usd_at = time.time()
            except Exception as e:
                log.warning("tao price fetch failed: %r", e)
        return self.state["tao_usd"]

    # ---------- one collection pass ----------
    def collect(self):
        st = self.client()
        head = st.block
        now = time.time()
        try:
            head_ts = st.timestamp(head).timestamp()
        except Exception:
            head_ts = now
        netuids = sorted(s.netuid for s in st.subnets.all() if s.netuid != 0)
        regs = dict(st.query_map(("SubtensorModule", "RegistrationsThisInterval"), block=head))
        try:
            flows = st.subnets.subnet_tao_flows(block=head)
        except Exception:
            flows = {}
        usd = self.tao_usd()
        rows = []
        for u in netuids:
            try:
                mg = st.subnets.metagraph(u, block=head, commitments=False)
                if mg is None: continue
                rows.append(self._row(u, mg.raw, head, head_ts, regs.get(u, 0), flows.get(u, 0.0)))
            except Exception as e:
                log.warning("subnet %s failed: %r", u, e)
        total_em = sum(r["emission_day"] for r in rows) or 1
        for r in rows:
            r["emission_share"] = r["emission_day"] / total_em
        self.store.put([{"netuid": r["netuid"], "block": head, "ts": now, "price": r["price"],
                         "reg_cost": r["reg_cost"], "emission_day": r["emission_day"],
                         "top_miner": r["top_miner_live"], "second_miner": r["second_miner_live"],
                         "median_miner": r["median_miner_live"], "earning": r["earning_miners"],
                         "volume": r["volume_total"]} for r in rows])
        self._enrich(rows, now, usd)
        self.state = {"block": head, "updated": now, "tao_usd": usd, "subnets": rows, "status": "live"}
        with self.cond:
            self.version += 1
            self.cond.notify_all()
        log.info("collected %d subnets at block %d in %.1fs", len(rows), head, time.time() - now)
        if self.version % 50 == 1:
            self.store.prune()

    def _row(self, u, raw, head, now, regs_int, flow):
        ident = raw.get("identity") or {}
        name = ident.get("subnet_name") or _text(raw.get("name")) or f"SN{u}"
        tempo = raw["tempo"]
        alpha_in = _f(raw["alpha_in"])
        price = _f(raw["tao_in"]) / alpha_in if alpha_in else 0.0
        epochs_day = DAY_BLOCKS / (tempo + 1) if tempo else 0
        owner = raw["owner_hotkey"]
        daily, owner_d, payees = [], 0.0, []
        imm = raw["immunity_period"]
        for uid, (hk, m) in enumerate(zip(raw["hotkeys"], miner_emissions(raw))):
            v = m * epochs_day / RAO * price
            if hk == owner: owner_d += v
            elif v > 0:
                daily.append(v)
                rb = raw["block_at_registration"][uid]
                payees.append({"uid": uid, "hotkey": hk, "coldkey": raw["coldkeys"][uid],
                               "incentive": raw["incentives"][uid] / 65535 if raw["incentives"][uid] > 1 else raw["incentives"][uid],
                               "alpha_epoch": m / RAO, "tao_epoch": m / RAO * price, "tao_day": v,
                               "registered_at": now - (head - rb) * BLOCK_SEC, "immune": head - rb < imm})
        daily.sort(reverse=True)
        miner_total = sum(daily) + owner_d
        payees.sort(key=lambda p: p["tao_day"], reverse=True)
        # payout timing: emission accrues every block and is distributed at the end of each epoch
        since = raw["blocks_since_last_step"]
        last_at = now - since * BLOCK_SEC
        next_in = max(0, tempo + 1 - since)
        alpha_out = raw["alpha_out_emission"] / RAO
        prunable = sum(1 for hk, rb in zip(raw["hotkeys"], raw["block_at_registration"])
                       if hk != owner and head - rb >= imm)
        open_slots = raw["max_uids"] - raw["num_uids"]
        limit = raw["target_regs_per_interval"] * 3
        reg_allowed = bool(raw["registration_allowed"])
        created_block = raw["network_registered_at"]
        seed = self.seed.get(u, {})
        if seed.get("created_block") == created_block and seed.get("created_date"):
            created = seed["created_date"]
        else:
            created = datetime.fromtimestamp(now - (head - created_block) * BLOCK_SEC, timezone.utc).date().isoformat()
        kn = self.k["subnets"].get(str(u), {})
        validators = sum(1 for v in raw["validator_permit"] if v)
        return {
            "netuid": u, "name": name, "symbol": _text(raw.get("symbol")),
            "description": " ".join((ident.get("description") or "").split()),
            "links": {"github": ident.get("github_repo") or "", "web": ident.get("subnet_url") or "",
                      "discord": ident.get("discord") or "", "contact": ident.get("subnet_contact") or "",
                      "logo": ident.get("logo_url") or "",
                      "taostats": f"https://taostats.io/subnets/{u}"},
            "task": kn.get("task") or ident.get("description") or "",
            "miner_role": kn.get("miner_role", ""), "conditions": kn.get("conditions", ""),
            "field": kn.get("field", "Unknown"), "tier": kn.get("tier", "unknown"),
            "hardware": kn.get("hardware", ""), "software": kn.get("software", ["Bittensor btcli"]),
            "tempo": tempo, "emission_cycle_min": round((tempo + 1) * BLOCK_SEC / 60, 1),
            "immunity_blocks": imm, "immunity_hours": round(imm * BLOCK_SEC / 3600, 1),
            "price": price,
            "num_uids": raw["num_uids"], "max_uids": raw["max_uids"], "validators": validators,
            "earning_miners_live": len(daily),
            "top_miner_live": daily[0] if daily else 0.0,
            "second_miner_live": daily[1] if len(daily) > 1 else 0.0,
            "median_miner_live": statistics.median(daily) if daily else 0.0,
            "top_share": daily[0] / miner_total if miner_total and daily else 0.0,
            "owner_burn_share": owner_d / miner_total if miner_total else 0.0,
            "miner_pool_day": sum(daily),
            "reg_cost": raw["burn"] / RAO,
            "registration_allowed": reg_allowed,
            "open_slots": open_slots, "prunable_uids": prunable,
            "uid_available": reg_allowed and regs_int < limit and (open_slots > 0 or prunable > 0),
            "regs_this_interval": regs_int, "reg_rate_limit": limit,
            "emission_day": raw["tao_in_emission"] * DAY_BLOCKS / RAO,
            "tao_flow_day": flow * DAY_BLOCKS / RAO,
            "volume_total": _f(raw.get("subnet_volume")) / RAO,
            "created_block": created_block, "created_date": created,
            "age_days": max(0, (head - created_block) * BLOCK_SEC / 86400),
            "earning_miners": len(daily),
            "payout": {
                "last_block": raw["last_step"], "last_at": last_at,
                "next_block": raw["last_step"] + tempo + 1, "next_at": now + next_in * BLOCK_SEC,
                "blocks_since": since, "epochs_day": round(epochs_day, 2),
                "alpha_epoch": alpha_out * (tempo + 1), "tao_epoch": alpha_out * (tempo + 1) * price,
                "alpha_day": alpha_out * DAY_BLOCKS, "tao_day": alpha_out * DAY_BLOCKS * price,
                "tao_in_epoch": raw["tao_in_emission"] * (tempo + 1) / RAO,
                "pending_alpha": raw["pending_alpha_emission"] / RAO,
                "pending_tao": raw["pending_alpha_emission"] / RAO * price,
                "miner_pool_epoch": sum(daily) / epochs_day if epochs_day else 0.0,
                "owner_epoch": owner_d / epochs_day if epochs_day else 0.0,
            },
            "top_payees": payees[:15],
        }

    def _enrich(self, rows, now, usd):
        """24h-smoothed miner earnings, 7-day series and changes, USD values, risk flags."""
        hist = self.store.series(now - 7 * 86400 - 3600)
        for r in rows:
            born = now - r["age_days"] * 86400  # netuids are recycled: ignore the previous subnet's history
            h = [(t, v) for t, v in hist.get(r["netuid"], []) if t >= born]
            day = [v for t, v in h if t >= now - 86400]
            for key in ("top_miner", "second_miner", "median_miner"):
                vals = [v[key] for v in day if v[key] is not None]
                r[key] = statistics.fmean(vals) if len(vals) >= 3 else r[key + "_live"]
            em = [v["earning"] for v in day if v["earning"] is not None]
            r["earning_miners"] = round(statistics.fmean(em)) if len(em) >= 3 else r["earning_miners_live"]
            r["series"] = _downsample(h, now)
            r["price_change_7d"] = _change(h, "price", now - 7 * 86400)
            r["price_change_24h"] = _change(h, "price", now - 86400)
            r["emission_change_7d"] = _change(h, "emission_day", now - 7 * 86400)
            vol = [(t, v["volume"]) for t, v in h if v["volume"] is not None and t >= now - 86400 - 3600]
            r["volume_24h"] = vol[-1][1] - vol[0][1] if len(vol) >= 2 and vol[-1][0] - vol[0][0] > 6 * 3600 else None
            ed = r["payout"]["epochs_day"] or 1
            for key in ("top_miner", "second_miner", "median_miner"):
                r["payout"][key + "_epoch"] = r[key] / ed
            r["usd"] = {k: (r[k] * usd if usd else None) for k in ("top_miner", "second_miner", "median_miner", "reg_cost")}
            r["flags"] = risk.flags(r, usd)
            r["risk_level"] = risk.level(r["flags"])

    # ---------- 7-day history backfill from an archive node ----------
    def backfill(self, days=7, per_day=4):
        done = self.store.meta("backfill_block")
        try:
            st = bt.Subtensor(self.archive)
            head = st.block
            if done and head - int(done) < DAY_BLOCKS // per_day:
                return
            step = DAY_BLOCKS // per_day
            head_ts = st.timestamp(head).timestamp()
            self._seed_history(head, head_ts)
            for j in range(days * per_day, 0, -1):
                b = head - j * step
                m = lambda k: dict(_retry(lambda: st.query_map(("SubtensorModule", k), block=b)))
                tao, alpha, burn, em, vol = (m(k) for k in ("SubnetTAO", "SubnetAlphaIn", "Burn", "SubnetTaoInEmission", "SubnetVolume"))
                ts = head_ts - (head - b) * BLOCK_SEC
                self.store.put([{"netuid": u, "block": b, "ts": ts,
                                 "price": tao.get(u, 0) / alpha[u] if alpha.get(u) else None,
                                 "reg_cost": burn.get(u, 0) / RAO, "emission_day": em.get(u, 0) * DAY_BLOCKS / RAO,
                                 "volume": vol.get(u, 0) / RAO}
                                for u in burn if u != 0])
            self.store.meta("backfill_block", head)
            log.info("backfilled %d days of history", days)
            self._wake.set()  # re-collect now so trends appear without waiting a full interval
        except Exception:
            log.exception("backfill failed (trends will build up from live data)")

    def _seed_history(self, head, head_ts):
        """Bundled 24h-sampled miner economics: lets earnings show smoothed values from the first pass."""
        if not self.seed or not self.seed_block or self.store.meta("seeded"):
            return
        b = self.seed_block
        if head - b > 7 * DAY_BLOCKS:
            return
        rows = []
        for u, r in self.seed.items():
            if "error" in r: continue
            rows.append({"netuid": u, "block": b, "ts": head_ts - (head - b) * BLOCK_SEC,
                         "top_miner": r.get("top_miner_tao_24h"), "second_miner": r.get("second_miner_tao_24h"),
                         "median_miner": r.get("median_miner_tao_24h"), "earning": r.get("miners_nonzero_24h")})
        self.store.put(rows)
        self.store.meta("seeded", 1)

def _retry(f, waits=(20, 40, 80, 160, 300, 300)):
    for w in waits:
        try:
            return f()
        except Exception as e:
            log.warning("archive query failed (%r), retrying in %ss", e, w)
            time.sleep(w)
    return f()

def _change(h, key, since):
    pts = [(t, v[key]) for t, v in h if v[key] and t >= since]
    if len(pts) < 2 or pts[-1][0] - pts[0][0] < (time.time() - since) * 0.5:
        return None
    return pts[-1][1] / pts[0][1] - 1

def _downsample(h, now, buckets=28):
    """~6h buckets over 7 days for price, reg cost and emission (last value per bucket)."""
    out = {}
    width = 7 * 86400 / buckets
    for t, v in h:
        i = int((t - (now - 7 * 86400)) // width)
        if i < 0: continue
        out[min(i, buckets - 1)] = (t, v)
    pts = [out[i] for i in sorted(out)]
    return {"t": [round(t) for t, _ in pts],
            "price": [v["price"] for _, v in pts],
            "reg_cost": [v["reg_cost"] for _, v in pts],
            "emission_day": [v["emission_day"] for _, v in pts]}
