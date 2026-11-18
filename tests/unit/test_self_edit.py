"""Self-edit (self_edit.py, D-040): a mission changes AXoR's code on the Workbench; only the Owner or a delegate starts one, never a model on its
own; protected paths and failing checks stop it; the merge request is bound to the commit and merges exactly that commit, Owner-only."""
import hashlib, json, os, tempfile, time, unittest
from pathlib import Path
from unittest import mock

from fastapi import HTTPException

from app import gm_chat, mission_attachments as ma, missions, self_edit
from app.auth import AuthDB

OWNER = {"id": 7, "username": "the-owner", "role": "admin"}
ADMIN = {"id": 8, "username": "admin-two", "role": "admin"}
BASE, SHA = "a" * 40, "b" * 40


class FakeBench:
    """The Workbench's HTTP API as self_edit.py calls it, scripted."""
    def __init__(self):
        self.calls, self.runs, self.files, self.head, self.merged = [], {}, ["backend/app/pages.py", "tests/unit/test_pages.py"], SHA, None
        self.engineer = {"status": "done", "commit": SHA[:8], "cost": 0.42, "result": "Fixed the typo in pages.py and added a test."}
        self.check = {"status": "done", "exit": 0, "events": [{"k": "out", "text": "Ran 3080 tests"}, {"k": "out", "text": "OK"}]}
        self.merge_out = {"ok": True, "head": "c" * 8, "from": SHA}

    def __call__(self, path, body=None, timeout=30):
        self.calls.append((path, body))
        if path == "/info":
            return {"repos": [{"id": "axor", "heads": {"self-edit/main": BASE}, "checks": [{"id": "unit"}]}]}
        if path == "/repos/axor/runs":
            rid = f"r{len(self.runs) + 1:011d}"
            self.runs[rid] = dict(self.check if body["kind"] == "check" else self.engineer)
            return {"id": rid, "status": "queued"}
        if path.startswith("/runs/") and path.endswith("/stop"): return {"status": "stopped"}
        if path.startswith("/runs/"): return self.runs[path.split("/")[2].split("?")[0]]
        if path.startswith("/repos/axor/diff"): return {"head": self.head, "files": [{"path": f} for f in self.files], "patch": "--- a/x\n+++ b/x\n"}
        if path == "/repos/axor/merge": self.merged = body; return self.merge_out
        if path == "/repos/axor/drop": return {"ok": True}
        raise AssertionError(path)


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(); self.addCleanup(self.dir.cleanup)
        ma.DATA_DIR = Path(self.dir.name)
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        for u in (OWNER, ADMIN):
            self.db.q("INSERT INTO users (id, username, email, pw_hash, created, role) VALUES (?,?,?,?,?,?)",
                      (u["id"], u["username"], f"{u['username']}@example.invalid", "x", time.time(), u["role"]))
        for k, v in {"AXOR_OWNERS": "the-owner"}.items():
            p = mock.patch.dict(os.environ, {k: v}); p.start(); self.addCleanup(p.stop)
        p = mock.patch.object(self_edit, "ENABLED", True); p.start(); self.addCleanup(p.stop)
        self.bench = FakeBench()
        self.se = self_edit.SelfEdit(self.db, url="http://bench", token="t" * 30)
        self.se.call = self.bench

    def change(self, me=OWNER, mid=1):
        return self.se.create(me, mid, "Fix the typo", "Fix the typo on the homepage.", 3)

    def run_through(self, cid):
        for _ in range(4): st, err = self.se.status(cid)
        return st, err


