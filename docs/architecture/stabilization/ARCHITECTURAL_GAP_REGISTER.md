# Architectural Gap Register, 2026-11-11

Each gap is a difference between [TARGET_ARCHITECTURE.md](TARGET_ARCHITECTURE.md) and [CURRENT_STATE.md](CURRENT_STATE.md).
Fixing a gap is planned in [IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md). The roadmap and decisions D-004 to D-008 were
approved on 2026-11-11 (the Owner delegated the decision). Status on 2026-11-11 ~09:30: G-00 closed; G-11 in progress; G-02 and G-22 fixed in
source, not deployed; G-12 partly addressed.

**Severity**

| Level | Meaning |
|---|---|
| P0 | Blocks the first operational milestone, or risks data, money or safety. |
| P1 | Makes mission results unreliable or unmeasurable. |
| P2 | Complexity or consistency debt. |

**Category**

| Code | Meaning |
|---|---|
| broken | Broken functionality |
| dup | Duplicate functionality |
| disc | Disconnected functionality |
| cplx | Unnecessary complexity |
| miss | Missing capability |
| incons | Architectural inconsistency |
| risk | Security or reliability risk |
| perf | Performance bottleneck |

**Evidence class**

| Code | Meaning |
|---|---|
| SRC | Verified in source code. |
| PROD | Verified in production (observed this session). |
| DOC | Documented but not verified. |
| SUSP | Suspected problem. |
| MISSING | The capability does not exist. |

**Fix** means: preserve, fix, consolidate, reintegrate, improve, develop, or deprecate (subject to approval).

## P0

### G-00 · Legacy Compose AXoR still running and public · risk · PROD · **CLOSED 2026-11-11**

**Closed 2026-11-11.** The Owner stopped all 5 containers; each now has restart policy `no` and shows Exited. `http://<host>:8000/`
answers `301 → https://<host>/`: the edge's redirect owns the port again. The containers and their volumes are kept.

**Finding.** The containers `subnet-scout`, `scout-runner`, `scout-drive`, `scout-push` and `scout-docker-proxy` have been up
for 8 days. They run the image from 2026-10-30, before the k3s cutover, with restart policy `unless-stopped`.
`subnet-scout` listens on 0.0.0.0:8000.

**Impact.**
- **[SUSP]** A second AXoR instance with week-old data runs its own background loops: collector, mining autopilot, missions and
  Agent HQ. It may spend model credits with the old keys.
- **[SUSP]** It answers on a public port with an old code base and old user accounts.
- **[SUSP]** The edge's intended redirect from :8000 to HTTPS cannot bind.

**Fix.** Deprecate, with Owner approval. First read its logs to see whether it does any work. Then
`docker update --restart=no` and `docker stop`, without removing it, so it can be brought back.

### G-11 · No scheduled backup of production data · risk · PROD/SRC · **IN PROGRESS**

**Progress 2026-11-11.** The first production backup is `/var/lib/axor/backups/20261111T065017Z` (306 MB, Postgres dump
52 MB). Its restore test passed after the G-22 fix: 281 tables, every SQLite copy reports integrity `ok`. The nightly timer
(`k8s/backup.sh --install`) is not installed: the permission policy refused it for Claude Code, so the Owner installs it.

**Finding.** Production data is in the in-cluster Postgres (PVC). No `pg_dump`, CronJob, cron entry or timer exists. The only
copies are the cutover copy (2026-10-30) and the SQLite file at the 2026-11-10 switch.

**Impact.** A lost volume or a bad migration is unrecoverable. Phase 0 of the directive ("back up, rollback point") is not met.

**Fix.** Develop: a nightly `pg_dump` CronJob to a host path with retention, plus a tested restore.

### G-01 · Mission Control does not own competition missions · incons · SRC

