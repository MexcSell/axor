"""Source hub: the team's GitHub repositories and their CI/CD (GitHub Actions) inside Subnet Scout.

Admins connect one or more sources: a GitHub token for github.com or a GitHub Enterprise Server, each with its own
account, and pick which repositories of each source the hub shows (several at a time). Sources can be added and
deleted; deleting one removes its token and its repositories from the hub. Every repository belongs to exactly one
source, and each GitHub call uses that source's token and server, so the URLs (/repos/owner/name) stay the same.
Before any source is saved, the single connection of earlier versions (a token saved in the app, or
SOURCE_GITHUB_TOKEN; it's separate from GITHUB_TOKEN, which only reads subnet news) is the source "main". Everyone signed in can browse those repositories: branches, commits with their CI
status, open pull requests, workflow runs with jobs, steps and logs, and deployments. Admins also run workflows
(workflow_dispatch, with the workflow's own inputs), re-run, re-run failed jobs, cancel runs, and enable or disable
workflows; every such action is audited.

Token permissions: a fine-grained token with read access to Contents, Metadata, Pull requests and Deployments,
and read/write access to Actions on the chosen repositories (or a classic token with the `repo` and `workflow`
scopes). Only repositories on the hub's list can be reached through the API, whatever else the token can see. The Code tab
shows folders and text files at any branch; files that look like secrets (.env files, keys, wallets) are listed but
their contents are never shown, for anyone.
GitHub is called from the server with a short shared cache, so browsers never see a token and the rate limit
isn't multiplied by viewers. SOURCE_GITHUB_API_URL is the default server (GitHub Enterprise: https://host/api/v3);
each source can name its own.
"""
import base64, json, logging, os, re, secrets, threading, time, urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

import yaml
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .secretbox import SecretBox, mask, fingerprint

log = logging.getLogger("source")
API = os.getenv("SOURCE_GITHUB_API_URL", "https://api.github.com").rstrip("/")
NAME = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
REF = re.compile(r"^[^\s~^:?*\[\\]{1,250}$")  # git's own ref rules, roughly
LOG_TAIL = 200_000
FILE_MAX = 400_000   # characters of a file shown in the Code tab
README = re.compile(r"^readme(\.(md|markdown|rst|txt))?$", re.I)
# files that look like secrets are listed in the Code tab but never shown, for anyone: open them on GitHub
SECRET = re.compile(r"(^|/)(\.env(rc|\.[^/]*)?|[^/]*\.(pem|key|p12|pfx|jks|keystore|ppk|kdbx)|id_(rsa|dsa|ecdsa|ed25519)|\.netrc|\.pgpass|\.npmrc|\.pypirc"
                    r"|[^/]*(secret|credential|apikey|api_key|private_key)[^/]*|([^/]*[._-])?tokens?([._-][^/]*)?|coldkey|hotkey|coldkeypub\.txt)$|(^|/)wallets/", re.I)
MAX_REPOS = 30       # across all sources
MAX_SOURCES = 8
TOKEN = re.compile(r"(gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|[0-9a-f]{40})")

class GitHubError(Exception):
    def __init__(self, msg, status=502):
        super().__init__(msg); self.status = status

class SourceIn(BaseModel):
    label: str = Field("", max_length=60)
    token: str = Field(..., min_length=8, max_length=400)
    api: str = Field("", max_length=300)

class SourcePatch(BaseModel):
    label: str | None = Field(None, max_length=60)
    token: str | None = Field(None, min_length=8, max_length=400)

class ReposIn(BaseModel):
    repos: list[str] = Field(..., min_length=1, max_length=MAX_REPOS)

class RepoNewIn(BaseModel):
    owner: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field("", max_length=300)

class DispatchIn(BaseModel):
    workflow: str = Field(..., max_length=200)
    ref: str = Field(..., max_length=250)
    inputs: dict[str, str | bool | int | float] = {}

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None  # log downloads redirect to storage that must not get our token

_plain = urllib.request.build_opener(_NoRedirect)

def parse_repo(s):
    """'owner/name', or a github.com URL / clone URL -> 'owner/name' (raises ValueError)."""
    s = s.strip()
    m = re.match(r"^(?:https?://[^/]+/|git@[^:]+:)?([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", s)
    if not m or not NAME.match(m[1]) or not NAME.match(m[2]): raise ValueError("Enter a repository as owner/name or its GitHub URL.")
    return f"{m[1]}/{m[2]}"

def api_url(url):
    """A source's API base: empty for the default server; otherwise https (or the default server's own scheme)."""
    url = (url or "").strip().rstrip("/")
    if not url or url == API: return API
    u = urllib.parse.urlparse(url)
    if u.scheme != "https" or not u.hostname or u.query or u.fragment or u.username:
        raise ValueError("Enter the API address as https://host/api/v3 (GitHub Enterprise Server), or leave it empty for github.com.")
    return url

