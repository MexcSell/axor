"""knowledge_spaces.py (Knowledge Hub: My Knowledge + Company Knowledge): private-by-default capture into folders, folder moves,
publishing to company review, approval bound to the content hash, agent retrieval filtered by scope before ranking, grants,
agent contributions that wait for review, feedback only on retrieved records, communications imports (dedupe, undo),
contradictions flagged instead of overwritten, and the model steps' refs checked against what was retrieved."""
import json, os, tempfile, time, unittest

os.environ.setdefault("KNOWLEDGE_INDEX", "0"); os.environ.setdefault("KNOWLEDGE_SYNC", "0")  # no background loops in tests

from fastapi import HTTPException

from app import knowledge_hub as kh
from app.auth import AuthDB
from app.knowledge_spaces import CaptureIn, CommsIn, CommsNote, DecideIn, FolderIn, FolderMove, GrantIn, LinkIn, OrganizeIn, PublishIn, RecordIn, AskIn

ME = {"id": 7, "username": "leo", "role": "admin"}
HER = {"id": 8, "username": "ana", "role": "member"}


class LLM:
    def __init__(self): self.calls = []
    def any_configured(self): return True
    def structured(self, model, system, prompt, schema, name, on_usage=None, effort=None):
        self.calls.append(name)
        if on_usage: on_usage(11)
        refs = [ln.split("]")[0][1:] for ln in prompt.splitlines() if ln.startswith("[kb:")]
        if name == "process":
            return {"title": "Tidy title", "summary": "What it says.", "ktype": "procedural", "folder": "/07-Knowledge/Procedures", "tags": ["miner", "eval"],
                    "links": [{"ref": r, "rel": "supports", "why": "Same topic."} for r in refs[:1]] + [{"ref": "kb:99999", "rel": "supports", "why": "Not listed."}],
                    "claims": ["It works."], "record": {"title": "Derived record", "body": "Register the miner, then run the validator locally first."}}
        if name == "ask":
            return {"answer": f"Use the validator first [{refs[0] if refs else 'kb:1'}]. Also [kb:99999].", "evidence": [{"ref": r, "why": "Says so."} for r in refs[:2]] + [{"ref": "kb:99999", "why": "x"}],
                    "gaps": ["No numbers."], "directions": ["Measure it."]}
        if name == "review":
            return {"verdict": "approve", "reasons": ["Sourced."], "evidence": "some", "risks": [], "confidence": 85, "ktype": "procedural", "review_days": 30}
        raise AssertionError(name)


class HubStub:
    def __init__(self): self.llm = LLM()
    def log_usage(self, *a, **k): pass
    def model_of(self, m): return "fake"


class SlackStub:
    def __init__(self): self.info, self.cache = {"channel": "general", "team": "Acme"}, {"messages": [{"ts": "1700000001.000100", "name": "Bo", "text": "Ship the eval harness"},
                                                                                                         {"ts": "1700000002.000100", "name": "Cy", "text": "Agreed, after tests"}]}
    def configured(self): return True
    def channel_ref(self): return "C1"


class SpacesTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        q, now = self.db.q, time.time()
        q("CREATE TABLE custom_agents (id INTEGER PRIMARY KEY, owner_id INTEGER, name TEXT, role TEXT, description TEXT, instructions TEXT, skills TEXT, status TEXT, updated REAL)")
        q("CREATE TABLE agent_memory (id INTEGER PRIMARY KEY, agent_id INTEGER, user_id INTEGER, text TEXT, source TEXT, created REAL)")
        q("CREATE TABLE agent_skills (id INTEGER PRIMARY KEY, owner_id INTEGER, name TEXT, description TEXT, body TEXT)")
        q("CREATE TABLE co_company (id INTEGER PRIMARY KEY, user_id INTEGER UNIQUE, name TEXT)")
        q("CREATE TABLE co_divisions (id INTEGER PRIMARY KEY, company_id INTEGER, name TEXT, status TEXT DEFAULT 'active')")
        q("CREATE TABLE co_projects (id INTEGER PRIMARY KEY, company_id INTEGER, division_id INTEGER, name TEXT, objective TEXT, status TEXT DEFAULT 'planning')")
        q("CREATE TABLE co_knowledge (id INTEGER PRIMARY KEY, company_id INTEGER, scope TEXT, owner_id INTEGER, project_id INTEGER, title TEXT, body TEXT, source TEXT, created REAL, updated REAL)")
        q("INSERT INTO custom_agents VALUES (1, 7, 'Scout', 'Researcher', '', 'Research.', '[]', 'live', ?)", (now,))
        q("INSERT INTO custom_agents VALUES (2, 7, 'Miner', 'Engineer', '', 'Mine.', '[]', 'live', ?)", (now,))
        q("INSERT INTO co_company VALUES (1, 7, 'AXoR Co')")
        q("INSERT INTO co_divisions VALUES (3, 1, 'Bittensor', 'active')")
        q("INSERT INTO co_projects VALUES (5, 1, 3, 'SN62', 'Rank up', 'active')")
        q("INSERT INTO co_projects VALUES (6, 1, 3, 'Handshake', 'Other', 'active')")
        self.hub = HubStub()
        self.K = kh.Hub(self.db, self.hub, lambda m: None, slack=SlackStub())

    def tearDown(self):
        self.dir.cleanup()

    def note(self, title, text, me=ME, **kw):
        return self.K.capture(me, CaptureIn(kind="note", title=title, text=text, **kw))

    def search(self, actor, query, **kw):
        return self.K.tool(ME, {"query": query, "scope": kw.get("scope", ""), "knowledge_type": kw.get("kt", "")}, "search_knowledge", actor)["results"]

    def test_capture_is_private_and_foldered(self):
        n = self.note("Validator first", "Run the validator locally before you register a miner.")
        self.assertEqual((n["space"], n["path"], n["reach"], n["visibility"]), ("personal", "/00-Inbox/Quick-Notes", "page", "Private"))
        with self.assertRaises(HTTPException) as e: self.note("Validator first", "Run the validator locally before you register a miner.")
        self.assertEqual(e.exception.status_code, 409)
        f = self.K.capture(ME, CaptureIn(kind="file", filename="miner.py", text="import torch\n\ndef score(x):\n    return x\nAPI_KEY = 'sk-ant-abcdefghijklmnopqrstuvwxyz0123456789'\n"))
        self.assertEqual((f["type"], f["data"]["kind"], f["path"]), ("source", "code", "/04-Sources/Git-Repositories"))
        self.assertIn("score", f["data"]["about"]); self.assertNotIn("sk-ant-abcdefghijkl", f["body"])
        with self.assertRaises(HTTPException) as e: self.K.capture(ME, CaptureIn(kind="file", filename="paper.pdf", text="%PDF-1.4"))
        self.assertEqual(e.exception.status_code, 415)
        b = self.K.capture(ME, CaptureIn(kind="url", url="http://127.0.0.1:9/private"))  # not a public address: kept as a bookmark, never fetched
        self.assertEqual((b["data"]["kind"], b["path"], b["trust"]), ("bookmark", "/00-Inbox/Bookmarks", "external"))
        # agents don't read private items; they do once shared
        self.assertEqual(self.search("hub:1", "validator miner"), [])
        self.K.update(ME, n["id"], kh.ItemPatch(reach="agents"))
        self.assertEqual([r["ref"] for r in self.search("hub:1", "validator miner")], [f"kb:{n['id']}"])
        # someone else's knowledge never shows
        self.assertEqual(self.K.search(HER, "validator")["results"], [])

    def test_folders(self):
        names = {f["path"] for f in self.K.folders(ME)}
        self.assertTrue({"/00-Inbox/Quick-Notes", "/02-Projects/Bittensor/SN62", "/99-Archive"} <= names)
        n = self.note("Plan", "A plan for the subnet work.", path="/02-Projects/Bittensor/SN62")
        self.K.move_folder(ME, FolderMove(path="/02-Projects/Bittensor", to="/02-Projects/Chain"))
        self.assertEqual(self.K.item(ME, n["id"])["path"], "/02-Projects/Chain/SN62")
        with self.assertRaises(HTTPException): self.K.delete_folder(ME, FolderIn(path="/02-Projects/Chain"))
        self.K.add_folder(ME, FolderIn(path="/03-Research/Zk"))
        self.K.delete_folder(ME, FolderIn(path="/03-Research/Zk"))
        with self.assertRaises(HTTPException): self.K.add_folder(ME, FolderIn(path="/bad/<name>"))

    def test_publish_review_and_scoped_retrieval(self):
        n = self.note("Miner ranking lesson", "Miners rank higher when the validator runs locally before submission.")
        r = self.K.publish(ME, PublishIn(ids=[n["id"]], scope="project:5", ktype="episodic"))
        cid = r["published"][0]
        c = self.K.item(ME, cid)
        self.assertEqual((c["space"], c["state"], c["scope"], c["ktype"], c["visibility"]), ("company", "submitted", "project:5", "episodic", "Waiting for review"))
        self.assertEqual(self.K.item(ME, n["id"])["visibility"], "Company candidate")
        with self.assertRaises(HTTPException): self.K.publish(ME, PublishIn(ids=[n["id"]], scope="company"))  # already a candidate
        self.assertEqual(self.search("project:5", "miner ranking"), [])  # not approved yet
        with self.assertRaises(HTTPException) as e: self.K.decide(ME, cid, DecideIn(decision="approve", hash="stale"))
        self.assertEqual(e.exception.status_code, 409)
        self.K.decide(ME, cid, DecideIn(decision="approve", hash=c["hash"], review_days=30))
        self.assertEqual(self.K.item(ME, n["id"])["visibility"], "Approved for the company")
        self.assertEqual([x["ref"] for x in self.search("project:5", "miner ranking")], [f"kb:{cid}"])  # its project reads it
        self.assertEqual(self.search("project:6", "miner ranking"), [])   # another project doesn't
        self.assertEqual(self.search("hub:1", "miner ranking"), [])       # nor an agent without a grant
        self.K.grant(ME, GrantIn(scope="project:5", actor="hub:1"))
        hit = self.search("hub:1", "miner ranking")[0]
        self.assertEqual((hit["ref"], hit["state"], hit["type"]), (f"kb:{cid}", "Verified", "episodic"))
        self.assertEqual(self.search("hub:1", "miner ranking", scope="Handshake"), [])  # narrowed to a scope it can't read: nothing
        # the Company's team runs read it through _knowledge_for
        self.assertEqual(self.K.company_rows(7, {"id": 5, "division_id": 3})[0]["title"], "Miner ranking lesson")
        self.assertEqual(self.K.company_rows(7, {"id": 6, "division_id": 3}), [])
        # reuse events, then feedback only on what was retrieved
        self.assertTrue(self.K.tool(ME, {"ref": f"kb:{cid}", "useful": True, "note": "Helped"}, "knowledge_feedback", "hub:1")["ok"])
        self.assertIn("error", self.K.tool(ME, {"ref": f"kb:{cid}", "useful": True, "note": ""}, "knowledge_feedback", "hub:2"))
        v = self.K.view(ME, "company")
        self.assertEqual(v["counts"]["verified"], 1)
        self.assertGreaterEqual(next(r for r in v["records"] if r["id"] == cid)["uses"]["good"], 1)
        # reviewed knowledge is kept
        with self.assertRaises(HTTPException) as e: self.K.delete(ME, cid)
        self.assertEqual(e.exception.status_code, 409)

    def test_agent_contributions_wait_and_contradictions_flag(self):
        out = self.K.tool(ME, {"title": "Retry the validator", "body": "When the validator times out, retry once with a longer timeout before failing.",
                               "knowledge_type": "procedural", "scope": "", "evidence": "run 41"}, "contribute_knowledge", "hub:2")
        self.assertEqual(out["status"], "submitted")
        rid = int(out["ref"][3:])
        k = self.K.item(ME, rid)
        self.assertEqual((k["state"], k["scope"], k["contributor"]), ("submitted", "hub:2", "agent:hub:2"))
        self.assertEqual(self.search("hub:2", "validator timeout"), [])  # its own contribution isn't knowledge until approved
        again = self.K.tool(ME, {"title": "Retry the validator", "body": "When the validator times out, retry once with a longer timeout before failing.",
                                 "knowledge_type": "procedural", "scope": "", "evidence": ""}, "contribute_knowledge", "hub:2")
        self.assertEqual(again["status"], "known")
        for i in range(9):
            self.K.tool(ME, {"title": f"Note {i}", "body": f"Something learned number {i} about the subnet and its validators.", "knowledge_type": "declarative",
                             "scope": "company", "evidence": ""}, "contribute_knowledge", "hub:2")
        self.assertIn("error", self.K.tool(ME, {"title": "One more", "body": "One more thing learned about the validator today.", "knowledge_type": "declarative",
                                                "scope": "", "evidence": ""}, "contribute_knowledge", "hub:2"))
        # the model's review is advice; the user decides
        self.K.assess(ME, rid, kh.ModelIn())
        self.assertEqual(self.K.item(ME, rid)["data"]["ai_review"]["verdict"], "approve")
        self.K.decide(ME, rid, DecideIn(decision="approve", hash=self.K.item(ME, rid)["hash"]))
        self.assertEqual(len(self.search("hub:2", "validator timeout")), 1)
        # a contradicting record flags it contested (still read, with its state), never overwrites it
        w = self.K.add_record(ME, RecordIn(title="Never retry", body="Retrying a timed-out validator wastes the slot; fail fast instead.", ktype="procedural", scope="company", approve=True))
        self.K.link(ME, LinkIn(item_id=w["id"], ref=f"kb:{rid}", rel="contradicts"))
        self.assertEqual(self.K.item(ME, rid)["state"], "contested")
        self.assertEqual(self.K.item(ME, rid)["body"], "When the validator times out, retry once with a longer timeout before failing.")
        self.assertTrue(any(q["id"] == rid and q["why"] == "contested" for q in self.K.view(ME, "company")["queue"]))

    def test_comms_import_dedupe_undo_and_note(self):
        discord = {"guild": {"name": "Bittensor"}, "channel": {"name": "sn62-dev"}, "messages": [
            {"id": "11", "timestamp": "2026-11-01T10:00:00+00:00", "author": {"name": "dev1"}, "content": "New miner trick: cache the embeddings https://example.com/x", "attachments": []},
            {"id": "12", "timestamp": "2026-11-01T10:05:00+00:00", "author": {"name": "dev2"}, "content": "Does it pass the validator?", "reference": {"messageId": "11"}}]}
        r = self.K.comms_import(ME, CommsIn(text=json.dumps(discord), filename="sn62.json"))
        self.assertEqual((r["platform"], r["added"]), ("discord", 2))
        self.assertEqual(self.K.comms_import(ME, CommsIn(text=json.dumps(discord)))["added"], 0)  # the same messages again: skipped
        tg = {"name": "Mining chat", "type": "private_group", "messages": [{"id": 3, "type": "message", "date": "2026-11-02T08:00:00", "from": "Ann",
                                                                             "text": ["Use ", {"type": "bold", "text": "fp16"}, " for speed"]}]}
        self.assertEqual(self.K.comms_import(ME, CommsIn(text=json.dumps(tg)))["platform"], "telegram")
        c = self.K.comms(ME)
        self.assertEqual(c["total"], 3)
        m = next(x for x in c["messages"] if x["message_id"] == "11")
        self.assertEqual((m["author"], m["channel"], m["urls"]), ("dev1", "sn62-dev", ["https://example.com/x"]))
        self.assertEqual(next(x for x in c["messages"] if x["platform"] == "telegram")["text"], "Use fp16 for speed")
        self.assertTrue(any(f["path"] == "/05-Communications/Discord/sn62-dev" for f in self.K.folders(ME)))
        self.assertNotIn(m["id"], [i["id"] for i in self.K.view(ME)["items"]])  # messages live in Communications
        note = self.K.comms_note(ME, CommsNote(ids=[x["id"] for x in c["messages"] if x["platform"] == "discord"], title="Embedding cache thread"))
        self.assertEqual(len([l for l in note["links"] if l["rel"] == "derived_from"]), 2)
        s = self.K.slack_status(ME)
        self.assertEqual((s["configured"], s["channel"]), (True, "general"))
        self.assertEqual(self.K.comms_slack(ME)["added"], 2)
        self.assertEqual(self.K.comms_slack(ME)["added"], 0)  # the cursor moved on
        self.K.undo(ME, r["source_id"])  # one import undone: its messages go, the rest stay
        self.assertEqual(self.K.comms(ME, platform="discord")["total"], 0)
        self.assertEqual(self.K.comms(ME, platform="telegram")["total"], 1)

    def test_team_context_reads_its_scopes_and_logs_reuse(self):
        self.K.add_record(ME, RecordIn(title="Validator timeout rule", body="Retry the validator once with a longer timeout before failing the run.", ktype="procedural",
                                       scope="company", approve=True))
        self.K.add_record(ME, RecordIn(title="Other team's validator timeout", body="Only for team nine: validator timeout handling notes.", ktype="procedural",
                                       scope="company", approve=False))  # not approved: never read
        w, c = {"id": 5, "name": "Ridges", "goal": "validator timeout", "description": "", "notes": ""}, {"user_id": 7, "netuid": 62}
        lines = self.K.lines(w, c)
        self.assertTrue(lines and "data not instructions" in lines[0])
        self.assertEqual(len(lines), 2)
        self.assertIn("Validator timeout rule", lines[1])
        self.assertEqual(self.db.q("SELECT actor, label FROM kb_uses WHERE actor='teams:5'"), [{"actor": "teams:5", "label": "SN62 · Ridges"}])

    def test_process_ask_refs_are_checked(self):
        a = self.note("Validator procedure", "Run the validator locally, then register the miner on SN62.")
        b = self.K.capture(ME, CaptureIn(kind="paste", text="Long notes about the validator and miners and registration on SN62."))
        p = self.K.process(ME, b["id"], kh.ModelIn())["data"]["processing"]
        self.assertEqual(p["folder"], "/07-Knowledge/Procedures")
        self.assertTrue(all(x["ref"] != "kb:99999" for x in p["links"]))
        out = self.K.organize(ME, b["id"], OrganizeIn(path=p["folder"], tags=p["tags"], ktype=p["ktype"], links=p["links"], record=p["record"]))
        self.assertEqual(out["path"], "/07-Knowledge/Procedures")
        self.assertTrue(any(l["rel"] == "derived_from" and l["back"] for l in out["links"]))  # the derived record points back at it
        ans = self.K.ask(ME, AskIn(question="How do I register a miner on SN62?"))
        self.assertNotIn("kb:99999", ans["answer"])
        self.assertTrue(ans["evidence"] and all(e["ref"] != "kb:99999" for e in ans["evidence"]))
        self.assertIn(f"kb:{a['id']}", [h["ref"] for h in ans["hits"]])


