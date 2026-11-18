# Target Architecture: AXoR Mission-Driven G5

**Status:** Approved by Owner on 2026-11-11 as the frozen target baseline. See [AXOR_CONSTITUTION.md](AXOR_CONSTITUTION.md).

This document describes the target. What exists today is in [CURRENT_STATE.md](CURRENT_STATE.md), and the distance between
the two is in [ARCHITECTURAL_GAP_REGISTER.md](ARCHITECTURAL_GAP_REGISTER.md). Where the code contradicts this document, the
gap register records it. This document does not change to match the code.

## 1. Layers

```
OWNER & GOVERNANCE        mission objectives · budget · autonomy · approvals · strategic decisions
        │
MISSION CONTROL           Understand → Research → Plan → Allocate → Execute → Verify → Deliver → Learn   (authoritative)
        │
MISSION ORCHESTRATION     Research (knowledge, intelligence) · Planning (tasks, dependencies)
                          Allocation (teams, specialists) · Coordination (scheduling, execution)
        │
DOMAIN EXECUTION ADAPTERS Bittensor (subnet + competition tasks) · Handshake · Outlier · future domains
        │
EXECUTION WORKFORCE       Agents · Teams · Swarms
                          models · skills · tools · MCP · sandboxes · containers · internet access
        │
EVALUATION & EVOLUTION    Evaluation (benchmarks, independent verification) · Evolution (experiment, improve, promote)
        └──────────────── reusable knowledge and continuous feedback into research, planning, staffing and execution
```

The system has one mission identity, one governance policy and one observable execution history.

## 2. Responsibilities

| Component | Owns | Must not become |
|---|---|---|
| Mission Control | Mission lifecycle and objectives | Another agent execution engine |
| Mission Orchestrator | Planning, allocation and handoffs | Another task database |
| Competition Adapter | Subnet-specific rules and integrations | A separate company intelligence system |
| Competition Team | Competition task execution | An independent mission governance system |
| Workforce / Swarm | Agent execution | Mission ownership |
| Task Lifecycle | Canonical task-state interpretation and reconciliation | A second competing task scheduler |
| G5 Orchestrator | Correlation, monitoring, evaluation coverage and feedback | A duplicate execution orchestrator |
| Evolution Engine | Controlled experimentation and promotion | Unrestricted self-modification |
| Control Hub | Human control and organizational visibility | A separate source of operational truth |
| Topology | System visualization | A separate state-management system |

Existing databases and subsystems are **not** merged into one module. Each type of information has **one source of truth**.
Consistent identifiers, events and interfaces connect the sources.

## 3. Mapping to existing modules

The target is built from modules that already exist. The first audit found no new module necessary. The "Current reality"
column summarizes CURRENT_STATE.md; the gap IDs are in the gap register.

| Target component | Existing module(s) | Current reality (see gaps) |
|---|---|---|
| Mission Control | `missions.py` (mx_*), `mission_intel.py`, `mission_engines.py`, `mission_autonomy.py`, `mission_link.py` | Owns custom missions `mx:N` only. Competition missions `comp:N` live elsewhere (G-01). |
| Mission Orchestrator | `control_missions.py`, `control_dispatch.py`, `task_lifecycle.py` | Runs predefined missions `comp:N` and Control Hub tasks outside Mission Control's lifecycle (G-01, G-03). |
| Competition Adapter | `mining.py`, `mining_sources.py`, `ridges.py`, `mining_rivals.py`, `mining_release.py`, `mining_command.py` (ingest) | Spread across about 10 modules. No single adapter interface (G-09). |
| Competition Team | `mining_work.py`, `mining_director.py`, `mining_crew.py`, `mining_autoloop.py` | Board tasks carry a mission ref (built 2026-11-11, not deployed; G-02). |
| Workforce / Swarm / Long tasks | `workforce.py`, `swarm.py`, `infiagent.py`, `rlm.py` | Mission Control's engines. Workforce also keeps its own missions (G-08). |
| Task Lifecycle | `task_lifecycle.py` | Derives stages for `ctl_tasks` only. Board tasks have their own states (G-03). |
| G5 Orchestrator | `orchestrator.py` (io_*), `agent_core.py` (ac_* ledger) | Counts a done board task as score 100 (G-05). |
| Evolution Engine | `evolution.py` (ev_*) | At least 6 other modules promote changes on their own (G-06). |
| Evaluation | `mining_lab.py`, `team_eval.py`, `mining_release.py` (mw_bench), `mission_ops.py` | Board-path benchmarks are reported by the agents themselves (G-04). |
| Control Hub | `control_hub.py`, `mission_ops.py`, `mission_evidence.py`, `command.py`, `governance.py` | Several overlapping consoles (G-10). |
| Topology | `topology.py` | Read-only, as intended. |
| Knowledge & memory | `knowledge_hub.py`, `knowledge_rag.py`, `experience.py`, `mining_knowledge.py` | Provenance exists. Visibility checks are in `mission_evidence.knowledge()`. |
| Governance | `mission_autonomy.py`, `governance.py`, `agent_core.py` limits | Approvals spread over 4 or more queues (G-10). |
| Execution infrastructure | `sandbox.py`, `egress_proxy.py`, k8s `axor-sandbox`, `axor-egress` | Pods run. Isolation is not re-verified (G-12). |

## 4. Nested loops: one mission, two lifecycles

