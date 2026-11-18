"""Personal CLI logins: each person's own Claude Code / Codex plan for the Terminal and Codex providers.

The server has one login per CLI (llm.py's "terminal", codex_cli.py's "codex"): the owner's plan. Here a teammate
connects their own, and from then on every model call made for them runs on their plan, never on the server's or on
another teammate's:
- Claude Code: a long-lived token from `claude setup-token` on their own machine, stored encrypted (SecretBox) and passed
  as CLAUDE_CODE_OAUTH_TOKEN with a private, empty CLAUDE_CONFIG_DIR, so nothing of the server's login is read.
- Codex: `codex login --device-auth` started from the page into a private CODEX_HOME (CLI_ACCOUNTS_DIR/u<id>/codex); they
  finish it in their own browser. Never a copied auth.json: refresh-token rotation would sign their own Codex out.

Whose call is it (owner()): the signed-in user of the request (a contextvar the middleware sets: they started it), else
the agent core's run open on this thread (every engine opens one with its owner; threads don't inherit the contextvar),
else the user the completer was built for. pick() then chooses the login:
- the owner connected their own login for that CLI: theirs, with its own parallel gate and usage-limit clock;
- no own login (anyone, admin or member): the server's login; with that off, a teammate's connected login (shared());
- no owner (system work: Agent HQ, schedules): the server's login, else a teammate's.
Every model registered on the site is shared (the owner's call, 11-11): nobody has to connect their own login to give a
mission. Named server logins (llm.TERMINAL_LOGINS) are open to everyone too."""
import contextvars, logging, os, re, shutil, subprocess, tempfile, threading, time, uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from . import agent_core, auth, cli_parallel, codex_cli, llm, model_switch  # llm and codex_cli only at call time (llm imports this module)
from .secretbox import SecretBox

log = logging.getLogger("scout.cli_accounts")

NAMES = {"terminal": "Claude Code", "codex": "Codex"}
PLANS = {"terminal": "Claude plan", "codex": "ChatGPT plan"}
TOKEN = re.compile(r"sk-ant-oat\d{2}-[A-Za-z0-9_\-]{20,}")
URL = re.compile(r"https://\S+")
CODE = re.compile(r"^\s*([A-Z0-9]{4,5}-[A-Z0-9]{4,6})\s*$")
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
LOGIN_TTL = 15 * 60  # a Codex device code expires after 15 minutes
USER_TTL = 30
MY_LOGINS = "Agents → My logins"

_acting = contextvars.ContextVar("cli_acting", default=None)  # the signed-in user of this request (main.py's middleware)
S = {"db": None, "box": None, "root": None}
_lock = threading.Lock()
_clocks, _logins, _users = {}, {}, {}


def init(db, data_dir):
    S["db"], S["box"] = db, SecretBox(db, data_dir)
    cli_parallel.load(db)  # runs at once per login, as saved in Agents → Models
    S["root"] = Path(os.getenv("CLI_ACCOUNTS_DIR") or Path(data_dir) / "cli")
    db.q("""CREATE TABLE IF NOT EXISTS cli_accounts (user_id INTEGER, provider TEXT, connected REAL, checked REAL, ok INTEGER,
            error TEXT, PRIMARY KEY (user_id, provider))""")
    sweep()


# ---------- whose call, and which login ----------
class Account:
    """One CLI login: whose it is (uid None = the server's), the environment the CLI runs with, its gate and its clock."""
    def __init__(self, provider, uid, env, gate, quota, home=None, label=None, var=None):
        self.provider, self.uid, self.env, self.gate, self.quota, self.home = provider, uid, env, gate, quota, home
        self.label, self.var = label, var  # a named server login (llm.TERMINAL_LOGINS): its model's name and token variable
        self.borrowed = False  # a teammate's own login used for someone else's work (shared())

    @property
    def not_signed_in(self):
        if self.var:
            return (f"The {self.label} Claude Code login doesn't work (the token in {self.var} is missing, expired or was revoked). "
                    f"Run `claude setup-token`, put the token in .env as {self.var} and redeploy (`./k8s/redeploy.sh`).")
        if not self.uid: return llm.NOT_SIGNED_IN if self.provider == "terminal" else codex_cli.NOT_SIGNED_IN
        if self.borrowed:
            return (f"The shared {NAMES[self.provider]} login this ran on doesn't work any more (expired, revoked or signed out). "
                    f"An administrator can connect the server's login in Agents → Models, or connect your own under {MY_LOGINS}.")
        if self.provider == "terminal":
            return ("Your Claude Code login doesn't work any more (the token expired or was revoked). Run `claude setup-token` "
                    f"on your own machine and connect the new token under {MY_LOGINS}.")
        return f"Your Codex login doesn't work any more (signed out or expired). Sign in again under {MY_LOGINS}."

    @property
    def whose(self):
        """Words for messages: never a username (Autoloop reads "codex" in an error to pick the plan)."""
        return " on a shared teammate login" if self.borrowed else " on the owner's own login" if self.uid else f" on the {self.label} login" if self.var else ""


