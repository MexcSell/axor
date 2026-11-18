# AXoR Current State (as-is), audited 2026-11-11

This is a read-only audit. No application code, schema or deployment was changed. Each finding carries an evidence class:

| Class | Meaning |
|---|---|
| **SRC** | Read in the code, with a file:line reference. |
| **PROD** | Observed on the running system in this session. |
| **DOC** | A docstring, README or note. Not verified. |
| **SUSP** | An inference not yet confirmed. |
| **MISSING** | The capability does not exist. |

**Limit of this audit.** Reading inside production pods and databases (for example `kubectl exec` or a SQL query) was refused
by the session's permission policy. **Nothing at the data level is verified in production.** That includes mission rows,
task counts, scores, budgets and run outcomes. Section 7 lists the exact read-only queries for the Owner to run.

## 1. Repository

| Item | Finding | Class |
|---|---|---|
| Branch / HEAD | `main` at `1aff3fd` ("Add unit tests for mission evidence and operations"), 157 commits | PROD |
| Uncommitted | 4 files staged by another session: `backend/app/agents.py`, `frontend/agents.js`, `frontend/chatkit.js`, `frontend/styles.css`. This audit did not touch them. | PROD |
| Size | 156 Python modules in `backend/app`, 73,943 lines. 126 front-end JS files, about 42,400 lines. 60 views in `index.html`. | SRC |
| Database tables | 280 `CREATE TABLE` statements across about 80 modules. Schema ownership is distributed: for example `mining_autoloop.py:102` adds columns to `mw_tasks`, which `mining_work.py` owns. | SRC |
| Tests | `tests/unit`: 71 files, **827 tests, all pass** on the built image (`redeploy.sh --check`, this session). There are fake services for every external API. No end-to-end test of a mission. | PROD |
| Test database | The deploy gate (`tests/run-unit.sh`) runs the suite on **SQLite**. Production runs on **Postgres**. | SRC |
| Architecture docs | Before this audit there was no `docs/`. The architecture lived in module docstrings, `README.md` and the assistant's private notes. | SRC |

## 2. Deployment (VPS)

| Item | Finding | Class |
|---|---|---|
| Platform | Single-node k3s v1.36.5 on 65.108.79.94. | PROD |
| Deployed build | `1aff3fd-20261111071938`, deployed 2026-11-11 07:23 CET, replacing `b22f1ab-20261111054521`. The image includes the 4 staged files ("+4 uncommitted"). | PROD (`/var/lib/axor/deploys/history`) |
| Tree vs deployed | Front-end files match the deploy's checksums (`*.sums`). Back-end files are not checksummed. | PROD |
| Post-deploy checks | All pods ran the new tag. `/api/health` reported `live`, version 5.1.0, 128 subnets, busy 0. The edge served AXoR. The log had no tracebacks. | PROD (deploy log) |
| Workloads `axor` | web, drive, push, postgres-0 (pgvector), temporal, redis, prometheus, tempo, grafana. All Running. | PROD |
| Other namespaces | `axor-edge` (edge, dns), `axor-egress` (egress), `axor-host` (runner, docker-proxy, hostfiles). `axor-machines/dev-kali` is stuck in **Unknown** (10 days old, replicas 0). | PROD |
| Stack switches (`.env`, via `k8s/stack.sh status`) | `DATABASE_URL` points to in-cluster Postgres. `MISSIONS_RUNTIME=temporal`, `AGENT_GRAPH=langgraph`, `REDIS_URL`, OTLP to Tempo, `METRICS_TOKEN` are all set. That web actually uses them at runtime was **not** verified: reading the pod was blocked. | PROD (config), SUSP (runtime) |
| Background work | All agent loops run as threads **inside the single `web` pod**. `main.py:372-392` starts collector, alerts, slack, devops, monitor, platform, tech board, Agent HQ, mining (snapshots, team cycles, autopilot), Workforce, Long tasks, Company, Organization, Marketplace, Swarm, Missions, Team tests, Evolution and Orchestrator. Every deploy restarts all of them. `restart_recovery.py` handles the aftermath. | SRC |
| Host services | `axor-workbench.service` (Workflow agents on host folders, `10.42.0.1:8350`). Dev server on `:8813`. `bex-capture` container on `:10001`. | PROD |
| **Legacy Compose AXoR** (stopped by the Owner 2026-11-11, restart=no; see §8) | The containers `subnet-scout` (image from 2026-10-30 07:36, before the cutover), `scout-runner`, `scout-drive`, `scout-push` and `scout-docker-proxy` are all **Up 8 days**, with restart policy `unless-stopped`, last started 2026-11-02 10:51 UTC. `subnet-scout` holds **0.0.0.0:8000**. The edge was meant to redirect port 8000 to HTTPS. | PROD |
| Backups | No scheduled database backup found on the host or the cluster: no `pg_dump` in `k8s/`, no cron or timer. Two copies exist: the cutover copy `/var/lib/axor/cutover-20261030093904`, and the SQLite file as of the 2026-11-10 Postgres switch. | PROD + SRC |
| Code rollback | `k8s/redeploy.sh` rolls back automatically when post-deploy checks fail. Manual rollback: `kubectl -n NS rollout undo deploy/NAME`. Earlier image tags are kept. | SRC |
| Data rollback | **None** beyond the 2 copies above. | MISSING |

