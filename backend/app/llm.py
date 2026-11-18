"""Model providers for agents: Claude (Anthropic API), OpenAI, OpenRouter (hundreds of models behind one key),
local OpenAI-compatible servers (Ollama, LM Studio, vLLM, llama.cpp...), and Terminal: the Claude Code CLI installed on
the server, signed in with its own Claude login (no API key).

Conversations are stored in Anthropic's message format (text / tool_use / tool_result blocks). OpenAI-style providers
get the history translated on every call and their replies translated back, so a chat can switch models mid-way.
A model is addressed as "<provider>:<model id>", e.g. "openai:gpt-5", "openrouter:google/gemini-2.5-pro" or "local:llama3.1:8b".

Terminal runs `claude -p` once per model turn with its built-in tools, MCP servers and customizations off. The CLI can't
call our tools natively, so the transcript and tool list go in as text and the reply comes back as structured output
({text, tool_calls}), which is translated into the usual tool_use blocks for the run loop.

Codex is the second terminal provider: OpenAI's `codex exec` on the server's ChatGPT login, the same text-mode shape
(codex_cli.py). Each has its own parallel limit and usage-limit clock, since each runs on its own plan.
"""
import functools, json, logging, os, re, secrets, shutil, subprocess, tempfile, threading, time, urllib.error, urllib.request
from urllib.parse import urlparse

import anthropic

from . import agent_core, busy, cli_accounts, cli_parallel, codex_bridge, codex_cli, copilot_cli, model_switch, terminal_bridge

_log = logging.getLogger(__name__)

PROVIDERS = {"anthropic": "Claude", "openai": "OpenAI", "openrouter": "OpenRouter", "copilot": "GitHub Copilot", "local": "Local",
             "terminal": "Terminal", "codex": "Codex", "copilot-cli": "GitHub Copilot CLI"}
EFFORTS = ("low", "medium", "high")
DEFAULT_CLAUDE = os.getenv("AGENT_MODEL", "claude-opus-5-5")
OPENAI_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENROUTER_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
# GitHub Copilot's OpenAI-style API: a GitHub token with Copilot access (a fine-grained PAT with "Copilot Requests") is the key
COPILOT_URL = os.getenv("COPILOT_BASE_URL", "https://api.githubcopilot.com")
MAX_TOKENS = 16000
STRUCT_OUT = 4000  # a structured (JSON) answer's output cap, on every API provider
CLAUDE_CLI = os.getenv("CLAUDE_CLI", "claude")
CLI_TIMEOUT = int(os.getenv("CLAUDE_CLI_TIMEOUT", "300"))  # per turn at medium effort; low gets half, high double
CLI_EFFORT_TIMEOUT = {"low": .5, "medium": 1, "high": 2}
# every CLI turn shares one plan quota with the owner's own Claude Code sessions: at most this many run at once
TERMINAL_PARALLEL = cli_parallel.DEFAULT["terminal"]  # the environment's default; live: cli_parallel.limit("terminal") (Agents → Models)
CLI_GATE = cli_parallel.Gate("terminal")
# aliases the CLI resolves to the latest model of each family, so the list never goes stale
TERMINAL_MODELS = [("fable", "Claude Code · Fable"), ("opus", "Claude Code · Opus"), ("sonnet", "Claude Code · Sonnet"), ("haiku", "Claude Code · Haiku")]
# further server logins, each offered as its own Terminal model ("terminal:<id>") while its token is set:
# id -> (label, the environment variable with its `claude setup-token` token, the CLI model alias it runs)
TERMINAL_LOGINS = {"claude-37": ("Claude-37", "CLAUDE_CODE_OAUTH_TOKEN1", "opus")}

def terminal_cli_model(model):
    """The `--model` the CLI gets for a Terminal model id: a named login's alias, else the id itself."""
    named = TERMINAL_LOGINS.get(model)
    return named[2] if named else model

def terminal_logins():
    """The named logins whose token is set and that aren't switched off in Agents → Models, as [(id, label)]."""
    db = cli_accounts.S.get("db")
    return [(m, label) for m, (label, var, _) in TERMINAL_LOGINS.items() if os.getenv(var) and not model_switch.off(db, f"login:{m}")]
# the CLI's built-in tools, MCP servers, hooks, CLAUDE.md and plugins stay off: it only writes text
CLI_FLAGS = ["-p", "--output-format", "json", "--tools", "", "--safe-mode", "--strict-mcp-config", "--no-session-persistence"]
TERMINAL_REPLY = {"type": "object", "required": ["text", "tool_calls"], "properties": {
    "text": {"type": "string"},
    "tool_calls": {"type": "array", "items": {"type": "object", "required": ["name", "input"],
                                              "properties": {"name": {"type": "string"}, "input": {"type": "object"}}}}}}
MODELS_TTL = 300
# chat-capable OpenAI models; the list endpoint also returns embeddings, audio, image and moderation models
OPENAI_CHAT = re.compile(r"^(gpt-|o\d|chatgpt-)")
OPENAI_SKIP = re.compile(r"audio|realtime|tts|transcribe|image|embedding|moderation|search|instruct|similarity|davinci|babbage")

class LLMError(Exception):
    """A provider call failed; the message is safe to show to the user."""

class QuotaError(LLMError):
    """The Claude Code plan's usage limit is reached: the run should wait for the reset, it didn't fail.
    The message says "rate limit" so failure classifiers (Autoloop, Upgrade) retry it instead of counting it."""

class RateLimited(LLMError):
    """A brief rate limit (a per-minute 429): the plan's usage isn't used up, so no login waits for a
    reset. `wait`: the seconds the message asks for (None when it names none). The message says "rate-limited", so failure
    classifiers (Autoloop's "rate", Upgrade's retry) try again after a short wait."""
    def __init__(self, msg, wait=None):
        super().__init__(msg)
        self.wait = wait

# A plan CLI's limit message, told apart (Agent_Company's V1: one per-minute 429 held a login for 30 min as if its plan were
# used up). The plan's usage limit: "You've hit your limit · resets 3pm", "5-hour limit reached ∙ resets", "Claude AI usage
# limit reached|1762…", "Weekly limit reached for …", Codex "You've hit your usage limit… try again at 3:45 PM".
# A brief one: "Rate limit reached for gpt-5 … try again in 1.2s", "API Error: 429 … rate_limit_error".
PLAN_LIMIT = re.compile(r"hit your (?:\w+ )?limit|reached your (?:\w+ )?limit|usage[ _]limit|out of extra usage"
                        r"|(?<!rate )(?<!budget )(?<!token )(?<!output )\blimit (?:reached|exceeded)", re.I)
BILLING = re.compile(r"insufficient_quota|exceeded your current quota|credit balance", re.I)
BRIEF_LIMIT = re.compile(r"rate.?limit|\b429\b|too many requests", re.I)  # "overloaded" (529) stays a plain error, as before
RATE_AS_PLAN = 600       # a "rate limit" that asks for this long or longer holds the login like the plan's usage limit
RATE_RETRY_MAX = 20      # a brief limit asking for up to this many seconds is waited out and tried once more, in place
RATE_RETRY_DEFAULT = 10  # …and one that names no wait after this many

def limit_wait(msg):
    """The seconds a limit message asks for ("try again in 1.2s", "retry after 30", "in 20 minutes"), else None."""
    m = re.search(r"(?:try again|retry)\s+(?:in|after)\s+(\d+(?:\.\d+)?)\s*(ms|millisec\w*|s|secs?|seconds?|m|mins?|minutes?|h|hrs?|hours?)?\b",
                  msg or "", re.I)
    if not m: return None
    unit = (m[2] or "s").lower()
    if unit == "ms" or unit.startswith("milli"): return float(m[1]) / 1000
    return float(m[1]) * (3600 if unit.startswith("h") else 60 if unit.startswith("m") else 1)

