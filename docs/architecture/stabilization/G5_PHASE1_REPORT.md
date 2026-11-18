# G5-1 Report: failure taxonomy and task capability requirements

**Branch:** `g5/phase1` (worktree `/home/thomas/subnet-scout-g5`), from `main` at `d57098e`. **Not deployed. Not merged.**
**Scope (D-014):** gaps G-26 (five failure vocabularies) and G-27 (no capability requirements on tasks). Nothing is gated
in this phase.

**Status of everything below:** in source and unit-tested on the branch, and measured on the restored production backup of
2026-11-11 06:50Z. Not deployed, not observed on live production.

**Report #208.** Not available when G5-1 was written. It was read from live production on 2026-11-11 (report of
07:20:21 UTC) after the Owner's review, and its content doesn't affect G5-1. Its Docker-session plan is reviewed in the
separate SN61 readiness report.

**Revision after the Owner's review (D-015).** This report was revised for review item B5. Failure recognition moved into one
recognizer, Mission Control's recovery actions moved into the taxonomy, and the acceptance criteria changed per D5.

## 1. Implementation summary

### Failure taxonomy (G-26: partly closed)

- **One table.** `orchestrator.FAILURE_CLASSES` holds the 11 classes that `fail_class` returns, plus 9 canonical
  refinements: credential, capability, input_too_large, timeout, no_deliverable, invalid_output, test, strategy, cancelled.
- **What each class carries:** label, family (environment, limit, provider, work, control), G5 layer, own fault, whether
  retrying fixes it, and the recovery. It also carries each consumer's policy: Mission Operations' situation and recovery,
  the dispatcher's retry/never, and Autoloop's label and policy.
- **Derived tables.** These are now built from the one table, with the same values and key order:
  - `orchestrator.RECOVERY` and `OWN_FAULT`;
  - `intel_layers.FAIL_LABEL` (re-exported);
  - `mission_ops.RECOVERY`;
  - `control_dispatch.RETRY` and `NEVER`;
  - `mining_autoloop.LABEL` and `POLICY`.
- **`fail_class`** moved from `intel_layers` to `orchestrator`, unchanged; `intel_layers` re-exports it.
- **`failure(status, error, source)`** gives one reading of a failure: the canonical class, the legacy readings
  (`fail_class`, Autoloop, Mission Control, sandbox) and `conflict`. `conflict` is set when the canonical and legacy readings
  disagree on whose fault the failure is.
- **Recorded, not used.** The orchestrator's diagnosis also records the canonical class (`io_diag.canon`, a new column). Every
  decision still reads the legacy class `cls`.
- **New endpoint.** `GET /api/g5/taxonomy` (read-only) returns the classes, the policy conflicts and the owner's diagnosed
  failures by canonical class.

### Recognition and recovery in one place (B5, after the review)

- **One recognizer.** Every failure pattern is now in `orchestrator.py`, which these modules read from:

  | Patterns | Used by | Before |
  |---|---|---|
  | `AUTOLOOP_PATTERNS` | `mining_autoloop.CLASSES` and `.classify` | `mining_autoloop` |
  | `MISSION_PATTERNS` | `missions.FAILURES` and `.classify` | `missions` |
  | `SBX` | sandbox diagnosis | `orchestrator` |
  | `CREDENTIAL`, `CAPABILITY`, `NO_DELIVERABLE` | canonical refinements | new |

- **`recognize(status, error)`** reads one error once in every vocabulary.
- **Mission Control's recovery actions** (`missions.RECOVERY`: pause, deliver, retry, replan, stop) are now
  `orchestrator.MISSION_ACTIONS`, beside the other policies.
- **Still three ordered pattern lists.** The vocabularies overlap and mean different things (§5, D5), so merging them into one
  list would change outputs. That is the documented reason they stay separate.
- **Unchanged, with the reason:**
  - `agent_core.terminal_state` gives a run's end state (success, failed, timeout, cancelled, restarted), not a failure class.
  - `llm.limit_kind` sorts provider limits into exceptions before an error text exists.
- **Not yet applied:** the Owner's D1–D4 (D-015) change policies, not structure, and are G5-2. No decision reads the
  canonical class yet.

### Capability requirements (G-27)

