"""G5-5 L5.2 verified-only knowledge (G-31, T-10): a mission's lesson reaches a planner only when its mission was verified. The
three readers that hand lessons to planners (orchestrator.guidance, Mission Control's discovery, experience recall by an engine or
agent) leave the others out; a person still sees them (Learning → Lessons, the "try" recall), labelled as observations. A lesson
a planner never received isn't counted as used."""
import json, os, sys, time, unittest

os.environ["KNOWLEDGE_INDEX"] = os.environ["KNOWLEDGE_SYNC"] = "0"  # no background loops in tests

sys.path.insert(0, os.path.dirname(__file__))
from app import mission_intel, missions, orchestrator as orc  # noqa: E402
import test_experience as tx  # noqa: E402  (fixtures; imported as modules so their own tests don't run again here)
import test_learning as tl  # noqa: E402
import test_orchestrator as to  # noqa: E402

ME, WF = tx.ME, tx.WF


def own_tests(cls):
    """Run only the tests this class defines, not the ones inherited from the fixture's test case."""
    for base in cls.__mro__[1:]:
        for n in vars(base):
            if n.startswith("test") and n not in vars(cls): setattr(cls, n, None)
    return cls

TEXT = "Enroll the validator hotkey before you start the miner"
UNVERIFIED = ("partial", "failed", "unverified", "", None)


class Rule(unittest.TestCase):
    def test_only_verified_reaches_planners(self):
        self.assertTrue(orc.lesson_for_planners("verified"))
        for o in UNVERIFIED: self.assertFalse(orc.lesson_for_planners(o), o)

    def test_matches_the_mission_outcome_rule(self):
        # the label comes from missions.outcome(): every criterion met (none unverifiable) is the only way to "verified"
        self.assertTrue(orc.lesson_for_planners(missions.outcome([{"status": "met"}, {"status": "met"}])))
        for r in ([{"status": "met"}, {"status": "unverifiable"}], [{"status": "met"}, {"status": "partly"}], [{"status": "unverifiable"}], []):
            self.assertFalse(orc.lesson_for_planners(missions.outcome(r)), r)


@own_tests
class Guidance(to.G5):
    """Reader 1: orchestrator.guidance(), which discovery, the Control Hub's Mission Intelligence and a team lead's plan read."""
    def setUp(self):
        super().setUp()
        self.o = orc.init(self.db)
        missions.Missions(self.db, hub=None, wf=WF(), ia=None, mw=None)  # the mx_ tables
        now = time.time()
        for i, o in enumerate(("verified",) + UNVERIFIED, start=1):
            self.db.q("INSERT INTO mx_lessons (id, user_id, mission_id, kind, text, outcome, created) VALUES (?,7,?,?,?,?,?)",
                      (i, i, "worked", f"{TEXT} ({i})", o, now))

    def test_unverified_lessons_are_not_returned(self):
        g = self.o.guidance(7, "enroll validator hotkey miner")
        self.assertEqual([x["id"] for x in g["lessons"]], [1])
        self.assertEqual(g["lessons"][0]["outcome"], "verified")

    def test_no_verified_lesson_means_none(self):
        self.db.q("DELETE FROM mx_lessons WHERE id=1")
        self.assertEqual(self.o.guidance(7, "enroll validator hotkey miner")["lessons"], [])


