"""orchestrator.decide (G5-2 milestone 1, Owner D-015 D1/D2 and clarification A): one recovery decision for the Control Hub
dispatcher, Autoloop and Mission Control.

D1: a failure that isn't the work's own (a missing login, the provider, the environment) never counts against the agent; it
counts in platform reliability. D2: only transient causes retry by themselves, bounded, backed off and jittered, each retry with
an idempotency key; an immediate retry (timeout, network) is kept apart from a delayed recovery (rate limit, quota, restart,
busy sandbox); authentication, permission, missing capability, invalid input and tool failures stop with their remediation."""
import os, sys, tempfile, threading, time, types, unittest

from app import mining_autoloop, orchestrator as o
from app.auth import AuthDB

sys.path.insert(0, os.path.dirname(__file__))
from test_mission_ref import ME, WID, Base as BoardBase  # noqa: E402

NOT_SIGNED_IN = "Claude Code on the server isn't signed in. Run `claude setup-token` on any machine where you use Claude Code"


class Table(unittest.TestCase):
    CASES = [  # (error, status, canonical class, action, retries by itself)
        ("Claude Code timed out after 150 s", "failed", "transient", "retry_now", True),
        ("connection reset by peer", "failed", "transient", "retry_now", True),
        ("429 too many requests", "failed", "rate", "retry_later", True),
        ("Claude Code plan rate limit reached; runs resume after the reset", "failed", "quota", "retry_later", True),
        ("Stopped by a server restart.", "lost", "restart", "retry_later", True),
        ("The sandbox is busy (2 runs at once): try again in a few minutes.", "failed", "sandbox", "retry_later", True),
        ("gVisor isn't installed on the server yet", "failed", "sandbox", "stop", False),
        ("Over the agent token budget of Noor", "failed", "budget", "hold", False),
        ("Stopped at the task's token cap (105,043 of 60,000 tokens)", "failed", "cap", "replan", False),
        ("401 unauthorized: invalid api key", "failed", "provider", "stop", False),
        (NOT_SIGNED_IN, "failed", "credential", "stop", False),
        ("the mcp tool failed: server unreachable", "failed", "tool", "stop", False),
        ("Docker is not set up on this server", "failed", "capability", "stop", False),
        ("The files come to 1200 kB; a run takes at most 900 kB.", "error", "input_too_large", "replan", False),
        ("Devon finished without filing the work.", "failed", "no_deliverable", "replan", False),
        ("The scoring code it was asked about doesn't exist.", "failed", "task", "replan", False),
    ]

    def test_every_class_gets_its_policy(self):
        for err, st, cls, action, retry in self.CASES:
            d = o.decide(st, err, key="ctl:t1")
            self.assertEqual((d["cls"], d["action"], d["retry"]), (cls, action, retry), err)

    def test_only_transient_causes_retry_by_themselves(self):
        retrying = {o.decide(st, err)["cls"] for err, st, *_ in self.CASES if o.decide(st, err)["retry"]}
        self.assertEqual(retrying, {"transient", "rate", "quota", "restart", "sandbox"})
        for k in ("provider", "credential", "tool", "capability", "input_too_large"):  # D2: stop or replan, never retried blindly
            self.assertNotIn(o.RECOVERY_POLICY[k]["action"], ("retry_now", "retry_later"), k)

    def test_immediate_retries_are_kept_apart_from_delayed_recovery(self):
        now = o.decide("failed", "Claude Code timed out after 150 s", key="k")
        later = o.decide("failed", "429 too many requests", key="k")
        quota = o.decide("failed", "plan rate limit reached", key="k")
        self.assertEqual((now["action"], later["action"], quota["action"]), ("retry_now", "retry_later", "retry_later"))
        self.assertLess(now["delay"], 60)
        self.assertGreaterEqual(later["delay"], 300)        # a delayed recovery never comes before its base wait
        self.assertGreaterEqual(quota["delay"], 3600)

    def test_backoff_is_bounded_exponential_and_jittered_deterministically(self):
        waits = [o.decide("failed", "timed out", tries=n, key="ctl:t7")["delay"] for n in range(3)]
        for n, w in enumerate(waits):
            base = min(900, 30 * 2 ** n)
            self.assertTrue(base * 0.8 - 1 <= w <= base * 1.2 + 1, (n, w))
        self.assertEqual(waits, [o.decide("failed", "timed out", tries=n, key="ctl:t7")["delay"] for n in range(3)])  # same key, same moment
        self.assertNotEqual(o.decide("failed", "timed out", key="ctl:t7")["delay"], o.decide("failed", "timed out", key="ctl:t8")["delay"])
        self.assertLessEqual(o.decide("failed", "429", tries=10, key="x")["delay"], 3600 * 1.2)

    def test_spent_retries_stop_and_hand_over(self):
        d = o.decide("failed", "timed out", tries=3, key="k")
        self.assertEqual((d["retry"], d["action"], d["who"], d["policy"]), (False, "stop", "you", "retry_now"))
        self.assertIn("Retried 3 times", d["remediation"])

    def test_every_retry_has_an_idempotency_key(self):
        self.assertEqual(o.decide("failed", "timed out", tries=1, key="ctl:t5")["retry_key"], "ctl:t5:retry:2")
        self.assertIsNone(o.decide("failed", NOT_SIGNED_IN, key="ctl:t5")["retry_key"])

    def test_d1_a_missing_login_is_platform_reliability_not_the_agent(self):
        d = o.decide("failed", NOT_SIGNED_IN)
        self.assertEqual((d["agent_fault"], d["reliability"], d["who"]), (False, True, "you"))
        self.assertTrue(o.decide("failed", "The scoring code it was asked about doesn't exist.")["agent_fault"])


