"""Knowledge Hub · live Discord and Telegram connectors for My Knowledge's Communications (knowledge_hub.Hub mixes this in).

Each connector is the user's own bot, read only:
- Discord: a bot token and the channel ids it may read (the bot must be in the server, with View Channel, Read Message
  History and the Message Content intent). Sync reads each channel's messages after the last one kept (GET
  /channels/{id}/messages?after=…, up to 500 a sync; the first sync takes the latest 100).
- Telegram: a bot token, optionally limited to some chat ids. Sync reads the bot's updates after the last one (getUpdates):
  messages people send it, and group or channel messages it can see (privacy mode off, or the bot an admin). getUpdates hands
  each update out once, so use a bot that does nothing else; it fails while the bot has a webhook.
Tokens are encrypted (secretbox.py) and never shown again; the page shows a masked form. Messages go through the same path
as imports (knowledge_spaces._add_messages): kept as untrusted, private sources under /05-Communications/<Platform>/<channel>,
deduplicated by platform, channel and message id. "Sync automatically" reads every SYNC_MINUTES in the background.
DISCORD_API_URL and TELEGRAM_API_URL point elsewhere for tests (tests/fake_knowledge_apis.py).
"""
import json, logging, os, re, threading, time, urllib.error, urllib.parse, urllib.request

from fastapi import HTTPException
from pydantic import BaseModel, Field

from .mining import _clip
from .secretbox import SecretBox, fingerprint

log = logging.getLogger("knowledge")
DISCORD = os.getenv("DISCORD_API_URL", "https://discord.com/api/v10").rstrip("/")
TELEGRAM = os.getenv("TELEGRAM_API_URL", "https://api.telegram.org").rstrip("/")
SYNC_MINUTES = max(5, int(os.getenv("KNOWLEDGE_SYNC_MINUTES", "15")))
PAGES = 5            # Discord pages of 100 per channel and sync
UA = "AXoR-Knowledge/1.0 (read-only connector)"


class ConnectorIn(BaseModel):
    platform: str = Field(..., pattern="^(discord|telegram)$")
    name: str = Field("", max_length=80)
    token: str = Field(..., min_length=20, max_length=200)
    channels: list[str] = Field(default_factory=list, max_length=50)   # Discord channel ids; Telegram chat ids (optional)
    auto: bool = False

class ConnectorPatch(BaseModel):
    name: str | None = Field(None, max_length=80)
    token: str | None = Field(None, min_length=20, max_length=200)
    channels: list[str] | None = Field(None, max_length=50)
    auto: bool | None = None


class ConnError(Exception):
    """A platform answered with an error; the message is safe to show."""


