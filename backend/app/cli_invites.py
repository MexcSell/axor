"""Connect requests: an administrator asks teammates to connect their own Claude Code / Codex (cli_accounts.py).

The admin does the setting up: picks the people and the CLIs, sends the request, sees who is connected, asked, has seen it,
declined or let it expire, reminds or cancels, and removes logins when someone leaves. The member does the one thing only
they may do: connect their own login (their click starts their own Codex device sign-in; they paste their own
`claude setup-token` token). Nothing here touches a login, a token or a device code, and nothing an admin does here makes
a call on a member's plan: the request is a row and a notification, never a credential.

Done is not stored: a request is answered once that person has a login for that CLI (then its row goes). Requests expire
after TTL days; asking again starts a fresh one. Members can be asked only when Agents are open to members (the hub's
gate), or they couldn't reach My logins at all."""
import logging, threading, time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import cli_accounts as ca, push

log = logging.getLogger("cli_invites")
TTL = 14 * 86400
REMIND_EVERY = 3600  # one reminder an hour per request, at most
LINK = "/#agents/logins"
S = {"db": None, "push": None}


def init(db):
    S["db"] = db
    db.q("""CREATE TABLE IF NOT EXISTS cli_invites (user_id INTEGER, provider TEXT, by_uid INTEGER, created REAL, seen REAL,
            reminded REAL, declined REAL, PRIMARY KEY (user_id, provider))""")
    if S["push"] is None: S["push"] = push.Push()


def members_allowed():
    return S["db"].setting("agents_for_members", "0") == "1"


def _tidy():
    """Requests that are answered (the person has a working login for it now) or whose person is gone, go. A login that
    stopped working can be asked about again: that request goes once it works again (reconnected, or Test passes)."""
    S["db"].q("""DELETE FROM cli_invites WHERE user_id NOT IN (SELECT id FROM users)
                 OR EXISTS (SELECT 1 FROM cli_accounts a WHERE a.user_id = cli_invites.user_id AND a.provider = cli_invites.provider
                            AND a.ok = 1)""")


def working(uid, p):
    return bool(S["db"].q("SELECT 1 FROM cli_accounts WHERE user_id=? AND provider=? AND ok=1", (uid, p), one=True))


def _state(r, now=None):
    if r["declined"]: return "declined"
    if (now or time.time()) > r["created"] + TTL: return "expired"
    return "asked"


def _send(uid, providers, by_name, again=False):
    """A push to the person's devices, when push is set up (best effort, off the request thread)."""
    c = S["push"]
    if not c or not c.enabled: return
    names = " and ".join(ca.NAMES[p] for p in providers)
    msg = {"title": f"{'Reminder: c' if again else 'C'}onnect your {names}",
           "body": f"{by_name} asked you to connect your own {names} so agents run on your own plan. It takes a minute.",
           "url": LINK, "kind": "cli_invite", "tag": f"cli-invite-{uid}"}
    def go():
        try: c.call("POST", "/v1/send", body={"users": [uid], "message": msg, "ttl": 3 * 86400})
        except Exception as e: log.info("connect request push skipped: %s", e)
    threading.Thread(target=go, daemon=True).start()


