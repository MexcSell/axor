"""Owner decision 2026-11-17 (afternoon), the SN61 team's token waste (docs/engineering/OWNER_DECISIONS_2026-11-17_AGENT_ACCESS.md):
- a team run's turn may take 600 s (300 s before), and the work prompt says how to keep a turn short;
- a rerun is told the steps of the task's last run, so it goes on from there instead of starting over.
A turn cut off by the limit still fails its run (in-run retry needs D-036's provisional charge, not adopted)."""
import json, os, sys, unittest

from app import mining_work

sys.path.insert(0, os.path.dirname(__file__))
from test_orchestrator import G5  # noqa: E402

CUT = "Claude Code timed out after 600 s. Try again or lower the thinking effort."


class TurnLimit(unittest.TestCase):
    def test_the_turn_limit_and_the_prompt_rule(self):
        self.assertEqual(mining_work.TEAM_TURN_S, 600)
        self.assertIn("at most 600 seconds", mining_work.WORK_SYSTEM)
        self.assertIn("short script in sandbox_run", mining_work.WORK_SYSTEM)
        mining_work.WORK_SYSTEM.format(name="n", title="t", comp="c", netuid=61, subnet="s", job="j", team="", calls=24, rules="",
                                       sandbox="", followups=3, directive="")  # still formats with the same fields


class CodexCount(unittest.TestCase):
    """Owner decision 11-17 (evening): a Codex turn counts input and output without the cached input, as Claude Code's cache reads."""
    def test_cached_input_is_left_out(self):
        from unittest import mock
        from app import codex_bridge, codex_cli
        u = {"input_tokens": 20000, "cached_input_tokens": 18000, "output_tokens": 500, "reasoning_output_tokens": 300}
        self.assertEqual(codex_cli.billed(u), 2500)
        self.assertEqual(codex_bridge.usage_tokens({"type": "turn.completed", "usage": u}), 2500)  # MCP mode, the same count
        self.assertEqual(codex_cli.billed({"input_tokens": 100, "output_tokens": 20}), 120)  # no cache reported: all of it
        self.assertEqual(codex_cli.billed({"input_tokens": 10, "cached_input_tokens": 50, "output_tokens": 1}), 1)  # never below 0 input
        self.assertEqual(codex_cli.billed(None), 0)
        with mock.patch.object(codex_cli, "COUNT_CACHED", True): self.assertEqual(codex_cli.billed(u), 20500)  # CODEX_COUNT_CACHED=1

    def test_a_text_mode_run_counts_the_same(self):
        from app import codex_cli
        out = "\n".join(json.dumps(e) for e in (
            {"type": "item.completed", "item": {"type": "agent_message", "text": "Done."}},
            {"type": "turn.completed", "usage": {"input_tokens": 9000, "cached_input_tokens": 8000, "output_tokens": 100}}))
        self.assertEqual(codex_cli.parse(out, "", None), ("Done.", 1100))


class CodexWrites(unittest.TestCase):
    """Owner decision 11-17 (evening): Codex is told its read-only sandbox doesn't stop AXoR's writing tools."""
    def test_the_guide_says_axor_tools_write(self):
        from app import codex_bridge
        g = codex_bridge.GUIDE
        self.assertIn("Your own sandbox is read-only", g)
        self.assertIn("file_write", g)
        self.assertIn("don't report that you can't write", g)
        self.assertIn("-s", codex_bridge.FLAGS); self.assertIn("read-only", codex_bridge.FLAGS)  # Codex's own sandbox stays read-only


class TeamSteps(unittest.TestCase):
    """Owner "fix steps" (11-17 PM): a team task run gets TOOL_CALLS + 2 model turns; everything else keeps agents.MAX_STEPS."""
    def loop(self, max_steps=None, calls=40, submit_at=None):
        from app import agents
        n = [0]
        def complete(system, tools, messages):
            n[0] += 1
            if submit_at and n[0] == submit_at: return [{"type": "text", "text": "Filed."}], "end_turn", 1
            return [{"type": "tool_use", "id": f"c{n[0]}", "name": "x", "input": {"i": n[0]}}], "tool_use", 1  # one call a turn, as Codex
        msgs = [{"role": "user", "content": "go"}]
        agents.run_loop(complete, "s", [], msgs, lambda name, args: {"ok": args["i"]}, max_steps=max_steps)
        return n[0], msgs

    def test_the_limits(self):
        from app import agents
        self.assertEqual(agents.MAX_STEPS, 10)  # chats, missions: unchanged
        self.assertEqual(mining_work.TEAM_STEPS, mining_work.TOOL_CALLS + 2)
        self.assertEqual(mining_work.TEAM_STEPS, 26)

    def test_the_default_still_stops_at_ten_and_a_team_run_gets_its_own(self):
        self.assertEqual(self.loop()[0], 10)
        self.assertEqual(self.loop(max_steps=mining_work.TEAM_STEPS)[0], 26)

    def test_a_one_call_a_turn_run_files_within_the_team_limit(self):
        turns, msgs = self.loop(max_steps=mining_work.TEAM_STEPS, submit_at=mining_work.TOOL_CALLS + 1)  # 24 calls, then it files
        self.assertEqual(turns, 25)
        self.assertFalse(any(str(b.get("text", "")).startswith("I stopped after several steps") for m in msgs if m["role"] == "assistant"
                             for b in (m["content"] if isinstance(m["content"], list) else [])))

    def test_task_runs_pass_the_team_limit(self):
        import inspect
        src = inspect.getsource(mining_work.Work._loop)
        self.assertEqual(src.count("max_steps=TEAM_STEPS"), 2)  # the run and its one closing turn to file


