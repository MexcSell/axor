"""codex_bridge.py: Codex with native tool calls. A fake `codex` starts the MCP server the real CLI would (terminal_bridge.py,
from the -c mcp_servers.axor.* flags), calls AXoR's tools through it as scripted, and prints `codex exec --json` events;
run_loop runs the tools, as it does for every provider."""
import json, os, stat, sys, tempfile, textwrap, threading, time, unittest
from unittest import mock

from app import agents, codex_bridge, codex_cli, llm
from app.auth import AuthDB
from app.llm import LLMError, Providers, QuotaError

# $FAKE_CODEX_SCRIPT: a JSON list of steps, played in order:
#   {"call": name, "args": {...}}  a tools/call through the MCP server; its result is logged
#   {"calls": [[name, args], ...]} several tools/calls sent at once, then their results read (in any order)
#   {"msg": text}                  an agent_message
#   {"done": [input, output]}      turn.completed with that usage, then exit
#   {"failed": message}            turn.failed, then exit
#   {"event": {...}}               any event as is
#   {"sleep": seconds}
FAKE = textwrap.dedent(f"""\
    #!{sys.executable}
    import json, os, subprocess, sys, time
    argv = sys.argv[1:]
    cfg = dict(argv[i + 1].split("=", 1) for i, a in enumerate(argv) if a == "-c" and "=" in argv[i + 1])
    log = {{"argv": argv, "stdin": sys.stdin.read(), "env": sorted(k for k in os.environ if "OPENAI" in k),
            "system": open(json.loads(cfg["model_instructions_file"])).read(), "results": []}}
    def save(): json.dump(log, open(os.environ["FAKE_CODEX_LOG"], "w"))
    save()
    mcp = subprocess.Popen([json.loads(cfg["mcp_servers.axor.command"]), *json.loads(cfg["mcp_servers.axor.args"])],
                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    n = [0]
    def rpc(method, params):
        n[0] += 1
        mcp.stdin.write(json.dumps({{"jsonrpc": "2.0", "id": n[0], "method": method, "params": params}}) + "\\n"); mcp.stdin.flush()
        return json.loads(mcp.stdout.readline())["result"]
    rpc("initialize", {{"protocolVersion": "2025-06-18"}})
    log["tools"] = [t["name"] for t in rpc("tools/list", {{}})["tools"]]; save()
    def out(e): print(json.dumps(e), flush=True)
    out({{"type": "thread.started"}}); out({{"type": "turn.started"}})
    for i, s in enumerate(json.load(open(os.environ["FAKE_CODEX_SCRIPT"]))):
        if "call" in s:
            r = rpc("tools/call", {{"name": s["call"], "arguments": s.get("args", {{}}), "_meta": {{"callId": f"exec-{{i}}"}}}})
            log["results"].append({{"text": r["content"][0]["text"], "error": r["isError"]}}); save()
        elif "calls" in s:
            ids = []
            for k, (name, args) in enumerate(s["calls"]):
                n[0] += 1; ids.append(n[0])
                mcp.stdin.write(json.dumps({{"jsonrpc": "2.0", "id": n[0], "method": "tools/call", "params": {{"name": name, "arguments": args, "_meta": {{"callId": f"exec-{{i}}-{{k}}"}}}}}}) + "\\n")
            mcp.stdin.flush()
            got = {{}}
            while len(got) < len(ids):
                r = json.loads(mcp.stdout.readline()); got[r["id"]] = r["result"]
            log["results"] += [{{"text": got[j]["content"][0]["text"], "error": got[j]["isError"]}} for j in ids]; save()
        elif "msg" in s: out({{"type": "item.completed", "item": {{"type": "agent_message", "text": s["msg"]}}}})
        elif "event" in s: out(s["event"])
        elif "sleep" in s: time.sleep(s["sleep"])
        elif "failed" in s: out({{"type": "turn.failed", "error": {{"message": s["failed"]}}}}); sys.exit(1)
        elif "done" in s:
            out({{"type": "turn.completed", "usage": {{"input_tokens": s["done"][0], "cached_input_tokens": 1, "output_tokens": s["done"][1]}}}})
            sys.exit(0)
    """)

TOOLS = [{"name": "add", "description": "Adds.", "input_schema": {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}}},
         {"name": "boom", "description": "Fails.", "input_schema": {"type": "object", "properties": {}}}]

def run_tool(name, inp):
    if name == "add": return {"sum": inp["a"] + inp["b"]}
    raise ValueError("boom failed")


