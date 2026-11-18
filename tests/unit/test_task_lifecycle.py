"""task_lifecycle.py + the dispatcher's recovery: the 11-10 review's acceptance cases for the Control Hub's Task dispatch.

"15 open tasks, 0 under way, 3 not dispatched after an hour, 0 retried or reassigned, and the Mission engine says 0 open
missions". Each test is one of the review's cases: 1 a healthy agent executes, 2 an unavailable agent means someone else,
3 a failed dispatch is retried with a growing wait, 4 a run that stops answering times out and runs again (its late end is
discarded), 5 an empty or unfinished deliverable is rejected and corrected, 6 nothing runs twice, 7 a spent budget stops
safely, 8 a success comes with a checked result, 9 missions and tasks reconcile."""
import json, os, sys, time, unittest
from unittest import mock

from fastapi import HTTPException

from app import agent_core, control_dispatch as cd, control_hub, control_missions as cm, task_lifecycle as tl

sys.path.insert(0, os.path.dirname(__file__))
from test_control_hub import Base, FakeLLM  # noqa: E402
from test_organization import ME  # noqa: E402


class SaysItLater(FakeLLM):
    """An agent that answers "done" with a promise instead of the work."""
    def structured(self, model, system, prompt, schema, name, on_usage=None, effort="low", messages=None):
        if name != "task": return super().structured(model, system, prompt, schema, name, on_usage, effort, messages)
        self.calls.append({"prompt": prompt, "schema": name})
        if on_usage: on_usage(40)
        return {"status": "done", "result": "I will write the launch plan tomorrow once the data is in.", "summary": "planned"}


class Empty(FakeLLM):
    def structured(self, model, system, prompt, schema, name, on_usage=None, effort="low", messages=None):
        if name != "task": return super().structured(model, system, prompt, schema, name, on_usage, effort, messages)
        return {"status": "done", "result": " - ", "summary": "done"}


class Idle:
    """A worker pool that never runs anything: a run that was started and never heard from again."""
    def __init__(self): self.jobs = []
    def submit(self, fn, *a, **kw): self.jobs.append((fn, a, kw))


