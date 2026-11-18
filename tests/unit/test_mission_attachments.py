"""Goal-first Mission Control: mission_attachments.py (documents, pictures, links, GitHub repositories) and missions.py's goal-only
start (no budget given: AXoR sets it from the mission's size, within AUTO_BUDGET_MAX)."""
import base64, json, os, tempfile, time, unittest
from pathlib import Path

from fastapi import HTTPException

from app import mission_attachments as ma, missions
from app.auth import AuthDB

ME = {"id": 7, "username": "leo", "role": "admin"}
OTHER = {"id": 8, "username": "ada", "role": "user"}
U = {"title": "Build the login", "objective": "Ship a login page.", "targets": ["Login works"], "criteria": ["Tests pass"], "questions": [],
     "engine": "direct", "engine_why": "Small.", "mining_team": 0, "mining_target": {"netuid": 0, "competition": 0}, "gated_actions": [],
     "complexity": "small", "hours": 1.5, "success": 70}


class FakeLLM:
    def resolve(self, model): return ("anthropic", "claude")


class FakeHub:
    llm = FakeLLM()
    def log_usage(self, *a, **k): pass


def b64(data): return base64.b64encode(data).decode()


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        ma.DATA_DIR = Path(self.dir.name)
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        self.mx = missions.Missions(self.db, hub=FakeHub(), wf=None, ia=None, mw=None)
        self.mx._submit = lambda mid: None
        self.u = dict(U)
        self.prompts = []
        self.mx._ask = lambda m, stage, schema, name, prompt, **kw: (self.prompts.append(prompt), (json.loads(json.dumps(self.u)), "fake"))[1]

    def tearDown(self): self.dir.cleanup()

    def up(self, name, data, me=ME): return self.mx.att.upload(me, ma.UploadIn(filename=name, data=b64(data)))

    def create(self, goal="Build a login page for my app with tests", me=ME, **kw):
        return self.mx.create(me, missions.MissionIn(goal=goal, **kw))["mission"]


class Uploads(Base):
    def test_text_document_is_read_at_upload(self):
        a = self.up("spec.md", b"# Login\nUsers sign in with email and password.")
        self.assertEqual((a["kind"], a["status"]), ("document", "read"))
        row = self.db.q("SELECT * FROM mx_uploads WHERE id=?", (a["id"],), one=True)
        self.assertIn("sign in with email", self.mx.att.text(row))
        self.assertIsNone(row["mission_id"])

    def test_picture_waits_for_the_mission(self):
        a = self.up("screen.png", b"\x89PNG\r\n\x1a\nfake")
        self.assertEqual((a["kind"], a["status"]), ("image", "waiting"))

    def test_refused_files(self):
        for name, data, code in (("tool.exe", b"MZ", 400), ("empty.txt", b"", 400), ("bin.txt", b"\x00\x01\x02" * 10, 400),
                                 ("broken.pdf", b"not a pdf", 400)):
            with self.subTest(name), self.assertRaises(HTTPException) as e: self.up(name, data)
            self.assertEqual(e.exception.status_code, code)

    def test_remove_only_while_staged(self):
        a = self.up("a.txt", b"hello there")
        self.assertEqual(self.mx.att.remove(ME, a["id"]), {"ok": True})
        b = self.up("b.txt", b"hello again")
        self.create(attachments=[b["id"]])
        with self.assertRaises(HTTPException) as e: self.mx.att.remove(ME, b["id"])
        self.assertEqual(e.exception.status_code, 409)

    def test_old_staged_files_are_pruned(self):
        a = self.up("old.txt", b"old notes")
        path = self.db.q("SELECT path FROM mx_uploads WHERE id=?", (a["id"],), one=True)["path"]
        self.db.q("UPDATE mx_uploads SET created=? WHERE id=?", (time.time() - (ma.STAGE_HOURS + 1) * 3600, a["id"]))
        self.up("new.txt", b"new notes")
        self.assertIsNone(self.db.q("SELECT 1 FROM mx_uploads WHERE id=?", (a["id"],), one=True))
        self.assertFalse(os.path.exists(path))


