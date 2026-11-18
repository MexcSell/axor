"""Knowledge Hub · linked folders: folders on this host kept in sync with My Knowledge (knowledge_hub.Hub mixes this in;
knowledge-linked.js draws it under Settings & connectors).

The web app can't see the host's disk (the axor namespace is "restricted": no host paths). AXoR Host files
(hostfiles_server.py, k8s/host/42-hostfiles.yaml) can: it runs in axor-host with chosen host folders mounted read-only
as "roots", answers only this pod, and never serves secrets (.env files, keys, credential stores), .git, virtual
environments or caches. HOSTFILES_URL and HOSTFILES_SECRET point here at it.

A link is (root, folder inside it, who reads it, excludes). A sync scans the folder, reads each new or changed file
(text and code as text; Word, PDF, Excel… through knowledge_media.extract; pictures, audio, video and binaries are
skipped, so a sync never spends a model call), takes secrets out (redact) and keeps it as a `source` item under
/06-Linked/<link>/<its subfolders, 4 levels at most>. A changed file is a new version of its item (so the passages are
re-indexed); a file gone from disk, or newly excluded, leaves My Knowledge. kb_linked_files maps (link, path) to the item.
"Sync automatically" re-scans every LINK_MINUTES. At most MAX_FILES files a link; the rest are counted, not read.

Only administrators link folders: it reads this server's disk. Items are the administrator's own, so agents read them
by the link's "Who reads it" like any My Knowledge item (retrieve() filters by reach before ranking).
"""
import hashlib, json, logging, os, re, threading, time, urllib.error, urllib.parse, urllib.request

from fastapi import HTTPException
from pydantic import BaseModel, Field

from .mining import _clip
from .mining_import import redact

log = logging.getLogger("knowledge")
LINK_ROOT = "/06-Linked"
MAX_FILES = max(1, int(os.getenv("KNOWLEDGE_LINK_MAX_FILES", "1000")))
LINK_MINUTES = max(2, int(os.getenv("KNOWLEDGE_LINK_MINUTES", "10")))
TEXT_FILE_MAX = 2_000_000      # bytes of one text or code file read
MAX_LINKS = 10
DEFAULT_EXCLUDE = ["*-data", "*.min.js", "*.map", "package-lock.json", "*.lock"]  # *-data: ridges-intel's copies of other miners' agents
CODE_EXT = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".sh", ".bash", ".go", ".rs", ".java", ".kt", ".c", ".h", ".cc", ".cpp", ".hpp", ".cs",
            ".rb", ".php", ".lua", ".r", ".sql", ".swift", ".scala", ".css", ".scss", ".vue", ".svelte", ".ipynb", ".toml", ".yaml", ".yml", ".ini", ".cfg"}
BINARY_EXT = {".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".whl", ".egg", ".bin", ".pt", ".pth", ".ckpt", ".safetensors", ".onnx", ".gguf",
              ".npy", ".npz", ".pkl", ".pickle", ".parquet", ".arrow", ".feather", ".h5", ".hdf5", ".exe", ".dll", ".so", ".dylib", ".o", ".a", ".class",
              ".jar", ".iso", ".img", ".dmg", ".ttf", ".otf", ".woff", ".woff2", ".eot", ".ico", ".bmp", ".tif", ".tiff", ".svgz", ".psd", ".db", ".sqlite"}
ROOT_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")


class LinkedIn(BaseModel):
    path: str = Field("", max_length=600)              # the folder's path on the server (/home/thomas/…): its root is found from it
    root: str = Field("", pattern=r"^([a-z0-9][a-z0-9-]{0,40})?$")   # or a root and a folder inside it, as before
    folder: str = Field("", max_length=400)            # inside the root; "" = all of it
    name: str = Field("", max_length=60)
    reach: str = Field("teams", pattern="^(page|agents|teams)$")
    exclude: list[str] | None = Field(None, max_length=50)
    auto: bool = True

class LinkedPatch(BaseModel):
    name: str | None = Field(None, max_length=60)
    reach: str | None = Field(None, pattern="^(page|agents|teams)$")
    exclude: list[str] | None = Field(None, max_length=50)
    auto: bool | None = None


