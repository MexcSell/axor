"""Competition teams, Top miner: the short road to a top SN62 Competition 28 miner, on what the team already measures
(mining-topminer.js draws it as a sub-tab of the Competition teams page).

- Roadmap: six milestones, M0 the competition contract → M1 reliability → M2 validation infrastructure → M3 task-solving quality
  → M4 cost and speed → M5 controlled submission (validation comes before quality: quality is measured on the set's held-out
  tasks, so the set has to exist first). The numbers come from the order; the stored keys (m0…m5) never change, so marks made
  before the reorder keep their meaning: key m3 is the validation step, key m2 the quality step. Each reads its evidence from what exists (the Lab's scored evals, the validation set, the Command center's
  approved deploys) and says what's missing; the user can also mark one by hand with a note. A milestone is never marked done
  from an agent's say-so.
- Validation set: 50 tasks in five categories (8 development + 2 held out each) (query generation, query fixing, query optimization, schema and index,
  semantic edge cases), each PostgreSQL, ClickHouse or both, each dev (to improve on) or held out (to judge with: never used to
  improve), with the edge cases it covers (empty results, duplicates, NULLs, ties, ordering). Task names match the eval's task
  names (eval/eval.py runs.jsonl), so the Lab's per-task results score them; names can be imported from the Lab's evals.
- Scorecard, from the newest done Lab eval on the set: correctness (tasks solved, every run passing), reliability (runs that
  passed, and runs that finished), efficiency (dollars and seconds per solved task), generalization (held-out against dev),
  and the internal quality figure solved / (dollars × hours). Competition performance (the evaluator's score and rank) comes
  from the Command center's measured metrics and stays apart: internal scores never stand in for official ones.
- Elite team: the 13 roles on the critical path (Director, 4 database, 3 engineering, 3 evaluation, 2 research and strategy),
  filled from the team's own agents by squad and title; the others stay as support. No agents are created.
- The first mission: the 30-minute "Top miner first milestone" brief as eleven tasks on the team's board, each for the elite
  agent who fits, with the constraints (no submitting, no secrets, isolated candidates, report what's unfinished at the
  deadline). The team works them the usual way (Start assigned, or autopilot); the tab follows them against the clock.

Agents never upload, register or submit: M5 is the user's, through the Command center's approval.
"""
import json, re, time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .mining import _clip
from .mining_lab import solved

CATEGORIES = {"generation": "Query generation", "fixing": "Query fixing", "optimization": "Query optimization",
              "schema": "Schema and indexes", "edge": "Semantic edge cases"}
ENGINES = {"postgres": "PostgreSQL", "clickhouse": "ClickHouse", "both": "Both", "other": "Other"}
EDGES = {"empty": "Empty results", "duplicates": "Duplicates", "nulls": "NULLs", "ties": "Ties", "ordering": "Ordering"}
TARGET, PER_CATEGORY, MIN_HELD, MAX_HELD = 50, 10, 0.2, 0.4   # tasks in the set, per category, share held out (at least, at most)
MAX_SET, MISSION_MINUTES = 200, 30
# (stored key, name, time box, success criterion), in the order the work happens; the shown number is the position (M0…M5)
MILESTONES = (
    ("m0", "Understand the competition contract", "30 min", "The official requirements, submission format, execution limits, scoring and evaluator are written down where the team reads them (Notebook or Links)."),
    ("m1", "Miner reliability", "30 min", "The miner starts, explores the repository, produces a valid unified diff and completes representative tasks."),
    ("m3", "Validation infrastructure", "2–3 h", f"A versioned set of {TARGET}+ tasks over all five categories, each with development and held-out tasks ({int(MIN_HELD * 100)}–{int(MAX_HELD * 100)}% held out), and a baseline eval on it."),
    ("m2", "Task-solving quality", "1–2 h", "Correctness on the held-out tasks measurably better than the baseline eval."),
    ("m4", "Cost and speed", "1–2 h", "Lower cost per solved task than the baseline, without losing correctness."),
    ("m5", "Controlled submission", "you", "A candidate compared with production, approved by you in the Command center, submitted, and the official result recorded."),
)
TITLES = {k: f"M{i} · {name}" for i, (k, name, _, _) in enumerate(MILESTONES)}
ROLES = (("director", "Director", 1, "Coordinates the work and keeps it on competition performance."),
         ("database", "Database specialists", 4, "PostgreSQL, ClickHouse, ORM and query optimization."),
         ("engineering", "Engineering specialists", 3, "Repository analysis, patch engineering and debugging."),
         ("evaluation", "Evaluation specialists", 3, "Testing, independent review and benchmark analysis."),
         ("research", "Research and strategy", 2, "Competition research and improvement discovery."))
