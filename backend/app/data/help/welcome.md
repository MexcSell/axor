---
title: Welcome to AXoR
section: start
order: 1
icon: rocket
summary: What AXoR does, a tour of the sidebar, and what to do in your first ten minutes.
---
AXoR reads every Bittensor subnet straight from the chain, works out what miners actually earn, and ranks subnets against your hardware, budget and skills. Around that core it gives you a workspace to plan your mining, AI agents that help you research and build, a study path, wallets, files and a daily board of new technology.

## The sidebar

The sidebar on the left holds every page, in groups. At the top is the AXoR logo. Click a group's name to fold it away (AXoR remembers which ones you folded, and a folded group still shows its alert count). The pin beside the logo keeps the sidebar open; unpin it to fold the sidebar to icons. On a phone it slides out from the menu button.

Under the logo, **Progress** follows work from what the company wants to what it achieved, in five numbered stages. Click a stage to open its first page and list the others; the stage of the page you're on is filled in. They're the same pages the groups below hold, so what your role and Simple mode let you open still decides what you see.

| Stage | Pages | The question it answers |
|---|---|---|
| **1 Goal** | Missions, Competition objectives (Control Hub → Missions), Projects | What does the company want, by when, with what budget? |
| **2 Work** | Task board, Team boards, Live operations, Agents | What's being done for it right now? |
| **3 Evidence** | Release & benchmarks (Competition teams → Status), Performance lab, Agent evaluation, Evolution Lab | What shows it worked: the frozen release candidate, benchmarks run on the same suite, tested changes |
| **4 Approval** | Approval Center (with its count), Contracts & approvals, Findings to share | What waits for your decision? |
| **5 Result** | Verified results (the Control Hub figure), Miner performance, Rewards & costs, Analytics | What was achieved and checked, not just run? |

| Section | Pages | What they're for |
|---|---|---|
| **Control Hub** | Control Hub, Notifications, Approval Center | What's happening across AXoR right now, and everything that waits for your decision |
| **Missions** | Mission Control, Missions & Tasks, Projects, Portfolio | Give AXoR a goal, every task on one board, every project and the shared portfolio |
| **Organization** | Company Overview (Organization HQ), Company OS, and the tree of your organization's departments, teams and agents | Who works for you and how they are organized |
| **Workforce** | Agents, Keys, Workforce, Agent Marketplace, Agent HQ, Long tasks, Evolution Lab, Learning, Benchmarks & evaluations | Every agent in one directory (profile, chat, versions, runs), the model providers, API keys and connectors they use (Keys, administrators), agents to import, and how they get better with measured evidence |
| **Knowledge** | Knowledge Hub, My Knowledge | What AXoR knows, shared and private |
| **Intelligence** | Market Intelligence, Technology Research (Tech Daily), Recommendations, New Subnets, Analytics, Avoid & Caution, Scam Signals | The market, new technology, a subnet ranking made for you, cost per result, and the subnets to stay away from |
| **Ecosystems** | Bittensor: My Subnets, Competition Teams, Bittensor Research, Subnet Explorer, Mining HQ | The subnets you mine and their competition teams, research, every subnet with live numbers, and the mining command center |
| **Workspace** | Workspace home, My workspace, File manager (Drive), Whiteboard, Source control, Slack, Study, My profile | Your shortlist of subnets, files, boards, team tools and learning |
| **System** | Governance, Infrastructure, Developer, Administration, Help & docs, Sidebar layout, then **Developer** (administrators) as the sidebar's last item | What AXoR may do by itself; for administrators the server, cluster, machines and DNS; Docker, DevOps, apps and functions; users, wallets, settings, appearance and the audit log; and which sidebar items show in Simple mode and for users |

