"""T-9 (2026-11-13): a board task whose run a server restart cut off goes under the existing transient retry rule (D-015 D2):
one counted, delayed retry per restart while the task has retries left under its team's policy, on autopilot teams and others;
with none left it stays parked for a person. Before, an autopilot team's cut-off task was put straight back in the queue on
every restart, uncounted (no bound), and a team without autopilot waited for a person. A task that was only queued when the
server stopped is not counted: back in the queue on autopilot teams, parked elsewhere, as before."""
import os, sys, time, unittest

sys.path.insert(0, os.path.dirname(__file__))
from app import mining_autoloop  # noqa: E402
from test_budget_safety import BoardFixture  # noqa: E402
from test_mission_ref import WID  # noqa: E402

NOTE = "Stopped by a server restart: start it again."


class RestartRetry(BoardFixture):
    def setUp(self):
        super().setUp()
        for col in ("autopilot INTEGER DEFAULT 0",):
            try: self.db.q(f"ALTER TABLE mw_comps ADD COLUMN {col}")
            except Exception: pass  # noqa: BLE001
        try: self.db.q("ALTER TABLE mw_runs ADD COLUMN error TEXT")
        except Exception: pass  # noqa: BLE001
        self.db.q("UPDATE mw_comps SET status='active', paused=0, autopilot=0 WHERE id=?", (WID,))
        self.events = []
        self.w._event = lambda wid, kind, text, **k: self.events.append(text)

    def boot(self):
        """What a restart does to the board: mining_work.Work.__init__'s three statements, then the Autoloop's recovery."""
        now, q = time.time(), self.db.q
        q("UPDATE mw_runs SET status='failed', error='Stopped by a server restart.', finished=? WHERE status='running'", (now,))
        q("UPDATE mw_tasks SET status='todo', note=?, updated=? WHERE status IN ('queued','working')", (NOTE, now))
        self.loop._recover()

    def working(self, title="Build the image", retries=0):
        tid = self.queued(title)
        rid = self.db.q("INSERT INTO mw_runs (comp_id, task_id, agent_id, kind, status, started) VALUES (?,?,2,'task','running',?) RETURNING id", (WID, tid, time.time()), one=True)["id"]
        self.db.q("UPDATE mw_tasks SET status='working', run_id=?, retries=? WHERE id=?", (rid, retries, tid))
        return tid

    def retry_now(self, tid):
        """The retry's time has come: the tick claims it and the board starts it (released on one pass, started on the same kick)."""
        self.db.q("UPDATE mw_tasks SET retry_at=? WHERE id=?", (time.time() - 1, tid))
        self.loop.ticked = 0; self.loop.tick()

    def test_a_restart_mid_run_leads_to_exactly_one_automatic_retry(self):
        tid = self.working()
        self.boot()
        t = self.row(tid)
        self.assertEqual((t["status"], t["hold"], t["retries"], t["fail_class"]), ("todo", "retry", 1, "transient"))
        self.assertGreater(t["retry_at"], time.time() + 20)                              # delayed, not at once
        self.assertIn("Retry 1 of 2", t["note"]); self.assertIn("server restart", t["note"])
        self.loop.ticked = 0; self.loop.tick()
        self.assertEqual(self.starts, [])                                                # not before its time
        self.retry_now(tid)
        self.assertEqual(self.starts, [tid])
        for _ in range(3): self.loop.ticked = 0; self.loop.tick()
        self.assertEqual(self.starts, [tid])                                             # once
        self.assertTrue(any("retries by itself" in e and "counted as a retry" in e for e in self.events))

    def test_it_is_the_same_on_a_team_with_autopilot_and_it_is_counted_there_too(self):
        self.db.q("UPDATE mw_comps SET autopilot=1 WHERE id=?", (WID,))
        tid = self.working()
        self.boot()
        t = self.row(tid)
        self.assertEqual((t["status"], t["hold"], t["retries"]), ("todo", "retry", 1))   # before: 'queued' at once, retries 0
        self.assertEqual(self.starts, [])

    def test_a_second_restart_while_it_waits_for_its_retry_changes_nothing(self):
        tid = self.working()
        self.boot()
        before = dict(self.row(tid))
        self.boot(); self.boot()
        after = dict(self.row(tid))
        self.assertEqual((after["status"], after["hold"], after["retries"], after["retry_at"]), (before["status"], before["hold"], 1, before["retry_at"]))

    def test_restarts_that_keep_cutting_it_off_stop_after_the_teams_retries(self):
        tid = self.working()
        for n in (1, 2):                                                                 # the policy's two retries
            self.boot()
            self.assertEqual((self.row(tid)["hold"], self.row(tid)["retries"]), ("retry", n))
            self.db.q("UPDATE mw_tasks SET status='working', hold=NULL, retry_at=NULL WHERE id=?", (tid,))    # the retry started…
            self.db.q("INSERT INTO mw_runs (comp_id, task_id, agent_id, kind, status, started) VALUES (?,?,2,'task','running',?)", (WID, tid, time.time()))
        self.boot()                                                                      # …and the server went down again
        t = self.row(tid)
        self.assertEqual((t["status"], t["hold"], t["retries"]), ("todo", None, 2))
        self.assertIn("automatic retries are used: start it again", t["note"])
        for _ in range(3): self.loop.ticked = 0; self.loop.tick()
        self.assertEqual(self.row(tid)["status"], "todo")                                # it waits for a person: no loop

    def test_a_task_that_had_already_used_its_last_retry_parks_at_boot(self):
        tid = self.working(retries=2)
        self.boot()
        t = self.row(tid)
        self.assertEqual((t["status"], t["hold"], t["retries"], t["retry_at"]), ("todo", None, 2, None))
        self.assertIn("start it again", t["note"])
        self.db.q("UPDATE mw_comps SET autopilot=1 WHERE id=?", (WID,))
        self.db.q("UPDATE mw_tasks SET status='working' WHERE id=?", (tid,))
        self.db.q("INSERT INTO mw_runs (comp_id, task_id, agent_id, kind, status, started) VALUES (?,?,2,'task','running',?)", (WID, tid, time.time()))
        self.boot()
        self.assertEqual((self.row(tid)["status"], self.row(tid)["hold"]), ("todo", None))   # on autopilot too: the old recovery would have re-queued it

    def test_a_task_that_was_only_queued_is_not_counted(self):
        tid = self.queued("Waiting its turn")
        self.boot()
        t = self.row(tid)
        self.assertEqual((t["status"], t["hold"], t["retries"] or 0, t["note"]), ("todo", None, 0, NOTE))       # no autopilot: parked, as before
        self.db.q("UPDATE mw_comps SET autopilot=1 WHERE id=?", (WID,))
        self.db.q("UPDATE mw_tasks SET status='queued' WHERE id=?", (tid,))
        self.boot()
        t = self.row(tid)
        self.assertEqual((t["status"], t["hold"], t["retries"] or 0), ("queued", None, 0))                       # autopilot: back in the queue, uncounted, as before

    def test_a_paused_team_and_an_observe_mode_team_are_left_alone(self):
        tid = self.working()
        self.db.q("UPDATE mw_comps SET paused=1 WHERE id=?", (WID,))
        self.boot()
        self.assertEqual((self.row(tid)["hold"], self.row(tid)["retries"] or 0, self.row(tid)["note"]), (None, 0, NOTE))
        self.db.q("UPDATE mw_comps SET paused=0 WHERE id=?", (WID,))
        self.db.q("INSERT INTO ml_policy (comp_id, mode) VALUES (?, 'observe')", (WID,))
        self.db.q("UPDATE mw_tasks SET status='working' WHERE id=?", (tid,))
        self.db.q("INSERT INTO mw_runs (comp_id, task_id, agent_id, kind, status, started) VALUES (?,?,2,'task','running',?)", (WID, tid, time.time()))
        self.boot()
        self.assertEqual((self.row(tid)["hold"], self.row(tid)["retries"] or 0), (None, 0))

    def test_a_team_whose_policy_allows_no_retries_parks_it(self):
        self.db.q("INSERT INTO ml_policy (comp_id, retries) VALUES (?, 0)", (WID,))
        tid = self.working()
        self.boot()
        self.assertEqual((self.row(tid)["status"], self.row(tid)["hold"], self.row(tid)["retries"] or 0), ("todo", None, 0))


if __name__ == "__main__":
    unittest.main()
