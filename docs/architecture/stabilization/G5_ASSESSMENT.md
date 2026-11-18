# G5 Assessment (accepted baseline)

**Status:** Accepted by the Owner on 2026-11-11 as the baseline for architectural stabilization (Owner Review, see D-010 to D-014). Read-only inspection of `main` at `261b8a0` plus the then-uncommitted work (since committed as `d57098e`), against the deployed `1aff3fd`.

**Date:** 2026-11-11 · **Type:** read-only inspection. No application code, schema, configuration or documentation was changed.
**Spec:** "AXoR G5 — Authoritative Intelligence Architecture and Implementation Directive" (sections A–L).

## 0. Scope and how to read this

### Trees inspected

| Tree | State |
|---|---|
| Working tree | `main` at `261b8a0`, with 36 modified or untracked paths from other sessions. |
| Deployed | `1aff3fd-20261111071938`, deployed 2026-11-11 07:23 (`/var/lib/axor/deploys/history`). |

Deployed is behind HEAD. Of the modules cited here, these differ between deployed and the working tree (`git diff --stat 1aff3fd`): `team_eval.py` (+601 lines: Proven benchmarks), `mining_work.py` (76), `missions.py` (26), `mining_release.py` (7), `control_missions.py` (6), `mission_ops.py` (2). Everything else cited is the same in both.

### Status values

Each capability gets exactly one of these:

| Status | Meaning |
|---|---|
| **Implemented** | The code does what the spec clause asks. |
| **Partial** | Some of it, or only on one path. |
| **Missing** | Not found by the searches named. |
| **Unverified** | Couldn't be checked from here. |

### Evidence levels

| Level | Meaning |
|---|---|
| **Src** | Read in the source, with a `file:line` reference. |
| **Unit** | Covered by unit tests with fake services. |
| **Prod** | Seen in production data. Source: the restored backup of 2026-11-11 06:50Z, aggregates only, from `CURRENT_STATE.md` §8.4. |
| **Live** | Observed on the cluster or host today. |

### Test result (today)

`tests/run-unit.sh` on the working tree (axor/web:1aff3fd image dependencies, SQLite): **Ran 865 tests, OK (skipped=7)**, 61.8 s.

All tests use fakes. **No end-to-end mission test exists** (G-15).

### Limits

- Production database reads are refused by this session's permission policy. Every production-data claim comes from the 06:50Z backup copy.
- Director report **#208** and `docs/docker-session` (the SN61 checklist) were **not read** when this assessment was written: #208 is in the production DB, and `docs/docker-session` is not in the repo. *Correction, 2026-11-11: both were read later that day (report of 07:20:21 UTC, and the checklist from team 23's files). See CURRENT_STATE.md §9 and SN61_DOCKER_SESSION_READINESS.md.* Both are **Unverified**.

### Earlier audit

This builds on `docs/architecture/stabilization/CURRENT_STATE.md` and `ARCHITECTURAL_GAP_REGISTER.md` (gap IDs G-xx). The line references this report takes from them were re-checked against the working tree: `main.py:371-392`, `orchestrator.py:622` and `mining_release.py:14,178`. Other gap descriptions are cited as written there. G-02 has changed since that audit: it is now in the working tree, not deployed.

### Overall verdict

All six layers have working parts, but each is spread over several modules and two parallel mission paths, and each has missing responsibilities (§2).

| Spec area | Verdict |
|---|---|
| Risk Intelligence (C) | **Missing** as a capability: there are six fragmentary stores and no register. |
| Preflight and readiness gate (D, E) | **Missing**. Environment problems are classified only after a run fails. |
| SN61 (I) | Its Docker prerequisites are **not available to agents** and **not detected by the system**. The team found the gap itself. |

Of the ten completion criteria in §L, none is fully met in production. Only "existing functionality operational" holds, and at unit-test level (table at the end).

---

## 1. Current architecture and component map

### 1.1 Runtime

| Item | Finding | Evidence |
|---|---|---|
| Size | 149 Python modules, 74,578 lines; 281 distinct tables; 84 routers in `main.py`; 126 front-end JS files | Src (counted today) |
| Process model | Every agent loop runs as a thread in the single `web` pod (`main.py:372-392`). A deploy restarts all of them; `restart_recovery.py` cleans up. | Src, G-13 |
| Cluster | Single-node k3s. | Live |
| Namespaces | `axor` (web, postgres, temporal, redis, observability), `axor-sandbox`, `axor-egress`, `axor-machines`, `axor-host`, `axor-edge`. | Live |
| Model-written code | Runs in throwaway pods in `axor-sandbox`: non-root, no capabilities, no internet unless the team has it. With internet, it goes through the egress proxy under gVisor. | Src `sandbox.py:1-24`, `k8s/base/56-sandbox.yaml` |
| Host Docker | Used by two admin-only services in `axor-host`: the DevOps **runner** (socket read-write, `k8s/host/40-host.yaml:21,37`) and the Docker page's **socket proxy** (read-only). | Src `devops.py:1-20`, `docker.py:1-7` |
| Agent access to host Docker | None directly. The DevOps agent has read tools only ("You can't run, deploy or change anything", `agent_hub.py:236-240`). The host **Workbench** (`axor-workbench.service`, runs as **root**, no `User=`) gives Workflow agents Read/Glob/Grep, and engineers also Edit/Write, but **never Bash** (`workbench/workbench.py:15,385`). Its "checks" are admin-configured commands the service runs on the host when a person clicks them (`workbench.py:15-17`), so they could call Docker as root, but no agent can. | Src, Live (unit file) |

