"""All files: one catalog over every place AXoR keeps files and work products (the 11-07 evaluation: "a single file and artifact
service with permissions, versioning, indexing, search and audit; consistent scopes Personal → Company → Division → Project → Team
→ Mission → Agent").

It doesn't move anything: each store keeps its files, its permissions and its own features. The catalog reads each one through
that store's own access path for the signed-in user, and lists the results side by side with one scope per item:

- Drive (drive.py → the drive service): your files (Personal), the shared space (Company) and what's shared with you; its own
  versions, activity log and full-text search.
- Competition teams (mining_work.py): each team's files and notebook findings (Team · SN62 Competition 28), only for your teams.
- Missions (missions.py): each mission's deliverable (Mission).
- Long tasks (infiagent.py): the files a long-task agent wrote (Agent).
- Knowledge (knowledge_hub.py): My Knowledge items (Personal) and company records you may read, with their scope (Company ·
  a division or project), on search only, through the Hub's own retrieval.

Division and Project scopes appear where a store records them (company knowledge records); no other store tracks them yet, and
the page says so instead of guessing. A store that fails or isn't set up is reported in `sources` and the rest still list.
Nothing here writes, so the catalog adds no versions or audit entries of its own: those stay with the stores that have them.
"""
import json, logging, time

from fastapi import APIRouter, Request

log = logging.getLogger("artifacts")
SCOPES = {"personal": "Personal", "company": "Company", "team": "Team", "mission": "Mission", "agent": "Agent"}
SOURCES = {"drive": "Drive", "teams": "Competition teams", "missions": "Missions", "longtasks": "Long tasks", "knowledge": "Knowledge"}
PER_SOURCE = 150
LIMIT = 300


def _hit(q, *texts):
    q = (q or "").strip().lower()
    return not q or any(q in str(t or "").lower() for t in texts)


