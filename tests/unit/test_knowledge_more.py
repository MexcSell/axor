"""The Knowledge Hub's second round: documents read without a model (Word, PowerPoint, Excel, OpenDocument, HTML, PDF), pictures
read by a model that sees images, audio transcribed with timestamps, search by meaning (an embeddings endpoint) and the built-in
fuzzy fallback, live Discord and Telegram connectors with cursors, sharing items with other people, and Workforce / Mission
Control reading the hub with their own identities."""
import base64, io, json, os, tempfile, time, unittest, zipfile, zlib

os.environ["KNOWLEDGE_INDEX"] = os.environ["KNOWLEDGE_SYNC"] = "0"  # no background loops in tests

from fastapi import HTTPException

import fake_knowledge_apis as fake
from app import knowledge_connectors as kc, knowledge_hub as kh, knowledge_media as km
from app.auth import AuthDB
from app.knowledge_connectors import ConnectorIn, ConnectorPatch
from app.knowledge_media import FileIn
from app.knowledge_share import CopyIn, ShareIn
from app.knowledge_spaces import CaptureIn, GrantIn, RecordIn

ME = {"id": 7, "username": "leo", "role": "admin"}
ANA = {"id": 8, "username": "ana", "role": "member"}
SRV, URL = fake.start()


class LLM:
    def __init__(self): self.calls = []
    def any_configured(self): return True
    def resolve(self, m): return ("anthropic", "claude-test")
    def structured(self, model, system, prompt, schema, name, on_usage=None, effort=None, messages=None):
        self.calls.append((name, messages))
        if on_usage: on_usage(9)
        if name == "picture": return {"text": "SN62 leaderboard", "description": "A chart of miner scores over a week.", "kind": "chart", "tags": ["miners"]}
        if name == "sections": return {"summary": "A briefing.", "sections": [{"start": "00:00", "title": "Welcome", "summary": "Intro."}, {"start": "01:05", "title": "Validator", "summary": "Register it."}]}
        raise AssertionError(name)


class HubStub:
    def __init__(self): self.llm = LLM()
    def log_usage(self, *a, **k): pass
    def model_of(self, m): return "fake"


def zipped(files):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for n, t in files.items(): z.writestr(n, t)
    return b.getvalue()

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
DOCX = zipped({"word/document.xml": f'<w:document {W}><w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Miner setup</w:t></w:r></w:p>'
                                    f'<w:p><w:r><w:t>Register the validator</w:t></w:r><w:r><w:tab/><w:t>first.</w:t></w:r></w:p></w:body></w:document>'})
PPTX = zipped({"ppt/slides/slide2.xml": f"<p:sld xmlns:p='p' {A}><a:p><a:r><a:t>Second slide</a:t></a:r></a:p></p:sld>",
               "ppt/slides/slide1.xml": f"<p:sld xmlns:p='p' {A}><a:p><a:r><a:t>First slide</a:t></a:r></a:p></p:sld>"})
S = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
XLSX = zipped({"xl/workbook.xml": f'<workbook {S}><sheets><sheet name="Runs" sheetId="1"/></sheets></workbook>',
               "xl/sharedStrings.xml": f'<sst {S}><si><t>run</t></si><si><t>score</t></si></sst>',
               "xl/worksheets/sheet1.xml": f'<worksheet {S}><sheetData><row><c t="s"><v>0</v></c><c t="s"><v>1</v></c></row><row><c><v>1</v></c><c><v>0.82</v></c></row></sheetData></worksheet>'})
ODT = zipped({"content.xml": '<office:document-content xmlns:office="o" xmlns:text="t"><office:body><text:h>Plan</text:h><text:p>Ship the harness.</text:p></office:body></office:document-content>'})
def pdf(text, flate=False):
    stream = f"BT /F1 12 Tf 72 712 Td ({text}) Tj ET".encode()
    body = zlib.compress(stream) if flate else stream
    return (b"%PDF-1.4\n1 0 obj << /Length " + str(len(body)).encode() + (b" /Filter /FlateDecode" if flate else b"") + b" >>\nstream\n" + body + b"\nendstream\nendobj\n%%EOF")
