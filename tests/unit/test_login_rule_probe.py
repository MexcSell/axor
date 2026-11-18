"""The G5-2 sign-in probe answers what the run would meet, under the login rule production runs (Owner, 2026-11-17: every
login is shared). mission_ops._auth asks pick() for the team owner, so the probe follows the rule: a member without their own
login runs on the server's login, or on a teammate's when the server's is off."""
import os, sys, types, unittest

from app import cli_accounts, mission_ops as mo

sys.path.insert(0, os.path.dirname(__file__))
from test_cli_accounts import Base  # noqa: E402


class ProbeFollowsTheRule(Base):
    def probe(self, owner):
        mo._probe_cache.clear()
        w = types.SimpleNamespace(m=types.SimpleNamespace(_campaign=lambda cid: {"user_id": owner}),
                                  _agents=lambda wid: [{"id": 1, "active": 1}], _model=lambda c, a: "terminal:sonnet")
        ch = types.SimpleNamespace(db=self.db, w=w, _has=lambda t: True)
        return mo.probe(ch, {"id": 3, "campaign_id": 1}, "auth", fresh=True)

    def test_a_member_without_their_own_login_runs_on_the_shared_one(self):
        a = cli_accounts.pick("terminal", self.alice)
        self.assertIsNone(a.uid)                                                    # the server's login, shared
        self.assertEqual(self.probe(self.alice)["state"], "PASS")

    def test_a_member_with_their_own_login_and_an_admin_pass(self):
        self.give_claude(self.alice)
        self.assertEqual(self.probe(self.alice)["state"], "PASS")
        self.assertEqual(self.probe(self.boss)["state"], "PASS")

    def test_a_teammates_login_is_shared_when_the_servers_is_off(self):
        self.db.setting("terminal_enabled", v="0")
        self.give_claude(self.bob)
        a = cli_accounts.pick("terminal", self.alice)
        self.assertEqual((a.uid, a.borrowed), (self.bob, True))                     # bob's login, used for alice's work
        self.assertEqual(self.probe(self.alice)["state"], "PASS")

if __name__ == "__main__":
    unittest.main()
