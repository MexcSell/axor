"""G5-2 Blocker A and B (Owner, 2026-11-11, before PR #5 merges): budget decisions that never fail open, and limits that
apply on every replica at once.

A. A budget decision has three states. ALLOW: verified, nothing refuses. REFUSE: a hard limit is reached (a budget hold).
   UNKNOWN: the decision couldn't be made (the database, a guard that throws, a ledger row that couldn't be opened): the work
   doesn't start or call, a verification hold keeps the error and time, and only a fresh ALLOW releases it. UNKNOWN is never
   the agent's failure and uses no retry. An acknowledged unlimited policy and an unset one still allow, as before.
B. Hard-limit decisions read the limits from the database every time: two Core instances (two replicas, each with its own
   memory) see a limit lowered, raised, deleted or recreated on the other one at the next check."""
import json, os, sys, threading, time, types, unittest
from unittest import mock

from app import agent_core, control_dispatch as cd, control_hub, llm, mining_autoloop, mining_work, orchestrator as o
from app.auth import AuthDB
from app.intel_layers import fail_class

sys.path.insert(0, os.path.dirname(__file__))
from test_budget_safety import OWNER, BoardFixture, spend  # noqa: E402
from test_control_hub import Base as HubBase  # noqa: E402
from test_mission_ref import WID  # noqa: E402
from test_organization import ME  # noqa: E402

OUTAGE = "could not connect to server: Connection timed out (usage limit of the pool reached, 503)"  # hostile text: other classes' words


class Flaky:
    """A database connection that can be taken down: what the budget reads see during an outage. Only the core's connection is
    wrapped, so the board can still write the hold (a total outage writes nothing and starts nothing: _kick can't read either)."""
    def __init__(self, db): self.inner, self.down = db, False
    def q(self, *a, **kw):
        if self.down: raise RuntimeError(OUTAGE)
        return self.inner.q(*a, **kw)
    def __getattr__(self, name): return getattr(self.inner, name)


class PerReplica:
    """agent_core._core for a test with several replicas in one process: each thread uses its own Core (its own memory)."""
    def __init__(self, default): self._tl, self._default = threading.local(), default
    def use(self, core): self._tl.core = core
    def __getattr__(self, name): return getattr(getattr(self._tl, "core", self._default), name)


class Classes(unittest.TestCase):
    def test_unknown_is_a_budget_hold_in_every_vocabulary_never_the_agents_fault(self):
        t = agent_core.VERIFY_STOP
        self.assertEqual(mining_autoloop.classify(t), "budget")                          # not quota, transient or provider: no retry used
        d = o.decide("failed", t)
        self.assertEqual((d["cls"], d["action"], d["retry"], d["agent_fault"]), ("budget", "hold", False, False))
        self.assertEqual(fail_class("failed", t), "budget")                              # the dispatcher's reading
        self.assertEqual(o.mission_class(t), "budget")                                   # Mission Control's: pause, not retry
        for word in ("connection", "timed out", "usage limit", "503", "401", "unavailable", "cancel"):
            self.assertNotIn(word, t.lower())                                            # the error itself is never in the text

    def test_the_hold_keeps_the_error_and_when(self):
        u = agent_core.unknown(RuntimeError(OUTAGE))
        self.assertEqual((u["decision"], u["release"]), ("UNKNOWN", "verify"))
        self.assertIn("Connection timed out", u["error"]); self.assertAlmostEqual(u["checked_at"], time.time(), delta=5)
        self.assertIn("couldn't be verified", mining_work._budget_note({**u, "held_at": time.time()}))


