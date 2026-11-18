"""How much of a model's plan is used: the 5-hour, weekly and monthly windows with % used and when each resets
(Agents → Models → a connected model → Usage).

Read where the plan itself keeps it, without spending a model run:
- Claude Code (terminal): GET api.anthropic.com/api/oauth/usage with the server's Claude login, the same numbers
  Claude Code's /usage shows (`limits`: session, weekly_all, weekly_scoped per model). A `claude setup-token` token may
  not be allowed to read it; then `probe=True` (a button, never automatic) reads the plan's windows from the
  rate_limit_event of one short `claude -p` run.
- Codex: `codex app-server` → account/rateLimits/read on the server's CODEX_HOME (primary = 5 h, secondary = weekly).
- GitHub Copilot (API key or CLI token): GET api.github.com/copilot_internal/user → quota_snapshots, reset monthly.
- OpenRouter: GET /api/v1/key → the key's own limit (daily/weekly/monthly) and what it spent.
API keys (Claude, OpenAI) and local servers bill per token: they have no weekly or monthly plan window.

Every answer has one shape: {"plan", "account", "windows": [{"id", "label", "group": session|weekly|monthly|daily|key,
"used": percent 0-100 or None, "resets_at": epoch or None, "detail"}], "checked_at", "error", "note", "can_probe"}.
Answers are cached CACHE_S seconds per provider."""
import json, os, re, subprocess, tempfile, threading, time, urllib.error, urllib.request
from datetime import datetime, timezone

CACHE_S = 60
PROBE_KEEP_S = 1800  # a short-prompt reading stays on show this long (the endpoint can't be read for that login)
_probed = {}
ANTHROPIC = os.getenv("ANTHROPIC_OAUTH_BASE", "https://api.anthropic.com")
GITHUB_API = os.getenv("GITHUB_API_URL", "https://api.github.com")
OPENROUTER = "https://openrouter.ai/api/v1"
_cache, _lock = {}, threading.Lock()


def _epoch(v):
    """An ISO time ("2026-11-14T18:00:00.12+00:00", "...Z", "2026-12-01") or epoch seconds/ms → epoch seconds."""
    if v in (None, "", 0): return None
    if isinstance(v, (int, float)): return float(v) / (1000 if v > 1e12 else 1)
    try: return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError: return None


def _pct(v):
    try: return max(0.0, min(100.0, round(float(v), 1)))
    except (TypeError, ValueError): return None


def _get(url, headers, timeout=15):
    """GET JSON; raises urllib.error.HTTPError / URLError."""
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "AXoR", **headers}), timeout=timeout) as r:
        return json.load(r)


def _answer(**kw):
    return {"plan": None, "account": None, "windows": [], "checked_at": time.time(), "error": None, "note": None, "can_probe": False, **kw}


def _window(id, label, group, used, resets_at, detail=None):
    return {"id": id, "label": label, "group": group, "used": _pct(used), "resets_at": resets_at, "detail": detail}


def _window_name(minutes):
    """A plan window's name from its length: 300 → 5-hour session, 10080 → Weekly limit, ~43200 → Monthly limit."""
    m = int(minutes or 0)
    if not m: return "Limit", "session"
    if m < 1440: return (f"{m // 60}-hour session" if m % 60 == 0 else f"{m}-minute window"), "session"
    if m == 1440: return "Daily limit", "daily"
    if m == 10080: return "Weekly limit", "weekly"
    if 40000 <= m <= 45000: return "Monthly limit", "monthly"
    return f"{round(m / 1440)}-day limit", "weekly" if m < 40000 else "monthly"


# ---------- Claude Code ----------
def claude_windows(d):
    """The usage endpoint's answer → windows. `limits` (what /usage shows) first; else five_hour / seven_day*.
    Its numbers are percents already (3.0 = 3 %)."""
    out = []
    for x in d.get("limits") or []:
        kind, scope = x.get("kind") or "", ((x.get("scope") or {}).get("model") or {}).get("display_name")
        if kind == "session": label, group = "5-hour session", "session"
        elif kind.startswith("weekly"): label, group = "Weekly limit" + (f" · {scope}" if scope else ""), "weekly"
        elif kind.startswith("monthly"): label, group = "Monthly limit" + (f" · {scope}" if scope else ""), "monthly"
        else: label, group = kind.replace("_", " ").capitalize() or "Limit", x.get("group") or "session"
        out.append(_window(kind + (f":{scope}" if scope else ""), label, group, x.get("percent"), _epoch(x.get("resets_at"))))
    if not out:
        names = {"five_hour": ("5-hour session", "session"), "seven_day": ("Weekly limit", "weekly"),
                 "seven_day_opus": ("Weekly limit · Opus", "weekly"), "seven_day_sonnet": ("Weekly limit · Sonnet", "weekly")}
        for k, (label, group) in names.items():
            if isinstance(d.get(k), dict):
                out.append(_window(k, label, group, d[k].get("utilization"), _epoch(d[k].get("resets_at"))))
    ex = d.get("extra_usage") or {}
    if ex.get("is_enabled") and ex.get("monthly_limit"):  # paid extra usage on top of the plan: a monthly credit limit
        out.append(_window("extra_usage", "Extra usage (monthly)", "monthly", ex.get("utilization"), None,
                           f"{ex.get('used_credits') or 0} of {ex.get('monthly_limit')} {ex.get('currency') or ''}".strip()))
    return out


