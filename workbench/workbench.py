#!/usr/bin/env python3
"""AXoR Workbench: Mining HQ's agents work on real folders of this host, the way Claude Code does in VS Code.

It runs on the host (systemd, workbench/axor-workbench.service), not in k3s: it needs the folders and the host's Claude Code
login. It listens on the pod network's gateway only (10.42.0.1:8350), and every call but /health carries the shared token.

- Folders: only the repos named in the config (/etc/axor-workbench.json). AXoR sends a repo id, never a path; every path is
  resolved and must stay inside the repo.
- Agents never touch the live checkout. Each task gets its own git worktree on a bench/<slug> branch, made from a commit, under
  the state folder. The agent's edits are committed there when its run ends, so the work is one branch you can read as a diff.
  Merging into the checkout is a separate call that refuses when the checkout's index isn't clean or its uncommitted files
  overlap the branch; then it answers with the command to run by hand. AXoR sends the commit you approved ("expect"): when
  the branch has moved on since, the merge refuses, so what lands is exactly what was reviewed and checked.
- Runs are `claude -p` with a fixed tool set per kind: plan and review read only (Read, Glob, Grep), engineer also edits
  (Edit, Write) inside its worktree. No agent gets Bash. Checks (unit tests, an eval) are commands from the config, run by
  this service in the worktree when you click them, never by an agent. A check with "results" (a JSON-lines file it writes,
  e.g. eval.py's runs.jsonl) hands that file back with the run, so AXoR can score the commit (mining_lab.py).
- Runs queue behind `parallel` (default 2): they spend the same Claude subscription as your own Claude Code sessions.
- Loadouts (AXoR's mining_loadout.py): a run can bring skills, MCP servers and an effort level. Skills are text: this service
  writes them as SKILL.md files into a plugin folder of its own, outside the worktree, made fresh for the run and deleted after;
  nothing else ever goes in it (no hooks, no MCP, no agents). MCP servers come only from the config's "mcp" list, by id: AXoR
  never sends a command.

Standard library only: the host has no FastAPI.
"""
import hashlib, hmac, ipaddress, json, os, re, shutil, signal, subprocess, sys, threading, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

