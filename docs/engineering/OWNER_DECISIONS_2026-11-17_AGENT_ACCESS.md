# Owner decisions 2026-11-17: SN61 team agent access and planning fixes

Recorded by Claude Code from the Owner's chat on 2026-11-17 (~08:30 UTC).

## Owner's words (verbatim)

> I approve free files, grant a search MCP server, raise the call and time limits, provider Docker. code fixes

Follow-up answers, the same session:

| Question | Owner's answer |
|---|---|
| How should the changes reach production? | **Two tracks.** A: a small hotfix on production's source 72e1dd0 (limits and planning fixes), deployed once tested. B: Docker through main 1b663a0, staging-tested with real VMs first, deployed only if it passes. Fixes are ported to main too. |
| How should workspace files be freed? | **Raise the caps:** 300 → 1000 files and 3 MB → 10 MB per team workspace. Nothing is deleted. |
| The 06:14 UTC deploy attempt of main 1b663a0 | It was the Owner's. |

## Context (read-only findings, production team 23 "Competition 1", SN61)

- The workspace held 300 of 300 files (2.07 of 3 MB). The agents could not write detector files.
- 12 tool calls per task run: 18 calls were refused across 11 of 88 runs between 11-15 18:49Z and 11-17 07:36Z.
- A Claude Code turn at the team's low effort gets 150 s (CLAUDE_CLI_TIMEOUT 300 × 0.5): 7 runs timed out.
- Search: Exa search and DeepWiki were used by team 23 through the owner's `missions:4` grant until 11-11 07:21Z, and not after.
- Docker: the production sandbox offers only PostgreSQL/ClickHouse services. `docker_job` (runner.py, D-8, V4.2) exists only on main.
- Planning:
  - the Director's plan prompt lists 60 board rows (1 of 23 blocked tasks);
  - failures with no failure class (1,923 expired-login runs) were summarised to the planner as "the task itself";
  - milestones were last updated 11-11 while the notebook records milestone 1 as closed.

## Scope of this approval, as read

Covered:
- Track A code: higher limits (files, bytes, tool calls, CLI turn time), the three planning fixes, and making sure the team is offered its granted search tools.
- Track B: staging test of the Docker runner on main, and deployment if it passes.

