"""G5 Unified Intelligence Orchestrator (/api/g5; shown on Control Hub → Intelligence layers, budgets on Agent Operations → Budget).

The six intelligence layers (intel_layers.py) were each built by their own system; what was missing between them is what this
module adds, on the systems' own records and never in their place:

- Correlation. Every run in the agent core's ledger gets a correlation id when it begins (agent_core.register_resolver): the
  mission or task it serves. A Mission Control mission links its child engine here when it launches it (link()), so the
  Workforce, swarm or long task runs of mission 4 all carry corr "mx:4". The same id keys the mission's hard token limit at
  the gateway (agent_core ac_limits, scope mission) and its end-to-end trace.
- Event-driven handoffs (io_events). One row per handoff between layers, with a unique idempotency key (an event seen twice is
  processed once), a correlation id, a handler per kind, retries with backoff and a dead letter after MAX_ATTEMPTS, so a broken
  handoff shows as a dead letter with its error instead of silence. Rows a restart cut off go back to pending. Every action is
  in the audit log (io_audit).
- Evaluation coverage (io_evals). Every finished run is scored or explicitly excluded with its reason: a verdict its own system
  already keeps is copied onto it (Workforce and swarm run scores, swarm contract scores, Mission Control's independent check for
  every run of that mission); chats, back-filled rows, evaluation tooling and monitoring rounds are excluded with why; a failed run
  is excluded with its terminal outcome. A run nobody can judge is a named coverage gap, by system and kind, not a missing number.
- Failure diagnosis (io_diag, io_sbx). Every failed run gets a class, whether retrying can fix it and the recovery to take;
  sandbox runs that couldn't run get a sandbox class (gVisor missing, egress proxy down, busy, image, input too large, ...) and,
  when recoverable, a one-click retry. Runs left "running" STALE_H hours after their process died are closed as lost.
- Evaluation → Adaptive. An agent whose failures or low scores cross a threshold becomes a signal event; its handler opens an
  Evolution proposal (model-drafted for your own agents when the Evolution policy lets the engine experiment, else a recorded
  diagnosis). Nothing is promoted here: evolution.py's experiments and evidence rule decide.
- Promote → Monitor → Rollback. A promoted change is watched on the agent's later scored runs against its runs before the
  promotion; a regression rolls it back when the policy is auto and the change is low-risk configuration, else waits for you.
- Adaptive → Mission. guidance() gives Mission Control's planner what the loop learned: failure classes to plan around with their
  recovery, changes promoted and rolled back, and which model scored best for each kind of work.
- Recovery: a diagnosed failed run a retry can fix is recovered, on your click, through its own system (a Control Hub task
  starts again, a long task or a mission resumes, a Workforce mission runs again); team work is Autoloop's to requeue. Nothing
  is retried on its own here: the systems that do (Autoloop, Mission Control, long tasks) already do.
- Workforce optimization (optimize()): underperforming, failing, costly and strong agents against their own system, idle ones,
  and models that scored better than the one most used for a kind of work. Recommendations only.
- An agent nobody scores (chats) is watched after a promotion on your thumbs in its chats instead (share of thumbs-up).
- Pruning: io_ rows go after KEEP_DAYS like the ledger's runs; the audit after AUDIT_DAYS; datasets stay (evidence names them).
- Versioned benchmark datasets (io_datasets). A benchmark's cases are frozen by content hash whenever they're used; evidence
  names the version and hash it was measured on, and reproduce() recomputes a verdict from its stored trials.
- Retrieval benchmark. A known-item test built from your own kept Knowledge Hub items (a sentence from an item must find that
  item in the top 5), versioned like any dataset, with a pass line and a reason per miss (not indexed, or ranked out).

Read-mostly: the tick writes only these io_ tables, scores on runs that had none, lost-marks on dead runs and proposals the
policy allows; it starts no model call except a draft under an Evolution policy that lets the engine experiment.
"""
import datetime, hashlib, json, logging, os, re, threading, time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import agent_core, restart_recovery

log = logging.getLogger("scout.orchestrator")

TICK = max(10, int(os.getenv("G5_TICK", "60")))  # seconds between rounds
STALE_H = 12            # a run still "running" after this many hours had its process die
GRACE = 6 * 3600        # a finished run waits this long for its own system's verdict before it's a coverage gap
WINDOW = 30 * 86400     # runs classified, failures diagnosed
BATCH = 2000            # runs handled per round
MAX_ATTEMPTS = 5
BACKOFF = (30, 120, 600, 1800, 3600)
SIGNAL_DAYS = 14
SIGNAL_MIN_FAILS, SIGNAL_FAIL_RATE, SIGNAL_MIN_SCORED, SIGNAL_LOW = 3, 0.3, 3, 60
MONITOR_N = 3           # scored runs after a promotion before it's judged
RB_CASES, RB_PASS, RB_K = 25, 0.8, 5  # retrieval benchmark: cases, recall@k pass line, k
RB_EVERY = 86400
KEEP_DAYS = 120         # io_ rows kept as long as the run ledger keeps runs (agent_core.KEEP)
# G5-3 risk feeds (D-029, Proposed; full record owner-decisions/g5-plan/g53/DECISIONS_20261113.md)
RISK_WINDOW = 24 * 3600  # a feed counts its source's failures over this window
RISK_RECUR = 3           # failures of one class in one scope within the window that make it a risk
RISK_FEED_EVERY = 300    # seconds between feed passes from tick
# not the work's own and not fed elsewhere: restart (a deploy, recovered by itself), budget (ac_alerts feed, R3.2), sandbox (the
# io_sbx feed, which has the finer class) and cancelled (on purpose) stay out
RISK_DIAG_CLASSES = ("credential", "provider", "quota", "rate", "transient", "tool", "capability")
RISK_SBX_SKIP = ("restart", "too_large", "timeout", "other")  # a deploy, the run's own input or time, or unknown: not the environment's
# C3 (wave 2): AXoR's own readiness check runs (W7, mission_ops.NET_CHECK_USER) are AXoR's measurement, not the team's work. Their
# answer reaches the register through the readiness path (an UNKNOWN or FAIL probe on a held task), so the sandbox feed leaves them out
RISK_SBX_NOT_TEAM = ("AXoR readiness check",)
RISK_FEED_APPROVAL = "the Owner may accept it; it closes by itself once no failure of its kind is seen for 24 h. The register changes nothing."
# G5-3 R3.2: sources with their own lifecycle; organization rows (hq_issues has no owner) are kept under ORG_OWNER, shown to and
# accepted by administrators only
RISK_SRC_FEEDS = ("hq", "budget", "ops", "campaign")
ORG_OWNER = 0
RISK_SOURCES = ("readiness", "diagnosis", "sandbox", *RISK_SRC_FEEDS, "monitor")  # the register's filters (R3.4); "monitor": the Owner's endpoint watches (L5.3, mining_web)
RISK_SCOPES = ("mission", "team", "owner", "organization")
RISK_SRC_APPROVAL = "the Owner may accept it; it closes when its source closes it. The register changes nothing."
AUDIT_DAYS = 365

LAYER = {"mission": "Mission intelligence", "workforce": "Workforce intelligence", "execution": "Execution intelligence",
         "knowledge": "Knowledge intelligence", "evaluation": "Evaluation", "adaptive": "Adaptive intelligence"}
# event kind → (from layer, to layer, what the handoff is)
KINDS = {
    "mission.launched": ("mission", "workforce", "A mission's plan handed to an engine, team or agent, its runs correlated to it"),
    "mission.finished": ("execution", "knowledge", "A finished mission's verdict on its runs and its lessons kept"),
    "agent.signal": ("evaluation", "adaptive", "An agent's failures or low scores turned into an improvement proposal"),
    "proposal.promoted": ("adaptive", "adaptive", "A promoted change put under watch"),
    "proposal.regressed": ("adaptive", "adaptive", "A watched change that scored worse: rolled back or held for you"),
    "mission.guided": ("adaptive", "mission", "What the loop learned given to a mission's planner"),
    # D-004 D4.3: a persistent mission's cycle (the decision, written once) and each of its effects (applied once, by key)
    "mission.cycle": ("evaluation", "mission", "A persistent mission's evidence evaluated and one decision recorded"),
    "mission.effect": ("mission", "mission", "One effect of a persistent mission's cycle applied: a line, a request, advice or the summary"),
    "mission.note": ("mission", "workforce", "A persistent mission's note given to its team's Director (plan or report run)"),
    # observed from each system's own records (observe_handoffs), with the record's own time, so a week counts the same everywhere
    "work.assigned": ("mission", "workforce", "A task or mission given straight to a team, an agent, the Workforce or a swarm"),
    "run.routed": ("workforce", "execution", "A run started on the model the router picked"),
    "knowledge.written": ("execution", "knowledge", "A lesson, memory or team finding kept from finished work"),
    "run.scored": ("execution", "evaluation", "A finished run given a score by its evaluator or verifier"),
    "run.reviewed": ("execution", "evaluation", "A finished board task recorded with its review verdict: reviewed, with no score (G5-5 L5.1)"),
    "proposal.tested": ("evaluation", "adaptive", "A proposed change measured: an experiment, a Workforce trial, a Lab eval or an exam sprint"),
    "recall.mission": ("adaptive", "mission", "Earlier experience recalled by a mission before it acts"),
    "knowledge.read": ("knowledge", "*", "A search or recall of what's known, by any layer"),
}

STEP = {"proposal.promoted": "Promote → Monitor", "proposal.regressed": "Monitor → Roll back"}  # handoffs inside one layer
# The loop's handoffs, each the sum of its event kinds. The one definition the Intelligence layers overview and the orchestrator
# table both show (edges()). `needs`: the kind that completes the handoff; others flowing without it is "partial".
EDGES = (
    {"key": "mission>workforce", "from": "mission", "to": "workforce", "label": "Work handed to an engine, team or agent", "kinds": ("mission.launched", "work.assigned")},
    {"key": "workforce>execution", "from": "workforce", "to": "execution", "label": "Runs on a routed model", "kinds": ("run.routed",)},
    {"key": "execution>knowledge", "from": "execution", "to": "knowledge", "label": "Lessons, memories and findings kept", "kinds": ("knowledge.written", "mission.finished")},
    {"key": "execution>evaluation", "from": "execution", "to": "evaluation", "label": "Runs scored or reviewed", "kinds": ("run.scored", "run.reviewed")},
    {"key": "evaluation>adaptive", "from": "evaluation", "to": "adaptive", "label": "Weak agents turned into proposals, and changes measured",
     "kinds": ("agent.signal", "proposal.tested"), "needs": "proposal.tested"},
    {"key": "adaptive>mission", "from": "adaptive", "to": "mission", "label": "What the loop learned, given back to missions",
     "kinds": ("mission.guided", "recall.mission"), "feedback": True},
    {"key": "knowledge>*", "from": "knowledge", "to": "*", "label": "Searches and recalls across the loop", "kinds": ("knowledge.read",), "shared": True},
)

# ------------------------------------------------------------------ the failure taxonomy (G5 Phase 1, D-014, gap G-26)
# One table for every failure class AXoR names. Until 2026-11-11 five modules kept their own vocabulary and policy: Autoloop
# (mining_autoloop.CLASSES/LABEL/POLICY), the shared classifier (fail_class, below; intel_layers re-exports it with FAIL_LABEL),
# this module's RECOVERY/OWN_FAULT and sandbox SBX, Mission Operations (mission_ops.RECOVERY), the Control Hub dispatcher
# (control_dispatch.RETRY/NEVER) and Mission Control (missions.FAILURES/RECOVERY, a mission-level vocabulary).
#
# The legacy classes (the keys fail_class returns) carry every consumer's policy here, and those consumers' tables are now
# derived from this one with the values they had (tests/unit/test_failure_taxonomy.py pins them). Policies that disagree are
# kept as they were and listed in CONFLICTS for the Owner; nothing here changes a decision any loop makes.
#
# failure() adds the canonical class on top: the legacy class, refined where the error says more (a missing login, an input
# over the sandbox's limit, a timeout, a missing capability), with its family and G5 layer. Where the canonical reading
# disagrees with the legacy one about whose fault it is, failure() says so ("conflict"); Phase 2 decides what changes.
#
# fields: label (Intelligence layers), family (environment, limit, provider, work, control), layer (the G5 layer where it
# arises), own (the work's own fault), fixes (retrying can fix it: this module's RECOVERY), recovery, ops (Mission Operations:
# situation, recovery, who), dispatch (Control Hub dispatcher: retry / never / None), autoloop (Autoloop's label, policy)
_ENV_RETRY = "Run it again: a deploy or restart cut it off. Mission Control and Autoloop requeue their own work by themselves."
FAILURE_CLASSES = {
    "restart": {"label": "Cut off by a restart", "family": "environment", "layer": "execution", "own": False, "fixes": True,
                "recovery": _ENV_RETRY, "dispatch": "retry",
                "ops": ("environment", "Cut off by a restart: back in the queue, not counted against the task.", "AXoR"),
                "autoloop": ("Cut off by a restart", "Back in the queue on autopilot, not counted")},
    "quota": {"label": "Plan usage limit", "family": "limit", "layer": "workforce", "own": False, "fixes": True,
              "recovery": "Wait for the plan's usage window to reset, or route the work to another login or provider (Agents → My logins).", "dispatch": "retry",
              "ops": ("provider", "The plan's usage limit lasts hours: its work waits in the queue and resumes at the reset. Retrying now is pointless.", "AXoR"),
              "autoloop": ("Plan usage limit", "Back in the queue, not counted; every team on that plan (Terminal or Codex) waits for its reset")},
    "budget": {"label": "Out of budget", "family": "limit", "layer": "execution", "own": False, "fixes": True,
               "recovery": "Raise the budget that stopped it (Agent Operations → Budget, or the scoped limit), or wait for the next day.", "dispatch": "never",
               "ops": ("budget", "Out of budget: the work waits in the queue. Raise the budget or wait for the window; it is not the task's fault.", "you"),
               "autoloop": ("Out of budget", "Back in the queue, not counted")},
    "provider": {"label": "Model provider refused", "family": "provider", "layer": "workforce", "own": False, "fixes": False,
                 "recovery": "Fix the provider first: a key, credit or permission was refused (Agents → Models). Retrying won't help until then.", "dispatch": "retry",
                 "ops": ("provider", "The model provider refused the key or the account is out of credit: fix the key or the credit in Agents → Models.", "you"),
                 "autoloop": ("Model provider refused", "Back in the queue; the team cools down")},
    "rate": {"label": "Rate limited", "family": "limit", "layer": "workforce", "own": False, "fixes": True,
             "recovery": "Retry with backoff; lower the runs at once per login if it keeps happening.", "dispatch": "retry",
             "ops": ("provider", "Rate limited: retried with backoff while the team cools down.", "AXoR"),
             "autoloop": ("Rate limited", "Retried with backoff; the team cools down")},
    "transient": {"label": "Timeout or network", "family": "environment", "layer": "execution", "own": False, "fixes": True,
                  "recovery": "Retry: a timeout or a network error.", "dispatch": "retry",
                  "ops": ("environment", "A timeout or network error: retried with backoff.", "AXoR"),
                  "autoloop": ("Transient", "Retried with backoff")},
    "cap": {"label": "Over the task's cap", "family": "limit", "layer": "execution", "own": True, "fixes": False,
            "recovery": "Split the task: it needs more than its token cap.", "dispatch": "never",
            "ops": ("task_failure", "Over the task's token cap without filing: split the task into smaller ones.", "the team lead"),
            "autoloop": ("Over the task's cap", "Counted; split the task")},
    "sandbox": {"label": "Sandbox", "family": "environment", "layer": "execution", "own": False, "fixes": True,
                "recovery": "See the sandbox diagnosis below: most sandbox failures are the environment's, not the code's.", "dispatch": "retry",
                "ops": ("environment", "The sandbox couldn't run it: repair the sandbox (pod, image, input size), not the agent's instructions.", "AXoR")},
    "tool": {"label": "Tool or MCP", "family": "environment", "layer": "execution", "own": False, "fixes": False,
             "recovery": "Fix or re-grant the tool the error names (Agents → Tools & MCP).", "dispatch": "retry",
             "ops": ("environment", "A tool or MCP server failed: check the tool's grant and its server, then retry.", "you")},
    "task": {"label": "The task itself", "family": "work", "layer": "execution", "own": True, "fixes": False,
             "recovery": "Read the error: the work itself failed. Repeated failures of one agent become an Evolution proposal.",
             "ops": ("task_failure", "The work itself failed: diagnose the approach, change the engineering strategy, then try the changed plan.", "the team lead"),
             "autoloop": ("The task itself", "Counted; twice and it waits for you")},
    "low": {"label": "Finished, scored under 50", "family": "work", "layer": "evaluation", "own": True,
            "ops": ("task_failure", "Finished but scored low: compare with the acceptance criteria and test an alternative.", "the team lead")},
    # canonical refinements: failure() names these where the error says more than the legacy class does
    "credential": {"label": "Login or credential missing", "family": "provider", "layer": "workforce", "own": False, "fixes": False,
                   "recovery": "Sign the login in or give the credential it names (Agents → Models / My logins); retrying won't help until then."},
    "capability": {"label": "Required capability missing", "family": "environment", "layer": "execution", "own": False, "fixes": False,
                   "recovery": "Provide what the task needs (an environment, a service, a tool) or change the task; Phase 2's preflight checks it before dispatch."},
    "input_too_large": {"label": "Input over the sandbox's limit", "family": "limit", "layer": "execution", "own": True, "fixes": False,
                        "recovery": "Narrow the run with paths: even the files the command names are over the input limit."},
    "timeout": {"label": "Ran past its time limit", "family": "limit", "layer": "execution", "own": True, "fixes": False,
                "recovery": "Give it a longer timeout, or make it faster."},
    "no_deliverable": {"label": "Finished without a deliverable", "family": "work", "layer": "execution", "own": True, "fixes": False,
                       "recovery": "The agent ended without filing its work: send it back with what to file, or split the task."},
    # 2026-11-11 reconciliation (#13): the five "finished without filing" runs of 11-09 had all used every step of the tool loop
    "step_limit": {"label": "Used all its steps without filing", "family": "work", "layer": "execution", "own": True, "fixes": False,
                   "recovery": "The run spent every tool-loop step before filing (since 11-10 it gets one closing turn to file). If it repeats, "
                               "narrow the task or split it: the work didn't fit the step budget."},
    "invalid_output": {"label": "Invalid output", "family": "work", "layer": "evaluation", "own": True, "fixes": False,
                       "recovery": "The output didn't parse or match its schema: fix the format the task asks for."},
    "test": {"label": "Tests or benchmark failed", "family": "work", "layer": "evaluation", "own": True, "fixes": False,
             "recovery": "Read the failing checks: the work doesn't meet them yet."},
    "strategy": {"label": "Nothing to do or no plan", "family": "work", "layer": "mission", "own": True, "fixes": False,
                 "recovery": "Re-plan: the approach or the scope produced no work."},
    "cancelled": {"label": "Cancelled", "family": "control", "layer": "mission", "own": False, "fixes": False,
                  "recovery": "Stopped on purpose: nothing to recover."},
}
LEGACY_CLASSES = ("restart", "quota", "budget", "provider", "rate", "transient", "cap", "sandbox", "tool", "task", "low")  # what fail_class names
# the consumers' tables, derived (same keys, same order, same values as before 2026-11-11)
RECOVERY = {k: (FAILURE_CLASSES[k]["fixes"], FAILURE_CLASSES[k]["recovery"])  # a failed run's class → (retrying can fix it, the recovery)
            for k in ("restart", "quota", "budget", "provider", "rate", "transient", "cap", "sandbox", "tool", "task")}
# the failure classes that are the work's own fault (the rest are the environment's: a restart, quota, budget, provider, rate limit,
# timeout, sandbox or tool), whatever retrying would do: outcomes() and the acceptance test's Evolve step split failures by it
OWN_FAULT = tuple(k for k in ("task", "cap") if FAILURE_CLASSES[k]["own"])
FAIL_LABEL = {k: FAILURE_CLASSES[k]["label"] for k in LEGACY_CLASSES}
OPS_RECOVERY = {k: FAILURE_CLASSES[k]["ops"] for k in ("quota", "rate", "provider", "budget", "restart", "transient", "sandbox", "tool", "cap", "task", "low")}
DISPATCH_RETRY = {k for k in LEGACY_CLASSES if FAILURE_CLASSES[k].get("dispatch") == "retry"}
DISPATCH_NEVER = {k for k in LEGACY_CLASSES if FAILURE_CLASSES[k].get("dispatch") == "never"}
AUTOLOOP_LABEL = {k: FAILURE_CLASSES[k]["autoloop"][0] for k in ("restart", "quota", "budget", "provider", "rate", "transient", "cap", "task")}
AUTOLOOP_POLICY = {k: FAILURE_CLASSES[k]["autoloop"][1] for k in ("restart", "quota", "budget", "provider", "rate", "transient", "cap", "task")}
# policies that disagree between consumers, kept as they were for the Owner to decide (G5 Phase 1 report)
CONFLICTS = [
    {"classes": ("provider", "tool"), "what": "The Control Hub dispatcher retries these on the same agent (dispatch 'retry'), while "
     "the orchestrator's recovery says retrying can't fix them (fixes False) and Mission Operations sends 'provider' to you."},
    {"classes": ("budget",), "what": "The orchestrator says retrying (after a raise or a new day) fixes it; the dispatcher never retries it: "
     "a limit is a decision. Both hold; they answer different questions."},
    {"classes": ("credential", "capability"), "what": "The legacy classifier files these errors under 'task', the work's own fault; the "
     "canonical class says they are the environment's (a missing login, a missing capability). Which one counts against an agent is a "
     "Phase 2 decision."},
]
CREDENTIAL = re.compile(r"isn't signed in|not signed in|not logged in|setup-token|no model is connected|login (?:expired|revoked)|token (?:expired|revoked)|"
                        r"rejected the server's .{0,40}login|login doesn't work|expired or was revoked", re.I)
NO_DELIVERABLE = re.compile(r"finished without (?:filing|a deliverable)|without filing the work", re.I)
STEP_LIMIT = re.compile(r"used all (?:of )?its \d+ steps", re.I)
# a missing capability, said as such (not "missing" or "no such" alone: those are ordinary code errors as often as not)
CAPABILITY = re.compile(r"(?:isn't|is not|not) (?:set up|configured|installed|connected)|\b(?:switched|turned) off\b|"
                        r"\bno (?:docker|kvm|gpu|registry|virtual machine)\b|\b(?:docker|kvm|gpu|registry)\b[^.]{0,40}\b(?:unavailable|not available|missing)\b", re.I)
# Mission Control's own classes that refine 'task' (no hit in the 2026-11-11 corpus: unvalidated on real errors)
_MISSION_TO_CANONICAL = {"invalid_output": "invalid_output", "test": "test", "strategy": "strategy"}

# ------------------------------------------------------------------ recognition: every failure pattern, in this one place
# (G5 Phase 1 completion, Owner review B5). Until 2026-11-11 the patterns lived in four modules: Autoloop (mining_autoloop.
# CLASSES), Mission Control (missions.FAILURES), the sandbox diagnosis (SBX below) and the canonical refinements above. They are
# all here now, and those modules read them from here. The vocabularies stay three ordered lists, because the same words mean
# different things to each reader (Owner decision D5, G5_PHASE1_REPORT §5): "timed out" is a transient run failure to Autoloop
# and a missed deadline to a mission; "model" names a provider problem to a mission and nothing to Autoloop. recognize() reads
# one error once, in every vocabulary.
# Autoloop's run classes: (class, pattern in the error); the first match wins, else "task"
AUTOLOOP_PATTERNS = (
    ("quota", r"plan rate limit reached|usage limit"),  # llm.QuotaError: the Claude or ChatGPT (Codex) plan, hours not minutes
    ("budget", r"token budget"),
    ("provider", r"credit|insufficient|quota|billing|payment|\b401\b|\b403\b|unauthori[sz]ed|invalid.{0,12}key|authentication|no model is connected|"
                 r"rejected the server's .{0,40}login|login doesn't work|expired or was revoked"),  # llm.TOKEN_REJECTED, cli_accounts (2026-11-17)
    ("rate", r"rate.?limit|\b429\b|too many requests|overloaded|\b529\b"),
    ("cap", r"token cap"),
    ("transient", r"timed? ?out|timeout|deadline|server restart|connection|temporar|\b50[0234]\b|unavailable|reset by peer|\beof\b"),
)
# Mission Control's mission classes: (class, pattern on the lower-cased error) in order, else "unknown"; and what a mission does
# about each (MISSION_ACTIONS: pause, deliver, retry, replan, stop). The Owner's D2 (retry only transient failures) changes these
# actions in Phase 2; Phase 1 keeps them as they were.
MISSION_PATTERNS = [
    ("cancelled", r"\bcancel"),
    ("budget", r"budget|used up|out of tokens|token limit|credit balance|no credits"),
    ("deadline", r"deadline|timed? ?out|took too long"),
    ("api", r"rate.?limit|429|503|502|overloaded|couldn't reach|connection|unavailable"),
    ("model", r"model|claude|openai|openrouter|declined|refus"),
    ("invalid_output", r"invalid|malformed|json|schema|parse|unexpected output"),
    ("test", r"tests? fail|assert|benchmark fail"),
    ("environment", r"sandbox|pod|container|not (set up|configured|connected)|no such|missing|turned off|paused"),
    ("infrastructure", r"restart|server|database|disk|memory|killed"),
    ("strategy", r"no task|nothing to|couldn't plan|approach|strategy|scope"),
]
MISSION_ACTIONS = {"budget": "pause", "deadline": "deliver", "api": "retry", "model": "retry", "infrastructure": "retry", "unknown": "retry",
                   "invalid_output": "replan", "test": "replan", "strategy": "replan", "environment": "stop", "cancelled": "stop"}


def autoloop_class(err):
    """Autoloop's class of an error (mining_autoloop.classify)."""
    for k, pat in AUTOLOOP_PATTERNS:
        if re.search(pat, err or "", re.I): return k
    return "task"


def mission_class(text):
    """Mission Control's class of an error (missions.classify)."""
    t = str(text or "").lower()
    return next((k for k, p in MISSION_PATTERNS if re.search(p, t)), "unknown")


def recognize(status, error):
    """One error read once in every vocabulary: {fail_class, autoloop, missions, mission_action, sandbox, credential, capability,
    no_deliverable}. failure() builds the canonical class on it."""
    st, e = (status or "failed").lower(), error or ""
    mk = mission_class(e)
    return {"fail_class": fail_class(st, e), "autoloop": autoloop_class(e), "missions": mk, "mission_action": MISSION_ACTIONS.get(mk, "retry"),
            "sandbox": sbx_class(st, e)[0], "credential": bool(CREDENTIAL.search(e)), "capability": bool(CAPABILITY.search(e)),
            "no_deliverable": bool(NO_DELIVERABLE.search(e))}


