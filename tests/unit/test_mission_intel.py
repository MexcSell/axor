"""mission_intel.py: the Intelligence Analyst's research in a mission's DISCOVER stage, before the plan. A scripted model and a
stub hub: the brief is filed, normalized and charged; lookups are capped; no web search is said from code; research that can't
be afforded or fails is skipped without holding the mission up; a cancel during research keeps the stage; the planner and the
engine get the brief."""
import json, os, tempfile, time, unittest

from app import mission_intel, missions
from app.auth import AuthDB

ME = {"id": 7, "username": "leo", "role": "admin"}
U = {"title": "Pick a subnet to mine", "objective": "Recommend one subnet to mine with an RTX 4090.", "targets": ["One pick"],
     "criteria": ["Names three options", "Recommends one"], "questions": [], "engine": "direct", "engine_why": "Small.",
     "mining_team": 0, "mining_target": {"netuid": 0, "competition": 0}, "gated_actions": [], "complexity": "small", "hours": 0.2, "success": 80}
BRIEF = {"summary": "SN64 pays GPU miners most; competition is heavy at the top.",
         "facts": [{"claim": "SN64 has the highest daily emissions among GPU subnets", "source": "market_overview", "as_of": "live", "confidence": "high"}],
         "latest": [{"item": "SN64 changed its scoring last week", "source": "https://example.org/sn64", "date": "2026-10-29"}],
         "competitors": [{"name": "UID 12", "position": "rank 1", "edge": "Low latency", "opening": "High cost"}],
         "unknowns": ["Registration cost next week"]}


def call(name, inp, i): return [{"type": "tool_use", "id": f"t{i}", "name": name, "input": inp}], "tool_use", 1000


class LLM:
    """A scripted completer: the lookups in `plan`, then file_brief (or nothing, with file=False)."""
    def __init__(self, plan, file=True, fail=None):
        self.plan, self.file, self.fail, self.seen = plan, file, fail, []
    def completer(self, model, effort="medium"):
        if self.fail: raise self.fail
        step = [0]
        def complete(system, tools, messages):
            self.seen.append([t["name"] for t in tools])
            i = step[0]; step[0] += 1
            if i < len(self.plan): return call(*self.plan[i], i)
            if self.file and i == len(self.plan): return call("file_brief", BRIEF, i)
            return [{"type": "text", "text": "Done."}], "end_turn", 500
        return complete, "fake:model"


class Hub:
    def __init__(self, llm):
        self.llm, self.knowledge, self.calls, self.usage = llm, None, [], []
    def run_tool(self, name, args): self.calls.append((name, args)); return {"name": name, "ok": True}
    def my_subnets(self, me): self.calls.append(("my_subnets", {})); return {"subnets": []}
    def source_tool(self, name, args): raise ValueError("The Source hub isn't connected.")
    def log_usage(self, me, source, tokens, agent_id=None, model=None): self.usage.append(tokens)


class Ext:
    def __init__(self, tools): self.tools = tools
    def __call__(self, name, args): return {"result": "a page"}


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        self.ext = mission_intel.mcp_hub
        mission_intel.mcp_hub = None

    def tearDown(self):
        mission_intel.mcp_hub = self.ext
        self.dir.cleanup()

    def make(self, llm, budget=5.0, u=None):
        self.hub = Hub(llm)
        self.mx = missions.Missions(self.db, hub=self.hub, wf=None, ia=None, mw=None)
        self.mx._model = lambda uid, avoid=None, stage=None: ("fake:model", 1.0)  # $1 per million tokens
        now = time.time()
        mid = self.db.q("""INSERT INTO mx_missions (user_id, title, goal, budget, constraints, status, stage, engine, understanding, created, updated)
                           VALUES (?,?,?,?,?,'running','discover','direct',?,?,?) RETURNING id""",
                        (ME["id"], "Pick a subnet", "Which subnet should I mine with one RTX 4090?", budget, "", json.dumps(u or U), now, now), one=True)["id"]
        return mid

    def events(self, mid): return [e["text"] for e in self.db.q("SELECT text FROM mx_events WHERE mission_id=? ORDER BY id", (mid,))]


