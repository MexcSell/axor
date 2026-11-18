"""cli_accounts.py: people's own Claude Code / Codex logins. Whose plan a call runs on (the request's user, else the run's
owner, else the server's for system work), every login shared (own → server's → a teammate's), per-login gates and
usage-limit clocks, connecting / removing, the Codex device sign-in, and the middleware that tells requests apart.
Against fake `claude` and `codex` scripts."""
import json, os, stat, sys, tempfile, textwrap, threading, time, unittest

from app import agent_core, auth, cli_accounts, codex_cli, llm
from app.auth import AuthDB
from app.llm import LLMError, Providers, QuotaError

# `claude`: `auth status` says loggedIn when a token is set; `-p` logs who it ran as and answers, or fails as the token says
FAKE_CLAUDE = textwrap.dedent(f"""\
    #!{sys.executable}
    import json, os, sys, time
    tok = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
    if sys.argv[1:3] == ["auth", "status"]:
        print(json.dumps({{"loggedIn": bool(tok) or os.environ.get("FAKE_SERVER_LOGIN") == "1"}})); sys.exit(0)
    if sys.argv[1:2] == ["setup-token"]:  # the sign-in: a link, then the code typed into its terminal, then the token
        assert sys.stdin.isatty() and not tok and os.environ.get("CLAUDE_CONFIG_DIR")
        print("\\x1b[1mBrowser didn't open? Use the url below\\x1b[0m\\r\\n", flush=True)
        print("https://claude.com/cai/oauth/authorize?code=true&client_id=x&state=abc\\r\\n\\r\\nPaste code here if prompted > ", flush=True)
        code = sys.stdin.readline().strip()
        if os.environ.get("FAKE_SILENT"): time.sleep(30)
        if code != "goodcode#abc": print("OAuth error: Request failed with status code 400 Press Enter to retry.", flush=True); sys.stdin.readline(); sys.exit(1)
        print("\\x1b[32mYour OAuth token (valid for 1 year):\\x1b[0m\\r\\n\\r\\nsk-ant-oat01-" + "s" * 40 + "\\r\\n\\r\\nStore this token securely.", flush=True)
        sys.exit(0)
    sys.stdin.read()
    with open(os.environ["FAKE_LOG"], "a") as f:
        f.write(json.dumps({{"cli": "claude", "token": tok, "config": os.environ.get("CLAUDE_CONFIG_DIR", "")}}) + "\\n")
    if "limit" in tok: print(json.dumps({{"is_error": True, "result": "You've hit your limit · resets 3pm"}})); sys.exit(0)
    if "bad" in tok: print(json.dumps({{"is_error": True, "result": "Failed to authenticate. API Error: 401 OAuth access token is invalid."}})); sys.exit(0)
    print(json.dumps({{"is_error": False, "result": "OK", "structured_output": {{"text": "hi", "tool_calls": []}},
                      "usage": {{"input_tokens": 10, "output_tokens": 2}}}}))
    """)