**Finding.** Competition work runs as predefined missions `comp:N` (`control_missions.py`, `ctl_fixed`, `ctl_tasks`). These
never enter `missions.STAGES`. Only custom missions `mx:N` with `engine=mining` go through Mission Control. Even then they only
send a note to the team's planner (`missions.py:690-693`).

**Impact.** Decision 2 ("Mission Control is the authoritative owner") does not hold for the primary initiative. The outer
loop, its evaluation and its decision (continue, replan, improve, deliver) do not exist for continuing competition work.

**Fix.** Reintegrate. Give each competition team one long-running `mx` mission, or one `mx` row per `comp:N`, that owns the
objective and criteria. The team's board stays the inner loop. Mission Control reads its results through the contract. This
needs a decision record (D-004 proposed).

### G-02 · Board tasks carry no mission key; attribution by time window · broken · SRC · **FIXED IN SOURCE, NOT DEPLOYED**

**Fixed in source 2026-11-11 for Mission Control** (D-006 and its amendment); `tests/unit/test_mission_ref.py` covers it. Team-side
readers are unchanged by design: the board, Mission Ops' competition cards and global activity still count every task on a team's
board, `mx:`-stamped ones included. The board's task output and `mission_ops._board` now carry each task's ref. Production impact so far:
none. The backup copy shows 0 rows in `mx_missions`, so the time-window path never ran in production.

**Finding.**
- `mw_tasks` has no `mission` column (`mining_work.py:358-361`).
- `Missions._child` and `_collect` treat **every team task created after `child_started`** as the mission's own
  (`missions.py:721-734`, `:777-783`).
- `_stop_child` cancels those same tasks (`:743-748`).
- `control_missions._to_board` finds the board task it just created by title (`:406-408`).

**Impact.**
- **[SUSP]** Tasks that Autoloop, the Director or Mission Intelligence create in the window count toward the mission, and
  cancelling the mission cancels them.
- **[SUSP]** Two `mx` missions on one team in overlapping windows each claim the other's tasks.
- **[SUSP]** Path A and Path B count the same task twice.
- **[SUSP]** A dedupe-merged task leaves `ctl_tasks.ref` empty.

**Fix.** Fix. Add a nullable `mission` column (ref `mx:N` / `comp:N`) to `mw_tasks`. `PlanIn` and `TaskIn` carry it, the lead's
plan stamps it, and Mission Control filters by it instead of by time. The migration is additive.

### G-03 · Mission completes on timeout with open work · broken · SRC

**Finding.** `_child` returns "done" once `MINING_WAIT` (6 h, `missions.py:75`) has passed, even with tasks still open
(`:733-734`). The mission then verifies and delivers whatever exists.

**Impact.** A mission can be delivered and scored with its work unfinished. That breaks "never claim completion without
evidence".

**Fix.** Fix. When the wait expires, the mission goes to a decision (extend, replan or deliver partial) recorded in
`mx_requests`, instead of "done".

### G-04 · Competition results are not independently measured in the mission path · miss · SRC

**Finding.**
- Path A verification is a second model reading task summaries (`missions.py:807-836`).
- Board-path benchmarks are scores the agents report through `record_benchmark`. AXoR checks the metadata against the frozen
  manifest only, and no sandbox run is required (`mining_release.py:302-334`).
- Independent sources exist but are not connected to mission verification: the Lab's `runs.jsonl` scoring
  (`mining_lab.py:46-53`), the evaluator or miner ingest (`mining_command.py:458-498`) and the rivals harvest.

**Impact.** "Results are independently tested" and "actual score where available" (acceptance rows Evaluation and Performance)
are not met. `mission_evidence.decide()` adopts techniques on numbers the agents reported.

**Fix.**
- Fix: a benchmark result counts as *measured* only with a sandbox run id (`mw_sbx`) or a Lab experiment id behind it.
  Otherwise it stays *reported*.
- Reintegrate: Mission Control's verify step reads the latest measured score and leader comparison for its competition, with
  source, timestamp, method and suite hash, and shows *unknown* when there is none.

