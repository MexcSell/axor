"""mission_ops.py and the P0 fixes of the 11-11 assessment ("AXoR G5: Self-Evolving Agent Ecosystem").

One task state for every engine (done is not verified), work progress apart from objective progress (an unverified criterion
counts 0, an unreadable rank is UNKNOWN), the decision engine's situations and recoveries, every finished run in one outcome,
the team budget reconciled and enforced at the gateway (runs in flight count, a run over the budget stops before its next
model call, CLI turns counted like API calls), monthly limits, failed attempts settling the experiences they recalled, failed
work as recallable experience, and no Postgres-reserved bare alias in the backend's SQL."""
import glob, json, os, re, sys, time, unittest

from fastapi import HTTPException

from app import agent_core, control_hub, experience, llm, mining_work, mission_ops as mo, orchestrator

sys.path.insert(0, os.path.dirname(__file__))
from test_control_hub import Base  # noqa: E402
from test_organization import ME  # noqa: E402

NOW = time.time()


class States(unittest.TestCase):
    def test_done_is_not_verified(self):
        self.assertEqual(mo.state_board({"status": "done"}, verified=False), "COMPLETED")  # D-018: closed without a verdict, not waiting for one
        self.assertEqual(mo.state_board({"status": "done"}, verified=True), "VERIFIED")
        self.assertEqual(mo.state_ctl("COMPLETED", False), "REVIEW")
        self.assertEqual(mo.state_ctl("COMPLETED", True), "VERIFIED")
        self.assertEqual(mo.state_mission("delivered", "unverified"), "REVIEW")
        self.assertEqual(mo.state_mission("delivered", "verified"), "VERIFIED")

    def test_every_engine_maps_onto_the_nine_states(self):
        b = mo.state_board
        self.assertEqual([b({"status": "todo"}), b({"status": "todo", "agent_id": 3}), b({"status": "queued"}), b({"status": "working"}), b({"status": "checking"}),
                          b({"status": "blocked"}), b({"status": "todo", "hold": "failed"}), b({"status": "todo"}, paused=True)],
                         ["PLANNED", "READY", "READY", "RUNNING", "REVIEW", "BLOCKED", "FAILED", "PAUSED"])
        self.assertEqual([mo.state_ctl(s, False) for s in ("CREATED", "QUEUED", "CLAIMED", "RUNNING", "SUBMITTED", "TIMEOUT", "BLOCKED", "CANCELLED")],
                         ["PLANNED", "READY", "READY", "RUNNING", "REVIEW", "FAILED", "BLOCKED", "CANCELLED"])
        self.assertEqual([mo.state_mission(s) for s in ("queued", "running", "needs_input", "paused", "failed", "cancelled")],
                         ["READY", "RUNNING", "BLOCKED", "PAUSED", "FAILED", "CANCELLED"])
        for s in ("VERIFIED", "REVIEW", "FAILED"): self.assertIn(s, mo.STATES)

    def test_work_progress_counts_verified_apart_from_completed(self):
        w = mo.work_progress(["VERIFIED"] * 45 + ["REVIEW"] * 25 + ["RUNNING"] * 10 + ["PLANNED"] * 20 + ["CANCELLED"] * 5)
        self.assertEqual((w["planned"], w["delivered"], w["review"], w["completed"], w["verified"], w["pct"], w["pct_active"]), (100, 70, 25, 0, 45, 43, 45))  # headline over the original 105


class Objective(unittest.TestCase):
    def test_an_unverified_criterion_counts_as_not_achieved(self):
        c = [mo._crit("a", "A", 30, 1, True), mo._crit("b", "B", 50, 1, False), mo._crit("c", "C", 20, 0.5, True)]
        p = mo.objective_progress(c)
        self.assertEqual(p["pct"], 40)  # (30·1 + 50·0 + 20·0.5) / 100
        self.assertEqual((p["verified"], p["unverified"]), (1, 1))

    def test_a_criterion_switched_off_leaves_the_formula(self):
        c = [mo._crit("a", "A", 30, 1, True), dict(mo._crit("b", "B", 70, 0, True), off=True)]
        self.assertEqual(mo.objective_progress(c)["pct"], 100)


