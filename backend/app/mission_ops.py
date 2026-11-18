"""AXoR Mission Operations: one operational model over every engine, and the console that reads it (Control Hub → Overview).

From the 11-11 assessment ("AXoR G5: Self-Evolving Agent Ecosystem"): the engines are built, what was missing is one answer to
"what are we trying to achieve, what is happening, are we progressing, what prevents success, what happens next". Nothing here
runs work and nothing is rebuilt: every figure is DERIVED from the records the engines already keep (ctl_tasks, mw_*, mx_*,
ac_runs, io_*, ev_*, mb_*, au_*, wf_*, mc_*, mh_briefs). The only table of its own is mo_criteria: the acceptance criteria a
person adds to a mission, their weights, and what they attested with evidence.

- One task state for every engine (STATES): PLANNED, READY, RUNNING, REVIEW, VERIFIED, and off the path BLOCKED, FAILED, PAUSED,
  CANCELLED. It is layered over task_lifecycle.stage() (Control Hub tasks), the team boards and the mission engines. DONE is not
  VERIFIED: work that finished without an independent verdict on record (a reviewer other than its author, or your decision)
  stays in REVIEW.
- Two progress figures per mission, never mixed. Work progress: planned / completed / reviewed / verified. Objective progress:
  P = Σ wᵢ·sᵢ / Σ wᵢ over weighted acceptance criteria, where a criterion that isn't verified counts 0. A competition's criteria
  come from records (registration, validation on the frozen benchmark, reliability, submission, official rank, holding it).
  A rank that can't be read is UNKNOWN with the reason and what's needed, never 0.
- Five performance dimensions per competition, kept apart: competition, technical, execution, economic, strategic.
- One decision engine (SITUATIONS): the situation a mission is in → the response → the next action, its owner and the blocker
  in a sentence. Failure classes map to different recoveries (RECOVERY): a quota is waited out, a sandbox is repaired, a wrong
  implementation is re-planned; nothing is "retry everything".
- One decision queue: infrastructure failures, work blocked on a person, regressions, budget, promotions to approve, milestones.
- Run accountability: every finished run in exactly one of the assessment's six outcomes; "inconclusive" always carries a reason
  and a next action.
- Budget: the four scopes (company, competition, team, agent/task) with what is set, spent and where it is enforced, and a
  reconciliation per team of its budget against every count of its tokens.
- Evolution registry: the separate improvement loops (Evolution Lab, Workforce trials, Workflow improvements and watches,
  Upgrade sprints, Command Center experiments) as one list with one stage and one evidence rule.
- G5 readiness: the assessment's twelve acceptance rows, each computed from records, pass / partial / fail / unknown.
- Drill-downs: an agent (objective, task, last run, tools, sandbox, failures, scores, versions, cost, next action) and a task's
  own graph (mission → task → agent, model, tool calls, sandbox, files, runs, evaluator, result).

Routes are mounted on the Control Hub's router (/api/control/ops…). Registration, submissions, deploys, payments and limits
stay a person's: this module never sets one.
"""
import hashlib, json, logging, math, re, threading, time

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

from . import agent_core
from . import runner as vmrunner  # the VM Docker runner (D-013, G5-4 V4.2): the docker and vm probes read it

DAY = 86400
WEEK = 7 * DAY
STALE_APPROVAL = 3 * DAY     # a pending approval older than this is "stale" in the decision queue
NO_PROGRESS = 3 * DAY        # open work and nothing verified for this long = "no progress"
HOLD_DAYS = 7                # a rank is "held" when the briefs of this many days stay inside the target
COVERAGE_TARGET = 95
CACHE_S = 8

# D-018 (Owner decision 2026-11-11): finished work is Review (delivered, waiting for a verdict), Verified (an independent verdict),
# Completed (closed on a person's word, no verdict), Dropped (the Director decided it is no longer needed: never completed work)
# or Cancelled. COMPLETED and DROPPED come after the path, so PATH stays the first five.
STATES = ("PLANNED", "READY", "RUNNING", "REVIEW", "VERIFIED", "BLOCKED", "FAILED", "PAUSED", "CANCELLED", "COMPLETED", "DROPPED")
PATH = STATES[:5]
STATE_LABEL = {"PLANNED": "Planned", "READY": "Ready", "RUNNING": "Running", "REVIEW": "Review", "VERIFIED": "Verified",
               "BLOCKED": "Blocked", "FAILED": "Failed", "PAUSED": "Paused", "CANCELLED": "Cancelled", "COMPLETED": "Completed", "DROPPED": "Dropped"}
STATE_NOTE = {"PLANNED": "Defined, not ready yet", "READY": "Dependencies and resources satisfied", "RUNNING": "An agent is executing it",
              "REVIEW": "Delivered, waiting for a verdict", "VERIFIED": "Approved by someone other than its author: a person or an agent reviewer (the record says which)",
              "BLOCKED": "A dependency, a question or an approval is needed", "FAILED": "Execution or acceptance failed",
              "PAUSED": "Stopped on purpose", "CANCELLED": "Called off by a person",
              "COMPLETED": "Closed as done on a person's word, without an independent verdict",
              "DROPPED": "Closed by the Director as no longer needed: not completed work"}
STAGE_STATE = {"CREATED": "PLANNED", "QUEUED": "READY", "DISPATCHING": "READY", "DISPATCHED": "READY", "CLAIMED": "READY", "RUNNING": "RUNNING",
               "SUBMITTED": "REVIEW", "VERIFYING": "REVIEW", "FAILED": "FAILED", "TIMEOUT": "FAILED", "CANCELLED": "CANCELLED", "BLOCKED": "BLOCKED"}

# the decision engine: situation → (label, what the system does, what happens next)
SITUATIONS = {
    "successful": ("Successful", "Preserve the result and its evidence", "Freeze the candidate and monitor it"),
    "partial": ("Partial success", "Identify the unmet criteria", "Continue only the missing work"),
    "task_failure": ("Task failure", "Diagnose the root cause", "Re-plan the task or improve the agent"),
    "environment": ("Environment failure", "Identify the infrastructure issue", "Repair the environment, then retry"),
    "provider": ("Provider failure", "Detect the quota or rate limit", "Hold the queue until the provider recovers"),
    "repeated": ("Repeated failure", "Stop repeating the same strategy", "Escalate, or investigate an alternative"),
    "no_progress": ("No progress", "Compare actual progress with the expected pace", "Reassign, redesign or abandon"),
    "uncertain": ("Uncertainty", "Identify the missing evidence", "Research, or run a controlled experiment"),
    "regression": ("Regression", "Compare with the previous version", "Roll back, or ask for approval"),
    "budget": ("Out of budget", "Stop new work at the limit", "Wait for the window, or raise the budget"),
    "blocked": ("Blocked on a decision", "Name who must decide and what", "Decide it; other work continues meanwhile"),
    "paused": ("Paused", "Keep its state as it is", "Resume it when its blocker is cleared"),
    "idle": ("Idle", "Nothing is planned", "Plan the next step toward the objective"),
    "progressing": ("Progressing", "Work is under way", "Let it run; check the next verified result"),
}
# a failure class → what recovers it (never "retry everything"): (situation, recovery, who)
from .orchestrator import OPS_RECOVERY as RECOVERY  # noqa: E402  one taxonomy (orchestrator.FAILURE_CLASSES, G5 Phase 1)
# a competition's strategy portfolio: lanes and the words (in an agent's squad, role, title or job) that put it in one
LANES = (
    ("baseline", "Baseline", "Reference performance", "Keeps the best-performing candidate and its benchmark results.",
     r"release|baseline|quality|benchmark|reference|freeze|frozen"),
    ("optimization", "Optimization", "Improve quality", "Algorithms, features, architecture and implementation improvements.",
     r"engineer|solver|build|model|develop|implement|optimi[sz]|stack|database|data\b|agent build"),
    ("competitor", "Competitor research", "Find advantages", "Studies successful and unsuccessful competitors and tests their techniques.",
     r"intel|competitor|rival|research|rules|scoring|analyst|scout|economic|validator"),
    ("red", "Red team", "Find weaknesses", "Breaks assumptions, finds edge cases and hidden failure modes.",
     r"red.?team|adversar|attack|security|break|edge.?case|fuzz"),
    ("evaluation", "Independent evaluation", "Judge results", "Compares candidates without relying on the agents that made them.",
     r"eval|test|judge|review|verif|qa\b"),
)
OWN_FAULT = ("task", "cap", "low")


def ensure_schema(db):
    db.q("""CREATE TABLE IF NOT EXISTS mo_criteria (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, mission TEXT, key TEXT, label TEXT,
            weight REAL, value REAL, evidence TEXT, off INTEGER DEFAULT 0, by_user TEXT, ts REAL, UNIQUE (user_id, mission, key))""")
    # G5-2: the Re-check limit, in the database so every replica and every restart sees it (Owner review §2A)
    db.q("CREATE TABLE IF NOT EXISTS mo_rechecks (user_id INTEGER, mission TEXT, at REAL, PRIMARY KEY (user_id, mission))")
    # P3 (D-023): a person's verdicts on board work, structured (by user id, never read from text): a sampled agent approval checked
    # by a person (source 'sample': agree / disagree / unsure), or a person's own approval (source 'approval': approve)
    db.q("""CREATE TABLE IF NOT EXISTS mo_verdicts (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, comp_id INTEGER, task_id INTEGER,
            source TEXT, verdict TEXT, by_user_id INTEGER, by_name TEXT, at REAL, note TEXT, UNIQUE (user_id, task_id, source))""")


def _j(s, d=None):
    if isinstance(s, (dict, list)): return s
    try: return json.loads(s) if s else d
    except (TypeError, ValueError): return d


def _clip(s, n): s = str(s or ""); return s if len(s) <= n else s[:n - 1] + "…"
def _pct(a, b): return round(100 * a / b) if b else None
def _s(n, w, s="s"): return f"{n} {w}{'' if n == 1 else s}"
def _marks(xs): return ",".join("?" * len(xs))


# ---------------------------------------------------------------- one task state for every engine
def state_ctl(stage, verified):
    """A Control Hub task's canonical state from its lifecycle stage; COMPLETED is VERIFIED only with an independent verdict."""
    if stage == "COMPLETED": return "VERIFIED" if verified else "REVIEW"
    return STAGE_STATE.get(stage, "PLANNED")


def tl_not_dropped(db):
    from .task_lifecycle import not_dropped
    return not_dropped(db)


def closed_as(t):
    """How a done board task was closed (D-018): the one definition, task_lifecycle.closed_as."""
    from .task_lifecycle import closed_as as one
    return one(t)


def state_board(t, paused=False, verified=False):
    """A team board task's canonical state. `verified`: a review by someone other than its author, or your approval, is on record.
    Done is VERIFIED with a verdict, DROPPED when the Director dropped it, else COMPLETED (closed without a verdict)."""
    st, hold = t.get("status"), t.get("hold")
    if st == "done":
        if closed_as(t) == "dropped": return "DROPPED"
        return "VERIFIED" if verified else "COMPLETED"
    if hold == "failed": return "FAILED"
    if st == "blocked": return "BLOCKED"
    if st == "working": return "RUNNING"
    if st in ("checking", "review"): return "REVIEW"
    if paused: return "PAUSED"
    if st == "queued" or hold == "retry": return "READY"
    if st == "todo": return "READY" if t.get("agent_id") else "PLANNED"
    return "PLANNED"


def state_mission(status, outcome=None, stage=None):
    """A mission engine's run (Mission Control, Workforce, Swarm) as one state. Delivered without a verified outcome is REVIEW."""
    s, o = str(status or "").lower(), str(outcome or "").lower()
    if s in ("cancelled", "canceled", "stopped", "declined"): return "CANCELLED"
    if s in ("failed", "error", "dead"): return "FAILED"
    if s in ("paused",): return "PAUSED"
    if s in ("needs_input", "blocked", "waiting", "needs_approval"): return "BLOCKED"
    if s in ("delivered", "done", "finished", "completed"): return "VERIFIED" if o in ("verified", "pass", "passed", "success") else "REVIEW"
    if s in ("running", "working", "executing"): return "REVIEW" if str(stage or "").lower() in ("verify", "evaluate", "review") else "RUNNING"
    if s in ("queued", "ready", "planned_ready"): return "READY"
    return "PLANNED"


BOARD_LIMIT = 6000  # board tasks read for the console (newest first); the baseline's tasks are read past it


def _board(ch, comp_ids):
    """Every board task of the given teams, with whether an independent verdict is on record for it."""
    if not comp_ids or not ch._has("mw_tasks"): return [], set()
    m = _marks(comp_ids)
    cols = ch._cols("mw_tasks")
    pick = [c for c in ("id", "comp_id", "title", "status", "priority", "agent_id", "hold", "fails", "fail_class", "note", "question", "summary", "updated", "created",
                        "done_at", "runs", "retry_at", "confidence", "mission", "closed_as", "origin") if c in cols]
    rows = ch.db.q(f"SELECT {', '.join(pick)} FROM mw_tasks WHERE comp_id IN ({m}) ORDER BY id DESC LIMIT {BOARD_LIMIT}", list(comp_ids))
    if "origin" in cols:  # Milestone 3: the original scope and person-made additions are always loaded, past the cap, so the baseline stays fixed
        seen = {r["id"] for r in rows}
        for cid in comp_ids:
            first, _cut = baseline_anchor(ch.db, cid)
            rows += [r for r in ch.db.q(f"""SELECT {', '.join(pick)} FROM mw_tasks WHERE comp_id=? AND (origin=? OR origin IS NULL
                                            OR (origin NOT LIKE 'agent:%' AND origin NOT LIKE 'plan:%'))""", (cid, first or "")) if r["id"] not in seen]
    return rows, approved_last(ch, comp_ids)


def approved_last(ch, comp_ids):
    """Board tasks whose last closing record is an approval (a person's, a squad lead's or the Director's: each writes an
    "approve" event). D-018 / 2026-11-11 reconciliation: a finished review run is not a verdict (it can say "revise" or pass the
    task on), and an approval followed by a drop, a close or a person's mark doesn't verify how the task ended. Before this, 46
    production tasks (45 dropped, 1 marked done) counted as Verified on a review run alone."""
    if not comp_ids or not ch._has("mw_events"): return set()
    m = _marks(comp_ids)
    last = {}
    for e in ch.db.q(f"SELECT id, task_id, kind FROM mw_events WHERE comp_id IN ({m}) AND kind IN ('approve','done') AND task_id IS NOT NULL ORDER BY id", list(comp_ids)):
        last[e["task_id"]] = e["kind"]
    return {t for t, k in last.items() if k == "approve"}


def verdict_sources(ch, comp_ids):
    """{task_id: "person" | "agent"} for board tasks with an approval. "person" only from a structured record (mo_verdicts: a person's
    own approval, or a person who agreed with a sampled agent approval, D-023); never from the event's text, which an agent named
    like a user could match. Everything else approved is an agent's (a squad lead's or the Director's)."""
    if not comp_ids or not ch._has("mw_events"): return {}
    m = _marks(comp_ids)
    out = {r["task_id"]: "agent" for r in ch.db.q(f"SELECT DISTINCT task_id FROM mw_events WHERE comp_id IN ({m}) AND kind='approve' AND task_id IS NOT NULL", list(comp_ids))}
    if ch._has("mo_verdicts"):
        for r in ch.db.q(f"SELECT task_id FROM mo_verdicts WHERE comp_id IN ({m}) AND verdict IN ('approve','agree')", list(comp_ids)):
            if r["task_id"] in out: out[r["task_id"]] = "person"
    return out


# ---------------------------------------------------------------- P3: a person checks a sample of agent approvals (D-023)
SAMPLE_RATE, SAMPLE_DAYS = 0.10, 7  # the Owner's 10%, uncapped (a cap of 10 made it ~1.6% at production's ~600 approvals a week)


def _sample_rate(ch):
    try: v = float(ch.db.setting("verify_sample_rate", SAMPLE_RATE))
    except (TypeError, ValueError, AttributeError): v = SAMPLE_RATE
    return min(1.0, max(0.0, v))


# The Owner's parameters (G5-2.2 directive, 2026-11-12): sample 10%, at least 30 reviews in a rolling 30 days, 95% agreement.
# A review is a decided verdict (agree or disagree); agreement = agree / (agree + disagree); unsure is counted apart and is
# neither a review nor an agreement. The setting verify_demonstrated ({"min", "agree"}) overrides them.
DEMONSTRATED = {"min": 30, "agree": 95, "days": 30}


def demonstrated_threshold(ch):
    """The threshold for "independently demonstrated": {"min": decided reviews in the window, "agree": %, "days"}."""
    try: t = json.loads(ch.db.setting("verify_demonstrated") or "null")
    except (TypeError, ValueError, AttributeError): t = None
    return {**DEMONSTRATED, **t} if isinstance(t, dict) and t.get("min") and t.get("agree") is not None else dict(DEMONSTRATED)


def sample_window(now=None):
    """(start, end) of the last complete ISO week, Monday 00:00 UTC to Monday 00:00 UTC: the week the sample is drawn from."""
    import calendar
    t = time.gmtime(now or time.time())
    this_monday = calendar.timegm(time.strptime(time.strftime("%G-W%V-1", t), "%G-W%V-%u"))
    return this_monday - SAMPLE_DAYS * DAY, this_monday


_pool_seen = {}


def verify_sample(ch, uid, comp_ids, now=None):
    """This week's sample of agent-approved board work for a person to check: the tasks an approval closed in the last complete
    ISO week (Monday to Monday, UTC: a closed window, so the sample stays the same all week), not dropped, ranked by
    sha256(week + task id) and the first ceil(rate × n) taken. Reproducible, and chosen by no agent.
    Returns (tasks, verdicts already given on them)."""
    now = now or time.time()
    if not comp_ids or not ch._has("mw_tasks"): return [], {}
    ok = approved_last(ch, comp_ids)
    # out of the sample: work a person approved themselves (source 'approval'). A sampled task a person has checked stays in this
    # week's sample, so the sample doesn't refill itself as it's worked through
    own = {r["task_id"] for r in ch.db.q(f"SELECT task_id FROM mo_verdicts WHERE comp_id IN ({_marks(comp_ids)}) AND source='approval'", list(comp_ids))} if ch._has("mo_verdicts") else set()
    cols = ch._cols("mw_tasks") if hasattr(ch, "_cols") else set()
    pick = [c for c in ("id", "comp_id", "title", "summary", "done_at", "note", "closed_as", "agent_id") if c in cols or c in ("id", "comp_id", "title")]
    lo, hi = sample_window(now)
    rows = [r for r in ch.db.q(f"SELECT {', '.join(pick)} FROM mw_tasks WHERE comp_id IN ({_marks(comp_ids)}) AND status='done' AND done_at>=? AND done_at<?",
                               (*comp_ids, lo, hi))
            if r["id"] in ok and r["id"] not in own and closed_as(r) != "dropped"]
    week = time.strftime("%G-W%V", time.gmtime(lo))  # the week sampled
    rows.sort(key=lambda r: hashlib.sha256(f"{week}:{r['id']}".encode()).hexdigest())
    k = math.ceil(_sample_rate(ch) * len(rows)) if rows else 0
    chosen = rows[:k]
    _pool_seen[(uid, tuple(comp_ids))] = len(rows)  # the week's agent-approved work the sample is drawn from (sample_summary)
    given = {}
    if chosen and ch._has("mo_verdicts"):
        for v in ch.db.q(f"SELECT task_id, verdict, by_name, at, note FROM mo_verdicts WHERE user_id=? AND source='sample' AND task_id IN ({_marks(chosen)})",
                         (uid, *[r["id"] for r in chosen])):
            given[v["task_id"]] = v
    return chosen, given


def sample_summary(ch, uid, comp_ids, now=None):
    now = now or time.time()
    chosen, given = verify_sample(ch, uid, comp_ids, now)
    th = demonstrated_threshold(ch)
    v30 = ch.db.q("SELECT verdict, COUNT(*) AS n FROM mo_verdicts WHERE user_id=? AND source='sample' AND at>? GROUP BY verdict", (uid, now - th["days"] * DAY)) if ch._has("mo_verdicts") else []
    c = {r["verdict"]: r["n"] for r in v30}
    a, d, u = c.get("agree", 0), c.get("disagree", 0), c.get("unsure", 0)
    pct = round(100 * a / (a + d), 1) if a + d else None
    met = bool(a + d >= th["min"] and pct is not None and pct >= th["agree"])
    # tiers, never merged (Milestone 2 D, Milestone 3): work an agent approved (last week's, the sample's pool), work the team's owner
    # reviewed (30 days: every verdict, unsure included) and whether those reviews meet the Owner's threshold (met), and independent
    # verification. Milestone 3: an owner's review is a person's check of the agents, not independent verification (the owner is
    # associated with the team that did the work), so independently demonstrated needs an independent reviewer: there is no such role
    # yet (G5_2_2_M3_INDEPENDENT_REVIEWER_PROPOSAL.md), so it is never awarded, whatever the owner's agreement.
    return {"week_sample": len(chosen), "pending": sum(1 for r in chosen if r["id"] not in given), "rate": _sample_rate(ch),
            "agree_30d": a, "disagree_30d": d, "unsure_30d": u, "reviews_30d": a + d, "agreement_pct": pct, "threshold": th, "met": met,
            "agent_approved_week": _pool_seen.get((uid, tuple(comp_ids)), 0), "human_reviewed_30d": a + d + u,
            "owner_reviewed_30d": a + d + u, "owner_threshold_met": met,
            "independent_reviews_30d": 0, "independent_reviewer": False, "independently_demonstrated": False,
            "independent_note": "No independent reviewer role exists yet: the team owner's reviews are not independent verification."}


class SampleVerdictIn(BaseModel):
    verdict: str = Field(..., pattern="^(agree|disagree|unsure)$")
    note: str = Field("", max_length=600)


def _person(me):
    """The sample is a person's check: a signed-in user's own session, never an agent and never anonymous (REQUIRE_LOGIN=0 gives
    no user: refused)."""
    if not me or not me.get("id"): raise HTTPException(401, "A person must be signed in to check sampled work.")


def sample_view(ch, me):
    _person(me)
    comps = list(ch._comps(me["id"]).keys()) if hasattr(ch, "_comps") else []
    chosen, given = verify_sample(ch, me["id"], comps)
    names = {}
    if ch._has("mw_agents") and chosen:
        names = {a["id"]: a["name"] for a in ch.db.q(f"SELECT id, name FROM mw_agents WHERE id IN ({_marks(chosen)})", [r.get("agent_id") for r in chosen])}
    appr = {}
    if chosen and ch._has("mw_events"):
        for e in ch.db.q(f"SELECT task_id, text FROM mw_events WHERE kind='approve' AND task_id IN ({_marks(chosen)}) ORDER BY id", [r["id"] for r in chosen]):
            appr[e["task_id"]] = _clip(e["text"], 160)
    return {"summary": sample_summary(ch, me["id"], comps),
            "tasks": [{"id": r["id"], "comp_id": r["comp_id"], "title": r["title"], "summary": _clip(r.get("summary"), 600), "agent": names.get(r.get("agent_id")),
                       "approved": appr.get(r["id"]), "done_at": r.get("done_at"), "verdict": (given.get(r["id"]) or {}).get("verdict")} for r in chosen]}


def sample_verdict(ch, me, tid, b: SampleVerdictIn):
    """A person's verdict on one sampled agent approval. Recorded with their user id. A disagreement is flagged in the decision
    queue for the Owner; it never reopens the task by itself. Only the team's owner sees its sample (_comps): anyone else gets 404."""
    _person(me)
    comps = list(ch._comps(me["id"]).keys()) if hasattr(ch, "_comps") else []
    chosen, _ = verify_sample(ch, me["id"], comps)
    t = next((r for r in chosen if r["id"] == tid), None)
    if not t: raise HTTPException(404, "That task isn't in this week's sample.")
    ensure_schema(ch.db)
    prev = ch.db.q("SELECT verdict, note, at FROM mo_verdicts WHERE user_id=? AND task_id=? AND source='sample'", (me["id"], tid), one=True)
    ch.db.q("DELETE FROM mo_verdicts WHERE user_id=? AND task_id=? AND source='sample'", (me["id"], tid))
    ch.db.q("INSERT INTO mo_verdicts (user_id, comp_id, task_id, source, verdict, by_user_id, by_name, at, note) VALUES (?,?,?,?,?,?,?,?,?)",
            (me["id"], t["comp_id"], tid, "sample", b.verdict, me["id"], me["username"], time.time(), _clip(b.note, 600) or None))
    # Milestone 4: the audit keeps the history the verdict table overwrites: the previous verdict and its note, and this one's note
    hist = (f"was {prev['verdict']}" + (f" (note: {_clip(prev['note'], 120)})" if prev.get("note") else "") + "; " if prev else "") + \
           (f"note: {_clip(b.note, 160)}; " if b.note else "")
    if hasattr(ch, "_audit"): ch._audit(me["id"], me["username"], f"verify.sample.{b.verdict}", f"mw:{tid}", _clip(hist + t["title"], 400))
    _cache.pop(me["id"], None)
    return sample_view(ch, me)

def _ref_id(r):
    """The board task id of a Control Hub task row's ref ("mw_task:12" → 12), or None."""
    ref = (r or {}).get("ref") or ""
    return int(ref.split(":")[1]) if ref.startswith("mw_task:") and ref.split(":")[1:2] and ref.split(":")[1].isdigit() else None


def _count(states):
    out = {s: 0 for s in STATES}
    for s in states: out[s] = out.get(s, 0) + 1
    return out


