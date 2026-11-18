"""Routing decisions kept with their runs (agent_core.route → begin), the Control Hub's Model routing panel and the journey
of a task or a mission from where it started to where it is now (control_journey.py)."""
import json, os, sys, threading, time, unittest

from fastapi import HTTPException

from app import agent_core, control_hub, control_journey
from app.missions import STAGES, ENGINES

sys.path.insert(0, os.path.dirname(__file__))
from test_control_hub import Base, FakeLLM  # noqa: E402
from test_organization import ME  # noqa: E402


class RouterLLM(FakeLLM):
    """Connected providers and models that resolve, settable per test."""
    def __init__(self, connected=("anthropic", "openai"), broken=()):
        super().__init__(); self.connected, self.broken = set(connected), set(broken)
    def configured(self, p): return p in self.connected
    def resolve(self, choice):
        if not choice or choice == "auto": return ("anthropic", "default")
        if choice in self.broken: raise RuntimeError("no login for you")
        p, _, m = choice.partition(":")
        return p, m


POOL = [{"model": "anthropic:claude-big"}, {"model": "openai:gpt-mini"}]


class Decisions(unittest.TestCase):
    def setUp(self):
        import tempfile
        from app.auth import AuthDB
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        self.core = agent_core.init(self.db)
        agent_core._waiting.clear()

    def tearDown(self):
        agent_core._local.run = None
        agent_core._core = None
        agent_core._waiting.clear()
        self.dir.cleanup()

    def dec(self, rid):
        r = self.db.q("SELECT decision FROM ac_runs WHERE id=?", (rid,), one=True)
        return json.loads(r["decision"]) if r["decision"] else None

    def test_a_routed_decision_is_kept_with_the_run_it_was_made_for(self):
        self.core.set_pool(5, POOL, "balanced")
        model, d = agent_core.route(RouterLLM(), 5, "missions", "plan")
        rid = agent_core.begin("missions", 5, "plan", ref="mx:1", model=model)
        agent_core.end("done")
        got = self.dec(rid)
        self.assertEqual(got["source"], "routed")
        self.assertEqual(got["task"], "plan")
        self.assertTrue(got["candidates"] and got["candidates"][0]["model"] == model)
        self.assertIn("Best of", got["reason"])

    def test_routed_then_run_on_another_thread_still_finds_it(self):
        self.core.set_pool(5, POOL, "balanced")
        model, _ = agent_core.route(RouterLLM(), 5, "teams", "plan")
        out = {}
        t = threading.Thread(target=lambda: out.setdefault("rid", agent_core.begin("teams", 5, "plan", ref="mw:9", model=model)))
        t.start(); t.join()
        self.assertEqual(self.dec(out["rid"])["source"], "routed")

    def test_routed_inside_an_open_run_is_written_onto_it(self):
        self.core.set_pool(5, POOL, "balanced")
        rid = agent_core.begin("teams", 5, "task", ref="mw:3")
        agent_core.route(RouterLLM(), 5, "teams", "task")
        agent_core.end("done")
        self.assertEqual(self.dec(rid)["source"], "routed")

    def test_a_decision_for_another_kind_or_model_or_a_stale_one_isnt_taken(self):
        self.core.set_pool(5, POOL, "balanced")
        model, _ = agent_core.route(RouterLLM(), 5, "missions", "plan")
        rid = agent_core.begin("missions", 5, "verify", ref="mx:1", model=model); agent_core.end("done")
        self.assertIsNone(self.dec(rid), "another kind of work")
        agent_core._waiting.clear()
        model, _ = agent_core.route(RouterLLM(), 5, "missions", "plan")
        for k in list(agent_core._waiting): agent_core._waiting[k] = (agent_core._waiting[k][0], time.time() - agent_core.PENDING - 5)
        rid = agent_core.begin("missions", 5, "plan", ref="mx:1", model=model); agent_core.end("done")
        self.assertIsNone(self.dec(rid), "too old")

    def test_picked_fallback_and_no_pool_are_told_apart(self):
        llm = RouterLLM()
        m, d = agent_core.route(llm, 5, "company", "task", choice="openai:gpt-x")
        self.assertEqual((m, d["source"]), ("openai:gpt-x", "picked"))
        m, d = agent_core.route(llm, 5, "company", "task")
        self.assertEqual((m, d["source"]), ("anthropic:default", "no_pool"))
        self.assertIn("No model pool", d["reason"])
        self.core.set_pool(5, POOL, "balanced")
        m, d = agent_core.route(RouterLLM(connected=()), 5, "company", "task")
        self.assertEqual(d["source"], "no_pool")
        self.assertIn("None of the model pool's providers", d["reason"])
        self.core.set_pool(5, [{"model": "anthropic:claude-big"}], "balanced")
        m, d = agent_core.route(RouterLLM(broken={"anthropic:claude-big"}), 5, "company", "task")
        self.assertEqual((m, d["source"], d["from"]), ("anthropic:default", "fallback", "anthropic:claude-big"))
        rid = agent_core.begin("company", 5, "task", ref="co:1", model=m); agent_core.end("done")
        self.assertEqual(self.dec(rid)["from"], "anthropic:claude-big")

    def test_routed_before_the_runs_model_was_known(self):
        self.core.set_pool(5, POOL, "balanced")
        model, _ = agent_core.route(RouterLLM(), 5, "longtask", "segment")
        rid = agent_core.begin("longtask", 5, "segment", ref="ia:1", model="auto")
        self.assertIsNone(self.dec(rid))
        agent_core.model(model); agent_core.end("done")
        self.assertEqual(self.dec(rid)["source"], "routed")

    def test_a_fixed_model_counts_as_picked(self):
        self.assertEqual(agent_core.compact_decision({"reason": "Router off for this run: one fixed model.", "candidates": []})["source"], "picked")

    def test_a_system_that_routes_itself_passes_its_decision(self):
        rid = agent_core.begin("workforce", 5, "execute", ref="wf:1", model="anthropic:claude-big",
                               decision={"task": "execute", "model": "anthropic:claude-big", "reason": "Best of 2", "candidates": [{"model": "anthropic:claude-big", "score": 0.9}]})
        agent_core.end("done")
        self.assertEqual(self.dec(rid)["source"], "routed")


