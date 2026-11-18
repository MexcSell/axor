"""AXoR's own Docker check job (D-035, Proposed): without it the first task that declares `docker` could never start, because the
probe passes only on a finished VM job and only an agent's task starts one. The job is fixed in code, goes through the same
Work._docker_job an agent's call does, is one at a time for the whole server, and is never team work or evidence of a score."""
import os, sys, threading, time, types, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
from app import mining_work, mission_ops as mo, runner as V, sandbox  # noqa: E402
import test_mission_persistent_evidence as tp  # noqa: E402
from test_g54_release_evidence import sbx_table  # noqa: E402
from test_vm_runner import BASE, FILES, FakeRunner, board  # noqa: E402


class Failing(FakeRunner):
    def run(self, job, files, label="", cancelled=None, started=None):
        self.jobs.append((job, files)); started and started("job-2-bad")
        clean = {k: v for k, v in job.items() if k != "id"}
        return V.finish(clean, {}, "failed", 1, "The VM ended without reporting.", "", "job-2-bad", V.inputs(clean, files), 9.0, None, [], [])


class VmCheck(tp.Base):
    def setUp(self):
        super().setUp()
        self._base = V.BASE_SHA; V.BASE_SHA = BASE
        q = self.db.q
        q("DROP TABLE IF EXISTS mw_sbx"); sbx_table(q); q("ALTER TABLE mw_sbx ADD COLUMN net TEXT")
        q("DROP TABLE IF EXISTS mw_files")
        q("""CREATE TABLE mw_files (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, path TEXT, content TEXT, size INTEGER, agent_id INTEGER,
             updated REAL, UNIQUE (comp_id, path))""")
        for p, t in FILES.items(): q("INSERT INTO mw_files (comp_id, path, content, size) VALUES (?,?,?,?)", (tp.WID, p, t, len(t)))
        self.w = board(self.db, files={})   # a job that names no artifacts hands none back (the stand-in runner would otherwise invent one)
        self.w.m = types.SimpleNamespace(_campaign=lambda cid: {"netuid": 61})
        self.ch = types.SimpleNamespace(db=self.db, w=self.w, _has=lambda t: True)
        self.comp = {"id": tp.WID, "campaign_id": 1}
        mo._probe_cache.clear(); mo._vm_check["at"] = 0.0; mo._awaiting.clear()

    def tearDown(self): V.BASE_SHA = self._base; super().tearDown()

    def probe(self, comp="team", **kw): return mo.probe(self.ch, self.comp if comp == "team" else comp, "docker", fresh=not kw, **kw)

    def settle(self):
        """The check job runs in a background thread: wait for it to leave 'running' (the stand-in runner answers at once)."""
        for t in threading.enumerate():
            if t.name == "readiness-vm-check": t.join(10)

    def rows(self): return [dict(r) for r in self.db.q("SELECT * FROM mw_sbx ORDER BY id")]

    def later(self, secs=mo.NET_CHECK_EVERY + 60):
        self.db.q("UPDATE mw_sbx SET started=started-?, finished=finished-?", (secs, secs)); mo._vm_check["at"] -= secs

    def test_a_fresh_server_proves_docker_by_its_own_check_job(self):
        p = self.probe()
        self.assertEqual(p["state"], "UNKNOWN"); self.assertIn("started a small check job of its own", p["evidence"])
        self.settle()
        (job, files), (row,) = self.w.runner.jobs[0], self.rows()
        self.assertEqual(len(self.w.runner.jobs), 1)
        self.assertEqual((job["kind"], job["network"], job["memory_mb"], job["cpus"], job["timeout_s"]), ("run", "none", 1024, 1, 60))
        self.assertIn("docker version", job["command"])
        self.assertEqual(files, {})                                                    # no team file enters the VM
        self.assertFalse(job.get("images") or job.get("artifacts") or job.get("score_file") or job.get("secrets"))
        self.assertEqual((row["by_user"], row["task_id"], row["agent_id"], row["services"], row["status"], row["exit_code"]), (sandbox.READINESS_USER, None, None, V.SERVICE, "done", 0))
        p = self.probe()
        self.assertEqual((p["state"], p["how"]), ("PASS", "job"))
        self.assertIn(f"AXoR's own check job #{row['id']}", p["evidence"]); self.assertIn("nothing about registries", p["evidence"])
        self.probe(); self.settle()
        self.assertEqual(len(self.w.runner.jobs), 1)                                   # proven: no further job

    def test_the_held_task_is_not_kept_waiting_long_after_the_check_ends(self):
        """An UNKNOWN that only means "the check is under way" is asked again after CHECK_RETRY, not after PROBE_TTL: in staging a
        task stayed held for minutes after its check job had passed in 12 seconds."""
        ask = lambda: mo.probe(self.ch, self.comp, "docker")              # as the dispatcher asks: the cached answer while it is fresh
        self.assertEqual(ask()["state"], "UNKNOWN"); self.settle()
        self.assertEqual(ask()["state"], "UNKNOWN")                       # within CHECK_RETRY: the same answer, nothing asked again
        mo._probe_cache[(tp.WID, "docker", None)]["checked"] -= mo.CHECK_RETRY + 1
        self.assertEqual(ask()["state"], "PASS")                          # well inside PROBE_TTL
        self.assertLess(mo.CHECK_RETRY, mo.PROBE_TTL)
        self.assertNotIn("retry_in", ask())                               # a settled answer keeps the ordinary time

    def test_an_agents_job_passes_it_too_and_is_named_as_such(self):
        out = self.w._docker_job(self.comp, {"netuid": 61}, {"kind": "run", "network": "none", "command": "true", "paths": [".none"]}, task=5, run=7, agent={"id": 1, "name": "Devon"})
        p = self.probe()
        self.assertEqual(p["state"], "PASS"); self.assertIn(f"VM runner job #{out['sbx']}", p["evidence"]); self.assertNotIn("own check job", p["evidence"])
        self.settle(); self.assertEqual(len(self.w.runner.jobs), 1)                    # no check job was needed

    def test_one_at_a_time_for_the_whole_server(self):
        self.assertTrue(mo._start_vm_check(self.ch, self.comp))
        self.assertIs(mo._start_vm_check(self.ch, {"id": tp.WID + 1, "campaign_id": 1}), False)   # another team probing at the same moment
        self.settle()
        mo._vm_check["at"] = 0.0                                                       # as another web process would see it: only the row
        self.assertIs(mo._start_vm_check(self.ch, self.comp), False)
        self.db.q("UPDATE mw_sbx SET status='running', started=?", (time.time() - mo.NET_CHECK_EVERY - 60,))
        self.assertIs(mo._start_vm_check(self.ch, self.comp), False)                   # still running, though started a while ago
        self.settle(); self.assertEqual(len(self.w.runner.jobs), 1)

    def test_a_check_row_left_running_by_a_dead_process_doesnt_block_checks_for_ever(self):
        self.assertTrue(mo._start_vm_check(self.ch, self.comp)); self.settle()
        self.db.q("UPDATE mw_sbx SET status='running', finished=NULL, started=?", (time.time() - 7200,))   # nothing closed it
        mo._vm_check["at"] = 0.0
        self.assertTrue(mo._start_vm_check(self.ch, self.comp)); self.settle()
        self.assertEqual(len(self.w.runner.jobs), 2)

    def test_a_check_job_that_never_got_a_vm_says_nothing_about_the_runner(self):
        class Busy(FakeRunner):
            def run(self, job, files, label="", cancelled=None, started=None):
                self.jobs.append((job, files)); raise V.RunnerError("The VM runner is busy (2 jobs at once): try again in a few minutes.")
        self.w.runner = Busy()
        self.assertEqual(self.probe()["state"], "UNKNOWN"); self.settle()
        (row,) = self.rows()
        self.assertEqual((row["status"], row["pod"]), ("error", None))
        p = self.probe()
        self.assertEqual(p["state"], "UNKNOWN"); self.assertIn("couldn't get a VM", p["evidence"]); self.assertIn("busy", p["evidence"]); self.assertEqual(p["retry_in"], mo.CHECK_RETRY)
        self.settle(); self.assertEqual(len(self.w.runner.jobs), 1)                    # not again within NET_CHECK_EVERY
        self.later()
        self.assertEqual(self.probe()["state"], "UNKNOWN"); self.settle()
        self.assertEqual(len(self.w.runner.jobs), 2)                                   # a new one after it
        # the control: a job that did run in a VM and exited 1 is a failure (test_a_failed_check_is_the_answer_for_a_while…)

    def test_a_check_stopped_by_a_server_restart_is_not_a_failure(self):
        self.assertTrue(mo._start_vm_check(self.ch, self.comp)); self.settle()
        self.db.q("UPDATE mw_sbx SET status='error', exit_code=NULL, pod='job-9-x', error='Stopped by a server restart.', finished=?", (time.time(),))
        self.db.q("DELETE FROM mw_files WHERE path LIKE 'runs/%'")
        self.assertEqual(self.probe()["state"], "UNKNOWN")

    def test_the_periodic_pass_is_asked_to_look_again_only_for_a_bounded_time(self):
        self.assertEqual(mo.awaiting(), set())
        self.probe(); self.settle()
        self.assertEqual(mo.awaiting(), {tp.WID})                                      # a check was started for this team
        until = mo._awaiting[tp.WID][0]
        self.assertAlmostEqual(until - time.time(), mo.AWAIT_FOR, delta=5)
        for _ in range(mo.AWAIT_STARTS + 2): mo._await(tp.WID)                         # a need that keeps failing: checks keep being started
        self.assertLessEqual(mo._awaiting[tp.WID][0], time.time() + mo.AWAIT_FOR + 1)  # …but the time stops being extended
        mo._awaiting[tp.WID][0] = time.time() - 1
        self.assertEqual(mo.awaiting(), set())
        mo._await(tp.WID)
        self.assertEqual(mo.awaiting(), set())                                         # too many in the last hour: left to an event or a person

    def test_a_rebuilt_base_disk_is_unproven_again_and_checked_once(self):
        self.probe(); self.settle(); self.assertEqual(self.probe()["state"], "PASS")
        V.BASE_SHA = "f6" * 32
        self.assertEqual(self.probe()["state"], "UNKNOWN"); self.settle()
        self.assertEqual(len(self.w.runner.jobs), 1)                                   # the last check is minutes old: not yet
        self.later()
        self.assertEqual(self.probe()["state"], "UNKNOWN"); self.settle()
        self.assertEqual(len(self.w.runner.jobs), 2)

    def test_a_failed_check_is_the_answer_for_a_while_and_does_not_loop(self):
        self.w.runner = Failing()
        self.assertEqual(self.probe()["state"], "UNKNOWN"); self.settle()
        for _ in range(3):
            p = self.probe()
            self.assertEqual(p["state"], "FAIL"); self.assertIn("did not finish cleanly", p["evidence"]); self.assertIn("The VM ended without reporting", p["evidence"])
        self.settle(); self.assertEqual(len(self.w.runner.jobs), 1)
        self.later(mo.NET_FAIL_HOLD + 60)                                              # the hold is over: measured again, once
        self.assertEqual(self.probe()["state"], "UNKNOWN"); self.settle()
        self.assertEqual(len(self.w.runner.jobs), 2)

    def test_a_page_being_read_starts_nothing(self):
        p = mo.probe(self.ch, self.comp, "docker", cached_only=True)
        self.settle()
        self.assertEqual((p["state"], self.w.runner.jobs, self.rows()), ("UNKNOWN", [], []))

    def test_where_it_cant_be_started_the_answer_says_so(self):
        self.assertIn("can't be started from here", self.probe(comp=None)["evidence"])          # a task with no team
        with mock.patch.object(mo, "NET_CHECK", False): self.assertIn("can't be started from here", self.probe()["evidence"])
        self.ch.w = types.SimpleNamespace(runner=self.w.runner)                                  # no board here
        self.assertIn("can't be started from here", self.probe()["evidence"])
        self.settle(); self.assertEqual(self.w.runner.jobs, [])

    def test_the_check_job_is_never_team_work_or_evidence(self):
        self.probe(); self.settle()
        (row,) = self.rows()
        self.assertFalse(V.backed(self.db, tp.WID, f"job:{row['id']}", 0.5)); self.assertIsNone((V.stored(self.db, tp.WID, row["id"]) or {}).get("score"))
        self.assertEqual(mining_work.sbx_record(row)["kind"], "check")
        kept = [f["path"] for f in self.db.q("SELECT path FROM mw_files WHERE comp_id=? AND path LIKE 'runs/%'", (tp.WID,))]
        self.assertEqual(kept, [f"runs/sbx-{row['id']}/result.json"])                  # its own record, nothing else


if __name__ == "__main__":
    unittest.main()
