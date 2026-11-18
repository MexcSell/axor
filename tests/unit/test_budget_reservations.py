"""Budget reservations (G5-2.2 Milestone 3): a model call under a stopping limit holds its estimate before it goes out, in a
transaction that checks spent + held + estimate against every limit over it, and its reported use settles the hold exactly once.

The concurrency tests run on two database connections (two AuthDB and two agent cores on one database), so what they show comes
from the database's transaction, not from one process's lock. They run on SQLite and, with DATABASE_URL, on Postgres."""
import os, sqlite3, tempfile, threading, time, types, unittest
from unittest import mock

from app import agent_core, llm
from app.auth import AuthDB
from app.llm import LLMError, Providers

OWNER = 1


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(); self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "a.db")
        self.db = AuthDB(self.path)
        saved = (dict(agent_core._buckets), dict(agent_core._guards))  # other tests' systems registered theirs: not these tests'
        agent_core._buckets.clear(); agent_core._guards.clear()
        def restore():
            agent_core._buckets.clear(); agent_core._buckets.update(saved[0])
            agent_core._guards.clear(); agent_core._guards.update(saved[1])
            agent_core._local.run = None
            agent_core._core = None
        self.addCleanup(restore)
        agent_core._core = None
        self.core = agent_core.init(self.db)
        agent_core._local.run = None

    def second(self):
        """Another connection to the same database, with its own core: another process, as far as the database can tell."""
        db2 = AuthDB(self.path)
        return agent_core.Core(db2)

    def limit(self, tokens, scope="system", key="race", period="day"):
        return self.core.set_limit(OWNER, scope, key, tokens, period=period, label=f"{scope} {key}", origin="manual", by="test")

    def spent(self, system="race"):
        return self.db.q("SELECT COALESCE(SUM(tokens),0) AS n FROM ac_runs WHERE system=?", (system,), one=True)["n"]

    def holds(self, **where):
        w = " AND ".join(f"{k}=?" for k in where) or "1=1"
        return self.db.q(f"SELECT * FROM ac_reservations WHERE {w} ORDER BY id", tuple(where.values()))


class Concurrency(Base):
    def race(self, n, estimate, actual, limit=1_000, latency=.03):
        """n runs at once, half on each connection, calling until refused. Returns (spent, calls)."""
        self.limit(limit)
        cores = [self.core, self.second()]
        go, calls, lock = threading.Barrier(n), [], threading.Lock()
        def worker(i):
            c = cores[i % 2]
            c.begin("race", OWNER, "task", ref=f"race:{i}")
            try:
                go.wait()
                for _ in range(20):
                    if c.admit(estimate, model="m"): break
                    time.sleep(latency)                  # the model call, between its reservation and its settlement
                    c.used(actual)
                    with lock: calls.append(i)
            finally:
                c.end("done")
        ts = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        for t in ts: t.start()
        for t in ts: t.join(60)
        return self.spent(), len(calls)

    def test_concurrent_runs_never_overcommit_the_limit(self):
        spent, calls = self.race(8, 300, 300)
        self.assertLessEqual(spent, 1_000)                          # Milestone 2 measured 2,400 here
        self.assertEqual((spent, calls), (900, 3))                  # 3 calls fit (900); a 4th's 300 doesn't
        self.assertEqual(self.holds(state="held"), [])
        print(f"\n[reservations] 8 runs on 2 connections, limit 1,000, 300 reserved and used a call: {spent:,} spent, {calls} calls")

    def test_without_a_reservation_the_check_alone_overshoots(self):
        # the Milestone 2 gateway, kept for comparison: estimate 0 checks without holding, so runs in flight all pass
        spent, calls = self.race(8, 0, 300)
        self.assertGreater(spent, 1_000)
        print(f"\n[check only] 8 runs, limit 1,000: {spent:,} spent ({calls} calls): why reservations were needed")

    def test_use_over_the_estimate_is_the_only_overshoot_and_is_recorded(self):
        spent, calls = self.race(8, 300, 450)
        # admitted calls fit by their estimates (3 × 300 ≤ 1,000); each used 150 more than it held: at most 3 × 150 over
        self.assertLessEqual(spent, 1_000 + 3 * 150)
        r = self.core.reservations(OWNER)["settled"]
        self.assertEqual((r["overruns"], r["over"]), (calls, calls * 150))
        print(f"\n[overrun] estimate 300, actual 450: {spent:,} spent, {r['overruns']} overruns recorded ({r['over']:,} tokens over their holds)")

    def test_concurrent_settlement_counts_once(self):
        self.limit(10_000)
        cores = [self.core, self.second()]                          # opened first: a core's start-up lapses the holds it finds
        rid = self.core.begin("race", OWNER, "task", ref="race:s")
        self.assertIsNone(self.core.admit(500, model="m"))
        hold = agent_core._local.run["hold"]
        go = threading.Barrier(8)
        def settle(i):
            go.wait(); cores[i % 2].settle([hold], 400, rid)
        ts = [threading.Thread(target=settle, args=(i,)) for i in range(8)]
        for t in ts: t.start()
        for t in ts: t.join(30)
        self.assertEqual(self.db.q("SELECT tokens FROM ac_runs WHERE id=?", (rid,), one=True)["tokens"], 400)
        self.assertEqual([(h["state"], h["actual"]) for h in self.holds(id=hold)], [("settled", 400)])


