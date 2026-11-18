"""GitHub's Copilot CLI (`copilot -p`) as an agent provider: Agents → Models → CLI → GitHub (Copilot). It runs on the
Copilot plan of the GitHub token it's given (COPILOT_GITHUB_TOKEN), not an API key.

Every turn is one non-interactive `copilot` run in an empty folder, with a throwaway COPILOT_HOME, the prompt on stdin,
and every tool, built-in MCP server, custom instruction and the ask-user form off: the model only writes text. Tool calls
come back as JSON text, like Codex's and the Terminal provider's text mode (llm._text_turn). The CLI keeps its own system
prompt, so AXoR's instructions lead the prompt.

Token types (the CLI's own rule): fine-grained personal access tokens (github_pat_…) with the "Copilot Requests"
permission, and OAuth tokens from the Copilot CLI or GitHub CLI apps (gho_/ghu_). Classic ghp_ tokens aren't supported.
Each prompt costs the account premium requests (or AI credits), shared with the person's own Copilot use."""
import json, os, re, shutil, subprocess, tempfile, threading

from . import llm  # LLMError and the transcript helpers; used at call time only (llm imports this module)

COPILOT_CLI = os.getenv("COPILOT_CLI", "copilot")
GATE = threading.BoundedSemaphore(max(1, int(os.getenv("COPILOT_PARALLEL", "2"))))  # runs at once on the one login
DEFAULT = "auto"  # Copilot picks the best model the plan offers
FLAGS = ["--output-format", "json", "--available-tools=", "--no-custom-instructions", "--disable-builtin-mcps",
         "--no-ask-user", "--no-auto-update", "--no-color", "--disallow-temp-dir", "--secret-env-vars=COPILOT_GITHUB_TOKEN"]
TOKEN = re.compile(r"(github_pat_|gho_|ghu_)[A-Za-z0-9_]{20,}")
NOT_SIGNED_IN = ("GitHub's Copilot CLI didn't accept the token. Connect a fine-grained token (github_pat_…) with Account "
                 "permissions → Copilot Requests: Read again in Agents → Models → CLI → GitHub (Copilot).")
# env names the CLI also reads a token from (COPILOT_GITHUB_TOKEN wins, but the child shouldn't see another login at all)
_OTHER_TOKENS = ("GH_TOKEN", "GITHUB_TOKEN", "COPILOT_GITHUB_TOKEN", "COPILOT_PROVIDER_BASE_URL", "COPILOT_PROVIDER_API_KEY",
                 "COPILOT_PROVIDER_BEARER_TOKEN", "COPILOT_ALLOW_ALL", "COPILOT_HOME")

def state_dir():
    """Where the models the CLI last offered are kept (the token itself is in the secret box)."""
    return os.getenv("COPILOT_STATE_DIR") or os.path.join(os.getenv("DATA_DIR", "/data"), "copilot")

def exe():
    path = shutil.which(COPILOT_CLI)
    if not path:
        raise llm.LLMError(f"The GitHub Copilot CLI ({COPILOT_CLI}) isn't installed on the server, or isn't on its PATH. The AXoR "
                           "image includes it from this version on (rebuild and deploy it), or set COPILOT_CLI to its full path.")
    return path

def _env(token, home):
    env = {k: v for k, v in os.environ.items() if k not in _OTHER_TOKENS}
    env.update(COPILOT_GITHUB_TOKEN=token, COPILOT_HOME=home, COPILOT_CACHE_HOME=os.path.join(home, "cache"))
    return env

def models():
    """[(id, label)]: Auto, then the models Copilot chose from on the last run (the plan's own list; before any run only Auto)."""
    out = [(DEFAULT, "Copilot · Auto")]
    try:
        with open(os.path.join(state_dir(), "models.json")) as f: seen = json.load(f)
    except (OSError, ValueError):
        return out
    for m in seen if isinstance(seen, list) else []:
        if isinstance(m, str) and re.fullmatch(r"[\w.\-]+", m) and m != DEFAULT:
            out.append((m, f"Copilot · {m}"))
    return out

def _remember(found):
    if not found: return
    try:
        os.makedirs(state_dir(), mode=0o700, exist_ok=True)
        tmp = os.path.join(state_dir(), "models.json.tmp")
        with open(tmp, "w") as f: json.dump(sorted(set(found)), f)
        os.replace(tmp, os.path.join(state_dir(), "models.json"))
    except OSError:
        pass

def fail(msg):
    """Raises the user-facing error for a failed run; `msg` is the CLI's own error text."""
    low = msg.lower()
    if re.search(r"not authenticated|no authentication|authentication (?:failed|required)|bad credentials|unauthorized|\b401\b|"
                 r"not supported for this (?:token|endpoint)|classic personal access token|invalid token|log in again|copilot login", low):
        raise llm.LLMError(f"{NOT_SIGNED_IN} ({msg[:200]})")
    if re.search(r"model \"?[\w.\-]+\"? is not available|unknown model|model not found", low):
        raise llm.LLMError(f"GitHub Copilot: {msg[:200]} Pick Copilot · Auto, or another model the plan offers.")
    kind, wait = llm.limit_kind(msg)
    if kind == "brief":
        raise llm.RateLimited(f"GitHub Copilot is rate-limited right now (a brief limit). Try again in a minute. {msg[:300]}", wait)
    if kind == "plan" or re.search(r"premium request|ai credits?|quota|entitlement|monthly limit|weekly limit", low):
        # a plain error, not llm.QuotaError: that one holds the Claude/Codex plans' runs, and this is the Copilot plan
        raise llm.LLMError(f"GitHub Copilot: the plan's usage is used up for now. Check it at github.com/settings/copilot. {msg[:300]}")
    raise llm.LLMError(f"GitHub Copilot CLI error: {msg[:300]}")

