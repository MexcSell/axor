"""model_router.py and agent_core.route(): the shared model router every agent system's "auto" work goes through."""
import json, os, tempfile, time, types, unittest

from app import agent_core, model_router
from app.auth import AuthDB
from app.llm import LLMError

STRONG, LIGHT, FRONTIER = "openrouter:google/gemini-2.5-flash", "openrouter:meta-llama/llama-3.1-8b", "anthropic:claude-opus-5-5"


class FakeLLM:
    """configured() and resolve() as llm.Providers answers them, for the providers in `on`."""
    def __init__(self, on=("anthropic", "openrouter"), default="anthropic:claude-sonnet-5-5"):
        self.on, self.default = set(on), default

    def configured(self, p): return p in self.on

    def resolve(self, choice):
        choice = self.default if not choice or choice == "auto" else choice
        if not choice: raise LLMError("No model is available yet.")
        p, _, m = choice.partition(":")
        if p not in self.on: raise LLMError(f"{p} isn't connected.")
        return p, m


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        self.core = agent_core.init(self.db)
        self.llm = FakeLLM()

    def tearDown(self):
        agent_core._local.run = None
        agent_core._core = None
        self.dir.cleanup()

    def pool(self, *models, weights="balanced"):
        agent_core.set_pool(5, [{"model": m, "tier": None, "price": None} for m in models], weights, "test")

    def runs(self, model, kind, n, status="done", tokens=5000, secs=10, score=None, system="teams"):
        now = time.time()
        for _ in range(n):
            self.db.q("""INSERT INTO ac_runs (system, owner_id, kind, ref, status, tokens, model, score, started, finished)
                         VALUES (?,?,?,?,?,?,?,?,?,?)""", (system, 5, kind, "x", status, tokens, model, score, now - secs, now))


