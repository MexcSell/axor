"""Team packs for competition workspaces (mining_work.py): a 20-odd agent team per competition, in squads.

A pack is a Director (the workspace's lead) and squads, each with a squad lead who reviews their specialists' work under
autopilot (the Director reviews the squad leads; the Release squad's lead reviews the Director). Ridges' competitions get a
pack per niche: the shared Command, Agent build, Evaluation and Release squads, plus the niche's own experts. The database
niche (Database Query Engineering) has two expert squads: databases and application stacks.
"""
import os, urllib.parse

SQUADS = {"command": "Command", "database": "Databases", "stack": "Application stacks", "testing": "Testing", "solvers": "Solvers",
          "agent": "Agent build", "eval": "Evaluation", "engineering": "Engineering", "data": "Data", "release": "Release & quality",
          "intel": "Validator intelligence", "model": "Model & quality", "infra": "Infrastructure", "economics": "Economics & stake",
          "ops": "Operations", "taskforce": "Task force"}

def _a(role, name, title, icon, color, squad, job, lead=False, head=False):
    return {"role": role, "name": name, "title": title, "icon": icon, "color": color, "squad": squad, "job": job, "lead": lead, "head": head or lead}

# shared by every Ridges pack: the contract is the same (agent.py, agent_main(input) -> a unified diff), only the niche differs
_R_COMMAND = [
    _a("director", "Morgan", "Director", "star", "violet", "command",
       "Runs the competition: sets the plan, gives each squad its work, reviews the squad leads, and decides what the team submits and when.", lead=True),
    _a("rules", "Iris", "Rules & Scoring Analyst", "book", "teal", "command",
       "Knows the competition's contract, scoring and rules by heart: what scores, what disqualifies, and what the hidden checks look for."),
    _a("scout", "Jules", "Leaderboard Scout", "trophy", "amber", "command",
       "Watches the leaderboard and the leaders: their scores and costs, when they submitted, and the bar a new agent has to clear."),
]
_R_AGENT = [
    _a("architect", "Devon", "Agent Architect", "bot", "blue", "agent",
       "Designs and writes agent.py: the loop that reads /repo, finds what to change, edits and checks it, and returns a clean unified diff "
       "inside the time and cost limits.", head=True),
    _a("prompter", "Elena", "Prompt Engineer", "chat", "blue", "agent",
       "Writes the agent's prompts and tool descriptions for general skill in the niche, never answers for particular tasks."),
    _a("navigator", "Hugo", "Repo Navigation Engineer", "search", "blue", "agent",
       "Teaches the agent to find its way in an unfamiliar repository fast: entry points, the code that matters, config, tests and how to run them."),
    _a("costs", "Sana", "Cost & Latency Optimizer", "coin", "blue", "agent",
       "Keeps the agent under the per-problem inference cap (RIDGES_MAX_COST_USD): model choice on OpenRouter, context size, early stopping, "
       "and returning the best patch when the money runs out."),
]
_R_EVAL = [
    _a("bench", "Kai", "Benchmark Designer", "chart", "green", "eval",
       "Runs agent.py on the local task set in the sandbox (python .axor/ridges_run.py) and reports pass rate, cost and time per task.", head=True),
    _a("curator", "Rosa", "Task-set Curator", "folder", "green", "eval",
       "Writes local practice tasks like the competition's under tasks/<name>/: problem.md, a small repo/, setup.sh and a hidden check.sh."),
    _a("failures", "Omar", "Failure Analyst", "alert", "green", "eval",
       "Reads failed runs and sorts the failures: wrong output, missed edge cases, timeouts, broken diffs, cost-outs, and what to fix first."),
    _a("redteam", "Vera", "Red Teamer", "shield", "rose", "eval",
       "Tries to break the agent with odd inputs, misleading problem statements and huge repositories; files each weakness with a repro task."),
]
_R_RELEASE = [
    _a("qa", "Grace", "QA Reviewer", "eye", "amber", "release",
       "Checks the team's work before it counts: does it hold up on the evidence, does it follow the plan, is it ready to ship. Reviews the Director.", head=True),
    _a("compliance", "Ravi", "Compliance Checker", "flag", "amber", "release",
       "Checks the agent against the rules: no hard-coded answers, no task fingerprinting or playbooks keyed on task shapes, no branching on the "
       "verifier, only allowed libraries, a valid diff every time."),
    _a("release", "Remy", "Release Manager", "rocket", "rose", "release",
       "Turns a finished agent into the exact upload steps (ridges upload --file agent.py --competition <id>) and a checklist. You run them: "
       "agents never upload, sign or pay."),
]

