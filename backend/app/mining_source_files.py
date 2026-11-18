"""The file manager's GitHub side (mining_files.py, mining-files.js): the Source hub's repositories as a third place beside a
competition team's files and My workspace (AXoR Drive), copied either way.

- Browsing uses the Source hub's own routes (/api/source/repos/.../branches and /contents), so everyone signed in sees the
  hub's repositories, as in the Source view.
- From a repository into My workspace or into a team: the picked files and folders at a branch, read through the git tree and
  blob API (up to SOURCE_FILE_BYTES each, so not only the contents API's 1 MB), keeping their subfolders below the folder
  they were picked in. Onto the drive: into its open folder (at a drive's top: GitHub › <owner>-<name>), a new version when the
  name is taken. Into a team: text files only, asking before replacing a file, as from the drive.
- Into a repository: the picked drive or team files as one commit on an existing branch, into the folder open in the GitHub
  pane, with the message the user wrote. Administrators only: the Source hub's tokens are theirs. Every commit is audited.
- Files that look like secrets (the Source hub's SECRET pattern: .env files, keys, wallets) are never copied, either way.
"""
import base64, logging, re, time, urllib.parse

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .drive import DriveError
from .mining_files import MAX_COPY, NID, Files, _safe
from .mining_work import FILE_BYTES, _path
from .source import NAME, REF, SECRET, GitHubError

log = logging.getLogger("mining.source_files")
SOURCE_FILE_BYTES = 10 * 2**20    # the most one file copied to or from GitHub holds
COMMIT_BYTES = 40 * 2**20         # and one commit
GITHUB_FOLDER = "GitHub"          # at a drive's top, repositories land in GitHub › <owner>-<name>
PART = re.compile(r"^[^/\x00]{1,200}$")


class FromSourceIn(BaseModel):
    repo: str = Field(min_length=3, max_length=140)
    ref: str = Field(min_length=1, max_length=250)
    paths: list[str] = Field(min_length=1, max_length=300)
    base: str = Field("", max_length=400)    # the repository folder the paths were picked in: subfolders are kept below it

class SourceToDriveIn(FromSourceIn):
    space: str = Field("mine", pattern="^(mine|shared)$")
    folder: str | None = Field(None, max_length=32)

class SourceToTeamIn(FromSourceIn):
    folder: str = Field("", max_length=400)
    replace: bool = False

class CommitIn(BaseModel):
    repo: str = Field(min_length=3, max_length=140)
    branch: str = Field(min_length=1, max_length=250)
    folder: str = Field("", max_length=400)  # the repository folder open in the GitHub pane
    message: str = Field(min_length=1, max_length=2000)

class DriveCommitIn(CommitIn):
    ids: list[str] = Field(min_length=1, max_length=MAX_COPY)

class TeamCommitIn(CommitIn):
    paths: list[str] = Field(min_length=1, max_length=300)
    base: str = Field("", max_length=400)


def _repo_path(p, what="path"):
    """A path inside a repository: names split by /, no empty, . or .. names, nothing under .git."""
    parts = [x for x in (p or "").strip().strip("/").split("/")] if (p or "").strip().strip("/") else []
    if any(not PART.match(x) or x in (".", "..") or x.strip() != x for x in parts) or (parts and parts[0].lower() == ".git"):
        raise HTTPException(422, f"That isn't a {what} in a repository.")
    return "/".join(parts)