class Gateway(unittest.TestCase):
    """The model-call gateway (Core.over, llm._gate): UNKNOWN refuses the call."""
    def setUp(self):
        import tempfile
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        self.core = agent_core.init(self.db)
        self.flaky = Flaky(self.db); self.core.db = self.flaky

    def tearDown(self):
        agent_core.end("failed")
        agent_core._core = None; agent_core._guards.pop("test", None)
        self.dir.cleanup()

    def test_a_database_outage_during_a_model_call_check_refuses_the_call(self):
        self.core.set_limit(OWNER, "global", "*", 1_000_000, period="day")
        agent_core.begin("teams", OWNER, "task", ref="mwt:1")
        self.assertIsNone(agent_core.over())                                             # ALLOW: verified
        self.flaky.down = True
        self.assertEqual(agent_core.over(), agent_core.VERIFY_STOP)                      # UNKNOWN: refused, never None
        with self.assertRaises(llm.LLMError) as e: llm._gate()
        self.assertIn(agent_core.VERIFY, str(e.exception))
        self.flaky.down = False
        self.assertIsNone(agent_core.over())                                             # recovered: a fresh check allows

    def test_an_unset_or_unlimited_policy_allows_but_an_outage_is_not_authorization(self):
        agent_core.begin("teams", OWNER, "task", ref="mwt:1")
        self.assertEqual(self.core.policy(OWNER)["state"], "unset")
        self.assertIsNone(agent_core.over())                                             # unset: allowed, as before G5-2
        self.core.set_unlimited(OWNER, True, "owner")
        self.assertEqual(self.core.policy(OWNER)["state"], "unlimited")
        self.assertIsNone(agent_core.over())
        self.assertIsNone(agent_core.preflight(OWNER, "teams", team="comp:1"))           # acknowledged unlimited: ALLOW
        self.flaky.down = True
        self.assertEqual(agent_core.over(), agent_core.VERIFY_STOP)                      # unlimited doesn't excuse an unverified check
        self.assertTrue(agent_core.is_unknown(agent_core.preflight(OWNER, "teams", team="comp:1")))

    def test_a_guard_that_throws_is_unknown_not_allow(self):
        def broken(run): raise RuntimeError("team budget table locked")
        agent_core.register_guard("test", broken)
        agent_core.begin("teams", OWNER, "task", ref="mwt:1")
        self.assertEqual(agent_core.over(), agent_core.VERIFY_STOP)
        r = agent_core.preflight(OWNER, "teams", team="comp:1")
        self.assertEqual(r["decision"], "UNKNOWN"); self.assertIn("table locked", r["error"])

    def test_a_ledger_row_that_cant_be_opened_leaves_the_run_unverified(self):
        self.flaky.down = True
        self.assertIsNone(agent_core.begin("teams", OWNER, "task", ref="mwt:1"))         # begin() failed (the ledger never stops a run)...
        self.flaky.down = False
        self.assertEqual(agent_core.over(), agent_core.VERIFY_STOP)                      # ...but its model calls can't go out unmetered
        agent_core.end("failed")
        self.assertIsNone(agent_core.over())                                             # the marker goes with the run
        self.flaky.down = True; agent_core.begin("teams", OWNER, "review", ref="mw:7"); self.flaky.down = False
        agent_core.end("failed", ref="mw:7")                                             # closed by ref, as the board closes its runs
        self.assertIsNone(agent_core.over())

    def test_per_call_limits_that_cant_be_read_stop_the_run(self):
        self.core.set_limit(OWNER, "global", "*", None, per_call=5000)
        agent_core.begin("teams", OWNER, "task", ref="mwt:1")
        self.assertIsNone(agent_core.over())
        self.assertEqual(agent_core.call_cap(), 5000)                                    # from over()'s own read
        self.flaky.down = True
        self.assertEqual(agent_core.call_cap(), 5000)                                    # no second read for the same call
        agent_core.used(9000)                                                            # the ledger write fails (logged); the per-call
        self.assertIn("per-call token budget", agent_core.over())                        # check uses over()'s read, so the breach stands

    def test_alerts_that_fail_never_decide(self):
        self.core.set_cap(OWNER, 1000, "owner"); spend(self.db, 900)                     # 90%: a warn alert is due
        agent_core.begin("teams", OWNER, "task", ref="mwt:1")
        with mock.patch.object(self.core, "_threshold", side_effect=RuntimeError("push server down")):
            self.assertIsNone(agent_core.over())                                         # ALLOW: under the cap
            spend(self.db, 200)
            self.assertIn("daily token budget", agent_core.over())                       # REFUSE: over it


