# G5-2 Progress: Mission Readiness and Risk Intelligence

**Branch:** `g5/phase2` (worktree `/home/thomas/subnet-scout-g5p2`), from `g5/phase1` @ `0b7ea0d`. **Not merged, not deployed.**
**Authorization:** Owner decisions of 2026-11-11 §5, with clarifications A–J, and acceptance criteria A1–A13 of
`G5_PHASE2_PROPOSAL.md`.

| Milestone | Scope | Status |
|---|---|---|
| M1 | One recovery decision (D1, D2, clarification A) for the dispatcher, Autoloop and Mission Control | **Built, unit-tested, corpus-replayed** |
| M2 | Planner schema v2 `needs` (D3, E); capability probes that check real usability (B, C) | **Built, unit-tested, probed on real cluster data** |
| M3 | Readiness gate (D, D4, F), dispatcher integration, `io_risks` (H) | **Built, unit-tested** |
| M4 | Control Hub Overview (G), seeded SN61 test and scripted end-to-end (J), browser check | **Built, tested, browser-checked** |

## M1: recovery decisions

### What changed
- **`orchestrator.decide(status, error, source, tries, key)`** gives every caller one answer: class, action, delay, max
  tries, whether to retry, an idempotency key, agent fault, reliability, remediation and who acts.
- **`RECOVERY_POLICY`**, one entry per canonical class:

  | Kind | Classes | Action |
  |---|---|---|
  | Immediate | transient | retry: 30 s × 2ⁿ, at most 15 min, ±20% jitter, 3 tries |
  | Delayed | rate (5 min × 2ⁿ), quota (1 h × 2ⁿ), restart (1 min × 2ⁿ), recoverable sandbox failures (2 min × 2ⁿ) | retry later, jitter only adds time (+0–20%), 3 tries |
  | Hold | budget | a person decides |
  | Stop with remediation | provider, credential, tool, capability, unrecoverable sandbox failures | stop until fixed |
  | Replan | cap, input_too_large, invalid_output, test, strategy, no_deliverable, timeout, task, low | back to planning |

  Spent retries become a stop handed to a person. The jitter is derived from the retry key, so two workers compute the same
  moment.
- **Control Hub dispatcher.** Retries only when `decide()` says so, with its delay and the idempotency key
  `ctl:t<id>:retry:<n>`. The token cap stays "held", as before.
- **Autoloop.**
  - Credential, provider, tool and capability failures put the task in **blocked**, with the remediation as its question.
    They are **not counted** against the task (D1), and a provider or login failure cools the team (D2: no blind retry).
  - Timeouts and rate limits retry with `decide()`'s delays.
- **Mission Control.**
  - A login, provider, tool or capability failure **pauses** the mission with its remediation, where it used to retry.
  - The work's own failures go back to planning instead of being retried.
  - Spent attempts stay the mission's own attempt policy.
- **Agent performance (D1).** These now read the canonical class, falling back to the legacy class for older rows:
  - `orchestrator.outcomes` (failure vs environment = platform reliability);
  - `orchestrator.optimize` (the "failing agent" count);
  - Intelligence layers' evolve step;
  - the team board's experience settling.
- **Backfill.** Diagnoses made before `io_diag.canon` existed get their canonical class, one batch per orchestrator pass.

### Source
| File | Change |
|---|---|
| `orchestrator.py` | `RECOVERY_POLICY`, `decide()`, `_jitter`, `OWN_CANON`/`OWN_SQL`; outcomes and optimize read canon; `io_diag.canon` backfill in `diagnose()` |
| `control_dispatch.py` | `_decide()`; `why()` and the tick's retry branch |
| `mining_autoloop.py` | `failed()`: stop and block for credential, provider, tool and capability; `decide()` delays |
| `missions.py` | `_recover()`: pause or replan per the class's policy |
| `intel_layers.py`, `mining_work.py` | Canonical own-fault |
| `tests/unit/test_recovery_decisions.py` | 12 tests (new) |
| `tests/unit/test_control_missions.py` | Transient retry delay is 30 s ±20% (was 5 min), per clarification A |

### Corpus replay (A2): every changed decision, 935 runs from the 06:50Z copy

| Runs | Consumer | Class | Before → after |
|---|---|---|---|
| 184 | agent fault | credential | counted → **not counted** (D1) |
| 184 | Autoloop | credential | counted → **blocked with remediation, not counted** (D1, D2) |
| 184 | Mission Control | credential | retry → **pause with remediation** (D2) |
| 153 | Mission Control | task | retry → replan (D2: the work's own failure isn't retried blindly) |
| 112 | Mission Control | input_too_large | retry → replan (D2: invalid input) |
| 60 | Mission Control | no_deliverable | retry → replan |
| 6 | Mission Control | cap | retry → replan |
| 5 | Mission Control | timeout (sandbox time limit) | retry → replan |
| 2 | agent fault | cancelled | counted → not counted (cancelled runs were never counted in outcomes: "stopped" bucket) |

There are **no other decision changes**. Timing changes not shown in the table:
- dispatcher transient retry: 5 min × 2ⁿ → 30 s × 2ⁿ;
- dispatcher quota: 1 h × 2ⁿ (unchanged in size), jitter added;
- Autoloop transient: 60/240/960 s → 30/60/120 s;
- Autoloop rate limit: 60/240/960 s → 300/600/1200 s.

**Not in the corpus:** `provider` and `tool` failures had zero hits. Their D2 change (the dispatcher used to retry them, now
they stop) is covered by the table tests only.