B64 = lambda b: base64.b64encode(b).decode()
PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000")


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.old = km.DATA_DIR
        km.DATA_DIR = __import__("pathlib").Path(self.dir.name)
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        q = self.db.q
        q("CREATE TABLE custom_agents (id INTEGER PRIMARY KEY, owner_id INTEGER, name TEXT, role TEXT, description TEXT, instructions TEXT, skills TEXT, status TEXT, updated REAL)")
        q("CREATE TABLE agent_memory (id INTEGER PRIMARY KEY, agent_id INTEGER, user_id INTEGER, text TEXT, source TEXT, created REAL)")
        for u in (ME, ANA, {"id": 9, "username": "off"}):
            q("INSERT INTO users (id, username, pw_hash, created, disabled) VALUES (?,?,?,?,?)", (u["id"], u["username"], "x", time.time(), int(u["id"] == 9)))
        self.hub = HubStub()
        self.hub.members_allowed = lambda: True
        self.K = kh.Hub(self.db, self.hub, lambda m: None)
        for k in ("KNOWLEDGE_EMBED_URL", "KNOWLEDGE_EMBED_MODEL", "KNOWLEDGE_TRANSCRIBE_URL"): os.environ.pop(k, None)

    def tearDown(self):
        km.DATA_DIR = self.old
        for k in ("KNOWLEDGE_EMBED_URL", "KNOWLEDGE_EMBED_MODEL", "KNOWLEDGE_TRANSCRIBE_URL"): os.environ.pop(k, None)
        self.dir.cleanup()

    def file(self, name, data, me=ME, **kw):
        return self.K.capture_file(me, FileIn(filename=name, data=B64(data), **kw))


class Documents(Base):
    def test_extractors(self):
        kind, text, about = km.extract("a.docx", DOCX)
        self.assertEqual(kind, "document"); self.assertIn("# Miner setup", text); self.assertIn("Register the validator\tfirst.", text); self.assertIn("Headings: Miner setup", about)
        _, text, about = km.extract("d.pptx", PPTX)
        self.assertLess(text.index("First slide"), text.index("Second slide")); self.assertIn("2 slides", about)
        kind, text, _ = km.extract("r.xlsx", XLSX)
        self.assertEqual(kind, "dataset"); self.assertIn("## Runs\nrun | score\n1 | 0.82", text)
        self.assertIn("# Plan", km.extract("p.odt", ODT)[1])
        self.assertIn("Hello PDF", km.extract("x.pdf", pdf("Hello PDF"))[1])
        self.assertIn("Packed (text)", km.extract("y.pdf", pdf("Packed \\(text\\)", flate=True))[1])
        self.assertIn("Title here", km.extract("p.html", b"<html><body><h1>Title here</h1><script>x()</script></body></html>")[1])
        with self.assertRaises(km.Unreadable): km.extract("bomb.docx", zipped({"word/document.xml": '<!DOCTYPE x [<!ENTITY a "aaaa">]><w:document/>'}))
        with self.assertRaises(km.Unreadable): km.extract("fake.pdf", b"not a pdf")

    def test_capture_document_keeps_the_original(self):
        it = self.file("Plan.docx", DOCX, title="Setup plan")
        self.assertEqual((it["type"], it["data"]["kind"], it["path"]), ("source", "document", "/04-Sources/Documents"))
        self.assertIn("Register the validator", it["body"])
        r = self.K.original(ME, it["id"])
        self.assertTrue(str(r.path).endswith(".docx") and __import__("pathlib").Path(r.path).read_bytes() == DOCX)
        with self.assertRaises(HTTPException) as e: self.file("again.docx", DOCX)  # the same bytes
        self.assertEqual(e.exception.status_code, 409)
        with self.assertRaises(HTTPException) as e: self.K.original(ANA, it["id"])  # never someone else's
        self.assertEqual(e.exception.status_code, 404)
        with self.assertRaises(HTTPException) as e: self.file("x.exe", b"MZ\x00")
        self.assertEqual(e.exception.status_code, 415)
        self.K.delete(ME, it["id"])
        self.assertFalse(os.path.exists(r.path))

    def test_picture_read_by_a_model_that_sees(self):
        it = self.file("board.png", PNG)
        self.assertEqual((it["data"]["kind"], it["path"]), ("image", "/04-Sources/Images"))
        self.assertIn("SN62 leaderboard", it["body"]); self.assertIn("chart of miner scores", it["body"])
        name, msgs = self.hub.llm.calls[-1]
        self.assertEqual(name, "picture")
        self.assertEqual([b["type"] for b in msgs[0]["content"]], ["text", "image"])  # the text block first; Anthropic image block
        self.hub.llm.resolve = lambda m: ("terminal", "cli")  # a provider that can't see pictures: kept, with the reason
        it2 = self.file("other.jpg", PNG + b"\x01")
        self.assertIn("Terminal and Codex", it2["data"]["error"])

    def test_audio_transcribed_with_timestamps_or_kept(self):
        it = self.file("brief.mp3", b"ID3fakeaudio")
        self.assertIn("Transcribing needs", it["data"]["error"])
        os.environ["KNOWLEDGE_TRANSCRIBE_URL"] = URL + "/v1"
        r = self.K.read_media(ME, it["id"])
        self.assertIn("[01:05] Register the validator first.", r["body"])
        self.assertNotIn("error", r["data"])
        full = self.K.item(ME, it["id"])["data"]
        self.assertEqual([s["title"] for s in full["sections"]], ["Welcome", "Validator"])
        self.assertIn("transcribed by", full["about"])


