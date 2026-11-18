"""developer.py + dev_files / dev_terminal / dev_claude: the administrators' Developer page (explorer, terminals, Claude panel)."""
import json, os, shutil, tempfile, time, unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import dev_claude, dev_files, dev_terminal, developer

XRW = {"X-Requested-With": "scout"}


class FakeDB:
    def __init__(self): self.logs = []
    def log(self, action, actor="", target="", ip="", detail=""): self.logs.append((action, actor, target))


def helpers():
    """admin/sudo as AXoR's admin router makes them, keyed on a test header: none, member, admin, admin+sudo."""
    def who(req):
        role = req.headers.get("x-test-user", "")
        if not role: raise HTTPException(401, "Sign in required.")
        return {"username": role, "role": "admin" if role.startswith("admin") else "user"}
    def admin(req):
        u = who(req)
        if u["role"] != "admin": raise HTTPException(403, "Administrators only.")
        return u
    def sudo(req):
        u = admin(req)
        if u["username"] != "admin-sudo": raise HTTPException(403, "SUDO_REQUIRED")
        return u
    return {"admin": admin, "sudo": sudo}


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.data = Path(self.dir.name) / "data"
        self.data.mkdir()
        self.env = mock.patch.dict(os.environ, {"DATA_DIR": str(self.data)})
        self.env.start()
        self.db = FakeDB()
        app = FastAPI()
        app.include_router(developer.build(self.db, helpers(), lambda req: "127.0.0.1"))
        self.c = TestClient(app).__enter__()  # one event loop for the whole test: shells register readers on it

    def tearDown(self):
        dev_terminal.close_all()
        self.c.__exit__(None, None, None)
        self.env.stop()
        self.dir.cleanup()

    def as_(self, who): return {**XRW, "x-test-user": who}


