# AXoR 5.1 stack: PostgreSQL + pgvector, Temporal, Redis, Prometheus/Tempo/Grafana (opt-in)

These manifests aren't part of `k8s/base`, so `deploy.sh` and `auto-update.sh` never apply them. `k8s/stack.sh` applies them:

| Step | Command | Production effect |
|---|---|---|
| 0 | `./k8s/redeploy.sh` (5.1) | none beyond a normal deploy: still SQLite, every switch off |
| 1 | `./k8s/stack.sh up` | Secret `axor-postgres`, NetworkPolicies (networkpolicy.yaml), StatefulSet `postgres` (pgvector 0.8.6, PG 16, 20 Gi), Deployment `temporal` (auto-setup 1.29.7), Deployment `redis` (7.4.1, no persistence) |
| 1b | `./k8s/stack.sh monitoring` (optional) | Secrets `axor-metrics`, `axor-grafana`; ConfigMaps from `monitoring/`; Prometheus v3.0.1, Tempo 2.6.1, Grafana 11.3.1 (not exposed: `port-forward svc/grafana 3000`) |
| 1c | `./k8s/stack.sh rehearse` (optional) | none: snapshots auth.db read-only, migrates it into a throwaway local Postgres, boots AXoR on it, reports, deletes it all |
| 2 | `./k8s/stack.sh migrate` | **stops web**, runs Job `axor-pg-migrate` (reads `/data/auth.db` read-only, copies it into Postgres, checks row counts) |
| 3 | `./k8s/stack.sh enable` | edits `.env` (backup kept as `.env.before-stack`): `DATABASE_URL`, `MISSIONS_RUNTIME=temporal`, `TEMPORAL_ADDRESS`, `AGENT_GRAPH=langgraph`, and when they're up `REDIS_URL`, `METRICS_TOKEN`, `OTEL_EXPORTER_OTLP_ENDPOINT` |
| 4 | `./k8s/redeploy.sh` | starts AXoR on Postgres + Temporal + LangGraph |

**All of it at once:** `./k8s/stack.sh switch` runs `up`, `monitoring`, `rehearse` (it stops there if the copy fails), `migrate` and `enable`,
then applies `.env` and restarts web on the new stack. No rebuild is needed, because the running 5.1 image has the code. It then checks that
the user count matches, the run count matches or has grown, AXoR reports Postgres, and the log has no database errors. If any check fails,
it restores `.env` and restarts web on SQLite by itself. Options: `--skip-rehearse`, `--no-monitoring`, `--dry-run`.

`--dry-run` prints what each step would do (`.env` values are never printed, only the stack's own keys, masked). `./k8s/stack.sh status` shows the pods and the settings in `.env`.

Every pod meets the `axor` namespace's restricted Pod Security policy (non-root, no capabilities, RuntimeDefault seccomp).
That was checked by running each image locally with the same user and capability settings. The namespace only lets web
reach its pods, so networkpolicy.yaml adds Temporal and the migration Job → Postgres, Prometheus → web:8000, and Grafana →
Prometheus/Tempo. Nothing here has been applied to this cluster yet.

## Testing without the cluster

    docker run -d --name pg -e POSTGRES_PASSWORD=test -e POSTGRES_DB=axor postgres:16-alpine
    # the unit suite on Postgres: every AuthDB(path) gets its own schema
    docker run --rm --link pg -v $PWD/tests/unit:/app/tests/unit:ro -v $PWD/backend/app:/app/backend/app:ro \
      -e DATA_DIR=/tmp/t -e DATABASE_URL=postgresql://postgres:test@pg:5432/axor -e DATABASE_SCHEMA_PER_PATH=1 \
      -w /app/backend --entrypoint python axor/web:TAG -m unittest discover -s /app/tests/unit -t /app/tests/unit

    # Temporal: a dev server, then the live tests (an image with temporalio + langgraph installed)
    docker run -d --name temporal temporalio/temporal:1.9.1 server start-dev --ip 0.0.0.0 --headless
    … -e TEMPORAL_TEST_ADDRESS=temporal:7233 … -p test_stack_runtime.py

## The React front end

Source in `frontend/react` (React 18.3.1, TypeScript 5.6, Vite 5.4). `npm ci && npm run build` writes `frontend/app`, which is
committed, so the image needs no Node. FastAPI serves it at `/app` (assets under `/static/app/`).
