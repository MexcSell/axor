"""A promoted trial's lesson (decided under the Owner's delegation of 2026-11-13 15:33 UTC; amends C2-2).

A team-agent change the gate promoted on a trial's measured evidence, when that promotion answered a mission's measured gap,
leaves one lesson with outcome `trial_verified`. Planners receive it, as they receive a verified mission's lesson. It says what
the trial measured and that it is a technical result; it never says the gap closed. When the promotion is rolled back the lesson
becomes an observation (`trial_rolled_back`): people still see it, planners stop receiving it.

- D4.4's writer is untouched: a mission's own lesson still carries the mission's outcome.
- Each reader that hands lessons to planners is checked on its own: guidance, Mission Control's discovery with and without
  the Knowledge Hub, and experience recall. One reader passing says nothing about the others.
"""
import json, os, sys, time, unittest

os.environ["KNOWLEDGE_INDEX"] = os.environ["KNOWLEDGE_SYNC"] = "0"  # no background loops in tests

sys.path.insert(0, os.path.dirname(__file__))
from app import analytics, mission_intel, missions, orchestrator as orc  # noqa: E402
import test_experience as tx  # noqa: E402  (fixtures; as modules, so their own tests don't run again here)
import test_g5_mission_lifecycle as tl  # noqa: E402
import test_learning as tlearn  # noqa: E402
import test_measured_evaluation as tm  # noqa: E402
import test_orchestrator as to  # noqa: E402
import test_technical_gap as tg  # noqa: E402
import test_vm_runner as tv  # noqa: E402
from test_mission_persistent_evidence import TEAM_ACCOUNT, WID  # noqa: E402

ME, WF = tx.ME, tx.WF
TEXT = "Enroll the validator hotkey before you start the miner"
TRIAL, GONE = orc.LESSON_TRIAL, orc.LESSON_TRIAL_WITHDRAWN


class Rule(unittest.TestCase):
    def test_a_promoted_trials_lesson_reaches_planners_and_a_rolled_back_one_does_not(self):
        self.assertEqual((TRIAL, GONE), ("trial_verified", "trial_rolled_back"))
        self.assertTrue(orc.lesson_for_planners(TRIAL))
        self.assertFalse(orc.lesson_for_planners(GONE))
        self.assertEqual(orc.LESSONS_FOR_PLANNERS, ("verified", "trial_verified", "bench_verified"))

    def test_no_mission_outcome_is_either_word(self):
        """A mission's own lesson can never become a trial's: missions.outcome() gives neither word."""
        for r in ([{"status": "met"}], [{"status": "partly"}], [{"status": "unverifiable"}], [{"status": "not_met"}], []):
            self.assertNotIn(missions.outcome(r), (TRIAL, GONE))


@tv.own_tests
class Guidance(to.G5):
    """Reader 1: orchestrator.guidance()."""
    def setUp(self):
        super().setUp()
        self.o = orc.init(self.db)
        missions.Missions(self.db, hub=None, wf=WF(), ia=None, mw=None)  # the mx_ tables
        for i, o in ((1, TRIAL), (2, GONE), (3, "partial")):
            self.db.q("INSERT INTO mx_lessons (id, user_id, mission_id, kind, text, outcome, created) VALUES (?,7,?,'worked',?,?,?)", (i, i, f"{TEXT} ({i})", o, time.time()))

    def test_guidance_returns_the_trials_lesson_and_never_the_rolled_back_one(self):
        g = self.o.guidance(7, "enroll validator hotkey miner")
        self.assertEqual([(x["id"], x["outcome"]) for x in g["lessons"]], [(1, TRIAL)])
        self.db.q("UPDATE mx_lessons SET outcome=? WHERE id=1", (GONE,))                             # its promotion is rolled back
        self.assertEqual(self.o.guidance(7, "enroll validator hotkey miner")["lessons"], [])


