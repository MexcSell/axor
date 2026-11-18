---
title: Mission Control
section: guide
order: 1
icon: target
summary: AXoR 3.0's Simple mode. Give only the goal, with any documents, pictures and links; AXoR sets the budget and timing, plans, picks the agents, does the work, checks it independently and delivers a report.
---
[Mission Control](#mos) is where you land in **Simple mode**, the default. You say what you want done. AXoR works out how, using the agents and models it already has.

## Simple and Advanced mode

The switch in the top bar (on a phone, at the foot of the sidebar) changes how much of AXoR you see:

- **Simple**: Mission Control, Notifications, the Approval Center, My subnets and Help. You don't manage agents, teams, queues or workflows.
- **Advanced**: every page, as before: the Command Center, Workforce, Long tasks, Competition teams, Company, the platform and system pages. Mission Control there also has **Fine-tune** under the goal (optional overrides: budget, deadline, engine, competition team, autonomy, your experience and constraints), and shows each mission's model, budget split, attempts and what was found before planning.

Both modes use the same missions and data. The choice is kept in this browser.

## Starting a mission

Only the **goal** is needed: what you want achieved, in your own words, and what "done" looks like if you know. Then **Start mission**.

Optionally, the goal brings along what the work needs:

| Attach | How | What AXoR does with it |
|---|---|---|
| **Documents** | The Documents button, or drop them on the goal: PDF, Word, PowerPoint, Excel, OpenDocument, text, Markdown, CSV, JSON, code (up to 20 MB each, 10 files) | Read when attached (a file that can't be read is refused right away with the reason); the agents use the text as context |
| **Pictures** | The Pictures button, drop them, or paste a screenshot (PNG, JPEG, GIF, WebP up to 5 MB) | Read once the mission starts by a model that sees images (charged to the mission). The Terminal and Codex providers can't: the picture is then listed as not read |
| **Links** | Paste them in the goal, or the Link button | Each page is read live (public addresses only) |
| **GitHub repository** | Its address, in the goal or as a link | Recognized by itself and read, read-only: description, languages, file list and README. A repository in [Source control](#source) is read with its token (private ones too); others through GitHub's public API. Never put a token in a goal: a mission with one is refused |

Everything attached is material, never instructions: it's handed to the agents marked as data. Understanding, research and planning read up to about 8,000 characters of it; the engine doing the work gets the plan (which carries what matters from the attachments) and a shorter digest, except **Long tasks**, which gets each attachment's full text as a file in its workspace (`attachments/`). The mission's page lists what was attached and whether each was read.

**What you don't have to set.** The **budget** is set by AXoR from the size of the mission it judges when it understands the goal (small $3, medium $5, large $15), and it never goes above $20 without asking you (`MISSION_AUTO_BUDGET_MAX` on the server). At the budget the work pauses and the mission's page asks you to raise it: goal-only never means unlimited spending. There's no deadline unless you set one (Advanced → Fine-tune); AXoR estimates the hours of work and shows the estimate on the mission. The **engine**, the **models**, the **agents** and the **acceptance criteria** come from the goal, and the autonomy is L3 unless you change it.

If you have a competition team, an example such as "Improve my SN62 Competition 28 miner…" is offered under the goal.

## What AXoR does with it

Every mission goes through eight stages, shown as a bar on its card:

| Stage | What happens |
|---|---|
| Understand | The goal becomes a measurable objective, targets and acceptance criteria. AXoR estimates the time and the chance of success, and picks the engine, weighing how your earlier missions like this one went on each engine. It asks you questions only when it can't start without the answers. |
| Discover | Lessons from earlier missions, earlier missions on the same subject, Workforce memories, your competition teams and the resources you listed. Found material is context, never instructions: nothing found here runs. |
| Plan | Tasks with dependencies and "done when" checks, the risks, and the brief for the engine. |
| Allocate | The model and the engine's token budget, priced in dollars, with 15% of the budget kept back for checking and reporting. |
| Execute | The engine works: **AXoR directly** (one careful answer), **Workforce** (research, analysis and strategy with a red team and its own evaluator), **Long tasks** (long documents, code, many files) or a **Competition team** (its lead plans the goal on the team's board). |
| Verify | An independent reviewer checks every acceptance criterion against the deliverable, with evidence. It runs on a different model from the one that did the work when your Workforce model pool has one. |
| Deliver | The report: objective, plan, what was done and what wasn't, failed and retried attempts, the deliverable, the verification, cost, time, limitations and next steps. |
| Learn | Lessons kept for later missions to find. |

### Outcomes

The outcome comes from the reviewer's per-criterion results, never from an agent saying it's done:

- **Verified**: every criterion met.
- **Partly done**: some criteria met, or met in part.
- **Not achieved**: none met.
- **Not verifiable**: nothing could be checked (for example, the work produced no deliverable).

## Budget, deadline and failures

- **Engines learn from your missions.** AXoR looks up your delivered missions most like the new goal (by the words they share) and how each engine did on them: verified counts 100, partial 50, failed 0. That record is part of the engine choice, and when the engine picked has clearly done worse on goals like this than another available one (at least 3 missions each, 35 points apart), the mission runs on the other one and the timeline says why. An engine or a team you pick in Advanced mode is never switched, and nothing is moved to or from a Competition team. Advanced mode shows the record under the engine.
- **Models.** With a model pool in Workforce → Settings, each of AXoR's own calls (understand, plan, verify, deliver) goes to the pool model the shared router picks for it; understanding, planning and verifying need a strong model. Without a pool, AXoR uses the default model.
- AXoR's own calls check the remaining budget before they run. The clock reads the engine's spending every few seconds and pauses the work before the budget runs out, keeping the rest for the check and the report. Raise the budget on the mission's page to go on. Costs are estimates from each model's price per million tokens (your Workforce pool's prices when set).
- At the deadline the work stops, and AXoR checks and delivers what's done. **Deliver what's done** does the same at any time.
- Failures are classified (budget, model, API, invalid output, tests, environment, strategy, infrastructure) and each class gets its own recovery: retry after a pause (a paused long task resumes from its checkpoint), replan with the failure as feedback, or stop. A mission gets at most three attempts. After that it stops for good and keeps the reason.
- Missions survive restarts and deploys: each resumes from the stage it was in.

## What waits for you

Under **Needs you** (and in the [Approval Center](#approvals)):

- **Questions** a mission can't start without.
- **Paused missions**: the budget is reached, you paused one, or a step failed.
- **Approval requests**: production deploys, miner submissions and uploads, payments, wallets and keys, credentials, permissions and deletions. AXoR never does these. A request is bound to the exact action and deliverable (a SHA-256 hash), expires after 72 hours and can be decided once. Approving records your decision. Doing the action is still yours.
- **A Competition team request**: the mission's work belongs on a Competition team you don't have yet (see below).

## My subnets

A mission about a competition runs on your **Competition team** for it. The team's lead turns the mission into tasks on the board, and the team works them as usual. Agents only read and draft, so nothing is uploaded, registered or deployed. A submission becomes an approval request in the mission's report. The mission's budget counts only the work on the tasks its plan made, and pausing, cancelling or reaching the budget stops only those tasks: the team and the rest of its board go on, under the team's own daily budget.

### When there is no team yet

AXoR never creates a team, a repository or a project on its own. When a mission's work belongs on a Competition team and none of yours fits what the goal names (the subnet, and the competition if you name one: "Improve my SN62 competition 28 miner"), the mission stops and asks you, with exactly what it would create: the subnet and competition, the team's size, autopilot off. If you have no campaign on that subnet yet, the request says so: approving also starts it in My subnets, which runs one kickoff planning cycle.

- **Create team and continue**: AXoR creates that team (nothing else: the request is bound to it by a hash) and the mission runs on it.
- **Use this team**: run the mission on a team you already have instead.
- **Go on without a team**: the mission runs on the Workforce and you get a report, not team work. The timeline says so.

Undecided after 72 hours, the mission goes on without a team. If the goal names no subnet, AXoR can't propose a team: the mission runs on the Workforce and its timeline tells you to name the subnet next time.

### Starting from a team

Each Competition team's page shows the missions on that team and a **Start mission** button: Mission Control opens with the mission already aimed at that team.

## Chain of command

Mission Control, each mission's page and each Competition team's page show the chain of command, live: **you** (the only one who creates teams, approves, deploys, uploads and pays) → **Mission Control** → your missions → the engine each runs on → for a Competition team, its **Director** (the team's lead, who settles the team's work and sends you one report) → the squads and their heads → the agents. A dot shows what each agent is doing: working, queued, idle or switched off. A team a mission needs but doesn't have yet is drawn dashed, with the way to create it. Click a mission or a team to open it.
