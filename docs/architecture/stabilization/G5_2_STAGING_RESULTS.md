# G5-2 Staging Results (run of 2026-11-11, 14:30–14:41 UTC). **Stopped at a critical finding**

**Environment.** This host, Docker, no production cluster changes:
- **Database:** the restored backup `20261111T065017Z` (verified) in `axor-stg-pg`, on an **internal** Docker network with no
  route out.
- **App:** two web replicas (`axor-stg-web1`, `-web2`) running PR #5's code (`g5/phase2` @ `d975c26`) on the
  `axor/web:1aff3fd-20261111071938` image's dependencies, with the **fake model**.
- **Access:** a localhost-only relay (`127.0.0.1:8877`) to web1.

**Isolation (Owner §2B), verified before any dispatch:**

| Requirement | Evidence |
|---|---|
| No production registration or submission credentials | Web environment variable names: `AGENT_CLIENT_FACTORY ANTHROPIC_API_KEY(=staging-none) AUTH_METHOD AXOR_STAGING DATABASE_URL DATA_DIR …` (full list in scratchpad `stg/iso-env-names.txt`); 0 variables matching wallet, hotkey, coldkey, mnemonic, Docker Hub, GitHub, OAuth, Claude Code, OpenAI, OpenRouter or registry; 0 stored login tokens in the copy (`cli_accounts`); MCP records hold secret *names* only |
| No production image pushes or external writes | Internal network: `https://pypi.org` from web1 fails name resolution; no Docker socket in the containers |
| Dedicated test team, disposable resources | Team `comp:24` "G5 staging test team" made in the copy; every other team `paused=1, autopilot=0`; every user's Control Hub on `manual`; every other account disabled |
| Minimal network | Only the database (internal) and the relay (localhost) |
| Explicit budgets | Copy's `ac_limits`: staging global 100k tokens per day (20k per call), test team 50k per day (10k per call); team budget 200k; fake model (no provider key) |
| Cleanup | Pending (the run stopped). All containers are **stopped**; to remove: `docker rm -f axor-stg-web1 axor-stg-web2 axor-stg-relay axor-stg-pg; docker volume rm axor-stg-data1 axor-stg-data2; docker network rm axor-stg-int axor-stg-pub` |

## The ten checks

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | Internet probe | **Not run** | Needs the production egress secret and cluster access from staging, which this run doesn't have (Owner decision below) |
| 2 | Sandbox service probe | **Not run** | Needs the sandbox namespace (Kubernetes) from staging |
| 3 | Real sign-in probe | **Signed-out path: PASS. Signed-in path: not run** | Re-check on `comp:23` and `comp:24` ran the real probe against the image's Claude Code CLI, which had no login: FAIL "Claude Code on the server isn't signed in…"; every task of those teams was held, critical. **No prompt was sent** (the CLI's sign-in status failed first). The signed-in path needs a dedicated test login. |
| 4 | Kubernetes quota read | **Not run** | The RBAC rule is in the branch's manifest only; applying it is a cluster change. Earlier evidence: the probe code on live cluster answers (G5_PHASE2_PROGRESS.md, M2). |
| 5 | Gate on actual mission tasks | **PASS** | Copy of SN61 (`comp:23`): Docker declared on the 16 confirmed tasks. After Re-check via the API: 268 open tasks = SQL 268; 8 open Docker-declared tasks = SQL 8 = 8 Docker risks (the other 8 are done or waiting on a person, so not dispatchable); plus 1 sign-in risk (no login in staging). `comp:22`: PASS, 142 open, 5 to confirm. |
| 6 | Dispatch on the seeded team | **CRITICAL FAIL (stopped)** | See below |
| 7 | Risk register persistence | **PASS** | web1 restarted: `io_risks` identical (9 rows, same ids, `seen`, status); the next Re-check updated `seen` 1 → 2 on all 9, no new rows |
| 8 | Concurrent requests across replicas | **Re-check race: PASS. Dispatcher race: not run** (stopped) | Both replicas signed in, then Re-check of `comp:23` fired at the same instant on web1 and web2: web1 200, web2 429 "Checked 0 s ago"; one `mo_rechecks` row; the sign-in check ran once. The dispatcher claim race is covered by the unit suite on Postgres (`ConcurrentRetry`). |
| 9 | Control Hub in the browser | **Not run** (stopped) | Earlier evidence on the test server (G5_PHASE2_PROGRESS.md, M4 and corrections) |
| 10 | Rollback rehearsal | **Not run** (stopped) | — |

