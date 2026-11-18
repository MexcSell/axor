"""Competition teams, loadouts: what each Workflow agent (mining_bench.py) brings to its runs on the AXoR Workbench, and how well
each version of it did.

- A loadout is an agent's model and instructions (kept on mb_agents) plus its skills, plugins, MCP servers, memory, effort and
  budget per run. An agent without one of its own runs on its role's template (TEMPLATES), so a new team starts equipped.
- Skills are SKILL.md texts: the built-in ones below or your own. The workbench writes them into a plugin folder of its own for
  the run (outside the worktree, no hooks), so Claude Code loads them the way it loads any plugin's skills.
- A plugin is a named bundle of skills and MCP servers. Claude Code plugins with hooks aren't loaded: hooks would run as root.
- MCP servers come only from the workbench's config on the host (/etc/axor-workbench.json, "mcp"): you pick them by id here.
- Memory: notes per agent (private) and per team. Some are written for you as the work goes (review issues, send-backs, failed
  checks, merges, which planned tasks you kept); the newest go into the agent's system prompt when its memory is on.
- Versions: every change to a loadout, here or in the Workflow's Team card, is a new version. Every run records the version it
  ran with, and every outcome of the work (the review's verdict, checks, merge, send back, drop) is recorded against the run
  that produced it, at the moment it happens, so the Scores compare versions on what actually happened.
- Suggestions read those scores and propose changes; nothing changes until you apply one.

Administrators only, like the Workflow.
"""
import json, math, re, time
from collections import Counter

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .mining import _clip
from .workforce import _words

NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}$")
EFFORTS = ("", "low", "medium", "high", "xhigh", "max")
MEMORY = {"off": "Off", "own": "Its own notes", "team": "Its own and the team's notes"}
MAX_SKILLS, NOTES_IN_PROMPT, NOTES_NEWEST, NOTES_CHARS, AUTO_NOTES_KEPT = 16, 12, 4, 3500, 60
OUTCOMES = ("planned", "approved", "run_failed", "no_change", "review", "check", "merged", "sent_back", "dropped")

SKILLS = [
    ("repo-map", "Map the repository", "Use at the start of any task in a folder you haven't read yet, before planning or editing.", ["director", "engineer", "reviewer"], """\
# Map the repository before you change it

1. Read the folder's CLAUDE.md and README first: they hold the rules you must keep.
2. List the top level, then the folders the task names. Find the entry points (the miner's agent file, main modules), the tests
   and anything that scores the work (eval scripts, sample sets, scoring notes).
3. Before editing, write down in two or three lines: where the code for this task lives, what calls it, which tests cover it.
4. Prefer Grep/Glob over reading whole trees; read whole files only when you will change them.
"""),
    ("task-splitting", "Split a goal into tasks", "Use when planning: turning a goal into tasks for engineers.", ["director"], """\
# Split the goal into tasks that land

- Each task is one engineer, one session, one focused diff. If it needs "and then", split it.
- Give each task the files it touches. Two tasks touching the same file can't run at once: order them or merge them.
- Every task says how the user checks it: which test, which eval, what should change in the score.
- Order by value: the change most likely to raise the competition's score first; cleanups last or not at all.
- Read your notes from earlier plans: if the user dropped a kind of task before, don't propose it again.
"""),
    ("eval-first", "Work toward the score", "Use whenever a change is meant to raise a competition score or pass rate.", ["director", "engineer", "reviewer"], """\
# Work toward what is scored

- Find out how the competition scores a submission (the eval scripts, the sample tasks, the rules page notes in the folder)
  before deciding what to change.
- Prefer changes that help across the whole hidden test distribution over tricks that only fit the visible samples.
- Never copy or adapt other miners' published agents: it is against the rules and gets submissions rejected.
- Say what you expect to happen to the score and which check shows it.
"""),
    ("small-diff", "Keep the diff small", "Use for every code change as an engineer.", ["engineer"], """\
# Keep the diff small and readable

- Change only what the task needs. No drive-by refactors, renames or formatting of untouched lines.
- Match the surrounding code: naming, comments, error handling, imports.
- No new dependencies unless the task asks for them.
- When you finish, list the files you changed and, for each, one line on why. Then say exactly what the user should run to
  check it.
"""),
    ("test-aware", "Change code and its tests together", "Use when changing code that has tests, or when checks failed on earlier work.", ["engineer"], """\
# Change code and tests together

You can't run commands, so reason like a test runner:
- Find the tests that cover what you change (Grep for the function and module names). Read them before editing.
- Update tests whose expectations your change alters, and add a test for the new behaviour or the bug you fix.
- Walk through the changed code by hand with one normal input and one edge case (empty, None, very large, wrong type).
- If an earlier check failed (see your notes), find the cause in the code before changing anything else.
"""),
    ("python-quality", "Write sound Python", "Use when writing or changing Python code.", ["engineer", "reviewer"], """\
# Sound Python

- Keep functions short and typed where the folder already uses type hints.
- Handle the errors you can act on; let the rest raise. Never `except: pass`.
- Close files and processes (with-blocks); no mutable default arguments; no global state for per-call data.
- Use the standard library before adding packages; keep imports at the top in the folder's style.
"""),
    ("failure-analysis", "Learn from the last failure", "Use when a task was sent back, a check failed or a run stopped.", ["director", "engineer"], """\
# Learn from the last failure first

1. Read your notes and the user's note: what exactly failed or was rejected?
2. Name the root cause in one sentence before touching code. If you can't, read more until you can.
3. Fix the cause, not the symptom, and check nothing else relied on the old behaviour.
4. In your summary, say what went wrong last time and why this time is different.
"""),
    ("review-checklist", "Review checklist", "Use for every review of an engineer's diff.", ["reviewer", "engineer"], """\
# Review checklist

Go through each point and only then decide:
1. Does the diff do the task, all of it, and nothing unrelated?
2. Bugs: off-by-one, None/empty input, wrong types, exceptions swallowed, resources not closed.
3. Tests: are the changed behaviours covered? Would the folder's checks still pass?
4. Rules: CLAUDE.md, the competition's rules (no copied miner code), no secrets, no new dependencies without reason.
5. Score: is it likely to help the competition's score, or only the visible samples?
Approve only if nothing in 1–4 fails. Each issue on its own line, with the file and what to change.
"""),
]
SKILL_ROLES = {s[0]: s[3] for s in SKILLS}
PLUGINS = [
    ("competition-starter", "Competition starter", "Know the folder and work toward the score.", ["repo-map", "eval-first"], []),
    ("python-engineer", "Python engineer", "Small, tested, idiomatic Python changes.", ["small-diff", "test-aware", "python-quality"], []),
    ("strict-review", "Strict review", "A checklist review that keeps the score in mind.", ["review-checklist", "eval-first", "python-quality"], []),
]
TEMPLATES = {
    "director": {"skills": ["task-splitting", "failure-analysis"], "plugins": ["competition-starter"], "mcp": [], "memory": "team", "effort": "high", "budget": None},
    "engineer": {"skills": ["failure-analysis"], "plugins": ["python-engineer"], "mcp": [], "memory": "own", "effort": "medium", "budget": None},
    "reviewer": {"skills": [], "plugins": ["strict-review"], "mcp": [], "memory": "own", "effort": "high", "budget": None},
}


