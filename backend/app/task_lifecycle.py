"""One task lifecycle for the Control Hub: Mission → task contract → Dispatcher → scheduler → agent → verification → done.

From the 11-10 ChatGPT review of production's Task dispatch ("15 open, 0 under way, 3 not dispatched after an hour, 0 retried
or reassigned", while the Mission engine said "0 open missions"). control_dispatch.py moves tasks; this module is what the
review asked for on top of it:

- stage(): one canonical stage per task, read from what's already recorded (ctl_tasks.status, its board task or mission,
  the agent run ledger), never stored, so nothing else that reads ctl_tasks.status changes:
      CREATED → QUEUED → DISPATCHING → DISPATCHED → CLAIMED → RUNNING → SUBMITTED → VERIFYING → COMPLETED
  plus FAILED, TIMEOUT, CANCELLED and BLOCKED. DISPATCHED isn't RUNNING (a board task waits for its Director to hand it
  out, an agent task for a worker), RUNNING isn't COMPLETED, and COMPLETED means accepted: by you (an agent task's review)
  or by the team's own review and checks (a board task).
- contract(): what a task must have to be dispatched (a title, a destination that exists) and what it must deliver
  (acceptance criteria, required outputs). A task whose contract can't be met is BLOCKED with the reason, never retried.
- verify(): an agent's "done" is checked before it reaches your review: a result to show, every required output named,
  and (CONTROL_VERIFY_MODEL=1) a second model judging the acceptance criteria. A failed check goes back to the agent once
  with the checker's notes. Your acceptance stays the last step: nothing is COMPLETED because an agent said so.
- watchdog(): an agent run with no sign of life after RUN_TIMEOUT is marked TIMEOUT (a "transient" failure, so the
  dispatcher's retry policy runs it again with a growing wait). It marks, never kills: a late finish of the old run is
  discarded (control_hub._run_task writes only while its run_key is the task's).
- unclaimed(): a task on a team's board that nobody took for CLAIM_TIMEOUT is given to the team's least-loaded agent once.
- pick(): the scheduler: an agent of the task's team that is active, has room and whose model isn't failing right now, else
  one from the mission's supporting teams, else AXoR's recommendation.
- dead(): the dead-letter rule (out of tries, contract invalid, the team gave up) and escalate(): an audit line and a push to
  the owner once a day per task.
- execution()/trace(): the Execution Monitor and the per-task diagnosis (Control Hub → Tasks), with reconcile(): missions
  and tasks counted from the same records, so "0 open missions, 15 open tasks" reads as what it is (the Mission engine
  counts custom missions; the competition's tasks belong to predefined missions) and any task whose mission is gone shows.
- retry()/reassign(): the monitor's controls.
"""
import hashlib, json, logging, os, re, time, uuid

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

log = logging.getLogger("scout.control.lifecycle")
RUN_TIMEOUT = max(300, int(os.getenv("CONTROL_RUN_TIMEOUT", "2700") or 2700))        # an agent run with no sign of life after this is a timeout
CLAIM_TIMEOUT = max(900, int(os.getenv("CONTROL_CLAIM_TIMEOUT", "10800") or 10800))  # a board task nobody took after this is handed out by AXoR
VERIFY_MODEL = os.getenv("CONTROL_VERIFY_MODEL", "0") == "1"                         # a second model judges the acceptance criteria (spends tokens)
BACKOFF_MAX = 6 * 3600   # the longest wait between two tries
TIMED_OUT = "Timed out"
FAILED_CHECK = "Failed its checks"
INVALID = "Invalid task contract"
STAGES = ["CREATED", "QUEUED", "DISPATCHING", "DISPATCHED", "CLAIMED", "RUNNING", "SUBMITTED", "VERIFYING", "COMPLETED"]
OFF_PATH = ["FAILED", "TIMEOUT", "CANCELLED", "BLOCKED"]
LABEL = {"CREATED": "Created", "QUEUED": "Queued", "DISPATCHING": "Dispatching", "DISPATCHED": "Dispatched", "CLAIMED": "Claimed",
         "RUNNING": "Running", "SUBMITTED": "Submitted", "VERIFYING": "Verifying", "COMPLETED": "Completed", "FAILED": "Failed",
         "TIMEOUT": "Timed out", "CANCELLED": "Cancelled", "BLOCKED": "Blocked"}
# what a template task must deliver (control_missions.TEMPLATE keys); every other task gets DEFAULT_ACCEPT
TEMPLATE_ACCEPT = {
    "infra": ["Names what the miner runs on: hardware or sandbox, dependencies, the validator-facing endpoint, monitoring",
              "Lists what's left for you (registering a hotkey, spending TAO) without doing it"],
    "interfaces": ["Names every interface and output format the competition's validators score", "Says how each was tested in the sandbox, with the result"],
    "availability": ["States whether the miner is up, reachable and scored", "Lists errors and restarts since the last check and what to fix"],
    "deliverables": ["Lists everything the competition asks to be submitted, checked against its rules", "Names the deadline; submitting stays yours"],
}
DEFAULT_ACCEPT = ["The result does what the title asks, as a finished piece of work (not a plan to do it later)"]
DEFERS = re.compile(r"^\s*(i will|i'll|i would|we will|next,? i|i plan to|i can't|i cannot|i'm unable|i am unable|unable to)\b", re.I)


# Structured requirements (Owner decision 2026-11-11, D-017): four layers kept apart on every task. Additive, nullable columns
# (RC1 ignores them, so a rollback needs no reverse step); REQ_COLS is also what tools/req_migrate.py --reverse drops.
REQ_COLS = [("needs_by", "TEXT"), ("needs_at", "REAL"), ("needs_confirm", "TEXT"), ("needs_verify", "TEXT")]


def ensure_schema(db):
    cols = {c["name"] for c in db.q("PRAGMA table_info(ctl_tasks)")}
    for name, ddl in [("run_key", "TEXT"), ("accept", "TEXT"), ("outputs", "TEXT"), ("verify", "TEXT"), ("needs", "TEXT")] + REQ_COLS:  # needs: G5 Phase 1
        if name not in cols: db.q(f"ALTER TABLE ctl_tasks ADD COLUMN {name} {ddl}")
    ensure_req_schema(db)


def ensure_req_schema(db):
    """The decisions a person took on inferred suggestions (one per task, capability and value; value '' = none)."""
    db.q("""CREATE TABLE IF NOT EXISTS task_req_decisions (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, task_id INTEGER, cap TEXT,
            value TEXT DEFAULT '', decision TEXT, by_user TEXT, at REAL, note TEXT, UNIQUE (kind, task_id, cap, value))""")


def _j(s, d=None):
    try: return json.loads(s) if s else d
    except (TypeError, ValueError): return d


def _clip(s, n): s = str(s or ""); return s if len(s) <= n else s[:n - 1] + "…"


def _lines(s): return [x.strip(" -•\t") for x in str(s or "").splitlines() if x.strip(" -•\t")]


def _hist(r, what, by="AXoR"):
    return json.dumps(((_j(r.get("history"), []) or []) + [{"ts": time.time(), "by": by, "what": what}])[-40:])


def backoff(base, n):
    """The wait before try n (1, 2, 3…): base, 2 × base, 4 × base…, at most BACKOFF_MAX."""
    return min(BACKOFF_MAX, base * 2 ** max(0, n - 1))


def new_key(): return uuid.uuid4().hex[:16]


# ---------- capability requirements (G5 Phase 1, D-014, gap G-27) ----------
# What a task needs from its environment before it can do its work: declared by a person (or, later, a planner) on the task,
# or inferred from its title and detail. Phase 1 only records and shows them; nothing is gated on them yet (Phase 2's
# preflight checks them before dispatch). Stored on both kinds of task: ctl_tasks.needs and mw_tasks.needs hold the declared
# ones as a JSON list of "cap" or "cap:value" strings; inferred ones are read from the text whenever they're asked for, so they
# follow edits and cover every board task, however it was made.
CAPABILITIES = {
    "docker": "A Docker engine that builds, runs, measures and pushes containers",
    "registry": "Push access to a container registry (and the pushed image's digest)",
    "vm": "A virtual machine (KVM)",
    "internet": "Internet from the sandbox (package installs, clones, downloads)",
    "git": "A git repository the sandbox clones over HTTPS, read only: git:<host>/<owner>/<repo> (it needs the team's sandbox internet)",
    "postgres": "PostgreSQL beside the sandbox run",
    "clickhouse": "ClickHouse beside the sandbox run",
    "gpu": "A GPU",
    "ram": "At least this much memory, in GB",
    "credential": "A named key, token or wallet the work uses",
    "approval": "A person's approval for an external action (register, submit, publish, deploy)",
    "live_data": "Live data AXoR reads for the task with its own server tools, never sandbox internet: live_data:web/<host>, live_data:chain (snapshots) or live_data:chain/query (chain storage beyond them)",
}
# D-024: live data, kept apart from sandbox internet. The value names the source; the source kind says how AXoR gets it, how fresh it
# must be and how readiness verifies it (mission_ops._live_data). "internet" stays what it was: the sandbox's own egress.
LIVE_SOURCES = {
    "web": {"method": "web_read: AXoR fetches the page or API itself (server-side), the sandbox has no part in it",
            "fresh_h": 24, "verify": "a live server-side read now of the team's saved page for that host (else its home page): a page with content "
                      "passes; a wrong or empty source fails; a timeout, network error, 429 or 5xx is unknown. A past fetch is "
                      "reported, never the gate"},
    "chain": {"method": "AXoR's chain snapshots of the subnet (mh_samples), read through the team's leaderboard and changes tools",
              "fresh_h": 2, "verify": "the team's competition's latest chain snapshot (block and time) is within the freshness window: stale fails, "
                        "none is unknown, and a collector whose latest read failed is unknown unless a fresh snapshot exists; a "
                        "brief is never evidence"},
}


