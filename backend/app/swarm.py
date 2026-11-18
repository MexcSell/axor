"""Agent Swarm (AXoR G5): the collaborative execution engine. A Swarm Controller turns a mission into contracts for a small
swarm of the user's Workforce agents, picks how many agents and which swarm pattern the mission needs, schedules the contracts
over their dependencies, lets the agents talk through controlled interfaces, checks every contract independently, reassigns
failed work and replans when the agents find something that changes the plan. Built from the "Agent Swarm in AXoR G5" spec
(build order: controller, task decomposition and assignment, agent-to-agent communication, shared mission state, monitoring,
evaluation and recovery, adaptive formation, swarm optimization); "first prove that a small swarm of 3-5 agents can
consistently complete a real mission": a swarm here never has more than MAX_AGENTS agents.

What it reuses, and doesn't rebuild:
- The agents are the user's Workforce (workforce.py): their instructions, versions, tool grants and team. The Workforce's CEO
  -> leads -> specialists pipeline stays the hierarchical engine of its own; a swarm forms a temporary team from the same people.
- An agent's work runs in the Workforce's tool loop (Workforce._loop: routing over the shared model pool, grant checks,
  spans, the agent core's ledger). Swarm subclasses Workforce only as that runtime: its bookkeeping (events, runs, spans,
  tokens, cancel checks) writes to the sw_ tables, so nothing of a swarm lands in a Workforce mission.

What the swarm adds:
- Swarm Controller (CONTROLLER): one structured call decides the size (one agent, a small team, a swarm of 3-5), the pattern,
  and the contracts. Code holds it to the caps whatever it says (contracts, distinct agents, competitive contracts, a DAG).
- Five patterns and the hybrid (PATTERNS), each a concrete policy, not a label: who may message whom (none, up to the
  controller, peers), whether competitive contracts are allowed, whether the controller replans mid-flight, and whether a
  failed contract is reassigned inside the agent's own team (hierarchical) or to whoever fits best.
- Task contracts (sw_contracts) in the spec's shape: task_id, mission_id, assigned_agent, objective, deadline, budget_limit,
  status, deliverables, plus depends. budget_limit is enforced during the work: every model call of the contract is metered
  (_Meter) and the next call past the limit stops it; a contract attempt also has a time limit (CONTRACT_SECS) and the
  swarm's deadline.
- Communication: delegation (the contracts), message passing (send_message / read_messages, sw_messages, addressed to one
  agent, the controller or everyone, as the pattern allows), a shared blackboard (read_blackboard: every contract's state and
  hand-off, and the findings filed so far) and event streaming (sw_events; an agent with unread messages is told so in its
  next tool result).
- Evaluation and recovery: an evaluator (the Workforce's Chief Evaluator, on another model than the worker when the pool has
  one) checks each contract against its objective and deliverables; a competitive contract's attempts are compared blind.
  Failed work is reassigned to another agent with the evaluator's note (at most MAX_ATTEMPTS attempts per contract).
- Adaptive formation: in the adaptive, hierarchical and hybrid patterns, a requirement or blocker an agent sends to the
  controller, or a contract that failed for good, makes the controller revise, drop or add contracts that haven't started.
- Swarm optimization: each finished swarm is a record (pattern, size, score, tokens, time). The controller sees how its
  patterns did on similar earlier swarms, and code switches a pick that did clearly worse (advise), as Mission Control does
  for its engines; agents' contract scores rank who gets work and who takes over failed work.

Governance: agents only read and draft (the Workforce's RULES); nothing is deployed, paid or posted. The swarm has a token
budget and an optional deadline; it stops starting contracts at EXEC_SHARE of the budget so the evaluation and the report fit.
Mission Control runs missions on it as the "swarm" engine (missions.py) and verifies the result independently on top.
"""
import json, logging, math, os, random, threading, time
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import agent_core, workforce
from .llm import LLMError
from .agents import _schema
from .workforce import Cancelled, RULES, SUBMIT_WORK, TEAM_NAME, _clip, _compact, _flat, _summary, _words

log = logging.getLogger("swarm")
ENABLED = os.getenv("SWARM", "1") == "1"
BUDGETS = workforce.BUDGETS            # token budgets (Mission Control fits a mission's dollars into one of them)
MAX_CONTRACTS = 8
MAX_AGENTS = 5                         # distinct agents in one swarm: the spec's "small swarm of 3-5 agents"
SLOTS = 4                              # agents working at once in one swarm
CONTENDERS = 3                         # attempts at most on one competitive contract
MAX_COMPETE = 2                        # competitive contracts at most per swarm
MAX_ATTEMPTS = 2                       # attempts per contract: the first and one reassignment
ADAPTS = 3                             # controller replans at most per swarm
SENDS = 4                              # messages one agent may send in one attempt
LOOKUPS = 4                            # tool lookups per attempt (blackboard and inbox reads count)
CONTRACT_SECS = 900                    # one attempt's time limit
MIN_LIMIT = 6000                       # smallest contract budget
EXEC_SHARE = 0.75                      # contracts stop starting at this share of the budget
PASS = 60                              # a competitive winner below this hasn't met the contract
WORKERS = 3                            # swarms at once on the server
ACTIVE_PER_USER = 3
MAX_SWARMS = 200                       # kept per user
EVENT_KEEP = 800
SIMILAR, NEAREST, PRIOR, PRIOR_WEIGHT, MIN_RUNS, GAP = 0.15, 12, 50, 2, 3, 25  # the pattern track record (see record/advise)
SIZES = {"solo": ("One agent", 1, 1), "team": ("Small team", 2, 3), "swarm": ("Swarm", 3, MAX_AGENTS)}
STATUSES = ("queued", "running", "done", "failed", "cancelled")

# talk: who an agent may message (none: work alone, reading the blackboard; up: the controller only; peers: anyone in the swarm)
PATTERNS = {
    "hierarchical": {"label": "Hierarchical", "icon": "group", "talk": "up", "compete": False, "adapt": True, "same_team": True,
                     "about": "The controller is accountable for the plan; agents report blockers and new requirements up to it, and failed "
                              "work is reassigned inside the agent's own team.",
                     "best": "Large missions with clear responsibilities."},
    "collaborative": {"label": "Collaborative", "icon": "chat", "talk": "peers", "compete": False, "adapt": False, "same_team": False,
                      "about": "Agents message each other directly (findings, requests, answers) through the swarm's message bus while they work.",
                      "best": "Research, brainstorming and complex problem-solving."},
    "parallel": {"label": "Parallel", "icon": "columns", "talk": "none", "compete": False, "adapt": False, "same_team": False,
                 "about": "Independent contracts run at the same time; agents don't message, they read the blackboard.",
                 "best": "Data processing, benchmarking and large-scale research."},
    "competitive": {"label": "Competitive", "icon": "trophy", "talk": "none", "compete": True, "adapt": False, "same_team": False,
                    "about": "Several agents attempt the same contract independently; an evaluator compares the attempts blind and keeps the best.",
                    "best": "Optimization and finding the strongest solution."},
    "adaptive": {"label": "Adaptive", "icon": "cycle", "talk": "up", "compete": False, "adapt": True, "same_team": False,
                 "about": "The controller revises, drops and adds contracts as agents report new requirements or work fails; failed work goes "
                          "to whoever fits best.",
                 "best": "Changing missions."},
    "hybrid": {"label": "Hybrid", "icon": "sparkle", "talk": "peers", "compete": True, "adapt": True, "same_team": False,
               "about": "The recommended mix: the controller stays accountable, agents collaborate as peers, independent contracts run in "
                        "parallel, key contracts can be competitive, and the plan adapts.",
               "best": "Most real missions."},
}
KINDS = ("finding", "request", "answer", "requirement", "blocker")


def _str(desc=""): return {"type": "string", **({"description": desc} if desc else {})}
def _arr(items, desc=""): return {"type": "array", "items": items, **({"description": desc} if desc else {})}
def _obj(props): return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}
def _j(x): return json.dumps(x, separators=(",", ":"), default=str, ensure_ascii=False)
def _l(s, d):
    try: return json.loads(s) if s else d
    except (TypeError, ValueError): return d
def _iso(ts): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)) if ts else None


class Overdue(Cancelled):
    """The attempt's time is up (its own limit, or the swarm's deadline)."""

class OverBudget(Cancelled):
    """The contract's budget_limit is spent."""

class Stop(Exception):
    pass


# ---------- the track record (swarm optimization) ----------
def _jaccard(a, b): return len(a & b) / len(a | b) if a and b else 0.0

def record(rows, want):
    """{"similar": n, "patterns": {p: {...}}, "sizes": {s: {...}}} over the finished swarms in `rows` (dicts with title, goal,
    pattern, size, score, tokens, started, finished) most like the words `want`; scores shrunk towards PRIOR."""
    near = sorted(((_jaccard(want, _words(f"{r.get('title') or ''} {r.get('goal') or ''}")), r) for r in rows), key=lambda x: -x[0])
    near = [r for s, r in near if s >= SIMILAR and r.get("score") is not None][:NEAREST]
    return {"similar": len(near), "patterns": _group(near, "pattern"), "sizes": _group(near, "size")}

def _group(rows, key):
    out = {}
    for r in rows:
        if not r.get(key): continue
        e = out.setdefault(r[key], {"n": 0, "sum": 0, "tokens": 0, "secs": 0.0})
        e["n"] += 1; e["sum"] += r["score"]; e["tokens"] += r.get("tokens") or 0
        if r.get("started") and r.get("finished"): e["secs"] += r["finished"] - r["started"]
    for e in out.values():  # avg: what the swarms scored; score: shrunk towards PRIOR, what advise() and the controller weigh
        e["avg"] = round(e["sum"] / e["n"])
        e["score"] = round((PRIOR * PRIOR_WEIGHT + e.pop("sum")) / (PRIOR_WEIGHT + e["n"]))
        e["tokens"] = round(e["tokens"] / e["n"])
        e["minutes"] = round(e.pop("secs") / e["n"] / 60, 1)
    return out

def advise(rec, pick, fixed=False):
    """(pattern, why or None): `pick`, or a pattern that clearly did better on similar earlier swarms."""
    pats = rec["patterns"]
    mine = pats.get(pick)
    if fixed or not mine or mine["n"] < MIN_RUNS: return pick, None
    best = max(((k, e) for k, e in pats.items() if k != pick and e["n"] >= MIN_RUNS), key=lambda x: x[1]["score"], default=None)
    if not best or best[1]["score"] - mine["score"] < GAP: return pick, None
    k, e = best
    return k, (f"on {rec['similar']} similar earlier swarms, {PATTERNS[k]['label'].lower()} scored {e['score']}/100 over {e['n']} "
               f"and {PATTERNS[pick]['label'].lower()} {mine['score']}/100 over {mine['n']}")

