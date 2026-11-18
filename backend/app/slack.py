"""Slack: one channel of one Slack workspace, read and written from inside Subnet Scout.

An admin connects a Slack app's bot token (xoxb-...) and picks the channel; SLACK_BOT_TOKEN / SLACK_CHANNEL work
too until something is saved in the app. Bot scopes: channels:history, channels:read, chat:write, users:read
(groups:history + groups:read for a private channel; chat:write.customize to post under each member's name;
channels:join so the bot can join a public channel by itself).

A poller reads the channel every SLACK_POLL_SECONDS into one cache that every signed-in user is served from, so
browsers never call Slack and the workspace's rate limits aren't multiplied by users. Members read the channel
and threads, post messages and replies (sent by the bot, labelled with their Subnet Scout name), and share a
subnet, one of their notes or an alert. Alert kinds the admin picks are posted to the channel as they happen.
Text from Subnet Scout is escaped and sent without link parsing, so nobody can @channel or @here through it.
"""
import json, logging, os, re, threading, time, urllib.error, urllib.parse, urllib.request
from collections import deque

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .secretbox import SecretBox, mask, fingerprint

log = logging.getLogger("slack")
API = os.getenv("SLACK_API_URL", "https://slack.com/api").rstrip("/")
POLL = max(5, int(os.getenv("SLACK_POLL_SECONDS", "15")))
NEEDED = {"channels:history", "channels:read", "chat:write", "users:read"}
ALERT_KINDS = ("new_subnet", "emission", "opportunity", "fund", "news")
POSTS_PER_MIN = 8

class SlackError(Exception):
    pass

def esc(t):
    """Slack's own escaping: only &, < and > are special in message text."""
    return (t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def note_to_mrkdwn(t):
    """Our note markdown -> Slack mrkdwn (checkboxes as ballot boxes, **bold** -> *bold*, ==mark== -> `mark`)."""
    out = []
    for line in esc(t).splitlines():
        line = re.sub(r"^\s*[-*+] \[[xX]\] ", "☑ ", line)
        line = re.sub(r"^\s*[-*+] \[ \] ", "☐ ", line)
        line = re.sub(r"^#{1,3} (.*)$", r"*\1*", line)
        line = re.sub(r"\*\*(.+?)\*\*", r"*\1*", line).replace("==", "`")
        line = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", r"<\2|\1>", line)
        out.append(line)
    return "\n".join(out)

class ConfigIn(BaseModel):
    token: str | None = None
    channel: str | None = None
    autopost: list[str] | None = None
    members_post: bool | None = None

class PostIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=3000)
    thread_ts: str | None = Field(None, pattern=r"^\d+\.\d+$")

class ShareIn(BaseModel):
    kind: str
    id: str
    comment: str = Field("", max_length=1000)

