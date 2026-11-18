/* The page guide's content (guide.js runs it): for each view, a short intro, what to try first, the help doc that covers
   it, spotlight steps on elements the page always has, and what each tab and main button is for. Steps whose element
   isn't on screen are skipped, and guide.js adds steps for whatever tabs, searches, buttons and forms the page shows,
   so a page's tour follows its state (empty or full, admin or not). Bodies are trusted HTML written here; anything read
   from the page is escaped by guide.js.

   GuideFields are the value suggestions shown under a field when it gets focus: rules are tried in order (a view's own
   first, then everyone's), and the first that returns values wins. get(el, c) returns a list of values ("x" or
   { v, label }) or { values, why }; c has view, form, me, val(name), data (the subnet snapshot), workspace() and
   name(netuid). Suggestions only fill a field, never submit it, and never propose an amount to send or stake, an
   address or a secret. */
const GuidePages = {
  // ---------- everyone ----------
  dashboard: {
    intro: "Your daily view of the network: the fund and emission picture, the best opportunities right now, your workspace subnets, notes and the latest notifications.",
    tips: ["Click a subnet row to open its details and 7-day charts.", "Subnets you add to your workspace (from Explorer or Recommend) show up here."],
    doc: "dashboard",
    steps: [{ sel: "#dash .stats", title: "The network at a glance", body: "TAO price, emission, fund flows and open UIDs, live from the chain." },
            { sel: "#dash .dash-alerts", up: ".card", title: "Latest notifications", body: "The newest alerts. The bell in the top bar and the Notifications page have all of them." }],
    tabs: { _: "Pick the metric fund movers are ranked by." },
  },
  notifications: {
    intro: "Every alert AXoR raises for you, with push to this browser and your other devices.",
    tips: ["Turn on push under <b>Devices</b> to get alerts when no AXoR tab is open.", "Set quiet hours and a cap under <b>Settings</b>."],
    doc: "dashboard",
    tabs: { Inbox: "Every alert, filtered by kind or unread.", Devices: "Turn on push for each browser or phone; rename, test or remove them.",
            Settings: "Per kind: show it in the bell, push it, or both. Quiet hours and an hourly cap live here too.", History: "Every push sent to your devices and whether it arrived.",
            Server: "The push service behind it." },
  },
  workspace: {
    intro: "Your shortlist of subnets. Each one gets a mining brief: the task, budget, a low-cost plan, how to become a top miner and the competition, plus notes, files, news and agents.",
    tips: ["Add subnets from Explorer or Recommend with <b>Add to workspace</b>.", "Add a project team to build a miner with seven agents, one per stage of the work.",
           "<b>Overview</b>, at the top of the sidebar, shows everything waiting for you and every agent at work, across all your teams."],
    doc: "workspace",
    tabs: { Brief: "The mining brief: task, budget, low-cost plan and how to become a top miner.", News: "News about this subnet.",
            Team: "The project team: a PDCA cycle with tasks and approvals.", Reports: "What the team reported and what waits for you." },
    buttons: { "Add subnets": "Pick subnets to follow. You can also add them from any subnet's details." },
  },
  mining: {
    intro: "A team of agents on each subnet you compete in: they read the competition, watch your miners and propose changes for you to approve.",
    tips: ["Start with <b>New campaign</b> and pick a subnet.", "Actions waiting for your approval show as a count in the sidebar."],
    doc: "mining",
    tabs: { Overview: "What the team is doing and what waits for you.", Competition: "The leaderboard and how the subnet scores miners.",
            Teams: "The control room for this subnet's competition teams: autopilot, pause, stop, budgets and Import competitions.", "My miners": "Your miners' ranks, earnings and alerts.",
            Team: "The agents on this campaign.", Activity: "Everything the team did, newest first.", Settings: "Autonomy, model, budget and notifications.",
            Dashboard: "Command center: every competition's numbers, what's critical and what waits for you.", Competitions: "One competition's HQ: overview, intelligence, miners, team, performance, experiments, files, knowledge and strategy.",
            Performance: "The Performance Lab: measured metrics over time, on-chain rank, the Lab's runs, and connecting the evaluator.",
            Experiments: "Idea to monitoring: isolated trials, baseline against candidate, an independent review, your approval, the deploy you record.",
            Miners: "Each miner's on-chain state, health, versions, logs and deploy history.", Rewards: "On-chain rewards and payouts against the costs you enter.",
            Approvals: "Every production or external action waiting for you.", Monitoring: "Silent miners, quiet evaluators, regressions after a deploy, critical alerts.", Agents: "Every competition-team agent, filtered." },
    buttons: { "New campaign": "Put a team on a subnet. You set how much they may do without asking.", "Command center": "My subnets' control room across every campaign and competition.",
               "New experiment": "Start an improvement as an idea; it moves stage by stage to a deploy you approve.", "Record a measurement": "Store a run you measured yourself." },
  },
  teams: {
    intro: "An agent team per competition you enter (a tab per subnet and competition): a Director, squad leads and specialists with their own board, notebook and sandbox.",
    tips: ["<b>Import competitions</b> brings them in from a page, a file or a source such as Ridges; nothing becomes a team until you approve it.", "Set a team's budget before you switch <b>Autopilot</b> on: a 20-agent team can spend 1-3M tokens a day."],
    doc: "mining",
    tabs: { Board: "Tasks from To do to Done; what waits for you has its own column.", Team: "The org chart: the Director, then each squad under its lead.",
            Notebook: "Every approved finding; agents read it before they work.", "Files & sandbox": "The team's files beside My workspace's (copy either way), and the code runs on them, with PostgreSQL and ClickHouse.",
            Activity: "Everything the team did, newest first." },
    buttons: { "Import competitions": "Competitions from pages, JSON, CSV and followed sources, waiting for your review and approval.", "New competition": "A team for a competition you add yourself.",
               "Plan now": "The Director writes the next tasks and assigns them.", "Run a command": "Runs a command in a throwaway sandbox on the team's files." },
  },
  portfolio: {
    intro: "Global HQ over your competition teams: their numbers side by side, what they share with each other, and where to put effort next.",
    tips: ["<b>Review the portfolio</b> asks the Portfolio Manager for a call on each team; nothing changes until you press a suggestion's button.",
           "Global candidates under <b>Knowledge</b> wait for you: approve one and every team of yours reads it."],
    doc: "portfolio",
    tabs: { Teams: "Every open team's measured numbers, and the Portfolio Manager's latest calls.", Knowledge: "What each notebook entry may reach: the team, the subnet, or every subnet.",
            "Task forces": "Extra specialists who join a team for a goal and a number of days." },
    buttons: { "Review the portfolio": "One model call compares every open team and suggests budgets, focuses and task forces.",
               "Send to the Director": "The team's Director plans with the focus.", "Start the task force": "Adds the members to the team in a Task force squad." },
  },
  knowledge: {
    intro: "The agent company's shared knowledge: every record has a scope, a type, a review state and its evidence. Agents read what's verified in their scopes and contribute candidates; you approve what becomes trusted.",
    tips: ["<b>Review &amp; governance</b> lists what waits: approve the exact version you read, or reject it (rejected records are kept).",
           "A <b>grant</b> on Divisions &amp; projects lets another agent, team or project read a scope; it's yours to give and it's logged.",
           "A record that another <b>contradicts</b> becomes contested, never overwritten: decide it again when you've looked."],
    doc: "knowledge-hub",
    tabs: { Overview: "Ask the hub, the knowledge lifecycle in numbers, what waits for review and the rules.", Knowledge: "Every company record, filtered by type, state, scope and contributor.",
            "Divisions & projects": "The scope tree, what each scope holds and who reads it; grants.", Contributions: "What your agents submitted, and what you published from My Knowledge.",
            "Skills & procedures": "Procedural and technical records.", Experiences: "What happened and what tests showed (experiments too), failures included.",
            Review: "Review and governance: waiting, contested, due for review and reported records; grants and rules.", Graph: "Records and their connections.", Analytics: "Reuse, usefulness, acceptance and activity." },
    buttons: { "Add knowledge": "Write a record with its type, scope and evidence; tick the box to approve it as you add it.", "Review with AI": "One model call: a verdict, reasons, risks and a suggested confidence. Advice only.",
               "Approve this version": "Agents in its scope start reading it. If it changed since you opened it, you're asked to read it again." },
  },
  myknowledge: {
    intro: "Your private knowledge: folders, notes, files, web pages, messages and ideas, connected to each other. Nothing reaches your agents or the company until you choose.",
    tips: ["<b>Capture</b> anything; it lands in the inbox, private. <b>Organize with AI</b> suggests a folder, tags, links and a record to derive.",
           "Sources (files, pages, messages) stay as they were; what you learn from one becomes its own record linked back to it.",
           "<b>Company sharing</b> sends a copy for review in the Knowledge Hub; it isn't company knowledge until you approve it there."],
    doc: "knowledge-hub",
    tabs: { Overview: "Ask My Knowledge, search, the inbox and what waits for you.", Workspace: "The folder tree and what each folder holds; move, share or publish many at once.",
            Sources: "Files and web pages, imports of earlier workspaces and external agents, and adopting what they hold.", Communications: "Slack, Discord and Telegram messages in one inbox.",
            Ideas: "Your ideas from proposed to evaluated, with AI analysis.", Connections: "Typed links between records and their graph.",
            "Company sharing": "Publish records for company review.", "Settings & connectors": "Connectors, visibility, export and the activity log." },
    buttons: { Capture: "A note, an idea, a web page, a text file, a paste or a conversation.", Ask: "An answer from your records, each point citing the record it comes from.",
               Export: "Downloads this workspace as a file another AXoR (or this one) can import.", "Organize with AI": "Suggestions only: tick what to apply.",
               "Sync now": "Reads new messages from the connected Slack channel or one of your bots (read only).",
               "Connect Discord or Telegram": "A bot of yours, read only; its token is encrypted and never shown again.",
               "Read it again": "Reads a stored picture, recording or document once more (after you set a model or a transcription endpoint).",
               "Rebuild the index": "Makes every item's search vector again, with the current embeddings endpoint." },
  },
  company: {
    intro: "Your AI agent company: divisions, projects and dynamic teams of agents with contracts. Agents propose; you approve what matters, and every approval is for one exact action.",
    tips: ["Add a task with the skills it needs, then <b>Propose a team</b>: the team builder picks the smallest team that covers them, and you start it.",
           "<b>Brief them</b> on the Overview: the leadership proposes a project with tasks and a budget for a goal.",
           "An approval runs once: <b>Approve</b>, then <b>Execute</b>. Editing a deliverable after approval stops it from running.",
           "Open an agent under <b>Agents</b> to chat with it in a project's context; what its answer suggests happens only when you press the button."],
    doc: "company",
    tabs: { Overview: "The leadership brief, the organization, what waits for you and the latest activity.", Projects: "Each project's objective, budget, tasks, teams, deliverables and knowledge.",
            Agents: "The directory, and each agent's workspace: chat, instructions, memory, knowledge, tools, files, performance and settings.", Approvals: "Every action that needs you, with its exact parameters, evidence and expiry.",
            Knowledge: "What each team may read: its project's, its division's and the company's.", Audit: "Everything that happened, append-only.", Settings: "The name, the model and which actions may be proposed." },
    buttons: { "Propose a team": "The team builder matches skills, availability and workload; no model call.", "Start the team": "Members report to the lead, the lead writes the deliverable, the evaluator scores it.",
               "Ask for approval": "Binds the request to this version of the deliverable.", "Execute": "Consumes the approval and runs the action once.",
               Compare: "The filtered agents side by side: profile, autonomy, tasks, scores, ratings, workload and tokens.",
               Clone: "A copy of the agent with its contract and configuration, under a new name.",
               "Save as report": "Keeps the chat answer as a file in the project, with its hash.", "Make it a task": "Adds the agent's suggested task to the project." },
  },
  infiagent: {
    intro: "Agents for work that takes hundreds of steps. The task's state lives in files, and each agent's prompt is rebuilt from its thinking record at every step.",
    tips: ["Attach the documents with <b>New task</b>; they go into <b>docs/</b>.", "Pick an agent under <b>Agents</b> to see its thinking record and the window of actions it sees.",
           "<b>Coverage</b> checks that every document was read and noted."],
    doc: "infiagent",
    buttons: { "New task": "Describe the work and attach its documents; the Alpha agent plans it and delegates.", Pause: "Stops after the current step; Resume continues from the checkpoint.",
               "Follow up": "A new run on the same workspace." },
  },
  workforce: {
    intro: "A CEO agent and six teams that take on a mission, plan it, review each other and report back for your approval.",
    tips: ["Give it a mission with <b>New mission</b>: say what you want achieved and by when.", "Plans, proposals and improvements waiting for you show as a count in the sidebar."],
    doc: "workforce",
    tabs: { Missions: "Your missions and their progress.", Org: "The CEO, the teams and who does what.", Memory: "What the workforce has learned and keeps.",
            Scoreboard: "How each agent scores on its work.", Improvement: "Changes the workforce proposes to itself.", Benchmarks: "Fixed tests that track quality over time.",
            Settings: "Models, limits and approvals." },
    buttons: { "New mission": "Describe the outcome you want; the CEO turns it into a plan for you to approve." },
  },
  study: {
    intro: "Two learning tracks, AI Engineer and English C1+, each with a roadmap, topics to tick off, practice drills, a code lab and study tutors.",
    tips: ["Set a goal and how many hours a week you have; the roadmap paces itself.", "<b>Fast track</b> keeps only what matters most."],
    doc: "study",
    tabs: { Roadmap: "Your plan, week by week.", "All topics": "Every topic of the track, to tick off as you go.", Practice: "Drills with instant feedback.",
            Lab: "A Python lab in your browser.", "Fast track": "The shortest path to the goal.", "Full path": "Every topic of the track." },
  },
  profile: {
    intro: "Your AI engineer profile, turned into a resume, a full CV and a personal website you can publish here or deploy to Netlify.",
    tips: ["Fill in the basics first: the resume and website update as you type.", "The profile strength meter says what to add next."],
    doc: "boards-profile",
    tabs: { Profile: "Your details, links, skills, experience and projects.", "Resume & CV": "A one-page resume and a full CV, ready to print or download.",
            Website: "A personal website from the same profile; publish it here or deploy it to Netlify." },
  },
  whiteboard: {
    intro: "Infinite boards with sticky notes, shapes, frames and templates, edited live with others.",
    tips: ["Start from a template, or ask the AI to draft a board from a topic.", "Share a board by username; everyone sees live cursors."],
    doc: "boards-profile",
    buttons: { "New board": "An empty board, or one from a template." },
  },
  wallet: {
    intro: "Your Bittensor wallets, tracked by public address: balances, assets and staking, with Send, Receive, Stake, Unstake and Move signed in your browser wallet.",
    tips: ["AXoR never holds your keys: every transaction is signed in your browser wallet.", "Open a subnet's runbook for its btcli commands."],
    doc: "wallets",
    tabs: { Assets: "TAO and each subnet's alpha, with its share of the wallet.", Staking: "Every position, with stake more, unstake and move on the row.",
            Activity: "Transactions signed here, with block, fee and an explorer link.", Hotkeys: "Registrations, UIDs and top-paid earnings.",
            Terminal: "The real btcli, read-only.", Runbook: "The btcli commands for any subnet." },
    buttons: { "Connect a browser wallet": "Link a browser wallet extension so you can sign transactions here." },
  },
  slack: {
    intro: "Your team's Slack channel inside AXoR: read and post messages and threads, and share subnets, notes and notifications.",
    tips: ["Share a subnet from its details straight into the channel."],
    doc: "files",
    buttons: { "Connect Slack": "Add a bot token and the channel to talk to." },
  },
  drive: {
    intro: "Private and shared files and folders, with sharing, share links and the trash.",
    tips: ["Drag files onto the page to upload them.", "Share by username, or make a link (with an optional password)."],
    doc: "files",
    tabs: { Details: "Size, owner, sharing and links.", Activity: "Who changed what, and when." },
  },
  source: {
    intro: "Your team's GitHub repositories: branches, commits with their CI status, code, pull requests, workflow runs and deployments.",
    tips: ["Connect a token that can see the repositories you want here.", "A red count in the sidebar means a repository's latest CI run failed."],
    doc: "files",
    tabs: { Code: "Browse files on any branch.", Actions: "Workflow runs and their logs.", Commits: "Commits with their CI status.", "Pull requests": "Open and recent pull requests.",
            Branches: "Every branch and how far it is from the default one.", Workflows: "The repository's workflows; run one by hand.", Deployments: "Where each commit was deployed." },
    buttons: { "Connect GitHub": "Add a GitHub token. A fine-grained token limited to the repositories you need is safest." },
  },
  explore: {
    intro: "Every subnet in one table, live from the chain: emission, miners, registration cost, price and risk.",
    tips: ["Tick <b>UID available</b> to see only subnets you can register on right now.", "Press <b>/</b> anywhere to jump to the search box."],
    doc: "explore",
    steps: [{ sel: "#stats", title: "The network at a glance", body: "Headline figures for the whole network, updated every few minutes." },
            { sel: "#q", up: ".search", title: "Search", body: "Search name, task, hardware or software. Press <b>/</b> from anywhere to jump here." },
            { sel: "#f-field", title: "Filters", body: "Narrow by field, hardware and risk. <b>UID available</b> keeps subnets you can register on now; <b>Has earners</b> drops subnets where no miner earns." },
            { sel: "#cols-btn", title: "Columns", body: "Choose which columns the table shows; AXoR remembers your choice." },
            { sel: "#csv-btn", title: "CSV", body: "Download exactly what's filtered, for a spreadsheet." },
            { sel: ".tablewrap", title: "Subnet details", body: "Click a header to sort. Click a row for payouts, the top-paid miners, 7-day charts and <b>Add to workspace</b>." }],
  },
  recommend: {
    intro: "Subnets ranked for your hardware, budget, capital and risk tolerance. Every change re-ranks the list instantly.",
    tips: ["Start from the preset closest to you, then adjust.", "Focus a field to see a suggested value based on live chain data."],
    doc: "first-subnet",
    steps: [{ sel: "#view-recommend .presets", up: ".field", title: "Start from a preset", body: "Four starting points: beginner, gaming GPU, datacenter or developer without a GPU." },
            { sel: "#hw", up: ".field", title: "Your hardware", body: "What you have or will rent. Tick <b>I already own this hardware</b> and rent drops out of the budget." },
            { sel: "[name=budget_usd]", up: ".field", title: "Budget and capital", body: "Your monthly budget for rent, and the TAO you can spend on registration. Focus a slider to see what the network costs right now." },
            { sel: "#risk", up: ".field", title: "Risk tolerance", body: "Low keeps steady, established subnets; high lets in new and winner-take-all ones." },
            { sel: "#weights", title: "What matters to you", body: "How much each of the six factors counts in the match score." },
            { sel: "#rec-list", title: "Your ranking", body: "Each result shows why it fits, what miners do, what you need, a budget with payback, and how to become a top miner." }],
  },
  new: { intro: "Subnets registered in the last four months, newest first. Early subnets can pay well before competition arrives, but carry more rule-change and deregistration risk.",
         tips: ["Click a card for the subnet's details."], doc: "explore",
         steps: [{ sel: "#new-body", title: "New subnets", body: "Newest first. Click a card for its payouts, top miners and trends." }] },
  caution: { intro: "Subnets where you can't profitably get in right now (<b>avoid</b>), or that are workable but hide a specific trap (<b>caution</b>).",
             tips: ["Every flag states the measurement behind it."], doc: "explore",
             steps: [{ sel: "#caution-body", title: "Flags with reasons", body: "Each card says what was measured: closed registration, no UID, dust rewards, slow payback, winner-take-all and more." }] },
  scam: { intro: "Subnets that draw emission while anonymous, abandoned or for sale, or where the owner or one closed-source hotkey captures almost all miner rewards.",
          tips: ["These are automated signals, not a verdict: do your own research."], doc: "explore",
          steps: [{ sel: "#view-scam .notice", title: "Read this first", body: "How a subnet lands here, and why it isn't proof of fraud." },
                  { sel: "#scam-body", title: "The evidence", body: "Each card shows the signals behind it." }] },
  tech: {
    intro: "A daily edition of new technology (AI, software, Android, devices, IoT and security) from the tech press, Hacker News and GitHub.",
    tips: ["Click a story to read it at the source.", "Earlier editions are at the bottom."],
    doc: "tech-daily",
    steps: [{ sel: "#tech .tb-cover", title: "Today's cover", body: "The day's cover line and spotlight story." }],
  },
  agents: {
    intro: "Every agent in one place: the Directory of all agents in every system, each with its profile, chat, versions and runs; create new ones, watch live runs, and browse the shared catalog.",
    tips: ["Open an agent in the Directory for its profile: instructions, skills, tools, memory, evaluations and versions.", "\"Only mine\" in the Directory lists the agents you made; their ⋯ menu edits, duplicates, pauses, publishes or deletes them.",
           "Describe what you want under New agent and AXoR drafts the agent for you."],
    doc: "agents",
    steps: [{ sel: "#hub-nav [data-ops-sec=directory]", title: "Directory", body: "Every agent you can see, from every system. Filter by system, state or Only mine; open one for its profile." },
            { sel: "#hub-nav [data-hub=home]", title: "New agent", body: "Describe an agent in a sentence, or start from a template or a blank one." },
            { sel: "#hub-nav [data-ops-sec=live]", title: "Live runs", body: "What runs now and what failed in the last day; a run opens its execution trace." },
            { sel: "#hub-nav [data-hub=directory]", title: "Shared catalog", body: "Agents people published for everyone. Add one to your agents to chat with it." }],
    buttons: { "New agent": "Make an agent from a description, a template or a blank form.", "Refresh": "Reload every agent's state now." },
  },
  help: {
    intro: "AXoR's documentation: getting started, a guide to every page, administration, the API with a reference of every endpoint, and developer docs.",
    tips: ["Every page's tour links to its guide here."],
    doc: "",
  },
  // ---------- admins ----------
  admin: {
    intro: "Accounts, roles, sign-up and sign-in settings, and the audit log.",
    tips: ["Every change here is in the audit log."], doc: "admin-users",
    steps: [{ sel: "#adm-method", up: ".card", title: "Sign-in method", body: "Username and password, or password plus an authenticator code." },
            { sel: "#adm-q", up: ".toolbar", title: "Users", body: "Search and filter accounts; change a role, disable or reset someone on their row." },
            { sel: "#adm-aq", up: ".toolbar", title: "Audit log", body: "Who did what, from which IP." }],
  },
  hq: {
    intro: "The agents that run AXoR's platform: field agents check services every few minutes and fix what's safe, team leads review fixes, and the Team Boss reports every hour.",
    tips: ["Fixes waiting for you and critical issues show as a count in the sidebar."], doc: "admin-hq",
    tabs: { Overview: "The Boss's latest report and what's happening now.", Issues: "What the field agents found and what they propose.", Reports: "The hourly reports.",
            Roster: "Every agent, its job and its record.", Settings: "How often they patrol and what they may fix alone." },
    buttons: { "Patrol now": "Send the field agents out now instead of waiting for the next round." },
  },
  docker: {
    intro: "This server's legacy Docker containers and images. AXoR itself runs on Kubernetes.",
    tips: ["Prune removes stopped containers and unused images; you confirm first."], doc: "admin-devops",
    steps: [{ sel: "#dk-stats", title: "At a glance", body: "Containers running and stopped, images and disk used." },
            { sel: "#dk-q", up: ".toolbar", title: "Containers", body: "Search by name, image, project or ID; start, stop, restart and read logs on each row." },
            { sel: "#dk-pull", title: "Pull image", body: "Download an image from a registry. Focus the field for examples." }],
  },
  devops: {
    intro: "AXoR's own CI/CD: pipelines that build, test and deploy Source hub repositories, their runs and the deployed apps.",
    tips: ["A pipeline builds a branch's Dockerfile, runs your tests, then deploys if they pass."], doc: "admin-devops",
    tabs: { Runs: "Every build, test and deploy, with logs.", App: "The deployed app: status, address and health.", Settings: "Repository, branch, tests, health check and resources." },
    buttons: { New: "Create a pipeline for a repository. Focus each field for a suggested value." },
  },
  connectors: {
    intro: "Keys (Workforce → Keys): the model providers and outside services your agents use, the keys AXoR holds for them, and your OpenRouter API keys: what each has spent, its credit limit, and whether it's on.",
    tips: ["Give every key a monthly limit so a runaway agent can't overspend."], doc: "admin-agents",
    buttons: { "Connect OpenRouter": "Add an OpenRouter key; AXoR then makes per-purpose keys with their own limits." },
  },
  system: {
    intro: "This server's CPU, memory, swap, disk and load, sampled every few seconds, with charts of the last hour.",
    tips: ["The meter in the top bar shows the same figures from any page."], doc: "admin-operations",
    tabs: { _: "How much history the charts show." },
  },
  cluster: {
    intro: "The Kubernetes cluster AXoR runs on: node capacity, namespaces with their deployments and pods, recent warnings, the platform's domain and HTTPS, and Updates.",
    tips: ["Updates deploys each new commit on main; you can check now, update now or pause it."], doc: "admin-platform",
    tabs: { Workloads: "Namespaces, deployments and pods, with logs.", "Domain & HTTPS": "The platform's domain, console address and certificates.",
            Updates: "The updater: history, log, check now, update now, pause." },
  },
  apps: {
    intro: "Apps on AXoR's Kubernetes platform: status, pods, events, logs and revisions.",
    tips: ["A new app needs an image and the port it listens on; focus each field for a suggested value."], doc: "admin-platform",
    tabs: { Overview: "Status, address, pods and events.", Test: "Send a request to the app.", Logs: "The pods' logs.", Revisions: "Every deploy; roll back to one." },
  },
  functions: {
    intro: "Serverless functions on AXoR's platform: code, test calls, logs, revisions and call statistics.",
    tips: ["Start from a runtime's template, then invoke it from the Invoke tab."], doc: "admin-platform",
    tabs: { Overview: "Status, address and settings.", Code: "Edit the function's code and packages.", Invoke: "Call it with a method, path, headers and body.",
            Logs: "Recent output.", Revisions: "Every deploy; roll back to one.", Stats: "Calls, errors and duration." },
  },
  machines: {
    intro: "Linux and Windows virtual machines on the server's KVM, with their console in the browser.",
    tips: ["A machine's disk size can't change later: pick enough room up front."], doc: "admin-platform",
    tabs: { Console: "The machine's screen and keyboard, in the browser.", Overview: "Status, resources and settings.", Logs: "Boot and hypervisor logs." },
  },
  dns: {
    intro: "The zones AXoR's own name server answers for: records, zone settings, lookups and a delegation check.",
    tips: ["Lower a record's TTL before you change it, so the change spreads fast."], doc: "admin-platform",
    tabs: { Records: "The zone's records; add, edit or import them.", Query: "Look a name up the way resolvers will.", Activity: "Queries answered over time." },
  },
};