VERSION = "3"
FEATURES = ["skills", "mcp", "effort", "pinned-merge", "results"]
CONFIG = Path(os.environ.get("WORKBENCH_CONFIG", "/etc/axor-workbench.json"))
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}$")
SHA = re.compile(r"^[0-9a-f]{7,40}$")
MODEL = re.compile(r"^[a-z0-9][a-z0-9.\-\[\]]{1,60}$")
SESSION = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
TOOLS = {"plan": "Read,Glob,Grep", "review": "Read,Glob,Grep", "engineer": "Read,Edit,Write,Glob,Grep"}
EFFORTS = ("low", "medium", "high", "xhigh", "max")
MAX_SKILLS, SKILL_CAP = 16, 20_000
FILE_CAP, DIFF_CAP, EVENTS_CAP, LIST_CAP = 512_000, 400_000, 3000, 600
RESULTS_CAP, RESULTS_LINES = 4_000_000, 5000
DEFAULT_SKIP = [".git", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache", ".pytest_cache"]

cfg = {}
runs, lock = {}, threading.Lock()
slots = None
last_rate = {}


def load_config():
    global cfg, slots
    c = json.loads(CONFIG.read_text())
    if not c.get("token") or len(c["token"]) < 24: sys.exit("The config needs a token of 24 characters or more.")
    c.setdefault("listen", "10.42.0.1"); c.setdefault("port", 8350); c.setdefault("parallel", 2); c.setdefault("max_budget_usd", 5.0)
    c.setdefault("state", "/var/lib/axor-workbench"); c.setdefault("claude", shutil.which("claude") or "/root/.local/bin/claude")
    c.setdefault("allow_from", ["10.42.0.0/16", "127.0.0.1/32"])
    for rid, r in c.get("repos", {}).items():
        if not SLUG.match(rid): sys.exit(f"Repo id {rid!r}: lower-case letters, digits and dashes only.")
        r["path"] = str(Path(r["path"]).resolve())
        r.setdefault("name", rid); r.setdefault("skip", []); r.setdefault("deny", []); r.setdefault("protect", []); r.setdefault("checks", {})
    for mid, m in c.setdefault("mcp", {}).items():
        if not SLUG.match(mid): sys.exit(f"MCP server id {mid!r}: lower-case letters, digits and dashes only.")
        if not m.get("command"): sys.exit(f"MCP server {mid!r} needs a command.")
        m.setdefault("label", mid); m.setdefault("note", ""); m.setdefault("args", []); m.setdefault("env", {}); m.setdefault("kinds", list(TOOLS))
    cfg, slots = c, threading.BoundedSemaphore(max(1, int(c["parallel"])))
    for d in ("worktrees", "runs"): Path(c["state"], d).mkdir(parents=True, exist_ok=True)


class Fail(Exception):
    def __init__(self, code, msg): super().__init__(msg); self.code = code


def git(repo, *args, cwd=None, check=True, timeout=60):
    p = subprocess.run(["git", "-C", cwd or repo["path"], *args], capture_output=True, text=True, timeout=timeout)
    if check and p.returncode: raise Fail(409, (p.stderr or p.stdout).strip()[:600] or f"git {args[0]} failed")
    return p.stdout


def repo_of(rid):
    r = cfg["repos"].get(rid or "")
    if not r: raise Fail(404, "No such folder on the workbench.")
    return r


def inside(root, rel):
    """The path rel inside root, or a 400: no absolute paths, no way out through .. or links."""
    rel = (rel or "").strip().lstrip("/")
    p = (Path(root) / rel).resolve()
    if p != Path(root).resolve() and Path(root).resolve() not in p.parents: raise Fail(400, "That path is outside the folder.")
    return p, rel


def branch_of(slug):
    if not SLUG.match(slug or ""): raise Fail(400, "Bad branch name.")
    return f"bench/{slug}"


def tree_path(repo, slug):
    return Path(cfg["state"], "worktrees", next(k for k, v in cfg["repos"].items() if v is repo), slug)


def repo_state(rid, r):
    out = {"id": rid, "name": r["name"], "path": r["path"],
           "checks": [{"id": k, "label": v.get("label", k), "note": v.get("note", ""), "scored": bool(v.get("results"))} for k, v in r["checks"].items()]}
    try:
        out["branch"] = git(r, "symbolic-ref", "--short", "-q", "HEAD", check=False).strip() or None
        out["head"] = git(r, "rev-parse", "HEAD").strip()
        out["subject"] = git(r, "log", "-1", "--format=%s").strip()
        dirty = [l for l in git(r, "status", "--porcelain", "--ignore-submodules=all").splitlines() if l.strip()]
        out["dirty"] = len(dirty)
        out["staged"] = sum(1 for l in dirty if l[0] not in " ?")
        heads = dict(l.split(" ", 1)[::-1] for l in git(r, "for-each-ref", "--format=%(objectname) %(refname:short)", "refs/heads").splitlines() if l.strip())
        out["heads"] = {b: s for b, s in heads.items() if not b.startswith("bench/")}
        out["branches"] = sorted(out["heads"])[:40]
    except Exception as e:  # noqa: BLE001 - shown on the page
        out["error"] = str(e)[:300]
    return out


# ---------- files ----------
def list_dir(r, rel, ref):
    if ref:
        target = ref if SHA.match(ref) else branch_of(ref.removeprefix("bench/"))
        _, rel = inside(r["path"], rel)
        raw = git(r, "ls-tree", "-l", f"{target}:{rel}" if rel else target, check=False)
        items = []
        for line in raw.splitlines()[:LIST_CAP]:
            meta, name = line.split("\t", 1)
            kind, size = meta.split()[1], meta.split()[3]
            items.append({"name": name, "dir": kind == "tree", "size": None if size == "-" else int(size)})
        return {"path": rel, "ref": ref, "items": sorted(items, key=lambda x: (not x["dir"], x["name"].lower()))}
    p, rel = inside(r["path"], rel)
    if not p.is_dir(): raise Fail(404, "No such folder.")
    skip = set(DEFAULT_SKIP + r["skip"])
    items, hidden = [], 0
    for e in sorted(os.scandir(p), key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.lower())):
        if e.name in skip or (rel == "" and e.name in r["skip"]): hidden += 1; continue
        if len(items) >= LIST_CAP: hidden += 1; continue
        d = e.is_dir(follow_symlinks=False)
        items.append({"name": e.name, "dir": d, "size": None if d else e.stat(follow_symlinks=False).st_size, "link": e.is_symlink()})
    return {"path": rel, "ref": "", "items": items, "hidden": hidden}


