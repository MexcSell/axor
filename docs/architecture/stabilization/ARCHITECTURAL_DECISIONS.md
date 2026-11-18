# Architectural Decisions

Each decision is authoritative from the moment the Owner approves it, until a later approved entry amends it.

**Statuses:** Approved · Proposed (awaiting Owner) · Superseded.

## D-001 · Stabilize, don't rebuild

**Status:** Approved by Owner, 2026-11-11.

**Decision.** AXoR evolves from its existing implementation. The alternatives "fundamental rebuild" and "hybrid
reconstruction" were rejected.

**Why.** The audit found that most of the target architecture already exists as modules (`missions.py`, `orchestrator.py`,
`evolution.py`, `task_lifecycle.py`, `mining_*`). The problem is integration, not missing capability.

## D-002 · First operational priority: prove the mission lifecycle on Bittensor

**Status:** Approved by Owner, 2026-11-11.

**Decision.** Prove the complete mission lifecycle on one existing Bittensor competition before building more company-wide
infrastructure.

## D-003 · Authoritative documents

**Status:** Approved by Owner (directive), 2026-11-11.

**Decision.** `docs/architecture/stabilization/` holds the Constitution, Target Architecture, Current State, Mission Execution
Contract, Gap Register, Roadmap and this log. They govern ChatGPT proposals and Claude Code implementation alike. Anything
that contradicts them waits for a decision here.

## D-004 · Mission Control owns competition missions

**Status:** Approved, 2026-11-11. The Owner delegated the decision to Claude Code ("you decide") after reading the audit summary.

**Context.** Gap G-01. Competition teams' continuing work runs as predefined missions `comp:N`, outside `missions.STAGES`.

**Proposal.**
- Each active competition team gets one long-running `mx` mission: objective "top-N in competition X", measurable criteria,
  budget and deadline.
- The team's board, Director and Autoloop remain the inner loop.
- Mission Control runs the outer evaluation and decision per cycle.
- `comp:N` stays the team's identity in the Control Hub; it is no longer a separate mission authority.

**Alternatives considered.**
- (a) Make `control_missions` the mission authority for competitions. This contradicts decision 2.
- (b) Keep both paths. This leaves the gap open.

**Consequences.**
- Additive only: a link from `mx_missions` to `mw_comps` (`team` already exists).
- No table is removed.
- Mission views show one mission per team.

## D-005 · Measured vs reported scores

**Status:** Approved, 2026-11-11. The Owner delegated the decision to Claude Code ("you decide") after reading the audit summary.

**Context.** Gap G-04. Board-path benchmark scores are reported by agents.

**Proposal.** A score is *measured* only when it comes from the Lab, the ingest key, the chain, or a `record_benchmark` call
backed by a finished sandbox run of that task. Only measured scores decide mission outcomes, promotions and technique
adoption. Reported scores stay visible, labelled.

## D-006 · Board tasks carry their mission ref

**Status:** Approved, 2026-11-11. The Owner delegated the decision to Claude Code ("you decide") after reading the audit summary.

**Context.** Gap G-02.

**Proposal.** Add an additive nullable `mw_tasks.mission` column. Mission Control selects by it, never by time window.

**Migration.** `ALTER TABLE … ADD COLUMN`, the same pattern `mining_autoloop.py:102` already uses. Existing rows stay NULL,
meaning inner-loop work.

**Amendment, 2026-11-11 (ChatGPT share t_6af4128b: "explicit mission ID for every board task").** Every board task has a
mission. NULL is read as the team's own predefined mission `comp:<comp_id>` (`mining_work.mission_ref()`). A Mission Control
mission's work stores `mx:<id>`. The 1,255 existing rows are not backfilled: NULL already means `comp:<comp_id>`.

How the ref travels:
- `mw_runs.mission` holds the ref for the lead's plan run.
- An agent's follow-ups inherit the ref from their parent task.
- A left-out task that is added back inherits the ref from its origin.
- When a mission's plan repeats an open task of the team's own, the mission adopts that task.
- Control Hub tasks reach the board with their ref, and `_to_board` keeps the id it created instead of matching by title.

Mission Control counts, collects and attributes tokens by ref. Cancelling a mission stops only tasks its own attempt created.
A Control Hub task marked standalone (`mission="none"`) also reads as `comp:<comp_id>` on the board.

**Status of the amendment: Proposed, awaiting Owner** (it changes an approved decision). Built and tested (12 new tests; full suite on SQLite and Postgres). The migration was rehearsed on
a copy of production data. Not deployed.

## D-007 · One promotion gate

**Status:** Approved, 2026-11-11. The Owner delegated the decision to Claude Code ("you decide") after reading the audit summary.

**Context.** Gap G-06.

**Proposal.** Every improvement path proposes; `evolution.py` promotes, versions, rolls back and audits.

**Resolution.** `mining_evolve`'s "self" mode stays, as an evolution-policy level the Owner sets per team. Its promotions also
go through the gate, so they are evidence-checked, versioned and audited like the others.

## D-008 · Retire the legacy Compose instance

**Status:** Approved, 2026-11-11. The Owner delegated the decision to Claude Code ("you decide") after reading the audit summary.

**Context.** Gap G-00.

**Proposal.** Stop the 5 legacy containers and set them to restart=no. Keep their volumes for 30 days, then decide.

**Why approved:** their logs (2026-11-11) show no agent work, only the subnet collector. Internet scanners probe them all
day, including failed logins against the pre-cutover accounts. `scout-runner` has read-write access to the Docker socket.

**Execution:** the permission policy refused the stop for Claude Code ("interfere with workloads"). The Owner runs it:
`for c in subnet-scout scout-runner scout-drive scout-push scout-docker-proxy; do docker update --restart=no $c; docker stop $c; done`

## D-009 · Proven external benchmarks in the evaluation system

**Status:** Proposed. Awaiting Owner. The Owner asked for the capability on 2026-11-11 (ChatGPT share 6af311c4, "Agent Team
Evaluation", §3 "Real-world test datasets and benchmark websites"). The design below is Claude Code's, not yet approved.

**Context.** The evaluation layer (TARGET_ARCHITECTURE "Evaluation") scores the team only with our own questions: Team tests
T01-T10 graded by a model against hidden checks. The Owner asked that evaluation also lean on established benchmarks,
specialised inspection tools and evaluation companies.

**Proposal (built, uncommitted, not deployed).**
- No new module, page or table prefix. Everything sits inside `team_eval.py` (Team tests): two columns on `te_cases`
  (`source`, `ext`) and one more (`constraints`), plus a "Proven benchmarks" tab.
- A catalog maps each capability to its proven benchmark, inspection tool or framework. For each it records the official grading
  and what AXoR lacks to run it (MISSING, from the code): SWE-bench, Terminal-Bench and OSWorld need repository checkout, test
  runs in per-task images, command execution or a desktop. No mission engine has any of these today.
- GAIA, which needs only research, runs end to end. Validation items are imported as blind benchmark cases from the server's
  verified local copy (see the amendment below) or from an uploaded JSON file. They are graded only by GAIA's official
  scorer, ported, on the last "FINAL ANSWER:" line. No model judges them.
- Official results are reported apart from our own cases: "n correct of m", with the dataset revision. They never enter the run's
  mean, and they're labelled an AXoR-run subset, not a leaderboard score.

**Limits stated in the product.** GAIA validation answers are public, so a team with web search could find them. Items with
attached files are skipped. The answer-format rule reaches the engine only through the planner's brief (SUSP: a planner that
drops it shows up as "no FINAL ANSWER line", counted separately).

**Not done, needs separate decisions.** Automated submission to outside graders (an external action). Sandbox changes for
SWE-bench images (root, per-task images). Live-site inspections (PageSpeed, WebPageTest, Lighthouse).

**Amendment, 2026-11-11 (Owner: "verified test data should be researched, kept locally, and used").** Proposed, with D-009.
- Each benchmark's official data is downloaded once by an administrator (Team tests → Proven benchmarks) and kept under
  `DATA_DIR/benchmarks/<id>/`: `items.jsonl`, `manifest.json` and, for GitHub sources, `source.tar.gz`. It isn't in the repository
  (GAIA asks not to be reshared in crawlable form). SRC: no API route serves it. Production keeps it on the web pod's volume,
  outside AXoR Host files' roots (`/home/thomas`, `/srv/data`). The folder is owner-only (0700), so Host files (another user)
  can't read it on the dev server either, whose data sits under `/home/thomas`. Workbench's host Claude Code is not
  restricted by this.