def scope_of(origin):
    """Who made a board task, from its origin: "agent" (an agent's follow-up, agent:…), "plan" (a lead's plan, plan:<run>: an agent's
    plan, asked for by a person or by Autopilot), "person" (a person, "you") or "other" (a template or an import a person started,
    or work from engines without an origin)."""
    o = str(origin or "")
    if o.startswith("agent:"): return "agent"
    if o.startswith("plan:"): return "plan"
    if o == "you" or o.startswith("you:"): return "person"
    return "other"


def baseline_anchor(db, comp_id):
    """(the first plan run's origin, the cut-off) of a board, from its own unbounded query: what scopes() pins the original scope to.
    Without a plan run: (None, just before the first agent follow-up), or (None, inf) when there is none (or no origin column)."""
    if "origin" not in {c["name"] for c in db.q("PRAGMA table_info(mw_tasks)")}: return None, float("inf")
    rows = db.q("SELECT origin, MAX(created) AS t FROM mw_tasks WHERE comp_id=? AND origin LIKE 'plan:%' GROUP BY origin", (comp_id,))
    plans = sorted(((int(r["origin"][5:]), r) for r in rows if str(r["origin"])[5:].isdigit()), key=lambda x: x[0])
    if plans: return plans[0][1]["origin"], float(plans[0][1]["t"] or 0)
    r = db.q("SELECT MIN(created) AS t FROM mw_tasks WHERE comp_id=? AND origin LIKE 'agent:%'", (comp_id,), one=True)
    return None, (float(r["t"]) - 1e-6) if r and r.get("t") is not None else float("inf")


def scopes(origins, created=None, anchor=None):
    """Each task's place against the original scope (Milestone 3, derived at read time from origin and creation, nothing stored):
    "base": the original scope, a fixed baseline: the board's first plan run, and what a person or a template put on the board up
    to the moment that plan's last task was made. Without a plan run, the non-agent work made before the first agent follow-up.
    "person": added later by a person (or a template or import a person started): an approved addition.
    "agent": added by agents: follow-ups, and every plan run after the first (Autopilot's included): no person approved it."""
    o = [str(x or "") for x in origins]
    c = [float(x or 0) for x in (created if created is not None else [0] * len(o))]
    if anchor is not None: first, cut = anchor  # the board's own (baseline_anchor): independent of which tasks the caller loaded
    else:
        plans = sorted({int(x[5:]) for x in o if x[5:].isdigit() and x.startswith("plan:")})
        first = f"plan:{plans[0]}" if plans else None
        if first: cut = max(t for x, t in zip(o, c) if x == first)
        else:
            ag = [t for x, t in zip(o, c) if x.startswith("agent:")]
            cut = (min(ag) - 1e-6) if ag else float("inf")
    out = []
    for x, t in zip(o, c):
        k = scope_of(x)
        out.append("base" if x == first else "agent" if k in ("agent", "plan") else "base" if t <= cut else "person")
    return out


def progress_headline(ch):
    """Which progress figure leads (Milestone 4: the Owner's choice, setting progress_headline): "original" (the original scope, the
    headline the Owner decided for G5-2.2, and the default) or "active" (the active plan). Every figure is shown either way."""
    try: v = ch.db.setting("progress_headline") or "original"
    except Exception: v = "original"  # noqa: BLE001
    return v if v in ("original", "active") else "original"


def work_progress(states, origins=None, created=None, anchor=None):
    """Work progress, from canonical states (D-018; Owner directives 2026-11-12, Milestone 3). origins, created: each task's
    origin and creation time, parallel to states (scopes()); without origins every task is base.
    pct, the headline, original scope: verified base tasks over every base task, a fixed baseline: no later addition joins it, and
    dropping or cancelling base work leaves its denominator as it is, so neither can raise it.
    pct_active, active plan: verified over the base and the approved (person-made) additions, less only what a person cancelled.
    Dropped work (the Director's decision, not a person's) stays in it as not done, so dropping work can't raise it either.
    Agent-made additions are in neither figure: shown apart (additions), until the Owner decides how one is approved.
    Dropped work is never verified, completed or delivered. delivered = in review + completed + verified (every task)."""
    sc = scopes(origins, created, anchor) if origins is not None else ["base"] * len(states)
    c = _count(states)
    by = {k: _count([s for s, x in zip(states, sc) if x == k]) for k in ("base", "person", "agent")}
    n = {k: sum(v.values()) for k, v in by.items()}
    planned = sum(c.values()) - c["CANCELLED"] - c["DROPPED"]
    active = n["base"] + n["person"] - by["base"]["CANCELLED"] - by["person"]["CANCELLED"]
    v_base, v_active = by["base"]["VERIFIED"], by["base"]["VERIFIED"] + by["person"]["VERIFIED"]
    return {"planned": planned, "original": n["base"], "active": active, "delivered": c["REVIEW"] + c["COMPLETED"] + c["VERIFIED"], "review": c["REVIEW"],
            "completed": c["COMPLETED"], "reviewed": c["VERIFIED"], "verified": c["VERIFIED"], "verified_original": v_base, "verified_active": v_active,
            "unverified": c["REVIEW"] + c["COMPLETED"], "dropped": c["DROPPED"], "cancelled": c["CANCELLED"],
            "running": c["RUNNING"], "ready": c["READY"], "blocked": c["BLOCKED"], "failed": c["FAILED"], "paused": c["PAUSED"],
            "pct": _pct(v_base, n["base"]), "pct_active": _pct(v_active, active), "states": c,
            "additions": {"approved": n["person"], "approved_verified": by["person"]["VERIFIED"], "agent": n["agent"],
                          "agent_verified": by["agent"]["VERIFIED"], "agent_dropped": by["agent"]["DROPPED"]}}


# ---------------------------------------------------------------- objective progress: weighted, verified criteria
def objective_progress(criteria):
    """P = Σ w·s / Σ w × 100 over the criteria that count; a criterion that isn't verified contributes 0."""
    on = [c for c in criteria if not c.get("off")]
    tw = sum(c["weight"] for c in on)
    got = sum(c["weight"] * (c["value"] or 0) for c in on if c["verified"])
    return {"pct": round(100 * got / tw) if tw else None, "weight": tw, "verified": sum(1 for c in on if c["verified"] and (c["value"] or 0) >= 1),
            "unverified": sum(1 for c in on if not c["verified"]), "total": len(on)}


def _crit(key, label, weight, value, verified, evidence="", needs="", owner="AXoR", unknown=False):
    return {"key": key, "label": label, "weight": weight, "value": None if value is None else max(0.0, min(1.0, float(value))), "verified": bool(verified),
            "evidence": evidence, "needs": needs, "owner": owner, "unknown": bool(unknown), "source": "records", "off": False}


def competition_criteria(ch, uid, ms, w, now=None):
    """A competition's acceptance criteria in the order they must be met, each from records: registration, validation on the
    frozen benchmark, reliability, submission, official rank, holding it."""
    now = now or time.time()
    q, has = ch.db.q, ch._has
    s, tgt = ms.get("standing") or {}, ms.get("target_rank")
    rank, of = s.get("rank"), s.get("of")
    camp = q("SELECT * FROM mh_campaigns WHERE id=?", (w["campaign_id"],), one=True) if has("mh_campaigns") else None
    keys = _j((camp or {}).get("keys"), []) or []
    miners = q("SELECT id, hotkey, name, version FROM mc_miners WHERE user_id=? AND (comp_id=? OR campaign_id=?)", (uid, w["id"], w["campaign_id"])) if has("mc_miners") else []
    out = []
    # 1. registration: a hotkey of yours with a UID on the subnet (the rank is read from the chain for that key)
    if rank is not None:
        out.append(_crit("registration", "Miner registered (UID on the subnet)", 10, 1, True, f"Ranked {rank} of {of or '?'} on the chain for your key"))
    elif keys or miners:
        out.append(_crit("registration", "Miner registered (UID on the subnet)", 10, 0, True,
                         f"{_s(len(keys) or len(miners), 'hotkey')} tracked, none has a UID on SN{w['netuid']} yet",
                         "Register the miner: confirm the hotkey and approve the registration (a spend on the chain, yours to approve).", "you"))
    else:
        out.append(_crit("registration", "Miner registered (UID on the subnet)", 10, 0, True, "No hotkey added to this campaign",
                         "Add the miner's hotkey on My subnets, then approve its registration.", "you"))
    # 2. validation: the frozen candidate benchmarked on the frozen suite, against its reference
    rel = q("SELECT * FROM mw_release WHERE comp_id=? AND current=1 ORDER BY id DESC LIMIT 1", (w["id"],), one=True) if has("mw_release") else None
    bench = q("SELECT * FROM mw_bench WHERE comp_id=? AND release_id=? AND comparable=1 ORDER BY id DESC LIMIT 1", (w["id"], rel["id"]), one=True) if rel and has("mw_bench") else None
    if not rel:
        out.append(_crit("validation", "Validation score on the frozen benchmark", 25, None, False, "No candidate is frozen",
                         "Freeze a release candidate and its benchmark suite (Competition teams → Status → Release & benchmarks).", "the team lead"))
    elif not bench:
        out.append(_crit("validation", "Validation score on the frozen benchmark", 25, None, False,
                         f"Release v{rel['version']} is frozen ({_clip(rel.get('suite') or 'suite', 40)}), not benchmarked on it yet",
                         "Run the frozen candidate on the frozen suite: only that result is comparable.", "the team"))
    else:
        ref = rel.get("reference_score")
        v = 1.0 if not ref else (bench["score"] or 0) / ref if ref > 0 else 1.0
        out.append(_crit("validation", "Validation score on the frozen benchmark", 25, v, True,
                         f"v{rel['version']} scored {bench['score']:g} on {_clip(bench.get('suite') or rel.get('suite') or 'the suite', 40)}"
                         + (f" against the reference {ref:g}" if ref else " (no reference score set: counted as met)"),
                         "" if v >= 1 else "Close the gap to the reference score: diagnose the failing cases and test alternatives.", "the team"))
    # 3. reliability: the miner's own health reports (not the agents' run success)
    hl = None
    if miners and has("mc_health"):
        hl = q(f"SELECT COUNT(*) AS n, AVG(up) AS up FROM mc_health WHERE miner_id IN ({_marks(miners)}) AND ts>?", (*[m["id"] for m in miners], now - WEEK), one=True)
    if hl and hl["n"]:
        up = float(hl["up"] or 0)
        out.append(_crit("reliability", "Candidate reliability", 15, 1 if up >= 0.99 else up, True, f"Up in {round(up * 100)}% of {hl['n']} health reports this week",
                         "" if up >= 0.99 else "Fix what takes the miner down before submitting or scaling.", "the team"))
    else:
        out.append(_crit("reliability", "Candidate reliability", 15, None, False, "No miner health reports this week",
                         "Send the miner's health to the Command center (ingest API), or run a soak test and file it.", "the team"))
    # 4. submission: a deploy on record that went live (yours to approve), or a rank on the chain
    dep = q("SELECT status, version, ts FROM mc_deploys WHERE user_id=? AND comp_id=? ORDER BY id DESC LIMIT 1", (uid, w["id"]), one=True) if has("mc_deploys") else None
    live = dep and str(dep["status"] or "").lower() in ("live", "deployed", "done", "success", "active")
    if live or rank is not None:
        out.append(_crit("submission", "Submission accepted", 15, 1, True,
                         f"Version {dep['version'] or '?'} is {dep['status']}" if live else "The miner is ranked on the chain"))
    else:
        out.append(_crit("submission", "Submission accepted", 15, 0, True, f"Last deploy: {dep['status']}" if dep else "Nothing submitted or deployed yet",
                         "Submit the frozen candidate; a deploy needs your approval (Command center → Experiments).", "you"))
    # 5. the official rank against the target: UNKNOWN (not 0) while it can't be read
    if not tgt:
        out.append(_crit("rank", "Official rank at the target", 25, None, False, "No target rank is set", "Configure the mission's target rank.", "you", unknown=True))
    elif rank is None:
        out.append(_crit("rank", f"Official rank inside the top {tgt}", 25, None, False, "UNKNOWN: no ranked miner under your keys",
                         "The rank can be read once a hotkey of yours has a UID on the subnet.", "you", unknown=True))
    else:
        v = 1.0 if rank <= tgt else max(0.0, ((of or rank) - rank) / max(1, (of or rank) - tgt))
        out.append(_crit("rank", f"Official rank inside the top {tgt}", 25, v, True, f"Rank {rank} of {of or '?'}" + (f", gap to the target {s['gap']}" if s.get("gap") is not None else ""),
                         "" if rank <= tgt else f"{rank - tgt} place{'s' if rank - tgt != 1 else ''} to go: put resources on what moves the official score.", "the team"))
    # 6. holding it: the last HOLD_DAYS days of briefs inside the target
    if tgt and rank is not None and has("mh_briefs"):
        br = [(_j(b["stats"], {}) or {}).get("rank") for b in q("SELECT stats FROM mh_briefs WHERE campaign_id=? AND ts>? ORDER BY id", (w["campaign_id"], now - HOLD_DAYS * DAY))]
        br = [x for x in br if x is not None]
        inside = sum(1 for x in br if x <= tgt)
        v = inside / len(br) if br else 0
        out.append(_crit("sustain", f"Rank held for {HOLD_DAYS} days", 10, v, bool(br), f"Inside the top {tgt} in {inside} of {len(br)} briefs of the last {HOLD_DAYS} days" if br else "No brief in the window",
                         "" if v >= 1 else "Hold it: watch regressions, new entrants and the miner's uptime.", "the team"))
    else:
        out.append(_crit("sustain", f"Rank held for {HOLD_DAYS} days", 10, None, False, "Not measurable before the miner is ranked", "Measured from the daily briefs once the rank is known.", "AXoR", unknown=rank is None))
    return out


def custom_criteria(m):
    """A Mission Control mission's criteria: the ones it understood, with the independent verifier's verdict on each."""
    u, v = _j(m.get("understanding"), {}) or {}, _j(m.get("verification"), {}) or {}
    names = [str(c.get("text") if isinstance(c, dict) else c) for c in (u.get("criteria") or [])]
    res = {}
    for c in (v.get("criteria") or v.get("checks") or []):
        if isinstance(c, dict):
            res[str(c.get("criterion") or c.get("text") or c.get("check") or "").strip().lower()] = c
    out = []
    for i, n in enumerate(names):
        r = res.get(n.strip().lower())
        met = None if r is None else bool(r.get("met") if "met" in r else r.get("ok") if "ok" in r else r.get("pass"))
        out.append(_crit(f"c{i + 1}", _clip(n, 160), 1, None if met is None else (1 if met else 0), met is not None,
                         _clip((r or {}).get("evidence") or (r or {}).get("note") or ("Checked by the independent verifier" if r else "Not verified yet"), 240),
                         "" if met else "Waits for the mission's independent verification." if met is None else "Unmet: continue only this missing work.",
                         "AXoR"))
    return out


def merge_criteria(ch, uid, ref, auto):
    """The mission's criteria with the person's changes: a weight or off on one from records, and criteria they added (which
    count only once they attested a value with evidence)."""
    rows = {r["key"]: r for r in ch.db.q("SELECT * FROM mo_criteria WHERE user_id=? AND mission=?", (uid, ref))}
    out = []
    for c in auto:
        r = rows.pop(c["key"], None)
        if r:
            if r["weight"] is not None: c["weight"] = r["weight"]
            c["off"] = bool(r["off"])
            c["edited"] = True
        out.append(c)
    for r in rows.values():
        ok = r["value"] is not None and bool((r["evidence"] or "").strip())
        c = _crit(r["key"], r["label"] or r["key"], r["weight"] if r["weight"] is not None else 10, r["value"] if ok else None, ok,
                  _clip(r["evidence"] or "", 300) + (f" (attested by {r['by_user']})" if ok and r["by_user"] else ""),
                  "" if ok and (r["value"] or 0) >= 1 else "Verify it and record the evidence: an unverified criterion counts as not achieved.", "you")
        c.update(source="yours", off=bool(r["off"]), id=r["id"])
        out.append(c)
    return out


# ---------------------------------------------------------------- the decision engine
def decide(sig):
    """The situation a mission is in, from its signals, in the order that decides what happens first. Returns
    {situation, label, response, next, blocker, owner}."""
    def out(key, blocker="", nxt=None, owner="AXoR"):
        label, resp, default = SITUATIONS[key]
        return {"situation": key, "label": label, "response": resp, "next": nxt or default, "blocker": blocker, "owner": owner}
    need = sig.get("first_unmet") or {}
    if sig.get("paused"):
        why = sig.get("pause_reason") or "The team is paused"
        return out("paused", why, sig.get("pause_next") or "Clear what paused it, then resume the team.", "you")
    if sig.get("budget_over"):
        return out("budget", sig["budget_over"], "Reconcile the spend with the budget, then raise it or wait for older runs to leave the 24-hour window.", "you")
    if sig.get("cooling"):
        return out("provider", sig["cooling"], "The queue is held until the provider recovers; nothing is retried before that.", "AXoR")
    if sig.get("regression"):
        return out("regression", sig["regression"], "Compare with the previous version: roll back, or approve keeping it.", "you")
    if sig.get("repeated"):
        return out("repeated", sig["repeated"], "Stop identical attempts: diagnose the failure class, then re-plan or reassign.", "the team lead")
    cls = sig.get("fail_class")
    if cls and sig.get("failing"):
        sit, rec, who = RECOVERY.get(cls, RECOVERY["task"])
        return out(sit, sig["failing"], rec, who)
    if sig.get("blocked"):
        return out("blocked", sig["blocked"], sig.get("blocked_next") or "Answer or approve it; the team continues other work meanwhile.", "you")
    if sig.get("unknown"):
        return out("uncertain", sig["unknown"], need.get("needs") or "Get the missing evidence first.", need.get("owner") or "you")
    if sig.get("met"):
        return out("successful", "", "Freeze the candidate, keep its evidence and monitor rank, rewards and uptime.", "AXoR")
    if sig.get("open") and not sig.get("moving") and sig.get("stalled"):
        return out("no_progress", sig["stalled"], "Compare with the expected pace: reassign, redesign or drop the stalled work.", "the team lead")
    if not sig.get("open") and need:
        return out("idle", "No open work toward the objective", need.get("needs") or "Plan the next step.", need.get("owner") or "the team lead")
    if need and sig.get("partial"):
        return out("partial", need.get("label", ""), need.get("needs") or "Continue only the missing work.", need.get("owner") or "the team")
    return out("progressing", "", need.get("needs") or None, need.get("owner") or "AXoR")


# ---------------------------------------------------------------- missions
def _comp_signals(ch, uid, ms, w, items, crit, now):
    """What the decision engine reads for a competition: pause, budget, cooldown, blocked and failing work, regression, pace."""
    q, has = ch.db.q, ch._has
    sig = {"open": sum(1 for i in items if i["state"] in ("PLANNED", "READY", "RUNNING", "REVIEW", "BLOCKED")),
           "moving": any(i["state"] == "RUNNING" for i in items)}
    full = q("SELECT * FROM mw_comps WHERE id=?", (w["id"],), one=True) or {}
    budget, used = ms.get("budget"), ms.get("used_today") or 0
    over = bool(budget) and used >= budget
    if over:
        sig["budget_over"] = f"{used:,} of {budget:,} tokens in 24 hours"
    if full.get("paused"):
        sig["paused"] = True
        sig["pause_reason"] = _clip(full.get("pilot_note") or "The team is paused", 200)
        if over: sig["pause_reason"] += f"; its 24-hour budget is spent ({used:,} of {budget:,} tokens)"
        sig["pause_next"] = ("Resolve the budget discrepancy (Budget tab → reconciliation) and check the provider before restarting the team."
                             if over else "Resume the team when you're ready: its queue is kept.")
    if has("ml_state"):
        st = q("SELECT cool_until, cool_reason FROM ml_state WHERE comp_id=?", (w["id"],), one=True)
        if st and st["cool_until"] and st["cool_until"] > now:
            sig["cooling"] = f"{st['cool_reason'] or 'The provider is cooling down'} until {time.strftime('%H:%M', time.localtime(st['cool_until']))}"
    blocked = [i for i in items if i["state"] == "BLOCKED"]
    if blocked:
        b = blocked[0]
        sig["blocked"] = f"{_s(len(blocked), 'task')} blocked: “{_clip(b['title'], 80)}”" + (f": {_clip(b.get('why'), 160)}" if b.get("why") else "")
    failed = [i for i in items if i["state"] == "FAILED"]
    if failed:
        cls = {}
        for i in failed: cls[i.get("fail_class") or "task"] = cls.get(i.get("fail_class") or "task", 0) + 1
        top = max(cls, key=cls.get)
        sig["fail_class"] = top
        sig["failing"] = f"{_s(len(failed), 'task')} failed ({cls[top]} as “{top}”): “{_clip(failed[0]['title'], 80)}”"
        if len(failed) >= 3 or any((i.get("fails") or 0) >= 2 for i in failed):
            sig["repeated"] = f"{_s(len(failed), 'task')} gave up after repeated failures, most as “{top}”"
    if has("mw_bench"):
        b2 = q("SELECT score FROM mw_bench WHERE comp_id=? AND comparable=1 ORDER BY id DESC LIMIT 2", (w["id"],))
        if len(b2) == 2 and b2[0]["score"] is not None and b2[1]["score"] is not None and b2[0]["score"] < b2[1]["score"]:
            sig["regression"] = f"The latest comparable benchmark scored {b2[0]['score']:g}, down from {b2[1]['score']:g}"
    last_v = max((i.get("done_at") or 0 for i in items if i["state"] == "VERIFIED"), default=0)
    if sig["open"] and not sig["moving"] and (now - last_v > NO_PROGRESS):
        sig["stalled"] = (f"{sig['open']} open tasks, none running, " + (f"nothing verified for {int((now - last_v) / DAY)} days" if last_v else "nothing verified yet"))
    on = [c for c in crit if not c.get("off")]
    unmet = [c for c in on if not (c["verified"] and (c["value"] or 0) >= 1)]
    sig["first_unmet"] = unmet[0] if unmet else None
    rk = next((c for c in on if c["key"] == "rank"), None)
    if rk and rk.get("unknown"): sig["unknown"] = "The official rank is UNKNOWN: " + (rk["evidence"].replace("UNKNOWN: ", "") or "it can't be measured yet")
    sig["met"] = bool(on) and not unmet
    sig["partial"] = any(c["verified"] and (c["value"] or 0) > 0 for c in on) and bool(unmet)
    return sig


def _competition(ch, me, ms, w, board, ok, tasks, now):
    uid = me["id"]
    paused = bool((ch.db.q("SELECT paused FROM mw_comps WHERE id=?", (w["id"],), one=True) or {}).get("paused")) if "paused" in ch._cols("mw_comps") else False
    on_board = {t["id"] for t in board}
    items = [{"id": f"mw:{t['id']}", "title": t["title"], "state": state_board(t, paused, t["id"] in ok), "fails": t.get("fails"), "fail_class": t.get("fail_class"),
              "why": t.get("question") or t.get("note"), "done_at": t.get("done_at"), "updated": t.get("updated"), "agent_id": t.get("agent_id"),
              "origin": t.get("origin"), "created": t.get("created")} for t in board]
    for t in tasks:  # Control Hub tasks of this mission that aren't one of its board's tasks (another team's, an agent's, not sent yet)
        ref = t.get("ref") or ""
        if t.get("mission") != ms["ref"] or (ref.startswith("mw_task:") and int(ref.split(":")[1]) in on_board): continue
        items.append({"id": f"ctl:{t['id']}", "title": t["title"], "state": t["canon"], "why": (t.get("why") or {}).get("text"), "done_at": t.get("done_at"),
                      "updated": t.get("updated"), "fail_class": None})
    crit = merge_criteria(ch, uid, ms["ref"], competition_criteria(ch, uid, ms, w, now))
    obj = objective_progress(crit)
    rk = next((c for c in crit if c["key"] == "rank"), {})
    sig = _comp_signals(ch, uid, ms, w, items, crit, now)
    d = decide(sig)
    measurable = not rk.get("unknown")
    obj["official"] = {"measurable": measurable, "text": (f"Rank {(ms.get('standing') or {}).get('rank')} of {(ms.get('standing') or {}).get('of') or '?'}" if measurable
                                                           else "UNKNOWN"), "reason": "" if measurable else rk.get("evidence", "").replace("UNKNOWN: ", ""),
                       "needs": "" if measurable else rk.get("needs", "")}
    health = ("paused" if sig.get("paused") else "blocked" if d["situation"] in ("blocked", "budget", "provider", "repeated", "regression", "environment", "task_failure")
              else "unmeasurable" if not measurable else "met" if sig.get("met") else "on_track")
    return {"ref": ms["ref"], "type": "predefined", "title": ms["title"], "subnet": ms.get("subnet"), "comp_id": w["id"], "unit": ms.get("unit"),
            "objective": (f"Reach and hold top {ms['target_rank']}" if ms.get("target_rank") else _clip(ms.get("objective") or "No objective set yet", 200)),
            "objective_note": _clip(ms.get("objective") or "", 300) if ms.get("target_rank") else "", "target_rank": ms.get("target_rank"),
            "has_objective": bool(ms.get("target_rank") or (ms.get("objective") or "").strip()),
            "standing": ms.get("standing"), "deadline": ms.get("deadline"), "health": health, "work": {**work_progress([i["state"] for i in items], [i.get("origin") for i in items], [i.get("created") for i in items], baseline_anchor(ch.db, w["id"])),
                     "headline": progress_headline(ch)},
            "objective_progress": obj, "criteria": crit, "decision": d, "budget": {"tokens": ms.get("budget"), "used_24h": ms.get("used_today") or 0,
                                                                                    "left": max(0, ms["budget"] - (ms.get("used_today") or 0)) if ms.get("budget") else None},
            "confidence": ("high" if measurable and obj["unverified"] == 0 else "medium" if obj["verified"] else "low"),
            "attention": [i for i in items if i["state"] in ("BLOCKED", "FAILED")][:6], "link": ms.get("link")}


