---
title: My subnets
section: guide
order: 4
icon: trophy
summary: A team of agents per subnet competition that watches the field, tracks your miners, plans how to reach the top, saves each step to your repository, and lets you watch and steer every step.
---
[My subnets](#mining) puts a team of agents on a subnet you mine. The team takes snapshots of the competition, tracks your own miners in it, works out how to reach the place you're aiming for, and reports to you. You decide what happens: you approve actions, give the agents instructions, and can follow each step they take.

My subnets is for everyone who can use [agents](#help/agents): administrators, and members when an administrator turns on **Members can use agents**.

## Finding your way

My subnets and Competition teams share one frame. The band on top shows whether the division is **Online** (a campaign is live), **Paused** or can't be reached, and three counts: open competition teams, agents switched on (and how many are working now), and approvals waiting for you. Click a count to open its screen.

The **Workflow** rail on the left lists the work in the order you do it: **1 Choose a competition** (the overview, your competitions, the campaign's strategy), **2 Build the team** (your agents, the team builder), **3 Run** (live operations, the team's tasks, the campaign's control room), **4 Test & improve** (experiments, the team's evals) and **5 Ship & review** (miners, rewards and costs). Everything else sits under **More**, folded until you open it: competition approvals, monitoring, budgets and alerts, campaign activity, competition intelligence, your miners against your goal, the Performance Lab, the code workflow, the team diagram, the analyst workflow, deployment history, files and settings. While folded, More shows the total of its counts, and it opens by itself when you're on one of its screens. Subnet Explorer and Portfolio are in the app's sidebar, and search is the box in the band. On a wide screen the rail replaces the Command center's tab row and the campaign's tabs. Screens that belong to a campaign show the campaign you picked in the row of campaigns. Fold the rail to icons with the button at its top; on a phone it opens from the menu button in the band.

**Find a competition, agent, task…** searches screens, campaigns, competition teams, agents and experiments, plus the tasks and files of the team you have open.

### Live operations

Who is working on what right now across every competition team (with how long and how many tokens so far), the queues (tasks about to start, in review, waiting for you), campaign cycles in progress, and one stream of everything every team did in the last three days. Filter by source, team or text; **Pause the stream** stops the updates (every 4 seconds). Click a line to open its team or task.

### Team builder

A competition team's squads side by side. Drag an agent's card to another squad, or onto another team at the top to move it there; drag a role from **Add an agent** onto a squad to add one (a taken name gets a number: Iris 2). Each card's **Change** menu does the same without dragging, and also copies an agent to another team, makes it squad lead, switches it off or removes it. A moved or copied agent keeps its job, instructions and model; the team lead and squad leads stay where they were. An agent in the middle of a task can be copied but not moved.

### Deployment history

Every deploy you recorded through an approved experiment, and every rollback, newest first: the version, the miner, the team, the experiment and its approval. Filter by team, miner, status or text. An experiment still being monitored after its deploy has **Keep or roll back**, which opens it.

### Budgets & alerts

Today's spend (the last 24 hours) for each competition team against its token budget, which you can change here, and for each campaign's analyst team. Dollars use the token rate from Command center → Settings, plus sandbox runs. Alerts are raised when:

- a team uses the share of its budget you set (80% by default), or all of it;
- everything together passes the **daily cap** in dollars (no cap by default);
- a team's primary metric falls by more than the share you set (10% by default) below the average of its earlier reports, beyond the noise between them (it needs at least four evaluator reports in 14 days).

Alerts also show in the Command center's Monitoring and on the dashboard, are kept in the alert history until they clear, and are pushed to your devices at most once a day each (switch that off in the alert rules).

### Ask AI

**Ask AI** in the band answers questions about what's on screen: the team you have open, the campaign, or the whole division (change it under **About**). It reads a snapshot of the project (goal, team, tasks, notebook, numbers, alerts, recent activity) and answers from it; it can't change anything. Each answer shows the model and the tokens it used, which count in your usage like other agent work; the conversation is kept per project until you clear it.

## Start a campaign

A campaign is one team on one competition of a subnet, with one goal. Open My subnets, choose **New campaign** and pick:

- **Subnet**: up to eight campaigns in all.
- **Competitions**: when the subnet runs several (see *Competitions* below), tick the ones you want a team on. Each one you tick gets its own team.
- **Your goal**: a top 1, 3, 5, 10 or 25 place.
- **Your miner's keys**: hotkeys, or a coldkey to cover every UID under it. These are public SS58 addresses only: anything that looks like a seed phrase or private key is refused. If you track wallets on the [Wallets](#wallet) page, you can pick their keys from chips.
- **Your product** (optional): what your miner is (model, approach, hardware, version), its GitHub repository, and, for administrators, the DevOps pipeline or app it runs as on this server.
- **Schedule**: a snapshot every 10, 15, 30 or 60 minutes, and a team cycle every 1, 3, 6, 12 or 24 hours.

The team starts its first cycle right away. Everything can be changed later in **Settings**.

## Competitions

Some subnets run several competitions (on chain, *incentive mechanisms*). Each one has its own validator weights, so it ranks miners on its own, and it pays out its own share of the miners' rewards. The same UIDs take part in every competition of the subnet.

- Rio reads every competition at the same block. A miner's rewards in a competition are the miners' pool times that competition's share times the miner's incentive there.
- A team works on one competition: its ranks, cutoffs, alerts, analysis, plan and brief are that competition's. The prune line stays subnet-wide, since deregistration doesn't care which competition a miner earns in.
- On such a subnet, a strip above the tabs shows every competition: its share of the rewards, the leader, where your miners stand, and its team. Click one to open its team, or **Put a team on it** to start one with this team's goal, keys, product, instructions and settings.
- The **Competition** tab has a sub-tab per competition: open any of them to see its field (trends, rewards by rank, the leader, movers, the leaderboard), even one without a team of yours. **Compare all** puts them side by side: how the subnet's miner rewards split, each competition's pool, leader, cutoff for your goal, spread and your best rank, and each one's top 5.
- In the [Explorer](#explore), a subnet's details have a **Competitions** card for every subnet: whether it runs one competition or several, and for each one its share, field and top 10 miners, with a button to open your mining team on it or put one on it.
- Give a competition a name in **Settings** (otherwise it's *Competition 1*, *2*, ...; the chain counts mechanisms from 0).
- If the subnet stops running a competition, Rio says so on its team and the team stops analysing it.

Competitions that a subnet runs off chain, inside a single mechanism, can't be told apart from chain data. Give each of those its own competition team instead (below).

## The Workflow: your folder, one step at a time

**Competition teams → Workflow** is where a team works on your real code. It opens first on every team. A small team takes five steps, and each one waits for you:

1. **Goal.** Pick the folder (for example `/home/thomas/bit`), the branch to start from and merge into, and what the team should reach.
2. **Plan.** The Director reads the folder (read only) and proposes tasks, each with the files it touches and an engineer. Edit them, untick the ones you don't want, then approve.
   - The Director also gets the eval record from the Lab: what the base solves, the eval tasks it doesn't solve yet, and what each earlier task did to the score (gained, lost, merged or dropped). **What the Director is told about the eval score** shows the exact text.
   - **Research (Workforce)** is optional. It starts one Workforce mission on the team's goal: how the competition scores agents, which tasks agents fail and why, and what's worth trying. When it's done, its report goes into the next plan unless you untick **Give the report to the Director**. It runs on the Workforce's model credits, not your Claude Code quota. Its agents work from what they know and AXoR's subnet data, not from your folder.
3. **Work.** Press **Start** on a task. Its engineer runs Claude Code in a separate copy of the folder, on its own branch `bench/…`, and you watch every file it reads and edits live. When it finishes, the task waits: **See what changed**, then **Send to the reviewer**. You can switch "Ask me between agents" off under Goal.
4. **Review.** You see the reviewer's verdict (approve or changes, with the issues), how sure the reviewer is, and the evidence: each claim with the file and line it read. Run the folder's **checks** (unit tests, an eval), read the diff, then **Merge**, **Send back** with a note (the engineer carries on in the same session) or **Drop**.
   - The review and each check remember the commit they saw. **Merge** takes one click when the reviewer approved and every check passed on the branch's current commit.
   - Otherwise a dialog says why: no review, the reviewer asked for changes, a check failed or is still running, or either one saw an older commit. Confirm, and only that commit is merged. If the branch moves after you confirm, the merge refuses.
   - Each merge records who merged which commit, when, and anything it was merged over. **Submit** shows it.
5. **Submit.** Submitting to the competition is yours to do. Mark it here when it's done, then plan the next round.

**What happens now**, at the top, lists everything that waits for you, each with its button. **Every step** on the side logs what happened. **Team** lets you add engineers or reviewers, pick their model (sonnet, opus, haiku), give them instructions or switch them off. **Files** shows your folder live and every task's branch, read only.

Safety:
- Agents never edit your checkout. They can't run commands or reach the web, and they can't read `ridges-intel` (other miners' agents).
- A merge refuses while you have staged changes, or uncommitted changes in the same files. It then shows the `git merge` command to run when you're ready.
- Runs use this host's Claude Code login, the same quota as your own sessions. The header shows how much of the 5-hour window is used.
- Only administrators can use the Workflow. It needs the AXoR Workbench on the host: see `workbench/README.md`.

The earlier tools (the autopilot board, the Director's report, Diagram, Roadmap, Prompts and the rest) are under **More**.

### Loadouts: what each agent brings

**Competition teams → Loadouts** sets up each Workflow agent:

- **Model and effort:** sonnet, opus or haiku, at an effort level from low to max.
- **Budget per run.**
- **Memory:** off, the agent's own notes, or its own plus the team's.
- **Skills:** written guidance Claude Code uses when the work fits. You get built-in skills such as *Map the repository*, *Work toward the score*, *Change code and its tests together* and *Review checklist*, and you can write your own.
- **Plugins:** bundles of skills and MCP servers.
- **MCP servers:** only the ones an administrator offers in `/etc/axor-workbench.json`.

New agents start on their role's template, so a new team is set up from its first run.

- **Agents:** a card per agent, with an editor. Every save is a new version.
- **Scores:** every version of every agent with what its runs led to: the eval against the base (tasks that gained, kept or lost eval tasks), the reviewer's verdict, checks passed or failed, work merged, sent back or dropped, and cost. Each outcome counts for the version that did the work; a task's eval also counts for the Director whose plan proposed it. **Use again** brings back an earlier version. The score (0–100) shows once there are 3 outcomes; for engineers the eval weighs half of it, because the eval is what the competition scores. Use it to compare versions of the same agent, not one agent with another.
- **Suggestions** on the cards come from those scores. For example: add *Work toward the score* when evals keep losing tasks, add *Change code and its tests together* when checks keep failing, try opus, or go back to a version that scored better. Nothing changes until you press **Apply**.
- **Improvements:** see below.
- **Library:** your skills and plugins. **Copy to edit** turns a built-in skill into one of yours.
- **Memory:** the Workflow writes notes as the work goes: what an eval gained and lost, what a review asked for, why you sent work back, which check failed, what got merged, which planned tasks you kept. A run gets the newest few, then the notes closest to its task (yours count more), up to about a page. You can add, edit, delete or share any note with the team.

Skills are text: they can't run anything, and agents still have no shell. Claude Code plugins with hooks aren't loaded, because hooks would run as root on the host. An MCP server runs alongside the agent's run on the host, so offer only servers you trust.

### Improvements: a change measured before you apply it

**Loadouts → Improvements** turns an eval that lost tasks into a tested change to the engineer's loadout.

1. **A proposal.** When a task's eval loses tasks against the base it started from, the Improvement Engineer looks for the cause in that engineer's loadout. It reads the instructions, skills and model, the task, the review, your notes, the diff and the lost eval tasks, all read only. It proposes the smallest change: new instructions (shown word by word), skills to add or drop, or another model. If no loadout change would have helped, it says so. It starts on its own unless you untick **Propose on its own**; you can also **Ask about** an engineer, with a note, from here or from the engineer's card.
2. **A trial.** **Test it on the eval** gives the task it was diagnosed on, plus up to four **held-out tasks** it never saw (two by default), to the engineer with the change (nothing is saved). Each task starts from its own starting commit, and the same eval runs on each branch. Held-out tasks are the team's other started tasks, not dropped ones: the engineer's own come first, then anyone's. They're picked when the trial starts, so **Test again** picks again. The current version runs each task too, unless the task's own eval stands for it, which needs that same version of the engineer to have written the work. The card shows the plan before you start: which tasks, which evals are reused, and how many engineer runs and evals that is. They queue on the workbench, two at a time by default. Every eval shows in the Lab as a trial (triangles).
3. **The margin rule.** The candidate measures **better** only when it solves at least the margin (two eval tasks by default) more over all the trial's tasks, and none fewer on the held-out ones. It was tuned on the diagnosed task, so a win there alone is partly fitting. It measures **worse** when it solves fewer in total or on the held-out tasks; otherwise **no better**. A held-out task whose run or eval failed is left out and named in the result. Only a failure on the diagnosed task fails the trial. When the team has no other started task, a win rests on the diagnosed task alone, and the result says so.
4. **Your decision.** **Promote** a candidate that measured better: it becomes the engineer's next loadout version. Or **Reject** it. The trial's branches are deleted once you decide. A proposal that wasn't tested can't be applied: if you want the change anyway, edit the engineer's loadout yourself in Loadouts and say why. That is your own edit, saved as a new version you can go back from.

5. **Or all on its own.** Tick **Test, promote and roll back on its own** and the team needs nobody for steps 2 to 4. A proposal is tested at once, with the default held-out tasks and margin. A candidate that measures better is promoted. Then a **watch** starts: the new version's next six real outcomes (reviews, checks, evals, merges; trials never count) are compared with the version it replaced. It stays when its score is no more than five points lower. Otherwise it goes back to the earlier version, saved as a new version so nothing is lost. When the earlier version had too few outcomes to score, the evals decide: it goes back when they lost more often than they gained. A change anyone makes in the meantime ends the watch. Two guards: a **weekly limit** (what the team's improvements cost in the last seven days, yours included, $10 by default) and **Freeze**. Either one stops new trials and promotions; neither stops a watch, since going back to a version that worked is the safe way. After a rollback, that engineer's next change waits for you for seven days, so a change that keeps failing can't go round in circles. Every step appears in the Workflow's log, signed `auto-improve`.

Each side was measured once per task, so a result is a hint, not proof; more held-out tasks make it a stronger one. One engineer has at most one open proposal. Proposals are for engineers only, since theirs is the work the eval measures. A diagnosis is one Claude Code run on the workbench (under $1 of your quota); a trial costs what its engineer runs and evals cost, up to two of each per task.

### The Lab: did the change solve more?

**Competition teams → Lab** keeps the eval score of every commit you check, so you can judge a change by what it solves, not by how its diff reads.

- **Scored checks.** An eval check that writes a results file (one line per run of a task, like `eval/eval.py`'s `runs.jsonl`) scores the commit it ran on. A task counts as solved only when every run of it passed, the way validators count. Next to that: runs passed, cost and agent time per run. An administrator sets this up with `"results"` in `/etc/axor-workbench.json` (see `workbench/README.md`).
- **Measure the base** runs the same eval on the branch you merge into. A task's check then shows, for example, *15/20 solved · base 13/20 (+2)*. A task is compared with the base measured at the commit it started from. When that commit was never measured (something was merged since), it's compared with the newest base and marked **other base**: the difference may come from the merged work, so it counts for no agent. **Measure the base at …** beside it measures that commit, and the comparison follows.
- **Import earlier evals** reads the folder's `eval/results/<label>/runs.jsonl` files, so your earlier runs show up next to the new ones.
- **Tasks solved over time:** one dot per eval. A filled dot is a task's branch, a ring is the base, a diamond is an imported eval, a triangle is an Improvements trial.
- **Compare:** pick any two evals (A and B) to see them task by task, on the tasks both ran: solved, gained, lost, runs passed and cost per run.
- **Every experiment:** the commit, the eval, the score, and what became of the task: merged, sent back, dropped, or superseded by a later commit.

The Lab never blocks a merge: the decision stays yours. An eval spends what the eval spends (OpenRouter credit for `eval.py --target openrouter`) and can take an hour or two, so run it when the change is worth measuring.

### GitHub: requests from an issue or pull request

**Competition teams → GitHub** links the Workflow to a repository of the Source hub, so the people you allow can ask the team for work where they already are.

- **Who may ask** is a list of GitHub logins. A mention of the **handle** (`@handle`, by default the account of the source's token) on an issue or a pull request's conversation becomes a task, from someone on the list only. Bots and everyone else are ignored, and the GitHub tab lists each one with the reason. Quoted lines and code don't count as mentions. The list is the only trust boundary: what a comment says can't change who may ask. Until the list has someone on it, nothing becomes a task.
- **A new request** either **waits for you** (it appears in Work like any task; you start it) or **starts by itself** (its engineer starts at once). The task keeps a *mandate*: who asked, where, and the version of the link's rules it was taken under.
- **Later comments** on the same thread go to the same task. With *starts by itself*, a comment on finished or stopped work sends it back to the engineer with the comment as the note; otherwise it lands in the log. `@handle stop` stops the task's run.
- **Replies** go to the same thread, in order: an acknowledgement, then finished, reviewed (with the verdict), stopped, merged (with the branch and commit) or dropped. They say what happened, not what the agent wrote, unless you tick **Include the agent's summary**; token-like text is removed and @mentions are defused either way. Mind public repositories before you tick it. GitHub's passing errors are retried; a reply GitHub refuses can be sent again from the tab.
- **Limits:** at most 5 open tasks from GitHub per workflow; more requests get a reply saying so. The repository is read once a minute. Replying needs the source's token to have **Issues: read and write** (fine-grained) or the `repo` scope (classic); the tab says so when a reply is refused.
- **What it doesn't do:** open pull requests (the work stays on the task's `bench/…` branch and you merge it in the Workflow), read inline review comments on a pull request's diff, or notice a mention added by editing an issue. Merging and submitting stay yours.

## Competition teams: an agent team per competition

Some subnets run several competitions at once, numbered off chain (Ridges, on SN62, runs several side by side). **[Competition teams](#teams)** (in the sidebar, under Workspace) gives each one you enter its own team of agents, with a tab per competition: **SN<subnet> · <number>**. A campaign holds up to 12.

- **Import competitions** brings competitions in from outside, automatically or by hand. Nothing becomes a team until you approve it (see below).
- **New competition** adds one by hand: the campaign it belongs to, its number or name, its dates, your goal, its rules and notes, and the team.
- **The team** is 20-odd agents in squads. A **Director** plans the competition and reviews the squad leads; each squad has a **squad lead** who reviews the squad's work. Ridges' teams share Command (the Director, a Rules & Scoring Analyst, a Leaderboard Scout), Agent build (an Agent Architect who writes `agent.py`, a Prompt Engineer, a Repo Navigation Engineer, a Cost & Latency Optimizer), Evaluation (a Benchmark Designer, a Task-set Curator, a Failure Analyst, a Red Teamer) and Release & quality (a QA Reviewer, a Compliance Checker, a Release Manager), plus their niche's experts. The database niche's team (Database Query Engineering) has two expert squads: Databases (PostgreSQL, ClickHouse, query performance, data correctness, schemas and migrations) and Application stacks (Go, TypeScript and Python data layers), 22 agents in all. Other subnets get a general team of 20. You can also start with a small team of five, copy another team, or start empty, and edit, add (up to 30), switch off and remove agents, move them between squads and make any of them a lead.
- **Autopilot** (the switch on a team's header) runs the team on its own: the Director plans every few hours (6 by default) and as soon as the board runs dry, assigned tasks start by themselves with at most 4 agents at work at once, and a finished task goes to its reviewer, who approves it or sends it back with what to change (twice at most; then it waits for you). Only what a person must do waits for you: your own tasks (uploads, registration, payments), agents' questions, and a task that failed twice. **Pause** lets the work in progress finish and starts nothing new; **Stop now** halts it at once. Imported teams start with autopilot off.
- **Autoloop** (a tab beside Workflow) shows the rules autopilot runs by and the loop it runs: observe, plan, execute, verify, learn, optimize, repeat. Each step shows what it's doing now and what it did today.
  - **Budget governor**: five checks before anything starts. They are the team's 24-hour budget, the competition's lifetime cap, the model provider's health, whether the next task is likely to fit, and a free slot. New tasks stop when only the reserve is left (15% of the day by default), which stays for reviews of finished work. When a check fails, work waits in the queue. It no longer starts, fails on the budget and counts as a failure.
  - **Per-task cap**: past it, an agent's tools stop and it must file what it has; at one and a half times the cap the run stops. By default it's 15% of the daily budget, and at least 60k tokens.
  - **Failures by class**: a run that ran out of budget, or that the model provider refused (bad key, no credit), goes back in the queue and isn't counted. A refusal or a rate limit also pauses the team for a few minutes. Timeouts, restarts, rate limits and server errors are retried after 1, 4 and 16 minutes, twice by default. Only the task's own failures count; after two of those, autopilot leaves the task to you (or to the Director).
  - **Queue**: autopilot keeps at most three tasks queued per slot. The Director doesn't plan while the backlog is deep (12 open tasks, or four per slot). Agents suggest one follow-up at most while it is. The tab explains why the queue is long (often the slot limit, not the team's size). It lists agents with long queues, with **Spread** to hand the extra tasks to idle squad-mates, and near-duplicate tasks you can delete.
  - **One agent per file**: an agent can't write a file that another running agent has written during its own run.
  - **Recovery**: after a server restart, the tasks it cut off on autopilot teams go back in the queue (not on teams that only observe).
  - **Autopilot mode**: **Act** (the default) lets autopilot start work on its own. **Observe only** keeps autopilot on but has it start nothing: it logs what it would start, when it would have the Director plan, and who would review finished work (finished work comes to you instead). Each entry is then checked against what you did: you started that task, someone planned, the review ran. A day later, an entry you didn't act on counts as *you didn't*. The tab shows the agreement over the last 7 days, so you can see whether autopilot picks what you would before you let it act. Switching back to Act closes the open entries; they never count as yours. Your own starts, plans and reviews run as usual while it observes.
  - **Cost of the work**: tokens per run, per filed task and per verified task (approved by a reviewer, the Director or you), and the week's tokens per day.
  - **Optimize** suggests what to change from the last day: let fewer work at once after rate limits, raise or share the budget, work the backlog down, check an agent that only fails. **Change the limits** sets the reserve, retries, the per-task and competition caps, and the queue and backlog caps.
- **Board**: To do, In progress (queued, working, and in review by a squad lead), Waiting for you, Done. Open a task for its result, its review (you can step in on a squad lead's review: your decision wins) and its runs, each with a trace of every model and tool call.
  - Every result also says how sure its agent is (high, medium or low) and lists the claims it rests on, each with its source: a file and line, a tool call, a chain block, a sandbox run or an eval.
  - A result with low confidence, or with claims that have no source, opens with those claims flagged, and its card on the board says *Low confidence*.
  - Squad leads and the Director see the same evidence. They're told to send work back rather than approve it when key claims have no source.
- **Notebook**: every approved result, newest first. Every agent reads it before it works, so the team doesn't redo what it has settled. When the campaign saves to a repository, the Scribe commits each entry under `<folder>/sn<netuid>/<competition>/notebook/`.
- **Files & sandbox**: the team's files (the Agent Architect's `agent.py`, practice tasks under `tasks/<name>/`) and the runs on them. A run is a throwaway pod on this server's cluster: Python, Go, Node and TypeScript, git and psql, with PostgreSQL and ClickHouse on localhost when it asks for them, and no internet unless an administrator turns it on for the team (**Internet in the sandbox**: runs then reach the public internet through AXoR's egress proxy, under gVisor, on ports 80 and 443 only, never this server or the cluster, with a cap on bytes in and out per run; files that look like secrets are held back, and each run lists the hosts it reached). Model calls go through a proxy that speaks Ridges' protocol (`$SANDBOX_PROXY_URL/api/v1/chat/completions` and `/api/v1/embeddings`, on the administrator's OpenRouter key) within a dollar budget per run and, like Ridges, per problem (`RIDGES_MAX_COST_USD`). `python .axor/ridges_run.py --agent agent.py tasks/<name> …` runs the agent the way Ridges does: the task's repository at `/repo`, `agent_main({"problem_statement": …})`, the returned diff applied to a clean copy, then the task's `check.sh` decides. A practice task is a folder with `problem.md`, `repo/`, an optional `setup.sh` (seeds the database) and `check.sh`. **Run a command** runs your own. Each team may spend 20 USD of sandbox inference a day.
- **Questions over many files** (`rlm_query`): when an agent needs to know something across more files than it can read one by one ("which tasks failed and why", "every place that calls this"), it can ask a recursive language model. The files go into a Python session in a sandbox pod as `context`; the agent's model explores them with code, hands chunks to a cheaper sub-model in parallel (`llm_batch`), and writes its answer to `answer["content"]` until it sets `answer["ready"] = True`. Each question takes a few minutes. It appears under Sandbox runs as `rlm: <question>`, with every step's code and output, and its sub-model calls count toward the team's daily sandbox budget. Only one runs at a time on the server.
- **Files** (at the top of Files & sandbox, and in [My workspace](#workspace) → Files): the team's files beside My workspace's, which are your AXoR Drive.
  - Tick files or folders and press **Copy to My workspace** or **Copy to the team**, or drag them onto the other side.
  - Copies into the team go into the team's open folder. They must be text files of up to 300 kB; anything else is skipped and the reason is shown. A file the team already has is replaced only when you press **Replace**. Drive names with spaces or other characters become paths with `-` (`my notes.md` becomes `my-notes.md`).
  - Copies to the drive go into the open drive folder and keep their subfolders. At the top of My drive or the Shared drive, they go to *Competition teams › <the team>*. A file that's already there gets a new version, so earlier ones stay in Drive's version history. Copies are tagged with the team's subnet, so My workspace shows them with that subnet. The Shared drive is readable by everyone signed in, so use My drive for code you keep to yourself.
  - The team side also has New file, New folder, Upload (text files), Rename or move (a folder takes its files along) and Delete. The drive side has New folder, Upload, a preview of text files and Move to trash. In My workspace, pick the team at the top: the open subnet's teams come first.
- **Activity**: everything that happened on the team.
- **Diagram**: the team as a live map you control. You at the top, then the Director, then each squad under its lead; each agent shows its level and whether it works, waits or is off. Animated lines show work going to its reviewer and work waiting for you. Drag agents where you want them (the layout is saved for the team; the reset button goes back to the automatic one), drag the background to pan, Ctrl + wheel or the buttons to zoom. Click an agent for its controls: switch it on or off, give it a task, start its next task, stop what it's doing, write to it, open its history or edit it. The team's controls (autopilot, pause, stop, plan, start assigned, write to the team) sit above.
- **Roadmap**: the competition from its start to its end, as milestones on a timeline with today's line, each with its dates, an owner, a status and the tasks finished in its window. **Set up the default roadmap** spreads five milestones over the competition's dates (or the next two weeks); add, edit, reorder by date and delete them as you like. Agents read the milestone in progress and the next one before they work.
- **Prompts**: every agent's prompt history: what each run (a task, a review, a plan) was asked and what it answered, and your messages. Pick one agent, several or everyone on the left; filter by kind or search. Tick entries one by one, **Select all shown**, or select every matching entry, then **Remember**, **Forget**, **Export** (Markdown) or **Delete** them; open one to read it whole or **Edit** it. **Write** sends a prompt to the agents you picked: a message they read in their next run, or a task each of them starts now; **Remember it** makes them re-read it in every run. What an agent remembers is this history: your unread messages, the entries you remember and its latest three replies, so editing or deleting an entry changes what it knows.
- **Levels**: every agent's engineer level, from Intern (L1) to Distinguished engineer (L7), earned from its work on the team: +40 XP per task done, +60 per finding approved into the notebook, +20 when it's approved without being sent back, +15 per review, +25 per plan, +5 per finished task run and −10 per failed run. The table shows each one's record (first-time approval rate, reviews, hours, tokens, days on the team, its most used tools); click a column to sort.
- **Links**: the team's Source repository, DevOps pipeline, cluster deployment, apps and functions, picked from those pages and shown with their live state (Source, DevOps, Cluster, Apps and Functions are administrators' pages; others see that). **Save the notebook** and **Save the prompt histories** write Markdown files to your Drive under *Competition teams / SN<subnet> <competition>*. Agents read the list of what's linked.
- **Import** (by Plan now) brings in what you did on the competition before the team existed, so the team carries on from there. On the machine where the work is, `python3 tools/mining-import.py <folder> --out work.json` packs the folder: its text files (code, plans, notes, eval logs and sets, up to 300 kB each), its git history, the Claude Code conversations held in that folder and Claude Code's memory notes. It only reads, and leaves out secrets (`.env` and key files, and API keys, tokens and passwords anywhere in the text), caches, other repositories and bulk data; a wallet's mnemonic has no shape to look for, so check the bundle if your work ever touched one. Upload `work.json` on the team: you see what's in it, with what fits the workspace ticked (files git tracks, plans, eval sets and logs; not downloaded data), and pick. **Import** puts the files in the workspace and the memory notes, the eval logs' scores and the git history in the notebook (a GitHub repository also becomes a link); the model then reads each conversation once into a dated notebook entry (what was asked, tried and found, and decided), and the Director reads it all and sets the team up: a **Start here** entry at the top of the notebook, roadmap milestones (what's done marked done), the open work as tasks that haven't started, and a report to you. Reading counts against the team's daily token budget and waits when it's spent; a conversation read for one team is free for the next. **Undo the import** takes out what it added, except files the team changed since and tasks that already ran.
- **Desk**: any of the team's views side by side. Pick a layout (Control room, Planning, People, Operations) or **Customize**: drag a panel by its grip or use the arrows to move it, choose its width or drag its corner, fold it to its title, hide it, bring hidden ones back; the shrink button makes it compact. The arrangement is kept in this browser.

Agents only read, write the team's files, and run code in the sandbox. Uploading (`ridges upload`), registering, signing and paying stay with you: the Release Manager writes the steps, and the task is yours.

## Import competitions: automatic and manual

**Import competitions** (on [Competition teams](#teams) and on a campaign's Teams tab) is where competitions come in. Whatever is found waits in **Review** until you decide; approving makes a team with autopilot off, so nothing runs, deploys, registers or spends by itself.

- **Import** by hand:
  - **From a URL**: a competition page, a GitHub repository or issue (its README or text), a ridges.ai page, a JSON address, or a subnet number (its on-chain competitions). AXoR picks the reader from the address, or you choose it. Only public addresses are read (local, private and internal ones are refused, redirects included), at most 2 MB, HTML, text, Markdown or JSON. A web page is read by the model, which fills the fields only from what the page says and quotes the sentence each came from; the page is data, never instructions. Without a model connected, only the page's title and description are read and you fill in the rest.
  - **JSON**: a list of competitions, `{"competitions": [...]}` or one object, pasted or from a file. Common column names are understood (name or title, subnet or netuid, id or number, start, end, url or link, status, scoring, rewards, requirements…).
  - **CSV**: up to 100 rows with a header row; you map each column to a field (or skip it) before anything is imported.
  - **Type it in**: the New competition form, which makes the team at once.
- **Sources** are checked on a schedule (every 30 minutes, hour, 6 hours or day): **Ridges competitions** (ridges.ai's competitions page, SN62), a **competition web page** (read by the model again only when the page changes), a **GitHub repository**, a **JSON feed**, or a **Bittensor subnet** (its on-chain competitions and their emission shares). **Check now** reads one at once. A new competition goes to Review; ended competitions nobody tracks are skipped; finding one again updates its entry in Review instead of adding another. When a competition already has a team, differences become an *update* to review, except Ridges' own dates, status and emission share, which update teams made from Ridges directly (as the old Ridges import did; a team you closed isn't reopened).
- **Review** shows each competition with:
  - its fields, each marked with how it was found: *From the source* (the source's own data), *Read by AI* (with the sentence it came from), *From the file*, or *Typed by you*. Unknown fields stay unknown: nothing is guessed.
  - the checks: *fails* (no name, an end before the start, a source address that isn't http(s)) blocks approval until you fix it; *needs a look* covers missing dates, an unknown subnet, a competition that already ended, and a field the model read whose quote isn't on the page.
  - possible duplicates among your teams (same competition ID, same subnet and number, same page, or a similar name) and in the queue, with the import and the team side by side.
  - **Assess with AI** (optional): a summary, the rules, deadlines, hardware, skills, the suggested team, risks, the opportunity and what to check, marked as an estimate.
- **Your decision**: **Edit** any field; **Approve and create team** on a campaign on the competition's subnet with the team you pick (the suggested pack, a small team, or empty); or **Update an existing team** with the fields you tick; **Save for later**, **Reject** (with a note) or **Delete**. Approving twice does nothing more, and creating a team that looks like an existing competition needs you to confirm it's a separate one.
- **History** lists every import, edit, check of a source and decision; approvals and rejections are also in the audit log.

Reading pages and AI assessments use the model of your first campaign and count against an import budget of 400k tokens per user per day; JSON, CSV, Ridges and subnet imports cost nothing.

Before November 2026 Ridges' competitions were made into teams by themselves for every SN62 campaign. That automatic import is now a Ridges source (created for you if you had it on), and its new competitions wait in Review like any other. Teams made earlier stay as they are; delete one from its settings if you don't want it.

## My subnets' Teams tab: the control room

A campaign's **Teams** tab lists its competition teams in one table: each one's status, autopilot (switch it on or off), who's at work, what waits for you, tokens today against its budget and its share of the emissions, with **Pause**/**Resume**, **Stop** and **Open**. Above the table:

- **Import competitions**: opens the import center, with the number waiting for your review.
- **Share a daily budget**: one number of tokens per 24 hours for all the campaign's open teams together, split by their share of the emissions (a competition at 50% gets twice what one at 25% gets). Teams without a share get the average.
- **Stop every team**: every competition team on every campaign of yours stops and pauses.

## The team

| Agent | Role | Uses tokens |
|---|---|---|
| **Avery**, Team Captain | Runs each cycle, reviews the actions the Strategist proposes, writes the brief you read, and answers your questions. | Yes |
| **Rio**, Data Scout | Reads the subnet's whole metagraph from the chain on schedule: every UID's rewards, incentive, trust, consensus, pruning score, stake, registration, axon and on-chain commitment. | No |
| **Kit**, Sentinel | Checks every snapshot for what needs you (see *Alerts* below). | No |
| **Ellis**, Competition Analyst | Studies the field: who leads and why, how rewards are spread, the bar to beat for your goal, churn, and the openings you can use. | Yes |
| **Finley**, Miner Coach | Tracks your miners against the field, explains why they moved, and suggests improvements to your product. | Yes |
| **Sage**, Strategist | Turns both reports into ranked recommendations and actions. | Yes |
| **Quinn**, Scribe | Commits each step's results to your repository as the step finishes (see *Save results to a repository*). | No |

## A cycle

1. **Snapshot**: Rio takes a fresh snapshot unless the last one is under two minutes old.
2. **Analysis**: Ellis and Finley work side by side. Each starts from a briefing of the headline numbers, makes up to five read-only lookups (the leaderboard, a miner's history, field trends, operators, changes, your miners, two miners side by side, and your repository's activity or your miner's app logs when those are linked), then files a structured report.
3. **Strategy**: Sage reads both reports, the recommendations you already have and what you did with earlier ones, and files the plan.
4. **Brief**: Avery reviews each proposed action (approve, pass to you, or reject, always with a one-line reason) and writes the brief: a headline, a green, amber or red standing, a short summary and what to do first.

Cycles run on schedule, when you choose **Run a cycle** (optionally with a note for the team), and early when Kit raises a critical alert (at most once an hour).

You can also run part of a cycle: one step on its own, or from one step on (for example, Sage and Avery again after you've told Sage something). A step that's left out lends its last results, when they're less than two days old, so the plan still has both reports. **Snapshot now** always reads the chain afresh.

## Alerts

Kit checks every snapshot and raises alerts for:

- **Critical**: one of your miners was deregistered; one is next in line to be pruned; your miner's app on this server is down.
- **Warning**: a miner is 2nd or 3rd in line to be pruned; its immunity ends within 6 hours and it would be at risk; it fell several places in 6 hours; it has earned nothing for two snapshots past immunity; it serves no axon while most of the top 20 do.
- **News**: a miner reached your goal; a new leader; the leader published a new commitment; registration got 30% or more cheaper.

Lasting alerts close by themselves when the check stops finding them; news stays a day. **Got it** hides one. A critical alert is pushed to your devices, even in quiet hours.

## The tabs

**Overview**: the Captain's brief, actions and tasks waiting for you, Sage's recommendations, Kit's alerts, **Ask the team** and the latest activity.

The overview is yours to arrange. **Layout** picks a preset: **Command center** (key numbers on top, compact, everything in view), **Classic**, **Focus** (the brief, what waits for you, recommendations) or **Watch floor** (key numbers, alerts and activity). **Customize** moves, resizes, folds and hides panels as on a competition team's Desk; the arrangement is kept in this browser. **Key numbers** is a ticker of your standing, rank, rewards, the gap to your goal, the field, alerts, what waits for you, teams that need you and the next cycle; click one to open its tab.

- **Recommendations**: mark one **I'm on it**, **Done** or **Dismiss**. When you dismiss one, say why: Sage reads your note next cycle and won't bring it back unless something changed.
- **Ask the team**: Avery answers with the same read tools the analysts use. Each answer has its own trace.

**Competition**: field trends over 24 hours, 7 or 30 days (the top miner, your goal's cutoff, the prune line, earning miners, the top miner's share, the registration cost); rewards by rank with your miners highlighted; Ellis's analysis (the bar to beat, advantages you can use, why the leaders lead, threats); the leader; movers; churn; operators that run several UIDs; and the full leaderboard with rank changes, incentive, trust, consensus, age, axon and each miner's on-chain commitment. Search it by UID, hotkey, coldkey or commitment.

**Teams**: the control room for the campaign's competition teams (see *My subnets' Teams tab* above); the teams themselves work on the [Competition teams](#teams) page.

**My miners**: each miner's rank, rewards, gap to your goal and to #1, trust and consensus, prune line or immunity, axon and commitment; charts of its rewards against your goal's cutoff and of its rank; the miners just above and below it; its history as a table; and Finley's report with improvements for your product.

**Team**: the workflow as a live diagram: Rio's snapshot, Kit's checks, Ellis and Finley side by side, Sage's plan and Avery's brief, with Quinn's lane below showing each file saved from the cycle. Each step shows its state in the running cycle, or the last one (working, done, reused, skipped, failed), how long it took, its tokens and what it found; the arrows move while work flows down them.

- Above the diagram: **Run a cycle**, **Snapshot now**, **Stop** (the team stops after the current step) and **Pause the team** / **Resume the team**.
- On each step: ▶ runs from that step on, and ⊘ switches the agent off (the Sentinel, Analyst, Coach and Strategist; the Captain and Data Scout run while the campaign runs).
- Click an agent for its card: what it did in the last cycle (with its trace and the file it saved), **Run only** this step or **Run from** here, your instructions for it (every run reads them), switching it off, and its recent runs and work.
- **Recent cycles**: a row per cycle and a cell per step; open a cell for that run's trace.
- Model use over the last 24 hours, and standing instructions for the whole team.

**Activity**: the live feed of everything the team does (filter by agent) and every model run. Open a run for its **trace**: each model call and tool call in order on a timeline, with its duration, tokens, input and output, then what the agent filed.

## How much the team may do on its own

In **Settings**:

- **Recommend only**: the team analyses and recommends; no actions are proposed.
- **Ask me** (the default): every action waits for you.
- **Restart when down**: Avery may restart your miner on its own when Kit sees it down, at most once in 6 hours. Everything else still waits for you.

Actions on the miner itself (restart it, or run its DevOps pipeline again) exist only when an administrator has linked a miner running on this server. Approving one asks you to confirm it's you, runs the page's own operation with its checks, and is in the audit log. Actions on miners anywhere else are **tasks**: steps and commands for you to run, which you mark done or dismiss. Review commands before you run them.

AXoR never signs, registers or stakes anything for you, and never asks for a seed phrase or key file.

## Save results to a repository

Quinn can commit each step's results to a GitHub repository as the step finishes, so the team's work builds up in your source repo, step by step. Turn it on in **Settings → Save results to a repository**, and pick:

- **Repository**: one on the [Source](#source) hub's list (your product's repository by default).
- **Branch**: `mining-hq` by default. A new branch is made from the default branch. Keep it off a branch that deploys on push.
- **Folder**: `mining-hq` by default.

Each cycle gets its own folder, `<folder>/sn<netuid>/competition-<n>/<date>/<time>-cycle-<id>/`, holding one Markdown file per step: `01-snapshot.md` (the field, the leaderboard, your miners and the subnet's competitions), `02-checks.md` (open alerts), `03-analysis.md`, `04-tracking.md`, `05-plan.md` (recommendations and actions with their commands) and `06-brief.md` (the brief and Avery's review). Each file ends with the step's data as JSON. Every file is its own commit, made in the order the steps finished. After a cycle, `README.md` in the competition's folder is rewritten with the latest brief and links to the recent cycles' files. Files are never overwritten, apart from the README.

What you need:

- Only an administrator's campaign can turn this on, because the Source hub's GitHub tokens are the administrators'.
- The token for that repository needs **Contents: read and write** (fine-grained), or the `repo` scope (classic).
- Anyone who can read the repository can read these files. On a public repository, that's everyone.

When a commit fails (no write access, say), the step shows **Not saved** with the reason, the team carries on, and the feed says so once per cycle. Deleting a campaign leaves the files it saved in the repository.

## Cost

Snapshots, alerts and saving to a repository are plain code and cost nothing. Each cycle makes two short tool loops and two structured calls on the campaign's model (Settings → Model; **Auto** uses the default). Each campaign (each competition's team) has its own token budget per 24 hours (200k by default; 0 means no limit): once it's spent, the team keeps watching and alerting, and the brief is written from the numbers until the budget frees up. Without a model connected, snapshots, alerts and a brief from the numbers still work. Each competition team has its own budget: 1M tokens per 24 hours for a 20-agent team, 150k for a small one. A task run is one short tool loop, and a plan and a review are one structured call each, on the agent's model; a big team on autopilot can spend 1-3M tokens a day, so set its budget (or share one from the Teams tab) before switching autopilot on. Usage shows under **My subnets** in your usage meter.

**Pause** the team in Settings to stop snapshots, alerts and cycles; everything is kept. Deleting a campaign removes its briefs, runs, traces, alerts and recommendations, and its competition teams.

## The measuring job of a release

A frozen release names a candidate and a suite. It can also freeze **the job that measures it**. On the Release form, give the number of a finished VM job that scored this suite, and the folder the candidate lives in (for example `miner`). Everything else that job was sent is its harness.

From then on a score counts as **measured** for this release only when the same job gave it: the same command and limits, the same harness files, the same pulled images, the same score file. The candidate under its folder may change; nothing else may. A score from another job, such as the team's own validator, is kept on the page, marked not comparable, and never counts for a mission's measure or a trial.

Without a measuring job, any VM job's score file counts under the suite's name. Freeze one before you rely on a team's benchmark numbers.

## Upgrade: the Agent Upgrade Factory

Competition teams → **Upgrade** makes a team's agents better at their own jobs in a timed sprint (30 minutes by default, a hard deadline), measured before and after on the same tasks.

1. **Diagnose**: each squad lead names its members' weaknesses on seven dimensions (reasoning, domain expertise, execution, tool efficiency, verification, reliability, collaboration) from their instructions and record. An Examiner who isn't on the team writes each agent practice tasks and held-out exam tasks.
2. **Identify weaknesses**: the agent as it is answers both; the Evaluator reviews the practice answers.
3. **Upgrade**: the Upgrade Engineer writes a candidate: role, five responsibilities, knowledge, tool use, examples, failure patterns and done criteria, compressed into at most 1,500 characters of instructions.
4. **Practice**: the candidate answers the practice tasks; if it did worse, it's revised once when there's time.
5. **Evaluate**: both versions' exam answers are scored blind by the Evaluator. The Agent Level Score (0–100) weighs domain and execution 20, reasoning and verification 15, the rest 10. Better = 3 points or more with no dimension down by more than 1.5.

The weakest agents go first; agents the clock can't fit are recorded as cut and can't be sent to trial.

A sprint changes nothing in the team. Its exam is scored by a model, so it **screens** candidates; it doesn't promote them. **Send to trial** puts a candidate that did better into the [Evolution Lab](#evolution) as a proposal for that agent (bound to its exact text, once, within 7 days, and refused if the agent's instructions changed meanwhile). There it goes on trial on the team's own benchmark, and a person promotes it only if the trial's measured scores show it is better. A trial starts only for a team the Owner turned experiments on for. Every earlier version of an agent's instructions can be restored. Models, tools, permissions and credentials never change. A sprint of 20-odd agents makes about 170 model calls; pick another Evaluator model for a more independent score.

## Top miner

Competition teams → **Top miner** is the short road to a top miner on what the team already measures:

- **Roadmap** M1 reliability → M2 task-solving quality → M3 validation lab → M4 cost and speed → M5 controlled submission, each with evidence read from the Lab and the Command center (or set by hand).
- **Validation set**: 30–50 tasks over five categories (generation, fixing, optimization, schema and indexes, semantic edge cases), PostgreSQL and ClickHouse, dev or held out. Names match the eval's task names; import them from the Lab's evals or paste a list.
- **Scorecard** from the newest Lab eval on the set: correctness, reliability, efficiency, generalization (held out against dev) and solved ÷ (dollars × hours). The official score and rank (Command center metrics) stay apart.
- **Elite team**: the 13 critical-path roles filled from the team; the rest support.
- **First mission**: eleven tasks on the board for a 30-minute first milestone. Agents never upload or submit: M5 is yours, through the Command center's approval.
