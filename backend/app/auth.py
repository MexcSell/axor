"""Accounts and sign-in.

- Accounts have a username (email optional); sign in with either.
- Sign-in method is chosen by an administrator:
    basic - username + password
    2fa   - username + password + authenticator code (TOTP, RFC 6238), mandatory for everyone
  Under "basic", users may still turn on 2FA themselves, and anyone who has it is always asked for it.
- Approval: while an administrator requires it (the default), self-registered accounts can't sign in until
  an administrator approves them; accounts that existed before, or were made by an admin, are approved.
- Passwords: Argon2id hashes, a length/variety policy, a common-password blocklist and an optional
  Have I Been Pwned k-anonymity check (only the first 5 hex chars of the SHA-1 leave the server).
- 2FA: replay-protected TOTP plus 10 one-time recovery codes (stored as SHA-256 hashes).
- Sessions: 256-bit random tokens, stored hashed; HttpOnly + SameSite=Strict cookies (Secure on HTTPS);
  7-day absolute and 24h idle expiry; rotated after each authentication step.
- Abuse limits: per-IP rate limits and per-account lockout after repeated failures; sign-in answers
  never reveal whether an account exists.
"""
import contextlib, hashlib, json, logging, os, re, secrets, sqlite3, string, threading, time, urllib.request
from collections import defaultdict, deque

import pyotp
import qrcode, qrcode.image.svg
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

ISSUER = "AXoR"
# Cookies ignore ports: a second instance on the same host (e.g. a plain-HTTP dev
# server next to production's HTTPS) needs its own name, or the browser refuses to
# let it overwrite production's Secure cookie and every sign-in silently fails.
COOKIE = os.getenv("SESSION_COOKIE", "scout_session")
FULL_TTL, IDLE_TTL, STEP_TTL = 7 * 86400, 86400, 600
PENDING_TTL = FULL_TTL  # a new account waiting for approval: its browser signs in once an admin approves (never longer than a full session)
MAX_FAILS, LOCK_SECONDS, MAX_MFA_TRIES = 5, 900, 5
METHODS = ("basic", "2fa")
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[A-Za-z]{2,}$")
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,31}$")
COMMON = set("""password password1 password12 password123 password1234 passw0rd p@ssw0rd p@ssword 123456 1234567 12345678
123456789 1234567890 12345678910 qwerty qwerty123 qwertyuiop 1q2w3e4r 1q2w3e4r5t 1qaz2wsx zaq12wsx abc123 abcd1234
111111 000000 123123 654321 iloveyou admin admin123 administrator welcome welcome1 welcome123 letmein monkey dragon
football baseball soccer master shadow sunshine princess trustno1 starwars superman batman freedom whatever
bittensor bittensor123 subnetscout changeme changeme123 secret secret123 login hello123 test1234 testtest""".split())

ph = PasswordHasher()  # argon2id, library defaults (64 MiB, t=3, p=4)
_DUMMY = ph.hash(secrets.token_hex(16))
log = logging.getLogger("auth")

USERS_DDL = """CREATE TABLE {name} (
  id INTEGER PRIMARY KEY, username TEXT UNIQUE COLLATE NOCASE NOT NULL, email TEXT UNIQUE COLLATE NOCASE,
  pw_hash TEXT NOT NULL, totp_secret TEXT, totp_enabled INTEGER DEFAULT 0, totp_last INTEGER DEFAULT 0,
  recovery TEXT DEFAULT '[]', fails INTEGER DEFAULT 0, locked_until REAL DEFAULT 0, created REAL,
  settings TEXT DEFAULT '{{}}', role TEXT DEFAULT 'user', disabled INTEGER DEFAULT 0, last_login REAL,
  last_ip TEXT, must_change INTEGER DEFAULT 0, approved INTEGER DEFAULT 1)"""
USER_COLS = ("id username email pw_hash totp_secret totp_enabled totp_last recovery fails locked_until created "
             "settings role disabled last_login last_ip must_change").split()

def slug_username(s):
    u = re.sub(r"[^a-z0-9_.-]", "", s.split("@")[0].lower()).lstrip("_.-")[:32]
    return u if len(u) >= 3 else (u + "user")[:32]

def edit_reason(reason):
    """The reason a person gives for changing an agent's configuration: required (K-22), one line, at most 300 characters."""
    r = " ".join((reason or "").split())
    if len(r) < 3: raise HTTPException(422, "Say why you're changing it: a change to what an agent does needs a reason.")
    return r[:300]


