"""Agents → Models → Add → CLI → GitHub (Copilot): GitHub's Copilot CLI on the token's Copilot plan (copilot_cli.py).
Connect checks the token's shape, GitHub's /user (like `curl -H "Authorization: Bearer $TOKEN" https://api.github.com/user`)
and one real prompt through the CLI; turns run `copilot` with COPILOT_GITHUB_TOKEN. GitHub is a local stub server and
`copilot` a stub script that writes the CLI's JSONL events."""
import json, os, stat, sys, tempfile, threading, unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from app import agents, copilot_cli, llm
from app.auth import AuthDB
from app.secretbox import SecretBox

GOOD = "github_pat_" + "a" * 40
NO_COPILOT = "github_pat_" + "b" * 40  # GitHub signs it in, the Copilot CLI refuses it
CLASSIC = "ghp_" + "c" * 36

# the stub CLI: a good token answers, any other fails like the real CLI; logs argv, stdin and env to $STUB_LOG
STUB = r'''#!PY
import json, os, sys
argv, prompt = sys.argv[1:], sys.stdin.read()
tok = os.environ.get("COPILOT_GITHUB_TOKEN", "")
with open(os.environ["STUB_LOG"], "a") as f:
    f.write(json.dumps({"argv": argv, "prompt": prompt, "good": tok == os.environ["STUB_GOOD"],
                        "gh": os.environ.get("GITHUB_TOKEN"), "home": os.environ.get("COPILOT_HOME")}) + "\n")
ev = lambda t, **d: print(json.dumps({"type": t, "data": d}))
if tok != os.environ["STUB_GOOD"]:
    ev("session.error", errorType="authentication", message="Authentication failed: this token can't use Copilot (401)")
    print(json.dumps({"type": "result", "exitCode": 1})); sys.exit(1)
ev("session.auto_mode_resolved", chosenModel="mai-code-1.1-flash", candidateModels=["mai-code-1.1-flash", "gpt-6-luna"])
ev("assistant.message", content=os.environ.get("STUB_ANSWER", "OK"), phase="final_answer", toolRequests=[])
u = argv[argv.index("--usage-output-file") + 1]
json.dump({"modelMetrics": {"mai-code-1.1-flash": {"usage": {"inputTokens": 1200, "outputTokens": 30}}}}, open(u, "w"))
print(json.dumps({"type": "result", "exitCode": 0}))
'''


class GitHub(BaseHTTPRequestHandler):
    seen = []
    def log_message(self, *a): pass
    def do_GET(self):
        tok = self.headers.get("Authorization", "").removeprefix("Bearer ")
        GitHub.seen.append(self.path)
        ok = tok in (GOOD, NO_COPILOT)
        b = json.dumps({"login": "octo"} if ok else {"message": "Bad credentials"}).encode()
        self.send_response(200 if ok else 401); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)


