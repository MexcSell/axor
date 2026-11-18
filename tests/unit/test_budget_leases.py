"""Budget reservations under Milestone 4: leases, the expiration race, the three values, separate processes.

A hold carries a lease (`expires`) that its process renews while the call is in flight (agent_core heartbeat). A lease runs out only
when its process stops renewing it (it died, or couldn't reach the database); the hold then lapses as charged at its bound or
unmetered, never released as 0. Tests run on SQLite and, with DATABASE_URL, on Postgres; the process race uses real processes."""
import json, os, sqlite3, subprocess, sys, tempfile, textwrap, threading, time, unittest
from unittest import mock

from app import agent_core
from app.auth import AuthDB
from app.llm import LLMError, Providers

OWNER = 1


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(); self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "a.db")
        self.db = AuthDB(self.path)
        saved = (dict(agent_core._buckets), dict(agent_core._guards))
        agent_core._buckets.clear(); agent_core._guards.clear()
        def restore():
            agent_core._buckets.clear(); agent_core._buckets.update(saved[0])
            agent_core._guards.clear(); agent_core._guards.update(saved[1])
            agent_core._local.run = None; agent_core._core = None
            with agent_core._llock: agent_core._leases.clear()
        self.addCleanup(restore)
        agent_core._core = None
        self.core = agent_core.init(self.db)
        agent_core._local.run = None
        self.core.set_limit(OWNER, "system", "lease", 1_000, period="day", label="lease test", origin="manual", by="test")

    def hold(self, **w):
        k = " AND ".join(f"{x}=?" for x in w) or "1=1"
        return self.db.q(f"SELECT * FROM ac_reservations WHERE {k} ORDER BY id", tuple(w.values()))

    def short_lease(self, seconds=2):
        was = agent_core.Core.LEASE
        agent_core.Core.LEASE = seconds
        self.addCleanup(lambda: setattr(agent_core.Core, "LEASE", was))