@tv.own_tests
class Recall(tm.Closing, tx.Exp):  # Closing: its base doesn't close the database, and on Postgres that holds a connection (PX-R13)
    """Readers 2 and 3: experience recall by an engine or agent, and Mission Control's discovery (through recall, and through its
    own query when there is no Knowledge Hub)."""
    def setUp(self):
        super().setUp()
        self.db.q("DELETE FROM mx_lessons")
        for i, o in ((11, TRIAL), (12, GONE)):
            self.db.q("INSERT INTO mx_lessons (id, user_id, mission_id, kind, text, outcome, created) VALUES (?, 7, 2, 'worked', ?, ?, ?)",
                      (i, f"Enroll the validator before you start the miner ({i})", o, time.time()))

    def refs(self, actor): return [h["ref"] for h in self.K.recall(ME, "enroll the validator before the miner", 8, actor, "", f"ctx:{actor}")]

    def test_recall_by_an_engine_or_agent(self):
        self.embed()
        for actor in ("missions", "workforce", "teams:5"):
            refs = self.refs(actor)
            self.assertIn("mxl:11", refs, actor); self.assertNotIn("mxl:12", refs, actor)
        self.assertFalse(self.db.q("SELECT 1 FROM ex_uses WHERE ref='mxl:12'"))
        self.db.q("UPDATE mx_lessons SET outcome=? WHERE id=11", (GONE,))                            # its promotion is rolled back
        for actor in ("missions", "workforce", "teams:5"): self.assertNotIn("mxl:11", self.refs(actor), actor)

    def test_a_person_sees_both_and_which_is_which(self):
        self.embed()
        hits = {h["ref"]: h for h in self.K.recall(ME, "enroll the validator before the miner", 8, "you", "", None, log_it=False)}
        self.assertEqual(hits["mxl:11"]["from"], "a promoted trial's lesson (a technical result)")
        self.assertEqual(hits["mxl:12"]["from"], "a trial's lesson (observation: its change was rolled back)")

    def discovered(self, mid, hub):
        M = missions.Missions(self.db, hub=hub, wf=WF(), ia=None, mw=None)
        self.db.q("INSERT INTO mx_missions (id, user_id, title, goal, status, understanding, created) VALUES (?, 7, 'Validator signup', 'Enroll the validator before you start the miner', 'running', ?, ?)",
                  (mid, json.dumps({"objective": "validator enrollment"}), time.time()))
        flag, mission_intel.ENABLED = mission_intel.ENABLED, False
        try: self.assertTrue(M._discover(M._m(mid)))
        finally: mission_intel.ENABLED = flag
        return [x["id"] for x in M._m(mid)["discovery"]["lessons"]]

    def test_discovery_through_the_knowledge_hub(self):
        self.embed()
        class Hub: knowledge, llm = self.K, None
        self.assertEqual(self.discovered(40, Hub()), [11])
        self.db.q("UPDATE mx_lessons SET outcome=? WHERE id=11", (GONE,))
        self.assertEqual(self.discovered(41, Hub()), [])

    def test_discovery_without_the_knowledge_hub(self):
        self.assertEqual(self.discovered(42, None), [11])
        self.assertEqual(self.db.q("SELECT used FROM mx_lessons WHERE id=12", one=True)["used"], 0)  # never given, never counted
        self.db.q("UPDATE mx_lessons SET outcome=? WHERE id=11", (GONE,))
        self.assertEqual(self.discovered(43, None), [])


@tv.own_tests
class LearningPage(tm.Closing, tlearn.LearningTest):
    def test_the_page_says_which_lessons_planners_receive(self):
        for i, o in ((21, TRIAL), (22, GONE)):
            self.db.q("INSERT INTO mx_lessons (id, user_id, mission_id, kind, text, outcome, created) VALUES (?, 7, 1, 'worked', 'x', ?, ?)", (i, o, time.time()))
        rows = {x["id"]: x for x in self.L.view(tlearn.ADMIN, fresh=True)["lessons"]}
        self.assertEqual((rows[21]["planners"], rows[21]["outcome"]), (True, TRIAL))
        self.assertEqual((rows[22]["planners"], rows[22]["outcome"]), (False, GONE))


@tv.own_tests
class LessonUses(tm.Targets):
    """K-14's M8: a lesson handed to an engine while its promotion stood was verified then; one handed out after the rollback wasn't."""
    def setUp(self):
        super().setUp()
        self.db.q("ALTER TABLE mx_lessons ADD COLUMN withdrawn REAL")
        self.db.q("INSERT INTO ex_recalls VALUES (1, 7, 'workforce')")

    def use(self, lesson, at): self.db.q("INSERT INTO ex_uses (recall_id, ref, ts) VALUES (1, ?, ?)", (f"mxl:{lesson}", at))

    def test_a_use_before_the_rollback_counts_and_one_after_it_does_not(self):
        q = self.db.q
        q("INSERT INTO mx_lessons VALUES (1, ?, NULL)", (TRIAL,)); self.use(1, self.now - 3600)
        x = self.t()["M8"]
        self.assertEqual((x["state"], x["value"], x["ids"]), ("met", "100%", []))
        q("UPDATE mx_lessons SET outcome=?, withdrawn=? WHERE id=1", (GONE, self.now - 1800))        # rolled back half an hour ago
        self.assertEqual((self.t()["M8"]["state"], self.t()["M8"]["ids"]), ("met", []))
        self.use(1, self.now - 60)                                                                    # a reader that handed it out afterwards
        x = self.t()["M8"]
        self.assertEqual((x["state"], x["value"], x["ids"]), ("not_met", "50%", [1]))

    def test_a_rolled_back_lesson_without_a_time_never_counts(self):
        self.db.q("INSERT INTO mx_lessons VALUES (1, ?, NULL)", (GONE,)); self.use(1, self.now - 3600)
        self.assertEqual((self.t()["M8"]["state"], self.t()["M8"]["ids"]), ("not_met", [1]))


