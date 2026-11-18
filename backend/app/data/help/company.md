---
title: Company
section: guide
order: 4
icon: layers
summary: Your AI agent company. Divisions, projects, dynamic teams of agents with contracts, an independent evaluator, approvals bound to exact actions, shared knowledge with scopes, and an append-only audit log.
---
[Company](#company) (in the sidebar, under Portfolio) runs an AI agent company with you as the founder. It's one organization: divisions own projects, projects have tasks, and each task gets a team of agents. Agents propose and do the work; you approve what matters.

It starts with three divisions and 31 agents:

- **Bittensor Division**: its first project is **My subnets** itself. It's a link, not a copy: your campaigns and [competition teams](#help/mining) keep running where they are, and the project shows their numbers live.
- **Handshake Division**: protocol research, core engineering, testing, security and the ecosystem.
- **Future Projects Division**: new products and research, from templates.
- **Leadership**: the CEO, COO, CTO, CFO, Research Director and Governance agents. They advise and never join a team.
- **Shared specialists**: code review, databases, security review, data analysis, documentation, web research, and the **Independent Evaluator**. Any division's teams can use them.

Add more divisions under **Overview → Organization** and more agents under **Agents → Register an agent**.

## Overview

- **Brief the leadership**: write a goal. The leadership board (one model call) answers as the CEO (why it matters), COO (the project), CTO (the approach), CFO (a token budget) and Governance (the approvals it will need and its risks), with up to five tasks. **Create this project** makes it, tasks included.
- **Organization**: the company, its divisions and their projects, and the shared services. Click a project to open it.
- **Waiting for you** and **Latest activity**.

## Projects and teams

A project has an objective, success criteria, a status and a **token budget**. Every call its teams make counts against the budget. A team stops when the budget runs out.

Add a **task** and tick the **skills** it needs. **Propose a team** runs the team builder. It doesn't call a model. It takes the available agents of the project's division plus the shared specialists, skips anyone at their workload limit, and picks the smallest team that covers the skills, using each agent's proficiency (1-5). The division's project manager leads it. An **Independent Evaluator** who isn't on the team is assigned to score the work. The proposal shows why each member is there and any skill nobody available covers. You can choose the team type:

- **Dynamic team**: released when the task ends (the usual).
- **Task force**: the same, for urgent work.
- **Permanent team**: stays together after the task.

**Start the team** begins the run. Each member reports to the lead in stage order: research, design, engineering, testing, then review. A report is one model call and one structured message: its type, a summary, the work itself, evidence, confidence, risk and the next action. The lead then writes the **deliverable**, which is kept with its SHA-256 hash. The evaluator scores it: 0-100, pass, revise or fail, its strengths and issues, and whether its claims rest on evidence. **Show the work** opens all of it.

A team only reads its own project's knowledge, its division's and the company's. It never reads another project's knowledge or anything restricted.

## Approvals

When the lead proposes an action that needs you, an approval request is created, unless the evaluator failed the work. You can also ask for one on any deliverable with **Ask for approval**. Each request shows:

- the exact action and its parameters
- what it's bound to: the deliverable's hash and the parameters' hash
- the evaluation, the expected result and the rollback plan
- when it expires (72 hours)

**Approve**, **Ask for changes** or **Reject** (the last two need a reason). Then **Execute**. The server checks that the approval is approved, unexpired and unused, that the deliverable and the parameters still hash to what you reviewed, and that the company's policy still allows the action. It then uses up the approval and records the execution in one step. An approval runs once, and there's no "approve all".

What executing does:

- **Release a deliverable**: marks it the project's official result.
- **Share knowledge more widely**: moves an item, or a task's lessons, to the division or the company.
- **Change an agent's permissions**: applies the new contract as a new version.
- **Production changes, deploys, external messages, financial and blockchain actions**: handed to you. AXoR holds no credentials for them and production execution is off, so the card gives you the exact approved payload to carry out yourself.

Editing a deliverable after an approval changes its hash, so that approval can't run any more.

## Agents

**Agents** opens the directory. Search by name, role or skill, and filter by group (leadership, a division, shared), status, skill, project and model profile. Sort by score, tasks, workload or this month's tokens. **Compare** shows them side by side in a table. **Register an agent** adds a new one.

Each agent is a persistent identity, whatever teams it joins. Click one to open its **workspace**. Every agent has the same workspace, and its contract decides which tabs it gets: leadership agents never join teams, so they have no Tasks or Workflows tab. The header shows its status, role, model profile and autonomy, with tasks done, success rate, tokens this month and chat answers. **Pause**, **Resume**, **Clone** and **Archive** are there too. An archived agent leaves the directory and joins no team, but keeps its history; **Restore** brings it back.

- **Overview**: its current mission, the projects it works on and why, how it runs (model, autonomy, tools) and its recent activity.
- **Chat**: talk to the agent directly. A conversation is about one project, or about the company as a whole, and keeps that context. The agent reads the company's knowledge, its division's and that project's, its own memory for that context, and the files you reference from the project. It never reads another project's knowledge or anything restricted. You can attach text files too. Each answer shows the agent's plan and what it read, with tokens and time. **Stop** ends an answer that's still coming.
- **What an answer suggests**: chat runs nothing. If an answer suggests something, it appears as a button, and nothing happens until you press it:
  - **Save as report** or **Save as code draft**: keeps the answer as a file in the project, with its SHA-256.
  - **Remember**: keeps a note in the agent's memory.
  - **Make it a task**: adds a task for the team builder.
  - **Ask for approval**: saves the answer and makes an approval request bound to it, like a team lead's.
  - **Send**: hands the answer to another agent working on the same project.

  Rate any answer helpful or not.
- **Instructions**: its current mission and standing instructions. They go into every call it makes, in chat and on teams. They don't widen its contract.
- **Tasks**: the tasks it worked on as a team member, by state: running, assigned, blocked (failed), completed.
- **Memory**: its notes, kept per project or for every context, and what it reported on its teams.
- **Knowledge**: everything it may read, by company, division and project, with a count of what it can't read.
- **Skills**: proficiency 1-5. **Test** opens Chat with a question that exercises the skill. You can change skills, writes, executes and teams at once here: that's its **contract**.
- **Tools**: its chat tools (read knowledge, keep memory, save files, suggest tasks, propose actions, hand off). Switch one off and the agent isn't offered it and the server refuses it. This tab also shows its contract permissions and restrictions. Execute permissions are described in its work, never run: there's no sandbox runner.
- **Files**: deliverables it wrote as a team lead and answers you saved from chat. You can ask for approval on one from here.
- **Workflows**: the teams it was on and its role in each, and the work it evaluated.
- **Performance**: tasks, deliverables led, average score and pass rate from the independent evaluator, chat answers, answer time, ratings, tokens per week and by model. These are tokens, not money: AXoR doesn't price models.
- **Activity**: its answers, what you applied, errors, configuration and status changes, and its audit entries.
- **Settings**:
  - **Model profile**: Standard, Fast (low effort), Advanced reasoning (high effort), Coding specialist, or Local model (the local server's first model). You can also set a model of its own.
  - **Autonomy**: **Advisory only** means every suggestion waits for you and it proposes no actions. **Managed execution** means it keeps its own memory notes and may propose actions for approval. Bounded sandbox autonomy isn't available.
  - **Monthly token budget**: at the cap, its calls stop, in chat and on teams.
  - **Project assignments**: lets an agent work on a project outside its division.
  - **Versions**: its configuration and contract versions.

Contract changes and configuration changes are kept apart. A contract change (skills, permissions, workload) is a new contract version. Agents can't change any contract, their own included. A configuration change (mission, instructions, model, autonomy, budget, tools) is a new configuration version and goes into the audit log. It doesn't touch the contract, so pending permission-change approvals stay valid.

## Knowledge

Lessons from finished tasks go to their project's knowledge. You can add items too. Mark one **restricted** to keep it out of every prompt and stop it ever being shared. Sharing with the division or the company is an approval request, so nothing private spreads by itself.

## Audit and settings

**Audit** lists everything that happened, whether you, an agent or AXoR did it. It's append-only: nothing changes or removes an entry. **Settings** has the company's name, its model ("auto" uses the server's default), and which actions agents may propose at all. Switching an action off also stops already-approved requests for it from running.
