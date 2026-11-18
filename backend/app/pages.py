"""AXoR's pages (the sidebar's views), for agents: the Assistant's map of the app, and the page a message was sent from
(the Assist panel, assist.js, sends it with every message so "this page" means the one the user is on)."""

# view id -> (title, what it shows, admins only)
PAGES = {
    "command": ("Command Center (Command → Overview)", "the operational overview: agents, active runs, competitions and approvals waiting; agent "
                "activity over 7 days (tasks or tokens), the tracked miner's subnet and rank, system health (the chain and the services that are "
                "set up), pending approvals (each reviewed on its own page), recent activity, quick actions, the AI Assistant, and tabs for "
                "active missions, running agents, system events and performance (miners, model use, team budgets)", False),
    "approvals": ("Approval Center", "every request waiting for the user's decision across My subnets, the Company, Workforce, "
                  "Agent HQ, the Portfolio, Competition teams, the Workflow and the project team, filtered by system, with the latest decisions; "
                  "each request is decided on its own page; its other tabs show agents' recommendations, executions, the audit trail and "
                  "permissions (agent contracts, team limits, tool grants)", False),
    "intel": ("Bittensor Research (Knowledge)", "the subnet market at a glance: emission leaders and concentration, competition (miners, slots, registration "
              "cost, top-miner share), rewards (top vs median miner), risk flags and the best opportunities, and the user's miners", False),
    "evolution": ("Evolution Lab", "AXoR 5.0's Evolution Engine: signals (weak spots from the run ledger, chat ratings and Studio tests), proposals "
                  "(written by the user or drafted by a model, for agents, skills, teams, departments, workflows, strategies or the organization), "
                  "benchmarks (fixed cases with a rubric), experiments where the current version and the candidate answer the same cases and a judge "
                  "scores them blind, promotion only with measured evidence (and by policy only for low-risk configuration), versions and rollback, "
                  "each agent as a capability package, the other systems' improvement loops, and the audit trail", False),
    "analytics": ("Analytics", "cost per successfully validated deliverable (ledger tokens over deliverables an evaluator, verifier or a mission's "
                  "independent reviewer checked), tokens and validated deliverables per day, the eight-row Generation 5 scorecard (mission completion, "
                  "agent improvement, knowledge transfer, team formation, cost, recovery, evolution, governance), and every system and agent", False),
    "topology": ("Unified control panel (System graph)", "AXoR as one interactive graph with seven synchronized projections: organization "
                 "(departments, teams, agents), missions and their tasks, agent execution (runs, models, tools, sandboxes), infrastructure "
                 "(Kubernetes nodes, namespaces, pods; administrators), network (sandboxes, the egress proxy, hosts reached or refused, model "
                 "and MCP providers), knowledge lineage (sources, items, who used them) and observability (failures and alerts on the component "
                 "they are about); global, operational and deep levels, trace, impact analysis, search, compare and replay of the time window", False),
    "governance": ("Governance","the Evolution Engine's policy (recommend, experiment, auto-promote low-risk configuration; margin, minimum cases, "
                   "daily tokens), the daily token limit over every agent system, AXoR 5.0's autonomy levels mapped onto the organization's L0-L4, "
                   "actions that always need the user, what waits for a decision, rollback points, rules in force and the merged audit trail", False),
    "layers": ("Intelligence layers", "AXoR as six capability layers, each with the parts that do its work and live figures: mission "
               "intelligence (Mission Intelligence, the Intelligence brief, the mission engine), workforce intelligence (agent registry, "
               "Workforce, Organization, model router), execution intelligence (agent runs, Autoloop, sandboxes, long tasks, Control Hub "
               "tasks), knowledge intelligence (Knowledge Hub, retrieval, mission lessons, Workforce memory, team notebooks, experience recall), evaluation "
               "(run scores, Lab evals, upgrade exams, Evolution experiments, retrieval evals) and adaptive intelligence (Evolution Lab, "
               "improvements, recall track record, watches, upgrade promotions, the router's track record); each layer active, ready or missing", False),
    "swarm": ("Agent Swarm (Workforce)", "AXoR G5's collaborative execution engine: a Swarm Controller sizes a temporary team of the user's "
              "Workforce agents (one, a small team, or a swarm of 3-5), picks a pattern (hierarchical, collaborative, parallel, competitive, "
              "adaptive or hybrid) and writes task contracts (objective, deliverables, dependencies, agent, token budget); agents work them in "
              "parallel over their dependencies, message each other on the bus as the pattern allows and file findings on a shared blackboard; "
              "an evaluator checks each contract (competitive ones blind), failed work is reassigned and adaptive swarms replan; the page shows "
              "the swarm map, contracts, message bus, blackboard, activity, the integrated result and each pattern's track record", False),
    "learning": ("Learning", "how agents get better from results, across every agent system: Mission Control's lessons (with the mission each came from and how "
                 "often later missions used it; the user can forget one), Workforce and Workflow improvements (why, the change, the trial's result, "
                 "adopted or not), watches that keep or roll back a promoted version, Agent Upgrade Factory sprints, and Experience recall (what missions, "
                 "Workforce and team tasks recalled from earlier work before acting, how that work went, and a box to try a recall); above them the "
                 "Knowledge → Intelligence → Learning loop in numbers", False),
    "org": ("Orchestration (Organization)", "every agent across the Company, Workforce, Competition teams, the user's agents and Agent HQ: the hierarchy, roles "
            "and workload, the teams and task forces at work, and who works with whom", False),
    "projects": ("Projects", "every project across the Company, Competition teams, Workforce missions, the project team and long "
                 "tasks: status, progress, spend against budget, and how projects depend on each other", False),
    "missions": ("Missions & tasks", "every task from those systems on one board: to do, in progress, needs review, blocked, done", False),
    "evaluation": ("Benchmarks & evaluations (Agent evaluation)", "agent scores and success rates, benchmarks and experiments, model use and routes, long-running tasks, "
                   "and knowledge and skills", False),
    "home": ("My workspace → Home", "the user's notes, files, whiteboards, study progress and shared work, with shortcuts to each (formerly Workspace home)", False),
    "settings": ("Settings", "the user's account security (two-factor, sessions), notifications and appearance; for administrators also "
                 "users, sign-up and the audit log", False),
    "infra": ("Platform overview", "AXoR's developer platform and infrastructure at a glance: services, server load, the cluster, pipelines, "
              "apps and functions, machines, DNS and connectors", True),
    "dashboard": ("Market Research", "the network and fund picture at a glance (TAO price, emission, flows, open UIDs), fund movers, "
                  "the best opportunities right now, the user's workspace subnets, notes and the latest notifications and news", False),
    "notifications": ("Notifications", "the inbox of alerts, Web Push on this browser and the user's other devices, and per-kind settings", False),
    "workspace": ("My workspace", "the user's shortlist of subnets, each with a mining brief (task, budget, low-cost plan, how to "
                  "become a top miner, competition), notes, files and news, plus agents and a project team that work on the open subnet; "
                  "its Overview shows everything waiting for the user and every agent at work across Competition teams, the Workflow, "
                  "My subnets, Workforce and the project team, with team progress, miners' ranks and token spend", False),
    "study": ("Study", "two learning tracks, AI Engineer and English C1+: a roadmap, topics to tick off, practice drills, a code lab and study tutors", False),
    "profile": ("My profile", "the user's AI engineer profile, made into a resume, a full CV and a portfolio website", False),
    "whiteboard": ("Whiteboard", "infinite boards with sticky notes, shapes, frames and templates, edited live with others", False),
    "wallet": ("Wallets", "the user's Bittensor wallets, tracked by public address: balances, assets, staking, and Send, Receive, "
               "Stake, Unstake and Move, each signed in the user's browser wallet", False),
    "slack": ("Slack", "the team's Slack channel: read and post messages and threads, share subnets, notes and notifications", False),
    "drive": ("File manager (Drive)", "AXoR Drive: private and shared files and folders, sharing, share links and the trash", False),
    "source": ("Source control", "the team's GitHub repositories: branches, commits with their CI status, code, pull requests, workflow runs and deployments", False),
    "explore": ("Subnet Explorer", "every subnet in one table with live metrics (emissions, miners, registration cost, price, risk), "
                "with filters, sorting, a CSV export and each subnet's details", False),
    "recommend": ("Recommendations", "subnets ranked for the user's hardware, budget, capital and risk tolerance", False),
    "new": ("New Subnets", "subnets registered in the last four months", False),
    "caution": ("Avoid & Caution", "subnets flagged as risky to mine or hold, with the reasons", False),
    "scam": ("Unverified & high-risk signals", "subnets with rule-based high-risk warning signs (formerly Scam Signals): evidence, not proof of fraud", False),
    "agents": ("Agents", "one page for every agent. Its rail: Directory (every agent across the user's agents, built-in agents, the Company, Workforce, "
               "Competition teams and, for admins, the Workflow and Agent HQ; filters by system, state and Only mine; each agent opens its profile with "
               "overview, instructions, skills, tools, memory, tasks, evaluations, versions and activity, and the user's own agents can be edited, tested, "
               "compared, restored, duplicated, paused, published or deleted there), New agent (create from a description, a template or blank), "
               "Operations (attention, approval queue, token use, daily budget), Live runs (running and failed runs with execution traces), "
               "Shared catalog (agents published for everyone), Connected systems, Ecosystem, Tools & MCP (MCP servers admins add and test, "
               "the tools agents may call from them, and which agents or Competition teams get them), the skill hub, My logins and settings; chats with an agent open here too", False),
    "knowledge": ("Knowledge Hub", "the agent company's governed knowledge: records scoped to the company, a division, a project, a "
                  "competition team or one agent, each with one of six types (declarative, procedural, episodic, strategic, technical, "
                  "evaluative), a review state (waiting, verified, contested, not approved, superseded), confidence, review date, evidence "
                  "and versions; tabs Overview (ask, the lifecycle), Knowledge, Divisions & projects (scope tree, grants), "
                  "Contributions, Skills & procedures, Experiences, Review (automatic checks, AI review, approve "
                  "the exact version), Graph and Analytics (reuse, usefulness); agents read verified records in their scopes with "
                  "search_knowledge, submit candidates with contribute_knowledge and rate what helped with knowledge_feedback", False),
    "myknowledge": ("My Knowledge", "the user's private knowledge space: a directory tree (00-Inbox … 99-Archive), Capture (note, idea, web "
                    "page, text file, Word/PowerPoint/Excel/OpenDocument/PDF/EPUB documents, pictures read by a model, audio and video "
                    "transcribed with key sections, paste, conversation), stored originals, search by meaning (embeddings) and words, "
                    "sharing items read-only with other users (Shared with me, save a copy), sources kept apart from the records derived "
                    "from them, Communications (Slack, Discord and Telegram messages from exports, the connected Slack channel and the "
                    "user's own read-only Discord/Telegram bots), ideas with AI analysis and stages, typed "
                    "connections and their graph, Ask My Knowledge (answers with cited evidence), Organize with AI, imports of earlier "
                    "workspaces and external agents' exports with adopt proposals, and Company sharing (publish for review); private by "
                    "default, shared with the user's agents or published only when the user chooses", False),
    "market": ("Agent Marketplace", "AXoR's agent ecosystem: discover agents (the user's own library, A2A Agent Cards, GitHub repositories, "
               "pasted packages), evaluate them in quarantine on their role's tasks (nine dimensions, judged separately), import them as an AXoR "
               "Agent Package with the original kept as version 1 (its DNA), adapt them as new versions, test, approve one exact version, and "
               "activate it as one of the user's agents; Workforce shows the imported agents at work, Intelligence the leaderboard, comparisons "
               "and continuous re-evaluation with regressions", False),
    "mos": ("Mission Control (Simple mode)", "AXoR 3.0's front door: the user gives only a goal, optionally with documents, pictures and links (GitHub "
            "repositories are recognized and read read-only); AXoR sets the budget from the mission's size (at most $20 without asking) and "
            "estimates the time, and Advanced mode keeps budget, deadline, engine, team and autonomy as optional overrides; each mission runs understand → discover → plan → allocate → execute → verify → deliver → learn on the engine "
            "that fits (AXoR directly, Workforce, Long tasks or a Competition team), with an independent check of every acceptance criterion, a "
            "report, kept lessons, and hash-bound approval requests for anything only the user may do", False),
    "tech": ("Technology Research (Tech Daily)", "a daily edition of new technology (AI, software, Android, devices, IoT and security) from the tech press, "
             "Hacker News and GitHub, written like ads: a cover line, the day's spotlight, each category's stories, earlier editions; a research brief "
             "(the day's or the week's themes, takeaways and what to watch) and Analyze on a story (reads the article: what it is, how it works, "
             "limits, maturity and an adopt/try/watch/skip verdict)", False),
    "help": ("Help", "AXoR's documentation: getting started, a guide to every page, administration, the API with a reference of every "
             "endpoint, and developer docs", False),
    "admin": ("User administration", "accounts, roles, sign-up and sign-in settings, and the audit log", True),
    "docker": ("Docker", "this server's legacy Docker containers and images (AXoR itself runs on Kubernetes)", True),
    "devops": ("DevOps", "AXoR's own CI/CD: pipelines that build, test and deploy Source hub repositories, their runs and the deployed apps", True),
    "connectors": ("Keys", "Workforce → Keys (formerly System → Models & connectors): the model providers and outside services AXoR holds a key for, and OpenRouter API keys with their spend and limits", True),
    "system": ("System", "this server's CPU, memory, swap, disk and load, with charts of the last hour", True),
    "cluster": ("Cluster", "the Kubernetes cluster AXoR runs on: node capacity, namespaces with their deployments and pods, "
                "recent warnings, the platform's domain and HTTPS, and Updates (the updater that deploys each new commit on main, "
                "its history and log; check now, update now, pause)", True),
    "apps": ("Apps", "apps on AXoR's Kubernetes platform (PaaS): status, pods, events, logs and revisions", True),
    "functions": ("Functions", "serverless functions on AXoR's platform (FaaS): code, test calls, logs, revisions and call statistics", True),
    "machines": ("Machines", "Linux and Windows virtual machines on the server's KVM, with their console in the browser", True),
    "dns": ("DNS", "the zones AXoR's own name server answers for: records, zone settings, lookups and a delegation check", True),
    "hq": ("Agent HQ", "the agents that run AXoR's platform: field agents check services and infrastructure every 10 minutes and fix "
           "what's safe, team leads review fixes, the Team Boss reports every hour, the Agents Manager runs the roster of every agent", True),
    "sidelayout": ("Sidebar layout", "the sidebar's items in three lists: Advanced (the whole sidebar), Simple (what everyone sees in Simple "
                   "mode) and User (what accounts that aren't administrators see in Advanced mode); drag items in, reorder, show or hide each", True),
    "developer": ("Developer", "the administrators' development page: a file explorer and editor over AXoR's code and data folders, terminals "
                  "on the server and a Claude Code / Codex conversation, side by side; terminals and prompts ask for sudo and are audited", True),
}