class Research(Base):
    def test_files_a_sourced_brief_and_charges_it(self):
        mid = self.make(LLM([("market_overview", {}), ("get_subnet", {"netuid": 64})]))
        self.assertTrue(self.mx._discover(self.mx._m(mid)))
        m = self.mx._m(mid)
        b = m["discovery"]["brief"]
        self.assertEqual(b["facts"][0]["source"], "market_overview")
        self.assertEqual(b["competitors"][0]["name"], "UID 12")
        self.assertEqual(b["lookups"], 2)
        self.assertEqual(b["tools"], ["get_subnet", "market_overview"])
        self.assertFalse(b["web"])
        self.assertIn(mission_intel.NO_WEB, b["unknowns"])            # said from code, whatever the model filed
        self.assertEqual([c[0] for c in self.hub.calls], ["market_overview", "get_subnet"])
        self.assertEqual(m["own_tokens"], 3500)                       # three tool steps of 1,000 and the closing 500
        self.assertAlmostEqual(m["own_usd"], 0.0035)
        self.assertEqual(self.hub.usage, [3500])
        ev = self.events(mid)
        self.assertTrue(any(t.startswith("Intelligence brief: 1 fact(s), 1 competitor(s)") for t in ev))
        self.assertTrue(any("web search off" in t for t in ev))
        # the analyst's tools: AXoR's data, the Source hub, the filing tool; no devops
        tools = self.hub.llm.seen[0]
        self.assertIn("market_overview", tools)
        self.assertIn("file_brief", tools)
        self.assertNotIn("devops_run", tools)

    def test_lookups_are_capped(self):
        plan = [("get_subnet", {"netuid": n}) for n in range(1, 8)]  # 7 asked, small mission: 4 allowed
        mid = self.make(LLM(plan))
        self.mx._discover(self.mx._m(mid))
        self.assertEqual(len(self.hub.calls), mission_intel.LOOKUPS["small"])
        self.assertEqual(self.mx._m(mid)["discovery"]["brief"]["lookups"], 4)

    def test_repeated_lookup_reuses_the_answer(self):
        mid = self.make(LLM([("get_subnet", {"netuid": 64}), ("get_subnet", {"netuid": 64})]))
        self.mx._discover(self.mx._m(mid))
        self.assertEqual(len(self.hub.calls), 1)

    def test_a_tool_error_costs_a_lookup_not_the_research(self):
        mid = self.make(LLM([("source_overview", {}), ("market_overview", {})]))
        self.mx._discover(self.mx._m(mid))
        b = self.mx._m(mid)["discovery"]["brief"]
        self.assertEqual(b["lookups"], 2)
        self.assertNotIn("skipped", b)

    def test_web_search_through_mission_mcp_tools(self):
        seen = []
        class Mcp:
            @staticmethod
            def attach(scopes, me):
                seen.append(scopes)
                return Ext([{"name": "ext_exa__web_search_exa", "description": "Search the web", "input_schema": {"type": "object", "properties": {}}}])
        mission_intel.mcp_hub = Mcp
        mid = self.make(LLM([("ext_exa__web_search_exa", {"query": "SN64 scoring"})]))
        self.mx._discover(self.mx._m(mid))
        b = self.mx._m(mid)["discovery"]["brief"]
        self.assertEqual(seen, [[f"missions:{ME['id']}"]])
        self.assertTrue(b["web"])
        self.assertNotIn(mission_intel.NO_WEB, b["unknowns"])
        self.assertEqual(b["tools"], ["ext_exa__web_search_exa"])

    def test_no_filing_keeps_the_prose(self):
        mid = self.make(LLM([("market_overview", {})], file=False))
        self.mx._discover(self.mx._m(mid))
        b = self.mx._m(mid)["discovery"]["brief"]
        self.assertEqual(b["summary"], "Done.")
        self.assertIn("The analyst didn't file a structured brief.", b["unknowns"])


