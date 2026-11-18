"""Adaptive → Mission for the planner that runs most: a Competition team lead's plan (mining_work._plan, every PLAN_GAP+ under
autopilot). Before, only Mission Control's discovery and the Control Hub's Mission Intelligence read orchestrator.guidance(),
both on demand, so production showed "Adaptive → Mission: 0, broken" while teams planned all day. Now the lead's plan hears
the team's own failure classes and best models (guidance(team="comp:N")) and puts mission.guided on the ledger."""
import os, sys, time, unittest
from unittest import mock

from app import mining_work, orchestrator as orc

sys.path.insert(0, os.path.dirname(__file__))
from test_orchestrator import G5  # noqa: E402

WID, RID = 4, 31


class LLM:
    def __init__(self): self.prompts = []
    def structured(self, model, system, prompt, schema, name, on_usage=None, effort="low"):
        self.prompts.append(prompt)
        return {"summary": "Benchmark first.", "tasks": []}


def lead(db, llm):
    """A Work with just what _plan reads; _by_name raises to stop it right after the handoff (the try/except logs it)."""
    w = mining_work.Work.__new__(mining_work.Work)
    w.db = db
    w.m = mock.Mock(); w.m._campaign.return_value = {"user_id": 7, "netuid": 62}; w.m._title.return_value = "SN62"; w.m.hub.llm = llm
    w.web = mock.Mock(); w.web.lead_note.return_value = ""
    w._comp = lambda wid: {"id": wid, "campaign_id": 1, "name": "Ridges 28", "goal": "Top 10 miner", "budget": 1}
    w._context = lambda wc, c: ("Context.", None)
    w._plan_prompt = lambda wid: (5, "")
    w._team = w._rules = w._directive = w._label = lambda *a: ""
    w._recall = lambda *a: ""
    w._board = lambda wid: []
    w._span = lambda *a, **k: None
    w._end = lambda *a, **k: None
    w._event = lambda *a, **k: None
    def stop(wid): raise RuntimeError("stop here")
    w._by_name = stop
    return w


class TeamPlan(G5):
    def setUp(self):
        super().setUp()
        self.o = orc.init(self.db)
        self.db.q("CREATE TABLE mw_agents (id INTEGER PRIMARY KEY, name TEXT, title TEXT, job TEXT)")
        self.db.q("INSERT INTO mw_agents VALUES (1, 'Dora', 'Director', 'Plans the board')")
        ago = time.time() - 3600
        for team, err, n in (("comp:4", "Anthropic: 429 rate limit reached", 3), ("comp:9", "sandbox pod OOMKilled", 5)):
            for _ in range(n): self.run_row(system="teams", kind="task", status="failed", error=err, team=team, started=ago, finished=ago)
        self.o.diagnose()

    def test_guidance_for_a_team_is_its_own_failures(self):
        mine = self.o.guidance(7, "Top 10 miner", team="comp:4")
        self.assertEqual([(f["cls"], f["n"]) for f in mine["failures"]], [("rate", 3)])  # not comp:9's sandbox failures
        every = self.o.guidance(7, "Top 10 miner")
        self.assertEqual({f["cls"] for f in every["failures"]}, {"rate", "sandbox"})

    def test_the_leads_plan_hears_it_and_the_handoff_is_on_the_ledger(self):
        llm = lead(self.db, LLM())
        llm._plan(WID, 1, RID, "anthropic:m", "", False)
        prompt = llm.m.hub.llm.prompts[0]
        self.assertIn("What AXoR learned from earlier runs", prompt)
        self.assertIn("3 recent run failure(s) of class 'Rate limited'", prompt)
        ev = self.db.q("SELECT * FROM io_events WHERE kind='mission.guided'", one=True)
        self.assertEqual((ev["corr"], ev["key"], ev["ref"], ev["status"]), ("comp:4", f"mw:{RID}:guided", f"mw:{RID}", "done"))
        llm._plan(WID, 1, RID, "anthropic:m", "", False)  # the same plan run again: one event (idempotent key)
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM io_events WHERE kind='mission.guided'", one=True)["n"], 1)

    def test_nothing_learned_means_no_section_and_no_handoff(self):
        llm = lead(self.db, LLM())
        llm._plan(7, 1, RID + 1, "anthropic:m", "", False)  # comp:7 has no runs, no lessons: nothing to plan around
        self.assertNotIn("What AXoR learned", llm.m.hub.llm.prompts[0])
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM io_events WHERE kind='mission.guided'", one=True)["n"], 0)

    def test_team_plans_count_as_plans_for_the_feedback_edge(self):
        q = self.db.q
        q("CREATE TABLE mh_campaigns (id INTEGER PRIMARY KEY, user_id INTEGER)")
        q("CREATE TABLE mw_comps (id INTEGER PRIMARY KEY, campaign_id INTEGER)")
        q("CREATE TABLE mw_runs (id INTEGER PRIMARY KEY, comp_id INTEGER, kind TEXT, status TEXT, started REAL)")
        q("INSERT INTO mh_campaigns VALUES (1, 7)"); q("INSERT INTO mw_comps VALUES (4, 1)")
        q("INSERT INTO mw_runs (comp_id, kind, status, started) VALUES (4, 'plan', 'done', ?), (4, 'task', 'done', ?), (4, 'plan', 'failed', ?)",
          (time.time(),) * 3)
        self.assertEqual(self.o.plans(7, time.time() - 86400), 1)


if __name__ == "__main__":
    unittest.main()
