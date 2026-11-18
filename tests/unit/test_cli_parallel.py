"""cli_parallel.py: runs at once per CLI login, set in Agents → Models and applied without a restart."""
import os, tempfile, threading, time, unittest

from app import cli_parallel, llm, codex_cli
from app.auth import AuthDB


class Limits(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        self.saved = dict(cli_parallel._limits)
        cli_parallel.load(self.db)

    def tearDown(self):
        cli_parallel._limits.update(self.saved)
        cli_parallel.S["db"] = None
        self.dir.cleanup()

    def test_defaults_then_a_saved_limit_survives_a_restart(self):
        self.assertEqual(cli_parallel.limit("terminal"), cli_parallel.DEFAULT["terminal"])
        self.assertFalse(cli_parallel.saved("terminal"))
        cli_parallel.set_limit("terminal", 6)
        self.assertEqual(llm.plan_parallel("terminal"), 6)
        cli_parallel._limits["terminal"] = 2
        cli_parallel.load(self.db)
        self.assertEqual(cli_parallel.limit("terminal"), 6)
        self.assertTrue(cli_parallel.saved("terminal"))
        self.assertEqual(llm.plan_parallel("codex"), cli_parallel.DEFAULT["codex"])  # each CLI its own

    def test_out_of_range_is_refused(self):
        for bad in (0, cli_parallel.MAX + 1):
            with self.assertRaises(ValueError): cli_parallel.set_limit("codex", bad)
        with self.assertRaises(ValueError): cli_parallel.set_limit("gemini", 3)

    def test_the_server_gates_follow_the_setting(self):
        self.assertIsInstance(llm.CLI_GATE, cli_parallel.Gate)
        self.assertIsInstance(codex_cli.GATE, cli_parallel.Gate)
        self.assertEqual(llm.CLI_GATE.p, "terminal"); self.assertEqual(codex_cli.GATE.p, "codex")


class Gating(unittest.TestCase):
    def setUp(self):
        self.saved = dict(cli_parallel._limits)
        cli_parallel._limits["terminal"] = 2

    def tearDown(self):
        cli_parallel._limits.update(self.saved)

    def test_at_most_the_limit_run_at_once(self):
        g, now, peak, lock = cli_parallel.Gate("terminal"), [0], [0], threading.Lock()
        def work():
            with g:
                with lock: now[0] += 1; peak[0] = max(peak[0], now[0])
                time.sleep(.05)
                with lock: now[0] -= 1
        ts = [threading.Thread(target=work) for _ in range(6)]
        for t in ts: t.start()
        for t in ts: t.join()
        self.assertEqual(peak[0], 2)
        self.assertEqual(g.held, 0)

    def test_raising_the_limit_lets_waiting_runs_start_without_a_restart(self):
        g = cli_parallel.Gate("terminal")
        g.acquire(); g.acquire()
        got = threading.Event()
        threading.Thread(target=lambda: (g.acquire(), got.set()), daemon=True).start()
        self.assertFalse(got.wait(.3))
        cli_parallel._limits["terminal"] = 3
        self.assertTrue(got.wait(2.5))
        self.assertEqual(g.held, 3)

    def test_lowering_it_lets_runs_finish_and_holds_new_ones(self):
        g = cli_parallel.Gate("terminal")
        g.acquire(); g.acquire()
        cli_parallel._limits["terminal"] = 1
        g.release()
        self.assertFalse(g.acquire(blocking=False))  # one still running = the new limit
        g.release()
        self.assertTrue(g.acquire(timeout=.5))
        g.release()

    def test_timeouts_and_over_release(self):
        g = cli_parallel.Gate("terminal")
        g.acquire(); g.acquire()
        t = time.monotonic()
        self.assertFalse(g.acquire(timeout=.2))
        self.assertLess(time.monotonic() - t, 1.0)
        g.release(); g.release()
        with self.assertRaises(ValueError): g.release()


if __name__ == "__main__":
    unittest.main()
