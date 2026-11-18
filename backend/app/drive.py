"""Drive: AXoR's side of AXoR Drive, the separate file server in drive/.

AXoR reaches the drive at DRIVE_URL over the internal network with a shared secret (DRIVE_SECRET, or the file
DRIVE_SECRET_FILE that the drive writes on first start) and tells it which signed-in user is acting. Browsers only
ever talk to AXoR: /api/drive/* proxies the drive for signed-in users, streaming uploads and downloads (with
Range, so videos seek; folders and selections as zips), and /s/<token> is the public page for share links. Sharing
with people names an account by username or email, resolved here. Admins can stop members from creating share
links. The workspace file panel and agent attachments use the drive too (see workspace.py).
"""
import asyncio, html, json, logging, os, re, tempfile, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from .secretbox import fingerprint

log = logging.getLogger("drive")
URL = (os.getenv("DRIVE_URL") or "").rstrip("/")
PASS = ("content-type", "content-length", "content-range", "accept-ranges", "content-disposition", "last-modified", "etag")
# drive content is shown in the page (images, PDFs, video in frames): same-origin framing only, no scripts.
# PDFs get framing rules only: Chrome's built-in viewer is itself an embedded plugin that default-src 'none' blocks.
CONTENT_CSP = "default-src 'none'; img-src 'self'; media-src 'self'; style-src 'unsafe-inline'; frame-ancestors 'self'"
PDF_CSP = "frame-ancestors 'self'"

class DriveError(Exception):
    def __init__(self, msg, status=502):
        super().__init__(msg); self.status = status

class Drive:
    def __init__(self, url=URL):
        self.url = url
        self._secret = None

    def secret(self):
        if self._secret is None:
            s = os.getenv("DRIVE_SECRET")
            if not s and os.getenv("DRIVE_SECRET_FILE"):
                try: s = Path(os.getenv("DRIVE_SECRET_FILE")).read_text().strip()
                except OSError: s = None  # the drive hasn't written it yet: try again next call
            self._secret = s
        return self._secret

    @property
    def enabled(self): return bool(self.url)

    def _req(self, method, path, me=None, params=None, body=None, headers=None, data=None):
        if not self.url: raise DriveError("File storage isn't set up on this server (DRIVE_URL).", 503)
        if not self.secret(): raise DriveError("AXoR can't read the drive's secret yet (DRIVE_SECRET / DRIVE_SECRET_FILE).", 503)
        q = "?" + urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None}) if params else ""
        h = {"Authorization": f"Bearer {self.secret()}", **(headers or {})}
        if me: h.update({"X-Drive-User": str(me["id"]), "X-Drive-Name": urllib.parse.quote(me["username"]), "X-Drive-Admin": "1" if me.get("role") == "admin" else "0"})
        if body is not None: data, h["Content-Type"] = json.dumps(body).encode(), "application/json"
        return urllib.request.Request(self.url + path + q, data=data, headers=h, method=method)

    def _open(self, req, timeout=60):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            try: detail = json.load(e).get("detail")
            except ValueError: detail = None
            if e.code == 401: self._secret = None  # the drive may have a new secret
            raise DriveError(detail if isinstance(detail, str) else f"The drive answered HTTP {e.code}.", e.code if e.code < 500 else 502)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise DriveError(f"The drive server isn't reachable ({getattr(e, 'reason', e)}).", 503)

    def call(self, method, path, me=None, params=None, body=None, headers=None, data=None, timeout=60):
        with self._open(self._req(method, path, me, params, body, headers, data), timeout) as r:
            raw = r.read()
        return json.loads(raw) if raw else None

    def stream(self, path, me=None, params=None, headers=None, filename=None):
        """A drive download as a streaming response, passing Range through."""
        r = self._open(self._req("GET", path, me, params, headers=headers), timeout=120)
        def body():
            try:
                while chunk := r.read(256 * 1024): yield chunk
            finally: r.close()
        h = {k: v for k, v in r.headers.items() if k.lower() in PASS}
        h["Content-Security-Policy"] = PDF_CSP if r.headers.get("content-type", "").startswith("application/pdf") else CONTENT_CSP
        h["X-Frame-Options"] = "SAMEORIGIN"
        return StreamingResponse(body(), status_code=r.status, headers=h)

    async def upload(self, me, req: Request, params, extra_headers=None, path="/v1/files"):
        """Spool the browser's upload (to disk past 8 MB), then hand it to the drive with a known length: a new file,
        or (path /v1/nodes/<id>/content) a new version of one."""
        limit = int(os.getenv("DRIVE_FILE_MB", "200")) * 2**20
        if int(req.headers.get("content-length") or 0) > limit: raise DriveError(f"Files can be up to {limit // 2**20} MB.", 413)
        spool, size = tempfile.SpooledTemporaryFile(max_size=8 * 2**20), 0
        try:
            async for chunk in req.stream():
                size += len(chunk)
                if size > limit: raise DriveError(f"Files can be up to {limit // 2**20} MB.", 413)
                spool.write(chunk)
            spool.seek(0)
            headers = {"Content-Length": str(size), "Content-Type": "application/octet-stream", **(extra_headers or {})}
            return await asyncio.to_thread(self.call, "PUT", path, me, params, None, headers, spool, 600)
        finally:
            spool.close()

    def text(self, me, nid):
        """(name, text or None, size) for an agent to read."""
        t = self.call("GET", f"/v1/nodes/{nid}/text", me)
        return t["name"], t["text"], t["size"]

