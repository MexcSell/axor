"""Knowledge Hub · sharing My Knowledge items with other people on this AXoR (knowledge_hub.Hub mixes this in).

The owner shares a personal item with named users (kb_shares). They read it, read only, under My Knowledge → Shared with
me, and can save their own copy (a new private item of theirs, marked "shared by …", linked to nothing of the owner's). Their
agents never read a shared item: only a copy they made and chose to share with their agents. The owner sees who has it and
takes it back at any time; deleting the item ends its shares. Company records aren't shared this way: each account has its
own agent company. Every share, revoke and copy is in both people's activity logs.
"""
import json, time

from fastapi import HTTPException
from pydantic import BaseModel, Field

from .mining import _clip

MAX_SHARES = 50   # people one item can be shared with


class ShareIn(BaseModel):
    usernames: list[str] = Field(..., min_length=1, max_length=20)
    ids: list[int] = Field(default_factory=list, max_length=100)   # bulk: these items too (the route's item is always one)

class CopyIn(BaseModel):
    path: str = Field("", max_length=400)


class Sharing:
    def _share_init(self):
        self.db.q("""CREATE TABLE IF NOT EXISTS kb_shares (id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER, owner_id INTEGER, user_id INTEGER,
                     created REAL, UNIQUE (item_id, user_id))""")
        self.db.q("CREATE INDEX IF NOT EXISTS kb_shares_u ON kb_shares (user_id)")

    def _members_ok(self):
        f = getattr(self.hub, "members_allowed", None)
        return f() if f else True

    def people(self, me, q=""):
        """Who an item can be shared with: active accounts that may open the Knowledge Hub (everyone when members may use agents,
        else the other administrators)."""
        q = q.strip().lower()
        rows = self.db.q("SELECT id, username, role FROM users WHERE id!=? AND disabled=0 AND COALESCE(approved, 1)=1 ORDER BY username COLLATE NOCASE LIMIT 500", (me["id"],))
        rows = [r for r in rows if r["role"] == "admin" or self._members_ok()]
        return [{"id": r["id"], "username": r["username"]} for r in rows if not q or q in r["username"].lower()][:30]

    def _shares(self, iid):
        return self.db.q("SELECT s.id, s.user_id, s.created, u.username FROM kb_shares s JOIN users u ON u.id=s.user_id WHERE s.item_id=? ORDER BY u.username", (iid,))

    def share(self, me, iid, b: ShareIn):
        ids = list(dict.fromkeys([iid, *b.ids]))
        items = [self._item(me, i) for i in ids]
        if any((k["space"] or "personal") != "personal" for k in items): raise HTTPException(400, "Only My Knowledge items are shared with people; company records stay in your company.")
        users = []
        for name in dict.fromkeys(x.strip() for x in b.usernames if x.strip()):
            u = self.db.q("SELECT id, username, role FROM users WHERE username=? COLLATE NOCASE AND disabled=0 AND COALESCE(approved, 1)=1", (name,), one=True)
            if not u: raise HTTPException(404, f"There's no user called “{_clip(name, 40)}”.")
            if u["id"] == me["id"]: raise HTTPException(400, "You have it already.")
            if u["role"] != "admin" and not self._members_ok():
                raise HTTPException(409, f"{u['username']} can't open the Knowledge Hub: on this server agents (and the hub) are for administrators only (Agents → Models).")
            users.append(u)
        now, made = time.time(), 0
        for k in items:
            if len(self._shares(k["id"])) + len(users) > MAX_SHARES: raise HTTPException(409, f"An item is shared with {MAX_SHARES} people at most.")
            for u in users:
                if self.db.q("INSERT OR IGNORE INTO kb_shares (item_id, owner_id, user_id, created) VALUES (?,?,?,?) RETURNING id", (k["id"], me["id"], u["id"], now), one=True): made += 1
        names = ", ".join(u["username"] for u in users)
        self._audit(me, "share", f"kb:{iid}", f"{len(items)} item{'s' if len(items) != 1 else ''} with {names}")
        for u in users:
            self.db.q("INSERT INTO kb_audit (user_id, ts, actor, action, target, detail) VALUES (?,?,?,?,?,?)",
                      (u["id"], now, me["username"], "shared-with-you", f"kb:{iid}", _clip(f"{me['username']} shared {len(items)} item{'s' if len(items) != 1 else ''}: " + "; ".join(k["title"] for k in items[:5]), 600)))
        return {"shared": made, "item": self.item(me, iid)}

    def unshare(self, me, iid, uid):
        self._item(me, iid)
        s = self.db.q("SELECT s.id, u.username FROM kb_shares s JOIN users u ON u.id=s.user_id WHERE s.item_id=? AND s.user_id=?", (iid, uid), one=True)
        if not s: raise HTTPException(404, "It isn't shared with that person.")
        self.db.q("DELETE FROM kb_shares WHERE id=?", (s["id"],))
        self._audit(me, "unshare", f"kb:{iid}", f"no longer shared with {s['username']}")
        return self.item(me, iid)

    def shared_with_me(self, me):
        rows = self.db.q("""SELECT k.id, k.type, k.title, k.body, k.data, k.path, k.updated, s.created shared, u.username owner FROM kb_shares s
                            JOIN kb_items k ON k.id=s.item_id JOIN users u ON u.id=s.owner_id WHERE s.user_id=? AND k.status='kept' ORDER BY s.created DESC LIMIT 500""", (me["id"],))
        return [{"id": r["id"], "type": r["type"], "title": r["title"], "body": _clip(r["body"], 300), "owner": r["owner"], "kind": json.loads(r["data"] or "{}").get("kind"),
                 "updated": r["updated"], "shared": r["shared"]} for r in rows]

    def _shared_row(self, me, iid):
        r = self.db.q("""SELECT k.*, u.username owner FROM kb_shares s JOIN kb_items k ON k.id=s.item_id JOIN users u ON u.id=s.owner_id
                         WHERE s.user_id=? AND s.item_id=? AND k.status='kept'""", (me["id"], iid), one=True)
        if not r: raise HTTPException(404, "Nothing like that is shared with you.")
        return r

    def shared_item(self, me, iid):
        k = self._shared_row(me, iid)
        d = json.loads(k["data"] or "{}")
        return {"id": k["id"], "type": k["type"], "type_label": self.TYPES_LABEL(k["type"]), "title": k["title"], "body": k["body"], "owner": k["owner"],
                "ktype": k["ktype"], "tags": json.loads(k["tags"] or "[]"), "updated": k["updated"], "version": k["version"],
                "data": {x: v for x, v in d.items() if x in ("kind", "about", "url", "platform", "channel", "author", "ts", "analysis", "sections", "summary")},
                "provenance": {x: v for x, v in json.loads(k["provenance"] or "{}").items() if x in ("source", "platform", "origin")}}

    def copy_shared(self, me, iid, b: CopyIn):
        from .knowledge_spaces import norm_path
        k = self._shared_row(me, iid)
        if self.db.q("SELECT 1 FROM kb_items WHERE user_id=? AND space='personal' AND hash=?", (me["id"], k["hash"]), one=True):
            raise HTTPException(409, "You have a copy already.")
        self._ensure_tree(me)
        path = norm_path(b.path) if b.path.strip() else "/00-Inbox/Unprocessed"
        d = {x: v for x, v in json.loads(k["data"] or "{}").items() if x not in ("file", "processing", "published_from")}
        nid = self._new(me, k["type"] if k["type"] != "idea" else "note", k["title"], k["body"], d | {"shared_by": k["owner"]}, "shared", "page",
                        provenance={"source": f"shared by {k['owner']}", "by": k["owner"], "copied_by": me["username"], "copied": time.time()},
                        note=f"Copied from {k['owner']}'s shared item", path=path, ktype=k["ktype"], tags=k["tags"])
        self._audit(me, "copy", f"kb:{nid}", f"“{k['title']}” shared by {k['owner']}")
        return self.item(me, nid)
