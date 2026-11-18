"""control_missions.py: missions (predefined = a Bittensor competition, custom = Mission Control) and tasks (fixed / dynamic,
subtasks, standalone) kept apart, Bittensor as the primary initiative, the competition template's fixed tasks (seeded once,
recurring, skippable), and Mission Intelligence by mode (manual proposes, hybrid creates) with its fallback and dedupe."""
import json, os, sys, time, unittest
from unittest import mock

from fastapi import HTTPException

from app import agent_core, control_dispatch as cd, control_hub, control_missions as cm
from app.llm import LLMError

sys.path.insert(0, os.path.dirname(__file__))
from test_control_hub import Base, FakeLLM  # noqa: E402
from test_organization import ME  # noqa: E402


class IntelLLM(FakeLLM):
    def __init__(self, fail=False): super().__init__(); self.fail = fail
    def structured(self, model, system, prompt, schema, name, on_usage=None, effort="low", messages=None):
        if name != "intelligence": return super().structured(model, system, prompt, schema, name, on_usage, effort, messages)
        self.calls.append({"system": system, "prompt": prompt, "schema": name})
        if self.fail: raise LLMError("no model")
        if on_usage: on_usage(100)
        return {"summary": "Behind the target.", "proposals": [
                    {"title": "Benchmark against the miners ranked above us", "detail": "Run the validation set.", "priority": "high", "reason": "4 places behind"},
                    {"title": "Configure the miner infrastructure", "detail": "dup of a fixed task", "priority": "low", "reason": "already covered"}],
                "reprioritize": []}