### G-12 · Deploy gate and production run different databases · risk · SRC · **PARTLY ADDRESSED**

**Progress 2026-11-11.** `tests/run-unit.sh --postgres` runs the suite on a throwaway `pgvector/pgvector:0.8.6-pg16`, the
production image. Result: all 856 pass (with mission refs). An earlier full run, before the mission-ref tests were added, had 1 order-dependent error out of 843 (G-24). The `redeploy.sh` gate still runs SQLite only.
Switching the gate adds about 7 minutes to every deploy and affects every session's deploys, so it is proposed, not switched.

**Finding.** `tests/run-unit.sh` (the redeploy gate) runs the 827 tests on SQLite. Production runs on Postgres. Postgres-only
errors (42601, 42702) have reached production before (CURRENT_STATE §6).

**Fix.** Improve: run the suite against a throwaway Postgres in the gate. A recipe already exists in `k8s/stack/README.md`.

### G-22 · A production dump didn't restore with a plain `pg_restore` · broken · PROD · **FIXED IN SOURCE, NOT DEPLOYED**

**Finding.** `axor_compat.f32vec` (`vector_pg.py`) casts with `::vector` but had no `search_path` of its own. `pg_restore` runs
with an empty search path, so re-computing the generated `emb` column during `COPY ex_vecs` failed. The first production
backup's restore test failed on exactly this.

**Fix.**
- The function now carries `SET search_path TO axor_compat, public`.
- `backup.sh` restores in three steps: schema, then set the function's search path (a no-op on newer dumps), then data. Older
  dumps therefore also restore.

**Verified.**
- Production's dump restores with the three-step procedure.
- After the source's `CREATE OR REPLACE`, a re-dump restores with a plain `pg_restore`.
- 501 of 501 `ex_vecs` rows get their `emb`.

Production keeps the old function until a deploy runs `vector_pg.ready()`.

## P1

| ID | Gap | Cat | Evidence | Fix |
|---|---|---|---|---|
| G-05 | `orchestrator._derived` scores a board-task run **100** once its task is done (`orchestrator.py:622`). Evaluation coverage therefore counts review approval as validation. | incons | SRC | Fix: score from a measured result when there is one; otherwise mark the run "reviewed, unmeasured", not 100. |
| G-06 | At least 7 independent promotion paths: `evolution.py`, `mining_upgrade.py`, `mining_improve.py`/`mining_evolve.py` (promotes and rolls back without the user in "self" mode), `workforce.py` self-improvement, `agent_studio.py`, `company_agents.py`, `marketplace.py`. `evolution.py` says it does not take over their rules. Decision 7 is not met. | dup / incons | SRC/DOC | Consolidate: each path *proposes*; promotion goes through one `evolution.promote()` gate (evidence, policy, version, rollback, audit). Existing UIs stay. |
| G-07 | Two task-state models. `task_lifecycle.stage()` covers `ctl_tasks` only; board tasks keep their own statuses. `mission_ops.STATES` maps both, a third vocabulary. | incons | SRC | Consolidate: `task_lifecycle.stage()` becomes the one mapping for both, and `mission_ops` reads it. |
| G-08 | Engines also accept missions directly (`wf_missions`, `sw_swarms`, `ia_tasks`, `co_projects`, `og_missions`, `team_cycles`). Decision 5 says engines are not mission authorities. | dup | SRC | Preserve the direct entry points for now, but label them "runs" in the contract, not missions. Revisit after the milestone. |
| G-09 | No single Competition Adapter interface. Rules, APIs, submission format, harness and network needs are spread over `mining*.py`, `ridges.py` and the `mining_rivals` and `mining_sources` modules. | disc | SRC | Develop a thin interface (`adapter.observe/score/leader/submit_request`) over existing calls. No logic moves. |
| G-10 | Approvals live in 4 tables (`mx_requests`, `og_requests`, `co_approvals`, `amp_approvals`) with 3 aggregate views (`command.py`, `governance.py`, `mission_ops.decision_queue`). About 10 consoles read the same records. | dup / cplx | SRC | Consolidate the views: name one canonical decision queue (`mission_ops.decision_queue`) and link the others to it. The tables stay. |
| G-13 | Every agent loop runs as a thread in one `web` pod (`main.py:372-392`). Each deploy interrupts all work; `restart_recovery.py` cleans up. | risk / perf | SRC | Preserve for now. Measure how much work deploys cut off before deciding on separate workers. |
| G-14 | Budget enforcement: in-flight token counting and cache-read exclusion were added 2026-11-11 and are deployed. The 68M-vs-5M overrun is explained from code only. | risk | SRC/SUSP | Verify on production data (CURRENT_STATE §7), then close. |
| G-15 | No end-to-end mission test. All 856 tests are unit tests with fake services; `test_mission_ref.py` covers the launch → plan → count/collect/cancel chain with stand-ins, not one full run. | miss | SRC | Develop one scripted E2E: a fake competition through Path A and Path B to delivery. |

