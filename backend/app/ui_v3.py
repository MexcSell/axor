"""AXoR UI v3 support API (/api/ui/*), for the React front end at /app (docs/ui-v3/ROADMAP.md, U13).

Only what this branch can serve truthfully:
  GET  /api/ui/bootstrap               who is signed in, plus the resources below that the server really holds
  GET  /api/ui/preferences             this user's appearance (theme) preferences, or null
  PUT  /api/ui/preferences             replace them (validated like the front end's sanitizeAppearance)
  GET  /api/ui/settings                organisation UI settings: self-renewal, AI role assignment, notifications
  PUT  /api/ui/settings                change them; self-renewal and AI roles are administrator-only
  GET  /api/ui/news-sources            the news / research source URLs
  POST /api/ui/news-sources            add one (organisation scope: administrators; mission scope: anyone signed in)
  PATCH /api/ui/news-sources/{id}      rename, change cadence, enable / disable (owner or administrator)
  DELETE /api/ui/news-sources/{id}     remove (owner or administrator)

Missions, approvals and agent messages are NOT handled here: the UI reads and writes them through the existing hubs
(/api/control, /api/company, /api/mos; owner decision 4, frontend/react/src/v3/data/hub.ts).

Storage: JSON in app_settings (AuthDB.setting), like side_layout.py, so no migration is needed:
    ui_prefs:<username>  {"appearance": {...}, "ts": ..., "v": 1}
    ui_settings          {"self_renewal": bool, "ai_roles": {...}, "notifications": {...}, "ts": ..., "by": ...}
    ui_news_sources      [ {id, name, url, cadence, scope, mission_id, topics, enabled, added_by, ts}, ... ]
Source URLs are only stored here; fetching them is someone else's job, and it must re-check the address it resolves to.
"""
import ipaddress, json, math, re, secrets, threading, time
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

PREFS = "ui_prefs:"
SETTINGS = "ui_settings"
SOURCES = "ui_news_sources"
USER_SETTINGS = "ui_user_settings:"  # per-user notification preferences and quiet hours
MAX_SOURCES = 200

STYLES = ("luxury", "luminous", "classic", "flat", "pretty", "fancy", "sakura", "renaissance")
ENUMS = {
    "style": STYLES, "mode": ("light", "dark", "system"), "density": ("ultra", "compact", "comfortable"),
    "fontFamily": ("theme", "inter", "system", "serif", "mono"), "sidebar": ("expanded", "collapsed"),
    "iconShape": ("rounded", "circle", "square"), "motion": ("full", "subtle", "off"), "focusRing": ("standard", "bold"),
    "avatarPack": ("robots", "glyphs"), "iconSet": ("core", "outline", "duotone", "solid", "neotech"),
    "avatarFace": ("classic", "holographic", "expressive", "minimal", "analytical", "elite"),
    "avatarColor": ("role", "cyan", "purple", "green", "gold", "pink"),
}
DEFAULT_APPEARANCE = {"version": 1, "style": "luxury", "mode": "dark", "accent": None, "density": "compact", "fontScale": 100, "fontFamily": "theme",
                      "sidebar": "expanded", "iconShape": "rounded", "highContrast": False, "reducedMotion": False, "motion": "full",
                      "focusRing": "standard", "avatarPack": "robots", "glow": 85, "iconSet": "core", "avatarFace": "classic", "avatarColor": "role"}
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
# Settings and sources are read-modify-write JSON values: one lock per process serialises the writes (GPT review #1, P1).
# Several web replicas would still need a DB-level compare-and-swap; noted in docs/ui-v3/ROADMAP.md.
_WRITE = threading.Lock()
CADENCES = ("Every 30 min", "Hourly", "Every 6 h", "Daily", "Weekly")
AI_ROLE_KEYS = ("architecture", "code", "research", "creative")
AUTONOMY_LEVELS = ("L0", "L1", "L2", "L3", "L4", "L5")
TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
DEFAULT_SETTINGS = {
    "self_renewal": False,
    "autonomy": {"L0": True, "L1": True, "L2": True, "L3": True, "L4": False, "L5": False},
    "quiet_hours": False, "quiet_from": "22:00", "quiet_to": "07:00",
    "verification_provider": "Independent QA (internal)",
    "ai_roles": {"architecture": "GPT (ARC-01)", "code": "Claude Code (DEV agents)", "research": "GPT + Claude (joint synthesis)", "creative": "GPT proposes, Claude reviews"},
    "notifications": {"decisions": True, "failures": True, "releases": True, "digest": True},
}


