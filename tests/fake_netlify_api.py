"""Minimal Netlify API for testing My profile's deploys offline.
Token "nfp_testtoken1234567890abcdefghij" is valid. POST /sites makes a site (the name "taken" is refused with 422, like
a subdomain in use), POST /sites/<id>/deploys takes a zip and must hold index.html, and DELETE /sites/<id> removes a
site so the app's next deploy has to recreate it. Deployed sites are served at /live/<name>/ with the CSP from their
_headers file, so the "live" link opens in a browser.
Run: python tests/fake_netlify_api.py 8796  then start the app with NETLIFY_API_URL=http://127.0.0.1:8796/api/v1"""
import io, itertools, json, re, sys, zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = "nfp_testtoken1234567890abcdefghij"
SITES, FILES, DEPLOYS = {}, {}, []  # id -> site; name -> {path: bytes}; every deploy
SEQ = itertools.count(1)  # site ids are never reused, like Netlify's
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8796

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def reply(self, status, body=None, ctype="application/json", headers=None):
        data = body if isinstance(body, bytes) else json.dumps(body).encode() if body is not None else b""
        self.send_response(status)
        self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items(): self.send_header(k, v)
        self.end_headers(); self.wfile.write(data)

    def live(self, name, path):
        files = FILES.get(name)
        if files is None: return self.reply(404, b"Not found", "text/plain")
        path = path.lstrip("/")
        if path == "" or path.endswith("/"): path += "index.html"
        if path not in files and path + "/index.html" in files: path += "/index.html"
        if path not in files: return self.reply(404, b"Not found", "text/plain")
        rules = dict(re.findall(r"^\s+([\w-]+):\s*(.+)$", files.get("_headers", b"").decode(), re.M))
        ctype = "text/html; charset=utf-8" if path.endswith(".html") else "application/octet-stream"
        return self.reply(200, files[path], ctype, rules)

    def route(self, method):
        path = self.path.split("?")[0]
        if method == "GET" and (x := re.match(r"^/live/([\w-]+)(/.*)?$", path)): return self.live(x[1], x[2] or "/")
        if self.headers.get("Authorization") != f"Bearer {TOKEN}": return self.reply(401, {"code": 401, "message": "Access Denied: your token is invalid"})
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if method == "GET" and path == "/api/v1/user": return self.reply(200, {"id": "u1", "email": "ada@example.com", "full_name": "Ada Lovelace"})
        if method == "POST" and path == "/api/v1/sites":
            n = next(SEQ)
            name = (json.loads(raw or b"{}").get("name") or f"brave-curie-{n:04d}").lower()
            if name == "taken" or any(s["name"] == name for s in SITES.values()): return self.reply(422, {"code": 422, "message": "subdomain must be unique"})
            sid = f"site-{n}"
            SITES[sid] = {"id": sid, "name": name, "ssl_url": f"http://127.0.0.1:{PORT}/live/{name}/", "url": f"http://127.0.0.1:{PORT}/live/{name}/",
                          "admin_url": f"https://app.netlify.com/sites/{name}"}
            return self.reply(201, SITES[sid])
        if (x := re.match(r"^/api/v1/sites/([\w-]+)(/deploys)?$", path)):
            site = SITES.get(x[1])
            if not site: return self.reply(404, {"code": 404, "message": "Not Found"})
            if method == "DELETE" and not x[2]:
                del SITES[x[1]]; FILES.pop(site["name"], None); return self.reply(204)
            if method == "POST" and x[2]:
                if self.headers.get("Content-Type") != "application/zip": return self.reply(422, {"code": 422, "message": "Expected a zip"})
                try: files = {n: z.read(n) for z in [zipfile.ZipFile(io.BytesIO(raw))] for n in z.namelist()}
                except zipfile.BadZipFile: return self.reply(422, {"code": 422, "message": "Invalid zip"})
                if "index.html" not in files: return self.reply(422, {"code": 422, "message": "No index.html"})
                FILES[site["name"]] = files
                d = {"id": f"dep-{len(DEPLOYS) + 1}", "site_id": site["id"], "state": "ready", "deploy_ssl_url": site["ssl_url"], "files": sorted(files)}
                DEPLOYS.append(d)
                return self.reply(200, d)
        return self.reply(404, {"code": 404, "message": "Not Found"})

    def do_GET(self): self.route("GET")
    def do_POST(self): self.route("POST")
    def do_DELETE(self): self.route("DELETE")

if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