## P2

| ID | Gap | Cat | Evidence | Fix |
|---|---|---|---|---|
| G-16 | Table-prefix collisions: `mo_` (`mining_ops` and `mission_ops`), `ml_` (`mining_loadout` and `mining_autoloop`). Columns are added to another module's table (`mining_autoloop.py:102` adds to `mw_tasks`). | incons | SRC | Document the owners in the contract. No renames. |
| G-17 | Parallel run, span and event tables per system (`mw_`, `wf_`, `sw_`, `mh_`, `ia_` runs, spans, events) beside the `ac_runs` ledger. | dup | SRC | Preserve; `ac_runs` + `corr` is the canonical join. Nothing new writes outside it. |
| G-18 | Six organizational models: Agent HQ, Workforce (CEO + teams), Company OS, Organization/Org HQ, Control Hub tree, Portfolio. | dup / cplx | SRC/DOC | Keep Organization as the source of structure; flag the rest for an approved deprecation review after the milestone. |
| G-19 | `axor-machines/dev-kali` pod stuck in Unknown. | broken | PROD | Clean up with approval. |
| G-20 | Sandbox network isolation and egress not re-verified since 2026-11-09. | risk | DOC | Run `test_sandbox_internet` plus a live probe in Phase 2. |
| G-23 | Production holds no measured competition result of any kind. Backup of 2026-11-11 06:50Z: 0 frozen releases (so all 14 `mw_bench` rows are non-comparable), 0 ingest metrics, 0 Lab experiments, 0 evolution trials, 0 upgrade versions, 0 hard token limits. Both teams' rank is UNKNOWN ("no ranked miner under your keys"). | miss | PROD (backup copy) | Owner: register a miner and freeze a release candidate per team. Without them, no milestone row for Evaluation, Performance or Evolution can pass. |
| G-24 | `test_knowledge_rag.test_passage_vectors` failed in 1 of 2 full Postgres runs, and passes alone. Suspected cause: `vector_pg._state` caches readiness by `id(connection)`, which can be reused by a new connection with another schema. | broken (tests) | SUSP | Key the cache by connection and schema, or clear it per AuthDB. Production has one connection, so it is not affected. |
| G-21 | Before this audit, the architecture lived only in docstrings and private notes. | miss | SRC | Fixed by these documents (pending Owner approval). |

## Verified vs suspected summary

| Class | Gaps |
|---|---|
| Verified in production | G-00 (closed: stopped, 301), G-11 (no schedule found; first backup verified), G-19, G-22 (restore failure), G-23 (backup copy) |
| Verified in source | G-01, G-02 (mechanism), G-03, G-04, G-05, G-06, G-07, G-12, G-13, G-15, G-16, G-17 |
| Suspected consequences, to confirm with the CURRENT_STATE §7 queries | G-14, G-24. G-02 impact resolved: 0 missions ever ran Path A. G-00 impact: logs showed no agent work. |

