"""mission_engines.py: Mission OS's engine track record over the owner's earlier missions like this one, and the guard on the pick."""
import unittest

from app import mission_engines as me
from app.missions import ENGINES, _words

OK = {"direct": True, "workforce": True, "longtask": True, "mining": True}


def mission(engine, outcome, goal="Compare subnet emissions and pick the best subnet to mine", usd=1.0, mins=10):
    return {"title": "", "goal": goal, "engine": engine, "outcome": outcome, "own_usd": usd / 2, "child_usd": usd / 2,
            "started": 1000.0, "finished": 1000.0 + mins * 60}


def rec(rows, goal="Which subnet should I mine, comparing emissions?"):
    return me.record(rows, _words(goal), _words)


class Record(unittest.TestCase):
    def test_only_similar_missions_count(self):
        rows = [mission("workforce", "verified"), mission("direct", "failed", goal="Write a poem about autumn leaves falling")]
        r = rec(rows)
        self.assertEqual(r["similar"], 1)
        self.assertEqual(list(r["engines"]), ["workforce"])

    def test_scores_are_shrunk_and_unverified_are_left_out(self):
        r = rec([mission("workforce", "verified"), mission("workforce", "unverified")])["engines"]["workforce"]
        self.assertEqual((r["n"], r["verified"], r["score"]), (1, 1, 67))  # (50*2 + 100) / 3
        self.assertEqual(r["usd"], 1.0)
        self.assertEqual(r["minutes"], 10.0)

    def test_prompt_lines(self):
        self.assertEqual(me.lines(rec([]), ENGINES), "")
        txt = me.lines(rec([mission("workforce", "verified"), mission("direct", "failed")]), ENGINES)
        self.assertIn("<track_record>", txt)
        self.assertLess(txt.index("Workforce"), txt.index("AXoR directly"), "best first")


class Advise(unittest.TestCase):
    def rows(self):
        return [mission("direct", "failed") for _ in range(4)] + [mission("workforce", "verified") for _ in range(4)]

    def test_a_clearly_worse_pick_is_switched(self):
        engine, why = me.advise(rec(self.rows()), "direct", OK)
        self.assertEqual(engine, "workforce")
        self.assertIn("similar earlier missions", why)

    def test_a_good_pick_stands(self):
        self.assertEqual(me.advise(rec(self.rows()), "workforce", OK), ("workforce", None))

    def test_too_few_missions_decide_nothing(self):
        rows = [mission("direct", "failed") for _ in range(2)] + [mission("workforce", "verified") for _ in range(4)]
        self.assertEqual(me.advise(rec(rows), "direct", OK), ("direct", None))

    def test_a_small_gap_decides_nothing(self):
        rows = [mission("direct", "partial") for _ in range(4)] + [mission("workforce", "verified") for _ in range(4)]
        self.assertEqual(me.advise(rec(rows), "direct", OK), ("direct", None))  # 50 vs 83: under the gap

    def test_never_to_an_unavailable_engine_or_a_team_and_never_when_fixed(self):
        self.assertEqual(me.advise(rec(self.rows()), "direct", {**OK, "workforce": False}), ("direct", None))
        rows = [mission("direct", "failed") for _ in range(4)] + [mission("mining", "verified") for _ in range(4)]
        self.assertEqual(me.advise(rec(rows), "direct", OK), ("direct", None))
        self.assertEqual(me.advise(rec(self.rows()), "direct", OK, fixed=True), ("direct", None))
        rows = [mission("mining", "failed") for _ in range(4)] + [mission("workforce", "verified") for _ in range(4)]
        self.assertEqual(me.advise(rec(rows), "mining", OK), ("mining", None))


if __name__ == "__main__":
    unittest.main()
