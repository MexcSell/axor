"""A small MCP server for tests (not a test itself): stdio by default, `--http PORT [--sse] [--token T]` for Streamable HTTP.

Tools: echo (read-only), write_note (no annotations: needs an admin's allow), boom (answers isError), slow (sleeps `seconds`),
big (a long text). Run it by hand too: `python tests/unit/fake_mcp.py --http 8899`.
"""
import json, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOOLS = [
    {"name": "echo", "description": "Repeat a text back.", "annotations": {"readOnlyHint": True, "title": "Echo"},
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "write_note", "description": "Save a note on the fake server.",
     "inputSchema": {"type": "object", "properties": {"note": {"type": "string"}}}},
    {"name": "boom", "description": "Always fails.", "annotations": {"readOnlyHint": True}, "inputSchema": {"type": "object", "properties": {}}},
    {"name": "slow", "description": "Waits.", "annotations": {"readOnlyHint": True},
     "inputSchema": {"type": "object", "properties": {"seconds": {"type": "number"}}}},
    {"name": "big", "description": "A long answer.", "annotations": {"readOnlyHint": True}, "inputSchema": {"type": "object", "properties": {}}},
]
NOTES = []

def handle(m):
    meth, mid, p = m.get("method"), m.get("id"), m.get("params") or {}
    if mid is None: return None  # a notification
    if meth == "initialize":
        r = {"protocolVersion": p.get("protocolVersion"), "capabilities": {"tools": {}}, "serverInfo": {"name": "fake-mcp", "version": "1.0"}}
    elif meth == "tools/list":
        r = {"tools": TOOLS}
    elif meth == "tools/call":
        name, a = p.get("name"), p.get("arguments") or {}
        if name == "echo": r = {"content": [{"type": "text", "text": f"echo: {a.get('text', '')}"}]}
        elif name == "write_note": NOTES.append(a.get("note")); r = {"content": [{"type": "text", "text": f"saved note {len(NOTES)}"}]}
        elif name == "boom": r = {"content": [{"type": "text", "text": "it broke"}], "isError": True}
        elif name == "slow": time.sleep(float(a.get("seconds") or 1)); r = {"content": [{"type": "text", "text": "done"}]}
        elif name == "big": r = {"content": [{"type": "text", "text": "x" * 50000}]}
        else: return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"Unknown tool {name}"}}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Unknown method {meth}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": r}

def stdio():
    for line in sys.stdin:
        if not line.strip(): continue
        out = handle(json.loads(line))
        if out: sys.stdout.write(json.dumps(out) + "\n"); sys.stdout.flush()

def http(port, sse=False, token=None):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_POST(self):
            if token and self.headers.get("Authorization") != f"Bearer {token}":
                self.send_response(401); self.end_headers(); return
            m = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            if m.get("method") != "initialize" and self.headers.get("Mcp-Session-Id") != "s-1":
                self.send_response(400); self.end_headers(); self.wfile.write(b"no session"); return
            out = handle(m)
            if out is None: self.send_response(202); self.end_headers(); return
            self.send_response(200)
            if m.get("method") == "initialize": self.send_header("Mcp-Session-Id", "s-1")
            if sse:
                self.send_header("Content-Type", "text/event-stream"); self.end_headers()
                self.wfile.write(b'event: message\ndata: {"jsonrpc":"2.0","method":"notifications/progress","params":{}}\n\n')
                self.wfile.write(f"event: message\ndata: {json.dumps(out)}\n\n".encode())
            else:
                body = json.dumps(out).encode()
                self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers()
                self.wfile.write(body)
        def do_DELETE(self): self.send_response(200); self.end_headers()
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    return srv

def serve_http_in_thread(sse=False, token=None):
    """For tests: a server on a free port; returns (server, url)."""
    srv = http(0, sse, token)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/mcp"

if __name__ == "__main__":
    if "--http" in sys.argv:
        a = sys.argv
        http(int(a[a.index("--http") + 1]), "--sse" in a, a[a.index("--token") + 1] if "--token" in a else None).serve_forever()
    else:
        stdio()