def _custom_mission(ch, me, c, now):
    m = ch.db.q("SELECT * FROM mx_missions WHERE id=? AND user_id=?", (c["mx_id"], me["id"]), one=True) or {}
    st = state_mission(m.get("status"), m.get("outcome"), m.get("stage"))
    crit = merge_criteria(ch, me["id"], c["ref"], custom_criteria(m))
    obj = objective_progress(crit)
    plan = (_j(m.get("plan"), {}) or {}).get("tasks") or []
    hist = _j(m.get("history"), []) or []
    done = {str(h.get("task") or h.get("id")) for h in hist if isinstance(h, dict) and str(h.get("status") or "").lower() in ("done", "delivered", "ok")}
    states = [("VERIFIED" if st == "VERIFIED" else "REVIEW") if (str(t.get("id")) in done or st in ("VERIFIED", "REVIEW")) else
              "RUNNING" if st == "RUNNING" else "FAILED" if st == "FAILED" else "CANCELLED" if st == "CANCELLED" else "PLANNED" for t in plan]
    need = next((x for x in crit if not x.get("off") and not (x["verified"] and (x["value"] or 0) >= 1)), None)
    sig = {"open": 0 if st in ("VERIFIED", "FAILED", "CANCELLED") else 1, "moving": st == "RUNNING", "first_unmet": need,
           "met": st == "VERIFIED" and not need, "partial": st == "REVIEW" and bool(crit)}
    if st == "PAUSED": sig.update(paused=True, pause_reason=_clip(m.get("pause_reason") or "The mission is paused", 200), pause_next="Resume it in Mission Control.")
    if st == "BLOCKED": sig.update(blocked="The mission waits for your answer or approval", blocked_next="Answer it in Mission Control: it goes on from where it stopped.")
    if st == "FAILED": sig.update(failing=_clip(m.get("error") or "The mission stopped for good", 200), fail_class=_class_of(m.get("error")))
    if st == "REVIEW" and not need: sig.update(unknown="Delivered without a verified outcome: independent evidence is missing")
    d = decide(sig)
    return {"ref": c["ref"], "type": "custom", "title": c["title"], "objective": _clip(m.get("goal") or c["title"], 240), "state": st, "stage": m.get("stage"),
            "health": ("met" if st == "VERIFIED" else "blocked" if st in ("BLOCKED", "FAILED") else "paused" if st == "PAUSED" else "on_track"),
            "work": work_progress(states), "objective_progress": {**obj, "official": {"measurable": True, "text": m.get("outcome") or "no verdict yet", "reason": "", "needs": ""}},
            "criteria": crit, "decision": d, "budget": {"usd": m.get("budget"), "spent_usd": m.get("spent")}, "parent": c.get("parent"), "updated": m.get("updated"),
            "confidence": "high" if st == "VERIFIED" else "low" if not obj["verified"] else "medium"}


def _class_of(error):
    try:
        from .intel_layers import fail_class
        return fail_class("failed", error or "")
    except Exception:  # noqa: BLE001
        return "task"


_cache = {}


def view(ch, me, fresh=False):
    """The console: competitions and custom missions with objective, both progress figures, blocker and next action; the global
    activity in one state model; the decision queue; run accountability; budgets; the evolution registry; G5 readiness."""
    uid, now = me["id"], time.time()
    hit = _cache.get(uid)
    if hit and not fresh and now - hit[0] < CACHE_S: return hit[1]
    from . import control_missions as cm, task_lifecycle as tl
    d = cm.missions(ch, me)
    tasks = d["tasks"]
    ids = [t["id"] for t in tasks]
    rows = {r["id"]: r for r in ch.db.q(f"SELECT * FROM ctl_tasks WHERE id IN ({_marks(ids)})", ids)} if ids else {}
    runs = tl._runs(ch, ids)
    for t in tasks:
        r = rows.get(t["id"]) or {}
        sg, note = tl.stage(t, r, runs.get(t["id"]))
        ref = r.get("ref") or ""
        # an independent verdict: your acceptance of an agent's result (the only way an agent task gets done), or the board's
        verified = t["status"] == "done" and (not ref.startswith("mw_task:") or None)
        t["stage"], t["stage_note"], t["_verified"] = sg, note, verified
    comps = ch._comps(uid)
    open_comps = [wid for wid, w in comps.items() if (w["status"] or "active") != "closed"]
    board, ok = _board(ch, open_comps)
    board_by_id = {b["id"]: b for b in board}
    by_comp = {}
    for b in board: by_comp.setdefault(b["comp_id"], []).append(b)
    for t in tasks:
        v = t.pop("_verified")
        if v is None:  # on a board: the board task's own review decides
            ref = (rows.get(t["id"]) or {}).get("ref") or ""
            v = int(ref.split(":")[1]) in ok if ref.split(":")[1:2] and ref.split(":")[1].isdigit() else False
        t["canon"] = state_ctl(t["stage"], v)
        bt = board_by_id.get(_ref_id(rows.get(t["id"])))
        if bt is not None and bt["status"] == "done":  # on a board: the board task's closing decides (D-018)
            t["canon"] = state_board(bt, False, bt["id"] in ok)
        if t.get("team_paused") and t["canon"] in ("PLANNED", "READY"): t["canon"] = "PAUSED"
    pre = [m for m in d["initiatives"][0]["missions"] if m["type"] == "predefined"]
    cus = [m for i in d["initiatives"] for m in i["missions"] if m["type"] == "custom"]
    competitions = []
    for ms in pre:
        w = comps.get(ms["comp_id"])
        if w: competitions.append(_competition(ch, me, ms, w, by_comp.get(w["id"], []), ok, tasks, now))
    custom = [_custom_mission(ch, me, c, now) for c in cus if c["status"] in cm.MX_ACTIVE or (c.get("updated") or 0) > now - WEEK][:12]
    # the global activity, each piece of work counted once: board tasks, and Control Hub tasks that aren't on a board
    paused_comps = {wid for wid in open_comps if (ch.db.q("SELECT paused FROM mw_comps WHERE id=?", (wid,), one=True) or {}).get("paused")} if "paused" in (ch._cols("mw_comps") if ch._has("mw_comps") else ()) else set()
    states = [state_board(b, b["comp_id"] in paused_comps, b["id"] in ok) for b in board]
    states += [t["canon"] for t in tasks if not ((rows.get(t["id"]) or {}).get("ref") or "").startswith("mw_task:") and t["status"] not in ("proposed", "skipped")]
    states += [c["state"] for c in custom]
    activity = _count(states)
    recent = now - DAY
    closing = [state_board(b, False, b["id"] in ok) for b in board if b["status"] == "done"]
    try: src = verdict_sources(ch, open_comps)
    except Exception: src = {}  # noqa: BLE001 - evidence detail only
    activity_note = {"verified_24h": sum(1 for b in board if b["status"] == "done" and b["id"] in ok and closed_as(b) != "dropped" and (b.get("done_at") or 0) > recent),
                     "unverified_done": closing.count("COMPLETED"),  # D-018: closed without a verdict; dropped work is not in it
                     "dropped": closing.count("DROPPED"), "in_review": sum(1 for b in board if b["status"] in ("review", "checking")),
                     "verified_total": closing.count("VERIFIED"), "sample": sample_summary(ch, uid, open_comps, now),
                     "verified_by_person": sum(1 for b in board if b["status"] == "done" and b["id"] in ok and closed_as(b) != "dropped" and src.get(b["id"]) == "person"),
                     "verified_by_agent": sum(1 for b in board if b["status"] == "done" and b["id"] in ok and closed_as(b) != "dropped" and src.get(b["id"]) != "person")}
    acc = accountability(ch, uid, now - WEEK)
    bud = budgets(ch, me, competitions, now)
    evo = evolution_registry(ch, uid, comps, now)
    queue = decision_queue(ch, me, competitions, custom, tasks, bud, evo, now)
    from . import mission_evidence as mev  # knowledge visibility, and techniques measured better than the baseline that wait for a decision
    know = None
    try: know = mev.knowledge(ch, me, now)
    except Exception as e:  # noqa: BLE001 - the console still shows the rest
        know = {"error": _clip(e, 200)}
    if ch._has("mo_techniques"):
        for c in competitions:
            w = comps.get(c["comp_id"])
            for r in ch.db.q("SELECT * FROM mo_techniques WHERE user_id=? AND mission=? AND status='reproducing'", (uid, c["ref"])):
                t = mev._technique(ch, w, r)
                if t["status"] == "evaluated":
                    queue.append({"kind": "promotion", "level": "info", "title": _clip(f"{c['title']}: a competitor technique is measured: {t['title']}", 160),
                                  "detail": f"{t['baseline']} → {t['candidate']} on {t['suite']}. " + ("It beat the baseline: adopt or reject it." if t["can_adopt"] else "It didn't beat the baseline: reject it or change the hypothesis."),
                                  "owner": "you", "go": None, "ref": c["ref"], "ts": t["updated"], "action": "competitors"})
    attention = activity["BLOCKED"] + activity["FAILED"]
    out = {"at": now, "mode": d["mode"], "states": [{"key": s, "label": STATE_LABEL[s], "note": STATE_NOTE[s], "path": s in PATH} for s in STATES],
           "kpis": {"competitions": len(competitions), "custom": sum(1 for c in custom if c["state"] not in ("VERIFIED", "FAILED", "CANCELLED")),
                    "objectives_verified": sum(1 for c in competitions if c["health"] == "met") + sum(1 for c in custom if c["state"] == "VERIFIED"),
                    "attention": attention, "decisions": len(queue), "yours": sum(1 for x in queue if x["owner"] == "you")},
           "competitions": competitions, "custom": custom, "activity": activity, "activity_note": activity_note, "queue": queue,
           "accountability": acc, "budget": bud, "evolution": evo, "knowledge": know, "situations": [{"key": k, "label": v[0], "response": v[1], "next": v[2]} for k, v in SITUATIONS.items()],
           "recovery": [{"cls": k, "situation": SITUATIONS[v[0]][0], "recovery": v[1], "owner": v[2]} for k, v in RECOVERY.items()]}
    out["_tasks"] = tasks  # for readiness and the queue's callers; left out of the answer (mount._view)
    out["readiness"] = readiness(ch, me, out, now)
    try: out["gate"] = gate_view(ch, me, out.get("competitions") or [])  # G5-2: mission readiness and its risks
    except Exception as e:  # noqa: BLE001 - the console still shows the rest
        out["gate"] = {"error": str(e)[:200], "missions": [], "risks": []}
    _cache[uid] = (now, out)
    return out


# ---------------------------------------------------------------- run accountability
def accountability(ch, uid, since):
    """Every finished run since `since` in exactly one of the seven outcomes. Inconclusive runs carry a reason and a next action.
    G5-5 L5.1 (IC-11): a board task's review verdict is its own outcome, "Reviewed, unmeasured": it is not a score, and not a gap."""
    q, has = ch.db.q, ch._has
    if not has("ac_runs"): return None
    try:
        from .intel_layers import GOOD, LOW
    except Exception:  # noqa: BLE001
        GOOD, LOW = 70, 50
    ev, dg = has("io_evals"), has("io_diag")
    own = ",".join(f"'{c}'" for c in ("task", "cap"))
    rows = q(f"""SELECT o, COUNT(*) AS n FROM (SELECT CASE
                   WHEN a.status IN ('failed','error','lost') THEN {"CASE WHEN d.run_id IS NULL THEN 'undiagnosed' WHEN d.cls IN (" + own + ") THEN 'failure' ELSE 'environment' END" if dg else "'failure'"}
                   WHEN a.status IN ('cancelled','stopped') THEN 'stopped'
                   WHEN a.score IS NOT NULL AND a.score<{LOW} THEN 'failure' WHEN a.score>={GOOD} THEN 'success' WHEN a.score IS NOT NULL THEN 'partial'
                   {"WHEN e.state='reviewed' THEN 'reviewed' WHEN e.state='excluded' THEN 'excluded' WHEN e.state='gap' THEN 'gap'" if ev else ""} ELSE 'waiting' END AS o
                 FROM ac_runs a {"LEFT JOIN io_evals e ON e.run_id=a.id" if ev else ""} {"LEFT JOIN io_diag d ON d.run_id=a.id" if dg else ""}
                 WHERE a.owner_id=? AND a.started>? AND a.status!='running') x GROUP BY o""", (uid, since))
    c = {r["o"]: r["n"] for r in rows}
    g = lambda k: c.get(k, 0)
    total = sum(c.values())
    inconclusive = []
    if ev and g("gap"):
        for r in q("""SELECT e.system AS system, e.kind AS kind, MAX(e.reason) AS reason, COUNT(*) AS n FROM io_evals e JOIN ac_runs a ON a.id=e.run_id
                      WHERE a.owner_id=? AND a.started>? AND e.state='gap' AND a.score IS NULL AND a.status NOT IN ('running','failed','error','lost','cancelled','stopped')
                      GROUP BY e.system, e.kind ORDER BY COUNT(*) DESC LIMIT 8""", (uid, since)):
            why = r["reason"] or "No verdict"
            nxt = ("Assign an evaluator to this kind of run, or exclude it with a reason (orchestrator.EVALUATORS)." if why.startswith("No evaluator")
                   else "Decide it (accept, approve or send back): a later decision still scores the run.")
            inconclusive.append({"n": r["n"], "what": f"{agent_core.SYSTEMS.get(r['system'], r['system'])} · {r['kind']}", "reason": why, "next": nxt})
    if g("waiting"):
        inconclusive.append({"n": g("waiting"), "what": "Finished, verdict still due", "reason": "Its evaluator or your decision has time left before it counts as a gap",
                             "next": "Nothing yet: classified on the orchestrator's next passes; overdue ones become a gap with their reason."})
    if g("undiagnosed"):
        inconclusive.append({"n": g("undiagnosed"), "what": "Failed, not diagnosed yet", "reason": "The failure has no class yet",
                             "next": "Diagnosed on the orchestrator's next pass (every minute), then counted as a task or an environment failure."})
    reasons = [dict(r) for r in q("""SELECT e.reason AS reason, COUNT(*) AS n FROM io_evals e JOIN ac_runs a ON a.id=e.run_id WHERE a.owner_id=? AND a.started>?
                                     AND e.state='excluded' AND a.score IS NULL AND a.status NOT IN ('failed','error','lost','cancelled','stopped')
                                     GROUP BY e.reason ORDER BY COUNT(*) DESC LIMIT 6""", (uid, since))] if ev else []
    inc = g("gap") + g("waiting") + g("undiagnosed")
    scored = g("success") + g("partial") + g("failure")
    if ev:  # orchestrator.coverage()'s definition, so this figure is the Intelligence layers' "scored of scoreable"
        st = {r["state"]: r["n"] for r in q("""SELECT e.state AS state, COUNT(*) AS n FROM io_evals e JOIN ac_runs a ON a.id=e.run_id
                                               WHERE a.owner_id=? AND a.started>? GROUP BY e.state""", (uid, since))}
        scored_eligible, eligible = st.get("scored", 0), st.get("scored", 0) + st.get("gap", 0)
    else:
        scored_eligible = eligible = scored
    return {"total": total, "since": since, "good": GOOD, "low": LOW,
            "outcomes": [{"key": "success", "label": "Scored success", "n": g("success"), "note": f"Scored {GOOD} or more by an evaluator or a verifier (model-judged), or a number derived from a decision. Not a measurement"},
                         {"key": "partial", "label": "Scored partial success", "n": g("partial"), "note": f"Scored {LOW} to {GOOD - 1}"},
                         {"key": "failure", "label": "Verified task failure", "n": g("failure"), "note": f"Scored under {LOW}, or failed as the work's own fault"},
                         {"key": "environment", "label": "Environment failure", "n": g("environment"), "note": "A restart, quota, budget, provider, timeout, sandbox or tool: not the work's fault"},
                         {"key": "reviewed", "label": "Reviewed, unmeasured", "n": g("reviewed"),
                          "note": "A board task its reviewer or you approved, sent back or rejected: a verdict, not a score of the work"},
                         {"key": "excluded", "label": "Excluded, with a reason", "n": g("excluded") + g("stopped"), "note": "Not scoreable by design, or stopped before it finished"},
                         {"key": "inconclusive", "label": "Inconclusive", "n": inc, "note": "No verdict yet: each group below says why and what happens next"}],
            "excluded_reasons": reasons + ([{"reason": "Stopped or cancelled before it finished", "n": g("stopped")}] if g("stopped") else []),
            "inconclusive": inconclusive, "eligible": eligible, "scored_eligible": scored_eligible, "coverage_pct": _pct(scored_eligible, eligible),
            "accounted_pct": _pct(total - g("waiting") - g("undiagnosed"), total), "target": COVERAGE_TARGET, "scored": scored, "reviewed": g("reviewed"),
            "rule_note": "Since G5-5 L5.1 a board task's review is counted as reviewed, not as a score: earlier runs in the period keep the score they were given."}


# ---------------------------------------------------------------- budgets: four scopes, and the reconciliation
def budgets(ch, me, competitions, now):
    uid, q, has = me["id"], ch.db.q, ch._has
    core = agent_core.get()
    scopes, lims = [], []
    if core is not None:
        try: lims = core.limit_status(uid)
        except Exception: lims = []  # noqa: BLE001
    cap = core.cap(uid) if core is not None else None
    spent = core.spent_today(uid) if core is not None else 0
    glob = [L for L in lims if L["scope"] == "global" and L.get("tokens")]
    month = [L for L in glob if L["period"] == "month"]
    policy = core.policy(uid) if core is not None else None
    hits = q("SELECT COUNT(*) AS n FROM ac_limit_hits WHERE owner_id=? AND ts>?", (uid, now - WEEK), one=True)["n"] if has("ac_limit_hits") else 0
    scopes.append({"scope": "company", "label": "Company", "required": "Maximum total daily and monthly spending",
                   "set": bool(cap or glob), "hard": bool(cap or any(L["mode"] != "alert" for L in glob)),
                   "detail": "; ".join(x for x in (f"daily limit {cap:,} tokens ({spent:,} used today)" if cap else "",
                                                   *(f"global limit {L['tokens']:,} per {L['period']} ({L['spent']:,} used)" for L in glob)) if x)
                             or ("Running without a cap, acknowledged" if policy and policy["state"] == "unlimited" else "No daily or monthly limit is set"),
                   "missing": [x for x in ("a daily limit" if not (cap or any(L["period"] == "day" for L in glob)) else "", "a monthly limit" if not month else "") if x],
                   "where": "Checked before every model call (agent_core.over)", "go": "layers"})
    comp_rows, team_rows, task_rows = [], [], []
    for c in competitions:
        wid = c["comp_id"]
        pol = (q("SELECT * FROM ml_policy WHERE comp_id=?", (wid,), one=True) or {}) if has("ml_policy") else {}
        total = q("SELECT COALESCE(SUM(tokens),0) AS n FROM mw_runs WHERE comp_id=?", (wid,), one=True)["n"] if has("mw_runs") else 0
        comp_rows.append({"name": c["title"], "set": bool(pol.get("total_cap")), "tokens": pol.get("total_cap"), "spent": total})
        b = c["budget"]
        team_rows.append({"name": c["title"], "set": bool(b["tokens"]), "tokens": b["tokens"], "spent": b["used_24h"]})
        tc = pol.get("task_cap")
        task_rows.append({"name": c["title"], "set": True, "tokens": tc if tc is not None else (max(60_000, int((b["tokens"] or 0) * 0.15)) if b["tokens"] else None),
                          "auto": tc is None})
    scopes.append({"scope": "competition", "label": "Competition", "required": "A separate competition budget", "set": bool(comp_rows) and all(r["set"] for r in comp_rows),
                   "hard": True, "rows": comp_rows, "detail": f"{sum(1 for r in comp_rows if r['set'])} of {len(comp_rows)} competitions have a lifetime cap",
                   "missing": [f"a lifetime cap for {r['name']}" for r in comp_rows if not r["set"]],
                   "where": "Checked by the team's governor before work starts (Autoloop → Competition budget)", "go": "teams"})
    scopes.append({"scope": "team", "label": "Team", "required": "A daily execution and experimentation budget", "set": bool(team_rows) and all(r["set"] for r in team_rows),
                   "hard": True, "rows": team_rows, "detail": f"{sum(1 for r in team_rows if r['set'])} of {len(team_rows)} teams have a 24-hour budget",
                   "missing": [f"a 24-hour budget for {r['name']}" for r in team_rows if not r["set"]],
                   "where": "Before work starts (governor), at each tool call, and before every model call of a run in flight (gateway)", "go": "teams"})
    per = [L for L in lims if L["scope"] in ("agent", "contract") or L.get("per_call")]
    scopes.append({"scope": "task", "label": "Agent / task", "required": "Per-run token, time and resource limits", "set": bool(task_rows) or bool(per), "hard": True, "rows": task_rows,
                   "detail": (f"{_s(len(task_rows), 'team')} with a per-task token cap" if task_rows else "No team task caps") + (f"; {_s(len(per), 'agent, contract or per-call limit')}" if per else ""),
                   "missing": [] if per else ["a per-call or per-agent limit for agents outside the teams"],
                   "where": "A team task files what it has at its cap and stops at 150%; per-call limits cap each model call's output", "go": "layers"})
    return {"scopes": scopes, "refused_7d": hits, "policy": policy, "reconcile": [reconcile(ch, uid, c, now) for c in competitions]}


def reconcile(ch, uid, c, now):
    """A team's 24-hour budget against every count of its tokens over the same window, and what explains a gap."""
    q, has = ch.db.q, ch._has
    wid, since = c["comp_id"], now - DAY
    budget = c["budget"]["tokens"]
    fin = q("SELECT COALESCE(SUM(tokens),0) AS n, COUNT(*) AS runs FROM mw_runs WHERE comp_id=? AND started>? AND status!='running'", (wid, since), one=True) if has("mw_runs") else {"n": 0, "runs": 0}
    led = fly = {"n": 0, "runs": 0}
    by_kind, by_model, biggest = [], [], []
    if has("ac_runs") and "team" in ch._cols("ac_runs"):
        team = f"comp:{wid}"
        led = q("SELECT COALESCE(SUM(tokens),0) AS n, COUNT(*) AS runs FROM ac_runs WHERE owner_id=? AND team=? AND started>?", (uid, team, since), one=True)
        fly = q("SELECT COALESCE(SUM(tokens),0) AS n, COUNT(*) AS runs FROM ac_runs WHERE owner_id=? AND team=? AND status='running'", (uid, team), one=True)
        by_kind = q("SELECT kind AS kind, COALESCE(SUM(tokens),0) AS tokens, COUNT(*) AS runs FROM ac_runs WHERE owner_id=? AND team=? AND started>? GROUP BY kind ORDER BY SUM(tokens) DESC LIMIT 8",
                    (uid, team, since))
        by_model = q("""SELECT COALESCE(model, '') AS model, COALESCE(SUM(tokens),0) AS tokens, COUNT(*) AS runs FROM ac_runs WHERE owner_id=? AND team=? AND started>?
                        GROUP BY COALESCE(model, '') ORDER BY SUM(tokens) DESC LIMIT 8""", (uid, team, since))
        biggest = q("SELECT id, kind, title, model, tokens, status, started FROM ac_runs WHERE owner_id=? AND team=? AND started>? ORDER BY tokens DESC LIMIT 5", (uid, team, since))
    counted = (fin["n"] or 0) + (fly["n"] or 0)
    plan = sum(r["tokens"] for r in by_model if str(r["model"]).split(":")[0] in ("terminal", "codex", "copilot-cli"))
    all_m = sum(r["tokens"] for r in by_model) or 0
    over = max(0, counted - budget) if budget else 0
    causes = []
    if budget and over:
        # likely causes, from what the records show; none is proof of what happened in a given run
        if all_m and plan / all_m >= 0.5:
            causes.append(f"{round(100 * plan / all_m)}% of the tokens came from plan (CLI) runs. Likely cause for runs made before the token-count fix: a CLI turn "
                          "counted every re-read of its cached context, many times what the same work counts through the API. Runs made since count input, cache "
                          "writes and output only (CLI_COUNT_CACHE_READS=1 restores the old count).")
        codex = sum(r["tokens"] for r in by_model if str(r["model"]).startswith("codex:"))
        if codex and codex >= counted * 0.3:
            causes.append("Codex reports a run's usage only when the run ends, so a Codex run can't be stopped mid-run by the budget: only its start is checked.")
        if biggest and biggest[0]["tokens"] and biggest[0]["tokens"] > budget * 0.5:
            causes.append(f"One run alone counted {biggest[0]['tokens']:,} tokens ({_clip(biggest[0]['title'] or biggest[0]['kind'], 60)}). Before the gateway check the budget was "
                          "read only when a run started; a run now stops before its next model call once the team is over.")
        if not causes:
            causes.append("Several runs started under the budget and finished over it: runs in flight used not to count until they ended. They now count as they spend.")
    diff = (led["n"] or 0) - counted
    return {"ref": c["ref"], "name": c["title"], "budget": budget, "finished": fin["n"] or 0, "finished_runs": fin["runs"] or 0, "in_flight": fly["n"] or 0,
            "in_flight_runs": fly["runs"] or 0, "counted": counted, "ledger": led["n"] or 0, "ledger_runs": led["runs"] or 0, "ledger_diff": diff, "over": over,
            "over_x": round(counted / budget, 1) if budget and over else None, "plan_share": round(100 * plan / all_m) if all_m else None,
            "by_kind": by_kind, "by_model": by_model, "biggest": biggest, "causes": causes,
            "state": "over" if over else "unset" if not budget else "near" if counted >= budget * 0.85 else "ok",
            "note": "" if abs(diff) <= max(1000, counted * 0.02) else
                    f"The ledger and the team's own count differ by {abs(diff):,} tokens: the ledger adds tokens per model call, the team's rows when a run ends."}


