"""G5-2 budget safety (Owner decision 2026-11-11, after the 199-run staging incident).

A budget refusal is orchestrator.decide's HOLD: a persistent, non-runnable hold with the refusing limit and its release
condition on record; never an immediate requeue; never counted against the agent. agent_core.preflight answers "would this
work be refused?" with the gateway's own accounting and scope matching, for work that hasn't started (no thread-local run).
Held tasks go back to the queue only after a fresh preflight passes; a per-call hold also needs a per-call limit changed."""
import json, os, sys, tempfile, threading, time, types, unittest

from app import agent_core, control_dispatch as cd, mining_autoloop, mining_work, orchestrator as o
from app.auth import AuthDB

sys.path.insert(0, os.path.dirname(__file__))
from test_mission_ref import ME, WID, Base as BoardBase  # noqa: E402
from test_task_lifecycle import Lifecycle  # noqa: E402

OWNER = ME["id"]


def spend(db, tokens, *, system="teams", team=None, agent=None, corr=None, contract=None, ref=None, started=None, owner=OWNER):
    db.q("""INSERT INTO ac_runs (system, owner_id, agent_key, kind, ref, status, tokens, started, finished, corr, team, contract)
            VALUES (?,?,?,?,?,'done',?,?,?,?,?,?)""", (system, owner, agent, "task", ref, tokens, started or time.time(), started or time.time(), corr, team, contract))


class Preflight(unittest.TestCase):
    """The preflight's scope matching and windows: the gateway's own rules."""
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        self.core = agent_core.init(self.db) or agent_core._core

    def tearDown(self):
        agent_core._core = None
        self.dir.cleanup()

    def limit(self, scope, key, tokens, period="day", mode="stop", per_call=None):
        return self.core.set_limit(OWNER, scope, key, tokens, period=period, mode=mode, per_call=per_call, label=f"{scope} {key}")

    def pf(self, system="teams", **s): return agent_core.preflight(OWNER, system, **s)

    def test_a_global_owner_limit_blocks_every_team(self):
        self.limit("global", "*", 1000); spend(self.db, 5000, team="comp:1")
        for team in ("comp:1", "comp:2", "comp:9"):
            r = self.pf(team=team, ref=f"mwt:{team}")
            self.assertEqual((r["scope"], r["release"]), ("global", "reset"))
            self.assertIn("token budget", r["reason"])

    def test_system_and_mission_limits_block_matching_work_only(self):
        self.limit("system", "teams", 1000); spend(self.db, 2000, system="teams")
        self.assertEqual(self.pf("teams", team="comp:1")["scope"], "system")
        self.assertIsNone(self.pf("workforce", ref="wf:1"))
        self.limit("mission", "comp:3", 500); spend(self.db, 600, system="control", corr="comp:3")
        self.assertEqual(self.pf("control", corr="comp:3", ref="ctl:t1")["scope"], "mission")
        self.assertIsNone(self.pf("control", corr="comp:4", ref="ctl:t2"))

    def test_team_agent_and_contract_limits_block_only_their_work(self):
        self.limit("team", "comp:1", 1000); spend(self.db, 1500, team="comp:1")
        self.assertEqual(self.pf("workforce", team="comp:1")["scope"], "team")
        self.assertIsNone(self.pf("workforce", team="comp:2"))
        self.limit("agent", "teams:7", 100); spend(self.db, 200, system="workforce", agent="teams:7")
        self.assertEqual(self.pf("workforce", agent_key="teams:7")["scope"], "agent")
        self.assertIsNone(self.pf("workforce", agent_key="teams:8"))
        self.limit("contract", "mwt:5", 100); spend(self.db, 300, system="workforce", ref="mwt:5")
        self.assertEqual(self.pf("workforce", ref="mwt:5")["scope"], "contract")
        self.assertIsNone(self.pf("workforce", ref="mwt:6"))

    def test_an_alert_only_limit_never_blocks(self):
        self.limit("global", "*", 10, mode="alert"); spend(self.db, 99999)
        self.assertIsNone(self.pf(team="comp:1"))

    def test_daily_and_monthly_windows_release_at_their_reset(self):
        # D1: preflight reserves a first call's estimate (at least the 2,000 floor) as the gateway does, so the limit sits above it
        self.limit("global", "*", 10_000, period="day"); spend(self.db, 50_000, started=agent_core._today() - 3600)  # spent yesterday
        self.assertIsNone(self.pf(team="comp:1"))
        spend(self.db, 50_000)
        r = self.pf(team="comp:1")
        self.assertEqual(r["release_at"], agent_core._today() + 86400)                   # midnight, local
        self.core.set_limit(OWNER, "global", "*", 10_000, period="month")
        r = self.pf(team="comp:1")
        self.assertEqual((r["period"], r["release"]), ("month", "reset"))
        self.assertGreater(r["release_at"], time.time())

    def test_a_total_limit_holds_until_raised(self):
        self.limit("team", "comp:1", 1000, period="total"); spend(self.db, 1500, team="comp:1", started=time.time() - 40 * 86400)
        r = self.pf(team="comp:1")
        self.assertEqual((r["release"], r["release_at"]), ("raise", None))
        self.limit("team", "comp:1", 5000, period="total")
        self.assertIsNone(self.pf(team="comp:1"))

    def test_a_refusal_is_not_the_agents_fault(self):
        d = o.decide("failed", "Over the global token budget of Staging hard limit: 30,771,653 of 100,000 tokens today (Intelligence layers → Budgets).")
        self.assertEqual((d["cls"], d["action"], d["retry"], d["agent_fault"]), ("budget", "hold", False, False))