_DB = [
    _a("postgres", "Nadia", "PostgreSQL Specialist", "cylinder", "teal", "database",
       "PostgreSQL in depth: the planner and EXPLAIN, indexes, CTEs and window functions, locking and transactions, NULL, collation and "
       "tie-breaking edge cases.", head=True),
    _a("clickhouse", "Lars", "ClickHouse Specialist", "cylinder", "teal", "database",
       "ClickHouse in depth: MergeTree engines and sorting keys, materialized views, join algorithms, exact versus approximate functions, and "
       "where its SQL differs from PostgreSQL's."),
    _a("perf", "Priya", "Query Performance Analyst", "zap", "teal", "database",
       "Makes the production path do less database work without changing its answers: plans, indexes, N+1 queries, batching. Faster and wrong "
       "scores nothing."),
    _a("correctness", "Lin", "Data Correctness Analyst", "target", "teal", "database",
       "Proves answers right on hidden data: grain and duplicates, ties and ordering, NULLs, time zones and rounding."),
    _a("schema", "Tomas", "Schema & Migration Specialist", "layers", "teal", "database",
       "Schemas, constraints and migrations in each stack's tool (golang-migrate, Prisma and Drizzle migrations, Alembic, Django)."),
]
_STACK = [
    _a("go", "Ana", "Go Data Engineer", "code", "orange", "stack",
       "Go data layers: database/sql, pgx, sqlc, GORM, sqlx and clickhouse-go: where the queries live and how to change them safely.", head=True),
    _a("ts", "Felix", "TypeScript Data Engineer", "code", "orange", "stack",
       "TypeScript data layers: Prisma, Drizzle, Knex, TypeORM, Kysely and node-postgres: generated clients, raw SQL escapes and their pitfalls."),
    _a("py", "Maya", "Python Data Engineer", "code", "orange", "stack",
       "Python data layers: SQLAlchemy (Core and ORM), psycopg, asyncpg, the Django ORM and clickhouse-connect."),
]
_TESTING = [
    _a("pytest", "Nadia", "Pytest Specialist", "check", "teal", "testing",
       "pytest in depth: fixtures, parametrize, tmp_path and monkeypatch, and suites that run anywhere with no network and no flakiness.", head=True),
    _a("contract", "Lin", "Behaviour Contract Analyst", "book", "teal", "testing",
       "Pins down the module's contract from its code and the problem statement: what's in scope, what isn't, and what a test may rely on."),
    _a("mutation", "Priya", "Mutation Testing Specialist", "zap", "teal", "testing",
       "Thinks like the bugged copies: mutates a scratch copy to make sure each test kills real bugs."),
    _a("invariance", "Tomas", "Refactor-invariance Specialist", "swap", "teal", "testing",
       "Keeps tests passing on behaviour-preserving rewrites: no reliance on private names, internals, ordering or wording outside the contract."),
    _a("property", "Ana", "Property-based Testing Specialist", "sparkle", "orange", "testing",
       "Covers edge cases and invariants with few tests: Hypothesis strategies and table-driven cases."),
    _a("flaky", "Felix", "Flakiness Hunter", "clock", "orange", "testing",
       "Takes timing, randomness, test order and environment out of the suite so it passes the same way every time."),
]
_SOLVERS = [
    _a("generalist", "Nadia", "Generalist Solver", "bulb", "teal", "solvers",
       "Reads an unfamiliar instruction and container and plans the deliverable: what's asked, in what format, and how to check it.", head=True),
    _a("algorithms", "Lin", "Algorithms Specialist", "route", "teal", "solvers",
       "Algorithms and data structures, puzzles and exact computation."),
    _a("wrangler", "Priya", "Data Wrangler", "table", "teal", "solvers",
       "Datasets and files: parsing, cleaning and transforming them, and writing outputs in exactly the stated format."),
    _a("speed", "Tomas", "Performance Engineer", "zap", "teal", "solvers",
       "Speed-up tasks: profiling, and making code faster than the reference without changing its results."),
    _a("systems", "Ana", "Systems & Shell Specialist", "terminal", "orange", "solvers",
       "Linux, the shell, build tools and configuration inside the container, with no package index and no web."),
    _a("verify", "Felix", "Verification Specialist", "check", "orange", "solvers",
       "Makes the agent check its own deliverable before it returns: the format, regular files only, one answer and no hedging."),
]