# ---------------------------------------------------------------- one registry over the improvement loops
def evolution_registry(ch, uid, comps, now):
    """Every improvement loop's changes as one list: source, target, stage, and whether reproducible benchmark evidence backs it.
    A change to an agent is not an improvement of the miner: a competition-linked change also shows the team's benchmark after it."""
    q, has = ch.db.q, ch._has
    items = []
    def add(source, where, id_, target, title, stage, evidence, ts, comp=None, base=None, cand=None, view="evolution"):
        items.append({"source": source, "where": where, "id": id_, "target": target, "title": _clip(title, 140), "stage": stage, "evidence": bool(evidence),
                      "baseline": base, "candidate": cand, "ts": ts, "comp": comp, "view": view})
    STG = {"proposed": "proposed", "draft": "proposed", "testing": "testing", "running": "testing", "trial": "testing", "verified": "verified", "better": "verified",
           "not_better": "rejected", "rejected": "rejected", "failed": "rejected", "declined": "rejected", "promoted": "promoted", "kept": "promoted",
           "rolled_back": "rolled_back", "regressed": "regressed", "open": "proposed", "done": "verified", "watching": "promoted"}
    if has("ev_proposals"):
        for p in q("""SELECT id, target_key, target_name, title, status, evidence, benchmark_id, created, tested, promoted FROM ev_proposals WHERE user_id=?
                      ORDER BY id DESC LIMIT 40""", (uid,)):
            e = _j(p["evidence"], {}) or {}
            add("evolution", "Evolution Lab", p["id"], p["target_name"] or p["target_key"], p["title"], STG.get(p["status"], p["status"]),
                e.get("cases") and e.get("baseline") is not None and e.get("candidate") is not None, p["promoted"] or p["tested"] or p["created"],
                base=e.get("baseline"), cand=e.get("candidate"))
    if has("wf_improvements"):
        for p in q("SELECT id, agent_id, change, status, baseline, candidate, trials, updated FROM wf_improvements WHERE user_id=? ORDER BY id DESC LIMIT 30", (uid,)):
            add("workforce", "Workforce trial", p["id"], f"Workforce agent {p['agent_id']}", p["change"], STG.get(p["status"], p["status"]),
                (p["trials"] or 0) > 0 and p["baseline"] and p["candidate"], p["updated"], view="workforce")
    flows = {}
    if has("mb_flows") and comps:
        flows = {r["id"]: r["comp_id"] for r in q(f"SELECT id, comp_id FROM mb_flows WHERE comp_id IN ({_marks(comps)})", list(comps))}
    if flows and has("mb_improvements"):
        watch = {r["improvement_id"]: r["status"] for r in q(f"SELECT improvement_id, status FROM mb_watches WHERE flow_id IN ({_marks(flows)})", list(flows))} if has("mb_watches") else {}
        for p in q(f"SELECT id, flow_id, agent_id, change, status, trial, result, updated FROM mb_improvements WHERE flow_id IN ({_marks(flows)}) ORDER BY id DESC LIMIT 30", list(flows)):
            st = watch.get(p["id"]) if watch.get(p["id"]) in ("rolled_back", "kept") else p["status"]
            add("workflow", "Workflow improvement", p["id"], f"Workflow agent {p['agent_id']}", p["change"], STG.get(st, st), bool(p["trial"]) and bool(p["result"]), p["updated"],
                comp=flows[p["flow_id"]], view="teams")
    if has("au_agents") and comps:
        for p in q(f"""SELECT id, comp_id, name, verdict, decision, base_score, cand_score, hash, finished, started FROM au_agents WHERE comp_id IN ({_marks(comps)})
                       AND (verdict IS NOT NULL OR decision IS NOT NULL) ORDER BY id DESC LIMIT 30""", list(comps)):
            st = "promoted" if p["decision"] == "promoted" else "rejected" if p["decision"] in ("declined", "rejected", "kept_old") else "verified" if p["verdict"] in ("promote", "better", "pass") else "rejected"
            add("upgrade", "Upgrade sprint", p["id"], p["name"], f"Upgraded instructions for {p['name']}", st, p["base_score"] is not None and p["cand_score"] is not None, p["finished"] or p["started"],
                comp=p["comp_id"], base=p["base_score"], cand=p["cand_score"], view="teams")
    if has("mc_experiments"):
        for p in q("SELECT id, comp_id, title, stage, status, base, cand, evidence_hash, updated FROM mc_experiments WHERE user_id=? ORDER BY id DESC LIMIT 30", (uid,)):
            sg = str(p["stage"] or "").lower()
            st = ("rolled_back" if "roll" in sg else "promoted" if sg in ("deployed", "monitor", "monitoring", "done", "kept") else "verified" if sg in ("approval", "approved", "review")
                  else "rejected" if str(p["status"] or "") in ("rejected", "closed", "abandoned") else "testing" if sg in ("sandbox", "benchmark", "test", "testing") else "proposed")
            add("experiment", "Command center experiment", p["id"], "The miner", p["title"], st, bool(p["evidence_hash"]) or (p["base"] and p["cand"]), p["updated"], comp=p["comp_id"], view="mining")
    # the miner's own measure after a competition-linked change: the team's comparable benchmark before and after it
    if has("mw_bench"):
        for it in items:
            if not it["comp"] or it["stage"] not in ("promoted", "rolled_back") or not it["ts"]: continue
            a = q("SELECT score FROM mw_bench WHERE comp_id=? AND comparable=1 AND ts<=? ORDER BY id DESC LIMIT 1", (it["comp"], it["ts"]), one=True)
            b = q("SELECT score FROM mw_bench WHERE comp_id=? AND comparable=1 AND ts>? ORDER BY id DESC LIMIT 1", (it["comp"], it["ts"]), one=True)
            if a and b and a["score"] is not None and b["score"] is not None:
                it["miner"] = {"before": a["score"], "after": b["score"], "delta": round(b["score"] - a["score"], 4)}
    items.sort(key=lambda x: -(x["ts"] or 0))
    by = {}
    for it in items: by[it["stage"]] = by.get(it["stage"], 0) + 1
    promoted = [it for it in items if it["stage"] == "promoted"]
    return {"items": items[:60], "by_stage": by, "sources": sorted({it["where"] for it in items}),
            "promoted": len(promoted), "promoted_with_evidence": sum(1 for it in promoted if it["evidence"]),
            "awaiting": [it for it in items if it["stage"] == "verified"][:10],
            "tested_7d": sum(1 for it in items if it["stage"] in ("verified", "rejected", "promoted", "rolled_back") and (it["ts"] or 0) > now - WEEK),
            "rollbacks": by.get("rolled_back", 0),
            "rule": "One rule for every loop: a change is promoted only on a baseline-versus-candidate result on the same frozen benchmark, judged by someone other than its author."}


# ---------------------------------------------------------------- the one decision queue
def decision_queue(ch, me, competitions, custom, tasks, bud, evo, now):
    uid, q, has = me["id"], ch.db.q, ch._has
    out = []
    def add(kind, level, title, detail, owner, go=None, ref=None, ts=None, action=""):
        out.append({"kind": kind, "level": level, "title": _clip(title, 160), "detail": _clip(detail, 400), "owner": owner, "go": go, "ref": ref, "ts": ts, "action": action})
    # P3 (D-023): this week's sample of agent approvals waiting for a person, and any disagreement (flagged, nothing reopened)
    try:
        ids = [c["comp_id"] for c in competitions]
        sm = sample_summary(ch, uid, ids, now) if ids else None
        if sm and sm["pending"]:
            add("verify", "info", f"Check {_s(sm['pending'], 'agent-approved task')} this week",
                f"A reproducible {round(sm['rate'] * 100)}% sample of work agents approved. Your verdict is the only person's check on agent approvals.",
                "you", "control", action="verify")
        if has("mo_verdicts"):
            for v in q("SELECT task_id, note, at FROM mo_verdicts WHERE user_id=? AND source='sample' AND verdict='disagree' AND at>?", (uid, now - 30 * DAY)):
                add("verify", "warn", f"You disagreed with an agent approval on #{v['task_id']}", v["note"] or "Recorded; the task was not reopened. Decide whether to send it back.",
                    "you", "control", f"mw:{v['task_id']}", v["at"])
    except Exception:  # noqa: BLE001 - the queue still shows the rest
        pass
    # critical infrastructure failures
    if has("io_sbx") and has("mw_sbx"):
        ids = [c["comp_id"] for c in competitions]
        if ids:
            r = q(f"""SELECT d.cls AS cls, MAX(d.recovery) AS recovery, COUNT(*) AS n FROM io_sbx d JOIN mw_sbx s ON s.id=d.sbx_id WHERE s.comp_id IN ({_marks(ids)}) AND s.started>?
                      GROUP BY d.cls ORDER BY COUNT(*) DESC LIMIT 1""", (*ids, now - DAY), one=True)
            if r and r["n"] >= 3: add("infra", "stop" if r["n"] >= 10 else "warn", f"{r['n']} sandbox runs couldn't run in 24 hours ({r['cls']})", r["recovery"] or "Repair the sandbox, then retry.", "AXoR", "layers")
    if has("io_events"):
        n = q("SELECT COUNT(*) AS n FROM io_events WHERE owner_id=? AND status='dead'", (uid,), one=True)["n"]
        if n: add("infra", "warn", f"{_s(n, 'handoff')} between layers failed for good (dead letters)", "Open Intelligence layers → Adaptive evolution and retry or dismiss each.", "you", "layers")
    for c in competitions:
        d, r = c["decision"], c["ref"]
        if d["situation"] in ("provider", "environment"):
            add("infra", "warn", f"{c['title']}: {d['label'].lower()}", f"{d['blocker']}. {d['next']}", d["owner"], "teams", r)
        elif d["situation"] in ("budget",):
            add("budget", "stop", f"{c['title']}: its 24-hour budget is spent", f"{d['blocker']}. {d['next']}", "you", "teams", r, action="budget")
        elif d["situation"] in ("regression",):
            add("regression", "stop", f"{c['title']}: regression", f"{d['blocker']}. {d['next']}", "you", "teams", r)
        elif d["situation"] in ("repeated", "task_failure"):
            add("regression", "warn", f"{c['title']}: {d['label'].lower()}", f"{d['blocker']}. {d['next']}", d["owner"], "teams", r)
        elif d["situation"] == "paused":
            add("human", "warn", f"{c['title']} is paused", f"{d['blocker']}. {d['next']}", "you", "teams", r)
        elif d["situation"] == "no_progress":
            add("milestone", "warn", f"{c['title']}: no progress", f"{d['blocker']}. {d['next']}", d["owner"], "teams", r)
        for a in [x for x in c.get("attention") or [] if x["state"] == "BLOCKED"][:3]:  # a board task waiting on a person
            add("human", "warn", f"{c['title']}: “{_clip(a['title'], 80)}” needs an answer", a.get("why") or "Blocked on the team's board: answer its question there.", "you", "teams", r, a.get("updated"))
        need = next((x for x in c["criteria"] if not x.get("off") and not (x["verified"] and (x["value"] or 0) >= 1)), None)
        if need and need["owner"] == "you":
            add("milestone", "warn", f"{c['title']}: {need['label']}", f"{need['evidence']}. {need['needs']}", "you", "mining" if need["key"] in ("registration", "submission") else "control", r)
    for rc in bud["reconcile"]:
        if rc["state"] == "over" and rc["over_x"] and rc["over_x"] >= 2:
            add("budget", "stop", f"{rc['name']}: {rc['counted']:,} tokens against a {rc['budget']:,} budget ({rc['over_x']}×)", " ".join(rc["causes"]) or "Reconcile before restarting autonomous work.", "you", None, rc["ref"], action="budget")
    co = next((s for s in bud["scopes"] if s["scope"] == "company"), None)
    if co and not co["set"] and not (bud.get("policy") or {}).get("state") == "unlimited":
        add("budget", "stop", "No company-wide spending limit is set", "A warning is not a hard budget. Set a daily and a monthly limit (Intelligence layers → Performance → Budgets suggests them), or confirm you run without one.", "you", "layers", action="budget")
    # work blocked on a person
    for t in tasks:
        if t["canon"] == "BLOCKED" and t["status"] in ("needs_input", "review", "todo"):
            add("human", "warn", f"Task needs you: {t['title']}", (t.get("why") or {}).get("text") or t.get("stage_note") or "Waiting for your answer.", "you", "control", f"ctl:{t['id']}", t.get("updated"))
    for c in custom:
        if c["state"] == "BLOCKED": add("human", "warn", f"Mission needs you: {c['title']}", c["decision"]["next"], "you", "mos", c["ref"], c.get("updated"))
    prop = sum(1 for t in tasks if t["status"] == "proposed")
    if prop: add("human", "info", f"{_s(prop, 'proposed task')} wait for your approval", "Mission Intelligence proposed them; approve or decline in Control Hub → Tasks.", "you", "control")
    # approvals, with the stale ones named
    pend = []
    if getattr(ch, "cmd", None):
        try: pend = [p for p in ch.cmd.view(me)["pending"] if p.get("kind") != "wait"]
        except Exception: pend = []  # noqa: BLE001
    if pend:
        def _t(x):
            try: return float(x)
            except (TypeError, ValueError): return None
        stale = [p for p in pend if (_t(p.get("ts")) or now) < now - STALE_APPROVAL]
        add("human", "stop" if stale else "warn", f"{_s(len(pend), 'approval')} pending" + (f", {len(stale)} older than {STALE_APPROVAL // DAY} days" if stale else ""),
            ("Stale approvals block the work behind them: decide or dismiss the oldest first. " if stale else "") + "; ".join(_clip(p["title"], 60) for p in (stale or pend)[:3]),
            "you", "approvals", ts=min((_t(p.get("ts")) or now) for p in pend))
    # candidate promotions and regressions from the evolution loops
    for it in evo["awaiting"][:5]:
        add("promotion", "info", f"Verified, waiting for your promotion: {it['title']}", f"{it['where']} · {it['target']}" + (f" · {it['baseline']} → {it['candidate']}" if it["baseline"] is not None and it["candidate"] is not None else ""),
            "you", it["view"], ts=it["ts"])
    if has("io_monitor"):
        n = q("SELECT COUNT(*) AS n FROM io_monitor WHERE owner_id=? AND state='regressed'", (uid,), one=True)["n"]
        if n: add("regression", "stop", f"{_s(n, 'promoted change')} scored worse after promotion", "Roll back, or keep it knowingly (Evolution Lab).", "you", "evolution")
    rank = {"stop": 0, "warn": 1, "info": 2}
    out.sort(key=lambda x: (rank.get(x["level"], 1), 0 if x["owner"] == "you" else 1, x["ts"] or now))
    return out[:40]


# ---------------------------------------------------------------- G5 readiness: the twelve acceptance rows, from records
# Evidence levels of a readiness row (Owner decision 2026-11-11, D-020). A row's pass/partial/fail/unknown state follows from its
# level: only records of real operation pass. Design-only capabilities are "implemented" and never count as demonstrated.
LEVELS = ("demonstrated", "operational", "partial", "implemented", "unknown", "fail")
LEVEL_LABEL = {"demonstrated": "Independently demonstrated", "operational": "Operationally tested", "partial": "Partial",
               "implemented": "Implemented", "unknown": "Unknown", "fail": "Fails"}
LEVEL_NOTE = {"demonstrated": "Records hold evidence from outside the actor and its team: an independent reviewer, an official measurement, a person's approval of a governed action (Milestone 3: a team owner's review of the team's work isn't independent verification)",
              "operational": "This server's records show it working in real operation, with nothing failing it",
              "partial": "Records show it working for some cases and missing or failing for others",
              "implemented": "Built and enforced by design, but no record on this server shows it in operation yet",
              "unknown": "No records to judge it by",
              "fail": "Records show the requirement broken"}
LEVEL_STATE = {"demonstrated": "pass", "operational": "pass", "partial": "partial", "implemented": "unknown", "unknown": "unknown", "fail": "fail"}


def readiness(ch, me, v, now):
    uid, q, has = me["id"], ch.db.q, ch._has
    rows = []
    def row(key, label, required, level, detail, go=None, evidence=None, state=None):
        """level: the evidence (LEVELS); state: what it means for the requirement, from the level unless the records say more
        (a requirement that is broken by configuration, e.g. no limit set, fails whatever is implemented)."""
        rows.append({"key": key, "label": label, "required": required, "level": level, "level_label": LEVEL_LABEL[level],
                     "state": state or LEVEL_STATE[level], "detail": detail, "go": go, "evidence": evidence or {},
                     "basis": "records" if level in ("demonstrated", "operational", "partial", "fail") else "design" if level == "implemented" else "none"})
    comps = v["competitions"]
    no_obj = [c["title"] for c in comps if not c.get("has_objective")]
    row("visibility", "Competition visibility", "Every active competition has an objective and current status",
        "unknown" if not comps else "partial" if no_obj else "operational", "No active competition" if not comps else f"No objective: {', '.join(no_obj)}" if no_obj else
        f"{_s(len(comps), 'competition')} with an objective, a status and a next action", "control", {"competitions": len(comps), "without_objective": len(no_obj)})
    # agents: each has open work on record; an idle state is shown by design, not recorded, so it doesn't count as evidence
    agents = idle = 0
    if has("mw_agents") and comps:
        ids = [c["comp_id"] for c in comps]
        a = q(f"""SELECT COUNT(*) AS n, SUM(CASE WHEN EXISTS (SELECT 1 FROM mw_tasks t WHERE t.agent_id=g.id AND t.status NOT IN ('done')) THEN 0 ELSE 1 END) AS idle
                  FROM mw_agents g WHERE g.comp_id IN ({_marks(ids)}) AND g.active=1""", ids, one=True)
        agents, idle = a["n"] or 0, a["idle"] or 0
    row("agents", "Agent accountability", "Every active agent has an assigned objective or an explicit idle state",
        "unknown" if not agents else "operational" if not idle else "implemented" if idle == agents else "partial",
        "No team agents" if not agents else f"{agents - idle} of {agents} team agents have open work on record on their competition's objective; "
        f"{idle} idle (an idle state shown by design, objective inherited from the team: not evidence)", "teams", {"agents": agents, "with_work": agents - idle, "idle": idle})
    open_tasks = [t for t in v["_tasks"] if t["canon"] in ("PLANNED", "READY", "RUNNING", "REVIEW", "BLOCKED", "FAILED", "PAUSED")]
    no_next = [t for t in open_tasks if not ((t.get("why") or {}).get("text") or t.get("stage_note") or t["canon"] in ("RUNNING",))]
    row("tasks", "Task observability", "Every task has an owner, status, blocker and next action",
        "unknown" if not open_tasks else "partial" if no_next else "operational",
        "No open task" if not open_tasks else f"{len(open_tasks) - len(no_next)} of {len(open_tasks)} open tasks say why they stand where they do and who moves them next",
        "control", {"open": len(open_tasks), "without_next": len(no_next)})
    acc = v["accountability"]
    if not acc or not acc["total"]: row("runs", "Run accountability", "Every terminal run has a settled outcome", "unknown", "No finished run this week", "layers")
    else:
        inc = next(o["n"] for o in acc["outcomes"] if o["key"] == "inconclusive")
        row("runs", "Run accountability", "Every terminal run has a settled outcome", "operational" if not inc else "partial" if acc["accounted_pct"] and acc["accounted_pct"] >= 95 else "fail",
            f"{acc['total'] - inc} of {acc['total']} finished runs this week have a final outcome; {inc} inconclusive, each with a reason and a next action", "layers",
            {"runs": acc["total"], "inconclusive": inc})
    if not acc or not acc["eligible"]: row("coverage", "Evaluation coverage", f"At least {COVERAGE_TARGET}% of eligible runs scored", "unknown", "No eligible run this week", "layers")
    else:
        row("coverage", "Evaluation coverage", f"At least {COVERAGE_TARGET}% of eligible runs scored, the rest accounted for",
            "operational" if acc["coverage_pct"] >= COVERAGE_TARGET else "partial" if acc["coverage_pct"] >= 70 else "fail",
            f"{acc['scored_eligible']} of {acc['eligible']} eligible runs scored ({acc['coverage_pct']}%)", "layers",
            {"eligible": acc["eligible"], "scored": acc["scored_eligible"], "pct": acc["coverage_pct"]})
    # verification: the state model holds it by design; records show it only when verdicts exist and unverified work is held apart
    an = v["activity_note"]
    unv, ver, drp = an.get("unverified_done", 0), an.get("verified_total", 0), an.get("dropped", 0)
    mxd = q("SELECT COUNT(*) AS n, SUM(CASE WHEN outcome='verified' THEN 1 ELSE 0 END) AS v FROM mx_missions WHERE user_id=? AND status='delivered' AND finished>?", (uid, now - 30 * DAY), one=True) if has("mx_missions") else None
    dn, dv = ((mxd or {}).get("n") or 0), ((mxd or {}).get("v") or 0)
    sm, th = an.get("sample") or {}, demonstrated_threshold(ch)
    checked = (sm.get("agree_30d") or 0) + (sm.get("disagree_30d") or 0)
    shown = checked >= int(th["min"]) and 100 * (sm.get("agree_30d") or 0) / max(1, checked) >= float(th["agree"])
    agr = f", {round(100 * (sm.get('agree_30d') or 0) / checked, 1)}% agreement" if checked else ", no agreement yet"
    # Milestone 3: the owner's reviews meeting the threshold are a person's check of the agents, recorded as operational; never
    # "demonstrated", which needs a reviewer independent of the team (no such role yet)
    row("verification", "Objective verification", "No mission declared successful without independent evidence",
        "operational" if shown or ver or dv else "implemented",
        f"Agent-approved: {an.get('verified_by_agent', 0)} tasks. Owner-reviewed (30 days): {checked + (sm.get('unsure_30d') or 0)} verdicts, {checked} decided, "
        f"{sm.get('disagree_30d', 0)} disagree{agr}; the Owner's threshold ({th['min']} reviews at {th['agree']}%) is {'met' if shown else 'not met'}. "
        "Independently demonstrated: no (a team owner's review isn't independent verification, and no independent reviewer exists yet). "
        + (f"{ver} board tasks ({an.get('verified_by_person', 0)} approved by a person, {an.get('verified_by_agent', 0)} by an agent reviewer) and {dv} of {dn} delivered "
         "missions (30 days) carry an independent verdict; " if ver or dv else "No independent verdict on record yet; ")
        + f"{unv} tasks closed without a verdict and {dn - dv} delivered missions without a verified outcome are held out of Verified; {drp} dropped tasks counted as neither "
        "(the hold is by design: the state model). "
        + (f"A person decided {checked} sampled agent approvals in {th['days']} days ({sm.get('agree_30d', 0)} agree, {sm.get('disagree_30d', 0)} disagree; "
           f"{sm.get('unsure_30d', 0)} unsure counted apart); the Owner's threshold ({th['min']} reviews, {th['agree']}% agreement) is {'met' if shown else 'not met'}"),
        "control", {"owner_threshold_met": shown, "independently_demonstrated": False, "person_checked_30d": checked, "person_agree_30d": sm.get("agree_30d", 0), "person_unsure_30d": sm.get("unsure_30d", 0), "threshold": th, "verified_tasks": ver, "verified_by_person": an.get("verified_by_person", 0), "verified_by_agent": an.get("verified_by_agent", 0), "closed_without_verdict": unv, "dropped": drp, "missions_delivered": dn, "missions_verified": dv})
    if has("io_diag"):
        d = q("SELECT COUNT(*) AS n, SUM(CASE WHEN recovery IS NOT NULL AND recovery!='' THEN 1 ELSE 0 END) AS r FROM io_diag WHERE owner_id=? AND ts>?", (uid, now - WEEK), one=True)
        und = next((x["n"] for x in (acc or {}).get("inconclusive", []) if x["what"].startswith("Failed, not diagnosed")), 0)
        n, r = d["n"] or 0, d["r"] or 0
        row("recovery", "Failure recovery", "Every failure classified with an appropriate recovery action", "unknown" if not n and not und else "operational" if r == n and not und else "partial",
            "No failure this week" if not n and not und else f"{r} of {n} diagnosed failures carry a recovery action; {und} not diagnosed yet", "layers",
            {"diagnosed": n, "with_recovery": r, "undiagnosed": und})
    else: row("recovery", "Failure recovery", "Every failure classified with an appropriate recovery action", "unknown", "The orchestrator's diagnosis isn't running on this server", "layers")
    evo = v["evolution"]
    row("evolution", "Evolution", "Every promoted change has reproducible benchmark evidence", "unknown" if not evo["promoted"] else "operational" if evo["promoted_with_evidence"] == evo["promoted"] else "partial",
        "No promoted change yet: continuous evolution is not demonstrated" if not evo["promoted"] else f"{evo['promoted_with_evidence']} of {evo['promoted']} promoted changes have a baseline-versus-candidate result on record", "evolution",
        {"promoted": evo["promoted"], "with_evidence": evo["promoted_with_evidence"]})
    row("rollback", "Regression protection", "Rollback is tested and available", "operational" if evo["rollbacks"] else "implemented",
        f"{_s(evo['rollbacks'], 'rollback')} on record" if evo["rollbacks"] else "Rollback is available in every loop, but none has been exercised on this server yet: test one on a low-risk change", "evolution",
        {"rollbacks": evo["rollbacks"]}, state=None if evo["rollbacks"] else "partial")
    if has("ex_uses"):
        e = q("""SELECT SUM(CASE WHEN outcome='success' THEN 1 ELSE 0 END) AS s, SUM(CASE WHEN outcome='failure' THEN 1 ELSE 0 END) AS f, COUNT(*) AS n FROM ex_uses WHERE user_id=?""", (uid,), one=True)
        s, f, n = e["s"] or 0, e["f"] or 0, e["n"] or 0
        row("knowledge", "Knowledge", "Verified successes and failures can be recalled by future missions", "unknown" if not n else "operational" if s and f else "partial",
            "No experience has been recalled yet" if not n else f"{s} recalled experiences settled on success, {f} on failure"
            + ("" if f else ": no failure has ever settled, so the ranking can't yet learn what to avoid (failed attempts settle from this version on)"), "learning",
            {"recalled": n, "success": s, "failure": f})
    else: row("knowledge", "Knowledge", "Verified successes and failures can be recalled by future missions", "unknown", "Experience recall isn't on this server", "learning")
    sc = v["budget"]["scopes"]
    miss = [s["label"] for s in sc if not s["set"]]
    refused = v["budget"]["refused_7d"]
    row("budget", "Budget", "Hard limits enforced at all required scopes",
        ("operational" if refused else "implemented") if not miss else "partial" if len(miss) < len(sc) else "implemented",
        ("A hard limit is set at every scope" + (f"; {refused} calls refused at a limit this week" if refused else "; none has refused a call on this server yet")) if not miss else
        f"No limit at: {', '.join(miss)}. {refused} calls refused at a limit this week (the gateway is built; limits are configuration)", "layers",
        {"scopes": len(sc), "unset": len(miss), "refused_7d": refused}, state=None if not miss else "partial" if len(miss) < len(sc) else "fail")
    bare = q("SELECT COUNT(*) AS n FROM mc_deploys WHERE user_id=? AND approval_id IS NULL AND rollback_of IS NULL", (uid,), one=True)["n"] if has("mc_deploys") else None
    deps = q("SELECT COUNT(*) AS n FROM mc_deploys WHERE user_id=?", (uid,), one=True)["n"] if has("mc_deploys") else 0
    row("governance", "Governance", "External production actions require the appropriate human approval",
        "fail" if bare else "demonstrated" if deps else "implemented",
        f"{_s(bare, 'deploy')} on record without an approval: check Command center → Miners" if bare else
        (f"Every one of {_s(deps, 'deploy')} on record carries a person's approval. " if deps else "No deploy on record: the approval rule is held by design only. ") +
        "Registration, submissions, deploys, payments and limits are never done by policy: each waits for a person (Approval Center, hash-bound approvals)",
        "approvals", {"deploys": deps, "without_approval": bare or 0})
    # login attribution (D-019): every run with model calls this week records the login it ran on
    if has("ac_runs") and "login" in ch._cols("ac_runs"):
        lr = q("""SELECT COUNT(*) AS n, SUM(CASE WHEN login IS NOT NULL THEN 1 ELSE 0 END) AS m FROM ac_runs WHERE owner_id=? AND started>? AND tokens>0
                  AND kind!='earlier' AND status!='running'""", (uid, now - WEEK), one=True)
        n, m = lr["n"] or 0, lr["m"] or 0
        row("attribution", "Login attribution", "Every model run records the login it ran on, never a credential",
            "unknown" if not n else "operational" if m == n else "partial" if m else "implemented",
            "No finished run with model calls this week" if not n else f"{m} of {n} finished runs with model calls this week name their login"
            + ("" if m == n else f"; {n - m} don't (runs before this version, or a path that isn't attributed: see the review report)"), "layers", {"runs": n, "attributed": m})
    order = {"fail": 0, "partial": 1, "unknown": 2, "pass": 3}
    levels = {lv: sum(1 for r in rows if r["level"] == lv) for lv in LEVELS}
    return {"rows": rows, "pass": sum(1 for r in rows if r["state"] == "pass"), "total": len(rows), "levels": levels,
            "level_labels": LEVEL_LABEL, "level_notes": LEVEL_NOTE,
            "demonstrated": levels["demonstrated"], "design_only": levels["implemented"],
            "verdict": ("Operational" if all(r["state"] == "pass" for r in rows) else "Not demonstrated yet" if any(r["state"] in ("fail", "unknown") for r in rows) else "Partly operational"),
            "first": min(rows, key=lambda r: order[r["state"]])["label"] if rows else None}