### 1.2 Components mapped to the G5 layers

| G5 layer | Main modules (owner of the records) |
|---|---|
| Mission | `missions.py` (mx_*, 8 stages, `STAGES` :59); `control_missions.py` + `control_dispatch.py` + `task_lifecycle.py` (comp:N predefined missions, ctl_*); `mission_intel.py`; `mission_engines.py`; `mission_autonomy.py`; `mission_link.py` |
| Workforce | `agent_core.py` (ac_agents registry, ac_runs ledger, budgets); `workforce.py`; `swarm.py`; `organization.py`; `model_router.py`; `cli_accounts.py`/`llm.py` (model access) |
| Execution | `mining_work.py` (board, Director, sandbox tool); `mining_autoloop.py`; `control_dispatch.py`; `sandbox.py`; `egress_proxy.py`; `infiagent.py`; `rlm.py`; `stuck.py`; `restart_recovery.py`; `machines.py` (VMs for people, not agents) |
| Evaluation | `orchestrator.py` (io_*: evaluator registry, coverage, outcomes); `mining_release.py` (mw_release, mw_bench); `mining_lab.py`; `team_eval.py`; `mission_evidence.py`; `mission_ops.py` (performance) |
| Adaptive | `evolution.py` (ev_*); `orchestrator.py` (diagnose, guidance, monitor, optimize); `mining_upgrade.py`; `mining_improve.py`/`mining_evolve.py`; `workforce.py` (wf_improvements); `agent_studio.py`, `company_agents.py`, `marketplace.py` |
| Knowledge | `knowledge_hub.py` + `knowledge_spaces.py` + `knowledge_rag.py`; `experience.py` (ex_*); `mx_lessons`; `wf_memory`; `mw_notes`; `mining_rivals.py` (rv_*) |
| Risk (cross-cutting) | No owner. Fragments: `hq.py` (hq_issues), `orchestrator.py` (io_diag, io_sbx), alert tables (§3) |
| Governance and control | `mission_autonomy.py`, `governance.py`, `command.py`, `agent_core` limits, `mission_ops.decision_queue`, four approval tables (G-10) |
| Read-models over all of it | `intel_layers.py` (6 layers), `ecosystem.py` (8 layers), `mission_ops.py`, `topology.py`, `analytics.py`, `overview.py`, `command.py` |

### 1.3 Two mission paths

| Path | What it covers | Production use |
|---|---|---|
| **Path A** (`mx:N`, `missions.py`) | The full 8-stage lifecycle. | **0 missions** (Prod). |
| **Path B** (`comp:N`, `control_missions.py`) | Competition teams. SN61 is `comp:23`. | All production work (1,255 board tasks, Prod). |

Path B **never passes through `missions.STAGES`** (G-01). This matters for everything below: a gate added to Path A's stages would not touch SN61.

---

## 2. The six intelligence layers

`intel_layers.py` already shows six layers with these names. That is a dashboard over the systems, though, not the systems themselves. Statuses below come from the owning modules.

### 2.1 Mission Intelligence

| Responsibility (B.1) | Status | Evidence |
|---|---|---|
| Understand objectives and requirements | Implemented (Path A); Partial (Path B: templates plus Mission Intelligence reviews) | Src `missions.py:445` (`_understand`), `control_missions.py:58-61` (templates); Unit `test_mission_*` (autonomy, engines, intel, ref, team), `test_control_missions`; Prod: Path A never ran |
| Constraints, deadlines, budgets | Partial. Budget fit is checked; the deadline only as a failure class. Environment and capacity constraints aren't analysed. | Src `missions.py:609-632` (`_allocate`, Pause if the budget is too small), `:95` (deadline class) |
| Measurable acceptance criteria | Implemented for mx and ctl tasks; Partial for board tasks | Src `missions.py:609-634` (criteria frozen as a dataset), `task_lifecycle.py:98` (`contract`) |
| Decompose into tasks | Implemented | Src `missions.py:573` (`_plan`), `control_missions.py` templates, `mining_work` lead plan |
| Required dependencies and capabilities | **Missing** for environment capabilities. Nothing derives "this task needs Docker, KVM, internet or N GB RAM". | Searched `missions.py`, `control_missions.py`, `control_dispatch.py`, `task_lifecycle.py`, `mission_link.py` for sandbox, docker, internet and ready(): no match except the post-failure regex `missions.py:100` |
| Priorities | Unverified (not inspected in depth) | n/a |