class LoadoutIn(BaseModel):
    model: str | None = Field(None, max_length=20)
    instructions: str | None = Field(None, max_length=2000)
    skills: list[str] = Field(default_factory=list, max_length=MAX_SKILLS)
    plugins: list[str] = Field(default_factory=list, max_length=8)
    mcp: list[str] = Field(default_factory=list, max_length=8)
    memory: str = Field("own", max_length=8)
    effort: str = Field("", max_length=8)
    budget: float | None = Field(None, ge=0.1, le=5)
    note: str = Field("", max_length=300)
    source: str = Field("manual", max_length=12)


class RestoreIn(BaseModel):
    version: int


class SkillIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    title: str = Field("", max_length=80)
    description: str = Field(..., min_length=8, max_length=600)
    body: str = Field(..., min_length=10, max_length=20000)
    roles: list[str] = Field(default_factory=list, max_length=3)


class PluginIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    title: str = Field("", max_length=80)
    description: str = Field("", max_length=600)
    skills: list[str] = Field(default_factory=list, max_length=MAX_SKILLS)
    mcp: list[str] = Field(default_factory=list, max_length=8)


class NoteIn(BaseModel):
    text: str = Field(..., min_length=2, max_length=1500)
    agent: int | None = None  # None: the team's


class NotePatch(BaseModel):
    text: str | None = Field(None, min_length=2, max_length=1500)
    team: bool | None = None


def _j(s, d=None): return json.loads(s) if s else ([] if d is None else d)