# ---------------------------------------------------------------- a competition's page: performance model and strategy portfolio
# G5-5 L5.1: what a figure of the performance view is. Only "measured" is a measurement (D-005); the page prints the kind beside each figure
FIGURE_KINDS = {"measured": "Measured: read from the chain, a designated evaluator's report or a job's own output, with its evidence",
                "reported": "Reported: sent or filed by an agent or a person, not verified",
                "reviewed": "Reviewed: a person's or an agent's verdict, not a measurement of the work",
                "counted": "Counted: activity in the run ledger or on the board", "set": "Set by you", "unknown": "Unknown: nothing measured"}


def performance(ch, uid, c, w, now):
    """Five dimensions, kept apart: a good local benchmark with no rank is technical quality, not competition performance.
    G5-5 L5.1 (IC-11 change 5): every figure names its kind (FIGURE_KINDS), and the team's persistent mission's measures are shown
    from the one measured reader (missions.measured): a value with its five fields, or UNKNOWN with the reason."""
    q, has = ch.db.q, ch._has
    wid, team, wk = w["id"], f"comp:{w['id']}", now - WEEK
    s = c.get("standing") or {}
    metrics = {}
    if has("mc_metrics"):
        for r in q("SELECT metric, value, ts, source FROM mc_metrics WHERE user_id=? AND comp_id=? ORDER BY id DESC LIMIT 200", (uid, wid)):
            metrics.setdefault(r["metric"], r)
    figs = lambda xs: [{"label": x[0], "value": x[1], "note": x[2], "kind": x[3]} for x in xs]
    unknown = s.get("rank") is None
    try: mm = ch.mx.team_measured(wid, now) if getattr(ch, "mx", None) else None
    except Exception as e:  # noqa: BLE001 - the view still answers; the measures read UNKNOWN with the reason
        mm = {"measures": [], "error": f"{type(e).__name__}: {_clip(e, 120)}"}
    def measures(tier):
        if mm is None: return [("Mission measures", "UNKNOWN", "No persistent mission evaluates this team, so nothing here comes from the measured reader", "unknown")] if tier == "external" else []
        if mm.get("error"): return [("Mission measures", "UNKNOWN", f"The measured reader couldn't answer ({mm['error']})", "unknown")] if tier == "external" else []
        out = []
        for x in [x for x in mm["measures"] if x["tier"] == tier]:
            f, v = x.get("fields") or {}, x["value"]
            val = "UNKNOWN" if x["state"] != "measured" else ("yes" if v is True else "no" if v is False else f"{v:g}" if isinstance(v, (int, float)) else str(v))
            if x["state"] == "measured" and x["pass"] is not None: val += " · meets the target" if x["pass"] else " · short of the target"
            note = x["reason"] if x["state"] != "measured" else f"{f.get('source')} · {time.strftime('%m-%d %H:%M', time.localtime(f['time']))} · {f.get('method')}"
            tgt = f"{x['target']:g}" if isinstance(x["target"], (int, float)) and not isinstance(x["target"], bool) else str(x["target"])
            out.append((f"Mission measure: {_clip(x.get('text') or x.get('metric') or x['id'], 60)} ({x['op']} {tgt})", val, note, "measured" if x["state"] == "measured" else "unknown"))
        return out
    has_m = lambda tier: bool(mm) and any(x["tier"] == tier and x["state"] == "measured" for x in mm.get("measures") or [])
    comp = {"key": "competition", "label": "Competition performance", "measured": not unknown or has_m("external"),
            "figures": figs([("Official rank", "UNKNOWN" if unknown else f"{s['rank']} of {s.get('of') or '?'}", "No ranked miner under your keys" if unknown else "", "unknown" if unknown else "measured"),
                             ("Target", f"Top {c['target_rank']}" if c.get("target_rank") else "not set", "", "set"),
                             ("Gap to the target", s.get("gap") if s.get("gap") is not None else "–", "", "measured" if s.get("gap") is not None else "unknown"),
                             ("Leader", s.get("top1") if s.get("top1") is not None else "–", "the top miner's rewards per day", "measured" if s.get("top1") is not None else "unknown"),
                             *[(k.replace("_", " ").capitalize(), f"{v['value']:g}", f"reported {time.strftime('%m-%d %H:%M', time.localtime(v['ts']))} ({v['source'] or 'no source'}): "
                                "a report, counted only where a mission measure below accepts it", "reported") for k, v in list(metrics.items())[:4]],
                             *measures("external")])}
    rel = q("SELECT * FROM mw_release WHERE comp_id=? AND current=1 ORDER BY id DESC LIMIT 1", (wid,), one=True) if has("mw_release") else None
    eref = "evidence_ref" if has("mw_bench") and "evidence_ref" in ch._cols("mw_bench") else "NULL AS evidence_ref"
    brel = "release_id" if has("mw_bench") and "release_id" in ch._cols("mw_bench") else "NULL AS release_id"
    bs = q(f"SELECT score, solved, suite, suite_tasks, ts, comparable, {eref}, {brel} FROM mw_bench WHERE comp_id=? ORDER BY id DESC LIMIT 12", (wid,)) if has("mw_bench") else []
    cmpb = [b for b in bs if b["comparable"]]
    # a benchmark score is measured only when a VM job's own output file gave it: the job's kept result is intact and still says
    # this score (runner.backed). Filed by an agent or a person, or naming a job whose result is gone or differs, it is a report
    from . import runner
    names_job = bool(cmpb) and str(cmpb[0]["evidence_ref"] or "").startswith("job:")
    bmeasure = runner.release_measure(ch.db, cmpb[0]["release_id"]) if cmpb else None  # D-034: the release's frozen measuring job, if any
    bkind = ("measured" if runner.backed(ch.db, wid, cmpb[0]["evidence_ref"], cmpb[0]["score"], bmeasure) else "reported") if cmpb else "unknown"
    bwhy = {"measured": "its job's own output file gave the score" + (", and it is this release's frozen measuring job" if bmeasure else ""),
            "reported": ("it names a job whose kept result is gone or says another score" + (", or that isn't this release's measuring job" if bmeasure else ""))
            if names_job else "filed by an agent or a person, not read from a job's output"}.get(bkind, "")
    tech = {"key": "technical", "label": "Technical quality", "measured": bool(cmpb) or has_m("internal"),
            "figures": figs([("Frozen candidate", f"v{rel['version']}" if rel else "none", _clip(rel.get("suite") or "", 60) if rel else "Freeze a candidate and its suite first", "set"),
                             ("Validation score", f"{cmpb[0]['score']:g}" if cmpb else "–",
                              "; ".join(x for x in (f"{cmpb[0]['solved']} of {cmpb[0]['suite_tasks']} solved" if cmpb and cmpb[0]["suite_tasks"] else "" if cmpb else "comparable results only", bwhy) if x), bkind),
                             ("Reference", f"{rel['reference_score']:g}" if rel and rel.get("reference_score") is not None else "–", "recorded when the candidate was frozen" if rel and rel.get("reference_score") is not None else "",
                              "reported" if rel and rel.get("reference_score") is not None else "unknown"),
                             ("Comparable results", len(cmpb), f"{len(bs) - len(cmpb)} not comparable (another candidate or suite)" if len(bs) > len(cmpb) else "", "counted"),
                             *measures("internal")])}
    ex = {"n": 0, "bad": 0, "sec": None}
    if has("ac_runs") and "team" in ch._cols("ac_runs"):
        r = q("""SELECT COUNT(*) AS n, SUM(CASE WHEN status IN ('failed','error','lost') THEN 1 ELSE 0 END) AS bad,
                        AVG(CASE WHEN status='done' AND finished IS NOT NULL THEN finished-started END) AS sec, COALESCE(SUM(tokens),0) AS tok, COALESCE(SUM(cost),0) AS usd
                 FROM ac_runs WHERE owner_id=? AND team=? AND started>? AND status!='running'""", (uid, team, wk), one=True)
        ex = {"n": r["n"] or 0, "bad": r["bad"] or 0, "sec": r["sec"], "tok": r["tok"] or 0, "usd": r["usd"] or 0}
    wp = c["work"]
    exe = {"key": "execution", "label": "Execution quality", "measured": bool(ex["n"]),
           "figures": figs([("Verified deliverables", wp["verified"], f"of {wp['original']} in the original scope ({wp['planned']} still planned); {wp['unverified']} delivered, not verified; {wp['dropped']} dropped (never counted as done). "
                             "Verified means approved by someone other than its author: a review, not a measurement of the work", "reviewed"),
                            ("Runs this week", ex["n"], "", "counted"), ("Failure rate", f"{_pct(ex['bad'], ex['n'])}%" if ex["n"] else "–", f"{ex['bad']} failed or lost", "counted"),
                            ("Median-ish latency", f"{round(ex['sec'] / 60)} min" if ex.get("sec") else "–", "average of finished runs", "counted")])}
    # validated = an approval closed it (approved_last), never a drop (D-018); RC1 counted every done task here
    if has("mw_tasks") and "done_at" in ch._cols("mw_tasks"):
        appr = approved_last(ch, [wid])
        v7 = sum(1 for r in q(f"SELECT id FROM mw_tasks WHERE comp_id=? AND status='done' AND done_at>? AND {tl_not_dropped(ch.db)}", (wid, wk)) if r["id"] in appr)
    else: v7 = 0
    tok = ex.get("tok") or 0
    eco = {"key": "economic", "label": "Economic efficiency", "measured": bool(tok),
           "figures": figs([("Tokens this week", f"{tok:,}", "", "counted"),
                            ("Tokens per validated task", f"{round(tok / v7):,}" if v7 else "–", (f"{v7} tasks validated this week" if v7 else "nothing validated this week") + " (validated = closed by an approval: a review)", "counted"),
                            ("Recorded cost", f"${ex.get('usd') or 0:.2f}", "plan (CLI) runs have no per-call price", "counted"),
                            ("Cost per validated task", f"${(ex.get('usd') or 0) / v7:.2f}" if v7 and ex.get("usd") else "–", "", "counted")])}
    delta = round(cmpb[0]["score"] - rel["reference_score"], 4) if cmpb and rel and rel.get("reference_score") is not None else None
    left = [x for x in c["criteria"] if not x.get("off") and not (x["verified"] and (x["value"] or 0) >= 1)]
    exp = q("SELECT COUNT(*) AS n FROM mc_experiments WHERE user_id=? AND comp_id=?", (uid, wid), one=True)["n"] if has("mc_experiments") else 0
    strat = {"key": "strategic", "label": "Strategic progress", "measured": delta is not None or bool(exp),
             "figures": figs([("Against the baseline", f"{'+' if delta and delta > 0 else ''}{delta:g}" if delta is not None else "–", "latest comparable score minus the reference (the reference is a report)",
                               "reported" if delta is not None else "unknown"),
                              ("Experiments", exp, "Command center → Experiments", "counted"), ("Milestones left", len(left), "; ".join(x["label"] for x in left[:3]), "reviewed"),
                              ("Objective progress", f"{c['objective_progress']['pct']}%" if c["objective_progress"]["pct"] is not None else "–", "verified criteria only", "reviewed")])}
    return [comp, tech, exe, eco, strat]


def portfolio(ch, uid, c, w, now):
    """The team's agents by strategy lane, with what each lane verified and spent this week, and where resources should go."""
    q, has = ch.db.q, ch._has
    if not has("mw_agents"): return None
    agents = q("SELECT id, name, title, role, squad, job, active FROM mw_agents WHERE comp_id=? AND active=1", (w["id"],))
    wk = now - WEEK
    done = {r["agent_id"]: r["n"] for r in q(f"SELECT agent_id, COUNT(*) AS n FROM mw_tasks WHERE comp_id=? AND status='done' AND {tl_not_dropped(ch.db)} AND done_at>? GROUP BY agent_id", (w["id"], wk))} if "done_at" in ch._cols("mw_tasks") else {}
    opn = {r["agent_id"]: r["n"] for r in q("SELECT agent_id, COUNT(*) AS n FROM mw_tasks WHERE comp_id=? AND status!='done' GROUP BY agent_id", (w["id"],))}
    tok = {r["agent_id"]: r["n"] for r in q("SELECT agent_id, COALESCE(SUM(tokens),0) AS n FROM mw_runs WHERE comp_id=? AND started>? GROUP BY agent_id", (w["id"], wk))} if has("mw_runs") else {}
    lanes = {k: {"key": k, "label": lb, "aim": aim, "what": what, "agents": [], "verified_7d": 0, "open": 0, "tokens_7d": 0} for k, lb, aim, what, _ in LANES}
    other = []
    for a in agents:
        text = " ".join(str(a.get(k) or "") for k in ("squad", "role", "title")).lower()
        job = str(a.get("job") or "").lower()
        key = next((k for k, *_x, pat in reversed(LANES) if re.search(pat, text)), None) or next((k for k, *_x, pat in reversed(LANES) if re.search(pat, job)), None)
        if a.get("role") in ("director",) or not key: other.append({"key": f"teams:{a['id']}", "name": a["name"], "title": a["title"]}); continue
        L = lanes[key]
        L["agents"].append({"key": f"teams:{a['id']}", "name": a["name"], "title": a["title"]}); L["verified_7d"] += done.get(a["id"], 0); L["open"] += opn.get(a["id"], 0); L["tokens_7d"] += tok.get(a["id"], 0)
    out = list(lanes.values())
    for L in out: L["yield"] = round(L["verified_7d"] / (L["tokens_7d"] / 1e6), 2) if L["tokens_7d"] else None
    ranked = sorted([L for L in out if L["yield"] is not None and L["verified_7d"]], key=lambda L: -L["yield"])
    empty = [L["label"] for L in out if not L["agents"]]
    advice = []
    if empty: advice.append(f"Nobody covers: {', '.join(empty)}. Agents shouldn't all investigate the same approach: give each lane an owner (Organization → the team → members).")
    if ranked:
        advice.append(f"{ranked[0]['label']} verifies the most per token this week ({ranked[0]['yield']} tasks per million): allocate more to it while it keeps winning on held-out tests.")
        if len(ranked) > 1 and ranked[-1]["yield"] < ranked[0]["yield"] / 3: advice.append(f"{ranked[-1]['label']} returns the least ({ranked[-1]['yield']} per million): when it stops improving, investigate an alternative there.")
    elif agents: advice.append("No lane has verified work this week: no basis yet for moving resources between them.")
    return {"lanes": out, "command": other, "advice": advice}


def mission(ch, me, ref):
    v = view(ch, me)
    c = next((x for x in v["competitions"] + v["custom"] if x["ref"] == ref), None)
    if not c: raise HTTPException(404, "There's no such active mission.")
    now, out = time.time(), {"mission": c, "states": v["states"]}
    if c["type"] == "predefined":
        w = ch._comps(me["id"]).get(c["comp_id"])
        out["performance"] = performance(ch, me["id"], c, w, now)
        out["figure_kinds"] = FIGURE_KINDS
        out["portfolio"] = portfolio(ch, me["id"], c, w, now)
        out["reconcile"] = next((r for r in v["budget"]["reconcile"] if r["ref"] == ref), None)
        out["evolution"] = [it for it in v["evolution"]["items"] if it["comp"] == c["comp_id"]][:12]
        out["sequence"] = [{"n": i + 1, "label": x["label"], "done": x["verified"] and (x["value"] or 0) >= 1, "evidence": x["evidence"], "needs": x["needs"], "owner": x["owner"]}
                           for i, x in enumerate(x for x in c["criteria"] if not x.get("off"))]
    return out


# ---------------------------------------------------------------- the person's criteria
class CriterionIn(BaseModel):
    key: str | None = Field(None, max_length=40)
    label: str | None = Field(None, max_length=200)
    weight: float | None = Field(None, ge=0, le=100)
    value: float | None = Field(None, ge=0, le=1)
    evidence: str | None = Field(None, max_length=1000)
    off: bool | None = None


def set_criterion(ch, me, ref, b: CriterionIn):
    if not re.fullmatch(r"(comp|mx):\d+", ref or ""): raise HTTPException(404, "There's no such mission.")
    from . import control_missions as cm
    cm._check_ref(ch, me["id"], ref)
    key = (b.key or "").strip().lower() or "x" + format(int(time.time() * 1000) % 10 ** 9, "x")
    if not re.fullmatch(r"[a-z0-9_]{1,40}", key): raise HTTPException(422, "A criterion's key is letters, digits and underscores.")
    auto = key in ("registration", "validation", "reliability", "submission", "rank", "sustain") or re.fullmatch(r"c\d+", key)
    if b.value is not None and auto: raise HTTPException(409, "This criterion is read from records: you can change its weight or switch it off, not its value.")
    if b.value is not None and not (b.evidence or "").strip(): raise HTTPException(422, "Say what verified it: a criterion without evidence counts as not achieved.")
    if not auto and not ch.db.q("SELECT 1 FROM mo_criteria WHERE user_id=? AND mission=? AND key=?", (me["id"], ref, key), one=True) and not (b.label or "").strip():
        raise HTTPException(422, "Give the criterion a name.")
    old = ch.db.q("SELECT * FROM mo_criteria WHERE user_id=? AND mission=? AND key=?", (me["id"], ref, key), one=True) or {}
    vals = {"label": b.label if b.label is not None else old.get("label"), "weight": b.weight if b.weight is not None else old.get("weight"),
            "value": b.value if b.value is not None else old.get("value"), "evidence": b.evidence if b.evidence is not None else old.get("evidence"),
            "off": int(b.off) if b.off is not None else old.get("off") or 0}
    ch.db.q("""INSERT INTO mo_criteria (user_id, mission, key, label, weight, value, evidence, off, by_user, ts) VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(user_id, mission, key) DO UPDATE SET label=excluded.label, weight=excluded.weight, value=excluded.value, evidence=excluded.evidence,
               off=excluded.off, by_user=excluded.by_user, ts=excluded.ts""",
            (me["id"], ref, key, vals["label"], vals["weight"], vals["value"], vals["evidence"], vals["off"], me["username"], time.time()))
    ch._audit(me["id"], me["username"], "ops.criterion.set", ref, f"{key}: weight {vals['weight']}, value {vals['value']}, off {vals['off']}")
    _cache.pop(me["id"], None)
    return mission(ch, me, ref)


def drop_criterion(ch, me, ref, key):
    n = ch.db.q("DELETE FROM mo_criteria WHERE user_id=? AND mission=? AND key=? RETURNING id", (me["id"], ref, key))
    if not n: raise HTTPException(404, "There's no such change to remove.")
    ch._audit(me["id"], me["username"], "ops.criterion.drop", ref, key)
    _cache.pop(me["id"], None)
    return mission(ch, me, ref)