### 2.2 Workforce Intelligence

| Responsibility (B.2) | Status | Evidence |
|---|---|---|
| Discover and evaluate agents | Implemented | Src `agent_core.py` (ac_agents), `orchestrator.py:1047` (`optimize`: under- and over-performers from the ledger) |
| Match expertise to tasks | Partial. The scheduler picks by team, room and model health, not by skill. | Src `task_lifecycle.py:278` (`pick`); skill maps exist in `organization.py:90` but aren't used by `pick` (not found) |
| Dynamic teams | Implemented (Swarm, Workforce) | Src `swarm.py` (controller sizes a team), `workforce.py`; Unit `test_swarm` |
| Allocate by performance and availability | Partial. Availability yes; per-model scores via the router; agent scores aren't used in allocation. | Src `task_lifecycle.py:278`, `model_router.py` |
| Identify capability gaps | **Missing**. The only "gaps" found are validation-set gaps. | Src `mining_topminer.py:285-297`; searched workforce, organization, organization_hq, mining_topminer |
| Improve composition | Partial. Recommendations only, never applied. | Src `orchestrator.py:1047-1050` docstring: "Recommendations … never applied here" |

### 2.3 Execution Intelligence

| Responsibility (B.3) | Status | Evidence |
|---|---|---|
| Coordinate agents, teams, swarms | Implemented | Src `control_dispatch.py:390` (`tick`), `mining_work` Director and Autoloop, `swarm.py` |
| Manage tools, APIs, sandboxes, VMs, environments | Partial. Sandboxes, egress and MCP tools are there. **No VM or Docker environment for agents**: the sandbox quota forbids KVM (`56-sandbox.yaml:29` `requests.axor.dev/kvm: "0"`) and the sandbox image has no Docker CLI (`k8s/sandbox/Dockerfile`). VMs exist only for people (`machines.py`). | Src; Live (boot test below) |
| Execute workflows | Implemented | Src `mining_work.py:1642-1695` (`_sandbox`), `missions.py:637+`; Prod 2,692 sandbox runs |
| Dependencies and concurrency | Partial. Concurrency yes (sandbox `AT_ONCE`, CLI gates, team caps). Task-to-task dependency ordering not verified. | Src `sandbox.py:40` (AT_ONCE), `cli_parallel`; Unit `test_cli_parallel` |
| Monitor health and resource consumption | Partial. Tokens and budget yes. Node CPU and memory against allocatable are read for the ops agents' `cluster_overview` tool and host memory and disk for the System page, but no mission or task path uses them. | Src `agent_core.py:273` (`over`), `kube.py:212`, `ops_agents.py:494-525`, `system.py:28,77` |
| Controlled retries and recovery | Implemented | Src `control_dispatch.py:31,41` (MAX_TRIES 3, RETRY classes), `missions.py:95-104` (RECOVERY), `mining_autoloop.py:48-61`, `stuck.py`, `restart_recovery.py`; Unit `test_stuck`, `test_task_lifecycle`, `test_dispatch_sync` |

**Docker on a VM (Live, 2026-11-11).** A one-off manual test pod in `axor-machines` booted a Debian VM with KVM. Inside it, Docker 29.9.3 and Compose v5.7.0 ran a build, `compose up`, a published port, an `/openapi.json` fetch and `docker stats`: PASS in 105 s. The pod has since been deleted.

This proves the cluster can host it. It is **not a product capability**: no code path uses it.

### 2.4 Evaluation Intelligence

| Responsibility (B.4) | Status | Evidence |
|---|---|---|
| Measure actual outcomes | Partial. A run on a done board task is scored **100** by derivation. | Src `orchestrator.py:655` (`classify`), `:622` ("Approved: its task is done"), G-05 |
| Validate deliverable quality | Partial. Structural checks; the model check is **off by default**; Path A's verifier judges text, not measurements. | Src `task_lifecycle.py:39` (`CONTROL_VERIFY_MODEL` default 0), `missions.py:808-836` (G-04) |
| Benchmarks and validation sets | Partial. Team tests T01–T10 and GAIA are in the working tree (GAIA committed in `261b8a0`, not deployed). Board benchmarks are **reported by agents** (`record_benchmark`). | Src `team_eval.py`, `mining_release.py:14,178` (BENCH_TOOL); Unit `test_team_eval*`, `test_mining_release`; Prod **14 mw_bench rows, all non-comparable; 0 frozen releases; 0 Lab experiments** |
| Compare against objectives and competitors | Partial. The competitor harvest runs; ranks are unknown. | Src `mission_evidence.py`, `mining_rivals.py`; Prod 114 rv_agents, rank UNKNOWN for both teams |
| Identify performance gaps | Partial (five-dimension model, no measured inputs) | Src `mission_ops.py` (`performance`) |
| Reproducible evidence | Partial. File or commit sha256 manifests; **no container image digest** anywhere. | Src `mining_release.py:197` (mw_release.sha256 of a workspace file or commit); searched mining_release, mining_command, mining_work for digest: none for images |