### Migration and rollback
M1 adds no table or column; it uses `io_diag.canon` from G5-1. To roll back, revert the M1 commit. The `canon` values written
by the backfill are harmless to the old code.

### Test results
See the commit message of the M1 commit and the table at the end of this file (filled per milestone).

## M2: planner needs (v2) and capability probes

### Planner schema v2 (D3, E)
- **Version 2 requires `needs` on every planned task.** It's set by `task_lifecycle.PLANNER_SCHEMA_VERSION = 2` and
  `NEEDS_SCHEMA`, and covers:
  - the team lead's plan (`mining_work.PLAN`);
  - agents' follow-ups (`SUBMIT_WORK.followups`);
  - Mission Intelligence proposals (`control_missions.INTEL`).
- **The prompts state the rule** (`NEEDS_RULE`): declare only what the work can't be done without, `[]` when nothing special.
- **Stored on the task:** `mw_tasks.needs` or `ctl_tasks.needs`, with `"[]"` for declared-none.
- **Recorded per plan run:** `needs_schema` is 2 for a v2 plan, 1 for an older output.
- **Backward compatible.** An output without `needs` (an older planner, a fake model, a stored plan) is version 1: accepted,
  with its tasks left undeclared. Their inferred needs become confirmation items in M3, never blocks (D4, F). Unknown
  capabilities in a v2 output are dropped, not fatal.

### Probes (B, C): `mission_ops.probe(ch, comp, cap, value, fresh)`

| Capability | PASS only when | Otherwise |
|---|---|---|
| docker, registry | (no path yet: the runner is G5-4) | FAIL, by design |
| vm | (never yet: no sandbox VM run) | FAIL when the sandbox quota allows no KVM; UNKNOWN when unreadable or allowed |
| internet | the team's switch is on **and** the egress proxy answers its health check now | FAIL |
| postgres, clickhouse | the sandbox answers now **and** a run used the service successfully in the last 7 days | UNKNOWN when up but unproven; FAIL when the sandbox is down |
| gpu | (never: sandbox runs don't request GPUs) | FAIL when no node offers one, else UNKNOWN |
| ram:N | N ≤ 4 GB, the sandbox runner's limit | FAIL |
| credential:NAME | (never by presence, per B) | UNKNOWN until verified (M3 records verifications) |
| approval | (an approval on record, M3) | UNKNOWN |
| auth (implicit, D1) | a **real tiny prompt** succeeds on each Claude Code / Codex login the team's agents run on (a quota hit still proves the sign-in) | FAIL with the error; UNKNOWN for API-key teams (no sign-in to lapse) |

- **Cached** for 10 minutes per team and capability; `fresh=True` asks again.
- **A probe that breaks** answers UNKNOWN, never PASS.

### Real environment evidence
The probe code was run on the live cluster's answers (`kubectl get --raw` of the sandbox quota and the nodes, captured
2026-11-11 12:39:53Z):

| Probe | State | Evidence |
|---|---|---|
| vm | FAIL | `requests.axor.dev/kvm: 0` in the sandbox quota (the node has 8 KVM slots) |
| gpu | FAIL | no GPU resource on any node |
| docker, registry | FAIL | no runner for agents (G-29) |
| ram:4 / ram:16 | PASS / FAIL | runner limit 4 GB |
| credential:BEX_CHALLENGE_API_KEY | UNKNOWN | presence is not proof |
| approval | UNKNOWN | none recorded |

- **`vm` would read UNKNOWN in production today.** `kubectl auth can-i` shows the web account can list nodes but **can't
  read the sandbox quota**. This branch adds a get-only `resourcequotas` rule to the `axor-sandbox` Role
  (`k8s/base/56-sandbox.yaml`); it takes effect only with a deploy the Owner approves.
- **Not probed from here:** `internet`, `postgres`/`clickhouse` and `auth` need the web pod's own clients (the egress secret,
  the sandbox API, the team's login), and reading inside the production pod isn't permitted from this session. Supporting
  facts: the egress deployment is 1/1 ready and the node's gVisor label is `ready`. These three are verified at deploy (M4).

### Source
| File | Change |
|---|---|
| `task_lifecycle.py` | `PLANNER_SCHEMA_VERSION`, `NEEDS_SCHEMA`, `NEEDS_RULE`, `planner_needs`, `declared` |
| `mining_work.py` | PLAN and follow-up schemas and prompts; plan and follow-up inserts store v2 needs; `needs_schema` on the plan run |
| `control_missions.py` | INTEL proposals declare needs; stored on the created or proposed `ctl_task` |
| `mission_ops.py` | `probe()` and the 11 probes |
| `k8s/base/56-sandbox.yaml` | Role: get `resourcequotas` (read only) |
| `tests/unit/test_planner_needs_probes.py` | 11 tests (new) |

## M3: readiness gate and the risk register

### The gate (`mission_ops.task_readiness`)