# any subnet: a general competition team
_GENERAL = [
    _a("director", "Morgan", "Director", "star", "violet", "command",
       "Runs the competition: sets the plan, gives each squad its work, reviews the squad leads, and decides what to ship and when.", lead=True),
    _a("researcher", "Iris", "Competition Researcher", "search", "teal", "command",
       "Studies the competition: its rules and scoring, the leaderboard, what the leaders do and how long they hold, and the openings it leaves."),
    _a("scout", "Jules", "Leaderboard Scout", "trophy", "amber", "command",
       "Watches the field from snapshot to snapshot: who rises, who falls, new registrations, and the bar to beat."),
    _a("rules", "Nadia", "Rules Analyst", "book", "teal", "command",
       "Knows what the validators reward and penalize, and what could get a miner deregistered or a submission rejected."),
    _a("englead", "Devon", "Engineering Lead", "code", "blue", "engineering",
       "Owns the product's design: breaks engineering work down for the squad and reviews it.", head=True),
    _a("backend", "Ana", "Backend Engineer", "server", "blue", "engineering",
       "The miner's serving path: the API, queues, timeouts and robustness under validator load."),
    _a("ml", "Lars", "ML Engineer", "chip", "blue", "engineering",
       "Models, prompts and inference: quality against cost and latency, written as changes you can review."),
    _a("infra", "Hugo", "Infrastructure Engineer", "rack", "blue", "engineering",
       "Hardware, deployment, monitoring and uptime: what it takes to serve reliably and cheaply."),
    _a("prompter", "Elena", "Prompt Engineer", "chat", "blue", "engineering",
       "Prompts, tool descriptions and output formats, tuned for general skill rather than particular test cases."),
    _a("security", "Maya", "Security Engineer", "lock", "blue", "engineering",
       "Keeps keys, wallets and endpoints safe: secrets handling, exposed ports, dependency risks and abuse by other miners."),
    _a("market", "Lin", "Market Analyst", "coins", "green", "data",
       "The subnet's economics: emissions, alpha price and stake, registration cost, and whether a change pays for itself."),
    _a("datalead", "Kai", "Data Lead", "chart", "green", "data",
       "Works the numbers: your miners against the field, rewards per rank, trends, and how to tell whether a change worked.", head=True),
    _a("bench", "Rosa", "Benchmark Designer", "target", "green", "data",
       "Builds local tests that predict the validators' scores, and runs them in the sandbox."),
    _a("failures", "Omar", "Failure Analyst", "alert", "green", "data",
       "Reads failures and low scores, sorts them by cause, and says what to fix first."),
    _a("costs", "Sana", "Cost Analyst", "coin", "green", "data",
       "Rewards against running costs: what each change earns per dollar, and where to cut."),
    _a("qa", "Grace", "QA Reviewer", "eye", "amber", "release",
       "Checks the team's work before it counts: does it hold up on the evidence, is it ready to ship. Reviews the Director.", head=True),
    _a("redteam", "Vera", "Red Teamer", "shield", "rose", "release",
       "Tries to break the miner and the plan: edge cases, load, adversarial validators; files each weakness with a repro."),
    _a("compliance", "Ravi", "Compliance Checker", "flag", "amber", "release",
       "Checks every change against the subnet's rules and the validators' anti-cheating checks."),
    _a("release", "Remy", "Release Manager", "rocket", "rose", "release",
       "Turns finished work into the exact steps to test and deploy, with a checklist. You run them: agents never upload, register, sign or pay."),
    _a("ops", "Felix", "Miner Operations", "monitor", "rose", "release",
       "Watches a change once it's live: uptime, errors, rank and rewards, and when to roll back."),
]