class FolderIn(BaseModel):
    space: str | None = None
    parent: str | None = None
    name: str = Field(..., min_length=1, max_length=200)

class EnsureIn(BaseModel):
    space: str | None = None
    parent: str | None = None
    path: list[str] = Field(..., min_length=1, max_length=32)

class CopyIn(BaseModel):
    space: str | None = None
    parent: str | None = None

class StarIn(BaseModel):
    on: bool

class PersonIn(BaseModel):
    user: str = Field(..., min_length=1, max_length=200)  # username or email
    role: str = Field("viewer", pattern="^(viewer|editor)$")

class PatchIn(BaseModel):
    name: str | None = Field(None, max_length=200)
    space: str | None = None
    parent: str | None = None
    netuid: int | None = None

class ShareIn(BaseModel):
    days: int | None = Field(7, ge=1, le=365)
    password: str | None = Field(None, max_length=200)

class SettingsIn(BaseModel):
    links_for_members: bool

NID = re.compile(r"^[0-9a-f]{32}$")
TOKEN = re.compile(r"^[A-Za-z0-9_-]{20,64}$")

def build(db, require, admin, ip, drive: Drive):
    r = APIRouter(prefix="/api/drive")
    public = APIRouter()

    def call(*a, **k):
        try: return drive.call(*a, **k)
        except DriveError as e: raise HTTPException(e.status, str(e))

    def nid_ok(nid):
        if not NID.match(nid): raise HTTPException(404, "That file or folder doesn't exist.")
        return nid

    def links_allowed(me): return me["role"] == "admin" or db.setting("drive_links_members", "1") == "1"

    @r.get("/status")
    def status(req: Request):
        me = require(req)
        if not drive.enabled: return {"enabled": False, "error": "AXoR isn't connected to a drive server yet (DRIVE_URL isn't set).", "is_admin": me["role"] == "admin"}
        try: u = drive.call("GET", "/v1/usage", me)
        except DriveError as e: return {"enabled": True, "error": str(e), "is_admin": me["role"] == "admin"}
        return {"enabled": True, "error": None, **u, "is_admin": me["role"] == "admin", "links": links_allowed(me),
                "links_for_members": db.setting("drive_links_members", "1") == "1"}

    @r.get("/list")
    def list_folder(req: Request, space: str, folder: str | None = None):
        return call("GET", "/v1/list", require(req), {"space": space, "folder_id": folder and nid_ok(folder)})

    @r.get("/recent")
    def recent(req: Request):
        return call("GET", "/v1/recent", require(req))

    @r.get("/starred")
    def starred(req: Request):
        return call("GET", "/v1/starred", require(req))

    @r.get("/storage")
    def storage(req: Request):
        return call("GET", "/v1/storage", require(req))

    @r.get("/search")
    def search(req: Request, q: str):
        return call("GET", "/v1/search", require(req), {"q": q[:200]})

    @r.get("/trash")
    def trash(req: Request, space: str):
        return call("GET", "/v1/trash", require(req), {"space": space})

    @r.delete("/trash")
    def empty_trash(req: Request, space: str):
        me = require(req)
        out = call("DELETE", "/v1/trash", me, {"space": space})
        db.log("drive.empty_trash", me["username"], space, ip(req), f"{out.get('deleted', 0)} items")
        return out

    @r.post("/folders")
    def make_folder(b: FolderIn, req: Request):
        if b.parent: nid_ok(b.parent)
        return call("POST", "/v1/folders", require(req), body=b.model_dump())

    @r.post("/folders/ensure")
    def ensure(b: EnsureIn, req: Request):
        """A folder path under a folder, created as needed (folder uploads)."""
        if b.parent: nid_ok(b.parent)
        return call("POST", "/v1/folders/ensure", require(req), body=b.model_dump())

    @r.post("/files")
    async def upload(req: Request, name: str, space: str | None = None, parent: str | None = None, conflict: str = "version"):
        """The raw request body is the file (no multipart). conflict=keep keeps both files when the name is taken."""
        me = require(req)
        if conflict not in ("version", "keep"): raise HTTPException(400, "conflict is version or keep.")
        try: return await drive.upload(me, req, {"space": space, "name": name, "parent": parent and nid_ok(parent), "conflict": conflict})
        except DriveError as e: raise HTTPException(e.status, str(e))

    @r.get("/zip")
    def zip_download(req: Request, ids: str):
        """Files and folders as one zip, streamed."""
        me = require(req)
        picked = [nid_ok(i) for i in ids.split(",") if i]
        if not 0 < len(picked) <= 200: raise HTTPException(400, "Pick between 1 and 200 items to download.")
        try: return drive.stream("/v1/zip", me, {"ids": ",".join(picked)})
        except DriveError as e: raise HTTPException(e.status, str(e))

    @r.get("/nodes/{nid}")
    def details(nid: str, req: Request):
        return call("GET", f"/v1/nodes/{nid_ok(nid)}", require(req))

    @r.get("/nodes/{nid}/content")
    def content(nid: str, req: Request, version: str | None = None, download: bool = False):
        me = require(req)
        if version and not NID.match(version): raise HTTPException(404, "That version doesn't exist.")
        rng = req.headers.get("range")
        try: return drive.stream(f"/v1/nodes/{nid_ok(nid)}/content", me, {"version": version, "download": "true" if download else None},
                                 {"Range": rng} if rng else None)
        except DriveError as e: raise HTTPException(e.status, str(e))

    @r.put("/nodes/{nid}/content")
    async def write(nid: str, req: Request):
        """A new version of a file from the raw body: an edit (X-Drive-Edit), or an uploaded replacement. With
        X-Drive-Base-Version, the drive refuses it if someone saved another version since."""
        me = require(req)
        base, h = req.headers.get("x-drive-base-version"), {}
        if base: h["X-Drive-Base-Version"] = nid_ok(base)
        if req.headers.get("x-drive-edit"): h["X-Drive-Edit"] = "1"
        try: return await drive.upload(me, req, None, h, path=f"/v1/nodes/{nid_ok(nid)}/content")
        except DriveError as e: raise HTTPException(e.status, str(e))

    @r.get("/nodes/{nid}/text")
    def text(nid: str, req: Request):
        return call("GET", f"/v1/nodes/{nid_ok(nid)}/text", require(req))

    @r.get("/nodes/{nid}/thumb")
    def thumb(nid: str, req: Request):
        me = require(req)
        try: return drive.stream(f"/v1/nodes/{nid_ok(nid)}/thumb", me)
        except DriveError as e: raise HTTPException(e.status, str(e))

    @r.get("/nodes/{nid}/activity")
    def activity(nid: str, req: Request):
        return call("GET", f"/v1/nodes/{nid_ok(nid)}/activity", require(req))

    @r.put("/nodes/{nid}/star")
    def star(nid: str, b: StarIn, req: Request):
        return call("PUT", f"/v1/nodes/{nid_ok(nid)}/star", require(req), body=b.model_dump())

    @r.post("/nodes/{nid}/copy")
    def copy(nid: str, b: CopyIn, req: Request):
        if b.parent: nid_ok(b.parent)
        return call("POST", f"/v1/nodes/{nid_ok(nid)}/copy", require(req), body=b.model_dump(), timeout=300)

    @r.put("/nodes/{nid}/people")
    def share_with(nid: str, b: PersonIn, req: Request):
        """Share an item with an account, named by username or email, as viewer or editor."""
        me = require(req)
        u = db.find(b.user)
        if not u or u["disabled"]: raise HTTPException(404, f"No account named {b.user.strip()!r}.")
        out = call("PUT", f"/v1/nodes/{nid_ok(nid)}/people", me, body={"uid": u["id"], "name": u["username"], "role": b.role})
        db.log("drive.share_people", me["username"], nid, ip(req), f"{u['username']} as {b.role}")
        return out

    @r.delete("/nodes/{nid}/people/{uid}")
    def unshare(nid: str, uid: str, req: Request):
        """Stop sharing with someone (the owner), or, with uid "me", remove an item shared with you."""
        me = require(req)
        if uid != "me" and not uid.isdigit(): raise HTTPException(404, "That person doesn't have access.")
        uid = me["id"] if uid == "me" else int(uid)
        out = call("DELETE", f"/v1/nodes/{nid_ok(nid)}/people/{uid}", me)
        db.log("drive.unshare_people", me["username"], nid, ip(req), "left" if uid == me["id"] else f"user #{uid}")
        return out

    @r.patch("/nodes/{nid}")
    def patch(nid: str, b: PatchIn, req: Request):
        return call("PATCH", f"/v1/nodes/{nid_ok(nid)}", require(req), body=b.model_dump(exclude_none=True))

    @r.post("/nodes/{nid}/trash")
    def to_trash(nid: str, req: Request):
        return call("POST", f"/v1/nodes/{nid_ok(nid)}/trash", require(req))

    @r.post("/nodes/{nid}/restore")
    def restore(nid: str, req: Request):
        return call("POST", f"/v1/nodes/{nid_ok(nid)}/restore", require(req))

    @r.delete("/nodes/{nid}")
    def delete_forever(nid: str, req: Request):
        me = require(req)
        out = call("DELETE", f"/v1/nodes/{nid_ok(nid)}", me)
        db.log("drive.delete", me["username"], nid, ip(req), "deleted forever")
        return out

    @r.post("/nodes/{nid}/versions/{vid}/restore")
    def restore_version(nid: str, vid: str, req: Request):
        return call("POST", f"/v1/nodes/{nid_ok(nid)}/versions/{nid_ok(vid)}/restore", require(req))

    @r.post("/nodes/{nid}/shares")
    def share(nid: str, b: ShareIn, req: Request):
        me = require(req)
        if not links_allowed(me): raise HTTPException(403, "Only admins can create share links.")
        out = call("POST", f"/v1/nodes/{nid_ok(nid)}/shares", me, body=b.model_dump())
        db.log("drive.share", me["username"], nid, ip(req), f"{b.days or 'no'} day expiry{', password' if b.password else ''}")
        return {"token": out["token"], "url": f"/s/{out['token']}"}

    @r.get("/shares")
    def shares(req: Request, all: bool = False):
        return call("GET", "/v1/shares", require(req), {"all": "true" if all else None})

    @r.delete("/shares/{token}")
    def revoke(token: str, req: Request):
        me = require(req)
        if not TOKEN.match(token): raise HTTPException(404, "That link doesn't exist.")
        out = call("DELETE", f"/v1/shares/{token}", me)
        db.log("drive.share_revoked", me["username"], fingerprint(token), ip(req), "")  # D-019: never the link's characters
        return out

    @r.put("/settings")
    def settings(b: SettingsIn, req: Request):
        me = admin(req)
        db.setting("drive_links_members", v="1" if b.links_for_members else "0")
        db.log("drive.settings", me["username"], "", ip(req), f"links for members {'on' if b.links_for_members else 'off'}")
        return {"links_for_members": b.links_for_members}

    # ---------- public share links: /s/<token> ----------
    attempts = {}

    def page(title, body, status=200):
        return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>{html.escape(title)} · AXoR</title><link rel="icon" href="/static/brand/favicon.ico">
