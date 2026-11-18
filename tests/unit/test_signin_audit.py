"""Sign-in audit and per-run login attribution (Owner decision 2026-11-11, D-019).

- Every step of a sign-in attempt is an audit row ("agent.cli_signin"): provider, flow, stage, attempt id, a fixed reason code.
  No row and no log line ever holds the token, the device code, the sign-in link or the code typed in: checked here with the
  fake CLIs' own values as sentinels, across the Codex device flow, the Claude setup-token flow and a pasted token.
- Each ledger run records the login its model calls ran on (ac_runs.login / login_kind), where the account is handed to the CLI."""
import logging, os, sys, time, unittest

from app import agent_core, cli_accounts, llm, secretbox
from app.llm import LLMError

sys.path.insert(0, os.path.dirname(__file__))
from test_cli_accounts import TOKEN, Base  # noqa: E402

# what the fake CLIs print or take: none of it may reach the audit or the logs
SENTINELS = ("ABCD-12345", "auth.openai.com", "goodcode", "wrongcode", "oauth/authorize", "state=abc", "sk-ant", "s" * 40, "a" * 40)


class Capture(logging.Handler):
    def __init__(self): super().__init__(logging.DEBUG); self.lines = []
    def emit(self, record): self.lines.append(self.format(record))


class Audit(Base):
    def setUp(self):
        super().setUp()
        self.cap = Capture()
        logging.getLogger().addHandler(self.cap)
        self.level = logging.getLogger().level
        logging.getLogger().setLevel(logging.DEBUG)

    def tearDown(self):
        logging.getLogger().removeHandler(self.cap)
        logging.getLogger().setLevel(self.level)
        super().tearDown()

    def rows(self): return self.db.q("SELECT * FROM audit WHERE action='agent.cli_signin' ORDER BY id")
    def stages(self): return [r["detail"].split(" attempt=")[0].split(" reason=")[0] for r in self.rows()]

    def assert_clean(self):
        blob = "\n".join(" ".join(str(v) for v in r.values()) for r in self.db.q("SELECT * FROM audit")) + "\n".join(self.cap.lines)
        for s in SENTINELS: self.assertNotIn(s, blob, s)

    def wait(self, view, uid, states=("waiting", "checking", "starting")):
        for _ in range(200):
            v = view(uid)
            if not v or v["state"] not in states: return v
            time.sleep(.05)
        return view(uid)

    def test_codex_device_flow_lifecycle(self):
        cli_accounts.start_login(self.alice, "10.0.0.7")
        cli_accounts.start_login(self.alice)                                            # the same attempt shown again: no new row
        open(os.path.join(cli_accounts._dir(self.alice, "codex"), "approve"), "w").close()
        self.assertEqual(self.wait(cli_accounts.login_view, self.alice)["state"], "done")
        self.assertEqual(self.stages(), ["codex device started", "codex device code_shown", "codex device connected"])
        r = self.rows()
        self.assertEqual(len({x["detail"].split("attempt=")[1].split()[0] for x in r}), 1)   # one attempt id ties them
        self.assertEqual((r[0]["actor"], r[0]["target"], r[0]["ip"]), ("alice", str(self.alice), "10.0.0.7"))
        self.assert_clean()

    def test_codex_cancel_and_expire(self):
        cli_accounts.start_login(self.bob); cli_accounts.cancel_login(self.bob, "10.0.0.8")
        cli_accounts.start_login(self.bob)
        cli_accounts._expire(cli_accounts._logins[self.bob])
        self.assertEqual(self.stages(), ["codex device started", "codex device code_shown", "codex device cancelled",
                                         "codex device started", "codex device code_shown", "codex device expired"])
        self.assert_clean()

    def test_claude_setup_token_flow_lifecycle_and_failures(self):
        cli_accounts.start_claude_login(self.alice)
        cli_accounts.claude_login_code(self.alice, "goodcode#abc")
        self.assertEqual(self.wait(cli_accounts.claude_login_view, self.alice)["state"], "done")
        cli_accounts.start_claude_login(self.bob)
        cli_accounts.claude_login_code(self.bob, "wrongcode#abc")
        self.assertEqual(self.wait(cli_accounts.claude_login_view, self.bob)["state"], "failed")
        st = self.stages()
        self.assertEqual(st[:4], ["terminal setup_token started", "terminal setup_token link_shown", "terminal setup_token code_submitted",
                                  "terminal setup_token connected"])
        self.assertIn("terminal setup_token failed", st[4:])
        self.assertTrue(any("reason=code_rejected" in r["detail"] for r in self.rows()))
        self.assert_clean()

    def test_a_pasted_token_and_a_check(self):
        try: cli_accounts.connect_claude(self.alice, "sk-ant-oat01-bad" + "a" * 40)
        except LLMError: pass
        cli_accounts.signin_event(self.alice, "terminal", "token", "failed", "x1", "token_check_failed")
        cli_accounts.signin_event(self.alice, "terminal", "token", "failed", "x2", "a reason that isn't a code")  # refused: not written
        cli_accounts.signin_event(self.alice, "terminal", "token", "leaked " + TOKEN)                            # refused: not a stage
        self.assertEqual(self.stages(), ["terminal token failed"])
        self.assert_clean()

    def test_audit_names_a_key_by_a_fingerprint_only(self):
        f = secretbox.fingerprint(TOKEN)
        self.assertTrue(f.startswith("sha256:") and len(f) == 19)
        for i in range(0, len(TOKEN) - 3): self.assertNotIn(TOKEN[i:i + 4], f.removeprefix("sha256:")) if TOKEN[i:i + 4] != "aaaa" else None
        self.assertNotEqual(f, secretbox.fingerprint(TOKEN + "b"))


