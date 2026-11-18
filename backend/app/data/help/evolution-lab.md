---
title: Evolution Lab, Analytics and Governance
section: guide
order: 5
icon: cycle
summary: AXoR 5.0's self-evolution loop. Find weak spots, propose a change, test it against the current version on the same benchmark cases with a blind judge, and promote it only when the numbers show it's better. Analytics measures cost per validated deliverable; Governance sets what AXoR may do by itself.
---
AXoR 5.0 adds an **Evolution Engine**. Earlier versions adapt to a mission. The Evolution Engine improves the things that make the next missions succeed: agents, skills, teams, workflows and the organization itself. It runs under your governance and needs evidence for every change.

## The loop

The [Evolution Lab](#evolution) follows one cycle:

| Step | What happens |
|---|---|
| **Observe** | Signals are weak spots backed by evidence. They come from the run ledger (repeated failures, low scores), chat ratings (thumbs-down) and failed Studio tests, all from the last 14 days. |
| **Propose** | A proposal describes a change and why it should help. You can write one, or let a model draft one for one of your agents (**Draft a fix**). A draft is only a proposal: it proves nothing. |
| **Experiment** | The current version and the candidate both answer the same **benchmark** cases on the same model. They run in a sandbox: tools are read-only and no memory is written. |
| **Evaluate** | An independent judge scores each answer from 0 to 100 against the case's rubric. The judge is blind: it doesn't know which version wrote the answer. |
| **Promote** | A change is promoted only once it is **verified**: scored on at least the policy's minimum number of cases, with an average at least the policy's margin above the current version, no more cases lost than won, and no failed answers. |
| **Version & rollback** | Every promotion keeps the version it replaced. **Roll back** restores that version in one click. |

AXoR never treats an improvement as real just because a model says so. **Promote** refuses anything that isn't verified. It also refuses a change whose agent was edited after the experiment, because the evidence measured a different configuration. Run the experiment again in that case.

## What changes where

- **Your own agents** (from [Agents](#agents)): instructions and skills count as configuration, the low-risk class. They are tested, promoted and versioned right here. The versions are the same ones Agent operations shows.
- **Anything else**: an agent of another system, a team, a department, a skill, a tool, a model, a strategy, a workflow or the organization. You propose the change here and **record evidence** measured elsewhere (one score per case for each version, in the same order). The same rule decides whether it's verified. Promoting it records your decision, and you apply the change on its own page.
- **Code changes and external actions** always need you. No policy promotes them.

The **Agents** tab shows each agent as a versioned capability package: core, model, skills, tools, memory, knowledge, evaluation and policies, plus its version history and the changes made to it. The **Other loops** tab lists improvements from the systems that run their own: Workforce, the Competition teams' Workflow and upgrade sprints. Each row opens the page where those changes are decided.

## Competition team agents

A proposal for an agent of one of your Competition teams carries the agent's complete new instructions. It isn't tested by the blind judge. It goes on **trial**:

1. The Owner turns experiments on for the team. Without that, no trial starts and nothing is promoted.
2. **Start trial** puts the candidate instructions on the agent. The team needs a frozen release first.
3. The team works, freezes the candidate it made during the trial on the same benchmark suite, and benchmarks it.
4. **End trial** puts the earlier instructions back, whatever the numbers say. The evidence is read from the team's benchmark jobs: scores the job's own output file gave, the release frozen before the trial against the one frozen during it.

A person promotes a verified trial. The policy never promotes a team agent, and numbers typed in by hand don't count for one. Trial evidence is technical. It is never a competition result.

This is the only way a Competition team's agent is promoted. The team's **Upgrade** sprint scores its exam with a model, so it screens candidates: **Send to trial** there makes a proposal here, marked *screened by an upgrade sprint*, and the sprint itself changes nothing in the team.

## Gaps a mission measured

A persistent team mission evaluates its measures in cycles. When a cycle decides **Correct** (an external measure fell away from its target, or it stalled while the team's own runs failed), it records the gap as a proposal here, under the team's account. The card says **Measured gap**.

- A gap says what was measured. It doesn't say what to change, and it is never tested or promoted itself.
- **Answer** makes a proposal for one of that team's agents, with the agent's complete new instructions. The answer goes on trial like any other team-agent proposal.
- One gap stays open per mission and measure. Later cycles that measure the same gap are added to it.
- The gap shows **Answered** when one of its answers is promoted. It opens again if that promotion is rolled back.
- Answered doesn't mean the measure improved. The mission's later cycles show that, and they name the gap, its answer and the versions before and after.

The Owner follows a gap from the mission's page: the cycle that recorded it names the proposal.

## Benchmarks

A benchmark is the fixed test set both versions answer: realistic requests, each with a rubric that says what a good answer contains. **Draft cases** has a model write more cases. Review them before you rely on them. Keep a benchmark fixed while you compare versions. A drafted proposal uses the agent's newest benchmark; to pick another, use the benchmark button on the proposal's card.

## Analytics

[Analytics](#analytics) leads with **cost per successfully validated deliverable**: every ledger token in the period, divided by the deliverables that something other than their author checked. That covers runs an evaluator or verifier scored 70 or more, and missions whose independent reviewer found every criterion met. Wasted work raises the number. AXoR should lower it over time without spending more tokens or adding more agents.

A Competition team's board task that was approved in review does **not** count as a validated deliverable. A review is a verdict, not a score of the work: the run is recorded as **Reviewed, unmeasured**, and no number is written for it. The same holds when the task is sent back or its reviewer rejects it. Runs scored before this rule keep their score, so a period that spans the date the rule started mixes both; the page shows that date.

Every score AXoR shows is one of two kinds, and neither is a measurement:

- **Model-judged**: a model evaluator or verifier scored the output (the Workforce reviewer, the Swarm's evaluator, Mission Control's independent check, the company evaluator, an experiment's blind judge).
- **Derived**: a fixed number for a decision or a status (a Control task you accepted, a merged Workflow task, the share of a plan's tasks that were delivered).

**Measured** values are a persistent mission's measures: a chain sample under an attested key, a designated evaluator's report, or a benchmark score read from a job's own output. Each comes with its source, time, method, benchmark version and evidence reference, or it reads **UNKNOWN** with the reason. The team's **Performance** tab in Mission Operations prints which kind every figure is.

The Owner also sees **Your first targets** on this page: five targets, each *met*, *not met* or *no data*, with what it was read from. A target with nothing behind it is never met.

The **Generation 5 scorecard** reports eight measurements, each with the evidence behind it: mission completion, agent improvement, knowledge transfer, team formation, cost, recovery, evolution and governance. A measurement with nothing behind it says **No data**. It never shows a made-up score. Analytics also breaks the period down by system and by agent.

## Governance

[Governance](#governance) puts the controls in one place:

- **Evolution Engine policy**. *Observe and recommend* (the default) lists signals and proposals, and runs experiments only when you start them. *Experiment in the sandbox* also runs queued experiments on its own, within its daily token limit, and never promotes. *Auto-promote low-risk configuration* also promotes verified configuration changes to your agents; you can roll each one back, and an agent at L0 Observe always waits for you. You also set the margin and the minimum number of cases here.
- **Daily token limit** across every agent system. Model calls stop when it's used up.
- **Autonomy levels**: AXoR 5.0's five levels mapped onto the organization's execution levels L0–L4. The organization's levels are the ones enforced. Raising an agent to L3 or more waits for your approval.
- **Always yours**: production deployment, external commitments, budget changes, destructive operations and strategy.
- **Waiting for you**, **Rollback points**, the **Rules in force** and the merged **Audit trail** of the Evolution Engine and the Organization.