def live_spec(value):
    """{kind, target, method, fresh_h, verify} of a live_data value ("web", "web/docs.ridges.ai", "chain", "chain/61"); None if not one."""
    kind, _, target = str(value or "").partition("/")
    spec = LIVE_SOURCES.get(kind)
    return {"kind": kind, "target": target or None, **spec} if spec else None
# (capability, pattern, value group or None[, flags]): an action that needs it, not a mention. "Dockerfile", "Docker Hub",
# MINER_DOCKER_PORT or docker_utils alone are writing or reading about Docker, so they infer nothing.
_NEED_RULES = (
    ("docker", r"\bdocker[ -](?:build|run|push|pull|stats|compose|exec|logs|rm|tag|login|inspect|create|cp)\b", None),  # not "images": "Docker images" is a noun as often
    ("docker", r"\b(?:build|push|pull|run|start|stop|rebuild)(?:s|ing)?[ \t]+(?:and[ \t]+(?:push|run|tag)[ \t]+)?(?:the|a|an|our|your|this)?[ \t]*(?:[\w-]+[ \t]+){0,2}(?:image|container)s?\b", None),
    ("docker", r"--image\s+(?:mode|\S+@sha256)|\blive[- ](?:bench|container)\b|\bmock validator against the live\b", None),
    ("docker", r"\b(?:run|in)[ \t]+(?:the|a)?[ \t]*(?:joint[ \t]+)?docker[ \t]+(?:steps?|session)\b|\bjoint docker session\b", None),  # review of the 39 production suggestions, 11-11, proposed to the Owner: #3188, #3326
    ("docker", r"\b(?:against|on|inside|in)[ \t]+(?:the|a)[ \t]+(?:built|running|live|real)[ \t]+(?:image|container)\b", None),  # #3141
    ("registry", r"\bpush(?:es|ed|ing)?[ \t]+(?:it[ \t]+|the[ \t]+|an?[ \t]+|our[ \t]+|your[ \t]+)?(?:[\w-]+[ \t]+){0,2}image\b|\bpush(?:es|ed|ing)? to (?:docker ?hub|ghcr|the registry)\b|\bdocker push\b", None),
    # not "image digest": recording a local image's digest needs no registry (review of the 39 production suggestions, 11-11, proposed to the Owner: #3188)
    ("vm", r"\bkvm\b|\bvirtual machine\b", None),
    ("internet", r"\b(?:pip3?|npm|apt(?:-get)?) install\b|\bgit clone\b|\bwget\b|\bcurl\s+(?:-\S+\s+)*https?://|\bdocker pull\b", None),
    # a clone names its repository: the address's host/owner/repo (".git" and anything after the repo left out)
    ("git", r"\bgit\s+(?:clone|fetch|pull|ls-remote)\s+(?:(?!https?://)\S+\s+){0,4}https?://(?:www\.)?((?:[a-z0-9-]+\.)+[a-z]{2,}/[\w.-]+/[\w-]+(?:\.(?!git\b)[\w-]+)*)", 1),
    ("postgres", r"\bpostgres(?:ql)?\b", None),
    ("clickhouse", r"\bclickhouse\b", None),
    ("gpu", r"\bgpu\b|\bcuda\b", None),
    ("ram", r"\b(\d{1,3})\s*(?:gb|gib|g)\s+(?:of\s+)?(?:ram|memory)\b", 1),
    ("credential", r"\b([A-Z][A-Z0-9_]*(?:API_KEY|_TOKEN|_SECRET))\b", 1, 0),  # an environment variable's name: case matters
    # a key is needed when the work signs or registers with it, not when it is named: public addresses, "the leader's hotkey",
    # "query the coldkey's UIDs" read the chain and need no key (review of the 39 production suggestions, 11-11, proposed to the Owner: 21 of 25 false suggestions were bare mentions)
    ("credential", r"\b(?:sign|signs|signed|signing)[ \t]+(?:\w+[ \t]+){0,2}(?:with|using|by)[ \t]+(?:the|your|our|a|its)?[ \t]*(hotkey|coldkey|wallet)\b", 1),
    ("credential", r"\b(?:unlock|regen(?:erate)?|import|load|use)(?:s|d|ing)?[ \t]+(?:the|your|our|a|its)?[ \t]*(hotkey|coldkey|wallet)\b", 1),
    ("credential", r"\bregister(?:s|ed|ing)?[ \t]+(?:the|your|our|a)?[ \t]*(hotkey)\b", 1),
    ("approval", r"\b(?:register|submit|publish|deploy)(?:s|ing)?[ \t]+(?:the|a|an|our|your)?[ \t]*(?:[\w-]+[ \t]+){0,2}(?:hotkey|uid|miner|commit|image|submission)s?\b", None),
)
# D-024: live data a task reads (suggestions only, like every inferred need). A URL names its host; web_read, taostats or a dashboard
# mean the web; the metagraph, Uids or on-chain weights, stake, incentive or emission mean the chain.
_LIVE_RULES = (
    (re.compile(r"https?://(?:www\.)?((?:[a-z0-9-]+\.)+[a-z]{2,})", re.I), lambda m: f"web/{m.group(1).lower()}"),
    # a bare host, written lowercase as hosts are (an operator called "1T1B.AI" is not a website)
    (re.compile(r"(?<![\w./@-])((?:[a-z0-9-]+\.)+(?:ai|io|com|org|net|dev|xyz))(?=[/\s),;:]|$)"), lambda m: f"web/{re.sub(r'^www[.]', '', m.group(1))}"),
    (re.compile(r"\btaostats\b", re.I), lambda m: "web/taostats.io"),
    (re.compile(r"\bweb_read\b|\bdashboard\b", re.I), lambda m: "web"),
    # Milestone 4: a storage map (Uids[…], Keys[…], …) or a raw subtensor query is chain storage beyond the snapshots: chain/query
    (re.compile(r"\b(?:Uids|Keys|Owner|OwnedHotkeys|NetworksAdded|SubnetworkN|Stake|TotalHotkeyAlpha|Weights|Bonds|Axons)\[|\bquery_(?:map_)?subtensor\b"),
     lambda m: "chain/query"),
    (re.compile(r"\bmetagraph\b|\bon[- ]chain\b|\b(?:chain|validator) (?:weights?|snapshots?|data|quer(?:y|ies)|stake)\b|"
                r"\b(?:first|next|each|every|latest) (?:chain )?snapshot\b|\b(?:operators|changes)(?:/leaderboard)? tools?\b|"
                r"\boperators/leaderboard\b|\bleaderboard (?:read|page|snapshot)s?\b|\bset weights? on\b|\bvalidator stake\b|"
                r"\bfrom the briefing\b", re.I), lambda m: "chain"),
)
_SLOT_ADMIN = re.compile(r"^\s*(?:free|rename|delete|prune|approve|cite|record|stop)\b[^\n]*\b(?:slots?|saved[- ]reads?|watch(?:es)?|web reads?|recipes?|data/web/)", re.I)
# A task that only writes about the work (adds a step to a checklist or a runbook, records something in the notebook) needs nothing
# from the environment, whatever its words describe (review of the 39 production suggestions, 11-11, proposed to the Owner: #3265, #3325, #3371, #3388).
_DOC_TASK = re.compile(r"^\s*(?:(?:add|update|document|record|amend|note)\b[^\n]*?\b(?:to|in|into|on)\s+(?:the\s+|a\s+)?[\w/.\- ]{0,40}?\b(?:checklist|runbook|readme|notebook|docs?|guide)\b(?:\s*/\s*[\w ]+)?\s*\.?\s*$"
                       r"|write\s+(?:the|a|an)\s+[\w/\- ]{0,60}?\b(?:checklist|runbook|readme|guide|note|docs?)\b)", re.I)
_SECOND_ACTION = re.compile(r"(?:\band\b|\bthen\b|,)\s+(?:run|build|push|pull|deploy|register|submit|publish|start|install)\b", re.I)  # "… and run docker build"
_NEED_RES = [(r[0], re.compile(r[1], r[3] if len(r) > 3 else re.I), r[2]) for r in _NEED_RULES]
NEED_RE = re.compile(r"^(" + "|".join(CAPABILITIES) + r")(?::([\w.@/+-]{1,80}))?$")
GIT_REPO = re.compile(r"^(?:[a-z0-9-]+\.)+[a-z]{2,}/[\w.-]{1,39}/[\w.-]{1,60}$")  # host/owner/repo, as git:<value> names it


def git_repo(value):
    """"host/owner/repo" from a git need's value (lower-case host, no ".git"), or None when it doesn't name one repository."""
    v = re.sub(r"\.git$", "", str(value or "").strip().strip("/"))
    host, _, rest = v.partition("/")
    v = host.lower() + "/" + rest
    return v if GIT_REPO.match(v) and ".." not in v else None


_GIT_URL = re.compile(r"\bgit\s+(?:clone|fetch|pull|ls-remote)\s+(?:(?!https?://)\S+\s+){0,4}https?://(?:[^/@\s]+@)?(?:www\.)?"
                      r"((?:[a-z0-9-]+\.)+[a-z]{2,}/[\w.-]+/[\w-]+(?:\.(?!git\b)[\w-]+)*)", re.I)


