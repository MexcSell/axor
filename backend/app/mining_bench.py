"""Competition teams, the Workflow (mining_work.py holds the teams): a small team that works on your real folder, step by step.

The work runs on the AXoR Workbench (workbench/workbench.py), a service on the host with the folders and the host's Claude Code:
each agent is a `claude -p` run, each task its own git worktree on a bench/<slug> branch, so nothing touches your checkout until
you merge. This module keeps the workflow and asks you at every step:

1. Goal: what the team works toward, and which folder and branch.
2. Plan: the Director reads the folder (read only) and proposes tasks; you edit, untick and approve them.
3. Work: you start a task; its engineer edits files in the task's worktree. When it's done the task waits for you ("Send to
   the reviewer"), unless you switched "Ask me between agents" off.
4. Review: the reviewer reads the diff and says approve or change; you read the diff, run the folder's checks (unit tests, an
   eval: commands in the workbench's config, run by the workbench, never by an agent), then merge, send it back with a note
   (the engineer resumes its session) or drop it. The review and every check remember the commit they saw. Merging pins
   the branch's commit: when there's no approving review, a check failed, or either saw an older commit, you're shown why
   and confirm that commit; the workbench refuses if the branch moved past it. The approval (who, when, which commit, what
   was overridden) stays on the task.
5. Submit: once work is merged, you submit to the competition yourself and mark it here; nothing is ever submitted for you.

Every step lands in the flow's log, so the page shows what happened and what waits for you. Administrators only: the
workbench writes on this host.

Settings: WORKBENCH_URL (http://10.42.0.1:8350 in k3s), WORKBENCH_TOKEN.
"""
import json, logging, os, re, secrets, threading, time, urllib.error, urllib.parse, urllib.request

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import agent_core
from .auth import edit_reason
from .mining import _clip

log = logging.getLogger("scout.mining.bench")
TICK = 3
MODELS = ("sonnet", "opus", "haiku")
ROLES = {"director": "Director", "engineer": "Engineer", "reviewer": "Reviewer"}
SEED = [("director", "Dana", "Reads the folder and splits the goal into small tasks, each with the files it touches.", "sonnet"),
        ("engineer", "Ada", "Makes focused code changes and explains what to test.", "sonnet"),
        ("engineer", "Linus", "Makes focused code changes and explains what to test.", "sonnet"),
        ("reviewer", "Vera", "Reads the diff for bugs, scope creep and broken rules; approves or asks for changes.", "sonnet")]
BUDGET = {"plan": 1.0, "engineer": 2.0, "review": 0.6}
OPEN = ("todo", "engineer", "handoff", "review", "ready", "failed")
PLAN_SCHEMA = {"type": "object", "required": ["summary", "tasks"], "properties": {
    "summary": {"type": "string", "description": "Two or three sentences: what you found and how the tasks get to the goal."},
    "tasks": {"type": "array", "maxItems": 8, "items": {"type": "object", "required": ["title", "detail", "files", "engineer"], "properties": {
        "title": {"type": "string"}, "detail": {"type": "string", "description": "What to change and why, and how to check it."},
        "files": {"type": "array", "items": {"type": "string"}}, "engineer": {"type": "string", "description": "An engineer's name from the team."}}}}}}
REVIEW_SCHEMA = {"type": "object", "required": ["verdict", "summary", "issues", "confidence", "evidence"], "properties": {
    "verdict": {"type": "string", "enum": ["approve", "changes"]}, "summary": {"type": "string"},
    "issues": {"type": "array", "items": {"type": "string"}},
    "confidence": {"type": "string", "enum": ["high", "medium", "low"], "description": "high only when you read every changed file and each claim below has a source."},
    "evidence": {"type": "array", "maxItems": 12, "items": {"type": "object", "required": ["claim", "source"], "properties": {
        "claim": {"type": "string"}, "source": {"type": "string", "description": "file:line you read, or \"\" when you couldn't check it."}}}}}}


class FlowIn(BaseModel):
    repo: str = Field(..., max_length=60)
    into: str = Field(..., max_length=200)
    goal: str = Field("", max_length=4000)


class FlowPatch(BaseModel):
    goal: str | None = Field(None, max_length=4000)
    into: str | None = Field(None, max_length=200)
    confirm: bool | None = None
    budget: float | None = Field(None, ge=0.1, le=5)


class PlanIn(BaseModel):
    note: str = Field("", max_length=2000)


class PickIn(BaseModel):
    id: int
    on: bool = True
    title: str = Field(..., min_length=2, max_length=200)
    detail: str = Field("", max_length=6000)
    engineer: int | None = None


class ApproveIn(BaseModel):
    tasks: list[PickIn] = Field(..., max_length=20)


class TaskIn(BaseModel):
    title: str = Field(..., min_length=2, max_length=200)
    detail: str = Field("", max_length=6000)
    engineer: int | None = None


class AgentIn(BaseModel):
    role: str = Field("engineer", max_length=20)
    name: str = Field(..., min_length=1, max_length=40)
    instructions: str = Field("", max_length=2000)
    model: str = Field("sonnet", max_length=20)


class AgentPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=40)
    instructions: str | None = Field(None, max_length=2000)
    model: str | None = Field(None, max_length=20)
    on: bool | None = None
    reason: str | None = Field(None, max_length=300)  # required when the instructions or the model change (K-22, G5-5 L5.4b)
    evidence: str | None = Field(None, max_length=300)  # what the edit rests on, if anything


class BackIn(BaseModel):
    note: str = Field(..., min_length=2, max_length=4000)


class CheckIn(BaseModel):
    check: str = Field(..., max_length=60)


class SubmitIn(BaseModel):
    note: str = Field("", max_length=2000)


class MergeIn(BaseModel):
    anyway: bool = False                                     # you saw the doubts and merge this commit all the same
    head: str | None = Field(None, pattern=r"^[0-9a-f]{7,40}$")  # the commit you confirmed


def _same(a, b):
    return bool(a and b) and (a.startswith(b) or b.startswith(a))