@own_tests
class Recall(tx.Exp):
    """Reader 3: experience recall. An engine or agent gets verified lessons only; a person sees the rest as observations."""
    def setUp(self):
        super().setUp()
        self.db.q("INSERT INTO mx_lessons (id, user_id, mission_id, kind, text, outcome, created) VALUES (3, 7, 2, 'worked', ?, 'partial', ?)",
                  ("Enroll the validator before you start the miner, again", time.time()))

    def test_planner_recall_leaves_unverified_out(self):
        self.embed()
        for actor in ("missions", "workforce", "teams:5"):
            refs = [h["ref"] for h in self.K.recall(ME, "enroll the validator before the miner", 8, actor, "", f"ctx:{actor}")]
            self.assertIn("mxl:1", refs, actor)
            self.assertNotIn("mxl:3", refs, actor)
        self.assertEqual(self.db.q("SELECT used FROM mx_lessons WHERE id=3", one=True)["used"], 0)  # never given, never counted
        self.assertFalse(self.db.q("SELECT 1 FROM ex_uses WHERE ref='mxl:3'"))

    def test_agent_tool_leaves_unverified_out(self):
        self.embed()
        _, h = self.K.agent_tools(7, "teams:5", "SN62 · Ridges", context="mw:12")["recall_experience"]
        self.assertNotIn("mxl:3", [x["ref"] for x in h({"query": "enroll the validator before the miner"})["experiences"]])

    def test_prompt_lines_leave_unverified_out(self):
        lines = "\n".join(self.K.experience_lines(7, "enroll the validator before you start the miner", "workforce", "Workforce", "wf:1"))
        self.assertIn("[mxl:1]", lines)
        self.assertNotIn("[mxl:3]", lines)

    def test_a_person_still_sees_it_as_an_observation(self):
        self.embed()
        hits = {h["ref"]: h for h in self.K.recall(ME, "enroll the validator before the miner", 8, "you", "", None, log_it=False)}
        self.assertIn("mxl:3", hits)
        self.assertIn("observation", hits["mxl:3"]["from"])
        self.assertNotIn("observation", hits["mxl:1"]["from"])

    def test_knowledge_search_never_returns_a_lesson(self):
        """Not a fourth path: the Knowledge Hub's search (search_knowledge, discovery's knowledge list) has no lesson source;
        experience vectors only give meaning to the hub's own candidates."""
        self.embed()
        for aud, actor in (("agents", "missions"), ("agents", "workforce"), ("page", "you")):
            refs = [h["ref"] for h in self.K.retrieve(ME, "enroll the validator before the miner", 8, aud, internal=False, actor=actor)]
            self.assertFalse([r for r in refs if r.startswith("mxl:")], (aud, actor, refs))

    def test_discovery_takes_verified_lessons_only(self):
        """Reader 2: Mission Control's discovery, through recall and through its own query."""
        self.embed()
        class Hub: knowledge, llm = self.K, None
        M = missions.Missions(self.db, hub=Hub(), wf=WF(), ia=None, mw=None)
        self.db.q("INSERT INTO mx_missions (id, user_id, title, goal, status, understanding, created) VALUES (40, 7, 'Validator signup', 'Enroll the validator on SN62 before the miner', 'running', ?, ?)",
                  (json.dumps({"objective": "validator enrollment"}), time.time()))
        flag, mission_intel.ENABLED = mission_intel.ENABLED, False
        try: self.assertTrue(M._discover(M._m(40)))
        finally: mission_intel.ENABLED = flag
        self.assertEqual([x["id"] for x in M._m(40)["discovery"]["lessons"]], [1])

    def test_discovery_without_the_hub_takes_verified_lessons_only(self):
        M = missions.Missions(self.db, hub=None, wf=WF(), ia=None, mw=None)
        self.db.q("INSERT INTO mx_missions (id, user_id, title, goal, status, understanding, created) VALUES (41, 7, 'Validator signup', 'Enroll the validator before you start the miner', 'running', ?, ?)",
                  (json.dumps({"objective": "validator enrollment"}), time.time()))
        flag, mission_intel.ENABLED = mission_intel.ENABLED, False
        try: self.assertTrue(M._discover(M._m(41)))
        finally: mission_intel.ENABLED = flag
        ids = [x["id"] for x in M._m(41)["discovery"]["lessons"]]
        self.assertIn(1, ids)
        self.assertNotIn(3, ids)
        self.assertEqual(self.db.q("SELECT used FROM mx_lessons WHERE id=3", one=True)["used"], 0)




@own_tests
class LearningPage(tl.LearningTest):
    """A person still sees every lesson on Learning → Lessons; an unverified one is marked as an observation planners don't get."""
    def test_learning_page_marks_observations(self):
        rows = {x["id"]: x for x in self.L.view(tl.ADMIN, fresh=True)["lessons"]}
        self.assertEqual(set(rows), {1, 2})
        self.assertTrue(rows[1]["planners"])   # verified
        self.assertFalse(rows[2]["planners"])  # failed: an observation


if __name__ == "__main__":
    unittest.main()