def limit_kind(msg):
    """("plan", wait) for the plan's usage limit, ("brief", wait) for a short rate limit, else (None, None)."""
    wait = limit_wait(msg)
    if BILLING.search(msg or ""): return None, None  # out of credit: the provider's own words, a plain error
    if PLAN_LIMIT.search(msg or ""): return "plan", wait
    if BRIEF_LIMIT.search(msg or ""): return ("plan" if wait and wait >= RATE_AS_PLAN else "brief"), wait
    return None, None

_gated = threading.local()  # the budget gate (_gate) the model call on this thread passed: retry_brief reserves its retry the same way

def retry_brief(once, *a, **kw):
    """`once(*a, **kw)`, waiting out one brief rate limit and trying once more (the login's gate is free while it waits). G5-4
    closure (A2 defect 1): when the limited attempt settled the call's reservation (its result reported usage), the retry is a new
    model call and takes a new reservation through the same gate first; a refusal stops it as any budget refusal does."""
    g = _gated.__dict__.pop("args", None)  # consumed here, whatever happens
    if g is not None and (not g["hold"] or g["hold"] != agent_core.hold_id()):
        g = None  # left by another call (an API call, a refused gate, another run): only the gate whose hold is in flight counts
    try: return once(*a, **kw)
    except RateLimited as e:
        if e.wait is not None and e.wait > RATE_RETRY_MAX: raise
        time.sleep(RATE_RETRY_DEFAULT if e.wait is None else max(e.wait, 0.5))
        if g is not None and not agent_core.holding():
            why = agent_core.admit(g["estimate"], bound=g["bound"], model=g["model"], reserve=g["reserve"])
            if why: raise LLMError(why)
        return once(*a, **kw)

def anthropic_message(e):
    """User-facing message for a failed Claude call (None if `e` isn't an API error)."""
    if isinstance(e, anthropic.AuthenticationError):
        return "The Claude API key is invalid. Update it in Agents → Models."
    if isinstance(e, anthropic.RateLimitError):
        return "Claude is rate-limited right now. Try again in a minute."
    if isinstance(e, anthropic.APIStatusError):
        detail = ((e.body or {}).get("error") or {}).get("message") if isinstance(e.body, dict) else None
        if detail and "credit balance" in detail:
            return "The Anthropic account behind this API key has no credits. Add credits under Plans & Billing at console.anthropic.com."
        return f"Claude API error ({e.status_code}): {detail}" if detail else f"Claude API error ({e.status_code}). Try again."
    if isinstance(e, anthropic.APIConnectionError):
        return "Couldn't reach the Claude API from the server."
    return None

ANTHROPIC_ERRORS = (anthropic.APIStatusError, anthropic.APIConnectionError)

def model_label(provider, model, display=None):
    if display: return display
    if provider == "openai":
        return re.sub(r"^gpt", "GPT", re.sub(r"^chatgpt", "ChatGPT", model))
    return model

def check_url(url):
    url = (url or "").strip().rstrip("/")
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise LLMError("Enter the server's base URL, e.g. http://host.docker.internal:11434/v1")
    return url

# ---------- OpenAI-compatible HTTP ----------
def _http(provider, base, key, path, body=None, timeout=60):
    headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {key}"} if key else {})}
    if provider == "openrouter": headers["X-Title"] = "AXoR"  # shows the app in the OpenRouter activity log
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try: err = json.loads(raw).get("error") or {}
        except (ValueError, AttributeError): err = {"message": raw.strip()[:300]}  # GitHub Copilot answers errors in plain text
        if isinstance(err, str): err = {"message": err}
        raise _http_error(provider, e.code, err.get("message") or "", err.get("code") or err.get("type") or "")
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        where = urlparse(base).netloc
        hint = (" If it runs on this machine, use http://host.docker.internal:<port>/v1 and start the container with "
                "--add-host=host.docker.internal:host-gateway.") if provider == "local" and re.match(r"(localhost|127\.)", where) else ""
        raise LLMError(f"Couldn't reach {PROVIDERS[provider]} at {where}: {getattr(e, 'reason', e)}.{hint}")

class HTTPStatusError(LLMError):
    def __init__(self, msg, status, detail):
        super().__init__(msg); self.status, self.detail = status, detail

def _http_error(provider, status, message, code):
    name = PROVIDERS[provider]
    if status == 401 and provider == "copilot":
        msg = "GitHub rejected this token, or it has no Copilot access. Use a token with the Copilot Requests permission (Agents → Models)."
    elif status in (400, 403) and provider == "copilot":
        # e.g. a classic ghp_ token, or a fine-grained one without the Copilot permission: GitHub signs it in, Copilot refuses it
        msg = (f"GitHub's Copilot API refused this token ({status}{': ' + message if message else ''}). Copilot needs a fine-grained "
               "token (github_pat_…) with Account permissions → Copilot Requests: Read, from an account with a Copilot plan; "
               "classic ghp_ tokens aren't accepted. Create one at github.com/settings/personal-access-tokens/new.")
    elif status == 401:
        msg = f"The {name} API key is invalid. Update it in Agents → Models." if provider != "local" else f"The {name} server rejected the API key."
    elif provider == "openrouter" and status == 402:
        msg = "The OpenRouter account behind this API key is out of credits. Add credits at openrouter.ai/settings/credits."
    elif code == "insufficient_quota":
        msg = "The OpenAI account behind this API key has no credits. Add credits under Billing at platform.openai.com."
    elif status == 429:
        msg = f"{name} is rate-limited right now. Try again in a minute."
    elif status == 404 and ("model" in message.lower() or code == "model_not_found"):
        msg = f"{name} doesn't have that model: {message}" if message else f"{name} doesn't have that model."
    else:
        msg = f"{name} error ({status}): {message}" if message else f"{name} error ({status}). Try again."
    return HTTPStatusError(msg, status, f"{code} {message}".lower())

def _to_openai(system, messages):
    out = [{"role": "system", "content": system}]
    for m in messages:
        blocks = m["content"] if isinstance(m["content"], list) else [{"type": "text", "text": m["content"]}]
        texts = [b["text"] for b in blocks if b.get("type") == "text" and b.get("text")]
        if m["role"] == "assistant":
            calls = [{"id": b["id"], "type": "function", "function": {"name": b["name"], "arguments": json.dumps(b.get("input") or {})}}
                     for b in blocks if b.get("type") == "tool_use"]
            if texts or calls:
                out.append({"role": "assistant", "content": "\n\n".join(texts) or None, **({"tool_calls": calls} if calls else {})})
        else:
            for b in blocks:  # tool results must directly follow the assistant message that called them
                if b.get("type") == "tool_result":
                    c = b.get("content")
                    out.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": c if isinstance(c, str) else json.dumps(c)})
            if texts: out.append({"role": "user", "content": "\n\n".join(texts)})
    return out

def _from_openai(msg):
    blocks = [{"type": "text", "text": msg["content"]}] if (msg.get("content") or "").strip() else []
    for c in msg.get("tool_calls") or []:
        fn = c.get("function") or {}
        try: args = json.loads(fn.get("arguments") or "{}")
        except ValueError: args = {}
        cid = c.get("id") or ""
        blocks.append({"type": "tool_use", "id": cid if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", cid) else "toolu_" + secrets.token_hex(8),
                       "name": fn.get("name", ""), "input": args if isinstance(args, dict) else {}})
    return blocks

def _json_text(text):
    text = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text or "")
    try: return json.loads(text)
    except ValueError: raise LLMError("The model returned an unreadable answer. Try again or pick another model.")

