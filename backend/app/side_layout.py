"""Sidebar layout (System → Sidebar layout; side-layout.js): which sidebar items show, and in what order, for administrators
in Simple mode ("simple") and for every account that isn't an administrator ("user": their only sidebar, one mode, no switch;
null falls back to "simple"). Advanced is the whole sidebar as index.html has it and is never stored.

One JSON blob in app_settings["sidebar_layout"]:
    {"simple": [entry, …] | null, "user": [entry, …] | null, "ts": …, "by": "<admin>"}
    entry = {"k": "<item key>", "on": true|false}   a sidebar item (its id, "v:<view>" or "a:<link>"), shown or hidden
          | {"h": "<heading text>"}                  a heading between items
null means "not set": that sidebar stays as it is. The server can't know the catalog (it lives in index.html), so it only
checks the shape. A list never grants access: an item the account may not open stays hidden whatever the list says.
Anyone signed in reads it (their sidebar draws from it); only administrators change it."""
import json, re, time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

KEY = "sidebar_layout"
LISTS = ("simple", "user")
MAX_ENTRIES = 200
KEY_RE = re.compile(r"^[A-Za-z0-9:_\-]{1,80}$")


def normalize(entries):
    """A list as it may be stored, or None for "not set". Raises ValueError with a message for the admin."""
    if entries is None: return None
    if not isinstance(entries, list): raise ValueError("A list must be a list of items.")
    if len(entries) > MAX_ENTRIES: raise ValueError(f"A list holds at most {MAX_ENTRIES} entries.")
    out, seen = [], set()
    for e in entries:
        if not isinstance(e, dict): raise ValueError("Each entry is an item or a heading.")
        if "h" in e:
            h = " ".join(str(e.get("h") or "").split())[:40]
            if h: out.append({"h": h})
            continue
        k = e.get("k")
        if not isinstance(k, str) or not KEY_RE.match(k): raise ValueError("An item has an invalid key.")
        if k in seen: continue  # an item appears once per list
        seen.add(k)
        out.append({"k": k, "on": e.get("on", True) is not False})
    return out


def load(db):
    try: d = json.loads(db.setting(KEY) or "{}")
    except (TypeError, ValueError): d = {}
    if not isinstance(d, dict): d = {}
    out = {"ts": d.get("ts"), "by": d.get("by") or ""}
    for n in LISTS:
        try: out[n] = normalize(d.get(n))
        except ValueError: out[n] = None  # a damaged list falls back to the normal sidebar
    return out


class Layout(BaseModel):
    simple: list | None = None
    user: list | None = None


def build(db, require, admin, ip):
    r = APIRouter(prefix="/api/sidebar-layout")

    @r.get("")
    def get(req: Request):
        """The saved Simple and User lists (null = not set: the normal sidebar)."""
        require(req)
        return load(db)

    @r.put("")
    def put(body: Layout, req: Request):
        """Replace both lists (null clears one). Administrators only."""
        me = admin(req)
        try: d = {n: normalize(getattr(body, n)) for n in LISTS}
        except ValueError as e: raise HTTPException(422, str(e))
        d.update(ts=time.time(), by=me["username"])
        db.setting(KEY, v=json.dumps(d))
        db.log("sidebar.layout", me["username"], "", ip(req),
               ", ".join(f"{n}: {'default' if d[n] is None else sum(1 for e in d[n] if e.get('on'))} shown" for n in LISTS))
        return load(db)

    return r
