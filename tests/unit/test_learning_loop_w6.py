"""G5 W6 (learning loop): what may become planning knowledge, and what a mission's success rests on.

- A team lesson only the Knowledge Manager (a model) classified is an observation: guidance, experience recall and the cross-team
  context leave it out. A person's decision or a benchmark with an evidence_ref makes it planning knowledge.
- A team mission is never `verified` because its tasks are done and a model read the team's write-up: without a valid benchmark it is
  `unverified`, and its lessons stay observations. The verification says what it rests on.
- A valid benchmark (the reader _ev_bench) leaves one `bench_verified` lesson, once, that planners receive.
"""
import os, sys, time, unittest

os.environ["KNOWLEDGE_INDEX"] = os.environ["KNOWLEDGE_SYNC"] = "0"
sys.path.insert(0, os.path.dirname(__file__))
from app import experience, missions, orchestrator as orc  # noqa: E402
import test_orchestrator as to  # noqa: E402
import test_vm_runner as tv  # noqa: E402

NOW = time.time()


def tables(db):
    db.q("CREATE TABLE IF NOT EXISTS mw_notes (id INTEGER PRIMARY KEY, comp_id INTEGER, task_id INTEGER, title TEXT, body TEXT, ts REAL)")
    db.q("CREATE TABLE IF NOT EXISTS mw_bench (id INTEGER PRIMARY KEY, comp_id INTEGER, task_id INTEGER, comparable INTEGER, evidence_ref TEXT)")
    db.q("""CREATE TABLE IF NOT EXISTS mk_items (id INTEGER PRIMARY KEY AUTOINCREMENT, note_id INTEGER UNIQUE, comp_id INTEGER, user_id INTEGER,
            netuid INTEGER, scope TEXT, suggested TEXT, sure TEXT, lesson TEXT, why TEXT, by_user TEXT, run_id INTEGER, created REAL, updated REAL, kb_id INTEGER)""")


def item(db, nid, task, scope="subnet_shared", by=orc.KM_AUTO, lesson="Enroll the validator hotkey before you start the miner"):
    db.q("INSERT INTO mw_notes (id, comp_id, task_id, title, body, ts) VALUES (?,1,?,?,?,?)", (nid, task, "t", "b", NOW))
    db.q("INSERT INTO mk_items (id, note_id, comp_id, user_id, netuid, scope, sure, lesson, by_user, created, updated) VALUES (?,?,1,7,61,?,'high',?,?,?,?)",
         (nid, nid, scope, lesson, by, NOW, NOW))


class Rule(unittest.TestCase):
    def test_the_bench_lesson_is_a_planner_input_and_no_outcome_can_be_it(self):
        self.assertTrue(orc.lesson_for_planners(orc.LESSON_BENCH))
        for r in ([{"status": "met"}], [{"status": "partly"}], [{"status": "unverifiable"}], [], [{"status": "not_met"}]):
            self.assertNotEqual(missions.outcome(r), orc.LESSON_BENCH)


@tv.own_tests
class Trust(to.G5):
    def setUp(self):
        super().setUp()
        self.o = orc.init(self.db)
        missions.Missions(self.db, hub=None, wf=None, ia=None, mw=None)
        tables(self.db)

    def test_a_model_only_entry_is_not_trusted_a_persons_or_a_benchmarks_is(self):
        item(self.db, 1, 10)                                      # the Knowledge Manager alone
        item(self.db, 2, 11, by="leo")                            # a person shared it
        item(self.db, 3, 12)                                      # the Knowledge Manager, on a task with a benchmark and evidence
        self.db.q("INSERT INTO mw_bench (comp_id, task_id, comparable, evidence_ref) VALUES (1, 12, 1, 'job:7')")
        item(self.db, 4, 13)                                      # a benchmark with no evidence_ref
        self.db.q("INSERT INTO mw_bench (comp_id, task_id, comparable, evidence_ref) VALUES (1, 13, 1, NULL)")
        item(self.db, 5, 14)                                      # a benchmark that wasn't comparable
        self.db.q("INSERT INTO mw_bench (comp_id, task_id, comparable, evidence_ref) VALUES (1, 14, 0, 'job:8')")
        item(self.db, 6, 15, scope="restricted", by="leo")
        got = {i: orc.mk_trusted(self.db, self.db.q("SELECT * FROM mk_items WHERE id=?", (i,), one=True)) for i in range(1, 7)}
        self.assertEqual(got, {1: False, 2: True, 3: True, 4: False, 5: False, 6: False})

    def test_guidance_gives_a_planner_only_the_trusted_ones(self):
        item(self.db, 1, 10); item(self.db, 2, 11, by="leo", lesson="Enroll the validator hotkey, then start the miner")
        g = self.o.guidance(7, "enroll validator hotkey miner start")
        self.assertEqual([x["ref"] for x in g["team_lessons"]], ["mk:2"])


