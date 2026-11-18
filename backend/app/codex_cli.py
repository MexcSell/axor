"""OpenAI's Codex CLI (`codex exec`) as an agent provider: the second terminal provider, next to Claude Code (llm.py's
"terminal"). It runs on the ChatGPT plan the CLI is signed in with, not an API key: that's what the OpenAI provider is for.

Every turn is one `codex exec` run in an empty folder with a read-only sandbox, the user's config, rules and session
files ignored, and every built-in tool off (shell, code mode, web search, browser, apps, plugins, sub-agents...): the
model only writes text. This file is Codex's text mode: tool calls come back as JSON text, like the Terminal provider's
text mode. Native tool calls (the default, Agents → Models → OpenAI (Codex) CLI → Tool calls) are codex_bridge.py: one session per
run through the same MCP bridge as Claude Code's.

The plan is the owner's own, shared with their Codex sessions: GATE lets PARALLEL turns run at once (separate from Claude's
CLI_GATE, since it's a separate plan), and a usage-limit error holds every Codex run until the reset (quota_until).
A teammate's own login (cli_accounts.py) comes in as `acct`: its own CODEX_HOME, gate and clock."""
import json, os, re, shutil, subprocess, tempfile, threading, time

from . import cli_parallel
from . import llm  # LLMError, QuotaError and the transcript helpers; used at call time only (llm imports this module)

CODEX_CLI = os.getenv("CODEX_CLI", "codex")
PARALLEL = cli_parallel.DEFAULT["codex"]  # the environment's default; the live limit is cli_parallel.limit("codex") (Agents → Models)
GATE = cli_parallel.Gate("codex")
# features that give the model a tool, or reach outside the turn; the shell itself is off too (and the sandbox is read-only)
FEATURES_OFF = ("shell_tool", "unified_exec", "code_mode_host", "apps", "plugins", "hooks", "multi_agent", "browser_use",
                "browser_use_external", "in_app_browser", "computer_use", "image_generation", "view_image", "goals",
                "tool_suggest", "skill_search", "sleep_tool", "shell_snapshot", "workspace_dependencies", "memories",
                "daemon_auto_start")
FLAGS = ["exec", "--json", "--ephemeral", "--skip-git-repo-check", "--ignore-user-config", "--ignore-rules",
         "-s", "read-only", "-c", "web_search=disabled", *[x for f in FEATURES_OFF for x in ("--disable", f)]]
DEFAULT = "default"  # no -m: the model Codex picks for the account
# a turn: strict structured output (no free-form objects), so each tool call's input is a JSON string
REPLY = {"type": "object", "additionalProperties": False, "required": ["text", "tool_calls"], "properties": {
    "text": {"type": "string"},
    "tool_calls": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["name", "input_json"],
                                              "properties": {"name": {"type": "string"}, "input_json": {"type": "string"}}}}}}
NOT_SIGNED_IN = ("Codex on the server isn't signed in. On Kubernetes run `kubectl -n axor exec -it deploy/web -- codex login "
                 "--device-auth` and finish the sign-in in a browser (it's saved in CODEX_HOME, /data/codex in the image). "
                 "Without Docker, run `codex login` once as the user that runs AXoR.")
COUNT_CACHED = os.getenv("CODEX_COUNT_CACHED", "0") == "1"

def billed(u):
    """Tokens of a Codex turn as AXoR counts them (Owner decision 2026-11-17): input and output, without the cached input.
    Codex reports cached_input_tokens as part of input_tokens: every turn re-reads the whole conversation from the cache, so
    counting it charged a Codex run about twice a Claude Code run for the same work. Claude Code's cache reads have been left
    out since 11-11 (llm._cli_tokens). CODEX_COUNT_CACHED=1 restores the full count."""
    u = u or {}
    cached = 0 if COUNT_CACHED else min(u.get("cached_input_tokens") or 0, u.get("input_tokens") or 0)
    return (u.get("input_tokens") or 0) - cached + (u.get("output_tokens") or 0)  # reasoning is part of output

QUOTA_FALLBACK = 1800  # the CLI didn't say when the limit resets: try again in 30 min
_QUOTA = {"until": 0.0}

class SchemaError(Exception):
    """The API refused the JSON schema for strict structured output (the caller falls back to plain JSON)."""

def home():
    return os.getenv("CODEX_HOME") or os.path.expanduser("~/.codex")

def _ensure_home():
    """The CLI refuses to start when CODEX_HOME doesn't exist (a fresh /data volume): make it, private, so `codex login`
    run by hand in the container works too."""
    try: os.makedirs(home(), mode=0o700, exist_ok=True)
    except OSError: pass

_ensure_home()

def _env():
    # never let the CLI fall back to an API key or another endpoint: it must use the machine's Codex (ChatGPT) login
    return {k: v for k, v in os.environ.items() if k not in ("OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL", "CODEX_ACCESS_TOKEN")}

def exe():
    path = shutil.which(CODEX_CLI)
    if not path:
        raise llm.LLMError(f"The Codex CLI ({CODEX_CLI}) isn't installed on the server, or isn't on its PATH. The AXoR image "
                           "includes it (rebuild it), or set CODEX_CLI to its full path.")
    _ensure_home()
    return path

