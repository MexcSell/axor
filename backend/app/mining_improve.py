"""Competition teams, improvements: when an engineer's work loses eval tasks, the Improvement Engineer proposes a change to its
loadout, and a trial measures the change on the same eval before you decide (mining_bench.py runs the Workflow,
mining_loadout.py keeps the loadouts, mining_lab.py scores the evals).

- A proposal comes from one read-only run on the AXoR Workbench (Claude Code, no loadout of its own). It reads the engineer's
  instructions, skills and model, the task, what the reviewer and you said, the diff, and which eval tasks the work gained
  and lost against the base it started from. It names the root cause in the loadout (not bad luck) and the smallest change:
  new instructions, skills from the library to add or drop, another model; or says no loadout change would have helped.
  It starts on its own when a task's eval loses tasks against its own base (unless you switch that off for the team), or
  when you ask from an engineer's card. One open proposal per engineer at a time.
- A trial gives the task it was diagnosed on, and up to four held-out tasks it never saw, to the candidate (the engineer
  with the change; nothing is saved) from each task's own starting commit, then runs the same scored check on each
  candidate branch. The current version runs each task too, unless the task's own eval stands for it: written by this
  version of this engineer, of the branch as it stands. Held-out tasks are other started tasks of the team (not dropped),
  this engineer's with a reusable eval first, then its others, then anyone's; they're picked when the trial starts, so
  "Test again" picks again. A held-out task whose run or eval failed is left out (and named); the trial fails only when
  the diagnosed task's does.
- The margin rule: the candidate is better only when it solves at least `margin` more eval tasks over all the trial's
  tasks and none fewer on the held-out ones (it was tuned on the diagnosed task, so a win there alone is partly fitting).
  Worse when it solves fewer in total or on the held-out tasks; else no better.
- Nothing changes until you decide: promote a candidate that measured better (it becomes the engineer's next loadout
  version) or reject it. The trial's branches are deleted once you decide. A proposal that wasn't tested can't be applied
  (Owner decision K-21): a person who wants the change anyway edits the loadout in Loadouts, as their own versioned edit.

Engineers only: theirs is the work the eval measures. Administrators only, like the Workflow.
"""
import json, logging, secrets, time, urllib.parse

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import agent_core
from .mining import _clip
from .mining_bench import BUDGET, MODELS
from .mining_lab import versus
from .mining_loadout import LoadoutIn

log = logging.getLogger("scout.mining.improve")
MODEL, DIAGNOSIS_USD = "sonnet", 0.8
OPEN = ("diagnosing", "proposed", "testing", "better")  # an engineer with one of these gets no new proposal
SETTLED = ("better", "same", "worse", "trial_failed")
DIFF_CHARS, SUMMARY_CHARS, LIST = 24000, 3000, 30
HELD, HELD_MAX, MARGIN, MARGIN_MAX, SCAN = 2, 4, 2, 20, 40  # held-out tasks per trial (default, most), eval tasks to win by, tasks looked at
WHY = """You are the Improvement Engineer of this team. Find out why {name}'s work on the task below went wrong, in what {name}
brings to every run: its instructions, its skills, its model. Not bad luck, not the task being hard: something in the loadout
that, changed, would have avoided it (a missing check, a wrong habit, an unclear priority, a skill it lacked). You can read the
folder (read only) to understand the code it changed. Then propose the smallest change: its full new instructions (its current
ones with the change applied and nothing else rewritten; under 2000 characters), skills from the library to add or drop, or
another model. The change is tested on this same task and eval before anyone applies it, so make it specific. If no change to
the loadout would have helped (the task needed a tool it can't have, the eval is noisy, the plan was wrong), say so with
fixable false."""


class AskIn(BaseModel):
    note: str = Field("", max_length=1500)
    task: int | None = None


class TestIn(BaseModel):
    check: str | None = Field(None, max_length=60)
    held: int = Field(HELD, ge=0, le=HELD_MAX)  # held-out tasks besides the diagnosed one
    margin: int = Field(MARGIN, ge=1, le=MARGIN_MAX)


class DecideIn(BaseModel):
    decision: str = Field(..., max_length=12)  # promote, reject, cancel ("apply", untested, is refused: K-21)


class SettingIn(BaseModel):
    improve: str = Field(..., max_length=8)  # auto: propose when a task's eval loses tasks; ask: only when you ask; self: also test, promote, watch (mining_evolve.py)


def _j(s, d=None): return json.loads(s) if s else ({} if d is None else d)
def plural(n, w): return f"{n} {w}{'' if n == 1 else 's'}"
def _signed(d): return f"+{d}" if d > 0 else f"−{-d}" if d < 0 else "±0"

def trial_status(total, held_net, has_held, margin):
    """The margin rule: better needs `margin` more eval tasks over all the trial's tasks and none fewer on the held-out ones."""
    if total < 0 or (has_held and held_net < 0): return "worse"
    return "better" if total >= margin else "same"