def claude_rate_event(info):
    """A stream-json rate_limit_event's rate_limit_info → windows. Its utilization is a fraction (0.03 = 3 %)."""
    out = []
    for k, v in ((info or {}).get("unifiedWindows") or {}).items():
        label, group = {"five_hour": ("5-hour session", "session"), "seven_day": ("Weekly limit", "weekly"),
                        "seven_day_opus": ("Weekly limit · Opus", "weekly"), "seven_day_sonnet": ("Weekly limit · Sonnet", "weekly")
                        }.get(k, (k.replace("_", " ").capitalize(), "weekly" if "day" in k else "session"))
        u = v.get("utilization")
        out.append(_window(k, label, group, None if u is None else float(u) * 100, _epoch(v.get("resetsAt"))))
    return out


def _claude_login(env):
    """(token, where): the server's Claude Code login the way the CLI picks it: CLAUDE_CODE_OAUTH_TOKEN (Agents → Models
    or the environment) first, else the browser sign-in saved in the CLI's config folder."""
    if env.get("CLAUDE_CODE_OAUTH_TOKEN"): return env["CLAUDE_CODE_OAUTH_TOKEN"], "token"
    folder = env.get("CLAUDE_CONFIG_DIR") or os.path.join(env.get("HOME") or os.path.expanduser("~"), ".claude")
    try:
        with open(os.path.join(folder, ".credentials.json")) as f: o = (json.load(f) or {}).get("claudeAiOauth") or {}
    except (OSError, ValueError): return None, None
    return o.get("accessToken"), "login"


def claude(env, status=None):
    """`env`: llm._cli_env(); `status`: `claude auth status` (account and plan), or None."""
    st = status or {}
    acct = " · ".join(x for x in (st.get("email"), st.get("orgName")) if x) or None
    plan = f"Claude {st['subscriptionType'].capitalize()}" if st.get("subscriptionType") else None
    tok, where = _claude_login(env)
    if not tok: return _answer(plan=plan, account=acct, error="Claude Code on the server isn't signed in, so there's no plan to read.")
    try:
        d = _get(ANTHROPIC + "/api/oauth/usage", {"Authorization": f"Bearer {tok}", "anthropic-beta": "oauth-2025-04-20"})
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            why = ("Anthropic didn't let this sign-in's token read the plan's usage (a `claude setup-token` token may only run "
                   "prompts; if agents fail too, the token has expired)."
                   if where == "token" else "The saved Claude sign-in has expired; connect it again under Add model, then check again.")
            return _answer(plan=plan, account=acct, can_probe=True,
                           error=why + " Check with a short prompt reads the windows from one tiny Claude Code run instead.")
        return _answer(plan=plan, account=acct, can_probe=True, error=f"Anthropic answered {e.code} for the usage read.")
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as e:
        return _answer(plan=plan, account=acct, error=f"Couldn't reach api.anthropic.com: {getattr(e, 'reason', e)}.")
    return _answer(plan=plan, account=acct, windows=claude_windows(d), note="Shared with every Claude Code session on this sign-in.")


