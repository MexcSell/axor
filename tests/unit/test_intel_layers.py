"""intel_layers.py (Control Hub → Intelligence layers): six layers with their parts, figures scoped to the signed-in user,
Workflow figures for administrators only, a layer's status from its parts, a missing table counting as not set up, the agents gate."""
import json, os, tempfile, time, unittest

from fastapi import HTTPException

from app import intel_layers, mining, missions, workforce
from app.auth import AuthDB

ADMIN = {"id": 7, "username": "leo", "role": "admin"}
MEMBER = {"id": 8, "username": "ana", "role": "member"}


class Ov:
    def __init__(self, ok=True): self.ok = ok
    def _agents_ok(self, me): return self.ok


class WF:
    def memory_recall(self, *a, **k): return []


def part(d, layer, name):
    L = next(x for x in d["layers"] if x["key"] == layer)
    return next(p for p in L["parts"] if p["name"] == name)


def fig(p, label):
    return next(f["value"] for f in p["figures"] if f["label"] == label)


class LayersTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        missions.Missions(self.db, hub=None, wf=WF(), ia=None, mw=None)  # creates the mx_ tables
        q, now = self.db.q, time.time()
        self.flags = (mining.ENABLED, workforce.ENABLED)
        mining.ENABLED, workforce.ENABLED = True, False
        q("INSERT INTO mx_missions (id, user_id, title, status, discovery, created) VALUES (1, 7, 'Pick a subnet', 'running', ?, ?)", (json.dumps({"brief": {"summary": "x"}}), now))
        q("INSERT INTO mx_missions (id, user_id, title, status, discovery, created) VALUES (2, 7, 'Old one', 'done', ?, ?)", (json.dumps({}), now - 30 * 86400))
        q("INSERT INTO mx_missions (id, user_id, title, status, created) VALUES (3, 8, 'Hers', 'done', ?)", (now,))
        q("INSERT INTO mx_lessons (user_id, mission_id, kind, text, used, created) VALUES (7, 1, 'worked', 'a', 2, ?)", (now,))
        q("INSERT INTO mx_lessons (user_id, mission_id, kind, text, used, created) VALUES (8, 3, 'worked', 'b', 5, ?)", (now,))
        # the agent core's run ledger: two runs of the admin's this week (one failed, one scored and routed), one of the member's
        q("""CREATE TABLE ac_runs (id INTEGER PRIMARY KEY, system TEXT, owner_id INTEGER, agent_key TEXT, kind TEXT, ref TEXT, title TEXT, status TEXT,
             tokens INTEGER, reported INTEGER, cost REAL, model TEXT, error TEXT, started REAL, finished REAL, score REAL, decision TEXT)""")
        q("INSERT INTO ac_runs (owner_id, status, started, score, decision) VALUES (7, 'done', ?, 80, '{}')", (now,))
        q("INSERT INTO ac_runs (owner_id, status, started) VALUES (7, 'failed', ?)", (now,))
        q("INSERT INTO ac_runs (owner_id, status, started, score) VALUES (8, 'done', ?, 40)", (now,))
        # one open Competition team of the admin's, with a Workflow eval and a kept watch
        q("CREATE TABLE mh_campaigns (id INTEGER PRIMARY KEY, user_id INTEGER, netuid INTEGER)")
        q("CREATE TABLE mw_comps (id INTEGER PRIMARY KEY, campaign_id INTEGER, number INTEGER, name TEXT, status TEXT, budget INTEGER, goal TEXT, autopilot INTEGER, paused INTEGER, updated REAL)")
        q("CREATE TABLE mw_runs (id INTEGER PRIMARY KEY, comp_id INTEGER, status TEXT, started REAL)")
        q("CREATE TABLE mb_flows (id INTEGER PRIMARY KEY, comp_id INTEGER, user_id INTEGER)")
        q("CREATE TABLE mb_experiments (id INTEGER PRIMARY KEY, flow_id INTEGER, status TEXT, finished REAL)")
        q("CREATE TABLE mb_watches (id INTEGER PRIMARY KEY, flow_id INTEGER, status TEXT, started REAL, ended REAL)")
        q("INSERT INTO mh_campaigns VALUES (1, 7, 62)")
        q("INSERT INTO mw_comps VALUES (5, 1, 28, 'Ridges', 'open', 0, '', 1, 0, ?)", (now,))
        q("INSERT INTO mw_runs VALUES (1, 5, 'done', ?)", (now,))
        q("INSERT INTO mb_flows VALUES (9, 5, 7)")
        q("INSERT INTO mb_experiments VALUES (1, 9, 'done', ?)", (now,))
        q("INSERT INTO mb_watches VALUES (1, 9, 'kept', ?, ?)", (now, now))
        self.L = intel_layers.Layers(self.db, Ov())

    def tearDown(self):
        mining.ENABLED, workforce.ENABLED = self.flags
        self.dir.cleanup()

    def test_six_layers_with_status(self):
        d = self.L.view(ADMIN, fresh=True)
        self.assertEqual([x["key"] for x in d["layers"]], ["mission", "workforce", "execution", "knowledge", "evaluation", "adaptive"])
        self.assertEqual(d["errors"], [])
        st = {x["key"]: x["status"] for x in d["layers"]}
        self.assertEqual(st["mission"], "operational")  # a mission started and researched this week: both required parts worked
        self.assertEqual(st["execution"], "operational")  # runs this week; one failure of two is a warning, under MIN_N runs
        self.assertEqual(st["evaluation"], "incomplete")  # no Evolution experiments (no ev_ tables): a required part is missing
        self.assertEqual(st["adaptive"], "incomplete")
        self.assertEqual(sum(d["score"].values()), 6)
        ev = next(x for x in d["layers"] if x["key"] == "evaluation")
        self.assertEqual([x["key"] for x in ev["depends"]], ["execution"])
        self.assertEqual(ev["depends"][0]["status"], "operational")

    def test_figures_are_the_owners(self):
        d = self.L.view(ADMIN, fresh=True)
        brief = part(d, "mission", "Intelligence brief")
        self.assertEqual((fig(brief, "Missions researched"), fig(brief, "Of recent missions")), (1, 2))
        runs = part(d, "execution", "Agent runs")
        self.assertEqual((fig(runs, "Runs this week"), fig(runs, "Failed or lost")), (2, 1))
        self.assertEqual(fig(part(d, "evaluation", "Run scores"), "Average score"), 80)
        self.assertEqual(fig(part(d, "workforce", "Model router"), "Calls routed this week"), 1)
        self.assertEqual(fig(part(d, "knowledge", "Mission lessons"), "Times reused"), 2)
        auto = part(d, "execution", "Autoloop")
        self.assertEqual((fig(auto, "Teams on autopilot"), fig(auto, "Team runs this week")), (1, 1))
        her = self.L.view(MEMBER, fresh=True)
        self.assertEqual(fig(part(her, "knowledge", "Mission lessons"), "Times reused"), 5)
        self.assertEqual(fig(part(her, "evaluation", "Run scores"), "Average score"), 40)
        self.assertFalse(part(her, "execution", "Autoloop")["present"])  # she has no open team

    def test_open_tasks_nobody_dispatched_degrade_the_mission_layer(self):
        """The review's "14 open tasks, 0 in progress": Task dispatch names it instead of the layer looking merely idle."""
        q, old = self.db.q, time.time() - 2 * 3600
        q("""CREATE TABLE ctl_tasks (id INTEGER PRIMARY KEY, user_id INTEGER, route TEXT, ref TEXT, status TEXT, origin TEXT, updated REAL)""")
        q("CREATE TABLE ctl_settings (user_id INTEGER PRIMARY KEY, mode TEXT)")
        q("CREATE TABLE og_audit (id INTEGER PRIMARY KEY, user_id INTEGER, ts REAL, actor TEXT, action TEXT, target TEXT, detail TEXT)")
        for i in range(3): q("INSERT INTO ctl_tasks (user_id, route, ref, status, origin, updated) VALUES (7, 'board', NULL, 'todo', 'template', ?)", (old,))
        q("INSERT INTO ctl_settings VALUES (7, 'manual')")
        p = part(self.L.view(ADMIN, fresh=True), "mission", "Task dispatch")
        # Manual mode: the stall is yours (a setting you chose), named, not the dispatcher's failure
        self.assertEqual((fig(p, "Open tasks"), fig(p, "Under way"), fig(p, "Stalled 1 h+, AXoR's move"), fig(p, "Stalled 1 h+, yours")), (3, 0, 0, 3))
        self.assertEqual(p["checks"][0]["level"], "warn"); self.assertIn("wait for you: 3 manual mode", p["checks"][0]["text"])
        q("UPDATE ctl_settings SET mode='hybrid'")  # Hybrid: AXoR should have sent them an hour ago, so the part fails
        p = part(self.L.view(ADMIN, fresh=True), "mission", "Task dispatch")
        self.assertEqual((fig(p, "Stalled 1 h+, AXoR's move"), fig(p, "Stalled 1 h+, yours"), p["state"]), (3, 0, "degraded"))
        self.assertIn("3 stalled on AXoR's side: 3 axor dispatches it on its next pass (within a minute) (Dispatcher)", p["checks"][0]["text"])
        q("UPDATE ctl_tasks SET status='running' WHERE id=1")
        q("INSERT INTO og_audit (user_id, ts, actor, action) VALUES (7, ?, 'AXoR', 'control.task.dispatch')", (time.time(),))
        p = part(self.L.view(ADMIN, fresh=True), "mission", "Task dispatch")
        self.assertEqual((p["state"], fig(p, "Dispatched this week"), fig(p, "Under way")), ("ok", 1, 1))
        self.assertEqual(p["checks"][0]["level"], "warn")  # two still never dispatched

    def test_agent_runs_add_up(self):
        from app import agent_core
        agent_core.init(self.db)
        try:
            p = part(self.L.view(ADMIN, fresh=True), "execution", "Agent runs")
            parts = sum(fig(p, k) for k in ("Succeeded", "Failed", "Timed out", "Cut off by a restart", "Cancelled", "Still running"))
            self.assertEqual(parts, fig(p, "Runs this week"))
        finally:
            agent_core._core = None

    def test_workflow_is_admin_only(self):
        d = self.L.view(ADMIN, fresh=True)
        self.assertEqual(fig(part(d, "evaluation", "Lab evals"), "Evals this week"), 1)
        self.assertEqual(fig(part(d, "adaptive", "Watches"), "Kept"), 1)
        self.db.q("UPDATE mh_campaigns SET user_id=8")  # the same team, owned by a member: still not shown
        m = self.L.view(MEMBER, fresh=True)
        self.assertFalse(part(m, "evaluation", "Lab evals")["present"])
        self.assertFalse(part(m, "adaptive", "Watches")["present"])
        self.assertEqual(part(m, "adaptive", "Watches")["figures"], [])

    def test_missing_tables_are_not_set_up(self):
        d = self.L.view(ADMIN, fresh=True)
        self.assertFalse(part(d, "adaptive", "Evolution Lab")["present"])   # no ev_ tables in this database
        self.assertFalse(part(d, "workforce", "Workforce")["present"])      # Workforce is off
        self.assertEqual(d["errors"], [])

    def test_degraded_and_failure_classes(self):
        q, now = self.db.q, time.time()
        for e in ["Request timed out after 120 s", "rate limit reached (429)", "sandbox pod didn't start", "the tool search_web failed",
                  "token budget used up", "wrote nonsense"] * 4:
            q("INSERT INTO ac_runs (owner_id, status, error, started) VALUES (7, 'failed', ?, ?)", (e, now))
        q("INSERT INTO ac_runs (owner_id, status, started) VALUES (7, 'lost', ?)", (now,))
        q("INSERT INTO ac_runs (owner_id, status, started, score) VALUES (7, 'done', ?, 20)", (now,))
        d = self.L.view(ADMIN, fresh=True)
        st = {x["key"]: x["status"] for x in d["layers"]}
        self.assertEqual(st["execution"], "degraded")  # 26 of 29 finished runs failed
        runs = part(d, "execution", "Agent runs")
        self.assertEqual(runs["state"], "degraded")
        self.assertEqual(runs["checks"][0]["level"], "fail")
        f = {x["key"]: x["n"] for x in d["failures"]}
        self.assertEqual((f["transient"], f["rate"], f["sandbox"], f["tool"], f["budget"], f["restart"], f["low"]), (4, 4, 4, 4, 4, 1, 1))
        self.assertEqual(f["task"], 5)  # "wrote nonsense" ×4 and the one failed run without an error from setUp
        self.assertEqual(d["fix"][0]["level"], "fail")  # failed checks lead the fix list
        self.assertTrue(any(x["part"] == "Agent runs" for x in d["fix"]))

    def test_brief_states_and_evidence(self):
        q, now = self.db.q, time.time()
        q("INSERT INTO mx_missions (user_id, title, status, discovery, created) VALUES (7, 'Skipped', 'done', ?, ?)",
          (json.dumps({"lessons": [], "brief": {"skipped": "The budget is too small for research"}}), now))
        q("INSERT INTO mx_missions (user_id, title, status, discovery, created) VALUES (7, 'No web', 'done', ?, ?)",
          (json.dumps({"brief": {"facts": [1], "web": False}}), now))
        d = self.L.view(ADMIN, fresh=True)
        b = part(d, "mission", "Intelligence brief")
        self.assertEqual((fig(b, "Missions researched"), fig(b, "Skipped"), fig(b, "Without the web")), (2, 1, 1))
        self.assertTrue(any("budget is too small" in c["text"] for c in b["checks"]))
        self.assertTrue(any("no web source" in c["text"] for c in b["checks"]))
        ev = d["evidence"]
        self.assertEqual(ev["now"]["runs"], 2)  # the admin's two finished runs this week
        self.assertEqual(ev["now"]["fail_rate"], 50.0)
        self.assertIsNone(ev["before"]["score"])
        self.assertEqual([p["key"] for p in d["pipeline"]], ["observe", "diagnose", "propose", "experiment", "evaluate", "approve", "promote", "monitor", "rollback"])
        self.assertTrue(next(p for p in d["pipeline"] if p["key"] == "diagnose")["stall"])  # something observed, nothing diagnosed

    def test_an_empty_week_is_quiet_not_broken(self):
        from app import agent_core, orchestrator
        saved = (orchestrator._orc, list(agent_core._resolvers))
        try:
            o = orchestrator.init(self.db)
            self.assertEqual({e["state"] for e in o.edges(7, time.time() - 7 * 86400)}, {"quiet"})
        finally:
            orchestrator._orc = saved[0]
            agent_core._resolvers[:] = saved[1]

    def test_learned_guidance_is_counted_per_planner(self):
        """Team lead plans emit mission.guided too (mining_work._plan): they're a figure of their own, and they can't hide a
        Mission Control mission that planned without guidance (the check compares mx missions with mx discoveries)."""
        from app import agent_core, orchestrator
        saved = (orchestrator._orc, list(agent_core._resolvers))
        try:
            o = orchestrator.init(self.db)
            for i in range(3): o.emit(7, "mission.guided", f"mw:{i}:guided", corr="comp:1", ref=f"mw:{i}", status="done")
            o.emit(7, "mission.guided", "ctl:mi:4:guided", corr="comp:1", ref="ctl:mi:4", status="done")
            p = part(self.L.view(ADMIN, fresh=True), "mission", "Learned guidance")
            self.assertEqual((fig(p, "Missions guided this week"), fig(p, "Mission Intelligence reviews guided"), fig(p, "Team lead plans guided")), (0, 1, 3))
            if fig(p, "Missions discovered this week"):
                self.assertIn("planned without learned guidance", " ".join(c["text"] for c in p["checks"]))
        finally:
            orchestrator._orc = saved[0]
            agent_core._resolvers[:] = saved[1]

    def test_handoffs_are_the_orchestrators_ledger(self):
        """The overview's handoffs and the orchestrator's table are the same rows: one ledger, one window, one state rule."""
        from app import agent_core, orchestrator
        saved = (orchestrator._orc, list(agent_core._resolvers))
        try:
            o = orchestrator.init(self.db)
            o.evaluate(); o.observe_handoffs()
            o.observe_handoffs()  # idempotent: a second round adds nothing
            d = self.L.view(ADMIN, fresh=True)
            g = o.view(ADMIN)
            strip = lambda E: [(e["key"], e["done"], e["dead"], e["state"]) for e in E]
            self.assertEqual(strip(d["links"]), strip(g["edges"]))
            L = {x["key"]: x for x in d["links"]}
            self.assertEqual(L["execution>evaluation"]["n"], 1)  # the admin's scored run, not the member's
            st = {x["key"]: (x["status"], x["moved"]) for x in d["layers"]}  # health on the same ledger: work through a layer is never "idle"
            self.assertTrue(all(s != "idle" for s, m in st.values() if m), st)
            self.assertTrue(all(s != "operational" for s, m in st.values() if not m), st)
            self.assertEqual(st["mission"], ("partial", 0))  # its parts worked, but nothing it planned crossed to the Workforce this week
            self.assertEqual(L["workforce>execution"]["n"], 1)  # the routed one
            self.assertEqual(L["execution>knowledge"]["n"], 1)  # the admin's lesson
            self.assertEqual((L["evaluation>adaptive"]["n"], L["evaluation>adaptive"]["state"]), (1, "flowing"))  # the Workflow's Lab eval: a measured change
            self.assertEqual(L["adaptive>mission"]["state"], "broken")  # something reached Adaptive and nothing went back to missions
            self.assertEqual(L["adaptive>mission"]["plans"], 1)  # the fixture's mission planned this week without learned guidance
            self.assertIn("1 plan this week took nothing the loop learned", L["adaptive>mission"]["why"])
            self.db.q("UPDATE mx_missions SET discovery=NULL")
            E = next(e for e in o.edges(7, time.time() - 7 * 86400) if e["key"] == "adaptive>mission")
            self.assertEqual((E["state"], E["plans"]), ("broken", 0)); self.assertIn("No mission was planned this week", E["why"])  # the remedy: plan one
            self.assertEqual(L["mission>workforce"]["state"], "quiet")  # nothing reached Mission intelligence either
            n = self.db.q("SELECT COUNT(*) n FROM io_events", one=True)["n"]
            o.observe_handoffs()
            self.assertEqual(self.db.q("SELECT COUNT(*) n FROM io_events", one=True)["n"], n)
            # a handoff that stopped: other kinds crossed, not the one that completes it
            self.db.q("DELETE FROM io_events WHERE kind='proposal.tested'")
            o.emit(7, "agent.signal", "sig:x", corr="teams:1", status="done")
            self.assertEqual(next(e for e in o.edges(7, time.time() - 7 * 86400) if e["key"] == "evaluation>adaptive")["state"], "partial")
        finally:
            orchestrator._orc = saved[0]
            agent_core._resolvers[:] = saved[1]

    def test_recall_without_failures_is_flagged(self):
        q, now = self.db.q, time.time()
        q("""CREATE TABLE ex_uses (id INTEGER PRIMARY KEY, recall_id INTEGER, user_id INTEGER, ref TEXT, rank INTEGER, context TEXT,
             outcome TEXT, ts REAL, settled REAL)""")
        for _ in range(25): q("INSERT INTO ex_uses (user_id, ref, context, outcome, ts, settled) VALUES (7, 'mxl:1', 'mw:3', 'success', ?, ?)", (now, now))
        q("INSERT INTO ex_uses (user_id, ref, context, ts) VALUES (7, 'mxl:1', 'mw:4', ?)", (now - 30 * 86400,))
        p = part(self.L.view(ADMIN, fresh=True), "adaptive", "Recall track record")
        self.assertEqual((fig(p, "Settled on success"), fig(p, "Still open")), (25, 1))
        t = " ".join(c["text"] for c in p["checks"])
        self.assertIn("no failure ever settled", t)
        self.assertIn("waited over", t)

    def test_mission_trace(self):
        q = self.db.q
        q("UPDATE mx_missions SET goal='g', engine='direct', outcome='verified', verification=? WHERE id=1",
          (json.dumps({"results": [{"criterion": "a", "status": "met"}, {"criterion": "b", "status": "not_met"}]}),))
        q("INSERT INTO ac_runs (owner_id, ref, status, model, started, score) VALUES (7, 'mx:1', 'done', 'm1', ?, 90)", (time.time(),))
        d = self.L.trace(ADMIN)
        self.assertIsNone(d["trace"])
        self.assertEqual([m["id"] for m in d["missions"]], [2, 1])
        t = self.L.trace(ADMIN, 1)["trace"]
        self.assertEqual([x["key"] for x in t["layers"]], ["mission", "workforce", "execution", "knowledge", "evaluation", "adaptive"])
        L = {x["key"]: x for x in t["layers"]}
        self.assertTrue(any("Researched" in x for x in L["mission"]["lines"]))
        self.assertTrue(any("1 met" in x and "1 not met" in x for x in L["evaluation"]["lines"]))
        self.assertIn("Models used: m1", L["workforce"]["lines"])
        with self.assertRaises(HTTPException) as e: self.L.trace(MEMBER, 1)  # not hers
        self.assertEqual(e.exception.status_code, 404)

    def test_a_team_missions_sandbox_runs_are_execute_evidence(self):
        """The review's acceptance run puts sandbox execution in the lifecycle: a Competition team mission's sandbox runs, from
        when it handed the work to the team until it ended, are named in step 4 (Execute)."""
        q, now = self.db.q, time.time()
        q("""CREATE TABLE mw_sbx (id INTEGER PRIMARY KEY, comp_id INTEGER, task_id INTEGER, status TEXT, exit_code INTEGER, started REAL)""")
        q("UPDATE mx_missions SET engine='mining', child=5, child_started=?, status='delivered', finished=? WHERE id=1", (now - 3600, now - 60))
        q("INSERT INTO ac_runs (owner_id, ref, kind, status, started) VALUES (7, 'mx:1', 'task', 'done', ?)", (now - 1800,))
        for i, (st, code, at) in enumerate([("failed", 1, now - 3000), ("done", 0, now - 2000), ("timeout", None, now - 1500), ("done", 0, now - 7200)]):
            q("INSERT INTO mw_sbx (id, comp_id, task_id, status, exit_code, started) VALUES (?, 5, 1, ?, ?, ?)", (i + 1, st, code, at))
        m = q("SELECT * FROM mx_missions WHERE id=1", one=True)
        ex = self.L.loop_check(7, m)[3]
        self.assertIn("3 sandbox runs, 2 ran to an exit", ex["detail"])          # the one from before the mission isn't its
        self.assertIn("sandbox #2 done (exit 0)", ex["evidence"])
        self.assertNotIn("sandbox #4 done (exit 0)", ex["evidence"])
        q("DELETE FROM mw_sbx")
        self.assertIn("no sandbox run", self.L.loop_check(7, m)[3]["detail"])

    def test_agents_gate(self):
        with self.assertRaises(HTTPException) as e: intel_layers.Layers(self.db, Ov(ok=False)).view(MEMBER)
        self.assertEqual(e.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
