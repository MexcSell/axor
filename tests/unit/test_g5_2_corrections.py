"""G5-2 corrections from the Owner's review of 2026-11-11 (§2 A–C).

A. Concurrent retry idempotency: an atomic, database-backed claim. Of any number of dispatcher passes racing for the same retry,
   exactly one claims and starts it; a claim left by a pass that died before starting the run expires and is taken again.
B. Dashboard side effects: reading the Overview never probes (no sign-in prompt, no live check) and shows cached answers with
   their time; only dispatch preflight and the explicit Re-check probe for real.
C. Credential verification is bound to the credential's fingerprint and expires; approvals of external actions are bound to
   the exact mission, task, action and payload, are used up when the task starts, and can't be had through a verification."""
import json, os, sys, tempfile, threading, time, types, unittest
from unittest import mock

from fastapi import HTTPException

from app import control_dispatch as cd, llm, mining_work, mission_ops as mo, orchestrator as o
from app.auth import AuthDB

sys.path.insert(0, os.path.dirname(__file__))
from test_mission_ref import ME, WID, Base as BoardBase  # noqa: E402
from test_task_lifecycle import Lifecycle  # noqa: E402


# ---------------------------------------------------------------- A: concurrent retries
class ConcurrentRetry(Lifecycle):
    def failed_task(self):
        t = self.agent_task("Write the launch plan")
        self.assertEqual(cd.dispatch(self.ch, ME)["agent"], 1)                          # its first run
        self.db.q("UPDATE ctl_tasks SET status='failed', summary='Model call timed out after 600 s', updated=?, attempts=0, retry_claim=NULL WHERE id=?",
                  (time.time() - 3600, t))
        return t

    def test_the_claim_is_atomic_in_the_database(self):
        t = self.failed_task()
        r = self.row(t)                                                                    # every racer read the same snapshot
        wins, go = [], threading.Barrier(8)
        def racer():
            go.wait()
            wins.append(cd._claim(self.ch, r, f"ctl:t{t}:retry:1", time.time()))
        th = [threading.Thread(target=racer) for _ in range(8)]
        for x in th: x.start()
        for x in th: x.join(10)
        self.assertEqual(sum(wins), 1)

    def test_two_simultaneous_dispatcher_passes_start_the_retry_once(self):
        t = self.failed_task()
        starts, real_start, real_decide = [], cd._start, cd._decide
        both = threading.Barrier(2, timeout=3)
        def decide(r, now=None):  # both passes decide before either claims: the race the claim must settle
            d = real_decide(r, now)
            if r["id"] == t:
                try: both.wait()
                except threading.BrokenBarrierError: pass
            return d
        def start(ch, me, r, *a, **k):
            if r["id"] == t: starts.append(threading.get_ident())
            return real_start(ch, me, r, *a, **k)
        later = time.time() + 3600
        with mock.patch.object(cd, "_decide", decide), mock.patch.object(cd, "_start", start):
            th = [threading.Thread(target=cd.dispatch, args=(self.ch, ME, later)) for _ in range(2)]
            for x in th: x.start()
            for x in th: x.join(20)
        self.assertEqual(len(starts), 1)
        self.assertEqual(self.row(t)["attempts"], 1)

    def test_a_worker_that_dies_after_claiming_is_recovered_after_the_claim_expires(self):
        t = self.failed_task()
        later = time.time() + 3600
        class Killed(BaseException): pass  # the process dies: no error handler of the pass runs (an ordinary exception is a counted miss)
        def dies(*a, **k): raise Killed("worker killed between the claim and the start")
        with mock.patch.object(cd, "_start", dies):
            with self.assertRaises(Killed): cd.dispatch(self.ch, ME, later)
        r = self.row(t)
        self.assertEqual((r["status"], r["attempts"]), ("failed", 0))
        self.assertTrue(r["retry_claim"])                                                  # the claim is left behind
        self.assertEqual(cd.dispatch(self.ch, ME, later + 1)["retried"], 0)                # still claimed: nobody else starts it
        out = cd.dispatch(self.ch, ME, later + cd.CLAIM_STALE + 1)                         # the claim expired: recovered
        self.assertEqual(out["retried"], 1)
        self.assertEqual(self.row(t)["attempts"], 1)


