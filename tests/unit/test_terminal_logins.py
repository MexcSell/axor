"""llm.TERMINAL_LOGINS: named server logins offered as their own Terminal models (Claude-37 on CLAUDE_CODE_OAUTH_TOKEN1).
Offered only while the token is set, runs on that token in its own folder with its own gate and usage-limit clock, passes
its CLI alias as --model, and is shared with everyone. Against test_cli_accounts' fake `claude`."""
import json, os, time, unittest

from app import cli_accounts, llm
from app.llm import LLMError, QuotaError

import test_cli_accounts as T

TOK1 = "sk-ant-oat01-" + "b" * 40
VAR = llm.TERMINAL_LOGINS["claude-37"][1]


class LoginBase(T.Base):
    def setUp(self):
        super().setUp()
        self.saved_var = os.environ.get(VAR)
        os.environ[VAR] = TOK1
        with open(llm.CLAUDE_CLI, "w") as f:  # the same fake, also logging its arguments
            f.write(T.FAKE_CLAUDE.replace('"config": os.environ.get("CLAUDE_CONFIG_DIR", "")',
                                          '"config": os.environ.get("CLAUDE_CONFIG_DIR", ""), "argv": sys.argv[1:]'))

    def tearDown(self):
        if self.saved_var is None: os.environ.pop(VAR, None)
        else: os.environ[VAR] = self.saved_var
        super().tearDown()

    def model_arg(self):
        a = self.calls()[-1]["argv"]
        return a[a.index("--model") + 1]


class NamedLogins(LoginBase):
    def test_offered_while_the_token_is_set(self):
        ids = [m["id"] for e in self.llm.catalog(refresh=True) if e["id"] == "terminal" for m in e["models"]]
        self.assertIn("terminal:claude-37", ids)
        self.assertIn("terminal:opus", ids)
        label = next(m["label"] for e in self.llm.catalog() if e["id"] == "terminal" for m in e["models"] if m["model"] == "claude-37")
        self.assertEqual(label, "Claude-37")
        os.environ.pop(VAR)
        ids = [m["id"] for e in self.llm.catalog(refresh=True) if e["id"] == "terminal" for m in e["models"]]
        self.assertNotIn("terminal:claude-37", ids)

    def test_offered_on_its_own_when_terminal_is_off(self):
        self.db.setting("terminal_enabled", v="0")
        self.assertTrue(self.llm.configured("terminal"))
        ids = [m["model"] for e in self.llm.catalog(refresh=True) if e["id"] == "terminal" for m in e["models"]]
        self.assertEqual(ids, ["claude-37"])

    def test_runs_on_token1_in_its_own_folder_with_its_alias(self):
        for who in (None, self.boss):
            self.as_run(who)
            call, label = self.llm.completer("terminal:claude-37")
            self.assertEqual(label, "terminal:claude-37")
            call("sys", [], [{"role": "user", "content": "hi"}])
            last = self.calls()[-1]
            self.assertEqual(last["token"], TOK1)
            self.assertTrue(last["config"].endswith(os.path.join("login-claude-37", "claude")))
            self.assertEqual(self.model_arg(), "opus")
            self.llm.structured("terminal:claude-37", "s", "p", {"type": "object"})
            self.assertEqual(self.calls()[-1]["token"], TOK1)
            self.assertEqual(self.model_arg(), "opus")
        self.as_run(None)
        self.llm.structured("terminal:opus", "s", "p", {"type": "object"})  # the other models: the server's login, as before
        self.assertEqual(self.calls()[-1]["token"], "")

    def test_members_share_it_too(self):
        self.give_claude(self.alice)
        self.as_run(self.alice)
        self.llm.resolve("terminal:claude-37")
        self.assertEqual(cli_accounts.pick("terminal", self.alice, "claude-37").var, "CLAUDE_CODE_OAUTH_TOKEN1")
        self.llm.resolve("terminal:opus")  # their own login still works

    def test_own_gate_and_usage_clock(self):
        a = cli_accounts.pick("terminal", None, "claude-37")
        self.assertIsNot(a.gate, llm.CLI_GATE)
        self.assertIs(a.gate, cli_accounts.pick("terminal", self.boss, "claude-37").gate)
        os.environ[VAR] = "sk-ant-oat01-limit" + "b" * 30
        self.as_run(None)
        call, _ = self.llm.completer("terminal:claude-37")
        with self.assertRaises(QuotaError) as e: call("sys", [], [{"role": "user", "content": "hi"}])
        self.assertIn("Claude-37", str(e.exception))
        self.assertGreater(a.quota["until"], time.time())
        self.assertEqual(llm.quota_until("terminal"), 0.0)  # the server's plan isn't held

    def test_a_rejected_or_missing_token_names_its_variable(self):
        os.environ[VAR] = "sk-ant-oat01-bad" + "b" * 30
        call, _ = self.llm.completer("terminal:claude-37")
        with self.assertRaises(LLMError) as e: call("sys", [], [{"role": "user", "content": "hi"}])
        self.assertIn(VAR, str(e.exception))
        os.environ.pop(VAR)
        with self.assertRaises(LLMError) as e: cli_accounts.pick("terminal", None, "claude-37")
        self.assertIn(VAR, str(e.exception))