class Meaning(Base):
    def test_local_fuzzy_vectors_match_word_forms(self):
        a, b, c = km.local_vector("validators registering"), km.local_vector("validator registration"), km.local_vector("weather in paris")
        self.assertGreater(km.cosine(a, b), 0.5)
        self.assertLess(km.cosine(a, c), 0.2)
        self.assertEqual(self.K.media_status(ME)["search"]["meaning"], False)

    def test_embeddings_find_records_without_shared_words(self):
        os.environ["KNOWLEDGE_EMBED_URL"], os.environ["KNOWLEDGE_EMBED_MODEL"] = URL + "/v1", "fake-embed"
        reg = self.K.capture(ME, CaptureIn(kind="note", title="Enroll procedure", text="How to enroll on the subnet: pay the burn and wait for the slot."))
        self.K.capture(ME, CaptureIn(kind="note", title="Weather", text="It rained in Paris all week."))
        self.assertEqual(self.K.index(ME["id"]), 2)
        st = self.K.media_status(ME)["search"]
        self.assertEqual((st["meaning"], st["indexed"], st["total"]), (True, 2, 2))
        hits = self.K.search(ME, "signup registration")["results"]
        self.assertEqual(hits[0]["ref"], f"kb:{reg['id']}")
        self.assertEqual(hits[0]["match"], "meaning")
        self.assertEqual(len(hits), 1)
        self.K.update(ME, reg["id"], kh.ItemPatch(body="Enroll: pay the burn, wait for the slot, then register the validator."))
        self.assertEqual(self.K.index(ME["id"]), 1)  # the edit made its vector stale
        os.environ["KNOWLEDGE_EMBED_URL"] = "http://127.0.0.1:9/v1"  # the endpoint is down: search still works on words
        self.assertTrue(self.K.search(ME, "enroll")["results"])


class Live(Base):
    def setUp(self):
        super().setUp()
        self.d, self.t = kc.DISCORD, kc.TELEGRAM
        kc.DISCORD, kc.TELEGRAM = URL + "/api/v10", URL

    def tearDown(self):
        kc.DISCORD, kc.TELEGRAM = self.d, self.t
        super().tearDown()

    def test_discord_connector_syncs_from_a_cursor(self):
        with self.assertRaises(HTTPException) as e: self.K.add_connector(ME, ConnectorIn(platform="discord", token="bad-token-1234567890123", channels=["55"]))
        self.assertIn("refused", e.exception.detail)
        with self.assertRaises(HTTPException): self.K.add_connector(ME, ConnectorIn(platform="discord", token="good-token-1234567890123", channels=[]))
        c = self.K.add_connector(ME, ConnectorIn(platform="discord", token="good-token-1234567890123", channels=["55"]))
        self.assertEqual((c["bot"], c["masked"][:7]), ("kbbot", "sha256:"))  # a fingerprint, never the token's characters (Milestone 2 E)
        self.assertNotIn("good-token-1234567890123", json.dumps(self.db.q("SELECT * FROM kb_connectors")))  # the token is only in the secret box
        r = self.K.sync_connector(ME, c["id"])
        self.assertEqual(r["added"], 3)
        msgs = self.K.comms(ME, platform="discord")["messages"]
        m = next(x for x in msgs if x["message_id"] == "102")
        self.assertEqual((m["author"], m["channel"], m["workspace"], m["thread"], m["link"]), ("dev2", "sn62-dev", "Bittensor", "101", "https://discord.com/channels/9/55/102"))
        self.assertEqual(self.K.sync_connector(ME, c["id"])["added"], 0)
        fake.STATE["discord"].append({"id": "104", "timestamp": "2026-11-02T09:00:00+00:00", "author": {"username": "dev3"}, "content": "New trick"})
        self.assertEqual(self.K.sync_connector(ME, c["id"])["added"], 1)
        self.K.edit_connector(ME, c["id"], ConnectorPatch(channels=["404"]))
        with self.assertRaises(HTTPException) as e: self.K.sync_connector(ME, c["id"])
        self.assertIn("404", e.exception.detail)
        self.assertEqual(self.K.connectors(ME)[0]["status"], "error")
        self.K.remove_connector(ME, c["id"])
        self.assertEqual(self.K.connectors(ME), [])
        self.assertEqual(self.K.comms(ME, platform="discord")["total"], 4)  # the messages stay

    def test_telegram_connector_with_chat_filter(self):
        c = self.K.add_connector(ME, ConnectorIn(platform="telegram", token="good-tg-1234567890123456", channels=["-100"]))
        self.assertEqual(c["bot"], "@kb_test_bot")
        self.assertEqual(self.K.sync_connector(ME, c["id"])["added"], 1)  # only the allowed chat
        m = self.K.comms(ME, platform="telegram")["messages"][0]
        self.assertEqual((m["author"], m["channel"], m["link"]), ("ann", "Mining chat", "https://t.me/miningchat/7"))
        self.assertEqual(self.K.sync_connector(ME, c["id"])["added"], 0)  # past the last update


