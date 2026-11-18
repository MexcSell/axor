"""G5-2 acceptance A13 (scripted end to end, on fakes) and A8 (seeded SN61-style board).

A13: a v2 plan → preflight BLOCKED (docker, an unverified credential, a signed-out plan login) → remediation (sign in, a person
verifies the key, a Docker runner appears) → READY → the board starts the work → a run fails → orchestrator.decide routes it
(a timeout retries shortly; a sign-in failure stops, not counted) → the readiness risks are resolved with their evidence.
A8: on an SN61-style board, no task with a declared docker need reaches an agent while Docker isn't provided, and every one of
them is shown with its blocker and remedy."""
import json, os, sys, threading, time, types, unittest
from unittest import mock

from app import mining_autoloop, mining_work, mission_ops as mo, orchestrator as o

sys.path.insert(0, os.path.dirname(__file__))
from test_mission_ref import ME, WID, Base as BoardBase  # noqa: E402

NOT_SIGNED_IN = "Claude Code on the server isn't signed in. Run `claude setup-token` on any machine where you use Claude Code"


class World(BoardBase):
    def setUp(self):
        super().setUp()
        for col in ("needs TEXT", "hold TEXT", "note TEXT", "feedback TEXT", "queued REAL", "run_id INTEGER", "runs INTEGER DEFAULT 0",
                    "reviewer INTEGER", "retries INTEGER DEFAULT 0", "retry_at REAL", "fail_class TEXT", "question TEXT"):
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
        self.o = o.init(self.db)
        mo._written.clear(); mo._probe_cache.clear()
        self.started = []
        self.w.loop = None
        def submit(fn, *a):  # the plan runs inline; a task's run is recorded as started, not run
            if getattr(fn, "__name__", "") == "_work": self.started.append(a[0])
            else: fn(*a)
        self.w.pool = types.SimpleNamespace(submit=submit)
        self.w._kick = mining_work.Work._kick.__get__(self.w)
        self.w._event = lambda *a, **k: None
        self.w.sbx = None
        self.env = {"docker": "FAIL", "credential": "UNKNOWN", "auth": "FAIL"}

    def tearDown(self):
        o._orc = None
        super().tearDown()

    def probe(self, ch, comp, cap, value=None, fresh=False):
        st = self.env.get(cap, "PASS")
        return {"cap": cap, "value": value, "state": st, "evidence": f"{cap} {st} (scripted)", "how": "test", "checked": time.time()}

    def kick(self):
        mo._written.clear()
        with mock.patch.object(mo, "probe", self.probe): self.w._kick(WID)

    def status(self, title): return self.db.q("SELECT status, hold FROM mw_tasks WHERE title=?", (title,), one=True)


