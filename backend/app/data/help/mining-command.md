---
title: Mining command center
section: guide
order: 4
icon: dash
summary: My subnets' control room over every subnet and competition. See measured performance, run experiments from idea to monitoring, approve deploys, track miners, and weigh rewards against costs.
---
**Command center** is the first chip in [My subnets](#mining)'s row of campaigns. It opens there by default. Pick a campaign chip to see that campaign's own tabs, and pick **Command center** to come back.

It works competition first. You pick a subnet, then a competition. You read its performance, put a team on it and run experiments. You evaluate them, approve the deploy, then watch the results and the rewards. The strip above the tabs shows that loop, and each step opens the section that does it. Agents do the work; competitions are what you run; performance and rewards are the outcome.

Every number here was measured by someone. Scores come from the competition's evaluator, from your own entries or from the Lab. Rank and rewards come from My subnets' on-chain snapshots. Nothing is estimated. A number nobody measured shows as "–" with a note on how to measure it.

## Dashboard

- **Key numbers**: the latest evaluator score, your best on-chain rank, on-chain rewards a day, miners up, experiments in flight and approvals waiting. Click a tile to open its section.
- **Competition operations**: a row per competition team. Each row shows the team's state, its primary score and the change since the last report, whether an evaluator reports, experiments by stage, and the agents at work. Click a row to open that competition's HQ.
- **Critical**: the worst checks from Monitoring.
- **Approval queue**: what waits for you, from every source.
- **Subnets**: each campaign's rank, rewards and standing. Click one to open the campaign.

## Competitions

Each competition gets its own HQ with nine tiles: **Overview**, **Intelligence** (the latest brief and the field), **Miner**, **Agent team**, **Performance**, **Experiments**, **Files**, **Knowledge** and **Strategy** (the brief's priorities and open recommendations). Each tile has a button to the page with the details: the team on [Competition teams](#help/mining), or the campaign's own tabs.

## Performance Lab

The Performance Lab shows each metric over time:

- evaluator score and rank
- correctness and task success rate
- latency P50, P95 and P99
- throughput, error rate and uptime
- cost per successful task

It also charts your miners' on-chain rank and lists the Lab's scored runs, with latency worked out across tasks.

The competition's own metric comes first. You choose it per team in **Settings**; it starts as the evaluator score. Latency, errors, cost and uptime are constraints next to it.

**Connect the evaluator.** Make an ingest key in **Settings**. Then have the evaluator post each evaluation:

```
curl -X POST https://<your AXoR>/api/mining/command/ingest \
  -H "Authorization: Bearer mcx_…" -H "X-Requested-With: scout" -H "Content-Type: application/json" \
  -d '{"competition": 12, "run": "eval-2026-11-02", "metrics": {"score": 0.71, "latency_p95": 880, "error_rate": 0.02}}'
```

`competition` is the team's id, shown at the top of its Performance Lab. Shares (correctness, success rate, error rate, uptime) go from 0 to 1. Latency is in milliseconds and cost in dollars. Add `"miner": "<hotkey>"` to tie the numbers to one miner.

A key can only add reports. It can't read anything, and you can revoke it at any time. **Record a measurement** stores a run you measured yourself.

## Experiment Center

Every improvement goes through eight stages, shown as a board:

1. **Idea**: what could be better and why. You or an agent spots it.
2. **Proposal**: the expected benefit, the risks and the cost.
3. **Sandbox**: try it in isolation. Link a sandbox or Lab run of the team, or note where you tried it.
4. **Evaluation**: baseline runs against candidate runs. Add them by hand, from the evaluator's reports (one run label = one run), or from the Lab. Name the artifact to deploy (a commit, version or image) and the miner. For each metric, the table shows each side's mean, spread and number of runs, the difference, and the noise band (two standard errors). It then reads the difference as better, worse or within noise.
5. **Recommendation**: the **Evidence Reviewer** reads the evidence. It never proposes experiments, so it reviews independently of the author. Its rule checks come first: enough runs on each side (3 by default, set in Settings), the primary metric better beyond noise, no constraint worse beyond noise, and a named artifact. If a model is connected, it then reads the numbers too. The model can only make the verdict stricter: **recommend**, **hold** or **reject**. One benchmark run never recommends anything.
6. **Approval**: **Ask for approval** sends a deploy request through the [Company](#help/company)'s gateway. The request is bound to the evidence's SHA-256, it expires, and it can be used once. If the evidence changes after the review or the request, it can't be approved. **Approve**, **Ask for changes** or **Reject**, with a reason. **Revise the evidence** takes it back to evaluation, and the reason goes into the log.
7. **Production**: **Authorize and hand off** uses up the approval and hands the deploy to you. AXoR never deploys. Deploy exactly the approved artifact, then **Record the deploy** with its version.
8. **Monitoring**: what the evaluator reports after the deploy, against the baseline and the candidate. If the primary metric falls below the baseline beyond noise, Monitoring flags a regression. **Keep it** closes the experiment. **Roll back** records the rollback, and the previous version becomes the active one again. Carry the rollback out on the miner yourself.

Each experiment keeps a log of every step, run, review and decision.

## Miners

Each miner of your campaigns gets a workspace. Miners under a campaign's keys appear by themselves. **Add a miner** adds one that isn't registered yet.

- **On chain**, from the snapshots: UID, rank, τ a day, incentive, trust, consensus and rank history.
- **Off chain**, from what the miner reports with an ingest key: version, uptime over 24 hours, CPU, memory, GPU, errors and log lines.
- **Your notes**: name, competition team, version, hardware, configuration and notes.
- **Deployments and rollbacks**, with the experiment behind each one.

Hotkeys are public addresses. Keys, seed phrases and passwords never come here: anything that looks like one is refused.

To report health, a miner adds this to a report:

```
"miner": "<hotkey>", "health": {"up": true, "cpu": 0.4, "mem": 0.6, "gpu": 0.7, "errors": 0, "version": "v1.5.0", "log": ["…"]}
```

## Rewards

For each subnet competition, over the last 7, 30 or 90 days, as amounts a day:

- **Rewards**: on-chain rewards (τ, and dollars at the collector's price) and the competition payouts you enter.
- **Costs**:
  - compute, hosting, infrastructure and other costs you enter (per day, per month or once);
  - sandbox and Workflow dollars;
  - model tokens, in dollars once you set a rate in Settings.
- **Results**: net, ROI, and the dollars a month you expected against what came in.

**Where to put effort** sets each team's measured score and emission share against its token spend. A high score isn't automatically profit.

## Approvals

**Approvals** lists every production or external action waiting for you:

- experiments' deploy requests, and anything else the Company has pending;
- My subnets' actions on a miner;
- Workflow merges ready to go in.

Each one opens where you decide it.

## Monitoring

Monitoring checks for:

- miners that went silent, report themselves down or report errors;
- uptime below 95%;
- miners missing from the latest snapshot;
- evaluators quiet for more than 24 hours;
- regressions after a deploy;
- critical My subnets alerts;
- stuck teams.

## Agents

Every competition-team agent, filtered by subnet, competition, squad and status, with tasks done, runs, failures and tokens over 7 days. Click an agent to open its team's Agents tab.
