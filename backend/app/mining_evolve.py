"""Competition teams, self-improvement on its own: the closed loop AgentForge runs on its agents' playbooks (a candidate, a
baseline, promote it or roll it back), on top of Improvements (mining_improve.py) and Loadouts (mining_loadout.py).

A Workflow whose Improvements setting is "self" (Loadouts → Improvements → "Improve on its own") goes all the way without you:
- A proposal the Improvement Engineer makes is tested at once (the trial's defaults: held-out tasks and margin).
- A candidate that measured better is promoted: it becomes the engineer's next loadout version.
- Then a watch starts. The promoted version's next real outcomes (reviews, checks, evals, merges: what Loadouts' Scores
  count; trials never count) are compared with the version it replaced. Once it has WINDOW of them it's kept, or rolled
  back to the earlier version when its score fell more than TOLERANCE points below that one's. Without a score to compare
  with (the earlier version had too few outcomes), it's rolled back when its evals lost more often than they gained.
- A version changed by anyone in the meantime ends the watch: that change is the one that counts now.

Guards: automatic diagnoses, trials and promotions stop for the week once the team's improvements (yours included) cost
`cap` USD in the last 7 days, and "frozen" stops them at once. An engineer rolled back in the last 7 days gets no automatic
test or promotion: its next change waits for you, so a change that keeps failing can't loop. Neither stops a watch: rolling back to a version that already
worked is the safe way. Every step is said in the Workflow's log and kept in mb_watches; nothing is ever deleted.
Administrators only, like the Workflow.
"""
import logging, time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .mining_loadout import RestoreIn

log = logging.getLogger("scout.mining.evolve")
WINDOW, TOLERANCE, CAP, CAP_MAX, WEEK = 6, 5, 10.0, 500.0, 7 * 86400
ACTOR = "auto-improve"


def watch_verdict(baseline, s, window=WINDOW, tolerance=TOLERANCE):
    """keep / rollback / None (keep watching) for a promoted version's scores entry `s` (Loadouts.scores) against the score of
    the version it replaced (None: too little to compare)."""
    if (s.get("basis") or 0) < window: return None
    if baseline is not None and s.get("score") is not None:
        return "rollback" if s["score"] < baseline - tolerance else "keep"
    return "rollback" if s.get("eval_down", 0) > s.get("eval_up", 0) else "keep"


class EvolveIn(BaseModel):
    cap: float | None = Field(None, ge=0, le=CAP_MAX)
    frozen: bool | None = None