class BoardFixture(BoardBase):
    """The board with the real start loop and the Autoloop's failure handling (no tests of its own: test_budget_verification reuses it)."""
    def setUp(self):
        super().setUp()
        for col in ("needs TEXT", "hold TEXT", "hold_info TEXT", "note TEXT", "feedback TEXT", "queued REAL", "run_id INTEGER", "runs INTEGER DEFAULT 0",
                    "reviewer INTEGER", "retries INTEGER DEFAULT 0", "retry_at REAL", "fail_class TEXT", "question TEXT", "fails INTEGER DEFAULT 0", "report_id INTEGER"):
            try: self.db.q(f"ALTER TABLE mw_tasks ADD COLUMN {col}")
            except Exception: pass  # noqa: BLE001
        for col in ("parallel INTEGER", "paused INTEGER DEFAULT 0", "internet INTEGER DEFAULT 0"):
            self.db.q(f"ALTER TABLE mw_comps ADD COLUMN {col}")
        self.db.q("ALTER TABLE mw_runs ADD COLUMN fail_class TEXT")
        for t in ("""CREATE TABLE ml_policy (comp_id INTEGER PRIMARY KEY, reserve REAL, retries INTEGER, task_cap INTEGER, total_cap INTEGER,
                     queue_cap INTEGER, backlog_cap INTEGER, updated REAL, mode TEXT)""",
                  """CREATE TABLE ml_state (comp_id INTEGER PRIMARY KEY, cool_until REAL, cool_reason TEXT, cool_n INTEGER DEFAULT 0,
                     plan_held TEXT, recovered INTEGER DEFAULT 0, recovered_at REAL, tick REAL)"""):
            self.db.q(t)
        self.core = agent_core.init(self.db) or agent_core._core
        self.starts = []
        self.w.loop, self.w.sbx = None, None
        self.w.pool = types.SimpleNamespace(submit=lambda fn, *a: self.starts.append(a[0]) if getattr(fn, "__name__", "") == "_work" else fn(*a))
        self.w._kick = mining_work.Work._kick.__get__(self.w)
        self.w._event = lambda *a, **k: None
        self.loop = object.__new__(mining_autoloop.Loop)
        self.loop.w, self.loop.db, self.loop.lk, self.loop.leases = self.w, self.db, threading.Lock(), {}

    def tearDown(self):
        agent_core._core = None
        super().tearDown()

    def queued(self, title, agent=2):
        tid = self.task(title, status="queued")
        self.db.q("UPDATE mw_tasks SET agent_id=? WHERE id=?", (agent, tid))
        return tid

    def runs(self): return self.db.q("SELECT COUNT(*) n FROM mw_runs", one=True)["n"]
    def row(self, tid): return self.db.q("SELECT * FROM mw_tasks WHERE id=?", (tid,), one=True)


