---
title: Models, agents and connectors
section: admin
order: 2
audience: admin
icon: key
summary: Connecting model providers, who may use agents, the default model, usage, the built-in operations agents and Connectors.
---
## Connecting models

**Agents → Models** lists every connected model in one list: the models connected with a key or token, the server's named logins and your own Claude Code / Codex login. **Add model** opens a dialog that only adds: pick the **Type** (API Key, CLI or Local), the **Model** (API Key: Claude, OpenAI (Codex), GitHub (Copilot), OpenRouter; CLI: Claude, OpenAI (Codex), GitHub (Copilot)), give it a **Name**, then enter the API key, the server URL or, for a CLI, a **Token**, and choose **Connect**: it's checked before saving, and the model is added when the check passes. The dialog shows nothing about models that are already connected; adding a model that's already there replaces its key or token. API Key → GitHub (Copilot) takes a GitHub token with Copilot access (create one at github.com/settings/personal-access-tokens) and offers the Copilot plan's chat models. CLI → Claude takes the token `claude setup-token` prints; CLI → OpenAI (Codex) takes a Codex access token or an OpenAI API key (sk-…, billed to the API). CLI → GitHub (Copilot) takes a fine-grained GitHub token and runs GitHub's Copilot CLI. For CLI → Claude or OpenAI (Codex), **Login** picks how it's added: **Token** (paste a token the server runs on) or **Website sign-in** (sign in on Claude's or ChatGPT's website with your own plan). Models added either way can be used by everyone on the site: a website sign-in runs its owner's work first, and teammates' work when the token login is off or at its usage limit. With Website sign-in, **Connect** opens Claude's or ChatGPT's sign-in page in a new tab: for Claude, sign in and paste the code its last page shows back into the dialog; for Codex, enter the code the dialog shows on the page. When the sign-in is through, the login is checked and saved, and the model appears in the list. Every explanation on the page and in the dialog sits behind a **?**: hover, focus or press it to read it. Errors stay in sight. Each connected model is a card: its **State**, the **supported models** (a few of them; **Show more** opens the whole list, with OpenRouter's free models tagged), the plan's usage (only the windows the plan has), a CLI's tool calls and runs at once, a Local model's server URL. There is no Save button: each setting is saved as soon as you change it (a new Local URL is checked first). The card's border and name are green when it's connected, amber when it has hit a limit and red when it can't be used. The refresh button on its usage reads the usage again and lists the model again, so its state is redrawn too; on a named server login it also checks the login with one tiny prompt. The brown trash can in the card's top right corner removes the model (after you confirm). The **switch** next to the card's state turns the model off or on. A model that's off stays connected (its key, token or login is kept), but no agent, chat or team runs on it and it leaves the model menus; its card turns grey with a dashed border and says **Off**. Work that names it fails with "switched off" until you turn it on again. On your own Claude Code / Codex card the switch is yours: off, neither your work nor your teammates' runs on your plan. The pencil next to its name renames it (Enter saves, Esc cancels). Names are kept in your browser. **Default model** opens a dialog: pick a connected model first, then one of the models it offers; OpenRouter's are split into **Paid models** and **Free models**, and long lists have a search box.

The providers agents run on:

| Provider | What you give it |
|---|---|
| **Claude** | An Anthropic API key |
| **OpenAI** | An OpenAI API key |
| **OpenRouter** | One key for Gemini, Llama, DeepSeek, Mistral and hundreds more (only models with tool calling are listed) |
| **Local** | The base URL (and optional key) of an OpenAI-compatible server: Ollama, LM Studio, vLLM, llama.cpp |
| **Terminal** | The Claude Code CLI on the server, signed in with its own Claude login: no API key |
| **Codex** | OpenAI's Codex CLI on the server, signed in with a ChatGPT plan: GPT models with no API key |

- Keys and URLs are **verified** with a model-list call (it costs nothing), then **stored encrypted** with Fernet under `DATA_DIR/secret.key` (or `SECRET_KEY`). Browsers only ever see a masked form such as `sk-ant-…WXYZ`.
- Connecting or removing a provider needs sudo and is audited.
- Keys saved here take priority over the `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY` and `LOCAL_LLM_URL` environment variables.

> [!TIP]
> **Local server in Docker:** the container can't reach `localhost` on your machine. Use `http://host.docker.internal:11434/v1` for Ollama. Local models need tool calling for agents to look things up (Llama 3.1+, Qwen 2.5+).

### Terminal

Terminal runs `claude -p` once per model turn, as the user that runs AXoR, with the CLI's own tools, MCP servers, hooks, plugins and CLAUDE.md turned off and any API key withheld, so usage counts against the Claude Code login. In a container, run `claude setup-token` once on your machine and set `CLAUDE_CODE_OAUTH_TOKEN` to the token it prints.

A second Claude Code login, **Claude-37**, runs on the token in `CLAUDE_CODE_OAUTH_TOKEN1` (Claude Code · Opus, on that token's own plan). While that variable is set it has its own card in **Agents → Models**, with that plan's usage. The token comes from the server's `.env`, so the card has no trash: to change or remove it, edit `.env` and redeploy. A token that's set isn't proof that it works, so the card stays **Not checked yet** until you press **Test**, which runs one tiny prompt on it. After that it's green when it works, amber when its plan's limit is reached and red when the token was refused. Claude-37 is offered in the model menus as soon as its token is set, for admins and system work only.

### Codex

Codex runs OpenAI's `codex exec` on the ChatGPT plan it is signed in with (an API key is API Key → OpenAI). Sign it in once on the server with `kubectl -n axor exec -it deploy/web -- codex login --device-auth`, then connect it here.

**Tool calls** works as it does for Terminal. **Native** (the default) is one Codex session per agent run: agents' tools reach it through a private MCP connection, so calls and their inputs are real and the conversation is cached. **Written as text** is one CLI run per turn. Either way the CLI's own shell, web search, browser, apps and plugins stay off, the sandbox is read-only and the folder is empty. In native mode Codex calls tools from its code mode, a bare JavaScript runtime with nothing but the tool bindings: no files, network or processes. Codex reports tokens when a run ends, so a run's whole cost lands on its last step. Codex usually makes one tool call at a time, and each counts as one of the run's steps. A server image without Codex's code-mode host shows up on the first tool call, with a message saying so.

### Teammates' own logins (Agents → My logins)

Claude and ChatGPT plans are personal, so the server's Terminal and Codex logins are for admins and system work only. Each teammate connects their own plan under **Agents → My logins**:

- **Claude Code:** they run `claude setup-token` on their own computer and paste the `sk-ant-oat…` token. It's stored encrypted and is never shown again.
- **Codex:** **Sign in with ChatGPT** starts `codex login --device-auth` on the server. They open the link, enter the code, and the login is saved in their own private Codex folder. Never copy someone's `auth.json`: Codex rotates refresh tokens, so a copy signs out the original.

A call runs on the login of the person it's for: whoever made the request, or the owner of the agent, team or run. Each login has its own parallel slots and its own usage-limit clock. **Runs at once, per login** on the CLI → Claude and CLI → OpenAI (Codex) models sets how many slots each login gets (default 2, up to 24). It's AXoR's own limit: one login can run many at once. It applies right away, to the server's login and everyone's own. A higher number finishes parallel work sooner but uses the plan's usage window sooner, and that window is shared with the person's own Claude Code or Codex. Each run is a CLI process of about 300 MB on the server, and the pod has room for about 24. A Competition team's own **parallel** setting (default 4, up to 24) caps that team on top of this: for a 20-agent team to work at once, set both to 20. Reaching that limit pauses that person's work only; it never moves to the server's plan or a teammate's. Members who haven't connected a login get a message telling them how. Logins of deleted accounts are removed automatically.

**Team logins** (admins, in the same dialog) lists everyone with their Claude Code and Codex status: connected, not working, asked, declined or expired. You never see a token or a sign-in code. To set the team up, tick the people and the CLIs and choose **Ask to connect**, or use **Ask** on one cell. Each person then gets:

- a banner in AXoR (**Connect** opens their My logins with the asked cards highlighted);
- a push notification on their devices, when push is set up.

They connect their own login there, which takes about a minute. For Codex they click **Sign in with ChatGPT** and enter the code on OpenAI's page. For Claude Code they need Claude Code on their own computer to run `claude setup-token`. The request is answered as soon as that login works. You can see when they've seen it and whether they declined.

- **Remind** sends the request again, at most once an hour.
- **Cancel** withdraws it.
- Requests expire after 14 days. **Ask again** starts a fresh one, and it also works for a login that stopped working.
- **Copy link** gives you a link (`/#agents/logins`) to send in chat; it opens My logins for whoever is signed in.
- **Remove** deletes someone's login when they leave (this needs sudo).

Members can be asked only while **Members can use agents** is on; otherwise they couldn't open My logins. Asking someone starts nothing on their account and never makes a call on their plan.

## Who may use agents, and the default model

- **Members can use agents** opens agents to every signed-in user. Off, agents are for administrators only. Study tutors and drills, the board assistant and the profile's AI review follow the same switch.
- The **default model** is what **Auto** means everywhere, including Tech Daily's copy (unless `TECH_MODEL` names another). Without one, Auto is Claude's default (`AGENT_MODEL`, `claude-opus-5-5`) when Claude is connected.
- Every model call is counted per user and feature; each user sees theirs on the usage meter.

## Built-in operations agents

For administrators, alongside the User administration agent:

| Agent | Reads | Proposes |
|---|---|---|
| **DevOps** | Pipelines, runs, step and app logs, the Source hub's CI | Runs, rollbacks, cancels; app start, stop, restart |
| **Functions** | Code, settings, logs, call statistics | New functions, code changes (as a diff), test calls, restarts, stops, rollbacks |
| **Apps** | Status, pods, events, revisions, logs | A new image or replica count, restarts, stops, rollbacks |
| **Cluster** | Nodes, deployments, problem pods, warnings, pod logs, server resources | Restarts, scaling, pod recycling (`kube-system` stays read-only) |
| **DNS** | Zones, records, lookups, delegation checks | Adding, changing and removing records (platform and ACME records are off limits) |

Read tools run at once; changes are approval cards that run the page's own operation, with its checks and audit entry, plus `agent.approve`. Agents see environment variable **names**, never values, and secret values are masked in logs.

For agents that watch the platform on their own every 10 minutes and report every hour, see [Agent HQ](#help/admin-hq).

## Connectors

[Connectors](#connectors) lists every outside service AXoR holds a key for (model providers, Slack, GitHub, service secrets), each with where it's set and a masked form; each is changed on its own page. Secrets never leave the server.

It also manages your **OpenRouter API keys** with an OpenRouter management key (`OPENROUTER_MANAGEMENT_KEY` works until one is saved): what each key has spent (total, today, this week, this month), creating, renaming, credit limits, disabling and deleting. The key AXoR's agents use is marked. A new key is shown once, to you, and not kept.