- Pinned and checked:
  - Hugging Face datasets record the dataset sha and the sha of the viewer's parquet conversion. A dataset that changes during
    the download is refused, and so are rows the viewer cut short.
  - GitHub repositories are read at the commit their default branch names (git's own `info/refs`, no API rate limit). The
    archive is accepted only if the commit id inside it matches.
  - Every copy carries the sha256 of its items, and reading it back checks that sha256. A failed download keeps the old copy.
- Held: GAIA validation (165 items; gated, so this one download needs the read token), SWE-bench Verified (500), Terminal-Bench
  2.0 (89 tasks, `harbor-framework/terminal-bench-2`), OSWorld test_all (368). About 60 MB in all.
- GAIA imports read only the local copy or an uploaded JSON file, with no network or token at import time. The per-import
  dataset-viewer path is removed.
- Holding SWE-bench, Terminal-Bench or OSWorld data doesn't make them runnable. They still need what the catalog lists:
  per-task execution environments and each benchmark's harness. That is the separate sandbox decision named above.
- Granting MCP tools (Agents → Tools & MCP) doesn't close that gap. A grant adds callable tools (search, GitHub reads, papers),
  not a per-task container, a desktop VM, or an official grader outside the agent's reach.

## D-004 amendment · Path B carries the lifecycle gates

**Status:** Approved by Owner, 2026-11-11 ("Owner Review — AXoR G5 Assessment and Implementation Authorization", §2).

**Decision.** Mission Control owns the `comp:N` competition mission lifecycle, and SN61 (`comp:23`) uses it. Preflight, risk
assessment and readiness gating are implemented **in Path B and its dispatcher** (`control_missions.py`, `control_dispatch.py`,
`task_lifecycle.py`, the team board in `mining_work.py`), never only in Path A (`missions.STAGES`). Existing mission and task
infrastructure is reused. D-004's original proposal (one long-running `mx` mission per team) remains the target for the outer
loop; the gate must work on Path B whether or not that `mx` mission exists yet.

## D-010 · G5: six intelligence layers, Risk cross-cutting

**Status:** Approved by Owner, 2026-11-11 (Owner Review §1).

**Decision.** The authoritative capability model has exactly six intelligence layers: Mission, Workforce, Execution,
Evaluation, Adaptive and Knowledge. Risk Intelligence is a cross-cutting capability across all six, **not a seventh layer**.
Governance and Control are shared organizational policies and controls, not layers. No further layers, duplicate services or
alternative architectural models without Owner approval.

**Compatibility.** The component stack in [TARGET_ARCHITECTURE.md](TARGET_ARCHITECTURE.md) §1–7 stays; it says *where* things
run, the six layers say *what capability* each part provides. `ecosystem.py` (eight layers) stays as a view. The mapping and
migration are in TARGET_ARCHITECTURE.md §8. No functionality is removed.

## D-011 · Readiness gate and preflight

**Status:** Approved by Owner, 2026-11-11 (G5 directive §D–E; Owner Review §2, §5 G5-2). Implementation design: Proposed,
reported per phase.

**Decision.** A shared Mission Preflight and Readiness Engine gives every mission, Path B first, one of three states:
**PASS** (all mandatory requirements verified), **CONDITIONAL** (only explicitly permitted non-critical issues remain) or
**BLOCKED** (a mandatory prerequisite is missing or failing). An aggregate score never overrides a critical failed requirement.
The dispatcher does not hand out a task whose mission is BLOCKED on a requirement that task needs.

**Basis in existing code.** `mission_ops.readiness()` already refuses to average a failing row away (`mission_ops.py:929`);
the probes exist (`sandbox.Sandbox.ready`, `Egress.status`, `platform_status`, `llm.cli_status`, node reads in `kube.py`).

## D-012 · One canonical risk register

**Status:** Approved by Owner, 2026-11-11 (Owner Review §3): one register; Risk identifies, predicts, assesses and monitors;
Adaptive owns approved countermeasures and improvements. **Owner of the register: Approved** (Owner decisions of 2026-11-11 §4):
the orchestrator's diagnostics (`orchestrator.py`, `io_*`).

**First table (G5-2).** `io_risks` is created in G5-2. Its only input then is readiness findings.
- Each risk has a stable identity and a deduplication key. A repeated probe updates the existing record instead of adding one.
- Records link to the mission, the task, the source diagnosis and the verification evidence.
- The lifecycle and the remediation owner are explicit.
- The existing diagnostics (`io_diag`, `io_sbx`) stay the source of raw evidence.
- G5-3 adds alerts, HQ issues and the other diagnosis sources.
- No other risk database, dashboard or orchestrator.

**Decision.** Infrastructure issues (`hq_issues`), alerts (`alerts`, `ac_alerts`, `mo_alerts`, `mh_alerts`), execution
diagnoses (`io_diag`, `io_sbx`) and preflight results feed the one register. They do not become competing risk systems. Each
record carries the G5 §C fields, including the mission ref and the layer.

## D-013 · Isolated VM-based remote Docker execution

**Status:** Approved by Owner, 2026-11-11 (Owner Review §4): direction and requirements. **Topology and interfaces: Proposed**,
to be designed and reported in G5-4.

**Evidence.** 2026-11-11, one-off manual test in `axor-machines`: a pod with `axor.dev/kvm`, baseline Pod Security and no
privileges booted a Debian VM with `-accel kvm`. Inside it, Docker 29.9.3 and Compose v5.7.0 ran a build, `compose up` with a
published port, an `/openapi.json` fetch and `docker stats`: PASS in 105 s. Not proven: egress-proxy routing, the Machines
image, a path from a sandbox run.

**Requirements.** Controlled agent job submission; restricted execution permissions; Docker image build and push; image
digest verification; mock and live benchmarks; RAM and container health measurements; logs and reproducible artifacts; human
approval for external submissions.

**Constraints.** Agents never get the host Docker socket or root on the host. The manual Docker session of 2026-11-12 (SN61
`docs/docker-session/live-bench-checklist.md`) stays the fallback while the capability is built.

**Design (G5-4 V4.1, 2026-11-13): Proposed.** `D013_VM_RUNNER_DESIGN.md`: one throwaway KVM VM per job, in a namespace of its own
(`axor-machines`' network policy gives every pod open egress, so a runner there couldn't be held to less), jobs recorded as
`mw_sbx` rows, pulls by digest only, approvals through the G5-2 hash-bound approval. Decisions D8-a…D8-h are the Owner's.

**Design approved by the Owner, 2026-11-13 (D-8, "I approval (D-8)"), D8-a…D8-h as recommended.** The approval covers V4.2
development: code, the manifests under `k8s/runner/`, the base-disk script, unit tests and a local staging job. It does not cover
creating the namespace, the RoleBinding or the image on the production cluster, or deploying: those need the Owner's written
production authorization.

**V4.2 as built (development, 2026-11-13).** `backend/app/runner.py`, the `docker_job` agent tool, `k8s/runner/` (outside
`k8s/base`, so `deploy.sh` doesn't apply it). Differences from the design, each within its decisions:
- D8-f: the base disk is a read-only layer of the runner pod image (pinned by its own sha256, which every job reports), not a
  separate volume. Pod Security baseline forbids `hostPath`, and the namespace's quota allows no volume claims.
- D8-c: the egress proxy takes an optional host list per run; a runner job's run is opened for the registry hosts only. A build
  whose `RUN` steps download packages (pip, apt) is therefore refused by the proxy: widening the list is the Owner's decision.
- §5: a job that names a secret, or a push, is recorded as held and never started. Running one after approval needs a
  credential store, which doesn't exist: not built.
- §4: the result reaches AXoR through the sandbox proxy's existing per-run hook (`/t/<token>/rlm/job/result`), so `sandbox.py`
  is unchanged. Q-4: a benchmark's score is read from the job's own `score_file`; Q-5: the score and the exit code are separate.
- Integrity limit: the job's command runs inside the VM with Docker, so a job that set out to forge its own result file could.
  The runner makes a score reproducible (hashed inputs, base disk, images), not tamper-proof against the job itself.

## D-014 · G5 phases and phase gates

**Status:** Approved by Owner, 2026-11-11 (Owner Review §5–7).

**Decision.** G5 phases (named G5-1 to G5-5, distinct from the stabilization roadmap's S0 to S5):
- G5-1: unified failure taxonomy and task capability requirements;
- G5-2: preflight engine, readiness gate and Path B integration;
- G5-3: canonical risk register;
- G5-4: SN61 Docker and benchmark validation;
- G5-5: runtime monitoring, measured evaluation, validated learning and adaptive improvements.

**Rules.**
- Work happens on a development branch (`g5/phase1`, worktree `/home/thomas/subnet-scout-g5`). Nothing is deployed to
  production automatically.
- Each phase reports: implementation summary, source changes, automated test results, regression results, evidence against
  acceptance criteria, and remaining risks. The Owner approves before the next phase starts.
- A capability is never reported complete because code exists or unit tests pass.
- G5-1 is authorized.

## D-015 · G5-1 review: failure policy and requirement gating

**Status:** Approved by Owner, 2026-11-11 (G5-1 review, decisions D1–D5). D1–D4 are implemented in G5-2; D5 changes G5-1's
acceptance criteria.

- **D1. Authentication failures.** Runs that fail because a login isn't signed in (canonical class `credential`; 184 runs in
  the 06:50Z corpus) no longer count against agent performance. They are provider authentication / environment readiness
  failures and stay in platform reliability metrics. An authentication preflight check runs before dispatch.
- **D2. Retry policy.** Only transient failures are retried automatically, with bounded exponential backoff, jitter and
  idempotency protection. Authentication, permission, missing capability, invalid input and unsupported tool failures stop and
  trigger remediation or replanning. This replaces the dispatcher's retry of `provider` and `tool` and Mission Control's
  `retry` for `model` (orchestrator `CONFLICTS`).
- **D3. Planner needs.** Every new planner output declares `needs`, an empty array when there are none, under a versioned
  schema. Existing planners keep working (backward compatible).
- **D4. Blocking.** Only declared requirements can block a task automatically, and each is verified against the actual
  execution environment: a declared Docker need is not Docker being available. Inferred requirements ask for confirmation and
  never block. Governance gates (production deploys, external submissions) stay mandatory.
- **D5. T-7 acceptance (revised).**
  - Zero changes in each legacy classifier's output across the regression cases.
  - Cross-classifier conflicts are measured explicitly.
  - Representative conflict examples are given.
  - The overlapping vocabularies are explained.
  - The regression tests stay.

> D-016 is used by the Developer page (uncommitted work in the shared tree); the decisions below start at D-017.

## D-017 · Structured task requirements

**Status:** Direction approved by Owner, 2026-11-11 ("Owner Decisions: RC1 Reconciliation", 1). Implemented on
`dev/rc1-owner-decisions`. Not deployed: the implementation awaits the Owner's review.

**Decision.** A task's requirements live in four layers that are never mixed:
- **Inferred:** what the task's words suggest. A suggestion only: it never declares and never blocks. A person accepts it (it
  becomes declared, by that person) or rejects it (it stops asking). Each decision records who and when (`task_req_decisions`).
- **Declared:** `needs` on the task, set by a person or a version-2 planner, with who and when (`needs_by`, `needs_at`). `[]` means
  declared none: no external dependency. NULL means undeclared.
- **Confirmed:** a person reviewed the declared list. The confirmation is bound to the list's hash, so it lapses when the list
  changes. Confirming settles every undecided suggestion.
- **Verified:** AXoR's live readiness check of the declared list (`needs_verify`), bound to the list's hash the same way.

**Inference rules after the review of the 39 production suggestions** (made by Claude, proposed to the Owner; the Owner approved the direction, not each verdict).
- Keys are inferred only when they are signed or registered with.
- Nothing is inferred from tasks that only write checklists, runbooks or notes.
- An "image digest" no longer implies a registry.
- On the reviewed set: precision went from 36% to 100% and recall from 82% to 94%. The rules were tuned on that set; across all 448
  open tasks, no new suggestion appeared beyond the reviewed ones.

## D-018 · Task-state accounting: Completed, Review, Verified, Cancelled, Dropped

**Status:** Direction approved by Owner, 2026-11-11 (2). Implemented on `dev/rc1-owner-decisions`. Not deployed.

**Decision.** Finished board work is one of five states:
- **Review:** delivered and waiting for an independent verdict.
- **Verified:** an independent verdict is on record.
- **Completed:** closed on a person's word without a verdict.
- **Dropped:** the Director closed it as no longer needed.
- **Cancelled:** a person called it off.

**Accounting rules.**
- Dropped and cancelled work counts in no planned, delivered, completed or unverified figure.
- How a task was closed is kept in `mw_tasks.closed_as`. Its status stays `done`, so the rollback image (RC1) reads rows unchanged.
- History is backfilled from the records by `app/state_migrate.py`: dry run by default, a journal row per change, reversible per
  batch.
- Rows that aren't migrated are read from the Director's note.

## D-019 · Sign-in audit and per-run login attribution

**Status:** Direction approved by Owner, 2026-11-11 (3). Implemented on `dev/rc1-owner-decisions`. Not deployed.

**Decision.**
- **Sign-in audit.** Every step of a sign-in attempt is an `agent.cli_signin` audit row: provider, flow, stage, attempt id and a
  fixed reason code.
- **Server keys in the audit** are named by a sha256 fingerprint, no longer by their first and last characters.
- **Per-run attribution.** Every ledger run records the login its model calls ran on (`ac_runs.login`, `login_kind`), at the
  point the account is handed to the CLI. API-key providers are recorded as `api:<provider>`.
- **Never logged:** credentials, tokens, device codes, sign-in links, the code a person types, CLI output or error texts.

## D-020 · Evidence levels for G5 readiness

**Status:** Direction approved by Owner, 2026-11-11 (4). Implemented on `dev/rc1-owner-decisions`. Not deployed.

**Decision.** Every readiness row carries an evidence level:

| Level | What the records show |
|---|---|
| Independently demonstrated | A verdict from someone other than the actor |
| Operationally tested | This server's records show it working in operation |
| Partial | It works for some cases and not others |
| Implemented | Built, with no operational record |
| Unknown | No records |
| Fails | The records show the requirement broken |

**Rules.**
- The row's pass, partial, fail or unknown state follows from its level. Only operational or demonstrated rows pass.
- Design-only capabilities are never counted as demonstrated.

## D-021 · Codex token metering

**Status:** Direction approved by Owner, 2026-11-12 (G5-2.1 authorization, P1). Implemented on `dev/g5-2.1`. Not deployed.

**Decision.**
- **Why.** Codex reports usage only when its session ends (`turn.completed`). A session that AXoR left earlier (the step limit,
  a replaced session, an error) was killed, so the run counted 0 tokens. On production, all 20 zero-token Codex task runs out of
  90 (11-09 to 11-11) stopped at exactly 10 model calls.
- **Drain.** A session left mid-run is drained instead: waiting tool calls are answered "the run ended", Codex closes its turn,
  and its usage is counted on the run that opened the session. The wait is bounded.
- **No usage in time.** The run is marked `metering = unmetered`, never counted as 0.
- **Not yet confirmed.** Whether the real CLI behaves this way needs a dedicated staging Codex login.

## D-022 · Read-only run traces for team agents

**Status:** Direction approved by Owner, 2026-11-12 (P2). Implemented on `dev/g5-2.1`. Not deployed.

**Decision.** A team's agents may read their own team's task runs through the `run_traces` board tool:
- status, error, model, steps, tools used, and the last calls, clipped;
- never another team's runs, review runs, plans, or Team tests benchmark missions;
- credentials are redacted;
- the answer is capped at 10 runs and about 9,000 characters;
- it never writes anything.

## D-023 · Human verification sampling

**Status:** Direction approved by Owner, 2026-11-12 (P3). Implemented on `dev/g5-2.1`. Not deployed.

**Decision.**
- **Weekly sample.** A person checks a sample of the work agents approved: reproducible (ranked by a hash of the ISO week and
  the task id), chosen by no agent. The default rate is 10%, at most 10 tasks a week; the rate is the Owner's setting.
- **Structured verdicts.** Verdicts are stored by user id (`mo_verdicts`), as are a person's own approvals. Whether a verdict is
  a person's or an agent's is never read from event text.
- **Disagreements** are flagged in the decision queue and reopen nothing.
- **"Independently demonstrated".** The verification row reaches it only when the Owner's threshold (`verify_demonstrated`:
  checks in 30 days, agreement %) is set and met. It is unset by default.
