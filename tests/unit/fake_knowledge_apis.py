"""A fake of the outside services the Knowledge Hub talks to (knowledge_media.py, knowledge_connectors.py), for unit tests
(in process: start()) and for running AXoR by hand (python fake_knowledge_apis.py PORT):

- POST /v1/embeddings: vectors from concept groups, so synonyms land close ("register" ~ "signup" ~ "enroll"), other words
  hashed; usage.total_tokens = the number of words.
- POST /v1/audio/transcriptions: a verbose_json transcript with two timed segments.
- Discord (/api/v10): users/@me (token "good-…" is a bot), channels/{id}, guilds/{id}, channels/{id}/messages with after/limit
  (newest first, as Discord answers).
- Telegram (/bot{token}/…): getMe, getUpdates with offset.
- POST /_add {platform, ...}: one more Discord message or Telegram update, to test incremental syncs.
"""
import hashlib, json, math, re, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

GROUPS = [{"register", "registration", "signup", "enroll", "enrollment", "enrol", "onboard"}, {"miner", "miners", "mining"}, {"validator", "validators", "checker", "verifier"},
          {"timeout", "timeouts", "delay", "latency", "slow"}, {"reward", "rewards", "emission", "emissions", "incentive"}]
DIM = 64
STATE = {"discord": [{"id": "101", "timestamp": "2026-11-01T10:00:00+00:00", "author": {"username": "dev1", "global_name": "Dev One"}, "content": "Cache embeddings for the miner"},
                     {"id": "102", "timestamp": "2026-11-01T10:05:00+00:00", "author": {"username": "dev2"}, "content": "Does it pass the validator?", "message_reference": {"message_id": "101"}},
                     {"id": "103", "timestamp": "2026-11-01T10:06:00+00:00", "author": {"username": "dev1"}, "content": "", "attachments": [{"filename": "bench.csv"}]}],
         "telegram": [{"update_id": 501, "message": {"message_id": 7, "date": 1762000000, "chat": {"id": -100, "title": "Mining chat", "type": "supergroup", "username": "miningchat"},
                                                      "from": {"username": "ann"}, "text": "Use fp16 for speed"}},
                      {"update_id": 502, "message": {"message_id": 8, "date": 1762000100, "chat": {"id": 42, "first_name": "Bo", "type": "private"},
                                                      "from": {"first_name": "Bo"}, "text": "Remember the reward curve", "reply_to_message": {"message_id": 3}}}]}


def vector(text):
    v = [0.0] * DIM
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        g = next((i for i, s in enumerate(GROUPS) if w in s), None)
        v[g if g is not None else len(GROUPS) + int(hashlib.md5(w.encode()).hexdigest(), 16) % (DIM - len(GROUPS))] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def _body(self):
        return self.rfile.read(int(self.headers.get("Content-Length") or 0))

    def do_POST(self):
        u = urlparse(self.path)
        if u.path.endswith("/embeddings"):
            b = json.loads(self._body())
            inp = b["input"] if isinstance(b["input"], list) else [b["input"]]
            return self._send(200, {"data": [{"index": i, "embedding": vector(t)} for i, t in enumerate(inp)], "usage": {"total_tokens": sum(len(t.split()) for t in inp)}})
        if u.path.endswith("/audio/transcriptions"):
            body = self._body()
            if b'name="file"' not in body: return self._send(400, {"error": {"message": "no file"}})
            return self._send(200, {"text": "Welcome to the miner briefing. Register the validator first.", "duration": 72.0, "language": "en",
                                    "segments": [{"start": 0.0, "end": 4.0, "text": " Welcome to the miner briefing."}, {"start": 65.0, "end": 70.0, "text": " Register the validator first."}]})
        if u.path == "/_add":
            b = json.loads(self._body())
            if b["platform"] == "discord": STATE["discord"].append(b["message"])
            else: STATE["telegram"].append(b["update"])
            return self._send(200, {"ok": True})
        self._send(404, {"message": "not found"})

    def do_GET(self):
        u, q = urlparse(self.path), parse_qs(urlparse(self.path).query)
        if u.path.startswith("/api/v10/"):
            if not (self.headers.get("Authorization") or "").startswith("Bot good-"): return self._send(401, {"message": "401: Unauthorized"})
            p = u.path[len("/api/v10"):]
            if p == "/users/@me": return self._send(200, {"id": "1", "username": "kbbot", "bot": True})
            if m := re.fullmatch(r"/guilds/(\d+)", p): return self._send(200, {"id": m.group(1), "name": "Bittensor"})
            if m := re.fullmatch(r"/channels/(\d+)", p):
                if m.group(1) == "404": return self._send(404, {"message": "Unknown Channel"})
                return self._send(200, {"id": m.group(1), "name": "sn62-dev", "guild_id": "9"})
            if m := re.fullmatch(r"/channels/(\d+)/messages", p):
                after = int((q.get("after") or ["0"])[0]); lim = int((q.get("limit") or ["50"])[0])
                msgs = [x for x in STATE["discord"] if int(x["id"]) > after]
                msgs = sorted(msgs, key=lambda x: int(x["id"]))[:lim] if after else sorted(msgs, key=lambda x: int(x["id"]))[-lim:]
                return self._send(200, sorted(msgs, key=lambda x: -int(x["id"])))
            return self._send(404, {"message": "Unknown"})
        if m := re.fullmatch(r"/bot([^/]+)/(getMe|getUpdates)", u.path):
            if not m.group(1).startswith("good-"): return self._send(401, {"ok": False, "description": "Unauthorized"})
            if m.group(2) == "getMe": return self._send(200, {"ok": True, "result": {"id": 5, "is_bot": True, "username": "kb_test_bot"}})
            off = int((q.get("offset") or ["0"])[0])
            return self._send(200, {"ok": True, "result": [x for x in STATE["telegram"] if x["update_id"] >= off][:int((q.get("limit") or ["100"])[0])]})
        self._send(404, {"message": "not found"})


def start(port=0):
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


if __name__ == "__main__":
    srv, url = start(int(sys.argv[1]) if len(sys.argv) > 1 else 8874)
    print("fake knowledge apis on", url, flush=True)
    threading.Event().wait()
