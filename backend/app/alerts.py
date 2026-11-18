"""Notifications, subnet news and the dashboard.

A watcher wakes after every collection pass and turns changes into alerts. Alerts are global rows; each
user's preferences and workspace decide which ones they see:
- new_subnet:  a netuid registered (or re-registered) since the last pass
- emission:    a subnet's emission up or down by EMISSION_MOVE or more vs ~24h ago (meaningful share only)
- opportunity: a subnet starts qualifying: realistic earnings >= OPP_RATIO x running cost, estimated
               top-miner chance >= OPP_CHANCE, a UID available, no scam/avoid flags
- fund:        TAO price, alpha price and registration cost moves over 24h, and a daily digest of TAO flows
- news:        GitHub releases (or recent commits) of subnet repos, and on-chain identity changes
               (renames, new website/repo, registration opened or closed). News always lands in the feed;
               it alerts only for subnets in the user's workspace.
The first pass after a fresh start records a baseline instead of alerting on everything already there.
"""
import json, logging, os, re, statistics, threading, time, urllib.error, urllib.request
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .workspace import brief

log = logging.getLogger("alerts")
KINDS = ("new_subnet", "emission", "opportunity", "fund", "news")
DEFAULT_PREFS = {**{k: True for k in KINDS}, "workspace_only": False, "browser": False}
EMISSION_MOVE = 0.25
MIN_SHARE = 0.002      # emission share below which moves are noise
TAO_MOVE = 0.05
ALPHA_MOVE = 0.20
OPP_RATIO, OPP_CHANCE = 2.0, 0.5
KEEP_ALERTS_DAYS, KEEP_NEWS_DAYS = 30, 120
NEWS_HOURS = float(os.getenv("NEWS_REFRESH_HOURS", "6"))
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GH_REPO = re.compile(r"https?://(?:www\.)?github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?(?:[/#?].*)?$")

def top_chance(r):
    """Rough odds (0-1) that a capable newcomer climbs into the paid top 10: how many miners earn at all,
    how many of today's top 10 are themselves recent registrants, and how spread out rewards are.
    A heuristic for ranking, not a probability anyone measured."""
    miners = max(1, r["num_uids"] - r["validators"])
    if not r["earning_miners"]: return 0.0
    earn = min(1.0, r["earning_miners"] / miners)
    top = (r.get("top_payees") or [])[:10]
    fresh = min(1.0, 2 * sum(1 for p in top if p["immune"]) / len(top)) if top else 0.0
    return round(min(1.0, 0.45 * earn + 0.35 * fresh + 0.2 * (1 - r["top_share"])), 3)

def _ago(points, now, hours=24):
    """Value from the newest point at least `hours` old (allowing 4h of slack for sparse history)."""
    old = [v for t, v in points if t <= now - (hours - 4) * 3600 and v]
    return old[-1] if old else None

def _day(ts=None):
    return datetime.fromtimestamp(ts or time.time(), timezone.utc).strftime("%Y-%m-%d")

def _ts(iso):
    try: return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except Exception: return time.time()

def _plain(md, n=400):
    t = re.sub(r"<[^>]+>|!\[[^\]]*\]\([^)]*\)", "", md or "")
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)
    t = " ".join(re.sub(r"[#*_`>|]+", " ", t).split())
    return t[:n] + ("…" if len(t) > n else "")

class RateLimited(Exception):
    def __init__(self, reset=None):
        self.reset = reset

class PrefsIn(BaseModel):
    new_subnet: bool | None = None
    emission: bool | None = None
    opportunity: bool | None = None
    fund: bool | None = None
    news: bool | None = None
    workspace_only: bool | None = None
    browser: bool | None = None

class ReadIn(BaseModel):
    id: int