# ---------------------------------------------------------------- drill-down: an agent
def agent(ch, me, key):
    """An agent's status derived from its own records: it never has to explain itself from scratch."""
    uid, q, has, now = me["id"], ch.db.q, ch._has, time.time()
    if not has("ac_runs"): raise HTTPException(409, "The run ledger isn't on this server.")
    a = q("SELECT * FROM ac_agents WHERE key=? AND owner_id=?", (key, uid), one=True) if has("ac_agents") else None
    runs = q("""SELECT id, system, kind, ref, title, status, model, tokens, cost, score, error, started, finished, corr, team FROM ac_runs
                WHERE owner_id=? AND agent_key=? ORDER BY id DESC LIMIT 40""", (uid, key)) if "corr" in ch._cols("ac_runs") else []
    if not a and not runs: raise HTTPException(404, "There's no such agent, or it has never run.")
    out = {"key": key, "name": (a or {}).get("name") or key, "role": (a or {}).get("role") or "", "system": agent_core.SYSTEMS.get((a or {}).get("system") or key.split(":")[0], key.split(":")[0])}
    v = view(ch, me)
    comp, team = None, next((r["team"] for r in runs if r.get("team")), None)
    local = key.split(":", 1)[1] if ":" in key else ""
    row = q("SELECT * FROM mw_agents WHERE id=?", (int(local),), one=True) if key.startswith("teams:") and local.isdigit() and has("mw_agents") else None
    if row: team = f"comp:{row['comp_id']}"
    if team: comp = next((c for c in v["competitions"] if c["ref"] == team), None)
    out["mission"] = {"ref": comp["ref"], "title": comp["title"], "objective": comp["objective"], "progress": comp["objective_progress"]["pct"],
                      "official": comp["objective_progress"]["official"]} if comp else None
    cur = None
    if row and has("mw_tasks"):
        cur = q("""SELECT id, title, status, hold, detail, note, updated FROM mw_tasks WHERE agent_id=? AND status NOT IN ('done') ORDER BY CASE status WHEN 'working' THEN 0
                   WHEN 'checking' THEN 1 WHEN 'queued' THEN 2 WHEN 'blocked' THEN 3 ELSE 4 END, updated DESC LIMIT 1""", (row["id"],), one=True)
    out["task"] = ({"ref": f"mw:{cur['id']}", "title": cur["title"], "state": state_board(cur), "deliverable": _clip(cur["detail"] or "", 400), "note": cur.get("note"), "updated": cur["updated"]}
                   if cur else None)
    out["idle"] = not cur and not any(r["status"] == "running" for r in runs)
    last = runs[0] if runs else None
    out["last_run"] = dict(last) if last else None
    wk = [r for r in runs if (r["started"] or 0) > now - WEEK]
    models = {}
    for r in wk:
        if r["model"]: models[r["model"]] = models.get(r["model"], 0) + 1
    out["models"] = [{"model": k, "runs": n} for k, n in sorted(models.items(), key=lambda x: -x[1])]
    tools = []
    if row and has("mw_spans") and has("mw_runs"):
        tools = q("""SELECT s.name AS name, COUNT(*) AS n, SUM(CASE WHEN s.error=1 THEN 1 ELSE 0 END) AS errors FROM mw_spans s JOIN mw_runs r ON r.id=s.run_id
                     WHERE r.agent_id=? AND r.started>? AND s.kind='tool' GROUP BY s.name ORDER BY COUNT(*) DESC LIMIT 12""", (row["id"], now - WEEK))
    out["tools"] = tools
    out["sandbox"] = None
    if row and has("mw_sbx"):
        s = q("SELECT id, status, exit_code, error, started, finished FROM mw_sbx WHERE agent_id=? ORDER BY id DESC LIMIT 1", (row["id"],), one=True)
        n = q("SELECT COUNT(*) AS n, SUM(CASE WHEN status IN ('error','timeout') THEN 1 ELSE 0 END) AS bad FROM mw_sbx WHERE agent_id=? AND started>?", (row["id"], now - WEEK), one=True)
        out["sandbox"] = {"last": dict(s) if s else None, "runs_7d": n["n"] or 0, "failed_7d": n["bad"] or 0}
    diag = {}
    bad = [r for r in runs if r["status"] in ("failed", "error", "lost")]
    if bad and has("io_diag"):
        ids = [r["id"] for r in bad]
        diag = {d["run_id"]: d for d in q(f"SELECT run_id, cls, recoverable, recovery FROM io_diag WHERE run_id IN ({_marks(ids)})", ids)}
    out["failures"] = [{"id": r["id"], "title": r["title"] or r["kind"], "error": _clip(r["error"] or "", 240), "started": r["started"], "cls": (diag.get(r["id"]) or {}).get("cls") or _class_of(r["error"]),
                        "recovery": (diag.get(r["id"]) or {}).get("recovery") or RECOVERY.get(_class_of(r["error"]), RECOVERY["task"])[1]} for r in bad[:8]]
    sc = [r["score"] for r in runs if r["score"] is not None]
    out["evaluation"] = {"scored": len(sc), "of": sum(1 for r in runs if r["status"] != "running"), "avg": round(sum(sc) / len(sc)) if sc else None,
                         "recent": [{"title": r["title"] or r["kind"], "score": r["score"], "started": r["started"]} for r in runs if r["score"] is not None][:6]}
    vers = []
    if row and has("au_versions"):
        vers += [{"what": f"Version {x['version']}" + (f", score {x['score']:g}" if x["score"] is not None else ""), "source": x["source"] or "Upgrade sprint", "by": x["by_user"], "ts": x["ts"]}
                 for x in q("SELECT version, source, score, by_user, ts FROM au_versions WHERE agent_id=? ORDER BY id DESC LIMIT 8", (row["id"],))]
    if has("ev_proposals"):
        vers += [{"what": x["title"], "source": f"Evolution Lab ({x['status']})", "by": x["decided_by"], "ts": x["promoted"] or x["updated"]}
                 for x in q("SELECT title, status, decided_by, promoted, updated FROM ev_proposals WHERE user_id=? AND target_key=? ORDER BY id DESC LIMIT 8", (uid, key))]
    out["versions"] = sorted(vers, key=lambda x: -(x["ts"] or 0))[:10]
    day = sum(r["tokens"] or 0 for r in runs if (r["started"] or 0) > now - DAY)
    lim = None
    if agent_core.get() is not None:
        lim = next((L for L in agent_core.get().limit_status(uid) if L["scope"] == "agent" and L["key"] == key), None)
    out["cost"] = {"tokens_24h": day, "tokens_7d": sum(r["tokens"] or 0 for r in wk), "usd_7d": round(sum(r["cost"] or 0 for r in wk), 2),
                   "limit": {"tokens": lim["tokens"], "spent": lim["spent"], "period": lim["period"]} if lim else None,
                   "team_left": comp["budget"]["left"] if comp else None}
    # the recommended next action, from the same decision engine
    recent_bad = [f for f in out["failures"] if (f["started"] or 0) > now - DAY]
    same = {}
    for f in recent_bad: same[f["cls"]] = same.get(f["cls"], 0) + 1
    if recent_bad and max(same.values()) >= 3:
        cls = max(same, key=same.get)
        nx = {"situation": "repeated", "label": SITUATIONS["repeated"][0],
              "next": ("Stop identical attempts. " + (RECOVERY.get(cls, RECOVERY["task"])[1] if cls not in OWN_FAULT else
                       "Inspect its model, instructions, skills, tools and knowledge; improve the agent or change its strategy, then test the candidate on held-out tasks before promoting it."))}
    elif recent_bad:
        sit, rec, _who = RECOVERY.get(recent_bad[0]["cls"], RECOVERY["task"])
        nx = {"situation": sit, "label": SITUATIONS[sit][0], "next": rec}
    elif out["task"] and out["task"]["state"] == "BLOCKED": nx = {"situation": "blocked", "label": SITUATIONS["blocked"][0], "next": "Answer its question on the team's board: it continues from there."}
    elif out["idle"]: nx = {"situation": "idle", "label": "Idle", "next": (comp["decision"]["next"] if comp else "No task assigned: give it one, or leave it idle.")}
    elif sc and out["evaluation"]["avg"] is not None and out["evaluation"]["avg"] < 50:
        nx = {"situation": "task_failure", "label": SITUATIONS["task_failure"][0], "next": "Its work scores low: diagnose it and run an upgrade against held-out tasks before changing it."}
    else: nx = {"situation": "progressing", "label": SITUATIONS["progressing"][0], "next": "Nothing to do: its work is moving."}
    out["next"] = nx
    return out


# ---------------------------------------------------------------- drill-down: one task's graph
def task_graph(ch, me, ref):
    """Mission → task → agent, model, tool calls, sandbox, files, runs, evaluator, result: the task's own neighbourhood, not the
    whole organization. ref: mw:<board task id> or ctl:<Control Hub task id>."""
    uid, q, has = me["id"], ch.db.q, ch._has
    m = re.fullmatch(r"(mw|ctl):(\d+)", ref or "")
    if not m: raise HTTPException(404, "There's no such task.")
    nodes, edges = [], []
    def node(id_, kind, label, state="", detail=""): nodes.append({"id": id_, "kind": kind, "label": _clip(label, 80), "state": state, "detail": _clip(detail, 300)}); return id_
    def edge(a, b, label=""): edges.append({"from": a, "to": b, "label": label})
    ctl, tid = None, int(m.group(2))
    if m.group(1) == "ctl":
        ctl = q("SELECT * FROM ctl_tasks WHERE id=? AND user_id=?", (tid, uid), one=True)
        if not ctl: raise HTTPException(404, "There's no such task.")
        bref = ctl.get("ref") or ""
        tid = int(bref.split(":")[1]) if bref.startswith("mw_task:") else None
    comps = ch._comps(uid)
    t = q("SELECT * FROM mw_tasks WHERE id=?", (tid,), one=True) if tid and has("mw_tasks") else None
    if t and t["comp_id"] not in comps: raise HTTPException(404, "There's no such task.")
    if not t and not ctl: raise HTTPException(404, "There's no such task.")
    mref = (ctl or {}).get("mission") or (f"comp:{t['comp_id']}" if t else None)
    if mref:
        w = comps.get(int(mref.split(":")[1])) if mref.startswith("comp:") else None
        node("mission", "mission", ch._label(w) if w else mref, "", "The objective this task serves")
    title = (t or ctl)["title"]
    if t:
        ok = bool(q("SELECT 1 FROM mw_runs WHERE task_id=? AND kind='review' AND status='done' LIMIT 1", (t["id"],), one=True)) or \
             bool(q("SELECT 1 FROM mw_events WHERE task_id=? AND kind='approve' LIMIT 1", (t["id"],), one=True)) if has("mw_runs") and has("mw_events") else False
        st = state_board(t, False, ok)
    else:
        from . import task_lifecycle as tl
        tv = ch._task_out(ctl, None)
        st = state_ctl(tl.stage(tv, ctl, tl._runs(ch, [ctl["id"]]).get(ctl["id"]))[0], tv["status"] == "done")
    node("task", "task", title, st, (t or {}).get("summary") or (ctl or {}).get("summary") or "")
    if mref: edge("mission", "task", "plans")
    result = None
    if t:
        ag = q("SELECT id, name, title FROM mw_agents WHERE id=?", (t["agent_id"],), one=True) if t.get("agent_id") else None
        if ag: node("agent", "agent", ag["name"], "", ag["title"]); edge("task", "agent", "assigned to")
        runs = q("SELECT id, kind, status, model, tokens, started, finished, error, agent_id FROM mw_runs WHERE task_id=? ORDER BY id DESC LIMIT 12", (t["id"],)) if has("mw_runs") else []
        ids = [r["id"] for r in runs]
        models = {}
        for r in runs:
            nid = node(f"run:{r['id']}", "run", f"{'Review' if r['kind'] == 'review' else 'Run'} #{r['id']}", r["status"], f"{r['tokens'] or 0:,} tokens" + (f" · {_clip(r['error'], 160)}" if r["error"] else ""))
            edge("task", nid, "attempt" if r["kind"] != "review" else "reviewed by")
            if r["model"]: models.setdefault(r["model"], []).append(nid)
        for mdl, rs in models.items():
            mid = node(f"model:{mdl}", "model", mdl, "", f"{_s(len(rs), 'run')}")
            for r in rs: edge(r, mid, "on")
        if ids and has("mw_spans"):
            tools = q(f"""SELECT name, COUNT(*) AS n, SUM(CASE WHEN error=1 THEN 1 ELSE 0 END) AS errors FROM mw_spans WHERE run_id IN ({_marks(ids)}) AND kind='tool'
                          GROUP BY name ORDER BY COUNT(*) DESC LIMIT 10""", ids)
            for x in tools:
                node(f"tool:{x['name']}", "tool", x["name"], "error" if x["errors"] else "", f"{_s(x['n'], 'call')}" + (f", {x['errors']} failed" if x["errors"] else ""))
                edge("agent" if ag else "task", f"tool:{x['name']}", "calls")
        if has("mw_sbx"):
            for s in q("SELECT id, status, exit_code, error, started FROM mw_sbx WHERE task_id=? ORDER BY id DESC LIMIT 5", (t["id"],)):
                node(f"sbx:{s['id']}", "sandbox", f"Sandbox #{s['id']}", s["status"], _clip(s["error"] or f"exit code {s['exit_code']}", 200)); edge("task", f"sbx:{s['id']}", "runs in")
        if has("mw_files") and runs:
            t0, t1 = min(r["started"] or 0 for r in runs), max((r["finished"] or time.time()) for r in runs)
            for f in q("SELECT path, size, updated FROM mw_files WHERE comp_id=? AND updated>=? AND updated<=? ORDER BY updated DESC LIMIT 8", (t["comp_id"], t0, t1 + 5)):
                node(f"file:{f['path']}", "file", f["path"], "", f"{f['size'] or 0:,} bytes"); edge("task", f"file:{f['path']}", "wrote")
        rv = q("SELECT name FROM mw_agents WHERE id=?", (t["reviewer"],), one=True) if t.get("reviewer") and "reviewer" in t else None
        rev_runs = [r for r in runs if r["kind"] == "review"]
        if rev_runs:
            ra = q("SELECT name, title FROM mw_agents WHERE id=?", (rev_runs[0]["agent_id"],), one=True) or rv
            node("evaluator", "evaluator", (ra or {}).get("name") or "Reviewer", rev_runs[0]["status"], "An independent review: not the task's author"); edge("task", "evaluator", "judged by")
        elif ok: node("evaluator", "evaluator", "You", "done", "Your approval"); edge("task", "evaluator", "judged by")
        else: node("evaluator", "evaluator", "No independent verdict yet", "missing", "Done is not verified until a reviewer or you decide"); edge("task", "evaluator", "needs")
        result = t.get("summary") or t.get("note")
    elif ctl:
        if ctl.get("agent_key"): node("agent", "agent", ctl["agent_key"], "", "Assigned agent"); edge("task", "agent", "assigned to")
        for r in (q("SELECT id, status, model, tokens, error FROM ac_runs WHERE ref=? ORDER BY id DESC LIMIT 8", (f"ctl:t{ctl['id']}",)) if has("ac_runs") else []):
            nid = node(f"run:{r['id']}", "run", f"Run #{r['id']}", r["status"], f"{r['tokens'] or 0:,} tokens" + (f" · {_clip(r['error'], 160)}" if r["error"] else "")); edge("task", nid, "attempt")
            if r["model"]:
                if not any(n["id"] == f"model:{r['model']}" for n in nodes): node(f"model:{r['model']}", "model", r["model"])
                edge(nid, f"model:{r['model']}", "on")
        vf = _j(ctl.get("verify"), None)
        node("evaluator", "evaluator", "Checks" if vf else "You", "done" if (vf or {}).get("ok") or ctl["status"] == "done" else "missing",
             (vf or {}).get("why") or ("You accepted its result" if ctl["status"] == "done" else "Waits for your acceptance")); edge("task", "evaluator", "judged by")
        result = ctl.get("summary")
    node("result", "result", STATE_LABEL[st], st, result or STATE_NOTE[st]); edge("evaluator" if any(n["id"] == "evaluator" for n in nodes) else "task", "result", "gives")
    return {"ref": ref, "title": title, "state": st, "nodes": nodes, "edges": edges}


# ---------------------------------------------------------------- routes (on the Control Hub's router)
def mount(r, ch, user):
    ensure_schema(ch.db)

    def _view(me, fresh=False):
        v = view(ch, me, fresh)
        return {k: x for k, x in v.items() if not k.startswith("_")}

    @r.get("/ops")
    def ops_(req: Request, fresh: bool = False): return _view(user(req), fresh)

    @r.get("/ops/verify-sample")
    def sample_(req: Request): return sample_view(ch, user(req))

    @r.post("/ops/verify-sample/{tid}")
    def sample_verdict_(tid: int, b: SampleVerdictIn, req: Request): return sample_verdict(ch, user(req), tid, b)

    @r.post("/ops/readiness/{ref}/refresh")
    def readiness_refresh_(ref: str, req: Request): return refresh_readiness(ch, user(req), ref[:40])

    @r.get("/ops/missions/{ref}")
    def mission_(ref: str, req: Request): return mission(ch, user(req), ref)

    @r.put("/ops/missions/{ref}/criteria")
    def criterion_(ref: str, b: CriterionIn, req: Request): return set_criterion(ch, user(req), ref, b)

    @r.delete("/ops/missions/{ref}/criteria/{key}")
    def drop_(ref: str, key: str, req: Request): return drop_criterion(ch, user(req), ref, key)

    @r.get("/ops/agents/{key}")
    def agent_(key: str, req: Request): return agent(ch, user(req), key)

    @r.get("/ops/tasks/{ref}/graph")
    def graph_(ref: str, req: Request): return task_graph(ch, user(req), ref)

    from . import mission_evidence  # competitors as evidence (seven steps, techniques) and knowledge visibility
    mission_evidence.mount(r, ch, user)


# ---------------------------------------------------------------- capability probes (G5-2 M2, Owner clarifications B and C)
# One probe per capability a task can declare (task_lifecycle.CAPABILITIES), plus the model sign-in AXoR checks for every
# team that runs on a Claude Code or Codex plan (D-015 D1). Each answers PASS, FAIL or UNKNOWN with its evidence and when.
# - B: usability, not configuration. A probe passes only on a live answer (the egress proxy's health, a real prompt on the
#   login, the sandbox's API) or on a successful use in the last PROBE_RECENT seconds. Something only configured is UNKNOWN.
# - C: UNKNOWN is never PASS for a mandatory requirement: the readiness gate (M3) treats it as not ready.
# Answers are cached per (team, capability) for PROBE_TTL; fresh=True asks again. A probe never starts work or spends more than
# the sign-in check's one tiny prompt.
PROBE_TTL = 600
CHECK_RETRY = 30  # an UNKNOWN that only means "AXoR's own check is under way" is asked again this soon, so the held task isn't kept
                  # for PROBE_TTL after the check has ended (a dispatcher pass re-checks held tasks; found in staging, 2026-11-13)
PROBE_RECENT = 7 * 86400
RUNNER_RAM_GB = 4  # the sandbox runner's memory limit (sandbox.Sandbox._pod: limits.memory 4Gi)
_probe_cache = {}


def _p(cap, state, evidence, how, value=None):
    return {"cap": cap, "value": value, "state": state, "evidence": evidence, "how": how, "checked": time.time()}


def probe(ch, comp, cap, value=None, fresh=False, cached_only=False):
    """The probe of one capability for a team (comp: its mw_comps row or None). Cached for PROBE_TTL unless fresh.
    cached_only (a page being read, Owner review 2026-11-11 §2B): never probes. It answers the cached result, marked stale past
    PROBE_TTL, or UNKNOWN "not checked yet" when there is none; dispatch preflight and the explicit Re-check probe for real."""
    key = ((comp or {}).get("id"), cap, value)
    hit = _probe_cache.get(key)
    if cached_only:
        if hit: return {**hit, "stale": time.time() - hit["checked"] >= PROBE_TTL}
        return {"cap": cap, "value": value, "state": "UNKNOWN", "how": "not checked", "checked": None, "stale": True,
                "evidence": "Not checked yet: the dispatcher checks it before it starts the work, or press Re-check."}
    if hit and not fresh and time.time() - hit["checked"] < min(PROBE_TTL, hit.get("retry_in") or PROBE_TTL): return hit
    try: out = _PROBES.get(cap, _unknown_cap)(ch, comp, value)
    except Exception as e:  # noqa: BLE001 - a probe that breaks is UNKNOWN, never PASS
        out = _p(cap, "UNKNOWN", f"The probe itself failed: {str(e)[:200]}", "error", value)
    out["cap"], out["value"] = cap, value
    _probe_cache[key] = out
    return out


def _unknown_cap(ch, comp, value):
    return _p("?", "UNKNOWN", "No probe for this capability.", "none", value)


def _sbx(ch):
    return getattr(getattr(ch, "w", None), "sbx", None)


def _runner(ch):
    return getattr(getattr(ch, "w", None), "runner", None)


def _docker(ch, comp, value):
    """G5-4 V4.2 (D-013 design §6): PASS only after a real job, never on configuration alone. FAIL while no runner is installed
    (as before V4.2); UNKNOWN while it is installed but hasn't completed a job on the current base disk in the last 7 days."""
    r = _runner(ch)
    ok, why = r.configured() if r else (False, "")
    if not ok:
        return _p("docker", "FAIL", "No Docker runner is connected for agents: sandbox runs have no Docker CLI and may not request KVM "
                  "(k8s/base/56-sandbox.yaml, gap G-29). " + (why or "The isolated VM runner (D-013) isn't installed on this server.") +
                  " Until then a person runs Docker work.", "design", value)
    ok, why = r.ready()
    if not ok: return _p("docker", "UNKNOWN", f"The VM runner is installed but can't take a job now: {why}", "kube", value)
    try:
        rows = ch.db.q("SELECT id, comp_id, finished, by_user FROM mw_sbx WHERE services=? AND status='done' AND exit_code=0 AND finished>? ORDER BY id DESC LIMIT 20",
                       (vmrunner.SERVICE, time.time() - vmrunner.VERIFY_DAYS * 86400))
    except Exception as e:  # noqa: BLE001 - no board on this server
        return _p("docker", "UNKNOWN", f"The runner's jobs couldn't be read ({str(e)[:100]}).", "records", value)
    for s in rows:
        d = vmrunner.stored(ch.db, s["comp_id"], s["id"])
        base = ((d or {}).get("environment") or {}).get("base_disk_sha256")
        if d and base and (not vmrunner.BASE_SHA or base == vmrunner.BASE_SHA):
            which = "AXoR's own check job" if s["by_user"] == NET_CHECK_USER else "VM runner job"
            return _p("docker", "PASS", f"{which} #{s['id']} finished cleanly {time.strftime('%Y-%m-%d %H:%M', time.gmtime(s['finished']))} UTC "
                      f"on base disk {base[:12]}: a VM started, its Docker daemon answered and the result was handed over. It shows nothing "
                      "about registries or the cluster's network policy.", "job", value)
    return _docker_unproven(ch, comp, value)


# AXoR's own Docker check job (D-035, Proposed; agreed with the runner's builder). Without it the first Docker task could never
# start: the probe above passes only on a finished job, only an agent's tool call starts a job, and a task that declares docker
# is held while the probe is UNKNOWN. Fixed in code, so nothing a team or an agent wrote goes into it: no image is pulled, no team
# file enters the VM (the path marker matches nothing), nothing comes back but the job's own record.
VM_CHECK_SPEC = {"kind": "run", "network": "none", "command": "docker version && docker info --format '{{.ServerVersion}}'",
                 "memory_mb": 1024, "cpus": 1, "timeout_s": 60, "images": [], "artifacts": [], "score_file": "", "secrets": []}
_vm_check = {"at": 0.0}  # when a check job was last started here: one at a time for the whole server (the probe's answer is server-wide)
VM_CHECK_WALL = 1200     # a check job still 'running' after this long isn't running any more (its spec: 60 s, plus the VM and the queue)
AWAIT_FOR = 900          # how long after AXoR starts a check for a team the periodic pass keeps re-checking that team's held tasks
AWAIT_STARTS = 3         # at most this many checks started for one team per AWAIT_WINDOW keep the periodic pass going
AWAIT_WINDOW = 3600
_awaiting = {}           # team id -> [until, [when each check was started]]: in this process only; lost on a restart, as a run is


def _await(comp_id):
    """AXoR has just started a check of its own for this team: its readiness-held tasks are looked at again by the periodic pass
    until AWAIT_FOR from now. Bounded: after AWAIT_STARTS checks in AWAIT_WINDOW the time isn't extended any more, so a need
    that keeps failing (or a runner that stays busy) leaves the board to an event or a person, as every other hold does."""
    now = time.time()
    until, starts = _awaiting.get(comp_id) or (0, [])
    starts = [t for t in starts if now - t < AWAIT_WINDOW] + [now]
    _awaiting[comp_id] = [now + AWAIT_FOR if len(starts) <= AWAIT_STARTS else until, starts]
    if len(_awaiting) > 5000: _awaiting.clear()


def awaiting():
    """The teams whose held tasks wait on a check AXoR itself started and whose time isn't up (mining_autoloop.tick reads it)."""
    now = time.time()
    return {k for k, (until, _) in list(_awaiting.items()) if until > now}


def _start_vm_check(ch, comp):
    """Starts AXoR's one Docker check job, in the background, through the same Work._docker_job an agent's call goes through (so its
    row and kept result are what the probe reads, and a stop of the team's mission ends it like any job). True: started. False:
    one was started lately (here or, by its row, anywhere on the server) or is still running. None: it can't be started from
    here (checks are off, or there is no team board to file its row under). It waits its turn for a VM like any job."""
    w = getattr(ch, "w", None)
    if not NET_CHECK or not comp or not w or not hasattr(w, "_docker_job"): return None
    now = time.time()
    if now - _vm_check["at"] < NET_CHECK_EVERY: return False
    if ch.db.q("SELECT id FROM mw_sbx WHERE by_user=? AND services=? AND ((status='running' AND started>?) OR started>?) LIMIT 1",
               (NET_CHECK_USER, vmrunner.SERVICE, now - VM_CHECK_WALL, now - NET_CHECK_EVERY), one=True):
        return False   # a row left 'running' by a process that died counts only for the job's own longest time (a restart closes it anyway)
    _vm_check["at"] = now; _await(comp["id"])
    try: c = w.m._campaign(comp.get("campaign_id")) or {}
    except Exception:  # noqa: BLE001 - the label only
        c = {}

    def go():
        try: w._docker_job(comp, {"netuid": c.get("netuid", "?")}, {**VM_CHECK_SPEC, "paths": [NET_CHECK_NO_FILES]}, user=NET_CHECK_USER)
        except Exception as e:  # noqa: BLE001 - the job's row says what happened; a refusal before the row is the next probe's "no evidence"
            logging.getLogger("mission_ops").info("the Docker check job didn't run: %s", e)
    threading.Thread(target=go, daemon=True, name="readiness-vm-check").start()
    return True


def _docker_unproven(ch, comp, value):
    """The runner can take a job, but no job on the current base disk proves it. A check job of AXoR's own that ran in a VM and
    did not finish cleanly is the answer for NET_FAIL_HOLD (with its reason; then it is measured again). One that never got a VM
    (the runner was busy, the pod never started, the server restarted) says nothing about the runner: UNKNOWN with its reason, and
    a new one after NET_CHECK_EVERY. Otherwise one is started and the answer is UNKNOWN until it ends. Only a live probe reaches
    this (a dispatch or a person's Re-check): a page being read never starts a job."""
    r = ch.db.q("SELECT id, status, exit_code, error, finished, pod FROM mw_sbx WHERE by_user=? AND services=? AND status IN ('failed','timeout','error') ORDER BY id DESC LIMIT 1",
                (NET_CHECK_USER, vmrunner.SERVICE), one=True)
    why = ((r["error"] or "").strip()[:200] or (f"exit {r['exit_code']}" if r["exit_code"] is not None else r["status"])) if r else ""
    ran = bool(r) and (r["status"] in ("failed", "timeout") or (bool(r["pod"]) and not (r["error"] or "").startswith("Stopped by a server restart")))
    fresh = bool(r) and time.time() - (r["finished"] or 0) < NET_FAIL_HOLD
    if ran and fresh:
        return _p("docker", "FAIL", f"AXoR's own check job #{r['id']} did not finish cleanly ({r['status']}: {why}), so the VM runner isn't shown to "
                  f"work on this base disk. It is tried again {NET_FAIL_HOLD // 60} minutes after it ended.", "job", value)
    started = _start_vm_check(ch, comp)
    last = f" AXoR's last check job (#{r['id']}) couldn't get a VM: {why}." if r and fresh and not ran else ""
    p = _p("docker", "UNKNOWN", "The VM runner is installed, but no job has finished cleanly on the current base disk in the last "
           f"{vmrunner.VERIFY_DAYS} days.{last} " + ("AXoR has started a small check job of its own to find out: check again in a few minutes." if started
                                                     else "AXoR's own check job is running or was started in the last few minutes: check again shortly." if started is False
                                                     else "It passes only after a real job (AXoR's own check job can't be started from here)."), "records", value)
    if started is not None: p["retry_in"] = CHECK_RETRY
    return p


