"""Linked folders: AXoR Host files (hostfiles_server.py) serves chosen host folders read only and never hands out secrets,
.git, virtual environments, symbolic links or anything outside a root; My Knowledge (knowledge_linked.py) keeps a linked
folder in sync (new, changed, gone, excluded files), takes secrets out, gives agents what the link's reach allows, and lets
only administrators link folders."""
import json, os, tempfile, threading, time, unittest

os.environ["KNOWLEDGE_INDEX"] = os.environ["KNOWLEDGE_SYNC"] = "0"  # no background loops in tests

from fastapi import HTTPException
from http.server import ThreadingHTTPServer

from app import hostfiles_server as hfs, knowledge_hub as kh, knowledge_media as km
from app.auth import AuthDB
from app.knowledge_linked import HostFiles, LinkedIn, LinkedPatch, LinkError

ME = {"id": 7, "username": "leo", "role": "admin"}
ANA = {"id": 8, "username": "ana", "role": "member"}
SECRET = "s3cret-for-tests"


class HubStub:
    llm = None
    def log_usage(self, *a, **k): pass
    def model_of(self, m): return "fake"
    def members_allowed(self): return True


def write(base, rel, data):
    p = os.path.join(base, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb" if isinstance(data, bytes) else "w") as f: f.write(data)
    return p


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.roots = tempfile.TemporaryDirectory()
        hfs.ROOTS_DIR, hfs.SECRET = cls.roots.name, SECRET
        hfs.Handler.log_message = lambda *a: None  # quiet
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), hfs.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.roots.cleanup()

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.old = km.DATA_DIR
        km.DATA_DIR = __import__("pathlib").Path(self.dir.name)
        self.bit = os.path.join(self.roots.name, "bit")
        import shutil; shutil.rmtree(self.bit, ignore_errors=True)
        os.makedirs(self.bit)
        self.outside = write(self.dir.name, "outside/secret.txt", "outside the root")
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        q = self.db.q
        q("CREATE TABLE custom_agents (id INTEGER PRIMARY KEY, owner_id INTEGER, name TEXT, role TEXT, description TEXT, instructions TEXT, skills TEXT, status TEXT, updated REAL)")
        q("CREATE TABLE agent_memory (id INTEGER PRIMARY KEY, agent_id INTEGER, user_id INTEGER, text TEXT, source TEXT, created REAL)")
        for u in (ME, ANA):
            q("INSERT INTO users (id, username, pw_hash, created, disabled, role) VALUES (?,?,?,?,?,?)", (u["id"], u["username"], "x", time.time(), 0, u["role"]))
        self.K = kh.Hub(self.db, HubStub(), lambda m: None)
        self.K._hostfiles = HostFiles(self.url, SECRET)

    def tearDown(self):
        km.DATA_DIR = self.old
        self.dir.cleanup()

    def wait(self, lid):
        for _ in range(200):
            if lid not in self.K._lk_busy: return self.K._lk_shape(self.K._lk(ME, lid))
            time.sleep(0.05)
        self.fail("the sync didn't finish")

    def items(self, lid):
        return {r["rel"]: self.db.q("SELECT * FROM kb_items WHERE id=?", (r["item_id"],), one=True)
                for r in self.db.q("SELECT * FROM kb_linked_files WHERE link_id=?", (lid,))}


