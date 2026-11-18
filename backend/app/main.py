"""Subnet Scout API: live subnet data, recommendations, and a server-sent-events update stream."""
import asyncio, concurrent.futures, json, logging, os, threading, time
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import admin, agents, alerts, auth, connectors, devops, docker, drive, kube, machines, nameserver, paas, profile, push, slack, source, study, system, team, wallet, whiteboard, workspace, writing
from . import platform_status
from . import busy
from . import agent_core
from . import mining_evolve
from . import knowledge_hub
from . import missions
from . import mining_upgrade, mining_topminer, ecosystem
from . import marketplace
from . import mining_github
from . import agent_studio, command, company, hubs, learning, company_agents, helpdocs, hq, infiagent, mining,mining_bench, mining_autoloop, mining_command, mining_crew, mining_director, mining_files, mining_import, mining_improve, mining_knowledge, mining_lab, mining_loadout, mining_ops, mining_portfolio, mining_research, mining_source_files, mining_sources, mining_status, mining_web, mining_work, overview, tech_analysis, techboard, updates, workforce
from .collector import Collector
from .recommend import DEFAULTS, recommend
from .store import Store

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(name)s %(levelname)s %(message)s")
HERE = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", HERE.parent / "var"))
FRONTEND = Path(os.getenv("FRONTEND_DIR", HERE.parent.parent / "frontend"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

knowledge = json.load(open(HERE / "data/knowledge.json"))
seed_path = HERE / "data/seed_snapshot.json"
collector = Collector(
    Store(DATA_DIR / "scout.db"), knowledge,
    seed=json.load(open(seed_path)) if seed_path.exists() else None,
    network=os.getenv("SUBTENSOR_NETWORK", "finney"),
    archive=os.getenv("ARCHIVE_NETWORK", "archive"),
    interval=int(os.getenv("REFRESH_SECONDS", "180")),
)

app = FastAPI(title="AXoR", version="5.1.0")
auth_db = auth.AuthDB(DATA_DIR / "auth.db")
auth_router, require_user = auth.build(auth_db)
app.include_router(auth_router)
admin_router = admin.build(auth_db, auth_router.state)
app.include_router(admin_router)
agents_router = agents.build(auth_db, admin_router.state, auth_router.state["ip"], DATA_DIR,
                             require=require_user, data=lambda: collector.state, tiers=knowledge["tiers"])
app.include_router(agents_router)
# the agent core: one registry, run ledger and budget under every agent system (before any of them starts its threads)
agent_core.init(auth_db, agents_router.state.get("hub"))
# people's own Claude Code / Codex logins: Terminal and Codex calls run on the plan of whoever they're for (Agents → My logins)
from . import cli_accounts
cli_accounts.install(app, auth_db, DATA_DIR, require_user, admin_router.state, auth_router.state["ip"], agents_router.state.get("hub"))
# Tools & MCP: MCP servers admins add, the tools agents may call from them (Agents → Tools & MCP; mcp_hub.py)
try: from . import mcp_hub
except ImportError: mcp_hub = None
if mcp_hub and agents_router.state.get("hub"):
    app.include_router(mcp_hub.build(auth_db, agents_router.state["hub"].llm.box, require_user, admin_router.state, auth_router.state["ip"], agents_router.state["hub"].gate))
file_drive = drive.Drive()
workspace_router = workspace.build(auth_db, require_user, lambda: collector.state, knowledge["tiers"],
                                   agents_router.state["hub"], agents_router.state["ready"],
                                   drive=file_drive, legacy_dir=DATA_DIR / "workspace_files")
pdca = None
if agents_router.state.get("hub"):  # the project team runs PDCA cycles on its own (Team tab in the workspace)
    pdca = team.Team(auth_db, agents_router.state["hub"])
    team.routes(workspace_router, pdca, require_user, agents_router.state["hub"].gate, agents_router.state["ready"])
app.include_router(workspace_router)
if agents_router.state.get("hub"):  # agents can read shared files the user attaches with @
    agents_router.state["hub"].read_file = workspace_router.state["ws"].read_text
alerts_router = alerts.build(auth_db, require_user, collector, knowledge["tiers"])
app.include_router(alerts_router)
slack_router = slack.build(auth_db, require_user, admin_router.state, auth_router.state["ip"], DATA_DIR,
                           data=lambda: collector.state, alerts=alerts_router.state["alerts"])
app.include_router(slack_router)
push_router = push.build(auth_db, require_user, admin_router.state, auth_router.state["ip"], alerts_router.state["alerts"])
app.include_router(push_router)  # Web Push through AXoR Push (push/): devices, push settings, announcements
alerts_router.state["alerts"].on_new = push.fanout(slack_router.state["slack"].on_alert, push_router.state["notifier"].on_alert)
source_router = source.build(auth_db, require_user, admin_router.state, auth_router.state["ip"], DATA_DIR)
app.include_router(source_router)
if agents_router.state.get("hub"):  # project-team agents read the team's repos and CI (read-only)
    agents_router.state["hub"].source = source_router.state["source"]
wallet_router = wallet.build(auth_db, require_user, lambda: collector.state, auth_router.state["ip"], DATA_DIR)
app.include_router(wallet_router)
drive_router = drive.build(auth_db, require_user, admin_router.state["admin"], auth_router.state["ip"], file_drive)
app.include_router(drive_router)
app.include_router(drive_router.state["public"])  # /s/<token>: share links, no sign-in
app.include_router(docker.build(auth_db, admin_router.state, auth_router.state["ip"]))
devops_router = devops.build(auth_db, admin_router.state, auth_router.state["ip"], DATA_DIR, source_router.state["source"])
app.include_router(devops_router)  # admins: pipelines that build, test and deploy Source hub repos through the AXoR Runner
if agents_router.state.get("hub"):  # the DevOps engineer (and admins' agents) read pipelines, runs and app logs
    agents_router.state["hub"].devops = devops_router.state["devops"]
app.include_router(connectors.build(auth_db, admin_router.state, auth_router.state["ip"], DATA_DIR))  # admins: every key AXoR holds; OpenRouter API keys
system_router =system.build(admin_router.state["admin"], DATA_DIR)  # server resources: app bar, status bar, System page
app.include_router(system_router)
from . import side_layout
app.include_router(side_layout.build(auth_db, require_user, admin_router.state["admin"], auth_router.state["ip"]))  # System → Sidebar layout: the Simple and User sidebar lists
from . import ui_v3
app.include_router(ui_v3.build(auth_db, require_user, auth_router.state["ip"]))  # /api/ui: UI v3 (React /app) preferences, settings, news sources
cluster_router = kube.build(auth_db, admin_router.state, auth_router.state["ip"])
app.include_router(cluster_router)  # admins: the Kubernetes cluster AXoR runs on (Cluster page)
app.include_router(updates.build(auth_db, admin_router.state, auth_router.state["ip"], cluster_router.state["kube"]))  # admins: the updater on the host (Cluster → Updates)
paas_router = paas.build(auth_db, admin_router.state, auth_router.state["ip"], DATA_DIR, cluster_router.state["kube"])
app.include_router(paas_router)  # admins: apps, functions, and the domain and HTTPS they're served on
app.middleware("http")(paas_router.state["guard"])  # unknown *.apps / *.fn names: 404, not AXoR's sign-in page
operations = agents_router.state["operations"]  # the DevOps, Functions, Apps, Cluster and DNS agents (ops_agents.py)
operations.devops, operations.monitor = devops_router.state["devops"], system_router.state["monitor"]
operations.cluster, operations.platform = cluster_router.state["cluster"], paas_router.state["platform"]
app.include_router(machines.build(auth_db, admin_router.state, auth_router.state["ip"], cluster_router.state["kube"]))  # admins: Linux and Windows VMs
from . import developer
app.include_router(developer.build(auth_db, admin_router.state, auth_router.state["ip"]))  # admins: the Developer page (explorer, editor, terminals, Claude Code panel)
app.include_router(nameserver.build(auth_db, admin_router.state, auth_router.state["ip"], paas_router.state["platform"].dns,
                                    platform_zone=lambda: paas_router.state["platform"].settings()["domain"],
                                    public_ip=paas_router.state["platform"].public_ip))  # admins: AXoR DNS zones and records
app.include_router(whiteboard.build(auth_db, require_user, agents_router.state.get("hub"), agents_router.state.get("ready")))
app.include_router(writing.build(require_user, agents_router.state.get("hub"), agents_router.state.get("ready")))  # writing help in every text field
study_router = study.build(auth_db, require_user, agents_router.state.get("hub"), agents_router.state.get("ready"))
app.include_router(study_router)
if agents_router.state.get("hub"):  # study agents read the learner's progress and tick topics (Study tab)
    agents_router.state["hub"].study = study_router.state["study"]
profile_router = profile.build(auth_db, require_user, auth_router.state["ip"], DATA_DIR,
                               agents_router.state.get("hub"), agents_router.state.get("ready"))
app.include_router(profile_router)
app.include_router(profile_router.state["public"])  # /u/<slug>: published profiles, no sign-in
LOGIN = os.getenv("REQUIRE_LOGIN", "1") == "1"

def user(req: Request):
    return require_user(req) if LOGIN else None

# Tech Daily (the day's new technology, told like ads) and Help (the docs and the API reference): for everyone signed in
tech_router = techboard.build(auth_db, user, admin_router.state["admin"], auth_router.state["ip"], agents_router.state.get("hub"))
app.include_router(tech_router)
# Technology Research analysis: Analyze on a story, and the day's / week's brief (tech_analysis.py)
app.include_router(tech_analysis.build(auth_db, user, require_user, auth_router.state["ip"],
                                       tech_router.state["board"], agents_router.state.get("hub")))
app.include_router(helpdocs.build(user, app))
# Platform status: which services are set up, for the Dashboard and the Developer / Infrastructure page tabs (platform.js)
app.include_router(platform_status.build(require_user, collector, drive=file_drive, slack=slack_router.state["slack"], source=source_router.state["source"],
                                  push=push_router.state["notifier"].push, ready=agents_router.state.get("ready"), docker_url=docker.URL,
                                  runner=devops_router.state["devops"].runner, kube=cluster_router.state["kube"], dns=paas_router.state["platform"].dns))
# Agent HQ (admins): field agents patrol the services and infrastructure, leads review their fixes, the Team Boss reports hourly
hq_router = hq.build(auth_db, admin_router.state, auth_router.state["ip"], operations, agents_router.state.get("hub"))
hq_router.state["hq"].notifier = push_router.state["notifier"]
app.include_router(hq_router)
# My subnets (anyone who may use agents): a team per user and subnet that watches the competition, tracks their miners and plans the climb
mining_router = mining.build(auth_db, require_user, admin_router.state, auth_router.state["ip"], lambda: collector.state,
                             agents_router.state.get("hub"), operations)
mining_router.state["mining"].notifier = push_router.state["notifier"]
agent_core.set_notifier(lambda uid, title, body, urgent: push_router.state["notifier"].send_user(  # budget alerts (agent_core._threshold)
    uid, title, body, urgent, url="/#layers", kind="budget", tag=f"budget-{uid}"), enabled=lambda: push_router.state["notifier"].push.enabled)
mining_router.state["mining"].drive = file_drive  # the Scribe saves results to the owner's My workspace
app.include_router(mining_router)
# its workspaces: one per competition the user enters on a campaign's subnet, each with its own agent team and task board
mining_work_router = mining_work.build(mining_router.state["mining"], require_user, auth_router.state["ip"], cluster_router.state["kube"])
app.include_router(mining_work_router)
if mcp_hub: mcp_hub.bind_teams(mining_work_router.state["work"])  # "team:<id>" grants: a Competition team's agents get its MCP tools
# and their crew: prompt histories, the roadmap, links to the rest of AXoR, the diagram's layout, engineer levels
app.include_router(mining_crew.build(mining_work_router.state["work"], require_user))
# and the Director's report: the user hears from the Director, who settles what the team can, not from each agent
app.include_router(mining_director.build(mining_work_router.state["work"], require_user))
# Agent Execution Fabric (exec_env.py, D-032): the execution history and run records, mission workspaces and their snapshots, a
# team's execution policy, the emergency stop. The Unified Agent Control Panel reads it (topology.js).
from . import exec_env
app.include_router(exec_env.build(mining_work_router.state["work"], require_user))
# and the team's status: how far it has got, what it does right now and why it isn't moving, each reason with its fix
app.include_router(mining_status.build(mining_work_router.state["work"], require_user))
# and live web reading: web_read for agents, saved recipes and watches that keep data/web/ fresh (mining_web.py)
app.include_router(mining_web.build(mining_work_router.state["work"], require_user))
# and the competitor harvest: every agent of a Ridges competition, failed ones included, as data/rivals/ files and a digest (mining_rivals.py)
from . import mining_rivals
app.include_router(mining_rivals.build(mining_work_router.state["work"], require_user))
# and the Autoloop's rules: the budget governor, failure classes and retries, queue caps, one agent per file
app.include_router(mining_autoloop.build(mining_work_router.state["work"], require_user))
# and importing the user's earlier work on a competition: files, notes, git history, conversations, then the Director's plan
app.include_router(mining_import.build(mining_work_router.state["work"], require_user))
# and importing competitions: sources checked on a schedule, URL / JSON / CSV imports, a review queue the user approves teams from
mining_sources_router = mining_sources.build(mining_work_router.state["work"], require_user, auth_router.state["ip"])
app.include_router(mining_sources_router)
# and the Workflow: a small team that works on a real folder of the host (the AXoR Workbench), asking you at every step
app.include_router(mining_bench.build(mining_work_router.state["work"], require_user))
# and requests from GitHub: an allowed person mentions the team on an issue or PR, it becomes a Workflow task, replies go to the thread
app.include_router(mining_github.build(mining_work_router.state["work"], require_user))
# and each Workflow agent's loadout: skills, plugins, MCP servers, memory, effort, versions and how each version scored
app.include_router(mining_loadout.build(mining_work_router.state["work"], require_user))
# and the Lab: the eval score of every checked commit, the base it's measured against, earlier evals, task-by-task compares
app.include_router(mining_lab.build(mining_work_router.state["work"], require_user))
# and improvements: when an engineer's work loses eval tasks, a proposed change to its loadout, measured on the same eval
app.include_router(mining_improve.build(mining_work_router.state["work"], require_user))
# and self-improvement on its own (setting "self"): test, promote, then keep or roll back on the next real outcomes
app.include_router(mining_evolve.build(mining_work_router.state["work"], require_user))
# and the Agent Upgrade Factory: a timed sprint that diagnoses, upgrades and re-tests a team's agents on held-out tasks
app.include_router(mining_upgrade.build(mining_work_router.state["work"], require_user))
# and Top miner: the M1-M5 roadmap, the validation set, the scorecard from the Lab, the elite team and the first mission
app.include_router(mining_topminer.build(mining_work_router.state["work"], require_user))
# and the file manager: a team's files beside My workspace's (AXoR Drive), copied either way
app.include_router(mining_files.build(mining_work_router.state["work"], file_drive, require_user))
# and release discipline: one frozen candidate + benchmark suite per team, comparable results only, duplicate tasks kept off the board
from . import mining_release  # noqa: E402
app.include_router(mining_release.build(mining_work_router.state["work"], require_user))
# and the GitHub side of it: the Source hub's repositories, copied to and from the team and My workspace (commits: admins)
app.include_router(mining_source_files.build(mining_work_router.state["work"], file_drive, require_user, auth_router.state["ip"]))
# Portfolio (Global HQ): shared knowledge between the user's teams (three tiers, the Knowledge Manager), the teams side by
# side, the Portfolio Manager's calls on where effort should go, and task forces that join a team for a goal and then dissolve
app.include_router(mining_knowledge.build(mining_work_router.state["work"], require_user))
app.include_router(mining_portfolio.build(mining_work_router.state["work"], require_user))
# Workforce (anyone who may use agents): a CEO, six teams of leads and specialists, a red teamer and an independent evaluator
# run missions; the workforce remembers what it verified, routes calls across a model pool and proposes tested improvements
workforce_router = workforce.build(auth_db, require_user, agents_router.state.get("hub"), lambda: collector.state, auth_router.state["ip"])
app.include_router(workforce_router)
# and the Workflow's research arm: one Workforce mission per team, its report in the Director's next plan
mining_work_router.state["work"].workforce = workforce_router.state["workforce"]
app.include_router(mining_research.build(mining_work_router.state["work"], require_user))
# My workspace → Overview: what waits for you and what every agent does, across the teams, the Workflow, My subnets and the rest
overview_router = overview.build(auth_db, require_user, mining_work_router.state["work"], pdca, workforce_router.state["workforce"], agents_router.state.get("hub"))
app.include_router(overview_router)
# Long tasks (InfiAgent, anyone who may use agents): agents whose state lives in a workspace of files, so a task can run for
# hundreds of steps with a bounded prompt: a thinking record rewritten every few tool calls, Alpha → domain → atomic agents
infiagent_router = infiagent.build(auth_db, require_user, agents_router.state.get("hub"), lambda: collector.state, DATA_DIR)
app.include_router(infiagent_router)
# Company (anyone who may use agents): an AI agent company over divisions, projects, dynamic teams and an agent registry with
# contracts; approvals bound to exact artifacts and consumed once by the execution gateway; an append-only audit log
company_router = company.build(auth_db, require_user, agents_router.state.get("hub"), lambda: collector.state)
app.include_router(company_router)
# Company → Agents: each agent's workspace (chat in a project context, instructions, memory, tools, model profile, autonomy,
# monthly budget, performance, activity) and the directory's clone, archive and project assignments
app.include_router(company_agents.build(require_user, company_router))
# Organization (organization.js): one hierarchical + matrix organization over the Company, Workforce and your agents: units,
# permanent reporting lines, missions with temporary assignments, execution authority L0-L4, delegation/escalation, performance
from . import organization
organization_router = organization.build(auth_db, require_user, agents_router.state.get("hub"))
app.include_router(organization_router)
# AXoR 2.0 Command Center and Approval Center (command.js): the Overview plus the organization and every request waiting for the
# user across My subnets, the Company, Workforce, Agent HQ and the Portfolio; read only, each decision stays on its own page
command_router = command.build(auth_db, require_user, overview_router.state["overview"], company_router.state["company"], auth_router.state["ip"])
command_router.state["command"].sources = mining_sources_router.state["sources"]  # stale imports are archived as drafts there
app.include_router(command_router)
# AXoR 2.0 hubs (hubs.js): Organization, Projects and Missions, Governance, Evaluation, Workspace and Settings, read only over the same systems
app.include_router(hubs.build(auth_db, require_user, overview_router.state["overview"], company_router.state["company"]))
# Learning (hub-learning.js): mission lessons, improvements, watches and upgrade sprints across every agent system
app.include_router(learning.build(auth_db, require_user, overview_router.state["overview"], company_router.state["company"]))
# Intelligence layers (hub-layers.js, /api/layers): mission, workforce, execution, knowledge intelligence, evaluation and adaptive
# intelligence, each read live from the parts that do that layer's work
from . import intel_layers
app.include_router(intel_layers.build(auth_db, require_user, overview_router.state["overview"], company_router.state["company"]))
# Agent Operations (agent-studio.js): every agent system in one workspace: overview, live runs and traces, and an Agent Studio per agent
# (instructions, skills, tools, memory, tasks, evaluations, versions, activity); your own agents get versions, restore and tests
studio_router = agent_studio.build(require_user, overview_router.state["overview"], agents_router.state.get("hub"), company_router.state["company"],
                                   command_router.state["command"])
app.include_router(studio_router)
# and the Ecosystem: the eight layers read live from the systems that do them, and a registry of external agents' cards (never called)
app.include_router(ecosystem.build(require_user, studio_router.state["studio"], agents_router.state.get("hub")))
# Agent Marketplace (AXoR 4.0, marketplace.js): discover agents (your library, Agent Cards, GitHub, pasted packages), evaluate them on
# their role's tasks, import them with the original kept as version 1, adapt, test, approve the exact version, then activate it as
# one of your agents (custom_agents: Agents, Agent Operations, the ledger); continuous re-evaluation flags regressions
market_router = marketplace.build(require_user, agents_router.state.get("hub"), company_router.state["company"])
app.include_router(market_router)
# Knowledge hub (knowledge.js): earlier workspaces, your ideas and other agents' experiences in one layer that your agents search
# (search_knowledge) and competition teams read; adopting anything into an agent waits for your approval
knowledge_router = knowledge_hub.build(auth_db, require_user, agents_router.state.get("hub"), agents_router.state.get("ready"),
                                       company_router.state["company"], mining_work_router.state["work"], slack=slack_router.state["slack"])
app.include_router(knowledge_router)
# Experience recall (experience.py, mixed into the Knowledge Hub): earlier work's lessons, missions, memories and findings that fit
# what an agent is about to do, and how work that used them went; Learning → Experience recall reads /api/experience
from . import experience
app.include_router(experience.build(require_user, getattr(knowledge_router, "state", {}).get("knowledge")))
# My subnets → Command center: the Bittensor division's control room: evaluator metrics and the Performance Lab, experiments from
# idea to monitoring (deploy approvals through the Company's gateway), miners, rewards against costs, monitoring, every team agent
mining_command_router = mining_command.build(mining_work_router.state["work"], require_user)
mining_command_router.state["command"].co = company_router.state["company"]
app.include_router(mining_command_router)
# My subnets operations: the live feed across teams, deployment history, budget and performance alerts (also in the Command
# center's Monitoring), moving agents between teams, and the project assistant
mining_ops_router = mining_ops.build(mining_command_router.state["command"], require_user)
mining_command_router.state["command"].ops = mining_ops_router.state["ops"]
app.include_router(mining_ops_router)
# Mission Control (AXoR 3.0, mission.js): a goal, a budget in dollars and a deadline become a mission (understand, discover, plan,
# allocate, execute, verify, deliver, learn) run by the engine that fits: AXoR directly, Workforce, Long tasks or a Competition team
# Agent Swarm (AXoR G5, swarm.js): a Swarm Controller sizes a temporary team of Workforce agents, picks a swarm pattern and runs the
# mission as task contracts over their dependencies, with a message bus, a blackboard, independent checks, reassignment and replans
from . import swarm
swarm_router = swarm.build(auth_db, require_user, agents_router.state.get("hub"), workforce_router.state["workforce"], auth_router.state["ip"])
app.include_router(swarm_router)
missions_router = missions.build(auth_db, require_user, agents_router.state.get("hub"), workforce_router.state["workforce"],
                                 infiagent_router.state["infiagent"], mining_work_router.state["work"], auth_router.state["ip"],
                                 sw=swarm_router.state["swarm"])
if missions_router.state["missions"]: missions_router.state["missions"].att.source = source_router.state["source"]  # attached GitHub repos in Source control: read with its token
app.include_router(missions_router)
# General Manager chat (D-039): the chat button in every page's top bar; an assignment becomes a mission (gm_chat.py)
from . import gm_chat
app.include_router(gm_chat.build(auth_db, require_user, missions_router, agents_router.state.get("hub")))
# Team tests (team-tests.js): a fixed library of test problems (T01-T10 + your own) run through Mission Control and graded on hidden
# checks; benchmark missions are kept out of lessons, memory and recall (missions.ISOLATED)
from . import team_eval
team_eval_router = team_eval.build(auth_db, require_user, missions_router.state["missions"], agents_router.state.get("hub"))
app.include_router(team_eval_router)
# Control Hub (control.js): one place to run the organization as Organization → Departments (a subnet, or a top unit) → Teams
# (a Competition team, or a unit's team) → Agents; missions (predefined: top-N miner on a competition; custom: Mission Control) and their fixed/dynamic tasks, hybrid staffing
# with approvals, and every agent's own workspace (chat with files, pictures, voice, video, web search)
from . import control_hub
control_router = control_hub.build(auth_db, require_user, organization_router.state["org"], mining_work_router.state["work"],
                                   missions_router.state["missions"], agents_router.state.get("hub"), command_router.state["command"],
                                   auth_router.state["ip"])
app.include_router(control_router)
# Unified control panel (topology.js, /api/topology): one typed graph of AXoR with seven synchronized projections (organization,
# missions, agent execution, infrastructure, network, knowledge lineage, observability) that share each entity's identity
from . import topology
app.include_router(topology.build(auth_db, require_user, control_router.state["control"], cluster_router.state["cluster"], agents_router.state.get("hub")))

# All files (file-catalog.js, in My workspace): one read-only catalog over Drive, team files and notebooks, mission deliverables,
# long-task files and knowledge, each read through its own store's access path, with one scope per item
from . import artifacts
app.include_router(artifacts.build(auth_db, require_user, drive=file_drive, work=mining_work_router.state["work"],
                                   ia=infiagent_router.state["infiagent"], missions=missions_router.state["missions"], hub=agents_router.state.get("hub")))

# AXoR 5.0: the Evolution Engine (evolution.js): benchmarks, proposals, blind experiments against the current version, promotion only
# with measured evidence and as the policy allows, versions and rollback (your agents' through the Agent Studio); Analytics
# (analytics.js: cost per validated deliverable, the Generation 5 scorecard) and Governance (governance.js: policy, budgets,
# autonomy levels, what waits for you, rollback points, audit), read-only over the systems that already decide
from . import analytics, evolution, governance
evolution_router = evolution.build(auth_db, require_user, overview_router.state["overview"], agents_router.state.get("hub"), studio_router.state["studio"],
                                   learning.Learning(auth_db, overview_router.state["overview"], company_router.state["company"]))
app.include_router(evolution_router)
evolution_router.state["evolution"].teams = mining_work_router.state["work"]  # G5-5 L5.4: the gate reaches competition team agents through their own version store
mining_work_router.state["work"].upgrade.evolution = evolution_router.state["evolution"]  # D-031: the Upgrade Factory sends a screened candidate to the gate; it promotes nothing itself
evolution_router.state["evolution"].missions = missions_router.state["missions"]  # a promoted trial that answered a mission's gap leaves one lesson there (None: Mission Control is off)
if missions_router.state["missions"]: missions_router.state["missions"].evolution = evolution_router.state["evolution"]  # G5-5 L5.5 (IC-7): a rule-4 cycle's gap becomes a proposal
app.include_router(analytics.build(auth_db, require_user, overview_router.state["overview"], company_router.state["company"]))
app.include_router(governance.build(auth_db, require_user, overview_router.state["overview"], company_router.state["company"], evolution_router.state["evolution"]))

# AXoR G5: the Unified Intelligence Orchestrator (orchestrator.py, /api/g5, shown on Intelligence layers): correlation ids and
# scoped hard limits at the agent core's gateway, handoff events with retries and dead letters, evaluation coverage, failure and
# sandbox diagnosis, versioned benchmark datasets, the retrieval benchmark, the post-promotion monitor, guidance for missions
from . import orchestrator
orchestrator_router = orchestrator.build(auth_db, require_user, overview_router.state["overview"], agents_router.state.get("hub"),
                                         evolution_router.state["evolution"], mining_work_router.state["work"])
app.include_router(orchestrator_router)
# what "Recover" on a diagnosed failed run goes through: each system's own restart, resume or rerun (None where a system is off)
orchestrator_router.state["orchestrator"].systems = {k: v for k, v in (("control", control_router.state["control"]), ("missions", missions_router.state["missions"]),
                                                                       ("workforce", workforce_router.state["workforce"]), ("infiagent", infiagent_router.state["infiagent"])) if v}

# AXoR 5.1: the spec's stack (stack.py: /api/stack + the React front end at /app): PostgreSQL behind AuthDB (db_pg.py, DATABASE_URL),
# Temporal under Mission Control (mission_temporal.py, MISSIONS_RUNTIME=temporal), LangGraph for the direct engine (agent_graph.py)
from . import stack
app.include_router(stack.build(require_user, FRONTEND, auth_db))
# 5.1: Prometheus /metrics (METRICS_TOKEN), OpenTelemetry traces (OTEL_EXPORTER_OTLP_ENDPOINT), events to Redis (bus.py, REDIS_URL)
from . import metrics
metrics.install(app, auth_db)

# media-src blob: lets the Control Hub's agent workspace read frames from a video the user picked (a blob: URL only this page's
# own scripts can make); no remote media
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' https: data:; media-src 'self' blob:; "
       "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
# the Study Lab's worker runs learners' Python: it loads Pyodide from its pinned path and packages from PyPI, and can't
# reach anything else, AXoR's own API included, so code typed in the lab can't act as the signed-in user
LAB_WORKER = "/static/lab-worker.js"
LAB_CSP = (f"default-src 'none'; script-src {study.PYODIDE} 'wasm-unsafe-eval'; "
           f"connect-src {study.PYODIDE} https://pypi.org https://files.pythonhosted.org")

@app.middleware("http")
async def guard(req: Request, call_next):
    # CSRF: state-changing API calls must come from our own page (custom header + same-origin Origin)
    if req.method in ("POST", "PUT", "PATCH", "DELETE") and req.url.path.startswith("/api/"):
        origin = req.headers.get("origin")
        host = req.headers.get("x-forwarded-host") or req.headers.get("host", "")
        if req.headers.get("x-requested-with") != "scout" or (origin and origin.split("://", 1)[-1] != host):
            return JSONResponse({"detail": "Cross-site request blocked."}, status_code=403)
    resp = await call_next(req)
    h = resp.headers
    if req.url.path == LAB_WORKER: h["Content-Security-Policy"] = LAB_CSP  # a worker gets its CSP from its own response
    h.setdefault("Content-Security-Policy", CSP)  # drive content sets a stricter one of its own
    h["X-Content-Type-Options"] = "nosniff"
    h.setdefault("X-Frame-Options", "DENY")  # drive previews (PDF, video) are framed by the app itself
    h["Referrer-Policy"] = "no-referrer"
    h["Permissions-Policy"] = "camera=(), microphone=(self), geolocation=()"  # microphone: voice input in agent chats
    h["Cross-Origin-Opener-Policy"] = "same-origin"
    if req.url.scheme == "https":
        h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if req.url.path.startswith("/api/"):
        h["Cache-Control"] = "no-store"
    elif req.url.path == "/" or req.url.path.startswith("/static/"):
        # revalidate on every load (a cheap 304 via ETag) so a deploy reaches browsers right away
        h["Cache-Control"] = "no-cache"
    return resp

@app.on_event("startup")
def _start():
    collector.start()
    alerts_router.state["alerts"].start()
    slack_router.state["slack"].start()
    if pdca: pdca.start_scheduler()
    devops_router.state["devops"].start()
    system_router.state["monitor"].start()
    paas_router.state["platform"].start()  # on Kubernetes: keeps the edge certificate, DNS and routes in step
    tech_router.state["board"].start()  # builds Tech Daily's edition once a day
    hq_router.state["hq"].start()  # Agent HQ's patrols and hourly reports
    mining_router.state["mining"].start()  # My subnets' snapshots, alerts and team cycles
    if workforce_router.state["workforce"]: workforce_router.state["workforce"].start()  # closes plans nobody decided on
    if infiagent_router.state["infiagent"]: infiagent_router.state["infiagent"].start()  # resumes long tasks from their checkpoints
    if company_router.state["company"]: company_router.state["company"].start()  # expires approval requests nobody decided on
    if organization_router.state["org"]: organization_router.state["org"].start()  # escalates overdue delegated tasks, expires requests
    if market_router.state["market"]: market_router.state["market"].start()  # the Agent Marketplace's continuous evaluation
    if swarm_router.state["swarm"]: swarm_router.state["swarm"].start()  # resumes swarms a restart cut off, from their contracts
    if missions_router.state["missions"]: missions_router.state["missions"].start()  # resumes missions from their stage, watches budgets and deadlines
    if team_eval_router.state["teameval"]: team_eval_router.state["teameval"].start()  # follows running team tests, grades finished cases
    evolution_router.state["evolution"].start()  # the Evolution Engine's own rounds (only for policies that let it experiment)
    orchestrator_router.state["orchestrator"].start()  # G5: evaluation coverage, diagnosis, handoffs, monitor (every G5_TICK s)
    threading.Thread(target=workspace_router.state["ws"].migrate, daemon=True, name="drive-migration").start()

@app.on_event("shutdown")
def _stop_evolution():
    evolution_router.state["evolution"].stop()  # a running experiment ends between answers; its proposal goes back to proposed on the next start
    orchestrator_router.state["orchestrator"].stop()
    if team_eval_router.state["teameval"]: team_eval_router.state["teameval"].stop()

@app.get("/api/health")
def health():
    s = collector.state
    # busy: agent loops and model calls in flight here (busy.py); a deploy waits for 0. A count only: nothing about whose.
    return {"status": s["status"], "block": s["block"], "updated": s["updated"], "subnets": len(s["subnets"]), "version": app.version,
            "busy": busy.count()}

# ---------- liveness and readiness (Kubernetes probes) ----------
# /api/live: the process answers. It reads nothing, so a database outage never gets a healthy process restarted.
# /api/ready: the process can serve: the database answers a query within READY_TIMEOUT seconds. 503 otherwise, so the replica gets
# no traffic until it does; the process keeps running and reconnects by itself (db_pg). /api/health above is unchanged (the deploy
# scripts read its version and busy count).
READY_TIMEOUT = float(os.getenv("READY_DB_TIMEOUT", "3"))
_ready = {"job": None, "lock": threading.Lock()}
_ready_pool = concurrent.futures.ThreadPoolExecutor(1, thread_name_prefix="ready")

@app.get("/api/live")
def live():
    return {"status": "alive", "version": app.version}

@app.get("/api/ready")
def ready():
    t0 = time.time()
    with _ready["lock"]:  # one check in flight: a database that hangs ties up one thread, not one per probe
        if _ready["job"] is None or _ready["job"].done(): _ready["job"] = _ready_pool.submit(auth_db.q, "SELECT 1 AS ok", (), True)
        job = _ready["job"]
    try:
        job.result(timeout=READY_TIMEOUT)
        db = {"ok": True, "ms": round((time.time() - t0) * 1000, 1)}
    except concurrent.futures.TimeoutError:
        db = {"ok": False, "error": f"no answer within {READY_TIMEOUT:g} s"}
    except Exception as e:  # noqa: BLE001 - the error's kind only: this endpoint is public
        db = {"ok": False, "error": type(e).__name__}
    return JSONResponse({"ready": db["ok"], "version": app.version, "checks": {"database": db}}, status_code=200 if db["ok"] else 503)

@app.get("/api/subnets", dependencies=[Depends(user)])
def subnets():
    return collector.state

@app.get("/api/meta", dependencies=[Depends(user)])
def meta():
    fields = sorted({v["field"] for v in knowledge["subnets"].values()} - {"Unknown"})
    return {"tiers": knowledge["tiers"], "fields": fields, "defaults": DEFAULTS, "login": LOGIN}

class Profile(BaseModel):
    hardware: str | None = None
    own_hardware: bool | None = None
    budget_usd: float | None = None
    capital_tao: float | None = None
    fields: list[str] | None = None
    risk: str | None = None
    count: int | None = None
    only_uid_available: bool | None = None
    exclude_scam: bool | None = None
    exclude_avoid: bool | None = None
    exclude_winner_take_all: bool | None = None
    min_age_days: float | None = None
    weights: dict[str, float] | None = None

@app.post("/api/recommend", dependencies=[Depends(user)])
def recommend_api(profile: Profile):
    s = collector.state
    return recommend(s["subnets"], knowledge["tiers"], s["tao_usd"], profile.model_dump(exclude_none=True))

@app.get("/api/stream", dependencies=[Depends(user)])
async def stream(req: Request):
    """Emits an `update` event whenever a new collection pass lands (and a keep-alive otherwise)."""
    async def gen():
        v = -1
        while True:
            try:
                user(req)  # stop streaming once the session is signed out or expires
            except Exception:
                yield "event: auth\ndata: {}\n\n"
                return
            nv = await asyncio.to_thread(collector.wait, v, 25)
            if nv != v:
                v = nv
                s = collector.state
                yield f"event: update\ndata: {json.dumps({'version': v, 'block': s['block'], 'updated': s['updated']})}\n\n"
            else:
                yield ": keep-alive\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

    @app.get("/")
    def index():
        return FileResponse(FRONTEND / "index.html")