class Lifecycle(Base):
    def setUp(self):
        super().setUp()
        self.limit(10_000)
        self.rid = self.core.begin("race", OWNER, "task", ref="race:1")

    def test_no_stopping_limit_means_no_reservation_and_no_write(self):
        self.core.drop_limit(OWNER, self.core.limits(OWNER)[0]["id"])
        self.assertIsNone(self.core.admit(500, model="m"))
        self.assertNotIn("hold", agent_core._local.run)
        self.core.used(120)
        self.assertEqual(self.holds(), [])
        self.assertEqual(self.spent(), 120)

    def test_alert_only_limits_reserve_nothing(self):
        self.core.set_limit(OWNER, "system", "race", 100, period="day", label="alert", origin="manual", by="test", mode="alert")
        self.assertIsNone(self.core.admit(500, model="m"))
        self.assertEqual(self.holds(), [])

    def test_estimated_and_actual_are_kept_apart(self):
        self.assertIsNone(self.core.admit(700, model="m"))
        self.core.used(650)
        h = self.holds(run_id=self.rid)[0]
        self.assertEqual((h["state"], h["estimate"], h["actual"]), ("settled", 700, 650))
        self.assertEqual(self.spent(), 650)                          # the run counts what was used, never the estimate

    def test_holds_count_against_the_limit_until_settled(self):
        other = self.second()
        self.assertIsNone(self.core.admit(6_000, model="m"))
        hold = agent_core._local.run.pop("hold")                    # still in flight
        other.begin("race", OWNER, "task", ref="race:2")
        why = other.admit(5_000, model="m")                          # 0 spent + 6,000 held + 5,000 > 10,000
        self.assertIn("token budget", why)
        self.assertIn("6,000", why)
        self.assertIsNone(other.admit(4_000, model="m"))             # fits: 6,000 + 4,000
        agent_core._local.run.pop("hold")
        self.core.settle([hold], 1_000, self.rid)                    # the first call used less: its hold gives way to its actual
        self.assertIsNone(other.admit(4_000, model="m"))             # 1,000 + 4,000 + 4,000 ≤ 10,000

    def test_duplicate_requests_hold_once_and_never_run_twice(self):
        self.assertIsNone(self.core.admit(500, key="req-1", model="m"))
        first = agent_core._local.run["hold"]
        self.assertIsNone(self.core.admit(500, key="req-1", model="m"))   # the same request again: the same hold
        self.assertEqual(agent_core._local.run["hold"], first)
        self.assertEqual(len(self.holds(state="held")), 1)
        self.core.used(300)
        why = self.core.admit(500, key="req-1", model="m")           # settled already: a duplicate isn't run again
        self.assertIn("duplicate", why)
        self.assertEqual(self.spent(), 300)

    def test_partial_use_of_a_failed_call_settles_it(self):
        # Claude Code's is_error result reports what it used before failing: _cli_once counts it (used), then raises
        self.assertIsNone(self.core.admit(2_000, model="m"))
        self.core.used(180)
        self.core.call_failed(LLMError("Claude Code failed: overloaded"))   # nothing left to release
        h = self.holds(run_id=self.rid)[0]
        self.assertEqual((h["state"], h["actual"]), ("settled", 180))
        self.assertEqual(self.spent(), 180)

    def test_an_answered_error_releases_the_hold(self):
        class Status(Exception): status_code = 500
        self.assertIsNone(self.core.admit(2_000, bound=9_000, model="m"))
        try:
            try: raise Status("server error")
            except Status as e: raise LLMError("Claude answered 500") from e
        except LLMError as e: self.core.call_failed(e)
        h = self.holds(run_id=self.rid)[0]
        self.assertEqual((h["state"], h["actual"]), ("released", 0))
        self.assertEqual(self.spent(), 0)

    def test_an_unknown_outcome_is_charged_at_its_bound_never_zero(self):
        self.assertIsNone(self.core.admit(2_000, bound=9_000, model="m"))
        try:
            try: raise TimeoutError("read timed out")
            except TimeoutError: raise LLMError("The model didn't answer in time.")
        except LLMError as e: self.core.call_failed(e)
        h = self.holds(run_id=self.rid)[0]
        self.assertEqual(h["state"], "charged")
        r = self.db.q("SELECT tokens, metering FROM ac_runs WHERE id=?", (self.rid,), one=True)
        self.assertEqual((r["tokens"], r["metering"]), (9_000, "charged"))

    def test_an_unknown_outcome_without_a_bound_is_unmetered(self):
        self.assertIsNone(self.core.admit(2_000, model="terminal:m"))     # a CLI call: no bound
        self.core.call_failed(ConnectionResetError("connection reset"))
        self.assertEqual(self.holds(run_id=self.rid)[0]["state"], "unmetered")
        self.assertEqual(self.db.q("SELECT metering FROM ac_runs WHERE id=?", (self.rid,), one=True)["metering"], "unmetered")
        self.assertIn("token budget", self.core.admit(100, model="m") or "")  # D-025: the scope waits for a person's estimate

    def test_a_cli_timeout_marked_unmetered_keeps_its_hold_unmetered(self):
        self.assertIsNone(self.core.admit(2_000, model="terminal:m"))
        self.core.unmetered("Claude Code timed out")                 # what _cli_once does before it raises
        self.core.call_failed(LLMError("Claude Code timed out after 300 s."))
        self.assertEqual(self.holds(run_id=self.rid)[0]["state"], "unmetered")

    def test_a_crashed_worker_is_recovered_at_start_up(self):
        self.assertIsNone(self.core.admit(2_000, bound=7_000, model="anthropic:m"))
        other = self.core.begin("race", OWNER, "task", ref="race:cli")   # a second run, left open as a crash leaves it
        self.assertIsNone(self.core.admit(3_000, model="terminal:m"))
        agent_core._local.run = None
        # the crash: this process stops renewing its holds, and their leases run out (Milestone 4: start-up lapses only those)
        agent_core._unlease([h["id"] for h in self.holds(state="held")])
        self.db.q("UPDATE ac_reservations SET expires=? WHERE state='held'", (time.time() - 1,))
        agent_core.Core(AuthDB(self.path))                              # the restart
        api, cli = self.holds(run_id=self.rid)[0], self.holds(run_id=other)[0]
        self.assertEqual((api["state"], cli["state"]), ("charged", "unmetered"))
        rows = {r["id"]: r for r in self.db.q("SELECT id, tokens, metering, status FROM ac_runs")}
        self.assertEqual((rows[self.rid]["tokens"], rows[self.rid]["metering"], rows[self.rid]["status"]), (7_000, "charged", "lost"))
        self.assertEqual((rows[other]["metering"], rows[other]["status"]), ("unmetered", "lost"))
        self.assertEqual(self.holds(state="held"), [])

    def test_an_expired_hold_lapses_at_the_next_admission(self):
        self.assertIsNone(self.core.admit(2_000, bound=5_000, model="m"))
        hold = agent_core._local.run.pop("hold")                     # its worker hung
        self.db.q("UPDATE ac_reservations SET expires=? WHERE id=?", (time.time() - 1, hold))
        self.assertIsNone(self.core.admit(100, model="m"))
        self.assertEqual(self.holds(id=hold)[0]["state"], "charged")
        # its call reports after all: the actual replaces the charge, once
        self.core.settle([hold], 1_200, self.rid)
        self.core.settle([hold], 1_200, self.rid)
        self.assertEqual(self.db.q("SELECT tokens FROM ac_runs WHERE id=?", (self.rid,), one=True)["tokens"], 1_200)
        self.assertIn("late", self.holds(id=hold)[0]["note"])

    def test_a_database_outage_at_admission_refuses_the_call(self):
        with mock.patch.object(self.db, "tx", side_effect=sqlite3.OperationalError("database is locked")):
            why = self.core.admit(500, model="m")
        self.assertEqual(why, agent_core.VERIFY_STOP)                # UNKNOWN: the call doesn't go out
        self.assertEqual(self.holds(), [])

    def test_a_database_outage_at_settlement_stops_the_run_and_keeps_the_hold(self):
        self.assertIsNone(self.core.admit(500, bound=4_000, model="m"))
        with mock.patch.object(self.core, "settle", side_effect=OSError("database unavailable")):
            self.core.used(300)
        self.assertEqual(self.core.admit(100, model="m"), agent_core.VERIFY_STOP)   # no more calls for this run
        self.assertEqual(self.holds(run_id=self.rid)[0]["state"], "held")          # still counted until it lapses
        self.assertNotIn(self.holds(run_id=self.rid)[0]["id"], agent_core._leases)  # no longer renewed: the call is over
        self.db.q("UPDATE ac_reservations SET expires=? WHERE run_id=?", (time.time() - 1, self.rid))  # its lease runs out
        self.core._recover("test")                                                 # the expiry rule: charged at its bound
        self.assertEqual(self.holds(run_id=self.rid)[0]["state"], "charged")

    def test_a_failed_transaction_leaves_nothing_behind(self):
        with self.assertRaises(RuntimeError):
            with self.db.tx():
                self.db.q("INSERT INTO ac_reservations (owner_id, run_id, rkey, estimate, state, created, expires) VALUES (1, 1, 'x', 5, 'held', 0, 0)")
                raise RuntimeError("boom")
        self.assertEqual(self.holds(), [])
        with self.db.tx():
            with self.db.tx():                                                     # nested: one transaction
                self.db.q("INSERT INTO ac_reservations (owner_id, run_id, rkey, estimate, state, created, expires) VALUES (1, 1, 'y', 5, 'held', 0, 0)")
        self.assertEqual(len(self.holds()), 1)