def git_requested(command):
    """The repositories a command asks git for, as host/owner/repo, in order, each once: what was requested, as opposed to what
    a task declared (its git: needs) and what a run really checked out (its source record)."""
    out = []
    for m in _GIT_URL.finditer(str(command or "")):
        r = git_repo(m.group(1))
        if r and r not in out: out.append(r)
    return out[:20]


def parse_needs(items):
    """Declared needs from a person or a planner: ["docker", "ram:16", "credential:BEX_CHALLENGE_API_KEY"] → the same, checked.
    Raises ValueError naming what isn't a capability."""
    out = []
    for x in items or []:
        s = str(x or "").strip()
        if not s: continue
        cap, colon, val = s.partition(":")
        m = NEED_RE.match(cap.lower() + colon + val)
        if not m: raise ValueError(f"“{s[:40]}” isn't a capability: use one of {', '.join(CAPABILITIES)}, optionally with :value")
        if m.group(1) == "ram" and m.group(2) and not m.group(2).isdigit(): raise ValueError("ram takes whole GB, e.g. ram:16")
        if m.group(1) == "git" and not git_repo(m.group(2)): raise ValueError("git names its repository: git:<host>/<owner>/<repo>, e.g. git:github.com/owner/repo")
        if m.group(1) == "live_data" and not live_spec(m.group(2)):
            raise ValueError("live_data names its source: live_data:web, live_data:web/<host> or live_data:chain")
        if m.group(0) not in out: out.append(m.group(0))
    return out[:20]


def infer_needs(text):
    """[{cap, value, source: "inferred", why}] from a task's words: one per capability and value, with the words that said so.
    Suggestions only (Owner decision 2026-11-11): nothing inferred is ever declared or gates a task."""
    t, out, seen = str(text or ""), [], set()
    title = t.split("\n", 1)[0]
    if _DOC_TASK.match(title) and not _SECOND_ACTION.search(title): return out  # the doc is the work: what it describes isn't needed
    for cap, rx, g in _NEED_RES:
        for m in rx.finditer(t):
            v = m.group(g).lower() if g and cap == "credential" and m.group(g).lower() in ("hotkey", "coldkey", "wallet") else (m.group(g) if g else None)
            if (cap, v) in seen: continue
            seen.add((cap, v))
            out.append({"cap": cap, "value": v, "source": "inferred", "why": " ".join(m.group(0).split())[:80]})
    web_hosts = set()
    if _SLOT_ADMIN.search(title): return out  # managing saved reads or watches names hosts it doesn't read (held-out sample, 11-12)
    for rx, val in _LIVE_RULES:
        for m in rx.finditer(t):
            v = val(m)
            if v == "web" and web_hosts: continue  # a named host says more than "the web"
            if ("live_data", v) in seen: continue
            if v.startswith("web/"): web_hosts.add(v)
            seen.add(("live_data", v))
            out.append({"cap": "live_data", "value": v, "source": "inferred", "why": " ".join(m.group(0).split())[:80]})
    if ("live_data", "chain/query") in seen:  # the storage query says more than "the chain": never suggest the snapshot check beside it
        out = [n for n in out if not (n["cap"] == "live_data" and n["value"] == "chain")]
    return out


# Planner outputs (G5-2 M2, Owner D-015 D3 and clarification E): schema version 2 asks every planned task for "needs", an empty
# array when it needs nothing special. Version 1 outputs (no "needs" key: older planners, fake models, stored plans) stay valid:
# their tasks are undeclared, and what their text suggests becomes a confirmation item, never a block (D4, F).
PLANNER_SCHEMA_VERSION = 2
NEEDS_SCHEMA = {"type": "array", "items": {"type": "string"},
                "description": "What the task's environment must provide, [] when nothing special: " + ", ".join(
                    f"{k}{':<GB>' if k == 'ram' else ':<NAME>' if k == 'credential' else ':web/<host>|chain' if k == 'live_data' else ':<host>/<owner>/<repo>' if k == 'git' else ''}" for k in CAPABILITIES) +
                ". Only what the work cannot be done without (writing a Dockerfile needs nothing; building or running the image needs docker)."}
NEEDS_RULE = ("needs: for every task, the capabilities its environment must provide (docker, registry, vm, internet, git:<host>/<owner>/<repo>, postgres, clickhouse, "
              "gpu, ram:<GB>, credential:<NAME>, approval, live_data:web/<host> or live_data:chain for live data AXoR reads for it), or [] when none. Declare only what the work can't be done without; "
              "AXoR checks each against the real environment before the task is handed out. A task that clones or fetches a repository declares "
              "git:<host>/<owner>/<repo> for each one and internet; a task that installs packages or downloads files in the sandbox declares internet; "
              "reading a web page or API with web_read is live_data, not internet.")


def planner_needs(item):
    """(stored needs, version) of one planned task: ("[...]" JSON, 2) when the planner declared them ("[]" = declared none),
    (None, 1) when it didn't (a version-1 output). Unknown capabilities are dropped, not fatal: the rest still count."""
    if not isinstance(item, dict) or "needs" not in item or item.get("needs") is None: return None, 1
    raw = item.get("needs") if isinstance(item.get("needs"), list) else [item.get("needs")]
    kept = []
    for x in raw[:20]:
        try: kept += [n for n in parse_needs([x]) if n not in kept]
        except ValueError: continue
    return json.dumps(kept), 2


def declared(r):
    """True when the task's needs were declared (by a person or a version-2 planner), even as []; False when undeclared."""
    return r.get("needs") is not None and _j(r.get("needs"), None) is not None


def needs_of(r, decided=None):
    """A task's capability requirements: the declared ones (row["needs"]) and the inferred ones its text adds, declared first.
    Each {cap, value, source: declared | inferred, why}; an inferred one also carries `decision` (accepted / rejected / None)
    when `decided` ({(cap, value or ""): decision}) is given. Only "declared" ever counts as a requirement."""
    declared = []
    for s in _j(r.get("needs"), []) or []:
        cap, _, v = str(s).partition(":")
        declared.append({"cap": cap, "value": v or None, "source": "declared", "why": ""})
    caps = {d["cap"] for d in declared}  # a declared capability replaces what the text suggests for it
    inferred = [n for n in infer_needs(f"{r.get('title') or ''}\n{r.get('detail') or ''}") if n["cap"] not in caps]
    for n in inferred:
        d = (decided or {}).get((n["cap"], n["value"] or ""))
        n["decision"] = d.get("decision") if isinstance(d, dict) else d
    return declared + inferred


# ---------- structured requirements: inferred, declared, confirmed, verified (Owner decision 2026-11-11, D-017) ----------
# inferred   what the words suggest: a suggestion only, never a requirement, never a block. A person accepts it (it becomes
#            declared, by them) or rejects it (it stops asking). Decisions live in task_req_decisions.
# declared   row.needs: the list the task says it needs, by a person or a version-2 planner (needs_by/needs_at). "[]" = declared
#            none: no external dependency. NULL = undeclared.
# confirmed  row.needs_confirm {by, at, hash}: a person reviewed the declared list; it holds only while the list is unchanged.
# verified   row.needs_verify {at, hash, ok, items}: AXoR's live environment check of the declared list (task_readiness, active).
REQ_KINDS = {"ctl": "ctl_tasks", "mw": "mw_tasks"}
# D-018: a board task the Director dropped is done but not completed work. ONE definition, in SQL here and in Python in
# mission_ops.closed_as(): closed_as when it is set (the closing path wrote it), else the Director's note "Dropped by …" (rows
# from before the column, or not migrated). Every count of finished board work adds not_dropped(db).
NOT_DROPPED_SQL = "COALESCE(note, '') NOT LIKE 'Dropped by %'"  # a database without closed_as (older schema, hand-made test tables)


def closed_as(t):
    """How a done board task was closed (D-018), the Python twin of not_dropped(): mw_tasks.closed_as when set, else read from
    the note the Director leaves ("Dropped by …" / "Done, by your answer to …")."""
    if t.get("closed_as"): return t["closed_as"]
    note = str(t.get("note") or "")
    return "dropped" if note.startswith("Dropped by ") else "closed" if note.startswith("Done, by your answer to ") else None


def not_dropped(db):
    """The SQL condition 'this board task wasn't dropped', for mw_tasks unaliased; matches closed_as(). Kept on the database
    object, never in a cache keyed by id(): a recycled id would hand one database's answer to another (G-24's cause)."""
    hit = getattr(db, "_not_dropped_sql", None)
    if hit: return hit
    try: cols = {c["name"] for c in db.q("PRAGMA table_info(mw_tasks)")}
    except Exception: cols = set()  # noqa: BLE001
    note = "CASE WHEN COALESCE(note, '') LIKE 'Dropped by %' THEN 'dropped' ELSE '' END" if "note" in cols else "''"
    sql = (f"COALESCE(closed_as, {note}) != 'dropped'" if "closed_as" in cols else
           NOT_DROPPED_SQL if "note" in cols else "1=1")  # a hand-made table with neither: nothing is marked dropped
    if "closed_as" in cols:  # not kept before start-up adds the column
        try: db._not_dropped_sql = sql
        except AttributeError: pass
    return sql


def needs_hash(items): return hashlib.sha256(json.dumps(sorted(items or [])).encode()).hexdigest()[:16]


def _nk(cap, value): return f"{cap}:{value}" if value else cap


def req_ref(task_ref):
    """("ctl", 12) from "ctl:t12", ("mw", 3) from "mw_task:3"; None for anything else."""
    m = re.fullmatch(r"ctl:t(\d+)|mw_task:(\d+)", task_ref or "")
    return None if not m else ("ctl", int(m.group(1))) if m.group(1) else ("mw", int(m.group(2)))


