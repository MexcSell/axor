"""D1 (2026-11-14 staging runaway: 9,264 empty runs, web at 100% CPU): agent_core.preflight released budget-held tasks that the
gateway then refused at once. The team bucket's in-flight stop is HARD_PCT (110%) of the budget and the gateway adds the first
call's reservation; preflight checked with estimate 0. At 156,291 of a 150,000 budget (stop 165,000) with an 11,545 reservation,
preflight said ALLOW, the gateway REFUSE, the hold's fallback record said nothing, and the next board pass released it again.

Fixed: preflight reserves the gateway's own estimate (estimate_start), new work stops at the team's START line (100%), and a task
re-held right after its release backs off before the next release. Tests follow the directive's list (1-10)."""
import json, os, sys, threading, time, unittest

from app import agent_core, control_dispatch as cd, mining_work

sys.path.insert(0, os.path.dirname(__file__))
from test_budget_safety import BoardFixture, OWNER, spend  # noqa: E402
from test_mission_ref import ME, WID  # noqa: E402
from test_task_lifecycle import Lifecycle  # noqa: E402

TEAM = f"comp:{WID}"
MODEL = "terminal:fable"
RESERVATION = 11_545  # the incident's reservation


def history(db, actual=RESERVATION, n=20, model=MODEL, owner=OWNER):
    """Settled calls on record, so the gateway's estimate_call (90th percentile) is `actual`, as in the incident."""
    for i in range(n):
        db.q("""INSERT INTO ac_reservations (owner_id, run_id, rkey, model, estimate, reserved, bound, actual, state, created, expires, settled)
                VALUES (?,?,?,?,?,?,?,?,'settled',?,?,?)""", (owner, None, f"h{model}{actual}{i}{time.time()}", model, actual, actual, None, actual,
                                                                time.time(), time.time() + 60, time.time()))


class TeamBudget(BoardFixture):
    """The board with the team's own budget registered as in production (mining_work.Work.__init__)."""
    def setUp(self):
        super().setUp()
        self.w._guarded = {}
        agent_core.register_guard("teams", self.w._budget_guard)
        agent_core.register_bucket("teams", self.w._budget_bucket)
        self.budget(150_000)
        history(self.db)
        for a in (1, 2):  # each agent's last metered run names its model (what _start_model reads), as in staging
            self.db.q("INSERT INTO ac_runs (system, owner_id, agent_key, kind, status, tokens, model, started, team) VALUES ('teams',?,?,'task','done',0,?,?,?)",
                      (OWNER, f"teams:{a}", MODEL, time.time() - 90_000, TEAM))

    def tearDown(self):
        agent_core._guards.pop("teams", None); agent_core._buckets.pop("teams", None)
        super().tearDown()

    def budget(self, n): self.db.q("UPDATE mw_comps SET budget=? WHERE id=?", (n, WID))

    def gateway(self, tid):
        """The first model call of this task's run, through the real gateway (begin + admit with the run's model): None = admitted."""
        agent_core.begin("teams", OWNER, "task", ref=f"mwt:{tid}", agent_key="teams:2", model=MODEL)
        try:
            agent_core._local.run.update({"team": TEAM, "corr": TEAM})
            return agent_core.admit(model=MODEL)
        finally:
            agent_core.call_failed(None)
            agent_core.end("failed")

    def drive(self, tid, passes=50):
        """Board passes as in staging: each start goes to the gateway; a refused start fails through the Autoloop's handler (what
        the run does when its first call is refused) and the run is closed. Returns the number of starts."""
        n0 = len(self.starts)
        for _ in range(passes):
            self.w._kick(WID)
            while len(self.starts) > n0:
                n0 += 1
                why = self.gateway(tid)
                t = self.row(tid)
                if why:
                    self.loop.failed(tid, t["run_id"], why, "failed")
                self.db.q("UPDATE mw_runs SET status=?, finished=? WHERE id=?", ("failed" if why else "done", time.time(), t["run_id"]))
        return len(self.starts)