class Scopes(Base):
    def test_every_scope_over_the_run_is_checked_with_its_holds(self):
        # owner (daily cap), global, team and task contract (a Company-wide limit is a system limit on "company"): the tightest decides
        b = self.second()
        self.core.set_cap(OWNER, 50_000, "test")
        self.limit(20_000, "global", "*")
        self.limit(8_000, "team", "comp:1")
        self.limit(3_000, "contract", "mw_task:7")
        def run(core, ref, team=None, contract=None, system="teams"):
            rid = core.begin(system, OWNER, "task", ref=ref)
            core.db.q("UPDATE ac_runs SET team=?, contract=? WHERE id=?", (team, contract, rid))
            agent_core._local.run.update(team=team, contract=contract)
            return rid
        run(self.core, "mw_task:7", "comp:1", "mw_task:7")
        self.assertIsNone(self.core.admit(2_000, model="m")); agent_core._local.run.pop("hold")
        self.assertIn("task contract", self.core.admit(2_000, model="m"))   # 2,000 held + 2,000 > the task's 3,000
        run(b, "mw_task:8", "comp:1")                                       # the same team, another task, another connection
        self.assertIsNone(b.admit(5_000, model="m")); agent_core._local.run.pop("hold")
        self.assertIn("team", b.admit(2_000, model="m"))                    # 7,000 held + 2,000 > the team's 8,000
        run(self.core, "c:1", system="hub")                                 # outside the team: only global and the cap
        self.assertIsNone(self.core.admit(12_000, model="m")); agent_core._local.run.pop("hold")
        self.assertIn("global", self.core.admit(2_000, model="m"))          # 19,000 held + 2,000 > 20,000
        self.core.set_cap(OWNER, 20_000, "test")
        self.assertIn("daily token budget", self.core.admit(1_500, model="m"))  # the cap: 19,000 + 1,500 > 20,000 (checked first)

    def test_the_owners_daily_cap_counts_holds(self):
        self.core.set_cap(OWNER, 5_000, "test")
        self.core.begin("hub", OWNER, "chat", ref="c:1")
        self.assertIsNone(self.core.admit(4_000, model="m"))
        agent_core._local.run.pop("hold")
        why = self.core.admit(2_000, model="m")
        self.assertIn("daily token budget", why)
        self.assertIn("4,000", why)

    def test_a_systems_own_budget_counts_the_holds_of_its_runs(self):
        # a Competition team's 24-hour budget or a Company project's, registered as a bucket (mining_work, company)
        here = threading.local()  # the connection of the core asking: in production every system shares the one AuthDB (main.py)
        def bucket(run):
            if run.get("team") != "comp:9": return []
            spent = here.db.q("SELECT COALESCE(SUM(tokens),0) AS n FROM ac_runs WHERE team='comp:9'", one=True)["n"]  # settled with the hold's release
            return [{"limit": 1_000, "spent": spent, "runs": ("team=?", ("comp:9",)), "label": "Team budget",
                     "message": lambda n, h, e: f"The team's 24-hour token budget can't take this call: {n} used, {h} held, {e} asked."}]
        agent_core.register_bucket("t", bucket)
        cores = [self.core, self.second()]
        go, calls, lock = threading.Barrier(6), [], threading.Lock()
        def worker(i):
            c = cores[i % 2]
            here.db = c.db
            rid = c.begin("teams", OWNER, "task", ref=f"t:{i}")
            c.db.q("UPDATE ac_runs SET team='comp:9' WHERE id=?", (rid,))
            agent_core._local.run["team"] = "comp:9"
            go.wait()
            if not c.admit(300, model="m"):
                time.sleep(.03)
                c.used(300)
                with lock: calls.append(i)
            c.end("done")
        ts = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
        for t in ts: t.start()
        for t in ts: t.join(30)
        self.assertEqual(len(calls), 3)                               # 3 × 300 held fit in 1,000; the other 3 were refused

    def test_the_team_and_company_buckets_are_registered(self):
        from app import company, mining_work
        self.assertTrue(hasattr(mining_work.Work, "_budget_bucket"))
        self.assertTrue(hasattr(company.Company, "_budget_bucket"))


