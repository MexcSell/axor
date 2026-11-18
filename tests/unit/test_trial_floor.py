"""The Owner's floor for a team's trials (Owner decision of 2026-11-13: for SN61 at least 7 runs on each side and a 10-point
margin, because one run of its scorer is noisy). The account that ends a trial sets its own policy, so without a floor the party
on trial chooses its own bar. The floor is the Owner's, per team, like the opt-in to experiments; a trial's evidence is judged by
the higher of the account's policy and the floor, and says which floor it was judged by.
"""
import json, os, sys, unittest

from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(__file__))
from app import evolution as evo  # noqa: E402
import test_mission_persistent_evidence as tp  # noqa: E402
import test_team_trials as tt  # noqa: E402  (as modules, so their own tests don't run again here)
import test_vm_runner as tv  # noqa: E402

ME = tt.ME


@tv.own_tests
class Floor(tt.TeamTrial):
    def owner(self): return self.me(tp.OWNER)
    def set(self, **kw): return self.ev.set_floor(self.owner(), tp.WID, evo.FloorIn(**kw))

    def test_only_the_owner_sets_or_reads_it_and_it_is_audited(self):
        self.refused(403, self.ev.set_floor, ME, tp.WID, evo.FloorIn(runs=7, margin=10))            # an administrator who isn't the Owner
        self.refused(403, self.ev.set_floor, tt.MEMBER, tp.WID, evo.FloorIn(runs=7, margin=10))
        self.refused(403, self.ev.floor, ME, tp.WID)
        self.refused(404, self.ev.set_floor, self.owner(), 999, evo.FloorIn(runs=7))
        self.refused(400, self.ev.set_floor, self.owner(), tp.WID, evo.FloorIn(runs=0))
        self.refused(400, self.ev.set_floor, self.owner(), tp.WID, evo.FloorIn(margin=51))
        self.assertIsNone(self.ev.floor(self.owner(), tp.WID)["floor"])
        self.assertEqual(self.set(runs=7, margin=10)["floor"], {"runs": 7, "margin": 10.0})
        self.assertEqual(self.ev.floor(self.owner(), tp.WID)["floor"], {"runs": 7, "margin": 10.0})
        a = self.db.q("SELECT actor, action, target, detail FROM audit WHERE action='trial.floor'", one=True)
        self.assertEqual((a["actor"], a["target"]), ("the-owner", f"comp:{tp.WID}")); self.assertIn('none → {"runs": 7, "margin": 10.0}', a["detail"])
        self.assertIsNone(self.set()["floor"])                                                         # cleared: back to the account's own policy

    def test_without_a_floor_three_runs_and_five_points_are_enough(self):
        pid, p = self.trial(0.60, 0.68, 3)
        self.assertEqual((p["status"], p["evidence"]["min_cases"], p["evidence"]["margin"]), ("verified", 3, 5.0)); self.assertNotIn("floor", p["evidence"])

    def test_the_floor_asks_for_more_runs(self):
        self.set(runs=7, margin=10)
        pid, p = self.trial(0.60, 0.80, 3)                                                             # 20 points better, on 3 runs a side
        e = p["evidence"]
        self.assertEqual((p["status"], e["min_cases"], e["margin"], e["floor"]), ("not_better", 7, 10.0, {"runs": 7, "margin": 10.0}))
        self.assertIn("the policy needs 7", "; ".join(e["why"]))

    def test_the_floor_asks_for_a_wider_margin(self):
        self.set(runs=7, margin=10)
        pid, p = self.trial(0.60, 0.68, 7)                                                             # enough runs, 8 points better
        self.assertEqual(p["status"], "not_better"); self.assertIn("the policy needs +10", "; ".join(p["evidence"]["why"]))

    def test_seven_runs_and_ten_points_pass_it(self):
        self.set(runs=7, margin=10)
        pid, p = self.trial(0.60, 0.75, 7)
        self.assertEqual((p["status"], p["evidence"]["cases"], p["evidence"]["delta"]), ("verified", 7, 15.0))

    def test_the_account_on_trial_cannot_lower_it(self):
        self.set(runs=7, margin=10)
        self.ev.set_policy(ME, evo.PolicyIn(mode="recommend", margin=0, min_cases=1, daily_tokens=1000))  # the team's account loosens its own policy
        pid, p = self.trial(0.60, 0.68, 3)
        self.assertEqual((p["status"], p["evidence"]["min_cases"], p["evidence"]["margin"]), ("not_better", 7, 10.0))

    def test_a_stricter_policy_of_the_accounts_own_still_counts(self):
        self.set(runs=3, margin=5)
        self.ev.set_policy(ME, evo.PolicyIn(mode="recommend", margin=30, min_cases=3, daily_tokens=1000))
        pid, p = self.trial(0.60, 0.75, 3)
        self.assertEqual((p["status"], p["evidence"]["margin"]), ("not_better", 30.0))                # the higher of the two


if __name__ == "__main__":
    unittest.main()
