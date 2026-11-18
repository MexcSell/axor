"""DevOps: AXoR's own CI/CD. Pipelines build, test and deploy Source hub repositories on this server (admins only).

A pipeline is one app: a Source hub repository and branch, where its Dockerfile is, an optional test command, and
how it runs (the port it listens on, the host port it's published on, a health check path, memory, CPUs, a volume,
environment variables and secrets). Without a container port it's CI only: build and test.
A run has up to four steps, each with its own log:
- Source: the commit (the branch's head unless one is asked for) is downloaded from GitHub as a tarball with the
  source's token and repacked as the build context: the context folder only, minus what its .dockerignore excludes.
- Build: the AXoR Runner (runner/, a separate service) builds the image with the engine's builder.
- Test: the test command runs in a throwaway container of the new image; a non-zero exit fails the run.
- Deploy: the runner swaps the app's container for the new image, checks its health and rolls back if it fails.
Runs start by hand, on new commits (auto deploy: the branch is polled every DEVOPS_POLL_SECONDS), or as a rollback to
an earlier run's image (the images of the last DEVOPS_KEEP successful runs are kept; failed runs' images are removed).
One run per pipeline at a time and RUNS at once; the rest queue.

AXoR itself never gets the Docker socket for this: only the runner builds and creates containers, and it decides
their settings itself (hardened, see runner/runner.py). AXoR reaches it at RUNNER_URL with a shared secret
(RUNNER_SECRET, or the file RUNNER_SECRET_FILE that the runner writes on first start).
Reads need an admin session; every change (pipelines, runs, cancels, rollbacks, starting and stopping apps) also
needs sudo and is audited. Secrets are stored encrypted, never shown again, and masked in run logs.
"""
import copy, json, logging, os, posixpath, re, tarfile, tempfile, threading, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .secretbox import SecretBox
from .source import API as GITHUB_API, REF, GitHubError, Source, _plain

log = logging.getLogger("devops")
URL = (os.getenv("RUNNER_URL") or "").rstrip("/")
POLL = max(30, int(os.getenv("DEVOPS_POLL_SECONDS", "120")))
CONTEXT_MAX = int(os.getenv("DEVOPS_CONTEXT_MB", "200")) * 2**20
RUNS = max(1, int(os.getenv("DEVOPS_RUNS", "2")))
KEEP = max(1, int(os.getenv("DEVOPS_KEEP", "5")))  # successful runs whose images stay for rollbacks (CI-only pipelines: 1)
BUILD_TIMEOUT = 45 * 60   # longest silence from the runner during a build (it enforces its own build time limit)
LOG_MAX = 300_000         # characters kept per step
LOG_VIEW = 120_000        # characters of each step sent to the page
HISTORY = 30              # runs listed per pipeline
APP = re.compile(r"^[a-z][a-z0-9-]{0,29}$")
ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
REL = re.compile(r"^(?!/)(?!.*(^|/)\.\.(/|$))[A-Za-z0-9._/ -]{0,200}$")
ABS = re.compile(r"^/[A-Za-z0-9._~/-]{1,199}$")
TRIGGERS = ("manual", "push", "rollback")
SETUP = "Start it with `docker compose --profile devops up -d` or ./scripts/run.sh (see DevOps in the README)."

class RunnerError(Exception):
    def __init__(self, msg, status=502):
        super().__init__(msg); self.status = status

class StepError(Exception):
    pass

class Runner:
    """Client for the AXoR Runner."""
    def __init__(self, url=URL):
        self.url, self._secret = url, None

    @property
    def enabled(self): return bool(self.url)

    def secret(self):
        if self._secret is None:
            s = os.getenv("RUNNER_SECRET")
            if not s and os.getenv("RUNNER_SECRET_FILE"):
                try: s = Path(os.getenv("RUNNER_SECRET_FILE")).read_text().strip()
                except OSError: s = None  # the runner hasn't written it yet: try again next call
            self._secret = s
        return self._secret

    def _open(self, method, path, params=None, body=None, data=None, headers=None, timeout=60):
        if not self.url: raise RunnerError("The AXoR Runner isn't set up on this server (RUNNER_URL). " + SETUP, 503)
        if not self.secret(): raise RunnerError("AXoR can't read the runner's secret yet (RUNNER_SECRET / RUNNER_SECRET_FILE).", 503)
        q = "?" + urllib.parse.urlencode(params) if params else ""
        h = {"Authorization": f"Bearer {self.secret()}", **(headers or {})}
        if body is not None: data, h["Content-Type"] = json.dumps(body).encode(), "application/json"
        try:
            return urllib.request.urlopen(urllib.request.Request(self.url + path + q, data=data, headers=h, method=method), timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                self._secret = None  # the runner made a new secret: read the file again next time
                raise RunnerError("The runner rejected AXoR's secret. Check that both share the same RUNNER_SECRET_FILE volume.")
            try: detail = json.load(e).get("detail")
            except ValueError: detail = None
            raise RunnerError(detail if isinstance(detail, str) else f"The runner answered HTTP {e.code}.", e.code if e.code in (400, 404, 409, 413) else 502)
        except (urllib.error.URLError, OSError) as e:
            raise RunnerError(f"Can't reach the AXoR Runner at {self.url} ({getattr(e, 'reason', e)}). " + SETUP)

    def call(self, method, path, params=None, body=None, timeout=60):
        with self._open(method, path, params, body, timeout=timeout) as r:
            data = r.read()
        return json.loads(data) if data.strip() else None

    def stream(self, method, path, params=None, body=None, data=None, headers=None, timeout=600):
        """The runner's newline-delimited JSON, one message at a time."""
        with self._open(method, path, params, body, data, headers, timeout) as r:
            for raw in r:
                if raw.strip():
                    try: yield json.loads(raw)
                    except ValueError: continue

# ---------- build context ----------
def _glob(p):
    """A .dockerignore pattern as a regex: * and ? within a folder, ** across folders, [...] classes."""
    out, i = "", 0
    while i < len(p):
        if p.startswith("**", i):
            i += 2
            if p.startswith("/", i): i += 1; out += "(?:.*/)?"
            else: out += ".*"
            continue
        ch = p[i]
        if ch == "*": out += "[^/]*"
        elif ch == "?": out += "[^/]"
        elif ch == "[" and "]" in p[i + 2:]:
            j = p.index("]", i + 2)
            body = p[i + 1:j]
            out += "[" + ("^" + body[1:] if body[0] in "!^" else body).replace("\\", "\\\\") + "]"; i = j
        elif ch == "\\" and i + 1 < len(p): i += 1; out += re.escape(p[i])
        else: out += re.escape(ch)
        i += 1
    return re.compile(out + r"\Z")

def dockerignore(text):
    rules = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"): continue
        neg = ln.startswith("!")
        ln = ln[1:].strip() if neg else ln
        ln = posixpath.normpath(ln.lstrip("/")) if ln.lstrip("/") else ""
        if ln and ln != ".": rules.append((neg, _glob(ln)))
    return rules

def ignored(path, rules):
    """Docker's rule: the last pattern that matches wins, and a pattern matching a folder matches everything in it."""
    parts = path.split("/")
    prefixes = ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]
    hit = False
    for neg, rx in rules:
        if any(rx.match(x) for x in prefixes): hit = not neg
    return hit

