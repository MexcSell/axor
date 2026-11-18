"""Terminal provider, MCP mode: real tool calls through Claude Code, one CLI session per agent run.

The CLI gets AXoR's tools as an MCP server (this file, run as a script) and keeps the conversation, so tool calls are
native and turns after the first are prompt-cached. AXoR's run loop stays in charge: every `complete()` returns one
model turn. When the model calls a tool, the CLI asks the MCP server, which asks the session over a unix socket and
waits; run_loop runs the tool with its own run_tool (checks, spans, budgets, leases as before) and the next
`complete()` hands the result back, which lets the CLI go on to the next turn.

    run_loop ── complete() ──▶ Session ◀── unix socket ── this file (stdio MCP server) ◀── claude -p
                                  └──────────── stream-json turns ◀───────────────────────────┘

Only the stdlib is used, so the script runs with `python3 -I` wherever the CLI runs.
"""
import json, os, queue, shutil, socket, socketserver, subprocess, sys, tempfile, threading, time, weakref

PREFIX = "mcp__axor__"
IDLE = int(os.getenv("TERMINAL_BRIDGE_IDLE", "3600"))  # a tool call waiting this long for run_loop: the run was dropped
FLAGS = ["-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages", "--restricted", "--setting-sources", "",
         "--strict-mcp-config", "--tools", "", "--allowedTools", PREFIX + "*", "--disable-slash-commands", "--no-session-persistence"]
# not --safe-mode: it also drops --mcp-config servers. --restricted with no setting sources keeps settings and hooks out,
# --disable-slash-commands the host's skills and commands, and --tools "" every built-in tool; tested with CLI 2.1.310.
# counted as an API call is (llm._billed): input, cache writes and output. Cache reads were counted too until 11-11: every turn of a
# session re-reads its whole context from the cache, so a long run showed many times the tokens the same work counts through the API
# and went far past a team budget set in billed tokens. CLI_COUNT_CACHE_READS=1 restores the old count.
USAGE = ("input_tokens", "cache_creation_input_tokens", "output_tokens") + (("cache_read_input_tokens",) if os.getenv("CLI_COUNT_CACHE_READS", "0") == "1" else ())


# ---------- the MCP server, started by the CLI ----------
def _ask(path, req):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.connect(path)
        s.sendall((json.dumps(req) + "\n").encode())
        f = s.makefile("r", encoding="utf-8")
        return json.loads(f.readline() or "{}")

def serve(path):
    """Stdio MCP server: newline-delimited JSON-RPC. tools/list and tools/call are forwarded to the session. Each
    tools/call is answered on its own thread, so calls the model makes at once all reach the session (JSON-RPC
    responses can come in any order; the CLI matches them by id)."""
    out = threading.Lock()
    def send(o):
        with out: sys.stdout.write(json.dumps(o) + "\n"); sys.stdout.flush()
    def handle(meth, i, p):
        try:
            if meth == "initialize":
                r = {"protocolVersion": p.get("protocolVersion"), "capabilities": {"tools": {}}, "serverInfo": {"name": "axor", "version": "1"}}
            elif meth == "tools/list":
                r = {"tools": _ask(path, {"op": "tools"}).get("tools", [])}
            elif meth == "tools/call":
                meta = p.get("_meta") or {}  # Claude Code names its tool_use id; Codex sends its own call id (codex_bridge.py)
                a = _ask(path, {"op": "call", "id": meta.get("claudecode/toolUseId") or meta.get("callId"), "name": p.get("name"),
                                "args": p.get("arguments") or {}})
                r = {"content": [{"type": "text", "text": a.get("content", "")}], "isError": bool(a.get("is_error"))}
            else:
                send({"jsonrpc": "2.0", "id": i, "error": {"code": -32601, "message": f"Unknown method {meth}"}}); return
        except OSError as e:
            r = {"content": [{"type": "text", "text": f"AXoR is unreachable: {e}"}], "isError": True}
        send({"jsonrpc": "2.0", "id": i, "result": r})
    for line in sys.stdin:
        try: m = json.loads(line)
        except ValueError: continue
        meth, i = m.get("method"), m.get("id")
        if i is None: continue  # notifications
        args = (meth, i, m.get("params") or {})
        if meth == "tools/call": threading.Thread(target=handle, args=args, daemon=True).start()
        else: handle(*args)