def fail_class(status, error):
    """The legacy class of a failed run from its status and error (what every loop decides on today): restart, then Autoloop's
    classes (quota, budget, provider, rate, cap, transient), then sandbox and tool, else the task itself. Moved here from
    intel_layers on 2026-11-11 (it re-exports it); unchanged."""
    if status == "lost" or "server restart" in (error or "").lower(): return "restart"
    e = error or ""
    k = autoloop_class(e)
    if k != "task": return k
    if _SANDBOX_ERR.search(e): return "sandbox"
    if _TOOL_ERR.search(e): return "tool"
    return "task"


_SANDBOX_ERR = re.compile(r"sandbox|\bpod\b|container|gvisor|exit code|\boom(?:killed)?\b|out of memory|killed", re.I)  # "oom" as a word: "room", "zoom" aren't
_TOOL_ERR = re.compile(r"\btool\b|\bmcp\b|tool_use|function call", re.I)


def failure(status, error, source=""):
    """One failure, read once: {cls, label, family, layer, own, fixes, recovery, legacy: {fail_class, autoloop, missions, sandbox},
    conflict}. cls is canonical: the legacy class, refined where the error says more. Status "timeout" (only sandbox runs have it)
    is the run's own time limit; source "sandbox" also names the sandbox class. conflict: the canonical and legacy readings disagree
    on whose fault it is. Refinements with no hit in the 2026-11-11 corpus (capability, invalid_output, test, strategy) are
    unvalidated on real errors."""
    st, e = (status or "failed").lower(), error or ""
    k, auto, mk = fail_class(st, e), autoloop_class(e), mission_class(e)
    sbx = sbx_class(st, e)[0] if source == "sandbox" or k == "sandbox" else None
    if st in ("cancelled", "stopped") or mk == "cancelled": c = "cancelled"
    elif k != "task": c = k
    elif CREDENTIAL.search(e): c = "credential"
    elif sbx == "too_large" or re.search(r"files come to|don't fit the sandbox", e, re.I): c = "input_too_large"
    elif st == "timeout": c = "timeout"
    elif STEP_LIMIT.search(e): c = "step_limit"  # a refinement of no_deliverable: same recovery action
    elif NO_DELIVERABLE.search(e): c = "no_deliverable"
    elif CAPABILITY.search(e): c = "capability"
    elif mk in _MISSION_TO_CANONICAL: c = _MISSION_TO_CANONICAL[mk]
    else: c = "task"
    d = FAILURE_CLASSES[c]
    legacy_own = FAILURE_CLASSES[k]["own"]
    return {"cls": c, "label": d["label"], "family": d["family"], "layer": d["layer"], "own": d["own"], "fixes": d.get("fixes", False),
            "recovery": d.get("recovery", ""), "legacy": {"fail_class": k, "autoloop": auto, "missions": mk, "sandbox": sbx},
            "conflict": d["own"] != legacy_own and c != "cancelled"}


# ------------------------------------------------------------------ recovery decisions (G5-2 milestone 1, Owner D-015 D1/D2)
# One answer to "what now?" for a failed run, read by the Control Hub dispatcher, Autoloop and Mission Control.
# - D1: a failure that isn't the work's own (a missing login, a provider refusal, the environment) never counts against the
#   agent; it counts in platform reliability (outcomes(): the 'environment' bucket).
# - D2: only transient failures retry by themselves. Owner clarification A: an immediate retry (timeout, network) is kept apart
#   from a delayed recovery (rate limit, plan quota, restart, a busy sandbox), which waits for its cause to pass. Authentication,
#   permission, missing capability, invalid input and tool failures stop, with their remediation, or go back to planning.
# Every retry is bounded (max tries), backs off exponentially, carries a deterministic jitter (from the retry key, so two
# workers compute the same moment) and an idempotency key "<ref>:retry:<n>" the caller records with the run it starts.
# action: retry_now | retry_later | hold (a limit: a person decides) | stop (remediate first) | replan | none (cancelled)
RECOVERY_POLICY = {
    "transient": {"action": "retry_now", "base": 30, "cap": 900, "tries": 3},
    "rate": {"action": "retry_later", "base": 300, "cap": 3600, "tries": 3},
    "quota": {"action": "retry_later", "base": 3600, "cap": 6 * 3600, "tries": 3},
    "restart": {"action": "retry_later", "base": 60, "cap": 600, "tries": 3},
    "sandbox": {"action": "retry_later", "base": 120, "cap": 1800, "tries": 3},        # only the sandbox classes SBX marks recoverable
    "budget": {"action": "hold"},
    "cap": {"action": "replan"},
    "provider": {"action": "stop"}, "credential": {"action": "stop"}, "tool": {"action": "stop"}, "capability": {"action": "stop"},
    "input_too_large": {"action": "replan"}, "invalid_output": {"action": "replan"}, "test": {"action": "replan"},
    "strategy": {"action": "replan"}, "no_deliverable": {"action": "replan"}, "step_limit": {"action": "replan"}, "timeout": {"action": "replan"},
    "task": {"action": "replan"}, "low": {"action": "replan"}, "cancelled": {"action": "none"},
}
JITTER = 0.2  # share of the wait: ± for an immediate retry, + only for a delayed recovery (it never comes before its cause passes)


def _jitter(key, wait, later=False):
    h = int(hashlib.sha1(str(key or "").encode()).hexdigest()[:8], 16) / 0xFFFFFFFF  # 0..1, the same for the same key
    return round(wait * (1 + JITTER * (h if later else 2 * h - 1)))


def decide(status, error, source="", tries=0, key="", now=None):
    """What to do about one failed run: {cls, action, delay, max_tries, retry, retry_key, agent_fault, reliability, remediation,
    who, why}. tries: how many retries already ran. retry is False when the action isn't a retry or the tries are spent."""
    now = now or time.time()
    f = failure(status, error, source)
    c, pol = f["cls"], RECOVERY_POLICY.get(f["cls"], {"action": "replan"})
    action, delay = pol["action"], 0
    if c == "sandbox":
        sub = sbx_class("error", error)
        if not sub[2]: action = "stop"  # not set up, gVisor missing, image, input: retrying can't fix it
    policy = action  # the class's own answer, before spent retries turn a retry into a stop
    if action in ("retry_now", "retry_later"):
        # a plan quota waits base × 2^n here; Autoloop reads the plan's real reset itself (llm.quota_until)
        delay = _jitter(f"{key}:{tries + 1}", min(pol["cap"], pol["base"] * 2 ** max(0, tries)), later=action == "retry_later")
    max_tries = pol.get("tries", 0)
    retry = action in ("retry_now", "retry_later") and tries < max_tries
    who = "AXoR" if retry or action == "none" else "you" if action in ("stop", "hold") else "the team lead"
    remediation = f.get("recovery") or FAILURE_CLASSES.get(c, {}).get("recovery", "")
    if action in ("retry_now", "retry_later") and not retry:
        action, who = "stop", "you"
        remediation = f"Retried {tries} times without success: look at it before it runs again. " + remediation
    return {"cls": c, "action": action, "policy": policy, "delay": delay if retry else 0, "max_tries": max_tries, "retry": retry,
            "retry_key": f"{key}:retry:{tries + 1}" if retry else None, "agent_fault": f["own"],
            "reliability": not f["own"] and c != "cancelled", "remediation": remediation, "who": who, "legacy": f["legacy"]["fail_class"],
            "why": f"{f['label']}: " + {"retry_now": "retried shortly", "retry_later": "recovered after its cause passes", "hold": "a limit; a person decides",
                                        "stop": "stopped until it is fixed", "replan": "back to planning", "none": "nothing to recover"}[action]}


OWN_CANON = tuple(k for k, d in FAILURE_CLASSES.items() if d["own"])  # canonical classes that are the work's own fault (D1)
OWN_SQL = ",".join(f"'{c}'" for c in OWN_CANON)  # for SQL IN (...): fixed class names, no user input
# sandbox runs that couldn't run: (class, label, pattern on the error, recoverable, recovery); the first match wins
SBX = (
    ("restart", "Cut off by a restart", r"server restart", True, "Run it again: a deploy cut it off."),
    ("gvisor", "gVisor not installed", r"gvisor", False, "Install gVisor on the node (sudo k8s/install-gvisor.sh) or turn the team's internet off: runs with internet only start under gVisor."),
    ("egress", "Egress proxy down", r"egress proxy|EGRESS_SECRET|can't have it|internet for sandbox runs is switched off", True,
     "Check the egress proxy (kubectl -n axor-egress get deploy egress), then run it again."),
    ("off", "Sandbox not set up", r"switched off on this server|isn't on a cluster|No sandbox image|namespace isn't set up|model proxy couldn't listen", False,
     "An administrator sets the sandbox up (k8s/deploy.sh): image, namespace axor-sandbox and its model proxy."),
    ("busy", "All sandbox slots busy", r"sandbox is busy", True, "Run it again in a few minutes, or raise SANDBOX_MAX_RUNS."),
    ("too_large", "Input over the size limit", r"files come to|don't fit the sandbox", False,
     "Narrow the run with paths: even the files the command names are over the input limit (bigger inputs are packed by themselves now)."),
    ("image", "Container couldn't start", r"ErrImagePull|ImagePullBackOff|InvalidImageName|CreateContainer|couldn't start", False,
     "The sandbox image isn't on the node or won't start: ./k8s/redeploy.sh loads it."),
    ("kube", "Kubernetes refused the pod", r"Kubernetes refused|Kubernetes didn't answer", True, "Read Kubernetes' reason (quota or admission policy); run it again once it's fixed."),
    ("lost", "Pod lost mid-run", r"Lost track|disappeared|pod ended", True, "Run it again: the pod went away mid-run."),
    ("budget", "Sandbox inference budget spent", r"inference budget", True, "The workspace's sandbox model budget for today is spent: wait, or raise SANDBOX_DAY_USD."),
)
SBX_LABEL = {k: l for k, l, *_ in SBX} | {"timeout": "Took too long", "other": "Other"}

COVERAGE_TARGET = 95       # % of scoreable finished runs (scored + gaps) that should carry a score
HUMAN_GRACE = 3 * 86400  # a verdict that is a person's decision (accept, approve, merge) gets this long before it's a gap
GAP_RECHECK = 600        # seconds between re-checks of the gaps (a verdict that came later turns a gap into a score)
SETTLE_AFTER = 1800     # an open recalled experience whose work has a final record gets this long for its own system to settle it

# Every run type the code records has an evaluator here (tests/unit/test_evaluators.py fails when one doesn't): rows of
# (system, kind, ref prefix, evaluator, what), first match wins, "*" matches anything, a kind ending in "*" is a prefix.
# exclude: never scored, for the reason given (evaluation tooling, reporting, chats people rate themselves);
# own: its own system scores it (agent_core.score) or keeps a verdict _verdict() reads; none: nobody judges it yet (a named gap);
# the rest are derived from the decisions its system records (_derived), a person's or an evaluator agent's.
# G5-5 L5.1 (contract IC-11): a row that yields a verdict also declares, as its sixth field, what that verdict rests on:
# model_judged (a model evaluator or verifier scored the output), derived (a fixed number AXoR assigns to a status, a decision or a
# verdict: nobody scored the output) or reviewed (a board task's review: kept as a verdict, with no number). None of the three is
# measured in D-005's sense: measured values live in a mission's measures (missions.measured).
BASES = ("model_judged", "derived", "reviewed")
EVALUATORS = (
    ("*", "earlier", "", "exclude", "Recorded from before the run ledger: no output was kept to judge"),
    ("*", "chat", "", "exclude", "A chat: the person rates its answers in the chat (thumbs), which the promotion monitor reads"),
    ("evolution", "cases", "", "exclude", "Evaluation tooling: drafts benchmark cases, which are themselves reviewed"),
    ("evolution", "draft", "", "exclude", "Evaluation tooling: drafts a proposal, which an experiment then measures"),
    ("evolution", "experiment", "", "own", "The experiment's blind judge (the candidate's mean)", "model_judged"),
    ("evolution", "team-test", "", "exclude", "Evaluation tooling: grades a Team tests case against its hidden checks; it is the verdict"),
    ("hq", "*", "", "exclude", "Agent HQ's patrol and report rounds: monitoring, no deliverable to score"),
    ("marketplace", "tasks", "", "exclude", "Drafts the role tasks an evaluation then scores"),
    ("marketplace", "eval", "", "exclude", "Evaluation tooling: it is the verdict on a marketplace agent"),
    ("marketplace", "watch", "", "exclude", "Evaluation tooling: the check on an activated marketplace agent"),
    ("missions", "verify", "", "exclude", "Mission Control's independent check itself: it gives the mission its score"),
    ("missions", "deliver", "", "exclude", "The delivery summary of a result the independent check already scored"),
    ("missions", "*", "mx:", "mission", "Mission Control's independent check of the mission", "model_judged"),
    ("teams", "review", "", "exclude", "Evaluation tooling: a squad lead's review, whose verdict is the score of the work it reviewed"),
    ("teams", "task", "mw:", "team_task", "Its reviewer's verdict, a squad lead's or yours: reviewed, not measured (no score)", "reviewed"),
    ("teams", "plan", "mw:", "team_plan", "How the tasks the plan put on the board ended (the share delivered)", "derived"),
    ("teams", "report", "", "exclude", "The Director's report to you: reporting, no deliverable to score"),
    ("teams", "portfolio", "", "exclude", "A portfolio review across your teams: reporting, no deliverable to score"),
    ("teams", "upgrade:*", "", "exclude", "Evaluation tooling: an upgrade sprint, whose blind held-out exam is the verdict on the agent"),
    ("workflow", "review", "", "exclude", "Evaluation tooling: the reviewer's verdict on a diff"),
    ("workflow", "check", "", "exclude", "Evaluation tooling: the folder's own checks on a commit"),
    ("workflow", "engineer", "mb:", "workflow_engineer", "Its task's merge after an approving review and passing checks", "derived"),
    ("workflow", "*", "", "none", "The Workflow judges commits (review, checks, Lab evals), not its planning and improvement runs"),
    ("workforce", "swarm-evaluate", "", "exclude", "Evaluation tooling: the swarm's evaluator, whose verdict scores the contracts"),
    ("workforce", "swarm-*", "sw:", "own", "The swarm's evaluator, or its contract check", "model_judged"),
    ("workforce", "evaluate", "", "exclude", "Evaluation tooling: the Workforce's evaluator, whose verdict scores the mission and its runs"),
    ("workforce", "critique", "", "exclude", "Evaluation tooling: the critic's review of an assignment"),
    ("workforce", "factcheck", "", "exclude", "Evaluation tooling: the fact-checker's check of an assignment"),
    ("workforce", "*", "wf:", "own", "The Workforce reviewer's score, or its mission's verdict", "model_judged"),
    ("*", "task", "ctl:t", "control_task", "Your decision on its result: accepted 100, sent back 30", "derived"),
    ("other", "intelligence", "ctl:mi:", "intel", "Your decisions on the tasks it proposed: the share you approved", "derived"),
    ("other", "research", "ctl:t", "none", "Research before a fixed task (task_research.py): the task's result is judged, the brief itself isn't yet"),
    ("company", "brief", "", "none", "Leadership briefs are read, not judged: no evaluator yet"),
    ("company", "*", "co:", "company_task", "The company evaluator agent's score of the task's deliverable", "model_judged"),
    ("team", "task", "tt:", "own", "The tester's verdict (pass 100, rework 30)", "derived"),
    ("team", "cycle", "tc:", "own", "The cycle's check score", "model_judged"),
    ("longtask", "*", "", "none", "Long tasks record completion, not quality: no evaluator yet"),
)
HUMAN = ("team_task", "team_plan", "workflow_engineer", "control_task", "intel")  # decided by a person: HUMAN_GRACE
REVIEWED_SINCE = "eval.reviewed_since"  # app setting: when this server first ran G5-5 L5.1 (figures over a period that spans it mix both rules)
# a board task's review verdict, as its run's reason (G5-5 L5.1). "rejected" is re-read while it lasts: the person's decision replaces it
REVIEWED = {"approved": "Approved (its task is done): reviewed, unmeasured",
            "sent_back": "Sent back for another try (a later run of the same task): reviewed, unmeasured",
            "rejected": "Rejected by its reviewer (neither approved nor sent back again; it waits for a person): reviewed, unmeasured"}


def _now(): return time.time()
def _j(x, d=None):
    if x is None or x == "": return d
    if isinstance(x, (dict, list)): return x
    try: return json.loads(x)
    except (TypeError, ValueError): return d
def _clip(s, n): s = str(s or ""); return s if len(s) <= n else s[:n - 1] + "…"
def _sha(x): return hashlib.sha256(json.dumps(x, sort_keys=True).encode()).hexdigest()[:16]


def evaluator_for(system, kind, ref):
    """The EVALUATORS row for a run, or None (an unassigned run type)."""
    ref, kind = ref or "", kind or ""
    for row in EVALUATORS:
        s, k, pre = row[:3]
        if s not in ("*", system): continue
        if not (k == "*" or k == kind or (k.endswith("*") and kind.startswith(k[:-1]))): continue
        if pre and not ref.startswith(pre): continue
        return row
    return None


def basis_for(system, kind, ref, state="scored", corr=None, source=""):
    """What an evaluation row's verdict rests on (BASES), or None for a row that holds none (excluded, a gap). Taken from the run's
    EVALUATORS row, so a row written before L5.1 gets its kind on read without being rewritten (IC-11 changes 2 and 3)."""
    if state == "reviewed": return "reviewed"
    if state != "scored": return None
    E = evaluator_for(system, kind, ref)
    b = E[5] if E and len(E) > 5 else None
    if (source or "").startswith("Mission Control's independent check"): return "model_judged"  # its mission's check scored the whole mission, this run with it
    # a board task that carries a score: its 100, 30 or 10 was AXoR's mapping of a review verdict (before L5.1). A mission's
    # correlation alone doesn't change that: Orchestrator._basis looks whether the mission's own check gave this very score
    if b == "reviewed": return "derived"
    return b or "model_judged"  # a score on a run whose row declares none came from an evaluator's or verifier's own call


def public_event(e):
    """An io_events row with the event contract's field names beside the stored ones (corr is the correlation id; a Mission
    Control mission's is mx:N, so mission_id is read from it)."""
    e = dict(e)
    c = e.get("corr") or ""
    mid = int(c[3:]) if c.startswith("mx:") and c[3:].isdigit() else None
    return {**e, "event_id": e.get("id"), "correlation_id": e.get("corr"), "mission_id": mid, "source_layer": e.get("src"), "target_layer": e.get("dst"),
            "event_type": e.get("kind"), "created_at": e.get("created"), "completed_at": e.get("done"), "retry_count": e.get("attempts") or 0}


def sbx_class(status, error):
    """(class, label, recoverable, recovery) of a sandbox run that didn't run its code to the end."""
    if status == "timeout": return "timeout", SBX_LABEL["timeout"], True, "Give it a longer timeout, or make it faster."
    e = error or ""
    for k, label, pat, ok, fix in SBX:
        if re.search(pat, e, re.I): return k, label, ok, fix
    return "other", "Other", False, "Read the error on the run."


class EstimateIn(BaseModel):
    tokens: int = Field(..., ge=1, le=50_000_000)
    note: str = Field("", max_length=300)


class LimitIn(BaseModel):
    scope: str = Field(..., pattern=r"^(global|system|mission|team|agent|contract)$")
    key: str = ""
    label: str = ""
    tokens: int | None = Field(None, ge=0, le=10_000_000_000)
    period: str = Field("total", pattern=r"^(day|month|total)$")
    per_call: int | None = Field(None, ge=0, le=10_000_000)
    warn_pct: int | None = Field(None, ge=1, le=100)            # this limit's warn-at share; none: the owner's default
    mode: str = Field("stop", pattern=r"^(stop|alert)$")        # stop: a hard stop at the limit; alert: only alerts


class AlertsIn(BaseModel):
    warn_pct: int | None = Field(None, ge=1, le=100)            # the default warn-at share for the daily limit and every scoped limit
    notify: bool | None = None                                  # push a crossing to your devices


