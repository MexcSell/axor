"""Connectors: every outside service AXoR holds a key for, on one admin page, and OpenRouter's API keys managed from it.

OpenRouter key management needs a management key (openrouter.ai/settings/management-keys; OPENROUTER_MANAGEMENT_KEY
works too until one is saved here). A management key can't call models: it lists the account's API keys with what
each has spent (total, today, this week, this month), creates keys, renames them, sets or clears a credit limit,
disables and re-enables them, and deletes them for good. The key AXoR's agents use (Agents → Models) is matched by
its masked label, so the page can say which key is the one AXoR depends on.

The overview reports the other keys (model providers, Slack, GitHub, service secrets) by where they're set and a
masked form; each is changed on its own page. Secrets never leave the server, except a new OpenRouter key, which
OpenRouter shows once: it's passed to the admin who created it and not kept.
"""
import json, os, re, time, urllib.error, urllib.parse, urllib.request

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .secretbox import SecretBox, fingerprint, mask

OR_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
RESETS = ("daily", "weekly", "monthly")
HASH = re.compile(r"[A-Za-z0-9_-]{6,128}")

class ORError(Exception):
    def __init__(self, msg, status=502):
        super().__init__(msg); self.status = status

class KeyIn(BaseModel):
    key: str = Field(..., min_length=10, max_length=300)