def repack(tgz, context, dockerfile, out):
    """GitHub's tarball (everything under one folder, owner-repo-sha/) -> the build context as a plain tar: the context
    folder's contents at the root, minus what its .dockerignore excludes. Only files, folders and symlinks are kept."""
    with tarfile.open(tgz, "r:gz") as tin:
        members = tin.getmembers()
        top = members[0].name.split("/")[0] if members else ""
        base = posixpath.join(top, context.strip("/")) if context.strip("/") else top
        rel = lambda m: m.name[len(base) + 1:] if m.name.startswith(base + "/") else None
        ign = next((m for m in members if rel(m) == ".dockerignore" and m.isfile()), None)
        rules = dockerignore(tin.extractfile(ign).read().decode("utf-8", "replace")) if ign else []
        found, files, size = False, 0, 0
        with open(out, "wb") as f, tarfile.open(fileobj=f, mode="w") as tout:
            for m in members:
                r = rel(m)
                if not r or not (m.isfile() or m.isdir() or m.issym()): continue
                if r == dockerfile and m.isfile(): found = True  # sent even if .dockerignore lists it, as docker build does
                elif rules and ignored(r, rules): continue
                n = copy.copy(m)
                n.name, n.uid, n.gid, n.uname, n.gname = r, 0, 0, "", ""
                tout.addfile(n, tin.extractfile(m) if m.isfile() else None)
                if m.isfile(): files += 1; size += m.size
    if not found: raise StepError(f"There's no {dockerfile} in {context.strip('/') or 'the repository root'} at this commit.")
    return {"files": files, "size": size, "dockerignore": len(rules)}

# ---------- requests ----------
class PipelineIn(BaseModel):
    app: str = Field(..., max_length=30)
    repo: str = Field(..., max_length=201)
    branch: str = Field(..., max_length=250)
    context: str = Field("", max_length=200)
    dockerfile: str = Field("Dockerfile", max_length=200)
    test: str = Field("", max_length=4000)
    test_timeout: int = Field(600, ge=10, le=7200)
    port: int | None = Field(None, ge=1, le=65535)
    host_port: int | None = Field(None, ge=1, le=65535)
    health: str = Field("", max_length=200)
    health_timeout: int = Field(60, ge=5, le=600)
    memory: int = Field(512, ge=32, le=262144)
    cpus: float = Field(1.0, ge=0.1, le=256)
    volume: str = Field("", max_length=200)
    env: dict[str, str] = {}
    secrets: dict[str, str | None] = {}  # name -> new value; None or "" keeps the stored one; names left out are deleted
    auto: bool = False

class RunIn(BaseModel):
    ref: str = Field("", max_length=250)  # a branch, tag or commit; empty = the pipeline's branch

class AppAct(BaseModel):
    action: str

class _Log:
    """A step's log: buffered, flushed to the database about once a second, secrets masked, the end kept when it's long."""
    def __init__(self, db, sid, masks):
        self.db, self.sid, self.masks, self.text, self.last = db, sid, masks, "", 0.0

    def __call__(self, text):
        self.text += text
        if len(self.text) > LOG_MAX: self.text = "[earlier output cut]\n" + self.text[-(LOG_MAX - 40):]
        if time.time() - self.last > 1: self.flush()

    def flush(self):
        t = self.text
        for m in self.masks: t = t.replace(m, "••••")
        self.db.q("UPDATE devops_steps SET log=? WHERE id=?", (t, self.sid))
        self.last = time.time()