### 2.5 Adaptive Intelligence

| Responsibility (B.5) | Status | Evidence |
|---|---|---|
| Analyse evaluation results and feedback | Implemented | Src `orchestrator.py:799` (`diagnose`), `:1183` (`guidance`, called by three planners: `control_missions.py:543`, `missions.py:549` with lessons off, `mining_work.py:1480` for team plans); Unit `test_team_plan_guidance`, `test_orchestrator` |
| Optimise strategies and workflows | Partial (guidance into planning; no workflow optimiser) | Src as above |
| Improve agent capabilities | Implemented, **in ≥7 separate promotion paths** | Src G-06 (`evolution.py`, `mining_upgrade.py`, `mining_improve.py`/`mining_evolve.py`, `workforce.py`, `agent_studio.py`, `company_agents.py`, `marketplace.py`) |
| Recommend workforce and architecture improvements | Partial. Workforce recommendations only; nothing for architecture. | Src `orchestrator.py:1047` |
| Execute approved adaptations | Implemented (hash-bound approvals) | Src `evolution.py`, `orchestrator.approve_experiment`; Unit `test_evolution`, `test_evolve` |
| Verify measurable improvement | Partial. A promotion monitor exists, but has never been exercised in production. | Src `orchestrator.py:1016` (`monitor`); Prod **0 evolution trials, 0 promotions** |

### 2.6 Knowledge Intelligence

| Responsibility (B.6) | Status | Evidence |
|---|---|---|
| Collect internal and external | Implemented | Src `knowledge_hub.py:1-30` (imports), `mission_intel.py`, `mining_rivals.py`, web_read |
| Maintain knowledge and experience | Implemented | Src `knowledge_hub`, `experience.py:77-82` (ex_*), `missions.py:236` (mx_lessons), `workforce.py:736` (wf_memory), `mining_work.py:413` (mw_notes) |
| Validate reliability and freshness | Partial. Company knowledge has review states and `review_at`. Lessons, notes and memories have none. | Src `knowledge_hub.py:189,454` |
| Skills, memories, procedures, docs | Partial (loadouts, knowledge types; no single owner) | Src `mining_loadout.py`, `knowledge_spaces.py` |
| Controlled sharing | Implemented (scopes, reach, promotion to teams) | Src `knowledge_hub.py:25-30` |
| Preserve lessons | Partial. Team and company lessons reach planners only when approved (`orchestrator.py:1235-1238`: `mk_items` scope `global_approved` or `subnet_shared`; verified `kb_items`). **Mission lessons don't**: model-written lessons go straight into `mx_lessons` (`missions.py:890-893`), and `guidance()` returns goal-matched ones with **no outcome or review filter** (`orchestrator.py:1225-1229`) to the team-plan and Control Hub planners. That conflicts with G: "do not automatically promote unverified agent-generated conclusions". | Src; Unit `test_learning`, `test_experience` |

---

## 3. Risk Intelligence: existing capabilities and integration

**Verdict: Missing** as a cross-cutting capability. There is no risk register, no prediction and no probability. Six unconnected stores each cover a slice.

| Store | What it records | Scope | Evidence |
|---|---|---|---|
| `hq_issues` | severity, title, detail, cause, recommendation, status, resolution, verdict, needs_admin, first/last seen | Infrastructure patrols (Agent HQ) only | Src `hq.py:215-218` |
| `io_diag` / `io_sbx` | failure class, recoverable, recovery, evidence | Failed runs and sandbox runs, after the fact | Src `orchestrator.py:263-267`, `:799-822` |
| `alerts`, `ac_alerts`, `mo_alerts`, `mh_alerts` | level, title, detail, status | Subnet news, budget thresholds, mining ops, campaigns | Src `alerts.py:86`, `agent_core.py:106`, `mining_ops.py:81`, `mining.py:403` |
| `ev_proposals.risk` | change class (config, code, external, financial) | Evolution proposals | Src `evolution.py:53,172-175` |
| Mission plan `risks` | up to 4 free-text lines | Path A plans only (0 in prod) | Src `missions.py:174`, `:851`, `:917` |
| Agent-declared risk | low, medium or high in structured messages | Company, Swarm, Workforce Security team | Src `company.py:175-178`, `workforce.py:207-210` |
| `risk.py` | **Subnet investment risk** (scam and avoid flags) | Not operational risk: a name collision to keep in mind | Src `tests/unit/test_risk.py:1` |

### Mapping to the spec's 11 risk-record fields (C)

Best existing match is `hq_issues`; none of the stores carries a mission reference.

| Field | Status | Where |
|---|---|---|
| Risk ID | partial | `hq_issues.id` (infrastructure only) |
| Related mission and layer | **missing** | No store has a mission or layer column |
| Description, root cause | partial | `hq_issues.detail`, `.cause`; `io_diag.evidence` |
| Probability | **missing** | nowhere |
| Impact | **missing** | `severity` only |
| Severity, priority | partial | `hq_issues.severity`, alert `level` |
| Detection method | partial | `hq_issues.agent`, `.key`; `io_diag` via classifier |
| Countermeasure | partial | `hq_issues.recommendation`, `io_diag.recovery` |
| Responsible agent or service | partial | `hq_issues.agent`, `.team` |
| Approval requirement | partial | `hq_issues.needs_admin` |
| Resolution status, verification evidence | partial | `hq_issues.status`, `.resolution`, `.verdict` |

