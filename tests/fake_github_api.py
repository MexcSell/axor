"""Minimal GitHub REST API for testing the Source hub offline.
Token "ghp_testtoken1234567890abcdefghij" is valid (classic, scopes repo + workflow) and so is a second one,
"ghp_secondtoken234567890abcdefghij" (another account, for testing several sources). Repository scout/miner has two
branches, commits, an open PR, two workflows (CI on push; Deploy with workflow_dispatch inputs), runs with jobs,
steps and logs (served through a redirect, like GitHub's storage links, which must arrive without the token) and a
deployment. Dispatch adds a queued run, cancel/rerun change a run's state, enable/disable change a workflow's.
Writes (Mining HQ's Scribe): POST git/refs makes a branch, PUT contents commits a file (422 without the sha of a file that's
there, 409 with a stale one; scout/validator answers 403, like a read-only token); written files read back at their branch,
and GET /_writes lists every commit made.
The file manager's GitHub pane: git trees (recursive) and blobs read the files (static ones and written ones), and blobs + trees +
commits + PATCH refs make one commit of several files (a ref update that isn't a fast forward answers 422). Creating
repositories: GET /user/orgs (scout), POST /user/repos and /orgs/<org>/repos; a created repository answers like the others.
Issues and comments (the Workflow's GitHub intake, mining_github.py): GET issues / issues/comments (with since) / issues/<n>, POST
issues/<n>/comments (scout/validator answers 403). Test hooks without a token: POST /_issue {repo, title, body, login, type} opens an
issue, POST /_comment {repo, number, body, login, type} comments, GET /_comments lists every comment, including the app's replies.
Run: python tests/fake_github_api.py 8797  then start the app with SOURCE_GITHUB_API_URL=http://127.0.0.1:8797"""
import base64, hashlib, json, re, sys, time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

