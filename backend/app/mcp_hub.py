"""Tools & MCP: MCP servers AXoR's agents can use, the tools each server offers, and which agents may call which.

- Servers (mcp_servers): administrators add a remote server (Streamable HTTP: a URL and headers) or a local one (stdio: a
  command that exists inside AXoR's container, its arguments and environment). Header and environment *values* are secrets:
  they're kept encrypted in the SecretBox under "mcp:<id>" and never leave the server; the API shows their names only.
- Discovery: "Test connection" runs initialize + tools/list and keeps the tools. A tool starts **not allowed** unless the server
  marks it read-only (readOnlyHint); an administrator ticks the rest. A server's audience ("admins" or "everyone") says whether
  members may give it to their own agents: its credentials are the server's, not theirs.
- Grants (mcp_grants): scope → server, with an optional subset of its allowed tools. Scopes are "hub:<agent id>" (an agent on
  the Agents page; its owner decides) and "team:<workspace id>" (a Competition team: every agent of the team; the team's owner
  decides). Administrators may set any grant.
- Runtime: attach(scopes, me) returns the tool definitions for a run_loop and the call for them. Tool names are
  "ext_<server slug>__<tool>" (≤ 64 characters; llm.py doesn't ask OpenAI's strict mode of them: MCP schemas rarely fit it).
  The audience, the allow-list and the grant are checked again at every call. Every call is written to mcp_calls.

The client is small and stdlib-only: newline-delimited JSON-RPC over a child's stdin/stdout, or JSON-RPC POSTs whose answer is
JSON or an SSE stream (Mcp-Session-Id and MCP-Protocol-Version headers kept). One session per server is kept open and reused;
sessions idle for IDLE seconds are closed, and a session is rebuilt when its server's settings change.
"""
import hashlib, json, logging, os, queue, re, subprocess, sys, threading, time, urllib.error, urllib.request
from collections import deque
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

log = logging.getLogger("scout.mcp")
PROTOCOL = "2025-06-18"
PREFIX = "ext_"  # llm.py: tools named so aren't sent with OpenAI's strict mode
TIMEOUT, LIST_TIMEOUT, IDLE = 60, 30, 600  # seconds
RESULT_CHARS, MAX_TOOLS, MAX_BODY = 20000, 40, 5 * 1024 * 1024
AUDIENCES = ("admins", "everyone")
BACKEND = Path(__file__).resolve().parents[1]
SOURCE_TOKEN = "{{source_github_token}}"  # a header value that means "the GitHub token the Source hub already has"; the only such marker

class McpError(Exception):
    """The server couldn't be reached or broke the protocol (not a tool's own error)."""

# ---------------------------------------------------------------- transports
class _Stdio:
    """A child process speaking newline-delimited JSON-RPC on stdin/stdout. One request at a time (the session's lock)."""
    def __init__(self, command, args, env):
        try:
            # never AXoR's own environment (API keys, SECRET_KEY…): a bare base plus what the admin set for this server
            base = {k: os.environ[k] for k in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "TZ", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
                                               "http_proxy", "https_proxy", "no_proxy", "SSL_CERT_FILE") if k in os.environ}
            # started in backend/ (where the bundled servers in app/mcp_servers are found by a relative path), output unbuffered
            self.p = subprocess.Popen([command, *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=BACKEND,
                                      env={**base, "PYTHONUNBUFFERED": "1", **env}, text=True, bufsize=1, start_new_session=True)
        except OSError as e:
            raise McpError(f"Couldn't start {command}: {e.strerror or e}. A local server's command must exist inside AXoR's container.")
        self.q, self.err = queue.Queue(), deque(maxlen=20)
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=lambda: [self.err.append(l.rstrip()) for l in self.p.stderr], daemon=True).start()

    def _read(self):
        for line in self.p.stdout:
            line = line.strip()
            if not line: continue
            try: self.q.put(json.loads(line))
            except ValueError: self.err.append("not JSON on stdout: " + line[:200])
        self.q.put(None)  # the process ended

    def _send(self, msg):
        try: self.p.stdin.write(json.dumps(msg) + "\n"); self.p.stdin.flush()
        except (OSError, ValueError) as e: raise McpError(f"The server's process isn't running ({e}). {self._tail()}")

    def _tail(self): return ("Its last output: " + " | ".join(list(self.err)[-3:])) if self.err else ""

    def request(self, msg, timeout):
        self._send(msg)
        end = time.time() + timeout
        while True:
            try: m = self.q.get(timeout=max(0.05, end - time.time()))
            except queue.Empty: raise McpError(f"No answer within {timeout} s.")
            if m is None: raise McpError(f"The server's process ended. {self._tail()}")
            if m.get("id") == msg["id"] and ("result" in m or "error" in m): return m
            if "method" in m and "id" in m:  # the server asks us something: ping is answered, the rest declined
                self._send({"jsonrpc": "2.0", "id": m["id"], "result": {}} if m["method"] == "ping"
                           else {"jsonrpc": "2.0", "id": m["id"], "error": {"code": -32601, "message": "Not supported by AXoR"}})
            if time.time() > end: raise McpError(f"No answer within {timeout} s.")

    def notify(self, msg): self._send(msg)

    def close(self):
        try:
            self.p.stdin.close()
            self.p.terminate(); self.p.wait(3)
        except Exception:  # noqa: BLE001
            try: self.p.kill(); self.p.wait(3)
            except Exception: pass  # noqa: BLE001
        for f in (self.p.stdout, self.p.stderr):  # the reader threads end with the process
            try: f.close()
            except Exception: pass  # noqa: BLE001