### The 9 responsibilities

| # | Responsibility | Status |
|---|---|---|
| 1 | Identification | Partial: infrastructure (hq) and failures (diag) only |
| 2 | Prediction | **Missing** |
| 3 | Probability and impact | **Missing** |
| 4 | Dependency and failure analysis | Partial: post-hoc failure classes |
| 5 | Countermeasure planning | Partial: per failure class, after the fact |
| 6 | Continuous monitoring | Partial (§4.3) |
| 7 | Incident detection and escalation | Partial: hq escalation; `task_lifecycle.escalate` |
| 8 | Countermeasure verification | Partial: `hq_issues.verdict` only |
| 9 | Risk knowledge preservation | **Missing**: only failure lessons in mx_lessons |

---

## 4. Missing functionality and architectural weaknesses

### 4.1 Mission lifecycle (D)

`missions.STAGES` has 8 stages: understand, discover, plan, allocate, execute, verify, deliver, learn (`missions.py:59`). The spec has 12 steps. **No stage exists for:**

- step 4: infrastructure and environment preflight;
- step 5: risk assessment and countermeasures;
- step 6: readiness verification.

Path B (SN61) has no stage machine at all (G-01).

### 4.2 Preflight (E) and Readiness Gate (D)

**Readiness gate (PASS / CONDITIONAL / BLOCKED): Missing.** `mission_ops.readiness()` (`:856-931`) is a **system scorecard** of 12 rows (pass, partial, unknown, fail). Its only caller is the console (`mission_ops.py:559`), and it never gates execution.

Two properties of it should be kept:

- Its verdict can't be raised by an aggregate: one failing row means "Not demonstrated yet" (`:929`).
- It marks design-held rows separately (`basis="design"`).

`mission_autonomy` is a plan-approval gate, not a readiness gate. `task_lifecycle.contract` (`:98`) blocks only a missing title or destination.

| Preflight item (E) | Status | Evidence |
|---|---|---|
| Execution environments | Partial: checked at run time, never before a mission | `sandbox.py:276` (`ready`), `Egress.status` (~:202) |
| Docker and container compatibility | **Missing** for agents | §2.3 |
| Network and internet | Partial: run-time and per-team flag | `Egress.status`, `mw_comps.internet` (`mining_work.py:673`) |
| External APIs and services | Partial: setup checks, not tied to missions | `platform_status.py:40`, `llm.check_url` :140 |
| Credentials and permissions | Partial: model logins only | `llm.cli_status` :265, `cli_check` :356, `plan_usage.py` |
| CPU, memory, disk | Partial: read for people and ops agents, **not for missions** | `kube.py:212`, `ops_agents.py:494`, `system.py:77`, `machines.py:102` (KVM slots); searched missions, control_missions, control_dispatch, task_lifecycle: no capacity read |
| Required models and tools | Partial | `missions._allocate` model pick; ungranted-tool notes (web_read) |
| Dependency versions | **Missing** | Searched for version and pin checks in the mission, dispatch and sandbox modules: none |
| Time and budget | Partial: budget yes, deadline reactive | `missions.py:609-627`, `:95` |
| Expertise and workforce | Partial | `mission_link` asks the user to make a team; `task_lifecycle.pick` |

**The seven-step issue pipeline** (identify, impact, countermeasure, auto-remediation allowed, execute, verify, update readiness) is **Missing**. Today an environment problem is found by a regex on a failure message (`missions.py:100`, class `environment` → RECOVERY `stop`), i.e. after the work has failed.

### 4.3 Continuous runtime monitoring (F)

| Signal | Status | Evidence |
|---|---|---|
| Infrastructure failures | Partial | `hq.py` patrols, `restart_recovery.py`, `platform_status.py` |
| Network interruptions | Partial (classified, not monitored) | `mining_autoloop.py:48-55` transient class |
| API changes | Partial: generic, not targeted | `mining_web.py:1-18,266` watches: any public page or JSON an agent sets up is re-fetched (≥10 min) and "added, removed, changed" goes to the board feed. Nothing watches the competition's API schema by default; searched "schema drift" and "openapi": nothing |
| Agent inactivity | Implemented | `task_lifecycle.py:292` (watchdog, RUN_TIMEOUT 2700 s), `:317` (unclaimed), `control_dispatch.py:36` (STALE 3600 s), `stuck.py`; Unit `test_stuck`, `test_task_lifecycle` |
| Repeated task failures | Implemented | `control_dispatch.py:31` (MAX_TRIES 3), autoloop "twice and it waits for you" (`mining_autoloop.py:58-61`), dead letters |
| Resource exhaustion | Partial (input size and quota errors only) | `orchestrator.diagnose_sandbox` :816 |
| Budget overruns | Implemented in source; not proven in production | `agent_core.py:273,635`, `mining_work.py:52` (HARD_PCT 110); Unit `test_budget*`; Prod **0 hard limits set**; G-14 |
| Benchmark deterioration | Partial (promotions only) | `orchestrator.py:1016` (`monitor`); no competition-score trend (0 measured scores, Prod) |
| Invalid or incomplete deliverables | Partial (structural; model check off) | `task_lifecycle.py:39` |
| Fallback environments | **Missing** | `sandbox.py` has one pod type; searched for fallback near sandbox across `backend/app`: none |
| Rollback | Implemented (deploys, evolution) | `k8s/redeploy.sh`, `evolution.py` |

