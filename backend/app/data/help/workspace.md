---
title: Workspace and the project team
section: guide
order: 3
icon: pickaxe
summary: Your shortlist and mining briefs, notes and the PDCA board, files, workspace agents and the project team.
---
## Overview

**Overview**, at the top of the workspace's sidebar, is one page for everything your agents do and everything that waits for you. Its count is how many things wait for you.

| Part | What it shows |
|---|---|
| **Needs you** | Everything waiting for you, worst first, each with a button that opens it: a Competition team's blockers and the Director's questions, Workflow plans, reviews and failures, the project team's decisions, My subnets' actions and critical alerts, Workforce plans and improvements, and Agent HQ fixes (administrators) |
| **At work now** | Every agent run going on right now, whichever system started it |
| **Competition teams** | Each open team's state (working, stuck, waiting, idle), tasks done, the last 7 days, agents at work, today's tokens against its budget and the Workflow's step |
| **Your miners** | My subnets' latest brief per campaign: best rank, what it earns a day and how far it is from your goal |
| **Project team** | The latest cycle on each subnet and the decisions it waits on |
| **Spend** | Your model tokens today, over 7 and 30 days, by source, and what the Workflow cost on the host |
| **Latest activity** | The newest events from the teams, the Workflow and the project team |

It refreshes every 20 seconds while it's open. It only reads: nothing on it starts work or spends tokens until you press a button and act on the page it opens.

## Your shortlist

[My workspace](#workspace) holds the subnets you're considering. Add one from a subnet's details, a recommendation card or the workspace's own picker.

Each subnet opens a **mining brief**:

| Part | What it tells you |
|---|---|
| **Task** | What the subnet wants and what you'd do |
| **Budget** | Hardware rent, inference or API spend, registration, running cost, first-month total, realistic newcomer earnings, net a month and break-even; set the hardware you own to adjust it |
| **Low-cost plan** | How to keep costs down |
| **Top-miner plan** | How to reach the top, with score targets from the current leaderboard |
| **Competition** | Earners, reward concentration, operators and newcomers in the top 15, registration pressure, the top paid miners |
| **News** | The subnet's GitHub releases (or recent commits) and on-chain changes |

## Notes

Notes are private sticky notes in light Markdown: clickable checklists, bold, italic, strike, highlight, headings, lists, code, links and SN mentions, with a formatting toolbar and **Beautify**, which tidies bullets, checkboxes, numbering, headings and spacing.

- A note belongs to one subnet or is general (shown with every subnet). Pick any color, resize it, pin it.
- **PDCA** is a board you drag notes through: Plan, Do, Check, Act.
- **Daily** is one note per day that carries over the items you didn't check.

## Files

The workspace's **Files** panel lists the Shared drive and your own drive. Uploads from the workspace and from agent chats go to *Shared drive › Workspace*. See [Drive, Source and Slack](#help/files).

## Agents in the workspace

Add agents to the workspace, select one and chat with it about the open subnet. Chats are kept per agent and subnet. **Ask an agent** on any subnet's details adds the subnet if needed and opens that chat. Workspace chats have `/new`, `/brief` and `/news` commands.

## The project team

**Add project team** creates seven senior engineers who build a miner or validator with you, one per stage of the work:

| Agent | Role |
|---|---|
| **Paige** | Engineering manager: the plan, targets, decision rules, go / no-go |
| **Sol** | Source engineer: the subnet's repository, docs and sample tasks, kept pinned and free of secrets |
| **Kai** | Simulation engineer: the local simulation, the subnet's local runner, later registration and submission steps |
| **Tessa** | Evaluation engineer: runs scored like validators, the decision rule, the release gate |
| **Vera** | Competition analyst: the leader, scoring and participation rules, published miners for ideas |
| **Devon** | Miner engineer: improves the miner one measured change at a time |
| **Iris** | Benchmark engineer: practice tasks beyond the samples |

### Running a PDCA cycle

On a subnet's **Team** tab the team runs a Plan-Do-Check-Act cycle on its own: Paige plans 3 to 6 tasks, teammates work through them as their hand-offs finish (two at a time), Tessa scores the work and sends weak tasks back once, and Paige writes a report with the next goal. You watch it live: phases, each agent's status, the tasks with their outputs, an activity feed and a token meter. Cycles can repeat daily or weekly.

### What waits for you

The team stops only for what you decide. Those items wait in the **Reports** tab:

- the **plan**, unless you untick *I approve the plan*
- raising the **token budget** when the team reaches 80% of it
- what agents escalate: funding (hardware rent, registration τ, paid APIs), access, scope changes and serious risks

Approve or reject each with an optional note, or several at once. A note is always acted on: on a plan, Paige applies it; on a rejected request, the agent gets a follow-up task that does what the note says. You can **edit** a plan, a budget raise or a request before deciding.

> [!NOTE]
> Agents can't spend money or change permissions. Approved funding and access requests become follow-up tasks in which the agent spells out the steps for you to take.

**Reset project** deletes every cycle on the subnet with its tasks, reports and schedule; the agents stay.
