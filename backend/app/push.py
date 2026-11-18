"""Push: AXoR's side of AXoR Push, the Web Push server in push/.

AXoR reaches the push server at PUSH_URL over the internal network with a shared secret (PUSH_SECRET, or the file
PUSH_SECRET_FILE that the push server writes on first start). Browsers subscribe through /api/push (the service
worker is frontend/sw.js) and never talk to the push server themselves.

Alerts (alerts.py) reach people as push notifications too: alerts raised close together (one chain pass) are
batched, and each user gets one push with what they'd see in the bell, filtered by their push settings: which kinds
to push, quiet hours in their own time zone, and at most `per_hour` pushes an hour. Admins can send an announcement
to everyone, to admins or to chosen users (sudo, audited), optionally posted to everyone's bell as well.
"""
import json, logging, os, re, threading, time, urllib.error, urllib.parse, urllib.request
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

log = logging.getLogger("push")
URL = (os.getenv("PUSH_URL") or "").rstrip("/")
KINDS = ("new_subnet", "emission", "opportunity", "fund", "news")
DEFAULT_PREFS = {"kinds": {"new_subnet": True, "emission": False, "opportunity": True, "fund": False, "news": True},
                 "announcements": True, "quiet": {"on": False, "start": "22:00", "end": "07:00"}, "tz": "UTC", "per_hour": 6}
BATCH_SECONDS = 8      # alerts raised within this window go out as one push
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

class PushError(Exception):
    def __init__(self, msg, status=502):
        super().__init__(msg); self.status = status

class Push:
    """Client for the push server."""
    def __init__(self, url=URL):
        self.url, self._secret = url, None

    @property
    def enabled(self): return bool(self.url)

    def secret(self):
        if self._secret is None:
            s = os.getenv("PUSH_SECRET")
            if not s and os.getenv("PUSH_SECRET_FILE"):
                try: s = Path(os.getenv("PUSH_SECRET_FILE")).read_text().strip()
                except OSError: s = None  # the push server hasn't written it yet: try again next call
            self._secret = s
        return self._secret

    def call(self, method, path, params=None, body=None, timeout=15):
        if not self.url: raise PushError("Push notifications aren't set up on this server (PUSH_URL).", 503)
        if not self.secret(): raise PushError("AXoR can't read the push server's secret yet (PUSH_SECRET / PUSH_SECRET_FILE).", 503)
        q = "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}) if params else ""
        h = {"Authorization": f"Bearer {self.secret()}"}
        data = None
        if body is not None: data, h["Content-Type"] = json.dumps(body).encode(), "application/json"
        try:
            with urllib.request.urlopen(urllib.request.Request(self.url + path + q, data=data, headers=h, method=method), timeout=timeout) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            try: detail = json.load(e).get("detail")
            except ValueError: detail = None
            if e.code == 401: self._secret = None  # the push server may have a new secret
            raise PushError(detail if isinstance(detail, str) else f"The push server answered HTTP {e.code}.", e.code if e.code < 500 else 502)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise PushError(f"The push server isn't reachable ({getattr(e, 'reason', e)}).", 503)
        return json.loads(raw) if raw else None

def device_name(ua):
    """'Chrome on Windows' from a User-Agent header."""
    ua = ua or ""
    browser = next((n for k, n in (("Edg/", "Edge"), ("OPR/", "Opera"), ("SamsungBrowser", "Samsung Internet"), ("Firefox/", "Firefox"),
                                    ("CriOS", "Chrome"), ("FxiOS", "Firefox"), ("Chrome/", "Chrome"), ("Safari/", "Safari")) if k in ua), "Browser")
    osn = next((n for k, n in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("CrOS", "ChromeOS"), ("Windows", "Windows"),
                                ("Mac OS X", "macOS"), ("Linux", "Linux")) if k in ua), "")
    return f"{browser} on {osn}" if osn else browser

def _minutes(hhmm):
    h, m = hhmm.split(":"); return int(h) * 60 + int(m)

class PrefsIn(BaseModel):
    kinds: dict[str, bool] | None = None
    announcements: bool | None = None
    quiet_on: bool | None = None
    quiet_start: str | None = Field(None, pattern=HHMM.pattern)
    quiet_end: str | None = Field(None, pattern=HHMM.pattern)
    tz: str | None = Field(None, max_length=64)
    per_hour: int | None = Field(None, ge=1, le=60)

