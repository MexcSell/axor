"""Competition teams, one deliverable per task and one release candidate (mining_work.py runs the work). From the operations
review of 2026-11-10: boards filled with repeats of "archive candidate", "strict audit" and "three-repeat benchmark", tasks
named competing candidate hashes, and benchmarks of 30 and 42 tasks were set against a 29-task reference.

- Duplicate tasks: a task the lead plans or an agent files as a follow-up is not added when an open task already asks for the
  same deliverable: the same objective (its title's words), the same candidate hashes and, when both state them, the same
  acceptance criteria. The board's existing duplicates are merged on request (`POST /comps/{wid}/dedupe`): the earliest copy
  (or the one already under way) stays, keeps one owner, and lists the copies it absorbed. Copies already under way are
  reported, never touched.
- Release manifest: one frozen candidate per team (a workspace file and its sha256, or a commit), the benchmark suite it is
  measured on (name, task count, the task ids' fingerprint, repeats, settings) and the reference score on that same suite.
  Every agent's context carries it; open tasks naming another candidate are listed as conflicts; the file changing after the
  freeze shows as drift. Freezing again makes a new version; earlier ones stay as history.
- Benchmarks: agents file results with the record_benchmark tool. A result counts only when it names the manifest's candidate
  and suite; anything else is kept but marked not comparable, with the reason, and is never set against the reference.
"""
import hashlib, json, logging, re, time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import runner
from .agents import _schema
from .mining import _clip

OPEN = ("todo", "queued", "working", "checking", "review", "blocked")
MERGEABLE = ("todo", "blocked")          # copies nobody has started: the only ones a merge removes
UNDER_WAY = ("queued", "working", "checking", "review")
SKIP_DAYS = 14                           # how long a task the duplicate check left out can still be added back
BENCH_DROP = 5.0                         # points out of 100: a measured score this far below the one before it, on the same frozen release, is a finding (L5.3)
log = logging.getLogger("mining_release")
HASH = re.compile(r"(?<![0-9a-z])(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,64}(?![0-9a-z])", re.I)
STOP = set("a an the of for to and or on in with by from into at its it this that these those run runs do make task please new "
           "again once more up out be is are was then than our your their via using use per all any each".split())
NUM = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "single": "1", "double": "2", "triple": "3", "twice": "2", "thrice": "3"}
CRIT = re.compile(r"^\s*(?:[-*•]\s*)?(?:acceptance(?: criteria)?|accept(?:ed)? when|done when|definition of done|pass(?:es)? when|success(?: criteria)?|deliverable)\b[:\s-]*(.*)$", re.I)


# ---------- duplicates ----------
def _stem(w):
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf): return w[: -len(suf)]
    return w


def words(text):
    """The objective's words: lower case, no hashes, ids or filler, numbers written as digits, light stemming."""
    t = re.sub(r"#\d+", " ", HASH.sub(" ", (text or "").lower()))
    out = set()
    for w in re.findall(r"[a-z0-9]+", t):
        w = NUM.get(w, w)
        if w in STOP or (len(w) < 2 and not w.isdigit()): continue
        out.add(_stem(w))
    return out


def hashes(text):
    """Candidate hashes a task names, as 7-character prefixes (a short and a full hash of one commit are the same candidate)."""
    return {h.lower()[:7] for h in HASH.findall(text or "")}


def criteria(detail):
    """The acceptance criteria a task states (the line after "Acceptance:", "Done when", … and its bullets), as words."""
    lines, grab, out = (detail or "").splitlines(), False, []
    for ln in lines:
        m = CRIT.match(ln)
        if m: grab = True; out.append(m.group(1)); continue
        if grab and re.match(r"^\s*(?:[-*•]|\d+[.)])\s+", ln): out.append(ln); continue
        if grab and ln.strip(): grab = False
    return words(" ".join(out))


def _jac(a, b): return len(a & b) / len(a | b) if a | b else 1.0
def _over(a, b): return len(a & b) / min(len(a), len(b)) if a and b else 0.0


class _F:
    """A task's features for comparing, worked out once (a board of hundreds compares every pair): the title's words, the hashes
    in title and detail, and the acceptance criteria only when a comparison gets that far."""
    __slots__ = ("words", "hashes", "detail", "_crit")

    def __init__(self, t):
        self.words, self.hashes = words(t.get("title")), hashes(f"{t.get('title')} {t.get('detail')}")
        self.detail, self._crit = t.get("detail"), None

    @property
    def crit(self):
        if self._crit is None: self._crit = criteria(self.detail)
        return self._crit


def _same(fa, fb):
    wa, wb = fa.words, fb.words
    if not wa or not wb: return False
    if fa.hashes != fb.hashes: return False  # another candidate is another deliverable (the manifest settles which one counts)
    ha, shared = fa.hashes, len(wa & wb)
    # a named candidate on both sides lets titles differ more ("Archive frozen candidate abc1234" ~ "Archive candidate abc1234 with manifest")
    if not (_jac(wa, wb) >= (0.4 if ha else 0.6) or (shared >= 2 and _over(wa, wb) >= (0.66 if ha else 0.75))): return False
    ca, cb = fa.crit, fb.crit
    return not (ca and cb and _jac(ca, cb) < 0.5)