### 4.4 Organizational learning (G)

| Requirement | Status | Evidence |
|---|---|---|
| Evidence capture and root causes | Partial | `io_diag` |
| Lesson validation before reuse | **Missing** for `mx_lessons`, `wf_memory`, `mw_notes` | §2.6 |
| Versioning and provenance | Implemented for the Knowledge Hub only | `knowledge_hub.py:20-24` |
| Measuring whether a lesson helped | Partial: recall outcomes settle per use | `experience.py` ex_uses; Prod: failure settlements were never seen before the 11-11 fix |

### 4.5 Governance (H)

| Requirement | Status | Evidence |
|---|---|---|
| Human approval for external actions | Implemented by design (hash-bound approvals) | `mission_ops.py:918-925` |
| Strict mission budgets | Partial: enforcement exists, no limits set in production | Prod: 0 `ac_limits` |
| Isolated execution | Implemented for sandboxes (G-20: not re-verified since 11-09) | — |
| Least privilege | Two host-level privileges to record (not defects): the DevOps runner holds the host Docker socket **read-write** (admin and sudo only, `k8s/host/40-host.yaml:37`, `devops.py:16-20`), and the Workbench runs as **root** on the host (agents get no Bash; admin-configured checks run as root). | Src, Live |

---

## 5. Duplicate services and unnecessary complexity

| Duplication | Instances | Evidence |
|---|---|---|
| Layer models | **Two live layer models**: `intel_layers.py` (6) and `ecosystem.py` (8). Its own docstring says "neither replaces the other" (`intel_layers.py:4-6`). A third, `TARGET_ARCHITECTURE.md` §1, was approved by the Owner on 11-11 and differs from G5's six. | Src, Doc. **Owner decision needed (see §8, Phase 0)** |
| Failure classifiers | **Five vocabularies** | `missions.py:95-104` (`environment`, `api`…), `mining_autoloop.py:48` (`transient`, `cap`…), `intel_layers.py:92-99` (`fail_class`), `orchestrator.py:103,221` (RECOVERY, `sbx_class`), `control_dispatch.py:41` (RETRY set) |
| Alert and issue stores | **Five plus diagnosis** | `alerts`, `ac_alerts`, `mo_alerts`, `mh_alerts`, `hq_issues` (+ `io_diag`) |
| Readiness and health scorecards | **Five** | `mission_ops.readiness`, `intel_layers` layer health, `ecosystem` status, `mining_topminer.readiness` (validation sets), `platform_status` |
| Mission and task authorities | 12 | CURRENT_STATE §3.1 |
| Approval queues | 4 tables, 3 aggregations | G-10 |
| Promotion paths | ≥7 | G-06 |
| Organizational models | 6 | G-18 |
| Table prefixes | `mo_` and `ml_` collide; columns added to other modules' tables | G-16 |

---

## 6. Existing functionality that must be preserved

- The **sandbox security model**: non-root, no capabilities, ConfigMap input, egress proxy with per-run tokens and byte caps, gVisor for internet runs, secret withholding (`sandbox.py`, `56-sandbox.yaml`, `57-egress.yaml`). Unit `test_sandbox_internet` and others.
- **Hash-bound approvals**, and "never by policy" for registration, submissions, deploys, payments and limits (`mission_ops.py:918-925`).
- `mission_ops.readiness`'s rule that one failing row can't be averaged away (`:929`), and its `basis` distinction.
- **Retry and recovery machinery**: dispatcher retries and dead letters, Autoloop classes and policy, `stuck.Watch`, restart recovery, task watchdog.
- **Budget gateway**: `agent_core.over` plus guards, team HARD_PCT.
- **Evidence and provenance**: Knowledge Hub versions and audit, mw_release manifests, criteria datasets, orchestrator handoff ledger (io_events).
- **Mission ref on board tasks** (G-02, working tree): needed for any per-mission gate on Path B.
- **APIs**: `/api/mos`, `/api/control/*`, `/api/layers`, `/api/g5`, `/api/learning`, the mining endpoints. The 865 unit tests pin much of this.
- **SN61 data**: team 23's files (BEX capture, detectors v0.6) and the host `bex-capture` container.

---

## 7. Required changes, by priority

