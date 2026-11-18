---
title: Agent directory and operations
section: guide
order: 3
icon: radio
summary: Every agent AXoR has in one place. What runs now and what failed, the approval queue and token use, an execution trace for any run, and an Agent Studio per agent where you can edit, test, compare and restore your own agents.
---
The operations side of [Agents](#agents) (sidebar → Agents: Directory, Operations, Live runs, Connected systems, Ecosystem in the page's rail) shows every agent you can see in one place: your own agents, the built-in ones, the [Company](#help/company), [Workforce](#help/workforce), [Competition teams](#help/mining) and, for administrators, the Workflow's engineers and [Agent HQ](#help/admin-hq). It doesn't copy any of them. Each agent stays in its own system, with that system's rules and approvals, and every row leads to the page that manages it.

## Overview

- **Agents, Working, In review, Needs attention, Approvals, Tokens · 7 days**. A card opens the section behind it.
- **Agents by system**: how many agents each system has, and how many are working now.
- **Needs attention**: agents whose last day had a failed run or that wait on a review, plus recent failures.
- **Approval queue**: the same list as the [Approval Center](#approvals). Decisions are made on each request's own page.
- **Token use**: the last 7 days by system, from the agent core's run ledger (below). AXoR keeps no price list, so costs aren't shown.
- **Daily budget**: what your agents used today across every system, and your daily limit. Leave it empty for no limit (the default). When today's use reaches it, agent work in every system (Workforce missions, Company teams, Competition teams, the project team, Long tasks, Mission OS, the Upgrade Factory) stops before its next model call, until midnight or until you raise the limit. Each stops the way it stops on any model error: a Workforce mission fails, a long task pauses, a team's task fails and can be retried. Chats count toward the limit but aren't stopped. Agent HQ has its own hourly budget.
- **Recent activity** across the systems.

## The agent core

Under the pages, every agent system shares one core (`agent_core.py`), while keeping its own process and its own page:

- **One registry.** Every agent of every system, under one key such as `workforce:12` or `teams:5`, with its owner and status. Each system keeps creating and changing its agents as before; the core mirrors them when Agent Operations is opened, at most every five minutes.
- **One run ledger.** Every run of every system, written as it happens: owner, agent, kind, status and the tokens of each model call made during it. The Workflow's runs on the host carry their dollar cost instead. Live operations, token use, the directory's "working" state, the Overview page's spend and "At work now", and the Ecosystem's token count all read it.
- **One budget**: the daily limit above.

The ledger starts with the 30 days before it existed, copied from the older usage log, which most systems wrote to but not all. From then on it holds every model call. It keeps 120 days.

## Live operations

What runs now, what failed in the last 24 hours, and what waits for your approval. Click a run to open its **execution trace**: each step in order with its input, output, tokens and timing. For Workforce and Competition teams these are the recorded model and tool spans. For a Company task they are the messages and handoffs between its agents. For Agent HQ they are a patrol round's events, and for a chat its tool calls. Runs of the other systems (the project team, Long tasks, Mission OS, the Upgrade Factory, the Portfolio Manager) open their ledger row: what ran, when, on which model and how many tokens. Retries happen where the run lives (Workforce retries assignments, Competition teams send tasks back).

## Directory and the Agent Studio

Filter the directory by system and state, or search by name, role or team. An agent opens in the **Agent Studio** with nine tabs: Overview, Instructions, Skills, Tools, Memory, Tasks, Evaluations, Versions and Activity. Each tab shows what that system keeps for the agent.

**Evaluations** works out the success rate, first-attempt success, average latency and tokens per successful run from the agent's runs. Where runs record a version (Workforce, the Workflow), it also shows a by-version table that flags a **regression** when the success rate drops more than 5 points against the previous version over at least 3 finished runs.

### Your own agents

Only the agents you made in [Agents](#agents) are changed here. The others are changed on their own pages, where their approval rules apply.

- **Instructions**: edit the instructions and **Test** the draft on one message before you save. A test uses the agent's read-only tools, remembers nothing and keeps only its result (under Evaluations). Its tokens count like a chat's.
- **Skills**: tick up to 10 skills.
- **Versions**: every save, here or in Agents, becomes a version. Tick two to see the changed lines and **Run both** on the same message, side by side. **Restore** makes an old version current again as a new version, so nothing is lost.

## Connected

Where the rest of the agent workspace already lives: orchestration (Workforce missions), teams and squads (Company, Competition teams), workflows and tasks (Missions & tasks), evaluations and benchmarks ([Agent evaluation](#evaluation)), recommendations and experiments (Workforce Improvements), approvals, permissions and audit (Approval Center), and knowledge (Portfolio).

## Ecosystem

AXoR as one AI ecosystem in eight layers (mission interface, mission intelligence, agent workforce, model intelligence, knowledge, execution, verification and evolution, governance), each with this week's figures from the systems doing that work and a link to them. **Interoperability** says where AXoR stands on MCP, A2A and agent identity. **External agents** keeps A2A Agent Cards you paste, for discovery only: AXoR never fetches a card or calls the agent, and each entry stays untrusted until you mark it reviewed.
