"""codex_cli.py and the Codex provider in llm.py: `codex exec --json` output, failures (usage limit, sign-in, strict-schema
fallback), the flags that keep the CLI's own tools off, and tool calls written as text. Against a fake `codex` script."""
import json, os, stat, sys, tempfile, textwrap, time, unittest
from unittest import mock

from app import codex_cli, llm
from app.auth import AuthDB
from app.llm import LLMError, Providers, QuotaError
from app.mining_autoloop import classify

# A stand-in for `codex`: answers `login status`, and for `exec` appends its argv, env and stdin to $FAKE_CODEX_LOG
# and prints the next scripted JSONL output from $FAKE_CODEX_SCRIPT (a JSON list; each item is a list of events,
# or {"stderr": ...}).
FAKE = textwrap.dedent(f"""\
    #!{sys.executable}
    import json, os, sys
    if sys.argv[1:3] == ["login", "status"]:
        print(os.environ.get("FAKE_CODEX_LOGIN", "Logged in using ChatGPT")); sys.exit(0 if "Logged in" in os.environ.get("FAKE_CODEX_LOGIN", "Logged in") else 1)
    log = os.environ["FAKE_CODEX_LOG"]
    calls = json.load(open(log)) if os.path.exists(log) else []
    stdin = sys.stdin.read()
    sysfile = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("model_instructions_file=")), None)
    calls.append({{"argv": sys.argv[1:], "stdin": stdin, "system": open(json.loads(sysfile)).read() if sysfile else None,
                   "env": sorted(k for k in os.environ if "OPENAI" in k or "CODEX" in k)}})
    json.dump(calls, open(log, "w"))
    script = json.load(open(os.environ["FAKE_CODEX_SCRIPT"]))
    out = script[min(len(calls), len(script)) - 1]
    if isinstance(out, dict): sys.stderr.write(out["stderr"]); sys.exit(1)
    for e in out: print(json.dumps(e))
    """)

CODE_MODE = {"type": "item.completed", "item": {"id": "item_0", "type": "error", "message": "Code Mode is unavailable because code-mode host is disabled."}}
def msg(text): return {"type": "item.completed", "item": {"type": "agent_message", "text": text if isinstance(text, str) else json.dumps(text)}}
def done(i=100, o=20): return {"type": "turn.completed", "usage": {"input_tokens": i, "cached_input_tokens": 50, "output_tokens": o, "reasoning_output_tokens": 5}}
def failed(m): return {"type": "turn.failed", "error": {"message": m}}
def ok(*texts, i=100, o=20): return [{"type": "thread.started"}, CODE_MODE, {"type": "turn.started"}, *map(msg, texts), done(i, o)]