class Decide(unittest.TestCase):
    def test_a_paused_team_over_budget_says_what_to_resolve(self):
        d = mo.decide({"paused": True, "pause_reason": "The team is paused; its 24-hour budget is spent", "pause_next": "Resolve the budget discrepancy"})
        self.assertEqual((d["situation"], d["owner"]), ("paused", "you"))
        self.assertIn("budget", d["next"])

    def test_failure_classes_get_different_recoveries(self):
        quota = mo.decide({"failing": "3 tasks failed", "fail_class": "quota"})
        sbx = mo.decide({"failing": "3 tasks failed", "fail_class": "sandbox"})
        task = mo.decide({"failing": "1 task failed", "fail_class": "task"})
        self.assertEqual([quota["situation"], sbx["situation"], task["situation"]], ["provider", "environment", "task_failure"])
        self.assertIn("pointless", quota["next"])
        self.assertIn("not the agent's instructions", sbx["next"])
        self.assertEqual(len({quota["next"], sbx["next"], task["next"]}), 3)

    def test_an_unknown_rank_is_uncertainty_with_what_is_needed(self):
        d = mo.decide({"open": 3, "unknown": "The official rank is UNKNOWN: no ranked miner", "first_unmet": {"label": "Miner registered", "needs": "Register the miner", "owner": "you"}})
        self.assertEqual((d["situation"], d["next"], d["owner"]), ("uncertain", "Register the miner", "you"))

    def test_met_freezes_and_monitors_and_repeats_stop(self):
        self.assertEqual(mo.decide({"met": True})["situation"], "successful")
        self.assertEqual(mo.decide({"repeated": "4 tasks gave up", "failing": "x", "fail_class": "task"})["situation"], "repeated")
        self.assertEqual(mo.decide({"open": 4, "moving": False, "stalled": "4 open, none running"})["situation"], "no_progress")