# ---------- the admin's side ----------
def ask(by, uids, providers):
    """Ask each of `uids` to connect each of `providers`. Returns who was asked and who wasn't, with why."""
    providers = [p for p in dict.fromkeys(providers) if p in ca.NAMES]
    if not providers: raise HTTPException(400, "Pick Claude Code, Codex or both.")
    if not uids: raise HTTPException(400, "Pick at least one person.")
    db, now, allowed = S["db"], time.time(), members_allowed()
    asked, skipped = [], []
    for uid in dict.fromkeys(uids):
        u = db.q("SELECT id, username, role, disabled, approved FROM users WHERE id=?", (uid,), one=True)
        if not u: skipped.append({"user_id": uid, "username": "", "why": "No such account."}); continue
        why = ("The account is disabled." if u["disabled"] else "The account is waiting for sign-up approval." if u["approved"] == 0
               else "Agents are for administrators only, so they can't open My logins. Open Agents to members in Agents → Models first."
               if u["role"] != "admin" and not allowed else None)
        if why: skipped.append({"user_id": uid, "username": u["username"], "why": why}); continue
        mine = []
        for p in providers:
            if working(uid, p):
                skipped.append({"user_id": uid, "username": u["username"], "provider": p, "why": f"Already connected their {ca.NAMES[p]}."}); continue
            r = db.q("SELECT * FROM cli_invites WHERE user_id=? AND provider=?", (uid, p), one=True)
            if r and _state(r, now) == "asked":  # asked already: asking again is a reminder, with the same hourly limit
                if now - (r["reminded"] or r["created"]) < REMIND_EVERY:
                    skipped.append({"user_id": uid, "username": u["username"], "provider": p,
                                    "why": f"Already asked about {ca.NAMES[p]} within the hour."}); continue
                db.q("UPDATE cli_invites SET reminded=?, seen=NULL WHERE user_id=? AND provider=?", (now, uid, p))
            else:
                db.q("""INSERT INTO cli_invites (user_id, provider, by_uid, created, seen, reminded, declined) VALUES (?,?,?,?,NULL,NULL,NULL)
                        ON CONFLICT(user_id, provider) DO UPDATE SET by_uid=excluded.by_uid, created=excluded.created, seen=NULL,
                        reminded=NULL, declined=NULL""", (uid, p, by["id"], now))
            mine.append(p)
        if mine:
            asked.append({"user_id": uid, "username": u["username"], "providers": mine})
            _send(uid, mine, by["username"])
    return {"asked": asked, "skipped": skipped}


def remind(by, uid, p):
    r = S["db"].q("SELECT * FROM cli_invites WHERE user_id=? AND provider=?", (uid, p), one=True)
    if not r: raise HTTPException(404, "There's no request to remind about. Ask them again.")
    if _state(r) != "asked": raise HTTPException(400, "That request was declined or has expired: ask them again instead.")
    if r["reminded"] and time.time() - r["reminded"] < REMIND_EVERY:
        raise HTTPException(429, "You reminded them less than an hour ago.")
    S["db"].q("UPDATE cli_invites SET reminded=?, seen=NULL WHERE user_id=? AND provider=?", (time.time(), uid, p))
    _send(uid, [p], by["username"], again=True)


def cancel(uid, p):
    S["db"].q("DELETE FROM cli_invites WHERE user_id=? AND provider=?", (uid, p))


def team():
    """Everyone with an account and, for each CLI: connected (and working), asked, declined, expired or nothing. Never a
    token or a device code."""
    _tidy()
    db, now = S["db"], time.time()
    accts = {(r["user_id"], r["provider"]): r for r in db.q("SELECT user_id, provider, connected, checked, ok, error FROM cli_accounts")}
    inv = {(r["user_id"], r["provider"]): r for r in db.q(
        "SELECT i.*, b.username AS by_name FROM cli_invites i LEFT JOIN users b ON b.id = i.by_uid")}
    allowed, people = members_allowed(), []
    for u in db.q("SELECT id, username, role, disabled, approved FROM users ORDER BY disabled, lower(username)"):
        row = {"user_id": u["id"], "username": u["username"], "role": u["role"], "disabled": bool(u["disabled"]),
               "pending_approval": u["approved"] == 0, "can_use": u["role"] == "admin" or allowed, "providers": {}}
        for p in ca.NAMES:
            a, i = accts.get((u["id"], p)), inv.get((u["id"], p))
            if a:
                cell = {"state": "connected" if a["ok"] else "not_working", "connected": a["connected"], "checked": a["checked"],
                        "error": None if a["ok"] else a["error"]}
                if i and not a["ok"] and _state(i, now) == "asked": cell["invite"] = {"asked": i["created"], "seen": i["seen"]}
            elif i:
                cell = {"state": _state(i, now), "asked": i["created"], "by": i["by_name"] or "", "seen": i["seen"],
                        "reminded": i["reminded"], "declined": i["declined"], "expires": i["created"] + TTL}
            else:
                cell = {"state": "none"}
            row["providers"][p] = cell
        people.append(row)
    return {"people": people, "members_allowed": allowed, "names": ca.NAMES, "link": LINK,
            "server_on": {p: ca.server_on(p) for p in ca.NAMES}, "push": bool(S["push"] and S["push"].enabled)}