def owner(fallback=None):
    """The user a model call is made for: the request's signed-in user, else the run open on this thread (0 = system
    work), else `fallback` (who the completer was built for)."""
    uid = _acting.get()
    if uid: return uid
    cur = getattr(agent_core._local, "run", None)
    if cur is not None and cur.get("owner") is not None: return cur["owner"]
    return fallback


def server_on(p):
    db = S["db"]
    key, env = ("terminal_enabled", "CLAUDE_CLI_ENABLED") if p == "terminal" else ("codex_enabled", "CODEX_CLI_ENABLED")
    if model_switch.off(db, p): return False  # its card is switched off in Agents → Models
    return bool(db and db.setting(key) == "1") or os.getenv(env) == "1"


def server(p):
    if p == "terminal": return Account(p, None, llm._cli_env(), llm.CLI_GATE, llm._QUOTA)
    return Account(p, None, codex_cli._env(), codex_cli.GATE, codex_cli._QUOTA, codex_cli.home())


def _key(uid): return f"cli_claude_token_u{int(uid)}"

def _dir(uid, p):
    """The user's private folder for one CLI (made 0700 on first use)."""
    d = S["root"] / f"u{int(uid)}" / ("claude" if p == "terminal" else "codex")
    d.mkdir(parents=True, exist_ok=True)
    for x in (d, d.parent, S["root"]):
        try: os.chmod(x, 0o700)
        except OSError: pass
    return str(d)

def _clock(p, uid):
    with _lock:
        if (p, uid) not in _clocks:
            _clocks[(p, uid)] = (cli_parallel.Gate(p), {"until": 0.0})  # the same runs-at-once limit as the server's login
        return _clocks[(p, uid)]

def personal(p, uid, token=None):
    """The user's own login (None when they haven't connected one). `token`: a Claude token being tried, not yet saved."""
    gate, quota = _clock(p, uid)
    if p == "terminal":
        tok = token or (S["box"].get(_key(uid)) if S["box"] else None)
        if not tok: return None
        env = {k: v for k, v in llm._cli_env().items() if k not in ("CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR")}
        env.update(CLAUDE_CODE_OAUTH_TOKEN=tok, CLAUDE_CONFIG_DIR=_dir(uid, p))
        return Account(p, uid, env, gate, quota)
    home = _dir(uid, p)
    return Account(p, uid, {**codex_cli._env(), "CODEX_HOME": home}, gate, quota, home)


def _user(uid):
    hit = _users.get(uid)
    if hit and time.time() - hit[0] < USER_TTL: return hit[1]
    u = S["db"].q("SELECT id, username, role, disabled FROM users WHERE id=?", (uid,), one=True) if S["db"] else None
    _users[uid] = (time.time(), u)
    return u

# ---------- sign-in lifecycle audit (Owner decision 2026-11-11, D-019) ----------
# One "agent.cli_signin" row per step of a sign-in attempt: provider, flow, stage, the attempt's own id and, on failure, a fixed
# reason code. Never the token, the device code, the sign-in link, the CLI's output or an error text (they can carry any of them).
SIGNIN_STAGES = ("started", "code_shown", "link_shown", "code_submitted", "connected", "failed", "expired", "cancelled", "test_ok", "test_failed")
SIGNIN_REASONS = ("cli_start_error", "cli_exit_error", "status_check_failed", "code_rejected", "no_answer_after_code", "token_check_failed",
                  "token_format", "not_finished")


def signin_event(uid, provider, flow, stage, attempt="", reason=None, ip=""):
    if stage not in SIGNIN_STAGES or (reason and reason not in SIGNIN_REASONS) or S["db"] is None: return
    try:
        S["db"].log("agent.cli_signin", (_user(uid) or {}).get("username", "") if uid else "", str(uid or ""), ip or "",
                    f"{provider} {flow} {stage}" + (f" attempt={attempt}" if attempt else "") + (f" reason={reason}" if reason else ""))
    except Exception as e:  # noqa: BLE001 - the audit never breaks a sign-in
        log.warning("sign-in audit: %s", type(e).__name__)


def _attempt(): return uuid.uuid4().hex[:10]


def connected(uid, p):
    return bool(S["db"] and S["db"].q("SELECT 1 FROM cli_accounts WHERE user_id=? AND provider=?", (uid, p), one=True))

def own_off(uid, p):
    """The person switched their own login's card off in Agents → Models: nothing runs on it, theirs or a teammate's work."""
    return model_switch.off(S["db"], model_switch.own_key(uid, p))

def usable(uid, p):
    return connected(uid, p) and not own_off(uid, p)

def any_connected(p):
    """Someone connected their own login for `p` and left it switched on."""
    rows = S["db"].q("SELECT user_id FROM cli_accounts WHERE provider=?", (p,)) if S["db"] else []
    return any(not own_off(r["user_id"], p) for r in rows)

