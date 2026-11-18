---
title: Workforce
section: guide
order: 4
icon: group
summary: A company of AI agents that runs missions for you: a CEO plans, leads delegate, specialists work, a red teamer and an independent evaluator check the work, and the workforce remembers, routes and improves itself.
---
[Workforce](#workforce) is a company of AI agents. You give it a mission, a goal in a sentence or two, and it organises the work the way a good team would. The CEO plans and staffs only the teams the goal needs. Team leads split the work, and specialists do it with read-only tools. A red teamer challenges the claims, a fact checker re-checks the important ones, and an independent evaluator scores everything before you read the report.

Workforce is for everyone who can use [agents](#help/agents): administrators, and members when an administrator turns on **Members can use agents**. Missions spend the same model credits as agent chats.

## The org

| Who | Role |
|---|---|
| **Atlas**, CEO | Plans each mission, staffs the teams it needs, writes the report and lists the decisions only you can take. |
| **Research**: Nora (lead), Milo (Market Researcher), Priya (Technical Researcher) | Facts: subnets, markets, competition, your repositories. |
| **Engineering**: Kenji (lead), Lena (Software Engineer), Arjun (ML Engineer) | Designs for miners, validators, services and pipelines, with the tests that prove them. |
| **Strategy**: Imani (lead), Jonas (Planner), Zara (Economist) | Plans, sequencing, costs, earnings and payback. |
| **Operations**: Omar (lead), Bea (Site Reliability Engineer), Luca (Release Manager) | Runbooks, monitoring, releases. For administrators, they can read AXoR's own pipelines and app logs. |
| **Security**: Ines (lead), Viktor (Risk Auditor), Rook (Red Teamer) | Risk audits. Rook challenges every mission's work before it's scored. |
| **Evaluation**: Wren (Chief Evaluator), Faye (Fact Checker), Ivo (Improvement Engineer) | Wren scores all work and never does any. Faye verifies findings, and Ivo proposes better instructions for agents whose work failed. |

The **Org** tab shows everyone live: who is working, on what, and how their work has scored. Open an agent to:

- **Pause or resume them.** The CEO and the Chief Evaluator run every mission, so they can't be paused.
- **Grant tools.** An agent can only get tools its team may use, and every call is checked against its grant, whatever the model asks for.
- **Edit their instructions.** Every change is saved as a new version, and you can restore any earlier version. The versions table shows how each one scored.

**Hire a specialist** adds your own agent to a team, up to 40 agents in all. Its lead can give it work from the next mission on.

## A mission

Choose **New mission** and describe the goal. Optionally add:

- **Success criteria**: one per line. Without them, the CEO writes checkable ones.
- **Subnets**: up to three, for context. Their details and mining brief go to every agent as a fact sheet.
- **A token budget**: 40,000 to 300,000 tokens.
- **Switches**: approve the plan first, red-team review, fact check, rework failures, memory, debate (off unless you turn it on).
- **Who works on it**: the workforce, or **one agent alone**. One agent alone is a baseline: Atlas with every tool does the whole mission, and the same evaluator scores it.

The mission page follows every step live:

1. **Recall**: the memories that match the goal (see *Memory* below).
2. **Plan**: Atlas writes the objective, the success criteria and the work items, each for one team, with what it depends on. With **Approve the plan first** on, the mission waits for you here. You can:
   - **Approve** it.
   - **Edit** it: change, add or remove work items, then approve.
   - **Send it back with a note**: Atlas plans again with your feedback, at most twice.
   - **Reject** it, which closes the mission.

   A plan nobody decides on closes after 24 hours. A waiting plan survives a server restart.
3. **Delegate**: each team's lead splits its items into assignments for their people, each with a *done when* check.
4. **Execute**: assignments run as the items they depend on finish, three at a time. Each specialist sees only its assignment, the summaries of the work it depends on, its team's memories and the fact sheet. Its tools are read-only lookups, the **blackboard** (what teammates found so far) and **propose action**. It files a deliverable, a summary and findings: claims with their evidence and confidence, plus risks and open questions. Findings go on the blackboard.
5. **Red team**: Rook challenges claims without evidence, numbers that don't add up and missing failure modes. Each challenge is major or minor. The author of each major challenge revises the work or rebuts it with evidence.
6. **Fact check**: Faye re-checks up to six of the most important findings with her own lookups: verified, disputed or can't verify.
7. **Debate** (only with **Debate** on): the authors settle what their deliverables disagree on, as peers, with no lead in between.
   - Atlas names up to two disagreements that would change what you do, such as different numbers for the same thing or opposite recommendations, without taking a side.
   - The two or three authors involved argue for up to two rounds. In each round they all speak at once, each seeing the others' positions and what they said last round. Each one **holds**, **amends** their position, or **agrees** with another side.
   - The debate closes on what was said, not on anyone's ruling. It's a **consensus** when every side ends on one side's position, and a **split** otherwise. A split goes into the report's **Decisions for you**, with each position side by side.
   - Wren weighs the outcome when she scores, and Atlas reports it. Deliverables stay as they were filed.

   A debate takes about 16,000 tokens, so it's skipped when the budget can't cover it. Use a budget of 150,000 or more. The **Debate** card on the mission page shows every round, and each turn links to its trace.
8. **Evaluate**: Wren scores each assignment against its task and *done when* check:
   - pass or fail;
   - a score out of 100;
   - for a failure, its category and a note on what to fix.

   She then scores the mission against each success criterion. When your model pool has more than one model, she runs on a different model from the authors. Failed work gets **one rework round** with her note, and only that work is scored again.
9. **Report**: Atlas writes the headline and report, the decisions only you can take, and a suggested next mission. **Start it** runs that next mission.
10. **Learn**: the memory engine stores what the mission taught.

**Cancel** stops a mission after the call it's on. **Run again** repeats a finished mission with its criteria. Every run's trace is in **Runs**: open one to see which model it used and why, each model call and tool call with its input and output, and any tool call that was refused.

### Proposed actions

Agents never change anything. When something needs doing, such as spending money, keys or access, a deploy, deleting or posting, the agent files a **proposal**. AXoR's policy rates its risk from what the action does, whatever the agent claimed: money, keys, access and deletions are high; changes to running systems and anything that speaks for you are medium. The proposal waits for you:

- **Approve** it, and it becomes your task: AXoR never carries it out.
- **Reject** it with a reason, which the workforce reads.

Every decision goes to the audit log. Proposals from every mission are listed under **N proposals wait for you**.

## Memory

The **Memory** tab holds four kinds of memory:

- **Facts**, stored only from findings the fact checker verified.
- **Procedures**: ways of working that produced passing work.
- **Strategies**: what worked, and under which conditions.
- **Episodes**: one record per mission, written from its numbers.

Each mission's blackboard is its working memory.

- **Recall**: a mission retrieves up to eight memories that share the most telling words with its goal, preferring useful and recent ones, with at most two episodes. Atlas sees them all; a specialist sees its team's.
- **Used, not just recalled**: agents cite the memories they rely on. Each memory shows how often it was recalled, used, and used in passing missions. **Lift** is the average score of missions that used it, minus your overall average.
- **Learning**: near-duplicates merge, and a memory a newer one contradicts is superseded. Past 400 active memories, the least useful are archived.
- **Teach the workforce** adds a fact, procedure or strategy of your own. You can archive, restore or delete any memory.

## Scoreboard

The **Scoreboard** shows:

- missions passed, with a 95% interval;
- the average score, tokens per success and time per mission;
- each mission's score and why first attempts failed;
- tables per agent, team and model.

The agent and team tables have these columns:

- **Pass@1**: the share of work that passed on the first attempt.
- **Recovery**: the share of failed work that passed after rework.
- **Utility**: passed assignments per 100,000 tokens.
- **Efficiency**: verified findings per lookup.
- **p95 time**.

An agent whose newest version scores ten points below the version before it is flagged as a regression.

## Improvement

When work still fails after rework, Ivo looks for the root cause in the agent's instructions and proposes a new version. **Test it** checks the proposal:

1. The failed assignment runs again with the current version and with the new one: same model, same inputs, and nothing written to the mission.
2. Wren scores every output blind.
3. A candidate counts as **better** when it averages at least five points more and passes at least as often.

Only a better candidate can be promoted, and only by you. It runs from the next mission on, and the old version stays restorable in Org. In **Settings**, self-improvement can be off, **propose** (the default: you start each test) or **propose and test** (one trial right away).

## Benchmarks

A benchmark asks whether the workforce earns its tokens. It re-runs a finished mission's goal and criteria in two to four arms, up to three trials each:

- the full workforce;
- one agent alone;
- no red team or fact check;
- no memory;
- one fixed model instead of the router;
- with a debate. Only this arm debates, so compare it with the full workforce to see whether debate pays for its tokens. It needs a mission that ran on 150,000 tokens or more.

Arms take turns, so changing data hits each arm alike. Memory writes are off, and one evaluator model scores every run. Each arm shows its pass rate with a 95% interval, its score and spread, tokens per success and median time. One trial per arm is a hint; three start to show the spread.

## Settings

**Model pool and router.** Add the models your workforce may use. Each gets a tier (1 light, 2 strong, 3 frontier) and a price per million tokens. Both are guessed from the model's name; you can override them.

For every call, the router picks the model with the best score for that kind of task. Four things count:

- **Quality**: the evaluator's average score for that model on that kind of task, or the tier's starting value until there are scores.
- **Cost**: the expected cost of a call.
- **Latency**: how long a call takes.
- **Failure rate**: how often its calls fail.

**Quality first**, **Balanced** and **Thrifty** set how much cost and speed count against quality. Planning, red-teaming, evaluating and the report need tier 2 or above. With **Independent evaluator** on, the evaluator and the red teamer use a different model from the work they review whenever the pool has one.

The settings page shows what the router would pick right now for each kind of task, and why. Each run's trace keeps its own decision. With no pool, everything runs on one model: the one you pick, or the default.

**The pool is shared.** The same pool and weights route every agent system that's set to **Auto**: Mission OS (each stage of a mission), the Company (team work and leadership briefs), Competition teams (tasks, reviews and the lead's plans), subnets in My subnets (each of the analyst, tracker, strategist and captain), the project team (the manager's plan, the check and the report on one model per cycle, the tasks on their own) and Long tasks (the agents and the thinking module). Each system learns from its own runs, separately for each kind of work. Quality comes from the scores its work earns: the evaluator's here, the share of acceptance criteria a mission met, a Competition team reviewer's verdict (approve, revise or pass on), and the project team tester's verdicts and score. subnets in My subnets learn from cost, time and failures. Planning, reviewing, verifying and briefs need tier 2 or above there too. A model picked for a company, a campaign, an agent or a task always runs as picked, and models whose provider isn't connected are skipped. Chats aren't routed: they run on the model you pick in the composer.

**Mission defaults** pre-fill the new-mission form.

The sidebar's count shows plans, proposals and promotable improvements waiting for you.