class Alerts:
    def __init__(self, db, collector, tiers):
        self.db, self.c, self.tiers = db, collector, tiers
        self._sig, self._lock = (None, {}), threading.Lock()
        self.on_new = None  # called with each newly raised alert (Slack auto-posting)
        db.q("""CREATE TABLE IF NOT EXISTS alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, netuid INTEGER,
                  title TEXT, body TEXT, level TEXT, url TEXT, key TEXT UNIQUE)""")
        db.q("""CREATE TABLE IF NOT EXISTS news (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, netuid INTEGER, source TEXT,
                  title TEXT, body TEXT, url TEXT, key TEXT UNIQUE)""")
        db.q("CREATE TABLE IF NOT EXISTS alert_prefs (user_id INTEGER PRIMARY KEY, prefs TEXT, last_read INTEGER DEFAULT 0)")
        db.q("CREATE TABLE IF NOT EXISTS alert_state (k TEXT PRIMARY KEY, v TEXT)")

    def start(self):
        threading.Thread(target=self._watch, daemon=True, name="alerts").start()
        if NEWS_HOURS > 0:
            threading.Thread(target=self._news_loop, daemon=True, name="news").start()

    # ---------- state ----------
    def _get(self, k):
        r = self.db.q("SELECT v FROM alert_state WHERE k=?", (k,), one=True)
        return json.loads(r["v"]) if r else None

    def _set(self, k, v):
        self.db.q("INSERT OR REPLACE INTO alert_state VALUES (?,?)", (k, json.dumps(v)))

    def add(self, kind, netuid, title, body="", level="info", key=None, url=None, ts=None):
        if key and self.db.q("SELECT 1 FROM alerts WHERE key=?", (key,), one=True): return
        self.db.q("INSERT OR IGNORE INTO alerts (ts, kind, netuid, title, body, level, url, key) VALUES (?,?,?,?,?,?,?,?)",
                  (ts or time.time(), kind, netuid, title, body, level, url, key))
        if self.on_new:
            try: self.on_new({"kind": kind, "netuid": netuid, "title": title, "body": body, "url": url})
            except Exception: log.exception("alert hook failed")

    def news(self, netuid, source, title, body="", url=None, ts=None, key=None, alert=True, update=False):
        new = not self.db.q("SELECT 1 FROM news WHERE key=?", (key,), one=True)
        if not new:
            if update: self.db.q("UPDATE news SET title=?, body=?, ts=? WHERE key=?", (title, body, ts or time.time(), key))
            return
        self.db.q("INSERT OR IGNORE INTO news (ts, netuid, source, title, body, url, key) VALUES (?,?,?,?,?,?,?)",
                  (ts or time.time(), netuid, source, title, body, url, key))
        if alert: self.add("news", netuid, title, body, "info", "news:" + key, url, ts)

    # ---------- per-subnet signals (cached per collection pass) ----------
    def signals(self):
        st = self.c.state
        with self._lock:
            if self._sig[0] == (self.c.version, st["updated"]): return self._sig[1]
            rows, usd, now = st["subnets"], st["tao_usd"], st["updated"] or time.time()
            hist = self.c.store.series(now - 30 * 3600)
            out = {}
            for r in rows:
                born = now - r["age_days"] * 86400
                h = [(t, v) for t, v in hist.get(r["netuid"], []) if t >= born]
                em0 = _ago([(t, v["emission_day"]) for t, v in h], now)
                reg0 = _ago([(t, v["reg_cost"]) for t, v in h], now)
                b = brief(r, self.tiers, usd)["budget"]
                monthly, gross = b["monthly"]["typical"], b["earnings"]["gross_month_usd"]
                ratio = gross / monthly if monthly and gross is not None else None
                chance = top_chance(r)
                out[r["netuid"]] = {
                    "netuid": r["netuid"], "ratio": ratio, "chance": chance, "monthly": monthly, "gross": gross,
                    "net": b["net_month_usd"], "emission_prev": em0,
                    "em_chg_24h": r["emission_day"] / em0 - 1 if em0 else None,
                    "reg_chg_24h": r["reg_cost"] / reg0 - 1 if reg0 and r["reg_cost"] else None,
                    # earnings-to-cost (capped so free-to-run subnets don't swamp it) times the top-miner chance
                    "score": min(ratio, 10) * chance if ratio else 0,
                    "qualifies": bool(ratio and ratio >= OPP_RATIO and chance >= OPP_CHANCE and r["uid_available"]
                                      and r["risk_level"] not in ("scam", "avoid")),
                }
            self._sig = ((self.c.version, st["updated"]), out)
            return out

    # ---------- watcher ----------
    def _watch(self):
        v = self.c.version
        while True:
            nv = self.c.wait(v, 300)
            if nv == v: continue
            v = nv
            try: self.scan()
            except Exception: log.exception("alert scan failed")

    def scan(self):
        st = self.c.state
        rows, usd, now = st["subnets"], st["tao_usd"], st["updated"] or time.time()
        if not rows: return
        sig, day, name = self.signals(), _day(now), {r["netuid"]: r["name"] for r in rows}
        label = lambda n: f"SN{n} {name.get(n, '')}".strip()

        # new subnets and on-chain identity news
        known, seen = self._get("subnets"), {}
        for r in rows:
            n = r["netuid"]
            cur = {"created": r["created_block"], "name": r["name"], "github": r["links"]["github"], "web": r["links"]["web"], "reg": r["registration_allowed"]}
            seen[str(n)] = cur
            k = (known or {}).get(str(n))
            if known is None: continue
            if not k or k["created"] != cur["created"]:
                if r["age_days"] <= 3:  # don't flag a backlog if the watcher was off for a while
                    body = f"{r['field']} · registration {r['reg_cost']:.4g} τ · {r['emission_day']:.3g} τ/day emission so far."
                    self.add("new_subnet", n, f"New subnet: {label(n)}", body, "info", f"new:{n}:{cur['created']}")
                    self.news(n, "chain", f"{label(n)} registered", body, r["links"]["taostats"], key=f"chain:new:{n}:{cur['created']}", alert=False)
                continue
            if cur["name"] != k["name"] and cur["name"] and k["name"]:
                self.news(n, "chain", f"SN{n} renamed from {k['name']} to {cur['name']}", key=f"chain:name:{n}:{cur['name']}")
            if cur["github"] and cur["github"] != k["github"]:
                self.news(n, "chain", f"{label(n)} set its code repository", cur["github"], cur["github"], key=f"chain:gh:{n}:{cur['github']}")
            if cur["web"] and cur["web"] != k["web"]:
                self.news(n, "chain", f"{label(n)} set its website", cur["web"], cur["web"], key=f"chain:web:{n}:{cur['web']}")
            if cur["reg"] != k["reg"]:
                what = "opened" if cur["reg"] else "closed"
                self.news(n, "chain", f"{label(n)} {what} registration", key=f"chain:reg:{n}:{what}:{day}")
        self._set("subnets", seen)
        if known is None: log.info("alerts: baseline recorded for %d subnets", len(seen))

        # emission moves, alpha price and registration cost moves
        for r in rows:
            n, s = r["netuid"], sig.get(r["netuid"], {})
            if r.get("emission_share", 0) < MIN_SHARE: continue
            c = s.get("em_chg_24h")
            if c is not None and abs(c) >= EMISSION_MOVE:
                up = c > 0
                self.add("emission", n, f"{label(n)}: emission {'up' if up else 'down'} {abs(c):.0%} in 24h",
                         f"{s['emission_prev']:.3g} → {r['emission_day']:.3g} τ/day ({r['emission_share']:.1%} of all emission).",
                         "good" if up else "warn", f"em:{n}:{'up' if up else 'down'}:{day}")
            p = r.get("price_change_24h")
            if p is not None and abs(p) >= ALPHA_MOVE:
                self.add("fund", n, f"{label(n)}: alpha price {'up' if p > 0 else 'down'} {abs(p):.0%} in 24h",
                         f"Now {r['price']:.4g} τ per alpha.", "good" if p > 0 else "warn", f"alpha:{n}:{p > 0}:{day}")
            g = s.get("reg_chg_24h")
            if g is not None and (g >= 1 or g <= -0.5):
                self.add("fund", n, f"{label(n)}: registration {'doubled' if g >= 1 else 'halved'} in 24h" if abs(g) < 3 else f"{label(n)}: registration cost {g:+.0%} in 24h",
                         f"Now {r['reg_cost']:.4g} τ" + (f" (${r['reg_cost'] * usd:,.2f})." if usd else "."), "info" if g < 0 else "warn", f"reg:{n}:{g > 0}:{day}")

        # opportunities: alert when a subnet starts qualifying
        qual, prev = {n for n, s in sig.items() if s["qualifies"]}, self._get("opportunities")
        if prev is not None:
            for n in sorted(qual - set(prev)):
                s = sig[n]
                self.add("opportunity", n, f"Opportunity: {label(n)}",
                         f"Realistic earnings about {s['ratio']:.1f}× running cost (${s['gross']:,.0f} vs ${s['monthly']:,.0f}/month), "
                         f"top-miner chance about {s['chance']:.0%}, UID available.", "good", f"opp:{n}:{day}")
        self._set("opportunities", sorted(qual))

        # TAO price history (for the 24h move) and the daily flow digest
        tao = [p for p in (self._get("tao") or []) if p[0] >= now - 50 * 3600]
        if usd and (not tao or now - tao[-1][0] >= 900): tao.append([now, usd])
        self._set("tao", tao)
        old = _ago(tao, now)
        if usd and old and abs(usd / old - 1) >= TAO_MOVE:
            c = usd / old - 1
            self.add("fund", None, f"TAO {'up' if c > 0 else 'down'} {abs(c):.1%} in 24h", f"${old:,.2f} → ${usd:,.2f}",
                     "good" if c > 0 else "warn", f"tao:{c > 0}:{day}")
        flows = sorted((r for r in rows if r.get("tao_flow_day")), key=lambda r: r["tao_flow_day"])
        if len(flows) >= 6 and datetime.fromtimestamp(now, timezone.utc).hour >= 12:
            fmt = lambda xs: ", ".join(f"SN{r['netuid']} {r['tao_flow_day']:+,.1f}" for r in xs)
            self.add("fund", None, "Daily TAO flows", f"Biggest inflows (τ/day): {fmt(flows[::-1][:3])}. Biggest outflows: {fmt(flows[:3])}.",
                     "info", f"flows:{day}")

        if self.c.version % 40 == 1:
            self.db.q("DELETE FROM alerts WHERE ts < ?", (now - KEEP_ALERTS_DAYS * 86400,))
            self.db.q("DELETE FROM news WHERE ts < ?", (now - KEEP_NEWS_DAYS * 86400,))

    # ---------- GitHub news ----------
    def _news_loop(self):
        time.sleep(90)
        while True:
            wait = NEWS_HOURS * 3600
            try: wait = self.fetch_news() or wait
            except Exception: log.exception("news fetch failed")
            time.sleep(wait)

    def _gh(self, path, etags):
        """GET a GitHub API path. Returns parsed JSON, None when unchanged (304, free against the rate
        limit), [] when missing, or raises RateLimited."""
        h = {"Accept": "application/vnd.github+json", "User-Agent": "subnet-scout", "X-GitHub-Api-Version": "2022-11-28"}
        if GITHUB_TOKEN: h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
        if path in etags: h["If-None-Match"] = etags[path]
        try:
            with urllib.request.urlopen(urllib.request.Request("https://api.github.com" + path, headers=h), timeout=15) as resp:
                if resp.headers.get("ETag"): etags[path] = resp.headers["ETag"]
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code == 304: return None
            if e.code == 429 or (e.code == 403 and e.headers.get("X-RateLimit-Remaining") == "0"):
                raise RateLimited(float(e.headers.get("X-RateLimit-Reset") or 0) or None)
            return []

    def fetch_news(self):
        """One round over every subnet repo, least recently checked first. Returns seconds until the next
        round when GitHub's rate limit cut this one short (so the rest are picked up when it resets)."""
        rows, now = self.c.state["subnets"], time.time()
        repos = {}
        for r in rows:
            m = GH_REPO.match(r["links"]["github"] or "")
            if m: repos.setdefault(f"{m[1]}/{m[2]}", []).append(r)
        etags, checked, has_rel = self._get("etags") or {}, self._get("news_checked") or {}, self._get("news_has_releases") or {}
        seeded = self._get("news_seeded") is not None  # until one full round is done, fill the feed without alerting
        wait = None
        try:
            for repo, subs in sorted(repos.items(), key=lambda kv: checked.get(kv[0], 0)):
                r = subs[0]
                label = f"SN{r['netuid']} {r['name']}"
                rel = self._gh(f"/repos/{repo}/releases?per_page=5", etags)
                if rel:
                    for x in rel:
                        if x.get("draft") or not x.get("published_at"): continue
                        ts = _ts(x["published_at"])
                        self.news(r["netuid"], "release", f"{label} released {x.get('name') or x['tag_name']}", _plain(x.get("body")),
                                  x.get("html_url"), ts, f"gh:rel:{x['id']}", alert=seeded and ts > now - 2 * 86400)
                    has_rel[repo] = True
                elif rel == []: has_rel[repo] = False
                checked[repo] = time.time()
                if has_rel.get(repo, True): continue
                # no releases: summarise recent commits instead (unchanged lists come back as a free 304)
                commits = self._gh(f"/repos/{repo}/commits?per_page=20", etags)
                by_day = {}
                for x in commits or []:
                    ts = _ts(((x.get("commit") or {}).get("committer") or {}).get("date", ""))
                    if ts >= now - 7 * 86400: by_day.setdefault(_day(ts), []).append((ts, x))
                for d, xs in by_day.items():
                    msgs = [(x["commit"]["message"] or "").splitlines()[0][:120] for _, x in xs]
                    self.news(r["netuid"], "commits", f"{label}: {len(xs)} commit{'s' if len(xs) > 1 else ''} to {repo} on {d}",
                              "; ".join(msgs[:5]), f"https://github.com/{repo}/commits", max(t for t, _ in xs),
                              f"gh:commits:{repo}:{d}", alert=False, update=True)
        except RateLimited as e:
            wait = max(120, min(NEWS_HOURS * 3600, (e.reset or now + 3600) - time.time() + 30))
            log.warning("GitHub rate limit reached; news resumes in %d min (set GITHUB_TOKEN for more)", wait // 60)
        self._set("etags", etags)
        self._set("news_checked", checked)
        self._set("news_has_releases", has_rel)
        if wait is None: self._set("news_seeded", 1)
        return wait

    # ---------- per-user reading ----------
    def _workspace(self, me):
        return {r["netuid"] for r in self.db.q("SELECT netuid FROM workspace_subnets WHERE user_id=?", (me["id"],))}

    def prefs(self, me):
        r = self.db.q("SELECT prefs, last_read FROM alert_prefs WHERE user_id=?", (me["id"],), one=True)
        if not r:  # a new reader starts with the last day's alerts unread, not the whole backlog
            top = self.db.q("SELECT COALESCE(MAX(id), 0) m FROM alerts WHERE ts < ?", (time.time() - 86400,), one=True)["m"]
            self.db.q("INSERT OR IGNORE INTO alert_prefs VALUES (?,?,?)", (me["id"], json.dumps(DEFAULT_PREFS), top))
            return {**DEFAULT_PREFS}, top
        return {**DEFAULT_PREFS, **json.loads(r["prefs"] or "{}")}, r["last_read"]

    def set_prefs(self, me, p: PrefsIn):
        cur, _ = self.prefs(me)
        cur.update({k: v for k, v in p.model_dump().items() if v is not None})
        self.db.q("UPDATE alert_prefs SET prefs=? WHERE user_id=?", (json.dumps(cur), me["id"]))
        return cur

    def _visible(self, me):
        p, last = self.prefs(me)
        mine = self._workspace(me)
        def ok(a):
            if not p.get(a["kind"], True): return False
            if a["kind"] == "news": return a["netuid"] in mine
            if p["workspace_only"] and a["kind"] in ("emission", "fund") and a["netuid"] is not None: return a["netuid"] in mine
            return True
        return ok, p, last, mine

    def feed(self, me, limit=30, before=None):
        ok, p, last, _ = self._visible(me)
        rows = self.db.q("SELECT id, ts, kind, netuid, title, body, level, url FROM alerts WHERE id < ? ORDER BY id DESC LIMIT 500",
                         (before or 2 ** 62,))
        vis = [a for a in rows if ok(a)]
        unread = sum(1 for a in vis if a["id"] > last) if not before else None
        return {"items": vis[:max(1, min(limit, 100))], "unread": unread, "last_read": last, "prefs": p,
                "more": len(vis) > limit}

    def read(self, me, upto):
        self.prefs(me)
        self.db.q("UPDATE alert_prefs SET last_read=MAX(last_read, ?) WHERE user_id=?", (upto, me["id"]))
        return {"ok": True}

    def news_feed(self, me, netuid=None, limit=30, before=None, mine_only=False):
        rows = self.db.q("SELECT id, ts, netuid, source, title, body, url FROM news " +
                         ("WHERE netuid=? " if netuid is not None else "") + "ORDER BY ts DESC LIMIT 400",
                         (netuid,) if netuid is not None else ())
        if mine_only:
            mine = self._workspace(me)
            rows = [r for r in rows if r["netuid"] in mine]
        if before: rows = [r for r in rows if r["ts"] < before]
        return {"items": rows[:max(1, min(limit, 100))], "more": len(rows) > limit}

    # ---------- dashboard ----------
    def dashboard(self, me):
        st = self.c.state
        rows, usd = st["subnets"], st["tao_usd"]
        if not rows: return {"ready": False}
        sig = self.signals()
        tao = self._get("tao") or []
        old = _ago(tao, st["updated"] or time.time())
        big = [r for r in rows if r.get("emission_share", 0) >= MIN_SHARE / 2]
        pick = lambda xs, f, n=5: [{"netuid": r["netuid"], "value": f(r)} for r in xs[:n]]
        em = sorted((r for r in big if sig[r["netuid"]]["em_chg_24h"] is not None), key=lambda r: sig[r["netuid"]]["em_chg_24h"])
        px = sorted((r for r in big if r.get("price_change_24h") is not None), key=lambda r: r["price_change_24h"])
        fl = sorted((r for r in rows if r.get("tao_flow_day")), key=lambda r: r["tao_flow_day"])
        opp = sorted((s for s in sig.values() if s["score"] > 0 and s["ratio"] >= 1), key=lambda s: -s["score"])
        rmap = {r["netuid"]: r for r in rows}
        opp = [s for s in opp if rmap[s["netuid"]]["uid_available"] and rmap[s["netuid"]]["risk_level"] not in ("scam", "avoid")][:6]
        vol = [r["volume_24h"] for r in rows if r.get("volume_24h") is not None]
        _, p, _, mine = self._visible(me)
        return {
            "ready": True, "updated": st["updated"], "block": st["block"],
            "tao": {"usd": usd, "change_24h": usd / old - 1 if usd and old else None,
                    "series": [v for _, v in tao[-96:]]},
            "network": {
                "subnets": len(rows), "new_7d": sum(1 for r in rows if r["age_days"] <= 7),
                "emission_day": sum(r["emission_day"] for r in rows),
                "flow_in": sum(r["tao_flow_day"] for r in rows if (r.get("tao_flow_day") or 0) > 0),
                "flow_out": sum(r["tao_flow_day"] for r in rows if (r.get("tao_flow_day") or 0) < 0),
                "volume_24h": sum(vol) if vol else None,
                "open_regs": sum(1 for r in rows if r["uid_available"]),
                "median_reg": statistics.median([r["reg_cost"] for r in rows]),
            },
            "movers": {
                "emission_up": pick(em[::-1], lambda r: sig[r["netuid"]]["em_chg_24h"]),
                "emission_down": pick(em, lambda r: sig[r["netuid"]]["em_chg_24h"]),
                "price_up": pick(px[::-1], lambda r: r["price_change_24h"]),
                "price_down": pick(px, lambda r: r["price_change_24h"]),
                "inflow": pick(fl[::-1], lambda r: r["tao_flow_day"]),
                "outflow": pick(fl, lambda r: r["tao_flow_day"]),
            },
            "opportunities": [{k: s[k] for k in ("netuid", "ratio", "chance", "net", "monthly", "gross", "score")} for s in opp],
            "workspace": [{k: sig[n][k] for k in ("netuid", "ratio", "chance", "net", "em_chg_24h")} for n in sorted(mine) if n in sig],
            "alerts": self.feed(me, 8)["items"],
            "news": self.news_feed(me, limit=8, mine_only=p["workspace_only"])["items"],
        }

def build(db, require, collector, tiers):
    r = APIRouter(prefix="/api")
    al = Alerts(db, collector, tiers)
    r.state = {"alerts": al}

    @r.get("/alerts")
    def feed(req: Request, limit: int = 30, before: int | None = None):
        return al.feed(require(req), limit, before)

    @r.post("/alerts/read")
    def read(b: ReadIn, req: Request):
        return al.read(require(req), b.id)

    @r.get("/alerts/prefs")
    def prefs(req: Request):
        return al.prefs(require(req))[0]

    @r.put("/alerts/prefs")
    def set_prefs(p: PrefsIn, req: Request):
        return al.set_prefs(require(req), p)

    @r.get("/news")
    def news(req: Request, netuid: int | None = None, limit: int = 30, before: float | None = None):
        return al.news_feed(require(req), netuid, limit, before)

    @r.get("/dashboard")
    def dashboard(req: Request):
        return al.dashboard(require(req))

    return r
