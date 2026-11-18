# AXoR G5.5: live system reassessment

**For the Owner and the external reviewer.** This is a read-only diagnostic of the running systems and the source behind them.
Snapshot taken 2026-11-15 at 19:31 UTC; report written by about 19:45 UTC.

**What this assessment did not do.** It changed no application code, database, configuration, permission, deployment, branch or
commit. It did not sign in to any instance, `kubectl exec` into production, read production databases or secrets, or stop or
restart anything. The only file written to the repository is this one, and it is **uncommitted**.

---

## 0. Bottom line

1. **Production changed today, and it no longer matches GitHub `main`.** This is the most urgent finding.
   - At **18:49 UTC on 2026-11-15**, k3s production was redeployed as `axor/web:9b34cd2-20261115194457`, replacing `083696d`.
   - The build came from the shared working tree (`main@9b34cd2` plus 5 uncommitted files). Its file contents equal local commit
     **`aba7ac5`**, made 37 minutes after the deploy and not pushed.
   - The deployed tree (`aba7ac5`) does **not** contain GitHub `main` (`083696d`). It is 155 commits behind and 2 ahead, with
     186 files different.
   - Production therefore **lost** the following. Each was checked with `git merge-base --is-ancestor <commit> aba7ac5`, which
     returned false:
     - RC1 hotfix H-1 (refuse an https→http redirect);
     - G5-2 "budget decisions never fail open" (`c4e63b8`);
     - replica safety, one web replica enforced (`5611cd7`);
     - the rule against teammate login borrowing (`fed32f7`);
     - the G5-2.2 budget leases;
     - D-004 D4.1–D4.4 (persistent missions);
     - G5-3/4/5 (VM runner client, frozen-release evidence, learning-loop fixes).
   - It **gained** the GAIA benchmark tab and the Developer page (D-016). RC1 had removed GAIA as unapproved.
   - Its deploy test gate ran **930 tests**. The `083696d` deploy it replaced ran **1,628**.
   - The guard that refuses exactly this kind of deploy (PX-B17, `df31866`) exists only on the development waves. It is not on
     `main` and not in the shared tree, so it didn't run.

   §3 has the evidence. Whether to keep, roll back or re-release is the Owner's decision. This report only records the state.
2. **The runtime at `http://localhost:8830/` is a staging instance, not production.**
   - It is container `axor-e2e-web`, image `axor-prep/web:g5-track-a2-cc2d183`, on SQLite.
   - Its file contents equal `dev/g5-track-a2@cc2d183` exactly (504 of 504 files).
   - That commit is **GitHub `main` plus 154 commits** (103 files, +13.8k lines), local only and not pushed.
   - It was restarted at 18:58:55 UTC today. **Since then it has recorded no mission, run, evaluation or memory row.** The
     Track A code it carries has no runtime evidence yet.
3. **Real autonomous operation has happened only in staging, and only under supervision.**
   - Two genuine SN61 missions ran with a real model login on earlier builds: mission 1 delivered `partial`, mission 2 delivered
     `unverified`.
   - Neither met its objective (≥0.8 official score). No criterion was independently verified.
   - Every run used **one model**. The verifier was the same model as the workers.
   - Model routing never used history. 50 of 63 completed runs record "no model pool, the default model", and the other 13
     record no decision.
4. **The self-improvement loop has never fired.**
   - Staging has 0 evolution proposals, 0 trials, 0 promotions and 0 rollbacks.
   - All 4 benchmark rows are `comparable=0`; two of them were hand-corrected by the Owner today.
   - The frozen release has no measuring job, so team trials can't start.
5. **Maturity: Level 2, supervised execution.** The evidence index is **2.7 / 5** (§9). No area has production evidence of
   sustained autonomous operation.

---

## 1. Scope, sources and evidence labels

### 1.1 What was inspected

| Target | Identity (how it was pinned) | Access used |
|---|---|---|
| **Staging runtime :8830** | Container `axor-e2e-web` (label `axor.e2e-instance=axor-e2e`), image `axor-prep/web:g5-track-a2-cc2d183`. `/app` hashes equal `git archive cc2d183` (504/504 files, 0 differences) | Unauthenticated `GET /api/health,/api/live,/api/ready`; `docker inspect/logs/top/stats`; a read-only snapshot of its SQLite files (SQLite backup API, opened `mode=ro`) |
| **Production (k3s)** | Deployment `axor/web` image `axor/web:9b34cd2-20261115194457`; pod imageID `sha256:689d1591…` = the containerd id of that tag (`k3s crictl inspecti`). `deploy.sh` imports it with `docker save` from the Docker image `sha256:64154306…`, whose `/app` hashes equal `git archive aba7ac5` (521/521 files, 0 differences) | Deployment and pod metadata (`kubectl get`), the host deploy log `/var/lib/axor/deploys/`, and an offline run of the image (`--network none`, nothing mounted). **No production data, logs or secrets were read** |
| **GitHub `main`** | `083696d` (checked live with `git ls-remote origin`; no fetch) | `git` |
| **Source for claims** | A frozen, detached worktree of `cc2d183`, never the shared working tree | `grep`/read |