class Lifecycle(Base):
    def test_engineer_then_checks_then_ready(self):
        cid = self.change()
        start = self.bench.calls[1][1]
        self.assertEqual((start["kind"], start["base"], start["slug"]), ("engineer", BASE, "mx1-1"))
        self.assertIn("backend/app/auth*.py", start["prompt"])  # the protected paths are told
        self.assertLessEqual(start["budget_usd"], self_edit.MAX_USD)
        self.assertEqual(self.run_through(cid), ("done", ""))
        c = self.se.get(cid)
        self.assertEqual((c["status"], c["sha"], c["files"]), ("ready", SHA, self.bench.files))
        self.assertTrue(any(b and b.get("kind") == "check" and b.get("check") == "unit" for _, b in self.bench.calls))
        d = self.se.deliverable(cid)
        self.assertEqual(d["kind"], "selfedit"); self.assertIn("Fixed the typo", d["text"]); self.assertIn("--- a/x", d["text"])

    def test_protected_paths_are_refused_before_any_check(self):
        self.bench.files = ["backend/app/pages.py", "k8s/base/30-axor.yaml"]
        cid = self.change()
        st, err = self.run_through(cid)
        self.assertEqual(st, "failed"); self.assertIn("k8s/base/30-axor.yaml", err); self.assertTrue(self_edit.final(err))
        self.assertFalse(any(b and b.get("kind") == "check" for _, b in self.bench.calls))
        for p in ("backend/app/auth.py", "backend/app/self_edit.py", "Dockerfile", "backend/app/aicp/grants.py", ".env.local", "workbench/workbench.py"):
            self.assertTrue(self_edit.protected(p), p)
        for p in ("backend/app/pages.py", "frontend/app.js", "tests/unit/test_x.py"):
            self.assertIsNone(self_edit.protected(p), p)

    def test_failed_checks_and_empty_work_fail(self):
        self.bench.check = {"status": "done", "exit": 1, "events": [{"k": "out", "text": "FAILED (failures=2)"}]}
        st, err = self.run_through(self.change())
        self.assertEqual(st, "failed"); self.assertIn("unit tests failed", err); self.assertIn("FAILED (failures=2)", err)
        self.assertEqual(missions.classify(err), "test")  # replanned with the failure as feedback
        self.bench.engineer = {"status": "done", "commit": None, "result": "Nothing to do"}
        st, err = self.run_through(self.change(mid=2))
        self.assertEqual(st, "failed"); self.assertIn("no files", err); self.assertTrue(self_edit.final(err))

    def test_only_the_owner_or_a_delegate_and_only_when_on(self):
        with self.assertRaises(HTTPException) as e: self.change(me=ADMIN)
        self.assertEqual(e.exception.status_code, 403)
        with mock.patch.object(self_edit, "ENABLED", False), self.assertRaises(HTTPException) as e: self.change()
        self.assertEqual(e.exception.status_code, 503)


class Merge(Base):
    def test_merges_exactly_the_approved_commit(self):
        cid = self.change(); self.run_through(cid)
        art = self.se.artifact(cid)
        with self.assertRaises(HTTPException): self.se.merge(ADMIN, cid, art)
        self.bench.head = "d" * 40  # the branch moved after its checks
        with self.assertRaises(HTTPException) as e: self.se.merge(OWNER, cid, art)
        self.assertEqual(e.exception.status_code, 409); self.assertIsNone(self.bench.merged)
        self.bench.head = SHA
        with self.assertRaises(HTTPException): self.se.merge(OWNER, cid, art.replace(BASE, "e" * 40))
        self.se.merge(OWNER, cid, art)
        self.assertEqual(self.bench.merged, {"slug": "mx1-1", "into": "self-edit/main", "expect": SHA})
        self.assertEqual(self.se.get(cid)["status"], "merged")
        with self.assertRaises(HTTPException): self.se.merge(OWNER, cid, art)  # once

    def test_refused_merge_is_reported(self):
        cid = self.change(); self.run_through(cid)
        self.bench.merge_out = {"ok": False, "why": "You have staged changes in the folder", "how": "cd x && git merge"}
        with self.assertRaises(HTTPException) as e: self.se.merge(OWNER, cid, self.se.artifact(cid))
        self.assertIn("staged changes", e.exception.detail)
        self.assertEqual(self.se.get(cid)["status"], "ready")