- **No new engine.** The sample feeds the existing readiness row and decision queue.

## D-024 · Live-data requirements

**Status:** Approved by Owner, 2026-11-12 (G5-2.2 directive, A). Implemented on `dev/g5-2.2`. Not deployed.

**Decision.** `live_data` is a requirement type of its own, separate from `internet` (which remains the sandbox's own egress).

| Source | Retrieval | Freshness | Verification |
|---|---|---|---|
| `live_data:web[/host]` | AXoR's server-side `web_read` | 24 h, reported, not gated | the retrieval path: available unless the host's latest fetch by AXoR failed. A task that exists to do the fetch is never held for not having done it. |
| `live_data:chain` | AXoR's chain snapshots of the subnet (`mh_samples`) | 2 h | the subnet's latest chain snapshot (block and time) is within the window; a campaign brief is not evidence |

- Verification reads the team's own records, never by giving the sandbox internet.
- A failing web source, or a stale chain snapshot, blocks the task. It is not critical, so the Owner may accept it (Conditional).
- Inference may suggest live data and never declares it.

## D-025 · Budget integrity for unmetered use

**Status:** Approved by Owner, 2026-11-12 (B). Implemented on `dev/g5-2.2`. Not deployed.

**Decision.**
- **Never counted as zero.** A run whose token use is unknown (`metering = unmetered`: a Codex session that reported no usage,
  or one a restart cut off) is never read as zero.
- **Fails closed.** Every stopping limit whose scope and period contain such a run, and the owner's daily cap, answer UNKNOWN:
  the work waits. Alert-only limits and scopes without a limit are unaffected.
- **Released by a person.** An audited estimate is counted on the run (`metering = estimated`), and the limit is checked again.
  The estimate can't be lower than the average of the model's last 50 metered runs, and never under 10,000 tokens.
- **Coverage.** `ac_limits`, the owner's daily cap and a team's 24-hour budget guard.
- **Not covered.** Autoloop's per-task cap can't stop a Codex run mid-way: Codex reports usage only when the session ends.

## Amendments, 2026-11-12 (G5-2.2 directive)

- **D-018 (progress).** The headline is original-scope progress: verified work over everything ever planned, dropped and
  cancelled work included, so dropping work can never raise it. Active-plan progress is shown beside it. Dropped work is never
  verified, completed or delivered.
- **D-023 (human verification).**
  - The Owner's parameters: sample 10%, with no cap; at least 30 reviews in a rolling 30 days; 95% agreement.
  - A review is a decided verdict (agree or disagree); agreement = agree ÷ (agree + disagree).
  - Unsure is tracked separately and counts as neither.
  - A disagreement never reopens work automatically.

## Amendments, 2026-11-12 (G5-2.2 Milestone 2: operational validation)

**Status:** Implemented on `dev/g5-2.2` (`51d84a9`..`bd63d98`). Not deployed. Evidence: `G5_2_2_MILESTONE2_REPORT.md` (release prep).

- **D-024 (web): a live read, not a past fetch.**
  - The check reads the source now, through AXoR's server-side fetch (`web_read`'s, with its public-address guard, 8 s): the
    team's saved page for the host, or the host's home page.
  - PASS: a page with content.
  - FAIL: a wrong or empty source (a 4xx other than 408/429, an address that isn't public, a type `web_read` can't read, no
    content).
  - UNKNOWN: AXoR can't tell (a timeout, a DNS or connection failure, a 408/429/5xx, no host and no saved page).
  - A past fetch is reported, never the gate. This replaces G5-2.2's PASS on "design" evidence when no fetch existed.
