---
title: Architecture
section: dev
order: 1
icon: layers
summary: AXoR's services, how a request flows, background work, where data lives, and the front end's structure.
---
## Services

AXoR is one web app and a few small services, each with its own Dockerfile.

| Service | Code | Port | What it does |
|---|---|---|---|
| **web** | `backend/app`, `frontend` | 8000 | The FastAPI app: every page's API, the static front end, background collectors |
| **drive** | `drive/drive.py` | 8100 | AXoR Drive: files, folders, versions, sharing, search, share links |
| **push** | `push/push.py` | 8300 | AXoR Push: Web Push subscriptions, VAPID keys, encrypted delivery |
| **runner** | `runner/` | 8200 | The DevOps runner: the only part allowed to build images and create containers |
| **dns** | `dns/dns.py` | 53, 8400 | AXoR DNS: the authoritative name server and its management API |
| **edge** | Traefik | 443 | HTTPS for AXoR, apps (`*.apps`) and functions (`*.fn`) on Kubernetes |

Browsers only ever talk to **web** (through the edge). The services sit on private addresses and trust web through shared secrets; the drive also receives the signed-in user's identity with each call, and decides what they may see.

## A request's path

1. The edge terminates TLS and forwards to web.
2. web's `guard` middleware (`main.py`) blocks state-changing `/api/` calls without the `X-Requested-With: scout` header or with a foreign `Origin`, then sets the security headers on the response: a strict Content-Security-Policy (no inline scripts, no `eval`), `nosniff`, `X-Frame-Options`, `no-referrer`, HSTS on HTTPS and `no-store` on the API.
3. The route's handler checks access itself: `require(req)` (signed in), `admin(req)` or `sudo(req)` (an admin who confirmed it's them in the last 10 minutes). Sessions are random 256-bit tokens; only their hash is stored.
4. Changes are written to the **audit log** with `db.log(action, actor, target, ip, detail)`.

## Background work

`main.py`'s start-up starts the long-running parts, each in its own thread:

| Part | Module | What it does |
|---|---|---|
| Collector | `collector.py` | Reads every subnet from the chain every `REFRESH_SECONDS`; backfills 7 days from an archive node once |
| Alerts and news | `alerts.py` | Turns each collection pass into alerts; fetches subnet news from GitHub |
| Slack | `slack.py` | Polls the channel once for everyone |
| Project team | `team.py` | Runs scheduled PDCA cycles |
| DevOps and system | `devops.py`, `system.py` | Pipeline runs and auto deploys; the server's resource history |
| Platform | `paas.py` | Keeps the edge certificate, DNS records and routes in step on Kubernetes |
| Tech Daily | `techboard.py` | Builds the day's edition after `TECH_DAILY_HOUR` |
| Technology Research analysis | `tech_analysis.py` | Writes the day's research brief after each edition; analyzes stories on request |

The collector's snapshot is shared in memory (`collector.state`); `/api/stream` tells open pages when a new one lands.

## Data

- **`auth.db`** (SQLite, `auth.AuthDB`) holds accounts, sessions, the audit log and settings, and every feature's own tables: each module creates its tables at start with `CREATE TABLE IF NOT EXISTS`. One connection is shared behind a lock; `db.q(sql, args, one=False)` runs a statement and returns rows as dicts.
- **`scout.db`** (`store.py`) holds the chain history behind the 7-day charts.
- **Secrets** saved in the app (API keys, tokens) go through `secretbox.SecretBox`: Fernet-encrypted under `DATA_DIR/secret.key` or `SECRET_KEY`, shown to browsers only masked.
- Curated subnet knowledge (hardware tiers, software, rent) is `backend/app/data/knowledge.json`, rebuilt with `tools/build_knowledge.py`.

## The front end

There's no build step and no framework. `frontend/index.html` loads plain scripts in order, and `app.js` comes last.

- Each page is a module: `const Tech = (() => { …; return { open }; })();`. It renders HTML strings into its section and wires events by delegation.
- `app.js`'s `setView(v)` shows the section `#view-<v>` and calls that module's `open()`. The address bar keeps `#<v>`, so pages can be linked.
- Shared helpers: `api()` (adds the CSRF header, shows progress, turns errors into messages), `esc()`, `icon()`, `$` and `$$`, `Loading`, `UI.toast()` and `UI.confirm()`.
- `styles.css` defines the design tokens (`--bg`, `--surface`, `--text`, `--accent`, `--good`, `--warn`, `--crit`…) for light and dark themes. A feature can bring its own stylesheet, as Tech Daily (`tech.css`) and Help (`help.css`) do.

## Agents

`agent_hub.py` hosts agents, chats, memory, skills and usage; `llm.py` speaks to every model provider and translates between their formats, with `structured()` for one-shot JSON answers. Built-in agents with tools are in `agents.py` (user administration), `ops_agents.py` (DevOps, Functions, Apps, Cluster, DNS) and `assistant.py` (the Assistant). Their changes are approval cards; `pages.py` describes every page so agents know where a message came from.
