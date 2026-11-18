---
title: The 5.1 stack: Postgres, Temporal, LangGraph, Redis, monitoring, React
section: admin
order: 8
audience: admin
icon: layers
summary: AXoR 5.1 adds the stack the 5.0 spec recommends. Each part is off until you switch it on, so AXoR keeps working while it moves. This page covers what each part does and how to switch over.
---
AXoR 5.1 adds the technology stack the AXoR 5.0 spec recommends: **PostgreSQL** for the database, **Temporal** for durable mission execution, **LangGraph** for stateful agent reasoning, and **React + TypeScript** for the front end. The backend stays Python + FastAPI. Every part is opt-in: with nothing switched on, AXoR 5.1 runs exactly like 5.0, on its SQLite file.

[Stack & migration](/app) (the first React page) shows what this server runs today and how far the migration has come.

## What each part does

- **PostgreSQL** (`DATABASE_URL=postgresql://…`). The whole app database moves: all ~270 tables of every page and agent system. AXoR's queries were written for SQLite, so a translation layer (`db_pg.py`) converts them as they run. Nothing else changes. The unit suite runs on both databases.
- **Temporal** (`MISSIONS_RUNTIME=temporal`). Mission Control hands each mission's stages to a Temporal workflow instead of its own worker pool. Temporal keeps the history, retries a stage that died with the server, and heartbeats long stages. If Temporal can't be reached, missions run in-process as before, so no mission is lost.
- **LangGraph** (`AGENT_GRAPH=langgraph`). Mission Control's direct engine ("AXoR directly") becomes a graph: draft → review against the acceptance criteria → revise, up to two revisions. Every step goes through the mission's budget, model routing and run ledger as before.
- **pgvector**. On Postgres, Knowledge search compares vectors inside the database (a generated `vector` column next to the stored bytes) instead of loading them into AXoR. It turns on by itself when the `vector` extension is available.
- **Redis** (`REDIS_URL`). Agent runs and mission events go to a Redis Stream (`axor:events`) that other services can read. Sign-in limits are shared between servers. If Redis is down, both fall back to the server's own memory, and limits never switch off.
- **Monitoring**. `/metrics` serves Prometheus metrics to a scraper holding `METRICS_TOKEN`. With `OTEL_EXPORTER_OTLP_ENDPOINT`, every request and agent run becomes an OpenTelemetry trace. `k8s/stack.sh monitoring` starts Prometheus, Tempo and Grafana with an AXoR dashboard.
- **React** (`/app`). Pages are moving to React and TypeScript: Stack & migration, Analytics and the new Activity feed are there now. Reach them from the version number at the bottom of the sidebar. The classic front end stays at `/` until every page has moved.

## Switching over (on the k3s host, as root)

On a server already running 5.1, `./k8s/stack.sh switch` does every step below in one go. It checks the result and switches back to SQLite by itself if a check fails. The separate steps:

1. Deploy 5.1 as usual: `./k8s/redeploy.sh`. It still runs on SQLite.
2. `./k8s/stack.sh up` starts Postgres 16 with pgvector, a Temporal server and Redis in the `axor` namespace. Optionally, `./k8s/stack.sh monitoring` starts Prometheus, Tempo and Grafana.
3. Optional: `./k8s/stack.sh rehearse` tries the migration on a copy first. It snapshots the database, migrates it into a throwaway local Postgres, starts AXoR on it, reports, and deletes everything. Production isn't touched.
4. `./k8s/stack.sh migrate` stops AXoR, copies `/data/auth.db` into Postgres and checks every table's row count. It only reads the SQLite file.
5. `./k8s/stack.sh enable` writes the settings to `.env`. Then run `./k8s/redeploy.sh` to start AXoR on the new stack.

To go back: `./k8s/stack.sh disable` and redeploy. Anything written on Postgres after the migration stays in Postgres and is not in the SQLite file.

## Known limits in 5.1

- One AXoR server per database: mission leases and the claim logic assume a single server.
- On Postgres, each statement commits on its own. The few multi-statement blocks keep their lock but aren't all-or-nothing.
- pgvector search scans one user's vectors exactly; there is no approximate (HNSW) index yet, because the dimension depends on the embedding model setting. Experience recall still compares its vectors in Python.
- The event stream is a recent-activity feed, not a record: Redis keeps about 10,000 events in memory, while AXoR's database keeps everything.
- Most pages are still on the classic front end.
