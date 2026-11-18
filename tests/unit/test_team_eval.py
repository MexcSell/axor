"""team_eval.py (Team tests) + its hooks in missions.py: a benchmark mission recalls nothing and teaches nothing, ordinary missions
never recall a benchmark mission, and a case's score comes from the hidden checks in code (the grader's say-so only per check)."""
import json, os, tempfile, time, unittest

from app import missions, team_eval
from app.auth import AuthDB

ME = {"id": 7, "username": "leo", "role": "admin"}
GOAL = "Compare three subnets for GPU mining and recommend one with its risks"


class FakeLLM:
    def __init__(self): self.out, self.calls = None, []
    def structured(self, model, system, prompt, schema, name, on_usage=None, effort=None):
        self.calls.append((model, prompt))
        if on_usage: on_usage(1000)
        return self.out


class FakeHub:
    def __init__(self): self.llm, self.used = FakeLLM(), []
    def log_usage(self, me, source, tokens, agent_id=None, model=None): self.used.append((source, tokens, model))


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        self.db.q("INSERT INTO users (id, username, role, pw_hash) VALUES (?,?,?,?)", (ME["id"], ME["username"], ME["role"], "x"))
        self.mx = missions.Missions(self.db, hub=None, wf=object(), ia=None, mw=None)
        self.mx._submit = lambda mid: None
        self.te = team_eval.TeamEval(self.db, self.mx)

    def tearDown(self):
        missions.ISOLATED = None
        self.dir.cleanup()

    def mission(self, goal=GOAL, status="delivered", **kw):
        now = time.time()
        cols = {"user_id": ME["id"], "title": goal[:60], "goal": goal, "budget": 3.0, "status": status, "stage": "learn", "resources": "",
                "understanding": json.dumps({"objective": goal, "criteria": ["A recommendation"], "questions": []}), "created": now, "updated": now, **kw}
        return self.db.q(f"INSERT INTO mx_missions ({','.join(cols)}) VALUES ({','.join('?' * len(cols))}) RETURNING id", tuple(cols.values()), one=True)["id"]

    def link(self, mid, split, **kw):
        run = self.db.q("INSERT INTO te_runs (user_id, name, status, cap, created) VALUES (?,?,?,?,?) RETURNING id", (ME["id"], "r", "running", 9, time.time()), one=True)["id"]
        snap = {"key": "T99", "split": split, "title": "t", "goal": GOAL, "criteria": [], "expected": "x", "checks": ["A", "B", "C", "D"], "budget": 3.0,
                "minutes": 20, "within_budget": False, **kw}
        return self.db.q("""INSERT INTO te_results (run_id, seq, key, code, title, split, snap, status, mission_id) VALUES (?,?,?,?,?,?,?,?,?) RETURNING id""",
                         (run, 1, "T99", "T99", "t", split, json.dumps(snap), "grading", mid), one=True)["id"]


class Isolation(Base):
    def test_benchmark_mission_recalls_nothing(self):
        old = self.mission()
        self.db.q("INSERT INTO mx_lessons (user_id, mission_id, kind, text, outcome, created) VALUES (?,?,?,?,?,?)",
                  (ME["id"], old, "worked", "Compare GPU subnets by mining risk before you recommend one", "verified", time.time()))
        bench = self.mission(status="running", stage="discover")
        self.link(bench, "benchmark")
        self.mx._discover(self.mx._m(bench))
        d = self.mx._m(bench)["discovery"]
        self.assertEqual((d["lessons"], d["missions"], d["memories"]), ([], [], []))
        # the same mission as practice recalls both
        prac = self.mission(status="running", stage="discover")
        self.link(prac, "practice")
        self.mx._discover(self.mx._m(prac))
        d = self.mx._m(prac)["discovery"]
        self.assertEqual(len(d["lessons"]), 1)
        self.assertIn(old, [x["id"] for x in d["missions"]])

    def test_ordinary_missions_never_recall_a_benchmark(self):
        bench, prac = self.mission(), self.mission()
        self.link(bench, "benchmark"); self.link(prac, "practice")
        new = self.mission(status="running", stage="discover")
        self.mx._discover(self.mx._m(new))
        past = [x["id"] for x in self.mx._m(new)["discovery"]["missions"]]
        self.assertIn(prac, past)
        self.assertNotIn(bench, past)

    def test_benchmark_learns_nothing(self):
        rep = {"lessons": [{"kind": "worked", "text": "The hidden answer is 21 million"}]}
        bench, prac = self.mission(report=json.dumps(rep), outcome="verified"), self.mission(report=json.dumps(rep), outcome="verified")
        self.link(bench, "benchmark"); self.link(prac, "practice")
        for mid in (bench, prac): self.mx._learn(self.mx._m(mid))
        n = lambda mid: self.db.q("SELECT COUNT(*) n FROM mx_lessons WHERE mission_id=?", (mid,), one=True)["n"]
        self.assertEqual((n(bench), n(prac)), (0, 1))
        self.mx._dead(self.mx._m(bench), "boom")
        self.assertEqual(n(bench), 0)

    def test_a_broken_hook_means_an_ordinary_mission(self):
        def boom(mid): raise RuntimeError("table gone")
        missions.ISOLATED = boom
        self.assertFalse(missions.isolated(1))