def read_file(r, rel, ref):
    if ref:
        target = ref if SHA.match(ref) else branch_of(ref.removeprefix("bench/"))
        _, rel = inside(r["path"], rel)
        p = subprocess.run(["git", "-C", r["path"], "show", f"{target}:{rel}"], capture_output=True, timeout=30)
        if p.returncode: raise Fail(404, "No such file on that branch.")
        data = p.stdout
    else:
        p, rel = inside(r["path"], rel)
        if not p.is_file(): raise Fail(404, "No such file.")
        with open(p, "rb") as f: data = f.read(FILE_CAP + 1)
    binary = b"\0" in data[:8000]
    return {"path": rel, "ref": ref, "size": len(data), "truncated": len(data) > FILE_CAP, "binary": binary,
            "content": "" if binary else data[:FILE_CAP].decode("utf-8", "replace")}


def diff(r, base, slug):
    if not SHA.match(base or ""): raise Fail(400, "Bad base commit.")
    b = branch_of(slug)
    if not git(r, "rev-parse", "--verify", "-q", b, check=False).strip(): return {"branch": b, "files": [], "patch": "", "commits": []}
    stat = git(r, "diff", "--numstat", f"{base}...{b}")
    files = []
    for line in stat.splitlines():
        a, d, name = line.split("\t", 2)
        files.append({"path": name, "added": None if a == "-" else int(a), "removed": None if d == "-" else int(d)})
    patch = git(r, "diff", "--no-color", "-U3", f"{base}...{b}")
    commits = [dict(zip(("sha", "subject", "when"), l.split("\t", 2))) for l in git(r, "log", "--format=%h\t%s\t%cI", f"{base}..{b}").splitlines()]
    return {"branch": b, "head": git(r, "rev-parse", b).strip(), "files": files, "patch": patch[:DIFF_CAP], "truncated": len(patch) > DIFF_CAP, "commits": commits}


def ensure_tree(r, slug, base):
    """The task's worktree on bench/<slug>, made from base the first time."""
    b, path = branch_of(slug), tree_path(r, slug)
    if path.is_dir() and (path / ".git").exists(): return path
    if not SHA.match(base or ""): raise Fail(400, "Bad base commit.")
    path.parent.mkdir(parents=True, exist_ok=True)
    have = git(r, "rev-parse", "--verify", "-q", b, check=False).strip()
    git(r, "worktree", "prune", check=False)
    git(r, "worktree", "add", *([str(path), b] if have else ["-b", b, str(path), base]), timeout=300)
    return path


def commit_tree(r, path, message, who):
    if not git(r, "status", "--porcelain", cwd=str(path)).strip(): return None
    git(r, "add", "-A", cwd=str(path))
    git(r, "-c", f"user.name=AXoR {who}", "-c", "user.email=workbench@axor.local", "commit", "-q", "--no-verify", "-m", message[:400], cwd=str(path))
    return git(r, "rev-parse", "--short", "HEAD", cwd=str(path)).strip()


def merge(r, slug, into, expect=""):
    b = branch_of(slug)
    how = f"cd {r['path']} && git checkout {into} && git merge --no-ff {b}"
    tip = git(r, "rev-parse", "--verify", "-q", b, check=False).strip()
    if not tip: return {"ok": False, "why": f"There's no branch {b} any more."}
    if expect:
        if not SHA.match(expect): raise Fail(400, "Bad commit.")
        if not tip.startswith(expect):
            return {"ok": False, "moved": True, "from": tip, "why": f"{b} is at {tip[:8]} now, not at {expect[:8]}, the commit you approved: look at the new work first."}
    cur = git(r, "symbolic-ref", "--short", "-q", "HEAD", check=False).strip()
    if cur != into: return {"ok": False, "why": f"The folder has {cur or 'a detached HEAD'} checked out, not {into}.", "how": how}
    if subprocess.run(["git", "-C", r["path"], "diff", "--cached", "--quiet", "--ignore-submodules=all"], timeout=60).returncode:
        return {"ok": False, "why": "You have staged changes in the folder; merging now would mix them into the merge.", "how": how}
    dirty = {l[3:].split(" -> ")[-1] for l in git(r, "status", "--porcelain", "--ignore-submodules=all").splitlines() if l.strip()}
    touched = set(git(r, "diff", "--name-only", f"{into}...{b}").split())
    clash = sorted(dirty & touched)
    if clash: return {"ok": False, "why": "You have uncommitted changes in files this branch also changes: " + ", ".join(clash[:8]), "how": how}
    p = subprocess.run(["git", "-C", r["path"], "merge", "--no-ff", "--no-edit", "-m", f"Merge branch '{b}' at {tip[:8]}", tip],  # the tip checked above, not whatever the branch is by now
                       capture_output=True, text=True, timeout=120)
    if p.returncode:
        if Path(r["path"], ".git", "MERGE_HEAD").exists(): subprocess.run(["git", "-C", r["path"], "merge", "--abort"], capture_output=True)
        return {"ok": False, "why": "The merge had conflicts, so it was undone: " + (p.stdout + p.stderr).strip()[-400:], "how": how}
    return {"ok": True, "head": git(r, "rev-parse", "--short", "HEAD").strip(), "from": tip}