def shared(p, but=None):
    """A teammate's connected login anyone may run on when the server's login is off or at its usage limit (every model on the site is shared):
    oldest first, preferring one that last checked fine and isn't at its usage limit. `but`: skip this user's own."""
    if S["db"] is None: return None
    rows = S["db"].q("""SELECT c.user_id FROM cli_accounts c JOIN users u ON u.id=c.user_id
                        WHERE c.provider=? AND COALESCE(u.disabled, 0)=0 ORDER BY c.ok DESC, c.connected""", (p,))
    spare = None
    for r in rows:
        if r["user_id"] == but or own_off(r["user_id"], p): continue
        a = personal(p, r["user_id"])
        if not a: continue
        a.borrowed = True
        if a.quota["until"] <= time.time(): return a
        spare = spare or a
    return spare


def any_home(p):
    """Some connected user's CODEX_HOME (its models cache lists the models), or None."""
    rows = S["db"].q("SELECT user_id FROM cli_accounts WHERE provider=? ORDER BY connected", (p,)) if S["db"] else []
    r = next((r for r in rows if not own_off(r["user_id"], p)), None)
    return _dir(r["user_id"], p) if r else None


def named(model):
    """A named server login (llm.TERMINAL_LOGINS, e.g. Claude-37 on CLAUDE_CODE_OAUTH_TOKEN1): its own token, private
    config folder, runs-at-once gate and usage-limit clock. Raises llm.LLMError when its token isn't set."""
    label, var, _ = llm.TERMINAL_LOGINS[model]
    tok = os.getenv(var)
    if not tok:
        raise llm.LLMError(f"{label} has no Claude Code login: run `claude setup-token`, put the token in .env as {var} and redeploy.")
    gate, quota = _clock("terminal", f"login:{model}")
    d = Path(S["root"] or Path(tempfile.gettempdir()) / "axor-cli") / f"login-{model}" / "claude"
    d.mkdir(parents=True, exist_ok=True)
    for x in (d, d.parent):
        try: os.chmod(x, 0o700)
        except OSError: pass
    env = {k: v for k, v in llm._cli_env().items() if k not in ("CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR")}
    env.update(CLAUDE_CODE_OAUTH_TOKEN=tok, CLAUDE_CONFIG_DIR=str(d))
    return Account("terminal", None, env, gate, quota, label=label, var=var)


def server_limit(p):
    """Until when the server's own (token) login waits for its plan's usage limit; 0 when it isn't reached."""
    q = llm._QUOTA if p == "terminal" else codex_cli._QUOTA
    return q["until"] if q["until"] > time.time() else 0.0


def pick(p, who=None, model=None):
    """The login a call made for `who` (a user id; None/0 = system work) runs on. Raises llm.LLMError when there's none.
    `model`: a Terminal model id; a named server login's (llm.TERMINAL_LOGINS) runs on that login, for everyone.
    Every login is shared, both kinds Agents → Models adds (Token = the server's, Website sign-in = a person's):
    their own if they connected one, else the server's, else a teammate's (shared()). A teammate's is also used while
    the server's login is at its usage limit, when that teammate's isn't."""
    name = NAMES[p]
    if who and S["db"] is not None:
        u = _user(who)
        if not u or u["disabled"]: raise llm.LLMError("This account is disabled.")
    if p == "terminal" and model in llm.TERMINAL_LOGINS:
        if model_switch.off(S["db"], f"login:{model}"):
            raise llm.LLMError(f"{llm.TERMINAL_LOGINS[model][0]} is switched off in Agents → Models.")
        return named(model)
    if S["db"] is None: return server(p)  # not installed (tests, scripts): the server's login, as before
    if who and usable(who, p) and (a := personal(p, who)): return a
    if server_on(p):
        if server_limit(p) and (a := shared(p, who)) and a.quota["until"] <= time.time(): return a
        return server(p)
    if (a := shared(p, who)): return a
    if (who and connected(who, p) and own_off(who, p)) or model_switch.off(S["db"], p):
        raise llm.LLMError(f"{name} is switched off in Agents → Models. Pick another model, or turn it on there.")
    raise llm.LLMError(f"{name} isn't connected yet. An administrator can set it up in Agents → Models"
                       f"{f', or you can connect your own under {MY_LOGINS}' if who else ''}.")


def attribute(acct):
    """Records on this thread's run which login a model call is handed to (D-019). Called where the account goes to the CLI,
    not in pick(), which also answers checks that run nothing."""
    if acct is None: return
    if acct.var: ref, kind = f"named:{acct.label}", "named"
    elif acct.uid: ref, kind = f"user:{int(acct.uid)}:{acct.provider}", "own" if acct.uid == owner() else "other_user"
    else: ref, kind = f"server:{acct.provider}", "server"
    agent_core.login(ref, kind)
    return acct


def peek(p, who):
    """pick() without raising: None when `who` has no login for `p`."""
    try: return pick(p, who)
    except llm.LLMError: return None


# ---------- connecting, testing, removing ----------
def _save(uid, p, ok=True, error=None):
    now = time.time()
    S["db"].q("""INSERT INTO cli_accounts (user_id, provider, connected, checked, ok, error) VALUES (?,?,?,?,?,?)
                 ON CONFLICT(user_id, provider) DO UPDATE SET checked=excluded.checked, ok=excluded.ok, error=excluded.error""",
              (uid, p, now, now, int(ok), error))