def _has_req(db):
    try: db.q("SELECT 1 FROM task_req_decisions LIMIT 1"); return True
    except Exception: return False  # noqa: BLE001 - an older database: no decisions yet


def decisions(db, kind, ids):
    """{task_id: {(cap, value): decision row}} for these tasks."""
    ids = [int(i) for i in ids or []]
    if not ids or not _has_req(db): return {}
    out = {}
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        for d in db.q(f"SELECT * FROM task_req_decisions WHERE kind=? AND task_id IN ({','.join('?' * len(part))})", [kind, *part]):
            out.setdefault(d["task_id"], {})[(d["cap"], d["value"] or "")] = d
    return out


def requirements(db, kind, r, decided=None):
    """One task's requirements, the four layers apart:
    {status: undeclared | declared | confirmed | verified, external: True/False/None, declared, inferred, pending, confirmed, verified}."""
    if decided is None: decided = decisions(db, kind, [r["id"]]).get(r["id"], {})
    dec = _j(r.get("needs"), None) if r.get("needs") is not None else None
    h = needs_hash(dec) if dec is not None else None
    inferred = []
    for n in infer_needs(f"{r.get('title') or ''}\n{r.get('detail') or ''}"):
        d = decided.get((n["cap"], n["value"] or ""))
        inferred.append({"cap": n["cap"], "value": n["value"], "why": n["why"], "decision": d and d["decision"], "by": d and d["by_user"],
                         "at": d and d["at"], "note": d and d["note"], "declared": dec is not None and _nk(n["cap"], n["value"]) in dec})
    conf, ver = _j(r.get("needs_confirm"), None), _j(r.get("needs_verify"), None)
    conf = conf and {**conf, "current": conf.get("hash") == h}
    ver = ver and {**ver, "current": ver.get("hash") == h}
    status = "undeclared" if dec is None else "verified" if ver and ver["current"] and ver.get("ok") else "confirmed" if conf and conf["current"] else "declared"
    return {"status": status, "external": None if dec is None else bool(dec),
            "declared": None if dec is None else {"needs": dec, "by": r.get("needs_by") or _declarer(r), "at": r.get("needs_at")},
            "inferred": inferred, "pending": sum(1 for n in inferred if not n["decision"] and not n["declared"]),
            "confirmed": conf or None, "verified": ver or None}


def _declarer(r):
    """Who declared a list written before needs_by existed, or by a planner path that doesn't stamp it: read from the task's origin."""
    o = str(r.get("origin") or "")
    if o.startswith("plan:"): return "planner (board plan)"
    if o.startswith("agent:"): return "planner (an agent's follow-up)"
    if o == "intelligence": return "planner (Mission Intelligence)"
    return "unattributed (declared before D-017)"


def _task_row(db, kind, tid):
    if kind not in REQ_KINDS: raise HTTPException(404, "Unknown kind of task.")
    r = db.q(f"SELECT * FROM {REQ_KINDS[kind]} WHERE id=?", (int(tid),), one=True)
    if not r: raise HTTPException(404, "There's no such task.")
    return r


def declare(db, kind, tid, needs, by, source="person"):
    """Writes the declared list ([] = declared none; None = undeclared again). A planner declares with source "planner"; nothing
    else declares: inference never does. A changed list leaves an earlier confirmation and verification not current (their hash)."""
    items = None if needs is None else parse_needs(needs)
    db.q(f"UPDATE {REQ_KINDS[kind]} SET needs=?, needs_by=?, needs_at=? WHERE id=?",
         (None if items is None else json.dumps(items), None if items is None else (by if source == "person" else f"{source}:{by}" if by else source),
          None if items is None else time.time(), int(tid)))
    return items


def decide(db, kind, tid, cap, value, decision, by, note=""):
    """A person's decision on one inferred suggestion. accept: it joins the declared list (declared by that person);
    reject: it stops asking. Either is kept with who and when."""
    if decision not in ("accepted", "rejected"): raise HTTPException(422, "decision is accepted or rejected.")
    r = _task_row(db, kind, tid)
    try: n = parse_needs([_nk(cap, value)])[0]
    except (ValueError, IndexError) as e: raise HTTPException(422, str(e) or "Not a capability.")
    cap, _, value = n.partition(":")
    ensure_req_schema(db)
    db.q("DELETE FROM task_req_decisions WHERE kind=? AND task_id=? AND cap=? AND value=?", (kind, int(tid), cap, value or ""))
    db.q("INSERT INTO task_req_decisions (kind, task_id, cap, value, decision, by_user, at, note) VALUES (?,?,?,?,?,?,?,?)",
         (kind, int(tid), cap, value or "", decision, by, time.time(), _clip(note, 300) or None))
    if decision == "accepted":
        cur = _j(r.get("needs"), None) or []
        if n not in cur: declare(db, kind, tid, cur + [n], by)
    return requirements(db, kind, _task_row(db, kind, tid))


def confirm(db, kind, tid, by, note=""):
    """A person confirms the declared list as reviewed (its hash, so an edit afterwards needs a new confirmation). Every suggestion
    still undecided is settled with it: accepted when the list has it, rejected when it doesn't. An undeclared task can't be
    confirmed: declare it first ([] when it needs nothing)."""
    r = _task_row(db, kind, tid)
    dec = _j(r.get("needs"), None) if r.get("needs") is not None else None
    if dec is None: raise HTTPException(409, "Its requirements aren't declared: declare them first ([] when it needs nothing external).")
    now = time.time()
    ensure_req_schema(db)
    done = decisions(db, kind, [tid]).get(int(tid), {})
    for n in infer_needs(f"{r.get('title') or ''}\n{r.get('detail') or ''}"):
        if (n["cap"], n["value"] or "") in done: continue
        db.q("INSERT INTO task_req_decisions (kind, task_id, cap, value, decision, by_user, at, note) VALUES (?,?,?,?,?,?,?,?)",
             (kind, int(tid), n["cap"], n["value"] or "", "accepted" if _nk(n["cap"], n["value"]) in dec else "rejected", by, now, "settled by confirming the declared list"))
    db.q(f"UPDATE {REQ_KINDS[kind]} SET needs_confirm=? WHERE id=?",
         (json.dumps({"by": by, "at": now, "hash": needs_hash(dec), "note": _clip(note, 300)}), int(tid)))
    return requirements(db, kind, _task_row(db, kind, tid))


def record_verification(db, task_ref, t, items):
    """task_readiness (active) after checking the declared list against the real environment: the verified layer. Only when the
    task's declared list was checked as a whole; written on the row, never a block of its own."""
    k = req_ref(task_ref)
    if not k or t.get("needs") is None: return
    dec = _j(t.get("needs"), None)
    if dec is None: return
    try:
        cols = {c["name"] for c in db.q(f"PRAGMA table_info({REQ_KINDS[k[0]]})")}
        if "needs_verify" not in cols: return
        rows = [{"cap": i["cap"], "value": i.get("value"), "state": i["state"], "probe": (i.get("probe") or {}).get("state"),
                 "evidence": _clip((i.get("probe") or {}).get("evidence"), 200)} for i in items if i.get("cap") != "auth"]
        db.q(f"UPDATE {REQ_KINDS[k[0]]} SET needs_verify=? WHERE id=?",
             (json.dumps({"at": time.time(), "hash": needs_hash(dec), "ok": all(x["state"] == "ready" for x in rows), "items": rows}), k[1]))
    except Exception as e:  # noqa: BLE001 - the record is evidence, never the gate
        log.warning("requirements: verification not recorded for %s: %s", task_ref, e)


# ---------- the contract ----------
def accept_of(r):
    return _lines(r.get("accept")) or TEMPLATE_ACCEPT.get(r.get("template") or "") or DEFAULT_ACCEPT


def outputs_of(r): return _lines(r.get("outputs"))


def contract(ch, me, r):
    """{"ok", "problems", "accept", "outputs", "needs"}: what the task must have to be dispatched, what it must deliver, and the
    capabilities its environment must give it (needs_of: declared and inferred; recorded, not yet checked: G5 Phase 2)."""
    probs = []
    if len((r.get("title") or "").strip()) < 3: probs.append("it has no title")
    route = r.get("route")
    if route not in ("board", "agent", "mission"): probs.append(f"it has no destination (route '{route or ''}')")
    v = ch._view(me)
    u = next((x for x in v["units"] if x["id"] == r.get("unit_id")), None) if r.get("unit_id") else None
    if r.get("unit_id") and not u: probs.append("its team no longer exists")
    if route == "board":
        wid = ch._comp_of(u) if u else None
        m = re.fullmatch(r"comp:(\d+)", r.get("mission") or "")
        if not wid and not u and m: wid = int(m.group(1))
        if not wid or wid not in ch._comps(me["id"]): probs.append("it goes to a team board, but its team isn't a Competition team with a board")
    if route == "agent" and not u and not r.get("agent_key"): probs.append("it has neither a team nor an agent")
    if r.get("agent_key") and r["agent_key"] not in v["names"]: probs.append("its agent is no longer in your organization")
    return {"ok": not probs, "problems": probs, "accept": accept_of(r), "outputs": outputs_of(r), "needs": needs_of(r)}


DISPATCHING = "dispatching to the team's board"