- **D-024 (chain): failures of the collector are UNKNOWN.**
  - The team's own competition's snapshots, with the subnet and competition matched.
  - Fresh PASS, stale FAIL, missing UNKNOWN.
  - A collector whose latest read failed, with no fresh snapshot, is UNKNOWN (a retrieval failure); with a fresh snapshot it
    still passes, and the failure is shown.
- **D-021/D-025: unknown is unknown on every CLI path.**
  - The Codex drain takes a runs-at-once slot (the closing turn then gets its own time), and the budget decides its closing
    turn like any other call. Either refusing:
    Codex is stopped without it and the run is unmetered.
  - Claude Code use that was never reported is unmetered: a `claude -p` timeout or signal kill, a session turn cut by its
    timeout or a CLI that dies mid-message, a restart with a Claude Code run in flight.
  - An error result counts the usage it reports.
- **D-025: concurrency is bounded, not prevented.**
  - The gateway checks before each call against counted tokens, so concurrent runs can overshoot a stopping limit by one call
    each (Codex: one session each). This is measured and pinned by a test.
  - Reservations would make it strict; they are proposed, not built.
- **D-023: reviewers and tiers.**
  - A verdict needs a signed-in person's session (no user: refused).
  - Only the team's owner sees and reviews its sample.
  - Work a person approved themselves is never in their sample.
  - The console shows agent-approved, human-reviewed and independently demonstrated apart.
- **D-019: no key characters stored anywhere.**
  - Knowledge connector tokens, Mining command ingest keys and Drive share revocations store a sha256 fingerprint.
  - A syntax-tree test keeps a masked key or a key slice out of every write.

## Amendments, 2026-11-12 (G5-2.2 Milestone 3: budget integrity and real-world reliability)

**Status:** Implemented on `dev/g5-2.2` (`64e97d4`, `2ae6a49`, `312c99b`, `21f11b7`, `5413699`). Not deployed. Both suites pass at `5413699` (SQLite 1,208, Postgres 1,208). Evidence:
`G5_2_2_M3_REPORT.md` (release prep).

- **D-025: budget reservations.**
  - A model call under a stopping limit reserves its estimate before it goes out, in one transaction (`AuthDB.tx()`: SQLite
    `BEGIN IMMEDIATE`; Postgres `BEGIN` with an advisory transaction lock and a 10 s `lock_timeout`).
  - The check is spent + held + estimate against every stopping limit over the run: the owner's daily cap, `ac_limits` (global,
    system, mission, team, agent, task contract), and the systems' own budgets (a Competition team's 24-hour budget, a Company
    project's budget), as buckets.
  - Its reported use settles the hold exactly once, in the transaction that counts the tokens.
  - Estimated (`estimate`), bounded (`bound`) and measured (`actual`) use are kept apart in `ac_reservations`.
  - **An unknown outcome is never released as 0.**
    - An API call that failed without an answered error status, or was cut by a crash or an expiry, is charged at its bound
      (metering `charged`).
    - A CLI call is unmetered (D-025's estimate settles it).
  - A Codex session's turns keep their holds until the session reports usage.
  - Duplicate requests, by idempotency key, hold once and never run twice.
  - A refusal made only by holds is released on settlement.
  - No stopping limit over a run: no transaction, no write, the Milestone 2 gateway exactly.
- **D-024 (web): the retrieval path is hardened.**
  - Each connection goes to an address checked in the same lookup (no rebinding window).
  - IPv6 forms carrying an internal IPv4 address are refused.
  - Only http and https are opened, with no proxy from the environment, and at most 5 redirects, each checked.
  - A total deadline cuts the whole fetch.
  - A name that doesn't resolve is UNKNOWN, never FAIL.
- **D-023: owner review isn't independent verification.**
  - "Independently demonstrated" needs a reviewer independent of the team. None exists, so it is never awarded on a team
    owner's reviews.
  - The owner's threshold is reported as its own tier, at most "operationally tested" in readiness.
  - VERIFIED and REVIEW no longer say "independent": agent approvals set them.
  - A reviewer role is proposed, not built.
- **D-018: progress.**
  - Original scope is a fixed baseline: the board's first plan run and what a person or a template put on the board by its end.
  - The active plan is the baseline plus person-made additions, less what a person cancelled. Dropped work stays in it as not
    done, so dropping work raises neither figure.
  - Agent-made additions (follow-ups, later plan runs) are shown apart, in neither figure.
  - Derived at read time from each task's origin and creation, nothing stored. **The definition awaits the Owner's
    confirmation** (gap G-54).
- **D-017: inferred requirements stay advisory** until a person declares or confirms them, whatever their checks say (pinned by
  a test).

## Amendments, 2026-11-12 (G5-2.2 Milestone 4: production readiness, budget integrity, operational proof)

**Status:** Implemented on `dev/g5-2.2` (`0b12ac7`, `e56af3f`, `84eee42`, `30ecddc`, `a2f3ddd`). Not deployed. Both suites pass at `a2f3ddd` (SQLite 1,247, Postgres 1,247). A separate RC1 security hotfix sits on
`hotfix/rc1-web-security` (`b3e0274`, `957cefe`). Evidence: `MILESTONE_4_IMPLEMENTATION_REPORT.md` (release prep).

- **D-025: leases.**
  - A reservation carries a lease that its process renews while the call is in flight (a heartbeat). The lease runs out only
    when the process stops renewing it; the hold then lapses, charged at its bound or unmetered, never released.
  - Start-up lapses only expired leases.
  - Expired leases lapse in their own transaction.
  - A settlement that can't be written stops renewing, so the hold lapses.
- **D-025: three values.**
  - `estimate` is the prediction and is never changed.
  - `reserved` is what is held. An API call reserves its input estimate (1 token per 3 bytes) plus its provider-enforced output
    cap. `AXOR_RESERVE_STRICT=1` reserves the full bound.
  - `actual` is reported use. An actual over the bound is flagged.
  - Only an API call's output is capped by its provider. No hard spending guarantee is claimed for any call, CLI calls least of
    all.
- **D-025: failures.** A CLI call that failed is released only when the model never ran (sign-in, installation, a usage limit the
  CLI reported up front); anything else is unmetered. Buckets fail closed on unmetered runs. OpenAI-style structured calls are
  capped at 4,000 output tokens.
- **D-024 (web):**
  - Ports are limited to `AXOR_WEB_PORTS` (default `80,443`).
  - Name resolution runs inside the fetch's total deadline, and connects take at most the time left.
  - An invalid certificate is refused, classed UNKNOWN.
  - `live_data:chain/query` (chain storage beyond the snapshots) is FAIL until a read-only chain-query tool exists (D-026
    candidate), never PASS on snapshot freshness.
- **D-024 (web), D-017:**
  - The competition importer reads within its total deadline on the candidate, as on the hotfix.
  - A storage map (`Uids[…]` and the like) or a raw subtensor query infers `live_data:chain/query`, never the snapshot check.
- **D-023:** a changed sample verdict keeps its history in the audit: the previous verdict and its note.
- **D-018:**
  - Scope changes a person makes on a board (adding or deleting a task) are recorded on the board's append-only event log
    (`mw_events`, kind `scope`): author, time, task, reason, and the original scope's and active plan's sizes before and after.
  - Older person-made tasks name no author ("you"): nothing is backfilled.
  - A board task the dispatcher places is recorded as placed by automatic dispatch, on the person's behalf.
  - The leading figure is the Owner's setting (`progress_headline`: `original`, the default and the last headline decided, or
    `active`). Every figure is shown either way.


