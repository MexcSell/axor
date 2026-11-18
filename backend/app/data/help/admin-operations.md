---
title: Configuration, deployment and backups
section: admin
order: 6
audience: admin
icon: server
summary: Environment variables, deploying on Kubernetes or Docker Compose, where data lives, backups, and troubleshooting.
---
## Configuration

AXoR is configured with environment variables: on Kubernetes from `.env` (loaded into the Secret `axor-env` by `k8s/deploy.sh`), with Docker Compose from `.env` next to `docker-compose.yml`. Settings changed in the app win over their starting values.

### Core

| Variable | Default | Meaning |
|---|---|---|
| `SUBTENSOR_NETWORK` | `finney` | Live node: `finney`, `test`, or a `ws://` / `wss://` endpoint (your own node avoids public rate limits) |
| `ARCHIVE_NETWORK` | `archive` | Archive node for the one-off 7-day backfill |
| `REFRESH_SECONDS` | `180` | Seconds between chain reads |
| `REQUIRE_LOGIN` | `1` | `0` serves the app without accounts |
| `SECRET_KEY` | generated | Fernet key for secrets saved in the app; by default `DATA_DIR/secret.key` |
| `COOKIE_SECURE` | auto | `1` behind an HTTPS proxy the app can't detect |
| `HIBP_CHECK` | `1` | Check new passwords against Have I Been Pwned (5 hash characters only) |

### Accounts

| Variable | Default | Meaning |
|---|---|---|
| `AUTH_METHOD` | `2fa` | Starting sign-in method: `basic` or `2fa` |
| `ALLOW_REGISTRATION` | `1` | Starting state of public registration |
| `ADMIN_EMAILS` | – | Existing accounts made administrators at start-up |
| `INIT_ADMIN_USERNAME`, `INIT_ADMIN_EMAIL`, `INIT_ADMIN_PASSWORD` | – | Create this admin at start-up if there's none |

### Agents and models