def sanitize_appearance(x):
    """The stored form of an appearance object: unknown keys dropped, bad values replaced by defaults (never raises)."""
    o = x if isinstance(x, dict) else {}
    out = dict(DEFAULT_APPEARANCE)
    for k, allowed in ENUMS.items():
        if o.get(k) in allowed: out[k] = o[k]
    if isinstance(o.get("accent"), str) and HEX.match(o["accent"]): out["accent"] = o["accent"].lower()
    try:
        fs = float(o.get("fontScale"))
        if math.isfinite(fs): out["fontScale"] = int(min(120, max(90, round(fs))))
    except (TypeError, ValueError, OverflowError): pass
    try:
        g = float(o.get("glow"))
        if math.isfinite(g): out["glow"] = int(min(100, max(0, round(g))))
    except (TypeError, ValueError, OverflowError): pass
    for k in ("highContrast", "reducedMotion"): out[k] = o.get(k) is True
    return out


_BLOCKED_HOSTS = ("localhost", "localhost.localdomain", "metadata.google.internal")


def check_source_url(url):
    """A normalised http(s) URL that does not point at this machine or a private network, or ValueError with a reason.
    Literal addresses are checked here; whatever fetches the URL must still check the address the name resolves to."""
    if not isinstance(url, str) or not url.strip(): raise ValueError("Enter the source's address.")
    url = url.strip()
    if len(url) > 500: raise ValueError("That address is too long.")
    p = urlsplit(url)
    if p.scheme not in ("http", "https"): raise ValueError("Only http and https sources are allowed.")
    host = (p.hostname or "").lower().rstrip(".")
    if not host: raise ValueError("That address has no host name.")
    if p.username or p.password: raise ValueError("Addresses with a user name or password aren't allowed.")
    if host in _BLOCKED_HOSTS or host.endswith((".local", ".internal", ".localhost", ".svc", ".cluster.local")):
        raise ValueError("Private and internal addresses are blocked.")
    try: ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError: ip = None
    # Hosts like 127.1, 2130706433 or 0x7f000001 aren't valid ip_address() spellings but resolve to loopback: a host whose
    # last label isn't a name (digits or hex) must be a standard IP address.
    last = host.strip("[]").split(".")[-1]
    if ip is None and (re.fullmatch(r"[0-9]+", last) or re.fullmatch(r"0x[0-9a-f]*", last)):
        raise ValueError("Use a domain name or a standard IP address.")
    if ip is not None and (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
        raise ValueError("Private and internal addresses are blocked.")
    if p.port is not None and p.port not in (80, 443, 8080, 8443): raise ValueError("Only the standard web ports are allowed.")
    return p.geturl()


def _load_json(db, key, default):
    try: v = json.loads(db.setting(key) or "null")
    except (TypeError, ValueError): v = None
    return default if v is None else v


PERSONAL = ("notifications", "quiet_hours", "quiet_from", "quiet_to")


def load_settings(db, username=None):
    """Organisation settings, with the user's own notification preferences and quiet hours when a username is given."""
    d = _load_json(db, SETTINGS, {})
    if not isinstance(d, dict): d = {}
    d = {k: v for k, v in d.items() if k not in PERSONAL}  # personal fields never come from the organisation record (GPT review #3, #2)
    if username:
        p = _load_json(db, USER_SETTINGS + username, {})
        if isinstance(p, dict): d = {**d, **{k: p[k] for k in PERSONAL if k in p}}
    out = json.loads(json.dumps(DEFAULT_SETTINGS))
    if isinstance(d.get("self_renewal"), bool): out["self_renewal"] = d["self_renewal"]
    for k in AI_ROLE_KEYS:
        v = (d.get("ai_roles") or {}).get(k)
        if isinstance(v, str) and v.strip(): out["ai_roles"][k] = v.strip()[:80]
    for k in out["notifications"]:
        v = (d.get("notifications") or {}).get(k)
        if isinstance(v, bool): out["notifications"][k] = v
    for k in AUTONOMY_LEVELS:
        v = (d.get("autonomy") or {}).get(k)
        if isinstance(v, bool): out["autonomy"][k] = v
    out["autonomy"]["L0"] = True  # observing is always allowed
    if isinstance(d.get("quiet_hours"), bool): out["quiet_hours"] = d["quiet_hours"]
    for k in ("quiet_from", "quiet_to"):
        if isinstance(d.get(k), str) and TIME.match(d[k]): out[k] = d[k]
    if isinstance(d.get("verification_provider"), str) and d["verification_provider"].strip(): out["verification_provider"] = d["verification_provider"].strip()[:120]
    out["ts"], out["by"] = d.get("ts"), d.get("by") or ""
    return out


def load_sources(db):
    d = _load_json(db, SOURCES, [])
    return [s for s in d if isinstance(s, dict) and s.get("id") and s.get("url")] if isinstance(d, list) else []


def _public_source(s):
    return {"id": s["id"], "name": s.get("name") or "", "url": s["url"], "cadence": s.get("cadence") or "Daily", "scope": s.get("scope") or "organization",
            "missionId": s.get("mission_id"), "topics": s.get("topics") or [], "status": "ok" if s.get("enabled", True) else "disabled",
            "trust": s.get("trust", 50), "lastFetched": s.get("last_fetched"), "items": s.get("items", 0), "addedBy": s.get("added_by") or ""}


class PrefsBody(BaseModel):
    appearance: dict


class SettingsBody(BaseModel):
    selfRenewal: bool | None = None
    aiRoles: dict | None = None
    notifications: dict | None = None
    autonomy: dict | None = None
    quietHours: bool | None = None
    quietFrom: str | None = None
    quietTo: str | None = None
    verificationProvider: str | None = None


class SourceBody(BaseModel):
    url: str
    name: str = ""
    cadence: str = "Daily"
    scope: str = "organization"
    missionId: str | None = None
    topics: list = []


class SourcePatch(BaseModel):
    name: str | None = None
    cadence: str | None = None
    enabled: bool | None = None


def build(db, require, ip):
    r = APIRouter(prefix="/api/ui")

    def user(req):
        u = require(req)
        if not u: raise HTTPException(401, "Sign in first.")
        return u

    def is_admin(u): return (u or {}).get("role") == "admin"

    @r.get("/bootstrap")
    def bootstrap(req: Request):
        """Who is signed in and the resources the server really holds. Everything else stays sample data in the UI."""
        u = user(req)
        s = load_settings(db, u["username"])
        return {"me": {"name": u.get("username"), "role": "admin" if is_admin(u) else "member"},
                "resources": {"newsSources": [_public_source(x) for x in load_sources(db)]},
                "settings": {"selfRenewal": s["self_renewal"], "aiRoles": s["ai_roles"], "notifications": s["notifications"], "autonomy": s["autonomy"],
                             "quietHours": s["quiet_hours"], "quietFrom": s["quiet_from"], "quietTo": s["quiet_to"], "verificationProvider": s["verification_provider"]}}

    @r.get("/preferences")
    def get_prefs(req: Request):
        u = user(req)
        d = _load_json(db, PREFS + u["username"], None)
        return {"appearance": sanitize_appearance(d.get("appearance")) if isinstance(d, dict) else None, "ts": d.get("ts") if isinstance(d, dict) else None}

    @r.put("/preferences")
    def put_prefs(body: PrefsBody, req: Request):
        u = user(req)
        a = sanitize_appearance(body.appearance)
        db.setting(PREFS + u["username"], v=json.dumps({"appearance": a, "ts": time.time(), "v": 1}))
        return {"appearance": a}

    @r.get("/settings")
    def get_settings(req: Request):
        u = user(req)
        return load_settings(db, u["username"])

    @r.put("/settings")
    def put_settings(body: SettingsBody, req: Request):
        u = user(req)
        with _WRITE: return _put_settings(body, req, u)

    def _put_settings(body, req, u):
        cur = load_settings(db, u["username"])
        changed = []
        if body.selfRenewal is not None or body.aiRoles is not None or body.autonomy is not None or body.verificationProvider is not None:
            if not is_admin(u): raise HTTPException(403, "Only administrators change self-renewal, autonomy levels, verification and AI role assignment.")
        if body.selfRenewal is not None and body.selfRenewal != cur["self_renewal"]:
            cur["self_renewal"] = body.selfRenewal; changed.append(f"self-renewal {'on' if body.selfRenewal else 'off'}")
        if body.aiRoles is not None:
            for k, v in body.aiRoles.items():
                if k not in AI_ROLE_KEYS: raise HTTPException(422, f"Unknown AI role {k!r}.")
                if not isinstance(v, str) or not v.strip(): raise HTTPException(422, f"AI role {k!r} needs a value.")
                cur["ai_roles"][k] = v.strip()[:80]; changed.append(f"role {k}")
        if body.autonomy is not None:
            for k, v in body.autonomy.items():
                if k not in AUTONOMY_LEVELS or not isinstance(v, bool): raise HTTPException(422, f"Unknown autonomy level {k!r}.")
                if k == "L0" and not v: raise HTTPException(422, "L0 (observe) can't be switched off.")
                if cur["autonomy"].get(k) != v: cur["autonomy"][k] = v; changed.append(f"autonomy {k} {'on' if v else 'off'}")
        if body.verificationProvider is not None:
            v = body.verificationProvider.strip()
            if not v: raise HTTPException(422, "The verification provider needs a name.")
            cur["verification_provider"] = v[:120]; changed.append("verification provider")
        if body.quietHours is not None: cur["quiet_hours"] = body.quietHours; changed.append(f"quiet hours {'on' if body.quietHours else 'off'}")
        for k, v in (("quiet_from", body.quietFrom), ("quiet_to", body.quietTo)):
            if v is None: continue
            if not TIME.match(v): raise HTTPException(422, "Quiet hours use HH:MM.")
            cur[k] = v; changed.append(k.replace("_", " "))
        if body.notifications is not None:
            for k, v in body.notifications.items():
                if k in cur["notifications"] and isinstance(v, bool): cur["notifications"][k] = v; changed.append(f"notify {k}")
        cur.update(ts=time.time(), by=u["username"])
        org = load_settings(db)  # organisation part as stored, without this user's personal overrides
        for k in ("self_renewal", "ai_roles", "autonomy", "verification_provider"): org[k] = cur[k]
        org.update(ts=cur["ts"], by=cur["by"])
        db.setting(SETTINGS, v=json.dumps({k: org[k] for k in ("self_renewal", "ai_roles", "autonomy", "verification_provider", "ts", "by")}))
        db.setting(USER_SETTINGS + u["username"], v=json.dumps({k: cur[k] for k in PERSONAL}))
        if changed: db.log("ui.settings", u["username"], "", ip(req), ", ".join(changed)[:300])
        return load_settings(db, u["username"])

    @r.get("/news-sources")
    def list_sources(req: Request):
        user(req)
        return {"sources": [_public_source(x) for x in load_sources(db)]}

    @r.post("/news-sources")
    def add_source(body: SourceBody, req: Request):
        u = user(req)
        try: url = check_source_url(body.url)
        except ValueError as e: raise HTTPException(422, str(e))
        scope = body.scope if body.scope in ("organization", "mission") else "organization"
        if scope == "organization" and not is_admin(u): raise HTTPException(403, "Only administrators add organisation-wide sources; add it to a mission instead.")
        # mission refs as Mission Control uses them (comp:<id>, mx:<id>) or plain ids; ownership is not checked here (no access to the
        # Control hub from this router), the source is only a URL scoped to that ref
        if scope == "mission" and not (body.missionId and re.match(r"^(comp:\d{1,10}|mx:\d{1,10}|[A-Za-z0-9_\-]{1,40})$", body.missionId)): raise HTTPException(422, "A mission source needs its mission.")
        cadence = body.cadence if body.cadence in CADENCES else "Daily"
        topics = [str(t).strip()[:30] for t in (body.topics or []) if str(t).strip()][:10]
        with _WRITE: return _add_source(body, req, u, url, scope, cadence, topics)

    def _add_source(body, req, u, url, scope, cadence, topics):
        cur = load_sources(db)
        if any(s["url"] == url and s.get("mission_id") == (body.missionId if scope == "mission" else None) for s in cur): raise HTTPException(409, "This source is already registered.")
        if len(cur) >= MAX_SOURCES: raise HTTPException(422, f"At most {MAX_SOURCES} sources.")
        s = {"id": "src_" + secrets.token_hex(6), "name": (body.name or urlsplit(url).hostname or "")[:80], "url": url, "cadence": cadence, "scope": scope,
             "mission_id": body.missionId if scope == "mission" else None, "topics": topics, "enabled": True, "added_by": u["username"], "ts": time.time()}
        db.setting(SOURCES, v=json.dumps(cur + [s]))
        db.log("ui.news_source.add", u["username"], url[:200], ip(req), scope)
        return _public_source(s)

    def _find(sid, u):
        cur = load_sources(db)
        s = next((x for x in cur if x["id"] == sid), None)
        if not s: raise HTTPException(404, "No such source.")
        if not is_admin(u) and s.get("added_by") != u["username"]: raise HTTPException(403, "Only the person who added it or an administrator can change it.")
        return cur, s

    @r.patch("/news-sources/{sid}")
    def patch_source(sid: str, body: SourcePatch, req: Request):
        u = user(req)
        with _WRITE: return _patch_source(sid, body, req, u)

    def _patch_source(sid, body, req, u):
        cur, s = _find(sid, u)
        if body.name is not None: s["name"] = body.name.strip()[:80] or s["name"]
        if body.cadence is not None:
            if body.cadence not in CADENCES: raise HTTPException(422, "Unknown cadence.")
            s["cadence"] = body.cadence
        if body.enabled is not None: s["enabled"] = body.enabled
        db.setting(SOURCES, v=json.dumps(cur))
        db.log("ui.news_source.update", u["username"], s["url"][:200], ip(req), "")
        return _public_source(s)

    @r.delete("/news-sources/{sid}")
    def delete_source(sid: str, req: Request):
        u = user(req)
        with _WRITE:
            cur, s = _find(sid, u)
            db.setting(SOURCES, v=json.dumps([x for x in cur if x["id"] != sid]))
        db.log("ui.news_source.remove", u["username"], s["url"][:200], ip(req), "")
        return {"ok": True}

    return r