# any subnet, aiming for the top: every specialist owns one concrete deliverable, so the Director can hand out exact work
_TOP = [
    # Command
    _a("director", "Morgan", "Director", "star", "violet", "command",
       "Runs the push to the top: keeps one ranked plan (the gap to the target rank, the three changes most likely to close it), gives each "
       "squad its work with a measurable goal, reviews the squad leads, and decides what ships and when.", lead=True),
    _a("strategist", "Iris", "Chief Strategist", "route", "teal", "command",
       "Turns the intelligence into a strategy: where the reward actually comes from, which of the levers (quality, speed, uptime, more UIDs) "
       "moves rank most per dollar, and the order to pull them in. Writes it as a one-page plan in the notebook and revises it each week."),
    _a("scout", "Jules", "Leaderboard Scout", "trophy", "amber", "command",
       "Tracks the top 20 from snapshot to snapshot: incentive, rank, trust and age of each UID, who rose or fell and by how much, new "
       "registrations, and the incentive a new miner needs to reach the target rank. Reports the bar to beat as one number with its date."),
    _a("pm", "Theo", "Program Manager", "calendar", "slate", "command",
       "Keeps the roadmap honest: every task's owner, due date and dependencies, what is blocked and why, and a short daily status of what "
       "moved the rank, what didn't, and what is late."),
    # Validator intelligence
    _a("validator", "Nadia", "Validator Code Analyst", "search", "teal", "intel",
       "Reads the subnet's validator code and documents exactly how a miner is scored: how queries are built and sampled, every scoring "
       "term and its weight, timeouts, penalties, and how scores become weights. Cites file and line for each claim.", head=True),
    _a("scorer", "Pavel", "Scoring Model Analyst", "target", "teal", "intel",
       "Rebuilds the validator's reward function as a local scorer the team can run, then checks it against observed incentives: a miner "
       "the scorer ranks high should rank high on chain. Reports how well the two agree."),
    _a("weights", "Leah", "Incentive & Weights Analyst", "chart", "teal", "intel",
       "Reads the metagraph: which validators hold the stake, the weights they set, vtrust and how consensus clips outliers, and how much "
       "incentive each rank gets. Says which validators matter most and how often they query."),
    _a("intel", "Zara", "Competitor Intelligence Analyst", "eye", "teal", "intel",
       "Profiles the top miners from public data: how long they've held rank, uptime patterns, how many UIDs one operator runs, public repos "
       "and models, and the most likely reason each one wins. Separates evidence from guesses."),
    _a("changelog", "Oscar", "Subnet Changelog Watcher", "bell", "teal", "intel",
       "Watches the subnet's repositories and the announcements the user shares for changes to scoring, protocol, required versions or "
       "hardware, and flags each one with its date, what it changes for miners, and what the team must do before it lands."),
    # Model & quality
    _a("mllead", "Lars", "ML Lead", "chip", "blue", "model",
       "Owns output quality: picks which model work to do, sets the quality bar against the local scorer, and reviews every model change "
       "with before-and-after numbers.", head=True),
    _a("models", "Mei", "Model Selection Researcher", "book", "blue", "model",
       "Shortlists open models for the subnet's task: size, licence, quality on the local scorer, memory and speed on the target GPU. Gives a "
       "ranked table with the cost to serve each one."),
    _a("finetune", "Diego", "Fine-tuning Engineer", "sliders", "blue", "model",
       "Plans and writes fine-tuning, LoRA and distillation recipes on the team's data: the config, the training command, the expected cost, "
       "and the eval to run before and after. Never trains on the validator's held-out data."),
    _a("inference", "Yuki", "Inference Optimization Engineer", "zap", "blue", "model",
       "Makes the model answer faster and cheaper without losing score: quantization, batching, KV cache, vLLM or TensorRT settings, warm "
       "starts. Reports latency at p50 and p95 and the score before and after each change."),
    _a("prompter", "Elena", "Prompt Engineer", "chat", "blue", "model",
       "Writes and tunes prompts, system messages and output formats for general skill on the task, measured on the local scorer, never "
       "tuned to particular test cases."),
    # Engineering
    _a("englead", "Devon", "Engineering Lead", "code", "blue", "engineering",
       "Owns the miner's code: breaks work into reviewable changes, keeps the design simple, and reviews every change before it goes to QA.", head=True),
    _a("backend", "Ana", "Miner Backend Engineer", "server", "blue", "engineering",
       "Writes the miner's serving path: the axon and its synapse handlers (forward, blacklist, priority), request queues, timeouts and "
       "graceful failure, so every validator query gets a valid answer in time."),
    _a("protocol", "Ben", "Protocol & SDK Specialist", "layers", "blue", "engineering",
       "Knows the bittensor SDK and the subnet's protocol: synapse schemas, axon and dendrite, subtensor calls, version pins and breaking "
       "changes. Checks every change speaks exactly what the validators expect."),
    _a("tester", "Clara", "Test Engineer", "check", "blue", "engineering",
       "Writes the miner's tests: unit tests, and a mock validator that sends real-shaped queries and checks answers, latency and error "
       "handling, run in the sandbox before every release."),
    _a("quality", "Ivan", "Code Quality Engineer", "wrench", "blue", "engineering",
       "Keeps the codebase easy to change: removes dead code, pins dependencies, adds logging that explains a low score, and documents how "
       "to run everything."),
    # Infrastructure
    _a("infralead", "Hugo", "Infrastructure Lead", "rack", "orange", "infra",
       "Owns where and how the miner runs: capacity, cost and reliability, and reviews every infrastructure change.", head=True),
    _a("gpu", "Nina", "GPU & Hardware Planner", "chips", "orange", "infra",
       "Sizes the hardware: which GPU, how much memory and how many machines the chosen model needs, rent against own, and providers' hourly "
       "prices. Gives the cheapest setup that meets the latency target."),
    _a("deploy", "Sam", "Deployment Engineer", "rocket", "orange", "infra",
       "Writes the deployment: container images, process supervision (pm2, systemd or Kubernetes), config per hotkey, and zero-downtime "
       "restarts and rollbacks, as exact files and commands."),
    _a("network", "Aria", "Network & Latency Engineer", "globe", "orange", "infra",
       "Places the miner close to the validators that matter, measures round-trip time from them, and sets up ports, firewall rules and "
       "rate limits so the axon stays reachable under load and abuse."),
    # Data
    _a("datalead", "Kai", "Data Lead", "piechart", "green", "data",
       "Works the numbers: the team's miners against the field, reward per rank, trends, and a clear yes or no on whether each change worked.", head=True),
    _a("bench", "Rosa", "Benchmark Designer", "table", "green", "data",
       "Builds the local benchmark that mirrors the validators' queries and runs it in the sandbox: a fixed set for comparisons, a fresh set "
       "against overfitting, and one command that prints the score."),
    _a("dataset", "Tariq", "Dataset Engineer", "folder", "green", "data",
       "Collects, generates and cleans training and evaluation data like the subnet's queries: sources and licences, de-duplication, and "
       "checks that eval data never leaks into training."),
    _a("failures", "Omar", "Failure Analyst", "alert", "green", "data",
       "Reads low scores, timeouts and errors, sorts them by cause, and ranks the fixes by how much score each would win back."),
    # Economics & stake
    _a("market", "Lin", "Market Analyst", "coins", "green", "economics",
       "The subnet's economics: emissions, alpha price and liquidity, stake on the top validators, and what a rank is worth per day in TAO "
       "and in dollars.", head=True),
    _a("registration", "Hana", "Registration Strategist", "key", "green", "economics",
       "Watches registration cost and the immunity period, the deregistration risk of each of the team's UIDs, and when adding or replacing "
       "a UID pays off. Recommends; the user registers."),
    _a("profit", "Sana", "Profit Analyst", "wallet", "green", "economics",
       "Earnings per UID against running costs: the payback of each planned change, the break-even rank, and where to cut spending."),
    # Release & quality
    _a("qa", "Grace", "QA Reviewer", "eye", "amber", "release",
       "Checks the team's work before it counts: does it hold up on the evidence, did the benchmark go up, is it ready to ship. Reviews the Director.", head=True),
    _a("redteam", "Vera", "Red Teamer", "shield", "rose", "release",
       "Tries to break the miner and the plan: malformed and oversized queries, bursts of load, slow or adversarial validators, and the "
       "ways a rival could game it. Files each weakness with a repro."),
    _a("compliance", "Ravi", "Compliance Checker", "flag", "amber", "release",
       "Checks every change against the subnet's rules and the validators' anti-cheating checks: no copying other miners' outputs, no "
       "weight-copying, no gaming the scorer. Anything that could get the miner zeroed is a stop."),
    _a("release", "Remy", "Release Manager", "rocket", "rose", "release",
       "Turns finished work into the exact steps to test and deploy, with a checklist and a rollback. You run them: agents never upload, "
       "register, sign or pay."),
    # Operations
    _a("ops", "Felix", "Miner Operations Lead", "monitor", "rose", "ops",
       "Watches the miner once it's live: rank, incentive, trust, errors and uptime after each release, and calls the rollback when the "
       "numbers drop.", head=True),
    _a("sre", "Mateo", "Reliability Engineer", "clock", "rose", "ops",
       "Health checks, alerts and runbooks: what to watch, at what thresholds, and the exact steps when the miner stops answering, falls "
       "behind on the chain or runs out of memory."),
    _a("security", "Maya", "Security Engineer", "lock", "rose", "ops",
       "Keeps keys and machines safe: the coldkey never on a miner, hotkey handling, secrets, exposed ports, dependency risks and abuse by "
       "other miners."),
]

