"""The `ram:` readiness probe against the real AEF planner (exec_env) on the integrated tree (kept by the integration owner from b3's merge check)."""
import json, os, tempfile, types, unittest, unittest.mock
from app import exec_env, mission_ops as mo, sandbox
from app.auth import AuthDB


class RealPlanner(unittest.TestCase):
    def setUp(self):
        mo._probe_cache.clear()
        self.db = AuthDB(os.path.join(tempfile.mkdtemp(), "t.db"))
        self.ch = types.SimpleNamespace(db=self.db, w=None, _has=lambda t: False)

    def set(self, k, v):
        self.db.q("INSERT INTO app_settings (k, v) VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, json.dumps(v)))

    def state(self, gb, team=23): return mo.probe(self.ch, {"id": team}, "ram", str(gb), fresh=True)["state"]

    def real_size(self, gb, team=23):
        cfg = exec_env.settings(self.db, team)
        on = bool(cfg.get("plan") or cfg.get("workspace") or (cfg.get("egress") or {}).get("mode"))   # exec_env.begin's line
        return exec_env.plan([{"cap": "ram", "value": str(gb), "source": "declared"}], cfg, False)["size"] if on else None

    def test_passes_exactly_when_the_real_plan_gives_L(self):
        self.assertEqual(sandbox.SIZES["L"][1], "8Gi")
        cases = [None, {}, {"plan": False}, {"egress": {"hosts": ["github.com"]}}, {"plan": True}, {"workspace": True},
                 {"egress": {"mode": "allowlist", "hosts": ["github.com"]}}, {"egress": {"mode": "off"}}]
        for cfg in cases:
            if cfg is not None: self.set("exec.comp:23", cfg)
            for gb in (5, 8):
                want = "PASS" if self.real_size(gb) == "L" else "UNKNOWN"
                self.assertEqual(self.state(gb), want, (cfg, gb))
            self.assertEqual(self.state(4), "PASS", cfg); self.assertEqual(self.state(16), "FAIL", cfg)
        self.assertEqual([self.real_size(8) for _ in (1,)], ["L"])   # the last case is a planned team

    def test_another_teams_switch_and_a_mission_only_policy_dont_count(self):
        self.set("exec.comp:7", {"plan": True})
        self.set("exec.mission:23:comp:23", {"egress": {"mode": "allowlist", "hosts": ["github.com"]}})
        self.assertEqual(self.state(8), "UNKNOWN")
        self.assertEqual(self.state(8, team=7), "PASS")

    def test_the_whole_fabric_off(self):
        self.set("exec.comp:23", {"plan": True})
        with unittest.mock.patch.object(exec_env, "ENABLED", False):
            self.assertEqual(self.state(8), "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