def claude_probe(exe, env, gate, status=None, slot="terminal"):
    """One short `claude -p` (haiku, low effort, no tools) in stream-json: its rate_limit_event carries the windows.
    Uses a little of the plan; only run when someone asks. `slot`: which login the reading is kept for (last_probe)."""
    st = status or {}
    acct = " · ".join(x for x in (st.get("email"), st.get("orgName")) if x) or None
    plan = f"Claude {st['subscriptionType'].capitalize()}" if st.get("subscriptionType") else None
    args = [exe, "-p", "--output-format", "stream-json", "--verbose", "--model", "haiku", "--effort", "low", "--tools", "",
            "--safe-mode", "--strict-mcp-config", "--no-session-persistence", "--system-prompt", "Reply with OK."]
    with gate, tempfile.TemporaryDirectory(prefix="scout-usage-") as cwd:
        try: r = subprocess.run(args, input="Reply with OK.", capture_output=True, text=True, timeout=120, cwd=cwd, env=env)
        except (subprocess.TimeoutExpired, OSError) as e:
            return _answer(plan=plan, account=acct, error=f"The short Claude Code run didn't finish: {e}.")
    for line in (r.stdout or "").splitlines():
        try: d = json.loads(line)
        except ValueError: continue
        if d.get("type") == "rate_limit_event":
            got = _answer(plan=plan, account=acct, windows=claude_rate_event(d.get("rate_limit_info")), can_probe=True,
                          note="Read from one short Claude Code run. Shared with every Claude Code session on this sign-in.")
            _probed[slot] = got
            return got
    last = ((r.stderr or r.stdout or "").strip().splitlines() or [""])[-1][:300]
    return _answer(plan=plan, account=acct, error="Claude Code didn't report the plan's windows" + (f": {last}" if last else "."))


# ---------- Codex ----------
def codex_windows(rl):
    """account/rateLimits/read's rateLimits → windows (usedPercent is a percent)."""
    out = []
    for k in ("primary", "secondary"):
        w = (rl or {}).get(k)
        if not isinstance(w, dict): continue
        label, group = _window_name(w.get("windowDurationMins"))
        out.append(_window(k, label, group, w.get("usedPercent"), _epoch(w.get("resetsAt"))))
    cr = (rl or {}).get("credits") or {}
    if cr.get("hasCredits") and not cr.get("unlimited"):
        out.append(_window("credits", "Credits", "key", None, None, f"{cr.get('balance')} left"))
    return out