class Evolve:
    def __init__(self, work):
        self.w, self.db = work, work.db
        q = self.db.q
        q("""CREATE TABLE IF NOT EXISTS mb_watches (id INTEGER PRIMARY KEY AUTOINCREMENT, flow_id INTEGER, agent_id INTEGER, improvement_id INTEGER,
             from_version INTEGER, to_version INTEGER, baseline INTEGER, baseline_n INTEGER, status TEXT, score INTEGER, basis INTEGER,
             result TEXT, started REAL, ended REAL)""")
        q("CREATE INDEX IF NOT EXISTS mb_watches_a ON mb_watches (agent_id, status)")
        have = {c["name"] for c in q("PRAGMA table_info(mb_flows)")}
        if "evolve_cap" not in have: q(f"ALTER TABLE mb_flows ADD COLUMN evolve_cap REAL DEFAULT {CAP}")
        if "evolve_frozen" not in have: q("ALTER TABLE mb_flows ADD COLUMN evolve_frozen INTEGER DEFAULT 0")
        work.evolve = self

    @property
    def imp(self): return self.w.improve
    @property
    def lo(self): return self.w.loadout
    @property
    def bench(self): return self.w.bench

    def _flow(self, fid): return self.db.q("SELECT * FROM mb_flows WHERE id=?", (fid,), one=True)
    def _actor(self, f): return {"id": f["user_id"], "username": ACTOR, "role": "admin"}  # the Workflow's owner, an administrator
    def _on(self, f): return bool(f) and f["improve"] == "self"

    def spent(self, f):
        """What the team's improvements cost in the last 7 days: diagnoses, trial runs and their evals."""
        since = time.time() - WEEK
        diag = self.db.q("SELECT COALESCE(SUM(cost), 0) AS c FROM mb_improvements WHERE flow_id=? AND created>=?", (f["id"], since), one=True)["c"]
        runs = self.db.q("""SELECT COALESCE(SUM(r.cost), 0) AS c FROM mb_runs r WHERE r.flow_id=? AND r.started>=? AND r.run IN
                            (SELECT run FROM mb_trials WHERE run IS NOT NULL UNION SELECT check_run FROM mb_trials WHERE check_run IS NOT NULL)""",
                         (f["id"], since), one=True)["c"]
        return round((diag or 0) + (runs or 0), 4)

    def _blocked(self, f, agent_id=None):
        """Why nothing automatic may start now, or None. An engineer rolled back in the last 7 days waits for you: else the same
        kind of change could be proposed, promoted and rolled back again and again, bounded only by the weekly limit."""
        if f["evolve_frozen"]: return "frozen"
        if agent_id and self.db.q("SELECT 1 FROM mb_watches WHERE agent_id=? AND status='rolled_back' AND ended>=?", (agent_id, time.time() - WEEK), one=True):
            return "this engineer was rolled back in the last 7 days, so its next change is yours to decide"
        cap = f["evolve_cap"] if f["evolve_cap"] is not None else CAP
        if self.spent(f) >= cap: return f"its improvements cost ${self.spent(f):.2f} of the ${cap:.2f} allowed in 7 days"
        return None

    # ---------- hooks (mining_improve.py, mining_loadout.py); errors never stop the work ----------
    def proposed(self, fid, iid):
        f = self._flow(fid)
        if not self._on(f): return
        imp = self.db.q("SELECT * FROM mb_improvements WHERE id=?", (iid,), one=True)
        a = self.bench._agent(imp["agent_id"]) if imp else None
        why = self._blocked(f, imp and imp["agent_id"])
        if why: return self.bench._say(fid, "wait", f"Not testing the proposal for {(a or {}).get('name', 'an engineer')} on its own: {why}. Test it in Loadouts → Improvements.", imp and imp["task_id"])
        from .mining_improve import TestIn
        try: self.imp.test(self._actor(f), iid, TestIn())
        except HTTPException as e:
            self.bench._say(fid, "error", f"The proposal for {(a or {}).get('name', 'an engineer')} couldn't be tested on its own: {e.detail}", imp and imp["task_id"])

    def settled(self, fid, iid, status):
        f = self._flow(fid)
        if not self._on(f) or status != "better": return
        imp = self.db.q("SELECT * FROM mb_improvements WHERE id=?", (iid,), one=True)
        a = self.bench._agent(imp["agent_id"]) if imp else None
        if not a: return
        why = self._blocked(f, a["id"])
        if why: return self.bench._say(fid, "wait", f"The proposal for {a['name']} measured better, but isn't promoted on its own: {why}. Promote it in Loadouts → Improvements.", imp["task_id"])
        before = next((s for s in self.lo.scores(a) if s["version"] == imp["base_version"]), None)
        from .mining_improve import DecideIn
        try: self.imp.decide(self._actor(f), iid, DecideIn(decision="promote"))
        except HTTPException as e:
            return self.bench._say(fid, "error", f"The better proposal for {a['name']} couldn't be promoted on its own: {e.detail}", imp["task_id"])
        now = self.lo._version(self.bench._agent(a["id"]))
        base = before["score"] if before else None
        self.db.q("""INSERT INTO mb_watches (flow_id, agent_id, improvement_id, from_version, to_version, baseline, baseline_n, status, started)
                     VALUES (?,?,?,?,?,?,?,?,?)""", (fid, a["id"], iid, imp["base_version"], now, base, before["basis"] if before else 0, "watching", time.time()))
        self.bench._say(fid, "ok", f"Promoted {a['name']}'s improvement on its own (version {now}). Watching its next {WINDOW} outcomes against version "
                        f"{imp['base_version']}" + (f" (score {base})" if base is not None else " (no score yet: its evals decide)") + "; it rolls back if it does worse.", imp["task_id"])

    def recorded(self, agent_id):
        """Loadouts recorded an outcome for this agent: settle its watch when the window is full."""
        w = self.db.q("SELECT * FROM mb_watches WHERE agent_id=? AND status='watching' ORDER BY id DESC LIMIT 1", (agent_id,), one=True)
        if not w: return
        a = self.bench._agent(agent_id)
        if not a: return self._end(w, "ended", "The engineer left the team.")
        if self.lo._version(a) != w["to_version"]:
            return self._end(w, "ended", f"The loadout changed to version {self.lo._version(a)} meanwhile: that change counts now.")
        s = next((x for x in self.lo.scores(a) if x["version"] == w["to_version"]), None)
        if not s: return
        self.db.q("UPDATE mb_watches SET score=?, basis=? WHERE id=?", (s["score"], s["basis"], w["id"]))
        v = watch_verdict(w["baseline"], s)
        if v is None: return
        f = self._flow(w["flow_id"])
        what = (f"score {s['score']} against version {w['from_version']}'s {w['baseline']}" if w["baseline"] is not None and s["score"] is not None
                else f"its evals gained {s['eval_up']} and lost {s['eval_down']}")
        if v == "keep":
            self._end(w, "kept", f"Kept after {s['basis']} outcomes: {what}.", s)
            return self.bench._say(w["flow_id"], "ok", f"{a['name']}'s version {w['to_version']} stays: {what}.")
        try: self.lo.restore(self._actor(f), agent_id, RestoreIn(version=w["from_version"]))
        except HTTPException as e:
            self._end(w, "ended", f"Doing worse ({what}), but the rollback failed: {e.detail}", s)
            return self.bench._say(w["flow_id"], "error", f"{a['name']}'s version {w['to_version']} does worse ({what}), and rolling back failed: {e.detail}")
        self._end(w, "rolled_back", f"Rolled back to version {w['from_version']} after {s['basis']} outcomes: {what}.", s)
        self.bench._say(w["flow_id"], "error", f"Rolled {a['name']} back to version {w['from_version']}: version {w['to_version']} did worse ({what}).")

    def _end(self, w, status, result, s=None):
        self.db.q("UPDATE mb_watches SET status=?, result=?, ended=?, score=COALESCE(?, score), basis=COALESCE(?, basis) WHERE id=?",
                  (status, result, time.time(), (s or {}).get("score"), (s or {}).get("basis"), w["id"]))

    # ---------- settings and the page ----------
    def setting(self, me, fid, b: EvolveIn):
        f = self.bench._flow(me, fid)
        if b.cap is not None: self.db.q("UPDATE mb_flows SET evolve_cap=? WHERE id=?", (round(b.cap, 2), fid))
        if b.frozen is not None:
            self.db.q("UPDATE mb_flows SET evolve_frozen=? WHERE id=?", (int(b.frozen), fid))
            self.bench._say(fid, "ok", f"{me['username']} {'froze' if b.frozen else 'unfroze'} self-improvement" + (": watches still roll back a version that does worse." if b.frozen else "."))
        return self.lo.view(me, f["id"])

    def view(self, f):
        names = {a["id"]: a["name"] for a in self.bench._team(f["id"])}
        rows = self.db.q("SELECT * FROM mb_watches WHERE flow_id=? ORDER BY id DESC LIMIT 20", (f["id"],))
        return {"cap": f["evolve_cap"] if f["evolve_cap"] is not None else CAP, "cap_max": CAP_MAX, "frozen": bool(f["evolve_frozen"]),
                "spent": self.spent(f), "window": WINDOW, "tolerance": TOLERANCE,
                "watches": [{**w, "agent": names.get(w["agent_id"])} for w in rows]}

    def forget(self, fid): self.db.q("DELETE FROM mb_watches WHERE flow_id=?", (fid,))


def build(work, require):
    r = APIRouter(prefix="/api/mining/evolve")
    gate = work.m.hub.gate if work.m.hub else (lambda me: me)
    user = lambda req: gate(require(req))
    ev = Evolve(work)
    r.state = {"evolve": ev}

    @r.patch("/flows/{fid}")
    def setting(fid: int, body: EvolveIn, req: Request): return ev.setting(user(req), fid, body)

    return r