class ModelsCard(LoginBase):
    """Agents → Models: Claude-37's own card (GET /api/agents/settings "logins"), its Test (one tiny prompt on TOKEN1)
    and its plan usage read with TOKEN1, not the server's login."""
    def setUp(self):
        super().setUp()
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app import agents
        me = lambda req: {"username": "root", "role": "admin"}
        app = FastAPI()
        app.include_router(agents.build(self.db, {"admin": me, "sudo": me, "ops": None}, lambda req: "127.0.0.1", self.dir.name))
        self.c = TestClient(app)

    def card(self):
        return next(l for l in self.c.get("/api/agents/settings").json()["logins"] if l["id"] == "claude-37")

    def press_test(self):
        return self.c.post("/api/agents/settings/login/claude-37/test")

    def test_listed_with_its_variable_and_not_checked_until_tested(self):
        c = self.card()
        self.assertEqual((c["label"], c["var"], c["model"], c["configured"], c["check"]), ("Claude-37", VAR, "terminal:claude-37", True, None))
        self.assertNotIn(TOK1, json.dumps(c))  # masked only
        r = self.press_test()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.calls()[-1]["token"], TOK1)  # the check ran on TOKEN1
        self.assertEqual(self.card()["check"]["kind"], "ok")

    def test_refused_and_limited_tokens_colour_the_card(self):
        os.environ[VAR] = "sk-ant-oat01-bad" + "b" * 30
        self.press_test()
        c = self.card()
        self.assertEqual(c["check"]["kind"], "error")
        self.assertIn("401", c["check"]["error"])
        os.environ[VAR] = "sk-ant-oat01-limit" + "b" * 30
        self.assertEqual(self.card()["check"], None)  # another token: the old result isn't its
        self.press_test()
        self.assertEqual(self.card()["check"]["kind"], "limit")

    def test_without_its_token(self):
        os.environ.pop(VAR)
        self.assertEqual(self.c.get("/api/agents/settings").json()["logins"], [])  # no card, like a model that isn't connected
        r = self.press_test()
        self.assertEqual(r.status_code, 400)
        self.assertIn(VAR, r.json()["detail"])
        self.assertEqual(self.c.post("/api/agents/settings/login/nope/test").status_code, 404)

    def test_usage_reads_token1s_plan(self):
        from app import plan_usage
        seen, was = [], plan_usage._get
        plan_usage._get = lambda url, headers, timeout=15: seen.append(headers["Authorization"]) or {"limits": []}
        try:
            u = self.c.get("/api/agents/settings/usage/terminal:claude-37?fresh=1").json()
            self.assertNotIn("error", {k for k, v in u.items() if v})
            self.assertEqual(seen, [f"Bearer {TOK1}"])
            self.assertEqual(self.c.get("/api/agents/settings/usage/terminal:nope").status_code, 404)
        finally:
            plan_usage._get = was
        plan_usage._probed.clear()
        plan_usage._probed["terminal:claude-37"] = {"checked_at": time.time()}
        self.assertIsNone(plan_usage.last_probe())  # the server's login doesn't show Claude-37's short-prompt reading
        self.assertIsNotNone(plan_usage.last_probe("terminal:claude-37"))
        plan_usage._probed.clear()


if __name__ == "__main__":
    unittest.main()