class Route(Base):
    def test_no_pool_runs_on_the_default_model(self):
        model, why = agent_core.route(self.llm, 5, "teams", "task")
        self.assertEqual(model, "anthropic:claude-sonnet-5-5")
        self.assertIn("No model pool", why["reason"])

    def test_a_picked_model_is_never_rerouted(self):
        self.pool(LIGHT, STRONG)
        model, why = agent_core.route(self.llm, 5, "teams", "task", choice=FRONTIER)
        self.assertEqual(model, FRONTIER)
        self.assertEqual(why["candidates"], [])

    def test_auto_goes_to_the_pool(self):
        self.pool(LIGHT, STRONG)
        model, why = agent_core.route(self.llm, 5, "teams", "task")
        self.assertIn(model, (LIGHT, STRONG))
        self.assertEqual(len(why["candidates"]), 2)

    def test_planning_and_reviewing_need_a_strong_model(self):
        self.pool(LIGHT, STRONG, weights="thrifty")
        for kind in ("plan", "review", "verify", "brief"):
            self.assertEqual(agent_core.route(self.llm, 5, "teams", kind)[0], STRONG, kind)
        self.assertEqual(len(agent_core.route(self.llm, 5, "teams", "task")[1]["candidates"]), 2, "plain work: any tier")

    def plan_waits(self, waiting):
        """cli_accounts.pick as it answers when the logins of the models in `waiting` ({model: seconds from now}) are at their limit."""
        from unittest import mock
        from app import cli_accounts
        self.picked = []
        def pick(p, who=None, model=None):
            self.picked.append((p, who, model))
            left = waiting.get(f"{p}:{model}")
            return types.SimpleNamespace(quota={"until": time.time() + left if left else 0.0})
        patch = mock.patch.object(cli_accounts, "pick", pick)
        patch.start(); self.addCleanup(patch.stop)

    def test_a_plan_waiting_for_its_limit_is_skipped_while_another_model_qualifies(self):
        # 11-17's pool shape: Claude Code tier 3 beats Codex tier 2 on the prior alone
        self.llm = FakeLLM(on=("terminal", "codex"))
        self.pool("terminal:fable", "codex:gpt-6.1-sol")
        self.plan_waits({})
        self.assertEqual(agent_core.route(self.llm, 5, "teams", "task")[0], "terminal:fable")
        self.plan_waits({"terminal:fable": 3600})
        model, why = agent_core.route(self.llm, 5, "teams", "task")
        self.assertEqual(model, "codex:gpt-6.1-sol")
        self.assertEqual([s["model"] for s in why["skipped"]], ["terminal:fable"])
        self.assertIn("waits for its usage limit", why["reason"])
        self.assertIn(("terminal", 5, "fable"), self.picked)                     # the login this owner's work would use

    def test_nothing_is_skipped_when_no_other_model_meets_the_tier_rule(self):
        self.llm = FakeLLM(on=("terminal", "codex"))
        self.pool("terminal:fable", "codex:gpt-6-luna")                           # luna is tier 1; a review needs tier 2
        self.plan_waits({"terminal:fable": 3600})
        model, why = agent_core.route(self.llm, 5, "teams", "review")
        self.assertEqual(model, "terminal:fable")                                 # as today: the run waits for the limit
        self.assertNotIn("skipped", why)
        self.assertIn("routed as before", why["reason"])
        self.assertEqual(agent_core.route(self.llm, 5, "teams", "task")[0], "codex:gpt-6-luna")  # plain work: any tier will do

    def test_a_limit_that_has_passed_or_per_token_models_are_not_skipped(self):
        self.llm = FakeLLM(on=("terminal", "anthropic"))
        self.pool("terminal:fable", FRONTIER)
        self.plan_waits({"terminal:fable": -5})                                   # reset five seconds ago
        self.assertNotIn("skipped", agent_core.route(self.llm, 5, "teams", "task")[1])
        self.plan_waits({})
        self.assertEqual([p for p in self.picked if p[0] == "anthropic"], [])     # an API model has no plan to ask about

    def test_a_missing_login_is_left_to_resolve(self):
        from unittest import mock
        from app import cli_accounts
        self.llm = FakeLLM(on=("terminal", "codex"))
        self.pool("terminal:fable", "codex:gpt-6.1-sol")
        def no_login(*a, **k): raise LLMError("Terminal isn't connected yet.")
        with mock.patch.object(cli_accounts, "pick", no_login):
            self.assertEqual(agent_core.route(self.llm, 5, "teams", "task")[0], "terminal:fable")   # not skipped, not an error

    def test_an_independent_review_avoids_the_authors_model(self):
        self.pool(STRONG, FRONTIER, weights="quality")
        self.assertEqual(agent_core.route(self.llm, 5, "missions", "verify")[0], FRONTIER)
        self.assertEqual(agent_core.route(self.llm, 5, "missions", "verify", avoid={FRONTIER})[0], STRONG)

    def test_a_disconnected_provider_is_skipped(self):
        self.pool(FRONTIER, STRONG, weights="quality")
        self.llm.on = {"openrouter"}
        model, why = agent_core.route(self.llm, 5, "teams", "task")
        self.assertEqual(model, STRONG)
        self.assertIn("skipped", why["reason"])
        self.llm.on = {"local"}
        self.llm.default = "local:llama3.1:8b"
        self.assertEqual(agent_core.route(self.llm, 5, "teams", "task")[0], "local:llama3.1:8b", "nothing in the pool is connected: the default")

    def test_it_learns_from_failures_and_scores(self):
        self.pool(STRONG, FRONTIER, weights="quality")
        self.assertEqual(agent_core.route(self.llm, 5, "teams", "task")[0], FRONTIER, "tier prior first")
        self.runs(FRONTIER, "task", 12, status="failed", score=None)
        self.runs(STRONG, "task", 12, score=95)
        model, why = agent_core.route(self.llm, 5, "teams", "task")
        self.assertEqual(model, STRONG)
        self.assertIn("scored run", why["reason"])

    def test_each_system_learns_on_its_own(self):
        self.pool(STRONG, FRONTIER, weights="quality")
        self.runs(FRONTIER, "task", 12, status="failed", system="company")
        self.assertEqual(agent_core.route(self.llm, 5, "company", "task")[0], STRONG)
        self.assertEqual(agent_core.route(self.llm, 5, "teams", "task")[0], FRONTIER, "the company's failures don't count against teams")

    def test_without_the_core_auto_is_the_default(self):
        agent_core._core = None
        self.assertEqual(agent_core.route(self.llm, 5, "teams", "task")[0], "anthropic:claude-sonnet-5-5")
        self.llm.on, self.llm.default = set(), None
        with self.assertRaises(LLMError): agent_core.route(self.llm, 5, "teams", "task")

    def test_a_broken_router_falls_back_to_the_default(self):
        self.pool(STRONG)
        self.db.q("UPDATE ac_pool SET pool='not json' WHERE owner_id=5")
        self.assertEqual(agent_core.route(self.llm, 5, "teams", "task")[0], "anthropic:claude-sonnet-5-5")


