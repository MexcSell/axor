"""Configurable budget alerts (agent_core._threshold): each limit warns at its own share or the owner's default, stops the work
or only alerts at the limit, and each crossing is recorded once per period and pushed once when the owner wants pushes."""
import os, tempfile, time, unittest
from unittest import mock

from app import agent_core
from app.auth import AuthDB


class Alerts(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        self.saved = (agent_core._core, agent_core._notifier, list(agent_core._resolvers))
        agent_core._resolvers.clear()
        self.core = agent_core.init(self.db)
        self.pushed = []
        agent_core.set_notifier(lambda uid, title, body, urgent: self.pushed.append((uid, title, body, urgent)))
        self.sync = mock.patch.object(agent_core.threading, "Thread", lambda target, args, **k: mock.Mock(start=lambda: target(*args)))
        self.sync.start()

    def tearDown(self):
        self.sync.stop()
        agent_core._local.run = None
        agent_core._core, agent_core._notifier = self.saved[0], self.saved[1]
        agent_core._resolvers[:] = self.saved[2]
        self.dir.cleanup()

    def spend(self, n, agent="workforce:3"):
        agent_core.begin("workforce", 7, "execute", ref="wf:1", agent_key=agent)
        agent_core.used(n)
        why = agent_core.over()
        agent_core.end("done")
        return why

    def rows(self): return [(r["ref"], r["level"]) for r in self.db.q("SELECT ref, level FROM ac_alerts ORDER BY id")]

    def test_default_warn_at_80_then_a_hard_stop_each_once(self):
        L = self.core.set_limit(7, "agent", "workforce:3", tokens=1000, period="day", label="Kenji")
        self.assertIsNone(self.spend(700)); self.assertEqual(self.rows(), [])
        self.assertIsNone(self.spend(150))                                   # 850 of 1,000: a warning, work goes on
        self.assertEqual(self.rows(), [(f"limit:{L['id']}", "warn")])
        self.assertIsNone(self.spend(10))                                    # still over 80%: not again
        self.assertIn("agent token budget", self.spend(200))                # over the limit: it stops, and says so once
        self.assertEqual(self.rows(), [(f"limit:{L['id']}", "warn"), (f"limit:{L['id']}", "limit")])
        self.assertEqual([p[3] for p in self.pushed], [False, True])         # reaching the limit is urgent (through quiet hours)
        self.assertIn("85% of its limit used", self.pushed[0][1])
        st = self.core.limit_status(7)[0]
        self.assertEqual((st["warn_at"], st["mode"], st["level"]), (80, "stop", "limit"))

    def test_a_limits_own_share_and_alert_only_mode(self):
        self.core.set_limit(7, "agent", "workforce:3", tokens=1000, period="total", warn_pct=50, mode="alert")
        self.assertIsNone(self.spend(600))
        self.assertEqual([lv for _, lv in self.rows()], ["warn"])
        self.assertIsNone(self.spend(600))                                   # 1,200 of 1,000 and it only alerts: work goes on
        self.assertEqual([lv for _, lv in self.rows()], ["warn", "limit"])
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM ac_limit_hits", one=True)["n"], 0)  # nothing refused
        self.assertIn("only alerts", self.pushed[-1][2])
        with self.assertRaises(ValueError): self.core.set_limit(7, "agent", "x", tokens=5, mode="maybe")
        with self.assertRaises(ValueError): self.core.set_limit(7, "agent", "x", tokens=5, warn_pct=0)

    def test_the_owners_default_and_push_switch(self):
        self.core.set_cap(7, 1000, "leo")
        out = self.core.set_alert_settings(7, warn_pct=50, notify=False, by="leo")
        self.assertEqual((out["warn_pct"], out["notify"]), (50, False))
        self.assertIsNone(self.spend(600))
        self.assertEqual(self.rows(), [("cap", "warn")])                      # the daily limit warns at the owner's 50%
        self.assertEqual(self.pushed, [])                                    # recorded, not pushed
        self.assertEqual(self.core.cap(7), 1000)                             # the setting kept the daily limit
        self.core.set_alert_settings(7, notify=True)
        self.assertEqual(self.core.alert_settings(7)["warn_pct"], 50)        # unchanged when not given
        self.assertIn("daily token budget", self.spend(500))
        self.assertEqual(self.rows()[-1], ("cap", "limit")); self.assertEqual(len(self.pushed), 1)

    def test_a_restart_doesnt_alert_twice_and_a_failing_push_never_stops_work(self):
        self.core.set_limit(7, "agent", "workforce:3", tokens=100, period="day")
        agent_core.set_notifier(lambda *a: (_ for _ in ()).throw(RuntimeError("push server down")))
        self.assertIn("token budget", self.spend(150))
        self.assertEqual([lv for _, lv in self.rows()], ["limit"])           # straight past the warning: only the limit
        self.core.alerted.clear()                                            # a restart: the record still holds it
        self.spend(1)
        self.assertEqual(len(self.rows()), 1)


if __name__ == "__main__":
    unittest.main()