class Orchestrator:
    def __init__(self, db, ov=None, hub=None, evolution=None, work=None):
        self.db, self.ov, self.hub, self.ev, self.work = db, ov, hub, evolution, work
        q = db.q
        q("""CREATE TABLE IF NOT EXISTS io_events (id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, corr TEXT, kind TEXT, ref TEXT, src TEXT,
             dst TEXT, payload TEXT, key TEXT UNIQUE, status TEXT, attempts INTEGER DEFAULT 0, next_at REAL, error TEXT, result TEXT,
             created REAL, updated REAL, done REAL)""")
        q("CREATE INDEX IF NOT EXISTS io_events_s ON io_events (status, next_at)")
        q("CREATE INDEX IF NOT EXISTS io_events_o ON io_events (owner_id, created)")
        q("CREATE INDEX IF NOT EXISTS io_events_c ON io_events (corr)")
        q("""CREATE TABLE IF NOT EXISTS io_audit (id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, ts REAL, corr TEXT, actor TEXT, action TEXT,
             ref TEXT, detail TEXT)""")
        q("CREATE INDEX IF NOT EXISTS io_audit_o ON io_audit (owner_id, id)")
        q("CREATE TABLE IF NOT EXISTS io_links (ref TEXT PRIMARY KEY, corr TEXT, owner_id INTEGER, created REAL)")
        q("""CREATE TABLE IF NOT EXISTS io_evals (run_id INTEGER PRIMARY KEY, owner_id INTEGER, system TEXT, kind TEXT, ref TEXT, corr TEXT, state TEXT,
             reason TEXT, source TEXT, score REAL, ts REAL)""")
        q("CREATE INDEX IF NOT EXISTS io_evals_o ON io_evals (owner_id, state)")
        q("""CREATE TABLE IF NOT EXISTS io_diag (run_id INTEGER PRIMARY KEY, owner_id INTEGER, system TEXT, ref TEXT, corr TEXT, agent_key TEXT,
             cls TEXT, recoverable INTEGER, recovery TEXT, evidence TEXT, ts REAL)""")
        q("CREATE INDEX IF NOT EXISTS io_diag_o ON io_diag (owner_id, ts)")
        q("""CREATE TABLE IF NOT EXISTS io_sbx (sbx_id INTEGER PRIMARY KEY, comp_id INTEGER, cls TEXT, recoverable INTEGER, recovery TEXT,
             retried_as INTEGER, ts REAL)""")
        q("""CREATE TABLE IF NOT EXISTS io_datasets (id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, kind TEXT, ref TEXT, name TEXT,
             version INTEGER, sha TEXT, cases TEXT, created REAL, UNIQUE (owner_id, kind, ref, sha))""")
        q("""CREATE TABLE IF NOT EXISTS io_bench_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, dataset_id INTEGER, ts REAL, by_user TEXT,
             metrics TEXT, per_case TEXT, passed INTEGER, ms INTEGER)""")
        q("CREATE INDEX IF NOT EXISTS io_bench_runs_o ON io_bench_runs (owner_id, id)")
        q("""CREATE TABLE IF NOT EXISTS io_monitor (proposal_id INTEGER PRIMARY KEY, owner_id INTEGER, target_key TEXT, promoted REAL, base_avg REAL,
             base_n INTEGER, after_avg REAL, after_n INTEGER, state TEXT, checked REAL, note TEXT)""")
        # the canonical risk register (D-012, G5-2): readiness findings are its only input in G5-2; G5-3 adds hq issues, alerts, diagnoses
        q("""CREATE TABLE IF NOT EXISTS io_risks (id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, rkey TEXT, mission TEXT, task_ref TEXT,
             layer TEXT, source TEXT, source_ref TEXT, title TEXT, description TEXT, root_cause TEXT, probability TEXT, impact TEXT, severity TEXT,
             priority TEXT, critical INTEGER DEFAULT 0, detection TEXT, countermeasure TEXT, responsible TEXT, approval TEXT, status TEXT,
             evidence TEXT, verification TEXT, first_seen REAL, last_seen REAL, seen INTEGER DEFAULT 1, resolved_at REAL, accepted_by TEXT,
             accepted_at REAL, updated REAL, UNIQUE (owner_id, rkey))""")
        q("CREATE INDEX IF NOT EXISTS io_risks_o ON io_risks (owner_id, status, mission)")
        for t, c in (("io_diag", "recovered"), ("io_monitor", "basis"), ("io_diag", "canon"),  # canon: failure()'s canonical class (G5 Phase 1)
                     ("io_evals", "basis")):  # G5-5 L5.1: what the row's verdict rests on (BASES); NULL on rows from before it (basis_for reads those)
            if c not in self._cols(t): q(f"ALTER TABLE {t} ADD COLUMN {c} TEXT")
        # recovery: a handler a restart cut off runs again (its key keeps it from running twice once it's done)
        q("UPDATE io_events SET status='pending', next_at=? WHERE status='running'", (_now(),))
        # a diagnosis of one of your own agents used to be refused ("the same as the current version") and dead-lettered: they go again
        q("""UPDATE io_events SET status='pending', attempts=0, next_at=?, error=NULL WHERE status='dead' AND kind='agent.signal'
             AND error LIKE '%same as the current version%'""", (_now(),))
        try:  # G5-5 L5.1 (IC-11 open points (c), (e)): the date from which a board task's review is recorded as reviewed, not scored
            if hasattr(self.db, "setting") and self.db.setting(REVIEWED_SINCE) is None: self.db.setting(REVIEWED_SINCE, v=str(_now()))
        except Exception as e: log.warning("orchestrator: couldn't record %s: %s", REVIEWED_SINCE, e)  # noqa: BLE001 - only a page note depends on it
        self.systems = {}  # main.py: "control", "workforce", "infiagent", "missions": the systems recover() goes through
        self.stopped, self.lock = threading.Event(), threading.Lock()
        self.last_tick, self.last_error, self._last_prune, self._gaps_at = None, None, None, None
        self._last_feeds = None  # G5-3: when the risk feeds last ran (risk_feeds)
        agent_core.register_resolver(self.resolve)

    # ------------------------------------------------------------------ plumbing
    def _has(self, t): return bool(self.db.q("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,), one=True))

    def _cols(self, t): return {r["name"] for r in self.db.q(f"PRAGMA table_info({t})")}

    def audit(self, owner, actor, action, ref="", detail="", corr=None):
        self.db.q("INSERT INTO io_audit (owner_id, ts, corr, actor, action, ref, detail) VALUES (?,?,?,?,?,?,?)",
                  (owner, _now(), corr, actor, action, ref, _clip(detail, 600)))

    def _gate(self, me):
        if self.ov is not None and not self.ov._agents_ok(me):
            raise HTTPException(403, "Agents aren't turned on for your account. An administrator can turn them on for members.")

    # ------------------------------------------------------------------ correlation
    def link(self, ref, corr, owner):
        """A child's ref belongs to corr from now on (Mission Control: "wfm:12" → "mx:4" when it launches Workforce mission 12)."""
        if not (ref and corr): return
        self.db.q("""INSERT INTO io_links (ref, corr, owner_id, created) VALUES (?,?,?,?)
                     ON CONFLICT(ref) DO UPDATE SET corr=excluded.corr, owner_id=excluded.owner_id""", (ref, corr, owner, _now()))

    def _corr_of(self, key):
        r = self.db.q("SELECT corr FROM io_links WHERE ref=?", (key,), one=True)
        return r["corr"] if r else None

    def resolve(self, system, ref):
        """agent_core's resolver: what a run with this ref belongs to. One or two indexed reads per run (not per call)."""
        if not ref: return {}
        p, _, rest = ref.partition(":")
        out = {}
        if p == "wf" and rest.isdigit() and self._has("wf_runs"):
            r = self.db.q("SELECT mission_id FROM wf_runs WHERE id=?", (int(rest),), one=True)
            if r and r["mission_id"]:
                k = f"wfm:{r['mission_id']}"
                out["corr"] = self._corr_of(k) or k
        elif p == "sw" and rest.isdigit() and self._has("sw_runs"):
            r = self.db.q("SELECT swarm_id, contract_id FROM sw_runs WHERE id=?", (int(rest),), one=True)
            if r:
                k = f"sws:{r['swarm_id']}"
                out["corr"] = self._corr_of(k) or k
                if r["contract_id"]: out["contract"] = f"swc:{r['contract_id']}"
        elif p == "mw" and rest.isdigit() and self._has("mw_runs"):
            r = self.db.q("SELECT comp_id, task_id FROM mw_runs WHERE id=?", (int(rest),), one=True)
            if r:
                out["team"] = f"comp:{r['comp_id']}"
                if r["task_id"]:
                    k = f"mwt:{r['task_id']}"
                    out["corr"] = self._corr_of(k) or self._corr_of(out["team"]) or k
        elif p == "co" and rest.isdigit() and self._has("co_tasks"):
            r = self.db.q("SELECT team_id FROM co_tasks WHERE id=?", (int(rest),), one=True)
            if r and r["team_id"]: out["team"] = f"co-team:{r['team_id']}"
        if "corr" not in out:
            c = self._corr_of(ref)
            if c: out["corr"] = c
        return out

    # ------------------------------------------------------------------ events
    def emit(self, owner, kind, key, corr=None, ref=None, payload=None, status="pending", at=None):
        """One handoff, once: a second emit with the same key is ignored (idempotent). Returns the event id or None.
        at: when it happened, for a handoff observed from a record after the fact."""
        src, dst, _ = KINDS.get(kind, ("", "", ""))
        now = at or _now()
        r = self.db.q("""INSERT OR IGNORE INTO io_events (owner_id, corr, kind, ref, src, dst, payload, key, status, next_at, created, updated, done)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
                      (owner, corr, kind, ref, src, dst, json.dumps(payload) if payload is not None else None, key, status, now, now, now,
                       now if status == "done" else None), one=True)
        return r and r["id"]

    def process(self, limit=200):
        """Due events through their handlers. A handler that raises is retried with backoff; after MAX_ATTEMPTS it's a dead letter."""
        n = 0
        for e in self.db.q("SELECT * FROM io_events WHERE status='pending' AND next_at<=? ORDER BY id LIMIT ?", (_now(), limit)):
            if self.stopped.is_set(): break
            got = self.db.q("UPDATE io_events SET status='running', updated=? WHERE id=? AND status='pending' RETURNING id", (_now(), e["id"]), one=True)
            if not got: continue  # someone else took it
            fn = getattr(self, "_on_" + e["kind"].replace(".", "_"), None)
            try:
                res = fn(e, _j(e["payload"], {}) or {}) if fn else {"note": "no handler: recorded"}
                self.db.q("UPDATE io_events SET status='done', result=?, error=NULL, done=?, updated=? WHERE id=?",
                          (json.dumps(res) if res is not None else None, _now(), _now(), e["id"]))
            except Busy:  # D4.3: the handler's lease is held elsewhere for a moment: again shortly, without using up an attempt
                self.db.q("UPDATE io_events SET status='pending', next_at=?, updated=? WHERE id=?", (_now() + BUSY_WAIT, _now(), e["id"]))
            except Exception as ex:  # noqa: BLE001 - a handler's failure is the event's, never the loop's
                a = (e["attempts"] or 0) + 1
                dead = a >= MAX_ATTEMPTS
                self.db.q("UPDATE io_events SET status=?, attempts=?, error=?, next_at=?, updated=? WHERE id=?",
                          ("dead" if dead else "pending", a, _clip(ex, 400), _now() + BACKOFF[min(a - 1, len(BACKOFF) - 1)], _now(), e["id"]))
                if dead: self.audit(e["owner_id"], "Orchestrator", "event.dead_letter", f"event:{e['id']}", f"{e['kind']}: {ex}", e["corr"])
            n += 1
        return n

    def retry_event(self, me, eid):
        self._gate(me)
        e = self.db.q("SELECT * FROM io_events WHERE id=? AND owner_id=?", (eid, me["id"]), one=True)
        if not e: raise HTTPException(404, "No such event of yours.")
        if e["status"] not in ("dead", "pending"): raise HTTPException(409, f"It's {e['status']}.")
        self.db.q("UPDATE io_events SET status='pending', attempts=0, next_at=?, updated=? WHERE id=?", (_now(), _now(), eid))
        self.audit(me["id"], me["username"], "event.retried", f"event:{eid}", e["kind"], e["corr"])
        self.process()
        return self.db.q("SELECT id, kind, status, attempts, error, result FROM io_events WHERE id=?", (eid,), one=True)

    # ---------- handlers ----------
    def _on_mission_effect(self, e, p):
        """D4.3: a persistent mission's cycle effect, applied by the handler Mission Control registered (missions.py). Without one
        (Mission Control off on this server) it raises, so the effect waits, retries and dead-letters instead of passing unapplied."""
        if EFFECTS is None: raise RuntimeError("Mission Control isn't running on this server: the effect waits")
        return EFFECTS(e, p)

    def _on_mission_finished(self, e, p):
        """Execution → Knowledge and Evaluation: the mission's verdict on every run correlated to it, and its lessons."""
        mid = int(e["corr"].split(":")[1])
        m = self.db.q("SELECT id, user_id, title, status, outcome, error, stage FROM mx_missions WHERE id=?", (mid,), one=True)
        if not m: return {"note": "mission gone"}
        r = self.db.q("SELECT score FROM ac_runs WHERE ref=? AND score IS NOT NULL ORDER BY id DESC LIMIT 1", (e["corr"],), one=True)
        scored = 0
        if r:
            scored = self.db.q("""UPDATE ac_runs SET score=? WHERE corr=? AND ref!=? AND score IS NULL AND status='done' RETURNING id, system, kind, ref""",
                               (r["score"], e["corr"], e["corr"])) or []
            for x in scored:
                self.db.q("""INSERT INTO io_evals (run_id, owner_id, system, kind, ref, corr, state, reason, source, score, ts, basis) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                             ON CONFLICT(run_id) DO UPDATE SET state='scored', reason=excluded.reason, source=excluded.source, score=excluded.score, ts=excluded.ts,
                             basis=excluded.basis""",
                          (x["id"], e["owner_id"], x["system"], x["kind"], x["ref"], e["corr"], "scored", "", f"Mission Control's independent check of {e['corr']}", r["score"], _now(),
                           "model_judged"))
            scored = len(scored)
        if not self._has("mx_lessons"): raise RuntimeError("Mission lessons (mx_lessons) aren't there: the knowledge handoff can't happen")
        # a promoted trial's lesson is written while the mission runs: it isn't the mission's own handoff
        lessons = self.db.q("SELECT COUNT(*) n FROM mx_lessons WHERE mission_id=? AND COALESCE(outcome, '') NOT IN (?, ?, ?)",
                            (mid, LESSON_TRIAL, LESSON_TRIAL_WITHDRAWN, LESSON_BENCH), one=True)["n"]
        res = {"runs_scored": scored, "lessons": lessons, "outcome": m["outcome"]}
        if self._has("ac_limits"):  # its hard limit has done its job
            self.db.q("DELETE FROM ac_limits WHERE owner_id=? AND scope='mission' AND key=? AND origin='mission budget'", (e["owner_id"], e["corr"]))
            # no cache to drop: agent_core reads the limits on every check (G5-2 Blocker B), on every replica
        if not lessons and (m["outcome"] == "failed" or m["status"] == "failed"):
            # recovery: a mission that failed for good before missions._dead kept its failure as a lesson; keep it now
            self.db.q("INSERT INTO mx_lessons (user_id, mission_id, kind, text, outcome, created) VALUES (?,?,?,?,?,?)",
                      (m["user_id"], mid, "failed", _clip(f"Mission “{m['title']}” failed for good at {m['stage'] or 'its start'}: {m['error'] or 'no error recorded'}", 400), "failed", _now()))
            self.audit(e["owner_id"], "Orchestrator", "knowledge.lesson_kept", e["corr"], "a failed mission had kept no lesson", e["corr"])
            res.update(lessons=1, repaired=True)
        elif not lessons:
            res["warning"] = "Delivered without a lesson: its report listed none"
        return res

    def _on_agent_signal(self, e, p):
        """Evaluation → Adaptive: an open proposal for the agent, unless one is open already."""
        if self.ev is None: raise RuntimeError("The Evolution Engine isn't running on this server")
        key, uid = p["agent"], e["owner_id"]
        open_ = self.db.q("""SELECT id FROM ev_proposals WHERE user_id=? AND target_key=? AND status IN ('proposed','testing','verified')""", (uid, key), one=True)
        if open_: return {"proposal": open_["id"], "note": "a proposal for it is open already"}
        me = self.db.q("SELECT * FROM users WHERE id=?", (uid,), one=True)
        if not me: return {"note": "owner gone"}
        from . import evolution as evo
        if self._has("ac_agents") and not self.db.q("SELECT 1 FROM ac_agents WHERE key=?", (key,), one=True) and agent_core.get() is not None:
            agent_core.get().sync(force=True)  # the registry mirrors every few minutes: an agent scored before its first sync isn't in it yet
        pol = self.ev.policy(uid)
        bench = self.db.q("SELECT id FROM ev_benchmarks WHERE user_id=? AND target_key=? ORDER BY id DESC LIMIT 1", (uid, key), one=True)
        why = "; ".join(p.get("evidence") or [])
        auto = pol["mode"] in ("experiment", "auto") and self.ev._spent_today(uid) < (pol["daily_tokens"] or 0)
        if key.startswith("hub:") and auto and bench:
            d = self.ev.draft(me, evo.DraftIn(target_key=key, benchmark_id=bench["id"], focus=why[:400]))  # the engine's tick runs its experiment
            self.audit(uid, "Orchestrator", "signal.drafted", f"proposal:{d['id']}", f"{p.get('name') or key}: {why}", e["corr"])
            return {"proposal": d["id"], "drafted": True}
        d = self.ev.propose(me, evo.ProposalIn(target_key=key, target_kind="agent", title=f"Fix: {_clip(p.get('top') or 'repeated failures', 120)}",
                                               hypothesis=f"Diagnosed from the run ledger: {why}"[:1500],
                                               change=(f"Recovery for its most common failure ({p['cls']}): {RECOVERY.get(p['cls'], RECOVERY['task'])[1]}" if p.get("cls") else
                                                       f"Its scored work is low ({p.get('top')}): read its lowest-scoring runs in Agent Operations, change its instructions, "
                                                       "skills or model, and measure the change on a benchmark before adopting it."),
                                               risk="config", benchmark_id=bench["id"] if bench else None), origin="diagnosis", signal=p)
        self.audit(uid, "Orchestrator", "signal.proposed", f"proposal:{d['id']}", f"{p.get('name') or key}: {why}", e["corr"])
        res = {"proposal": d["id"], "drafted": False}
        if auto:  # the policy lets the engine experiment: it approves the experiment as you would (promotion still waits for its own rule)
            try: res["experiment"] = self.approve_experiment(me, d["id"], by="Evolution Engine (policy)").get("routed")
            except HTTPException as ex:
                res["held"] = ex.detail
                self.audit(uid, "Evolution Engine (policy)", "experiment.held", f"proposal:{d['id']}", ex.detail, e["corr"])
        return res

    def approve_experiment(self, me, pid, by=None):
        """A proposal's experiment, approved (by you, or by=the policy), in the system that can measure its target: the Evolution
        Lab for your own agents (benchmark and candidate drafted when missing), the Workforce's own trial for a Workforce agent.
        Competition team agents are measured by an Upgrade sprint; other targets on their own page. Nothing is promoted here."""
        self._gate(me)
        p = self.db.q("SELECT * FROM ev_proposals WHERE id=? AND user_id=?", (pid, me["id"]), one=True) if self._has("ev_proposals") else None
        if not p: raise HTTPException(404, "No such proposal of yours.")
        if p["origin"] == "mission" and p["target_kind"] == "team":  # L5.5: a gap a mission measured is answered, never tested itself
            raise HTTPException(409, "This proposal records a gap a mission measured. Answer it with a proposal for one of the team's agents; that answer is what gets tested.")
        key = p["target_key"] or ""
        if key.startswith("hub:"):
            if self.ev is None: raise HTTPException(503, "The Evolution Engine isn't running on this server.")
            return {"routed": "evolution", "proposal": self.ev.approve(me, pid, by=by)}
        if key.startswith("workforce:") and key[10:].isdigit():
            wf = self.systems.get("workforce")
            if wf is None or not self._has("wf_improvements"): raise HTTPException(503, "The Workforce isn't running on this server.")
            imp = self.db.q("""SELECT id FROM wf_improvements WHERE user_id=? AND agent_id=? AND status IN ('proposed','not_better','failed') ORDER BY id DESC LIMIT 1""",
                            (me["id"], int(key[10:])), one=True)
            if not imp:
                raise HTTPException(409, "The Workforce measures a change on the failed assignment it came from, and none is proposed for this agent yet: its "
                                         "Improvement Engineer proposes one after the agent's next failed assignment (Workforce → Improvements).")
            from .workforce import TestIn
            wf.test(me, imp["id"], TestIn(trials=1))
            self.db.q("UPDATE ev_proposals SET note=?, updated=? WHERE id=?", (f"Trial running in the Workforce: improvement #{imp['id']}. Promote it there if it measures better.", _now(), pid))
            self.audit(me["id"], by or me["username"], "experiment.approved", f"proposal:{pid}", f"Workforce trial of improvement #{imp['id']}", key)
            return {"routed": "workforce", "improvement": imp["id"]}
        if key.startswith("teams:"):
            raise HTTPException(409, "A Competition team agent is measured by an Upgrade sprint's blind held-out exam: start one on Competition teams → Upgrade.")
        raise HTTPException(409, "This target is measured on its own page: record its evidence here once you have it.")

    def _on_proposal_promoted(self, e, p):
        """Adaptive → Monitor: the agent's average on scored runs in the 14 days before the promotion is the bar."""
        pid = int(e["ref"].split(":")[1])
        pr = self.db.q("SELECT id, user_id, target_key, promoted FROM ev_proposals WHERE id=?", (pid,), one=True)
        if not pr: return {"note": "proposal gone"}
        b = self.db.q("""SELECT AVG(score) a, COUNT(score) n FROM ac_runs WHERE owner_id=? AND agent_key=? AND score IS NOT NULL AND started<? AND started>=?
                         AND kind NOT IN ('experiment','cases','draft')""", (pr["user_id"], pr["target_key"], pr["promoted"], pr["promoted"] - 14 * 86400), one=True)
        basis, avg, n = "scores", b["a"], b["n"] or 0
        if not n:  # nothing scored before it (an agent used in chats): your thumbs in its chats are the measure, when there are enough
            avg, n = self._ratings(pr["user_id"], pr["target_key"], pr["promoted"] - 30 * 86400, pr["promoted"])
            basis = "ratings"
        none = n < MONITOR_N
        self.db.q("""INSERT OR IGNORE INTO io_monitor (proposal_id, owner_id, target_key, promoted, base_avg, base_n, state, checked, note, basis)
                     VALUES (?,?,?,?,?,?,?,?,?,?)""", (pid, pr["user_id"], pr["target_key"], pr["promoted"], avg, n, "no_baseline" if none else "watching", _now(),
                                                       "Neither scored runs nor enough rated chat answers before the promotion: only its experiment stands for it" if none else None,
                                                       basis))
        return {"base_avg": avg, "base_n": n, "basis": basis}

    def _ratings(self, uid, key, a, b=None):
        """(share of rated answers with a thumbs-up × 100, how many were rated) in your chats with your agent `key` (hub:N) that
        started between a and b: the measure for an agent whose work nobody scores."""
        if not (key or "").startswith("hub:") or not self._has("agent_conversations"): return None, 0
        up = down = 0
        for c in self.db.q(f"SELECT messages FROM agent_conversations WHERE user_id=? AND agent=? AND created>=?{' AND created<?' if b else ''}",
                           (uid, f"custom:{key[4:]}", a, *((b,) if b else ()))):
            for m in _j(c["messages"], []) or []:
                r = (m.get("meta") or {}).get("rating") if isinstance(m, dict) else None
                up += r == 1; down += r == -1
        n = up + down
        return (round(100 * up / n, 1) if n else None), n

    def _on_proposal_regressed(self, e, p):
        pid = int(e["ref"].split(":")[1])
        pr = self.db.q("SELECT * FROM ev_proposals WHERE id=?", (pid,), one=True)
        if not pr or pr["status"] != "promoted": return {"note": "not promoted any more"}
        pol = self.ev.policy(pr["user_id"]) if self.ev else {"mode": "recommend"}
        if pol["mode"] == "auto" and pr["risk"] == "config" and (pr["target_key"] or "").startswith("hub:"):
            me = self.db.q("SELECT * FROM users WHERE id=?", (pr["user_id"],), one=True)
            self.ev.rollback(me, pid, by="Evolution Engine (monitor)")
            self.db.q("UPDATE io_monitor SET state='rolled_back', note=? WHERE proposal_id=?", (p.get("why"), pid))
            self.audit(pr["user_id"], "Orchestrator", "monitor.rolled_back", f"proposal:{pid}", p.get("why") or "", e["corr"])
            return {"rolled_back": True}
        self.db.q("UPDATE io_monitor SET state='regressed', note=? WHERE proposal_id=?", (p.get("why"), pid))
        self.audit(pr["user_id"], "Orchestrator", "monitor.held", f"proposal:{pid}", (p.get("why") or "") + " · waits for you: roll it back in the Evolution Lab", e["corr"])
        return {"rolled_back": False, "waits": "human"}

    # ------------------------------------------------------------------ the round
    def tick(self):
        with self.lock:
            out = {}
            for name, fn in (("stale", self.close_stale), ("relink", self.relink), ("evaluate", self.evaluate), ("diagnose", self.diagnose), ("sandbox", self.diagnose_sandbox),
                             ("risks", self.risk_feeds), ("missions", self.observe_missions), ("signals", self.observe_signals), ("promotions", self.observe_promotions),
                             ("handoffs", self.observe_handoffs), ("outcomes", self.settle_outcomes),
                             ("monitor", self.monitor), ("events", self.process), ("retrieval", self.retrieval_due), ("prune", self.prune)):
                if self.stopped.is_set(): break
                try: out[name] = fn()
                except Exception as e:  # noqa: BLE001 - one step's failure never stops the others
                    log.warning("orchestrator %s: %s", name, e)
                    out[name] = f"error: {e}"
                    self.last_error = f"{name}: {e}"
            self.last_tick = _now()
            return out

    def start(self):
        threading.Thread(target=self._loop, name="g5-orchestrator", daemon=True).start()

    def stop(self): self.stopped.set()

    def _loop(self):
        if self.stopped.wait(20): return
        while not self.stopped.is_set():
            try: self.tick()
            except Exception:  # noqa: BLE001
                log.exception("orchestrator tick")
            if self.stopped.wait(TICK): return

    # ---------- terminal outcomes ----------
    def close_stale(self):
        """Runs still 'running' STALE_H hours on: their thread died without end() (a crash, not a restart). Lost, with why. Not the
        Workflow's (host runs that go on through restarts) nor Long tasks' (their segments can be long; infiagent closes its own)."""
        if not self._has("ac_runs"): return 0
        rows = self.db.q("""UPDATE ac_runs SET status='lost', finished=?, error=COALESCE(error, ?) WHERE status='running' AND started<?
                            AND system NOT IN ('workflow','longtask') AND kind NOT LIKE 'upgrade:%' RETURNING id, owner_id, corr""",
                         (_now(), f"No end was recorded within {STALE_H} hours: the process that ran it stopped without closing it.", _now() - STALE_H * 3600)) or []
        for r in rows: self.audit(r["owner_id"], "Orchestrator", "run.closed_stale", f"run:{r['id']}", f"open over {STALE_H} h", r["corr"])
        return len(rows)

    def relink(self):
        """Runs a child engine began before its mission linked it (a race of a few seconds) join the mission's correlation id."""
        if "corr" not in self._cols("ac_runs"): return 0
        n = 0
        for l in self.db.q("SELECT ref, corr FROM io_links WHERE created>?", (_now() - WINDOW,)):
            n += len(self.db.q("UPDATE ac_runs SET corr=? WHERE corr=? RETURNING id", (l["corr"], l["ref"])) or [])
        return n

    def prune(self):
        """Old rows go as the ledger's do: events, evaluations, diagnoses and links after KEEP_DAYS, the audit after AUDIT_DAYS,
        retrieval runs past the newest 60 per owner. Datasets stay (evidence names them), as do watches of promoted changes."""
        if self._last_prune and _now() - self._last_prune < 3600: return 0
        self._last_prune, old, n = _now(), _now() - KEEP_DAYS * 86400, 0
        # D4.3 (F.1): a persistent mission's cycles and effects are its history: never pruned
        for sql, args in (("DELETE FROM io_events WHERE created<? AND status IN ('done','dead') AND kind NOT IN ('mission.cycle','mission.effect') RETURNING id", (old,)),
                          ("DELETE FROM io_evals WHERE ts<? RETURNING run_id", (old,)),
                          ("DELETE FROM io_diag WHERE ts<? RETURNING run_id", (old,)),
                          ("DELETE FROM io_sbx WHERE ts<? RETURNING sbx_id", (old,)),
                          ("DELETE FROM io_links WHERE created<? RETURNING ref", (old,)),
                          ("DELETE FROM io_audit WHERE ts<? RETURNING id", (_now() - AUDIT_DAYS * 86400,)),
                          ("""DELETE FROM io_bench_runs WHERE id IN (SELECT id FROM (SELECT id, ROW_NUMBER() OVER (PARTITION BY owner_id ORDER BY id DESC) k
                              FROM io_bench_runs) WHERE k>60) RETURNING id""", ())):
            n += len(self.db.q(sql, args) or [])
        return n

    # ---------- evaluation coverage ----------
    def _verdict(self, r):
        """(score, source) from the run's own system's records, or None."""
        p, _, rest = (r["ref"] or "").partition(":")
        if p == "wf" and rest.isdigit() and self._has("wf_runs"):
            x = self.db.q("""SELECT w.score, m.score ms, m.status mst FROM wf_runs w LEFT JOIN wf_missions m ON m.id=w.mission_id WHERE w.id=?""", (int(rest),), one=True)
            if x and x["score"] is not None: return x["score"], "Workforce reviewer's score of this run"
            if x and x["ms"] is not None and x["mst"] in ("done", "delivered", "finished"): return x["ms"], "Workforce mission verdict"
        if p == "sw" and rest.isdigit() and self._has("sw_runs"):
            x = self.db.q("""SELECT r.score, c.score cs FROM sw_runs r LEFT JOIN sw_contracts c ON c.id=r.contract_id WHERE r.id=?""", (int(rest),), one=True)
            if x and x["score"] is not None: return x["score"], "Swarm evaluator's score of this run"
            if x and x["cs"] is not None: return x["cs"], "Swarm contract check"
        if p == "mx" and r["kind"] in ("discover", "execute"):  # the verifier scores understand and plan; the brief and the deliverable earned it too
            x = self.db.q("SELECT score FROM ac_runs WHERE ref=? AND score IS NOT NULL LIMIT 1", (r["ref"],), one=True)
            if x: return x["score"], f"Mission Control's independent check of {r['ref']}"
        if r["corr"] and r["corr"] != r["ref"] and r["corr"].startswith("mx:"):
            x = self.db.q("SELECT score FROM ac_runs WHERE ref=? AND score IS NOT NULL LIMIT 1", (r["corr"],), one=True)
            if x: return x["score"], f"Mission Control's independent check of {r['corr']}"
        return None

    def _basis(self, system, kind, ref, state, corr=None, source="", score=None):
        """basis_for, plus the one case it can't settle without the ledger: a scored board run under a mission. It is model-judged
        only when that mission's independent check holds this very score (the check scored the mission's runs with it); a review's
        number under a mission, and any score under a persistent mission (which has no model check), stays derived."""
        b = basis_for(system, kind, ref, state, corr, source)
        if b == "derived" and state == "scored" and score is not None and corr and corr != ref and str(corr).startswith("mx:"):
            E = evaluator_for(system, kind, ref)
            if E and len(E) > 5 and E[5] == "reviewed":
                x = self.db.q("SELECT score FROM ac_runs WHERE ref=? AND score IS NOT NULL ORDER BY id DESC LIMIT 1", (corr,), one=True)
                if x and abs(x["score"] - score) < 1e-9: return "model_judged"
        return b

    def _derived(self, ev, r, now):
        """A verdict its system keeps elsewhere: (score, source), ("exclude", why), ("reviewed", verdict) for a board task (no number),
        or None while it can still come."""
        p, _, rest = (r["ref"] or "").partition(":")
        q, has = self.db.q, self._has
        if ev == "mission":
            x = q("SELECT score FROM ac_runs WHERE ref=? AND score IS NOT NULL LIMIT 1", (r["ref"],), one=True)
            return (x["score"], f"Mission Control's independent check of {r['ref']}") if x else None
        if ev == "team_task" and rest.isdigit() and has("mw_runs") and has("mw_tasks"):
            t = q("SELECT t.id, t.status FROM mw_runs w JOIN mw_tasks t ON t.id=w.task_id WHERE w.id=?", (int(rest),), one=True)
            if not t: return "exclude", "Its task was deleted before a verdict"
            # G5-5 L5.1 (IC-11 change 1 and open point (a)): a review is a verdict, not a measurement. The run is recorded as reviewed,
            # with the verdict as its reason and no number: neither the 100 of "its task is done" nor the 30 and 10 of the other verdicts
            if q("SELECT 1 FROM mw_runs WHERE task_id=? AND kind='task' AND id>? AND status!='cancelled' LIMIT 1", (t["id"], int(rest)), one=True):
                return "reviewed", REVIEWED["sent_back"]
            if t["status"] == "done": return "reviewed", REVIEWED["approved"]
            if t["status"] == "review" and q("SELECT 1 FROM mw_runs WHERE task_id=? AND kind='review' AND id>? AND status='done' LIMIT 1", (t["id"], int(rest)), one=True):
                return "reviewed", REVIEWED["rejected"]  # its reviewer neither approved it nor sent it back again: it waits for a person
            return None
        if ev == "team_plan" and rest.isdigit() and has("mw_tasks"):
            ts = q("SELECT status FROM mw_tasks WHERE origin=?", (f"plan:{rest}",))
            if not ts: return "exclude", "The plan put no task on the board: nothing to judge it by"
            done = sum(1 for t in ts if t["status"] == "done")
            if done == len(ts) or (r["finished"] or r["started"] or 0) < now - HUMAN_GRACE:
                return round(100 * done / len(ts)), f"{done} of the {len(ts)} tasks it put on the board were delivered"
            return None
        if ev == "control_task" and rest[1:].isdigit() and has("ctl_tasks"):
            t = q("SELECT status FROM ctl_tasks WHERE id=?", (int(rest[1:]),), one=True)
            if not t: return "exclude", "Its task was deleted before a decision"
            if q("SELECT 1 FROM ac_runs WHERE ref=? AND id>? LIMIT 1", (r["ref"], r["id"]), one=True): return 30, "Sent back for another try (a later run of the same task)"
            if t["status"] == "done": return 100, "You accepted its result"
            if t["status"] in ("cancelled", "declined"): return "exclude", "The task was cancelled before you decided on the result"
            return None
        if ev == "intel" and r["ref"].startswith("ctl:mi:") and has("ctl_tasks") and "origin" in self._cols("ctl_tasks") and "mission" in self._cols("ctl_tasks"):
            ts = q("""SELECT status FROM ctl_tasks WHERE user_id=? AND origin='intelligence' AND mission=? AND created>=? AND created<=?""",
                   (r["owner_id"], r["ref"][7:], (r["started"] or 0) - 5, (r["finished"] or r["started"] or 0) + 300))
            if not ts: return "exclude", "It proposed no task: nothing for you to accept or decline"
            decided = [t for t in ts if t["status"] != "proposed"]
            if not decided or (len(decided) < len(ts) and (r["finished"] or r["started"] or 0) > now - HUMAN_GRACE): return None
            ok = sum(1 for t in decided if t["status"] not in ("declined", "skipped", "cancelled"))
            return round(100 * ok / len(decided)), f"You approved {ok} of the {len(decided)} tasks it proposed that you decided on"
        if ev == "company_task" and rest.isdigit() and has("co_artifacts") and has("co_evals"):
            x = q("""SELECT e.score FROM co_evals e JOIN co_artifacts a ON a.id=e.artifact_id WHERE a.task_id=? AND e.score IS NOT NULL ORDER BY e.id DESC LIMIT 1""",
                  (int(rest),), one=True)
            return (x["score"], "The company evaluator agent's score of its deliverable") if x else None
        if ev == "workflow_engineer" and has("mb_runs") and has("mb_tasks"):
            t = q("SELECT t.merged, t.status FROM mb_runs b JOIN mb_tasks t ON t.id=b.task_id WHERE b.run=?", (r["ref"][3:],), one=True)
            if t and t["merged"]: return 100, "Merged after an approving review and passing checks"
            return None
        return None

    def classify(self, r, now=None):
        """(state, reason, source, score) for one finished run: scored, reviewed (a board task's review verdict: no score), excluded
        or gap; None = wait (its verifier may still score it). Its evaluator comes from EVALUATORS; one with no entry is a gap that
        names the missing evaluator."""
        now = now or _now()
        E = evaluator_for(r["system"], r["kind"], r["ref"])
        if r["score"] is not None: return "scored", "", (E[4] if E and E[3] != "exclude" else "Its evaluator or verifier"), r["score"]
        if r["status"] in ("failed", "error", "lost"):
            k = fail_class(r["status"], r["error"])
            return "excluded", f"Failed: {FAIL_LABEL.get(k, k).lower()}. No output to score; its diagnosis says what to do", "", None
        if r["status"] in ("cancelled", "stopped"): return "excluded", "Stopped before it finished: nothing to score", "", None
        if not r["ref"]: return "excluded", "A chat or a one-off model call outside any run: the person rates it in the chat", "", None
        if E and E[3] == "exclude": return "excluded", E[4], "", None
        v = self._verdict(r) if not E or E[3] in ("own", "mission") else None
        if v is None and E and E[3] not in ("own", "none"):
            d = self._derived(E[3], r, now)
            if d and d[0] == "exclude": return "excluded", d[1], "", None
            if d and d[0] == "reviewed": return "reviewed", d[1], E[4], None
            v = d
        if v: return "scored", "", v[1], max(0.0, min(100.0, float(v[0])))
        label = agent_core.SYSTEMS.get(r["system"], r["system"])
        if not E: return "gap", f"No evaluator assigned to {label}'s '{r['kind']}' runs", "", None
        if E[3] == "none": return "gap", f"No evaluator: {E[4]}", "", None
        wait = HUMAN_GRACE if E[3] in HUMAN else GRACE
        if (r["finished"] or r["started"] or 0) > now - wait: return None
        return "gap", f"No verdict within {wait // 3600} hours from {E[4][0].lower() + E[4][1:]}", "", None

    def evaluate(self):
        """Classifies finished runs that have no row yet; re-checks gaps that have a score since."""
        if not self._has("ac_runs"): return 0
        now, n = _now(), 0
        cols = self._cols("ac_runs")
        corr = "r.corr" if "corr" in cols else "NULL AS corr"
        rows = self.db.q(f"""SELECT r.id, r.owner_id, r.system, r.kind, r.ref, {corr}, r.status, r.error, r.score, r.started, r.finished FROM ac_runs r
                             LEFT JOIN io_evals e ON e.run_id=r.id WHERE r.status!='running' AND r.started>? AND e.run_id IS NULL ORDER BY r.id LIMIT ?""",
                         (now - WINDOW, BATCH))
        for r in rows:
            c = self.classify(r, now)
            if not c: continue
            st, why, src, sc = c
            if st == "scored" and r["score"] is None and sc is not None:  # copied onto the ledger: the router learns from it too
                self.db.q("UPDATE ac_runs SET score=? WHERE id=? AND score IS NULL", (max(0.0, min(100.0, float(sc))), r["id"]))
            self.db.q("INSERT OR REPLACE INTO io_evals (run_id, owner_id, system, kind, ref, corr, state, reason, source, score, ts, basis) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      (r["id"], r["owner_id"], r["system"], r["kind"], r["ref"], r["corr"], st, why, src, sc, now, self._basis(r["system"], r["kind"], r["ref"], st, r["corr"], src, sc)))
            n += 1
        for r in self.db.q("""SELECT e.run_id FROM io_evals e JOIN ac_runs a ON a.id=e.run_id WHERE e.state='excluded' AND e.reason LIKE 'Failed:%'
                              AND a.status='done' LIMIT ?""", (BATCH,)):  # closed as lost, then its own end() came: classified again next round
            self.db.q("DELETE FROM io_evals WHERE run_id=?", (r["run_id"],)); self.db.q("DELETE FROM io_diag WHERE run_id=?", (r["run_id"],))
            n += 1
        for r in self.db.q("""SELECT e.run_id, a.score, e.system, e.kind, e.ref, e.corr FROM io_evals e JOIN ac_runs a ON a.id=e.run_id WHERE e.state='gap' AND a.score IS NOT NULL
                              LIMIT ?""", (BATCH,)):
            self.db.q("UPDATE io_evals SET state='scored', reason='', source='Its evaluator or verifier (later)', score=?, ts=?, basis=? WHERE run_id=?",
                      (r["score"], now, self._basis(r["system"], r["kind"], r["ref"], "scored", r["corr"], "", r["score"]), r["run_id"]))
            n += 1
        if not self._gaps_at or now - self._gaps_at >= GAP_RECHECK:  # a decision made after the deadline (an accept, a merge) still counts
            self._gaps_at = now
            for r in self.db.q(f"""SELECT r.id, r.owner_id, r.system, r.kind, r.ref, {corr}, r.status, r.error, r.score, r.started, r.finished FROM io_evals e
                                   JOIN ac_runs r ON r.id=e.run_id WHERE e.state='gap' AND r.started>? ORDER BY e.ts LIMIT ?""", (now - WINDOW, BATCH)):
                c = self.classify(r, now)
                if not c or c[0] == "gap":
                    if c: self.db.q("UPDATE io_evals SET reason=?, ts=? WHERE run_id=?", (c[1], now, r["id"]))
                    continue
                st, why, src, sc = c
                if st == "scored" and sc is not None: self.db.q("UPDATE ac_runs SET score=? WHERE id=? AND score IS NULL", (sc, r["id"]))
                self.db.q("UPDATE io_evals SET state=?, reason=?, source=?, score=?, ts=?, basis=? WHERE run_id=?",
                          (st, why, src, sc, now, self._basis(r["system"], r["kind"], r["ref"], st, r["corr"], src, sc), r["id"]))
                n += 1
            # a run its reviewer rejected waits for a person: their approval or their sending it back is the verdict the row then keeps
            for r in self.db.q(f"""SELECT r.id, r.owner_id, r.system, r.kind, r.ref, {corr}, r.status, r.error, r.score, r.started, r.finished FROM io_evals e
                                   JOIN ac_runs r ON r.id=e.run_id WHERE e.state='reviewed' AND e.reason=? AND r.started>? ORDER BY e.ts LIMIT ?""",
                               (REVIEWED["rejected"], now - WINDOW, BATCH)):
                c = self.classify(r, now)
                if c and c[0] == "reviewed" and c[1] != REVIEWED["rejected"]:
                    self.db.q("UPDATE io_evals SET reason=?, ts=? WHERE run_id=?", (c[1], now, r["id"])); n += 1
        return n

    def coverage(self, uid, since):
        """Finished runs since `since`: scored, reviewed (a board task's review verdict: no score, and not a gap), excluded (with
        reasons), gaps (by system and kind) and still waiting. Scored runs are also counted by what their score rests on (BASES)."""
        if not self._has("ac_runs"): return None
        fin = self.db.q("SELECT COUNT(*) n FROM ac_runs WHERE owner_id=? AND started>? AND status!='running'", (uid, since), one=True)["n"]
        st = {r["state"]: r["n"] for r in self.db.q("""SELECT e.state, COUNT(*) n FROM io_evals e JOIN ac_runs a ON a.id=e.run_id
                                                       WHERE a.owner_id=? AND a.started>? GROUP BY e.state""", (uid, since))}
        reasons = [dict(r) for r in self.db.q("""SELECT e.reason, COUNT(*) n FROM io_evals e JOIN ac_runs a ON a.id=e.run_id WHERE a.owner_id=? AND a.started>?
                                                  AND e.state='excluded' GROUP BY e.reason ORDER BY n DESC LIMIT 8""", (uid, since))]
        gaps = [dict(r, label=agent_core.SYSTEMS.get(r["system"], r["system"])) for r in self.db.q(
            """SELECT e.system, e.kind, e.reason, COUNT(*) n FROM io_evals e JOIN ac_runs a ON a.id=e.run_id WHERE a.owner_id=? AND a.started>?
               AND e.state='gap' GROUP BY e.system, e.kind ORDER BY n DESC LIMIT 10""", (uid, since))]
        src = {}
        for r in self.db.q("""SELECT e.source, COUNT(*) n FROM io_evals e JOIN ac_runs a ON a.id=e.run_id WHERE a.owner_id=? AND a.started>?
                              AND e.state='scored' GROUP BY e.source""", (uid, since)):
            k = re.sub(r" of mx:\d+$", "", r["source"] or "")  # one line for every mission's independent check
            src[k] = src.get(k, 0) + r["n"]
        sources = [{"source": k, "n": v} for k, v in sorted(src.items(), key=lambda x: -x[1])[:8]]
        scored, excl, gap, rev = st.get("scored", 0), st.get("excluded", 0), st.get("gap", 0), st.get("reviewed", 0)
        waiting = max(0, fin - scored - excl - gap - rev)
        scoreable = scored + gap  # a reviewed run isn't scoreable: its verdict is kept, and nothing is due
        kinds = {r["basis"]: r["n"] for r in self.db.q("""SELECT e.basis, COUNT(*) n FROM io_evals e JOIN ac_runs a ON a.id=e.run_id WHERE a.owner_id=? AND a.started>?
                                                          AND e.state='scored' AND e.basis IS NOT NULL GROUP BY e.basis""", (uid, since))}
        for r in self.db.q("""SELECT e.system, e.kind, e.ref, e.corr, e.source, e.score FROM io_evals e JOIN ac_runs a ON a.id=e.run_id WHERE a.owner_id=? AND a.started>?
                              AND e.state='scored' AND e.basis IS NULL""", (uid, since)):  # rows from before L5.1: read, never rewritten
            b = self._basis(r["system"], r["kind"], r["ref"], "scored", r["corr"], r["source"], r["score"])
            kinds[b] = kinds.get(b, 0) + 1
        return {"finished": fin, "scored": scored, "reviewed": rev, "excluded": excl, "gap": gap, "waiting": waiting, "scoreable": scoreable,
                "scored_by": {b: kinds.get(b, 0) for b in BASES[:2]}, "measured": 0,  # no run score is measured (D-005): missions.measured has those
                "accounted_pct": round(100 * (scored + excl + rev) / fin) if fin else None,
                "scored_pct": round(100 * scored / scoreable) if scoreable else None, "of_finished_pct": round(100 * scored / fin) if fin else None,
                "target": COVERAGE_TARGET, "reasons": reasons, "gaps": gaps, "sources": sources, "outcomes": self.outcomes(uid, since)}

    def outcomes(self, uid, since):
        """Every finished run's final outcome, one bucket each so they add up to the finished runs: success (scored GOOD+), partial,
        failure (the work's own: failed as the task itself or over its cap, OWN_FAULT, or scored under LOW), environment (failed or
        lost for a reason outside the work: a restart, quota, budget, provider, rate limit, timeout, sandbox or tool), stopped
        (cancelled or stopped by a person), reviewed (a board task's review verdict, kept without a score: G5-5 L5.1), excluded (never
        scored, for its evaluator's reason) and unsettled (no verdict yet, or a failure not classified yet). Then the recalled experiences the learning system ranks by: settled on success, partial,
        failure, excluded, or still open."""
        from .intel_layers import GOOD, LOW
        diag = self._has("io_diag")
        rows = {r["o"]: r["n"] for r in self.db.q(f"""SELECT CASE WHEN a.status IN ('failed','error','lost') THEN
                     {"CASE WHEN d.run_id IS NULL THEN 'unsettled' WHEN COALESCE(d.canon, d.cls) IN (" + ",".join(f"'{c}'" for c in OWN_CANON) + ") THEN 'failure' ELSE 'environment' END" if diag else "'failure'"}
                     WHEN a.status IN ('cancelled','stopped') THEN 'stopped' WHEN a.score IS NOT NULL AND a.score<{LOW} THEN 'failure'
                     WHEN a.score>={GOOD} THEN 'success' WHEN a.score IS NOT NULL THEN 'partial' WHEN e.state='reviewed' THEN 'reviewed' WHEN e.state='excluded' THEN 'excluded' ELSE 'unsettled' END o,
                     COUNT(*) n FROM ac_runs a LEFT JOIN io_evals e ON e.run_id=a.id {"LEFT JOIN io_diag d ON d.run_id=a.id" if diag else ""}
                     WHERE a.owner_id=? AND a.started>? AND a.status!='running' GROUP BY o""", (uid, since))}
        out = {"runs": {k: rows.get(k, 0) for k in ("success", "partial", "failure", "environment", "stopped", "reviewed", "excluded", "unsettled")}, "good": GOOD, "low": LOW}
        if self._has("ex_uses"):
            r = {x["o"] or "open": x["n"] for x in self.db.q("SELECT outcome o, COUNT(*) n FROM ex_uses WHERE user_id=? AND ts>? GROUP BY outcome", (uid, since))}
            out["recalls"] = {k: r.get(k, 0) for k in ("success", "partial", "failure", "excluded", "open")}
        return out

    def settle_outcomes(self):
        """Recalled experiences (ex_uses) still open though the work that recalled them has a final record: settled from that
        record, so the recall ranking learns from failures and stops, not only from the successes their systems reported.
        mx:N a mission, wf:N a Workforce mission, mw:N a team task (done: you or its reviewer approved it); a record that's gone, a
        cancelled one or one that ended without a verdict settles as excluded (no evidence either way). Work still going stays open."""
        if not self._has("ex_uses"): return 0
        from .experience import OUTCOMES
        n = 0
        for c in self.db.q("""SELECT user_id, context FROM ex_uses WHERE outcome IS NULL AND context IS NOT NULL AND ts<? GROUP BY user_id, context
                              ORDER BY MIN(ts) LIMIT ?""", (_now() - SETTLE_AFTER, BATCH)):
            kind, _, rid = (c["context"] or "").partition(":")
            if not rid.isdigit(): continue
            o = None
            if kind == "mx" and self._has("mx_missions"):
                r = self.db.q("SELECT status, outcome FROM mx_missions WHERE id=? AND user_id=?", (int(rid), c["user_id"]), one=True)
                o = ("excluded" if not r else "failure" if r["status"] == "failed" or r["outcome"] == "failed" else OUTCOMES.get(r["outcome"] or "")
                     or ("excluded" if r["status"] in ("cancelled", "delivered", "done") else None))
            elif kind == "wf" and self._has("wf_missions"):
                r = self.db.q("SELECT status, verdict FROM wf_missions WHERE id=? AND user_id=?", (int(rid), c["user_id"]), one=True)
                o = ("excluded" if not r else "failure" if r["status"] == "failed" else "excluded" if r["status"] == "cancelled"
                     else (OUTCOMES.get(r["verdict"] or "") or "excluded") if r["status"] == "done" else None)
            elif kind == "mw" and self._has("mw_tasks"):
                r = self.db.q("SELECT * FROM mw_tasks WHERE id=?", (int(rid),), one=True)
                # done: approved; hold 'failed': it gave up after its own failures (a row recalled before 11-11's hook, or by a
                # run that ended outside it); blocked waits on you and stays open
                o = "excluded" if not r else "success" if r["status"] == "done" else "failure" if r.get("hold") == "failed" else None
            if o:
                self.db.q("UPDATE ex_uses SET outcome=?, settled=? WHERE user_id=? AND context=? AND outcome IS NULL AND ts<?",
                          (o, _now(), c["user_id"], c["context"], _now() - SETTLE_AFTER))
                n += 1
        return n

    # ---------- failure diagnosis ----------
    def diagnose(self):
        if not self._has("ac_runs"): return 0
        cols = self._cols("ac_runs")
        corr = "r.corr" if "corr" in cols else "NULL AS corr"
        rows = self.db.q(f"""SELECT r.id, r.owner_id, r.system, r.ref, {corr}, r.agent_key, r.status, r.error FROM ac_runs r LEFT JOIN io_diag d ON d.run_id=r.id
                             WHERE r.status IN ('failed','error','lost') AND r.started>? AND d.run_id IS NULL ORDER BY r.id LIMIT ?""", (_now() - WINDOW, BATCH))
        for r in rows:
            k = fail_class(r["status"], r["error"])
            ok, fix = RECOVERY.get(k, RECOVERY["task"])
            if k == "sandbox":
                _c, lbl, ok, fix = sbx_class("error", r["error"])
            canon = failure(r["status"], r["error"])["cls"]  # recorded beside the legacy class; decisions still use cls (G5 Phase 1)
            self.db.q("""INSERT OR REPLACE INTO io_diag (run_id, owner_id, system, ref, corr, agent_key, cls, recoverable, recovery, evidence, ts, canon)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (r["id"], r["owner_id"], r["system"], r["ref"], r["corr"], r["agent_key"], k, int(ok), fix, _clip(r["error"] or FAIL_LABEL.get(k, k), 300), _now(), canon))
        # diagnoses made before io_diag.canon existed get their canonical class too, a batch per pass (G5-2, D-015 D1)
        old = self.db.q("""SELECT d.run_id, r.status, r.error FROM io_diag d JOIN ac_runs r ON r.id=d.run_id WHERE d.canon IS NULL LIMIT ?""", (BATCH,))
        for x in old: self.db.q("UPDATE io_diag SET canon=? WHERE run_id=?", (failure(x["status"], x["error"])["cls"], x["run_id"]))
        if not getattr(self, "_rediagnosed", False):
            self._rediagnosed = True
            self._rediagnose()
        return len(rows) + len(old)

    # ------------------------------------------------------------------ risk register (D-012, G5-2)
    RISK_FIELDS = ("mission", "task_ref", "layer", "source", "source_ref", "title", "description", "root_cause", "probability", "impact",
                   "severity", "priority", "critical", "detection", "countermeasure", "responsible", "approval")

    def risk_upsert(self, uid, rkey, evidence=None, **f):
        """Records a finding under its stable key: a new risk, or the same one seen again (last_seen, seen + 1, fresh evidence).
        A resolved risk that is found again reopens. An accepted one stays accepted (the Owner's decision holds until it resolves)."""
        now, ev = _now(), json.dumps(evidence or {}, default=str)[:4000]
        cur = self.db.q("SELECT id, status FROM io_risks WHERE owner_id=? AND rkey=?", (uid, rkey), one=True)
        vals = {k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in f.items() if k in self.RISK_FIELDS}
        if not cur:
            cols = ["owner_id", "rkey", "status", "evidence", "first_seen", "last_seen", "updated", *vals]
            self.db.q(f"INSERT INTO io_risks ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", (uid, rkey, "open", ev, now, now, now, *vals.values()))
            self.audit(uid, "Risk Intelligence", "risk.open", rkey, _clip(f.get("title") or "", 200), f.get("mission"))
            return self.db.q("SELECT id FROM io_risks WHERE owner_id=? AND rkey=?", (uid, rkey), one=True)["id"]
        reopen = cur["status"] == "resolved"
        sets = {**vals, "evidence": ev, "last_seen": now, "updated": now, **({"status": "open", "resolved_at": None, "verification": None} if reopen else {})}
        self.db.q(f"UPDATE io_risks SET {', '.join(f'{k}=?' for k in sets)}, seen=seen+1 WHERE id=?", (*sets.values(), cur["id"]))
        if reopen: self.audit(uid, "Risk Intelligence", "risk.reopen", rkey, _clip(f.get("title") or "", 200), f.get("mission"))
        return cur["id"]

    def risk_resolve(self, uid, rkey, verification):
        """The finding no longer holds: resolved, with the evidence that shows it (the probe that passed)."""
        cur = self.db.q("SELECT id, status FROM io_risks WHERE owner_id=? AND rkey=?", (uid, rkey), one=True)
        if not cur or cur["status"] == "resolved": return False
        now = _now()
        self.db.q("UPDATE io_risks SET status='resolved', resolved_at=?, verification=?, updated=? WHERE id=?",
                  (now, json.dumps(verification or {}, default=str)[:4000], now, cur["id"]))
        self.audit(uid, "Risk Intelligence", "risk.resolve", rkey, "verified", None)
        return True

    # ------------------------------------------------------------------ G5-3 R3.1: diagnosis feeds into the register (D-012)
    # Each feed groups its source's failures of the last RISK_WINDOW by scope and class. A group of RISK_RECUR or more opens (or
    # reopens) one row; a row stays open while its group has any failure in the window and resolves once it has none. A row is
    # written only when its fingerprint (count, newest id) changed, so re-running a feed changes nothing. A feed touches only its
    # own rows (source), never a readiness row. The register records; it never applies a change (T-9).
    def risk_feeds(self, now=None):
        """Every feed, at most once per RISK_FEED_EVERY seconds from tick (a test passes `now` and runs them at once)."""
        if now is None:
            if self._last_feeds and _now() - self._last_feeds < RISK_FEED_EVERY: return 0
            self._last_feeds = _now()
        if not self._has("io_risks"): return 0
        return (self.risk_feed_diag(now) + self.risk_feed_sbx(now) + self.risk_feed_hq(now) + self.risk_feed_budget(now)
                + self.risk_feed_ops(now) + self.risk_feed_campaign(now))

    # ---------- G5-3 R3.2: infrastructure issues and operational alerts. Each source keeps its own lifecycle: a row is open exactly
    # while its source item is (an alert's own status, an HQ issue's own resolution, a budget alert's period), so the register's
    # open count per source equals a direct count of the source. Severity follows the source's level; critical stays 0 (G3-7).
    def _src_fields(self, source, source_ref, mission, layer, title, description, root_cause, impact, severity, detection, countermeasure,
                    responsible):
        return dict(mission=mission, layer=layer, source=source, source_ref=source_ref, title=_clip(title, 200), description=_clip(description, 1500),
                    root_cause=_clip(root_cause, 600), probability="observed", impact=impact, severity=severity,
                    priority="high" if severity == "high" else "medium", critical=0, detection=detection, countermeasure=_clip(countermeasure, 600),
                    responsible=responsible, approval=RISK_SRC_APPROVAL)

    def risk_feed_hq(self, now=None):
        """hq_issues (Agent HQ's patrols of AXoR's services and infrastructure), open, warning or critical: organization rows
        (owner ORG_OWNER, mission NULL, layer execution). Snoozed issues are still open at the source, so they stay open here."""
        if not self._has("hq_issues"): return 0
        out = {}
        for i in self.db.q("SELECT * FROM hq_issues WHERE status='open' AND severity IN ('critical','warning')"):
            fp = f"{i['severity']}:{i['seen']}:{i['title']}"
            out[(ORG_OWNER, f"hq:{i['key']}")] = {"n": RISK_RECUR, "fp": fp, "evidence": {"issue": i["id"], "seen": i["seen"], "severity": i["severity"],
                "target": i["target"], "last_seen": i["last_seen"]}, "fields": self._src_fields(
                "hq", f"hq_issues:{i['id']}", None, "execution", f"{i['title']} ({i['team']})", i["detail"] or i["title"],
                i["cause"] or i["detail"] or i["title"], {"scope": "organization", "team": i["team"], "agent": i["agent"]},
                "high" if i["severity"] == "critical" else "medium",
                f"Agent HQ patrol by {i['agent']} ({i['team']}), seen {i['seen']}×", i["recommendation"] or "Agent HQ's lead investigates it; see its fixes.",
                f"Agent HQ {i['team']} lead")}
        return self._feed("hq", out, now or _now(), resolve_note=self._hq_resolution)

    def _hq_resolution(self, row):
        """The resolution of the very issue the row was fed from (source_ref hq_issues:<id>): a key has many issues over time."""
        _, _, iid = (row["source_ref"] or "").partition(":")
        r = self.db.q("SELECT id, status, resolution, verdict FROM hq_issues WHERE id=?", (int(iid),), one=True) if iid.isdigit() else None
        return {"issue": r["id"], "status": r["status"], "resolution": r["resolution"], "verdict": r["verdict"]} if r else {"issue": None, "note": "the issue is gone"}

    def risk_feed_budget(self, now=None):
        """ac_alerts (a limit's or the daily cap's warn share or the limit itself crossed): one row per owner, limit and period,
        at its highest level. Open while its period is the current one; a whole-life ("total") limit's row is open until the
        limit is removed or raised above the use that crossed it."""
        if not self._has("ac_alerts"): return 0
        now = now or _now()
        today = datetime.date.fromtimestamp(now)
        current = {today.isoformat(), today.strftime("%Y-%m")}
        lim = {}
        if self._has("ac_limits"): lim = {f"limit:{r['id']}": r for r in self.db.q("SELECT id, tokens, mode FROM ac_limits")}
        best = {}
        for a in self.db.q("SELECT * FROM ac_alerts ORDER BY id"):
            if a["period"] == "total":
                L = lim.get(a["ref"])
                if not L or (L["tokens"] or 0) > (a["spent"] or 0): continue
            elif a["period"] not in current: continue
            k = (a["owner_id"], f"budget:{a['ref']}:{a['period']}")
            if k not in best or (a["level"] == "limit" and best[k]["level"] != "limit"): best[k] = a
        out = {}
        for (uid, rkey), a in best.items():
            if uid is None: continue
            stop = a["level"] == "limit"
            stops = (lim.get(a["ref"]) or {}).get("mode", "stop") != "alert"
            out[(uid, rkey)] = {"n": RISK_RECUR, "fp": f"{a['level']}:{a['spent']}", "evidence": {"alert": a["id"], "level": a["level"], "spent": a["spent"],
                "tokens": a["tokens"], "period": a["period"]}, "fields": self._src_fields(
                "budget", f"ac_alerts:{a['id']}", None, "execution",
                f"{a['label'] or a['ref']}: {'limit reached' if stop else 'near its limit'} ({a['period']})",
                f"{a['spent']:,} of {a['tokens']:,} tokens used in {a['period']}." if a["spent"] is not None and a["tokens"] else a["label"] or a["ref"],
                "Use reached the limit." if stop else "Use crossed the limit's warn-at share.", {"scope": "owner", "limit": a["ref"], "period": a["period"]},
                "high" if stop and stops else "medium", f"budget threshold ({a['level']}) recorded by the agent core",
                "Raise the limit, or wait for its next period (Agent Operations → Budget)." if a["period"] != "total" else "Raise or remove the limit (Agent Operations → Budget).",
                "you")}
        return self._feed("budget", out, now)

    def risk_feed_ops(self, now=None):
        """mo_alerts (Mining Operations: team budgets, spend, performance), open at warn or stop: one row per owner and alert key."""
        if not self._has("mo_alerts"): return 0
        out = {}
        for a in self.db.q("SELECT * FROM mo_alerts WHERE status='open' AND level IN ('warn','stop') ORDER BY id"):
            if a["user_id"] is None: continue
            m = re.match(r"(?:budget|perf):(\d+)$", a["key"] or "")  # Mining Operations keys a team's alerts by its mw_comps id
            team = f"comp:{m.group(1)}" if m else None
            out[(a["user_id"], f"mo:{a['key']}")] = {"n": RISK_RECUR, "fp": f"{a['level']}:{a['title']}:{a['id']}", "evidence": {"alert": a["id"],
                "level": a["level"], "kind": a["kind"], "first_seen": a["first_seen"], "last_seen": a["last_seen"]}, "fields": self._src_fields(
                "ops", f"mo_alerts:{a['id']}", team, "evaluation" if a["kind"] == "performance" else "execution", a["title"] or a["key"],
                a["detail"] or a["title"] or a["key"], a["detail"] or a["title"] or a["key"], {"scope": team or "owner", "kind": a["kind"], "go": a["go"]},
                "high" if a["level"] == "stop" else "medium", f"Mining Operations alert ({a['kind']}, {a['level']})",
                "Open it in Mining Operations and act on its line.", "you")}
        return self._feed("ops", out, now or _now())

    def risk_feed_campaign(self, now=None):
        """mh_alerts (a campaign's sentinel: miner health, scouting), open or acknowledged, critical or warning: one row per
        campaign and alert key, owned by the campaign's user. Its mission column stays NULL: a campaign isn't a team or a mission."""
        if not (self._has("mh_alerts") and self._has("mh_campaigns")): return 0
        out = {}
        for a in self.db.q("""SELECT a.*, c.user_id, c.netuid FROM mh_alerts a JOIN mh_campaigns c ON c.id=a.campaign_id
                              WHERE a.status IN ('open','acked') AND a.level IN ('critical','warning') ORDER BY a.id"""):
            if a["user_id"] is None: continue
            out[(a["user_id"], f"mh:{a['campaign_id']}:{a['key']}")] = {"n": RISK_RECUR, "fp": f"{a['level']}:{a['title']}:{a['id']}", "evidence": {
                "alert": a["id"], "level": a["level"], "status": a["status"], "first_seen": a["first_seen"], "last_seen": a["last_seen"]},
                "fields": self._src_fields(
                "campaign", f"mh_alerts:{a['id']}", None, "mission", f"SN{a['netuid']}: {a['title'] or a['key']}", a["detail"] or a["title"] or a["key"],
                a["detail"] or a["title"] or a["key"], {"scope": "campaign", "campaign": a["campaign_id"], "netuid": a["netuid"]},
                "high" if a["level"] == "critical" else "medium", f"campaign sentinel alert ({a['level']})",
                "Open the campaign in Mining HQ and act on the alert.", "you")}
        return self._feed("campaign", out, now or _now())

    def _diag_scope(self, corr, team):
        """(mission column, scope label) of a diagnosed run: its mission when it has one, else its team, else its owner's own
        work (mission NULL). Never invented: corr falls back to the run's own ref, so only an mx: corr names a mission."""
        if corr and corr.startswith("mx:") and corr[3:].isdigit(): return corr, corr
        if team and (team.startswith("comp:") or team.startswith("co-team:")): return team, team
        return None, "owner"

    def risk_feed_diag(self, now=None):
        """io_diag: failure classes that aren't the work's own (RISK_DIAG_CLASSES), counted per scope over the window."""
        if not (self._has("io_diag") and self._has("ac_runs")): return 0
        now, cols = now or _now(), self._cols("ac_runs")
        corr = "a.corr" if "corr" in cols else "NULL"
        team = "a.team" if "team" in cols else "NULL"
        ph = ",".join("?" * len(RISK_DIAG_CLASSES))
        rows = self.db.q(f"""SELECT d.owner_id, {corr} AS corr, {team} AS team, COALESCE(d.canon, d.cls) AS k, a.id, a.system, d.evidence
                             FROM io_diag d JOIN ac_runs a ON a.id=d.run_id
                             WHERE a.started>? AND a.started<=? AND COALESCE(d.canon, d.cls) IN ({ph}) ORDER BY a.id""",
                         (now - RISK_WINDOW, now, *RISK_DIAG_CLASSES))
        groups = {}
        for r in rows:
            if r["owner_id"] is None: continue
            mission, scope = self._diag_scope(r["corr"], r["team"])
            g = groups.setdefault((r["owner_id"], f"diag:{scope}:{r['k']}"), {"mission": mission, "k": r["k"], "runs": [], "systems": set(), "latest": ""})
            g["runs"].append(r["id"]); g["systems"].add(r["system"] or "?"); g["latest"] = r["evidence"] or g["latest"]
        out = {}
        for (uid, rkey), g in groups.items():
            c, n = FAILURE_CLASSES.get(g["k"], {}), len(g["runs"])
            ops = c.get("ops") or ()
            where = g["mission"] or "your own runs"
            out[(uid, rkey)] = {"n": n, "fp": str(g["runs"][-1]), "evidence": {
                "runs": g["runs"][-20:], "n": n, "systems": sorted(g["systems"]), "latest": _clip(g["latest"], 300),
                "window_h": RISK_WINDOW // 3600, "threshold": RISK_RECUR}, "fields": dict(
                mission=g["mission"], layer=c.get("layer") or "execution", source="diagnosis", source_ref=f"io_diag:{g['k']}",
                title=_clip(f"{c.get('label') or g['k']} keeps failing runs ({where})", 200),
                description=f"{n} failed runs diagnosed as '{g['k']}' in the last {RISK_WINDOW // 3600} h ({', '.join(sorted(g['systems']))}); "
                            f"runs #{g['runs'][0]}–#{g['runs'][-1]}.",
                root_cause=ops[1] if len(ops) > 1 else f"{c.get('label') or g['k']}: {_clip(g['latest'], 240)}",
                probability="observed", impact={"runs": g["runs"][-20:], "mission": g["mission"], "scope": where},
                severity="medium" if c.get("fixes") else "high", priority="high" if n >= 3 * RISK_RECUR else "medium", critical=0,
                detection=f"orchestrator diagnosis of failed runs: {n} of class '{g['k']}' in {RISK_WINDOW // 3600} h (threshold {RISK_RECUR})",
                countermeasure=c.get("recovery") or "Read the newest run's error.", responsible=ops[2] if len(ops) > 2 else "you",
                approval=RISK_FEED_APPROVAL)}
        return self._feed("diagnosis", out, now)

    def risk_feed_sbx(self, now=None):
        """io_sbx (the diagnosis of failed sandbox runs), joined to mw_sbx for when and what: per team and sandbox class. The team's
        owning account (its campaign's user) owns the row; a run whose team or campaign is gone has no owner and isn't fed."""
        if not (self._has("io_sbx") and self._has("mw_sbx") and self._has("mw_comps") and self._has("mh_campaigns")): return 0
        now = now or _now()
        ph = ",".join("?" * len(RISK_SBX_SKIP))
        mine = "by_user" in {c["name"] for c in self.db.q("PRAGMA table_info(mw_sbx)")}
        not_team = f" AND COALESCE(s.by_user, '') NOT IN ({','.join('?' * len(RISK_SBX_NOT_TEAM))})" if mine else ""
        rows = self.db.q(f"""SELECT p.user_id AS owner_id, s.comp_id, d.cls AS k, s.id, s.error FROM io_sbx d JOIN mw_sbx s ON s.id=d.sbx_id
                             JOIN mw_comps w ON w.id=s.comp_id JOIN mh_campaigns p ON p.id=w.campaign_id
                             WHERE s.started>? AND s.started<=? AND d.cls NOT IN ({ph}){not_team} ORDER BY s.id""",
                         (now - RISK_WINDOW, now, *RISK_SBX_SKIP, *(RISK_SBX_NOT_TEAM if mine else ())))
        groups = {}
        for r in rows:
            if r["owner_id"] is None: continue
            g = groups.setdefault((r["owner_id"], f"sbx:comp:{r['comp_id']}:{r['k']}"), {"comp": f"comp:{r['comp_id']}", "k": r["k"], "runs": [], "latest": ""})
            g["runs"].append(r["id"]); g["latest"] = r["error"] or g["latest"]
        fixes = {k: (ok, fix) for k, _l, _p, ok, fix in SBX}
        out = {}
        for (uid, rkey), g in groups.items():
            n, (ok, fix) = len(g["runs"]), fixes.get(g["k"], (False, "Read the error on the run."))
            out[(uid, rkey)] = {"n": n, "fp": str(g["runs"][-1]), "evidence": {
                "sandbox_runs": g["runs"][-20:], "n": n, "latest": _clip(g["latest"], 300), "window_h": RISK_WINDOW // 3600, "threshold": RISK_RECUR},
                "fields": dict(
                mission=g["comp"], layer="execution", source="sandbox", source_ref=f"io_sbx:{g['k']}",
                title=_clip(f"Sandbox: {SBX_LABEL.get(g['k'], g['k'])} keeps recurring ({g['comp']})", 200),
                description=f"{n} sandbox runs of {g['comp']} failed as '{g['k']}' in the last {RISK_WINDOW // 3600} h; runs #{g['runs'][0]}–#{g['runs'][-1]}.",
                root_cause=f"{SBX_LABEL.get(g['k'], g['k'])}: {_clip(g['latest'], 240)}", probability="observed",
                impact={"sandbox_runs": g["runs"][-20:], "mission": g["comp"], "scope": g["comp"]},
                severity="medium" if ok else "high", priority="high" if n >= 3 * RISK_RECUR else "medium", critical=0,
                detection=f"orchestrator diagnosis of failed sandbox runs: {n} of class '{g['k']}' in {RISK_WINDOW // 3600} h (threshold {RISK_RECUR})",
                countermeasure=fix, responsible="AXoR (retries it)" if ok else "an administrator", approval=RISK_FEED_APPROVAL)}
        return self._feed("sandbox", out, now)

    def _feed(self, source, groups, now, resolve_note=None):
        """Writes one feed's groups {(owner, rkey): {n, fp, evidence, fields}} against its own rows. Returns the rows changed.
        R3.2's feeds pass n = RISK_RECUR: their source already decided it's an issue, so presence alone opens the row."""
        mine = {(r["owner_id"], r["rkey"]): r for r in self.db.q("SELECT id, owner_id, rkey, status, evidence, source_ref FROM io_risks WHERE source=?", (source,))}
        n = 0
        for key, g in groups.items():
            cur = mine.get(key)
            live = cur and cur["status"] != "resolved"
            if not (g["n"] >= RISK_RECUR or live): continue  # under the threshold and nothing open: not a risk yet
            try: was = json.loads(cur["evidence"] or "{}").get("fp") if live else None
            except (TypeError, ValueError): was = None
            if live and was == g["fp"]: continue  # nothing new since the last pass
            self.risk_upsert(key[0], key[1], {**g["evidence"], "fp": g["fp"], "checked": now}, **g["fields"])
            n += 1
        for key, cur in mine.items():
            if cur["status"] != "resolved" and key not in groups:
                if source in RISK_SRC_FEEDS:
                    v = {"by": "", "feed": source, "checked": now, "note": f"no longer open at its source ({source})"}
                    if resolve_note: v["source"] = resolve_note(cur)
                else:
                    v = {"by": "", "feed": source, "n": 0, "window_h": RISK_WINDOW // 3600, "checked": now,
                         "note": f"no {source} failure of this kind in the last {RISK_WINDOW // 3600} h"}
                n += bool(self.risk_resolve(key[0], key[1], v))
        return n

    def risk_accept(self, me, rid, note=""):
        """The Owner's explicit acceptance of a non-critical risk: its readiness item no longer blocks (CONDITIONAL). Critical risks
        (a sign-in, an approval, a credential) can't be accepted."""
        org = me.get("role") == "admin"  # the organization's rows (ORG_OWNER) are accepted by an administrator (G5-3 R3.2)
        r = self.db.q("SELECT * FROM io_risks WHERE id=? AND owner_id IN (?, ?)", (rid, me["id"], ORG_OWNER if org else me["id"]), one=True)
        if not r: raise HTTPException(404, "There's no such risk.")
        if r["critical"]: raise HTTPException(409, "A critical requirement can't be accepted: it has to be fixed.")
        if r["status"] == "resolved": raise HTTPException(409, "It's resolved already.")
        now = _now()
        self.db.q("UPDATE io_risks SET status='accepted', accepted_by=?, accepted_at=?, updated=? WHERE id=?", (me["username"], now, now, rid))
        self.audit(me["id"], me["username"], "risk.accept", r["rkey"], _clip(note, 300), r["mission"])
        return self.risk(me["id"], rid, org)

    def _risk_row(self, me, rid):
        r = self.db.q("SELECT * FROM io_risks WHERE id=? AND owner_id=?", (rid, me["id"]), one=True)
        if not r: raise HTTPException(404, "There's no such risk.")
        if (r["source"] or "readiness") != "readiness":  # G5-3: a fed row records its source; only a readiness item is verified or approved
            raise HTTPException(409, "Only a readiness requirement is verified or approved here; this risk closes when its source does.")
        try: state = (json.loads(r["evidence"] or "{}") or {}).get("state")
        except ValueError: state = None
        return r, state, (r["source_ref"] or "").partition(":")[2], (r["rkey"] or "").rsplit(":", 1)[-1]

    def risk_verify(self, me, rid, note=""):
        """A person vouches that a **credential** works (no probe can show it, Owner clarification B). The verification is bound
        to the credential's fingerprint (a changed value voids it; for a credential Vault holds, a new version of the secret) and
        expires: mission_ops.credential_ttl (VERIFY_DAYS, or CRED_ABSENT_HOURS for a credential this server can't see). Approvals of external actions are never verified this way: they use risk_approve.
        Only for a finding whose probe said UNKNOWN: a FAIL has to be fixed, not vouched for."""
        from . import mission_ops
        r, state, cap, value = self._risk_row(me, rid)
        if cap == "approval": raise HTTPException(409, "An external action needs its own approval, bound to the task: use Approve.")
        if cap != "credential": raise HTTPException(409, "Only a credential can be verified by hand; this requirement has a probe: fix it.")
        if state != "UNKNOWN": raise HTTPException(409, "This credential failed its check: fix it rather than vouch for it.")
        if not (note or "").strip(): raise HTTPException(422, "Say how you verified it.")
        team, mission = mission_ops.cred_scope(self.db, r["rkey"])
        now, fp = _now(), mission_ops.credential_fingerprint(value, team, mission)
        if fp == mission_ops.CRED_UNREADABLE:  # PX-B16: never a record that can't be tied to the secret's version
            raise HTTPException(503, "Vault can't be read right now, so this verification couldn't be tied to the secret's current version: try again when Vault answers.")
        ttl = mission_ops.credential_ttl(fp)
        v = {"kind": "credential", "by": me["username"], "note": _clip(note, 500), "at": now, "fingerprint": fp, "expires": now + ttl}
        self.db.q("UPDATE io_risks SET status='resolved', resolved_at=?, verification=?, updated=? WHERE id=?", (now, json.dumps(v), now, rid))
        self.audit(me["id"], me["username"], "risk.verify", r["rkey"], _clip(f"{note} (fingerprint {fp})", 300), r["mission"])
        return self.risk(me["id"], rid)

    def risk_approve(self, me, rid, action="", payload_sha=None):
        """The Owner's approval of one external action for one exact task: bound to the risk's mission and task, the action named,
        and the task's payload (title, detail, needs) as it is now; payload_sha, when given, must be what the approver saw. One use
        (consumed when the task starts) within mission_ops.APPROVAL_HOURS."""
        from . import mission_ops
        if me.get("role") != "admin": raise HTTPException(403, "Only an administrator approves external actions.")
        r, state, cap, value = self._risk_row(me, rid)
        if cap != "approval": raise HTTPException(409, "This risk isn't an approval.")
        t = self._task_of(r["task_ref"])
        if not t: raise HTTPException(409, "Its task is gone.")
        sha = mission_ops.task_payload(t)
        if payload_sha and payload_sha != sha: raise HTTPException(409, "The task changed since you looked at it: read it again before approving.")
        if not (action or "").strip(): raise HTTPException(422, "Name the action you approve (e.g. push the image, submit the commit).")
        now = _now()
        v = {"kind": "approval", "by": me["username"], "at": now, "mission": r["mission"], "task_ref": r["task_ref"], "action": _clip(action, 200),
             "payload_sha": sha, "single_use": True, "expires": now + mission_ops.APPROVAL_HOURS * 3600, "consumed": None}
        self.db.q("UPDATE io_risks SET status='resolved', resolved_at=?, verification=?, updated=? WHERE id=?", (now, json.dumps(v), now, rid))
        self.audit(me["id"], me["username"], "risk.approve", r["rkey"], _clip(f"{action} · payload {sha[:12]}", 300), r["mission"])
        return self.risk(me["id"], rid)

    def approval_consume(self, uid, rkey):
        """The approved task started: its one-time approval is used up (the next run needs a new one)."""
        r = self.db.q("SELECT id, verification, mission FROM io_risks WHERE owner_id=? AND rkey=?", (uid, rkey), one=True)
        if not r: return False
        try: v = json.loads(r["verification"] or "{}")
        except ValueError: return False
        if v.get("kind") != "approval" or v.get("consumed"): return False
        v["consumed"] = _now()
        self.db.q("UPDATE io_risks SET verification=?, updated=? WHERE id=?", (json.dumps(v), _now(), r["id"]))
        self.audit(uid, "Risk Intelligence", "approval.consumed", rkey, v.get("action", ""), r["mission"])
        return True

    def _task_of(self, ref):
        m = re.fullmatch(r"(mw_task|ctl):t?(\d+)", ref or "")
        if not m: return None
        table = "mw_tasks" if m.group(1) == "mw_task" else "ctl_tasks"
        return self.db.q(f"SELECT * FROM {table} WHERE id=?", (int(m.group(2)),), one=True) if self._has(table) else None

    def risk(self, uid, rid, org=False):
        r = self.db.q("SELECT * FROM io_risks WHERE id=? AND owner_id IN (?, ?)", (rid, uid, ORG_OWNER if org else uid), one=True)
        return _risk_out(r) if r else None

    def risks(self, uid, mission=None, status=None, limit=200, source=None, scope=None, org=False):
        """This owner's rows, plus the organization's (ORG_OWNER) for an administrator (org). scope: mission (mx:), team (comp:,
        co-team:), owner (no mission, this owner's) or organization; source: the feed or 'readiness' (G5-3 R3.4)."""
        sql, args = "SELECT * FROM io_risks WHERE owner_id IN (?, ?)", [uid, ORG_OWNER if org else uid]
        if mission: sql += " AND mission=?"; args.append(mission)
        if status: sql += " AND status=?"; args.append(status)
        if source: sql += " AND source=?"; args.append(source)
        if scope == "organization": sql += " AND owner_id=?"; args.append(ORG_OWNER)
        elif scope == "mission": sql += " AND mission LIKE 'mx:%'"
        elif scope == "team": sql += " AND (mission LIKE 'comp:%' OR mission LIKE 'co-team:%')"
        elif scope == "owner": sql += " AND mission IS NULL AND owner_id=?"; args.append(uid)
        return [_risk_out(r) for r in self.db.q(sql + " ORDER BY critical DESC, CASE status WHEN 'open' THEN 0 WHEN 'accepted' THEN 1 ELSE 2 END, last_seen DESC LIMIT ?",
                                                 (*args, max(1, min(int(limit), 500))))]

    def _rediagnose(self):
        """Once a process: runs filed as 'task' that today's classifier files elsewhere (2026-11-17: expired-login refusals were read
        as the task's own failure, and the planners' guidance said so for 30 days) get their class, recovery and canon redone. Their
        diagnosis time stays, so they leave the window when they would have. Returns how many changed."""
        n = 0
        for r in self.db.q("""SELECT d.run_id, a.status, a.error FROM io_diag d JOIN ac_runs a ON a.id=d.run_id
                              WHERE d.cls='task' AND d.ts>? ORDER BY d.run_id LIMIT ?""", (_now() - WINDOW, BATCH * 5)):
            k = fail_class(r["status"], r["error"])
            if k == "task": continue
            ok, fix = RECOVERY.get(k, RECOVERY["task"])
            if k == "sandbox": _c, _l, ok, fix = sbx_class("error", r["error"])
            self.db.q("UPDATE io_diag SET cls=?, recoverable=?, recovery=?, canon=? WHERE run_id=?",
                      (k, int(ok), fix, failure(r["status"], r["error"])["cls"], r["run_id"]))
            n += 1
        if n: log.info("diagnose: %d run(s) filed as 'task' re-filed under today's classes", n)
        return n

    def taxonomy(self, uid, days=7):
        """The failure taxonomy (read-only): every class with its family, layer and policies, the consumers' policy conflicts, and this
        owner's diagnosed failures of the last `days` by canonical class, with how many the legacy class files differently."""
        counts = []
        if self._has("io_diag"):
            for x in self.db.q("""SELECT COALESCE(canon, '') AS canon, cls, COUNT(*) AS n FROM io_diag WHERE owner_id=? AND ts>?
                                 GROUP BY COALESCE(canon, ''), cls ORDER BY n DESC""",
                               (uid, _now() - days * 86400)):
                c = x["canon"] or None
                counts.append({"canon": c, "legacy": x["cls"], "n": x["n"],
                               "conflict": bool(c and c in FAILURE_CLASSES and x["cls"] in FAILURE_CLASSES and c != "cancelled"
                                                and FAILURE_CLASSES[c]["own"] != FAILURE_CLASSES[x["cls"]]["own"])})
        classes = [{"key": k, "legacy": k in LEGACY_CLASSES, **{f: v for f, v in d.items() if f not in ("ops", "autoloop")},
                    "ops": dict(zip(("situation", "recovery", "who"), d["ops"])) if d.get("ops") else None} for k, d in FAILURE_CLASSES.items()]
        return {"classes": classes, "conflicts": [{**c, "classes": list(c["classes"])} for c in CONFLICTS], "days": days, "counts": counts,
                "undiagnosed_canon": sum(x["n"] for x in counts if not x["canon"])}

    def diagnose_sandbox(self):
        if not self._has("mw_sbx"): return 0
        rows = self.db.q("""SELECT s.id, s.comp_id, s.status, s.error FROM mw_sbx s LEFT JOIN io_sbx d ON d.sbx_id=s.id
                            WHERE s.status IN ('error','timeout') AND s.started>? AND d.sbx_id IS NULL LIMIT ?""", (_now() - WINDOW, BATCH))
        for r in rows:
            k, _l, ok, fix = sbx_class(r["status"], r["error"])
            self.db.q("INSERT OR REPLACE INTO io_sbx (sbx_id, comp_id, cls, recoverable, recovery, ts) VALUES (?,?,?,?,?,?)", (r["id"], r["comp_id"], k, int(ok), fix, _now()))
        return len(rows)

    def _recovery_path(self, d):
        """(how, label) a diagnosed failed run is recovered through its own system, or (None, why not here)."""
        p, _, rest = (d["ref"] or "").partition(":")
        if d["system"] == "teams" or p in ("mw", "au"): return None, "Autoloop puts team work back in the queue by itself"
        st = lambda sql, i: (self.db.q(sql, (i,), one=True) or {}).get("status") if self._has(sql.split(" FROM ")[1].split()[0]) else None
        if p == "ctl" and rest.startswith("t") and rest[1:].isdigit() and "control" in self.systems:
            x = st("SELECT status FROM ctl_tasks WHERE id=?", int(rest[1:]))
            return ("control", "Start the task again") if x == "failed" else (None, f"The task is {x or 'gone'} now")
        if p == "ia" and rest.isdigit() and "infiagent" in self.systems:
            x = st("SELECT status FROM ia_tasks WHERE id=?", int(rest))
            return ("infiagent", "Resume the long task from its checkpoint") if x == "paused" else (None, f"The long task is {x or 'gone'} now")
        if p == "mx" and rest.isdigit() and "missions" in self.systems:
            x = st("SELECT status FROM mx_missions WHERE id=?", int(rest))
            return ("missions", "Resume the mission") if x == "paused" else (None, f"The mission is {x or 'gone'} now")
        if p == "wf" and rest.isdigit() and "workforce" in self.systems and self._has("wf_runs"):
            r = self.db.q("SELECT mission_id FROM wf_runs WHERE id=?", (int(rest),), one=True)
            x = r and r["mission_id"] and st("SELECT status FROM wf_missions WHERE id=?", r["mission_id"])
            return ("workforce", "Run its Workforce mission again (a new mission)") if x in ("failed", "cancelled", "stopped") else (None, f"Its Workforce mission is {x or 'gone'} now")
        return None, "Its system has no way to run it again from here"

    def recoverable(self, uid, since, limit=10):
        """Recent failed runs a retry can fix that haven't been recovered, newest first, each with how it would be."""
        out = []
        for d in self.db.q("""SELECT d.*, a.title, a.started FROM io_diag d JOIN ac_runs a ON a.id=d.run_id WHERE d.owner_id=? AND d.ts>? AND d.recoverable=1
                              AND d.recovered IS NULL ORDER BY d.run_id DESC LIMIT 60""", (uid, since)):
            if d["cls"] == "restart":  # its own system may have picked it up already (restart_recovery.py): then it's recovered, and says by whom
                f = restart_recovery.follow(self.db, {"id": d["run_id"], "ref": d["ref"], "status": "failed", "error": "server restart"})
                if f["state"] == "recovered":
                    self.db.q("UPDATE io_diag SET recovered=? WHERE run_id=? AND recovered IS NULL", (_clip(f"by itself ({f['owner']}): {f['detail']}", 300), d["run_id"]))
                    continue
            how, label = self._recovery_path(d)
            if how: out.append({"run_id": d["run_id"], "ref": d["ref"], "title": d["title"], "cls": d["cls"], "recovery": d["recovery"], "how": label, "started": d["started"]})
            if len(out) >= limit: break
        return out

    def recover(self, me, run_id):
        """A recoverable failed run, again, through its own system (as you, so its own permission and budget checks apply)."""
        self._gate(me)
        d = self.db.q("SELECT * FROM io_diag WHERE run_id=? AND owner_id=?", (run_id, me["id"]), one=True)
        if not d: raise HTTPException(404, "No diagnosed failed run of yours with that id.")
        if not d["recoverable"]: raise HTTPException(409, f"Running it again won't help: {d['recovery']}")
        if d["recovered"]: raise HTTPException(409, f"It was recovered already ({d['recovered']}).")
        how, label = self._recovery_path(d)
        if not how: raise HTTPException(409, label)
        rest = d["ref"].partition(":")[2]
        sysobj = self.systems[how]
        if how == "control":
            sysobj.start_task(me, int(rest[1:])); done = f"task {rest} started again"
        elif how == "infiagent":
            t = self.db.q("SELECT status FROM ia_tasks WHERE id=?", (int(rest),), one=True)
            if not t or t["status"] != "paused": raise HTTPException(409, f"The long task is {t['status'] if t else 'gone'}: only a paused one resumes.")
            sysobj.resume(me, int(rest)); done = f"long task {rest} resumed"
        elif how == "missions":
            m = self.db.q("SELECT status FROM mx_missions WHERE id=?", (int(rest),), one=True)
            if not m or m["status"] != "paused": raise HTTPException(409, f"The mission is {m['status'] if m else 'gone'}: only a paused one resumes.")
            sysobj.resume(me, int(rest)); done = f"mission {rest} resumed"
        else:
            r = self.db.q("SELECT mission_id FROM wf_runs WHERE id=?", (int(rest),), one=True)
            if not r or not r["mission_id"]: raise HTTPException(409, "Its Workforce mission isn't there any more.")
            st = self.db.q("SELECT status FROM wf_missions WHERE id=?", (r["mission_id"],), one=True)
            if st and st["status"] not in ("failed", "cancelled", "stopped"): raise HTTPException(409, f"Its Workforce mission is {st['status']}: nothing to run again.")
            got = sysobj.rerun(me, r["mission_id"]); done = f"Workforce mission {r['mission_id']} run again as #{got.get('id')}"
        # every failed run of the same work counts as recovered by this
        self.db.q("UPDATE io_diag SET recovered=? WHERE owner_id=? AND ref=? AND recovered IS NULL", (done, me["id"], d["ref"]))
        self.audit(me["id"], me["username"], "run.recovered", f"run:{run_id}", f"{d['cls']}: {done}", d["corr"])
        return {"recovered": done}

    def retry_sandbox(self, me, sid):
        """A recoverable sandbox run again, as the same command on the same team's files (recorded as a new sandbox run)."""
        self._gate(me)
        if self.work is None: raise HTTPException(503, "Competition teams aren't running on this server.")
        r = self.db.q("SELECT * FROM mw_sbx WHERE id=?", (sid,), one=True)
        if not r: raise HTTPException(404, "There's no such sandbox run.")
        self.work._own(me, r["comp_id"])  # 404/403 unless it's your team's
        d = self.db.q("SELECT * FROM io_sbx WHERE sbx_id=?", (sid,), one=True)
        if not d:
            self.diagnose_sandbox(); d = self.db.q("SELECT * FROM io_sbx WHERE sbx_id=?", (sid,), one=True)
        if not d: raise HTTPException(400, "That run didn't fail in the sandbox: it ran, and its code's own result stands.")
        if not d["recoverable"]: raise HTTPException(409, f"Running it again won't help: {d['recovery']}")
        if d["retried_as"]: raise HTTPException(409, f"It was run again already (sandbox run #{d['retried_as']}).")
        from . import mining_work
        before = self.db.q("SELECT MAX(id) n FROM mw_sbx", one=True)["n"] or 0
        self.work.run_sandbox(me, r["comp_id"], mining_work.RunIn(command=r["command"], services=[s for s in (r["services"] or "").split(",") if s]))
        new = self.db.q("SELECT MAX(id) n FROM mw_sbx WHERE comp_id=?", (r["comp_id"],), one=True)["n"]
        self.db.q("UPDATE io_sbx SET retried_as=? WHERE sbx_id=?", (new if new and new > before else None, sid))
        self.audit(me["id"], me["username"], "sandbox.retried", f"sbx:{sid}", f"{d['cls']} → run #{new}")
        return {"retried_as": new}

    # ---------- observations that become handoff events ----------
    def observe_missions(self):
        if not self._has("mx_missions"): return 0
        n = 0
        for m in self.db.q("""SELECT id, user_id, status, outcome FROM mx_missions WHERE finished IS NOT NULL AND finished>? AND
                              (status IN ('delivered','failed','done') OR outcome IS NOT NULL)""", (_now() - WINDOW,)):
            n += bool(self.emit(m["user_id"], "mission.finished", f"mx:{m['id']}:finished", corr=f"mx:{m['id']}", ref=f"mx:{m['id']}",
                                payload={"status": m["status"], "outcome": m["outcome"]}))
        return n

    def signals(self, uid, since=None):
        """Agents whose recent work is failing or scoring low, from the ledger and the diagnoses (owner's agents only)."""
        since = since or _now() - SIGNAL_DAYS * 86400
        out = []
        for r in self.db.q("""SELECT agent_key, COUNT(*) n, SUM(status IN ('failed','error','lost')) bad, COUNT(score) scored, AVG(score) avg FROM ac_runs
                              WHERE owner_id=? AND agent_key IS NOT NULL AND started>=? AND status!='running' AND kind NOT IN ('experiment','earlier','cases','draft')
                              GROUP BY agent_key""", (uid, since)):
            ev, cls = [], None
            if (r["bad"] or 0) >= SIGNAL_MIN_FAILS and r["bad"] / r["n"] >= SIGNAL_FAIL_RATE:
                top = self.db.q("""SELECT cls, COUNT(*) n FROM io_diag WHERE owner_id=? AND agent_key=? AND ts>=? GROUP BY cls ORDER BY n DESC LIMIT 1""",
                                (uid, r["agent_key"], since), one=True)
                cls = top["cls"] if top else "task"
                if cls in ("restart", "quota", "budget", "rate", "transient"): cls = None  # the environment's, not the agent's: no proposal fixes it
                else: ev.append(f"{r['bad']} of {r['n']} runs failed in {SIGNAL_DAYS} days, most: {cls}")
            if (r["scored"] or 0) >= SIGNAL_MIN_SCORED and (r["avg"] if r["avg"] is not None else 100) < SIGNAL_LOW:
                ev.append(f"average score {r['avg']:.0f}/100 over {r['scored']} scored runs")
            if ev:
                name = self.db.q("SELECT name FROM ac_agents WHERE key=?", (r["agent_key"],), one=True) if self._has("ac_agents") else None
                out.append({"agent": r["agent_key"], "name": (name or {}).get("name") or r["agent_key"], "evidence": ev, "cls": cls,
                            "top": ev[0], "runs": r["n"], "failed": r["bad"] or 0, "avg": r["avg"]})
        return out

    def observe_signals(self):
        if not (self._has("ac_runs") and self._has("ev_proposals")): return 0
        n, week = 0, int(_now() // (7 * 86400))
        for u in self.db.q("SELECT DISTINCT owner_id FROM ac_runs WHERE started>? AND owner_id>0", (_now() - SIGNAL_DAYS * 86400,)):
            for s in self.signals(u["owner_id"]):
                n += bool(self.emit(u["owner_id"], "agent.signal", f"sig:{u['owner_id']}:{s['agent']}:{week}", corr=s["agent"], ref=s["agent"], payload=s))
        return n

    def observe_promotions(self):
        if not self._has("ev_proposals"): return 0
        n = 0
        for p in self.db.q("SELECT id, user_id, target_key FROM ev_proposals WHERE status IN ('promoted','rolled_back') AND promoted>?", (_now() - WINDOW,)):
            n += bool(self.emit(p["user_id"], "proposal.promoted", f"ev:{p['id']}:promoted", corr=p["target_key"], ref=f"ev:{p['id']}"))
        return n

    def _obs(self, kind, need, key, cols, frm, where, args=()):
        """Records not yet in the ledger as done `kind` events, at the record's own time. key: SQL for the idempotency key;
        cols: SQL giving owner, corr, ref and at."""
        if not all(self._has(t) for t in need): return 0
        n = 0
        for r in self.db.q(f"SELECT {key} AS k, {cols} FROM {frm} LEFT JOIN io_events ev ON ev.key={key} WHERE ev.id IS NULL AND {where} LIMIT ?", (*args, BATCH)):
            if r["owner"] is None or not r["k"]: continue
            n += bool(self.emit(r["owner"], kind, r["k"], corr=r["corr"], ref=r["ref"], status="done", at=r["at"] or _now()))
        return n

    def observe_handoffs(self):
        """Every loop handoff the systems recorded in the last WINDOW, once each, into io_events: the one ledger both the
        Intelligence layers overview and the orchestrator's table count (edges()). WINDOW (30 d) < KEEP_DAYS (120 d), so prune()
        never deletes an event its record would emit again."""
        since, n = _now() - WINDOW, 0
        corr = "COALESCE(r.corr, r.ref)" if self._has("ac_runs") and "corr" in self._cols("ac_runs") else "r.ref"
        late = _now() - 60  # a child engine's mission links it within a second of creating it: don't call it direct before that
        for kind, need, key, cols, frm, where, args in (
            ("mission.launched", ("mx_missions",), "'mx:' || m.id || ':launched:' || m.engine || ':' || COALESCE(CAST(m.child AS TEXT), 'None')",
             "m.user_id owner, 'mx:' || m.id corr, 'mx:' || m.id ref, m.started at", "mx_missions m", "m.engine IS NOT NULL AND m.started>?", (since,)),
            ("work.assigned", ("ctl_tasks",), "'ctl:t' || t.id || ':assigned'", "t.user_id owner, 'ctl:t' || t.id corr, 'ctl:t' || t.id ref, t.created at",
             "ctl_tasks t", "t.created>?", (since,)),
            ("work.assigned", ("wf_missions", "io_links"), "'wfm:' || w.id || ':assigned'", "w.user_id owner, 'wfm:' || w.id corr, 'wfm:' || w.id ref, w.created at",
             "wf_missions w", "w.created>? AND w.created<? AND w.bench_id IS NULL AND NOT EXISTS (SELECT 1 FROM io_links l WHERE l.ref='wfm:' || w.id)", (since, late)),
            ("work.assigned", ("sw_swarms", "io_links"), "'sws:' || s.id || ':assigned'", "s.user_id owner, 'sws:' || s.id corr, 'sws:' || s.id ref, s.created at",
             "sw_swarms s", "s.created>? AND s.created<? AND NOT EXISTS (SELECT 1 FROM io_links l WHERE l.ref='sws:' || s.id)", (since, late)),
            ("run.routed", ("ac_runs",), "'run:' || r.id || ':routed'", f"r.owner_id owner, {corr} corr, 'run:' || r.id ref, r.started at",
             "ac_runs r", "r.decision IS NOT NULL AND r.started>? AND r.owner_id>0", (since,)),
            ("knowledge.written", ("mx_lessons",), "'mxl:' || x.id", "x.user_id owner, 'mx:' || x.mission_id corr, 'mxl:' || x.id ref, x.created at",
             "mx_lessons x", "x.created>?", (since,)),
            ("knowledge.written", ("wf_memory",), "'wfmem:' || x.id", "x.user_id owner, NULL corr, 'wfmem:' || x.id ref, x.created at",
             "wf_memory x", "x.created>?", (since,)),
            ("knowledge.written", ("mw_notes", "mw_comps", "mh_campaigns"), "'mwn:' || x.id",
             "p.user_id owner, 'comp:' || x.comp_id corr, 'mwn:' || x.id ref, x.ts at",
             "mw_notes x JOIN mw_comps c ON c.id=x.comp_id JOIN mh_campaigns p ON p.id=c.campaign_id", "x.ts>?", (since,)),
            ("run.scored", ("ac_runs", "io_evals"), "'run:' || r.id || ':scored'", f"r.owner_id owner, {corr} corr, 'run:' || r.id ref, COALESCE(r.finished, r.started) at",
             "io_evals e JOIN ac_runs r ON r.id=e.run_id", "e.state='scored' AND r.started>? AND r.owner_id>0", (since,)),
            # G5-5 L5.1: a reviewed board run reached evaluation too. Without this, a week of reviewed work reads as a broken handoff
            ("run.reviewed", ("ac_runs", "io_evals"), "'run:' || r.id || ':reviewed'", f"r.owner_id owner, {corr} corr, 'run:' || r.id ref, COALESCE(r.finished, r.started) at",
             "io_evals e JOIN ac_runs r ON r.id=e.run_id", "e.state='reviewed' AND r.started>? AND r.owner_id>0", (since,)),
            ("proposal.tested", ("ev_trials", "ev_proposals"), "'ev:' || x.pid || ':run:' || x.run", "x.owner owner, x.target corr, 'ev:' || x.pid ref, x.at at",
             "(SELECT t.proposal_id pid, t.run run, p.user_id owner, p.target_key target, MIN(t.ts) at FROM ev_trials t JOIN ev_proposals p ON p.id=t.proposal_id GROUP BY t.proposal_id, t.run, p.user_id, p.target_key) x",
             "x.at>?", (since,)),
            ("proposal.tested", ("wf_improvements",), "'wfi:' || x.id || ':trial:' || x.trials", "x.user_id owner, 'workforce:' || x.agent_id corr, 'wfi:' || x.id ref, x.updated at",
             "wf_improvements x", "x.trials>0 AND x.updated>?", (since,)),
            ("proposal.tested", ("mb_experiments", "mb_flows"), "'mbx:' || x.id", "f.user_id owner, 'comp:' || f.comp_id corr, 'mbx:' || x.id ref, x.finished at",
             "mb_experiments x JOIN mb_flows f ON f.id=x.flow_id", "x.status='done' AND x.finished>?", (since,)),
            ("proposal.tested", ("au_sprints",), "'au:' || x.id", "x.user_id owner, 'comp:' || x.comp_id corr, 'au:' || x.id ref, x.started at",
             "au_sprints x", "x.started>?", (since,)),
            ("recall.mission", ("ex_recalls",), "'exr:' || x.id || ':mission'", "x.user_id owner, x.context corr, 'exr:' || x.id ref, x.ts at",
             "ex_recalls x", "x.context LIKE 'mx:%' AND x.found>0 AND x.ts>?", (since,)),
            ("knowledge.read", ("kb_queries",), "'kbq:' || x.id", "x.user_id owner, NULL corr, 'kbq:' || x.id ref, x.ts at", "kb_queries x", "x.ts>?", (since,)),
            ("knowledge.read", ("ex_recalls",), "'exr:' || x.id", "x.user_id owner, x.context corr, 'exr:' || x.id ref, x.ts at", "ex_recalls x", "x.ts>?", (since,)),
        ):
            try: n += self._obs(kind, need, key, cols, frm, where, args)
            except Exception as e:  # noqa: BLE001 - a system whose table differs here never stops the other observations
                log.warning("orchestrator observe %s (%s): %s", kind, frm.split()[0], e)
        return n

    def monitor(self):
        """Watched promotions: after MONITOR_N scored runs, kept when they hold the bar, a regression event when they fall under it by
        more than the policy's margin."""
        if not self._has("io_monitor") or not self._has("ev_proposals"): return 0
        n = 0
        for w in self.db.q("SELECT * FROM io_monitor WHERE state='watching'"):
            st = self.db.q("SELECT status FROM ev_proposals WHERE id=?", (w["proposal_id"],), one=True)
            if not st or st["status"] != "promoted":
                self.db.q("UPDATE io_monitor SET state='ended', checked=? WHERE proposal_id=?", (_now(), w["proposal_id"])); continue
            if w["basis"] == "ratings":
                ra, rn = self._ratings(w["owner_id"], w["target_key"], w["promoted"])
                a = {"a": ra, "n": rn}
            else:
                a = self.db.q("""SELECT AVG(score) a, COUNT(score) n FROM ac_runs WHERE owner_id=? AND agent_key=? AND score IS NOT NULL AND started>=?
                                 AND kind NOT IN ('experiment','cases','draft')""", (w["owner_id"], w["target_key"], w["promoted"]), one=True)
            self.db.q("UPDATE io_monitor SET after_avg=?, after_n=?, checked=? WHERE proposal_id=?", (a["a"], a["n"] or 0, _now(), w["proposal_id"]))
            if (a["n"] or 0) < MONITOR_N or w["base_avg"] is None: continue
            margin = float((self.ev.policy(w["owner_id"]) if self.ev else {}).get("margin", 5.0))
            if w["basis"] == "ratings": margin = max(margin, 15.0)  # a share of thumbs moves in big steps on few answers
            if a["a"] < w["base_avg"] - margin:
                what = "scored runs" if w["basis"] != "ratings" else "rated chat answers (% thumbs-up)"
                why = f"After the promotion it averaged {a['a']:.0f} over {a['n']} {what}, against {w['base_avg']:.0f} before (margin {margin:g})"
                n += bool(self.emit(w["owner_id"], "proposal.regressed", f"ev:{w['proposal_id']}:regressed", corr=w["target_key"], ref=f"ev:{w['proposal_id']}", payload={"why": why}))
            else:
                self.db.q("UPDATE io_monitor SET state='kept', note=? WHERE proposal_id=?",
                          (f"Held: {a['a']:.0f} over {a['n']} {'rated chat answers' if w['basis'] == 'ratings' else 'scored runs'} against {w['base_avg']:.0f} before", w["proposal_id"]))
                self.audit(w["owner_id"], "Orchestrator", "monitor.kept", f"proposal:{w['proposal_id']}", f"{a['a']:.0f} vs {w['base_avg']:.0f}", w["target_key"])
                n += 1
        return n

    # ------------------------------------------------------------------ performance-based workforce optimization
    def optimize(self, uid, days=30):
        """Recommendations from the run ledger, never applied here: underperforming and costly agents (against their own system's
        average), strong ones, idle registered agents, and models that scored better than the one most used for a kind of work.
        Failures that aren't the work's own (OWN_CANON, G5-2 D-015 D1: restart, quota, budget, rate, network, a missing login, the
        provider, the sandbox, a tool) don't count against an agent."""
        since, out = _now() - days * 86400, []
        if not self._has("ac_runs"): return {"agents": [], "models": [], "idle": 0, "idle_names": []}
        rows = self.db.q(f"""SELECT a.agent_key, a.system, COUNT(*) n, COUNT(a.score) scored, AVG(a.score) avg,
                                   SUM(a.status IN ('failed','error','lost') AND COALESCE(d.canon, d.cls, 'task') IN ({OWN_SQL})) bad,
                                   AVG(CASE WHEN a.status='done' THEN NULLIF(a.tokens,0) END) tok, MAX(a.started) last
                            FROM ac_runs a LEFT JOIN io_diag d ON d.run_id=a.id WHERE a.owner_id=? AND a.started>? AND a.agent_key IS NOT NULL AND a.status!='running'
                            AND a.kind NOT IN ('experiment','cases','draft','earlier') GROUP BY a.agent_key""", (uid, since))
        sysavg, systok = {}, {}
        for s in {r["system"] for r in rows}:
            mine = [r for r in rows if r["system"] == s]
            sc = [r["avg"] for r in mine if r["scored"] >= 3 and r["avg"] is not None]
            tk = sorted(r["tok"] for r in mine if r["tok"])
            sysavg[s], systok[s] = (sum(sc) / len(sc) if sc else None), (tk[len(tk) // 2] if tk else None)
        names = {r["key"]: r["name"] for r in self.db.q("SELECT key, name FROM ac_agents WHERE owner_id=?", (uid,))} if self._has("ac_agents") else {}
        for r in rows:
            sa, st, k = sysavg.get(r["system"]), systok.get(r["system"]), r["agent_key"]
            base = {"agent": k, "name": names.get(k) or k, "system": agent_core.SYSTEMS.get(r["system"], r["system"]), "runs": r["n"], "scored": r["scored"],
                    "avg": round(r["avg"]) if r["avg"] is not None else None, "sys_avg": round(sa) if sa is not None else None, "tokens": round(r["tok"]) if r["tok"] else None}
            if r["scored"] >= 5 and sa is not None and r["avg"] < sa - 15:
                out.append({**base, "kind": "under", "advice": f"Scores {r['avg']:.0f} against {sa:.0f} for its system: review its instructions or model, or give its work to a stronger agent (an Evolution proposal measures a fix)."})
            elif r["n"] >= 5 and (r["bad"] or 0) / r["n"] >= 0.3:
                out.append({**base, "kind": "failing", "advice": f"{r['bad']} of {r['n']} runs failed for reasons of its own: see its diagnoses; a fix is an Evolution proposal."})
            elif r["tok"] and st and r["n"] >= 5 and r["tok"] > 2 * st and (sa is None or r["avg"] is None or r["avg"] <= sa):
                out.append({**base, "kind": "costly", "advice": f"{r['tok']:,.0f} tokens per run, over twice its system's median ({st:,.0f}), for no better score: tighten its instructions or route it to a cheaper model."})
            elif r["scored"] >= 5 and sa is not None and r["avg"] >= sa + 10:
                out.append({**base, "kind": "strong", "advice": f"Scores {r['avg']:.0f} against {sa:.0f} for its system: give it more of this work, or copy what it does into weaker agents."})
        rank = {"under": 0, "failing": 1, "costly": 2, "strong": 3}
        out.sort(key=lambda x: (rank[x["kind"]], -(x["runs"] or 0)))
        idle = self.db.q("""SELECT g.key, g.name FROM ac_agents g WHERE g.owner_id=? AND COALESCE(g.status,'') NOT IN ('gone','off')
                            AND NOT EXISTS (SELECT 1 FROM ac_runs a WHERE a.agent_key=g.key AND a.started>?) ORDER BY g.name""", (uid, since)) if self._has("ac_agents") else []
        models = []
        for r in self.db.q("""SELECT system, kind, model, COUNT(*) n, COUNT(score) scored, AVG(score) avg, AVG(NULLIF(tokens,0)) tok FROM ac_runs
                              WHERE owner_id=? AND started>? AND status!='running' AND model IS NOT NULL AND kind NOT IN ('experiment','earlier','cases','draft')
                              GROUP BY system, kind, model""", (uid, since)):
            models.append(dict(r))
        tips = []
        for (s, k) in {(m["system"], m["kind"]) for m in models}:
            g = [m for m in models if (m["system"], m["kind"]) == (s, k)]
            used = max(g, key=lambda m: m["n"])
            best = max((m for m in g if m["scored"] >= 3 and m["avg"] is not None), key=lambda m: m["avg"], default=None)
            if best and best["model"] != used["model"] and used["scored"] >= 3 and used["avg"] is not None and best["avg"] >= used["avg"] + 10:
                tips.append({"system": agent_core.SYSTEMS.get(s, s), "kind": k, "used": used["model"], "used_avg": round(used["avg"]), "used_n": used["n"],
                             "best": best["model"], "best_avg": round(best["avg"]), "best_n": best["scored"],
                             "advice": f"Most {k} work runs on {used['model']} (average {used['avg']:.0f}); {best['model']} scored {best['avg']:.0f} on {best['scored']} runs. "
                                       "Put it in your model pool (Workforce → Settings) so the router can pick it."})
        tips.sort(key=lambda t: -(t["best_avg"] - t["used_avg"]))
        return {"agents": out[:12], "models": tips[:6], "idle": len(idle), "idle_names": [r["name"] for r in idle[:8]]}

    # ------------------------------------------------------------------ spending
    def spend(self, uid, since):
        """Dollars since `since`: recorded where a run recorded its cost, else estimated at list price from its tokens (your model
        pool's price per million, or the router's guess); plan, terminal and local calls cost nothing per token and are counted
        apart. Per validated deliverable (a run scored VALID+ or a verified mission), like Analytics."""
        if not self._has("ac_runs"): return None
        from . import model_router
        from .analytics import VALID
        core = agent_core.get()
        pool = model_router.effective(core.pool(uid)["pool"]) if core else []
        short = lambda m: (m or "").partition(":")[2] or (m or "")
        def price(m):
            hit = next((p for p in pool if p["model"] == m or short(p["model"]) == short(m)), None)
            return hit["price"] if hit else model_router.guess(m if ":" in m else f"x:{m}")[1]
        tot = {"recorded_usd": 0.0, "estimated_usd": 0.0, "plan_tokens": 0, "unpriced_tokens": 0, "tokens": 0, "runs": 0}
        by = {}
        for r in self.db.q("""SELECT system, model, COUNT(*) n, COALESCE(SUM(tokens),0) tok, COALESCE(SUM(cost),0) usd,
                                     COALESCE(SUM(CASE WHEN cost IS NULL THEN tokens END),0) tok_nc FROM ac_runs
                              WHERE owner_id=? AND started>? AND status!='running' AND kind!='earlier' GROUP BY system, model""", (uid, since)):
            b = by.setdefault(r["system"], {"system": r["system"], "label": agent_core.SYSTEMS.get(r["system"], r["system"]), "runs": 0, "tokens": 0, "usd": 0.0, "estimated": 0.0})
            est = 0.0
            if r["tok_nc"]:
                if not r["model"]: tot["unpriced_tokens"] += r["tok_nc"]
                else:
                    pr = price(r["model"])
                    if pr: est = r["tok_nc"] * pr / 1e6
                    else: tot["plan_tokens"] += r["tok_nc"]
            tot["recorded_usd"] += r["usd"]; tot["estimated_usd"] += est; tot["tokens"] += r["tok"]; tot["runs"] += r["n"]
            b["runs"] += r["n"]; b["tokens"] += r["tok"]; b["usd"] += r["usd"] + est; b["estimated"] += est
        val = self.db.q("""SELECT COUNT(DISTINCT COALESCE(ref, CAST(id AS TEXT))) n FROM ac_runs WHERE owner_id=? AND started>? AND score>=?
                           AND system NOT IN ('missions','evolution')""", (uid, since, VALID), one=True)["n"] or 0
        if self._has("mx_missions"):
            val += self.db.q("SELECT COUNT(*) n FROM mx_missions WHERE user_id=? AND finished>? AND status='delivered' AND outcome='verified'", (uid, since), one=True)["n"] or 0
        usd = tot["recorded_usd"] + tot["estimated_usd"]
        return {**{k: round(v, 4) if isinstance(v, float) else v for k, v in tot.items()}, "usd": round(usd, 4), "validated": val, "valid_at": VALID,
                "usd_per_validated": round(usd / val, 4) if val and usd else None, "tokens_per_validated": round(tot["tokens"] / val) if val else None,
                "by_system": sorted(({**b, "usd": round(b["usd"], 4), "estimated": round(b["estimated"], 4)} for b in by.values()), key=lambda b: -b["tokens"])[:8],
                "basis": "Recorded dollars where a run recorded them; the rest at list price from your model pool. Plan and local calls have no per-token price."}

    @staticmethod
    def _alerts(uid):
        """The owner's alert settings and this week's threshold crossings (agent_core._threshold)."""
        c = agent_core.get()
        if not c: return None
        try: return {**c.alert_settings(uid), "recent": c.alerts(uid)}
        except Exception as e:  # noqa: BLE001 - the page shows the rest
            log.warning("g5 alerts: %s", e); return None

    def suggest_limits(self, uid, days=14):
        """Hard limits worth setting, from what was spent: a daily limit 1.5× the busiest day of the last `days`, for the whole
        account, the three busiest systems, and the two busiest teams and agents, where none is set. Suggestions only: setting
        one (or all of them) is your click."""
        if not self._has("ac_runs"): return []
        since = _now() - days * 86400
        have = {(L["scope"], L["key"]) for L in self.db.q("SELECT scope, key FROM ac_limits WHERE owner_id=?", (uid,))} if self._has("ac_limits") else set()
        cap = self.db.q("SELECT daily_tokens FROM ac_budget WHERE owner_id=?", (uid,), one=True) if self._has("ac_budget") else None
        rnd = lambda x: int(float(f"{x:.2g}")) if x >= 10 else int(x)
        def busiest(extra="", args=()):
            r = self.db.q(f"""SELECT MAX(t) m FROM (SELECT CAST(started / 86400 AS INTEGER) d, SUM(tokens) t FROM ac_runs WHERE owner_id=? AND started>? {extra}
                              GROUP BY d)""", (uid, since, *args), one=True)
            return (r or {}).get("m") or 0
        out = []
        top = busiest()
        if top and ("global", "*") not in have and not (cap and cap["daily_tokens"]):
            out.append({"scope": "global", "key": "*", "label": "Everything you run", "tokens": rnd(top * 1.5), "period": "day",
                        "why": f"Your busiest day of the last {days} used {top:,} tokens"})
        for r in self.db.q("""SELECT system, SUM(tokens) t FROM ac_runs WHERE owner_id=? AND started>? GROUP BY system ORDER BY t DESC LIMIT 3""", (uid, since)):
            m = busiest("AND system=?", (r["system"],))
            if m and ("system", r["system"]) not in have:
                out.append({"scope": "system", "key": r["system"], "label": agent_core.SYSTEMS.get(r["system"], r["system"]), "tokens": rnd(m * 1.5), "period": "day",
                            "why": f"Its busiest day of the last {days} used {m:,} tokens"})
        cols = self._cols("ac_runs")
        for scope, col in (("team", "team"), ("agent", "agent_key")):  # the review asked for team and agent limits too: the two busiest of each
            if col not in cols: continue
            for r in self.db.q(f"""SELECT {col} k, SUM(tokens) t FROM ac_runs WHERE owner_id=? AND started>? AND {col} IS NOT NULL AND {col}!=''
                                   GROUP BY {col} ORDER BY t DESC LIMIT 2""", (uid, since)):
                m = busiest(f"AND {col}=?", (r["k"],))
                if not m or (scope, r["k"]) in have: continue
                name = (self.db.q("SELECT name FROM ac_agents WHERE key=?", (r["k"],), one=True) or {}).get("name") if scope == "agent" and self._has("ac_agents") else None
                out.append({"scope": scope, "key": r["k"], "label": name or r["k"], "tokens": rnd(m * 1.5), "period": "day",
                            "why": f"{'Its' if scope == 'agent' else 'The team’s'} busiest day of the last {days} used {m:,} tokens"})
        return out

    # ------------------------------------------------------------------ Adaptive → Mission
    def guidance(self, uid, goal="", days=30, lessons=True, team=None):
        """What the loop learned, for a mission's planner (Mission Control's discovery, the Control Hub's Mission Intelligence and
        a Competition team lead's plan): failure classes to plan around (with their recovery), changes promoted and rolled back,
        changes measured but not decided, the best-scoring model per kind of work, and (lessons=True) the lessons of finished
        missions that share the goal's words. team ("comp:N"): failure classes and best models from that team's own runs.
        Records, not advice from a model. `refs` names each record used, so the next mission's evidence can point back at them."""
        since = _now() - days * 86400
        out = {"failures": [], "changes": [], "tested": [], "models": [], "lessons": [], "lines": [],
               "refs": {"failures": [], "proposals": [], "improvements": [], "lessons": []}}
        if self._has("io_diag"):
            own = team and "team" in self._cols("ac_runs")
            for r in self.db.q(("""SELECT d.cls, COUNT(*) n, MAX(d.recovery) fix FROM io_diag d JOIN ac_runs a ON a.id=d.run_id
                                   WHERE d.owner_id=? AND d.ts>? AND a.team=? GROUP BY d.cls ORDER BY n DESC LIMIT 4""" if own else
                                """SELECT cls, COUNT(*) n, MAX(recovery) fix FROM io_diag WHERE owner_id=? AND ts>? AND system IN ('missions','workforce','longtask','teams','swarm','control')
                                  GROUP BY cls ORDER BY n DESC LIMIT 4"""), (uid, since, team) if own else (uid, since)):
                out["failures"].append({"cls": r["cls"], "label": FAIL_LABEL.get(r["cls"], r["cls"]), "n": r["n"], "fix": r["fix"]})
        if self._has("ev_proposals"):
            for p in self.db.q("""SELECT id, title, target_name, status, evidence FROM ev_proposals WHERE user_id=? AND status IN ('promoted','rolled_back')
                                  AND updated>? ORDER BY updated DESC LIMIT 4""", (uid, since)):
                e = _j(p["evidence"], {}) or {}
                out["changes"].append({"id": p["id"], "title": p["title"], "target": p["target_name"], "status": p["status"],
                                       "before": e.get("baseline"), "after": e.get("candidate")})
            for p in self.db.q("""SELECT id, title, target_name, status, evidence FROM ev_proposals WHERE user_id=? AND tested>? AND evidence IS NOT NULL
                                  AND status NOT IN ('promoted','rolled_back') ORDER BY tested DESC LIMIT 3""", (uid, since)):
                e = _j(p["evidence"], {}) or {}
                if e.get("baseline") is None: continue
                out["tested"].append({"ref": f"ev:{p['id']}", "id": p["id"], "title": p["title"], "target": p["target_name"], "better": bool(e.get("verified")),
                                      "before": e.get("baseline"), "after": e.get("candidate")})
        if self._has("wf_improvements") and self._has("wf_agents"):
            for p in self.db.q("""SELECT i.id, i.change, i.status, i.result, a.name FROM wf_improvements i LEFT JOIN wf_agents a ON a.id=i.agent_id
                                  WHERE i.user_id=? AND i.trials>0 AND i.updated>? AND i.status IN ('better','not_better','promoted') ORDER BY i.updated DESC LIMIT 3""", (uid, since)):
                out["tested"].append({"ref": f"wfi:{p['id']}", "id": p["id"], "title": _clip(p["change"] or "Workforce improvement", 140), "target": p["name"],
                                      "better": p["status"] in ("better", "promoted"), "result": _clip(p["result"], 200), "status": p["status"]})
        if self._has("ac_runs"):
            best = {}
            mine = team and "team" in self._cols("ac_runs")
            for r in self.db.q("""SELECT system, model, AVG(score) a, COUNT(score) n FROM ac_runs WHERE owner_id=? AND started>? AND score IS NOT NULL AND model IS NOT NULL
                                  AND system IN ('missions','workforce','longtask','teams','control')""" + (" AND team=?" if mine else "") +
                               " GROUP BY system, model HAVING COUNT(score)>=3", (uid, since, team) if mine else (uid, since)):
                if r["system"] not in best or r["a"] > best[r["system"]]["avg"]: best[r["system"]] = {"system": r["system"], "model": r["model"], "avg": round(r["a"]), "n": r["n"]}
            out["models"] = list(best.values())
        if lessons and goal and self._has("mx_lessons"):
            words = set(re.findall(r"[a-z0-9]{4,}", goal.lower()))
            rows = self.db.q(f"SELECT id, mission_id, kind, text, outcome FROM mx_lessons WHERE user_id=? AND outcome IN ({','.join('?' * len(LESSONS_FOR_PLANNERS))}) ORDER BY id DESC LIMIT 400",
                             (uid, *LESSONS_FOR_PLANNERS))  # L5.2: verified lessons (and a promoted trial's) only; the rest are observations
            hit = sorted(((len(words & set(re.findall(r"[a-z0-9]{4,}", (x["text"] or "").lower()))), x) for x in rows), key=lambda t: -t[0])
            out["lessons"] = [dict(x) for k, x in hit if k >= 2][:3]
        # approved team knowledge too: competition lessons shared beyond their team (mining_knowledge.py) and verified Company
        # Knowledge records, matched on the goal's words like mission lessons: what the teams learned reaches the planner
        out["team_lessons"] = []
        if lessons and goal:
            words = set(re.findall(r"[a-z0-9]{4,}", goal.lower()))
            pool = []
            if self._has("mk_items"):
                pool += [("mk", x["id"], x["lesson"], x["scope"]) for x in self.db.q(
                    """SELECT id, lesson, scope, note_id, comp_id, by_user FROM mk_items WHERE user_id=? AND scope IN ('global_approved','subnet_shared') AND COALESCE(lesson,'')!=''
                       ORDER BY scope='global_approved' DESC, id DESC LIMIT 400""", (uid,)) if mk_trusted(self.db, x)]  # W6: a person's decision or a benchmark's evidence, not the model's say-so
            if self._has("kb_items"):
                pool += [("kb", x["id"], f"{x['title']}: {x['body']}", "verified") for x in self.db.q(
                    """SELECT id, title, body FROM kb_items WHERE user_id=? AND space='company' AND state='verified' AND status='kept' ORDER BY id DESC LIMIT 300""", (uid,))]
            hit = sorted(((len(words & set(re.findall(r"[a-z0-9]{4,}", (t or "").lower()))), (k, i, t, sc)) for k, i, t, sc in pool), key=lambda t: -t[0])
            out["team_lessons"] = [{"ref": f"{k}:{i}", "text": t, "scope": sc} for n, (k, i, t, sc) in hit if n >= 2][:3]
        R, L = out["refs"], out["lines"]
        R.setdefault("knowledge", [])
        for x in out["team_lessons"]:
            R["knowledge"].append(x["ref"])
            L.append(f"{'Verified company knowledge' if x['ref'].startswith('kb:') else 'Lesson a team shared'} [{x['ref']}]: {_clip(x['text'], 240)}")
        for f in out["failures"]:
            R["failures"].append(f["cls"]); L.append(f"{f['n']} recent run failure(s) of class '{f['label']}': {f['fix']}")
        for c in out["changes"]:
            R["proposals"].append(c["id"])
            L.append(f"{'Promoted' if c['status'] == 'promoted' else 'Rolled back'}: {c['title']} ({c['target']}"
                     + (f", {c['before']} → {c['after']} on its benchmark" if c["before"] is not None else "") + ")")
        for t in out["tested"]:
            (R["proposals"] if t["ref"].startswith("ev:") else R["improvements"]).append(t["id"])
            L.append(f"Measured, {'better' if t['better'] else 'not better'}: {t['title']} ({t['target'] or 'agent'}"
                     + (f", {t['before']} → {t['after']}" if t.get("before") is not None else f": {t['result']}" if t.get("result") else "") + ")")
        for m in out["models"]:
            L.append(f"Best-scoring model for {agent_core.SYSTEMS.get(m['system'], m['system'])} work: {m['model']} (average {m['avg']} over {m['n']} scored runs)")
        for x in out["lessons"]:
            R["lessons"].append(x["id"]); L.append(f"Lesson from mission #{x['mission_id']} ({x['outcome'] or 'unverified'}): {_clip(x['text'], 240)}")
        return out

    def guided(self, uid, mid, g, corr=None, key=None):
        """A planner took guidance: the Adaptive → Mission handoff, on the record with the refs it used. mid: a Mission Control
        mission (mx:N); corr and key: another planner's (the Control Hub's Mission Intelligence: comp:N, ctl:mi:<review>)."""
        corr = corr or f"mx:{mid}"
        R = g.get("refs") or {}
        self.emit(uid, "mission.guided", key or f"mx:{mid}:guided", corr=corr, ref=key.rsplit(":", 1)[0] if key else f"mx:{mid}",
                  payload={"lines": len(g.get("lines") or []), "failures": len(g.get("failures") or []), "changes": len(g.get("changes") or []),
                           "tested": len(g.get("tested") or []), "refs": {k: v for k, v in R.items() if v}}, status="done")
        kb = [int(r[3:]) for r in R.get("knowledge") or [] if r.startswith("kb:") and r[3:].isdigit()]
        if kb and self._has("kb_uses"):  # a planner reading verified company knowledge is a reuse of it (Company Knowledge counts kb_uses)
            now = _now()
            for i in kb:
                self.db.q("INSERT INTO kb_uses (user_id, item_id, ts, actor, label, query) VALUES (?,?,?,?,?,?)", (uid, i, now, "missions", "Mission planner", _clip(corr, 300)))
            self.db.q(f"UPDATE kb_items SET used=used+1, last_used=? WHERE user_id=? AND id IN ({','.join('?' * len(kb))})", (now, uid, *kb))

    def launched(self, uid, mid, engine, child, limit_tokens=None):
        """Mission Control launched mission mid's engine: correlate the child's runs to it and put its budget at the gateway."""
        key = {"workforce": f"wfm:{child}", "swarm": f"sws:{child}", "longtask": f"ia:{child}"}.get(engine)
        corr = f"mx:{mid}"
        if key and child: self.link(key, corr, uid)
        if limit_tokens:
            try: agent_core.get() and agent_core.get().set_limit(uid, "mission", corr, tokens=int(limit_tokens), period="total",
                                                                 label=f"Mission #{mid}", origin="mission budget", by="Mission Control")
            except Exception as e:  # noqa: BLE001 - the mission's own clock still watches its budget
                log.warning("orchestrator mission limit: %s", e)
        self.emit(uid, "mission.launched", f"{corr}:launched:{engine}:{child}", corr=corr, ref=key or corr,
                  payload={"engine": engine, "child": child, "limit_tokens": limit_tokens}, status="done")
        self.audit(uid, "Mission Control", "mission.launched", corr, f"{engine} {child or ''}".strip() + (f", hard limit {int(limit_tokens):,} tokens" if limit_tokens else ""), corr)

    def mission_budget(self, uid, mid, budget, price):
        """The mission's budget changed: its gateway limit (if it has one) follows, so raising it lets the work go on."""
        corr = f"mx:{mid}"
        if not (price and agent_core.get() is not None): return
        if not self.db.q("SELECT 1 FROM ac_limits WHERE owner_id=? AND scope='mission' AND key=? AND origin='mission budget'", (uid, corr), one=True): return
        agent_core.get().set_limit(uid, "mission", corr, tokens=int(budget / price * 1e6), period="total", label=f"Mission #{mid}", origin="mission budget", by="Mission Control")
        self.audit(uid, "Mission Control", "mission.limit_changed", corr, f"budget ${budget:.2f} → {int(budget / price * 1e6):,} tokens", corr)

    # ------------------------------------------------------------------ versioned datasets and reproducibility
    def snapshot(self, uid, kind, ref, name, cases):
        """The dataset's version for these exact cases: the existing one when the content hash matches, else the next version."""
        sha = _sha(cases)
        r = self.db.q("SELECT id, version, sha FROM io_datasets WHERE owner_id=? AND kind=? AND ref=? AND sha=?", (uid, kind, ref, sha), one=True)
        if r: return dict(r)
        v = (self.db.q("SELECT MAX(version) v FROM io_datasets WHERE owner_id=? AND kind=? AND ref=?", (uid, kind, ref), one=True)["v"] or 0) + 1
        self.db.q("INSERT OR IGNORE INTO io_datasets (owner_id, kind, ref, name, version, sha, cases, created) VALUES (?,?,?,?,?,?,?,?)",
                  (uid, kind, ref, _clip(name, 160), v, sha, json.dumps(cases), _now()))
        return dict(self.db.q("SELECT id, version, sha FROM io_datasets WHERE owner_id=? AND kind=? AND ref=? AND sha=?", (uid, kind, ref, sha), one=True))

    def reproduce(self, me, pid):
        """Recomputes a proposal's verdict from its stored trials with the evidence rule, and checks it was measured on one frozen
        dataset version with the same cases on both arms. Spends nothing."""
        from . import evolution as evo
        p = self.db.q("SELECT * FROM ev_proposals WHERE id=? AND user_id=?", (pid, me["id"]), one=True)
        if not p: raise HTTPException(404, "No such proposal of yours.")
        e = _j(p["evidence"], None)
        if not e: raise HTTPException(400, "It has no evidence yet.")
        checks = []
        if e.get("source") != "experiment":
            return {"reproducible": None, "checks": [{"ok": None, "text": "Recorded evidence (measured elsewhere): nothing stored here to recompute from"}], "evidence": e}
        rows = self.db.q("SELECT case_id, arm, score FROM ev_trials WHERE proposal_id=? AND run=?", (pid, e.get("run")))
        again = evo.evidence([{"case": r["case_id"], "arm": r["arm"], "score": r["score"]} for r in rows], {"margin": e.get("margin"), "min_cases": e.get("min_cases")})
        same = all(again.get(k) == e.get(k) for k in ("baseline", "candidate", "delta", "wins", "losses", "verified"))
        checks.append({"ok": same, "text": f"Verdict recomputed from {len(rows)} stored trials: {again['baseline']} → {again['candidate']}, "
                                           f"{'verified' if again['verified'] else 'not verified'}" + ("" if same else " (differs from the stored evidence)")})
        arms = {}
        for r in rows: arms.setdefault(r["arm"], set()).add(r["case_id"])
        both = arms.get("baseline", set()) == arms.get("candidate", set())
        checks.append({"ok": both, "text": "Baseline and candidate answered the same cases" if both else "The arms answered different cases"})
        ds = e.get("dataset_id") and self.db.q("SELECT * FROM io_datasets WHERE id=?", (e["dataset_id"],), one=True)
        if ds:
            ids = {c.get("id") for c in _j(ds["cases"], [])}
            ok = ds["sha"] == e.get("dataset_sha") and arms.get("baseline", set()) <= ids
            checks.append({"ok": ok, "text": f"Measured on dataset version {ds['version']} ({ds['sha']}), frozen with {len(ids)} cases" if ok
                                             else "The trials don't match the frozen dataset version"})
        else:
            checks.append({"ok": None, "text": "Measured before benchmark datasets were versioned: no frozen version to check against"})
        bad = [c for c in checks if c["ok"] is False]
        return {"reproducible": not bad, "checks": checks, "evidence": {k: e.get(k) for k in ("baseline", "candidate", "delta", "cases", "verified", "run", "dataset_version", "dataset_sha", "model")},
                "recomputed": {k: again.get(k) for k in ("baseline", "candidate", "delta", "cases", "verified")}}

    # ------------------------------------------------------------------ the retrieval benchmark
    @staticmethod
    def _probe(title, body):
        """A sentence from the item (8-24 words, not the title) as the query that should find it."""
        t = set(re.findall(r"[a-z0-9]+", (title or "").lower()))
        best = None
        for s in re.split(r"(?<=[.!?])\s+|\n+", body or ""):
            w = re.findall(r"[A-Za-z0-9][\w.-]*", s)
            if not 8 <= len(w) <= 40: continue
            novel = sum(1 for x in w if x.lower() not in t)
            if novel < 6: continue
            if not best or novel > best[0]: best = (novel, " ".join(w[:24]))
        return best and best[1]

    def retrieval_dataset(self, uid):
        """Known-item cases from the owner's kept items, a stable sample (by id hash), frozen as a dataset version."""
        if not self._has("kb_items"): return None, []
        items = self.db.q("SELECT id, version, title, body FROM kb_items WHERE user_id=? AND status='kept' AND LENGTH(COALESCE(body,''))>=120 ORDER BY id DESC LIMIT 2000", (uid,))
        items.sort(key=lambda k: hashlib.sha1(str(k["id"]).encode()).hexdigest())
        cases = []
        for k in items:
            q = self._probe(k["title"], k["body"])
            if q: cases.append({"id": f"kb:{k['id']}", "item": k["id"], "version": k["version"], "query": q})
            if len(cases) >= RB_CASES: break
        if not cases: return None, []
        return self.snapshot(uid, "retrieval", "known-item", "Known-item retrieval", cases), cases

    def run_retrieval(self, me, by=None):
        """Each case's query through the Knowledge Hub's own retrieval as you (log off): did the item come back in the top k?"""
        kb = getattr(self.hub, "knowledge", None) if self.hub is not None else None
        if kb is None: raise HTTPException(503, "The Knowledge Hub isn't running on this server.")
        uid, t0 = me["id"], _now()
        ds, cases = self.retrieval_dataset(uid)
        if not cases: raise HTTPException(400, "Not enough kept Knowledge Hub items with text to build a retrieval benchmark (each needs a sentence of 8+ words).")
        per, rr = [], 0.0
        for c in cases:
            try: refs = [h["ref"] for h in kb.retrieve(me, c["query"], RB_K, "page", internal=False, log_it=False)]
            except Exception as e:  # noqa: BLE001 - a case that errors is a miss with its reason
                refs, err = [], str(e)
            else: err = None
            rank = refs.index(c["id"]) + 1 if c["id"] in refs else None
            rr += 1 / rank if rank else 0
            why = None
            if not rank:
                cur = self.db.q("SELECT version FROM kb_items WHERE id=?", (c["item"],), one=True)
                idx = cur and self.db.q("SELECT 1 FROM kb_chunks WHERE item_id=? AND ver=? LIMIT 1", (c["item"], cur["version"]), one=True) if self._has("kb_chunks") else True
                why = (f"Retrieval failed: {_clip(err, 160)}" if err else "Not indexed: no passage of its current version" if not idx
                       else f"Ranked out of the top {RB_K}")
            per.append({"case": c["id"], "query": c["query"], "rank": rank, "why": why})
        n = len(per)
        hit = sum(1 for p in per if p["rank"])
        metrics = {"cases": n, f"recall@{RB_K}": round(hit / n, 3), "mrr": round(rr / n, 3), "not_indexed": sum(1 for p in per if (p["why"] or "").startswith("Not indexed")),
                   "ranked_out": sum(1 for p in per if (p["why"] or "").startswith("Ranked out")), "pass_line": RB_PASS, "k": RB_K,
                   "dataset_version": ds["version"], "dataset_sha": ds["sha"]}
        passed = hit / n >= RB_PASS
        self.db.q("INSERT INTO io_bench_runs (owner_id, dataset_id, ts, by_user, metrics, per_case, passed, ms) VALUES (?,?,?,?,?,?,?,?)",
                  (uid, ds["id"], _now(), by or me.get("username"), json.dumps(metrics), json.dumps(per), int(passed), int((_now() - t0) * 1000)))
        self.audit(uid, by or me.get("username") or "", "retrieval.benchmark", f"dataset:{ds['id']}",
                   f"v{ds['version']}: recall@{RB_K} {metrics[f'recall@{RB_K}']}, MRR {metrics['mrr']} → {'pass' if passed else 'fail'}")
        return self.retrieval_status(uid)

    def retrieval_status(self, uid):
        r = self.db.q("""SELECT b.*, d.version, d.sha FROM io_bench_runs b JOIN io_datasets d ON d.id=b.dataset_id WHERE b.owner_id=? AND d.kind='retrieval'
                         ORDER BY b.id DESC LIMIT 1""", (uid,), one=True)
        if not r: return None
        return {"ts": r["ts"], "by": r["by_user"], "passed": bool(r["passed"]), "metrics": _j(r["metrics"], {}), "ms": r["ms"],
                "misses": [p for p in _j(r["per_case"], []) if not p.get("rank")][:8], "version": r["version"], "sha": r["sha"]}

    def retrieval_due(self):
        """Once a day per owner of kept items: the known-item benchmark (no chat model; one embedding per query when an embeddings endpoint is set)."""
        if self.hub is None or getattr(self.hub, "knowledge", None) is None or not self._has("kb_items"): return 0
        n = 0
        for u in self.db.q("SELECT user_id, COUNT(*) c FROM kb_items WHERE status='kept' GROUP BY user_id HAVING c>=5"):
            last = self.db.q("""SELECT MAX(b.ts) t FROM io_bench_runs b JOIN io_datasets d ON d.id=b.dataset_id WHERE b.owner_id=? AND d.kind='retrieval'""",
                             (u["user_id"],), one=True)["t"]
            if last and last > _now() - RB_EVERY: continue
            me = self.db.q("SELECT * FROM users WHERE id=?", (u["user_id"],), one=True)
            if not me: continue
            try: self.run_retrieval(me, by="Orchestrator (daily)"); n += 1
            except HTTPException: pass
        return n

    # ------------------------------------------------------------------ what the Intelligence layers page reads
    def handoffs(self, uid, since):
        """Per event kind since `since`: done, waiting, retrying, dead, the processing lag (handled events only) and the last one."""
        got = {r["kind"]: r for r in self.db.q("""SELECT kind, SUM(status='done') done, SUM(status='pending' AND attempts=0) pending,
                   SUM(status='pending' AND attempts>0) retrying, SUM(status='dead') dead, AVG(CASE WHEN status='done' AND done>created THEN done-created END) lag,
                   MAX(created) last FROM io_events WHERE owner_id=? AND created>? GROUP BY kind""", (uid, since))}
        out = []
        for kind, (src, dst, what) in KINDS.items():
            r = got.get(kind) or {}
            out.append({"kind": kind, "from": src, "to": dst, "what": what, "step": STEP.get(kind), **{k: r.get(k) or 0 for k in ("done", "pending", "retrying", "dead")},
                        "lag_s": round(r["lag"]) if r.get("lag") is not None else None, "last": r.get("last"),
                        "state": "broken" if r.get("dead") else "retrying" if r.get("retrying") else "flowing" if r.get("done") else "quiet"})
        return out

    def edges(self, uid, since):
        """The loop's handoffs from the ledger: the one definition of flowing / partial / retrying / broken / quiet.
        broken: a dead letter, or nothing crossed while something reached the layer it leaves; partial: other kinds crossed but
        not the one that completes it; quiet: nothing reached that layer either."""
        K = {k["kind"]: k for k in self.handoffs(uid, since)}
        out = []
        for E in EDGES:
            ks = [K[k] for k in E["kinds"]]
            row = {**{k: v for k, v in E.items() if k != "kinds"}, "kinds": ks, **{f: sum(k[f] for k in ks) for f in ("done", "pending", "retrying", "dead")}}
            lags = [k["lag_s"] for k in ks if k["lag_s"] is not None]
            row.update(n=row["done"], lag_s=max(lags) if lags else None, last=max((k["last"] for k in ks if k["last"]), default=None))
            out.append(row)
        reached = {e["to"] for e in out if e["done"]}
        for e in out:
            needs = K[e["needs"]]["done"] if e.get("needs") else None
            e["state"] = ("broken" if e["dead"] else "retrying" if e["retrying"] else "partial" if e["done"] and needs == 0 else "flowing" if e["done"]
                          else "broken" if e["from"] in reached else "quiet")
            if e.get("feedback"):  # what the receiving side did: a plan that took nothing learned, or no plan at all to take it
                e["plans"] = self.plans(uid, since)
                if e["state"] == "broken" and not e["dead"]:
                    e["why"] = (f"{e['plans']} plan{'s' if e['plans'] != 1 else ''} this week took nothing the loop learned" if e["plans"] else
                                "No mission was planned this week, so nothing could take what the loop learned: start a mission in Mission Control, "
                                "or run Mission Intelligence on a Bittensor mission (Control Hub → Missions)")
        return out

    def plans(self, uid, since):
        """Mission plans made since: Mission Control discoveries, the Control Hub's Mission Intelligence reviews and Competition
        team leads' plans (mining_work._plan, the predefined missions' planner: it takes guidance too)."""
        n = 0
        if self._has("ctl_intel"): n += self.db.q("SELECT COUNT(*) n FROM ctl_intel WHERE user_id=? AND ts>?", (uid, since), one=True)["n"]
        if self._has("mx_missions"): n += self.db.q("SELECT COUNT(*) n FROM mx_missions WHERE user_id=? AND created>? AND discovery IS NOT NULL", (uid, since), one=True)["n"]
        if self._has("mw_runs") and self._has("mh_campaigns") and "kind" in self._cols("mw_runs"):
            n += self.db.q("""SELECT COUNT(*) n FROM mw_runs r JOIN mw_comps w ON w.id=r.comp_id JOIN mh_campaigns c ON c.id=w.campaign_id
                              WHERE c.user_id=? AND r.kind='plan' AND r.status='done' AND r.started>?""", (uid, since), one=True)["n"]
        return n

    def view(self, me):
        """The orchestrator's part of the Intelligence layers page, for the signed-in user."""
        uid, now = me["id"], _now()
        wk = now - 7 * 86400
        diag = [dict(r, label=FAIL_LABEL.get(r["cls"], r["cls"]), system_label=agent_core.SYSTEMS.get(r["system"], r["system"]))
                for r in self.db.q("""SELECT system, cls, recoverable, MAX(recovery) recovery, COUNT(*) n, MAX(evidence) example FROM io_diag WHERE owner_id=? AND ts>?
                                      GROUP BY system, cls ORDER BY n DESC LIMIT 12""", (uid, wk))]
        sbx = []
        if self._has("mw_sbx") and self._has("mw_comps") and self._has("mh_campaigns"):
            # the layers page's scope (Hubs._comps: open teams), so the class breakdown adds up to its Sandboxes figure
            comps = [r["id"] for r in self.db.q("SELECT w.id FROM mw_comps w JOIN mh_campaigns c ON c.id=w.campaign_id WHERE c.user_id=? AND w.status!='closed'", (uid,))]
            if comps:
                ph = ",".join("?" * len(comps))
                sbx = [dict(r, label=SBX_LABEL.get(r["cls"], r["cls"])) for r in self.db.q(
                    f"""SELECT d.cls, d.recoverable, MAX(d.recovery) recovery, COUNT(*) n, MAX(s.id) last_id, SUM(d.retried_as IS NOT NULL) retried
                        FROM io_sbx d JOIN mw_sbx s ON s.id=d.sbx_id WHERE s.comp_id IN ({ph}) AND s.started>? GROUP BY d.cls ORDER BY n DESC""", (*comps, wk))]
        dead = self.db.q("SELECT id, kind, corr, ref, src, dst, status, attempts, error, created, done FROM io_events WHERE owner_id=? AND status='dead' ORDER BY id DESC LIMIT 10", (uid,))
        lims = []
        if agent_core.get() is not None:
            try: lims = agent_core.get().limit_status(uid)
            except Exception as e:  # noqa: BLE001
                log.warning("orchestrator limits: %s", e)
        hits = self.db.q("SELECT COUNT(*) n FROM ac_limit_hits WHERE owner_id=? AND ts>?", (uid, wk), one=True)["n"] if self._has("ac_limit_hits") else 0
        mon = [dict(r) for r in self.db.q("""SELECT m.*, p.title, p.target_name, p.status, p.evidence, p.decision FROM io_monitor m JOIN ev_proposals p ON p.id=m.proposal_id
                                             WHERE m.owner_id=? ORDER BY m.promoted DESC LIMIT 12""", (uid,))] if self._has("ev_proposals") else []
        for m in mon:
            e = _j(m.pop("evidence"), {}) or {}
            m.update(exp_before=e.get("baseline"), exp_after=e.get("candidate"), cases=e.get("cases"), dataset_version=e.get("dataset_version"))
        hist = self.db.q("""SELECT ts, actor, action, target, detail FROM ev_audit WHERE user_id=? AND action IN ('proposal.promoted','proposal.rolled_back','promotion.held')
                            ORDER BY id DESC LIMIT 12""", (uid,)) if self._has("ev_audit") else []
        hist = list(hist) + list(self.db.q("""SELECT ts, actor, action, ref AS target, detail FROM io_audit WHERE owner_id=? AND action LIKE 'monitor.%' ORDER BY id DESC LIMIT 12""", (uid,)))
        hist.sort(key=lambda r: -r["ts"])
        compare = []
        if self._has("ac_runs"):
            compare = [dict(r, label=agent_core.SYSTEMS.get(r["system"], r["system"])) for r in self.db.q(
                """SELECT system, model, COUNT(*) runs, COUNT(score) scored, AVG(score) avg, SUM(status IN ('failed','error','lost')) failed,
                          AVG(CASE WHEN status='done' THEN NULLIF(tokens,0) END) tok, SUM(cost) usd FROM ac_runs WHERE owner_id=? AND started>? AND status!='running'
                          AND model IS NOT NULL GROUP BY system, model HAVING COUNT(*)>=2 ORDER BY runs DESC LIMIT 14""", (uid, wk))]
        steps = [k for k in self.handoffs(uid, wk) if k["step"]]
        return {"tick": self.last_tick, "tick_every": TICK, "error": self.last_error, "since": wk,
                "edges": self.edges(uid, wk), "steps": steps, "dead": [public_event(e) for e in dead], "coverage": self.coverage(uid, wk), "diagnosis": diag, "sandbox": sbx,
                "retrieval": self.retrieval_status(uid), "limits": lims, "alerts": self._alerts(uid), "blocked_7d": hits, "spend": self.spend(uid, wk), "suggested_limits": self.suggest_limits(uid), "monitor": mon, "history": hist[:14], "compare": compare,
                "signals": self.signals(uid)[:8], "proposals": self.proposals(uid),
                "policy": self.ev.policy(uid) if self.ev is not None else None, "recoverable": self.recoverable(uid, wk), "optimize": self.optimize(uid),
                "audit": self.db.q("SELECT ts, corr, actor, action, ref, detail FROM io_audit WHERE owner_id=? ORDER BY id DESC LIMIT 20", (uid,))}

    def events(self, uid, layer=None, kind=None, status=None, limit=30):
        """Recent handoff events of the owner's, newest first: into or out of a layer, of a kind, in a state."""
        w, a = ["owner_id=?"], [uid]
        if layer: w.append("(src=? OR dst=?)"); a += [layer, layer]
        if kind: w.append("kind=?"); a.append(kind)
        if status: w.append("status=?"); a.append(status)
        rows = self.db.q(f"""SELECT id, corr, kind, ref, src, dst, status, attempts, error, created, done FROM io_events WHERE {' AND '.join(w)}
                             ORDER BY created DESC, id DESC LIMIT ?""", (*a, max(1, min(200, limit))))
        return [public_event(r) for r in rows]

    def proposals(self, uid):
        """Open Evolution proposals and where their experiment would run (the Adaptive section's queue)."""
        if not self._has("ev_proposals"): return []
        out = []
        for p in self.db.q("""SELECT id, target_key, target_name, title, origin, status, risk, benchmark_id, evidence, note, created, tested FROM ev_proposals
                              WHERE user_id=? AND status IN ('proposed','testing','verified','not_better','failed') ORDER BY id DESC LIMIT 20""", (uid,)):
            k = p["target_key"] or ""
            where = ("evolution" if k.startswith("hub:") and p["risk"] == "config" else "workforce" if k.startswith("workforce:") else
                     "upgrade" if k.startswith("teams:") else "own page")
            e = _j(p["evidence"], {}) or {}
            trial = None  # a Workforce agent's proposal: its trial runs in the Workforce, whose state decides what's next
            if where == "workforce" and k[10:].isdigit() and self._has("wf_improvements"):
                t = self.db.q("SELECT id, status FROM wf_improvements WHERE user_id=? AND agent_id=? ORDER BY updated DESC LIMIT 1", (uid, int(k[10:])), one=True)
                trial = dict(t) if t else None
            out.append({**{x: p[x] for x in ("id", "target_key", "target_name", "title", "origin", "status", "risk", "note", "created", "tested")}, "trial": trial,
                        "runs_in": where, "benchmark": bool(p["benchmark_id"]), "baseline": e.get("baseline"), "candidate": e.get("candidate"),
                        "cases": e.get("cases"), "dataset_version": e.get("dataset_version")})
        return out

    def trace(self, uid, corr):
        """Everything correlated to corr: its runs across systems, its handoff events and its audit."""
        cols = self._cols("ac_runs") if self._has("ac_runs") else set()
        runs = self.db.q("""SELECT r.id, r.system, r.kind, r.ref, r.status, r.model, r.tokens, r.score, r.error, r.started, r.finished, e.state eval_state, e.reason eval_reason,
                                   e.basis eval_basis, e.source eval_source
                            FROM ac_runs r LEFT JOIN io_evals e ON e.run_id=r.id WHERE r.owner_id=? AND r.corr=? ORDER BY r.id LIMIT 300""", (uid, corr)) if "corr" in cols else []
        for r in runs:  # every shown score names what it rests on (IC-11 guarantee 2): a row from before L5.1 gets its kind on read
            src = r.pop("eval_source", None)
            if not r.get("eval_basis") and (r.get("eval_state") in ("scored", "reviewed") or r.get("score") is not None):
                r["eval_basis"] = self._basis(r["system"], r["kind"], r["ref"], r.get("eval_state") if r.get("eval_state") == "reviewed" else "scored", corr, src, r.get("score"))
        ev = self.db.q("SELECT id, corr, kind, src, dst, status, attempts, error, result, created, done FROM io_events WHERE owner_id=? AND corr=? ORDER BY created, id", (uid, corr))
        links = self.db.q("SELECT ref FROM io_links WHERE corr=? AND owner_id=?", (corr, uid))
        return {"corr": corr, "runs": runs, "events": [public_event(e) for e in ev], "children": [r["ref"] for r in links],
                "audit": self.db.q("SELECT ts, actor, action, ref, detail FROM io_audit WHERE owner_id=? AND corr=? ORDER BY id LIMIT 100", (uid, corr))}


# ---------- module level: no-ops until main.py calls init(), so a system works the same without the orchestrator ----------
_orc = None
EFFECTS = None  # D4.3: callable(event, payload) → result, registered by Mission Control for mission.effect events


class Busy(Exception):
    """A handler couldn't take what it needs (a mission's lease) right now: process() retries it shortly, without an attempt."""


BUSY_WAIT = 5


def register_effects(fn):
    global EFFECTS
    EFFECTS = fn

def init(db, ov=None, hub=None, evolution=None, work=None):
    global _orc
    _orc = Orchestrator(db, ov, hub, evolution, work)
    return _orc

def get(): return _orc

def _risk_out(r):
    out = dict(r)
    for k in ("evidence", "verification", "impact"):
        try: out[k] = json.loads(out[k]) if out.get(k) else None
        except (TypeError, ValueError): pass
    out["critical"] = bool(out.get("critical"))
    return out


def _safe(name, *a, **kw):
    if _orc is None: return None
    try: return getattr(_orc, name)(*a, **kw)
    except Exception as e:  # noqa: BLE001 - the orchestrator never stops the work it watches
        log.warning("orchestrator %s: %s", name, e)
        return None

# ---------- G5-5 L5.2: verified-only knowledge (G-31, T-10) ----------
# A mission's lesson reaches a planner only when its mission was verified (missions.outcome(): every acceptance criterion met,
# from per-criterion results, never an agent's say-so). Every other lesson is an observation: people still see it (Learning →
# Lessons, the "try" recall), planners don't (guidance, mission discovery, and recall by an engine or agent).
LESSON_VERIFIED = "verified"
# Decided under the Owner's delegation of 2026-11-13 15:33 UTC (amends C2-2; D4.4's rule for a mission's own lessons is unchanged):
# a promoted trial that answered a mission's measured gap leaves one lesson planners also receive. It is a technical result, never
# a verified mission. When that promotion is rolled back the lesson becomes an observation again.
LESSON_TRIAL = "trial_verified"
LESSON_TRIAL_WITHDRAWN = "trial_rolled_back"
# G5 W6 (learning loop): a lesson written from a comparable benchmark on the team's frozen release whose score rests on a finished
# measuring job (missions._ev_bench valid: release + evidence_ref). A technical result, never a verified mission or a competition result.
LESSON_BENCH = "bench_verified"
LESSONS_FOR_PLANNERS = (LESSON_VERIFIED, LESSON_TRIAL, LESSON_BENCH)  # the one list: the rule below and both SQL filters (guidance, mission discovery) read it
def lesson_for_planners(outcome): return (outcome or "") in LESSONS_FOR_PLANNERS

KM_AUTO = "Knowledge Manager"  # mk_items.by_user of an entry only the model classified: nobody decided it
def bench_backed(db, comp, task):
    """True when a comparable benchmark row of this team's task carries an evidence_ref (a finished sandbox run or measuring job)."""
    try:
        return bool(task) and bool(db.q("SELECT 1 FROM mw_bench WHERE comp_id=? AND task_id=? AND comparable=1 AND COALESCE(evidence_ref,'')!='' LIMIT 1", (comp, task), one=True))
    except Exception: return False  # noqa: BLE001 - no benchmark table on this server: nothing is backed
def mk_trusted(db, k):
    """G5 W6: a team's shared lesson (mk_items row) is planning knowledge only when a person decided it (approved, shared or edited it:
    by_user is a login, not the Knowledge Manager) or the note it came from rests on a benchmark with an evidence_ref. A scope the
    model alone chose, on an agent's own note, is an unverified claim: people still see it, planners don't."""
    if k["scope"] == "restricted": return False
    if (k["by_user"] or KM_AUTO) != KM_AUTO: return True
    n = db.q("SELECT task_id FROM mw_notes WHERE id=?", (k["note_id"],), one=True)
    return bench_backed(db, k["comp_id"], n["task_id"] if n else None)

def launched(uid, mid, engine, child, limit_tokens=None): return _safe("launched", uid, mid, engine, child, limit_tokens)
def guidance(uid, goal="", lessons=True, team=None): return _safe("guidance", uid, goal, lessons=lessons, team=team)
def risk_upsert(uid, rkey, evidence=None, **f): return _safe("risk_upsert", uid, rkey, evidence, **f)
def risk_resolve(uid, rkey, verification): return _safe("risk_resolve", uid, rkey, verification)
def risks(uid, mission=None, status=None, org=False, source=None, scope=None):
    return _safe("risks", uid, mission, status, source=source, scope=scope, org=org) or []
def approval_consume(uid, rkey): return _safe("approval_consume", uid, rkey)
def guided(uid, mid, g, corr=None, key=None): return _safe("guided", uid, mid, g, corr, key)
def snapshot(uid, kind, ref, name, cases): return _safe("snapshot", uid, kind, ref, name, cases)
def mission_budget(uid, mid, budget, price): return _safe("mission_budget", uid, mid, budget, price)
def emit(owner, kind, key, corr=None, ref=None, payload=None, status="pending", at=None):  # D4.3: None on an error or before init (read back by key)
    return _safe("emit", owner, kind, key, corr=corr, ref=ref, payload=payload, status=status, at=at)


def build(db, require, ov=None, hub=None, evolution=None, work=None):
    r = APIRouter(prefix="/api/g5")
    o = init(db, ov, hub, evolution, work)
    r.state = {"orchestrator": o}

    def me_(req):
        me = require(req)
        o._gate(me)
        return me

    @r.get("")
    def view(req: Request): return o.view(me_(req))

    @r.get("/trace")
    def trace(corr: str, req: Request): return o.trace(me_(req)["id"], corr[:80])

    @r.get("/events")
    def events(req: Request, layer: str | None = None, kind: str | None = None, status: str | None = None, limit: int = 30):
        return o.events(me_(req)["id"], (layer or "")[:20] or None, (kind or "")[:40] or None, (status or "")[:12] or None, limit)

    @r.post("/tick")
    def tick(req: Request):
        me = me_(req)
        if me.get("role") != "admin": raise HTTPException(403, "Administrators only.")
        return o.tick()

    @r.post("/events/{eid}/retry")
    def retry(eid: int, req: Request): return o.retry_event(me_(req), eid)

    @r.post("/runs/{rid}/recover")
    def recover(rid: int, req: Request): return o.recover(me_(req), rid)

    @r.post("/sandbox/{sid}/retry")
    def sbx_retry(sid: int, req: Request): return o.retry_sandbox(me_(req), sid)

    @r.get("/guidance")
    def guidance_(req: Request, goal: str = ""): return o.guidance(me_(req)["id"], goal[:400])

    @r.get("/taxonomy")
    def taxonomy_(req: Request, days: int = 7): return o.taxonomy(me_(req)["id"], max(1, min(int(days), 90)))

    @r.get("/risks")
    def risks_(req: Request, mission: str | None = None, status: str | None = None, source: str | None = None, scope: str | None = None):
        me = me_(req)
        return {"risks": o.risks(me["id"], (mission or "")[:40] or None, status if status in ("open", "accepted", "resolved") else None,
                                 source=source if source in RISK_SOURCES else None, scope=scope if scope in RISK_SCOPES else None,
                                 org=me.get("role") == "admin")}

    @r.post("/risks/{rid}/accept")
    def risk_accept_(rid: int, req: Request): return o.risk_accept(me_(req), rid)

    class VerifyIn(BaseModel):
        note: str = Field("", max_length=500)

    @r.post("/risks/{rid}/verify")
    def risk_verify_(rid: int, b: VerifyIn, req: Request): return o.risk_verify(me_(req), rid, b.note)

    class ApproveIn(BaseModel):
        action: str = Field("", max_length=200)
        payload_sha: str | None = Field(None, max_length=64)

    @r.post("/risks/{rid}/approve")
    def risk_approve_(rid: int, b: ApproveIn, req: Request): return o.risk_approve(me_(req), rid, b.action, b.payload_sha)

    @r.post("/proposals/{pid}/approve")
    def approve(pid: int, req: Request): return o.approve_experiment(me_(req), pid)

    @r.get("/proposals/{pid}/reproduce")
    def reproduce(pid: int, req: Request): return o.reproduce(me_(req), pid)

    @r.post("/retrieval/run")
    def retrieval(req: Request): return o.run_retrieval(me_(req))

    @r.get("/limits")
    def limits(req: Request):
        me = me_(req)
        c = agent_core.get()
        return {"limits": c.limit_status(me["id"]) if c else [], "scopes": agent_core.SCOPES,
                "alerts": {**c.alert_settings(me["id"]), "recent": c.alerts(me["id"])} if c else None}

    @r.put("/limits")
    def set_limit(b: LimitIn, req: Request):
        me = me_(req)
        if agent_core.get() is None: raise HTTPException(503, "The agent core isn't running.")
        if not b.tokens and not b.per_call: raise HTTPException(400, "Give a token limit, a per-call limit or both.")
        try: L = agent_core.get().set_limit(me["id"], b.scope, b.key, b.tokens, b.period, b.per_call, b.label, "manual", me["username"], b.warn_pct, b.mode)
        except ValueError as e: raise HTTPException(400, str(e))
        o.audit(me["id"], me["username"], "limit.set", f"{b.scope}:{L['key']}", f"{b.tokens or '–'} tokens {b.period}, per call {b.per_call or '–'}, "
                f"{'alert only' if b.mode == 'alert' else 'hard stop'}, warn at {b.warn_pct or 'default'}%")
        return {"limits": agent_core.get().limit_status(me["id"])}

    @r.put("/alerts")
    def set_alerts(b: AlertsIn, req: Request):
        me = me_(req)
        if agent_core.get() is None: raise HTTPException(503, "The agent core isn't running.")
        try: out = agent_core.get().set_alert_settings(me["id"], b.warn_pct, b.notify, me["username"])
        except ValueError as e: raise HTTPException(400, str(e))
        o.audit(me["id"], me["username"], "alerts.set", "budget", f"warn at {out['warn_pct']}%, push {'on' if out['notify'] else 'off'}")
        return {"limits": agent_core.get().limit_status(me["id"]), "alerts": {**out, "recent": agent_core.get().alerts(me["id"])}}

    @r.get("/unmetered")
    def unmetered(req: Request):
        me = me_(req)
        return {"runs": agent_core.get().unmetered_runs(me["id"]) if agent_core.get() else [],
                "provisional": agent_core.get().provisional_runs(me["id"]) if agent_core.get() else []}  # D-036: "estimated, unverified"

    @r.get("/reservations")
    def reservations(req: Request, days: int = 7):
        """Milestone 3: this owner's budget reservations, read-only: held now, and estimated against actual for the settled ones
        (overruns: calls that used more than they reserved), released, charged and unmetered (an unknown outcome)."""
        me = me_(req)
        if agent_core.get() is None: return {"by_state": {}, "held": []}
        held = agent_core.get().db.q("""SELECT id, run_id, model, estimate, bound, created, expires FROM ac_reservations
                                        WHERE owner_id=? AND state='held' ORDER BY id DESC LIMIT 100""", (me["id"],))
        return {"by_state": agent_core.get().reservations(me["id"], max(1, min(int(days), 90))), "held": held}

    @r.post("/unmetered/{rid}")
    def estimate(rid: int, b: EstimateIn, req: Request):
        me = me_(req)
        if agent_core.get() is None: raise HTTPException(503, "The agent core isn't running.")
        try: r = agent_core.get().estimate(me["id"], rid, b.tokens, me["username"], b.note)
        except ValueError as e: raise HTTPException(400, str(e))
        except LookupError as e: raise HTTPException(404, str(e))
        if r.get("path") != "correct":  # a D-036 correction is audited by the core, with the old figure
            o.audit(me["id"], me["username"], "metering.estimate", f"run:{rid}", f"{b.tokens} tokens estimated (D-025): {b.note[:200]}")
        return {"run": r, "runs": agent_core.get().unmetered_runs(me["id"]), "provisional": agent_core.get().provisional_runs(me["id"])}

    @r.delete("/limits/{lid}")
    def drop_limit(lid: int, req: Request):
        me = me_(req)
        if not agent_core.get() or not agent_core.get().drop_limit(me["id"], lid): raise HTTPException(404, "No such limit of yours.")
        o.audit(me["id"], me["username"], "limit.removed", f"limit:{lid}")
        return {"limits": agent_core.get().limit_status(me["id"])}

    return r
