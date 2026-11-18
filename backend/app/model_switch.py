"""The on/off switch on each card in Agents → Models.

A switched-off model stays connected (its key, token or login is kept) but nothing runs on it: it leaves the model
pickers and the catalog, llm.resolve() refuses it, and cli_accounts.pick() skips the login. Turning it on again restores it.

Keys, kept as one JSON list in app_settings "models_off":
  "<provider>"           the server's own connection (llm.PROVIDERS id: "openai", "codex", "terminal", ...)
  "login:<id>"           a named server login (llm.TERMINAL_LOGINS, e.g. "login:claude-37")
  "own:<user id>:<p>"    a person's website sign-in login (cli_accounts.py), switched by that person
"""
import json

SETTING = "models_off"


def _read(db):
    if db is None: return set()
    try: v = json.loads(db.setting(SETTING) or "[]")
    except (ValueError, TypeError): return set()
    return {str(k) for k in v} if isinstance(v, list) else set()


def off(db, key):
    """True when the card `key` is switched off."""
    return key in _read(db)


def own_key(uid, p): return f"own:{int(uid)}:{p}"


def switch(db, key, on):
    """Turn the card `key` on or off."""
    keys = _read(db)
    keys.discard(key) if on else keys.add(key)
    db.setting(SETTING, v=json.dumps(sorted(keys)))