## Critical finding (check 6): budget refusals spin Autoloop

**What happened.**
- Test team, three tasks created and started through the API:
  - `docker` (declared): **correctly held**, `docker FAIL`;
  - the two others: first **correctly held** by the failing sign-in (agents on the Claude Code plan).
- After pointing the two agents at the fake API model and pressing Re-check, both started.
- **Every run failed instantly** with "Over the global token budget of Staging hard limit: 30,771,653 of 100,000 tokens today".
- Autoloop classed each as `budget`, put the task back in the queue ("not counted"), and the board started it again at once:
  **199 runs in 38 s** (14:39:56–14:40:35 UTC), all failed, **0 tokens** (the gateway refused before any model call).
- Pausing the team stopped it immediately.

**Why.**
- The restored copy holds the owner's real usage for that day (30.8M tokens), so the staging hard limit was already exceeded.
- Autoloop's `failed()` handles `budget` by requeueing the task with no wait (`mining_autoloop.py:234-237`, unchanged since
  `d57098e`).
- The board's start gate (`Autoloop.gate`) watches the **team's** 24-hour budget, not `ac_limits` (global or scoped limits),
  so nothing stops the restart.

**Scope.**
- **Pre-existing, not introduced by G5-2:** the same code is in `main` (`5862bed`) and in `d57098e`.
- **Production today:** 0 hard limits (`ac_limits` empty in the backup), so it hasn't triggered. It **will**, for any team
  whose owner has a hard limit set and crossed, which is exactly what G-14 recommends setting.
- **Effect:** CPU and database churn plus thousands of failed run rows per hour, not token spend.

**Proposed fix (not implemented: needs the Owner's approval).** Apply G5-2's own decision for `budget` (`decide()` → `hold`)
in Autoloop:
- on a budget refusal, hold the task (`hold='budget'`) instead of requeueing it;
- cool the team until the limit's window resets (next day for `day`) or the Owner raises the limit;
- make the board's start gate ask `agent_core.over()` before starting work, so a refused team starts nothing.

Tests:
- a refused run is not restarted within the window;
- a raised limit releases the task;
- no more than one failed run per held task.

## Model usage and infrastructure
- **Model usage: 0 real tokens.** The fake model is used and there's no provider key. The sign-in probe sent no prompt (no
  login). The 199 loop runs show 0 tokens.
- **Infrastructure:** one Postgres (restored copy), two web replicas and one relay, for about 11 minutes. The loop was
  bounded by the pause and caused no disk-space issue.