class ExpirationRace(Base):
    """Agent A reserves and its call stays in flight past its first lease; agent B tries to take the amount; A then completes."""

    def test_a_call_in_flight_keeps_its_hold_past_its_lease(self):
        self.short_lease(2)
        other = agent_core.Core(AuthDB(self.path))                 # agent B: another connection (another process, to the database)
        started, done, tries = threading.Event(), threading.Event(), []
        def agent_a():
            self.core.begin("lease", OWNER, "task", ref="lease:A")
            assert self.core.admit(600, model="m") is None
            ha = agent_core._local.run["hold"]
            started.set()
            time.sleep(6)                                          # the model call, three leases long
            self.core.used(400)
            self.core.end("done")
            done.set(); tries.append(("a_hold", ha))
        def agent_b():
            started.wait(5)
            other.begin("lease", OWNER, "task", ref="lease:B")
            while not done.is_set():
                tries.append(("b", other.admit(600, model="m")))
                agent_core._local.run.pop("hold", None)
                time.sleep(.3)
            time.sleep(.2)
            tries.append(("b_after", other.admit(600, model="m")))
            other.end("done")
        ta, tb = threading.Thread(target=agent_a), threading.Thread(target=agent_b)
        ta.start(); tb.start(); ta.join(30); tb.join(30)
        during = [w for k, w in tries if k == "b"]
        self.assertTrue(len(during) >= 10)
        self.assertTrue(all(w and "token budget" in w for w in during), during[:3])   # never admitted while A's call was in flight
        ha = dict(tries)["a_hold"]
        a = self.hold(id=ha)[0]
        self.assertEqual((a["state"], a["actual"]), ("settled", 400))             # settled, never lapsed or charged
        self.assertIsNone(dict(tries)["b_after"])                                  # 400 + 600 fit once A settled
        print(f"\n[lease race] lease 2 s, A's call 6 s: B refused {len(during)} times while A was in flight; A settled 400; B admitted after")

    def test_a_dead_holder_cannot_release_its_amount(self):
        other = agent_core.Core(AuthDB(self.path))
        for bound in (None, 700):
            with self.subTest(bound=bound):
                self.db.q("DELETE FROM ac_reservations"); self.db.q("DELETE FROM ac_runs")
                ra = self.core.begin("lease", OWNER, "task", ref="lease:A")
                self.assertIsNone(self.core.admit(600, bound=bound, model="m"))
                ha = agent_core._local.run.pop("hold")
                agent_core._unlease([ha])                                          # A's process died: no more renewals …
                self.db.q("UPDATE ac_reservations SET expires=? WHERE id=?", (time.time() - 1, ha))  # … and its lease ran out
                other.begin("lease", OWNER, "task", ref="lease:B")
                why = other.admit(600, model="m")
                agent_core._local.run.pop("hold", None)
                self.assertIsNotNone(why)                                          # B never gets A's amount
                st = self.hold(id=ha)[0]["state"]
                self.assertEqual(st, "charged" if bound else "unmetered")
                if bound:                                                         # A's call reports after all: the charge becomes the actual, once
                    self.core.settle([ha], 300, ra); self.core.settle([ha], 300, ra)
                    self.assertEqual(self.db.q("SELECT tokens FROM ac_runs WHERE id=?", (ra,), one=True)["tokens"], 300)
                    self.assertIsNone(other.admit(600, model="m")); agent_core._local.run.pop("hold", None)

    def test_a_start_up_beside_a_live_hold_leaves_it_held(self):
        self.core.begin("lease", OWNER, "task", ref="lease:A")
        self.assertIsNone(self.core.admit(600, model="m"))
        h = agent_core._local.run["hold"]
        agent_core.Core(AuthDB(self.path))                                         # another process starts its core (a probe, the acceptance)
        self.assertEqual(self.hold(id=h)[0]["state"], "held")

    def test_the_heartbeat_renews_and_stops_with_settlement(self):
        self.short_lease(1)
        self.core.begin("lease", OWNER, "task", ref="lease:A")
        self.assertIsNone(self.core.admit(600, model="m"))
        h = agent_core._local.run["hold"]
        first = self.hold(id=h)[0]["expires"]
        time.sleep(1.6)
        self.assertGreater(self.hold(id=h)[0]["expires"], first)                  # renewed while in flight
        self.core.used(500)
        self.assertNotIn(h, agent_core._leases)                                    # settled: nothing renews it

    def test_budget_exhaustion_during_execution_stops_the_next_call(self):
        self.core.begin("lease", OWNER, "task", ref="lease:A")
        self.assertIsNone(self.core.admit(300, model="m")); self.core.used(300)   # A works
        other = agent_core.Core(AuthDB(self.path))
        other.begin("lease", OWNER, "task", ref="lease:B")
        self.assertIsNone(other.admit(600, model="m")); other.used(650)           # B spends the rest meanwhile
        why = self.core.admit(100, model="m")                                       # A's next call: 950 + 100 > 1,000
        self.assertIn("token budget", why)


