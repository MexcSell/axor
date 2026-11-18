---
title: Portfolio
section: guide
order: 4
icon: target
summary: Global HQ over your competition teams. See their numbers side by side, control what they learn from each other, ask the Portfolio Manager where effort should go, and send in task forces.
---
[Portfolio](#portfolio) (in the sidebar, under Competition teams) sits above your [competition teams](#help/mining). Each team works on its own competition. The portfolio looks across all of them: which team has the most to gain, which one spends without results, and what one team learned that another could use.

Nothing on this page changes a team by itself. Every suggestion has its own button.

## Teams

Each open team gets a card with its measured numbers:

- **Standing**: the campaign's standing and rank, from My subnets' latest brief.
- **Eval**: what the Lab measured. This is how many eval tasks the base solves, plus the tasks whose changes gained or lost against their base. It shows only for teams with a Workflow and a scored check.
- **Done** and **Failed runs**: tasks done and runs failed in the last 7 days.
- **Tokens**: tokens in 7 days, and per done task.
- **Sandbox**: dollars of inference in sandbox runs, 7 days.
- **Emissions**, **Ends**: the competition's share of the subnet's emissions, and the days left.
- **Knowledge**: lessons the team shared (↑) and lessons it reads from your other teams (↓).

The numbers aren't combined into one score. The competition's own score comes first. Cost, failures and time left are constraints beside it.

**Review the portfolio** asks the **Portfolio Manager** to read every card. This is one model call; you can add a note to steer it. It answers with:

- a call for each team: **invest**, **optimize**, **investigate**, **hold** or **pause**, with the reason in the numbers;
- a **focus**: what the team's Director should aim the next plan at. **Send to the Director** starts a plan with it;
- a suggested **daily token budget**. **Budget … → …** applies it;
- where spend runs ahead of results;
- up to two **task forces**. **Start it** brings one in.

The review spends model tokens; they count in your My subnets usage. Nothing reviews on a schedule: it runs only when you ask.

## Knowledge: what teams share

Every approved notebook entry has a scope, in three tiers:

| Tier | Scope | Who reads it |
|---|---|---|
| 1, the team's own | **Private** | Only its own team (the default) |
| | **Restricted** | Only its own team, ever: scoring internals, the evaluator's tasks and their answers, your own plans |
| 2, the subnet | **Shared on the subnet** | Your other teams on the same subnet (SN62's 28 reads what 29 learned) |
| 3, every subnet | **Global candidate** | Shared on its subnet while it waits for you |
| | **Shared everywhere** | Every team of yours, on every subnet |

Other teams never read the raw entry. They read its **lesson**: the finding restated to stand on its own, without task names or answers. Each agent's prompt lists the few lessons most relevant to its team. Lessons only ever come from your own teams.

The **Knowledge Manager** classifies new entries within a minute or two of their approval. This is a short model call per batch, on the team's model and inside its daily budget; it shows in the team's runs. It shares an entry only when it's sure. Otherwise the entry stays private, with its suggestion and an **Accept** button. Anything tied to particular evaluator tasks stays restricted, because Ridges screens agents for hard-coded task knowledge.

You can change any entry's scope, edit or write its lesson, and turn the Knowledge Manager off. Global candidates wait under **Waiting for you**, and their count shows in the sidebar. **Share everywhere** approves one; **Keep it on the subnet** turns it down. Entries approved more than a week before sharing started aren't classified on their own. **Classify now** on them reads them, and from then on older entries are classified like new ones.

## Task forces

A task force is a few extra specialists who join a team for a goal and a number of days. You can start one from a review, or by hand under **Task forces → New task force**. The members are Competition Researcher, Miner Engineer, Benchmark Specialist, Experiment Designer, Optimization Strategist or Competition Analyst.

- They join the team's **Task force** squad. The first member leads it and reviews the others' work. The Director plans their work straight away.
- A team has one task force at a time, and the team's 45-agent limit counts them.
- When the days are up, or when you press **Dissolve now**, the members switch off once they finish the task at hand. Their findings stay in the notebook, and their unstarted tasks go to the Director. They stay on the team, switched off, with their history.
- **Keep them for good** makes them permanent members of the team.