class EndToEnd(World):
    def test_a13_plan_preflight_remediate_dispatch_fail_decide_close(self):
        # 1 a version-2 plan: needs declared per task
        self.w.plan_out = {"summary": "Bench the miner", "tasks": [
            {"title": "Run the live bench", "detail": "", "assignee": "Devon", "priority": "high", "needs": ["docker", "credential:BEX_KEY"]},
            {"title": "Write the scoring notes", "detail": "", "assignee": "Gus", "priority": "low", "needs": []}]}
        self.w.plan(ME, WID, mining_work.PlanIn(note="", start=False))
        self.db.q("UPDATE mw_tasks SET status='queued'")
        # 2 preflight: the plan login is signed out, Docker isn't provided, the key is unverified → everything held
        self.kick()
        self.assertEqual(self.started, [])
        self.assertEqual({self.status(t)["hold"] for t in ("Run the live bench", "Write the scoring notes")}, {"readiness"})
        open_ = {r["title"].split(" not ready")[0]: r for r in self.o.risks(ME["id"], status="open")}
        self.assertEqual(set(open_), {"docker", "credential:BEX_KEY", "auth"})
        self.assertTrue(open_["auth"]["critical"] and open_["credential:BEX_KEY"]["critical"] and not open_["docker"]["critical"])
        # 3 remediation: sign in (auth PASS), a person verifies the key, a Docker runner appears (docker PASS)
        self.env.update(auth="PASS", docker="PASS")
        self.o.risk_verify(ME, open_["credential:BEX_KEY"]["id"], "live_score.py answered 200 with it")
        self.kick()   # releases both (needs pass now) and, in the same pass, starts them
        self.assertEqual(sorted(self.started), sorted(r["id"] for r in self.db.q("SELECT id FROM mw_tasks")))
        self.assertEqual(self.status("Run the live bench")["status"], "working")
        # 4 a run fails: orchestrator.decide routes it through Autoloop
        loop = object.__new__(mining_autoloop.Loop)
        loop.w, loop.db, loop.lk, loop.leases = self.w, self.db, threading.Lock(), {}
        bench = self.db.q("SELECT id, run_id FROM mw_tasks WHERE title='Run the live bench'", one=True)
        notes = self.db.q("SELECT id, run_id FROM mw_tasks WHERE title='Write the scoring notes'", one=True)
        self.assertTrue(loop.failed(bench["id"], bench["run_id"], "Claude Code timed out after 150 s", "failed"))
        self.assertEqual(self.status("Run the live bench")["hold"], "retry")                     # transient: a short retry
        self.assertTrue(loop.failed(notes["id"], notes["run_id"], NOT_SIGNED_IN, "failed"))
        self.assertEqual(self.status("Write the scoring notes")["status"], "blocked")             # sign-in: stops, not counted
        # 5 the readiness risks are closed with their evidence
        res = {r["title"].split(" not ready")[0]: r for r in self.o.risks(ME["id"], status="resolved")}
        self.assertEqual(set(res), {"docker", "credential:BEX_KEY", "auth"})
        self.assertEqual(res["docker"]["verification"]["probe"]["state"], "PASS")
        self.assertEqual(res["credential:BEX_KEY"]["verification"]["by"], ME["username"])


class SeededSN61(World):
    """A8 on a synthetic SN61-style board: the real board's wording, a person confirmed Docker on the tasks that need it."""
    TASKS = [("Build and push the image on your machine when PR1-2 pass", ["docker", "registry"]),
             ("Run --image mode with docker", ["docker"]), ("Measure the BEX challenge container's peak RAM", ["docker"]),
             ("Live-container bench mode", ["docker"]), ("Real docker build of the gate (positive and negative)", ["docker"]),
             ("Confirm MINER_DOCKER_PORT (10002 vs 10001)", []), ("Add --check build line to BEX Dockerfile", []),
             ("Document how SN61 validators score a submission", []), ("Start the challenge container and score one commit", None)]

    def test_a8_no_docker_task_reaches_an_agent_and_each_shows_its_fix(self):
        self.env = {"docker": "FAIL", "registry": "FAIL"}  # as on this cluster: no Docker for agents
        for title, needs in self.TASKS:
            self.db.q("INSERT INTO mw_tasks (comp_id, title, detail, status, priority, agent_id, origin, created, updated, needs) VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (WID, title, "", "queued", "high", 2, "plan:1", time.time(), time.time(), json.dumps(needs) if needs is not None else None))
        for _ in range(len(self.TASKS)):  # one agent: one start per pass
            self.kick()
            self.db.q("UPDATE mw_tasks SET status='done' WHERE status='working'"); self.db.q("UPDATE mw_runs SET status='done' WHERE status='running'")
        docker = [t for t, n in self.TASKS if n and "docker" in n]
        started = {r["title"] for r in self.db.q(f"SELECT title FROM mw_tasks WHERE id IN ({','.join('?' * len(self.started))})", self.started)} if self.started else set()
        self.assertFalse(started & set(docker))                                                   # 0 Docker-dependent tasks dispatched
        self.assertEqual(started, {t for t, n in self.TASKS if not (n and "docker" in n)})        # the rest (incl. the inferred-only one) ran
        held = self.db.q("SELECT title, note FROM mw_tasks WHERE hold='readiness'")
        self.assertEqual({h["title"] for h in held}, set(docker))
        for h in held: self.assertIn("docker FAIL", h["note"]); self.assertIn("→", h["note"])     # 100 % with blocker and remedy


if __name__ == "__main__":
    unittest.main()