def _person(u):
    return {"login": u.get("login"), "avatar": u.get("avatar_url")} if u else None

def _run(r):
    return {"id": r["id"], "name": r.get("name"), "title": r.get("display_title") or r.get("name"), "number": r.get("run_number"),
            "attempt": r.get("run_attempt", 1), "status": r.get("status"), "conclusion": r.get("conclusion"), "event": r.get("event"),
            "branch": r.get("head_branch"), "sha": r.get("head_sha"), "workflow_id": r.get("workflow_id"), "url": r.get("html_url"),
            "created": r.get("created_at"), "started": r.get("run_started_at"), "updated": r.get("updated_at"),
            "actor": _person(r.get("triggering_actor") or r.get("actor"))}

def dispatch_inputs(text):
    """The workflow_dispatch inputs of a workflow file, or None if it can't be run by hand."""
    try: doc = yaml.safe_load(text) or {}
    except yaml.YAMLError: return None
    on = doc.get("on", doc.get(True)) if isinstance(doc, dict) else None  # YAML 1.1 reads a bare `on:` key as True
    if on == "workflow_dispatch" or (isinstance(on, list) and "workflow_dispatch" in on): return []
    if not isinstance(on, dict) or "workflow_dispatch" not in on: return None
    raw = ((on.get("workflow_dispatch") or {}).get("inputs") or {})
    out = []
    for name, spec in raw.items() if isinstance(raw, dict) else []:
        spec = spec if isinstance(spec, dict) else {}
        out.append({"name": str(name), "description": str(spec.get("description") or ""), "required": bool(spec.get("required")),
                    "type": spec.get("type") or "string", "default": spec.get("default"),
                    "options": [str(o) for o in spec.get("options") or []]})
    return out