class ThreeValues(Base):
    def test_estimate_reserved_and_actual_are_kept_apart(self):
        self.core.begin("lease", OWNER, "task", ref="lease:3")
        self.assertIsNone(self.core.admit(200, reserve=700, bound=900, model="m"))
        h = agent_core._local.run["hold"]
        self.core.used(450)
        r = self.hold(id=h)[0]
        self.assertEqual((r["estimate"], r["reserved"], r["actual"], r["bound"]), (200, 700, 450, 900))
        self.assertEqual(self.core.reservations(OWNER)["settled"]["overruns"], 0)  # 450 ≤ 700 reserved (over the 200 estimate: shown apart)

    def test_merging_a_session_keeps_each_estimate(self):
        self.core.begin("lease", OWNER, "task", ref="lease:s")
        self.assertIsNone(self.core.admit(200, model="m")); first = agent_core.defer()
        self.assertIsNone(self.core.admit(300, model="m"))
        self.core.absorb([first]); self.core.used(900)
        rows = {r["id"]: r for r in self.hold()}
        self.assertEqual(rows[first]["estimate"], 200)
        settled = next(r for r in rows.values() if r["state"] == "settled")
        self.assertEqual((settled["estimate"], settled["reserved"], settled["actual"]), (300, 500, 900))
        self.assertEqual(self.core.reservations(OWNER)["settled"]["over"], 400)    # actual over reserved: visible

    def test_an_actual_over_the_bound_is_flagged(self):
        self.core.begin("lease", OWNER, "task", ref="lease:b")
        self.assertIsNone(self.core.admit(100, bound=200, model="m")); self.core.used(250)
        self.assertIn("over its bound", self.hold()[0]["note"])
        self.assertEqual(self.core.reservations(OWNER)["settled"]["over_bound"], 1)

    def test_strict_mode_reserves_the_bound(self):
        with mock.patch.object(agent_core.Core, "STRICT", True):
            self.core.begin("lease", OWNER, "task", ref="lease:x")
            self.assertIsNone(self.core.admit(100, reserve=300, bound=800, model="m"))
        self.assertEqual(self.hold()[0]["reserved"], 800)

    def test_an_api_call_reserves_its_input_estimate_and_output_cap(self):
        from app import llm
        self.core.set_limit(OWNER, "system", "lease", 10_000_000, period="day", label="roomy", origin="manual", by="test")
        self.core.begin("lease", OWNER, "task", ref="lease:api")
        p = Providers.__new__(Providers)
        fn = lambda s, t, m: ([{"type": "text", "text": "ok"}], "end_turn", 640)
        with mock.patch.object(Providers, "_completer", lambda self, choice, effort="medium": (fn, "anthropic:test")):
            call, _ = p.completer("anthropic:test")
        msgs = [{"role": "user", "content": "x" * 3000}]
        call("sys", [], msgs)
        r = self.hold()[0]
        self.assertEqual(r["reserved"], llm._reserve_api(llm.MAX_TOKENS, "sys", [], msgs))
        self.assertGreaterEqual(r["reserved"], 1000 + llm.MAX_TOKENS)
        self.assertEqual(r["bound"], llm._bound(llm.MAX_TOKENS, "sys", [], msgs))
        self.assertEqual(r["actual"], 640)


class Failures(Base):
    def setUp(self):
        super().setUp()
        self.rid = self.core.begin("lease", OWNER, "task", ref="lease:f")

    def test_a_cli_failure_before_the_model_ran_releases(self):
        self.assertIsNone(self.core.admit(500, model="codex:m"))
        self.core.call_failed(LLMError("Codex isn't signed in on this login: sign in again under Agents → My logins."))
        self.assertEqual(self.hold()[0]["state"], "released")

    def test_any_other_cli_failure_is_unmetered_never_zero(self):
        self.assertIsNone(self.core.admit(500, model="codex:m"))
        self.core.call_failed(LLMError("Codex failed: the model broke"))          # a turn.failed: it may have billed
        self.assertEqual(self.hold()[0]["state"], "unmetered")
        self.assertEqual(self.db.q("SELECT metering FROM ac_runs WHERE id=?", (self.rid,), one=True)["metering"], "unmetered")

    def test_a_bucket_with_unmetered_use_fails_closed(self):
        agent_core.register_bucket("t", lambda run: [{"limit": 10_000, "spent": 0, "runs": ("team=?", ("comp:5",)), "label": "Team budget",
                                                      "message": lambda n, h, e: "The team's token budget can't take this call."}] if run.get("team") == "comp:5" else [])
        self.db.q("INSERT INTO ac_runs (system, owner_id, kind, status, tokens, started, team, metering) VALUES ('teams', 1, 'task', 'done', 0, ?, 'comp:5', 'unmetered')", (time.time(),))
        self.core.drop_limit(OWNER, self.core.limits(OWNER)[0]["id"])
        r = self.core.begin("teams", OWNER, "task", ref="mw:5"); agent_core._local.run["team"] = "comp:5"
        self.db.q("UPDATE ac_runs SET team='comp:5' WHERE id=?", (r,))
        self.assertEqual(self.core.admit(100, model="m"), agent_core.VERIFY_STOP)  # unknown use under the bucket: UNKNOWN, never let through