# `codex`: signed in when $CODEX_HOME/auth.json exists; the device sign-in prints a link and code, then finishes once
# the test drops an "approve" file; `exec` logs its CODEX_HOME and answers (or hits the usage limit)
FAKE_CODEX = textwrap.dedent(f"""\
    #!{sys.executable}
    import json, os, sys, time
    home = os.environ.get("CODEX_HOME", "")
    a = sys.argv[1:]
    if a[:2] == ["login", "status"]:
        ok = os.path.exists(os.path.join(home, "auth.json")); print("Logged in using ChatGPT" if ok else "Not logged in"); sys.exit(0 if ok else 1)
    if a[:2] == ["login", "--device-auth"]:
        print("\\x1b[1mFollow these steps\\x1b[0m", flush=True)
        print("   \\x1b[94mhttps://auth.openai.com/codex/device\\x1b[0m", flush=True)
        print("2. Enter this one-time code \\x1b[90m(expires in 15 minutes)\\x1b[0m", flush=True)
        time.sleep(float(os.environ.get("FAKE_CODE_DELAY", "0")))
        print("   \\x1b[94mABCD-12345\\x1b[0m", flush=True)
        for _ in range(200):
            if os.path.exists(os.path.join(home, "approve")):
                open(os.path.join(home, "auth.json"), "w").write("{{}}"); print("Successfully logged in", flush=True); sys.exit(0)
            time.sleep(.05)
        sys.exit(1)
    if a[:1] == ["logout"]:
        try: os.remove(os.path.join(home, "auth.json"))
        except OSError: pass
        sys.exit(0)
    sys.stdin.read()
    with open(os.environ["FAKE_LOG"], "a") as f: f.write(json.dumps({{"cli": "codex", "home": home}}) + "\\n")
    if os.path.exists(os.path.join(home, "limit")):
        print(json.dumps({{"type": "turn.failed", "error": {{"message": "You've hit your usage limit. Try again at 3:45 PM."}}}})); sys.exit(1)
    print(json.dumps({{"type": "item.completed", "item": {{"type": "agent_message", "text": "{{\\"text\\": \\"hi\\", \\"tool_calls\\": []}}"}}}}))
    print(json.dumps({{"type": "turn.completed", "usage": {{"input_tokens": 10, "output_tokens": 2}}}}))
    """)

TOKEN = "sk-ant-oat01-" + "a" * 40


class Base(unittest.TestCase):
    def setUp(self):
        self._threads0 = set(threading.enumerate())  # tearDown waits for the sign-in followers this test starts (they write to a.db)
        self.dir = tempfile.TemporaryDirectory()
        d = self.dir.name
        for name, body in (("claude", FAKE_CLAUDE), ("codex", FAKE_CODEX)):
            path = os.path.join(d, name)
            with open(path, "w") as f: f.write(body)
            os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
        self.log = os.path.join(d, "log.jsonl")
        self.saved = {k: os.environ.get(k) for k in ("FAKE_LOG", "FAKE_SERVER_LOGIN", "CODEX_HOME", "CLAUDE_CODE_OAUTH_TOKEN", "CLI_ACCOUNTS_DIR")}
        os.environ.update(FAKE_LOG=self.log, FAKE_SERVER_LOGIN="1", CODEX_HOME=os.path.join(d, "server-codex"))
        os.environ.pop("CLAUDE_CODE_OAUTH_TOKEN", None); os.environ.pop("CLI_ACCOUNTS_DIR", None)
        os.makedirs(os.environ["CODEX_HOME"])
        with open(os.path.join(os.environ["CODEX_HOME"], "auth.json"), "w") as f: f.write("{}")
        self.clis = llm.CLAUDE_CLI, codex_cli.CODEX_CLI
        llm.CLAUDE_CLI, codex_cli.CODEX_CLI = os.path.join(d, "claude"), os.path.join(d, "codex")
        self.db = AuthDB(os.path.join(d, "a.db"))
        agent_core.init(self.db)
        cli_accounts.init(self.db, d)
        cli_accounts._users.clear(); cli_accounts._clocks.clear()
        self.db.setting("terminal_enabled", v="1"); self.db.setting("codex_enabled", v="1")
        self.boss, self.alice, self.bob = (self.user(n, r) for n, r in (("boss", "admin"), ("alice", "user"), ("bob", "user")))
        self.llm = Providers(self.db, cli_accounts.S["box"])
        llm._QUOTA["until"] = codex_cli._QUOTA["until"] = 0.0

    def tearDown(self):
        llm.CLAUDE_CLI, codex_cli.CODEX_CLI = self.clis
        llm._QUOTA["until"] = codex_cli._QUOTA["until"] = 0.0
        agent_core._local.run = None
        agent_core._core = None
        for L in list(cli_accounts._logins.values()): cli_accounts._stop(L)
        cli_accounts._logins.clear()
        for L in list(cli_accounts._clogins.values()): cli_accounts._stop_claude(L)
        cli_accounts._clogins.clear()
        # A stopped sign-in's follower thread still writes its closing sign-in event to this test's database: wait for it, and
        # cancel the expiry timers, before the folder goes (otherwise rmtree can race a journal file: "Directory not empty", R-17)
        for t in set(threading.enumerate()) - self._threads0:
            if isinstance(t, threading.Timer): t.cancel()
            elif getattr(t, "_target", None) in (cli_accounts._follow, cli_accounts._follow_claude): t.join(10)
        cli_accounts.S.update(db=None, box=None, root=None)
        for k, v in self.saved.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
        self.dir.cleanup()

    def user(self, name, role):
        return self.db.q("INSERT INTO users (username, pw_hash, role, created) VALUES (?,?,?,?) RETURNING id",
                         (name, "x", role, time.time()), one=True)["id"]

    def calls(self):
        try:
            with open(self.log) as f: return [json.loads(l) for l in f]
        except FileNotFoundError: return []

    def as_run(self, uid):
        agent_core._local.run = {"id": 0, "owner": uid}

    def give_claude(self, uid, token=TOKEN):
        cli_accounts.connect_claude(uid, token)

    def give_codex(self, uid):
        home = cli_accounts._dir(uid, "codex")
        with open(os.path.join(home, "auth.json"), "w") as f: f.write("{}")
        cli_accounts._save(uid, "codex")
        return home


