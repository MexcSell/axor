"""Competition teams ⇄ My workspace: one file manager for a team's files (mw_files, mining_work.py) and the user's AXoR Drive
(the files of My workspace, drive.py). The page shows both side by side, in Competition teams (Files & sandbox) and in My
workspace (Files); this module adds what the two stores don't do on their own:

- Moving and renaming a team file or a whole folder (folders are only path prefixes in mw_files), and deleting several at once.
- Copying Drive files and folders into a team's folder. Team files hold text only, so the drive's raw content is decoded as
  UTF-8 and anything binary or over a team file's size is skipped with the reason; a file the team already has is replaced
  only when asked. Drive names become team paths (letters, digits, . _ - @ +).
- Copying team files and folders to the drive, keeping their subfolders, into the folder open in the Drive pane (at a space's
  root: <space> › Competition teams › <team>). A file the folder already has gets a new version, so nothing is lost. Each copy
  is tagged with the team's subnet, which shows it with that subnet in My workspace.

Browsing the drive, uploads, previews and team file edits use the existing routes (/api/drive/*, /api/mining/work/files).
"""
import re, time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .drive import DriveError
from .mining_work import FILE_BYTES, FILES_BYTES, MAX_FILES, _path

MAX_COPY = 50                    # files one copy moves, either way
TEAMS_FOLDER = "Competition teams"
NID = re.compile(r"^[0-9a-f]{32}$")


class MoveIn(BaseModel):
    src: str = Field(min_length=1, max_length=400)
    dst: str = Field(min_length=1, max_length=400)

class PathsIn(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=300)

class FromDriveIn(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=MAX_COPY)
    folder: str = Field("", max_length=400)  # the team folder to copy into ("" is the top)
    replace: bool = False

class ToDriveIn(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=300)
    base: str = Field("", max_length=400)    # the team folder the paths were picked in: subfolders are kept below it
    space: str = Field("mine", pattern="^(mine|shared)$")
    folder: str | None = Field(None, max_length=32)


def _safe(name):
    """A drive name as one part of a team path."""
    s = re.sub(r"-{2,}", "-", re.sub(r"[^A-Za-z0-9._@+-]", "-", (name or "").strip())).strip("-")[:80]
    return s if s and s not in (".", "..") else "file"


