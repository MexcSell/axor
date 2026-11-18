---
title: Agent HQ and its field agents
section: admin
order: 3
audience: admin
icon: flag
summary: The agents that look after AXoR's platform: what they check every 10 minutes, how fixes are reviewed and approved, the hourly report, the roster of every agent, and the settings.
---
[Agent HQ](#hq) is a team of agents that looks after the platform AXoR runs on: its own services, apps, functions, pipelines, the cluster, this server, the edge and DNS. Like the pages it watches, it's for administrators only.

## The team

| Who | Job |
|---|---|
| **Jordan**, Team Boss | Writes the hourly report you read, and pushes what only a person can decide to your devices |
| **Morgan**, Agents Manager | Sends each finding to the field agent that owns it, keeps the hourly token budget, decides who investigates first (critical issues first), and keeps the roster of every agent on the server |
| **Quinn**, Services Lead | Reviews the fixes the services team proposes: approves, escalates to you, or rejects each one |
| **Rowan**, Infrastructure Lead | The same for the infrastructure team |

The field agents, each with its own checks:

| Team | Field agent | Checks every patrol |
|---|---|---|
| Services | **Casey**, AXoR services | Every deployment in `axor`, `axor-edge` and `axor-host` has its pods ready; no pod crash-loops or restarts 3 or more times between patrols; no rollout is stuck |
| Services | **Harper**, Apps | No app is failing, failed or degraded, or keeps restarting |
| Services | **Skye**, Functions | The same for functions, and none fails 20% or more of its calls between patrols (5 or more server errors) |
| Services | **Blake**, Pipelines | The AXoR Runner answers, each pipeline's latest run succeeded, and every deployed app is running |
| Infrastructure | **Reese**, Cluster | Nodes are ready, without memory, disk or PID pressure; Kubernetes' own services and machines are ready; no scheduling, volume, eviction or out-of-memory warnings |
| Infrastructure | **Emery**, Server | Disk under 85% full (critical from 95%), memory under 90% over the last hour, no heavy swapping while memory is short, CPU under 90% over the last hour, load |
| Infrastructure | **Sasha**, Edge, TLS & DNS | The platform's sync (certificate, DNS, routes) works; the edge certificate has 21 or more days left (critical under 7) and AXoR's CA 60 or more; AXoR DNS answers |

A field agent whose service isn't set up on this server (no Kubernetes, no AXoR Runner) shows **Not set up here** and sits out.

## A patrol

Every 10 minutes (`HQ_PATROL_MINUTES`):

1. **Checks.** Plain code: no model, no tokens. Each finding opens an issue, which stays open until a check stops finding it. It's then resolved as "Fixed: …" or "Cleared on its own".
2. **Investigation.** A new issue, or one whose finding changed, gets one short investigation by its field agent. The agent uses the read tools of the matching operations agent, at most 6 calls. It files a diagnosis and a recommendation, and may propose one fix. An unchanged issue is looked at again after 6 hours; a snoozed one isn't.
3. **Review.** The lead approves, escalates or rejects each proposed fix, with a one-line note you can read.
4. **Fixes.** Depending on the setting below, a fix runs or waits for you.
5. **Verification.** If a fix's issue is still there two patrols later, the fix is marked as not having helped and the issue needs you.

**Patrol now** runs a patrol, with a report, straight away.

## The hourly report

Once an hour a patrol ends with the Team Boss's report: a headline, a short summary and what needs you. When nothing happened, it's written from the numbers and costs nothing. Its status is computed, not guessed:

- **Red:** a critical issue is open (unless HQ just fixed it and is verifying), or a fix failed.
- **Amber:** an issue is open, or a fix waits for you.
- **Green:** everything else.

Earlier reports are on the **Reports** tab, each with the hour's issues, fixes and what the agents did.

## How much HQ may fix

| Setting | What happens |
|---|---|
| **Report only** | Field agents diagnose and recommend. Nothing is proposed or changed |
| **Ask me** (the default) | Every fix a lead doesn't reject waits for you on the Overview and Issues tabs |
| **Fix safe issues** | A fix the lead approves runs at once when it restarts something that's failing right now: a deployment, an app, a function or a deployed pipeline app, or a crashed pod recycled. At most 3 a patrol, and once per target in 6 hours. Everything else still waits for you |

> [!IMPORTANT]
> Turning on **Fix safe issues** and approving a fix both ask you to confirm it's you. Every fix is checked again by its operations agent before it runs, then runs the page's own operation with its own audit entry. Fixes HQ runs on its own are audited as `HQ · Quinn` or `HQ · Rowan`.

- AXoR itself (`axor/web`) is never restarted or recycled from HQ, because HQ runs inside it. HQ never scales anything.
- A fix waiting for you expires after 3 hours, or as soon as its issue goes away.
- **Snooze 24 h** on an issue keeps it out of investigations, reports and the sidebar count until it wakes up.

## Notifications

With **Push notifications** on (the default), administrators' devices get:

- critical issues at once, even in quiet hours
- fixes waiting for approval
- the hourly report, when its status changes or is red

The sidebar's count is the number of fixes waiting for you plus open critical issues.

## Roster

The Agents Manager's view of the server:

- **HQ agents**, each with its state, last check, open issues, fixes and tokens today. Switching a field agent off duty stops its checks and closes its open issues.
- **Model use** on the server by feature over the last 30 days.
- The **built-in agents**.
- **Every member's agent**, with its owner and token use. **Pause** stops anyone chatting with it (and keeps it out of project-team work) until it's resumed. Its owner can resume it too.

Changes are in the audit log (`hq.agent`, `hq.roster`, `hq.settings`).

## Model and cost

- **Model:** Auto (the default model) or any connected model. Investigations, reviews and reports are short, so a smaller model is plenty.
- **Token budget per hour:** 40,000 by default, 0 for no limit. Once the last hour's use reaches it, the Agents Manager holds the remaining investigations until a later patrol. Checks never use tokens.
- Without a model, HQ still checks and reports from the numbers.
- `HQ=0` in the environment turns Agent HQ off.