class Panel(Base):
    def setUp(self):
        super().setUp()
        self.hub.llm = RouterLLM(broken={"openai:gpt-mini"})
        self.core = agent_core.init(self.db)
        agent_core._waiting.clear()

    def tearDown(self):
        agent_core._local.run = None
        agent_core._core = None
        super().tearDown()

    def test_pool_health_lanes_fallbacks_and_model_stats(self):
        uid = ME["id"]
        self.core.set_pool(uid, POOL + [{"model": "openrouter:llama-8b"}], "balanced")
        for kind, status in (("plan", "done"), ("plan", "failed"), ("verify", "done")):
            m, _ = agent_core.route(self.hub.llm, uid, "missions", kind)
            agent_core.begin("missions", uid, kind, ref="mx:1", model=m); agent_core.end(status)
        self.core.set_pool(uid, [{"model": "openai:gpt-mini"}], "balanced")  # the router's pick isn't available to this person
        m, _ = agent_core.route(self.hub.llm, uid, "teams", "task")
        agent_core.begin("teams", uid, "task", ref="mw:1", model=m); agent_core.end("done")
        self.core.set_pool(uid, POOL + [{"model": "openrouter:llama-8b"}], "balanced")
        out = control_journey.routing(self.ch, ME)
        by = {p["model"]: p for p in out["pool"]}
        self.assertTrue(by["anthropic:claude-big"]["usable"])
        self.assertEqual((by["openai:gpt-mini"]["connected"], by["openai:gpt-mini"]["usable"]), (True, False))
        self.assertIn("no login", by["openai:gpt-mini"]["why"])
        self.assertFalse(by["openrouter:llama-8b"]["connected"])
        self.assertEqual(out["usable"], 1)
        self.assertEqual(out["counts"]["fallback"], 1)
        self.assertEqual(len(out["fallbacks"]), 1)
        lanes = {(x["system"], x["kind"]): x for x in out["lanes"]}
        self.assertEqual(lanes[("missions", "plan")]["runs"], 2)
        self.assertEqual(lanes[("teams", "task")]["last"]["source"], "fallback")
        self.assertTrue(lanes[("missions", "plan")]["now"]["model"])
        self.assertEqual(by["anthropic:claude-big"]["runs"], 3)
        self.assertEqual(by["anthropic:claude-big"]["failed"], 1)
        self.assertTrue(any(p["model"] == "anthropic:default" and not p["in_pool"] for p in out["pool"]), "the default model shows as outside the pool")

    def test_nothing_recorded_yet(self):
        out = control_journey.routing(self.ch, ME)
        self.assertEqual((out["pool"], out["lanes"], out["recent"], out["usable"]), ([], [], [], 0))


class FakeMX:
    def __init__(self): self.m = {}
    def state(self, me, mid):
        if mid not in self.m or self.m[mid]["user_id"] != me["id"]: raise HTTPException(404, "There's no such mission.")
        m = self.m[mid]
        return {"mission": {**m, "doing": m.get("doing", "Working")}, "events": m.get("events", []), "requests": m.get("requests", []),
                "stages": STAGES, "engines": ENGINES}


