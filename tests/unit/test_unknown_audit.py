"""G5-2 final stabilization (Owner, 2026-11-11): what each consumer of the shared budget decision does with UNKNOWN.

UNKNOWN (agent_core: the token budget couldn't be verified) never authorizes a model call, never counts against an agent or a
model, never causes an immediate retry loop, keeps persistent holds, never silently releases blocked work, and has a recovery
path after verification succeeds. AXoR resumes only what it paused for verification; a person's pause stays a person's.
Autoloop, Competition teams and the Control Hub are covered in test_budget_verification.py and test_budget_safety.py."""
import json, os, sys, tempfile, time, types, unittest
from unittest import mock

from app import agent_core, missions, mining_director, swarm, workforce
from app.auth import AuthDB

sys.path.insert(0, os.path.dirname(__file__))
from test_budget_safety import OWNER, BoardFixture, spend  # noqa: E402
from test_budget_verification import Flaky  # noqa: E402
from test_mission_ref import WID  # noqa: E402

ME = {"id": OWNER, "username": "owner"}
UNKNOWN_ERR = "The model failed: " + agent_core.VERIFY_STOP


class MissionControl(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        self.core = agent_core.init(self.db)
        self.flaky = Flaky(self.db); self.core.db = self.flaky
        self.mx = missions.Missions(self.db, hub=None, wf=None, ia=None, mw=None)
        self.submitted = []
        self.mx._submit = lambda mid: self.submitted.append(mid)
        self.mx._stop_child = lambda m, how="cancel": None

    def tearDown(self):
        agent_core._core = None
        self.dir.cleanup()

    def mission(self, stage="plan", engine="direct", child=None):
        now = time.time()
        return self.db.q("""INSERT INTO mx_missions (user_id, title, goal, budget, constraints, status, stage, engine, child, attempts, created, updated)
                            VALUES (?, 'Pick a subnet', 'Which subnet?', 5.0, '', 'running', ?, ?, ?, 1, ?, ?) RETURNING id""",
                         (OWNER, stage, engine, child, now, now), one=True)["id"]

    def m(self, mid): return self.mx._m(mid)
    def errors(self, mid): return self.db.q("SELECT COUNT(*) n FROM mx_events WHERE mission_id=? AND kind='error'", (mid,), one=True)["n"]
    def age(self, mid): self.db.q("UPDATE mx_missions SET updated=? WHERE id=?", (time.time() - missions.VERIFY_RETRY - 1, mid))

    def test_unknown_pauses_uncounted_and_never_dead_letters(self):
        mid = self.mission()
        for _ in range(10): self.mx._fail_soft(mid, UNKNOWN_ERR)                      # ten times past the attempts policy
        m = self.m(mid)
        self.assertEqual((m["status"], m["failure"], m["attempts"], self.errors(mid)), ("paused", "verify", 1, 0))
        self.assertIn("resumes by itself", m["pause_reason"])

    def test_an_engines_work_ending_on_unknown_is_the_same_pause_not_a_failed_attempt(self):
        mid = self.mission(stage="execute", engine="workforce", child=7)
        self.mx._child = lambda m: ("failed", 0, agent_core.VERIFY_STOP)
        with mock.patch.object(self.mx, "_recover", side_effect=AssertionError("no recovery for UNKNOWN")):
            self.mx._watch(self.m(mid), time.time())
        m = self.m(mid)
        self.assertEqual((m["status"], m["failure"], self.errors(mid)), ("paused", "verify", 0))

    def test_auto_resume_only_after_a_fresh_allow_and_at_most_once_a_minute(self):
        mid = self.mission()
        self.mx._fail_soft(mid, UNKNOWN_ERR)
        self.flaky.down = True
        self.age(mid); self.mx._verify_resume(time.time())
        self.assertEqual((self.m(mid)["status"], self.submitted), ("paused", []))       # still UNKNOWN: waits
        self.flaky.down = False
        self.mx._verify_resume(time.time())
        self.assertEqual(self.submitted, [])                                             # just re-checked: not again before VERIFY_RETRY
        self.age(mid); self.mx._verify_resume(time.time())
        m = self.m(mid)
        self.assertEqual((m["status"], m["attempts"], self.submitted), ("running", 1, [mid]))  # resumed; the pause used no attempt (still 1)
        ev = self.db.q("SELECT text FROM mx_events WHERE mission_id=? AND kind='decision' ORDER BY id DESC LIMIT 1", (mid,), one=True)["text"]
        self.assertIn("AXoR (the budget check passed again) resumed", ev)

    def test_a_refusal_on_recheck_becomes_a_budget_pause_for_a_person(self):
        mid = self.mission()
        self.mx._fail_soft(mid, UNKNOWN_ERR)
        self.core.set_limit(OWNER, "mission", f"mx:{mid}", 100, period="total"); spend(self.db, 500, system="missions", corr=f"mx:{mid}")
        self.age(mid); self.mx._verify_resume(time.time())
        m = self.m(mid)
        self.assertEqual((m["status"], m["failure"], self.submitted), ("paused", "budget", []))
        self.core.set_limit(OWNER, "mission", f"mx:{mid}", 10_000_000, period="total")
        self.age(mid); self.mx._verify_resume(time.time())
        self.assertEqual((self.m(mid)["status"], self.submitted), ("paused", []))       # a budget pause waits for a person, raised or not

    def test_a_persons_pause_is_never_resumed_by_axor(self):
        mid = self.mission()
        self.mx.pause(ME, mid)                                                           # paused by the person
        other = self.mission()
        self.mx._fail_soft(other, UNKNOWN_ERR)
        self.mx.pause(ME, other)                                                         # a person's pause over a verification pause
        for x in (mid, other): self.age(x)
        for _ in range(3): self.mx._verify_resume(time.time() + 3600)
        self.assertEqual([(self.m(x)["status"], self.m(x)["failure"]) for x in (mid, other)], [("paused", None), ("paused", None)])
        self.assertEqual(self.submitted, [])

    def test_a_refusal_at_the_gateway_is_a_budget_hold_not_an_error(self):
        mid = self.mission()
        for _ in range(5): self.mx._fail_soft(mid, "The model failed: Over the global token budget of Cap: 9 of 1 tokens today.")
        m = self.m(mid)
        self.assertEqual((m["status"], m["failure"], self.errors(mid)), ("paused", "budget", 0))

    def test_resume_past_the_deadline_stays_paused_for_a_person(self):
        mid = self.mission()
        self.mx._fail_soft(mid, UNKNOWN_ERR)
        self.db.q("UPDATE mx_missions SET deadline=? WHERE id=?", (time.time() - 60, mid))
        self.age(mid); self.mx._verify_resume(time.time())
        m = self.m(mid)
        self.assertEqual((m["status"], m["failure"], self.submitted), ("paused", None, []))
        self.assertIn("deadline", m["pause_reason"])


class RunTables(unittest.TestCase):
    """Workforce and Agent Swarm keep their own run tables, read by the model router and the agents' scorecards."""
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        self.db.q("""CREATE TABLE wf_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, mission_id INTEGER, assignment_id INTEGER,
                     improvement_id INTEGER, agent TEXT, step TEXT, task TEXT, model TEXT, route TEXT, status TEXT, started REAL, finished REAL,
                     tokens INTEGER DEFAULT 0, score INTEGER, summary TEXT, error TEXT)""")
        self.db.q("CREATE TABLE sw_runs AS SELECT * FROM wf_runs WHERE 1=0")
        now = time.time()
        for status, err in (("done", None), ("failed", "The model returned an unreadable answer."),
                            ("failed", agent_core.VERIFY_STOP), ("failed", "Over the global token budget of Cap: 9 of 1 tokens today.")):
            for t in ("wf_runs", "sw_runs"):
                self.db.q(f"INSERT INTO {t} (user_id, agent, step, task, model, status, started, finished, tokens, error) VALUES (?,?,?,?,?,?,?,?,?,?)",
                          (OWNER, "analyst", "execute", "execute", "m1", status, now - 5, now, 10, err))

    def tearDown(self): self.dir.cleanup()

    def test_budget_stops_are_not_the_models_failures(self):
        raw = {"workforce": workforce.Workforce._stats, "swarm": swarm.Swarm._stats}
        for name, fn in raw.items():
            obj = types.SimpleNamespace(db=self.db)
            with mock.patch("app.model_router.stats_rows", side_effect=lambda rows: rows):
                rows = fn(obj, OWNER)
            r = next(x for x in rows if x["task"] == "execute")
            per = 1 if name == "workforce" else 2                                        # the swarm reads both tables
            self.assertEqual((r["n"], r["failed"]), (2 * per, 1 * per), name)            # one real failure counted; the two budget stops aren't


class SwarmAttempts(unittest.TestCase):
    def test_an_attempt_stopped_by_budget_uses_no_attempt_and_isnt_reassigned(self):
        s = object.__new__(swarm.Swarm)
        contract = {"id": 5, "key": "C1", "title": "Compare", "mode": "single", "agent": "analyst", "contenders": [], "attempts": 0,
                    "history": [], "budget_limit": 20_000}
        sets, events = [], []
        s._swarm = lambda sid: {"id": sid, "user_id": OWNER, "deadline": None}
        s._team = lambda uid: {"analyst": {"name": "Ana"}, "critic": {"name": "Cy"}}
        s._contracts = lambda sid: [contract]
        s._cset = lambda cid, **kw: (sets.append(kw), contract.update(kw))
        s._event = lambda *a, **k: events.append(a)
        s._check_cancel = lambda cx: None
        s._attempt = lambda *a, **k: {"status": "failed", "note": agent_core.VERIFY_STOP, "budget_stop": True, "agent": "analyst"}
        s._replacement = mock.Mock(side_effect=AssertionError("no reassignment"))
        s._evaluate = mock.Mock(side_effect=AssertionError("nothing to evaluate"))
        s._fulfil({"sid": 1, "owner": ME}, 1, 5)
        self.assertEqual(contract["attempts"], 0)                                        # the attempt it set (1) is given back
        self.assertEqual(contract["status"], "failed")
        self.assertIn("not counted against the agent", contract["note"])


class Director(BoardFixture):
    def test_no_report_run_starts_while_unknown_or_refused(self):
        self.db.q("""CREATE TABLE mw_reports (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, agent_id INTEGER, run_id INTEGER, ts REAL,
                     headline TEXT, body TEXT, asks TEXT, settled TEXT, status TEXT)""")
        for col in ("last_report REAL", "relay INTEGER DEFAULT 1"):
            try: self.db.q(f"ALTER TABLE mw_comps ADD COLUMN {col}")
            except Exception: pass  # noqa: BLE001
        self.db.q("UPDATE mw_comps SET last_report=0 WHERE id=?", (WID,))
        tid = self.queued("Waiting for the Director"); self.db.q("UPDATE mw_tasks SET status='blocked' WHERE id=?", (tid,))
        d = object.__new__(mining_director.Director)
        d.db, d.w = self.db, self.w
        self.w._over, self.w._model = (lambda w: False), (lambda c, a, *k: "fake:model")
        d._lead = lambda wid: {"id": 1, "name": "Gus"}
        started = []
        d._start = lambda w, c, lead, note="": started.append(w["id"]) or 1
        w = self.db.q("SELECT * FROM mw_comps WHERE id=?", (WID,), one=True)
        flaky = Flaky(self.db); self.core.db = flaky
        flaky.down = True
        d._tick_one(w)
        self.assertEqual(started, [])                                                    # UNKNOWN: no report run
        flaky.down = False
        self.core.set_limit(OWNER, "global", "*", 10, period="day"); spend(self.db, 100)
        d._tick_one(w)
        self.assertEqual(started, [])                                                    # REFUSE: none either
        self.core.set_limit(OWNER, "global", "*", 10_000_000, period="day")
        d._tick_one(w)
        self.assertEqual(started, [WID])                                                 # ALLOW: the report starts


if __name__ == "__main__":
    unittest.main()