class Missionish(to.G5):
    """_success_basis, the cap in _verify, and the benchmark lesson, on a Missions with the benchmark reader answered by the test."""
    def setUp(self):
        super().setUp()
        self.o = orc.init(self.db)
        self.m = missions.Missions(self.db, hub=None, wf=None, ia=None, mw=None)
        tables(self.db)
        self.status = {"status": "missing", "reason": "No comparable benchmark on the frozen suite yet"}
        def ev(e, ctx):
            e.update(self.status)
        self.m._ev_bench = ev
        self.mid = self.db.q("""INSERT INTO mx_missions (user_id, title, goal, engine, team, status, stage, understanding, created, started)
                                VALUES (7,'SN61 miner','Score at least 0.8','mining',1,'running','verify',?,?,?) RETURNING id""",
                             (missions._j({"criteria": ["The miner scores 0.8 or more"], "objective": "x"}), NOW, NOW), one=True)["id"]
        self.m._collect = lambda m: {"kind": "mining", "text": "All 5 team tasks done. The miner scores 0.9.", "items": []}
        self.m._ask = lambda m, *a, **k: ({"results": [{"criterion": "The miner scores 0.8 or more", "status": "met", "evidence": "the write-up says 0.9"}], "limitations": []}, "other:model")

    def valid(self, ref=None):
        self.status = {"status": "valid", "value": 6.13, "evidence_ref": ref or {"bench_row": 1, "release": 2, "sandbox_run": "job:7", "suite_hash": "add4a911e5a1", "score_source": "read from the job's output file"}}

    def run_verify(self):
        self.m._verify(self.m._m(self.mid))
        return self.m._m(self.mid)

    def test_all_tasks_done_and_a_reviewer_who_met_every_criterion_is_not_a_verified_mission(self):
        m = self.run_verify()
        self.assertEqual(m["outcome"], "unverified")
        self.assertEqual(m["verification"]["basis"]["level"], "agent_reported")
        self.assertIn("Tasks being done is not a result", " ".join(m["verification"]["limitations"]))
        self.assertEqual([r["status"] for r in m["verification"]["results"]], ["met"])  # the criteria stay as judged

    def test_a_finished_sandbox_run_without_a_benchmark_is_tool_executed_and_still_not_verified(self):
        self.db.q("CREATE TABLE IF NOT EXISTS mw_sbx (id INTEGER PRIMARY KEY, comp_id INTEGER, status TEXT, exit_code INTEGER, finished REAL)")
        self.db.q("INSERT INTO mw_sbx (comp_id, status, exit_code, finished) VALUES (1,'done',0,?)", (NOW + 5,))
        m = self.run_verify()
        self.assertEqual((m["outcome"], m["verification"]["basis"]["level"]), ("unverified", "tool_executed"))

    def test_a_valid_benchmark_lets_the_outcome_stand(self):
        self.valid()
        m = self.run_verify()
        self.assertEqual((m["outcome"], m["verification"]["basis"]["level"]), ("verified", "independently_verified"))  # the mock reviewer isn't the worker's model
        self.assertEqual(m["verification"]["basis"]["benchmark"]["evidence_ref"], "job:7")

    def test_a_reviewer_that_is_not_the_workers_model_makes_it_independently_verified(self):
        self.valid()
        self.assertEqual(self.m._success_basis(self.m._m(self.mid), {"independent": True})["level"], "independently_verified")
        self.assertEqual(self.m._success_basis(self.m._m(self.mid), {"independent": False})["level"], "benchmark")

    def test_an_unmeasured_mission_of_another_engine_is_left_as_the_reviewer_judged(self):
        self.db.q("UPDATE mx_missions SET engine='workforce', team=NULL WHERE id=?", (self.mid,))
        self.assertEqual(self.run_verify()["outcome"], "verified")

    def test_a_valid_benchmark_leaves_one_lesson_that_planners_receive_and_it_is_not_the_missions_handoff(self):
        self.valid()
        m = self.m._m(self.mid)
        lid = self.m._bench_lesson(m)
        self.assertTrue(lid)
        self.assertIsNone(self.m._bench_lesson(m))                                   # once per benchmark row
        row = self.db.q("SELECT * FROM mx_lessons WHERE id=?", (lid,), one=True)
        self.assertEqual(row["outcome"], orc.LESSON_BENCH)
        self.assertIn("not a competition result", row["text"])
        self.assertIn("job:7", row["text"])
        self.assertEqual([x["id"] for x in self.o.guidance(7, "scored frozen suite candidate release benchmark")["lessons"]] , [lid])

    def test_no_valid_benchmark_no_lesson(self):
        self.assertIsNone(self.m._bench_lesson(self.m._m(self.mid)))
        self.status = {"status": "unverifiable", "value": 6.13, "evidence_ref": {"bench_row": 1}}
        self.assertIsNone(self.m._bench_lesson(self.m._m(self.mid)))
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM mx_lessons", one=True)["n"], 0)


@tv.own_tests
class Recall(to.G5):
    """Experience recall by an engine or agent (planner) leaves out a model-only team lesson; a person sees it."""
    def test_planner_recall_and_a_persons_view(self):
        tables(self.db)
        item(self.db, 1, 10); item(self.db, 2, 11, by="leo", lesson="A person shared this one")
        class X(experience.Experience):
            def __init__(s, db): s.db = db
            def _has(s, t): return bool(s.db.q("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,), one=True))
        x = X(self.db)
        planner = {r["ref"] for r in x._exp_rows(7, planner=True) if r["source"] == "mk"}
        person = {r["ref"] for r in x._exp_rows(7, planner=False) if r["source"] == "mk"}
        self.assertEqual((planner, person), ({"mk:2"}, {"mk:1", "mk:2"}))


if __name__ == "__main__": unittest.main()
