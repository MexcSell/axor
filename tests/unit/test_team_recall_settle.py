"""mining_work.Work: a team task that gives up settles its recalled experiences as a failure (experience.py), so the recall
track record can learn what to avoid; a failure the Autoloop takes as not the task's fault, and one under FAILS, settle nothing;
a user's send-back settles as partial, as a reviewer's revise does."""
import os, tempfile, time, unittest

from app import mining_work
from app.auth import AuthDB


class KB:
    def __init__(self): self.calls = []
    def exp_outcome(self, uid, ctx, outcome): self.calls.append((uid, ctx, outcome))


class Loop:
    def __init__(self, handled): self.handled = handled
    def failed(self, *a): return self.handled


class SettleTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        self.db.q("""CREATE TABLE mw_tasks (id INTEGER PRIMARY KEY, comp_id INTEGER, status TEXT, note TEXT, fails INTEGER DEFAULT 0,
                     hold TEXT, updated REAL)""")
        self.w = mining_work.Work.__new__(mining_work.Work)
        self.w.db, self.w.kb, self.w.loop = self.db, KB(), None
        self.w._end = lambda *a, **k: None
        self.c = {"user_id": 7}

    def tearDown(self): self.dir.cleanup()

    def run_fail(self, tid):
        self.db.q("UPDATE mw_tasks SET status='working' WHERE id=?", (tid,))
        self.w._done_run(self.c, 1, "failed", error="boom", tid=tid, note="Failed", failed=True)

    def test_gives_up_settles_failure(self):
        self.db.q("INSERT INTO mw_tasks (id, comp_id, status, fails) VALUES (3, 1, 'working', 0)")
        self.run_fail(3)
        # the work's own failure ("boom" is the task itself): what this attempt recalled learns it at once; the retry recalls afresh
        self.assertEqual(self.w.kb.calls, [(7, "mw:3", "failure")])
        for _ in range(mining_work.FAILS - 1): self.run_fail(3)
        self.assertEqual(self.db.q("SELECT hold FROM mw_tasks WHERE id=3", one=True)["hold"], "failed")
        self.assertEqual(set(self.w.kb.calls), {(7, "mw:3", "failure")})

    def test_an_environment_failure_settles_only_when_the_task_gives_up(self):
        self.db.q("INSERT INTO mw_tasks (id, comp_id, status, fails) VALUES (5, 1, 'working', 0)")
        self.db.q("UPDATE mw_tasks SET status='working' WHERE id=5")
        self.w._done_run(self.c, 1, "failed", error="Connection timed out", tid=5, note="Failed", failed=True)
        self.assertEqual(self.w.kb.calls, [])  # a timeout says nothing about the experiences it recalled
        for _ in range(mining_work.FAILS - 1):
            self.db.q("UPDATE mw_tasks SET status='working' WHERE id=5")
            self.w._done_run(self.c, 1, "failed", error="Connection timed out", tid=5, note="Failed", failed=True)
        self.assertEqual(self.w.kb.calls, [(7, "mw:5", "failure")])  # it gave up: that is an outcome

    def test_not_the_tasks_fault_settles_nothing(self):
        self.db.q("INSERT INTO mw_tasks (id, comp_id, status, fails) VALUES (4, 1, 'working', 5)")
        self.w.loop = Loop(True)
        self.run_fail(4)
        self.assertEqual(self.w.kb.calls, [])


if __name__ == "__main__":
    unittest.main()