def adopt(ch, r):
    """Idempotent board dispatch: when the task's last step is DISPATCHING (a pass wrote it, then stopped before linking the
    board task it made), the board task made since then with its title and not linked to another task is the one: link it
    instead of making a second. Returns its id or None."""
    h = _j(r.get("history"), []) or []
    if not h or not str(h[-1].get("what") or "").startswith(DISPATCHING): return None
    ts, title = h[-1].get("ts") or 0, _clip(r.get("title"), 160)
    try:
        rows = ch.db.q("SELECT * FROM mw_tasks WHERE title=? ORDER BY id DESC LIMIT 20", (title,))
        taken = {x["ref"] for x in ch.db.q("SELECT ref FROM ctl_tasks WHERE ref LIKE 'mw_task:%' AND id!=?", (r["id"],))}
    except Exception:  # noqa: BLE001
        return None
    for x in rows:
        made = x.get("created") or x.get("updated")
        if f"mw_task:{x['id']}" not in taken and (made is None or made >= ts - 5): return x["id"]
    return None


def board_detail(r):
    """The board task's detail with the contract written in, so the team's own checks read the same acceptance criteria."""
    acc, outs = accept_of(r), outputs_of(r)
    tail = "\n\nDone when:\n" + "\n".join(f"- {a}" for a in acc) + ("\n\nRequired outputs:\n" + "\n".join(f"- {o}" for o in outs) if outs else "")
    return _clip((r.get("detail") or "") + tail, 4000)


# ---------- verification ----------
VERDICT = {"type": "object", "additionalProperties": False, "required": ["criteria", "feedback"], "properties": {
    "criteria": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["criterion", "met", "evidence"], "properties": {
        "criterion": {"type": "string"}, "met": {"type": "boolean"}, "evidence": {"type": "string"}}}},
    "feedback": {"type": "string"}}}


def verify(ch, me, r, out, agent_name="the agent"):
    """The checks between an agent's "done" and your review. Returns the report saved on the task:
    {"ok", "why", "checks": [{"check", "ok", "note"}], "criteria": [{"criterion", "met", "evidence"}], "by", "at", "tokens"}."""
    res = (out.get("result") or "").strip()
    checks = [{"check": "A result to show", "ok": bool(res), "note": f"{len(res)} characters"}]
    for o in outputs_of(r):
        hit = o.lower() in res.lower()
        checks.append({"check": f"Required output: {o}", "ok": hit, "note": "named in the result" if hit else "not found in the result"})
    lead = DEFERS.search(res[:200] or "")
    checks.append({"check": "Delivers the work, not a promise of it", "ok": not lead,
                   "note": f"opens with “{_clip(res[:80], 80)}”" if lead else "it delivers"})
    crit = [{"criterion": c, "met": None, "evidence": "for your review"} for c in accept_of(r)]
    by, tokens = "checks", 0
    if VERIFY_MODEL and res and all(c["ok"] for c in checks) and getattr(ch, "hub", None):
        spent = [0]
        try:
            from . import agent_core
            model = agent_core.route(ch.hub.llm, me["id"], "other", "verify", choice="auto")[0]
            v = ch.hub.llm.structured(model, "You check another agent's deliverable against its acceptance criteria. You are strict and "
                                      "independent: a criterion is met only when the result itself shows it, not when the agent says so.",
                                      f"Task: {r.get('title')}\n{r.get('detail') or ''}\n\nAcceptance criteria:\n" + "\n".join(f"- {c}" for c in accept_of(r)) +
                                      f"\n\nThe deliverable from {agent_name}:\n{_clip(res, 12000)}", VERDICT, "verify",
                                      on_usage=lambda n: spent.__setitem__(0, spent[0] + n), effort="low")
            got = {(c.get("criterion") or "").strip().lower(): c for c in v.get("criteria") or []}
            crit = [{"criterion": c, "met": bool((got.get(c.lower()) or {}).get("met")), "evidence": _clip((got.get(c.lower()) or {}).get("evidence") or "not judged", 300)}
                    for c in accept_of(r)]
            by, tokens = "model", spent[0]
            if not all(c["met"] for c in crit): checks.append({"check": "Acceptance criteria (second model)", "ok": False, "note": _clip(v.get("feedback") or "", 400)})
        except Exception as e:  # noqa: BLE001 - no model for the check: the plain checks and your review stand
            log.info("verify task %s: %s", r.get("id"), e)
            by = "checks (the second model wasn't available)"
        finally:
            if spent[0] and hasattr(ch.hub, "log_usage"):
                try: ch.hub.log_usage(me, "control", spent[0], None, None)
                except Exception: pass  # noqa: BLE001
    bad = [c for c in checks if not c["ok"]]
    why = "; ".join(f"{c['check'].lower()}: {c['note']}" for c in bad)
    return {"ok": not bad, "why": why, "checks": checks, "criteria": crit, "by": by, "at": time.time(), "tokens": tokens}


# ---------- the canonical stage ----------
def stage(t, r, run=None):
    """(STAGE, note) for a task. `t` is the hub's task (status read through its board task or mission), `r` its ctl_tasks
    row, `run` its latest agent run in the ledger ({"status", "started"}) if any."""
    st, ref, summ = t.get("status"), r.get("ref") or "", r.get("summary") or ""
    if st in ("cancelled", "skipped"): return "CANCELLED", "skipped" if st == "skipped" else ""
    if st == "done": return "COMPLETED", ""
    if st == "failed": return ("TIMEOUT", summ) if summ.startswith(TIMED_OUT) else ("FAILED", summ)
    if st == "proposed": return "CREATED", "a proposal waiting for your approval"
    if summ.startswith(INVALID): return "BLOCKED", summ
    if st == "needs_input": return "BLOCKED", summ or "waiting for your answer"
    if ref.startswith("mw_task:"):
        b = t.get("board_status")
        if b == "blocked": return "BLOCKED", "blocked on the team's board"
        if b == "working": return "RUNNING", "being worked on the team's board"
        if b == "queued": return "CLAIMED", "assigned and queued on the team's board"
        if b == "checking": return "VERIFYING", "the team's checks are running"
        if b == "review": return "SUBMITTED", "delivered on the board, waiting for its review"
        if t.get("board_agent") is not None: return "CLAIMED", "assigned on the team's board"
        return "DISPATCHED", "on the team's board, not taken yet"
    if ref.startswith("mx:"):
        return {"running": ("RUNNING", "its mission is running"), "review": ("SUBMITTED", "")}.get(st, ("DISPATCHED", "sent to Mission Control"))
    if st == "running":
        if run and run.get("status") == "running": return "RUNNING", ""
        return "DISPATCHED", "started, waiting for a worker"
    if st == "review":
        v = _j(r.get("verify"), None)
        return ("VERIFYING", "checked: waiting for your acceptance") if v and v.get("ok") else ("SUBMITTED", "delivered: waiting for your review")
    if st == "todo":
        if r.get("route") == "board" and not ref and r.get("next_try") and (r.get("attempts") or 0): return "QUEUED", "a dispatch to the board failed: tries again"
        return "QUEUED" if (t.get("why") or {}).get("state") in ("dispatch", "retry", "busy") else "CREATED", ""
    return "CREATED", ""


def dead(t, r):
    """The dead-letter reason when no automatic path is left for an open or failed task, else None."""
    from . import control_dispatch as cd
    st, tries, summ = t.get("status"), r.get("attempts") or 0, r.get("summary") or ""
    if summ.startswith(INVALID) and st in ("todo", "needs_input", "failed"): return summ
    if t.get("board_hold") == "failed": return "The team gave up on it after failed runs."
    w = (t.get("why") or {}).get("state")
    if st == "todo" and not r.get("ref") and tries >= cd.MAX_TRIES: return f"Couldn't be dispatched in {tries} tries: {_clip(summ, 200)}"
    if st == "failed" and tries >= cd.MAX_TRIES: return f"Failed after {tries} retries: {_clip(summ, 200)}"
    if st == "needs_input" and tries >= cd.MAX_TRIES and (summ.startswith(cd.NO_DELIVERABLE) or summ.startswith(FAILED_CHECK)): return _clip(summ, 300)
    if w == "stuck": return (t.get("why") or {}).get("text")
    return None


# ---------- the scheduler: who can take it ----------
def _failing(db, key, now):
    """Whether an agent's model is failing right now: its last two runs in the past hour failed on the provider or quota."""
    try:
        rows = db.q("SELECT status, error FROM ac_runs WHERE agent_key=? AND started>? ORDER BY id DESC LIMIT 2", (key, now - 3600))
    except Exception:  # noqa: BLE001 - no ledger
        return False
    if len(rows) < 2: return False
    from .intel_layers import fail_class
    return all(x["status"] == "failed" and fail_class("failed", x["error"] or "") in ("provider", "quota", "rate") for x in rows)


def candidates(ch, me, r, now=None):
    """Every agent who could take the task, with why one can't: its team first, then the mission's supporting teams."""
    now = now or time.time()
    v = ch._view(me)
    units = {u["id"]: u for u in v["units"]}
    teams = []
    u = units.get(r.get("unit_id"))
    if u: teams.append((u, "its team"))
    if (r.get("mission") or "").startswith("comp:"):
        try:
            for s in ch.db.q("SELECT unit_id FROM ctl_mission_teams WHERE user_id=? AND mission=?", (me["id"], r["mission"])):
                if s["unit_id"] in units and all(s["unit_id"] != x["id"] for x, _ in teams): teams.append((units[s["unit_id"]], "a supporting team"))
        except Exception: pass  # noqa: BLE001 - no supporting teams table
    out, seen = [], set()
    for tm, rel in teams:
        sq = set(tm.get("squads") or [])
        for a in v["agents"]:
            if a["key"] in seen or not (a["unit_id"] == tm["id"] or a["unit_id"] in sq): continue
            seen.add(a["key"])
            no = ("inactive" if a["status"] != "active" else "full: no room for another task" if a["load"] >= a["cap"] else
                  "its model is failing right now" if _failing(ch.db, a["key"], now) else "")
            out.append({"key": a["key"], "name": a["name"], "team": tm["name"], "relation": rel, "lead": a["key"] == tm.get("manager_key"),
                        "load": a["load"], "cap": a["cap"], "system": a.get("system"), "eligible": not no, "why_not": no})
    return out