class LinkError(Exception):
    """Host files answered with an error, or couldn't be reached; the message is safe to show."""
    def __init__(self, msg, code=502): super().__init__(msg); self.code = code


def _rel(p):
    parts = [x for x in str(p or "").replace("\\", "/").split("/") if x not in ("", ".")]
    if any(x == ".." for x in parts): raise HTTPException(400, "A folder inside the root, without ..")
    return "/".join(parts)


class HostFiles:
    """The client of AXoR Host files (hostfiles_server.py)."""
    def __init__(self, url=None, secret=None):
        self.url = (url if url is not None else os.getenv("HOSTFILES_URL", "")).rstrip("/")
        self.secret = secret if secret is not None else os.getenv("HOSTFILES_SECRET", "")

    @property
    def ready(self): return bool(self.url and self.secret)

    def _get(self, path, params, timeout=60, raw=False):
        if not self.ready: raise LinkError("Host files isn't connected (HOSTFILES_URL / HOSTFILES_SECRET): a redeploy adds it.", 503)
        req = urllib.request.Request(f"{self.url}{path}?{urllib.parse.urlencode(params)}", headers={"X-Hostfiles-Secret": self.secret})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r: return r.read() if raw else json.load(r)
        except urllib.error.HTTPError as e:
            try: msg = json.load(e).get("error") or ""
            except ValueError: msg = ""
            raise LinkError(f"Host files: {msg or e.code}", e.code)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            raise LinkError(f"Couldn't reach Host files: {getattr(e, 'reason', e)}.")

    def roots(self): return self._get("/v1/roots", {}, 10)["roots"]
    def dir(self, root, path): return self._get("/v1/dir", {"root": root, "path": path}, 20)
    def scan(self, root, path, exclude, cap): return self._get("/v1/scan", {"root": root, "path": path, "exclude": json.dumps(exclude), "max": cap}, 180)
    def file(self, root, path): return self._get("/v1/file", {"root": root, "path": path}, 120, raw=True)


def _kind(name):
    from .knowledge_media import AUDIO, DOCS, IMAGES, VIDEO
    ext = os.path.splitext(name.lower())[1]
    if ext in DOCS: return "doc"
    if ext in IMAGES or ext in AUDIO or ext in VIDEO or ext == ".svg": return "media"
    if ext in BINARY_EXT: return "binary"
    return "text"