class Pool(Base):
    def test_the_workforce_pool_is_copied_once(self):
        self.db.q("CREATE TABLE wf_settings (user_id INTEGER PRIMARY KEY, settings TEXT)")
        self.db.q("INSERT INTO wf_settings VALUES (5, ?)", (json.dumps({"pool": [{"model": STRONG, "tier": 3, "price": 1.0}], "weights": "quality"}),))
        self.assertEqual(agent_core.pool(5), {"pool": [{"model": STRONG, "tier": 3, "price": 1.0}], "weights": "quality"})
        self.db.q("UPDATE wf_settings SET settings='{}' WHERE user_id=5")
        self.assertEqual(agent_core.pool(5)["weights"], "quality", "the core keeps it now")
        self.assertEqual(agent_core.pool(6), {"pool": [], "weights": "balanced"})

    def test_set_tier_and_price_win_over_the_guess(self):
        got = model_router.effective([{"model": LIGHT, "tier": 3, "price": 2.5}, {"model": "openrouter:openai/gpt-5-mini"}, {"bad": 1}])
        self.assertEqual(got[0], {"model": LIGHT, "tier": 3, "price": 2.5})
        self.assertEqual(got[1]["tier"], 1)
        self.assertEqual(len(got), 2)

    def test_guessed_tiers(self):
        for model, tier in ((STRONG, 2), ("openrouter:google/gemini-2.5-pro", 3), ("openrouter:google/gemini-2.0-flash-lite", 1),
                            (LIGHT, 1), ("openai:gpt-5", 3), ("openai:gpt-5-mini", 1), ("anthropic:claude-haiku-5-5", 1), (FRONTIER, 3)):
            self.assertEqual(model_router.guess(model)[0], tier, model)
        self.assertEqual(model_router.guess("local:llama3.1:8b")[1], 0.0)

    def test_suffixed_gpt_models_rank_by_suffix_as_openai_describes_them(self):
        # every id in Codex's model list of 2026-11-18, with the tier its description gives it
        for model, tier in (("codex:gpt-6.2-astra", 3), ("codex:gpt-6-astra", 3), ("codex:gpt-6.2-sol", 2), ("codex:gpt-6.1-sol", 2),
                            ("codex:gpt-6-sol", 2), ("codex:gpt-6.1-terra", 2), ("codex:gpt-5.6-sol", 2), ("codex:gpt-5.6-terra", 2),
                            ("codex:gpt-6-luna", 1), ("codex:gpt-5.6-luna", 1), ("openrouter:openai/gpt-6.1-terra", 2),
                            ("terminal:opus", 3), ("terminal:fable", 3), ("terminal:sonnet", 2), ("terminal:haiku", 1)):
            self.assertEqual(model_router.guess(model)[0], tier, model)
        self.assertEqual(model_router.guess("codex:gpt-6.2-astra")[1], 0.0)                   # a plan: no price
        self.assertEqual(model_router.guess("openai:gpt-6.2-astra")[1], model_router.PRICE[3])  # per token: the tier's
        got = model_router.effective([{"model": "codex:gpt-6.1-terra", "tier": 3}])
        self.assertEqual(got[0]["tier"], 3)                                                    # a tier the owner set still wins

    def test_scores_land_on_finished_runs_of_the_right_kinds(self):
        self.runs(STRONG, "plan", 1); self.runs(STRONG, "verify", 1)
        self.db.q("UPDATE ac_runs SET ref='mx:1'")
        agent_core.score("mx:1", 80, only_unscored=True, kinds=("understand", "plan"))
        got = {r["kind"]: r["score"] for r in self.db.q("SELECT kind, score FROM ac_runs")}
        self.assertEqual(got, {"plan": 80, "verify": None})
        agent_core.score("mx:1", 10, only_unscored=True, kinds=("plan",))
        self.assertEqual(self.db.q("SELECT score FROM ac_runs WHERE kind='plan'", one=True)["score"], 80, "only_unscored keeps the first")
        agent_core.score("mx:1", 500)
        self.assertEqual(self.db.q("SELECT MAX(score) s FROM ac_runs", one=True)["s"], 100, "clamped")

    def test_the_run_model_can_be_set_after_begin(self):
        rid = agent_core.begin("longtask", 5, "segment", ref="ia:1", model="auto")
        agent_core.model(STRONG)
        agent_core.end("stopped")
        self.assertEqual(self.db.q("SELECT model FROM ac_runs WHERE id=?", (rid,), one=True)["model"], STRONG)
        self.assertIn((STRONG, "segment"), self.core.stats(5, "longtask"), "a paused segment counts as finished work")