## Decisions needed before staging resumes
1. **The Autoloop budget-loop fix** (above): approve it as a PR #5 correction or as a separate fix to `main`.
2. **Checks 1–4** need one of:
   - **(a)** a staging service account in the cluster (a Role in `axor-sandbox` with the branch's rules; read access to the
     egress proxy's health) plus a **dedicated test Claude Code login** with a small plan; or
   - **(b)** running them only on production after deploy, with dispatch held.

   Option (a) changes the production cluster (new objects only), so it needs your go-ahead.
3. Then: resume checks 6 (with a staging limit set above the copy's usage, or the copy's usage cleared), 8 (dispatcher), 9
   and 10, and clean up.

---

# Run 2 (2026-11-11, 14:50–15:10 UTC): after the budget correction and the Owner's option A

**Code:** PR #5 with the budget-safety correction and the probe fix found in this run (see below).
**Environment:** same isolation as run 1; restored backup `20261111T065017Z`.
- **Fresh synthetic test owner** `stg-owner` (user 8, no history) with its own team `comp:24` and its own fixtures. No
  historical usage was erased.
- **Option A objects** in `axor-sandbox`, labelled `axor.dev/staging=g5-2`: ServiceAccount `axor-staging-probe` and Role
  `axor-staging-probe` (only `get` on `resourcequotas/sandbox`), with its RoleBinding. Used through a 2-hour token.
- **Permissions verified with `kubectl auth can-i`:** get the sandbox quota: yes. Get another quota, list or create pods,
  exec into pods, get secrets in `axor-sandbox` or `axor`, list nodes: all no.

| # | Check | Result | Evidence (scratchpad `stg/evidence-run2/`) |
|---|---|---|---|
| 1 | Internet probe | **Team off: PASS (FAIL, correctly). Team on: UNKNOWN, stopped at the permission boundary** | Real probe code, staging token, egress `/health` (unauthenticated; the probe sent a dummy secret, never the production one). The proxy answered its health check. Confirming gVisor needs **cluster-wide node read**, beyond the authorized Role. The node's real label (admin read) is `ready`. `probes-live-after-fix.txt` |
| 2 | Sandbox service probe | **Not run: needs broader access** | A sandbox run with `postgres` needs **pod creation** in `axor-sandbox`, which isn't authorized |
| 3 | Real sign-in probe | **Signed-out path: PASS. Signed-in path: not run** | No temporary test Claude Code login was available. Your personal credentials were not used (by your rule). |
| 4 | Kubernetes quota read | **PASS** | `vm` FAIL "The sandbox quota allows no KVM device (requests.axor.dev/kvm: 0)", read through the API with only `get resourcequotas/sandbox` |
| 5 | Gate on actual mission tasks | **PASS (revalidated)** | SN61 copy: 268 open = SQL 268; 8 open Docker-declared = SQL 8 = 8 Docker risks (+1 sign-in) (`check5.txt`) |
| 6 | Dispatch on the seeded team | **PASS** | **A:** `ram:4` and undeclared tasks ran (fake model) and finished; the Docker task was held by readiness. **B:** global limit 1,000 per day vs the synthetic owner's own 9,600 tokens: a new task got **one persistent hold** (`hold='budget'`, scope global, limit id 1, release `reset`, "Not counted against the agent"), and **6 forced Start requests over 60 s gave 0 runs**. Limit raised → fresh preflight → released → **1 run** (`check6-phaseA.txt`, `check6-phaseB.txt`) |
| 7 | Risk persistence | PASS (run 1) | Unchanged code path |
| 8 | Concurrent retries across replicas | **PASS** | Two replica containers, two processes, the same failed Control Hub task, `_claim` fired at the same instant: **1 claimed / 1 lost in 6 of 6 rounds** (0.1 ms apart in round 1); one claim on the row (`race-*.txt`) |
| 9 | Control Hub in the browser | **PASS** | `stg-owner` and the SN61 copy, at 1440 px dark and 390 px light: card present, held rows with cached times, Re-check updated the time (03:58 → 04:03 local), no console errors, no sideways scroll (`browser.txt`, `browser-*.png`) |
| 10 | Rollback rehearsal | **PASS** | web1 recreated with `READINESS_GATE=0`; the rollback SQL (`… WHERE hold IN ('readiness','budget')`) requeued the held task; the board started it once; 0 tasks held anywhere (`rollback.txt`) |

## Found in this run, and fixed
**A refused permission read as "none".**
- `Kube.items()` answers `[]` when reading is refused (403), by design, and the G5-2 GPU probe trusted it. With the
  least-privilege account it reported "No node offers a GPU".
- The egress status's gVisor check (`sandbox.Egress._gvisor`, older code) reports "not installed" for the same reason.
- **Fixed in `mission_ops`:** probes read nodes through a call that raises on refusal, so they answer **UNKNOWN** ("reading
  nodes was refused"). The internet probe confirms a "gVisor missing" answer before believing it.
- **Test:** `test_a_refused_node_read_is_unknown_never_absent`.
- In production the web account can list nodes, so production was not affected, but a least-privilege deployment would
  have been.

## Usage and infrastructure (run 2)
- **Model usage: 0 real tokens.** The fake model's ledger shows 13,200 *fake* tokens: three task runs × 3,600 + report and
  knowledge × 1,200. No provider was called, and no sign-in prompt was sent.
- **Infrastructure:** one Postgres, two web replicas and one relay for about 20 minutes, plus one short host-network probe
  container (no database, no model credentials) for checks 1 and 4.
- **Cluster:** 3 objects created and deleted; token lifetime 2 hours.

## Cleanup (verified)
0 staging containers, volumes or networks; 0 objects labelled `axor.dev/staging=g5-2`; the token and the copied CA deleted;
nothing listens on 8877. Run 1's evidence is in `stg/evidence-run1/`, run 2's in `stg/evidence-run2/`.

## Still needed from the Owner
- **Check 1 (team on):** node read (a ClusterRole with `list nodes`), or verify it after deploy, where the web account
  already has it.
- **Check 2:** pod creation in `axor-sandbox` for one disposable sandbox run, or verify it after deploy.
- **Check 3 (signed in):** a temporary test Claude Code login with a small plan, provided by the Owner.

---

# Run 3 (2026-11-11, 15:48–16:01 UTC): Blocker A (fail-open verification) and Blocker B (cross-replica limits)

**Environment.**
- **Database:** the same verified backup (`20261111T065017Z`), restored again into `axor-stg-pg`, on the internal network,
  with the same isolation SQL. Every team is paused, and every user's Control Hub is on manual.
- **Test owner and team:**
  - a dedicated test owner, `stg-budget-test` (id 8), whose password can't be used, so nobody can sign in as it;
  - a team of its own, `comp:24` "G5-2 budget test", with two agents on the fake API model;
  - 50,000 seeded tokens of usage today.
  - No production row was changed.
- **App:** two web replicas, `axor-stg-web1` and `-web2`, ticking the board every 3 s (`MINING_PILOT_TICK=3`), with the fake
  model.
  - First on **`2589329`** (PR #5 before this fix), for the contrast.
  - Then on **`c4e63b8`** (the fix).
  - Both are exact `git archive` copies. `READINESS_GATE=1`.
- **Limit changes:** made from a third process inside a web container (`stg/limit.py`). It calls `Core.set_limit`,
  `drop_limit` and `set_cap`, the functions the API runs. It uses a bare Core, so it never marks the servers' runs lost.
- **Unavailable verification:** with the database up, `ac_limits.owner_id` was renamed so every limits read fails, then
  renamed back. Reversible, and on the staging copy only.
- **Total outage:** `docker stop axor-stg-pg` for 30 s.
- **Evidence:** `stg/evidence-run3/run3.log` (timestamped), the replica logs, and the final task table.

## Before the fix (`2589329`): both blockers reproduced on real replicas

| Step | What happened |
|---|---|
| Limit 1e9, warm-up task ran | Both replicas had read the limits |
| **Lowered to 10,000 from another process; task 3347 queued 1 s later** | **Started and ran (4,800 tokens)** with the owner at 60,800 of 10,000. A replica's 30 s cache still said 1e9 (**Blocker B**). |
| After the cache expired, task 3348 queued | Held (global) |
| **Limits made unreadable (database up)** | Logged `agent core preflight: … does not exist` and `agent core over: …`, then **let the work through**: new task 3349 **started and ran**, and **held task 3348 was released and ran** (both at 15:53:23, 4,800 tokens each) under the exceeded limit (**Blocker A**: `_safe()` turned the error into ALLOW) |

## After the fix (`c4e63b8`)

| # | Scenario | Result |
|---|---|---|
| S1 | Limit 1e9, warm-up task 3350 | Ran once |
| S2 | **Lowered to 10,000 from another process; task 3351 queued at once** | **Held within 1 s:** `hold=budget`, REFUSE, global, "76,400 of 10,000 tokens today"; **0 runs** |
| S3 | **Raised to 1e9 from a process on the other replica** | 3351 released and **started exactly once** within one tick |
| S4 | Lowered again → task 3352 held; **limit deleted** (web1 process) → released, **started once**; **recreated** as "Recreated" 10,000 (web2 process) → task 3353 held with label "Recreated" | PASS at each step, each within one tick |
| S5 | 60 s (about 20 ticks on each replica) under the refusing limit | **0 starts**; one hold; `hold_info` byte-identical (same `held_at`); team runs 9 → 9 |
| S6 | **Limits unreadable** (database up); task 3354 queued | **Held as UNKNOWN:** `decision=UNKNOWN`, scope `verification`, error `OperationalError: no such column … owner_id`, `held_at 15:57:05`; note "Held: the token budget couldn't be verified (11-11 15:57: …). Not counted against the agent; it starts after a successful check". Held 3353 kept its REFUSE hold. **0 runs.** |
| S7 | **Both replicas restarted while unreadable** | Both healthy in 30 s. 3354's `hold_info` byte-identical across the restart. web1 re-checked 36 times in 60 s, all UNKNOWN, so it stayed held. **0 runs.** |
| S8 | **Recovery:** column restored (the 10,000 limit, still exceeded, readable again) | 3354 changed **UNKNOWN → REFUSE** (global "Recreated"), **not released**. Then raised to 1e9: 3353 and 3354 released after a fresh ALLOW, **1 run each** |
| S9 | **Postgres stopped 30 s**, then started | **0 task runs started during the outage.** `db_pg` logged "connection lost: reconnecting" and recovered **without a web restart**. A task queued after recovery (3355) ran once. |
| S10 | Cost of authoritative reads: owner 4 (7,130 ledger rows), 3 limits, 300 preflights on Postgres | Preflight median **1.03 ms before → 1.56 ms after** (p95 1.06 → 1.69). The limits read itself: 0.28 ms (it was a cache hit before). |

**Every task ran at most once.** On `comp:24`, each of tasks 3346–3355 has exactly 1 task run, including those started while
both replicas ticked the board at the same time.

**Findings.**
- **`/api/health` answered 200 during the database outage.** It checks the chain endpoint, not the database. This was not
  changed here (out of scope), but a load balancer would keep routing to a replica that can't reach Postgres.
- **The board's start isn't claimed in the database.** `Work._kick` marks a task `working` with no `AND status='queued'`
  condition, under a per-process lock. On one database, two replicas could both start the same queued task. Production runs
  one web replica (`kubectl get deploy -n axor`: web 1), and it was not observed here: every task had 1 run. This is the
  same kind of fix `_claim` got for the Control Hub. It's recorded as a risk for the multi-replica stack, and not changed
  under "surgical".

**Not exercised in this run (unit-tested instead):**
- the gateway refusing mid-run (fake-model runs finish in milliseconds);
- the Control Hub dispatcher (Control Hub on manual everywhere by the isolation SQL).

**Scope of run 3.** It repeated the budget scenario (check 6) with the new failure modes. Checks 5, 7, 8, 9 and 10 were
**not re-run on `c4e63b8`**:
- **5 (gate on mission tasks) and 7 (risk persistence):** code paths unchanged by this fix.
- **8 (Control Hub retry race):** `_claim` is unchanged. The new budget check runs before it and doesn't touch the row on a
  hold.
- **9 (browser):** no UI change.
- **10 (rollback):** the rollback SQL (`… WHERE hold IN ('readiness','budget')`) also requeues verification holds. The next
  board pass checks them again and holds any that still aren't ALLOW. That is unit-tested, not re-run here.

Commit `81f9ab5` (reviews gated, marker cleared on `end(ref)`) came after run 3, and is unit-tested only.

**Cleanup (verified).** 0 staging containers, volumes or networks. Model usage: 0 real tokens (fake model); 4,800 fake tokens
per task run.

**Still not done (unchanged from run 2):**
- check 1 positive (internet/gVisor);
- check 2 (a disposable sandbox service run);
- check 3 signed in (a dedicated test login).

---

# Run 4 (2026-11-11, 17:11–17:17 UTC): final-code checks 5, 7, 8, 9, 10 on PR #5 `1057cc1`

**Code:** an exact `git archive` of PR #5 at **`1057cc1`** (`backend/` and `frontend/`), on the `axor/web:1aff3fd-20261111071938`
image's dependencies, with the fake model. Run 3's evidence (on `c4e63b8`) is **not** reused for these checks.

**Environment:**
- the verified backup `20261111T065017Z`, restored fresh, on the internal network, with the same isolation SQL;
- two replicas (`axor-stg-web1`, `-web2`) and a localhost-only relay to web1. No outside name resolution (`pypi.org` fails).

**Logins (staging only):**
- **Synthetic admin `stg-owner`** (user 8, with team `comp:24`, 8 agents on the fake API model).
- **The restored copy of user 4**, with a password set only in this copy. Check 5 needs the SN61 team's owner. No production
  credential was used or changed.
- Every other account in the copy is disabled.

**Evidence:** `stg/evidence-run4/`.

| # | Check | Result | Evidence |
|---|---|---|---|
| 5 | Gate on actual mission tasks | **PASS** | Re-check through the API on the SN61 copy (`comp:23`): Overview 268 open = SQL 268; 8 open Docker-declared = SQL 8 = 8 Docker risks; plus 1 sign-in risk (no login in staging, so all 268 held, critical), as in run 2 (`check5.txt`, `ops-check5.json`) |
| 7 | Risk persistence across restart | **PASS** | web1 restarted (17:11:06 → 17:12:04): `io_risks` identical (9 rows, same ids, `seen`, status). The next Re-check set `seen` 1 → 2 on all 9; no new rows (`check7.txt`) |
| 8 | Dispatcher concurrency across replicas | **PASS** | One failed Control Hub task; `_claim` fired from both containers' own processes at the same instant: **1 claimed / 1 lost in 6 of 6 rounds**; each replica won at least once (`check8.txt`) |
| 9 | Control Hub in the browser | **PASS** | Playwright through the relay: `stg-owner` and the user-4 copy, at 1440 px dark and 390 px light. The Mission readiness card is present, with held rows, check times ("checked 06:13 PM"), Re-check buttons and the risk register. **0 console errors, 0 sideways scroll** (`browser.txt`, `browser-*.png`) |
| 10 | Rollback rehearsal | **PASS** | See below (`check10.txt`) |

**Check 10 sequence:**
- Before:
  - a Docker-declared task (3342) held by readiness;
  - a task (3343) held as **UNKNOWN**, queued while `ac_limits` was unreadable.
- Rollback: web1 recreated with `READINESS_GATE=0` (web2 stopped), then the rollback SQL requeued both.
- With the limits still unreadable, **the next pass held both as UNKNOWN**: the gate was off, but budget safety still applies.
  0 runs.
- Limits readable again: both started, **1 run each**; 0 tasks held anywhere.

**Not re-run:**
- check 6, which run 3 covered on `c4e63b8`. The budget code changed after that only in `81f9ab5` (reviews, marker) and
  `f5fcba5` (consumers), and both are unit-tested.
- checks 1–3 (below).

# Run 5 (2026-11-11, 17:17–17:23 UTC): replica safety on `g5/replica-safety` `8a227cd`

**Code and setup:**
- `1057cc1` (for the contrast), then **`8a227cd`**, both exact archives, on the same database.
- The servers' own board ticks were off (`MINING_PILOT_TICK=100000`). Each round, a script ran the **real `Work._kick`** once in
  each web container's own process, at the same instant (`board_race.py`): own lock, own database connection, the real budget
  decision.
- Each round queued 8 tasks, one per agent.
- **Evidence:** `stg/evidence-run5/`.

| Scenario | `1057cc1` (before the claim) | `8a227cd` (the claim) |
|---|---|---|
| Board start race, both replicas at once | **4 of 5 rounds: all 8 tasks started twice** (16 runs per round; each replica started all 8) | **10 of 10 rounds: 8 tasks, 8 runs, 0 duplicates.** The replicas interleaved (4+4, 0+8, 6+2, 2+6 …). |
| Review race | not run | **5 of 5 rounds: one review run.** Gaps in the run ids show the loser's insert reached the index and was refused. |
| Interrupted claim (working, no run) | — | Claimed just now: left alone. Claimed 200 s ago: back in the queue on the first pass, **started exactly once** on the next. |
| Postgres stopped 30 s | — | `/api/live` 200 throughout; `/api/ready` **503** (`InterfaceError`) during, **200** within 5 s after; **0 restarts** (`StartedAt` unchanged) |
| Postgres hung (`docker pause`) | — | `/api/ready` **503 "no answer within 3 s"** in 3.0 s, `/api/live` 200 in 0.01 s; ready again after unpause; 0 restarts |
| Start-up on the restored copy | — | The unique index `mw_runs_one_review` was created on the production copy at start; no tracebacks other than the unreachable chain endpoint |

**Not shown here:** the kubelet's handling of the new probes (Docker staging has no kubelet). The manifest change is reviewed,
not exercised.

**Cleanup (runs 4 and 5, verified):** 0 staging containers, volumes or networks; nothing listens on 8877. Fake model only:
0 real tokens.

## Checks still UNKNOWN (not PASS)
| # | Check | Status | What it needs |
|---|---|---|---|
| 1 | Internet/gVisor with the team's internet on | **UNKNOWN** | Independent verification (node read, or after deploy where the web account has it). No broader permission requested. |
| 2 | Sandbox service probe | **UNKNOWN** | An authorized disposable sandbox service test (pod creation in `axor-sandbox`) |
| 3 | Signed-in authentication | **UNKNOWN** | A dedicated temporary test account. The Owner's personal credentials are not used. |