Live operations, Performance lab, Experiments, Miner performance and Rewards & costs are on [My subnets](#mining)'s own rail; Ctrl+K finds them too.

**Knowledge, Intelligence and Learning** are three different things in AXoR. *Knowledge* is what AXoR knows: subnet data, the market, research, documents and lessons from earlier missions, which agents retrieve and use; the **Knowledge** section of the sidebar is where you read it. *Intelligence* is what AXoR does with what it knows: analysing it, finding opportunities and recommending a strategy (in a mission, the Intelligence Analyst's brief). *Learning* is how agents get better from results: a mission's lessons, practice and improvement trials; [Learning](#learning) under Agents shows them all, and lets you forget a mission lesson that's wrong. On a mission they come in that order: Knowledge retrieves the rules, code and earlier experiments, Intelligence analyses them and recommends a plan, and Learning keeps what worked for the next one.

The foot of the sidebar shows AXoR's version and whether AXoR is healthy: the chain, and the services that are set up (a service that isn't set up doesn't count against it). The status bar along the bottom shows AXoR's version, the same health, and how many agents, projects and pending approvals you have; administrators also see the server's CPU, memory and disk there.

Some pages only show once you're signed in, and a group whose pages your role can't open stays hidden. Press [[Ctrl]]+[[K]] (on a Mac [[⌘]]+[[K]]) to jump to any page or subnet by typing part of its name. **Help & docs** at the end of the System section brings you back here.

The sidebar's very last item, **Developer** (administrators only), is a development page with files, an editor, terminals on the server and Claude Code: see [Developer](#help/developer). Administrators can change the sidebar itself in **Sidebar layout**, just above it (it stays visible with System folded and in Simple mode). It has three lists: **Advanced**, the whole sidebar, which administrators see in Advanced mode; **Simple**, what administrators see in Simple mode; and **User**, the only sidebar of every account that isn't an administrator. Those accounts have one mode, with no Simple/Advanced switch, and don't see Progress, the status bar, the version and health at the foot of the sidebar, or the chain, TAO price and unit in the top bar; with no User list saved they get the Simple list. Drag items from Advanced into Simple or User (or use their **+ Simple** / **+ User** buttons), drag or use the arrows to reorder, add headings, and use the eye to show or hide an entry. **Preview** shows a list in your own sidebar before you save. A list only arranges the sidebar: it never opens a page to an account that can't use it, and a hidden page can still be reached with Ctrl+K or its link. A saved list is drawn as one list under your headings; **Default** goes back to the built-in sidebar, with its folding sections.

## The top bar

- The top bar starts with the page you're on (with the sidebar folded or on a narrower screen, its section too). [[Ctrl]]+[[K]] opens search, which jumps to any page, My subnets screen or subnet. With nothing typed it lists the pages you visited last first.
- **Live** shows the chain block AXoR last read and how long ago. Subnet data refreshes every few minutes and open pages update on their own.
- **τ** is the TAO price, and the **τ / $** switch shows earnings in TAO or US dollars everywhere.
- The **bell** holds your notifications ([Dashboard and notifications](#help/dashboard)).
- **Assist** opens an agent beside the page you're on ([Agents and Assist](#help/agents)).
- The **theme** button picks light, dark or system, and an accent color.
- Your **avatar** and name open the account menu: your profile, password, two-factor, recovery codes and sign-out.

## Your first ten minutes

1. **Secure your account.** Save your recovery codes somewhere safe and check that two-factor is on. See [Your account and security](#help/account).
2. **Look around the [Explorer](#explore).** Every subnet is a row. Click one for its details and 7-day charts.
3. **Get a ranking that fits you.** Open [Recommendations](#recommend), pick a preset or tell it your hardware and budget, and the list re-ranks as you change things.
4. **Shortlist a subnet.** Add one to your workspace from its details or its recommendation card. Its mining brief tells you the task, the budget and how to become a top miner. See [Find a subnet to mine](#help/first-subnet).
5. **Check the risks.** Before you commit, read [Avoid & Caution](#caution) and [Scam Signals](#scam).

> [!TIP]
> Press [[/]] on any page to jump to the Explorer's search. Links such as `#sn64` or `#recommend` open a subnet or a page directly, so you can share them.

## Where to go next

- [Find a subnet to mine](#help/first-subnet): from the first look to a registered miner.
- [Tips and shortcuts](#help/shortcuts): keys, deep links and settings that follow you.
- The [User guide](#help) covers every page in detail.

> [!NOTE]
> Mining returns change every epoch. AXoR's estimates come from recent on-chain data and typical hardware prices. They are not financial advice and not a guarantee of earnings.