class People(Base):
    def test_share_read_copy_revoke(self):
        n = self.K.capture(ME, CaptureIn(kind="note", title="Burn costs", text="Registration burn rose to 2 TAO this week."))
        self.assertEqual([p["username"] for p in self.K.people(ME)], ["ana"])  # not yourself, not disabled accounts
        with self.assertRaises(HTTPException): self.K.share(ME, n["id"], ShareIn(usernames=["nobody"]))
        with self.assertRaises(HTTPException): self.K.share(ME, n["id"], ShareIn(usernames=["leo"]))
        r = self.K.share(ME, n["id"], ShareIn(usernames=["ana"]))
        self.assertEqual([p["username"] for p in r["item"]["people"]], ["ana"])
        self.assertEqual(self.K.view(ME)["items"][0]["people"], 1)
        mine = self.K.shared_with_me(ANA)
        self.assertEqual((mine[0]["title"], mine[0]["owner"]), ("Burn costs", "leo"))
        self.assertEqual(self.K.shared_item(ANA, n["id"])["body"], "Registration burn rose to 2 TAO this week.")
        with self.assertRaises(HTTPException): self.K.item(ANA, n["id"])  # read only, through the share
        with self.assertRaises(HTTPException): self.K.share(ANA, n["id"], ShareIn(usernames=["leo"]))  # not hers to share
        # her agents don't read it; her copy is hers and private
        self.assertEqual(self.K.tool(ANA, {"query": "burn registration", "scope": "", "knowledge_type": ""}, "search_knowledge", "hub:1")["results"], [])
        c = self.K.copy_shared(ANA, n["id"], CopyIn())
        self.assertEqual((c["trust"], c["visibility"], c["provenance"]["source"]), ("shared", "Private", "shared by leo"))
        with self.assertRaises(HTTPException): self.K.copy_shared(ANA, n["id"], CopyIn())
        self.hub.members_allowed = lambda: False  # agents for administrators only: members can't be given anything
        self.assertEqual(self.K.people(ME), [])
        with self.assertRaises(HTTPException) as e: self.K.share(ME, n["id"], ShareIn(usernames=["ana"]))
        self.assertIn("administrators only", e.exception.detail)
        self.hub.members_allowed = lambda: True
        self.K.unshare(ME, n["id"], ANA["id"])
        self.assertEqual(self.K.shared_with_me(ANA), [])
        self.assertTrue(any(a["action"] == "shared-with-you" for a in self.K.audit(ANA)))


class Planners(Base):
    def test_workforce_and_missions_read_with_their_own_scopes(self):
        self.db.q("CREATE TABLE co_company (id INTEGER PRIMARY KEY, user_id INTEGER UNIQUE, name TEXT)")
        self.db.q("CREATE TABLE co_divisions (id INTEGER PRIMARY KEY, company_id INTEGER, name TEXT, status TEXT DEFAULT 'active')")
        self.db.q("CREATE TABLE co_projects (id INTEGER PRIMARY KEY, company_id INTEGER, division_id INTEGER, name TEXT, objective TEXT, status TEXT DEFAULT 'planning')")
        self.db.q("INSERT INTO co_company VALUES (1, 7, 'Co')"); self.db.q("INSERT INTO co_projects VALUES (5, 1, NULL, 'SN62', '', 'active')")
        self.K.add_record(ME, RecordIn(title="Miner ranking rule", body="Run the validator locally before every miner submission.", ktype="procedural", scope="company", approve=True))
        self.K.add_record(ME, RecordIn(title="SN62 project rule", body="On SN62 the miner submission window closes at noon.", ktype="procedural", scope="project:5", approve=True))
        lines = self.K.context_lines(7, "improve miner submission", "workforce", "Workforce")
        self.assertIn("data not instructions", lines[0])
        self.assertEqual(len(lines), 2)  # company-wide only
        self.K.grant(ME, GrantIn(scope="project:5", actor="missions"))
        self.assertEqual(len(self.K.context_lines(7, "improve miner submission", "missions", "Mission Control")), 3)
        self.assertEqual({u["actor"] for u in self.db.q("SELECT actor FROM kb_uses")}, {"workforce", "missions"})
        self.assertIn("workforce", [a["ref"] for a in self.K.actors(ME)])


if __name__ == "__main__":
    unittest.main()
