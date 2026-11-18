"""model_switch.py: the on/off switch on each card in Agents → Models. A switched-off model stays connected, but nothing
runs on it: the server's login, a named login, a person's own login, or an API provider."""
import os, unittest

from app import cli_accounts, llm, model_switch
from app.llm import LLMError

from test_cli_accounts import Base


class Store(Base):
    def test_switching_round_trip_and_a_broken_value(self):
        self.assertFalse(model_switch.off(self.db, "openai"))
        model_switch.switch(self.db, "openai", False); model_switch.switch(self.db, "codex", False)
        self.assertTrue(model_switch.off(self.db, "openai"))
        model_switch.switch(self.db, "openai", True)
        self.assertFalse(model_switch.off(self.db, "openai")); self.assertTrue(model_switch.off(self.db, "codex"))
        self.db.setting(model_switch.SETTING, v="not json")
        self.assertFalse(model_switch.off(self.db, "codex"))  # a broken value turns nothing off
        self.assertFalse(model_switch.off(None, "codex"))


class ServerLogin(Base):
    def test_off_server_login_is_not_used_and_says_so(self):
        model_switch.switch(self.db, "codex", False)
        self.assertTrue(self.llm.server_configured("codex"))  # still connected: its card stays
        self.assertFalse(self.llm.configured("codex"))
        with self.assertRaises(LLMError) as e: cli_accounts.pick("codex", self.alice)
        self.assertIn("switched off", str(e.exception))
        with self.assertRaises(LLMError) as e: self.llm.resolve("codex:gpt-5")
        self.assertIn("switched off", str(e.exception))
        model_switch.switch(self.db, "codex", True)
        self.assertIsNone(cli_accounts.pick("codex", self.alice).uid)

    def test_off_server_login_leaves_peoples_own_logins_working(self):
        self.give_codex(self.alice)
        model_switch.switch(self.db, "codex", False)
        self.assertTrue(self.llm.configured("codex"))
        self.assertEqual(cli_accounts.pick("codex", self.alice).uid, self.alice)
        a = cli_accounts.pick("codex", self.bob)  # the server's is off: a teammate's shared one
        self.assertEqual(a.uid, self.alice); self.assertTrue(a.borrowed)


class OwnLogin(Base):
    def test_off_own_login_is_skipped_for_its_owner_and_teammates(self):
        self.give_codex(self.alice)
        model_switch.switch(self.db, model_switch.own_key(self.alice, "codex"), False)
        self.assertIsNone(cli_accounts.pick("codex", self.alice).uid)  # the server's login instead
        self.assertTrue(cli_accounts.mine(self.alice, "user")["providers"]["codex"]["off"])
        model_switch.switch(self.db, "codex", False)  # and with the server's off too: nothing left
        self.assertFalse(cli_accounts.any_connected("codex"))
        self.assertFalse(self.llm.configured("codex"))
        with self.assertRaises(LLMError) as e: cli_accounts.pick("codex", self.alice)
        self.assertIn("switched off", str(e.exception))
        with self.assertRaises(LLMError): cli_accounts.pick("codex", self.bob)
        model_switch.switch(self.db, model_switch.own_key(self.alice, "codex"), True)
        self.assertEqual(cli_accounts.pick("codex", self.bob).uid, self.alice)


class Removing(Base):
    def test_removing_a_switched_off_login_or_model_forgets_the_switch(self):
        self.give_codex(self.alice)
        model_switch.switch(self.db, model_switch.own_key(self.alice, "codex"), False)
        cli_accounts.remove(self.alice, "codex")
        self.give_codex(self.alice)  # signed in again: on
        self.assertEqual(cli_accounts.pick("codex", self.alice).uid, self.alice)
        self.assertEqual(cli_accounts.mine(self.alice, "user")["providers"]["codex"]["uses"], "own")
        model_switch.switch(self.db, model_switch.own_key(self.alice, "codex"), False)
        self.assertEqual(cli_accounts.mine(self.alice, "user")["providers"]["codex"]["uses"], "server")  # follows pick()

    def test_a_switched_off_error_counts_as_not_run(self):
        from app import agent_core
        self.assertTrue(agent_core._no_use(LLMError("Codex is switched off in Agents → Models. Pick another model, or turn it on there.")))


class ApiProvider(Base):
    def test_off_api_provider_leaves_the_catalog_and_is_refused(self):
        self.llm.openai_key = lambda: "sk-test"
        self.llm.list_models = lambda p, key=None, url=None: [{"id": "gpt-x", "label": "GPT X"}]
        self.assertTrue(self.llm.configured("openai"))
        model_switch.switch(self.db, "openai", False)
        self.llm.forget()
        entry = next(e for e in self.llm.catalog() if e["id"] == "openai")
        self.assertFalse(entry["configured"]); self.assertEqual(entry["models"], [])
        with self.assertRaises(LLMError) as e: self.llm.resolve("openai:gpt-x")
        self.assertIn("switched off", str(e.exception))
        model_switch.switch(self.db, "openai", True)
        self.assertEqual(self.llm.resolve("openai:gpt-x"), ("openai", "gpt-x"))


class NamedLogin(Base):
    def setUp(self):
        super().setUp()
        self.var = llm.TERMINAL_LOGINS["claude-37"][1]
        self.was = os.environ.get(self.var)
        os.environ[self.var] = "sk-ant-oat01-" + "n" * 40

    def tearDown(self):
        if self.was is None: os.environ.pop(self.var, None)
        else: os.environ[self.var] = self.was
        super().tearDown()

    def test_off_named_login_leaves_the_menu_and_is_refused(self):
        self.assertIn("claude-37", dict(llm.terminal_logins()))
        model_switch.switch(self.db, "login:claude-37", False)
        self.assertNotIn("claude-37", dict(llm.terminal_logins()))
        with self.assertRaises(LLMError) as e: cli_accounts.pick("terminal", self.alice, "claude-37")
        self.assertIn("switched off", str(e.exception))
        with self.assertRaises(LLMError): self.llm.resolve("terminal:claude-37")
        self.assertIsNone(cli_accounts.pick("terminal", self.alice, "sonnet").uid)  # the server's login is untouched


if __name__ == "__main__":
    unittest.main()
