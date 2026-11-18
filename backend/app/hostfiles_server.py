"""AXoR Host files: read-only access to chosen folders on this host, for My Knowledge's linked folders (knowledge_linked.py).

Runs on its own in the axor-host namespace (k8s/host/42-hostfiles.yaml) from AXoR's web image, as user nobody in group
1000, with each host folder mounted read-only at ROOTS_DIR/<name> (a "root"): a broad one (the home folder) to browse
anywhere in, and narrower ones as they were linked first. Only the AXoR web pod may reach it (the axor-only
NetworkPolicy), and every call but /health carries the shared secret (HOSTFILES_SECRET).

It never writes, never follows symbolic links, never leaves a root, and never hands out what looks like a secret or tooling
noise, whatever the caller asks for (DENY_DIRS, DENY_FILES): .env files, keys and certificates, credential stores, .git,
virtual environments, caches, the home folder's tool settings and logins (.config, .codex, .bittensor wallets, shell
history). Files private to their owner (mode 600/700) are unreadable to nobody: listed as such and never served.

  GET /health                                   ok (no secret: the readiness probe)
  GET /v1/roots                                 the roots and whether each is mounted
  GET /v1/dir?root=R&path=P                     one folder: its subfolders and files (for picking a folder)
  GET /v1/scan?root=R&path=P&exclude=[..]&max=N every file under P (relative paths, size, mtime, readable), excludes applied
  GET /v1/file?root=R&path=P                    one file's bytes, up to MAX_FILE
Stdlib only; python hostfiles_server.py.
"""
import fnmatch, hmac, json, os, re, stat, sys, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOTS_DIR = os.getenv("HOSTFILES_ROOTS", "/roots")
SECRET = os.getenv("HOSTFILES_SECRET", "")
PORT = int(p) if (p := os.getenv("HOSTFILES_PORT", "8500")).isdigit() else 8500  # a Service link (tcp://ip:port) isn't a port: the default
BIND = os.getenv("HOSTFILES_BIND", "0.0.0.0")  # in its pod; 127.0.0.1 when run by hand on the host
MAX_FILE = 25_000_000
SCAN_CAP = 20_000        # files one scan lists, at most
DIR_CAP = 500            # entries of one kind one folder listing returns
DENY_DIRS = (".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", "*-venv", "*venv", ".tox", ".mypy_cache", ".ruff_cache",
             ".pytest_cache", ".cache", ".ssh", ".gnupg", ".aws", ".docker", ".kube", ".claude",
             # a home folder's tool settings, logins and wallets
             ".config", ".codex", ".copilot", ".local", ".dotnet", ".bittensor", ".vscode-server", ".cursor-server", ".mozilla", ".pki",
             ".npm", ".cargo", ".rustup", ".gradle", ".m2", ".azure", ".gcloud", ".terraform.d", ".password-store", "wallets")
DENY_FILES = (".env", ".env.*", "*.env", ".envrc", "*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore", "id_rsa*", "id_dsa*", "id_ecdsa*",
              "id_ed25519*", "*.enc", "*.gpg", "*.asc", ".netrc", ".pgpass", ".npmrc", ".pypirc", ".git-credentials", "credentials", "credentials.*",
              "*.kdbx", "secrets.*", "*.secret", "*.secrets", ".htpasswd", "*.sqlite", "*.db", "*.pyc", "*.so", "*.o",
              ".claude.json", ".claude.json.*", "*_history", ".viminfo", ".lesshst", ".wget-hsts", ".python_history", ".git-credentials*",
              "auth.json", "token.json", "tokens.json", "hosts.yml", "coldkey*", "hotkey*")
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
try: LABELS = {str(k): str(v) for k, v in json.loads(os.getenv("HOSTFILES_LABELS") or "{}").items()}  # root -> where it is on the host, for the page
except (ValueError, AttributeError): LABELS = {}


class Refused(Exception):
    def __init__(self, code, msg): super().__init__(msg); self.code = code


def denied_dir(name): return any(fnmatch.fnmatch(name.lower(), p) for p in DENY_DIRS)
def denied_file(name): return any(fnmatch.fnmatch(name.lower(), p) for p in DENY_FILES)


def roots():
    try: names = sorted(n for n in os.listdir(ROOTS_DIR) if NAME.fullmatch(n))
    except OSError: names = []
    return [{"name": n, "mounted": os.path.isdir(os.path.join(ROOTS_DIR, n)), "host": LABELS.get(n)} for n in names]


def resolve(root, rel, want_dir):
    """The real path of rel inside root, refusing anything that leaves it, goes through a link or a denied name."""
    if not NAME.fullmatch(root or ""): raise Refused(400, "unknown root")
    base = os.path.realpath(os.path.join(ROOTS_DIR, root))
    if not os.path.isdir(base): raise Refused(404, f"the root {root} isn't mounted")
    parts = [p for p in str(rel or "").replace("\\", "/").split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts) or len(parts) > 40: raise Refused(400, "bad path")
    cur = base
    for i, p in enumerate(parts):
        cur = os.path.join(cur, p)
        try: st = os.lstat(cur)
        except FileNotFoundError: raise Refused(404, "not found")
        except PermissionError: raise Refused(403, "not readable")
        if stat.S_ISLNK(st.st_mode): raise Refused(403, "symbolic links aren't followed")
        last = i == len(parts) - 1
        if stat.S_ISDIR(st.st_mode) and denied_dir(p): raise Refused(403, "that folder is never shared")
        if last and not stat.S_ISDIR(st.st_mode) and denied_file(p): raise Refused(403, "that file is never shared")
    if os.path.commonpath([base, os.path.realpath(cur)]) != base: raise Refused(403, "outside the root")
    if want_dir and not os.path.isdir(cur): raise Refused(400, "not a folder")
    if not want_dir and not os.path.isfile(cur): raise Refused(400, "not a file")
    return cur, "/".join(parts)