def drop(r, slug):
    b, path = branch_of(slug), tree_path(r, slug)
    for rid, run in list(runs.items()):
        if run.get("slug") == slug and run["status"] in ("queued", "running"): stop(rid)
    if path.exists(): git(r, "worktree", "remove", "--force", str(path), check=False); shutil.rmtree(path, ignore_errors=True)
    git(r, "worktree", "prune", check=False)
    git(r, "branch", "-D", b, check=False)
    return {"ok": True}


# ---------- runs ----------
def short_arg(name, inp, cwd):
    v = inp.get("file_path") or inp.get("path") or inp.get("pattern") or inp.get("command") or ""
    v = str(v)
    if cwd and v.startswith(cwd): v = v[len(cwd):].lstrip("/") or "."
    return v[:200]


def add(run, ev):
    ev["t"] = round(time.time() - run["started_at"], 1) if run.get("started_at") else 0
    with lock:
        run["events"].append(ev)
        if len(run["events"]) > EVENTS_CAP: run["events"] = run["events"][:50] + [{"k": "note", "text": "…earlier steps cut…"}] + run["events"][-EVENTS_CAP + 60:]
        run["n"] += 1


class Stuck:
    """A run going in circles (AXoR's backend/app/stuck.py, copied: this file is standard library only, alone on the host):
    the same tool call with the same result REPEAT times in a row, or the same call with the same error ERRORS times."""
    REPEAT, ERRORS = 5, 3

    def __init__(self):
        self.calls, self.last, self.streak, self.failed, self.reason = {}, None, 0, {}, ""

    def use(self, b):
        self.calls[str(b.get("id"))] = (str(b.get("name") or "?"), json.dumps(b.get("input"), sort_keys=True, default=str))

    def result(self, b):
        name, inp = self.calls.pop(str(b.get("tool_use_id")), (None, None))
        if self.reason or name is None: return self.reason
        c = b.get("content"); c = c if isinstance(c, str) else json.dumps(c, sort_keys=True, default=str)
        same = hashlib.sha1("\0".join((name, inp, " ".join(c.split()))).encode("utf-8", "replace")).hexdigest()
        self.streak = self.streak + 1 if same == self.last else 1
        self.last = same
        if self.streak >= self.REPEAT:
            self.reason = f"Stopped: the run was going in circles. It called {name} {self.streak} times in a row with the same input and got the same result each time."
        elif b.get("is_error"):
            self.failed[same] = self.failed.get(same, 0) + 1
            if self.failed[same] >= self.ERRORS:
                self.reason = f"Stopped: the run was going in circles. {name} failed {self.failed[same]} times with the same input and the same error."
        return self.reason


def killpg(pid, sig):
    try: os.killpg(pid, sig)
    except ProcessLookupError: pass


