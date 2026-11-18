"""orchestrator.py (AXoR G5, the Unified Intelligence Orchestrator), against the G5 acceptance tests:
1 retrieval benchmark, 2 every finished run scored or excluded with a reason, 3 failed runs get accurate terminal outcomes,
4 a complete improvement experiment, 5 reproducible comparisons, 6 promotion and rollback, 7 budget limits enforced at the gateway,
8 sandbox failures classified and recoverable, 9 one mission through the six layers, 10 human approval gates; plus idempotent
events, retries and dead letters."""
import json, os, tempfile, time, unittest

os.environ.setdefault("KNOWLEDGE_INDEX", "0"); os.environ.setdefault("KNOWLEDGE_SYNC", "0")

from fastapi import HTTPException

from app import agent_core, agent_studio, evolution as evo, intel_layers, llm, mission_intel, missions, orchestrator as orc
from app.auth import AuthDB
from app.mining_autoloop import classify as autoloop_class
from test_evolution import FakeHub, Ov  # the Evolution Lab's scripted model: "cite sources" answers score 85, others 60

ME = {"id": 7, "username": "leo", "role": "admin"}
DAY = 86400


class G5(unittest.TestCase):
    """A fresh database with the agent core and the orchestrator on it; the module globals are put back afterwards."""
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        self.db.q("INSERT INTO users (id, username, pw_hash, created, role) VALUES (7, 'leo', 'x', ?, 'admin')", (time.time(),))
        self.saved = (agent_core._core, list(agent_core._resolvers), orc._orc)
        agent_core._resolvers.clear()
        self.core = agent_core.init(self.db)

    def tearDown(self):
        agent_core._local.run = None
        agent_core._core, orc._orc = self.saved[0], self.saved[2]
        agent_core._resolvers[:] = self.saved[1]
        try: self.db.db.close()  # PX-R13: on Postgres the connection would otherwise live until the collector runs
        except Exception: pass  # noqa: BLE001
        self.dir.cleanup()

    def run_row(self, **kw):
        r = {"system": "workforce", "owner_id": 7, "kind": "execute", "status": "done", "tokens": 100, "started": time.time() - 3 * DAY,
             "finished": time.time() - 3 * DAY + 60, **kw}
        cols = ",".join(r)
        return self.db.q(f"INSERT INTO ac_runs ({cols}) VALUES ({','.join('?' * len(r))}) RETURNING id", tuple(r.values()), one=True)["id"]

    def ev_row(self, rid): return self.db.q("SELECT * FROM io_evals WHERE run_id=?", (rid,), one=True)


class Coverage(G5):
    """2 and 3: every finished run scored or excluded with its reason; failures classified with a recovery; dead runs closed."""
    def setUp(self):
        super().setUp()
        self.o = orc.init(self.db)
        q = self.db.q
        q("CREATE TABLE wf_missions (id INTEGER PRIMARY KEY, score INTEGER, status TEXT)")
        q("CREATE TABLE wf_runs (id INTEGER PRIMARY KEY, mission_id INTEGER, score INTEGER)")
        q("INSERT INTO wf_missions VALUES (1, NULL, 'running'), (5, NULL, 'running')")
        q("INSERT INTO wf_runs VALUES (11, 1, 72), (12, 5, NULL)")

    def test_every_finished_run_is_scored_or_excluded_with_a_reason(self):
        chat = self.run_row(system="hub", kind="chat", ref=None)
        early = self.run_row(system="other", kind="earlier", ref=None)
        rate = self.run_row(status="failed", ref="wf:99", error="Anthropic: 429 rate limit reached", agent_key="workforce:3")
        wf = self.run_row(ref="wf:11", corr="wfm:1")
        plan = self.run_row(system="missions", kind="plan", ref="mx:1", corr="mx:1", score=80)
        exe = self.run_row(system="missions", kind="execute", ref="mx:1", corr="mx:1")
        ver = self.run_row(system="missions", kind="verify", ref="mx:1", corr="mx:1")
        child = self.run_row(ref="wf:12", corr="mx:1")
        co = self.run_row(system="company", kind="task", ref="co:4")
        fresh = self.run_row(ref="wf:12", corr="wfm:5", started=time.time() - 60, finished=time.time() - 30)
        self.o.evaluate()
        st = lambda rid: (self.ev_row(rid) or {}).get("state")
        self.assertEqual(st(chat), "excluded"); self.assertIn("chat", self.ev_row(chat)["reason"])
        self.assertEqual(st(early), "excluded")
        self.assertEqual(st(rate), "excluded"); self.assertIn("rate limited", self.ev_row(rate)["reason"])
        self.assertEqual((st(wf), self.ev_row(wf)["score"]), ("scored", 72))
        self.assertEqual(self.db.q("SELECT score FROM ac_runs WHERE id=?", (wf,), one=True)["score"], 72)  # the router learns from it too
        self.assertEqual(st(plan), "scored")
        self.assertEqual((st(exe), self.ev_row(exe)["score"]), ("scored", 80))  # the deliverable earned the independent check's score
        self.assertEqual(st(ver), "excluded")
        self.assertEqual((st(child), self.ev_row(child)["score"]), ("scored", 80))  # a child engine's run: its mission's check
        self.assertIn("mx:1", self.ev_row(child)["source"])
        self.assertEqual(st(co), "gap"); self.assertIn("company evaluator agent's score", self.ev_row(co)["reason"])  # its evaluator gave none in time
        self.assertIsNone(self.ev_row(fresh))  # its verifier may still score it
        self.db.q("UPDATE ac_runs SET started=?, finished=? WHERE id=?", (time.time() - DAY, time.time() - DAY, fresh))
        self.o.evaluate()
        self.assertEqual(st(fresh), "gap"); self.assertIn("No verdict within 6 hours from the Workforce reviewer", self.ev_row(fresh)["reason"])
        self.db.q("UPDATE ac_runs SET score=55 WHERE id=?", (co,))  # a verdict that comes later turns a gap into a score
        self.o.evaluate()
        self.assertEqual(st(co), "scored")
        cov = self.o.coverage(7, time.time() - 7 * DAY)
        self.assertEqual(cov["finished"], 10)
        self.assertEqual(cov["waiting"], 0)
        self.assertEqual(cov["scored"] + cov["excluded"] + cov["gap"], 10)
        self.assertEqual(cov["gap"], 1)

    def test_failed_runs_get_a_class_and_a_recovery_and_dead_runs_are_closed(self):
        over = "Over the mission token budget of Mission #3: 1,200 of 1,000 tokens (Intelligence layers → Budgets). This work stops before its next model call."
        b = self.run_row(status="failed", ref="mx:3", error=over)
        p = self.run_row(status="failed", ref="wf:7", error="401 Unauthorized: invalid x-api-key")
        sb = self.run_row(status="failed", ref="mw:4", system="teams", error="The sandbox is busy (2 runs at once): try again in a few minutes.")
        dead = self.run_row(status="running", system="teams", ref="mw:5", started=time.time() - 13 * 3600, finished=None)
        alive = self.run_row(status="running", system="teams", ref="mw:6", started=time.time() - 60, finished=None)
        host = self.run_row(status="running", system="workflow", ref="mb:1", started=time.time() - 20 * 3600, finished=None)
        self.assertEqual(self.o.close_stale(), 1)
        self.o.diagnose()
        d = lambda rid: self.db.q("SELECT * FROM io_diag WHERE run_id=?", (rid,), one=True)
        self.assertEqual((d(b)["cls"], d(b)["recoverable"]), ("budget", 1))
        self.assertEqual((d(p)["cls"], d(p)["recoverable"]), ("provider", 0))
        self.assertEqual((d(sb)["cls"], d(sb)["recoverable"]), ("sandbox", 1))
        self.assertIn("SANDBOX_MAX_RUNS", d(sb)["recovery"])
        self.assertEqual(d(dead)["cls"], "restart")
        self.assertIn("No end was recorded", self.db.q("SELECT error FROM ac_runs WHERE id=?", (dead,), one=True)["error"])
        self.assertEqual(self.db.q("SELECT status FROM ac_runs WHERE id=?", (alive,), one=True)["status"], "running")
        self.assertEqual(self.db.q("SELECT status FROM ac_runs WHERE id=?", (host,), one=True)["status"], "running")


