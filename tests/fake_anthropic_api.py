"""Minimal stand-in for api.anthropic.com's /v1/models, for testing API-key verification offline.
Accepts keys starting with sk-ant-good; everything else gets the API's 401 shape.
Run: python tests/fake_anthropic_api.py 8798  and set ANTHROPIC_BASE_URL=http://127.0.0.1:8798"""
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        ok = (self.headers.get("x-api-key") or "").startswith("sk-ant-good")
        body = ({"data": [{"type": "model", "id": "claude-opus-5-5", "display_name": "Claude Opus 5.5", "created_at": "2026-09-01T00:00:00Z"}],
                 "has_more": False, "first_id": "claude-opus-5-5", "last_id": "claude-opus-5-5"} if ok else
                {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}})
        raw = json.dumps(body).encode()
        self.send_response(200 if ok else 401)
        self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(raw))); self.end_headers()
        self.wfile.write(raw)
    def log_message(self, *a): pass

if __name__ == "__main__":
    HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