Each item names the spec clause, the gap ID, and the existing module it would extend. No new module is assumed. Anything that does need one is marked as needing a decision.

| # | Change | Spec | Gap | Extends |
|---|---|---|---|---|
| **P0-1** | Give Path B (comp:N, SN61) a stage machine that can carry a gate. Otherwise no readiness gate reaches SN61. | D, I | G-01 (D-004 approved, not implemented) | `control_missions.py`, `task_lifecycle.py` |
| **P0-2** | **Requirements on tasks plus a preflight evaluator.** Tasks and missions declare required capabilities (docker, internet, KVM, RAM, model, tool, credential). A preflight check maps each to an existing probe and returns PASS / CONDITIONAL / BLOCKED. Critical requirements can't be overridden by an aggregate. The **dispatcher refuses** dependent tasks while BLOCKED. | D, E, I | new gap | `task_lifecycle.contract`, `control_dispatch.tick`, `mission_ops.readiness` (reuse its row rule), probes in `sandbox.py`, `platform_status.py`, `llm.py` |
| **P0-3** | **One failure taxonomy**, shared by missions, Autoloop, dispatcher and orchestrator. Today environment problems are named five ways. | C, F | new gap | `intel_layers.fail_class` / `orchestrator` as the single source |
| **P0-4** | **Risk register.** One record type with the 11 fields, a mission ref and a layer. It is fed by preflight results, `io_diag` classes and `hq_issues`; Adaptive acts on it, Risk doesn't. Needs a decision on where it lives (extend `hq_issues`, or a register owned by the orchestrator). | C | new gap | **decision needed** |
| **P0-5** | **Docker execution for agents.** The cluster can host a KVM VM with Docker (Live test). Turning it into an agent capability is an **option awaiting Owner approval**, not a finding. | E, I | new gap | **decision needed** |
| P1-1 | Measured evaluation: scores from measured results; agent-reported benchmarks marked as such | B.4 | G-04, G-05 | `orchestrator._derived`, `mining_release` |
| P1-2 | Container image digest in the release manifest (SN61 submissions use a sha256 digest) | I | new | `mining_release.py` (mw_release) |
| P1-3 | Validate lessons before guidance uses them (outcome-verified only, or reviewed) | G | new | `missions._learn`, `orchestrator.guidance` |
| P1-4 | API-change detection for competition endpoints by default (e.g. the BEX `/openapi.json` hash compared over time) | F | new | `mining_web` watches (already detect changes), `mining_rivals` |
| P1-5 | Capacity check (node allocatable, sandbox quota) in preflight | E | new | `kube.py:212` node read, `machines.py:102` |
| P1-6 | One promotion gate | B.5 | G-06 | `evolution.promote` |
| P1-7 | Owner actions with no code involved: register a miner, freeze a release per team, set hard limits | I, H | G-23, G-14 | — |
| P2-1 | Pick one layer view (6 vs 8) after the Owner rules on the layer model | A, J | new | `intel_layers` / `ecosystem` |
| P2-2 | Read alert stores through one read-model, consistent with the register | C | G-10-like | `mission_ops.decision_queue` |
| P2-3 | Workforce capability-gap detection | B.2 | new | `orchestrator.optimize` |

---

## 8. Practical implementation roadmap

*Naming note (2026-11-11): the phases below became G5-1 to G5-5 (D-014), distinct from the stabilization roadmap's S0 to S5. This assessment keeps its original wording.*

Each phase ends with its own tests and an evidence check. Nothing ships without the Owner's go-ahead per phase.

**Phase 0: decisions (Owner, no code).** Decide:

- the layer model: G5 six layers vs the approved `TARGET_ARCHITECTURE.md`;
- where the risk register lives;
- whether to adopt Docker-for-agents (P0-5) and on what isolation;
- confirm D-004 (Mission Control owns comp:N) as the route for SN61.

Record as D-010 onward.

**Phase 1: taxonomy and requirements (P0-3, P0-2 data side).**

- One classifier, with mapping tables for the old vocabularies.
- Capability requirements on ctl tasks and board tasks, derived from templates (e.g. `infra` and `interfaces` tasks need docker for SN61) plus manual edits.
- Gate: unit tests; classifier agreement on recorded errors.

**Phase 2: preflight and gate (P0-2, P0-1).**

- The preflight evaluator, reusing the existing probes.
- PASS / CONDITIONAL / BLOCKED per mission. The dispatcher holds BLOCKED dependent tasks.
- A Path B stage machine (G-01) wired to it.
- Gate: unit tests, plus a seeded server where SN61 is BLOCKED on docker before any docker task dispatches.

**Phase 3: risk register (P0-4).**

- Register fed by preflight, diagnosis and hq issues.
- Read in Control Hub's existing Overview, not a new dashboard.
- Gate: every BLOCKED preflight item and every diagnosed failure class has a register row with all 11 fields.

**Phase 4: SN61 validation (I).**