<style>:root{{color-scheme:light dark;--bg:#f6f6f4;--card:#fff;--line:#e2e2dd;--text:#121212;--muted:#6b6a66;--accent:#2a78d6;--crit:#c93434}}
@media (prefers-color-scheme:dark){{:root{{--bg:#111;--card:#1a1a19;--line:#2f2f2c;--text:#f0efec;--muted:#a3a29b;--accent:#5b9be6;--crit:#f07171}}}}
body{{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,sans-serif;padding:16px;box-sizing:border-box}}
main{{width:100%;max-width:420px;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:24px;display:grid;gap:14px}}
.brand{{display:flex;gap:10px;align-items:center;color:var(--muted);font-size:13px}}.brand img{{width:28px;height:28px}}
h1{{font-size:18px;margin:0;overflow-wrap:anywhere}}p{{margin:0;color:var(--muted);font-size:13.5px}}.err{{color:var(--crit)}}
input{{width:100%;box-sizing:border-box;padding:10px 12px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--text);font:inherit}}
button{{width:100%;padding:11px;border:0;border-radius:10px;background:var(--accent);color:#fff;font:inherit;font-weight:600;cursor:pointer}}
form{{display:grid;gap:10px;margin:0}}</style></head><body><main><div class="brand"><img src="/static/brand/icon-192.png" alt="">AXoR</div>{body}</main></body></html>""",
            status_code=status, headers={"Referrer-Policy": "no-referrer", "Cache-Control": "no-store"})

    def size(n):
        for u in ("bytes", "KB", "MB", "GB"):
            if n < 1024 or u == "GB": return f"{n:.0f} {u}" if u == "bytes" else f"{n:.1f} {u}"
            n /= 1024

    @public.get("/s/{token}", include_in_schema=False)
    def share_page(token: str, err: str | None = None):
        if not TOKEN.match(token): return page("Link not found", "<h1>This link has expired or was removed.</h1>", 404)
        try: m = drive.call("GET", f"/v1/public/{token}")
        except DriveError as e: return page("Link not found", f"<h1>{html.escape(str(e))}</h1>", e.status if e.status in (404, 503) else 502)
        exp = f" · expires {time.strftime('%b %d, %Y', time.gmtime(m['expires']))}" if m["expires"] else ""
        folder = m.get("kind") == "folder"
        what = f"Folder · {m['files']} file{'' if m['files'] == 1 else 's'} · {size(m['size'] or 0)}" if folder else size(m["size"] or 0)
        return page(m["name"], f"""<h1>{html.escape(m['name'])}</h1><p>{what} · shared by {html.escape(m['by'] or 'someone')}{exp}</p>
            <form method="post" action="/s/{token}">{'<input type="password" name="password" placeholder="Password" required autofocus aria-label="Password">' if m['password'] else ''}
            {'<p class="err">Wrong password. Try again.</p>' if err else ''}<button type="submit">{'Download as .zip' if folder else 'Download'}</button></form>""")

    @public.post("/s/{token}", include_in_schema=False)
    async def share_download(token: str, req: Request):
        if not TOKEN.match(token): return page("Link not found", "<h1>This link has expired or was removed.</h1>", 404)
        key, now = (ip(req), token), time.time()
        if len(attempts) > 5000: attempts.clear()
        recent = [t for t in attempts.get(key, []) if t > now - 600]
        if len(recent) >= 10: return page("Too many attempts", "<h1>Too many attempts</h1><p>Wait a few minutes and try again.</p>", 429)
        form = urllib.parse.parse_qs((await req.body())[:4096].decode("utf-8", "replace"))
        pw = (form.get("password") or [""])[0]
        try:
            return await asyncio.to_thread(drive.stream, f"/v1/public/{token}/content", None, None, {"X-Share-Password": urllib.parse.quote(pw)})
        except DriveError as e:
            if e.status == 403:
                attempts[key] = recent + [now]
                return share_page(token, err="1")
            return page("Link not found", f"<h1>{html.escape(str(e))}</h1>", e.status if e.status in (404, 503) else 502)

    r.state = {"drive": drive, "public": public}
    return r
