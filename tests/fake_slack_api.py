"""Minimal Slack Web API for testing the Slack channel offline.
Token "xoxb-test-token-123" is valid (scopes below, sent in X-OAuth-Scopes); channel #mining (C0MINING01) has a
few messages and a thread; the bot starts outside it and joins via conversations.join. chat.postMessage stores
messages (with username and metadata) so they come back in history.
Run: python tests/fake_slack_api.py 8798  then start the app with SLACK_API_URL=http://127.0.0.1:8798/api"""
import json, sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

TOKEN = "xoxb-test-token-123"
SCOPES = "channels:history,channels:read,chat:write,users:read,channels:join,chat:write.customize"
USERS = {"U01ALICE": {"name": "alice", "profile": {"display_name": "Alice", "image_48": "https://example.com/a.png"}},
         "U02BOB": {"name": "bob", "profile": {"real_name": "Bob Miner", "image_48": "https://example.com/b.png"}}}
CHANNEL = {"id": "C0MINING01", "name": "mining", "is_private": False, "is_member": False, "topic": {"value": "Subnet mining chat"}}
now = time.time()
MESSAGES = [
    {"ts": f"{now - 7200:.6f}", "user": "U01ALICE", "text": "Morning! SN62 emission looks *up* today <https://taostats.io/subnets/62|chart>"},
    {"ts": f"{now - 3600:.6f}", "user": "U02BOB", "text": "Registered a new hotkey on SN5 &amp; it's earning &lt;3 hours in", "reply_count": 1},
    {"ts": f"{now - 600:.6f}", "user": "U01ALICE", "text": "<@U02BOB> nice, what GPU?"},
]
REPLIES = {MESSAGES[1]["ts"]: [{"ts": f"{now - 3000:.6f}", "user": "U01ALICE", "text": "Which validator weights you most?", "thread_ts": MESSAGES[1]["ts"]}]}
POSTS = []

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def reply(self, body):
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json"); self.send_header("X-OAuth-Scopes", SCOPES)
        self.send_header("content-length", str(len(raw))); self.end_headers(); self.wfile.write(raw)

    def handle_call(self, method, p):
        if self.headers.get("Authorization") != f"Bearer {TOKEN}": return self.reply({"ok": False, "error": "invalid_auth"})
        if method == "auth.test": return self.reply({"ok": True, "team": "Scout Test", "url": "https://scout-test.slack.com/", "user": "scoutbot", "user_id": "U0BOT"})
        if method == "conversations.list": return self.reply({"ok": True, "channels": [CHANNEL], "response_metadata": {"next_cursor": ""}})
        if method in ("conversations.info", "conversations.history", "conversations.replies", "chat.postMessage", "conversations.join") and p.get("channel") != CHANNEL["id"]:
            return self.reply({"ok": False, "error": "channel_not_found"})
        if method == "conversations.info": return self.reply({"ok": True, "channel": CHANNEL})
        if method == "conversations.join": CHANNEL["is_member"] = True; return self.reply({"ok": True, "channel": CHANNEL})
        if not CHANNEL["is_member"] and method in ("conversations.history", "chat.postMessage"): return self.reply({"ok": False, "error": "not_in_channel"})
        if method == "conversations.history":
            top = [m for m in MESSAGES if not m.get("thread_ts") or m["thread_ts"] == m["ts"]]
            return self.reply({"ok": True, "messages": sorted(top, key=lambda m: -float(m["ts"]))[:int(p.get("limit", 100))]})
        if method == "conversations.replies":
            parent = next((m for m in MESSAGES if m["ts"] == p.get("ts")), None)
            return self.reply({"ok": True, "messages": ([parent] if parent else []) + REPLIES.get(p.get("ts"), [])})
        if method == "users.info":
            u = USERS.get(p.get("user"))
            return self.reply({"ok": True, "user": {"id": p["user"], **u}} if u else {"ok": False, "error": "user_not_found"})
        if method == "chat.postMessage":
            POSTS.append(p)
            m = {"ts": f"{time.time():.6f}", "bot_id": "B0BOT", "text": p["text"], "bot_profile": {"name": "scoutbot"}}
            if p.get("username"): m["username"] = p["username"]
            if p.get("metadata"): m["metadata"] = p["metadata"]
            if p.get("thread_ts"):
                m["thread_ts"] = p["thread_ts"]; REPLIES.setdefault(p["thread_ts"], []).append(m)
                parent = next(x for x in MESSAGES if x["ts"] == p["thread_ts"]); parent["reply_count"] = parent.get("reply_count", 0) + 1
            else: MESSAGES.append(m)
            return self.reply({"ok": True, "ts": m["ts"], "channel": CHANNEL["id"]})
        self.reply({"ok": False, "error": "unknown_method"})

    def do_GET(self):
        u = urlparse(self.path)
        self.handle_call(u.path.rsplit("/", 1)[-1], {k: v[0] for k, v in parse_qs(u.query).items()})

    def do_POST(self):
        p = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
        self.handle_call(urlparse(self.path).path.rsplit("/", 1)[-1], p)

if __name__ == "__main__":
    HTTPServer(("0.0.0.0", int(sys.argv[1]) if len(sys.argv) > 1 else 8798), H).serve_forever()