- `task_lifecycle.CAPABILITIES` defines 10 capabilities: docker, registry, vm, internet, postgres, clickhouse, gpu,
  ram:<GB>, credential:<name>, approval.
- **Declared needs** are stored on both kinds of task: `ctl_tasks.needs` and `mw_tasks.needs` (new nullable columns, JSON).
  - They are set through the Control Hub contract (`ContractIn.needs`) and the board's add and patch (`TaskIn.needs`,
    `TaskPatch.needs`), and checked by `parse_needs`.
  - A Control Hub task's declared needs go with it when it becomes a board task (`control_missions._to_board`).
  - Agents' follow-up tasks do **not** inherit their parent's needs. A follow-up is different work; its text is read instead.
- **Inferred needs** are computed from the title and detail by `infer_needs` whenever they're read.
  - That way they cover every board task, whichever of the 7 insert paths made it, and they follow edits.
  - Each inferred need names the words that triggered it.
- **Order.** `needs_of` lists declared needs first. A declared capability replaces the inferred one for the same capability.
- **Where they appear.** They are returned by `contract()` and by the board API's task list. **No page displays them yet,
  and no dispatch decision reads them.**

## 2. Source changes

| File | Change |
|---|---|
| `backend/app/orchestrator.py` | `FAILURE_CLASSES`; derived tables; `CONFLICTS`; `fail_class` (moved); `failure()`; `io_diag.canon`; `taxonomy()`; `GET /api/g5/taxonomy` |
| `backend/app/intel_layers.py` | Re-exports `FAIL_LABEL`, `fail_class`, `SANDBOX`, `TOOL` from `orchestrator` |
| `backend/app/mission_ops.py` | `RECOVERY` = `orchestrator.OPS_RECOVERY` |
| `backend/app/control_dispatch.py` | `RETRY`/`NEVER` = `orchestrator.DISPATCH_RETRY`/`DISPATCH_NEVER` |
| `backend/app/mining_autoloop.py` | `LABEL`/`POLICY` = `orchestrator.AUTOLOOP_LABEL`/`AUTOLOOP_POLICY` (`CLASSES` patterns unchanged) |
| `backend/app/task_lifecycle.py` | `CAPABILITIES`, inference rules, `parse_needs`, `infer_needs`, `needs_of`; `ctl_tasks.needs`; contract and `ContractIn` |
| `backend/app/mining_work.py` | `mw_tasks.needs`; `TaskIn`/`TaskPatch.needs`; `_needs()`; board API `needs` |
| `backend/app/control_missions.py` | `_to_board` carries declared needs (`_declared_needs`) |
| `backend/app/mining_autoloop.py` (B5) | `CLASSES` = `orchestrator.AUTOLOOP_PATTERNS`; `classify` → `orchestrator.autoloop_class` |
| `backend/app/missions.py` (B5) | `FAILURES`/`RECOVERY` = `orchestrator.MISSION_PATTERNS`/`MISSION_ACTIONS`; `classify` → `orchestrator.mission_class` |
| `tests/unit/test_failure_taxonomy.py` | 11 tests (new) |
| `tests/unit/test_task_needs.py` | 13 tests (new) |
| `tools/g5/char_failures.py`, `tools/g5/char_diff.py` | Re-runnable before/after characterization (no data committed) |

**Schema:** three nullable TEXT columns: `ctl_tasks.needs`, `mw_tasks.needs` and `io_diag.canon`. They are added the way each
module already adds columns at start. Nothing is removed or renamed.

**Deferred for Owner approval:** planner tool schemas don't ask for needs yet. Changing a strict tool schema changes what
planners must output.

## 3. Automated test results

| Run | Result |
|---|---|
| New test files only | 35 tests (24 new plus fixture classes they import), OK |
| Full suite, SQLite | **911 OK (7 skipped)**: 865 existing + 46 from the new files (24 new tests, plus fixture classes they import running again) |
| Full suite, Postgres (`--postgres`) | **911 OK (5 skipped)**. An earlier run found one Postgres-only error in the new `taxonomy()` query (42803: the compatibility layer wraps `cls` in `MAX()`, so `GROUP BY 1, 2` named an aggregate). It was fixed with explicit `GROUP BY` columns; SQLite had not caught it (gap G-12) |
| `import app.main` (web image, branch tree) | OK. All modules load, including the new import order (`intel_layers`, `mission_ops`, `control_dispatch` and `mining_autoloop` now import `orchestrator` at load). |

