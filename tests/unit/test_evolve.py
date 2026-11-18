"""mining_evolve.py: self-improvement on its own. The keep / roll back rule, and the loop end to end on a real database with
stand-ins for Improvements, Loadouts and the Workflow (they call the workbench)."""
import os, tempfile, time, unittest
from types import SimpleNamespace

from fastapi import HTTPException

from app.auth import AuthDB
from app.mining_evolve import WINDOW, Evolve, watch_verdict


class Rule(unittest.TestCase):
    def test_keeps_watching_until_the_window_is_full(self):
        self.assertIsNone(watch_verdict(60, {"basis": WINDOW - 1, "score": 10}))

    def test_rolls_back_only_past_the_tolerance(self):
        self.assertEqual(watch_verdict(60, {"basis": WINDOW, "score": 54}), "rollback")
        self.assertEqual(watch_verdict(60, {"basis": WINDOW, "score": 55}), "keep")

    def test_without_a_baseline_the_evals_decide(self):
        self.assertEqual(watch_verdict(None, {"basis": WINDOW, "score": 70, "eval_up": 1, "eval_down": 2}), "rollback")
        self.assertEqual(watch_verdict(None, {"basis": WINDOW, "score": 30, "eval_up": 2, "eval_down": 2}), "keep")


class World:
    """One team (flow 1) with one engineer (agent 7) at loadout version 3."""
    def __init__(self, path):
        self.db = AuthDB(path)
        q = self.db.q
        q("CREATE TABLE mb_flows (id INTEGER PRIMARY KEY, user_id INTEGER, improve TEXT DEFAULT 'auto')")
        q("""CREATE TABLE mb_improvements (id INTEGER PRIMARY KEY, flow_id INTEGER, agent_id INTEGER, task_id INTEGER, base_version INTEGER,
             status TEXT, cost REAL DEFAULT 0, version INTEGER, created REAL)""")
        q("CREATE TABLE mb_trials (id INTEGER PRIMARY KEY, improvement_id INTEGER, run TEXT, check_run TEXT)")
        q("CREATE TABLE mb_runs (run TEXT PRIMARY KEY, flow_id INTEGER, cost REAL DEFAULT 0, started REAL)")
        q("INSERT INTO mb_flows (id, user_id, improve) VALUES (1, 42, 'self')")
        q("INSERT INTO mb_improvements (id, flow_id, agent_id, task_id, base_version, status, cost, created) VALUES (5, 1, 7, 9, 3, 'proposed', 0.5, ?)", (time.time(),))
        self.version, self.calls, self.log = 3, [], []
        self.scores = {3: {"version": 3, "score": 60, "basis": 8, "eval_up": 2, "eval_down": 1}}
        w = self
        self.agent = {"id": 7, "name": "Ada", "flow_id": 1}

        class Imp:
            def test(_, me, iid, b): w.calls.append(("test", me["username"], me["id"], iid))
            def decide(_, me, iid, b):
                w.calls.append(("decide", b.decision, iid)); w.version = 4
                w.scores[4] = {"version": 4, "score": None, "basis": 0, "eval_up": 0, "eval_down": 0}

        class Lo:
            def scores(_, a): return [dict(s) for s in sorted(w.scores.values(), key=lambda s: -s["version"])]
            def _version(_, a): return w.version
            def restore(_, me, aid, b): w.calls.append(("restore", aid, b.version)); w.version = 5

        class Bench:
            def _agent(_, aid): return w.agent if aid == 7 else None
            def _say(_, fid, kind, text, tid=None): w.log.append((kind, text))
            def _team(_, fid): return [w.agent]
            def _flow(_, me, fid): return w.db.q("SELECT * FROM mb_flows WHERE id=?", (fid,), one=True)
            def _admin(_, me): return me

        self.work = SimpleNamespace(db=self.db, improve=Imp(), loadout=Lo(), bench=Bench())
        self.ev = Evolve(self.work)

    def flow(self, **kw):
        self.db.q(f"UPDATE mb_flows SET {', '.join(f'{k}=?' for k in kw)} WHERE id=1", tuple(kw.values()))

    def watch(self): return self.db.q("SELECT * FROM mb_watches ORDER BY id DESC LIMIT 1", one=True)