@tv.own_tests
class Promoted(tg.Held):
    """End to end on the fixture team: a mission measures a technical gap, a person answers it, the gate's trial measures the
    answer on the frozen measuring job, the team's account promotes it."""
    def setUp(self):
        super().setUp()
        self.ev.missions = self.mx                                                                   # as main.py wires it

    def lessons(self, mid=None):
        return [dict(x) for x in self.db.q("SELECT * FROM mx_lessons WHERE (? IS NULL OR mission_id=?) ORDER BY id", (mid, mid))]
    def guidance(self): return [x["id"] for x in orc.guidance(TEAM_ACCOUNT, "trial instructions benchmark runs frozen suite promoted")["lessons"]]

    def test_the_promotion_leaves_one_lesson_under_the_missions_own_account(self):
        mid, gid, pid, team = self.promoted()
        (x,) = self.lessons()
        self.assertEqual((x["mission_id"], x["user_id"], x["kind"], x["outcome"], x["withdrawn"]), (mid, TEAM_ACCOUNT, "worked", TRIAL, None))
        self.assertEqual(x["user_id"], self.m(mid)["user_id"])
        self.assertTrue(x["text"].startswith(f"[mx:{mid}:trial:{pid}] Technical result, not a competition result: "), x["text"])
        for part in ("scored 60 → 85 on 3 benchmark runs a side", f"team #{WID}'s frozen suite", "“Benchmark before approving”", f"It answered gap #{gid}",
                     "whether that gap closed is for the mission's next cycles to measure"):
            self.assertIn(part, x["text"])
        self.assertLessEqual(len(x["text"]), 400)
        a = [r["action"] for r in self.db.q("SELECT action FROM ev_audit WHERE target=? ORDER BY id", (f"proposal:{pid}",))]
        self.assertIn("lesson.trial", a)
        self.assertEqual(self.guidance(), [x["id"]])                                                 # a planner of this account gets it

    def test_the_mission_is_still_open_and_its_own_lesson_is_not_written_by_this(self):
        mid, *_ = self.promoted()
        self.assertEqual(self.m(mid)["status"], "monitoring")
        self.assertFalse(self.db.q("SELECT 1 FROM mx_lessons WHERE text LIKE ?", (f"[mx:{mid}:deliver]%",)))

    def test_a_rollback_makes_it_an_observation_before_anything_else(self):
        mid, gid, pid, team = self.promoted()
        (x,) = self.lessons()
        t0 = time.time()
        self.assertEqual(self.ev.rollback(team, pid)["status"], "rolled_back")
        (y,) = self.lessons()
        self.assertEqual((y["id"], y["outcome"], y["text"]), (x["id"], GONE, x["text"]))
        self.assertGreaterEqual(y["withdrawn"], t0)
        self.assertEqual(self.guidance(), [])                                                        # and no planner gets it any more
        self.assertEqual(self.db.q("SELECT status FROM ev_proposals WHERE id=?", (gid,), one=True)["status"], "proposed")
        self.assertIn("lesson.trial_withdrawn", [r["action"] for r in self.db.q("SELECT action FROM ev_audit WHERE target=?", (f"proposal:{pid}",))])

    def test_a_rollback_goes_through_when_the_lesson_cannot_be_withdrawn_and_says_so(self):
        """The rollback takes a bad change out; the lesson's bookkeeping never blocks it. A person is told what is left to do."""
        mid, gid, pid, team = self.promoted()
        def broken(*a): raise RuntimeError("the database is away")
        self.mx.trial_lesson_withdrawn = broken
        promoted = self.db.q("SELECT instructions FROM mw_agents WHERE id=2", one=True)["instructions"]
        with self.assertLogs("scout.evolution", "ERROR"):
            out = self.ev.rollback(team, pid)
        self.assertEqual((out["status"], self.db.q("SELECT status FROM ev_proposals WHERE id=?", (pid,), one=True)["status"]), ("rolled_back", "rolled_back"))
        self.assertNotEqual(self.db.q("SELECT instructions FROM mw_agents WHERE id=2", one=True)["instructions"], promoted)   # the version before is back
        self.assertEqual(self.db.q("SELECT status FROM ev_proposals WHERE id=?", (gid,), one=True)["status"], "proposed")       # and the gap is open again
        self.assertEqual(self.lessons()[0]["outcome"], TRIAL)                                        # the lesson is what couldn't be changed
        note = out["lesson_not_withdrawn"]
        self.assertIn("Lesson not withdrawn: the database is away", note); self.assertIn(f"[mx:{mid}:trial:{pid}]", note); self.assertIn("forget it on Learning", note)
        (a,) = self.db.q("SELECT actor, detail FROM ev_audit WHERE target=? AND action='lesson.trial_not_withdrawn'", (f"proposal:{pid}",))
        self.assertEqual(a["detail"], note)
        self.assertFalse(self.db.q("SELECT 1 FROM ev_audit WHERE target=? AND action='lesson.trial_withdrawn'", (f"proposal:{pid}",)))

    def test_a_rollback_that_withdrew_the_lesson_says_nothing_more(self):
        mid, gid, pid, team = self.promoted()
        self.assertNotIn("lesson_not_withdrawn", self.ev.rollback(team, pid))
        self.assertFalse(self.db.q("SELECT 1 FROM ev_audit WHERE action='lesson.trial_not_withdrawn'"))

    def test_a_lesson_that_cannot_be_written_never_undoes_the_promotion(self):
        def broken(*a): raise RuntimeError("the database is away")
        self.mx.trial_lesson = broken
        with self.assertLogs("scout.evolution", "ERROR"):
            mid, gid, pid, team = self.promoted()
        self.assertEqual(self.db.q("SELECT status FROM ev_proposals WHERE id=?", (pid,), one=True)["status"], "promoted")
        self.assertEqual(self.db.q("SELECT status FROM ev_proposals WHERE id=?", (gid,), one=True)["status"], "answered")
        self.assertEqual(self.lessons(), [])

    def test_without_mission_control_nothing_is_written_and_the_gate_works_as_before(self):
        self.ev.missions = None
        mid, gid, pid, team = self.promoted()
        self.assertEqual(self.lessons(), [])
        self.assertEqual(self.ev.rollback(team, pid)["status"], "rolled_back")

    def test_the_writer_writes_one_row_per_proposal_and_only_for_its_own_team(self):
        mid, gid, pid, team = self.promoted()
        (x,) = self.lessons()
        f = {"proposal": pid, "gap": gid, "team": f"comp:{WID}", "agent": "Rae", "title": "t", "baseline": 60.0, "candidate": 85.0, "cases": 3, "before_version": 1, "after_version": 2}
        self.assertEqual(self.mx.trial_lesson(mid, f), x["id"])                                      # a second call: the same row
        self.assertEqual(len(self.lessons()), 1)
        self.assertIsNone(self.mx.trial_lesson(mid, f | {"proposal": pid + 100, "team": f"comp:{WID + 1}"}))   # a gap of another team
        self.assertIsNone(self.mx.trial_lesson(mid + 500, f | {"proposal": pid + 100}))                       # no such mission
        flag, missions.ISOLATED = missions.ISOLATED, lambda m: True
        try: self.assertIsNone(self.mx.trial_lesson(mid, f | {"proposal": pid + 100}))                         # a Team tests mission keeps no lesson
        finally: missions.ISOLATED = flag
        self.assertEqual(len(self.lessons()), 1)
        self.assertNotEqual(self.mx.trial_lesson(mid, f | {"proposal": pid * 10 + 1}), x["id"])     # another proposal: its own row, and "7" never matches "71"
        self.assertEqual(self.mx.trial_lesson_withdrawn(mid, pid), 1)                                # the shorter number: its own row only
        self.assertEqual([r["outcome"] for r in self.lessons()], [GONE, TRIAL])
        self.assertEqual(self.mx.trial_lesson_withdrawn(mid, pid), 0)                                # once
        self.assertEqual(self.mx.trial_lesson_withdrawn(mid, pid * 10 + 1), 1)
        self.assertEqual([r["outcome"] for r in self.lessons()], [GONE, GONE])

    def test_the_missions_handoff_does_not_count_a_trials_lesson_as_its_own(self):
        """The orchestrator's knowledge handoff counts a mission's own lessons when it finishes. A trial's lesson, written while
        the mission was running, isn't one of them, standing or rolled back."""
        mid, gid, pid, team = self.promoted()
        hand = lambda: orc._orc._on_mission_finished({"corr": f"mx:{mid}", "owner_id": TEAM_ACCOUNT}, {})
        r = hand()
        self.assertEqual((len(self.lessons(mid)), r["lessons"]), (1, 0)); self.assertIn("without a lesson", r["warning"])
        self.ev.rollback(team, pid)
        self.assertEqual(hand()["lessons"], 0)
        self.db.q("INSERT INTO mx_lessons (user_id, mission_id, kind, text, outcome, created) VALUES (?, ?, 'worked', 'its own', 'partial', ?)", (TEAM_ACCOUNT, mid, time.time()))
        self.assertEqual(hand()["lessons"], 1)                                                       # the mission's own lesson still counts


if __name__ == "__main__":
    unittest.main()