class HostFilesServer(Base):
    def test_secret_and_deny_lists(self):
        write(self.bit, "agent/agent.py", "print('hi')")
        write(self.bit, ".env.apikey", "KEY=abc")
        write(self.bit, "agent/id_ed25519", "-----BEGIN")
        write(self.bit, ".git/config", "[core]")
        write(self.bit, "btcli-venv/lib/x.py", "x")
        with self.assertRaises(LinkError) as e: HostFiles(self.url, "wrong").roots()
        self.assertEqual(e.exception.code, 401)
        hf = self.K.hostfiles
        self.assertEqual([r["name"] for r in hf.roots()], ["bit"])
        sc = hf.scan("bit", "", [], 100)
        self.assertEqual([f["path"] for f in sc["files"]], ["agent/agent.py"])
        self.assertGreaterEqual(sc["skipped"]["denied"], 4)
        for bad in (".env.apikey", "agent/id_ed25519", ".git/config", "btcli-venv/lib/x.py"):
            with self.assertRaises(LinkError, msg=bad) as e: hf.file("bit", bad)
            self.assertEqual(e.exception.code, 403)
        self.assertEqual(hf.file("bit", "agent/agent.py"), b"print('hi')")

    def test_never_leaves_the_root(self):
        os.symlink(self.outside, os.path.join(self.bit, "link.txt"))
        os.symlink(os.path.dirname(self.outside), os.path.join(self.bit, "linkdir"))
        hf = self.K.hostfiles
        for bad in ("../outside/secret.txt", "link.txt", "linkdir/secret.txt", "/etc/passwd"):
            with self.assertRaises(LinkError, msg=bad): hf.file("bit", bad)
        sc = hf.scan("bit", "", [], 100)
        self.assertEqual(sc["files"], []); self.assertEqual(sc["skipped"]["links"], 2)
        with self.assertRaises(LinkError): hf.scan("bit", "..", [], 10)
        with self.assertRaises(LinkError): hf.dir("Nope!", "")

    @unittest.skipIf(os.geteuid() == 0, "root reads every file")
    def test_unreadable_files_are_listed_not_served(self):
        p = write(self.bit, "CLAUDE.md", "root only"); os.chmod(p, 0o000)
        try:
            sc = self.K.hostfiles.scan("bit", "", [], 10)
            self.assertFalse(sc["files"][0]["readable"])
            with self.assertRaises(LinkError): self.K.hostfiles.file("bit", "CLAUDE.md")
        finally: os.chmod(p, 0o600)