## D-029 · G5-3 risk feeds: what feeds the one register, and how

**Status:** Proposed, 2026-11-13. Built on the local branch `dev/g5-3-risk` (R3.1, R3.2, R3.4); not merged or deployed.
**Order:** G5-3 started in parallel with D-004 D4.3, on the user's instruction in the session of 2026-11-13 ("Okay, start
G5-3"). This amends D-014's order (D-004 → G5-3) for R3.1, R3.2 and R3.4 only. R3.3 still follows D4.3.
**Full record:** `owner-decisions/g5-plan/g53/DECISIONS_20261113.md` (G3-1 to G3-17).

**Decision (extends D-012).**
- **Feeds.** Six feeds run from the orchestrator's `tick`, at most every 300 s: `io_diag`, `io_sbx`, `hq_issues`,
  `ac_alerts`, `mo_alerts` and `mh_alerts`. Market alerts are not fed (K-5).
- **Diagnosis feeds** (`io_diag`, `io_sbx`):
  - Three failures of one class that isn't the work's own, in one scope, within 24 h, make one row.
  - The row stays open while that class still shows and resolves after a quiet window.
  - The scope is never invented. It is `mx:N` only from an `mx:` corr, otherwise the run's team, otherwise the owner's own work
    (`mission` NULL).
- **Alert feeds:** a row is open exactly while its source item is open, so the register's counts equal the source's.
- **Organization rows.** Agent HQ issues, and Agent HQ's own runs (recorded with owner 0), are kept under owner 0 with
  `mission` NULL. They are shown to, and accepted by, administrators only.
- **Own rows only.** A feed writes only when its source changed, and touches only rows of its own source. Verify and Approve
  stay readiness-only.
- **T-9.** The register never holds a task or applies a change.
- **`critical`.** Feed rows are never critical, so the Owner may accept them. Consequence: until this is revisited, R3.3's
  "critical risks trigger an early cycle" can't fire from a fed row.

## D-030 · Reach is proven from inside the sandbox; a `git` capability