def _decode(data):
    if b"\x00" in data[:8192]: return None
    try: return data.decode("utf-8")
    except UnicodeDecodeError:
        t = data.decode("utf-8", errors="replace")
        return t if t.count("�") < max(8, len(t) // 200) else None


class Linked:
    @property
    def hostfiles(self):
        if getattr(self, "_hostfiles", None) is None: self._hostfiles = HostFiles()
        return self._hostfiles

    def _linked_init(self):
        q = self.db.q
        q("""CREATE TABLE IF NOT EXISTS kb_linked (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, root TEXT, folder TEXT, dest TEXT,
             reach TEXT, exclude TEXT, auto INTEGER DEFAULT 1, status TEXT, error TEXT, last_sync REAL, stats TEXT, created REAL)""")
        q("""CREATE TABLE IF NOT EXISTS kb_linked_files (link_id INTEGER, rel TEXT, item_id INTEGER, size INTEGER, mtime REAL, sha TEXT,
             PRIMARY KEY (link_id, rel))""")
        q("UPDATE kb_linked SET status='ready' WHERE status='syncing'")  # a restart stopped those mid-way: the next sync goes on
        self._lk_busy, self._lk_lock = set(), threading.Lock()
        if os.getenv("KNOWLEDGE_SYNC", "1") != "0" and not getattr(self, "_lk_loop", None):
            self._lk_loop = threading.Thread(target=self._linked_loop, name="kb-linked", daemon=True)
            self._lk_loop.start()

    # ---------- links ----------
    @staticmethod
    def _lk_admin(me):
        if me.get("role") != "admin": raise HTTPException(403, "Linked folders read this server's disk, so only administrators link them.")

    def _lk(self, me, lid):
        c = self.db.q("SELECT * FROM kb_linked WHERE id=? AND user_id=?", (lid, me["id"]), one=True)
        if not c: raise HTTPException(404, "There's no such linked folder.")
        return c

    def _lk_shape(self, c, labels=None):
        n = (self.db.q("SELECT COUNT(*) n FROM kb_linked_files WHERE link_id=?", (c["id"],), one=True) or {"n": 0})["n"]
        host = (labels or {}).get(c["root"])
        return {"id": c["id"], "name": c["name"], "root": c["root"], "folder": c["folder"], "dest": c["dest"], "reach": c["reach"],
                "exclude": json.loads(c["exclude"] or "[]"), "auto": bool(c["auto"]), "status": "syncing" if c["id"] in self._lk_busy else c["status"],
                "error": c["error"], "last_sync": c["last_sync"], "stats": json.loads(c["stats"] or "{}"), "files": n, "created": c["created"],
                "host": (host.rstrip("/") + ("/" + c["folder"] if c["folder"] else "")) if host else f"{c['root']}:/{c['folder']}"}

    def linked(self, me):
        """The page: whether Host files is there, its roots, and this user's links."""
        out = {"admin": me.get("role") == "admin", "connected": self.hostfiles.ready, "roots": [], "error": None, "links": [],
               "every": LINK_MINUTES, "max_files": MAX_FILES, "default_exclude": DEFAULT_EXCLUDE}
        if not out["admin"]: return out
        labels = {}
        if out["connected"]:
            try:
                out["roots"] = self.hostfiles.roots()
                labels = {r["name"]: r.get("host") for r in out["roots"]}
            except LinkError as e: out["error"] = str(e)
        out["links"] = [self._lk_shape(c, labels) for c in self.db.q("SELECT * FROM kb_linked WHERE user_id=? ORDER BY id", (me["id"],))]
        return out

    def _host_path(self, path):
        """A server path (/home/thomas/x/y) → (root, folder inside it, the clean path): the longest mounted root that holds it."""
        import posixpath
        p = str(path or "").strip().replace("\\", "/")
        if p == "~" or p.startswith("~/"): p = "/home/thomas" + p[1:]
        if not p.startswith("/") or ".." in p.split("/"): raise HTTPException(400, "A full path on the server, like /home/thomas/projects.")
        p = posixpath.normpath(p)
        try: roots = [(r["name"], (r.get("host") or "").rstrip("/") or "/") for r in self.hostfiles.roots() if r.get("mounted") and r.get("host")]
        except LinkError as e: raise HTTPException(e.code if e.code in (400, 403, 404, 503) else 502, str(e))
        fits = [(n, h) for n, h in roots if p == h or p.startswith(h.rstrip("/") + "/")]
        if not fits: raise HTTPException(404, "AXoR can read only inside " + ", ".join(sorted({h for _, h in roots})) + ". Another place needs a mount: k8s/host-folders.sh add <path> on the server.")
        n, h = max(fits, key=lambda x: len(x[1]))
        return n, p[len(h):].strip("/"), p

    def linked_dir(self, me, root, path, host=""):
        self._lk_admin(me)
        if host: root, path, host = self._host_path(host)
        elif not ROOT_NAME.fullmatch(root or ""): raise HTTPException(400, "Pick a root.")
        try: d = self.hostfiles.dir(root, _rel(path))
        except LinkError as e: raise HTTPException(e.code if e.code in (400, 403, 404) else 502, str(e))
        return {**d, "root": root, "folder": _rel(path), "host": host or None}

    def _dest(self, me, name, lid):
        from .knowledge_spaces import _safe_seg
        base = f"{LINK_ROOT}/{_safe_seg(name, 50)}"
        taken = {r["dest"] for r in self.db.q("SELECT dest FROM kb_linked WHERE user_id=? AND id!=?", (me["id"], lid or 0))}
        dest, i = base, 2
        while dest in taken: dest, i = f"{base[:56]}-{i}", i + 1
        return dest

    def add_linked(self, me, b: LinkedIn):
        self._lk_admin(me)
        if b.path.strip(): b.root, b.folder, _ = self._host_path(b.path)
        elif not b.root: raise HTTPException(400, "Pick the folder to link.")
        folder = _rel(b.folder)
        if self.db.q("SELECT COUNT(*) n FROM kb_linked WHERE user_id=?", (me["id"],), one=True)["n"] >= MAX_LINKS: raise HTTPException(409, f"{MAX_LINKS} linked folders at most.")
        if self.db.q("SELECT 1 FROM kb_linked WHERE user_id=? AND root=? AND folder=?", (me["id"], b.root, folder), one=True):
            raise HTTPException(409, "That folder is linked already.")
        try: self.hostfiles.dir(b.root, folder)  # it exists, is a folder, may be shared
        except LinkError as e: raise HTTPException(e.code if e.code in (400, 403, 404, 503) else 502, str(e))
        name = _clip(b.name.strip() or (folder.rsplit("/", 1)[-1] if folder else b.root), 60)
        exclude = self._excl(b.exclude if b.exclude is not None else DEFAULT_EXCLUDE)
        lid = self._ins("INSERT INTO kb_linked (user_id, name, root, folder, dest, reach, exclude, auto, status, created) VALUES (?,?,?,?,?,?,?,?,'ready',?)",
                        (me["id"], name, b.root, folder, "", b.reach, json.dumps(exclude), int(b.auto), time.time()))
        self.db.q("UPDATE kb_linked SET dest=? WHERE id=?", (self._dest(me, name, lid), lid))
        self._ensure_tree(me); self._mkdirs(me, self._lk(me, lid)["dest"])
        self._audit(me, "link", f"linked:{lid}", f"{name}: {b.root}:/{folder} linked ({b.reach})")
        self._lk_start(me, lid)
        return self._lk_shape(self._lk(me, lid))

    @staticmethod
    def _excl(xs):
        out = []
        for x in xs:
            x = str(x).strip().strip("/")
            if x and len(x) <= 200 and ".." not in x: out.append(x)
        return list(dict.fromkeys(out))[:50]

    def edit_linked(self, me, lid, b: LinkedPatch):
        self._lk_admin(me)
        c, sets, rescan = self._lk(me, lid), {}, False
        if b.name is not None and b.name.strip(): sets["name"] = _clip(b.name.strip(), 60)
        if b.auto is not None: sets["auto"] = int(b.auto)
        if b.exclude is not None:
            ex = self._excl(b.exclude)
            if ex != json.loads(c["exclude"] or "[]"): sets["exclude"], rescan = json.dumps(ex), True
        if b.reach is not None and b.reach != c["reach"]:
            sets["reach"] = b.reach
            self.db.q("UPDATE kb_items SET reach=? WHERE user_id=? AND id IN (SELECT item_id FROM kb_linked_files WHERE link_id=?)", (b.reach, me["id"], lid))
        if sets: self.db.q(f"UPDATE kb_linked SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?", (*sets.values(), lid))
        self._audit(me, "link", f"linked:{lid}", f"{c['name']}: changed ({', '.join(sets) or 'nothing'})")
        if rescan: self._lk_start(me, lid)
        return self._lk_shape(self._lk(me, lid))

    def remove_linked(self, me, lid, keep=False):
        self._lk_admin(me)
        c = self._lk(me, lid)
        if lid in self._lk_busy: raise HTTPException(409, "It's syncing: remove it when the sync is done.")
        rows = self.db.q("SELECT item_id FROM kb_linked_files WHERE link_id=?", (lid,))
        if not keep:
            for r in rows: self._lk_drop_item(r["item_id"])
            self.db.q("DELETE FROM kb_folders WHERE user_id=? AND (path=? OR path LIKE ?) AND path NOT IN (SELECT DISTINCT path FROM kb_items WHERE user_id=? AND path IS NOT NULL)",
                      (me["id"], c["dest"], c["dest"] + "/%", me["id"]))
        self.db.q("DELETE FROM kb_linked_files WHERE link_id=?", (lid,))
        self.db.q("DELETE FROM kb_linked WHERE id=?", (lid,))
        self._audit(me, "link", f"linked:{lid}", f"{c['name']}: unlinked; {len(rows)} files {'kept as copies' if keep else 'removed from My Knowledge'} (the host folder is untouched)")
        return {"ok": True}

    def sync_linked(self, me, lid):
        self._lk_admin(me)
        self._lk(me, lid)
        self._lk_start(me, lid)
        return self._lk_shape(self._lk(me, lid))

    # ---------- syncing ----------
    def _lk_start(self, me, lid):
        with self._lk_lock:
            if lid in self._lk_busy: return False
            self._lk_busy.add(lid)
        me = {"id": me["id"], "username": me["username"], "role": me.get("role")}
        threading.Thread(target=self._lk_run, args=(me, lid), name=f"kb-linked-{lid}", daemon=True).start()
        return True

    def _lk_run(self, me, lid):
        try: self._lk_sync(me, lid)
        except Exception as e:  # noqa: BLE001 - a sync never takes the app down; the link says what went wrong
            log.warning("linked folder %s: %s", lid, e)
            self.db.q("UPDATE kb_linked SET status='error', error=? WHERE id=?", (_clip(f"Sync failed: {e}", 300), lid))
        finally:
            with self._lk_lock: self._lk_busy.discard(lid)

    def _lk_path(self, c, rel):
        """The My Knowledge folder of a file: the link's folder plus up to 4 levels of the file's own folders."""
        from .knowledge_spaces import _safe_seg, norm_path
        dirs = rel.split("/")[:-1][:4]
        p = c["dest"] + "".join("/" + _safe_seg(d, 50) for d in dirs)
        try: return norm_path(p)
        except HTTPException: return c["dest"]

    def _lk_sync(self, me, lid, budget=None):
        """One sync of link lid. Returns its stats. Nothing is removed when the scan itself fails."""
        c = self._lk(me, lid)
        t0 = time.time()
        self.db.q("UPDATE kb_linked SET status='syncing', error=NULL WHERE id=?", (lid,))
        try: sc = self.hostfiles.scan(c["root"], c["folder"], json.loads(c["exclude"] or "[]"), MAX_FILES)
        except LinkError as e:
            self.db.q("UPDATE kb_linked SET status='error', error=?, last_sync=? WHERE id=?", (_clip(str(e), 300), time.time(), lid))
            self._audit(me, "sync", f"linked:{lid}", f"{c['name']}: failed: {e}")
            return None
        self._ensure_tree(me)
        have = {r["rel"]: r for r in self.db.q("SELECT * FROM kb_linked_files WHERE link_id=?", (lid,))}
        st = {"files": len(sc["files"]), "added": 0, "changed": 0, "unchanged": 0, "removed": 0, "errors": 0, "redacted": 0, "truncated": sc.get("truncated", False),
              "skipped": {**sc.get("skipped", {}), "media": 0, "binary": 0, "large": 0, "notext": 0}}
        keep, prefix = set(), (c["folder"] + "/") if c["folder"] else ""
        for f in sc["files"]:
            rel, kind = f["path"], _kind(f["path"])
            if not f.get("readable"): continue  # counted by the scan
            if kind in ("media", "binary"): st["skipped"][kind] += 1; continue
            if f["size"] > (TEXT_FILE_MAX if kind == "text" else 25_000_000): st["skipped"]["large"] += 1; continue
            if f["size"] == 0: st["skipped"]["notext"] += 1; continue
            row = have.get(rel)
            item = row and self.db.q("SELECT * FROM kb_items WHERE id=? AND user_id=?", (row["item_id"], me["id"]), one=True)
            if item and row["size"] == f["size"] and row["mtime"] == f["mtime"]:
                keep.add(rel); st["unchanged"] += 1; continue
            try: data = self.hostfiles.file(c["root"], prefix + rel)
            except LinkError as e:
                st["errors"] += 1
                if item: keep.add(rel)  # it was readable before: keep what we have
                log.info("linked folder %s: %s: %s", lid, rel, e)
                continue
            sha = hashlib.sha256(data).hexdigest()
            if item and row["sha"] == sha:
                self.db.q("UPDATE kb_linked_files SET size=?, mtime=? WHERE link_id=? AND rel=?", (f["size"], f["mtime"], lid, rel))
                keep.add(rel); st["unchanged"] += 1; continue
            text, about = self._lk_text(rel, data, kind)
            if not text or not text.strip():
                st["skipped"]["notext"] += 1; continue
            from .knowledge_media import TEXT_MAX
            body, n = redact(text[:TEXT_MAX]); st["redacted"] += n
            ext = os.path.splitext(rel.lower())[1]
            meta = {"kind": "document" if kind == "doc" else "code" if ext in CODE_EXT else "file", "filename": rel.rsplit("/", 1)[-1], "size": f["size"],
                    "about": about, "truncated": len(text) > TEXT_MAX, "redacted": n, "linked": {"id": lid, "root": c["root"], "path": prefix + rel}}
            title = _clip(prefix + rel, 200)
            if item:
                self._change(me, item, {"title": title, "body": body, "data": json.dumps(meta)}, "Changed on disk")
                st["changed"] += 1
            else:
                if row: self.db.q("DELETE FROM kb_linked_files WHERE link_id=? AND rel=?", (lid, rel))  # its item was deleted by hand: link it anew
                iid = self._new(me, "source", title, body, meta, "yours", c["reach"], note="Linked", path=self._lk_path(c, rel),
                                provenance={"source": "linked folder", "file": f"{c['root']}:/{prefix + rel}", "by": me["username"]})
                self.db.q("INSERT INTO kb_linked_files (link_id, rel, item_id, size, mtime, sha) VALUES (?,?,?,?,?,?)", (lid, rel, iid, f["size"], f["mtime"], sha))
                st["added"] += 1
            if item: self.db.q("UPDATE kb_linked_files SET size=?, mtime=?, sha=? WHERE link_id=? AND rel=?", (f["size"], f["mtime"], sha, lid, rel))
            keep.add(rel)
        for rel, row in have.items():
            if rel in keep: continue
            self._lk_drop_item(row["item_id"])
            self.db.q("DELETE FROM kb_linked_files WHERE link_id=? AND rel=?", (lid, rel))
            st["removed"] += 1
        st["ms"] = int((time.time() - t0) * 1000)
        self.db.q("UPDATE kb_linked SET status='ok', error=NULL, last_sync=?, stats=? WHERE id=?", (time.time(), json.dumps(st), lid))
        if st["added"] or st["changed"] or st["removed"] or st["errors"]:
            self._audit(me, "sync", f"linked:{lid}", f"{c['name']}: {st['added']} added, {st['changed']} changed, {st['removed']} removed"
                        + (f", {st['errors']} unreadable" if st["errors"] else "") + (f", {st['redacted']} secrets taken out" if st["redacted"] else ""))
        return st

    @staticmethod
    def _lk_text(rel, data, kind):
        if kind == "doc":
            from .knowledge_media import Unreadable, extract
            try: _, text, about = extract(rel.rsplit("/", 1)[-1], data)
            except Unreadable: return "", ""
            except Exception as e:  # noqa: BLE001 - a broken document is skipped, never the sync
                log.info("linked file %s: %s", rel, e); return "", ""
            return text, about
        t = _decode(data)
        return (t, f"{os.path.splitext(rel)[1][1:].upper() or 'Text'} file · {len(data):,} bytes") if t is not None else ("", "")

    def _lk_drop_item(self, iid):
        """Delete.delete() without its per-item audit line: a sync or an unlink writes one line for all of them."""
        self.db.q("DELETE FROM kb_shares WHERE item_id=?", (iid,))
        self.db.q("DELETE FROM kb_vectors WHERE item_id=?", (iid,))
        self._rag_drop(iid)
        self.db.q("DELETE FROM kb_items WHERE id=?", (iid,))
        self.db.q("DELETE FROM kb_links WHERE item_id=? OR ref=?", (iid, f"kb:{iid}"))
        self.db.q("UPDATE kb_proposals SET status='declined', result='Its item was deleted.' WHERE item_id=? AND status='pending'", (iid,))

    def _linked_loop(self):
        time.sleep(45)
        while True:
            try:
                due = self.db.q("SELECT id, user_id FROM kb_linked WHERE auto=1 AND (last_sync IS NULL OR last_sync<?)", (time.time() - LINK_MINUTES * 60,))
                for c in due:
                    u = self.db.q("SELECT id, username, role FROM users WHERE id=? AND disabled=0", (c["user_id"],), one=True)
                    if not u or u["role"] != "admin" or c["id"] in self._lk_busy: continue
                    with self._lk_lock: self._lk_busy.add(c["id"])
                    self._lk_run(dict(u), c["id"])  # one at a time, in this thread
            except Exception as e:  # noqa: BLE001 - the loop never stops the app
                log.warning("linked folders loop: %s", e)
            time.sleep(60)

