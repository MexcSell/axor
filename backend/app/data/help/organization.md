---
title: Organization HQ
section: guide
order: 5
icon: branch
summary: One organization over your Company, Workforce, Competition teams and own agents. Executive Office, business divisions, shared departments, the agent directory, team and squad assignments, knowledge, and governance with authority and budgets.
---
[Organization HQ](#org) (sidebar → Agents → Organization) puts every agent you run into one company. Your [Company](#help/company), [Workforce](#help/workforce), Competition teams and your own agents keep running as they do. Organization HQ reads them and keeps its own records, so nothing changes in how they work.

Five principles hold it together:

1. **One company, many divisions.**
2. **One permanent identity per agent, many scoped assignments.**
3. **Shared specialist departments, not duplicated agents.**
4. **Autonomous execution inside the authority you grant.**
5. **Learning and promotion from real, finished work.**

## The structure

You (owner · chairman) → the **CEO** (Atlas, who also owns [Mission Control](#mos)) → three groups:

- **Executive Office.** One company-wide portfolio per executive: CTO, CRO, COO, CFO, CSO, CSecO. Portfolios start from the Company leadership's own roles. Cyrus is the Company's CTO Agent, so he is the CTO. Ezra (Research Director) is the CRO, Brook the COO, Dana the CFO and Fern (Governance) the CSecO. Ada stays Chief of Staff and holds Strategy. Change any of them in **Executive Office**: each portfolio has one holder.
- **Business divisions** (Bittensor, Handshake, Future Projects). Each has a **general manager** (Gus, Noor, Tess), a **leadership** team (Hana · Mining Research Lead, Teo · Engineering Lead, Juno · Evaluation & Performance Lead…) and, for Bittensor, the **Competition teams**.
- **Shared departments**, the company-wide service layer: Research & Intelligence, Software Engineering, Data & Evaluation, AI & Model Intelligence, Security & Compliance, Quality Assurance, Infrastructure & DevOps, Knowledge Management. Each has an **executive sponsor**. The sponsor is a dashed line on the chart (oversight), not a new manager: a department manager keeps reporting to the CEO.

**Competition teams are operational units of their own.** Each team sits in the Bittensor Division, led by its **Competition director**. Its **squads** (Databases, Agent build, Evaluation, Release & quality…) come from the team's own roster, and each squad is led by its squad lead. The Director's own Command squad works directly under the Director. **Business divisions** shows each team as an environment: its goal, board, budget, notebook and lessons, files, experiments, sandbox runs, the Director's latest report, and any specialists on loan. Competition 28 and Competition 29 never share a board, files or budget.

On the **Organization chart**, solid lines mean *reports to*, dashed lines mean *sponsors*, and dotted lines mean *assigned to*. Drag an agent onto a unit to change its home.

## Home and assignments (the matrix)

Every agent has:

- **A permanent identity**: one id (`agent_subnet_intelligence_agent_001`), a **home** unit, one **manager**, and a **department** (its profession). Hana's home is the Bittensor Division, her manager is Gus, and her department is Research & Intelligence.
- **Active assignments**: temporary memberships in a squad, team, division or department. Each one carries its own **authority level inside**, which can narrow the agent's level but never raise it. Assigning never moves the home or changes the manager.

**Request a specialist** (on a division or team, or in **Teams & squads**): pick the department and the skills you need. The department's members and affiliated agents are ranked by skill match, free capacity and performance, with no model call. The request goes to **Governance → Approvals**, or applies at once if your *Mission assignments* policy says *Apply*. The specialist stays one identity and works in a separate scoped context for each assignment.

**Teams & squads** also holds **missions** (temporary teams with a mission manager, which the CEO can staff) and **delegation**. A manager hands tasks down its own line. A task at L3 or above, or one marked sensitive, waits for you. Blocked or overdue work escalates one step a day.

## Governance and authority

**The authority ladder** (organizational authority, by position):

| Position | Authority |
|---|---|
| You (owner · chairman) | Company strategy and reserved decisions |
| CEO | Organization-wide coordination |
| Executive staff | Functional leadership |
| Division and department managers | Division strategy and execution, within budget |
| Competition directors | Competition delivery, in their own team only |
| Squad and team leaders | Task allocation and supervision |
| Agents | Assigned execution |

**Execution authority** is separate, and position never raises it: L0 Observe, L1 Recommend, L2 Sandbox, L3 Approved execution, L4 Restricted autonomy. Raising an agent to L3 or L4 needs your approval.

**Safeguards**:

- The CEO can't override your reserved decisions. Strategy, budgets, external commitments, production deploys and destructive operations always come to you.
- **Budgets** are daily tokens, the same unit as your daily limit (Agent Operations → Budget) and each team's 24-hour budget. A unit's allocation can't exceed its parent's, and the top units' allocations can't exceed your limit. Each team keeps its own budget, which its governor enforces. It counts against the division here.
- **Data scope**: an agent may read what it manages, its home, its team (for squad members, the whole team), its assignments and its missions' units. A Competition director can't read another team's data. Team agents are isolated by their team's own sandbox and files. The profile shows each agent's scope.
- Agents can recommend organizational changes but never grant themselves authority. A proposal that would raise, promote or assign its own author is refused.
- Every request is bound to its exact contents, applies once and expires after 7 days. Pending requests also appear in the [Approval Center](#approvals).

## Knowledge and experience

Read from where it lives, never copied: the [Knowledge hub](#knowledge), each team's notebook, lessons, files and experiments, expertise by department, and performance. **Score agents** scores everyone from finished work over 90 days: runs, evaluation scores, and tasks done without escalation. An agent needs at least 5 finished pieces of work to get a score. Promotions are proposals.

Organization HQ doesn't run agents, call a model or spend tokens.