class SourceFiles:
    def __init__(self, work, drive, ip):
        self.w, self.db, self.drive, self.ip = work, work.db, drive, ip
        self.files = Files(work, drive)

    def _src(self):
        src = self.w.m.hub.source if self.w.m.hub else None
        if not src or not src.configured(): raise HTTPException(503, "GitHub isn't connected: an administrator connects it in the Source view.")
        return src

    def _repo(self, repo):
        owner, _, name = repo.strip().partition("/")
        if not NAME.match(owner or "") or not NAME.match(name or ""): raise HTTPException(422, "The repository is owner/name.")
        return self._src().allowed(owner, name)

    def _gh(self, method, path, body=None, params=None):
        try: return self._src().call(method, path, body, params=params).get("data")
        except GitHubError as e: raise HTTPException(e.status, str(e))

    def view(self, me):
        src = self.w.m.hub.source if self.w.m.hub else None
        ok = bool(src and src.configured())
        return {"configured": ok, "repos": src.repos() if ok else [], "can_write": ok and me["role"] == "admin",
                "drive": bool(self.drive and self.drive.enabled)}

    # ---------- out of a repository ----------
    def _picked(self, b: FromSourceIn):
        """[(blob entry, path below the folder picked in)] for the picked files and folders at the branch, and those skipped."""
        repo = self._repo(b.repo)
        if not REF.match(b.ref): raise HTTPException(422, "That isn't a branch name.")
        base = _repo_path(b.base, "folder")
        picks = [_repo_path(p) for p in b.paths]
        t = self._gh("GET", f"/repos/{repo}/git/trees/{urllib.parse.quote(b.ref, safe='')}", params={"recursive": "1"}) or {}
        tree = t.get("tree") or []
        out, skipped, seen = [], [], set()
        for p in picks:
            hit = [e for e in tree if e["type"] == "blob" and (e["path"] == p or e["path"].startswith(p + "/"))]
            if not hit:
                if any(e["type"] == "commit" and e["path"] == p for e in tree): skipped.append({"name": p, "error": "a submodule: open it on GitHub"}); continue
                raise HTTPException(404, f"{p} isn't on {b.ref}" + (" (the repository is too big to list in one go)" if t.get("truncated") else "") + ".")
            for e in hit:
                if e["path"] in seen: continue
                seen.add(e["path"])
                rel = e["path"][len(base) + 1:] if base and e["path"].startswith(base + "/") else e["path"]
                if SECRET.search(e["path"]): skipped.append({"name": e["path"], "error": "looks like a secret (keys, .env files, wallets): it stays on GitHub"})
                elif e.get("mode") == "120000": skipped.append({"name": e["path"], "error": "a symbolic link"})
                elif (e.get("size") or 0) > SOURCE_FILE_BYTES: skipped.append({"name": e["path"], "error": f"over {SOURCE_FILE_BYTES // 2**20} MB"})
                else: out.append((e, rel))
        if len(out) > MAX_COPY: raise HTTPException(422, f"That's more than {MAX_COPY} files: copy fewer at a time.")
        return repo, out, skipped

    def _blob(self, repo, sha):
        d = self._gh("GET", f"/repos/{repo}/git/blobs/{sha}") or {}
        if d.get("encoding") != "base64": raise LookupError("GitHub didn't send the file's content")
        return base64.b64decode(d.get("content") or "")

    def to_drive(self, me, b: SourceToDriveIn):
        if b.folder and not NID.match(b.folder): raise HTTPException(404, "That folder doesn't exist.")
        repo, items, skipped = self._picked(b)
        done = [{"path": s["name"], "error": s["error"]} for s in skipped]
        top = [] if b.folder else [GITHUB_FOLDER, repo.replace("/", "-")]
        dirs, d = {}, self.files._drive()
        try:
            if not b.folder: dirs[()] = d.call("POST", "/v1/folders/ensure", me, body={"space": b.space, "parent": None, "path": top})["id"]
            for e, rel in items:
                *sub, name = rel.split("/")
                key = tuple(sub)
                if key not in dirs:
                    dirs[key] = (d.call("POST", "/v1/folders/ensure", me, body={"space": b.space, "parent": dirs.get(()) or b.folder, "path": list(sub)})["id"]
                                 if sub else dirs.get(()) or b.folder)
                try:
                    data = self._blob(repo, e["sha"])
                    x = d.call("PUT", "/v1/files", me, {"space": b.space, "parent": dirs[key], "name": name, "conflict": "version"},
                               None, {"Content-Type": "application/octet-stream", "Content-Length": str(len(data))}, data, 120)
                    done.append({"path": e["path"], "ok": True, "new_version": bool(x.get("new_version"))})
                except (DriveError, LookupError) as x: done.append({"path": e["path"], "error": str(x)})
                except HTTPException as x: done.append({"path": e["path"], "error": str(x.detail)})
        except DriveError as e: raise HTTPException(e.status, str(e))
        n = sum(1 for x in done if x.get("ok"))
        return {"results": done, "copied": n, "where": {"space": b.space, "folder": dirs.get(()) or b.folder, "path": top}}

    def to_team(self, me, wid, b: SourceToTeamIn):
        self.w._own(me, wid)
        try: folder = _path(b.folder) if b.folder.strip() else ""
        except LookupError as e: raise HTTPException(422, str(e))
        repo, items, skipped = self._picked(b)
        have = {r["path"] for r in self.db.q("SELECT path FROM mw_files WHERE comp_id=?", (wid,))}
        done, conflicts = [{"name": s["name"], "error": s["error"]} for s in skipped], []
        for e, rel in items:
            path = "/".join(([folder] if folder else []) + [_safe(p) for p in rel.split("/")])
            res = {"name": e["path"], "path": path}
            try: path = _path(path)
            except LookupError as x: done.append({**res, "error": str(x)}); continue
            if (e.get("size") or 0) > FILE_BYTES: done.append({**res, "error": f"over {FILE_BYTES // 1000} kB, the most a team file holds"}); continue
            if path in have and not b.replace: conflicts.append(path); done.append({**res, "error": "the team has a file there", "conflict": True}); continue
            try: raw = self._blob(repo, e["sha"])
            except (LookupError, HTTPException) as x: done.append({**res, "error": str(getattr(x, "detail", x))}); continue
            try: text = raw.decode("utf-8")
            except UnicodeDecodeError: text = None
            if text is None or "\x00" in text: done.append({**res, "error": "not a text file (team files hold text only)"}); continue
            try: self.w._write_file(wid, path, text)
            except LookupError as x: done.append({**res, "error": str(x)}); continue
            done.append({**res, "ok": True, "replaced": path in have}); have.add(path)
        n = sum(1 for x in done if x.get("ok"))
        if n: self.w._event(wid, "file", f"{me['username']} copied {n} file{'s' if n != 1 else ''} from {repo} ({b.ref}) into {folder or 'the top folder'}")
        return {"results": done, "copied": n, "conflicts": conflicts, "team": self.files.team(me, wid)}

    # ---------- into a repository ----------
    def _commit(self, me, b: CommitIn, files, req, origin):
        """files: [(path below the open folder, bytes)] as one commit on the branch; secrets and oversize files are left out."""
        if me["role"] != "admin": raise HTTPException(403, "Only administrators commit to the Source hub's repositories: its GitHub tokens are theirs.")
        repo = self._repo(b.repo)
        if not REF.match(b.branch): raise HTTPException(422, "That isn't a branch name.")
        folder = _repo_path(b.folder, "folder")
        msg = b.message.strip()
        if not msg: raise HTTPException(422, "Write a commit message.")
        done, put, total = [], {}, 0
        for rel, data in files:
            try: path = _repo_path("/".join(x for x in [folder, rel] if x))
            except HTTPException as e: done.append({"path": rel, "error": e.detail}); continue
            if SECRET.search(path): done.append({"path": path, "error": "looks like a secret (keys, .env files, wallets): not committed"}); continue
            if len(data) > SOURCE_FILE_BYTES: done.append({"path": path, "error": f"over {SOURCE_FILE_BYTES // 2**20} MB"}); continue
            total += len(data)
            if total > COMMIT_BYTES: done.append({"path": path, "error": f"the commit would pass {COMMIT_BYTES // 2**20} MB: commit the rest separately"}); continue
            put[path] = data
        if not put: return {"results": done, "committed": 0, "commit": None}
        q = urllib.parse.quote(b.branch, safe="/")
        try:
            head = self._gh("GET", f"/repos/{repo}/git/ref/heads/{q}")["object"]["sha"]
            base_tree = self._gh("GET", f"/repos/{repo}/git/commits/{head}")["tree"]["sha"]
            entries = [{"path": p, "mode": "100644", "type": "blob",
                        "sha": self._gh("POST", f"/repos/{repo}/git/blobs", {"content": base64.b64encode(data).decode(), "encoding": "base64"})["sha"]}
                       for p, data in put.items()]
            tree = self._gh("POST", f"/repos/{repo}/git/trees", {"base_tree": base_tree, "tree": entries})["sha"]
            c = self._gh("POST", f"/repos/{repo}/git/commits", {"message": msg, "tree": tree, "parents": [head]})
            self._gh("PATCH", f"/repos/{repo}/git/refs/heads/{q}", {"sha": c["sha"], "force": False})
        except HTTPException as e:
            if e.status_code in (403, 404):
                raise HTTPException(e.status_code, f"The token can't write to {repo}: give it Contents read and write (fine-grained) or the repo scope (classic)."
                                                   if e.status_code == 403 else f"{b.branch} isn't a branch of {repo}, or the token can't see it.")
            raise
        self._src().forget(repo)
        done += [{"path": p, "ok": True} for p in put]
        self.db.log("source.commit", me["username"], repo, self.ip(req), f"{b.branch} {c['sha'][:7]}: {len(put)} files from {origin}")
        web = self.w.m._web(repo)
        return {"results": done, "committed": len(put), "commit": {"sha": c["sha"], "url": c.get("html_url") or f"{web}/commit/{c['sha']}"}}

    def drive_to_source(self, me, b: DriveCommitIn, req):
        if me["role"] != "admin": raise HTTPException(403, "Only administrators commit to the Source hub's repositories: its GitHub tokens are theirs.")
        if any(not NID.match(i) for i in b.ids): raise HTTPException(404, "That file doesn't exist.")
        items, files, bad = [], [], []
        try:
            for i in b.ids: self.files._walk(me, i, [], items)
        except DriveError as e: raise HTTPException(e.status, str(e))
        if len(items) > MAX_COPY: raise HTTPException(422, f"That's more than {MAX_COPY} files: commit fewer at a time.")
        d = self.files._drive()
        for n, parts in items:
            rel = "/".join(parts)
            if n["size"] > SOURCE_FILE_BYTES: bad.append({"path": rel, "error": f"over {SOURCE_FILE_BYTES // 2**20} MB"}); continue
            try:
                with d._open(d._req("GET", f"/v1/nodes/{n['id']}/content", me), timeout=120) as r: files.append((rel, r.read(SOURCE_FILE_BYTES + 1)))
            except DriveError as e: bad.append({"path": rel, "error": str(e)})
        r = self._commit(me, b, files, req, "My workspace")
        return {**r, "results": bad + r["results"]}

    def team_to_source(self, me, wid, b: TeamCommitIn, req):
        if me["role"] != "admin": raise HTTPException(403, "Only administrators commit to the Source hub's repositories: its GitHub tokens are theirs.")
        w, _ = self.w._own(me, wid)
        try: base = _path(b.base) if b.base.strip() else ""
        except LookupError as e: raise HTTPException(422, str(e))
        rows = self.files._picked(wid, b.paths)
        if len(rows) > MAX_COPY: raise HTTPException(422, f"That's more than {MAX_COPY} files: commit fewer at a time.")
        files = [(r["path"][len(base) + 1:] if base and r["path"].startswith(base + "/") else r["path"], (r["content"] or "").encode()) for r in rows]
        r = self._commit(me, b, files, req, self.w._label(w))
        if r["committed"]: self.w._event(wid, "file", f"{me['username']} committed {r['committed']} file{'s' if r['committed'] != 1 else ''} to {b.repo} ({b.branch})")
        return r


def build(work, drive, require, ip):
    r = APIRouter(prefix="/api/mining/files/source")
    gate = work.m.hub.gate if work.m.hub else (lambda me: me)
    user = lambda req: gate(require(req))
    s = SourceFiles(work, drive, ip)

    @r.get("")
    def view(req: Request): return s.view(user(req))

    @r.post("/to-drive")
    def to_drive(b: SourceToDriveIn, req: Request): return s.to_drive(user(req), b)

    @r.post("/to-team/{wid}")
    def to_team(wid: int, b: SourceToTeamIn, req: Request): return s.to_team(user(req), wid, b)

    @r.post("/from-drive")
    def from_drive(b: DriveCommitIn, req: Request): return s.drive_to_source(user(req), b, req)

    @r.post("/from-team/{wid}")
    def from_team(wid: int, b: TeamCommitIn, req: Request): return s.team_to_source(user(req), wid, b, req)

    return r