class AgentFault(unittest.TestCase):
    """D1 in the numbers: outcomes() and optimize() read the canonical class (legacy class for rows diagnosed before it)."""
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        self.db.q("""CREATE TABLE ac_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, system TEXT, kind TEXT, ref TEXT, corr TEXT,
                     agent_key TEXT, status TEXT, error TEXT, score REAL, tokens INTEGER, started REAL, finished REAL, model TEXT)""")
        self.o = o.Orchestrator(self.db)

    def tearDown(self): self.dir.cleanup()

    def test_sign_in_failures_count_in_reliability_not_against_the_agent(self):
        now = time.time()
        for err in [NOT_SIGNED_IN] * 4 + ["The scoring code it was asked about doesn't exist."]:
            self.db.q("INSERT INTO ac_runs (owner_id, system, kind, ref, agent_key, status, error, started) VALUES (7, 'teams', 'task', 'mw:1', 'devon', 'failed', ?, ?)",
                      (err, now))
        self.o.diagnose()
        runs = self.o.outcomes(7, now - 60)["runs"]
        self.assertEqual((runs["failure"], runs["environment"]), (1, 4))
        # 1 own failure of 5 runs is under optimize()'s 30 % "failing" bar; counted the legacy way (all 5 'task') Devon was "failing"
        self.assertFalse([a for a in self.o.optimize(7)["agents"] if a.get("kind") == "failing"])

    def test_old_diagnoses_get_their_canonical_class(self):
        now = time.time()
        self.db.q("INSERT INTO ac_runs (owner_id, system, kind, ref, status, error, started) VALUES (7, 'teams', 'task', 'mw:1', 'failed', ?, ?)", (NOT_SIGNED_IN, now))
        rid = self.db.q("SELECT MAX(id) i FROM ac_runs", one=True)["i"]
        self.db.q("INSERT INTO io_diag (run_id, owner_id, cls, ts) VALUES (?, 7, 'task', ?)", (rid, now))  # diagnosed before G5-1
        self.o.diagnose()
        self.assertEqual(self.db.q("SELECT canon FROM io_diag WHERE run_id=?", (rid,), one=True)["canon"], "credential")
        self.assertEqual(self.o.outcomes(7, now - 60)["runs"]["environment"], 1)