class MigrationTest(unittest.TestCase):
    """A database from the 11-03 hub (kb_items without the space columns, v1 snapshots without them) opens as My Knowledge."""
    def test_old_rows_become_personal(self):
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        db = AuthDB(os.path.join(d.name, "a.db"))
        q, now = db.q, time.time()
        q("CREATE TABLE custom_agents (id INTEGER PRIMARY KEY, owner_id INTEGER, name TEXT, role TEXT, description TEXT, instructions TEXT, skills TEXT, status TEXT, updated REAL)")
        q("CREATE TABLE agent_memory (id INTEGER PRIMARY KEY, agent_id INTEGER, user_id INTEGER, text TEXT, source TEXT, created REAL)")
        q("""CREATE TABLE kb_items (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, source_id INTEGER, type TEXT, title TEXT,
             body TEXT, data TEXT, trust TEXT, reach TEXT, status TEXT DEFAULT 'kept', stage TEXT, origin_ref TEXT, parent_ref TEXT, hash TEXT,
             provenance TEXT, version INTEGER DEFAULT 1, used INTEGER DEFAULT 0, last_used REAL, created REAL, updated REAL)""")
        q("""CREATE TABLE kb_versions (id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER, version INTEGER, snap TEXT, note TEXT,
             by_user TEXT, ts REAL, UNIQUE (item_id, version))""")
        old_snap = lambda title, body, reach, stage: json.dumps({"title": title, "body": body, "data": "{}", "reach": reach, "status": "kept", "stage": stage, "provenance": "{}",
                                                                 "trust": "yours", "source_id": None, "origin_ref": None, "parent_ref": None, "type": "x", "hash": "h"})
        q("INSERT INTO kb_items (id, user_id, type, title, body, data, trust, reach, status, stage, hash, provenance, version, created, updated) VALUES (1, 7, 'idea', 'Old idea', 'Body', '{}', 'yours', 'agents', 'kept', 'proposed', 'h1', '{}', 1, ?, ?)", (now, now))
        q("INSERT INTO kb_items (id, user_id, type, title, body, data, trust, reach, status, hash, provenance, version, created, updated) VALUES (2, 7, 'lesson', 'Old lesson', 'Retry once.', '{}', 'workspace', 'page', 'kept', 'h2', '{\"source\": \"old export\"}', 1, ?, ?)", (now, now))
        q("INSERT INTO kb_versions (item_id, version, snap, note, by_user, ts) VALUES (1, 1, ?, 'Proposed', 'leo', ?)", (old_snap("Old idea", "Body", "agents", "proposed"), now))
        q("INSERT INTO kb_versions (item_id, version, snap, note, by_user, ts) VALUES (2, 1, ?, 'Imported', 'leo', ?)", (old_snap("Old lesson", "Retry once.", "page", None), now))
        K = kh.Hub(db, HubStub(), lambda m: None)
        rows = {r["id"]: r for r in db.q("SELECT id, space, path, ktype FROM kb_items")}
        self.assertEqual(rows[1], {"id": 1, "space": "personal", "path": "/06-Ideas-and-Connections/Ideas", "ktype": "strategic"})
        self.assertEqual(rows[2], {"id": 2, "space": "personal", "path": "/07-Knowledge/Lessons-Learned", "ktype": "episodic"})
        v = K.view(ME)
        self.assertEqual({i["id"]: i["visibility"] for i in v["ideas"] + v["items"]}, {1: "Shared with your agents", 2: "Private"})
        self.assertEqual(K.item(ME, 2)["provenance"]["source"], "old export")
        K.update(ME, 2, kh.ItemPatch(title="Old lesson, edited"))
        r = K.restore(ME, 2, kh.RestoreIn(version=1))  # an old-shape snapshot: the new columns keep their values
        self.assertEqual((r["title"], r["space"], r["path"]), ("Old lesson", "personal", "/07-Knowledge/Lessons-Learned"))
        self.assertTrue(any(f["path"] == "/00-Inbox" for f in K.folders(ME)))
        kh.Hub(db, HubStub(), lambda m: None)  # opening it again changes nothing
        self.assertEqual(db.q("SELECT COUNT(*) n FROM kb_items", one=True)["n"], 2)


if __name__ == "__main__":
    unittest.main()