class AuthDB:
    def __init__(self, path):
        from . import db_pg  # 5.1: DATABASE_URL=postgresql://… moves this database to Postgres (db_pg.py); unset = SQLite as before
        if db_pg.enabled():
            self.db = db_pg.connect(path)
        else:
            self.db = sqlite3.connect(path, check_same_thread=False)
            try: os.chmod(path, 0o600)
            except OSError: pass
        # re-entrant: a transaction (tx) holds it across its statements, and q() inside it runs on the same thread
        self.lock, self._tx_thread = threading.RLock(), None
        with self.lock:
            self._migrate()

    def _migrate(self):
        cols = [r[1] for r in self.db.execute("PRAGMA table_info(users)")]
        if not cols:
            self.db.execute(USERS_DDL.format(name="users"))
        elif "username" not in cols:
            # v1 -> v2: email-keyed accounts become username-keyed (email kept, now optional)
            for col, ddl in (("role", "TEXT DEFAULT 'user'"), ("disabled", "INTEGER DEFAULT 0"), ("last_login", "REAL"),
                             ("last_ip", "TEXT"), ("must_change", "INTEGER DEFAULT 0")):
                if col not in cols: self.db.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")
            self.db.execute(USERS_DDL.format(name="users_v2"))
            taken = set()
            old = [c for c in USER_COLS if c != "username"]
            for row in self.db.execute(f"SELECT {', '.join(old)} FROM users ORDER BY id").fetchall():
                rec = dict(zip(old, row))
                base = name = slug_username(rec["email"]); n = 2
                while name in taken: name = f"{base[:29]}{n}"; n += 1
                taken.add(name)
                rec["username"] = name
                self.db.execute(f"INSERT INTO users_v2 ({', '.join(USER_COLS)}) VALUES ({','.join('?' * len(USER_COLS))})",
                                [rec[c] for c in USER_COLS])
            self.db.execute("DROP TABLE users")
            self.db.execute("ALTER TABLE users_v2 RENAME TO users")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
              hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, stage TEXT NOT NULL, created REAL, last_seen REAL,
              expires REAL, tries INTEGER DEFAULT 0, ip TEXT, ua TEXT, sudo_until REAL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
            CREATE TABLE IF NOT EXISTS audit (
              id INTEGER PRIMARY KEY, ts REAL, actor TEXT, action TEXT, target TEXT, ip TEXT, detail TEXT);
            CREATE INDEX IF NOT EXISTS audit_ts ON audit(ts);
            CREATE TABLE IF NOT EXISTS app_settings (k TEXT PRIMARY KEY, v TEXT);""")
        if "sudo_until" not in [r[1] for r in self.db.execute("PRAGMA table_info(sessions)")]:
            self.db.execute("ALTER TABLE sessions ADD COLUMN sudo_until REAL DEFAULT 0")
        if "approved" not in [r[1] for r in self.db.execute("PRAGMA table_info(users)")]:
            self.db.execute("ALTER TABLE users ADD COLUMN approved INTEGER DEFAULT 1")  # existing accounts stay approved
        self.db.commit()

    def q(self, sql, args=(), one=False):
        with self.lock:
            try: cur = self.db.execute(sql, args)
            except sqlite3.Error:
                # Outside tx() only. SQLite opens a write transaction before a failing INSERT / UPDATE (a unique-index violation,
                # say) and keeps it open, which blocks every other connection's writes until this one is used again. Nothing else is
                # pending there (each call commits), so rolling back drops only the failed statement; on Postgres (db_pg, autocommit
                # outside a transaction) it's a no-op. Inside tx() the transaction's own statements are pending: a rollback here would
                # drop them and let the block's later statements commit on their own (on both engines), so the error just propagates
                # and tx() rolls back the whole block (D-004 integration with G5-2.2).
                if self._tx_thread != threading.get_ident(): self.db.rollback()
                raise
            cols = [c[0] for c in cur.description] if cur.description else []
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            if self._tx_thread != threading.get_ident(): self.db.commit()  # inside tx(): the transaction commits once, at its end
        return (rows[0] if rows else None) if one else rows

    TX_LOCK = 0x41584F52  # the advisory lock every tx() takes on Postgres ("AXOR"): transactions serialise across connections
    TX_WAIT = 10          # seconds a tx() waits for another's lock before it fails (SQLite's own busy timeout is 5 s)

    @contextlib.contextmanager
    def tx(self):
        """One all-or-nothing transaction (G5-2.2 Milestone 3, budget reservations): q() calls on this thread inside the block run in
        it and commit together at the end; an exception rolls all of them back and propagates. It serialises against every other
        tx() on the database, from this process or another: SQLite takes the write lock up front (BEGIN IMMEDIATE), Postgres an
        advisory transaction lock, so a read-check-write inside it can't interleave with another one's. Other threads of this process
        wait on the connection's lock for its length, so the block is kept short. A nested tx() on the same thread joins the outer one.
        A Postgres connection lost inside it is never reconnected into the middle of it: the statement raises (db_pg)."""
        with self.lock:
            if self._tx_thread == threading.get_ident():
                yield self; return
            pg = hasattr(self.db, "begin")
            if pg: self.db.begin(self.TX_LOCK, self.TX_WAIT)
            else: self.db.execute("BEGIN IMMEDIATE")
            self._tx_thread = threading.get_ident()
            try:
                yield self
            except BaseException:
                self._tx_thread = None
                try: self.db.rollback()
                except Exception as e:  # noqa: BLE001 - the original error is the one to raise
                    log.warning("tx rollback: %s", e)
                raise
            self._tx_thread = None
            try: self.db.commit()
            except BaseException:
                try: self.db.rollback()
                except Exception: pass  # noqa: BLE001
                raise

    def log(self, action, actor="", target="", ip="", detail=""):
        self.q("INSERT INTO audit(ts,actor,action,target,ip,detail) VALUES (?,?,?,?,?,?)",
               (time.time(), actor, action, target, ip, str(detail)[:300]))

    def agent_edit(self, actor, target, store, reason, previous, new, rollback, changed, ip="", values=None, evidence=""):
        """A person's direct change to an agent's configuration (K-22, G5-5 L5.4b part A): one `agent.edit` audit row with the author
        (actor), the reason, the version it replaced, the version it wrote, the reference that undoes it through the agent's own
        version store, the fields changed and, if given, the evidence it rests on. A manual edit is never an improvement: nothing
        here is measured, verified or promoted. The detail is JSON and is written whole (log() would cut it at 300 characters)."""
        d = {"reason": edit_reason(reason), "store": store, "previous_version": previous, "new_version": new, "rollback": rollback,
             "changed": sorted(changed)}
        if values: d["values"] = {k: [str(a if a is not None else "")[:400], str(b if b is not None else "")[:400]] for k, (a, b) in values.items()}
        if (evidence or "").strip(): d["evidence"] = " ".join(evidence.split())[:300]
        self.q("INSERT INTO audit(ts,actor,action,target,ip,detail) VALUES (?,?,?,?,?,?)",
               (time.time(), actor, "agent.edit", target, ip, json.dumps(d, sort_keys=True)))

    def setting(self, k, default=None, v=None):
        if v is None:
            r = self.q("SELECT v FROM app_settings WHERE k=?", (k,), one=True)
            return r["v"] if r else default
        self.q("INSERT OR REPLACE INTO app_settings VALUES (?,?)", (k, str(v)))

    def auth_method(self):
        m = self.setting("auth_method", os.getenv("AUTH_METHOD", "2fa"))
        return m if m in METHODS else "2fa"

    def approval_required(self):
        """New self-registered accounts wait for an administrator's approval."""
        return self.setting("registration_approval", os.getenv("REGISTRATION_APPROVAL", "1")) == "1"

    def find(self, login):
        """Account by username or email."""
        login = (login or "").strip().lower()
        return self.q("SELECT * FROM users WHERE username=? OR email=?", (login, login), one=True)

    def create_admin(self, login, password=None, actor="server shell"):
        """Create (or upgrade) an admin account with a one-time password; first sign-in forces a password
        change (and authenticator setup when the sign-in method is 2fa). Returns (username, password)."""
        login = login.strip().lower()
        email = login if "@" in login else None
        if email and not EMAIL_RE.match(email): raise ValueError(f"Not a valid email: {login}")
        username = slug_username(login) if email else login
        if not USERNAME_RE.match(username): raise ValueError("Usernames are 3-32 characters: a-z, 0-9, _ . -")
        pw = password or one_time_password()
        if password and password_problems(password, username): raise ValueError(" ".join(password_problems(password, username)))
        u = self.find(login) or (self.find(username) if email else None)
        if u:
            self.q("UPDATE users SET role='admin', pw_hash=?, must_change=1, disabled=0, approved=1, fails=0, locked_until=0 WHERE id=?",
                   (ph.hash(pw), u["id"]))
            self.q("DELETE FROM sessions WHERE user_id=?", (u["id"],))
            username = u["username"]
        else:
            self.q("INSERT INTO users(username,email,pw_hash,totp_secret,created,role,must_change) VALUES (?,?,?,?,?, 'admin', 1)",
                   (username, email, ph.hash(pw), pyotp.random_base32(32), time.time()))
        self.log("admin.created", actor, username)
        return username, pw

    def bootstrap_admin(self):
        """INIT_ADMIN_USERNAME / INIT_ADMIN_EMAIL: create the first admin at start-up when there is none."""
        login = (os.getenv("INIT_ADMIN_USERNAME") or os.getenv("INIT_ADMIN_EMAIL") or "").strip()
        if not login or self.q("SELECT 1 FROM users WHERE role='admin'", one=True):
            return
        try:
            name, pw = self.create_admin(login, os.getenv("INIT_ADMIN_PASSWORD") or None, actor="INIT_ADMIN")
        except ValueError as e:  # a bad setting shouldn't take the whole site down
            log.error("INIT_ADMIN not created: %s", e)
            return
        if not os.getenv("INIT_ADMIN_PASSWORD"):
            log.warning("Initial admin %s created. One-time password: %s  (sign in, then choose a new password)", name, pw)

    def promote_env_admins(self):
        """ADMIN_EMAILS (usernames or emails, comma-separated) are made admins at start-up."""
        for login in filter(None, (x.strip() for x in os.getenv("ADMIN_EMAILS", "").split(","))):
            u = self.find(login)
            if u and u["role"] != "admin":
                self.q("UPDATE users SET role='admin', approved=1 WHERE id=?", (u["id"],))
                self.log("role.admin", "ADMIN_EMAILS", u["username"])