## G5 gaps (from [G5_ASSESSMENT.md](G5_ASSESSMENT.md), accepted by the Owner 2026-11-11)

| ID | Gap | Type | Evidence | G5 phase (D-014) |
|---|---|---|---|---|
| G-25 | No preflight and no PASS/CONDITIONAL/BLOCKED readiness gate. Environment problems are only classified after a run fails (`missions.py:100`); `mission_ops.readiness()` is a console scorecard that gates nothing. | miss | SRC | G5-2 |
| G-26 | Five failure vocabularies: `mining_autoloop.CLASSES`, `intel_layers.fail_class`, `orchestrator.RECOVERY`/`sbx_class`, `missions.FAILURES`/`RECOVERY`, `control_dispatch.RETRY`/`NEVER`. | dup | SRC | G5-1 |
| G-27 | Tasks don't declare required capabilities (Docker, KVM, internet, RAM, tools, credentials), so nothing can check them before dispatch. | miss | SRC | G5-1 |
| G-28 | No risk register. Six partial stores, none with a mission ref, probability or impact. | miss | SRC | G5-3 |
| G-29 | No Docker or VM execution for agents. The sandbox quota forbids KVM (`56-sandbox.yaml:29`); the sandbox image has no Docker CLI. SN61's checklist needs Docker. | miss | SRC, LIVE | G5-4 |
| G-30 | No container image digest in the release manifest (`mw_release` holds a file or commit sha256 only). | miss | SRC | G5-4 |
| G-31 | Model-written mission lessons reach planners unvalidated (`missions.py:890-893` → `orchestrator.guidance` `:1225-1229`). | risk | SRC | G5-5 |
| G-32 | No default API-change watch on competition endpoints (`mining_web` watches exist but are set up by hand); no capacity read in any mission path. | miss | SRC | G5-5 |

## G5-2 stabilization findings (2026-11-11, before PR #5 merges)

Status as of PR #5 `1057cc1` and the separate draft branch `g5/replica-safety` `8a227cd`. Nothing here is deployed.

| ID | Gap | Type | Evidence | Status |
|---|---|---|---|---|
| G-33 | Budget verification failed open. Errors in the gateway check, the preflight, guards or per-call reads became ALLOW (`agent_core._safe`). | risk | SRC, staging run 3 | **Fixed in PR #5** (`c4e63b8`, `81f9ab5`): three states ALLOW, REFUSE, UNKNOWN; UNKNOWN holds |
| G-34 | Limits were cached per process for 30 s, so another replica enforced a change late. | risk | SRC, staging run 3 | **Fixed in PR #5** (`c4e63b8`): read from the database on every decision |
| G-35 | Board starts weren't claimed in the database: two replicas started every task twice (staging run 5 contrast: 4 of 5 rounds, 8 of 8 tasks). | risk | staging run 5 | **Fixed on `g5/replica-safety`** (`8a227cd`): conditional claim plus a unique index for reviews. Not merged. |
| G-36 | `/api/health` doesn't check the database, and all three Kubernetes probes used it. | risk | SRC, staging run 3 | **Fixed on `g5/replica-safety`**: `/api/live` and `/api/ready`; probes changed in the manifest only (kubelet behaviour not exercised in Docker staging) |
| G-37 | Every web process's start-up resets every running board run and queued or working task, cluster-wide. Autoloop's caps and agent slots are per process. | risk | SRC | **Open.** Mitigation: one web replica, Recreate, enforced by `k8s/deploy.sh` on `g5/replica-safety`. Multi-replica board execution stays disabled. |
| G-38 | Model paths outside the budget gateway: the sandbox inference proxy (miner code and `rlm` sub-calls; its own `SANDBOX_DAY_USD` cap), knowledge embeddings, the host Workbench's Claude Code (recorded after the fact by `agent_core.record`), and the sign-in probe (a tiny prompt). | risk | SRC | **Open**, by design for the proxy and the Workbench. Every agent model call (`llm.completer`/`structured`: API, Claude Code, Codex, Copilot) is gated. |
| G-39 | Staging checks 1 (internet/gVisor, team on), 2 (a disposable sandbox service run) and 3 (signed-in authentication) have never run. | miss | — | **UNKNOWN**: needs node read, pod creation in `axor-sandbox`, and a dedicated temporary test login, none authorized |
| G-40 | After UNKNOWN, recovery is automatic only for board tasks, the Control Hub's undispatched tasks and Mission Control. A Control Hub task refused mid-run stays failed until a person retries it. A standalone Workforce mission or Swarm contract stops with the reason; a person re-runs it. Agent HQ, Company and Long tasks weren't audited. | miss | SRC | **Open** (recorded; not a retry loop, nothing counted against agents) |