class DevOps:
    def __init__(self, db, source: Source, data_dir, runner=None):
        self.db, self.src, self.box = db, source, SecretBox(db, data_dir)
        self.runner = runner or Runner()
        self.lock, self.active, self.cancelled = threading.Lock(), {}, set()  # active: pipeline id -> run id
        db.q("""CREATE TABLE IF NOT EXISTS devops_pipelines (
                  id INTEGER PRIMARY KEY, app TEXT UNIQUE, repo TEXT, branch TEXT, context TEXT DEFAULT '', dockerfile TEXT DEFAULT 'Dockerfile',
                  test TEXT DEFAULT '', test_timeout INTEGER DEFAULT 600, port INTEGER, host_port INTEGER, health TEXT DEFAULT '',
                  health_timeout INTEGER DEFAULT 60, memory INTEGER DEFAULT 512, cpus REAL DEFAULT 1, volume TEXT DEFAULT '',
                  env TEXT DEFAULT '{}', secrets TEXT DEFAULT '[]', auto INTEGER DEFAULT 0, live_run INTEGER,
                  created_by TEXT, created REAL, updated REAL)""")
        db.q("""CREATE TABLE IF NOT EXISTS devops_runs (
                  id INTEGER PRIMARY KEY, pipeline_id INTEGER, number INTEGER, trigger TEXT, actor TEXT, ref TEXT, sha TEXT, message TEXT,
                  author TEXT, status TEXT, image TEXT, error TEXT, rollback_of INTEGER, created REAL, started REAL, finished REAL)""")
        db.q("""CREATE TABLE IF NOT EXISTS devops_steps (
                  id INTEGER PRIMARY KEY, run_id INTEGER, seq INTEGER, name TEXT, status TEXT, started REAL, finished REAL, log TEXT DEFAULT '')""")
        db.q("CREATE INDEX IF NOT EXISTS devops_runs_pipeline ON devops_runs (pipeline_id, id)")
        db.q("CREATE INDEX IF NOT EXISTS devops_steps_run ON devops_steps (run_id, seq)")
        # runs cut off by a restart; the runner may still have finished their last step
        now = time.time()
        for r in db.q("SELECT id FROM devops_runs WHERE status='running'"):
            db.q("UPDATE devops_steps SET status=CASE WHEN status='running' THEN 'failed' ELSE 'skipped' END, finished=? WHERE run_id=? AND status IN ('running','pending')", (now, r["id"]))
            db.q("UPDATE devops_runs SET status='failed', error='AXoR restarted during this run.', finished=? WHERE id=?", (now, r["id"]))

    # ---------- pipelines ----------
    def _pipeline(self, pid):
        p = self.db.q("SELECT * FROM devops_pipelines WHERE id=?", (pid,), one=True)
        if not p: raise HTTPException(404, "That pipeline doesn't exist.")
        return p

    def _by_app(self, name):
        p = self.db.q("SELECT * FROM devops_pipelines WHERE app=?", ((name or "").strip().lower(),), one=True)
        if not p: raise LookupError(f"No pipeline named {name!r}. Call devops_overview for the pipelines.")
        return p

    def _env(self, p):
        """Environment for tests and the app: plain variables, then secrets."""
        out = dict(json.loads(p["env"] or "{}"))
        for k in json.loads(p["secrets"] or "[]"):
            v = self.box.get(f"devops:{p['id']}:{k}")
            if v is not None: out[k] = v
        return out

    def _masks(self, p):
        vals = [self.box.get(f"devops:{p['id']}:{k}") for k in json.loads(p["secrets"] or "[]")]
        return sorted({v for v in vals if v and len(v) >= 4}, key=len, reverse=True)

    def _clean(self, b: PipelineIn, pid=None):
        app_ = b.app.strip().lower()
        if not APP.match(app_): raise HTTPException(400, "Name the app with 1-30 lowercase letters, digits or dashes, starting with a letter.")
        owner, _, name = b.repo.strip().partition("/")
        repo = self.src.allowed(owner, name)  # only Source hub repositories
        branch = b.branch.strip()
        if not REF.match(branch): raise HTTPException(400, "That isn't a valid branch name.")
        context = posixpath.normpath(b.context.strip().strip("/")) if b.context.strip().strip("/") else ""
        dockerfile = b.dockerfile.strip() or "Dockerfile"
        if not REL.match(context): raise HTTPException(400, "The context folder must be a path inside the repository, such as drive.")
        if not REL.match(dockerfile) or not dockerfile: raise HTTPException(400, "The Dockerfile path must be inside the context folder.")
        if (b.port is None) != (b.host_port is None): raise HTTPException(400, "Deploying needs both the app's port and the host port (leave both empty for CI only).")
        if b.host_port is not None:
            other = self.db.q("SELECT app FROM devops_pipelines WHERE host_port=? AND id IS NOT ?", (b.host_port, pid), one=True)
            if other: raise HTTPException(409, f"Host port {b.host_port} is already used by {other['app']}.")
        health = b.health.strip()
        if health and not ABS.match(health): raise HTTPException(400, "The health check path must start with / (for example /health).")
        volume = b.volume.strip().rstrip("/")
        if volume and not ABS.match(volume): raise HTTPException(400, "The volume path must be a folder in the container, such as /data.")
        for k in [*b.env, *b.secrets]:
            if not ENV_KEY.match(k): raise HTTPException(400, f"{k!r} isn't a valid environment variable name.")
        if set(b.env) & set(b.secrets): raise HTTPException(400, f"{sorted(set(b.env) & set(b.secrets))[0]} is both a variable and a secret.")
        if len(b.env) + len(b.secrets) > 100: raise HTTPException(400, "100 variables and secrets at most.")
        if any(len(v) > 8192 for v in [*b.env.values(), *(s or "" for s in b.secrets.values())]): raise HTTPException(400, "Values are 8192 characters at most.")
        return {"app": app_, "repo": repo, "branch": branch, "context": context, "dockerfile": dockerfile, "test": b.test.strip(),
                "test_timeout": b.test_timeout, "port": b.port, "host_port": b.host_port, "health": health, "health_timeout": b.health_timeout,
                "memory": b.memory, "cpus": round(b.cpus, 2), "volume": volume, "env": json.dumps(b.env), "auto": int(b.auto)}

    def _save_secrets(self, pid, given, keep=()):
        new = next((k for k, v in given.items() if not v and k not in keep), None)
        if new: raise HTTPException(400, f"Enter a value for the new secret {new}.")
        for k, v in given.items():
            if v: self.box.set(f"devops:{pid}:{k}", v)
        for k in set(keep) - set(given): self.box.delete(f"devops:{pid}:{k}")
        self.db.q("UPDATE devops_pipelines SET secrets=? WHERE id=?", (json.dumps(sorted(given)), pid))

    def create(self, me, b: PipelineIn, ip):
        v = self._clean(b)
        if self.db.q("SELECT 1 FROM devops_pipelines WHERE app=?", (v["app"],), one=True): raise HTTPException(409, f"There's already a pipeline named {v['app']}.")
        now = time.time()
        self.db.q(f"INSERT INTO devops_pipelines ({', '.join(v)}, created_by, created, updated) VALUES ({', '.join('?' * len(v))}, ?, ?, ?)",
                  (*v.values(), me["username"], now, now))
        pid = self.db.q("SELECT id FROM devops_pipelines WHERE app=?", (v["app"],), one=True)["id"]
        try: self._save_secrets(pid, b.secrets)
        except HTTPException:
            self.db.q("DELETE FROM devops_pipelines WHERE id=?", (pid,)); raise
        self.db.log("devops.create", me["username"], v["app"], ip, f"{v['repo']}@{v['branch']}" + (f" → :{v['host_port']}" if v["host_port"] else " (CI only)"))
        return self.view(pid)

    def update(self, me, pid, b: PipelineIn, ip):
        p = self._pipeline(pid)
        if b.app.strip().lower() != p["app"]: raise HTTPException(400, "An app's name can't change: its containers are named after it. Make a new pipeline instead.")
        v = self._clean(b, pid)
        self._save_secrets(pid, b.secrets, json.loads(p["secrets"] or "[]"))
        self.db.q(f"UPDATE devops_pipelines SET {', '.join(k + '=?' for k in v)}, updated=? WHERE id=?", (*v.values(), time.time(), pid))
        changed = [k for k in v if str(v[k]) != str(p[k])] + (["secrets"] if sorted(b.secrets) != json.loads(p["secrets"] or "[]") or any(b.secrets.values()) else [])
        self.db.log("devops.edit", me["username"], p["app"], ip, ", ".join(changed) or "no changes")
        return self.view(pid)

    def delete(self, me, pid, volume, ip):
        p = self._pipeline(pid)
        if p["id"] in self.active: raise HTTPException(409, "A run is in progress. Cancel it first.")
        gone = {}
        try: gone = self.runner.call("DELETE", f"/apps/{p['app']}", {"volume": int(volume)}, timeout=120)
        except RunnerError as e:
            if e.status != 503: raise  # the runner isn't set up: nothing of this app can be running
        for k in json.loads(p["secrets"] or "[]"): self.box.delete(f"devops:{pid}:{k}")
        self.db.q("DELETE FROM devops_steps WHERE run_id IN (SELECT id FROM devops_runs WHERE pipeline_id=?)", (pid,))
        self.db.q("DELETE FROM devops_runs WHERE pipeline_id=?", (pid,))
        self.db.q("DELETE FROM devops_pipelines WHERE id=?", (pid,))
        self.db.log("devops.delete", me["username"], p["app"], ip, f"{gone.get('containers', 0)} containers, {gone.get('images', 0)} images"
                    + (", volume" if gone.get("volume") else ""))
        return {"ok": True, **gone}

    # ---------- runs ----------
    def queue(self, p, trigger, actor, ref="", sha=None, rollback_of=None, image=None):
        with self.lock:
            n = (self.db.q("SELECT MAX(number) n FROM devops_runs WHERE pipeline_id=?", (p["id"],), one=True)["n"] or 0) + 1
            self.db.q("""INSERT INTO devops_runs (pipeline_id, number, trigger, actor, ref, sha, status, image, rollback_of, created)
                         VALUES (?,?,?,?,?,?,'queued',?,?,?)""", (p["id"], n, trigger, actor, ref or p["branch"], sha, image, rollback_of, time.time()))
            rid = self.db.q("SELECT id FROM devops_runs WHERE pipeline_id=? AND number=?", (p["id"], n), one=True)["id"]
            steps = ["deploy"] if trigger == "rollback" else ["source", "build"] + (["test"] if p["test"] else []) + (["deploy"] if p["port"] else [])
            for i, s in enumerate(steps): self.db.q("INSERT INTO devops_steps (run_id, seq, name, status) VALUES (?,?,?,'pending')", (rid, i, s))
        self._kick()
        return rid

    def _kick(self):
        """Starts queued runs: oldest first, one per pipeline, RUNS at once."""
        with self.lock:
            for r in self.db.q("SELECT id, pipeline_id FROM devops_runs WHERE status='queued' ORDER BY id"):
                if len(self.active) >= RUNS: break
                if r["pipeline_id"] in self.active: continue
                self.active[r["pipeline_id"]] = r["id"]
                self.db.q("UPDATE devops_runs SET status='running', started=? WHERE id=?", (time.time(), r["id"]))
                threading.Thread(target=self._run, args=(r["id"],), daemon=True, name=f"devops-run-{r['id']}").start()

    def _run(self, rid):
        run = self.db.q("SELECT * FROM devops_runs WHERE id=?", (rid,), one=True)
        p = self.db.q("SELECT * FROM devops_pipelines WHERE id=?", (run["pipeline_id"],), one=True)
        ctx, status, error = {"image": run["image"], "files": []}, "success", None
        try:
            env, masks = self._env(p), self._masks(p)
            for s in self.db.q("SELECT * FROM devops_steps WHERE run_id=? ORDER BY seq", (rid,)):
                if rid in self.cancelled: status, error = "cancelled", "Cancelled."; break
                self.db.q("UPDATE devops_steps SET status='running', started=? WHERE id=?", (time.time(), s["id"]))
                out = _Log(self.db, s["id"], masks)
                try:
                    getattr(self, "_step_" + s["name"])(p, run, out, ctx, env)
                    result = "success"
                except StepError as e:
                    result, error = ("cancelled", "Cancelled.") if rid in self.cancelled else ("failed", str(e))
                    out(f"\n{error}\n")
                except (RunnerError, GitHubError) as e:
                    result, error = "failed", str(e)
                    out(f"\n{error}\n")
                out.flush()
                self.db.q("UPDATE devops_steps SET status=?, finished=? WHERE id=?", (result, time.time(), s["id"]))
                if result != "success": status = result; break
        except Exception as e:
            log.exception("devops run %s", rid)
            status, error = "failed", f"Internal error: {e}"
        finally:
            for f in ctx["files"]:
                try: os.unlink(f)
                except OSError: pass
            now = time.time()
            self.db.q("UPDATE devops_steps SET status='skipped', finished=? WHERE run_id=? AND status IN ('pending','running')", (now, rid))
            self.db.q("UPDATE devops_runs SET status=?, error=?, image=COALESCE(?, image), finished=? WHERE id=?", (status, error, ctx["image"], now, rid))
            if status == "success" and any(s["name"] == "deploy" for s in self.db.q("SELECT name FROM devops_steps WHERE run_id=?", (rid,))):
                self.db.q("UPDATE devops_pipelines SET live_run=? WHERE id=?", (rid, p["id"]))
            if ctx["image"]: self._prune(p)
            with self.lock:
                self.active.pop(p["id"], None); self.cancelled.discard(rid)
            self._kick()

    def _prune(self, p):
        """Keeps the images of the last few successful runs (rollback targets); failed runs' images and older ones go."""
        keep = [r["image"] for r in self.db.q("""SELECT image FROM devops_runs WHERE pipeline_id=? AND status='success' AND image IS NOT NULL
                                                 GROUP BY image ORDER BY MAX(id) DESC LIMIT ?""", (p["id"], KEEP if p["port"] else 1))]
        try: self.runner.call("POST", f"/apps/{p['app']}/prune", body={"keep": keep}, timeout=120)
        except RunnerError as e: log.info("devops prune %s: %s", p["app"], e)

    def _step_source(self, p, run, out, ctx, env):
        want = run["sha"] or run["ref"] or p["branch"]
        c = self.src.call("GET", f"/repos/{p['repo']}/commits/{urllib.parse.quote(want, safe='/')}")["data"]
        sha, msg = c["sha"], (c.get("commit") or {}).get("message", "").split("\n")[0][:200]
        author = ((c.get("author") or {}).get("login") or ((c.get("commit") or {}).get("author") or {}).get("name") or "")[:60]
        self.db.q("UPDATE devops_runs SET sha=?, message=?, author=? WHERE id=?", (sha, msg, author, run["id"]))
        run.update(sha=sha)
        out(f"{p['repo']} at {want if want != sha else sha[:7]}: {sha[:7]} {msg}" + (f" ({author})" if author else "") + "\n")
        tgz = self._tarball(p["repo"], sha, ctx)
        out(f"Downloaded the snapshot ({os.path.getsize(tgz) / 2**20:.1f} MB).\n")
        fd, tar = tempfile.mkstemp(prefix="devops-context-", suffix=".tar"); os.close(fd); ctx["files"].append(tar)
        info = repack(tgz, p["context"], p["dockerfile"], tar)
        if os.path.getsize(tar) > CONTEXT_MAX: raise StepError(f"The build context is over {CONTEXT_MAX // 2**20} MB. Exclude large files with .dockerignore.")
        out(f"Build context: {info['files']} files, {info['size'] / 2**20:.1f} MB from {p['context'] or 'the repository root'}"
            + (f", {info['dockerignore']} .dockerignore rules applied" if info["dockerignore"] else "") + ".\n")
        ctx["context"] = tar

    def _tarball(self, repo, sha, ctx):
        """The commit as GitHub's tarball, saved to a temporary file. GitHub redirects to signed storage, which gets no token."""
        conn = self.src.source_of(repo)
        token = conn and self.src.token(conn["id"])
        if not token: raise StepError("GitHub isn't connected for this repository (Source hub).")
        req = urllib.request.Request(f"{(conn.get('api') or GITHUB_API)}/repos/{repo}/tarball/{sha}", headers={
            "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "subnet-scout"})
        try: r = _plain.open(req, timeout=30)
        except urllib.error.HTTPError as e:
            if e.code not in (301, 302, 303, 307, 308) or not e.headers.get("Location"): raise Source._error(e)
            try: r = urllib.request.urlopen(e.headers["Location"], timeout=60)
            except (urllib.error.URLError, OSError) as e2: raise StepError(f"Couldn't download the snapshot ({getattr(e2, 'reason', e2)}).")
        except (urllib.error.URLError, OSError) as e:
            raise StepError(f"Can't reach GitHub ({getattr(e, 'reason', e)}).")
        fd, path = tempfile.mkstemp(prefix="devops-src-", suffix=".tar.gz"); ctx["files"].append(path)
        size = 0
        with r, os.fdopen(fd, "wb") as f:
            while chunk := r.read(1 << 16):
                size += len(chunk)
                if size > CONTEXT_MAX * 2: raise StepError(f"The repository snapshot is over {CONTEXT_MAX * 2 // 2**20} MB.")
                f.write(chunk)
        return path

    def _step_build(self, p, run, out, ctx, env):
        tag = f"r{run['number']}-{run['sha'][:7]}"
        with open(ctx["context"], "rb") as f:
            for m in self.runner.stream("POST", "/build", {"name": p["app"], "tag": tag, "dockerfile": p["dockerfile"], "job": f"run{run['id']}"},
                                        data=f, headers={"Content-Type": "application/x-tar", "Content-Length": str(os.path.getsize(ctx["context"]))},
                                        timeout=BUILD_TIMEOUT):
                if "log" in m: out(m["log"])
                elif m.get("error"): raise StepError(m["error"])
                elif m.get("done"):
                    ctx["image"] = m["image"]
                    out(f"Built {m['image']} ({m.get('size', 0) / 2**20:.0f} MB).\n")
        if not ctx["image"]: raise StepError("The runner ended the build without an image.")
        self.db.q("UPDATE devops_runs SET image=? WHERE id=?", (ctx["image"], run["id"]))

    def _step_test(self, p, run, out, ctx, env):
        out(f"$ {p['test']}\n")
        body = {"app": p["app"], "image": ctx["image"], "command": p["test"], "env": env, "timeout": p["test_timeout"],
                "memory_mb": max(p["memory"], 256), "cpus": p["cpus"], "job": f"run{run['id']}"}
        for m in self.runner.stream("POST", "/test", body=body, timeout=p["test_timeout"] + 120):
            if "log" in m: out(m["log"])
            elif m.get("error"): raise StepError(m["error"])
            elif m.get("done"):
                if m.get("exit"): raise StepError(f"The tests failed (exit code {m['exit']}).")
                out("Tests passed.\n")

    def _step_deploy(self, p, run, out, ctx, env):
        if not ctx["image"]: raise StepError("There's no image to deploy.")
        body = {"app": p["app"], "image": ctx["image"], "port": p["port"], "host_port": p["host_port"], "env": env, "health": p["health"],
                "health_timeout": p["health_timeout"], "memory_mb": p["memory"], "cpus": p["cpus"], "volume": p["volume"], "job": f"run{run['id']}"}
        for m in self.runner.stream("POST", "/deploy", body=body, timeout=p["health_timeout"] + 300):
            if "log" in m: out(m["log"])
            elif m.get("error"):
                raise StepError(f"Deploy failed: {m['error']}." + (" The previous version was restored." if m.get("rolled_back") else ""))
            elif m.get("done"): out(f"Live on port {m['host_port']}.\n")

    def run(self, me, pid, ref, ip):
        p = self._pipeline(pid)
        ref = ref.strip()
        if ref and not REF.match(ref): raise HTTPException(400, "That isn't a valid branch, tag or commit.")
        rid = self.queue(p, "manual", me["username"], ref)
        self.db.log("devops.run", me["username"], p["app"], ip, ref or p["branch"])
        return self.run_view(rid)

    def rollback(self, me, rid, ip):
        r = self._run_row(rid)
        p = self._pipeline(r["pipeline_id"])
        if r["status"] != "success" or not r["image"]: raise HTTPException(400, "Only a successful run's image can be deployed again.")
        if not p["port"]: raise HTTPException(400, "This pipeline doesn't deploy (it has no port).")
        kept = {i["image"] for i in self.runner.call("GET", f"/apps/{p['app']}/images")}
        if r["image"] not in kept:
            raise HTTPException(410, f"Run #{r['number']}'s image was cleaned up: only the last {KEEP} successful runs' images are kept. Re-run that commit instead.")
        nid = self.queue(p, "rollback", me["username"], r["ref"], r["sha"], rollback_of=rid, image=r["image"])
        self.db.q("UPDATE devops_runs SET message=?, author=? WHERE id=?", (r["message"], r["author"], nid))
        self.db.log("devops.rollback", me["username"], p["app"], ip, f"to run #{r['number']} ({(r['sha'] or '')[:7]})")
        return self.run_view(nid)

    def cancel(self, me, rid, ip):
        r = self._run_row(rid)
        p = self._pipeline(r["pipeline_id"])
        with self.lock:
            if r["status"] == "queued":
                now = time.time()
                self.db.q("UPDATE devops_runs SET status='cancelled', error='Cancelled.', finished=? WHERE id=?", (now, rid))
                self.db.q("UPDATE devops_steps SET status='skipped', finished=? WHERE run_id=?", (now, rid))
            elif r["status"] == "running": self.cancelled.add(rid)
            else: raise HTTPException(400, "This run has already finished.")
        if r["status"] == "running":
            try: self.runner.call("POST", f"/jobs/run{rid}/cancel")
            except RunnerError: pass  # the step stops at its next check anyway
        self.db.log("devops.cancel", me["username"], p["app"], ip, f"run #{r['number']}")
        return {"ok": True}

    # ---------- auto deploy ----------
    def start(self):
        threading.Thread(target=self._poller, daemon=True, name="devops-poll").start()
        self._kick()

    def _poller(self):
        while True:
            time.sleep(POLL)
            try: self.poll()
            except Exception: log.exception("devops poll")

    def poll(self):
        """Queues a run for every auto-deploy pipeline whose branch moved since its last run."""
        for p in self.db.q("SELECT * FROM devops_pipelines WHERE auto=1"):
            if self.db.q("SELECT 1 FROM devops_runs WHERE pipeline_id=? AND status IN ('queued','running')", (p["id"],), one=True): continue
            try: sha = self.src.call("GET", f"/repos/{p['repo']}/branches/{urllib.parse.quote(p['branch'], safe='/')}")["data"]["commit"]["sha"]
            except (GitHubError, KeyError, TypeError) as e:
                log.info("devops poll %s: %s", p["app"], e); continue
            last = self.db.q("SELECT sha FROM devops_runs WHERE pipeline_id=? AND trigger!='rollback' AND sha IS NOT NULL ORDER BY id DESC LIMIT 1",
                             (p["id"],), one=True)
            if not last or last["sha"] != sha:
                self.queue(p, "push", "auto", p["branch"], sha)
                self.db.log("devops.run", "auto", p["app"], "", f"new commit {sha[:7]} on {p['branch']}")

    # ---------- views ----------
    def _run_row(self, rid):
        r = self.db.q("SELECT * FROM devops_runs WHERE id=?", (rid,), one=True)
        if not r: raise HTTPException(404, "That run doesn't exist.")
        return r

    def _steps(self, rids):
        if not rids: return {}
        out = {}
        for s in self.db.q(f"SELECT run_id, seq, name, status, started, finished FROM devops_steps WHERE run_id IN ({','.join('?' * len(rids))}) ORDER BY seq", tuple(rids)):
            out.setdefault(s["run_id"], []).append({k: s[k] for k in ("seq", "name", "status", "started", "finished")})
        return out

    @staticmethod
    def _run_out(r, steps, numbers=None):
        return {**{k: r[k] for k in ("id", "number", "trigger", "actor", "ref", "sha", "message", "author", "status", "image", "error",
                                     "created", "started", "finished")},
                "rollback_of": (numbers or {}).get(r["rollback_of"]), "steps": steps.get(r["id"], [])}

    def _shape(self, p, live, last=None):
        return {**{k: p[k] for k in ("id", "app", "repo", "branch", "context", "dockerfile", "test", "test_timeout", "port", "host_port", "health",
                                     "health_timeout", "memory", "cpus", "volume", "created_by", "created", "updated")},
                "env": json.loads(p["env"] or "{}"), "secrets": json.loads(p["secrets"] or "[]"), "auto": bool(p["auto"]),
                "live": live, "live_run": p["live_run"], "last": last}

    def _runner_info(self):
        try: return self.runner.call("GET", "/info", timeout=10), None
        except RunnerError as e: return None, str(e)

    def overview(self):
        info, err = self._runner_info()
        apps = {a["app"]: a for a in (info or {}).get("apps", [])}
        ps = self.db.q("SELECT * FROM devops_pipelines ORDER BY app")
        lasts = {r["pipeline_id"]: r for r in self.db.q("SELECT * FROM devops_runs WHERE id IN (SELECT MAX(id) FROM devops_runs GROUP BY pipeline_id)")}
        steps = self._steps([r["id"] for r in lasts.values()])
        week = self.db.q("SELECT status, COUNT(*) n FROM devops_runs WHERE created>? AND status IN ('success','failed') GROUP BY status", (time.time() - 7 * 86400,))
        return {"enabled": self.runner.enabled, "github": self.src.configured(), "repos": self.src.repos(),
                "runner": {k: v for k, v in (info or {}).items() if k != "apps"} if info else {"error": err},
                "week": {r["status"]: r["n"] for r in week},
                "pipelines": [self._shape(p, apps.get(p["app"]), self._run_out(lasts[p["id"]], steps) if p["id"] in lasts else None) for p in ps]}

    def view(self, pid):
        p = self._pipeline(pid)
        info, err = self._runner_info()
        live = next((a for a in (info or {}).get("apps", []) if a["app"] == p["app"]), None)
        runs = self.db.q("SELECT * FROM devops_runs WHERE pipeline_id=? ORDER BY id DESC LIMIT ?", (pid, HISTORY))
        numbers = {r["id"]: r["number"] for r in self.db.q("SELECT id, number FROM devops_runs WHERE pipeline_id=?", (pid,))}
        steps = self._steps([r["id"] for r in runs])
        images = []
        if info and p["port"]:
            try: images = [i["image"] for i in self.runner.call("GET", f"/apps/{p['app']}/images")]
            except RunnerError: pass
        out = self._shape(p, live)
        out.update(runs=[{**self._run_out(r, steps, numbers), "kept": r["image"] in images} for r in runs], runner_error=err)
        return out

    def run_view(self, rid):
        r = self._run_row(rid)
        numbers = {x["id"]: x["number"] for x in self.db.q("SELECT id, number FROM devops_runs WHERE pipeline_id=?", (r["pipeline_id"],))}
        out = self._run_out(r, {}, numbers)
        out["app"] = self.db.q("SELECT app FROM devops_pipelines WHERE id=?", (r["pipeline_id"],), one=True)["app"]
        out["pipeline_id"] = r["pipeline_id"]
        out["steps"] = [{**{k: s[k] for k in ("seq", "name", "status", "started", "finished")}, "log": s["log"][-LOG_VIEW:], "cut": len(s["log"]) > LOG_VIEW}
                        for s in self.db.q("SELECT * FROM devops_steps WHERE run_id=? ORDER BY seq", (rid,))]
        return out

    def app_logs(self, pid, tail=300):
        p = self._pipeline(pid)
        text = self.runner.call("GET", f"/apps/{p['app']}/logs", {"tail": tail}, timeout=30)["text"]
        for m in self._masks(p): text = text.replace(m, "••••")
        return {"app": p["app"], "text": text}

    def app_action(self, me, pid, action, ip):
        p = self._pipeline(pid)
        if action not in ("start", "stop", "restart"): raise HTTPException(400, "Unknown action.")
        r = self.runner.call("POST", f"/apps/{p['app']}/{action}", timeout=90)
        self.db.log("devops." + action, me["username"], p["app"], ip, "")
        return r

    # ---------- agents (read-only) ----------
    def agent_overview(self):
        o = self.overview()
        def last(r):
            if not r: return None
            failed = next((s["name"] for s in r["steps"] if s["status"] == "failed"), None)
            return {"run": r["number"], "status": r["status"], "trigger": r["trigger"], "commit": (r["sha"] or "")[:7], "message": r["message"],
                    "when": _when(r["created"]), "took_s": round(r["finished"] - r["started"]) if r["finished"] and r["started"] else None,
                    "failed_step": failed, "error": r["error"]}
        return {"runner": o["runner"], "runs_7d": o["week"], "pipelines": [{
            "app": p["app"], "repo": p["repo"], "branch": p["branch"], "auto_deploy": p["auto"], "deploys": bool(p["port"]),
            "host_port": p["host_port"], "health": p["health"] or None, "tests": p["test"] or None, "memory_mb": p["memory"], "cpus": p["cpus"],
            "env": sorted(p["env"]), "secrets": p["secrets"], "live": {k: p["live"][k] for k in ("state", "status", "image")} if p["live"] else None,
            "last_run": last(p["last"])} for p in o["pipelines"]],
            **({"note": "No pipelines yet. An administrator can create them in the DevOps view."} if not o["pipelines"] else {})}

    def agent_run(self, name, number=0):
        p = self._by_app(name)
        r = self.db.q("SELECT id FROM devops_runs WHERE pipeline_id=?" + (" AND number=?" if number else "") + " ORDER BY id DESC LIMIT 1",
                      (p["id"], number) if number else (p["id"],), one=True)
        if not r: return {"app": p["app"], "note": "No runs yet." if not number else f"No run #{number}."}
        v = self.run_view(r["id"])
        return {"app": p["app"], "run": v["number"], "status": v["status"], "trigger": v["trigger"], "actor": v["actor"], "ref": v["ref"],
                "commit": (v["sha"] or "")[:7], "message": v["message"], "image": v["image"], "error": v["error"], "when": _when(v["created"]),
                "steps": [{"name": s["name"], "status": s["status"],
                           "took_s": round(s["finished"] - s["started"]) if s["finished"] and s["started"] else None,
                           "log_tail": s["log"][-(3000 if s["status"] == "failed" else 500):]} for s in v["steps"]]}

    def agent_logs(self, name, lines=100):
        p = self._by_app(name)
        try: return {"app": p["app"], "logs": self.app_logs(p["id"], max(10, min(int(lines or 100), 300)))["text"][-6000:]}
        except RunnerError as e: return {"app": p["app"], "error": str(e)}
        except HTTPException as e: return {"app": p["app"], "error": e.detail}

def _when(ts):
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(ts)) if ts else None

def build(db, admin_state, ip, data_dir, source):
    r = APIRouter(prefix="/api/devops")
    admin, sudo = admin_state["admin"], admin_state["sudo"]
    d = DevOps(db, source, data_dir)
    r.state = {"devops": d}

    def call(fn, *a):
        try: return fn(*a)
        except RunnerError as e: raise HTTPException(e.status, str(e))
        except GitHubError as e: raise HTTPException(e.status, str(e))

    @r.get("")
    def overview(req: Request):
        admin(req)
        return d.overview()

    @r.post("/sudo")
    def unlock(req: Request):  # asked before the pipeline form opens, so a sudo prompt can't replace a half-filled form
        sudo(req)
        return {"ok": True}

    @r.post("/pipelines")
    def create(b: PipelineIn, req: Request):
        return call(d.create, sudo(req), b, ip(req))

    @r.get("/pipelines/{pid}")
    def view(pid: int, req: Request):
        admin(req)
        return d.view(pid)

    @r.put("/pipelines/{pid}")
    def update(pid: int, b: PipelineIn, req: Request):
        return call(d.update, sudo(req), pid, b, ip(req))

    @r.delete("/pipelines/{pid}")
    def delete(pid: int, req: Request, volume: bool = False):
        return call(d.delete, sudo(req), pid, volume, ip(req))

    @r.post("/pipelines/{pid}/run")
    def run(pid: int, b: RunIn, req: Request):
        return call(d.run, sudo(req), pid, b.ref, ip(req))

    @r.get("/pipelines/{pid}/logs")
    def logs(pid: int, req: Request, tail: int = 300):
        admin(req)
        return call(d.app_logs, pid, max(1, min(tail, 5000)))

    @r.post("/pipelines/{pid}/app")
    def app_action(pid: int, a: AppAct, req: Request):
        return call(d.app_action, sudo(req), pid, a.action, ip(req))

    @r.get("/runs/{rid}")
    def run_view(rid: int, req: Request):
        admin(req)
        return d.run_view(rid)

    @r.post("/runs/{rid}/cancel")
    def cancel(rid: int, req: Request):
        return call(d.cancel, sudo(req), rid, ip(req))

    @r.post("/runs/{rid}/rollback")
    def rollback(rid: int, req: Request):
        return call(d.rollback, sudo(req), rid, ip(req))

    return r
