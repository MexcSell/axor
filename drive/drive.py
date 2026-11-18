"""AXoR Drive: a small self-hosted file server for AXoR, with what people expect from Google Drive, Dropbox or OneDrive.

It runs as its own service (own container, database and storage volume) and is only reached by the AXoR backend,
which authenticates with a shared secret and says which signed-in user is acting (X-Drive-User / -Name / -Admin).
The drive is never exposed to browsers directly: AXoR proxies every request, including public share links.

- Spaces: each user's private "My drive" (user:<id>) and the team's "Shared drive" (shared), with nested folders.
- Sharing with people: the owner of a My drive item can share it with other users as viewer or editor; sharing a
  folder shares everything in it. It shows under "Shared with me" for them.
- Files are stored content-addressed (blobs/<sha256>), so identical uploads and copies take the space once.
- Uploading a file with a name that already exists in a folder adds a version (or, asked to keep both, gets a
  numbered name); text files edited in the browser get a version too. The last DRIVE_VERSIONS are kept and any of
  them can be downloaded or restored.
- Stars, copies, zip downloads of folders and selections, image thumbnails and an activity log per item.
- Trash: deleting moves a file or folder (with its contents) to the trash, restorable for DRIVE_TRASH_DAYS days.
- Search by name and by text content (text, markdown, code, CSV, JSON, PDFs and Office files), with SQLite FTS5.
- Share links: expiring, optionally password-protected download links for files and folders (as a zip), revocable.
- Quota: DRIVE_QUOTA_MB per user, counting every stored version the user uploaded or copied; DRIVE_FILE_MB per file.

Permissions: My drive is its owner's alone, apart from what they share. In the Shared drive everyone can read,
upload (new files or new versions) and create folders; renaming, moving, deleting and restoring versions is for the
item's creator or an admin. Viewers of a shared item can open, download and copy it. Editors can also add and edit
files in it and rename, move or delete what's inside it; the shared item itself stays its owner's to rename, move,
delete or share.
Run: DRIVE_DATA=/data uvicorn drive:app --port 8100
"""
import hashlib, hmac, html, logging, mimetypes, os, re, secrets, sqlite3, threading, time, uuid, warnings, zipfile
from pathlib import Path
from urllib.parse import quote, unquote

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

try:  # thumbnails are optional: without Pillow, grids show file icons
    from PIL import Image, ImageOps
    Image.MAX_IMAGE_PIXELS = 120_000_000
    warnings.simplefilter("error", Image.DecompressionBombWarning)  # bigger images get no thumbnail
except ImportError:
    Image = None

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("drive")
DATA = Path(os.getenv("DRIVE_DATA", Path(__file__).resolve().parent / "var"))
MAX_FILE = int(os.getenv("DRIVE_FILE_MB", "200")) * 2**20
QUOTA = int(os.getenv("DRIVE_QUOTA_MB", "2048")) * 2**20
KEEP_VERSIONS = max(1, int(os.getenv("DRIVE_VERSIONS", "10")))
TRASH_DAYS = int(os.getenv("DRIVE_TRASH_DAYS", "30"))
ACTIVITY_DAYS = 365
TEXT_MAX = 300_000
MAX_ZIP_ITEMS, MAX_COPY_ITEMS = 10_000, 5_000
THUMB = 400
ID = re.compile(r"^[0-9a-f]{32}$")
# shown in the browser as themselves; everything else is served as plain text (if it's text) or as a download
INLINE = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/avif", "application/pdf", "video/mp4", "video/webm",
          "audio/mpeg", "audio/ogg", "audio/wav", "audio/webm", "audio/mp4"}
TEXT_EXT = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".jsonl", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".log",
            ".py", ".js", ".ts", ".tsx", ".jsx", ".rs", ".go", ".java", ".c", ".h", ".cpp", ".hpp", ".cs", ".rb", ".php", ".sh", ".bash",
            ".sql", ".html", ".htm", ".css", ".xml", ".svg", ".env", ".dockerfile", ".r", ".ipynb", ".tex", ".rst", ".proto", ".sol"}
# Office documents are zip files of XML: the parts that hold their text
OFFICE = {".docx": r"word/(document|footnotes|endnotes|header\d*|footer\d*)\.xml", ".pptx": r"ppt/(slides/slide|notesSlides/notesSlide)\d+\.xml",
          ".xlsx": r"xl/sharedStrings\.xml", ".odt": r"content\.xml", ".ods": r"content\.xml", ".odp": r"content\.xml"}
ARCHIVE_EXT = {".zip", ".gz", ".tgz", ".bz2", ".xz", ".zst", ".7z", ".rar", ".tar", ".jar", ".whl"}
THUMBABLE = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/avif", "image/bmp", "image/tiff"}
THUMB_FORMATS = ["PNG", "JPEG", "GIF", "WEBP", "AVIF", "BMP", "TIFF"]
for d in ("blobs", "tmp", "thumbs"): (DATA / d).mkdir(parents=True, exist_ok=True)

def load_secret():
    if os.getenv("DRIVE_SECRET"): return os.getenv("DRIVE_SECRET")
    path = Path(os.getenv("DRIVE_SECRET_FILE", DATA / "secret"))
    if not path.exists():  # first start: make one; AXoR reads the same file (a shared volume in docker-compose)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_urlsafe(32))
        os.chmod(path, 0o600)
    return path.read_text().strip()

SECRET = load_secret()

