"""Competition teams: a board of finished tasks still takes new work, and the Status tab tells current trouble from history.

- mining_work: MAX_TASKS counts open tasks, so 400 done tasks don't stop the Director's plans, follow-ups or the user's own tasks.
- mining_status: a failure whose task is done or ran fine afterwards is marked resolved and doesn't make a "failing" blocker;
  a dry board says when autopilot really plans (PLAN_GAP after the last plan) and next_plan agrees; a full board says so.
"""
import os, tempfile, time, unittest

from fastapi import HTTPException

from app import mining_status, mining_work
from app.auth import AuthDB

WID = 5


class FakeM:
    def _model(self, c, *a): return "fake:model"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = db = AuthDB(os.path.join(self.tmp.name, "t.db"))
        db.q("""CREATE TABLE mw_tasks (id INTEGER PRIMARY KEY, comp_id INTEGER, title TEXT, detail TEXT, status TEXT, priority TEXT, agent_id INTEGER,
                due TEXT, origin TEXT, hold TEXT, fails INTEGER DEFAULT 0, reviewer INTEGER, run_id INTEGER, created REAL, updated REAL, done_at REAL,
                queued REAL, note TEXT, summary TEXT, mission TEXT)""")
        db.q("""CREATE TABLE mw_runs (id INTEGER PRIMARY KEY, comp_id INTEGER, agent_id INTEGER, task_id INTEGER, kind TEXT, status TEXT,
                started REAL, finished REAL, error TEXT, tokens INTEGER DEFAULT 0)""")
        db.q("CREATE TABLE mw_notes (id INTEGER PRIMARY KEY, comp_id INTEGER)")
        self.now = time.time()
        self.comp = {"id": WID, "status": "active", "paused": 0, "autopilot": 1, "parallel": 4, "plan_every": 2, "last_plan": self.now - 60,
                     "goal": "Top the board", "ends": "", "starts": "", "created": self.now - 86400, "pilot_note": ""}
        self.agents = [{"id": 1, "name": "Gus", "lead": 1, "active": 1}, {"id": 2, "name": "Devon", "lead": 0, "active": 1}]
        w = object.__new__(mining_work.Work)
        w.db, w.m, w.director, w.loop, w.web = db, FakeM(), None, None, None
        w._own = lambda me, wid: (self.comp, {"id": 9})
        w._agents = lambda wid: self.agents
        w._summary = lambda w_, c: {"budget": 0, "day": 0}
        w._model = lambda c, a, *k: "fake:model"
        w._event = lambda *a, **k: None
        w.view = lambda me, wid: {"ok": True}
        self.w, self.me = w, {"id": 4, "username": "leonardo"}

    def tearDown(self): self.tmp.cleanup()

    def tasks(self, n, status="done", agent=2):
        for i in range(n):
            self.db.q("INSERT INTO mw_tasks (comp_id, title, status, priority, agent_id, created, updated, done_at) VALUES (?,?,?,?,?,?,?,?)",
                      (WID, f"Task {i}", status, "medium", agent, self.now - 7200, self.now - 7200, self.now - 7200 if status == "done" else None))

    def run_row(self, task, status, at, kind="task", error=None):
        self.db.q("INSERT INTO mw_runs (comp_id, agent_id, task_id, kind, status, started, finished, error) VALUES (?,?,?,?,?,?,?,?)",
                  (WID, 2, task, kind, status, at - 30, at, error))

    def status(self):
        return mining_status.Status(self.w).status(self.me, WID)


class OpenCap(Base):
    def test_done_tasks_dont_count_against_the_cap(self):
        self.tasks(mining_work.MAX_TASKS)
        self.assertEqual(self.w._open(WID), 0)
        self.w._ins = lambda sql, args: self.db.q(sql, args) or 1
        self.w.add_task(self.me, WID, mining_work.TaskIn(title="Rebuild the candidate"))  # no 409

    def test_open_tasks_still_cap_the_board(self):
        self.tasks(mining_work.MAX_TASKS, status="todo")
        with self.assertRaises(HTTPException) as e: self.w.add_task(self.me, WID, mining_work.TaskIn(title="One more"))
        self.assertEqual(e.exception.status_code, 409)


class StatusTab(Base):
    def test_a_dry_board_of_done_tasks_says_when_autopilot_plans(self):
        self.tasks(400)
        st = self.status()
        dry = next(b for b in st["blockers"] if b["key"] == "dry")
        self.assertRegex(dry["detail"], r"plan in 1[34] min\.")  # 15 min after the last plan, a minute ago
        self.assertFalse(any(b["key"] == "full" for b in st["blockers"]))
        self.assertAlmostEqual(st["now"]["next_plan"], self.comp["last_plan"] + mining_work.PLAN_GAP)  # not last_plan + 2 h

    def test_a_board_full_of_open_tasks_says_so(self):
        self.tasks(mining_work.MAX_TASKS, status="todo", agent=None)
        st = self.status()
        self.assertTrue(any(b["key"] == "full" for b in st["blockers"]))
        self.assertFalse(any(b["key"] == "dry" for b in st["blockers"]))  # not both side by side
        self.assertIsNone(st["now"]["next_plan"])

    def test_a_failure_fixed_since_is_history(self):
        self.tasks(1)
        self.run_row(1, "failed", self.now - 3600, error="Devon finished without filing the work.")
        self.run_row(1, "done", self.now - 1800)
        st = self.status()
        self.assertTrue(st["errors"][0]["resolved"])
        self.assertFalse(any(b["key"] == "failing" for b in st["blockers"]))

    def test_a_failure_nothing_fixed_is_current(self):
        self.tasks(1, status="todo")
        self.run_row(1, "done", self.now - 3600)
        self.run_row(1, "failed", self.now - 1800, error="Devon finished without filing the work.")
        st = self.status()
        self.assertFalse(st["errors"][0]["resolved"])
        self.assertTrue(any(b["key"] == "failing" for b in st["blockers"]))


if __name__ == "__main__":
    unittest.main()
