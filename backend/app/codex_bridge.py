"""Codex provider, MCP mode: real tool calls through the Codex CLI, one `codex exec` session per agent run.

The Claude Code bridge (terminal_bridge.py) with Codex in place of `claude -p`: the CLI gets AXoR's tools as the same
stdio MCP server (terminal_bridge.py run as a script) and keeps the conversation, so tool calls are native, tool inputs
are real objects (no JSON-in-a-string), and turns after the first are prompt-cached. run_loop stays in charge: every
`complete()` returns one model turn, and tools run in run_loop with its own checks, spans, budgets and leases.

How Codex differs from Claude Code, which shapes this file (checked against codex-cli 0.162.1):
- Its stream doesn't show tool_use blocks before they run, so a tool call is announced by the MCP side: the socket
  handler puts it on the event queue as soon as Codex asks, then waits for run_loop's result. The id is Codex's
  `_meta.callId`.
- Codex calls MCP tools from "code mode" (a bare V8 runtime: no require, process, fetch or file access, only the tool
  bindings), so `code_mode_host` stays on here; text mode turns it off. Every other tool feature stays off, the sandbox
  is read-only and the folder is empty, as in text mode.
- MCP tools need approval by default and exec can't ask anyone: AXoR's server is pre-approved
  (`default_tools_approval_mode="approve"`). AXoR's own run_tool still decides what a call may do.
- Calls Codex makes at once reach the session together (the MCP server answers each on its own thread) and make one
  turn (SETTLE). Codex runs an MCP server's calls one after another unless the server is marked
  `supports_parallel_tool_calls` (checked 2026-11-18 on 0.162.1: three calls the model asked for together ran a→b→c,
  each a run_loop step of its own, with no model request in between), so AXoR's server is marked: they come as one turn.
  Usage is only reported when the run ends, so the whole run's tokens come with its last turn.

    run_loop ── complete() ──▶ CodexSession ◀── unix socket ── terminal_bridge.py (stdio MCP) ◀── codex exec
                                     └──────────── --json events ◀──────────────────────────────────┘
"""
import collections, itertools, json, os, queue, socketserver, subprocess, sys, tempfile, threading, time, weakref

from . import codex_cli, terminal_bridge
from .terminal_bridge import IDLE, _Box, _read, _stop

SETTLE = .3  # calls arriving within this of each other are one turn (the model made them at once)
DRAIN = 45    # drain(): how long a session left mid-run may take to close its turn and report its usage (D-021)
# codex_cli's flags, but with code mode on: it's how Codex calls MCP tools
FLAGS = ["exec", "--json", "--ephemeral", "--skip-git-repo-check", "--ignore-user-config", "--ignore-rules",
         "-s", "read-only", "-c", "web_search=disabled",
         *[x for f in codex_cli.FEATURES_OFF if f != "code_mode_host" for x in ("--disable", f)]]
GUIDE = ("\n\nYour tools are AXoR's (the mcp__axor__ tools); call them whenever you need data or to act. You have no "
         "shell, files or web of your own. When several tool calls don't depend on each other, make them at once."
         # Owner decision 2026-11-17: on Codex, SN61 agents read the read-only sandbox as "the workspace is read-only" and never
         # called file_write, then asked the user for write access they had
         "\nYour own sandbox is read-only and your folder is empty: that is only yours. AXoR's tools act on AXoR's side, so a "
         "tool of theirs that writes (file_write, for instance, when you have it) does write and its result says so. Use it to "
         "save your work; don't report that you can't write while you have such a tool.")
NO_HOST = ("Codex can't call tools on this server: its code-mode host (codex-code-mode-host, next to the codex CLI) is missing. "
           "The AXoR image includes it (rebuild it); meanwhile an administrator can set Codex's Tool calls to "
           "\"Written as text\" in Agents → Models.")
_ids = itertools.count(1)


def usage_tokens(e):
    return codex_cli.billed(e.get("usage"))  # without the cached input, as Claude Code's cache reads (Owner, 11-17)