def status(acct=None):
    """The CLI's own sign-in line, e.g. "Logged in using ChatGPT" (raises LLMError when it isn't signed in)."""
    try:
        r = subprocess.run([exe(), "login", "status"], capture_output=True, text=True, timeout=30, env=acct.env if acct else _env())
    except subprocess.TimeoutExpired:
        raise llm.LLMError("The Codex CLI didn't answer. Try again.")
    except OSError as e:
        raise llm.LLMError(f"Couldn't start the Codex CLI: {e}.")
    line = ((r.stdout or r.stderr or "").strip().splitlines() or [""])[-1]
    if r.returncode or "logged in" not in line.lower() or "not logged in" in line.lower():
        raise llm.LLMError(acct.not_signed_in if acct else NOT_SIGNED_IN)
    return line

def check(acct=None):
    """A tiny real prompt: a stored login can be expired or revoked, so this is what proves it works."""
    status(acct)
    run("Reply with OK.", "Reply with OK.", DEFAULT, "low", timeout=120, acct=acct)

def models(home_dir=None):
    """[(id, label)]: Codex's default, then the models the CLI lists for this account (from its models cache, which every
    run refreshes; before the first run only the default is known)."""
    out = [(DEFAULT, "Codex · default model")]
    try:
        with open(os.path.join(home_dir or home(), "models_cache.json")) as f: data = json.load(f).get("models") or []
    except (OSError, ValueError, AttributeError):
        return out
    for m in data:
        slug = isinstance(m, dict) and m.get("slug")
        if slug and m.get("visibility") == "list" and re.fullmatch(r"[\w.\-]+", slug):
            out.append((slug, f"Codex · {m.get('display_name') or slug}"))
    return out

def quota_until():
    """Until when every Codex run should wait for the plan's usage limit (0 when it isn't reached)."""
    return _QUOTA["until"] if _QUOTA["until"] > time.time() else 0.0

def reset_at(msg, now=None):
    """The reset time in a limit message: "…Try again at 3:45 PM." / "at 15:30" / "in 2 hours", else 30 min from now."""
    now = now or time.time()
    if (m := re.search(r"try again in\s+(?:(\d+)\s*h\w*)?[\s,and]*(?:(\d+)\s*m\w*)?", msg, re.I)) and (m[1] or m[2]):
        return now + int(m[1] or 0) * 3600 + int(m[2] or 0) * 60
    m = re.search(r"try again at\b[^\n]*?(\d{1,2}):(\d{2})\s*([ap]\.?m\.?)?", msg, re.I)
    if not m: return now + QUOTA_FALLBACK
    h, mi = int(m[1]) % 24, int(m[2])
    if m[3]: h = h % 12 + (12 if m[3][0].lower() == "p" else 0)
    t = time.localtime(now)
    at = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, h, mi, 0, 0, 0, -1))
    return at + 86400 if at <= now else at  # a later day ("Nov 6, 3:45 PM") lands a day early: the next try finds out

def _api_message(msg):
    """turn.failed carries the API's error body as a JSON string: its own message is the readable part."""
    try:
        body = json.loads(msg)
        return str(((body.get("error") or {}).get("message")) or msg) if isinstance(body, dict) else msg
    except ValueError:
        return msg

def fail(msg, acct=None):
    """Raises the user-facing error for a failed run; `msg` is the CLI's or the API's own error text. `acct`: the person's
    own login it ran on, whose clock a usage limit sets; else the server's."""
    low = msg.lower()
    if "invalid_json_schema" in low or "invalid schema for response_format" in low:
        raise SchemaError(msg)
    if "not logged in" in low or "401" in msg or "unauthorized" in low or "refresh token" in low or "log in again" in low:
        raise llm.LLMError(acct.not_signed_in if acct else NOT_SIGNED_IN)
    kind, wait = llm.limit_kind(msg)
    if kind == "brief":  # a per-minute limit ("Rate limit reached for … try again in 1.2s"): nothing waits for a reset
        raise llm.RateLimited(f"Codex is rate-limited right now{acct.whose if acct else ''} (a brief limit, the plan isn't used up). "
                              f"Try again in a minute. {_api_message(msg)[:300]}", wait)
    if kind == "plan":
        q = acct.quota if acct else _QUOTA
        q["until"] = max(q["until"], reset_at(msg))
        # "plan rate limit reached": Autoloop and Upgrade wait for the reset instead of counting a failure
        raise llm.QuotaError(f"Codex plan rate limit reached{acct.whose if acct else ''}; Codex runs resume after the reset at "
                             f"{time.strftime('%H:%M', time.localtime(q['until']))}. {_api_message(msg)[:300]}")
    raise llm.LLMError(f"Codex error: {_api_message(msg)[:300]}")

