---
title: Run AXoR locally
section: dev
order: 2
icon: terminal
summary: A development server with test accounts and offline fakes, and testing pages in a real browser.
---
## Requirements

Python 3.12 and the packages in `backend/requirements.txt` (and `drive/requirements.txt` for the drive). Nothing to build for the front end.

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r backend/requirements.txt -r drive/requirements.txt
```

## A development server

Run it on a spare port with its own data folder, so it never touches a real install:

```bash
export DATA_DIR=$PWD/var-dev
export REQUIRE_LOGIN=1 AUTH_METHOD=basic HIBP_CHECK=0
export INIT_ADMIN_USERNAME=admin INIT_ADMIN_PASSWORD='a-long-dev-password-123'
export SUBTENSOR_NETWORK=ws://127.0.0.1:9    # fails fast: no chain load while you work on other pages
export NEWS_REFRESH_HOURS=0 TECH_DAILY=0     # no background fetching
python -m uvicorn app.main:app --app-dir backend --port 8812
```

Open `http://127.0.0.1:8812`. The start-up admin must change its password at first sign-in. Leave `SUBTENSOR_NETWORK` unset to read the real chain (`finney`); the first snapshot takes 10 to 20 seconds.

> [!TIP]
> Start the server with `… & echo $! > dev.pid` and stop it with `kill $(cat dev.pid)`. Never stop servers by pattern (`pkill -f uvicorn`): it also hits any real AXoR running on the same machine.

## With the drive

```bash
export DRIVE_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
(cd drive && DRIVE_DATA=./var exec uvicorn drive:app --port 8811) &
DRIVE_URL=http://127.0.0.1:8811 python -m uvicorn app.main:app --app-dir backend --port 8812
```

## Offline fakes

`tests/` holds stand-ins for every outside service, so you can work without keys or a network:

| Fake | Stands in for | Use it with |
|---|---|---|
| `fake_claude.py` | The Claude API, with scripted answers for agents, practice, the board, the profile review and Tech Daily | `AGENT_CLIENT_FACTORY=fake_claude:factory PYTHONPATH=tests ANTHROPIC_API_KEY=x` |
| `fake_anthropic_api.py`, `fake_openai_api.py`, `fake_openrouter_api.py` | Key verification and model lists | `ANTHROPIC_BASE_URL`, `OPENAI_BASE_URL`, `OPENROUTER_BASE_URL` |
| `fake_github_api.py` | GitHub's REST API for the Source hub | `SOURCE_GITHUB_API_URL` |
| `fake_slack_api.py` | Slack's Web API | `SLACK_API_URL` |
| `fake_netlify_api.py` | Netlify, serving deploys at `/live/<name>/` | `NETLIFY_API_URL` |
| `fake_push_service.py` | A browser push service | `PUSH_HOSTS=http://127.0.0.1:8832` |
| `fake_subtensor.py` | The Bittensor chain for Wallets | `WALLET_CHAIN_FACTORY=fake_subtensor:factory` |

When your feature calls a model, add a branch to `fake_claude.py` keyed on your system prompt's first words, as Tech Daily's `_tech()` does, so it answers with data your code can use.

## Testing in a browser

Playwright drives a real Chromium against your dev server. Things that look like failures but aren't:

- **Rate limits:** sign-ins are limited per IP and per account. Sign in once, save Playwright's `storage_state`, and reuse it. Restarting the server clears the limits.
- **The CSP blocks `eval`:** pass functions to `wait_for_function` (`"() => typeof S !== 'undefined' && S.view"`), not expressions.
- **Switching pages:** setting `location.hash` from another page doesn't switch views; click the sidebar button (`[data-view="tech"]`) instead. At phone width the sidebar is collapsed, so `goto(base + "/#tech")`.
- **Push:** the headless shell always reports notifications as denied; launch the full Chromium (`channel="chromium"`) with a persistent context.

## Kubernetes pieces

Pages that talk to Kubernetes (Cluster, Apps, Functions, Machines, DNS) read `KUBE_API`, `KUBE_TOKEN_FILE` and `KUBE_CA_FILE` outside the cluster. Point them at a test cluster, or at a small fake HTTP API, rather than the production cluster's: the platform sync writes the edge certificate.