def record_lines(rec):
    if not rec["patterns"]: return ""
    rows = [f"- {PATTERNS.get(k, {}).get('label', k)} ({k}): {e['n']} swarm(s), score {e['score']}/100, about {e['tokens']:,} tokens and "
            f"{e['minutes']:.0f} min each" for k, e in sorted(rec["patterns"].items(), key=lambda x: -x[1]["score"])]
    rows += [f"- size {k}: {e['n']} swarm(s), score {e['score']}/100" for k, e in sorted(rec["sizes"].items(), key=lambda x: -x[1]["score"])]
    return "\n<track_record>\nHow the user's earlier swarms on goals like this one went:\n" + "\n".join(rows) + "\n</track_record>"


# ---------- the metered model (a contract's budget_limit, enforced during the work) ----------
class _LLM:
    def __init__(self, llm, tl): self._llm, self._tl = llm, tl
    def __getattr__(self, k): return getattr(self._llm, k)
    def completer(self, choice, effort="medium"):
        complete, used = self._llm.completer(choice, effort)
        def metered(system, tools, messages):
            out = complete(system, tools, messages)
            meter = getattr(self._tl, "meter", None)
            if meter is not None: meter[0] += out[2] or 0
            return out
        return metered, used

class _Cache(dict):
    """Tool results the swarm's agents share (one lookup serves them all), without the unread-message notice meant for one agent."""
    def __setitem__(self, k, v):
        super().__setitem__(k, {a: b for a, b in v.items() if a != "_swarm"} if isinstance(v, dict) else v)

class _Meter:
    """The hub as the Workforce's tool loop sees it, with each contract's model calls counted on the thread that runs it."""
    def __init__(self, hub, tl): self._hub, self.llm = hub, _LLM(hub.llm, tl)
    def __getattr__(self, k): return getattr(self._hub, k)


# ---------- prompts ----------
CONTROLLER_SYSTEM = """You are the Swarm Controller of the user's AXoR Agent Swarm: you turn a mission into contracts for a \
temporary team of the user's Workforce agents and coordinate them. AXoR is an app for Bittensor subnets.

{rules}

First decide how many agents the mission needs: one agent (solo) when one careful piece of work settles it; a small team \
(team, 2-3 agents) for two or three distinct parts; a swarm (3-{max_agents} agents) only for several independent workstreams or \
mixed specialists. More agents do not mean better results: each one adds tokens, duplicated work, messages and conflicting \
answers.

Then pick the swarm pattern:
{patterns}

Then write the contracts (at most {max_contracts}). A contract is one agent's piece of the mission: a title, an objective, the \
deliverables a reviewer can check from the work alone, the contracts it depends on (keys of earlier contracts only; the rest \
run at the same time), the agent who fits it best by job and track record, and its share of the budget in percent. A \
competitive contract (competitive and hybrid patterns only, at most {compete}) goes to 2-3 contenders, the agent among them, \
who work independently; an evaluator keeps the best attempt. Use it only where the strongest of several attempts is worth \
paying for. Weigh the track record when there is one: it is how the user's earlier swarms on similar goals went."""

WORK_SYSTEM = """You are {name}, the {title} in the user's AXoR Workforce, working in an agent swarm: a few agents each \
fulfil one contract of a mission, coordinated by the Swarm Controller.

{rules}

How the swarm works: {talk} read_blackboard shows every contract's state and the findings filed so far. Use your tools only for \
data you lack (at most {calls} lookups; reading the blackboard or your messages counts). Your contract has a token budget and \
a time limit: work stops when either runs out. Then call submit_work once: the deliverable (under 350 words, lead with the \
result) that meets every deliverable of your contract, a summary the swarm can act on, findings (each a claim with its \
evidence and your confidence; risks and open questions too), and the memories you used (none: an empty list).

<role>
{instructions}
</role>"""

TALK = {
    "none": "you work on your own: there is no messaging in this pattern.",
    "up": "send_message reaches the Swarm Controller only: send it a requirement when you find something that changes what other "
          "contracts must do, or a blocker when you can't go on; it may change the plan. read_messages shows what it sent you.",
    "peers": "send_message reaches one agent of the swarm, everyone (all) or the Swarm Controller: share a finding others need, ask a "
             "question, answer one, or tell the controller about a requirement or a blocker. read_messages shows what was sent to you.",
}

EVAL_SYSTEM = """You are {name}, the evaluator of the user's AXoR Agent Swarm, checking one contract independently: you did \
none of the work and owe nobody a pass. pass: the deliverable meets the contract's objective and each of its deliverables, with \
evidence for its claims. revise: close, but it misses something specific. fail: off task, unsupported or empty. Score it \
0-100; note: under 40 words, exactly what to fix (empty for a pass); met: each deliverable, met or not.

{rules}"""

COMPARE_SYSTEM = """You are {name}, the evaluator of the user's AXoR Agent Swarm, comparing independent attempts at one \
contract blind: you don't know who wrote which. Score each 0-100 against the contract's objective and deliverables (evidence \
for claims counts), name the strongest as the winner, and say why in under 40 words.

{rules}"""

ADAPT_SYSTEM = """You are the Swarm Controller of the user's AXoR Agent Swarm. The swarm is running and something changed: \
read the news below and revise the contracts that haven't started. For each: keep it, revise it (a new objective that takes \
the news into account) or drop it (no longer needed). Add at most 2 new contracts only when the news needs work nobody has, \
each for an agent from the roster. notify: one message the running agents get now (empty for none). Change as little as \
possible: every change costs the swarm time and tokens.

{rules}"""

INTEGRATE_SYSTEM = """You are {name}, integrating the results of the user's AXoR Agent Swarm into one deliverable for the \
user. The contracts were done by different agents and checked by an evaluator. Write:
- headline: one line, the result.
- report: under 600 words of Markdown: ## Result (answer the mission directly), ## What the swarm found (by contract, with the \
numbers), ## Risks and open questions, ## Next steps. Say plainly what failed or was skipped; never present unchecked work as \
checked.
- limits: what this result could not do or check.

{rules}"""

FINAL_SYSTEM = """You are {name}, the evaluator of the user's AXoR Agent Swarm, judging the integrated result against each \
success criterion of the mission, independently: met or not, with a note. Score it 0-100. verdict: pass when every criterion \
is met, partial when some are, fail when none is.

{rules}"""

READ_BLACKBOARD = {"name": "read_blackboard", "strict": True,
                   "description": "The swarm's shared mission state: every contract (who has it, its status, and the hand-off summary "
                                  "of finished ones) and the findings filed so far. query narrows the findings; empty for the latest.",
                   "input_schema": _schema({"query": _str()})}
READ_MESSAGES = {"name": "read_messages", "strict": True,
                 "description": "Messages sent to you, or to everyone, by other agents and the Swarm Controller, newest first.",
                 "input_schema": _schema({})}

def SEND_MESSAGE(to):
    return {"name": "send_message", "strict": True,
            "description": f"Send a message on the swarm's message bus (at most {SENDS} per contract). to: one agent's key, 'all' or "
                           "'controller'. kind: finding (others need it), request (ask for something), answer (to a request), "
                           "requirement (changes what other contracts must do: for the controller), blocker (you can't go on).",
            "input_schema": _schema({"to": {"type": "string", "enum": to}, "kind": {"type": "string", "enum": list(KINDS)},
                                     "text": _str("Under 400 characters")})}

def PLAN_SCHEMA(keys, sizes, patterns):
    return _obj({
        "size": {"type": "string", "enum": sizes},
        "pattern": {"type": "string", "enum": patterns},
        "why": _str("Two sentences: why this size and pattern for this mission."),
        "contracts": _arr(_obj({
            "key": {"type": "integer", "description": "1, 2, 3... in order"},
            "title": _str("Under 10 words"),
            "objective": _str("What the agent must achieve, under 70 words"),
            "deliverables": _arr(_str(), "1-4 checkable deliverables"),
            "depends": _arr({"type": "integer"}, "Keys of earlier contracts whose results this one needs"),
            "agent": {"type": "string", "enum": keys},
            "mode": {"type": "string", "enum": ["single", "competitive"]},
            "contenders": _arr({"type": "string", "enum": keys}, "For a competitive contract: 2-3 agents, the agent among them; else empty"),
            "share": {"type": "integer", "description": "Percent of the budget, 5-60"}})),
    })

EVAL_SCHEMA = _obj({"verdict": {"type": "string", "enum": ["pass", "revise", "fail"]}, "score": {"type": "integer"}, "note": _str(),
                    "met": _arr(_obj({"deliverable": _str(), "met": {"type": "boolean"}}))})

def COMPARE_SCHEMA(letters):
    return _obj({"entries": _arr(_obj({"entry": {"type": "string", "enum": letters}, "score": {"type": "integer"}, "note": _str()})),
                 "winner": {"type": "string", "enum": letters}, "why": _str()})

def ADAPT_SCHEMA(queued, keys, agents):
    return _obj({
        "changes": _arr(_obj({"contract": {"type": "integer", "enum": queued or [0]}, "action": {"type": "string", "enum": ["keep", "revise", "drop"]},
                              "objective": _str("The revised objective (empty unless revise)"), "note": _str()})),
        "add": _arr(_obj({"title": _str(), "objective": _str(), "deliverables": _arr(_str()), "depends": _arr({"type": "integer", "enum": keys or [0]}),
                          "agent": {"type": "string", "enum": agents}})),
        "notify": _str(), "why": _str()})

INTEGRATE_SCHEMA = _obj({"headline": _str(), "report": _str(), "limits": _arr(_str())})
FINAL_SCHEMA = _obj({"criteria": _arr(_obj({"criterion": {"type": "integer"}, "met": {"type": "boolean"}, "note": _str()})),
                     "score": {"type": "integer"}, "verdict": {"type": "string", "enum": ["pass", "partial", "fail"]}})

CONTROLLER = {"key": "controller", "name": "Swarm Controller", "title": "Swarm Controller", "team": "exec", "id": None}
EVALUATOR = {"key": "evaluator", "name": "Evaluator", "title": "Evaluator", "team": "evaluation", "id": None}


# ---------- requests ----------
class SwarmIn(BaseModel):
    goal: str = Field(min_length=10, max_length=4000)
    title: str = Field(default="", max_length=120)
    criteria: list[str] = Field(default_factory=list, max_length=6)
    budget: int = 80_000
    size: str = "auto"
    pattern: str = "auto"
    deadline: float | None = None