def codex(exe, env, timeout=30):
    """Asks `codex app-server` (JSON-RPC over stdio) for the signed-in ChatGPT plan's limits. No model run."""
    try: p = subprocess.Popen([exe, "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
    except OSError as e: return _answer(error=f"Couldn't start the Codex CLI: {e}.")
    found, kill = {}, threading.Timer(timeout, p.kill)
    kill.start()
    try:
        def send(o): p.stdin.write(json.dumps(o) + "\n"); p.stdin.flush()
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"clientInfo": {"name": "axor", "version": "1"}}})
        send({"jsonrpc": "2.0", "method": "initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "account/rateLimits/read"})
        for line in p.stdout:
            try: d = json.loads(line)
            except ValueError: continue
            if d.get("method") == "account/updated": found["plan"] = (d.get("params") or {}).get("planType")
            if d.get("id") == 2: found["answer"] = d; break
    except (OSError, ValueError): pass
    finally:
        kill.cancel()
        try: p.kill()
        except OSError: pass
    d = found.get("answer")
    if not d: return _answer(error="Codex didn't answer the usage read in time. Is it signed in? Check again with the refresh button.")
    if d.get("error"):
        msg = str((d["error"] or {}).get("message") or d["error"])[:300]
        return _answer(error=f"Codex couldn't read the plan's limits: {msg}" + (" (an API key login has no plan windows)" if "api" in msg.lower() else ""))
    rl = (d.get("result") or {}).get("rateLimits") or {}
    plan = rl.get("planType") or found.get("plan")
    return _answer(plan=f"ChatGPT {plan.capitalize()}" if plan else None, windows=codex_windows(rl),
                   note="Shared with every Codex session on this ChatGPT sign-in.")


# ---------- GitHub Copilot ----------
COPILOT_QUOTAS = (("premium_interactions", "Premium requests"), ("chat", "Chat messages"), ("completions", "Code completions"))

def copilot_windows(d):
    """copilot_internal/user → monthly windows (percent_remaining inverted). A quota the plan doesn't include
    (entitlement 0) and unlimited ones are left out; the reset is the account's quota_reset_date."""
    reset, out = _epoch(d.get("quota_reset_date_utc") or d.get("quota_reset_date")), []
    for k, label in COPILOT_QUOTAS:
        q = (d.get("quota_snapshots") or {}).get(k)
        if not isinstance(q, dict) or q.get("unlimited") or not q.get("entitlement"): continue
        used = 100 - float(q.get("percent_remaining") or 0)
        out.append(_window(k, f"{label} (monthly)", "monthly", used, reset, f"{q.get('remaining')} of {q.get('entitlement')} left"))
    return out


def copilot(token):
    if not token: return _answer(error="No GitHub token is saved for Copilot.")
    try: d = _get(GITHUB_API + "/copilot_internal/user", {"Authorization": f"token {token}", "Accept": "application/json"})
    except urllib.error.HTTPError as e:
        return _answer(error=f"GitHub doesn't show this token's Copilot quota ({e.code}): fine-grained tokens may not be "
                             "allowed to read it. See github.com/settings/copilot for the plan's premium requests.")
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as e:
        return _answer(error=f"Couldn't reach api.github.com: {getattr(e, 'reason', e)}.")
    sku, plan = d.get("access_type_sku") or "", d.get("copilot_plan")
    name = "Copilot Free" if "free" in sku else f"Copilot {plan.capitalize()}" if plan else None
    unlimited = [label for k, label in COPILOT_QUOTAS if ((d.get("quota_snapshots") or {}).get(k) or {}).get("unlimited")]
    return _answer(plan=name, account=d.get("login"), windows=copilot_windows(d),
                   note=("Unlimited: " + ", ".join(x.lower() for x in unlimited) + ". " if unlimited else "")
                        + "Counted per request, reset on the 1st of the month (UTC).")


# ---------- OpenRouter ----------
def _next_reset(kind, now=None):
    """OpenRouter's key limits reset at midnight UTC: daily, Mondays (weekly), the 1st (monthly)."""
    now = now or time.time()
    t = datetime.fromtimestamp(now, timezone.utc)
    base = datetime(t.year, t.month, t.day, tzinfo=timezone.utc).timestamp()  # today's midnight UTC
    if kind == "daily": return base + 86400
    if kind == "weekly": return base + 86400 * (7 - t.weekday())
    if kind == "monthly":
        y, m = (t.year + 1, 1) if t.month == 12 else (t.year, t.month + 1)
        return datetime(y, m, 1, tzinfo=timezone.utc).timestamp()
    return None


def openrouter_windows(k, now=None):
    out, cost = [], lambda v: f"${float(v or 0):.2f}"
    lim, reset = k.get("limit"), k.get("limit_reset")
    if lim:
        used = float(lim) - float(k.get("limit_remaining") if k.get("limit_remaining") is not None else lim)
        out.append(_window("limit", f"Key limit ({reset})" if reset else "Key limit", reset or "key", used / float(lim) * 100,
                           _next_reset(reset, now) if reset else None, f"{cost(used)} of {cost(lim)}"))
    for kind, label in (("weekly", "Spent this week"), ("monthly", "Spent this month")):
        if k.get(f"usage_{kind}") is not None and reset != kind:
            out.append(_window(f"usage_{kind}", label, kind, None, _next_reset(kind, now), cost(k.get(f"usage_{kind}"))))
    return out


def openrouter(key):
    if not key: return _answer(error="No OpenRouter key is saved.")
    try: k = (_get(OPENROUTER + "/key", {"Authorization": f"Bearer {key}"}) or {}).get("data") or {}
    except urllib.error.HTTPError as e: return _answer(error=f"OpenRouter answered {e.code} for this key.")
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as e:
        return _answer(error=f"Couldn't reach openrouter.ai: {getattr(e, 'reason', e)}.")
    return _answer(plan="Free tier" if k.get("is_free_tier") else "Pay as you go", account=k.get("label"), windows=openrouter_windows(k),
                   note=None if k.get("limit") else "This key has no spending limit, so there's no % used: set one at openrouter.ai/settings/keys.")


def per_token(provider):
    who = {"anthropic": "Anthropic API", "openai": "OpenAI API", "local": "your own server"}.get(provider, provider)
    return _answer(plan="Billed per token", note=f"{who} bills each token; there's no weekly or monthly plan window to show."
                   + (" Spending limits are set in the provider's console." if provider != "local" else ""))


def last_probe(slot="terminal"):
    """The last Claude short-prompt reading for `slot` (the server's login, or "terminal:<id>" for a named login) while
    it's under PROBE_KEEP_S old, else None."""
    got = _probed.get(slot)
    return got if got and time.time() - got["checked_at"] < PROBE_KEEP_S else None


def cached(provider, fetch, fresh=False):
    """fetch() at most once per CACHE_S per provider unless `fresh`."""
    with _lock:
        hit = _cache.get(provider)
        if hit and not fresh and time.time() - hit["checked_at"] < CACHE_S: return hit
    got = fetch()
    with _lock: _cache[provider] = got
    return got
