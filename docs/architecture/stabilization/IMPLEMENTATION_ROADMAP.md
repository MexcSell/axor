# Implementation Roadmap: Mission-First Stabilization

**Status:** Approved, 2026-11-11 (the Owner delegated the decision). Phase 0 is in progress; see the status column. Every item follows the change-control procedure
and the 10-point report in [AXOR_CONSTITUTION.md](AXOR_CONSTITUTION.md) §5. Gap IDs refer to
[ARCHITECTURAL_GAP_REGISTER.md](ARCHITECTURAL_GAP_REGISTER.md).

Phase 5 (company-wide integration) does not start until Phase 2 is proven.

## S0 (stabilization phase 0): Protect the existing system

| # | Item | Gap | Kind | Risk | Effort | Rollback | Status |
|---|---|---|---|---|---|---|---|
| 0.1 | Record the known-good point: tag `stable-2026-11-11` at `1aff3fd`. Image `1aff3fd-20261111071938` is already kept. | — | ops | none | XS | delete the tag | **Done:** local tag, not pushed. |
| 0.2 | Nightly `pg_dump` CronJob to a host path, 14-day retention, plus a restore test into a throwaway Postgres. | G-11 | ops | low | S | `k8s/backup.sh --uninstall` | **First backup taken and restore-verified 2026-11-11** (after the G-22 fix). The nightly timer still needs the Owner: `./k8s/backup.sh --install`. |
| 0.3 | Read the legacy Compose `subnet-scout` logs. With Owner approval, `docker update --restart=no` and stop all 5 legacy containers (not removed). | G-00 | ops | low (data kept) | XS | `docker start` | **Done 2026-11-11** by the Owner: Exited, restart=no, port 8000 answers 301. |
| 0.4 | Freeze architectural expansion: no new module, page, table prefix or agent system without a decision record. | — | process | none | — | — | **In force.** |

**Done when** a restore from last night's dump boots AXoR, only one AXoR instance runs, and the tag exists.

## S1 (stabilization phase 1): Audit completion

| # | Item | Gap |
|---|---|---|
| 1.1 | Owner runs the read-only queries in CURRENT_STATE §7. The results go into CURRENT_STATE, and suspected gaps are confirmed or closed. | G-02, G-14, G-00 |
| 1.2 | Pick the pilot: one existing active competition team (SN62 or SN61). Do not create a new one. | — |
| 1.3 | Confirm which score sources are connected for the pilot: ingest key, Lab, rivals. | G-04 |

**Done when** every P0 and P1 gap is classed PROD or closed, and the pilot is named.

## S2 (stabilization phase 2): Mission execution stabilization (highest priority)

Order is by dependency. Items on the same line can run in parallel.

| # | Item | Gap | Depends on | Risk | Effort |
|---|---|---|---|---|---|
| 2.1 | Postgres in the deploy test gate. **`run-unit.sh --postgres` built; switching the gate awaits the Owner (+~7 min per deploy).** | G-12 | 0.2 | low | S |
| 2.2 | Mission ref on board tasks: additive nullable `mw_tasks.mission`, stamped by `plan`, `add_task` and follow-ups. `_child`, `_collect` and `_stop_child` select by it. `_to_board` returns the id it created, not a title match. **Built and tested 2026-11-11, not deployed.** | G-02 | 2.1 | medium (hot path) | M |
| 2.3 | `MINING_WAIT` expiry becomes a mission decision (extend, replan, deliver partial), not "done". | G-03 | 2.2 | low | S |
| 2.4 | Mission Control owns the competition mission: one `mx` mission per pilot team, linked to `comp:N`. The inner loop (Director, Autoloop) is unchanged. Mission Control runs the outer evaluation and the decision. **Needs decision D-004.** | G-01 | 2.2, 2.3 | medium | M |
| 2.5 | `task_lifecycle.stage()` covers board tasks; `mission_ops` reads it. | G-07 | 2.2 | low | S |
| 2.6 | Re-verify sandbox isolation and internet for the pilot team (test plus live probe). | G-20 | — | none | XS |
| 2.7 | Measured vs reported: `record_benchmark` takes an optional `sandbox_run`. A result is *measured* only when that run exists, belongs to the task and finished. Mission verify reads the latest measured score with source, ts, method and suite hash, otherwise *unknown*. | G-04 | 2.2 | low | M |
| 2.8 | Orchestrator: "task done" is no longer score 100; measured verdicts first. | G-05 | 2.7 | low | S |
| 2.9 | Confirm budget enforcement on production data; close or fix. | G-14 | 1.1 | — | S |
| 2.10 | One E2E test: fake competition, Path A and Path B, through to delivery with a measured score. | G-15 | 2.2–2.8 | none | M |

**Done when** the pilot mission runs through all 8 stages with tasks attributed by ref and verification based on a measured
score, and passes the acceptance tests below.

## S3 (stabilization phase 3): Performance intelligence

| # | Item | Gap |
|---|---|---|
| 3.1 | Thin Competition Adapter interface over existing calls: `observe`, `score`, `leader`, `submit_request`. | G-09 |
| 3.2 | Score history, best score and leader gap per mission, measured sources only. | — |
| 3.3 | Agent and team contribution from `mission_ops.performance` on measured outcomes. | — |