// Today plus n days, as a date field wants it (local time).
const guideDate = n => { const d = new Date(Date.now() + n * 864e5); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
// The port an image usually listens on, from its name.
const guidePort = image => {
  const i = String(image || "").toLowerCase();
  for (const [re, p] of [[/nginx|httpd|caddy|apache/, 80], [/grafana|node|next|nuxt|vite/, 3000], [/redis/, 6379], [/postgres/, 5432], [/mysql|mariadb/, 3306],
                         [/mongo/, 27017], [/streamlit/, 8501], [/gradio/, 7860], [/jupyter/, 8888], [/python|gunicorn|uvicorn|fastapi|django|flask/, 8000]])
    if (re.test(i)) return p;
  return null;
};

const GuideFields = [
  // Recommend: what the network costs right now
  { v: "recommend", sel: "[name=budget_usd]", get: (el, c) => {
      const hw = S.profile?.hardware || "cpu", by = { none: [50, 100], cpu: [100, 250], gpu1: [300, 500], gpu2: [800, 1500], gpu3: [3000, 5000] }[hw] || [300];
      return { values: by.map(n => ({ v: String(n), label: `$${n}/mo` })), why: `Typical monthly rent for the hardware you picked (${hw === "gpu1" ? "1 GPU" : hw === "gpu2" ? "pro GPU" : hw === "gpu3" ? "cluster" : hw.toUpperCase()}).` };
    } },
  { v: "recommend", sel: "[name=capital_tao]", get: (el, c) => {
      const costs = (c.data?.subnets || []).filter(r => r.uid_available && r.reg_cost > 0).map(r => r.reg_cost).sort((a, b) => a - b);
      if (!costs.length) return null;
      const med = costs[Math.floor(costs.length / 2)], lo = costs[0], fit = x => String(Math.min(+el.max, Math.ceil(x * 20) / 20));
      return { values: [{ v: fit(med), label: `${fit(med)} τ · median` }, { v: fit(lo), label: `${fit(lo)} τ · cheapest` }],
               why: `Registration costs right now across the ${costs.length} subnets with a UID open.` };
    } },
  { v: "recommend", sel: "[name=min_age_days]", get: () => ({ values: S.profile?.risk === "high" ? ["0"] : S.profile?.risk === "low" ? ["90", "30"] : ["30", "0"],
      why: "Older subnets change their rules less often. Low risk tolerance suits 90 days or more." }) },
  { v: "recommend", sel: "[name=count]", get: () => ({ values: ["8", "12"], why: "Enough to compare without scrolling forever." }) },
  // Explorer filters
  { v: "explore", sel: "#q", get: (el, c) => ({ values: [...new Set([...(S.profile?.fields || []), "4090", "inference", "LLM"])].slice(0, 4), why: "Search matches name, task, hardware and software." }) },
  { v: "explore", sel: "#f-field", get: () => S.profile?.fields?.length ? { values: S.profile.fields.slice(0, 3), why: "The fields you picked in Recommend." } : null },
  { v: "explore", sel: "#f-tier", get: () => S.profile?.hardware && S.profile.hardware !== "none" ? { values: [S.profile.hardware], why: "The hardware you picked in Recommend." } : null },
  { v: "explore", sel: "#f-risk", get: () => ({ values: [{ v: "clear", label: "Clear only" }, { v: "caution", label: "Caution or better" }], why: "New to mining? Start with subnets that carry no flag." }) },
  // Help
  { v: "help", sel: "input[type=search]", get: () => ({ values: ["first subnet", "push", "wallet", "API key"], why: "Common questions." }) },
  // subnet numbers anywhere: the subnets in your workspace first
  { v: "*", sel: "input[placeholder*='netuid' i], input[aria-label='Subnet number'], input[name=netuid]", get: (el, c) => {
      const ws = c.workspace();
      return ws.length ? { values: ws.slice(0, 4).map(n => ({ v: String(n), label: `SN${n}${c.name(n) ? " · " + c.name(n) : ""}` })), why: "Subnets in your workspace." } : null;
    } },
  // apps and functions
  { v: ["apps", "functions"], sel: "[name=name]", get: (el, c) => {
      const img = c.val("image").split("/").pop().split(":")[0].replace(/[^a-z0-9-]/g, "");
      return { values: [...new Set([img, c.view === "apps" ? "web" : "hello", c.view === "apps" ? "api" : "webhook"].filter(Boolean))], why: "Lowercase letters, digits and dashes. It becomes part of the address." };
    } },
  { v: "apps", sel: "[name=image]", get: () => ({ values: ["nginx:1.27-alpine", "ghcr.io/your-org/app:1.0"], why: "Pin a version tag rather than latest, so a redeploy runs the same code." }) },
  { v: ["apps", "devops"], sel: "[name=port]", get: (el, c) => {
      const p = guidePort(c.val("image") || c.val("command"));
      return { values: [...new Set([p, 8080, 8000].filter(Boolean).map(String))], why: p ? `The port ${c.val("image").split(":")[0] || "this image"} usually listens on.` : "The port your app listens on inside the container." };
    } },
  { v: ["apps", "devops"], sel: "[name=health]", get: (el, c) => ({ values: /nginx|httpd|caddy/.test(c.val("image")) ? ["/"] : ["/health", "/"],
      why: "A path that answers 200 once the app is ready; traffic waits for it." }) },
  { v: ["apps", "functions", "devops"], sel: "[name=memory]", get: (el, c) => ({ values: c.view === "functions" ? ["128", "256"] : ["256", "512"],
      why: c.view === "functions" ? "MB. Most handlers fit in 128; data work wants 256 or more." : "MB. A small web app fits in 256; Python with libraries wants 512." }) },
  { v: ["apps", "functions"], sel: "[name=cpu]", get: () => ({ values: ["0.25", "0.5", "1"], why: "Cores. 0.25 is plenty for light traffic; raise it if requests queue." }) },
  { v: "devops", sel: "[name=cpus]", get: () => ({ values: ["0.5", "1"], why: "Cores for the deployed container." }) },
  { v: ["apps", "functions"], sel: "[name=replicas]", get: (el, c) => ({ values: c.view === "apps" ? ["1", "2"] : ["1"], why: "Two copies keep an app up while one restarts or updates." }) },
  { v: ["apps", "functions"], sel: "[name=autoscale_max]", get: () => ({ values: ["3", "0"], why: "The most copies autoscaling may add under load; 0 turns it off." }) },
  { v: "functions", sel: "[name=timeout]", get: () => ({ values: ["30", "60"], why: "Seconds before a call is cut off. Most handlers finish well under 10." }) },
  { v: "functions", sel: "[name=handler]", get: el => el.placeholder ? { values: [el.placeholder], why: "The function the runtime calls, from the template." } : null },
  { v: ["apps", "devops"], sel: "[name=volume]", get: () => ({ values: ["/data"], why: "Where the app keeps files that must survive a restart. Leave it empty if it keeps none." }) },
  // DevOps pipelines
  { v: "devops", sel: "[name=app]", get: (el, c) => { const r = c.val("repo").split("/").pop().toLowerCase().replace(/[^a-z0-9-]/g, "-").replace(/^[^a-z]+/, "").slice(0, 30);
      return r ? { values: [r], why: "Named after the repository." } : null; } },
  { v: "devops", sel: "[name=dockerfile]", get: () => ({ values: ["Dockerfile"], why: "The path from the build context." }) },
  { v: "devops", sel: "[name=test]", get: () => ({ values: ["python -m pytest -q", "npm test", "go test ./..."], why: "A command that exits non-zero when a test fails stops the deploy." }) },
  { v: "devops", sel: "[name=test_timeout]", get: () => ({ values: ["600"], why: "Seconds. Ten minutes covers most test suites." }) },
  { v: "devops", sel: "[name=health_timeout]", get: () => ({ values: ["60", "120"], why: "Seconds the new app gets to answer its health check before the deploy is rolled back." }) },
  // Machines
  { v: "machines", sel: "[name=name]", get: (el, c) => ({ values: /win/.test(c.val("os")) ? ["win-desktop", "win-test"] : ["dev-box", "build-box"], why: "Lowercase letters, digits and dashes. It's also the host name." }) },
  { v: "machines", sel: "[name=cores]", get: (el, c) => ({ values: /win/.test(c.val("os")) ? ["4", "2"] : ["2", "4"], why: /win/.test(c.val("os")) ? "Windows is comfortable with 4 cores." : "2 cores suit a dev box; 4 for builds." }) },
  { v: "machines", sel: "[name=ram]", get: (el, c) => ({ values: /win/.test(c.val("os")) ? ["8", "4"] : ["4", "8"], why: "GB of memory." }) },
  { v: "machines", sel: "[name=disk]", get: (el, c) => ({ values: /win/.test(c.val("os")) ? ["64", "100"] : ["32", "64"], why: "GB. It can't grow later, so leave room." }) },
  { v: "machines", sel: "[name=username]", get: (el, c) => c.me?.username ? { values: [c.me.username.slice(0, 20), "admin"], why: "The Windows account to create." } : null },
  { v: "machines", sel: "select[name=language]", get: el => { const l = navigator.language.slice(0, 2); return [...el.options].some(o => o.value === l) ? { values: [l], why: "Your browser's language." } : null; } },
  // DNS
  { v: "dns", sel: "[name=ttl]", get: (el, c) => c.form?.elements.ns ? { values: ["3600"], why: "Seconds. An hour is the usual default for a zone." }
      : { values: ["300", "3600"], why: "300 s while you're still changing the record; 3600 s once it's settled." } },
  { v: "dns", sel: "[name=name]", get: (el, c) => c.form?.elements.value ? { values: ["@", "www"], why: "@ is the zone itself." } : null },
  { v: "dns", sel: "[name=value]", get: (el, c) => ({
      TXT: { values: ['"v=spf1 mx -all"', '"v=DMARC1; p=none"'], why: "SPF says who may send mail for the zone; DMARC (on _dmarc) what to do with mail that fails." },
      CAA: { values: ['0 issue "letsencrypt.org"'], why: "Only Let's Encrypt may issue certificates for this name." },
      MX: { values: ["10 mail"], why: "Priority, then the mail server's name." } }[c.val("type")] || null) },
  { v: "dns", sel: "[name=email]", get: (el, c) => c.me?.email ? { values: [c.me.email], why: "Where problems with the zone are reported." } : null },
  // Cluster
  { v: "cluster", sel: "[name=public_ip]", get: el => { const ip = (el.placeholder || "").replace(/\s*\(detected\)$/, ""); return ip ? { values: [ip], why: "The address this server was detected on." } : null; } },
  { v: "cluster", sel: "[name=acme_email]", get: (el, c) => c.me?.email ? { values: [c.me.email], why: "Let's Encrypt writes here before a certificate expires." } : null },
  // Connectors
  { v: "connectors", sel: "[name=limit]", get: () => ({ values: ["10", "25"], why: "A credit limit in USD stops a runaway agent from overspending." }) },
  { v: "connectors", sel: "[name=expires]", get: () => ({ values: [{ v: guideDate(90), label: "In 90 days" }], why: "Keys that expire are safer if one leaks." }) },
  // Docker
  { v: "docker", sel: "[name=image]", get: () => ({ values: ["redis:7-alpine", "postgres:16-alpine", "nginx:1.27-alpine"], why: "Pin a version tag; alpine images are smaller." }) },
  // Agents
  { v: "agents", sel: "[name=name]", get: () => ({ values: ["Rhea", "Atlas", "Nova"], why: "A short name you'll recognise in chats." }) },
  { v: "agents", sel: "[name=role]", get: () => ({ values: ["Risk Guardian", "Subnet Scout", "Market Watcher"], why: "What it does, in two or three words." }) },
  // Wallets: names only, never amounts or addresses
  { v: "wallet", sel: "[name=name]", get: (el, c) => c.form?.elements.coldkey ? { values: ["miner", "validator", "savings"], why: "A name for this wallet in AXoR only." } : null },
  { v: "wallet", sel: "[name=hk_name]", get: () => ({ values: ["default", "miner"], why: "The hotkey's name in btcli." }) },
  // Slack, Source, notifications
  { v: "slack", sel: "[name=channel]", get: () => ({ values: ["#mining", "#axor"], why: "The channel's name or ID; invite the bot there first." }) },
  { v: "source", sel: "[name=label]", get: () => ({ values: ["Personal", "Our org"], why: "Tells your tokens apart." }) },
  { v: "notifications", sel: "[name=url]", get: () => ({ values: ["/#dashboard", "/#notifications"], why: "Where a click on the test notification goes." }) },
  { v: "notifications", sel: "[data-ntp-time=quiet_start]", get: () => ({ values: ["22:00", "23:00"], why: "No pushes from this time." }) },
  { v: "notifications", sel: "[data-ntp-time=quiet_end]", get: () => ({ values: ["07:00", "08:00"], why: "Pushes resume at this time." }) },
  { v: "notifications", sel: "select[data-ntp-tz]", get: el => { const tz = Intl.DateTimeFormat().resolvedOptions().timeZone; return [...el.options].some(o => o.value === tz) ? { values: [tz], why: "This device's time zone." } : null; } },
  // Whiteboard
  { v: "whiteboard", sel: "[name=name]", get: () => ({ values: [`Mining plan · ${new Date().toLocaleDateString(undefined, { month: "short", day: "numeric" })}`, "Ideas", "Retro"], why: "You can rename it later." }) },
  // everyone: account details and dates
  { v: "*", sel: "input[type=email]", get: (el, c) => c.me?.email ? { values: [c.me.email], why: "Your account's email." } : null },
  { v: "*", sel: "[name=branch], [name=ref]", get: el => {
      const list = el.list ? [...el.list.options].map(o => o.value).filter(Boolean) : [];
      return { values: [...new Set([...list.filter(b => b === "main" || b === "master"), ...list.slice(0, 2), "main"])].slice(0, 3), why: "The branch to use." };
    } },
  { v: "*", sel: "input[type=date][name=due]", get: () => ({ values: [{ v: guideDate(7), label: "In a week" }, { v: guideDate(14), label: "In two weeks" }], why: "When it should be done." }) },
  { v: "*", sel: "input[type=date][name=starts]", get: () => ({ values: [{ v: guideDate(0), label: "Today" }], why: "" }) },
  { v: "*", sel: "input[type=date][name=ends]", get: (el, c) => ({ values: [{ v: guideDate(14), label: "In two weeks" }, { v: guideDate(30), label: "In a month" }], why: "" }) },
];
