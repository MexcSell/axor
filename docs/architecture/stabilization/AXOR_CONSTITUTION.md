# AXoR Constitution

**Status:** Approved by Owner, 2026-11-11 (development direction: *stabilize*; first operational priority: *mission*).
**Authority:** This document and [TARGET_ARCHITECTURE.md](TARGET_ARCHITECTURE.md) govern every change to AXoR. Only an entry in
[ARCHITECTURAL_DECISIONS.md](ARCHITECTURAL_DECISIONS.md) that the Owner approves can amend them.

## 1. Mission

AXoR is a mission-driven agent company. Its job is to receive missions and understand their objectives. It then researches,
plans, assembles the right specialist workforce, executes, validates outcomes against evidence, and improves its own
capabilities. Missions come from Bittensor, Handshake, Outlier and future domains.

AXoR optimizes, in this order:

1. Successful mission outcomes.
2. Execution reliability.
3. Performance.
4. Cost efficiency.
5. Time.

> The Owner provides the mission, time, budget and desired outcome. AXoR researches, plans, staffs, executes, measures and
> improves until it achieves the objective, or explains clearly why it cannot.

## 2. Non-negotiable architectural decisions

1. Stabilize the existing implementation. Do not rebuild AXoR.
2. **Mission Control** owns the overall mission lifecycle.
3. **Bittensor Competition Teams** are specialized execution environments inside the mission ecosystem.
4. **Competition Autoloop** manages the internal competition-task execution cycle.
5. **Workforce, Agent Swarm and Long Tasks** are execution engines, not independent mission authorities.
6. The **G5 Unified Intelligence Orchestrator** provides correlation, observability, evaluation coverage, diagnosis and feedback.
7. The **Evolution Engine** governs experimentation, validation, promotion, versioning and rollback.
8. The **Control Hub** provides unified organizational monitoring and control.
9. **Topology** visualizes the actual system state.
10. Knowledge and memory are reusable, with controlled access and provenance.
11. The following require human approval: critical production operations, submissions, external commitments, financial
    operations and destructive changes.
12. AXoR enforces budgets, sandbox isolation, execution permissions and auditability.

## 3. Standing decisions, kept from earlier discussions

| Decision | Direction |
|---|---|
| Autonomy | Hybrid |
| Evolution | Continuous |
| Knowledge sharing | Controlled |
| Organization | Hybrid |
| Agent assignment | Hybrid |
| Mission execution | Autonomous within constraints |
| Production execution | Human approval for critical actions |
| Resource management | Strict budgets |
| Experimentation | Sandboxed |
| Primary objective | Mission performance |

## 4. Development agreement

1. **Mission first.** Every change contributes to mission execution, reliability, performance or governance.
2. **One architecture.** No specification may contradict this one.
3. **Inspect before modifying.** Understand the existing implementation before changing it.
4. **Preserve existing functionality.** No destructive refactoring without an impact analysis and Owner approval.
5. **Evidence before conclusions.** Nobody calls an agent, team or mission successful without measured evidence.
6. **Incremental implementation.** Every change has tests, acceptance criteria and a rollback procedure.
7. **Continuous evolution.** Improvement comes through controlled experiments, never uncontrolled self-modification.
8. **Human governance.** The Owner approves critical production operations and external actions.
9. **No unnecessary complexity.** Consolidate existing capabilities rather than add layers and dashboards.
10. **No roadmap drift.** Every new architectural proposal is measured against this constitution.

## 5. Roles

| Role | Authority |
|---|---|
| Owner | Final product and architectural authority. Sets objectives, approves architecture and budgets, authorizes production deployment. |
| ChatGPT | Architecture advisor. Analyzes, writes bounded proposals, reviews evidence against acceptance criteria. |
| Claude Code | Implementation engineer. Inspects the real repository and deployment, implements approved changes, tests, reports evidence. |

Neither assistant makes a unilateral architectural change. ChatGPT does not introduce new architectural directions outside
the decision log. Claude Code does not reinterpret the product architecture.

### Change control

1. Someone identifies a problem or improvement.
2. ChatGPT writes a bounded proposal.
3. Claude Code inspects the existing implementation and the change's impact.
4. The Owner approves any architectural change. It is recorded in ARCHITECTURAL_DECISIONS.md.
5. Claude Code implements and tests.
6. ChatGPT reviews the evidence against the acceptance criteria.
7. The Owner authorizes the production deployment.

### Report for each implementation task

Every implementation task reports these 10 items:

1. Problem and evidence.
2. Root cause.
3. Components affected.
4. Minimal change.
5. Dependencies and risks.
6. Acceptance criteria.
7. Implementation.
8. Test results.
9. Regression assessment.
10. Rollback instructions.

## 6. Safeguards

- Back up before changes.
- Make changes incrementally, keep them isolated and reversible, and add no unnecessary frameworks.
- No uncontrolled database migrations.
- No module is removed without an impact analysis and Owner approval.
- Add regression and integration tests with each change.
- Never promote an unverified improvement.
- Never claim mission completion on an agent's statement alone.
- Never fabricate scores or test results. A number nobody measured is shown as **unknown**.
- Never print secrets, credentials, private keys or complete environment-variable values.

## 7. Four things that are never confused

Every document and status report keeps these four apart:

1. What AXoR implements.
2. What works in production.
3. What is missing or broken.
4. What we intend to build next.

Every finding carries one evidence class:

| Class | Meaning |
|---|---|
| **SRC** | Verified in source code, with a file:line reference. |
| **PROD** | Verified in production: observed on the running system. |
| **DOC** | Documented but not verified: a docstring, README or note. |
| **SUSP** | Suspected problem: an inference not yet confirmed. |
| **MISSING** | A capability that does not exist. |

> The architecture serves the mission, not the other way around.