| Kind of item | Outcome |
|---|---|
| Declared need, probe PASS | ready |
| Declared need, probe FAIL or UNKNOWN | **blocked** (C: UNKNOWN never passes) |
| Owner accepted a **non-critical** blocked need | **conditional** |
| Person verified an **UNKNOWN** need (credential, approval) | ready, for 7 days |
| Inferred need (the task's words) | **confirmation item only**, never blocks (D4, F) |
| Team on a Claude Code or Codex plan whose sign-in probe **FAILs** (D-015 D1) | every task of the team **blocked**, critical |

- **The task's state:** BLOCKED if any item is blocked, whatever the others say (D); CONDITIONAL if only accepted items remain;
  otherwise READY.
- **Critical needs** (auth, approval, credential) can never be accepted.

### Where it holds work
- **Team board** (`Work._kick`). Before an agent starts a queued task, its readiness is computed (probes run outside the
  board's lock).
  - A blocked task goes back to `todo` with `hold='readiness'` and the blocker and remedy in its note, plus a feed event.
  - When the needs pass (or are accepted or verified), the next pass requeues it.
- **Control Hub dispatcher.** An agent task whose readiness is BLOCKED isn't dispatched. Its summary says why;
  `readiness_held` counts them.
  - Board-routed tasks carry their declared needs to the board, which applies the same gate.
- **Switch:** `READINESS_GATE=0` turns the gate off. Default on.

### The register (`orchestrator.io_risks`, D-012 Approved)
- **One record per finding**, keyed `readiness:<mission>:<task ref>:<capability>:<value>`. A repeated probe updates it
  (`last_seen`, `seen`, evidence), and a cached probe answer read again isn't counted as a new sighting.
- **Fields (G5 §C):**
  - id, mission, task, layer;
  - title, description, root cause;
  - probability (observed or unverified), impact (the tasks and mission it blocks);
  - severity, priority, critical;
  - detection (which probe, when), countermeasure, responsible;
  - approval rule, status;
  - evidence (the latest probe), verification.
- **Lifecycle:**
  - **open**, to **resolved** when its probe passes (verification = the probe), reopened if found again;
  - **accepted** by the Owner (non-critical only);
  - **resolved** by a person's verification (UNKNOWN only, with their note).
- **Remediation owner** (`responsible`) per capability: Owner, AXoR or the team lead.
- **Raw evidence stays in the diagnostics.** Only readiness writes risks in G5-2; G5-3 adds hq issues, alerts and
  diagnoses.
- **API:**
  - `GET /api/g5/risks?mission=&status=`
  - `POST /api/g5/risks/{id}/accept`
  - `POST /api/g5/risks/{id}/verify {note}`
  - Every write is in `io_audit`.

### Migration and rollback
- **Migration:** a new table `io_risks`, created at start-up (`CREATE TABLE IF NOT EXISTS`), with an index. No column on
  existing tables (`mw_tasks.hold` takes the new value `readiness`).
- **Rollback, either:**
  - set `READINESS_GATE=0` (no code change);
  - or revert the M3 commit, then requeue tasks left on `hold='readiness'` with
    `UPDATE mw_tasks SET status='queued', hold=NULL WHERE hold='readiness'`.
- **`io_risks`** can stay or be dropped: nothing else reads it.

### Source
| File | Change |
|---|---|
| `orchestrator.py` | `io_risks`; `risk_upsert`, `risk_resolve`, `risk_accept`, `risk_verify`, `risks`, `risk`; routes |
| `mission_ops.py` | `task_readiness`, `gate_text`, `REMEDY`, `CRITICAL`, `GATE_ON`, risk writes |
| `mining_work.py` | `_readiness()`; `_kick` holds and releases |
| `control_dispatch.py` | `_readiness()`; agent tasks held when BLOCKED (`readiness_held`) |
| `tests/unit/test_readiness_gate.py` | 11 tests (new) |
| `tests/unit/test_task_needs.py` | The G5-1 "nothing gated" test becomes G5-2's: declared needs hold, inferred ones don't |

## M4: visibility, seeded SN61, end to end, browser

### Control Hub Overview (G)
- **No new page.** The existing Mission operations console (Control Hub → Overview) gets a **Mission readiness** card,
  built from `mission_ops.gate_view`, read only, with cached probes. It shows:
  - each mission's state (Ready, Conditional, Blocked), with its counts of open, held, conditional and to-confirm tasks;
  - each held task, with each failing need, the probe's state, the remedy and who acts;
  - the risk register (open and accepted), with **Accept** (non-critical only) and **Verify** (UNKNOWN only, with a note)
    buttons calling `/api/g5/risks/{id}/accept|verify`.
- `/api/control/ops` gains a `gate` block.

### End to end on fakes (A13): `tests/unit/test_g5_end_to_end.py::EndToEnd`
1. A v2 plan declares needs.
2. Preflight: the plan login is signed out, Docker isn't provided and the key is unverified, so both tasks are held, with 3
   risks (auth critical, credential critical, docker non-critical).
3. Remediation: sign in (auth PASS), a person verifies the key, a Docker runner appears (docker PASS).
4. Both tasks are released and started in one board pass.
5. A timeout goes to a short retry; a sign-in failure is blocked and not counted.
6. All 3 risks are resolved: docker by its passing probe, the key by the person's verification.

### Seeded SN61 (A8)
- **Synthetic, in the suite** (`SeededSN61`): 9 tasks in SN61's real wording.
  - 0 Docker-declared tasks dispatched.
  - Every held one shows "docker FAIL" and its remedy.
  - The rest ran, including the one whose Docker need was only inferred.
- **Real board** (the 06:50Z copy, 571 tasks; scratchpad `p2/seeded_real.py`, data not committed). Docker was declared on the
  16 tasks the G5-1 hand-check confirmed need it; the docker probe ran unmocked.

  | Measure | Result |
  |---|---|
  | Open tasks | 279 |
  | Open tasks with declared Docker | 11 |
  | **Held** | **11** (exactly those 11, each with blocker and remedy) |
  | Not held | 268 |
  | Confirmation items (inferred, non-blocking) | 25 |
  | Risks open | 11 |
  | Gate time per pass | 36 ms |

### Browser verification (A11)
Setup: an isolated test server from this branch (port 8876, its own data, the fake model), with the earlier Mission
Operations seed, two SN61 tasks with declared needs, both started through the real API
(`POST /api/mining/work/tasks/{id}/start`). The **real board gate held both** and wrote 4 risks.

| Viewport | Result |
|---|---|
| 390 px light | no horizontal scroll (fold closed or open); 2 missions; 2 held rows; 3 risk rows; no console errors |
| 1440 px dark | same, plus both actions through the UI: **Verify** resolved the credential risk ("verified by admin", with the note), and **Accept** on task #22's Docker risk turned that task from held into conditional ("1 held · 1 conditional") |

Found and fixed during this check: after an action, the Overview's redraw closed the register's fold. It now stays as the
viewer left it.

Screenshots are in the scratchpad (`ui/gate-*.png`).

### Source (M3 visibility and M4)
| File | Change |
|---|---|
| `mission_ops.py` | `gate_view()`; `view()["gate"]` |
| `frontend/control-ops.js`, `control-ops.css` | Mission readiness card, risk register with Accept/Verify, verification dialog |
| `tests/unit/test_g5_end_to_end.py` | A13 and A8, 2 tests (new) |

## Test results per milestone

| Milestone | SQLite | Postgres | Other evidence |
|---|---|---|---|
| Base (`g5/phase1` @ `0b7ea0d`) | 911 OK (7 skipped) | 911 OK (5 skipped) | — |
| M1 | 923 OK (7 skipped) | 923 OK (5 skipped) | Corpus replay above: 890 changed decisions, all listed |
| M2 | 934 OK (7 skipped) | 934 OK (5 skipped) | Probes on live cluster answers (12:39:53Z); RBAC gap found and fixed in the manifest |
| M3 + M4 | **947 OK (7 skipped)** | **947 OK (5 skipped)** | Real-board gate (11/11 held), API-path gate on the test server, browser check at 1440 dark and 390 light |
| Corrections A–C, on `main` @ `5862bed` | **982 OK (7 skipped)** | **982 OK (5 skipped)** | Concurrency tests pass on Postgres too (real row-level race) |
| DB Re-check limit, budget safety, probe fix | **1025 OK (7 skipped)** | **1025 OK (5 skipped)** | Staging run 2: checks 4, 5, 6, 8, 9 and 10 pass; 1 to 3 partly, at the authorized boundary |
| Blockers A and B (`c4e63b8`) | 1048 OK (7 skipped) | 1048 OK (5 skipped) | Staging run 3: both blockers reproduced on `2589329`, fixed on `c4e63b8` (S1–S10) |
| + reviews gated, marker on `end(ref)` (`81f9ab5`) | **1049 OK (7 skipped)** | **1049 OK (5 skipped)** | Unit only (after run 3) |
| UNKNOWN audit (`f5fcba5`), Postgres fixture fix (`1057cc1`) | **1059 OK (7 skipped)** @ `1057cc1` | **1059 OK (5 skipped)** @ `1057cc1` | Staging run 4 on `1057cc1`: checks 5, 7, 8, 9, 10 pass |
| `g5/replica-safety` `8a227cd` (separate draft) | **1062 OK (7 skipped)** @ `8a227cd` | **1062 OK (5 skipped)** @ `8a227cd` | Staging run 5 on `8a227cd` |

## Corrections after the Owner's review of 2026-11-11 (§2 A–C)

### A. Concurrent retry idempotency
- **The claim:** `control_dispatch._claim` is one conditional `UPDATE … RETURNING`. It writes `retry_claim` (the retry key
  `ctl:t<id>:retry:<n>`) and `claimed_at` only while the task is still the failed attempt it was read as, and only if no live
  claim holds that key. Of any number of passes (threads, workers, pods on one database), exactly one gets the row back and
  starts the retry.
- **A killed worker** leaves its claim behind. Nobody else starts the retry until the claim is older than `CLAIM_STALE`
  (10 min); then the next pass claims it again and starts it once.
- **Tests** (`test_g5_2_corrections.py::ConcurrentRetry`, run on SQLite and Postgres):
  - 8 threads racing `_claim` on the same snapshot: 1 winner;
  - 2 simultaneous `dispatch()` passes, both made to decide before either claims: 1 start, `attempts` 0 → 1;
  - a worker killed (an uncaught `BaseException`) between claim and start: the claim stays, a second pass doesn't start it,
    and after `CLAIM_STALE` it is recovered with exactly one start.
- **Autoloop's own retries** were already guarded the same way (`UPDATE … WHERE status='working'`). The Control Hub retry was
  the read-then-start path.

### B. Dashboard side effects
- `mission_ops.probe(…, cached_only=True)` never probes. It answers the cached result, flagged `stale` past the 10-minute
  TTL, or UNKNOWN "not checked yet". `task_readiness(…, active=False)` uses only that and writes nothing.
- `gate_view()` (the Overview's GET) uses it. Each item carries `checked` and `stale`; the card shows "checked 14:05", "stale"
  or "not checked yet".
- **Active probes run only** in dispatch preflight (`Work._kick`, the dispatcher) and in the explicit **Re-check**:
  `POST /api/control/ops/readiness/{ref}/refresh`, at most once a minute per mission, button on each mission row.
- **Tests** (`ReadOnlyDashboard`):
  - an Overview read with an empty cache makes **0 sign-in prompts and 0 egress calls**, shows UNKNOWN with no time, and
    writes no risk;
  - Re-check probes for real (sign-in prompt and egress), and the page afterwards still reads only the cache;
  - an expired cached answer is shown as stale, not refreshed;
  - a second Re-check within a minute is refused (429).

### C. Credential verification and approval scope
- **Credentials.** A verification is bound to the credential's **fingerprint** (first 16 hex of sha256 of the server's
  environment variable of that name, never the value).
  - A changed or newly set value voids it.
  - It expires after 7 days, or **24 hours** when the server can't see the credential (fingerprint "absent", so no change
    could be noticed).
  - Verify is refused for anything but a credential whose probe said UNKNOWN.
- **Approvals of external actions** use their own action: `POST /api/g5/risks/{id}/approve {action, payload_sha?}`.
  - **Administrators only.**
  - Bound to the risk's **mission**, its **task**, the **action** named, and the task's **payload** (sha256 of title, detail
    and declared needs). `payload_sha` must match what the approver saw.
  - **Single use:** consumed when the task starts (board start loop or dispatcher), after which the next run needs a new
    approval and the risk reopens.
  - **Expires** after 24 hours.
  - **Verify can't stand in for an approval.** The old generic 7-day verification no longer authorizes anything but that
    credential.
- **Tests** (`Scope`, `ApprovalUsedByTheStart`):
  - a credential is READY after verification and BLOCKED after the value rotates;
  - expiry blocks again;
  - an unseen credential gets 24 hours;
  - verify is refused for an approval (409);
  - approve is refused for non-admins (403) and for a payload hash the approver didn't see (409);
  - an approval for task 1 doesn't cover task 2;
  - editing the task voids the approval;
  - consume works once, and the next run is blocked with the risk reopened;
  - an expired approval blocks;
  - on the board, the start that the approval allowed consumes it.

### Migration (corrections)
Two nullable columns on `ctl_tasks`: `retry_claim`, `claimed_at`. Nothing else.

## Budget safety (Owner decision 2026-11-11, after the 199-run staging incident)

**The problem.** `orchestrator.decide()` called a budget refusal HOLD, but Autoloop requeued it at once, and the board's start
gate only watched the team's own 24-hour budget. One task under an exceeded global limit restarted 199 times in 38 seconds.

**The correction.**
- **`agent_core.preflight(owner, system, agent_key, ref, team, corr, contract)`** answers "would this work be refused right
  now?"
  - It uses over()'s own accounting and matching: the owner's daily cap, `_matching`, `_spent`, and the system guards (the
    team's 24-hour budget).
  - It takes the scope from the caller, so it works before a run exists, never reads the thread's active run, and writes
    nothing.
  - Alert-only limits never refuse.
  - The refusal names scope, key, limit id, label, tokens, spent and period, plus `release`: "reset" (day: local midnight;
    month: the 1st) or "raise" (total), with `release_at`.
  - `per_call_caps()` lists the per-call limits a scope falls under.
- **Board start loop** (`Work._kick`): before starting a queued task, `_budget_holds()` runs the preflight with the scope the
  run will have (system `teams`, agent `teams:<id>`, team `comp:<id>`, the mission it correlates with, contract ref
  `mwt:<task>`).
  - A refused task gets a **persistent hold**: `status='todo'`, `hold='budget'`, and `hold_info` (new column) with the full
    refusal and its release condition.
  - It is never started, and `_enqueue` refuses held tasks (Director, autopilot).
  - A held task is released only when a **fresh preflight passes**. A **per-call** hold also needs one of its per-call limits
    changed: a new day doesn't make a call fit.
- **Autoloop** (`failed()`, budget class): the same hold, recording the refusing limit or the per-call breach. **No
  requeue**, not counted (`fails`/`retries` unchanged), and the event says so.
- **Control Hub dispatcher:** the same preflight before an agent task starts. A refused task isn't dispatched
  (`budget_held`), with the reason in its summary, and is never retried (`decide()` → hold).
- **Agent performance:** a budget refusal is canonical `budget`, not the work's own. It goes to the reliability bucket, never
  against the agent.

**Tests** (`tests/unit/test_budget_safety.py`, 13 + fixture tests, SQLite and Postgres):
- a global owner limit blocks every team;
- system and mission limits block matching work only;
- team, agent and contract limits block only their own work;
- alert-only limits never block;
- daily and monthly limits release at their reset;
- a total limit holds until raised;
- a per-call refusal waits for a changed limit, not a reset;
- the Director and autopilot can't requeue a held task;
- repeated dispatcher passes start nothing, and a raised limit dispatches once;
- a refusal isn't the agent's fault;
- **the 199-run regression:** an exceeded global limit and 50 board passes give **0 starts and one persistent hold**;
- a run refused mid-task: **1 run in all** over 50 passes, then raised → released → started once.

**Staging run 2:** 6 forced starts in 60 s under the refusing limit gave **0 runs**; raising the limit gave exactly 1.

**Migration:** `mw_tasks.hold_info` (TEXT, nullable). Rollback SQL now also covers budget holds:
`UPDATE mw_tasks SET status='queued', hold=NULL, hold_info=NULL WHERE hold IN ('readiness','budget')`.

## Budget verification and cross-replica limits (Owner review before PR #5 merges, Blockers A and B)

### Root causes
- **A. Fail-open verification.**
  - `agent_core._safe()` (the ledger's "never stop a run" wrapper) also wrapped `over()`, `preflight()` and `per_call_caps()`.
    Any exception there (database, a system guard) became None, which every caller read as ALLOW.
  - Guards that threw were skipped with `continue`.
  - `per_call_caps()` turned an error into `{}` ("no per-call limit"), which released per-call holds.
  - `_budget_holds()` returned "nothing to hold" when the owner couldn't be read.
  - A failed `begin()` left no run on the thread, so `over()` had no scope and allowed every call.
  - Staging run 3 on `2589329`: a new task and an already-held task both started under an exceeded limit while the limits
    couldn't be read.
- **B. Per-process limit cache.**
  - `Core.limits()` and the owner's cap were cached per process for 30 s. `set_limit()`, `drop_limit()` and `set_cap()`
    dropped only their own process's copy.
  - Another replica enforced a lowered or deleted limit up to 30 s late, and a raise as late.
  - The team guard memoised its whole answer for 5 s per process, budget included.
  - Staging run 3 on `2589329`: a task queued 1 s after a lower started and ran.

### Decision model
`agent_core.preflight()` (before work) and `over()` (before each model call) now share one decision, `Core._verdict()`:

| State | preflight() | over() / llm._gate | Board | Dispatcher |
|---|---|---|---|---|
| ALLOW (verified) | None | None | may start (only tasks with ALLOW in this pass) | dispatches |
| REFUSE (hard limit reached) | refusal dict, `decision: "REFUSE"` | the limit's message | budget hold (`hold='budget'`, `hold_info` = refusal) | not dispatched, summary says why |
| UNKNOWN (couldn't verify) | `unknown()`: `decision: "UNKNOWN"`, `error`, `checked_at`, `release: "verify"` | `VERIFY_STOP` | **verification hold**: `hold='budget'`, `hold_info.decision='UNKNOWN'` + error + time | not dispatched, one history line with the error; no attempt used |

- **UNKNOWN is the budget class everywhere.**
  - `VERIFY_STOP` contains "token budget", so Autoloop, `decide()`, `fail_class` and Mission Control all read it as budget:
    hold, not the agent's fault, no retry.
  - It carries no exception text. A "connection timed out" or "usage limit" in it would have been read as transient or quota,
    and retried. The error goes to the log and the hold.
- **Release only after a fresh authoritative ALLOW.**
  - A verification hold that can now be read but is refused becomes that refusal.
  - A per-call hold also needs `per_call_caps()` readable and changed.
  - The Autoloop tick now also kicks boards whose only tasks are budget-held, so holds get checked again.
- **Still allowed:** an acknowledged unlimited policy and an unset one, as before. An outage is never authorization, whatever
  the policy.
- **Alert-only limits never refuse.** Alerts and the hit record are side effects whose errors never decide.
- **Every start path is checked:**
  - Board (`_kick`): queued tasks are re-checked in the same pass, so a task the Director requeues (`hold_ok`) is held again.
  - Autoloop's budget branch.
  - Dispatcher: new tasks, plus **retries and corrections, checked before the claim** (they were unchecked).
  - Gateway: every model call; a failed `begin()` now refuses its calls.
- **Authoritative reads (B).**
  - Every decision reads `ac_limits` and the owner's `ac_budget` row from the database (one indexed read each). The cache
    remains only for alert settings and display.
  - The team guard reads the team's budget every time and memoises only its spend (5 s, at the gateway, keyed by the budget
    read). A preflight reads both fresh.
  - **No versioning or invalidation protocol was needed.**

### Files changed (code `c4e63b8`, then `81f9ab5`)
| File | Why |
|---|---|
| `backend/app/agent_core.py` | `_verdict()` (the one decision; raises when it can't decide); `over()` and module `over()`, `preflight()` and `per_call_caps()` fail closed; `unknown()`, `is_unknown()`, `VERIFY`, `VERIFY_STOP`; `begin()` leaves an `unverified` marker on failure; per-call check from over()'s read, before the ledger write; `limits()` and `cap()` read fresh; the `lims` cache removed |
| `backend/app/mining_work.py` | `_budget_holds()` returns holds, UNKNOWN→REFUSE re-holds, releases and the ALLOW set; `_kick` starts only ALLOW tasks; `budget_hold_info()` records UNKNOWN; `_budget_note()` for verification holds; the team guard's memo keyed by budget |
| `backend/app/mining_autoloop.py` | The tick also re-checks boards whose only tasks are budget-held |
| `backend/app/control_dispatch.py` | `_budget_hold()` / `_budget_hold_retry()`: REFUSE and UNKNOWN for new tasks, retries and corrections, no attempt used |
| `backend/app/orchestrator.py` | Drops its pop of the removed cache after deleting a finished mission's limit |
| `81f9ab5`: `mining_work.py`, `agent_core.py` | Board **reviews** start only with ALLOW in the same pass (under REFUSE/UNKNOWN they wait in `checking`, re-checked, no run; before, a refused review settled to the user's review); `end(ref=…)` clears a failed `begin()`'s marker, as the board closes runs by ref |

### Migrations
None. A verification hold uses the existing `hold='budget'` and `hold_info` (from `2589329`); old `hold_info` rows without
`decision` read as REFUSE. No data is rewritten. Rollback SQL is unchanged.

### Tests (`tests/unit/test_budget_verification.py`, 24)
- **A:**
  - a database outage during the gateway check refuses the call and recovers;
  - unset and unlimited policies allow, but an outage is not authorization;
  - a guard that throws is UNKNOWN;
  - a failed `begin()` leaves the run unverified;
  - unreadable per-call limits stop the run;
  - failing alerts never decide;
  - on the board: an outage holds and starts nothing over 50 passes, with error and time, not counted;
  - UNKNOWN → REFUSE once readable;
  - mid-run UNKNOWN holds uncounted and restarts exactly once after ALLOW;
  - the hold survives a restart;
  - the Director can't requeue past UNKNOWN;
  - an unreadable owner is UNKNOWN;
  - unreadable per-call caps never release;
  - the tick re-checks held-only boards;
  - a review doesn't start while UNKNOWN or REFUSE, and starts once on ALLOW;
  - dispatcher: UNKNOWN dispatches nothing, uses no attempt and writes one history line;
  - a retry is checked before its claim;
  - UNKNOWN classifies as a budget hold in every vocabulary, against hostile error text.
- **B (two Core instances, own connections, warm caches):**
  - lower, raise, delete and recreate apply on the other at once;
  - the owner cap too;
  - the gateway of a run on B sees A's change before the next call;
  - a team budget lowered on one replica applies on the other;
  - **both replicas running board passes at the same time:** 0 starts after a lower, exactly 1 after a raise. The two
    replicas share one `Work` object and its lock, so this proves separate budget memory, not that starts are exclusive
    across processes. The cross-process evidence is staging run 3, and the board-start claim is a named risk.
  - There is no two-instance simultaneous `dispatch()` test. Cross-replica dispatcher evidence is `ConcurrentRetry`
    (atomic claim) plus the new budget check before the claim.
  - **All 5 fail on `2589329`** (run against an exact copy of it).
- **C:** `test_budget_safety.py` unchanged (199-run regression, mid-run refusal, per-call, Director, dispatcher), except
  the fixture split and a stronger Director check (the real `_enqueue(hold_ok=True)`, then 10 passes: still held).

## Final stabilization (Owner decision of 2026-11-11): UNKNOWN audit and gateway coverage

### Gateway coverage (does UNKNOWN reach every model call?)
- **Gated:** every agent model call goes through `llm.completer()` (each turn) or `llm.structured()`, and both call
  `_gate()` → `agent_core.over()` before the call. That covers the Anthropic API, OpenAI, OpenRouter, Copilot, local
  endpoints, the Claude Code CLI, Codex (CLI and the MCP bridge) and the Copilot CLI.
- **Not gated by the budget core (G-38):**
  - the sandbox inference proxy, used by miner code and `rlm` sub-calls; it has its own `SANDBOX_DAY_USD` cap;
  - knowledge embeddings (`knowledge_media._post`);
  - the host Workbench's Claude Code (recorded after the fact by `agent_core.record`);
  - the sign-in probe's one-line prompt.

### Consumers of the shared decision

| Consumer | Never authorizes a call | Never counts against agents | No retry loop | Holds kept, nothing released silently | Recovery after verification succeeds |
|---|---|---|---|---|---|
| **Competition teams** (board) | Start only on ALLOW; reviews too (`81f9ab5`) | `fails`/`retries` unchanged | Held, re-checked each pass, no run | `hold='budget'` + `hold_info.decision='UNKNOWN'`; Director requeue re-held | Automatic: fresh ALLOW releases; started once |
| **Autoloop** | Budget class → hold, not requeue | Not counted (budget branch) | Hold, not retry | Hold persists through restarts (run 3) | Tick re-checks boards with only held tasks |
| **Director** | Report run starts only on ALLOW (`f5fcba5`) | — | At most one check per tick, no run | — | Next tick |
| **Control Hub** | Dispatch, retry and correction checked before start/claim | `_failing` ignores budget; no attempt used | Held each pass, one history line | Summary stays; nothing dispatched | New tasks automatic; a task refused **mid-run** stays failed for a person (G-40) |
| **Mission Control** | Gateway refuses; stage stops | **No error event, no attempt; never dead-lettered** (`f5fcba5`; before: counted, and could reach `_dead`) | Re-check at most once a minute (`VERIFY_RETRY`) | `failure='verify'` pause | **Automatic only for `failure='verify'`** after a fresh ALLOW. REFUSE → budget pause for a person. Deadline passed or budget used up → stays paused. **A person's pause, including one placed over a verify pause, is never resumed by AXoR.** |
| **Workforce** | Gateway refuses each call | Budget-stopped runs left out of router stats and scorecards (`NOT_BUDGET_STOP`; before: counted as model failures) | No retry: the assignment or mission fails with the reason | — | Under Mission Control: its verify pause. Standalone: a person re-runs it (G-40). |
| **Agent Swarm** | Gateway refuses each call | Left out of router stats; an all-budget-stopped contract **uses no attempt and isn't reassigned** (before: reassigned and counted) | Bounded | — | As Workforce |

**Tests** (`tests/unit/test_unknown_audit.py`, 10; plus `test_budget_verification.py`, 24):
- missions: UNKNOWN pauses uncounted ten times over and is never dead-lettered;
- an engine's UNKNOWN is a pause, not a failed attempt;
- auto-resume only after ALLOW and at most once a minute;
- REFUSE on re-check → a person decides;
- a person's pause, and a person's pause over a verify pause, never resumed;
- a gateway REFUSE isn't an error;
- past the deadline it stays paused;
- Workforce and Swarm run tables: budget stops aren't model failures;
- Swarm: no attempt used, no reassignment;
- Director: no report run while UNKNOWN or REFUSE.

### Board claim, liveness and readiness: separate draft branch `g5/replica-safety` (`8a227cd`, stacked on PR #5)
- **Board claim:** queued → working by one conditional update. One open review run per task, by a unique index. A claim with
  no run is requeued after 120 s.
  - `test_board_claim.py`: two `Work` objects with their own locks and connections give 1 run per task over 10 rounds of 8.
    On `1057cc1` that test fails with 2 runs per task.
  - Staging run 5: 0 duplicates in 10 rounds, against 8 of 8 tasks doubled before the fix.
  - Limits: the claim gives one run per task. It doesn't make agent slots or `parallel` global across replicas, and start-up
    still resets every running run (G-37). **One web replica stays required**, and `k8s/deploy.sh` refuses a manifest with
    more.
- **Liveness and readiness:**
  - `/api/live` is the process only. `/api/ready` checks that the database answers within 3 s (one check in flight), else
    503, and reports the error kind only, since it's public.
  - Probes: readiness → `/api/ready`; liveness and startup → `/api/live`. `redeploy.sh` waits for ready.
  - `/api/health` is unchanged.
- **Why a separate PR:** these changes are replica safety, not G5-2's budget or readiness work. With one web replica and
  Recreate (as in production today), the board race can't happen, so PR #5 is safe to merge without it. The health change is
  independent: without it, a database outage keeps sending traffic to the pod (no restart either way), which is the status quo.

## Acceptance criteria A1–A13 (G5_PHASE2_PROPOSAL.md, with the Owner's clarifications)

| ID | Criterion | Evidence | Status |
|---|---|---|---|
| A1 | Sign-in failures don't count against agents | Corpus replay: 184 runs counted → not counted; `AgentFault` tests (outcomes, optimize) | Met on the 06:50Z copy |
| A2 | Only transient causes auto-retry; immediate vs delayed (A) | `Table` tests; corpus replay lists all 890 changed decisions | Met; provider/tool unexercised by real data |
| A3 | Idempotency | Atomic claim in the database; 8-thread claim race, 2 concurrent dispatcher passes, killed worker (`ConcurrentRetry`) | Met (SQLite and Postgres) |
| A4 | Planner schema v2, v1 still accepted (E) | `PlannerSchema`, `PlannerOnTheBoard` | Met |
| A5 | Only declared needs block (D4, F) | Gate tests; Control Hub and board tests; SN61 inferred-only task ran | Met |
| A6 | Probes reflect the real environment (B, C) | Probe code on live cluster answers: vm, gpu, docker, registry, ram, credential, approval | Partly: internet, services and auth need the web pod (verified at deploy) |
| A7 | Critical failure → BLOCKED whatever the aggregate (D) | `test_critical_failure_blocks_whatever_the_rest_says`; acceptance only for non-critical | Met |
| A8 | Seeded SN61: no Docker task reaches an agent | Synthetic test; real board: 11 of 11 held, each with its fix | Met on the copy |
| A9 | Sign-in preflight | Probe tests (FAIL, PASS, quota, API); gate blocks the team; E2E step 2 → 3 | Met with fakes; **real login check not run** (needs the pod) |
| A10 | Risk records complete, linked | `test_declared_failing_need_blocks_and_records_a_risk` (all D-012 fields); impact links tasks and mission | Met |
| A11 | Visibility, browser-checked | Mission readiness card; 1440 dark and 390 light; actions; no errors or scroll | Met on the test server |
| A12 | Regression | Full suite on both databases per milestone (table below) | See below |
| A13 | Scripted end to end | `EndToEnd` test | Met with fakes |

## Remaining blockers and security risks
- **Not deployed, not run against live production.** The internet, services and sign-in probes and the gate on live data
  are only proven when the Owner deploys.
- **The sign-in probe spends a tiny prompt** on each plan login, at most once per 10 minutes per team, only while that team
  has queued or held tasks, or on an explicit Re-check. Since the corrections, opening the Overview spends nothing.
- **The gate makes the board's start pass slower**: probes run before the lock, and the sign-in check can take seconds when
  its cached answer has expired. Measured 36 ms on the real board copy with cached probes; not measured on a cold cache.
- **Credentials:** a verification is voided by a changed value, but a credential that is revoked upstream with the same
  value isn't noticed until it expires (7 days; 24 hours if the server can't see it).
- **RBAC change:** the web role may now *get* `resourcequotas` in `axor-sandbox` (read only). This needs a deploy.
- **Budget decisions now stop work when the ledger can't be read** (Blocker A). A database problem holds new work and refuses
  model calls until a fresh check passes. It no longer lets work through unmetered. That is intended, but an outage of the
  `ac_limits`/`ac_budget` reads now pauses agent work everywhere.
- **Board starts aren't claimed in the database** (found in staging run 3). Under a per-process lock, two replicas could
  start the same queued task. Production runs one web replica, and run 3 saw none (every task ran once). It needs a
  `_claim`-style conditional update before the board runs on several replicas.
- **`/api/health` stays 200 when Postgres is down** (staging run 3). Not changed here.
- **A Control Hub task refused mid-run** (REFUSE or UNKNOWN) stays failed until a person retries it, as budget failures did
  before. It isn't restarted automatically after recovery; a retry goes through the pre-dispatch check.
- **Other systems receive a gateway UNKNOWN as a budget-class failure**: Mission Control, Workforce, Agent HQ, Company, Long
  tasks. Their handling wasn't audited in this change. Missions pause on budget and don't resume by themselves after the
  check recovers.
- **The team guard's spend memo** can lag the team's 24-hour spend by up to 5 s at the gateway (accounting lag, not a limit
  change). A preflight has no lag.
- **SN61 itself remains not ready:** live scores 0.05 and 0.24 against 0.8 (readiness report §6). The gate now holds its
  Docker tasks instead of letting agents fail on them.