class CopilotCli(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.srv = HTTPServer(("127.0.0.1", 0), GitHub)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        stub = os.path.join(d, "copilot")
        with open(stub, "w") as f: f.write(STUB.replace("#!PY", "#!" + sys.executable))
        os.chmod(stub, os.stat(stub).st_mode | stat.S_IEXEC)
        self.log = os.path.join(d, "stub.log")
        self._was = agents.GITHUB_API, copilot_cli.COPILOT_CLI
        agents.GITHUB_API, copilot_cli.COPILOT_CLI = f"http://127.0.0.1:{self.srv.server_port}", stub
        self._env = {"COPILOT_STATE_DIR": os.path.join(d, "state"), "STUB_LOG": self.log, "STUB_GOOD": GOOD,
                     "GITHUB_TOKEN": "ghp_server_alerts_token_should_not_reach_copilot"}
        os.environ.update(self._env)
        self.db = AuthDB(os.path.join(d, "a.db"))
        me = lambda req: {"username": "root", "role": "admin"}
        app = FastAPI()
        app.include_router(agents.build(self.db, {"admin": me, "sudo": me, "ops": None}, lambda req: "127.0.0.1", d))
        self.c = TestClient(app)
        GitHub.seen = []

    def tearDown(self):
        agents.GITHUB_API, copilot_cli.COPILOT_CLI = self._was
        for k in [*self._env, "STUB_ANSWER"]: os.environ.pop(k, None)
        self.srv.shutdown(); self.srv.server_close(); self.tmp.cleanup()

    def runs(self):
        try:
            with open(self.log) as f: return [json.loads(l) for l in f]
        except OSError:
            return []

    def post(self, key):
        return self.c.post("/api/agents/settings/provider", json={"provider": "copilot-cli", "key": key})

    def configured(self):
        return self.c.get("/api/agents/settings").json()["providers"]["copilot-cli"]["configured"]

    def test_connect_checks_user_then_a_real_cli_prompt_and_saves(self):
        r = self.post(GOOD)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("@octo", r.json()["message"])
        self.assertEqual(GitHub.seen, ["/user"])
        (run,) = self.runs()
        self.assertTrue(run["good"])  # the saved token is what the CLI gets, as COPILOT_GITHUB_TOKEN
        self.assertIn("--available-tools=", run["argv"])  # no shell, files or web for the model
        self.assertEqual(run["argv"][run["argv"].index("--model") + 1], "auto")
        self.assertIsNone(run["gh"])  # the server's own GITHUB_TOKEN never reaches the CLI
        self.assertTrue(run["home"])
        self.assertTrue(self.configured())
        cat = next(c for c in self.c.get("/api/agents/settings").json()["catalog"] if c["id"] == "copilot-cli")
        self.assertEqual([m["id"] for m in cat["models"]], ["copilot-cli:auto", "copilot-cli:gpt-6-luna", "copilot-cli:mai-code-1.1-flash"])

    def test_classic_token_is_refused_before_anything_runs(self):
        r = self.post(CLASSIC)
        self.assertEqual(r.status_code, 400)
        self.assertIn("classic", r.json()["detail"])
        self.assertEqual((GitHub.seen, self.runs()), ([], []))

    def test_github_rejects_token(self):
        r = self.post("github_pat_" + "z" * 40)
        self.assertEqual(r.status_code, 400)
        self.assertIn("401", r.json()["detail"])
        self.assertEqual(self.runs(), [])  # stopped at /user
        self.assertFalse(self.configured())

    def test_cli_refuses_token_saves_nothing(self):
        r = self.post(NO_COPILOT)
        self.assertEqual(r.status_code, 400)
        self.assertIn("Copilot Requests", r.json()["detail"])
        self.assertIn("Nothing was saved", r.json()["detail"])
        self.assertFalse(self.configured())

    def test_cli_not_installed(self):
        copilot_cli.COPILOT_CLI = os.path.join(self.tmp.name, "missing-copilot")
        r = self.post(GOOD)
        self.assertEqual(r.status_code, 400)
        self.assertIn("isn't installed", r.json()["detail"])
        self.assertEqual(GitHub.seen, [])

    def test_agent_turn_runs_through_the_cli(self):
        self.assertEqual(self.post(GOOD).status_code, 200)
        os.environ["STUB_ANSWER"] = json.dumps({"text": "", "tool_calls": [{"name": "lookup", "input": {"subnet": 1}}]})
        prov = llm.Providers(self.db, SecretBox(self.db, self.tmp.name))
        call, label = prov._completer("copilot-cli:auto", "low")
        tools = [{"name": "lookup", "description": "Look up a subnet.", "input_schema": {"type": "object", "properties": {"subnet": {"type": "integer"}}, "required": ["subnet"]}}]
        blocks, stop, tokens = call("You are the Scout.", tools, [{"role": "user", "content": "How is subnet 1?"}])
        self.assertEqual(label, "copilot-cli:auto")
        self.assertEqual((stop, blocks[0]["name"], blocks[0]["input"], tokens), ("tool_use", "lookup", {"subnet": 1}, 1230))
        last = self.runs()[-1]
        self.assertIn("You are the Scout.", last["prompt"])
        self.assertIn("How is subnet 1?", last["prompt"])
        os.environ["STUB_ANSWER"] = '{"verdict": "fine"}'
        self.assertEqual(prov._structured("copilot-cli:auto", "Judge.", "Subnet 1?", {"type": "object"}), {"verdict": "fine"})


class Parse(unittest.TestCase):
    def test_model_not_available_says_pick_auto(self):
        out = json.dumps({"type": "session.error", "data": {"message": 'Execution failed: Model "gpt-4.1" is not available.'}})
        with self.assertRaises(llm.LLMError) as e: copilot_cli.parse(out)
        self.assertIn("Copilot · Auto", str(e.exception))

    def test_used_up_plan_is_a_plain_error_not_the_claude_quota(self):
        out = json.dumps({"type": "session.error", "data": {"message": "You have exceeded your premium request allowance for this month."}})
        with self.assertRaises(llm.LLMError) as e: copilot_cli.parse(out)
        self.assertNotIsInstance(e.exception, llm.QuotaError)
        self.assertIn("used up", str(e.exception))


if __name__ == "__main__":
    unittest.main()