## G5-2.2 Milestone 2 findings (2026-11-12, `dev/g5-2.2` at `bd63d98`, not deployed)

| ID | Gap | Type | Evidence | Status |
|---|---|---|---|---|
| G-41 | Concurrent runs can overshoot a stopping limit by one call in flight each (Codex: one session each): the gateway checks before a call against counted tokens and reserves nothing. | risk | `test_budget_race`: 8 runs, limit 1,000, 300-token calls, 2,400 spent | **Fixed on `dev/g5-2.2` (Milestone 3, `64e97d4`, `21f11b7`): atomic reservations.** 900 of 1,000 on 2 connections (SQLite, Postgres) and across 2 processes on the staging copy. Residual: use over the estimate (G-51). |
| G-42 | The Codex drain's closing turn ran outside the runs-at-once gate and wasn't checked by the budget. | risk | G5-2.2 open risk | **Fixed on `dev/g5-2.2`** (`3f45e99`, `a1064c4`, `bd63d98`): it takes a gate slot, the turn then gets its own time, and the budget decides it; refused: no turn, unmetered |
| G-43 | Claude Code use that was never reported was read as 0 (a timeout, a kill, a death mid-message, a restart); API-key runs in flight at a restart still lose up to one call, unmarked. | risk | code reading; `test_cli_metering` | **Fixed for Claude Code** (`3f45e99`). API-key residual: **fixed under a stopping limit** (Milestone 3: a held API call cut by a restart is charged at its bound); **open** without one (nothing reserves there). |
| G-44 | Live-data web checks passed with no retrieval ("design" evidence), and chain checks didn't tell a collector failure from staleness or match the team's competition. | broken | G5-2.2 report; staging 4d/4e | **Fixed on `dev/g5-2.2`** (`51d84a9`) |
| G-45 | No server tool reads chain storage beyond the snapshots (task 2732's `Uids` query), so a `live_data:chain` check can pass without proving the task's query can run. | miss | `G5_2_2_LIVE_DATA_VALIDATION.md` B3 | **Open.** Read-only `chain_query` proposed; Owner decision (D-026 candidate) |
| G-46 | Key characters stored outside the audit: Mining command ingest key prefixes (2 live production rows: 6 random characters each), Knowledge connector tokens (0 rows), Drive share revocations (0 rows). | risk | read-only production counts; `test_no_key_fragments` | **Code fixed** (`7754948`). The 2 production rows wait for the Owner (one UPDATE to fingerprints, no key needed). |
| G-47 | Only a team's owner can review its sample: AXoR has no human team members, so "a reviewer not associated with the executing team" can't be stricter than "a person, not an agent, and not the person who approved it". | miss | `G5_2_2_HUMAN_VERIFICATION.md` | **Partly addressed (Milestone 3, `312c99b`):** the owner's reviews no longer award "independently demonstrated" (always no, with the reason). A reviewer role is proposed (`G5_2_2_M3_INDEPENDENT_REVIEWER_PROPOSAL.md`), Owner decision. |
| G-48 | Local copies of the audit fragments outside production: the old Compose volume `subnet-scout-data` (6 rows), the dev server's database (2), an orphan volume (1); two backups (12 each, 0700, pruned after 14 days). | risk | read-only scan of 164 local SQLite copies | **Open:** delete or redact after rotation (`G5_2_2_SECURITY_REMEDIATION_PLAN.md` §6) |
| G-49 | The real Claude Code and Codex CLIs have never run against this branch: sign-in, metering, attribution and failure behaviour are proven only with scripted fakes. | miss | `G5_2_2_REAL_CLI_EVIDENCE.md` | **UNKNOWN** until the Owner connects the dedicated staging accounts |

The progress finding (dropping open work raises the active-plan percentage, by design; the original-scope headline can't be
raised that way) is a disclosure under D-018, not a gap: `test_task_states.ProgressMaths` pins both. Milestone 3 changed it:
dropped work stays in the active plan, so it can't raise either figure (D-018 amendment).

## G5-2.2 Milestone 3 findings (2026-11-12, `dev/g5-2.2` at `5413699`, not deployed)

| ID | Gap | Type | Evidence | Status |
|---|---|---|---|---|
| G-50 | A call whose outcome is unknown is charged at its bound (UTF-8 bytes sent plus the output cap), which overstates real use. No person can correct a charge (D-025's estimate covers unmetered runs only). | risk | `test_budget_reservations` | **Open**, fail-safe direction; only under a stopping limit. Proposal: let an estimate replace a charge. |
| G-51 | A reservation is an estimate, not a bound, for CLI calls (Claude Code, Codex): a call can use more than it reserved, and the limit is overshot by the difference. A model's first calls reserve the 2,000 floor. | risk | `test_budget_reservations` overrun case; fake-CLI dry run (Codex 3,150 against 2,000) | **Open, measured.** Overruns are recorded per hold and shown (`GET /api/g5/reservations`). Mitigations: the estimate learns (p90 of 50 settled calls); the floor is configurable (`AXOR_RESERVE_FLOOR`). The real size waits for the real-CLI acceptance (G-49). |
| G-52 | Live web retrieval was open to DNS rebinding (the guard resolved, then urllib resolved again), had no total timeout (a server dripping bytes or headers ran on), followed up to 10 redirects, and let some malformed addresses raise unclassified errors. | broken | `test_web_security` before the fix: 3 FAIL, 2 ERROR (`m3/tests/web-security-before-fix-bd63d98.txt`) | **Fixed on `dev/g5-2.2`** (`2ae6a49`, `21f11b7`): pinned connections, an http(s)-only opener, 5 checked redirects, a total deadline, error classes. 33 cases over http and https. Residual: public addresses on any port (by `web_read`'s design); DNS lookup time outside the deadline. |
| G-53 | A name that doesn't resolve was FAIL (address) with the guard on, where D-024 says UNKNOWN. Milestone 2's scenarios ran with the guard off and didn't show it. | broken | `test_web_security`; staging `4d2-web-guard.jsonl` | **Fixed on `dev/g5-2.2`** (`21f11b7`) |
| G-54 | "Original scope" grew with every follow-up, and the active plan rose when the Director dropped work. | incons | `G5_2_2_M3_REPORT.md` | **Changed on `dev/g5-2.2`** (`312c99b`, `21f11b7`): the first plan run as a fixed baseline; dropped work stays in the active plan; agent additions shown apart. A board without a plan run has no fixed baseline. **The definition is the Owner's** (the figures move: SN61 41% (was 38%), SN62 31% (was 52%), on the 11-11 copy). |
| G-55 | VERIFIED is set by an agent reviewer's approval as well as a person's; it said "independently passed". | incons | `verdict_sources` | **Wording fixed** (`312c99b`). Whether VERIFIED should need a person is the Owner's decision (it moves the headline). |

## G5-2.2 Milestone 4 findings (2026-11-12, `dev/g5-2.2` at `a2f3ddd`, not deployed)

| ID | Gap | Type | Evidence | Status |
|---|---|---|---|---|
| G-56 | A reservation's fixed 4-hour expiry could lapse a hold while its call was still in flight (a long CLI gate wait), and any process starting a core (the acceptance script, probes) lapsed every live hold. | risk | `test_budget_leases` | **Fixed** (`0b12ac7`): renewed leases; start-up lapses expired leases only |
| G-57 | A lapsed unbounded hold under a team or Company budget counted as nothing: buckets had no unmetered check. The teams guard's 5 s memo could skip its own. | broken | code review; `test_budget_leases.test_a_bucket_with_unmetered_use_fails_closed` | **Fixed** (`0b12ac7`) |
| G-58 | An admission refused or UNKNOWN rolled back the lapse it had just made: an expired unbounded hold stayed held forever, never surfacing as an unmetered run to estimate. | broken | `test_budget_leases.test_a_dead_holder_cannot_release_its_amount` | **Fixed** (`0b12ac7`): lapses in their own transaction |
| G-59 | A Codex `turn.failed` (and any non-timeout CLI failure) released its hold as 0. | risk | code review | **Fixed** (`0b12ac7`): unmetered unless the model never ran |
| G-60 | `estimate` was overwritten by merges and settlement; no separate reserved value. | incons | code review | **Fixed** (`0b12ac7`): estimate, reserved, actual |
| G-61 | The web fetch's name lookup ran outside the deadline, and any port was allowed. | risk | `test_web_security` | **Fixed on `dev/g5-2.2` and on the RC1 hotfix** (`e56af3f`, `b3e0274`) |
| G-62 | RC1 (production) is open to DNS rebinding through `web_read`, with no total timeout (G-52 in production). | risk | M3 before-fix tests; the RC1 code is identical | **Open in production.** Hotfix `75aeea0` prepared and validated (final review: CONDITIONAL GO); deploying it needs the Owner. |
| G-63 | Task 2732's premise was answered by 2716 (the registration attempts were never sent); it would need a chain-storage tool that doesn't exist. | incons | read-only reads of 2716 and 2732 | **Superseded** (final review): 2716's result already reports no UID on the other two hotkeys across all 129 subnets. Proposal: the Owner closes 2732 with that answer; no chain-query tool is built (D-026 not needed now). |
| G-64 | The candidate's competition importer had no total deadline, though the hotfix gave it one. Deploying the candidate after the hotfix would have removed that protection. | broken | the final review | **Fixed** (`ef919be`); a drip test on both branches |
| G-65 | Inference suggested `live_data:chain` for storage queries (task 2732's "Uids["). A person accepting it would get PASS on fresh snapshots. | risk | staging `4i-2732-requirements.json` | **Fixed** (`ef919be`): such text suggests `chain/query` |
| G-66 | The web fetcher follows an https → http redirect (a downgrade). On the hotfix and the candidate. | risk | final review probe (`m4/review/probe-hotfix-75aeea0.txt`) | **Open.** A tested patch (`m4/review/hotfix-downgrade.patch`, 70 of 70) awaits the Owner: apply to both branches and rerun, or accept in writing |
| G-67 | `test_rate_limits` (Codex cases) patches the global `time.sleep`, so it counts `subprocess.run(timeout=…)`'s exit polling when the fake child exits a few ms after closing its pipes. Failed once (candidate `b6f81bf`, Postgres run 1; run 2 passed). Test and code identical to RC1. | broken | `m4/tests/pg-b6f81bf-run1.txt`; `m4/review/probe-subprocess-sleep-out.txt` | **Open** (test only): patch a sleep only `llm.retry_brief` sees, after authorization; never skip |

G-45 updated: `live_data:chain/query` now fails without a tool, so readiness can't pass chain-dependent work on snapshots. G-49:
still UNKNOWN; the harness covers all twelve scenarios and waits for the Owner's accounts.
