"""The emergency stop and the recursive query (mining_rlm.query asks exec_env, as mining_work._docker_job does; rlm.py is untouched):
a query of a stopped mission is recorded as not started, before a pod exists or inference is paid for; a running query ends
through its own cancelled test; without a stop the query is what it was; if the stop can't be asked, the query doesn't run."""
import os, sys, tempfile, types, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
import test_exec_env as te  # noqa: E402
from app import exec_env as ex, mining_rlm, mission_ops  # noqa: E402

RES = {"status": "done", "answer": "in run.py", "ready": True, "turns": 2, "sub_calls": 1, "cost": 0.01, "seconds": 3.0, "error": "", "tokens": 120, "pod": "p"}


class RlmStop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = db = te.board(self.tmp.name)
        db.q("INSERT INTO mw_files (comp_id, path, content) VALUES (7, 'run.py', 'print(1)')")
        db.q("INSERT INTO mw_tasks (id, comp_id, title, mission) VALUES (71, 7, 'read the code', 'mx:alpha')")
        db.q("INSERT INTO mw_tasks (id, comp_id, title, mission) VALUES (72, 7, 'another mission', 'mx:beta')")
        ins = lambda sql, args: db.q(sql + " RETURNING id", args, one=True)["id"]
        llm = types.SimpleNamespace(completer=lambda model, effort: (lambda *a, **k: None, "p:model"))
        self.work = types.SimpleNamespace(db=db, sbx=object(), _ins=ins, _label=lambda w: "team", _event=lambda *a, **k: None,
                                          m=types.SimpleNamespace(hub=types.SimpleNamespace(llm=llm)))
        self.calls = []

    def tearDown(self): te.close(self.db); self.tmp.cleanup()

    def ask(self, task=71, cancelled=lambda: False, during=None):
        def run(sbx, complete, question, files, **kw):
            self.calls.append(kw); self.seen = kw["cancelled"]
            if during: during()
            return dict(RES, status="cancelled" if kw["cancelled"]() else "done")
        with mock.patch.object(mining_rlm.rlm, "run", run), mock.patch.object(mining_rlm.rlm, "transcript", lambda *a: "trajectory"):
            return mining_rlm.query(self.work, {"id": 7}, {"netuid": 0}, {"id": 2, "name": "Devon"}, "p:model", {"question": "where is it handled"}, task=task, run=5, cancelled=cancelled)

    def rows(self): return self.db.q("SELECT * FROM mw_sbx ORDER BY id")

    def test_without_a_stop_the_query_is_what_it_was(self):
        out = self.ask()
        self.assertEqual((out["status"], out["answer"], len(self.calls)), ("done", "in run.py", 1))
        self.assertFalse(self.seen())                                     # its cancelled test is there and says no
        self.assertEqual([r["status"] for r in self.rows()], ["done"])
        own = [True]
        self.assertEqual(self.ask(cancelled=lambda: own[0])["status"], "cancelled")   # the caller's own cancel still reaches it

    def test_a_query_of_a_stopped_mission_is_recorded_as_not_started_and_nothing_runs(self):
        for key in ("exec.stop:mx:alpha", "exec.stop:*"):
            self.db.q("DELETE FROM app_settings WHERE k LIKE 'exec.stop:%'"); self.db.q("DELETE FROM mw_sbx"); self.db.setting(key, v="Owner: stop")
            with self.assertRaises(LookupError) as e: self.ask()
            self.assertIn("Runs are stopped", str(e.exception)); self.assertEqual(self.calls, [])       # no pod, no inference
            (r,) = self.rows()
            self.assertEqual((r["status"], r["pod"], r["task_id"], r["run_id"]), ("cancelled", None, 71, 5)); self.assertIn("Runs are stopped", r["error"])
            self.assertIsNotNone(r["finished"]); self.assertTrue(r["command"].startswith("rlm: "))
            self.assertTrue(mining_rlm.AT_ONCE.acquire(blocking=False)); mining_rlm.AT_ONCE.release()      # the one-at-a-time lock was never taken
        self.db.q("DELETE FROM app_settings WHERE k LIKE 'exec.stop:%'"); self.db.setting("exec.stop:mx:alpha", v="x")
        self.assertEqual(self.ask(task=72)["status"], "done")              # the control: another mission's query goes on

    def test_a_stop_during_a_query_ends_it_through_its_own_cancelled_test(self):
        with mock.patch.object(ex.time, "time", side_effect=iter(range(1000, 9000, 10)).__next__):   # the guard looks again at most every few seconds
            out = self.ask(during=lambda: self.db.setting("exec.stop:mx:alpha", v="Owner: stop"))
        self.assertEqual(out["status"], "cancelled"); self.assertTrue(self.seen())
        self.assertEqual([r["status"] for r in self.rows()], ["cancelled"])

    def test_if_the_stop_cannot_be_asked_the_query_does_not_run(self):
        with mock.patch.object(ex, "refusal", side_effect=RuntimeError("db away")):
            with self.assertRaises(LookupError) as e: self.ask()
        self.assertIn("couldn't check whether runs are stopped", str(e.exception)); self.assertEqual(self.calls, [])
        self.assertEqual([r["status"] for r in self.rows()], ["cancelled"])


class ReadinessCheckAndThePackageRule(unittest.TestCase):
    """The readiness gate's own internet check run (mission_ops.NET_CHECK_CMD) passes when ANY of its hosts answers. A planned run
    with no egress policy no longer reaches package indexes; this pins that the check still has a host that is not one."""
    def test_the_internet_check_keeps_a_host_that_is_not_a_package_index(self):
        p = ex.plan([], {"plan": 1}, True, approved=("pypi.org", "files.pythonhosted.org"))
        left = [h for h in mission_ops.NET_CHECK_HOSTS if not ex.index_related(h) and h not in p["net"]["deny"]]
        self.assertEqual(left, ["github.com"])
        self.assertIn("ok=0", mission_ops.NET_CHECK_CMD); self.assertIn("exit $ok", mission_ops.NET_CHECK_CMD)   # one success is a pass


if __name__ == "__main__": unittest.main()