class Console(Base):
    def setUp(self):
        super().setUp()
        agent_core.init(self.db)
        mo.ensure_schema(self.db)
        mo._cache.clear()
        self.ch.edit_fixed(ME, 1, control_hub.FixedPatch(target_rank=10))

    def tearDown(self):
        agent_core._core = None
        mo._cache.clear()
        super().tearDown()

    def view(self): return mo.view(self.ch, ME, fresh=True)
    def comp(self, v, cid=1): return next(c for c in v["competitions"] if c["comp_id"] == cid)

    def test_every_competition_has_an_objective_a_status_and_a_next_action(self):
        v = self.view()
        self.assertEqual(len(v["competitions"]), 3)
        for c in v["competitions"]:
            self.assertTrue(c["objective"]); self.assertTrue(c["decision"]["next"]); self.assertIn(c["health"], ("blocked", "unmeasurable", "met", "on_track", "paused"))
        self.assertEqual(self.comp(v)["objective"], "Reach and hold top 10")
        self.assertNotIn("_tasks", {k for k in v if not k.startswith("_")})

    def test_a_ranked_miner_is_measured_and_an_unranked_one_is_unknown_not_zero(self):
        c = self.comp(self.view())
        rk = next(x for x in c["criteria"] if x["key"] == "rank")
        self.assertTrue(rk["verified"]); self.assertLess(rk["value"], 1)  # rank 14, target 10
        self.assertTrue(c["objective_progress"]["official"]["measurable"])
        other = self.comp(self.view(), 4)  # SN19: no brief, so no rank
        o = other["objective_progress"]["official"]
        self.assertEqual((o["measurable"], o["text"]), (False, "UNKNOWN"))
        self.assertTrue(o["needs"]); self.assertEqual(other["health"], "unmeasurable")
        self.assertEqual(other["decision"]["situation"], "uncertain")

    def test_objective_progress_is_apart_from_work_progress(self):
        q = self.db.q
        for i in range(4): q("INSERT INTO mw_tasks (comp_id, title, status, agent_id, done_at, updated) VALUES (1, ?, 'done', 1, ?, ?)", (f"t{i}", NOW, NOW))
        c = self.comp(self.view())
        self.assertEqual((c["work"]["completed"], c["work"]["verified"]), (4, 0))  # done, no independent verdict on record: Completed (D-018)
        self.assertEqual(c["work"]["states"]["COMPLETED"], 4)
        self.assertIsNotNone(c["objective_progress"]["pct"])  # from criteria, whatever the tasks say
        q("CREATE TABLE mw_events (id INTEGER PRIMARY KEY, comp_id INTEGER, ts REAL, agent_id INTEGER, task_id INTEGER, kind TEXT, text TEXT)")
        q("INSERT INTO mw_events (comp_id, task_id, kind) SELECT 1, id, 'approve' FROM mw_tasks WHERE comp_id=1 AND title IN ('t0','t1')")
        c = self.comp(self.view())
        self.assertEqual((c["work"]["delivered"], c["work"]["completed"], c["work"]["verified"]), (4, 2, 2))  # 2 verified, 2 still closed without a verdict

    def test_a_criterion_of_yours_counts_only_with_evidence(self):
        with self.assertRaises(HTTPException): mo.set_criterion(self.ch, ME, "comp:1", mo.CriterionIn(label="Docker image frozen", value=1))
        with self.assertRaises(HTTPException): mo.set_criterion(self.ch, ME, "comp:1", mo.CriterionIn(key="rank", value=1, evidence="trust me"))
        before = self.comp(self.view())["objective_progress"]["pct"]
        mo.set_criterion(self.ch, ME, "comp:1", mo.CriterionIn(key="image", label="Docker image frozen", weight=20))
        c = self.comp(self.view())
        mine = next(x for x in c["criteria"] if x["key"] == "image")
        self.assertFalse(mine["verified"]); self.assertLess(c["objective_progress"]["pct"], before or 101)
        d = mo.set_criterion(self.ch, ME, "comp:1", mo.CriterionIn(key="image", value=1, evidence="sha256:abc frozen 11-11"))
        mine = next(x for x in d["mission"]["criteria"] if x["key"] == "image")
        self.assertTrue(mine["verified"])
        mo.set_criterion(self.ch, ME, "comp:1", mo.CriterionIn(key="rank", weight=50))
        self.assertEqual(next(x for x in self.comp(self.view())["criteria"] if x["key"] == "rank")["weight"], 50)

    def test_a_spent_budget_is_a_decision_for_you_with_the_reconciliation(self):
        self.ch.w.day_tokens = lambda wid: 900_000 if wid == 1 else 1000
        v = self.view()
        c = self.comp(v)
        self.assertEqual((c["decision"]["situation"], c["decision"]["owner"]), ("budget", "you"))
        self.assertTrue(any(x["kind"] == "budget" and x["ref"] == "comp:1" for x in v["queue"]))
        self.assertEqual(v["queue"][0]["level"], "stop")

    def test_the_mission_page_has_five_dimensions_the_sequence_and_the_portfolio(self):
        d = mo.mission(self.ch, ME, "comp:1")
        self.assertEqual([p["key"] for p in d["performance"]], ["competition", "technical", "execution", "economic", "strategic"])
        self.assertFalse(d["performance"][1]["measured"])  # no frozen candidate benchmarked: technical quality isn't claimed
        self.assertEqual([s["n"] for s in d["sequence"]], list(range(1, len(d["sequence"]) + 1)))
        self.assertEqual([x["key"] for x in d["portfolio"]["lanes"]], ["baseline", "optimization", "competitor", "red", "evaluation"])
        self.assertIn("Rex", [a["name"] for a in next(x for x in d["portfolio"]["lanes"] if x["key"] == "competitor")["agents"]])  # a Researcher
        self.assertTrue(any("Nobody covers" in a for a in d["portfolio"]["advice"]))

    def test_readiness_is_twelve_rows_from_records(self):
        r = self.view()["readiness"]
        self.assertEqual(len(r["rows"]), 13)  # the twelve G5 rows and login attribution (D-019)
        self.assertEqual({x["state"] for x in r["rows"]} - {"pass", "partial", "fail", "unknown"}, set())
        for x in r["rows"]:  # D-020: a row passes only on records of operation; built-only rows never pass
            self.assertIn(x["level"], mo.LEVELS)
            if x["state"] == "pass": self.assertIn(x["level"], ("operational", "demonstrated"), x["key"])
            if x["level"] == "implemented": self.assertNotEqual(x["state"], "pass", x["key"])
        self.assertEqual(sum(r["levels"].values()), 13)
        self.assertEqual(next(x for x in r["rows"] if x["key"] == "evolution")["state"], "unknown")  # nothing promoted: not demonstrated
        self.assertNotEqual(r["verdict"], "Operational")

    def test_the_task_graph_is_the_tasks_own_neighbourhood(self):
        self.db.q("INSERT INTO mw_tasks (id, comp_id, title, status, agent_id, updated) VALUES (90, 1, 'Build the scorer', 'done', 2, ?)", (NOW,))
        g = mo.task_graph(self.ch, ME, "mw:90")
        kinds = {n["kind"] for n in g["nodes"]}
        self.assertTrue({"mission", "task", "agent", "evaluator", "result"} <= kinds)
        self.assertEqual(g["state"], "COMPLETED")  # done without a verdict (D-018)
        self.assertEqual(next(n for n in g["nodes"] if n["kind"] == "evaluator")["state"], "missing")
        with self.assertRaises(HTTPException): mo.task_graph(self.ch, ME, "mw:9999")