def _gate(estimate=None, bound=None, model=None, reserve=None):
    """The agent core's budget: a run whose owner used up today's limit makes no more model calls. Milestone 3: under a stopping
    limit the call reserves its estimate first (agent_core.admit), and its use settles the reservation (used / call_failed)."""
    _gated.__dict__.pop("args", None)
    why = agent_core.admit(estimate, bound=bound, model=model, reserve=reserve)
    if why: raise LLMError(why)
    # the gate this call passed, bound to the hold it took (retry_brief reserves a retry the same way, only for that hold)
    _gated.args = {"estimate": estimate, "bound": bound, "model": model, "reserve": reserve, "hold": agent_core.hold_id()}


def _bound(out_cap, *parts):
    """The most an API call can bill: never more input tokens than the UTF-8 bytes of what is sent, plus its output cap."""
    n = 0
    for x in parts:
        if x is None: continue
        n += len((x if isinstance(x, str) else json.dumps(x, default=str)).encode("utf-8", "replace"))
    return n + int(out_cap or 0)


def _reserve_api(out_cap, *parts):
    """What an API call holds (Milestone 4): its input, estimated at one token per 3 bytes sent, plus its output cap, which the
    provider enforces. Conservative, not a guarantee (tokenization varies; tools add tokens): an overrun is recorded at settlement.
    AXOR_RESERVE_STRICT=1 holds the full bound instead."""
    n = 0
    for x in parts:
        if x is None: continue
        n += len((x if isinstance(x, str) else json.dumps(x, default=str)).encode("utf-8", "replace"))
    return -(-n // 3) + int(out_cap or 0)


def _counted_call(fn, *a, **kw):
    """Run one model call that admit() let through: its reservation is settled by used(), or by call_failed() if it raises."""
    try: return fn(*a, **kw)
    except BaseException as e:
        agent_core.call_failed(e)
        raise

def _max_out():
    """Output tokens one call may write: MAX_TOKENS, or less under a per-call limit of the run's (agent_core.call_cap)."""
    cap = agent_core.call_cap()
    return max(256, min(MAX_TOKENS, cap)) if cap else MAX_TOKENS

def _billed(resp):
    """Tokens a Claude response was billed for at full rate or more: input, cache writes and output (cache reads,
    a tenth of the price, aren't counted)."""
    u = getattr(resp, "usage", None)
    return sum(getattr(u, k, 0) or 0 for k in ("input_tokens", "cache_creation_input_tokens", "output_tokens")) if u else 0

# ---------- Claude Code CLI ----------
_NEW_TOKEN = ("run `claude setup-token` on any machine where you use Claude Code, put the token in .env as "
              "CLAUDE_CODE_OAUTH_TOKEN and redeploy (on Kubernetes `./k8s/redeploy.sh`, with Docker `docker compose up -d`). "
              "Without either, running `claude` once and logging in as the user that runs AXoR works too.")
NOT_SIGNED_IN = "Claude Code on the server isn't signed in. To sign it in, " + _NEW_TOKEN
TOKEN_REJECTED = ("Claude rejected the server's Claude Code login: the token in CLAUDE_CODE_OAUTH_TOKEN has expired or was revoked. "
                  "To replace it, " + _NEW_TOKEN)
def _cli_env():
    # never let the CLI fall back to an API key: it must use the machine's Claude Code login
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    tok = cli_accounts.server_token()  # a `claude setup-token` token connected in Agents → Models wins over the environment's
    if tok: env["CLAUDE_CODE_OAUTH_TOKEN"] = tok
    return env

def _cli_exe():
    exe = shutil.which(CLAUDE_CLI)
    if not exe:
        raise LLMError(f"The Claude Code CLI ({CLAUDE_CLI}) isn't installed on the server, or isn't on its PATH. Install it (the Docker "
                       "image includes it; rebuild with docker compose build), or set CLAUDE_CLI to its full path.")
    return exe

def cli_status(acct=None):
    """{"loggedIn", "authMethod", ...} from `claude auth status` (raises LLMError). `acct`: a cli_accounts login, else the server's."""
    try:
        r = subprocess.run([_cli_exe(), "auth", "status"], capture_output=True, text=True, timeout=30, env=acct.env if acct else _cli_env())
        st = json.loads(r.stdout)
    except subprocess.TimeoutExpired:
        raise LLMError("The Claude Code CLI didn't answer. Try again.")
    except (OSError, ValueError) as e:
        raise LLMError(f"Couldn't read the Claude Code sign-in status: {e}.")
    if not st.get("loggedIn"):
        raise LLMError(acct.not_signed_in if acct else NOT_SIGNED_IN)
    return st

_turn = threading.local()  # a caller's own per-turn limit for the CLIs, on its thread (turn_limit)

class turn_limit:
    """`with turn_limit(s):` every CLI turn made on this thread waits up to s seconds, whatever the effort (a Competition team's
    runs: mining_work.TEAM_TURN_S). Other callers keep CLI_TIMEOUT x effort; a falsy s changes nothing. Nests; restored on exit."""
    def __init__(self, seconds): self.s = int(seconds or 0)
    def __enter__(self):
        self.old = getattr(_turn, "s", 0)
        if self.s > 0: _turn.s = self.s
        return self
    def __exit__(self, *exc): _turn.s = self.old

def _cli_timeout(effort):
    own = getattr(_turn, "s", 0)
    return own if own > 0 else int(CLI_TIMEOUT * CLI_EFFORT_TIMEOUT.get(effort, 1))

def _cli(prompt, *args, timeout=CLI_TIMEOUT, acct=None):
    """One `claude -p` run with the prompt on stdin; returns the CLI's JSON result. Waits for a slot of the login's gate
    first (CLI_GATE for the server's; `acct` is a person's own, cli_accounts.py); the wait doesn't count toward `timeout`.
    A brief rate limit is waited out and the run tried once more (retry_brief)."""
    return retry_brief(_cli_once, prompt, *args, timeout=timeout, acct=acct)

def _cli_once(prompt, *args, timeout=CLI_TIMEOUT, acct=None):
    exe = _cli_exe()
    with (acct.gate if acct else CLI_GATE), tempfile.TemporaryDirectory(prefix="scout-cli-") as cwd:  # an empty folder, so no project files are in reach
        try:
            r = subprocess.run([exe, *CLI_FLAGS, *args], input=prompt, capture_output=True, text=True, timeout=timeout, cwd=cwd,
                               env=acct.env if acct else _cli_env())
        except subprocess.TimeoutExpired:
            # Milestone 2: the CLI ran until it was killed and reports usage only in its final result: unknown, never 0 (D-021)
            agent_core.unmetered(f"Claude Code timed out after {timeout} s before reporting its usage: this run's tokens are unknown.", single_call=True)  # D-036
            raise LLMError(f"Claude Code timed out after {timeout} s. Try again or lower the thinking effort.")
        except OSError as e:
            raise LLMError(f"Couldn't start the Claude Code CLI: {e}.")
    try:
        out = json.loads(r.stdout)
    except ValueError:
        last = ((r.stderr or r.stdout or "").strip().splitlines() or [""])[-1][:300]
        if r.returncode is not None and r.returncode < 0:  # killed by a signal (OOM, an operator) mid-run: its usage never came
            agent_core.unmetered(f"Claude Code was killed (signal {-r.returncode}) before reporting its usage: this run's tokens are unknown.", single_call=True)  # D-036
        raise LLMError(f"Claude Code failed{': ' + last if last else ''}.")
    if out.get("is_error"):
        # a failed run still spent what it reports (callers count only success); a result that reports its usage, even none, is a
        # known use: it settles the call's hold (Milestone 4), so the failure isn't taken for an unknown one
        if _cli_tokens(out) or isinstance(out.get("usage"), dict): agent_core.used(_cli_tokens(out))
        _cli_fail(str(out.get("result") or out.get("terminal_reason") or "unknown error"), cli=True, acct=acct)
    return out

_QUOTA = {"until": 0.0}  # when the Claude plan's usage limit resets, from the last limit the CLI hit
QUOTA_FALLBACK = 1800    # the CLI didn't say when: try again in 30 min

# ---------- Codex sessions a run leaves open (D-021: token metering) ----------
_open = threading.local()


def _track(session):
    """A Codex MCP session opened on this thread: settle_sessions() drains it if the run ends before Codex reports usage."""
    if not hasattr(_open, "sessions"): _open.sessions = []
    cur = getattr(agent_core._local, "run", None)
    session.run_id = cur.get("id") if cur else None  # the run its tokens belong to, whenever they are drained
    # strong references, so a session outlives its completer until it is drained (Long tasks return before they settle); the
    # list never grows unbounded: finished sessions drop out, and past OPEN_MAX the oldest is drained now
    live = [x for x in _open.sessions if not (getattr(x, "counted", False) or getattr(x, "drained", False))]
    while len(live) >= OPEN_MAX:
        old = live.pop(0)
        n = _drain(old, 10)
        if getattr(old, "holds", None): agent_core.settle(old.holds, n, getattr(old, "run_id", None)); old.holds = []
        elif n and getattr(old, "run_id", None): agent_core.add_tokens(old.run_id, n)
    _open.sessions = live + [session]


def _session_hold(s):
    """A Codex turn just returned (Milestone 3). Codex reports usage only when its session ends, so a turn that ends without it
    keeps the call's hold with the session (agent_core.defer), and the turn that reports it settles every hold of the session
    with the session's total (agent_core.absorb, then used())."""
    if not hasattr(s, "holds"): s.holds = []
    if getattr(s, "counted", False):
        if s.holds: agent_core.absorb(s.holds); s.holds = []
        return
    h = agent_core.defer()
    if h: s.holds.append(h)


REPLACE_DRAIN = 20  # a session replaced mid-run (Long tasks start one per step): wait this long for its usage
OPEN_MAX = 16      # Codex sessions a thread may leave open before the oldest is drained


def _drain(s, timeout=None):
    """Tokens of one session that ends early; None from drain() = no usage came: the session's own run is marked unmetered,
    never counted 0. A drain costs Codex one more short turn (it is told the run ended), inside the runs-at-once gate.
    Milestone 2: that turn is a model call, so the budget decides it first (over(), as before every call). Refused, or the
    budget can't be verified: Codex is stopped without it and the run is unmetered, so a drain never gets past a budget."""
    why = agent_core.over() if not (getattr(s, "counted", False) or getattr(s, "drained", False)) and hasattr(s, "abort") else None
    if why:
        s.abort()
        agent_core.unmetered(f"A Codex session's closing turn was refused by the budget ({str(why)[:160]}): this run's tokens are unknown.",
                             getattr(s, "run_id", None))
        agent_core.unknown_outcome(getattr(s, "holds", None), "the session was stopped before reporting its usage"); s.holds = []
        _log.warning("codex: the budget refused a session's closing turn; the run is marked unmetered")
        return 0
    n = s.drain() if timeout is None else s.drain(timeout)
    if n is None:
        agent_core.unmetered("A Codex session ended without reporting its usage: this run's tokens are unknown.", getattr(s, "run_id", None))
        agent_core.unknown_outcome(getattr(s, "holds", None), "the session ended without reporting its usage"); s.holds = []
        _log.warning("codex: a session ended without reporting usage; the run is marked unmetered")
        return 0
    return n


def settle_sessions(quick=False):
    """run_loop's end (agents.run_loop): every Codex session this thread opened and left before Codex reported usage is drained,
    its tokens counted on this thread's run (agent_core.used) and returned for the caller's own count. quick: the loop ended
    in an error, so it waits less."""
    ss, _open.sessions = getattr(_open, "sessions", []) or [], []
    cur = getattr(agent_core._local, "run", None)
    here, total = cur.get("id") if cur else None, 0
    ledgered = 0
    for s in ss:
        if getattr(s, "counted", True) or getattr(s, "drained", False): continue
        n = _drain(s, 10 if quick else None)
        if getattr(s, "holds", None):  # Milestone 3: the session's holds settle with its total, which counts it on its run once
            agent_core.settle(s.holds, n, getattr(s, "run_id", None) or here); s.holds = []
            if getattr(s, "run_id", None) in (None, here): total += n; ledgered += n
            continue
        if getattr(s, "run_id", None) == here: total += n
        elif n and getattr(s, "run_id", None): agent_core.add_tokens(s.run_id, n)  # opened by an earlier run on this thread: its own
    if total - ledgered: agent_core.used(total - ledgered)
    return total


def _attribute_api(p):
    """Per-run login attribution (D-019) for providers that don't run on a CLI plan: the server's key ("api:<provider>"), so a run
    without a login recorded means a missed record, never "an API call". Plan CLIs record theirs in cli_accounts.attribute."""
    if p in PLAN_PROVIDERS: return
    agent_core.login(f"server:{p}" if p == "copilot-cli" else f"api:{p}", "server" if p == "copilot-cli" else "api")


API_PROVIDERS = ("anthropic", "openai", "openrouter", "local", "copilot")  # billed per call, with an output cap: a call's bound is known (_bound)
PLAN_PROVIDERS = ("terminal", "codex")  # CLIs on the owner's own plan: they wait for its usage limit and run a few at a time

def quota_until(provider="terminal", owner=None):
    """Until when every run on a plan provider (Terminal: the Claude plan, Codex: the ChatGPT plan) should wait for the
    plan's usage limit (0 when it isn't reached). `owner`: the user whose runs ask; their own login has its own clock."""
    a = cli_accounts.peek(provider, owner)  # their own login, the server's, or a shared teammate's
    if a and a.uid: return a.quota["until"] if a.quota["until"] > time.time() else 0.0
    if provider == "codex": return codex_cli.quota_until()
    return _QUOTA["until"] if _QUOTA["until"] > time.time() else 0.0

def plan_parallel(provider="terminal"):
    """How many turns the provider's CLI runs at once (per login; set in Agents → Models)."""
    return cli_parallel.limit("codex" if provider == "codex" else "terminal")

def _reset_at(msg, now=None):
    """The reset time in a CLI limit message: "…limit reached|1762200000" or "…resets 3pm" / "resets at 15:30"."""
    now = now or time.time()
    if (m := re.search(r"\|(\d{10})\b", msg)): return float(m[1])
    m = re.search(r"resets?\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", msg, re.I)
    if not m: return now + QUOTA_FALLBACK
    h, mi = int(m[1]) % 24, int(m[2] or 0)
    if m[3]: h = h % 12 + (12 if m[3].lower() == "pm" else 0)
    t = time.localtime(now)
    at = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, h, mi, 0, 0, 0, -1))
    return at + 86400 if at <= now else at

