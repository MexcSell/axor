"""My subnets → Command center: the Bittensor division's control room over every campaign and competition team of the user's
(mining-command.js draws it inside My subnets). Competition-first: subnet → competition → performance → team → experiments →
evaluation → approval → deployment → monitoring → rewards. Agents are the workforce; competitions are the operating units.

- Measured numbers only. The competition's evaluator score and the rest of the off-chain metrics come from the evaluator (or
  the miner) through an ingest key, from the user's own entries, and from the Lab's scored checks (mining_lab.py); on-chain
  rank and rewards come from My subnets' snapshots (mh_points, the latest sample). Nothing is estimated or filled in: a number
  nobody measured shows as "connect …".
- Performance Lab (per competition team): score, rank, correctness, success rate, latency P50/P95/P99, throughput, error
  rate, uptime and cost per successful task over time, the on-chain rank of the campaign's miners, the Lab's base scores.
  The competition's own metric comes first (settable per team); latency, errors and cost are constraints next to it.
- Experiment Center: idea → proposal → sandbox → evaluation → recommendation → approval → production → monitoring. The
  evaluation compares repeated baseline and candidate runs (mean, spread, noise band): one run never recommends anything.
  The recommendation is the Evidence Reviewer's, independent of whoever proposed it: rule checks first (enough runs, the
  primary metric better beyond noise, no constraint worse beyond noise), then, if a model is connected, a structured read of
  the evidence that can only make the verdict stricter. Approval goes through the Company's gateway (company.py: bound to the
  evidence's SHA-256, expires, consumed once; a deploy is handed off, never executed by AXoR). The user records the deploy
  they carried out; monitoring compares what the evaluator reports since with the evaluation, and a rollback is recorded
  the same way (the previous version becomes the active one again).
- Miners: each miner of a campaign (its hotkeys on chain, or registered by hand) with its public identity, version and
  configuration (never secrets), hardware, health and logs the miner reports, on-chain state apart from off-chain metrics,
  and its deployment and rollback history.
- Rewards: on-chain τ a day for the user's miners (and dollars at the collector's price), competition payouts and the costs
  the user enters (compute, hosting, infrastructure, other), model tokens (and dollars at a rate the user sets), sandbox and
  Workflow dollars; net, and expected against realized. A high score isn't treated as profit.
- Approval Center: every production or external action waiting for the user, wherever it comes from: deploy approvals of
  experiments (and the rest of the Company's), My subnets actions on a miner, Workflow merges.
- Monitoring: silent or failing miners, stale evaluators, regressions after a deploy, critical My subnets alerts, stuck teams.
- Agents: every competition-team agent, filtered by subnet, competition, squad and status, each linking to its team.
"""
import hashlib, json, logging, math, re, secrets, statistics, threading, time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .agents import _schema
from .secretbox import fingerprint
from .task_lifecycle import not_dropped  # D-018: dropped work isn't completed work
from .mining import _clip, _validator, ranked
from .mining_status import Status
from .wallet import SECRET_HINT, looks_secret

log = logging.getLogger("mining.command")
DAY, WEEK = 86400, 7 * 86400
# metric: label, unit, better ("up" or "down"). Shares are 0..1; latency in milliseconds; cost in dollars.
METRICS = {
    "score": ("Evaluator score", "", "up"),
    "rank": ("Competition rank", "#", "down"),
    "leader_score": ("Leader's score", "", "up"),  # the top miner's evaluator score, so Top miner can show the gap
    "correctness": ("Correctness", "%", "up"),
    "success_rate": ("Task success rate", "%", "up"),
    "latency_p50": ("Latency P50", "ms", "down"),
    "latency_p95": ("Latency P95", "ms", "down"),
    "latency_p99": ("Latency P99", "ms", "down"),
    "throughput": ("Throughput", "/min", "up"),
    "error_rate": ("Error rate", "%", "down"),
    "uptime": ("Uptime", "%", "up"),
    "cost_task": ("Cost per successful task", "$", "down"),
}
CONSTRAINTS = ("latency_p95", "error_rate", "cost_task", "uptime", "correctness")
STAGES = ("idea", "proposal", "sandbox", "evaluation", "recommendation", "approval", "production", "monitoring")
STAGE_LABEL = {"idea": "Idea", "proposal": "Proposal", "sandbox": "Sandbox", "evaluation": "Evaluation", "recommendation": "Recommendation",
               "approval": "Approval", "production": "Production", "monitoring": "Monitoring"}
COST_KINDS = {"compute": "Compute", "hosting": "Hosting", "infra": "Infrastructure", "model_api": "Model API (outside AXoR)", "other": "Other",
              "payout": "Competition payout (income)"}
PERIODS = {"day": 1, "month": 30.4, "once": None}
MIN_RUNS = 3  # runs a side before an evaluation can recommend anything
SILENT_MIN = 15  # a miner that reported health and then went quiet this long is silent
STALE_H = 24  # an evaluator that reported and then nothing for this long is stale
HEALTH_KEEP = 500  # health reports kept per miner
INGEST_PER_HOUR = 600
CACHE = 8  # seconds the dashboard is kept per user (the page polls it)
POINTS = 3000  # measurements a Performance Lab answer carries (the latest)
MAX_EXPERIMENTS = 200
SS58 = re.compile(r"^5[1-9A-HJ-NP-Za-km-z]{46,47}$")
STR = {"type": "string"}
REVIEW = _schema({"verdict": {"type": "string", "enum": ["recommend", "hold", "reject"]}, "summary": STR,
                  "concerns": {"type": "array", "items": STR}, "checks": {"type": "array", "items": STR}},
                 ["verdict", "summary", "concerns", "checks"])
REVIEW_SYSTEM = """You are the Evidence Reviewer of a Bittensor mining operation. You did not propose this experiment and you
have no stake in it. Read the evidence and say whether the candidate should go to production.

Rules: optimize the competition's own evaluation metric first; latency, error rate, cost and uptime are constraints. A
difference inside the noise band is not an improvement. Too few runs, missing baselines, a candidate measured on different
tasks or conditions than the baseline, or a constraint that got worse are reasons to hold. Never invent numbers: if something
isn't measured, say it isn't. The rule checks already ran; you may be stricter than them, never looser.
verdict: recommend (deploy it), hold (needs more evidence), reject (worse or not worth it). summary: two or three sentences.
concerns: what could make the result wrong. checks: what you verified in the numbers."""


def _now(): return time.time()
def _j(x): return json.dumps(x, separators=(",", ":"), sort_keys=True, ensure_ascii=False, default=str)
def _sha(x): return hashlib.sha256((x if isinstance(x, str) else _j(x)).encode()).hexdigest()
def _load(s, d):
    try: return json.loads(s) if s else d
    except (TypeError, ValueError): return d
def _num(x):
    try: v = float(x)
    except (TypeError, ValueError): return None
    return v if math.isfinite(v) else None


def stats(values):
    v = [x for x in values if x is not None]
    if not v: return None
    return {"n": len(v), "mean": statistics.fmean(v), "sd": statistics.stdev(v) if len(v) > 1 else None, "min": min(v), "max": max(v)}


def compare(base, cand, primary, min_runs=MIN_RUNS):
    """Baseline runs against candidate runs, metric by metric: the means, the difference, and whether it's beyond noise (two
    standard errors of the difference). Runs are {metric: value} dicts."""
    out = {}
    for k in METRICS:
        a, b = stats([_num(r.get(k)) for r in base]), stats([_num(r.get(k)) for r in cand])
        if not a or not b: continue
        diff, better = b["mean"] - a["mean"], METRICS[k][2]
        if a["n"] < 2 or b["n"] < 2: band, verdict = None, "too_few"
        else:
            band = 2 * math.sqrt((a["sd"] or 0) ** 2 / a["n"] + (b["sd"] or 0) ** 2 / b["n"])
            good = diff > 0 if better == "up" else diff < 0
            verdict = "noise" if abs(diff) <= band else "better" if good else "worse"
        out[k] = {"base": a, "cand": b, "diff": diff, "rel": diff / abs(a["mean"]) if a["mean"] else None, "band": band, "verdict": verdict,
                  "primary": k == primary, "enough": a["n"] >= min_runs and b["n"] >= min_runs}
    return out


def rule_review(cmp, primary, artifact, min_runs=MIN_RUNS):
    """The checks every candidate passes before anyone recommends it."""
    reasons, verdict = [], "recommend"
    p = cmp.get(primary)
    if not p:
        return {"verdict": "hold", "reasons": [f"{METRICS[primary][0]} isn't measured on both sides."]}
    if not p["enough"]:
        verdict = "hold"; reasons.append(f"{METRICS[primary][0]}: {p['base']['n']} baseline and {p['cand']['n']} candidate runs; {min_runs} a side are needed.")
    if p["verdict"] == "worse": verdict = "reject"; reasons.append(f"{METRICS[primary][0]} is worse beyond noise.")
    elif p["verdict"] == "noise": verdict = "hold" if verdict != "reject" else verdict; reasons.append(f"{METRICS[primary][0]}'s difference is inside the noise band.")
    elif p["verdict"] == "too_few": verdict = "hold" if verdict != "reject" else verdict; reasons.append("One run a side can't be told from noise.")
    else: reasons.append(f"{METRICS[primary][0]} is better beyond noise.")
    for k in CONSTRAINTS:
        c = cmp.get(k)
        if not c or k == primary: continue
        if c["verdict"] == "worse": verdict = "reject" if verdict == "reject" else "hold"; reasons.append(f"{METRICS[k][0]} got worse beyond noise.")
    if not (artifact or {}).get("ref"): verdict = "hold" if verdict == "recommend" else verdict; reasons.append("No versioned artifact to deploy: name the commit, version or image.")
    return {"verdict": verdict, "reasons": reasons}


STRICT = {"recommend": 0, "hold": 1, "reject": 2}


class ExperimentIn(BaseModel):
    comp_id: int
    title: str = Field(min_length=3, max_length=160)
    idea: str = Field("", max_length=3000)
    source: str = Field("", max_length=200)  # where the idea came from: "task:12", "rec:4", a note


class ExperimentPatch(BaseModel):
    title: str | None = Field(None, min_length=3, max_length=160)
    idea: str | None = Field(None, max_length=3000)
    benefit: str | None = Field(None, max_length=2000)
    risks: str | None = Field(None, max_length=2000)
    cost: str | None = Field(None, max_length=600)
    sandbox_note: str | None = Field(None, max_length=3000)
    primary: str | None = Field(None, max_length=40)
    artifact: dict | None = None  # {kind: commit|version|image, ref, repo, note}
    miner_id: int | None = None


class RunsIn(BaseModel):
    side: str = Field(pattern="^(base|cand)$")
    runs: list[dict] = Field(default_factory=list, max_length=100)  # [{metric: value, ..., label?}]
    replace: bool = False


class LinkIn(BaseModel):
    kind: str = Field(pattern="^(sandbox|lab)$")
    id: int
    side: str | None = Field(None, pattern="^(base|cand)$")  # a Lab experiment can also be one evaluation run


class StepIn(BaseModel):
    to: str = Field(pattern="^(idea|proposal|sandbox|evaluation|recommendation)$")
    note: str = Field("", max_length=600)


class DecideIn(BaseModel):
    decision: str = Field(pattern="^(approve|reject|changes)$")
    reason: str = Field("", max_length=1000)


class DeployIn(BaseModel):
    version: str = Field(min_length=1, max_length=120)
    miner_id: int | None = None
    note: str = Field("", max_length=600)


class CloseIn(BaseModel):
    outcome: str = Field(pattern="^(kept|rolled_back|abandoned)$")
    reason: str = Field("", max_length=600)


class MetricIn(BaseModel):
    comp_id: int
    metrics: dict[str, float]
    ts: float | None = None
    run: str = Field("", max_length=80)
    miner_id: int | None = None
    note: str = Field("", max_length=300)


class MinerIn(BaseModel):
    campaign_id: int
    hotkey: str = Field(min_length=46, max_length=48)
    name: str = Field("", max_length=80)
    comp_id: int | None = None


class MinerPatch(BaseModel):
    name: str | None = Field(None, max_length=80)
    comp_id: int | None = None
    version: str | None = Field(None, max_length=120)
    config: str | None = Field(None, max_length=4000)
    hardware: str | None = Field(None, max_length=600)
    notes: str | None = Field(None, max_length=2000)


class CostIn(BaseModel):
    kind: str = Field(pattern="^(compute|hosting|infra|model_api|other|payout)$")
    label: str = Field(min_length=1, max_length=120)
    usd: float = Field(ge=0, le=10_000_000)
    period: str = Field(pattern="^(day|month|once)$")
    campaign_id: int | None = None
    comp_id: int | None = None
    starts: str = Field("", max_length=10)  # YYYY-MM-DD, for "once" the day it was paid
    ends: str = Field("", max_length=10)