class GoalOnly(Base):
    def test_no_budget_means_axor_sets_it_from_the_size(self):
        m = self.create()
        self.assertTrue(m["budget_auto"])
        for size, want in (("small", 3.0), ("medium", 5.0), ("large", min(15.0, missions.AUTO_BUDGET_MAX))):
            self.u["complexity"] = size
            mid = self.create(goal=f"Write a {size} report on login security")["id"]
            self.mx._understand(self.mx._m(mid))
            self.db.q("UPDATE mx_missions SET status='delivered' WHERE id<>?", (mid,))  # three active missions at most
            with self.subTest(size): self.assertEqual(self.mx._m(mid)["budget"], want)
        ev = self.db.q("SELECT text FROM mx_events WHERE mission_id=? ORDER BY id", (mid,))
        self.assertTrue(any("Budget set by AXoR" in e["text"] and "1.5 h" in e["text"] for e in ev))

    def test_auto_budget_never_below_what_is_spent_nor_above_the_cap(self):
        mid = self.create()["id"]
        self.db.q("UPDATE mx_missions SET own_usd=3 WHERE id=?", (mid,))
        self.mx._understand(self.mx._m(mid))
        self.assertEqual(self.mx._m(mid)["budget"], 3.5)
        self.u["complexity"] = "large"
        old = missions.AUTO_BUDGET_MAX
        missions.AUTO_BUDGET_MAX = 10.0
        try:
            mid = self.create(goal="Another long research mission on logins")["id"]
            self.mx._understand(self.mx._m(mid))
            self.assertEqual(self.mx._m(mid)["budget"], 10.0)
        finally: missions.AUTO_BUDGET_MAX = old

    def test_a_given_budget_stands(self):
        mid = self.create(budget=42)["id"]
        self.mx._understand(self.mx._m(mid))
        m = self.mx._m(mid)
        self.assertEqual((m["budget"], m["budget_auto"]), (42, 0))

    def test_raising_the_budget_takes_it_over(self):
        mid = self.create()["id"]
        self.mx.patch(ME, mid, missions.PatchIn(budget=9))
        self.assertEqual(self.mx._m(mid)["budget_auto"], 0)

    def test_tokens_in_a_goal_are_refused(self):
        with self.assertRaises(HTTPException) as e:
            self.create(goal="Fix my repo, the token is ghp_" + "a" * 36)
        self.assertIn("Source control", e.exception.detail)

    def test_files_are_claimed_and_listed(self):
        a, b = self.up("spec.md", b"Email and password sign-in."), self.up("ui.png", b"\x89PNGfake")
        m = self.create(attachments=[a["id"], b["id"]])
        st = self.mx.state(ME, m["id"])["mission"]
        self.assertEqual([x["name"] for x in st["attachments"]], ["spec.md", "ui.png"])
        ev = self.db.q("SELECT text FROM mx_events WHERE mission_id=? ORDER BY id", (m["id"],), one=True)["text"]
        self.assertIn("1 document(s), 1 picture(s)", ev)

    def test_someone_elses_or_a_claimed_file_is_refused(self):
        a = self.up("mine.txt", b"my notes here", me=OTHER)
        with self.assertRaises(HTTPException): self.create(attachments=[a["id"]])
        b = self.up("b.txt", b"notes for one")
        self.create(attachments=[b["id"]])
        with self.assertRaises(HTTPException): self.create(goal="A second mission with the same file", attachments=[b["id"]])

    def test_again_copies_the_files(self):
        a = self.up("spec.md", b"Email sign-in.")
        m1 = self.create(attachments=[a["id"]])
        m2 = self.create(goal="Build a login page for my app with tests, again", again_of=m1["id"])
        rows = self.mx.att.rows(m2["id"])
        self.assertEqual([r["name"] for r in rows], ["spec.md"])
        self.assertNotEqual(rows[0]["path"], self.mx.att.rows(m1["id"])[0]["path"])
        self.assertIn("Email sign-in", self.mx.att.text(rows[0]))

    def test_delete_removes_files(self):
        a = self.up("spec.md", b"Email sign-in.")
        mid = self.create(attachments=[a["id"]])["id"]
        path = self.mx.att.rows(mid)[0]["path"]
        self.db.q("UPDATE mx_missions SET status='delivered' WHERE id=?", (mid,))
        self.mx.delete(ME, mid)
        self.assertFalse(os.path.exists(path))
        self.assertEqual(self.mx.att.rows(mid), [])