class Loadouts:
    def __init__(self, work):
        self.w, self.db = work, work.db
        q = self.db.q
        q("""CREATE TABLE IF NOT EXISTS ml_skills (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, title TEXT, description TEXT,
             body TEXT, roles TEXT, created REAL, updated REAL)""")
        q("""CREATE TABLE IF NOT EXISTS ml_plugins (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, title TEXT, description TEXT,
             skills TEXT, mcp TEXT, created REAL, updated REAL)""")
        q("""CREATE TABLE IF NOT EXISTS ml_loadouts (agent_id INTEGER PRIMARY KEY, skills TEXT, plugins TEXT, mcp TEXT, memory TEXT, effort TEXT,
             budget REAL, updated REAL)""")
        q("""CREATE TABLE IF NOT EXISTS ml_versions (id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id INTEGER, n INTEGER, snap TEXT, note TEXT,
             source TEXT, user TEXT, created REAL)""")
        q("""CREATE TABLE IF NOT EXISTS ml_runs (run TEXT PRIMARY KEY, agent_id INTEGER, version INTEGER, flow_id INTEGER, task_id INTEGER, kind TEXT,
             applied TEXT, created REAL)""")
        q("""CREATE TABLE IF NOT EXISTS ml_outcomes (id INTEGER PRIMARY KEY AUTOINCREMENT, run TEXT, agent_id INTEGER, version INTEGER, flow_id INTEGER,
             task_id INTEGER, kind TEXT, value TEXT, detail TEXT, ts REAL)""")
        q("""CREATE TABLE IF NOT EXISTS ml_memory (id INTEGER PRIMARY KEY AUTOINCREMENT, flow_id INTEGER, agent_id INTEGER, text TEXT, source TEXT,
             task_id INTEGER, created REAL)""")
        q("CREATE INDEX IF NOT EXISTS ml_versions_a ON ml_versions (agent_id, n)")
        q("CREATE INDEX IF NOT EXISTS ml_outcomes_a ON ml_outcomes (agent_id, version)")
        q("CREATE INDEX IF NOT EXISTS ml_runs_t ON ml_runs (task_id, kind)")
        q("CREATE INDEX IF NOT EXISTS ml_memory_f ON ml_memory (flow_id, agent_id, id)")
        work.loadout = self

    @property
    def bench(self):
        b = getattr(self.w, "bench", None)
        if not b: raise HTTPException(503, "The Workflow isn't running.")
        return b

    # ---------- the library ----------
    def _skills(self, uid):
        out = {s[0]: {"id": None, "name": s[0], "title": s[1], "description": s[2], "roles": s[3], "body": s[4], "builtin": True} for s in SKILLS}
        for r in self.db.q("SELECT * FROM ml_skills WHERE user_id=? ORDER BY name", (uid,)):
            out[r["name"]] = {"id": r["id"], "name": r["name"], "title": r["title"] or r["name"], "description": r["description"], "roles": _j(r["roles"]),
                              "body": r["body"], "builtin": False, "updated": r["updated"]}
        return out

    def _plugins(self, uid):
        out = {p[0]: {"id": None, "name": p[0], "title": p[1], "description": p[2], "skills": p[3], "mcp": p[4], "builtin": True} for p in PLUGINS}
        for r in self.db.q("SELECT * FROM ml_plugins WHERE user_id=? ORDER BY name", (uid,)):
            out[r["name"]] = {"id": r["id"], "name": r["name"], "title": r["title"] or r["name"], "description": r["description"] or "",
                              "skills": _j(r["skills"]), "mcp": _j(r["mcp"]), "builtin": False}
        return out

    def _offered(self):
        """The workbench's features and MCP servers, from its /info (cached by the bench)."""
        i = self.bench._info() or {}
        return set(i.get("features") or []), {m["id"]: m for m in i.get("mcp") or []}, bool(i)

    def save_skill(self, me, b: SkillIn, sid=None):
        self.bench._admin(me)
        name = b.name.strip().lower()
        if not NAME.match(name): raise HTTPException(422, "Skill names: lower-case letters, digits and dashes, like eval-first.")
        if name in SKILL_ROLES: raise HTTPException(409, f"{name} is a built-in skill: pick another name (or copy it under a new one).")
        clash = self.db.q("SELECT id FROM ml_skills WHERE user_id=? AND name=?", (me["id"], name), one=True)
        if clash and clash["id"] != sid: raise HTTPException(409, f"You already have a skill called {name}.")
        roles = json.dumps([r for r in b.roles if r in TEMPLATES])
        now = time.time()
        if sid:
            old = self.db.q("SELECT * FROM ml_skills WHERE id=? AND user_id=?", (sid, me["id"]), one=True)
            if not old: raise HTTPException(404, "There's no such skill.")
            self.db.q("UPDATE ml_skills SET name=?, title=?, description=?, body=?, roles=?, updated=? WHERE id=?",
                      (name, b.title.strip(), b.description.strip(), b.body, roles, now, sid))
            if old["name"] != name: self._rename(me, "skills", old["name"], name)
        else:
            self.db.q("INSERT INTO ml_skills (user_id, name, title, description, body, roles, created, updated) VALUES (?,?,?,?,?,?,?,?)",
                      (me["id"], name, b.title.strip(), b.description.strip(), b.body, roles, now, now))
        return {"skills": list(self._skills(me["id"]).values())}

    def delete_skill(self, me, sid):
        self.bench._admin(me)
        r = self.db.q("SELECT * FROM ml_skills WHERE id=? AND user_id=?", (sid, me["id"]), one=True)
        if not r: raise HTTPException(404, "There's no such skill.")
        self.db.q("DELETE FROM ml_skills WHERE id=?", (sid,))
        self._rename(me, "skills", r["name"], None)
        return {"skills": list(self._skills(me["id"]).values())}

    def save_plugin(self, me, b: PluginIn, pid=None):
        self.bench._admin(me)
        name = b.name.strip().lower()
        if not NAME.match(name): raise HTTPException(422, "Plugin names: lower-case letters, digits and dashes.")
        if name in {p[0] for p in PLUGINS}: raise HTTPException(409, f"{name} is a built-in plugin: pick another name.")
        clash = self.db.q("SELECT id FROM ml_plugins WHERE user_id=? AND name=?", (me["id"], name), one=True)
        if clash and clash["id"] != pid: raise HTTPException(409, f"You already have a plugin called {name}.")
        lib = self._skills(me["id"])
        miss = [s for s in b.skills if s not in lib]
        if miss: raise HTTPException(422, f"No such skill: {', '.join(miss)}.")
        now = time.time()
        if pid:
            old = self.db.q("SELECT * FROM ml_plugins WHERE id=? AND user_id=?", (pid, me["id"]), one=True)
            if not old: raise HTTPException(404, "There's no such plugin.")
            self.db.q("UPDATE ml_plugins SET name=?, title=?, description=?, skills=?, mcp=?, updated=? WHERE id=?",
                      (name, b.title.strip(), b.description.strip(), json.dumps(b.skills), json.dumps(b.mcp), now, pid))
            if old["name"] != name: self._rename(me, "plugins", old["name"], name)
        else:
            self.db.q("INSERT INTO ml_plugins (user_id, name, title, description, skills, mcp, created, updated) VALUES (?,?,?,?,?,?,?,?)",
                      (me["id"], name, b.title.strip(), b.description.strip(), json.dumps(b.skills), json.dumps(b.mcp), now, now))
        return {"plugins": list(self._plugins(me["id"]).values())}

    def delete_plugin(self, me, pid):
        self.bench._admin(me)
        r = self.db.q("SELECT * FROM ml_plugins WHERE id=? AND user_id=?", (pid, me["id"]), one=True)
        if not r: raise HTTPException(404, "There's no such plugin.")
        self.db.q("DELETE FROM ml_plugins WHERE id=?", (pid,))
        self._rename(me, "plugins", r["name"], None)
        return {"plugins": list(self._plugins(me["id"]).values())}

    def _rename(self, me, col, old, new):
        """A renamed or deleted skill/plugin follows into the loadouts of this user's teams (the next run is a new version)."""
        for r in self.db.q(f"""SELECT l.agent_id, l.{col} AS v FROM ml_loadouts l JOIN mb_agents a ON a.id=l.agent_id JOIN mb_flows f ON f.id=a.flow_id
                               WHERE f.user_id=?""", (me["id"],)):
            names = _j(r["v"])
            if old in names:
                names = [new if x == old else x for x in names if new or x != old]
                self.db.q(f"UPDATE ml_loadouts SET {col}=?, updated=? WHERE agent_id=?", (json.dumps(names), time.time(), r["agent_id"]))

    # ---------- loadouts ----------
    def _row(self, a):
        r = self.db.q("SELECT * FROM ml_loadouts WHERE agent_id=?", (a["id"],), one=True)
        if not r: return {**TEMPLATES.get(a["role"], TEMPLATES["engineer"]), "default": True}
        return {"skills": _j(r["skills"]), "plugins": _j(r["plugins"]), "mcp": _j(r["mcp"]), "memory": r["memory"] or "own",
                "effort": r["effort"] or "", "budget": r["budget"], "default": False}

    def _snap(self, a, lo=None):
        lo = lo or self._row(a)
        return {"model": a["model"], "instructions": a["instructions"] or "", "role": a["role"],
                **{k: lo[k] for k in ("skills", "plugins", "mcp", "memory", "effort", "budget")}}

    def _version(self, a, note="", source="team", user=""):
        """The agent's current version number: a new one when its model, instructions or loadout changed since the last."""
        snap = self._snap(a)
        last = self.db.q("SELECT n, snap FROM ml_versions WHERE agent_id=? ORDER BY n DESC LIMIT 1", (a["id"],), one=True)
        if last and json.loads(last["snap"]) == snap: return last["n"]
        n = (last["n"] if last else 0) + 1
        if not last and not note: note, source = ("Role template" if self._row(a)["default"] else "First version"), "auto"
        elif not note: note = "Changed in the Workflow's Team card"
        self.db.q("INSERT INTO ml_versions (agent_id, n, snap, note, source, user, created) VALUES (?,?,?,?,?,?,?)",
                  (a["id"], n, json.dumps(snap), _clip(note, 300), source, user, time.time()))
        return n

    def resolved(self, a, uid, lo=None):
        """The skills (with their texts) and MCP ids the agent's loadout comes to, plugins unpacked."""
        lo = lo or self._row(a)
        lib, plugs = self._skills(uid), self._plugins(uid)
        names, mcp = [], list(lo["mcp"])
        for p in lo["plugins"]:
            if p in plugs:
                names += plugs[p]["skills"]; mcp += plugs[p]["mcp"]
        names += lo["skills"]
        seen, skills = set(), []
        for n in names:
            if n in lib and n not in seen: seen.add(n); skills.append(lib[n])
        return skills[:MAX_SKILLS], list(dict.fromkeys(mcp))

    def save(self, me, aid, b: LoadoutIn):
        a, f = self._agent(me, aid)
        uid = f["user_id"]
        lib, plugs = self._skills(uid), self._plugins(uid)
        feats, mcp_offered, up = self._offered()
        if b.memory not in MEMORY: raise HTTPException(422, "Pick a memory setting.")
        if b.effort not in EFFORTS: raise HTTPException(422, "Pick an effort level.")
        if b.model is not None and b.model not in self.bench_models(): raise HTTPException(422, "Pick a model.")
        miss = [s for s in b.skills if s not in lib] + [p for p in b.plugins if p not in plugs]
        if miss: raise HTTPException(422, f"Not in the library: {', '.join(miss)}.")
        lo = {"skills": list(dict.fromkeys(b.skills)), "plugins": list(dict.fromkeys(b.plugins)), "mcp": list(dict.fromkeys(b.mcp)),
              "memory": b.memory, "effort": b.effort, "budget": b.budget}
        skills, mcp = self.resolved(a, uid, lo)
        if up:  # an older workbench ignores what it doesn't know: refuse rather than record runs that didn't get the loadout
            need = [k for k, on in (("skills", skills), ("mcp", mcp), ("effort", b.effort)) if on and k not in feats]
            if need: raise HTTPException(409, f"The workbench on the host doesn't support {', '.join(need)} yet: reinstall it (sudo ./workbench/install.sh …), then save again.")
            bad = [m for m in mcp if m not in mcp_offered]
            if bad: raise HTTPException(422, f"The workbench offers no MCP server {', '.join(bad)}: an administrator adds it to /etc/axor-workbench.json.")
            kind = {"director": "plan", "reviewer": "review"}.get(a["role"], "engineer")
            off = [m for m in mcp if kind not in mcp_offered[m].get("kinds", [kind])]
            if off: raise HTTPException(422, f"{', '.join(off)} isn't offered to {a['role']}s on the workbench.")
        if len(skills) > MAX_SKILLS: raise HTTPException(422, f"At most {MAX_SKILLS} skills, plugins included.")
        kw = {}
        if b.model is not None: kw["model"] = b.model
        if b.instructions is not None: kw["instructions"] = b.instructions.strip()
        if kw: self.db.q(f"UPDATE mb_agents SET {', '.join(f'{k}=?' for k in kw)} WHERE id=?", (*kw.values(), aid))
        self.db.q("""INSERT INTO ml_loadouts (agent_id, skills, plugins, mcp, memory, effort, budget, updated) VALUES (?,?,?,?,?,?,?,?)
                     ON CONFLICT(agent_id) DO UPDATE SET skills=excluded.skills, plugins=excluded.plugins, mcp=excluded.mcp, memory=excluded.memory,
                     effort=excluded.effort, budget=excluded.budget, updated=excluded.updated""",
                  (aid, json.dumps(lo["skills"]), json.dumps(lo["plugins"]), json.dumps(lo["mcp"]), lo["memory"], lo["effort"], lo["budget"], time.time()))
        a = self.bench._agent(aid)
        source = b.source if b.source in ("manual", "suggestion", "template", "restore", "improvement") else "manual"
        before = self.db.q("SELECT MAX(n) AS n FROM ml_versions WHERE agent_id=?", (aid,), one=True)["n"]
        n = self._version(a, note=b.note.strip() or "Edited in Loadouts", source=source, user=me["username"])
        if n != before: self.bench._say(f["id"], "ok", f"{me['username']} changed {a['name']}'s loadout (version {n})" + (f": {b.note.strip()[:160]}" if b.note.strip() else ""))
        if n != before and source != "improvement":  # a person's edit, not a promotion: audited like every manual edit (G5-5 L5.4b part A)
            self.db.agent_edit(me["username"], f"workflow:{aid}", "ml_versions", b.note.strip() or {"template": "Back to the role template",
                               "restore": "Restored a version", "suggestion": "Took a suggested loadout"}.get(source, "Edited in Loadouts"),
                               before, n, {"restore": before}, ["loadout"])
        return self.view(me, f["id"])

    def template(self, me, aid):
        a, f = self._agent(me, aid)
        t = TEMPLATES.get(a["role"], TEMPLATES["engineer"])
        return self.save(me, aid, LoadoutIn(skills=t["skills"], plugins=t["plugins"], mcp=[], memory=t["memory"], effort=t["effort"], budget=None,
                                            note="Back to the role template", source="template"))

    def restore(self, me, aid, b: RestoreIn):
        a, f = self._agent(me, aid)
        v = self.db.q("SELECT * FROM ml_versions WHERE agent_id=? AND n=?", (aid, b.version), one=True)
        if not v: raise HTTPException(404, "There's no such version.")
        s = json.loads(v["snap"])
        return self.save(me, aid, LoadoutIn(model=s["model"], instructions=s["instructions"], skills=s["skills"], plugins=s["plugins"], mcp=s["mcp"],
                                            memory=s["memory"], effort=s["effort"], budget=s["budget"], note=f"Back to version {b.version}", source="restore"))

    def bench_models(self):
        from .mining_bench import MODELS
        return MODELS

    def _agent(self, me, aid):
        a = self.bench._agent(aid)
        if not a: raise HTTPException(404, "There's no such agent.")
        return a, self.bench._flow(me, a["flow_id"])

    # ---------- runs: what the workbench gets ----------
    def apply(self, f, a, kind, body, tid=None, lo=None):
        """The run's body with the agent's loadout (or lo, a candidate's: mining_improve.py's trials): skills, MCP, effort,
        budget, memory in the system prompt."""
        lo = lo or self._row(a)
        skills, mcp = self.resolved(a, f["user_id"], lo)
        feats, offered, up = self._offered()
        dropped = []
        if skills and "skills" not in feats: dropped.append("skills"); skills = []
        if mcp and "mcp" not in feats: dropped.append("MCP"); mcp = []
        mcp = [m for m in mcp if m in offered and kind in offered[m].get("kinds", [kind])]
        effort = lo["effort"] if "effort" in feats else ""
        if lo["effort"] and not effort: dropped.append("effort")
        if dropped: self.bench._say(f["id"], "error", f"{a['name']} ran without its {', '.join(dropped)}: the workbench on the host is older. Reinstall it to use loadouts.", tid)
        out = dict(body)
        if skills: out["skills"] = [{"name": s["name"], "description": s["description"], "body": s["body"]} for s in skills]
        if mcp: out["mcp"] = mcp
        if effort: out["effort"] = effort
        if lo["budget"]: out["budget_usd"] = min(float(lo["budget"]), float(f["budget"] or lo["budget"]))
        system = []
        if skills: system.append("Skills from your loadout (use the Skill tool when one fits the work): " + "; ".join(f"{s['name']}: {s['description']}" for s in skills))
        if mcp: system.append("MCP servers from your loadout: " + ", ".join(f"{m} ({offered[m].get('label') or m})" for m in mcp))
        task = self.db.q("SELECT title, detail FROM mb_tasks WHERE id=?", (tid,), one=True) if tid else None
        notes = self.notes_for(f["id"], a, lo["memory"], " ".join([str(body.get("prompt") or ""), *(str(v or "") for v in (task or {}).values())]))
        if notes: system.append("Your notes from earlier work on this team (the newest, then the ones closest to this work):\n" + notes)
        # A resumed session (a send-back) keeps the system prompt of its first run (Claude Code records it), so what's new goes in
        # the prompt there
        if system and out.get("resume"): out["prompt"] = "\n\n".join([str(out.get("prompt") or ""), *system])
        elif system: out["system"] = "\n\n".join([*([out["system"]] if out.get("system") else []), *system])
        out["_applied"] = {"skills": [s["name"] for s in skills], "mcp": mcp, "effort": effort, "memory": lo["memory"] if notes else "", "dropped": dropped}
        return out

    def started(self, rid, f, a, kind, tid, body):
        n = self._version(a)
        self.db.q("INSERT OR REPLACE INTO ml_runs (run, agent_id, version, flow_id, task_id, kind, applied, created) VALUES (?,?,?,?,?,?,?,?)",
                  (rid, a["id"], n, f["id"], tid, kind, json.dumps(body.get("_applied") or {}), time.time()))

    def notes_for(self, fid, a, memory, query=""):
        """The newest few notes (what just went wrong stays in view), then the ones sharing the most rare words with the work
        (yours count more), then by age."""
        if memory == "off": return ""
        rows = self.db.q("SELECT text, agent_id, source FROM ml_memory WHERE flow_id=? AND (agent_id=? OR (? AND agent_id IS NULL)) ORDER BY id DESC LIMIT 300",
                         (fid, a["id"], int(memory == "team")))
        pick, rest, want = rows[:NOTES_NEWEST], rows[NOTES_NEWEST:], _words(query)
        if want and rest:
            docs = [(r, _words(r["text"])) for r in rest]
            df = Counter(w for _, ws in docs for w in ws)
            rel = [(sum(math.log(1 + len(docs) / df[w]) for w in want & ws) * (1.5 if r["source"] == "you" else 1), i) for i, (r, ws) in enumerate(docs)]
            top = [i for s, i in sorted(rel, key=lambda x: (-x[0], x[1])) if s > 0]
            seen = set(top)
            rest = [rest[i] for i in top] + [r for i, r in enumerate(rest) if i not in seen]
        out, used = [], 0
        for r in (pick + rest)[:NOTES_IN_PROMPT]:
            line = f"- {'(team) ' if r['agent_id'] is None else ''}{r['text']}"
            if used + len(line) > NOTES_CHARS: break
            out.append(line); used += len(line)
        return "\n".join(out)

    # ---------- outcomes, recorded as they happen ----------
    def _engineer_run(self, tid):
        return self.db.q("SELECT * FROM ml_runs WHERE task_id=? AND kind='engineer' ORDER BY created DESC LIMIT 1", (tid,), one=True) if tid else None

    def _record(self, r, kind, value, detail, tid=None):
        if not r: return
        self.db.q("INSERT INTO ml_outcomes (run, agent_id, version, flow_id, task_id, kind, value, detail, ts) VALUES (?,?,?,?,?,?,?,?,?)",
                  (r["run"], r["agent_id"], r["version"], r["flow_id"], tid or r["task_id"], kind, None if value is None else str(value), _clip(detail, 1000), time.time()))
        ev = getattr(self.w, "evolve", None)  # mining_evolve.py: a promoted version under watch is kept or rolled back on these
        if ev:
            try: ev.recorded(r["agent_id"])
            except Exception as e:  # noqa: BLE001 - never stops the work
                import logging; logging.getLogger("scout.mining.loadout").warning("evolve recorded: %s", e)

    def remember(self, fid, aid, text, tid=None, source="auto"):
        if source == "auto" and self.db.q("SELECT 1 FROM ml_memory WHERE flow_id=? AND agent_id IS ? AND text=?", (fid, aid, _clip(text, 1500)), one=True): return
        self.db.q("INSERT INTO ml_memory (flow_id, agent_id, text, source, task_id, created) VALUES (?,?,?,?,?,?)", (fid, aid, _clip(text, 1500), source, tid, time.time()))
        if aid and source == "auto":
            self.db.q(f"""DELETE FROM ml_memory WHERE flow_id=? AND agent_id=? AND source='auto' AND id NOT IN
                          (SELECT id FROM ml_memory WHERE flow_id=? AND agent_id=? AND source='auto' ORDER BY id DESC LIMIT {AUTO_NOTES_KEPT})""", (fid, aid, fid, aid))

    def outcome(self, kind, fid, t=None, run=None, value=None, detail=""):
        """Called by the Workflow as the work goes. run: the run that just ended (plan, engineer, review); otherwise the outcome
        belongs to the task's last engineer run."""
        tid = t["id"] if t else None
        title = t["title"] if t else ""
        this = self.db.q("SELECT * FROM ml_runs WHERE run=?", (run,), one=True) if run else None
        eng = self._engineer_run(tid)
        if kind == "planned":
            self._record(this, kind, value, detail)
        elif kind == "approved":  # value: (kept, proposed, dropped titles)
            kept, proposed, gone = value
            plan = self.db.q("SELECT * FROM ml_runs WHERE flow_id=? AND kind='plan' ORDER BY created DESC LIMIT 1", (fid,), one=True)
            self._record(plan, kind, f"{kept}/{proposed}", "; ".join(gone))
            if plan and proposed:
                self.remember(fid, plan["agent_id"], f"The user kept {kept} of {proposed} planned tasks" + (f"; dropped: {'; '.join(gone)[:600]}" if gone else "."))
        elif kind in ("run_failed", "no_change"):
            self._record(this, kind, None, detail, tid)
            if this and kind == "run_failed": self.remember(fid, this["agent_id"], f"Your run on “{title}” stopped: {_clip(detail, 300)}", tid)
        elif kind == "review":  # value: approve / changes; the verdict counts for the reviewer's run and the engineer's
            self._record(this, kind, value, detail, tid)
            self._record(eng, kind, value, detail, tid)
            if eng and value == "changes" and detail: self.remember(fid, eng["agent_id"], f"The review of “{title}” asked for changes: {_clip(detail, 700)}", tid)
        elif kind == "check":  # value: pass / fail
            self._record(eng, kind, value, detail, tid)
            if eng and value == "fail": self.remember(fid, eng["agent_id"], f"The check {_clip(detail, 500)} failed on “{title}”: look for the cause first next time.", tid)
        elif kind == "eval":  # value: eval tasks solved minus the base's, on the tasks both ran; for the engineer and the plan it came from
            self._record(eng, kind, value, detail, tid)
            plan = self.db.q("SELECT * FROM ml_runs WHERE run=?", (t["plan_run"],), one=True) if t and t.get("plan_run") else None
            self._record(plan, kind, value, f"“{title}”: {detail}", tid)
            if eng: self.remember(fid, eng["agent_id"], f"The eval of your work on “{title}” {detail}." + (" Find out why before changing that code again." if "; lost" in detail else ""), tid)
        elif kind in ("merged", "sent_back", "dropped"):
            self._record(eng, kind, value, detail, tid)
            if not eng: return
            if kind == "sent_back": self.remember(fid, eng["agent_id"], f"The user sent “{title}” back: {_clip(detail, 700)}", tid)
            first = re.split(r"(?<=[.!?])\s|\n", (detail or "").strip(), maxsplit=1)[0]  # the engineer's summary: its first sentence
            if kind == "merged": self.remember(fid, eng["agent_id"], f"Merged: “{title}”" + (f". What worked: {_clip(first, 300)}" if first else ""), tid)
            if kind == "dropped": self.remember(fid, eng["agent_id"], f"The user dropped “{title}”: don't take that approach again unless asked.", tid)

    # ---------- scores ----------
    def scores(self, a):
        rows = self.db.q("""SELECT v.n, v.note, v.source, v.created, v.snap,
                                   (SELECT COUNT(*) FROM ml_runs r WHERE r.agent_id=v.agent_id AND r.version=v.n) AS runs
                            FROM ml_versions v WHERE v.agent_id=? ORDER BY v.n DESC""", (a["id"],))
        outs = self.db.q("SELECT version, kind, value, run FROM ml_outcomes WHERE agent_id=?", (a["id"],))
        costs = self.db.q("""SELECT r.version, m.status, m.cost FROM ml_runs r JOIN mb_runs m ON m.run=r.run WHERE r.agent_id=?""", (a["id"],))
        out = []
        for v in rows:
            o = [x for x in outs if x["version"] == v["n"]]
            c = [x for x in costs if x["version"] == v["n"]]
            count = lambda k, val=None: sum(1 for x in o if x["kind"] == k and (val is None or x["value"] == val))
            finished = [x for x in c if x["status"] not in ("queued", "running")]
            s = {"version": v["n"], "note": v["note"], "source": v["source"], "created": v["created"], "snap": json.loads(v["snap"]), "runs": v["runs"],
                 "failed": sum(1 for x in finished if x["status"] != "done"), "cost": round(sum(x["cost"] or 0 for x in c), 4),
                 "approve": count("review", "approve"), "changes": count("review", "changes"), "check_pass": count("check", "pass"), "check_fail": count("check", "fail"),
                 "merged": count("merged"), "sent_back": count("sent_back"), "dropped": count("dropped"), "no_change": count("no_change"), "plans": count("planned"),
                 "kept": sum(int(x["value"].split("/")[0]) for x in o if x["kind"] == "approved" and x["value"]),
                 "proposed": sum(int(x["value"].split("/")[1]) for x in o if x["kind"] == "approved" and x["value"])}
            ev = [int(x["value"]) for x in o if x["kind"] == "eval" and re.fullmatch(r"-?\d+", x["value"] or "")]
            s.update(eval_up=sum(1 for x in ev if x > 0), eval_same=sum(1 for x in ev if x == 0), eval_down=sum(1 for x in ev if x < 0), eval_net=sum(ev))
            s["avg_cost"] = round(s["cost"] / len(finished), 4) if finished else None
            s["score"], s["basis"] = self._score(a["role"], s, len(finished))
            out.append(s)
        return out

    @staticmethod
    def _score(role, s, finished):
        """0–100 from what's known, and how many outcomes it rests on (None under 3: too little to compare). The eval against the
        base weighs most: it's what the competition scores; a change that keeps the score counts half."""
        parts = []  # (weight, rate, n)
        rate = lambda good, bad: (good / (good + bad), good + bad) if good + bad else None
        evals = s["eval_up"] + s["eval_same"] + s["eval_down"]
        ev = ((s["eval_up"] + s["eval_same"] / 2) / evals, evals) if evals else None
        if role == "engineer":
            for w, r in ((50, ev), (20, rate(s["check_pass"], s["check_fail"])), (15, rate(s["merged"], s["dropped"] + s["sent_back"])), (10, rate(s["approve"], s["changes"]))):
                if r: parts.append((w, *r))
        elif role == "reviewer":
            r = rate(s["approve"] + s["changes"], 0)
            if r: parts.append((10, *r))
        elif role == "director":
            for w, r in ((40, ev), (50, rate(s["kept"], s["proposed"] - s["kept"]))):
                if r: parts.append((w, *r))
        if finished: parts.append((5 if role == "engineer" else 10, (finished - s["failed"]) / finished, finished))
        n = sum(p[2] for p in parts)
        if n < 3: return None, n
        return round(100 * sum(w * r for w, r, _ in parts) / sum(w for w, _, _ in parts)), n

    # ---------- suggestions ----------
    def suggest(self, a, lo, sc, uid):
        """Advisory changes from the agent's scores: each is a partial loadout you can apply (a new version) or ignore."""
        cur = sc[0] if sc else None
        skills, mcp = self.resolved(a, uid, lo)
        has = {s["name"] for s in skills}
        out = []
        add = lambda key, title, why, change: out.append({"id": f"{a['id']}-{key}", "agent": a["id"], "title": title, "why": why, "change": change})
        with_skill = lambda n: {"skills": lo["skills"] + [n]}
        if lo["default"]:
            add("template", "Running on the role template", f"{a['name']} has no loadout of its own yet: it runs on the {a['role']} template. Save one to start tracking your changes.", {})
        if not cur: return out
        if a["role"] in ("engineer", "director") and cur["eval_down"] >= 2 and cur["eval_down"] > cur["eval_up"] and "eval-first" not in has:
            add("evalfirst", "Add the eval-first skill", f"{cur['eval_down']} of version {cur['version']}'s {'tasks' if a['role'] == 'engineer' else 'planned tasks'} lost eval tasks against the base, {cur['eval_up']} gained.", with_skill("eval-first"))
        if a["role"] == "engineer":
            if cur["check_fail"] >= 2 and cur["check_fail"] >= cur["check_pass"]:
                if "test-aware" not in has: add("test", "Add the test-aware skill", f"Checks failed {cur['check_fail']} times against {cur['check_pass']} passes on version {cur['version']}.", with_skill("test-aware"))
                elif a["model"] != "opus": add("opus", "Try opus", f"Checks still fail more often than they pass ({cur['check_fail']}/{cur['check_pass'] + cur['check_fail']}) with test-aware on.", {"model": "opus"})
            if cur["sent_back"] + cur["changes"] >= 2 and "review-checklist" not in has:
                add("selfreview", "Let it review itself first", f"Sent back {cur['sent_back']} times and asked for changes {cur['changes']} times: the review checklist catches the same issues before hand-off.", with_skill("review-checklist"))
            if cur["no_change"] >= 2: add("effort", "Raise effort", f"{cur['no_change']} runs ended without changing a file.", {"effort": "high"})
        if a["role"] == "reviewer":
            rev = cur["approve"] + cur["changes"]
            if rev >= 5 and cur["changes"] == 0 and a["model"] == "opus":
                add("cheaper", "Try sonnet", f"Approved all {rev} reviews on opus: a cheaper model may do the same.", {"model": "sonnet"})
        if a["role"] == "director" and cur["proposed"] >= 6 and cur["kept"] / cur["proposed"] < 0.5:
            if "task-splitting" not in has: add("split", "Add the task-splitting skill", f"You kept {cur['kept']} of {cur['proposed']} proposed tasks.", with_skill("task-splitting"))
            elif lo["memory"] != "team": add("memory", "Let it read the team's notes", f"You kept {cur['kept']} of {cur['proposed']} proposed tasks: its notes say which ones you dropped.", {"memory": "team"})
        failed = cur["failed"]
        if failed >= 2 and failed >= cur["runs"] / 2:
            budget = round(min(5.0, (lo["budget"] or 2.0) * 1.5), 1)
            add("budget", "Raise its budget per run", f"{failed} of {cur['runs']} runs on version {cur['version']} stopped with an error; when it's the budget cap, more room helps.", {"budget": budget})
        if lo["memory"] == "off" and cur["sent_back"] + cur["check_fail"] >= 1:
            add("mem", "Switch its memory on", "It was sent back or failed a check, and with memory off it won't see why next time.", {"memory": "own"})
        if len(sc) > 1 and sc[0]["score"] is not None and sc[1]["score"] is not None and sc[0]["score"] < sc[1]["score"] - 15:
            add("rollback", f"Go back to version {sc[1]['version']}", f"Version {sc[0]['version']} scores {sc[0]['score']}, version {sc[1]['version']} scored {sc[1]['score']}.", {"restore": sc[1]["version"]})
        return out

    # ---------- memory ----------
    def add_note(self, me, fid, b: NoteIn):
        f = self.bench._flow(me, fid)
        if b.agent is not None:
            a = self.bench._agent(b.agent)
            if not a or a["flow_id"] != fid: raise HTTPException(404, "There's no such agent on this team.")
        self.remember(fid, b.agent, b.text.strip(), source="you")
        return self.view(me, f["id"])

    def patch_note(self, me, nid, b: NotePatch):
        n = self.db.q("SELECT * FROM ml_memory WHERE id=?", (nid,), one=True)
        if not n: raise HTTPException(404, "There's no such note.")
        f = self.bench._flow(me, n["flow_id"])
        kw = {}
        if b.text is not None: kw["text"] = b.text.strip()
        if b.team is True: kw["agent_id"] = None
        if kw: self.db.q(f"UPDATE ml_memory SET {', '.join(f'{k}=?' for k in kw)}, source='you' WHERE id=?", (*kw.values(), nid))
        return self.view(me, f["id"])

    def delete_note(self, me, nid):
        n = self.db.q("SELECT * FROM ml_memory WHERE id=?", (nid,), one=True)
        if not n: raise HTTPException(404, "There's no such note.")
        f = self.bench._flow(me, n["flow_id"])
        self.db.q("DELETE FROM ml_memory WHERE id=?", (nid,))
        return self.view(me, f["id"])

    # ---------- the page ----------
    def view(self, me, fid):
        f = self.bench._flow(me, fid)
        uid = f["user_id"]
        feats, offered, up = self._offered()
        agents = []
        for a in self.bench._team(fid):
            lo = self._row(a)
            sc = self.scores(a)
            skills, mcp = self.resolved(a, uid, lo)
            agents.append({"id": a["id"], "name": a["name"], "role": a["role"], "model": a["model"], "instructions": a["instructions"] or "", "on": bool(a["on_team"]),
                           "loadout": lo, "resolved": {"skills": [s["name"] for s in skills], "mcp": mcp}, "scores": sc,
                           "version": sc[0]["version"] if sc else None, "suggestions": self.suggest(a, lo, sc, uid),
                           "notes": self.db.q("SELECT COUNT(*) AS n FROM ml_memory WHERE flow_id=? AND agent_id=?", (fid, a["id"]), one=True)["n"]})
        runs = self.db.q("""SELECT r.run, r.agent_id, r.version, r.kind, r.applied, r.created, m.label, m.status, m.cost FROM ml_runs r
                            LEFT JOIN mb_runs m ON m.run=r.run WHERE r.flow_id=? ORDER BY r.created DESC LIMIT 40""", (fid,))
        for r in runs: r["applied"] = _j(r["applied"], {})
        imp = getattr(self.w, "improve", None)  # mining_improve.py: proposals to improve engineers, tested on the eval
        return {"flow": fid, "improve": imp.view(f) if imp else None, "agents": agents, "skills": list(self._skills(uid).values()), "plugins": list(self._plugins(uid).values()),
                "mcp": list(offered.values()), "features": sorted(feats), "connected": up, "templates": TEMPLATES, "efforts": EFFORTS, "memory": MEMORY,
                "models": self.bench_models(), "runs": runs,
                "notes": self.db.q("SELECT * FROM ml_memory WHERE flow_id=? ORDER BY id DESC LIMIT 300", (fid,))}