def _match(rel, name, pats):
    return any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(name, p) or fnmatch.fnmatch(rel, p.rstrip("/") + "/*") for p in pats)


def list_dir(root, rel):
    path, rel = resolve(root, rel, True)
    dirs, files = [], []
    try: entries = sorted(os.scandir(path), key=lambda e: e.name.lower())
    except PermissionError: raise Refused(403, "not readable")
    for e in entries:
        try:
            if e.is_symlink(): continue
            if e.is_dir(follow_symlinks=False):
                if len(dirs) < DIR_CAP: dirs.append({"name": e.name, "denied": denied_dir(e.name), "readable": os.access(e.path, os.R_OK | os.X_OK)})
            elif e.is_file(follow_symlinks=False):
                if len(files) < DIR_CAP:
                    st = e.stat(follow_symlinks=False)
                    files.append({"name": e.name, "size": st.st_size, "mtime": st.st_mtime, "denied": denied_file(e.name), "readable": os.access(e.path, os.R_OK)})
        except OSError: continue
    return {"root": root, "path": rel, "dirs": dirs, "files": files}


def scan(root, rel, exclude, cap):
    """Every file under rel (paths relative to rel), excludes and the deny lists applied; folders pruned on the way down."""
    path, rel = resolve(root, rel, True)
    out, skipped, truncated = [], {"denied": 0, "excluded": 0, "unreadable": 0, "links": 0}, False
    stack = [(path, "")]
    while stack:
        d, drel = stack.pop()
        try: entries = sorted(os.scandir(d), key=lambda e: e.name)
        except OSError: skipped["unreadable"] += 1; continue
        subs = []
        for e in entries:
            r = f"{drel}/{e.name}" if drel else e.name
            try:
                if e.is_symlink(): skipped["links"] += 1; continue
                if e.is_dir(follow_symlinks=False):
                    if denied_dir(e.name): skipped["denied"] += 1
                    elif _match(r, e.name, exclude): skipped["excluded"] += 1
                    elif not os.access(e.path, os.R_OK | os.X_OK): skipped["unreadable"] += 1
                    else: subs.append((e.path, r))
                elif e.is_file(follow_symlinks=False):
                    if denied_file(e.name): skipped["denied"] += 1; continue
                    if _match(r, e.name, exclude): skipped["excluded"] += 1; continue
                    if len(out) >= cap: truncated = True; continue
                    st = e.stat(follow_symlinks=False)
                    ok = os.access(e.path, os.R_OK)
                    if not ok: skipped["unreadable"] += 1
                    out.append({"path": r, "size": st.st_size, "mtime": st.st_mtime, "readable": ok})
            except OSError: skipped["unreadable"] += 1
        stack.extend(reversed(subs))  # depth first, in name order
    return {"root": root, "path": rel, "files": out, "skipped": skipped, "truncated": truncated}


def read_file(root, rel):
    path, _ = resolve(root, rel, False)
    if os.path.getsize(path) > MAX_FILE: raise Refused(413, "over 25 MB")
    try:
        with open(path, "rb", opener=lambda p, f: os.open(p, f | os.O_NOFOLLOW)) as fh: return fh.read(MAX_FILE + 1)
    except PermissionError: raise Refused(403, "not readable")


class Handler(BaseHTTPRequestHandler):
    server_version = "AXoR-Hostfiles/1"

    def log_message(self, fmt, *args): sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    def reply(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        q = {k: v[-1] for k, v in urllib.parse.parse_qs(u.query).items()}
        if u.path == "/health": return self.reply(200, {"ok": True})
        if not SECRET: return self.reply(503, {"error": "HOSTFILES_SECRET isn't set"})
        if not hmac.compare_digest(self.headers.get("X-Hostfiles-Secret", ""), SECRET): return self.reply(401, {"error": "bad secret"})
        try:
            if u.path == "/v1/roots": return self.reply(200, {"roots": roots()})
            if u.path == "/v1/dir": return self.reply(200, list_dir(q.get("root", ""), q.get("path", "")))
            if u.path == "/v1/scan":
                try: exclude = [str(x)[:200] for x in json.loads(q.get("exclude") or "[]")][:100]
                except (ValueError, TypeError): raise Refused(400, "exclude is a JSON list")
                return self.reply(200, scan(q.get("root", ""), q.get("path", ""), exclude, max(1, min(SCAN_CAP, int(q.get("max") or SCAN_CAP)))))
            if u.path == "/v1/file": return self.reply(200, read_file(q.get("root", ""), q.get("path", "")), "application/octet-stream")
            return self.reply(404, {"error": "no such call"})
        except Refused as e: return self.reply(e.code, {"error": str(e)})
        except ValueError as e: return self.reply(400, {"error": str(e)})


def main():
    srv = ThreadingHTTPServer((BIND, PORT), Handler)
    sys.stderr.write(f"hostfiles: {', '.join(r['name'] for r in roots()) or 'no roots'} under {ROOTS_DIR}, port {PORT}\n")
    srv.serve_forever()


if __name__ == "__main__":
    main()