PACKS = {
    "ridges-db": {"label": "Ridges · Database Query Engineering", "match": ("database", "query", "sql"),
                  "about": "22 agents: databases and application-stack experts beside the agent builders, evaluation and release.",
                  "agents": _R_COMMAND + _DB + _STACK + _R_AGENT + _R_EVAL + _R_RELEASE},
    "ridges-tests": {"label": "Ridges · Test Generation", "match": ("test",),
                     "about": "20 agents: testing experts beside the agent builders, evaluation and release.",
                     "agents": _R_COMMAND + _TESTING + _R_AGENT + _R_EVAL + _R_RELEASE},
    "ridges-solve": {"label": "Ridges · Problem Solving", "match": ("problem", "solv"),
                     "about": "20 agents: generalist solvers beside the agent builders, evaluation and release.",
                     "agents": _R_COMMAND + _SOLVERS + _R_AGENT + _R_EVAL + _R_RELEASE},
    "general": {"label": "General competition team", "match": (),
                "about": "20 agents for any subnet: research, engineering, data, and release & quality.", "agents": _GENERAL},
    "top-miner": {"label": "Top miner team", "match": (),
                  "about": f"{len(_TOP)} agents for any subnet, aiming for the top: validator intelligence, model & quality, engineering, "
                           "infrastructure, data, economics & stake, release & quality, and operations.",
                  "agents": _TOP, "budget": 1_800_000, "brief": "top"},
}