class Outcomes(G5):
    """Every run's final outcome reconciled (success, partial, failure, stopped, excluded, unsettled add up to the finished runs),
    and recalled experiences settled from the work's own final record when its system didn't settle them."""
    def test_finished_runs_fall_in_exactly_one_outcome(self):
        o = orc.init(self.db)
        for kw in ({"score": 90}, {"score": 60}, {"score": 20}, {"status": "failed", "error": "boom"}, {"status": "lost"}, {"status": "cancelled"},
                   {"system": "hub", "kind": "chat"}, {"system": "company", "kind": "task", "ref": "co:1"}, {"status": "running", "finished": None},
                   {"status": "failed", "error": "401 Unauthorized: invalid x-api-key"}):
            self.run_row(**kw)
        o.evaluate()
        out = o.outcomes(7, time.time() - 7 * DAY)["runs"]
        self.assertEqual(out, {"success": 1, "partial": 1, "failure": 1, "environment": 0, "stopped": 1, "reviewed": 0, "excluded": 1, "unsettled": 4})  # failures not classified yet
        o.diagnose()
        out = o.outcomes(7, time.time() - 7 * DAY)["runs"]
        self.assertEqual(out, {"success": 1, "partial": 1, "failure": 2, "environment": 2, "stopped": 1, "reviewed": 0, "excluded": 1, "unsettled": 1})  # boom: the work's; lost (a restart) and a refused key: not
        cov = o.coverage(7, time.time() - 7 * DAY)
        self.assertEqual(sum(out.values()), cov["finished"])
        self.assertEqual(cov["of_finished_pct"], round(100 * cov["scored"] / cov["finished"]))  # both: of every finished run, and of the scoreable

    def test_open_recalls_settle_from_the_works_final_record(self):
        from app.experience import Experience
        class KB(Experience):
            def __init__(s, db): s.db = db; s._has = lambda t: bool(db.q("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,), one=True))
        KB(self.db)._exp_init()
        o = orc.init(self.db)
        q, old = self.db.q, time.time() - 2 * 3600
        q("CREATE TABLE mx_missions (id INTEGER PRIMARY KEY, user_id INTEGER, status TEXT, outcome TEXT)")
        q("CREATE TABLE wf_missions (id INTEGER PRIMARY KEY, user_id INTEGER, status TEXT, verdict TEXT)")
        q("CREATE TABLE mw_tasks (id INTEGER PRIMARY KEY, status TEXT)")
        q("INSERT INTO mx_missions VALUES (1, 7, 'cancelled', NULL), (2, 7, 'delivered', 'unverified'), (3, 7, 'running', NULL), (4, 7, 'failed', NULL)")
        q("INSERT INTO wf_missions VALUES (1, 7, 'done', NULL), (2, 7, 'failed', NULL), (3, 7, 'done', 'pass')")
        q("INSERT INTO mw_tasks VALUES (1, 'done'), (2, 'blocked')")
        ctx = ["mx:1", "mx:2", "mx:3", "mx:4", "mx:99", "wf:1", "wf:2", "wf:3", "mw:1", "mw:2"]
        for c in ctx: q("INSERT INTO ex_uses (user_id, ref, context, ts) VALUES (7, 'mxl:1', ?, ?)", (c, old))
        q("INSERT INTO ex_uses (user_id, ref, context, ts) VALUES (7, 'mxl:1', 'mx:4', ?)", (time.time(),))  # too recent: its own system may still settle it
        self.assertEqual(o.settle_outcomes(), 8)  # contexts settled; mx:3 runs on, mw:2 waits on you
        got = {r["context"]: r["outcome"] for r in q("SELECT context, outcome FROM ex_uses WHERE ts<?", (time.time() - 3600,))}
        self.assertEqual(got, {"mx:1": "excluded", "mx:2": "excluded", "mx:3": None, "mx:4": "failure", "mx:99": "excluded",
                               "wf:1": "excluded", "wf:2": "failure", "wf:3": "success", "mw:1": "success", "mw:2": None})
        self.assertEqual(o.settle_outcomes(), 0)  # idempotent: only open rows
        self.assertEqual(o.outcomes(7, time.time() - DAY)["recalls"], {"success": 2, "partial": 0, "failure": 2, "excluded": 4, "open": 3})


class Recovery(G5):
    """Recover: a recoverable failed run again through its own system, once; never what retrying can't fix, never team work."""
    def setUp(self):
        super().setUp()
        q = self.db.q
        q("CREATE TABLE ia_tasks (id INTEGER PRIMARY KEY, status TEXT)")
        q("CREATE TABLE wf_runs (id INTEGER PRIMARY KEY, mission_id INTEGER, score INTEGER)")
        q("CREATE TABLE wf_missions (id INTEGER PRIMARY KEY, score INTEGER, status TEXT)")
        q("CREATE TABLE ctl_tasks (id INTEGER PRIMARY KEY, status TEXT)")
        q("INSERT INTO ia_tasks VALUES (4, 'paused')"); q("INSERT INTO wf_runs VALUES (8, 3, NULL), (9, 6, NULL)")
        q("INSERT INTO wf_missions VALUES (3, NULL, 'failed'), (6, NULL, 'done')"); q("INSERT INTO ctl_tasks VALUES (5, 'failed')")
        self.calls = []
        c = self.calls
        class Sys:
            def start_task(self, me, tid): c.append(("task", tid))
            def resume(self, me, tid): c.append(("resume", tid))
            def rerun(self, me, mid): c.append(("rerun", mid)); return {"id": 99}
        self.o = orc.init(self.db)
        self.o.systems = {"control": Sys(), "infiagent": Sys(), "workforce": Sys(), "missions": Sys()}

    def test_recover_through_each_system(self):
        t = self.run_row(status="failed", system="other", ref="ctl:t5", error="Connection reset by peer")
        ia = self.run_row(status="failed", system="longtask", ref="ia:4", error="Stopped by a server restart.")
        wf = self.run_row(status="failed", ref="wf:8", error="503 Service Unavailable")
        wf2 = self.run_row(status="failed", ref="wf:8", error="timed out")
        team = self.run_row(status="failed", system="teams", ref="mw:2", error="timed out")
        bad = self.run_row(status="failed", ref="wf:8", error="401 invalid x-api-key")
        finished = self.run_row(status="failed", ref="wf:9", error="timed out")  # its Workforce mission went on to finish: nothing to recover
        self.o.diagnose()
        got = {x["run_id"] for x in self.o.recoverable(7, 0)}
        self.assertEqual(got, {t, ia, wf, wf2})  # team work is Autoloop's; a refused key isn't fixed by retrying
        self.o.recover(ME, t); self.o.recover(ME, ia); self.o.recover(ME, wf)
        self.assertEqual(self.calls, [("task", 5), ("resume", 4), ("rerun", 3)])
        with self.assertRaises(HTTPException): self.o.recover(ME, wf2)  # the same work: recovered already
        with self.assertRaises(HTTPException): self.o.recover(ME, bad)
        with self.assertRaises(HTTPException): self.o.recover(ME, team)
        with self.assertRaises(HTTPException): self.o.recover(ME, finished)
        self.assertEqual(len(self.db.q("SELECT 1 FROM io_audit WHERE action='run.recovered'")), 3)


class Optimize(G5):
    def test_recommendations_from_the_ledger(self):
        self.o = orc.init(self.db)
        q, now = self.db.q, time.time()
        for i in range(6):
            self.run_row(agent_key="workforce:1", score=90, tokens=1000, model="m:a", kind="execute")
            self.run_row(agent_key="workforce:2", score=40, tokens=1000, model="m:b", kind="execute")
            self.run_row(agent_key="workforce:3", score=70, tokens=1000, model="m:b", kind="execute")
            self.run_row(agent_key="workforce:4", score=65, tokens=9000, model="m:b", kind="execute")
            self.run_row(agent_key="workforce:5", status="failed", error="429 rate limit", model="m:b", kind="execute")  # the provider's, not the agent's
        q("INSERT INTO ac_agents (key, system, owner_id, name, status) VALUES ('workforce:9', 'workforce', 7, 'Idle Ida', 'active')")
        self.o.diagnose()
        o = self.o.optimize(7)
        kinds = {a["agent"]: a["kind"] for a in o["agents"]}
        self.assertEqual(kinds, {"workforce:2": "under", "workforce:4": "costly", "workforce:1": "strong"})
        self.assertEqual((o["idle"], o["idle_names"]), (1, ["Idle Ida"]))
        self.assertEqual((o["models"][0]["used"], o["models"][0]["best"]), ("m:b", "m:a"))


class Prune(G5):
    def test_old_rows_go(self):
        self.o = orc.init(self.db)
        old = time.time() - (orc.KEEP_DAYS + 1) * DAY
        self.o.emit(7, "x", "old"); self.o.emit(7, "x", "new")
        self.db.q("UPDATE io_events SET status='done', created=? WHERE key='old'", (old,))
        self.db.q("INSERT INTO io_evals (run_id, owner_id, state, ts) VALUES (1, 7, 'scored', ?), (2, 7, 'scored', ?)", (old, time.time()))
        self.assertEqual(self.o.prune(), 2)
        self.assertEqual([r["key"] for r in self.db.q("SELECT key FROM io_events")], ["new"])
        self.assertEqual(self.o.prune(), 0)  # once an hour


class Events(G5):
    def setUp(self):
        super().setUp()
        self.o = orc.init(self.db)

    def test_idempotent_retried_then_dead_letter_then_retry_by_hand(self):
        self.assertIsNotNone(self.o.emit(7, "test.flaky", "k1", corr="mx:1"))
        self.assertIsNone(self.o.emit(7, "test.flaky", "k1", corr="mx:1"))  # the same key: once
        calls = []
        def flaky(e, p):
            calls.append(1)
            raise RuntimeError("downstream is down")
        self.o._on_test_flaky = flaky
        for _ in range(orc.MAX_ATTEMPTS):
            self.db.q("UPDATE io_events SET next_at=0")
            self.o.process()
        e = self.db.q("SELECT * FROM io_events WHERE key='k1'", one=True)
        self.assertEqual((e["status"], e["attempts"], len(calls)), ("dead", orc.MAX_ATTEMPTS, orc.MAX_ATTEMPTS))
        self.assertIn("downstream is down", e["error"])
        self.assertTrue(self.db.q("SELECT 1 FROM io_audit WHERE action='event.dead_letter'", one=True))
        self.o._on_test_flaky = lambda e, p: {"ok": True}
        got = self.o.retry_event(ME, e["id"])
        self.assertEqual(got["status"], "done")

    def test_a_restart_puts_a_running_handler_back(self):
        self.o.emit(7, "test.x", "k2")
        self.db.q("UPDATE io_events SET status='running' WHERE key='k2'")
        orc.Orchestrator(self.db)
        self.assertEqual(self.db.q("SELECT status FROM io_events WHERE key='k2'", one=True)["status"], "pending")


class Budgets(G5):
    """7: hard limits at the gateway, before every model call, for a mission (by correlation), an agent, a contract, per call."""
    def setUp(self):
        super().setUp()
        self.o = orc.init(self.db)
        q = self.db.q
        q("CREATE TABLE wf_runs (id INTEGER PRIMARY KEY, mission_id INTEGER, score INTEGER)")
        q("CREATE TABLE sw_runs (id INTEGER PRIMARY KEY, swarm_id INTEGER, contract_id INTEGER, score INTEGER)")
        q("INSERT INTO wf_runs VALUES (1, 5, NULL), (2, 5, NULL)")
        q("INSERT INTO sw_runs VALUES (1, 2, 4, NULL)")

    def tearDown(self):
        agent_core.end("done")
        super().tearDown()

    def test_no_limit_changes_nothing(self):
        agent_core.begin("workforce", 7, "execute", ref="wf:1")
        agent_core.used(10 ** 9)
        self.assertIsNone(agent_core.over())
        self.assertIsNone(agent_core.call_cap())

    def test_a_missions_limit_covers_its_child_engines_runs(self):
        self.o.launched(7, 9, "workforce", 5, limit_tokens=1000)  # Mission Control launched Workforce mission 5 for mission 9
        agent_core.begin("workforce", 7, "execute", ref="wf:1", agent_key="workforce:3")
        self.assertEqual(self.db.q("SELECT corr FROM ac_runs WHERE ref='wf:1'", one=True)["corr"], "mx:9")
        agent_core.used(600)
        self.assertIsNone(agent_core.over())
        agent_core.end("done")
        agent_core.begin("workforce", 7, "review", ref="wf:2")  # another of the child's runs: the same mission's budget
        agent_core.used(500)
        why = agent_core.over()
        self.assertIn("1,100 of 1,000 tokens", why)
        self.assertEqual(autoloop_class(why), "budget")            # Autoloop: not the task's fault
        self.assertEqual(missions.classify(why), "budget")         # Mission Control: pause, not retry
        with self.assertRaises(llm.LLMError): llm._gate()          # the call is refused before it's made
        self.assertTrue(self.db.q("SELECT 1 FROM ac_limit_hits WHERE kind='tokens'", one=True))
        other = self.db.q("SELECT corr FROM ac_runs WHERE ref='wf:2'", one=True)
        self.assertEqual(other["corr"], "mx:9")

    def test_raising_the_missions_budget_raises_its_gateway_limit(self):
        self.o.launched(7, 9, "longtask", 4, limit_tokens=1000)
        self.o.mission_budget(7, 9, 2.0, 1.0)  # $2 at $1 per million tokens
        self.assertEqual(self.db.q("SELECT tokens FROM ac_limits WHERE key='mx:9'", one=True)["tokens"], 2_000_000)
        self.o.mission_budget(7, 10, 2.0, 1.0)  # a mission without a gateway limit gets none
        self.assertFalse(self.db.q("SELECT 1 FROM ac_limits WHERE key='mx:10'", one=True))

    def test_runs_that_began_before_the_link_are_recorrelated(self):
        agent_core.begin("workforce", 7, "execute", ref="wf:1")
        agent_core.end("done")
        self.assertEqual(self.db.q("SELECT corr FROM ac_runs WHERE ref='wf:1'", one=True)["corr"], "wfm:5")
        self.o.link("wfm:5", "mx:9", 7)
        self.o.relink()
        self.assertEqual(self.db.q("SELECT corr FROM ac_runs WHERE ref='wf:1'", one=True)["corr"], "mx:9")

    def test_agent_day_contract_and_per_call_limits(self):
        self.core.set_limit(7, "agent", "workforce:3", tokens=300, period="day")
        agent_core.begin("workforce", 7, "execute", ref="wf:1", agent_key="workforce:3")
        agent_core.used(300)
        self.assertIn("agent token budget", agent_core.over())
        agent_core.end("done")
        agent_core.begin("workforce", 7, "execute", ref="wf:1", agent_key="workforce:4")  # another agent: not under it
        self.assertIsNone(agent_core.over())
        agent_core.end("done")
        self.core.set_limit(7, "contract", "swc:4", tokens=50)
        agent_core.begin("workforce", 7, "swarm-execute", ref="sw:1")
        self.assertEqual(self.db.q("SELECT contract FROM ac_runs WHERE ref='sw:1'", one=True)["contract"], "swc:4")
        agent_core.used(60)
        self.assertIn("task contract token budget", agent_core.over())
        agent_core.end("done")
        self.core.set_limit(7, "system", "missions", per_call=2000)
        agent_core.begin("missions", 7, "plan", ref="mx:1")
        self.assertEqual(agent_core.call_cap(), 2000)
        self.assertEqual(llm._max_out(), 2000)                     # the output of each call is capped at it
        agent_core.used(1500)
        self.assertIsNone(agent_core.over())
        agent_core.used(2500)                                      # one call over it: the run makes no more calls
        self.assertIn("per-call token budget", agent_core.over())
        self.assertEqual(autoloop_class(agent_core.over()), "budget")
        st = {L["scope"]: L for L in self.core.limit_status(7)}
        self.assertEqual(st["contract"]["spent"], 60)
        self.assertGreaterEqual(st["agent"]["blocked_7d"], 1)

    def test_the_owners_daily_limit_message_is_a_budget_stop(self):
        self.core.set_cap(7, 100, "leo")
        agent_core.begin("teams", 7, "task", ref="mw:1")
        agent_core.used(150)
        why = agent_core.over()
        self.assertIn("150 of your 100", why)
        self.assertEqual(autoloop_class(why), "budget")  # it used to read as the task's own failure


class Sandbox(G5):
    """8: sandbox runs that couldn't run are classified, and the recoverable ones run again."""
    def setUp(self):
        super().setUp()
        q = self.db.q
        q("""CREATE TABLE mw_sbx (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, command TEXT, services TEXT, status TEXT, error TEXT, started REAL)""")
        now = time.time()
        for st, err in (("error", "This team has internet on, but the run can't have it: gVisor isn't installed on the server yet, and runs with internet only start under it: run k8s/install-gvisor.sh as root."),
                        ("error", "The sandbox is busy (2 runs at once): try again in a few minutes."),
                        ("error", "Stopped by a server restart."), ("timeout", "The run took too long (or never started) and was stopped."),
                        ("failed", "")):
            q("INSERT INTO mw_sbx (comp_id, command, services, status, error, started) VALUES (3, 'pytest', '', ?, ?, ?)", (st, err, now))
        test = self
        class Work:
            def _own(self, me, wid):
                if wid != 3: raise HTTPException(404, "no")
            def run_sandbox(self, me, wid, b):
                test.db.q("INSERT INTO mw_sbx (comp_id, command, services, status, started) VALUES (?,?,'', 'running', ?)", (wid, b.command, time.time()))
        self.o = orc.init(self.db, work=Work())

    def test_classes_and_recovery(self):
        self.o.diagnose_sandbox()
        d = {r["sbx_id"]: r for r in self.db.q("SELECT * FROM io_sbx")}
        self.assertEqual([d[i]["cls"] for i in (1, 2, 3, 4)], ["gvisor", "busy", "restart", "timeout"])
        self.assertNotIn(5, d)  # its code failed: that's the code's result, not the sandbox's
        self.assertEqual(d[1]["recoverable"], 0); self.assertIn("install-gvisor.sh", d[1]["recovery"])
        with self.assertRaises(HTTPException) as c: self.o.retry_sandbox(ME, 1)
        self.assertEqual(c.exception.status_code, 409)  # running it again won't help
        got = self.o.retry_sandbox(ME, 2)
        self.assertEqual(got["retried_as"], 6)
        with self.assertRaises(HTTPException): self.o.retry_sandbox(ME, 2)  # once
        with self.assertRaises(HTTPException): self.o.retry_sandbox(ME, 5)  # not a sandbox failure


class Improvement(G5):
    """4, 5, 6, 10: an agent's low scores become a drafted proposal; the engine's experiment verifies it on a frozen dataset
    version; the policy promotes it; the comparison recomputes from its trials; the monitor sees a regression and rolls it back.
    Code, external, financial and critical changes are never promoted by policy."""
    def setUp(self):
        super().setUp()
        self.hub = FakeHub(self.db)
        self.db.q("""INSERT INTO custom_agents (id, owner_id, name, role, description, instructions, icon, color, face, kind, skills, examples, shared_with,
                     in_directory, status) VALUES (1, 7, 'Py', 'Python engineer', '', 'Answer briefly.', 'bot', 'violet', '', '', '[]', '[]', '[]', 0, 'live')""")
        self.studio = agent_studio.Studio(self.db, Ov(), self.hub)
        self.studio.agent = lambda me, key: {}
        self.ev = evo.Evolution(self.db, Ov(), self.hub, self.studio)
        self.o = orc.init(self.db, Ov(), None, self.ev)
        self.bench = self.ev.save_bench(ME, evo.BenchIn(name="Python", target_key="hub:1", cases=[{"prompt": f"Task {i}", "rubric": "Correct"} for i in range(3)]))

    def tearDown(self):
        self.ev.pool.shutdown(wait=True)
        super().tearDown()

    def settle(self):
        self.ev.pool.shutdown(wait=True)
        self.ev.pool = evo.ThreadPoolExecutor(2)

    def test_signal_to_promotion_to_monitored_rollback(self):
        self.ev.set_policy(ME, evo.PolicyIn(mode="auto"))
        for i in range(4): self.run_row(system="hub", kind="chat", ref=f"chat:{i}", agent_key="hub:1", score=40, started=time.time() - DAY - i)
        self.assertEqual(self.o.observe_signals(), 1)
        self.assertEqual(self.o.observe_signals(), 0)  # once a week per agent
        self.o.process()
        p = self.db.q("SELECT * FROM ev_proposals", one=True)
        self.assertEqual((p["origin"], p["status"], p["benchmark_id"]), ("drafted", "proposed", self.bench["id"]))
        self.assertEqual(self.ev.tick(), 1)  # the engine runs its experiment
        self.settle()
        p = self.ev.proposal(ME, p["id"])
        self.assertEqual((p["status"], p["decision"], p["basis"]), ("verified", None, "model_judged"))  # K-29: a model's judgment never promotes by itself
        self.assertEqual(self.hub._get(1)["instructions"], "Answer briefly.")
        p = self.ev.promote(ME, p["id"])  # the person's approval
        self.assertEqual((p["status"], p["decision"]), ("promoted", "human"))
        e = p["evidence"]
        self.assertEqual((e["baseline"], e["candidate"], e["dataset_version"]), (60, 85, 1))
        self.assertTrue(e["dataset_sha"])
        r = self.o.reproduce(ME, p["id"])  # 5: recomputed from its stored trials, on its frozen dataset version
        self.assertTrue(r["reproducible"], r["checks"])
        self.assertEqual(r["recomputed"]["candidate"], 85)
        self.assertEqual(self.hub._get(1)["instructions"], "Answer and cite sources.")
        self.o.observe_promotions(); self.o.process()
        w = self.db.q("SELECT * FROM io_monitor", one=True)
        self.assertEqual((w["state"], w["base_avg"], w["base_n"]), ("watching", 40, 4))
        for i in range(3): self.run_row(system="hub", kind="chat", ref=f"chat:a{i}", agent_key="hub:1", score=20, started=time.time() + 1)
        self.assertEqual(self.o.monitor(), 1)
        self.o.process()
        self.assertEqual(self.ev.proposal(ME, p["id"])["status"], "rolled_back")
        self.assertEqual(self.hub._get(1)["instructions"], "Answer briefly.")  # 6: back to the version before
        self.assertEqual(self.db.q("SELECT state FROM io_monitor", one=True)["state"], "rolled_back")
        self.assertTrue(self.db.q("SELECT 1 FROM ev_audit WHERE action='proposal.rolled_back' AND actor='Evolution Engine (monitor)'", one=True))
        self.db.q("UPDATE ev_trials SET score=0 WHERE arm='candidate'")  # tampered trials don't reproduce the stored verdict
        self.assertFalse(self.o.reproduce(ME, p["id"])["reproducible"])

    def test_a_regression_waits_for_a_person_unless_the_policy_is_auto(self):
        p = self.ev.propose(ME, evo.ProposalIn(target_key="hub:1", title="Cite", instructions="Answer and cite sources.", benchmark_id=self.bench["id"]))
        self.ev.run(ME, p["id"], evo.RunIn()); self.settle()
        self.ev.promote(ME, p["id"])
        for i in range(3): self.run_row(system="hub", kind="chat", ref=f"c{i}", agent_key="hub:1", score=90, started=time.time() - DAY)
        self.db.q("UPDATE ev_proposals SET promoted=? WHERE id=?", (time.time() - 3600, p["id"]))
        self.o.observe_promotions(); self.o.process()
        for i in range(3): self.run_row(system="hub", kind="chat", ref=f"d{i}", agent_key="hub:1", score=30, started=time.time())
        self.o.monitor(); self.o.process()
        self.assertEqual(self.ev.proposal(ME, p["id"])["status"], "promoted")
        self.assertEqual(self.db.q("SELECT state FROM io_monitor", one=True)["state"], "regressed")
        self.assertTrue(self.db.q("SELECT 1 FROM io_audit WHERE action='monitor.held'", one=True))

    def test_a_change_with_nothing_scored_before_it_is_not_watched_forever(self):
        p = self.ev.propose(ME, evo.ProposalIn(target_key="hub:1", title="Cite", instructions="Answer and cite sources.", benchmark_id=self.bench["id"]))
        self.ev.run(ME, p["id"], evo.RunIn()); self.settle()
        self.ev.promote(ME, p["id"])
        self.o.observe_promotions(); self.o.process()
        self.assertEqual(self.db.q("SELECT state FROM io_monitor", one=True)["state"], "no_baseline")

    def test_a_chat_agent_is_watched_on_your_thumbs(self):
        q = self.db.q
        q("CREATE TABLE agent_conversations (id TEXT PRIMARY KEY, user_id INTEGER, agent TEXT, title TEXT, created REAL, updated REAL, messages TEXT)")
        rated = lambda ups, downs: json.dumps([{"role": "assistant", "meta": {"rating": 1}}] * ups + [{"role": "assistant", "meta": {"rating": -1}}] * downs)
        q("INSERT INTO agent_conversations VALUES ('a', 7, 'custom:1', '', ?, ?, ?)", (time.time() - DAY, time.time() - DAY, rated(4, 0)))
        p = self.ev.propose(ME, evo.ProposalIn(target_key="hub:1", title="Cite", instructions="Answer and cite sources.", benchmark_id=self.bench["id"]))
        self.ev.run(ME, p["id"], evo.RunIn()); self.settle()
        self.ev.promote(ME, p["id"])
        self.o.observe_promotions(); self.o.process()
        w = self.db.q("SELECT * FROM io_monitor", one=True)
        self.assertEqual((w["state"], w["basis"], w["base_avg"], w["base_n"]), ("watching", "ratings", 100, 4))
        q("INSERT INTO agent_conversations VALUES ('b', 7, 'custom:1', '', ?, ?, ?)", (time.time() + 1, time.time() + 1, rated(1, 3)))
        self.o.monitor(); self.o.process()
        self.assertEqual(self.db.q("SELECT state FROM io_monitor", one=True)["state"], "regressed")  # 25% thumbs-up after, 100% before; policy recommend: held

    def test_environmental_failures_dont_hide_low_scores(self):
        for i in range(4): self.run_row(system="hub", kind="chat", ref=f"r{i}", agent_key="hub:1", status="failed", error="429 rate limit", started=time.time() - DAY)
        for i in range(3): self.run_row(system="hub", kind="chat", ref=f"s{i}", agent_key="hub:1", score=30, started=time.time() - DAY)
        self.o.diagnose()
        s = self.o.signals(7)
        self.assertEqual(len(s), 1)
        self.assertEqual(s[0]["evidence"], ["average score 30/100 over 3 scored runs"])  # rate limits are the provider's, not the agent's

    def test_human_approval_gates(self):
        self.ev.set_policy(ME, evo.PolicyIn(mode="auto"))
        for risk in ("code", "external", "financial", "critical"):
            p = self.ev.propose(ME, evo.ProposalIn(target_key="hub:1", title=f"A {risk} change", change="Do it", risk=risk))
            with self.assertRaises(HTTPException): self.ev.run(ME, p["id"], evo.RunIn())  # never experimented on automatically
            self.ev.record_evidence(ME, p["id"], evo.EvidenceIn(test_set="held out", baseline=[50, 50, 50], candidate=[80, 80, 80]))
            self.ev._maybe_auto(ME, p["id"])
            self.assertEqual(self.ev.proposal(ME, p["id"])["status"], "verified")  # verified, still waiting for a person
            with self.assertRaises(HTTPException) as c: self.ev.promote(ME, p["id"], by_policy=True)
            self.assertEqual(c.exception.status_code, 403)
            self.assertEqual(self.ev.promote(ME, p["id"])["decision"], "human")
        q = self.ev.propose(ME, evo.ProposalIn(target_key="hub:1", title="Unmeasured", instructions="Answer and cite sources.", benchmark_id=self.bench["id"]))
        with self.assertRaises(HTTPException): self.ev.promote(ME, q["id"])  # never an unverified change

    def test_a_diagnosis_under_recommend_waits_for_approval_then_runs_its_experiment(self):
        self.db.q("DELETE FROM ev_benchmarks")  # nothing to measure on yet
        for i in range(4): self.run_row(system="hub", kind="chat", ref=f"chat:{i}", agent_key="hub:1", score=40, started=time.time() - DAY - i)
        self.o.observe_signals(); self.o.process()
        e = self.db.q("SELECT * FROM io_events WHERE kind='agent.signal'", one=True)
        self.assertEqual(e["status"], "done", e["error"])  # it used to be refused as "the same as the current version" and dead-lettered
        p = self.db.q("SELECT * FROM ev_proposals", one=True)
        self.assertEqual((p["origin"], p["status"], p["benchmark_id"]), ("diagnosis", "proposed", None))  # policy recommend: it waits for you
        with self.assertRaises(HTTPException): self.ev.run(ME, p["id"], evo.RunIn())  # a change in words has no candidate to measure
        r = self.o.approve_experiment(ME, p["id"])
        self.assertEqual(r["routed"], "evolution")
        self.settle()
        p = self.ev.proposal(ME, p["id"])
        b = self.db.q("SELECT * FROM ev_benchmarks WHERE id=?", (p["benchmark_id"],), one=True)
        self.assertEqual((b["origin"], b["target_key"]), ("drafted", "hub:1"))
        self.assertEqual(p["change"]["instructions"], "Answer and cite sources.")  # the candidate, drafted from the diagnosis
        self.assertIn(p["status"], ("verified", "not_better"))
        self.assertEqual((p["evidence"]["baseline"], p["evidence"]["candidate"]), (60, 85))
        self.assertTrue(p["evidence"]["dataset_sha"])  # measured on a frozen dataset version
        self.assertNotEqual(p["status"], "promoted")  # promotion is a separate decision
        self.o.observe_handoffs()
        self.assertEqual(next(k for k in self.o.handoffs(7, time.time() - 7 * DAY) if k["kind"] == "proposal.tested")["done"], 1)
        acts = [a["action"] for a in self.db.q("SELECT action FROM ev_audit ORDER BY id")]
        self.assertLess(acts.index("experiment.approved"), acts.index("experiment.started"))

    def test_other_targets_are_routed_or_explained(self):
        self.db.q("INSERT INTO ac_agents (key, system, owner_id, name, status) VALUES ('teams:4', 'teams', 7, 'Ana', 'active')")
        p = self.ev.propose(ME, evo.ProposalIn(target_key="teams:4", title="Fix", change="Do better"), origin="diagnosis")
        with self.assertRaises(HTTPException) as c: self.o.approve_experiment(ME, p["id"])
        self.assertEqual(c.exception.status_code, 409); self.assertIn("Upgrade sprint", c.exception.detail)

    def test_dead_lettered_diagnoses_go_again_after_the_fix(self):
        self.o.emit(7, "agent.signal", "sig:old", corr="hub:1", payload={"agent": "hub:1"})
        self.db.q("UPDATE io_events SET status='dead', attempts=5, error='The change is the same as the current version: edit the instructions or the skills.'")
        orc.init(self.db, Ov(), None, self.ev)
        self.assertEqual(self.db.q("SELECT status, attempts FROM io_events", one=True), {"status": "pending", "attempts": 0})

    def test_a_benchmark_edit_is_a_new_dataset_version(self):
        b = self.ev.save_bench(ME, evo.BenchIn(name="Python", target_key="hub:1", cases=[{"prompt": "Other", "rubric": "R"}]), self.bench["id"])
        v = self.db.q("SELECT version FROM io_datasets WHERE ref=? ORDER BY version", (f"evb:{b['id']}",))
        self.assertEqual([x["version"] for x in v], [1, 2])


class Retrieval(G5):
    """1: the known-item retrieval benchmark over the Knowledge Hub's own retrieval, versioned, with a reason per miss."""
    def setUp(self):
        super().setUp()
        import test_knowledge_rag as tk
        from app import knowledge_hub as kh, knowledge_media as km
        self.km, self.old = km, km.DATA_DIR
        km.DATA_DIR = __import__("pathlib").Path(self.dir.name)
        q = self.db.q
        q("CREATE TABLE custom_agents (id INTEGER PRIMARY KEY, owner_id INTEGER, name TEXT, role TEXT, description TEXT, instructions TEXT, skills TEXT, status TEXT, updated REAL)")
        q("CREATE TABLE agent_memory (id INTEGER PRIMARY KEY, agent_id INTEGER, user_id INTEGER, text TEXT, source TEXT, created REAL)")
        self.hub = tk.HubStub()
        self.hub.knowledge = self.K = kh.Hub(self.db, self.hub, lambda m: None)
        from app.knowledge_spaces import CaptureIn
        topics = [("Validator weights", "Validators publish weights every tempo and the chain averages them with stake to set incentive for each miner uid."),
                  ("GPU drivers", "Keep the CUDA toolkit and the NVIDIA kernel module on matching versions or the miner silently falls back to the cpu."),
                  ("Registration", "Registering a hotkey burns a dynamic amount of TAO that rises when many miners register within the same interval."),
                  ("Checkpoint uploads", "Upload the checkpoint to the bucket before the deadline, then commit its hash on chain so validators can fetch it."),
                  ("Reward curve", "Emissions follow a reward curve where the top ranked miner takes the largest share and the tail earns almost nothing."),
                  ("Latency budget", "Answer each validator query within twelve seconds, since slower responses score zero for that round entirely.")]
        for t, body in topics:
            self.K.capture(ME, CaptureIn(kind="note", title=t, text=(body + " ") * 2))
        self.o = orc.init(self.db, hub=self.hub)

    def tearDown(self):
        self.km.DATA_DIR = self.old
        super().tearDown()

    def test_passes_is_versioned_and_explains_misses(self):
        r = self.o.run_retrieval(ME)
        self.assertTrue(r["passed"], r)
        self.assertEqual((r["metrics"]["cases"], r["metrics"]["recall@5"], r["version"]), (6, 1.0, 1))
        self.assertEqual(self.o.run_retrieval(ME)["version"], 1)  # the same items: the same frozen version
        from app.knowledge_spaces import CaptureIn
        self.K.capture(ME, CaptureIn(kind="note", title="Hotkeys", text="Rotate the hotkey when it leaks, and move the stake to a fresh coldkey the same day. " * 2))
        self.assertEqual(self.o.run_retrieval(ME)["version"], 2)
        self.K.retrieve = lambda *a, **k: []  # retrieval that finds nothing
        r = self.o.run_retrieval(ME)
        self.assertFalse(r["passed"])
        self.assertTrue(all(m["why"].startswith("Ranked out") for m in r["misses"]))
        self.db.q("DELETE FROM kb_chunks")
        r = self.o.run_retrieval(ME)
        self.assertTrue(all(m["why"].startswith("Not indexed") for m in r["misses"]))


class KnowledgeMeasure(G5):
    """M1: the Knowledge Hub part counts items without a passage of their current version (not items against chunk rows), and
    splits searches that found nothing into nothing readable (access or ingestion) and ranked nothing in (ranking)."""
    def test_unindexed_items_and_empty_searches(self):
        q, now = self.db.q, time.time()
        q("CREATE TABLE kb_items (id INTEGER PRIMARY KEY, user_id INTEGER, status TEXT, version INTEGER, updated REAL)")
        q("CREATE TABLE kb_chunks (id INTEGER PRIMARY KEY, item_id INTEGER, user_id INTEGER, ver INTEGER, n INTEGER)")
        q("CREATE TABLE kb_queries (id INTEGER PRIMARY KEY, user_id INTEGER, ts REAL, results INTEGER, candidates INTEGER, cited TEXT)")
        q("INSERT INTO kb_items VALUES (1, 7, 'kept', 1, ?), (2, 7, 'kept', 3, ?), (3, 7, 'kept', 1, ?)", (now - DAY, now - DAY, now))
        for n in range(20): q("INSERT INTO kb_chunks (item_id, user_id, ver, n) VALUES (1, 7, 1, ?)", (n,))  # one long document
        q("INSERT INTO kb_chunks (item_id, user_id, ver, n) VALUES (2, 7, 2, 0)")  # an edited item still has its old version's
        for i in range(4): q("INSERT INTO kb_queries (user_id, ts, results, candidates) VALUES (7, ?, ?, ?)", (now, 0 if i < 2 else 3, 0 if i == 0 else 9))
        d = intel_layers.Layers(self.db, Ov()).view(ME, fresh=True)
        L = next(x for x in d["layers"] if x["key"] == "knowledge")
        hubp = next(p for p in L["parts"] if p["name"] == "Knowledge Hub")
        f = {x["label"]: x["value"] for x in hubp["figures"]}
        self.assertEqual((f["Items kept"], f["Passages indexed"], f["Items not indexed yet"]), (3, 20, 2))  # the old check said 3 > 21: nothing wrong
        ret = {x["label"]: x["value"] for x in next(p for p in L["parts"] if p["name"] == "Retrieval")["figures"]}
        self.assertEqual((ret["Searches this week"], ret["Ranked nothing in"], ret["Nothing readable"]), (4, 1, 1))


class MissionThroughSixLayers(G5):
    """9: a Mission Control mission (direct engine, scripted model) through all six layers, read back from their records."""
    class LLM:
        def __init__(self): self.prompts = {}
        def completer(self, model, effort="medium"):  # the Intelligence Analyst files its brief at once (test_mission_intel's script)
            from test_mission_intel import LLM
            return LLM([]).completer(model, effort)
        def structured(self, model, system, prompt, schema, name, on_usage=None, effort=None, messages=None):
            self.prompts[name] = prompt
            if on_usage: on_usage(1000)
            if name == "plan": return {"brief": "Compare three subnets and pick one.", "tasks": [{"title": "Compare", "owner": "AXoR", "done_when": "three compared"}], "risks": []}
            if name == "deliverable": return {"deliverable": "Options: SN64, SN19, SN56. Recommendation: SN64.", "summary": "Pick SN64.", "limits": []}
            if name == "verification":
                return {"results": [{"criterion": c, "status": "met", "evidence": "In the text."} for c in ("Names three options", "Recommends one")], "limitations": []}
            if name == "delivery": return {"summary": "Pick SN64.", "recommendations": [], "lessons": [{"kind": "worked", "text": "The direct engine fits a small comparison."}]}
            raise AssertionError(name)

    class Hub:
        def __init__(self, llm): self.llm, self.knowledge = llm, None
        def log_usage(self, *a, **k): pass
        def run_tool(self, name, args): return {"ok": True}

    def test_mission_through_six_layers(self):
        from test_mission_intel import U
        self.o = orc.init(self.db)
        now = time.time()
        # what the loop learned before: a classified failure and a model with a scored record
        self.db.q("INSERT INTO io_diag (run_id, owner_id, system, cls, recoverable, recovery, ts) VALUES (900, 7, 'missions', 'transient', 1, 'Retry: a timeout.', ?)", (now,))
        for i in range(3): self.run_row(system="missions", kind="plan", ref=f"mx:{100 + i}", model="fake:model", score=90)
        self.llm = self.LLM()
        on, ext = mission_intel.ENABLED, mission_intel.mcp_hub
        mission_intel.ENABLED, mission_intel.mcp_hub = True, None
        try:
            mx = missions.Missions(self.db, hub=self.Hub(self.llm), wf=None, ia=None, mw=None)
            mx._model = lambda uid, avoid=None, stage=None: ("fake:model", 1.0)
            mid = self.db.q("""INSERT INTO mx_missions (user_id, title, goal, budget, constraints, status, stage, engine, understanding, created, updated)
                               VALUES (7, 'Pick a subnet', 'Which subnet should I mine with one RTX 4090?', 5.0, '', 'running', 'discover', 'direct', ?, ?, ?) RETURNING id""",
                            (json.dumps(U), now, now), one=True)["id"]
            mx._advance(mid)
        finally:
            mission_intel.ENABLED, mission_intel.mcp_hub = on, ext
        m = mx._m(mid)
        self.assertEqual((m["status"], m["outcome"]), ("delivered", "verified"))
        corr = f"mx:{mid}"
        # Mission: planned with what the loop learned
        self.assertTrue(m["discovery"]["adaptive"])
        self.assertIn("learned by AXoR", self.llm.prompts["plan"])
        self.assertIn("Retry: a timeout.", self.llm.prompts["plan"])
        # Workforce: the work handed to an engine with the mission's whole budget as a hard limit at the gateway
        ev = {e["kind"]: e for e in self.db.q("SELECT * FROM io_events WHERE corr=?", (corr,))}
        self.assertEqual(json.loads(ev["mission.launched"]["payload"])["limit_tokens"], 5_000_000)
        self.assertIn("mission.guided", ev)
        # Execution: every engine call in the ledger, correlated
        runs = self.db.q("SELECT * FROM ac_runs WHERE corr=?", (corr,))
        self.assertEqual({r["kind"] for r in runs}, {"discover", "plan", "execute", "verify", "deliver"})
        self.assertTrue(all(r["status"] == "done" and r["tokens"] for r in runs))
        # Knowledge, Evaluation, Adaptive: the orchestrator's round
        self.o.tick()
        fin = self.db.q("SELECT * FROM io_events WHERE kind='mission.finished' AND corr=?", (corr,), one=True)
        self.assertEqual(fin["status"], "done")
        self.assertGreaterEqual(json.loads(fin["result"])["lessons"], 1)
        self.assertFalse(self.db.q("SELECT 1 FROM ac_limits WHERE key=?", (corr,), one=True))  # its limit is done with
        st = {r["kind"]: (r["state"], r["score"]) for r in self.db.q("SELECT a.kind, e.state, e.score FROM ac_runs a JOIN io_evals e ON e.run_id=a.id WHERE a.corr=?", (corr,))}
        self.assertEqual(st, {"discover": ("scored", 100), "plan": ("scored", 100), "execute": ("scored", 100), "verify": ("excluded", None), "deliver": ("excluded", None)})
        t = self.o.trace(7, corr)
        self.assertEqual(len(t["runs"]), 5)
        self.assertLessEqual({"mission.launched", "mission.guided", "mission.finished"}, {e["kind"] for e in t["events"]})
        self.assertEqual({(e["correlation_id"], e["mission_id"]) for e in t["events"]}, {(corr, mid)})  # the event contract's names
        # the Intelligence layers page's trace of it follows the correlation id
        L = intel_layers.Layers(self.db, Ov()).trace(ME, mid)["trace"]
        self.assertEqual({x["key"]: x["state"] for x in L["layers"]}, {k: "done" for k in ("mission", "workforce", "execution", "knowledge", "evaluation", "adaptive")})
        self.assertEqual(len(L["g5"]["runs"]), 5)
        A = {x["key"]: x["state"] for x in L["acceptance"]}  # the review's eight-step lifecycle acceptance test, from the records
        self.assertEqual([x["key"] for x in L["acceptance"]], ["understand", "plan", "assemble", "execute", "evaluate", "learn", "evolve", "improve"])
        self.assertEqual({k: A[k] for k in ("understand", "plan", "assemble", "execute", "learn")}, {k: "pass" for k in ("understand", "plan", "assemble", "execute", "learn")})
        self.assertEqual(A["evaluate"], "fail")  # one model in the pool: the checker wasn't independent of the worker
        self.assertEqual((A["evolve"], A["improve"]), ("na", "pending"))  # nothing failed; no later mission took its lessons yet
        self.assertTrue(all(x["evidence"] for x in L["acceptance"] if x["state"] == "pass"))  # every passed step names its records
        acc = intel_layers.Layers(self.db, Ov()).acceptance(7)
        self.assertEqual((acc["lifecycle"], acc["loop"]), (None, None))

    def _mission(self, mx, goal, now):
        from test_mission_intel import U
        mid = self.db.q("""INSERT INTO mx_missions (user_id, title, goal, budget, constraints, status, stage, engine, understanding, created, updated)
                           VALUES (7, ?, ?, 5.0, '', 'running', 'discover', 'direct', ?, ?, ?) RETURNING id""", (goal[:40], goal, json.dumps(U), now, now), one=True)["id"]
        mx._advance(mid)
        return mx._m(mid)

    def test_one_mission_through_all_eight_steps_and_into_the_next(self):
        """The review's acceptance test: a controlled mission is understood, planned, assembled, executed, independently verified
        against criteria frozen before the work, leaves lessons, and the next mission on the goal plans with them (step 8)."""
        self.o = orc.init(self.db)
        now = time.time()
        self.llm = self.LLM()
        on, ext = mission_intel.ENABLED, mission_intel.mcp_hub
        mission_intel.ENABLED, mission_intel.mcp_hub = True, None
        try:
            mx = missions.Missions(self.db, hub=self.Hub(self.llm), wf=None, ia=None, mw=None)
            mx._model = lambda uid, avoid=None, stage=None: ("fake:checker" if avoid else "fake:model", 1.0)  # two models: the checker is independent
            m1 = self._mission(mx, "Which subnet should I mine with one RTX 4090? A small comparison of the options.", now)
            self.assertEqual((m1["status"], m1["outcome"]), ("delivered", "verified"))
            self.assertEqual(m1["verification"]["dataset"]["version"], 1)  # checked against the criteria frozen before the work ran
            L = intel_layers.Layers(self.db, Ov())
            A = {x["key"]: x for x in L.loop_check(7, self.db.q("SELECT * FROM mx_missions WHERE id=?", (m1["id"],), one=True))}
            self.assertEqual({k: x["state"] for k, x in A.items()},
                             {"understand": "pass", "plan": "pass", "assemble": "pass", "execute": "pass", "evaluate": "pass", "learn": "pass", "evolve": "na", "improve": "pending"})
            self.assertIn("frozen as dataset v1", A["evaluate"]["detail"])
            # a run that failed for the environment (a rate limit) is no weakness of the work: nothing to evolve, the loop can still pass
            self.run_row(system="missions", kind="execute", status="failed", ref=f"mx:{m1['id']}", corr=f"mx:{m1['id']}", error="Anthropic: 429 rate limit reached")
            A = {x["key"]: x for x in L.loop_check(7, self.db.q("SELECT * FROM mx_missions WHERE id=?", (m1["id"],), one=True))}
            self.assertEqual(A["evolve"]["state"], "pending")  # not classified yet
            self.o.diagnose()
            A = {x["key"]: x for x in L.loop_check(7, self.db.q("SELECT * FROM mx_missions WHERE id=?", (m1["id"],), one=True))}
            self.assertEqual(A["evolve"]["state"], "na"); self.assertIn("failed for the environment (Rate limited)", A["evolve"]["detail"])
            self.assertEqual(self.o.outcomes(7, now - 7 * DAY)["runs"]["environment"], 1)
            self.assertEqual(L.acceptance(7)["follow_up"]["id"], m1["id"])  # the next test to run: its follow-up
            m2 = self._mission(mx, "Which subnet should I mine with one RTX 4090 now? Redo the small comparison of the options.", now + 5)
        finally:
            mission_intel.ENABLED, mission_intel.mcp_hub = on, ext
        self.assertIn(m1["id"], [x["id"] for x in m2["discovery"]["missions"]] + [None])
        lesson = self.db.q("SELECT id FROM mx_lessons WHERE mission_id=?", (m1["id"],), one=True)["id"]
        self.assertIn(lesson, [x["id"] for x in m2["discovery"]["lessons"]])
        A = {x["key"]: x for x in L.loop_check(7, self.db.q("SELECT * FROM mx_missions WHERE id=?", (m1["id"],), one=True))}
        self.assertEqual(A["improve"]["state"], "pass")
        self.assertIn(f"Mission #{m2['id']} planned with 1 of its lesson", A["improve"]["detail"])
        acc = L.acceptance(7)
        self.assertEqual(acc["loop"]["id"], m1["id"])  # all eight: 1-6 pass, nothing to evolve, the next mission took its lessons

    def test_a_mission_that_fails_for_good_keeps_its_lesson(self):
        mx = missions.Missions(self.db, hub=self.Hub(self.LLM()), wf=None, ia=None, mw=None)
        now = time.time()
        mid = self.db.q("""INSERT INTO mx_missions (user_id, title, goal, budget, status, stage, engine, created, updated)
                           VALUES (7, 'T', 'G', 5.0, 'running', 'execute', 'direct', ?, ?) RETURNING id""", (now, now), one=True)["id"]
        mx._dead(mx._m(mid), "The model kept refusing")
        les = self.db.q("SELECT kind, text FROM mx_lessons WHERE mission_id=?", (mid,))
        self.assertEqual(les[0]["kind"], "failed"); self.assertIn("kept refusing", les[0]["text"])


if __name__ == "__main__":
    unittest.main()
