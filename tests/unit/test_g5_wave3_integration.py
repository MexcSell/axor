"""G5 wave-3 cross-stream contracts (integration owner, 2026-11-13). Each test crosses two streams' code, as merged on
dev/integration-g5-wave3; a clean textual merge can't show any of them.

1. L5.3 → R3.3 (IC-3): an API change the Owner's endpoint watch finds (mining_web, written outside risk_feeds) is a new register
   row scoped to the team, so the team's persistent mission runs an early cycle that names it. Negative control: without R3.3's
   new-row detection there is no early cycle.
2. W7 → G5-3 (IC-4, C3): AXoR's own readiness check runs never become the team's recurring sandbox failure, by the marker W7
   itself defines (sandbox.READINESS_USER); the team's own runs failing the same way still do.
3. W7 → V4.4 (IC-4, IC-8): a clean readiness check run in the team's sandbox never backs a benchmark row: the evidence is the
   calling run's own clean sandbox run only.
"""
import os, sys, time, types, threading, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
from app import mining_release as R, missions, orchestrator, sandbox  # noqa: E402
from app.auth import AuthDB  # noqa: E402
import test_endpoint_watch as tw  # noqa: E402  (modules, not classes: their own tests don't run again here)
import test_g54_release_evidence as tr  # noqa: E402
import test_risk_feeds as tf  # noqa: E402
from test_mission_persistent_evidence import TEAM_ACCOUNT, WID  # noqa: E402


@tr.own_tests
class WatchToCycle(tw.Watch):
    def _api_change_then_tick(self):
        self.fresh()
        mid = self.ok_mission()
        self.assertEqual(self.mx._cycle_tick(self.m(mid))["trigger"], "baseline"); self.process()
        self.declare(); self.round()                                                     # the watch's baseline raises nothing
        self.mx._looked.clear()
        self.assertIsNone(self.mx._cycle_tick(self.m(mid)))
        self.doc["paths"]["/task"] = {"get": {"responses": {"200": {"description": "x"}}}}
        self.assertEqual(self.round(tw.W.ENDPOINT_EVERY), 1)                             # the API changed: one register row
        (row,) = self.rows()
        self.mx._looked.clear()
        return mid, row, self.mx._cycle_tick(self.m(mid))

    def test_an_api_change_found_by_the_watch_starts_an_early_cycle_that_names_it(self):
        mid, row, rec = self._api_change_then_tick()
        self.assertEqual((rec["trigger"], rec["new_risks"]), ("early", [row["id"]]))
        self.assertIn(row["id"], rec["risks"]["ids"])
        self.assertEqual(rec["risks"]["critical"], 0)                                     # G3-7 holds for the monitor's rows too
        self.assertIn("new risk row", rec["decision"]["reason"])

    def test_negative_control_without_new_row_detection_there_is_no_early_cycle(self):
        with mock.patch.object(missions.Missions, "_new_risks", staticmethod(lambda ev, last: [])):
            _mid, _row, rec = self._api_change_then_tick()
        self.assertIsNone(rec)


class CheckRunsInTheFeed(tf.FeedBase):
    def test_the_marker_w7_defines_is_the_one_the_feed_leaves_out(self):
        self.assertIn(sandbox.READINESS_USER, orchestrator.RISK_SBX_NOT_TEAM)
        self.db.q("ALTER TABLE mw_sbx ADD COLUMN by_user TEXT")
        for who in (sandbox.READINESS_USER,) * 4:
            self.db.q("INSERT INTO mw_sbx (comp_id, status, error, started, by_user) VALUES (5, 'error', 'The sandbox is busy', ?, ?)", (self.now, who))
        self.o.diagnose_sandbox(); self.o.risk_feeds(self.now)
        self.assertEqual(self.rows("sandbox"), [])
        for _ in range(3):  # positive control: the team's own runs
            self.db.q("INSERT INTO mw_sbx (comp_id, task_id, status, error, started, by_user) VALUES (5, 1, 'error', 'The sandbox is busy', ?, 'agent')", (self.now,))
        self.o.diagnose_sandbox(); self.o.risk_feeds(self.now)
        self.assertEqual([r["rkey"] for r in self.rows("sandbox")], ["sbx:comp:5:busy"])


@tr.own_tests
class CheckRunsAndBenchmarks(tr.Release):
    def test_a_clean_check_run_never_backs_a_benchmark_and_the_runs_own_clean_run_does(self):
        self.freeze()
        chk = self.db.q("""INSERT INTO mw_sbx (comp_id, run_id, by_user, command, status, exit_code, started, finished) VALUES (?,?,?,?,?,?,?,?)
                           RETURNING id""", (tr.WID, None, sandbox.READINESS_USER, "echo check", "done", 0, time.time() - 30, time.time()), one=True)["id"]
        self.assertIsNone(self.bench(run=tr.RUN)["evidence_ref"])                         # the calling run has no clean run of its own
        own = tr.sbx(self.db.q, tr.WID, tr.RUN)
        got = self.bench(run=tr.RUN)["evidence_ref"]
        self.assertEqual(got, f"sbx:{own}")                                              # positive control
        self.assertNotEqual(got, f"sbx:{chk}")


if __name__ == "__main__":
    unittest.main()