class RerunNotes(G5):
    def setUp(self):
        super().setUp()
        q = self.db.q
        q("""CREATE TABLE mw_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, task_id INTEGER, agent_id INTEGER, kind TEXT,
             status TEXT, started REAL, finished REAL, tokens INTEGER, error TEXT)""")
        q("""CREATE TABLE mw_spans (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, ts REAL, "end" REAL, kind TEXT, name TEXT,
             input TEXT, output TEXT, tokens INTEGER, error INTEGER DEFAULT 0)""")
        self.w = mining_work.Work.__new__(mining_work.Work)
        self.w.db = self.db

    def mk_run(self, status, error=None, task=5, kind="task"):
        return self.db.q("INSERT INTO mw_runs (task_id, kind, status, error) VALUES (?,?,?,?) RETURNING id", (task, kind, status, error), one=True)["id"]

    def span(self, rid, kind, name, inp="", out="", error=0):
        self.db.q("INSERT INTO mw_spans (run_id, kind, name, input, output, error) VALUES (?,?,?,?,?,?)", (rid, kind, name, inp, out, error))

    def test_a_rerun_gets_the_steps_of_the_attempt_that_timed_out(self):
        r = self.mk_run("failed", CUT)
        self.span(r, "model", "fable", "1 message(s)", "Checking the pins first.\n→ sandbox_run")
        self.span(r, "tool", "sandbox_run", '{"command":"sha256sum -c tests/PINS.sha256"}', "selftest.sh: OK")
        self.span(r, "model", "fable", "3 message(s)", "→ file_write")
        self.span(r, "tool", "file_write", '{"path":"ops/PINS.sha256","content":"…"}', '{"ok":true}')
        self.span(r, "tool", "file_read", '{"path":"nope"}', "There's no nope", error=1)
        text = self.w._attempt(5, r + 1)
        self.assertIn(f"run #{r}) stopped before filing: {CUT}", text)
        self.assertIn("- you said: Checking the pins first.", text)
        self.assertIn('- sandbox_run {"command":"sha256sum -c tests/PINS.sha256"}\n  → selftest.sh: OK', text)
        self.assertIn("- file_write", text)
        self.assertIn("- file_read {\"path\":\"nope\"} (error)", text)
        self.assertNotIn("→ file_write", text)  # a step that only called tools says nothing of its own
        self.assertIn("don't repeat a step", text)

    def test_a_run_that_filed_gives_its_steps_too(self):
        r = self.mk_run("done")  # filed (a question, or work the Director sent back): its result goes in already; its steps now too
        self.span(r, "tool", "sandbox_run", "bash tests/selftest.sh", "EXIT=0")
        self.span(r, "tool", "submit_work", '{"outcome":"blocked"}', "filed")
        text = self.w._attempt(5, 99)
        self.assertIn(f"The steps your last run on this task (run #{r}) took before it filed", text)
        self.assertIn("- sandbox_run bash tests/selftest.sh\n  → EXIT=0", text)
        self.assertNotIn("submit_work", text)
        self.assertIn("unless the feedback or the answer calls for it", text)

    def test_nothing_without_steps(self):
        self.assertEqual(self.w._attempt(5, 99), "")  # a first run
        r = self.mk_run("done"); self.span(r, "model", "fable", "1", "I know this.\n→ submit_work"); self.span(r, "tool", "submit_work", "{}", "filed")
        self.assertEqual(self.w._attempt(5, 99), "")  # it filed without a step of its own

    def test_an_attempt_that_did_nothing_is_skipped_for_the_one_before(self):
        r1 = self.mk_run("failed", CUT); self.span(r1, "tool", "sandbox_run", "ls", "a b")
        self.mk_run("failed", "Over the team token budget")  # refused before any step
        text = self.w._attempt(5, 99)
        self.assertIn(f"run #{r1})", text)
        self.assertIn("- sandbox_run ls", text)

    def test_other_tasks_reviews_and_later_runs_are_not_mixed_in(self):
        o = self.mk_run("failed", CUT, task=6); self.span(o, "tool", "sandbox_run", "other", "x")
        rv = self.mk_run("failed", "review failed", kind="review"); self.span(rv, "tool", "notebook", "rv", "x")
        self.assertEqual(self.w._attempt(5, 99), "")
        r = self.mk_run("failed", CUT); self.span(r, "tool", "sandbox_run", "mine", "x")
        later = self.mk_run("failed", CUT); self.span(later, "tool", "sandbox_run", "later", "x")
        self.assertIn("mine", self.w._attempt(5, later))
        self.assertNotIn("later", self.w._attempt(5, later))  # the run being started isn't its own last attempt

    def test_a_long_attempt_keeps_its_latest_steps_within_the_cap(self):
        r = self.mk_run("failed", CUT)
        for i in range(40): self.span(r, "tool", "sandbox_run", f"step {i:02d} " + "x" * 280, "o" * 590)
        text = self.w._attempt(5, 99)
        self.assertIn("(earlier steps left out)", text)
        self.assertIn("step 39", text)
        self.assertNotIn("step 00", text)
        self.assertLess(len(text), mining_work.ATTEMPT_CHARS + 1000)

    def test_the_task_prompt_carries_the_notes(self):
        from unittest import mock
        from app.mining import Cancelled
        q = self.db.q
        q("""CREATE TABLE mw_tasks (id INTEGER PRIMARY KEY, comp_id INTEGER, title TEXT, detail TEXT, status TEXT, priority TEXT, due TEXT,
             agent_id INTEGER, result TEXT, feedback TEXT, question TEXT, note TEXT, fails INTEGER DEFAULT 0, hold TEXT, updated REAL)""")
        q("CREATE TABLE mw_agents (id INTEGER PRIMARY KEY, comp_id INTEGER, name TEXT, title TEXT, job TEXT, head INTEGER, lead INTEGER)")
        q("INSERT INTO mw_agents VALUES (2, 4, 'Devon', 'Engineer', 'Builds', 0, 0)")
        q("""INSERT INTO mw_tasks (id, comp_id, title, status, priority, due, agent_id, result, feedback, question)
             VALUES (5, 4, 'Consolidate the release gates', 'working', 'high', '', 2, 'Wrote 1 of 4 files.', 'Write the rest.', 'Shall I go on?')""")
        r = self.mk_run("done"); self.span(r, "tool", "sandbox_run", "sha256sum -c tests/PINS.sha256", "OK")
        now = self.mk_run("running")
        w, seen = self.w, []
        w.m = mock.Mock(); w.m._campaign.return_value = {"user_id": 7, "netuid": 61}; w.m._title.return_value = "SN61"
        w._comp = lambda wid: {"id": wid, "campaign_id": 1}
        w._model = lambda c, a, kind=None: "terminal:fable"
        w._over = lambda wc: False
        w._event = w._end = w._kick = lambda *a, **k: None
        w._context = lambda wc, c: ("Context.", None)
        w.sbx = mock.Mock(); w.sbx.ready.return_value = (True,)
        w._team = w._rules = w._directive = w._label = w._recall = lambda *a: ""
        w.loop = None
        def loop(c, rep, wc, a, rid, model, system, prompt, tid, box):
            seen.append(prompt); raise Cancelled()
        w._loop = loop
        w._work(5, now)
        prompt = seen[0]
        self.assertIn("Your last result on it:\nWrote 1 of 4 files.", prompt)
        self.assertIn(f"The steps your last run on this task (run #{r})", prompt)
        self.assertLess(prompt.index("The answer: Write the rest."), prompt.index("The steps your last run"))
        self.assertIn("- sandbox_run sha256sum -c tests/PINS.sha256\n  → OK", prompt)
        q("DROP TABLE mw_spans")  # the notes fail: the run goes on without them
        seen.clear(); q("UPDATE mw_tasks SET status='working' WHERE id=5")
        with self.assertLogs("mining.work", "WARNING"): w._work(5, self.mk_run("running"))
        self.assertEqual(len(seen), 1)
        self.assertNotIn("The steps your last run", seen[0])

if __name__ == "__main__":
    unittest.main()
