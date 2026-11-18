"""A stand-in for ridges.ai's competitions page (backend/app/ridges.py reads it): the same Next.js flight chunks, with
competitions 30, 29 and 28 open (50/25/25% of emissions) and 27 ended. GET /_close/<n> ends one, GET /_open/<n> opens a new one.

    python tests/fake_ridges.py 8796      then RIDGES_URL=http://127.0.0.1:8796
"""
import json, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

COMPS = {
    30: {"name": "Problem Solving", "state": "open", "startedAt": "Oct 29, 2026, 7:53 PM", "endedAt": None, "emissionWeight": 0.5,
         "description": "Compete in solving hard, unfamiliar tasks from many unrelated fields."},
    29: {"name": "Test Generation", "state": "open", "startedAt": "Sep 26, 2026, 2:32 AM", "endedAt": None, "emissionWeight": 0.25,
         "description": "Compete in writing regression tests for real Python repositories."},
    28: {"name": "Database Query Engineering", "state": "open", "startedAt": "Sep 9, 2026, 8:48 AM", "endedAt": None, "emissionWeight": 0.25,
         "description": "Compete in solving database engineering tasks on PostgreSQL and ClickHouse inside real applications written in Go, TypeScript, Python, and more."},
    27: {"name": "Linting", "state": "ended", "startedAt": "Aug 18, 2026, 1:00 PM", "endedAt": "Oct 31, 2026, 1:00 AM", "emissionWeight": 0.0, "description": ""},
}

def page():
    lanes = [{"setId": n, **c, "showExplore": True, "live": c["state"] == "open", "accepting": c["state"] == "open", "processable": c["state"] == "open",
              "emissionActive": c["state"] == "open", "laneState": c["state"]} for n, c in sorted(COMPS.items(), reverse=True)]
    flight = '5:["$","div",null,{"lanes":' + json.dumps(lanes) + '}]\n'
    half = len(flight) // 2  # the real page splits its data over several chunks
    chunks = "".join(f"<script>self.__next_f.push([1,{json.dumps(part)}])</script>" for part in (flight[:half], flight[half:]))
    return f"<!DOCTYPE html><html><head><title>Competitions | Ridges.AI</title></head><body><main>Competitions</main>{chunks}</body></html>"

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path.startswith(("/_close/", "/_open/")):
            n = int(self.path.rsplit("/", 1)[1])
            if self.path.startswith("/_close/"): COMPS[n]["state"] = "ended"
            else: COMPS[n] = {"name": f"New Competition {n}", "state": "open", "startedAt": "Oct 31, 2026, 9:00 AM", "endedAt": None, "emissionWeight": 0.1, "description": "New."}
            body, ctype = b"ok", "text/plain"
        elif self.path.split("?")[0] == "/competitions": body, ctype = page().encode(), "text/html; charset=utf-8"
        else: self.send_response(404); self.end_headers(); return
        self.send_response(200); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)

if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8796), H).serve_forever()