def _cli_fail(msg, cli=False, acct=None):
    """Raises the user-facing error for a failed CLI run; `cli` means `msg` is the CLI's own error text. `acct`: the
    person's own login it ran on (cli_accounts.py), whose usage-limit clock it sets; else the server's."""
    if not cli: raise LLMError(msg)
    if "not logged in" in msg.lower() or "/login" in msg or "oauth" in msg.lower() or "401" in msg:
        # `auth status` said signed in (it trusts any token), so the token itself was refused: say so, with the CLI's words
        mine = acct and (acct.uid or acct.var)  # a person's own login, or a named server login (TERMINAL_LOGINS)
        _log.warning("Claude Code login refused (%s): %s", f"user {acct.uid}" if acct and acct.uid else acct.var if mine else "server", msg[:300])
        raise LLMError(f"{acct.not_signed_in if mine else TOKEN_REJECTED} Claude Code said: {msg[:200]}")
    kind, wait = limit_kind(msg)
    if kind == "brief":  # a per-minute limit: nothing waits for a reset
        raise RateLimited(f"Claude Code is rate-limited right now{acct.whose if acct else ''} (a brief limit, the plan isn't used up). "
                          f"Try again in a minute. {msg[:300]}", wait)
    if kind == "plan":
        q = acct.quota if acct else _QUOTA
        said = re.search(r"\|\d{10}\b|resets?\s", msg, re.I)  # the CLI named the reset; else the wait it asked for, else 30 min
        q["until"] = max(q["until"], _reset_at(msg) if said or not wait else time.time() + wait)
        raise QuotaError(f"Claude Code plan rate limit reached{acct.whose if acct else ''}; runs resume after the reset at "
                         f"{time.strftime('%H:%M', time.localtime(q['until']))}. {msg[:300]}")
    raise LLMError(f"Claude Code error: {msg[:300]}")