def connect_claude(uid, token):
    token = (token or "").strip()
    if not TOKEN.fullmatch(token):
        raise llm.LLMError("That isn't a Claude Code token. Run `claude setup-token` on your own machine and paste the "
                           "sk-ant-oat… token it prints (an API key, sk-ant-api…, goes in Agents → Models instead).")
    a = personal("terminal", uid, token=token)
    llm.cli_check(a)  # auth status trusts any token: a tiny real prompt proves it
    S["box"].set(_key(uid), token)
    _save(uid, "terminal")

# ---------- the server's own login, from a token pasted in Agents → Models ----------
SERVER_TOKEN = "claude_cli_token_server"

def server_token():
    """The server's Claude Code token saved in Agents → Models (None: the environment's CLAUDE_CODE_OAUTH_TOKEN or ~/.claude login)."""
    try: return S["box"].get(SERVER_TOKEN) if S["box"] else None
    except Exception: return None

def connect_server_claude(token):
    """Check a `claude setup-token` token with a real prompt, then make it the server's login."""
    token = (token or "").strip()
    if not TOKEN.fullmatch(token):
        raise llm.LLMError("That isn't a Claude Code token. Run `claude setup-token` and paste the sk-ant-oat… token it prints "
                           "(an API key, sk-ant-api…, goes under API Key → Claude).")
    env = {**llm._cli_env(), "CLAUDE_CODE_OAUTH_TOKEN": token}
    try: llm.cli_check(Account("terminal", None, env, llm.CLI_GATE, llm._QUOTA))
    except llm.LLMError as e:
        if not str(e).startswith((llm.NOT_SIGNED_IN, llm.TOKEN_REJECTED)): raise  # a 401 adds "Claude Code said: …"
        raise llm.LLMError("Claude Code didn't accept that token: it's expired, revoked or cut short. Run `claude setup-token` again "
                           "and paste the whole token. Nothing was saved.")
    S["box"].set(SERVER_TOKEN, token)

def forget_server_claude():
    if S["box"]: S["box"].delete(SERVER_TOKEN)

def connect_server_codex(token):
    """Sign the server's Codex in with a token: an OpenAI API key (sk-…) or a Codex access token. It's signed in and checked
    in a scratch CODEX_HOME first, so a bad token never touches the server's working login."""
    token = (token or "").strip()
    flag = "--with-api-key" if token.startswith("sk-") else "--with-access-token"
    root = S["root"] or Path(tempfile.gettempdir()) / "axor-cli"
    root.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="codex-server-", dir=root)
    try:
        os.chmod(tmp, 0o700)
        env = {**codex_cli._env(), "CODEX_HOME": tmp}
        try:
            r = subprocess.run([codex_cli.exe(), "login", flag], input=token + "\n", capture_output=True, text=True, timeout=60, env=env)
        except subprocess.TimeoutExpired:
            raise llm.LLMError("The Codex CLI didn't answer. Try again.")
        if r.returncode:
            msg = ANSI.sub("", (r.stderr or r.stdout or "").strip()).splitlines()
            raise llm.LLMError(f"Codex didn't accept that token{': ' + msg[-1] if msg else '.'}")
        try: codex_cli.check(Account("codex", None, env, codex_cli.GATE, codex_cli._QUOTA, tmp))  # a real prompt proves it
        except llm.LLMError as e:
            if str(e) != codex_cli.NOT_SIGNED_IN: raise
            raise llm.LLMError("Codex didn't accept that token: it's expired, revoked or cut short. Nothing was saved.")
        home = codex_cli.home()
        os.makedirs(home, mode=0o700, exist_ok=True)
        shutil.copyfile(os.path.join(tmp, "auth.json"), os.path.join(home, "auth.json"))
        os.chmod(os.path.join(home, "auth.json"), 0o600)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test(uid, p):
    a = personal(p, uid) if connected(uid, p) else None
    if not a: raise llm.LLMError(f"You haven't connected your own {NAMES[p]} yet.")
    try:
        llm.cli_check(a) if p == "terminal" else codex_cli.check(a)
    except llm.LLMError as e:
        _save(uid, p, False, str(e)[:300]); raise
    _save(uid, p)

def remove(uid, p):
    """Forget the user's login: the token or the Codex home (signed out first), the row and the clock."""
    cancel_login(uid) if p == "codex" else cancel_claude_login(uid)
    if p == "codex" and (S["root"] / f"u{int(uid)}" / "codex").exists():
        try: subprocess.run([codex_cli.exe(), "logout"], capture_output=True, timeout=30, env={**codex_cli._env(), "CODEX_HOME": _dir(uid, p)})
        except (OSError, subprocess.TimeoutExpired, llm.LLMError): pass
    if p == "terminal" and S["box"]: S["box"].delete(_key(uid))
    shutil.rmtree(S["root"] / f"u{int(uid)}" / ("claude" if p == "terminal" else "codex"), ignore_errors=True)
    S["db"].q("DELETE FROM cli_accounts WHERE user_id=? AND provider=?", (uid, p))
    model_switch.switch(S["db"], model_switch.own_key(uid, p), True)  # connected again later, it starts on
    with _lock: _clocks.pop((p, uid), None)