class Structured(Base):
    def test_an_auto_structured_call_keeps_its_bound_and_an_answered_error_releases(self):
        from app import llm
        class Status(Exception): status_code = 500
        def boom(self, *a, **kw):
            try: raise Status("overloaded")
            except Status as e: raise LLMError("Claude answered 500") from e
        self.core.set_limit(OWNER, "system", "lease", 10_000_000, period="day", label="roomy", origin="manual", by="test")
        self.core.begin("lease", OWNER, "task", ref="lease:auto")
        p = Providers.__new__(Providers)
        with mock.patch.object(Providers, "resolve", lambda self, choice: ("anthropic", "test")), mock.patch.object(Providers, "_structured", boom):
            with self.assertRaises(LLMError): p.structured("auto", "sys", "prompt", {"type": "object"}, "result")
        h = self.hold()[0]
        self.assertEqual((h["model"], h["state"]), ("anthropic:test", "released"))   # resolved before the gate: bounded, so an answer releases
        self.assertIsNotNone(h["bound"])


class Migration(unittest.TestCase):
    def test_a_milestone_3_table_gains_reserved_and_holder_and_keeps_its_live_hold(self):
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        db = AuthDB(os.path.join(d.name, "a.db"))
        db.q("""CREATE TABLE ac_reservations (id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, run_id INTEGER, rkey TEXT UNIQUE,
                model TEXT, estimate INTEGER, bound INTEGER, actual INTEGER, state TEXT, created REAL, expires REAL, settled REAL, note TEXT)""")
        now = time.time()
        db.q("INSERT INTO ac_reservations (owner_id, run_id, rkey, model, estimate, state, created, expires) VALUES (1, 1, 'k', 'm', 700, 'held', ?, ?)", (now, now + 3600))
        agent_core._core = None
        self.addCleanup(lambda: setattr(agent_core, "_core", None))
        agent_core.init(db)                                                        # Milestone 4's start on a Milestone 3 database
        r = db.q("SELECT * FROM ac_reservations", one=True)
        self.assertEqual((r["estimate"], r["reserved"], r["state"], r["holder"]), (700, 700, "held", None))  # not lapsed: its lease (old expiry) is live
        self.assertEqual(agent_core.get()._held(1), 0)                            # (run 1 doesn't exist: nothing in scope)


WORKER = textwrap.dedent("""
    import json, sys, threading, time
    sys.path.insert(0, "/app/backend")
    from app.auth import AuthDB
    from app import agent_core
    path, who, start = sys.argv[1], sys.argv[2], float(sys.argv[3])
    core = agent_core.Core(AuthDB(path))
    while time.time() < start: time.sleep(.01)
    calls, lock, go = [], threading.Lock(), threading.Barrier(4)
    def w(i):
        core.begin("lease", 1, "task", ref=f"lease:{who}:{i}")
        go.wait()
        for _ in range(10):
            if core.admit(300, model="m"): break
            time.sleep(.05); core.used(300)
            with lock: calls.append(i)
        core.end("done")
    ts = [threading.Thread(target=w, args=(i,)) for i in range(4)]
    [t.start() for t in ts]; [t.join(60) for t in ts]
    print(json.dumps({"who": who, "calls": len(calls)}))
""")


class Processes(Base):
    def test_two_processes_never_overcommit(self):
        start = time.time() + 6
        ps = [subprocess.Popen([sys.executable, "-c", WORKER, self.path, w, str(start)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                               cwd="/app/backend") for w in ("P1", "P2")]
        outs = [p.communicate(timeout=90) for p in ps]
        calls = sum(json.loads(o.strip().splitlines()[-1])["calls"] for o, _ in outs)
        spent = self.db.q("SELECT COALESCE(SUM(tokens),0) AS n FROM ac_runs WHERE system='lease'", one=True)["n"]
        self.assertEqual((spent, calls), (900, 3), [e[-400:] for _, e in outs])
        self.assertEqual(self.hold(state="held"), [])
        print(f"\n[processes] 2 processes × 4 threads, limit 1,000, 300 a call: {spent:,} spent, {calls} calls")


if __name__ == "__main__":
    unittest.main()
