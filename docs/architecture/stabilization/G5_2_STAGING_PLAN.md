# G5-2 Staging Verification Plan

**Status:** Proposed. Nothing here has run yet. **No production deployment until every check below passes and the Owner
approves.**

## Where to stage

A **staging namespace on the same cluster** (`axor-staging`), with:
- the PR #5 image (built by `k8s/redeploy.sh --check`, never pushed live);
- a **restored copy of the latest verified backup** (`k8s/backup.sh --verify` restores into a throwaway database);
- the production `axor-sandbox` and `axor-egress` namespaces, read through the staging web pod's own service account. That
  gives real probes without touching live data.

The staging web pod runs with **`READINESS_GATE=1`** and **`CONTROL_DISPATCH` off**, so it probes and reports but **starts no
agent work**. The single exception is check 6, a scripted run on one seeded test team.

## Checks

| # | Check | How | Pass when |
|---|---|---|---|
| 1 | Internet probe | Control Hub → Overview → Re-check on a team with internet on and on one with it off | ON: PASS, evidence "egress proxy answered its health check"; OFF: FAIL "internet is off". The egress record shows the health call. |
| 2 | Sandbox service probe | Run one sandbox run with `services: ["postgres"]` on the staging test team, then Re-check | Before the run: UNKNOWN "no run has used postgres". After: PASS naming the run's id. ClickHouse the same. |
| 3 | Real sign-in probe | Re-check on a team on the Claude Code plan login; then on a team whose login is signed out (a test login with a revoked token) | Signed in: PASS "answered a real prompt" (one tiny Haiku prompt in the plan's usage). Signed out: FAIL with "isn't signed in", and every task of that team held. **No prompt on a plain page load** (staging log shows none). |
| 4 | Kubernetes quota read | `kubectl auth can-i get resourcequotas -n axor-sandbox --as=system:serviceaccount:<staging>:web`, then Re-check a task that declares `vm` | `yes`; the probe says FAIL "allows no KVM device (requests.axor.dev/kvm: 0)", not UNKNOWN |
| 5 | Gate on actual mission tasks | On the restored copy, declare `docker` on SN61's 16 confirmed Docker tasks (as in the A8 replay) | The open ones (11 in the 06:50Z copy, recount on the restore) are held with blocker and remedy; all others untouched; the Overview's counts equal a direct SQL count |
| 6 | Dispatch path, one seeded team | Seeded test team: a queued task declaring `ram:4`, one declaring `docker`, one undeclared; dispatch on for that team only | `ram:4` and the undeclared one start; `docker` is held; a forced timeout retries once (one retry key, one run); a forced sign-in failure blocks, not counted |
| 7 | Risk register persistence | Restart the staging web pod between checks 5 and 6 | Risks keep their ids, `seen` and evidence; a repeated probe updates (`seen` + 1), never duplicates; resolved ones reopen if they fail again |
| 8 | Concurrent retries | Two staging web replicas (or two dispatcher threads) against one failed task due for retry | `ctl_tasks.attempts` rises by exactly 1, one run starts, and the other pass logs no start |
| 9 | Control Hub behavior | Browser at 1440 px dark and 390 px light on staging | The card shows cached evidence with times; Re-check works and is limited to once a minute; Accept works for non-critical risks only; Verify works for credentials only; Approve works for admins only, once; no console errors, no sideways scroll |
| 10 | Rollback rehearsal | Set `READINESS_GATE=0`, then requeue held tasks with the PR's SQL | No task is left held; the board starts as before |

## Evidence to hand back
For each check: the command or click, its output or screenshot, the time, and the staging image tag. Failures are reported
as found, with no retries to make them pass.

## After the Owner's approval
Production deploy with `k8s/redeploy.sh` by the Owner, then checks 1, 3, 4, 5 (count only) and 9 again on production.