class Board(BoardFixture):
    def test_the_199_run_incident_is_one_refusal_one_hold_zero_restarts(self):
        # as in staging: a global hard limit the owner's real usage today already exceeds
        self.core.set_limit(OWNER, "global", "*", 100_000, period="day", label="Staging hard limit")
        spend(self.db, 30_771_653)
        tid = self.queued("Summarise the staging scoring notes")
        for _ in range(50): self.w._kick(WID)                                             # 50 board passes
        self.assertEqual((self.starts, self.runs()), ([], 0))                            # zero starts
        t = self.row(tid)
        info = json.loads(t["hold_info"])
        self.assertEqual((t["status"], t["hold"], info["scope"], info["release"]), ("todo", "budget", "global", "reset"))
        self.assertTrue(info["limit_id"]); self.assertIn("Not counted against the agent", t["note"])

    def test_a_run_refused_mid_task_holds_once_and_is_never_restarted(self):
        tid = self.queued("Bench the candidate")
        self.w._kick(WID)                                                                  # no limit yet: it starts
        self.assertEqual(self.starts, [tid])
        self.core.set_limit(OWNER, "global", "*", 100_000, period="day", label="Hard limit")
        spend(self.db, 200_000)
        t = self.row(tid)
        self.assertTrue(self.loop.failed(tid, t["run_id"], "Over the global token budget of Hard limit: 200,000 of 100,000 tokens today (Intelligence layers → Budgets).", "failed"))
        self.db.q("UPDATE mw_runs SET status='failed', finished=? WHERE task_id=?", (time.time(), tid))  # the run is closed, as its caller does
        t = self.row(tid)
        self.assertEqual((t["status"], t["hold"], t["fails"], t["retries"]), ("todo", "budget", 0, 0))  # held, not counted, not retried
        for _ in range(50): self.w._kick(WID)                                             # the agent is free: only the hold stops a restart
        self.assertEqual((self.starts, self.runs()), ([tid], 1))                         # one run in all: the one that was refused
        # raising the limit releases it after a fresh preflight, and the next pass starts it once
        self.core.set_limit(OWNER, "global", "*", 10_000_000, period="day", label="Hard limit")
        self.w._kick(WID)
        self.assertEqual(self.row(tid)["hold"], None)
        self.assertEqual(self.starts.count(tid), 2)

    def test_a_team_limit_holds_only_that_team(self):
        self.core.set_limit(OWNER, "team", f"comp:{WID}", 1000, period="day")
        spend(self.db, 5000, team=f"comp:{WID}")
        tid = self.queued("Team task")
        self.w._kick(WID)
        self.assertEqual(self.row(tid)["hold"], "budget")
        self.assertIsNone(agent_core.preflight(OWNER, "teams", team="comp:999", ref="mwt:1"))

    def test_an_agent_limit_holds_only_that_agents_task(self):
        self.core.set_limit(OWNER, "agent", "teams:2", 100, period="day")
        spend(self.db, 500, agent="teams:2")
        mine, other = self.queued("Devon's task", agent=2), self.queued("Gus's task", agent=1)
        self.w._kick(WID)
        self.assertEqual((self.row(mine)["hold"], self.row(other)["hold"]), ("budget", None))
        self.assertIn(other, self.starts)

    def test_a_total_limit_stays_held_past_any_reset(self):
        self.core.set_limit(OWNER, "team", f"comp:{WID}", 1000, period="total")
        spend(self.db, 5000, team=f"comp:{WID}", started=time.time() - 10 * 86400)
        tid = self.queued("Team task")
        self.w._kick(WID)
        self.assertEqual(json.loads(self.row(tid)["hold_info"])["release"], "raise")
        for _ in range(5): self.w._kick(WID)
        self.assertEqual(self.row(tid)["hold"], "budget")
        self.core.set_limit(OWNER, "team", f"comp:{WID}", 100_000, period="total")
        self.w._kick(WID)
        self.assertIsNone(self.row(tid)["hold"])

    def test_a_per_call_refusal_waits_for_a_changed_limit_not_a_reset(self):
        self.core.set_limit(OWNER, "team", f"comp:{WID}", None, period="day", per_call=5000)
        tid = self.queued("Big task")
        self.w._kick(WID)
        t = self.row(tid)
        err = "A single model call used 12,000 tokens, over the per-call token budget of 5,000 (team comp:3). Split the work."
        self.assertTrue(self.loop.failed(tid, t["run_id"], err, "failed"))
        self.db.q("UPDATE mw_runs SET status='failed', finished=? WHERE task_id=?", (time.time(), tid))
        info = json.loads(self.row(tid)["hold_info"])
        self.assertEqual((info["kind"], info["release"]), ("per_call", "change"))
        for _ in range(10): self.w._kick(WID)                                             # nothing is spent over any window: still held
        self.assertEqual((self.row(tid)["hold"], self.starts.count(tid)), ("budget", 1))
        time.sleep(0.01)
        self.core.set_limit(OWNER, "team", f"comp:{WID}", None, period="day", per_call=20000)  # the Owner raises the per-call limit
        self.w._kick(WID)
        self.assertIsNone(self.row(tid)["hold"])

    def test_the_director_and_autopilot_cant_requeue_a_held_task(self):
        self.core.set_limit(OWNER, "global", "*", 10, period="day"); spend(self.db, 100)
        tid = self.queued("Held task")
        self.w._kick(WID)
        self.w._enqueue = mining_work.Work._enqueue.__get__(self.w)                      # the real one (the fixture stubs it)
        self.assertFalse(self.w._enqueue(tid))                                           # _enqueue refuses a held task
        self.assertEqual(self.row(tid)["status"], "todo")
        self.assertTrue(self.w._enqueue(tid, "Director: go on", hold_ok=True))          # the Director's requeue (hold_ok) queues it...
        for _ in range(10): self.w._kick(WID)
        self.assertEqual((self.row(tid)["hold"], self.starts), ("budget", []))           # ...and the start loop's fresh check holds it again


class Dispatcher(Lifecycle):
    def test_repeated_dispatcher_passes_start_nothing_under_a_refusing_limit(self):
        self.core = agent_core._core
        self.core.set_limit(ME["id"], "global", "*", 100, period="day", label="Hard limit")
        spend(self.db, 1000, owner=ME["id"])
        t = self.agent_task("Write the launch plan")
        for _ in range(10):
            out = cd.dispatch(self.ch, ME)
            self.assertEqual(out["agent"], 0)
        self.assertEqual(out.get("budget_held"), 1)
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM ac_runs WHERE ref=?", (f"ctl:t{t}",), one=True)["n"], 0)
        self.assertIn("Held by budget (global)", self.row(t)["summary"])
        self.core.set_limit(ME["id"], "global", "*", 1_000_000, period="day", label="Hard limit")
        self.assertEqual(cd.dispatch(self.ch, ME)["agent"], 1)                             # raised: dispatched once


if __name__ == "__main__":
    unittest.main()