def pick(ch, me, r, avoid=()):
    """(agent key, note) for an agent task: an eligible agent of its team (its lead last, the least loaded first), else of the
    mission's supporting teams, else AXoR's recommendation (control_missions._pick_agent). (None, reason) when nobody can."""
    c = [a for a in candidates(ch, me, r) if a["eligible"] and a["key"] not in avoid]
    for rel in ("its team", "a supporting team"):
        own = sorted((a for a in c if a["relation"] == rel), key=lambda a: (a["lead"], a["load"]))
        if own: return own[0]["key"], ("" if rel == "its team" else f"nobody free on its team: {own[0]['name']} of {own[0]['team']} (supporting the mission) takes it")
    from . import control_missions as cm
    k = cm._pick_agent(ch, me, r)
    if k and k not in avoid: return k, ""
    return None, "Nobody on its team or the mission's supporting teams can take it: add an agent to the team."


# ---------- watchdog, claims, escalation ----------
def watchdog(db, now=None):
    """Agent runs with no sign of life after RUN_TIMEOUT → failed with TIMED_OUT (a transient failure: the dispatcher retries
    it with a growing wait). Returns the task ids it marked."""
    now = now or time.time()
    try:
        rows = db.q("SELECT id, history, updated FROM ctl_tasks WHERE status='running' AND route='agent' AND updated<?", (now - RUN_TIMEOUT,))
    except Exception:  # noqa: BLE001
        return []
    marked = []
    for r in rows:
        try: run = db.q("SELECT id, status, started FROM ac_runs WHERE ref=? ORDER BY id DESC LIMIT 1", (f"ctl:t{r['id']}",), one=True)
        except Exception: run = None  # noqa: BLE001 - no ledger
        if run and run["status"] == "running" and (run["started"] or 0) > now - RUN_TIMEOUT: continue  # started late, still in time
        mins = RUN_TIMEOUT // 60
        msg = f"{TIMED_OUT} after {mins} min: " + ("the run never started (no worker picked it up)" if not run or run["status"] != "running" else "the run didn't finish")
        got = db.q("UPDATE ctl_tasks SET status='failed', summary=?, run_key=NULL, history=?, updated=? WHERE id=? AND status='running' RETURNING id",
                   (msg, _hist(r, f"no sign of life for {mins} min: timed out"), now, r["id"]), one=True)
        if not got: continue
        if run and run["status"] == "running":
            try: db.q("UPDATE ac_runs SET status='timeout', finished=?, error=? WHERE id=? AND status='running'", (now, msg, run["id"]))
            except Exception: pass  # noqa: BLE001
        marked.append(r["id"])
    return marked


def unclaimed(ch, me, now=None):
    """Board tasks AXoR put on a team's board that nobody took for CLAIM_TIMEOUT (team running, autopilot on): given to the
    team's least-loaded active agent, once per task. Returns how many."""
    from . import control_dispatch as cd, mining_work
    now, n = now or time.time(), 0
    rows = ch.db.q("SELECT * FROM ctl_tasks WHERE user_id=? AND status='todo' AND ref LIKE 'mw_task:%'", (me["id"],))
    for r in rows:
        if "not taken in" in (r.get("history") or ""): continue  # once: then it's the team's (and yours)
        L = cd.linked(ch.db, r["ref"]) or {}
        if L.get("board_status") != "todo" or L.get("board_agent") is not None or L.get("team_paused") or L.get("team_autopilot") is False: continue
        b = ch.db.q("SELECT * FROM mw_tasks WHERE id=?", (L["board_id"],), one=True) or {}
        since = b.get("created") or b.get("updated") or r.get("updated") or now
        if since > now - CLAIM_TIMEOUT: continue
        try:
            ags = ch.db.q("""SELECT a.id, a.name, (SELECT COUNT(*) FROM mw_tasks t WHERE t.agent_id=a.id AND t.status NOT IN ('done')) n FROM mw_agents a
                             WHERE a.comp_id=? AND a.active=1 ORDER BY n, a.lead, a.id""", (b.get("comp_id"),))
        except Exception:  # noqa: BLE001
            ags = []
        if not ags: continue
        a = ags[0]
        try: ch.w.update_task(me, L["board_id"], mining_work.TaskPatch(agent=a["id"]))
        except HTTPException as e:
            log.info("claim timeout: board task %s: %s", L["board_id"], e.detail); continue
        hrs = round(CLAIM_TIMEOUT / 3600, 1)
        ch.db.q("UPDATE ctl_tasks SET history=?, updated=? WHERE id=?", (_hist(r, f"not taken in {hrs:g} h on the team's board: given to {a['name']}"), now, r["id"]))
        ch._audit(me["id"], "AXoR", "task.reassign", f"ctl:t{r['id']}", f"{r['title']}: unclaimed on the board → {a['name']}")
        n += 1
    return n


def escalate(ch, me, rows_tasks, now=None):
    """Dead-letter tasks go to their owner: an audit line and a push, once a day per task. Returns how many went out."""
    now, n = now or time.time(), 0
    for t, r in rows_tasks:
        why = dead(t, r)
        if not why: continue
        target = f"ctl:t{r['id']}"
        if ch.db.q("SELECT 1 FROM og_audit WHERE user_id=? AND action='control.task.escalate' AND target=? AND ts>?", (me["id"], target, now - 86400), one=True): continue
        ch._audit(me["id"], "AXoR", "task.escalate", target, _clip(f"{r['title']}: {why}", 400))
        try:
            from . import agent_core
            if agent_core._notifier: agent_core._notify(me["id"], "A task needs you", _clip(f"{r['title']}: {why}", 240), False)
        except Exception as e:  # noqa: BLE001 - the audit line is the record
            log.info("escalate push: %s", e)
        n += 1
    return n


# ---------- reading: reconcile, the monitor, one task's trace ----------
def reconcile(ch, me, tasks=None):
    """Missions and tasks from the same records: open predefined missions (active Competition teams), open custom missions
    (Mission Control), open tasks by the mission they serve, and the ones whose mission is closed or gone (orphans)."""
    from . import control_missions as cm
    uid = me["id"]
    comps = ch._comps(uid)
    pre = {f"comp:{k}" for k, w in comps.items() if (w.get("status") or "active") != "closed"}
    mx = {}
    if ch._has("mx_missions"):
        mx = {f"mx:{m['id']}": m["status"] for m in ch.db.q("SELECT id, status FROM mx_missions WHERE user_id=?", (uid,))}
    custom_open = sum(1 for s in mx.values() if s in cm.MX_ACTIVE)
    if tasks is None:
        tasks = [{"id": r["id"], "title": r["title"], "mission": r["mission"], "status": r["status"]}
                 for r in ch.db.q(f"SELECT id, title, mission, status FROM ctl_tasks WHERE user_id=? AND status IN ({','.join('?' * len(cm.OPEN))})", (uid, *cm.OPEN))]
    open_ = [t for t in tasks if t["status"] in cm.OPEN and t["status"] != "proposed"]
    by, orphans = {"predefined": 0, "custom": 0, "standalone": 0}, []
    for t in open_:
        m = t.get("mission") or ""
        if not m: by["standalone"] += 1; continue
        by["predefined" if m.startswith("comp:") else "custom"] += 1
        if m.startswith("comp:") and m not in pre:
            orphans.append({"id": t["id"], "title": t["title"], "mission": m, "why": "its Competition team is closed or no longer yours"})
        elif m.startswith("mx:") and m not in mx:
            orphans.append({"id": t["id"], "title": t["title"], "mission": m, "why": "its Mission Control mission was deleted"})
        elif m.startswith("mx:") and mx[m] not in cm.MX_ACTIVE:
            orphans.append({"id": t["id"], "title": t["title"], "mission": m, "why": f"its mission is {mx[m]}"})
    return {"missions_open": {"predefined": len(pre), "custom": custom_open, "total": len(pre) + custom_open},
            "tasks_open": len(open_), "tasks_by_mission": by, "orphans": orphans,
            "note": ("The Mission engine's “open missions” are Mission Control's custom missions; a competition's tasks belong to its predefined "
                     "mission (the Competition team), counted here.")}


def _runs(ch, ids):
    """{task id: latest agent run} from the ledger."""
    if not ids or not ch._has("ac_runs"): return {}
    refs = [f"ctl:t{i}" for i in ids]
    rows = ch.db.q(f"SELECT ref, status, started, finished, error, model FROM ac_runs WHERE ref IN ({','.join('?' * len(refs))}) ORDER BY id", refs)
    return {int(x["ref"][5:]): x for x in rows}