class Grading(Base):
    def setUp(self):
        super().setUp()
        self.mx.hub = FakeHub()
        self.mx._model = lambda uid, avoid=None, stage=None: ("p:grader", 10.0)

    def grade(self, mid, rid):
        self.te._grade(ME, self.db.q("SELECT * FROM te_results WHERE id=?", (rid,), one=True))
        return self.db.q("SELECT * FROM te_results WHERE id=?", (rid,), one=True)

    def test_score_from_checks_missing_ones_count_as_not_met(self):
        mid = self.mission(outcome="verified", deliverable=json.dumps({"text": "an answer"}), allocation=json.dumps({"model": "p:worker"}))
        rid = self.link(mid, "benchmark")
        self.mx.hub.llm.out = {"checks": [{"check": 1, "status": "met", "evidence": "e"}, {"check": 2, "status": "partly", "evidence": "e"},
                                          {"check": 2, "status": "met", "evidence": "dup ignored"}, {"check": 9, "status": "met", "evidence": "no such"},
                                          {"check": 3, "status": "excellent", "evidence": "bad status"}],
                               "wrong": [], "summary": "ok"}
        r = self.grade(mid, rid)
        g = json.loads(r["grade"])
        self.assertEqual([c["status"] for c in g["checks"]], ["met", "partly", "not_met", "not_met"])
        self.assertEqual(r["score"], 37.5)
        self.assertEqual((r["passed"], r["lenient"]), (0, 1))  # the reviewer verified it, the hidden checks say otherwise
        self.assertTrue(g["independent"])
        self.assertEqual(r["grade_usd"], 0.01)
        self.assertNotIn("p:worker", self.mx.hub.llm.calls[0][0])

    def test_pass_and_the_budget_check(self):
        mid = self.mission(outcome="partial", deliverable=json.dumps({"text": "an answer"}))
        rid = self.link(mid, "benchmark", within_budget=True)
        self.db.q("UPDATE te_results SET spent=2.5 WHERE id=?", (rid,))
        self.mx.hub.llm.out = {"checks": [{"check": i, "status": "met", "evidence": "e"} for i in range(1, 5)], "wrong": [], "summary": "ok"}
        r = self.grade(mid, rid)
        checks = json.loads(r["grade"])["checks"]
        self.assertEqual(len(checks), 5)
        self.assertEqual(checks[-1]["status"], "met")
        self.assertEqual((r["score"], r["passed"], r["lenient"]), (100.0, 1, 0))

    def test_no_deliverable_scores_zero_without_a_call(self):
        mid = self.mission(status="cancelled", deliverable=json.dumps({"text": ""}))
        rid = self.link(mid, "practice")
        r = self.grade(mid, rid)
        self.assertEqual((r["score"], r["passed"], r["status"]), (0, 0, "done"))
        self.assertEqual(self.mx.hub.llm.calls, [])

    def test_hidden_answer_never_reaches_the_mission(self):
        lib = {c["key"]: c for c in self.te.cases(ME["id"])}
        for c in lib.values():
            self.assertTrue(c["checks"] and c["expected"])
            for chk in c["checks"]: self.assertNotIn(chk, c["goal"])
        self.assertEqual(sorted(k for k in lib if k.startswith("T")), [f"T{i:02d}" for i in range(1, 11)])


if __name__ == "__main__":
    unittest.main()