class Incident(TeamBudget):
    def test_1_2_3_the_incident_state_holds_persistently_with_zero_starts(self):
        spend(self.db, 156_291, team=TEAM)                                   # the exact state of 04:22 UTC
        tid = self.queued("Build a repeatable clean-run harness")
        self.assertEqual(self.drive(tid, 50), 0)                             # 50 board passes: no start at all
        t = self.row(tid)
        info = json.loads(t["hold_info"])
        self.assertEqual((t["status"], t["hold"]), ("todo", "budget"))       # 1. a persistent budget hold
        self.assertEqual(info["scope"], "guard:teams")
        self.assertEqual(self.runs(), 0)
        for _ in range(10): self.loop.tick()                                 # 3. the Autoloop's tick re-kicks held boards: still nothing
        self.assertEqual((len(self.starts), self.row(tid)["hold"]), (0, "budget"))

    def test_the_band_under_the_gateway_line_is_refused_by_the_reservation(self):
        # past the budget the start is refused outright; just under the gateway's line, the first call's reservation can't fit either
        self.budget(1_000_000)
        spend(self.db, 1_100_000 - RESERVATION + 1, team=TEAM)
        tid = self.queued("Benchmark C1")
        self.assertEqual(self.drive(tid, 50), 0)
        self.assertEqual(self.row(tid)["hold"], "budget")

    def test_under_the_budget_work_the_gateway_admits_starts(self):
        # below 100%, a first call that fits under the gateway's line starts (review finding: no stall the gateway wouldn't make)
        self.budget(1_000_000)
        spend(self.db, 1_000_000 - RESERVATION + 1, team=TEAM)
        tid = self.queued("Benchmark C1")
        self.assertEqual(self.drive(tid, 3), 1)
        self.assertIsNone(self.row(tid)["hold"])

    def test_a_small_budget_with_a_large_call_estimate_is_not_stalled(self):
        # review probe A: budget 10,000, the model's p90 10,500 (gateway line 11,000): the gateway admits, so the board starts it
        self.db.q("DELETE FROM ac_reservations"); history(self.db, actual=10_500)
        self.budget(10_000)
        tid = self.queued("Small team")
        self.assertIsNone(agent_core.preflight(OWNER, "teams", model=MODEL, **self.w._budget_scope(WID, self.row(tid))))
        self.assertEqual(self.drive(tid, 3), 1)

    def test_another_models_big_calls_dont_starve_a_small_team(self):
        # review probe B: the owner's other model makes 60,000-token calls; this team's model reserves 3,000
        self.db.q("DELETE FROM ac_reservations"); history(self.db, actual=3_000); history(self.db, actual=60_000, model="codex:big")
        self.budget(30_000)
        tid = self.queued("Small team")
        self.assertEqual(self.drive(tid, 3), 1)

    def test_preflight_allow_implies_the_gateway_admits_across_the_band(self):
        # the invariant behind D1: whatever preflight releases, the gateway's first call takes
        self.budget(150_000)
        tid = self.queued("Probe")
        self.db.q("UPDATE mw_tasks SET status='todo' WHERE id=?", (tid,))
        scope = self.w._budget_scope(WID, self.row(tid))
        spent = 0
        for step in [100_000, 20_000, 10_000, 5_000, 3_000, 2_000, 1_500, 1_000, 3_000, 5_000, 10_000]:
            spend(self.db, step, team=TEAM); spent += step
            pf = agent_core.preflight(OWNER, "teams", **scope)
            if pf is None: self.assertIsNone(self.gateway(tid), f"preflight ALLOW but gateway REFUSE at {spent:,}")

    def test_in_flight_runs_keep_the_hard_pct_margin(self):
        # a run already going may finish its work between 100% and 110% (its tool calls tell it to file): only NEW work stops at 100%
        spend(self.db, 151_000, team=TEAM)
        tid = self.queued("Running already")
        self.assertIsNone(self.gateway(tid))
        self.assertIsNotNone(agent_core.preflight(OWNER, "teams", **self.w._budget_scope(WID, self.row(tid))))


