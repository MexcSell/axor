"""Competition teams, the Lab: the score of every evaluated commit, so a change is judged on what it solves (mining_bench.py runs
the Workflow; the work runs on the AXoR Workbench).

- A scored check is a workbench check with "results" (workbench/README.md): an eval that writes one JSON line per run of a task,
  in eval/eval.py's runs.jsonl format (task, passed, cost_usd, agent_sec, end). When it ends, the Lab scores the commit it ran
  on the way validators count: a task is solved only when every run of it passed. Beside that: the pass rate over runs, the
  cost and the agent's time per run.
- One experiment per evaluated commit: a task's branch (the check in the Review step), the base (Measure the base: the same
  check on the branch you merge into), or an earlier eval imported from the folder (<folder>/<label>/runs.jsonl). What became
  of the task (merged, sent back, dropped) is written on its experiments; a merge marks the experiment of the merged commit and
  the task's older ones as superseded.
- Compare: two experiments task by task, scored on the tasks both ran.
- A task's check shows its score beside the newest base on the same check. Nothing here gates a merge: you decide.

Administrators only, like the Workflow.
"""
import json, re, time, urllib.parse

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .mining import _clip
from .mining_bench import _same

LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")
FOLDER = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")
MAX_IMPORT, LIST = 60, 300
NAMES, UNSOLVED, LEDGER = 20, 30, 12  # task names kept per gain/loss; unsolved names and earlier tasks the Director is told


class BaseIn(BaseModel):
    check: str = Field(..., max_length=60)
    at: str | None = Field(None, pattern=r"^[0-9a-f]{7,40}$")  # a task's starting commit; else the branch you merge into as it is now


class ImportIn(BaseModel):
    path: str = Field("eval/results", max_length=200)
    labels: list[str] = Field(..., min_length=1, max_length=MAX_IMPORT)


class NoteIn(BaseModel):
    note: str = Field("", max_length=2000)


def score(lines):
    """(summary, per task) from result lines: solved = every run of the task passed."""
    per = {}
    for x in lines:
        name = str(x.get("task") or "").strip()[:200]
        if not name: continue
        p = per.setdefault(name, {"runs": 0, "passed": 0, "cost": 0.0, "secs": 0.0, "timed": 0, "ends": {}})
        p["runs"] += 1
        p["passed"] += 1 if x.get("passed") is True else 0
        try: p["cost"] += float(x.get("cost_usd") or 0)
        except (TypeError, ValueError): pass
        if isinstance(x.get("agent_sec"), (int, float)): p["secs"] += x["agent_sec"]; p["timed"] += 1
        end = str(x.get("end") or "")[:60]
        if end: p["ends"][end] = p["ends"].get(end, 0) + 1
    runs = sum(p["runs"] for p in per.values())
    timed = sum(p["timed"] for p in per.values())
    return {"tasks": len(per), "solved": sum(1 for p in per.values() if p["runs"] and p["passed"] == p["runs"]), "runs": runs,
            "passed": sum(p["passed"] for p in per.values()), "cost": sum(p["cost"] for p in per.values()),
            "secs": (sum(p["secs"] for p in per.values()) / timed) if timed else None}, per


def solved(p): return bool(p and p["runs"] and p["passed"] == p["runs"])


def versus(pa, pb):
    """A against B on the tasks both ran."""
    both = sorted(set(pa) & set(pb))
    sa, sb = sum(solved(pa[k]) for k in both), sum(solved(pb[k]) for k in both)
    gained = [k for k in both if solved(pa[k]) and not solved(pb[k])]
    lost = [k for k in both if solved(pb[k]) and not solved(pa[k])]
    # one suite = the same tasks, each run as often: else only the shared tasks compare, and the totals don't
    same_suite = set(pa) == set(pb) and all(pa[k]["runs"] == pb[k]["runs"] for k in both)
    return {"shared": len(both), "a": sa, "b": sb, "gained": gained, "lost": lost, "same_suite": same_suite,
            "only_a": len(set(pa) - set(pb)), "only_b": len(set(pb) - set(pa))}