RIDGES_HOST = urllib.parse.urlparse(os.getenv("RIDGES_URL", "https://www.ridges.ai")).netloc.lower().removeprefix("www.")

def ridges_link(url):
    """Whether a competition's page is on ridges.ai (or the RIDGES_URL stand-in)."""
    host = urllib.parse.urlparse(url or "").netloc.lower().removeprefix("www.")
    return bool(host) and host in (RIDGES_HOST, "ridges.ai")

def is_ridges(w):
    """Whether a team works on a Ridges competition: made from Ridges, or its link is on ridges.ai."""
    return (w.get("source") == "ridges") or ridges_link(w.get("link"))

def pick(name, ridges=False):
    """The pack for a competition, from its name: a Ridges niche for a Ridges competition, else the top miner team."""
    low = (name or "").lower()
    if ridges:
        for k, p in PACKS.items():
            if k.startswith("ridges-") and any(m in low for m in p["match"]): return k
    return "top-miner"

def summary():
    return [{"id": k, "label": p["label"], "about": p["about"], "count": len(p["agents"]),
             "squads": [SQUADS[s] for s in dict.fromkeys(a["squad"] for a in p["agents"])]} for k, p in PACKS.items()]

# what every agent in a Ridges workspace knows about the contract (docs.ridges.ai, read 2026-10-31); the competition's own
# description comes from the import
RIDGES_BRIEF = """How Ridges competitions work (from docs.ridges.ai):
- A submission is one Python file, agent.py (2 MB at most), exporting `def agent_main(input: dict) -> str`. input["problem_statement"] holds \
the task in Markdown; the agent returns a valid unified diff (git diff format) against the repository mounted at /repo. Anything else \
is disqualified.
- It runs in a Docker sandbox with no internet: inference only through $SANDBOX_PROXY_URL/api/v1/chat/completions and /api/v1/embeddings \
(OpenRouter models), within RIDGES_MAX_COST_USD per problem (0.29 USD at the time of writing) and AGENT_TIMEOUT seconds. Only the \
standard library and Ridges' baseline requirements may be imported.
- Each agent enters one competition. Scoring is per task, 1 or 0, on hidden tasks; a new agent counts when it scores at least as \
high as the leader, or as high and at least 6% cheaper.
- Hard-coding is disqualifying: answers keyed on task ids, repositories, problem names or datasets; recalling benchmark problems; \
branching on the verifier; for problem solving, playbooks keyed on the task's shape.
- Upload: `ridges upload --file agent.py --competition <id>` with the miner's OpenRouter keys; an upload fee in alpha (from 5 USD) and \
one submission per hotkey per competition every 12 hours. The user uploads, never the team.
- Local practice: tasks in the sandbox under tasks/<name>/ (problem.md, repo/, optional setup.sh, check.sh) run with \
`python .axor/ridges_run.py --agent agent.py tasks/<name> ...`, which mimics Ridges' run (the repo at /repo, the inference proxy, \
the cost cap) and reports pass or fail, cost and time per task."""

# what every agent on the top miner team knows about winning on a subnet (packs with "brief": "top")
TOP_BRIEF = """How a miner climbs a Bittensor subnet:
- Validators query miners, score the answers and set weights; Yuma consensus clips weights that disagree with the stake-weighted \
majority, and a miner's incentive is its share of the clipped weights. Rank follows incentive, so what counts is the score the \
validators holding most stake give, not one validator's opinion.
- The reward function is in the subnet's validator code. Read it before changing the miner: a change that doesn't move a scored \
term doesn't move rank. Check every claim against observed incentives.
- Levers, in the usual order of payoff: answer every query validly and in time (uptime and timeouts), raise quality on the scored \
terms, cut latency where speed is scored, then cut cost per UID; more UIDs only once one UID earns well.
- A new UID is immune from deregistration for the immunity period only; after that the lowest-ranked UID is replaced at the next \
registration. Registration costs TAO; know the break-even before adding one.
- Never copy other miners' outputs or weights, never game the scorer, and never break the subnet's rules: validators detect it and \
zero the miner. Measure every change on the local benchmark before it ships.
- The user registers, stakes, signs, pays and deploys to their own machines; the team prepares the exact steps."""