def sweep():
    """Logins of deleted users go with them."""
    for r in S["db"].q("SELECT DISTINCT user_id FROM cli_accounts WHERE user_id NOT IN (SELECT id FROM users)"):
        for p in NAMES: remove(r["user_id"], p)
        shutil.rmtree(S["root"] / f"u{int(r['user_id'])}", ignore_errors=True)


# ---------- Codex device sign-in, started from the page ----------
class _Login:
    def __init__(self, proc, uid=None):
        self.proc, self.url, self.code, self.state, self.error = proc, None, None, "starting", None
        self.started, self.ready = time.time(), threading.Event()
        self.uid, self.attempt = uid, _attempt()

    def view(self):
        left = max(0, int(self.started + LOGIN_TTL - time.time()))
        return {"state": self.state, "url": self.url, "code": self.code, "error": self.error, "expires_in": left}


def start_login(uid, ip=""):
    with _lock:
        cur = _logins.get(uid)
        if cur and cur.state in ("starting", "waiting") and cur.proc.poll() is None: return cur.view()  # the same attempt: no new event
    home = _dir(uid, "codex")
    try:
        proc = subprocess.Popen([codex_cli.exe(), "login", "--device-auth"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, env={**codex_cli._env(), "CODEX_HOME": home, "NO_COLOR": "1"})
    except OSError as e:
        signin_event(uid, "codex", "device", "failed", _attempt(), "cli_start_error", ip)
        raise llm.LLMError(f"Couldn't start the Codex CLI: {e}.")
    L = _Login(proc, uid)
    signin_event(uid, "codex", "device", "started", L.attempt, ip=ip)
    with _lock: _logins[uid] = L
    threading.Thread(target=_follow, args=(uid, L), daemon=True).start()
    t = threading.Timer(LOGIN_TTL + 30, lambda: _expire(L)); t.daemon = True; t.start()
    L.ready.wait(5)  # the code can take 10-25 s to come from OpenAI: the page polls until it shows (only _expire stops the CLI)
    return L.view()

def _follow(uid, L):
    tail = []
    for raw in L.proc.stdout:
        line = ANSI.sub("", raw).rstrip()
        if not L.url and (m := URL.search(line)): L.url = m[0]
        elif not L.code and (m := CODE.match(line)): L.code = m[1]
        elif line.strip() and not URL.search(line) and not CODE.match(line): tail = (tail + [line.strip()])[-3:]
        if L.url and L.code and L.state == "starting":
            L.state = "waiting"; L.ready.set()
            signin_event(uid, "codex", "device", "code_shown", L.attempt)  # that it was shown: never the code or the link
    rc = L.proc.wait()
    L.ready.set()
    if L.state not in ("starting", "waiting"): return  # cancelled or expired
    if rc == 0:
        try:
            codex_cli.status(personal("codex", uid))
            _save(uid, "codex")
            L.state = "done"
            S["db"].log("agent.cli_login", (_user(uid) or {}).get("username", ""), "", "", "codex")
            signin_event(uid, "codex", "device", "connected", L.attempt)
            return
        except llm.LLMError as e:
            L.error = str(e)
    last = tail[-1] if tail and not tail[-1].lower().startswith(("2. enter", "continue only")) else ""
    signin_event(uid, "codex", "device", "failed", L.attempt, "status_check_failed" if L.error else "cli_exit_error")
    L.state, L.error = "failed", L.error or (f"The sign-in didn't finish: {last}" if last else "The sign-in didn't finish. Start again.")

def _stop(L):
    if L.proc.poll() is None:
        L.proc.terminate()
        try: L.proc.wait(5)
        except subprocess.TimeoutExpired: L.proc.kill()

def _expire(L):
    if L.state in ("starting", "waiting"):
        L.state, L.error = "expired", "The code expired. Start again."
        signin_event(L.uid, "codex", "device", "expired", L.attempt)
        _stop(L)

def cancel_login(uid, ip=""):
    with _lock: L = _logins.pop(uid, None)
    if L and L.state in ("starting", "waiting"):
        L.state = "cancelled"; _stop(L)
        signin_event(uid, "codex", "device", "cancelled", L.attempt, ip=ip)

def login_view(uid):
    L = _logins.get(uid)
    return L.view() if L else None


# ---------- Claude sign-in, started from the page (Agents → Models → Add model → CLI → Claude → My own login) ----------
# `claude setup-token` in a terminal of its own (it needs one), with an empty private config folder and no token in its
# environment: it prints Claude's sign-in link, the person signs in on claude.ai in their own browser and gets a code,
# the page sends the code here, the CLI trades it for a long-lived token and prints it. The token never reaches the
# browser: it's read here, checked with a real prompt (connect_claude) and saved encrypted.
CLAUDE_URL = re.compile(r"https://\S*oauth/authorize\S+")
CLAUDE_LOGIN_TTL = 10 * 60
CODE_WAIT = 90  # after the code is typed: the CLI trades it for the token in a few seconds, then one check prompt runs
TERM_ESC = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[=>()][A-Za-z0-9]?")
_clogins = {}

class _ClaudeLogin:
    def __init__(self, proc, fd, tmp, uid=None):
        self.proc, self.fd, self.tmp = proc, fd, tmp
        self.uid, self.attempt = uid, _attempt()
        self.url, self.state, self.error, self.sent, self.sent_at = None, "starting", None, False, 0.0
        self.started, self.ready = time.time(), threading.Event()

    def view(self):
        left = max(0, int(self.started + CLAUDE_LOGIN_TTL - time.time()))
        return {"state": self.state, "url": self.url, "error": self.error, "expires_in": left, "code_sent": self.sent}


def start_claude_login(uid, ip=""):
    import fcntl, struct, termios
    with _lock:
        cur = _clogins.get(uid)
        if cur and cur.state in ("starting", "waiting") and not cur.sent: return cur.view()  # the same attempt: no new event
    if cur:
        if cur.state in ("starting", "waiting"): signin_event(uid, "terminal", "setup_token", "cancelled", cur.attempt, ip=ip)  # replaced by a new one
        _stop_claude(cur)
    exe = llm._cli_exe()
    tmp = tempfile.mkdtemp(prefix="claude-login-")
    env = {k: v for k, v in llm._cli_env().items() if k not in ("CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR")}
    env.update(CLAUDE_CONFIG_DIR=tmp, NO_COLOR="1", TERM="xterm", BROWSER="true", COLUMNS="1000", LINES="50")  # no browser on the server: the link goes to the page
    fd = slave = None
    try:
        fd, slave = os.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 1000, 0, 0))  # wide: the link and the token stay on one line
        proc = subprocess.Popen([exe, "setup-token"], stdin=slave, stdout=slave, stderr=slave, env=env, start_new_session=True)
    except OSError as e:
        if fd is not None: os.close(fd)
        shutil.rmtree(tmp, ignore_errors=True)
        signin_event(uid, "terminal", "setup_token", "failed", _attempt(), "cli_start_error", ip)
        raise llm.LLMError(f"Couldn't start the Claude Code CLI: {e}.")
    finally:
        if slave is not None: os.close(slave)
    L = _ClaudeLogin(proc, fd, tmp, uid)
    signin_event(uid, "terminal", "setup_token", "started", L.attempt, ip=ip)
    with _lock: _clogins[uid] = L
    threading.Thread(target=_follow_claude, args=(uid, L), daemon=True).start()
    t = threading.Timer(CLAUDE_LOGIN_TTL, lambda: _expire_claude(L)); t.daemon = True; t.start()
    L.ready.wait(20)
    return L.view()