class _Http:
    """Streamable HTTP: each message is a POST; the answer is JSON or an SSE stream holding it."""
    def __init__(self, url, headers):
        self.url, self.headers, self.sid, self.proto = url, headers, None, None

    def _post(self, msg, timeout):
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "User-Agent": "AXoR-MCP/1", **self.headers}
        if self.sid: h["Mcp-Session-Id"] = self.sid
        if self.proto: h["MCP-Protocol-Version"] = self.proto
        req = urllib.request.Request(self.url, data=json.dumps(msg).encode(), headers=h, method="POST")
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            body = e.read(2000).decode("utf-8", "replace")
            if e.code == 404 and self.sid: self.sid = None; raise McpError("The server ended the session.")
            if e.code in (401, 403): raise McpError(f"The server refused AXoR's credentials (HTTP {e.code}). Check the headers.")
            raise McpError(f"HTTP {e.code} from the server: {body[:300]}")
        except (urllib.error.URLError, OSError) as e:
            raise McpError(f"Couldn't reach {self.url}: {getattr(e, 'reason', e)}")
        with resp:
            if resp.headers.get("Mcp-Session-Id"): self.sid = resp.headers["Mcp-Session-Id"]
            if "id" not in msg or resp.status == 202: return None
            ctype = resp.headers.get("Content-Type", "")
            if "text/event-stream" in ctype: return self._sse(resp, msg["id"])
            body = resp.read(MAX_BODY + 1)
            if len(body) > MAX_BODY: raise McpError("The server's answer is too large.")
            try: m = json.loads(body or b"{}")
            except ValueError: raise McpError(f"The server didn't answer with JSON ({ctype or 'no content type'}).")
            if isinstance(m, list): m = next((x for x in m if x.get("id") == msg["id"]), {})
            return m

    def _sse(self, resp, mid):
        data, size = [], 0
        for raw in resp:
            size += len(raw)
            if size > MAX_BODY: raise McpError("The server's answer is too large.")
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if line.startswith("data:"): data.append(line[5:].lstrip()); continue
            if line == "" and data:
                try: m = json.loads("\n".join(data))
                except ValueError: m = {}
                data = []
                if isinstance(m, dict) and m.get("id") == mid and ("result" in m or "error" in m): return m
        raise McpError("The server's stream ended without an answer.")

    def request(self, msg, timeout):
        m = self._post(msg, timeout)
        if not m: raise McpError("The server sent no answer.")
        return m

    def notify(self, msg): self._post(msg, 15)

    def close(self):
        if not self.sid: return
        try: urllib.request.urlopen(urllib.request.Request(self.url, headers={**self.headers, "Mcp-Session-Id": self.sid}, method="DELETE"), timeout=5).close()
        except Exception: pass  # noqa: BLE001 - the server forgets it anyway