## 4. Regression results

| Check | Baseline `d57098e` | `g5/phase1` |
|---|---|---|
| Unit suite, SQLite | 865 OK (7 skipped) | **911 OK (7 skipped)**: 865 existing + 46 from the new files (24 new tests, plus fixture classes they import running again) |
| Unit suite, Postgres | 865 OK (5 skipped) | **911 OK (5 skipped)**. An earlier run found one Postgres-only error in the new `taxonomy()` query (42803: the compatibility layer wraps `cls` in `MAX()`, so `GROUP BY 1, 2` named an aggregate). It was fixed with explicit `GROUP BY` columns; SQLite had not caught it (gap G-12) |
| Every legacy classifier's reading on the corpus, final tree vs `d57098e`: `fail_class`, Autoloop, sandbox class, Mission Control class, terminal state, dispatcher policy and both recovery tables. 197 rows: 97 distinct production error strings plus 100 synthetic. | — | **0 differences** (`tools/g5/char_diff.py`) |
| Consumer constants, 13 tables | — | **0 differences**; key order pinned by `test_every_consumer_table_keeps_its_values_and_order` |

The corpus has 935 failed runs, sandbox runs and team runs, taken from the 06:50Z backup copy. It is kept outside the
repository.

## 5. Evidence against the acceptance criteria

The roadmap criterion for G5-1 is "legacy classifier outputs unchanged on the real error corpus; crosswalk conflicts
counted; requirements measured on SN61's real tasks".

**T-7, as revised by the Owner (D-015 D5).**
- Zero changes in each legacy classifier's output: met (§4).
- Cross-classifier conflicts measured: see below.
- Representative examples and the overlapping vocabularies: see below.
- Regression tests kept: yes.

**Why the vocabularies overlap.** Each reader answers a different question about the same text:
- **Autoloop** decides whether a team task's failure counts against the task (run classes).
- **Mission Control** decides what a mission does next (mission classes → pause, deliver, retry, replan, stop).
- **The run ledger's end state** says how a run ended.

So the same words land in different classes on purpose:
- "timed out" is a transient run failure to Autoloop, a missed deadline (→ deliver) to a mission, and `timeout` to the ledger.
- A plan's usage limit is `quota` to Autoloop and `api` (→ retry) to a mission.

**Representative cross-classifier readings** from the real corpus (06:50Z copy). Columns: `fail_class` / Autoloop / Mission
Control / run end state.

| Runs | Example error | Readings | Canonical |
|---|---|---|---|
| 258 | "Claude Code plan rate limit reached; runs resume after the reset…" | quota / quota / **api** / failed | quota |
| 184 | "Claude Code on the server isn't signed in. Run `claude setup-token`…" | **task** / task / **model** / failed | credential |
| 72 | "Stopped by a server restart." | restart / **transient** / infrastructure / restarted | restart |
| 40 | "Claude Code timed out after 150 s…" | transient / transient / **deadline** / timeout | transient |
| 33 | "The sandbox is busy (2 runs at once)…" | sandbox / **task** / environment / failed | sandbox |
| 10 | "…the run can't have it: The egress proxy doesn't answer…" | transient / transient / **api** / failed | transient |
| 6 | "Stopped at the task's token cap (105,043 of 60,000 tokens)…" | cap / cap / **unknown** / failed | cap |
| 325 | (empty error: sandbox code exited non-zero) | task / task / unknown / failed | task |

Bold marks a reading that differs from `fail_class`. Two of these matter under D-015 D2:
- the sign-in failure, which a mission would **retry** as `model`;
- the plan limit, which a mission would **retry** as `api` within hours of a reset that `quota` says to wait for.