def _follow_claude(uid, L):
    buf, seen = "", 0
    try:
        while True:
            try: chunk = os.read(L.fd, 65536)
            except OSError: break
            if not chunk: break
            buf = (buf + TERM_ESC.sub("", chunk.decode("utf-8", "replace")))[-60000:]
            if not L.url and (m := CLAUDE_URL.search(buf)) and buf[m.end():].strip():  # the whole link is out once text follows it
                L.url, L.state, seen = m[0], "waiting", len(buf); L.ready.set()
                signin_event(uid, "terminal", "setup_token", "link_shown", L.attempt)  # that it was shown: never the link
            if not L.sent: continue
            if (m := TOKEN.search(buf)) and re.search(r"[^A-Za-z0-9_\-]", buf[m.end():]):  # the whole token: something follows it
                token = m[0]
                L.state = "checking"  # the token is in: one real prompt proves it (the wait for the CLI is over)
                _stop_claude(L, keep_state=True)
                try:
                    connect_claude(uid, token)
                    L.state = "done"
                    S["db"].log("agent.cli_login", (_user(uid) or {}).get("username", ""), "", "", "terminal")
                    signin_event(uid, "terminal", "setup_token", "connected", L.attempt)
                except llm.LLMError as e:
                    L.state, L.error = "failed", str(e)
                    signin_event(uid, "terminal", "setup_token", "failed", L.attempt, "token_check_failed")
                return
            if "OAuth error" in buf[seen:] or "Press Enter to retry" in buf[seen:].replace("\xa0", " ") or "PressEntertoretry" in buf[seen:]:
                L.state, L.error = "failed", "Claude didn't accept that code. Press Connect to start again, and paste the whole code the page shows."
                signin_event(uid, "terminal", "setup_token", "failed", L.attempt, "code_rejected")
                _stop_claude(L, keep_state=True)
                return
        if L.sent and L.state == "waiting" and (m := TOKEN.search(buf)):  # the CLI ended right after the token
            L.state = "checking"
            try:
                connect_claude(uid, m[0]); L.state = "done"
                S["db"].log("agent.cli_login", (_user(uid) or {}).get("username", ""), "", "", "terminal")
                signin_event(uid, "terminal", "setup_token", "connected", L.attempt)
            except llm.LLMError as e:
                L.state, L.error = "failed", str(e)
                signin_event(uid, "terminal", "setup_token", "failed", L.attempt, "token_check_failed")
    finally:
        L.ready.set()
        if L.state in ("starting", "waiting"):
            L.state, L.error = "failed", L.error or "The sign-in didn't finish. Press Connect to start again."
            signin_event(uid, "terminal", "setup_token", "failed", L.attempt, "not_finished")
        _stop_claude(L, keep_state=True)

