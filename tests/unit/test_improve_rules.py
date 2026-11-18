"""The rules Competition teams' self-improvement rests on: the trial's margin rule (mining_improve.py), eval comparisons
(mining_lab.py) and a loadout version's score (mining_loadout.py)."""
import unittest

from app.mining_improve import trial_status
from app.mining_lab import versus
from app.mining_loadout import Loadouts


class Margin(unittest.TestCase):
    def test_better_needs_the_margin(self):
        self.assertEqual(trial_status(2, 0, True, 2), "better")
        self.assertEqual(trial_status(1, 0, True, 2), "same")

    def test_a_loss_on_held_out_tasks_is_worse_even_with_a_big_total(self):
        self.assertEqual(trial_status(5, -1, True, 2), "worse")

    def test_held_out_net_is_ignored_without_held_out_tasks(self):
        self.assertEqual(trial_status(3, -4, False, 2), "better")

    def test_fewer_in_total_is_worse(self):
        self.assertEqual(trial_status(-1, 0, False, 1), "worse")


def p(runs, passed): return {"runs": runs, "passed": passed}


class Versus(unittest.TestCase):
    def test_only_shared_tasks_count(self):
        a = {"t1": p(1, 1), "t2": p(1, 0), "t3": p(1, 1)}
        b = {"t1": p(1, 0), "t2": p(1, 1), "t4": p(1, 1)}
        self.assertEqual(versus(a, b), {"shared": 2, "a": 1, "b": 1, "gained": ["t1"], "lost": ["t2"],
                                        "same_suite": False, "only_a": 1, "only_b": 1})  # another task set: only the shared tasks compare

    def test_same_suite_needs_the_same_tasks_run_as_often(self):
        self.assertTrue(versus({"t1": p(3, 3)}, {"t1": p(3, 1)})["same_suite"])
        self.assertFalse(versus({"t1": p(3, 3)}, {"t1": p(1, 1)})["same_suite"])

    def test_solved_means_every_run_passed(self):
        self.assertEqual(versus({"t": p(3, 2)}, {"t": p(3, 3)})["lost"], ["t"])


def stats(**kw):
    s = {k: 0 for k in ("eval_up", "eval_same", "eval_down", "check_pass", "check_fail", "merged", "dropped", "sent_back",
                        "approve", "changes", "kept", "proposed", "failed")}
    s.update(kw)
    return s


class Score(unittest.TestCase):
    def test_too_little_to_compare(self):
        self.assertEqual(Loadouts._score("engineer", stats(eval_up=1), 1), (None, 2))

    def test_engineer_score_weights_the_eval_most(self):
        good, n = Loadouts._score("engineer", stats(eval_up=4, check_fail=4), 4)
        bad, _ = Loadouts._score("engineer", stats(eval_down=4, check_pass=4), 4)
        self.assertGreater(good, bad)
        self.assertEqual(n, 12)

    def test_same_score_counts_half(self):
        self.assertEqual(Loadouts._score("engineer", stats(eval_same=4), 0)[0], 50)


if __name__ == "__main__":
    unittest.main()