class Improve:
    def __init__(self, work):
        self.w, self.db = work, work.db
        q = self.db.q
        q("""CREATE TABLE IF NOT EXISTS mb_improvements (id INTEGER PRIMARY KEY AUTOINCREMENT, flow_id INTEGER, agent_id INTEGER, task_id INTEGER,
             check_id TEXT, base_version INTEGER, trigger TEXT, note TEXT, run TEXT, status TEXT, root_cause TEXT, change TEXT, candidate TEXT,
             trial TEXT, result TEXT, cost REAL DEFAULT 0, version INTEGER, decided_by TEXT, created REAL, updated REAL, margin INTEGER)""")
        q("""CREATE TABLE IF NOT EXISTS mb_trials (id INTEGER PRIMARY KEY AUTOINCREMENT, improvement_id INTEGER, task_id INTEGER, held INTEGER DEFAULT 0,
             arm TEXT, slug TEXT, run TEXT, check_run TEXT, experiment INTEGER, head TEXT, status TEXT, error TEXT, created REAL)""")
        q("CREATE INDEX IF NOT EXISTS mb_improvements_f ON mb_improvements (flow_id, id)")
        q("CREATE INDEX IF NOT EXISTS mb_trials_i ON mb_trials (improvement_id)")
        if "improve" not in {c["name"] for c in q("PRAGMA table_info(mb_flows)")}:
            q("ALTER TABLE mb_flows ADD COLUMN improve TEXT DEFAULT 'auto'")
        if "margin" not in {c["name"] for c in q("PRAGMA table_info(mb_improvements)")}:
            q("ALTER TABLE mb_improvements ADD COLUMN margin INTEGER")
        have = {c["name"] for c in q("PRAGMA table_info(mb_trials)")}  # older trials ran on the diagnosed task only
        for col in ("task_id INTEGER", "held INTEGER DEFAULT 0"):
            if col.split()[0] not in have: q(f"ALTER TABLE mb_trials ADD COLUMN {col}")
        work.improve = self

    @property
    def bench(self):
        b = getattr(self.w, "bench", None)
        if not b: raise HTTPException(503, "The Workflow isn't loaded.")
        return b

    @property
    def lo(self):
        lo = getattr(self.w, "loadout", None)
        if not lo: raise HTTPException(503, "Loadouts aren't loaded.")
        return lo

    @property
    def lab(self):
        lab = getattr(self.w, "lab", None)
        if not lab: raise HTTPException(503, "The Lab isn't loaded.")
        return lab

    def _row(self, me, iid):
        imp = self.db.q("SELECT * FROM mb_improvements WHERE id=?", (iid,), one=True)
        if not imp: raise HTTPException(404, "There's no such proposal.")
        return imp, self.bench._flow(me, imp["flow_id"])

    def _set(self, iid, **kw):
        kw["updated"] = time.time()
        self.db.q(f"UPDATE mb_improvements SET {', '.join(f'{k}=?' for k in kw)} WHERE id=?", (*kw.values(), iid))

    def _start(self, f, mark, kind, who, label, body):
        """A run on the workbench, recorded under its own kind so the Workflow hands it back here when it ends."""
        r = self.bench.call(f"/repos/{f['repo']}/runs", {"kind": kind, "who": who, "title": label, **body})
        self.db.q("INSERT INTO mb_runs (run, flow_id, task_id, kind, who, label, status, started) VALUES (?,?,?,?,?,?,?,?)",
                  (r["id"], f["id"], None, mark, who, _clip(label, 200), r["status"], time.time()))
        agent_core.record("workflow", f["user_id"], mark, f"mb:{r['id']}", title=label)
        return r["id"]

    def _evolve(self, name, *a):
        """mining_evolve.py, when the team improves on its own (setting "self"): it never stops the work here."""
        ev = getattr(self.w, "evolve", None)
        if not ev: return None
        try: return getattr(ev, name)(*a)
        except Exception as e:  # noqa: BLE001
            log.warning("evolve %s: %s", name, e)

    def _flow_row(self, fid):
        return self.db.q("SELECT * FROM mb_flows WHERE id=?", (fid,), one=True)

    def _diff(self, f, slug, base):
        return self.bench.call("/repos/{}/diff?{}".format(f["repo"], urllib.parse.urlencode({"base": base, "slug": slug})))

    # ---------- proposals ----------
    def regressed(self, t, c):
        """The Workflow's hook: a task's eval lost tasks against the base it started from."""
        f = self._flow_row(t["flow_id"])
        if not f or (f["improve"] or "auto") not in ("auto", "self"): return
        eng = self.lo._engineer_run(t["id"])  # the version that wrote the work, which may not be the task's engineer by now
        a = self.bench._agent(eng["agent_id"] if eng else t["engineer_id"])
        if not a or a["role"] != "engineer" or self._open(a["id"]): return
        e = self.db.q("SELECT check_id FROM mb_experiments WHERE id=?", (c["score"]["id"],), one=True)
        self._propose(f, a, t, "eval", e["check_id"] if e else None)

    def _open(self, aid):
        return self.db.q(f"SELECT id FROM mb_improvements WHERE agent_id=? AND status IN ({','.join('?' * len(OPEN))})", (aid, *OPEN), one=True)

    def ask(self, me, aid, b: AskIn):
        a = self.bench._agent(aid)
        if not a: raise HTTPException(404, "There's no such agent.")
        f = self.bench._flow(me, a["flow_id"])
        if a["role"] != "engineer": raise HTTPException(400, "Proposals are for engineers: theirs is the work the eval measures.")
        if self._open(aid): raise HTTPException(409, f"{a['name']} already has an open proposal: decide on it first.")
        t = self.db.q("SELECT * FROM mb_tasks WHERE id=? AND flow_id=?", (b.task, f["id"]), one=True) if b.task else self._worst(f, a)
        if not t: raise HTTPException(409, f"Nothing to learn from yet: none of {a['name']}'s work lost eval tasks, was sent back, dropped, failed a check or was asked to change.")
        if not t["base"]: raise HTTPException(409, "That task never started, so there's no work to learn from.")
        scored = next((k for k, x in _j(t["checks"]).items() if x.get("score")), None)
        self._propose(f, a, t, "you", scored, b.note.strip())
        return self.lo.view(me, f["id"])

    def _worst(self, f, a):
        """The newest task where the agent's work went wrong: an eval that lost tasks, a send-back, a drop, a failed check, a review asking for changes."""
        row = self.db.q("""SELECT o.task_id FROM ml_outcomes o WHERE o.flow_id=? AND o.agent_id=? AND o.task_id IS NOT NULL AND (
                             (o.kind='eval' AND (o.value LIKE '-%' OR o.detail LIKE '%; lost %')) OR o.kind IN ('sent_back','dropped')
                             OR (o.kind='check' AND o.value='fail') OR (o.kind='review' AND o.value='changes')) ORDER BY o.id DESC LIMIT 1""", (f["id"], a["id"]), one=True)
        return self.db.q("SELECT * FROM mb_tasks WHERE id=?", (row["task_id"],), one=True) if row else None

    def _propose(self, f, a, t, trigger, check=None, note=""):
        lo = self.lo._row(a)
        skills, _ = self.lo.resolved(a, f["user_id"], lo)
        has = {s["name"] for s in skills}
        lib = [s for s in self.lo._skills(f["user_id"]).values() if s["name"] not in has]
        outs = self.db.q("SELECT kind, value, detail FROM ml_outcomes WHERE task_id=? ORDER BY id", (t["id"],))
        rv = _j(t["review"], None)
        try: d = self._diff(f, t["slug"], t["base"]) if t["slug"] and t["base"] and t["status"] != "dropped" else None
        except HTTPException: d = None
        sc = (self.lo.scores(a) or [{}])[0]
        prompt = [self.bench._context(f), "", WHY.format(name=a["name"]), "",
                  f"## {a['name']} now (engineer, version {sc.get('version', '?')})", f"Model: {a['model']}. Effort: {lo['effort'] or 'default'}. Memory: {lo['memory']}.",
                  "Instructions:", "<instructions>", a["instructions"] or "(none)", "</instructions>",
                  "Skills: " + ("; ".join(f"{s['name']} ({s['description']})" for s in skills) or "none"),
                  "Skills in the library it doesn't have: " + ("; ".join(f"{s['name']} ({s['description']})" for s in lib) or "none"),
                  f"Its record on this version: {sc.get('runs', 0)} runs; evals against the base {sc.get('eval_up', 0)} up, {sc.get('eval_same', 0)} same, {sc.get('eval_down', 0)} down; "
                  f"checks {sc.get('check_pass', 0)} passed, {sc.get('check_fail', 0)} failed; {sc.get('merged', 0)} merged, {sc.get('sent_back', 0)} sent back, {sc.get('dropped', 0)} dropped.",
                  "", f"## The task: {t['title']} ({t['status']})", t["detail"] or "",
                  f"{a['name']} said when it finished:", _clip(t["summary"] or "(nothing)", SUMMARY_CHARS)]
        if rv: prompt += [f"The reviewer: {rv.get('verdict')}. {rv.get('summary') or ''}"] + [f"- {i}" for i in rv.get("issues") or []]
        if outs: prompt += ["What happened to the work:"] + [f"- {o['kind']}" + (f" ({o['value']})" if o["value"] and o["kind"] != "eval" else "") + f": {_clip(o['detail'] or '', 600)}"
                                                             for o in outs if o["detail"] or o["value"]]
        if note: prompt += ["", f"The user adds: {note}"]
        if d and d.get("patch"): prompt += ["", f"The diff it made (branch {d.get('branch')}):", _clip(d["patch"], DIFF_CHARS)]
        schema = {"type": "object", "required": ["fixable", "root_cause", "change", "instructions", "add_skills", "drop_skills", "model"], "properties": {
            "fixable": {"type": "boolean", "description": "false when no change to the loadout would have helped"},
            "root_cause": {"type": "string", "description": "One or two sentences: what in the loadout led to it."},
            "change": {"type": "string", "description": "The change in one sentence."},
            "instructions": {"type": "string", "description": "The full new instructions, under 2000 characters; empty to keep the current ones."},
            "add_skills": {"type": "array", "items": {"type": "string", **({"enum": [s["name"] for s in lib]} if lib else {})}},
            "drop_skills": {"type": "array", "items": {"type": "string", **({"enum": sorted(has)} if has else {})}},
            "model": {"type": "string", "enum": ["", *MODELS], "description": "Another model, or empty to keep it."}}}
        label = f"Why {a['name']}'s “{t['title']}” went wrong"
        rid = self._start(f, "improve", "plan", "Improvement Engineer", label,
                          {"prompt": "\n".join(prompt), "model": MODEL, "budget_usd": min(DIAGNOSIS_USD, f["budget"] or DIAGNOSIS_USD), "schema": schema})
        now = time.time()
        self.db.q("""INSERT INTO mb_improvements (flow_id, agent_id, task_id, check_id, base_version, trigger, note, run, status, created, updated)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (f["id"], a["id"], t["id"], check, self.lo._version(a), trigger, note or None, rid, "diagnosing", now, now))
        why = "its eval lost tasks" if trigger == "eval" else "you asked"
        self.bench._say(f["id"], "run", f"The Improvement Engineer is looking at {a['name']}'s “{t['title']}” ({why})", t["id"])

    def _diagnosed(self, imp, run):
        f = self._flow_row(imp["flow_id"])
        a = self.bench._agent(imp["agent_id"])
        out = run.get("structured") if run["status"] == "done" else None
        cost = run.get("cost") or 0
        if not out or not a:
            self._set(imp["id"], status="failed", cost=cost, result=_clip(run.get("error") or ("The engineer is gone." if not a else "The diagnosis finished without an answer."), 600))
            return self.bench._say(imp["flow_id"], "error", f"The Improvement Engineer couldn't finish: {run.get('error') or run['status']}")
        lo = self.lo._row(a)
        skills, _ = self.lo.resolved(a, f["user_id"], lo)
        has, lib = {s["name"] for s in skills}, self.lo._skills(f["user_id"])
        cand = {}
        ins = str(out.get("instructions") or "").strip()
        if ins and ins != (a["instructions"] or "").strip(): cand["instructions"] = ins[:2000]
        add = [s for s in dict.fromkeys(out.get("add_skills") or []) if s in lib and s not in has]
        drop = [s for s in dict.fromkeys(out.get("drop_skills") or []) if s in has]
        if add: cand["add_skills"] = add
        if drop: cand["drop_skills"] = drop
        if out.get("model") in MODELS and out["model"] != a["model"]: cand["model"] = out["model"]
        root, change = _clip(out.get("root_cause"), 600), _clip(out.get("change"), 300)
        if not out.get("fixable") or not cand:
            self._set(imp["id"], status="nothing", cost=cost, root_cause=root, change=change, result="No loadout change would have helped: " + (root or "the cause lies elsewhere."))
            return self.bench._say(imp["flow_id"], "ok", f"The Improvement Engineer found no loadout change for {a['name']}: {root}", imp["task_id"])
        self._set(imp["id"], status="proposed", cost=cost, root_cause=root, change=change, candidate=json.dumps(cand))
        self.bench._say(imp["flow_id"], "wait", f"The Improvement Engineer proposes for {a['name']}: {change} Test it on the eval or decide in Loadouts → Improvements.", imp["task_id"])
        self._evolve("proposed", imp["flow_id"], imp["id"])

    # ---------- the candidate ----------
    def candidate(self, f, a, imp):
        """The agent and loadout with the proposal applied (nothing saved). A dropped skill that came in a plugin unpacks the plugin."""
        c, lo = _j(imp["candidate"]), self.lo._row(a)
        plugs = self.lo._plugins(f["user_id"])
        skills, plugins, drop = list(lo["skills"]), list(lo["plugins"]), set(c.get("drop_skills") or [])
        for p in list(plugins):
            inside = (plugs.get(p) or {}).get("skills") or []
            if drop & set(inside):
                plugins.remove(p); skills += [s for s in inside if s not in drop and s not in skills]
        skills = [s for s in skills if s not in drop] + [s for s in c.get("add_skills") or [] if s not in skills]
        return ({**a, "instructions": c.get("instructions") or a["instructions"], "model": c.get("model") or a["model"]},
                {**lo, "skills": skills, "plugins": plugins, "default": False})

    # ---------- trials ----------
    def test(self, me, iid, b: TestIn):
        imp, f = self._row(me, iid)
        if imp["status"] not in ("proposed", "same", "worse", "trial_failed"): raise HTTPException(409, "This proposal can't be tested now.")
        a = self.bench._agent(imp["agent_id"])
        if not a: raise HTTPException(409, "That engineer has left the team.")
        if self.lo._version(a) != imp["base_version"]: raise HTTPException(409, f"{a['name']}'s loadout changed since this was proposed (now version {self.lo._version(a)}): ask for a new proposal.")
        t = self.db.q("SELECT * FROM mb_tasks WHERE id=?", (imp["task_id"],), one=True)
        if not t or not t["base"]: raise HTTPException(409, "The task is gone, so there's nothing to test it on.")
        scored = {c["id"]: c for c in self.lab._scored(f)}
        check = b.check or imp["check_id"] or next(iter(scored), None)
        if check not in scored: raise HTTPException(409, "The folder has no scored check to measure it with: add an eval with \"results\" to the workbench's config.")
        held = self._held(f, imp, scored)[:b.held]
        self._clear(f, iid)
        cand, clo = self.candidate(f, a, imp)
        reused = 0
        try:
            for x, h in [(t, False)] + [(y, True) for y in held]:
                own = self._own(x, imp, check)
                if own:
                    reused += 1
                    self.db.q("INSERT INTO mb_trials (improvement_id, task_id, held, arm, experiment, head, status, created) VALUES (?,?,?,?,?,?,?,?)",
                              (iid, x["id"], int(h), "current", own["id"], own["head"], "reused", time.time()))
                else: self._arm(f, imp, x, a, None, "current", h)
                self._arm(f, imp, x, cand, clo, "candidate", h)
        except HTTPException:
            self._clear(f, iid)
            raise
        self._set(iid, status="testing", check_id=check, margin=b.margin, trial=None, result=None)
        n = 1 + len(held)
        what = f"the diagnosed task and {plural(len(held), 'held-out task')}" if held else "the diagnosed task only (no held-out task)"
        self.bench._say(f["id"], "run", f"{me['username']} is testing the proposal for {a['name']} on “{scored[check]['label']}”: {what}, "
                        f"{plural(2 * n - reused, 'engineer run')} and as many evals" + (f" ({reused} reused from the tasks' own evals)" if reused else ""), t["id"])
        return self.lo.view(me, f["id"])

    def _own(self, t, imp, check, eng=False):
        """The task's own eval on check, when it stands for the current version: this version of this engineer wrote the work,
        and the eval is of the branch as it stands (not one from before a send-back)."""
        if eng is False: eng = self.lo._engineer_run(t["id"])
        if not eng or eng["agent_id"] != imp["agent_id"] or eng["version"] != imp["base_version"]: return None
        run = (_j(t["checks"]).get(check) or {}).get("run")
        if not run: return None
        return self.db.q("SELECT * FROM mb_experiments WHERE task_id=? AND kind='task' AND check_id=? AND run=? AND status='done'", (t["id"], check, run), one=True)

    def _held(self, f, imp, scored):
        """Tasks the diagnosis never saw, best first: this engineer's with an eval that stands for the current version (cheapest),
        then its others, then anyone's; newest first within each. Each with the checks whose own eval it reuses."""
        rows = self.db.q("""SELECT * FROM mb_tasks WHERE flow_id=? AND id!=? AND base IS NOT NULL AND status NOT IN ('proposed','dropped')
                            ORDER BY id DESC LIMIT ?""", (f["id"], imp["task_id"], SCAN))
        out = []
        for t in rows:
            eng = self.lo._engineer_run(t["id"])
            mine = (eng["agent_id"] if eng else t["engineer_id"]) == imp["agent_id"]
            same = eng and mine and eng["version"] == imp["base_version"]  # else no eval of it can stand for the current version
            reuse = [c for c in scored if self._own(t, imp, c, eng)] if same else []
            out.append((0 if reuse else 1 if mine else 2, {**t, "reuse": reuse}))
        return [t for _, t in sorted(out, key=lambda x: x[0])]  # stable: newest first within a rank

    def plan(self, f, imp, scored):
        """What a trial would run, for the card: the diagnosed task and the held-out ones, each with the checks it reuses."""
        t = self.db.q("SELECT * FROM mb_tasks WHERE id=?", (imp["task_id"],), one=True)
        if not t: return None
        brief = lambda x: {"id": x["id"], "title": x["title"], "reuse": [c for c in scored if self._own(x, imp, c)] if "reuse" not in x else x["reuse"]}
        return {"seen": brief(t), "held": [brief(x) for x in self._held(f, imp, scored)[:HELD_MAX]]}

    def _arm(self, f, imp, t, a, lo, arm, held=False):
        slug = f"x{imp['id']}{arm[0]}-t{t['id']}-{secrets.token_hex(2)}"
        body = {"slug": slug, "base": t["base"], "prompt": self.bench._task_prompt(f, t, a, slug, t["base"]), "model": a["model"],
                "budget_usd": min(BUDGET["engineer"], f["budget"])}
        body = self.lo.apply(f, a, "engineer", body, t["id"], lo=lo)
        body.pop("_applied", None)  # a trial isn't a run of the agent's version: it stays out of its scores
        rid = self._start(f, "trial", "engineer", f"{a['name']} ({arm})", f"Trial #{imp['id']}, {arm}: {t['title']}", body)
        self.db.q("INSERT INTO mb_trials (improvement_id, task_id, held, arm, slug, run, status, created) VALUES (?,?,?,?,?,?,?,?)",
                  (imp["id"], t["id"], int(held), arm, slug, rid, "working", time.time()))

    def finished(self, r, run):
        """The Workflow's hook for every ended run: True when it was one of ours."""
        if r["kind"] == "improve":
            imp = self.db.q("SELECT * FROM mb_improvements WHERE run=?", (r["run"],), one=True)
            if imp and imp["status"] == "diagnosing": self._diagnosed(imp, run)
            return True
        if r["kind"] not in ("trial", "check"): return False
        arm = self.db.q("SELECT * FROM mb_trials WHERE run=? OR check_run=?", (r["run"], r["run"]), one=True)
        if not arm: return r["kind"] == "trial"
        imp = self.db.q("SELECT * FROM mb_improvements WHERE id=?", (arm["improvement_id"],), one=True)
        if not imp or imp["status"] != "testing": return True
        self._set(imp["id"], cost=(imp["cost"] or 0) + (run.get("cost") or 0))
        f = self._flow_row(imp["flow_id"])
        if r["kind"] == "trial": self._worked(f, imp, arm, run)
        else:
            e = self.db.q("SELECT * FROM mb_experiments WHERE id=?", (arm["experiment"],), one=True)
            ok = e and e["status"] == "done"
            self.db.q("UPDATE mb_trials SET status=?, error=? WHERE id=?", ("done" if ok else "failed", None if ok else _clip((e or {}).get("error") or run.get("error") or "The eval gave no score.", 600), arm["id"]))
        self._settle(f, imp)
        return True

    def _worked(self, f, imp, arm, run):
        """An arm's engineer run ended: eval its branch with the trial's check."""
        fail = lambda why: self.db.q("UPDATE mb_trials SET status='failed', error=? WHERE id=?", (_clip(why, 600), arm["id"]))
        if run["status"] != "done": return fail(f"The engineer stopped: {run.get('error') or run['status']}")
        t = self.db.q("SELECT * FROM mb_tasks WHERE id=?", (arm["task_id"] or imp["task_id"],), one=True)
        if not t: return fail("The task is gone.")
        try:
            d = self._diff(f, arm["slug"], t["base"])
            if not d.get("files"): return fail("The engineer changed no file.")
            ch = next((c for c in self.lab._scored(f) if c["id"] == imp["check_id"]), None)
            if not ch: return fail("The scored check is gone from the workbench's config.")
            rid = self._start(f, "check", "check", "Workbench", f"{ch['label']}: trial #{imp['id']}, {arm['arm']}", {"check": ch["id"], "slug": arm["slug"], "base": t["base"]})
        except HTTPException as e: return fail(f"Couldn't start the eval: {e.detail}")
        a = self.bench._agent(imp["agent_id"])
        eid = self.lab.trial(f, f"Trial #{imp['id']}: {(a or {}).get('name', '?')} {arm['arm']} on “{t['title']}”", rid, ch["id"], d.get("head"), t["base"])
        self.db.q("UPDATE mb_trials SET status='evaluating', check_run=?, experiment=?, head=? WHERE id=?", (rid, eid, d.get("head"), arm["id"]))

    def _settle(self, f, imp):
        """Every arm ended: compare the two versions task by task, then apply the margin rule over all tasks and the held-out ones."""
        rows = self.db.q("SELECT * FROM mb_trials WHERE improvement_id=? ORDER BY id", (imp["id"],))
        if any(x["status"] in ("working", "evaluating") for x in rows): return
        a = self.bench._agent(imp["agent_id"])
        name = (a or {}).get("name", "the engineer")
        tasks = {}
        for x in rows: tasks.setdefault(x["task_id"] or imp["task_id"], {"held": bool(x["held"]), "arms": {}})["arms"][x["arm"]] = x
        titles = {t["id"]: t["title"] for t in self.db.q(f"SELECT id, title FROM mb_tasks WHERE id IN ({','.join('?' * len(tasks))})", tuple(tasks))} if tasks else {}
        per, left_out, seen_bad = [], [], None
        for tid, g in tasks.items():
            arms, title = g["arms"], titles.get(tid, "a task that's gone")
            bad = [f"{k}: {x['error']}" for k, x in arms.items() if x["status"] == "failed"]
            ex = {k: self.db.q("SELECT * FROM mb_experiments WHERE id=?", (x["experiment"],), one=True) for k, x in arms.items()} if not bad else {}
            if not bad and set(arms) != {"current", "candidate"}: bad = ["a side never started"]
            if not bad and not all(ex.values()): bad = ["an eval was deleted from the Lab"]
            if bad:
                if not g["held"]: seen_bad = bad
                left_out.append(f"“{title}” ({'; '.join(bad)})")
                continue
            vs = versus(_j(ex["candidate"]["per_task"]), _j(ex["current"]["per_task"]))
            per.append({"task": tid, "title": title, "held": g["held"], "shared": vs["shared"], "candidate": vs["a"], "current": vs["b"],
                        "gained": vs["gained"][:20], "lost": vs["lost"][:20], "reused": arms["current"]["status"] == "reused",
                        "experiments": {k: e["id"] for k, e in ex.items()}})
        if seen_bad is not None or not per:
            why = " ".join(seen_bad or ["Nothing was scored."])
            self._set(imp["id"], status="trial_failed", result=_clip(f"The trial didn't finish on the diagnosed task: {why}", 800))
            return self.bench._say(f["id"], "error", f"The trial of the proposal for {name} didn't finish: {why[:300]}", imp["task_id"])
        margin = imp["margin"] or MARGIN
        net = lambda ps: sum(p["candidate"] - p["current"] for p in ps)
        held = [p for p in per if p["held"]]
        seen = next(p for p in per if not p["held"])
        total, held_net, planned = net(per), net(held), sum(1 for g in tasks.values() if g["held"])
        status = trial_status(total, held_net, bool(held), margin)
        if status == "better": verdict = "Better: it clears the margin" + (" and loses nothing on the held-out tasks." if held else ", but on the diagnosed task alone.") + " You can promote it."
        elif status == "worse": verdict = "Worse on the held-out tasks: it fixed what it was tuned on and lost elsewhere." if total >= 0 else "Worse: it solves fewer in total."
        else: verdict = f"No better: {_signed(total)} is under the margin of +{margin}."
        result = (f"Over {plural(len(per), 'task')}, the candidate solved {sum(p['candidate'] for p in per)} of {sum(p['shared'] for p in per)} eval tasks, "
                  f"the current version {sum(p['current'] for p in per)} ({_signed(total)}). On the diagnosed task {_signed(seen['candidate'] - seen['current'])}"
                  + (f"; on {plural(len(held), 'held-out task')} it never saw {_signed(held_net)}. " if held else
                     ". No held-out task " + ("finished. " if planned else "in this trial (you chose none). " if self._held(f, imp, [c["id"] for c in self.lab._scored(f)])
                                             else "was available: the team has no other started task. "))
                  + (f"Left out: {'; '.join(left_out)}. " if left_out else "") + verdict + " Each side was measured once per task: a hint, not proof.")
        trial = {"shared": sum(p["shared"] for p in per), "candidate": sum(p["candidate"] for p in per), "current": sum(p["current"] for p in per),
                 "net": total, "seen_net": seen["candidate"] - seen["current"], "held_net": held_net, "held_ran": len(held), "held_planned": planned,
                 "margin": margin, "tasks": per, "left_out": left_out, "gained": [g for p in per for g in p["gained"]][:20], "lost": [g for p in per for g in p["lost"]][:20],
                 "experiments": seen["experiments"], "reused": seen["reused"]}
        self._set(imp["id"], status=status, result=_clip(result, 1500), trial=json.dumps(trial))
        self.bench._say(f["id"], "ok" if status == "better" else "wait", f"Trial of the proposal for {name}: {_clip(result, 600)}", imp["task_id"])
        self._evolve("settled", f["id"], imp["id"], status)

    def _clear(self, f, iid):
        """Stops the trial's runs and deletes its branches."""
        for x in self.db.q("SELECT * FROM mb_trials WHERE improvement_id=?", (iid,)):
            for rid in (x["run"], x["check_run"]):
                if rid and x["status"] in ("working", "evaluating"):
                    try: self.bench.call(f"/runs/{rid}/stop", {})
                    except HTTPException: pass
            if x["slug"] and f:
                try: self.bench.call(f"/repos/{f['repo']}/drop", {"slug": x["slug"]})
                except HTTPException as e: log.warning("improve drop %s: %s", x["slug"], e.detail)
        self.db.q("DELETE FROM mb_trials WHERE improvement_id=?", (iid,))

    # ---------- your decision ----------
    def decide(self, me, iid, b: DecideIn):
        imp, f = self._row(me, iid)
        a = self.bench._agent(imp["agent_id"])
        if b.decision == "apply":  # Owner decision K-21 (2026-11-12), G5-5 L5.4b: an untested proposal is never applied as a promotion
            raise HTTPException(409, "A proposal that wasn't tested can't be applied any more. Test it and promote it; or, if you want the change anyway, "
                                     "edit the engineer's loadout yourself in Loadouts and say why: that is your own edit, versioned and audited.")
        if b.decision == "promote":
            if imp["status"] != "better": raise HTTPException(409, "Only a candidate that measured better can be promoted: test it first.")
            if not a: raise HTTPException(409, "That engineer has left the team.")
            if self.lo._version(a) != imp["base_version"]: raise HTTPException(409, f"{a['name']}'s loadout changed since this was proposed: ask for a new proposal.")
            cand, clo = self.candidate(f, a, imp)
            tag = ""
            self.lo.save(me, a["id"], LoadoutIn(model=cand["model"], instructions=cand["instructions"], skills=clo["skills"], plugins=clo["plugins"], mcp=clo["mcp"],
                                                memory=clo["memory"], effort=clo["effort"], budget=clo["budget"], note=_clip(f"Improvement #{iid}{tag}: {imp['change']}", 300), source="improvement"))
            self._clear(f, iid)
            self._set(iid, status="promoted", decided_by=me["username"], version=self.lo._version(self.bench._agent(a["id"])))
        elif b.decision == "reject":
            if imp["status"] in ("diagnosing", "testing"): raise HTTPException(409, "Wait for it to finish, or cancel the trial first.")
            self._clear(f, iid)
            self._set(iid, status="rejected", decided_by=me["username"])
            self.bench._say(f["id"], "ok", f"{me['username']} rejected the proposal for {(a or {}).get('name', 'an engineer')}", imp["task_id"])
        elif b.decision == "cancel":
            if imp["status"] == "diagnosing":  # also the way out when a diagnosis never came back
                try: self.bench.call(f"/runs/{imp['run']}/stop", {})
                except HTTPException: pass
                self._set(iid, status="failed", result="Diagnosis cancelled.")
            elif imp["status"] == "testing":
                self._clear(f, iid)
                self._set(iid, status="proposed", result="Trial cancelled.")
            else: raise HTTPException(409, "Nothing is running.")
        else: raise HTTPException(422, "Promote, apply, reject or cancel.")
        return self.lo.view(me, f["id"])

    def delete(self, me, iid):
        imp, f = self._row(me, iid)
        if imp["status"] in ("diagnosing", "testing"): raise HTTPException(409, "It's still running.")
        self._clear(f, iid)
        self.db.q("DELETE FROM mb_improvements WHERE id=?", (iid,))
        return self.lo.view(me, f["id"])

    def setting(self, me, fid, b: SettingIn):
        f = self.bench._flow(me, fid)
        if b.improve not in ("auto", "ask", "self"): raise HTTPException(422, "auto, ask or self.")
        self.db.q("UPDATE mb_flows SET improve=? WHERE id=?", (b.improve, fid))
        return self.lo.view(me, f["id"])

    def forget(self, fid):
        self._evolve("forget", fid)
        for imp in self.db.q("SELECT id FROM mb_improvements WHERE flow_id=?", (fid,)): self.db.q("DELETE FROM mb_trials WHERE improvement_id=?", (imp["id"],))
        self.db.q("DELETE FROM mb_improvements WHERE flow_id=?", (fid,))

    # ---------- the page (in Loadouts; what waits for you in the Workflow's "What happens now") ----------
    def waiting(self, f):
        rows = self.db.q("""SELECT i.id, i.status, i.change, i.result, a.name agent, t.title task FROM mb_improvements i LEFT JOIN mb_agents a ON a.id=i.agent_id
                            LEFT JOIN mb_tasks t ON t.id=i.task_id WHERE i.flow_id=? AND i.status IN ('diagnosing','proposed','testing','better') ORDER BY i.id""", (f["id"],))
        return [{**r, "agent": r["agent"] or "an engineer"} for r in rows]

    def view(self, f):
        team = {a["id"]: a for a in self.bench._team(f["id"])}
        titles = {t["id"]: t["title"] for t in self.db.q("SELECT id, title FROM mb_tasks WHERE flow_id=?", (f["id"],))}
        rows = self.db.q("SELECT * FROM mb_improvements WHERE flow_id=? ORDER BY id DESC LIMIT ?", (f["id"], LIST))
        info = self.bench._info()
        scored = [c["id"] for c in self.lab._scored(f)] if info else []
        out = []
        for imp in rows:
            a = team.get(imp["agent_id"])
            o = {k: imp[k] for k in imp if k not in ("candidate", "trial")}
            arms = self.db.q("SELECT task_id, held, arm, slug, status, error, head, experiment FROM mb_trials WHERE improvement_id=? ORDER BY id", (imp["id"],))
            for x in arms: x.update(task_id=x["task_id"] or imp["task_id"], held=bool(x["held"]), task=titles.get(x["task_id"] or imp["task_id"]))
            o.update(candidate=_j(imp["candidate"]), trial=json.loads(imp["trial"]) if imp["trial"] else None, agent=a["name"] if a else None, task=titles.get(imp["task_id"]),
                     current={"instructions": a["instructions"] or "", "model": a["model"]} if a else None, arms=arms,
                     plan=self.plan(f, imp, scored) if imp["status"] in ("proposed", "same", "worse", "trial_failed") and scored else None)
            out.append(o)
        checks = [{"id": c["id"], "label": c["label"]} for c in self.lab._scored(f)] if info else []
        ev = getattr(self.w, "evolve", None)
        return {"setting": f["improve"] or "auto", "items": out, "checks": checks, "evolve": ev.view(f) if ev else None,
                "trial": {"held": HELD, "held_max": HELD_MAX, "margin": MARGIN, "margin_max": MARGIN_MAX, "parallel": (info or {}).get("parallel")}}


def build(work, require):
    r = APIRouter(prefix="/api/mining/improve")
    gate = work.m.hub.gate if work.m.hub else (lambda me: me)
    user = lambda req: gate(require(req))
    imp = Improve(work)
    r.state = {"improve": imp}

    @r.post("/agents/{aid}/ask")
    def ask(aid: int, body: AskIn, req: Request): return imp.ask(user(req), aid, body)

    @r.post("/{iid}/test")
    def test(iid: int, body: TestIn, req: Request): return imp.test(user(req), iid, body)

    @r.post("/{iid}/decide")
    def decide(iid: int, body: DecideIn, req: Request): return imp.decide(user(req), iid, body)

    @r.delete("/{iid}")
    def delete(iid: int, req: Request): return imp.delete(user(req), iid)

    @r.patch("/flows/{fid}")
    def setting(fid: int, body: SettingIn, req: Request): return imp.setting(user(req), fid, body)

    return r