class Lifecycle(Base):
    def setUp(self):
        super().setUp()
        agent_core.init(self.db)
        self.ch.edit_fixed(ME, 1, control_hub.FixedPatch(target_rank=10))
        self.ch.set_mode(ME, control_hub.SettingsIn(mode="hybrid"))

    def tearDown(self):
        agent_core._core = None
        super().tearDown()

    def hs(self): return f"u:{next(u['id'] for u in self.o.view(ME)['units'] if u['name'] == 'Handshake')}"
    def row(self, tid): return self.db.q("SELECT * FROM ctl_tasks WHERE id=?", (tid,), one=True)
    def agent_task(self, title, who="Noor", origin="intelligence"):
        t = self.ch.add_task(ME, control_hub.TaskIn(team=self.hs(), title=title, agent=self.key(who), start=False))
        self.db.q("UPDATE ctl_tasks SET origin=? WHERE id=?", (origin, t["id"]))
        return t["id"]
    def exec_row(self, tid): return next(x for x in tl.execution(self.ch, ME)["tasks"] if x["id"] == tid)

    # 1
    def test_1_a_healthy_agent_receives_executes_and_its_result_waits_checked_for_you(self):
        t = self.agent_task("Write the launch plan")
        self.assertEqual(self.exec_row(t)["stage"], "QUEUED")
        self.assertEqual(cd.dispatch(self.ch, ME)["agent"], 1)
        r = self.row(t)
        self.assertEqual(r["status"], "review")                                   # delivered, not completed: you accept it
        self.assertTrue(json.loads(r["verify"])["ok"])
        self.assertEqual(self.exec_row(t)["stage"], "VERIFYING")
        run = self.db.q("SELECT status FROM ac_runs WHERE ref=?", (f"ctl:t{t}",), one=True)
        self.assertEqual(run["status"], "done")
        self.ch.patch_task(ME, t, control_hub.TaskPatch(status="done"))
        self.assertEqual(tl.trace(self.ch, ME, t)["stage"], "COMPLETED")

    # 2
    def test_2_an_unavailable_agent_means_another_one_then_a_supporting_team(self):
        t = self.agent_task("Write the launch plan")
        self.db.q("UPDATE ctl_tasks SET agent_key=NULL WHERE id=?", (t,))          # Mission Intelligence's: no agent named, AXoR picks
        r = self.row(t)
        noor = self.key("Noor")
        self.assertEqual(tl.pick(self.ch, ME, r)[0], noor)
        with mock.patch.object(tl, "_failing", lambda db, key, now: key == noor):   # Noor's model is failing right now
            c = {a["key"]: a for a in tl.candidates(self.ch, ME, r)}
            self.assertFalse(c[noor]["eligible"]); self.assertIn("failing", c[noor]["why_not"])
            # a supporting team on the task's mission is next
            self.db.q("UPDATE ctl_tasks SET mission='comp:1' WHERE id=?", (t,))
            lena = self.key("Lena")
            lena_unit = next(a["unit_id"] for a in self.o.view(ME)["agents"] if a["key"] == lena)
            self.db.q("INSERT INTO ctl_mission_teams (user_id, mission, unit_id, duty, added) VALUES (7, 'comp:1', ?, 'helps', ?)", (lena_unit, time.time()))
            key, note = tl.pick(self.ch, ME, self.row(t))
            self.assertNotEqual(key, noor)
            out = cd.dispatch(self.ch, ME)
            self.assertEqual(out["agent"], 1)
            self.assertNotEqual(self.row(t)["agent_key"], noor)
        # the monitor's Reassign: AXoR picks someone other than the current agent
        t2 = self.agent_task("Write the FAQ")
        self.db.q("UPDATE ctl_tasks SET status='failed', summary='The scoring code it was asked about doesn''t exist.', updated=? WHERE id=?", (time.time(), t2))
        self.o.apply(ME, "move_agent", {"key": self.key("Lena"), "unit_id": self.row(t2)["unit_id"]}); self.ch._cache.clear()
        d = tl.reassign(self.ch, ME, t2, tl.ReassignIn())
        self.assertEqual(self.row(t2)["agent_key"], self.key("Lena"))
        self.assertEqual(d["task"]["status"], "review")
        self.assertIn("reassigned to Lena", self.row(t2)["history"])

    # 3
    def test_3_a_failed_dispatch_is_retried_with_a_growing_wait_then_escalated_once(self):
        cm.missions(self.ch, ME)
        sent = []
        agent_core.set_notifier(lambda *a: sent.append(a))
        try:
            def full(me, wid, b, actor=None): raise HTTPException(409, "A workspace holds at most 400 open tasks.")
            with mock.patch.object(self.ch.w, "_add_task", full):
                now = time.time()
                cd.dispatch(self.ch, ME, now)
                t = self.db.q("SELECT * FROM ctl_tasks WHERE kind='fixed' ORDER BY id LIMIT 1", one=True)
                self.assertEqual(t["attempts"], 1); self.assertAlmostEqual(t["next_try"] - time.time(), cd.RETRY_AFTER, delta=30)
                self.assertIn("400 open tasks", t["summary"])  # the board's 409, not a stub's TypeError (PX-R12)
                cd.dispatch(self.ch, ME, t["next_try"] + 1)
                t = self.row(t["id"])
                self.assertEqual(t["attempts"], 2); self.assertAlmostEqual(t["next_try"] - time.time(), 2 * cd.RETRY_AFTER, delta=30)  # 5 min, then 10
                self.assertEqual(self.exec_row(t["id"])["stage"], "QUEUED")
                cd.dispatch(self.ch, ME, t["next_try"] + 1)
                self.assertEqual(self.row(t["id"])["attempts"], cd.MAX_TRIES)
            x = self.exec_row(t["id"])
            self.assertIn("Couldn't be dispatched", x["dead"])
            n = self.db.q("SELECT COUNT(*) n FROM og_audit WHERE action='control.task.escalate' AND target=?", (f"ctl:t{t['id']}",), one=True)["n"]
            self.assertEqual(n, 1); self.assertTrue(sent)
            cd.dispatch(self.ch, ME)                                              # once a day, not every pass
            self.assertEqual(self.db.q("SELECT COUNT(*) n FROM og_audit WHERE action='control.task.escalate' AND target=?", (f"ctl:t{t['id']}",), one=True)["n"], 1)
            d = tl.retry(self.ch, ME, t["id"])                                     # the monitor's Retry: a clean count, onto the board
            self.assertEqual((self.row(t["id"])["attempts"], d["stage"]), (0, "DISPATCHED"))
        finally:
            agent_core.set_notifier(None)

    # 4
    def test_4_a_run_that_stops_answering_times_out_runs_again_and_its_late_end_is_discarded(self):
        t = self.agent_task("Write the launch plan")
        self.ch.pool = Idle()
        self.assertEqual(cd.dispatch(self.ch, ME)["agent"], 1)
        self.assertEqual((self.row(t)["status"], self.exec_row(t)["stage"]), ("running", "DISPATCHED"))   # started, no worker yet
        self.assertEqual(tl.watchdog(self.db, time.time() + 60), [])                                      # not yet
        later = time.time() + tl.RUN_TIMEOUT + 5
        self.assertEqual(tl.watchdog(self.db, later), [t])
        r = self.row(t)
        self.assertEqual(r["status"], "failed"); self.assertTrue(r["summary"].startswith(tl.TIMED_OUT))
        self.assertEqual(self.exec_row(t)["stage"], "TIMEOUT")
        self.assertEqual(cd._cls(r["summary"]), "transient")                                              # the retry policy's
        from test_control_hub import Sync
        self.ch.pool = Sync()
        out = cd.dispatch(self.ch, ME, later + cd.RETRY_AFTER + 1)
        self.assertEqual(out["retried"], 1); self.assertEqual(self.row(t)["status"], "review")
        # a run whose task was timed out and restarted meanwhile: its end changes nothing
        t2 = self.agent_task("Write the FAQ")
        class Slow(FakeLLM):
            def structured(s, model, system, prompt, schema, name, on_usage=None, effort="low", messages=None):
                if name == "task": self.db.q("UPDATE ctl_tasks SET run_key='newer' WHERE id=?", (t2,))  # the watchdog + a retry, mid-call
                return super().structured(model, system, prompt, schema, name, on_usage, effort, messages)
        self.hub.llm = Slow()
        self.ch._start_task(ME, t2)
        r2 = self.row(t2)
        self.assertEqual((r2["status"], r2["result"]), ("running", None))

    # 5
    def test_5_an_empty_or_promised_deliverable_is_rejected_and_sent_back_for_a_correction(self):
        self.hub.llm = Empty()
        t = self.ch.add_task(ME, control_hub.TaskIn(team=self.hs(), title="Write the launch plan", agent=self.key("Noor")))["id"]
        self.assertTrue(self.row(t)["summary"].startswith(cd.NO_DELIVERABLE))
        self.assertEqual(self.exec_row(t)["stage"], "BLOCKED")
        self.hub.llm = SaysItLater()
        t = self.ch.add_task(ME, control_hub.TaskIn(team=self.hs(), title="Write the FAQ", agent=self.key("Noor")))["id"]
        r = self.row(t)
        self.assertEqual(r["status"], "needs_input"); self.assertTrue(r["summary"].startswith(tl.FAILED_CHECK))
        rep = json.loads(r["verify"]); self.assertFalse(rep["ok"]); self.assertIn("promise", rep["why"])
        self.assertEqual(self.db.q("SELECT status FROM ac_runs WHERE ref=? ORDER BY id DESC", (f"ctl:t{t}",), one=True)["status"], "failed")
        why = next(x for x in cm.missions(self.ch, ME)["tasks"] if x["id"] == t)["why"]
        self.assertEqual(why["state"], "dispatch"); self.assertIn("checks", why["text"])
        self.hub.llm = FakeLLM()
        out = cd.dispatch(self.ch, ME)
        self.assertEqual(out["corrected"], 1)
        r = self.row(t)
        self.assertEqual((r["status"], r["attempts"]), ("review", 1))
        self.assertIn("promise", self.hub.llm.calls[-1]["prompt"])               # the checks' notes went back with it

    # 6
    def test_6_nothing_runs_twice(self):
        t = self.agent_task("Write the launch plan")
        self.ch.pool = Idle()
        self.ch._start_task(ME, t)
        with self.assertRaises(HTTPException) as e: self.ch._start_task(ME, t)
        self.assertEqual(e.exception.status_code, 409)
        self.assertEqual(len(self.ch.pool.jobs), 1)
        self.db.q("UPDATE ctl_tasks SET status='failed', summary='Model call timed out', updated=? WHERE id=?", (time.time() - 3600, t))
        real = self.ch._start_task
        def raced(me, tid, feedback=""):  # you clicked Run between the pass's read and its start
            self.db.q("UPDATE ctl_tasks SET status='running' WHERE id=?", (tid,)); return real(me, tid, feedback)
        with mock.patch.object(self.ch, "_start_task", raced):
            out = cd.dispatch(self.ch, ME, time.time() + 10 * cd.RETRY_AFTER)
        self.assertEqual((out["retried"], out["missed"]), (0, 0))
        self.assertEqual(len(self.ch.pool.jobs), 1)
        # a board dispatch that stopped between making the board task and linking it is linked, not made twice
        cm.missions(self.ch, ME)
        r = self.db.q("SELECT * FROM ctl_tasks WHERE kind='fixed' ORDER BY id LIMIT 1", one=True)
        cd._note(self.ch, r, tl.DISPATCHING, {})
        self.ch.w.add_task(ME, 1, cm.mining_work.TaskIn(title=r["title"], priority="high"))
        before = self.db.q("SELECT COUNT(*) n FROM mw_tasks", one=True)["n"]
        cd.dispatch(self.ch, ME)
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM mw_tasks WHERE title=?", (r["title"],), one=True)["n"],
                         self.db.q("SELECT COUNT(*) n FROM ctl_tasks WHERE title=? AND ref LIKE 'mw_task:%'", (r["title"],), one=True)["n"])
        self.assertTrue(self.row(r["id"])["ref"].startswith("mw_task:"))
        self.assertLess(self.db.q("SELECT COUNT(*) n FROM mw_tasks", one=True)["n"] - before, 12)

    # 7
    def test_7_a_spent_budget_stops_safely(self):
        t = self.agent_task("Write the launch plan")
        with mock.patch.object(control_hub, "_cap", lambda uid: 1000), mock.patch.object(control_hub, "_spent", lambda uid: 990):
            out = cd.dispatch(self.ch, ME)
        self.assertEqual(out["agent"], 0); self.assertIn("daily token limit", out["held"])
        self.assertEqual(self.row(t)["status"], "todo")
        self.db.q("UPDATE ctl_tasks SET status='failed', summary=?, updated=? WHERE id=?",
                  ("Over the agent token budget of Noor: 5,000 of 5,000 tokens.", time.time(), t))
        self.assertEqual(cd.dispatch(self.ch, ME, time.time() + 10 * cd.RETRY_AFTER)["retried"], 0)  # a limit is a decision
        self.assertEqual(self.exec_row(t)["why"]["state"], "held")

    # 8
    def test_8_a_success_comes_with_a_checked_result_and_named_outputs(self):
        t = self.agent_task("Write the launch plan")
        tl.set_contract(self.ch, ME, t, tl.ContractIn(accept="Covers the launch date\nNames an owner", outputs="launch-plan.md"))
        cd.dispatch(self.ch, ME)
        r = self.row(t)
        self.assertEqual(r["status"], "needs_input")                              # "the work" doesn't name launch-plan.md
        self.assertIn("launch-plan.md", json.loads(r["verify"])["why"])

        class Good(FakeLLM):
            def structured(s, model, system, prompt, schema, name, on_usage=None, effort="low", messages=None):
                if name == "verify":
                    if on_usage: on_usage(30)
                    return {"criteria": [{"criterion": "Covers the launch date", "met": True, "evidence": "May 4"},
                                         {"criterion": "Names an owner", "met": True, "evidence": "Noor"}], "feedback": ""}
                if name == "task": return {"status": "done", "result": "launch-plan.md: launch May 4, owner Noor.", "summary": "plan"}
                return super().structured(model, system, prompt, schema, name, on_usage, effort, messages)
        self.hub.llm = Good()
        with mock.patch.object(tl, "VERIFY_MODEL", True):
            out = cd.dispatch(self.ch, ME)
        self.assertEqual(out["corrected"], 1)
        d = tl.trace(self.ch, ME, t)
        self.assertEqual(d["stage"], "VERIFYING")
        self.assertTrue(d["verify"]["ok"]); self.assertEqual(d["verify"]["by"], "model")
        self.assertTrue(all(c["met"] for c in d["verify"]["criteria"]))
        self.assertIn("launch-plan.md", d["task"]["result"])

    # 9
    def test_9_missions_and_tasks_reconcile_from_the_same_records(self):
        d = cm.missions(self.ch, ME)
        x = tl.execution(self.ch, ME)
        rc = x["reconcile"]
        self.assertEqual(rc["missions_open"]["predefined"], 3)                  # the competitions are open missions too
        self.assertEqual(rc["tasks_open"], d["counts"]["tasks_open"])
        self.assertEqual(x["counts"]["open"], d["counts"]["tasks_open"])
        self.assertEqual(sum(rc["tasks_by_mission"].values()), rc["tasks_open"])
        self.assertEqual(rc["orphans"], [])
        self.db.q("UPDATE mw_comps SET status='closed' WHERE id=2")              # a team closed with its tasks still open
        rc = tl.reconcile(self.ch, ME)
        self.assertEqual(rc["missions_open"]["predefined"], 2)
        self.assertEqual({o["mission"] for o in rc["orphans"]}, {"comp:2"})
        self.assertEqual(sum(x["n"] for x in tl.execution(self.ch, ME)["stages"]), len(tl.execution(self.ch, ME)["tasks"]))

    def test_an_unclaimed_board_task_goes_to_the_least_loaded_agent_once(self):
        cm.missions(self.ch, ME)
        cd.dispatch(self.ch, ME); cd.dispatch(self.ch, ME)
        given = []
        def assign(me, bid, b):
            given.append((bid, b.agent)); self.db.q("UPDATE mw_tasks SET agent_id=? WHERE id=?", (b.agent, bid))
        self.ch.w.update_task = assign
        self.assertEqual(cd.dispatch(self.ch, ME)["claimed"], 0)                 # not yet
        out = cd.dispatch(self.ch, ME, time.time() + tl.CLAIM_TIMEOUT + 60)
        self.assertEqual(out["claimed"], 12)
        comp1 = [a for bid, a in given if self.db.q("SELECT comp_id FROM mw_tasks WHERE id=?", (bid,), one=True)["comp_id"] == 1]
        self.assertEqual(comp1[0], 2)                                            # Rex before Dora, the Director, at equal load
        self.assertEqual(sorted(comp1), [1, 1, 2, 2])                           # then spread by load
        x = next(t for t in tl.execution(self.ch, ME)["tasks"] if t["route"] == "board")
        self.assertEqual(x["stage"], "CLAIMED")
        given.clear()
        self.db.q("UPDATE mw_tasks SET agent_id=NULL")
        self.assertEqual(cd.dispatch(self.ch, ME, time.time() + tl.CLAIM_TIMEOUT + 60)["claimed"], 0)  # once per task

    def test_an_invalid_contract_is_blocked_with_the_reason_never_retried(self):
        t = self.agent_task("Write the launch plan")
        self.db.q("UPDATE ctl_tasks SET agent_key='teams:999' WHERE id=?", (t,))  # an agent who's gone
        out = cd.dispatch(self.ch, ME)
        self.assertEqual((out["blocked"], out["agent"]), (1, 0))
        r = self.row(t)
        self.assertTrue(r["summary"].startswith(tl.INVALID)); self.assertEqual(r["attempts"], cd.MAX_TRIES)
        x = self.exec_row(t)
        self.assertTrue(x["dead"]); self.assertEqual(x["why"]["state"], "stuck")
        self.assertEqual(cd.dispatch(self.ch, ME)["blocked"], 0)                 # once
        d = tl.reassign(self.ch, ME, t, tl.ReassignIn(agent=self.key("Noor")))  # fixed by giving it to someone who's there
        self.assertFalse((self.row(t)["summary"] or "").startswith(tl.INVALID))
        self.assertEqual((d["task"]["status"], d["dead"]), ("review", None))