## S4 (stabilization phase 4): Controlled self-evolution

| # | Item | Gap |
|---|---|---|
| 4.1 | One promote gate in `evolution.py`. The Upgrade Factory, Improvements and self mode, Workforce, Studio and Marketplace call it. Their UIs stay. | G-06 |
| 4.2 | One evolution cycle on the pilot: a proposal from a real failure, a sandboxed trial on the frozen suite, promote or reject, then confirmation by an independent re-run. | — |

## S5 (stabilization phase 5): Company-wide integration (after S2 is proven)

| # | Item | Gap |
|---|---|---|
| 5.1 | More competitions through the same adapter. | — |
| 5.2 | Engines' direct missions relabelled as runs. | G-08 |
| 5.3 | Approval views point to one queue. | G-10 |
| 5.4 | Deprecation review of overlapping organizational models, subject to approval. | G-18 |

## Acceptance tests for the first operational milestone

Milestone: **one existing Bittensor competition mission completes its entire execution and evaluation lifecycle with
reproducible evidence.** Each row is checked on production data for the pilot mission.

| Area | Test, pass when | Evidence source |
|---|---|---|
| Mission | `mx` row with an objective and at least 1 measurable criterion, frozen as dataset v1. | `mx_missions`, `io_datasets` |
| Research | Discovery brief cites the competition's official rules and evaluation page with URLs and dates. | `mx_missions.discovery` |
| Planning | Every mission task has a mission ref, acceptance criteria and dependencies where they apply. | `mw_tasks.mission`, `detail`, `ctl_tasks.accept` |
| Workforce | Every mission task has an agent whose role matches. No task is unclaimed for more than 3 h. | `mw_tasks.agent_id`, `task_lifecycle.unclaimed` |
| Execution | At least 1 task finished with a sandbox run that exited 0. | `mw_sbx` |
| Sandbox | Pilot's network policy probe: allowed hosts reachable, others blocked. | `test_sandbox_internet` plus a live probe |
| Monitoring | Every mission run has `corr = mx:N`, and `GET /api/g5/trace?corr=mx:N` lists them. | `ac_runs`, orchestrator trace |
| Evaluation | Mission verify used a **measured** score (source ≠ reported) with a suite hash. | `mx_missions.verification` |
| Performance | Current score, best score and leader gap shown with source and ts, or *unknown* with a reason. | mission view |
| Recovery | A run killed mid-way (deploy or pod restart) is resumed or re-queued without duplicate work. | `restart_recovery.follow` |
| Budget | A deliberately low mission limit stops runs at the gateway; spend ≤ limit × `HARD_PCT`. | `ac_limit_hits` |
| Evolution | At least 1 candidate improvement trialled on the frozen suite, with a promote or reject verdict and audit. | `ev_trials` / `au_versions`, `ev_audit` |
| Governance | A submission step became a request and was not executed until the Owner approved it. | `mx_requests` |

## Dependencies summary

```
0.2 backup ─▶ 2.1 PG gate ─▶ 2.2 mission ref ─┬▶ 2.3 wait decision ─▶ 2.4 MC owns comp mission (D-004)
                                               ├▶ 2.5 one stage model
                                               └▶ 2.7 measured scores ─▶ 2.8 no "done = 100" ─▶ 2.10 E2E
1.1 owner queries ─▶ 2.9 budget confirm ;  2.6 sandbox re-verify (independent)
Phase 2 proven ─▶ 3.x ─▶ 4.x ─▶ 5.x
```

## G5 phases G5-1 to G5-5 (D-014, approved 2026-11-11)

**Naming (Owner, 2026-11-11).** The stabilization phases above are **S0 to S5**, with steps such as S2.1. The G5 phases
below are **G5-1 to G5-5**. The two series are independent: G5-2 is not S2.

Run on the development branch `g5/phase1` and its successors. Each phase ends with the Owner's seven report items and the
Owner's approval; nothing deploys automatically.

| G5 phase | Scope | Gaps | Done when (evidence, not code) |
|---|---|---|---|
| G5-1 | Unified failure taxonomy; task capability requirements (declared or inferred), on board tasks and Control Hub tasks. Nothing gates yet. | G-26, G-27 | Per D-015 D5: zero changes in each legacy classifier's output across the regression cases; cross-classifier conflicts measured, with representative examples and the overlapping vocabularies explained; regression tests kept; requirements measured on SN61's real tasks |
| G5-2 | Preflight engine, readiness gate (PASS/CONDITIONAL/BLOCKED), Path B and dispatcher integration | G-25, G-01 | Seeded SN61 shows BLOCKED on Docker before any Docker task reaches an agent |
| G5-3 | Canonical risk register fed by preflight, diagnoses, hq issues, alerts | G-28 | Every BLOCKED item and diagnosed failure has a full register row |
| G5-4 | SN61 Docker and benchmark validation on the isolated VM capability (D-013) | G-29, G-30 | SN61 checklist (`docs/docker-session/live-bench-checklist.md`) passes with artifacts tied to commit, digest, environment, time |
| G5-5 | Runtime monitoring, measured evaluation, validated learning, adaptive improvements | G-04, G-05, G-31, G-32 | Per the G5 assessment §9 tests |