def _stop_claude(L, keep_state=False):
    if not keep_state and L.state in ("starting", "waiting"): L.state = "cancelled"
    def reap():
        if L.proc.poll() is None:
            L.proc.terminate()
            try: L.proc.wait(5)
            except subprocess.TimeoutExpired: L.proc.kill(); L.proc.wait()
        try: os.close(L.fd)
        except OSError: pass
        shutil.rmtree(L.tmp, ignore_errors=True)
    with _lock:
        if getattr(L, "reaping", False): return
        L.reaping = True
    threading.Thread(target=reap, daemon=True).start()

def _expire_claude(L):
    if L.state in ("starting", "waiting"):
        L.state, L.error = "expired", "The sign-in took too long. Press Connect to start again."
        signin_event(L.uid, "terminal", "setup_token", "expired", L.attempt)
        _stop_claude(L, keep_state=True)

def claude_login_code(uid, code):
    """The code Claude's page showed after the sign-in: typed into the waiting CLI. The page then polls for the result."""
    code = (code or "").strip()
    L = _clogins.get(uid)
    if not L or L.state != "waiting": raise llm.LLMError("The sign-in isn't open any more. Press Connect to start again.")
    if not re.fullmatch(r"[A-Za-z0-9_\-#.~]{8,600}", code): raise llm.LLMError("That doesn't look like the code. Copy the whole code Claude's page shows.")
    if L.sent: return L.view()
    L.sent, L.sent_at = True, time.time()
    signin_event(uid, "terminal", "setup_token", "code_submitted", L.attempt)  # that a code went in: never the code
    try: os.write(L.fd, code.encode() + b"\r")
    except OSError: raise llm.LLMError("The sign-in isn't open any more. Press Connect to start again.")
    def late():  # no token and no error from the CLI: don't leave the page waiting
        if L.state == "waiting":
            L.state, L.error = "failed", (f"Claude Code didn't answer after the code. Press Connect to start again, or paste a "
                                          f"`claude setup-token` token under {MY_LOGINS} instead.")
            signin_event(uid, "terminal", "setup_token", "failed", L.attempt, "no_answer_after_code")
            _stop_claude(L, keep_state=True)
    t = threading.Timer(CODE_WAIT, late); t.daemon = True; t.start()
    return L.view()

def cancel_claude_login(uid, ip=""):
    with _lock: L = _clogins.pop(uid, None)
    if L:
        if L.state in ("starting", "waiting"): signin_event(uid, "terminal", "setup_token", "cancelled", L.attempt, ip=ip)
        _stop_claude(L)

def claude_login_view(uid):
    L = _clogins.get(uid)
    return L.view() if L else None


# ---------- API ----------
class TokenIn(BaseModel):
    token: str

class CodeIn(BaseModel):
    code: str

class SwitchIn(BaseModel):
    on: bool


def mine(uid, role):
    out = {}
    for p, name in NAMES.items():
        r = S["db"].q("SELECT connected, checked, ok, error FROM cli_accounts WHERE user_id=? AND provider=?", (uid, p), one=True)
        g, q = _clocks.get((p, uid), (None, {"until": 0.0}))
        a = peek(p, uid)  # what pick() runs their work on (not their own while it's switched off)
        out[p] = {"name": name, "plan": PLANS[p], "connected": bool(r), "connected_at": r and r["connected"], "checked": r and r["checked"],
                  "ok": bool(r and r["ok"]), "error": r and r["error"], "off": own_off(uid, p), "limit_until": q["until"] if q["until"] > time.time() else None,
                  "uses": "own" if a and a.uid == uid else "shared" if a and a.borrowed else "server" if a else "none",
                  "server_on": server_on(p), "login": login_view(uid) if p == "codex" else claude_login_view(uid)}
    return {"providers": out, "is_admin": role == "admin"}