class Swarm(workforce.Workforce):
    """The engine. A Workforce subclass only so an agent's work runs in the Workforce's tool loop; every piece of bookkeeping
    that loop calls (events, runs, spans, tokens, cancel checks, activity) is overridden to the swarm's own tables."""

    def __init__(self, db, hub, wf=None):
        self.db, self.wf, self.data = db, wf, None
        self._tl = threading.local()
        self.hub = _Meter(hub, self._tl)
        q = db.q
        q("""CREATE TABLE IF NOT EXISTS sw_swarms (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, title TEXT, goal TEXT, criteria TEXT,
             budget INTEGER, deadline REAL, size_pref TEXT, pattern_pref TEXT, status TEXT, step TEXT, size TEXT, pattern TEXT, decision TEXT,
             tokens INTEGER DEFAULT 0, adapts INTEGER DEFAULT 0, headline TEXT, report TEXT, limits TEXT, verdict TEXT, score INTEGER,
             criteria_eval TEXT, error TEXT, parent INTEGER, created REAL, updated REAL, started REAL, finished REAL)""")
        q("CREATE INDEX IF NOT EXISTS sw_swarms_u ON sw_swarms (user_id, id)")
        q("""CREATE TABLE IF NOT EXISTS sw_contracts (id INTEGER PRIMARY KEY AUTOINCREMENT, swarm_id INTEGER, key INTEGER, title TEXT,
             objective TEXT, deliverables TEXT, depends TEXT, mode TEXT, agent TEXT, contenders TEXT, status TEXT, budget_limit INTEGER,
             deadline REAL, attempts INTEGER DEFAULT 0, tokens INTEGER DEFAULT 0, output TEXT, summary TEXT, verdict TEXT, score INTEGER,
             note TEXT, revision INTEGER DEFAULT 0, history TEXT, added INTEGER DEFAULT 0, started REAL, finished REAL)""")
        q("CREATE INDEX IF NOT EXISTS sw_contracts_s ON sw_contracts (swarm_id, key)")
        q("""CREATE TABLE IF NOT EXISTS sw_attempts (id INTEGER PRIMARY KEY AUTOINCREMENT, swarm_id INTEGER, contract_id INTEGER, user_id INTEGER,
             agent TEXT, attempt INTEGER, entry TEXT, status TEXT, output TEXT, summary TEXT, verdict TEXT, score INTEGER, note TEXT,
             tokens INTEGER DEFAULT 0, model TEXT, run_id INTEGER, started REAL, finished REAL)""")
        q("CREATE INDEX IF NOT EXISTS sw_attempts_c ON sw_attempts (contract_id, id)")
        q("CREATE INDEX IF NOT EXISTS sw_attempts_u ON sw_attempts (user_id, agent)")
        q("""CREATE TABLE IF NOT EXISTS sw_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, swarm_id INTEGER, contract_id INTEGER, attempt_id INTEGER,
             sender TEXT, recipient TEXT, kind TEXT, text TEXT, evidence TEXT, status TEXT DEFAULT 'sent', seen TEXT DEFAULT '[]', created REAL)""")
        q("CREATE INDEX IF NOT EXISTS sw_messages_s ON sw_messages (swarm_id, id)")
        q("""CREATE TABLE IF NOT EXISTS sw_events (id INTEGER PRIMARY KEY AUTOINCREMENT, swarm_id INTEGER, user_id INTEGER, ts REAL, agent TEXT,
             kind TEXT, text TEXT, contract INTEGER, run_id INTEGER, tokens INTEGER DEFAULT 0)""")
        q("CREATE INDEX IF NOT EXISTS sw_events_s ON sw_events (swarm_id, id)")
        q("""CREATE TABLE IF NOT EXISTS sw_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, swarm_id INTEGER, contract_id INTEGER,
             attempt_id INTEGER, agent TEXT, step TEXT, task TEXT, model TEXT, route TEXT, status TEXT, started REAL, finished REAL,
             tokens INTEGER DEFAULT 0, score INTEGER, summary TEXT, error TEXT)""")
        q("CREATE INDEX IF NOT EXISTS sw_runs_s ON sw_runs (swarm_id, id)")
        q("""CREATE TABLE IF NOT EXISTS sw_spans (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, ts REAL, end REAL, kind TEXT, name TEXT,
             input TEXT, output TEXT, tokens INTEGER DEFAULT 0, error INTEGER DEFAULT 0)""")
        q("CREATE INDEX IF NOT EXISTS sw_spans_r ON sw_spans (run_id)")
        now = time.time()  # a restart: runs in flight are lost; their contracts go back in the queue and the swarm resumes (start)
        q("UPDATE sw_runs SET status='failed', error='Stopped by a server restart.', finished=? WHERE status='running'", (now,))
        q("UPDATE sw_attempts SET status='lost', note='Stopped by a server restart.', finished=? WHERE status='running'", (now,))
        q("UPDATE sw_contracts SET status='queued' WHERE status='running' AND swarm_id IN (SELECT id FROM sw_swarms WHERE status='running')")
        self.pool = ThreadPoolExecutor(WORKERS, thread_name_prefix="swarm")
        self.cancels, self.lock, self.activity = set(), threading.Lock(), {}
        self.version, self.cond = 0, threading.Condition()
        self._thread = None

    # ---------- the runtime's bookkeeping (Workforce._loop and _structured call these) ----------
    def _ctx(self, s):
        return {"uid": s["user_id"], "mid": s["id"], "sid": s["id"], "imp": None, "settings": self._settings(s["user_id"]), "budget": s["budget"],
                "sandbox": False, "owner": self._owner(s["user_id"]), "cache": _Cache(), "eval_model": None, "bench": None, "deadline": s["deadline"]}

    def _check(self, ctx):
        if ctx["sid"] in self.cancels: raise Cancelled()
        if ctx.get("until") and time.time() > ctx["until"]: raise Overdue()
        if ctx.get("limit") and ctx["meter"][0] >= ctx["limit"]: raise OverBudget()

    def _tokens(self, ctx):
        return (self.db.q("SELECT tokens FROM sw_swarms WHERE id=?", (ctx["sid"],), one=True) or {}).get("tokens") or 0

    def _event(self, ctx, agent, kind, text, run_id=None, tokens=0):
        self.db.q("INSERT INTO sw_events (swarm_id, user_id, ts, agent, kind, text, contract, run_id, tokens) VALUES (?,?,?,?,?,?,?,?,?)",
                  (ctx["sid"], ctx["uid"], time.time(), agent, kind, _clip(text, 400), ctx.get("ckey"), run_id, tokens))
        self._bump()

    def _run_start(self, ctx, agent, step, task, model, route, aid=None):
        rid = self._ins("""INSERT INTO sw_runs (user_id, swarm_id, contract_id, attempt_id, agent, step, task, model, route, status, started)
                           VALUES (?,?,?,?,?,?,?,?,?,'running',?)""",
                        (ctx["uid"], ctx["sid"], ctx.get("cid"), ctx.get("atid"), agent["key"], step, task, model, _compact(route), time.time()))
        # the swarm's agents are the Workforce's: their runs are on its line of the ledger, kind swarm-<step>
        workforce.agent_core.begin("workforce", ctx["uid"], f"swarm-{step}", ref=f"sw:{rid}", agent_key=f"workforce:{agent['id']}" if agent.get("id") else None,
                                   title=f"Swarm #{ctx['sid']}: {task or step}", model=model, decision=route)
        self._act(ctx, agent["key"], {"plan": "Planning the swarm", "execute": "Working on a contract", "evaluate": "Checking a contract",
                                      "compare": "Comparing attempts", "adapt": "Revising the plan", "integrate": "Integrating the results",
                                      "final": "Checking the result"}.get(step, step))
        return rid

    def _run_end(self, ctx, rid, agent, status, tokens, model=None, summary="", error=None):
        self.db.q("UPDATE sw_runs SET status=?, finished=?, tokens=?, summary=?, error=? WHERE id=?",
                  (status, time.time(), tokens, _clip(summary, 400), _clip(error, 400) if error else None, rid))
        if tokens:
            self.db.q("UPDATE sw_swarms SET tokens=tokens+? WHERE id=?", (tokens, ctx["sid"]))
            if ctx.get("cid"): self.db.q("UPDATE sw_contracts SET tokens=tokens+? WHERE id=?", (tokens, ctx["cid"]))
            self.hub.log_usage(ctx["owner"], "workforce", tokens, None, model)
        workforce.agent_core.end(status, ref=f"sw:{rid}", tokens=tokens, error=error, model=model)  # after log_usage: counted once
        self._act(ctx, agent["key"], None)

    def _span(self, rid, kind, name, t0, inp="", out="", tokens=0, error=False):
        self.db.q("INSERT INTO sw_spans (run_id, ts, end, kind, name, input, output, tokens, error) VALUES (?,?,?,?,?,?,?,?,?)",
                  (rid, t0, time.time(), kind, name, _clip(inp, workforce.SPAN_CHARS), _clip(out, workforce.SPAN_CHARS), tokens, int(error)))

    def _stats(self, uid):
        """The router learns from the Workforce's runs and the swarm's alike."""
        rows = self.db.q("""SELECT model, task, COUNT(*) n, AVG(tokens) tokens, AVG(finished-started) latency, SUM(status='failed') failed,
                                   COUNT(score) scored, COALESCE(SUM(score),0) score_sum FROM
                              (SELECT model, task, tokens, finished, started, status, score FROM wf_runs WHERE user_id=? AND model IS NOT NULL AND finished IS NOT NULL AND """ + agent_core.NOT_BUDGET_STOP + """
                               UNION ALL SELECT model, task, tokens, finished, started, status, score FROM sw_runs WHERE user_id=? AND model IS NOT NULL AND finished IS NOT NULL AND """ + agent_core.NOT_BUDGET_STOP + """)
                            GROUP BY model, task""", (uid, uid))
        return workforce.model_router.stats_rows(rows)

    def _kb_extra(self, ctx):
        kb, owner = getattr(self.hub, "knowledge", None), ctx.get("owner")
        if not kb or not owner or not hasattr(kb, "agent_tools"): return {}
        try: tools = kb.agent_tools(owner["id"], "workforce", "Workforce")
        except Exception as e:  # noqa: BLE001 - the swarm works without the Knowledge Hub
            log.info("swarm: knowledge tools unavailable: %s", e); return {}
        return {n: (d, h, True) for n, (d, h) in tools.items()}

    def _call_tool(self, owner, name, args):
        out = super()._call_tool(owner, name, args)
        ctx = getattr(self._tl, "ctx", None)  # event streaming: a data tool's result tells the agent it has unread messages
        if ctx and isinstance(out, dict) and (n := self._unread(ctx)): out = {**out, "_swarm": f"{n} unread message(s) for you: call read_messages."}
        return out

    # ---------- bookkeeping ----------
    def _swarm(self, sid):
        s = self.db.q("SELECT * FROM sw_swarms WHERE id=?", (sid,), one=True)
        if not s: raise HTTPException(404, "There's no such swarm.")
        for k, d in (("criteria", []), ("decision", {}), ("limits", []), ("criteria_eval", [])): s[k] = _l(s[k], d)
        return s

    def _own(self, me, sid):
        s = self._swarm(sid)
        if s["user_id"] != me["id"]: raise HTTPException(404, "There's no such swarm.")
        return s

    def _set(self, sid, **kw):
        kw["updated"] = time.time()
        for k in ("criteria", "decision", "limits", "criteria_eval"):
            if k in kw and not isinstance(kw[k], str): kw[k] = _j(kw[k])
        self.db.q(f"UPDATE sw_swarms SET {', '.join(k + '=?' for k in kw)} WHERE id=?", (*kw.values(), sid))
        self._bump()

    def _contracts(self, sid):
        rows = self.db.q("SELECT * FROM sw_contracts WHERE swarm_id=? ORDER BY key", (sid,))
        for c in rows:
            for k, d in (("deliverables", []), ("depends", []), ("contenders", []), ("history", [])): c[k] = _l(c[k], d)
        return rows

    def _cset(self, cid, **kw):
        for k in ("deliverables", "depends", "contenders", "history"):
            if k in kw and not isinstance(kw[k], str): kw[k] = _j(kw[k])
        self.db.q(f"UPDATE sw_contracts SET {', '.join(k + '=?' for k in kw)} WHERE id=?", (*kw.values(), cid))
        self._bump()

    def _eligible(self, team):
        """Who can hold a contract: every active Workforce agent except the CEO (the Workforce's own orchestrator) and the
        Chief Evaluator (she checks the work)."""
        return {k: a for k, a in team.items() if a["role"] not in ("orchestrator", "evaluator") and a["level"] != "ceo"}

    def _records(self, uid):
        """{agent key: {n, passed, score}}: how each agent's contract attempts were judged."""
        out = {}
        for r in self.db.q("""SELECT agent, COUNT(*) n, SUM(verdict='pass') passed, AVG(score) avg FROM sw_attempts
                              WHERE user_id=? AND score IS NOT NULL GROUP BY agent""", (uid,)):
            out[r["agent"]] = {"n": r["n"], "passed": r["passed"] or 0, "score": round((PRIOR * PRIOR_WEIGHT + (r["avg"] or 0) * r["n"]) / (PRIOR_WEIGHT + r["n"]))}
        return out

    def _past(self, uid, sid=None):
        return self.db.q("""SELECT title, goal, pattern, size, score, tokens, started, finished FROM sw_swarms WHERE user_id=? AND id<>? AND status='done'
                            AND score IS NOT NULL ORDER BY id DESC LIMIT 300""", (uid, sid or 0))

    def _left(self, ctx):
        return ctx["budget"] - self._tokens(ctx)

    # ---------- the mission ----------
    def create(self, me, b: SwarmIn, parent=None):
        if b.budget not in BUDGETS: raise HTTPException(400, "Pick one of the token budgets.")
        if b.size != "auto" and b.size not in SIZES: raise HTTPException(400, "The size is auto, solo, team or swarm.")
        if b.pattern != "auto" and b.pattern not in PATTERNS: raise HTTPException(400, "Unknown swarm pattern.")
        if b.deadline is not None and b.deadline < time.time() + 60: raise HTTPException(400, "The deadline has to be at least a minute away.")
        busy = self.db.q("SELECT COUNT(*) n FROM sw_swarms WHERE user_id=? AND status IN ('queued','running')", (me["id"],), one=True)["n"]
        if busy >= ACTIVE_PER_USER and not parent: raise HTTPException(429, f"You have {busy} swarms running: wait for one to finish.")
        crit = [_flat(c, 240) for c in b.criteria if c.strip()][:6]
        now = time.time()
        sid = self._ins("""INSERT INTO sw_swarms (user_id, title, goal, criteria, budget, deadline, size_pref, pattern_pref, status, step, parent,
                           created, updated) VALUES (?,?,?,?,?,?,?,?,'queued','queued',?,?,?)""",
                        (me["id"], _flat(b.title, 120) or _flat(b.goal, 80), b.goal.strip(), _j(crit), b.budget, b.deadline, b.size, b.pattern,
                         parent, now, now))
        self._prune(me["id"])
        self._submit(sid)
        return sid

    def _submit(self, sid, resume=False):
        self.pool.submit(self._run, sid, resume)

    def _prune(self, uid):
        for s in self.db.q("SELECT id FROM sw_swarms WHERE user_id=? AND status NOT IN ('queued','running') ORDER BY id DESC LIMIT -1 OFFSET ?", (uid, MAX_SWARMS)):
            self._purge(s["id"])

    def _purge(self, sid):
        runs = [r["id"] for r in self.db.q("SELECT id FROM sw_runs WHERE swarm_id=?", (sid,))]
        for rid in runs: self.db.q("DELETE FROM sw_spans WHERE run_id=?", (rid,))
        for t in ("sw_runs", "sw_events", "sw_messages", "sw_attempts", "sw_contracts"): self.db.q(f"DELETE FROM {t} WHERE swarm_id=?", (sid,))
        self.db.q("DELETE FROM sw_swarms WHERE id=?", (sid,))

    def _run(self, sid, resume=False):
        try: s = self._swarm(sid)
        except HTTPException: return
        if s["status"] not in ("queued", "running"):
            with self.lock: self.cancels.discard(sid)
            return
        ctx = self._ctx(s)
        try:
            if resume and self._contracts(sid):
                self._event(ctx, "controller", "phase", "Resumed after a server restart: contracts in flight start again")
            else:
                self._set(sid, status="running", step="plan", started=time.time())
                self._plan(ctx, self._swarm(sid))
            self._set(sid, status="running", step="execute")
            self._execute(ctx, sid)
            self._check_cancel(ctx)
            if not any(c["status"] == "done" for c in self._contracts(sid)): raise Stop("No contract was fulfilled, so there is nothing to integrate.")
            self._set(sid, step="integrate")
            self._integrate(ctx, sid)
            if not self._swarm(sid)["parent"]:  # Mission Control verifies a mission's result itself
                self._set(sid, step="evaluate")
                self._final(ctx, sid)
            s = self._swarm(sid)
            self._set(sid, status="done", step="done", finished=time.time())
            self._event(ctx, "controller", "phase", f"Swarm done: {s['verdict'] or 'delivered'}" + (f" at {s['score']}/100" if s["score"] is not None else "")
                        + f" · {s['tokens']:,} tokens")
        except Stop as e:
            self._set(sid, status="failed", error=_clip(e, 300), finished=time.time())
            self._event(ctx, "controller", "fail", str(e))
        except Cancelled:
            self._set(sid, status="cancelled", finished=time.time())
            self._event(ctx, "controller", "warn", "Swarm cancelled.")
        except (LLMError, HTTPException, LookupError, KeyError, ValueError) as e:
            msg = getattr(e, "detail", None) or str(e) or e.__class__.__name__
            self._set(sid, status="failed", error=_clip(msg, 300), finished=time.time())
            self._event(ctx, "controller", "fail", f"Swarm failed: {msg}")
        except Exception as e:  # never leave a swarm hanging in an active state
            log.exception("swarm %s crashed", sid)
            self._set(sid, status="failed", error="Internal error.", finished=time.time())
            self._event(ctx, "controller", "fail", f"Swarm failed: internal error ({e.__class__.__name__}).")
        finally:
            with self.lock: self.cancels.discard(sid)
            self.db.q("UPDATE sw_contracts SET status='skipped', finished=? WHERE swarm_id=? AND status IN ('queued','running')", (time.time(), sid))
            self.db.q("DELETE FROM sw_events WHERE swarm_id=? AND id NOT IN (SELECT id FROM sw_events WHERE swarm_id=? ORDER BY id DESC LIMIT ?)", (sid, sid, EVENT_KEEP))
            self._bump()

    def _check_cancel(self, ctx):
        if ctx["sid"] in self.cancels: raise Cancelled()

    # ---------- 1. the Swarm Controller: size, pattern, contracts ----------
    def _plan(self, ctx, s):
        team = self._team(s["user_id"])
        pool = self._eligible(team)
        if not pool: raise Stop("No Workforce agent is active to work in a swarm: unpause some on the Workforce page.")
        recs = self._records(s["user_id"])
        rec = record(self._past(s["user_id"], s["id"]), _words(f"{s['title']} {s['goal']}"))
        sizes = [s["size_pref"]] if s["size_pref"] in SIZES else list(SIZES)
        pats = [s["pattern_pref"]] if s["pattern_pref"] in PATTERNS else list(PATTERNS)
        roster = "\n".join(
            f"- {k}: {a['name']}, {a['title']} ({TEAM_NAME.get(a['team'], a['team'])}). {a['job']} Tools: {', '.join(sorted(self._grants(ctx['owner'], a))) or 'none'}."
            + (f" Track record: {recs[k]['n']} attempt(s), {recs[k]['passed']} passed, score {recs[k]['score']}/100." if k in recs else " No track record yet.")
            for k, a in pool.items())
        patterns = "\n".join(f"- {k}: {p['about']} Best for: {p['best']}" for k, p in PATTERNS.items() if k in pats)
        dl = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(s["deadline"])) if s["deadline"] else "none"
        prompt = (f"<mission>\n{s['goal']}\n</mission>\nSuccess criteria:\n" + ("\n".join(f"{i}. {c}" for i, c in enumerate(s["criteria"], 1)) or "none given")
                  + f"\nBudget: {s['budget']:,} tokens in all (contracts get about {int(EXEC_SHARE * 100)}% of it). Deadline: {dl}."
                  + (f"\nThe user asked for size {s['size_pref']}." if s["size_pref"] in SIZES else "")
                  + (f"\nThe user asked for the {s['pattern_pref']} pattern." if s["pattern_pref"] in PATTERNS else "")
                  + f"\n\n<roster>\n{roster}\n</roster>" + record_lines(rec) + "\n\nPlan the swarm.")
        system = CONTROLLER_SYSTEM.format(rules=RULES, max_agents=MAX_AGENTS, patterns=patterns, max_contracts=MAX_CONTRACTS, compete=MAX_COMPETE)
        self._event(ctx, "controller", "phase", f"Plan: the Swarm Controller sizes the swarm from {len(pool)} available agents")
        out, _, _ = self._structured(ctx, CONTROLLER, "plan", "plan", system, prompt, PLAN_SCHEMA(list(pool), sizes, pats), "swarm_plan")
        size = out.get("size") if out.get("size") in sizes else sizes[0] if len(sizes) == 1 else "team"
        picked = out.get("pattern") if out.get("pattern") in pats else pats[0] if len(pats) == 1 else "hybrid"
        pattern, switch = advise(rec, picked, fixed=s["pattern_pref"] in PATTERNS)
        if switch: self._event(ctx, "controller", "adapt", f"Running {PATTERNS[pattern]['label'].lower()}, not {PATTERNS[picked]['label'].lower()}: {switch}")
        contracts = self._shape(out.get("contracts") or [], pool, recs, size, pattern, s)
        if not contracts: raise Stop("The controller planned no contracts.")
        agents = sorted({k for c in contracts for k in [c["agent"], *c["contenders"]]})
        decision = {"why": _flat(out.get("why"), 500), "picked": picked, "switch": switch, "record": rec, "agents": agents,
                    "policy": {k: PATTERNS[pattern][k] for k in ("talk", "compete", "adapt", "same_team")}}
        self._set(s["id"], size=size, pattern=pattern, decision=decision)
        now = time.time()
        for c in contracts:
            self.db.q("""INSERT INTO sw_contracts (swarm_id, key, title, objective, deliverables, depends, mode, agent, contenders, status, budget_limit,
                         deadline, history) VALUES (?,?,?,?,?,?,?,?,?,'queued',?,?,?)""",
                      (s["id"], c["key"], c["title"], c["objective"], _j(c["deliverables"]), _j(c["depends"]), c["mode"], c["agent"], _j(c["contenders"]),
                       c["budget_limit"], s["deadline"], _j([{"ts": now, "what": "planned", "agent": c["agent"]}])))
        names = ", ".join(pool[k]["name"] for k in agents)
        self._event(ctx, "controller", "plan", f"{SIZES[size][0]}, {PATTERNS[pattern]['label'].lower()}: {len(contracts)} contract(s) for {len(agents)} agent(s) ({names}). "
                    + _flat(out.get("why"), 240))

    def _shape(self, raw, pool, recs, size, pattern, s):
        """The controller's contracts held to the caps: numbered in order, dependencies only on earlier contracts (a DAG), real
        agents, at most the size's agents, competitive only where the pattern allows it, budgets that add up."""
        lo, hi = SIZES[size][1], SIZES[size][2]
        cap = 1 if size == "solo" else min(MAX_CONTRACTS, 3 if size == "team" else MAX_CONTRACTS)
        raw = [c for c in raw if isinstance(c, dict) and _flat(c.get("objective") or c.get("title"), 10)][:cap]
        if size == "solo" and raw:
            raw[0] = {**raw[0], "objective": raw[0].get("objective") or s["goal"], "depends": [], "mode": "single", "contenders": []}
        fit = lambda k: (recs.get(k, {}).get("score", PRIOR))
        chosen, out, keymap, competes = [], [], {}, 0
        for i, c in enumerate(raw, 1):
            keymap[c.get("key")] = i
            agent = c.get("agent") if c.get("agent") in pool else max(pool, key=fit)
            if agent not in chosen:
                if len(chosen) < hi: chosen.append(agent)
                else:  # over the size's agents: the contract goes to the chosen agent from the same team, else the best scored one
                    agent = next((k for k in chosen if pool[k]["team"] == pool[agent]["team"]), None) or max(chosen, key=fit)
            mode, contenders = "single", []
            if c.get("mode") == "competitive" and PATTERNS[pattern]["compete"] and competes < MAX_COMPETE and size != "solo":
                want = [agent] + [k for k in dict.fromkeys(c.get("contenders") or []) if k in pool and k != agent]
                want = [k for k in want if k in chosen or len(chosen) < hi][:CONTENDERS]
                for k in want:
                    if k not in chosen: chosen.append(k)
                if len(want) >= 2: mode, contenders, competes = "competitive", want, competes + 1
            deps = sorted({keymap[d] for d in c.get("depends") or [] if d in keymap and keymap[d] < i})
            dels = [_flat(d, 200) for d in c.get("deliverables") or [] if str(d).strip()][:4] or ["What the objective asks, with evidence."]
            share = max(5, min(60, int(c.get("share") or 0) or 100 // max(len(raw), 1)))
            out.append({"key": i, "title": _flat(c.get("title"), 90) or f"Contract {i}", "objective": _flat(c.get("objective"), 600) or s["goal"],
                        "deliverables": dels, "depends": deps, "agent": agent, "mode": mode, "contenders": contenders, "share": share})
        if out and len(chosen) < lo and size != "solo":  # a swarm the controller under-staffed: spread its contracts over more agents
            spare = sorted((k for k in pool if k not in chosen), key=lambda k: -fit(k))
            for c in out[1:]:
                if len(chosen) >= lo or not spare: break
                if c["mode"] == "single" and sum(x["agent"] == c["agent"] for x in out) > 1:
                    c["agent"] = spare.pop(0); chosen.append(c["agent"])
        total = sum(c["share"] for c in out) or 1
        room = s["budget"] * EXEC_SHARE
        for c in out: c["budget_limit"] = max(MIN_LIMIT, int(room * c["share"] / total))
        return out

    # ---------- 2. scheduling: contracts over their dependencies, a few agents at once ----------
    def _execute(self, ctx, sid):
        s = self._swarm(sid)
        pol = PATTERNS[s["pattern"]]
        self._event(ctx, "controller", "phase", f"Execute: up to {SLOTS} agents at once; {len(self._contracts(sid))} contract(s)")
        with ThreadPoolExecutor(SLOTS + CONTENDERS, thread_name_prefix=f"sw-{sid}") as ex:
            running = {}  # contract id -> (future, slots)
            while True:
                rows = self._contracts(sid)
                by = {c["key"]: c for c in rows}
                ok = lambda k: by.get(k, {}).get("status") in ("done", "dropped")
                bad = lambda k: by.get(k, {}).get("status") in ("failed", "skipped")
                for c in rows:  # work that needs a contract that failed for good has nothing to build on
                    if c["status"] == "queued" and any(bad(d) for d in c["depends"]):
                        self._cset(c["id"], status="skipped", finished=time.time())
                        self._event({**ctx, "ckey": c["key"]}, "controller", "warn", f"Skipped contract {c['key']} “{c['title']}”: the work it needs failed")
                        c["status"] = "skipped"
                if pol["adapt"] or pol["talk"] != "none": self._inbox(ctx, sid, pol)
                ready = [c for c in rows if c["status"] == "queued" and c["id"] not in running and all(ok(d) for d in c["depends"])]
                stop = None
                if sid in self.cancels: stop = "cancel"
                elif s["deadline"] and time.time() > s["deadline"]: stop = "The deadline passed: no more contracts start; the swarm integrates what's done."
                elif ready and self._tokens(ctx) >= s["budget"] * EXEC_SHARE: stop = f"Budget at {int(EXEC_SHARE * 100)}%: no more contracts start, so the evaluation and the report fit."
                if stop:
                    if stop != "cancel" and not running:
                        for c in rows:
                            if c["status"] == "queued": self._cset(c["id"], status="skipped", finished=time.time())
                        if any(c["status"] == "queued" for c in rows): self._event(ctx, "controller", "warn", stop)
                    ready = []
                used = sum(n for _, n in running.values())
                for c in ready:
                    need = len(c["contenders"]) if c["mode"] == "competitive" and not c["attempts"] else 1
                    if used + need > SLOTS and running: break
                    used += need
                    self._cset(c["id"], status="running", started=c["started"] or time.time())
                    running[c["id"]] = (ex.submit(self._fulfil, ctx, sid, c["id"]), need)
                if not running: break
                done = next((cid for cid, (f, _) in running.items() if f.done()), None)
                if done is None:
                    with self.cond: self.cond.wait(1.0)
                    continue
                running.pop(done)[0].result()
                c = self.db.q("SELECT key, status FROM sw_contracts WHERE id=?", (done,), one=True)
                if c and c["status"] == "failed" and pol["adapt"] and sid not in self.cancels:
                    self._adapt(ctx, sid, f"Contract {c['key']} failed for good after {MAX_ATTEMPTS} attempt(s); its dependents can't use it.")
                s = self._swarm(sid)
        self._check_cancel(ctx)

    # ---------- 3. one contract: attempts, evaluation, reassignment ----------
    def _fulfil(self, base, sid, cid):
        s = self._swarm(sid)
        team = self._team(s["user_id"])
        try:
            while True:
                c = next(x for x in self._contracts(sid) if x["id"] == cid)
                n = (c["attempts"] or 0) + 1
                cx = {**base, "cid": cid, "ckey": c["key"]}
                note = next((h.get("note") for h in reversed(c["history"]) if h.get("note")), None) if n > 1 else None
                competitive = c["mode"] == "competitive" and n == 1
                who = [k for k in (c["contenders"] if competitive else [c["agent"]]) if k in team]
                if not who:
                    self._cset(cid, status="failed", finished=time.time(), note="Its agent isn't active any more.")
                    return
                self._cset(cid, attempts=n)
                limit = max(MIN_LIMIT // 2, c["budget_limit"] // len(who))
                for k in who: self._event(cx, k, "start", f"{team[k]['name']} started contract {c['key']}: {c['title']}" + (f" (attempt {n})" if n > 1 else "")
                                          + (" (competing)" if competitive else ""))
                if len(who) > 1:
                    with ThreadPoolExecutor(len(who), thread_name_prefix=f"sw-{sid}-c{c['key']}") as ex:
                        tries = list(ex.map(lambda kl: self._attempt(cx, s, c, team[kl[0]], limit, n, note, kl[1]), zip(who, "ABC")))
                else:
                    tries = [self._attempt(cx, s, c, team[who[0]], limit, n, note)]
                self._check_cancel(cx)
                if tries and all(t.get("budget_stop") for t in tries):
                    # G5-2: refused by a budget, or the budget couldn't be verified: not the agents' failure. No attempt is used and
                    # nobody else is tried (they'd be refused the same way); the contract stops with the reason
                    why = tries[0]["note"]
                    self._cset(cid, attempts=n - 1, status="failed", finished=time.time(), note=_flat(f"Held by budget, not counted against the agent: {why}", 300))
                    self._event(cx, "controller", "warn", f"Contract {c['key']} stopped by budget (not counted, not reassigned): {_flat(why, 200)}")
                    return
                done = [t for t in tries if t["status"] == "done"]
                if not done:
                    verdict, why, win = "fail", "; ".join(f"{t['agent']}: {t['note']}" for t in tries), None
                elif competitive and len(done) > 1:
                    win, verdict, why = self._compare(cx, s, c, done, team)
                else:
                    win = done[0]
                    verdict, why = self._evaluate(cx, s, c, win, team)
                if verdict == "pass":
                    self._settle(cx, sid, c, win, team)
                    return
                c = next(x for x in self._contracts(sid) if x["id"] == cid)
                hist = c["history"] + [{"ts": time.time(), "what": "failed", "agent": win["agent"] if win else c["agent"], "note": _flat(why, 300), "attempt": n}]
                if n >= MAX_ATTEMPTS:
                    self._cset(cid, status="failed", finished=time.time(), note=_flat(why, 300), history=hist,
                               verdict="fail", score=win["score"] if win else None)
                    self._event(cx, "controller", "fail", f"Contract {c['key']} “{c['title']}” failed after {n} attempt(s): {_flat(why, 200)}")
                    return
                tried = {h.get("agent") for h in hist} | set(c["contenders"]) | {c["agent"]}
                nxt = self._replacement(s, c, team, tried)
                if not nxt:
                    nxt = (win or {}).get("agent") or c["agent"]
                    self._event(cx, "controller", "adapt", f"Nobody else fits contract {c['key']}: {team[nxt]['name']} tries again with the evaluator's note")
                else:
                    self._event(cx, "controller", "adapt", f"Reassigned contract {c['key']} from {team.get(c['agent'], {}).get('name', c['agent'])} to "
                                                            f"{team[nxt]['name']}: {_flat(why, 160)}")
                hist.append({"ts": time.time(), "what": "reassigned", "agent": nxt, "from": c["agent"]})
                self._cset(cid, agent=nxt, mode="single", history=hist)
        except Cancelled:
            self.db.q("UPDATE sw_contracts SET status='skipped', finished=? WHERE id=? AND status='running'", (time.time(), cid))
        except LLMError as e:  # the evaluator's model failed: the contract fails, the swarm goes on
            self._cset(cid, status="failed", finished=time.time(), note=_clip(str(e), 300))
            self._event({**base, "ckey": None}, "controller", "fail", f"A contract's check failed: {e}")

    def _attempt(self, cx, s, c, agent, limit, n, note, entry=None):
        """One agent's attempt at the contract, metered against its budget and its time. Returns the attempt (a dict)."""
        until = time.time() + CONTRACT_SECS
        if s["deadline"]: until = min(until, s["deadline"])
        atid = self._ins("""INSERT INTO sw_attempts (swarm_id, contract_id, user_id, agent, attempt, entry, status, started) VALUES (?,?,?,?,?,?,'running',?)""",
                         (s["id"], c["id"], s["user_id"], agent["key"], n, entry, time.time()))
        ctx = {**cx, "atid": atid, "akey": agent["key"], "meter": [0], "limit": limit, "until": until}
        self._tl.ctx, self._tl.meter = ctx, ctx["meter"]
        out = {"id": atid, "agent": agent["key"], "entry": entry, "status": "failed", "note": "", "score": None}
        try:
            w = self._work_contract(ctx, s, c, agent, note, atid)
            out.update(status="done", output=w["deliverable"], summary=w["summary"], model=w["model"], run=w["run"], findings=w["findings"])
        except (Overdue, OverBudget) as e:
            out["note"] = (f"ran out of its {limit:,}-token budget before filing" if isinstance(e, OverBudget) else "ran out of time before filing")
            out["status"] = "over_budget" if isinstance(e, OverBudget) else "overdue"
            self._event(ctx, agent["key"], "warn", f"{agent['name']}'s attempt at contract {c['key']} {out['note']}")
        except Cancelled:
            self.db.q("UPDATE sw_attempts SET status='cancelled', finished=? WHERE id=?", (time.time(), atid))
            raise
        except LLMError as e:
            out["note"] = _flat(str(e), 200)
            out["budget_stop"] = agent_core.budget_stop(e)
            self._event(ctx, agent["key"], "warn" if out["budget_stop"] else "fail", f"{agent['name']}'s attempt at contract {c['key']} "
                        + ("was stopped by budget (not counted)" if out["budget_stop"] else "failed") + f": {out['note']}")
        finally:
            self._tl.ctx = self._tl.meter = None
        tok = (self.db.q("SELECT COALESCE(SUM(tokens),0) n FROM sw_runs WHERE attempt_id=?", (atid,), one=True) or {}).get("n") or 0
        self.db.q("UPDATE sw_attempts SET status=?, output=?, summary=?, note=?, tokens=?, model=?, run_id=?, finished=? WHERE id=?",
                  (out["status"], out.get("output"), out.get("summary"), out["note"] or None, tok, out.get("model"), out.get("run"), time.time(), atid))
        if out["status"] == "done":
            for f in out["findings"]:  # the blackboard; a failed check withdraws them (_withdraw)
                self.db.q("""INSERT INTO sw_messages (swarm_id, contract_id, attempt_id, sender, recipient, kind, text, evidence, status, created)
                             VALUES (?,?,?,?,'all','finding',?,?,'board',?)""", (s["id"], c["id"], atid, agent["key"], f["text"], f["evidence"], time.time()))
            self._event(ctx, agent["key"], "done", f"{agent['name']} filed contract {c['key']}" + (f" (entry {entry})" if entry else "") + f": {_flat(out['summary'], 180)}",
                        out.get("run"), tok)
        return out

    def _work_contract(self, ctx, s, c, agent, note, atid):
        pol = PATTERNS[s["pattern"]]
        others = [k for k in (s["decision"] or {}).get("agents") or [] if k != agent["key"]]
        sent = [0]
        extra = {"read_blackboard": (READ_BLACKBOARD, lambda a: self._blackboard(ctx, a), True),
                 "read_messages": (READ_MESSAGES, lambda a: self._read_messages(ctx, agent["key"]), True)}
        if pol["talk"] != "none":
            to = ["controller"] if pol["talk"] == "up" else ["controller", "all", *others]
            extra["send_message"] = (SEND_MESSAGE(to), lambda a: self._send(ctx, agent, c, atid, a, to, sent), False)
        system = WORK_SYSTEM.format(name=agent["name"], title=agent["title"], rules=RULES, talk=TALK[pol["talk"]], calls=LOOKUPS, instructions=agent["instructions"])
        got, text, tokens, used, rid, calls = self._loop(ctx, agent, "execute", agent["team"], system, self._brief(ctx, s, c, note), self._grants(ctx["owner"], agent),
                                                         extra, SUBMIT_WORK, LOOKUPS)
        findings = [{"text": _flat(f.get("text"), 300), "evidence": _flat(f.get("evidence"), 300)} for f in (got.get("findings") or [])[:8]
                    if isinstance(f, dict) and _flat(f.get("text"), 300)]
        deliverable = str(got.get("deliverable") or text or "(no answer)").strip()
        return {"deliverable": _clip(deliverable, 12000), "summary": _flat(got.get("summary"), 400) or _summary(deliverable), "findings": findings,
                "model": used, "run": rid}

    def contract_json(self, s, c, agent=None):
        """The task contract in the spec's shape (what the agent is given, and what the page shows); `agent`: the contender it's for."""
        return {"task_id": f"sw{s['id']}-c{c['key']}", "mission_id": f"mx-{s['parent']}" if s.get("parent") else f"swarm-{s['id']}",
                "assigned_agent": agent or c["agent"], "objective": c["objective"], "deadline": _iso(c["deadline"]), "budget_limit": c["budget_limit"],
                "status": c["status"], "deliverables": c["deliverables"], "depends": [f"sw{s['id']}-c{d}" for d in c["depends"]],
                **({"contenders": c["contenders"]} if c["mode"] == "competitive" else {})}

    def _brief(self, ctx, s, c, note):
        hand = [x for x in self._contracts(s["id"]) if x["key"] in c["depends"] and x["status"] == "done"]
        team = self._team(s["user_id"])
        crit = "\n".join(f"{i}. {x}" for i, x in enumerate(s["criteria"], 1))
        return (f"Mission: {s['goal']}" + (f"\nSuccess criteria of the mission:\n{crit}" if crit else "")
                + f"\n\nYour contract ({PATTERNS[s['pattern']]['label'].lower()} swarm" + (", competing: other agents attempt it independently and an evaluator "
                  "keeps the best" if c["mode"] == "competitive" and (c["attempts"] or 0) <= 1 else "") + f"):\n{_j(self.contract_json(s, c, ctx.get('akey')))}"
                + ("\n\nHand-offs from the contracts yours depends on:\n" + "\n".join(
                    f"- {self.contract_json(s, x)['task_id']} “{x['title']}” by {team.get(x['agent'], {}).get('name', x['agent'])}: {x['summary']}" for x in hand) if hand else "")
                + (f"\n\nThe Swarm Controller revised this contract: {rev}" if c["revision"] and (rev := next((h.get("note") for h in reversed(c["history"]) if h.get("what") == "revised"), "")) else "")
                + (f"\n\nThe last attempt at this contract didn't pass: {note}\nFix exactly that." if note else ""))

    def _evaluate(self, cx, s, c, t, team):
        ev = team.get("chief-evaluator") or EVALUATOR
        prompt = (f"Mission: {s['goal']}\n\nThe contract:\n{_j(self.contract_json(s, c))}\n\nThe work, by {team.get(t['agent'], {}).get('name', t['agent'])}:\n"
                  f"{_clip(t['output'], workforce.OUT_CHARS * 2)}\n\nCheck the contract.")
        out, _, _ = self._structured(cx, ev, "evaluate", "evaluate", EVAL_SYSTEM.format(name=ev["name"], rules=RULES), prompt, EVAL_SCHEMA, "contract_check",
                                     avoid=tuple(x for x in (t.get("model"),) if x))
        verdict = out.get("verdict") if out.get("verdict") in ("pass", "revise", "fail") else "fail"
        score = max(0, min(100, int(out.get("score") or 0)))
        note = _flat(out.get("note"), 300)
        self.db.q("UPDATE sw_attempts SET verdict=?, score=?, note=COALESCE(?, note) WHERE id=?", (verdict, score, note or None, t["id"]))
        if t.get("run"): self.db.q("UPDATE sw_runs SET score=? WHERE id=?", (score, t["run"]))  # the router learns from it
        t["score"] = score
        self._event(cx, ev["key"], "check", f"{ev['name']}: contract {c['key']} {verdict} at {score}/100" + (f": {note}" if note and verdict != "pass" else ""))
        if verdict != "pass": self._withdraw(t)
        return verdict, note or f"scored {score}/100"

    def _compare(self, cx, s, c, tries, team):
        ev = team.get("chief-evaluator") or EVALUATOR
        order = tries[:]
        random.shuffle(order)  # blind: the letters don't follow who was asked first
        letters = [chr(65 + i) for i in range(len(order))]
        for t, L in zip(order, letters): t["blind"] = L
        prompt = (f"Mission: {s['goal']}\n\nThe contract:\n{_j({k: v for k, v in self.contract_json(s, c).items() if k not in ('assigned_agent', 'contenders')})}\n\n"
                  + "\n\n".join(f"### Attempt {t['blind']}\n{_clip(t['output'], workforce.OUT_CHARS)}" for t in order) + "\n\nCompare the attempts.")
        out, _, _ = self._structured(cx, ev, "compare", "evaluate", COMPARE_SYSTEM.format(name=ev["name"], rules=RULES), prompt, COMPARE_SCHEMA(letters),
                                     "attempt_comparison", avoid=tuple({t.get("model") for t in order if t.get("model")}))
        scores = {e.get("entry"): (max(0, min(100, int(e.get("score") or 0))), _flat(e.get("note"), 200)) for e in out.get("entries") or [] if isinstance(e, dict)}
        for t in order:
            sc, nt = scores.get(t["blind"], (None, ""))
            t["score"] = sc
            self.db.q("UPDATE sw_attempts SET score=?, note=?, verdict=? WHERE id=?", (sc, nt or None, None, t["id"]))
            if t.get("run") and sc is not None: self.db.q("UPDATE sw_runs SET score=? WHERE id=?", (sc, t["run"]))
        win = next((t for t in order if t["blind"] == out.get("winner")), None) or max(order, key=lambda t: t["score"] or 0)
        for t in order:
            v = "pass" if t is win and (t["score"] or 0) >= PASS else "lost" if t is not win else "fail"
            self.db.q("UPDATE sw_attempts SET verdict=? WHERE id=?", (v, t["id"]))
            if t is not win or v == "fail": self._withdraw(t)
        why = _flat(out.get("why"), 300)
        name = lambda k: team.get(k, {}).get("name", k)
        tally = " · ".join(f"{name(t['agent'])} {t['score']}" for t in order)
        self._event(cx, ev["key"], "check", f"{ev['name']} compared {len(order)} attempts blind at contract {c['key']}: {name(win['agent'])}'s won at {win['score']}/100 ({tally})")
        if (win["score"] or 0) < PASS: return win, "fail", f"the best attempt scored {win['score']}/100: {why}"
        return win, "pass", why

    def _withdraw(self, t):
        self.db.q("UPDATE sw_messages SET status='withdrawn' WHERE attempt_id=? AND status='board'", (t["id"],))

    def _settle(self, cx, sid, c, win, team):
        hist = next(x for x in self._contracts(sid) if x["id"] == c["id"])["history"] + [{"ts": time.time(), "what": "passed", "agent": win["agent"], "score": win["score"]}]
        self._cset(c["id"], status="done", agent=win["agent"], output=win["output"], summary=win["summary"], verdict="pass", score=win["score"],
                   note=None, history=hist, finished=time.time())
        self._event(cx, win["agent"], "done", f"Contract {c['key']} “{c['title']}” fulfilled by {team.get(win['agent'], {}).get('name', win['agent'])} at {win['score']}/100")

    def _replacement(self, s, c, team, tried):
        """Who takes over failed work: an eligible agent who hasn't tried it, ranked by how their job fits the objective (a
        teammate of the agent who failed counts as a good fit), then their contract track record, and agents not busy on
        another running contract of the swarm first; strictly inside the agent's own team first when the pattern is hierarchical."""
        pool = {k: a for k, a in self._eligible(team).items() if k not in tried}
        if not pool: return None
        recs, want = self._records(s["user_id"]), _words(c["objective"] + " " + c["title"])
        home = team.get(c["agent"], {}).get("team")
        busy = {k for x in self._contracts(s["id"]) if x["status"] == "running" and x["id"] != c["id"] for k in [x["agent"], *x["contenders"]]}
        def rank(k):
            a = pool[k]
            fit = len(want & _words(f"{a['title']} {a['job']}")) + (2 if a["team"] == home else 0)
            return ((PATTERNS[s["pattern"]]["same_team"] and a["team"] == home), fit, k not in busy, recs.get(k, {}).get("score", PRIOR))
        return max(pool, key=rank)

    # ---------- 4. communication: the message bus, the blackboard, event notifications ----------
    def _send(self, ctx, agent, c, atid, args, to, sent):
        sent[0] += 1
        if sent[0] > SENDS: return {"error": f"You've sent {SENDS} messages for this contract. Finish your work."}
        dest = args.get("to") if args.get("to") in to else None
        if not dest: return {"error": f"You can message: {', '.join(to)}."}
        kind = args.get("kind") if args.get("kind") in KINDS else "finding"
        text = _flat(args.get("text"), 400)
        if not text: return {"error": "The message is empty."}
        mid = self._ins("""INSERT INTO sw_messages (swarm_id, contract_id, attempt_id, sender, recipient, kind, text, created) VALUES (?,?,?,?,?,?,?,?)""",
                        (ctx["sid"], c["id"], atid, agent["key"], dest, kind, text, time.time()))
        self._event(ctx, agent["key"], "message", f"{agent['name']} → {dest}: {kind}: {_flat(text, 160)}")
        return {"sent": mid, "note": "The controller reads it between contracts and may change the plan." if dest == "controller" else "Delivered. Carry on."}

    def _read_messages(self, ctx, key):
        rows = self.db.q("""SELECT * FROM sw_messages WHERE swarm_id=? AND sender<>? AND status='sent' AND (recipient=? OR recipient='all')
                            ORDER BY id DESC LIMIT 12""", (ctx["sid"], key, key))
        for r in rows:
            seen = _l(r["seen"], [])
            if key not in seen: self.db.q("UPDATE sw_messages SET seen=? WHERE id=?", (_j(seen + [key]), r["id"]))
        return {"messages": [{"id": r["id"], "from": r["sender"], "to": r["recipient"], "kind": r["kind"], "text": r["text"]} for r in rows]} if rows \
            else {"messages": [], "note": "No messages for you."}

    def _unread(self, ctx):
        key = ctx.get("akey")
        if not key: return 0
        rows = self.db.q("SELECT seen FROM sw_messages WHERE swarm_id=? AND sender<>? AND status='sent' AND (recipient=? OR recipient='all')", (ctx["sid"], key, key))
        return sum(1 for r in rows if key not in _l(r["seen"], []))

    def _blackboard(self, ctx, args):
        s = self._swarm(ctx["sid"])
        team = self._team(s["user_id"])
        q = _words(args.get("query") or "")
        cs = [{"task_id": f"sw{s['id']}-c{c['key']}", "title": c["title"], "agent": team.get(c["agent"], {}).get("name", c["agent"]), "status": c["status"],
               **({"summary": c["summary"]} if c["status"] == "done" else {})} for c in self._contracts(s["id"])]
        rows = self.db.q("SELECT * FROM sw_messages WHERE swarm_id=? AND recipient='all' AND kind='finding' AND status IN ('board','sent') ORDER BY id DESC LIMIT 40", (s["id"],))
        if q: rows = [r for r in rows if q & _words(r["text"] + " " + (r["evidence"] or ""))] or rows
        return {"mission": _clip(s["goal"], 600), "pattern": s["pattern"], "contracts": cs,
                "findings": [{"by": team.get(r["sender"], {}).get("name", r["sender"]), "text": r["text"], "evidence": r["evidence"]} for r in rows[:12]]}

    def _inbox(self, ctx, sid, pol):
        """What agents sent the controller: requirements and blockers make an adaptive swarm replan; otherwise the controller
        passes them on to everyone, so nobody's news is lost."""
        rows = self.db.q("SELECT * FROM sw_messages WHERE swarm_id=? AND recipient='controller' AND status='sent' ORDER BY id", (sid,))
        if not rows: return
        for r in rows: self.db.q("UPDATE sw_messages SET status='handled' WHERE id=?", (r["id"],))
        team = self._team(ctx["uid"])
        news = "\n".join(f"- {team.get(r['sender'], {}).get('name', r['sender'])} ({r['kind']}): {r['text']}" for r in rows)
        if pol["adapt"] and any(r["kind"] in ("requirement", "blocker") for r in rows):
            self._adapt(ctx, sid, "Agents reported:\n" + news)
            return
        self.db.q("""INSERT INTO sw_messages (swarm_id, sender, recipient, kind, text, created) VALUES (?,?,?,?,?,?)""",
                  (sid, "controller", "all", "finding", _clip("Passed on by the controller:\n" + news, 1200), time.time()))
        self._event(ctx, "controller", "message", f"Passed {len(rows)} message(s) on to the swarm")

    # ---------- 5. adaptive formation ----------
    def _adapt(self, ctx, sid, trigger):
        s = self._swarm(sid)
        if (s["adapts"] or 0) >= ADAPTS:
            self._event(ctx, "controller", "warn", f"Not replanning again: {ADAPTS} replans is the limit. {_flat(trigger, 160)}")
            return
        if self._left(ctx) < 12000:
            self._event(ctx, "controller", "warn", "Not replanning: the budget left is kept for the evaluation and the report.")
            return
        rows = self._contracts(sid)
        queued = [c["key"] for c in rows if c["status"] == "queued"]
        team = self._team(s["user_id"])
        pool = self._eligible(team)
        state = "\n".join(f"- contract {c['key']} [{c['status']}] “{c['title']}” ({team.get(c['agent'], {}).get('name', c['agent'])}): {c['objective']}"
                          + (f" Result: {c['summary']}" if c["status"] == "done" else "") + (f" Why it failed: {c['note']}" if c["status"] == "failed" else "")
                          for c in rows)
        prompt = (f"<mission>\n{s['goal']}\n</mission>\n\n<news>\n{trigger}\n</news>\n\nThe contracts:\n{state}\n\nThe roster: "
                  + ", ".join(f"{k} ({a['title']})" for k, a in pool.items()) + "\n\nRevise the plan.")
        self._set(sid, adapts=(s["adapts"] or 0) + 1)
        out, _, _ = self._structured(ctx, CONTROLLER, "adapt", "plan", ADAPT_SYSTEM.format(rules=RULES), prompt,
                                     ADAPT_SCHEMA(queued, [c["key"] for c in rows], list(pool)), "swarm_replan")
        by, changed, now = {c["key"]: c for c in rows}, [], time.time()
        for ch in out.get("changes") or []:
            c = by.get(ch.get("contract"))
            if not c or c["status"] != "queued" or ch.get("action") not in ("revise", "drop"): continue
            if ch["action"] == "drop":
                self._cset(c["id"], status="dropped", finished=now, history=c["history"] + [{"ts": now, "what": "dropped", "note": _flat(ch.get("note"), 300)}])
                changed.append(f"dropped {c['key']}")
            elif _flat(ch.get("objective"), 600):
                deps = [d for d in c["depends"] if by.get(d, {}).get("status") not in ("failed", "skipped")]  # it no longer waits on failed work
                self._cset(c["id"], objective=_flat(ch["objective"], 600), revision=(c["revision"] or 0) + 1, depends=deps,
                           history=c["history"] + [{"ts": now, "what": "revised", "note": _flat(ch.get("note") or ch["objective"], 300)}])
                changed.append(f"revised {c['key']}")
        key, room = max(by) if by else 0, self._left(ctx) - s["budget"] * (1 - EXEC_SHARE)
        agents = set((s["decision"] or {}).get("agents") or [])
        for a in (out.get("add") or [])[:2]:
            if len(by) >= MAX_CONTRACTS + 2 or not _flat(a.get("objective"), 10) or a.get("agent") not in pool: continue
            if a["agent"] not in agents and len(agents) >= MAX_AGENTS: continue
            key += 1
            agents.add(a["agent"])
            deps = [d for d in a.get("depends") or [] if d in by and by[d]["status"] not in ("failed", "skipped")]
            self.db.q("""INSERT INTO sw_contracts (swarm_id, key, title, objective, deliverables, depends, mode, agent, contenders, status, budget_limit,
                         deadline, history, added) VALUES (?,?,?,?,?,?,'single',?,'[]','queued',?,?,?,1)""",
                      (sid, key, _flat(a.get("title"), 90) or f"Contract {key}", _flat(a["objective"], 600),
                       _j([_flat(d, 200) for d in a.get("deliverables") or [] if str(d).strip()][:4] or ["What the objective asks, with evidence."]),
                       _j(deps), a["agent"], max(MIN_LIMIT, int(max(room, 0) / (len(queued) + 1))), s["deadline"],
                       _j([{"ts": now, "what": "added", "agent": a["agent"], "note": "Added by a replan"}])))
            changed.append(f"added {key}")
        if agents != set((s["decision"] or {}).get("agents") or []): self._set(sid, decision={**(s["decision"] or {}), "agents": sorted(agents)})
        if _flat(out.get("notify"), 400):
            self.db.q("INSERT INTO sw_messages (swarm_id, sender, recipient, kind, text, created) VALUES (?,?,'all','requirement',?,?)",
                      (sid, "controller", _flat(out["notify"], 600), now))
        self._event(ctx, "controller", "adapt", f"Replan {s['adapts'] + 1}: " + (", ".join(changed) or "no change") + f". {_flat(out.get('why'), 200)}")

    # ---------- 6. integration and the final check ----------
    def _integrate(self, ctx, sid):
        s, rows, team = self._swarm(sid), self._contracts(sid), self._team(self._swarm(sid)["user_id"])
        who = team.get("ceo") or CONTROLLER
        parts = "\n\n".join(f"### Contract {c['key']}: {c['title']} [{c['status']}" + (f", {c['score']}/100" if c["score"] is not None else "") + "]\n"
                            f"By {team.get(c['agent'], {}).get('name', c['agent'])}. Objective: {c['objective']}\n" + (_clip(c["output"], workforce.OUT_CHARS) if c["status"] == "done"
                                                                                                                       else f"Not done: {c['note'] or c['status']}")
                            for c in rows)
        prompt = (f"<mission>\n{s['goal']}\n</mission>\nSuccess criteria:\n" + ("\n".join(f"{i}. {x}" for i, x in enumerate(s["criteria"], 1)) or "none given")
                  + f"\n\nThe swarm ({PATTERNS[s['pattern']]['label'].lower()}, {SIZES[s['size']][0].lower()}):\n\n{parts}\n\nIntegrate the results.")
        self._event(ctx, who["key"], "phase", f"Integrate: {who['name']} combines {sum(c['status'] == 'done' for c in rows)} fulfilled contract(s) into one result")
        out, _, _ = self._structured(ctx, who, "integrate", "synthesize", INTEGRATE_SYSTEM.format(name=who["name"], rules=RULES), prompt, INTEGRATE_SCHEMA, "swarm_result")
        self._set(sid, headline=_flat(out.get("headline"), 200), report=_clip(out.get("report"), 20000), limits=[_flat(x, 240) for x in out.get("limits") or []][:6])

    def _final(self, ctx, sid):
        s = self._swarm(sid)
        if not s["criteria"]: return
        ev = self._team(s["user_id"]).get("chief-evaluator") or EVALUATOR
        prompt = (f"<mission>\n{s['goal']}\n</mission>\nSuccess criteria:\n" + "\n".join(f"{i}. {x}" for i, x in enumerate(s["criteria"], 1))
                  + f"\n\nThe result:\n{s['headline'] or ''}\n\n{_clip(s['report'], 12000)}\n\nJudge it.")
        out, _, _ = self._structured(ctx, ev, "final", "evaluate", FINAL_SYSTEM.format(name=ev["name"], rules=RULES), prompt, FINAL_SCHEMA, "swarm_verdict")
        crit = [{"criterion": s["criteria"][x["criterion"] - 1], "met": bool(x.get("met")), "note": _flat(x.get("note"), 300)}
                for x in out.get("criteria") or [] if isinstance(x, dict) and isinstance(x.get("criterion"), int) and 1 <= x["criterion"] <= len(s["criteria"])]
        met = sum(x["met"] for x in crit)
        verdict = "pass" if crit and met == len(s["criteria"]) else "partial" if met else "fail"  # from the criteria in code, not the model's word
        self._set(sid, criteria_eval=crit, score=max(0, min(100, int(out.get("score") or 0))), verdict=verdict)
        self._event(ctx, ev["key"], "check", f"{ev['name']}: {met} of {len(s['criteria'])} criteria met · {verdict}")

    def score_from_mission(self, sid, outcome):
        """Mission Control verified a swarm's result: its outcome is the swarm's score for the track record."""
        sc = {"verified": 100, "partial": 50, "failed": 0}.get(outcome)
        if sc is not None: self.db.q("UPDATE sw_swarms SET score=?, verdict=? WHERE id=? AND score IS NULL",
                                     (sc, {"verified": "pass", "partial": "partial", "failed": "fail"}[outcome], sid))

    # ---------- the user's side ----------
    def cancel(self, me, sid):
        s = self._own(me, sid)
        if s["status"] not in ("queued", "running"): raise HTTPException(409, "The swarm isn't running.")
        with self.lock: self.cancels.add(sid)
        if s["status"] == "queued": self._set(sid, status="cancelled", finished=time.time())
        self._bump()
        return {"ok": True}

    def delete(self, me, sid, ip=""):
        s = self._own(me, sid)
        if s["status"] in ("queued", "running"): raise HTTPException(409, "Cancel the swarm first.")
        self._purge(sid)
        self.db.log("swarm.delete", me["username"], str(sid), ip, s["title"])
        self._bump()
        return {"ok": True}

    def _card(self, s):
        n = self.db.q("SELECT COUNT(*) n, SUM(status='done') done FROM sw_contracts WHERE swarm_id=?", (s["id"],), one=True)
        return {k: s[k] for k in ("id", "title", "status", "step", "pattern", "size", "tokens", "budget", "score", "verdict", "headline", "error", "parent",
                                  "created", "finished")} | {"contracts": n["n"] or 0, "done": n["done"] or 0, "agents": len((s["decision"] or {}).get("agents") or [])}

    def state(self, me, sid, since=0):
        s = self._own(me, sid)
        team = self._team(me["id"])
        rows = self._contracts(sid)
        att = self.db.q("SELECT id, contract_id, agent, attempt, entry, status, summary, verdict, score, note, tokens, model, run_id, started, finished "
                        "FROM sw_attempts WHERE swarm_id=? ORDER BY id", (sid,))
        cs = [{**{k: c[k] for k in ("id", "key", "title", "objective", "deliverables", "depends", "mode", "agent", "contenders", "status", "budget_limit",
                                    "attempts", "tokens", "summary", "verdict", "score", "note", "revision", "history", "added", "started", "finished")},
               "output": c["output"], "contract": self.contract_json(s, c), "tries": [a for a in att if a["contract_id"] == c["id"]]} for c in rows]
        msgs = self.db.q("SELECT id, contract_id, sender, recipient, kind, text, evidence, status, created FROM sw_messages WHERE swarm_id=? ORDER BY id DESC LIMIT 200", (sid,))
        ev = self.db.q("SELECT * FROM sw_events WHERE swarm_id=? AND id>? ORDER BY id DESC LIMIT 300", (sid, since))
        keys = set((s["decision"] or {}).get("agents") or []) | {c["agent"] for c in rows}
        live = {a: t for a, t in self._live(me["id"]).items()}
        people = {k: {"key": k, "name": a["name"], "title": a["title"], "team": a["team"], "icon": a["icon"], "color": a["color"], "doing": (live.get(k) or {}).get("text")}
                  for k, a in team.items() if k in keys or k in ("ceo", "chief-evaluator")}
        return {"swarm": {**s, "goal": s["goal"]}, "contracts": cs, "messages": msgs, "events": ev, "people": people,
                "patterns": PATTERNS, "sizes": {k: v[0] for k, v in SIZES.items()}, "version": self.version}

    def _live(self, uid):
        with self.lock:
            return {a: {"swarm": k[1], "text": t} for k, acts in self.activity.items() if k[0] == uid for a, t in acts.items()}

    def trace(self, me, rid):
        r = self.db.q("SELECT * FROM sw_runs WHERE id=?", (rid,), one=True)
        if not r or r["user_id"] != me["id"]: raise HTTPException(404, "There's no such run.")
        r["route"] = _l(r["route"], {})
        return {"run": r, "spans": self.db.q("SELECT * FROM sw_spans WHERE run_id=? ORDER BY id", (rid,))}

    def home(self, me):
        uid = me["id"]
        team = self._team(uid)
        recs = self._records(uid)
        rows = self.db.q("SELECT * FROM sw_swarms WHERE user_id=? ORDER BY id DESC LIMIT 60", (uid,))
        for s in rows: s["decision"] = _l(s["decision"], {})
        done = [s for s in self._past(uid)]
        overall = {"patterns": _group(done, "pattern"), "sizes": _group(done, "size")}
        roster = [{"key": k, "name": a["name"], "title": a["title"], "team": a["team"], "icon": a["icon"], "color": a["color"], "record": recs.get(k)}
                  for k, a in self._eligible(team).items()]
        return {"swarms": [self._card(s) for s in rows], "roster": roster, "patterns": PATTERNS, "sizes": {k: {"label": v[0], "min": v[1], "max": v[2]} for k, v in SIZES.items()},
                "budgets": BUDGETS, "record": overall,
                "limits": {"agents": MAX_AGENTS, "contracts": MAX_CONTRACTS, "slots": SLOTS, "attempts": MAX_ATTEMPTS, "adapts": ADAPTS, "contenders": CONTENDERS,
                           "competitive": MAX_COMPETE, "lookups": LOOKUPS, "minutes": CONTRACT_SECS // 60, "exec_share": EXEC_SHARE},
                "version": self.version}

    def start(self):
        """Swarms a restart cut off go on from their contracts (the ones done stay done)."""
        if self._thread or not ENABLED: return
        self._thread = True
        for s in self.db.q("SELECT id, status FROM sw_swarms WHERE status IN ('queued','running')"):
            self._submit(s["id"], resume=s["status"] == "running")


def build(db, require, hub, wf, ip):
    r = APIRouter(prefix="/api/swarm")
    gate = hub.gate if hub else (lambda me: me)
    sw = Swarm(db, hub, wf) if hub and wf and ENABLED and workforce.ENABLED else None
    r.state = {"swarm": sw}
    def user(req):  # anyone who may use agents: a swarm spends the same model credits as the Workforce
        if not sw: raise HTTPException(404, "The agent swarm is turned off on this server.")
        return gate(require(req))

    @r.get("")
    def home(req: Request): return sw.home(user(req))

    @r.post("/swarms")
    def create(b: SwarmIn, req: Request):
        me = user(req)
        return sw.state(me, sw.create(me, b))

    @r.get("/swarms/{sid}")
    def state(sid: int, req: Request, since: int = 0): return sw.state(user(req), sid, since)

    @r.post("/swarms/{sid}/cancel")
    def cancel(sid: int, req: Request): return sw.cancel(user(req), sid)

    @r.delete("/swarms/{sid}")
    def delete(sid: int, req: Request): return sw.delete(user(req), sid, ip(req))

    @r.get("/runs/{rid}")
    def trace(rid: int, req: Request): return sw.trace(user(req), rid)

    return r