class BoardVerification(BoardFixture):
    def setUp(self):
        super().setUp()
        self.flaky = Flaky(self.db); self.core.db = self.flaky
        self.w._enqueue = mining_work.Work._enqueue.__get__(self.w)

    def info(self, tid): return json.loads(self.row(tid)["hold_info"] or "{}")

    def test_an_outage_during_preflight_holds_and_starts_nothing(self):
        tid = self.queued("Bench the candidate")
        self.flaky.down = True
        for _ in range(50): self.w._kick(WID)
        self.assertEqual((self.starts, self.runs()), ([], 0))                            # zero starts while UNKNOWN
        t, i = self.row(tid), self.info(tid)
        self.assertEqual((t["status"], t["hold"], i["decision"], i["kind"], i["release"]), ("todo", "budget", "UNKNOWN", "verify", "verify"))
        self.assertIn("Connection timed out", i["error"]); self.assertTrue(i["checked_at"])
        self.assertIn("couldn't be verified", t["note"]); self.assertIn("Not counted against the agent", t["note"])
        self.assertEqual((t["fails"], t["retries"]), (0, 0))
        self.flaky.down = False                                                          # recovery: a fresh ALLOW releases and starts it once
        self.w._kick(WID)
        self.assertEqual((self.row(tid)["hold"], self.starts), (None, [tid]))

    def test_unknown_turns_into_the_refusing_limit_once_it_can_be_read(self):
        tid = self.queued("Bench the candidate")
        self.flaky.down = True; self.w._kick(WID)
        self.flaky.down = False
        self.core.set_limit(OWNER, "global", "*", 100, period="total", label="Hard limit"); spend(self.db, 500)
        self.w._kick(WID)
        i = self.info(tid)
        self.assertEqual((self.row(tid)["hold"], i["decision"], i["scope"], i["release"]), ("budget", "REFUSE", "global", "raise"))
        self.assertEqual(self.starts, [])

    def test_a_run_refused_unverified_mid_task_holds_uncounted_and_restarts_once_after_allow(self):
        tid = self.queued("Bench the candidate")
        self.w._kick(WID)
        self.assertEqual(self.starts, [tid])
        self.flaky.down = True
        t = self.row(tid)
        self.assertTrue(self.loop.failed(tid, t["run_id"], agent_core.VERIFY_STOP, "failed"))  # handled: not counted
        self.db.q("UPDATE mw_runs SET status='failed', finished=? WHERE task_id=?", (time.time(), tid))
        t, i = self.row(tid), self.info(tid)
        self.assertEqual((t["status"], t["hold"], t["fails"], t["retries"], i["decision"]), ("todo", "budget", 0, 0, "UNKNOWN"))
        for _ in range(20): self.w._kick(WID)
        self.assertEqual(self.starts, [tid])                                             # no restart while UNKNOWN
        self.flaky.down = False
        self.w._kick(WID); self.w._kick(WID)
        self.assertEqual((self.starts.count(tid), self.row(tid)["hold"]), (2, None))     # exactly once after a fresh ALLOW

    def test_the_hold_survives_a_restart(self):
        tid = self.queued("Bench the candidate")
        self.flaky.down = True; self.w._kick(WID)
        self.core = agent_core.init(self.db)                                             # a new process: nothing in memory
        self.flaky = Flaky(self.db); self.core.db = self.flaky; self.flaky.down = True
        self.w._guarded = {}
        for _ in range(5): self.w._kick(WID)
        self.assertEqual((self.row(tid)["hold"], self.info(tid)["decision"], self.starts), ("budget", "UNKNOWN", []))
        self.flaky.down = False; self.w._kick(WID)
        self.assertEqual(self.starts, [tid])

    def test_the_director_cant_requeue_past_an_unknown(self):
        tid = self.queued("Held task")
        self.flaky.down = True; self.w._kick(WID)
        self.assertTrue(self.w._enqueue(tid, "Director: go on", hold_ok=True))
        for _ in range(10): self.w._kick(WID)
        self.assertEqual((self.row(tid)["hold"], self.starts), ("budget", []))

    def test_an_unreadable_owner_is_unknown(self):
        tid = self.queued("Held task")
        self.w.m._campaign = lambda cid: (_ for _ in ()).throw(RuntimeError(OUTAGE))
        self.w._kick(WID)
        self.assertEqual((self.info(tid)["decision"], self.starts), ("UNKNOWN", []))

    def test_unreadable_per_call_limits_never_release_a_per_call_hold(self):
        self.core.set_limit(OWNER, "team", f"comp:{WID}", None, period="day", per_call=5000)
        tid = self.queued("Big task"); self.w._kick(WID)
        err = "A single model call used 12,000 tokens, over the per-call token budget of 5,000 (team comp:3)."
        self.assertTrue(self.loop.failed(tid, self.row(tid)["run_id"], err, "failed"))
        self.db.q("UPDATE mw_runs SET status='failed', finished=? WHERE task_id=?", (time.time(), tid))
        time.sleep(0.01)
        self.core.set_limit(OWNER, "team", f"comp:{WID}", None, period="day", per_call=20000)
        with mock.patch.object(agent_core, "per_call_caps", return_value=None):         # can't be read: not "no per-call limit"
            for _ in range(5): self.w._kick(WID)
            self.assertEqual(self.row(tid)["hold"], "budget")
        self.w._kick(WID)
        self.assertIsNone(self.row(tid)["hold"])

    def test_a_review_doesnt_start_while_unknown_or_refused(self):
        tid = self.queued("Reviewed task")
        self.db.q("UPDATE mw_tasks SET status='checking', reviewer=1 WHERE id=?", (tid,))
        reviews = lambda: self.db.q("SELECT COUNT(*) n FROM mw_runs WHERE task_id=? AND kind='review'", (tid,), one=True)["n"]
        self.w._review = lambda t, rid: None
        self.flaky.down = True
        for _ in range(10): self.w._kick(WID)
        self.assertEqual((reviews(), self.row(tid)["status"]), (0, "checking"))         # UNKNOWN: no review run, re-checked each pass
        self.flaky.down = False
        self.core.set_limit(OWNER, "global", "*", 10, period="day"); spend(self.db, 100)
        for _ in range(10): self.w._kick(WID)
        self.assertEqual(reviews(), 0)                                                   # REFUSE: none either
        self.core.set_limit(OWNER, "global", "*", 10_000_000, period="day")
        self.w._kick(WID)
        self.assertEqual(reviews(), 1)                                                   # ALLOW: one review

    def test_a_board_with_only_held_tasks_is_checked_again_by_the_tick(self):
        tid = self.queued("Held task")
        self.flaky.down = True; self.w._kick(WID)
        self.flaky.down = False
        self.loop.ticked = 0
        self.loop.tick()                                                                 # nothing queued: the tick still kicks the board
        self.assertEqual(self.starts, [tid])

    def held_for_readiness(self, title="Needs Docker"):
        from app import mission_ops as mo
        tid = self.queued(title)
        self.db.q("UPDATE mw_tasks SET status='todo', hold='readiness', note='held' WHERE id=?", (tid,))
        mo._awaiting.clear(); self.addCleanup(mo._awaiting.clear)
        return tid, mo

    def test_a_task_held_while_axors_own_check_runs_is_released_by_the_tick_when_it_has_passed(self):
        """Found in staging, 2026-11-13: AXoR's own Docker check job passed in 12 s and the task it was held for stayed held."""
        tid, mo = self.held_for_readiness()
        mo._await(WID)                                                                   # AXoR started a check for this team
        self.w._readiness = lambda wid: ({}, [tid], {})                                  # its declared needs pass now
        self.loop.ticked = 0
        self.loop.tick()                                                                 # nothing queued, nothing running: the tick still kicks the board
        self.assertEqual((self.row(tid)["hold"], self.row(tid)["status"]), (None, "queued"))   # released on this pass
        self.loop.ticked = 0
        self.loop.tick()                                                                 # and started on the next (its budget check is per pass)
        self.assertEqual(self.starts, [tid])

    def test_a_readiness_hold_only_a_person_can_clear_is_not_retried_by_the_tick(self):
        tid, mo = self.held_for_readiness("Needs a private repository")
        asked = []
        self.w._readiness = lambda wid: (asked.append(wid), ({tid: "held"}, [], {}))[1]
        for _ in range(5): self.loop.ticked = 0; self.loop.tick()
        self.assertEqual((asked, self.starts, self.row(tid)["hold"]), ([], [], "readiness"))   # no check under way: nothing is probed at all
        mo._awaiting[WID] = [time.time() - 1, [time.time() - 1000]]                      # the waiting time is over
        self.loop.ticked = 0; self.loop.tick()
        self.assertEqual(asked, [])

    def test_a_kick_while_waiting_starts_nothing_that_still_fails_its_check(self):
        tid, mo = self.held_for_readiness()
        mo._await(WID)
        self.w._readiness = lambda wid: ({tid: "still unknown"}, [], {})
        for _ in range(3): self.loop.ticked = 0; self.loop.tick()
        self.assertEqual((self.starts, self.row(tid)["hold"], self.row(tid)["status"]), ([], "readiness", "todo"))

    def test_a_paused_teams_readiness_hold_is_left_alone(self):
        tid, mo = self.held_for_readiness()
        mo._await(WID); self.db.q("UPDATE mw_comps SET paused=1 WHERE id=?", (WID,))
        self.w._readiness = lambda wid: ({}, [tid], {})
        self.loop.ticked = 0; self.loop.tick()
        self.assertEqual((self.starts, self.row(tid)["hold"]), ([], "readiness"))