def _registry(ch, comp, value):
    return _p("registry", "FAIL", "No registry push path for agents: a push needs a person's approval and a credential store, and neither is "
              "built (D-013 design §5). Pushes stay the Owner's action.", "design", value)


def _vm(ch, comp, value):
    """KVM for agents' jobs. With the VM runner installed (G5-4 V4.2) it is the runner's quota that counts: PASS when it allows a
    device. Without it, as before: the sandbox's own quota, which is never a PASS because no sandbox run starts a VM."""
    r = _runner(ch)
    if r and r.configured()[0]:
        try: kvm = r.quota()
        except Exception as e:  # noqa: BLE001 - the web pod's role may not read the quota, or the namespace isn't there
            return _p("vm", "UNKNOWN", f"The VM runner's quota couldn't be read ({str(e)[:120]}).", "kube", value)
        if not kvm: return _p("vm", "FAIL", "The VM runner's quota allows no KVM device (requests.axor.dev/kvm: 0).", "kube", value)
        return _p("vm", "PASS", f"The VM runner's quota allows {kvm} KVM device{'s' if kvm != 1 else ''}: one per job.", "kube", value)
    s = _sbx(ch)
    kube = getattr(s, "kube", None)
    if not kube or not getattr(kube, "enabled", False): return _p("vm", "UNKNOWN", "Not on a cluster: nothing to ask.", "none", value)
    try:
        q = kube.get("/api/v1/namespaces/axor-sandbox/resourcequotas/sandbox") or {}
        kvm = ((q.get("spec") or {}).get("hard") or {}).get("requests.axor.dev/kvm")
    except Exception as e:  # noqa: BLE001 - the web pod's role may not read quotas
        return _p("vm", "UNKNOWN", f"The sandbox quota couldn't be read ({str(e)[:120]}).", "kube", value)
    if str(kvm) == "0": return _p("vm", "FAIL", "The sandbox quota allows no KVM device (requests.axor.dev/kvm: 0), and no VM runner is installed.", "kube", value)
    return _p("vm", "UNKNOWN", f"The sandbox quota allows KVM ({kvm}), but no sandbox run starts a VM and no VM runner is installed.", "kube", value)


def _nodes(kube):
    """The cluster's nodes, or raise: unlike Kube.items (which answers [] when reading is refused), a refusal here is an error,
    so a probe that can't read nodes says UNKNOWN instead of "none" (found in G5-2 staging with a least-privilege account)."""
    return (kube.call("GET", "/api/v1/nodes") or {}).get("items", [])


# ---- reach measured from inside the sandbox (2026-11-13, directive "Mission Execution Recovery" Phase 1/2). An answer from the egress
# proxy to AXoR's own server shows the proxy is up, not that a run can reach anything through it. So `internet` and `git` pass
# only on what a sandbox run of this team did: a finished run that reached a host (its `net` record), or checked a repository
# out (its `src` record). When there is none, AXoR starts one short check run itself (a fixed command, no inference, its own
# mw_sbx row by NET_CHECK_USER) and answers UNKNOWN until that run has ended; the dispatcher's next pass reads the result.
NET_CHECK = __import__("os").getenv("READINESS_NET_CHECK", "1") != "0"
from .sandbox import READINESS_USER as NET_CHECK_USER  # noqa: E402  one name for the check runs' rows, shared with the register's feed
NET_CHECK_EVERY = 600   # at most one check run per team and target in this time
NET_FAIL_HOLD = 900     # a check run that failed is the answer for this long; then the next probe measures again (a blip mustn't hold a team for days)
NET_CHECK_HOSTS = ("github.com", "pypi.org")
NET_CHECK_CMD = ('echo "@@AXOR-NETCHECK internet"; ok=1; for u in ' + " ".join(f"https://{h}" for h in NET_CHECK_HOSTS) +
                 '; do c=$(curl -sS -o /dev/null -m 20 -w "%{http_code} %{time_total}s" "$u" 2>&1) && { echo "$u $c"; ok=0; } || echo "$u FAILED $c"; done; exit $ok')
NET_CHECK_NO_FILES = ".axor-netcheck"  # a path prefix no team file has: the check run carries none of the team's files
_net_checks = {}  # (team, target) -> when its check run was last started here


def _git_check_cmd(repo): return f'echo "@@AXOR-NETCHECK git {repo}"; git ls-remote https://{repo} HEAD'


def _start_net_check(ch, comp, command):
    """Starts one check run in the team's sandbox, in the background. False when one for this command was started lately (here or,
    by its row, anywhere), when checks are off, or when the team's board isn't reachable from here. Tests replace this."""
    w = getattr(ch, "w", None)
    if not NET_CHECK or not w or not hasattr(w, "_sandbox"): return False
    k, now = (comp["id"], command), time.time()
    if now - _net_checks.get(k, 0) < NET_CHECK_EVERY: return False
    if ch.db.q("SELECT id FROM mw_sbx WHERE comp_id=? AND by_user=? AND command=? AND started>? LIMIT 1", (comp["id"], NET_CHECK_USER, command, now - NET_CHECK_EVERY), one=True):
        return False
    _net_checks[k] = now; _await(comp["id"])
    try: c = w.m._campaign(comp.get("campaign_id")) or {}
    except Exception:  # noqa: BLE001 - the label only
        c = {}

    def go():
        try: w._sandbox(comp, {"netuid": c.get("netuid", "?")}, command, [], 90, 0.05, paths=[NET_CHECK_NO_FILES], user=NET_CHECK_USER)
        except Exception as e:  # noqa: BLE001 - the run's row says what happened; a refusal before the row is the next probe's "no evidence"
            logging.getLogger("mission_ops").info("readiness check run for team %s didn't run: %s", comp["id"], e)
    threading.Thread(target=go, daemon=True, name="readiness-net-check").start()
    return True


def _sbx_rows(ch, comp, where, args=()):
    if not ch._has("mw_sbx"): return []
    cols = {c["name"] for c in ch.db.q("PRAGMA table_info(mw_sbx)")}
    if "net" not in cols: return []
    sel = "id, by_user, command, status, exit_code, finished, net, " + ("src" if "src" in cols else "NULL AS src") + ", substr(output, 1, 4000) AS output"
    return ch.db.q(f"SELECT {sel} FROM mw_sbx WHERE comp_id=? AND finished>? AND {where} ORDER BY id DESC LIMIT 60", (comp["id"], time.time() - PROBE_RECENT, *args))


def _when(ts): return time.strftime("%m-%d %H:%M", time.localtime(ts or 0))


def _last_check(ch, comp, command):
    """AXoR's newest check run of this command that measured something: it ran in the sandbox to its end (done or failed). A run
    that never got there (error: sandbox busy, a restart, the cluster refused it; timeout; cancelled) is no answer. A failed one
    counts for NET_FAIL_HOLD only: (row, fresh) where fresh says a failure is still young enough to stand."""
    r = next(iter(_sbx_rows(ch, comp, "by_user=? AND command=? AND status IN ('done','failed')", (NET_CHECK_USER, command))), None)
    if not r: return None, False
    return r, r["status"] == "done" or time.time() - (r["finished"] or 0) < NET_FAIL_HOLD


def _reached(ch, comp):
    """The team's newest finished sandbox run whose network record shows a host reached: (row, hosts) or (None, [])."""
    for r in _sbx_rows(ch, comp, "net IS NOT NULL"):
        hosts = list((_j(r["net"], {}) or {}).get("hosts") or {})
        if hosts: return r, hosts
    return None, []


def _proxy_state(ch, comp, cap, value):
    """None when the team's sandbox internet is switched on and its proxy is healthy now; else the probe answer to give."""
    if not comp: return _p(cap, "UNKNOWN", "No team to check.", "none", value)
    if not comp.get("internet"): return _p(cap, "FAIL", "This team's sandbox internet is off (an administrator's switch on the team).", "records", value)
    s = _sbx(ch)
    if not s or not getattr(s, "egress", None): return _p(cap, "UNKNOWN", "No sandbox on this server.", "none", value)
    st = s.egress.status(fresh=True)
    if st.get("ready"): return None
    if "gVisor" in (st.get("why") or "") and getattr(s, "kube", None):  # Egress reads "can't read nodes" as "not installed": check it
        try: _nodes(s.kube)
        except Exception as e:  # noqa: BLE001 - refused or unreachable: unknown, not absent
            return _p(cap, "UNKNOWN", f"The egress proxy answered, but gVisor's state can't be confirmed: reading nodes was refused ({str(e)[:100]}).", "live", value)
    return _p(cap, "FAIL", st.get("why") or "The egress proxy isn't ready.", "live", value)


def _internet(ch, comp, value):
    bad = _proxy_state(ch, comp, "internet", value)
    if bad: return bad
    r, hosts = _reached(ch, comp)
    if r:
        return _p("internet", "PASS", f"The egress proxy answers now, and sandbox run #{r['id']} of this team reached {', '.join(hosts[:3])}"
                  f"{' and ' + str(len(hosts) - 3) + ' more' if len(hosts) > 3 else ''} through it at {_when(r['finished'])} (measured inside the sandbox).", "recent", value)
    last, fresh = _last_check(ch, comp, NET_CHECK_CMD)
    if last and last["status"] == "failed" and fresh:  # AXoR's own check ran inside the sandbox and reached nothing: a measured failure, for a while
        from . import sandbox as _sb
        tail = " / ".join(x for x in (last["output"] or "").splitlines() if x.startswith("https://"))[:200]
        cls = _sb.reach_class(last["exit_code"], tail or last["output"], last["status"])
        p = _p("internet", "FAIL", f"The egress proxy answers AXoR's server, but check run #{last['id']} inside the sandbox reached no host at "
               f"{_when(last['finished'])}{': ' + tail if tail else ''}. {_sb.REACH[cls]}", "recent", value)
        p["reach"] = cls
        return p
    started = _start_net_check(ch, comp, NET_CHECK_CMD)
    waiting = NET_CHECK and hasattr(getattr(ch, "w", None), "_sandbox")
    p = _p("internet", "UNKNOWN", "The egress proxy answers AXoR's server, but no sandbox run of this team has reached a host in "
           f"{PROBE_RECENT // 86400} days: that isn't proof for a run. " + ("A check run inside the sandbox was started now; the next check reads its result."
           if started else "A check run inside the sandbox is under way or was started lately; the next check reads its result." if waiting
           else "Run one sandbox command that reaches the internet to prove it."), "live", value)
    if waiting: p["retry_in"] = CHECK_RETRY
    return p


def _git(ch, comp, value):
    from . import task_lifecycle as tl
    repo = tl.git_repo(value)
    if not repo: return _p("git", "FAIL", f"“{value or ''}” doesn't name a repository: use git:<host>/<owner>/<repo>.", "design", value)
    bad = _proxy_state(ch, comp, "git", value)
    if bad: return bad
    for r in _sbx_rows(ch, comp, "src IS NOT NULL"):  # a run that checked it out: the strongest evidence, with the commit it got
        for x in _j(r["src"], []) or []:
            if not isinstance(x, dict) or x.get("basis") == "declared": continue  # a Docker job's source is what its submitter said (V4.2), not a checkout the runner read
            u = re.sub(r"\.git$", "", re.sub(r"^https?://(?:www\.)?", "", str(x.get("url") or "")).strip("/"))
            if u.lower() == repo.lower():
                p = _p("git", "PASS", f"Sandbox run #{r['id']} of this team checked {repo} out at commit {str(x.get('commit'))[:12]} at {_when(r['finished'])}.", "recent", value)
                p["reach"] = "ok"
                return p
    cmd = _git_check_cmd(repo)
    last, fresh = _last_check(ch, comp, cmd)
    m = last and re.search(r"^([0-9a-f]{40,64})\s+HEAD\s*$", last["output"] or "", re.M)
    if last and last["status"] == "done" and m:
        p = _p("git", "PASS", f"Check run #{last['id']} inside the sandbox read {repo} (HEAD {m.group(1)[:12]}) at {_when(last['finished'])}.", "recent", value)
        p["reach"] = "ok"
        return p
    if last and last["status"] == "failed" and fresh:
        # what failed, in git's own words and as one class (sandbox.reach_class): a repository that asks for a login is not a
        # broken git, a refused host is not a network fault, a missing program is not either (consolidated directive C1)
        from . import sandbox as _sb
        out = " ".join(x for x in (last["output"] or "").splitlines() if x and not x.startswith("@@"))[-220:]
        cls = _sb.reach_class(last["exit_code"], last["output"], last["status"])
        said = {"private": f"{repo} asked for a login: it is private or misnamed, and sandbox runs carry no repository credentials. Git and the network work",
                "credentials": f"{repo}'s server rejected the request's credentials",
                "policy": f"AXoR's egress proxy refused the repository's host (not a public address, not an allowed port, or not on the run's list)",
                "no_internet": "the run had no internet (its proxy token wasn't accepted)",
                "no_executable": "git isn't in the sandbox image, so nothing was tried on the network",
                "dns": f"the repository's host name didn't resolve", "connection": "the connection to the repository's host failed or was cut",
                "timeout": "git ls-remote ran past the check's time limit"}.get(cls, "git ls-remote failed for a reason of its own")
        p = _p("git", "FAIL", f"Check run #{last['id']} inside the sandbox couldn't read {repo} at {_when(last['finished'])}: {said}. "
               f"Git said: {out or last['status']}.", "recent", value)
        p["reach"] = cls
        return p
    started = _start_net_check(ch, comp, cmd)
    waiting = NET_CHECK and hasattr(getattr(ch, "w", None), "_sandbox")
    p = _p("git", "UNKNOWN", f"No sandbox run of this team has read {repo} in {PROBE_RECENT // 86400} days. " + (
           "A check run (git ls-remote inside the sandbox) was started now; the next check reads its result." if started
           else "A check run is under way or was started lately; the next check reads its result." if waiting
           else "Run git ls-remote on it in the sandbox to prove it."), "live", value)
    if waiting: p["retry_in"] = CHECK_RETRY
    return p


def _service(name):
    def run(ch, comp, value):
        s = _sbx(ch)
        if not s: return _p(name, "UNKNOWN", "No sandbox on this server.", "none", value)
        ok, why = s.ready()
        if not ok: return _p(name, "FAIL", why, "live", value)
        r = ch.db.q("""SELECT id, finished FROM mw_sbx WHERE status='done' AND services LIKE ? AND finished>? ORDER BY id DESC LIMIT 1""",
                    (f"%{name}%", time.time() - PROBE_RECENT), one=True) if ch._has("mw_sbx") else None
        if r: return _p(name, "PASS", f"Sandbox up now; sandbox run #{r['id']} used {name} successfully at {time.strftime('%m-%d %H:%M', time.localtime(r['finished']))}.", "recent", value)
        return _p(name, "UNKNOWN", f"Sandbox up now, but no run has used {name} successfully in {PROBE_RECENT // 86400} days.", "live", value)
    return run


def _gpu(ch, comp, value):
    s = _sbx(ch)
    kube = getattr(s, "kube", None)
    if not kube or not getattr(kube, "enabled", False): return _p("gpu", "UNKNOWN", "Not on a cluster.", "none", value)
    try: nodes = _nodes(kube)
    except Exception as e:  # noqa: BLE001 - refused or unreachable: unknown, never "no GPU"
        return _p("gpu", "UNKNOWN", f"Nodes couldn't be read ({str(e)[:120]}).", "kube", value)
    n = sum(int(v or 0) for nd in nodes for k, v in ((nd.get("status") or {}).get("allocatable") or {}).items() if k.endswith("/gpu"))
    if not n: return _p("gpu", "FAIL", "No node offers a GPU.", "kube", value)
    return _p("gpu", "UNKNOWN", f"{n} GPU(s) on the cluster, but sandbox runs don't request GPUs.", "kube", value)


def _ram_sizes():
    """(what a run gets by default, the most any sandbox size gives, that size's name), in GB. sandbox.SIZES (the Agent Execution
    Fabric's S / M / L, where it exists) is {name: (cpu, "<n>Gi", slots)} with M the default; without it every run gets RUNNER_RAM_GB."""
    from . import sandbox as _sb
    sizes = getattr(_sb, "SIZES", None) or {}
    gb = {}
    for name, spec in sizes.items():
        m = re.fullmatch(r"(\d+)Gi", str((spec[1] if isinstance(spec, (tuple, list)) and len(spec) > 1 else "") or ""))
        if m: gb[name] = int(m.group(1))
    if not gb: return RUNNER_RAM_GB, RUNNER_RAM_GB, None
    top = max(gb, key=gb.get)
    return gb.get("M", RUNNER_RAM_GB), gb[top], top


def _ram_planned(ch, comp, gb):
    """What the execution planner would give a run of this team whose task declares ram:<gb>, in GB: None when there is no
    planner here (exec_env, the Agent Execution Fabric's) or it can't be read, 0 when this team's runs aren't planned.
    The switch test is exec_env.begin's own (exec_env.planned; the same line here only where that function isn't yet).
    A mission's own policy also plans its runs, but a probe is per team and can't tell which mission a task is in, so it doesn't
    count here. The size comes from the planner's own pure rule (exec_env.plan), never from a copy of it."""
    try:
        from . import exec_env
        cfg = exec_env.settings(ch.db, comp["id"])
        planned = getattr(exec_env, "planned", None) or (lambda c: bool(c and (c.get("plan") or c.get("workspace") or (c.get("egress") or {}).get("mode"))))
        if not planned(cfg): return 0
        return int(exec_env.plan([{"cap": "ram", "value": str(gb), "source": "declared"}], cfg, False)["memory_mb"]) // 1024
    except Exception:  # noqa: BLE001 - no planner on this branch, no database, no team: nothing is shown to ask for a size
        return None


def _ram_mission_policies(ch, comp):
    """Whether any mission of this team has its own execution policy (its runs are then planned though the team's aren't)."""
    try:
        from . import exec_env
        return bool(exec_env.mission_policies(ch.db, comp["id"]))
    except Exception:  # noqa: BLE001
        return False


def _ram(ch, comp, value):
    try: gb = int(value or 0)
    except ValueError: return _p("ram", "FAIL", f"“{value}” isn't a size in GB.", "design", value)
    default, most, top = _ram_sizes()
    if gb <= default: return _p("ram", "PASS", f"Sandbox runs get {default} GB (the runner's memory limit).", "design", value)
    if gb > most: return _p("ram", "FAIL", f"Sandbox runs get at most {most} GB; {gb} GB needs another environment.", "design", value)
    got = _ram_planned(ch, comp, gb)   # a larger size exists; a run gets it only when the planner asks for it
    if got is None:
        return _p("ram", "UNKNOWN", f"A larger sandbox size exists ({top}, {most} GB), but a run gets {default} GB unless that size is asked for it, "
                  f"and nothing asks for a size here: {gb} GB isn't available to this task today.", "design", value)
    if got >= gb:
        return _p("ram", "PASS", f"This team's runs are planned: a run of a task that declares ram:{gb} is given the {got} GB size. "
                  "A rule of the planner, not a measurement of a run.", "design", value)
    if _ram_mission_policies(ch, comp):  # true for a task in such a mission, but a probe is per team and can't tell which mission a task is in
        return _p("ram", "UNKNOWN", f"A larger sandbox size exists ({top}, {most} GB). This team's runs aren't planned as a whole (its execution "
                  f"switches are off); only runs of a mission with its own execution policy are, and this check can't tell which mission a task "
                  f"is in: {gb} GB isn't shown to be available to this task.", "design", value)
    return _p("ram", "UNKNOWN", f"A larger sandbox size exists ({top}, {most} GB), but this team's runs aren't planned (its execution switches are "
              f"off), so a run gets {default} GB: {gb} GB isn't available to this task today.", "design", value)


def _credential(ch, comp, value):
    team = (comp or {}).get("id")
    fp = credential_fingerprint(value, team, f"comp:{team}" if team is not None else None)   # the text only: a task's own mission is read when it is verified
    where = ("looked for in Vault, which can't be read now" if fp == CRED_UNREADABLE else f"held in Vault for this team ({fp})" if fp.startswith("vault:")
             else f"set on this server (fingerprint {fp})" if fp != "absent" else "not held by this server")
    return _p("credential", "UNKNOWN", f"{value or 'The credential'} is {where}; its presence doesn't show it works (Owner clarification B): "
              "verify it and record the verification on its readiness item. A changed value voids the verification.", "none", value)


def _approval(ch, comp, value):
    return _p("approval", "UNKNOWN", "The external action needs a person's approval; none is recorded for this task.", "records", value)


def _postgres(ch, comp, value): return _service("postgres")(ch, comp, value)
def _clickhouse(ch, comp, value): return _service("clickhouse")(ch, comp, value)


def _auth(ch, comp, value):
    """The team's model sign-in (D-015 D1): one tiny real prompt per plan login its active agents run on."""
    from . import cli_accounts, codex_cli, llm
    w = getattr(ch, "w", None)
    if not comp or not w: return _p("auth", "UNKNOWN", "No team to check.", "none", value)
    try:
        c = w.m._campaign(comp["campaign_id"])
        providers = {(w._model(c, a) or "").partition(":")[0] for a in w._agents(comp["id"]) if a.get("active", 1)}
    except Exception as e:  # noqa: BLE001
        return _p("auth", "UNKNOWN", f"The team's models couldn't be read ({str(e)[:120]}).", "records", value)
    owner = c.get("user_id") if c else None
    seen = []
    for p in sorted(x for x in providers if x in ("terminal", "codex")):
        try: acct = cli_accounts.pick(p, owner) if owner else cli_accounts.peek(p, None)
        except llm.LLMError as e:  # this owner may run on no login of this CLI (no borrowing): the run would be refused the same way
            return _p("auth", "FAIL", f"{'Claude Code' if p == 'terminal' else 'Codex'}: {str(e)[:240]}", "live", value)
        try:
            (llm.cli_check if p == "terminal" else codex_cli.check)(acct)
            seen.append(f"{'Claude Code' if p == 'terminal' else 'Codex'} answered a real prompt")
        except llm.QuotaError:
            seen.append(f"{'Claude Code' if p == 'terminal' else 'Codex'} is signed in (its plan's usage limit is reached)")
        except llm.LLMError as e:
            return _p("auth", "FAIL", f"{'Claude Code' if p == 'terminal' else 'Codex'}: {str(e)[:240]}", "live", value)
    if seen: return _p("auth", "PASS", "; ".join(seen) + ".", "live", value)
    return _p("auth", "UNKNOWN", "The team runs on API keys: there is no sign-in to lapse, and a key is checked on its first use.", "none", value)


LIVE_WEB_TIMEOUT = 8  # s: the live-data web check's own read (D-024 amendment 2026-11-12); web_read itself allows 20