Not covered (each needs its own word):
- unpausing team 23 or switching its autopilot on;
- the 20 saved web-read slots per team;
- production database writes by Claude Code;
- deleting any team file;
- putting Claude Code's own SN61 miner work into the team's work (Issue #35 rule).

Deploys are run by the Owner (`./k8s/redeploy.sh`); Claude Code runs only `--check` and `--verify`.

## Track B decisions (Owner's chat, 2026-11-17, later the same morning)

The Owner said "do Track B", then answered:

| Question | Owner's answer |
|---|---|
| Package-index hosts that image builds in the runner VM may reach (D1, `runner.package_hosts`) | **PyPI only:** `pypi.org`, `files.pythonhosted.org`. |
| Team 23's unmetered run 9597 under main's budget gate | **Claude Code records 25,000 tokens** through AXoR's own estimate function after the deploy, logged as the Owner's. |
| Staging main against production data | **Yes, an isolated copy.** A read-only pg_dump goes into a network-less Postgres container in Claude Code's scratch folder, and is deleted when staging ends. |

Track B's order:
1. Local VM-runner staging with main's code.
2. Staging main on the production-data copy.
3. A deploy, only if both pass, run by the Owner.

The cluster steps (k8s/runner/58-runner.yaml, the runner image, the KVM device plugin restart) are part of that deploy and are listed with it.

## Track B pass criteria (written before staging)

Track B is deployed only when every row passes. Each row's evidence is recorded in the report.

**Runner (local staging, real KVM VMs, k8s/runner/stage-local.sh, base disk sha256 f3444e21…, job.py bb7ac11d…):**

| # | Criterion |
|---|---|
| R1 | A synthetic `build` job whose Dockerfile `pip install`s a pinned package from PyPI builds, and reports the image digest with exit 0 (`PACKAGE_HOSTS=pypi.org,files.pythonhosted.org`). |
| R2 | A synthetic `run`/`bench` job starts the built container, reaches its port inside the VM, and returns its output and score file through the real result path. |
| R3 | A build that fetches from a host off the list (not PyPI) is refused by the egress proxy, and the job reports the failure. |
| R4 | A job that exceeds its time limit is stopped. No VM, container or network is left behind on the host. |

No team code, miner code or detector is used in any job.

**main on an isolated copy of production's data** (main's web image; Postgres from production's image, on an internal Docker network; explicit environment only):

| # | Criterion |
|---|---|
| M0 | From inside the staging web container, production Postgres (10.43.110.126:5432), the Kubernetes API and the internet are unreachable. The check runs before the first boot. |
| M1 | main boots on the copy: its migrations finish without errors, and `/api/live` and `/api/ready` answer 200. |
| M2 | As a staging-only admin, team 23's workspace, board, files and roadmap pages answer, and the plan board shows the blocked questions. |
| M3 | The budget gate is counted over the whole copy: every team or mission main would hold, and why. Run 9597 is among them. |
| M4 | Rehearsed on the copy: the 25,000-token estimate for run 9597 clears team 23's hold, and `runner.package_hosts` = [pypi.org, files.pythonhosted.org] is accepted. Each step is recorded with the exact production call. |
| M5 | Rollback: production's image (axor/web:d429a13-20261115222828) boots on the copy main migrated, and answers `/api/health` and team 23's workspace. |
| M6 | `./k8s/redeploy.sh --check` passes from this tree: parse, build, offline boot and unit tests in the image. |

The copy is deleted when staging ends.

## Token waste (2026-11-17, afternoon)

The Owner asked why team 23's token use was so high. Claude Code measured it read-only in production on 11-17 at about 15:00 UTC:

- Task runs used 94% of the day's 9.9M tokens.
- 22 of 142 task runs failed, using about 1.3M tokens. 9 of them hit the per-turn time limit.
- 87 tasks took the 142 runs, about 3.5M tokens of repeats. A rerun started over: it re-read the same files and re-ran the same checks.

The Owner approved two fixes:

| # | The Owner's words | What it means |
|---|---|---|
| 1 | "I approve 1" (stop losing timed-out runs) | A team run's turn may take **600 s** (it was 300 s). The work prompt tells agents to build long files with a script, or split them, rather than write them out in one call. **Not done: retrying a cut-off turn inside the run.** The cut-off turn marks the run unmetered (D-021/D-036), so main's gate refuses the run's next call until a person records an estimate. A retry needs D-036's provisional charge (`ac_provisional`, proposed, not adopted), which is the Owner's decision. |
| 2 | "I approve 2" (rerun notes) | A task's rerun is told the steps of the task's last run: the tool calls with clipped results, what the agent said, and, for a run that failed or was cancelled, why it stopped. At most 8,000 characters, the latest steps kept. This covers runs that stopped before filing (16 reruns, 1.5M tokens on 11-17). It also covers runs that filed and were then sent back or had a question answered (39 reruns, 2.2M tokens), where it is added to the filed result and the answer. A run that took no step (a budget refusal) is skipped for the one before. |
| 3 | "you do from the Director chat now" | **Prepared, not posted.** Claude Code's direct write was refused by its permission check. The text is in /var/lib/axor/deploys/trackb-20261117/director-reply-231.txt, for the Owner to paste as the answer to the open report. It asks the Director to: assign #3611 (the BEX re-capture with docker_job) to a teammate; park the release housekeeping; accept at most 3 follow-ups a report; give no third run to a task that ran twice. |

Code: `mining_work.TEAM_TURN_S`, `ATTEMPT_CHARS`, `Work._attempt` (called in `Work._work`), and WORK_SYSTEM's turn rule. Tests: `tests/unit/test_token_waste.py`.

## Codex token count (2026-11-17, evening)

After the Owner's own Claude Code login was removed (about 14:55Z), the router sent team 23's runs to Codex. The Owner said **"keep Codex in mind"**, and running on Codex is accepted.

Measured on 11-17's finished task runs, a Codex run was counted at about 144k tokens, against 66k on Claude Code. The main cause is the count, not the work:
- For Codex, AXoR added up `input_tokens`, which includes `cached_input_tokens`. Each turn re-reads the whole conversation from the cache.
- Claude Code's cache reads have been left out since 11-11 (`llm._cli_tokens`).

Codex also took about 25% more steps a run (8.9 against 7.0).

| The Owner's words | What it means |
|---|---|
| "you do" (to "count Codex the way Claude Code is counted") | A Codex turn counts input plus output **without the cached input** (`codex_cli.billed`), in text mode and in MCP mode (`codex_bridge.usage_tokens`). `CODEX_COUNT_CACHED=1` restores the full count. Budgets, limits and estimates read the new count from the deploy on. Runs recorded before it keep their counts. |

## Codex writes (2026-11-17, evening)

On Codex, team 23's agents never called `file_write`. They filed "the workspace is read-only" blockers, and the Director asked the Owner to "Restore workspace tool access". The cause was the run's own setup:
- Codex runs with its own sandbox set to read-only (`-s read-only`, unchanged).
- AXoR's guidance said "you have no shell, files or web of your own".
- The model read both as "nothing may be written".

The Owner chose **"2"**: one line in `codex_bridge.GUIDE` says the read-only sandbox is only Codex's own. It says AXoR's writing tools (file_write) do write, and that Codex must not report it can't write while it has one. Not done: the cascade where one Codex session that ends without reporting usage stops the team through the gate. That would need D-036 or the Claude Code login back.

## Team step limit (2026-11-17, evening)

Three times between 16:36Z and 17:34Z, a Codex task run hit `agents.MAX_STEPS` (10 model turns), and the chain reaction followed:
- Codex makes one tool call a turn, so it reaches the step limit long before the 24 tool calls.
- A Codex session stopped mid-run never reports its usage (usage comes only at `turn.completed`), so the run is unmetered.
- The fail-closed team gate (D-025) then refused every other run's next call, including other Codex sessions' closing turns, which then ended unmetered too: 4 runs each time, and the team idle until a person recorded estimates.

The trigger runs were 10038, 10073 and 10080. Each had exactly 10 model turns and 10 tool calls.

The Owner chose **"fix steps"**:
- A team task run now gets `TEAM_STEPS = TOOL_CALLS + 2` = 26 model turns: the 24 calls, `submit_work`, and one spare.
- `agents.run_loop` takes `max_steps`. Chats, missions and every other caller keep `MAX_STEPS` = 10.
- The tool-call cap (24) still bounds the work. At the cap, the agent is told to call submit_work, so a run ends by filing instead of being cut off mid-session.