# ---------- the session, inside AXoR ----------
class _Box:
    """State shared with the socket and reader threads: the tools, the stream, and tool results waiting to go back."""
    def __init__(self, tools):
        self.tools, self.results, self.closed, self.err = tools, {}, False, []
        self.events, self.cv = queue.Queue(), threading.Condition()

    def tool_list(self):
        return {"tools": [{"name": t["name"], "description": t["description"], "inputSchema": t["input_schema"]} for t in self.tools]}

    def call(self, tid):
        """Waits for run_loop to run the tool call `tid` (the CLI's tool_use id) and hands back its result."""
        with self.cv:
            if not self.cv.wait_for(lambda: tid in self.results or self.closed, timeout=IDLE) or tid not in self.results:
                return {"content": "The run ended before this tool ran.", "is_error": True}
            return self.results.pop(tid)

    def answer(self, results):
        with self.cv: self.results.update(results); self.cv.notify_all()

    def close(self):
        with self.cv: self.closed = True; self.cv.notify_all()

def _read(f, events):
    for line in f:
        try: events.put(json.loads(line))
        except ValueError: pass
    events.put(None)

def _unmetered(why):
    """This thread's run has model use no usage was reported for (D-021, Milestone 2): unknown, never 0."""
    from . import agent_core  # here: agent_core imports llm, which imports this module
    agent_core.unmetered(f"{why} before reporting its usage: this run's tokens are unknown.")

def _stop(proc, server, d, box):
    box.close()
    if proc and proc.poll() is None: proc.kill()
    server.shutdown(); server.server_close()
    shutil.rmtree(d, ignore_errors=True)