```
OUTER LOOP: AXoR mission (Mission Control)
  Achieve the competition objective within the deadline and budget.
      │
      ▼
INNER LOOP: Competition team (Director + squads + Autoloop), repeated while the mission is active
  observe competition and miner → plan and prioritize → assign specialists → execute
  → review and validate → learn and optimize
      │
      ▼
OUTER EVALUATION: actual competition performance against the mission's success criteria
      │
      ▼
MISSION DECISION: continue · replan · improve · deliver · request approval
```

**The mission owns the objective. The competition team owns the execution of its assigned work.**

| Actor | Role in the loops |
|---|---|
| Mission | Become a top-performing miner in competition X. |
| Competition team | Does the competition's actual work. |
| Director | Plans and coordinates the squads. |
| Agents | Research, engineer, benchmark, analyze, optimize. |
| Autoloop | Keeps tasks moving and enforces operational constraints. |
| Evolution Engine | Experiments with improvements to agents and strategies. |
| Mission Control | Decides whether the mission is succeeding. |

## 5. Data contract

The data contract is specified in [MISSION_EXECUTION_CONTRACT.md](MISSION_EXECUTION_CONTRACT.md). In outline, every record
from a mission down to its evolution history carries the mission ID:

1. Mission ID: objective, success criteria, budget, deadline, governance.
2. Research and competition reference.
3. Task contracts.
4. Execution records.
5. Evaluation records.
6. Evolution history.

Correlation reuses `orchestrator.py` (`io_links`, `corr` on `ac_runs`). There is no second tracking system.

## 6. Universal mission lifecycle

| Phase | What happens |
|---|---|
| Discovery | Objectives, rules, evaluation method, deadlines and constraints. |
| Research | Current documentation, source code, benchmarks and prior experience. |
| Strategy and plan | Approach, expected performance, resources, risks, milestones. |
| Workforce assembly | Discover or create agents, assign roles, configure tools. |
| Execution | Coordinated agents, parallel work, sandboxes. |
| Validation | Measured results compared against benchmarks, weaknesses identified. |
| Evolution | Evidence-based improvement of agents, knowledge, tools, workflows and strategy. |
| Delivery | Validated results, submission once authorized, monitoring, lessons kept. |

`missions.STAGES` already implements this lifecycle as
`understand, discover, plan, allocate, execute, verify, deliver, learn` (`missions.py:59`). For Bittensor, the Competition
Adapter supplies the rules and evaluation criteria. Other domains use the same lifecycle with their own adapters.

## 7. Evolution loop

| Step | What happens |
|---|---|
| 1. Observe | Score, errors, latency, cost, validation. |
| 2. Diagnose | Find the real causes of weak results. |
| 3. Propose | A change to the model, prompt, skills, tools, algorithm, data or strategy. |
| 4. Experiment | In a sandbox, versioned, on a fixed validation set, within budget. |
| 5. Compare | Baseline against candidate: statistical reliability, cost and latency. |
| 6. Decide | Pass: the change is promoted. Fail: the baseline stays. |

Approved improvements become reusable company knowledge.

Evolution works at 4 levels:

| Level | What evolves |
|---|---|
| Agent | Knowledge, skills, prompts, tools, configuration. |
| Team | Roles, composition, coordination, workflows. |
| Mission | Strategies, plans, resource allocation. |
| Company | Reusable capabilities, orchestration policies, infrastructure. |

## 8. G5 capability layers: compatibility addendum (D-010, 2026-11-11)

Sections 1–7 above describe the component stack and the loops; they stay as written. D-010 adds the authoritative
**capability** model: six intelligence layers, with Risk Intelligence across all of them and Governance and Control as shared
policies. The two models are views of the same modules, so nothing moves and nothing is removed.

| G5 layer | Component stack (§1) | `ecosystem.py` layer (view) | Main owning modules |
|---|---|---|---|
| Mission | Mission Control; Mission Orchestration (research, planning) | Mission interface, Mission intelligence | `missions.py`, `control_missions.py`, `control_dispatch.py`, `task_lifecycle.py`, `mission_intel.py` |
| Workforce | Execution Workforce (agents, teams, swarms); Orchestration (allocation) | Agent workforce, Model intelligence | `agent_core.py`, `workforce.py`, `swarm.py`, `organization.py`, `model_router.py` |
| Execution | Execution Workforce (tools, sandboxes, containers, internet); Domain Execution Adapters | Execution | `mining_work.py`, `mining_autoloop.py`, `sandbox.py`, `egress_proxy.py`, `infiagent.py` |
| Evaluation | Evaluation & Evolution (evaluation) | Verification and evolution (verification half) | `orchestrator.py` (evaluation), `mining_release.py`, `mining_lab.py`, `team_eval.py` |
| Adaptive | Evaluation & Evolution (evolution) | Verification and evolution (evolution half) | `evolution.py`, `orchestrator.py` (diagnose, guidance, monitor) and the promotion paths of D-007 |
| Knowledge | The feedback band ("reusable knowledge and continuous feedback") | Knowledge | `knowledge_hub.py`, `knowledge_rag.py`, `experience.py`, `mx_lessons` |
| Risk (cross-cutting) | — (new capability) | — | One register, D-012 |
| Governance and Control (shared) | Owner & Governance | Governance and control | `mission_autonomy.py`, `governance.py`, `agent_core` limits, approval tables |

**Migration plan (no removal).**
1. Now: this table is the crosswalk. `intel_layers.py` already uses the six names and stays the six-layer view.
2. Phase 5 (P2-1 of the G5 assessment): `ecosystem.py` labels each of its eight layers with its G5 layer, so both pages read
   the same model. Its page and API stay.
3. Any new code names its G5 layer in its module docstring.