def cli_check(acct=None):
    """A tiny real prompt: `auth status` trusts any token, so this is what proves the login works."""
    cli_status(acct)
    _cli("Reply with OK.", "--system-prompt", "Reply with OK.", "--model", "haiku", "--effort", "low", timeout=120, acct=acct)

CLI_CACHE_READS = os.getenv("CLI_COUNT_CACHE_READS", "0") == "1"

def _cli_tokens(out):
    """Tokens of a Claude Code CLI turn, counted as an API call is (_billed): input, cache writes and output. Cache reads were
    counted here too until 11-11: one CLI turn re-reads its whole context on every step, so a team on the plan showed ten times
    the tokens of the same work through the API and ran far past a budget set in billed tokens. CLI_COUNT_CACHE_READS=1 restores it."""
    u = out.get("usage") or {}
    keys = ("input_tokens", "output_tokens", "cache_creation_input_tokens") + (("cache_read_input_tokens",) if CLI_CACHE_READS else ())
    return sum(u.get(k) or 0 for k in keys)

def _cli_json(out):
    return out["structured_output"] if isinstance(out.get("structured_output"), (dict, list)) else _json_text(out.get("result"))

def _transcript(messages):
    """The conversation as plain text for the CLI, tool calls and results included."""
    names, parts = {}, []
    for m in messages:
        blocks = m["content"] if isinstance(m["content"], list) else [{"type": "text", "text": m["content"]}]
        for b in blocks:
            t = b.get("type")
            if t == "text" and b.get("text"):
                parts.append(f"<{m['role']}>\n{b['text']}\n</{m['role']}>")
            elif t == "tool_use":
                names[b["id"]] = b["name"]
                parts.append(f'<tool_call name="{b["name"]}">\n{json.dumps(b.get("input") or {})}\n</tool_call>')
            elif t == "tool_result":
                c = b.get("content")
                parts.append(f'<tool_result name="{names.get(b["tool_use_id"], "")}"{" error" if b.get("is_error") else ""}>\n'
                             f'{c if isinstance(c, str) else json.dumps(c)}\n</tool_result>')
    return "\n\n".join(parts) + "\n\nWrite the assistant's next turn."

def _bad_calls(calls, tools):
    """What's wrong with a Terminal reply's tool calls: unknown tools, or inputs missing required fields."""
    known, out = {t["name"]: t for t in tools or []}, []
    for c in calls or []:
        if not isinstance(c, dict) or not c.get("name"): out.append("A tool call has no name."); continue
        t = known.get(c["name"])
        if not t: out.append(f"There is no tool named {c['name']}. The tools are: {', '.join(known) or 'none'}."); continue
        inp = c.get("input") if isinstance(c.get("input"), dict) else {}
        missing = [k for k in (t.get("input_schema") or {}).get("required") or [] if k not in inp]
        if missing: out.append(f"{c['name']} needs {', '.join(missing)} in its input.")
    return out

def _text_turn(turn, system, tools, messages, who):
    """One model turn of a CLI that writes its tool calls as JSON text (Terminal text mode, Codex), as run-loop blocks.
    `turn(system, tools, transcript)` returns (tokens, reply dict or None); a reply can be unreadable or call a tool wrongly,
    so there's one retry with the reason. A reply's "_problems" are extra reasons (e.g. tool input that isn't JSON)."""
    transcript = _transcript(messages)
    used, reply = turn(system, tools, transcript)
    bad = lambda r: (["Your reply wasn't the JSON object asked for."] if not isinstance(r, dict)
                     else list(r.get("_problems") or []) + _bad_calls(r.get("tool_calls"), tools))
    problems = bad(reply)
    if problems:
        more, reply = turn(system, tools, transcript + "\n\nYour previous reply was rejected:\n- " + "\n- ".join(problems) +
                           "\nWrite the turn again, fixing that.")
        used += more
    if not isinstance(reply, dict): raise LLMError(f"{who} returned an unreadable answer. Try again.")
    blocks = [{"type": "text", "text": reply["text"]}] if (reply.get("text") or "").strip() else []
    blocks += [{"type": "tool_use", "id": "toolu_" + secrets.token_hex(8), "name": c["name"],
                "input": c.get("input") if isinstance(c.get("input"), dict) else {}}
               for c in reply.get("tool_calls") or [] if isinstance(c, dict) and c.get("name")]
    stop = "tool_use" if any(b["type"] == "tool_use" for b in blocks) else "end_turn"
    return blocks, stop, used

def _terminal_system(system, tools):
    if not tools:
        return system + "\n\nReply with JSON: your answer (Markdown) in `text`, and `tool_calls` empty."
    spec = "\n".join(f"- {t['name']}: {t['description']}\n  input schema: {json.dumps(t['input_schema'])}" for t in tools)
    return (system + "\n\n# Tools\nThese tools are available. They aren't native function calls: you call one by listing it in "
            "`tool_calls` in your JSON reply, and the application runs it and adds the result to the conversation.\n" + spec +
            "\n\n# Reply format\nThe conversation so far is in the user message, with earlier <tool_call>s and their "
            "<tool_result>s. Reply with JSON. When you need data a tool can give, call it: list it in `tool_calls` (each "
            "`input` must match the tool's schema) and keep `text` to a short note or empty. When you have what you need, "
            "put your answer (Markdown) in `text` and leave `tool_calls` empty. Never invent tool results.")