# ---------- the member's side ----------
def pending(uid):
    """The requests this person still has to answer (read on every page load: no writes here)."""
    now = time.time()
    rows = S["db"].q("""SELECT i.*, b.username AS by_name FROM cli_invites i LEFT JOIN users b ON b.id = i.by_uid
                        WHERE i.user_id=? AND NOT EXISTS (SELECT 1 FROM cli_accounts a WHERE a.user_id = i.user_id
                              AND a.provider = i.provider AND a.ok = 1) ORDER BY i.provider = 'codex'""", (uid,))  # Claude Code first, as on the page
    return [{"provider": r["provider"], "name": ca.NAMES[r["provider"]], "plan": ca.PLANS[r["provider"]], "by": r["by_name"] or "An administrator",
             "asked": r["created"], "seen": r["seen"]} for r in rows if r["provider"] in ca.NAMES and _state(r, now) == "asked"]


def mark_seen(uid):
    S["db"].q("UPDATE cli_invites SET seen=? WHERE user_id=? AND seen IS NULL AND declined IS NULL", (time.time(), uid))


def decline(uid, p):
    S["db"].q("UPDATE cli_invites SET declined=? WHERE user_id=? AND provider=? AND declined IS NULL", (time.time(), uid, p))


# ---------- API ----------
class AskIn(BaseModel):
    users: list[int] = Field(min_length=1, max_length=500)
    providers: list[str] = Field(min_length=1, max_length=2)


def build(require, admin, ip, gate=None):
    r = APIRouter(prefix="/api/cli-accounts")
    me_ = lambda req: (gate or (lambda u: u))(require(req))

    def known(p):
        if p not in ca.NAMES: raise HTTPException(404, "Unknown CLI.")
        return p

    def name_of(uid):
        u = S["db"].q("SELECT username FROM users WHERE id=?", (uid,), one=True)
        return u["username"] if u else str(uid)

    @r.get("/team")
    def get_team(req: Request):
        admin(req)
        return team()

    @r.post("/invites")
    def post_ask(b: AskIn, req: Request):
        me = admin(req)
        out = ask(me, b.users, b.providers)
        for a in out["asked"]:
            S["db"].log("agent.cli_invite", me["username"], a["username"], ip(req), ",".join(a["providers"]))
        return {**team(), **out}

    @r.post("/invites/{uid}/{p}/remind")
    def post_remind(uid: int, p: str, req: Request):
        me = admin(req)
        remind(me, uid, known(p))
        S["db"].log("agent.cli_invite", me["username"], name_of(uid), ip(req), f"{p} (reminder)")
        return {**team(), "message": "Reminder sent."}

    @r.delete("/invites/{uid}/{p}")
    def delete_invite(uid: int, p: str, req: Request):
        me = admin(req)
        cancel(uid, known(p))
        S["db"].log("agent.cli_invite_cancel", me["username"], name_of(uid), ip(req), p)
        return {**team(), "message": "Request cancelled."}

    @r.get("/requests")
    def get_requests(req: Request):
        me = me_(req)
        return {"requests": pending(me["id"])}

    @r.post("/requests/seen")
    def post_seen(req: Request):
        me = me_(req)
        mark_seen(me["id"])
        return {"requests": pending(me["id"])}

    @r.post("/requests/{p}/decline")
    def post_decline(p: str, req: Request):
        me = me_(req)
        decline(me["id"], known(p))
        S["db"].log("agent.cli_invite_decline", me["username"], "", ip(req), p)
        return {"requests": pending(me["id"]), "message": "Declined. Your administrator can see that."}

    return r


def install(app, db, require, admin, ip, gate=None):
    init(db)
    app.include_router(build(require, admin, ip, gate))