## 3. Functional inventory

### 3.1 Mission and task authorities

These modules hold their own "mission", "project" or "task" records.

| Module | Records | Role today |
|---|---|---|
| `missions.py` | `mx_missions`, `mx_events`, `mx_lessons`, `mx_requests` | Mission Control, 8 stages. Custom missions `mx:N`. |
| `control_missions.py` + `control_hub.py` | `ctl_fixed` (predefined missions `comp:N`), `ctl_tasks`, `ctl_intel`, `ctl_mission_teams` | Predefined competition missions and Control Hub tasks. |
| `mining_work.py` | `mw_comps`, `mw_tasks`, `mw_runs`, `mw_events`, … | Competition team board and execution. |
| `workforce.py` | `wf_missions`, `wf_items`, `wf_assignments`, `wf_board` | Workforce engine. It also accepts missions directly. |
| `swarm.py` | `sw_swarms`, `sw_contracts` | Swarm engine. |
| `infiagent.py` | `ia_tasks` | Long-tasks engine. |
| `company.py` | `co_projects`, `co_tasks`, `co_executions`, `co_approvals` | Agent Company OS. |
| `organization.py` | `og_missions`, `og_tasks`, `og_requests` | Organization (hierarchy and matrix). |
| `team.py` | `team_cycles`, `team_tasks` | PDCA project team. |
| `hq.py` | `hq_issues`, `hq_fixes` | Agent HQ (infrastructure patrols). |
| `mining_bench.py` | `mb_flows`, `mb_tasks`, `mb_runs` | Workflow on the Workbench. |
| `mining_topminer.py` | `tm_missions` | Top-miner roadmap missions. |

All rows are SRC (from table definitions and docstrings).

`agent_core.py` gives about 10 agent systems one registry (`ac_agents`), one run ledger (`ac_runs`) and one budget
(`ac_budget`, `ac_limits`) **[SRC]**. Each system still keeps its own runs, spans and events tables: `mw_*`, `wf_*`, `sw_*`,
`mh_*`, `ia_*` **[SRC]**.

### 3.2 Evaluation and evolution

| Module | What it does | Promotes on its own? |
|---|---|---|
| `evolution.py` | Engine (ev_*): proposals, blind-judged trials, policy, rollback. Its docstring says it reads the other loops "without taking over their promotion rules". | Yes, when the policy allows. |
| `mining_upgrade.py` | Upgrade Factory sprints: diagnose, practice, held-out exam. | Promotes with a hash-bound decision. |
| `mining_improve.py` + `mining_evolve.py` | Improvement Engineer trials. "Self" mode promotes and rolls back **without the user**. | Yes. |
| `mining_loadout.py` | Agent loadout versions and outcome scores. | Stores versions. |
| `mining_lab.py` | Scores commits from the Workbench's `runs.jsonl` (solved only if every run passed). | No (measurement). |
| `mining_release.py` | Frozen release manifest. `mw_bench` results come from the `record_benchmark` tool. | No. |
| `team_eval.py` | Team tests T01-T10 with hidden checks. | No. |
| `workforce.py` | `wf_improvements`, `wf_benchmarks`: Workforce self-improvement. | Yes. |
| `agent_studio.py`, `company_agents.py`, `marketplace.py` | Versions, tests and evaluations for their own agents. | Per module. |
| `mission_evidence.py` | Competitor techniques: reproduce, then adopt only if the candidate beats the baseline. | Owner decides. |

