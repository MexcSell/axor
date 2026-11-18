"""D-038 B3: the team governor follows the router. A plan in its usage-limit wait holds a team only when the router can't send
the team's work to another free model (a plan model of ALT_TIER or more, or such a per-token model); agents on a picked model,
and teams without a live pool, are held as before."""
import os, sys, time, types, unittest
from unittest import mock

from app import agent_core, mining_autoloop
from app.mining_autoloop import Loop

sys.path.insert(0, os.path.dirname(__file__))
from test_budget_safety import BoardFixture  # noqa: E402
from test_mission_ref import ME, WID  # noqa: E402

R = lambda plans, alt=(), other=False, routed=True: {"plans": set(plans), "alt": set(alt), "other": other, "routed": routed}


class PlanHold(unittest.TestCase):
    """plan_hold(): the decision alone."""
    def test_a_picked_plan_that_waits_holds_the_team_as_before(self):
        self.assertEqual(Loop.plan_hold([R({"terminal"}, routed=False)], {"terminal": 500.0}), ("terminal", 500.0))
        self.assertEqual(Loop.plan_hold([R({"terminal"}, routed=False)], {"terminal": 0}), (None, 0))

    def test_routed_work_goes_on_while_a_strong_model_is_free(self):
        self.assertEqual(Loop.plan_hold([R({"terminal", "codex"}, alt={"terminal", "codex"})], {"terminal": 500.0, "codex": 0}), (None, 0))
        self.assertEqual(Loop.plan_hold([R({"terminal"}, alt={"terminal"}, other=True)], {"terminal": 500.0}), (None, 0))  # an API model

    def test_routed_work_waits_when_only_a_light_model_is_free(self):
        # reviews and plans need tier 2: going on would send them to the waiting plan, and fail, every tick
        self.assertEqual(Loop.plan_hold([R({"terminal", "codex"}, alt={"terminal"})], {"terminal": 500.0, "codex": 0}), ("terminal", 500.0))

    def test_routed_work_resumes_when_its_first_plan_does(self):
        self.assertEqual(Loop.plan_hold([R({"terminal", "codex"}, alt={"terminal", "codex"})], {"terminal": 900.0, "codex": 500.0}), ("codex", 500.0))

    def test_one_picked_agent_on_a_waiting_plan_still_holds_a_mixed_team(self):
        routes = [R({"terminal", "codex"}, alt={"terminal", "codex"}), R({"terminal"}, routed=False)]
        self.assertEqual(Loop.plan_hold(routes, {"terminal": 500.0, "codex": 0}), ("terminal", 500.0))


class FakeLLM:
    def __init__(self, on): self.on = set(on)
    def configured(self, p): return p in self.on