class Accountability(Base):
    def setUp(self):
        super().setUp()
        agent_core.init(self.db)
        self.orc = orchestrator.Orchestrator(self.db)

    def tearDown(self):
        agent_core._core = None
        super().tearDown()

    def run_(self, status, score=None, error=None, ev=None, cls=None, reason=""):
        rid = self.db.q("""INSERT INTO ac_runs (system, owner_id, kind, ref, status, score, error, started, finished, tokens) VALUES ('teams', 7, 'task', ?, ?, ?, ?, ?, ?, 10)
                           RETURNING id""", (f"mw:{time.time_ns()}", status, score, error, NOW - 60, NOW), one=True)["id"]
        if ev: self.db.q("INSERT INTO io_evals (run_id, owner_id, system, kind, state, reason, ts) VALUES (?, 7, 'teams', 'task', ?, ?, ?)", (rid, ev, reason, NOW))
        if cls: self.db.q("INSERT INTO io_diag (run_id, owner_id, system, cls, recoverable, recovery, ts) VALUES (?, 7, 'teams', ?, 1, 'retry', ?)", (rid, cls, NOW))
        return rid

    def test_every_finished_run_is_in_exactly_one_outcome(self):
        self.run_("done", 95, ev="scored"); self.run_("done", 60, ev="scored"); self.run_("done", 30, ev="scored")
        self.run_("failed", error="boom", ev="excluded", cls="task"); self.run_("failed", error="timed out", ev="excluded", cls="transient")
        self.run_("cancelled", ev="excluded", reason="Stopped"); self.run_("done", ev="excluded", reason="Evaluation tooling")
        self.run_("done", ev="gap", reason="No evaluator assigned to Teams's 'task' runs"); self.run_("done"); self.run_("failed", error="odd")
        self.run_("running")
        a = mo.accountability(self.ch, 7, NOW - 3600)
        n = {o["key"]: o["n"] for o in a["outcomes"]}
        self.assertEqual(n, {"success": 1, "partial": 1, "failure": 2, "environment": 1, "reviewed": 0, "excluded": 2, "inconclusive": 3})
        self.assertEqual(sum(n.values()), a["total"]); self.assertEqual(a["total"], 10)  # the running one isn't finished
        self.assertEqual(sum(x["n"] for x in a["inconclusive"]), 3)
        for x in a["inconclusive"]: self.assertTrue(x["reason"] and x["next"])
        # the same figures the Intelligence layers page shows (orchestrator.coverage and .outcomes): one definition
        cov = self.orc.coverage(7, NOW - 3600)
        self.assertEqual((a["eligible"], a["scored_eligible"], a["coverage_pct"]), (cov["scoreable"], cov["scored"], cov["scored_pct"]))
        theirs = cov["outcomes"]["runs"]
        self.assertEqual((n["success"], n["partial"], n["failure"], n["environment"]), tuple(theirs[k] for k in ("success", "partial", "failure", "environment")))
        self.assertEqual((n["excluded"], n["inconclusive"]), (theirs["excluded"] + theirs["stopped"], theirs["unsettled"]))


