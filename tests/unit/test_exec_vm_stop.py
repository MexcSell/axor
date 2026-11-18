"""The emergency stop and VM Docker jobs (mining_work._docker_job asks exec_env; runner.py is untouched): a job of a stopped
mission is recorded as not started before anything is made; a waiting or running job is ended through its own cancelled test;
without a stop the job is what it was; if the stop can't be asked, the job doesn't run."""
import os, sys, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
import test_vm_runner as tv  # noqa: E402
from app import exec_env as ex, runner as V  # noqa: E402

tp = tv.tp


class Recorder(tv.FakeRunner):
    """Runner.run's stand-in that also asks the job's cancelled test, as the real one does while it waits and while it runs."""
    def run(self, job, files, label="", cancelled=None, started=None):
        self.cancelled = cancelled
        if getattr(self, "before", None): self.before()
        if cancelled and cancelled():
            clean = {k: v for k, v in job.items() if k != "id"}
            self.jobs.append((job, files))
            return V.finish(clean, {}, "cancelled", None, "Stopped before it finished.", "", "job-1-abc", V.inputs(clean, files), 4.0, {"hosts": {}}, [], [])
        return super().run(job, files, label, cancelled, started)


class VmStop(tv.Board):
    """The board fixture of tests/unit/test_vm_runner.py; its own tests aren't run a second time here (see below the class)."""

    def tearDown(self):
        db = self.db
        super().tearDown()
        try: db.db.close()        # on Postgres every AuthDB holds a connection for as long as it lives
        except Exception: pass    # noqa: BLE001

    def fresh(self):
        self.w.runner = Recorder()
        return self.w.runner

    def row(self, sid): return self.db.q("SELECT * FROM mw_sbx WHERE id=?", (sid,), one=True)

    def test_without_a_stop_the_job_is_what_it_was(self):
        plain = self.job()                                               # the board's own runner double, as tests/unit/test_vm_runner.py runs it
        r = self.fresh(); out = self.job(run=tv.RUN)
        same = lambda d: {k: v for k, v in d.items() if k not in ("sbx", "result_file", "kept", "output")}
        self.assertEqual(same(out), same(plain)); self.assertEqual(out["status"], "done")
        self.assertEqual(len(r.jobs), 1); self.assertFalse(r.cancelled())    # the job's cancelled test is there and says no
        self.assertIsNotNone(V.stored(self.db, tp.WID, out["sbx"]))

    def test_a_new_job_of_a_stopped_mission_is_recorded_as_not_started_and_nothing_is_made(self):
        for key in (f"exec.stop:comp:{tp.WID}", "exec.stop:*"):
            self.db.q("DELETE FROM app_settings WHERE k LIKE 'exec.stop:%'"); self.db.setting(key, v="Owner: stop")
            r = self.fresh(); out = self.job()
            self.assertEqual((out["status"], r.jobs), ("cancelled", [])); self.assertIn("Runs are stopped", out["error"])
            s = self.row(out["sbx"])
            self.assertEqual((s["status"], s["pod"], s["services"]), ("cancelled", None, "vm-docker")); self.assertIsNotNone(s["finished"])
            self.assertEqual(self.db.q("SELECT COUNT(*) n FROM mw_files WHERE path LIKE ?", (f"runs/sbx-{out['sbx']}/%",), one=True)["n"], 0)
            self.assertIsNone(V.stored(self.db, tp.WID, out["sbx"]))    # never evidence
        self.db.q("DELETE FROM app_settings WHERE k LIKE 'exec.stop:%'"); self.db.setting("exec.stop:mx:another", v="x")
        r = self.fresh()
        self.assertEqual((self.job()["status"], len(r.jobs)), ("done", 1))   # the control: another mission's stop isn't this job's

    def test_a_job_that_is_waiting_or_running_is_ended_by_the_stop_and_is_never_evidence(self):
        r = self.fresh()
        r.before = lambda: self.db.setting(f"exec.stop:comp:{tp.WID}", v="stop")   # the stop arrives after the job was let in
        with mock.patch.object(ex.time, "time", lambda t=__import__("time").time: t() + 10): out = self.job()
        self.assertEqual(out["status"], "cancelled"); self.assertEqual(self.row(out["sbx"])["status"], "cancelled")
        self.assertIsNone(V.stored(self.db, tp.WID, out["sbx"]))
        self.db.q("DELETE FROM app_settings WHERE k LIKE 'exec.stop:%'")
        r2 = self.fresh(); r2.before = lambda: None
        self.assertEqual(self.job()["status"], "done")                      # the control: no stop, it runs through

    def test_if_the_stop_cant_be_asked_the_job_doesnt_run(self):
        r = self.fresh()
        with mock.patch.object(ex, "refusal", side_effect=RuntimeError("database gone")):
            out = self.job()
        self.assertEqual((out["status"], r.jobs), ("cancelled", [])); self.assertIn("couldn't check whether runs are stopped (RuntimeError)", out["error"])
        self.assertEqual(self.row(out["sbx"])["status"], "cancelled")


for _name in dir(tv.Board):   # only this file's tests: the fixture's own run in their own file
    if _name.startswith("test_") and _name not in VmStop.__dict__: setattr(VmStop, _name, None)


if __name__ == "__main__":
    unittest.main()