# ---------- helpers ----------
def one_time_password():
    a = string.ascii_letters + string.digits
    core = "".join(secrets.choice(a) for _ in range(16))
    return f"{core[:8]}-{core[8:]}#{secrets.randbelow(90) + 10}"

def _h(token): return hashlib.sha256(token.encode()).hexdigest()

def password_problems(pw, name=""):
    p = []
    if len(pw) < 12: p.append("Use at least 12 characters.")
    if len(pw) > 128: p.append("Use at most 128 characters.")
    classes = sum(bool(re.search(rx, pw)) for rx in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]"))
    if len(pw) < 16 and classes < 3: p.append("Mix at least 3 of: lowercase, uppercase, digits, symbols (or use 16+ characters).")
    low = pw.lower()
    if low in COMMON or re.sub(r"[\d!@#$%^&*.]+$", "", low) in COMMON: p.append("This is a commonly used password.")
    local = (name or "").split("@")[0].lower()
    if len(local) >= 4 and local in low: p.append("Don't include your username in the password.")
    if re.search(r"(.)\1{3,}", pw): p.append("Avoid repeating the same character 4+ times.")
    if len(set(pw)) < 6: p.append("Use more distinct characters.")
    return p

def pwned_count(pw):
    """Have I Been Pwned range query (k-anonymity). Returns None when unavailable."""
    if os.getenv("HIBP_CHECK", "1") != "1": return None
    sha = hashlib.sha1(pw.encode()).hexdigest().upper()
    try:
        req = urllib.request.Request(f"https://api.pwnedpasswords.com/range/{sha[:5]}",
                                     headers={"User-Agent": "subnet-scout", "Add-Padding": "true"})
        body = urllib.request.urlopen(req, timeout=4).read().decode()
    except Exception:
        return None
    for line in body.splitlines():
        suf, _, n = line.partition(":")
        if suf == sha[5:]: return int(n)
    return 0

