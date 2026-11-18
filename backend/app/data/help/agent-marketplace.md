---
title: Agent Marketplace
section: guide
order: 3
icon: apps
summary: Don't build every agent from scratch. Find agents that already exist, evaluate them on the job they'd do, import them with their origin kept, adapt them, and after your approval put them to work as your own agents.
---
The [Agent Marketplace](#market) (sidebar → Agents → Agent Marketplace) is AXoR 4.0's agent ecosystem. It has three tabs:

- **Ecosystem**: find agents, follow each one through its lifecycle, and see every package you hold.
- **Workforce**: the imported agents at work.
- **Intelligence**: how the agents score, side by side.

## Where agents come from

| Source | What you get |
|---|---|
| Your library | Your own agents and skills, packaged so you can evaluate them, adapt them and keep their versions. |
| Agent Cards | External agents whose A2A cards you keep in [Agent Operations → Ecosystem](#help/agent-operations). AXoR never calls them. They import as a native agent written from the card's description and skills. |
| GitHub | Public repositories. Search for a role ("python engineer") or a framework ("crewai"), or type `owner/repo`. **Look inside** lists the files that could hold an agent, best first: an AXoR package (`axor-agent.json`, `*.agent.json`), agent files (`.claude/agents/*.md`, `agents/*`), `agents.yaml`, `AGENTS.md` / `CLAUDE.md`, then the README. AXoR reads GitHub through `api.github.com` only. |
| Paste a package | An AXoR Agent Package, an agent file (YAML front matter, then the instructions), a CrewAI agent (role, goal, backstory), an Agent Card, or any JSON with a name and instructions. |
| Third-party catalogs | Not connected yet. Copy an agent's package from its page and paste it. |

Stars and descriptions aren't quality. Evaluate an agent before you import it.

## The AXoR Agent Package

Whatever the source, an agent becomes one package (schema `axor.agent/v1`). It records:

- identity and role
- instructions
- skills (with their content)
- tools, models and runtime/framework
- dependencies and the input/output contract
- permissions, version, author and license
- evaluations

A package read from a README or `AGENTS.md`, with no manifest of its own, is marked **derived**. The **Manifest** tab shows the package next to the text exactly as it was found. That text is shown as text and never run.

## The lifecycle

1. **Discovered.** The agent is quarantined. Nothing of it runs anywhere except its evaluation, and that has no tools.
2. **Evaluated.** It has been scored on its role's tasks. You can see what it would do before you import it.
3. **Imported.** The original becomes **version 1**, its DNA, and never changes.
4. **Configured.** Each change you make on **Configure** is a new version on top: name, role, instructions, its own skills, AXoR skills, icon and the preferred model.
5. **Tested.** The newest version has been evaluated, now with AXoR's read-only tools.
6. **Approved.** You approved one exact version. The approval is bound to that version's hash and is used once.
7. **Active.** Activating creates the agent in your [Agents](#help/agents), or updates it if it's already there. Agent Operations keeps the earlier configuration as a version. You can also register it in your [Company](#help/company).

**Retire** pauses its agent. **Reject** ends a package that isn't active. Versions waiting for approval and score drops also appear in the [Approval Center](#help/command-center).

## Security and compatibility

- **Security scan.** A static read of the package. It looks for:
  - hidden or direction-changing characters
  - instructions to send secrets somewhere, or to collect your passwords or keys
  - attempts to override other instructions
  - shell pipes and long encoded blobs
  - permissions and credentials it asks for
  - unpinned dependencies

  A package with a critical finding is **blocked** and can't be imported.
- **Never granted.** Whatever a package asks for, imported agents get AXoR's read-only tools only. They get no shell, no file writes, no network and no credentials. The **Compatibility** card shows how each of its tools maps.
- **Frameworks.** AXoR runs an agent from its instructions on its own runtime. A LangGraph, CrewAI, AutoGen or other framework's agent brings its role, instructions and skills. Its graph or crew code isn't run, because that needs an adapter AXoR doesn't have. It's marked **Adapter needed**.

## Evaluation

**Evaluation** runs the agent on tasks for its role. Every package starts with:

- three built-in tasks for its role family (Python engineering, ML research, infrastructure, security, research and analysis, or writing)
- a task outside its speciality
- an injection probe

You can add up to eight tasks of your own, or have the model **write 2 for this role**. The tasks are kept on the package, so later runs are comparable.

Each answer is scored by a separate evaluator call on nine dimensions:

| Dimension | Weight | How it's measured |
|---|---|---|
| Task performance | 25% | The evaluator's score on the role tasks. |
| Technical quality | 15% | The evaluator's score on the role tasks. |
| Reasoning | 12% | The evaluator's score on every task. |
| Reliability | 10% | A repeat run of the first task, and any failures. |
| Speed | 6% | Time per task. |
| Cost efficiency | 6% | Tokens per task. |
| Tool proficiency | 8% | Not measured in quarantine. |
| Security | 10% | The scan, plus how it handled the injection probe. |
| Adaptability | 8% | The task outside its speciality. |

The score is AXoR's evaluation on those tasks. It's a way to compare your candidates, not a public benchmark. Each run's answers and the evaluator's notes are under **Runs**. Evaluation tokens count against your daily budget and show in Agent Operations.

## Workforce and Intelligence

- **Workforce** lists the active imported agents, with links to the Agent workspace, Agent Operations, Workforce, Company and Orchestration. Choose how often each one is re-evaluated: daily, weekly or monthly. If an agent scores 8 points or more below its previous run, it's flagged as a regression. To roll back, activate an earlier version. That needs its own approval.
- **Intelligence** shows the leaderboard (filter by role), **Compare two** (the dimensions side by side) and the continuous evaluation of active agents.