class Bench:
    def __init__(self, work, url=None, token=None):
        self.w, self.db = work, work.db
        self.url = (url if url is not None else os.getenv("WORKBENCH_URL", "")).rstrip("/")
        self.token = token if token is not None else os.getenv("WORKBENCH_TOKEN", "")
        q = self.db.q
        q("""CREATE TABLE IF NOT EXISTS mb_flows (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER UNIQUE, user_id INTEGER, repo TEXT, into_branch TEXT,
             goal TEXT, confirm INTEGER DEFAULT 1, budget REAL DEFAULT 2.0, plan_run TEXT, plan_summary TEXT, plan_error TEXT,
             submitted REAL, submit_note TEXT, created REAL, updated REAL)""")
        q("""CREATE TABLE IF NOT EXISTS mb_agents (id INTEGER PRIMARY KEY AUTOINCREMENT, flow_id INTEGER, role TEXT, name TEXT, instructions TEXT,
             model TEXT, on_team INTEGER DEFAULT 1, created REAL)""")
        q("""CREATE TABLE IF NOT EXISTS mb_tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, flow_id INTEGER, title TEXT, detail TEXT, files TEXT, status TEXT,
             engineer_id INTEGER, slug TEXT, base TEXT, session TEXT, run TEXT, summary TEXT, review TEXT, checks TEXT, note TEXT, error TEXT,
             cost REAL DEFAULT 0, merged TEXT, created REAL, updated REAL)""")
        q("""CREATE TABLE IF NOT EXISTS mb_runs (run TEXT PRIMARY KEY, flow_id INTEGER, task_id INTEGER, kind TEXT, who TEXT, label TEXT, status TEXT,
             cost REAL DEFAULT 0, error TEXT, started REAL, finished REAL)""")
        q("CREATE TABLE IF NOT EXISTS mb_log (id INTEGER PRIMARY KEY AUTOINCREMENT, flow_id INTEGER, task_id INTEGER, kind TEXT, text TEXT, ts REAL)")
        have = {c["name"] for c in q("PRAGMA table_info(mb_tasks)")}
        for col in ("reviewed TEXT", "approval TEXT", "plan_run TEXT"):  # the commit the review read; who merged which commit, over what; the plan it came from
            if col.split()[0] not in have: q(f"ALTER TABLE mb_tasks ADD COLUMN {col}")
        q("CREATE INDEX IF NOT EXISTS mb_tasks_f ON mb_tasks (flow_id, id)")
        q("CREATE INDEX IF NOT EXISTS mb_log_f ON mb_log (flow_id, id)")
        self.info, self.info_at, self.info_err = None, 0, ""
        self.tick_lock = threading.Lock()
        if self.url: threading.Thread(target=self._loop, daemon=True, name="mining-bench").start()
        work.bench = self

    # ---------- the workbench ----------
    def call(self, path, body=None, timeout=30):
        if not self.url: raise HTTPException(503, "The workbench isn't connected: an administrator installs it on the host (workbench/README.md).")
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode() if body is not None else None, method="POST" if body is not None else "GET",
                                     headers={"X-Workbench-Token": self.token, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r: return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try: detail = json.loads(e.read()).get("detail")
            except ValueError: detail = None
            raise HTTPException(e.code if e.code in (400, 404, 409) else 502, detail or f"The workbench answered {e.code}.")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise HTTPException(503, f"The workbench doesn't answer at {self.url}: {getattr(e, 'reason', e)}. Is axor-workbench running on the host?")

    def _info(self, fresh=False):
        if not fresh and time.time() - self.info_at < 10: return self.info
        try: self.info, self.info_err = self.call("/info", timeout=10), ""
        except HTTPException as e: self.info, self.info_err = None, e.detail
        self.info_at = time.time()
        return self.info

    def _repo(self, rid):
        i = self._info()
        return next((r for r in (i or {}).get("repos", []) if r["id"] == rid), None)

    # ---------- rows ----------
    def _admin(self, me):
        if me.get("role") != "admin": raise HTTPException(403, "The Workflow edits files on this host, so only administrators can use it.")
        return me

    def _flow_of(self, me, wid):
        self._admin(me); self.w._own(me, wid)
        return self.db.q("SELECT * FROM mb_flows WHERE comp_id=?", (wid,), one=True)

    def _flow(self, me, fid):
        f = self.db.q("SELECT * FROM mb_flows WHERE id=?", (fid,), one=True)
        if not f: raise HTTPException(404, "There's no such workflow.")
        self._admin(me); self.w._own(me, f["comp_id"])
        return f

    def _task(self, me, tid):
        t = self.db.q("SELECT * FROM mb_tasks WHERE id=?", (tid,), one=True)
        if not t: raise HTTPException(404, "There's no such task.")
        return t, self._flow(me, t["flow_id"])

    def _agent(self, aid):
        return self.db.q("SELECT * FROM mb_agents WHERE id=?", (aid,), one=True) if aid else None

    def _team(self, fid, role=None):
        rows = self.db.q("SELECT * FROM mb_agents WHERE flow_id=? ORDER BY CASE role WHEN 'director' THEN 0 WHEN 'engineer' THEN 1 ELSE 2 END, id", (fid,))
        return [a for a in rows if (role is None or a["role"] == role)]

    def _say(self, fid, kind, text, tid=None):
        self.db.q("INSERT INTO mb_log (flow_id, task_id, kind, text, ts) VALUES (?,?,?,?,?)", (fid, tid, kind, _clip(text, 600), time.time()))

    def _set(self, tid, **kw):
        kw["updated"] = time.time()
        self.db.q(f"UPDATE mb_tasks SET {', '.join(f'{k}=?' for k in kw)} WHERE id=?", (*kw.values(), tid))

    def _touch(self, fid, **kw):
        kw["updated"] = time.time()
        self.db.q(f"UPDATE mb_flows SET {', '.join(f'{k}=?' for k in kw)} WHERE id=?", (*kw.values(), fid))

    # ---------- the page ----------
    def step(self, f, tasks):
        if not f: return "goal"
        if not (f["goal"] or "").strip(): return "goal"
        live = [t for t in tasks if t["status"] != "dropped"]
        if f["plan_run"] or (not live) or any(t["status"] == "proposed" for t in live): return "plan"
        if any(t["status"] == "ready" for t in live): return "review"
        if any(t["status"] in ("todo", "engineer", "handoff", "review", "failed") for t in live): return "work"
        return "submit" if any(t["status"] == "merged" for t in live) else "plan"

    def view(self, me, wid):
        self._admin(me)
        w, c = self.w._own(me, wid)
        f = self.db.q("SELECT * FROM mb_flows WHERE comp_id=?", (wid,), one=True)
        info = self._info()
        out = {"connected": bool(info), "why": "" if info else (self.info_err or "The workbench isn't set up."), "url": self.url,
               "info": info, "comp": {"id": w["id"], "label": self.w._label(w), "goal": w["goal"] or ""}, "models": MODELS, "roles": ROLES, "flow": None}
        if not f: return out
        tasks = self.db.q("SELECT * FROM mb_tasks WHERE flow_id=? AND status!='dropped' ORDER BY id", (f["id"],))
        runs = self.db.q("SELECT * FROM mb_runs WHERE flow_id=? ORDER BY started DESC LIMIT 60", (f["id"],))
        for t in tasks:
            for k in ("review", "checks", "files", "approval"): t[k] = json.loads(t[k]) if t[k] else ([] if k == "files" else {} if k == "checks" else None)
        out.update(flow={k: f[k] for k in ("id", "repo", "into_branch", "goal", "confirm", "budget", "plan_run", "plan_summary", "plan_error", "submitted", "submit_note", "created")},
                   repo=self._repo(f["repo"]) if info else None, agents=self._team(f["id"]), tasks=tasks, runs=runs, step=self.step(f, tasks),
                   log=self.db.q("SELECT * FROM mb_log WHERE flow_id=? ORDER BY id DESC LIMIT 80", (f["id"],)),
                   spent=sum(r["cost"] or 0 for r in self.db.q("SELECT cost FROM mb_runs WHERE flow_id=?", (f["id"],))),
                   ledger=self._lab("ledger", f) or [], research=self._research("view", f), improving=self._improve("waiting", f) or [])
        return out

    # ---------- 1. goal ----------
    def create(self, me, wid, b: FlowIn):
        if self._flow_of(me, wid): raise HTTPException(409, "This team already has a workflow.")
        r = self._repo(b.repo) if self._info(fresh=True) else None
        if not r: raise HTTPException(400, self.info_err or "Pick a folder the workbench offers.")
        if b.into not in (r.get("heads") or {}): raise HTTPException(400, f"{r['name']} has no branch {b.into}.")
        w, _ = self.w._own(me, wid)
        now = time.time()
        fid = self.db.q("""INSERT INTO mb_flows (comp_id, user_id, repo, into_branch, goal, created, updated) VALUES (?,?,?,?,?,?,?) RETURNING id""",
                        (wid, me["id"], b.repo, b.into, b.goal.strip() or (w["goal"] or ""), now, now), one=True)["id"]
        for role, name, ins, model in SEED:
            self.db.q("INSERT INTO mb_agents (flow_id, role, name, instructions, model, created) VALUES (?,?,?,?,?,?)", (fid, role, name, ins, model, now))
        self._say(fid, "goal", f"{me['username']} set up the workflow on {r['name']} ({b.into})" + (f": {b.goal.strip()[:200]}" if b.goal.strip() else ""))
        return self.view(me, wid)

    def update(self, me, fid, b: FlowPatch):
        f = self._flow(me, fid)
        kw = {}
        if b.goal is not None and b.goal.strip() != (f["goal"] or ""):
            kw["goal"] = b.goal.strip(); self._say(fid, "goal", f"Goal: {b.goal.strip()[:300]}")
        if b.into is not None and b.into != f["into_branch"]:
            r = self._repo(f["repo"])
            if not r or b.into not in (r.get("heads") or {}): raise HTTPException(400, f"There's no branch {b.into}.")
            kw["into_branch"] = b.into; self._say(fid, "goal", f"Work now starts from and merges into {b.into}")
        if b.confirm is not None: kw["confirm"] = int(b.confirm)
        if b.budget is not None: kw["budget"] = b.budget
        if kw: self._touch(fid, **kw)
        return self.view(me, f["comp_id"])

    def reset(self, me, fid):
        f = self._flow(me, fid)
        busy = self.db.q("SELECT run FROM mb_runs WHERE flow_id=? AND status IN ('queued','running')", (fid,))
        for r in busy:
            try: self.call(f"/runs/{r['run']}/stop", {})
            except HTTPException: pass
        for t in ("mb_tasks", "mb_agents", "mb_runs", "mb_log"): self.db.q(f"DELETE FROM {t} WHERE flow_id=?", (fid,))
        self.db.q("DELETE FROM mb_flows WHERE id=?", (fid,))
        self._lab("forget", fid)
        self._improve("forget", fid)
        self._research("forget", fid)
        return self.view(me, f["comp_id"])

    # ---------- runs on the workbench ----------
    def _run(self, f, kind, who, label, body, tid=None, agent=None):
        lo = getattr(self.w, "loadout", None) if agent else None  # mining_loadout.py: skills, MCP, effort, memory
        if lo: body = lo.apply(f, agent, kind, body, tid)
        applied = body.pop("_applied", None)
        r = self.call(f"/repos/{f['repo']}/runs", {"kind": kind, "who": who, "title": label, **body})
        self.db.q("INSERT INTO mb_runs (run, flow_id, task_id, kind, who, label, status, started) VALUES (?,?,?,?,?,?,?,?)",
                  (r["id"], f["id"], tid, kind, who, _clip(label, 200), r["status"], time.time()))
        # the agent core's ledger: a run on the host, so record() (it never takes this thread's model calls)
        agent_core.record("workflow", f["user_id"], kind, f"mb:{r['id']}", agent_key=f"workflow:{agent['id']}" if agent else None, title=label)
        if lo:
            try: lo.started(r["id"], f, agent, kind, tid, {"_applied": applied})
            except Exception as e:  # noqa: BLE001 - the run is going: scores never stop the work
                log.warning("loadout started %s: %s", r["id"], e)
        return r["id"]

    def _lab(self, name, *a, **kw):
        lab = getattr(self.w, "lab", None)  # mining_lab.py: the score of every evaluated commit
        if not lab: return None
        try: return getattr(lab, name)(*a, **kw)
        except Exception as e:  # noqa: BLE001 - scores never stop the work
            log.warning("lab %s: %s", name, e)

    def _ext(self, attr, name, *a, **kw):
        m = getattr(self.w, attr, None)  # mining_improve.py (work.improve), mining_research.py (work.research)
        if not m: return None
        try: return getattr(m, name)(*a, **kw)
        except Exception as e:  # noqa: BLE001 - they never stop the work
            log.warning("%s %s: %s", attr, name, e)

    def _improve(self, name, *a, **kw): return self._ext("improve", name, *a, **kw)
    def _research(self, name, *a, **kw): return self._ext("research", name, *a, **kw)

    def _outcome(self, kind, fid, t=None, **kw):
        if kind in ("merged", "dropped", "sent_back"): self._lab("decided", kind, fid, t)
        lo = getattr(self.w, "loadout", None)
        if not lo: return
        try: lo.outcome(kind, fid, t, **kw)
        except Exception as e:  # noqa: BLE001 - scores never stop the work
            log.warning("loadout outcome %s: %s", kind, e)

    def _context(self, f):
        w = self.w._comp(f["comp_id"])
        lines = [f"Competition: {self.w._label(w)}."]
        if (w.get("description") or "").strip(): lines.append(f"About it: {_clip(w['description'], 1500)}")
        lines.append(f"The team's goal: {f['goal']}")
        return "\n".join(lines)

    def _head(self, f):
        r = self._repo(f["repo"]) if self._info(fresh=True) else None
        sha = (r or {}).get("heads", {}).get(f["into_branch"])
        if not sha: raise HTTPException(409, self.info_err or f"The folder has no branch {f['into_branch']} any more.")
        return sha

    def _tip(self, f, t, d=None):
        """The task branch's commit now (a workbench before v3 gives only the short sha of its newest commit)."""
        if not t["slug"] or not t["base"]: return None
        d = d or self.call("/repos/{}/diff?{}".format(f["repo"], urllib.parse.urlencode({"base": t["base"], "slug": t["slug"]})))
        return d.get("head") or ((d.get("commits") or [{}])[0].get("sha"))

    # ---------- 2. plan ----------
    def plan(self, me, fid, b: PlanIn):
        f = self._flow(me, fid)
        if not (f["goal"] or "").strip(): raise HTTPException(409, "Write the goal first: the Director plans toward it.")
        if f["plan_run"]: raise HTTPException(409, "The Director is already planning.")
        d = next((a for a in self._team(fid, "director") if a["on_team"]), None)
        if not d: raise HTTPException(409, "The team has no Director: add one in Team.")
        eng = [a["name"] for a in self._team(fid, "engineer") if a["on_team"]]
        if not eng: raise HTTPException(409, "The team has no engineer: add one in Team.")
        done = self.db.q("SELECT title, status, summary FROM mb_tasks WHERE flow_id=? AND status NOT IN ('proposed','dropped') ORDER BY id", (fid,))
        prompt = [self._context(f), "",
                  f"You are {d['name']}, the Director. {d['instructions']}",
                  f"Read this folder (branch {f['into_branch']}) to see where the work stands, then propose the next tasks toward the goal: "
                  "at most 6, each small enough for one engineer in one session, naming the files it touches and how to check it. "
                  f"Assign each to one of these engineers: {', '.join(eng)}. Engineers can read and edit files but can't run commands; "
                  "the user runs the tests and evals. Don't propose copying other miners' code.",
                  ]
        if done: prompt += ["", "Tasks so far:"] + [f"- [{t['status']}] {t['title']}" + (f": {_clip(t['summary'], 200)}" if t["summary"] else "") for t in done]
        ledger = self._lab("ledger", f)  # mining_lab.py: what the base solves and what earlier tasks did to the score
        if ledger: prompt += ["", *ledger]
        research = self._research("brief", f)  # mining_research.py: a Workforce mission's findings, when you gave them to the Director
        if research: prompt += ["", *research]
        if b.note.strip(): prompt += ["", f"The user adds: {b.note.strip()}"]
        rid = self._run(f, "plan", d["name"], "Plan", {"prompt": "\n".join(prompt), "model": d["model"], "budget_usd": min(BUDGET["plan"], f["budget"]), "schema": PLAN_SCHEMA}, agent=d)
        self._touch(fid, plan_run=rid, plan_error=None)
        self._say(fid, "plan", f"{d['name']} is reading the folder and planning" + (f" ({b.note.strip()[:120]})" if b.note.strip() else ""))
        return self.view(me, f["comp_id"])

    def _planned(self, f, run):
        self._touch(f["id"], plan_run=None)
        out = run.get("structured") or {}
        if run["status"] != "done" or not out.get("tasks"):
            err = run.get("error") or "The Director finished without a plan."
            self._touch(f["id"], plan_error=_clip(err, 600))
            self._outcome("run_failed", f["id"], run=run["id"], detail=err)
            return self._say(f["id"], "error", f"Planning failed: {err}")
        self.db.q("DELETE FROM mb_tasks WHERE flow_id=? AND status='proposed'", (f["id"],))
        names = {a["name"].lower(): a["id"] for a in self._team(f["id"], "engineer") if a["on_team"]}
        now = time.time()
        for t in out["tasks"][:8]:
            self.db.q("INSERT INTO mb_tasks (flow_id, title, detail, files, status, engineer_id, plan_run, created, updated) VALUES (?,?,?,?,?,?,?,?,?)",
                      (f["id"], _clip(t.get("title"), 200), _clip(t.get("detail"), 6000), json.dumps((t.get("files") or [])[:20]), "proposed",
                       names.get((t.get("engineer") or "").strip().lower()), run["id"], now, now))
        self._touch(f["id"], plan_summary=_clip(out.get("summary"), 2000))
        self._outcome("planned", f["id"], run=run["id"], value=len(out["tasks"][:8]))
        self._say(f["id"], "wait", f"The plan is ready: {len(out['tasks'][:8])} tasks proposed. Approve the ones you want.")

    def approve(self, me, fid, b: ApproveIn):
        f = self._flow(me, fid)
        team = {a["id"] for a in self._team(fid, "engineer")}
        n, proposed, gone = 0, len(self.db.q("SELECT id FROM mb_tasks WHERE flow_id=? AND status='proposed'", (fid,))), []
        for p in b.tasks:
            t = self.db.q("SELECT * FROM mb_tasks WHERE id=? AND flow_id=? AND status='proposed'", (p.id, fid), one=True)
            if not t: continue
            if not p.on: gone.append(t["title"]); self.db.q("DELETE FROM mb_tasks WHERE id=?", (t["id"],)); continue
            self._set(t["id"], title=p.title.strip(), detail=p.detail.strip(), engineer_id=p.engineer if p.engineer in team else t["engineer_id"], status="todo")
            n += 1
        self.db.q("DELETE FROM mb_tasks WHERE flow_id=? AND status='proposed'", (fid,))
        self._outcome("approved", fid, value=(n, proposed, gone))
        self._say(fid, "ok", f"{me['username']} approved {n} task{'s' if n != 1 else ''}" + (": start them one by one in Work." if n else "."))
        return self.view(me, f["comp_id"])

    def add_task(self, me, fid, b: TaskIn):
        f = self._flow(me, fid)
        eng = self._agent(b.engineer)
        now = time.time()
        tid = self.db.q("INSERT INTO mb_tasks (flow_id, title, detail, files, status, engineer_id, created, updated) VALUES (?,?,?,?,?,?,?,?) RETURNING id",
                        (fid, b.title.strip(), b.detail.strip(), "[]", "todo", eng["id"] if eng and eng["flow_id"] == fid else None, now, now), one=True)["id"]
        self._say(fid, "ok", f"{me['username']} added the task “{b.title.strip()}”", tid)
        return self.view(me, f["comp_id"])

    # ---------- 3. work ----------
    def _slug(self, t):
        s = re.sub(r"[^a-z0-9]+", "-", t["title"].lower()).strip("-")[:36].strip("-")
        return f"t{t['id']}-{s or 'task'}-{secrets.token_hex(2)}"  # the suffix keeps a branch left from an earlier database out of it

    def _task_prompt(self, f, t, a, slug, base, note=""):
        """A fresh engineer run's prompt (mining_improve.py's trials give the same task to a candidate version of the agent)."""
        files = json.loads(t["files"] or "[]")
        return "\n".join([self._context(f), "", f"You are {a['name']}, an engineer on the team. {a['instructions']}",
                          f"Your task: {t['title']}", t["detail"] or "", f"Files it likely touches: {', '.join(files)}" if files else "",
                          f"You're in a git worktree of the folder on branch bench/{slug}, made from {f['into_branch']} at {base[:8]}. "
                          "Edit files here only. You can't run commands: the user runs the tests and evals after you. "
                          "Keep the change focused on this task. When you're done, say in a few lines what you changed, why, and what the user should test."]
                         + ([f"The user adds: {note}"] if note else []))

    def _engineer(self, f, t, note=""):
        a = self._agent(t["engineer_id"])
        if not a or not a["on_team"]:
            a = next((x for x in self._team(f["id"], "engineer") if x["on_team"]), None)
            if not a: raise HTTPException(409, "The team has no engineer on: add one in Team.")
            self._set(t["id"], engineer_id=a["id"])
        slug = t["slug"] or self._slug(t)
        base = t["base"] or self._head(f)
        if note and t["session"]:
            prompt, resume = f"The user sends your work back with this note:\n{note}\n\nRework it in the same folder, then say what you changed.", t["session"]
        else:
            prompt, resume = self._task_prompt(f, t, a, slug, base, note), None
        rid = self._run(f, "engineer", a["name"], t["title"], {"slug": slug, "base": base, "prompt": prompt, "model": a["model"],
                                                              "budget_usd": min(BUDGET["engineer"], f["budget"]), "resume": resume}, t["id"], agent=a)
        self._set(t["id"], status="engineer", run=rid, slug=slug, base=base, error=None, note=note or None)
        self._say(f["id"], "run", f"{a['name']} started “{t['title']}”" + (" again, with your note" if note else "") + f" on bench/{slug}", t["id"])

    def start(self, me, tid):
        t, f = self._task(me, tid)
        if t["status"] not in ("todo", "failed"): raise HTTPException(409, "This task isn't waiting to start.")
        if t["status"] == "failed" and t["session"] and t["error"]:
            self._engineer(f, t, note=f"Your last run stopped with: {t['error']}. Carry on from where you got.")
        else: self._engineer(f, t)
        return self.view(me, f["comp_id"])

    def _reviewer(self, f, t):
        a = next((x for x in self._team(f["id"], "reviewer") if x["on_team"]), None)
        if not a:
            self._set(t["id"], status="ready", review=None)
            return self._say(f["id"], "wait", f"“{t['title']}” is ready for you (the team has no reviewer on)", t["id"])
        d = self.call("/repos/{}/diff?{}".format(f["repo"], urllib.parse.urlencode({"base": t["base"], "slug": t["slug"]})))
        if not d.get("files"):
            self._set(t["id"], status="ready", review=json.dumps({"verdict": "changes", "summary": "The engineer changed no files.", "issues": []}))
            return self._say(f["id"], "wait", f"“{t['title']}”: no files changed. Send it back or drop it.", t["id"])
        prompt = "\n".join([self._context(f), "", f"You are {a['name']}, the reviewer. {a['instructions']}", f"The task: {t['title']}", t["detail"] or "",
                            f"The engineer says: {_clip(t['summary'], 3000)}", "", "The diff against the base:", _clip(d["patch"], 60000), "",
                            "You're in the task's worktree and can read any file for context. Check the change does the task, has no bugs, stays in "
                            "scope and keeps the folder's rules (CLAUDE.md). Approve, or ask for changes with each issue on its own line. "
                            "List the evidence your verdict rests on, each claim with the file and line you read, and say how sure you are."])
        rid = self._run(f, "review", a["name"], f"Review: {t['title']}", {"slug": t["slug"], "base": t["base"], "prompt": prompt, "model": a["model"],
                                                                          "budget_usd": min(BUDGET["review"], f["budget"]), "schema": REVIEW_SCHEMA}, t["id"], agent=a)
        self._set(t["id"], status="review", run=rid, reviewed=self._tip(f, t, d))  # review runs can't edit: this is the commit it reads
        self._say(f["id"], "run", f"{a['name']} is reviewing “{t['title']}”", t["id"])

    def next(self, me, tid):
        t, f = self._task(me, tid)
        if t["status"] != "handoff": raise HTTPException(409, "This task isn't waiting to move on.")
        self._say(f["id"], "ok", f"{me['username']} sent “{t['title']}” to review", tid)
        self._reviewer(f, t)
        return self.view(me, f["comp_id"])

    def back(self, me, tid, b: BackIn):
        t, f = self._task(me, tid)
        if t["status"] not in ("handoff", "ready", "failed"): raise HTTPException(409, "This task isn't waiting for you.")
        self._say(f["id"], "ok", f"{me['username']} sent “{t['title']}” back: {b.note.strip()[:200]}", tid)
        self._outcome("sent_back", f["id"], t, detail=b.note.strip())
        self._engineer(f, t, note=b.note.strip())
        return self.view(me, f["comp_id"])

    def stop(self, me, tid):
        t, f = self._task(me, tid)
        if t["run"] and t["status"] in ("engineer", "review"):
            try: self.call(f"/runs/{t['run']}/stop", {})
            except HTTPException: pass
        return self.view(me, f["comp_id"])

    def _finished(self, t, run):
        f = self.db.q("SELECT * FROM mb_flows WHERE id=?", (t["flow_id"],), one=True)
        cost = (t["cost"] or 0) + (run.get("cost") or 0)
        who = run.get("who") or "The agent"
        if t["status"] == "engineer":
            if run["status"] != "done":
                self._set(t["id"], status="failed", error=_clip(run.get("error") or run["status"], 600), cost=cost, session=run.get("session") or t["session"], run=None)
                self._outcome("run_failed", f["id"], t, run=run["id"], detail=run.get("error") or run["status"])
                return self._say(f["id"], "error", f"{who} stopped on “{t['title']}”: {run.get('error') or run['status']}. Start it again or send it back with a note.", t["id"])
            self._set(t["id"], status="handoff", summary=_clip(run.get("result"), 6000), session=run.get("session") or t["session"], cost=cost, run=None)
            if not run.get("commit") and not self._has_work(f, t):
                self._outcome("no_change", f["id"], t, run=run["id"])
                self._say(f["id"], "wait", f"{who} finished “{t['title']}” without changing any file. Read what it says, then send it back or drop it.", t["id"])
            elif f["confirm"]:
                self._say(f["id"], "wait", f"{who} finished “{t['title']}”" + (f" (commit {run['commit']})" if run.get("commit") else "") + ". Look at it, then send it to the reviewer.", t["id"])
            else:
                self._say(f["id"], "ok", f"{who} finished “{t['title']}”: on to review", t["id"])
                try: self._reviewer(f, {**t, "status": "handoff", "summary": run.get("result")})
                except HTTPException as e: self._say(f["id"], "error", f"Couldn't start the review: {e.detail}", t["id"])
        elif t["status"] == "review":
            rev = run.get("structured") if run["status"] == "done" else None
            if not rev: rev = {"verdict": "changes", "summary": f"The review didn't finish: {run.get('error') or run['status']}.", "issues": []}
            self._set(t["id"], status="ready", review=json.dumps(rev), cost=cost, run=None)
            self._outcome("review", f["id"], t, run=run["id"], value=rev.get("verdict"), detail="; ".join(rev.get("issues") or []) or rev.get("summary", ""))
            self._say(f["id"], "wait", f"{who} {'approves' if rev.get('verdict') == 'approve' else 'asks for changes on'} “{t['title']}”. It's your call: merge, send back or drop.", t["id"])

    def _has_work(self, f, t):
        try: return bool(self.call("/repos/{}/diff?{}".format(f["repo"], urllib.parse.urlencode({"base": t["base"], "slug": t["slug"]}))).get("files"))
        except HTTPException: return True

    # ---------- 4. review ----------
    def diff(self, me, tid):
        t, f = self._task(me, tid)
        if not t["slug"] or not t["base"]: return {"files": [], "patch": "", "commits": []}
        return self.call("/repos/{}/diff?{}".format(f["repo"], urllib.parse.urlencode({"base": t["base"], "slug": t["slug"]})))

    def check(self, me, tid, b: CheckIn):
        t, f = self._task(me, tid)
        if not t["slug"]: raise HTTPException(409, "Nothing to check yet: start the task first.")
        r = self._repo(f["repo"]) or {}
        ch = next((c for c in r.get("checks", []) if c["id"] == b.check), None)
        if not ch: raise HTTPException(404, "There's no such check for this folder.")
        try: tip = self._tip(f, t)
        except HTTPException: tip = None
        rid = self._run(f, "check", "Workbench", f"{ch['label']}: {t['title']}", {"check": b.check, "slug": t["slug"], "base": t["base"]}, t["id"])
        checks = json.loads(t["checks"] or "{}")
        checks[b.check] = {"label": ch["label"], "run": rid, "status": "running", "at": time.time(), "head": tip}
        self._set(tid, checks=json.dumps(checks))
        if ch.get("scored"): self._lab("started", f, t, rid, ch, tip)
        self._say(f["id"], "run", f"{me['username']} ran “{ch['label']}” on “{t['title']}”", tid)
        return self.view(me, f["comp_id"])

    def _checked(self, t, run):
        checks = json.loads(t["checks"] or "{}")
        for k, c in checks.items():
            if c.get("run") == run["id"]:
                tail = [e["text"] for e in run.get("events", []) if e["k"] == "out"][-12:]
                c.update(status=run["status"], exit=run.get("exit"), tail="\n".join(tail)[-2000:], error=run.get("error"))
                self._set(t["id"], checks=json.dumps(checks))
                if c.get("score"): self._scored(t, c)  # an eval exits non-zero once a task fails: its score is the outcome, not its exit
                else:
                    self._outcome("check", t["flow_id"], t, value="pass" if run["status"] == "done" else "fail", detail=f"“{c['label']}”" + (f" ({tail[-1][:200]})" if tail and run["status"] != "done" else ""))
                    self._say(t["flow_id"], "ok" if run["status"] == "done" else "error", f"“{c['label']}” {'passed' if run['status'] == 'done' else 'failed'} on “{t['title']}”", t["id"])

    def _scored(self, t, c):
        """A scored check's result against the base the task's branch was made from: an outcome for the engineer (and the plan
        the task came from), and a proposal to improve the engineer when the branch lost eval tasks."""
        s, vs = c["score"], c["score"].get("vs")
        text = f"“{c['label']}” solved {s['solved']} of {s['tasks']} on “{t['title']}”"
        if not vs:
            return self._say(t["flow_id"], "ok", f"{text}. Measure the base in the Lab to see what it gained.", t["id"])
        d = vs["solved"] - vs["base"]
        detail = (f"solved {vs['solved']} of {vs['shared']} shared tasks against {vs['base']} on the base ({f'+{d}' if d > 0 else d if d else 'same'})"
                  + (f"; gained {', '.join(vs.get('gained_tasks') or [])}" if vs["gained"] else "") + (f"; lost {', '.join(vs.get('lost_tasks') or [])}" if vs["lost"] else ""))
        if vs.get("stale"):  # main moved since the task started: the difference may be other work, so it counts for nobody
            return self._say(t["flow_id"], "ok", f"{text}: {detail}. The base was measured on another commit, so this isn't counted for the agent: measure the base at {t['base'][:8]} to compare like with like.", t["id"])
        self._outcome("eval", t["flow_id"], t, value=d, detail=detail)
        self._say(t["flow_id"], "ok" if d >= 0 and not vs["lost"] else "error", f"{text}: {detail}", t["id"])
        if vs["lost"] or d < 0: self._improve("regressed", t, c)

    def _doubts(self, t, tip):
        """Why merging this commit isn't plainly backed by the review and the checks; empty when it is."""
        out, rv = [], json.loads(t["review"]) if t["review"] else None
        if not rv: out.append("No reviewer has read it.")
        elif rv.get("verdict") != "approve": out.append("The reviewer asked for changes.")
        elif t["reviewed"] and not _same(t["reviewed"], tip): out.append(f"The branch changed after the review: the reviewer read {t['reviewed'][:8]}, it's at {tip[:8]} now.")
        for c in json.loads(t["checks"] or "{}").values():
            if c.get("status") == "running": out.append(f"“{c['label']}” is still running.")
            elif c.get("status") != "done": out.append(f"“{c['label']}” failed.")
            elif c.get("head") and not _same(c["head"], tip): out.append(f"“{c['label']}” passed on an older commit ({c['head'][:8]}).")
        return out

    def _approval(self, me, t, commit, doubts, **kw):
        rv = json.loads(t["review"]) if t["review"] else None
        checks = {c["label"]: {k: c.get(k) for k in ("status", "head", "score")} for c in json.loads(t["checks"] or "{}").values()}
        return json.dumps({"by": me["username"], "at": time.time(), "commit": commit, "reviewed": t["reviewed"], "verdict": (rv or {}).get("verdict"),
                           "checks": checks, "over": doubts, **kw})

    def merge(self, me, tid, b: MergeIn | None = None):
        b = b or MergeIn()
        t, f = self._task(me, tid)
        if t["status"] not in ("ready", "handoff"): raise HTTPException(409, "Only work waiting for you can be merged.")
        tip = self._tip(f, t)
        if not tip: raise HTTPException(409, "The branch has no commit to merge.")
        if b.anyway and not b.head: raise HTTPException(422, "Say which commit you confirm.")
        if b.head and not _same(b.head, tip):
            return {**self.view(me, f["comp_id"]), "merge": {"ok": False, "why": f"The branch moved to {tip[:8]} after you confirmed {b.head[:8]}: look at the new work, then merge again."}}
        doubts = self._doubts(t, tip)
        if doubts and not b.anyway: return {**self.view(me, f["comp_id"]), "merge": {"ok": False, "confirm": doubts, "head": tip}}
        r = self.call(f"/repos/{f['repo']}/merge", {"slug": t["slug"], "into": f["into_branch"], "expect": tip}, timeout=180)
        if not r.get("ok"):
            self._say(f["id"], "error", f"Didn't merge “{t['title']}”: {r.get('why')}", tid)
            return {**self.view(me, f["comp_id"]), "merge": r}
        commit = r.get("from") or tip
        self._set(tid, status="merged", merged=r.get("head"), approval=self._approval(me, t, commit, doubts, head=r.get("head")))
        self._outcome("merged", f["id"], t, value=r.get("head"), detail=_clip(t["summary"], 300))
        self._say(f["id"], "ok", f"{me['username']} merged “{t['title']}” at {commit[:8]} into {f['into_branch']} ({r.get('head')})"
                  + (f", over: {' '.join(doubts)}" if doubts else ""), tid)
        return {**self.view(me, f["comp_id"]), "merge": r}

    def merged_by_hand(self, me, tid):
        t, f = self._task(me, tid)
        if t["status"] not in ("ready", "handoff"): raise HTTPException(409, "Only work waiting for you can be marked merged.")
        try: tip = self._tip(f, t)
        except HTTPException: tip = None
        self._set(tid, status="merged", merged="by hand", approval=self._approval(me, t, tip, self._doubts(t, tip) if tip else [], by_hand=True))
        self._outcome("merged", f["id"], t, value="by hand", detail=_clip(t["summary"], 300))
        self._say(f["id"], "ok", f"{me['username']} merged “{t['title']}” by hand", tid)
        return self.view(me, f["comp_id"])

    def drop(self, me, tid):
        t, f = self._task(me, tid)
        if t["status"] in ("engineer", "review"): raise HTTPException(409, "Stop it first.")
        if t["slug"]:
            try: self.call(f"/repos/{f['repo']}/drop", {"slug": t["slug"]})
            except HTTPException as e: log.warning("bench drop %s: %s", t["slug"], e.detail)
        if t["slug"]: self._outcome("dropped", f["id"], t)
        self._set(tid, status="dropped")
        self._say(f["id"], "ok", f"{me['username']} dropped “{t['title']}”" + (f" and its branch bench/{t['slug']}" if t["slug"] else ""), tid)
        return self.view(me, f["comp_id"])

    # ---------- 5. submit ----------
    def submitted(self, me, fid, b: SubmitIn):
        f = self._flow(me, fid)
        self._touch(fid, submitted=time.time(), submit_note=b.note.strip() or None)
        self._say(fid, "ok", f"{me['username']} submitted to the competition" + (f": {b.note.strip()[:200]}" if b.note.strip() else ""))
        return self.view(me, f["comp_id"])

    # ---------- the team ----------
    def add_agent(self, me, fid, b: AgentIn):
        f = self._flow(me, fid)
        if b.role not in ROLES: raise HTTPException(422, "Pick a role.")
        if b.model not in MODELS: raise HTTPException(422, "Pick a model.")
        if len(self._team(fid)) >= 12: raise HTTPException(409, "A team has at most 12 agents.")
        if b.role == "director" and self._team(fid, "director"): raise HTTPException(409, "The team already has a Director.")
        self.db.q("INSERT INTO mb_agents (flow_id, role, name, instructions, model, created) VALUES (?,?,?,?,?,?)",
                  (fid, b.role, b.name.strip(), b.instructions.strip(), b.model, time.time()))
        self._say(fid, "ok", f"{b.name.strip()} joined as {ROLES[b.role]}")
        return self.view(me, f["comp_id"])

    def update_agent(self, me, aid, b: AgentPatch):
        a = self._agent(aid)
        if not a: raise HTTPException(404, "There's no such agent.")
        f = self._flow(me, a["flow_id"])
        kw = {k: v for k, v in (("name", b.name and b.name.strip()), ("instructions", b.instructions), ("model", b.model)) if v is not None}
        if "model" in kw and kw["model"] not in MODELS: raise HTTPException(422, "Pick a model.")
        if b.on is not None: kw["on_team"] = int(b.on)
        # A person's change to what the agent does (instructions, model): a reason, a version in the loadout's store (ml_versions)
        # and an agent.edit audit row (K-22, G5-5 L5.4b part A). The version before is taken first, so the edit can be undone.
        cfg = {k: (a[k], kw[k]) for k in ("instructions", "model") if k in kw and (kw[k] or "") != (a[k] or "")}
        lo = getattr(self.w, "loadout", None)
        if cfg:
            reason = edit_reason(b.reason)
            if not lo: raise HTTPException(503, "The agents' version store isn't loaded: nothing was changed.")
            before = lo._version(a)
        if kw: self.db.q(f"UPDATE mb_agents SET {', '.join(f'{k}=?' for k in kw)} WHERE id=?", (*kw.values(), aid))
        if cfg:
            n = lo._version(self._agent(aid), note=reason, source="manual", user=me["username"])
            self.db.agent_edit(me["username"], f"workflow:{aid}", "ml_versions", reason, before, n, {"restore": before}, cfg, "",
                               {k: v for k, v in cfg.items() if k != "instructions"}, b.evidence or "")
        return self.view(me, f["comp_id"])

    def remove_agent(self, me, aid):
        a = self._agent(aid)
        if not a: raise HTTPException(404, "There's no such agent.")
        f = self._flow(me, a["flow_id"])
        if self.db.q("SELECT 1 FROM mb_tasks WHERE engineer_id=? AND status IN ('engineer','review')", (aid,), one=True): raise HTTPException(409, f"{a['name']} is working: stop the task first.")
        self.db.q("UPDATE mb_tasks SET engineer_id=NULL WHERE engineer_id=?", (aid,))
        self.db.q("DELETE FROM mb_agents WHERE id=?", (aid,))
        self._say(f["id"], "ok", f"{a['name']} left the team")
        return self.view(me, f["comp_id"])

    # ---------- files and runs ----------
    def tree(self, me, fid, path, ref):
        f = self._flow(me, fid)
        return self.call(f"/repos/{f['repo']}/tree?" + urllib.parse.urlencode({"path": path or "", "ref": ref or ""}))

    def file(self, me, fid, path, ref):
        f = self._flow(me, fid)
        return self.call(f"/repos/{f['repo']}/file?" + urllib.parse.urlencode({"path": path or "", "ref": ref or ""}))

    def run(self, me, rid, after):
        r = self.db.q("SELECT * FROM mb_runs WHERE run=?", (rid,), one=True)
        if not r: raise HTTPException(404, "There's no such run.")
        self._flow(me, r["flow_id"])
        return self.call(f"/runs/{rid}?after={int(after)}")

    # ---------- the loop: picks up finished runs ----------
    def _loop(self):
        while True:
            time.sleep(TICK)
            try: self.tick()
            except Exception as e:  # noqa: BLE001 - the loop keeps going
                log.warning("bench tick: %s", e)

    def tick(self):
        with self.tick_lock:
            for r in self.db.q("SELECT * FROM mb_runs WHERE status IN ('queued','running')"):
                try: run = self.call(f"/runs/{r['run']}?after=0", timeout=15)
                except HTTPException as e:
                    if e.status_code == 404: run = {"id": r["run"], "status": "failed", "error": "The workbench lost this run."}
                    else: continue
                if run["status"] in ("queued", "running"):
                    if run["status"] != r["status"]: self.db.q("UPDATE mb_runs SET status=? WHERE run=?", (run["status"], r["run"]))
                    continue
                self.db.q("UPDATE mb_runs SET status=?, cost=?, error=?, finished=? WHERE run=?",
                          (run["status"], run.get("cost") or 0, _clip(run.get("error"), 600), time.time(), r["run"]))
                agent_core.record("workflow", (self.db.q("SELECT user_id FROM mb_flows WHERE id=?", (r["flow_id"],), one=True) or {}).get("user_id"), r["kind"], f"mb:{r['run']}", title=r["label"],
                                  status="done" if run["status"] == "done" else run["status"], cost=run.get("cost") or 0, error=run.get("error"))
                if r["kind"] == "check": self._lab("finished", r, run)  # before the task: a baseline run has none, and the score goes on the task's check
                if self._improve("finished", r, run): continue  # mining_improve.py's diagnoses, trial runs and their evals
                if r["kind"] == "plan":
                    f = self.db.q("SELECT * FROM mb_flows WHERE id=?", (r["flow_id"],), one=True)
                    if f and f["plan_run"] == r["run"]: self._planned(f, run)
                    continue
                t = self.db.q("SELECT * FROM mb_tasks WHERE id=?", (r["task_id"],), one=True)
                if not t: continue
                if r["kind"] == "check": self._checked(t, run)
                elif t["run"] == r["run"]: self._finished(t, run)


def build(work, require):
    r = APIRouter(prefix="/api/mining/bench")
    gate = work.m.hub.gate if work.m.hub else (lambda me: me)
    user = lambda req: gate(require(req))
    b = Bench(work)
    r.state = {"bench": b}

    @r.get("/comps/{wid}")
    def view(wid: int, req: Request): return b.view(user(req), wid)

    @r.post("/comps/{wid}")
    def create(wid: int, body: FlowIn, req: Request): return b.create(user(req), wid, body)

    @r.patch("/flows/{fid}")
    def update(fid: int, body: FlowPatch, req: Request): return b.update(user(req), fid, body)

    @r.delete("/flows/{fid}")
    def reset(fid: int, req: Request): return b.reset(user(req), fid)

    @r.post("/flows/{fid}/plan")
    def plan(fid: int, body: PlanIn, req: Request): return b.plan(user(req), fid, body)

    @r.post("/flows/{fid}/approve")
    def approve(fid: int, body: ApproveIn, req: Request): return b.approve(user(req), fid, body)

    @r.post("/flows/{fid}/tasks")
    def add_task(fid: int, body: TaskIn, req: Request): return b.add_task(user(req), fid, body)

    @r.post("/flows/{fid}/agents")
    def add_agent(fid: int, body: AgentIn, req: Request): return b.add_agent(user(req), fid, body)

    @r.post("/flows/{fid}/submitted")
    def submitted(fid: int, body: SubmitIn, req: Request): return b.submitted(user(req), fid, body)

    @r.get("/flows/{fid}/tree")
    def tree(fid: int, req: Request, path: str = "", ref: str = ""): return b.tree(user(req), fid, path, ref)

    @r.get("/flows/{fid}/file")
    def file(fid: int, req: Request, path: str = "", ref: str = ""): return b.file(user(req), fid, path, ref)

    @r.patch("/agents/{aid}")
    def update_agent(aid: int, body: AgentPatch, req: Request): return b.update_agent(user(req), aid, body)

    @r.delete("/agents/{aid}")
    def remove_agent(aid: int, req: Request): return b.remove_agent(user(req), aid)

    for name in ("start", "next", "stop", "drop"):
        def act(tid: int, req: Request, _n=name): return getattr(b, _n)(user(req), tid)
        r.add_api_route(f"/tasks/{{tid}}/{name}", act, methods=["POST"], name=f"bench_{name}")

    @r.post("/tasks/{tid}/merge")
    def merge(tid: int, req: Request, body: MergeIn | None = None): return b.merge(user(req), tid, body)

    @r.post("/tasks/{tid}/merged")
    def merged(tid: int, req: Request): return b.merged_by_hand(user(req), tid)

    @r.post("/tasks/{tid}/back")
    def back(tid: int, body: BackIn, req: Request): return b.back(user(req), tid, body)

    @r.post("/tasks/{tid}/check")
    def check(tid: int, body: CheckIn, req: Request): return b.check(user(req), tid, body)

    @r.get("/tasks/{tid}/diff")
    def diff(tid: int, req: Request): return b.diff(user(req), tid)

    @r.get("/runs/{rid}")
    def run(rid: str, req: Request, after: int = 0): return b.run(user(req), rid, after)

    return r