class Files:
    def __init__(self, work, drive):
        self.w, self.db, self.drive = work, work.db, drive

    def _drive(self):
        if not self.drive or not self.drive.enabled: raise HTTPException(404, "File storage isn't available on this server.")
        return self.drive

    def _call(self, *a, **k):
        try: return self._drive().call(*a, **k)
        except DriveError as e: raise HTTPException(e.status, str(e))

    def _picked(self, wid, paths):
        """The team files the picked paths stand for: a file itself, or every file in a folder."""
        rows = self.db.q("SELECT id, path, size, content FROM mw_files WHERE comp_id=? ORDER BY path", (wid,))
        out, seen = [], set()
        for p in paths:
            try: p = _path(p)
            except LookupError as e: raise HTTPException(422, str(e))
            hit = [r for r in rows if r["path"] == p or r["path"].startswith(p + "/")]
            if not hit: raise HTTPException(404, f"The team has no file or folder {p}.")
            out += [r for r in hit if r["id"] not in seen]; seen.update(r["id"] for r in hit)
        return out

    # ---------- the teams and their files ----------
    def teams(self, me):
        """Every competition team of the user's, with how full its files are (My workspace's team picker)."""
        out = []
        for c in self.db.q("SELECT id, netuid FROM mh_campaigns WHERE user_id=? ORDER BY netuid, id", (me["id"],)):
            camp = self.w.m._campaign(c["id"])
            for w in self.db.q("""SELECT w.*, (SELECT COUNT(*) FROM mw_files f WHERE f.comp_id=w.id) nfiles,
                                         (SELECT COALESCE(SUM(size),0) FROM mw_files f WHERE f.comp_id=w.id) nbytes
                                  FROM mw_comps w WHERE w.campaign_id=? ORDER BY w.status='closed', w.number DESC, w.id DESC""", (c["id"],)):
                out.append({"id": w["id"], "label": self.w._label(w), "number": w["number"], "status": w["status"], "netuid": c["netuid"],
                            "subnet": self.w.m._name(camp), "files": w["nfiles"], "bytes": w["nbytes"]})
        return {"teams": out, "drive": bool(self.drive and self.drive.enabled)}

    def team(self, me, wid):
        w, c = self.w._own(me, wid)
        files = self.db.q("""SELECT f.id, f.path, f.size, f.updated, f.agent_id agent, a.name author FROM mw_files f
                             LEFT JOIN mw_agents a ON a.id=f.agent_id WHERE f.comp_id=? ORDER BY f.path""", (wid,))
        return {"comp": {"id": w["id"], "label": self.w._label(w), "netuid": c["netuid"]}, "files": files,
                "limits": {"files": MAX_FILES, "file_bytes": FILE_BYTES, "files_bytes": FILES_BYTES}}

    def move(self, me, wid, b: MoveIn):
        self.w._own(me, wid)
        try: src, dst = _path(b.src), _path(b.dst)
        except LookupError as e: raise HTTPException(422, str(e))
        if src == dst: return self.team(me, wid)
        if dst.startswith(src + "/"): raise HTTPException(422, f"{src} can't move into itself.")
        with self.w.lock:
            rows = self.db.q("SELECT id, path FROM mw_files WHERE comp_id=?", (wid,))
            moving = [r for r in rows if r["path"] == src or r["path"].startswith(src + "/")]
            if not moving: raise HTTPException(404, f"The team has no file or folder {src}.")
            stay = {r["path"] for r in rows} - {r["path"] for r in moving}
            new = {r["id"]: dst + r["path"][len(src):] for r in moving}
            # taken: the same path, a folder of that name, or a file where the path needs a folder
            clash = sorted(p for p in new.values() if p in stay or any(s.startswith(p + "/") or p.startswith(s + "/") for s in stay))
            if clash: raise HTTPException(409, f"{clash[0]} is taken: rename or delete that first.")
            for fid, p in new.items(): self.db.q("UPDATE mw_files SET path=?, updated=? WHERE id=?", (p, time.time(), fid))
        self.w._event(wid, "file", f"{me['username']} moved {src} to {dst}" + (f" ({len(moving)} files)" if len(moving) > 1 else ""))
        return self.team(me, wid)

    def delete(self, me, wid, b: PathsIn):
        self.w._own(me, wid)
        rows = self._picked(wid, b.paths)
        for r in rows: self.db.q("DELETE FROM mw_files WHERE id=?", (r["id"],))
        self.w._event(wid, "file", f"{me['username']} deleted " + (rows[0]["path"] if len(rows) == 1 else f"{len(rows)} files"))
        return self.team(me, wid)

    # ---------- the drive into the team ----------
    def _walk(self, me, nid, rel, out):
        """A drive file or folder as (node, path below the picked item), folders followed down."""
        n = self._call("GET", f"/v1/nodes/{nid}", me)
        if n["kind"] == "file": out.append((n, rel + [n["name"]]))
        else:
            for x in self._call("GET", "/v1/list", me, {"space": n["space"], "folder_id": n["id"]})["items"]:
                if len(out) > MAX_COPY: break
                if x["kind"] == "file": out.append((x, rel + [n["name"], x["name"]]))
                else: self._walk(me, x["id"], rel + [n["name"]], out)
        return out

    def _bytes(self, me, nid):
        with self._drive()._open(self._drive()._req("GET", f"/v1/nodes/{nid}/content", me), timeout=60) as r:
            return r.read(FILE_BYTES + 1)

    def from_drive(self, me, wid, b: FromDriveIn):
        self.w._own(me, wid)
        try: folder = _path(b.folder) if b.folder.strip() else ""
        except LookupError as e: raise HTTPException(422, str(e))
        if any(not NID.match(i) for i in b.ids): raise HTTPException(404, "That file doesn't exist.")
        items = []
        try:
            for i in b.ids: self._walk(me, i, [], items)
        except DriveError as e: raise HTTPException(e.status, str(e))
        if len(items) > MAX_COPY: raise HTTPException(422, f"That's more than {MAX_COPY} files: copy fewer at a time.")
        have = {r["path"] for r in self.db.q("SELECT path FROM mw_files WHERE comp_id=?", (wid,))}
        done, conflicts = [], []
        for n, parts in items:
            path = "/".join(([folder] if folder else []) + [_safe(p) for p in parts])
            res = {"name": "/".join(parts), "path": path}
            try: path = _path(path)
            except LookupError as e: done.append({**res, "error": str(e)}); continue
            if n["size"] > FILE_BYTES: done.append({**res, "error": f"over {FILE_BYTES // 1000} kB, the most a team file holds"}); continue
            if path in have and not b.replace: conflicts.append(path); done.append({**res, "error": "the team has a file there", "conflict": True}); continue
            try: raw = self._bytes(me, n["id"])
            except DriveError as e: done.append({**res, "error": str(e)}); continue
            try: text = raw.decode("utf-8")
            except UnicodeDecodeError: text = None
            if text is None or "\x00" in text: done.append({**res, "error": "not a text file (team files hold text only)"}); continue
            try: self.w._write_file(wid, path, text)
            except LookupError as e: done.append({**res, "error": str(e)}); continue
            done.append({**res, "ok": True, "replaced": path in have}); have.add(path)
        n_ok = sum(1 for x in done if x.get("ok"))
        if n_ok: self.w._event(wid, "file", f"{me['username']} copied {n_ok} file{'s' if n_ok != 1 else ''} from My workspace into {folder or 'the top folder'}")
        return {"results": done, "copied": n_ok, "conflicts": conflicts, "team": self.team(me, wid)}

    # ---------- the team onto the drive ----------
    def to_drive(self, me, wid, b: ToDriveIn):
        w, c = self.w._own(me, wid)
        if b.folder and not NID.match(b.folder): raise HTTPException(404, "That folder doesn't exist.")
        try: base = _path(b.base) if b.base.strip() else ""
        except LookupError as e: raise HTTPException(422, str(e))
        rows = self._picked(wid, b.paths)
        if len(rows) > MAX_COPY: raise HTTPException(422, f"That's more than {MAX_COPY} files: copy fewer at a time.")
        label = self.w._label(w)
        top = [] if b.folder else [TEAMS_FOLDER, label]  # at a space's root, a folder of its own
        dirs, done = {}, []
        try:
            if not b.folder:
                dirs[()] = self._drive().call("POST", "/v1/folders/ensure", me, body={"space": b.space, "parent": None, "path": top})["id"]
            for r in rows:
                rel = r["path"][len(base) + 1:] if base and r["path"].startswith(base + "/") else r["path"]
                *sub, name = rel.split("/")
                key = tuple(sub)
                if key not in dirs:
                    dirs[key] = (self._drive().call("POST", "/v1/folders/ensure", me, body={"space": b.space, "parent": dirs.get(()) or b.folder, "path": list(sub)})["id"]
                                 if sub else dirs.get(()) or b.folder)
                data = (r["content"] or "").encode()
                try:
                    x = self._drive().call("PUT", "/v1/files", me, {"space": b.space, "parent": dirs[key], "name": name, "netuid": c["netuid"], "conflict": "version"},
                                           None, {"Content-Type": "application/octet-stream", "Content-Length": str(len(data))}, data, 120)
                    done.append({"path": r["path"], "ok": True, "name": "/".join(top + list(sub) + [name]), "new_version": bool(x.get("new_version"))})
                except DriveError as e: done.append({"path": r["path"], "error": str(e)})
        except DriveError as e: raise HTTPException(e.status, str(e))
        n_ok = sum(1 for x in done if x.get("ok"))
        if n_ok: self.w._event(wid, "file", f"{me['username']} copied {n_ok} file{'s' if n_ok != 1 else ''} to My workspace")
        return {"results": done, "copied": n_ok, "where": {"space": b.space, "folder": dirs.get(()) or b.folder, "path": top}}


def build(work, drive, require):
    r = APIRouter(prefix="/api/mining/files")
    gate = work.m.hub.gate if work.m.hub else (lambda me: me)
    user = lambda req: gate(require(req))
    f = Files(work, drive)
    r.state = {"files": f}

    @r.get("/teams")
    def teams(req: Request): return f.teams(user(req))

    @r.get("/teams/{wid}")
    def team(wid: int, req: Request): return f.team(user(req), wid)

    @r.post("/teams/{wid}/move")
    def move(wid: int, b: MoveIn, req: Request): return f.move(user(req), wid, b)

    @r.post("/teams/{wid}/delete")
    def delete(wid: int, b: PathsIn, req: Request): return f.delete(user(req), wid, b)

    @r.post("/teams/{wid}/from-drive")
    def from_drive(wid: int, b: FromDriveIn, req: Request): return f.from_drive(user(req), wid, b)

    @r.post("/teams/{wid}/to-drive")
    def to_drive(wid: int, b: ToDriveIn, req: Request): return f.to_drive(user(req), wid, b)

    return r
