"""General Manager chat (gm_chat.py, D-039): an assignment becomes a real mission through Missions.create (files attached, the page as
a resource, the change-for-review constraint); anything else gets an answer and no mission; the gate, limits and errors are
Mission Control's own."""
import base64, json, os, tempfile, unittest
from pathlib import Path

from fastapi import HTTPException

from app import gm_chat, mission_attachments as ma, missions
from app.auth import AuthDB
from app.llm import LLMError

ME = {"id": 7, "username": "leo", "role": "admin"}
OTHER = {"id": 8, "username": "ada", "role": "user"}
U = {"title": "Fix the homepage", "objective": "Fix it.", "targets": ["Works"], "criteria": ["Tests pass"], "questions": [],
     "engine": "direct", "engine_why": "Small.", "mining_team": 0, "mining_target": {"netuid": 0, "competition": 0}, "gated_actions": [],
     "complexity": "small", "hours": 1.5, "success": 70}
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


class FakeLLM:
    def __init__(self): self.answer, self.calls, self.fail = {"kind": "assignment", "text": "The team will do it."}, [], None
    def resolve(self, model):
        if self.fail == "resolve": raise LLMError("no model is set up")
        return ("anthropic", "claude")
    def structured(self, model, system, prompt, schema, name, on_usage=None, effort="low"):
        self.calls.append({"model": model, "system": system, "prompt": prompt, "schema": schema})
        if on_usage: on_usage(321)
        if self.fail == "call": raise LLMError("overloaded")
        return self.answer


class FakeHub:
    def __init__(self): self.llm, self.usage = FakeLLM(), []
    def log_usage(self, me, source, tokens, agent_id=None, model=None): self.usage.append((me["id"], source, tokens, model))


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        ma.DATA_DIR = Path(self.dir.name)
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        self.hub = FakeHub()
        self.mx = missions.Missions(self.db, hub=self.hub, wf=None, ia=None, mw=None)
        self.mx._submit = lambda mid: None
        self.mx._ask = lambda m, stage, schema, name, prompt, **kw: (json.loads(json.dumps(U)), "fake")
        self.gm = gm_chat.GM(self.db, self.mx)

    def tearDown(self): self.dir.cleanup()

    def send(self, text="", me=ME, **kw): return self.gm.send(me, gm_chat.SendIn(text=text, **kw))

    def up(self, name="shot.png", data=PNG, me=ME): return self.mx.att.upload(me, ma.UploadIn(filename=name, data=base64.b64encode(data).decode()))["id"]

    def mission_rows(self, uid=ME["id"]): return self.db.q("SELECT * FROM mx_missions WHERE user_id=?", (uid,))


class Assignments(Base):
    def test_assignment_creates_a_mission_with_the_persons_words_page_and_constraint(self):
        out = self.send("Fix the broken signup button on the homepage", page="Overview", path="/#explore")
        rows = self.mission_rows()
        self.assertEqual(len(rows), 1)
        m = rows[0]
        self.assertEqual(m["goal"], "Fix the broken signup button on the homepage")
        self.assertEqual(m["constraints"], gm_chat.CONSTRAINTS)
        self.assertIn("Overview", m["resources"]); self.assertIn("/#explore", m["resources"])
        user, gm = out["messages"][-2:]
        self.assertEqual((user["role"], user["mission_id"]), ("user", m["id"]))
        self.assertEqual((gm["role"], gm["kind"], gm["mission_id"]), ("gm", "mission", m["id"]))
        self.assertIn(f"#{m['id']}", gm["text"])
        self.assertEqual(out["missions"][str(m["id"])]["status"], "queued")

    def test_pictures_go_with_the_mission(self):
        aid = self.up()
        out = self.send("Make the header look like this picture", attachments=[aid])
        mid = out["messages"][-1]["mission_id"]
        self.assertEqual(self.db.q("SELECT mission_id FROM mx_uploads WHERE id=?", (aid,), one=True)["mission_id"], mid)
        self.assertEqual(out["messages"][-2]["files"], [{"id": aid, "name": "shot.png", "kind": "image"}])
        self.assertIn("shot.png", self.hub.llm.calls[-1]["prompt"])  # the General Manager sees the file names, as data

    def test_short_assignment_asks_for_more_and_keeps_the_files(self):
        aid = self.up()
        out = self.send("fix this", attachments=[aid])
        self.assertEqual(self.mission_rows(), [])
        self.assertEqual(out["messages"][-1]["kind"], "more")
        self.assertTrue(out["kept_files"])
        self.assertIsNone(self.db.q("SELECT mission_id FROM mx_uploads WHERE id=?", (aid,), one=True)["mission_id"])

    def test_mission_errors_are_said_in_the_chat_and_create_nothing(self):
        for _ in range(missions.ACTIVE_PER_USER): self.send("Write a research report about subnet incentives")
        out = self.send("Develop one more program for the team please")
        self.assertEqual(len(self.mission_rows()), missions.ACTIVE_PER_USER)
        self.assertEqual(out["messages"][-1]["kind"], "error")
        self.assertIn("already running", out["messages"][-1]["text"])

    def test_broken_decision_still_starts_the_work(self):
        self.hub.llm.answer = {"nonsense": True}
        self.send("Update the pricing table on the homepage")
        self.assertEqual(len(self.mission_rows()), 1)