def execution(ch, me):
    """The Execution Monitor: running / queued / overdue / needs-you counts, the stage pipeline, every open (and recently
    failed) task with its stage, destination, tries, last error and why, the dispatcher's state, and the reconciliation."""
    from . import control_dispatch as cd, control_missions as cm
    d = cm.missions(ch, me)
    now, uid = time.time(), me["id"]
    pick_ = [t for t in d["tasks"] if (t["status"] in cm.OPEN and t["status"] != "proposed") or (t["status"] == "failed" and (t.get("updated") or 0) > now - 7 * 86400)]
    ids = [t["id"] for t in pick_]
    rows = {r["id"]: r for r in ch.db.q(f"SELECT * FROM ctl_tasks WHERE id IN ({','.join('?' * len(ids))})", ids)} if ids else {}
    runs = _runs(ch, ids)
    names = ch._view(me)["names"]
    units = {u["id"]: u["name"] for u in ch._view(me)["units"]}
    seen, out, stages = {}, [], {s: 0 for s in STAGES + OFF_PATH}
    for t in pick_:
        r = rows.get(t["id"])
        if not r: continue
        sg, note = stage(t, r, runs.get(t["id"]))
        stages[sg] = stages.get(sg, 0) + 1
        dl = dead(t, r)
        why = t.get("why") or {}
        overdue = why.get("state") not in ("moving", "review", None) and (t.get("updated") or now) < now - cd.STALE
        dup = (t.get("mission") or "", (t["title"] or "").strip().lower())
        ref = r.get("ref") or ""
        dest = (f"Team board #{ref.split(':')[1]}" if ref.startswith("mw_task:") else f"Mission #{ref.split(':')[1]}" if ref.startswith("mx:")
                else "Team board (not sent yet)" if r["route"] == "board" else "Mission Control (not started)" if r["route"] == "mission" else "Agent run")
        run = runs.get(t["id"])
        out.append({"id": t["id"], "title": t["title"], "mission": t.get("mission"), "mission_title": t.get("mission_title"), "kind": t.get("kind"),
                    "origin": t.get("origin"), "route": r["route"], "status": t["status"], "stage": sg, "stage_label": LABEL[sg], "stage_note": note,
                    "team": units.get(r["unit_id"]), "agent": names.get(r["agent_key"]) if r["agent_key"] else None,
                    "board_agent": t.get("board_agent"), "destination": dest, "attempts": r.get("attempts") or 0, "next_try": r.get("next_try"),
                    "last_error": r["summary"] if t["status"] in ("failed", "needs_input") or (r.get("attempts") or 0) else None,
                    "updated": t.get("updated"), "why": why, "dead": dl, "overdue": overdue, "duplicate_of": seen.get(dup),
                    "run": {k: run[k] for k in ("status", "started", "finished", "model")} if run else None,
                    "verified": (_j(r.get("verify"), {}) or {}).get("ok")})
        seen.setdefault(dup, t["id"])
    rank = lambda x: (0 if x["dead"] else 1 if x["overdue"] else 2 if x["stage"] in ("RUNNING", "CLAIMED", "VERIFYING", "SUBMITTED") else 3, -(x["updated"] or 0))
    out.sort(key=rank)
    open_ = [x for x in out if x["status"] in cm.OPEN]
    counts = {"running": sum(1 for x in open_ if x["stage"] == "RUNNING"),
              "under_way": sum(1 for x in open_ if x["stage"] in ("CLAIMED", "RUNNING", "SUBMITTED", "VERIFYING")),
              "open": len(open_), "overdue": sum(1 for x in open_ if x["overdue"] and cd.owner(x["why"].get("state")) != "you"),
              "needs_you": sum(1 for x in out if x["dead"] or (x["overdue"] and cd.owner(x["why"].get("state")) == "you")),
              "dead": sum(1 for x in out if x["dead"])}
    wk = now - 7 * 86400
    aud = {x["action"]: x["n"] for x in ch.db.q("""SELECT action, COUNT(*) n FROM og_audit WHERE user_id=? AND ts>? AND action IN
            ('control.task.dispatch','control.task.retry','control.task.reassign','control.task.escalate') GROUP BY action""", (uid, wk))} if ch._has("og_audit") else {}
    return {"at": now, "mode": d["mode"], "counts": counts, "stages": [{"stage": s, "label": LABEL[s], "n": stages.get(s, 0), "off_path": s in OFF_PATH} for s in STAGES + OFF_PATH],
            "tasks": out[:60], "dispatch": d["dispatch"], "reasons": d["dispatch"].get("reasons") or [],
            "week": {"dispatched": aud.get("control.task.dispatch", 0), "retried": aud.get("control.task.retry", 0),
                     "reassigned": aud.get("control.task.reassign", 0), "escalated": aud.get("control.task.escalate", 0)},
            "timeouts": {"run_min": RUN_TIMEOUT // 60, "claim_h": round(CLAIM_TIMEOUT / 3600, 1), "verify_model": VERIFY_MODEL},
            "reconcile": reconcile(ch, me, [{"id": x["id"], "title": x["title"], "mission": x["mission"], "status": x["status"]} for x in out])}


def trace(ch, me, tid):
    """One task's diagnosis: stage, why, contract, checks, every step of its history and its runs, and who could take it."""
    from . import control_dispatch as cd, control_missions as cm
    r = ch.db.q("SELECT * FROM ctl_tasks WHERE id=? AND user_id=?", (tid, me["id"]), one=True)
    if not r: raise HTTPException(404, "There's no such task.")
    t = cm._task(ch, r, ch._view(me))
    mode, now = ch.mode(me["id"]), time.time()
    if t["status"] in cm.OPEN or t["status"] == "failed":
        t["why"] = dict(zip(("state", "text"), cd.why(t, r, mode, now, cm.RUNS_PER_USER() - ch._busy(me["id"]))))
        t["why"]["owner"] = cd.owner(t["why"]["state"])
    runs = []
    if ch._has("ac_runs"):
        runs = ch.db.q("SELECT id, status, model, tokens, error, started, finished FROM ac_runs WHERE ref=? ORDER BY id DESC LIMIT 10", (f"ctl:t{tid}",))
    board = None
    if (r["ref"] or "").startswith("mw_task:") and ch._has("mw_tasks"):
        bid = int(r["ref"].split(":")[1])
        board = ch.db.q("SELECT * FROM mw_tasks WHERE id=?", (bid,), one=True)
        if board:
            board = {k: board.get(k) for k in ("id", "status", "agent_id", "hold", "summary", "result", "updated", "done_at")}
            if board.get("agent_id"):
                a = ch.db.q("SELECT name FROM mw_agents WHERE id=?", (board["agent_id"],), one=True)
                board["agent"] = a["name"] if a else None
            if ch._has("mw_runs"):
                try:
                    runs = runs + [{"id": x["id"], "status": x["status"], "model": x.get("model"), "tokens": x.get("tokens"), "error": x.get("error"),
                                    "started": x.get("started"), "finished": x.get("finished"), "board": True}
                                   for x in ch.db.q("SELECT * FROM mw_runs WHERE task_id=? ORDER BY id DESC LIMIT 10", (bid,))]
                except Exception: pass  # noqa: BLE001 - an older board without runs
    run = runs[0] if runs and not runs[0].get("board") else None
    sg, note = stage(t, r, run)
    return {"task": {**t, "result": r["result"] if r["route"] == "agent" else (board or {}).get("result"), "attempts": r.get("attempts") or 0,
                     "next_try": r.get("next_try")},
            "stage": sg, "stage_label": LABEL[sg], "stage_note": note, "stages": STAGES, "dead": dead(t, r),
            "contract": contract(ch, me, r), "verify": _j(r.get("verify"), None), "board": board, "runs": runs,
            "candidates": candidates(ch, me, r) if r["route"] == "agent" else [], "board_agents": _board_agents(ch, r) if r["route"] == "board" else []}


def _board_agents(ch, r):
    from . import control_dispatch as cd
    L = cd.linked(ch.db, r.get("ref")) or {}
    if not L.get("board_id"): return []
    b = ch.db.q("SELECT comp_id FROM mw_tasks WHERE id=?", (L["board_id"],), one=True)
    if not b: return []
    return [{"key": f"teams:{a['id']}", "name": a["name"], "lead": bool(a["lead"])}
            for a in ch.db.q("SELECT id, name, lead FROM mw_agents WHERE comp_id=? AND active=1 ORDER BY lead, name", (b["comp_id"],))]


# ---------- the monitor's controls ----------
def _fresh(r):
    """The note a retried or reassigned task keeps: an invalid-contract verdict goes (it's checked again on the next pass)."""
    s = r.get("summary")
    return None if (s or "").startswith(INVALID) or (s or "").startswith("Couldn't dispatch") else s


def retry(ch, me, tid):
    """Run it again now, from a clean count of tries: an agent task on its agent (or one picked), a board task back on its board."""
    from . import control_dispatch as cd, control_missions as cm, mining_work
    r = ch.db.q("SELECT * FROM ctl_tasks WHERE id=? AND user_id=?", (tid, me["id"]), one=True)
    if not r: raise HTTPException(404, "There's no such task.")
    if r["status"] == "running": raise HTTPException(409, "It's running already.")
    if r["route"] == "mission": raise HTTPException(409, "This task runs as a Mission Control mission: retry it there.")
    now, by = time.time(), me["username"]
    if r["route"] == "agent":
        if r["status"] in ("review", "done"): raise HTTPException(409, "It delivered: send it back with a note instead.")
        key = r["agent_key"]
        if not key: key, _ = pick(ch, me, r)
        if not key: raise HTTPException(409, "Nobody on its team can take it: add an agent to the team, or reassign it.")
        fb = (_j(r.get("verify"), {}) or {}).get("why") if (r["summary"] or "").startswith(FAILED_CHECK) else ""
        ch.db.q("UPDATE ctl_tasks SET status='todo', agent_key=?, attempts=0, next_try=NULL, summary=?, history=?, updated=? WHERE id=?",
                (key, _fresh(r), _hist(r, "retry, from a clean count of tries", by), now, tid))
        ch._start_task(me, tid, fb or "")
    else:
        L = cd.linked(ch.db, r["ref"]) or {}
        if r["ref"] and not L.get("gone") and L.get("board_id"):
            if L.get("board_status") in ("working", "queued", "checking"): raise HTTPException(409, "It's being worked on the team's board.")
            ch.w.update_task(me, L["board_id"], mining_work.TaskPatch(status="todo"))  # clears the board's hold and its failure count
            ch.db.q("UPDATE ctl_tasks SET status='todo', attempts=0, next_try=NULL, done_at=NULL, summary=?, history=?, updated=? WHERE id=?",
                    (_fresh(r), _hist(r, "retry: open again on the team's board", by), now, tid))
        else:
            bid = cm._to_board(ch, me, {**r, "detail": board_detail(r)})
            if not bid: raise HTTPException(409, "The team's board didn't take it.")
            ch.db.q("UPDATE ctl_tasks SET status='todo', ref=?, attempts=0, next_try=NULL, done_at=NULL, summary=NULL, history=?, updated=? WHERE id=?",
                    (f"mw_task:{bid}", _hist(r, "retry: sent to the team's board", by), now, tid))
    ch._audit(me["id"], by, "task.retry", f"ctl:t{tid}", r["title"])
    return trace(ch, me, tid)


class ReassignIn(BaseModel):
    agent: str = Field("", max_length=80)   # "" lets AXoR pick another agent


def reassign(ch, me, tid, b: ReassignIn):
    """Give it to another agent: an agent task starts on them; a board task is assigned on the board (a team agent)."""
    from . import control_dispatch as cd, mining_work
    r = ch.db.q("SELECT * FROM ctl_tasks WHERE id=? AND user_id=?", (tid, me["id"]), one=True)
    if not r: raise HTTPException(404, "There's no such task.")
    if r["status"] == "running": raise HTTPException(409, "It's running: cancel it first, or wait for it.")
    if r["route"] == "mission": raise HTTPException(409, "This task runs as a Mission Control mission: its engine staffs it.")
    names, now, by = ch._view(me)["names"], time.time(), me["username"]
    want = (b.agent or "").strip()
    if r["route"] == "board":
        L = cd.linked(ch.db, r["ref"]) or {}
        if not L.get("board_id") or L.get("gone"): raise HTTPException(409, "It isn't on a team board yet: retry it to send it there.")
        opts = {a["key"]: a for a in _board_agents(ch, r)}
        if not want:
            cur = f"teams:{L['board_agent']}" if L.get("board_agent") is not None else None
            want = next((k for k, a in opts.items() if k != cur), "")
        if want not in opts: raise HTTPException(400, "Pick an agent of the task's team board.")
        ch.w.update_task(me, L["board_id"], mining_work.TaskPatch(agent=int(want.split(":")[1])))
        ch.db.q("UPDATE ctl_tasks SET history=?, updated=? WHERE id=?", (_hist(r, f"reassigned on the board to {opts[want]['name']}", by), now, tid))
        ch._audit(me["id"], by, "task.reassign", f"ctl:t{tid}", f"{r['title']} → {opts[want]['name']}")
        return trace(ch, me, tid)
    if want:
        c = {a["key"]: a for a in candidates(ch, me, r)}
        if want not in names: raise HTTPException(404, "There's no such agent in your organization.")
        if want in c and not c[want]["eligible"]: raise HTTPException(409, f"{c[want]['name']} can't take it: {c[want]['why_not']}.")
    else:
        want, note = pick(ch, me, r, avoid=(r["agent_key"],) if r["agent_key"] else ())
        if not want: raise HTTPException(409, note)
    ch.db.q("UPDATE ctl_tasks SET status='todo', agent_key=?, attempts=0, next_try=NULL, summary=?, history=?, updated=? WHERE id=?",
            (want, _fresh(r), _hist(r, f"reassigned to {names.get(want, want)}", by), now, tid))
    ch._audit(me["id"], by, "task.reassign", f"ctl:t{tid}", f"{r['title']} → {names.get(want, want)}")
    if r["status"] not in ("review", "done"): ch._start_task(me, tid)
    return trace(ch, me, tid)


class ContractIn(BaseModel):
    accept: str = Field("", max_length=2000)    # one criterion per line ("" = the default for its kind)
    outputs: str = Field("", max_length=1000)   # one required output per line, named in the result
    needs: list[str] | None = Field(None, max_length=20)  # declared capabilities ("docker", "ram:16"); None leaves them as they are


def set_contract(ch, me, tid, b: ContractIn):
    r = ch.db.q("SELECT * FROM ctl_tasks WHERE id=? AND user_id=?", (tid, me["id"]), one=True)
    if not r: raise HTTPException(404, "There's no such task.")
    acc, outs = "\n".join(_lines(b.accept)[:12]), "\n".join(_lines(b.outputs)[:12])
    try: needs = parse_needs(b.needs) if b.needs is not None else None
    except ValueError as e: raise HTTPException(422, str(e))
    ch.db.q("UPDATE ctl_tasks SET accept=?, outputs=?, history=?, updated=? WHERE id=?",
            (acc or None, outs or None, _hist(r, "acceptance criteria changed", me["username"]), time.time(), tid))
    if needs is not None: declare(ch.db, "ctl", tid, needs, me["username"])  # [] = declared none, kept as "[]" (it was NULL: undeclared)
    ch._audit(me["id"], me["username"], "task.contract", f"ctl:t{tid}", r["title"])
    return trace(ch, me, tid)


class ReqDeclareIn(BaseModel):
    needs: list[str] | None = Field(..., max_length=20)  # [] = declared none (no external dependency); null = undeclared


class ReqDecideIn(BaseModel):
    cap: str = Field(..., max_length=40)
    value: str | None = Field(None, max_length=80)
    decision: str = Field(..., pattern="^(accepted|rejected)$")
    note: str = Field("", max_length=300)


class ReqConfirmIn(BaseModel):
    note: str = Field("", max_length=300)


def _req_task(ch, me, kind, tid):
    """The task, when it's this person's: a Control Hub task they own, or a board task of a team they own."""
    r = _task_row(ch.db, kind, tid)
    if kind == "ctl" and r.get("user_id") != me["id"]: raise HTTPException(404, "There's no such task.")
    if kind == "mw" and r.get("comp_id") not in ch._comps(me["id"]): raise HTTPException(404, "There's no such task.")
    return r


def req_view(ch, me, kind, tid):
    return {"kind": kind, "id": int(tid), **requirements(ch.db, kind, _req_task(ch, me, kind, tid))}


def req_declare(ch, me, kind, tid, b: ReqDeclareIn):
    r = _req_task(ch, me, kind, tid)
    try: items = declare(ch.db, kind, tid, b.needs, me["username"])
    except ValueError as e: raise HTTPException(422, str(e))
    ch._audit(me["id"], me["username"], "task.requirements.declare", f"{kind}:{tid}", f"{r['title'][:80]}: {json.dumps(items)}")
    return req_view(ch, me, kind, tid)


def req_decide(ch, me, kind, tid, b: ReqDecideIn):
    r = _req_task(ch, me, kind, tid)
    decide(ch.db, kind, tid, b.cap, b.value, b.decision, me["username"], b.note)
    ch._audit(me["id"], me["username"], f"task.requirements.{b.decision}", f"{kind}:{tid}", f"{r['title'][:80]}: {_nk(b.cap, b.value)}")
    return req_view(ch, me, kind, tid)


def req_confirm(ch, me, kind, tid, b: ReqConfirmIn):
    r = _req_task(ch, me, kind, tid)
    out = confirm(ch.db, kind, tid, me["username"], b.note)
    ch._audit(me["id"], me["username"], "task.requirements.confirm", f"{kind}:{tid}", f"{r['title'][:80]}: {json.dumps(out['declared']['needs'])}")
    return req_view(ch, me, kind, tid)


def mount(r, ch, user):
    """Adds the Execution Monitor's routes to the Control Hub's router (control_hub.build)."""
    ensure_schema(ch.db)

    @r.get("/requirements/{kind}/{tid}")
    def req_view_(kind: str, tid: int, req: Request): return req_view(ch, user(req), kind, tid)

    @r.put("/requirements/{kind}/{tid}")
    def req_declare_(kind: str, tid: int, b: ReqDeclareIn, req: Request): return req_declare(ch, user(req), kind, tid, b)

    @r.post("/requirements/{kind}/{tid}/decide")
    def req_decide_(kind: str, tid: int, b: ReqDecideIn, req: Request): return req_decide(ch, user(req), kind, tid, b)

    @r.post("/requirements/{kind}/{tid}/confirm")
    def req_confirm_(kind: str, tid: int, b: ReqConfirmIn, req: Request): return req_confirm(ch, user(req), kind, tid, b)

    @r.get("/execution")
    def execution_(req: Request): return execution(ch, user(req))

    @r.get("/tasks/{tid}/trace")
    def trace_(tid: int, req: Request): return trace(ch, user(req), tid)

    @r.post("/tasks/{tid}/retry")
    def retry_(tid: int, req: Request): return retry(ch, user(req), tid)

    @r.post("/tasks/{tid}/reassign")
    def reassign_(tid: int, b: ReassignIn, req: Request): return reassign(ch, user(req), tid, b)

    @r.put("/tasks/{tid}/contract")
    def contract_(tid: int, b: ContractIn, req: Request): return set_contract(ch, user(req), tid, b)