class Source:
    def __init__(self, db, data_dir):
        self.db, self.box = db, SecretBox(db, data_dir)
        self.cache, self.lock = {}, threading.Lock()
        self.accounts = {}  # source id -> the GitHub account its token belongs to

    # ---------- configuration ----------
    def sources(self):
        """[{id, label, api, repos, created}]. Until one is saved, the earlier single connection is source "main"."""
        saved = self.db.setting("source_sources")
        if saved is not None: return json.loads(saved)
        if not (self.box.get("github_token") or os.getenv("SOURCE_GITHUB_TOKEN")): return []
        legacy = self.db.setting("source_repos")
        repos = json.loads(legacy) if legacy is not None else [parse_repo(x) for x in os.getenv("SOURCE_REPOS", "").split(",") if x.strip()]
        return [{"id": "main", "label": "GitHub", "api": API, "repos": repos, "created": 0}]

    def save_sources(self, xs):
        self.db.setting("source_sources", v=json.dumps(xs))

    def source(self, sid):
        x = next((x for x in self.sources() if x["id"] == sid), None)
        if not x: raise HTTPException(404, "That source doesn't exist.")
        return x

    def token(self, sid):
        t = self.box.get(f"source_token:{sid}")
        if not t and sid == "main": t = self.box.get("github_token") or os.getenv("SOURCE_GITHUB_TOKEN")
        return t or None

    def token_source(self, sid):
        if self.box.get(f"source_token:{sid}") or (sid == "main" and self.box.get("github_token")): return "app"
        return "env" if sid == "main" and os.getenv("SOURCE_GITHUB_TOKEN") else None

    def repos(self):
        return [r for x in self.sources() for r in x["repos"]]

    def source_of(self, repo):
        repo = repo.lower()
        return next((x for x in self.sources() if any(r.lower() == repo for r in x["repos"])), None)

    def configured(self):
        return any(self.token(x["id"]) for x in self.sources())

    def allowed(self, owner, name):
        """The repository as listed in the hub, or 404: the token can't be used to read anything else."""
        full = f"{owner}/{name}".lower()
        r = next((x for x in self.repos() if x.lower() == full), None)
        if not r: raise HTTPException(404, "That repository isn't in the Source hub.")
        return r

    # ---------- GitHub REST API ----------
    def _conn(self, path):
        """The source a /repos/owner/name/... path goes through."""
        m = re.match(r"^/repos/([^/]+/[^/]+)", path)
        return self.source_of(m[1]) if m else None

    def call(self, method, path, body=None, token=None, params=None, raw=False, conn=None, api=None):
        conn = conn or (None if token else self._conn(path))
        token = token or (conn and self.token(conn["id"]))
        if not token: raise GitHubError("GitHub isn't connected for that repository.", 503)
        url = (api or (conn or {}).get("api") or API) + path + ("?" + urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")}) if params else "")
        h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
             "User-Agent": "subnet-scout"}
        if body is not None: h["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, headers=h, method=method)
        try:
            with _plain.open(req, timeout=20) as r:
                data = r.read()
                if raw: return data
                return {"_scopes": r.headers.get("X-OAuth-Scopes"), **({"data": json.loads(data)} if data else {})}
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 307) and raw and e.headers.get("Location"):
                return self._download(e.headers["Location"])
            raise self._error(e)
        except (urllib.error.URLError, TimeoutError) as e:
            raise GitHubError(f"Can't reach GitHub ({getattr(e, 'reason', e)}).")

    def _download(self, url):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return r.read()
        except (urllib.error.URLError, TimeoutError) as e:
            raise GitHubError(f"Couldn't download the log ({getattr(e, 'reason', e)}).")

    @staticmethod
    def _error(e):
        try: msg = json.load(e).get("message") or ""
        except ValueError: msg = ""
        if e.code == 401: return GitHubError("GitHub rejected the token. It may have expired or been revoked: connect a new one.")
        if e.code in (403, 429) and (e.headers.get("X-RateLimit-Remaining") == "0" or "rate limit" in msg.lower()):
            reset = int(e.headers.get("X-RateLimit-Reset") or time.time() + 60)
            return GitHubError(f"GitHub's rate limit is used up; it resets in {max(1, round((reset - time.time()) / 60))} min.", 429)
        if e.code == 403: return GitHubError("The token isn't allowed to do that. Give it Actions read/write (fine-grained) or the repo and workflow scopes (classic).", 403)
        if e.code == 404: return GitHubError("GitHub can't find that, or the token can't see it.", 404)
        if e.code == 422: return GitHubError(f"GitHub refused: {msg}" if msg else "GitHub refused the request.", 400)
        if e.code == 409: return GitHubError(msg or "That conflicts with the run's current state.", 409)
        return GitHubError(f"GitHub answered HTTP {e.code}{': ' + msg if msg else ''}.")

    def get(self, path, ttl=30, conn=None, **params):
        """Cached GET shared by every viewer (per source)."""
        conn = conn or self._conn(path)
        key = ((conn or {}).get("id"), path, tuple(sorted(params.items())))
        with self.lock: hit = self.cache.get(key)
        if hit and time.time() - hit[0] < ttl: return hit[1]
        data = self.call("GET", path, params=params, conn=conn).get("data")
        with self.lock:
            if len(self.cache) > 2000: self.cache.clear()
            self.cache[key] = (time.time(), data)
        return data

    def forget(self, repo=None):
        with self.lock:
            if repo is None: self.cache.clear()
            else:
                for k in [k for k in self.cache if k[1].lower().startswith(f"/repos/{repo.lower()}/") or k[1].lower() == f"/repos/{repo.lower()}"]:
                    del self.cache[k]

    def connect(self, token, api=API):
        r = self.call("GET", "/user", token=token, api=api)
        u = r["data"]
        scopes = [s.strip() for s in (r.get("_scopes") or "").split(",") if s.strip()]
        return {"login": u.get("login"), "name": u.get("name"), "avatar": u.get("avatar_url"), "url": u.get("html_url"),
                "scopes": scopes, "classic": r.get("_scopes") is not None,
                "missing": [s for s in ("repo", "workflow") if r.get("_scopes") is not None and s not in scopes]}

    def whoami(self, sid):
        if sid not in self.accounts:
            x, t = self.source(sid), self.token(sid)
            if not t: return {"error": "No token: add one, or delete this source."}
            try: self.accounts[sid] = self.connect(t, x["api"])
            except GitHubError as e: return {"error": str(e)}
        return self.accounts[sid]

    # ---------- reads ----------
    def summary(self, repo):
        try:
            info = self.get(f"/repos/{repo}", ttl=120)
            runs = self.get(f"/repos/{repo}/actions/runs", ttl=20, per_page=1).get("workflow_runs") or []
            pulls = self.get(f"/repos/{repo}/pulls", ttl=60, state="open", per_page=50)
        except GitHubError as e:
            return {"repo": repo, "source": self._label(repo), "error": str(e)}
        return {"repo": repo, "source": self._label(repo), "description": info.get("description"), "private": info.get("private"), "url": info.get("html_url"),
                "default_branch": info.get("default_branch"), "language": info.get("language"), "stars": info.get("stargazers_count"),
                "forks": info.get("forks_count"), "pushed": info.get("pushed_at"), "archived": info.get("archived"),
                "open_prs": len(pulls), "open_prs_more": len(pulls) >= 50, "last_run": _run(runs[0]) if runs else None}

    def _label(self, repo):
        x = self.source_of(repo)
        return {"id": x["id"], "label": x["label"]} if x else None

    def overview(self):
        repos = self.repos()
        if not repos: return []
        with ThreadPoolExecutor(max_workers=min(8, len(repos))) as pool:
            return list(pool.map(self.summary, repos))

    def branches(self, repo):
        info = self.get(f"/repos/{repo}", ttl=120)
        items = self.get(f"/repos/{repo}/branches", ttl=60, per_page=100)
        default = info.get("default_branch")
        out = [{"name": b["name"], "sha": b["commit"]["sha"], "protected": b.get("protected", False), "default": b["name"] == default} for b in items]
        return sorted(out, key=lambda b: (not b["default"], b["name"].lower()))

    def commits(self, repo, ref=None):
        items = self.get(f"/repos/{repo}/commits", ttl=30, sha=ref, per_page=30)
        runs = self.get(f"/repos/{repo}/actions/runs", ttl=20, per_page=100).get("workflow_runs") or []
        ci = {}
        for r in runs:  # newest first: keep each workflow's latest run per commit
            ci.setdefault(r["head_sha"], {}).setdefault(r.get("workflow_id"), r)
        def status(sha):
            rs = list((ci.get(sha) or {}).values())
            if not rs: return None
            if any(r["status"] != "completed" for r in rs): return "running"
            if any(r["conclusion"] in ("failure", "timed_out", "startup_failure") for r in rs): return "failure"
            if any(r["conclusion"] == "cancelled" for r in rs): return "cancelled"
            return "success"
        return [{"sha": c["sha"], "message": c["commit"]["message"], "author": (c.get("author") or {}).get("login") or c["commit"]["author"]["name"],
                 "avatar": (c.get("author") or {}).get("avatar_url"), "date": c["commit"]["author"]["date"], "url": c.get("html_url"),
                 "ci": status(c["sha"]), "runs": len(ci.get(c["sha"]) or {})} for c in items]

    def pulls(self, repo):
        items = self.get(f"/repos/{repo}/pulls", ttl=60, state="open", per_page=50)
        return [{"number": p["number"], "title": p["title"], "author": _person(p.get("user")), "draft": p.get("draft", False),
                 "head": p["head"]["ref"], "base": p["base"]["ref"], "sha": p["head"]["sha"], "created": p.get("created_at"),
                 "updated": p.get("updated_at"), "url": p.get("html_url"), "labels": [l["name"] for l in p.get("labels") or []]} for p in items]

    def workflows(self, repo):
        items = self.get(f"/repos/{repo}/actions/workflows", ttl=120, per_page=100).get("workflows") or []
        return [{"id": w["id"], "name": w["name"], "path": w["path"], "state": w["state"], "url": w.get("html_url")} for w in items]

    def runs(self, repo, workflow=None, branch=None, status=None):
        path = f"/repos/{repo}/actions/workflows/{workflow}/runs" if workflow else f"/repos/{repo}/actions/runs"
        data = self.get(path, ttl=10, per_page=30, branch=branch, status=status)
        return [_run(r) for r in data.get("workflow_runs") or []]

    def run(self, repo, run_id):
        r = self.get(f"/repos/{repo}/actions/runs/{run_id}", ttl=5)
        jobs = self.get(f"/repos/{repo}/actions/runs/{run_id}/jobs", ttl=5, filter="latest", per_page=100).get("jobs") or []
        return {**_run(r), "jobs": [{"id": j["id"], "name": j["name"], "status": j["status"], "conclusion": j.get("conclusion"),
                                      "started": j.get("started_at"), "completed": j.get("completed_at"), "url": j.get("html_url"),
                                      "steps": [{"number": s["number"], "name": s["name"], "status": s["status"], "conclusion": s.get("conclusion"),
                                                 "started": s.get("started_at"), "completed": s.get("completed_at")} for s in j.get("steps") or []]}
                                     for j in jobs]}

    def job_log(self, repo, job_id):
        text = self.call("GET", f"/repos/{repo}/actions/jobs/{job_id}/logs", raw=True).decode("utf-8", "replace")
        text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)  # ANSI colours
        text = re.sub(r"^﻿?\d{4}-\d\d-\d\dT[\d:.]+Z ", "", text, flags=re.M)  # per-line timestamps
        return {"text": text[-LOG_TAIL:], "truncated": len(text) > LOG_TAIL}

    def contents(self, repo, path="", ref=None):
        """A folder (its entries, folders first, and its README) or a file (text, or why it isn't shown) at a branch."""
        data = self.get(f"/repos/{repo}/contents/{urllib.parse.quote(path)}", ttl=60, ref=ref)
        if isinstance(data, list):
            entries = sorted(({"name": e["name"], "path": e["path"], "type": e["type"], "size": e.get("size") or 0,
                               "secret": e["type"] == "file" and bool(SECRET.search(e["path"]))} for e in data),
                             key=lambda e: (e["type"] != "dir", e["name"].lower()))
            readme = next((e for e in entries if e["type"] == "file" and README.match(e["name"])), None)
            return {"type": "dir", "path": path, "entries": entries, "readme": self.contents(repo, readme["path"], ref) if readme else None}
        out = {"type": data.get("type"), "path": data.get("path") or path, "name": data.get("name"), "size": data.get("size") or 0,
               "url": data.get("html_url"), "sha": data.get("sha")}
        if out["type"] != "file": return out  # submodule or symlink: GitHub has the details
        if SECRET.search(out["path"]): return {**out, "hidden": "secret"}
        if data.get("encoding") != "base64" or not data.get("content"): return {**out, "hidden": "large"}  # over GitHub's 1 MB
        raw = base64.b64decode(data["content"])
        if b"\0" in raw[:8000]: return {**out, "hidden": "binary"}
        text = raw.decode("utf-8", "replace")
        return {**out, "text": text[:FILE_MAX], "truncated": len(text) > FILE_MAX}

    def deployments(self, repo):
        items = self.get(f"/repos/{repo}/deployments", ttl=30, per_page=15)
        def shape(d):
            st = self.get(f"/repos/{repo}/deployments/{d['id']}/statuses", ttl=30, per_page=1)
            s = st[0] if st else {}
            return {"id": d["id"], "environment": d.get("environment"), "ref": d.get("ref"), "sha": d.get("sha"), "created": d.get("created_at"),
                    "creator": _person(d.get("creator")), "state": s.get("state") or "pending", "url": s.get("environment_url") or s.get("log_url") or s.get("target_url")}
        with ThreadPoolExecutor(max_workers=6) as pool:
            return list(pool.map(shape, items))

    def dispatch_form(self, repo, workflow_id, ref=None):
        wf = next((w for w in self.workflows(repo) if str(w["id"]) == str(workflow_id)), None)
        if not wf: raise GitHubError("That workflow doesn't exist.", 404)
        try:
            f = self.get(f"/repos/{repo}/contents/{urllib.parse.quote(wf['path'])}", ttl=60, ref=ref)
            inputs = dispatch_inputs(base64.b64decode(f.get("content") or "").decode("utf-8", "replace"))
        except GitHubError:
            inputs = []  # can't read the file: let GitHub decide
        return {"workflow": wf, "dispatchable": inputs is not None, "inputs": inputs or []}

    # ---------- actions ----------
    def dispatch(self, repo, d: DispatchIn):
        if not REF.match(d.ref): raise GitHubError("That isn't a valid branch or tag name.", 400)
        wf = d.workflow if re.fullmatch(r"\d+|[\w.-]+\.ya?ml", d.workflow) else None
        if not wf: raise GitHubError("Unknown workflow.", 400)
        inputs = {k: ("true" if v is True else "false" if v is False else str(v)) for k, v in d.inputs.items() if NAME.match(k)}
        self.call("POST", f"/repos/{repo}/actions/workflows/{wf}/dispatches", {"ref": d.ref, "inputs": inputs})
        self.forget(repo)

    def run_action(self, repo, run_id, action):
        path = {"rerun": "rerun", "rerun-failed": "rerun-failed-jobs", "cancel": "cancel"}[action]
        self.call("POST", f"/repos/{repo}/actions/runs/{run_id}/{path}", {} if action != "cancel" else None)
        self.forget(repo)

    def set_workflow(self, repo, workflow_id, enabled):
        self.call("PUT", f"/repos/{repo}/actions/workflows/{workflow_id}/{'enable' if enabled else 'disable'}")
        self.forget(repo)

