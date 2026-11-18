"""G5-4 V4.3 and V4.4: frozen releases carry the candidate's image digest; benchmark rows carry an evidence reference to the sandbox
run that produced them, taken from the run that filed them (never from what an agent says); and D-004's internal measure reads a
benchmark as valid only when it is comparable, on the team's current frozen release, and rests on a sandbox run that finished
cleanly. Technical evidence only: it never makes the competition outcome PASS.

- V4.3: freeze accepts image_digest (sha256:<64 hex> or nothing), keeps it, shows it; an older table gains the column.
- V4.4 (record): evidence_ref = sbx:<id> of the calling run's newest sandbox run with status done and exit 0, in the same team;
  none without a calling run, with only failed runs, or with another run's or team's sandbox run; an agent-supplied value is ignored.
- V4.4 (D-004 reader): valid / unverifiable / stale / missing per EVIDENCE_PROVENANCE_SPEC.md; reading writes nothing.
"""
import os, sys, tempfile, threading, time, types, unittest

from pydantic import ValidationError

sys.path.insert(0, os.path.dirname(__file__))
from app import mining_release as R  # noqa: E402
from app.auth import AuthDB  # noqa: E402
import test_mission_persistent_evidence as tp  # noqa: E402  (imported as a module so its own tests don't run again here)

WID, RUN, CAND = 7, 41, "abc1234def5678"
DIGEST = "sha256:" + "ab" * 32


def sbx_table(q):
    """mw_sbx as mining_work creates it (the columns the evidence reads)."""
    q("""CREATE TABLE IF NOT EXISTS mw_sbx (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, task_id INTEGER, run_id INTEGER, agent_id INTEGER,
         by_user TEXT, command TEXT, services TEXT, status TEXT, exit_code INTEGER, output TEXT, error TEXT, started REAL, finished REAL,
         cost REAL DEFAULT 0, calls INTEGER DEFAULT 0, pod TEXT)""")


def sbx(q, comp, run, status="done", code=0, finished=True):
    return q("INSERT INTO mw_sbx (comp_id, run_id, status, exit_code, started, finished, pod) VALUES (?,?,?,?,?,?,?) RETURNING id",
             (comp, run, status, code, time.time() - 60, time.time() if finished else None, f"pod-{run}"), one=True)["id"]


def own_tests(cls):
    """Run only the tests this class defines, not the ones inherited from the fixture's test case."""
    for base in cls.__mro__[1:]:
        for n in vars(base):
            if n.startswith("test") and n not in vars(cls): setattr(cls, n, None)
    return cls