def build(work, require):
    r = APIRouter(prefix="/api/mining/loadout")
    gate = work.m.hub.gate if work.m.hub else (lambda me: me)
    user = lambda req: gate(require(req))
    lo = Loadouts(work)
    r.state = {"loadout": lo}

    @r.get("/flows/{fid}")
    def view(fid: int, req: Request): return lo.view(user(req), fid)

    @r.put("/agents/{aid}")
    def save(aid: int, body: LoadoutIn, req: Request): return lo.save(user(req), aid, body)

    @r.post("/agents/{aid}/template")
    def template(aid: int, req: Request): return lo.template(user(req), aid)

    @r.post("/agents/{aid}/restore")
    def restore(aid: int, body: RestoreIn, req: Request): return lo.restore(user(req), aid, body)

    @r.post("/skills")
    def add_skill(body: SkillIn, req: Request): return lo.save_skill(user(req), body)

    @r.put("/skills/{sid}")
    def edit_skill(sid: int, body: SkillIn, req: Request): return lo.save_skill(user(req), body, sid)

    @r.delete("/skills/{sid}")
    def delete_skill(sid: int, req: Request): return lo.delete_skill(user(req), sid)

    @r.post("/plugins")
    def add_plugin(body: PluginIn, req: Request): return lo.save_plugin(user(req), body)

    @r.put("/plugins/{pid}")
    def edit_plugin(pid: int, body: PluginIn, req: Request): return lo.save_plugin(user(req), body, pid)

    @r.delete("/plugins/{pid}")
    def delete_plugin(pid: int, req: Request): return lo.delete_plugin(user(req), pid)

    @r.post("/flows/{fid}/notes")
    def add_note(fid: int, body: NoteIn, req: Request): return lo.add_note(user(req), fid, body)

    @r.patch("/notes/{nid}")
    def patch_note(nid: int, body: NotePatch, req: Request): return lo.patch_note(user(req), nid, body)

    @r.delete("/notes/{nid}")
    def delete_note(nid: int, req: Request): return lo.delete_note(user(req), nid)

    return r