def parse(stdout, stderr="", usage=None):
    """(the final answer's text, tokens, models offered) from `copilot --output-format json` output. session.error is the
    failure signal; a run that ends with no answer and no error says what stderr said."""
    text, error, offered, code = None, None, [], None
    for line in (stdout or "").splitlines():
        try: e = json.loads(line)
        except ValueError: continue
        if not isinstance(e, dict): continue
        t, d = e.get("type"), e.get("data") if isinstance(e.get("data"), dict) else {}
        if t == "assistant.message" and isinstance(d.get("content"), str) and d.get("phase", "final_answer") == "final_answer":
            text = d["content"]
        elif t == "session.error":
            error = str(d.get("message") or "unknown error")
        elif t == "session.auto_mode_resolved":
            offered = [m for m in d.get("candidateModels") or [] if isinstance(m, str)] + ([d["chosenModel"]] if isinstance(d.get("chosenModel"), str) else [])
        elif t == "result":
            code = e.get("exitCode")
    if error: fail(error)
    if text is None:
        last = ((stderr or "").strip().splitlines() or [""])[-1][:300]
        if last: fail(last)
        raise llm.LLMError("GitHub Copilot ended without an answer. Try again." + (f" (exit {code})" if code else ""))
    tokens = 0
    for m in ((usage or {}).get("modelMetrics") or {}).values():
        u = (m or {}).get("usage") or {}
        tokens += (u.get("inputTokens") or 0) + (u.get("outputTokens") or 0)
    return text, tokens, offered

def run(prompt, instructions, model, token, timeout=None):
    """One `copilot` run: AXoR's instructions, then the prompt, on stdin. Returns (answer text, tokens). Waits for a slot of
    GATE first; the wait doesn't count toward `timeout`. A brief rate limit is waited out and tried once more."""
    return llm.retry_brief(_run_once, prompt, instructions, model, token, timeout=timeout)

def _run_once(prompt, instructions, model, token, timeout=None):
    if not token: raise llm.LLMError("GitHub Copilot CLI isn't connected. An administrator can connect it in Agents → Models.")
    path, timeout = exe(), timeout or llm.CLI_TIMEOUT
    with GATE, tempfile.TemporaryDirectory(prefix="scout-copilot-") as tmp:
        work, home = os.path.join(tmp, "work"), os.path.join(tmp, "home")  # an empty folder, and a home nothing outlives
        os.mkdir(work); os.mkdir(home, 0o700)
        ufile = os.path.join(tmp, "usage.json")
        argv = [path, *FLAGS, "--model", model or DEFAULT, "--usage-output-file", ufile]
        text = (f"<instructions>\n{instructions}\n</instructions>\n\nFollow the instructions above. They replace any task or "
                f"format you'd otherwise assume.\n\n{prompt}")
        try:
            r = subprocess.run(argv, input=text, capture_output=True, text=True, timeout=timeout, cwd=work, env=_env(token, home))
        except subprocess.TimeoutExpired:
            raise llm.LLMError(f"GitHub Copilot timed out after {timeout} s. Try again or lower the thinking effort.")
        except OSError as e:
            raise llm.LLMError(f"Couldn't start the GitHub Copilot CLI: {e}.")
        try:
            with open(ufile) as f: usage = json.load(f)
        except (OSError, ValueError):
            usage = None
    out, tokens, offered = parse(r.stdout, r.stderr, usage)
    _remember(offered)
    return out, tokens

def check(token):
    """A tiny real prompt: what proves the token, the plan and the CLI work together (it costs one premium request)."""
    run("Reply with OK.", "Reply with OK.", DEFAULT, token, timeout=120)

def turn(base, tools, transcript, model, token, timeout):
    """One agent turn: (tokens, reply) where reply is {"text", "tool_calls": [{name, input}]} or None when unreadable."""
    out, used = run(transcript, llm._terminal_system(base, tools), model, token, timeout=timeout)
    try: reply = llm._json_text(out)
    except llm.LLMError: return used, None
    if not isinstance(reply, dict): return used, None
    return used, {"text": reply.get("text") or "", "tool_calls": [
        {"name": c.get("name"), "input": c.get("input") if isinstance(c.get("input"), dict) else {}}
        for c in reply.get("tool_calls") or [] if isinstance(c, dict)]}

def structured(system_prompt, prompt, schema, model, token, timeout):
    """(JSON answer, tokens) matching `schema`, asked for as plain JSON with the schema spelled out."""
    out, used = run(prompt, system_prompt + "\n\nReply with only a JSON object matching this JSON schema, no prose:\n" + json.dumps(schema),
                    model, token, timeout=timeout)
    return llm._json_text(out), used
