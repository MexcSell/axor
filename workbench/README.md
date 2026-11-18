# AXoR Workbench

Lets the Competition teams **Workflow** (Mining HQ) work on real folders of this host, with Claude Code, the same way you use it in VS Code. It runs on the host, not in k3s: it needs the folders and root's Claude Code login.

## Install

```bash
sudo ./workbench/install.sh /home/thomas/bit   # one or more git folders
./k8s/redeploy.sh                              # the web pod picks up WORKBENCH_URL and the token
```

`install.sh` copies `workbench.py` to `/opt/axor-workbench` and starts `axor-workbench.service`. On the first run it writes `/etc/axor-workbench.json` (mode 600) with a fresh token, and saves the token in the k8s secret `axor/workbench`. Later runs keep the config and update the code.

## What it may do

- **Network:** it listens on `10.42.0.1:8350`, the pod network's gateway, never the public IP. It accepts calls from `10.42.0.0/16` that carry the token.
- **Folders:** only the folders in the config. AXoR sends a folder id, never a path, and every path must resolve inside the folder.
- **Agents never touch your checkout.** Each task gets a git worktree on a `bench/<task>` branch under `/var/lib/axor-workbench/worktrees`, made from the last commit of the branch you picked. Your uncommitted work isn't in it.
- **Merging** goes into your checkout only when the right branch is checked out, nothing is staged, and none of your uncommitted files overlap the branch. Otherwise it refuses and gives you the `git merge` command to run yourself. Conflicts are aborted.
- **Merges are pinned to the commit you approved.** AXoR sends that commit as `expect`. If the branch has moved on since then, the merge refuses (`"moved": true`), and what lands is exactly the commit that was reviewed and checked.
- **Agents have no Bash, no web access and no subagents.**
  - The Director (plan) and the reviewer can only Read, Glob and Grep.
  - Engineers can also Edit and Write inside their worktree.
  - Reads outside the working folder are refused.
- **`deny`** lists paths agents may not read at all, which also hides them from Glob and Grep. By default that's `ridges-intel` (other miners' published agents: never copy them) and `workspace/apikeys.md`.
- **Checks** are commands from the config, such as unit tests or an eval. The workbench runs them in the task's worktree when you press the button. They run as root, on code an agent wrote, so read the diff first.
- **Cost and limits:** runs use root's Claude Code login, the same plan quota as your own sessions. At most `parallel` runs go at once (default 2). Each run is capped by `--max-budget-usd`, at most `max_budget_usd`.

## Config (`/etc/axor-workbench.json`)

```json
{"listen": "10.42.0.1", "port": 8350, "token": "…", "parallel": 2, "max_budget_usd": 5.0, "allow_from": ["10.42.0.0/16"],
 "repos": {"bit": {"path": "/home/thomas/bit", "name": "bit", "skip": ["btcli-venv"], "deny": ["ridges-intel"],
   "checks": {"handin30": {"label": "agent30 hand-in tests", "argv": ["python3", "-m", "unittest", "discover", "-s", "agent30"], "cwd": "{worktree}", "timeout": 900}}}}}
```

In `argv` and `cwd`, `{worktree}` becomes the task's folder, `{repo}` your checkout and `{run}` the run id. After editing the config, run `systemctl restart axor-workbench`.

### Scored checks: evals for the Lab

A check with `"results"` names a JSON-lines file that it writes. When the check ends, the workbench reads that file (at most 5,000 lines and 4 MB) and returns it with the run. AXoR's Lab (`backend/app/mining_lab.py`) then records the score against the commit: tasks solved, pass rate, cost and time. The file must be inside the folder or the task's worktree, and newer than the run, so put `{run}` in its path. Each line is one run of one task, in the format of `eval/eval.py`'s `runs.jsonl`: `task`, `passed`, and optionally `cost_usd`, `agent_sec` and `end`. A task counts as solved only when all of its runs passed, which is how the validators count.

For `/home/thomas/bit`, this runs the task's branch of the comp-28 agent through OpenRouter on one eval set:

```json
"eval-sql": {"label": "Eval: hard SQL set", "note": "OpenRouter, about 1-2 h, a few dollars",
  "argv": ["python3", "{repo}/eval/eval.py", "--label", "bench-{run}", "--target", "openrouter", "--agent", "{worktree}/agent/agent.py",
           "--task-list", "{repo}/eval/sets/hard-screen-sql-v1.txt", "--repeats", "1"],
  "cwd": "{repo}/eval", "timeout": 10800, "results": "{repo}/eval/results/bench-{run}/runs.jsonl"}
```