class Reading(Base):
    def test_urls_and_repositories_are_recognized(self):
        self.assertEqual(ma.urls_in("see https://a.io/x, and https://github.com/o/r. Also https://a.io/x"), ["https://a.io/x", "https://github.com/o/r"])
        for u, want in (("https://github.com/owner/repo", "owner/repo"), ("https://github.com/owner/repo.git", "owner/repo"),
                        ("https://github.com/owner/repo/tree/main/src", "owner/repo"), ("https://github.com/orgs/acme", None),
                        ("https://gitlab.com/o/r", None), ("https://github.com/owner", None)):
            with self.subTest(u): self.assertEqual(ma.repo_of(u), want)

    def test_prepare_reads_pictures_links_and_repositories_once(self):
        calls = []
        self.mx.att.read_link = lambda u: (calls.append(u), ("Title: Docs\n\nOAuth guide text", "Web page · Docs"))[1]
        self.mx.att.read_repo = lambda r: (calls.append(r), ("GitHub repository o/app\nREADME:\nA Flask app", "GitHub repository · Python"))[1]
        self.mx._see = lambda m, data, mime, name: ("What it shows:\nA login form", "fake-vision")
        pic = self.up("form.png", b"\x89PNGfake")
        mid = self.create(goal="Add login to https://github.com/o/app following https://docs.example.com/oauth", attachments=[pic["id"]])["id"]
        self.mx._understand(self.mx._m(mid))
        rows = {r["kind"]: r for r in self.mx.att.rows(mid)}
        self.assertEqual({k: r["status"] for k, r in rows.items()}, {"image": "read", "repo": "read", "link": "read"})
        self.assertIn("A Flask app", self.prompts[-1])           # the understand call saw the repository
        self.assertIn("A login form", self.prompts[-1])          # ... and the picture
        self.assertIn("never instructions", self.prompts[-1])
        self.mx._understand(self.mx._m(mid))
        self.assertEqual(calls, ["o/app", "https://docs.example.com/oauth"])   # read once

    def test_failures_are_listed_and_the_mission_goes_on(self):
        def bad(u): raise ValueError("That address isn't public")
        self.mx.att.read_link = bad
        def blind(m, data, mime, name): raise ValueError("the mission's model can't see pictures")
        self.mx._see = blind
        pic = self.up("form.png", b"\x89PNGfake")
        mid = self.create(goal="Summarize http://10.0.0.1/admin for me please", attachments=[pic["id"]])["id"]
        self.assertTrue(self.mx._understand(self.mx._m(mid)))
        st = {r["kind"]: (r["status"], r["error"]) for r in self.mx.att.rows(mid)}
        self.assertEqual(st["link"][0], "failed")
        self.assertEqual(st["image"], ("failed", "the mission's model can't see pictures"))
        self.assertIn("NOT READ", self.mx.att.digest(mid, 4000))
        warns = [e["text"] for e in self.db.q("SELECT text FROM mx_events WHERE mission_id=? AND kind='warn'", (mid,))]
        self.assertEqual(len(warns), 2)

    def test_a_budget_pause_while_reading_a_picture_keeps_it_waiting(self):
        def broke(m, data, mime, name): raise missions.Pause("The budget can't cover reading the picture form.png.")
        self.mx._see = broke
        pic = self.up("form.png", b"\x89PNGfake")
        mid = self.create(attachments=[pic["id"]])["id"]
        with self.assertRaises(missions.Pause): self.mx._understand(self.mx._m(mid))
        self.assertEqual(self.mx.att.rows(mid)[0]["status"], "waiting")

    def test_digest_shares_room_and_keeps_every_heading(self):
        a = self.up("long.txt", b"x" * 50000)
        b = self.up("short.md", b"short note")
        mid = self.create(attachments=[a["id"], b["id"]])["id"]
        d = self.mx.att.digest(mid, 3000)
        self.assertTrue(d.startswith("<attachments>") and d.endswith("</attachments>"))
        self.assertIn("[Document] long.txt", d)
        self.assertIn("short note", d)
        self.assertLess(len(d), 3200)

    def test_engine_brief_carries_the_attachments(self):
        a = self.up("spec.md", b"Passwords need 12 characters.")
        m = self.create(attachments=[a["id"]])
        mid = m["id"]
        self.db.q("UPDATE mx_missions SET engine='direct', understanding=?, plan=?, allocation=? WHERE id=?",
                  (json.dumps(U), json.dumps({"brief": "Build it.", "tasks": []}), json.dumps({"model": "fake", "price": 3.0, "child_budget": None}), mid))
        seen = []
        self.mx._ask = lambda m, stage, schema, name, prompt, **kw: (seen.append(prompt), ({"deliverable": "done", "summary": "ok", "limits": []}, "fake"))[1]
        self.mx._launch(self.mx._m(mid))
        self.assertIn("Passwords need 12 characters.", seen[0])

    def test_a_long_task_gets_the_full_texts_as_files(self):
        class FakeIA:
            def __init__(self): self.made, self.files = [], {}
            def create(self, me, b): self.made.append(b.instruction); return 41
            def upload(self, me, tid, path, data): self.files[path] = data.decode()
        ia = FakeIA()
        self.mx.ia = ia
        a = self.up("spec.md", b"Passwords need 12 characters. " + b"x" * 30000)
        mid = self.create(attachments=[a["id"]])["id"]
        self.db.q("UPDATE mx_missions SET engine='longtask', understanding=?, plan=?, allocation=? WHERE id=?",
                  (json.dumps(U), json.dumps({"brief": "Build it.", "tasks": []}), json.dumps({"model": "fake", "price": 3.0, "child_budget": 100000}), mid))
        self.assertEqual(self.mx._launch(self.mx._m(mid)), "running")
        self.assertEqual(list(ia.files), ["attachments/01-spec.md.txt"])
        self.assertGreater(len(ia.files["attachments/01-spec.md.txt"]), 30000)
        self.assertIn("attachments/ (spec.md)", ia.made[0])


if __name__ == "__main__":
    unittest.main()