class Release(TeamBudget):
    def test_5_a_fresh_allow_releases_the_hold_when_the_budget_frees_up(self):
        spend(self.db, 156_291, team=TEAM)
        tid = self.queued("Baseline")
        self.drive(tid, 5)
        self.assertEqual(self.row(tid)["hold"], "budget")
        self.budget(1_000_000)                                               # the Owner raises the allowance
        self.assertEqual(self.drive(tid, 3), 1)                              # released and started exactly once
        self.assertIsNone(self.row(tid)["hold"])

    def test_6_refuse_preserves_the_hold(self):
        spend(self.db, 156_291, team=TEAM)
        tid = self.queued("Baseline")
        self.drive(tid, 3)
        self.budget(155_000)                                                 # raised, still under what was spent (156,291)
        self.assertEqual(self.drive(tid, 20), 0)
        self.assertEqual(self.row(tid)["hold"], "budget")

    def test_7_unknown_never_becomes_allow(self):
        spend(self.db, 1_000, team=TEAM)
        tid = self.queued("Baseline")
        real = agent_core._core.preflight
        agent_core._core.preflight = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("database gone"))
        try:
            self.assertEqual(self.drive(tid, 20), 0)                         # UNKNOWN: held, never started
            info = json.loads(self.row(tid)["hold_info"])
            self.assertEqual((self.row(tid)["hold"], info["decision"]), ("budget", "UNKNOWN"))
        finally:
            agent_core._core.preflight = real
        self.assertEqual(self.drive(tid, 2), 1)                              # the check works again and allows: one start

    def test_8_fifty_board_and_tick_passes_produce_zero_additional_starts(self):
        spend(self.db, 156_291, team=TEAM)
        tids = [self.queued(f"Task {i}", agent=2 if i % 2 else 1) for i in range(4)]
        for _ in range(50):
            self.w._kick(WID); self.loop.tick()
        self.assertEqual((self.starts, self.runs()), ([], 0))
        self.assertTrue(all(self.row(t)["hold"] == "budget" for t in tids))

    def test_a_disagreement_backs_off_instead_of_looping(self):
        # defence in depth: if preflight and the gateway still disagree (here: the gateway's estimate is forced far above preflight's),
        # each re-hold right after a release doubles the wait: 50 passes make at most a couple of refused starts, never thousands
        spend(self.db, 120_000, team=TEAM)  # preflight (forced 2,000): 122k fits; the gateway (forced 50,000): 170k > 165k
        tid = self.queued("Disagreement")
        core = agent_core._core
        core.estimate_start = lambda owner, model=None: 2_000              # preflight underestimates (instance attributes)...
        core.estimate_call = lambda owner, model, bound=None: 50_000       # ...and the gateway reserves far more
        try:
            starts = self.drive(tid, 50)
        finally:
            del core.estimate_start, core.estimate_call
        self.assertLessEqual(starts, 2)
        info = json.loads(self.row(tid)["hold_info"])
        self.assertEqual(self.row(tid)["hold"], "budget")
        self.assertGreater(info.get("not_before", 0), time.time())

    def test_a_raised_budget_ends_the_backoff_at_once(self):
        spend(self.db, 120_000, team=TEAM)
        tid = self.queued("Disagreement")
        core = agent_core._core
        core.estimate_start = lambda owner, model=None: 2_000
        core.estimate_call = lambda owner, model, bound=None: 50_000
        try:
            self.drive(tid, 10)
            self.assertGreater(json.loads(self.row(tid)["hold_info"]).get("not_before", 0), time.time())
            n = len(self.starts)
            self.budget(1_000_000)                                           # the Owner raises the allowance during the backoff
            self.assertEqual(self.drive(tid, 1), n + 1)                       # released and started on the next pass
        finally: del core.estimate_start, core.estimate_call

    def test_10_a_refused_attempt_is_not_counted_against_the_agent(self):
        spend(self.db, 120_000, team=TEAM)  # preflight (forced 2,000): 122k fits; the gateway (forced 50,000): 170k > 165k
        tid = self.queued("Disagreement")
        core = agent_core._core
        core.estimate_start = lambda owner, model=None: 2_000
        core.estimate_call = lambda owner, model, bound=None: 50_000
        try: self.drive(tid, 10)
        finally: del core.estimate_start, core.estimate_call
        t = self.row(tid)
        self.assertEqual((t["fails"], t["retries"]), (0, 0))
        self.assertIn("Not counted against the agent", t["note"])


class Replicas(TeamBudget):
    def test_9_two_processes_cannot_start_the_same_task_twice(self):
        tid = self.queued("Benchmark C1")
        spend(self.db, 1_000, team=TEAM)
        other = self.work()                                                  # a second replica on the same database
        other.loop, other.sbx, other._guarded = None, None, {}
        other.pool, other._event = self.w.pool, (lambda *a, **k: None)
        other._kick = mining_work.Work._kick.__get__(other)
        go = threading.Barrier(2)
        def run(w): go.wait(); w._kick(WID)
        ts = [threading.Thread(target=run, args=(w,)) for w in (self.w, other)]
        for t in ts: t.start()
        for t in ts: t.join()
        self.assertEqual(self.starts.count(tid), 1)
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM mw_runs WHERE task_id=?", (tid,), one=True)["n"], 1)


class Dispatcher(Lifecycle):
    def test_4_the_dispatcher_cannot_bypass_the_preflight(self):
        # control_dispatch asks the same preflight; with the reservation it now refuses the band under an owner limit too
        core = agent_core._core
        history(self.db, owner=ME["id"])
        core.set_limit(ME["id"], "global", "*", 100_000, period="day", label="Hard limit")
        spend(self.db, 100_000 - RESERVATION + 1, owner=ME["id"])
        t = self.agent_task("Write the launch plan")
        for _ in range(50): self.assertEqual(cd.dispatch(self.ch, ME)["agent"], 0)
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM ac_runs WHERE ref=?", (f"ctl:t{t}",), one=True)["n"], 0)


if __name__ == "__main__":
    unittest.main()