# the sidebar's nine sections (index.html), so agents can say where a page is
SIDEBAR = ("The sidebar (the AXoR Mission Control sidebar: logo and pin at the top; version and health at the foot) has these "
           "sections, after Progress at the top (Goal → Work → Evidence → Approval → Result, five numbered stages that open the existing pages: "
           "Goal = Missions, Competition objectives, Projects; Work = Task board, Team boards, Live operations, Agents; Evidence = Release & benchmarks "
           "(Competition teams → Status), Performance lab, Agent evaluation, Evolution Lab; Approval = Approval Center, Contracts & approvals, Findings "
           "to share; Result = Verified results (Control Hub figure), Miner performance, Rewards & costs, Analytics): Control Hub (Control Hub, Notifications, Approval Center; its Missions and Tasks tabs hold every mission and task); Primary initiative → Bittensor (My Subnets, Competition Teams, Bittensor Research, Subnet Explorer, Mining HQ = My subnets' "
           "command center); Missions (Mission Control = custom missions, Task board, Projects, Portfolio); "
           "Organization (Company Overview = Organization HQ, Contracts & approvals = Company OS, and the tree of departments, teams and agents); Workforce (Agents, Keys = model providers, API keys and connectors, administrators only, "
           "Workforce, Agent Marketplace, Agent HQ, Long tasks, Evolution Lab, Learning, Benchmarks & evaluations); Knowledge (Knowledge Hub, "
           "My Knowledge); Intelligence (Market Research, Technology Research, Recommendations, New Subnets, Analytics; Risk intelligence: "
           "Avoid & Caution, High-risk signals); Workspace (My workspace = tabs Home, Subnets & notes and All files: one catalog over Drive, team files and notebooks, mission deliverables, long-task files and knowledge; File manager, Whiteboard, Study; Connected tools: Source control, Slack, "
           "Discord & Telegram = My Knowledge → Settings & connectors); My profile is in the account menu (top right); System (Governance; "
           "Execution infrastructure: System, Cluster, Machines, Docker; Platform operations: Platform overview, DNS, "
           "DevOps, Apps, Functions; Security & administration: Users & permissions, Wallets & security; Audit & settings: Audit log, Settings, "
           "Appearance; Help & docs; Sidebar layout, administrators only: which items show, and in what order, in Simple mode and for "
           "accounts that aren't administrators; a saved list reorders and hides sidebar items but never grants access; Developer, administrators only, "
           "the sidebar's last item: files, editor, terminals and Claude Code). Live operations, Performance lab, Experiments, Miner "
           "performance and Rewards & costs are on My subnets' own rail (and in Ctrl+K).")

def page_list(admin):
    """The pages a user sees, one line each, then where they sit in the sidebar."""
    return "\n".join(f"- {t}: {d}" for t, d, only in PAGES.values() if admin or not only) + "\n" + SIDEBAR

def page_note(page, admin):
    """A line for the system prompt naming the page a message comes from ("" for none or an unknown one)."""
    p = PAGES.get(page or "")
    if not p or (p[2] and not admin): return ""
    return (f"The user is writing from the {p[0]} page of AXoR ({p[1]}). When they say \"this page\" or \"here\", "
            "they mean that page.")
