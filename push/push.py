"""AXoR Push: AXoR's own Web Push server. It keeps the browsers' push subscriptions and this server's VAPID key pair
and delivers notifications to them, so alerts reach people whose AXoR tab is closed.

It runs as its own service (own container), like AXoR Drive. AXoR reaches it over a private network with a shared
secret (PUSH_SECRET, or the file PUSH_SECRET_FILE written on first start) and names the user it acts for; browsers
never talk to it. Nothing here depends on a third-party notification service beyond the browsers' own push services
(FCM for Chrome and Edge, Mozilla's for Firefox, Apple's for Safari), which every Web Push message has to pass through:
- Payloads are encrypted for the receiving browser (RFC 8291, aes128gcm), so the push services only see ciphertext,
  and every request is signed with this server's VAPID key (RFC 8292). The key pair is made on first start
  (PUSH_DATA/vapid.pem); replacing it ends every subscription.
- Subscriptions are only accepted for the push services in PUSH_HOSTS, over HTTPS, and each delivery checks that the
  host resolves to public addresses only, so a made-up endpoint can't point this server at internal hosts.
- Deliveries run on a small worker pool (PUSH_WORKERS) and retry rate limits and server errors twice. An endpoint the
  push service reports gone (404/410) is removed, and so is one that failed PUSH_MAX_FAILS times in a row.
- Every delivery is logged (PUSH_KEEP_DAYS) for the user's History and the admins' Server tab.
Run: PUSH_DATA=./var PUSH_SECRET_FILE=./var/push.key uvicorn push:app --port 8300
"""
import base64, fnmatch, hmac, ipaddress, json, logging, os, queue, secrets, socket, sqlite3, struct, threading, time
import urllib.error, urllib.parse, urllib.request
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("push")
DATA = Path(os.getenv("PUSH_DATA", Path(__file__).resolve().parent / "var"))
WORKERS = max(1, int(os.getenv("PUSH_WORKERS", "4")))
MAX_FAILS = max(1, int(os.getenv("PUSH_MAX_FAILS", "5")))
KEEP_DAYS = max(1, int(os.getenv("PUSH_KEEP_DAYS", "30")))
SUBJECT = os.getenv("PUSH_SUBJECT") or "mailto:admin@localhost"  # who push services contact about this sender
# push services of the major browsers; an entry with a scheme (http://127.0.0.1:9000) is one exact origin, for tests
HOSTS = [h.strip().lower() for h in (os.getenv("PUSH_HOSTS") or "fcm.googleapis.com,android.googleapis.com,jmt17.google.com,"
         "*.push.services.mozilla.com,*.notify.windows.com,*.push.apple.com").split(",") if h.strip()]
MAX_SUBS = 20         # devices per user
PAYLOAD_MAX = 3000    # bytes of JSON before encryption (the push services take 4096 with the encryption overhead)
DATA.mkdir(parents=True, exist_ok=True)

def load_secret():
    if os.getenv("PUSH_SECRET"): return os.getenv("PUSH_SECRET")
    path = Path(os.getenv("PUSH_SECRET_FILE", DATA / "push.key"))
    if not path.exists():  # first start: make one; AXoR reads the same file (a shared volume in docker-compose)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_urlsafe(32))
        os.chmod(path, 0o600)
    return path.read_text().strip()

SECRET = load_secret()

def b64u(b): return base64.urlsafe_b64encode(b).rstrip(b"=").decode()
def unb64u(s): return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

# ---------- VAPID key pair and request signing (RFC 8292) ----------
def load_vapid():
    path = DATA / "vapid.pem"
    if not path.exists():
        k = ec.generate_private_key(ec.SECP256R1())
        path.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        os.chmod(path, 0o600)
        log.info("made a new VAPID key pair")
    return serialization.load_pem_private_key(path.read_bytes(), None)

VAPID = load_vapid()
PUBLIC = VAPID.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
PUBLIC_B64 = b64u(PUBLIC)
_jwts, _jwt_lock = {}, threading.Lock()