**Inherited claims.** The source map in `g5-plan/level5/LEVEL5_AUDIT.md` (written today about 18:30 UTC) covers `083696d` and
`9552fd5`. Both are ancestors of `cc2d183` (checked). Claims taken from it are labelled **INH**. Only the ones this report leans
on were re-read in `cc2d183` (labelled SRC).

### 1.2 Evidence labels

| Label | Meaning |
|---|---|
| **PROD-OBS** | Observed on production metadata, its image or the host deploy log today |
| **STG-OBS** | Observed in the :8830 snapshot (19:31:20 UTC) or its API, logs or process |
| **SRC** | Read in `cc2d183` source, with file:line |
| **REP** | Reported by another session's records (tests, staging rehearsals). Not re-run here |
| **INH** | Inherited from LEVEL5_AUDIT §4, not re-read |

**The time split matters.** The staging container started at **18:58:55 UTC**. Every staging row cited below was written
**before** that, by earlier builds (the genuine SN61 run's records name wave 10j `b85d23b`, REP). The current build is a
superset of those, but its own runtime record is empty (§5.1).

---

## 2. Updated ecosystem architecture

```
                              ┌──────────────────────────── GitHub ────────────────────────────┐
                              │ main = 083696d (= production until 18:49 UTC today)              │
                              │ dev/* branches (some pushed); dev/g5-track-a2 NOT pushed          │
                              └────────────────────────────────────────────────────────────────┘
                                         ▲ not contained                     ▲ contained (+154)
  ┌──────────────── k3s PRODUCTION (since 18:49 UTC) ────────────────┐   ┌──── STAGING :8830 (docker, 127.0.0.1) ────┐
  │ web  axor/web:9b34cd2-20261115194457 (= local aba7ac5, unpushed) │   │ axor-e2e-web   image cc2d183 (SQLite)       │
  │      1 replica, Recreate; ~30 in-process loops (INH)              │   │ axor-e2e-egress (egress proxy, same image)  │
  │ drive, push, dns, egress, runner, hostfiles, docker-proxy         │   │ VM runner via kube stand-in (REP)            │
  │ temporal, redis, prometheus/tempo/grafana (deployments seen);     │
  │ postgres+pgvector per deploy records (statefulset not inspected)  │   │ data: /var/lib/axor-staging-auth (auth.db)  │
  │ sandbox pods (gVisor) + egress proxy                               │   │ 12-hour soak by another session until ~07:00│
  └──────────────────────────────────────────────────────────────────┘   └────────────────────────────────────────────┘

  Inside one web process (both environments), by D-010 layer:
  Mission ─── missions.py (Path A: understand→discover→plan→execute→verify→deliver→learn), mission_ops readiness,
  │            control_missions/control_dispatch/task_lifecycle (Path B), mining_work board + Director + Autoloop
  Workforce ─ agent_core (ac_agents registry, ac_runs ledger, admit/preflight budget gateway), model_router, organization,
  │            workforce.py, agent_studio
  Execution ─ sandbox.py (gVisor pods), exec_env.py (AEF workspace, staging/dev only), runner.py (VM Docker jobs), swarm.py,
  │            team.py, infiagent.py
  Evaluation ─ missions._verify, mining_release (frozen release, mw_bench), team_eval (T01–T10; GAIA only in production now)
  Adaptive ── evolution.py (one gate, D-007), orchestrator diagnose/guidance/optimize/monitor, mining_upgrade/improve/evolve
  Knowledge ─ knowledge_hub (kb_*), mining_knowledge (mk_items), mx_lessons, experience.py (ex_* recall), wf_memory, mw_notes
  Cross-cut ─ orchestrator.py = "G5 Unified Intelligence Orchestrator" (io_events bus, io_evals, io_diag, io_risks)
```

**Population of that architecture (STG-OBS).** The staging database has 286 application tables, of which **217 are empty**.
Thirty table prefixes are empty throughout, including:

- `co_` (Company OS), `sw_` (Agent Swarm), `ev_` (Evolution), `hq_` (Agent HQ);
- `amp_` (Marketplace), `ia_` (InfiAgent), `mb_` (mining bench);
- `au_` (Upgrade Factory), `te_` (team tests), `team_` (project team);
- `wallet_` and `devops_`.

Most of the architecture exists only as source.

---

## 3. Runtime versus source-code discrepancies

### 3.1 Deployed modules compared with GitHub `main` (`083696d`), `backend/app`

| Runtime | Added | Removed | Changed |
|---|---|---|---|
| **Production** (`aba7ac5`) | 5: `developer.py`, `dev_claude.py`, `dev_files.py`, `dev_terminal.py`, `data/help/developer.md` | 3: **`runner.py`** (G5-4 VM runner client), **`audit_redact.py`**, **`state_migrate.py`** | 58 files, 53 of them Python modules (listed below) |
| **Staging :8830** (`cc2d183`) | 3: `exec_env.py` (AEF), `sandbox_files/aef.py`, `vault.py` | 0 | 26 |

**Production's 53 changed Python modules** (`git diff --name-status 083696d aba7ac5 -- backend/app`):

| Area | Modules |
|---|---|
| Agent core and models | `agent_core`, `agents`, `cli_accounts`, `codex_bridge`, `llm`, `terminal_bridge` |
| Security and platform | `auth`, `secretbox`, `egress_proxy`, `sandbox`, `techboard`, `db_pg`, `drive`, `main` |
| Missions and control | `missions`, `mission_ops`, `mission_link`, `mission_attachments`, `control_dispatch`, `control_hub`, `control_missions`, `task_lifecycle` |
| Intelligence | `orchestrator`, `evolution`, `experience`, `learning`, `intel_layers`, `swarm`, `workforce`, `organization` |
| Mining | `mining`, `mining_work`, `mining_autoloop`, `mining_bench`, `mining_command`, `mining_director`, `mining_improve`, `mining_loadout`, `mining_portfolio`, `mining_release`, `mining_sources`, `mining_topminer`, `mining_upgrade`, `mining_web` |
| Other | `company`, `connectors`, `helpdocs`, `infiagent`, `knowledge_connectors`, `pages`, `slack`, `source`, `team_eval` |

In production these modules are **older** versions, from the `5862bed` line, not newer ones. So every G5 behaviour change in
them since 11-11 is absent from production.

### 3.2 Discrepancy register

| # | Discrepancy | Evidence | Severity |
|---|---|---|---|
| **X-1** | **Production ≠ GitHub `main`.** Production runs a tree that doesn't contain `083696d` (`aba7ac5`: 155 behind / 2 ahead, 186 files) | PROD-OBS: deploy log `history` line `2026-11-15T19:49:36+01:00 9b34cd2-20261115194457 083696d-… ok main@9b34cd2 +5 uncommitted`; image hashes = `aba7ac5`; `git merge-base --is-ancestor 083696d aba7ac5` false | **Critical** |
| X-2 | Production lost security and safety fixes, among them H-1. The production image has no `"redirect from https to plain http"` check in `techboard.py`, 0 lease references in `agent_core.py`, no `UnmeteredSpend`, no `exec_env.py`, no `runner.py`. The 083696d image has all of these except `exec_env.py`; the cc2d183 image has all of them | PROD-OBS (offline image grep, all three images) | **Critical** |
| X-3 | Production's deploy test gate ran **930** tests today. The same gate ran **1,628** at the `083696d` deploy it replaced. (For reference, the candidate suite on `cc2d183` is reported at 2,249, REP) | PROD-OBS (deploy logs `9b34cd2-20261115194457.log`, `083696d-20261113163134.log`) | High |
| X-4 | The deploy-ancestry guard (PX-B17, `df31866`: "refuse a build that doesn't contain the commit production runs") is in `b85d23b`, `9552fd5` and `cc2d183`, **not** in `083696d` or the shared tree. The deploy ran the shared tree's older `redeploy.sh` | SRC (`git show <sha>:k8s/redeploy.sh`) | High |
| X-5 | GAIA, which RC1 removed as unapproved (D-009), is back in production (`team_eval.py`, 68 references). So is the Developer page (`developer.py`, absent on `main`) | PROD-OBS (image tree = `aba7ac5`) | Medium (governance) |
| X-6 | The staging runtime (`cc2d183`) is 154 commits ahead of `main` on an **unpushed** branch | `git ls-remote` shows no `dev/g5-track-a2` | Medium |
| X-7 | `/api/health` reports `"version": "5.1.0"` for every build (`083696d`, `aba7ac5`, `cc2d183`). The API carries no build identity | STG-OBS, PROD-OBS (deploy log) | Medium |
| X-8 | Memory and audit documents written today still say production = `083696d` (for example LEVEL5_AUDIT §1.1). That has been stale since 18:49 UTC | DOC | Medium |
| X-9 | Routing records say "No model pool (Workforce → Settings): the default model" on 50 of 63 completed runs; the other 13 record no decision. Yet `ac_pool` now holds a pool, written at 18:43 UTC, after the last run | STG-OBS (`ac_runs.decision`, `ac_pool.updated`) | Low (explains §7) |
| X-10 | The Evolution "independent judge" label vs code: the judge uses the arms' own model | INH (`evolution.py:624,663`) | Low until Evolution runs |

---

## 4. Capability classification

Each row has two classifications: the **status** (the six classes requested) and the **runtime evidence**:

- **this build**: rows written by `cc2d183` after 18:58:55 UTC;
- **earlier build**: staging rows written before the restart;
- **none**: no rows anywhere.

Production data was not read, so production use is "Cannot verify" throughout. Source existence alone never makes a row
"enabled". The status column describes the **staging runtime** (`cc2d183` and the earlier staging builds). Where production
differs, the evidence column says so ("absent in production" means the code isn't in the production image, §3.1).

### 4.1 Agent Core

| Capability | Status | Runtime evidence |
|---|---|---|
| Agent registry (`ac_agents`) | Implemented and enabled | Earlier build: 42 agents |
| Run ledger (`ac_runs`, corr / team / login_kind) | Implemented and enabled | Earlier build: 9,329 rows (63 done, 9,266 failed) |
| Budget gateway (`admit` / `preflight`, reservations, 24-hour team bucket) | **Implemented but malfunctioning** | Last observed state; the fix is in source and hasn't been exercised on this build. Earlier build: **9,261 refused runs in 22 min** (11-14 04:22:09–04:44:28 UTC, about 7 per second): "The team's 24-hour token budget can't take this call: 156,291 of 150,000". REP: root cause D1 (preflight allowed, gateway refused); fix `09f07ed` is in `cc2d183` |
| Owner daily cap | **Implemented but disabled** | STG-OBS: `ac_budget.unlimited` set 2026-11-12 08:06 UTC; only the team bucket limits spend |
| Fail-closed budget (`UnmeteredSpend`) | Implemented and enabled | SRC in `cc2d183`; REP: it held team 1 after a restart. **Absent in production** (PROD-OBS: image grep) |

### 4.2 Mission OS

| Capability | Status | Runtime evidence |
|---|---|---|
| Path A lifecycle (understand → … → learn) | Implemented and enabled | Earlier build: 2 missions, both `delivered`, stage `learn`, autonomy L2, engine `mining`, budget 20 |
| Acceptance criteria → verification | **Partially implemented** | Mission 1: 6 criteria (1 met, 1 partly, 2 not met, 2 unverifiable) → `partial`. Mission 2: 5 of 5 `unverifiable` → `unverified`. Verifier model `terminal:fable` = the worker model |
| Readiness gate and risk register (`io_risks`) | Implemented and enabled | Earlier build: 43 risks (36 open, 6 resolved, 1 accepted), for example "docker not ready… AXoR has started a small check job" |
| Recovery and replanning | Partially implemented | Earlier build: 3 `transient` timeouts (150 s); whether they were retried was not checked. REP: restart mid-job → error, retry scheduled, then a budget hold that needs a person |
| Track A additions (D3 mission window, D4 inputs hold, D6 fd-leak fix, D8, D9) | **Cannot verify** | Implemented in source. This build: no mission rows since the restart. REP: unit tests plus a 60-min soak (D6: open handles 24→274 old vs 19 steady fixed); a 12-hour soak runs until ~07:00 UTC |
| Path B (control missions, dispatcher) | Cannot verify | `ctl_tasks` 8, `ctl_briefs` 3, `ctl_mission_teams` 0 |
| Persistent missions (D-004) | Cannot verify | No persistent mission in staging data. **Absent in production** (PROD-OBS: D4.1–D4.4 commits not in the deployed tree) |

### 4.3 Execution (AEF sandbox and VM jobs)

| Capability | Status | Runtime evidence |
|---|---|---|
| Sandbox runs and VM Docker jobs (`mw_sbx`) | Implemented and enabled | Earlier build: 66 jobs: 46 done (mean 92 s), 18 failed, 2 error |
| Mission workspace store (`mw_ws`, `mw_blobs`) | Implemented and enabled | Earlier build: 11 workspaces, 80 blobs. Absent in production (`exec_env.py` not in the image; staging/dev only by design) |
| Team egress policy (allowlist, packages approved) | Implemented and enabled | STG-OBS: `exec.comp:1` = allowlist, up 50 MB/day, down 2,000 MB/day; `runner.package_hosts` = the two PyPI hosts |
| Official scorer through the VM path | Implemented and enabled | Earlier build: `mw_bench` rows from jobs 7, 51, 52, 53 |

### 4.4 Agent Swarm, Workforce, Company and other agent systems

| System | Status | Runtime evidence |
|---|---|---|
| Agent Swarm (`swarm.py`) | **Cannot verify** | Implemented in source, never exercised: `sw_*` all 0. Missions chose engine `mining`, never `swarm` |
| Workforce (CEO/teams/debate) | **Cannot verify** | Implemented in source. `wf_agents` 19 and `wf_versions` 19 (seeded); `wf_runs`, `wf_missions`, `wf_memory` 0 |
| Organization (matrix) | Partially implemented | Structure data only: `og_units` 12, `og_agents` 24, `og_lines` 29. `og_perf` 0, so no performance is recorded for selection |
| Company OS, Agent HQ, Marketplace, InfiAgent, Upgrade Factory, team tests, project team | **Cannot verify** | Implemented in source; all tables 0 |

### 4.5 Evolution Lab and benchmarks

| Capability | Status | Runtime evidence |
|---|---|---|
| Proposal → experiment → promote → monitor → rollback | **Cannot verify** | Implemented in source, never fired: `ev_proposals`, `ev_trials`, `ev_benchmarks`, `ev_policy`, `ev_audit`, `io_monitor`, `io_bench_runs` all 0 |
| Team trials on frozen-release VM benchmarks | **Implemented but disabled** (precondition unmet) | `mw_release` v1 frozen 11-14 08:30 UTC, `measure` = NULL (no measuring job). REP: Owner approval item 4 "can't be done yet", because team 1 is over its allowance until ~15:00 UTC 11-16 |
| Benchmark quality (`mw_bench`) | **Partially implemented** | 4 rows, **all `comparable=0`** ("candidate isn't the frozen…", "no release manifest is frozen yet"). Rows 2–3 corrected today from 10.9 to 4.5 by the Owner's decision (audit `benchmark.correct` ×2). Scores 6.13 / 4.5 / 4.5 / 10.9 on a 0–100 scale; target ≥80 |
| Statistical promotion rule | Not implemented | INH: `evidence()` is threshold-only (n≥3, +5 points); REP: staging reading rule = ≥5 runs, ranges must not overlap |
| `mining_evolve` "self" mode auto-promotion outside the gate | Cannot verify | INH: implemented, and it bypasses the gate; no staging rows (`mb_*` 0) |

### 4.6 Unified Intelligence Orchestrator (`orchestrator.py`, `io_*`)

| Capability | Status | Runtime evidence |
|---|---|---|
| Event bus (`io_events`, idempotent keys, retries) | Implemented and enabled | Earlier build: 18,744 events, **all `done`, 0 dead, max attempts 0** |
| Run evaluation and diagnosis (`io_evals`, `io_diag`) | Implemented and enabled | 9,319 evals, 9,266 diagnoses (most from the refusal storm) |
| Guidance to planners | Implemented and enabled | Effect unproven: 3 `mission.guided` events, each `changes: 0, tested: 0` |
| Monitor after promotion | Cannot verify | `io_monitor` 0 (nothing promoted) |
| `/api/g5` access control | Implemented and enabled | STG-OBS: unauthenticated `GET /api/g5` → 401 |

### 4.7 Organizational memory

| Capability | Status | Runtime evidence |
|---|---|---|
| Experience recall across work items (`ex_recalls`, `ex_uses`) | Implemented and enabled | 36 recalls (16 inside mission 1's window, 20 inside mission 2's), 135 uses. Mission 2's work recalled **mission 1's own record** (`recall.mission`; `ex_uses` ref `mx:1` ×7, 11-15 14:57–16:17 UTC). Other items recalled: mining knowledge (`mk:`), team notes (`mwn:`), control briefs (`ctl:`). n = one mission-to-mission transition |
| Lessons to planners (`mx_lessons`) | **Implemented but disabled** | Disabled in effect by its own gate. 8 lessons, all `used=0`, and no lesson ref (`mxl:<id>`) appears in `ex_uses`. A planner's recall excludes unverified lessons (`experience.py:224`, L5.2), and guidance reads only `verified`, `trial_verified` and `bench_verified` (`orchestrator.py:1974`, `:2369`). All 8 are `partial` or `unverified`. The gate works as designed; the loop is starved because no mission verifies |
| Meaning (vector) search | **Implemented but disabled** | All 36 recalls `fuzzy`. There is no embeddings key, so the built-in vectors match word forms only (`experience.py:253`) |
| Company knowledge base (`kb_items`) | Partially implemented | `kb_items` 0, yet `kb_queries` 5,017: agents query an empty hub |

### 4.8 Model routing

| Capability | Status | Runtime evidence |
|---|---|---|
| Router by history (`model_router.rank`, quality / cost / latency / failure terms) | **Implemented but disabled** | Disabled at run time. 50 of 63 completed runs record `"source": "no_pool"`, `candidates: []`; the other 13 record no decision. The pool was configured 11-15 18:43 UTC, after the last run. No run since, so its effect is Cannot verify |
| Multi-model operation | Implemented but disabled | Only one model was ever used. `ac_runs` and `mw_runs`: one model (`terminal:fable`), one login (`cli_accounts` 1), `login_kind=server` |
| Quality signal for routing | Partially implemented | Score coverage 4 of 63 completed runs (6%) |
| Routing versioning / rollback | Not implemented | INH (`ac_pool` one upserted row per owner) |

### 4.9 Background workers, scheduler, restart recovery, concurrency

| Capability | Status | Runtime evidence |
|---|---|---|
| In-process loops (about 30, INH) | Partially implemented | Liveness observed for only four loops since the restart. The sandbox proxy logs "listening on 8091". The chain collector and mining snapshot keep logging (expected failures, below). **Platform sync fails on every pass**: 47 × `platform sync failed: 'status'`. For the rest, liveness is Cannot verify: one uvicorn process with 73 threads (69 Python, 4 libuv), 14% CPU, 208 MiB, 0 restarts, healthy; no loop has written a row except `mh_events` |
| Chain sampler | Implemented and enabled | Staging stand-in. 16 `mh_events` since the restart. Its errors (`RpcConnectionError`, 16 collector errors since start) are expected, because staging has no chain endpoint (REP) |
| Restart recovery | Partially implemented | Recovery needs a person to finish. REP: restart mid-job → job `error` "Stopped by a server restart", VM removed, task requeued, then held by the budget (unmetered run) until a person acts |
| Concurrency limits | Implemented and enabled | STG-OBS `terminal_parallel=4`; INH missions WORKERS=2, ACTIVE_PER_USER=3 |
| Single-replica safety | Implemented and enabled | Staging runs one instance. **Absent in production**: replicas=1 Recreate (PROD-OBS), but the enforcing commit `5611cd7` isn't in the deployed tree |
| Single scheduler / loop registry | Not implemented | INH |

### 4.10 Security, governance and human approval

| Capability | Status | Runtime evidence |
|---|---|---|
| Login required and admin gates | Implemented and enabled | STG-OBS `REQUIRE_LOGIN` set; 401 on `/api/g5`; audit `login.fail` ×4, `sudo.fail` ×2 (refusals recorded) |
| Secrets at rest | Implemented and enabled | STG-OBS: `app_settings` secret values are Fernet ciphertext |
| Egress control | Implemented and enabled | §4.3; https-only VM jobs in `cc2d183` (REP) |
| SSRF / redirect hardening (H-1) | Implemented and enabled | In the staging image. **Absent in production** (X-2) |
| Mission autonomy boundary | Implemented and enabled | Both missions ran at L2. INH: external actions (deploy, pay, keys, delete) are never carried out automatically |
| Owner approval of risks and decisions | Implemented and enabled | `io_risks.approval` "the Owner may accept it (CONDITIONAL)"; the Owner corrected benchmarks by recorded decision |
| Deploy governance (ancestry guard, main = production) | **Partially implemented** | The guard exists only on dev waves and didn't run (X-1, X-4) |
| CI | Not implemented | No `.github/workflows` |

---

## 5. Mission execution and verification history (staging)

### 5.1 Rows written after the 18:58:55 UTC restart (this build)

The only table with new rows is `mh_events`: 16 rows, from the chain sampler. `ac_runs`, `mw_runs`, `mx_*`, `io_*`, `ex_*`,
`audit` and `mw_events` have **no rows** since the restart. The last `ac_runs` row is from 17:19 UTC and the last `mw_events`
row from 18:45 UTC. A second snapshot at about 19:50 UTC still had 0 `ac_runs` and 0 `mw_runs` rows after the restart.

*Method:* inserts were counted by one timestamp column per table (`created`, `ts`, `started` or `updated`, whichever exists
first). Updates to older rows were not checked.

### 5.2 The two genuine missions (earlier builds)

| | Mission 1 | Mission 2 |
|---|---|---|
| Title | SN61 BEX-Tracer Miner to ≥0.8 Official Score | Score SN61 Candidates C1, C1+C2, C1+C3 |
| Wall clock | 11-14 04:17 → 10:20 UTC (6.1 h) | 11-14 15:32 → 11-15 16:35 UTC (25.0 h, includes paused time) |
| Tokens (own / child) | 56,500 / 535,494 | 70,771 / 889,796 |
| Outcome | `partial` (1 met, 1 partly, 2 not met, 2 unverifiable) | `unverified` (0 of 5 verifiable) |
| Verifier | `terminal:fable` (same as workers) | `terminal:fable` (same as workers) |
| Objective met? | No (baseline 6.13 / 100) | No (best candidate 10.9; Owner-corrected rows 4.5) |
| Person acts | — | REP: three (D4, D5, D8), per the AEF final review |

**Board state.** `mw_tasks` holds 13 done, 2 blocked and 44 todo. Team 1 has been paused since 16:41 UTC 11-15 (REP).

**Verdict.** The mission machinery runs end to end with a real model. It has **not** produced a verified success, and it
needed people to continue.

---

## 6. Evolution, benchmarks, promotions and rollbacks

- **Experiments:** 0. **Promotions:** 0. **Rollbacks:** 0 (STG-OBS, all `ev_*` tables). Production was not read. INH reports 0
  trials and 0 promotions on production as of 11-11.
- **Benchmark quality:**
  - Every `mw_bench` row is `comparable=0`.
  - The suite is 5 cases with `repeats=1` per row.
  - The scores (6.13, 4.5, 4.5, 10.9) sit far below the 80-point target and are within the run-to-run noise reported for this
    challenge (REP: identical inputs scored 0.005–0.095 on the 0–1 scale).
  - Two rows were wrong (the job's newest score file was taken instead of its own). They were corrected by hand today.
  - This is a data-integrity defect in benchmark attribution, fixed in `cc2d183` (D9/D-037) per REP, and unexercised since.
- **Why the loop can't fire today:**
  1. The release has no measuring job.
  2. Personal-agent experiments are model-judged, which policy never promotes (INH).
  3. The team is over its token allowance.
  4. Missions never reach `verified`, so no lesson reaches planners.

---

## 7. Model routing against historical performance

There is no runtime evidence of history-based routing.

- 50 of 63 completed runs record `no_pool` → default model `terminal:fable`. The other 13 record no decision, and they also ran
  on `terminal:fable`.
- Only one model login exists on the instance.
- Only 6% of runs carry a score the router could learn from.
- The pool written at 18:43 UTC lists several models, but no run has used it.

**Classification:** router *implemented but disabled at run time*; effectiveness **Cannot verify**.

---

## 8. Measured performance (staging, earlier builds)

| Measure | Value |
|---|---|
| Runs completed / attempted | **52 / 9,317** overall. Excluding the 22-minute refusal storm: **52 / 56** (93%) |
| Task run duration | median 148 s, p90 635 s, max 1,259 s (n=37) |
| Report / plan / knowledge runs | median 52 s / 38 s / 18 s |
| Task run tokens | median 36,558, p90 89,097 |
| Total model tokens recorded (`ac_runs`, done) | 1,909,668 (team runs 1,778,099; mission steps 127,271) |
| Refusal storm | 9,261 refused calls in 22 min; `ac_runs` charges 297,025 tokens to failed runs while `mw_runs` records 0. Both ledgers count differently (REP: the governor counts `mw_runs`, the bucket counts max(`mw_runs`, ledger)) |
| VM / sandbox jobs | 46 done (mean 92 s), 18 failed, 2 error |
| Transient model timeouts | 3 (150 s each) |
| Event bus | 18,744 events, 0 dead, 0 retries |
| Web process now | 14% CPU, 208 MiB, 73 threads, 0 restarts |
| Recall latency | mean 8 ms (fuzzy) |
| Production | Not measured (no production data read). Deploy log: health and edge checks passed at 18:49 UTC; `/api/health` showed `busy: 1` |

---

## 9. Evidence-based maturity score

**Rungs, evidence only:**

| Rung | Meaning |
|---|---|
| 0 | Not implemented |
| 1 | Source only |
| 2 | Tests or scripted staging only |
| 3 | Ran with a real model in staging, but its outcome is unproven or a defect was observed |
| 4 | Ran with a real model in staging and met its own acceptance check |
| 5 | Observed sustained in production |

Each area is capped at its highest **observed** rung.

| # | Area | Rung | Why |
|---|---|---|---|
| 1 | Agent Core | 3 | Ran; refusal storm observed; fix unexercised |
| 2 | Mission OS lifecycle | 3 | Two real missions, neither met its objective |
| 3 | Mission verification | 3 | Ran, same-model verifier, 0 independently verified |
| 4 | Execution fabric (sandbox/VM) | 4 | 46 jobs done; the official scorer runs through it |
| 5 | Agent Swarm | 2 | Tests only (INH); 0 rows |
| 6 | Workforce | 2 | Seeded rows only |
| 7 | Evolution Lab | 2 | 0 experiments |
| 8 | Unified Intelligence Orchestrator | 3 | Bus and evals run cleanly; guidance changed nothing; monitor never ran |
| 9 | Organizational memory | 3 | Recall works; lessons never reach planners |
| 10 | Model routing | 2 | No pool at run time; one model |
| 11 | Workers, scheduler, recovery | 3 | Bus healthy; recovery needs a person (REP) |
| 12 | Security and governance | 2 | Enforced on staging, but production regressed and the deploy guard is bypassed |

**Evidence index = (3+3+3+4+2+2+2+3+3+2+3+2) / 12 = 32 / 12 = 2.7 / 5.**

**Autonomy level:**

| Level | Description |
|---|---|
| L1 | Assisted: people run agents |
| L2 | Supervised execution: missions run end to end, and people unblock them |
| L3 | Verified autonomy: independent verification, no person acts |
| L4 | Governed self-improvement: measured promotions and rollbacks through the gate |
| L5 | Sustained self-evolution in production |

**AXoR is at L2.** L3's first condition (one independently verified mission with no person act) hasn't been met.

---

## 10. Reliability and security findings

| ID | Finding | Evidence | Severity |
|---|---|---|---|
| R-1 | Production regressed below GitHub `main`: H-1, fail-closed budget, replica safety, login rule, budget leases and D-004 removed | X-1, X-2 | Critical |
| R-2 | The deploy path lets a non-descendant tree reach production; the guard exists only on dev waves | X-4 | High |
| R-3 | Retry storm on a refused budget: 9,261 calls in 22 min, with no circuit breaker effective at run time | §4.1 | High |
| R-4 | Production's deploy test gate ran 930 tests today, down from 1,628 at the previous deploy. The gate counts whatever the deployed tree holds, so dropping a tree's tests also drops them from the gate | X-3 | High |
| R-5 | Same-model verification; the "independent" label on the Evolution judge isn't backed by code | §5, X-10 | High |
| R-6 | Benchmark attribution took the wrong job's score (two rows hand-corrected) | §6 | Medium |
| R-7 | One web process carries ~30 loops; production must stay at one replica, and its enforcement is gone from production | §4.9 | Medium |
| R-8 | Owner daily cap disabled on staging (`unlimited`); only the team bucket bounds spend | §4.1 | Medium |
| R-9 | Restart mid-run → unmetered run → whole-team budget hold needing a person (REP) | §4.2 | Medium |
| R-10 | No build identity in the API (`version` 5.1.0 everywhere) | X-7 | Low |
| R-11 | Untracked, unpushed state: staging runs an unpushed branch; production runs an unpushed commit | X-1, X-6 | Medium |
| R-12 | Staging platform sync fails on every pass (`platform sync failed: 'status'`, 47 times since 18:59 UTC) | STG-OBS (`docker logs`) | Low (staging) |
| R-13 | A production-cluster pod, `axor-machines/dev-kali-…`, is in state `Unknown` with 3 restarts | PROD-OBS (`kubectl get pods -A`); cause not investigated | Low |

**No secrets were exposed in this report.** Encrypted setting values were seen in the snapshot and are not reproduced.
Environment variables are named, never valued.

---

## 11. Top 10 architectural weaknesses

1. **Release integrity isn't enforced by the tooling that deploys.** "main = production" is a convention. The shared tree can
   deploy anything, and today it did (R-1, R-2).
2. **There is no independent verifier in practice.** With one model login, `_verify` uses the workers' own model, so no mission
   can reach `verified`. That outcome is the precondition for lessons and for the learning loop.
3. **The learning loop is starved by design coupling.** Lessons need `verified`. Trials need a measuring job. The measuring job
   needs an agent run. That run needs allowance. One blocked link stops everything (§6).
4. **The budget control plane has two ledgers and no runtime circuit breaker.** `mw_runs` and `ac_runs` disagree on tokens for
   failed runs, and a refusal loop ran unchecked for 22 minutes.
5. **Benchmarks are tiny and noisy, and none is comparable.** The suite has 5 cases with `repeats=1` per row, under a
   documented ±0.05 noise band. There is no split, no held-out set, and no statistical gate (INH).
6. **Routing intelligence has no inputs.** It had no pool, one provider and 6% score coverage, and routing has no versioning.
7. **Subsystem sprawl.** 217 of 286 tables are empty. There are 12+ agent registries (INH) and several promotion paths outside
   the gate (INH). Most of the "ecosystem" is unexercised code.
8. **Everything runs in a single process.** About 30 daemon loops share one web pod, and a restart resets running work
   cluster-wide (G-37). There is no loop registry or shared dead-letter queue.
9. **There is no CI.** The deploy gate tests whatever the deployed tree contains: 930 tests today against 1,628 at the
   previous deploy. Patches can also edit their own tests (INH).
10. **Human-in-the-loop dependence is unmeasured.** Person acts aren't counted as a metric, and no metric snapshots persist. So
    autonomy can't be shown to improve over time (INH).

---

## 12. Prioritized roadmap to Level 5

Each step has an exit criterion that can only be met by runtime evidence.

| Priority | Step | Exit criterion (evidence) | Owner decision needed |
|---|---|---|---|
| **P0** | Reconcile production with the release record. Options: roll back to `083696d` (its images, including `axor/web:083696d-20261113163134`, are still in containerd); re-release a reviewed descendant; or formally accept `aba7ac5` and push it | Production image tree hash = a commit on GitHub `main`; H-1 / leases / `UnmeteredSpend` present in the running image | **Yes, now** |
| P0 | Put the PX-B17 ancestry guard on `main` and in every tree that can run `redeploy.sh`; expose build sha in `/api/health` | A deliberate non-descendant deploy is refused in a rehearsal; health shows the sha | Yes (merge) |
| P1 | A second model login and a pool, so `_verify` uses a different model | A mission verifier model ≠ worker model, recorded in `verification` | Yes (login) |
| P1 | Exercise the D1 / Track A fixes on `cc2d183` with a real run | Budget refusal yields one backoff, not a loop; `mw_runs` vs `ac_runs` reconcile for that run | — |
| P2 | Freeze a release with a measuring job; trial floor (≥7 runs per side, 10-point margin) | One `ev_trials` row with comparable arms; `mw_bench.comparable=1` | Yes (allowance) |
| P2 | One independently verified mission with **zero person acts** (L3 gate) | `mx_missions.outcome='verified'`, verifier ≠ worker model, person-act count 0 | — |
| P3 | Lessons reach planners: verified or bench-verified lessons; an embeddings key for meaning search | `mx_lessons.used > 0`; recall mode `meaning`; a with-vs-without comparison on ≥2 missions | Yes (key) |
| P3 | CI, plus a deploy gate that refuses a drop in test count | A deploy whose test count falls below the running release's is refused; CI runs on every PR | Yes |
| P4 | First promotion through the one gate, then monitor and rollback | `ev_proposals` → trial → promote → `io_monitor` rows; one rehearsed rollback | Yes (per promotion) |
| P4 | Routing on history: score coverage ≥80%, pool versioned | Router decisions name candidates and stats; a pool history table | Yes (D-xxx) |
| P5 | Persisted metric snapshots, including person acts per mission and autonomous-hours share | Weekly snapshots for ≥4 weeks show the trend | Yes (L5-3) |
| P5 | Retire or freeze unexercised subsystems (empty prefixes) by decision record | Fewer registries; promotion paths outside the gate closed (G-06) | Yes |
| **L5 exit** | Sustained production operation | ≥30 days in production with ≥3 gated promotions that held under monitor, ≥1 automatic rollback, and person acts per mission trending down | — |

The open Owner decisions L5-1…L5-7 (LEVEL5_AUDIT §2) still apply. This roadmap follows their option B (close G5-4/5 first)
and adds P0, which did not exist this morning.

---

## 13. Reproducing this assessment (read-only)

- **Staging identity:** `docker inspect axor-e2e-web`; hash `/app` in `docker run --rm --network none --entrypoint sh <image>`
  against `git archive cc2d183`, comparing the sorted lists with `LC_ALL=C sort -k2` (an unsorted diff shows false
  differences).
- **Production identity:**
  - `kubectl -n axor get deploy -o custom-columns=…image`;
  - `k3s crictl inspecti <tag>`;
  - `/var/lib/axor/deploys/history` and `9b34cd2-20261115194457.log`;
  - an offline image hash against `git archive aba7ac5`.
- **Staging data:** SQLite backup API from `file:/var/lib/axor-staging-auth/auth.db?mode=ro` into a scratch copy; all queries
  on the copy. The scratch copies (which hold credential ciphertext) were deleted after use, including a second snapshot
  taken at about 19:50 UTC for the recounts.

**Not verified:**
- production database contents (missions, dispatch pause, owner settings);
- `AXOR_OWNERS` in production (it would be in secret `axor-env`, which was not opened);
- any authenticated staging API;
- the reported test-suite results.
