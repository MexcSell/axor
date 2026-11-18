# Mission Execution Contract

**Status:** Draft for Owner approval, 2026-11-11.

This contract is the universal data and behaviour agreement between Mission Control, the orchestration layer, domain adapters,
execution engines and evaluation. Each field names the store that is its **source of truth**. Fields marked **(new)** do not
exist yet; their gap is named.

## 1. Identity

| Ref | Meaning | Source of truth |
|---|---|---|
| `mx:<id>` | A mission | `mx_missions` (`missions.py`) |
| `comp:<id>` | A competition team, which is today's predefined mission | `mw_comps` (`mining_work.py`); `ctl_fixed` in `control_hub.py` holds its target |
| `ctl:t<id>` | A Control Hub task | `ctl_tasks` |
| `mw_task:<id>` | A board task | `mw_tasks` |
| `<system>:<run>` | A run | `ac_runs` (`agent_core.py`), with `corr` = the mission ref |

There is **one correlation mechanism**: `ac_runs.corr` plus `io_links` (`orchestrator.link`, `orchestrator.launched`). No
second tracking system is added.

Target (G-01): every competition team works under exactly one `mx` mission that owns its objective. `comp:N` stays the team's
identity. It is not a separate mission authority.

## 2. Mission record

Every field below must exist before Execute starts.

| Field | Source of truth | Notes |
|---|---|---|
| Objective | `mx_missions.understanding.objective` | Written at UNDERSTAND. |
| Success criteria (measurable) | `mx_missions.understanding.criteria`, frozen by `orchestrator.snapshot` at ALLOCATE | Changes after work starts create a new dataset version. |
| Weighted and attested criteria | `mo_criteria` (`mission_ops.py`) | Added by a person, with evidence. |
| Budget (USD, plus the token limit at the gateway) | `mx_missions.budget`; `orchestrator.mission_budget` → `ac_limits` | Hard limit for every run correlated to the mission. |
| Deadline | `mx_missions.deadline` | |
| Autonomy and governance | `mx_missions.autonomy` (`mission_autonomy.py`) | Levels L0 to L4; plan, recover and external overrides. |
| Domain and competition | `mx_missions.team` → `mw_comps` (netuid, competition) | |
| Research | `mx_missions.discovery` (`mission_intel.py`) | Sources and evidence. |

## 3. Task contract

Every task that does mission work carries these fields.

| Field | Board task (`mw_tasks`) | Control Hub task (`ctl_tasks`) |
|---|---|---|
| Task ID | `id` | `id` |
| **Mission ref** | `mission` (built 2026-11-11, not deployed): `mx:<id>`, or NULL = the team's `comp:<comp_id>`; `mining_work.mission_ref()` | `mission` (exists) |
| Assigned agent | `agent_id` | `agent_key` |
| Dependencies | **(new)** for board tasks; the lead's plan lists them only in text | `parent_id` |
| Acceptance criteria | "Done when:" block in `detail` (`mining_release.criteria()`) | `accept` (`task_lifecycle.contract()`) |
| Budget | Team's 24-hour budget plus per-run token cap (`mining_autoloop`) | Run budget |
| Canonical stage | `task_lifecycle.stage()`, which must cover board tasks (G-07) | `task_lifecycle.stage()` |

Rules:

- A task with NULL ref belongs to its team's predefined mission `comp:<comp_id>`: inner-loop work. Mission Control never counts it, never cancels it and never
  attributes it.
- Mission Control selects its tasks **by mission ref, never by time window**. This replaces `missions.py:721-734`.

## 4. Execution records

| Record | Source of truth |
|---|---|
| Agent runs | `ac_runs` (ledger), with detail in the system's own runs table (`mw_runs` …) |
| Model and tool calls | spans (`mw_spans` …), plus OTel traces to Tempo when configured |
| Sandbox runs | `mw_sbx` and `io_sbx` |
| Artifacts | `mw_files`, the notebook (`mw_notes`), Drive saves |