class BestEffort(Base):
    def test_small_budget_skips_and_goes_on(self):
        mid = self.make(LLM([("market_overview", {})]), budget=0.1)  # 40k tokens = $0.04 > a quarter of $0.10
        self.assertTrue(self.mx._discover(self.mx._m(mid)))
        b = self.mx._m(mid)["discovery"]["brief"]
        self.assertIn("too small for research", b["skipped"])
        self.assertEqual(self.hub.calls, [])
        self.assertTrue(any("too small for research" in t for t in self.events(mid)))

    def test_model_failure_skips_and_goes_on(self):
        mid = self.make(LLM([], fail=RuntimeError("provider down")))
        self.assertTrue(self.mx._discover(self.mx._m(mid)))
        self.assertIn("Research failed", self.mx._m(mid)["discovery"]["brief"]["skipped"])

    def test_cancel_during_research_keeps_the_stage(self):
        mid = self.make(LLM([("market_overview", {}), ("get_subnet", {"netuid": 1})]))
        orig = self.hub.run_tool
        def cancel_then_run(name, args):
            self.db.q("UPDATE mx_missions SET status='cancelled' WHERE id=?", (mid,))
            return orig(name, args)
        self.hub.run_tool = cancel_then_run
        self.assertFalse(self.mx._discover(self.mx._m(mid)))
        m = self.mx._m(mid)
        self.assertIsNone(m["discovery"])                             # nothing stored: a resume researches again
        self.assertEqual(len(self.hub.calls), 1)
        self.assertEqual(m["own_tokens"], 1000)                       # what it spent before the cancel is still charged

    def test_disabled_or_no_hub(self):
        mid = self.make(LLM([]))
        self.mx.hub = None
        self.assertTrue(self.mx._discover(self.mx._m(mid)))
        self.assertNotIn("brief", self.mx._m(mid)["discovery"])


class Downstream(unittest.TestCase):
    def brief(self): return mission_intel.normalize(BRIEF, web=False, lookups=2, tools=["market_overview"], model="fake:model")

    def test_plan_block(self):
        t = mission_intel.plan_block(self.brief())
        self.assertIn("fact: SN64 has the highest daily emissions", t)
        self.assertIn("competitor: UID 12: rank 1; edge: Low latency; opening: High cost", t)
        self.assertIn("unknown: Registration cost next week", t)
        self.assertEqual(mission_intel.plan_block({"skipped": "x"}), "")

    def test_digest_fits_and_drops_the_web_note(self):
        d = mission_intel.digest(self.brief(), 600)
        self.assertLessEqual(len(d), 600)
        self.assertIn("[market_overview]", d)
        self.assertNotIn("No web search", d)
        self.assertEqual(mission_intel.digest(None, 600), "")
        long = mission_intel.normalize({**BRIEF, "facts": [{"claim": "x" * 200, "source": "s", "as_of": "", "confidence": "low"}] * 12})
        self.assertLessEqual(len(mission_intel.digest(long, 600)), 600)

    def test_workforce_goal_carries_the_digest_within_its_limit(self):
        got = {}
        class WF:
            def create(self, me, b): got["goal"] = b.goal; return 99
        with tempfile.TemporaryDirectory() as d:
            db = AuthDB(os.path.join(d, "a.db"))
            mx = missions.Missions(db, hub=None, wf=WF(), ia=None, mw=None)
            now = time.time()
            disc = {"brief": self.brief()}
            plan = {"brief": "P" * 3800, "tasks": []}
            mid = db.q("""INSERT INTO mx_missions (user_id, title, goal, budget, status, stage, engine, understanding, discovery, plan, allocation, created, updated)
                          VALUES (?,?,?,?,'running','execute','workforce',?,?,?,?,?,?) RETURNING id""",
                       (ME["id"], "t", "g" * 20, 5.0, json.dumps(U), json.dumps(disc), json.dumps(plan),
                        json.dumps({"child_budget": 200000}), now, now), one=True)["id"]
            self.assertEqual(mx._launch(mx._m(mid)), "running")
        self.assertLessEqual(len(got["goal"]), 2000)
        self.assertIn("Intelligence brief", got["goal"])
        self.assertTrue(got["goal"].rstrip().endswith("list such steps for the user instead."))


if __name__ == "__main__":
    unittest.main()