class Providers:
    def __init__(self, db, box, anthropic_factory=None):
        self.db, self.box, self.fake = db, box, anthropic_factory
        self._cache, self._lock = {}, threading.Lock()

    # ---------- configuration ----------
    def anthropic_key(self): return self.box.get("anthropic_api_key") or os.getenv("ANTHROPIC_API_KEY") or None
    def openai_key(self): return self.box.get("openai_api_key") or os.getenv("OPENAI_API_KEY") or None
    def openrouter_key(self): return self.box.get("openrouter_api_key") or os.getenv("OPENROUTER_API_KEY") or None
    def copilot_key(self): return self.box.get("copilot_api_key") or os.getenv("COPILOT_API_KEY") or None
    # the Copilot CLI's GitHub token (copilot_cli.py): saved in Agents → Models, or COPILOT_GITHUB_TOKEN in the server's environment
    def copilot_cli_token(self): return self.box.get("copilot_github_token") or os.getenv("COPILOT_GITHUB_TOKEN") or None
    def local_url(self): return self.db.setting("local_llm_url") or os.getenv("LOCAL_LLM_URL") or None
    def local_key(self): return self.box.get("local_llm_key") or os.getenv("LOCAL_LLM_KEY") or None
    def terminal_on(self): return self.db.setting("terminal_enabled") == "1" or os.getenv("CLAUDE_CLI_ENABLED") == "1"
    def codex_on(self): return self.db.setting("codex_enabled") == "1" or os.getenv("CODEX_CLI_ENABLED") == "1"
    def terminal_mode(self):
        """"text": tool calls written as JSON text, one CLI run per turn (the default). "mcp": real tool calls, one session per run."""
        m = (self.db.setting("terminal_mode") if self.db else None) or os.getenv("TERMINAL_MODE") or "text"
        return m if m in ("text", "mcp") else "text"
    def codex_mode(self):
        """Codex: "mcp" (the default): native tool calls, one `codex exec` session per run (codex_bridge.py). "text": tool
        calls written as JSON text, one run per turn."""
        m = (self.db.setting("codex_mode") if self.db else None) or os.getenv("CODEX_MODE") or "mcp"
        return m if m in ("text", "mcp") else "mcp"

    def server_configured(self, p):
        """Connected for the whole server (Agents → Models)."""
        return bool({"anthropic": self.anthropic_key() or self.fake, "openai": self.openai_key(), "openrouter": self.openrouter_key(),
                     "copilot": self.copilot_key(), "local": self.local_url(), "terminal": self.terminal_on(), "codex": self.codex_on(),
                     "copilot-cli": self.copilot_cli_token()}[p])

    def server_on(self, p):
        """The server's connection is set and its card isn't switched off (model_switch.py)."""
        return self.server_configured(p) and not model_switch.off(self.db, p)

    def configured(self, p):
        """Offered at all: connected for the server (and switched on), or (Terminal, Codex) someone connected their own login (cli_accounts.py)."""
        return (self.server_on(p) or (p in PLAN_PROVIDERS and cli_accounts.any_connected(p))
                or (p == "terminal" and bool(terminal_logins())))

    def any_configured(self):
        return any(self.configured(p) for p in PROVIDERS)

    def source(self, p):
        stored = {"anthropic": self.box.get("anthropic_api_key"), "openai": self.box.get("openai_api_key"),
                  "openrouter": self.box.get("openrouter_api_key"), "copilot": self.box.get("copilot_api_key"), "local": self.db.setting("local_llm_url"),
                  "terminal": self.db.setting("terminal_enabled") == "1", "codex": self.db.setting("codex_enabled") == "1",
                  "copilot-cli": self.box.get("copilot_github_token")}[p]
        env = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "openrouter": "OPENROUTER_API_KEY", "copilot": "COPILOT_API_KEY", "local": "LOCAL_LLM_URL",
               "terminal": "CLAUDE_CLI_ENABLED", "codex": "CODEX_CLI_ENABLED", "copilot-cli": "COPILOT_GITHUB_TOKEN"}[p]
        return "ui" if stored else "env" if os.getenv(env) else None

    def forget(self, p=None):
        """Drop the cached model lists (all, or one provider's) so the next catalog() lists again."""
        with self._lock:
            if p is None: self._cache.clear()
            else: self._cache.pop(p, None)

    def _anthropic(self, key=None):
        return self.fake() if self.fake and not key else anthropic.Anthropic(api_key=key or self.anthropic_key(), max_retries=2)

    # ---------- model lists ----------
    def list_models(self, p, key=None, url=None):
        """Raw model list from a provider (raises LLMError). key/url override the saved settings, for verification."""
        if p == "anthropic":
            if self.fake and not key:
                return [{"id": DEFAULT_CLAUDE, "label": "Claude (test client)"}]
            try:
                page = self._anthropic(key).models.list(limit=100)
            except anthropic.AuthenticationError:
                raise LLMError("Anthropic rejected this key. Check that you copied the whole key.")
            except anthropic.PermissionDeniedError:
                raise LLMError("This key doesn't have permission to use the API.")
            except ANTHROPIC_ERRORS as e:
                raise LLMError(anthropic_message(e))
            return [{"id": m.id, "label": m.display_name or m.id} for m in page.data]
        if p == "openai":
            data = _http(p, OPENAI_URL, key or self.openai_key(), "/models", timeout=15).get("data", [])
            data = [m for m in data if OPENAI_CHAT.match(m["id"]) and not OPENAI_SKIP.search(m["id"])]
            return [{"id": m["id"], "label": model_label(p, m["id"])} for m in sorted(data, key=lambda m: -(m.get("created") or 0))]
        if p == "openrouter":
            key = key or self.openrouter_key()
            _http(p, OPENROUTER_URL, key, "/key", timeout=15)  # the model list is public, so check the key separately
            data = _http(p, OPENROUTER_URL, key, "/models", timeout=20).get("data", [])
            # agents need tool calling; the list also has image, audio and plain-completion models
            data = [m for m in data if "tools" in (m.get("supported_parameters") or [])]
            free = lambda m: m["id"].endswith(":free") or all(str((m.get("pricing") or {}).get(k, "1")) in ("0", "0.0") for k in ("prompt", "completion"))
            return [{"id": m["id"], "label": m.get("name") or m["id"], "free": free(m)}
                    for m in sorted(data, key=lambda m: (m.get("name") or m["id"]).lower())]
        if p == "copilot":
            data = _http(p, COPILOT_URL, key or self.copilot_key(), "/models", timeout=20).get("data", [])
            # chat models that call tools over /chat/completions (the Responses-only GPT models don't), and not switched off by policy
            ok = lambda m: ((m.get("capabilities") or {}).get("type") == "chat" and ((m.get("capabilities") or {}).get("supports") or {}).get("tool_calls")
                            and (m.get("supported_endpoints") is None or "/chat/completions" in m["supported_endpoints"])
                            and (m.get("policy") or {}).get("state") != "disabled")
            seen, out = set(), []
            for m in data:
                if ok(m) and m["id"] not in seen:
                    seen.add(m["id"]); out.append({"id": m["id"], "label": f"Copilot · {m.get('name') or m['id']}"})
            return out
        if p == "terminal":
            if self.server_on(p): cli_status()  # the CLI is installed and signed in (people's own logins are checked when connected)
            base = TERMINAL_MODELS if self.server_on(p) or cli_accounts.any_connected(p) else []
            return [{"id": m, "label": label} for m, label in base + terminal_logins()]
        if p == "copilot-cli":
            copilot_cli.exe()  # installed (the token was proven with a real prompt when it was connected)
            return [{"id": m, "label": label} for m, label in copilot_cli.models()]
        if p == "codex":
            if self.server_on(p): codex_cli.status()  # the same for Codex
            return [{"id": m, "label": label} for m, label in codex_cli.models(None if self.server_on(p) else cli_accounts.any_home(p))]
        base = check_url(url or self.local_url())
        data = _http(p, base, key if url else self.local_key(), "/models", timeout=10).get("data", [])
        return [{"id": m["id"], "label": m["id"]} for m in sorted(data, key=lambda m: m["id"])]

    def catalog(self, refresh=False):
        """Every configured provider's models (cached for a few minutes), plus each provider's status."""
        out = []
        for p, label in PROVIDERS.items():
            entry = {"id": p, "label": label, "configured": self.configured(p), "models": [], "error": None}
            if entry["configured"]:
                with self._lock: hit = self._cache.get(p)
                if hit and not refresh and time.time() - hit[0] < MODELS_TTL:
                    entry["models"], entry["error"] = hit[1], hit[2]
                else:
                    try: models, err = self.list_models(p), None
                    except LLMError as e: models, err = [], str(e)
                    models = [{**m, "id": f"{p}:{m['id']}", "model": m["id"], "provider": p} for m in models]
                    with self._lock: self._cache[p] = (time.time(), models, err)
                    entry["models"], entry["error"] = models, err
            out.append(entry)
        return out

    def default_model(self, catalog=None):
        """The admin's default if it's still offered, else Claude's default, else the first model anyone offers."""
        catalog = catalog or self.catalog()
        offered = {e["id"]: [m["id"] for m in e["models"]] for e in catalog if e["configured"]}
        want = self.db.setting("default_model") or ""
        p = want.partition(":")[0]
        if p in offered and (want in offered[p] or not offered[p]):  # an empty list means listing failed: trust the setting
            return want
        if "anthropic" in offered:
            claude = f"anthropic:{DEFAULT_CLAUDE}"
            return claude if claude in offered["anthropic"] or not offered["anthropic"] else offered["anthropic"][0]
        return next((i for ids in offered.values() for i in ids), None)

    def resolve(self, choice):
        """'auto' / None -> the default model. Returns (provider, model id)."""
        if not choice or choice == "auto":
            choice = self.default_model()
            if not choice:
                raise LLMError("No model is available yet: an administrator needs to connect Claude, OpenAI, OpenRouter, a local server, Terminal or Codex in Agents → Models.")
        p, _, model = choice.partition(":")
        if p not in PROVIDERS or not model:
            raise LLMError("Unknown model. Pick one from the model menu.")
        if p == "terminal" and model in TERMINAL_LOGINS and model_switch.off(self.db, f"login:{model}"):
            raise LLMError(f"{TERMINAL_LOGINS[model][0]} is switched off in Agents → Models. Pick another model, or turn it on there.")
        if not self.configured(p):
            if self.server_configured(p) and model_switch.off(self.db, p):
                raise LLMError(f"{PROVIDERS[p]} is switched off in Agents → Models. Pick another model, or turn it on there.")
            raise LLMError(f"{PROVIDERS[p]} isn't connected. An administrator can set it up in Agents → Models.")
        if p in PLAN_PROVIDERS: cli_accounts.pick(p, cli_accounts.owner(), model)  # whose plan: says now when there's none for them
        return p, model

    # ---------- calls ----------
    def _endpoint(self, p):
        """(base URL, key) of an OpenAI-style provider."""
        if p == "openai": return OPENAI_URL, self.openai_key()
        if p == "openrouter": return OPENROUTER_URL, self.openrouter_key()
        if p == "copilot": return COPILOT_URL, self.copilot_key()
        return check_url(self.local_url()), self.local_key()

    def completer(self, choice, effort="medium"):
        """A function (system, tools, messages) -> (blocks, stop_reason, tokens) for the run loop, and the model's id.
        Each call counts as work in flight (busy.py) while it runs, and its tokens go to the run open on this thread (agent_core.py),
        whose owner's daily limit it checks first."""
        call, label = self._completer(choice, effort)
        p = label.partition(":")[0]
        def counted(system, tools, messages):
            reserve = getattr(call, "reserve", None)  # Codex: 0 when the call is the next turn of a session that holds already
            est = reserve(messages) if reserve else None
            api = p in API_PROVIDERS
            _gate(est, bound=_bound(_max_out(), system, tools, messages) if api else None, model=label,
                  reserve=_reserve_api(_max_out(), system, tools, messages) if api else None)
            _attribute_api(p)
            with busy.working("model"):
                out = _counted_call(call, system, tools, messages)
            agent_core.used(out[2] if isinstance(out, tuple) and len(out) > 2 else 0)
            return out
        return counted, label

    def structured(self, *a, **kw):
        """_structured, counted the same way as completer's calls; on_usage (keyword or 6th argument) still gets each count."""
        choice = a[0] if a else kw.get("choice")
        try:  # Milestone 4: "auto" resolves first, so an API call keeps its bound (an error then releases, not freezes)
            p, _m = self.resolve(choice); choice = f"{p}:{_m}"
        except Exception:  # noqa: BLE001 - unresolvable here: as before (the call itself raises what's wrong)
            p, choice = str(choice or "").partition(":")[0], str(choice or "auto")
        prompt = a[2] if len(a) > 2 else kw.get("prompt")
        system = a[1] if len(a) > 1 else kw.get("system")
        schema = a[3] if len(a) > 3 else kw.get("schema")
        msgs = a[7] if len(a) > 7 else kw.get("messages")
        api = p in API_PROVIDERS  # every API provider's structured call is capped at STRUCT_OUT output tokens (Milestone 4: OpenAI-style too)
        _gate(bound=_bound(STRUCT_OUT, system, prompt, msgs, schema) if api else None, model=choice,
              reserve=_reserve_api(STRUCT_OUT, system, prompt, msgs, schema) if api else None)
        a = list(a)
        theirs = a[5] if len(a) > 5 else kw.get("on_usage")
        def on_usage(n):
            agent_core.used(n)
            if theirs: theirs(n)
        if len(a) > 5: a[5] = on_usage
        else: kw["on_usage"] = on_usage
        with busy.working("model"): return _counted_call(self._structured, *a, **kw)

    def _completer(self, choice, effort="medium"):
        p, model = self.resolve(choice)
        effort = effort if effort in EFFORTS else "medium"
        if p == "anthropic":
            client = self._anthropic()
            def call(system, tools, messages):
                # the system prompt is cached: a tool loop re-sends it every step, and cache reads cost a tenth
                kw = dict(model=model, max_tokens=_max_out(), system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                          messages=[{"role": m["role"], "content": m["content"]} for m in messages], **({"tools": tools} if tools else {}))
                try:
                    try:
                        resp = client.beta.messages.create(**kw, output_config={"effort": effort},
                                                           betas=["server-side-fallback-2026-07-01"], fallbacks="default")
                    except anthropic.BadRequestError as e:
                        if "effort" not in str(e).lower() and "fallback" not in str(e).lower(): raise
                        resp = client.beta.messages.create(**kw)  # older models: no effort control / fallbacks
                except ANTHROPIC_ERRORS as e:
                    raise LLMError(anthropic_message(e))
                return [b.to_dict() if hasattr(b, "to_dict") else dict(b) for b in resp.content], resp.stop_reason, _billed(resp)
            return call, f"{p}:{model}"

        # the CLIs run on a person's plan: picked per call (cli_accounts.py), for the run's owner or whoever this was built for
        built = cli_accounts.owner() if p in PLAN_PROVIDERS else None
        login = lambda: cli_accounts.attribute(cli_accounts.pick(p, cli_accounts.owner(built), model))  # D-019: the run records the login
        if p == "terminal":
            run_model = terminal_cli_model(model)  # a named login (TERMINAL_LOGINS) runs its own alias
            def turn(system, tools, transcript, acct):
                out = _cli(transcript, "--system-prompt", _terminal_system(system, tools), "--model", run_model,
                           "--effort", effort, "--json-schema", json.dumps(TERMINAL_REPLY), timeout=_cli_timeout(effort), acct=acct)
                try: reply = _cli_json(out)
                except LLMError: reply = None
                return _cli_tokens(out), reply
            bridge = {}  # MCP mode: the open session of this run
            def mcp_call(system, tools, messages, acct):
                s = bridge.get("s")
                if s and s.expects(messages) and bridge.get("uid") == acct.uid:
                    s.answer(messages)
                else:  # a new run, or one that went on without us: start a session with the history as text
                    if s: s.close()
                    one = len(messages) == 1 and isinstance(messages[0]["content"], str)
                    s = bridge["s"] = terminal_bridge.Session(_cli_exe(), acct.env, run_model, effort, system, tools,
                                                              messages[0]["content"] if one else _transcript(messages),
                                                              _cli_timeout(effort), acct.gate, functools.partial(_cli_fail, acct=acct))
                    s.messages, bridge["uid"] = messages, acct.uid
                return s.turn()
            def call(system, tools, messages):
                acct = login()
                if tools and self.terminal_mode() == "mcp": return mcp_call(system, tools, messages, acct)
                return _text_turn(lambda s, t, tr: turn(s, t, tr, acct), system, tools, messages, "Claude Code")
            return call, f"{p}:{model}"

        if p == "codex":
            bridge = {}  # MCP mode: the open `codex exec` session of this run (codex_bridge.py)
            def mcp_call(system, tools, messages, acct):
                s = bridge.get("s")
                if s and s.expects(messages) and bridge.get("uid") == acct.uid:
                    s.answer(messages)
                else:  # a new run, or one that went on without us: start a session with the history as text
                    extra = _drain(s, REPLACE_DRAIN) if s else 0  # D-021: the replaced session's tokens still count, on this run
                    if s and getattr(s, "holds", None):  # its holds settle with this call, which counts its tokens (Milestone 3)
                        agent_core.absorb(s.holds); s.holds = []
                    one = len(messages) == 1 and isinstance(messages[0]["content"], str)
                    s = bridge["s"] = codex_bridge.CodexSession(codex_cli.exe(), acct.env, model, effort,
                                                                system, tools, messages[0]["content"] if one else _transcript(messages),
                                                                _cli_timeout(effort), acct.gate,
                                                                lambda msg, cli=False: codex_cli.fail(msg, acct))
                    s.messages, bridge["uid"] = messages, acct.uid
                    _track(s)
                    blocks, stop, tokens = s.turn()
                    _session_hold(s)
                    return blocks, stop, tokens + extra
                out = s.turn()
                _session_hold(s)
                return out
            def call(system, tools, messages):
                acct = login()
                if tools and self.codex_mode() == "mcp": return mcp_call(system, tools, messages, acct)
                return _text_turn(lambda s, t, transcript: codex_cli.turn(s, t, transcript, model, effort, _cli_timeout(effort), acct=acct),
                                  system, tools, messages, "Codex")
            def reserve(messages):
                """A turn of the open session holds nothing new: the session's first turn reserved for all of it (Milestone 3)."""
                s = bridge.get("s")
                return 0 if s and not getattr(s, "counted", False) and getattr(s, "holds", None) and s.expects(messages) else None
            call.reserve = reserve
            return call, f"{p}:{model}"

        if p == "copilot-cli":  # text mode only: tool calls written as JSON, one `copilot` run per turn
            def call(system, tools, messages):
                token = self.copilot_cli_token()
                return _text_turn(lambda s, t, transcript: copilot_cli.turn(s, t, transcript, model, token, _cli_timeout(effort)),
                                  system, tools, messages, "GitHub Copilot")
            return call, f"{p}:{model}"

        base, key = self._endpoint(p)
        openai_tools = lambda tools: [{"type": "function", "function": {
            "name": t["name"], "description": t["description"], "parameters": t["input_schema"],
            **({"strict": True} if p == "openai" and not t["name"].startswith("ext_") else {})}}  # ext_: MCP tools (mcp_hub.py), whose schemas rarely fit strict mode
            for t in tools]
        state = {"effort": p != "local"}  # local servers rarely understand reasoning_effort
        def call(system, tools, messages):
            body = {"model": model, "messages": _to_openai(system, messages)}
            if tools: body["tools"] = openai_tools(tools)
            body["max_completion_tokens" if p == "openai" else "max_tokens"] = _max_out()
            if state["effort"]:
                if p == "openrouter": body["reasoning"] = {"effort": effort}  # models without reasoning ignore it
                else: body["reasoning_effort"] = effort
            try:
                r = _http(p, base, key, "/chat/completions", body, timeout=300)
            except HTTPStatusError as e:
                if e.status != 400 or "reasoning" not in e.detail or not state["effort"]: raise
                state["effort"] = False; body.pop("reasoning_effort", None); body.pop("reasoning", None)  # non-reasoning model
                r = _http(p, base, key, "/chat/completions", body, timeout=300)
            choice = (r.get("choices") or [{}])[0]
            blocks = _from_openai(choice.get("message") or {})
            finish = choice.get("finish_reason")
            stop = "tool_use" if any(b["type"] == "tool_use" for b in blocks) else {"length": "max_tokens", "content_filter": "refusal"}.get(finish, "end_turn")
            u = r.get("usage") or {}
            return blocks, stop, (u.get("prompt_tokens") or 0) + (u.get("completion_tokens") or 0)
        return call, f"{p}:{model}"

    def _structured(self, choice, system, prompt, schema, name="result", on_usage=None, effort="low", messages=None):
        """One-shot JSON answer matching `schema`. `on_usage(tokens)` gets the call's token count; `messages` (alternating
        user and assistant turns, plain text) replaces the single prompt when given."""
        used = on_usage or (lambda n: None)
        p, model = self.resolve(choice)
        _attribute_api(p)  # D-019: API-key providers named on the run (plan CLIs are attributed where their login is handed over)
        msgs = messages or [{"role": "user", "content": prompt}]
        effort = effort if effort in EFFORTS else "low"
        if p == "anthropic":
            try:
                resp = self._anthropic().beta.messages.create(
                    model=model, max_tokens=STRUCT_OUT, system=system, messages=msgs,
                    output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}})
            except ANTHROPIC_ERRORS as e:
                raise LLMError(anthropic_message(e))
            used(_billed(resp))
            if resp.stop_reason == "refusal": raise LLMError("Claude declined that request.")
            return _json_text("".join(getattr(b, "text", "") for b in resp.content))
        if p == "terminal":
            out = _cli(_transcript(msgs) if messages else prompt, "--system-prompt", system + "\n\nReply with JSON matching the given schema.",
                       "--model", terminal_cli_model(model), "--effort", effort, "--json-schema", json.dumps(schema), timeout=_cli_timeout(effort),
                       acct=cli_accounts.attribute(cli_accounts.pick(p, cli_accounts.owner(), model)))
            used(_cli_tokens(out))
            return _cli_json(out)
        if p == "codex":
            answer, n = codex_cli.structured(system, _transcript(msgs) if messages else prompt, schema, model, effort, _cli_timeout(effort),
                                             acct=cli_accounts.attribute(cli_accounts.pick(p, cli_accounts.owner())))
            used(n)
            return answer
        if p == "copilot-cli":
            answer, n = copilot_cli.structured(system, _transcript(msgs) if messages else prompt, schema, model,
                                               self.copilot_cli_token(), _cli_timeout(effort))
            used(n)
            return answer
        base, key = self._endpoint(p)
        body = {"model": model, "messages": [{"role": "system", "content": system}, *msgs],
                "response_format": {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}}}
        if (getattr(agent_core._local, "run", None) or {}).get("hold"):  # capped only when a hold was taken (a stopping limit): its bound must hold;
            body["max_completion_tokens" if p == "openai" else "max_tokens"] = STRUCT_OUT  # without one, nothing changes (reasoning tokens count here)
        try:
            r = _http(p, base, key, "/chat/completions", body, timeout=300)
        except HTTPStatusError as e:
            if e.status != 400: raise
            # servers without JSON-schema support: plain JSON mode with the schema spelled out
            body["response_format"] = {"type": "json_object"}
            body["messages"][0]["content"] += "\n\nReply with only a JSON object matching this JSON schema:\n" + json.dumps(schema)
            r = _http(p, base, key, "/chat/completions", body, timeout=300)
        u = r.get("usage") or {}
        used((u.get("prompt_tokens") or 0) + (u.get("completion_tokens") or 0))
        return _json_text(((r.get("choices") or [{}])[0].get("message") or {}).get("content"))