FIT = {"database": re.compile(r"postgres|clickhouse|sql|query|schema|index|database|orm|migration", re.I),
       "engineering": re.compile(r"engineer|patch|repo|code|debug|stack|architect|build|developer", re.I),
       "evaluation": re.compile(r"eval|review|test|bench|qa|red team|verif|failure|curator", re.I),
       "research": re.compile(r"research|strateg|scout|intel|analyst|leaderboard|rules|competit", re.I)}
SQUAD_FIT = {"database": "database", "stack": "engineering", "agent": "engineering", "solvers": "engineering", "eval": "evaluation",
             "testing": "evaluation", "release": "evaluation", "intel": "research", "command": "research"}
# the first mission: (title, role it goes to, detail)
MISSION = (
    ("Inspect the miner and the agent interface", "engineering", "Read agent.py and the Ridges agent interface it implements. List what it does per task, where the patch comes from, and anything that doesn't match the interface."),
    ("Read recent failed runs, logs and submission errors", "evaluation", "Go through the newest eval runs and any submission errors. Group the failures by cause, with the run or log line for each."),
    ("Rank the top five technical weaknesses", "director", "From the inspection and the failures, rank the five weaknesses that cost the most solved tasks, each with its evidence."),
    ("Check unified diff generation and output validation", "engineering", "Check the diff the miner writes is a valid unified diff against the repo at the task's commit, and that malformed output is caught before it's returned."),
    ("Check repository exploration and schema understanding", "database", "Check how the miner finds the query path: schemas, ORM expressions, query builders, migrations. Say where it guesses instead of reading."),
    ("Check PostgreSQL and ClickHouse task handling", "database", "Compare how it handles a PostgreSQL task and a ClickHouse task: dialect, NULLs, duplicates, ties and ordering."),
    ("Run representative local tests", "evaluation", "Run the miner on a handful of dev tasks from the validation set in the sandbox or the Lab and record each result."),
    ("Find the correctness, reliability and cost bottlenecks", "research", "From the runs: where correctness is lost, where runs fail or time out, and where the cost goes."),
    ("Prepare the highest-impact fixes", "engineering", "Draft the fixes for the top weaknesses as diffs on an isolated candidate branch; never on the production miner."),
    ("Test the candidate", "evaluation", "Run the candidate on the same tasks as the baseline, held-out tasks included, and record pass/fail, cost and time."),
    ("Compare the candidate with the baseline and recommend", "director", "Compare candidate and baseline on correctness, cost and runtime. Write the health report, the ranked weaknesses, the before/after table and the recommended next milestone. If nothing could be verified, say exactly why."),
)
MISSION_RULES = ("Constraints: don't replace the existing miner without evidence; don't invent competition results; don't optimize only for "
                 "internal scores; never expose wallet secrets or signing credentials; don't upload or submit anything; keep the "
                 "production miner as it is and work on isolated candidate versions; at the deadline, report what's unfinished.")


class SetIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: str = Field("generation", pattern="^(generation|fixing|optimization|schema|edge)$")
    engine: str = Field("postgres", pattern="^(postgres|clickhouse|both|other)$")
    split: str = Field("dev", pattern="^(dev|held)$")
    edges: list[str] = Field(default_factory=list, max_length=5)
    note: str = Field("", max_length=400)


class SetPatch(BaseModel):
    category: str | None = Field(None, pattern="^(generation|fixing|optimization|schema|edge)$")
    engine: str | None = Field(None, pattern="^(postgres|clickhouse|both|other)$")
    split: str | None = Field(None, pattern="^(dev|held)$")
    edges: list[str] | None = Field(None, max_length=5)
    note: str | None = Field(None, max_length=400)


class BulkIn(BaseModel):
    names: list[str] = Field(default_factory=list, max_length=MAX_SET)
    from_lab: bool = False
    held_share: float = Field(0.2, ge=0, le=0.8)


