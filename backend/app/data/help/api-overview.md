---
title: API overview
section: api
order: 1
icon: code
summary: Signing in from code, the CSRF header, sudo, errors, rate limits and the live update stream, with curl and Python examples.
---
AXoR's web app is built on its own REST API, so anything the app does you can do from a script. Requests and responses are JSON, served from the same address as the app (for example `https://axor.example.com/api/subnets`). The [API reference](#help/api-reference) lists every endpoint you may call, read from the running server.

## Signing in

AXoR has no API keys: a script signs in like the browser and keeps the **session cookie** (`scout_session`). A session lasts 24 hours without activity and 7 days at most.

1. `POST /api/auth/login` with `{"login": "<username or email>", "password": "…"}`.
2. The answer says what's next:
   - `{"stage": "done"}`: you're signed in.
   - `{"stage": "mfa"}`: send `POST /api/auth/mfa` with `{"code": "123456"}` from your authenticator app (or a recovery code).
   - an answer with a QR code: the account must set up two-factor first. Do that once in the browser.
3. Send the cookie with every later request. `GET /api/auth/me` tells you who you are.

### With curl

```bash
B=https://axor.example.com
curl -s -c cookies.txt -b cookies.txt -H 'X-Requested-With: scout' -H 'Content-Type: application/json' \
  -d '{"login": "alice", "password": "…"}' $B/api/auth/login
curl -s -c cookies.txt -b cookies.txt -H 'X-Requested-With: scout' -H 'Content-Type: application/json' \
  -d '{"code": "123456"}' $B/api/auth/mfa
curl -s -b cookies.txt $B/api/auth/me
```

### With Python

```python
import requests

B = "https://axor.example.com"
s = requests.Session()
s.headers["X-Requested-With"] = "scout"       # needed on every POST, PUT, PATCH and DELETE

r = s.post(f"{B}/api/auth/login", json={"login": "alice", "password": "…"}).json()
if r.get("stage") == "mfa":
    s.post(f"{B}/api/auth/mfa", json={"code": input("Authenticator code: ")}).raise_for_status()

subnets = s.get(f"{B}/api/subnets").json()
print(subnets["block"], len(subnets["subnets"]), "subnets")
```

> [!WARNING]
> Keep the cookie file private: it's as good as your password until the session ends. `POST /api/auth/logout` ends it.

## The CSRF header

Every `POST`, `PUT`, `PATCH` and `DELETE` under `/api/` must carry the header `X-Requested-With: scout`. If the request has an `Origin` header, it must match AXoR's own address. Otherwise AXoR answers `403` with "Cross-site request blocked." `GET` requests don't need it.

## Sudo for administrator changes

Administrators' changes (to users, the cluster, apps, DNS and so on) need a recent confirmation. Send `POST /api/admin/sudo` with `{"code": "123456"}` (or `{"password": "…"}` for an admin without two-factor); it lasts 10 minutes for this session. Without it, those endpoints answer `403` with the detail `SUDO_REQUIRED`. The reference marks them **Admin + sudo**.

## Errors

Errors are JSON with a message in `detail`, written to be shown to a person:

```json
{"detail": "Too many attempts. Try again in 42s."}
```

| Status | Meaning |
|---|---|
| `400` | The request doesn't make sense (a bad value, an invalid code) |
| `401` | Not signed in, or the session ended |
| `403` | Not allowed: administrators only, the CSRF header missing, or `SUDO_REQUIRED` |
| `404` | No such thing, or not yours |
| `409` | A conflict: something changed since you read it (a whiteboard saved by someone else answers with the current version) |
| `422` | The body doesn't match the schema; `detail` lists each field's problem |
| `423` | The account is locked after too many wrong passwords |
| `429` | Rate-limited; `detail` says when to try again |
| `502`, `503` | A service AXoR depends on (the chain, GitHub, Kubernetes, the drive) didn't answer or isn't set up |

## Rate limits

Sign-ins: 10 per IP every 5 minutes and 20 per account an hour. Authenticator codes: 10 per IP every 5 minutes. Registrations: 5 per IP an hour. Other endpoints aren't rate-limited, but please cache: subnet data only changes every few minutes.

## Live updates

`GET /api/stream` is a server-sent events stream. It sends an `update` event whenever a new chain snapshot lands, a comment line every 25 seconds or so to keep the connection open, and an `auth` event if your session ends.

```bash
curl -sN -b cookies.txt https://axor.example.com/api/stream
# event: update
# data: {"version": 12, "block": 5123456, "updated": 1793300000.1}
```

Read `GET /api/subnets` again after each `update`.

## Examples

```bash
# Rank subnets for a gaming GPU and $300 a month
curl -s -b cookies.txt -H 'X-Requested-With: scout' -H 'Content-Type: application/json' \
  -d '{"hardware": "gpu1", "budget_usd": 300, "risk": "medium", "count": 5}' $B/api/recommend

# Add subnet 19 to your workspace, then read its mining brief
curl -s -b cookies.txt -H 'X-Requested-With: scout' -H 'Content-Type: application/json' -d '{"netuid": 19}' $B/api/workspace/subnets
curl -s -b cookies.txt "$B/api/workspace/subnets/19/brief"

# Today's Tech Daily edition, or an earlier one
curl -s -b cookies.txt "$B/api/tech"
curl -s -b cookies.txt "$B/api/tech?day=2026-10-29"
```

## Conventions

- **Times** are Unix timestamps in seconds (UTC); days are `YYYY-MM-DD` strings.
- **Lists** that grow (notifications, news, push history) take `limit` and `before` for paging back.
- **Amounts** in τ are plain numbers; USD values are computed at the live TAO price.
- API responses are never cached (`Cache-Control: no-store`).