class RealBuckets(Base):
    """The two systems' own budgets as they run (mining_work.Work._budget_bucket, company.Company._budget_bucket), on their real
    tables and SQL, concurrent calls on the one connection production shares (main.py's auth_db)."""
    def race(self, n, system, refs, setup_run, estimate=300, actual=300, after=None):
        go, calls, lock = threading.Barrier(n), [], threading.Lock()
        def worker(i):
            rid = self.core.begin(system, OWNER, "task", ref=refs[i])
            setup_run(rid)
            try:
                go.wait()
                if not self.core.admit(estimate, model="m"):
                    time.sleep(.03); self.core.used(actual)
                    with lock: calls.append(i)
                if after: after(i)
            finally:
                self.core.end("done")
        ts = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        for t in ts: t.start()
        for t in ts: t.join(30)
        return len(calls)

    def test_a_company_projects_budget(self):
        from app import company
        co = company.Company(self.db, None)                              # its tables, and its bucket registered
        self.assertIn("company", agent_core._buckets)
        self.db.q("INSERT INTO co_projects (id, company_id, name, budget, spent, status) VALUES (1, 1, 'Probe', 1000, 0, 'active')")
        for t in range(1, 7): self.db.q("INSERT INTO co_tasks (id, company_id, project_id, title) VALUES (?, 1, 1, 't')", (t,))
        n = self.race(6, "company", [f"co:{t}" for t in range(1, 7)], lambda rid: None)
        self.assertEqual(n, 3)                                           # 3 × 300 fit in 1,000; the ledger counts what settled
        led = self.db.q("SELECT COALESCE(SUM(tokens),0) AS n FROM ac_runs WHERE ref IN (SELECT 'co:' || id FROM co_tasks WHERE project_id=1)", one=True)["n"]
        self.assertEqual(led, 900)
        b = co._budget_bucket({"system": "company", "ref": "co:1"})[0]
        self.assertEqual((b["limit"], b["spent"]), (1000, 900))
        self.assertEqual(co._budget_bucket({"system": "company", "ref": "cob:1"}), [])   # a brief has no project

    def test_a_competition_teams_24_hour_budget(self):
        from app import mining_work
        self.db.q("CREATE TABLE IF NOT EXISTS mw_comps (id INTEGER PRIMARY KEY, name TEXT, number INTEGER, budget INTEGER)")
        self.db.q("CREATE TABLE IF NOT EXISTS mw_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, started REAL, tokens INTEGER)")
        self.db.q("INSERT INTO mw_comps (id, name, number, budget) VALUES (1, 'SN-test', 1, 1000)")   # the stop: HARD_PCT% of it
        w = types.SimpleNamespace(db=self.db)
        w.day_tokens = lambda wid: mining_work.Work.day_tokens(w, wid)
        w._flying = lambda wid: mining_work.Work._flying(w, wid)
        w._label = lambda c: c["name"]
        agent_core.register_bucket("teams", lambda run: mining_work.Work._budget_bucket(w, run))
        def setup(rid):
            self.db.q("UPDATE ac_runs SET team='comp:1' WHERE id=?", (rid,)); agent_core._local.run["team"] = "comp:1"
        def finish(i):  # as mining_work does at a run's end: mw_runs gets its tokens before the ledger row closes
            self.db.q("INSERT INTO mw_runs (comp_id, started, tokens) SELECT 1, ?, tokens FROM ac_runs WHERE id=?", (time.time(), agent_core._local.run["id"]))
        n = self.race(8, "teams", [f"mw:{i}" for i in range(8)], setup, after=finish)
        limit = 1000 * mining_work.HARD_PCT // 100
        self.assertEqual(n, limit // 300)
        self.assertLessEqual(mining_work.Work.day_tokens(w, 1), limit)
        print(f"\n[team bucket] 8 runs, 24-hour budget 1,000 (stop at {limit:,}), 300 a call: {n} calls, {mining_work.Work.day_tokens(w, 1):,} spent")


class Edges(Base):
    def setUp(self):
        super().setUp()
        self.limit(10_000)
        self.rid = self.core.begin("race", OWNER, "task", ref="race:e")

    def test_a_hold_left_on_the_thread_lapses_at_the_next_admission(self):
        self.assertIsNone(self.core.admit(500, bound=3_000, model="m"))
        stale = agent_core._local.run["hold"]                           # a path that never called used() or call_failed()
        self.assertIsNone(self.core.admit(500, model="m"))
        self.assertEqual(self.holds(id=stale)[0]["state"], "charged")  # unknown use: charged at its bound, never released as 0

    def test_a_bounded_call_failing_without_an_answer_is_charged(self):
        self.assertIsNone(self.core.admit(500, bound=3_000, model="m"))
        self.core.call_failed(LLMError("The reply couldn't be read."))   # no status in its chain: it may have been billed
        self.assertEqual(self.holds(run_id=self.rid)[0]["state"], "charged")

    def test_a_refusal_made_by_holds_passes_when_they_settle(self):
        self.assertIsNone(self.core.admit(9_000, model="m"))
        hold = agent_core._local.run.pop("hold")
        r = self.core.preflight(OWNER, "race", ref="race:e")              # D1: new work reserves its first call too: 9,000 held + 2,000 > 10,000
        self.assertEqual((r["decision"], r["release"]), ("REFUSE", "settle"))  # the gateway's own answer (below): it waits for the hold to settle
        why = self.core.admit(2_000, model="m")
        self.assertIn("calls in flight hold 9,000", why)
        self.assertNotIn("breach", agent_core._local.run)                  # it doesn't stop the run for good
        self.core.settle([hold], 1_000, self.rid)
        self.assertIsNone(self.core.admit(2_000, model="m"))

    def test_a_refusal_made_by_holds_is_released_on_settlement_not_at_midnight(self):
        self.limit(1_000, "system", "race2")
        self.core.begin("race2", OWNER, "task", ref="race2:1")
        self.assertIsNone(self.core.admit(600, model="m")); agent_core._local.run.pop("hold")
        self.core.begin("race2", OWNER, "task", ref="race2:2")
        r = self.core._verdict(dict(agent_core._local.run), estimate=600)
        self.assertEqual((r["release"], r["release_at"], r["spent"], r["held"]), ("settle", None, 0, 600))
        from app.mining_work import _budget_note
        self.assertIn("when calls in flight settle", _budget_note(r))


@unittest.skipUnless(os.getenv("DATABASE_URL"), "Postgres only: a transaction's connection lost on the server")
class PostgresOutage(Base):
    def test_a_connection_lost_inside_a_transaction_rolls_back_and_recovers(self):
        killer = AuthDB(self.path)                                         # another connection, to end this one's backend
        with self.assertRaises(sqlite3.Error):
            with self.db.tx():
                self.db.q("INSERT INTO ac_reservations (owner_id, run_id, rkey, estimate, state, created, expires) VALUES (1, 1, 'lost', 5, 'held', 0, 0)")
                pid = self.db.q("SELECT pg_backend_pid() AS p", one=True)["p"]
                killer.q("SELECT pg_terminate_backend(?)", (pid,))
                time.sleep(.3)
                self.db.q("SELECT 1 AS one")                               # the connection is gone: this raises, no reconnect into the transaction
        self.assertIsNone(self.db._tx_thread)
        self.assertFalse(self.db.db._tx)
        self.assertEqual(self.db.q("SELECT COUNT(*) AS n FROM ac_reservations WHERE rkey='lost'", one=True)["n"], 0)   # nothing committed
        self.assertEqual(self.db.q("SELECT 1 AS one", one=True)["one"], 1)  # the next statement works on a new connection

    def test_a_connection_lost_between_statements_is_replaced_at_the_next_transaction(self):
        killer = AuthDB(self.path)
        pid = self.db.q("SELECT pg_backend_pid() AS p", one=True)["p"]
        killer.q("SELECT pg_terminate_backend(?)", (pid,))
        time.sleep(.3)
        with self.db.tx():                                                  # BEGIN on the dead connection: reconnected once
            self.db.q("INSERT INTO ac_reservations (owner_id, run_id, rkey, estimate, state, created, expires) VALUES (1, 1, 'after', 5, 'held', 0, 0)")
        self.assertEqual(self.db.q("SELECT COUNT(*) AS n FROM ac_reservations WHERE rkey='after'", one=True)["n"], 1)

    def test_the_lock_wait_is_bounded(self):
        other = AuthDB(self.path)
        holding, release = threading.Event(), threading.Event()
        def hold():
            with other.tx():
                holding.set(); release.wait(10)
        t = threading.Thread(target=hold); t.start()
        holding.wait(5)
        was, AuthDB.TX_WAIT = AuthDB.TX_WAIT, 1
        try:
            t0 = time.time()
            with self.assertRaises(sqlite3.Error):
                with self.db.tx(): pass
            self.assertLess(time.time() - t0, 5)
        finally:
            AuthDB.TX_WAIT = was; release.set(); t.join(10)
        with self.db.tx(): self.db.q("SELECT 1 AS one")                    # free again


class Gateway(Base):
    """The wiring in llm.py: every counted call reserves first and settles after, or releases or lapses when it raises."""
    def setUp(self):
        super().setUp()
        self.limit(1_000_000)
        self.rid = self.core.begin("race", OWNER, "task", ref="race:g")
        self.p = Providers.__new__(Providers)

    def completer(self, fn):
        with mock.patch.object(Providers, "_completer", lambda self, choice, effort="medium": (fn, "anthropic:test")):
            call, _ = self.p.completer("anthropic:test")
        return call

    def test_an_api_call_reserves_within_its_bound_and_settles(self):
        call = self.completer(lambda s, t, m: ([{"type": "text", "text": "ok"}], "end_turn", 640))
        call("system", [], [{"role": "user", "content": "hello"}])
        h = self.holds(run_id=self.rid)[0]
        self.assertEqual((h["state"], h["actual"]), ("settled", 640))
        self.assertGreater(h["bound"], llm.MAX_TOKENS)                # input bytes + the output cap
        self.assertLessEqual(h["estimate"], h["bound"])

    def test_an_api_call_that_times_out_is_charged_not_zeroed(self):
        def call(s, t, m):
            try: raise TimeoutError("timed out")
            except TimeoutError: raise LLMError("The model didn't answer in time.")
        with self.assertRaises(LLMError):
            self.completer(call)("system", [], [{"role": "user", "content": "hello"}])
        h = self.holds(run_id=self.rid)[0]
        self.assertEqual(h["state"], "charged")
        self.assertEqual(self.db.q("SELECT tokens FROM ac_runs WHERE id=?", (self.rid,), one=True)["tokens"], h["bound"])


if __name__ == "__main__":
    unittest.main()
