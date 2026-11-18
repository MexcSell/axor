"""Minimal OpenRouter API for testing Connectors (key management) offline.
"sk-or-v1-mgmt-test-0123456789abcdef" is a management key; "sk-or-v1-agent-0123456789abcdef" is a regular key, the one
AXoR's agents would use (it's in the list as "AXoR agents"), and gets 403 on the management routes like the real API.
Keys can be listed (in pages of 2, to exercise offset), created, edited, disabled and deleted; /credits answers too.
Run: python tests/fake_openrouter_api.py 8798  then start the app with OPENROUTER_BASE_URL=http://127.0.0.1:8798/api/v1"""
import json, secrets, sys, time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

MGMT = "sk-or-v1-mgmt-test-0123456789abcdef"
AGENT = "sk-or-v1-agent-0123456789abcdef"
iso = lambda ago: datetime.fromtimestamp(time.time() - ago, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
label = lambda k: f"{k[:11]}...{k[-4:]}"

def key(name, raw, usage, limit=None, reset=None, disabled=False, ago=86400 * 20):
    return {"hash": secrets.token_hex(32), "name": name, "label": label(raw), "disabled": disabled, "limit": limit,
            "limit_remaining": None if limit is None else max(0, limit - usage), "limit_reset": reset, "include_byok_in_limit": False,
            "usage": usage, "usage_daily": round(usage * .04, 4), "usage_weekly": round(usage * .2, 4), "usage_monthly": round(usage * .6, 4),
            "byok_usage": 0, "byok_usage_daily": 0, "byok_usage_weekly": 0, "byok_usage_monthly": 0,
            "created_at": iso(ago), "updated_at": None, "last_used_at": iso(300), "expires_at": None, "workspace_id": "default"}

KEYS = [key("AXoR agents", AGENT, 12.3456, 50, "monthly"), key("Research notebook", "sk-or-v1-research-aaaabbbbcccc", 3.21),
        key("Old CI key", "sk-or-v1-oldci-ddddeeeeffff", 0.5, disabled=True, ago=86400 * 90)]

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def send(self, code, body):
        b = json.dumps(body).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers()
        self.wfile.write(b)

    def route(self, method):
        u = urlparse(self.path); p = u.path.removeprefix("/api/v1"); q = parse_qs(u.query)
        tok = self.headers.get("Authorization", "").removeprefix("Bearer ")
        if tok not in (MGMT, AGENT): return self.send(401, {"error": {"code": 401, "message": "Invalid API key"}})
        if p == "/key" and method == "GET":
            k = next((k for k in KEYS if k["label"] == label(tok)), None)
            return self.send(200, {"data": {**(k or {}), "label": label(tok), "is_management_key": tok == MGMT}})
        if p == "/models": return self.send(200, {"data": [{"id": "google/gemini-2.5-pro", "name": "Gemini 2.5 Pro", "created": 1}]})
        if p in ("/chat/completions", "/embeddings") and method == "POST":  # Mining HQ's sandbox proxy: a canned answer at 0.01 USD a call
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            usage = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120, **({"cost": 0.01} if (body.get("usage") or {}).get("include") else {})}
            if p == "/embeddings": return self.send(200, {"data": [{"embedding": [0.1, 0.2, 0.3], "index": 0}], "model": body.get("model"), "usage": usage})
            return self.send(200, {"id": "gen-test", "model": body.get("model"), "usage": usage,
                                   "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "SELECT 1;"}}]})
        if tok != MGMT: return self.send(403, {"error": {"code": 403, "message": "Only management keys can perform this operation"}})
        if p == "/credits": return self.send(200, {"data": {"total_credits": 100, "total_usage": sum(k["usage"] for k in KEYS)}})
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}") if method in ("POST", "PATCH") else {}
        if p == "/keys" and method == "GET":
            off = int(q.get("offset", ["0"])[0])
            rows = [k for k in KEYS if k["disabled"] is False or q.get("include_disabled") == ["true"]]
            return self.send(200, {"data": rows[off:off + 2]})
        if p == "/keys" and method == "POST":
            if not body.get("name"): return self.send(400, {"error": {"code": 400, "message": "name is required"}})
            raw = "sk-or-v1-" + secrets.token_hex(32)
            k = key(body["name"], raw, 0, body.get("limit"), body.get("limit_reset"), ago=0)
            k.update(include_byok_in_limit=bool(body.get("include_byok_in_limit")), expires_at=body.get("expires_at"), last_used_at=None)
            KEYS.append(k)
            return self.send(201, {"data": k, "key": raw})
        k = next((k for k in KEYS if p == f"/keys/{k['hash']}"), None)
        if not k: return self.send(404, {"error": {"code": 404, "message": "Not found"}})
        if method == "GET": return self.send(200, {"data": k})
        if method == "DELETE": KEYS.remove(k); return self.send(200, {"deleted": True})
        if method == "PATCH":
            fields = {f: body[f] for f in ("name", "disabled", "limit", "limit_reset", "include_byok_in_limit") if f in body}
            if not fields: return self.send(400, {"error": {"code": 400, "message": "No update fields provided"}})
            k.update(fields, updated_at=iso(0))
            k["limit_remaining"] = None if k["limit"] is None else max(0, k["limit"] - k["usage"])
            return self.send(200, {"data": k})
        self.send(405, {"error": {"code": 405, "message": "Method not allowed"}})

    def do_GET(self): self.route("GET")
    def do_POST(self): self.route("POST")
    def do_PATCH(self): self.route("PATCH")
    def do_DELETE(self): self.route("DELETE")

if __name__ == "__main__":
    HTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8798), H).serve_forever()
