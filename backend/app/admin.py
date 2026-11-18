"""User administration.

Every route needs an admin session. Changes additionally need "sudo": a fresh authenticator code (or,
for admins without 2FA, their password), valid for 10 minutes on that session. Admins can't act on
themselves here, and the last active admin can't be demoted, disabled or deleted. Every change is audited.
Accounts that registered while approval is required wait as "pending" until an admin approves or rejects them.

`Admin` holds the operations so the HTTP routes and the user-administration agent share the same rules.
"""
import json, time

import pyotp
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .auth import METHODS, AuthDB, one_time_password, ph

SUDO_SECONDS = 600
USER_ACTIONS = ("approve", "reject", "promote", "demote", "unlock", "logout", "reset_password", "reset_2fa", "disable", "enable", "delete")

class Admin:
    def __init__(self, db: AuthDB, registration_open):
        self.db, self.registration_open = db, registration_open

    # ---------- reads ----------
    def users(self):
        now = time.time()
        rows = self.db.q("""SELECT u.id, u.username, u.email, u.role, u.disabled, u.totp_enabled, u.created, u.last_login,
                              u.last_ip, u.locked_until, u.must_change, u.recovery, u.approved,
                              CASE WHEN u.approved=0 THEN (SELECT a.ip FROM audit a WHERE a.action='register' AND a.target=u.username
                                                           ORDER BY a.ts DESC LIMIT 1) END signup_ip,
                              (SELECT COUNT(*) FROM sessions s WHERE s.user_id=u.id AND s.stage='full' AND s.expires>?) sessions
                            FROM users u ORDER BY u.created""", (now,))
        for x in rows:
            x["recovery_left"] = len(json.loads(x.pop("recovery") or "[]"))
            x["locked"] = x.pop("locked_until") > now
        return rows

    def stats(self, users=None):
        users = users if users is not None else self.users()
        now = time.time()
        count = lambda sql: self.db.q(sql, (now - 86400,), one=True)["n"]
        return {
            "users": len(users), "admins": sum(x["role"] == "admin" for x in users), "pending": sum(not x["approved"] for x in users),
            "with_2fa": sum(bool(x["totp_enabled"]) for x in users), "disabled": sum(bool(x["disabled"]) for x in users),
            "locked": sum(x["locked"] for x in users), "sessions": sum(x["sessions"] for x in users),
            "logins_24h": count("SELECT COUNT(*) n FROM audit WHERE action='login.ok' AND ts>?"),
            "fails_24h": count("SELECT COUNT(*) n FROM audit WHERE action IN ('login.fail','mfa.fail') AND ts>?"),
        }

    def audit(self, q="", limit=200, since=0.0):
        like = f"%{q}%"
        return self.db.q("""SELECT ts, actor, action, target, ip, detail FROM audit
                            WHERE ts >= ? AND (? = '' OR actor LIKE ? OR target LIKE ? OR action LIKE ? OR ip LIKE ?)
                            ORDER BY ts DESC LIMIT ?""", (since, q, like, like, like, like, max(1, min(int(limit), 1000))))

    # ---------- changes (caller must have verified admin + sudo) ----------
    def act(self, me, target_id, action, ip, via="admin"):
        t = self.db.q("SELECT * FROM users WHERE id=?", (target_id,), one=True)
        if not t: raise HTTPException(404, "User not found.")
        if action not in USER_ACTIONS: raise HTTPException(400, "Unknown action.")
        if (action in ("approve", "reject")) == bool(t["approved"]):
            raise HTTPException(400, "This account isn't waiting for approval." if t["approved"] else "Approve or reject this account first.")
        active_admins = self.db.q("SELECT COUNT(*) n FROM users WHERE role='admin' AND disabled=0", one=True)["n"]
        if action in ("disable", "delete", "demote", "reset_2fa", "reset_password") and t["id"] == me["id"]:
            raise HTTPException(400, "You can't do that to your own account here. Use the account menu instead.")
        if action in ("disable", "delete", "demote") and t["role"] == "admin" and not t["disabled"] and active_admins <= 1:
            raise HTTPException(400, "This is the last active administrator. Make someone else an admin first.")
        kill = lambda: self.db.q("DELETE FROM sessions WHERE user_id=?", (t["id"],))
        out = {"ok": True, "username": t["username"], "action": action}
        if action == "approve":
            self.db.q("UPDATE users SET approved=1 WHERE id=?", (t["id"],))
        elif action == "reject":
            kill(); self.db.q("DELETE FROM users WHERE id=?", (t["id"],))
        elif action == "disable":
            self.db.q("UPDATE users SET disabled=1 WHERE id=?", (t["id"],)); kill()
        elif action == "enable":
            self.db.q("UPDATE users SET disabled=0, fails=0, locked_until=0 WHERE id=?", (t["id"],))
        elif action == "unlock":
            self.db.q("UPDATE users SET fails=0, locked_until=0 WHERE id=?", (t["id"],))
        elif action == "logout":
            kill()
        elif action == "promote":
            if self.db.auth_method() == "2fa" and not t["totp_enabled"]:
                raise HTTPException(400, "The user must finish two-factor setup before becoming an admin.")
            self.db.q("UPDATE users SET role='admin' WHERE id=?", (t["id"],))
        elif action == "demote":
            self.db.q("UPDATE users SET role='user' WHERE id=?", (t["id"],))
        elif action == "reset_2fa":
            self.db.q("UPDATE users SET totp_enabled=0, totp_secret=?, totp_last=0, recovery='[]' WHERE id=?",
                      (pyotp.random_base32(32), t["id"])); kill()
        elif action == "reset_password":
            pw = one_time_password()
            self.db.q("UPDATE users SET pw_hash=?, must_change=1, fails=0, locked_until=0 WHERE id=?", (ph.hash(pw), t["id"])); kill()
            out["temp_password"] = pw
        elif action == "delete":
            kill(); self.db.q("DELETE FROM users WHERE id=?", (t["id"],))
        self.db.log("admin." + action, me["username"], t["username"], ip, via)
        return out

    def set_registration(self, me, open_, ip, via="admin"):
        self.db.setting("registration", v="1" if open_ else "0")
        self.db.log("registration." + ("open" if open_ else "closed"), me["username"], "", ip, via)
        return {"registration_open": bool(open_)}

    def set_approval(self, me, required, ip, via="admin"):
        self.db.setting("registration_approval", v="1" if required else "0")
        self.db.log("approval." + ("on" if required else "off"), me["username"], "", ip, via)
        return {"approval_required": bool(required)}

    def set_auth_method(self, me, method, ip, via="admin"):
        if method not in METHODS: raise HTTPException(400, "Unknown sign-in method.")
        self.db.setting("auth_method", v=method)
        self.db.log("auth_method." + method, me["username"], "", ip, via)
        return {"auth_method": method}

