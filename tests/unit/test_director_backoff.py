"""The Director's report tick waits FAIL_GAP after a failed report run, even with an answered report waiting.

On 2026-11-14 the server's Claude Code token expired. Team 23 had an answered report waiting, and that path skipped every gap,
so the tick (every 15 s) started a report run, it died in about 3.5 s on the dead login, and the next tick started another:
1,923 failed runs in 9 hours.
"""
import os, sys, unittest
from unittest import mock

from app import mining_director

sys.path.insert(0, os.path.dirname(__file__))
from test_budget_safety import BoardFixture  # noqa: E402
from test_mission_ref import WID  # noqa: E402


class ReportBackoff(BoardFixture):
    def setUp(self):
        super().setUp()
        self.db.q("""CREATE TABLE IF NOT EXISTS mw_reports (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, agent_id INTEGER,
                     run_id INTEGER, ts REAL, headline TEXT, body TEXT, asks TEXT, settled TEXT, status TEXT, reply TEXT, replied REAL,
                     by_user TEXT)""")
        for col in ("last_report REAL", "relay INTEGER DEFAULT 1"):
            try: self.db.q(f"ALTER TABLE mw_comps ADD COLUMN {col}")
            except Exception: pass  # noqa: BLE001
        self.db.q("UPDATE mw_comps SET last_report=0 WHERE id=?", (WID,))
        # the user answered the last report: the path that skipped REPORT_GAP and QUICK_GAP
        self.db.q("INSERT INTO mw_reports (comp_id, status) VALUES (?, 'answered')", (WID,))
        self.now = 1_800_000_000.0
        self.started = []
        self.d = d = object.__new__(mining_director.Director)
        d.db, d.w = self.db, self.w
        self.w._over, self.w._model = (lambda w: False), (lambda c, a, *k: "fake:model")
        d._lead = lambda wid: {"id": 1, "name": "Gus"}
        d._start = self.fake_start
        self.outcome = "failed"
        for p in (mock.patch.object(mining_director.time, "time", lambda: self.now),
                  mock.patch.object(mining_director.agent_core, "preflight", lambda *a, **k: None)):
            p.start(); self.addCleanup(p.stop)

    def fake_start(self, w, c, lead, note=""):
        """A report run that ends 3.5 s later with self.outcome (a dead login fails like this)."""
        self.started.append(self.now)
        self.db.q("INSERT INTO mw_runs (comp_id, agent_id, kind, status, started, finished) VALUES (?,?,'report',?,?,?)",
                  (w["id"], lead["id"], self.outcome, self.now, self.now + 3.5))
        self.db.q("UPDATE mw_comps SET last_report=? WHERE id=?", (self.now, w["id"]))
        return 1

    def tick(self, advance=15):
        self.now += advance
        self.d._tick_one(self.db.q("SELECT * FROM mw_comps WHERE id=?", (WID,), one=True))

    def test_a_failed_run_waits_fail_gap_then_tries_again(self):
        self.tick()
        self.assertEqual(len(self.started), 1)                                   # the answered report starts at once
        for _ in range(int(mining_director.FAIL_GAP // 15) - 1): self.tick()
        self.assertEqual(len(self.started), 1)                                   # inside FAIL_GAP: no restart
        self.tick(advance=30)
        self.assertEqual(len(self.started), 2)                                   # after it: one more try

    def test_the_11_14_incident_is_a_few_runs_an_hour(self):
        for _ in range(9 * 3600 // 15): self.tick()                              # 9 hours of 15 s ticks, every run failing
        self.assertLessEqual(len(self.started), 9 * 3600 // mining_director.FAIL_GAP + 1)   # 37 at most, was 1,923
        self.assertGreater(len(self.started), 30)                                # it keeps trying: a fixed login recovers

    def test_a_run_that_did_not_fail_leaves_the_answered_path_as_it_was(self):
        self.outcome = "done"
        self.tick(); self.tick()
        self.assertEqual(len(self.started), 2)                                   # an answered report still goes right away

    def test_a_cancelled_run_is_not_held_back(self):
        self.outcome = "cancelled"
        self.tick(); self.tick()
        self.assertEqual(len(self.started), 2)

    def test_another_teams_failure_does_not_hold_this_team(self):
        self.db.q("INSERT INTO mw_runs (comp_id, kind, status, started, finished) VALUES (?, 'report', 'failed', ?, ?)",
                  (WID + 1000, self.now, self.now))
        self.tick()
        self.assertEqual(len(self.started), 1)


if __name__ == "__main__":
    unittest.main()