**Status:** Approved by the Owner, 2026-11-13 08:00 UTC ("I approve your decision", in reply to this entry being put to the
Owner as "yours to approve or reject"). The approval is of this decision as written. It is not a deployment authorization and
covers no production action: dispatch, budgets, the runner's cluster objects, the package-host list and Vault stay separate
decisions. Built on the local branch `dev/g5-mx-exec` (stream W7, "Mission Execution Recovery" directive); merged into the
integration candidates, not deployed. The number was allocated by the integration owner (`INTERFACE_CONTRACTS.md`, IC-9).
**Contract:** IC-10, "reach proof": `owner-decisions/g5-plan/mx-exec/G5_EXECUTION_API_CONTRACT.md` §2 to §4.
**Evidence:** `owner-decisions/g5-plan/mx-exec/staging/run4/` (21 of 21 checks on host Docker, with the production sandbox
image and AXoR's own egress proxy); `tests/unit/test_mission_exec_access.py`.

**Decision (amends D-011's `internet` probe; extends the capability list of G5-1).**
- **`internet` passes only on what a run did.** PASS needs both: the egress proxy is healthy now, and a finished run of the
  team reached at least one host from inside its sandbox in the last 7 days (the run's own network record). The proxy answering
  AXoR's own server is no longer proof by itself.
- **With no such run, AXoR measures.** It starts one check run in the team's sandbox (fixed command, none of the team's files,
  no inference; the row's `by_user` is `AXoR readiness check`; at most one per team and target per 10 minutes) and answers
  UNKNOWN until that run has ended.
- **What counts as an answer.** Only a check run that ran to its end in the sandbox (`done` or `failed`). One that never ran
  (`error`, `timeout`, `cancelled`) is no answer: the probe stays UNKNOWN and measures again. A failed check is FAIL for 15
  minutes, then it is measured again.
- **`git:<host>/<owner>/<repo>` is a capability.** Declared by a person or a planner, suggested from a clone in the task's
  words. It passes on a run of the team that checked that repository out (the evidence names the commit, read by the sandbox
  runner itself), or on `git ls-remote` in a check run. A source a Docker job only states (`basis: "declared"`) is not proof.
- **A failure says what failed.** The probe's answer carries one class (`sandbox.reach_class`): no executable, private
  repository, credentials rejected, refused by the egress policy, no internet, DNS, connection, timeout, or the command's own
  failure. A repository that asks for a login is reported as private, not as a broken git.
- **A run's source record.** After its command ends, the sandbox runner reads the git checkouts left under `/work` and `/repo`
  and returns remote and commit; they are kept on the run (`mw_sbx.src`, nullable).

**Consequences.**
- A team whose declared-internet tasks passed on the proxy alone is held for about one dispatcher pass while the first check
  run runs, unless it already has a run that reached a host in the last 7 days.
- Check runs are ordinary sandbox runs of the team: they take a sandbox slot for a few seconds, and the register's sandbox feed
  leaves them out (G5-3, `risk_feed_sbx`).
- Private repositories stay unreachable for agents: runs carry no repository credentials. Lending a read-only token to a run
  is a separate decision for the Owner.
- `READINESS_NET_CHECK=0` turns the check runs off; probes then answer UNKNOWN and say what to run.


## D-031 · Which rule promotes a competition team's agent

**Status:** Decided by the Owner, 2026-11-13 11:09 UTC ("I approve all", answering a list that named this decision): the second
rule, as recommended. Built for the Upgrade Factory on `dev/g5-5-l54b`. Development only: nothing is deployed. The Owner was told
that it removes a working promote button and can reverse it.
**Raised:** 2026-11-13 from G5-5 L5.4b part B.
**Number:** allocated by the integration owner (`owner-decisions/g5-plan/parallel/`, PX-B10). D-030 is W7's reach proof.

**The question.** Two approved rules disagree for competition team agents (`mw_agents`):

| Rule | Says | Effect on the Upgrade Factory, which promotes team agents on a model-scored exam plus a person's hash-bound approval |
|---|---|---|
| K-29 (Owner, 2026-11-13) | Promotion on measured evidence **or a person's approval** | Stays as it is |
| L5.4's row in the plan, as built (C2-9) | A team agent is promoted **only on internal measured evidence**, by a person | Its promote is always refused; it becomes a screening step that opens a gate proposal and a trial |

**Recommendation (the G5-5 builder's):** the second, as one rule for every path to a team agent. It removes a working promote
button, so it needs the Owner's yes.

**What the answer settles:**
- the Upgrade Factory's promote;
- Improvements' promote for team agents;
- Workforce (model-judged trials plus a person);
- self-improvement mode (measured on real eval checks, no person).

**What is built on the answer:**
- The Upgrade Factory's promote is a screening step (`mining_upgrade.decide`): it opens a gate proposal for the agent, origin
  `upgrade`, and writes no instructions and no version. The proposal needs a trial's measured evidence and a person, like any
  other team-agent proposal. It is the only promotion path that wrote a Competition team's agent (`mw_agents`).
- K-21 of part B was built before: "apply untested" is refused (`mining_improve.decide`).

**Three more paths: left as they are (2026-11-13, 12:55 UTC).** The recommendation said the same answer settles three more
paths. None of them writes a Competition team's agent, so the rule as approved ("every path to a team agent") doesn't reach
them by its own words. Asked whether the rule should cover them, the Owner answered "you decide"; the G5-5 builder decided to
leave all three unchanged. That is the builder's decision under the Owner's delegation, and the Owner can change it:
- Improvements' promote (`mining_improve.decide`): Workflow agents, measured on real eval checks, promoted by a person.
- Self-improvement mode (`mining_evolve`): Workflow agents of an opted-in Workflow, measured on real eval checks, no person.
- Workforce (`workforce.decide_improvement`): Workforce agents, model-judged trials plus a person, which K-29 allows.

**Rollback note:** a candidate sent to trial is recorded as `screened` with its proposal id (`au_agents.gate_proposal`, nullable).
RC1 doesn't know that word: it shows such a row as "Rejected" and refuses to act on it again. Nothing else changes for RC1.

## D-034 · A release freezes its measuring job

**Status:** Decided under the Owner's delegation, 2026-11-13 13:35 UTC. The Owner was shown this decision (as row F of
`owner-decisions/g5-plan/e2e/G5_LEARNING_LOOP_VALIDATION.md`) and answered "you decide"; the runner's builder decided yes. It
is not the Owner's approval of this text, and the Owner can change it. Number allocated by the integration owner. Development
only: nothing is deployed.

**The problem.** A benchmark row counted as measured when a VM job's kept result was intact and said the row's score. Nothing
said which job. Any job whose command wrote a score file could be filed under the frozen suite's name, so a team's own mock
validator could stand in for the official scorer.

**The decision.** A release may freeze its measuring job. For such a release a row is job-measured only when the job behind
it is that job. A release without one behaves as before.

| Part | Rule |
|---|---|
| What is frozen | The job's spec without the run's id, the proxy tokens and the declared source; the hash of its harness files (every file sent into the job outside the release's candidate folder); the digests of the images it pulled; the score file's path |
| Who freezes it | A person, on the release form, from a finished VM job of the team and the candidate folder. The folder is the release's, never the job's |
| Where | `mw_release.measure` (nullable JSON). The runner's kept result lists the job's files one by one (`inputs.tree`) |
| The check | `runner.backed(..., measure=...)`, called by the release's own readers, a trial's evidence, the mission's internal measure, Analytics and the performance view |
| A score from another job | Kept, not comparable, with the reason; the mission's measure reads it as unverifiable |
| A trial | Both releases must freeze the same measuring job, or its evidence doesn't count |

**Limits.** The candidate still controls its own image build and what its container answers. The harness writes the score file
inside the same VM. A scorer that draws at random is noisy in one run. An agent-filed number after a clean sandbox run is
still valid for a mission's own evaluation (Q-4); it is never measured.

**Consequences.** A new nullable column; an older version ignores it. No change for any release that freezes no measuring job.

## D-034a · A frozen release names its candidate (amends D-034)

**Status:** Decided under the Owner's delegation of 2026-11-13 13:35 UTC ("you decide", which covered D-034 itself), by the
integration owner on the runner builder's proposal, after the SN61 session raised the gap. It narrows what counts as measured
and widens nothing the Owner decided. It is not the Owner's approval of this text, and the Owner can change it. Development
only: nothing is deployed.

**The problem.** D-034 froze the measuring job: its spec, its harness files, the images it pulled, its score file. The
candidate's own files were outside all of them, by design, so that the same job could measure the next candidate. But then
nothing said *which* candidate a release measured. After a freeze, a job on any later contents of the candidate folder was
still that release's measuring job, and the seven runs meant to describe one candidate could be runs of three.

**The decision.** At freeze, the release also keeps the hash of the reference run's files under the candidate folder
(`candidate_sha256`: the same per-file list as the harness hash, the other half of it). A job counts for that release only when
it is the measuring job **and** its own candidate hash equals the release's. Otherwise it reads: "it measured another candidate
than the one this release froze: freeze a new release to measure it".

| Part | Rule |
|---|---|
| A new candidate | Is measured by a new release, frozen from a run of that candidate |
| A trial | Its two releases measure with the same job (spec, harness, images, score file) and different candidates. The trial's "same job" check compares the job only, never the candidate |
| A release frozen before this | Kept no candidate hash and can't say: for it any candidate under the folder counts, as before. Freeze it again to get the rule |
| With the mission workspace (D-032c step 1) | A job may name the workspace snapshot that holds the frozen candidate, so the same candidate can be measured again after the workspace has moved on. The snapshot's number is not part of the measuring job's hash; the candidate hash is what ties it down |
| What an agent is told | A finished bench job's result says at once whether it was the current release's measuring job on that candidate, and why not |

**Limits.** As D-034's. The hash covers the text files sent into the job under the candidate folder; what the candidate's own
image build fetches is not in it.

**Consequences.** No new column: the hash is one more key in `mw_release.measure`. Releases frozen earlier are unchanged.

## D-035 · AXoR's own Docker check job

**Status: Proposed (2026-11-13). Number allocated by the integration owner. Built on `dev/g5-mx-exec-vmcheck` for development and
staging only; it needs the Owner's approval, and it is not a deployment authorization.**

**Problem.** The `docker` readiness probe (D-013 design §6) passes only on a VM runner job that finished cleanly on the current
base disk in the last 7 days. Only an agent's `docker_job` call starts a job. A task that declares `docker` is held while the
probe is UNKNOWN. So on a fresh server, after a deploy, after a base-disk rebuild or after seven quiet days, every task that
correctly declares `docker` waits for a job that nothing can start. Found on 2026-11-13 while proving the agent-to-VM path in
staging; confirmed by the runner's builder.

**Decision.** When a live probe (a dispatch or a person's Re-check, never a page being read) finds the runner ready but
unproven, AXoR starts one check job itself, as it does for internet reach (D-030):
- the job is fixed in code: kind `run`, no network, no image, no artifact, no score file, 1 CPU, 1,024 MB, 60 s, command
  `docker version && docker info`;
- it goes through the same `Work._docker_job` an agent's call does, so its row and kept result are what the probe already
  reads, and an emergency stop ends it like any job; no team file enters its VM;
- one at a time for the whole server (the probe's answer is server-wide); it waits its turn for a VM;
- its row is by "AXoR readiness check": never team work, never a team's sandbox failure, never evidence of a score;
- a check job that ran and failed is the answer (FAIL, with its reason) for 15 minutes, then it is measured again;
- the probe's PASS says whether a check job or an agent's job proved it, and that it shows a VM, the Docker daemon and the
  result's hand-over on this base disk: nothing about registries or the cluster's network policy.

**Two changes that make it work end to end** (found by running it on a real VM in staging, 2026-11-13; they also apply to
D-030's check runs):
- an UNKNOWN that only means "AXoR's own check is under way" is asked again after 30 seconds instead of the usual 10 minutes;
- the periodic pass re-checks a board whose tasks are held for readiness, but **only while a check AXoR itself started for
  that team is under way**: for 15 minutes after the check was started, and for at most three checks per team per hour.
  Before, a task stayed held after its check had passed until something else moved the board. Every other readiness hold
  (a private repository, a failing sign-in, an unverified credential) waits for an event or a person, exactly as before:
  re-probing those on every pass would start check runs and real sign-in prompts for as long as the task stays held. (The
  first version of this change did exactly that; it was corrected before any image was built from it.)

**What counts as the check failing.** Only a check job that ran in a VM and did not finish cleanly. One that never got a VM
(the runner was busy, the pod never started, the server restarted) says nothing about the runner: the answer stays UNKNOWN
with that reason, and a new check is started after 10 minutes. A check row left "running" by a process that died counts for
20 minutes at most.

**Consequences.** One small VM job per base disk per week on a server whose teams use Docker. After a failure: one more every
15 minutes while a live probe keeps asking (a dispatch, or a person's Re-check), and the periodic pass stops asking after
three checks in an hour. Each check job, passed or failed in a VM, leaves one record file in the files of the team whose task
triggered it (`runs/sbx-<id>/result.json`).
Without the runner installed nothing changes: the probe stays FAIL.

## D-016 · Developer page: the administrators' own console

**Status:** Requested by Owner, 2026-11-11 (put the content of Agent Company's `docs/developer.md` into AXoR, as the last
item of the left sidebar): the page is approved by that request; the details below (sudo scope, what was not ported, an
unfiltered shell in the web process) await the Owner's confirmation.

**Decision.** AXoR gets one new admin-only page, **Developer** (`#developer`), ported from Agent Company's Developer page: a
file explorer and editor, terminals on the server and a Claude Code / Codex panel. New code only: `developer.py` (router,
`/api/dev/*`), `dev_files.py`, `dev_terminal.py`, `dev_claude.py`, `frontend/dvp-*.js`, `dvp.css`, vendored xterm.js,
pdf.js, mammoth and the Seti icon font. No new database tables (opened folders: `DATA_DIR/developer/roots.json`).

- It is the administrator's tool, not an agent system: shells run as the server's user with no command filter, Claude Code
  with every tool allowed in the opened folder. It is never used by agents, missions or teams, and no agent gate is
  loosened because of it.
- Access: every route needs an admin session; every change (files, opened folders, uploads, terminals, stopping other
  processes' sessions, deleting history) also needs sudo, as Machines' console does; stopping the page's own runs and
  closing its own terminals don't. Owner, 2026-11-11: the Claude panel's composer (sending a prompt, pasting or attaching
  files) needs only the admin session, so typing there never brings up the password box; those prompts are still audited
  (`dev.claude`). The terminal WebSocket checks the admin session and the same-origin
  `Origin`. Everything that changes something is audited (`dev.*`).
- Shells and Claude runs live in the web process's memory: this relies on one web replica with one worker
  (k8s/base/30-axor.yaml), as Machines' console does.
- Not ported: Agent Company's per-model sign-ins (the panel uses AXoR's own Claude Code login, `llm._cli_env`), the
  General Manager panel on project pages, and "Developer is the home page" (AXoR's start page is unchanged).

## D-028 · Control Hub scene: the Overview drawn as the command room

**Status:** Requested by Owner, 2026-11-12 (a mock-up image: "Accurately implement the frontend interface, including its color
palette and animations"): the request approves the presentation. Details decided under the Owner's delegation, 2026-11-13
("you decide"): the scene stays the default Overview (G5-2's readiness gate reaches it through Next actions); the sidebar folds
to icons while the scene shows on wide screens, and stays unfolded for anyone who unfolds it; Mission health as defined below;
the Dashboard toggle is remembered per device. Not committed or deployed by this decision. Numbered D-028 because D-017..D-025
are taken on the dev branches, D-026 is the chain-query candidate and D-027 the proposed downgrade-fix port (register K-16, "new
entries from D-028"; K-16 is still a recommendation, so this number is provisional).

**Decision.** The Control Hub's Overview section (`#control`, no node) renders as the mock-up's scene by default. It is a presentation
layer only: no new view, route, nav item, endpoint or table. New code: `frontend/control-scene.js`, `control-scene.css` (prefix `ctl-sc-`),
`frontend/brand/scene-portrait.webp` (a colour cut-out of the public-domain Mona Lisa scan the backdrop already uses), rebuilt by
`tools/scene-portrait.py`. control.js gets four guarded hooks (`hubView`, `render`, `draw`, `stop`).

- It reads only `/api/control` and `/api/control/ops`. Every figure is one those already serve. **Mission health** = active missions
  (competitions + custom, paused left out) with health `met`/`on_track`, over those that are measurable (`unmeasurable` ones are
  counted in the caption, not as failures); with none measurable it shows agent run success (24 h) and says so in its caption.
  The mission band counts the ops console's five path states (PLANNED…VERIFIED); D-018's COMPLETED/DROPPED are not on it.
- It reads `/api/control/ops` exactly as Mission operations does (plain GET, never `fresh`): read-only, cached probes. When the
  server has G5-2's readiness gate (`ops.gate`), blocked missions and open critical risks lead **Next actions** and open the
  Dashboard's Mission readiness card, where they are decided; the scene itself decides nothing.
- Its links press the real sidebar buttons (or Control Hub sections), so access and the Sidebar layout still decide what opens.
- "Dashboard" brings back the Command Center cards and the other Control Hub areas. The choice is per device (`localStorage ctl.scene`).
- On screens ≥1280 px the sidebar folds to icons while the scene shows and comes back on leave. A person who unfolds it there keeps
  it unfolded (`ctl.scene.fold`).

## D-039 · General Manager chat: an assignment from any page becomes a mission

**Status:** Requested by the Owner, 2026-11-17 ("You should be able to communicate with the company's general manager from anywhere
on the website … chat icon in the upper right … text or images … a new mission is automatically created"). The request approves the
feature; the scope below was the builder's choice. Numbered D-039 because D-036..D-038 are taken (provisional, like D-028).
Branch `dev/gm-chat` (worktree /home/thomas/axor-gm-chat): committed c3bc757 (feature) + dea9aef (frontend/app rebuilt, Owner
2026-11-17), deployed to the non-production KVM VM (:8820) on the Owner's word; not pushed, not in production.

**Decision.** A chat button in the top bar of every page (classic UI `frontend/gm-chat.js` + `.css`, prefix `gm-`; React UI
`frontend/react/src/v3/app/GmChat.tsx`, prefix `ax-gm-`) opens one thread per person with the General Manager
(`backend/app/gm_chat.py`, `/api/gm`, table `gm_messages`).
- One small structured model call per message decides "assignment" or "reply" (metered as llm_usage source `gm`). An assignment is
  created with `Missions.create`, exactly as Mission Control's composer does: the person's own words are the goal, pictures and
  documents are staged through `POST /api/mos/uploads`, the page they were on is a resource, and a fixed constraint says that changes
  to AXoR itself are delivered for review and that deploying is an Owner approval. "Start as a mission" overrides a "reply".
- No new engine, agent system or permission. The gate is Mission Control's (anyone who may use agents). Limits, budgets, autonomy and
  approvals are the mission's own. Mission errors (three active, no model, token in the text) are said in the chat and create nothing.
- Cards in the thread follow each mission's status. A mission waiting for answers is answered in the card (`/api/mos/missions/{id}/answer`).
- **Not built here:** missions could not change AXoR's code. The engines read and draft. Superseded by D-040 for the Owner and
  delegates, when self-edit is switched on.
- The React bundle `frontend/app` was rebuilt with this change (Owner, 2026-11-17), which also brings the bundle up to date with the rest of
  the React source merged since its last build.
- Real model (VM, terminal:opus): the decision step sorted six sample messages correctly (2026-11-17). No chat mission ran on a real model yet.

## D-040 · Self-edit: a mission changes AXoR's own code; the Owner approves the exact commit before it merges

**Status:** Owner decision, 2026-11-17 ("you want missions to be able to edit AXoR's code themselves", answering the question raised
under D-039). The scope below was the builder's choice, made conservatively. Provisional number, like D-028. Branch `dev/gm-chat`.
It is off by default (`AXOR_SELF_EDIT=1` turns it on), and it is not in production.

**Decision.** A new mission engine, `selfedit` (`backend/app/self_edit.py`, table `se_changes`), runs on the existing AXoR Workbench
(`workbench/workbench.py`, the host service the Workflow uses). No new credential, sandbox or deploy path is added.
- **Who:**
  - Only the Owner or a delegate (`missions.may_steer`) can start one, and only on purpose.
  - The engine is offered to them alone, and the code drops it whenever a model picks it without it being forced.
  - The General Manager chat forces it when its decision says the assignment changes AXoR and the person may steer. Everyone else
    keeps D-039's review-only missions.
- **Where:**
  - Work happens in a dedicated clone registered on the Workbench, never the live checkout and never `main`.
  - Each change gets its own worktree, from the head of `SELF_EDIT_BRANCH` at that moment (the base is pinned).
  - The engineer is one `claude -p` run: Read/Edit/Write/Glob/Grep only, with no Bash and no web, and a budget cap.
- **Guards, in code:**
  - The change must have files.
  - It must touch no path under `SELF_EDIT_PROTECT`: deploy and cluster files, sign-in, egress and sandbox, AICP and agent copies,
    the Workbench, self-edit itself, the updater and DevOps.
  - The Workbench's `protect` list also refuses edits there.
  - "Changed no files" and "protected paths" stop the mission. A failing unit check replans, with the failing lines as feedback.
- **Approval:**
  - Delivery always raises a request of kind `selfedit`, bound to the change, commit, base and passing check run, whatever the
    mission's autonomy.
  - Only the Owner or a delegate decides it. At decision time the change must still be exactly that commit.
  - Approving makes the Workbench merge that commit (pinned merge: refused if the branch moved or the clone isn't clean). Rejecting
    drops the branch.
- **Not live:** a merge lands only on the clone's branch. Pushing and deploying stay the Owner's own steps, as before.
- **Limits:**
  - The Workbench runs on the host, so the non-production VM (whose guard blocks the host) cannot use it.
  - The engineer's cost is the Workbench run's, capped per run. It is not counted in the mission's dollar budget.
  - React source changes still need a bundle rebuild before they show.

**Verified (2026-11-17):**
- 13 unit tests (`tests/unit/test_self_edit.py`); full suite 3103 OK; the new tests also pass on Postgres.
- End to end, with a throwaway Workbench on 127.0.0.1 and a scratch clone, plus a local AXoR running the stand-in mission model and
  real Claude Code as the engineer:
  - A chat assignment became a selfedit mission. The real engineer made the one-line change, the checks passed, and the Owner's
    approval in Mission Control merged exactly that commit.
  - A request to edit `k8s/` was declined by the engineer. A direct probe showed the Workbench refusing Edit on that path.
  - A failing test on attempt 1 was replanned, and attempt 2 passed.

## D-041 · Assessment of 2026-11-18: measured scores, follow-up brake, reviewer independence, release hygiene, and a freeze on new subsystems

**Status:** Owner decision, 2026-11-18 ("Write this up as a document and do 1,2,3,4,5", answering the assessment's five numbered
priorities). The scope of each item below was the builder's choice, made conservatively. Two parts are **proposed, not decided**
and say so: the single place for the SN61 pilot (5b) and every production step listed under "Not done". Branch
`dev/assess-fixes-20261118`, off production's `2886643`.

**Why.** The assessment found a working platform with no measured result: team 23's candidate scored 0.037 on the official SN61
scorer (public baseline 0.047, validator gate 0.8) while the team's own mock had said 0.81; no mission has been verified by a model
that did none of the work; team 23 was paused on 2026-11-18 with 182 blocked tasks after agents kept adding follow-ups; GitHub
`main` was not what production ran; there was no CI and no scheduled backup.

**1 · A score is measured or it is self-reported.**
- Every team work, review and plan prompt carries one rule after the ground rules (`mining_work.SCORE_RULE`): a score counts only
  when a job running the official scorer wrote it and `record_benchmark` read it from the job's output file; anything else is
  called self-reported and never planned, approved or reported on as an improvement.
- `record_benchmark` says in its answer where the figure came from, and `Release.results` gives each row a `source`:
  `measuring_job` (the release's frozen measuring job wrote it), `job_output` (some VM job's output file wrote it, but nothing shows
  that job ran the official scorer) or `self_reported` (typed).
- What counts as a measurement is unchanged: D-034's frozen measuring job, and the mission's reader, which already reads a typed
  number on such a release as unverifiable (C5-5).
- **Partly done.** The rule and the labels take effect when this branch is deployed. The mock is not retired, and no measured
  score exists until a release with an official-scorer measuring job is frozen. The backup of 2026-11-18 02:54 UTC shows team 23
  with no frozen release and 29 benchmark rows, none comparable. Freezing one needs an agent's finished VM job on the official
  scorer image and then a person's freeze (Status → Release).

**2 · Blocked tasks count when follow-ups are rationed** (`mining_autoloop.followup_room`).
- Follow-ups per run: any number below the backlog cap, one at the cap, none at twice the cap. Open and blocked tasks both count.
- The Director's plan hold (`_backlog`, `plan_held`) is unchanged, so the Director can still plan a way out.
- When follow-ups are dropped for this reason, the board's log says so once per run.
- With team 23's board as it stood (182 blocked, cap 24) no follow-up is added until the blocked tasks are answered or closed
  down to under 48 open and blocked together.

**3 · A reviewer is independent only when its model did none of the work** (`missions._verify`, `_worker_models`).
- The reviewer avoids, and is compared with, every model that ran the mission's work: the allocation's model, the models of the
  team runs made for the mission, and the mission's other ledger runs. Before, only the allocation's model counted, although a
  team's runs are routed one by one.
- The verification record keeps `worker_models`.
- No mission was launched. The first real-model mission in production stays the Owner's, and a team mission cannot reach
  "verified" without item 1's measuring job.

**4 · Release hygiene.**
- GitHub `main` was fast-forwarded `1b663a0` → `2886643` on 2026-11-18 02:53 UTC, so `main` is again exactly what production runs.
  The auto-update timer was inactive, so nothing was deployed.
- `.github/workflows/unit-tests.yml` runs the unit suite on every push to `main`, `dev/**`, `release/**` and on every pull
  request, and fails when fewer than `MIN_TESTS` tests run. It is on this branch only, so it reaches `main` with this branch.
  Branch protection is not available on this repository's plan, so CI reports and does not block.
- `axor-backup.timer` is installed (daily 03:30 host time, with a restore test), pointing at the deploy clone
  `/home/thomas/axor-main-agent-access`. Backups still go to the same two mirrored disks as the data: there is no separate volume.

**5a · Freeze on new subsystems.** Until one team's candidate beats the public baseline on the official scorer, measured by a
frozen measuring job, no new module, page, table prefix or agent system is started. Fixes to gap-register items and to what a
running team needs are not new subsystems. For the open pull request #46 (AICP/AICAP) this means: it stays a draft, is not merged,
no new wave is started on it, and its flags stay off in production. The non-production VM is left as it is.

**5b · One place for the SN61 pilot (proposed under delegation, not acted on).** Proposal: production team 23, because the fixes
above are on production's code line and the VM runs another one. The Owner paused team 23 on 2026-11-18 and approved the VM pilot
on 2026-11-17 ("Pilot: yes, continue"), so the builder neither resumed team 23 nor stopped or changed the VM. The choice is the
Owner's.

**Not done (each needs the Owner's word or hands):**
- Deploying this branch. Items 1 to 3 are built and tested, not live.
- Putting team 23's limit back to stop mode. The builder tested the change offline and then tried it in production; the
  production write was refused to this session. The tested script is `/var/lib/axor/deploys/assess-20261118/limit_stop.py`
  (18,000,000 a day, stop mode, audit row; team stays paused). Stop mode also brings back the hold on runs with no reported usage
  (team runs are mostly on Codex and D-036 is not adopted), so resuming also needs D-036 or the Claude Code login.
- Freezing a release with the official scorer as team 23's measuring job.
- Replacing the Claude sign-in token that is in `main`'s history.
- A separate volume for backups.

**Known limit:** independence compares model names, so a run recorded as `codex:default` (87 ledger runs) counts as a different
model from `codex:gpt-6.1-terra` even if it resolved to it.

**Verified (2026-11-18):** `tests/unit/test_assessment_fixes.py`; the full suite in production's image; the touched test files on
a throwaway Postgres (497 OK); the workflow on GitHub Actions.

## D-042 · Owner's answers to D-041: deploy the fixes, pilot on production team 23, freeze a measured release, a backup disk

**Status:** Owner decision, 2026-11-18 ("1,3,4,6", answering the six numbered choices of the D-041 hand-off). Items 2 (team 23's
limit back to stop mode) and 5 (replacing the sign-in token in `main`'s history) were not chosen and stay open.

**1 · Deploy `dev/assess-fixes-20261118`.** Approved. D-041 items 1 to 3 go live with this commit; the deploy record is in
`/var/lib/axor/deploys/` and the deploy history.

**3 · The SN61 pilot runs on production team 23.** This replaces D-041 5b's proposal. The VM pilot approved on 2026-11-17 is not
the measured place: a measured win counts only on production team 23. Choosing the place is not permission to resume the team:
team 23 stays paused, and its limit is still alert-only (item 2 was not chosen), so resuming still needs the Owner, the stop-mode
limit, and D-036 or the Claude Code login.

**4 · Freeze a release for team 23 with the official scorer as its measuring job.** Approved, and **blocked on a prerequisite**.
- `Release.freeze` takes the measuring job from a finished VM job of the team that named a `score_file`. The backup of 2026-11-18
  02:54 UTC holds 39 kept results of team 23's VM jobs (32 clean): none named a score file, so none can be frozen from. Job #6933
  started the official challenge image but ran a detector test, not the scorer.
- Only an agent's `docker_job` call starts a VM job (`mission_ops`, D-035 note), and team 23 is paused.
- The official harness of the 11-17 re-score (`/home/thomas/axor-sn61-35/bench/bench.py`, 0.037 median against the public
  baseline's 0.047) is not in the team's files and writes no `{"score": …}` file.
- What it takes, in order: put the harness and a wrapper that writes `score.json` (`{"score": median, "tasks": runs}`) into the
  team's files; one team run whose `docker_job` runs it on `redteamsubnet61/rest-bex-challenge@sha256:1be22365…e089bb` with
  `score_file: score.json` and the candidate under `miner/bex_tracer/`; then a person freezes the release from that job (Status →
  Release: measure job = its id, candidate root = `miner/bex_tracer`). The reference score is the same job run on the public
  baseline miner, not a typed number. Freezing without a measuring job is not done: it would give exactly the `job_output` rows
  D-041 item 1 exists to tell apart.

**6 · A separate volume for backups.** Approved, and **needs hardware**: the host has only its two mirrored NVMe disks (`md0`–`md2`),
so there is nothing to attach from here. A loop file or a directory on the same mirror would not be separate. Once the Owner orders a
disk or a storage box and names it, `k8s/backup.sh`'s target moves to it (Issue #45). Until then backups stay on the mirror, with
14-day pruning.
