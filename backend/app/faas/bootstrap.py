"""AXoR Functions runtime for Python: serves the function in /code/main.py over HTTP on PORT.

The handler gets one argument, the request as a dict (method, path, query, headers, body, json, client, context) and
returns the response: a str (text/plain), bytes, a dict or list (JSON), a (body, status) or (body, status, headers)
tuple, or {"statusCode": …, "headers": {…}, "body": …}. Calls longer than FN_TIMEOUT seconds get 504, uncaught
errors 500 with the traceback in the logs. Each call logs one JSON line ({"axor": "call", …}) the Functions page
counts. GET /__axor/health is answered here, for the readiness check.
"""
import importlib.util, json, os, sys, threading, time, traceback, urllib.parse, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

NAME, HANDLER = os.environ.get("FN_NAME", "function"), os.environ.get("FN_HANDLER", "handle")
TIMEOUT, PORT, MAX_BODY = float(os.environ.get("FN_TIMEOUT", "30")), int(os.environ.get("PORT", "8080")), 6 * 2**20

sys.path[:0] = ["/code", "/deps"]
spec = importlib.util.spec_from_file_location("main", "/code/main.py")
main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(main)
fn = getattr(main, HANDLER, None)
if not callable(fn): sys.exit(f"main.py has no function named {HANDLER!r}.")

def response(r):
    """(status, headers, body bytes) from whatever the handler returned."""
    status, headers = 200, {}
    if isinstance(r, tuple):
        r, status, headers = (list(r) + [200, {}])[:3]
    elif isinstance(r, dict) and "body" in r and ("statusCode" in r or "status" in r):
        status, headers, r = r.get("statusCode", r.get("status", 200)), r.get("headers") or {}, r["body"]
    headers = {str(k): str(v) for k, v in (headers or {}).items()}
    if r is None: return int(status), headers, b""
    if isinstance(r, (bytes, bytearray)): headers.setdefault("Content-Type", "application/octet-stream"); return int(status), headers, bytes(r)
    if isinstance(r, str): headers.setdefault("Content-Type", "text/plain; charset=utf-8"); return int(status), headers, r.encode()
    headers.setdefault("Content-Type", "application/json")
    return int(status), headers, json.dumps(r, default=str).encode()

class Handler(BaseHTTPRequestHandler):
    server_version, sys_version, protocol_version = "axor-fn", "", "HTTP/1.1"

    def log_message(self, *a): pass

    def send(self, status, headers, body):
        self.send_response(status)
        for k, v in headers.items(): self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD": self.wfile.write(body)

    def serve(self):
        u = urllib.parse.urlsplit(self.path)
        if u.path == "/__axor/health": return self.send(200, {"Content-Type": "text/plain"}, b"ok")
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY: return self.send(413, {"Content-Type": "text/plain"}, b"Request body too large (6 MB at most).")
        raw = self.rfile.read(n) if n else b""
        body = raw.decode("utf-8", "replace")
        try: data = json.loads(body) if body and "json" in (self.headers.get("Content-Type") or "") else None
        except ValueError: data = None
        rid = self.headers.get("X-Request-Id") or uuid.uuid4().hex[:16]
        event = {"method": self.command, "path": u.path, "query": {k: v[0] if len(v) == 1 else v for k, v in urllib.parse.parse_qs(u.query).items()},
                 "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body, "json": data,
                 "client": (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip(),
                 "context": {"function": NAME, "request_id": rid, "timeout": TIMEOUT}}
        out, t0 = {}, time.monotonic()
        def run():
            try: out["r"] = fn(event)
            except BaseException as e:  # noqa: BLE001 - the function's own error: log it and answer 500
                out["e"] = e; traceback.print_exc()
        t = threading.Thread(target=run, daemon=True); t.start(); t.join(TIMEOUT)
        if t.is_alive(): status, headers, payload = 504, {"Content-Type": "text/plain"}, f"{NAME} took longer than {TIMEOUT:g}s.".encode()
        elif "e" in out: status, headers, payload = 500, {"Content-Type": "text/plain"}, f"{type(out['e']).__name__}: {out['e']}".encode()
        else:
            try: status, headers, payload = response(out.get("r"))
            except Exception as e:  # noqa: BLE001
                status, headers, payload = 500, {"Content-Type": "text/plain"}, f"The handler's return value can't be sent: {e}".encode()
        ms = round((time.monotonic() - t0) * 1000, 1)
        headers.setdefault("X-Request-Id", rid)
        self.send(status, headers, payload)
        print(json.dumps({"axor": "call", "id": rid, "method": self.command, "path": u.path, "status": status, "ms": ms}), flush=True)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_HEAD = serve

print(json.dumps({"axor": "start", "function": NAME, "handler": HANDLER, "port": PORT}), flush=True)
ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