def same(a, b):
    """Two tasks ask for one deliverable: the same objective, the same candidate, the same acceptance (when both state it)."""
    return _same(_F(a), _F(b))


def _cleared(db, wid, title):
    """The tasks this title was added back over: a person said it isn't a repeat of them, so it never is again."""
    try:
        return {r["dup_of"] for r in db.q("SELECT dup_of FROM mw_skipped WHERE comp_id=? AND restored IS NOT NULL AND lower(title)=?",
                                          (wid, (title or "").strip().lower()))}
    except Exception:  # noqa: BLE001 - before the table exists
        return set()


def dup_of(db, wid, title, detail=""):
    """The open task on the board that already asks for this deliverable, or None."""
    me = _F({"title": title, "detail": detail})
    if not me.words: return None
    ok = _cleared(db, wid, title)
    for t in db.q(f"SELECT id, title, detail, status, agent_id FROM mw_tasks WHERE comp_id=? AND status IN ({','.join('?' * len(OPEN))}) ORDER BY id",
                  (wid, *OPEN)):
        if t["id"] not in ok and _same(me, _F(t)): return t
    return None


def keep_off(db, wid, title, detail, dup, origin, agent_id=None, priority=None, by=""):
    """Record a task the duplicate check left off the board, so a person can add it back if the check was wrong (Release.restore)."""
    try:
        db.q("""INSERT INTO mw_skipped (comp_id, title, detail, priority, agent_id, origin, by_name, dup_of, ts) VALUES (?,?,?,?,?,?,?,?,?)""",
             (wid, _clip(title, 160), _clip(detail or "", 4000), priority if priority in ("low", "medium", "high", "urgent") else "medium",
              agent_id, origin, by or None, dup["id"], time.time()))
    except Exception:  # noqa: BLE001 - recording it never stops the plan
        pass


def groups(rows):
    """Duplicate groups among open tasks: [(keeper, [copies])]. The keeper is the copy under way, else the earliest."""
    rows, seen, out = sorted(rows, key=lambda t: t["id"]), set(), []
    F = {t["id"]: _F(t) for t in rows}
    for i, t in enumerate(rows):
        if t["id"] in seen: continue
        g = [t] + [u for u in rows[i + 1:] if u["id"] not in seen and _same(F[t["id"]], F[u["id"]])]
        if len(g) < 2: continue
        seen.update(x["id"] for x in g)
        keep = next((x for x in g if x["status"] in UNDER_WAY), g[0])
        out.append((keep, [x for x in g if x is not keep]))
    return out


# ---------- the release manifest ----------
def suite_hash(name, tasks, task_ids, repeats, settings):
    """One benchmark suite's fingerprint: its task ids when known (else its name and size), the repeats and the settings."""
    ids = sorted({str(x).strip() for x in task_ids or [] if str(x).strip()})
    body = {"ids": ids} if ids else {"name": (name or "").strip().lower(), "tasks": int(tasks or 0)}
    body.update(repeats=int(repeats or 1), settings={k: settings[k] for k in sorted(settings or {})})
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def suite_id(name, h): return f"{(name or 'suite').strip()}@{h[:8]}"


class FreezeIn(BaseModel):
    path: str = Field("", max_length=300)               # the candidate file in the workspace (its sha256 is taken now) …
    commit: str = Field("", pattern=r"^([0-9a-fA-F]{7,64})?$")  # … or a commit / artifact hash given as is
    suite: str = Field(..., min_length=1, max_length=80)
    tasks: int = Field(..., ge=1, le=100000)
    task_ids: list[str] = Field(default_factory=list, max_length=5000)
    repeats: int = Field(1, ge=1, le=100)
    settings: dict = Field(default_factory=dict)        # timeout, model, seed…: anything that changes a score
    reference_score: float | None = None
    reference_note: str = Field("", max_length=500)
    note: str = Field("", max_length=1000)
    image_digest: str = Field("", pattern=r"^(sha256:[0-9a-f]{64})?$")  # G5-4 V4.3: the candidate's container image, if it has one
    # D-034: the release's measuring job, frozen from a finished VM job of this team (its id), with the folder the candidate lives in.
    # Everything that job was sent outside that folder is its harness. Both or neither.
    measure_job: int | None = Field(None, ge=1)
    candidate_root: str = Field("", max_length=200, pattern=r"^[A-Za-z0-9_][A-Za-z0-9._/@+-]*$|^$")


class DedupeIn(BaseModel):
    keep: list[int] = Field(default_factory=list, max_length=400)  # groups (by keeper id) to merge; empty = every group


BENCH_TOOL = {"name": "record_benchmark", "strict": True,
              "description": "File a benchmark result against the team's release manifest (your context names its candidate and suite). "
                             "candidate: the exact hash you measured; suite: the suite's name; tasks: how many tasks ran; task_ids: their ids "
                             "([] if unknown); repeats: runs per task; score: the score (0-100) or -1; solved: tasks solved or -1; note: anything "
                             "that changes how to read it. A result on another candidate or suite is kept but marked not comparable.",
              "input_schema": _schema({"candidate": {"type": "string"}, "suite": {"type": "string"}, "tasks": {"type": "integer"},
                                       "task_ids": {"type": "array", "items": {"type": "string"}}, "repeats": {"type": "integer"},
                                       "score": {"type": "number"}, "solved": {"type": "integer"}, "note": {"type": "string"}})}