def _live_data(ch, comp, value):
    """D-024: live data AXoR reads with its own server tools, never through sandbox internet. Every result rests on evidence:
    web[/host]: a live read now, through the same server-side fetch web_read uses (its public-address guard included): the team's
      saved page for that host, else the host's home page. PASS: a page with content. FAIL: the source is wrong or gives nothing
      (an address that isn't public, a page web_read can't read, a 4xx answer other than 408/429, no content). UNKNOWN: AXoR can't
      tell (a timeout, DNS or connection failure, which may be on AXoR's side, a 408, 429 or 5xx answer; no host and no saved page).
      A past fetch is reported, never the gate (Milestone 2, 2026-11-12: "the actual retrieval path rather than a previously fetched
      result").
    chain: the subnet's latest chain snapshot (mh_samples, the team's own competition), never a brief: fresh PASS, stale FAIL, none
      UNKNOWN; when the collector's latest read of the chain failed and no fresh snapshot exists: UNKNOWN (a retrieval failure: whether
      the chain moved can't be told). A fresh snapshot passes even after a later failed read: the data in hand is within the window."""
    from .task_lifecycle import live_spec
    sp = live_spec(value)
    if not sp: return _p("live_data", "FAIL", f"“{value}” isn't a live-data source (web, web/<host>, chain, chain/<subnet> or chain/query).", "records", value)
    if not comp: return _p("live_data", "UNKNOWN", "No team to check.", "none", value)
    now, win = time.time(), sp["fresh_h"] * 3600
    age = lambda ts: f"{int((now - ts) // 3600)} h {int((now - ts) % 3600 // 60)} min ago"
    if sp["kind"] == "chain" and sp.get("target") == "query":
        # Milestone 4: chain storage beyond the snapshots (Uids, Keys, Owner, …: task 2732's kind of query). No AXoR tool reads it (the
        # read-only chain_query tool is a design awaiting the Owner, D-026), so snapshot freshness can't stand in for it: FAIL, never PASS
        return _p("live_data", "FAIL", "This work queries chain storage beyond AXoR's snapshots (Uids, Keys, owners…), and no AXoR tool reads it: the "
                  "read-only chain-query tool is designed but not approved (D-026). Fresh snapshots don't prove the query can run.", "records", value)
    if sp["kind"] == "chain":
        if not ch._has("mh_samples") or not ch._has("mh_campaigns") or not comp.get("campaign_id"):
            return _p("live_data", "UNKNOWN", "No chain snapshots on this server for the team's subnet.", "none", value)
        c = ch.db.q("SELECT * FROM mh_campaigns WHERE id=?", (comp["campaign_id"],), one=True) or {}
        explicit = (sp["target"] or "").isdigit()
        net = int(sp["target"]) if explicit else c.get("netuid")
        if net is None: return _p("live_data", "UNKNOWN", "The team's subnet isn't known.", "none", value)
        # the team's own competition on a subnet that runs several (mech): another competition's snapshot isn't this team's data
        mech = None if explicit or not hasattr(ch, "_cols") or "mech" not in ch._cols("mh_samples") else c.get("mech")
        b = ch.db.q("SELECT ts, block FROM mh_samples WHERE netuid=?" + (" AND mech=?" if mech is not None else "") + " ORDER BY ts DESC LIMIT 1",
                    (net,) + ((mech,) if mech is not None else ()), one=True)
        st = ch.db.q("SELECT status, note, last_run FROM mh_agent_state WHERE campaign_id=? AND agent='scout'", (comp["campaign_id"],), one=True) \
            if ch._has("mh_agent_state") else None
        failed = bool(st and st.get("status") == "error" and (st.get("last_run") or 0) >= ((b or {}).get("ts") or 0))
        why = f"the collector's latest read of the chain failed{' ' + age(st['last_run']) if failed and st.get('last_run') else ''} ({_clip((st or {}).get('note'), 160)})"
        if not b or not b["ts"]:
            return _p("live_data", "UNKNOWN", f"No chain snapshot of SN{net} yet" + (f": {why}." if failed else "."), "records", value)
        if now - b["ts"] > win:
            if failed:
                return _p("live_data", "UNKNOWN", f"The latest chain snapshot of SN{net} (block {b['block']}) is {age(b['ts'])}, older than {sp['fresh_h']} h, and {why}: "
                          "a retrieval failure, so whether the chain moved can't be told.", "records", value)
            return _p("live_data", "FAIL", f"The latest chain snapshot of SN{net} (block {b['block']}) is {age(b['ts'])}: older than {sp['fresh_h']} h.", "records", value)
        return _p("live_data", "PASS", f"Chain snapshot of SN{net} at block {b['block']}, {age(b['ts'])} (within {sp['fresh_h']} h), read by AXoR, not the sandbox"
                  + (f"; since then {why}." if failed else "."), "records", value)
    from . import mining_web
    rows = ch.db.q("SELECT url, last_at, last_status FROM mw_web WHERE comp_id=? AND on_=1", (comp["id"],)) if ch._has("mw_web") else []
    if sp["target"]:
        host = sp["target"].lower()
        rows = [r for r in rows if re.search(r"https?://(?:www\.)?" + re.escape(host) + r"(?:[:/]|$)", r["url"] or "", re.I)]
    where = sp["target"] or "the web"
    last = max(rows, key=lambda r: r["last_at"] or 0) if rows else None
    url = last["url"] if last else f"https://{sp['target']}/" if sp["target"] else None
    if not url:
        return _p("live_data", "UNKNOWN", "No host declared and no saved page: nothing to read. Declare live_data:web/<host>.", "none", value)
    before = (f"; its last saved fetch {age(last['last_at'])} was {last['last_status'] or 'ok'}" if last and last.get("last_at") else "")
    try: page = mining_web.fetch(url, timeout=LIVE_WEB_TIMEOUT)
    except mining_web.WebError as e:
        k, code = getattr(e, "kind", None), getattr(e, "code", None) or 0
        if k in ("timeout", "network") or (k == "http" and (code in (408, 429) or code >= 500)):
            return _p("live_data", "UNKNOWN", f"AXoR's server-side read of {url} didn't answer conclusively: {e}{before}.", "live", value)
        return _p("live_data", "FAIL", f"AXoR's server-side read of {url} failed: {e}{before}.", "live", value)
    n = len((page.get("text") or "").strip())
    if not n: return _p("live_data", "FAIL", f"{url} answered with no content: the data isn't there{before}.", "live", value)
    return _p("live_data", "PASS", f"AXoR read {url} just now, server-side ({page.get('seconds')} s, {n:,} characters){before}.", "live", value)


_PROBES = {"docker": _docker, "registry": _registry, "vm": _vm, "internet": _internet, "git": _git, "postgres": _postgres, "clickhouse": _clickhouse,
           "gpu": _gpu, "ram": _ram, "credential": _credential, "approval": _approval, "auth": _auth, "live_data": _live_data}


# ---------------------------------------------------------------- readiness gate (G5-2 M3: D-011, Owner D4 and clarifications C, D, F, H)
# Per task: every declared need is probed. PASS is ready; anything else blocks the task, unless the Owner accepted that risk
# (CONDITIONAL; critical needs can't be accepted, clarification D) or a person verified an UNKNOWN one (a credential, an
# approval). Inferred needs (the task's words) only ask for confirmation (F). Teams on a Claude Code or Codex plan also need a
# working sign-in (D-015 D1): a FAIL there blocks every task of the team. Each blocking or accepted item is a risk in the
# register (orchestrator.io_risks, D-012), keyed so a repeated probe updates the same record; a passing probe resolves it.
GATE_ON = __import__("os").getenv("READINESS_GATE", "1") != "0"
CRITICAL = ("auth", "approval", "credential")
VERIFY_DAYS = 7  # a person's verification of an UNKNOWN need holds this long
REMEDY = {
    "docker": ("Where the VM runner is installed, AXoR's own check job settles an UNKNOWN within a few minutes: check again. Otherwise run it where "
               "Docker is (the Owner's host session), or have the Owner install the VM runner (k8s/runner, D-013); or change the task.", "Owner"),
    "registry": ("Push from the Owner's machine or session: agents have no push path (it needs a person's approval and a credential store).", "Owner"),
    "vm": ("VMs for agents' jobs come with the VM runner (k8s/runner, D-013), the Owner's step: run it elsewhere or change the task.", "Owner"),
    "internet": ("An administrator turns the team's sandbox internet on, or checks the egress proxy.", "Owner"),
    "live_data": ("Web: check the address is right and the site answers AXoR's server-side read, then Re-check. Chain: check the team's chain "
                  "collector (its scout) can read the chain; the next snapshot clears it. Sandbox internet is not involved.", "the team"),
    "postgres": ("Run one sandbox run that uses postgres to prove it, or fix the sandbox.", "AXoR"),
    "clickhouse": ("Run one sandbox run that uses clickhouse to prove it, or fix the sandbox.", "AXoR"),
    "gpu": ("No GPU for sandbox runs: change the task or run it elsewhere.", "Owner"),
    "ram": ("Sandbox runs get 4 GB by default. Where a larger size exists, a run gets it only when the team's runs are planned (an "
            "administrator turns the team's execution switches on) and the task declares the need. Otherwise reduce the memory the task "
            "needs, or run it elsewhere.", "the team lead"),
    "credential": ("Verify the credential works, then record the verification on this risk.", "Owner"),
    "approval": ("The Owner approves the external action, then records it on this risk.", "Owner"),
    "auth": ("Sign the login in again (Agents → Models, or My logins), then check it.", "Owner"),
}


# reach proven inside the sandbox (2026-11-13): set here, apart from the table above, which the runner's stream edits too
REMEDY["internet"] = ("An administrator turns the team's sandbox internet on, or checks the egress proxy. When the answer is UNKNOWN, AXoR's check run "
                      "inside the sandbox settles it within a few minutes: check again.", "Owner")
REMEDY["git"] = ("Check the repository's address (git:<host>/<owner>/<repo>) and that it is public: sandbox runs carry no repository credentials, so a "
                 "private one needs the Owner to provide its files another way. The team's sandbox internet must be on.", "Owner")


def _rkey(mission, task_ref, cap, value): return f"readiness:{mission or '-'}:{task_ref}:{cap}:{value or ''}"


CRED_ABSENT_HOURS = 24  # a credential this server can't see can't be watched for changes: its verification lasts a day
APPROVAL_HOURS = 24     # an approval is for one execution of one exact task, within this time


CRED_VAULT_HOURS = 24   # a credential Vault holds: a rotation voids its verification at the next check; otherwise it lasts the short time
CRED_UNREADABLE = "unreadable"   # Vault is on but didn't answer: never equal to a recorded fingerprint, and nothing is recorded against it
UNREADABLE_HOLD = 15    # seconds a "Vault didn't answer" is kept, so a sealed Vault doesn't cost one timeout per credential per pass
_fp_cache = {}          # (team, mission, name) -> (when, identity or None or CRED_UNREADABLE): Vault's last answer, for page reads


def _vault_identity(name, team, mission, live=True):
    """(known, identity): Vault's identity of the secret a run of this team and mission would be given under this name, as the
    Vault stream's own lookup answers it (vault.fingerprint(team, mission, name): the path it would read, that secret's version
    and when the version was made; never a copy of its rule, never a value). identity is None when there is no Vault code here,
    no team, Vault is off or holds no such secret, and CRED_UNREADABLE when Vault is on but didn't answer.
    live=True reads Vault every time: a verification is recorded and checked against the secret as it is now, and a run's
    credential grant reads the same moment's answer, so no earlier answer is ever reused for a decision (only "didn't answer",
    for UNREADABLE_HOLD). live=False (a page being read) never calls Vault: the last answer whatever its age, or known=False
    when there is none."""
    try:
        from . import vault
        fn = getattr(vault, "fingerprint", None)
    except Exception:  # noqa: BLE001 - no Vault code on this branch
        fn = None
    if not callable(fn) or team is None: return True, None
    key, now = (team, mission, str(name or "")), time.time()
    hit = _fp_cache.get(key)
    if not live: return (True, hit[1]) if hit else (False, None)
    if hit and hit[1] == CRED_UNREADABLE and now - hit[0] < UNREADABLE_HOLD: return True, CRED_UNREADABLE
    try: got = fn(team, mission, str(name or "")) or None
    except Exception as e:  # noqa: BLE001 - vault.VaultError, or anything else: Vault's answer isn't known
        logging.getLogger("mission_ops").warning("credential %s: Vault didn't answer (%s)", name, type(e).__name__); got = CRED_UNREADABLE
    if len(_fp_cache) > 2000: _fp_cache.clear()
    _fp_cache[key] = (now, got)
    return True, got


def credential_fingerprint(name, team=None, mission=None, live=True):
    """What identifies the credential's current value without showing it.
    - "vault:<path and version>" when Vault holds it for this team or mission: that is the secret a run is given, so it wins over an
      environment variable of the same name, and a rotation (a new version) changes it;
    - CRED_UNREADABLE when Vault is on but can't be read;
    - else the first 16 hex of sha256 of the server's environment variable of that name, or "absent" when the server doesn't hold
      it (then nothing can notice it change).
    None only with live=False, when Vault hasn't been asked about it yet (see _vault_identity)."""
    import hashlib, os
    known, ident = _vault_identity(name, team, mission, live)
    if ident == CRED_UNREADABLE: return CRED_UNREADABLE
    if ident: return vault_fp(ident)
    if not known: return None
    v = os.environ.get(str(name or ""))
    return hashlib.sha256(v.encode()).hexdigest()[:16] if v else "absent"


def vault_fp(ident):
    """The fingerprint recorded for a secret Vault holds, from Vault's identity of it (vault.fingerprint's string). Whole: the
    version and its time are at the end, so it is never cut; hashed only when very long."""
    import hashlib
    fp = "vault:" + re.sub(r"^vault:", "", str(ident))
    return fp if len(fp) <= 300 else "vault:sha256:" + hashlib.sha256(fp.encode()).hexdigest()


def credential_ttl(fp):
    """How long a person's verification of a credential with this fingerprint lasts, in seconds."""
    if str(fp).startswith("vault:"): return CRED_VAULT_HOURS * 3600
    return VERIFY_DAYS * 86400 if fp != "absent" else CRED_ABSENT_HOURS * 3600


_RKEY_CRED = re.compile(r"readiness:(.*?):((?:mw_task|ctl|team):[^:]+):credential:.*", re.S)


def cred_scope(db, rkey):
    """(team, mission) a credential need belongs to, read from its readiness key (_rkey's own form, so every caller that has the
    key reads the same secret and no column of the record is relied on). The team is the board task's own (mw_task:<id> →
    mw_tasks.comp_id, as the run's is); a task that isn't on a board has no team, and Vault is then not asked."""
    m = _RKEY_CRED.fullmatch(rkey or "")
    if not m: return None, None
    mission, t = (None if m.group(1) == "-" else m.group(1)), re.fullmatch(r"mw_task:(\d+)", m.group(2))
    if not t: return None, mission
    try: r = db.q("SELECT comp_id FROM mw_tasks WHERE id=?", (int(t.group(1)),), one=True)
    except Exception:  # noqa: BLE001 - no board here, or a board without teams
        r = None
    return (r["comp_id"] if r and r["comp_id"] is not None else None), mission


def task_payload(t):
    """The exact task an approval is for: sha256 of its title, detail and declared needs. Any edit changes it."""
    import hashlib
    return hashlib.sha256(json.dumps([t.get("title") or "", t.get("detail") or "", t.get("needs") or ""]).encode()).hexdigest()


def _verification(ch, uid, rkey):
    if not ch._has("io_risks"): return None
    r = ch.db.q("SELECT status, verification, resolved_at FROM io_risks WHERE owner_id=? AND rkey=?", (uid, rkey), one=True)
    if not r or r["status"] != "resolved": return None
    try: v = json.loads(r["verification"] or "{}")
    except ValueError: return None
    return v if v.get("by") else None


def _verified(ch, uid, rkey, value=None, live=True, identity=None):
    """A person's verification of a credential still holds: within its expiry, and the credential's fingerprint is the one
    they verified (a changed or newly set credential voids it; for one Vault holds, a new version of the secret does).
    Owner review 2026-11-11 §2C; PX-B16. The team and mission come from the key itself, so every caller reads the same secret.
    live=False (a page being read) never calls Vault: a record tied to a Vault secret that hasn't been looked up yet is shown
    as it stands; a dispatch always checks it live.
    identity (the run's credential grant): Vault's identity of the secret the caller is about to hand over, from the caller's
    own lookup (vault.fingerprint's string). The verification then counts only if it is of exactly that secret, and Vault isn't
    asked again here: the check and the grant rest on one reading of Vault, so no rotation can land between them."""
    v = _verification(ch, uid, rkey)
    if not v or v.get("kind") == "approval": return None
    if (v.get("expires") or 0) < time.time(): return None
    if identity: return v if v.get("fingerprint") == vault_fp(identity) else None
    team, mission = cred_scope(ch.db, rkey)
    fp = credential_fingerprint(value, team, mission, live=live)
    if fp is None:
        if str(v.get("fingerprint") or "").startswith("vault:"): return v
        fp = credential_fingerprint(value)
    if fp == CRED_UNREADABLE or v.get("fingerprint") != fp: return None
    return v


def _approved(ch, uid, rkey, mission, task_ref, t):
    """A one-time approval of this exact task: same mission and task, same payload (title, detail, needs), not used, not expired."""
    v = _verification(ch, uid, rkey)
    if not v or v.get("kind") != "approval" or v.get("consumed"): return None
    if v.get("mission") != mission or v.get("task_ref") != task_ref or (v.get("expires") or 0) < time.time(): return None
    return v if v.get("payload_sha") == task_payload(t) else None


def _accepted(ch, uid, rkey):
    if not ch._has("io_risks"): return False
    r = ch.db.q("SELECT status FROM io_risks WHERE owner_id=? AND rkey=?", (uid, rkey), one=True)
    return bool(r and r["status"] == "accepted")


_written = {}  # rkey -> the probe answer last written: a cached answer read again isn't a new sighting


def _risk(uid, mission, task_ref, title, cap, value, p, critical):
    from . import orchestrator
    k = (uid, _rkey(mission, task_ref, cap, value))
    if _written.get(k) == p.get("checked"): return None
    _written[k] = p.get("checked")
    fix, who = REMEDY.get(cap, ("Provide it or change the task.", "Owner"))
    return orchestrator.risk_upsert(
        uid, _rkey(mission, task_ref, cap, value), evidence=p, mission=mission, task_ref=task_ref,
        layer="workforce" if cap == "auth" else "execution", source="readiness", source_ref=f"probe:{cap}",
        title=f"{cap}{':' + value if value else ''} not ready for “{(title or '')[:80]}”", description=p.get("evidence", ""),
        root_cause=p.get("evidence", ""), probability="observed" if p.get("state") == "FAIL" else "unverified",
        impact={"tasks": [task_ref], "mission": mission}, severity="critical" if critical else "high", priority="high",
        critical=int(critical), detection=f"readiness probe '{cap}' ({p.get('how')}), {time.strftime('%m-%d %H:%M', time.localtime(p.get('checked') or time.time()))}",
        countermeasure=fix, responsible=who, approval="cannot be accepted: fix it" if critical else "the Owner may accept it (CONDITIONAL)")


def task_readiness(ch, uid, comp, t, mission, task_ref, write=True, active=True, decided=None):
    """{state: READY | CONDITIONAL | BLOCKED, items, confirm}: what stands between one task and its dispatch. active=False (a page
    being read) uses only cached probe answers: no sign-in prompt, no live check, nothing written."""
    if not active: write = False
    look = (lambda cap, value=None: probe(ch, comp, cap, value)) if active else (lambda cap, value=None: probe(ch, comp, cap, value, cached_only=True))
    from . import orchestrator, task_lifecycle as tl
    items, confirm = [], []
    k = tl.req_ref(task_ref)
    decided = tl.decisions(ch.db, k[0], [k[1]]).get(k[1], {}) if k and decided is None else (decided or {})
    for n in tl.needs_of(t, decided):
        cap, value = n["cap"], n["value"]
        if n["source"] != "declared":  # F: what the words suggest asks for confirmation, never blocks
            if n.get("decision") != "rejected": confirm.append({"cap": cap, "value": value, "why": n["why"]})  # a person said no: it stops asking (D-017)
            continue
        p, key = look(cap, value), _rkey(mission, task_ref, cap, value)
        crit = cap in CRITICAL
        if p["state"] == "PASS":
            items.append({"cap": cap, "value": value, "state": "ready", "probe": p})
            if write: orchestrator.risk_resolve(uid, key, {"by": "", "probe": p})
            continue
        if cap == "approval":  # bound to this mission, this task and its exact payload; used up when the task starts
            v = _approved(ch, uid, key, mission, task_ref, t)
            if v:
                items.append({"cap": cap, "value": value, "state": "ready", "probe": p, "approved": v, "consume": key}); continue
        elif p["state"] == "UNKNOWN" and cap == "credential":  # a person can vouch for a credential no probe can see, never against a FAIL
            v = _verified(ch, uid, key, value, live=active)
            if v:
                items.append({"cap": cap, "value": value, "state": "ready", "probe": p, "verified": v}); continue
        acc = (not crit) and _accepted(ch, uid, key)
        items.append({"cap": cap, "value": value, "state": "conditional" if acc else "blocked", "critical": crit, "probe": p,
                      "remedy": REMEDY.get(cap, ("", ""))[0], "who": REMEDY.get(cap, ("", "Owner"))[1]})
        if write: _risk(uid, mission, task_ref, t.get("title"), cap, value, p, crit)
    a = look("auth") if comp else None  # D-015 D1: the team's plan sign-in, for every task of a plan team
    if a and a["state"] == "FAIL":
        items.append({"cap": "auth", "value": None, "state": "blocked", "critical": True, "probe": a, "remedy": REMEDY["auth"][0], "who": "Owner"})
        if write: _risk(uid, mission, f"team:{comp['id']}", f"the team {comp.get('name') or comp['id']}", "auth", None, a, True)
    elif a and a["state"] == "PASS" and write:
        orchestrator.risk_resolve(uid, _rkey(mission, f"team:{comp['id']}", "auth", None), {"by": "", "probe": a})
    state = "BLOCKED" if any(i["state"] == "blocked" for i in items) else "CONDITIONAL" if any(i["state"] == "conditional" for i in items) else "READY"
    if write and active: tl.record_verification(ch.db, task_ref, t, items)  # the verified layer: this live check of the declared list (D-017)
    return {"state": state, "items": items, "confirm": confirm}


def gate_text(r):
    b = [i for i in r["items"] if i["state"] == "blocked"]
    return "Held by readiness: " + "; ".join(f"{i['cap']}{':' + i['value'] if i.get('value') else ''} {i['probe']['state']} ({i['probe']['evidence'][:120]}) → {i['remedy']}" for i in b[:3])



def gate_view(ch, me, comps):
    """Mission readiness for the Overview (G5-2 M4): per competition mission PASS / CONDITIONAL / BLOCKED from its open board tasks
    (queued, to do, or held by readiness), the blocked tasks with blocker, remedy and who, confirmations, and the open or
    accepted risks. Read only: probes are the cached ones, and nothing is written."""
    import types as _t
    out = []
    for c in comps:
        wid = c.get("comp_id")
        comp = ch.db.q("SELECT * FROM mw_comps WHERE id=?", (wid,), one=True) if wid and ch._has("mw_comps") else None
        if not comp: continue
        ref = f"comp:{wid}"
        ctx = _t.SimpleNamespace(db=ch.db, w=getattr(ch, "w", None), _has=ch._has)
        blocked, conditional, confirm, n = [], [], 0, 0
        from . import task_lifecycle as tl
        rows = ch.db.q("""SELECT * FROM mw_tasks WHERE comp_id=? AND (status IN ('todo','queued') OR hold='readiness') ORDER BY id DESC LIMIT 400""", (wid,))
        dec = tl.decisions(ch.db, "mw", [t["id"] for t in rows])
        undeclared = 0
        for t in rows:
            undeclared += t.get("needs") is None
            r = task_readiness(ctx, me["id"], comp, t, ref, f"mw_task:{t['id']}", active=False, decided=dec.get(t["id"], {}))  # read only: cached answers
            n += 1
            confirm += len(r["confirm"])
            row = {"task": t["id"], "title": t["title"], "held": t.get("hold") == "readiness",
                   "items": [{k: i.get(k) for k in ("cap", "value", "state", "critical", "remedy", "who")} | {"evidence": i["probe"]["evidence"], "probe": i["probe"]["state"],
                                                                                                       "checked": i["probe"].get("checked"), "stale": bool(i["probe"].get("stale"))}
                             for i in r["items"] if i["state"] != "ready"]}
            if r["state"] == "BLOCKED": blocked.append(row)
            elif r["state"] == "CONDITIONAL": conditional.append(row)
        state = "BLOCKED" if blocked else "CONDITIONAL" if conditional else "PASS"
        out.append({"ref": ref, "title": c.get("title"), "state": state, "tasks": n, "blocked": blocked[:20], "blocked_n": len(blocked),
                    "conditional": conditional[:10], "conditional_n": len(conditional), "confirm": confirm, "undeclared": undeclared})
    from . import orchestrator
    risks = [r for r in (orchestrator.risks(me["id"], org=me.get("role") == "admin") or []) if r["status"] in ("open", "accepted")][:50]
    return {"missions": out, "risks": [{k: r.get(k) for k in ("id", "mission", "task_ref", "title", "severity", "critical", "status", "countermeasure",
                                                               "source", "layer",
                                                               "responsible", "approval", "seen", "last_seen")} | {"state": (r.get("evidence") or {}).get("state"),
                                                                                                               "cap": (r.get("source_ref") or "").partition(":")[2] if r.get("source") == "readiness" else None} for r in risks]}



def refresh_readiness(ch, me, ref):
    """The explicit Re-check (Owner review §2B): probes a competition mission's open tasks for real (the sign-in check included)
    and records what they find. At most once per REFRESH_EVERY per mission."""
    import types as _t
    m = re.fullmatch(r"comp:(\d+)", ref or "")
    if not m: raise HTTPException(404, "Re-check works on a competition mission (comp:N).")
    wid = int(m.group(1))
    comp = ch.db.q("SELECT * FROM mw_comps WHERE id=?", (wid,), one=True) if ch._has("mw_comps") else None
    if not comp or wid not in (ch._comps(me["id"]) if hasattr(ch, "_comps") else {wid: 1}): raise HTTPException(404, "There's no such mission.")
    if not _recheck_slot(ch.db, me["id"], ref):
        last = (ch.db.q("SELECT at FROM mo_rechecks WHERE user_id=? AND mission=?", (me["id"], ref), one=True) or {}).get("at") or time.time()
        raise HTTPException(429, f"Checked {max(0, int(time.time() - last))} s ago: wait a minute between re-checks.")
    for k in [k for k in _probe_cache if k[0] == wid]: _probe_cache.pop(k, None)
    ctx = _t.SimpleNamespace(db=ch.db, w=getattr(ch, "w", None), _has=ch._has)
    n = 0
    for t in ch.db.q("SELECT * FROM mw_tasks WHERE comp_id=? AND (status IN ('todo','queued') OR hold='readiness') ORDER BY id DESC LIMIT 400", (wid,)):
        task_readiness(ctx, me["id"], comp, t, ref, f"mw_task:{t['id']}"); n += 1
    return {"mission": ref, "tasks": n, "checked": time.time()}


REFRESH_EVERY = 60


def _recheck_slot(db, uid, ref, now=None):
    """Takes this owner's Re-check slot for the mission, atomically in the database: one upsert that writes only when there is no
    row or the last one is REFRESH_EVERY old, and returns the row only to the request that wrote it. Two replicas asking at the
    same moment get one yes; a restart forgets nothing."""
    now = now or time.time()  # the table is made at start-up (mount → ensure_schema), never here: replicas would race on the catalog
    return bool(db.q("""INSERT INTO mo_rechecks (user_id, mission, at) VALUES (?, ?, ?)
                        ON CONFLICT (user_id, mission) DO UPDATE SET at=excluded.at WHERE mo_rechecks.at < ? RETURNING user_id""",
                     (uid, ref, now, now - REFRESH_EVERY), one=True))