def vapid_header(endpoint):
    """`Authorization: vapid t=<JWT>, k=<public key>` for the endpoint's origin; tokens are reused for an hour of their 12."""
    u = urllib.parse.urlsplit(endpoint)
    aud, now = f"{u.scheme}://{u.netloc}", int(time.time())
    with _jwt_lock:
        tok, exp = _jwts.get(aud, (None, 0))
        if exp - now < 11 * 3600:
            exp = now + 12 * 3600
            head = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
            body = b64u(json.dumps({"aud": aud, "exp": exp, "sub": SUBJECT}, separators=(",", ":")).encode())
            r, s = decode_dss_signature(VAPID.sign(f"{head}.{body}".encode(), ec.ECDSA(hashes.SHA256())))
            tok = f"{head}.{body}.{b64u(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
            _jwts[aud] = (tok, exp)
    return f"vapid t={tok}, k={PUBLIC_B64}"

# ---------- payload encryption (RFC 8291, one aes128gcm record) ----------
def _hkdf(salt, ikm, info, n):
    return HKDF(hashes.SHA256(), n, salt, info).derive(ikm)

def encrypt(p256dh, auth, plain):
    ua_pub, secret = unb64u(p256dh), unb64u(auth)
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_pub)
    eph = ec.generate_private_key(ec.SECP256R1())
    as_pub = eph.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    ikm = _hkdf(secret, eph.exchange(ec.ECDH(), ua_key), b"WebPush: info\x00" + ua_pub + as_pub, 32)
    salt = os.urandom(16)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    body = AESGCM(cek).encrypt(nonce, plain + b"\x02", None)  # 0x02: the last (and only) record, no padding
    return salt + struct.pack("!I", 4096) + bytes([len(as_pub)]) + as_pub + body

# ---------- where subscriptions may point ----------
def endpoint_ok(url, resolve=True):
    """None if the endpoint is a push service we deliver to, else why not."""
    try: u = urllib.parse.urlsplit(url)
    except ValueError: return "That isn't a URL."
    if not u.hostname or u.username or u.password: return "That isn't a push service address."
    host, origin = u.hostname.lower(), f"{u.scheme}://{u.netloc}".lower()
    if origin in HOSTS: return None  # an exact test origin
    if u.scheme != "https" or (u.port or 443) != 443: return "Push services are reached over HTTPS."
    if not any(fnmatch.fnmatchcase(host, h) for h in HOSTS if "://" not in h):
        return f"{host} isn't a push service this server delivers to (PUSH_HOSTS)."
    if resolve:
        try: addrs = {a[4][0] for a in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)}
        except OSError as e: return f"Can't resolve {host} ({e})."
        if not addrs or not all(ipaddress.ip_address(a.split("%")[0]).is_global for a in addrs):
            return f"{host} doesn't resolve to public addresses."
    return None