## 5. Evaluation records

Every score shown anywhere must carry all 5 fields below. If any is missing, the score is shown as **unknown** and never
estimated.

| Field | Meaning |
|---|---|
| `source` | `lab` (`mining_lab` runs.jsonl), `ingest` (`mc_metrics`, evaluator or miner key), `chain` (`mh_points`), `rivals` (public harvest), or `reported` (an agent's `record_benchmark`) |
| `ts` | When it was measured |
| `method` | Suite name, task count, repeats, settings |
| `benchmark_version` | `suite_hash` of the frozen release (`mw_release`) |
| `evidence_ref` | A sandbox run, Lab experiment or ingest run id. **(new)** for `mw_bench`, see G-04 |

Only `lab`, `ingest` and `chain` count as **measured**. `reported` is shown, but it never decides a promotion, an adoption or a
mission outcome.

## 6. Competition measurements

| Measurement | Where it comes from today | Status |
|---|---|---|
| Current score | `mc_metrics` (ingest), Lab experiments | Exists. Whether it is connected is unknown. |
| Best historical score | max over measured records | Derived. |
| Leader score and gap | `mining_rivals` (Ridges / SN62); other subnets: `mc_metrics` or unknown | SN62 only. |
| Validation results | Lab, `mw_bench` (comparable) | `mw_bench` is reported (G-04). |
| Task completion | `mw_tasks` by mission ref | Built 2026-11-11, not deployed (G-02). |
| Agent effectiveness | `mission_ops.performance`, `ml_outcomes` | Derived. |
| Execution reliability | `ac_runs` outcomes, `mining_autoloop` failure classes | Exists. |
| Internet connectivity | `mw_sbx` network results, `intel_layers` sandbox part | Exists. |
| Cost per validated result | `analytics.py` | Exists. "Validated" must mean measured (G-05). |
| Evolution improvement | `ev_trials`, `au_versions`, `mb_trials` | Exists in parts (G-06). |

## 7. Handoffs

| From → to | Today | Contract |
|---|---|---|
| Mission Control → competition team | `mw.plan(note≤590 chars, start=True)` | `mw.plan(mission="mx:N", objective, criteria, budget, deadline)`. Every task the plan creates is stamped with `mission`. |
| Team → Mission Control | By mission ref (built 2026-11-11, not deployed; previously a time window) | Mission Control reads tasks by mission ref, plus the latest measured score (§5). |
| Mission Control → engines (Workforce, Swarm, Long tasks) | `child` id and status mapping (`missions._child`) | Unchanged. |
| Any → evaluation | `orchestrator.emit` and `_derived` | Measured verdicts first. A task marked done is not a score (G-05). |
| Any → evolution | Each module promotes on its own | Proposals go to the `evolution` promote gate (G-06). |

## 8. Mission decisions

At the end of each inner-loop cycle, or when `MINING_WAIT` expires, Mission Control makes one decision and records it in
`mx_events`. Request-type decisions also go to `mx_requests`.

| Decision | When |
|---|---|
| continue | Measured progress is going the right way and budget is left. |
| replan | Criteria are not progressing, or tasks are failing in a class that replanning fixes. |
| improve | A measured weakness has an evolution proposal. |
| deliver | The criteria are met on measured evidence, or the deadline arrived. Deliver partial with the reason. |
| request approval | Any submission, production change, payment or external commitment. |

## 9. Governance invariants

- External submissions, production deployments, payments and key or permission changes are never executed by agents. They
  become requests (`mx_requests` or the Approval Center).
- Budgets are hard limits at the gateway (`agent_core.over`). AXoR never sets a limit automatically.
- Experiments run in sandboxes, with no memory writes and read-only tools (`evolution.py`).
- Every promotion and rollback is audited (`ev_audit`; `og_audit` for organization changes).