TOKEN = "ghp_testtoken1234567890abcdefghij"
TOKEN2 = "ghp_secondtoken234567890abcdefghij"
iso = lambda ago: datetime.fromtimestamp(time.time() - ago, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
ME = {"login": "scout-bot", "name": "Scout Bot", "avatar_url": "https://example.com/bot.png", "html_url": "https://github.com/scout-bot"}
REPO = {"full_name": "scout/miner", "description": "SN62 miner", "private": True, "default_branch": "main", "html_url": "https://github.com/scout/miner",
        "stargazers_count": 12, "forks_count": 3, "language": "Python", "pushed_at": iso(600), "archived": False}
BRANCHES = [{"name": "main", "commit": {"sha": "a" * 40}, "protected": True}, {"name": "feature/gpu", "commit": {"sha": "b" * 40}, "protected": False}]
COMMITS = [{"sha": "a" * 40, "commit": {"message": "Tune batch size\n\nDetails", "author": {"name": "Alice", "date": iso(600)}},
            "author": {"login": "alice", "avatar_url": "https://example.com/a.png"}, "html_url": "https://github.com/scout/miner/commit/aaa"},
           {"sha": "c" * 40, "commit": {"message": "Initial commit", "author": {"name": "Bob", "date": iso(86400 * 3)}}, "author": None, "html_url": None}]
PULLS = [{"number": 7, "title": "GPU kernels", "user": {"login": "bob", "avatar_url": None}, "draft": False, "head": {"ref": "feature/gpu", "sha": "b" * 40},
          "base": {"ref": "main"}, "created_at": iso(7200), "updated_at": iso(900), "html_url": "https://github.com/scout/miner/pull/7", "labels": [{"name": "perf"}]}]
WORKFLOWS = [{"id": 101, "name": "CI", "path": ".github/workflows/ci.yml", "state": "active", "html_url": "https://github.com/scout/miner/actions/workflows/ci.yml"},
             {"id": 102, "name": "Deploy", "path": ".github/workflows/deploy.yml", "state": "active", "html_url": "https://github.com/scout/miner/actions/workflows/deploy.yml"}]
FILES = {".github/workflows/ci.yml": "name: CI\non: [push, pull_request]\njobs: {}\n",
         ".github/workflows/deploy.yml": "name: Deploy\non:\n  workflow_dispatch:\n    inputs:\n      environment:\n        type: choice\n        options: [staging, production]\n"
                                         "        default: staging\n        required: true\n      dry_run:\n        type: boolean\n        default: true\n        description: Only print the plan\n"
                                         "      note:\n        description: Free text\njobs: {}\n"}
CODE = {"README.md": "# Miner\n\nRuns the **SN62** agent.\n\n- `agent.py`: the agent\n", "agent.py": "import os\n\ndef main():\n    print('hi')\n",
        ".env.apikey": "OPENROUTER_API_KEY=sk-or-v1-secret\n", "eval/eval.py": "# 3 runs per task\n"}
def run(i, wf, status, conclusion, sha, branch, ago):
    return {"id": i, "name": wf["name"], "display_title": f"Run {i}", "run_number": i - 1000, "run_attempt": 1, "status": status, "conclusion": conclusion,
            "event": "push", "head_branch": branch, "head_sha": sha, "workflow_id": wf["id"], "html_url": f"https://github.com/scout/miner/actions/runs/{i}",
            "created_at": iso(ago), "run_started_at": iso(ago), "updated_at": iso(ago - 90), "actor": {"login": "alice", "avatar_url": None}}
RUNS = [run(1003, WORKFLOWS[0], "in_progress", None, "b" * 40, "feature/gpu", 60), run(1002, WORKFLOWS[0], "completed", "failure", "a" * 40, "main", 700),
        run(1001, WORKFLOWS[1], "completed", "success", "c" * 40, "main", 90000)]
JOBS = {1002: [{"id": 5002, "name": "test", "status": "completed", "conclusion": "failure", "started_at": iso(690), "completed_at": iso(610),
                "html_url": "https://github.com/scout/miner/actions/runs/1002/job/5002",
                "steps": [{"number": 1, "name": "Checkout", "status": "completed", "conclusion": "success", "started_at": iso(690), "completed_at": iso(685)},
                          {"number": 2, "name": "pytest", "status": "completed", "conclusion": "failure", "started_at": iso(685), "completed_at": iso(610)}]}]}
LOGS = {5002: "﻿2026-10-22T10:00:00.0000000Z ##[group]Run pytest\n2026-10-22T10:00:01.0000000Z \x1b[31mFAILED\x1b[0m test_kernels.py::test_batch\n"
              "2026-10-22T10:00:01.5000000Z ##[endgroup]\n2026-10-22T10:00:02.0000000Z ##[error]Process completed with exit code 1.\n"}
DEPLOYS = [{"id": 9, "environment": "production", "ref": "main", "sha": "c" * 40, "created_at": iso(86000), "creator": {"login": "alice", "avatar_url": None}}]
STATUSES = {9: [{"state": "success", "environment_url": "https://miner.example.com"}]}
DISPATCHES = []

# DevOps: scout/miner as a tiny web app the pipelines can build, test and deploy. Each commit is a snapshot (served as
# GitHub's tarball, through a redirect that must arrive without the token): a = main (healthy), c = an older healthy
# version, b = feature/gpu (crashes on start, to test rollback), d = failing tests. POST /_push {branch, sha} moves a
# branch (auto deploy); a sha that isn't listed is a healthy version too.
HEADS = {"main": "a" * 40, "feature/gpu": "b" * 40}
WRITES, COMMITTED = {}, []  # (repo, branch, path) -> (text, blob sha); every commit in order
BLOBS, TREES, NEWCOMMITS, CREATED = {}, {}, {}, {}  # git data: blob sha -> bytes, tree sha -> entries, commit sha -> (tree, message, parent); repo -> info
def files_at(repo, ref):
    """Every file of a repository at a branch: the static ones and those written there."""
    out = {k: v.encode() for k, v in {**FILES, **CODE}.items()}
    out.update({path: t.encode() for (r, b, path), (t, _) in WRITES.items() if r == repo.lower() and b == ref})
    return out
def blob_sha(raw):
    sha = hashlib.sha1(b"blob %d\0" % len(raw) + raw).hexdigest(); BLOBS[sha] = raw; return sha
MESSAGES = {"a" * 40: "Tune batch size", "b" * 40: "GPU kernels", "c" * 40: "Initial commit", "d" * 40: "Break the tests"}
def snapshot(sha):
    import io, tarfile
    crash, failing = sha.startswith("b"), sha.startswith("d")
    files = {
        "Dockerfile": "FROM python:3.12-slim\nWORKDIR /app\nCOPY . .\nEXPOSE 8000\nCMD [\"python\", \"app.py\"]\n",
        ".dockerignore": "notes\n*.log\n",
        "app.py": "import http.server, os, sys\nVERSION = %r\n" % sha[:7]
                  + ("sys.exit('boom: the GPU driver is missing')\n" if crash else "")
                  + "class H(http.server.BaseHTTPRequestHandler):\n    def do_GET(self):\n"
                    "        body = f\"hello from {VERSION}, key {'set' if os.getenv('MINER_KEY') else 'missing'}, mode {os.getenv('MODE')}\\n\".encode()\n"
                    "        self.send_response(200 if self.path in ('/', '/health') else 404); self.send_header('content-length', str(len(body))); self.end_headers(); self.wfile.write(body)\n"
                    "    def log_message(self, f, *a): print(f % a, flush=True)\n"
                    "print('listening on 8000', flush=True)\nhttp.server.ThreadingHTTPServer(('0.0.0.0', 8000), H).serve_forever()\n",
        "test_app.py": "import os, sys\nprint('the key is', os.getenv('MINER_KEY'))\n" + ("print('FAILED test_batch'); sys.exit(1)\n" if failing else "print('2 passed')\n"),
        "notes/big.txt": "x" * 5000, "debug.log": "noise\n",
    }
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as t:
        top = f"scout-miner-{sha[:7]}"
        d = tarfile.TarInfo(top); d.type = tarfile.DIRTYPE; t.addfile(d)
        for name, text in files.items():
            raw = text.encode(); i = tarfile.TarInfo(f"{top}/{name}"); i.size = len(raw); t.addfile(i, io.BytesIO(raw))
    return out.getvalue()
def commit(ref):
    sha = HEADS.get(ref, ref)
    if not re.fullmatch(r"[0-9a-f]{40}", sha): return None
    return {"sha": sha, "commit": {"message": MESSAGES.get(sha, f"Release {sha[:7]}") + "\n\nDetails", "author": {"name": "Alice", "date": iso(600)}},
            "author": {"login": "alice", "avatar_url": None}, "html_url": f"https://github.com/scout/miner/commit/{sha}"}

ISSUES, COMMENTS = [], []  # the intake's issues and comments


def _issue(repo, number):
    return next((i for i in ISSUES if i["_repo"] == repo.lower() and i["number"] == number), None)


def _shown(x):
    return {k: v for k, v in x.items() if not k.startswith("_")}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def reply(self, code, body=None, headers=None):
        raw = json.dumps(body).encode() if body is not None else b""
        self.send_response(code)
        self.send_header("content-type", "application/json"); self.send_header("X-OAuth-Scopes", "repo, workflow")
        for k, v in (headers or {}).items(): self.send_header(k, v)
        self.send_header("content-length", str(len(raw))); self.end_headers(); self.wfile.write(raw)

    def route(self, method):
        u = urlparse(self.path); p, q = u.path, {k: v[0] for k, v in parse_qs(u.query).items()}
        if p.startswith("/download/log/"):  # storage: must not receive the API token
            if self.headers.get("Authorization"): return self.reply(400, {"message": "unexpected Authorization header"})
            text = LOGS.get(int(p.rsplit("/", 1)[1]), "").encode()
            self.send_response(200); self.send_header("content-type", "text/plain"); self.send_header("content-length", str(len(text))); self.end_headers()
            return self.wfile.write(text)
        if p.startswith("/download/tarball/"):  # storage too
            if self.headers.get("Authorization"): return self.reply(400, {"message": "unexpected Authorization header"})
            raw = snapshot(p.rsplit("/", 1)[1])
            self.send_response(200); self.send_header("content-type", "application/x-gzip"); self.send_header("content-length", str(len(raw))); self.end_headers()
            return self.wfile.write(raw)
        if p == "/_writes" and method == "GET": return self.reply(200, COMMITTED)
        if p == "/_comments" and method == "GET": return self.reply(200, [{**_shown(c), "repo": c["_repo"]} for c in COMMENTS])
        if p in ("/_issue", "/_comment") and method == "POST":
            b = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)))
            user = {"login": b.get("login", "alice"), "type": b.get("type", "User")}
            if p == "/_issue":
                n = 100 + len(ISSUES) + 1
                x = {"_repo": b["repo"].lower(), "number": n, "title": b.get("title", ""), "body": b.get("body", ""), "user": user, "state": "open",
                     "created_at": iso(0), "updated_at": iso(0), "html_url": f"https://github.com/{b['repo']}/issues/{n}"}
                if b.get("pr"): x["pull_request"] = {"url": "x"}
                ISSUES.append(x); return self.reply(201, _shown(x))
            n = int(b["number"])
            if not _issue(b["repo"], n):
                ISSUES.append({"_repo": b["repo"].lower(), "number": n, "title": b.get("title", f"Thread {n}"), "body": "", "user": user, "state": "open",
                               "created_at": iso(3600), "updated_at": iso(0), "html_url": f"https://github.com/{b['repo']}/issues/{n}"})
            c = {"_repo": b["repo"].lower(), "id": 5000 + len(COMMENTS) + 1, "body": b["body"], "user": user, "created_at": iso(0), "updated_at": iso(0),
                 "issue_url": f"https://api.github.com/repos/{b['repo']}/issues/{n}", "html_url": f"https://github.com/{b['repo']}/issues/{n}#issuecomment-{5000 + len(COMMENTS) + 1}"}
            COMMENTS.append(c); return self.reply(201, _shown(c))
        if p == "/_push" and method == "POST":
            b = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)))
            HEADS[b["branch"]] = b["sha"]; return self.reply(200, HEADS)
        auth = self.headers.get("Authorization")
        if auth not in (f"Bearer {TOKEN}", f"Bearer {TOKEN2}"): return self.reply(401, {"message": "Bad credentials"})
        second = auth == f"Bearer {TOKEN2}"
        body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"null")
        if p == "/user": return self.reply(200, {**ME, "login": "scout-ops"} if second else ME)
        if p == "/user/orgs" and method == "GET": return self.reply(200, [] if second else [{"login": "scout", "avatar_url": None}])
        if method == "POST" and (p == "/user/repos" or re.match(r"^/orgs/[^/]+/repos$", p)):
            owner = (("scout-ops" if second else ME["login"]) if p == "/user/repos" else p.split("/")[2])
            if p != "/user/repos" and (second or owner != "scout"): return self.reply(404, {"message": "Not Found"})
            full = f"{owner}/{body['name']}"
            if full.lower() in CREATED or full.lower() in ("scout/miner", "scout/validator"): return self.reply(422, {"message": "Repository creation failed.", "errors": [{"message": "name already exists on this account"}]})
            CREATED[full.lower()] = {**REPO, "full_name": full, "description": body.get("description"), "private": bool(body.get("private")),
                                     "html_url": f"https://github.com/{full}", "auto_init": bool(body.get("auto_init"))}
            return self.reply(201, CREATED[full.lower()])
        if p == "/user/repos": return self.reply(200, [{**REPO, "full_name": "ops/infra"}] if second else [REPO, {**REPO, "full_name": "scout/validator", "private": False}])
        m = re.match(r"^/repos/([^/]+/[^/]+)(/.*)?$", p)
        if not m or m[1].lower() not in (("ops/infra",) if second else ("scout/miner", "scout/validator", *CREATED)): return self.reply(404, {"message": "Not Found"})
        if m[2] in (None, "") and method == "GET": return self.reply(200, CREATED.get(m[1].lower()) or {**REPO, "full_name": m[1]})
        rest = m[2] or ""
        repo = m[1].lower()
        if method == "GET" and rest == "/issues":
            xs = [i for i in ISSUES if i["_repo"] == repo and i["updated_at"] >= q.get("since", "") and q.get("state", "open") in ("all", i["state"])]
            return self.reply(200, [_shown(i) for i in xs][:int(q.get("per_page", 30))])
        if method == "GET" and rest == "/issues/comments":
            xs = [c for c in COMMENTS if c["_repo"] == repo and c["updated_at"] >= q.get("since", "")]
            return self.reply(200, [_shown(c) for c in xs][:int(q.get("per_page", 30))])
        if (x := re.match(r"^/issues/(\d+)$", rest)) and method == "GET":
            i = _issue(repo, int(x[1]))
            return self.reply(200, _shown(i)) if i else self.reply(404, {"message": "Not Found"})
        if (x := re.match(r"^/issues/(\d+)/comments$", rest)) and method == "POST":
            if repo == "scout/validator": return self.reply(403, {"message": "Resource not accessible by personal access token"})
            if not _issue(repo, int(x[1])): return self.reply(404, {"message": "Not Found"})
            c = {"_repo": repo, "id": 5000 + len(COMMENTS) + 1, "body": body["body"], "user": {**({"login": "scout-ops"} if second else {"login": ME["login"]}), "type": "User"},
                 "created_at": iso(0), "updated_at": iso(0), "issue_url": f"https://api.github.com/repos/{m[1]}/issues/{x[1]}",
                 "html_url": f"https://github.com/{m[1]}/issues/{x[1]}#issuecomment-{5000 + len(COMMENTS) + 1}"}
            COMMENTS.append(c); return self.reply(201, _shown(c))
        if method == "GET":
            if rest == "": return self.reply(200, REPO)
            if rest == "/branches": return self.reply(200, [{**b, "commit": {"sha": HEADS.get(b["name"], b["commit"]["sha"])}} for b in BRANCHES])
            if rest.startswith("/branches/"):
                name = rest[len("/branches/"):]
                return self.reply(200, {"name": name, "commit": {"sha": HEADS[name]}}) if name in HEADS else self.reply(404, {"message": "Branch not found"})
            if rest.startswith("/git/ref/heads/"):
                name = rest[len("/git/ref/heads/"):]
                return self.reply(200, {"ref": f"refs/heads/{name}", "object": {"sha": HEADS[name], "type": "commit"}}) if name in HEADS else self.reply(404, {"message": "Not Found"})
            if rest.startswith("/contents/") and (w := WRITES.get((m[1].lower(), q.get("ref", "main"), rest[len("/contents/"):]))):
                return self.reply(200, {"type": "file", "path": rest[len("/contents/"):], "sha": w[1], "encoding": "base64", "content": base64.b64encode(w[0].encode()).decode()})
            if rest.startswith("/commits/"):
                c = commit(rest[len("/commits/"):])
                return self.reply(200, c) if c else self.reply(422, {"message": f"No commit found for SHA: {rest[len('/commits/'):]}"})
            if (x := re.match(r"^/tarball/([0-9a-f]{40})$", rest)):
                return self.reply(302, headers={"Location": f"http://{self.headers['Host']}/download/tarball/{x[1]}"})
            if rest == "/commits": return self.reply(200, COMMITS if q.get("sha", "main") == "main" else COMMITS[:0])
            if rest == "/pulls": return self.reply(200, PULLS)
            if rest == "/actions/workflows": return self.reply(200, {"total_count": len(WORKFLOWS), "workflows": WORKFLOWS})
            if rest == "/actions/runs" or re.match(r"^/actions/workflows/\d+/runs$", rest):
                wf = re.findall(r"\d+", rest)
                rs = [r for r in RUNS if (not wf or r["workflow_id"] == int(wf[0])) and (not q.get("branch") or r["head_branch"] == q["branch"])]
                return self.reply(200, {"total_count": len(rs), "workflow_runs": rs[:int(q.get("per_page", 30))]})
            if (x := re.match(r"^/actions/runs/(\d+)$", rest)):
                r = next((r for r in RUNS if r["id"] == int(x[1])), None)
                return self.reply(200, r) if r else self.reply(404, {"message": "Not Found"})
            if (x := re.match(r"^/actions/runs/(\d+)/jobs$", rest)): return self.reply(200, {"jobs": JOBS.get(int(x[1]), [])})
            if (x := re.match(r"^/actions/jobs/(\d+)/logs$", rest)):
                return self.reply(302, headers={"Location": f"http://{self.headers['Host']}/download/log/{x[1]}"})
            if rest == "/contents" or rest.startswith("/contents/"):  # folders list their entries; files come base64-encoded
                path = rest[len("/contents/"):] if rest != "/contents" else ""
                tree = {k: v.decode("utf-8", "replace") for k, v in files_at(m[1], q.get("ref", "main")).items()}
                if path in tree:
                    f = tree[path]
                    return self.reply(200, {"type": "file", "name": path.rsplit("/", 1)[-1], "path": path, "size": len(f), "sha": "f" * 40, "encoding": "base64",
                                            "content": base64.b64encode(f.encode()).decode(), "html_url": f"https://github.com/{m[1]}/blob/main/{path}"})
                kids = {p[len(path) + 1 if path else 0:].split("/")[0] for p in tree if not path or p.startswith(path + "/")}
                if not kids: return self.reply(404, {"message": "Not Found"})
                full = lambda k: f"{path}/{k}" if path else k
                return self.reply(200, [{"name": k, "path": full(k), "type": "file" if full(k) in tree else "dir", "size": len(tree.get(full(k), ""))} for k in sorted(kids)])
            if (x := re.match(r"^/git/trees/(.+)$", rest)):
                ref = x[1].replace("%2F", "/")
                if ref not in HEADS: return self.reply(404, {"message": "Not Found"})
                fs, dirs = files_at(m[1], ref), set()
                for f in fs: dirs.update("/".join(f.split("/")[:i]) for i in range(1, f.count("/") + 1))
                return self.reply(200, {"sha": HEADS[ref], "truncated": False, "tree": [{"path": d, "type": "tree", "mode": "040000", "sha": "e" * 40} for d in sorted(dirs)]
                                        + [{"path": f, "type": "blob", "mode": "100644", "sha": blob_sha(raw), "size": len(raw)} for f, raw in sorted(fs.items())]})
            if (x := re.match(r"^/git/blobs/([0-9a-f]{40})$", rest)):
                raw = BLOBS.get(x[1])
                return self.reply(200, {"sha": x[1], "size": len(raw), "encoding": "base64", "content": base64.b64encode(raw).decode()}) if raw is not None else self.reply(404, {"message": "Not Found"})
            if (x := re.match(r"^/git/commits/([0-9a-f]{40})$", rest)): return self.reply(200, {"sha": x[1], "tree": {"sha": "t" * 40}})
            if rest == "/deployments": return self.reply(200, DEPLOYS)
            if (x := re.match(r"^/deployments/(\d+)/statuses$", rest)): return self.reply(200, STATUSES.get(int(x[1]), []))
        if method == "POST" and (x := re.match(r"^/actions/workflows/(\d+)/dispatches$", rest)):
            wf = next((w for w in WORKFLOWS if w["id"] == int(x[1])), None)
            if not wf: return self.reply(404, {"message": "Not Found"})
            if wf["id"] == 101: return self.reply(422, {"message": "Workflow does not have 'workflow_dispatch' trigger"})
            DISPATCHES.append(body)
            RUNS.insert(0, run(max(r["id"] for r in RUNS) + 1, wf, "queued", None, "a" * 40, body["ref"], 0))
            return self.reply(204)
        if method == "POST" and (x := re.match(r"^/actions/runs/(\d+)/(cancel|rerun|rerun-failed-jobs)$", rest)):
            r = next((r for r in RUNS if r["id"] == int(x[1])), None)
            if not r: return self.reply(404, {"message": "Not Found"})
            if x[2] == "cancel":
                if r["status"] == "completed": return self.reply(409, {"message": "Cannot cancel a workflow run that is completed."})
                r.update(status="completed", conclusion="cancelled"); return self.reply(202, {})
            r.update(status="queued", conclusion=None, run_attempt=r["run_attempt"] + 1); return self.reply(201, {})
        if method == "POST" and rest in ("/git/blobs", "/git/trees", "/git/commits") and m[1].lower() == "scout/validator":
            return self.reply(403, {"message": "Resource not accessible by personal access token"})
        if method == "POST" and rest == "/git/blobs": return self.reply(201, {"sha": blob_sha(base64.b64decode(body["content"]))})
        if method == "POST" and rest == "/git/trees":
            sha = hashlib.sha1(json.dumps(body, sort_keys=True).encode()).hexdigest(); TREES[sha] = body["tree"]; return self.reply(201, {"sha": sha})
        if method == "POST" and rest == "/git/commits":
            sha = hashlib.sha1(json.dumps(body, sort_keys=True).encode()).hexdigest(); NEWCOMMITS[sha] = (body["tree"], body["message"], body["parents"][0])
            return self.reply(201, {"sha": sha, "html_url": f"https://github.com/{m[1]}/commit/{sha}"})
        if method == "PATCH" and (x := re.match(r"^/git/refs/heads/(.+)$", rest)):
            branch, c = x[1], NEWCOMMITS.get(body["sha"])
            if branch not in HEADS or not c: return self.reply(404, {"message": "Not Found"})
            if c[2] != HEADS[branch]: return self.reply(422, {"message": "Update is not a fast forward"})
            for e in TREES[c[0]]:
                raw = BLOBS[e["sha"]]; WRITES[(m[1].lower(), branch, e["path"])] = (raw.decode("utf-8", "replace"), e["sha"])
                COMMITTED.append({"repo": m[1], "branch": branch, "path": e["path"], "message": c[1], "sha": body["sha"], "bytes": len(raw), "update": False})
            HEADS[branch] = body["sha"]
            return self.reply(200, {"ref": f"refs/heads/{branch}", "object": {"sha": body["sha"]}})
        if method == "POST" and rest == "/git/refs":
            name = body["ref"].removeprefix("refs/heads/")
            if name in HEADS: return self.reply(422, {"message": "Reference already exists"})
            HEADS[name] = body["sha"]; return self.reply(201, {"ref": body["ref"], "object": {"sha": body["sha"]}})
        if method == "PUT" and rest.startswith("/contents/"):
            if m[1].lower() == "scout/validator": return self.reply(403, {"message": "Resource not accessible by personal access token"})
            path, branch = rest[len("/contents/"):], body.get("branch") or "main"
            if branch not in HEADS: return self.reply(404, {"message": f"Branch {branch} not found"})
            k, cur = (m[1].lower(), branch, path), WRITES.get((m[1].lower(), branch, path))
            if cur and not body.get("sha"): return self.reply(422, {"message": "Invalid request.\n\n\"sha\" wasn't supplied."})
            if cur and body["sha"] != cur[1]: return self.reply(409, {"message": f"{path} does not match {body['sha']}"})
            text = base64.b64decode(body["content"]).decode()
            blob, sha = hashlib.sha1(text.encode()).hexdigest(), hashlib.sha1(f"{HEADS[branch]}{path}{text}".encode()).hexdigest()
            WRITES[k], HEADS[branch] = (text, blob), sha
            COMMITTED.append({"repo": m[1], "branch": branch, "path": path, "message": body["message"], "sha": sha, "bytes": len(text), "update": bool(cur)})
            return self.reply(200 if cur else 201, {"content": {"path": path, "sha": blob, "html_url": f"https://github.com/{m[1]}/blob/{branch}/{path}"},
                                                    "commit": {"sha": sha, "html_url": f"https://github.com/{m[1]}/commit/{sha}"}})
        if method == "PUT" and (x := re.match(r"^/actions/workflows/(\d+)/(enable|disable)$", rest)):
            wf = next((w for w in WORKFLOWS if w["id"] == int(x[1])), None)
            if not wf: return self.reply(404, {"message": "Not Found"})
            wf["state"] = "active" if x[2] == "enable" else "disabled_manually"; return self.reply(204)
        return self.reply(404, {"message": "Not Found"})

    def do_GET(self): self.route("GET")
    def do_POST(self): self.route("POST")
    def do_PUT(self): self.route("PUT")
    def do_PATCH(self): self.route("PATCH")

if __name__ == "__main__":
    HTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8797), H).serve_forever()