class RateLimiter:
    def __init__(self): self.hits, self.lock = defaultdict(deque), threading.Lock()
    def check(self, key, limit, window):
        from . import bus  # 5.1: with REDIS_URL every AXoR server shares these limits; Redis errors fall back to this process's
        shared = bus.hit(":".join(map(str, key if isinstance(key, tuple) else (key,))), limit, window)
        if shared is not None:
            if not shared[0]: raise HTTPException(429, f"Too many attempts. Try again in {shared[1]}s.")
            return
        now = time.time()
        with self.lock:
            d = self.hits[key]
            while d and d[0] < now - window: d.popleft()
            if len(d) >= limit:
                raise HTTPException(429, f"Too many attempts. Try again in {int(d[0] + window - now) + 1}s.")
            d.append(now)

# ---------- router ----------
class Login(BaseModel):
    login: str
    password: str

class Register(BaseModel):
    username: str
    password: str
    email: str | None = None

class PwCheck(BaseModel):
    password: str
    username: str = ""

class Code(BaseModel):
    code: str

class PendingIn(BaseModel):
    claim: bool = True  # False: only report "approved" (the certificate window shows first); True: sign in

class PwChange(BaseModel):
    current: str
    new: str
    code: str = ""

def build(db: AuthDB):
    r = APIRouter(prefix="/api/auth")
    rl = RateLimiter()
    db.bootstrap_admin()
    db.promote_env_admins()

    def registration_open():
        return db.setting("registration", os.getenv("ALLOW_REGISTRATION", "1")) == "1"

    def ip(req): return req.client.host if req.client else "?"

    def secure(req): return req.url.scheme == "https" or os.getenv("COOKIE_SECURE") == "1"

    def new_session(req, resp, uid, stage):
        tok = secrets.token_urlsafe(32)
        now = time.time()
        ttl = FULL_TTL if stage == "full" else PENDING_TTL if stage == "pending" else STEP_TTL
        db.q("INSERT INTO sessions(hash,user_id,stage,created,last_seen,expires,ip,ua) VALUES (?,?,?,?,?,?,?,?)",
             (_h(tok), uid, stage, now, now, now + ttl, ip(req), req.headers.get("user-agent", "")[:200]))
        resp.set_cookie(COOKIE, tok, max_age=ttl, httponly=True, samesite="strict", secure=secure(req), path="/")
        old = req.cookies.get(COOKIE)
        if old: db.q("DELETE FROM sessions WHERE hash=?", (_h(old),))  # rotate

    def signed_in(req, resp, u, how):
        new_session(req, resp, u["id"], "full")
        db.q("UPDATE users SET last_login=?, last_ip=? WHERE id=?", (time.time(), ip(req), u["id"]))
        db.log("login.ok", u["username"], u["username"], ip(req), how)

    def session(req, stage=None):
        tok = req.cookies.get(COOKIE)
        if not tok: return None
        s = db.q("SELECT * FROM sessions WHERE hash=?", (_h(tok),), one=True)
        now = time.time()
        if not s or s["expires"] < now or (s["stage"] == "full" and now - s["last_seen"] > IDLE_TTL):
            if s: db.q("DELETE FROM sessions WHERE hash=?", (s["hash"],))
            return None
        if stage and s["stage"] != stage: return None
        if s["stage"] == "full" and now - s["last_seen"] > 60:
            db.q("UPDATE sessions SET last_seen=? WHERE hash=?", (now, s["hash"]))
        return s

    def user(uid): return db.q("SELECT * FROM users WHERE id=?", (uid,), one=True)

    def totp_payload(u, stage="setup"):
        uri = pyotp.TOTP(u["totp_secret"]).provisioning_uri(name=u["username"], issuer_name=ISSUER)
        svg = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2).to_string().decode()
        return {"stage": stage, "otpauth": uri, "secret": u["totp_secret"], "qr_svg": svg}

    def check_totp(u, code):
        """Valid TOTP in a ±30 s window that hasn't been used before (replay protection)."""
        code = re.sub(r"\s", "", code or "")
        if not u["totp_enabled"] and u["totp_secret"] is None: return False
        if not re.fullmatch(r"\d{6}", code): return False
        t = pyotp.TOTP(u["totp_secret"])
        now = int(time.time()) // 30
        last = db.q("SELECT totp_last FROM users WHERE id=?", (u["id"],), one=True)["totp_last"]
        for step in (now - 1, now, now + 1):
            if step > last and secrets.compare_digest(t.at(step * 30), code):
                db.q("UPDATE users SET totp_last=? WHERE id=?", (step, u["id"]))
                return True
        return False

    def check_password(u, pw):
        try: return ph.verify(u["pw_hash"], pw or "")
        except (VerificationError, InvalidHashError): return False

    def use_recovery(u, code):
        h = _h(re.sub(r"[\s-]", "", code).upper())
        codes = json.loads(u["recovery"])
        if h in codes:
            codes.remove(h)
            db.q("UPDATE users SET recovery=? WHERE id=?", (json.dumps(codes), u["id"]))
            return True
        return False

    def new_recovery(uid):
        codes = ["-".join(secrets.token_hex(5).upper()[i:i + 5] for i in (0, 5)) for _ in range(10)]
        db.q("UPDATE users SET recovery=? WHERE id=?", (json.dumps([_h(c.replace("-", "")) for c in codes]), uid))
        return codes

    def require(req):
        s = session(req, "full")
        if not s: raise HTTPException(401, "Sign in required.")
        u = user(s["user_id"])
        if not u or u["disabled"] or not u["approved"]:
            db.q("DELETE FROM sessions WHERE hash=?", (s["hash"],))
            raise HTTPException(401, "This account is disabled." if u and u["approved"] else "This account is waiting for approval.")
        if u["must_change"] and not req.url.path.startswith(("/api/auth/password", "/api/auth/logout")):
            raise HTTPException(403, "Change your temporary password first.")
        u["_session"] = s
        return u

    @r.get("/config")
    def config():
        """Public: what the sign-in screen needs to know."""
        return {"auth_method": db.auth_method(), "registration_open": registration_open(), "approval_required": db.approval_required()}

    @r.get("/me")
    def me(req: Request):
        s = session(req)
        if not s: return {"authenticated": False, "auth_method": db.auth_method()}
        u = user(s["user_id"])
        if s["stage"] != "full":
            out = {"authenticated": False, "stage": s["stage"], "username": u["username"]}
            if s["stage"] == "setup": out.update(totp_payload(u))
            return out
        return {"authenticated": True, "username": u["username"], "email": u["email"], "created": u["created"],
                "role": u["role"], "must_change": bool(u["must_change"]), "totp_enabled": bool(u["totp_enabled"]),
                "auth_method": db.auth_method(), "registration_open": registration_open(), "approval_required": db.approval_required(),
                "recovery_left": len(json.loads(u["recovery"])), "settings": json.loads(u["settings"] or "{}")}

    @r.post("/password-check")
    def pw_check(c: PwCheck, req: Request):
        rl.check(("pwcheck", ip(req)), 30, 60)
        probs = password_problems(c.password, c.username)
        n = pwned_count(c.password) if not probs else None
        if n: probs.append(f"This password appeared in {n:,} known data breaches.")
        return {"problems": probs}

    @r.post("/register")
    def register(c: Register, req: Request, resp: Response):
        rl.check(("register", ip(req)), 5, 3600)
        if not registration_open(): raise HTTPException(403, "Registration is closed. Ask an administrator for an account.")
        username = c.username.strip().lower()
        email = (c.email or "").strip().lower() or None
        if not USERNAME_RE.match(username):
            raise HTTPException(400, "Usernames are 3-32 characters: lowercase letters, digits, _ . - (starting with a letter or digit).")
        if email and (not EMAIL_RE.match(email) or len(email) > 254): raise HTTPException(400, "Enter a valid email address or leave it empty.")
        probs = password_problems(c.password, username)
        if not probs and (pwned_count(c.password) or 0) > 0:
            probs.append("This password appeared in known data breaches. Choose another.")
        if probs: raise HTTPException(400, " ".join(probs))
        if db.q("SELECT 1 FROM users WHERE username=? OR (email IS NOT NULL AND email=?) OR email=?", (username, email, username), one=True):
            raise HTTPException(400, "That username or email is already taken.")
        pending = db.approval_required()
        db.q("INSERT INTO users(username,email,pw_hash,totp_secret,created,approved) VALUES (?,?,?,?,?,?)",
             (username, email, ph.hash(c.password), pyotp.random_base32(32), time.time(), 0 if pending else 1))
        db.log("register", username, username, ip(req), "awaiting approval" if pending else "")
        u = db.find(username)
        if pending:  # a "pending" session opens nothing; /pending turns it into a sign-in once an administrator approves
            new_session(req, resp, u["id"], "pending")
            return {"stage": "pending", "username": username}
        if db.auth_method() == "basic":
            signed_in(req, resp, u, "registered")
            return {"stage": "done"}
        new_session(req, resp, u["id"], "setup")
        return totp_payload(u)

    @r.post("/pending")
    def pending_check(req: Request, resp: Response, c: PendingIn | None = None):
        """The "Request sent" screen polls this with claim=false: "approved" opens the certificate window, whose OK claims.
        Claiming an approved account → the same next step as a password sign-in (done, 2FA setup or code)."""
        rl.check(("pending", ip(req)), 120, 60)
        s = session(req, "pending")
        u = s and user(s["user_id"])
        if not u or u["disabled"]:  # rejected (account and sessions deleted), expired, or disabled
            if s: db.q("DELETE FROM sessions WHERE hash=?", (s["hash"],))
            return {"stage": "gone"}
        if not u["approved"]: return {"stage": "pending", "username": u["username"]}
        if c is not None and not c.claim: return {"stage": "approved", "username": u["username"]}  # the pending session stays (7 days)
        if u["totp_enabled"]:
            new_session(req, resp, u["id"], "mfa")
            return {"stage": "mfa"}
        if db.auth_method() == "2fa":
            new_session(req, resp, u["id"], "setup")
            return totp_payload(u)
        signed_in(req, resp, u, "approved")
        return {"stage": "done"}

    @r.post("/register/verify")
    def register_verify(c: Code, req: Request, resp: Response):
        rl.check(("verify", ip(req)), 10, 300)
        s = session(req, "setup")
        if not s: raise HTTPException(401, "Setup expired. Sign in again to continue.")
        u = user(s["user_id"])
        if not check_totp(u, c.code):
            db.q("UPDATE sessions SET tries=tries+1 WHERE hash=?", (s["hash"],))
            if s["tries"] + 1 >= MAX_MFA_TRIES: db.q("DELETE FROM sessions WHERE hash=?", (s["hash"],))
            raise HTTPException(400, "That code didn't match. Check your phone's clock and try the newest code.")
        db.q("UPDATE users SET totp_enabled=1 WHERE id=?", (u["id"],))
        db.log("2fa.enabled", u["username"], u["username"], ip(req))
        codes = new_recovery(u["id"])
        signed_in(req, resp, u, "authenticator setup")
        return {"recovery_codes": codes}

    @r.post("/login")
    def login(c: Login, req: Request, resp: Response):
        rl.check(("login", ip(req)), 10, 300)
        login_name = c.login.strip().lower()
        rl.check(("login-acct", login_name), 20, 3600)
        u = db.find(login_name)
        bad = HTTPException(401, "Incorrect username or password.")
        if not u:
            check_password({"pw_hash": _DUMMY}, c.password)  # same work either way: no account enumeration by timing
            db.log("login.fail", login_name, login_name, ip(req), "unknown account")
            raise bad
        if u["locked_until"] > time.time():
            raise HTTPException(423, f"Too many failed attempts. Account locked for {int(u['locked_until'] - time.time()) // 60 + 1} more minute(s).")
        if not check_password(u, c.password):
            fails = u["fails"] + 1
            db.log("login.fail", u["username"], u["username"], ip(req), "wrong password" + (" - locked" if fails >= MAX_FAILS else ""))
            db.q("UPDATE users SET fails=?, locked_until=? WHERE id=?",
                 (0 if fails >= MAX_FAILS else fails, time.time() + LOCK_SECONDS if fails >= MAX_FAILS else 0, u["id"]))
            raise bad
        if u["disabled"]:
            db.log("login.blocked", u["username"], u["username"], ip(req), "account disabled")
            raise HTTPException(403, "This account is disabled. Contact an administrator.")
        if not u["approved"]:
            db.log("login.blocked", u["username"], u["username"], ip(req), "awaiting approval")
            raise HTTPException(403, "Your account is waiting for an administrator's approval. Try again once you've heard back.")
        db.q("UPDATE users SET fails=0 WHERE id=?", (u["id"],))
        if ph.check_needs_rehash(u["pw_hash"]):
            db.q("UPDATE users SET pw_hash=? WHERE id=?", (ph.hash(c.password), u["id"]))
        if u["totp_enabled"]:                      # anyone with 2FA is always asked for it
            new_session(req, resp, u["id"], "mfa")
            return {"stage": "mfa"}
        if db.auth_method() == "2fa":              # 2FA required but not set up yet
            new_session(req, resp, u["id"], "setup")
            return totp_payload(u)
        signed_in(req, resp, u, "password")        # basic: username + password
        return {"stage": "done"}

    @r.post("/mfa")
    def mfa(c: Code, req: Request, resp: Response):
        rl.check(("mfa", ip(req)), 10, 300)
        s = session(req, "mfa")
        if not s: raise HTTPException(401, "Sign-in expired. Enter your password again.")
        u = user(s["user_id"])
        used_recovery = False
        ok = check_totp(u, c.code)
        if not ok and len(re.sub(r"[\s-]", "", c.code)) == 10:
            ok = used_recovery = use_recovery(u, c.code)
        if not ok:
            db.log("mfa.fail", u["username"], u["username"], ip(req))
            db.q("UPDATE sessions SET tries=tries+1 WHERE hash=?", (s["hash"],))
            if s["tries"] + 1 >= MAX_MFA_TRIES:
                db.q("DELETE FROM sessions WHERE hash=?", (s["hash"],))
                raise HTTPException(401, "Too many wrong codes. Enter your password again.")
            raise HTTPException(400, "Invalid code.")
        signed_in(req, resp, u, "recovery code" if used_recovery else "authenticator")
        return {"ok": True}

    @r.post("/2fa/setup")
    def twofa_setup(req: Request):
        """Signed-in user turns on 2FA voluntarily (when the method is basic)."""
        u = require(req)
        if u["totp_enabled"]: raise HTTPException(400, "Two-factor authentication is already on.")
        db.q("UPDATE users SET totp_secret=?, totp_last=0 WHERE id=?", (pyotp.random_base32(32), u["id"]))
        return totp_payload(user(u["id"]), stage="enroll")

    @r.post("/2fa/enable")
    def twofa_enable(c: Code, req: Request):
        rl.check(("verify", ip(req)), 10, 300)
        u = require(req)
        if u["totp_enabled"]: raise HTTPException(400, "Two-factor authentication is already on.")
        if not check_totp(u, c.code): raise HTTPException(400, "That code didn't match. Try the newest code.")
        db.q("UPDATE users SET totp_enabled=1 WHERE id=?", (u["id"],))
        db.log("2fa.enabled", u["username"], u["username"], ip(req))
        return {"recovery_codes": new_recovery(u["id"])}

    @r.post("/logout")
    def logout(req: Request, resp: Response):
        tok = req.cookies.get(COOKIE)
        if tok: db.q("DELETE FROM sessions WHERE hash=?", (_h(tok),))
        resp.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    @r.post("/logout-all")
    def logout_all(req: Request, resp: Response):
        u = require(req)
        db.q("DELETE FROM sessions WHERE user_id=?", (u["id"],))
        resp.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    @r.post("/password")
    def change_password(c: PwChange, req: Request, resp: Response):
        rl.check(("pwchange", ip(req)), 5, 900)
        u = require(req)
        if not check_password(u, c.current): raise HTTPException(400, "Current password is incorrect.")
        if u["totp_enabled"] and not check_totp(u, c.code): raise HTTPException(400, "Invalid authenticator code.")
        probs = password_problems(c.new, u["username"])
        if c.new == c.current: probs.append("Choose a password different from the current one.")
        if not probs and (pwned_count(c.new) or 0) > 0: probs.append("This password appeared in known data breaches.")
        if probs: raise HTTPException(400, " ".join(probs))
        db.q("UPDATE users SET pw_hash=?, must_change=0 WHERE id=?", (ph.hash(c.new), u["id"]))
        db.q("DELETE FROM sessions WHERE user_id=?", (u["id"],))  # sign out everywhere
        db.log("password.changed", u["username"], u["username"], ip(req))
        new_session(req, resp, u["id"], "full")
        return {"ok": True}

    @r.post("/recovery-codes")
    def regen(c: Code, req: Request):
        rl.check(("regen", ip(req)), 5, 900)
        u = require(req)
        if not u["totp_enabled"]: raise HTTPException(400, "Turn on two-factor authentication first.")
        if not check_totp(u, c.code): raise HTTPException(400, "Invalid authenticator code.")
        return {"recovery_codes": new_recovery(u["id"])}

    @r.put("/settings")
    async def put_settings(req: Request):
        u = require(req)
        body = await req.json()
        allowed = {k: body[k] for k in ("theme", "accent", "unit", "profile") if k in body}
        cur = json.loads(u["settings"] or "{}"); cur.update(allowed)
        raw = json.dumps(cur)
        if len(raw) > 8000: raise HTTPException(400, "Settings too large.")
        db.q("UPDATE users SET settings=? WHERE id=?", (raw, u["id"]))
        return {"ok": True}

    r.state = {"require": require, "ip": ip, "check_totp": check_totp, "check_password": check_password,
               "registration_open": registration_open}
    return r, require