class Attribution(Base):
    def run_row(self, rid): return self.db.q("SELECT login, login_kind FROM ac_runs WHERE id=?", (rid,), one=True)

    def test_a_run_records_the_login_its_calls_ran_on(self):
        self.give_claude(self.alice)
        rid = agent_core.begin("teams", self.alice, "task", ref="mw:1")
        call, _ = self.llm.completer("terminal:sonnet")
        call("sys", [], [{"role": "user", "content": "hi"}])
        call("sys", [], [{"role": "user", "content": "again"}])                          # the same login: recorded once
        self.assertEqual(self.run_row(rid), {"login": f"user:{self.alice}:terminal", "login_kind": "own"})
        agent_core.end("done")

    def test_system_work_on_the_servers_login_and_a_run_that_used_two(self):
        rid = agent_core.begin("teams", 0, "task", ref="mw:2")
        self.llm.structured("terminal:haiku", "s", "p", {"type": "object"})
        self.assertEqual(self.run_row(rid), {"login": "server:terminal", "login_kind": "server"})
        call, _ = self.llm.completer("codex:default")
        call("sys", [], [{"role": "user", "content": "hi"}])
        self.assertEqual(self.run_row(rid), {"login": "server:terminal,server:codex", "login_kind": "mixed"})
        agent_core.end("done")

    def test_checks_that_run_nothing_record_nothing(self):
        rid = agent_core.begin("teams", self.boss, "task", ref="mw:3")
        cli_accounts.pick("terminal", self.boss); cli_accounts.peek("terminal", self.boss); self.llm.resolve("terminal:sonnet")
        self.assertEqual(self.run_row(rid), {"login": None, "login_kind": None})
        agent_core.end("done")

    def test_api_key_providers_are_named_too(self):
        rid = agent_core.begin("teams", self.boss, "task", ref="mw:4")
        llm._attribute_api("anthropic"); llm._attribute_api("terminal")
        self.assertEqual(self.run_row(rid), {"login": "api:anthropic", "login_kind": "api"})
        agent_core.end("done")


if __name__ == "__main__":
    unittest.main()


class Redaction(unittest.TestCase):
    """app/audit_redact.py: finds key fragments only in the actions that wrote them, never prints one, keeps no copy."""
    def test_dry_run_apply_and_its_own_output(self):
        import io, tempfile
        from contextlib import redirect_stdout
        from unittest import mock
        from app import audit_redact as ar
        from app.auth import AuthDB
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        db = AuthDB(os.path.join(d.name, "a.db"))
        key = "sk-ant-oat01-" + "Q" * 30 + "ZZ9x"
        frag = secretbox.mask(key)
        db.log("agent.provider_set", "boss", "", "1.2.3.4", f"terminal {frag}")
        db.log("connector.openrouter_connect", "boss", "", "", f"sk-or-v1-abc…wxyz (3 keys)")
        db.log("mining.miner", "boss", "", "", "hotkey 5ChiqfuT…BbXh")                    # a shortened hotkey: not a key, left alone
        db.log("agent.provider_set", "boss", "", "", "openai sha256:0123456789ab")           # already a fingerprint
        run = lambda *a: (lambda b: (mock.patch.object(ar, "open_db", lambda: db).__enter__(), redirect_stdout(b).__enter__(), ar.main(list(a)), b.getvalue())[-1])(io.StringIO())
        out = run()
        self.assertIn("audit rows with a key fragment: 2", out)
        for s in (frag, "sk-or-v1-abc", "wxyz", "ZZ9x"): self.assertNotIn(s, out)          # ids and counts only
        self.assertTrue(db.q("SELECT 1 FROM audit WHERE detail LIKE ?", (f"%{frag}%",), one=True))  # dry run wrote nothing
        out = run("--apply")
        self.assertIn("redacted: 2 rows; left: 0", out)
        blob = " ".join(r["detail"] for r in db.q("SELECT detail FROM audit"))
        for s in (frag, "sk-or-v1-abc…wxyz"): self.assertNotIn(s, blob)
        self.assertIn("5ChiqfuT…BbXh", blob)
        self.assertEqual(db.q("SELECT name FROM sqlite_master WHERE name LIKE '%redact%'"), [])  # no journal of old values