# ---------- storage ----------
class DB:
    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.lock = threading.RLock()
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS nodes (id TEXT PRIMARY KEY, space TEXT NOT NULL, parent TEXT, kind TEXT NOT NULL, name TEXT NOT NULL,
              owner INTEGER, owner_name TEXT, netuid INTEGER, created REAL, updated REAL, size INTEGER DEFAULT 0, mime TEXT, version TEXT,
              trashed REAL, trashed_with TEXT, trashed_by TEXT, legacy_id TEXT UNIQUE);
            CREATE INDEX IF NOT EXISTS nodes_parent ON nodes(space, parent);
            CREATE INDEX IF NOT EXISTS nodes_parent_id ON nodes(parent);
            CREATE TABLE IF NOT EXISTS versions (id TEXT PRIMARY KEY, node TEXT NOT NULL, blob TEXT NOT NULL, size INTEGER, mime TEXT,
              created REAL, by INTEGER, by_name TEXT);
            CREATE INDEX IF NOT EXISTS versions_node ON versions(node);
            CREATE INDEX IF NOT EXISTS versions_by ON versions(by);
            CREATE TABLE IF NOT EXISTS shares (token TEXT PRIMARY KEY, node TEXT NOT NULL, by INTEGER, by_name TEXT, created REAL,
              expires REAL, pw TEXT, downloads INTEGER DEFAULT 0, revoked REAL);
            CREATE TABLE IF NOT EXISTS stars (uid INTEGER NOT NULL, node TEXT NOT NULL, created REAL, PRIMARY KEY (uid, node));
            CREATE TABLE IF NOT EXISTS grants (node TEXT NOT NULL, uid INTEGER NOT NULL, user_name TEXT, role TEXT NOT NULL,
              by INTEGER, by_name TEXT, created REAL, PRIMARY KEY (node, uid));
            CREATE INDEX IF NOT EXISTS grants_uid ON grants(uid);
            CREATE TABLE IF NOT EXISTS activity (id INTEGER PRIMARY KEY AUTOINCREMENT, node TEXT NOT NULL, uid INTEGER, user_name TEXT,
              action TEXT NOT NULL, detail TEXT, ts REAL);
            CREATE INDEX IF NOT EXISTS activity_node ON activity(node, ts);""")
        try:
            self.db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS texts USING fts5(node UNINDEXED, body)")
            self.fts = True
        except sqlite3.OperationalError:  # SQLite built without FTS5: plain table, LIKE search
            self.db.execute("CREATE TABLE IF NOT EXISTS texts (node TEXT, body TEXT)")
            self.fts = False
        self.db.commit()

    def q(self, sql, args=(), one=False):
        with self.lock:
            cur = self.db.execute(sql, args)
            cols = [c[0] for c in cur.description] if cur.description else []
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            self.db.commit()
        return (rows[0] if rows else None) if one else rows

db = DB(DATA / "drive.db")

def blob_path(sha): return DATA / "blobs" / sha[:2] / sha
def thumb_path(sha): return DATA / "thumbs" / f"{sha}.webp"

def gc_blob(sha):
    if not db.q("SELECT 1 FROM versions WHERE blob=? LIMIT 1", (sha,), one=True):
        blob_path(sha).unlink(missing_ok=True); thumb_path(sha).unlink(missing_ok=True)

# ---------- callers ----------
def caller(req: Request):
    """The AXoR backend, acting for one of its users."""
    if not hmac.compare_digest(req.headers.get("authorization", "").encode(), f"Bearer {SECRET}".encode()):
        raise HTTPException(401, "Bad drive credentials.")
    uid = req.headers.get("x-drive-user", "")
    if not uid.isdigit(): raise HTTPException(400, "No acting user.")
    return {"id": int(uid), "name": unquote(req.headers.get("x-drive-name", ""))[:64] or f"user {uid}", "admin": req.headers.get("x-drive-admin") == "1"}

def service(req: Request):
    """The AXoR backend on its own (public share links)."""
    if not hmac.compare_digest(req.headers.get("authorization", "").encode(), f"Bearer {SECRET}".encode()):
        raise HTTPException(401, "Bad drive credentials.")

def space_key(me, s):
    if s == "shared": return "shared"
    if s == "mine": return f"user:{me['id']}"
    if s == "with": raise HTTPException(400, "Open a folder that's shared with you to add to it.")
    raise HTTPException(400, "Unknown drive space.")

def space_name(me, key): return "shared" if key == "shared" else "mine" if key == f"user:{me['id']}" else "with"
def spaces(me): return ("shared", f"user:{me['id']}")

# ---------- permissions ----------
# `me` lives for one request, so it caches the user's grants and stars and what's been worked out from them.
RANK = {None: 0, "viewer": 1, "editor": 2}

def my_grants(me):
    if "_grants" not in me: me["_grants"] = {r["node"]: r["role"] for r in db.q("SELECT node, role FROM grants WHERE uid=?", (me["id"],))}
    return me["_grants"]

def above(me, nid):
    """(best role shared with the user on this node or a folder above it, whether one of those is an editor grant)."""
    if nid is None: return None, False
    memo = me.setdefault("_above", {})
    if nid not in memo:
        memo[nid] = (None, False)  # a guard, should parents ever loop
        p = db.q("SELECT parent FROM nodes WHERE id=?", (nid,), one=True)
        role, editor = above(me, p["parent"]) if p else (None, False)
        own = my_grants(me).get(nid)
        memo[nid] = (own if RANK[own] > RANK[role] else role, editor or own == "editor")
    return memo[nid]

def perms(me, n):
    """(role, write, manage) of the user on a node. role: owner (their My drive), member (the Shared drive), editor or
    viewer (shared with them), or None (no access). write: add files, folders and versions. manage: rename, move, delete."""
    if n["space"] == f"user:{me['id']}": return "owner", True, True
    if n["space"] == "shared": return "member", True, me["admin"] or n["owner"] == me["id"]
    if not my_grants(me): return None, False, False
    role, editor_above = above(me, n["parent"])
    own = my_grants(me).get(n["id"])
    role = own if RANK[own] > RANK[role] else role
    return role, role == "editor", editor_above  # editors manage what's inside a shared folder, not the shared item itself

def need_manage(me, n, verb="change"):
    role, _, manage = perms(me, n)
    if manage: return role
    raise HTTPException(403, f"Only the person who added this (or an admin) can {verb} it." if role == "member"
                        else f"Only its owner can {verb} an item they shared with you." if role == "editor" else f"You can view this, but not {verb} it.")

def stars(me):
    if "_stars" not in me: me["_stars"] = {r["node"] for r in db.q("SELECT node FROM stars WHERE uid=?", (me["id"],))}
    return me["_stars"]

def clean(name):
    name = re.sub(r"[\x00-\x1f\x7f/\\]", "_", (name or "").strip())[:200].strip()
    if not name or name in (".", ".."): raise HTTPException(400, "Give it a name.")
    return name

def get(me, nid, trashed=False):
    n = db.q("SELECT * FROM nodes WHERE id=?", (nid,), one=True) if ID.match(nid or "") else None
    if not n or not perms(me, n)[0] or (n["trashed"] and not trashed): raise HTTPException(404, "That file or folder doesn't exist.")
    return n

def dest(me, space, parent):
    """Where new items go: (space key, folder or None for the space's root), checking the user may add there."""
    if not parent: return space_key(me, space), None
    f = get(me, parent)
    if f["kind"] != "folder": raise HTTPException(400, "That isn't a folder.")
    if not perms(me, f)[1]: raise HTTPException(403, "You can view this folder, but not add to it.")
    return f["space"], f

def pid(f): return f["id"] if f else None

def path_of(n):
    out, cur, seen = [], n, set()
    while cur and cur["parent"] and cur["parent"] not in seen:
        seen.add(cur["parent"])
        cur = db.q("SELECT id, name, parent FROM nodes WHERE id=?", (cur["parent"],), one=True)
        if cur: out.insert(0, {"id": cur["id"], "name": cur["name"]})
    return out

def trail(me, n):
    """The folders above a node that the user may see: all of them in their own spaces; otherwise from the topmost
    folder shared with them (the owner's folders above it stay private)."""
    path = path_of(n)
    if n["space"] in spaces(me): return path
    for i, p in enumerate(path):
        if p["id"] in my_grants(me): return path[i:]
    return []

def descendants(nid):
    return [r["id"] for r in db.q("""WITH RECURSIVE sub(id) AS (SELECT id FROM nodes WHERE parent=? UNION SELECT c.id FROM nodes c JOIN sub ON c.parent=sub.id)
                                     SELECT id FROM sub""", (nid,))]

def folder_files(nid, live=True):
    """(number of files, their total size) inside a folder, at any depth."""
    alive = " AND trashed IS NULL" if live else ""
    r = db.q(f"""WITH RECURSIVE sub(id) AS (SELECT id FROM nodes WHERE parent=?{alive} UNION SELECT c.id FROM nodes c JOIN sub ON c.parent=sub.id
                   WHERE 1{alive.replace('trashed', 'c.trashed')}) SELECT COUNT(*) n, COALESCE(SUM(size), 0) s FROM nodes WHERE kind='file' AND id IN (SELECT id FROM sub)""",
             (nid,), one=True)
    return r["n"], r["s"]

def taken(key, parent, name, exclude=None):
    return db.q("SELECT id, kind FROM nodes WHERE space=? AND parent IS ? AND name=? COLLATE NOCASE AND trashed IS NULL AND id IS NOT ?",
                (key, parent, name, exclude), one=True)

def free_name(key, parent, name, kind="file", tag=None):
    """The first free name in the folder with a counter: “a (1).txt”, or with a tag: “a (copy).txt”, “a (copy 2).txt”."""
    stem, ext = os.path.splitext(name) if kind == "file" else (name, "")
    for i in range(1, 10_000):
        cand = f"{stem} ({(tag if i == 1 else f'{tag} {i}') if tag else i}){ext}"
        if not taken(key, parent, cand): return cand
    raise HTTPException(409, "Too many items with that name here.")

def usage(uid):
    return db.q("SELECT COALESCE(SUM(size), 0) s FROM versions WHERE by=?", (uid,), one=True)["s"]

def item(me, n, extra=None):
    role, write, manage = perms(me, n)
    parent = n["parent"] if role in ("owner", "member") or (n["parent"] and above(me, n["parent"])[0]) else None  # only a folder they can open
    return {"id": n["id"], "kind": n["kind"], "name": n["name"], "parent": parent, "size": n["size"] or 0, "mime": n["mime"], "created": n["created"],
            "updated": n["updated"], "owner": n["owner_name"], "mine": n["owner"] == me["id"], "netuid": n["netuid"],
            "space": space_name(me, n["space"]), "role": role, "can_write": write, "can_modify": manage, "trashed": n["trashed"],
            "starred": n["id"] in stars(me), "version": n["version"], "versions": n.get("nversions"), "links": n.get("nlinks"),
            "shared": n.get("npeople"), **(extra or {})}

def where(me, n): return {"path": "/".join(p["name"] for p in trail(me, n))}

COUNTS = """, (SELECT COUNT(*) FROM versions v WHERE v.node=n.id) nversions,
              (SELECT COUNT(*) FROM shares s WHERE s.node=n.id AND s.revoked IS NULL AND (s.expires IS NULL OR s.expires > strftime('%s','now'))) nlinks,
              (SELECT COUNT(*) FROM grants g WHERE g.node=n.id) npeople"""
# every node the user can read: their own spaces (checked in the query) and everything under what's shared with them
READABLE = "WITH RECURSIVE acc(id) AS (SELECT node FROM grants WHERE uid=? UNION SELECT c.id FROM nodes c JOIN acc ON c.parent=acc.id) "
CAN_READ = "(n.space IN (?,?) OR n.id IN (SELECT id FROM acc))"

def act(me, nid, action, detail=""):
    db.q("INSERT INTO activity(node, uid, user_name, action, detail, ts) VALUES (?,?,?,?,?,?)",
         (nid, me["id"], me["name"], action, str(detail)[:300], time.time()))

def new_node(me, key, parent, kind, name, netuid=None, ts=None, legacy=None):
    nid, ts = uuid.uuid4().hex, ts or time.time()
    db.q("""INSERT INTO nodes(id, space, parent, kind, name, owner, owner_name, netuid, created, updated, legacy_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (nid, key, parent, kind, name, me["id"], me["name"], netuid, ts, ts, legacy))
    return nid

def add_version(me, nid, sha, size, mime, ts):
    """A new current version of a file, dropping the oldest past DRIVE_VERSIONS (callers hold db.lock)."""
    vid = uuid.uuid4().hex
    db.q("INSERT INTO versions VALUES (?,?,?,?,?,?,?,?)", (vid, nid, sha, size, mime, ts, me["id"], me["name"]))
    db.q("UPDATE nodes SET version=?, size=?, mime=?, updated=? WHERE id=?", (vid, size, mime, ts, nid))
    for v in db.q("SELECT id, blob FROM versions WHERE node=? ORDER BY created DESC LIMIT -1 OFFSET ?", (nid, KEEP_VERSIONS)):
        db.q("DELETE FROM versions WHERE id=?", (v["id"],)); gc_blob(v["blob"])
    return vid

async def receive(req: Request, me):
    """Store the request body as a blob: (sha256, size), within the file size limit and the user's quota."""
    declared, used = int(req.headers.get("content-length") or 0), usage(me["id"])
    if declared > MAX_FILE: raise HTTPException(413, f"Files can be up to {MAX_FILE // 2**20} MB.")
    if used + declared > QUOTA: raise HTTPException(413, "Not enough space left in your drive. Empty the trash or delete old files.")
    tmp, h, size = DATA / "tmp" / uuid.uuid4().hex, hashlib.sha256(), 0
    try:
        with open(tmp, "wb") as f:
            async for chunk in req.stream():
                size += len(chunk)
                if size > MAX_FILE: raise HTTPException(413, f"Files can be up to {MAX_FILE // 2**20} MB.")
                if used + size > QUOTA: raise HTTPException(413, "Not enough space left in your drive. Empty the trash or delete old files.")
                h.update(chunk); f.write(chunk)
        sha = h.hexdigest()
        dest_path = blob_path(sha)
        dest_path.parent.mkdir(exist_ok=True)
        if dest_path.exists(): tmp.unlink()
        else: os.replace(tmp, dest_path)
    finally:
        tmp.unlink(missing_ok=True)
    return sha, size

# ---------- text for search and agents ----------
def textlike(name, mime):
    return (mime or "").startswith("text/") or Path(name).suffix.lower() in TEXT_EXT or mime in ("application/json", "application/xml")

def office_text(path, ext):
    """The text of a Word, PowerPoint, Excel or OpenDocument file, read from its XML (each part read up to a limit)."""
    natural = lambda s: [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]
    out = []
    with zipfile.ZipFile(path) as z:
        for part in sorted((p for p in z.namelist() if re.fullmatch(OFFICE[ext], p)), key=natural)[:500]:
            with z.open(part) as f: xml = f.read(TEXT_MAX * 8).decode("utf-8", "replace")
            xml = re.sub(r"<(?:w:tab|text:tab)\b[^>]*/>", "\t", xml)
            xml = re.sub(r"</(?:w:p|a:p|text:p|text:h|si)>|<(?:w:br|a:br|text:line-break)\b[^>]*/>", "\n", xml)
            out.append(html.unescape(re.sub(r"<[^>]+>", "", xml)))
            if sum(map(len, out)) > TEXT_MAX: break
    return re.sub(r"\n{3,}", "\n\n", "\n\n".join(out)).strip()[:TEXT_MAX]

def extract(path, name, mime):
    ext = Path(name).suffix.lower()
    if mime == "application/pdf" or ext == ".pdf":
        try:
            from pypdf import PdfReader
            reader, out = PdfReader(str(path)), []
            for page in reader.pages[:60]:
                out.append(page.extract_text() or "")
                if sum(map(len, out)) > TEXT_MAX: break
            return "\n\n".join(out)[:TEXT_MAX]
        except Exception as e:
            log.info("pdf text failed for %s: %s", name, e); return None
    if ext in OFFICE:
        try: return office_text(path, ext)
        except Exception as e:
            log.info("office text failed for %s: %s", name, e); return None
    if not textlike(name, mime): return None
    with open(path, "rb") as f: raw = f.read(TEXT_MAX * 2)
    if b"\x00" in raw[:4096]: return None
    try: return raw.decode("utf-8")[:TEXT_MAX]
    except UnicodeDecodeError: return raw.decode("latin-1")[:TEXT_MAX]

def has_text(name, mime): return textlike(name, mime) or mime == "application/pdf" or Path(name).suffix.lower() in (".pdf", *OFFICE)

def index(nid):
    n = db.q("SELECT n.name, v.blob, v.mime FROM nodes n JOIN versions v ON v.id=n.version WHERE n.id=?", (nid,), one=True)
    if not n: return
    text = extract(blob_path(n["blob"]), n["name"], n["mime"]) if blob_path(n["blob"]).exists() else None
    with db.lock:
        db.q("DELETE FROM texts WHERE node=?", (nid,))
        if text and text.strip(): db.q("INSERT INTO texts(node, body) VALUES (?,?)", (nid, text))

def reindex(nid): threading.Thread(target=index, args=(nid,), daemon=True).start()

# ---------- zip downloads ----------
class Sink:
    """A write-only file for zipfile that hands over what's been written so far (zipfile streams when it can't seek)."""
    def __init__(self): self.buf, self.pos = bytearray(), 0
    def write(self, b): self.buf += b; self.pos += len(b); return len(b)
    def tell(self): return self.pos
    def flush(self): pass
    def take(self):
        out = bytes(self.buf); self.buf.clear(); return out

def zip_entries(roots):
    """(path in the zip, the file's current version or None for a folder, modified) for these items and what's in them."""
    out, tops = [], set()
    def walk(n, path):
        if len(out) >= MAX_ZIP_ITEMS: raise HTTPException(413, f"That's more than {MAX_ZIP_ITEMS:,} items. Download fewer at a time.")
        if n["kind"] == "file":
            v = db.q("SELECT blob, size, mime FROM versions WHERE id=?", (n["version"],), one=True)
            if v and blob_path(v["blob"]).exists(): out.append((path, v, n["updated"]))
            return
        out.append((path + "/", None, n["updated"]))
        for c in db.q("SELECT * FROM nodes WHERE parent=? AND trashed IS NULL ORDER BY kind DESC, name COLLATE NOCASE", (n["id"],)):
            walk(c, f"{path}/{c['name']}")
    for r in roots:  # items picked from search results can share a name
        name, i = r["name"], 1
        while name.lower() in tops:
            i += 1; stem, ext = os.path.splitext(r["name"]) if r["kind"] == "file" else (r["name"], ""); name = f"{stem} ({i}){ext}"
        tops.add(name.lower()); walk(r, name)
    return out

def zip_stream(entries):
    sink = Sink()
    with zipfile.ZipFile(sink, "w") as zf:
        for path, v, ts in entries:
            zi = zipfile.ZipInfo(path, date_time=time.localtime(max(ts or 0, 315532800))[:6])
            if v is None:
                zf.writestr(zi, b""); continue
            packed = Path(path).suffix.lower() in ARCHIVE_EXT | {".docx", ".xlsx", ".pptx", ".pdf"} or (v["mime"] or "").startswith(("image/", "video/", "audio/"))
            zi.compress_type, zi.file_size = zipfile.ZIP_STORED if packed else zipfile.ZIP_DEFLATED, v["size"] or 0
            with open(blob_path(v["blob"]), "rb") as src, zf.open(zi, "w") as dst:
                while chunk := src.read(2**20):
                    dst.write(chunk)
                    if len(sink.buf) >= 2**20: yield sink.take()
            yield sink.take()
    yield sink.take()

def zip_response(roots, name):
    entries = zip_entries(roots)
    fallback = re.sub(r"[^A-Za-z0-9._ -]", "_", name) or "download.zip"
    return StreamingResponse(zip_stream(entries), media_type="application/zip",
                             headers={"Content-Disposition": f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(name)}"})

# ---------- app ----------
app = FastAPI(title="AXoR Drive", version="2.0", docs_url=None, redoc_url=None)

@app.middleware("http")
async def headers(req, call_next):
    resp = await call_next(req)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers.setdefault("Cache-Control", "no-store")
    return resp

@app.get("/health")
def health():
    return {"ok": True, "fts": db.fts, "thumbnails": Image is not None}

@app.get("/v1/usage")
def get_usage(me=Depends(caller)):
    return {"used": usage(me["id"]), "quota": QUOTA, "max_file": MAX_FILE, "versions": KEEP_VERSIONS, "trash_days": TRASH_DAYS,
            "thumbnails": Image is not None}

def shared_with(me):
    """What's shared with the user, newest first, leaving out what's inside something else shared with them."""
    rows = db.q(f"""SELECT n.*{COUNTS}, g.by_name shared_by, g.created shared_at FROM grants g JOIN nodes n ON n.id=g.node
                    WHERE g.uid=? AND n.trashed IS NULL AND n.space LIKE 'user:%' ORDER BY g.created DESC""", (me["id"],))
    return [item(me, r, {"shared_by": r["shared_by"], "shared_at": r["shared_at"]}) for r in rows if not above(me, r["parent"])[0]]

@app.get("/v1/list")
def list_folder(space: str, folder_id: str | None = None, me=Depends(caller)):
    if folder_id:
        f = get(me, folder_id)
        if f["kind"] != "folder": raise HTTPException(400, "That isn't a folder.")
        rows = db.q(f"SELECT n.*{COUNTS} FROM nodes n WHERE space=? AND parent=? AND trashed IS NULL ORDER BY kind DESC, name COLLATE NOCASE",
                    (f["space"], f["id"]))
        role, write, manage = perms(me, f)
        return {"space": space_name(me, f["space"]), "folder": {"id": f["id"], "name": f["name"], "role": role, "can_write": write, "can_modify": manage},
                "path": trail(me, f) + [{"id": f["id"], "name": f["name"]}], "items": [item(me, r) for r in rows]}
    if space == "with": return {"space": "with", "folder": None, "path": [], "items": shared_with(me)}
    rows = db.q(f"SELECT n.*{COUNTS} FROM nodes n WHERE space=? AND parent IS NULL AND trashed IS NULL ORDER BY kind DESC, name COLLATE NOCASE",
                (space_key(me, space),))
    return {"space": space, "folder": None, "path": [], "items": [item(me, r) for r in rows]}

@app.get("/v1/files")
def all_files(limit: int = 1000, me=Depends(caller)):
    """Every live file in the user's own spaces, newest first (the workspace panel and agent attachments)."""
    rows = db.q(f"SELECT n.*{COUNTS} FROM nodes n WHERE kind='file' AND trashed IS NULL AND space IN (?,?) ORDER BY updated DESC LIMIT ?",
                (*spaces(me), min(limit, 2000)))
    return [item(me, r, where(me, r)) for r in rows]

@app.get("/v1/recent")
def recent(me=Depends(caller)):
    rows = db.q(f"{READABLE}SELECT n.*{COUNTS} FROM nodes n WHERE kind='file' AND trashed IS NULL AND {CAN_READ} ORDER BY updated DESC LIMIT 60",
                (me["id"], *spaces(me)))
    return [item(me, r, where(me, r)) for r in rows]

@app.get("/v1/starred")
def starred(me=Depends(caller)):
    rows = db.q(f"""{READABLE}SELECT n.*{COUNTS} FROM stars st JOIN nodes n ON n.id=st.node WHERE st.uid=? AND n.trashed IS NULL AND {CAN_READ}
                    ORDER BY n.kind DESC, n.name COLLATE NOCASE""", (me["id"], me["id"], *spaces(me)))
    return [item(me, r, where(me, r)) for r in rows]

@app.get("/v1/search")
def search(q: str, me=Depends(caller)):
    q = q.strip()[:200]
    if len(q) < 2: return []
    like = "%" + re.sub(r"([%_\\])", r"\\\1", q) + "%"
    words = re.findall(r"\w+", q)[:8]
    hits = {}
    if words:
        if db.fts:
            match = " AND ".join(f'"{w}"*' for w in words)
            try:
                hits = {r["node"]: r["snip"] for r in db.q("SELECT node, snippet(texts, 1, char(2), char(3), '…', 14) snip FROM texts WHERE texts MATCH ? LIMIT 200", (match,))}
            except sqlite3.OperationalError: hits = {}
        else:
            hits = {r["node"]: None for r in db.q("SELECT node FROM texts WHERE body LIKE ? ESCAPE '\\' LIMIT 200", (like,))}
    ids = list(hits)
    rows = db.q(f"""{READABLE}SELECT n.*{COUNTS} FROM nodes n WHERE trashed IS NULL AND {CAN_READ}
                    AND (name LIKE ? ESCAPE '\\' {f"OR id IN ({','.join('?' * len(ids))})" if ids else ""})
                    ORDER BY (name LIKE ? ESCAPE '\\') DESC, updated DESC LIMIT 100""", (me["id"], *spaces(me), like, *ids, like))
    return [item(me, r, {**where(me, r), "snippet": hits.get(r["id"])}) for r in rows]

@app.get("/v1/trash")
def trash(space: str, me=Depends(caller)):
    key = space_key(me, space)
    rows = db.q(f"SELECT n.*{COUNTS} FROM nodes n WHERE space=? AND trashed IS NOT NULL AND trashed_with=id ORDER BY trashed DESC", (key,))
    return [item(me, r, {"trashed_by": r["trashed_by"], "purge_at": r["trashed"] + TRASH_DAYS * 86400,
                         "contains": len(descendants(r["id"])) if r["kind"] == "folder" else 0}) for r in rows]

def category(name, mime):
    m, ext = mime or "", Path(name).suffix.lower()
    if m.startswith("image/"): return "Images"
    if m.startswith("video/"): return "Videos"
    if m.startswith("audio/"): return "Audio"
    if has_text(name, m): return "Documents"
    if ext in ARCHIVE_EXT: return "Archives"
    return "Other"

@app.get("/v1/storage")
def storage(me=Depends(caller)):
    """What takes the user's space: by type, older versions, the trash, and their largest files."""
    vs = db.q("SELECT v.size, v.mime, v.id=n.version current, n.trashed, n.name FROM versions v JOIN nodes n ON n.id=v.node WHERE v.by=?", (me["id"],))
    kinds = {}
    for v in vs: kinds[category(v["name"], v["mime"])] = kinds.get(category(v["name"], v["mime"]), 0) + (v["size"] or 0)
    rows = db.q(f"""SELECT n.*{COUNTS} FROM nodes n JOIN versions v ON v.id=n.version WHERE v.by=? AND n.kind='file' AND n.trashed IS NULL
                    ORDER BY n.size DESC LIMIT 60""", (me["id"],))
    return {"used": usage(me["id"]), "quota": QUOTA, "kinds": sorted(({"kind": k, "size": s} for k, s in kinds.items()), key=lambda x: -x["size"]),
            "old_versions": sum(v["size"] or 0 for v in vs if not v["current"] and not v["trashed"]),
            "trash": sum(v["size"] or 0 for v in vs if v["trashed"]),
            "largest": [item(me, r, where(me, r)) for r in rows if perms(me, r)[0]][:50]}

class FolderIn(BaseModel):
    space: str | None = None
    parent: str | None = None
    name: str = Field(..., max_length=200)

@app.post("/v1/folders")
def make_folder(b: FolderIn, me=Depends(caller)):
    key, p = dest(me, b.space, b.parent)
    name = clean(b.name)
    with db.lock:
        if taken(key, pid(p), name): raise HTTPException(409, f"“{name}” already exists here.")
        nid = new_node(me, key, pid(p), "folder", name)
    act(me, nid, "created")
    return item(me, get(me, nid))

class EnsureIn(BaseModel):
    space: str | None = None
    parent: str | None = None
    path: list[str] = Field(..., min_length=1, max_length=32)

@app.post("/v1/folders/ensure")
def ensure(b: EnsureIn, me=Depends(caller)):
    """The folder at this path (from a space's root or a folder), created as needed: workspace uploads go to a fixed
    folder, and folder uploads recreate their tree."""
    key, p = dest(me, b.space, b.parent)
    parent = pid(p)
    with db.lock:
        for part in b.path:
            name = clean(part)
            t = taken(key, parent, name)
            if t and t["kind"] != "folder": raise HTTPException(409, f"“{name}” is a file, not a folder.")
            if not t:
                parent = new_node(me, key, parent, "folder", name)
                act(me, parent, "created")
            else: parent = t["id"]
    return {"id": parent}

@app.put("/v1/files")
async def upload(req: Request, space: str | None = None, name: str = "", parent: str | None = None, netuid: int | None = None,
                 conflict: str = "version", me=Depends(caller)):
    """The raw body is the file. A file with the same name in the folder gets a new version, or with conflict=keep,
    the new file gets a numbered name."""
    key, p = dest(me, space, parent)
    name = clean(name)
    legacy = req.headers.get("x-drive-import-id")
    if legacy:
        old = db.q("SELECT * FROM nodes WHERE legacy_id=?", (legacy,), one=True)
        if old: return item(me, old)
    sha, size = await receive(req, me)
    mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
    created = float(req.headers.get("x-drive-import-created") or time.time()) if legacy else time.time()
    try:
        with db.lock:
            t = taken(key, pid(p), name)
            if t and conflict == "keep": name, t = free_name(key, pid(p), name), None
            if t and t["kind"] == "folder": raise HTTPException(409, f"A folder named “{name}” already exists here.")
            nid = t["id"] if t else new_node(me, key, pid(p), "file", name, netuid, created, legacy)
            add_version(me, nid, sha, size, mime, created)
            if netuid is not None: db.q("UPDATE nodes SET netuid=? WHERE id=?", (netuid, nid))
    except HTTPException:
        gc_blob(sha); raise
    act(me, nid, "new_version" if t else "uploaded")
    reindex(nid)
    return item(me, db.q(f"SELECT n.*{COUNTS} FROM nodes n WHERE id=?", (nid,), one=True), {"new_version": bool(t)})

@app.get("/v1/nodes/{nid}")
def details(nid: str, me=Depends(caller)):
    n = db.q(f"SELECT n.*{COUNTS} FROM nodes n WHERE id=?", (get(me, nid, trashed=True)["id"],), one=True)
    role = perms(me, n)[0]
    out = item(me, n, {"path": trail(me, n), "can_share": role == "owner", "people": people_of(me, n)})
    now = time.time()
    out["shares"] = [{"token": s["token"], "by": s["by_name"], "created": s["created"], "expires": s["expires"], "password": bool(s["pw"]),
                      "downloads": s["downloads"], "mine": s["by"] == me["id"]}
                     for s in db.q("SELECT * FROM shares WHERE node=? AND revoked IS NULL ORDER BY created DESC", (nid,))
                     if not s["expires"] or s["expires"] > now]
    if n["kind"] == "file":
        out["versions_list"] = [{**v, "current": v["id"] == n["version"]} for v in
                                db.q("SELECT id, size, mime, created, by_name FROM versions WHERE node=? ORDER BY created DESC", (nid,))]
        out["textlike"] = textlike(n["name"], n["mime"])
        out["has_text"] = bool(db.q("SELECT 1 FROM texts WHERE node=? LIMIT 1", (nid,), one=True))
    else:
        out["contains"] = len(descendants(nid))
        out["files"], out["size"] = folder_files(nid, live=not n["trashed"])
    if role in ("editor", "viewer"):
        g = db.q(f"SELECT by_name FROM grants WHERE uid=? AND node IN ({','.join('?' * (len(out['path']) + 1))}) ORDER BY created LIMIT 1",
                 (me["id"], nid, *[p["id"] for p in out["path"]]), one=True)
        out["shared_by"] = g and g["by_name"]
    return out

def serve(n, v, download):
    path = blob_path(v["blob"])
    if not path.exists(): raise HTTPException(410, "The file's data is missing from the drive.")
    mime = v["mime"] or "application/octet-stream"
    if mime in INLINE: media, inline = mime, True
    elif textlike(n["name"], mime): media, inline = "text/plain; charset=utf-8", True
    else: media, inline = "application/octet-stream", False
    return FileResponse(path, media_type=media, filename=n["name"], content_disposition_type="inline" if inline and not download else "attachment")

@app.get("/v1/nodes/{nid}/content")
def content(nid: str, version: str | None = None, download: bool = False, me=Depends(caller)):
    n = get(me, nid)
    if n["kind"] != "file": raise HTTPException(400, "Folders download as a zip.")
    v = db.q("SELECT * FROM versions WHERE id=? AND node=?", (version or n["version"], nid), one=True)
    if not v: raise HTTPException(404, "That version doesn't exist.")
    return serve(n, v, download)

@app.put("/v1/nodes/{nid}/content")
async def write(nid: str, req: Request, me=Depends(caller)):
    """A new version of a file from the raw body: an edit made in the browser, or an uploaded replacement. With
    X-Drive-Base-Version, it's refused if someone saved another version since that one."""
    n = get(me, nid)
    if n["kind"] != "file": raise HTTPException(400, "That's a folder.")
    if not perms(me, n)[1]: raise HTTPException(403, "You can view this file, but not change it.")
    base = req.headers.get("x-drive-base-version")
    stale = HTTPException(409, "Someone saved a newer version of this file since you opened it. Copy your changes, reopen it and try again.")
    if base and base != n["version"]: raise stale
    sha, size = await receive(req, me)
    with db.lock:
        if base and db.q("SELECT version FROM nodes WHERE id=?", (nid,), one=True)["version"] != base:
            gc_blob(sha); raise stale
        add_version(me, nid, sha, size, mimetypes.guess_type(n["name"])[0] or n["mime"] or "application/octet-stream", time.time())
    act(me, nid, "edited" if req.headers.get("x-drive-edit") else "new_version")
    reindex(nid)
    return item(me, db.q(f"SELECT n.*{COUNTS} FROM nodes n WHERE id=?", (nid,), one=True))

@app.get("/v1/nodes/{nid}/text")
def text(nid: str, me=Depends(caller)):
    n = get(me, nid)
    if n["kind"] != "file": raise HTTPException(400, "Folders have no text.")
    t = db.q("SELECT body FROM texts WHERE node=?", (nid,), one=True)
    if not t and has_text(n["name"], n["mime"]):  # not indexed yet (just uploaded)
        index(nid); t = db.q("SELECT body FROM texts WHERE node=?", (nid,), one=True)
    return {"name": n["name"], "size": n["size"], "mime": n["mime"], "version": n["version"], "text": t["body"] if t else None}

thumb_gate = threading.Semaphore(2)  # decoding big images takes memory: two at a time

@app.get("/v1/nodes/{nid}/thumb")
def thumb(nid: str, me=Depends(caller)):
    n = get(me, nid)
    v = db.q("SELECT blob, mime FROM versions WHERE id=?", (n["version"],), one=True) if n["kind"] == "file" else None
    if not Image or not v or v["mime"] not in THUMBABLE: raise HTTPException(404, "No thumbnail for this file.")
    out = thumb_path(v["blob"])
    if not out.exists():
        with thumb_gate:
            if not out.exists():
                tmp = out.with_name(f"{uuid.uuid4().hex}.tmp")
                try:
                    with Image.open(blob_path(v["blob"]), formats=THUMB_FORMATS) as im:  # by content, so only these decoders
                        im.draft("RGB", (THUMB * 2, THUMB * 2))  # JPEGs decode at a fraction of their size
                        im = ImageOps.exif_transpose(im)
                        im.thumbnail((THUMB, THUMB))
                        im = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P", "PA") else "RGB")
                        im.save(tmp, "WEBP", quality=78)
                    os.replace(tmp, out)
                except Exception as e:
                    log.info("no thumbnail for %s: %s", n["name"], e)
                    raise HTTPException(404, "No thumbnail for this file.")
                finally:
                    tmp.unlink(missing_ok=True)
    return FileResponse(out, media_type="image/webp")

@app.get("/v1/nodes/{nid}/activity")
def activity(nid: str, me=Depends(caller)):
    """What happened to an item (and, for a folder, to what's in it), newest first."""
    get(me, nid, trashed=True)
    rows = db.q("""WITH RECURSIVE sub(id) AS (SELECT ? UNION SELECT c.id FROM nodes c JOIN sub ON c.parent=sub.id)
                   SELECT a.node, a.user_name, a.uid, a.action, a.detail, a.ts, n.name, n.kind FROM activity a JOIN sub ON sub.id=a.node
                   LEFT JOIN nodes n ON n.id=a.node ORDER BY a.ts DESC, a.id DESC LIMIT 100""", (nid,))
    return [{**r, "mine": r.pop("uid") == me["id"]} for r in rows]

class PatchIn(BaseModel):
    name: str | None = Field(None, max_length=200)
    space: str | None = None
    parent: str | None = None  # "" = the space's root
    netuid: int | None = None

@app.patch("/v1/nodes/{nid}")
def patch(nid: str, b: PatchIn, me=Depends(caller)):
    n = get(me, nid)
    need_manage(me, n)
    name = clean(b.name) if b.name is not None else n["name"]
    key, parent = n["space"], n["parent"]
    moving = b.parent is not None or (b.space is not None and space_key(me, b.space) != n["space"])
    if moving:
        if b.parent:
            key, p = dest(me, None, b.parent)
            if p["id"] == nid or p["id"] in descendants(nid): raise HTTPException(400, "A folder can't go inside itself.")
            parent = p["id"]
        else:
            key, parent = space_key(me, b.space) if b.space else n["space"], None
            if key not in spaces(me): raise HTTPException(403, "Pick a folder to move it into.")
        if key != n["space"]:
            if n["space"] not in spaces(me): raise HTTPException(403, "Items shared with you stay in their owner's drive. Make a copy instead.")
            if key != "shared" and n["owner"] != me["id"]:
                raise HTTPException(403, "You can only move your own files into My drive." if key in spaces(me) else "You can only move your own files into a folder shared with you.")
    with db.lock:
        if taken(key, parent, name, exclude=nid): raise HTTPException(409, f"“{name}” already exists there.")
        db.q("UPDATE nodes SET name=?, space=?, parent=?, netuid=COALESCE(?, netuid), updated=? WHERE id=?",
             (name, key, parent, b.netuid, time.time(), nid))
        if key != n["space"]:
            sub = [nid] + descendants(nid)
            for d in sub: db.q("UPDATE nodes SET space=? WHERE id=?", (key, d))
            for i in range(0, len(sub), 500):  # sharing belongs to the drive it was in
                db.q(f"DELETE FROM grants WHERE node IN ({','.join('?' * len(sub[i:i + 500]))})", sub[i:i + 500])
    if name != n["name"]: act(me, nid, "renamed", f"{n['name']} → {name}")
    if key != n["space"] or parent != n["parent"]:
        to = db.q("SELECT name FROM nodes WHERE id=?", (parent,), one=True) if parent else None
        act(me, nid, "moved", to["name"] if to else {"shared": "Shared drive"}.get(key, "My drive"))
    return item(me, get(me, nid))

@app.post("/v1/nodes/{nid}/trash")
def to_trash(nid: str, me=Depends(caller)):
    n = get(me, nid)
    need_manage(me, n, "delete")
    now = time.time()
    with db.lock:
        for i in [nid] + descendants(nid):
            db.q("UPDATE nodes SET trashed=?, trashed_with=?, trashed_by=? WHERE id=? AND trashed IS NULL", (now, nid, me["name"], i))
    act(me, nid, "trashed")
    return {"ok": True}

@app.post("/v1/nodes/{nid}/restore")
def restore(nid: str, me=Depends(caller)):
    n = get(me, nid, trashed=True)
    if not n["trashed"] or n["trashed_with"] != nid: raise HTTPException(400, "That isn't in the trash.")
    need_manage(me, n, "restore")
    with db.lock:
        parent = n["parent"]
        if parent and not db.q("SELECT 1 FROM nodes WHERE id=? AND trashed IS NULL", (parent,), one=True): parent = None  # its folder is gone
        name = n["name"]
        if taken(n["space"], parent, name, exclude=nid):
            stem, ext = os.path.splitext(name) if n["kind"] == "file" else (name, "")
            name = f"{stem} (restored){ext}"
        db.q("UPDATE nodes SET trashed=NULL, trashed_with=NULL, trashed_by=NULL WHERE trashed_with=?", (nid,))
        db.q("UPDATE nodes SET parent=?, name=? WHERE id=?", (parent, name, nid))
    act(me, nid, "restored")
    return item(me, get(me, nid))

def purge(nid):
    with db.lock:
        for i in [nid] + descendants(nid):
            blobs = [v["blob"] for v in db.q("SELECT blob FROM versions WHERE node=?", (i,))]
            for t in ("versions", "shares", "texts", "stars", "grants", "activity"): db.q(f"DELETE FROM {t} WHERE node=?", (i,))
            db.q("DELETE FROM nodes WHERE id=?", (i,))
            for b in set(blobs): gc_blob(b)

@app.delete("/v1/nodes/{nid}")
def delete_forever(nid: str, me=Depends(caller)):
    n = get(me, nid, trashed=True)
    if not n["trashed"] or n["trashed_with"] != nid: raise HTTPException(400, "Move it to the trash first.")
    need_manage(me, n, "delete")
    purge(nid)
    return {"ok": True}

@app.delete("/v1/trash")
def empty_trash(space: str, me=Depends(caller)):
    key = space_key(me, space)
    n = 0
    for r in db.q("SELECT * FROM nodes WHERE space=? AND trashed IS NOT NULL AND trashed_with=id", (key,)):
        if perms(me, r)[2]: purge(r["id"]); n += 1
    return {"ok": True, "deleted": n}

@app.post("/v1/nodes/{nid}/versions/{vid}/restore")
def restore_version(nid: str, vid: str, me=Depends(caller)):
    n = get(me, nid)
    role, _, manage = perms(me, n)
    if not (manage or role == "editor"): raise HTTPException(403, "Only the person who added this file (or an admin) can restore an old version.")
    v = db.q("SELECT * FROM versions WHERE id=? AND node=?", (vid, nid), one=True)
    if not v: raise HTTPException(404, "That version doesn't exist.")
    with db.lock:  # restoring copies the old version on top, so nothing in the history is lost
        add_version(me, nid, v["blob"], v["size"], v["mime"], time.time())
    act(me, nid, "version_restored", time.strftime("%b %d, %Y %H:%M", time.gmtime(v["created"])) + " UTC")
    reindex(nid)
    return {"ok": True}

# ---------- stars, copies and zips ----------
class StarIn(BaseModel):
    on: bool

@app.put("/v1/nodes/{nid}/star")
def star(nid: str, b: StarIn, me=Depends(caller)):
    get(me, nid)
    if b.on: db.q("INSERT OR IGNORE INTO stars(uid, node, created) VALUES (?,?,?)", (me["id"], nid, time.time()))
    else: db.q("DELETE FROM stars WHERE uid=? AND node=?", (me["id"], nid))
    return {"starred": b.on}

class CopyIn(BaseModel):
    space: str | None = None
    parent: str | None = None

@app.post("/v1/nodes/{nid}/copy")
def copy(nid: str, b: CopyIn, me=Depends(caller)):
    """A copy of a file or folder (current versions only): where asked, else next to the original if the user may add
    there, else in their My drive. Copies share the stored data but count towards the copier's space."""
    n = get(me, nid)
    if b.space or b.parent: key, p = dest(me, b.space, b.parent)
    else:
        try: key, p = dest(me, None, n["parent"]) if n["parent"] else (n["space"], None)
        except HTTPException: key, p = None, None
        if not p and key not in spaces(me): key = f"user:{me['id']}"
    if p and n["kind"] == "folder" and (p["id"] == nid or p["id"] in descendants(nid)): raise HTTPException(400, "A folder can't be copied into itself.")
    tree = [n]  # taken in full before anything is written
    for t in tree:
        if len(tree) > MAX_COPY_ITEMS: raise HTTPException(413, f"That's more than {MAX_COPY_ITEMS:,} items to copy.")
        if t["kind"] == "folder": tree += db.q("SELECT * FROM nodes WHERE parent=? AND trashed IS NULL", (t["id"],))
    need = sum(t["size"] or 0 for t in tree if t["kind"] == "file")
    if usage(me["id"]) + need > QUOTA: raise HTTPException(413, "Not enough space left in your drive for a copy.")
    now, ids = time.time(), {}
    with db.lock:
        name = free_name(key, pid(p), n["name"], n["kind"], "copy") if taken(key, pid(p), n["name"]) else n["name"]
        for t in tree:
            parent = pid(p) if t is n else ids[t["parent"]]
            ids[t["id"]] = new_node(me, key, parent, t["kind"], name if t is n else t["name"], t["netuid"], now)
            if t["kind"] == "file":
                v = db.q("SELECT * FROM versions WHERE id=?", (t["version"],), one=True)
                if v: add_version(me, ids[t["id"]], v["blob"], v["size"], v["mime"], now)
                db.q("INSERT INTO texts(node, body) SELECT ?, body FROM texts WHERE node=?", (ids[t["id"]], t["id"]))
    act(me, ids[nid], "copied", n["name"])
    return item(me, get(me, ids[nid]))

@app.get("/v1/zip")
def zip_download(ids: str, me=Depends(caller)):
    """Files and folders as one zip, streamed as it's built."""
    nodes = [get(me, i) for i in list(dict.fromkeys(ids.split(",")))[:200]]
    if not nodes: raise HTTPException(400, "Pick something to download.")
    one = len(nodes) == 1 and nodes[0]["kind"] == "folder"
    return zip_response(nodes, f"{nodes[0]['name']}.zip" if one else f"AXoR Drive {time.strftime('%Y-%m-%d')}.zip")

# ---------- sharing with people ----------
def people_of(me, n):
    """Who an item is shared with, directly or through a folder above it that the user can see."""
    visible = trail(me, n)
    chain = [n["id"]] + [p["id"] for p in reversed(visible)]
    names = {p["id"]: p["name"] for p in visible}
    out, have = [], set()
    for nid in chain:
        for g in db.q("SELECT * FROM grants WHERE node=? ORDER BY created", (nid,)):
            if g["uid"] in have: continue
            have.add(g["uid"])
            out.append({"uid": g["uid"], "name": g["user_name"], "role": g["role"], "by": g["by_name"], "created": g["created"],
                        "me": g["uid"] == me["id"], "via": None if nid == n["id"] else names.get(nid)})
    return out

class GrantIn(BaseModel):
    uid: int
    name: str = Field(..., max_length=64)
    role: str = Field(..., pattern="^(viewer|editor)$")

@app.put("/v1/nodes/{nid}/people")
def share_with(nid: str, b: GrantIn, me=Depends(caller)):
    n = get(me, nid)
    if perms(me, n)[0] != "owner":
        raise HTTPException(403, "Everyone signed in can already open the Shared drive." if n["space"] == "shared" else "Only its owner can share this with people.")
    if b.uid == me["id"]: raise HTTPException(400, "That's you.")
    old = db.q("SELECT role FROM grants WHERE node=? AND uid=?", (nid, b.uid), one=True)
    db.q("""INSERT INTO grants(node, uid, user_name, role, by, by_name, created) VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(node, uid) DO UPDATE SET role=excluded.role, user_name=excluded.user_name""",
         (nid, b.uid, b.name, b.role, me["id"], me["name"], time.time()))
    act(me, nid, "shared", f"{b.name} can {'edit' if b.role == 'editor' else 'view'}" + (" now" if old else ""))
    return {"people": people_of(me, n)}

@app.delete("/v1/nodes/{nid}/people/{uid}")
def unshare(nid: str, uid: int, me=Depends(caller)):
    """The owner stops sharing with someone, or someone removes an item shared with them."""
    n = get(me, nid, trashed=True)
    if perms(me, n)[0] != "owner" and uid != me["id"]: raise HTTPException(403, "Only its owner can change who it's shared with.")
    g = db.q("SELECT user_name FROM grants WHERE node=? AND uid=?", (nid, uid), one=True)
    if not g: raise HTTPException(404, "It isn't shared with them directly." if uid != me["id"] else "It's shared with you through a folder above it.")
    db.q("DELETE FROM grants WHERE node=? AND uid=?", (nid, uid))
    act(me, nid, "unshared", "left" if uid == me["id"] else g["user_name"])
    return {"ok": True}

# ---------- share links ----------
def pw_hash(pw, salt=None):
    salt = salt or secrets.token_hex(16)
    return f"{salt}${hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1).hex()}"

class ShareIn(BaseModel):
    days: int | None = Field(7, ge=1, le=365)  # None = never expires
    password: str | None = Field(None, max_length=200)

@app.post("/v1/nodes/{nid}/shares")
def share(nid: str, b: ShareIn, me=Depends(caller)):
    n = get(me, nid)
    if perms(me, n)[0] == "viewer": raise HTTPException(403, "You can view this, but not share it.")
    token, now = secrets.token_urlsafe(24), time.time()
    db.q("INSERT INTO shares(token, node, by, by_name, created, expires, pw) VALUES (?,?,?,?,?,?,?)",
         (token, nid, me["id"], me["name"], now, now + b.days * 86400 if b.days else None, pw_hash(b.password) if b.password else None))
    act(me, nid, "link_created", f"{b.days} days" if b.days else "no expiry")
    return {"token": token}

@app.get("/v1/shares")
def shares(all: bool = False, me=Depends(caller)):
    """Active links: the user's own, or every link for an admin."""
    now = time.time()
    rows = db.q("""SELECT s.*, n.name, n.kind, n.space, n.trashed FROM shares s JOIN nodes n ON n.id=s.node
                   WHERE s.revoked IS NULL AND (s.expires IS NULL OR s.expires > ?) AND (? OR s.by=?) ORDER BY s.created DESC""",
                (now, 1 if all and me["admin"] else 0, me["id"]))
    return [{"token": r["token"], "node": r["node"], "name": r["name"], "kind": r["kind"], "by": r["by_name"], "mine": r["by"] == me["id"],
             "created": r["created"], "expires": r["expires"], "password": bool(r["pw"]), "downloads": r["downloads"], "trashed": bool(r["trashed"]),
             "space": "shared" if r["space"] == "shared" else "private"} for r in rows]

@app.delete("/v1/shares/{token}")
def revoke(token: str, me=Depends(caller)):
    s = db.q("SELECT s.*, n.space, n.owner, n.parent FROM shares s JOIN nodes n ON n.id=s.node WHERE token=?", (token,), one=True)
    role = perms(me, {**s, "id": s["node"]})[0] if s else None
    if not s or not (s["by"] == me["id"] or me["admin"] or role == "owner" or (role and s["owner"] == me["id"])):
        raise HTTPException(404, "That link doesn't exist.")
    db.q("UPDATE shares SET revoked=? WHERE token=?", (time.time(), token))
    act(me, s["node"], "link_revoked")
    return {"ok": True}

def live_share(token):
    s = db.q("SELECT s.*, n.name, n.kind, n.size, n.mime, n.version, n.trashed, n.updated FROM shares s JOIN nodes n ON n.id=s.node WHERE token=?", (token,), one=True) \
        if re.fullmatch(r"[A-Za-z0-9_-]{20,64}", token) else None
    if not s or s["revoked"] or s["trashed"] or (s["expires"] and s["expires"] < time.time()):
        raise HTTPException(404, "This link has expired or was removed.")
    return s

def check_password(s, req):
    if s["pw"]:
        salt = s["pw"].split("$")[0]
        if not hmac.compare_digest(pw_hash(unquote(req.headers.get("x-share-password", "")), salt), s["pw"]): raise HTTPException(403, "Wrong password.")

@app.get("/v1/public/{token}", dependencies=[Depends(service)])
def public_meta(token: str):
    s = live_share(token)
    out = {"name": s["name"], "kind": s["kind"], "size": s["size"], "mime": s["mime"], "expires": s["expires"], "password": bool(s["pw"]), "by": s["by_name"]}
    if s["kind"] == "folder": out["files"], out["size"] = folder_files(s["node"])
    return out

@app.get("/v1/public/{token}/content", dependencies=[Depends(service)])
def public_content(token: str, req: Request):
    s = live_share(token)
    check_password(s, req)
    if "range" not in req.headers or req.headers["range"].startswith("bytes=0-"):
        db.q("UPDATE shares SET downloads=downloads+1 WHERE token=?", (token,))
    if s["kind"] == "folder":
        return zip_response([db.q("SELECT * FROM nodes WHERE id=?", (s["node"],), one=True)], f"{s['name']}.zip")
    v = db.q("SELECT * FROM versions WHERE id=?", (s["version"],), one=True)
    return serve({"name": s["name"]}, v, True)

# ---------- housekeeping ----------
def backfill():
    """Index Office files uploaded before the drive could read them."""
    done = {r["node"] for r in db.q("SELECT node FROM texts")}
    for r in db.q("SELECT id, name FROM nodes WHERE kind='file' AND trashed IS NULL"):
        if r["id"] not in done and Path(r["name"]).suffix.lower() in OFFICE: index(r["id"])

def janitor():
    try: backfill()
    except Exception: log.exception("drive backfill failed")
    while True:
        try:
            for r in db.q("SELECT id FROM nodes WHERE trashed IS NOT NULL AND trashed_with=id AND trashed < ?", (time.time() - TRASH_DAYS * 86400,)):
                purge(r["id"])
            db.q("DELETE FROM activity WHERE ts < ?", (time.time() - ACTIVITY_DAYS * 86400,))
            for t in [*(DATA / "tmp").iterdir(), *(DATA / "thumbs").glob("*.tmp")]:  # uploads interrupted by a restart
                if time.time() - t.stat().st_mtime > 86400: t.unlink(missing_ok=True)
        except Exception:
            log.exception("drive janitor failed")
        time.sleep(3600)

@app.on_event("startup")
def start():
    threading.Thread(target=janitor, daemon=True, name="janitor").start()
    log.info("AXoR Drive ready: data in %s, %d MB per file, %d MB per user, FTS %s, thumbnails %s", DATA, MAX_FILE // 2**20,
             QUOTA // 2**20, "on" if db.fts else "off", "on" if Image else "off (no Pillow)")
