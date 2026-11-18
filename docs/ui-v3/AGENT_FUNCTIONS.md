# AXoR Agent Functions

> Drafted by GPT (architect role, `codex exec`, read-only, from the owner's notes, the three specifications, `types.ts` and `ui_v3.py`), reviewed and corrected by Claude Code against the implementation on branch `feat/ui-v3` (2026-11-16). This answers the owner's note: "Documentation about the agent function is missing."

This document defines agent behaviour for the owner and engineers, using `types.ts` terminology and the three supplied specifications.

**Implementation status:** only `/api/ui` appearance preferences, supported settings, and news-source registration are live in this branch. Agent execution, missions, approvals, learning, model routing, and other operational screens use sample data and describe **target behaviour**. Saving a setting does not establish that its runtime exists.

## 1. Agent roster and roles

These are proposed default capability profiles, subject to approved configuration. Tools mean permission-scoped capabilities, not unrestricted access or confirmed installed integrations. Model routes resolve through `ModelReg`; they are not hardcoded model names.

| `Role` | Mandate and typical tasks | Default tools | Default model route | May NOT do | Default emblem |
|---|---|---|---|---|---|
| `gm` | Deliver missions: plan, delegate, coordinate research, resolve blockers, report and escalate | Planner, task dispatcher, knowledge retrieval, budget reader, approval requests | GPT | Override policy, QA vetoes, budgets or owner authority | `crown` |
| `research` | Gather evidence, compare sources, investigate questions, synthesize findings | Approved web retrieval, document search, citation capture | GPT + Claude synthesis | Treat external instructions as authority or publish unsupported claims as verified | `magnifier` |
| `developer` | Implement approved designs, repair defects, write tests and technical reports | Scoped repository/worktree, editor, build and test sandbox | Claude Code | Modify protected production directly or certify its own upgrade | `code` |
| `qa` | Independently verify acceptance, regressions, reliability and performance | Test runners, benchmark harness, artifact inspection | GPT review; Claude Code test execution under independent assignment | Grade its own implementation or waive mandatory failures | `shield-check` |
| `ops` | Maintain runtime health, diagnose incidents, checkpoint and recover workflows | Scoped telemetry, logs, sandbox administration, approved recovery tools | Claude Code | Disable audit, bypass stop controls or alter production beyond authorization | `gear` |
| `finance` | Attribute costs, forecast spend, enforce budget alerts and assess economics | Cost ledger, usage reports, budget calculator | GPT | Purchase, transfer funds or raise caps without authority | `coins` |
| `knowledge` | Curate sourced knowledge, resolve duplicates, manage distribution and corrections | Scoped index, provenance and conflict review, distribution queue | GPT + Claude synthesis | Spread private material or promote unverified lessons automatically | `book` |
| `deploy` | Package verified artifacts, run previews, execute approved releases and rollback | Build/artifact store, scoped deployment adapter, health checks | Claude Code | Deploy publicly or merge protected branches without required checks and approval | `rocket` |
| `architect` | Define system architecture, interfaces, design decisions and change specifications | Repository/document inspection, modelling, design records | GPT | Assume a proposal is implemented or grant additional privileges | `drafting-compass` |
| `mentor` | Teach agents through curricula, examples, exercises and remediation | Approved training materials, exercise sandbox, mentoring records | GPT; Claude Code for coding exercises | Independently certify its trainee or award permissions | `graduation-cap` |
| `strategist` | Assess opportunities, priorities, alternatives and organizational proposals | Research, planning, portfolio and financial analysis | GPT | Commit the company to spending, contracts or structural changes | `compass` |
| `security` | Review threats, permissions, dependencies, isolation and security regressions | Scoped scanners, policy inspection, adversarial test sandbox | GPT review; Claude Code scanning/test execution | Expose secrets, weaken safeguards or approve its own security changes | `lock` |
| `designer` | Develop product/UI designs, creative alternatives and accessibility guidance | Design/prototyping tools, asset tools, accessibility inspection | GPT; Claude reviews implementation feasibility | Change workflow authority through appearance or bypass design review | `palette` |

Avatars may be customized without changing identity, role or permissions. Appearance Studio offers an avatar pack (robots / glyphs), six face styles (classic, holographic, expressive, minimal, analytical, elite) and a colour scheme (role colour, cyan, purple, green, gold, pink). The role emblem badge never changes, and accessible labels always name the role.

## 2. General Manager

The GM converts mission input into objectives, acceptance criteria, deliverables, a dependency graph, staffing, milestones, risks, schedule and bounded budget. It records plan revisions and delegates work to specific `AgentInstance`s through `Task`s.

Research orchestration includes internal retrieval, approved external research, parallel investigations where authorized, contradiction review, and GPT/Claude synthesis. Reports must retain citations, uncertainty and unresolved questions.

| GM resolves within the approved charter | GM escalates through `Approval` |
|---|---|
| Task ordering, scoped assignments, reversible implementation choices, bounded retries, research questions, remediation after failed checks | Missing authority, repository creation, public deployment, purchases, budget increases, destructive actions, access/credential changes, constitution changes |
| Evidence disputes resolvable by further investigation or independent evaluation | Unresolved material ambiguity, conflicting strategic objectives, unacceptable risk, or changes outside scope |

A failed gate cannot be “resolved” by ignoring it. The GM may repair, replan or request an authorized change.

The **deputy/associate governor** is a delegated responsibility, not another `Role` union member. Its exact authority remains an owner configuration decision. It may consolidate subordinate reports, track dependencies and cover assigned coordination duties; delegation does not confer owner authority.

The **notes & reports window** shows current plans, decision rationale summaries, directives, deputy reports, subordinate reports, blockers and evidence links. `Message.kind = "thought"` contains an authored operational note, never purported access to hidden internal reasoning.

Company restructuring follows **proposal → impact analysis → approval → staged application**. Analysis covers before/after reporting lines, `Department`s, capability coverage, cost, permissions, independent verification, active instances and rollback. Apply approved changes to future assignments; migrating active instances requires explicit compatibility planning.

## 3. Stable identity and mission instances

| Object | Meaning |
|---|---|
| `AgentIdentity` | Stable `id`, name, role, department, `reportsTo`, approved capabilities, permissions and current `baseline` |
| `AgentVersion` | Immutable version with parent, changes, score, status and change kinds |
| `AgentInstance` | Mission execution identified by `id`, `agentId`, `missionId`, `pinnedVersion`, branch, supervisor and resource usage |
| `Release` / `Branch` / `MergeRequest` | Mission deliverable and source-control lineage, separate from agent evolution |

Lifecycle:

1. Select an authorized `AgentIdentity` and resolve its approved baseline.
2. Create an instance pinned to that version, allocating isolated context, memory writes, files/worktree, credentials, tool scope, execution state and budget.
3. Assign tasks through `Task.instanceId`; record execution and evidence.
4. Other missions may concurrently instantiate the same identity, each with separate resources and history.
5. At checkpoints or completion, freeze evidence and extract `Experience`.
6. Submit reusable changes through the candidate pipeline.
7. Retain instance provenance and retire its runtime according to retention policy.

Use `mission/<mission-id>/<feature-slug>` for mission source branches. Distinct workspaces are required where instances could otherwise mutate shared files.

An instance cannot directly modify another instance or the stable baseline. Approved shared knowledge is accessed through scoped retrieval. Mission completion does not automatically merge memory or code.

**New instances use the new baseline; running instances stay pinned.** Any migration requires authorization, compatibility tests, checkpointing and recovery instructions.

## 4. Experience, evaluation and promotion

`Experience` records `agentId`, `missionId`, timestamp, lesson, classification, confidence, generalization, eligibility and evidence.

| `Experience.kind` | Handling |
|---|---|
| `verified` | Evidence-supported lesson; still requires transfer and applicability checks |
| `tentative` | Hypothesis awaiting corroboration; cannot enter shared memory as verified fact |
| `code` | Implementation lesson/change requiring code review and tests |
| `security` | Restricted security review and remediation; control disclosure |
| `private` | Mission-restricted material; excluded from general promotion |

Filter secrets, personal data, private communications, customer documents, proprietary source and license-restricted material. Redaction alone does not establish transfer rights. Deduplicate and check contradictions before setting `eligible`.

The pipeline is:

1. **Experience → candidate:** define exact diff, applicability, expected benefit and rollback. Populate `Candidate.from`, `to`, `sourceInstances`, `risk`, `kind`, metrics and evaluator. A candidate has one primary `kind`; `AgentVersion.kind` may list several.
2. **Experiment:** isolate the candidate and freeze the evaluation policy.
3. **Independent evaluation:** compare baseline and candidate on matched tasks, pinned datasets, controlled model conditions, repetitions and held-out/adversarial cases.
4. **Decision:** require improvement, non-regression, security, budget and approval gates.
5. **Promotion and canary:** authorize the tested version, expose it to a bounded cohort of new instances, monitor, then complete baseline adoption.
6. **Rollback:** restore the previous healthy baseline/rollout selection on declared regression triggers.

Use the exact candidate statuses: `proposed`, `experiment`, `evaluating`, `passed`, `failed`, `promoted`, `rejected`, `rolled_back`. Canary progress uses `Candidate.canary`; there is no separate canary status.

Before evaluation, version the primary metric, minimum improvement, minimum sample size, confidence requirement, secondary-metric tolerances, canary scope/window and rollback thresholds. **The specifications provide no approved numeric defaults. Missing thresholds block promotion.**

Critical test failures, critical security regressions, unauthorized permission expansion, privacy violations or compromised evaluation independence veto promotion. A positive `delta` or aggregate score cannot override them.

For concurrent candidates, perform a **three-way merge** using their original baseline, proposed change and current baseline. Review semantic conflicts using applicability, evidence strength and recency; preserve conflicting evidence and seek arbitration when necessary. Never use last-write-wins.

Advance `AgentIdentity.baseline` atomically using **compare-and-swap** against the evaluated baseline. If it changed, rebase/merge and independently re-evaluate before retrying.

Preserve exact diffs, source instances, benchmarks, approvals, signed artifact references and rollback lineage. Rollback changes future selection and safely stops/quarantines affected canaries; it never silently rewrites running instances or history.

## 5. Self-modification of agent code

Authorized changes may cover knowledge pointers, procedures, prompts, skills, tool adapters, permitted routing configuration and allowlisted agent implementation code.

All code proposals use:

```text
agent/<agent-id>/candidate/<candidate-id>
```

Build in a separate worktree/sandbox. Claude Code implements; GPT specifies architecture/design; independent reviewers evaluate. Merging mission deliverables does not promote an agent baseline.

Required checks, according to affected scope, include:

- Formatting, lint, type/schema checks and unit tests.
- Integration, tool-contract and end-to-end acceptance tests.
- Paired baseline benchmarks, regression and held-out task evaluation.
- Secret, dependency, permission, isolation and adversarial security tests.
- Reproducible build/artifact checks, rollback and recovery validation.
- Independent review and required risk-tier approval.

Always protected from agent self-modification: governance and permission enforcement, authentication, secrets, spending limits, approval identities/records, audit integrity, stop controls, protected production branches, evaluation scoring/thresholds and held-out fixtures.

Changes to those systems require a separate authorized governance workflow. Exact modifiable directories remain an owner decision; absent an allowlist, code modification is blocked.

## 6. Mentoring and verification

`Mentoring` records `mentor`, `trainee`, `module`, `progress`, `assessment`, independent `verifier`, status and transfer count.

A mentor provides curricula, demonstrations, practice and feedback. Training produces proposed additions to the trainee’s candidate version.

**Mentor ≠ verifier.** Authors, trainees and mentors cannot certify their own work. Assign verifiers independently; changing instance IDs does not remove a conflict of interest. Avoid the same authoring execution lineage controlling evaluation. If independence cannot be established, hold certification for another reviewer.

Retain mentor/trainee source versions, materials, exercises, results, transferred lessons, verifier identity, assessment evidence and resulting candidate/promotion references. A training assessment does not itself grant qualification, permissions or promotion.

## 7. Self-renewal

`Settings.selfRenewal` is administrator-controlled.

| Setting | Target behaviour |
|---|---|
| Off | Disable continuous autonomous evolution. Mission-derived learning and required maintenance may still be proposed under the mission charter and normal gates. |
| On | Schedule ongoing discovery, mentoring and experiments within approved quotas and identical evaluation/approval gates. |

Set hard limits for concurrency, duration, tokens, spend, tool calls, network scope and external writes. Stop on exhausted budgets, failed safeguards, repeated unsuccessful loops or owner intervention.

Provide owner-accessible global stop, mission stop, agent quarantine, evolution freeze and spending suspension independently of agent runtime.

External inspection companies supply versioned verification data: benchmark suites, security cases, methodology, provenance, freshness and integrity evidence. Independently inspect these imports before adoption. Candidates cannot edit the inspection data or scoring used to judge themselves; external reports do not replace local acceptance checks.

The provider and acceptance policy remain configuration decisions. The live router stores `selfRenewal`; it does not implement the scheduler or external verification integration.

## 8. Model loader and routing

`ModelReg` contains:

| Fields | Purpose |
|---|---|
| `id`, `provider`, `model`, `version` | Exact registered model identity |
| `capabilities`, `context`, `roles` | Task, context and role eligibility |
| `costIn`, `costOut`, `latencyMs` | Cost and latency constraints |
| `health`, `enabled` | Availability: `ok`, `degraded`, `down`; activation |
| `fallback` | Alternative registered model ID or `null` |

Define units for registry costs before calculating budgets.

Routing intersects task needs, `AgentIdentity.models`, model `roles`, capabilities, context, tool compatibility, permissions and remaining budget. Reject disabled/down models. Use degraded models only under policy; follow compatible fallback routes with cycle protection. If none qualifies, block and escalate rather than silently widen permissions or cost.

Default division: **GPT handles architecture, design and creative proposals; Claude Code writes code; both synthesize research.** Log handoffs with task, source revision, constraints, evidence and acceptance criteria. Creative proposals receive review. Administrators may configure routes within policy.

`Settings.aiRoles` has `architecture`, `code`, `research`, `creative`. Its live values are assignment labels; saving them does not load a model. Model probes, routing enforcement, credentials and fallback execution remain target behaviour.

## 9. Agent communication protocol

`Thread` links participants within a mission using `kind`: `user`, `superior`, `subordinate`, `peer`. `Participant` is `"user"` or an agent identity ID. `Message` includes thread, mission, sender, recipient, timestamp, kind, text, optional state/attachments and `condensed`.

Use every `MsgKind` as follows:

| Kind | Meaning |
|---|---|
| `instruction` | Assigned action or user directive |
| `report` | Progress, findings, blockers or verification report |
| `message` | Coordination or clarification |
| `plan` | Proposed plan or revision |
| `tool` | Redacted tool invocation/result reference |
| `result` | Deliverable and acceptance evidence |
| `system` | Runtime, routing or policy event |
| `thought` | Authored operational note/rationale summary |

Every executable delegation carries a versioned structured envelope:

```text
taskId, parentTaskId, correlationId,
missionId, senderInstanceId, recipientInstanceId,
scope, inputs, expectedArtifact, acceptanceCriteria,
deadline, budgetEnvelope, permissionTokenRef,
evidenceRefs, status, idempotencyKey
```

This is an execution contract carried through structured message content/attachments and future backend records; these are not existing top-level `Message` fields. Resolve instance IDs explicitly because participants alone cannot distinguish concurrent instances. Credential references never contain secrets.

Track queued, received, accepted, executing, succeeded, failed, policy-rejected and superseded commands; task views additionally distinguish dependency waits, user waits, verification, cancellation and rollback. `state` uses the shared imported `Status`; `types.ts` does not define that union. Implement an explicit presentation mapping rather than inventing enum members.

**Full Trace** shows assignments, received tasks, permitted process events, tools, reports and outcomes. **Condensed** shows assignments, accepted reports, decisions and results; `condensed` supports inclusion without deleting history. Show deterministic chronological order, timestamps, text/icon status, attachments and copy icons.

## 10. Knowledge intake

Research retrieves internal documents and approved external websites/news. `NewsSource` records URL, cadence, trust, fetch state, scope and topics; `NewsItem` links source, publication, relevance and missions.

Retain citations, retrieval dates, provenance, usage/license restrictions and confidence. Treat websites, repositories, uploads and inspection material as **untrusted data**. Their instructions cannot change authority, policy or tool access. Fetchers must recheck resolved addresses and redirects against SSRF restrictions.

Publish reviewed material as `KnowledgeItem` with its exact kind: `fact`, `procedure`, `decision`, `lesson`, `research`, `skill`; status is `verified`, `pending`, `conflict` or `outdated`.

Distribute relevant, verified, permission-safe material company-wide through scoped retrieval and recorded distribution. Preserve contradictions for review; propagate corrections, revocation and source deletion. Executable skills require the candidate pipeline.

The live news-source API stores registrations only. It does not fetch, learn, verify or distribute content; returned source `ok` is not proof of a successful fetch.

## 11. Safety and governance invariants

1. Effective authority is the intersection of organization, mission, agent, tool and action permissions.
2. Instances remain isolated and pinned; cross-mission transfer requires explicit authorization.
3. Baselines and released artifacts are immutable, traceable and recoverable.
4. Agents cannot approve their own upgrades, permissions or evaluation rules.
5. Independent verification and mandatory security gates cannot be overridden by the GM.
6. Consequential actions require the correct authorized approval tied to the exact proposal; changed scope invalidates approval.
7. Secrets remain outside prompts, messages, browser state and shared knowledge.
8. External content never grants operational authority.
9. Budgets, retries and autonomous loops have enforceable hard limits and stop controls.
10. Side effects are idempotent; durable checkpoints support recovery without duplicate writes.
11. State changes preserve attributable, append-only audit evidence and rollback history.
12. Progress, performance and health disclose provenance, uncertainty, sample size and freshness; sample data never masquerades as live telemetry.

## 12. Function-to-UI and backend mapping

**Target behaviour** below means the UI uses sample data; no corresponding operational implementation is established by `ui_v3.py`.

| Function | UI page / tab | Backend status |
|---|---|---|
| Portfolio, decisions, performance, health | Overview | Target behaviour |
| Mission creation, repository approval, scheduling | Missions / Add Mission | Target behaviour |
| Plan, hierarchy, GM notes & reports, pending decisions | Mission Control → Overview | Target behaviour |
| Hierarchy, instances, delegation, chat with a selected agent | Mission Control → Agents | Target behaviour |
| Dependencies, acceptance, retries | Mission Control → Task Flow | Target behaviour |
| Instructions, handoffs, full/condensed messages | Mission Control → Conversations | Target behaviour |
| User decisions and response history | Mission Control → Approvals | Target behaviour |
| Execution traces | Mission Control → Activity | Target behaviour |
| Per-agent assigned / received missions, process, results; GM/deputy reports | Mission Control → Reports; Conversations (GM window) | Target behaviour |
| Tools, models, qualifications | Agents → Capabilities | Target behaviour |
| Concurrent pinned executions | Agents → Mission Instances | Target behaviour |
| Lesson classification and eligibility | Agents → Experience | Target behaviour |
| Baselines, candidates and comparisons | Agents → Evolution | Target behaviour |
| Teaching and independent assessment | Agents → Mentoring | Target behaviour |
| Quality, cost and latency evidence | Agents → Performance | Target behaviour |
| Agent changes and rollback records | Agents → Audit | Target behaviour |
| Departments, assignments, restructuring | Organization | Target behaviour |
| Releases, branches, previews, downloads, merges | Versions | Target behaviour |
| Experiments, benchmarks, promotion, canary, history | Evolution Lab | Target behaviour |
| Library, research, conflicts, distribution | Knowledge | Target behaviour |
| Source registration and management | Knowledge → News / Sources | **Live:** `GET/POST /api/ui/news-sources`; `PATCH/DELETE /api/ui/news-sources/{id}`. Fetching remains target behaviour. |
| Spend attribution, caps, forecasts | Finance | Target behaviour |
| Policies, permissions, approvals, model registry | Governance | Target behaviour |
| Self-renewal, AI assignment labels, notifications | Settings | **Live storage:** `GET/PUT /api/ui/settings`; self-renewal and AI roles require admin. Runtime enforcement remains target behaviour. |
| Appearance preferences | Appearance | **Live:** `GET/PUT /api/ui/preferences`, sanitized per signed-in user |
| Initial identity and supported resources | Application bootstrap | **Live:** `GET /api/ui/bootstrap` |

Source creation is admin-only for organization scope; signed-in users may register mission-scoped sources. Modification/removal requires source ownership or admin authority.

`Settings.autonomy`, `verificationProvider` and `quietHours` are domain fields not persisted by this router. `/settings` uses snake_case storage/response keys; bootstrap exposes camelCase settings, so adapters are required.

Evaluation manifests, task envelopes, rollout records and detailed provenance require backend schemas beyond these UI interfaces. Connecting missions, approvals and messages to existing hubs remains subject to owner decision **D-OWNER-003 / deploy HOLD**.