`--agent` only works with `--target openrouter`: eval.py builds local targets from `workspace-local/`. Each eval spends OpenRouter credit, and a 20-task set takes about one to two hours. The Lab's "Measure the base" button runs the same check on the branch you merge into, which gives a commit to compare against. `/info` lists each check with `"scored": true|false`.

## Loadouts: skills, MCP servers, effort

AXoR's Loadouts tab (`backend/app/mining_loadout.py`) can give each run:

- **Skills.** AXoR sends a name, a description and the text of each one. The workbench writes them as `skills/<name>/SKILL.md` into a plugin folder of its own under `state/runs/<run>-plugin`, outside the worktree, and loads it with `--plugin-dir`. The run also gets the `Skill` tool, and the folder is deleted when the run ends. Nothing else ever goes in that folder: no hooks, MCP servers or agents. With the `Skill` tool on, the run log also lists Claude Code's built-in skills (`update-config`, `loop` and the like). That's harmless: the run's tools, its denied paths and its folder stay the same.
- **MCP servers,** by id, from this config only. AXoR never sends a command. Each server gets `--mcp-config` (a file made for the run, mode 600, deleted after) and `--allowedTools mcp__<id>`.
- **An effort level** (`--effort`).

```json
"mcp": {"docs": {"label": "Library docs", "note": "Looks up API docs", "command": "/usr/local/bin/docs-mcp", "args": [], "env": {}, "kinds": ["plan", "engineer"]}}
```

`kinds` limits a server to plan, review or engineer runs. A server runs as root beside the run, so add only ones you trust. `/info` reports `"features": ["skills", "mcp", "effort", "pinned-merge", "results"]` (version 3) and the servers' ids and labels. AXoR refuses to save a loadout that an older workbench (without `features`) would ignore.

## Look at it

`journalctl -u axor-workbench -f` shows the service log. Run logs are in `/var/lib/axor-workbench/runs/*.json`. Branches show up with `git -C /home/thomas/bit branch --list 'bench/*'`.

## AXoR's own code (D-040, self-edit missions)
Missions can change AXoR itself through this service (`backend/app/self_edit.py`). The flow, per change:
1. The engineer works in a worktree of a **dedicated clone**, never the live checkout.
2. The Workbench runs the `unit` check on the result.
3. The change merges into the clone's self-edit branch only after the Owner approves that exact commit in Mission Control.

Nothing pushes or deploys.

### Setting it up (Owner steps)
1. Make the dedicated clone, on its own branch:
   ```
   git clone <repo> /srv/axor-self-edit
   cd /srv/axor-self-edit
   git checkout -b self-edit/main <base commit>
   ```
2. Add it to `/etc/axor-workbench.json` under `repos`, then `systemctl restart axor-workbench`:
   ```json
   "axor": {"path": "/srv/axor-self-edit", "name": "AXoR (self-edit clone)", "deny": [".env", ".env.local"],
            "protect": ["k8s", "Dockerfile", "docker-compose.yml", "runner", "workbench", "tools", "dns", "push", ".github",
                        "backend/app/auth.py", "backend/app/egress_proxy.py", "backend/app/sandbox.py", "backend/app/aicp",
                        "backend/app/agent_env", "backend/app/self_edit.py", "backend/app/updates.py", "backend/app/devops.py",
                        "tests/run-unit.sh"],
            "checks": {"unit": {"label": "AXoR unit suite", "argv": ["bash", "tests/run-unit.sh"], "cwd": "{worktree}", "timeout": 1500}}}
   ```
   - `protect`: Edit/Write are refused there; AXoR also refuses a diff that touches `SELF_EDIT_PROTECT`.
   - The check needs Docker and an `axor/web` image on the host.
3. Set `AXOR_SELF_EDIT=1` in AXoR's environment, and deploy. Optional settings, with their defaults:
   - `SELF_EDIT_REPO=axor`
   - `SELF_EDIT_BRANCH=self-edit/main`
   - `SELF_EDIT_CHECK=unit`
   - `SELF_EDIT_MODEL=opus`
   - `SELF_EDIT_MAX_USD=5`

### Getting a merged change live
A merged change is still only on `self-edit/main` in the clone. Taking it further is the Owner's own step: review it, push it, and deploy it as usual.