class Picking(Base):
    def test_system_work_and_admins_without_their_own_use_the_servers_login(self):
        self.assertIsNone(cli_accounts.pick("terminal", None).uid)
        self.assertIsNone(cli_accounts.pick("terminal", 0).uid)
        self.assertIsNone(cli_accounts.pick("codex", self.boss).uid)

    def test_a_member_without_their_own_login_uses_the_servers(self):
        self.assertIsNone(cli_accounts.pick("terminal", self.alice).uid)
        self.assertIsNone(cli_accounts.pick("codex", self.alice).uid)
        self.as_run(self.alice)
        call, _ = self.llm.completer("terminal:sonnet")
        call("sys", [], [{"role": "user", "content": "hi"}])
        self.assertEqual(self.calls()[-1]["token"], "")  # the server's login, no personal token

    def test_nothing_connected_anywhere_says_who_can_set_it_up(self):
        self.db.setting("terminal_enabled", v="0")
        with self.assertRaises(LLMError) as e: cli_accounts.pick("terminal", self.alice)
        self.assertIn("Agents → Models", str(e.exception))
        self.assertNotIn("isn't shared", str(e.exception))

    def test_a_disabled_member_is_refused_even_with_a_login(self):
        self.give_claude(self.alice)
        self.db.q("UPDATE users SET disabled=1 WHERE id=?", (self.alice,)); cli_accounts._users.clear()
        with self.assertRaises(LLMError): cli_accounts.pick("terminal", self.alice)

    def test_the_request_user_wins_over_a_run_left_on_the_thread(self):
        self.as_run(self.alice)
        self.assertEqual(cli_accounts.owner(), self.alice)
        mark = cli_accounts._acting.set(self.bob)
        try: self.assertEqual(cli_accounts.owner(), self.bob)
        finally: cli_accounts._acting.reset(mark)
        agent_core._local.run = None
        self.assertEqual(cli_accounts.owner(fallback=7), 7)

    def test_offered_when_only_a_teammate_connected(self):
        self.db.setting("terminal_enabled", v="0")
        self.assertFalse(self.llm.configured("terminal"))
        self.give_claude(self.alice)
        self.assertTrue(self.llm.configured("terminal"))
        self.assertFalse(self.llm.server_configured("terminal"))
        for who in (self.boss, self.bob, None):  # the server's login is off: everyone shares alice's
            a = cli_accounts.pick("terminal", who)
            self.assertEqual((a.uid, a.borrowed), (self.alice, True))
        self.assertFalse(cli_accounts.pick("terminal", self.alice).borrowed)  # her own, as before
        self.as_run(self.bob)
        self.llm.resolve("terminal:sonnet")
        self.assertEqual(cli_accounts.mine(self.bob, "user")["providers"]["terminal"]["uses"], "shared")

    def test_a_website_login_is_shared_while_the_token_login_is_at_its_limit(self):
        self.give_claude(self.alice)
        self.assertIsNone(cli_accounts.pick("terminal", self.bob).uid)  # the token login is on and fine: it runs bob's work
        llm._QUOTA["until"] = time.time() + 600                         # ...until its plan hits the usage limit
        for who in (self.boss, self.bob, None):
            a = cli_accounts.pick("terminal", who)
            self.assertEqual((a.uid, a.borrowed), (self.alice, True))
        self.assertEqual(cli_accounts.mine(self.bob, "user")["providers"]["terminal"]["uses"], "shared")
        self.assertEqual(llm.quota_until("terminal", self.bob), 0.0)    # bob's runs don't wait: alice's plan has room
        self.assertGreater(cli_accounts.server_limit("terminal"), time.time())
        cli_accounts._clock("terminal", self.alice)[1]["until"] = time.time() + 600  # both at their limit: the token login
        self.assertIsNone(cli_accounts.pick("terminal", self.bob).uid)


