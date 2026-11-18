"""Claude Code metering (Milestone 2, 2026-11-12; D-021/D-025): model use the CLI never reported is unknown, never 0.
- `claude -p` reports usage only in its final JSON: a run it times out on, or that a signal kills, is marked unmetered; one that
  fails to start (an exit code, no output) spent nothing.
- A failed `claude -p` run still counts the usage its error result reports.
- A Claude Code session reports usage at each message's end: a turn cut off by its timeout is unmetered; a CLI that dies in
  the middle of a message is unmetered; one that dies between messages lost nothing.
- A restart marks Claude Code runs in flight unmetered (as Codex runs); API-key runs are not marked (G-43)."""
import os, queue, stat, tempfile, time, types, unittest
from unittest import mock

from app import agent_core, llm, terminal_bridge
from app.auth import AuthDB
from app.llm import LLMError

OWNER = 1


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(); self.addCleanup(self.dir.cleanup)
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        agent_core._core = None
        agent_core.init(self.db)
        self.addCleanup(lambda: (setattr(agent_core._local, "run", None), setattr(agent_core, "_core", None)))
        self.rid = agent_core.begin("teams", OWNER, "task", ref="mw:1")

    def row(self): return self.db.q("SELECT tokens, metering FROM ac_runs WHERE id=?", (self.rid,), one=True)

    def fake(self, body):
        exe = os.path.join(self.dir.name, "claude")
        with open(exe, "w") as f: f.write("#!/usr/bin/env python3\nimport sys, time, json\nsys.stdin.read()\n" + body + "\n")
        os.chmod(exe, os.stat(exe).st_mode | stat.S_IEXEC)
        was, llm.CLAUDE_CLI = llm.CLAUDE_CLI, exe
        self.addCleanup(lambda: setattr(llm, "CLAUDE_CLI", was))


class OneShot(Base):
    def test_a_timeout_is_unmetered_never_zero(self):
        self.fake("time.sleep(10)")
        with self.assertRaises(LLMError) as e: llm._cli_once("hi", timeout=.5)
        self.assertIn("timed out", str(e.exception))
        self.assertEqual(self.row(), {"tokens": 0, "metering": "unmetered"})

    def test_a_cli_killed_by_a_signal_is_unmetered(self):
        self.fake("import os, signal; os.kill(os.getpid(), signal.SIGKILL)")
        with self.assertRaises(LLMError): llm._cli_once("hi", timeout=10)
        self.assertEqual(self.row()["metering"], "unmetered")

    def test_a_cli_that_fails_to_start_spent_nothing(self):
        self.fake("print('config error', file=sys.stderr); sys.exit(2)")
        with self.assertRaises(LLMError): llm._cli_once("hi", timeout=10)
        self.assertIsNone(self.row()["metering"])

    def test_a_failed_run_counts_what_it_reports(self):
        self.fake('print(json.dumps({"is_error": True, "result": "Claude Code error: something broke", '
                  '"usage": {"input_tokens": 120, "output_tokens": 30, "cache_creation_input_tokens": 0}}))')
        with self.assertRaises(LLMError): llm._cli_once("hi", timeout=10)
        self.assertEqual(self.row(), {"tokens": 150, "metering": None})

    def test_a_good_run_is_metered(self):
        self.fake('print(json.dumps({"is_error": False, "result": "OK", "usage": {"input_tokens": 5, "output_tokens": 1}}))')
        self.assertEqual(llm._cli_once("hi", timeout=10)["result"], "OK")
        self.assertIsNone(self.row()["metering"])