`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `LOCAL_LLM_URL` / `LOCAL_LLM_KEY` (all overridden by keys saved in the app), `AGENT_MODEL` (Claude's model on Auto, `claude-opus-5-5`), `CLAUDE_CODE_OAUTH_TOKEN`, `CLAUDE_CLI`, `CLAUDE_CLI_ENABLED` and `CLAUDE_CLI_TIMEOUT` (300 seconds per Terminal turn).

### News and Tech Daily

| Variable | Default | Meaning |
|---|---|---|
| `GITHUB_TOKEN` | – | Optional token for subnet news and Tech Daily's GitHub search (without it, GitHub's public rate limit applies) |
| `NEWS_REFRESH_HOURS` | `6` | How often subnet news is fetched; `0` turns it off |
| `TECH_DAILY` | `1` | `0` turns Tech Daily's builder off (editions already made stay readable) |
| `TECH_DAILY_HOUR` | `6` | The UTC hour after which each day's edition is built |
| `TECH_MODEL` | `auto` | The model that writes the copy: `auto` (the agents' default), a model id like `anthropic:claude-haiku-5-5`, or `off` |
| `TECH_KEEP_DAYS` | `60` | Days of editions kept |
| `TECH_ANALYZE_DAILY` | `150` | New story analyses the server writes per UTC day (cached ones are free) |
| `TECH_ANALYZE_PER_USER` | `30` | New story analyses one user can ask for per UTC day (admins aren't held to it) |
| `HQ` | `1` | `0` turns [Agent HQ](#help/admin-hq) off |
| `HQ_PATROL_MINUTES` | `10` | How often Agent HQ's field agents check (at least 5) |
| `MINING` | `1` | `0` turns [My subnets](#help/mining) off (no snapshots, alerts or cycles) |

### Services

`DRIVE_URL`, `DRIVE_SECRET` / `DRIVE_SECRET_FILE`, `PUSH_URL`, `PUSH_SECRET` / `PUSH_SECRET_FILE`, `RUNNER_URL`, `RUNNER_SECRET` / `RUNNER_SECRET_FILE` and `DOCKER_URL` connect AXoR to its services; `deploy.sh` and `docker-compose.yml` set them. The Slack, Source, Drive and push variables are covered in [Slack, Source hub, Drive and push](#help/admin-integrations).

## Deploying

### Kubernetes (k3s)

```bash
sudo ./k8s/install-k3s.sh      # once: k3s without its bundled Traefik and ServiceLB, Secrets encrypted at rest
sudo ./k8s/deploy.sh           # build the images, load them into k3s and roll out; again after every change
sudo ./k8s/deploy.sh --host    # also the DevOps runner and the Docker page's proxy
```

`deploy.sh` makes the shared secrets once and keeps them, and never opens a host port. `k8s/cutover.sh` moved a Docker Compose install onto k3s: it copied the volumes, mapped port 443 to the edge, 53 to AXoR DNS and 8000 to a redirect to HTTPS. `./k8s/cutover.sh --rollback` closes those ports, stops AXoR on k3s and starts the Compose containers again on their untouched volumes.

> [!WARNING]
> `deploy.sh` rebuilds and restarts the live services. Run it when a short restart is acceptable.

### Docker Compose

```bash
docker compose up -d --build      # open http://localhost:8000
```

The first chain snapshot appears after 10 to 20 seconds; the 7-day backfill runs in the background. Use HTTPS in production: without it, passwords and session cookies cross the network unencrypted.

## Where data lives

| Data | Where | Back it up? |
|---|---|---|
| Accounts, sessions, the audit log, settings and most feature data (workspace, agents, study, boards, Tech Daily…) | `auth.db` in `DATA_DIR` | Yes |
| Chain history (7-day series) | `scout.db` in `DATA_DIR` | Optional: it refills from the chain |
| The key that encrypts saved secrets | `secret.key` in `DATA_DIR` | Yes, with `auth.db`: without it, saved keys and tokens can't be read |
| Drive files and their database | the drive's volume | Yes |
| Push subscriptions and the VAPID keys | the push server's volume | Yes: new keys end every subscription |

On Kubernetes, `DATA_DIR` is `/data` in the `web` deployment, on the volume `web-data`; the drive and push server use `drive-data` and `push-data`, all in namespace `axor` on k3s's local-path storage (by default under `/var/lib/rancher/k3s/storage`). With Docker Compose they're the `subnet-scout-data`, `scout-drive-data` and `scout-push-data` volumes.

### Backing up the databases

SQLite's backup API copies a database safely while AXoR runs:

```bash
kubectl -n axor exec deploy/web -- python -c "import sqlite3; s = sqlite3.connect('/data/auth.db'); s.backup(sqlite3.connect('/data/auth-backup.db'))"
kubectl -n axor cp "$(kubectl -n axor get pod -l app=web -o name | head -1 | cut -d/ -f2)":/data/auth-backup.db ./auth-backup.db
kubectl -n axor cp "$(kubectl -n axor get pod -l app=web -o name | head -1 | cut -d/ -f2)":/data/secret.key ./secret.key
```

Keep backups private: `auth.db` holds password hashes and encrypted secrets, and `secret.key` decrypts them.

## Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| "Collecting first snapshot…" for minutes | The chain node is unreachable or rate-limited | Check `SUBTENSOR_NETWORK`; your own node avoids public limits. `GET /api/health` shows the collector's status. |
| Agents say no model is available | No provider connected | Connect one in **Agents → Models** |
| Drive says it isn't connected | `DRIVE_URL` or the shared secret is missing | Set them, or redeploy with `deploy.sh` |
| Push can't be turned on | The page isn't served over HTTPS | Serve AXoR over HTTPS (the edge does on Kubernetes) |
| Tech Daily is empty | The first edition is still being built, or the server can't reach the internet | Wait a minute and reload; an administrator sees the last error on the page |
| A user is locked out | Five wrong passwords | **Unlock** them in Administration, or wait 15 minutes |
| A user lost their phone and recovery codes | – | **Reset two-factor** for them |