class OwnStats(Base):
    def test_a_system_can_route_on_its_own_run_table(self):
        self.pool(STRONG, FRONTIER, weights="quality")
        own = model_router.stats_rows([{"model": FRONTIER, "task": "analyst", "n": 12, "tokens": 4000, "latency": 5, "failed": 12, "scored": 0, "score_sum": 0}])
        self.assertEqual(agent_core.route(self.llm, 5, "teams", "analyst", stats=own)[0], STRONG)
        self.assertEqual(agent_core.route(self.llm, 5, "teams", "analyst")[0], FRONTIER, "the ledger knows nothing against it")


class Wiring(Base):
    """The systems' own model helpers: Auto routes, a pick stands. Built bare (object.__new__): only what _model reads."""
    def hub(self): return types.SimpleNamespace(llm=self.llm, model_of=lambda c: "anthropic:" + ("claude-sonnet-5-5" if c == "auto" else c.split(":", 1)[-1]))

    def test_project_team(self):
        from app import team
        self.pool(LIGHT, STRONG, weights="thrifty")
        t = object.__new__(team.Team); t.hub = self.hub()
        self.assertEqual(t._model({"model": "auto", "user_id": 5}, "cycle"), STRONG, "plan, check and report: tier 2+")
        self.assertEqual(t._model({"model": FRONTIER, "user_id": 5}, "task"), FRONTIER)

    def test_mining_campaign(self):
        from app import mining
        self.pool(LIGHT, STRONG)
        mn = object.__new__(mining.Mining); mn.hub, mn.db = self.hub(), self.db
        self.db.q("CREATE TABLE mh_campaigns (id INTEGER PRIMARY KEY, user_id INTEGER)")
        self.db.q("CREATE TABLE mh_runs (id INTEGER PRIMARY KEY, campaign_id INTEGER, agent TEXT, model TEXT, status TEXT, tokens INTEGER, started REAL, finished REAL)")
        c = {"user_id": 5, "settings": {"model": "auto"}}
        self.assertEqual(mn._model(c, "strategist"), STRONG)
        self.assertEqual(mn._model(c), "anthropic:claude-sonnet-5-5", "no agent: the campaign's model, as before")
        self.assertEqual(mn._model({"user_id": 5, "settings": {"model": FRONTIER}}, "analyst"), FRONTIER)

    def test_competition_team(self):
        from app import mining_work
        self.pool(LIGHT, STRONG)
        w = object.__new__(mining_work.Work)
        w.m = types.SimpleNamespace(hub=self.hub(), _model=lambda c: "anthropic:campaign-model")
        c = {"user_id": 5, "settings": {"model": "auto"}}
        self.assertEqual(w._model(c, {"model": "auto"}, "review"), STRONG)
        self.assertEqual(w._model(c, {"model": FRONTIER}, "task"), FRONTIER, "the agent's own pick")
        self.assertEqual(w._model({"user_id": 5, "settings": {"model": FRONTIER}}, {"model": "auto"}, "task"), "anthropic:campaign-model")


class Rank(unittest.TestCase):
    def test_pressure_makes_cost_count_double(self):
        pool = model_router.effective([{"model": STRONG}, {"model": FRONTIER}])
        calm, _ = model_router.rank(pool, {}, "task", "quality")
        _, tight = model_router.rank(pool, {}, "task", "quality", pressure=True)
        self.assertEqual(calm, FRONTIER)
        self.assertEqual(tight["weights"][1], model_router.WEIGHTS["quality"][1] * 2)
        self.assertIn("cost counts double", tight["reason"])


if __name__ == "__main__":
    unittest.main()
