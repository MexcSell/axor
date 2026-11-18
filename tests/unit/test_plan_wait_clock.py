"""The governor's wait times name their zone and carry the timestamp, so the page shows them in the viewer's own time.
(2026-11-18: "Codex work resumes at 07:11" was 07:11 UTC; read in CET it looked like a wait that had already ended.)"""
import os, sys, time, unittest

sys.path.insert(0, os.path.dirname(__file__))
from app import mining_autoloop  # noqa: E402
from test_mission_ref import WID  # noqa: E402
from test_router_b3 import Governor  # noqa: E402


class PlanWaitClock(Governor):
    """The B3 governor fixture; its own tests are blanked below so they run once, in test_router_b3."""

    def zone(self, ts): return time.strftime("%H:%M %Z", time.localtime(ts))

    def test_a_held_plan_names_the_zone_and_carries_the_time(self):
        at = time.time() + 1800
        self.waits = {"terminal": at}
        g, prov = self.gate()
        self.assertFalse(prov["ok"])
        self.assertEqual(prov["until"], at)
        self.assertIn(f"resumes at {self.zone(at)}.", prov["detail"])

    def test_a_cooling_team_names_the_zone_and_carries_the_time(self):
        at = time.time() + 900
        self.loop._set(WID, cool_until=at, cool_reason="Rate limited")
        g, prov = self.gate()
        self.assertFalse(prov["ok"])
        self.assertEqual(prov["until"], at)
        self.assertIn(f"resumes at {self.zone(at)}.", prov["detail"])

    def test_a_plan_the_router_works_around_carries_the_time_too(self):
        self.pool(("terminal:fable", None), ("codex:gpt-6.1-sol", None))
        at = time.time() + 3600
        self.waits = {"terminal": at}
        g, prov = self.gate()
        self.assertTrue(prov["ok"])
        self.assertEqual(prov["until"], at)
        self.assertIn(self.zone(at), prov["detail"])

    def test_checks_without_a_time_carry_none(self):
        g, _ = self.gate()
        self.assertTrue(all(c["until"] is None for c in g["checks"]))

    def test_the_helper_names_the_zone(self):
        self.assertRegex(mining_autoloop._hm(0), r"^\d{2}:\d{2} \S+$")


for _n in dir(Governor):
    if _n.startswith("test_"): setattr(PlanWaitClock, _n, None)


if __name__ == "__main__":
    unittest.main()