class InMissions(Base):
    def setUp(self):
        super().setUp()
        class LLM:
            def resolve(s, model): return ("anthropic", "claude")
        class Hub:
            llm = LLM()
            def log_usage(s, *a, **k): pass
        self.mx = missions.Missions(self.db, hub=Hub(), wf=None, ia=None, mw=None)
        self.mx.se = self.se
        self.mx._submit = lambda mid: None

    def test_engine_offered_to_the_owner_only(self):
        self.assertTrue(self.mx._engines(OWNER["id"])["selfedit"])
        self.assertFalse(self.mx._engines(ADMIN["id"])["selfedit"])
        with self.assertRaises(HTTPException) as e: self.mx.create(ADMIN, missions.MissionIn(goal="Fix the homepage typo please", engine="selfedit"))
        self.assertEqual(e.exception.status_code, 400)

    def deliver_ready(self):
        mid = self.mx.create(OWNER, missions.MissionIn(goal="Fix the homepage typo please", engine="selfedit"))["mission"]["id"]
        cid = self.change(mid=mid); self.run_through(cid)
        self.mx._set(mid, engine="selfedit", child=cid, outcome="verified", status="running", stage="deliver")
        m = self.mx._m(mid)
        if m["engine"] == "selfedit" and m["child"] and m["outcome"] != "failed":  # what _deliver does (the report itself needs a whole mission)
            c = self.se.get(cid)
            self.mx._request(m, f"Merge AXoR code change {c['id']}", self.se.artifact(cid), kind=("selfedit", "Merge an AXoR code change"))
        return mid, cid, self.db.q("SELECT * FROM mx_requests WHERE mission_id=? AND kind='selfedit'", (mid,), one=True)

    def test_owner_approval_merges_and_is_used_once(self):
        mid, cid, r = self.deliver_ready()
        self.assertEqual(r["artifact"], hashlib.sha256(self.se.artifact(cid).encode()).hexdigest())
        self.mx.decide(OWNER, r["id"], missions.DecideIn(approve=True, hash=r["hash"]))
        self.assertEqual(self.se.get(cid)["status"], "merged")
        self.assertEqual(self.db.q("SELECT status FROM mx_requests WHERE id=?", (r["id"],), one=True)["status"], "approved")
        with self.assertRaises(HTTPException): self.mx.decide(OWNER, r["id"], missions.DecideIn(approve=True, hash=r["hash"]))

    def test_failed_merge_leaves_the_request_pending(self):
        mid, cid, r = self.deliver_ready()
        self.bench.merge_out = {"ok": False, "why": "conflicts"}
        with self.assertRaises(HTTPException): self.mx.decide(OWNER, r["id"], missions.DecideIn(approve=True, hash=r["hash"]))
        self.assertEqual(self.db.q("SELECT status FROM mx_requests WHERE id=?", (r["id"],), one=True)["status"], "pending")

    def test_reject_merges_nothing(self):
        mid, cid, r = self.deliver_ready()
        self.mx.decide(OWNER, r["id"], missions.DecideIn(approve=False, hash=r["hash"]))
        self.assertIsNone(self.bench.merged); self.assertEqual(self.se.get(cid)["status"], "rejected")

    def test_a_model_never_picks_selfedit_by_itself(self):
        u = {"title": "t", "objective": "o", "targets": ["x"], "criteria": ["c"], "questions": [], "engine": "selfedit", "engine_why": "w",
             "mining_team": 0, "mining_target": {"netuid": 0, "competition": 0}, "gated_actions": [], "complexity": "small", "hours": 1, "success": 70}
        self.mx._ask = lambda m, *a, **k: (dict(u), "fake")
        self.mx._read_attachments = lambda m: None
        mid = self.mx.create(OWNER, missions.MissionIn(goal="Fix the homepage typo please"))["mission"]["id"]
        self.mx._understand(self.mx._m(mid))
        self.assertNotEqual(self.mx._m(mid)["engine"], "selfedit")


class Recovery(InMissions):
    def test_declined_or_protected_stops_test_failure_replans(self):
        mid = self.mx.create(OWNER, missions.MissionIn(goal="Fix the homepage typo please", engine="selfedit"))["mission"]["id"]
        self.mx._set(mid, engine="selfedit", attempts=1, status="running", stage="execute")
        self.assertEqual(self.mx._recover(self.mx._m(mid), "The engineer changed no files."), "dead")
        self.assertEqual(self.mx._recover(self.mx._m(mid), "The change touches protected paths: k8s/x (k8s/*). It is refused (D-040)."), "dead")
        self.assertNotEqual(self.mx._recover(self.mx._m(mid), "The unit tests failed on the change (Exited with 1.). Last lines: FAILED"), "dead")


class GMChat(InMissions):
    def test_axor_change_from_the_owner_runs_as_selfedit_others_stay_proposals(self):
        class LLM:
            def resolve(s, model): return ("anthropic", "claude")
            def structured(s, *a, **k): return {"kind": "assignment", "text": "On it.", "changes_axor": True}
        self.mx.hub.llm = LLM()
        gm = gm_chat.GM(self.db, self.mx)
        gm.send(OWNER, gm_chat.SendIn(text="Fix the typo in the homepage header please"))
        gm.send(ADMIN, gm_chat.SendIn(text="Fix the typo in the homepage header please"))
        rows = {r["user_id"]: r for r in self.db.q("SELECT user_id, forced, constraints FROM mx_missions")}
        self.assertEqual(rows[OWNER["id"]]["forced"], "selfedit"); self.assertEqual(rows[OWNER["id"]]["constraints"], gm_chat.SELF_CONSTRAINTS)
        self.assertIn(rows[ADMIN["id"]]["forced"], (None, "")); self.assertEqual(rows[ADMIN["id"]]["constraints"], gm_chat.CONSTRAINTS)


if __name__ == "__main__": unittest.main()