class Journey(Base):
    def setUp(self):
        super().setUp()
        self.core = agent_core.init(self.db)
        self.ch.mx = FakeMX()

    def tearDown(self):
        agent_core._local.run = None
        agent_core._core = None
        super().tearDown()

    def handshake(self): return f"u:{next(u['id'] for u in self.o.view(ME)['units'] if u['name'] == 'Handshake')}"

    def test_an_agent_task_from_created_to_your_review(self):
        t = self.ch.add_task(ME, control_hub.TaskIn(team=self.handshake(), title="Write the launch plan", agent=self.key("Noor")))
        j = control_journey.journey(self.ch, ME, f"ctl:t{t['id']}")
        self.assertEqual([s["key"] for s in j["steps"]], ["origin", "route", "assign", "work", "review"])
        st = {s["key"]: s for s in j["steps"]}
        self.assertEqual((st["work"]["status"], st["review"]["status"]), ("done", "current"))
        self.assertEqual(j["now"]["step"], "review")
        self.assertEqual(j["now"]["waiting_on"], "you")
        self.assertEqual(len(st["work"]["runs"]), 1)
        self.assertEqual(st["work"]["runs"][0]["source"], "no_pool", "Control Hub's own run now goes through the router")
        self.ch.patch_task(ME, t["id"], control_hub.TaskPatch(status="done"))
        j = control_journey.journey(self.ch, ME, f"ctl:t{t['id']}")
        self.assertTrue(all(s["status"] == "done" for s in j["steps"]))
        self.assertEqual((j["now"]["done"], j["now"]["total"]), (5, 5))

    def test_a_board_task_waits_for_the_director(self):
        c28 = self.team("Competition 28")["id"]
        t = self.ch.add_task(ME, control_hub.TaskIn(team=c28, title="Profile the miner", agent="auto", route="board"))
        j = control_journey.journey(self.ch, ME, f"ctl:t{t['id']}")
        st = {s["key"]: s for s in j["steps"]}
        self.assertEqual(st["assign"]["status"], "waiting")
        self.assertIn("Director", st["assign"]["text"])
        self.assertEqual(st["work"]["status"], "pending")

    def test_a_mission_from_its_origin_to_the_current_stage(self):
        now = time.time()
        self.ch.mx.m[4] = {"id": 4, "user_id": ME["id"], "title": "Rank the subnets", "goal": "Rank the subnets by yield", "status": "needs_input",
                           "stage": "plan", "engine": "workforce", "child": None, "attempts": 1, "created": now - 100, "updated": now, "started": now - 90,
                           "doing": "Waiting for you: approve the plan, or decline it with a note", "spent": 0.2, "budget": 5, "outcome": None,
                           "pause_reason": None, "error": None,
                           "events": [{"id": 1, "ts": now - 80, "stage": "understand", "kind": "stage", "text": "Objective: rank"},
                                      {"id": 2, "ts": now - 50, "stage": "plan", "kind": "stage", "text": "3 task(s)"}],
                           "requests": [{"id": 1, "kind": "plan", "label": "Approve the plan", "status": "pending"}]}
        agent_core.begin("missions", ME["id"], "plan", ref="mx:4", model="anthropic:m"); agent_core.end("done")
        j = control_journey.journey(self.ch, ME, "mx:4")
        self.assertEqual([s["key"] for s in j["steps"]], ["origin", *STAGES])
        st = {s["key"]: s for s in j["steps"]}
        self.assertEqual((st["understand"]["status"], st["discover"]["status"], st["plan"]["status"], st["execute"]["status"]), ("done", "done", "waiting", "pending"))
        self.assertEqual(len(st["plan"]["runs"]), 1)
        self.assertIn("approve the plan", st["plan"]["note"])
        self.assertEqual(j["now"]["waiting_on"], "you: Approve the plan")
        self.ch.mx.m[4] |= {"status": "delivered", "stage": "learn"}
        self.assertTrue(all(s["status"] == "done" for s in control_journey.journey(self.ch, ME, "mx:4")["steps"]))
        self.ch.mx.m[4] |= {"status": "failed", "stage": "execute", "error": "No model"}
        st = {s["key"]: s for s in control_journey.journey(self.ch, ME, "mx:4")["steps"]}
        self.assertEqual((st["execute"]["status"], st["verify"]["status"]), ("failed", "skipped"))

    def test_others_work_and_bad_refs(self):
        self.ch.mx.m[9] = {"id": 9, "user_id": 99}
        with self.assertRaises(HTTPException): control_journey.journey(self.ch, ME, "mx:9")
        with self.assertRaises(HTTPException): control_journey.journey(self.ch, ME, "wf:1")
        with self.assertRaises(HTTPException): control_journey.journey(self.ch, ME, "ctl:t999")

    def test_the_list_puts_work_waiting_on_you_first(self):
        t = self.ch.add_task(ME, control_hub.TaskIn(team=self.handshake(), title="Write the launch plan", agent=self.key("Noor")))
        c28 = self.team("Competition 28")["id"]
        self.ch.add_task(ME, control_hub.TaskIn(team=c28, title="Profile the miner", agent="teams:2"))
        items = control_journey.journeys(self.ch, ME)["items"]
        self.assertEqual(items[0]["ref"], f"ctl:t{t['id']}")
        self.assertEqual(items[0]["step_status"], "current")
        self.assertEqual(len(items), 2)


if __name__ == "__main__":
    unittest.main()