class NewKey(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    limit: float | None = Field(None, ge=0, lt=1_000_000)
    limit_reset: str | None = None
    include_byok_in_limit: bool = False
    expires_at: str | None = Field(None, pattern=r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?Z$")

class KeyEdit(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=256)
    limit: float | None = Field(None, ge=0, lt=1_000_000)
    limit_reset: str | None = None
    include_byok_in_limit: bool | None = None
    disabled: bool | None = None

class OpenRouter:
    def __init__(self, db, box):
        self.db, self.box = db, box
        self._label = (None, None, 0.0)  # (inference key, its label, when looked up)

    def key(self): return self.box.get("openrouter_mgmt_key") or os.getenv("OPENROUTER_MANAGEMENT_KEY") or None
    def source(self): return "app" if self.box.get("openrouter_mgmt_key") else "env" if os.getenv("OPENROUTER_MANAGEMENT_KEY") else None
    def agent_key(self): return self.box.get("openrouter_api_key") or os.getenv("OPENROUTER_API_KEY") or None

    def call(self, method, path, key=None, body=None, **params):
        key = key or self.key()
        if not key: raise ORError("OpenRouter key management isn't connected.", 400)
        url = f"{OR_URL}{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
        h = {"Authorization": f"Bearer {key}", "User-Agent": "axor", "X-Title": "AXoR"}
        if body is not None: h["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(), headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=20) as r: return json.load(r)
        except urllib.error.HTTPError as e:
            try: detail = (json.load(e).get("error") or {}).get("message") or ""
            except Exception: detail = ""
            raise ORError(_explain(e.code, detail), 404 if e.code == 404 else 400 if e.code in (400, 409) else 502)
        except (urllib.error.URLError, TimeoutError) as e:
            raise ORError(f"Can't reach OpenRouter ({getattr(e, 'reason', e)}).")

    def keys(self, key=None):
        """Every key on the account, disabled and expired ones included, following the offset pages."""
        out, seen = [], set()
        for _ in range(50):
            page = self.call("GET", "/keys", key=key, include_disabled="true", include_expired="true", offset=len(out)).get("data") or []
            new = [k for k in page if k.get("hash") not in seen]
            if not new: break
            out += new; seen |= {k.get("hash") for k in new}
        return out

    def credits(self):
        try: return self.call("GET", "/credits").get("data")
        except ORError: return None  # the page still works without the account balance

    def agent_label(self):
        """Masked label of the key the agents use, so it can be pointed out in the list (looked up at most every 10 min)."""
        k = self.agent_key()
        if not k: return None
        if self._label[0] == k and time.time() - self._label[2] < 600: return self._label[1]
        try: label = (self.call("GET", "/key", key=k).get("data") or {}).get("label")
        except ORError: label = None
        self._label = (k, label, time.time())
        return label

def _explain(code, detail):
    if code == 401: return "OpenRouter rejected the management key: it's wrong, revoked or expired."
    if code == 403: return ("That's a regular OpenRouter API key. Managing keys needs a management key: "
                            "create one at openrouter.ai/settings/management-keys.")
    if code == 404: return "OpenRouter has no such key. It may have been deleted already."
    if code == 429: return "OpenRouter is rate-limiting us; try again shortly."
    return f"OpenRouter: {detail}" if detail else f"OpenRouter answered HTTP {code}."

def _mask(k):
    """OpenRouter keys all start sk-or-v1-, so show a few characters past that, as OpenRouter's own labels do."""
    return f"{k[:12]}…{k[-4:]}" if k and k.startswith("sk-or-v1-") and len(k) > 24 else mask(k)

def _key_view(k, agent_label):
    keep = ("hash", "name", "label", "disabled", "limit", "limit_remaining", "limit_reset", "include_byok_in_limit",
            "usage", "usage_daily", "usage_weekly", "usage_monthly", "byok_usage", "byok_usage_monthly",
            "created_at", "updated_at", "last_used_at", "expires_at")
    return {**{f: k.get(f) for f in keep}, "agents": bool(agent_label) and k.get("label") == agent_label}

def _check_reset(v):
    if v not in (None, *RESETS): raise HTTPException(400, "The limit resets daily, weekly, monthly or never.")

def _check_hash(h):
    if not HASH.fullmatch(h): raise HTTPException(400, "Bad key id.")
    return urllib.parse.quote(h, safe="")

def build(db, admin_state, ip, data_dir):
    r = APIRouter(prefix="/api/connectors")
    box = SecretBox(db, data_dir)
    orr = OpenRouter(db, box)
    admin, sudo = admin_state["admin"], admin_state["sudo"]
    r.state = {"openrouter": orr}

    def fail(e): raise HTTPException(e.status, str(e))

    @r.get("")
    def overview(req: Request):
        """Every key AXoR holds, where it's set, and which page changes it. Never the secrets themselves."""
        admin(req)
        def item(id, name, group, stored, env, manage, note="", show=True):
            v = stored or os.getenv(env)
            return {"id": id, "name": name, "group": group, "configured": bool(v), "source": "app" if stored else "env" if v else None,
                    "env": env, "masked": _mask(v) if show else None, "manage": manage, "note": note}
        g = box.get
        return {"connectors": [
            item("anthropic", "Claude (Anthropic)", "Model providers", g("anthropic_api_key"), "ANTHROPIC_API_KEY", "agents", "Agents use it to call Claude."),
            item("openai", "OpenAI", "Model providers", g("openai_api_key"), "OPENAI_API_KEY", "agents", "Agents use it to call OpenAI models."),
            item("openrouter", "OpenRouter API key", "Model providers", g("openrouter_api_key"), "OPENROUTER_API_KEY", "agents", "Agents use it for OpenRouter models."),
            item("openrouter_mgmt", "OpenRouter management key", "Model providers", g("openrouter_mgmt_key"), "OPENROUTER_MANAGEMENT_KEY", "connectors", "Manages the account's API keys on this page; can't call models."),
            item("local", "Local model server key", "Model providers", g("local_llm_key"), "LOCAL_LLM_KEY", "agents", "Only if the local server asks for one."),
            item("slack", "Slack bot token", "Apps", g("slack_bot_token"), "SLACK_BOT_TOKEN", "slack", "Reads and posts to the team's Slack channel."),
            item("github", "GitHub token (Source hub)", "Apps", g("github_token"), "SOURCE_GITHUB_TOKEN", "source", "Reads repositories and CI; other sources keep their own tokens."),
            item("github_alerts", "GitHub token (alerts)", "Apps", None, "GITHUB_TOKEN", None, "Raises the GitHub rate limit for subnet repo checks. Set in the environment."),
            item("drive", "AXoR Drive secret", "AXoR services", None, "DRIVE_SECRET", None, "Shared with the Drive service. Set in the environment.", show=False),
            item("push", "AXoR Push secret", "AXoR services", None, "PUSH_SECRET", None, "Shared with the Push service. Set in the environment.", show=False),
            item("runner", "AXoR Runner secret", "AXoR services", None, "RUNNER_SECRET", None, "Shared with the DevOps runner. Set in the environment.", show=False),
        ]}

    @r.get("/openrouter")
    def openrouter(req: Request):
        admin(req)
        k = orr.key()
        out = {"connected": bool(k), "masked": _mask(k), "source": orr.source(), "agent_key": bool(orr.agent_key())}
        if not k: return out
        try: keys = orr.keys()
        except ORError as e: return {**out, "error": str(e), "keys": []}
        label = orr.agent_label()
        return {**out, "keys": [_key_view(x, label) for x in keys], "credits": orr.credits(), "agent_label": label}

    @r.put("/openrouter")
    def connect(c: KeyIn, req: Request):
        """A management key is checked by listing the account's keys before it's saved."""
        me = sudo(req)
        key = c.key.strip()
        if not key.startswith("sk-or-"): raise HTTPException(400, "That doesn't look like an OpenRouter key (they start with sk-or-).")
        try: n = len(orr.keys(key=key))
        except ORError as e: raise HTTPException(400, f"{e} Nothing was saved.")
        box.set("openrouter_mgmt_key", key)
        db.log("connector.openrouter_connect", me["username"], "", ip(req), f"{fingerprint(key)} ({n} keys)")  # D-019: never key characters
        return openrouter(req)

    @r.delete("/openrouter")
    def disconnect(req: Request):
        me = sudo(req)
        box.delete("openrouter_mgmt_key")
        db.log("connector.openrouter_disconnect", me["username"], "", ip(req), "")
        return openrouter(req)

    @r.post("/openrouter/keys")
    def create(k: NewKey, req: Request):
        """The new key comes back once, in `key`: OpenRouter won't show it again and AXoR doesn't keep it."""
        me = sudo(req)
        _check_reset(k.limit_reset)
        body = {"name": k.name.strip(), "limit": k.limit, "limit_reset": k.limit_reset if k.limit is not None else None,
                "include_byok_in_limit": k.include_byok_in_limit}
        if k.expires_at: body["expires_at"] = k.expires_at
        try: res = orr.call("POST", "/keys", body=body)
        except ORError as e: fail(e)
        d = res.get("data") or {}
        db.log("connector.key_create", me["username"], d.get("name", ""), ip(req), f"{d.get('label', '')} limit={k.limit}")
        return {"key": res.get("key"), "data": _key_view(d, None)}

    @r.patch("/openrouter/keys/{h}")
    def edit(h: str, k: KeyEdit, req: Request):
        me = sudo(req)
        body = k.model_dump(exclude_unset=True)  # a limit sent as null clears it; one left out stays as it is
        if not body: raise HTTPException(400, "Nothing to change.")
        if "name" in body:
            if body["name"] is None or not body["name"].strip(): raise HTTPException(400, "A key needs a name.")
            body["name"] = body["name"].strip()
        if "limit_reset" in body: _check_reset(body["limit_reset"])
        try: d = orr.call("PATCH", f"/keys/{_check_hash(h)}", body=body).get("data") or {}
        except ORError as e: fail(e)
        what = "disable" if body.get("disabled") is True else "enable" if body.get("disabled") is False else "edit"
        db.log(f"connector.key_{what}", me["username"], d.get("name", h), ip(req), json.dumps({x: v for x, v in body.items() if x != "disabled"})[:200])
        return _key_view(d, orr.agent_label())

    @r.delete("/openrouter/keys/{h}")
    def delete(h: str, req: Request):
        me = sudo(req)
        path = f"/keys/{_check_hash(h)}"
        try:
            name = (orr.call("GET", path).get("data") or {}).get("name", h)
            orr.call("DELETE", path)
        except ORError as e: fail(e)
        db.log("connector.key_delete", me["username"], name, ip(req), h)
        return {"ok": True}

    return r