class Replies(Base):
    def test_reply_creates_no_mission_and_is_metered(self):
        self.hub.llm.answer = {"kind": "reply", "text": "Hi! Mission #3 is in progress."}
        out = self.send("hello, how are things?")
        self.assertEqual(self.mission_rows(), [])
        self.assertEqual(out["messages"][-1]["text"], "Hi! Mission #3 is in progress.")
        self.assertEqual(self.hub.usage, [(7, "gm", 321, "anthropic:claude")])

    def test_status_context_is_only_the_persons_own_missions(self):
        self.send("Write a research report about subnet incentives")
        self.gm.send(OTHER, gm_chat.SendIn(text="Build a secret program for ada only"))
        self.hub.llm.answer = {"kind": "reply", "text": "ok"}
        self.send("how is it going?")
        prompt = self.hub.llm.calls[-1]["prompt"]
        self.assertIn("research report", prompt)
        self.assertNotIn("secret program", prompt)

    def test_start_as_a_mission_turns_the_message_into_one(self):
        self.hub.llm.answer = {"kind": "reply", "text": "Happy to help."}
        out = self.send("Could the dashboard show weekly earnings too?")
        uid = out["messages"][-2]["id"]
        self.assertEqual(self.mission_rows(), [])
        n = len(self.hub.llm.calls)
        users = len(self.db.q("SELECT id FROM gm_messages WHERE role='user'"))
        self.gm.as_mission(ME, uid, gm_chat.SendIn())
        rows = self.mission_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(self.hub.llm.calls), n)  # no second decision
        self.assertEqual(len(self.db.q("SELECT id FROM gm_messages WHERE role='user'")), users)  # no second copy of the message
        self.assertEqual(self.db.q("SELECT mission_id FROM gm_messages WHERE id=?", (uid,), one=True)["mission_id"], rows[0]["id"])
        with self.assertRaises(HTTPException) as e: self.gm.as_mission(ME, uid, gm_chat.SendIn())
        self.assertEqual(e.exception.status_code, 409)
        with self.assertRaises(HTTPException) as e: self.gm.as_mission(OTHER, uid, gm_chat.SendIn())
        self.assertEqual(e.exception.status_code, 404)


class Guards(Base):
    def test_empty_token_and_foreign_files_are_refused(self):
        with self.assertRaises(HTTPException): self.send("")
        with self.assertRaises(HTTPException): self.send("use ghp_" + "a" * 36 + " to push the fix")
        aid = self.up(me=OTHER)
        with self.assertRaises(HTTPException) as e: self.send("Make the header look like this picture", attachments=[aid])
        self.assertEqual(e.exception.status_code, 400)
        self.assertEqual(self.mission_rows(), [])

    def test_no_model_or_failed_call_is_answered_and_nothing_starts(self):
        for fail in ("resolve", "call"):
            self.hub.llm.fail = fail
            out = self.send("Fix the broken signup button on the homepage")
            self.assertEqual([m["role"] for m in out["messages"]], ["user", "gm"])  # never a message left without an answer
            self.assertEqual(out["messages"][-1]["kind"], "error")
            self.assertEqual(self.mission_rows(), [])

    def test_threads_are_private_and_clearable(self):
        self.send("Write a research report about subnet incentives")
        self.assertEqual(self.gm.thread(OTHER)["messages"], [])
        self.assertEqual(len(self.gm.thread(ME)["messages"]), 2)
        self.gm.clear(ME)
        self.assertEqual(self.gm.thread(ME)["messages"], [])
        self.assertEqual(len(self.mission_rows()), 1)  # clearing the chat never touches missions

    def test_mission_cards_only_for_own_missions(self):
        mid = self.send("Write a research report about subnet incentives")["messages"][-1]["mission_id"]
        self.assertEqual(self.gm.missions(ME, [mid])[str(mid)]["status"], "queued")
        self.assertTrue(self.gm.missions(OTHER, [mid])[str(mid)]["gone"])

    def test_one_message_at_a_time(self):
        self.gm._lock(ME["id"]).acquire()
        with self.assertRaises(HTTPException) as e: self.send("Write a research report about subnet incentives")
        self.assertEqual(e.exception.status_code, 409)

    def test_router_uses_mission_controls_gate(self):
        class R: state = {"missions": None}
        r = gm_chat.build(self.db, lambda req: ME, R, None)
        self.assertIsNone(r.state["gm"])


if __name__ == "__main__": unittest.main()