class Session:
    """An initialized connection to one server."""
    def __init__(self, s, secrets):
        if s["transport"] == "stdio":
            self.t = _Stdio(s["command"], json.loads(s["args"] or "[]"), secrets.get("env") or {})
        else:
            self.t = _Http(s["url"], secrets.get("headers") or {})
        self.lock, self.ids, self.last, self.serial = threading.Lock(), 0, time.time(), s["transport"] == "stdio"
        try:
            r = self._call("initialize", {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": {"name": "AXoR", "version": "4.0"}}, LIST_TIMEOUT)
            self.info = r.get("serverInfo") or {}
            if isinstance(self.t, _Http): self.t.proto = r.get("protocolVersion") or PROTOCOL
            self.t.notify({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except BaseException:
            self.t.close()  # a local server that won't initialize isn't left running
            raise

    def _call(self, method, params, timeout):
        with self.lock:
            self.ids += 1; mid = self.ids
        msg = {"jsonrpc": "2.0", "id": mid, "method": method, "params": params}
        if self.serial:
            with self.lock: m = self.t.request(msg, timeout)
        else: m = self.t.request(msg, timeout)
        self.last = time.time()
        if "error" in m:
            e = m["error"] or {}
            raise McpError(f"{method}: {e.get('message') or e}")
        return m.get("result") or {}

    def tools(self):
        out, cursor = [], None
        for _ in range(10):
            r = self._call("tools/list", {"cursor": cursor} if cursor else {}, LIST_TIMEOUT)
            out += r.get("tools") or []
            cursor = r.get("nextCursor")
            if not cursor: break
        return out

    def call(self, name, args, timeout=None):
        return self._call("tools/call", {"name": name, "arguments": args}, timeout or TIMEOUT)

    def close(self): self.t.close()

def flatten(r):
    """A tools/call result as (text for the model, is_error)."""
    parts = []
    for c in r.get("content") or []:
        t = c.get("type")
        if t == "text": parts.append(c.get("text") or "")
        elif t == "resource":
            res = c.get("resource") or {}
            parts.append(res.get("text") or f"[resource {res.get('uri', '')} ({res.get('mimeType', '')}) not shown]")
        elif t == "resource_link": parts.append(f"[link] {c.get('name') or ''} {c.get('uri') or ''}".strip())
        elif t in ("image", "audio"): parts.append(f"[{t} {c.get('mimeType') or ''} not shown]")
    text = "\n".join(p for p in parts if p)
    if not text and r.get("structuredContent") is not None: text = json.dumps(r["structuredContent"])
    if len(text) > RESULT_CHARS: text = text[:RESULT_CHARS] + f"\n… (cut at {RESULT_CHARS} characters)"
    return text, bool(r.get("isError"))

# ---------------------------------------------------------------- names and schemas
def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")[:16].strip("_")
    return s or "server"

def tool_name(slug, tool):
    t = re.sub(r"[^A-Za-z0-9_-]", "_", tool)
    n = f"{PREFIX}{slug}__{t}"
    if len(n) <= 64: return n
    h = hashlib.sha1(tool.encode()).hexdigest()[:6]
    return f"{PREFIX}{slug}__{t[:64 - len(PREFIX) - len(slug) - 2 - 7]}_{h}"

def _schema(s):
    s = s if isinstance(s, dict) else {}
    s = json.loads(json.dumps(s))  # a copy
    s.pop("$schema", None)  # real servers send it (Context7, Exa); model APIs don't need it
    if s.get("type") != "object": s = {"type": "object", "properties": {}}
    s.setdefault("properties", {})
    return s

def _read_only(t): return bool((t.get("annotations") or {}).get("readOnlyHint"))

# ---------------------------------------------------------------- the catalog: servers added in one click
# "allow": which discovered tools start allowed: "read_only" (the server's own readOnlyHint) or "all" (servers known to only read).
# Checked against the real services on 2026-11-04: DeepWiki, Context7 and Exa without keys; GitHub not (it needs a token).
CATALOG = [
    {"key": "github", "name": "GitHub", "for": ["GitHub"], "transport": "http", "url": "https://api.githubcopilot.com/mcp/", "allow": "read_only",
     "about": "GitHub's official MCP server: repositories, files, issues, pull requests, code search and Actions. Read-only tools start allowed; "
              "tools that write (open an issue, push a file) wait for your tick.",
     "fields": [{"part": "headers", "key": "Authorization", "label": "GitHub token", "prefix": "Bearer ", "source_token": True,
                 "help": "A fine-grained personal access token with read access to the repositories agents may see, or the token Source already has."}]},
    {"key": "deepwiki", "name": "DeepWiki", "for": ["GitHub", "New tech"], "transport": "http", "url": "https://mcp.deepwiki.com/mcp", "allow": "all",
     "about": "Ask questions about any public GitHub repository and read its generated documentation. Free, no key.", "fields": []},
    {"key": "context7", "name": "Context7", "for": ["New tech"], "transport": "http", "url": "https://mcp.context7.com/mcp", "allow": "read_only",
     "about": "Current documentation and code examples for libraries and frameworks, so agents don't build on stale knowledge. Works without a key "
              "(rate-limited); a key raises the limit.",
     "fields": [{"part": "headers", "key": "CONTEXT7_API_KEY", "label": "Context7 API key", "optional": True}]},
    {"key": "exa", "name": "Exa search", "for": ["Search", "Essay"], "transport": "http", "url": "https://mcp.exa.ai/mcp", "allow": "read_only",
     "about": "Web search and page reading for research and fact-checking. Works without a key.", "fields": []},
    {"key": "papers", "name": "Research papers", "for": ["Papers", "Essay"], "transport": "stdio", "bundled": "app/mcp_servers/papers.py", "allow": "all",
     "about": "Search arXiv, Semantic Scholar and OpenAlex; a paper's abstract, authors, year, citations and links, and what cites it. "
              "Built in to AXoR, no key.",
     "fields": [{"part": "env", "key": "S2_API_KEY", "label": "Semantic Scholar API key", "optional": True,
                 "help": "Only for searches on Semantic Scholar, which often refuses requests without one. OpenAlex and arXiv need none."}]},
    {"key": "database", "name": "Database (read-only)", "for": ["Database"], "transport": "stdio", "bundled": "app/mcp_servers/database.py", "allow": "all",
     "about": "Read-only SQL on a PostgreSQL database or an SQLite file: list and describe tables, run SELECT queries (row-capped, time-limited). "
              "Built in to AXoR.",
     "fields": [{"part": "env", "key": "DATABASE_URL", "label": "Database URL", "placeholder": "postgresql://reader:…@host:5432/dbname  or  sqlite:////path/to/file.db",
                 "help": "Give it an account that can only read: the server refuses writes too, but the account is the real guard."}]},
]
CATALOG_BY_KEY = {c["key"]: c for c in CATALOG}

# ---------------------------------------------------------------- the hub
class Hub:
    def __init__(self, db, box):
        self.db, self.box, self.pool, self.plock = db, box, {}, threading.Lock()
        db.q("""CREATE TABLE IF NOT EXISTS mcp_servers (
                  id INTEGER PRIMARY KEY, name TEXT, slug TEXT UNIQUE, transport TEXT, url TEXT, command TEXT, args TEXT DEFAULT '[]',
                  secret_names TEXT DEFAULT '{}', audience TEXT DEFAULT 'admins', enabled INTEGER DEFAULT 1, tools TEXT DEFAULT '[]',
                  allowed TEXT DEFAULT '[]', status TEXT DEFAULT 'new', error TEXT, checked REAL, server_info TEXT,
                  created_by INTEGER, created REAL, updated REAL)""")
        db.q("CREATE TABLE IF NOT EXISTS mcp_grants (scope TEXT, server_id INTEGER, tools TEXT, by INTEGER, ts REAL, PRIMARY KEY (scope, server_id))")
        db.q("""CREATE TABLE IF NOT EXISTS mcp_calls (id INTEGER PRIMARY KEY, ts REAL, user_id INTEGER, scope TEXT, server_id INTEGER,
                  tool TEXT, ok INTEGER, ms INTEGER, error TEXT)""")
        db.q("CREATE INDEX IF NOT EXISTS mcp_calls_ts ON mcp_calls(ts)")
        if "catalog" not in [c["name"] for c in db.q("PRAGMA table_info(mcp_servers)")]:
            db.q("ALTER TABLE mcp_servers ADD COLUMN catalog TEXT")  # the catalog entry it was added from
        self.teams = None  # mining_work's Work, for "team:" scopes (bind_teams)
        threading.Thread(target=self._reaper, daemon=True).start()

    # ---- servers
    def _row(self, sid):
        s = self.db.q("SELECT * FROM mcp_servers WHERE id=?", (sid,), one=True)
        if not s: raise HTTPException(404, "There's no such MCP server.")
        return s

    def _secrets(self, sid):
        try: return json.loads(self.box.get(f"mcp:{sid}") or "{}")
        except ValueError: return {}

    def source_token(self):
        return self.box.get("github_token") or os.getenv("SOURCE_GITHUB_TOKEN") or ""

    def _live(self, sid):
        """The secrets a session uses: the stored ones, with the Source hub's GitHub token put in where a header asks for it."""
        sec = self._secrets(sid)
        h = sec.get("headers") or {}
        if any(SOURCE_TOKEN in (v or "") for v in h.values()):
            tok = self.source_token()
            if not tok: raise McpError("This server uses the GitHub token from Source, and Source has none. Connect GitHub in Source, or give the server its own token.")
            sec = {**sec, "headers": {k: (v or "").replace(SOURCE_TOKEN, tok) for k, v in h.items()}}
        return sec

    def visible(self, s, me):
        return me.get("role") == "admin" or s["audience"] == "everyone"

    def view(self, s, me, full=None):
        admin = me.get("role") == "admin" if full is None else full
        tools, allowed = json.loads(s["tools"] or "[]"), set(json.loads(s["allowed"] or "[]"))
        out = {"id": s["id"], "name": s["name"], "slug": s["slug"], "transport": s["transport"], "audience": s["audience"], "enabled": bool(s["enabled"]),
               "status": s["status"], "error": s["error"], "checked": s["checked"], "server": json.loads(s["server_info"] or "{}"),
               "tools": [{"name": t["name"], "title": t.get("title") or (t.get("annotations") or {}).get("title") or "", "description": (t.get("description") or "")[:500],
                          "read_only": _read_only(t), "allowed": t["name"] in allowed, "call_name": tool_name(s["slug"], t["name"])}
                         for t in tools if admin or t["name"] in allowed]}
        if admin:
            names = json.loads(s["secret_names"] or "{}")
            out |= {"url": s["url"], "command": s["command"], "args": json.loads(s["args"] or "[]"),
                    "headers": names.get("headers", []), "env": names.get("env", []), "updated": s["updated"],
                    "grants": self.db.q("SELECT COUNT(*) n FROM mcp_grants WHERE server_id=?", (s["id"],), one=True)["n"]}
        return out

    def listing(self, me):
        rows = [s for s in self.db.q("SELECT * FROM mcp_servers ORDER BY name COLLATE NOCASE") if self.visible(s, me)]
        out = {"admin": me.get("role") == "admin", "me": me["id"], "servers": [self.view(s, me) for s in rows]}  # me: the "missions:<id>" scope
        if out["admin"]:
            added = {}
            for s in rows: added.setdefault(s.get("catalog"), []).append(s["id"])
            out["catalog"] = [{k: c.get(k) for k in ("key", "name", "for", "about", "transport", "url")} | {
                "keyless": not any(not f.get("optional") for f in c["fields"]), "added": added.get(c["key"], []),
                "fields": [{k: f.get(k) for k in ("key", "label", "help", "placeholder", "optional", "source_token")} for f in c["fields"]]} for c in CATALOG]
            out["source_token"] = bool(self.source_token())
            out["calls"] =self.db.q("""SELECT c.ts, c.scope, c.tool, c.ok, c.ms, c.error, s.name server, u.username who FROM mcp_calls c
                                        LEFT JOIN mcp_servers s ON s.id=c.server_id LEFT JOIN users u ON u.id=c.user_id ORDER BY c.id DESC LIMIT 30""")
        return out

    def _check(self, b):
        name = (b.name or "").strip()
        if not 1 <= len(name) <= 60: raise HTTPException(400, "Give the server a name (up to 60 characters).")
        if b.transport not in ("http", "stdio"): raise HTTPException(400, "Pick remote (HTTP) or local (command).")
        if b.audience not in AUDIENCES: raise HTTPException(400, "Pick who may use it: admins or everyone.")
        if b.transport == "http" and not re.match(r"^https?://[^\s/]+", b.url or ""): raise HTTPException(400, "The URL must start with http:// or https://.")
        if b.transport == "stdio" and not (b.command or "").strip(): raise HTTPException(400, "Give the command that starts the server.")
        if len(b.args or []) > 30 or any(len(a) > 500 for a in b.args or []): raise HTTPException(400, "Up to 30 arguments of 500 characters.")
        for kind, items in (("header", b.headers or []), ("environment variable", b.env or [])):
            if len(items) > 20: raise HTTPException(400, f"Up to 20 of each {kind}.")
            for it in items:
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,63}", it.key or ""): raise HTTPException(400, f"“{it.key}” isn't a valid {kind} name.")
        return name

    def _merge(self, sid, b):
        """New secret values over the old: an empty value keeps the old one; a name left out is removed."""
        old, new = self._secrets(sid) if sid else {}, {}
        for part, items in (("headers", b.headers or []), ("env", b.env or [])):
            keep = old.get(part) or {}
            new[part] = {it.key: it.value if it.value else keep.get(it.key, "") for it in items}
        return new

    def create(self, me, b, slug=None):
        name, now = self._check(b), time.time()
        base = slugify(slug or name)
        slug, n = base, 2
        while self.db.q("SELECT 1 FROM mcp_servers WHERE slug=?", (slug,), one=True): slug, n = f"{base[:13]}_{n}", n + 1
        self.db.q("""INSERT INTO mcp_servers (name, slug, transport, url, command, args, audience, created_by, created, updated)
                     VALUES (?,?,?,?,?,?,?,?,?,?)""", (name, slug, b.transport, (b.url or "").strip() if b.transport == "http" else None,
                                                       (b.command or "").strip() if b.transport == "stdio" else None, json.dumps(b.args or []), b.audience, me["id"], now, now))
        sid = self.db.q("SELECT id FROM mcp_servers WHERE slug=?", (slug,), one=True)["id"]
        self._save_secrets(sid, self._merge(None, b))
        return self.test(sid)

    def install(self, me, key, values, audience="admins"):
        """Add a catalog server: its settings come from the catalog, the secrets from `values` ({field key: value, "use_source": bool})."""
        c = CATALOG_BY_KEY.get(key)
        if not c: raise HTTPException(404, "There's no such catalog entry.")
        pairs = {"headers": [], "env": []}
        for f in c["fields"]:
            v = str(values.get(f["key"]) or "").strip()
            if f.get("source_token") and values.get("use_source"):
                if not self.source_token(): raise HTTPException(400, "Source has no GitHub token yet. Connect GitHub in Source, or paste a token here.")
                v = SOURCE_TOKEN
            if not v:
                if f.get("optional"): continue
                raise HTTPException(400, f"{f['label']} is needed.")
            if f.get("prefix") and v.startswith(f["prefix"]): v = v[len(f["prefix"]):]  # pasted with "Bearer " already
            pairs[f["part"]].append(Pair(key=f["key"], value=f.get("prefix", "") + v))
        bundled = c.get("bundled")
        s = self.create(me, ServerIn(name=c["name"], transport=c["transport"], url=c.get("url"), command=sys.executable if bundled else None,
                                     args=([bundled] + (["--protect", os.getenv("DATA_DIR", "/data")] if key == "database" else [])) if bundled else [],
                                     headers=pairs["headers"], env=pairs["env"], audience=audience), slug=key)  # tools read ext_<key>__…
        self.db.q("UPDATE mcp_servers SET catalog=? WHERE id=?", (key, s["id"]))
        if s["status"] == "ok" and c["allow"] == "all":
            self.set_allowed(s["id"], [t["name"] for t in json.loads(s["tools"] or "[]")])
        return self._row(s["id"])

    def update(self, me, sid, b):
        s, name = self._row(sid), self._check(b)
        secrets = self._merge(sid, b)
        self.db.q("UPDATE mcp_servers SET name=?, transport=?, url=?, command=?, args=?, audience=?, enabled=?, updated=? WHERE id=?",
                  (name, b.transport, (b.url or "").strip() if b.transport == "http" else None, (b.command or "").strip() if b.transport == "stdio" else None,
                   json.dumps(b.args or []), b.audience, 1 if b.enabled else 0, time.time(), sid))
        self._save_secrets(sid, secrets)
        self._drop(sid)
        moved = (s["transport"], s["url"], s["command"], s["args"]) != (b.transport, (b.url or "").strip() or None, (b.command or "").strip() or None, json.dumps(b.args or []))
        return self.test(sid) if b.enabled and (moved or s["status"] != "ok") else self._row(sid)

    def _save_secrets(self, sid, secrets):
        self.box.set(f"mcp:{sid}", json.dumps(secrets))
        self.db.q("UPDATE mcp_servers SET secret_names=? WHERE id=?", (json.dumps({k: sorted(v) for k, v in secrets.items()}), sid))

    def delete(self, sid):
        self._row(sid)
        self._drop(sid)
        self.db.q("DELETE FROM mcp_grants WHERE server_id=?", (sid,))
        self.db.q("DELETE FROM mcp_servers WHERE id=?", (sid,))
        self.box.delete(f"mcp:{sid}")

    def set_allowed(self, sid, names):
        s = self._row(sid)
        known = {t["name"] for t in json.loads(s["tools"] or "[]")}
        bad = [n for n in names if n not in known]
        if bad: raise HTTPException(400, f"The server has no tool named {bad[0]}. Test the connection to refresh its tools.")
        self.db.q("UPDATE mcp_servers SET allowed=?, updated=? WHERE id=?", (json.dumps(sorted(set(names))), time.time(), sid))
        return self._row(sid)

    def test(self, sid):
        """Connect, list the tools, keep them. New tools start allowed only when the server marks them read-only."""
        s = self._row(sid)
        self._drop(sid)
        try:
            sess = self._session(s)
            tools = [t for t in sess.tools() if isinstance(t, dict) and t.get("name")]
        except McpError as e:
            self.db.q("UPDATE mcp_servers SET status='error', error=?, checked=? WHERE id=?", (str(e)[:500], time.time(), sid))
            self._drop(sid)
            return self._row(sid)
        before = {t["name"] for t in json.loads(s["tools"] or "[]")}
        allowed = {n for n in json.loads(s["allowed"] or "[]") if any(t["name"] == n for t in tools)}
        allowed |= {t["name"] for t in tools if t["name"] not in before and _read_only(t)}
        keep = [{k: t.get(k) for k in ("name", "title", "description", "inputSchema", "annotations") if t.get(k) is not None} for t in tools]
        self.db.q("UPDATE mcp_servers SET status='ok', error=NULL, checked=?, tools=?, allowed=?, server_info=? WHERE id=?",
                  (time.time(), json.dumps(keep), json.dumps(sorted(allowed)), json.dumps(sess.info), sid))
        return self._row(sid)

    # ---- sessions
    def _fingerprint(self, s):
        return hashlib.sha256(json.dumps([s["transport"], s["url"], s["command"], s["args"], self.box.get(f"mcp:{s['id']}") or ""]).encode()).hexdigest()

    def _session(self, s):
        fp = self._fingerprint(s)
        with self.plock:
            got = self.pool.get(s["id"])
            if got and got[0] == fp: return got[1]
            if got: got[1].close()
        sess = Session(s, self._live(s["id"]))  # outside the lock: starting a server can take seconds
        with self.plock:
            old = self.pool.get(s["id"])
            if old and old[1] is not sess: old[1].close()
            self.pool[s["id"]] = (fp, sess)
        return sess

    def _drop(self, sid):
        with self.plock: got = self.pool.pop(sid, None)
        if got: got[1].close()

    def _reaper(self):
        while True:
            time.sleep(60)
            with self.plock: idle = [k for k, (_, s) in self.pool.items() if time.time() - s.last > IDLE]
            for k in idle: self._drop(k)

    # ---- grants
    def _scope(self, scope):
        kind, _, ident = (scope or "").partition(":")
        if kind not in ("hub", "team", "missions") or not ident.isdigit(): raise HTTPException(400, "Unknown scope.")
        return kind, int(ident)

    def can_edit(self, me, scope):
        kind, ident = self._scope(scope)
        if kind == "hub":
            a = self.db.q("SELECT owner_id FROM custom_agents WHERE id=?", (ident,), one=True)
            if not a: raise HTTPException(404, "Agent not found.")
            return me.get("role") == "admin" or a["owner_id"] == me["id"]
        if kind == "missions":  # "missions:<user id>": the tools that user's missions get, in every engine they run on
            if me["id"] != ident and me.get("role") != "admin": raise HTTPException(403, "These are someone else's mission tools.")
            return True
        if not self.teams: raise HTTPException(404, "Competition teams aren't running on this server.")
        self.teams._own(me, ident)  # 404 unless the team is yours (or you're an admin)
        return True

    def grants(self, me, scope):
        edit = self.can_edit(me, scope)
        if not edit: raise HTTPException(403, "Only the agent's creator can change its tools.")
        got = {g["server_id"]: g for g in self.db.q("SELECT * FROM mcp_grants WHERE scope=?", (scope,))}
        servers = []
        for s in self.db.q("SELECT * FROM mcp_servers ORDER BY name COLLATE NOCASE"):
            g = got.get(s["id"])
            if not self.visible(s, me) and not g: continue
            v = self.view(s, me, full=False)
            v |= {"granted": bool(g), "picked": json.loads(g["tools"]) if g and g["tools"] else None, "usable": self.visible(s, me) and bool(s["enabled"])}
            servers.append(v)
        return {"scope": scope, "servers": servers}

    def set_grants(self, me, scope, items):
        if not self.can_edit(me, scope): raise HTTPException(403, "Only the agent's creator can change its tools.")
        now, keep = time.time(), []
        for it in items:
            s = self._row(it.server_id)
            if not self.visible(s, me): raise HTTPException(403, f"{s['name']} is for administrators' agents only.")
            allowed = set(json.loads(s["allowed"] or "[]"))
            pick = None if it.tools is None else sorted(set(it.tools) & allowed)
            if it.tools is not None and not pick: continue  # nothing picked: no grant
            keep.append((scope, s["id"], json.dumps(pick) if pick is not None else None, me["id"], now))
        self.db.q("DELETE FROM mcp_grants WHERE scope=?", (scope,))
        for k in keep: self.db.q("INSERT INTO mcp_grants VALUES (?,?,?,?,?)", k)
        return self.grants(me, scope)

    def granted(self, scope, me):
        """[(server row, tool dict)] a scope may call now, for `me` (the agent's owner or the team's)."""
        out = []
        for g in self.db.q("SELECT * FROM mcp_grants WHERE scope=?", (scope,)):
            s = self.db.q("SELECT * FROM mcp_servers WHERE id=?", (g["server_id"],), one=True)
            if not s or not s["enabled"] or not self.visible(s, me): continue
            allowed, pick = set(json.loads(s["allowed"] or "[]")), json.loads(g["tools"]) if g["tools"] else None
            out += [(s, t) for t in json.loads(s["tools"] or "[]") if t["name"] in allowed and (pick is None or t["name"] in pick)]
        return out

    # ---- runtime
    def attach(self, scopes, me):
        tools, route = [], {}
        for scope in scopes:
            for s, t in self.granted(scope, me):
                n = tool_name(s["slug"], t["name"])
                if n in route or len(tools) >= MAX_TOOLS: continue
                route[n] = (scope, s["id"], t["name"])
                desc = (t.get("description") or t.get("title") or t["name"]).strip()
                tools.append({"name": n, "description": f"{desc[:900]} (from the MCP server “{s['name']}”)", "input_schema": _schema(t.get("inputSchema"))})
        return Attached(self, tools, route, me)

    def call(self, me, scope, sid, tool, args):
        t0 = time.time()
        s = self.db.q("SELECT * FROM mcp_servers WHERE id=?", (sid,), one=True)
        ok, err = False, None
        try:
            if not s or not s["enabled"]: raise McpError("The server was turned off or removed.")
            if not any(srv["id"] == sid and t["name"] == tool for srv, t in self.granted(scope, me)):
                raise McpError(f"{tool} isn't allowed for this agent any more.")
            for attempt in (0, 1):
                try:
                    r = self._session(s).call(tool, args)
                    break
                except McpError:
                    self._drop(sid)  # a broken or expired session: one more try on a fresh one
                    if attempt: raise
            text, is_err = flatten(r)
            ok, err = not is_err, (text[:300] if is_err else None)
            if is_err: raise ValueError(text or "The tool reported an error.")
            return {"result": text}
        except McpError as e:
            err = str(e)[:300]
            return {"error": f"The MCP server “{s['name'] if s else sid}” failed: {e}"}
        except ValueError: raise  # the tool's own error (isError): run_loop marks the result as an error
        except Exception as e:  # noqa: BLE001 - a server that answers nonsense costs the agent one call, not the run
            err = f"Unexpected answer: {e}"[:300]
            log.warning("mcp call %s/%s: %s", sid, tool, e)
            return {"error": f"The MCP server “{s['name'] if s else sid}” gave an answer AXoR couldn't read."}
        finally:
            self.db.q("INSERT INTO mcp_calls (ts, user_id, scope, server_id, tool, ok, ms, error) VALUES (?,?,?,?,?,?,?,?)",
                      (t0, me.get("id"), scope, sid, tool, 1 if ok else 0, int((time.time() - t0) * 1000), err))

class Attached:
    """MCP tools for one run: `tools` go to run_loop; `name in attached` says whether a call is one of them."""
    def __init__(self, hub, tools, route, me):
        self.hub, self.tools, self.route, self.me = hub, tools, route, me
    def __contains__(self, name): return name in self.route
    def __call__(self, name, args):
        scope, sid, tool = self.route[name]
        return self.hub.call(self.me, scope, sid, tool, args)

NONE = Attached(None, [], {}, {})
_hub = None

def init(db, box):
    global _hub
    _hub = Hub(db, box)
    return _hub

def bind_teams(work):
    if _hub: _hub.teams = work

def attach(scopes, me):
    """The MCP tools these scopes may call (empty when Tools & MCP isn't running). Never raises."""
    if _hub is None: return NONE
    try: return _hub.attach(scopes, me)
    except Exception as e:  # noqa: BLE001 - a broken registry costs the run its MCP tools, not the run
        log.warning("mcp attach %s: %s", scopes, e)
        return NONE

def listed(scope, me):
    """[(server name, tool name, call name)] for a profile's Tools tab."""
    if _hub is None: return []
    try: return [(s["name"], t["name"], tool_name(s["slug"], t["name"])) for s, t in _hub.granted(scope, me)]
    except Exception: return []  # noqa: BLE001

# ---------------------------------------------------------------- routes
class Pair(BaseModel):
    key: str
    value: str | None = None  # empty: keep the stored value

class ServerIn(BaseModel):
    name: str
    transport: str = "http"
    url: str | None = None
    command: str | None = None
    args: list[str] = []
    headers: list[Pair] = []
    env: list[Pair] = []
    audience: str = "admins"
    enabled: bool = True

class InstallIn(BaseModel):
    values: dict[str, str | bool] = {}  # catalog field key → secret value; "use_source": the Source hub's GitHub token
    audience: str = "admins"

class AllowedIn(BaseModel):
    allowed: list[str]

class GrantIn(BaseModel):
    server_id: int
    tools: list[str] | None = None  # None: every allowed tool, now and later

class GrantsIn(BaseModel):
    scope: str
    grants: list[GrantIn]

def build(db, box, require, admin_state, ip, gate=None):
    hub = init(db, box)
    r = APIRouter(prefix="/api/mcp")
    admin, sudo = admin_state["admin"], admin_state["sudo"]
    me_ = lambda req: (gate or (lambda u: u))(require(req))
    audit = lambda me, req, what, detail="": db.log(what, me["username"], "", ip(req), detail)

    @r.get("")
    def listing(req: Request):
        return hub.listing(me_(req))

    # the grant routes come before /{sid}: PUT /grants would otherwise match PUT /{sid}
    @r.get("/grants")
    def grants(scope: str, req: Request):
        return hub.grants(me_(req), scope)

    @r.put("/grants")
    def set_grants(b: GrantsIn, req: Request):
        me = me_(req)
        out = hub.set_grants(me, b.scope, b.grants)
        audit(me, req, "mcp.grants", f"{b.scope}: {', '.join(s['name'] for s in out['servers'] if s['granted'])[:250] or 'none'}")
        return out

    @r.post("/catalog/{key}")
    def install(key: str, b: InstallIn, req: Request):
        me = sudo(req)
        if b.audience not in AUDIENCES: raise HTTPException(400, "Pick who may use it: admins or everyone.")
        s = hub.install(me, key, b.values, b.audience)
        audit(me, req, "mcp.server_add", f"{s['name']} (catalog: {key})")
        return hub.view(s, me)

    @r.post("")
    def create(b: ServerIn, req: Request):
        me = sudo(req)
        s = hub.create(me, b)
        audit(me, req, "mcp.server_add", f"{s['name']} ({s['transport']})")
        return hub.view(s, me)

    @r.put("/{sid}")
    def update(sid: int, b: ServerIn, req: Request):
        me = sudo(req)
        s = hub.update(me, sid, b)
        audit(me, req, "mcp.server_edit", s["name"])
        return hub.view(s, me)

    @r.delete("/{sid}")
    def delete(sid: int, req: Request):
        me = sudo(req)
        name = hub._row(sid)["name"]
        hub.delete(sid)
        audit(me, req, "mcp.server_delete", name)
        return {"ok": True}

    @r.post("/{sid}/test")
    def test(sid: int, req: Request):
        me = admin(req)
        return hub.view(hub.test(sid), me)

    @r.put("/{sid}/allowed")
    def allowed(sid: int, b: AllowedIn, req: Request):
        me = sudo(req)
        s = hub.set_allowed(sid, b.allowed)
        audit(me, req, "mcp.tools_allowed", f"{s['name']}: {', '.join(b.allowed)[:250] or 'none'}")
        return hub.view(s, me)

    r.state = {"mcp": hub}
    return r
