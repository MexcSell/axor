# G5-2 Proposal: Mission Readiness and Risk Intelligence

**Status:** Proposed, awaiting the Owner. Nothing here is built. Scope follows the Owner's G5-1 review §D and D-011,
D-012, D-015.

**Rules.**
- Extend existing modules: `orchestrator.py` (taxonomy, diagnostics), `task_lifecycle.py` (contracts), `control_dispatch.py`,
  `mission_ops.py` (Control Hub Overview) and the probes in `sandbox.py`, `platform_status.py`, `llm.py` and `kube.py`.
- Add no new dashboard, no parallel mission system and no second orchestrator.
- Risk Intelligence is a capability inside the orchestrator's diagnostics (D-012), read by every layer.

## Scope

1. **Centralized recovery.** One decision function `orchestrator.decide(failure)` used by the dispatcher, Autoloop and Mission
   Control. It applies D1 (credential failures are platform reliability, not agent performance) and D2 (only transient
   failures retry automatically, with bounded exponential backoff, jitter and an idempotency key; the rest stop with
   remediation or replanning).
2. **Capability contracts.** Planner tool schema **v2**: `needs` is required, an empty array allowed. v1 outputs are still
   accepted: missing `needs` means undeclared, and inferred needs then ask for confirmation.
3. **Environment probes.** One probe per capability, each returning PASS, FAIL or UNKNOWN with evidence and a timestamp:

   | Capability | Probe |
   |---|---|
   | docker | the D-013 runner, until then "not provided" |
   | registry | push access configured |
   | vm | `axor.dev/kvm` allocatable and quota |
   | internet | `Egress.status` |
   | postgres, clickhouse | sandbox services |
   | gpu, ram | node allocatable and sandbox quota |
   | credential | a secret by that name exists (names only, never values) |
   | approval | an approval on record |
   | auth (D1) | the CLI or API login for the team's model is signed in (`llm.cli_status`) |

4. **Readiness gate (D-011, D4).** Each mission, Path B `comp:N` first and also `mx:N`, gets PASS, CONDITIONAL or BLOCKED.
   - A failing declared need on a critical task → BLOCKED, whatever the aggregate.
   - CONDITIONAL only through an explicit, Owner-set allow-list.
   - Inferred needs → a confirmation item, never a block.
   - Governance gates unchanged.
5. **Dispatcher integration.** `control_dispatch.tick` and the board's queueing (Autoloop or Director) hold a task whose
   declared needs fail, with the blocker shown. Other tasks continue.
6. **Risk and dependency assessment.** Each BLOCKED or CONDITIONAL item becomes a risk record. Fields:
   - id, mission, layer;
   - description, root cause;
   - probability, impact (the tasks and missions that depend on it);
   - severity;
   - detection (which probe);
   - countermeasure, responsible;
   - approval needed;
   - status, verification evidence.

   **Boundary change for the Owner to decide:** this brings forward part of G5-3. Either the register's first table
   (`io_risks`, owned by the orchestrator per D-012) is created here, fed only by readiness, with G5-3 adding the
   `hq_issues`, alert and diagnosis feeds; or readiness keeps its own records until G5-3. **Recommended: the first option.**
   It avoids a temporary store that G5-3 would have to migrate.
7. **Remediation.** Each blocker names its remediation, its owner (AXoR, a person, or the Owner) and whether AXoR may run it
   alone. For example, re-check a probe is automatic; sign in a login is the Owner's.
8. **Control Hub visibility.** On the existing Control Hub Overview (`mission_ops` console): readiness state per mission,
   blocked tasks with blocker and remediation, open confirmations. No new page.

## Acceptance criteria (evidence, not code)

| ID | Criterion | How it is measured |
|---|---|---|
| A1 | D1: authentication failures don't count against agents | Replaying the 935-run corpus through `decide()`: the 184 sign-in failures fall in **0 agent-fault counts** and in **184 platform-reliability counts**. Unit tests on `orchestrator.outcomes` and `optimize`. |
| A2 | D2: only transient failures auto-retry | A table test over every canonical class: retry only for `transient`, `rate`, `restart` and `quota` (wait for the reset), each with a cap, jitter and an idempotency key. `provider`, `tool`, `credential`, `capability` and `input_too_large` stop with remediation. The corpus replay lists every changed decision by class and count, and **no unlisted change** is allowed. |
| A3 | Idempotency | The same task cannot run twice for one retry key (existing `run_key`), tested under a concurrent tick. |
| A4 | D3: planner schema v2 | v2 planners must emit `needs` (schema-validated, `[]` allowed); a v1 output is still accepted. Tests for both. |
| A5 | D4: only declared needs block | A task with an inferred-only `docker` need is dispatched and a confirmation item appears. With `docker` declared and the probe failing, it is held. |
| A6 | Probes reflect the real environment | On this cluster, live: docker → FAIL (no runner yet), internet → PASS or FAIL per `Egress.status`, vm → PASS (`axor.dev/kvm: 8`), auth → the real login state. UNKNOWN never counts as PASS. |
| A7 | Critical override | 11 of 12 requirements PASS and 1 critical FAIL → **BLOCKED**. A non-critical failure on the allow-list → CONDITIONAL; off the list → BLOCKED. |
| A8 | SN61 seeded end to end | On a seeded copy of SN61's board (06:50Z copy, then live data), every task with a **declared** `docker` need is BLOCKED **before** reaching an agent. Metric: 0 Docker-dependent tasks dispatched, 100% shown with blocker and remediation. |
| A9 | Auth preflight (D1) | With the team's login signed out, the gate says BLOCKED (auth) and no model run starts. Signed back in, it says PASS within one probe interval. |
| A10 | Risk records | Every BLOCKED or CONDITIONAL item has a risk record with all fields filled, or "n/a" with a reason. Each record links the missions and tasks it blocks. |
| A11 | Visibility | The Control Hub Overview shows the readiness state, blocked tasks and confirmations, from the same API the tests read. Browser-checked at 1440 px and 390 px, both themes, no console errors. |
| A12 | Regression | Full unit suite green on SQLite and Postgres. The legacy-reading characterization shows only the A2-listed changes. G5-1 tests kept. |
| A13 | End to end | One scripted scenario on fakes: mission → preflight (BLOCKED: docker, auth) → remediation (sign in; docker "provided" by a fake runner) → PASS → dispatch → a failure → `decide()` → the correct retry or stop → a risk record closed with evidence. |

## Not in G5-2

- The D-013 Docker VM runner (G5-4).
- Feeding `hq_issues`, alerts and diagnoses into the register (G5-3).
- Measured evaluation and validated learning (G5-5).
- Any production deploy, which needs Owner approval.