def build(db, require, admin_state, ip, data_dir):
    r = APIRouter(prefix="/api/source")
    src = Source(db, data_dir)
    admin, sudo = admin_state["admin"], admin_state["sudo"]
    r.state = {"source": src}

    def gh(fn, *a, **k):
        try: return fn(*a, **k)
        except GitHubError as e: raise HTTPException(e.status, str(e))

    def repo_of(req, owner, name, write=False):
        me = (admin if write else require)(req)
        if not src.configured(): raise HTTPException(503, "GitHub isn't connected.")
        return me, src.allowed(owner, name)

    @r.get("")
    def view(req: Request):
        me = require(req)
        base = {"configured": src.configured(), "is_admin": me["role"] == "admin"}
        if not src.configured(): return base
        accts = [{"id": x["id"], "label": x["label"], **{k: (src.whoami(x["id"]) or {}).get(k) for k in ("login", "avatar", "url", "error")}} for x in src.sources()]
        return {**base, "sources": accts, "error": "; ".join(f"{a['label']}: {a['error']}" for a in accts if a["error"]) or None,
                "repos": src.overview(), "updated": time.time()}

    @r.get("/repos/{owner}/{name}/branches")
    def branches(owner: str, name: str, req: Request):
        _, repo = repo_of(req, owner, name)
        return gh(src.branches, repo)

    @r.get("/repos/{owner}/{name}/commits")
    def commits(owner: str, name: str, req: Request, ref: str | None = None):
        _, repo = repo_of(req, owner, name)
        if ref and not REF.match(ref): raise HTTPException(400, "Bad branch name.")
        return gh(src.commits, repo, ref)

    @r.get("/repos/{owner}/{name}/pulls")
    def pulls(owner: str, name: str, req: Request):
        _, repo = repo_of(req, owner, name)
        return gh(src.pulls, repo)

    @r.get("/repos/{owner}/{name}/workflows")
    def workflows(owner: str, name: str, req: Request):
        _, repo = repo_of(req, owner, name)
        return gh(src.workflows, repo)

    @r.get("/repos/{owner}/{name}/runs")
    def runs(owner: str, name: str, req: Request, workflow: int | None = None, branch: str | None = None, status: str | None = None):
        _, repo = repo_of(req, owner, name)
        if branch and not REF.match(branch): raise HTTPException(400, "Bad branch name.")
        if status and status not in ("queued", "in_progress", "completed", "success", "failure", "cancelled", "waiting"): raise HTTPException(400, "Bad status.")
        return gh(src.runs, repo, workflow, branch, status)

    @r.get("/repos/{owner}/{name}/runs/{run_id}")
    def run(owner: str, name: str, run_id: int, req: Request):
        _, repo = repo_of(req, owner, name)
        return gh(src.run, repo, run_id)

    @r.get("/repos/{owner}/{name}/jobs/{job_id}/log")
    def job_log(owner: str, name: str, job_id: int, req: Request):
        _, repo = repo_of(req, owner, name)
        return gh(src.job_log, repo, job_id)

    @r.get("/repos/{owner}/{name}/contents")
    def contents(owner: str, name: str, req: Request, path: str = "", ref: str | None = None):
        _, repo = repo_of(req, owner, name)
        path = path.strip("/")
        if len(path) > 500 or any(p in ("..", ".") for p in path.split("/")) or re.search(r"[\x00-\x1f\\]", path):
            raise HTTPException(400, "Bad path.")
        if ref and not REF.match(ref): raise HTTPException(400, "Bad branch name.")
        return gh(src.contents, repo, path, ref)

    @r.get("/repos/{owner}/{name}/deployments")
    def deployments(owner: str, name: str, req: Request):
        _, repo = repo_of(req, owner, name)
        return gh(src.deployments, repo)

    # ---------- CI/CD actions (admins) ----------
    @r.get("/repos/{owner}/{name}/workflows/{workflow_id}/form")
    def form(owner: str, name: str, workflow_id: int, req: Request, ref: str | None = None):
        _, repo = repo_of(req, owner, name, write=True)
        if ref and not REF.match(ref): raise HTTPException(400, "Bad branch name.")
        return gh(src.dispatch_form, repo, workflow_id, ref)

    @r.post("/repos/{owner}/{name}/dispatch")
    def dispatch(owner: str, name: str, d: DispatchIn, req: Request):
        me, repo = repo_of(req, owner, name, write=True)
        gh(src.dispatch, repo, d)
        db.log("source.dispatch", me["username"], repo, ip(req), f"workflow {d.workflow} on {d.ref} {json.dumps(d.inputs)}"[:300])
        return {"ok": True}

    @r.post("/repos/{owner}/{name}/runs/{run_id}/{action}")
    def run_action(owner: str, name: str, run_id: int, action: str, req: Request):
        if action not in ("rerun", "rerun-failed", "cancel"): raise HTTPException(404, "Unknown action.")
        me, repo = repo_of(req, owner, name, write=True)
        gh(src.run_action, repo, run_id, action)
        db.log(f"source.{action}", me["username"], repo, ip(req), f"run {run_id}")
        return {"ok": True}

    @r.put("/repos/{owner}/{name}/workflows/{workflow_id}/{state}")
    def workflow_state(owner: str, name: str, workflow_id: int, state: str, req: Request):
        if state not in ("enable", "disable"): raise HTTPException(404, "Unknown action.")
        me, repo = repo_of(req, owner, name, write=True)
        gh(src.set_workflow, repo, workflow_id, state == "enable")
        db.log(f"source.workflow_{state}", me["username"], repo, ip(req), f"workflow {workflow_id}")
        return {"ok": True}

    # ---------- configuration (admins): sources and their repositories ----------
    def shape(x):
        t = src.token(x["id"])
        return {"id": x["id"], "label": x["label"], "api": x["api"], "default_api": x["api"] == API, "token": mask(t),
                "token_source": src.token_source(x["id"]), "account": src.whoami(x["id"]) if t else {"error": "No token."}, "repos": x["repos"]}

    @r.get("/config")
    def config(req: Request):
        admin(req)
        return {"configured": src.configured(), "sources": [shape(x) for x in src.sources()], "max_repos": MAX_REPOS,
                "max_sources": MAX_SOURCES, "api": API}

    def checked(token, api):
        token = token.strip()
        if not TOKEN.fullmatch(token): raise HTTPException(400, "That doesn't look like a GitHub token (they start with github_pat_ or ghp_).")
        try: return token, src.connect(token, api)
        except GitHubError as e: raise HTTPException(400, f"{e} Nothing was saved.")

    @r.post("/config/sources")
    def add_source(b: SourceIn, req: Request):
        """A new source: its token is checked against its GitHub server before anything is saved."""
        me = sudo(req)
        xs = src.sources()
        if len(xs) >= MAX_SOURCES: raise HTTPException(400, f"The hub holds up to {MAX_SOURCES} sources. Delete one first.")
        try: api = api_url(b.api)
        except ValueError as e: raise HTTPException(400, str(e))
        token, acct = checked(b.token, api)
        dup = next((x for x in xs if x["api"] == api and (src.whoami(x["id"]) or {}).get("login") == acct["login"]), None)
        if dup: raise HTTPException(400, f"@{acct['login']} is already connected as “{dup['label']}”. Replace its token there instead.")
        sid = secrets.token_hex(4)
        label = " ".join(b.label.split()) or (acct["login"] if api == API else f"{acct['login']} @ {urllib.parse.urlparse(api).hostname}")
        src.box.set(f"source_token:{sid}", token)
        src.save_sources(xs + [{"id": sid, "label": label[:60], "api": api, "repos": [], "created": time.time()}])
        src.accounts[sid] = acct
        db.log("source.connect", me["username"], label[:60], ip(req), f"{acct['login']} {api} {fingerprint(token)}")  # D-019
        return {**config(req), "added": sid}

    @r.patch("/config/sources/{sid}")
    def edit_source(sid: str, b: SourcePatch, req: Request):
        me = sudo(req)
        xs, x = src.sources(), src.source(sid)
        if b.token:
            token, acct = checked(b.token, x["api"])
            src.box.set(f"source_token:{sid}", token)
            src.accounts[sid] = acct; src.forget()
            db.log("source.token", me["username"], x["label"], ip(req), f"{acct['login']} {fingerprint(token)}")  # D-019
        if b.label is not None and " ".join(b.label.split()):
            x["label"] = " ".join(b.label.split())[:60]
        src.save_sources([x if y["id"] == sid else y for y in xs])
        return config(req)

    @r.delete("/config/sources/{sid}")
    def delete_source(sid: str, req: Request):
        """Deletes the source, its token and its repositories from the hub (nothing changes on GitHub)."""
        me = sudo(req)
        x = src.source(sid)
        src.save_sources([y for y in src.sources() if y["id"] != sid])
        src.box.delete(f"source_token:{sid}")
        if sid == "main": src.box.delete("github_token")
        src.accounts.pop(sid, None); src.forget()
        db.log("source.disconnect", me["username"], x["label"], ip(req), f"{len(x['repos'])} repositories removed")
        return config(req)

    @r.get("/config/sources/{sid}/available")
    def available(sid: str, req: Request):
        """Repositories the source's token can see, most recently pushed first, to pick from."""
        admin(req)
        x = src.source(sid)
        items = gh(src.get, "/user/repos", 60, conn=x, per_page=100, sort="pushed", affiliation="owner,collaborator,organization_member")
        listed = {r.lower() for r in src.repos()}
        return [{"repo": i["full_name"], "private": i.get("private"), "description": i.get("description"), "pushed": i.get("pushed_at"),
                 "listed": i["full_name"].lower() in listed} for i in items]

    @r.post("/config/sources/{sid}/repos")
    def add_repos(sid: str, b: ReposIn, req: Request):
        """Adds several repositories to a source at once; each is checked with its token. Returns what failed and why."""
        me = admin(req)
        x = src.source(sid)
        have = {r.lower() for r in src.repos()}
        added, errors = [], []
        for raw in dict.fromkeys(b.repos):
            try: repo = parse_repo(raw)
            except ValueError as e: errors.append({"repo": raw[:100], "error": str(e)}); continue
            if repo.lower() in have:
                other = src.source_of(repo)
                errors.append({"repo": repo, "error": "Already in the hub" + (f" (via {other['label']})." if other else ".")}); continue
            if len(have) >= MAX_REPOS: errors.append({"repo": repo, "error": f"The hub holds up to {MAX_REPOS} repositories."}); continue
            try: info = src.get(f"/repos/{repo}", 0, conn=x)
            except GitHubError as e: errors.append({"repo": repo, "error": str(e)}); continue
            added.append(info["full_name"]); have.add(info["full_name"].lower())
            db.log("source.repo_add", me["username"], info["full_name"], ip(req), f"{x['label']} {'private' if info.get('private') else 'public'}")
        if added:
            src.save_sources([{**y, "repos": y["repos"] + added} if y["id"] == sid else y for y in src.sources()])
        return {**config(req), "added": added, "errors": errors}

    @r.post("/config/repos/remove")
    def remove_repos(b: ReposIn, req: Request):
        """Removes several repositories from the hub, whichever source they belong to."""
        me = admin(req)
        drop = {x.strip().lower() for x in b.repos}
        gone = [r for r in src.repos() if r.lower() in drop]
        if not gone: raise HTTPException(404, "None of those repositories are in the Source hub.")
        src.save_sources([{**y, "repos": [r for r in y["repos"] if r.lower() not in drop]} for y in src.sources()])
        for repo in gone:
            src.forget(repo)
            db.log("source.repo_remove", me["username"], repo, ip(req), "")
        return {**config(req), "removed": gone}

    # ---------- a new repository, made on GitHub and added to the hub (My subnets' results, the file manager) ----------
    @r.get("/config/owners")
    def owners(req: Request):
        """Where each source's token can make a repository: its own account, then its organizations."""
        admin(req)
        out = []
        for x in src.sources():
            acct = src.whoami(x["id"]) or {}
            if not acct.get("login"): out.append({"id": x["id"], "label": x["label"], "owners": [], "error": acct.get("error")}); continue
            try: orgs = [o["login"] for o in src.call("GET", "/user/orgs", conn=x, params={"per_page": 100}).get("data") or []]
            except GitHubError: orgs = []  # a fine-grained token may not read them: the account still works
            out.append({"id": x["id"], "label": x["label"], "owners": [{"login": acct["login"], "kind": "user"}] + [{"login": o, "kind": "org"} for o in orgs]})
        return {"sources": out, "full": len(src.repos()) >= MAX_REPOS, "max_repos": MAX_REPOS}

    @r.post("/config/sources/{sid}/create")
    def create_repo(sid: str, b: RepoNewIn, req: Request):
        """A new private repository with a README (so it has a default branch to branch from), added to the hub."""
        me = sudo(req)
        x = src.source(sid)
        if len(src.repos()) >= MAX_REPOS: raise HTTPException(400, f"The hub holds up to {MAX_REPOS} repositories. Remove one first.")
        owner, name = b.owner.strip(), b.name.strip()
        if not NAME.match(owner) or not NAME.match(name) or name in (".", "..") or name.lower().endswith(".git"):
            raise HTTPException(400, "Use letters, digits, - _ and . for the name.")
        acct = src.whoami(sid) or {}
        if not acct.get("login"): raise HTTPException(400, acct.get("error") or "That source's token doesn't work.")
        mine = owner.lower() == acct["login"].lower()
        body = {"name": name, "private": True, "auto_init": True, "description": " ".join(b.description.split())[:300]}
        try: info = src.call("POST", "/user/repos" if mine else f"/orgs/{urllib.parse.quote(owner)}/repos", body, conn=x)["data"]
        except GitHubError as e:
            if e.status in (403, 404):
                raise HTTPException(e.status, f"The token can't make repositories {'on its account' if mine else f'in {owner}'}: give it Administration "
                                              "read and write (fine-grained, for that owner) or the repo scope (classic)." + ("" if mine else " Organization owners may also limit who makes repositories."))
            raise HTTPException(e.status, f"{e} Is {owner}/{name} taken already?" if e.status == 400 else str(e))
        full = info["full_name"]
        src.save_sources([{**y, "repos": y["repos"] + [full]} if y["id"] == sid else y for y in src.sources()])
        src.forget()
        db.log("source.repo_create", me["username"], full, ip(req), f"{x['label']} private")
        return {"repo": full, "url": info.get("html_url"), "default_branch": info.get("default_branch") or "main", "repos": src.repos()}

    return r