class DispatcherVerification(HubBase):
    def setUp(self):
        super().setUp()
        self.core = agent_core.init(self.db)
        self.ch.edit_fixed(ME, 1, control_hub.FixedPatch(target_rank=10))
        self.ch.set_mode(ME, control_hub.SettingsIn(mode="hybrid"))
        self.flaky = Flaky(self.db); self.core.db = self.flaky

    def tearDown(self):
        agent_core._core = None
        super().tearDown()

    def row(self, tid): return self.db.q("SELECT * FROM ctl_tasks WHERE id=?", (tid,), one=True)
    def runs(self, tid): return self.db.q("SELECT COUNT(*) n FROM ac_runs WHERE ref=?", (f"ctl:t{tid}",), one=True)["n"]

    def agent_task(self, title):
        t = self.ch.add_task(ME, control_hub.TaskIn(team=f"u:{next(u['id'] for u in self.o.view(ME)['units'] if u['name'] == 'Handshake')}",
                                                    title=title, agent=self.key("Noor"), start=False))
        self.db.q("UPDATE ctl_tasks SET origin='intelligence' WHERE id=?", (t["id"],))
        return t["id"]

    def test_unknown_dispatches_nothing_uses_no_attempt_and_recovers(self):
        t = self.agent_task("Write the launch plan")
        with mock.patch.object(control_hub, "_cap", return_value=None):                 # the near-limit hint reads the core too; not under test
            self.flaky.down = True
            for _ in range(10):
                out = cd.dispatch(self.ch, ME)
                self.assertEqual(out["agent"], 0)
            self.assertEqual(out.get("budget_unknown"), 1)
            r = self.row(t)
            self.assertEqual((self.runs(t), r["attempts"] or 0, r["status"]), (0, 0, "todo"))
            self.assertIn("couldn't be verified", r["summary"])
            hist = json.loads(r["history"])
            self.assertEqual(sum("verification failed" in h["what"] for h in hist), 1)  # one line with the error, not one per pass
            self.assertIn("Connection timed out", next(h["what"] for h in hist if "verification failed" in h["what"]))
            self.flaky.down = False
            self.assertEqual(cd.dispatch(self.ch, ME)["agent"], 1)                       # a fresh ALLOW: dispatched once
        self.assertEqual(self.runs(t), 1)

    def test_a_retry_is_checked_before_its_claim(self):
        t = self.agent_task("Write the launch plan")
        self.db.q("UPDATE ctl_tasks SET status='failed', summary='Request timed out', agent_key=?, attempts=1, updated=? WHERE id=?",
                  (self.key("Noor"), time.time() - 3600, t))
        with mock.patch.object(control_hub, "_cap", return_value=None), mock.patch.object(cd, "_decide", return_value={
                "retry": True, "action": "retry", "delay": 0, "retry_key": "transient:1", "cls": "transient", "max_tries": 3}):
            self.flaky.down = True
            out = cd.dispatch(self.ch, ME)
            self.assertEqual((out["retried"], out.get("budget_unknown")), (0, 1))
            r = self.row(t)
            self.assertEqual((r["attempts"], r["retry_claim"], self.runs(t)), (1, None, 0))  # no attempt used, no claim taken
            self.flaky.down = False
            self.assertEqual(cd.dispatch(self.ch, ME)["retried"], 1)


