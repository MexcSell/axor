"""Competition teams, research: a Workforce mission (workforce.py) as the Workflow's research arm (mining_bench.py).

From the Plan step you start one mission about the team's goal: how the competition scores agents, which kinds of task fail
and why, which approaches are worth trying. It runs on the Workforce's own team and model credits (not the workbench's Claude
Code quota) and skips the Workforce's plan approval. When it's done, its report goes into the Director's next plan prompt,
unless you switch that off. One mission per team at a time; a new one replaces the last.

Administrators only, like the Workflow.
"""
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .mining import _clip

REPORT_CHARS = 5000


class StartIn(BaseModel):
    focus: str = Field("", max_length=1000)


class UseIn(BaseModel):
    use: bool


class Research:
    def __init__(self, work):
        self.w, self.db = work, work.db
        self.db.q("CREATE TABLE IF NOT EXISTS mb_research (flow_id INTEGER PRIMARY KEY, mission_id INTEGER, use INTEGER DEFAULT 1, focus TEXT, by_user TEXT, created REAL)")
        work.research = self

    @property
    def bench(self):
        b = getattr(self.w, "bench", None)
        if not b: raise HTTPException(503, "The Workflow isn't loaded.")
        return b

    @property
    def wf(self):
        return getattr(self.w, "workforce", None)  # main.py hands it over; None when the Workforce is off on this server

    def _mission(self, mid):
        try: return self.wf._mission(mid) if self.wf and mid else None
        except HTTPException: return None  # pruned or deleted in the Workforce

    def start(self, me, fid, b: StartIn):
        f = self.bench._flow(me, fid)
        if not self.wf: raise HTTPException(409, "The Workforce is turned off on this server (WORKFORCE=0 or no agent models).")
        from .workforce import MissionIn
        w = self.w._comp(f["comp_id"])
        label = self.w._label(w)
        goal = " ".join(f"Research for the team competing in {label}: {f['goal']}. Find what would raise its eval score: how the competition "
                        f"scores agents, which kinds of task agents fail and why, and approaches worth trying, each with its evidence. "
                        f"{b.focus.strip()}".split())
        try: mid = self.wf.create(me, MissionIn(goal=goal[:2000], title=_clip(f"Research: {label}", 120), approve_plan=False))
        except HTTPException as e: raise HTTPException(409, f"The Workforce can't start it: {e.detail}")
        self.db.q("""INSERT INTO mb_research (flow_id, mission_id, use, focus, by_user, created) VALUES (?,?,1,?,?,?)
                     ON CONFLICT(flow_id) DO UPDATE SET mission_id=excluded.mission_id, use=1, focus=excluded.focus, by_user=excluded.by_user, created=excluded.created""",
                  (fid, mid, b.focus.strip() or None, me["username"], time.time()))
        self.bench._say(fid, "plan", f"{me['username']} started a Workforce research mission for the Director" + (f": {b.focus.strip()[:160]}" if b.focus.strip() else ""))
        return self.bench.view(me, f["comp_id"])

    def use(self, me, fid, b: UseIn):
        f = self.bench._flow(me, fid)
        self.db.q("UPDATE mb_research SET use=? WHERE flow_id=?", (int(b.use), fid))
        return self.bench.view(me, f["comp_id"])

    def view(self, f):
        r = self.db.q("SELECT * FROM mb_research WHERE flow_id=?", (f["id"],), one=True)
        out = {"available": bool(self.wf), "mission": None}
        if not r: return out
        m = self._mission(r["mission_id"])
        out.update(use=bool(r["use"]), focus=r["focus"], by=r["by_user"], started=r["created"],
                   mission={"id": m["id"], "status": m["status"], "step": m["step"], "headline": m["headline"], "error": m.get("error"),
                            "decisions": m["decisions"]} if m else {"id": r["mission_id"], "status": "gone"})
        return out

    def brief(self, f):
        """The Director's plan prompt lines: the finished mission's report, when you give it to the Director."""
        r = self.db.q("SELECT * FROM mb_research WHERE flow_id=? AND use=1", (f["id"],), one=True)
        m = self._mission(r["mission_id"]) if r else None
        if not m or m["status"] != "done" or not (m["report"] or "").strip(): return []
        return ([f"Research the Workforce did for this team (mission #{m['id']}: its agents worked from what they know and AXoR's subnet data, "
                 "not from this folder, so check its claims against the code):",
                 f"Headline: {m['headline']}", _clip(m["report"], REPORT_CHARS)]
                + [f"- Decision: {d['title']}: {d['detail']}" for d in m["decisions"]])

    def forget(self, fid):
        self.db.q("DELETE FROM mb_research WHERE flow_id=?", (fid,))


def build(work, require):
    r = APIRouter(prefix="/api/mining/research")
    gate = work.m.hub.gate if work.m.hub else (lambda me: me)
    user = lambda req: gate(require(req))
    rs = Research(work)
    r.state = {"research": rs}

    @r.post("/flows/{fid}")
    def start(fid: int, body: StartIn, req: Request): return rs.start(user(req), fid, body)

    @r.patch("/flows/{fid}")
    def use(fid: int, body: UseIn, req: Request): return rs.use(user(req), fid, body)

    return r