class Code(BaseModel):
    code: str = ""
    password: str = ""

class Action(BaseModel):
    action: str

class RegToggle(BaseModel):
    open: bool

class ApprovalToggle(BaseModel):
    required: bool

class Method(BaseModel):
    method: str

def build(db: AuthDB, helpers):
    r = APIRouter(prefix="/api/admin")
    require, ip, check_totp, check_password = (helpers[k] for k in ("require", "ip", "check_totp", "check_password"))
    ops = Admin(db, helpers["registration_open"])

    def admin(req):
        u = require(req)
        if u["role"] != "admin": raise HTTPException(403, "Administrators only.")
        return u

    def sudo(req):
        u = admin(req)
        if (u["_session"]["sudo_until"] or 0) < time.time():
            raise HTTPException(403, "SUDO_REQUIRED")
        return u

    @r.post("/sudo")
    def enter_sudo(c: Code, req: Request):
        u = admin(req)
        ok = check_totp(u, c.code) if u["totp_enabled"] else check_password(u, c.password)
        if not ok:
            db.log("sudo.fail", u["username"], "", ip(req))
            raise HTTPException(400, "Invalid authenticator code." if u["totp_enabled"] else "Incorrect password.")
        db.q("UPDATE sessions SET sudo_until=? WHERE hash=?", (time.time() + SUDO_SECONDS, u["_session"]["hash"]))
        db.log("sudo", u["username"], "", ip(req))
        return {"sudo_until": time.time() + SUDO_SECONDS}

    @r.get("/overview")
    def overview(req: Request):
        u = admin(req)
        users = ops.users()
        for x in users: x["you"] = x["id"] == u["id"]
        return {"users": users, "stats": ops.stats(users), "registration_open": ops.registration_open(),
                "approval_required": db.approval_required(),
                "auth_method": db.auth_method(), "sudo_until": u["_session"]["sudo_until"] or 0}

    @r.get("/audit")
    def audit(req: Request, q: str = "", limit: int = 200):
        admin(req)
        return ops.audit(q, limit)

    @r.post("/registration")
    def registration(t: RegToggle, req: Request):
        return ops.set_registration(sudo(req), t.open, ip(req))

    @r.post("/approval")
    def approval(t: ApprovalToggle, req: Request):
        return ops.set_approval(sudo(req), t.required, ip(req))

    @r.post("/auth-method")
    def auth_method(m: Method, req: Request):
        return ops.set_auth_method(sudo(req), m.method, ip(req))

    @r.post("/users/{uid}")
    def act(uid: int, a: Action, req: Request):
        return ops.act(sudo(req), uid, a.action, ip(req))

    r.state = {"ops": ops, "admin": admin, "sudo": sudo}
    return r