### 3.3 Consoles and read-models over the same data

Control Hub (`control_hub.py`), Mission Operations (`mission_ops.py`, the Control Hub Overview), Command and Approval Center
(`command.py`), Governance (`governance.py`), Analytics (`analytics.py`), Intelligence layers (`intel_layers.py`), Topology
(`topology.py`), Overview (`overview.py`), Command center (`mining_command.py`) and Organization HQ (`organization_hq.py`).
All are read-models of the same records **[SRC/DOC]**.

### 3.4 Approval queues

There are 4 tables: `mx_requests` (missions), `og_requests` (organization), `co_approvals` (company) and `amp_approvals`
(marketplace). `command.py`, `governance.py` and `mission_ops.decision_queue` aggregate them **[SRC/DOC]**.

## 4. End-to-end trace: a Bittensor competition mission

There are **two separate paths**. Neither covers the whole target lifecycle.

### Path A: custom mission `mx:N` with engine `mining`

Source: `missions.py`, `mission_link.py`, `mining_work.py`.

| Step | What happens | Evidence |
|---|---|---|
| Start | User creates a mission (`POST /api/mos/missions` → `Missions.create`). A worker leases it. With `MISSIONS_RUNTIME=temporal`, `_submit` starts workflow `axor-mission-<id>`, whose activity calls `_advance`. | SRC `missions.py:1258`, `:1155`. Temporal path DOC (memory). |
| Understand / discover | A model writes the objective and criteria. `mission_intel` writes the research brief. `mission_engines` recommends an engine from past missions. With no fitting team, `mission_link` asks the user to create one. | SRC `:445`, `:506`; DOC `mission_link.py` |
| Plan | Plan written. `mission_autonomy` may hold it for approval (a request bound to the plan's sha256). | SRC `:573`, `:906` |
| Allocate | Criteria frozen as a dataset version (`orchestrator.snapshot`). Model and budget chosen. | SRC `:609-634` |
| Execute (handoff) | The mission objective and criteria are cut to **590 characters** and sent as a *note* to the team lead's planner: `mw.plan(me, team, PlanIn(note=…, start=True))`. The lead's plan puts tasks on the board. The team's Director, squads and Autoloop run them. | SRC `:690-693` |
| Task assignment | Tasks go to agents through the lead's plan or Director, `_reviewer` picks the reviewer, Autoloop admits work under budget. | SRC `mining_work.py:526`, `mining_autoloop.py` docstring |
| Where it runs | Model calls run in the web pod. Code runs in sandbox pods (`mining_work._sandbox`, `sandbox.py`), with internet through the egress proxy when the team allows it. | SRC `mining_work.py:1595`; PROD pods up |
| Attribution | `mw_tasks` has **no mission column** (`mining_work.py:358-361`). Mission Control counts as its own **every team task created after `child_started`** (`missions.py:721-734`). That includes Autoloop, Director and other planners' tasks in the same window. | SRC |
| Mission's status | Running while the plan runs or tasks are open. After `MINING_WAIT` (6 h, `:75`) it returns **"done" even with tasks still open**. After 30 min with no tasks planned, "failed". | SRC `:731-734` |
| Validation | `_verify` gives the joined task summaries and results (`_collect`, `:777-783`) to a second model. The model judges each criterion against **that text**. It does not read a benchmark score, a sandbox result or `mw_bench`. | SRC `:807-836` |
| Outcome | Comes from the reviewer's results per criterion, never from the engine's own claim. | SRC `:133-140` |
| Score / leader | Not read by Path A. | MISSING |
| Failure handling | `_recover` classifies the failure and decides between pause, retry, replan or dead. Policy from `mission_autonomy`. | SRC `:785-805` |
| Delivery | Report with cost, time, verification and approvals. External actions become `mx_requests` when the autonomy level says "request". | SRC `:838-867` |
| Learning | Lessons go to `mx_lessons`. The experience recall settles when the outcome is known. | SRC `:869-900` |

### Path B: predefined mission `comp:N` (the competition team's own, ongoing work)

| Step | What happens | Evidence |
|---|---|---|
| Identity | Each open competition team is mission `comp:<mw_comps.id>`. It is **not** a row in `mx_missions` and never goes through `missions.STAGES`. | SRC `control_missions.py` docstring and `:399-408`; `missions.py:1464` (only displays it) |
| Planning | The Control Hub template seeds fixed tasks. Mission Intelligence (`ctl_intel`) proposes or creates dynamic tasks. Autoloop and the Director plan board work directly. | SRC/DOC |
| Dispatch | `control_dispatch.tick` sends `ctl_tasks` to the board through `_to_board`, which calls `mw.add_task`. The new board task is found by title, the highest id with that title. `ctl_tasks.ref = mw_task:<id>` is the only link. Tasks Autoloop or the Director create have no `ctl_task`. | SRC `control_missions.py:399-424` |
| Task state | `task_lifecycle.stage()` derives a canonical stage for **`ctl_tasks` only**. Board tasks keep their own statuses (todo, queued, working, checking, review, blocked, done). | SRC/DOC |
| Validation | Team review by the squad lead, Director or QA lead. Benchmarks: an agent calls `record_benchmark` with the **score it reports itself**. AXoR checks only that the candidate hash, suite, task count and repeats match the frozen manifest. No sandbox run is required to back the score. | SRC `mining_work.py:526-536`, `mining_release.py:302-334` |
| Independent scores (when connected) | `mining_lab` computes scores from the eval's `runs.jsonl` (Workflow path). `mining_command` ingests the evaluator's or miner's metrics with an `mcx_` key. `mining_rivals` and `ridges` read the public competitor field. | SRC `mining_lab.py:46-53`, `mining_command.py:458-498` |
| Correlation | `orchestrator._derived`: a board-task run scores **100** "Approved: its task is done" when its task is done. A team plan scores the share of its tasks that were done. | SRC `orchestrator.py:617-628` |
| Mission view | `mission_ops.py` derives states, objective progress (unverified counts as 0), the decision queue and readiness over both paths. It is read-only. | SRC/DOC |

### What the trace shows

- Mission Control does **not** govern competition teams' continuing work. That work is Path B, outside the 8 stages.
- Path A hands off a 590-character note and attributes tasks by time window. It judges success by reading text.
- The independent score sources (Lab, ingest, rivals) are not connected to Path A's verify step.

## 5. What works, by evidence class

| Area | Status |
|---|---|
| Build, unit suite, deploy pipeline with automatic rollback | PROD |
| Mission Control 8 stages, autonomy gates, failure classification | SRC, tested with a fake model. Real missions not checked in data. |
| Competition team board, Director, Autoloop budget governor, sandbox runs | SRC, plus unit tests. Production activity not checked in data. |
| Postgres, Temporal, LangGraph, Redis, OTel | Pods PROD, configuration PROD. Runtime use SUSP (not read). |
| Sandbox internet through egress and VPS exit proxy | Pods PROD. Isolation not re-verified this session. |
| Real competition score and leader comparison | Possible through the ingest key and rivals harvest. Whether connected is unknown (data not read). |
| Evolution demonstrated on a real competition | No evidence found. |

## 6. Recorded production problems (from deploy history and prior reviews)

These are dated records, not re-verified in this session.

- 2026-11-08: hostfiles crash loop (Service env collision). Deploys 17:33 to 19:30 failed.
- 2026-11-10/11: Postgres-only SQL errors 42601 and 42702 in `intel_layers.py` and `mining_rivals.py`. Fixed in source; reached production in the 11-11 07:23 deploy.
- 2026-11-10: "14 open tasks, 0 in progress". Board cap counted done tasks. Dispatcher added.
- 2026-11-11: a team spent 68M tokens against a 5M budget. Two causes found in code (in-flight tokens, cached CLI reads). **Not confirmed on production data.**

## 7. Read-only checks for the Owner to run

These need production read access, which this session did not have. All are read-only.

```bash
# runtime stack in use
kubectl -n axor logs deploy/web --since=24h | grep -iE "postgres|temporal|langgraph|error" | tail -50
kubectl -n axor exec deploy/web -- python -c "import os;print({k: bool(os.getenv(k)) for k in ['DATABASE_URL','MISSIONS_RUNTIME','AGENT_GRAPH']})"
# what Path A / B look like in data
kubectl -n axor exec postgres-0 -- psql -U axor -d axor -c "SELECT id,status,stage,engine,team,outcome,attempts FROM mx_missions ORDER BY id DESC LIMIT 20"
kubectl -n axor exec postgres-0 -- psql -U axor -d axor -c "SELECT comp_id,status,COUNT(*) FROM mw_tasks GROUP BY 1,2 ORDER BY 1,2"
kubectl -n axor exec postgres-0 -- psql -U axor -d axor -c "SELECT comp_id,COUNT(*),SUM(comparable) FROM mw_bench GROUP BY 1"
kubectl -n axor exec postgres-0 -- psql -U axor -d axor -c "SELECT comp_id,metric,COUNT(*),MAX(ts) FROM mc_metrics GROUP BY 1,2"
# legacy Compose instance
docker logs --since 24h subnet-scout 2>&1 | tail -50
```

## 8. Verification round, 2026-11-11 (ChatGPT share t_6af4128b)

Evidence levels used in this section:

| Level | Meaning |
|---|---|
| Source | Implemented in the code. |
| Deployed | Running on the VPS. |
| Tested | Functionally tested in isolation. |
| Production data | Verified on production's data. |

"Production data" here means a restored copy of the backup taken 2026-11-11 06:50Z. The copy ran in a throwaway Postgres
container with no network. Only aggregates were read.

### 8.1 What production runs

- `1aff3fd-20261111071938`, deployed 07:23. HEAD has moved on since (`77b6658`, `b565f42`, `261b8a0` and uncommitted work),
  so production is behind HEAD.
- Mission Operations (`mission_ops.py`, `control-ops.js`) is in `1aff3fd`, and the front-end files match the deploy's
  checksums.
- Level: **Deployed.**

### 8.2 Mission Operations on Control Hub → Overview

- An isolated server ran this tree with seeded data, checked at 1440 px (dark) and 390 px (light).
- The console renders first on the Overview. Its 5 KPI tiles equal `GET /api/control/ops`. No horizontal scroll, no
  application errors.
- Level: **Tested.** Seeing it rendered on production needs the Owner's own sign-in.

### 8.3 Figures against their records

`mission_ops.view()` ran in-process on the backup copy, with no loops started, and was compared with direct SQL:

| Figure | Console | SQL | Match |
|---|---|---|---|
| Open competition teams | 2 | 2 | ✓ |
| Board tasks (done) | 605 verified + 228 done unverified | 833 done | ✓ |
| Board tasks (blocked) | 11 | 11 | ✓ |
| Runs, last 7 days (accountability) | 4,874 | 4,874 `ac_runs` (same window, same moment) | ✓ |

**Caveat.** Importing AXoR on the copy ran its restart recovery, which moved `queued`/`working` tasks back to `todo` and ended
`running` runs. So the console's open-task split (0 running) and the 7-day window are as of the import, not the backup. Taken
with plain SQL from a fresh restore, before any import, the backup holds: 386 todo, 18 queued, 6 working, 1 checking,
11 blocked, 833 done; 6 `mw_runs` running. `ac_runs` started in the 7 days before the backup: 4,611 done, 284 failed,
31 lost, 7 cancelled, 6 running. The structural counts in §8.4 are unaffected.
| Custom missions | 0 | 0 `mx_missions` | ✓ |

Other figures, for the Owner to compare with the live Overview:

- KPI tiles: Active competitions 2, Verified objectives 0, Tasks requiring attention 11, Decisions waiting 9 (8 for you).
- comp:23 is blocked and comp:22 is paused. Both show objective progress 0 and rank UNKNOWN ("no ranked miner under your keys").
- 61% of the week's runs (2,996 of 4,874) are excluded from evaluation, each with a reason.

### 8.4 Production facts from the backup copy

| Record | Count |
|---|---|
| Users | 5 |
| `ac_runs` | 7,117 |
| `mx_missions` | **0**: Mission Control's competition path (Path A) has never run in production |
| Board tasks | 1,255, of which 58 came from a lead's plan and 1,197 from other origins |
| Sandbox runs | 2,692 (2,368 done, 173 error, 144 failed, 5 timeout) |
| `rv_agents` (competitor harvest) | 114 |
| Frozen releases | 0 |
| `mw_bench` | 14, all non-comparable |
| `mc_metrics` | 0 |
| Lab experiments | 0 |
| Evolution trials | 0 |
| Hard token limits (`ac_limits`) | 0 |

See G-23.

### 8.5 Item-by-item status

| # | Item | Source | Deployed | Tested | Production data |
|---|---|---|---|---|---|
| 1 | VPS runs the intended commit | — | `1aff3fd` (behind HEAD) | `redeploy.sh --check` | ✓ deploy log, health |
| 2 | Mission Ops on Overview | ✓ | ✓ (files match) | ✓ browser, seeded | needs the Owner's sign-in |
| 3 | Figures against records | ✓ | ✓ | ✓ | ✓ backup copy (§8.3) |
| 4 | Mission ID on every board task | ✓ (D-006 amended) | ✗ | ✓ 12 tests; migration rehearsed on the backup copy | n/a (0 missions) |
| 5 | Tests on production's Postgres | ✓ `run-unit.sh --postgres` | — | ✓ 856/856 on Postgres; 1 intermittent error in an earlier run (G-24) | migration rehearsal ✓ |
| 6 | First backup and restore | ✓ | — | ✓ | ✓ after the G-22 fix; timer not installed |
| 7 | Legacy containers | — | stopped by the Owner | — | ✓ port 8000 answers 301 |
| 8 | Mission → competition end to end | partial (unit level) | — | partial | ✗ never run (0 missions, no measured score) |

## 9. G5 baseline, 2026-11-11 ~11:30 CET

| Item | Value | Class |
|---|---|---|
| Running in production | `axor/web:1aff3fd-20261111071938` (deploy log: `main@1aff3fd +4 uncommitted`, 07:23) | PROD (`kubectl get deploy web`, `/var/lib/axor/deploys/history`) |
| `main` | `d57098e` = `origin/main`. The 36 paths that were uncommitted during the G5 assessment were committed by the Owner at 11:08 as `d57098e`; the tree was clean afterwards. | PROD (git) |
| Commits on `main` not deployed | `77b6658`, `b565f42`, `261b8a0`, `d57098e` | PROD (git) |
| Auto-update timer | inactive, so a push to `main` does not deploy | PROD |
| G5 work | branch `g5/phase1` from `d57098e`, worktree `/home/thomas/subnet-scout-g5` | PROD (git) |
| SN61 checklist | `docs/docker-session/live-bench-checklist.md` in team 23's files, read from the 06:50Z backup copy (4,159 bytes). Steps 0–8: tool hash check, challenge container on port 10001, health, live `POST /score`, busy probe, mock validator similarity gate, benchmark filing after a frozen release, cleanup. | PROD (backup copy, 06:50Z) |
| Director report #208 | Team 23, 2026-11-11 07:20:21 UTC. Not in the 06:50Z backup (last report there: #205). The first live read was refused by the permission policy; it was read live later on 2026-11-11 with the Owner's export script, after the Owner's review. It holds the step-by-step plan for the 2026-11-12 Docker session and finding #3082 (validators run the miner offline on an internal network, port 10002 only). Its pinned challenge digest `sha256:1be22365…089bb` matches the image on the host. | PROD (live read, 2026-11-11) |
| Host port 10001 | Held by the `bex-capture` container started 2026-11-10; the checklist's step 2 needs that port. | LIVE |