- With or without P0-5, depending on Phase 0.
- Run the SN61 checklist (once `docs/docker-session` and report #208 are read; both were read on 2026-11-11, see CURRENT_STATE.md §9).
- Every artifact linked to commit, image digest, environment and time.

**Phase 5: monitors and learning (P1).**

- API-change watch, capacity, benchmark trend, lesson validation, measured evaluation.

This fits the existing stabilization roadmap; Phase 0 there is done, and 2.1 and 2.2 have been worked on.

---

## 9. Test cases and measurable acceptance criteria

| ID | Test | Pass condition |
|---|---|---|
| T-1 | Readiness gate, critical override | 11 of 12 requirements pass, 1 critical fails → **BLOCKED** (never CONDITIONAL or PASS) |
| T-2 | CONDITIONAL only by permission | A non-critical failure on the allow-list → CONDITIONAL; the same failure not on the list → BLOCKED |
| T-3 | Dispatcher respects the gate | A task requiring `docker` on a BLOCKED mission is not dispatched; an unrelated task is |
| T-4 | SN61 detection before work (seeded) | With no Docker environment, SN61's Docker-dependent tasks show BLOCKED with reason and countermeasure **before** any of them reaches an agent. Metric: 100% of them, 0 agent-discovered |
| T-5 | Preflight probes | Each of the 10 E items returns a state with evidence. Probe off: Unknown, never PASS |
| T-6 | Remediation loop | An auto-permitted issue: identify → countermeasure → execute → verify → readiness updated, each step logged. A non-permitted issue: stops at the approval request |
| T-7 | Taxonomy agreement | Every recorded `ac_runs.error` and `mw_sbx.error` maps to exactly one class; the old classifiers' results match the mapping table (0 disagreements) |
| T-8 | Risk register completeness | Every register row has all 11 fields non-empty, or a stated "n/a" reason; each BLOCKED preflight item and diagnosed failure has a row |
| T-9 | Risk ≠ Adaptive | The register never applies a change. Adaptive actions reference a register row and an approval |
| T-10 | Lesson validation | An unverified lesson is not returned by `guidance()`; a verified one is |
| T-11 | API change | A changed `/openapi.json` hash raises an incident within one watch interval |
| T-12 | Regression | The full unit suite still passes (today: 865 OK) on SQLite and `--postgres` |
| T-13 | End-to-end (G-15) | One scripted mission on fakes: understand → preflight (BLOCKED) → remediation → PASS → execute → evaluate → learn, with records at every step |

---

## Completion criteria (§L), as of today

| Criterion | Status |
|---|---|
| Six layers with clear, implemented responsibilities | Partial. Five have working parts; responsibilities are spread out; workforce gap detection and risk are missing. |
| Risk Intelligence across all six layers | Missing |
| Preflight detects critical missing requirements | Missing |
| Readiness gates prevent unprepared execution | Missing |
| Runtime monitoring detects and responds to failures | Partial: inactivity, repeats and budget yes; API change only through hand-made watches; no capacity monitoring for missions; no fallback |
| Adaptive Intelligence improves measurable outcomes | Unverified: 0 trials and 0 measured scores in production |
| Knowledge preserves verified learning | Partial: lessons are stored unverified |
| Governance policies enforced | Partial: design-enforced approvals; 0 hard limits set |
| Existing functionality operational | Implemented at unit level (865 OK); production deployed is `1aff3fd` |
| SN61 complete workflow with evidence | Missing: no Docker path, no digest, 0 frozen releases, rank unknown |

### SN61 checklist (I)

| Item | Status | Evidence |
|---|---|---|
| Docker availability | Missing for agents | `56-sandbox.yaml:29`, `k8s/sandbox/Dockerfile`; the host Docker capture on 11-10 and the VM test on 11-11 were manual one-offs |
| Remote execution connectivity | Missing | No remote-execution target in `sandbox.py` or `mining_work._sandbox`; Workbench checks run on the host but only on a person's click |
| Image build and push | Missing for agents. The DevOps runner builds for admins; push to a registry is unverified. | `devops.py:1-20` |
| Image digest verification | Missing | §2.4 |
| Mock validator | Partial: described in a prompt pack, no execution path | `mining_packs.py:213` |
| Live benchmark | Unverified (self-reported; 0 comparable in production) | G-04, Prod |
| RAM measurement | Partial: miner health reports `mem`; no build or test path | `mining_command.py:269` |
| BEX OpenAPI capture | Unverified as a capability; the 11-10 capture was a manual host run; v1.0.0 serves no `/task` | team 23 files |
| Challenge image compatibility | Missing | Searched mining_*, sandbox, team_eval for challenge-image checks: none |
| Container health checks | Partial: miner health, DevOps pipeline health path | `mining_command.py:269`, `devops.py` |
| Reproducible results | Partial: file or commit manifest; 0 frozen releases in production | `mining_release.py:197`, Prod |
| Missing prerequisites detected before dependent tasks | **Missing**. The team found the Docker gap itself (report #208, relayed by the user; not read when this was written, read later on 2026-11-11, see CURRENT_STATE.md §9). | — |