def parse(run, line, cwd, watch=None):
    try: d = json.loads(line)
    except ValueError: return add(run, {"k": "out", "text": line[:2000]})
    t = d.get("type")
    if t == "system" and d.get("subtype") == "init":
        run["session"] = d.get("session_id"); run["model"] = d.get("model")
        skills = [x.split(":", 1)[1] for x in d.get("skills") or [] if x.startswith("axor-loadout:")]
        mcp = [f"{x.get('name')} ({x.get('status')})" for x in d.get("mcp_servers") or []]
        run["loaded"] = {"skills": skills, "mcp": d.get("mcp_servers") or []}
        return add(run, {"k": "note", "text": f"Claude Code {d.get('claude_code_version', '')} started ({d.get('model')}), tools: {', '.join(t for t in d.get('tools') or [] if not t.startswith('mcp__'))}"
                         + (f" · skills: {', '.join(skills)}" if skills else "") + (f" · MCP: {', '.join(mcp)}" if mcp else "")})
    if t == "rate_limit_event":
        w = (d.get("rate_limit_info") or {}).get("unifiedWindows") or {}
        last_rate.update({k: {"used": v.get("utilization"), "resets": v.get("resetsAt"), "status": v.get("status")} for k, v in w.items()})
        run["rate"] = dict(last_rate)
        return
    if t == "assistant":
        for b in (d.get("message") or {}).get("content") or []:
            if b.get("type") == "text" and b.get("text", "").strip(): add(run, {"k": "say", "text": b["text"][:8000]})
            elif b.get("type") == "tool_use":
                add(run, {"k": "tool", "name": b.get("name"), "arg": short_arg(b.get("name"), b.get("input") or {}, cwd)})
                if watch: watch.use(b)
        return
    if t == "user":
        for b in (d.get("message") or {}).get("content") or []:
            if watch and isinstance(b, dict) and b.get("type") == "tool_result": watch.result(b)
            if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("is_error"):
                c = b.get("content"); c = c if isinstance(c, str) else json.dumps(c)[:600]
                add(run, {"k": "err", "text": c[:600]})
        return
    if t == "result":
        run["result"] = d.get("result") or ""
        run["structured"] = d.get("structured_output")
        run["cost"] = d.get("total_cost_usd") or 0
        run["turns"] = d.get("num_turns")
        run["denied"] = [x.get("tool_name") for x in d.get("permission_denials") or []]
        if d.get("is_error") or (d.get("subtype") or "").startswith("error"):
            run["error"] = (d.get("result") or d.get("subtype") or "The run ended with an error.")[:600]
        add(run, {"k": "done", "text": f"Finished in {d.get('num_turns')} turns, ${run['cost']:.3f}" + (f" · {run['error']}" if run.get("error") else "")})


def clean_env():
    keep = {k: os.environ[k] for k in ("PATH", "HOME", "LANG", "LC_ALL", "USER") if k in os.environ}
    keep.setdefault("HOME", "/root"); keep.setdefault("PATH", "/root/.local/bin:/usr/local/bin:/usr/bin:/bin")
    keep["TERM"] = "dumb"
    return keep


def one_line(s, cap):
    return re.sub(r"\s+", " ", str(s or "")).strip()[:cap]