class SettingsIn(BaseModel):
    usd_per_mtok: float | None = Field(None, ge=0, le=1000)
    min_runs: int | None = Field(None, ge=2, le=50)
    primary: dict[str, str] | None = None  # {comp_id: metric}
    expected: dict[str, float] | None = None  # {campaign_id: expected dollars a month}


class NoteIn(BaseModel):
    note: str = Field("", max_length=600)


class HolderIn(BaseModel):  # D-004 D4.2 (K-20): who holds an ingest key's token, as the Owner designates it
    holder: str | None = Field(None, pattern="^(independent_evaluator|team)$")

class KeyIn(BaseModel):
    label: str = Field(min_length=1, max_length=60)


class Command:
    def __init__(self, work):
        self.w, self.m, self.db = work, work.m, work.db
        self.co = None  # company.Company, set by main.py: the approval gateway
        q = self.db.q
        q("""CREATE TABLE IF NOT EXISTS mc_metrics (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, comp_id INTEGER, miner_id INTEGER, ts REAL,
             metric TEXT, value REAL, source TEXT, run TEXT, note TEXT)""")
        q("CREATE INDEX IF NOT EXISTS mc_metrics_c ON mc_metrics (comp_id, metric, ts)")
        q("""CREATE TABLE IF NOT EXISTS mc_experiments (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, comp_id INTEGER, title TEXT, stage TEXT,
             status TEXT DEFAULT 'open', idea TEXT, source TEXT, benefit TEXT, risks TEXT, cost TEXT, sandbox TEXT, sandbox_note TEXT, primary_metric TEXT,
             base TEXT, cand TEXT, artifact TEXT, miner_id INTEGER, review TEXT, approval_id INTEGER, evidence_hash TEXT, deploy_id INTEGER,
             monitor_since REAL, outcome_reason TEXT, author TEXT, created REAL, updated REAL)""")
        q("CREATE INDEX IF NOT EXISTS mc_experiments_u ON mc_experiments (user_id, comp_id, id)")
        q("""CREATE TABLE IF NOT EXISTS mc_log (id INTEGER PRIMARY KEY AUTOINCREMENT, exp_id INTEGER, ts REAL, who TEXT, kind TEXT, text TEXT)""")
        q("CREATE INDEX IF NOT EXISTS mc_log_e ON mc_log (exp_id, id)")
        q("""CREATE TABLE IF NOT EXISTS mc_miners (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, campaign_id INTEGER, comp_id INTEGER, hotkey TEXT,
             name TEXT, version TEXT, config TEXT, hardware TEXT, notes TEXT, manual INTEGER DEFAULT 0, created REAL, updated REAL,
             UNIQUE (user_id, campaign_id, hotkey))""")
        q("""CREATE TABLE IF NOT EXISTS mc_health (id INTEGER PRIMARY KEY AUTOINCREMENT, miner_id INTEGER, ts REAL, up INTEGER, cpu REAL, mem REAL, gpu REAL,
             errors INTEGER, version TEXT, log TEXT)""")
        q("CREATE INDEX IF NOT EXISTS mc_health_m ON mc_health (miner_id, ts)")
        q("""CREATE TABLE IF NOT EXISTS mc_deploys (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, miner_id INTEGER, comp_id INTEGER, exp_id INTEGER,
             approval_id INTEGER, version TEXT, ref TEXT, status TEXT, prev_id INTEGER, rollback_of INTEGER, note TEXT, by_user TEXT, ts REAL)""")
        q("CREATE INDEX IF NOT EXISTS mc_deploys_m ON mc_deploys (miner_id, id)")
        q("""CREATE TABLE IF NOT EXISTS mc_costs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, campaign_id INTEGER, comp_id INTEGER, kind TEXT,
             label TEXT, usd REAL, period TEXT, starts TEXT, ends TEXT, created REAL)""")
        q("CREATE TABLE IF NOT EXISTS mc_settings (user_id INTEGER PRIMARY KEY, settings TEXT)")
        q("""CREATE TABLE IF NOT EXISTS mc_keys (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, label TEXT, hash TEXT UNIQUE, prefix TEXT,
             created REAL, last_used REAL, uses INTEGER DEFAULT 0, revoked REAL)""")
        # D-004 D4.2 (K-20): which key sent a report and when AXoR received it; who holds a key, since when, designated by whom.
        # Additive and nullable: an older release ignores them, and rows it writes read as unverifiable later (fail closed).
        for t, cols in (("mc_metrics", (("key_id", "INTEGER"), ("received", "REAL"))),
                        ("mc_keys", (("holder", "TEXT"), ("holder_since", "REAL"), ("holder_by", "TEXT")))):
            have = {c["name"] for c in q(f"PRAGMA table_info({t})")}
            for c, ddl in cols:
                if c not in have: q(f"ALTER TABLE {t} ADD COLUMN {c} {ddl}")
        self.st, self.lock, self.hits, self.cache = Status(work), threading.Lock(), {}, {}
        work.command = self

    # ---------- basics ----------
    def _has(self, table):
        return bool(self.db.q("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,), one=True))

    def settings(self, me):
        r = self.db.q("SELECT settings FROM mc_settings WHERE user_id=?", (me["id"],), one=True)
        return {"usd_per_mtok": None, "min_runs": MIN_RUNS, "primary": {}, "expected": {}, **_load(r and r["settings"], {})}

    def save_settings(self, me, b: SettingsIn):
        s = self.settings(me)
        if b.usd_per_mtok is not None: s["usd_per_mtok"] = b.usd_per_mtok or None
        if b.min_runs is not None: s["min_runs"] = b.min_runs
        if b.primary is not None:
            for k, v in b.primary.items():
                if v not in METRICS: raise HTTPException(400, "Unknown metric.")
                self._comp(me, int(k))
                s["primary"][str(int(k))] = v
        if b.expected is not None:
            for k, v in b.expected.items():
                self.m._own(me, int(k))
                if v is None or v <= 0: s["expected"].pop(str(int(k)), None)
                else: s["expected"][str(int(k))] = min(float(v), 10_000_000)
        self.db.q("INSERT INTO mc_settings (user_id, settings) VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET settings=excluded.settings", (me["id"], _j(s)))
        return {"settings": s}

    def _campaigns(self, me):
        return [self.m._campaign(r["id"]) for r in self.db.q("SELECT id FROM mh_campaigns WHERE user_id=? ORDER BY netuid, mech, id", (me["id"],))]

    def _comps(self, me, closed=False):
        out = []
        for c in self._campaigns(me):
            for w in self.w._order(self.db.q("SELECT * FROM mw_comps WHERE campaign_id=?", (c["id"],))):
                if closed or w["status"] != "closed": out.append((w, c))
        return out

    def _comp(self, me, wid):
        return self.w._own(me, wid)

    def _label(self, w, c):
        return f"SN{c['netuid']} · {w['number'] if w['number'] is not None else w['name']}"

    def primary(self, me, wid):
        return self.settings(me)["primary"].get(str(wid), "score")

    # ---------- the user's miners (on chain) ----------
    def _chain(self, c):
        """The campaign's miners in its latest snapshot: their rows and rank, or [] before the first snapshot."""
        s = self.m._latest(c["netuid"], c["mech"])
        if not s: return [], None
        mine = self.m._mine(c)
        rank = {r["hk"]: i + 1 for i, r in enumerate(ranked(s))}  # the same order as mh_points and the Competition tab
        return [dict(r, rank=rank.get(r["hk"])) for r in s["rows"] if mine(r) and not _validator(r)], s

    def _sync_miners(self, me, c):
        """Every hotkey of the campaign's on-chain miners gets a workspace row (once)."""
        ours, _ = self._chain(c)
        now = _now()
        for r in ours:
            self.db.q("""INSERT OR IGNORE INTO mc_miners (user_id, campaign_id, hotkey, name, created, updated) VALUES (?,?,?,?,?,?)""",
                      (me["id"], c["id"], r["hk"], f"UID {r.get('u')}", now, now))
        return {r["hk"]: r for r in ours}

    def _miner(self, me, mid):
        r = self.db.q("SELECT * FROM mc_miners WHERE id=? AND user_id=?", (mid, me["id"]), one=True)
        if not r: raise HTTPException(404, "There's no such miner.")
        return r

    def _health(self, mid, since=None):
        since = since or _now() - DAY
        return self.db.q("SELECT ts, up, cpu, mem, gpu, errors, version FROM mc_health WHERE miner_id=? AND ts>? ORDER BY ts", (mid, since))

    def _miner_state(self, m, chain, now):
        last = self.db.q("SELECT ts, up, cpu, mem, gpu, errors, version FROM mc_health WHERE miner_id=? ORDER BY ts DESC LIMIT 1", (m["id"],), one=True)
        h = self._health(m["id"])
        up = round(sum(1 for x in h if x["up"]) / len(h), 4) if h else None
        state = "unknown" if not last else "silent" if now - last["ts"] > SILENT_MIN * 60 else "down" if not last["up"] else "erroring" if (last["errors"] or 0) > 0 else "up"
        dep = self.db.q("SELECT version, ts, exp_id FROM mc_deploys WHERE miner_id=? AND status='active' ORDER BY id DESC LIMIT 1", (m["id"],), one=True)
        r = chain.get(m["hotkey"])
        return {"id": m["id"], "name": m["name"] or "", "hotkey": m["hotkey"], "campaign": m["campaign_id"], "comp": m["comp_id"], "manual": bool(m["manual"]),
                "version": (dep and dep["version"]) or m["version"] or (last and last["version"]) or "", "health": state, "last_seen": last and last["ts"],
                "uptime_24h": up, "errors": last and last["errors"], "cpu": last and last["cpu"], "mem": last and last["mem"], "gpu": last and last["gpu"],
                "onchain": {"registered": bool(r), "uid": r and r.get("u"), "rank": r and r.get("rank"), "em": r and round(r.get("em", 0), 6),
                            "inc": r and r.get("inc"), "trust": r and r.get("tr"), "consensus": r and r.get("cs"), "coldkey": r and r.get("ck")},
                "deployed": dep and {"version": dep["version"], "ts": dep["ts"], "exp": dep["exp_id"]}}

    def miners(self, me):
        now, out = _now(), []
        for c in self._campaigns(me):
            chain = self._sync_miners(me, c)
            for m in self.db.q("SELECT * FROM mc_miners WHERE user_id=? AND campaign_id=? ORDER BY manual, id", (me["id"], c["id"])):
                out.append(self._miner_state(m, chain, now) | {"netuid": c["netuid"], "subnet": self.m._name(c)})
        return {"miners": out}

    def add_miner(self, me, b: MinerIn):
        c = self.m._own(me, b.campaign_id)
        hk = b.hotkey.strip()
        if looks_secret(hk) or not SS58.match(hk): raise HTTPException(400, "Give the miner's public hotkey address (SS58, starts with 5). " + SECRET_HINT)
        if b.comp_id: self._comp_on(me, c, b.comp_id)
        now = _now()
        r = self.db.q("""INSERT INTO mc_miners (user_id, campaign_id, comp_id, hotkey, name, manual, created, updated) VALUES (?,?,?,?,?,1,?,?)
                         ON CONFLICT(user_id, campaign_id, hotkey) DO NOTHING RETURNING id""", (me["id"], c["id"], b.comp_id, hk, b.name.strip(), now, now), one=True)
        if not r: raise HTTPException(409, "That miner is on the campaign already.")
        return self.miner(me, r["id"])

    def _comp_on(self, me, c, wid):
        w = self.db.q("SELECT id FROM mw_comps WHERE id=? AND campaign_id=?", (wid, c["id"]), one=True)
        if not w: raise HTTPException(400, "That competition team isn't on this campaign.")
        return w

    def patch_miner(self, me, mid, b: MinerPatch):
        m = self._miner(me, mid)
        sets = {}
        for k in ("name", "version", "hardware", "notes", "config"):
            v = getattr(b, k)
            if v is None: continue
            if looks_secret(v): raise HTTPException(400, SECRET_HINT)
            sets[k] = v.strip()
        if "config" in sets and re.search(r"(?i)(mnemonic|seed|private[_ ]?key|secret|password|api[_-]?key)\s*[:=]", sets["config"]):
            raise HTTPException(400, "Keep secrets out of the configuration: wallet seeds, private keys, passwords and API keys stay on the miner.")
        if "comp_id" in b.model_fields_set:
            if b.comp_id: self._comp_on(me, self.m._campaign(m["campaign_id"]), b.comp_id)
            sets["comp_id"] = b.comp_id or None
        if sets:
            self.db.q(f"UPDATE mc_miners SET {', '.join(f'{k}=?' for k in sets)}, updated=? WHERE id=?", (*sets.values(), _now(), mid))
        return self.miner(me, mid)

    def delete_miner(self, me, mid):
        m = self._miner(me, mid)
        if not m["manual"]: raise HTTPException(409, "It's on chain under the campaign's keys: take the key out of the campaign's settings instead.")
        for t in ("mc_health",): self.db.q(f"DELETE FROM {t} WHERE miner_id=?", (mid,))
        self.db.q("DELETE FROM mc_miners WHERE id=?", (mid,))
        return {"ok": True}

    def miner(self, me, mid):
        m = self._miner(me, mid)
        c = self.m._campaign(m["campaign_id"])
        chain, s = self._chain(c)
        chain = {r["hk"]: r for r in chain}
        now = _now()
        out = self._miner_state(m, chain, now) | {"netuid": c["netuid"], "subnet": self.m._name(c), "config": m["config"] or "", "hardware": m["hardware"] or "",
                                                  "notes": m["notes"] or "", "snapshot": s and {"ts": s["ts"], "block": s["head"].get("block")}}
        out["history"] = [{"ts": p["ts"], "rank": p["rank"], "em": p["em"], "inc": p["inc"]} for p in self.db.q(
            "SELECT ts, rank, em, inc FROM mh_points WHERE netuid=? AND mech=? AND hk=? AND ts>? ORDER BY ts", (c["netuid"], c["mech"], m["hotkey"], now - 30 * DAY))]
        out["health_24h"] = self._health(m["id"])
        logs = self.db.q("SELECT ts, log FROM mc_health WHERE miner_id=? AND log IS NOT NULL AND log!='' ORDER BY ts DESC LIMIT 20", (m["id"],))
        out["logs"] = [{"ts": r["ts"], "lines": _load(r["log"], [])} for r in logs]
        out["metrics"] = [{"ts": r["ts"], "metric": r["metric"], "value": r["value"], "source": r["source"]} for r in self.db.q(
            "SELECT ts, metric, value, source FROM mc_metrics WHERE miner_id=? ORDER BY ts DESC LIMIT 200", (m["id"],))]
        out["deploys"] = [self._deploy_out(d) for d in self.db.q("SELECT * FROM mc_deploys WHERE miner_id=? ORDER BY id DESC LIMIT 50", (m["id"],))]
        out["comps"] = [{"id": w["id"], "label": self._label(w, c)} for w in self.w._order(self.db.q("SELECT * FROM mw_comps WHERE campaign_id=?", (c["id"],)))]
        out["evaluator"] = self._evaluator(me, m["comp_id"]) if m["comp_id"] else None
        return out

    @staticmethod
    def _deploy_out(d):
        return {k: d[k] for k in ("id", "miner_id", "comp_id", "exp_id", "approval_id", "version", "ref", "status", "prev_id", "rollback_of", "note", "by_user", "ts")}

    # ---------- metrics: ingest, manual, derived ----------
    def keys(self, me):
        return {"keys": [{k: r.get(k) for k in ("id", "label", "prefix", "created", "last_used", "uses", "revoked", "holder", "holder_since")}
                         for r in self.db.q("SELECT * FROM mc_keys WHERE user_id=? ORDER BY revoked IS NOT NULL, id DESC", (me["id"],))]}

    def new_key(self, me, b: KeyIn):
        if self.db.q("SELECT COUNT(*) n FROM mc_keys WHERE user_id=? AND revoked IS NULL", (me["id"],), one=True)["n"] >= 10:
            raise HTTPException(409, "Ten keys are live already: revoke one first.")
        token = "mcx_" + secrets.token_urlsafe(30)
        self.db.q("INSERT INTO mc_keys (user_id, label, hash, prefix, created) VALUES (?,?,?,?,?)", (me["id"], b.label.strip(), _sha(token), fingerprint(token), _now()))  # D-019: never key characters
        return self.keys(me) | {"token": token}

    def revoke_key(self, me, kid):
        if not self.db.q("UPDATE mc_keys SET revoked=? WHERE id=? AND user_id=? AND revoked IS NULL RETURNING id", (_now(), kid, me["id"]), one=True):
            raise HTTPException(404, "There's no such live key.")
        return self.keys(me)

    def set_holder(self, me, kid, b: HolderIn, ip=""):
        """The Owner designates who holds an ingest key's token (K-20). Only reports received after the designation count as an
        independent evaluator's; a revoked key's reports never count. Audited. No token or token fragment is returned."""
        from . import missions  # the Owner role lives with Mission Control (AXOR_OWNERS)
        if not missions.is_owner(self.db, me): raise HTTPException(403, "Only the Owner designates who holds an ingest key.")
        k = self.db.q("SELECT id, revoked, holder FROM mc_keys WHERE id=?", (kid,), one=True)
        if not k: raise HTTPException(404, "There's no such key.")
        if k["revoked"] is not None: raise HTTPException(409, "That key is revoked: its reports never count.")
        if k["holder"] == b.holder:  # unchanged: keep its date, so its earlier reports keep counting
            r = self.db.q("SELECT holder, holder_since FROM mc_keys WHERE id=?", (kid,), one=True)
            return {"id": kid, "holder": r["holder"], "holder_since": r["holder_since"]}
        now = _now()
        self.db.q("UPDATE mc_keys SET holder=?, holder_since=?, holder_by=? WHERE id=?", (b.holder, now if b.holder else None, me["username"], kid))
        self.db.log("mission.evidence_key", me["username"], f"key {kid}", ip, f"holder {k['holder'] or 'none'} → {b.holder or 'none'}")
        return {"id": kid, "holder": b.holder, "holder_since": now if b.holder else None}

    def _key_user(self, token):
        return self._key(token)[0]

    def _key(self, token):
        """The key's owner and the key's id, or 401 / 429."""
        if not token or not token.startswith("mcx_"): raise HTTPException(401, "Send the ingest key as Authorization: Bearer mcx_…")
        k = self.db.q("SELECT * FROM mc_keys WHERE hash=? AND revoked IS NULL", (_sha(token),), one=True)
        if not k: raise HTTPException(401, "That key isn't valid (revoked, or never made).")
        now = _now()
        with self.lock:
            hits = [t for t in self.hits.get(k["id"], []) if t > now - 3600]
            if len(hits) >= INGEST_PER_HOUR: raise HTTPException(429, "Too many reports this hour for this key.")
            self.hits[k["id"]] = hits + [now]
        self.db.q("UPDATE mc_keys SET last_used=?, uses=uses+1 WHERE id=?", (now, k["id"]))
        u = self.db.q("SELECT id, username, role FROM users WHERE id=?", (k["user_id"],), one=True)
        if not u: raise HTTPException(401, "The key's owner is gone.")
        return u, k["id"]

    def _put_metrics(self, me, wid, metrics, ts, run, miner_id, source, note="", key_id=None):
        w, _ = self._comp(me, wid)
        if miner_id: self._miner(me, miner_id)
        now = _now()
        ts = now if ts is None else float(ts)
        if not now - 90 * DAY <= ts <= now + 300: raise HTTPException(400, "The time must be within the last 90 days (seconds since 1970).")
        rows = []
        for k, v in (metrics or {}).items():
            if k not in METRICS: raise HTTPException(400, f"Unknown metric {k!r}: use {', '.join(METRICS)}.")
            v = _num(v)
            if v is None: raise HTTPException(400, f"{k} needs a number.")
            if METRICS[k][1] == "%" and not 0 <= v <= 1: raise HTTPException(400, f"{k} is a share from 0 to 1.")
            rows.append((me["id"], w["id"], miner_id, ts, k, v, source, _clip(run, 80) or None, _clip(note, 300) or None, key_id, now))
        if not rows: raise HTTPException(400, "No metrics in the report.")
        for r in rows:
            self.db.q("INSERT INTO mc_metrics (user_id, comp_id, miner_id, ts, metric, value, source, run, note, key_id, received) VALUES (?,?,?,?,?,?,?,?,?,?,?)", r)
        return len(rows)

    def add_metrics(self, me, b: MetricIn):
        n = self._put_metrics(me, b.comp_id, b.metrics, b.ts, b.run, b.miner_id, "manual", b.note)
        return {"ok": True, "stored": n}

    def delete_metric(self, me, mid):
        if not self.db.q("DELETE FROM mc_metrics WHERE id=? AND user_id=? AND source='manual' RETURNING id", (mid, me["id"]), one=True):
            raise HTTPException(404, "There's no such entry of yours (evaluator reports can't be deleted here).")
        return {"ok": True}

    def ingest(self, token, body):
        """An evaluator's or a miner's report: {competition, metrics{}, ts?, run?, miner (hotkey)?, health{up,cpu,mem,gpu,errors,version,log[]}?}."""
        me, key_id = self._key(token)
        if not isinstance(body, dict): raise HTTPException(400, "Send a JSON object.")
        mid = None
        if body.get("miner"):
            hk = str(body["miner"]).strip()
            m = self.db.q("SELECT id, campaign_id FROM mc_miners WHERE user_id=? AND hotkey=? ORDER BY id LIMIT 1", (me["id"], hk), one=True)
            if not m: raise HTTPException(404, "That hotkey isn't a miner of yours in the Command center: add it to a campaign first.")
            mid = m["id"]
        out = {"ok": True, "stored": 0, "health": False}
        if body.get("metrics"):
            try: wid = int(body.get("competition"))
            except (TypeError, ValueError): raise HTTPException(400, "Say which competition team: \"competition\": its id (Command center → Performance shows it).")
            out["stored"] = self._put_metrics(me, wid, body["metrics"], body.get("ts"), str(body.get("run") or ""), mid, "evaluator", key_id=key_id)
        h = body.get("health")
        if isinstance(h, dict):
            if not mid: raise HTTPException(400, "A health report needs \"miner\": the miner's hotkey.")
            lines = [_clip(x, 400) for x in (h.get("log") or [])[:50] if isinstance(x, str)]
            if any(looks_secret(x) for x in lines): raise HTTPException(400, "A log line looks like a secret: it wasn't stored.")
            self.db.q("INSERT INTO mc_health (miner_id, ts, up, cpu, mem, gpu, errors, version, log) VALUES (?,?,?,?,?,?,?,?,?)",
                      (mid, _now(), 1 if h.get("up", True) else 0, _num(h.get("cpu")), _num(h.get("mem")), _num(h.get("gpu")),
                       int(_num(h.get("errors")) or 0), _clip(h.get("version"), 120) or None, _j(lines) if lines else None))
            self.db.q("""DELETE FROM mc_health WHERE miner_id=? AND id NOT IN (SELECT id FROM mc_health WHERE miner_id=? ORDER BY id DESC LIMIT ?)""",
                      (mid, mid, HEALTH_KEEP))
            out["health"] = True
        if not out["stored"] and not out["health"]: raise HTTPException(400, "Nothing to store: send metrics, health, or both.")
        return out

    def _evaluator(self, me, wid):
        r = self.db.q("SELECT MAX(ts) last, COUNT(*) n FROM mc_metrics WHERE comp_id=? AND source='evaluator'", (wid,), one=True)
        if not r["n"]: return {"state": "none", "last": None}
        return {"state": "stale" if _now() - r["last"] > STALE_H * 3600 else "live", "last": r["last"], "reports": r["n"]}

    def _lab_points(self, wid, since):
        """The Lab's scored base runs on this team's Workflow: solved share, success rate, mean time, cost per solved task."""
        if not (self._has("mb_flows") and self._has("mb_experiments")): return []
        f = self.db.q("SELECT id FROM mb_flows WHERE comp_id=?", (wid,), one=True)
        if not f: return []
        out = []
        for e in self.db.q("""SELECT id, kind, label, head, tasks, solved, runs, passed, cost, secs, finished, per_task FROM mb_experiments WHERE flow_id=?
                              AND status='done' AND finished>? ORDER BY finished""", (f["id"], since)):
            out.append(self._lab_run(e))
        return out

    @staticmethod
    def _lab_run(e):
        per = _load(e.get("per_task"), {})
        times = sorted(p["secs"] / p["timed"] * 1000 for p in per.values() if p.get("timed"))
        pc = lambda q: times[min(len(times) - 1, int(math.ceil(q * len(times))) - 1)] if times else None
        run = {"score": round(e["solved"] / e["tasks"], 4) if e["tasks"] else None, "success_rate": round(e["passed"] / e["runs"], 4) if e["runs"] else None,
               "latency_p50": pc(0.5), "latency_p95": pc(0.95), "latency_p99": pc(0.99),
               "cost_task": round(e["cost"] / e["solved"], 4) if e["solved"] and e["cost"] is not None else None}
        return {"id": e["id"], "kind": e["kind"], "label": e["label"], "head": e["head"], "ts": e["finished"], "tasks": e["tasks"], "solved": e["solved"],
                "metrics": {k: v for k, v in run.items() if v is not None}}

    def performance(self, me, wid, days=30):
        w, c = self._comp(me, wid)
        now = _now()
        since = now - days * DAY
        series = {}
        for r in reversed(self.db.q("SELECT id, ts, metric, value, source, run, miner_id, note FROM mc_metrics WHERE comp_id=? AND ts>? ORDER BY ts DESC LIMIT ?",
                                    (wid, since, POINTS))):
            series.setdefault(r["metric"], []).append({"id": r["id"], "ts": r["ts"], "v": r["value"], "src": r["source"], "run": r["run"], "note": r["note"]})
        latest = {k: v[-1] for k, v in series.items()}
        ours, s = self._chain(c)
        hks = [r["hk"] for r in ours]
        rank = []
        if hks:
            pts = self.db.q(f"""SELECT ts, MIN(rank) rank, SUM(em) em FROM mh_points WHERE netuid=? AND mech=? AND ts>? AND hk IN ({','.join('?' * len(hks))})
                               GROUP BY sample_id ORDER BY ts""", (c["netuid"], c["mech"], since, *hks))
            rank = [{"ts": p["ts"], "rank": p["rank"], "em": round(p["em"] or 0, 6)} for p in pts]
        lab = self._lab_points(wid, since)
        prim = self.primary(me, wid)
        running = self.db.q("""SELECT * FROM mc_experiments WHERE comp_id=? AND user_id=? AND status='open' AND stage IN ('evaluation','recommendation','approval')
                               ORDER BY updated DESC LIMIT 1""", (wid, me["id"]), one=True)
        return {"comp": {"id": wid, "label": self._label(w, c), "campaign": c["id"], "netuid": c["netuid"]}, "primary": prim, "metrics": METRICS,
                "series": series, "latest": latest, "onchain": rank, "onchain_now": {"miners": len(ours), "best": min((r["rank"] for r in ours if r.get("rank")), default=None),
                                                                                   "em": round(sum(r.get("em", 0) for r in ours), 6), "ts": s and s["ts"]},
                "lab": lab, "evaluator": self._evaluator(me, wid), "comparison": running and self._exp_out(me, running, full=False), "days": days}

    # ---------- experiments ----------
    def _exp(self, me, eid):
        e = self.db.q("SELECT * FROM mc_experiments WHERE id=? AND user_id=?", (eid, me["id"]), one=True)
        if not e: raise HTTPException(404, "There's no such experiment.")
        return e

    def _log(self, eid, who, kind, text):
        self.db.q("INSERT INTO mc_log (exp_id, ts, who, kind, text) VALUES (?,?,?,?,?)", (eid, _now(), who, kind, _clip(text, 1000)))

    def _evidence(self, e):
        """What a reviewer and an approver read: the runs, the artifact, the primary metric. Its hash binds the approval."""
        return {"experiment": e["id"], "primary": e["primary_metric"], "base": _load(e["base"], []), "cand": _load(e["cand"], []),
                "artifact": _load(e["artifact"], {}), "miner": e["miner_id"], "sandbox": _load(e["sandbox"], [])}

    def _approval(self, aid):
        if not aid or not self._has("co_approvals"): return None
        a = self.db.q("SELECT id, status, expires_at, decided_by, decided_at, decision_reason, artifact_hash, payload_hash FROM co_approvals WHERE id=?", (aid,), one=True)
        if not a: return None
        ex = self.db.q("SELECT status, finished, by_user FROM co_executions WHERE approval_id=?", (aid,), one=True) if self._has("co_executions") else None
        st = "expired" if a["status"] in ("pending", "approved") and (a["expires_at"] or 0) < _now() else a["status"]
        return {"id": a["id"], "status": st, "expires_at": a["expires_at"], "decided_by": a["decided_by"], "decided_at": a["decided_at"],
                "reason": a["decision_reason"], "hash": a["artifact_hash"], "execution": ex and {"status": ex["status"], "finished": ex["finished"], "by_user": ex["by_user"]}}

    def _exp_out(self, me, e, full=True):
        base, cand = _load(e["base"], []), _load(e["cand"], [])
        mr = self.settings(me)["min_runs"]
        cmp = compare(base, cand, e["primary_metric"], mr)
        h = _sha(self._evidence(e))
        rv = _load(e["review"], None)
        out = {k: e[k] for k in ("id", "comp_id", "title", "stage", "status", "idea", "source", "benefit", "risks", "cost", "sandbox_note", "miner_id",
                                 "approval_id", "deploy_id", "monitor_since", "outcome_reason", "author", "created", "updated")}
        out |= {"primary": e["primary_metric"], "artifact": _load(e["artifact"], {}), "sandbox": _load(e["sandbox"], []), "runs": {"base": len(base), "cand": len(cand)},
                "compare": cmp, "rule": rule_review(cmp, e["primary_metric"], _load(e["artifact"], {}), mr), "review": rv,
                "review_current": bool(rv and rv.get("hash") == h), "hash": h, "approval": self._approval(e["approval_id"]), "min_runs": mr}
        if full:
            out["base"], out["cand"] = base, cand
            out["log"] = self.db.q("SELECT ts, who, kind, text FROM mc_log WHERE exp_id=? ORDER BY id DESC LIMIT 80", (e["id"],))
            out["monitor"] = self._monitor(e, cmp) if e["stage"] == "monitoring" else None
            out["deploy"] = e["deploy_id"] and self._deploy_out(self.db.q("SELECT * FROM mc_deploys WHERE id=?", (e["deploy_id"],), one=True) or {k: None for k in (
                "id", "miner_id", "comp_id", "exp_id", "approval_id", "version", "ref", "status", "prev_id", "rollback_of", "note", "by_user", "ts")})
        return out

    def experiments(self, me, wid=None):
        rows = self.db.q(f"SELECT * FROM mc_experiments WHERE user_id=? {'AND comp_id=?' if wid else ''} ORDER BY status='open' DESC, updated DESC LIMIT 200",
                         (me["id"], wid) if wid else (me["id"],))
        labels = {w["id"]: self._label(w, c) for w, c in self._comps(me, closed=True)}
        return {"experiments": [self._exp_out(me, e, full=False) | {"comp": labels.get(e["comp_id"], "a deleted team")} for e in rows],
                "stages": [[k, STAGE_LABEL[k]] for k in STAGES], "metrics": METRICS, "teams": [{"id": k, "label": v} for k, v in labels.items()]}

    def experiment(self, me, eid):
        e = self._exp(me, eid)
        w, c = self._comp(me, e["comp_id"])
        out = self._exp_out(me, e) | {"comp": self._label(w, c), "campaign": c["id"]}
        out["sandboxes"] = [dict(r) for r in self.db.q("""SELECT id, command, status, exit_code, started, finished, cost FROM mw_sbx WHERE comp_id=?
                                                         ORDER BY id DESC LIMIT 20""", (e["comp_id"],))]
        out["labs"] = self._lab_points(e["comp_id"], 0)[-30:]
        out["miners"] = [{"id": m["id"], "name": m["name"], "hotkey": m["hotkey"]} for m in self.db.q(
            "SELECT id, name, hotkey FROM mc_miners WHERE user_id=? AND campaign_id=? ORDER BY id", (me["id"], c["id"]))]
        return out

    def new_experiment(self, me, b: ExperimentIn):
        w, c = self._comp(me, b.comp_id)
        if self.db.q("SELECT COUNT(*) n FROM mc_experiments WHERE user_id=? AND status='open'", (me["id"],), one=True)["n"] >= MAX_EXPERIMENTS:
            raise HTTPException(409, f"{MAX_EXPERIMENTS} experiments are open: close some first.")
        if looks_secret(b.idea) or looks_secret(b.title): raise HTTPException(400, SECRET_HINT)
        now = _now()
        eid = self.db.q("""INSERT INTO mc_experiments (user_id, comp_id, title, stage, idea, source, primary_metric, base, cand, sandbox, artifact, author, created, updated)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
                        (me["id"], w["id"], b.title.strip(), "idea", b.idea.strip(), b.source.strip() or None, self.primary(me, w["id"]), "[]", "[]", "[]", "{}",
                         f"user:{me['username']}", now, now), one=True)["id"]
        self._log(eid, me["username"], "idea", f"Idea: {b.title.strip()}" + (f" (from {b.source.strip()})" if b.source.strip() else ""))
        return self.experiment(me, eid)

    def _open(self, e, *stages):
        if e["status"] != "open": raise HTTPException(409, "This experiment is closed.")
        if stages and e["stage"] not in stages: raise HTTPException(409, f"It's at {STAGE_LABEL[e['stage']]}: that isn't possible now.")

    def _frozen(self, e):
        """After the approval request, the evidence can't change: a change would need a new approval."""
        a = self._approval(e["approval_id"])
        if a and a["status"] in ("pending", "approved", "consumed"):
            raise HTTPException(409, "The evidence is under approval: withdraw or revise it first (a change needs a new approval).")

    def _editing(self, e):
        """Before evidence changes: open, not under approval, not past the review. A change after the review sends it back to
        evaluation (the review no longer matches the evidence)."""
        self._open(e, "idea", "proposal", "sandbox", "evaluation", "recommendation")
        self._frozen(e)
        return {"stage": "evaluation"} if e["stage"] == "recommendation" else {}

    def patch_experiment(self, me, eid, b: ExperimentPatch):
        e = self._exp(me, eid)
        self._open(e)
        sets = {}
        for k in ("title", "idea", "benefit", "risks", "cost", "sandbox_note"):
            v = getattr(b, k)
            if v is None: continue
            if looks_secret(v): raise HTTPException(400, SECRET_HINT)
            sets[k] = v.strip()
        evidence = {}
        if b.primary is not None:
            if b.primary not in METRICS: raise HTTPException(400, "Unknown metric.")
            evidence["primary_metric"] = b.primary
        if b.artifact is not None:
            a = {k: _clip(str(b.artifact.get(k) or "").strip(), 300) for k in ("kind", "ref", "repo", "note")}
            if a["kind"] and a["kind"] not in ("commit", "version", "image"): raise HTTPException(400, "The artifact is a commit, a version or an image.")
            if any(looks_secret(v) for v in a.values()): raise HTTPException(400, SECRET_HINT)
            evidence["artifact"] = _j({k: v for k, v in a.items() if v})
        if "miner_id" in b.model_fields_set:
            if b.miner_id: self._miner(me, b.miner_id)
            evidence["miner_id"] = b.miner_id or None
        if evidence: evidence |= self._editing(e)
        sets |= evidence
        if not sets: return self.experiment(me, eid)
        self.db.q(f"UPDATE mc_experiments SET {', '.join(f'{k}=?' for k in sets)}, updated=? WHERE id=?", (*sets.values(), _now(), eid))
        self._log(eid, me["username"], "edit", "Changed " + ", ".join(sorted(k.replace("_metric", "").replace("_id", "") for k in sets)) + ".")
        return self.experiment(me, eid)

    def link(self, me, eid, b: LinkIn):
        e = self._exp(me, eid)
        back = self._editing(e)
        if e["stage"] in ("idea", "proposal"): raise HTTPException(409, "Finish the proposal first: trials come after it.")
        if b.kind == "sandbox":
            r = self.db.q("SELECT id, command, status, exit_code, cost FROM mw_sbx WHERE id=? AND comp_id=?", (b.id, e["comp_id"]), one=True)
            if not r: raise HTTPException(404, "There's no such sandbox run on this team.")
            ref = {"kind": "sandbox", "id": r["id"], "what": _clip(r["command"], 160), "status": r["status"], "exit": r["exit_code"]}
        else:
            f = self.db.q("SELECT id FROM mb_flows WHERE comp_id=?", (e["comp_id"],), one=True) if self._has("mb_flows") else None
            r = f and self.db.q("SELECT * FROM mb_experiments WHERE id=? AND flow_id=?", (b.id, f["id"]), one=True)
            if not r: raise HTTPException(404, "There's no such Lab run on this team's Workflow.")
            if r["status"] != "done": raise HTTPException(409, "That Lab run hasn't finished with a score.")
            ref = {"kind": "lab", "id": r["id"], "what": _clip(r["label"], 160), "status": r["status"], "solved": r["solved"], "tasks": r["tasks"]}
        box = [x for x in _load(e["sandbox"], []) if not (x["kind"] == ref["kind"] and x["id"] == ref["id"])] + [ref]
        sets = {"sandbox": _j(box), **back}
        if b.kind == "lab" and b.side:
            run = self._lab_run(r)
            side = _load(e[b.side], [])
            if any(x.get("lab") == r["id"] for x in side): raise HTTPException(409, "That Lab run is in the evaluation already.")
            side.append({**run["metrics"], "label": f"Lab #{r['id']}: {_clip(r['label'], 60)}", "lab": r["id"], "ts": r["finished"]})
            sets[b.side] = _j(side)
        self.db.q(f"UPDATE mc_experiments SET {', '.join(f'{k}=?' for k in sets)}, updated=? WHERE id=?", (*sets.values(), _now(), eid))
        self._log(eid, me["username"], "sandbox", f"Linked {ref['kind']} run #{ref['id']}" + (f" as a {'baseline' if b.side == 'base' else 'candidate'} run" if b.side else "") + ".")
        return self.experiment(me, eid)

    def add_runs(self, me, eid, b: RunsIn):
        e = self._exp(me, eid)
        back = self._evaluating(e)
        runs = [] if b.replace else _load(e[b.side], [])
        for r in b.runs:
            clean = {k: _num(r.get(k)) for k in METRICS if _num(r.get(k)) is not None}
            for k, v in clean.items():
                if METRICS[k][1] == "%" and not 0 <= v <= 1: raise HTTPException(400, f"{k} is a share from 0 to 1.")
            if not clean: raise HTTPException(400, "Each run needs at least one metric with a number.")
            runs.append(clean | {"label": _clip(r.get("label") or "", 80) or f"run {len(runs) + 1}", "ts": _now()})
        if len(runs) > 100: raise HTTPException(400, "Up to 100 runs a side.")
        self.db.q(f"UPDATE mc_experiments SET {b.side}=?, stage=?, updated=? WHERE id=?", (_j(runs), back, _now(), eid))
        self._log(eid, me["username"], "evaluation", f"{'Replaced' if b.replace else 'Added'} {len(b.runs)} {'baseline' if b.side == 'base' else 'candidate'} run{'s' * (len(b.runs) != 1)}.")
        return self.experiment(me, eid)

    def runs_from_reports(self, me, eid, side, label):
        """Evaluator reports with one run label become one evaluation run (every metric reported under it)."""
        e = self._exp(me, eid)
        back = self._evaluating(e)
        rows = self.db.q("SELECT metric, value, ts FROM mc_metrics WHERE comp_id=? AND user_id=? AND run=?", (e["comp_id"], me["id"], label))
        if not rows: raise HTTPException(404, "No reports under that run label on this team.")
        runs = _load(e[side], [])
        if any(x.get("report") == label for x in runs): raise HTTPException(409, "That run is in the evaluation already.")
        run = {}
        for r in rows: run[r["metric"]] = r["value"]
        runs.append(run | {"label": f"reports: {label}", "report": label, "ts": max(r["ts"] for r in rows)})
        self.db.q(f"UPDATE mc_experiments SET {side}=?, stage=?, updated=? WHERE id=?", (_j(runs), back, _now(), eid))
        self._log(eid, me["username"], "evaluation", f"Added the evaluator's run {label!r} as a {'baseline' if side == 'base' else 'candidate'} run.")
        return self.experiment(me, eid)

    def report_runs(self, me, wid):
        self._comp(me, wid)
        return {"runs": self.db.q("""SELECT run, COUNT(*) n, MAX(ts) ts, GROUP_CONCAT(DISTINCT metric) metrics FROM mc_metrics WHERE comp_id=? AND user_id=?
                                    AND run IS NOT NULL GROUP BY run ORDER BY MAX(ts) DESC LIMIT 60""", (wid, me["id"]))}

    def delete_run(self, me, eid, side, idx):
        e = self._exp(me, eid)
        back = self._evaluating(e)
        runs = _load(e[side], [])
        if not 0 <= idx < len(runs): raise HTTPException(404, "There's no such run.")
        gone = runs.pop(idx)
        self.db.q(f"UPDATE mc_experiments SET {side}=?, stage=?, updated=? WHERE id=?", (_j(runs), back, _now(), eid))
        self._log(eid, me["username"], "evaluation", f"Removed {'baseline' if side == 'base' else 'candidate'} run {gone.get('label')!r}.")
        return self.experiment(me, eid)

    def _evaluating(self, e):
        """Runs go in at evaluation (or after the review, which sends it back there): the stage to store."""
        self._editing(e)
        if e["stage"] not in ("evaluation", "recommendation"): raise HTTPException(409, "Runs go in at the evaluation stage: move it on from the sandbox first.")
        return "evaluation"

    def step(self, me, eid, b: StepIn):
        """Moves through the first stages; each one asks for what it needs."""
        e = self._exp(me, eid)
        self._open(e)
        self._frozen(e)
        to, cur = b.to, e["stage"]
        if STAGES.index(to) > STAGES.index(cur) + 1: raise HTTPException(409, "One stage at a time.")
        if STAGES.index(to) > STAGES.index(cur):
            if to == "proposal" and not (e["idea"] or "").strip(): raise HTTPException(400, "Say what the idea is first.")
            if to == "sandbox" and not ((e["benefit"] or "").strip() and (e["risks"] or "").strip()):
                raise HTTPException(400, "The proposal needs the expected benefit and the risks (and the cost, if you know it).")
            if to == "evaluation" and not (_load(e["sandbox"], []) or (e["sandbox_note"] or "").strip()):
                raise HTTPException(400, "Link a sandbox or Lab run, or note where it was tried in isolation.")
            if to == "recommendation": raise HTTPException(409, "Ask the Evidence Reviewer: the review moves it on.")
        self.db.q("UPDATE mc_experiments SET stage=?, updated=? WHERE id=?", (to, _now(), eid))
        self._log(eid, me["username"], "stage", f"{STAGE_LABEL[cur]} → {STAGE_LABEL[to]}" + (f": {b.note.strip()}" if b.note.strip() else ""))
        return self.experiment(me, eid)

    def review(self, me, eid):
        """The Evidence Reviewer: the rule checks, then (with a model) a structured read that can only be stricter."""
        e = self._exp(me, eid)
        self._open(e, "evaluation", "recommendation")
        self._frozen(e)
        out = self._exp_out(me, e)
        rule, model = out["rule"], None
        w, c = self._comp(me, e["comp_id"])
        name = self.m._model(c)
        if name and self.m.hub:
            spent = [0]
            try:
                model = self.m.hub.llm.structured(name, REVIEW_SYSTEM, self._describe(e, out), REVIEW, "mining-review",
                                                  on_usage=lambda n: spent.__setitem__(0, spent[0] + n), effort="medium")
                model = {"verdict": model.get("verdict") if model.get("verdict") in STRICT else "hold", "summary": _clip(model.get("summary"), 800),
                         "concerns": [_clip(x, 300) for x in (model.get("concerns") or [])][:8], "checks": [_clip(x, 300) for x in (model.get("checks") or [])][:8],
                         "model": name, "tokens": spent[0]}
            except Exception as ex:  # noqa: BLE001 - the rule review stands
                log.warning("evidence review %s: %s", eid, ex)
                model = {"error": _clip(str(ex), 300)}
            finally:
                if spent[0]: self.m.hub.log_usage(me, "mining", spent[0], None, name)
        verdict = rule["verdict"]
        if model and model.get("verdict") and STRICT[model["verdict"]] > STRICT[verdict]: verdict = model["verdict"]
        rv = {"verdict": verdict, "rule": rule, "model": model, "by": "Evidence Reviewer", "independent_of": e["author"], "ts": _now(), "hash": out["hash"]}
        self.db.q("UPDATE mc_experiments SET review=?, stage='recommendation', updated=? WHERE id=?", (_j(rv), _now(), eid))
        self._log(eid, "Evidence Reviewer", "review", f"Verdict: {verdict}. " + " ".join(rule["reasons"]) + (f" Model: {model.get('summary')}" if model and model.get("summary") else ""))
        return self.experiment(me, eid)

    def _describe(self, e, out):
        lines = [f"Experiment: {e['title']}", f"Idea: {e['idea'] or 'not given'}", f"Expected benefit: {e['benefit'] or 'not given'}",
                 f"Risks: {e['risks'] or 'not given'}", f"Cost: {e['cost'] or 'not given'}", f"Primary metric: {METRICS[e['primary_metric']][0]} (better: {METRICS[e['primary_metric']][2]})",
                 f"Artifact: {_j(out['artifact']) if out['artifact'] else 'none named'}", f"Isolated trials: {_j(out['sandbox']) if out['sandbox'] else (e['sandbox_note'] or 'none')}",
                 f"Runs: {out['runs']['base']} baseline, {out['runs']['cand']} candidate (at least {out['min_runs']} a side are required).", "", "Metric comparison:"]
        sd = lambda s: "n/a" if s["sd"] is None else f"{s['sd']:.4g}"
        band = lambda x: "n/a" if x["band"] is None else f"±{x['band']:.4g}"
        for k, x in out["compare"].items():
            b, cn = x["base"], x["cand"]
            lines.append(f"- {METRICS[k][0]}: baseline mean {b['mean']:.4g} (sd {sd(b)}, n {b['n']}), candidate mean {cn['mean']:.4g} (sd {sd(cn)}, n {cn['n']}), "
                         f"difference {x['diff']:+.4g}, noise band {band(x)}, reading: {x['verdict']}")
        if not out["compare"]: lines.append("- nothing measured on both sides")
        lines += ["", f"Rule checks: {out['rule']['verdict']}: " + " ".join(out["rule"]["reasons"])]
        return "\n".join(lines)

    def request_approval(self, me, eid, note=""):
        e = self._exp(me, eid)
        self._open(e, "recommendation", "approval")
        out = self._exp_out(me, e)
        rv = out["review"]
        if not rv or rv["verdict"] != "recommend": raise HTTPException(409, "The Evidence Reviewer doesn't recommend it: revise the evidence and ask again.")
        if not out["review_current"]: raise HTTPException(409, "The evidence changed after the review: ask the Evidence Reviewer again.")
        a = self._approval(e["approval_id"])
        if a and a["status"] in ("pending", "approved"): raise HTTPException(409, "An approval request is open already.")
        if not self.co: raise HTTPException(503, "The Company's approval gateway is off on this server, and production approvals go through it.")
        c = self.co._company(me)
        if "deploy" in self.co._off(c): raise HTTPException(409, "Deploys are switched off in the Company's policy (Company → Settings).")
        p = self.db.q("SELECT id FROM co_projects WHERE company_id=? AND link='mining' ORDER BY id LIMIT 1", (c["id"],), one=True)
        w, camp = self._comp(me, e["comp_id"])
        art = out["artifact"]
        miner = e["miner_id"] and self.db.q("SELECT name, hotkey FROM mc_miners WHERE id=?", (e["miner_id"],), one=True)
        prev = e["miner_id"] and self.db.q("SELECT version FROM mc_deploys WHERE miner_id=? AND status='active' ORDER BY id DESC LIMIT 1", (e["miner_id"],), one=True)
        p_ = out["compare"].get(e["primary_metric"])
        payload = {"action": "deploy", "experiment": e["id"], "competition": self._label(w, camp), "artifact": art,
                   "miner": miner and {"name": miner["name"], "hotkey": miner["hotkey"]}, "evidence_hash": out["hash"]}
        evidence = {"review": {"verdict": rv["verdict"], "reasons": rv["rule"]["reasons"], "model": (rv.get("model") or {}).get("summary")},
                    "primary": p_ and {"metric": e["primary_metric"], "base": p_["base"]["mean"], "cand": p_["cand"]["mean"], "band": p_["band"], "runs": [p_["base"]["n"], p_["cand"]["n"]]}}
        aid = self.co._request(c, p and p["id"], None, "deploy", f"Deploy: {e['title']}", (e["benefit"] or "") + (f"\n\n{note.strip()}" if note.strip() else ""),
                               ("user", me["username"]), "mining_experiment", e["id"], out["hash"], payload, "high" if not prev else "medium", evidence,
                               _clip(e["benefit"], 600), f"Roll back to {prev['version']}" if prev else "Stop the miner's new version and restore the previous build.")
        self.db.q("UPDATE mc_experiments SET approval_id=?, evidence_hash=?, stage='approval', updated=? WHERE id=?", (aid, out["hash"], _now(), eid))
        self._log(eid, me["username"], "approval", f"Asked for approval #{aid} (deploy), bound to evidence {out['hash'][:12]}.")
        return self.experiment(me, eid)

    def decide(self, me, eid, b: DecideIn):
        e = self._exp(me, eid)
        self._open(e, "approval")
        if not self.co: raise HTTPException(503, "The Company's approval gateway is off on this server.")
        if b.decision == "approve" and _sha(self._evidence(e)) != e["evidence_hash"]: raise HTTPException(409, "The evidence changed since the request: reject it.")
        from .company import DecideIn as CoDecide
        self.co.decide(me, e["approval_id"], CoDecide(decision=b.decision, reason=b.reason))
        self._log(eid, me["username"], "approval", {"approve": "Approved", "reject": "Rejected", "changes": "Asked for changes"}[b.decision] + (f": {b.reason.strip()}" if b.reason.strip() else "."))
        return self.experiment(me, eid)

    def authorize(self, me, eid):
        """The gateway consumes the approval once and hands the deploy off; the experiment's evidence is checked first, because
        the Company can't read what an experiment is."""
        e = self._exp(me, eid)
        self._open(e, "approval")
        if not self.co: raise HTTPException(503, "The Company's approval gateway is off on this server.")
        a = self._approval(e["approval_id"])
        handed = a and a["status"] == "consumed" and (a["execution"] or {}).get("status") == "handed_off"  # authorized on the Company page
        if not a or (a["status"] != "approved" and not handed): raise HTTPException(409, "It isn't approved.")
        if _sha(self._evidence(e)) != a["hash"]: raise HTTPException(409, "The evidence changed after approval: ask for a new approval.")
        if not handed: self.co.execute(me, a["id"])
        a = self._approval(e["approval_id"])
        if (a["execution"] or {}).get("status") != "handed_off": raise HTTPException(409, "The gateway didn't hand it off.")
        self.db.q("UPDATE mc_experiments SET stage='production', updated=? WHERE id=?", (_now(), eid))
        self._log(eid, me["username"], "production", "Authorized once and handed off: AXoR doesn't deploy. Deploy exactly the approved artifact, then record it here.")
        return self.experiment(me, eid)

    def revise(self, me, eid, note=""):
        """Back to evaluation after a rejection, a request for changes, an expiry, or to withdraw a pending request."""
        e = self._exp(me, eid)
        self._open(e, "recommendation", "approval")
        a = self._approval(e["approval_id"])
        if a and a["status"] == "consumed": raise HTTPException(409, "It was authorized already: record the deploy, or close the experiment.")
        if a and a["status"] in ("pending", "approved") and self.co:
            from .company import DecideIn as CoDecide
            self.co.decide(me, a["id"], CoDecide(decision="reject", reason=note.strip() or "Withdrawn to revise the evidence."))
        self.db.q("UPDATE mc_experiments SET stage='evaluation', approval_id=NULL, evidence_hash=NULL, review=NULL, updated=? WHERE id=?", (_now(), eid))
        why = (a and a.get("reason")) or note.strip()
        self._log(eid, me["username"], "revise", "Back to evaluation" + (f" ({a['status']})" if a else "") + (f": {why}" if why else "."))
        return self.experiment(me, eid)

    def deployed(self, me, eid, b: DeployIn):
        e = self._exp(me, eid)
        self._open(e, "production")
        a = self._approval(e["approval_id"])
        if not a or a["status"] != "consumed" or (a["execution"] or {}).get("status") != "handed_off": raise HTTPException(409, "It wasn't authorized through the gateway.")
        if _sha(self._evidence(e)) != a["hash"]: raise HTTPException(409, "The evidence no longer matches what was approved.")
        if looks_secret(b.version) or looks_secret(b.note): raise HTTPException(400, SECRET_HINT)
        mid = b.miner_id or e["miner_id"]
        if mid: self._miner(me, mid)
        art = _load(e["artifact"], {})
        prev = mid and self.db.q("SELECT id FROM mc_deploys WHERE miner_id=? AND status='active' ORDER BY id DESC LIMIT 1", (mid,), one=True)
        now = _now()
        if mid and not prev:  # the first recorded deploy: what ran before it is the version a rollback restores
            m = self.db.q("SELECT version FROM mc_miners WHERE id=?", (mid,), one=True)
            h = self.db.q("SELECT version FROM mc_health WHERE miner_id=? AND version IS NOT NULL ORDER BY ts DESC LIMIT 1", (mid,), one=True)
            was = (m and m["version"]) or (h and h["version"])
            if was:
                prev = self.db.q("""INSERT INTO mc_deploys (user_id, miner_id, comp_id, version, status, note, by_user, ts) VALUES (?,?,?,?,'active',?,?,?)
                                    RETURNING id""", (me["id"], mid, e["comp_id"], was, "The version before the first recorded deploy.", me["username"], now), one=True)
        if prev: self.db.q("UPDATE mc_deploys SET status='replaced' WHERE id=?", (prev["id"],))
        did = self.db.q("""INSERT INTO mc_deploys (user_id, miner_id, comp_id, exp_id, approval_id, version, ref, status, prev_id, note, by_user, ts)
                           VALUES (?,?,?,?,?,?,?,'active',?,?,?,?) RETURNING id""",
                        (me["id"], mid, e["comp_id"], eid, a["id"], b.version.strip(), art.get("ref"), prev and prev["id"], b.note.strip() or None, me["username"], now), one=True)["id"]
        if mid: self.db.q("UPDATE mc_miners SET version=?, updated=? WHERE id=?", (b.version.strip(), now, mid))
        self.db.q("UPDATE mc_experiments SET stage='monitoring', deploy_id=?, monitor_since=?, updated=? WHERE id=?", (did, now, now, eid))
        self._log(eid, me["username"], "production", f"Deployed {b.version.strip()}" + (f" on miner #{mid}" if mid else "") + ". Monitoring from now.")
        return self.experiment(me, eid)

    def _monitor(self, e, cmp):
        """What the evaluator reported since the deploy, against the evaluation."""
        since, prim = e["monitor_since"] or _now(), e["primary_metric"]
        out = {"since": since, "metrics": {}, "verdict": "waiting"}
        for k in {prim, *CONSTRAINTS}:
            vals = [r["value"] for r in self.db.q("SELECT value FROM mc_metrics WHERE comp_id=? AND metric=? AND ts>=? AND source!='lab'", (e["comp_id"], k, since))]
            s, x = stats(vals), cmp.get(k)
            if not s: continue
            m = {"live": s}
            if x:
                up = METRICS[k][2] == "up"
                d = s["mean"] - x["base"]["mean"]
                worse = (d < 0) if up else (d > 0)
                m |= {"vs_base": d, "vs_cand": s["mean"] - x["cand"]["mean"], "worse": bool(worse and abs(d) > (x["band"] or 0))}
            out["metrics"][k] = m
        p = out["metrics"].get(prim)
        if p and "worse" in p:
            out["verdict"] = "regressed" if p["worse"] else "holding"
            if not p["worse"] and any(v.get("worse") for k, v in out["metrics"].items() if k != prim): out["verdict"] = "constraint"
        elif p: out["verdict"] = "no_baseline"
        return out

    def close(self, me, eid, b: CloseIn):
        e = self._exp(me, eid)
        self._open(e)
        if b.outcome == "kept" and e["stage"] != "monitoring": raise HTTPException(409, "Only a deployed experiment can be kept.")
        if b.outcome == "rolled_back":
            if e["stage"] != "monitoring" or not e["deploy_id"]: raise HTTPException(409, "Nothing was deployed to roll back.")
            d = self.db.q("SELECT * FROM mc_deploys WHERE id=?", (e["deploy_id"],), one=True)
            prev = d["prev_id"] and self.db.q("SELECT * FROM mc_deploys WHERE id=?", (d["prev_id"],), one=True)
            now = _now()
            self.db.q("UPDATE mc_deploys SET status='rolled_back' WHERE id=?", (d["id"],))
            if prev:
                self.db.q("""INSERT INTO mc_deploys (user_id, miner_id, comp_id, exp_id, approval_id, version, ref, status, prev_id, rollback_of, note, by_user, ts)
                             VALUES (?,?,?,?,?,?,?,'active',?,?,?,?,?)""", (me["id"], d["miner_id"], d["comp_id"], prev["exp_id"], prev["approval_id"], prev["version"],
                                                                         prev["ref"], d["id"], d["id"], _clip(b.reason, 600) or "Rolled back.", me["username"], now))
                if d["miner_id"]: self.db.q("UPDATE mc_miners SET version=?, updated=? WHERE id=?", (prev["version"], now, d["miner_id"]))
        elif b.outcome == "abandoned":
            a = self._approval(e["approval_id"])
            if a and a["status"] in ("pending", "approved") and self.co:
                from .company import DecideIn as CoDecide
                self.co.decide(me, a["id"], CoDecide(decision="reject", reason=b.reason.strip() or "The experiment was abandoned."))
        self.db.q("UPDATE mc_experiments SET status=?, outcome_reason=?, updated=? WHERE id=?", (b.outcome, b.reason.strip() or None, _now(), eid))
        self._log(eid, me["username"], b.outcome, {"kept": "Kept in production", "rolled_back": "Rolled back to the previous version (carry it out on the miner)",
                                                  "abandoned": "Abandoned"}[b.outcome] + (f": {b.reason.strip()}" if b.reason.strip() else "."))
        return self.experiment(me, eid)

    def delete_experiment(self, me, eid):
        e = self._exp(me, eid)
        if e["deploy_id"]: raise HTTPException(409, "It reached production: it stays on the record. Close it instead.")
        a = self._approval(e["approval_id"])
        if a and a["status"] in ("pending", "approved", "consumed"): raise HTTPException(409, "It's under approval: revise or abandon it first.")
        self.db.q("DELETE FROM mc_log WHERE exp_id=?", (eid,))
        self.db.q("DELETE FROM mc_experiments WHERE id=?", (eid,))
        return {"ok": True}

    # ---------- rewards and economics ----------
    def costs(self, me):
        return [dict(r) for r in self.db.q("SELECT * FROM mc_costs WHERE user_id=? ORDER BY id DESC", (me["id"],))]

    def add_cost(self, me, b: CostIn):
        if b.campaign_id: self.m._own(me, b.campaign_id)
        if b.comp_id: self._comp(me, b.comp_id)
        for d in (b.starts, b.ends):
            if d and not re.match(r"^\d{4}-\d{2}-\d{2}$", d): raise HTTPException(400, "Dates are YYYY-MM-DD.")
        if looks_secret(b.label): raise HTTPException(400, SECRET_HINT)
        self.db.q("INSERT INTO mc_costs (user_id, campaign_id, comp_id, kind, label, usd, period, starts, ends, created) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (me["id"], b.campaign_id, b.comp_id, b.kind, b.label.strip(), b.usd, b.period, b.starts or None, b.ends or None, _now()))
        return self.rewards(me)

    def delete_cost(self, me, cid):
        if not self.db.q("DELETE FROM mc_costs WHERE id=? AND user_id=? RETURNING id", (cid, me["id"]), one=True): raise HTTPException(404, "There's no such entry.")
        return self.rewards(me)

    @staticmethod
    def _per_day(cost, start, end):
        """A cost entry's dollars over [start, end), as dollars a day."""
        days = (end - start) / DAY
        def day(s, d):
            try: return time.mktime(time.strptime(s, "%Y-%m-%d")) if s else d
            except ValueError: return d
        a, b = max(start, day(cost["starts"], start)), min(end, day(cost["ends"], end) + (DAY if cost["ends"] else 0))
        if cost["period"] == "once":
            t = day(cost["starts"], cost["created"])
            return cost["usd"] / days if start <= t < end else 0.0
        if b <= a: return 0.0
        return cost["usd"] / PERIODS[cost["period"]] * ((b - a) / DAY) / days

    def rewards(self, me, days=30):
        now, s = _now(), self.settings(me)
        start = now - days * DAY
        tao = (self.m.data() or {}).get("tao_usd")
        rate = s["usd_per_mtok"]
        costs = self.costs(me)
        rows, tot = [], {"tau_day": 0.0, "usd_day": 0.0, "cost_day": 0.0, "payout_day": 0.0, "tokens_day": 0, "token_usd_day": 0.0}
        for c in self._campaigns(me):
            ours, smp = self._chain(c)
            tau = round(sum(r.get("em", 0) for r in ours), 6)
            hks = [r["hk"] for r in ours]
            hist = []
            if hks:
                hist = self.db.q(f"""SELECT CAST(ts/86400 AS INTEGER) d, AVG(e) em FROM (SELECT sample_id, MIN(ts) ts, SUM(em) e FROM mh_points WHERE netuid=? AND mech=?
                                    AND ts>? AND hk IN ({','.join('?' * len(hks))}) GROUP BY sample_id) GROUP BY d ORDER BY d""", (c["netuid"], c["mech"], start, *hks))
            realized = round(statistics.fmean([h["em"] for h in hist]), 6) if hist else None
            wids = [w["id"] for w in self.db.q("SELECT id FROM mw_comps WHERE campaign_id=?", (c["id"],))]
            ph = ",".join("?" * len(wids)) or "NULL"
            tok = self.db.q("SELECT COALESCE(SUM(tokens),0) n FROM mh_runs WHERE campaign_id=? AND started>?", (c["id"], start), one=True)["n"]
            tok += self.db.q(f"SELECT COALESCE(SUM(tokens),0) n FROM mw_runs WHERE comp_id IN ({ph}) AND started>?", (*wids, start), one=True)["n"]
            sbx = self.db.q(f"SELECT COALESCE(SUM(cost),0) usd FROM mw_sbx WHERE comp_id IN ({ph}) AND started>?", (*wids, start), one=True)["usd"] or 0
            bench = 0.0
            if self._has("mb_runs") and self._has("mb_flows"):
                bench = self.db.q(f"""SELECT COALESCE(SUM(r.cost),0) usd FROM mb_runs r JOIN mb_flows f ON f.id=r.flow_id WHERE f.comp_id IN ({ph}) AND r.started>?""",
                                  (*wids, start), one=True)["usd"] or 0
            mine_c = [x for x in costs if x["campaign_id"] == c["id"] or (x["comp_id"] in wids)]
            entered = {k: round(sum(self._per_day(x, start, now) for x in mine_c if x["kind"] == k), 4) for k in COST_KINDS}
            payout = entered.pop("payout")
            tokens_day = round(tok / days)
            token_usd = round(tokens_day / 1e6 * rate, 4) if rate else None
            cost_day = round(sum(entered.values()) + sbx / days + bench / days + (token_usd or 0), 4)
            usd_day = round(tau * tao, 2) if tao is not None else None
            net = round((usd_day or 0) + payout - cost_day, 2) if usd_day is not None else None
            exp = s["expected"].get(str(c["id"]))
            row = {"campaign": c["id"], "netuid": c["netuid"], "subnet": self.m._name(c), "comp": self.m._comp(c), "miners": len(ours),
                   "best_rank": min((r["rank"] for r in ours if r.get("rank")), default=None), "tau_day": tau, "usd_day": usd_day, "realized_tau_day": realized,
                   "history": [{"day": h["d"] * DAY, "tau": round(h["em"], 6)} for h in hist], "payout_day": round(payout, 2),
                   "costs_day": {**entered, "sandbox": round(sbx / days, 4), "workflow": round(bench / days, 4), "tokens": token_usd},
                   "cost_day": cost_day, "tokens_day": tokens_day, "net_day": net, "expected_month": exp,
                   "realized_month": round(((realized or 0) * tao + payout) * 30.4, 2) if tao is not None and realized is not None else None,
                   "roi": round(((usd_day or 0) + payout) / cost_day, 2) if cost_day and usd_day is not None else None, "snapshot": smp and smp["ts"]}
            rows.append(row)
            tot["tau_day"] += tau; tot["usd_day"] += usd_day or 0; tot["cost_day"] += cost_day; tot["payout_day"] += payout
            tot["tokens_day"] += tokens_day; tot["token_usd_day"] += token_usd or 0
        tot = {k: round(v, 4) for k, v in tot.items()} | {"net_day": round(tot["usd_day"] + tot["payout_day"] - tot["cost_day"], 2) if tao is not None else None}
        teams = []
        for w, c in self._comps(me):
            prim = self.primary(me, w["id"])
            last = self.db.q("SELECT value, ts FROM mc_metrics WHERE comp_id=? AND metric=? ORDER BY ts DESC LIMIT 1", (w["id"], prim), one=True)
            tok = self.db.q("SELECT COALESCE(SUM(tokens),0) n FROM mw_runs WHERE comp_id=? AND started>?", (w["id"], start), one=True)["n"]
            teams.append({"id": w["id"], "label": self._label(w, c), "campaign": c["id"], "share": w["share"], "primary": prim, "score": last and last["value"],
                          "score_ts": last and last["ts"], "tokens_day": round(tok / days)})
        return {"days": days, "tao_usd": tao, "settings": s, "campaigns": rows, "totals": tot, "teams": teams, "costs": costs, "kinds": COST_KINDS}

    # ---------- the approval center ----------
    def approvals(self, me):
        now, out = _now(), []
        if self._has("co_approvals") and self.co:
            c = self.co._company(me, create=False)
            if c:
                for a in self.db.q("""SELECT * FROM co_approvals WHERE company_id=? AND (status IN ('pending','approved') OR (status='consumed' AND created>?))
                                      ORDER BY created DESC LIMIT 60""", (c["id"], now - WEEK)):
                    st = "expired" if a["status"] in ("pending", "approved") and (a["expires_at"] or 0) < now else a["status"]
                    if st == "expired": continue
                    ex = self.db.q("SELECT status FROM co_executions WHERE approval_id=?", (a["id"],), one=True)
                    e = a["artifact_kind"] == "mining_experiment" and self.db.q("SELECT id, stage, status, comp_id FROM mc_experiments WHERE id=? AND user_id=?",
                                                                                 (a["artifact_id"], me["id"]), one=True)
                    if st == "consumed" and not (e and e["stage"] == "production"): continue  # done with: only a deploy still to record stays
                    out.append({"source": "experiment" if e else "company", "id": a["id"], "title": a["title"], "action": a["action_type"], "risk": a["risk"],
                                "status": st, "requested_by": a["requested_by"], "created": a["created"], "expires_at": a["expires_at"],
                                "reason": _clip(a["reason"], 600), "expected": a["expected"], "rollback": a["rollback"], "hash": a["artifact_hash"],
                                "evidence": _load(a["evidence"], {}), "payload": _load(a["payload"], {}), "execution": ex and ex["status"],
                                "experiment": e and {"id": e["id"], "stage": e["stage"], "comp": e["comp_id"]}})
        for c in self._campaigns(me):
            for a in self.db.q("""SELECT id, type, kind, title, detail, reason, created, status, safe FROM mh_actions WHERE campaign_id=? AND status='awaiting'
                                  ORDER BY created DESC LIMIT 20""", (c["id"],)):
                out.append({"source": "miner_action", "id": a["id"], "title": a["title"], "action": a["kind"] or a["type"], "risk": "low" if a["safe"] else "medium",
                            "status": "pending", "created": a["created"], "reason": _clip(a["reason"] or a["detail"], 600), "campaign": c["id"],
                            "where": f"SN{c['netuid']} · {self.m._comp(c)}"})
        if self._has("mb_tasks") and self._has("mb_flows"):
            for w, c in self._comps(me):
                f = self.db.q("SELECT id FROM mb_flows WHERE comp_id=?", (w["id"],), one=True)
                if not f: continue
                for t in self.db.q("SELECT id, title, updated FROM mb_tasks WHERE flow_id=? AND status='ready' ORDER BY updated DESC LIMIT 10", (f["id"],)):
                    out.append({"source": "merge", "id": t["id"], "title": f"Merge: {t['title']}", "action": "merge", "risk": "medium", "status": "pending",
                                "created": t["updated"], "team": w["id"], "where": self._label(w, c)})
        order = {"approved": 0, "pending": 1, "consumed": 2}
        out.sort(key=lambda a: (order.get(a["status"], 3), -(a["created"] or 0)))
        return {"approvals": out, "gateway": bool(self.co)}

    # ---------- monitoring ----------
    def monitoring(self, me):
        now, checks = _now(), []
        add = lambda level, kind, title, detail, go=None: checks.append({"level": level, "kind": kind, "title": title, "detail": detail, "go": go})
        for m in self.miners(me)["miners"]:
            nm = m["name"] or m["hotkey"][:8]
            if m["health"] == "silent": add("stop", "miner", f"{nm} went silent", f"No health report since {time.strftime('%H:%M', time.localtime(m['last_seen']))}.", {"miner": m["id"]})
            elif m["health"] == "down": add("stop", "miner", f"{nm} reports down", "Its last health report says it isn't serving.", {"miner": m["id"]})
            elif m["health"] == "erroring": add("warn", "miner", f"{nm} reports {m['errors']} errors", "Read its logs in the miner's workspace.", {"miner": m["id"]})
            if m["onchain"]["registered"] is False and not m["manual"]: add("warn", "chain", f"{nm} isn't in the latest snapshot", "Deregistered, or the key changed.", {"miner": m["id"]})
            if m["uptime_24h"] is not None and m["uptime_24h"] < 0.95: add("warn", "miner", f"{nm} was up {m['uptime_24h'] * 100:.0f}% of the last 24 h", "Below 95%.", {"miner": m["id"]})
        for w, c in self._comps(me):
            ev = self._evaluator(me, w["id"])
            if ev["state"] == "stale": add("warn", "evaluator", f"{self._label(w, c)}: the evaluator went quiet", f"No report for over {STALE_H} hours.", {"perf": w["id"]})
            try: st = self.st.status(me, w["id"])
            except HTTPException: continue
            if st["state"] == "stuck": add("warn", "team", f"{self._label(w, c)}: the team is stuck", st["line"], {"team": w["id"]})
        for e in self.db.q("SELECT * FROM mc_experiments WHERE user_id=? AND status='open' AND stage='monitoring'", (me["id"],)):
            mon = self._exp_out(me, e)["monitor"]
            if mon and mon["verdict"] in ("regressed", "constraint"):
                add("stop" if mon["verdict"] == "regressed" else "warn", "deploy", f"After the deploy of {e['title']!r}: " + ("the primary metric is worse than the baseline" if mon["verdict"] == "regressed" else "a constraint got worse"),
                    "Roll back, or keep it if you accept the trade.", {"exp": e["id"]})
        for c in self._campaigns(me):
            for a in self.db.q("SELECT title, detail FROM mh_alerts WHERE campaign_id=? AND status='open' AND level='critical'", (c["id"],)):
                add("stop", "alert", f"SN{c['netuid']}: {a['title']}", _clip(a["detail"], 300), {"campaign": c["id"]})
        if getattr(self, "ops", None): checks += self.ops.checks(me)  # budget and performance alerts (mining_ops.py)
        checks.sort(key=lambda x: ("stop", "warn", "info").index(x["level"]))
        return {"checks": checks, "at": now}

    # ---------- agents ----------
    def agents(self, me):
        now, out = _now(), []
        for w, c in self._comps(me, closed=True):
            working = {r["agent_id"] for r in self.db.q("SELECT agent_id FROM mw_runs WHERE comp_id=? AND status='running'", (w["id"],))}
            stats_ = {r["agent_id"]: r for r in self.db.q("""SELECT agent_id, COUNT(*) runs, SUM(status='failed') failed, COALESCE(SUM(tokens),0) tokens, MAX(started) last
                                                            FROM mw_runs WHERE comp_id=? AND started>? GROUP BY agent_id""", (w["id"], now - WEEK))}
            done = {r["agent_id"]: r["n"] for r in self.db.q("SELECT agent_id, COUNT(*) n FROM mw_tasks WHERE comp_id=? AND status='done' AND " + not_dropped(self.db) + " GROUP BY agent_id", (w["id"],))}
            for a in self.db.q("SELECT id, role, name, title, job, icon, color, squad, lead, head, active FROM mw_agents WHERE comp_id=? ORDER BY lead DESC, head DESC, squad, id", (w["id"],)):
                s = stats_.get(a["id"]) or {}
                out.append({**{k: a[k] for k in ("id", "role", "name", "title", "icon", "color", "squad")}, "job": _clip(a["job"], 200), "lead": bool(a["lead"]), "head": bool(a["head"]),
                            "status": "working" if a["id"] in working else "on" if a["active"] else "off", "team": w["id"], "team_label": self._label(w, c),
                            "team_open": w["status"] != "closed", "netuid": c["netuid"], "done": done.get(a["id"], 0), "runs_week": s.get("runs", 0),
                            "failed_week": s.get("failed") or 0, "tokens_week": s.get("tokens", 0), "last": s.get("last")})
        return {"agents": out}

    # ---------- the dashboard and a competition's HQ ----------
    def _comp_row(self, me, w, c, now):
        prim = self.primary(me, w["id"])
        pts = self.db.q("SELECT value, ts FROM mc_metrics WHERE comp_id=? AND metric=? ORDER BY ts DESC LIMIT 2", (w["id"], prim))
        try: st = self.st.status(me, w["id"])
        except HTTPException: st = {"state": "idle", "line": ""}
        s = self.w._summary(w, c)
        exps = self.db.q("SELECT stage, COUNT(*) n FROM mc_experiments WHERE comp_id=? AND user_id=? AND status='open' GROUP BY stage", (w["id"], me["id"]))
        return {"id": w["id"], "label": self._label(w, c), "name": w["name"], "number": w["number"], "netuid": c["netuid"], "subnet": self.m._name(c), "campaign": c["id"],
                "status": w["status"], "state": st["state"], "line": st["line"], "share": w["share"], "ends": w["ends"] or "", "agents": s["agents"], "active": s["active"],
                "working": s["working"], "waiting": s["waiting"], "primary": prim, "score": pts[0]["value"] if pts else None, "score_ts": pts[0]["ts"] if pts else None,
                "score_prev": pts[1]["value"] if len(pts) > 1 else None, "evaluator": self._evaluator(me, w["id"])["state"],
                "experiments": {r["stage"]: r["n"] for r in exps}}

    def dashboard(self, me, fresh=False):
        hit = self.cache.get(me["id"])
        if hit and not fresh and _now() - hit[0] < CACHE: return hit[1]
        out = self._dashboard(me)
        self.cache[me["id"]] = (_now(), out)
        return out

    def _dashboard(self, me):
        now = _now()
        comps = [self._comp_row(me, w, c, now) for w, c in self._comps(me)]
        camps = []
        for c in self._campaigns(me):
            ours, smp = self._chain(c)
            b = self.db.q("SELECT headline, standing, ts FROM mh_briefs WHERE campaign_id=? ORDER BY id DESC LIMIT 1", (c["id"],), one=True)
            camps.append({"id": c["id"], "netuid": c["netuid"], "subnet": self.m._name(c), "comp": self.m._comp(c), "status": c["status"], "miners": len(ours),
                          "best_rank": min((r["rank"] for r in ours if r.get("rank")), default=None), "of": smp and smp["stats"].get("miners"),
                          "tau_day": round(sum(r.get("em", 0) for r in ours), 6), "target": c["settings"]["target"], "standing": b and b["standing"],
                          "headline": b and _clip(b["headline"], 200), "teams": sum(1 for x in comps if x["campaign"] == c["id"])})
        ap = self.approvals(me)["approvals"]
        mon = self.monitoring(me)["checks"]
        mins = self.miners(me)["miners"]
        exps = self.db.q("SELECT stage, COUNT(*) n FROM mc_experiments WHERE user_id=? AND status='open' GROUP BY stage", (me["id"],))
        tao = (self.m.data() or {}).get("tao_usd")
        scored = [x for x in comps if x["score"] is not None]
        return {"at": now, "campaigns": camps, "comps": comps, "approvals": ap[:8], "approvals_n": sum(1 for a in ap if a["status"] in ("pending", "approved")),
                "critical": [x for x in mon if x["level"] == "stop"][:8], "checks_n": len(mon), "experiments": {r["stage"]: r["n"] for r in exps},
                "miners": {"n": len(mins), "up": sum(1 for m in mins if m["health"] == "up"), "silent": sum(1 for m in mins if m["health"] in ("silent", "down")),
                           "unknown": sum(1 for m in mins if m["health"] == "unknown")},
                "score": max(scored, key=lambda x: x["score_ts"]) if scored else None, "evaluators": sum(1 for x in comps if x["evaluator"] != "none"),
                "tau_day": round(sum(x["tau_day"] for x in camps), 6), "tao_usd": tao, "stages": [[k, STAGE_LABEL[k]] for k in STAGES], "metrics": METRICS,
                "gateway": bool(self.co)}

    def comp_hq(self, me, wid):
        w, c = self._comp(me, wid)
        now = _now()
        row = self._comp_row(me, w, c, now)
        latest = {}
        for r in self.db.q("SELECT metric, value, ts, source FROM mc_metrics WHERE id IN (SELECT MAX(id) FROM mc_metrics WHERE comp_id=? GROUP BY metric)", (wid,)):
            latest[r["metric"]] = {"v": r["value"], "ts": r["ts"], "src": r["source"]}
        b = self.db.q("SELECT headline, standing, summary, priorities, stats, ts FROM mh_briefs WHERE campaign_id=? ORDER BY id DESC LIMIT 1", (c["id"],), one=True)
        recs = self.db.q("SELECT id, title, impact, effort, agent FROM mh_recs WHERE campaign_id=? AND status='open' ORDER BY id DESC LIMIT 6", (c["id"],))
        notes = self.db.q("SELECT COUNT(*) n FROM mw_notes WHERE comp_id=?", (wid,), one=True)["n"]
        files = self.db.q("SELECT COUNT(*) n FROM mw_files WHERE comp_id=?", (wid,), one=True)["n"]
        squads = self.db.q("SELECT COALESCE(squad,'') squad, COUNT(*) n, SUM(active) on_ FROM mw_agents WHERE comp_id=? GROUP BY squad", (wid,))
        lead = self.db.q("SELECT name, title FROM mw_agents WHERE comp_id=? AND lead=1 ORDER BY id LIMIT 1", (wid,), one=True)
        shared = self.db.q("SELECT COUNT(*) n FROM mk_items WHERE comp_id=?", (wid,), one=True)["n"] if self._has("mk_items") else 0
        chain, _ = self._chain(c)
        ms = [self._miner_state(m, {r["hk"]: r for r in chain}, now) for m in self.db.q(
            "SELECT * FROM mc_miners WHERE user_id=? AND campaign_id=? AND (comp_id=? OR comp_id IS NULL) ORDER BY id", (me["id"], c["id"], wid))]
        exps = [self._exp_out(me, e, full=False) for e in self.db.q("SELECT * FROM mc_experiments WHERE comp_id=? AND user_id=? ORDER BY status='open' DESC, updated DESC LIMIT 12", (wid, me["id"]))]
        return row | {"goal": w["goal"] or "", "description": _clip(w["description"], 1200), "link": w["link"] or "", "starts": w["starts"] or "", "latest": latest,
                      "brief": b and {"headline": b["headline"], "standing": b["standing"], "summary": _clip(b["summary"], 800), "priorities": _load(b["priorities"], [])[:6],
                                      "stats": _load(b["stats"], {}), "ts": b["ts"]}, "recs": recs, "notes": notes, "files": files, "shared": shared,
                      "squads": [{"squad": s["squad"], "n": s["n"], "on": s["on_"] or 0} for s in squads], "lead": lead, "miners": ms, "exps": exps,
                      "metrics": METRICS, "stages": [[k, STAGE_LABEL[k]] for k in STAGES]}


def build(work, require):
    r = APIRouter(prefix="/api/mining/command")
    gate = work.m.hub.gate if work.m.hub else (lambda me: me)
    user = lambda req: gate(require(req))
    cm = Command(work)
    r.state = {"command": cm}

    @r.get("")
    def dashboard(req: Request, fresh: bool = False): return cm.dashboard(user(req), fresh)

    @r.get("/comps/{wid}")
    def comp(wid: int, req: Request): return cm.comp_hq(user(req), wid)

    @r.get("/comps/{wid}/performance")
    def performance(wid: int, req: Request, days: int = 30): return cm.performance(user(req), wid, max(1, min(90, days)))

    @r.get("/comps/{wid}/reports")
    def report_runs(wid: int, req: Request): return cm.report_runs(user(req), wid)

    @r.post("/metrics")
    def add_metrics(b: MetricIn, req: Request): return cm.add_metrics(user(req), b)

    @r.delete("/metrics/{mid}")
    def delete_metric(mid: int, req: Request): return cm.delete_metric(user(req), mid)

    @r.post("/ingest")
    async def ingest(req: Request):
        """For the evaluator or the miner: Authorization: Bearer mcx_… (Command center → Settings makes keys). No session."""
        auth = req.headers.get("authorization") or ""
        try: body = await req.json()
        except ValueError: raise HTTPException(400, "Send a JSON body.")
        return cm.ingest(auth[7:].strip() if auth.lower().startswith("bearer ") else "", body)

    @r.get("/experiments")
    def experiments(req: Request, comp: int | None = None): return cm.experiments(user(req), comp)

    @r.post("/experiments")
    def new_experiment(b: ExperimentIn, req: Request): return cm.new_experiment(user(req), b)

    @r.get("/experiments/{eid}")
    def experiment(eid: int, req: Request): return cm.experiment(user(req), eid)

    @r.patch("/experiments/{eid}")
    def patch_experiment(eid: int, b: ExperimentPatch, req: Request): return cm.patch_experiment(user(req), eid, b)

    @r.delete("/experiments/{eid}")
    def delete_experiment(eid: int, req: Request): return cm.delete_experiment(user(req), eid)

    @r.post("/experiments/{eid}/step")
    def step(eid: int, b: StepIn, req: Request): return cm.step(user(req), eid, b)

    @r.post("/experiments/{eid}/link")
    def link(eid: int, b: LinkIn, req: Request): return cm.link(user(req), eid, b)

    @r.post("/experiments/{eid}/runs")
    def add_runs(eid: int, b: RunsIn, req: Request): return cm.add_runs(user(req), eid, b)

    @r.post("/experiments/{eid}/runs/report")
    def runs_report(eid: int, req: Request, side: str, label: str):
        if side not in ("base", "cand"): raise HTTPException(400, "side is base or cand.")
        return cm.runs_from_reports(user(req), eid, side, label[:80])

    @r.delete("/experiments/{eid}/runs/{side}/{idx}")
    def delete_run(eid: int, side: str, idx: int, req: Request):
        if side not in ("base", "cand"): raise HTTPException(400, "side is base or cand.")
        return cm.delete_run(user(req), eid, side, idx)

    @r.post("/experiments/{eid}/review")
    def review(eid: int, req: Request): return cm.review(user(req), eid)

    @r.post("/experiments/{eid}/approval")
    def request_approval(eid: int, b: NoteIn, req: Request): return cm.request_approval(user(req), eid, b.note)

    @r.post("/experiments/{eid}/decide")
    def decide(eid: int, b: DecideIn, req: Request): return cm.decide(user(req), eid, b)

    @r.post("/experiments/{eid}/authorize")
    def authorize(eid: int, req: Request): return cm.authorize(user(req), eid)

    @r.post("/experiments/{eid}/revise")
    def revise(eid: int, b: NoteIn, req: Request): return cm.revise(user(req), eid, b.note)

    @r.post("/experiments/{eid}/deployed")
    def deployed(eid: int, b: DeployIn, req: Request): return cm.deployed(user(req), eid, b)

    @r.post("/experiments/{eid}/close")
    def close(eid: int, b: CloseIn, req: Request): return cm.close(user(req), eid, b)

    @r.get("/miners")
    def miners(req: Request): return cm.miners(user(req))

    @r.post("/miners")
    def add_miner(b: MinerIn, req: Request): return cm.add_miner(user(req), b)

    @r.get("/miners/{mid}")
    def miner(mid: int, req: Request): return cm.miner(user(req), mid)

    @r.patch("/miners/{mid}")
    def patch_miner(mid: int, b: MinerPatch, req: Request): return cm.patch_miner(user(req), mid, b)

    @r.delete("/miners/{mid}")
    def delete_miner(mid: int, req: Request): return cm.delete_miner(user(req), mid)

    @r.get("/rewards")
    def rewards(req: Request, days: int = 30): return cm.rewards(user(req), max(1, min(90, days)))

    @r.post("/costs")
    def add_cost(b: CostIn, req: Request): return cm.add_cost(user(req), b)

    @r.delete("/costs/{cid}")
    def delete_cost(cid: int, req: Request): return cm.delete_cost(user(req), cid)

    @r.get("/approvals")
    def approvals(req: Request): return cm.approvals(user(req))

    @r.get("/monitoring")
    def monitoring(req: Request): return cm.monitoring(user(req))

    @r.get("/agents")
    def agents(req: Request): return cm.agents(user(req))

    @r.get("/settings")
    def settings(req: Request):
        me = user(req)
        return {"settings": cm.settings(me), "metrics": METRICS} | cm.keys(me)

    @r.patch("/settings")
    def save_settings(b: SettingsIn, req: Request): return cm.save_settings(user(req), b)

    @r.post("/keys")
    def new_key(b: KeyIn, req: Request): return cm.new_key(user(req), b)

    @r.delete("/keys/{kid}")
    def revoke_key(kid: int, req: Request): return cm.revoke_key(user(req), kid)

    @r.put("/keys/{kid}/holder")
    def set_holder(kid: int, b: HolderIn, req: Request):  # D4.2: the Owner only; audited
        return cm.set_holder(user(req), kid, b, req.client.host if req.client else "")

    return r