class DeviceIn(BaseModel):
    endpoint: str = Field(max_length=2000)
    p256dh: str = Field(max_length=200)
    auth: str = Field(max_length=100)
    label: str = Field("", max_length=60)

class LabelIn(BaseModel):
    label: str = Field(max_length=60)

class BroadcastIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    body: str = Field("", max_length=1000)
    url: str = Field("", max_length=500)
    audience: str = Field("all", pattern="^(all|admins|users)$")
    users: list[int] = Field(default_factory=list, max_length=500)
    in_app: bool = False      # also post it to everyone's bell (audience "all" only)
    urgent: bool = False      # through quiet hours and the hourly cap

class Notifier:
    def __init__(self, db, client: Push, alerts):
        self.db, self.push, self.alerts = db, client, alerts
        self._pending, self._lock, self._timer = [], threading.Lock(), None
        self._recent = defaultdict(deque)  # user id -> times of recent pushes (the hourly cap)
        db.q("CREATE TABLE IF NOT EXISTS push_prefs (user_id INTEGER PRIMARY KEY, prefs TEXT)")

    # ---------- settings ----------
    def prefs(self, me):
        r = self.db.q("SELECT prefs FROM push_prefs WHERE user_id=?", (me["id"],), one=True)
        p = json.loads(r["prefs"]) if r else {}
        out = {**DEFAULT_PREFS, **p}
        out["kinds"] = {**DEFAULT_PREFS["kinds"], **p.get("kinds", {})}
        out["quiet"] = {**DEFAULT_PREFS["quiet"], **p.get("quiet", {})}
        return out

    def set_prefs(self, me, b: PrefsIn):
        p = self.prefs(me)
        if b.kinds is not None: p["kinds"].update({k: bool(v) for k, v in b.kinds.items() if k in KINDS})
        if b.announcements is not None: p["announcements"] = b.announcements
        if b.quiet_on is not None: p["quiet"]["on"] = b.quiet_on
        if b.quiet_start: p["quiet"]["start"] = b.quiet_start
        if b.quiet_end: p["quiet"]["end"] = b.quiet_end
        if b.tz:
            try: ZoneInfo(b.tz); p["tz"] = b.tz
            except (KeyError, ValueError): raise HTTPException(400, f"Unknown time zone {b.tz!r}.")
        if b.per_hour is not None: p["per_hour"] = b.per_hour
        self.db.q("INSERT OR REPLACE INTO push_prefs VALUES (?,?)", (me["id"], json.dumps(p)))
        return p

    def quiet_now(self, p, now=None):
        q = p["quiet"]
        if not q["on"]: return False
        try: tz = ZoneInfo(p["tz"])
        except (KeyError, ValueError): tz = ZoneInfo("UTC")
        t = datetime.fromtimestamp(now or time.time(), tz)
        m, a, b = t.hour * 60 + t.minute, _minutes(q["start"]), _minutes(q["end"])
        return a <= m < b if a <= b else m >= a or m < b  # 22:00–07:00 wraps past midnight

    def _room(self, uid, p, take=True):
        """Under the user's hourly cap (and count this push if so)."""
        d, now = self._recent[uid], time.time()
        while d and d[0] < now - 3600: d.popleft()
        if len(d) >= p["per_hour"]: return False
        if take: d.append(now)
        return True

    def _users(self, ids):
        if not ids: return {}
        rows = self.db.q(f"SELECT id, username, role, disabled FROM users WHERE id IN ({','.join('?' * len(ids))})", tuple(ids))
        return {r["id"]: r for r in rows}

    def send_user(self, uid, title, body, urgent=False, url="/", kind="system", tag=None):
        """One push to one user's devices, within their quiet hours and hourly cap unless urgent. False when it wasn't sent."""
        if not self.push.enabled: return False
        if uid not in set(self.push.call("GET", "/v1/users") or []): return False
        p = self.prefs({"id": uid})
        if not urgent and (self.quiet_now(p) or not self._room(uid, p)): return False
        self.push.call("POST", "/v1/send", body={"users": [uid], "urgency": "high" if urgent else "normal", "ttl": 6 * 3600, "topic": tag or kind,
                                                 "message": {"title": title[:120], "body": body[:300], "url": url, "kind": kind, "tag": tag or kind}})
        return True

    # ---------- alerts -> pushes ----------
    def on_alert(self, a):
        if not self.push.enabled or a["kind"] == "announcement": return  # announcements are pushed by broadcast()
        with self._lock:
            self._pending.append(a)
            if not self._timer:
                self._timer = threading.Timer(BATCH_SECONDS, self._flush); self._timer.daemon = True; self._timer.start()

    def _flush(self):
        with self._lock: batch, self._pending, self._timer = self._pending, [], None
        try: self.deliver_alerts(batch)
        except PushError as e: log.warning("alert pushes skipped: %s", e)
        except Exception: log.exception("alert pushes failed")

    def deliver_alerts(self, batch):
        ids = self.push.call("GET", "/v1/users") or []
        users = self._users(ids)
        for uid in ids:
            u = users.get(uid)
            if not u: self.push.call("DELETE", f"/v1/users/{uid}"); continue  # the account is gone: so are its devices
            if u["disabled"]: continue
            p = self.prefs(u)
            ok = self.alerts._visible(u)[0]
            mine = [a for a in batch if p["kinds"].get(a["kind"], False) and ok(a)]
            if not mine or self.quiet_now(p) or not self._room(uid, p): continue
            if len(mine) == 1:
                a = mine[0]
                msg = {"title": a["title"], "body": a.get("body") or "", "kind": a["kind"], "tag": f"alert-{a['kind']}",
                       "url": a.get("url") or (f"/#sn{a['netuid']}" if a.get("netuid") is not None else "/#notifications")}
            else:
                msg = {"title": f"{len(mine)} new notifications", "body": " · ".join(a["title"] for a in mine[:4]) + (" …" if len(mine) > 4 else ""),
                       "kind": "alerts", "tag": "alerts", "url": "/#notifications"}
            self.push.call("POST", "/v1/send", body={"users": [uid], "message": msg, "topic": "alerts", "ttl": 6 * 3600})

    # ---------- announcements ----------
    def broadcast(self, me, b: BroadcastIn):
        if b.audience == "users" and not b.users: raise HTTPException(400, "Pick at least one user.")
        if b.url and not (b.url.startswith("/") and not b.url.startswith("//") or re.match(r"^https?://", b.url)):
            raise HTTPException(400, "Links are a path in AXoR (/#drive) or an http(s) address.")
        ids = set(self.push.call("GET", "/v1/users") or [])
        users = self._users(list(ids))
        want = [u for u in users.values() if not u["disabled"] and
                (b.audience == "all" or (b.audience == "admins" and u["role"] == "admin") or (b.audience == "users" and u["id"] in b.users))]
        held = 0
        targets = []
        for u in want:
            p = self.prefs(u)
            if not p["announcements"] and not b.urgent: held += 1; continue
            if not b.urgent and (self.quiet_now(p) or not self._room(u["id"], p)): held += 1; continue
            targets.append(u["id"])
        res = {"devices": 0, "users": 0}
        if targets:
            res = self.push.call("POST", "/v1/send", body={
                "users": targets, "sender": me["username"], "urgency": "high" if b.urgent else "normal", "ttl": 3 * 86400,
                "message": {"title": b.title, "body": b.body, "url": b.url or "/#notifications", "kind": "announcement", "tag": f"announce-{int(time.time())}"}})
        if b.in_app and b.audience == "all":
            self.alerts.add("announcement", None, b.title, b.body, "info", key=f"announce:{time.time()}", url=b.url or None)
        return {**res, "held": held, "in_app": b.in_app and b.audience == "all"}

    def test(self, me, sub=None):
        p = self.prefs(me)
        msg = {"title": "Test notification from AXoR", "body": f"Push works{' on this device' if sub else ''}. Sent {datetime.now(ZoneInfo(p['tz'])).strftime('%H:%M')} your time.",
               "url": "/#notifications", "kind": "test", "tag": "test"}
        return self.push.call("POST", "/v1/send", body={"users": [me["id"]], "sub": sub, "message": msg, "urgency": "high", "ttl": 600})