class Lab:
    def __init__(self, work):
        self.w, self.db = work, work.db
        self.db.q("""CREATE TABLE IF NOT EXISTS mb_experiments (id INTEGER PRIMARY KEY AUTOINCREMENT, flow_id INTEGER, task_id INTEGER, kind TEXT,
                     run TEXT, check_id TEXT, label TEXT, head TEXT, base TEXT, status TEXT, tasks INTEGER, solved INTEGER, runs INTEGER,
                     passed INTEGER, cost REAL, secs REAL, per_task TEXT, decision TEXT, decided REAL, error TEXT, note TEXT, by_user TEXT,
                     created REAL, finished REAL)""")
        self.db.q("CREATE INDEX IF NOT EXISTS mb_experiments_f ON mb_experiments (flow_id, id)")
        self.db.q("CREATE INDEX IF NOT EXISTS mb_experiments_r ON mb_experiments (run)")
        work.lab = self

    @property
    def bench(self):
        b = getattr(self.w, "bench", None)
        if not b: raise HTTPException(503, "The Workflow isn't loaded.")
        return b

    def _row(self, me, eid):
        e = self.db.q("SELECT * FROM mb_experiments WHERE id=?", (eid,), one=True)
        if not e: raise HTTPException(404, "There's no such experiment.")
        self.bench._flow(me, e["flow_id"])
        return e

    def _scored(self, f):
        return [c for c in (self.bench._repo(f["repo"]) or {}).get("checks", []) if c.get("scored")]

    def _out(self, e, full=False):
        o = {k: e[k] for k in e if k != "per_task"}
        if full: o["per_task"] = json.loads(e["per_task"]) if e["per_task"] else {}
        return o

    # ---------- hooks from the Workflow (mining_bench.py) ----------
    def started(self, f, t, rid, ch, tip):
        self.db.q("""INSERT INTO mb_experiments (flow_id, task_id, kind, run, check_id, label, head, base, status, created)
                     VALUES (?,?,?,?,?,?,?,?,?,?)""", (f["id"], t["id"], "task", rid, ch["id"], _clip(t["title"], 200), tip, t["base"], "running", time.time()))

    def trial(self, f, label, rid, check, head, base):
        """A trial branch's eval (mining_improve.py): scored like any other; the improvement compares it."""
        return self.db.q("""INSERT INTO mb_experiments (flow_id, kind, run, check_id, label, head, base, status, created) VALUES (?,?,?,?,?,?,?,?,?) RETURNING id""",
                         (f["id"], "trial", rid, check, _clip(label, 200), head, base, "running", time.time()), one=True)["id"]

    def finished(self, r, run):
        e = self.db.q("SELECT * FROM mb_experiments WHERE run=?", (r["run"],), one=True)
        if not e or e["status"] != "running": return
        lines, now = run.get("results"), time.time()
        if run["status"] == "stopped" or not lines:
            why = run.get("error") or ("Stopped." if run["status"] == "stopped" else "The check wrote no result lines.")
            return self.db.q("UPDATE mb_experiments SET status=?, error=?, finished=? WHERE id=?",
                             ("stopped" if run["status"] == "stopped" else "failed", _clip(why, 600), now, e["id"]))
        s, per = score(lines)
        # a check can exit non-zero once some tasks fail: the score still counts, the exit is noted
        self.db.q("""UPDATE mb_experiments SET status='done', tasks=?, solved=?, runs=?, passed=?, cost=?, secs=?, per_task=?, error=?, finished=? WHERE id=?""",
                  (s["tasks"], s["solved"], s["runs"], s["passed"], s["cost"], s["secs"], json.dumps(per), _clip(run.get("error"), 600), now, e["id"]))
        if e["task_id"]: self._on_task(e, s, per)
        if e["kind"] == "base": self._rescore(e)

    def _rescore(self, b):
        """A base measured at the commit tasks started from: those compared with no base, or with another commit's, are compared
        now, and the Workflow records what that says."""
        for e in self.db.q("SELECT * FROM mb_experiments WHERE flow_id=? AND kind='task' AND check_id=? AND status='done' AND task_id IS NOT NULL",
                           (b["flow_id"], b["check_id"])):
            if not _same(e["base"], b["head"]): continue
            t = self.db.q("SELECT checks FROM mb_tasks WHERE id=?", (e["task_id"],), one=True)
            c = json.loads(t["checks"] or "{}").get(e["check_id"]) if t else None
            vs = ((c or {}).get("score") or {}).get("vs")
            if not c or c.get("run") != e["run"] or (vs and not vs.get("stale")): continue
            self._on_task(e, {k: e[k] for k in ("solved", "tasks", "passed", "runs", "cost")}, json.loads(e["per_task"] or "{}"))
            t = self.db.q("SELECT * FROM mb_tasks WHERE id=?", (e["task_id"],), one=True)
            self.bench._scored(t, json.loads(t["checks"])[e["check_id"]])

    def _base_for(self, fid, check, commit):
        """The base to compare a branch made from commit with: the measurement of that commit, else the newest (stale: the
        branch you merge into has moved, so a difference may come from work merged since, not from this branch)."""
        rows = self.db.q("SELECT * FROM mb_experiments WHERE flow_id=? AND kind='base' AND check_id=? AND status='done' ORDER BY id DESC LIMIT 50", (fid, check))
        b = next((x for x in rows if _same(x["head"], commit)), None)
        return (b, False) if b else ((rows[0], True) if rows else (None, False))

    def _on_task(self, e, s, per):
        """The score on the task's check entry, beside the base the task's branch was made from (or the newest, marked stale)."""
        t = self.db.q("SELECT checks FROM mb_tasks WHERE id=?", (e["task_id"],), one=True)
        if not t: return
        checks = json.loads(t["checks"] or "{}")
        c = checks.get(e["check_id"])
        if not c or c.get("run") != e["run"]: return
        sc = {"id": e["id"], "solved": s["solved"], "tasks": s["tasks"], "passed": s["passed"], "runs": s["runs"], "cost": s["cost"]}
        b, stale = self._base_for(e["flow_id"], e["check_id"], e["base"])
        if b:
            vs = versus(per, json.loads(b["per_task"] or "{}"))
            sc["vs"] = {"id": b["id"], "head": b["head"], "shared": vs["shared"], "solved": vs["a"], "base": vs["b"], "gained": len(vs["gained"]), "lost": len(vs["lost"]),
                        "gained_tasks": vs["gained"][:NAMES], "lost_tasks": vs["lost"][:NAMES], "stale": stale}
        c["score"] = sc
        self.db.q("UPDATE mb_tasks SET checks=? WHERE id=?", (json.dumps(checks), e["task_id"]))

    def decided(self, kind, fid, t):
        if not t: return
        now = time.time()
        if kind != "merged":
            return self.db.q("UPDATE mb_experiments SET decision=?, decided=? WHERE task_id=? AND decision IS NULL", (kind.replace("_", " "), now, t["id"]))
        row = self.db.q("SELECT approval FROM mb_tasks WHERE id=?", (t["id"],), one=True)
        commit = (json.loads(row["approval"]) if row and row["approval"] else {}).get("commit") or ""
        for e in self.db.q("SELECT id, head FROM mb_experiments WHERE task_id=? AND decision IS NULL", (t["id"],)):
            hit = not commit or (e["head"] and (commit.startswith(e["head"]) or e["head"].startswith(commit)))
            self.db.q("UPDATE mb_experiments SET decision=?, decided=? WHERE id=?", ("merged" if hit else "superseded", now, e["id"]))

    def forget(self, fid):
        self.db.q("DELETE FROM mb_experiments WHERE flow_id=?", (fid,))

    # ---------- what the Director is told when it plans ----------
    def ledger(self, f):
        """The eval record for the Director's plan prompt: what the base solves and doesn't yet, then what each earlier task did
        to the score. Empty when nothing was scored."""
        repo = self.bench._repo(f["repo"]) or {}
        labels = {c["id"]: c["label"] for c in repo.get("checks", [])}
        refs, seen = [], set()
        for e in self.db.q("""SELECT * FROM mb_experiments WHERE flow_id=? AND status='done' AND kind IN ('base','import')
                              ORDER BY COALESCE(finished, created) DESC, id DESC LIMIT 60""", (f["id"],)):
            key = e["check_id"] if e["kind"] == "base" else "import"  # the newest base of each eval; the newest earlier eval
            if key not in seen: seen.add(key); refs.append(e)
        if any(e["kind"] == "base" for e in refs): refs = [e for e in refs if e["kind"] == "base"]
        lines = []
        for e in refs[:3]:
            miss = sorted(k for k, p in json.loads(e["per_task"] or "{}").items() if not solved(p))
            what = f"“{labels.get(e['check_id'], e['check_id'])}” on {e['label']}" if e["kind"] == "base" else f"Your earlier eval {e['label']}"
            lines.append(f"- {what} solves {e['solved']} of {e['tasks']} tasks" + (f". Not solved yet: {', '.join(miss[:UNSOLVED])}{f' and {len(miss) - UNSOLVED} more' if len(miss) > UNSOLVED else ''}." if miss else ": all of them."))
        done = []
        for t in self.db.q("SELECT title, status, checks FROM mb_tasks WHERE flow_id=? AND status!='proposed' ORDER BY id DESC", (f["id"],)):
            s = next((c["score"] for c in json.loads(t["checks"] or "{}").values() if c.get("score")), None)
            if not s: continue
            vs, line = s.get("vs"), f"- [{t['status']}] “{t['title']}”: solved {s['solved']} of {s['tasks']}"
            if vs:
                d = vs["solved"] - vs["base"]
                line += f" against {vs['base']} on the base ({f'+{d}' if d > 0 else d if d else 'same'}" + (", base measured on another commit" if vs.get("stale") else "") + ")"
                if vs.get("gained_tasks"): line += f"; gained {', '.join(vs['gained_tasks'])}"
                if vs.get("lost_tasks"): line += f"; lost {', '.join(vs['lost_tasks'])}"
            done.append(line)
            if len(done) >= LEDGER: break
        if not lines and not done: return []
        head = (repo.get("heads") or {}).get(f["into_branch"])
        return (["What the eval says (the Lab; a task counts as solved only when every run of it passed):"]
                + ([f"{f['into_branch']} is at {head[:8]} now."] if head else []) + lines
                + (["What earlier tasks did to the score, newest first:", *done] if done else [])
                + ["Aim the next tasks at eval tasks that aren't solved yet, build on what gained, and don't repeat what lost tasks or was dropped."])

    # ---------- the page ----------
    def view(self, me, fid):
        f = self.bench._flow(me, fid)
        rows = self.db.q("SELECT * FROM mb_experiments WHERE flow_id=? ORDER BY COALESCE(finished, created) DESC, id DESC LIMIT ?", (fid, LIST))
        titles = {t["id"]: t["title"] for t in self.db.q("SELECT id, title FROM mb_tasks WHERE flow_id=?", (fid,))}
        out = []
        for e in rows:
            o = self._out(e)
            if e["task_id"]: o["task"] = titles.get(e["task_id"])
            out.append(o)
        return {"flow": {"id": f["id"], "into_branch": f["into_branch"], "repo": f["repo"]}, "checks": self._scored(f) if self.bench._info() else [],
                "connected": bool(self.bench._info()), "experiments": out}

    def experiment(self, me, eid):
        return self._out(self._row(me, eid), full=True)

    def compare(self, me, a, b):
        ea, eb = self._row(me, a), self._row(me, b)
        if ea["flow_id"] != eb["flow_id"]: raise HTTPException(400, "Compare two experiments of the same team.")
        pa, pb = json.loads(ea["per_task"] or "{}"), json.loads(eb["per_task"] or "{}")
        rows = []
        for k in sorted(set(pa) | set(pb)):
            x, y = pa.get(k), pb.get(k)
            rows.append({"task": k, "a": x, "b": y, "change": None if not (x and y) else "gained" if solved(x) and not solved(y) else "lost" if solved(y) and not solved(x) else "same"})
        vs = versus(pa, pb)
        cost = lambda p, ks: sum(p[k]["cost"] for k in ks) / max(1, sum(p[k]["runs"] for k in ks))
        both = [k for k in pa if k in pb]
        return {"a": self._out(ea), "b": self._out(eb), "rows": rows, "shared": vs["shared"], "solved_a": vs["a"], "solved_b": vs["b"],
                "gained": len(vs["gained"]), "lost": len(vs["lost"]), "cost_a": cost(pa, both) if both else None, "cost_b": cost(pb, both) if both else None,
                "passed_a": sum(pa[k]["passed"] for k in both), "passed_b": sum(pb[k]["passed"] for k in both),
                "runs_a": sum(pa[k]["runs"] for k in both), "runs_b": sum(pb[k]["runs"] for k in both),
                "same_suite": vs["same_suite"], "only_a": vs["only_a"], "only_b": vs["only_b"]}

    def baseline(self, me, fid, b: BaseIn):
        f = self.bench._flow(me, fid)
        ch = next((c for c in self._scored(f) if c["id"] == b.check), None)
        if not ch: raise HTTPException(404, "There's no such scored check for this folder.")
        if b.at:  # only a commit a task of this flow started from
            t = next((t for t in self.db.q("SELECT base FROM mb_tasks WHERE flow_id=? AND base IS NOT NULL", (fid,)) if _same(t["base"], b.at)), None)
            if not t: raise HTTPException(404, "No task of this team started from that commit.")
            head = t["base"]
        else: head = self.bench._head(f)
        if self.db.q("SELECT 1 FROM mb_experiments WHERE flow_id=? AND kind='base' AND check_id=? AND head=? AND status='running'", (fid, b.check, head), one=True):
            raise HTTPException(409, f"The base at {head[:8]} is already being measured on this check.")
        label = f"{f['into_branch']} at {head[:8]}"
        rid = self.bench._run(f, "check", "Workbench", f"{ch['label']}: base {label}", {"check": b.check, "slug": f"base-{head[:10]}", "base": head})
        self.db.q("""INSERT INTO mb_experiments (flow_id, kind, run, check_id, label, head, base, status, by_user, created) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                  (fid, "base", rid, b.check, label, head, head, "running", me["username"], time.time()))
        self.bench._say(fid, "run", f"{me['username']} is measuring the base ({label}) with “{ch['label']}”")
        return self.view(me, fid)

    # ---------- earlier evals in the folder ----------
    def past(self, me, fid, path):
        f = self.bench._flow(me, fid)
        path = (path or "eval/results").strip().strip("/")
        if not FOLDER.match(path) or ".." in path.split("/"): raise HTTPException(400, "Give a folder inside the repo, like eval/results.")
        listing = self.bench.call(f"/repos/{f['repo']}/tree?" + urllib.parse.urlencode({"path": path, "ref": ""}))
        have = {e["label"] for e in self.db.q("SELECT label FROM mb_experiments WHERE flow_id=? AND kind='import'", (fid,))}
        items = [{"label": i["name"], "imported": i["name"] in have, "bench": i["name"].startswith("bench-")}
                 for i in listing.get("items", []) if i.get("dir") and LABEL.match(i["name"])]
        return {"path": path, "items": items}

    def _read(self, f, path):
        return self.bench.call(f"/repos/{f['repo']}/file?" + urllib.parse.urlencode({"path": path, "ref": ""}))

    def import_(self, me, fid, b: ImportIn):
        f = self.bench._flow(me, fid)
        path = b.path.strip().strip("/")
        if not FOLDER.match(path) or ".." in path.split("/"): raise HTTPException(400, "Give a folder inside the repo, like eval/results.")
        have = {e["label"] for e in self.db.q("SELECT label FROM mb_experiments WHERE flow_id=? AND kind='import'", (fid,))}
        done, skipped = 0, []
        for label in dict.fromkeys(b.labels):
            if not LABEL.match(label) or label in have: continue
            try: got = self._read(f, f"{path}/{label}/runs.jsonl")
            except HTTPException as e: skipped.append(f"{label}: {e.detail}"); continue
            lines = []
            for line in (got.get("content") or "").splitlines():
                try: o = json.loads(line)
                except ValueError: continue
                if isinstance(o, dict): lines.append(o)
            if not lines: skipped.append(f"{label}: no result lines"); continue
            when = None
            try:  # eval.py's summary.md says when it was written
                m = re.search(r"written (\d{4}-\d\d-\d\d \d\d:\d\d)", self._read(f, f"{path}/{label}/summary.md").get("content") or "")
                if m: when = time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M"))
            except HTTPException: pass
            s, per = score(lines)
            self.db.q("""INSERT INTO mb_experiments (flow_id, kind, label, status, tasks, solved, runs, passed, cost, secs, per_task, error, by_user, created, finished)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (fid, "import", label, "done", s["tasks"], s["solved"], s["runs"], s["passed"], s["cost"], s["secs"], json.dumps(per),
                       "The file was cut at 512 kB: the score covers its first part." if got.get("truncated") else None, me["username"], when or time.time(), when or time.time()))
            done += 1
        if done: self.bench._say(fid, "ok", f"{me['username']} imported {done} earlier eval{'s' if done != 1 else ''} into the Lab")
        return {**self.view(me, fid), "imported": done, "skipped": skipped}

    def note(self, me, eid, b: NoteIn):
        e = self._row(me, eid)
        self.db.q("UPDATE mb_experiments SET note=? WHERE id=?", (b.note.strip() or None, eid))
        return self.view(me, e["flow_id"])

    def delete(self, me, eid):
        e = self._row(me, eid)
        if e["status"] == "running": raise HTTPException(409, "It's still running.")
        self.db.q("DELETE FROM mb_experiments WHERE id=?", (eid,))
        return self.view(me, e["flow_id"])