class Governor(BoardFixture):
    """gate() and failed() on the board, with the owner's pool, the agents' models and the plans' clocks set per test."""
    def setUp(self):
        super().setUp()
        self.camp = {"id": 1, "user_id": ME["id"], "netuid": 62, "settings": {"model": "auto"}}
        self.w.m._campaign = lambda cid: self.camp
        self.w.m.hub.llm = FakeLLM(("terminal", "codex"))
        for a in self.agents: a["model"] = "auto"
        self.default = "terminal:opus"  # what the agents' default model resolves to (Terminal before Codex)
        self.w._model = lambda c, a, *k: a["model"] if a.get("model") not in (None, "auto") else self.default
        self.waits = {}
        p = mock.patch.object(mining_autoloop, "quota_until", lambda pp, owner=None: self.waits.get(pp, 0.0))
        p.start(); self.addCleanup(p.stop)

    def pool(self, *entries):
        agent_core.set_pool(ME["id"], [{"model": m, "tier": t, "price": None} for m, t in entries], "balanced", "test")

    def gate(self):
        g = self.loop.gate(WID)
        return g, {c["key"]: c for c in g["checks"]}["provider"]

    def test_claude_at_its_limit_with_codex_in_the_pool_the_team_goes_on(self):
        self.pool(("terminal:fable", None), ("codex:gpt-6.1-sol", None))
        self.waits = {"terminal": time.time() + 3600}
        g, prov = self.gate()
        self.assertTrue(g["tasks"]); self.assertTrue(g["reviews"])
        self.assertTrue(prov["ok"]); self.assertIn("router sends work", prov["detail"])
        self.assertEqual(g["plan_providers"], ["terminal", "codex"])

    def test_without_a_pool_the_default_models_plan_holds_the_team_as_before(self):
        self.waits = {"terminal": time.time() + 3600}
        g, prov = self.gate()
        self.assertFalse(g["tasks"]); self.assertFalse(prov["ok"])
        self.assertEqual(g["plan_providers"], ["terminal"])

    def test_a_pool_whose_free_models_are_light_still_holds(self):
        self.pool(("terminal:fable", None), ("codex:gpt-6-luna", None))  # luna is tier 1
        self.waits = {"terminal": time.time() + 3600}
        self.assertFalse(self.gate()[0]["tasks"])

    def test_every_plan_at_its_limit_holds_until_the_first_reset(self):
        self.pool(("terminal:fable", None), ("codex:gpt-6.1-sol", None))
        soon = time.time() + 600
        self.waits = {"terminal": time.time() + 3600, "codex": soon}
        g, prov = self.gate()
        self.assertFalse(g["tasks"])
        self.assertIn(time.strftime("%H:%M", time.localtime(soon)), prov["detail"])

    def test_slots_follow_the_free_plan(self):
        self.pool(("terminal:fable", None), ("codex:gpt-6.1-sol", None))
        self.db.q("UPDATE mw_comps SET parallel=10 WHERE id=?", (WID,))
        self.waits = {"terminal": time.time() + 3600}
        with mock.patch.object(mining_autoloop, "plan_parallel", lambda pp: {"terminal": 2, "codex": 5}[pp]):
            self.assertEqual(self.gate()[0]["slots"], 5)
            self.waits = {}
            self.assertEqual(self.gate()[0]["slots"], 2)                                   # both free: the smaller, as before

    def working(self):
        tid = self.queued("Build the thing")
        rid = self.db.q("INSERT INTO mw_runs (comp_id, task_id, agent_id, kind, status, started) VALUES (?,?,?,'task','failed',?) RETURNING id",
                        (WID, tid, 2, time.time()), one=True)["id"]
        self.db.q("UPDATE mw_tasks SET status='working', run_id=? WHERE id=?", (rid, tid))
        return tid, rid

    QUOTA = "Claude Code plan rate limit reached; runs resume after the reset at 15:00. You've hit your session limit"

    def test_a_routed_task_that_hits_the_limit_requeues_and_the_team_goes_on(self):
        self.pool(("terminal:fable", None), ("codex:gpt-6.1-sol", None))
        tid, rid = self.working()
        self.waits = {"terminal": time.time() + 3600}                                       # the CLI's error set the clock
        self.assertTrue(self.loop.failed(tid, rid, self.QUOTA, ""))
        self.assertEqual(self.row(tid)["status"], "queued")
        self.assertFalse(self.loop._state(WID)["cool_until"])                              # no team-wide wait
        self.assertTrue(self.loop.gate(WID)["tasks"])

    def test_a_picked_agent_that_hits_the_limit_cools_the_team_as_before(self):
        self.pool(("terminal:fable", None), ("codex:gpt-6.1-sol", None))
        self.agents[1]["model"] = "terminal:fable"
        tid, rid = self.working()
        self.waits = {"terminal": time.time() + 3600}
        self.assertTrue(self.loop.failed(tid, rid, self.QUOTA, ""))
        self.assertEqual(self.row(tid)["status"], "queued")
        self.assertGreater(self.loop._state(WID)["cool_until"], time.time())

    def test_a_limit_the_owners_clock_does_not_show_cools_the_team_as_before(self):
        # e.g. a named login's own clock: the router wouldn't skip that model, so going on would repeat the failure
        self.pool(("terminal:fable", None), ("codex:gpt-6.1-sol", None))
        tid, rid = self.working()
        self.assertTrue(self.loop.failed(tid, rid, self.QUOTA, ""))
        self.assertGreater(self.loop._state(WID)["cool_until"], time.time())


if __name__ == "__main__":
    unittest.main()