def loadout_files(b, kind, rid, made):
    """The run's plugin folder (its skills) and MCP config, written by this service only; (argv additions, paths to delete)."""
    argv, tools = [], []
    skills = b.get("skills") or []
    if not isinstance(skills, list) or len(skills) > MAX_SKILLS: raise Fail(400, f"At most {MAX_SKILLS} skills.")
    if skills:
        root = Path(cfg["state"], "runs", f"{rid}-plugin")
        (root / ".claude-plugin").mkdir(parents=True, exist_ok=True); made.append(root)
        (root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "axor-loadout", "version": "1.0.0", "description": "Skills from the agent's AXoR loadout."}))
        for sk in skills:
            name = str((sk or {}).get("name") or "")
            if not SLUG.match(name): raise Fail(400, f"Bad skill name {name[:40]!r}.")
            desc = one_line(sk.get("description"), 1000) or name
            d = root / "skills" / name; d.mkdir(parents=True, exist_ok=True)
            (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {json.dumps(desc)}\n---\n\n" + str(sk.get("body") or "")[:SKILL_CAP] + "\n")
        argv += ["--plugin-dir", str(root)]; tools.append("Skill")
    mcp = b.get("mcp") or []
    if not isinstance(mcp, list): raise Fail(400, "Bad MCP list.")
    if mcp:
        servers = {}
        for mid in mcp:
            m = cfg["mcp"].get(str(mid))
            if not m: raise Fail(400, f"The workbench offers no MCP server {str(mid)[:40]!r}.")
            if kind not in m["kinds"]: raise Fail(400, f"MCP server {mid} isn't offered to {kind} runs.")
            servers[mid] = {"type": "stdio", "command": m["command"], "args": [str(a) for a in m["args"]], "env": {str(k): str(v) for k, v in m["env"].items()}}
        f = Path(cfg["state"], "runs", f"{rid}-mcp.json"); f.write_text(json.dumps({"mcpServers": servers})); f.chmod(0o600); made.append(f)
        argv += ["--mcp-config", str(f), "--allowedTools", *[f"mcp__{mid}" for mid in servers]]
    effort = b.get("effort") or ""
    if effort:
        if effort not in EFFORTS: raise Fail(400, "Bad effort level.")
        argv += ["--effort", effort]
    return argv, made, tools


def claude_argv(r, b, cwd, rid):
    kind = b["kind"]
    model = b.get("model") or "sonnet"
    if not MODEL.match(model): raise Fail(400, "Bad model name.")
    budget = min(float(b.get("budget_usd") or 1.0), float(cfg["max_budget_usd"]))
    made = []
    try: extra, made, more_tools = loadout_files(b, kind, rid, made)
    except Exception:
        for m in made: shutil.rmtree(m, ignore_errors=True) if Path(m).is_dir() else Path(m).unlink(missing_ok=True)
        raise
    argv = [cfg["claude"], "-p", str(b.get("prompt") or "")[:60000], "--model", model, "--output-format", "stream-json", "--verbose",
            "--tools", ",".join([TOOLS[kind], *more_tools]), "--permission-mode", "acceptEdits" if kind == "engineer" else "default",
            "--strict-mcp-config", "--setting-sources", "", "--max-budget-usd", f"{budget:.2f}", *extra]
    # No settings from the folder: a .claude/settings.json an agent wrote could hold a hook, which would run as root on the
    # next run. The folder's CLAUDE.md (its rules) still goes in, read here.
    rules = Path(cwd, "CLAUDE.md")
    system = str(b.get("system") or "")[:20000]
    if rules.is_file(): system += ("\n\n" if system else "") + "The folder's CLAUDE.md:\n" + rules.read_text(errors="replace")[:30000]
    if system: argv += ["--append-system-prompt", system]
    if b.get("schema"): argv += ["--json-schema", json.dumps(b["schema"])[:20000]]
    deny = [f"Read(/{Path(root, d)}/**)" if not Path(root, d).suffix else f"Read(/{Path(root, d)})" for root in {r["path"], str(cwd)} for d in r["deny"]]
    deny += [f"{t}(/{Path(cwd, x)}{s})" for t in ("Edit", "Write") for x, s in ((".claude", "/**"), (".mcp.json", ""))]  # nor in the branch you merge
    # the config's "protect": paths an engineer may read but never edit (D-040: AXoR's own deploy, sign-in and sandbox code); AXoR checks the diff again
    deny += [f"{t}(/{Path(cwd, x)}{'' if Path(x).suffix else '/**'})" for t in ("Edit", "Write") for x in r.get("protect", [])]
    deny += ["Bash", "WebFetch", "WebSearch", "Task"]
    argv += ["--disallowedTools", *deny]
    if b.get("resume"):
        if not SESSION.match(b["resume"]): raise Fail(400, "Bad session id.")
        argv += ["--resume", b["resume"]]
    else: argv += ["--session-id", str(uuid.uuid4())]
    return argv, made


def check_argv(r, b, cwd, rid):
    ch = r["checks"].get(b.get("check") or "")
    if not ch: raise Fail(404, "No such check for this folder.")
    sub = lambda s: s.replace("{worktree}", str(cwd)).replace("{run}", rid).replace("{repo}", r["path"])
    results = None
    if ch.get("results"):  # where the check writes its JSON lines: inside the folder or the task's worktree, nowhere else
        results = Path(sub(ch["results"])).resolve()
        if not any(results == Path(x).resolve() or Path(x).resolve() in results.parents for x in (r["path"], cwd)): raise Fail(400, "The check's results file is outside the folder.")
    return [sub(a) for a in ch["argv"]], Path(sub(ch.get("cwd", "{worktree}"))), int(ch.get("timeout", 900)), results


def read_results(path):
    """The check's JSON lines (each an object), capped; lines that aren't JSON objects are skipped."""
    out, size = [], 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            size += len(line)
            if size > RESULTS_CAP or len(out) >= RESULTS_LINES: break
            try: o = json.loads(line)
            except ValueError: continue
            if isinstance(o, dict): out.append(o)
    return out


def start(rid_repo, b):
    r = repo_of(rid_repo)
    kind = b.get("kind")
    if kind not in ("plan", "engineer", "review", "check"): raise Fail(400, "Unknown kind of run.")
    rid = uuid.uuid4().hex[:12]
    slug = b.get("slug") or ""
    if kind == "plan": cwd = Path(r["path"])
    else: cwd = ensure_tree(r, slug, b.get("base"))
    made, results = [], None
    if kind == "check": argv, cwd, timeout, results = check_argv(r, b, cwd, rid)
    else: (argv, made), timeout = claude_argv(r, b, cwd, rid), int(b.get("timeout_s") or 1800)
    run = {"id": rid, "repo": rid_repo, "kind": kind, "slug": slug, "status": "queued", "events": [], "n": 0, "created": time.time(),
           "who": str(b.get("who") or "agent")[:40], "title": str(b.get("title") or "")[:300], "cost": 0, "proc": None, "made": [str(m) for m in made]}
    if results: run["results_path"] = str(results)
    with lock: runs[rid] = run
    threading.Thread(target=work, args=(r, run, argv, cwd, timeout), daemon=True).start()
    return public(run)


def work(r, run, argv, cwd, timeout):
    with slots:
        if run["status"] == "stopped":
            for m in run.pop("made", []): shutil.rmtree(m, ignore_errors=True) if Path(m).is_dir() else Path(m).unlink(missing_ok=True)
            return save(run)
        run["status"], run["started_at"] = "running", time.time()
        add(run, {"k": "note", "text": ("Running " + " ".join(argv[:6])) if run["kind"] == "check" else f"Working in {cwd}"})
        try:
            p = subprocess.Popen(argv, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=clean_env(), start_new_session=True)
            run["proc"] = p
            killer = threading.Timer(timeout, lambda: (run.update(error=f"Stopped after {timeout} s."), os.killpg(p.pid, signal.SIGTERM)))
            killer.start()
            watch = Stuck() if run["kind"] != "check" else None
            for line in p.stdout:
                line = line.rstrip("\n")
                if not line: continue
                if run["kind"] == "check": add(run, {"k": "out", "text": line[:2000]})
                else: parse(run, line, str(cwd), watch)
                if watch and watch.reason and not run.get("error"):  # going in circles: end it now, not at the timeout or budget
                    run["error"] = watch.reason
                    add(run, {"k": "err", "text": watch.reason})
                    killpg(p.pid, signal.SIGTERM)
                    threading.Timer(5, killpg, (p.pid, signal.SIGKILL)).start()  # one that ignores SIGTERM
            p.wait(); killer.cancel()
            run["exit"] = p.returncode
            if run["kind"] == "check" and p.returncode and not run.get("error"): run["error"] = f"Exited with {p.returncode}."
            if run["kind"] not in ("check",) and p.returncode and not run.get("error") and run["status"] != "stopped":
                run["error"] = f"Claude Code exited with {p.returncode}."
        except Exception as e:  # noqa: BLE001 - shown on the task
            run["error"] = str(e)[:600]
        if run["kind"] == "engineer":
            try:
                sha = commit_tree(r, cwd, run["title"] or "Agent's work", run["who"])
                run["commit"] = sha
                add(run, {"k": "note", "text": f"Committed the changes as {sha} on {branch_of(run['slug'])}" if sha else "No files changed."})
            except Exception as e:  # noqa: BLE001
                add(run, {"k": "err", "text": f"Couldn't commit the work: {e}"[:600]})
        if run.get("results_path") and run["status"] != "stopped":
            try:
                if os.path.getmtime(run["results_path"]) < run.get("started_at", 0): raise OSError("it's older than this run (put {run} in its path)")
                run["results"] = read_results(run["results_path"])
                add(run, {"k": "note", "text": f"Read {len(run['results'])} result lines from {run['results_path']}"})
            except OSError as e:  # a scored check that leaves no score didn't do its job
                run["error"] = f"The check wrote no results file: {e}"[:600]
                add(run, {"k": "err", "text": run["error"]})
        for m in run.pop("made", []):  # the run's plugin folder and MCP config
            shutil.rmtree(m, ignore_errors=True) if Path(m).is_dir() else Path(m).unlink(missing_ok=True)
        run["finished"] = time.time()
        if run["status"] != "stopped": run["status"] = "failed" if run.get("error") else "done"
        save(run)


def save(run):
    out = {k: v for k, v in run.items() if k != "proc"}
    Path(cfg["state"], "runs", f"{run['id']}.json").write_text(json.dumps(out))


def stop(rid):
    run = runs.get(rid)
    if not run: raise Fail(404, "No such run.")
    if run["status"] in ("queued", "running"):
        run["status"] = "stopped"; run["error"] = "Stopped by you."
        p = run.get("proc")
        if p and p.poll() is None:
            try: os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError: pass
        add(run, {"k": "note", "text": "Stopped."})
    return public(run)


def public(run, after=0):
    with lock:
        ev = run["events"]
        skip = max(0, after - (run["n"] - len(ev)))
        out = {k: v for k, v in run.items() if k not in ("proc", "events")}
        out["events"], out["from"] = ev[skip:], after
    return out


def get_run(rid, after):
    run = runs.get(rid)
    if not run:
        f = Path(cfg["state"], "runs", f"{rid}.json") if re.match(r"^[0-9a-f]{12}$", rid) else None
        if not f or not f.exists(): raise Fail(404, "No such run.")
        run = json.loads(f.read_text())
        if run["status"] in ("queued", "running"): run.update(status="failed", error="The workbench restarted while it ran.")
        with lock: runs[rid] = run
    return public(run, after)


# ---------- HTTP ----------
class H(BaseHTTPRequestHandler):
    server_version = "axor-workbench/" + VERSION

    def log_message(self, fmt, *args): sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    def reply(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data)))
        self.end_headers(); self.wfile.write(data)

    def allowed(self):
        ip = ipaddress.ip_address(self.client_address[0])
        if not any(ip in ipaddress.ip_network(n) for n in cfg["allow_from"]): return False
        return hmac.compare_digest(self.headers.get("X-Workbench-Token", ""), cfg["token"])

    def handle_any(self, method):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        parts = [p for p in u.path.split("/") if p]
        if parts == ["health"]: return self.reply(200, {"ok": True})
        if not self.allowed(): return self.reply(401, {"detail": "Not allowed."})
        body = {}
        if method == "POST":
            n = int(self.headers.get("Content-Length") or 0)
            if n > 2_000_000: return self.reply(413, {"detail": "Too big."})
            body = json.loads(self.rfile.read(n) or b"{}")
        try:
            if parts == ["info"]:
                v = subprocess.run([cfg["claude"], "--version"], capture_output=True, text=True, env=clean_env(), timeout=20).stdout.strip()
                busy = sum(1 for x in runs.values() if x["status"] == "running")
                return self.reply(200, {"version": VERSION, "features": FEATURES, "claude": v, "parallel": cfg["parallel"], "running": busy, "rate": last_rate,
                                        "mcp": [{"id": k, "label": m["label"], "note": m["note"], "kinds": m["kinds"]} for k, m in cfg["mcp"].items()],
                                        "max_budget_usd": cfg["max_budget_usd"], "repos": [repo_state(k, r) for k, r in cfg["repos"].items()]})
            if len(parts) >= 3 and parts[0] == "repos":
                r, what = repo_of(parts[1]), parts[2]
                if what == "tree": return self.reply(200, list_dir(r, q.get("path"), q.get("ref")))
                if what == "file": return self.reply(200, read_file(r, q.get("path"), q.get("ref")))
                if what == "diff": return self.reply(200, diff(r, q.get("base"), q.get("slug")))
                if what == "runs" and method == "POST": return self.reply(200, start(parts[1], body))
                if what == "merge" and method == "POST": return self.reply(200, merge(r, body.get("slug"), body.get("into") or "", str(body.get("expect") or "")))
                if what == "drop" and method == "POST": return self.reply(200, drop(r, body.get("slug")))
            if len(parts) == 2 and parts[0] == "runs": return self.reply(200, get_run(parts[1], int(q.get("after") or 0)))
            if len(parts) == 3 and parts[0] == "runs" and parts[2] == "stop" and method == "POST": return self.reply(200, stop(parts[1]))
            return self.reply(404, {"detail": "Not found."})
        except Fail as e:
            return self.reply(e.code, {"detail": str(e)})
        except subprocess.TimeoutExpired:
            return self.reply(504, {"detail": "git took too long."})
        except Exception as e:  # noqa: BLE001
            return self.reply(500, {"detail": f"Workbench error: {e}"[:400]})

    def do_GET(self): self.handle_any("GET")
    def do_POST(self): self.handle_any("POST")


def main():
    load_config()
    srv, tries = None, 0
    while srv is None:  # cni0 comes up with k3s: wait for the address
        try: srv = ThreadingHTTPServer((cfg["listen"], int(cfg["port"])), H)
        except OSError as e:
            tries += 1
            if tries > 60: raise
            sys.stderr.write(f"waiting for {cfg['listen']}: {e}\n"); time.sleep(5)
    sys.stderr.write(f"AXoR Workbench on {cfg['listen']}:{cfg['port']}, repos: {', '.join(cfg['repos'])}\n")
    srv.serve_forever()


if __name__ == "__main__":
    main()