class Release(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = db = AuthDB(os.path.join(self.tmp.name, "t.db"))
        db.q("""CREATE TABLE mw_tasks (id INTEGER PRIMARY KEY, comp_id INTEGER, title TEXT, detail TEXT, status TEXT, agent_id INTEGER,
                priority TEXT, due TEXT, origin TEXT, created REAL, updated REAL, mission TEXT)""")
        db.q("CREATE TABLE mw_files (id INTEGER PRIMARY KEY, comp_id INTEGER, path TEXT, content TEXT)")
        db.q("CREATE TABLE mw_agents (id INTEGER PRIMARY KEY, name TEXT)")
        sbx_table(db.q)
        self.events = []
        work = types.SimpleNamespace(db=db, lock=threading.Lock(), _own=lambda me, wid: ({"id": wid}, {"id": 1}), _agents=lambda wid: [],
                                     _event=lambda wid, kind, text, **k: self.events.append(text))
        self.rel, self.me = R.Release(work), {"id": 1, "username": "leo"}

    def tearDown(self):
        try: self.db.db.close()  # on Postgres an AuthDB holds a connection for as long as it lives (PX-R13)
        except Exception: pass   # noqa: BLE001
        self.tmp.cleanup()

    def freeze(self, **kw):
        return self.rel.freeze(self.me, WID, R.FreezeIn(commit=CAND, suite="swe-mini", tasks=3, repeats=1, **kw))

    def bench(self, run=None, **extra):
        return self.rel.record(WID, self.rel.current(WID), {"candidate": CAND, "suite": "swe-mini", "tasks": 3, "repeats": 1, "score": 71, **extra},
                               task=5, agent=1, run=run)

    # ---------- V4.3 ----------
    def test_freeze_keeps_the_image_digest(self):
        v = self.freeze(image_digest=DIGEST)
        self.assertEqual(v["manifest"]["image_digest"], DIGEST)
        self.assertEqual(self.rel.current(WID)["image_digest"], DIGEST)
        self.assertIn("image sha256:abab", self.events[-1])

    def test_no_digest_is_allowed_and_stays_empty(self):
        self.assertIsNone(self.freeze()["manifest"]["image_digest"])

    def test_a_malformed_digest_is_refused(self):
        for bad in ("abab", "sha256:" + "ab" * 31, "sha256:" + "AB" * 32, "md5:" + "ab" * 16):
            with self.assertRaises(ValidationError): R.FreezeIn(commit=CAND, suite="s", tasks=1, image_digest=bad)

    def test_an_older_table_gains_both_columns(self):
        with tempfile.TemporaryDirectory() as d:
            db = AuthDB(os.path.join(d, "old.db"))
            db.q("""CREATE TABLE mw_release (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, version INTEGER, path TEXT, sha256 TEXT,
                    commit_ref TEXT, suite TEXT, suite_tasks INTEGER, suite_hash TEXT, repeats INTEGER, settings TEXT, reference_score REAL,
                    reference_note TEXT, note TEXT, by_user TEXT, frozen REAL, current INTEGER DEFAULT 1)""")
            db.q("""CREATE TABLE mw_bench (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, release_id INTEGER, task_id INTEGER,
                    agent_id INTEGER, candidate TEXT, suite TEXT, suite_tasks INTEGER, suite_hash TEXT, repeats INTEGER, score REAL, solved INTEGER,
                    note TEXT, comparable INTEGER, why TEXT, ts REAL)""")
            db.q("INSERT INTO mw_bench (comp_id, score, comparable) VALUES (1, 50, 1)")
            R.Release(types.SimpleNamespace(db=db))
            R.Release(types.SimpleNamespace(db=db))  # twice: idempotent
            self.assertIn("image_digest", {c["name"] for c in db.q("PRAGMA table_info(mw_release)")})
            self.assertIn("evidence_ref", {c["name"] for c in db.q("PRAGMA table_info(mw_bench)")})
            self.assertIsNone(db.q("SELECT evidence_ref FROM mw_bench", one=True)["evidence_ref"])  # old rows stay without one

    # ---------- V4.4: record ----------
    def test_evidence_is_the_calling_runs_clean_sandbox_run(self):
        self.freeze()
        sbx(self.db.q, WID, RUN, "failed", 1)
        good = sbx(self.db.q, WID, RUN)
        out = self.bench(run=RUN)
        self.assertTrue(out["comparable"])
        self.assertEqual(out["evidence_ref"], f"sbx:{good}")
        self.assertEqual(self.db.q("SELECT evidence_ref FROM mw_bench ORDER BY id DESC", one=True)["evidence_ref"], f"sbx:{good}")
        self.assertEqual(self.rel.results(WID)["results"][0]["evidence_ref"], f"sbx:{good}")

    def test_no_evidence_without_a_clean_run_of_its_own(self):
        self.freeze()
        sbx(self.db.q, WID, RUN, "failed", 1)
        sbx(self.db.q, WID, RUN, "timeout", 124)
        sbx(self.db.q, WID, RUN, "done", 0, finished=False)
        sbx(self.db.q, WID, RUN + 1)              # another run's clean sandbox run
        sbx(self.db.q, WID + 1, RUN)              # another team's, same run id
        out = self.bench(run=RUN)
        self.assertIsNone(out["evidence_ref"])
        self.assertIn("isn't measured evidence", out["note"])
        self.assertIsNone(self.bench(run=None)["evidence_ref"])  # a person's entry: no calling run

    def test_an_agent_cant_supply_the_reference(self):
        self.freeze()
        forged = sbx(self.db.q, WID, RUN + 9)
        self.assertIsNone(self.bench(run=RUN, evidence_ref=f"sbx:{forged}")["evidence_ref"])

    def test_the_tool_passes_the_calling_run(self):
        self.freeze()
        good = sbx(self.db.q, WID, RUN)
        out = self.rel.call({"id": WID}, {"id": 1, "name": "Gus"}, 5, "record_benchmark",
                            {"candidate": CAND, "suite": "swe-mini", "tasks": 3, "repeats": 1, "score": 70}, run=RUN)
        self.assertEqual(out["evidence_ref"], f"sbx:{good}")


@own_tests
class Reader(tp.Base):
    """D-004's internal measure (missions._ev_bench) on G5-4 V4.4's evidence."""
    def setUp(self):
        super().setUp()
        R.Release(types.SimpleNamespace(db=self.db))
        sbx_table(self.db.q)
        self.rel_id = self.release(1)

    def tearDown(self):
        db = self.db
        super().tearDown()
        try: db.db.close()       # as above
        except Exception: pass   # noqa: BLE001

    def release(self, version, digest=DIGEST):
        self.db.q("UPDATE mw_release SET current=0 WHERE comp_id=?", (tp.WID,))
        return self.db.q("""INSERT INTO mw_release (comp_id, version, commit_ref, sha256, suite, suite_tasks, suite_hash, repeats, frozen, current, image_digest)
                            VALUES (?, ?, ?, NULL, 'swe-mini', 3, 'h1', 1, ?, 1, ?) RETURNING id""", (tp.WID, version, CAND, time.time(), digest), one=True)["id"]

    def row(self, score, ref=None, release=None, comparable=1):
        self.db.q("""INSERT INTO mw_bench (comp_id, release_id, candidate, suite, suite_tasks, suite_hash, repeats, score, comparable, ts, evidence_ref)
                     VALUES (?, ?, ?, 'swe-mini', 3, 'h1', 1, ?, ?, ?, ?)""", (tp.WID, release or self.rel_id, CAND, score, comparable, time.time(), ref))

    def bench(self, target=0.8):
        return tp.bench_measure() | {"target": target}  # created after a chain measure: a persistent mission needs an external one (D4.2)

    def test_valid_with_a_clean_sandbox_run_on_the_current_release(self):
        s = sbx(self.db.q, tp.WID, RUN)
        self.row(0.9, f"sbx:{s}")
        e = self.one(self.create([tp.chain_measure(), self.bench()], keys=[]), 1)
        self.assertEqual((e["status"], e["value"], e["pass"], e["category"]), ("valid", 0.9, True, "internal"))
        ref = e["evidence_ref"]
        self.assertEqual((ref["sandbox_run"], ref["release"], ref["commit"], ref["suite_hash"], ref["image_digest"], ref["pod"]),
                         (f"sbx:{s}", self.rel_id, CAND, "h1", DIGEST, f"pod-{RUN}"))
        self.assertEqual(e["basis"]["kind"], "internal_measured")

    def test_a_failing_score_is_a_valid_fail(self):
        self.row(0.5, f"sbx:{sbx(self.db.q, tp.WID, RUN)}")
        ev = self.ev(self.create([tp.chain_measure(), self.bench()], keys=[]))
        self.assertEqual((ev["measures"][1]["status"], ev["measures"][1]["pass"]), ("valid", False))
        self.assertEqual(ev["dimensions"]["technical"]["value"], "FAIL")

    def test_the_newest_backed_row_wins_over_a_newer_unbacked_one(self):
        self.row(0.9, f"sbx:{sbx(self.db.q, tp.WID, RUN)}")
        self.row(0.1)  # newer, no reference
        e = self.one(self.create([tp.chain_measure(), self.bench()], keys=[]), 1)
        self.assertEqual((e["status"], e["value"]), ("valid", 0.9))

    def test_unverifiable_without_a_reference_or_a_clean_run(self):
        mid = self.create([tp.chain_measure(), self.bench()], keys=[])  # one persistent mission per team: reused below
        self.row(0.9)
        e = self.one(mid, 1)
        self.assertEqual((e["status"], e["pass"]), ("unverifiable", None))
        for ref in (f"sbx:{sbx(self.db.q, tp.WID, RUN, 'failed', 1)}",   # its run failed
                    "sbx:999999",                                          # gone
                    f"sbx:{sbx(self.db.q, tp.WID + 1, RUN)}"):             # another team's run
            self.db.q("DELETE FROM mw_bench")
            self.row(0.9, ref)
            self.assertEqual(self.one(mid, 1)["status"], "unverifiable", ref)

    def test_stale_when_a_newer_release_is_frozen(self):
        self.row(0.9, f"sbx:{sbx(self.db.q, tp.WID, RUN)}")
        self.release(2)
        e = self.one(self.create([tp.chain_measure(), self.bench()], keys=[]), 1)
        self.assertEqual((e["status"], e["pass"]), ("stale", None))

    def test_missing_without_a_release_or_a_comparable_row(self):
        mid = self.create([tp.chain_measure(), self.bench()], keys=[])
        self.assertEqual(self.one(mid, 1)["status"], "missing")  # release, no row
        self.row(0.9, f"sbx:{sbx(self.db.q, tp.WID, RUN)}", comparable=0)
        self.assertEqual(self.one(mid, 1)["status"], "missing")
        self.db.q("DELETE FROM mw_release")
        self.assertEqual(self.one(mid, 1)["status"], "missing")

    def test_a_technical_pass_never_makes_a_competition_pass(self):
        self.row(0.9, f"sbx:{sbx(self.db.q, tp.WID, RUN)}")
        ev = self.ev(self.create([tp.chain_measure(), self.bench()], keys=[]))
        self.assertEqual(ev["dimensions"]["technical"]["value"], "PASS")
        self.assertEqual(ev["dimensions"]["competition"]["value"], "UNKNOWN")

    def test_reading_writes_nothing(self):
        self.row(0.9, f"sbx:{sbx(self.db.q, tp.WID, RUN)}")
        mid = self.create([tp.chain_measure(), self.bench()], keys=[])
        snap = lambda: (self.db.q("SELECT * FROM mw_bench"), self.db.q("SELECT * FROM mw_release"), self.db.q("SELECT * FROM mw_sbx"))
        before = snap()
        for _ in range(3): self.ev(mid)
        self.assertEqual(snap(), before)


if __name__ == "__main__":
    unittest.main()