class Budget(Base):
    def setUp(self):
        super().setUp()
        agent_core.init(self.db)
        mo.ensure_schema(self.db)
        mo._cache.clear()

    def tearDown(self):
        agent_core._core = None
        agent_core._guards.clear()
        agent_core._local.run = None
        super().tearDown()

    def test_a_guard_stops_a_run_before_its_next_model_call(self):
        agent_core.register_guard("teams", lambda run: "Over the team's 24-hour token budget: 9 of 5 tokens." if run.get("system") == "teams" else None)
        agent_core.begin("teams", 7, "task", ref="mw:1")
        why = agent_core.over()
        self.assertIn("token budget", why)  # the words the Autoloop reads as a budget stop, not the task's fault
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM ac_limit_hits WHERE owner_id=7", one=True)["n"], 1)
        agent_core.end("failed", error=why)
        agent_core.begin("workforce", 7, "task", ref="wf:1")
        self.assertIsNone(agent_core.over())
        agent_core.end()

    def test_a_monthly_limit_counts_from_the_first(self):
        self.db.q("INSERT INTO ac_runs (system, owner_id, kind, ref, status, tokens, started) VALUES ('hub', 7, 'chat', 'x:1', 'done', 600, ?)", (agent_core._month() + 5,))
        self.db.q("INSERT INTO ac_runs (system, owner_id, kind, ref, status, tokens, started) VALUES ('hub', 7, 'chat', 'x:0', 'done', 9000, ?)", (agent_core._month() - 86400,))
        L = agent_core.get().set_limit(7, "global", "*", tokens=1000, period="month", by="t")
        self.assertEqual(agent_core.get()._spent({"owner": 7}, L), 600)
        agent_core.begin("hub", 7, "chat", ref="x:2")
        self.assertIsNone(agent_core.over())
        agent_core.used(500)
        self.assertIn("this month", agent_core.over())
        agent_core.end()
        with self.assertRaises(ValueError): agent_core.get().set_limit(7, "global", "*", tokens=1, period="year")

    def test_the_team_budget_counts_runs_in_flight_and_stops_them_at_the_gateway(self):
        q = self.db.q
        q("CREATE TABLE mw_runs (id INTEGER PRIMARY KEY, comp_id INTEGER, task_id INTEGER, agent_id INTEGER, kind TEXT, status TEXT, started REAL, finished REAL, tokens INTEGER DEFAULT 0)")
        q("INSERT INTO mw_runs (id, comp_id, kind, status, started, tokens) VALUES (1, 1, 'task', 'done', ?, 100000), (2, 1, 'task', 'running', ?, 0)", (NOW - 60, NOW - 30))
        q("INSERT INTO ac_runs (system, owner_id, kind, ref, status, tokens, started, team) VALUES ('teams', 7, 'task', 'mw:2', 'running', 70000, ?, 'comp:1')", (NOW - 30,))
        w = mining_work.Work.__new__(mining_work.Work)
        w.db, w._guarded = self.db, {}
        self.assertEqual(w.day_tokens(1), 170000)  # 100k finished + 70k a run in flight has used so far
        run = {"system": "teams", "team": "comp:1"}
        self.assertIn("token budget", w._budget_guard(run))  # 170k of a 150k budget: past 110%
        q("UPDATE mw_comps SET budget=160000 WHERE id=1"); w._guarded.clear()
        self.assertIsNone(w._budget_guard(run))  # over 100% (its tool calls say file now), under the hard stop
        self.assertIsNone(w._budget_guard({"system": "workforce", "team": "comp:1"}))
        q("UPDATE mw_comps SET budget=0 WHERE id=1"); w._guarded.clear()
        self.assertIsNone(w._budget_guard(run))  # no budget, no stop

    def test_a_cli_turn_is_counted_like_an_api_call(self):
        out = {"usage": {"input_tokens": 100, "output_tokens": 50, "cache_creation_input_tokens": 30, "cache_read_input_tokens": 90000}}
        self.assertEqual(llm._cli_tokens(out), 180)
        from app import terminal_bridge
        self.assertNotIn("cache_read_input_tokens", terminal_bridge.USAGE)  # the session path a team task with tools takes

    def test_tokens_that_arrive_per_turn_stop_the_run_at_its_next_call(self):
        """A CLI session reports usage per model turn: the gateway is asked before each turn, the ledger is added to after it."""
        q = self.db.q
        q("CREATE TABLE mw_runs (id INTEGER PRIMARY KEY, comp_id INTEGER, task_id INTEGER, agent_id INTEGER, kind TEXT, status TEXT, started REAL, finished REAL, tokens INTEGER DEFAULT 0)")
        q("INSERT INTO mw_runs (id, comp_id, kind, status, started, tokens) VALUES (5, 1, 'task', 'running', ?, 0)", (NOW,))
        w = mining_work.Work.__new__(mining_work.Work)
        w.db, w._guarded = self.db, {}
        agent_core.register_guard("teams", w._budget_guard)
        agent_core.register_resolver(lambda system, ref: {"team": "comp:1"} if ref == "mw:5" else {})
        try:
            agent_core.begin("teams", 7, "task", ref="mw:5")
            self.assertIsNone(agent_core.over())       # turn 1 may start: nothing spent
            agent_core.used(90_000); w._guarded.clear()
            self.assertIsNone(agent_core.over())       # 90k of 150k
            agent_core.used(80_000); w._guarded.clear()
            self.assertIn("token budget", agent_core.over())  # 170k: past 110%, the next turn doesn't start
            agent_core.end("failed")
        finally:
            agent_core._resolvers.pop()

    def test_reconciliation_names_the_gap_and_its_cause(self):
        q = self.db.q
        q("CREATE TABLE mw_runs (id INTEGER PRIMARY KEY, comp_id INTEGER, task_id INTEGER, agent_id INTEGER, kind TEXT, status TEXT, started REAL, finished REAL, tokens INTEGER DEFAULT 0)")
        q("INSERT INTO mw_runs (id, comp_id, kind, status, started, tokens) VALUES (1, 1, 'task', 'done', ?, 2000000)", (NOW - 60,))
        q("""INSERT INTO ac_runs (system, owner_id, kind, ref, title, status, tokens, started, team, model) VALUES
             ('teams', 7, 'task', 'mw:1', 'Port the solver', 'done', 2000000, ?, 'comp:1', 'terminal:opus')""", (NOW - 60,))
        c = {"comp_id": 1, "ref": "comp:1", "title": "SN62 · Competition 28", "budget": {"tokens": 150000, "used_24h": 2000000}}
        r = mo.reconcile(self.ch, 7, c, NOW)
        self.assertEqual((r["state"], r["counted"], r["ledger"], r["over"]), ("over", 2000000, 2000000, 1850000))
        self.assertEqual(r["plan_share"], 100)
        self.assertTrue(any("CLI" in x for x in r["causes"])); self.assertTrue(any("One run alone" in x for x in r["causes"]))
        self.assertEqual(r["note"], "")

    def test_four_scopes_say_what_is_set_and_what_is_missing(self):
        v = mo.view(self.ch, ME, fresh=True)
        sc = {s["scope"]: s for s in v["budget"]["scopes"]}
        self.assertEqual(list(sc), ["company", "competition", "team", "task"])
        self.assertFalse(sc["company"]["set"]); self.assertIn("a monthly limit", sc["company"]["missing"])
        self.assertTrue(sc["team"]["set"])
        self.assertTrue(any(x["kind"] == "budget" and "company-wide" in x["title"] for x in v["queue"]))
        agent_core.get().set_cap(7, 1_000_000, "t")
        v = mo.view(self.ch, ME, fresh=True)
        self.assertTrue(next(s for s in v["budget"]["scopes"] if s["scope"] == "company")["set"])