class AutoloopStops(BoardBase):
    """Autoloop: a missing login stops the task with its fix (not counted, no blind retry); a timeout retries shortly."""
    def setUp(self):
        super().setUp()
        have = {c["name"] for c in self.db.q("PRAGMA table_info(mw_tasks)")}  # the shared fixture already has note
        for col in ("retries INTEGER DEFAULT 0", "retry_at REAL", "fail_class TEXT", "question TEXT", "note TEXT", "hold TEXT"):
            if col.split()[0] not in have: self.db.q(f"ALTER TABLE mw_tasks ADD COLUMN {col}")
        self.db.q("ALTER TABLE mw_runs ADD COLUMN fail_class TEXT")
        self.db.q("ALTER TABLE mw_comps ADD COLUMN parallel INTEGER")
        self.db.q("""CREATE TABLE ml_policy (comp_id INTEGER PRIMARY KEY, reserve REAL, retries INTEGER, task_cap INTEGER, total_cap INTEGER,
                     queue_cap INTEGER, backlog_cap INTEGER, updated REAL, mode TEXT)""")
        self.db.q("""CREATE TABLE ml_state (comp_id INTEGER PRIMARY KEY, cool_until REAL, cool_reason TEXT, cool_n INTEGER DEFAULT 0,
                     plan_held TEXT, recovered INTEGER DEFAULT 0, recovered_at REAL, tick REAL)""")
        self.loop = object.__new__(mining_autoloop.Loop)
        self.loop.w, self.loop.db, self.loop.lk, self.loop.leases = self.w, self.db, threading.Lock(), {}

    def working(self, title):
        tid = self.task(title, status="working")
        rid = self.db.q("INSERT INTO mw_runs (comp_id, task_id, status, started) VALUES (?, ?, 'failed', ?) RETURNING id", (WID, tid, time.time()), one=True)["id"]
        return tid, rid

    def test_a_missing_login_stops_the_task_with_its_fix_and_is_not_counted(self):
        tid, rid = self.working("Bench the candidate")
        self.assertTrue(self.loop.failed(tid, rid, NOT_SIGNED_IN, "failed"))  # True: handled, not counted against the task
        t = self.db.q("SELECT status, question, retries FROM mw_tasks WHERE id=?", (tid,), one=True)
        self.assertEqual((t["status"], t["retries"]), ("blocked", 0))
        self.assertIn("Login or credential missing", t["question"])
        self.assertGreater(self.loop._state(WID)["cool_until"] or 0, time.time())  # nothing new starts on that login meanwhile

    def test_a_timeout_retries_shortly(self):
        tid, rid = self.working("Bench the candidate")
        self.assertTrue(self.loop.failed(tid, rid, "Claude Code timed out after 150 s", "failed"))
        t = self.db.q("SELECT status, hold, retry_at, retries FROM mw_tasks WHERE id=?", (tid,), one=True)
        self.assertEqual((t["status"], t["hold"], t["retries"]), ("todo", "retry", 1))
        self.assertLess(t["retry_at"] - time.time(), 60)


class MissionPauses(unittest.TestCase):
    def test_mission_control_pauses_on_a_missing_login_instead_of_retrying(self):
        from app import missions
        m = {"id": 3, "attempts": 1, "history": [{}], "policy": None}
        mx = object.__new__(missions.Missions)
        events = []
        mx._set = lambda mid, **kw: None
        mx._event = lambda mid, stage, kind, text: events.append(text)
        mx._pol = lambda m: {"attempts": 3, "recover": "auto"}
        self.assertEqual(mx._recover(m, NOT_SIGNED_IN), "pause")
        self.assertTrue(any("Login or credential missing" in e for e in events))
        self.assertEqual(mx._recover(dict(m, history=[{}]), "Claude Code timed out after 150 s"), "verify")  # a mission deadline delivers, as before


if __name__ == "__main__":
    unittest.main()
