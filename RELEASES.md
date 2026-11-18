# AXoR release record

There is one record of which code runs where. Code names in branches, folders and image tags are not a record: use this file.
`main` on GitHub equals what production runs. Development work is pushed under `dev/`, and nothing is merged to `main` until
it is deployed.

## Production (k3s, namespace `axor`)

| Field | Value |
|---|---|
| Commit | `083696d28088de2ff4020afbfb144d4b6ec6333c` = `main` = tag `g5-wave6c-prod-20261113` |
| Content | G5 integration wave 6c: G5-1, G5-2, G5-3, base G5-4 runner, G5-5 L5.4b part A and L5.5, D-004 D4.1–D4.4 |
| Image | `axor/web:083696d-20261113163134`, imageID `sha256:847950e7db894f211cb9f1e81e72a7f4bec05fcd604549d4128a2abb22d52761` |
| Deployed | 2026-11-13 15:38 UTC by the Owner (`redeploy.sh` from `/home/thomas/axor-release-g5c`; deploy log "+0 uncommitted") |
| Previous | `e4a0dcb` (branch `release/g5-2-rc1`), image tag `e4a0dcb-20261111212932` |
| Notes | Dispatch paused; VM runner off. The auto-update timer is not installed, so a push to `main` does not deploy. |

## Isolated staging (`axor-e2e-*` on this host): reported, changes often

Read 2026-11-14 15:50 UTC with `docker inspect` and a read-only database read. The harness session owns this instance.

| Field | Value |
|---|---|
| Web image now | `axor-prep/web:g5-d1-09f07ed` (`sha256:c150e32ac73baedd528cebe1ab2ba5411d1e423601a86810c4fea0237ba07b91`), from `dev/sc-w1-preflight` `09f07ed` = `b85d23b` + the D1 budget-loop fix |
| Before (11-14 03:39 to the swap) | `axor-prep/web:g5-w10j-b85d23b` (`sha256:4b677f0416ce9d67d27348b91d597b9f5a10422eae8f4678c980f9673b16848c`), branch `dev/integration-g5-wave10j` |

## Development heads (pushed, not released)

| Branch | Commit | What |
|---|---|---|
| `dev/integration-g5-wave6c` | `083696d` | Same as production |
| `dev/integration-g5-wave10j` | `b85d23b` | Wave 10j: the first genuine SN61 run's image |
| `dev/sc-w1-preflight` | `09f07ed` | D1: budget preflight and backoff |
| `dev/sc-w3-egress-health` | `f69832c` | Role-aware egress health check |
| `dev/sc-w6-learning` | `01cb8c6` | Verified-only lessons for planners |
| `dev/sc-integration-1` | `7016589` | `b85d23b` + W1 + W3 + W6; SQLite and PostgreSQL suites pass (2,048 tests) |
| `dev/g5-4-d036` | `9f68fd0` | D-036 (Proposed; switch `AC_PROVISIONAL` **off** by default): a provisional charge for one timed-out Claude Code call, plus D-025 estimate-path fixes. Two independent review passes, no open HIGH or MEDIUM. SQLite 2,081 OK. |
| `dev/g5-5-t4` | `933e092` | G5-5 blocker T-4 learning steps, measure and record only. Three independent review passes, no open HIGH or MEDIUM. Gate verdict byte-identical to `7016589`. SQLite 2,100 OK. |
| `dev/sc-integration-2` | `f2db4f6` | Superseded by integration-3: the earlier heads, before the second and third review fixes. |
| `dev/sc-integration-3` | `8d1188a` | `7016589` + D-036 `9f68fd0` + T-4 `933e092`. **SQLite and Postgres 2,133 OK each** (Postgres peak 158 of 400 connections). Superseded as the candidate by `dev/g5-closure`. |
| `dev/g5-closure` | `9552fd5` | `8d1188a` + the 2026-11-15 closure round.<br>**D-036 correction finality:** a person's figure is a floor, never a cap; the switch is still **off**. Reviewed by three independent passes, an advisor check and a targeted review of the team-count changes. Every under-count found is fixed. The model-based fuzz test finds 0 under-counts.<br>**Team 24 h count:** it keeps D-036 replacements and corrections.<br>**Rate-limit retry:** it takes its own reservation (a defect from before D-036, found by fault injection). This changes the default path, so a switched-off branch is not identical to `8d1188a`. A1 alone is identical on the probed scenarios.<br>**Also:** mission-1 lesson regression tests, and T-5 acceptance tests (the cluster cases skip).<br>**Tests:** SQLite and Postgres 2,198 OK each (Postgres peak 171). Fault injection 123/123 on each engine. Multi-process concurrency passes on both.<br>**The current development candidate.** Not deployed. Report: `docs/G5_4_5_OPERATIONAL_CLOSURE_REPORT.md` (local). |
| `wip/developer-page-and-scene` | `9b34cd2` | Developer page (D-016) and Control Hub scene (D-028): 36 files. **Not in production and not reviewed.** It is based on the old `main` (`5862bed`), so it needs a rebase onto `main` before any merge. The commit's title ("proven benchmarks tab") doesn't describe its content. |

## Decided on the Owner's behalf (2026-11-14, "you decide")

These are the cautious options, and each can be reversed.

| Question | Decision | Why |
|---|---|---|
| The unpushed local commit `9b34cd2` | Pushed as `wip/developer-page-and-scene`. Not merged into `main`. | Its 36 files exist nowhere else, so dropping it would lose the work. Merging it would make `main` differ from production. |
| The local `main` in `/home/thomas/subnet-scout` (1 ahead of and 155 behind GitHub) | Left as it is. | Several sessions work in that folder. Resetting it there could discard their uncommitted work. |
| Old folders, local branches and images | Nothing deleted and no further branches pushed. | Live sessions use some of them, and the evidence files cite image digests. Delete an item only after its commit is on GitHub and no session or evidence file refers to it. |

## How to update

- **A production deploy:**
  1. Fast-forward `main` to the deployed commit.
  2. Add an annotated tag `<name>-prod-<yyyymmdd>` with the image ID in its message.
  3. Update the Production table.
- **A staging change:** update the staging table with the time it was read.
- **New development work:** push it under `dev/`.