class Bridge(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(codex_cli, "COUNT_CACHED", True); p.start(); self.addCleanup(p.stop)  # these pin the plumbing on the full count; test_token_waste covers the 11-17 count
        self.dir = tempfile.TemporaryDirectory()
        d = self.dir.name
        exe = os.path.join(d, "codex")
        with open(exe, "w") as f: f.write(FAKE)
        os.chmod(exe, os.stat(exe).st_mode | stat.S_IEXEC)
        self.log, self.script = os.path.join(d, "log.json"), os.path.join(d, "script.json")
        self.env = {k: os.environ.get(k) for k in ("FAKE_CODEX_LOG", "FAKE_CODEX_SCRIPT", "OPENAI_API_KEY", "CODEX_HOME")}
        os.environ.update(FAKE_CODEX_LOG=self.log, FAKE_CODEX_SCRIPT=self.script, OPENAI_API_KEY="sk-not-for-codex", CODEX_HOME=d)
        self.cli, codex_cli.CODEX_CLI = codex_cli.CODEX_CLI, exe
        codex_cli._QUOTA["until"] = 0.0
        self.db = AuthDB(os.path.join(d, "a.db"))
        self.db.setting("codex_enabled", v="1")
        self.p = Providers(self.db, {})

    def tearDown(self):
        codex_cli.CODEX_CLI = self.cli
        codex_cli._QUOTA["until"] = 0.0
        for k, v in self.env.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
        self.dir.cleanup()

    def plays(self, *steps):
        with open(self.script, "w") as f: json.dump(list(steps), f)

    def logged(self):
        with open(self.log) as f: return json.load(f)

    def loop(self, task="Add 2 and 3, then try boom."):
        call, _ = self.p.completer("codex:gpt-6-luna", "low")
        msgs, toks = [{"role": "user", "content": task}], []
        agents.run_loop(call, "You are the Scout.", TOOLS, msgs, run_tool, toks.append)
        return msgs, toks

    def test_native_is_the_default_and_text_stays_a_choice(self):
        self.assertEqual(self.p.codex_mode(), "mcp")
        self.db.setting("codex_mode", v="text")
        self.assertEqual(self.p.codex_mode(), "text")

    def test_tool_calls_run_in_run_loop_and_results_go_back_to_codex(self):
        self.plays({"msg": "Adding first."}, {"call": "add", "args": {"a": 2, "b": 3}}, {"call": "boom"},
                   {"msg": "5, and boom failed."}, {"done": [900, 40]})
        msgs, toks = self.loop()
        kinds = [[b["type"] for b in m["content"]] if isinstance(m["content"], list) else "task" for m in msgs]
        self.assertEqual(kinds, ["task", ["text", "tool_use"], ["tool_result"], ["tool_use"], ["tool_result"], ["text"]])
        self.assertEqual((msgs[1]["content"][1]["id"], msgs[1]["content"][1]["input"]), ("exec-1", {"a": 2, "b": 3}))  # Codex's callId, a real object
        self.assertEqual(msgs[-1]["content"][0]["text"], "5, and boom failed.")
        self.assertEqual(toks, [0, 0, 940])  # Codex reports usage when the run ends
        log = self.logged()
        self.assertEqual(log["results"], [{"text": '{"sum": 5}', "error": False}, {"text": '{"error": "boom failed"}', "error": True}])
        self.assertEqual(log["tools"], ["add", "boom"])

    def test_calls_made_at_once_are_one_turn(self):
        self.plays({"calls": [["add", {"a": 1, "b": 2}], ["add", {"a": 3, "b": 4}]]}, {"msg": "3 and 7"}, {"done": [50, 5]})
        msgs, toks = self.loop("Add 1+2 and 3+4 at once.")
        # each call comes in on its own connection and thread, so two made at once can queue either way round (seen under load
        # in redeploy.sh's run, 2026-11-09); results go back by id, so the order inside the turn doesn't matter
        self.assertEqual(sorted(b["id"] for b in msgs[1]["content"]), ["exec-0-0", "exec-0-1"])
        self.assertEqual(len(msgs), 4)  # task, both calls, both results, answer: one step for the pair
        self.assertEqual(self.logged()["results"], [{"text": '{"sum": 3}', "error": False}, {"text": '{"sum": 7}', "error": False}])

    def test_one_locked_down_session_with_axor_pre_approved(self):
        self.plays({"msg": "hi"}, {"done": [10, 1]})
        self.loop("hello there")
        log, argv = self.logged(), self.logged()["argv"]
        self.assertEqual(log["stdin"], "hello there")
        self.assertTrue(log["system"].startswith("You are the Scout.") and "mcp__axor__" in log["system"])
        self.assertEqual(log["env"], [])  # never an API key: it runs on the ChatGPT login
        off = {argv[i + 1] for i, a in enumerate(argv) if a == "--disable"}
        self.assertNotIn("code_mode_host", off)  # how Codex calls MCP tools
        self.assertTrue({"shell_tool", "unified_exec", "apps", "plugins", "browser_use", "multi_agent"} <= off)
        for want in ('mcp_servers.axor.default_tools_approval_mode="approve"', "web_search=disabled", "--ignore-user-config", "--ephemeral",
                     "mcp_servers.axor.supports_parallel_tool_calls=true"):  # else Codex sends calls made at once one by one (11-18)
            self.assertIn(want, argv)
        self.assertEqual(argv[argv.index("-s") + 1], "read-only")
        self.assertEqual(argv[argv.index("-m") + 1], "gpt-6-luna")

    def test_a_usage_limit_is_a_quota_error_and_frees_the_gate(self):
        self.plays({"call": "add", "args": {"a": 1, "b": 1}}, {"failed": "You've hit your usage limit. Try again in 2 hours."})
        free = codex_cli.GATE._value
        with self.assertRaises(QuotaError) as e: self.loop()
        self.assertIn("Codex plan rate limit reached", str(e.exception))
        self.assertGreater(codex_cli.quota_until(), time.time() + 3600)
        self.assertEqual(codex_cli.GATE._value, free)

    def test_a_missing_code_mode_host_says_what_to_fix(self):
        self.plays({"event": {"type": "item.completed", "item": {"type": "error", "message": "Code Mode is unavailable because failed to spawn code-mode host"}}},
                   {"msg": "I couldn't use the tools."}, {"done": [10, 1]})
        with self.assertRaises(LLMError) as e: self.loop()
        self.assertIn("code-mode host", str(e.exception))

    def test_a_dropped_run_stops_its_cli(self):
        self.plays({"call": "add", "args": {"a": 1, "b": 2}}, {"msg": "never read"})
        call, _ = self.p.completer("codex:default", "low")
        msgs = [{"role": "user", "content": "go"}]
        blocks, stop, _ = call("s", TOOLS, msgs)
        self.assertEqual(stop, "tool_use")
        free = codex_cli.GATE._value
        self.plays({"msg": "fresh"}, {"done": [5, 1]})  # a new run on the same completer: the old session is closed
        blocks, stop, n = call("s", TOOLS, [{"role": "user", "content": "again"}])
        self.assertEqual((blocks[0]["text"], stop, n), ("fresh", "end_turn", 6))
        self.assertEqual(codex_cli.GATE._value, free)

    # ---- D-021: token metering. Codex reports usage only at turn.completed; a session left mid-run used to be killed first
    def test_a_run_that_hits_the_step_limit_still_counts_its_tokens(self):
        from app import agent_core
        agent_core.init(self.db)
        self.addCleanup(lambda: (setattr(agent_core._local, "run", None), setattr(agent_core, "_core", None)))
        self.plays(*[{"call": "add", "args": {"a": i, "b": 1}} for i in range(agents.MAX_STEPS + 2)], {"done": [1000, 50]})
        rid = agent_core.begin("teams", 1, "task", ref="mw:1")
        msgs, toks = self.loop("Keep adding.")
        self.assertEqual(sum(1 for m in msgs if m["role"] == "assistant" and any(b.get("type") == "tool_use" for b in m["content"])), agents.MAX_STEPS)
        self.assertEqual(toks[-1], 1050)                                   # drained at the loop's end, given to the caller's count
        self.assertEqual(self.db.q("SELECT tokens, metering FROM ac_runs WHERE id=?", (rid,), one=True), {"tokens": 1050, "metering": None})
        self.assertTrue(any(r["error"] and "run ended" in r["text"] for r in self.logged()["results"]))  # Codex was told, not killed
        agent_core.end("done")

    def test_no_usage_in_time_marks_the_run_unmetered_never_zero(self):
        from app import agent_core
        agent_core.init(self.db)
        self.addCleanup(lambda: (setattr(agent_core._local, "run", None), setattr(agent_core, "_core", None)))
        self.plays(*[{"call": "add", "args": {"a": i, "b": 1}} for i in range(agents.MAX_STEPS + 1)], {"sleep": 30}, {"done": [1, 1]})
        was, codex_bridge.DRAIN = codex_bridge.DRAIN, .5
        self.addCleanup(lambda: setattr(codex_bridge, "DRAIN", was))
        rid = agent_core.begin("teams", 1, "task", ref="mw:2")
        t0 = time.time(); self.loop("Keep adding.")
        self.assertLess(time.time() - t0, 25)                              # bounded: the drain gives up
        self.assertEqual(self.db.q("SELECT metering FROM ac_runs WHERE id=?", (rid,), one=True)["metering"], "unmetered")
        agent_core.end("done")

    def _full_gate(self):
        """Every slot of the Codex gate taken by other runs; returns a function that frees them."""
        n = 0
        while codex_cli.GATE.acquire(blocking=False): n += 1
        return lambda: [codex_cli.GATE.release() for _ in range(n)]

    def test_the_drain_takes_a_gate_slot_or_gives_up_unmetered(self):
        # Milestone 2 C: the closing turn is a model turn: it waits for a runs-at-once slot within the drain's deadline. None free:
        # Codex is stopped without that turn (it never hears "the run ended") and the run is unmetered, never 0
        from app import agent_core
        agent_core.init(self.db)
        self.addCleanup(lambda: (setattr(agent_core._local, "run", None), setattr(agent_core, "_core", None)))
        self.plays({"call": "add", "args": {"a": 1, "b": 2}}, {"done": [70, 7]})
        rid = agent_core.begin("teams", 1, "task", ref="mw:g")
        call, _ = self.p.completer("codex:default", "low")
        call("s", TOOLS, [{"role": "user", "content": "go"}])            # stops at the tool call: the gate slot is released
        free = self._full_gate()
        try:
            was, codex_bridge.DRAIN = codex_bridge.DRAIN, .6
            try:
                t0 = time.time(); n = llm.settle_sessions()
            finally: codex_bridge.DRAIN = was
        finally: free()
        self.assertLess(time.time() - t0, 5)
        self.assertEqual(n, 0)
        self.assertEqual(self.db.q("SELECT metering, tokens FROM ac_runs WHERE id=?", (rid,), one=True), {"metering": "unmetered", "tokens": 0})
        self.assertFalse(any("run ended" in r["text"] for r in self.logged().get("results", [])))  # no closing turn ran
        agent_core.end("done")

    def test_the_drain_runs_inside_the_gate_and_counts_its_turn(self):
        from app import agent_core
        agent_core.init(self.db)
        self.addCleanup(lambda: (setattr(agent_core._local, "run", None), setattr(agent_core, "_core", None)))
        self.plays({"call": "add", "args": {"a": 1, "b": 2}}, {"done": [70, 7]})
        rid = agent_core.begin("teams", 1, "task", ref="mw:h")
        call, _ = self.p.completer("codex:default", "low")
        call("s", TOOLS, [{"role": "user", "content": "go"}])
        free = self._full_gate()
        threading.Timer(.4, free).start()                                  # a slot frees up within the deadline
        seen = []
        real = codex_cli.GATE.acquire
        def acquire(*a, **k):
            ok = real(*a, **k); seen.append(ok); return ok
        with mock.patch.object(codex_cli.GATE, "acquire", acquire):
            n = llm.settle_sessions()
        self.assertEqual(n, 77); self.assertIn(True, seen)                 # it waited for the slot, then drained
        self.assertTrue(any("run ended" in r["text"] for r in self.logged()["results"]))  # Codex was told; no tool ran
        self.assertEqual(self.db.q("SELECT tokens, metering FROM ac_runs WHERE id=?", (rid,), one=True), {"tokens": 77, "metering": None})
        agent_core.end("done")
        self.assertEqual(codex_cli.GATE.held, 0)                           # every slot given back

    def test_a_slot_freed_late_still_leaves_the_turn_its_time(self):
        # the gate wait and the closing turn don't share one deadline: a slot freed near the end still drains and counts
        from app import agent_core
        agent_core.init(self.db)
        self.addCleanup(lambda: (setattr(agent_core._local, "run", None), setattr(agent_core, "_core", None)))
        self.plays({"call": "add", "args": {"a": 1, "b": 2}}, {"done": [70, 7]})   # the fake closes its turn 0.5 s after "run ended"
        rid = agent_core.begin("teams", 1, "task", ref="mw:late")
        call, _ = self.p.completer("codex:default", "low")
        call("s", TOOLS, [{"role": "user", "content": "go"}])
        free = self._full_gate()
        threading.Timer(.9, free).start()                                  # freed at 0.9 s of a 1 s drain
        was, codex_bridge.DRAIN = codex_bridge.DRAIN, 1.0
        try: n = llm.settle_sessions()
        finally: codex_bridge.DRAIN = was
        self.assertEqual(n, 77)
        self.assertEqual(self.db.q("SELECT metering FROM ac_runs WHERE id=?", (rid,), one=True)["metering"], None)
        agent_core.end("done")

    def test_a_budget_that_refuses_gets_no_closing_turn(self):
        # Milestone 2 C5: the drain's closing turn is a model call: a stopping limit already reached refuses it like any other.
        # Codex is stopped without it and the run is unmetered (an estimate settles it), so a drain never gets past the budget
        from app import agent_core
        agent_core.init(self.db)
        self.addCleanup(lambda: (setattr(agent_core._local, "run", None), setattr(agent_core, "_core", None)))
        # Milestone 3: the first turn reserves (the floor, 2,000) before it goes out, so the limit must leave room for it
        agent_core.get().set_limit(1, "system", "teams", 5_000, period="day", label="tight", origin="manual", by="test")
        self.plays({"call": "add", "args": {"a": 1, "b": 2}}, {"done": [70, 7]})
        rid = agent_core.begin("teams", 1, "task", ref="mw:b")
        call, _ = self.p.completer("codex:default", "low")
        call("s", TOOLS, [{"role": "user", "content": "go"}])            # admitted: nothing was spent yet; its hold stays with the session
        held = self.db.q("SELECT state, estimate FROM ac_reservations WHERE run_id=?", (rid,))
        self.assertEqual([(r["state"], r["estimate"]) for r in held], [("held", 2_000)])
        agent_core.used(6_000)                                           # the scope is now over its limit
        self.assertIsNotNone(agent_core.over())
        n = llm.settle_sessions()
        self.assertEqual(n, 0)
        self.assertEqual(self.db.q("SELECT metering FROM ac_runs WHERE id=?", (rid,), one=True)["metering"], "unmetered")
        self.assertEqual(self.db.q("SELECT state FROM ac_reservations WHERE run_id=?", (rid,), one=True)["state"], "unmetered")  # never released as 0
        self.assertFalse(any("run ended" in r["text"] for r in self.logged().get("results", [])))  # no closing turn ran
        self.assertEqual(codex_cli.GATE.held, 0)
        agent_core.end("done")

    def test_a_session_that_reports_on_a_later_turn_settles_its_hold_with_the_total(self):
        # Milestone 3: turn 1 reserves (its hold stays with the session), turn 2 holds nothing new (admit(0)) and the session reports
        # its usage there: the session's hold is settled with that total, in the transaction that counts it, never with 0
        from app import agent_core
        agent_core.init(self.db)
        self.addCleanup(lambda: (setattr(agent_core._local, "run", None), setattr(agent_core, "_core", None)))
        agent_core.get().set_limit(1, "system", "teams", 100_000, period="day", label="roomy", origin="manual", by="test")
        self.plays({"call": "add", "args": {"a": 1, "b": 2}}, {"done": [70, 7]})
        rid = agent_core.begin("teams", 1, "task", ref="mw:n")
        msgs, toks = self.loop("Add 1 and 2.")
        agent_core.end("done")
        hs = self.db.q("SELECT state, estimate, actual FROM ac_reservations WHERE run_id=? ORDER BY id", (rid,))
        run = self.db.q("SELECT tokens, metering FROM ac_runs WHERE id=?", (rid,), one=True)
        self.assertEqual([h["state"] for h in hs], ["settled"])                # one hold: the session's, settled once
        self.assertEqual(hs[0]["actual"], run["tokens"])
        self.assertGreater(run["tokens"], 0)
        self.assertIsNone(run["metering"])
        self.assertEqual(sum(toks), run["tokens"])                              # the caller's own count agrees

    def test_two_sessions_at_once_under_one_limit_each_settle_once(self):
        # Milestone 4: concurrent Codex sessions under one stopping limit: each holds, each settles with its own session's total
        from app import agent_core
        agent_core.init(self.db)
        self.addCleanup(lambda: (setattr(agent_core._local, "run", None), setattr(agent_core, "_core", None)))
        agent_core.get().set_limit(1, "system", "teams", 1_000_000, period="day", label="roomy", origin="manual", by="test")
        self.plays({"call": "add", "args": {"a": 1, "b": 2}}, {"done": [70, 7]})
        rids, errs = [], []
        def one(i):
            try:
                rids.append(agent_core.begin("teams", 1, "task", ref=f"mw:c{i}"))
                self.loop("Add 1 and 2.")
                agent_core.end("done")
            except Exception as e:  # noqa: BLE001
                errs.append(e)
        ts = [threading.Thread(target=one, args=(i,)) for i in range(2)]
        for t in ts: t.start()
        for t in ts: t.join(60)
        self.assertEqual(errs, [])
        for rid in rids:
            hs = self.db.q("SELECT state, actual FROM ac_reservations WHERE run_id=? ORDER BY id", (rid,))
            tokens = self.db.q("SELECT tokens FROM ac_runs WHERE id=?", (rid,), one=True)["tokens"]
            self.assertEqual([h["state"] for h in hs if h["state"] != "merged"], ["settled"])
            self.assertEqual(next(h["actual"] for h in hs if h["state"] == "settled"), tokens)
            self.assertGreater(tokens, 0)

    def test_a_session_that_fails_mid_way_leaves_no_hold_held(self):
        # Milestone 3: the first turn's hold stays with the session; the session then fails (turn.failed, no usage). Every hold of
        # it must end settled, unmetered or charged, never left held (it would hold the budget) and never released as 0
        from app import agent_core
        agent_core.init(self.db)
        self.addCleanup(lambda: (setattr(agent_core._local, "run", None), setattr(agent_core, "_core", None)))
        agent_core.get().set_limit(1, "system", "teams", 100_000, period="day", label="roomy", origin="manual", by="test")
        self.plays({"call": "add", "args": {"a": 1, "b": 2}}, {"failed": "the model broke"})
        rid = agent_core.begin("teams", 1, "task", ref="mw:f")
        with self.assertRaises(LLMError): self.loop("Add 1 and 2.")
        llm.settle_sessions(quick=True)
        states = [r["state"] for r in self.db.q("SELECT state FROM ac_reservations WHERE run_id=?", (rid,))]
        self.assertTrue(states)
        self.assertNotIn("held", states)
        self.assertNotIn("released", states)                           # a Codex call has no bound: its use is unknown, not none
        self.assertEqual(self.db.q("SELECT metering FROM ac_runs WHERE id=?", (rid,), one=True)["metering"], "unmetered")
        agent_core.end("failed")

    def test_a_session_drained_later_credits_the_run_that_opened_it(self):
        from app import agent_core
        agent_core.init(self.db)
        self.addCleanup(lambda: (setattr(agent_core._local, "run", None), setattr(agent_core, "_core", None)))
        self.plays({"call": "add", "args": {"a": 1, "b": 2}}, {"done": [70, 7]})
        a = agent_core.begin("teams", 1, "task", ref="mw:a")
        call, _ = self.p.completer("codex:default", "low")
        call("s", TOOLS, [{"role": "user", "content": "go"}])           # a call outside run_loop leaves the session open
        agent_core.end("done")
        self.plays({"msg": "hi"}, {"done": [10, 1]})
        b = agent_core.begin("teams", 1, "task", ref="mw:b")
        self.loop("hello")                                                 # this loop's end drains the earlier session too
        agent_core.end("done")
        row = lambda rid: self.db.q("SELECT tokens FROM ac_runs WHERE id=?", (rid,), one=True)["tokens"]
        self.assertEqual((row(a), row(b)), (77, 11))

    def test_a_finished_session_is_not_drained_again(self):
        self.plays({"msg": "hi"}, {"done": [10, 1]})
        msgs, toks = self.loop("hello")
        self.assertEqual(toks, [11])                                       # counted once, by its own turn

    def test_text_mode_still_writes_tool_calls_as_json(self):
        self.db.setting("codex_mode", v="text")
        s = codex_bridge.CodexSession
        codex_bridge.CodexSession = None  # never used in text mode
        try:
            with self.assertRaises(LLMError): self.loop()  # the fake speaks MCP only: text mode reads no answer from it
        finally:
            codex_bridge.CodexSession = s
        self.assertIn("--output-schema", self.logged()["argv"])