class Calls(Base):
    def test_claude_runs_on_the_owners_own_token_and_folder(self):
        self.give_claude(self.alice)
        self.as_run(self.alice)
        call, _ = self.llm.completer("terminal:sonnet")
        blocks, stop, n = call("sys", [], [{"role": "user", "content": "hi"}])
        last = self.calls()[-1]
        self.assertEqual(last["token"], TOKEN)
        self.assertTrue(last["config"].endswith(os.path.join(f"u{self.alice}", "claude")))
        self.as_run(None)
        self.llm.structured("terminal:haiku", "s", "p", {"type": "object"})  # system work: the server's login
        self.assertEqual(self.calls()[-1]["token"], "")

    def test_codex_runs_in_the_owners_own_home(self):
        home = self.give_codex(self.bob)
        self.as_run(self.bob)
        call, _ = self.llm.completer("codex:default")
        call("sys", [], [{"role": "user", "content": "hi"}])
        self.assertEqual(self.calls()[-1]["home"], home)
        self.as_run(self.boss)
        call("sys", [], [{"role": "user", "content": "hi"}])
        self.assertEqual(self.calls()[-1]["home"], os.environ["CODEX_HOME"])

    def test_a_usage_limit_holds_only_that_persons_plan(self):
        self.give_claude(self.alice)
        cli_accounts.S["box"].set(cli_accounts._key(self.alice), "sk-ant-oat01-limit" + "a" * 30)
        self.as_run(self.alice)
        call, _ = self.llm.completer("terminal:sonnet")
        with self.assertRaises(QuotaError) as e: call("sys", [], [{"role": "user", "content": "hi"}])
        self.assertNotIn("codex", str(e.exception).lower())
        self.assertGreater(llm.quota_until("terminal", self.alice), time.time())
        self.assertEqual(llm.quota_until("terminal"), 0.0)          # the server's plan
        self.assertEqual(llm.quota_until("terminal", self.boss), 0.0)  # an admin on the server's plan
        home = self.give_codex(self.bob)
        open(os.path.join(home, "limit"), "w").close()
        self.as_run(self.bob)
        call, _ = self.llm.completer("codex:default")
        with self.assertRaises(QuotaError): call("sys", [], [{"role": "user", "content": "hi"}])
        self.assertGreater(llm.quota_until("codex", self.bob), time.time())
        self.assertEqual(codex_cli.quota_until(), 0.0)

    def test_each_login_has_its_own_gate(self):
        self.give_claude(self.alice)
        a = cli_accounts.pick("terminal", self.alice)
        self.assertIsNot(a.gate, llm.CLI_GATE)
        self.assertIs(a.gate, cli_accounts.pick("terminal", self.alice).gate)
        self.assertIs(cli_accounts.pick("terminal", None).gate, llm.CLI_GATE)

    def test_an_expired_token_says_to_reconnect_it(self):
        self.give_claude(self.alice)
        cli_accounts.S["box"].set(cli_accounts._key(self.alice), "sk-ant-oat01-bad" + "a" * 30)
        with self.assertRaises(LLMError) as e: cli_accounts.test(self.alice, "terminal")
        self.assertIn("setup-token", str(e.exception))
        self.assertEqual(self.db.q("SELECT ok FROM cli_accounts WHERE user_id=?", (self.alice,), one=True)["ok"], 0)


