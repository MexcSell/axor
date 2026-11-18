"""B2 (2026-11-15 closure): why mission 1's four lessons never reached planners, kept as a regression in both directions.

Root cause (staging, read-only): mission 1 met 1 of its 6 criteria, so missions.outcome() is `partial`, and _learn writes the
report's lessons with the mission's outcome. `partial` is not in orchestrator.LESSONS_FOR_PLANNERS, so the lessons are observations
by design (G5-5 L5.2). No `bench_verified` lesson was written either: the team's only mw_bench row was recorded before the release
freeze (comparable 0, "no release manifest is frozen yet"), and the 32-run development bench went through the runner stand-in and
was never recorded as a team benchmark. Nothing here widens the planner rule; that is the Owner's learning policy.

Through the real paths: _verify -> _learn -> mx_lessons, then the planner readers (orchestrator.guidance, experience recall with
planner=True) and the person's view (planner=False)."""
import os, sys, time, unittest

os.environ["KNOWLEDGE_INDEX"] = os.environ["KNOWLEDGE_SYNC"] = "0"
sys.path.insert(0, os.path.dirname(__file__))
from app import experience, missions, orchestrator as orc  # noqa: E402
import test_orchestrator as to  # noqa: E402
import test_learning_loop_w6 as w6  # noqa: E402

NOW = time.time()
CRITERIA = [f"BEX miner criterion {i}" for i in range(1, 7)]
LESSONS = [  # mission 1's four lessons on staging (kind, text shortened)
    ("worked", "A digest-pinned fresh-export BEX miner harness with sha256 of the miner tree gave trustworthy reproducible baselines"),
    ("failed", "Spending the BEX miner tool budget on research and tooling before running a candidate left no measured candidate"),
    ("failed", "Parallel BEX miner tasks reported conflicting state about candidates and baselines"),
    ("strategy", "For BEX miner score-target missions iterate tightly: change, five official runs, record the median, change again"),
]
QUERY = "BEX miner candidate baseline official runs median score"


class Recaller(experience.Experience):
    def __init__(s, db): s.db = db
    def _has(s, t): return bool(s.db.q("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,), one=True))


class Mission1Replay(to.G5):
    def setUp(self):
        super().setUp()
        self.o = orc.init(self.db)
        self.m = missions.Missions(self.db, hub=None, wf=None, ia=None, mw=None)
        w6.tables(self.db)
        self.status = {"status": "unverifiable", "value": 6.13, "reason": "no release manifest is frozen yet", "evidence_ref": {"bench_row": 1}}
        self.m._ev_bench = lambda e, ctx: e.update(self.status)
        self.mid = self.db.q("""INSERT INTO mx_missions (user_id, title, goal, engine, team, status, stage, understanding, report, created, started)
                                VALUES (7,'SN61 BEX miner','Score at least 0.8','mining',1,'running','verify',?,?,?,?) RETURNING id""",
                             (missions._j({"criteria": CRITERIA, "objective": "x"}),
                              missions._j({"lessons": [{"kind": k, "text": t} for k, t in LESSONS]}), NOW, NOW), one=True)["id"]
        self.m._collect = lambda m: {"kind": "mining", "text": "report", "items": []}
        res = [{"criterion": c, "status": "met" if i == 0 else "not_met", "evidence": "e"} for i, c in enumerate(CRITERIA)]
        self.m._ask = lambda m, *a, **k: ({"results": res, "limitations": []}, "same:model")

    def verify_and_learn(self):
        self.m._verify(self.m._m(self.mid))
        m = self.m._m(self.mid)
        self.m._learn(m)
        return m

    def planner_refs(self):
        return {r["ref"] for r in Recaller(self.db)._exp_rows(7, planner=True) if r["source"] == "mxl"}

    def person_refs(self):
        return {r["ref"] for r in Recaller(self.db)._exp_rows(7, planner=False) if r["source"] == "mxl"}

    def test_mission1_one_of_six_met_is_partial_and_its_lessons_reach_no_planner(self):
        m = self.verify_and_learn()
        self.assertEqual(m["outcome"], "partial")
        rows = self.db.q("SELECT id, outcome FROM mx_lessons WHERE mission_id=?", (self.mid,))
        self.assertEqual([r["outcome"] for r in rows], ["partial"] * 4)
        self.assertEqual(self.o.guidance(7, QUERY)["lessons"], [])                      # planner reader 1
        self.assertEqual(self.planner_refs(), set())                                     # planner reader 2 (engine/agent recall)
        self.assertEqual(self.person_refs(), {f"mxl:{r['id']}" for r in rows})          # a person still sees all four

    def test_a_non_comparable_benchmark_leaves_no_planner_lesson(self):
        self.verify_and_learn()
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM mx_lessons WHERE outcome=?", (orc.LESSON_BENCH,), one=True)["n"], 0)

    def test_with_a_comparable_benchmark_on_the_frozen_release_planners_get_one_bench_lesson_and_still_not_the_partial_ones(self):
        self.status = {"status": "valid", "value": 6.13, "evidence_ref": {"bench_row": 2, "release": 1, "sandbox_run": "job:7",
                                                                          "suite_hash": "add4a911e5a1", "score_source": "the job's output file"}}
        m = self.verify_and_learn()
        self.assertEqual(m["outcome"], "partial")                                        # a benchmark does not turn 1/6 into success
        (b,) = self.db.q("SELECT id, text FROM mx_lessons WHERE outcome=?", (orc.LESSON_BENCH,))
        self.assertIn("not a competition result", b["text"])
        self.assertEqual(self.planner_refs(), {f"mxl:{b['id']}"})
        g = [x["id"] for x in self.o.guidance(7, "candidate scored frozen suite release benchmark team")["lessons"]]
        self.assertEqual(g, [b["id"]])

    def test_every_outcome_other_than_the_three_is_an_observation(self):
        self.assertEqual(set(orc.LESSONS_FOR_PLANNERS), {"verified", "trial_verified", "bench_verified"})
        for o in ("partial", "failed", "unverified", "trial_rolled_back", "estimated", "trial_not_better", "trial_rejected",
                  "promotion_holding", "promotion_not_holding", "promotion_inconclusive", "mission_measured", ""):
            self.assertFalse(orc.lesson_for_planners(o), o)

    def test_a_verified_lesson_is_not_pushed_out_by_400_newer_observations(self):  # the 400-row correction (T-4)
        v = self.db.q("INSERT INTO mx_lessons (user_id, mission_id, kind, text, outcome, created) VALUES (7,NULL,'worked',?, 'verified', ?) RETURNING id",
                      ("BEX miner verified lesson: five official runs per candidate", NOW), one=True)["id"]
        for i in range(450):
            self.db.q("INSERT INTO mx_lessons (user_id, mission_id, kind, text, outcome, created) VALUES (7,NULL,'strategy',?,'partial',?)",
                      (f"BEX miner observation {i}", NOW + i))
        self.assertIn(f"mxl:{v}", self.planner_refs())
        self.assertIn(v, [x["id"] for x in self.o.guidance(7, "BEX miner verified lesson official runs candidate")["lessons"]])


if __name__ == "__main__": unittest.main()