def build(work, require):
    r = APIRouter(prefix="/api/mining/lab")
    gate = work.m.hub.gate if work.m.hub else (lambda me: me)
    user = lambda req: gate(require(req))
    lab = Lab(work)
    r.state = {"lab": lab}

    @r.get("/flows/{fid}")
    def view(fid: int, req: Request): return lab.view(user(req), fid)

    @r.post("/flows/{fid}/baseline")
    def baseline(fid: int, body: BaseIn, req: Request): return lab.baseline(user(req), fid, body)

    @r.get("/flows/{fid}/past")
    def past(fid: int, req: Request, path: str = "eval/results"): return lab.past(user(req), fid, path)

    @r.post("/flows/{fid}/import")
    def import_(fid: int, body: ImportIn, req: Request): return lab.import_(user(req), fid, body)

    @r.get("/experiments/{eid}")
    def experiment(eid: int, req: Request): return lab.experiment(user(req), eid)

    @r.patch("/experiments/{eid}")
    def note(eid: int, body: NoteIn, req: Request): return lab.note(user(req), eid, body)

    @r.delete("/experiments/{eid}")
    def delete(eid: int, req: Request): return lab.delete(user(req), eid)

    @r.get("/compare")
    def compare(req: Request, a: int, b: int): return lab.compare(user(req), a, b)

    return r