class Connecting(Base):
    def test_claude_token_is_checked_then_kept_encrypted(self):
        with self.assertRaises(LLMError): cli_accounts.connect_claude(self.alice, "sk-ant-api03-" + "a" * 40)
        with self.assertRaises(LLMError): cli_accounts.connect_claude(self.alice, "sk-ant-oat01-bad" + "a" * 30)
        self.assertFalse(cli_accounts.connected(self.alice, "terminal"))
        cli_accounts.connect_claude(self.alice, TOKEN)
        self.assertTrue(cli_accounts.connected(self.alice, "terminal"))
        raw = self.db.setting("secret:" + cli_accounts._key(self.alice))
        self.assertNotIn(TOKEN, raw)
        self.assertEqual(cli_accounts.mine(self.alice, "user")["providers"]["terminal"]["uses"], "own")
        self.assertEqual(cli_accounts.mine(self.bob, "user")["providers"]["terminal"]["uses"], "server")

    def test_remove_forgets_token_folder_and_clock(self):
        self.give_claude(self.alice)
        home = self.give_codex(self.alice)
        cli_accounts.remove(self.alice, "terminal"); cli_accounts.remove(self.alice, "codex")
        self.assertIsNone(cli_accounts.S["box"].get(cli_accounts._key(self.alice)))
        self.assertFalse(os.path.exists(home))
        self.assertFalse(cli_accounts.connected(self.alice, "codex"))
        self.assertIsNone(cli_accounts.pick("terminal", self.alice).uid)  # back on the server's login

    def test_deleted_users_logins_are_swept(self):
        self.give_claude(self.bob)
        self.db.q("DELETE FROM users WHERE id=?", (self.bob,))
        cli_accounts.sweep()
        self.assertIsNone(self.db.q("SELECT 1 FROM cli_accounts WHERE user_id=?", (self.bob,), one=True))
        self.assertIsNone(cli_accounts.S["box"].get(cli_accounts._key(self.bob)))

    def test_codex_device_sign_in_from_the_page(self):
        v = cli_accounts.start_login(self.alice)
        self.assertEqual((v["state"], v["url"], v["code"]), ("waiting", "https://auth.openai.com/codex/device", "ABCD-12345"))
        self.assertEqual(cli_accounts.start_login(self.alice)["code"], "ABCD-12345")  # one at a time
        open(os.path.join(cli_accounts._dir(self.alice, "codex"), "approve"), "w").close()
        for _ in range(100):
            if cli_accounts.login_view(self.alice)["state"] != "waiting": break
            time.sleep(.05)
        self.assertEqual(cli_accounts.login_view(self.alice)["state"], "done")
        self.assertTrue(cli_accounts.connected(self.alice, "codex"))

    def _claude_done(self):
        for _ in range(200):
            if cli_accounts.claude_login_view(self.alice)["state"] not in ("waiting", "checking"): break
            time.sleep(.05)
        return cli_accounts.claude_login_view(self.alice)

    def test_claude_sign_in_from_the_page(self):
        v = cli_accounts.start_claude_login(self.alice)
        self.assertEqual((v["state"], v["url"]), ("waiting", "https://claude.com/cai/oauth/authorize?code=true&client_id=x&state=abc"))
        self.assertEqual(cli_accounts.start_claude_login(self.alice)["url"], v["url"])  # one at a time
        self.assertEqual(cli_accounts.mine(self.alice, "member")["providers"]["terminal"]["login"]["state"], "waiting")
        with self.assertRaises(LLMError): cli_accounts.claude_login_code(self.alice, "no")
        self.assertFalse(cli_accounts.connected(self.alice, "terminal"))
        cli_accounts.claude_login_code(self.alice, " goodcode#abc ")
        self.assertEqual(self._claude_done()["state"], "done")
        self.assertTrue(cli_accounts.connected(self.alice, "terminal"))
        a = cli_accounts.personal("terminal", self.alice)  # the token the CLI printed, saved for this person only
        self.assertEqual(a.env["CLAUDE_CODE_OAUTH_TOKEN"], "sk-ant-oat01-" + "s" * 40)
        self.assertNotIn("sk-ant", json.dumps(cli_accounts.mine(self.alice, "member")))

    def test_claude_sign_in_with_a_wrong_code_saves_nothing(self):
        cli_accounts.start_claude_login(self.alice)
        cli_accounts.claude_login_code(self.alice, "wrongcode#abc")
        v = self._claude_done()
        self.assertEqual(v["state"], "failed"); self.assertIn("didn't accept that code", v["error"])
        self.assertFalse(cli_accounts.connected(self.alice, "terminal"))
        with self.assertRaises(LLMError): cli_accounts.claude_login_code(self.alice, "goodcode#abc")  # closed: start again
        cli_accounts.start_claude_login(self.alice)
        was, cli_accounts.CODE_WAIT = cli_accounts.CODE_WAIT, .3  # a CLI that says nothing after the code: the page isn't left waiting
        try:
            os.environ["FAKE_SILENT"] = "1"
            cli_accounts.cancel_claude_login(self.alice); cli_accounts.start_claude_login(self.alice)
            cli_accounts.claude_login_code(self.alice, "goodcode#abc")
            v = self._claude_done()
            self.assertEqual(v["state"], "failed"); self.assertIn("didn't answer", v["error"])
        finally:
            cli_accounts.CODE_WAIT = was; os.environ.pop("FAKE_SILENT", None)
        cli_accounts.start_claude_login(self.alice); cli_accounts.cancel_claude_login(self.alice)
        self.assertIsNone(cli_accounts.claude_login_view(self.alice))

    def test_a_slow_code_is_waited_for_not_killed(self):
        os.environ["FAKE_CODE_DELAY"] = "6"
        try: v = cli_accounts.start_login(self.alice)
        finally: os.environ.pop("FAKE_CODE_DELAY", None)
        self.assertEqual((v["state"], v["code"]), ("starting", None))
        for _ in range(100):
            if cli_accounts.login_view(self.alice)["code"]: break
            time.sleep(.05)
        self.assertEqual(cli_accounts.login_view(self.alice)["state"], "waiting")
        self.assertEqual(cli_accounts.login_view(self.alice)["code"], "ABCD-12345")

    def test_codex_sign_in_can_be_cancelled(self):
        cli_accounts.start_login(self.bob)
        cli_accounts.cancel_login(self.bob)
        self.assertIsNone(cli_accounts.login_view(self.bob))
        self.assertFalse(cli_accounts.connected(self.bob, "codex"))