class SessionTurn(Base):
    def session(self, *events, timeout=.3):
        s = terminal_bridge.Session.__new__(terminal_bridge.Session)
        q = queue.Queue()
        for e in events: q.put(e)
        s.box = types.SimpleNamespace(events=q, err=[], closed=True)  # closed: close() has nothing to stop
        s.timeout, s.held, s.proc = timeout, False, mock.Mock()
        def fail(msg, cli=False): raise LLMError(msg)
        s.fail = fail
        return s

    def test_a_turn_cut_off_by_its_timeout_is_unmetered(self):
        s = self.session()
        with self.assertRaises(LLMError): s.turn()
        s.proc.kill.assert_called_once()
        self.assertEqual(self.row()["metering"], "unmetered")

    def test_a_cli_that_dies_mid_message_is_unmetered(self):
        start = {"type": "stream_event", "event": {"type": "message_start", "message": {"usage": {"input_tokens": 900}}}}
        with self.assertRaises(LLMError): self.session(start, None).turn()
        self.assertEqual(self.row()["metering"], "unmetered")

    def test_a_cli_that_dies_between_messages_lost_nothing(self):
        with self.assertRaises(LLMError): self.session(None).turn()
        self.assertIsNone(self.row()["metering"])


class SessionTurnUnderALimit(SessionTurn):
    """Milestone 4: a Claude Code session turn (MCP mode) under a stopping limit reserves, and settles with its own messages' use."""
    def setUp(self):
        super().setUp()
        agent_core.get().set_limit(OWNER, "system", "teams", 1_000_000, period="day", label="roomy", origin="manual", by="test")

    def test_a_turn_settles_its_hold_with_its_own_use(self):
        start = {"type": "stream_event", "event": {"type": "message_start", "message": {"usage": {"input_tokens": 900}}}}
        delta = {"type": "stream_event", "event": {"type": "message_delta", "usage": {"output_tokens": 40}, "delta": {"stop_reason": "end_turn"}}}
        stop = {"type": "stream_event", "event": {"type": "message_stop"}}
        done = {"type": "result", "subtype": "success", "is_error": False, "result": "OK"}
        self.assertIsNone(agent_core.admit(model="terminal:sonnet"))
        out, why, tokens = self.session(start, delta, stop, done).turn()
        agent_core.used(tokens)
        h = self.db.q("SELECT state, estimate, reserved, actual FROM ac_reservations WHERE run_id=?", (self.rid,), one=True)
        self.assertEqual((tokens, h["state"], h["actual"]), (940, "settled", 940))
        self.assertEqual(self.row()["tokens"], 940)

    def test_a_turn_that_dies_mid_message_leaves_its_hold_unmetered(self):
        start = {"type": "stream_event", "event": {"type": "message_start", "message": {"usage": {"input_tokens": 900}}}}
        self.assertIsNone(agent_core.admit(model="terminal:sonnet"))
        with self.assertRaises(LLMError) as e: self.session(start, None).turn()
        agent_core.call_failed(e.exception)                                   # what llm._counted_call does
        h = self.db.q("SELECT state FROM ac_reservations WHERE run_id=?", (self.rid,), one=True)
        self.assertEqual(h["state"], "unmetered")


class Restart(unittest.TestCase):
    def test_cli_runs_in_flight_are_unmetered_api_runs_are_not(self):
        with tempfile.TemporaryDirectory() as d:
            db = AuthDB(os.path.join(d, "a.db"))
            agent_core._core = None
            agent_core.init(db)
            self.addCleanup(lambda: setattr(agent_core, "_core", None))
            ins = lambda model, login=None: db.q("INSERT INTO ac_runs (system, owner_id, kind, status, tokens, started, model, login) "
                                                 "VALUES ('teams',?,'task','running',40,?,?,?) RETURNING id", (OWNER, time.time(), model, login), one=True)["id"]
            codex, claude, own, api = ins("codex:gpt-6"), ins("terminal:opus"), ins(None, "user:4:terminal"), ins("anthropic:claude-opus")
            agent_core._core = None
            agent_core.init(db)                                              # the server restarts
            m = lambda i: db.q("SELECT status, metering FROM ac_runs WHERE id=?", (i,), one=True)
            for i in (codex, claude, own): self.assertEqual(m(i), {"status": "lost", "metering": "unmetered"})
            self.assertEqual(m(api), {"status": "lost", "metering": None})  # at most its one call in flight (G-43)


if __name__ == "__main__":
    unittest.main()