class Stage(unittest.TestCase):
    def test_dispatched_is_not_running_and_running_is_not_completed(self):
        b = {"ref": "mw_task:3", "route": "board"}
        self.assertEqual(tl.stage({"status": "todo", "board_status": "todo", "board_agent": None}, b)[0], "DISPATCHED")
        self.assertEqual(tl.stage({"status": "todo", "board_status": "todo", "board_agent": 4}, b)[0], "CLAIMED")
        self.assertEqual(tl.stage({"status": "running", "board_status": "working"}, b)[0], "RUNNING")
        self.assertEqual(tl.stage({"status": "running", "board_status": "checking"}, b)[0], "VERIFYING")
        self.assertEqual(tl.stage({"status": "done"}, b)[0], "COMPLETED")
        a = {"ref": None, "route": "agent"}
        self.assertEqual(tl.stage({"status": "running"}, a)[0], "DISPATCHED")
        self.assertEqual(tl.stage({"status": "running"}, a, {"status": "running"})[0], "RUNNING")
        self.assertEqual(tl.stage({"status": "review"}, a)[0], "SUBMITTED")
        self.assertEqual(tl.stage({"status": "review"}, {**a, "verify": json.dumps({"ok": True})})[0], "VERIFYING")
        self.assertEqual(tl.stage({"status": "failed"}, {**a, "summary": tl.TIMED_OUT + " after 45 min"})[0], "TIMEOUT")

    def test_backoff_doubles_and_is_capped(self):
        self.assertEqual([tl.backoff(300, n) for n in (1, 2, 3)], [300, 600, 1200])
        self.assertEqual(tl.backoff(3600, 10), tl.BACKOFF_MAX)


if __name__ == "__main__":
    unittest.main()