try:
    from fastapi import FastAPI
    from fastapi.responses import StreamingResponse
    from fastapi.testclient import TestClient
except Exception:  # noqa: BLE001 - no httpx in this environment
    TestClient = None


@unittest.skipUnless(TestClient, "fastapi.testclient needs httpx")
class Middleware(Base):
    def test_requests_know_their_user_plain_and_streaming(self):
        app = FastAPI()
        @app.get("/api/who")
        def who(): return {"uid": cli_accounts.owner()}
        @app.get("/api/stream")
        def stream(): return StreamingResponse(iter([json.dumps({"uid": cli_accounts.owner()})]))
        ident = lambda u: u
        cli_accounts.install(app, self.db, self.dir.name, lambda req: None, {"admin": ident, "sudo": ident}, lambda req: "")
        now = time.time()
        self.db.q("INSERT INTO sessions (hash, user_id, stage, created, last_seen, expires) VALUES (?,?,?,?,?,?)",
                  (auth._h("tok-a"), self.alice, "full", now, now, now + 3600))
        c = TestClient(app)
        self.assertEqual(c.get("/api/who").json(), {"uid": None})
        c.cookies.set(auth.COOKIE, "tok-a")
        self.assertEqual(c.get("/api/who").json(), {"uid": self.alice})
        self.assertEqual(c.get("/api/stream").json(), {"uid": self.alice})
        self.assertIsNone(cli_accounts._acting.get())


if __name__ == "__main__":
    unittest.main()