class Slack:
    def __init__(self, db, data_dir, data=None, alerts=None):
        self.db, self.data, self.alerts = db, data, alerts
        self.box = SecretBox(db, data_dir)
        self.cache = {"messages": [], "updated": None, "error": None}
        self.info, self.users, self.threads = {}, {}, {}
        self.posts, self.lock, self.wake = {}, threading.Lock(), threading.Event()
        self.queue = deque(maxlen=50)

    # ---------- configuration ----------
    def token(self):
        return self.box.get("slack_bot_token") or os.getenv("SLACK_BOT_TOKEN") or None

    def channel_ref(self):
        return self.db.setting("slack_channel") or os.getenv("SLACK_CHANNEL") or None

    def settings(self):
        return {"autopost": [k for k in json.loads(self.db.setting("slack_autopost", "[]")) if k in ALERT_KINDS],
                "members_post": self.db.setting("slack_members_post", "1") == "1"}

    def configured(self):
        return bool(self.token() and self.channel_ref())

    # ---------- Slack Web API ----------
    def call(self, method, token=None, get=False, **params):
        token = token or self.token()
        if not token: raise SlackError("Slack isn't connected.")
        h = {"Authorization": f"Bearer {token}", "User-Agent": "subnet-scout"}
        if get:
            req = urllib.request.Request(f"{API}/{method}?{urllib.parse.urlencode(params)}", headers=h)
        else:
            h["Content-Type"] = "application/json; charset=utf-8"
            req = urllib.request.Request(f"{API}/{method}", data=json.dumps(params).encode(), headers=h, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                body, scopes = json.load(r), r.headers.get("X-OAuth-Scopes")
        except urllib.error.HTTPError as e:
            if e.code == 429: raise SlackError(f"Slack is rate-limiting us; retrying in {e.headers.get('Retry-After', '30')}s.")
            raise SlackError(f"Slack answered HTTP {e.code}.")
        except (urllib.error.URLError, TimeoutError) as e:
            raise SlackError(f"Can't reach Slack ({getattr(e, 'reason', e)}).")
        if not body.get("ok"):
            raise SlackError(_explain(body.get("error", "unknown_error"), body.get("needed")))
        if scopes is not None: body["_scopes"] = {s.strip() for s in scopes.split(",") if s.strip()}
        return body

    def connect(self, token, channel):
        """Check a token and channel end to end: who we are, which channel, that we can read it."""
        me = self.call("auth.test", token=token)
        scopes = me.get("_scopes", set())
        ref = channel.strip().lstrip("#")
        if re.fullmatch(r"[CG][A-Z0-9]{6,}", ref):
            ch = self.call("conversations.info", token=token, get=True, channel=ref)["channel"]
        else:
            ch, cursor = None, ""
            for _ in range(20):  # up to 20 pages of 200 channels
                page = self.call("conversations.list", token=token, get=True, limit=200, cursor=cursor, exclude_archived="true",
                                 types="public_channel,private_channel" if "groups:read" in scopes else "public_channel")
                ch = next((c for c in page["channels"] if c["name"] == ref.lower()), None)
                cursor = (page.get("response_metadata") or {}).get("next_cursor")
                if ch or not cursor: break
            if not ch: raise SlackError(f"No channel named #{ref} that the app can see. Use the channel ID (C…) or invite the app first.")
        if not ch.get("is_member"):
            if ch.get("is_private"): raise SlackError(f"Invite the app to #{ch['name']} first (type /invite @your-app in the channel).")
            try: self.call("conversations.join", token=token, channel=ch["id"])
            except SlackError: raise SlackError(f"The app isn't in #{ch['name']}. Invite it (/invite @your-app) or add the channels:join scope.")
        self.call("conversations.history", token=token, get=True, channel=ch["id"], limit=1)
        return {"team": me.get("team"), "team_url": me.get("url"), "bot": me.get("user"), "bot_id": me.get("user_id"),
                "channel": {"id": ch["id"], "name": ch["name"], "private": ch.get("is_private", False),
                            "topic": (ch.get("topic") or {}).get("value", "")},
                "scopes": sorted(scopes), "missing": sorted(NEEDED - scopes) if scopes else [],
                "customize": "chat:write.customize" in scopes}

    def _info(self):
        if not self.info.get("channel") and self.configured():
            self.info = self.connect(self.token(), self.channel_ref())
        return self.info

    def _user(self, uid):
        u = self.users.get(uid)
        if u and time.time() - u["at"] < 6 * 3600: return u
        try:
            p = self.call("users.info", get=True, user=uid)["user"]
            prof = p.get("profile") or {}
            u = {"name": prof.get("display_name") or prof.get("real_name") or p.get("name") or uid, "avatar": prof.get("image_48"), "at": time.time()}
        except SlackError:
            u = {"name": uid, "avatar": None, "at": time.time() - 5 * 3600}  # retry in an hour
        self.users[uid] = u
        return u

    def _shape(self, m):
        """A Slack message as the page needs it: author, avatar, text with user mentions named."""
        meta = (m.get("metadata") or {})
        scout = (meta.get("event_payload") or {}).get("user") if meta.get("event_type") == "scout_message" else None
        if m.get("user"):
            u = self._user(m["user"]); name, avatar = u["name"], u["avatar"]
        else:
            bp = m.get("bot_profile") or {}
            name = m.get("username") or bp.get("name") or "Bot"
            avatar = ((m.get("icons") or {}).get("image_48") or (bp.get("icons") or {}).get("image_48"))
        text = re.sub(r"<@([UW][A-Z0-9]+)>", lambda x: f"<@{x[1]}|{self._user(x[1])['name']}>", m.get("text") or "")
        return {"ts": m["ts"], "name": scout or name, "avatar": avatar, "text": text, "bot": not m.get("user"), "scout_user": scout,
                "thread_ts": m.get("thread_ts"), "reply_count": m.get("reply_count", 0), "latest_reply": m.get("latest_reply"),
                "edited": bool(m.get("edited")), "subtype": m.get("subtype"),
                "files": [{"name": f.get("name") or f.get("title") or "file", "url": f.get("permalink")} for f in m.get("files") or []]}

    # ---------- poller ----------
    def start(self):
        threading.Thread(target=self._loop, daemon=True, name="slack").start()

    def _loop(self):
        while True:
            if self.configured():
                try: self.refresh()
                except SlackError as e:
                    self.cache["error"] = str(e)
                    log.warning("slack: %s", e)
                except Exception:
                    log.exception("slack poll failed")
                self._drain()
            self.wake.wait(POLL); self.wake.clear()

    def refresh(self):
        info = self._info()
        h = self.call("conversations.history", get=True, channel=info["channel"]["id"], limit=60, include_all_metadata="true")
        msgs = [self._shape(m) for m in reversed(h.get("messages", []))
                if m.get("subtype") not in ("channel_join", "channel_leave", "bot_add", "channel_purpose")]
        with self.lock:
            self.cache = {"messages": msgs, "updated": time.time(), "error": None}

    def thread(self, ts):
        c = self.threads.get(ts)
        if c and time.time() - c["at"] < 10: return c["items"]
        r = self.call("conversations.replies", get=True, channel=self._info()["channel"]["id"], ts=ts, limit=100, include_all_metadata="true")
        items = [self._shape(m) for m in r.get("messages", [])]
        self.threads[ts] = {"at": time.time(), "items": items}
        return items

    # ---------- posting ----------
    def post(self, text, user=None, thread_ts=None):
        """Send as the bot. With chat:write.customize the message carries the member's name; otherwise the
        name leads the text. Escaped and unparsed, so mentions like @channel stay plain text."""
        info = self._info()
        body = {"channel": info["channel"]["id"], "text": text, "unfurl_links": False, "unfurl_media": False, "parse": "none", "link_names": False}
        if thread_ts: body["thread_ts"] = thread_ts
        if user:
            body["metadata"] = {"event_type": "scout_message", "event_payload": {"user": user}}
            if info.get("customize"): body["username"] = f"{user} (AXoR)"
            else: body["text"] = f"*{esc(user)}* via AXoR: {text}"
        r = self.call("chat.postMessage", **body)
        self.threads.pop(thread_ts, None)
        self.wake.set()
        return r.get("ts")

    def _limit(self, me):
        now = time.time()
        q = [t for t in self.posts.get(me["id"], []) if t > now - 60]
        if len(q) >= POSTS_PER_MIN: raise HTTPException(429, "You're posting quickly: wait a moment and try again.")
        self.posts[me["id"]] = q + [now]

    def can_post(self, me):
        return self.configured() and (me["role"] == "admin" or self.settings()["members_post"])

    # alerts the admin chose are queued here (from the alert watcher's thread) and sent by the poller
    def on_alert(self, a):
        if self.configured() and a["kind"] in self.settings()["autopost"]:
            self.queue.append(a); self.wake.set()

    def _drain(self):
        while self.queue:
            a = self.queue.popleft()
            text = f"*{esc(a['title'])}*" + (f"\n{esc(a['body'])}" if a.get("body") else "")
            if a.get("url"): text += f"\n<{a['url']}|Open>"
            elif a.get("netuid") is not None: text += f"\n<https://taostats.io/subnets/{a['netuid']}|SN{a['netuid']} on taostats>"
            try: self.post(text)
            except SlackError as e: log.warning("slack autopost failed: %s", e); break

    def share(self, me, s: ShareIn):
        comment = esc(s.comment.strip())
        if s.kind == "subnet":
            r = next((x for x in self.data()["subnets"] if str(x["netuid"]) == s.id), None) if self.data else None
            if not r: raise HTTPException(404, "That subnet isn't in the current data.")
            usd = self.data().get("tao_usd") or 0
            fmt = lambda t: f"{t:.4g} τ" + (f" (${t * usd:,.0f})" if usd and t * usd >= 1 else "")
            risk = {"scam": "Scam signal", "avoid": "Avoid", "caution": "Caution"}.get(r.get("risk_level"), "No risk flags")
            text = (f"*SN{r['netuid']} · {esc(r['name'])}* · {esc(r['field'])}\n{esc(r['task'])[:300]}\n"
                    f"Top miner {fmt(r['top_miner'])}/day · registration {fmt(r['reg_cost'])} · emission {r['emission_day']:.3g} τ/day · "
                    f"{r['earning_miners']} miners earning · {'UID open' if r['uid_available'] else 'no UID open'} · {risk}\n"
                    f"<https://taostats.io/subnets/{r['netuid']}|taostats>")
        elif s.kind == "note":
            n = self.db.q("SELECT text, netuid, kind, day FROM workspace_notes WHERE id=? AND user_id=?", (int(s.id) if s.id.isdigit() else -1, me["id"]), one=True)
            if not n: raise HTTPException(404, "That note doesn't exist.")
            head = f"Daily note {n['day']}" if n["kind"] == "daily" else ("Note" + (f" on SN{n['netuid']}" if n["netuid"] is not None else ""))
            text = f"_{head}_\n{note_to_mrkdwn(n['text'])[:2800]}"
        elif s.kind == "agent":  # an agent's answer: "<agent id>:<conversation id>:<message index>"
            try: aid, cid, idx = s.id.split(":"); aid, idx = int(aid), int(idx)
            except ValueError: raise HTTPException(400, "Bad answer reference.")
            c = self.db.q("SELECT messages FROM agent_conversations WHERE id=? AND user_id=? AND agent=?", (cid, me["id"], f"custom:{aid}"), one=True)
            msgs = json.loads(c["messages"]) if c else []
            if not (0 <= idx < len(msgs)) or msgs[idx]["role"] != "assistant": raise HTTPException(404, "That answer doesn't exist.")
            a = self.db.q("SELECT name, role FROM custom_agents WHERE id=?", (aid,), one=True) or {"name": "Agent", "role": ""}
            body = "\n".join(b["text"] for b in msgs[idx]["content"] if b.get("type") == "text")
            body = re.sub(r"\s*\[\[suggest:.*?\]\]\s*$", "", body, flags=re.S)
            text = f"_Answer from {esc(a['name'])}{', ' + esc(a['role']) if a['role'] else ''}_\n{note_to_mrkdwn(body)[:2800]}"
        elif s.kind == "alert":
            a = self.db.q("SELECT kind, netuid, title, body, url FROM alerts WHERE id=?", (int(s.id) if s.id.isdigit() else -1,), one=True)
            if not a: raise HTTPException(404, "That notification doesn't exist.")
            text = f"*{esc(a['title'])}*" + (f"\n{esc(a['body'])}" if a["body"] else "") + (f"\n<{a['url']}|Open>" if a["url"] else "")
        else:
            raise HTTPException(400, "Share a subnet, a note or a notification.")
        return self.post((comment + "\n" if comment else "") + text, user=me["username"])

def _explain(err, needed=None):
    return {
        "invalid_auth": "Slack rejected the token. Copy the Bot User OAuth Token (xoxb-…) again.",
        "not_authed": "No Slack token was sent.", "token_revoked": "That Slack token was revoked. Reinstall the app and copy the new token.",
        "account_inactive": "The Slack app or its workspace is no longer active.",
        "channel_not_found": "Slack can't find that channel, or the app isn't allowed to see it. Invite the app to the channel.",
        "not_in_channel": "The app isn't in the channel. Type /invite @your-app in the channel.",
        "is_archived": "That channel is archived.", "msg_too_long": "That message is too long for Slack.",
        "missing_scope": f"The Slack app is missing a permission{f' ({needed})' if needed else ''}. Add it under OAuth & Permissions and reinstall the app.",
        "ratelimited": "Slack is rate-limiting us; try again shortly.",
    }.get(err, f"Slack error: {err}.")

def build(db, require, admin_state, ip, data_dir, data=None, alerts=None):
    r = APIRouter(prefix="/api/slack")
    sl = Slack(db, data_dir, data, alerts)
    admin, sudo = admin_state["admin"], admin_state["sudo"]
    r.state = {"slack": sl}

    @r.get("")
    def view(req: Request):
        me = require(req)
        if not sl.configured():
            return {"configured": False, "is_admin": me["role"] == "admin"}
        info = sl.info or {}
        return {"configured": True, "is_admin": me["role"] == "admin", "can_post": sl.can_post(me), "me": me["username"],
                "team": info.get("team"), "team_url": info.get("team_url"), "channel": info.get("channel"),
                "messages": sl.cache["messages"], "updated": sl.cache["updated"], "error": sl.cache["error"]}

    @r.get("/thread")
    def thread(ts: str, req: Request):
        require(req)
        if not re.fullmatch(r"\d+\.\d+", ts): raise HTTPException(400, "Bad thread id.")
        try: return {"items": sl.thread(ts)}
        except SlackError as e: raise HTTPException(502, str(e))

    @r.post("/messages")
    def post(p: PostIn, req: Request):
        me = require(req)
        if not sl.can_post(me): raise HTTPException(403, "Posting to Slack is limited to admins.")
        sl._limit(me)
        try: ts = sl.post(esc(p.text.strip()), user=me["username"], thread_ts=p.thread_ts)
        except SlackError as e: raise HTTPException(502, str(e))
        return {"ok": True, "ts": ts}

    @r.post("/share")
    def share(s: ShareIn, req: Request):
        me = require(req)
        if not sl.can_post(me): raise HTTPException(403, "Posting to Slack is limited to admins.")
        sl._limit(me)
        try: sl.share(me, s)
        except SlackError as e: raise HTTPException(502, str(e))
        return {"ok": True, "channel": (sl.info.get("channel") or {}).get("name")}

    @r.get("/config")
    def config(req: Request):
        admin(req)
        t = sl.token()
        return {"configured": sl.configured(), "token": mask(t), "token_source": "app" if sl.box.get("slack_bot_token") else "env" if t else None,
                "channel": sl.channel_ref(), **sl.settings(), "kinds": list(ALERT_KINDS), "status": sl.info or None, "error": sl.cache["error"]}

    @r.put("/config")
    def set_config(c: ConfigIn, req: Request):
        """Connecting or changing the token/channel is checked end to end before anything is saved."""
        me = sudo(req) if c.token or c.channel is not None else admin(req)
        if c.token is not None or c.channel is not None:
            token = (c.token or "").strip() or sl.token()
            channel = (c.channel if c.channel is not None else sl.channel_ref() or "").strip()
            if not token: raise HTTPException(400, "Paste the app's Bot User OAuth Token (xoxb-…).")
            if c.token and not re.fullmatch(r"xox[bp]-[A-Za-z0-9-]{10,}", token): raise HTTPException(400, "That doesn't look like a Slack bot token (they start with xoxb-).")
            if not channel: raise HTTPException(400, "Name the channel, e.g. #mining or its ID (C…).")
            try: info = sl.connect(token, channel)
            except SlackError as e: raise HTTPException(400, f"{e} Nothing was saved.")
            if c.token: sl.box.set("slack_bot_token", token)
            db.setting("slack_channel", v=info["channel"]["id"])
            sl.info, sl.cache, sl.threads = info, {"messages": [], "updated": None, "error": None}, {}
            sl.wake.set()
            db.log("slack.connect", me["username"], "", ip(req), f"#{info['channel']['name']} {info['team']} {fingerprint(token)}"[:200])  # D-019: never key characters
        if c.autopost is not None:
            db.setting("slack_autopost", v=json.dumps([k for k in c.autopost if k in ALERT_KINDS]))
        if c.members_post is not None:
            db.setting("slack_members_post", v="1" if c.members_post else "0")
        if c.autopost is not None or c.members_post is not None:
            db.log("slack.settings", me["username"], "", ip(req), json.dumps(sl.settings()))
        return config(req)

    @r.delete("/config")
    def disconnect(req: Request):
        me = sudo(req)
        sl.box.delete("slack_bot_token")
        db.q("DELETE FROM app_settings WHERE k='slack_channel'")
        sl.info, sl.cache, sl.threads = {}, {"messages": [], "updated": None, "error": None}, {}
        db.log("slack.disconnect", me["username"], "", ip(req), "")
        return config(req)

    return r