def build(db, require, admin_state, ip, alerts):
    r = APIRouter(prefix="/api/push")
    admin, sudo = admin_state["admin"], admin_state["sudo"]
    client = Push()
    n = Notifier(db, client, alerts)
    r.state = {"notifier": n}

    def call(fn, *a, **k):
        try: return fn(*a, **k)
        except PushError as e: raise HTTPException(e.status, str(e))

    @r.get("")
    def overview(req: Request):
        me = require(req)
        out = {"enabled": client.enabled, "prefs": n.prefs(me), "devices": [], "public_key": None, "error": None,
               "quiet_now": n.quiet_now(n.prefs(me))}
        if not client.enabled: return {**out, "error": "Push notifications aren't set up on this server (PUSH_URL)."}
        try:
            out["public_key"] = client.call("GET", "/v1/info")["public_key"]
            out["devices"] = client.call("GET", "/v1/subs", {"user": me["id"]})
        except PushError as e: out["error"] = str(e)
        return out

    @r.put("/prefs")
    def set_prefs(b: PrefsIn, req: Request):
        return n.set_prefs(require(req), b)

    @r.put("/devices")
    def subscribe(b: DeviceIn, req: Request):
        me = require(req)
        ua = device_name(req.headers.get("user-agent"))
        return call(client.call, "PUT", "/v1/subs", body={"user": me["id"], "endpoint": b.endpoint, "p256dh": b.p256dh, "auth": b.auth,
                                                         "label": b.label.strip(), "ua": ua})

    @r.patch("/devices/{sid}")
    def rename(sid: int, b: LabelIn, req: Request):
        return call(client.call, "PATCH", f"/v1/subs/{sid}", {"user": require(req)["id"]}, {"label": b.label})

    @r.delete("/devices/{sid}")
    def remove(sid: int, req: Request):
        return call(client.call, "DELETE", f"/v1/subs/{sid}", {"user": require(req)["id"]})

    @r.post("/devices/{sid}/test")
    def test_one(sid: int, req: Request):
        return call(n.test, require(req), sid)

    @r.post("/test")
    def test_all(req: Request):
        return call(n.test, require(req))

    @r.get("/history")
    def history(req: Request, before: int | None = None, limit: int = 50):
        return call(client.call, "GET", "/v1/deliveries", {"user": require(req)["id"], "before": before, "limit": limit})

    # ---------- admins ----------
    @r.get("/admin")
    def server(req: Request):
        admin(req)
        info = call(client.call, "GET", "/v1/info")
        devices = call(client.call, "GET", "/v1/subs")
        names = n._users(list({d["user_id"] for d in devices}))
        for d in devices: d["username"] = (names.get(d["user_id"]) or {}).get("username", f"#{d['user_id']} (deleted)")
        users = db.q("SELECT id, username, role FROM users WHERE disabled=0 ORDER BY username")
        return {"info": info, "devices": devices, "messages": call(client.call, "GET", "/v1/messages", {"limit": 20})["items"], "users": users}

    @r.get("/admin/messages/{mid}")
    def message(mid: int, req: Request):
        admin(req)
        res = call(client.call, "GET", "/v1/deliveries", {"msg": mid, "limit": 200})
        names = n._users(list({d["user_id"] for d in res["items"]}))
        for d in res["items"]: d["username"] = (names.get(d["user_id"]) or {}).get("username", f"#{d['user_id']}")
        return res

    @r.post("/admin/broadcast")
    def broadcast(b: BroadcastIn, req: Request):
        me = sudo(req)
        res = call(n.broadcast, me, b)
        db.log("push.broadcast", me["username"], b.audience if b.audience != "users" else f"{len(b.users)} users", ip(req),
               f"{b.title[:80]} → {res['devices']} devices, {res['held']} held")
        return res

    @r.delete("/admin/devices/{sid}")
    def admin_remove(sid: int, req: Request):
        me = sudo(req)
        res = call(client.call, "DELETE", f"/v1/subs/{sid}")
        db.log("push.device.remove", me["username"], f"device {sid}", ip(req))
        return res

    return r

def fanout(*hooks):
    """One alerts.on_new hook that calls several (Slack, push)."""
    def run(a):
        for h in hooks:
            try: h(a)
            except Exception: log.exception("alert hook failed")
    return run
