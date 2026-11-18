"""Concurrent runs against one stopping limit: the check alone (agent_core.over), measured.

Milestone 2 C8 measured this: a check before each call against tokens already counted lets runs in flight each pass before any
of them is counted (8 runs, limit 1,000, 300-token calls: 2,400 spent). Milestone 3 put a reservation in front of every model call
under a stopping limit (agent_core.admit; tests in test_budget_reservations.py: 900 spent, never over). These tests keep the
check-only gateway's behaviour on record (over() is still the check every reservation makes, and the drain's): one run alone
stops at the first call past the limit, concurrent runs overshoot by at most one call each without a reservation, and nothing
starts once the limit is crossed."""
import os, tempfile, threading, time, unittest

from app import agent_core
from app.auth import AuthDB

OWNER, LIMIT, CALL = 1, 1_000, 300


class Race(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(); self.addCleanup(self.dir.cleanup)
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        agent_core._core = None
        agent_core.init(self.db)
        self.addCleanup(lambda: setattr(agent_core, "_core", None))
        self.core = agent_core.get()
        self.core.set_limit(OWNER, "system", "race", LIMIT, period="day", label="race", origin="manual", by="test")

    def run_many(self, n, latency):
        go, calls = threading.Barrier(n), []
        def worker():
            agent_core.begin("race", OWNER, "task", ref="race")
            try:
                go.wait()
                while not agent_core.over():
                    time.sleep(latency)                          # the model call: checked before, counted after
                    agent_core.used(CALL); calls.append(1)
            finally:
                agent_core.end("done")
        ts = [threading.Thread(target=worker) for _ in range(n)]
        for t in ts: t.start()
        for t in ts: t.join(30)
        return self.db.q("SELECT COALESCE(SUM(tokens),0) AS n FROM ac_runs WHERE system='race'", one=True)["n"], len(calls)

    def test_one_run_stops_at_the_first_call_past_the_limit(self):
        spent, calls = self.run_many(1, 0)
        self.assertEqual((spent, calls), (1_200, 4))             # 3 calls under, the 4th crosses it, then no more

    def test_without_reservations_concurrent_runs_overshoot_by_at_most_one_call_each(self):
        n = 8
        spent, calls = self.run_many(n, .05)
        self.assertGreaterEqual(spent, LIMIT)
        self.assertLessEqual(spent, LIMIT + n * CALL)            # the bound: one call in flight per concurrent run
        print(f"\n[race, check only] {n} concurrent runs, limit {LIMIT:,}, {CALL} tokens a call: {spent:,} spent "
              f"({spent - LIMIT:,} over, bound {n * CALL:,}), {calls} calls")

    def test_nothing_starts_once_the_limit_is_crossed(self):
        self.run_many(4, .01)
        self.assertIsNotNone(agent_core.preflight(OWNER, "race", ref="race"))  # new work is refused before it starts


if __name__ == "__main__":
    unittest.main()