| Criterion | Evidence | Met |
|---|---|---|
| Legacy outputs unchanged | 0 differences on 197 rows and 13 constant tables (§4) | Yes, on the backup copy |
| Conflicts counted | See below | Yes |
| Policy conflicts listed | See below | Listed, not resolved (Owner) |
| Unvalidated refinements | `capability`, `invalid_output`, `test` and `strategy` had **no hit** in the corpus; they are tested only on synthetic text. `capability` is narrowed to explicit wording ("is not set up", "switched off", "no docker"…), so ordinary code errors such as "No such file", `KeyError: 'missing'` stay `task` (tested). | Labelled |
| Requirements measured on SN61 | Inferred on comp 23's 571 real tasks: credential 28 tasks, docker 18, registry 11, approval 4, gpu 1, ram 1, internet 1 | See next rows |
| Docker inference, hand-checked | See below | Measured |
| Credential inference | Mention-based ("hotkey", `*_API_KEY`): it marks tasks that talk about a key, not only those that use one. **Low precision; not fit for gating.** | Measured, weak |
| Cost | `needs_of` over 571 tasks: about 42 ms per board view | Measured |
| Nothing gated | `test_nothing_is_gated_on_needs_in_phase_1`: a task declaring docker and vm is dispatched to its agent although no Docker exists | Yes |

**Conflicts on the real corpus (935 runs), canonical class vs legacy class:**

| Canonical | Legacy | Runs |
|---|---|---|
| quota | quota | 258 |
| **credential** | task | **184** |
| task | task | 153 |
| input_too_large | task | 112 |
| restart | restart | 72 |
| no_deliverable | task | 60 |
| transient | transient | 50 |
| sandbox | sandbox | 33 |
| cap | cap | 6 |
| timeout | task | 5 |
| cancelled | task | 2 |

Only one disagreement is about **whose fault** it is: 184 runs, one error, "Claude Code on the server isn't signed in". The
legacy classifier counts it as the work's own failure; it is a missing login. The other refinements agree with the legacy
reading on fault and only name the cause more precisely.

**Policy conflicts** (`orchestrator.CONFLICTS`):
1. The dispatcher retries `provider` and `tool` failures, while the recovery table says retrying can't fix them.
2. `budget`: the recovery table says it is retryable after a raise; the dispatcher never retries it automatically.
3. `credential` and `capability` are filed by the legacy classifier as the work's own fault.

**Docker inference, hand-checked on all 48 SN61 tasks that mention Docker:**

| Result | Tasks |
|---|---|
| Correct (needs a Docker engine) | 15 |
| False positive | 3: #2785, a runbook listing "push the image" for the user; #2864 and #3082, tasks that read about building or `docker run` |
| Miss | 1: #3188, "Run the docker steps … against the built image" |
| Correctly not flagged | 29 |

That is about 83% precision and 94% recall among tasks that mention Docker. Recall for tasks that need Docker without
mentioning it is not measurable from text. One rule change came out of the check: `images` was removed from the subcommand
list, because "Docker images" as a noun caused one false positive (#2858). A fresh sample of the other mention-only tasks was
then checked.

## 6. Remaining risks

- **Inference is text-based.** In G5-2, gating should rely on declared needs. Inferred needs should only raise a "confirm
  requirements" prompt and never block on their own.
- **The 184 credential failures** are still counted against agents by every live decision (legacy `task`). Changing that is a
  G5-2 policy decision. It is also the clearest case for preflight: a login check before dispatch would have stopped all
  184 runs.
- **Measured on a copy.** All measurements are on the 06:50Z backup; production has changed since (report #208 is newer).
- **The patch test is partial.** `TaskPatch.needs` is tested through `update_task` with a stand-in for `Work._task` (the
  board fixture has no full workspace). The board API's task list isn't covered, because the fixture stubs the board view.

## 7. Rollback

The branch is not merged or deployed, so nothing needs rolling back now. After a merge and deploy, revert the G5-1 commits
on `main` and redeploy. The three new columns are nullable and unused by the old code, so they can stay.

## 8. Owner decisions (D-015, 2026-11-11)

D1 credential failures no longer count against agents, and an authentication preflight runs before dispatch. D2 only transient
failures are retried (bounded backoff, jitter, idempotency). D3 planners declare `needs` under a versioned schema. D4 only
declared needs block, verified against the real environment; inferred needs ask for confirmation. D5 the revised T-7 criteria.
D1–D4 are G5-2 work.