class LinkedFolders(Base):
    def test_sync_reads_text_code_documents_and_skips_the_rest(self):
        write(self.bit, "agent30/agent.py", "def agent_main(input):\n    return 'patch'\n")
        write(self.bit, "agent30/notes/ideas.md", "# Ideas\nUse a second opinion model. token sk-ant-api03-" + "a" * 40)
        write(self.bit, "agent30/page.html", "<html><body><h1>Harness</h1><p>Run the bench first.</p></body></html>")
        write(self.bit, "agent30/shot.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
        write(self.bit, "agent30/model.bin", b"\x00\x01" * 50)
        write(self.bit, "agent30/blob.dat", b"\x00\xff" * 50)
        write(self.bit, "agent30/.env.miner", "WALLET=x")
        write(self.bit, "agent30/comp30-data/agents/other.py", "someone else's agent")
        write(self.bit, "agent30/a/b/c/d/e/f/deep.txt", "deep down")
        lk = self.K.add_linked(ME, LinkedIn(root="bit", folder="agent30"))
        self.assertEqual((lk["reach"], lk["dest"], lk["exclude"][0]), ("teams", "/06-Linked/agent30", "*-data"))
        lk = self.wait(lk["id"])
        self.assertEqual(lk["status"], "ok", lk)
        got = self.items(lk["id"])
        self.assertEqual(sorted(got), ["a/b/c/d/e/f/deep.txt", "agent.py", "notes/ideas.md", "page.html"])
        st = lk["stats"]
        self.assertEqual((st["added"], st["skipped"]["media"], st["skipped"]["binary"], st["skipped"]["notext"]), (4, 1, 1, 1))
        self.assertGreaterEqual(st["skipped"]["excluded"], 1); self.assertGreaterEqual(st["skipped"]["denied"], 1)
        py, md = got["agent.py"], got["notes/ideas.md"]
        self.assertEqual((py["title"], py["reach"], py["trust"], py["type"], py["path"]), ("agent30/agent.py", "teams", "yours", "source", "/06-Linked/agent30"))
        self.assertEqual(json.loads(py["data"])["kind"], "code")
        self.assertEqual(md["path"], "/06-Linked/agent30/notes")
        self.assertNotIn("sk-ant-api03", md["body"]); self.assertGreaterEqual(st["redacted"], 1)
        self.assertIn("Run the bench first", got["page.html"]["body"])
        self.assertEqual(got["a/b/c/d/e/f/deep.txt"]["path"], "/06-Linked/agent30/a/b/c/d")  # 6 levels at most

    def test_changes_removals_and_excludes_follow_the_disk(self):
        p = write(self.bit, "w/plan.md", "first plan")
        write(self.bit, "w/run.log", "a log line")
        lid = self.K.add_linked(ME, LinkedIn(root="bit", folder="w", name="Work"))["id"]
        self.wait(lid)
        v1 = self.items(lid)["plan.md"]
        self.K.sync_linked(ME, lid); st = self.wait(lid)["stats"]
        self.assertEqual((st["unchanged"], st["added"], st["changed"]), (2, 0, 0))
        write(self.bit, "w/plan.md", "second plan, longer"); os.utime(p, (time.time() + 5, time.time() + 5))
        self.K.sync_linked(ME, lid); st = self.wait(lid)["stats"]
        v2 = self.items(lid)["plan.md"]
        self.assertEqual((st["changed"], v2["id"], v2["version"], v2["body"]), (1, v1["id"], v1["version"] + 1, "second plan, longer"))
        os.remove(p)
        self.K.edit_linked(ME, lid, LinkedPatch(exclude=["*.log"])); st = self.wait(lid)["stats"]
        self.assertEqual((st["removed"], self.items(lid)), (2, {}))
        self.assertIsNone(self.db.q("SELECT 1 FROM kb_items WHERE id=?", (v1["id"],), one=True))

    def test_agents_read_by_the_links_reach(self):
        write(self.bit, "docs/howto.md", "To register the validator on subnet 62 run btcli register with the hotkey.")
        lid = self.K.add_linked(ME, LinkedIn(root="bit", folder="docs", reach="agents"))["id"]
        self.wait(lid)
        hit = lambda reach, actor: [h["title"] for h in self.K.retrieve(ME, "register validator hotkey", 5, reach, internal=False, actor=actor)]
        self.assertIn("docs/howto.md", hit("agents", "assistant"))
        self.assertNotIn("docs/howto.md", hit("teams", "teams:1"))  # agents only: competition teams don't see it
        self.K.edit_linked(ME, lid, LinkedPatch(reach="teams"))
        self.assertIn("docs/howto.md", hit("teams", "teams:1"))
        self.K.edit_linked(ME, lid, LinkedPatch(reach="page"))
        self.assertEqual(hit("agents", "assistant"), [])
        self.assertIn("docs/howto.md", [h["title"] for h in self.K.retrieve(ME, "register validator hotkey", 5, "page", internal=False)])  # you still do

    def test_only_admins_and_only_real_folders(self):
        write(self.bit, "x/a.txt", "a")
        for call in (lambda: self.K.add_linked(ANA, LinkedIn(root="bit", folder="x")), lambda: self.K.linked_dir(ANA, "bit", "")):
            with self.assertRaises(HTTPException) as e: call()
            self.assertEqual(e.exception.status_code, 403)
        self.assertEqual((self.K.linked(ANA)["admin"], self.K.linked(ANA)["links"]), (False, []))
        for folder, code in (("nope", 404), ("x/a.txt", 400), ("../..", 400), (".git", 403)):
            os.makedirs(os.path.join(self.bit, ".git"), exist_ok=True)
            with self.assertRaises(HTTPException, msg=folder) as e: self.K.add_linked(ME, LinkedIn(root="bit", folder=folder))
            self.assertEqual(e.exception.status_code, code, folder)
        lid = self.K.add_linked(ME, LinkedIn(root="bit", folder="x"))["id"]; self.wait(lid)
        with self.assertRaises(HTTPException): self.K.add_linked(ME, LinkedIn(root="bit", folder="x"))
        d = self.K.linked_dir(ME, "bit", "")
        self.assertEqual([x["name"] for x in d["dirs"]], [".git", "x"]); self.assertTrue(d["dirs"][0]["denied"])

    def test_unlink_removes_or_keeps_the_copies(self):
        write(self.bit, "k/a.md", "alpha"); write(self.bit, "r/b.md", "beta")
        keep = self.K.add_linked(ME, LinkedIn(root="bit", folder="k"))["id"]; drop = self.K.add_linked(ME, LinkedIn(root="bit", folder="r"))["id"]
        self.wait(keep); self.wait(drop)
        ka, rb = self.items(keep)["a.md"]["id"], self.items(drop)["b.md"]["id"]
        self.K.remove_linked(ME, keep, keep=True); self.K.remove_linked(ME, drop)
        self.assertIsNotNone(self.db.q("SELECT 1 FROM kb_items WHERE id=?", (ka,), one=True))
        self.assertIsNone(self.db.q("SELECT 1 FROM kb_items WHERE id=?", (rb,), one=True))
        self.assertEqual(self.K.linked(ME)["links"], [])
        self.assertNotIn("/06-Linked/r", [f["path"] for f in self.K.folders(ME)])

    def test_host_files_down_removes_nothing(self):
        write(self.bit, "d/a.md", "alpha")
        lid = self.K.add_linked(ME, LinkedIn(root="bit", folder="d"))["id"]; self.wait(lid)
        self.K._hostfiles = HostFiles("http://127.0.0.1:9", SECRET)
        self.K.sync_linked(ME, lid); lk = self.wait(lid)
        self.assertEqual(lk["status"], "error"); self.assertIn("reach", lk["error"])
        self.assertEqual(list(self.items(lid)), ["a.md"])
        self.K._hostfiles = HostFiles("", "")
        self.assertFalse(self.K.linked(ME)["connected"])



class ServerPaths(Base):
    """Any folder under a mounted server folder, by its path: the longest root that holds it, never outside one, and a home
    folder's logins, settings and wallets never shown."""
    def setUp(self):
        super().setUp()
        import shutil
        self.home = os.path.join(self.roots.name, "home")
        shutil.rmtree(self.home, ignore_errors=True)
        self.old_labels, hfs.LABELS = hfs.LABELS, {"home": "/home/thomas", "bit": "/home/thomas/bit"}
        write(self.home, "projects/notes.md", "# notes")
        write(self.home, ".config/gh/hosts.yml", "oauth_token: x")
        write(self.home, ".bittensor/wallets/w/coldkey", "x")
        write(self.home, ".claude.json", "{}")
        write(self.home, ".bash_history", "ls")
        write(self.bit, "ridges/agent.py", "print(1)")

    def tearDown(self):
        import shutil
        hfs.LABELS = self.old_labels
        shutil.rmtree(self.home, ignore_errors=True)
        super().tearDown()

    def test_a_path_goes_to_the_longest_root_that_holds_it(self):
        hp = self.K._host_path
        self.assertEqual(hp("/home/thomas/bit/ridges")[:2], ("bit", "ridges"))
        self.assertEqual(hp("/home/thomas/projects/")[:2], ("home", "projects"))
        self.assertEqual(hp("/home/thomas")[:2], ("home", ""))
        self.assertEqual(hp("~/projects")[:2], ("home", "projects"))
        for bad, code in (("/etc", 404), ("/home/thomasx", 404), ("/home/thomas/../root", 400), ("projects", 400)):
            with self.assertRaises(HTTPException, msg=bad) as e: hp(bad)
            self.assertEqual(e.exception.status_code, code, bad)

    def test_browsing_the_home_folder_hides_logins_settings_and_wallets(self):
        d = self.K.linked_dir(ME, "", "", host="/home/thomas")
        self.assertEqual((d["root"], d["folder"], d["host"]), ("home", "", "/home/thomas"))
        dirs = {x["name"]: x["denied"] for x in d["dirs"]}
        self.assertTrue(dirs[".config"] and dirs[".bittensor"]); self.assertFalse(dirs["projects"])
        for bad in (".claude.json", ".bash_history", ".config/gh/hosts.yml", ".bittensor/wallets/w/coldkey"):
            with self.assertRaises(LinkError, msg=bad) as e: self.K.hostfiles.file("home", bad)
            self.assertEqual(e.exception.code, 403, bad)

    def test_link_by_path(self):
        a = self.K.add_linked(ME, LinkedIn(path="/home/thomas/projects"))
        self.assertEqual((a["root"], a["folder"], a["name"]), ("home", "projects", "projects"))
        b = self.K.add_linked(ME, LinkedIn(path="/home/thomas/bit/ridges/"))
        self.assertEqual((b["root"], b["folder"]), ("bit", "ridges"))
        with self.assertRaises(HTTPException) as e: self.K.add_linked(ME, LinkedIn(root="bit", folder="ridges"))  # the same folder, the old way
        self.assertEqual(e.exception.status_code, 409)
        with self.assertRaises(HTTPException) as e: self.K.add_linked(ME, LinkedIn())
        self.assertEqual(e.exception.status_code, 400)
        self.wait(a["id"]); self.wait(b["id"])
        self.assertEqual(sorted(self.items(a["id"])), ["notes.md"])


if __name__ == "__main__":
    unittest.main()