# ---------------------------------------------------------------- B: no side effects from reading the dashboard
class ReadOnlyDashboard(BoardBase):
    def setUp(self):
        super().setUp()
        mo._probe_cache.clear(); mo._written.clear()
        mo.ensure_schema(self.db)  # as start-up does (mission_ops.mount)
        for col in ("needs TEXT", "hold TEXT"):
            self.db.q(f"ALTER TABLE mw_tasks ADD COLUMN {col}")
        self.db.q("ALTER TABLE mw_comps ADD COLUMN internet INTEGER DEFAULT 1")
        self.o = o.init(self.db)
        egress = types.SimpleNamespace(calls=0)
        def status(fresh=False): egress.calls += 1; return {"ready": True, "gvisor": True}
        egress.status = status
        self.egress = egress
        self.w.sbx = types.SimpleNamespace(egress=egress, kube=None, ready=lambda: (True, ""))
        # 2026-11-13: internet passes on a run inside the team's sandbox that reached a host, not on the proxy answering alone
        # (tests/unit/test_mission_exec_access.py): this team has such a run
        self.db.q("""CREATE TABLE IF NOT EXISTS mw_sbx (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, by_user TEXT, command TEXT, status TEXT,
                     exit_code INTEGER, output TEXT, finished REAL, net TEXT, src TEXT)""")
        self.db.q("INSERT INTO mw_sbx (comp_id, by_user, command, status, exit_code, finished, net) VALUES (?, 'Devon', 'pip install x', 'done', 0, ?, ?)",
                  (WID, __import__("time").time() - 60, json.dumps({"hosts": {"pypi.org": {"conns": 1}}})))
        self.w._model = lambda c, a, *k: "terminal:sonnet"                                 # a Claude Code plan team: auth probes prompt
        self.w._agents = lambda wid: [{"id": 2, "active": 1}]
        self.ch = types.SimpleNamespace(db=self.db, w=self.w, _has=lambda t: bool(self.db.q("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,), one=True)),
                                        _comps=lambda uid: {WID: {}})
        tid = self.task("Bench the candidate", status="queued")
        self.db.q("UPDATE mw_tasks SET needs=? WHERE id=?", (json.dumps(["internet"]), tid))

    def tearDown(self):
        o._orc = None
        super().tearDown()

    def test_reading_the_overview_never_probes_and_shows_when_it_was_checked(self):
        with mock.patch.object(llm, "cli_check") as prompt:
            g = mo.gate_view(self.ch, ME, [{"comp_id": WID, "title": "SN61"}])
        prompt.assert_not_called()
        self.assertEqual(self.egress.calls, 0)
        item = g["missions"][0]["blocked"][0]["items"][0]
        self.assertEqual((item["probe"], item["checked"], item["stale"]), ("UNKNOWN", None, True))  # not checked yet: never PASS
        self.assertEqual(self.o.risks(ME["id"]), [])                                       # nothing written by a read

    def test_recheck_probes_for_real_then_the_page_shows_the_cached_answer(self):
        with mock.patch.object(llm, "cli_check") as prompt:
            out = mo.refresh_readiness(self.ch, ME, f"comp:{WID}")
            self.assertEqual(out["tasks"], 1)
            prompt.assert_called()                                                         # the sign-in check is part of an explicit re-check
            self.assertGreater(self.egress.calls, 0)
            calls = self.egress.calls
            g = mo.gate_view(self.ch, ME, [{"comp_id": WID, "title": "SN61"}])
            self.assertEqual(self.egress.calls, calls)                                     # the page still reads the cache only
        self.assertEqual(g["missions"][0]["state"], "PASS")
        with self.assertRaises(HTTPException) as e: mo.refresh_readiness(self.ch, ME, f"comp:{WID}")
        self.assertEqual(e.exception.status_code, 429)                                     # at most once a minute

    def test_an_expired_cached_answer_is_shown_as_stale_not_refreshed(self):
        with mock.patch.object(llm, "cli_check"): mo.refresh_readiness(self.ch, ME, f"comp:{WID}")
        for v in mo._probe_cache.values(): v["checked"] -= mo.PROBE_TTL + 1
        calls = self.egress.calls
        with mock.patch.object(llm, "cli_check") as prompt:
            p = mo.probe(self.ch, {"id": WID}, "internet", cached_only=True)
        prompt.assert_not_called(); self.assertEqual(self.egress.calls, calls)
        self.assertTrue(p["stale"])


class RecheckLimitAcrossReplicas(ReadOnlyDashboard):
    """Owner review §2A: the Re-check limit lives in the database, so two replicas (two connections to one database) and a
    restarted process all see it; of simultaneous requests exactly one runs, and the sign-in prompt is sent once."""
    def replica(self):
        db = AuthDB(self.db.path) if hasattr(self.db, "path") else AuthDB(os.path.join(self.dir.name, "a.db"))  # its own connection
        return types.SimpleNamespace(db=db, w=self.w, _has=self.ch._has, _comps=lambda uid: {WID: {}})

    def test_two_replicas_at_once_one_accepted_one_prompt(self):
        a, b, go, res = self.replica(), self.replica(), threading.Barrier(2), []
        def ask(ch):
            go.wait()
            try: mo.refresh_readiness(ch, ME, f"comp:{WID}"); res.append("ok")
            except HTTPException as e: res.append(e.status_code)
        with mock.patch.object(llm, "cli_check") as prompt:
            th = [threading.Thread(target=ask, args=(c,)) for c in (a, b)]
            for x in th: x.start()
            for x in th: x.join(20)
        self.assertEqual(sorted(map(str, res)), ["429", "ok"])
        self.assertEqual(prompt.call_count, 1)                                            # no duplicate authentication prompt

    def test_the_limit_survives_a_restart_and_lifts_after_a_minute(self):
        with mock.patch.object(llm, "cli_check"): mo.refresh_readiness(self.ch, ME, f"comp:{WID}")
        restarted = self.replica()                                                         # a new process: nothing in memory
        with self.assertRaises(HTTPException) as e: mo.refresh_readiness(restarted, ME, f"comp:{WID}")
        self.assertEqual(e.exception.status_code, 429)
        self.assertFalse(mo._recheck_slot(restarted.db, ME["id"], f"comp:{WID}", time.time() + 30))
        self.assertTrue(mo._recheck_slot(restarted.db, ME["id"], f"comp:{WID}", time.time() + mo.REFRESH_EVERY + 1))
        self.assertTrue(mo._recheck_slot(restarted.db, ME["id"], "comp:99"))              # keyed by owner and mission
        self.assertTrue(mo._recheck_slot(restarted.db, ME["id"] + 1, f"comp:{WID}"))


# ---------------------------------------------------------------- C: credential verification and approval scope
class Scope(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        self.db.q("CREATE TABLE mw_tasks (id INTEGER PRIMARY KEY, title TEXT, detail TEXT, needs TEXT)")
        self.o = o.init(self.db)
        self.ch = types.SimpleNamespace(db=self.db, w=None, _has=lambda t: bool(self.db.q("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,), one=True)))
        mo._written.clear(); mo._probe_cache.clear()

    def tearDown(self):
        o._orc = None
        os.environ.pop("G5_TEST_KEY", None)
        self.dir.cleanup()

    def task(self, tid, needs, detail="Push the frozen image and submit its digest"):
        self.db.q("INSERT OR REPLACE INTO mw_tasks (id, title, detail, needs) VALUES (?,?,?,?)", (tid, f"Task {tid}", detail, json.dumps(needs)))
        return self.db.q("SELECT * FROM mw_tasks WHERE id=?", (tid,), one=True)

    def ready(self, t, tid=1):
        return mo.task_readiness(self.ch, ME["id"], None, t, "comp:23", f"mw_task:{tid}")

    def risk(self, cap):
        return next(r for r in self.o.risks(ME["id"]) if r["source_ref"] == f"probe:{cap}")

    def test_a_credential_verification_is_void_once_the_credential_changes(self):
        os.environ["G5_TEST_KEY"] = "first-value"
        t = self.task(1, ["credential:G5_TEST_KEY"])
        self.assertEqual(self.ready(t)["state"], "BLOCKED")
        v = self.o.risk_verify(ME, self.risk("credential")["id"], "live_score.py answered 200")
        self.assertEqual(v["verification"]["fingerprint"], mo.credential_fingerprint("G5_TEST_KEY"))
        self.assertEqual(self.ready(t)["state"], "READY")
        os.environ["G5_TEST_KEY"] = "rotated-value"                                       # the key changed: the verification no longer holds
        self.assertEqual(self.ready(t)["state"], "BLOCKED")

    def test_a_credential_verification_expires(self):
        os.environ["G5_TEST_KEY"] = "v"
        t = self.task(1, ["credential:G5_TEST_KEY"]); self.ready(t)
        rid = self.risk("credential")["id"]
        v = self.o.risk_verify(ME, rid, "checked")["verification"]
        self.assertAlmostEqual(v["expires"] - v["at"], mo.VERIFY_DAYS * 86400, delta=5)
        self.db.q("UPDATE io_risks SET verification=? WHERE id=?", (json.dumps({**v, "expires": time.time() - 1}), rid))
        self.assertEqual(self.ready(t)["state"], "BLOCKED")

    def test_a_credential_the_server_cant_see_is_verified_for_a_day_only(self):
        t = self.task(1, ["credential:NOT_ON_THIS_SERVER"]); self.ready(t)
        v = self.o.risk_verify(ME, self.risk("credential")["id"], "held by the Owner, checked by hand")["verification"]
        self.assertEqual(v["fingerprint"], "absent")
        self.assertAlmostEqual(v["expires"] - v["at"], mo.CRED_ABSENT_HOURS * 3600, delta=5)

    def test_an_approval_cant_be_had_by_verification(self):
        t = self.task(1, ["approval"]); self.ready(t)
        with self.assertRaises(HTTPException) as e: self.o.risk_verify(ME, self.risk("approval")["id"], "I approve")
        self.assertEqual(e.exception.status_code, 409)

    def test_an_approval_is_for_this_task_as_it_is_and_only_once(self):
        t = self.task(1, ["approval"]); self.ready(t)
        rid = self.risk("approval")["id"]
        with self.assertRaises(HTTPException) as e: self.o.risk_approve({**ME, "role": "member"}, rid, "push the image")
        self.assertEqual(e.exception.status_code, 403)                                     # administrators only
        with self.assertRaises(HTTPException): self.o.risk_approve(ME, rid, "push the image", payload_sha="0" * 64)  # not what they saw
        a = self.o.risk_approve(ME, rid, "push the image", payload_sha=mo.task_payload(t))["verification"]
        self.assertEqual((a["mission"], a["task_ref"], a["action"], a["single_use"]), ("comp:23", "mw_task:1", "push the image", True))
        r = self.ready(t)
        self.assertEqual(r["state"], "READY"); self.assertEqual(r["items"][0]["consume"], "readiness:comp:23:mw_task:1:approval:")
        other = self.task(2, ["approval"])
        self.assertEqual(self.ready(other, tid=2)["state"], "BLOCKED")                    # another task: not covered
        edited = self.task(1, ["approval"], detail="Push the image to a PUBLIC repo")      # the task changed after approval
        self.assertEqual(self.ready(edited)["state"], "BLOCKED")
        self.task(1, ["approval"])                                                         # back as approved
        self.assertTrue(self.o.approval_consume(ME["id"], "readiness:comp:23:mw_task:1:approval:"))
        self.assertFalse(self.o.approval_consume(ME["id"], "readiness:comp:23:mw_task:1:approval:"))  # used once
        self.assertEqual(self.ready(t)["state"], "BLOCKED")                                # the next run needs a new approval
        self.assertEqual(self.risk("approval")["status"], "open")

    def test_an_approval_expires(self):
        t = self.task(1, ["approval"]); self.ready(t)
        rid = self.risk("approval")["id"]
        a = self.o.risk_approve(ME, rid, "submit the commit")["verification"]
        self.db.q("UPDATE io_risks SET verification=? WHERE id=?", (json.dumps({**a, "expires": time.time() - 1}), rid))
        self.assertEqual(self.ready(t)["state"], "BLOCKED")


class ApprovalUsedByTheStart(BoardBase):
    """The board's start loop uses the approval up when the approved task starts."""
    def setUp(self):
        super().setUp()
        for col in ("needs TEXT", "hold TEXT", "note TEXT", "feedback TEXT", "queued REAL", "run_id INTEGER", "runs INTEGER DEFAULT 0", "reviewer INTEGER"):
            try: self.db.q(f"ALTER TABLE mw_tasks ADD COLUMN {col}")
            except Exception: pass  # noqa: BLE001
        for col in ("parallel INTEGER", "paused INTEGER DEFAULT 0", "internet INTEGER DEFAULT 0"):
            self.db.q(f"ALTER TABLE mw_comps ADD COLUMN {col}")
        self.o = o.init(self.db)
        mo._written.clear(); mo._probe_cache.clear()
        self.w.loop, self.w.sbx = None, None
        self.w.pool = types.SimpleNamespace(submit=lambda *a: None)
        self.w._kick = mining_work.Work._kick.__get__(self.w)
        self.w._event = lambda *a, **k: None

    def tearDown(self):
        o._orc = None
        super().tearDown()

    def test_the_start_consumes_the_approval(self):
        tid = self.task("Push the frozen image", status="queued")
        self.db.q("UPDATE mw_tasks SET needs=?, agent_id=2 WHERE id=?", (json.dumps(["approval"]), tid))
        self.w._kick(WID)
        self.assertEqual(self.db.q("SELECT hold FROM mw_tasks WHERE id=?", (tid,), one=True)["hold"], "readiness")
        rid = next(r for r in self.o.risks(ME["id"]) if r["source_ref"] == "probe:approval")["id"]
        self.o.risk_approve(ME, rid, "push the image")
        self.w._kick(WID)
        self.assertEqual(self.db.q("SELECT status FROM mw_tasks WHERE id=?", (tid,), one=True)["status"], "working")
        self.assertTrue(self.o.risk(ME["id"], rid)["verification"]["consumed"])


if __name__ == "__main__":
    unittest.main()