class Catalog:
    def __init__(self, db, drive=None, work=None, ia=None, missions=None, hub=None):
        self.db, self.drive, self.work, self.ia, self.mx, self.hub = db, drive, work, ia, missions, hub

    def _agents(self, me):
        """Teams, missions, long tasks and knowledge open only to users who may use agents: the same gate their pages use."""
        if self.hub is not None and hasattr(self.hub, "gate"): self.hub.gate(me)

    def _has(self, t): return bool(self.db.q("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,), one=True))

    # ---------- the stores ----------
    def _drive(self, me, q):
        if not self.drive or not self.drive.enabled: return None  # not set up on this server
        rows = self.drive.call("GET", "/v1/search", me, {"q": q[:200]}) if len(q.strip()) >= 2 else self.drive.call("GET", "/v1/recent", me)
        out = []
        for n in rows or []:
            if n.get("kind") == "folder" and not q: continue
            sc = {"mine": "personal", "shared": "company"}.get(n.get("space"), "personal")
            where = {"mine": "My drive", "shared": "Shared drive", "with": f"Shared with you by {n.get('owner') or 'a teammate'}"}.get(n.get("space"), "Drive")
            out.append({"source": "drive", "id": n["id"], "kind": "folder" if n.get("kind") == "folder" else "file", "title": n.get("name") or "",
                        "where": where + (f" / {n['path']}" if n.get("path") else ""), "scope": sc, "size": n.get("size"), "updated": n.get("updated"),
                        "versions": n.get("versions"), "snippet": n.get("snippet"), "owner": n.get("owner"),
                        "open": {"view": "drive", "space": n.get("space"), "folder": n.get("parent"), "id": n["id"]}})
        return out

    def _teams(self, me, q):
        if not self.work: return None
        self._agents(me)
        out = []
        for c in self.work.all(me)["comps"][:40]:
            wid = c["id"]
            self.work._own(me, wid)  # the team's own access check, per team
            label = f"SN{c.get('netuid')} · {c.get('label') or 'team'}"
            for f in self.db.q("SELECT path, size, updated FROM mw_files WHERE comp_id=? ORDER BY updated DESC LIMIT 200", (wid,)):
                if _hit(q, f["path"], label):
                    out.append({"source": "teams", "id": f"{wid}:{f['path']}", "kind": "file", "title": f["path"].rsplit("/", 1)[-1], "where": f"{label} / {f['path']}",
                                "scope": "team", "size": f["size"], "updated": f["updated"], "open": {"view": "teams", "team": wid, "sub": "sandbox"}})
            for n in self.db.q("SELECT id, title, ts FROM mw_notes WHERE comp_id=? ORDER BY id DESC LIMIT 100", (wid,)):
                if _hit(q, n["title"], label):
                    out.append({"source": "teams", "id": f"{wid}:note:{n['id']}", "kind": "finding", "title": n["title"] or "A finding", "where": f"{label} / Notebook",
                                "scope": "team", "updated": n["ts"], "open": {"view": "teams", "team": wid, "sub": "notes"}})
        return out

    def _missions(self, me, q):
        if not self.mx or not self._has("mx_missions"): return None
        self._agents(me)
        out = []
        for m in self.db.q("""SELECT id, title, deliverable, updated, finished FROM mx_missions WHERE user_id=? AND deliverable IS NOT NULL
                              ORDER BY id DESC LIMIT 100""", (me["id"],)):
            try: d = json.loads(m["deliverable"] or "{}") or {}
            except ValueError: continue
            if not (d.get("text") or "").strip(): continue
            if _hit(q, m["title"], d.get("summary"), d.get("text")):
                out.append({"source": "missions", "id": f"mission:{m['id']}", "kind": "plan" if d.get("kind") == "plan" else "deliverable",
                            "title": f"Deliverable: {m['title']}", "where": f"Mission #{m['id']}", "scope": "mission", "size": len(d.get("text") or ""),
                            "updated": m["finished"] or m["updated"], "snippet": (d.get("summary") or "")[:200], "open": {"view": "mos", "id": m["id"]}})
            for f in d.get("files") or []:
                if _hit(q, f, m["title"]):
                    out.append({"source": "missions", "id": f"mission:{m['id']}:{f}", "kind": "file", "title": str(f).rsplit("/", 1)[-1],
                                "where": f"Mission #{m['id']} · {m['title']}", "scope": "mission", "updated": m["finished"] or m["updated"], "open": {"view": "mos", "id": m["id"]}})
        return out

    def _longtasks(self, me, q):
        if not self.ia or not self._has("ia_tasks") or not self._has("ia_files"): return None
        self._agents(me)
        out = []
        for f in self.db.q("""SELECT f.task_id, f.path, f.size, f.updated, t.title FROM ia_files f JOIN ia_tasks t ON t.id=f.task_id
                              WHERE t.user_id=? ORDER BY f.updated DESC LIMIT 400""", (me["id"],)):
            if _hit(q, f["path"], f["title"]):
                out.append({"source": "longtasks", "id": f"{f['task_id']}:{f['path']}", "kind": "file", "title": f["path"].rsplit("/", 1)[-1],
                            "where": f"Long task #{f['task_id']} · {f['title']} / {f['path']}", "scope": "agent", "size": f["size"], "updated": f["updated"],
                            "open": {"view": "infiagent", "id": f["task_id"]}})
        return out

    def _knowledge(self, me, q):
        kb = getattr(self.hub, "knowledge", None)
        if not kb: return None
        self._agents(me)
        if len(q.strip()) < 2: return []  # the Hub lists by search: browse it in Knowledge
        out = []
        for r in kb.search(me, q[:300], internal=False)["results"]:
            if not str(r.get("ref", "")).startswith("kb:"): continue
            company = r.get("space") == "company"
            out.append({"source": "knowledge", "id": r["ref"], "kind": "record" if company else (r.get("itype") or "item"), "title": r.get("title") or "",
                        "where": ("Company knowledge" + (f" · {r['scope_label']}" if r.get("scope_label") else "")) if company else ("My Knowledge" + (f" / {r['path']}" if r.get("path") else "")),
                        "scope": "company" if company else "personal", "updated": r.get("ts"), "snippet": (r.get("text") or "")[:200],
                        "state": r.get("state_label") or "", "open": {"view": "knowledge" if company else "myknowledge", "id": int(r["ref"][3:])}})
        return out

    # ---------- the catalog ----------
    def search(self, me, q="", scope="", source=""):
        items, sources = [], {}
        for key, fn in (("drive", self._drive), ("teams", self._teams), ("missions", self._missions), ("longtasks", self._longtasks), ("knowledge", self._knowledge)):
            if source and key != source:
                continue
            try:
                got = fn(me, q or "")
            except Exception as e:  # noqa: BLE001 - one store failing leaves the rest
                log.info("artifacts: %s failed: %s", key, e)
                sources[key] = {"label": SOURCES[key], "ok": False, "error": str(getattr(e, "detail", None) or e)[:200], "n": 0}
                continue
            if got is None:
                sources[key] = {"label": SOURCES[key], "ok": False, "error": "Not set up on this server.", "n": 0}
                continue
            got = got[:PER_SOURCE]
            sources[key] = {"label": SOURCES[key], "ok": True, "error": "", "n": len(got)}
            items += got
        counts = {k: sum(1 for i in items if i["scope"] == k) for k in SCOPES}
        if scope in SCOPES: items = [i for i in items if i["scope"] == scope]
        items.sort(key=lambda i: -(i.get("updated") or 0))
        return {"q": q, "scope": scope, "items": items[:LIMIT], "total": len(items), "counts": counts, "sources": sources,
                "scopes": [{"key": k, "label": l} for k, l in SCOPES.items()], "at": time.time(),
                "untracked": ["Division", "Project"]}


def build(db, require, drive=None, work=None, ia=None, missions=None, hub=None):
    r = APIRouter(prefix="/api/artifacts")
    cat = Catalog(db, drive, work, ia, missions, hub)
    r.state = {"catalog": cat}

    @r.get("")
    def search(req: Request, q: str = "", scope: str = "", source: str = ""):
        return cat.search(require(req), q[:200], scope, source)

    return r