def _get(url, headers=None, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: return json.load(r)
    except urllib.error.HTTPError as e:
        try: body = json.load(e)
        except ValueError: body = {}
        if e.code == 429: raise ConnError(f"Rate limited: try again in {round(float(body.get('retry_after') or body.get('parameters', {}).get('retry_after') or 5))} s.")
        msg = body.get("message") or body.get("description") or ""
        raise ConnError({401: "The token was refused (401): check it.", 403: f"Not allowed (403){': ' + msg if msg else ''}: check the bot's permissions.",
                         404: f"Not found (404){': ' + msg if msg else ''}.", 409: f"Conflict (409){': ' + msg if msg else ''}."}.get(e.code, f"The platform answered {e.code}{': ' + msg if msg else ''}."))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        raise ConnError(f"Couldn't reach the platform: {getattr(e, 'reason', e)}.")


class Connectors:
    @property
    def box(self):
        """The encrypted store of connector tokens (secretbox.py), made when first needed."""
        if getattr(self, "_box", None) is None:
            from . import knowledge_media
            knowledge_media.DATA_DIR.mkdir(parents=True, exist_ok=True)
            self._box = SecretBox(self.db, knowledge_media.DATA_DIR)
        return self._box

    def _connectors_init(self):
        self.db.q("""CREATE TABLE IF NOT EXISTS kb_connectors (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, platform TEXT, name TEXT, config TEXT,
                     masked TEXT, auto INTEGER DEFAULT 0, status TEXT, error TEXT, last_sync REAL, added INTEGER DEFAULT 0, created REAL)""")
        if os.getenv("KNOWLEDGE_SYNC", "1") != "0" and not getattr(self, "_syncer", None):
            self._syncer = threading.Thread(target=self._sync_loop, name="kb-connectors", daemon=True)
            self._syncer.start()

    def _conn(self, me, cid):
        c = self.db.q("SELECT * FROM kb_connectors WHERE id=? AND user_id=?", (cid, me["id"]), one=True)
        if not c: raise HTTPException(404, "There's no such connector.")
        return c

    @staticmethod
    def _secret(c): return f"kb_conn_{c['user_id']}_{c['id']}"

    def _shape(self, c):
        cfg = json.loads(c["config"] or "{}")
        return {"id": c["id"], "platform": c["platform"], "name": c["name"], "masked": c["masked"], "channels": cfg.get("channels") or [],
                "names": cfg.get("names") or {}, "bot": cfg.get("bot"), "auto": bool(c["auto"]), "status": c["status"], "error": c["error"],
                "last_sync": c["last_sync"], "added": c["added"] or 0}

    def connectors(self, me):
        return [self._shape(c) for c in self.db.q("SELECT * FROM kb_connectors WHERE user_id=? ORDER BY id", (me["id"],))]

    @staticmethod
    def _ids(platform, xs):
        out = []
        for x in xs:
            x = str(x).strip()
            if not x: continue
            if not re.fullmatch(r"-?\d{1,25}", x): raise HTTPException(400, f"“{_clip(x, 40)}” isn't a {'channel' if platform == 'discord' else 'chat'} id (digits only{'' if platform == 'discord' else ', a minus sign for groups'}).")
            out.append(x)
        return list(dict.fromkeys(out))

    def _whoami(self, platform, token):
        if platform == "discord":
            u = _get(f"{DISCORD}/users/@me", {"Authorization": f"Bot {token}"})
            if not u.get("bot"): raise ConnError("That token isn't a bot's token.")
            return u.get("username") or "bot"
        r = _get(f"{TELEGRAM}/bot{urllib.parse.quote(token, safe=':')}/getMe")
        if not r.get("ok"): raise ConnError(r.get("description") or "Telegram refused the token.")
        return "@" + str((r.get("result") or {}).get("username") or "bot")

    def add_connector(self, me, b: ConnectorIn):
        chans = self._ids(b.platform, b.channels)
        if b.platform == "discord" and not chans: raise HTTPException(400, "Give the ids of the channels the bot may read (Discord: right-click a channel → Copy Channel ID).")
        if len(self.connectors(me)) >= 10: raise HTTPException(409, "Ten connectors at most.")
        try: bot = self._whoami(b.platform, b.token.strip())
        except ConnError as e: raise HTTPException(400, str(e))
        name = b.name.strip() or f"{'Discord' if b.platform == 'discord' else 'Telegram'} · {bot}"
        cid = self._ins("INSERT INTO kb_connectors (user_id, platform, name, config, masked, auto, status, created) VALUES (?,?,?,?,?,?,?,?)",
                        (me["id"], b.platform, _clip(name, 80), json.dumps({"channels": chans, "bot": bot}), fingerprint(b.token.strip()), int(b.auto), "ready", time.time()))  # a stored row: never key characters (D-019)
        c = self._conn(me, cid)
        self.box.set(self._secret(c), b.token.strip())
        self._audit(me, "connector", f"connector:{cid}", f"{name}: added ({len(chans)} channel{'s' if len(chans) != 1 else ''})")
        return self._shape(c)

    def edit_connector(self, me, cid, b: ConnectorPatch):
        c = self._conn(me, cid)
        cfg, sets = json.loads(c["config"] or "{}"), {}
        if b.token:
            try: cfg["bot"] = self._whoami(c["platform"], b.token.strip())
            except ConnError as e: raise HTTPException(400, str(e))
            self.box.set(self._secret(c), b.token.strip()); sets["masked"] = fingerprint(b.token.strip())
        if b.channels is not None:
            chans = self._ids(c["platform"], b.channels)
            if c["platform"] == "discord" and not chans: raise HTTPException(400, "Keep at least one channel.")
            cfg["channels"] = chans
        if b.name is not None and b.name.strip(): sets["name"] = _clip(b.name.strip(), 80)
        if b.auto is not None: sets["auto"] = int(b.auto)
        sets["config"] = json.dumps(cfg)
        self.db.q(f"UPDATE kb_connectors SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?", (*sets.values(), cid))
        self._audit(me, "connector", f"connector:{cid}", f"{c['name']}: changed ({', '.join(k for k in sets if k != 'config') or 'channels'})")
        return self._shape(self._conn(me, cid))

    def remove_connector(self, me, cid):
        c = self._conn(me, cid)
        self.box.delete(self._secret(c))
        self.db.q("DELETE FROM kb_connectors WHERE id=?", (cid,))
        self.db.q("DELETE FROM kb_cursors WHERE user_id=? AND connector LIKE ?", (me["id"], f"conn:{cid}:%"))
        self._audit(me, "connector", f"connector:{cid}", f"{c['name']}: removed (its messages stay)")
        return {"ok": True}

    def _cursor(self, me, key, value=None):
        if value is None:
            r = self.db.q("SELECT cursor FROM kb_cursors WHERE user_id=? AND connector=?", (me["id"], key), one=True)
            return r["cursor"] if r else None
        self.db.q("INSERT INTO kb_cursors (user_id, connector, cursor, updated) VALUES (?,?,?,?) ON CONFLICT (user_id, connector) DO UPDATE SET cursor=excluded.cursor, updated=excluded.updated",
                  (me["id"], key, str(value), time.time()))

    def sync_connector(self, me, cid):
        c = self._conn(me, cid)
        token = self.box.get(self._secret(c))
        if not token: raise HTTPException(409, "The connector's token is gone (the server's secret key changed?): give it again.")
        self._ensure_tree(me)
        cfg = json.loads(c["config"] or "{}")
        try:
            got, names = (self._discord(me, c, cfg, token) if c["platform"] == "discord" else self._telegram(me, c, cfg, token))
            made, skipped, red = 0, 0, 0
            for (ws, label), msgs in got.items():
                if not msgs: continue
                m_, s_, r_ = self._add_messages(me, c["platform"], ws, msgs, label)
                made += len(m_); skipped += s_; red += r_
            cfg["names"] = {**(cfg.get("names") or {}), **names}
            self.db.q("UPDATE kb_connectors SET status='ok', error=NULL, last_sync=?, added=added+?, config=? WHERE id=?", (time.time(), made, json.dumps(cfg), cid))
            self._audit(me, "sync", f"connector:{cid}", f"{c['name']}: {made} messages" + (f", {skipped} already kept" if skipped else "") + (f", {red} secrets taken out" if red else ""))
            return {"added": made, "skipped": skipped, "connector": self._shape(self._conn(me, cid))}
        except ConnError as e:
            self.db.q("UPDATE kb_connectors SET status='error', error=?, last_sync=? WHERE id=?", (str(e), time.time(), cid))
            self._audit(me, "sync", f"connector:{cid}", f"{c['name']}: failed: {e}")
            raise HTTPException(502, f"{c['name']}: {e}")

    def _discord(self, me, c, cfg, token):
        h = {"Authorization": f"Bot {token}"}
        out, names, guilds = {}, {}, {}
        for ch in cfg.get("channels") or []:
            info = _get(f"{DISCORD}/channels/{ch}", h)
            gid = info.get("guild_id")
            if gid and gid not in guilds:
                try: guilds[gid] = _get(f"{DISCORD}/guilds/{gid}", h).get("name") or ""
                except ConnError: guilds[gid] = ""
            cname = info.get("name") or ch
            names[ch] = cname
            key = f"conn:{c['id']}:{ch}"
            after, msgs = self._cursor(me, key), []
            for _ in range(PAGES if after else 1):
                page = _get(f"{DISCORD}/channels/{ch}/messages?limit=100" + (f"&after={after}" if after else ""), h)
                if not isinstance(page, list) or not page: break
                page.sort(key=lambda m: int(m["id"]))
                for m in page:
                    a = m.get("author") or {}
                    msgs.append({"id": str(m["id"]), "author": a.get("global_name") or a.get("username") or "someone", "ts": _iso(m.get("timestamp")),
                                 "text": str(m.get("content") or ""), "channel": cname, "thread": str((m.get("message_reference") or {}).get("message_id") or "") or None,
                                 "attachments": [x.get("filename") for x in m.get("attachments") or [] if isinstance(x, dict)],
                                 "link": f"https://discord.com/channels/{gid or '@me'}/{ch}/{m['id']}"})
                after = page[-1]["id"]
                if len(page) < 100: break
            if after: self._cursor(me, key, after)
            msgs = [m for m in msgs if m["text"].strip() or m["attachments"]]
            out.setdefault((guilds.get(gid, ""), f"Discord #{cname}"), []).extend(msgs)
        return out, names

    def _telegram(self, me, c, cfg, token):
        key = f"conn:{c['id']}:updates"
        off = self._cursor(me, key)
        allow = set(cfg.get("channels") or [])
        out, names, last = {}, {}, None
        for _ in range(5):
            q = {"timeout": 0, "limit": 100, "allowed_updates": json.dumps(["message", "channel_post", "edited_message", "edited_channel_post"])}
            if off: q["offset"] = int(off) + 1
            r = _get(f"{TELEGRAM}/bot{urllib.parse.quote(token, safe=':')}/getUpdates?{urllib.parse.urlencode(q)}")
            if not r.get("ok"): raise ConnError(r.get("description") or "Telegram refused the request.")
            ups = r.get("result") or []
            if not ups: break
            for u in ups:
                last = off = u.get("update_id")
                m = u.get("message") or u.get("channel_post") or u.get("edited_message") or u.get("edited_channel_post")
                if not isinstance(m, dict): continue
                chat = m.get("chat") or {}
                cid_ = str(chat.get("id"))
                if allow and cid_ not in allow: continue
                cname = chat.get("title") or chat.get("username") or " ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x) or cid_
                names[cid_] = cname
                fr = m.get("from") or {}
                text = m.get("text") or m.get("caption") or ""
                files = [x for x in ((m.get("document") or {}).get("file_name"), "photo" if m.get("photo") else None, "voice message" if m.get("voice") else None) if x]
                out.setdefault(("", f"Telegram {cname}"), []).append({
                    "id": str(m.get("message_id")), "author": fr.get("username") or " ".join(x for x in (fr.get("first_name"), fr.get("last_name")) if x) or cname,
                    "ts": float(m.get("date") or 0) or None, "text": str(text), "channel": cname,
                    "thread": str((m.get("reply_to_message") or {}).get("message_id") or "") or None, "attachments": files,
                    "link": f"https://t.me/{chat['username']}/{m.get('message_id')}" if chat.get("username") else None})
            if len(ups) < 100: break
        if last is not None: self._cursor(me, key, last)
        for k in out: out[k] = [m for m in out[k] if m["text"].strip() or m["attachments"]]
        return out, names

    def _sync_loop(self):
        time.sleep(30)
        while True:
            try:
                due = self.db.q("SELECT id, user_id FROM kb_connectors WHERE auto=1 AND (last_sync IS NULL OR last_sync<?)", (time.time() - SYNC_MINUTES * 60,))
                for c in due:
                    u = self.db.q("SELECT id, username FROM users WHERE id=? AND disabled=0", (c["user_id"],), one=True)
                    if not u: continue
                    try: self.sync_connector(dict(u), c["id"])
                    except HTTPException as e: log.info("knowledge connector %s: %s", c["id"], e.detail)
            except Exception as e:  # noqa: BLE001 - the loop never stops the app
                log.warning("knowledge connector loop: %s", e)
            time.sleep(60)


def _iso(s):
    from .knowledge_spaces import _ts
    return _ts(s)
