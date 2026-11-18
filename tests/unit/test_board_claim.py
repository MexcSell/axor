"""Board starts claimed in the database (Owner, G5-2 final stabilization, 2026-11-11).

Two web replicas on one database each run Work._kick under their own lock. A queued task is claimed by one conditional update
(queued -> working), so exactly one replica makes its run and the other skips it: no run, no slot, no approval used. A review
run is claimed by the database too: at most one open review run per task (unique index). A claim whose run was never made (the
process failed in between) goes back to the queue after CLAIM_STALE. Each "replica" here is its own Work object with its own
lock and its own database connection."""
import os, sys, threading, time, types, unittest

from app import agent_core, mining_work
from app.auth import AuthDB

sys.path.insert(0, os.path.dirname(__file__))
from test_budget_safety import BoardFixture  # noqa: E402
from test_mission_ref import WID  # noqa: E402

AGENTS = 8


class Replicas(BoardFixture):
    def setUp(self):
        super().setUp()
        self.db.q("UPDATE mw_comps SET parallel=? WHERE id=?", (AGENTS, WID))
        for i in range(3, AGENTS + 1):
            self.db.q("INSERT INTO mw_agents (id, comp_id, name, title, job, lead, active) VALUES (?,?,?,?,?,0,1)", (i, WID, f"Agent {i}", "Engineer", "Builds"))
        self.db.q("CREATE UNIQUE INDEX IF NOT EXISTS mw_runs_one_review ON mw_runs (task_id) WHERE kind='review' AND status='running'")
        self.lock = threading.Lock()
        self.reviews = []
        self.replicas = [self.replica() for _ in range(2)]

    def replica(self):
        """Another web process: the same board code with its own lock, its own connection and its own start pool."""
        path = getattr(self.db, "path", None)
        w = object.__new__(mining_work.Work)
        w.__dict__.update({k: v for k, v in self.w.__dict__.items()})
        w.db, w.lock = AuthDB(path) if path else self.db, threading.Lock()
        w.__dict__.pop("_mw_cols", None)
        w._kick = mining_work.Work._kick.__get__(w)
        def submit(fn, *a):
            with self.lock:
                (self.starts if getattr(fn, "__name__", "") == "_work" else self.reviews).append(a[0])
        w.pool = types.SimpleNamespace(submit=submit)
        return w

    def race(self, rounds=1):
        go = threading.Barrier(len(self.replicas))
        def run(w):
            go.wait()
            for _ in range(rounds): w._kick(WID)
        th = [threading.Thread(target=run, args=(w,)) for w in self.replicas]
        for x in th: x.start()
        for x in th: x.join(30)

    def per_task(self, kind="task"):
        return {r["task_id"]: r["n"] for r in self.db.q("SELECT task_id, COUNT(*) n FROM mw_runs WHERE kind=? GROUP BY task_id", (kind,))}

    def test_two_replicas_starting_the_same_queued_tasks_make_exactly_one_run_each(self):
        for round_ in range(10):  # ten rounds of AGENTS queued tasks, both replicas starting at the same instant
            self.db.q("UPDATE mw_runs SET status='done' WHERE status='running'")         # the agents are free again
            ids = [self.queued(f"Task {round_}.{i}", agent=i + 1) for i in range(AGENTS)]
            self.race()
            runs = self.per_task()
            self.assertEqual([runs.get(t, 0) for t in ids], [1] * AGENTS, f"round {round_}")  # exactly one run per task
            for t in ids:
                r = self.row(t)
                self.assertEqual((r["status"], r["runs"]), ("working", 1))
                self.assertEqual(self.db.q("SELECT id FROM mw_runs WHERE task_id=? AND kind='task'", (t,), one=True)["id"], r["run_id"])
        self.assertEqual(len(self.starts), len(set(self.starts)))                         # no task handed to a worker twice

    def test_two_replicas_starting_the_same_review_make_one_review_run(self):
        for i in range(5):
            t = self.queued(f"Reviewed {i}", agent=2)
            self.db.q("UPDATE mw_tasks SET status='checking', reviewer=1 WHERE id=?", (t,))
            self.db.q("UPDATE mw_runs SET status='done' WHERE status='running'")
            self.race()
            self.assertEqual(self.per_task("review").get(t), 1, f"review {i}")
            self.db.q("UPDATE mw_tasks SET status='done' WHERE id=?", (t,))                 # its review ran (as _review would close it)
        self.assertEqual(len(self.reviews), 5)

    def test_a_claim_whose_run_was_never_made_goes_back_to_the_queue_and_starts_once(self):
        t = self.queued("Interrupted start")
        w = self.replicas[0]
        real = w._ins
        def crash(sql, args):
            if "'task','running'" in sql: raise RuntimeError("the process failed between the claim and the run")
            return real(sql, args)
        w._ins = crash
        with self.assertRaises(RuntimeError): w._kick(WID)
        w._ins = real
        r = self.row(t)
        self.assertEqual((r["status"], r["run_id"], self.per_task().get(t, 0)), ("working", None, 0))   # claimed, no run
        for _ in range(5): w._kick(WID)
        self.assertEqual((self.row(t)["status"], self.starts), ("working", []))          # not before CLAIM_STALE: it may still be starting
        self.db.q("UPDATE mw_tasks SET updated=? WHERE id=?", (time.time() - mining_work.CLAIM_STALE - 1, t))
        self.race(rounds=2)  # the first pass puts it back in the queue; the next one checks its budget and starts it
        r = self.row(t)
        self.assertEqual((r["status"], r["runs"], self.per_task().get(t), self.starts), ("working", 1, 1, [t]))  # recovered, started once


if __name__ == "__main__":
    unittest.main()