# ---------- storage ----------
class DB:
    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS subs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, endpoint TEXT UNIQUE NOT NULL,
              p256dh TEXT NOT NULL, auth TEXT NOT NULL, label TEXT DEFAULT '', ua TEXT DEFAULT '', created REAL, last_ok REAL,
              last_error TEXT DEFAULT '', last_error_ts REAL, fails INTEGER DEFAULT 0, sent INTEGER DEFAULT 0);
            CREATE INDEX IF NOT EXISTS subs_user ON subs(user_id);
            CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, title TEXT, body TEXT,
              url TEXT, sender TEXT DEFAULT '', targets INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS deliveries (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, msg_id INTEGER, sub_id INTEGER,
              user_id INTEGER, device TEXT, status TEXT, code INTEGER, detail TEXT DEFAULT '');
            CREATE INDEX IF NOT EXISTS deliveries_user ON deliveries(user_id, id);
            CREATE INDEX IF NOT EXISTS deliveries_msg ON deliveries(msg_id);
        """)

    def q(self, sql, args=(), one=False):
        with self.lock:
            cur = self.db.execute(sql, args)
            rows = [dict(r) for r in cur.fetchall()]
            self.db.commit()
            if sql.lstrip().upper().startswith("INSERT"): return cur.lastrowid
        return (rows[0] if rows else None) if one else rows

db = DB(DATA / "push.db")
STARTED = time.time()

# ---------- delivery ----------
JOBS = queue.Queue()

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None  # a 3xx is an answer, never a hop to another host

OPENER = urllib.request.build_opener(_NoRedirect)

def _post(sub, data, ttl, urgency, topic):
    h = {"TTL": str(ttl), "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream",
         "Authorization": vapid_header(sub["endpoint"]), "Urgency": urgency}
    if topic: h["Topic"] = topic
    req = urllib.request.Request(sub["endpoint"], data=data, headers=h, method="POST")
    try:
        with OPENER.open(req, timeout=15) as r: return r.status, "", None
    except urllib.error.HTTPError as e:
        try: detail = e.read(500).decode("utf-8", "replace").strip()
        except OSError: detail = ""
        return e.code, detail or e.reason or "", e.headers.get("Retry-After")

def deliver(msg, sub_id, ttl, urgency, topic):
    sub = db.q("SELECT * FROM subs WHERE id=?", (sub_id,), one=True)
    if not sub: return
    device = sub["label"] or sub["ua"] or "Device"
    def done(status, code=None, detail=""):
        db.q("INSERT INTO deliveries (ts, msg_id, sub_id, user_id, device, status, code, detail) VALUES (?,?,?,?,?,?,?,?)",
             (time.time(), msg["id"], sub_id, sub["user_id"], device, status, code, detail[:300]))
    why = endpoint_ok(sub["endpoint"])
    if why: return done("failed", None, why)
    payload = {k: msg[k] for k in ("title", "body", "url", "kind", "tag") if msg.get(k)}
    payload["id"], payload["ts"] = msg["id"], msg["ts"]
    raw = json.dumps(payload).encode()
    while len(raw) > PAYLOAD_MAX and payload.get("body"):
        payload["body"] = payload["body"][: len(payload["body"]) * 3 // 4] + "…"; raw = json.dumps(payload).encode()
    try: data = encrypt(sub["p256dh"], sub["auth"], raw)
    except (ValueError, TypeError) as e:
        db.q("DELETE FROM subs WHERE id=?", (sub_id,))
        return done("gone", None, f"The browser's keys are unusable ({e}); the device was removed.")
    for attempt in range(3):
        try: code, detail, retry = _post(sub, data, ttl, urgency, topic)
        except (urllib.error.URLError, OSError) as e: code, detail, retry = None, f"Couldn't reach the push service ({getattr(e, 'reason', e)}).", None
        if code and 200 <= code < 300:
            db.q("UPDATE subs SET last_ok=?, fails=0, sent=sent+1 WHERE id=?", (time.time(), sub_id))
            return done("sent", code)
        if code in (404, 410):  # the browser dropped the subscription
            db.q("DELETE FROM subs WHERE id=?", (sub_id,))
            return done("gone", code, "The browser ended this subscription; the device was removed.")
        if attempt < 2 and (code is None or code == 429 or code >= 500):
            try: wait = min(30, max(1, int(retry or 2 * 4 ** attempt)))
            except ValueError: wait = 5
            time.sleep(wait); continue
        break
    db.q("UPDATE subs SET fails=fails+1, last_error=?, last_error_ts=? WHERE id=?", (detail[:300] or f"HTTP {code}", time.time(), sub_id))
    if (db.q("SELECT fails FROM subs WHERE id=?", (sub_id,), one=True) or {"fails": 0})["fails"] >= MAX_FAILS:
        db.q("DELETE FROM subs WHERE id=?", (sub_id,))
        detail = (detail or f"HTTP {code}") + f" (removed after {MAX_FAILS} failures in a row)"
    done("failed", code, detail or f"HTTP {code}")

def worker():
    while True:
        job = JOBS.get()
        try: deliver(*job)
        except Exception: log.exception("delivery failed")
        finally: JOBS.task_done()

def prune():
    while True:
        cut = time.time() - KEEP_DAYS * 86400
        db.q("DELETE FROM deliveries WHERE ts < ?", (cut,))
        db.q("DELETE FROM messages WHERE ts < ? AND id NOT IN (SELECT DISTINCT msg_id FROM deliveries)", (cut,))
        time.sleep(3600)

for i in range(WORKERS): threading.Thread(target=worker, daemon=True, name=f"push-{i}").start()
threading.Thread(target=prune, daemon=True, name="prune").start()

# ---------- API ----------
app = FastAPI(title="AXoR Push", docs_url=None, redoc_url=None, openapi_url=None)

def auth(req: Request):
    if not hmac.compare_digest(req.headers.get("authorization", "").encode(), f"Bearer {SECRET}".encode()):
        raise HTTPException(401, "Unauthorized.")

class SubIn(BaseModel):
    user: int
    endpoint: str = Field(max_length=2000)
    p256dh: str = Field(max_length=200)
    auth: str = Field(max_length=100)
    label: str = Field("", max_length=60)
    ua: str = Field("", max_length=120)

class SubEdit(BaseModel):
    label: str = Field(max_length=60)

class Message(BaseModel):
    title: str = Field(max_length=200)
    body: str = Field("", max_length=2000)
    url: str = Field("", max_length=500)
    kind: str = Field("", max_length=40)
    tag: str = Field("", max_length=64)

class SendIn(BaseModel):
    users: list[int] | None = None   # None: every user with a device
    sub: int | None = None           # one device only (a test)
    message: Message
    sender: str = Field("", max_length=64)
    ttl: int = Field(86400, ge=0, le=28 * 86400)
    urgency: str = Field("normal", pattern="^(very-low|low|normal|high)$")
    topic: str = Field("", max_length=32, pattern="^[A-Za-z0-9_-]*$")  # a newer message with the same topic replaces an undelivered one

def _sub_out(s):
    return {k: s[k] for k in ("id", "user_id", "label", "ua", "created", "last_ok", "last_error", "last_error_ts", "fails", "sent")} | {
        "service": urllib.parse.urlsplit(s["endpoint"]).hostname, "endpoint_tail": s["endpoint"][-12:]}

def _mine(sid, user):
    s = db.q("SELECT * FROM subs WHERE id=?", (sid,), one=True)
    if not s or (user is not None and s["user_id"] != user): raise HTTPException(404, "No such device.")
    return s

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/v1/info", dependencies=[Depends(auth)])
def info():
    day = time.time() - 86400
    count = lambda st: db.q("SELECT COUNT(*) n FROM deliveries WHERE status=? AND ts>?", (st, day), one=True)["n"]
    services = db.q("SELECT endpoint FROM subs")
    by = {}
    for s in services:
        h = urllib.parse.urlsplit(s["endpoint"]).hostname or "?"
        by[h] = by.get(h, 0) + 1
    return {"public_key": PUBLIC_B64, "subject": SUBJECT, "hosts": HOSTS, "workers": WORKERS, "max_fails": MAX_FAILS,
            "keep_days": KEEP_DAYS, "started": STARTED, "queue": JOBS.qsize(),
            "devices": len(services), "users": db.q("SELECT COUNT(DISTINCT user_id) n FROM subs", one=True)["n"],
            "services": by, "sent_24h": count("sent"), "failed_24h": count("failed"), "gone_24h": count("gone"),
            "messages_24h": db.q("SELECT COUNT(*) n FROM messages WHERE ts>?", (day,), one=True)["n"]}

@app.get("/v1/users", dependencies=[Depends(auth)])
def users():
    return [r["user_id"] for r in db.q("SELECT DISTINCT user_id FROM subs")]

@app.get("/v1/subs", dependencies=[Depends(auth)])
def subs(user: int | None = None):
    rows = db.q("SELECT * FROM subs" + (" WHERE user_id=?" if user is not None else "") + " ORDER BY id", (user,) if user is not None else ())
    return [_sub_out(s) for s in rows]

@app.get("/v1/subs/find", dependencies=[Depends(auth)])
def find(user: int, endpoint: str):
    s = db.q("SELECT * FROM subs WHERE endpoint=? AND user_id=?", (endpoint, user), one=True)
    return _sub_out(s) if s else None

@app.put("/v1/subs", dependencies=[Depends(auth)])
def subscribe(b: SubIn):
    why = endpoint_ok(b.endpoint)
    if why: raise HTTPException(400, why)
    try:
        if len(unb64u(b.p256dh)) != 65 or len(unb64u(b.auth)) != 16: raise ValueError
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64u(b.p256dh))
    except (ValueError, TypeError): raise HTTPException(400, "The browser's subscription keys aren't valid.")
    old = db.q("SELECT * FROM subs WHERE endpoint=?", (b.endpoint,), one=True)
    if not old and db.q("SELECT COUNT(*) n FROM subs WHERE user_id=?", (b.user,), one=True)["n"] >= MAX_SUBS:
        raise HTTPException(400, f"You can have {MAX_SUBS} devices at most. Remove one first.")
    if old:  # the same browser again (maybe now signed in as someone else): it belongs to whoever subscribed last
        db.q("UPDATE subs SET user_id=?, p256dh=?, auth=?, label=?, ua=?, fails=0, last_error='' WHERE id=?",
             (b.user, b.p256dh, b.auth, b.label or old["label"], b.ua, old["id"]))
        sid = old["id"]
    else:
        sid = db.q("INSERT INTO subs (user_id, endpoint, p256dh, auth, label, ua, created) VALUES (?,?,?,?,?,?,?)",
                   (b.user, b.endpoint, b.p256dh, b.auth, b.label, b.ua, time.time()))
    return _sub_out(db.q("SELECT * FROM subs WHERE id=?", (sid,), one=True))

@app.patch("/v1/subs/{sid}", dependencies=[Depends(auth)])
def rename(sid: int, b: SubEdit, user: int | None = None):
    _mine(sid, user)
    db.q("UPDATE subs SET label=? WHERE id=?", (b.label.strip(), sid))
    return _sub_out(db.q("SELECT * FROM subs WHERE id=?", (sid,), one=True))

@app.delete("/v1/subs/{sid}", dependencies=[Depends(auth)])
def remove(sid: int, user: int | None = None):
    _mine(sid, user)
    db.q("DELETE FROM subs WHERE id=?", (sid,))
    return {"ok": True}

@app.delete("/v1/users/{uid}", dependencies=[Depends(auth)])
def forget(uid: int):
    n = db.q("SELECT COUNT(*) n FROM subs WHERE user_id=?", (uid,), one=True)["n"]
    db.q("DELETE FROM subs WHERE user_id=?", (uid,))
    return {"removed": n}

@app.post("/v1/send", dependencies=[Depends(auth)])
def send(b: SendIn):
    if b.sub is not None: targets = [_mine(b.sub, b.users[0] if b.users else None)]
    elif b.users is None: targets = db.q("SELECT * FROM subs")
    elif not b.users: targets = []
    else: targets = db.q(f"SELECT * FROM subs WHERE user_id IN ({','.join('?' * len(b.users))})", tuple(b.users))
    m = b.message.model_dump()
    m["ts"] = time.time()
    m["id"] = db.q("INSERT INTO messages (ts, kind, title, body, url, sender, targets) VALUES (?,?,?,?,?,?,?)",
                   (m["ts"], m["kind"], m["title"], m["body"], m["url"], b.sender, len(targets)))
    for s in targets: JOBS.put((m, s["id"], b.ttl, b.urgency, b.topic))
    return {"id": m["id"], "devices": len(targets), "users": len({s["user_id"] for s in targets})}

@app.get("/v1/deliveries", dependencies=[Depends(auth)])
def deliveries(user: int | None = None, msg: int | None = None, limit: int = 50, before: int | None = None):
    where, args = ["d.id < ?"], [before or 2 ** 62]
    if user is not None: where.append("d.user_id=?"); args.append(user)
    if msg is not None: where.append("d.msg_id=?"); args.append(msg)
    limit = max(1, min(limit, 200))
    rows = db.q(f"""SELECT d.id, d.ts, d.msg_id, d.sub_id, d.user_id, d.device, d.status, d.code, d.detail, m.kind, m.title, m.body, m.url, m.sender
                    FROM deliveries d LEFT JOIN messages m ON m.id = d.msg_id WHERE {' AND '.join(where)} ORDER BY d.id DESC LIMIT ?""",
                tuple(args) + (limit + 1,))
    return {"items": rows[:limit], "more": len(rows) > limit}

@app.get("/v1/messages", dependencies=[Depends(auth)])
def messages(limit: int = 30, before: int | None = None):
    limit = max(1, min(limit, 100))
    rows = db.q("""SELECT m.*, SUM(d.status='sent') sent, SUM(d.status='failed') failed, SUM(d.status='gone') gone
                   FROM messages m LEFT JOIN deliveries d ON d.msg_id = m.id WHERE m.id < ? GROUP BY m.id ORDER BY m.id DESC LIMIT ?""",
                (before or 2 ** 62, limit + 1))
    for r in rows: r["sent"], r["failed"], r["gone"] = r["sent"] or 0, r["failed"] or 0, r["gone"] or 0
    return {"items": rows[:limit], "more": len(rows) > limit}
