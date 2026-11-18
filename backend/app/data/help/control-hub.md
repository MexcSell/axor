---
title: Control Hub
section: guide
order: 4
icon: dash
summary: Run AXoR as one organization from one place. The sidebar's tree goes Organization → Departments → Teams → Agents; a subnet is a department and a competition is a team. The hub covers missions, agents, teams, resources, approvals, alerts, performance and audit. Fixed tasks aim for a top 1–10 miner rank, dynamic tasks go where they can run, and every agent has its own workspace.
---
The [Control Hub](#control) is where you see and run the whole organization. It replaced the Command Center as the overview; the old page is still there under **Agent operations → Command Center (classic)**.

## The scene

The Control Hub opens on the **scene**: AXoR as a command room, with the AXoR core in the middle and the systems it runs around it. Every number in it is live, and everything in it opens something:

- **The rail** (Control Hub, Missions, Agent Topology, Knowledge Hub, Intelligence, Governance) and **the hexagons around the core** open those pages. A hexagon you don't have access to stays dimmed and does nothing. The core opens the Agent Topology.
- **Mission health**: the share of your active missions (Bittensor competitions and custom missions; paused ones left out) whose objective is on track or met. The dots are those missions, colored by health. The line is agent run success per day over the last 7 days. With no active mission, the ring shows agent run success over 24 hours, and the caption says so.
- **Company status**: agent run success over 24 hours, how many agents are working now, and tokens used today (against the daily limit when there is one).
- **Next actions**: the top three decisions waiting, from the same queue as Mission operations, then approvals and alerts. A mission whose tasks are blocked by readiness, or an open critical risk, comes first and opens the Dashboard's **Mission readiness** card, where you decide it. The bar shows how urgent each one is.
- **Missions** (the bottom band): every task of every engine, counted in its state on the path Planned → Ready → Running → Review → Verified.

**Dashboard** (top right of the scene) switches to the cards of the Command Center, with Live operations, Notifications and the Approval Center. The ✦ button there brings the scene back. The choice is remembered on this device. On a wide screen the sidebar folds to icons while the scene shows; unfold it with **[** or its pin, and it stays unfolded.

## One hierarchy

The sidebar's **Organization** tree has four levels, and each one has a single job:

| Level | Responsibility |
|---|---|
| **Organization** | Global policies, resources, governance and strategy |
| **Department** | A business domain, or a Bittensor subnet |
| **Team** | A competition, or an operational mission |
| **Agent** | One agent's execution capability |

Bittensor maps directly onto it. **Department = subnet** (the My subnets campaigns you run on that subnet). **Team = competition** (a Competition team, with its own board, files, sandbox and budget). **Agents** = that team's workforce, plus any specialists you assigned to it. This mapping is the same in the tree, in fixed-task setup, in monitoring and in reporting.

Every other top unit of your organization is also a department: a business division such as Handshake, a shared department such as Engineering, or Executive staff. The teams inside a department are its teams. People placed in a department but in no team show up as **Department staff**.

An agent isn't locked to one team. **Assign** an agent to a team and it serves that team too, while keeping its home and manager. How many teams it can serve depends on its capacity, which is set in [Organization HQ](#help/organization).

### Using the tree

- Click the chevron to fold or unfold a level. Click a name to open it here. The arrow keys move through the tree, and ← / → fold and unfold.
- The dot next to a name shows its status: green is active, accent is working now, amber means something failed lately, red means the last run failed, and grey means idle or off.
- Open **⋯** (or right-click a name) for that node's actions. On a team you can add an agent, get recommendations, add a task, configure the fixed task or open the board. On a department you can make a new team, rename it or dissolve it. On a subnet you can add a new competition team.

## What each level shows

- **Organization**: the leadership, the Bittensor subnets and every department.
- **Department**: its teams. A subnet department also lists its chain competitions (its campaigns).
- **Team**: its agents (the Director or lead first, assigned specialists marked), its fixed task, its dynamic tasks, its board and its history.
- **Agent**: the agent's workspace (see below).

## The hub

With no node selected, the Control Hub shows one source of operational truth:

- **Overview**: departments, what needs you, fixed-task targets, who is at work, dynamic tasks.
- **Missions**: fixed tasks, dynamic tasks, open work on team boards, and Mission Control.
- **Agent operations**: running and failed runs.
- **Team operations**: agents, work and tokens for each team.
- **Resources**: tokens today against your daily limit, by system, and each Competition team's budget.
- **Approvals**: organization requests, which you decide here, and everything else waiting in the [Approval Center](#approvals).
- **Monitoring & alerts**: failures, structural issues, budgets close to their limit, and open My subnets alerts.
- **Performance**: rank against the target, plus the best and weakest agent scores.
- **Audit**: who changed what.

## Fixed and dynamic tasks

**Fixed tasks** are persistent. A Competition team holds one objective for as long as it exists: reach a top 1–10 miner rank on its competition and stay there. The team is the organizational entity; its objective and its execution are separate records. That means the team stays put while individual runs finish or get replaced.

Set one up with **New fixed task**, in seven steps:

1. **Subnet**: pick it from the chain's list, or type its number.
2. **Discover**: AXoR reads the subnet's chain competitions (its mechanisms and their emission shares) and its named competitions (Ridges' on SN62, approved competition imports, and teams you already have).
3. **Select**: pick the competition, or name it yourself.
4. **Configure**: target rank (top 1–10), objectives, constraints, execution requirements, a daily token budget and a deadline.
5. **Workforce**: the team's own agents (the pack that fits, the default five, or none), specialists from your organization, and up to two picks from AXoR.
6. **Validate**: AXoR checks the subnet, the campaign, duplicates, your budget, the sandbox, the model provider and agent capacity. A stop blocks activation; a warning doesn't.
7. **Activate**: AXoR makes the My subnets campaign if there isn't one, opens the Competition team, and starts controlled execution under the team's budget governor. Clicking Activate is your approval.

On a team, **Rank now** and the gap come from the campaign's latest brief. Add your miner's hotkey in My subnets so it can be tracked. **Top miner plan** opens the team's own plan.

**Dynamic tasks** are flexible. You can create, change, delegate and send them back. Each one goes where it can actually run:

- to a **Competition team's board**, where its own agents work with their tools and sandbox;
- as a single **agent's own run**, which waits for your review (accept it, send it back with a note, or delegate it);
- or to **Mission Control**, as a budgeted mission.

Choose **Automatic** for the agent and the route, and AXoR decides both.

## Hybrid management

The switch at the top right sets how much AXoR does on its own:

- **Manual**: AXoR only recommends; you make every change.
- **Hybrid** (the default): AXoR assigns tasks to agents itself. Staffing a team waits for your approval: one request per agent, which you decide here or in the Approval Center.
- **Auto**: AXoR also staffs teams itself, within each agent's capacity.

In every mode, budgets, authority raises and activating a fixed task stay your decision.

**Recommend agents** rates each candidate on seven factors: capability (skills against the need), performance, availability, model and tool compatibility, cost, reliability and collaboration. Each candidate gets the reasons and the tokens a day they're expected to use. A cost marked * is an estimate, because the agent has no finished runs in the last 30 days.

## The agent workspace

Select an agent to open its workspace: **Conversation**, **Execution** (its tasks, board work and runs), **Knowledge** (its team objective, fixed task, notebook and memory) and **Profile**.

Each agent keeps one conversation, whatever system it lives in. In the message box you can:

- type, or speak with the microphone (your browser turns speech into text);
- **record** your voice, which the server transcribes, and turn on **Read answers aloud**;
- attach a **picture**, take one with your **camera**, or attach a **video**: the agent sees four frames from it, and its sound is transcribed if the file is 25 MB or smaller;
- add a Drive or Source file with **+**;
- turn on **Web search**, so the agent reads the top results and you see the sources under its answer;
- add context with the chips: the team brief, the fixed task and the agent's own tasks.

When an agent proposes a task in the chat, it runs only after you click **Approve and run**.

Some features depend on what's set up:

- Pictures need a model that can see images (Anthropic, OpenAI, OpenRouter or a local server). The Terminal and Codex providers can't.
- Transcription uses the same endpoint as Knowledge: an OpenAI key in Agents → Models, or `KNOWLEDGE_TRANSCRIBE_URL` on the server.
- Web search uses an MCP search server (Exa's public one unless `CONTROL_SEARCH_MCP` names another; `off` turns it off).

## Where things still live

The Control Hub reads and changes the same records as the other pages, so they always agree. Structure, reporting lines, authority and policies are in [Organization HQ](#help/organization). A team's board, files and squads are on its Competition teams page. Campaigns, miners and keys are in [My subnets](#help/mining). Missions are in [Mission Control](#help/mission-control).
