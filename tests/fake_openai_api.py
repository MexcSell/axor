"""Minimal OpenAI-compatible server (the API Ollama, LM Studio and vLLM expose), for testing OpenAI/local models offline.
GET /v1/models lists two models. POST /v1/chat/completions calls the first offered tool once, then summarizes its result;
with response_format it returns an agent draft. "plain-model" rejects reasoning_effort like a non-reasoning model does.
Hub agents: a user message containing "remember" makes it call the remember tool first, and when the system prompt
asks for [[suggest: …]] replies the final answer ends with one.
Run: python tests/fake_openai_api.py 8799  then connect http://127.0.0.1:8799/v1 as a local server."""
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

MODELS = ["llama3.1:8b", "plain-model"]

class H(BaseHTTPRequestHandler):
    def reply(self, code, body):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(raw))); self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.rstrip("/") != "/v1/models": return self.reply(404, {"error": {"message": "not found"}})
        self.reply(200, {"object": "list", "data": [{"id": m, "object": "model", "created": 1, "owned_by": "test"} for m in MODELS]})

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["content-length"])))
        H.calls.append(req)
        if req["model"] not in MODELS:
            return self.reply(404, {"error": {"message": f"model '{req['model']}' not found", "code": "model_not_found"}})
        if req["model"] == "plain-model" and "reasoning_effort" in req:
            return self.reply(400, {"error": {"message": "Unrecognized request argument supplied: reasoning_effort", "code": "unsupported_parameter"}})
        if req.get("response_format"):
            msg = {"role": "assistant", "content": "```json\n" + json.dumps({
                "name": "Lola", "role": "Local Analyst", "description": "I run on your own server.", "instructions": "Use market_overview.",
                "icon": "chip", "color": "slate", "skills": ["plain-language", "made-up"], "examples": ["How big is the network?"]}) + "\n```"}
            finish = "stop"
        elif req["messages"][-1]["role"] == "tool":
            data = json.loads(req["messages"][-1]["content"])
            text = "Local summary: " + ", ".join(f"{k}={v}" for k, v in data.items() if not isinstance(v, (dict, list)))
            if "[[suggest:" in (req["messages"][0].get("content") or ""): text += "\n[[suggest: Show the top 5 | What about SN62? | Thanks!]]"
            msg = {"role": "assistant", "content": text}
            finish = "stop"
        elif req.get("tools") and "remember" in str(req["messages"][-1].get("content", "")).lower() and any(t["function"]["name"] == "remember" for t in req["tools"]):
            msg = {"role": "assistant", "content": None, "tool_calls": [{"id": "call-mem", "type": "function", "function": {"name": "remember", "arguments": json.dumps({"fact": "Mines on one RTX 4090"})}}]}
            finish = "tool_calls"
        elif req.get("tools"):
            names = [t["function"]["name"] for t in req["tools"]]
            name = next((n for n in ("market_overview", "security_overview") if n in names), names[0])
            msg = {"role": "assistant", "content": None, "tool_calls": [{"id": "call 1!", "type": "function", "function": {"name": name, "arguments": "{}"}}]}
            finish = "stop"  # some local servers report "stop" even with tool calls
        else:
            msg, finish = {"role": "assistant", "content": "Hello from the local model."}, "stop"
        self.reply(200, {"id": "chatcmpl-1", "object": "chat.completion", "model": req["model"],
                         "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
                         "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}})

    def log_message(self, *a): pass

H.calls = []

if __name__ == "__main__":
    HTTPServer((sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1", int(sys.argv[1])), H).serve_forever()