class Files(Base):
    def test_roots_are_the_code_folder_data_and_opened_folders(self):
        names = [r["name"] for r in self.c.get("/api/dev/files/roots", headers=self.as_("admin-sudo")).json()]
        self.assertEqual(names, ["axor", "data"])
        extra = Path(self.dir.name) / "elsewhere"
        extra.mkdir()
        r = self.c.post("/api/dev/files/roots", json={"path": str(extra)}, headers=self.as_("admin-sudo"))
        self.assertEqual(r.status_code, 200, r.text)
        roots = self.c.get("/api/dev/files/roots", headers=self.as_("admin-sudo")).json()
        self.assertEqual(roots[-1], {"name": "elsewhere", "path": str(extra.resolve()), "opened": "1"})
        self.assertTrue((self.data / "developer" / "roots.json").is_file())  # kept for every administrator
        self.c.delete("/api/dev/files/roots", params={"path": str(extra)}, headers=self.as_("admin-sudo"))
        self.assertEqual(len(self.c.get("/api/dev/files/roots", headers=self.as_("admin-sudo")).json()), 2)
        self.assertTrue(extra.is_dir())  # closing a folder never touches the disk
        self.assertIn(("dev.folder_open", "admin-sudo", str(extra.resolve())), self.db.logs)

    def test_read_write_create_move_copy_delete(self):
        h, d = self.as_("admin-sudo"), str(self.data)
        self.assertEqual(self.c.post("/api/dev/files/create", json={"path": d + "/src", "folder": True}, headers=h).status_code, 200)
        r = self.c.put("/api/dev/files/write", json={"path": d + "/src/a.py", "text": "print('hi')\n"}, headers=h)
        self.assertEqual(r.json()["size"], 12)
        got = self.c.get("/api/dev/files/read", params={"path": d + "/src/a.py"}, headers=h).json()
        self.assertEqual((got["kind"], got["binary"], got["text"]), ("python", False, "print('hi')\n"))
        self.c.post("/api/dev/files/move", json={"src": d + "/src/a.py", "dest": d + "/src/b.py", "keep_source": True}, headers=h)
        self.c.post("/api/dev/files/move", json={"src": d + "/src/a.py", "dest": d + "/c.py"}, headers=h)
        names = [i["name"] for i in self.c.get("/api/dev/files/list", params={"path": d}, headers=h).json()["items"]]
        self.assertEqual(names[:2], ["src", "c.py"])  # folders first
        self.assertTrue((self.data / "src" / "b.py").is_file() and not (self.data / "src" / "a.py").exists())
        r = self.c.post("/api/dev/files/delete", json={"paths": [d + "/src"]}, headers=h)
        self.assertEqual(r.json()["deleted"], [d + "/src"])
        self.assertEqual([a for a, *_ in self.db.logs], ["dev.file_create", "dev.file_write", "dev.file_copy", "dev.file_move", "dev.file_delete"])

    def test_paths_stay_inside_the_roots(self):
        h = self.as_("admin-sudo")
        outside = Path(self.dir.name) / "secret.txt"
        outside.write_text("no")
        for path in (str(outside), str(self.data / ".." / "secret.txt"), "", "x\0y"):
            r = self.c.get("/api/dev/files/read", params={"path": path}, headers=h)
            self.assertEqual(r.status_code, 400, path)
        link = self.data / "link"
        link.symlink_to(outside)
        self.assertEqual(self.c.get("/api/dev/files/read", params={"path": str(link)}, headers=h).status_code, 400)
        self.assertEqual(self.c.post("/api/dev/files/delete", json={"paths": [str(self.data)]}, headers=h).status_code, 400)  # a root

    def test_git_internals_are_read_only(self):
        (self.data / ".git").mkdir()
        r = self.c.put("/api/dev/files/write", json={"path": str(self.data / ".git" / "config"), "text": "x"}, headers=self.as_("admin-sudo"))
        self.assertEqual(r.status_code, 400)
        self.assertIn(".git", r.json()["detail"])

    def test_upload_is_the_raw_body(self):
        h = {**self.as_("admin-sudo"), "Content-Type": "application/octet-stream"}
        r = self.c.post("/api/dev/files/upload", params={"folder": str(self.data), "name": "../up.bin"}, content=b"\x00\x01data", headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((self.data / "up.bin").read_bytes(), b"\x00\x01data")  # the name's folder part is dropped
        with mock.patch.object(developer, "MAX_UPLOAD", 4):
            r = self.c.post("/api/dev/files/upload", params={"folder": str(self.data), "name": "big"}, content=b"12345", headers=h)
        self.assertEqual(r.status_code, 413)

    def test_compress_extract_and_archive(self):
        h, d = self.as_("admin-sudo"), self.data
        (d / "pkg").mkdir(); (d / "pkg" / "x.txt").write_text("x")
        z = self.c.post("/api/dev/files/compress", json={"paths": [str(d / "pkg")]}, headers=h).json()
        self.assertTrue(z["path"].endswith("pkg.zip"))
        out = self.c.post("/api/dev/files/extract", json={"path": z["path"]}, headers=h).json()
        self.assertEqual((Path(out["path"]) / "pkg" / "x.txt").read_text(), "x")
        r = self.c.get("/api/dev/files/archive", params={"paths": [str(d / "pkg")]}, headers=h)
        self.assertEqual((r.status_code, r.headers["content-type"]), (200, "application/zip"))
        r = self.c.get("/api/dev/files/raw", params={"path": str(d / "pkg" / "x.txt")}, headers=h)
        self.assertEqual(r.text, "x")
        self.assertIn("default-src 'none'", r.headers["content-security-policy"])

    def test_folder_picker_lists_folder_names_only(self):
        (self.data / "a").mkdir(); (self.data / ".hidden").mkdir(); (self.data / "f.txt").write_text("x")
        got = self.c.get("/api/dev/files/folders", params={"path": str(self.data)}, headers=self.as_("admin-sudo")).json()
        self.assertEqual([f["name"] for f in got["folders"]], ["a"])


class Access(Base):
    def test_every_route_needs_an_administrator(self):
        for who, code in (("", 401), ("member", 403)):
            h = self.as_(who) if who else XRW
            self.assertEqual(self.c.get("/api/dev/files/roots", headers=h).status_code, code)
            self.assertEqual(self.c.get("/api/dev/terminal/sessions", headers=h).status_code, code)
            self.assertEqual(self.c.get("/api/dev/claude-sessions", headers=h).status_code, code)
            self.assertEqual(self.c.put("/api/dev/files/write", json={"path": str(self.data / "x"), "text": "x"}, headers=h).status_code, code)
        self.assertFalse((self.data / "x").exists())

    def test_every_change_needs_sudo(self):
        h, d = self.as_("admin"), str(self.data)
        (self.data / "keep.txt").write_text("x")
        for method, path, kw in (("put", "/api/dev/files/write", {"json": {"path": d + "/x", "text": "x"}}),
                                 ("post", "/api/dev/files/create", {"json": {"path": d + "/y"}}),
                                 ("post", "/api/dev/files/delete", {"json": {"paths": [d + "/keep.txt"]}}),
                                 ("post", "/api/dev/files/move", {"json": {"src": d + "/keep.txt", "dest": d + "/z"}}),
                                 ("post", "/api/dev/files/roots", {"json": {"path": "/"}}),
                                 ("post", "/api/dev/files/upload", {"params": {"folder": d, "name": "u"}, "content": b"x"}),
                                 ("delete", "/api/dev/claude-history/0123456789abcdef", {})):
            r = getattr(self.c, method if method != "delete" else "request")(*(("DELETE", path) if method == "delete" else (path,)), **{"headers": h, **kw})
            self.assertEqual((r.status_code, r.json()["detail"]), (403, "SUDO_REQUIRED"), path)
        self.assertEqual(sorted(p.name for p in self.data.iterdir()), ["keep.txt"])
        self.assertEqual(self.db.logs, [])

    def test_running_commands_needs_sudo(self):
        r = self.c.post("/api/dev/terminal/sessions", json={"cwd": str(self.data)}, headers=self.as_("admin"))
        self.assertEqual((r.status_code, r.json()["detail"]), (403, "SUDO_REQUIRED"))
        self.assertEqual(dev_terminal.list_sessions(), [])

    def test_claude_composer_needs_only_admin(self):
        """Owner, 2026-11-11: prompts and pasted images never bring up the password box; members are still refused."""
        r = self.c.post("/api/dev/uploads", params={"name": "a.png"}, content=b"\x89PNG", headers={**self.as_("admin"), "Content-Type": "image/png"})
        self.assertEqual(r.status_code, 200, r.text)
        for who in ("none", "member"):
            r = self.c.post("/api/dev/uploads", params={"name": "a.png"}, content=b"x", headers={**self.as_(who), "Content-Type": "image/png"})
            self.assertIn(r.status_code, (401, 403), who)
            r = self.c.post("/api/dev/claude", json={"prompt": "hi", "cwd": str(self.data)}, headers=self.as_(who))
            self.assertIn(r.status_code, (401, 403), who)


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class Terminal(Base):
    def open(self):
        r = self.c.post("/api/dev/terminal/sessions", json={"cwd": str(self.data), "cols": 100, "rows": 30}, headers=self.as_("admin-sudo"))
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["id"]

    def read_until(self, ws, needle, limit=10.0):
        got, end = b"", time.time() + limit
        while needle not in got and time.time() < end:
            m = ws.receive()
            if m.get("bytes"): got += m["bytes"]
        return got

    def test_a_shell_runs_commands_and_replays_its_output(self):
        sid = self.open()
        origin = {"origin": "http://testserver", "x-test-user": "admin"}
        with self.c.websocket_connect(f"/api/dev/terminal/sessions/{sid}/ws", headers=origin) as ws:
            self.assertEqual(json.loads(ws.receive_text())["t"], "at")
            ws.send_text(json.dumps({"t": "in", "data": "echo dvp-$((40+2))\r"}))
            self.assertIn(b"dvp-42", self.read_until(ws, b"dvp-42"))
            ws.send_text(json.dumps({"t": "resize", "cols": 80, "rows": 20}))
        with self.c.websocket_connect(f"/api/dev/terminal/sessions/{sid}/ws", headers=origin) as ws:  # the shell kept running
            self.assertEqual(json.loads(ws.receive_text()), {"t": "at", "from": 0})
            self.assertIn(b"dvp-42", ws.receive_bytes())  # the replay
        self.assertEqual(self.c.delete(f"/api/dev/terminal/sessions/{sid}", headers=self.as_("admin")).status_code, 200)
        self.assertEqual([a for a, *_ in self.db.logs], ["dev.terminal_open", "dev.terminal_close"])

    def test_websocket_refuses_other_sites_members_and_unknown_shells(self):
        sid = self.open()
        for headers in ({"origin": "https://evil.example", "x-test-user": "admin"}, {"x-test-user": "admin"},
                        {"origin": "http://testserver", "x-test-user": "member"}, {"origin": "http://testserver"}):
            with self.c.websocket_connect(f"/api/dev/terminal/sessions/{sid}/ws", headers=headers) as ws:
                with self.assertRaises(WebSocketDisconnect) as e: ws.receive_text()
                self.assertEqual(e.exception.code, 4403, headers)
        with self.c.websocket_connect("/api/dev/terminal/sessions/nope/ws", headers={"origin": "http://testserver", "x-test-user": "admin"}) as ws:
            with self.assertRaises(WebSocketDisconnect) as e: ws.receive_text()
            self.assertEqual(e.exception.code, 4404)

    def test_at_most_twelve_shells(self):
        with mock.patch.object(dev_terminal, "MAX_SESSIONS", 1):
            self.open()
            r = self.c.post("/api/dev/terminal/sessions", json={"cwd": str(self.data)}, headers=self.as_("admin-sudo"))
        self.assertEqual(r.status_code, 400)


class Claude(Base):
    def test_stream_json_becomes_display_events(self):
        out = dev_claude.normalise({"type": "assistant", "message": {"content": [
            {"type": "thinking", "thinking": "hmm"}, {"type": "text", "text": "Hello"},
            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}]}})
        self.assertEqual([e["kind"] for e in out], ["thinking", "text", "tool_use"])
        res = dev_claude.normalise({"type": "result", "result": "Done", "num_turns": 2, "total_cost_usd": 0.01, "usage": {"input_tokens": 5, "output_tokens": 7}})
        self.assertEqual(res[0]["kind"], "result")

    def test_a_missing_cli_is_a_503(self):
        with mock.patch.object(dev_claude.shutil, "which", return_value=None):
            r = self.c.post("/api/dev/claude", json={"prompt": "hi", "cwd": str(self.data)}, headers=self.as_("admin-sudo"))
        self.assertEqual(r.status_code, 503)
        self.assertIn("not installed", r.json()["detail"])

    def test_bad_session_ids_and_model_names_are_refused(self):
        with mock.patch.object(dev_claude.shutil, "which", return_value="/bin/true"):
            for body in ({"session_id": "../../etc"}, {"model": "x; rm -rf /"}, {"router_model": "m"}):
                r = self.c.post("/api/dev/claude", json={"prompt": "hi", "cwd": str(self.data), **body}, headers=self.as_("admin-sudo"))
                self.assertEqual(r.status_code, 400, body)

    def test_attachments_are_typed_and_sized(self):
        h = {**self.as_("admin-sudo"), "Content-Type": "image/png"}
        r = self.c.post("/api/dev/uploads", params={"name": "shot.png"}, content=b"\x89PNG", headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        uid = r.json()["id"]
        self.assertEqual(self.c.get(f"/api/dev/uploads/{uid}", headers=self.as_("admin")).content, b"\x89PNG")
        r = self.c.post("/api/dev/uploads", params={"name": "x.exe"}, content=b"MZ", headers={**self.as_("admin-sudo"), "Content-Type": "application/x-msdownload"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.c.get("/api/dev/uploads/../../etc", headers=self.as_("admin")).status_code, 404)


if __name__ == "__main__":
    unittest.main()