class MarkIn(BaseModel):
    status: str = Field(..., pattern="^(auto|todo|doing|done)$")
    note: str = Field("", max_length=400)


def clean_name(name):
    """A task name as the eval writes it: no surrounding quotes, bullets or list punctuation, and no unbalanced closing bracket
    (a name pasted from prose, e.g. "ch-top-pages-pruning-001)", never matches the eval's per-task results)."""
    n, prev = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", name or "").strip(), None
    while n != prev:
        prev, n = n, n.strip().strip("`'\"“”‘’").rstrip(",;:")
    while n and n[-1] in ")]}" and n.count(n[-1]) > n.count({")": "(", "]": "[", "}": "{"}[n[-1]]):
        n = n[:-1].rstrip(",;:")
    return n.strip()


def guess(name):
    """(category, engine, edges) from an eval task's name, e.g. ch-dec-daily-summary-mv-001 or bc-pg-308."""
    n = name.lower()
    engine = "clickhouse" if re.search(r"(^|[-_])ch[-_]|clickhouse", n) else "postgres" if re.search(r"(^|[-_])pg[-_]?|postgres", n) else "other"
    cat = ("optimization" if re.search(r"optim|perf|prun|speed|index-scan|fast|mv|rollup", n) else "fixing" if re.search(r"fix|bug|dedup|repair|broken", n)
           else "schema" if re.search(r"schema|index|column|migrat|partition", n) else "edge" if re.search(r"null|tie|order|empty|dup|edge", n) else "generation")
    edges = [k for k, rx in (("nulls", "null"), ("duplicates", "dup"), ("ties", "tie"), ("ordering", "order|sort"), ("empty", "empty")) if re.search(rx, n)]
    return cat, engine, edges