class Loop(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.w = World(os.path.join(self.dir.name, "m.db"))

    def tearDown(self): self.dir.cleanup()

    def test_a_proposal_is_tested_at_once_as_the_owner(self):
        self.w.ev.proposed(1, 5)
        self.assertEqual(self.w.calls, [("test", "auto-improve", 42, 5)])

    def test_nothing_starts_unless_the_team_chose_self(self):
        self.w.flow(improve="auto")
        self.w.ev.proposed(1, 5); self.w.ev.settled(1, 5, "better")
        self.assertEqual(self.w.calls, [])

    def test_freeze_and_the_weekly_limit_stop_new_work(self):
        self.w.flow(evolve_frozen=1)
        self.w.ev.proposed(1, 5)
        self.w.flow(evolve_frozen=0, evolve_cap=0.4)  # the diagnosis already cost 0.5
        self.w.ev.proposed(1, 5)
        self.assertEqual(self.w.calls, [])
        self.assertIn("frozen", self.w.log[0][1])
        self.assertIn("$0.50 of the $0.40", self.w.log[1][1])

    def test_trial_runs_count_toward_the_limit(self):
        now = time.time()
        self.w.db.q("INSERT INTO mb_trials (improvement_id, run, check_run) VALUES (5, 'r1', 'c1')")
        self.w.db.q("INSERT INTO mb_runs (run, flow_id, cost, started) VALUES ('r1', 1, 2.0, ?), ('c1', 1, 0.25, ?), ('other', 1, 9.0, ?)", (now, now, now))
        self.assertEqual(self.w.ev.spent(self.w.db.q("SELECT * FROM mb_flows WHERE id=1", one=True)), 2.75)  # 0.5 diagnosis + 2.25

    def test_a_failed_test_start_is_said_not_raised(self):
        def no(*a): raise HTTPException(409, "The folder has no scored check")
        self.w.work.improve.test = no
        self.w.ev.proposed(1, 5)
        self.assertIn("no scored check", self.w.log[-1][1])

    def test_better_is_promoted_and_watched_against_the_old_score(self):
        self.w.ev.settled(1, 5, "better")
        self.assertEqual(self.w.calls, [("decide", "promote", 5)])
        w = self.w.watch()
        self.assertEqual((w["from_version"], w["to_version"], w["baseline"], w["status"]), (3, 4, 60, "watching"))

    def test_same_or_worse_waits_for_you(self):
        for s in ("same", "worse", "trial_failed"): self.w.ev.settled(1, 5, s)
        self.assertEqual(self.w.calls, [])

    def test_a_version_that_does_worse_is_rolled_back(self):
        self.w.ev.settled(1, 5, "better")
        self.w.scores[4].update(basis=WINDOW - 1, score=40)
        self.w.ev.recorded(7)
        self.assertEqual(self.w.watch()["status"], "watching")
        self.w.scores[4].update(basis=WINDOW, score=40)
        self.w.ev.recorded(7)
        self.assertEqual(self.w.calls[-1], ("restore", 7, 3))
        self.assertEqual(self.w.watch()["status"], "rolled_back")
        self.w.ev.recorded(7)  # settled: nothing more happens
        self.assertEqual(sum(1 for c in self.w.calls if c[0] == "restore"), 1)

    def test_after_a_rollback_the_next_change_waits_for_you(self):
        self.w.ev.settled(1, 5, "better")
        self.w.scores[4].update(basis=WINDOW, score=10)
        self.w.ev.recorded(7)  # rolled back
        n = len(self.w.calls)
        self.w.db.q("UPDATE mb_improvements SET status='proposed', base_version=5 WHERE id=5")  # the next proposal for Ada
        self.w.ev.proposed(1, 5); self.w.ev.settled(1, 5, "better")
        self.assertEqual(len(self.w.calls), n)
        self.assertIn("rolled back in the last 7 days", self.w.log[-1][1])

    def test_a_version_that_holds_up_is_kept(self):
        self.w.ev.settled(1, 5, "better")
        self.w.scores[4].update(basis=WINDOW, score=58)
        self.w.ev.recorded(7)
        self.assertEqual(self.w.watch()["status"], "kept")
        self.assertNotIn("restore", [c[0] for c in self.w.calls])

    def test_freeze_does_not_stop_a_rollback(self):
        self.w.ev.settled(1, 5, "better")
        self.w.flow(evolve_frozen=1)
        self.w.scores[4].update(basis=WINDOW, score=10)
        self.w.ev.recorded(7)
        self.assertEqual(self.w.watch()["status"], "rolled_back")

    def test_a_change_by_someone_else_ends_the_watch(self):
        self.w.ev.settled(1, 5, "better")
        self.w.version = 9
        self.w.ev.recorded(7)
        w = self.w.watch()
        self.assertEqual(w["status"], "ended")
        self.assertIn("version 9", w["result"])

    def test_view(self):
        self.w.ev.settled(1, 5, "better")
        v = self.w.ev.view(self.w.db.q("SELECT * FROM mb_flows WHERE id=1", one=True))
        self.assertEqual((v["cap"], v["frozen"], v["watches"][0]["agent"]), (10.0, False, "Ada"))


if __name__ == "__main__":
    unittest.main()