class Missions(Base):
    def setUp(self):
        super().setUp()
        self.ch.edit_fixed(ME, 1, control_hub.FixedPatch(target_rank=10))  # SN62 · 28 is rank 14 of 200: 4 places behind
        self.unit = f"u:{cm._units(self.ch, ME)[1]['id']}"

    def mx(self, title, team=None, status="running"):
        q = self.db.q
        q("""CREATE TABLE IF NOT EXISTS mx_missions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, title TEXT, goal TEXT, status TEXT, stage TEXT,
             progress REAL, budget REAL, spent REAL, team INTEGER, plan TEXT, updated REAL, created REAL)""")
        return q("INSERT INTO mx_missions (user_id, title, goal, status, stage, team, plan, updated) VALUES (7,?,?,?,?,?,?,?) RETURNING id",
                 (title, title, status, "execute", team, json.dumps({"tasks": [{"id": 1, "title": "Research"}, {"id": 2, "title": "Build"}]}), time.time()), one=True)["id"]

    def test_bittensor_is_the_primary_initiative_and_each_competition_a_predefined_mission(self):
        d = cm.missions(self.ch, ME)
        bt, other = d["initiatives"]
        self.assertEqual((bt["key"], bt["primary"], other["primary"]), ("bittensor", True, False))
        self.assertEqual(sorted(m["ref"] for m in bt["missions"]), ["comp:1", "comp:2", "comp:4"])
        self.assertTrue(all(m["type"] == "predefined" for m in bt["missions"]))
        self.assertEqual(bt["summary"]["subnets"], 2)
        self.assertEqual(bt["summary"]["behind"], 1)
        self.assertEqual(bt["summary"]["best_rank"], 14)

    def test_the_template_seeds_fixed_tasks_once(self):
        cm.missions(self.ch, ME); cm.missions(self.ch, ME)
        m = cm.mission(self.ch, ME, "comp:1")
        self.assertEqual([t["template"] for t in m["fixed"]], ["infra", "interfaces", "availability", "deliverables"])
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM ctl_tasks WHERE mission='comp:1' AND kind='fixed'", one=True)["n"], 4)
        self.assertEqual(next(t for t in m["fixed"] if t["template"] == "availability")["cadence_days"], 7)

    def test_a_teams_task_serves_its_mission_unless_standalone_and_subtasks_inherit(self):
        t = self.ch.add_task(ME, control_hub.TaskIn(team=self.unit, title="Profile the scoring code", agent="", route="board"))
        s = self.ch.add_task(ME, control_hub.TaskIn(team=self.unit, title="Rotate the server logs", agent="", route="board", mission="none"))
        sub = self.ch.add_task(ME, control_hub.TaskIn(team=self.unit, title="Profile the tokenizer", agent="", route="board", parent=t["id"], mission="none"))
        row = lambda i: self.db.q("SELECT mission, kind, parent_id FROM ctl_tasks WHERE id=?", (i,), one=True)
        self.assertEqual(dict(row(t["id"])), {"mission": "comp:1", "kind": "dynamic", "parent_id": None})
        self.assertIsNone(row(s["id"])["mission"])
        self.assertEqual((row(sub["id"])["mission"], row(sub["id"])["parent_id"]), ("comp:1", t["id"]))
        self.assertEqual(cm.missions(self.ch, ME)["counts"]["standalone_open"], 1)
        with self.assertRaises(HTTPException): self.ch.add_task(ME, control_hub.TaskIn(team=self.unit, title="Elsewhere", agent="", route="board", mission="comp:3"))  # another user's

    def test_custom_missions_belong_to_bittensor_when_launched_for_a_team(self):
        a, b = self.mx("Speed up our SN62 miner", team=1), self.mx("Build a browser automation agent")
        d = cm.missions(self.ch, ME)
        bt, other = d["initiatives"]
        ca = next(m for m in bt["missions"] if m["ref"] == f"mx:{a}")
        self.assertEqual((ca["type"], ca["parent"]), ("custom", "comp:1"))
        self.assertEqual([m["ref"] for m in other["missions"]], [f"mx:{b}"])
        self.assertEqual([m["ref"] for m in cm.mission(self.ch, ME, "comp:1")["custom"]], [f"mx:{a}"])
        self.assertEqual([p["title"] for p in cm.mission(self.ch, ME, f"mx:{b}")["plan"]], ["Research", "Build"])
        self.assertEqual(d["counts"]["active"], 3 + 2)

    def test_a_recurring_fixed_task_opens_again_when_due(self):
        cm.missions(self.ch, ME)
        tid = self.db.q("SELECT id FROM ctl_tasks WHERE mission='comp:1' AND template='availability'", one=True)["id"]
        cm.run(self.ch, ME, tid)
        bid = int(self.db.q("SELECT ref FROM ctl_tasks WHERE id=?", (tid,), one=True)["ref"].split(":")[1])
        self.db.q("UPDATE ctl_tasks SET updated=? WHERE id=?", (time.time() - 30 * 86400, tid))  # sent to the board long ago...
        self.db.q("UPDATE mw_tasks SET status='done', done_at=? WHERE id=?", (time.time() - 86400, bid))  # ...finished yesterday
        cm.missions(self.ch, ME)
        t = next(t for t in cm.mission(self.ch, ME, "comp:1")["fixed"] if t["id"] == tid)
        self.assertEqual(t["status"], "done")  # due in 6 days, counted from when the board finished it
        self.assertAlmostEqual(t["due"], time.time() + 6 * 86400, delta=60)
        self.db.q("UPDATE ctl_tasks SET done_at=? WHERE id=?", (time.time() - 8 * 86400, tid))
        t = next(t for t in cm.mission(self.ch, ME, "comp:1")["fixed"] if t["id"] == tid)
        self.assertEqual((t["status"], t["ref"]), ("todo", None))

    def test_skip_promote_and_cadence(self):
        cm.missions(self.ch, ME)
        fx = self.db.q("SELECT id FROM ctl_tasks WHERE mission='comp:1' AND template='deliverables'", one=True)["id"]
        self.assertEqual(cm.patch(self.ch, ME, fx, cm.MTaskPatch(skip=True))["status"], "skipped")
        t = self.ch.add_task(ME, control_hub.TaskIn(team=self.unit, title="Check validator weights", agent="", route="board"))
        with self.assertRaises(HTTPException): cm.patch(self.ch, ME, t["id"], cm.MTaskPatch(cadence_days=3))  # only a fixed task recurs
        out = cm.patch(self.ch, ME, t["id"], cm.MTaskPatch(kind="fixed", cadence_days=3))
        self.assertEqual((out["kind"], out["cadence_days"]), ("fixed", 3))
        moved = cm.patch(self.ch, ME, t["id"], cm.MTaskPatch(mission="comp:2"))  # a move keeps its level
        self.assertEqual((moved["mission"], moved["kind"]), ("comp:2", "fixed"))
        with self.assertRaises(HTTPException): cm.patch(self.ch, ME, t["id"], cm.MTaskPatch(mission="comp:3"))  # another user's
        d = self.ch.add_task(ME, control_hub.TaskIn(team=self.unit, title="Read the new rules", agent="", route="board"))
        with self.assertRaises(HTTPException): cm.patch(self.ch, ME, d["id"], cm.MTaskPatch(skip=True))  # a dynamic task is cancelled, not skipped
        with self.assertRaises(HTTPException): cm.patch(self.ch, ME, 999, cm.MTaskPatch(skip=True))

    def test_intelligence_proposes_in_manual_mode_and_dedupes(self):
        self.hub.llm = IntelLLM()
        self.ch.set_mode(ME, control_hub.SettingsIn(mode="manual"))
        m = cm.intelligence(self.ch, ME, "comp:1")
        self.assertEqual([p["title"] for p in m["proposed"]], ["Benchmark against the miners ranked above us"])
        self.assertEqual([i["outcome"] for i in m["intelligence"]["items"]], ["proposed", "covered"])
        self.assertIn("4 places from the top 10", self.hub.llm.calls[-1]["prompt"])
        self.assertEqual(self.hub.used, [("control", 100)])
        # approved: onto the board; a second run doesn't propose it again
        pid = m["proposed"][0]["id"]
        t = cm.decide(self.ch, ME, pid, True)
        self.assertTrue((t["ref"] or "").startswith("mw_task:"))
        m2 = cm.intelligence(self.ch, ME, "comp:1")
        self.assertEqual(m2["proposed"], [])
        self.assertEqual({i["outcome"] for i in m2["intelligence"]["items"]}, {"covered"})

    def test_intelligence_creates_in_hybrid_mode(self):
        self.hub.llm = IntelLLM()
        m = cm.intelligence(self.ch, ME, "comp:1")
        self.assertEqual(m["proposed"], [])
        made = [t for t in m["dynamic"] if t["origin"] == "intelligence"]
        self.assertEqual([t["title"] for t in made], ["Benchmark against the miners ranked above us"])
        self.assertTrue(made[0]["ref"].startswith("mw_task:"))

    def test_without_a_model_it_reads_the_signals(self):
        self.hub.llm = IntelLLM(fail=True)
        self.ch.set_mode(ME, control_hub.SettingsIn(mode="manual"))
        m = cm.intelligence(self.ch, ME, "comp:1")
        self.assertEqual(m["intelligence"]["source"], "signals")
        self.assertEqual([p["title"] for p in m["proposed"]], ["Close the gap to the top 10"])
        self.assertEqual(self.hub.used, [])

    def test_intelligence_plans_with_what_the_loop_learned(self):
        """Adaptive → Mission: the review reads the orchestrator's guidance (failure classes, measured changes) and the handoff is
        on the ledger with the records it used; without a model the top failure class becomes a proposal of its own."""
        from app import orchestrator as orc
        saved = orc._orc
        try:
            o = orc.init(self.db)
            for i in range(3):
                self.db.q("INSERT INTO io_diag (run_id, owner_id, system, cls, recoverable, recovery, ts) VALUES (?, 7, 'teams', 'quota', 1, 'Wait for the usage window.', ?)",
                          (900 + i, time.time()))
            q = self.db.q  # a Workforce change measured in a trial: the planner hears it, better or not
            q("CREATE TABLE IF NOT EXISTS wf_agents (id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT)")
            q("""CREATE TABLE IF NOT EXISTS wf_improvements (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, agent_id INTEGER, change TEXT,
                 status TEXT, trials INTEGER DEFAULT 0, result TEXT, updated REAL)""")
            q("INSERT INTO wf_agents (id, user_id, name) VALUES (31, 7, 'Rhea')")
            iid = q("""INSERT INTO wf_improvements (user_id, agent_id, change, status, trials, result, updated) VALUES (7, 31, 'Cite every source', 'better', 1,
                       'Candidate 82 vs current 61', ?) RETURNING id""", (time.time(),), one=True)["id"]
            self.hub.llm = IntelLLM()
            cm.intelligence(self.ch, ME, "comp:1")
            self.assertIn("Measured, better: Cite every source (Rhea: Candidate 82 vs current 61)", self.hub.llm.calls[-1]["prompt"])
            self.assertIn("What AXoR learned from recent work", self.hub.llm.calls[-1]["prompt"])
            self.assertIn("Wait for the usage window.", self.hub.llm.calls[-1]["prompt"])
            ev = self.db.q("SELECT * FROM io_events WHERE kind='mission.guided'")
            self.assertEqual([(e["corr"], e["src"], e["dst"]) for e in ev], [("comp:1", "adaptive", "mission")])
            self.assertEqual(json.loads(ev[0]["payload"])["refs"], {"failures": ["quota"], "improvements": [iid]})
            E = {e["key"]: e for e in o.edges(7, time.time() - 7 * 86400)}
            self.assertEqual((E["adaptive>mission"]["done"], E["adaptive>mission"]["state"]), (1, "flowing"))
            self.hub.llm = IntelLLM(fail=True)
            self.ch.set_mode(ME, control_hub.SettingsIn(mode="manual"))
            m = cm.intelligence(self.ch, ME, "comp:1")
            self.assertIn("Plan around 'Plan usage limit' failures", [p["title"] for p in m["proposed"]])
            self.assertEqual(self.db.q("SELECT COUNT(*) n FROM io_events WHERE kind='mission.guided'", one=True)["n"], 2)  # one per review
        finally:
            orc._orc = saved

    def test_a_declined_proposal_closes_and_custom_missions_plan_their_own(self):
        self.hub.llm = IntelLLM(fail=True)
        self.ch.set_mode(ME, control_hub.SettingsIn(mode="manual"))
        pid = cm.intelligence(self.ch, ME, "comp:1")["proposed"][0]["id"]
        self.assertEqual(cm.decide(self.ch, ME, pid, False)["status"], "cancelled")
        with self.assertRaises(HTTPException): cm.decide(self.ch, ME, pid, True)
        with self.assertRaises(HTTPException): cm.intelligence(self.ch, ME, f"mx:{self.mx('Anything at all')}")

    def support_unit(self):
        """A plain team of another department (not a Competition team)."""
        dept = next(d["id"] for d in self.ch.tree(ME, True)["departments"] if d["kind"] in ("division", "department"))
        self.ch.add_team(ME, control_hub.TeamIn(dept=dept, name="Research squad", purpose="Reads the competition"))
        v = self.ch._view(ME, True)
        ref = next(f"u:{u['id']}" for u in v["units"] if u["name"] == "Research squad")
        key = next(a["key"] for a in v["agents"] if a["system"] != "teams" and a["status"] == "active" and a["load"] < a["cap"])
        self.ch.add_member(ME, ref, control_hub.MemberIn(key=key, how="assign", role="researcher"))
        return ref

    def test_several_teams_on_one_mission(self):
        sup = self.support_unit()
        m = cm.add_team(self.ch, ME, "comp:1", cm.TeamIn(team=sup, duty="Research the top miners"))
        self.assertEqual([(t["role"], t["duty"]) for t in m["mission"]["teams"]], [("lead", m["mission"]["teams"][0]["duty"]), ("support", "Research the top miners")])
        with self.assertRaises(HTTPException): cm.add_team(self.ch, ME, "comp:1", cm.TeamIn(team=sup))            # already on it
        with self.assertRaises(HTTPException): cm.add_team(self.ch, ME, "comp:1", cm.TeamIn(team=self.unit))      # the lead
        t = self.ch.add_task(ME, control_hub.TaskIn(team=sup, title="Read the top miners' code", agent="auto", route="agent", start=False, mission="comp:1"))
        self.assertEqual(t["route"], "agent")
        m = cm.mission(self.ch, ME, "comp:1")
        self.assertEqual(next(x for x in m["mission"]["teams"] if x["ref"] == sup)["open"], 1)
        with self.assertRaises(HTTPException): cm.run(self.ch, ME, -1)
        self.assertEqual(len(cm.remove_team(self.ch, ME, "comp:1", sup)["mission"]["teams"]), 1)
        with self.assertRaises(HTTPException): cm.remove_team(self.ch, ME, "comp:1", sup)

    def test_a_task_for_another_team_brings_it_onto_the_mission(self):
        sup = self.support_unit()
        self.ch.add_task(ME, control_hub.TaskIn(team=sup, title="Survey validator weights", agent="auto", route="agent", start=False, mission="comp:1"))
        teams = cm.mission(self.ch, ME, "comp:1")["mission"]["teams"]
        self.assertEqual([(t["ref"], t["duty"]) for t in teams if t["role"] == "support"], [(sup, "Joined with a task")])

    def test_intelligence_gives_tasks_to_the_team_it_names(self):
        sup = self.support_unit()
        name = cm.add_team(self.ch, ME, "comp:1", cm.TeamIn(team=sup, duty="Research"))["mission"]["teams"][1]["name"]
        llm = IntelLLM()
        base = llm.structured
        def named(model, system, prompt, schema, n, on_usage=None, effort="low", messages=None):
            out = base(model, system, prompt, schema, n, on_usage, effort, messages)
            if n == "intelligence": out["proposals"][0]["team"] = name
            return out
        llm.structured = named
        self.hub.llm = llm
        m = cm.intelligence(self.ch, ME, "comp:1")
        made = next(t for t in m["dynamic"] if t["origin"] == "intelligence")
        self.assertEqual((made["team"], made["route"]), (sup, "agent"))
        self.assertIn(f"{name} (support: Research", llm.calls[-1]["prompt"])

    def test_the_schedule_runs_in_auto_mode_only_when_due_and_not_held(self):
        self.hub.llm = IntelLLM(fail=True)
        with mock.patch.object(cm, "_owner", lambda ch, uid: dict(ME)):
            self.assertEqual(cm.tick(self.ch), 0)                          # hybrid: never on a timer
            self.ch.set_mode(ME, control_hub.SettingsIn(mode="auto"))
            self.assertEqual(cm.tick(self.ch), 3)                          # every predefined mission is due once
            self.assertEqual(cm.tick(self.ch), 0)                          # then not for EVERY_H hours
            self.assertEqual(self.db.q("SELECT by_user FROM ctl_intel ORDER BY id DESC LIMIT 1", one=True)["by_user"], "schedule")
            self.assertEqual(cm.tick(self.ch, now=time.time() + cm.EVERY_H * 3600 + 60), 3)
            self.db.q("UPDATE mw_comps SET budget=1000")                    # the team has used its whole daily budget (FakeWork: 1000 today)
            sch = cm.mission(self.ch, ME, "comp:1")["mission"]["schedule"]
            self.assertTrue(sch["on"]); self.assertIn("daily token budget", sch["hold"])
            self.assertEqual(cm.tick(self.ch, now=time.time() + 3 * cm.EVERY_H * 3600), 0)

    def test_the_hub_counts_missions_and_tasks_apart(self):
        s = self.ch._structure(ME)
        self.assertEqual((s["initiative"]["key"], s["counts"]["predefined"]), ("bittensor", 3))
        self.assertEqual(s["counts"]["fixed_open"], 12)
        self.assertEqual(s["counts"]["dynamic_open"], 0)