MANIFEST_TOOL = {"name": "release_manifest", "strict": True,
                 "description": "The team's frozen release candidate (file, sha256 or commit), its benchmark suite and reference score, "
                                "whether the file changed since, and the latest comparable benchmark results.",
                 "input_schema": _schema({})}
NAMES = ("record_benchmark", "release_manifest")


class Release:
    def __init__(self, work):
        self.w, self.db = work, work.db
        q = self.db.q
        q("""CREATE TABLE IF NOT EXISTS mw_release (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, version INTEGER, path TEXT, sha256 TEXT,
             commit_ref TEXT, suite TEXT, suite_tasks INTEGER, suite_hash TEXT, repeats INTEGER, settings TEXT, reference_score REAL,
             reference_note TEXT, note TEXT, by_user TEXT, frozen REAL, current INTEGER DEFAULT 1)""")
        q("CREATE INDEX IF NOT EXISTS mw_release_c ON mw_release (comp_id, current)")
        q("""CREATE TABLE IF NOT EXISTS mw_bench (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, release_id INTEGER, task_id INTEGER,
             agent_id INTEGER, candidate TEXT, suite TEXT, suite_tasks INTEGER, suite_hash TEXT, repeats INTEGER, score REAL, solved INTEGER,
             note TEXT, comparable INTEGER, why TEXT, ts REAL)""")
        q("CREATE INDEX IF NOT EXISTS mw_bench_c ON mw_bench (comp_id, id)")
        # G5-4 V4.3 / V4.4: two nullable columns an older release ignores. image_digest: the frozen candidate's container image
        # (sha256:…), given by the person who freezes. evidence_ref: the finished sandbox run that produced a benchmark row, taken
        # from the run that filed it, never from what an agent says.
        if "image_digest" not in {c["name"] for c in q("PRAGMA table_info(mw_release)")}: q("ALTER TABLE mw_release ADD COLUMN image_digest TEXT")
        # D-034: the measuring job a release freezes (JSON: job_sha256, harness_sha256, images, score_file, candidate_root, from_job).
        # Nullable; a release without it behaves as before, and an older version ignores the column
        if "measure" not in {c["name"] for c in q("PRAGMA table_info(mw_release)")}: q("ALTER TABLE mw_release ADD COLUMN measure TEXT")
        if "evidence_ref" not in {c["name"] for c in q("PRAGMA table_info(mw_bench)")}: q("ALTER TABLE mw_bench ADD COLUMN evidence_ref TEXT")
        q("""CREATE TABLE IF NOT EXISTS mw_skipped (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, title TEXT, detail TEXT, priority TEXT,
             agent_id INTEGER, origin TEXT, by_name TEXT, dup_of INTEGER, ts REAL, restored REAL, restored_by TEXT, restored_task INTEGER)""")
        q("CREATE INDEX IF NOT EXISTS mw_skipped_c ON mw_skipped (comp_id, id)")
        work.release = self

    # ---------- lookups ----------
    def current(self, wid):
        return self.db.q("SELECT * FROM mw_release WHERE comp_id=? AND current=1 ORDER BY id DESC LIMIT 1", (wid,), one=True)

    def _file_sha(self, wid, path):
        f = self.db.q("SELECT content FROM mw_files WHERE comp_id=? AND path=?", (wid, path), one=True)
        return hashlib.sha256((f["content"] or "").encode()).hexdigest() if f else None

    def candidate(self, r):
        return (r["sha256"] or r["commit_ref"] or "").lower()

    def drift(self, wid, r):
        """The frozen file has changed since (or is gone): True/False, None for a commit-only manifest."""
        if not r or not r["path"]: return None
        now = self._file_sha(wid, r["path"])
        return now != r["sha256"]

    def _pub(self, wid, r):
        if not r: return None
        return {"id": r["id"], "version": r["version"], "path": r["path"], "sha256": r["sha256"], "commit": r["commit_ref"],
                "candidate": self.candidate(r)[:12], "suite": r["suite"], "suite_id": suite_id(r["suite"], r["suite_hash"]),
                "suite_tasks": r["suite_tasks"], "repeats": r["repeats"], "settings": json.loads(r["settings"] or "{}"),
                "reference_score": r["reference_score"], "reference_note": r["reference_note"], "note": r["note"], "by": r["by_user"],
                "frozen": r["frozen"], "drift": self.drift(wid, r),
                "image_digest": dict(r).get("image_digest"), "measure": self.measure(r)}

    @staticmethod
    def measure(r):
        """D-034: the release's frozen measuring job ({job_sha256, harness_sha256, images, score_file, candidate_root, from_job}), or None."""
        try: m = json.loads(dict(r or {}).get("measure") or "null")
        except ValueError: m = None
        return m if isinstance(m, dict) and m.get("job_sha256") and m.get("harness_sha256") else None

    def conflicts(self, wid, r):
        """Open tasks that name a candidate other than the frozen one."""
        if not r: return []
        mine, out = self.candidate(r)[:7], []
        for t in self.db.q(f"SELECT id, title, detail, status FROM mw_tasks WHERE comp_id=? AND status IN ({','.join('?' * len(OPEN))}) ORDER BY id",
                           (wid, *OPEN)):
            other = sorted(h for h in hashes(f"{t['title']} {t['detail']}") if h != mine)
            if other: out.append({"id": t["id"], "title": t["title"], "status": t["status"], "names": other})
        return out

    def candidates_seen(self, wid):
        """Every hash the open board names, how often: what the user picks the one candidate from."""
        n = {}
        for t in self.db.q(f"SELECT title, detail FROM mw_tasks WHERE comp_id=? AND status IN ({','.join('?' * len(OPEN))})", (wid, *OPEN)):
            for h in hashes(f"{t['title']} {t['detail']}"): n[h] = n.get(h, 0) + 1
        return sorted(({"hash": h, "tasks": k} for h, k in n.items()), key=lambda x: -x["tasks"])[:12]

    def dupes(self, wid):
        rows = self.db.q(f"SELECT id, title, detail, status, agent_id FROM mw_tasks WHERE comp_id=? AND status IN ({','.join('?' * len(OPEN))})",
                         (wid, *OPEN))
        names = {a["id"]: a["name"] for a in self.w._agents(wid)}
        pub = lambda t: {"id": t["id"], "title": t["title"], "status": t["status"], "agent": names.get(t["agent_id"])}
        out = []
        for keep, copies in groups(rows):
            out.append({"keep": pub(keep), "copies": [pub(c) for c in copies],
                        "mergeable": sum(c["status"] in MERGEABLE for c in copies),
                        "under_way": sum(c["status"] in UNDER_WAY for c in copies)})
        return out

    def skipped(self, wid):
        """Tasks the duplicate check left off the board in the last SKIP_DAYS days, newest first, each with the task it repeats."""
        rows = self.db.q("""SELECT s.*, t.title dup_title, t.status dup_status FROM mw_skipped s LEFT JOIN mw_tasks t ON t.id=s.dup_of
                            WHERE s.comp_id=? AND s.restored IS NULL AND s.ts>? ORDER BY s.id DESC LIMIT 20""", (wid, time.time() - SKIP_DAYS * 86400))
        return [{"id": r["id"], "title": r["title"], "detail": _clip(r["detail"] or "", 300), "by": r["by_name"], "ts": r["ts"],
                 "origin": "plan" if (r["origin"] or "").startswith("plan:") else "follow-up",
                 "dup": {"id": r["dup_of"], "title": r["dup_title"], "status": r["dup_status"]}} for r in rows]

    # ---------- what agents read ----------
    def lines(self, w):
        r = self.current(w["id"])
        if not r:
            return ("Release discipline: no release candidate is frozen yet. If you audit, archive or benchmark, name the exact file hash "
                    "(sha256) or commit you measured, file benchmark results with record_benchmark, and propose the candidate to freeze; "
                    "don't open a second audit or benchmark of something already on the board.")
        p = self._pub(w["id"], r)
        cand = f"{p['path']} sha256 {r['sha256'][:12]}" if p["path"] else f"commit {p['commit'][:12]}"
        drift = " The file has CHANGED since it was frozen: say so in any result, and ask the user to freeze again." if p["drift"] else ""
        ref = f"; reference score {p['reference_score']:g} on this same suite" if p["reference_score"] is not None else "; no reference score yet"
        return (f"Release manifest v{p['version']} (frozen {time.strftime('%Y-%m-%d %H:%M', time.gmtime(p['frozen']))} UTC): candidate {cand}. "
                f"Benchmark suite {p['suite_id']}: {p['suite_tasks']} tasks × {p['repeats']} repeat{'s' if p['repeats'] != 1 else ''}{ref}.{drift} "
                "Every audit, archive and benchmark names this exact candidate and suite, and files results with record_benchmark. "
                "A result on another candidate or another task set isn't comparable: don't plan one unless the user changes the manifest, "
                "and don't open a second task for a deliverable already on the board.")

    def tools(self): return [MANIFEST_TOOL, BENCH_TOOL]

    def call(self, w, a, tid, name, args, run=None):
        wid = w["id"]
        r = self.current(wid)
        if name == "release_manifest":
            if not r: return {"manifest": None, "note": "No release candidate is frozen yet: the user freezes one in Status → Release."}
            return {"manifest": self._pub(wid, r), "results": self.results(wid, 8)["results"]}
        out = self.record(wid, r, args, task=tid, agent=a["id"] if a else None, run=run)
        if a: self.w._event(wid, "bench", f"{a['name']} recorded a benchmark: {out['line']}", agent=a["id"], task=tid)
        return out

    # ---------- benchmarks ----------
    def evidence(self, wid, run):
        """G5-4 V4.4: the evidence a benchmark row rests on: the newest sandbox run of the calling agent run that finished
        cleanly (status done, exit 0). None without a calling run (a person's entry) or without such a sandbox run.
        V4.2 (Q-4): when that run is a VM runner job that returned a score from its own output file, the reference is
        `job:<id>` and the row's score is that file's (measured()); otherwise `sbx:<id>`: a clean run happened, the score is the agent's."""
        if not run: return None
        s = self.db.q("""SELECT id, services FROM mw_sbx WHERE comp_id=? AND run_id=? AND status='done' AND exit_code=0 AND finished IS NOT NULL
                         ORDER BY id DESC LIMIT 1""", (wid, run), one=True)
        if not s: return None
        return f"job:{s['id']}" if s["services"] == runner.SERVICE and self.measured(wid, f"job:{s['id']}") else f"sbx:{s['id']}"

    def measured(self, wid, ref, release=None):
        """The score a VM runner job read from its own output ({"score", "solved"?, "tasks"?}), for an evidence reference
        `job:<id>` of this team; None for anything else, or when the job's kept result is gone, edited or has no score.
        release (D-034): when it has a frozen measuring job, the job must also be that job; another job's score is None here."""
        m = re.fullmatch(r"job:(\d+)", ref or "")
        d = runner.stored(self.db, wid, int(m[1])) if m else None
        sc = (d or {}).get("score")
        if not (isinstance(sc, dict) and isinstance(sc.get("score"), (int, float))): return None
        frozen = self.measure(release)
        return None if frozen and runner.differs(d, frozen) else sc

    def not_measuring(self, wid, ref, release):
        """Why a job that returned a score isn't the release's measuring job, in words; "" when it is, or the release has none."""
        frozen, m = self.measure(release), re.fullmatch(r"job:(\d+)", ref or "")
        d = runner.stored(self.db, wid, int(m[1])) if frozen and m else None
        return runner.differs(d, frozen) if d else ""

    def record(self, wid, r, x, task=None, agent=None, run=None):
        cand = HASH.findall(str(x.get("candidate") or ""))
        cand = cand[0].lower() if cand else ""
        name = _clip((x.get("suite") or "").strip(), 80) or "suite"
        tasks, reps = max(0, int(x.get("tasks") or 0)), max(1, int(x.get("repeats") or 1))
        ids = [str(i)[:120] for i in (x.get("task_ids") or [])][:5000]
        score = x.get("score"); score = None if score is None or score < 0 else float(score)
        solved = x.get("solved"); solved = None if solved is None or solved < 0 else int(solved)
        why = []
        if not r: why.append("no release manifest is frozen yet")
        else:
            settings = json.loads(r["settings"] or "{}")
            mine = self.candidate(r)
            if not cand: why.append("it names no candidate hash")
            elif not (mine.startswith(cand) or cand.startswith(mine)):  # a short and a full hash of one candidate match
                why.append(f"candidate {cand[:12]} isn't the frozen {mine[:12]}")
            if name.lower() != (r["suite"] or "").lower(): why.append(f"suite “{name}” isn't the manifest's “{r['suite']}”")
            if tasks != r["suite_tasks"]: why.append(f"{tasks} tasks against the suite's {r['suite_tasks']}")
            if reps != r["repeats"]: why.append(f"{reps} repeats against the suite's {r['repeats']}")
            frozen_ids = r["suite_hash"] != suite_hash(r["suite"], r["suite_tasks"], [], r["repeats"], settings)  # the suite was frozen with its task ids
            if ids and frozen_ids and suite_hash(name, tasks, ids, reps, settings) != r["suite_hash"] and not why:
                why.append("a different task set than the frozen suite")
        h = suite_hash(name, tasks, ids, reps, json.loads(r["settings"] or "{}") if r else {})
        ok = not why
        ev = self.evidence(wid, run)  # from the calling run only: an agent can't name one
        got, filed = self.measured(wid, ev, r), score
        other = self.not_measuring(wid, ev, r)  # D-034: a job gave a score, but it isn't the job this release measures with
        if other: why.append(other)
        if got:  # Q-4: the job's own output file gives the score; what the agent wrote is kept in the note when it differs
            score, solved = got["score"], got.get("solved", solved)
            if got.get("tasks") is not None and got["tasks"] != tasks: why.append(f"the job's score file counts {got['tasks']} tasks, the result says {tasks}")
            if filed is not None and abs(filed - score) > 1e-9: x = {**x, "note": f"[filed as {filed:g}; the job's output file says {score:g}] {x.get('note') or ''}"}
        ok = not why
        self.db.q("""INSERT INTO mw_bench (comp_id, release_id, task_id, agent_id, candidate, suite, suite_tasks, suite_hash, repeats, score, solved, note,
                     comparable, why, ts, evidence_ref) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (wid, r["id"] if r else None, task, agent, cand, name, tasks, r["suite_hash"] if ok else h, reps, score, solved,
                   _clip(x.get("note"), 1000), int(ok), "; ".join(why) or None, time.time(), ev))
        if ok and got:  # L5.3: a measured row on the frozen release; a drop against the measured one before it is a finding
            try: self.watch(wid, r, self.db.q("SELECT MAX(id) id FROM mw_bench WHERE comp_id=?", (wid,), one=True)["id"], score, ev)
            except Exception as e:  # noqa: BLE001 - the row is recorded either way
                log.warning("benchmark watch for team %s: %s", wid, e)
        delta = (score - r["reference_score"]) if ok and score is not None and r["reference_score"] is not None else None
        line = (f"{'' if score is None else f'{score:g}'}{'' if solved is None else f' ({solved}/{tasks} solved)'} on {name}, candidate {cand[:12] or '?'}"
                + (f", {delta:+.1f} against the reference" if delta is not None else "") + ("" if ok else f" — not comparable: {'; '.join(why)}"))
        return {"recorded": True, "comparable": ok, "why": why, "delta": delta, "line": line.strip(), "evidence_ref": ev,
                "score": score, "score_source": "job_output" if got else "filed",
                "note": ("Counted against the manifest." if ok else "Kept, but not comparable to the reference: don't report it as an improvement.")
                + ((" The score is the one the release's measuring job wrote." if self.measure(r) else
                    " The score is the one the job's output file gave, but no measuring job is frozen, so nothing shows the job ran the "
                    "official scorer: call it a job's score, never the official result.") if got else
                   " The score is self-reported (no job's output file gave it): call it that wherever you cite it, never the official result.")
                + ("" if ev else " No finished sandbox run in this run backs it, so it isn't measured evidence: run the benchmark with sandbox_run"
                   " (exit 0) in this same run before filing it.")}

    # ---------- runtime monitoring (G5-5 L5.3): the frozen release's measured score dropped ----------
    def _before(self, wid, r, row_id):
        """The newest measured row on this release before `row_id`: comparable, on the release's suite, its score the one its
        VM job's own output file gave (the kept result intact). None when there is none."""
        for b in self.db.q("""SELECT id, score, evidence_ref, ts FROM mw_bench WHERE comp_id=? AND release_id=? AND suite_hash=? AND comparable=1 AND score IS NOT NULL
                              AND id<? ORDER BY id DESC LIMIT 20""", (wid, r["id"], r["suite_hash"], row_id)):
            got = self.measured(wid, b["evidence_ref"], r)
            if got and abs(got["score"] - b["score"]) < 1e-9: return {"row": b["id"], "score": b["score"], "evidence_ref": b["evidence_ref"], "ts": b["ts"]}
        return None

    def watch(self, wid, r, row_id, score, ev):
        """One measured benchmark of the team's frozen release, set against the measured one before it on the same release (the
        same artifact and suite, so the candidate didn't change: its surroundings did). A score more than BENCH_DROP points
        lower opens the team's register row `bench:comp:<id>` (source "monitor"), which keeps the score it fell from as its
        reference. A later measured score back within BENCH_DROP of that reference resolves it; so does freezing another
        release. Technical evidence about one artifact: never a competition result. Returns "opened", "open", "resolved" or None."""
        from . import orchestrator  # at call time: the orchestrator is set up after the board
        own = self.db.q("SELECT p.user_id FROM mw_comps w JOIN mh_campaigns p ON p.id=w.campaign_id WHERE w.id=?", (wid,), one=True)
        uid, rkey = (own or {}).get("user_id"), f"bench:comp:{wid}"
        if uid is None: return None
        cur = self.db.q("SELECT status, evidence FROM io_risks WHERE owner_id=? AND rkey=?", (uid, rkey), one=True)
        held = json.loads(cur["evidence"] or "{}") if cur and cur["status"] != "resolved" else None
        if held and held.get("release") != r["id"]:
            orchestrator.risk_resolve(uid, rkey, f"Release #{r['id']} was frozen since: the finding was about release #{held.get('release')}.")
            held = None
        ref = (held or {}).get("reference") or self._before(wid, r, row_id)
        if not ref: return None
        scale = 100.0 if max(ref["score"], score) <= 1 else 1.0
        drop = round((ref["score"] - score) * scale, 4)
        now_ = {"row": row_id, "score": score, "evidence_ref": ev, "ts": time.time()}
        if drop <= BENCH_DROP:
            if held: orchestrator.risk_resolve(uid, rkey, f"Benchmark row #{row_id} measured {score:g} ({ev}), within {BENCH_DROP:g} points of {ref['score']:g} again.")
            return "resolved" if held else None
        text = f"the frozen release's measured score fell from {ref['score']:g} to {score:g} on the same candidate and suite"
        if not held: self.w._event(wid, "error", f"Benchmark watch: {text} (rows #{ref['row']} and #{row_id}).")
        orchestrator.risk_upsert(uid, rkey, {"release": r["id"], "suite_hash": r["suite_hash"], "candidate": self.candidate(r)[:12], "reference": ref, "latest": now_,
                                             "drop_points": drop, "threshold_points": BENCH_DROP},
                                 mission=f"comp:{wid}", layer="execution", source="monitor", source_ref=f"release:{r['id']}", probability="observed", critical=0,
                                 title=f"Benchmark score dropped on the frozen release (comp:{wid})"[:200],
                                 description=f"{text[0].upper() + text[1:]}: {drop:g} points, more than the {BENCH_DROP:g} this watch allows. Both scores were read from VM jobs' own output files.",
                                 root_cause="The candidate and the suite are frozen, so something around them changed: the competition's API or data, a dependency, "
                                            "the environment, or the benchmark is noisier than this threshold.",
                                 impact={"mission": f"comp:{wid}", "scope": f"comp:{wid}", "release": r["id"]}, severity="medium", priority="medium",
                                 responsible="the team's lead and the Owner", approval="none: the register only reports; a person decides what the drop means",
                                 detection="every measured benchmark on the frozen release is set against the measured one before it",
                                 countermeasure=f"Compare the two jobs' results ({ref['evidence_ref']} and {ev}): images, environment and output. Run the benchmark again to tell a change from noise.")
        return "open" if held else "opened"

    def _source(self, wid, r, b):
        """Where a row's score came from: measuring_job (the current release's frozen measuring job wrote it), job_output (a VM
        job's output file wrote it, but no measuring job says that job was the official scorer), or self_reported (typed)."""
        rel = r if r and b["release_id"] == r["id"] else None
        m = self.measured(wid, dict(b).get("evidence_ref"), rel)  # None when the release measures with another job
        if not m or b["score"] is None or abs(m["score"] - b["score"]) >= 1e-9: return "self_reported"
        return "measuring_job" if self.measure(rel) else "job_output"

    def results(self, wid, limit=40):
        r = self.current(wid)
        rows = self.db.q("""SELECT b.*, a.name agent FROM mw_bench b LEFT JOIN mw_agents a ON a.id=b.agent_id WHERE b.comp_id=? ORDER BY b.id DESC LIMIT ?""",
                         (wid, limit))
        out = []
        for b in rows:
            cur = bool(r and b["release_id"] == r["id"] and b["comparable"])
            out.append({"id": b["id"], "task": b["task_id"], "agent": b["agent"], "candidate": (b["candidate"] or "")[:12],
                        "suite": suite_id(b["suite"], b["suite_hash"] or ""), "tasks": b["suite_tasks"], "repeats": b["repeats"],
                        "score": b["score"], "solved": b["solved"], "comparable": bool(b["comparable"]), "current": cur, "why": b["why"],
                        "delta": (b["score"] - r["reference_score"]) if cur and b["score"] is not None and r["reference_score"] is not None else None,
                        "note": b["note"], "ts": b["ts"], "evidence_ref": dict(b).get("evidence_ref"),
                        "source": self._source(wid, r, b)})
        return {"results": out, "comparable": sum(x["current"] for x in out), "other": sum(not x["current"] for x in out)}

    # ---------- the user's side ----------
    def view(self, me, wid):
        self.w._own(me, wid)
        r = self.current(wid)
        hist = self.db.q("SELECT * FROM mw_release WHERE comp_id=? ORDER BY id DESC LIMIT 10", (wid,))
        files = [f["path"] for f in self.db.q("SELECT path FROM mw_files WHERE comp_id=? ORDER BY path LIMIT 300", (wid,))]
        d = self.dupes(wid)
        return {"manifest": self._pub(wid, r), "history": [self._pub(wid, h) for h in hist if not r or h["id"] != r["id"]],
                "conflicts": self.conflicts(wid, r), "seen": self.candidates_seen(wid), "files": files,
                "dupes": d, "dupe_tasks": sum(len(g["copies"]) for g in d), "skipped": self.skipped(wid), **self.results(wid)}

    def freeze(self, me, wid, b: FreezeIn):
        w, _ = self.w._own(me, wid)
        path = b.path.strip().lstrip("/")
        sha = self._file_sha(wid, path) if path else None
        if path and not sha: raise HTTPException(404, f"There's no {path} in the team's files.")
        if not sha and not b.commit: raise HTTPException(422, "Name the candidate: a file in the team's files, or a commit / artifact hash.")
        settings = {str(k)[:60]: v for k, v in list((b.settings or {}).items())[:30]}
        h = suite_hash(b.suite, b.tasks, b.task_ids, b.repeats, settings)
        measure = None
        if b.measure_job or b.candidate_root.strip():  # D-034: the measuring job is frozen with the release, from a finished job of this team
            root = b.candidate_root.strip().strip("/")
            if not b.measure_job or not root: raise HTTPException(422, "To freeze the measuring job, name both: the finished job to take it from, and the folder the candidate lives in.")
            d = runner.stored(self.db, wid, b.measure_job)
            if not d: raise HTTPException(404, f"Job #{b.measure_job} isn't a VM job of this team that finished cleanly with its result kept.")
            measure = runner.measure_of(d, root)
            if not measure: raise HTTPException(422, f"Job #{b.measure_job} can't be a measuring job: it names no score file, or its result holds no file list (it ran before this was recorded).")
            if not any(p.startswith(root + "/") for p in (d.get("inputs") or {}).get("tree") or {}):
                raise HTTPException(422, f"Job #{b.measure_job} was sent no file under {root}/: that isn't where its candidate lives.")
            measure["from_job"] = b.measure_job
        with self.w.lock:
            prev = self.current(wid)
            ver = (self.db.q("SELECT MAX(version) v FROM mw_release WHERE comp_id=?", (wid,), one=True)["v"] or 0) + 1
            self.db.q("UPDATE mw_release SET current=0 WHERE comp_id=?", (wid,))
            self.db.q("""INSERT INTO mw_release (comp_id, version, path, sha256, commit_ref, suite, suite_tasks, suite_hash, repeats, settings, reference_score,
                         reference_note, note, by_user, frozen, current, image_digest, measure) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)""",
                      (wid, ver, path or None, sha, b.commit.lower() or None, b.suite.strip(), b.tasks, h, b.repeats, json.dumps(settings),
                       b.reference_score, b.reference_note.strip() or None, b.note.strip() or None, me["username"], time.time(), b.image_digest or None,
                       json.dumps(measure) if measure else None))
        cand = f"{path} ({sha[:12]})" if sha else b.commit[:12]
        self.w._event(wid, "release", f"{me['username']} froze release v{ver}: {cand} on suite {suite_id(b.suite, h)}"
                      + (f", image {b.image_digest[:19]}…" if b.image_digest else "")
                      + (f", measuring job frozen from job #{b.measure_job} (candidate under {measure['candidate_root']}/)" if measure else "")
                      + (f" (was v{prev['version']})" if prev else ""))
        return self.view(me, wid)

    def dedupe(self, me, wid, b: DedupeIn):
        w, _ = self.w._own(me, wid)
        merged, kept = 0, []
        with self.w.lock:
            rows = self.db.q(f"SELECT id, title, detail, status, agent_id FROM mw_tasks WHERE comp_id=? AND status IN ({','.join('?' * len(OPEN))})",
                             (wid, *OPEN))
            names = {a["id"]: a["name"] for a in self.w._agents(wid)}
            for keep, copies in groups(rows):
                if b.keep and keep["id"] not in b.keep: continue
                gone = [c for c in copies if c["status"] in MERGEABLE]
                if not gone: continue
                owner = keep["agent_id"] or next((c["agent_id"] for c in gone if c["agent_id"]), None)  # one owner: the keeper's, else a copy's
                note = "Merged duplicates (same objective, candidate and acceptance): " + ", ".join(
                    f"#{c['id']}" + (f" ({names[c['agent_id']]})" if c["agent_id"] in names else "") for c in gone)
                self.db.q("UPDATE mw_tasks SET detail=?, agent_id=?, updated=? WHERE id=?",
                          (_clip(f"{keep['detail'] or ''}\n\n{note}".strip(), 8000), owner, time.time(), keep["id"]))
                self.db.q(f"DELETE FROM mw_tasks WHERE id IN ({','.join('?' * len(gone))})", tuple(c["id"] for c in gone))
                merged += len(gone); kept.append(keep["id"])
        if merged:
            self.w._event(wid, "task", f"{me['username']} merged {merged} duplicate task{'s' if merged != 1 else ''} into "
                          + ", ".join(f"#{k}" for k in kept))
        return {"merged": merged, "kept": kept, **self.view(me, wid)}


    def restore(self, me, wid, sid):
        """Add back a task the duplicate check left out: it goes on the board as it was asked for, and its title is never
        counted as a repeat of that task again."""
        from . import mining_work  # here: mining_work imports this module
        self.w._own(me, wid)
        with self.w.lock:
            s = self.db.q("SELECT * FROM mw_skipped WHERE id=? AND comp_id=?", (sid, wid), one=True)
            if not s: raise HTTPException(404, "That left-out task isn't here.")
            if s["restored"]: raise HTTPException(409, f"It was added back already (#{s['restored_task']}).")
            now = time.time()
            self.db.q("""INSERT INTO mw_tasks (comp_id, title, detail, status, priority, agent_id, due, origin, created, updated, mission)
                         VALUES (?,?,?,'todo',?,?,'',?,?,?,?)""", (wid, s["title"], s["detail"], s["priority"] or "medium", s["agent_id"],
                                                                  f"restored:{sid}", now, now, mining_work.mission_of_origin(self.db, s["origin"])))
            tid = self.db.q("SELECT MAX(id) i FROM mw_tasks WHERE comp_id=?", (wid,), one=True)["i"]
            self.db.q("UPDATE mw_skipped SET restored=?, restored_by=?, restored_task=? WHERE id=?", (now, me["username"], tid, sid))
        self.w._event(wid, "task", f"{me['username']} added back “{s['title']}” as #{tid}: the duplicate check had left it out as a repeat of #{s['dup_of']}")
        return {"task": tid, **self.view(me, wid)}


def build(work, require):
    r = APIRouter(prefix="/api/mining/work")
    gate = work.m.hub.gate if work.m.hub else (lambda me: me)
    user = lambda req: gate(require(req))
    rel = Release(work)
    r.state = {"release": rel}

    @r.get("/comps/{wid}/release")
    def view(wid: int, req: Request): return rel.view(user(req), wid)

    @r.post("/comps/{wid}/release")
    def freeze(wid: int, b: FreezeIn, req: Request): return rel.freeze(user(req), wid, b)

    @r.post("/comps/{wid}/dedupe")
    def dedupe(wid: int, b: DedupeIn, req: Request): return rel.dedupe(user(req), wid, b)

    @r.post("/comps/{wid}/skipped/{sid}/restore")
    def restore(wid: int, sid: int, req: Request): return rel.restore(user(req), wid, sid)

    return r