def argv(exe, model, effort, instructions_file, sock):
    """The `codex exec` command line of one session; the prompt goes in on stdin."""
    py = sys.executable if os.path.basename(sys.executable).startswith("python") else "python3"
    a = [exe, *FLAGS, "-C", os.path.join(os.path.dirname(sock), "work"),
         "-c", f"model_instructions_file={json.dumps(instructions_file)}",
         "-c", f"model_reasoning_effort={json.dumps(effort if effort in ('low', 'medium', 'high') else 'medium')}",
         "-c", f"mcp_servers.axor.command={json.dumps(py)}",
         "-c", f"mcp_servers.axor.args={json.dumps(['-I', os.path.abspath(terminal_bridge.__file__), sock])}",
         "-c", f"mcp_servers.axor.tool_timeout_sec={IDLE}", "-c", "mcp_servers.axor.startup_timeout_sec=60",
         "-c", 'mcp_servers.axor.default_tools_approval_mode="approve"',
         # its calls may run at once: serve() answers each on its own thread, and run_loop runs them one by one anyway
         "-c", "mcp_servers.axor.supports_parallel_tool_calls=true"]
    if model and model != codex_cli.DEFAULT: a += ["-m", model]
    return [*a, "-"]


class CodexSession(terminal_bridge.Session):
    """One `codex exec` run serving one run_loop. turn() returns the next model turn as (blocks, stop, tokens);
    expects(), answer() and close() are the Claude Code session's."""

    def __init__(self, exe, env, model, effort, system, tools, prompt, timeout, gate, fail):
        self.timeout, self.gate, self.fail = timeout, gate, fail
        self.messages = None
        self.asked, self.held, self.back, self.error = set(), False, collections.deque(), None
        self.counted = False  # its usage was reported (turn.completed) and returned by turn() or drain()
        box = self.box = _Box(tools)
        self.dir = tempfile.mkdtemp(prefix="scout-codex-bridge-")
        os.chmod(self.dir, 0o700)
        sock = os.path.join(self.dir, "s")
        class Handler(socketserver.StreamRequestHandler):
            def handle(h):
                try: req = json.loads(h.rfile.readline() or "{}")
                except ValueError: return
                if req.get("op") == "tools": out = box.tool_list()
                else:  # announce the call to turn(), then wait for run_loop to run it
                    tid = str(req.get("id") or f"codex_call_{next(_ids)}")
                    box.events.put({"type": "_call", "id": tid, "name": req.get("name") or "", "input": req.get("args") or {}})
                    out = box.call(tid)
                h.wfile.write((json.dumps(out) + "\n").encode())
        self.server = socketserver.ThreadingUnixStreamServer(sock, Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        os.mkdir(os.path.join(self.dir, "work"))  # the agent's folder: empty, so no project files are in reach
        instructions = os.path.join(self.dir, "instructions.md")  # replaces Codex's own system prompt
        with open(instructions, "w") as f: f.write(system + GUIDE)
        self.gate.acquire()  # held while the model writes, released while tools run
        self.held = True
        try:
            self.proc = subprocess.Popen(argv(exe, model, effort, instructions, sock), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, text=True, cwd=os.path.join(self.dir, "work"), env=env)
        except OSError:
            self.proc = None; self.close(); raise
        self.proc.stdin.write(prompt); self.proc.stdin.close()
        threading.Thread(target=_read, args=(self.proc.stdout, box.events), daemon=True).start()
        threading.Thread(target=lambda f=self.proc.stderr, err=box.err: err.extend(f.read().splitlines()[-5:]), daemon=True).start()
        self._done = weakref.finalize(self, _stop, self.proc, self.server, self.dir, box)

    def drain(self, timeout=None):
        """Ends a session run_loop left before Codex finished its turn (the step limit, a session replaced, an error) without
        losing its tokens: Codex reports usage only at turn.completed, and killing it first lost the whole run's count (20 of
        90 Codex task runs, 11-09 to 11-11). Every waiting and later tool call is answered "the run ended", Codex closes its
        turn, and the usage it reports comes back. Returns the tokens, 0 when already counted, None when none came in time.
        The closing turn is a model turn, so it takes a slot of the login's runs-at-once gate like any other (Milestone 2: it ran
        outside the gate before), waiting up to the drain's time for it; the turn then gets that time again. No slot in time: the session is stopped without its closing turn and
        None comes back (unmetered, never 0), so the gate is never bypassed. No tool runs while it drains (box.close() answers every
        call "the run ended"); its tokens are counted, but the turn isn't checked against the budget first: it only closes work the
        budget already admitted, and skipping it would lose the whole run's usage."""
        if self.counted or getattr(self, "drained", False): return 0
        self.drained = True
        if (self.proc is None or self.proc.poll() is not None) and self.box.events.empty() and not self.back:
            if hasattr(self, "_done"): self._done()
            return None  # the CLI is gone and said nothing more: no usage will come
        wait = max(0, DRAIN if timeout is None else timeout)
        if not self.held:
            if not self.gate.acquire(timeout=wait):
                self.abort()  # no slot in time: stopped without a closing turn, so its usage is unknown
                return None
            self.held = True
        tokens, deadline = None, time.time() + wait  # the closing turn gets its own time once it holds a slot
        self.box.close()
        try:
            while self.proc is not None and time.time() < deadline:
                try: e = self._next(max(.1, deadline - time.time()))
                except queue.Empty: break
                if e is None: break
                if e.get("type") == "turn.completed":
                    tokens, self.counted = usage_tokens(e), True
                    break
        finally:
            if self.held: self.gate.release(); self.held = False
            if hasattr(self, "_done"): self._done()
        return tokens

    def abort(self):
        """Stops the session without a closing turn: Codex is killed first (closing the box first would answer its waiting tool
        call and let it start one). Its usage never comes: the caller marks the run unmetered."""
        self.drained = True
        if self.proc is not None and self.proc.poll() is None: self.proc.kill()
        if self.held: self.gate.release(); self.held = False
        if hasattr(self, "_done"): self._done()

    def _next(self, timeout):
        if self.back: return self.back.popleft()
        return self.box.events.get(timeout=timeout)

    def turn(self):
        """Reads events up to the next tool call(s) (or the end of the run)."""
        blocks, tokens, deadline = [], 0, time.time() + self.timeout
        try:
            while True:
                try: e = self._next(max(.1, deadline - time.time()))
                except queue.Empty:
                    self.proc.kill(); self.fail(f"Codex timed out after {self.timeout} s. Try again or lower the thinking effort.")
                if e is None:  # the CLI exited without finishing its turn
                    self.fail(self.error or (self.box.err[-1][:300] if self.box.err else "Codex ended without an answer."))
                t, item = e.get("type"), e.get("item") if isinstance(e.get("item"), dict) else {}
                if t == "_call":
                    blocks.append({"type": "tool_use", "id": e["id"], "name": e["name"], "input": e["input"] if isinstance(e["input"], dict) else {}})
                    while True:  # calls the model made at once arrive together: one turn
                        try: more = self.box.events.get(timeout=SETTLE)
                        except queue.Empty: break
                        if more and more.get("type") == "_call":
                            blocks.append({"type": "tool_use", "id": more["id"], "name": more["name"], "input": more["input"] if isinstance(more["input"], dict) else {}})
                        else:
                            self.back.append(more)
                            if more is None: break
                    break
                if t == "item.completed" and item.get("type") == "error" and "code mode is unavailable" in str(item.get("message")).lower():
                    # no code-mode host: every tool call would fail and the model would only say so; stop before it spends a turn
                    self.proc.kill()
                    raise codex_cli.llm.LLMError(NO_HOST)
                if t == "item.completed" and item.get("type") == "agent_message" and item.get("text"):
                    blocks.append({"type": "text", "text": item["text"]})
                elif t == "turn.completed":
                    tokens = usage_tokens(e)
                    self.counted = True
                    self.close()
                    break
                elif t == "turn.failed":
                    self.fail(str((e.get("error") or {}).get("message") or "unknown error"))
                elif t == "error":  # a stream error; reconnects say so too, so it only counts when the run never finishes
                    self.error = str(e.get("message") or "") or self.error
        except BaseException:
            self.close(); raise
        if self.held: self.gate.release(); self.held = False
        self.asked = {b["id"] for b in blocks if b["type"] == "tool_use"}
        if self.asked: return blocks, "tool_use", tokens
        return blocks, "end_turn", tokens