def build(require, admin, sudo, ip, gate=None):
    r = APIRouter(prefix="/api/cli-accounts")
    me_ = lambda req: (gate or (lambda u: u))(require(req))
    log = lambda me, req, what, detail="": S["db"].log(what, me["username"], "", ip(req), detail)

    def call(fn, *a):
        try: return fn(*a)
        except llm.LLMError as e: raise HTTPException(400, str(e))

    @r.get("")
    def get_mine(req: Request):
        me = me_(req)
        return mine(me["id"], me["role"])

    @r.post("/terminal")
    def post_claude(t: TokenIn, req: Request):
        me = me_(req)
        a = _attempt()
        try: call(connect_claude, me["id"], t.token)
        except HTTPException:
            signin_event(me["id"], "terminal", "token", "failed", a, "token_check_failed" if TOKEN.fullmatch((t.token or "").strip()) else "token_format", ip(req))
            raise
        log(me, req, "agent.cli_login", "terminal")
        signin_event(me["id"], "terminal", "token", "connected", a, ip=ip(req))
        return {**mine(me["id"], me["role"]), "message": "Your Claude Code is connected: your runs on Terminal models use your own plan, and everyone on the site may use it too."}

    @r.post("/terminal/start")
    def claude_start(req: Request):
        """Start Claude's sign-in for the signed-in person: answers with the link to open (state "waiting")."""
        me = me_(req)
        return {**mine(me["id"], me["role"]), "login": call(start_claude_login, me["id"], ip(req))}

    @r.post("/terminal/code")
    def claude_code(c: CodeIn, req: Request):
        me = me_(req)
        return {**mine(me["id"], me["role"]), "login": call(claude_login_code, me["id"], c.code)}

    @r.post("/terminal/cancel")
    def claude_cancel(req: Request):
        me = me_(req)
        cancel_claude_login(me["id"], ip(req))
        return mine(me["id"], me["role"])

    @r.post("/codex/start")
    def codex_start(req: Request):
        me = me_(req)
        return {**mine(me["id"], me["role"]), "login": call(start_login, me["id"], ip(req))}

    @r.post("/codex/cancel")
    def codex_cancel(req: Request):
        me = me_(req)
        cancel_login(me["id"], ip(req))
        return mine(me["id"], me["role"])

    @r.post("/{p}/test")
    def post_test(p: str, req: Request):
        me = me_(req)
        if p not in NAMES: raise HTTPException(404, "Unknown CLI.")
        try: call(test, me["id"], p)
        except HTTPException:
            signin_event(me["id"], p, "check", "test_failed", ip=ip(req)); raise
        signin_event(me["id"], p, "check", "test_ok", ip=ip(req))
        return {**mine(me["id"], me["role"]), "message": f"Your {NAMES[p]} answered."}

    @r.post("/{p}/switch")
    def post_switch(p: str, b: SwitchIn, req: Request):
        """The on/off switch on the person's own login card: off keeps the login, but nothing runs on it (model_switch.py)."""
        me = me_(req)
        if p not in NAMES: raise HTTPException(404, "Unknown CLI.")
        if not connected(me["id"], p): raise HTTPException(400, f"You haven't connected your own {NAMES[p]}.")
        model_switch.switch(S["db"], model_switch.own_key(me["id"], p), b.on)
        log(me, req, "agent.model_switch", f"own:{p} {'on' if b.on else 'off'}")
        return {**mine(me["id"], me["role"]), "message": f"Your {NAMES[p]} is switched {'on' if b.on else 'off'}."}

    @r.delete("/{p}")
    def delete_mine(p: str, req: Request):
        me = me_(req)
        if p not in NAMES: raise HTTPException(404, "Unknown CLI.")
        remove(me["id"], p)
        log(me, req, "agent.cli_logout", p)
        return {**mine(me["id"], me["role"]), "message": f"Your {NAMES[p]} login is removed from the server."}

    @r.get("/all")
    def get_all(req: Request):
        """Admins: who connected their own login (never the tokens)."""
        admin(req)
        sweep()
        return [{"user_id": x["user_id"], "username": x["username"], "provider": x["provider"], "name": NAMES.get(x["provider"], x["provider"]),
                 "connected": x["connected"], "checked": x["checked"], "ok": bool(x["ok"]), "error": x["error"]}
                for x in S["db"].q("""SELECT a.*, u.username FROM cli_accounts a JOIN users u ON u.id = a.user_id
                                      ORDER BY u.username, a.provider""")]

    @r.delete("/all/{uid}/{p}")
    def delete_any(uid: int, p: str, req: Request):
        me = sudo(req)
        if p not in NAMES: raise HTTPException(404, "Unknown CLI.")
        remove(uid, p)
        S["db"].log("agent.cli_logout", me["username"], str(uid), ip(req), f"{p} (by an admin)")
        return get_all(req)

    return r


def install(app, db, data_dir, require, admin_state, ip, hub=None):
    """main.py: the table, the routes, and the middleware that remembers who signed in for this request."""
    init(db, data_dir)

    @app.middleware("http")
    async def acting(req: Request, call_next):
        uid = None
        tok = req.cookies.get(auth.COOKIE) if req.url.path.startswith("/api/") else None
        if tok:
            s = db.q("SELECT user_id FROM sessions WHERE hash=? AND stage='full' AND expires>?", (auth._h(tok), time.time()), one=True)
            uid = s and s["user_id"]
        mark = _acting.set(uid) if uid else None
        try: return await call_next(req)
        finally:
            if mark is not None: _acting.reset(mark)

    app.include_router(build(require, admin_state["admin"], admin_state["sudo"], ip, hub.gate if hub else None))
    from . import cli_invites  # admins ask teammates to connect theirs (here: it imports this module)
    cli_invites.install(app, db, require, admin_state["admin"], ip, hub.gate if hub else None)