def parse(stdout, stderr="", acct=None):
    """(the last agent message's text, tokens) from `codex exec --json` output. A turn can write more than one message
    (a progress note, then the answer): the last one is the answer. turn.failed is the failure signal, not the exit code."""
    text, tokens, error = None, None, None
    for line in (stdout or "").splitlines():
        try: e = json.loads(line)
        except ValueError: continue
        if not isinstance(e, dict): continue
        t = e.get("type")
        if t == "item.completed" and isinstance(e.get("item"), dict) and e["item"].get("type") == "agent_message":
            text = e["item"].get("text") or ""
        elif t == "turn.completed":
            tokens = billed(e.get("usage"))
        elif t == "turn.failed":
            fail(str((e.get("error") or {}).get("message") or "unknown error"), acct)
        elif t == "error":  # a stream error; reconnects say so too, so it only counts when the turn never completes
            error = str(e.get("message") or "")
    if tokens is None:
        last = error or ((stderr or "").strip().splitlines() or [""])[-1][:300]
        if last: fail(last, acct)
        raise llm.LLMError("Codex ended without an answer. Try again.")
    return text or "", tokens

def run(prompt, instructions, model, effort, schema=None, timeout=None, acct=None):
    """One `codex exec` turn with `instructions` in place of Codex's own system prompt and the prompt on stdin. Returns
    (answer text, tokens). Waits for a slot of the login's gate first; the wait doesn't count toward `timeout`.
    A brief rate limit is waited out and the turn tried once more (llm.retry_brief)."""
    return llm.retry_brief(_run_once, prompt, instructions, model, effort, schema=schema, timeout=timeout, acct=acct)

def _run_once(prompt, instructions, model, effort, schema=None, timeout=None, acct=None):
    path, timeout = exe(), timeout or llm.CLI_TIMEOUT
    with (acct.gate if acct else GATE), tempfile.TemporaryDirectory(prefix="scout-codex-") as tmp:
        work = os.path.join(tmp, "work")  # the agent's folder: empty, so no project files are in reach
        os.mkdir(work)
        sysfile = os.path.join(tmp, "instructions.md")
        with open(sysfile, "w") as f: f.write(instructions)
        argv = [path, *FLAGS, "-C", work, "-c", f"model_instructions_file={json.dumps(sysfile)}",
                "-c", f"model_reasoning_effort={json.dumps(effort if effort in llm.EFFORTS else 'medium')}"]
        if model and model != DEFAULT: argv += ["-m", model]
        if schema is not None:
            sfile = os.path.join(tmp, "schema.json")
            with open(sfile, "w") as f: json.dump(schema, f)
            argv += ["--output-schema", sfile]
        try:
            r = subprocess.run([*argv, "-"], input=prompt, capture_output=True, text=True, timeout=timeout, cwd=work, env=acct.env if acct else _env())
        except subprocess.TimeoutExpired:
            raise llm.LLMError(f"Codex timed out after {timeout} s. Try again or lower the thinking effort.")
        except OSError as e:
            raise llm.LLMError(f"Couldn't start the Codex CLI: {e}.")
    return parse(r.stdout, r.stderr, acct)

def system(base, tools):
    """The Terminal text-mode instructions, with Codex's tool-call shape (strict output has no free-form objects)."""
    s = llm._terminal_system(base, tools)
    if tools:
        s += ('\n\nIn your JSON reply each tool call is {"name", "input_json"}: `input_json` is the tool\'s input object '
              'encoded as a JSON string, e.g. "{\\"subnet\\": 1}".')
    return s

def turn(base, tools, transcript, model, effort, timeout, acct=None):
    """One agent turn: (tokens, reply) where reply is {"text", "tool_calls": [{name, input}]} or None when unreadable.
    Tool calls whose input_json doesn't parse are listed in reply["_problems"] for the corrective retry."""
    out, used = run(transcript, system(base, tools), model, effort, schema=REPLY, timeout=timeout, acct=acct)
    try: reply = json.loads(out)
    except ValueError: return used, None
    if not isinstance(reply, dict): return used, None
    calls, problems = [], []
    for c in reply.get("tool_calls") or []:
        if not isinstance(c, dict): continue
        try: inp = json.loads(c.get("input_json") or "{}")
        except ValueError: inp = None
        if not isinstance(inp, dict):
            problems.append(f"The input_json of your {c.get('name') or 'unnamed'} call isn't a JSON object.")
            inp = {}
        calls.append({"name": c.get("name"), "input": inp})
    return used, {"text": reply.get("text") or "", "tool_calls": calls, "_problems": problems}

def structured(system_prompt, prompt, schema, model, effort, timeout, acct=None):
    """(JSON answer, tokens) matching `schema`. Strict structured output first; schemas it can't take (optional fields,
    free-form objects) get plain JSON with the schema spelled out, the OpenAI provider's fallback."""
    try:
        out, used = run(prompt, system_prompt + "\n\nReply with JSON matching the given schema.", model, effort, schema=schema, timeout=timeout, acct=acct)
    except SchemaError:
        out, used = run(prompt, system_prompt + "\n\nReply with only a JSON object matching this JSON schema:\n" + json.dumps(schema),
                        model, effort, timeout=timeout, acct=acct)
    return llm._json_text(out), used