class TwoReplicas(BoardFixture):
    """Blocker B: two Core instances with their own memory on one database, as two web replicas. Both are built before any run
    (a Core marks open runs lost when it starts) and both have read the limits before the change (warm caches)."""
    def setUp(self):
        super().setUp()
        path = getattr(self.db, "path", None)
        self.A = agent_core.Core(AuthDB(path) if path else self.db)
        self.B = agent_core.Core(AuthDB(path) if path else self.db)
        self.proxy = PerReplica(self.B); agent_core._core = self.proxy

    def tearDown(self):
        agent_core._guards.pop("teams", None)
        super().tearDown()

    def scope(self): return dict(team=f"comp:{WID}", ref="mwt:1", agent_key="teams:2")
    def refused(self, core): return core.preflight(OWNER, "teams", **self.scope())

    def warm(self):
        for c in (self.A, self.B):
            c.limits(OWNER); c.cap(OWNER); self.refused(c)

    def test_lower_raise_delete_recreate_apply_on_the_other_replica_at_once(self):
        self.A.set_limit(OWNER, "global", "*", 1_000_000, period="day", label="Hard limit"); spend(self.db, 50_000)
        self.warm()
        self.assertIsNone(self.refused(self.B))                                          # 1: both loaded the original limit
        self.A.set_limit(OWNER, "global", "*", 10_000, period="day", label="Hard limit")  # 2: A lowers it
        r = self.refused(self.B)                                                         # 3-4: B enforces the new limit
        self.assertEqual((r["scope"], r["tokens"]), ("global", 10_000))
        self.A.set_limit(OWNER, "global", "*", 2_000_000, period="day", label="Hard limit")  # 5: A raises it
        self.assertIsNone(self.refused(self.B))                                          # 6: B sees the raise
        self.A.set_limit(OWNER, "global", "*", 10_000, period="day", label="Hard limit"); self.warm()
        self.assertIsNotNone(self.refused(self.B))
        lid = self.A.limits(OWNER)[0]["id"]
        self.assertTrue(self.A.drop_limit(OWNER, lid))                                   # 7: deleted on A...
        self.assertIsNone(self.refused(self.B))                                          # ...gone on B
        self.A.set_limit(OWNER, "global", "*", 5_000, period="day", label="Recreated")   # recreated on A...
        self.assertEqual(self.refused(self.B)["label"], "Recreated")                     # ...enforced on B

    def test_the_owner_cap_applies_on_the_other_replica_at_once(self):
        spend(self.db, 50_000); self.warm()
        self.A.set_cap(OWNER, 10_000, "owner")
        self.assertEqual(self.refused(self.B)["scope"], "owner_daily")
        self.A.set_cap(OWNER, None, "owner")
        self.assertIsNone(self.refused(self.B))

    def test_the_gateway_on_the_other_replica_sees_the_change_before_the_next_call(self):
        self.proxy.use(self.B)
        agent_core.begin("teams", OWNER, "task", ref="mwt:1", agent_key="teams:2")
        try:
            spend(self.db, 50_000)
            self.assertIsNone(agent_core.over())                                         # B's run: allowed, B has read the limits
            self.A.set_limit(OWNER, "global", "*", 10_000, period="day")                 # A lowers; the run's next call on B is refused
            self.assertIn("token budget", agent_core.over() or "")
            self.A.set_limit(OWNER, "global", "*", 10_000_000, period="day")
            self.assertIsNone(agent_core.over())
        finally:
            agent_core.end("failed")

    def test_a_team_budget_lowered_on_one_replica_applies_on_the_other(self):
        path = getattr(self.db, "path", None)
        w2 = object.__new__(mining_work.Work)                                            # the second replica's board: its own connection
        w2.db, w2._guarded, w2.m = AuthDB(path) if path else self.db, {}, self.w.m
        w2._label, w2.day_tokens = self.w._label, mining_work.Work.day_tokens.__get__(w2)
        w2._flying = mining_work.Work._flying.__get__(w2)
        agent_core.register_guard("teams", mining_work.Work._budget_guard.__get__(w2))
        self.db.q("UPDATE mw_comps SET budget=1000000 WHERE id=?", (WID,))
        self.db.q("INSERT INTO mw_runs (comp_id, task_id, agent_id, kind, status, started, tokens) VALUES (?,?,?,?,?,?,?)",
                  (WID, 1, 2, "task", "done", time.time(), 50_000))
        run = {"system": "teams", "team": f"comp:{WID}", "id": 1}
        self.assertIsNone(w2._budget_guard(run))                                         # the gateway memo is warm with the old budget
        self.db.q("UPDATE mw_comps SET budget=1000 WHERE id=?", (WID,))                  # the team's budget lowered on replica A
        self.assertIn("24-hour token budget", w2._budget_guard(run) or "")              # the memo is keyed by the budget it was made for
        self.assertEqual(self.refused(self.B)["scope"], "guard:teams")

    def test_both_replicas_dispatching_at_once_start_nothing_after_a_lower_then_exactly_once_after_a_raise(self):
        self.A.set_limit(OWNER, "global", "*", 1_000_000, period="day", label="Hard limit"); spend(self.db, 50_000)
        self.warm()
        tid = self.queued("Bench the candidate")
        self.A.set_limit(OWNER, "global", "*", 10_000, period="day", label="Hard limit")
        lock = threading.Lock()
        self.w.pool = types.SimpleNamespace(submit=lambda fn, *a: (lock.acquire(), self.starts.append(a[0]), lock.release())
                                            if getattr(fn, "__name__", "") == "_work" else fn(*a))
        def passes(core, go, n):
            self.proxy.use(core); go.wait()
            for _ in range(n): self.w._kick(WID)
        go = threading.Barrier(2)
        th = [threading.Thread(target=passes, args=(c, go, 25)) for c in (self.A, self.B)]
        for x in th: x.start()
        for x in th: x.join(30)
        self.assertEqual((self.starts, self.runs(), self.row(tid)["hold"]), ([], 0, "budget"))  # zero unauthorized starts, one hold
        self.A.set_limit(OWNER, "global", "*", 10_000_000, period="day", label="Hard limit")
        go = threading.Barrier(2)
        th = [threading.Thread(target=passes, args=(c, go, 5)) for c in (self.B, self.A)]
        for x in th: x.start()
        for x in th: x.join(30)
        self.assertEqual((self.starts, self.runs()), ([tid], 1))                         # released and started exactly once


if __name__ == "__main__":
    unittest.main()