class TopMiner:
    def __init__(self, work):
        self.w, self.db = work, work.db
        q = self.db.q
        q("""CREATE TABLE IF NOT EXISTS tm_set (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, name TEXT, category TEXT, engine TEXT,
             split TEXT, edges TEXT, note TEXT, source TEXT, created REAL, UNIQUE (comp_id, name))""")
        q("CREATE TABLE IF NOT EXISTS tm_marks (comp_id INTEGER, key TEXT, status TEXT, note TEXT, by_user TEXT, ts REAL, PRIMARY KEY (comp_id, key))")
        q("""CREATE TABLE IF NOT EXISTS tm_missions (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, by_user TEXT, started REAL, deadline REAL,
             tasks TEXT, status TEXT)""")
        work.topminer = self
        self._clean_names()

    def _clean_names(self):
        """Names saved before clean_name() existed: fix the ones it changes, unless the fixed name is already in the set."""
        for r in self.db.q("SELECT id, comp_id, name FROM tm_set WHERE name LIKE '%)' OR name LIKE '%]' OR name LIKE '%,' OR name LIKE '%;' OR name LIKE '%`'"):
            n = clean_name(r["name"])
            if n and n != r["name"] and not self.db.q("SELECT 1 FROM tm_set WHERE comp_id=? AND name=?", (r["comp_id"], n), one=True):
                self.db.q("UPDATE tm_set SET name=? WHERE id=?", (n, r["id"]))

    def _has(self, table):
        return bool(self.db.q("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,), one=True))

    # ---------- the validation set ----------
    def _set(self, wid):
        rows = self.db.q("SELECT * FROM tm_set WHERE comp_id=? ORDER BY category, name", (wid,))
        for r in rows: r["edges"] = json.loads(r["edges"] or "[]")
        return rows

    def add(self, me, wid, b: SetIn):
        self.w._own(me, wid)
        if self.db.q("SELECT COUNT(*) n FROM tm_set WHERE comp_id=?", (wid,), one=True)["n"] >= MAX_SET: raise HTTPException(409, f"A set holds at most {MAX_SET} tasks.")
        name = clean_name(b.name)
        if not name: raise HTTPException(400, "That isn't a task name.")
        if self.db.q("SELECT 1 FROM tm_set WHERE comp_id=? AND name=?", (wid, name), one=True): raise HTTPException(409, "That task is already in the set.")
        self.db.q("INSERT INTO tm_set (comp_id, name, category, engine, split, edges, note, source, created) VALUES (?,?,?,?,?,?,?,?,?)",
                  (wid, name, b.category, b.engine, b.split, json.dumps([e for e in b.edges if e in EDGES]), b.note.strip(), "you", time.time()))
        return self.view(me, wid)

    def bulk(self, me, wid, b: BulkIn):
        self.w._own(me, wid)
        names = [n for n in (clean_name(x)[:200] for x in b.names) if n]
        if b.from_lab:
            for e in self._evals(wid, 40):
                names += list(json.loads(e["per_task"] or "{}"))
        have = {r["name"] for r in self.db.q("SELECT name FROM tm_set WHERE comp_id=?", (wid,))}
        new = [n for n in dict.fromkeys(names) if n not in have][:max(0, MAX_SET - len(have))]
        if not new: raise HTTPException(409, "Nothing new to add: those tasks are in the set already." if names else
                                        "No task names found." + (" The Lab has no finished evals for this team yet." if b.from_lab else ""))
        # hold out every k-th task of each category, so both splits cover every category
        by_cat, now = {}, time.time()
        for n in sorted(new):
            cat, eng, edges = guess(n)
            k = by_cat.setdefault(cat, [0])
            k[0] += 1
            held = b.held_share > 0 and (k[0] % max(1, round(1 / b.held_share)) == 0)
            self.db.q("INSERT OR IGNORE INTO tm_set (comp_id, name, category, engine, split, edges, note, source, created) VALUES (?,?,?,?,?,?,?,?,?)",
                      (wid, n, cat, eng, "held" if held else "dev", json.dumps(edges), "", "lab" if b.from_lab else "list", now))
        self.w._event(wid, "topminer", f"{me['username']} added {len(new)} tasks to the validation set")
        return self.view(me, wid)

    def patch(self, me, sid, b: SetPatch):
        r = self.db.q("SELECT * FROM tm_set WHERE id=?", (sid,), one=True)
        if not r: raise HTTPException(404, "There's no such task in the set.")
        self.w._own(me, r["comp_id"])
        sets = {k: v for k, v in b.model_dump(exclude_unset=True).items() if v is not None}
        if "edges" in sets: sets["edges"] = json.dumps([e for e in sets["edges"] if e in EDGES])
        if sets: self.db.q(f"UPDATE tm_set SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?", (*sets.values(), sid))
        return self.view(me, r["comp_id"])

    def delete(self, me, sid):
        r = self.db.q("SELECT * FROM tm_set WHERE id=?", (sid,), one=True)
        if not r: raise HTTPException(404, "There's no such task in the set.")
        self.w._own(me, r["comp_id"])
        self.db.q("DELETE FROM tm_set WHERE id=?", (sid,))
        return self.view(me, r["comp_id"])

    # ---------- measurements ----------
    def _evals(self, wid, n=10):
        if not self._has("mb_experiments") or not self._has("mb_flows"): return []
        f = self.db.q("SELECT id FROM mb_flows WHERE comp_id=?", (wid,), one=True)
        if not f: return []
        return self.db.q("""SELECT id, kind, label, head, status, tasks, solved, runs, passed, cost, secs, per_task, finished FROM mb_experiments
                            WHERE flow_id=? AND status='done' AND kind != 'trial' ORDER BY finished DESC LIMIT ?""", (f["id"], n))

    def _baseline(self, wid, sets, newest_id):
        """The eval quality and cost are judged against: the newest Lab base measurement that ran tasks of the set, else the
        earliest eval that ever did. Never "whichever is oldest in the last ten", which drifts as evals pile up."""
        if not self._has("mb_experiments") or not self._has("mb_flows"): return None
        f = self.db.q("SELECT id FROM mb_flows WHERE comp_id=?", (wid,), one=True)
        if not f: return None
        cols = "id, kind, label, head, status, tasks, solved, runs, passed, cost, secs, per_task, finished"
        for sql, how in ((f"SELECT {cols} FROM mb_experiments WHERE flow_id=? AND status='done' AND kind='base' ORDER BY finished DESC LIMIT 50", "the newest base measurement"),
                         (f"SELECT {cols} FROM mb_experiments WHERE flow_id=? AND status='done' AND kind != 'trial' ORDER BY finished ASC LIMIT 200", "the earliest eval on the set")):
            for e in self.db.q(sql, (f["id"],)):
                if e["id"] == newest_id: continue
                c = self.card(e, sets)
                if c: return c | {"how": how}
        return None

    @staticmethod
    def card(e, sets):
        """The scorecard of one eval on the validation set (None when the eval ran none of its tasks)."""
        per = json.loads(e["per_task"] or "{}")
        split = {r["name"]: r["split"] for r in sets}
        cats = {r["name"]: r["category"] for r in sets}
        mine = {k: v for k, v in per.items() if k in split}
        if not mine: return None
        def part(keys):
            ps = [mine[k] for k in keys]
            if not ps: return None
            runs, passed = sum(p["runs"] for p in ps), sum(p["passed"] for p in ps)
            ok = sum(1 for p in ps if solved(p))
            fin = sum((p.get("ends") or {}).get("finished", 0) for p in ps)
            cost, secs = sum(p.get("cost") or 0 for p in ps), sum(p.get("secs") or 0 for p in ps)
            return {"tasks": len(ps), "solved": ok, "correct": ok / len(ps), "runs": runs, "pass_rate": passed / runs if runs else None,
                    "finished": fin / runs if runs and any(p.get("ends") for p in ps) else None, "cost": cost,
                    "cost_solved": cost / ok if ok else None, "secs_solved": secs / ok if ok else None,
                    "quality": ok / (cost * secs / 3600) if cost > 0 and secs > 0 else None}
        allk = list(mine)
        dev, held = [k for k in allk if split[k] == "dev"], [k for k in allk if split[k] == "held"]
        out = {"eval": {k: e[k] for k in ("id", "kind", "label", "head", "finished")}, "all": part(allk), "dev": part(dev), "held": part(held),
               "missing": len(split) - len(mine),
               "categories": {c: part([k for k in allk if cats[k] == c]) for c in CATEGORIES}}
        d, h = out["dev"], out["held"]
        out["gap"] = (d["correct"] - h["correct"]) if d and h else None
        return out

    def _official(self, wid):
        """The competition's own measurements (the Command center's evaluator reports or manual entries), newest first. Internal
        Lab scores never fill these in: a field nobody reported stays None."""
        if not self._has("mc_metrics"): return {}
        out = {}
        for m in ("score", "rank", "leader_score", "correctness", "success_rate", "cost_task", "latency_p50"):
            r = self.db.q("SELECT value, ts, source FROM mc_metrics WHERE comp_id=? AND metric=? ORDER BY ts DESC LIMIT 1", (wid, m), one=True)
            if r: out[m] = r
        if "score" in out and "leader_score" in out:
            out["gap"] = {"value": out["leader_score"]["value"] - out["score"]["value"]}
        n = self.db.q("SELECT COUNT(DISTINCT ts) n FROM mc_metrics WHERE comp_id=? AND metric IN ('score','rank') AND source != 'manual'", (wid,), one=True)
        out["evaluations"] = n["n"] if n else 0
        last = self.db.q("SELECT MAX(ts) t FROM mc_metrics WHERE comp_id=? AND metric IN ('score','rank')", (wid,), one=True)
        out["last"] = last["t"] if last and last["t"] else None
        if self._has("mc_deploys"):
            out["submissions"] = self.db.q("SELECT COUNT(*) n FROM mc_deploys WHERE comp_id=? AND approval_id IS NOT NULL", (wid,), one=True)["n"]
            dep = self.db.q("SELECT version, status, ts FROM mc_deploys WHERE comp_id=? ORDER BY id DESC LIMIT 1", (wid,), one=True)
            if dep: out["submission"] = dep
        return out

    def _deployed(self, wid):
        if not self._has("mc_deploys"): return None
        return self.db.q("SELECT version, ts, approval_id FROM mc_deploys WHERE comp_id=? AND approval_id IS NOT NULL ORDER BY id DESC LIMIT 1", (wid,), one=True)

    @staticmethod
    def readiness(sets):
        """What the validation set still lacks, as short sentences (empty when it's ready to judge with)."""
        held = sum(1 for r in sets if r["split"] == "held")
        dev = len(sets) - held
        gaps = []
        if not sets: return ["The set is empty."]
        if not dev: gaps.append("No development set: every task is held out, so agents have nothing to improve on.")
        if not held: gaps.append("No held-out tasks: nothing judges a change without bias.")
        if len(sets) < TARGET: gaps.append(f"{len(sets)} of {TARGET} tasks.")
        for k, label in CATEGORIES.items():
            c = [r for r in sets if r["category"] == k]
            if not c: gaps.append(f"No {label.lower()} tasks.")
            elif not any(r["split"] == "dev" for r in c) or not any(r["split"] == "held" for r in c):
                gaps.append(f"{label}: needs both development and held-out tasks.")
        if dev and held and not (MIN_HELD <= held / len(sets) <= MAX_HELD):
            gaps.append(f"{held / len(sets):.0%} held out: aim for {MIN_HELD:.0%}–{MAX_HELD:.0%}.")
        return gaps

    # ---------- roadmap ----------
    def _roadmap(self, wid, sets, cards, comp=None):
        marks = {r["key"]: r for r in self.db.q("SELECT * FROM tm_marks WHERE comp_id=?", (wid,))}
        new = cards[0] if cards else None
        base = self._baseline(wid, sets, new["eval"]["id"]) if new else None
        bname = f"“{base['eval']['label'] or base['eval']['id']}”, {base['how']}" if base else ""
        gaps = self.readiness(sets)
        auto = {}
        # M0: only a person can say the contract is understood; the competition page or its rules being on file is a start
        comp = comp or {}
        has = [x for x, ok in (("the competition page", comp.get("link")), ("the team's notes", comp.get("notes"))) if ok]
        auto["m0"] = (("doing", f"On file: {' and '.join(has)}. Mark it done once the format, limits, scoring and evaluator are written down.") if has
                      else ("todo", "Nothing on file yet: add the competition page (team settings) and note the format, limits, scoring and evaluator."))
        # M1: an eval with at least one passing run means the miner produced a valid patch end to end
        auto["m1"] = (("done", f"Eval “{new['eval']['label'] or new['eval']['id']}”: {new['all']['solved']} of {new['all']['tasks']} set tasks solved.")
                      if new and new["all"]["solved"] else ("doing", "Evals ran, but no task of the set passed yet.") if new
                      else ("todo", "No Lab eval of the miner on the set yet: run a scored check (Lab tab)."))
        # validation infrastructure (key m3): a ready set with a baseline eval that covered it
        measured = new and new["missing"] <= len(sets) * 0.2
        held = sum(1 for r in sets if r["split"] == "held")
        auto["m3"] = (("done", f"{len(sets)} tasks, {len(sets) - held} development and {held} held out, every category; baseline measured.") if not gaps and measured else
                      ("doing" if sets else "todo", " ".join(gaps + ([] if measured else [f"{new['missing']} tasks not in the newest eval." if new else "No baseline eval yet."]))))
        # task-solving quality (key m2): held-out correctness better than the baseline, on a set that is ready (built by evidence
        # or marked done by hand)
        m3 = marks.get("m3")
        ready = (m3["status"] if m3 and m3["status"] != "auto" else auto["m3"][0]) == "done"
        if new and base and new["held"] and base["held"]:
            up = new["held"]["correct"] - base["held"]["correct"]
            line = f"Held-out correctness {base['held']['correct']:.0%} (baseline {bname}) → {new['held']['correct']:.0%}."
            auto["m2"] = ("done" if up > 0 and ready else "doing",
                          line + ("" if ready else f" Not conclusive until {TITLES['m3'].split(' · ')[0]} is done."))
        else: auto["m2"] = ("todo", f"Needs the baseline and a newer eval that both ran held-out tasks ({TITLES['m3'].split(' · ')[0]} first).")
        if new and base and new["all"]["cost_solved"] and base["all"]["cost_solved"]:
            better = new["all"]["cost_solved"] < base["all"]["cost_solved"] and new["all"]["correct"] >= base["all"]["correct"]
            auto["m4"] = ("done" if better else "doing", f"${base['all']['cost_solved']:.3f} (baseline {bname}) → ${new['all']['cost_solved']:.3f} per solved task, "
                          f"correctness {base['all']['correct']:.0%} → {new['all']['correct']:.0%}.")
        else: auto["m4"] = ("todo", "Needs the baseline and a newer eval with costs and solved tasks.")
        dep = self._deployed(wid)
        auto["m5"] = (("done", f"Version {dep['version'] or '?'} deployed with your approval.") if dep else
                      ("todo", "Compare a candidate in the Command center's Experiment center, approve it, and record the deploy you carried out."))
        out = []
        for i, (k, name, time_, success) in enumerate(MILESTONES):
            st, ev = auto[k]
            m = marks.get(k)
            out.append({"key": k, "num": f"M{i}", "name": name, "title": TITLES[k], "time": time_, "success": success, "auto": st, "evidence": ev,
                        "status": m["status"] if m and m["status"] != "auto" else st, "mark": m})
        return out

    def mark(self, me, wid, key, b: MarkIn):
        self.w._own(me, wid)
        if key not in {m[0] for m in MILESTONES}: raise HTTPException(404, "There's no such milestone.")
        self.db.q("INSERT OR REPLACE INTO tm_marks (comp_id, key, status, note, by_user, ts) VALUES (?,?,?,?,?,?)",
                  (wid, key, b.status, b.note.strip(), me["username"], time.time()))
        return self.view(me, wid)

    # ---------- the elite team ----------
    def elite(self, wid):
        team = [a for a in self.w._agents(wid) if a["active"]]
        taken, out = set(), []
        for key, label, n, about in ROLES:
            if key == "director":
                pick = [a for a in team if a["lead"]][:1]
            else:
                text = lambda a: f"{a['title']} {a['job']}"
                fits = [a for a in team if a["id"] not in taken and not a["lead"] and (SQUAD_FIT.get(a["squad"] or "") == key or FIT[key].search(text(a)))]
                fits.sort(key=lambda a: (SQUAD_FIT.get(a["squad"] or "") != key, not FIT[key].search(a["title"]), a["id"]))
                pick = fits[:n]
            taken |= {a["id"] for a in pick}
            out.append({"key": key, "label": label, "need": n, "about": about,
                        "agents": [{"id": a["id"], "name": a["name"], "title": a["title"], "squad": a["squad"] or ""} for a in pick]})
        support = [{"id": a["id"], "name": a["name"], "title": a["title"]} for a in team if a["id"] not in taken]
        return out, support

    # ---------- the first mission ----------
    def _mission(self, wid):
        m = self.db.q("SELECT * FROM tm_missions WHERE comp_id=? ORDER BY id DESC LIMIT 1", (wid,), one=True)
        if not m: return None
        ids = json.loads(m["tasks"] or "[]")
        from .task_lifecycle import not_dropped  # D-018: a dropped task is neither completed nor attempted work of the mission
        rows = {t["id"]: t for t in self.db.q(f"SELECT id, title, status, agent_id, summary, done_at, CASE WHEN {not_dropped(self.db)} THEN 0 ELSE 1 END AS dropped FROM mw_tasks WHERE id IN ({','.join('?' * len(ids))})", ids)} if ids else {}
        names = {a["id"]: a["name"] for a in self.w._agents(wid)}
        tasks = [dict(rows[i], agent=names.get(rows[i]["agent_id"])) if i in rows else {"id": i, "title": "(deleted)", "status": "deleted"} for i in ids]
        done = sum(1 for t in tasks if t["status"] == "done" and not t.get("dropped"))
        # the contract, kept apart: time allocated vs tasks attempted, completed, unfinished, and what it actually used
        attempted = sum(1 for t in tasks if t["status"] not in ("todo", "deleted"))
        used = self.db.q(f"SELECT COALESCE(SUM(tokens),0) t, COUNT(*) n FROM mw_runs WHERE task_id IN ({','.join('?' * len(ids))})", ids, one=True) if ids and self._has("mw_runs") else None
        return {k: m[k] for k in ("id", "by_user", "started", "deadline")} | {"tasks": tasks, "done": done,
                "contract": {"minutes": round((m["deadline"] - m["started"]) / 60), "attempted": attempted, "completed": done,
                             "unfinished": len([t for t in tasks if t["status"] not in ("done", "deleted")]),
                             "runs": used["n"] if used else 0, "tokens": used["t"] if used else 0},
                "status": "done" if done == len(tasks) else "late" if time.time() > m["deadline"] else "running"}

    def launch(self, me, wid):
        w, _ = self.w._own(me, wid)
        cur = self._mission(wid)
        if cur and cur["status"] == "running": raise HTTPException(409, "The first mission is already on the board.")
        roles, _ = self.elite(wid)
        by = {r["key"]: r["agents"] for r in roles}
        lead = (by.get("director") or [None])[0]
        turn, now, ids = {}, time.time(), []
        day = time.strftime("%Y-%m-%d", time.localtime(now))
        for title, role, detail in MISSION:
            pool = by.get(role) or ([lead] if lead else [])
            a = pool[turn.get(role, 0) % len(pool)] if pool else None
            turn[role] = turn.get(role, 0) + 1
            body = f"{detail}\n\nPart of the Top miner first milestone ({MISSION_MINUTES} minutes). {MISSION_RULES}"
            ids.append(self.w._ins("""INSERT INTO mw_tasks (comp_id, title, detail, status, priority, agent_id, due, origin, created, updated)
                                      VALUES (?,?,?,'todo','high',?,?,'topminer',?,?)""", (wid, title, body, a["id"] if a else None, day, now, now)))
        self.db.q("INSERT INTO tm_missions (comp_id, by_user, started, deadline, tasks, status) VALUES (?,?,?,?,?,?)",
                  (wid, me["username"], now, now + MISSION_MINUTES * 60, json.dumps(ids), "running"))
        self.w._event(wid, "topminer", f"{me['username']} put the Top miner first mission on the board: {len(ids)} tasks, {MISSION_MINUTES} minutes")
        return self.view(me, wid)

    # ---------- the tab ----------
    def view(self, me, wid):
        w, c = self.w._own(me, wid)
        sets = self._set(wid)
        cards = [x for x in (self.card(e, sets) for e in self._evals(wid)) if x]
        roles, support = self.elite(wid)
        cats = {k: {"label": l, "count": sum(1 for r in sets if r["category"] == k), "held": sum(1 for r in sets if r["category"] == k and r["split"] == "held")} for k, l in CATEGORIES.items()}
        return {"comp": {"id": w["id"], "label": self.w._label(w)}, "now": time.time(),
                "roadmap": self._roadmap(wid, sets, cards, w), "set": sets, "gaps": self.readiness(sets), "categories": cats, "engines": ENGINES, "edges": EDGES,
                "coverage": {k: sum(1 for r in sets if k in r["edges"]) for k in EDGES},
                "targets": {"total": TARGET, "per_category": PER_CATEGORY, "held": MIN_HELD, "held_max": MAX_HELD,
                            "dev_per_category": PER_CATEGORY - round(PER_CATEGORY * MIN_HELD), "held_per_category": round(PER_CATEGORY * MIN_HELD)},
                "scorecard": cards[0] if cards else None, "previous": cards[1] if len(cards) > 1 else None,
                "trend": [{"eval": x["eval"], "correct": x["all"]["correct"], "held": x["held"]["correct"] if x["held"] else None,
                           "cost_solved": x["all"]["cost_solved"]} for x in reversed(cards[:8])],
                "official": self._official(wid), "elite": roles, "support": support,
                "mission": self._mission(wid), "mission_plan": [{"title": t, "role": r} for t, r, _ in MISSION], "mission_minutes": MISSION_MINUTES}


def build(work, require):
    r = APIRouter(prefix="/api/mining/work")
    gate = work.m.hub.gate if work.m.hub else (lambda me: me)
    user = lambda req: gate(require(req))
    tm = TopMiner(work)
    r.state = {"topminer": tm}

    @r.get("/comps/{wid}/topminer")
    def view(wid: int, req: Request): return tm.view(user(req), wid)

    @r.post("/comps/{wid}/topminer/set")
    def add(wid: int, b: SetIn, req: Request): return tm.add(user(req), wid, b)

    @r.post("/comps/{wid}/topminer/set/bulk")
    def bulk(wid: int, b: BulkIn, req: Request): return tm.bulk(user(req), wid, b)

    @r.patch("/topminer/set/{sid}")
    def patch(sid: int, b: SetPatch, req: Request): return tm.patch(user(req), sid, b)

    @r.delete("/topminer/set/{sid}")
    def delete(sid: int, req: Request): return tm.delete(user(req), sid)

    @r.put("/comps/{wid}/topminer/milestones/{key}")
    def mark(wid: int, key: str, b: MarkIn, req: Request): return tm.mark(user(req), wid, key, b)

    @r.post("/comps/{wid}/topminer/mission")
    def launch(wid: int, req: Request): return tm.launch(user(req), wid)

    return r