class Fake(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(codex_cli, "COUNT_CACHED", True); p.start(); self.addCleanup(p.stop)  # these pin the plumbing on the full count; test_token_waste covers the 11-17 count
        self.dir = tempfile.TemporaryDirectory()
        d = self.dir.name
        exe = os.path.join(d, "codex")
        with open(exe, "w") as f: f.write(FAKE)
        os.chmod(exe, os.stat(exe).st_mode | stat.S_IEXEC)
        self.log, self.script = os.path.join(d, "log.json"), os.path.join(d, "script.json")
        self.env = {k: os.environ.get(k) for k in ("FAKE_CODEX_LOG", "FAKE_CODEX_SCRIPT", "FAKE_CODEX_LOGIN", "OPENAI_API_KEY", "CODEX_HOME")}
        os.environ.update(FAKE_CODEX_LOG=self.log, FAKE_CODEX_SCRIPT=self.script, OPENAI_API_KEY="sk-not-for-codex", CODEX_HOME=d)
        os.environ.pop("FAKE_CODEX_LOGIN", None)
        self.cli, codex_cli.CODEX_CLI = codex_cli.CODEX_CLI, exe
        codex_cli._QUOTA["until"] = 0.0

    def tearDown(self):
        codex_cli.CODEX_CLI = self.cli
        codex_cli._QUOTA["until"] = 0.0
        for k, v in self.env.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
        self.dir.cleanup()

    def plays(self, *outputs):
        with open(self.script, "w") as f: json.dump(list(outputs), f)

    def calls(self):
        with open(self.log) as f: return json.load(f)


class Run(Fake):
    def test_the_last_message_is_the_answer_and_tokens_are_input_plus_output(self):
        self.plays(ok("Looking at it…", "The answer.", i=300, o=40))
        self.assertEqual(codex_cli.run("hi", "be brief", "gpt-5.6-luna", "low"), ("The answer.", 340))

    def test_the_cli_runs_locked_down_on_its_own_login(self):
        self.plays(ok("x"))
        codex_cli.run("the prompt", "You are the Scout.", "gpt-5.6-luna", "high")
        c = self.calls()[0]
        a = c["argv"]
        self.assertEqual((a[0], a[-1], c["stdin"], c["system"]), ("exec", "-", "the prompt", "You are the Scout."))
        for flag in ("--json", "--ephemeral", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check"): self.assertIn(flag, a)
        self.assertEqual(a[a.index("-s") + 1], "read-only")
        off = {a[i + 1] for i, x in enumerate(a) if x == "--disable"}
        self.assertTrue({"shell_tool", "unified_exec", "code_mode_host", "apps", "plugins", "browser_use", "computer_use"} <= off)
        self.assertIn("web_search=disabled", a)
        self.assertIn('model_reasoning_effort="high"', a)
        self.assertEqual(a[a.index("-m") + 1], "gpt-5.6-luna")
        self.assertNotIn("OPENAI_API_KEY", c["env"])  # never billed to the API key the OpenAI provider uses

    def test_the_default_model_passes_no_model_flag(self):
        self.plays(ok("x"))
        codex_cli.run("p", "s", codex_cli.DEFAULT, "medium")
        self.assertNotIn("-m", self.calls()[0]["argv"])

    def test_a_usage_limit_is_a_quota_error_that_holds_codex_runs_only(self):
        self.plays([{"type": "turn.started"}, failed("You've hit your usage limit. Upgrade to Pro or try again at 11:59 PM.")])
        with self.assertRaises(QuotaError) as e: codex_cli.run("p", "s", "m", "low")
        self.assertIn("plan rate limit reached", str(e.exception))
        self.assertEqual(classify(str(e.exception)), "quota")
        self.assertGreater(llm.quota_until("codex"), time.time())
        self.assertEqual(llm.quota_until(), llm.quota_until("terminal"))
        self.assertNotEqual(llm.quota_until("terminal"), llm.quota_until("codex"))

    def test_a_signed_out_cli_says_how_to_sign_in(self):
        self.plays([{"type": "turn.started"}, failed('{"error":{"message":"401 Unauthorized: refresh token expired"},"status":401}')])
        with self.assertRaises(LLMError) as e: codex_cli.run("p", "s", "m", "low")
        self.assertIn("codex login --device-auth", str(e.exception))

    def test_api_errors_show_their_own_message(self):
        self.plays([failed('{"type":"error","error":{"message":"The model is overloaded."},"status":500}')])
        with self.assertRaisesRegex(LLMError, r"^Codex error: The model is overloaded\.$"): codex_cli.run("p", "s", "m", "low")

    def test_a_run_without_a_turn_reports_stderr(self):
        self.plays({"stderr": "boom\nError: config unreadable\n"})
        with self.assertRaisesRegex(LLMError, "config unreadable"): codex_cli.run("p", "s", "m", "low")

    def test_status_and_models(self):
        self.assertEqual(codex_cli.status(), "Logged in using ChatGPT")
        os.environ["FAKE_CODEX_LOGIN"] = "Not logged in"
        with self.assertRaisesRegex(LLMError, "isn't signed in"): codex_cli.status()
        self.assertEqual(codex_cli.models(), [(codex_cli.DEFAULT, "Codex · default model")])
        with open(os.path.join(self.dir.name, "models_cache.json"), "w") as f:
            json.dump({"models": [{"slug": "gpt-6-luna", "display_name": "GPT-6-Luna", "visibility": "list"},
                                  {"slug": "codex-auto-review", "visibility": "hide"}, {"slug": "bad slug!", "visibility": "list"}]}, f)
        self.assertEqual([m for m, _ in codex_cli.models()], [codex_cli.DEFAULT, "gpt-6-luna"])


class ResetTime(unittest.TestCase):
    def test_forms(self):
        now = time.mktime((2026, 11, 4, 10, 0, 0, 0, 0, -1))
        at = lambda s: time.localtime(codex_cli.reset_at(s, now))[3:5]
        self.assertEqual(at("try again at 3:45 PM."), (15, 45))
        self.assertEqual(at("Try again at 09:30"), (9, 30))  # already past today: tomorrow
        self.assertEqual(codex_cli.reset_at("try again at 09:30", now) - now, 23.5 * 3600)
        self.assertEqual(codex_cli.reset_at("try again in 2 hours 5 minutes", now) - now, 2 * 3600 + 300)
        self.assertEqual(codex_cli.reset_at("try again in 45 minutes", now) - now, 2700)
        self.assertEqual(codex_cli.reset_at("You've hit your usage limit.", now) - now, codex_cli.QUOTA_FALLBACK)


class Provider(Fake):
    def setUp(self):
        super().setUp()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        self.db.setting("codex_enabled", v="1")
        self.db.setting("codex_mode", v="text")  # these are text-mode tests; native tool calls: test_codex_bridge.py
        self.p = Providers(self.db, {})

    def test_listed_and_resolved(self):
        cat = {e["id"]: e for e in self.p.catalog()}
        self.assertTrue(cat["codex"]["configured"])
        self.assertEqual(cat["codex"]["models"][0]["id"], "codex:default")
        self.assertEqual(self.p.resolve("codex:gpt-6-luna"), ("codex", "gpt-6-luna"))
        self.assertEqual(self.p.source("codex"), "ui")
        self.assertEqual(llm.plan_parallel("codex"), codex_cli.PARALLEL)

    def test_a_tool_call_comes_back_as_a_tool_use_block(self):
        self.plays(ok({"text": "", "tool_calls": [{"name": "lookup", "input_json": '{"q": "sn1"}'}]}, i=500, o=30))
        call, label = self.p.completer("codex:gpt-6-luna", "low")
        tools = [{"name": "lookup", "description": "Find a subnet.", "input_schema": {"type": "object", "required": ["q"], "properties": {"q": {"type": "string"}}}}]
        blocks, stop, n = call("You are the Scout.", tools, [{"role": "user", "content": "Tell me about sn1"}])
        self.assertEqual((label, stop, n), ("codex:gpt-6-luna", "tool_use", 530))
        self.assertEqual([(b["type"], b["name"], b["input"]) for b in blocks], [("tool_use", "lookup", {"q": "sn1"})])
        c = self.calls()[0]
        self.assertIn("input_json", c["system"])
        self.assertIn("lookup", c["system"])
        self.assertIn("Tell me about sn1", c["stdin"])
        self.assertIn("--output-schema", c["argv"])  # strict structured output (the file itself is gone after the run)

    def test_tool_input_that_isnt_json_gets_one_retry_and_both_count(self):
        self.plays(ok({"text": "", "tool_calls": [{"name": "lookup", "input_json": "q=sn1"}]}, i=100, o=10),
                   ok({"text": "", "tool_calls": [{"name": "lookup", "input_json": '{"q": "sn1"}'}]}, i=200, o=10))
        call, _ = self.p.completer("codex:default")
        tools = [{"name": "lookup", "description": "d", "input_schema": {"type": "object", "required": ["q"], "properties": {"q": {"type": "string"}}}}]
        blocks, stop, n = call("s", tools, [{"role": "user", "content": "hi"}])
        self.assertEqual((stop, n, blocks[0]["input"]), ("tool_use", 320, {"q": "sn1"}))
        retry = self.calls()[1]["stdin"]
        self.assertIn("previous reply was rejected", retry)
        self.assertIn("isn't a JSON object", retry)

    def test_a_plain_answer_ends_the_turn(self):
        self.plays(ok({"text": "Subnet 1 is text prompting.", "tool_calls": []}))
        blocks, stop, _ = self.p.completer("codex:default")[0]("s", [], [{"role": "user", "content": "hi"}])
        self.assertEqual((stop, blocks), ("end_turn", [{"type": "text", "text": "Subnet 1 is text prompting."}]))

    def test_structured_falls_back_to_plain_json_when_the_schema_isnt_strict(self):
        self.plays([{"type": "turn.started"}, failed('{"error":{"message":"Invalid schema for response_format \'codex_output_schema\'","code":"invalid_json_schema"},"status":400}')],
                   ok('```json\n{"answer": "4"}\n```', i=50, o=5))
        got = []
        schema = {"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string"}, "extra": {"type": "object"}}}
        self.assertEqual(self.p.structured("codex:default", "Do maths.", "2+2?", schema, "r", got.append), {"answer": "4"})
        self.assertEqual(got, [55])
        first, second = self.calls()
        self.assertIn("--output-schema", first["argv"])
        self.assertNotIn("--output-schema", second["argv"])
        self.assertIn('"extra"', second["system"])


if __name__ == "__main__":
    unittest.main()