class EmptyLLM(FakeLLM):
    """An agent that says it's done and hands back nothing."""
    def structured(self, model, system, prompt, schema, name, on_usage=None, effort="low", messages=None):
        if name != "task": return super().structured(model, system, prompt, schema, name, on_usage, effort, messages)
        if on_usage: on_usage(50)
        return {"status": "done", "result": "  N/A ", "summary": "done"}


class Dispatch(Missions):
    """control_dispatch.py: Planner → Dispatcher → board or agent. The review's "14 open tasks, none in progress": the template's
    fixed tasks were never sent anywhere, Mission Intelligence's agent tasks were never started, a restart's were never resumed."""
    def hs(self): return f"u:{next(u['id'] for u in self.o.view(ME)['units'] if u['name'] == 'Handshake')}"

    def row(self, tid): return self.db.q("SELECT * FROM ctl_tasks WHERE id=?", (tid,), one=True)

    def agent_task(self, title, who="Noor", origin="intelligence", summary=None):
        t = self.ch.add_task(ME, control_hub.TaskIn(team=self.hs(), title=title, agent=self.key(who), start=False))
        self.db.q("UPDATE ctl_tasks SET origin=?, summary=? WHERE id=?", (origin, summary, t["id"]))
        return t["id"]

    def test_hybrid_sends_the_template_to_the_boards_and_manual_waits_for_you(self):
        self.ch.set_mode(ME, control_hub.SettingsIn(mode="manual"))
        d = cm.missions(self.ch, ME)
        self.assertEqual((d["counts"]["fixed_open"], d["counts"]["in_progress"]), (12, 0))
        self.assertEqual(cd.dispatch(self.ch, ME)["board"], 0)
        fixed = cm.mission(self.ch, ME, "comp:1")["fixed"]
        self.assertEqual({t["why"]["state"] for t in fixed}, {"manual"})
        self.assertFalse(cm.missions(self.ch, ME)["dispatch"]["on"])
        self.ch.set_mode(ME, control_hub.SettingsIn(mode="hybrid"))
        self.assertEqual(cd.dispatch(self.ch, ME)["board"], cd.PER_PASS)  # 12 fixed tasks on 3 missions: 8, then the rest
        self.assertEqual(cd.dispatch(self.ch, ME)["board"], 12 - cd.PER_PASS)
        self.assertEqual(cd.dispatch(self.ch, ME)["board"], 0)             # nothing twice
        fixed = cm.mission(self.ch, ME, "comp:1")["fixed"]
        self.assertTrue(all((t["ref"] or "").startswith("mw_task:") for t in fixed))
        self.assertEqual({t["why"]["state"] for t in fixed}, {"queued"})   # on the board, for its Director
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM mw_tasks", one=True)["n"], 12)
        self.assertIn("dispatched to the team's board", self.row(fixed[0]["id"])["history"])
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM og_audit WHERE action='control.task.dispatch' AND actor='AXoR'", one=True)["n"], 12)
        bid = int(fixed[0]["ref"].split(":")[1])
        self.db.q("UPDATE mw_tasks SET status='working' WHERE id=?", (bid,))
        self.db.q("UPDATE mw_tasks SET status='blocked' WHERE id=?", (bid + 1,))
        d = cm.missions(self.ch, ME)
        self.assertEqual(d["counts"]["in_progress"], 1)
        self.assertEqual(next(t for t in d["tasks"] if t["ref"] == f"mw_task:{bid + 1}")["why"]["state"], "waiting")

    def test_a_board_that_refuses_is_retried_then_named_stuck(self):
        cm.missions(self.ch, ME)
        def full(me, wid, b, actor=None): raise HTTPException(409, "A workspace holds at most 400 open tasks: finish, drop or delete some first.")
        with mock.patch.object(self.ch.w, "_add_task", full):
            out = cd.dispatch(self.ch, ME)
            self.assertEqual((out["board"], out["missed"]), (0, 12))
            t = next(t for t in cm.missions(self.ch, ME)["tasks"] if t["kind"] == "fixed")
            r = self.row(t["id"])
            self.assertEqual(r["attempts"], 1); self.assertGreater(r["next_try"], time.time())
            self.assertEqual(t["why"]["state"], "retry"); self.assertIn("400 open tasks", t["why"]["text"])
            self.assertEqual(cd.dispatch(self.ch, ME)["missed"], 0)       # waits for its next try
            for _ in range(cd.MAX_TRIES): cd.dispatch(self.ch, ME, now=time.time() + 10 * cd.RETRY_AFTER * cd.MAX_TRIES)
            t = next(x for x in cm.missions(self.ch, ME)["tasks"] if x["id"] == t["id"])
            self.assertEqual((self.row(t["id"])["attempts"], t["why"]["state"]), (cd.MAX_TRIES, "stuck"))
        d = cm.missions(self.ch, ME)["dispatch"]
        self.assertEqual(d["stuck"], 0)  # they've been stuck for minutes, not an hour yet
        self.assertEqual(cd.summary([dict(t, updated=time.time() - 2 * cd.STALE) for t in cm.missions(self.ch, ME)["tasks"] if t.get("why")])["stuck"], 12)

    def test_agent_tasks_start_a_restart_resumes_and_yours_wait_for_you(self):
        made = self.agent_task("Write the launch plan")                               # Mission Intelligence's, made with start=False
        back = self.agent_task("Summarize the week", origin="you", summary=cd.RESTARTED + ": in Hybrid and Auto mode AXoR starts it again.")
        mine = self.agent_task("Draft the FAQ", origin="you")                          # yours, unstarted on purpose
        out = cd.dispatch(self.ch, ME)
        self.assertEqual(out["agent"], 2)
        self.assertEqual((self.row(made)["status"], self.row(back)["status"], self.row(mine)["status"]), ("review", "review", "todo"))
        why = {t["id"]: t["why"] for t in cm.missions(self.ch, ME)["tasks"] if t.get("why")}
        self.assertEqual(why[mine]["state"], "manual"); self.assertIn("without starting it", why[mine]["text"])
        self.assertEqual(why[made]["state"], "review")

    def test_runs_at_once_and_the_daily_limit_hold_agent_tasks(self):
        a, b = self.agent_task("Write the launch plan"), self.agent_task("Write the FAQ")
        with mock.patch.object(self.ch, "_busy", lambda uid: control_hub.RUNS_PER_USER):
            self.assertEqual(cd.dispatch(self.ch, ME)["agent"], 0)
            self.assertEqual(next(t for t in cm.missions(self.ch, ME)["tasks"] if t["id"] == a)["why"]["state"], "busy")
        with mock.patch.object(control_hub, "_cap", lambda uid: 1000), mock.patch.object(control_hub, "_spent", lambda uid: 950):
            out = cd.dispatch(self.ch, ME)
            self.assertEqual(out["agent"], 0); self.assertIn("daily token limit", out["held"])
        self.assertEqual(cd.dispatch(self.ch, ME)["agent"], 2)

    def test_failures_outside_the_work_are_retried_limits_and_the_tasks_own_are_not(self):
        t = self.agent_task("Write the launch plan")
        fail = lambda why: self.db.q("UPDATE ctl_tasks SET status='failed', summary=?, updated=? WHERE id=?", (why, time.time(), t))
        fail("Model call timed out after 600 s")
        self.assertEqual(cd.dispatch(self.ch, ME)["retried"], 0)                    # retry 1 waits its backoff
        # G5-2 (Owner D-015 D2, clarification A): a timeout is an immediate transient retry, 30 s ± 20 % jitter (was RETRY_AFTER, 5 min)
        self.assertGreater(self.row(t)["next_try"], time.time() + 30 * 0.8 - 5)
        self.assertLess(self.row(t)["next_try"], time.time() + 30 * 1.2 + 5)
        out = cd.dispatch(self.ch, ME, now=time.time() + cd.RETRY_AFTER + 1)
        self.assertEqual(out["retried"], 1)
        self.assertEqual((self.row(t)["status"], self.row(t)["attempts"]), ("review", 1))
        fail("Over the agent token budget of Noor: 5,000 of 5,000 tokens (Intelligence layers → Budgets).")
        self.assertEqual(cd.dispatch(self.ch, ME)["retried"], 0)
        self.assertEqual(next(x for x in cm.missions(self.ch, ME)["tasks"] if x["id"] == t)["why"]["state"], "held")
        fail("The scoring code it was asked about doesn't exist.")
        self.assertEqual(cd.dispatch(self.ch, ME)["retried"], 0)
        self.assertEqual(next(x for x in cm.missions(self.ch, ME)["tasks"] if x["id"] == t)["why"]["state"], "failed")
        fail("Claude plan usage limit reached; resets at 18:00")                    # quota: an hour per try, not five minutes
        self.assertEqual(cd.dispatch(self.ch, ME)["retried"], 0)
        self.assertGreater(self.row(t)["next_try"], time.time() + 3000)
        fail("Model call timed out"); self.db.q("UPDATE ctl_tasks SET attempts=?, next_try=NULL WHERE id=?", (cd.MAX_TRIES, t))
        self.assertEqual(cd.dispatch(self.ch, ME, now=time.time() + 10 * cd.RETRY_AFTER)["retried"], 0)  # out of tries: yours
        self.db.q("UPDATE ctl_tasks SET attempts=0, updated=? WHERE id=?", (time.time() - 2 * cd.RECENT, t))
        self.assertEqual(cd.dispatch(self.ch, ME)["retried"], 0)                    # an old failure isn't revived

    def test_done_without_a_deliverable_is_a_failure_report_then_another_agent_tries(self):
        agent_core.init(self.db)
        try:
            self.hub.llm = EmptyLLM()
            t = self.ch.add_task(ME, control_hub.TaskIn(team=self.hs(), title="Write the launch plan", agent=self.key("Noor")))
            r = self.row(t["id"])
            self.assertEqual(r["status"], "needs_input"); self.assertTrue(r["summary"].startswith(cd.NO_DELIVERABLE))
            run = self.db.q("SELECT status, error FROM ac_runs WHERE ref=?", (f"ctl:t{t['id']}",), one=True)
            self.assertEqual(run["status"], "failed"); self.assertIn(cd.NO_DELIVERABLE, run["error"])
            self.assertEqual(next(x for x in cm.missions(self.ch, ME)["tasks"] if x["id"] == t["id"])["why"]["state"], "dispatch")
            self.hub.llm = FakeLLM()
            out = cd.dispatch(self.ch, ME)                                        # Noor is alone on the team: back to you, said so
            self.assertEqual(out["reassigned"], 0)
            w = next(x for x in cm.missions(self.ch, ME)["tasks"] if x["id"] == t["id"])["why"]
            self.assertEqual(w["state"], "waiting"); self.assertIn("Nobody else on the team", w["text"])
            self.o.apply(ME, "move_agent", {"key": self.key("Lena"), "unit_id": r["unit_id"]})
            self.ch._cache.clear()
            self.hub.llm = EmptyLLM()
            t = self.ch.add_task(ME, control_hub.TaskIn(team=self.hs(), title="Write the release notes", agent=self.key("Noor")))
            r = self.row(t["id"])
            self.hub.llm = FakeLLM()
            self.assertEqual(cd.dispatch(self.ch, ME)["reassigned"], 1)
            r2 = self.row(t["id"])
            self.assertEqual((r2["status"], r2["attempts"], r2["agent_key"]), ("review", 1, self.key("Lena")))
            self.assertIn("ended without a deliverable", r2["history"])
        finally:
            agent_core._core = None

    def test_the_tick_skips_manual_users(self):
        cm.missions(self.ch, ME)
        self.ch.set_mode(ME, control_hub.SettingsIn(mode="manual"))
        with mock.patch.object(cm, "_owner", lambda ch, uid: dict(ME)):
            self.assertEqual(cd.tick(self.ch), 0)
            self.ch.set_mode(ME, control_hub.SettingsIn(mode="hybrid"))
            self.assertEqual(cd.tick(self.ch), cd.PER_PASS)
        self.assertIsNotNone(cm.missions(self.ch, ME)["dispatch"]["last"])


class RunOutcomes(unittest.TestCase):
    def test_every_run_has_one_final_state(self):
        ts = agent_core.terminal_state
        self.assertEqual([ts("done", ""), ts("failed", "Model call timed out"), ts("failed", "boom"), ts("lost", ""), ts("failed", "Stopped by a server restart."),
                          ts("cancelled", ""), ts("stopped", ""), ts("running", ""), ts("weird", "")],
                         ["success", "timeout", "failed", "restarted", "restarted", "cancelled", "cancelled", "running", None])


if __name__ == "__main__":
    unittest.main()
