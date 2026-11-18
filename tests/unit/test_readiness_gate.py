"""G5-2 M3: the readiness gate (D-011, Owner D4 and clarifications C, D, F, H) and the canonical risk register io_risks (D-012).

Declared needs are probed and block their task unless they pass, the Owner accepted a non-critical one (CONDITIONAL) or a
person verified one no probe can see. Inferred needs only ask for confirmation. A failing plan sign-in blocks every task of
the team. Every blocking or accepted item is one risk in io_risks, deduplicated by its key; a passing probe resolves it."""
import json, os, sys, tempfile, threading, time, types, unittest
from unittest import mock

from fastapi import HTTPException

from app import mining_work, mission_ops as mo, orchestrator as o
from app.auth import AuthDB

sys.path.insert(0, os.path.dirname(__file__))
from test_mission_ref import ME, WID, Base as BoardBase  # noqa: E402


def probe_says(states):
    """A stand-in for mission_ops.probe: {cap: state}; anything else PASS."""
    def fake(ch, comp, cap, value=None, fresh=False):
        st = states.get(cap, "PASS")
        return {"cap": cap, "value": value, "state": st, "evidence": f"{cap} is {st}", "how": "test", "checked": time.time()}
    return fake


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        self.o = o.init(self.db) or o._orc
        self.ch = types.SimpleNamespace(db=self.db, w=None, _has=lambda t: bool(self.db.q("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,), one=True)))
        mo._written.clear()

    def tearDown(self):
        o._orc = None
        self.dir.cleanup()

    def risks(self): return self.o.risks(ME["id"])

    def ready(self, needs, states, comp=None, title="Bench the candidate"):
        t = {"id": 1, "title": title, "detail": "", "needs": json.dumps(needs) if needs is not None else None}
        with mock.patch.object(mo, "probe", probe_says(states)):
            return mo.task_readiness(self.ch, ME["id"], comp, t, "comp:23", "mw_task:1")


class Register(Base):
    def test_one_record_per_finding_updated_by_repeated_probes(self):
        k = "readiness:comp:23:mw_task:1:docker:"
        a = self.o.risk_upsert(ME["id"], k, {"state": "FAIL"}, title="docker not ready", mission="comp:23", severity="high")
        b = self.o.risk_upsert(ME["id"], k, {"state": "FAIL", "again": 1}, title="docker not ready", mission="comp:23", severity="high")
        self.assertEqual(a, b)
        r = self.risks()[0]
        self.assertEqual((r["seen"], r["status"], r["evidence"]["again"]), (2, "open", 1))

    def test_resolve_reopen_accept_and_verify(self):
        k = "readiness:comp:23:mw_task:1:internet:"
        rid = self.o.risk_upsert(ME["id"], k, {"state": "FAIL"}, title="internet not ready", critical=0, source_ref="probe:internet")
        self.assertTrue(self.o.risk_resolve(ME["id"], k, {"by": "", "probe": {"state": "PASS"}}))
        self.assertEqual(self.o.risk(ME["id"], rid)["status"], "resolved")
        self.o.risk_upsert(ME["id"], k, {"state": "FAIL"}, title="internet not ready")
        self.assertEqual(self.o.risk(ME["id"], rid)["status"], "open")                     # found again: reopened
        with self.assertRaises(HTTPException): self.o.risk_verify(ME, rid, "I checked")    # a FAIL is fixed, not vouched for
        self.assertEqual(self.o.risk_accept(ME, rid)["status"], "accepted")
        crit = self.o.risk_upsert(ME["id"], "readiness:comp:23:team:23:auth:", {"state": "FAIL"}, title="auth", critical=1)
        with self.assertRaises(HTTPException) as e: self.o.risk_accept(ME, crit)
        self.assertEqual(e.exception.status_code, 409)
        unk = self.o.risk_upsert(ME["id"], "readiness:comp:23:mw_task:1:credential:BEX_KEY", {"state": "UNKNOWN"}, title="key", critical=1, source_ref="probe:credential")
        with self.assertRaises(HTTPException): self.o.risk_verify(ME, unk, "")
        v = self.o.risk_verify(ME, unk, "Ran live_score.py with it: 200")
        self.assertEqual((v["status"], v["verification"]["by"]), ("resolved", ME["username"]))


class Gate(Base):
    def test_declared_failing_need_blocks_and_records_a_risk(self):
        r = self.ready(["docker"], {"docker": "FAIL"})
        self.assertEqual(r["state"], "BLOCKED")
        risk = self.risks()[0]
        self.assertEqual((risk["mission"], risk["task_ref"], risk["source"], risk["layer"], risk["status"]), ("comp:23", "mw_task:1", "readiness", "execution", "open"))
        for f in ("title", "description", "root_cause", "probability", "impact", "severity", "priority", "detection", "countermeasure", "responsible", "approval"):
            self.assertTrue(risk[f], f)                                                    # every D-012 field filled
        self.assertEqual(risk["impact"]["tasks"], ["mw_task:1"])

    def test_unknown_is_never_pass(self):
        self.assertEqual(self.ready(["internet"], {"internet": "UNKNOWN"})["state"], "BLOCKED")

    def test_critical_failure_blocks_whatever_the_rest_says(self):
        needs = ["postgres", "clickhouse", "internet", "ram:4", "credential:BEX_KEY"]
        r = self.ready(needs, {"credential": "UNKNOWN"})
        self.assertEqual(r["state"], "BLOCKED")
        self.assertEqual(sum(i["state"] == "ready" for i in r["items"]), 4)

    def test_conditional_only_by_the_owners_acceptance(self):
        self.ready(["docker"], {"docker": "FAIL"})
        self.o.risk_accept(ME, self.risks()[0]["id"])
        r = self.ready(["docker"], {"docker": "FAIL"})
        self.assertEqual(r["state"], "CONDITIONAL")

    def test_a_verified_unknown_need_is_ready(self):
        self.ready(["credential:BEX_KEY"], {"credential": "UNKNOWN"})
        self.o.risk_verify(ME, self.risks()[0]["id"], "Key works: live /score answered")
        self.assertEqual(self.ready(["credential:BEX_KEY"], {"credential": "UNKNOWN"})["state"], "READY")

    def test_inferred_needs_ask_for_confirmation_and_never_block(self):
        r = self.ready(None, {"docker": "FAIL"}, title="Start the challenge container")
        self.assertEqual((r["state"], [c["cap"] for c in r["confirm"]]), ("READY", ["docker"]))
        self.assertEqual(self.risks(), [])

    def test_a_failing_plan_sign_in_blocks_every_task_of_the_team(self):
        r = self.ready([], {"auth": "FAIL"}, comp={"id": 23, "name": "SN61"})
        self.assertEqual(r["state"], "BLOCKED")
        self.assertTrue(self.risks()[0]["critical"])

    def test_a_passing_probe_resolves_the_risk(self):
        self.ready(["docker"], {"docker": "FAIL"})
        self.ready(["docker"], {"docker": "PASS"})
        self.assertEqual(self.risks()[0]["status"], "resolved")


class BoardGate(BoardBase):
    """The board's start loop holds a queued task whose declared needs fail and puts it back once they pass."""
    def setUp(self):
        super().setUp()
        self.db.q("ALTER TABLE mw_tasks ADD COLUMN needs TEXT")
        for col in ("hold TEXT", "note TEXT", "feedback TEXT", "queued REAL", "run_id INTEGER", "runs INTEGER DEFAULT 0", "reviewer INTEGER"):
            try: self.db.q(f"ALTER TABLE mw_tasks ADD COLUMN {col}")
            except Exception: pass  # noqa: BLE001
        for col in ("parallel INTEGER", "paused INTEGER DEFAULT 0", "internet INTEGER DEFAULT 0"):
            self.db.q(f"ALTER TABLE mw_comps ADD COLUMN {col}")
        self.w.loop, self.w.pool = None, types.SimpleNamespace(submit=lambda *a: None)
        self.w._kick = mining_work.Work._kick.__get__(self.w)
        self.events = []
        self.w._event = lambda wid, kind, text, **k: self.events.append(text)
        self.w.sbx = None
        mo._written.clear()

    def test_held_then_released(self):
        tid = self.task("Run the live bench", status="queued")
        self.db.q("UPDATE mw_tasks SET needs=?, agent_id=2 WHERE id=?", (json.dumps(["docker"]), tid))
        with mock.patch.object(mo, "probe", probe_says({"docker": "FAIL"})):
            self.w._kick(WID)
        t = self.db.q("SELECT status, hold, note FROM mw_tasks WHERE id=?", (tid,), one=True)
        self.assertEqual((t["status"], t["hold"]), ("todo", "readiness"))
        self.assertIn("docker FAIL", t["note"])
        self.assertTrue(any("held before it started" in e for e in self.events))
        with mock.patch.object(mo, "probe", probe_says({})):
            self.w._kick(WID)
        self.assertEqual(self.db.q("SELECT status, hold FROM mw_tasks WHERE id=?", (tid,), one=True)["hold"], None)


if __name__ == "__main__":
    unittest.main()