class Session:
    """One `claude -p` run serving one run_loop. turn() returns the next model turn as (blocks, stop, tokens)."""

    def __init__(self, exe, env, model, effort, system, tools, prompt, timeout, gate, fail):
        self.timeout, self.gate, self.fail = timeout, gate, fail
        self.messages = None  # run_loop's list, set by the completer
        self.asked, self.held = set(), False
        # what the socket and reader threads touch; they never hold the session, so a run that's dropped mid-way
        # (an exception in run_tool, MAX_STEPS) frees it, and the finalizer stops the CLI
        box = self.box = _Box(tools)
        self.dir = tempfile.mkdtemp(prefix="scout-bridge-")
        os.chmod(self.dir, 0o700)
        sock = os.path.join(self.dir, "s")
        class Handler(socketserver.StreamRequestHandler):
            def handle(h):
                try: req = json.loads(h.rfile.readline() or "{}")
                except ValueError: return
                h.wfile.write((json.dumps(box.tool_list() if req.get("op") == "tools" else box.call(req.get("id"))) + "\n").encode())
        self.server = socketserver.ThreadingUnixStreamServer(sock, Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        cfg = os.path.join(self.dir, "mcp.json")
        with open(cfg, "w") as f:
            json.dump({"mcpServers": {"axor": {"command": sys.executable if os.path.basename(sys.executable).startswith("python") else "python3",
                                               "args": ["-I", os.path.abspath(__file__), sock]}}}, f)
        cwd = os.path.join(self.dir, "work")  # an empty folder, so no project files are in reach
        os.mkdir(cwd)
        env = {**env, "MCP_TOOL_TIMEOUT": str(IDLE * 1000), "MAX_MCP_OUTPUT_TOKENS": "50000"}
        self.gate.acquire()  # held while the model writes a turn, released while tools run
        self.held = True
        try:
            self.proc = subprocess.Popen([exe, *FLAGS, "--mcp-config", cfg, "--system-prompt", system, "--model", model, "--effort", effort],
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=cwd, env=env)
        except OSError:
            self.proc = None; self.close(); raise
        self.proc.stdin.write(prompt); self.proc.stdin.close()
        threading.Thread(target=_read, args=(self.proc.stdout, box.events), daemon=True).start()
        threading.Thread(target=lambda f=self.proc.stderr, err=box.err: err.extend(f.read().splitlines()[-5:]), daemon=True).start()
        self._done = weakref.finalize(self, _stop, self.proc, self.server, self.dir, box)

    def close(self):
        if self.held: self.gate.release(); self.held = False
        if self.box.closed: return
        if self.proc and self.proc.poll() is None:
            self.box.close()  # a tool call still waiting gets an error, and the CLI can finish
            try: self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired: pass
        if hasattr(self, "_done"): self._done()  # runs _stop once, and not again when the session is freed
        else: _stop(self.proc, self.server, self.dir, self.box)

    # run_loop side
    def expects(self, messages):
        """True when `messages` is this session's run and ends with results for the calls the model is waiting on."""
        if self.box.closed or messages is not self.messages or not messages or messages[-1]["role"] != "user": return False
        ids = [b.get("tool_use_id") for b in messages[-1]["content"] if isinstance(b, dict) and b.get("type") == "tool_result"] \
            if isinstance(messages[-1]["content"], list) else []
        return bool(ids) and set(ids) == self.asked

    def answer(self, messages):
        self.gate.acquire(); self.held = True
        self.box.answer({b["tool_use_id"]: {"content": b["content"] if isinstance(b.get("content"), str) else json.dumps(b.get("content")),
                                            "is_error": bool(b.get("is_error"))}
                         for b in messages[-1]["content"] if b.get("type") == "tool_result"})

    def turn(self):
        """Reads the stream up to the end of the next assistant message (or of the run)."""
        blocks, stop, tokens, usage, deadline = {}, None, 0, {}, time.time() + self.timeout
        try:
            while True:
                try: e = self.box.events.get(timeout=max(.1, deadline - time.time()))
                except queue.Empty:
                    # Milestone 2: usage arrives per message (message_stop); a turn cut off by the timeout had a request out: unknown
                    self.proc.kill(); _unmetered("Claude Code timed out mid-turn")
                    self.fail(f"Claude Code timed out after {self.timeout} s. Try again or lower the thinking effort.")
                if e is None:
                    if usage: _unmetered("Claude Code stopped mid-message")  # a message started and never reported its end
                    self.fail("Claude Code failed" + (": " + self.box.err[-1][:300] if self.box.err else "") + ".")
                t = e.get("type")
                if t == "assistant":
                    for b in e["message"].get("content") or []:
                        if b.get("type") == "text" and b.get("text"): blocks[len(blocks)] = {"type": "text", "text": b["text"]}
                        elif b.get("type") == "tool_use":
                            n = b["name"][len(PREFIX):] if b["name"].startswith(PREFIX) else b["name"]
                            blocks[len(blocks)] = {"type": "tool_use", "id": b["id"], "name": n, "input": b.get("input") or {}}
                elif t == "stream_event":
                    ev = e.get("event") or {}
                    # message_delta repeats message_start's counts as running totals: keep one record per message
                    if ev.get("type") == "message_start": usage = dict((ev.get("message") or {}).get("usage") or {})
                    if ev.get("type") == "message_delta":
                        usage.update({k: v for k, v in (ev.get("usage") or {}).items() if v is not None})
                        stop = (ev.get("delta") or {}).get("stop_reason") or stop
                    if ev.get("type") == "message_stop":
                        tokens += sum(usage.get(k) or 0 for k in USAGE); usage = {}
                        if any(b["type"] == "tool_use" for b in blocks.values()): break  # the model is waiting on its tool calls
                elif t == "result":
                    if e.get("is_error") or e.get("subtype") != "success":
                        self.fail(str(e.get("result") or e.get("terminal_reason") or e.get("subtype") or "unknown error"), cli=True)
                    if not blocks and e.get("result"): blocks[0] = {"type": "text", "text": e["result"]}
                    self.close()
                    break
        except BaseException:
            self.close(); raise
        if self.held: self.gate.release(); self.held = False
        out = list(blocks.values())
        self.asked = {b["id"] for b in out if b["type"] == "tool_use"}
        if self.asked: return out, "tool_use", tokens
        return out, stop if stop in ("refusal", "max_tokens") else "end_turn", tokens


if __name__ == "__main__":
    serve(sys.argv[1])