class NegativeExperience(unittest.TestCase):
    def test_a_task_that_gave_up_settles_its_open_recalls_as_failure(self):
        import tempfile
        from app.auth import AuthDB
        with tempfile.TemporaryDirectory() as d:
            db = AuthDB(os.path.join(d, "a.db"))
            agent_core.init(db)
            try:
                o = orchestrator.Orchestrator(db)
                db.q("CREATE TABLE mw_tasks (id INTEGER PRIMARY KEY, comp_id INTEGER, status TEXT, hold TEXT)")
                db.q("""CREATE TABLE ex_uses (id INTEGER PRIMARY KEY AUTOINCREMENT, recall_id INTEGER, user_id INTEGER, ref TEXT, rank INTEGER, context TEXT, outcome TEXT,
                        ts REAL, settled REAL)""")
                db.q("INSERT INTO mw_tasks VALUES (1, 1, 'todo', 'failed'), (2, 1, 'done', NULL), (3, 1, 'blocked', NULL)")
                old = NOW - orchestrator.SETTLE_AFTER - 10
                for t in (1, 2, 3): db.q("INSERT INTO ex_uses (recall_id, user_id, ref, rank, context, ts) VALUES (1, 7, 'mk:1', 1, ?, ?)", (f"mw:{t}", old))
                o.settle_outcomes()
                got = {r["context"]: r["outcome"] for r in db.q("SELECT context, outcome FROM ex_uses")}
                self.assertEqual(got, {"mw:1": "failure", "mw:2": "success", "mw:3": None})
            finally:
                agent_core._core = None

    def test_failed_work_is_a_recallable_experience(self):
        self.assertIn("mwf", experience.SOURCES)
        import tempfile
        from app.auth import AuthDB
        with tempfile.TemporaryDirectory() as d:
            db = AuthDB(os.path.join(d, "a.db"))
            q = db.q
            q("CREATE TABLE mh_campaigns (id INTEGER PRIMARY KEY, user_id INTEGER, netuid INTEGER)")
            q("CREATE TABLE mw_comps (id INTEGER PRIMARY KEY, campaign_id INTEGER, number INTEGER, name TEXT, status TEXT)")
            q("CREATE TABLE mw_tasks (id INTEGER PRIMARY KEY, comp_id INTEGER, title TEXT, detail TEXT, note TEXT, runs INTEGER, fails INTEGER, hold TEXT, fail_class TEXT, updated REAL)")
            q("CREATE TABLE mw_runs (id INTEGER PRIMARY KEY, task_id INTEGER, status TEXT, error TEXT, tokens INTEGER)")
            q("""CREATE TABLE mx_missions (id INTEGER PRIMARY KEY, user_id INTEGER, title TEXT, goal TEXT, status TEXT, stage TEXT, engine TEXT, outcome TEXT, report TEXT,
                 error TEXT, spent REAL, finished REAL, created REAL)""")
            q("INSERT INTO mh_campaigns VALUES (1, 7, 62)"); q("INSERT INTO mw_comps VALUES (1, 1, 28, '', 'active')")
            q("INSERT INTO mw_tasks VALUES (5, 1, 'Port the detector to Rust', 'Rewrite it', 'Failed: the build never linked', 3, 3, 'failed', 'task', ?)", (NOW,))
            q("INSERT INTO mw_tasks VALUES (6, 1, 'Fine', '', '', 1, 0, NULL, NULL, ?)", (NOW,))
            q("INSERT INTO mw_runs VALUES (1, 5, 'failed', 'linker error: undefined symbol', 40000)")
            q("INSERT INTO mx_missions VALUES (2, 7, 'Scrape the leaderboard', 'Get the top 10', 'failed', 'execute', 'workforce', 'failed', NULL, 'The site blocked every request', 1.5, ?, ?)", (NOW, NOW))

            class Hub(experience.Experience):
                def __init__(self, db): self.db = db
                def _has(self, t): return bool(self.db.q("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,), one=True))
            rows = {r["ref"]: r for r in Hub(db)._exp_rows(7)}
            self.assertEqual(rows["mwf:5"]["outcome"], "failure")
            self.assertIn("linker error", rows["mwf:5"]["text"]); self.assertIn("failure class: task", rows["mwf:5"]["text"])
            self.assertNotIn("mwf:6", rows)
            self.assertEqual(rows["mx:2"]["outcome"], "failure"); self.assertIn("blocked every request", rows["mx:2"]["text"])


class PortableSql(unittest.TestCase):
    """Postgres refuses these words as a bare column alias (42601): `SUM(x) day` must be `SUM(x) AS day`, or another name."""
    BARE = re.compile(r"\)\s+(day|year|month|hour|minute|second|filter|over|within|array|char|character|precision|varying|isnull|notnull|overlaps)\s*(,|\bFROM\b|\n)", re.I)

    def test_no_reserved_bare_alias_in_the_backend(self):
        bad = []
        for p in glob.glob(os.path.join(os.path.dirname(mo.__file__), "*.py")):
            with open(p, encoding="utf-8") as f: src = f.read()
            for m in re.finditer(r'"""(.*?)"""|"([^"\n]*)"', src, re.S):
                s = m.group(1) or m.group(2) or ""
                if re.search(r"\bSELECT\b", s) and self.BARE.search(s): bad.append(f"{os.path.basename(p)}: {self.BARE.search(s).group(0).strip()!r}")
        self.assertEqual(bad, [])

    def test_the_sandbox_figure_reads_named_columns(self):
        with open(os.path.join(os.path.dirname(mo.__file__), "intel_layers.py"), encoding="utf-8") as f: src = f.read()
        self.assertIn("AS week_count", src); self.assertIn("AS today_count", src)
        self.assertNotIn("SUM(s.started>?) day", src)


if __name__ == "__main__":
    unittest.main()
