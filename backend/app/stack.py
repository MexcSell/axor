"""AXoR 5.1: where this server stands on the spec's stack (React · FastAPI · LangGraph · Temporal · PostgreSQL) and the migration.

GET /api/stack       what runs here: database engine, mission runtime, agent graph, front end, and the migration steps
GET /app, /app/...   the React + TypeScript front end (frontend/app, built from frontend/react by `npm run build`); the
                     classic front end stays at / while pages move over one by one
"""
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from . import agent_graph, bus, db_pg, metrics, mission_temporal

SPEC = [  # the spec's recommended stack (AXoR 5.0 "Self-Evolving Agent Ecosystem", section 8) and where 5.1 stands
    ("frontend", "React + TypeScript", "Stack & migration page in React at /app; the other pages are still the classic front end"),
    ("backend", "Python + FastAPI", "unchanged"),
    ("agent_workflows", "LangGraph", "Mission Control's direct engine as a draft → review → revise graph (AGENT_GRAPH=langgraph)"),
    ("orchestration", "Temporal", "Mission Control's stages as Temporal workflows (MISSIONS_RUNTIME=temporal)"),
    ("database", "PostgreSQL", "the whole app database through db_pg.py (DATABASE_URL), migration with app.pg_migrate"),
    ("vectors", "pgvector", "Knowledge search computes similarity in Postgres (vector_pg.py; on with Postgres + the extension)"),
    ("cache_queues", "Redis / Redis Streams", "the event stream (agent runs, mission events) and shared sign-in limits (REDIS_URL)"),
    ("monitoring", "OpenTelemetry + Prometheus + Grafana", "/metrics (METRICS_TOKEN), OTLP traces (OTEL_EXPORTER_OTLP_ENDPOINT), Grafana dashboard"),
]


def state(admin=False, db=None):
    conn, db = db, db_pg.describe()
    if not admin: db = {"engine": db["engine"]}
    t = mission_temporal.status()
    if not admin: t = {k: t.get(k) for k in ("enabled", "installed", "ready", "submitted", "fallbacks")}
    g = agent_graph.status()
    b, mon = bus.status(), metrics.status()
    if not admin: b = {k: b.get(k) for k in ("enabled", "installed", "ready")}
    pgv = False
    if conn is not None and db_pg.enabled():
        from . import vector_pg
        pgv = vector_pg.ready(conn)
    react = (Path(os.getenv("FRONTEND_DIR", Path(__file__).resolve().parents[2] / "frontend")) / "app" / "index.html").exists()
    live = {"frontend": react, "backend": True, "agent_workflows": g["enabled"] and g["installed"], "orchestration": bool(t.get("ready")),
            "database": db["engine"] == "postgres", "vectors": pgv, "cache_queues": b["ready"], "monitoring": mon["prometheus"] or mon["tracing"]}
    steps = [
        {"key": "code", "title": "Postgres-ready code", "done": True, "detail": "db_pg.py translates AXoR's SQLite SQL; the unit suite runs on both"},
        {"key": "infra", "title": "Postgres + Temporal running", "done": db["engine"] == "postgres" or bool(t.get("ready")),
         "detail": "k8s/stack.sh up (k8s/stack/*.yaml): pgvector Postgres 16 and a Temporal server in the axor namespace"},
        {"key": "data", "title": "Data copied", "done": db["engine"] == "postgres",
         "detail": "k8s/stack.sh migrate (after 5.1 is deployed): python -m app.pg_migrate copies auth.db and checks every table's row count"},
        {"key": "switch", "title": "Switched over", "done": db["engine"] == "postgres",
         "detail": "k8s/stack.sh enable writes DATABASE_URL, MISSIONS_RUNTIME=temporal and AGENT_GRAPH=langgraph to .env; ./k8s/redeploy.sh starts AXoR on them"},
        {"key": "ops", "title": "Redis + monitoring", "done": bool(b.get("ready")) and bool(mon["prometheus"]),
         "detail": "k8s/stack.sh up also starts Redis; k8s/stack.sh monitoring starts Prometheus, Tempo and Grafana; enable sets REDIS_URL, METRICS_TOKEN, OTEL_EXPORTER_OTLP_ENDPOINT"},
        {"key": "ui", "title": "Pages on React", "done": False, "detail": "page by page under /app; the classic front end stays until the last one moves"},
    ]
    return {"version": "5.1.0", "stack": [{"key": k, "spec": s, "now": n, "live": live.get(k, False)} for k, s, n in SPEC],
            "database": db, "missions_runtime": t, "agent_graph": g, "events": b, "monitoring": mon, "react": react, "migration": steps}


def build(require_user, frontend, auth_db=None):
    r = APIRouter()
    app_dir = Path(frontend) / "app"

    @r.get("/api/stack")
    def stack(req: Request):
        me = require_user(req)
        return state(admin=(me or {}).get("role") == "admin", db=auth_db)

    @r.get("/api/events")
    def events(req: Request, limit: int = 100, kind: str = ""):
        """The newest events of the stream (bus.py): agent runs and mission events. Admins only: they span every user."""
        me = require_user(req)
        if (me or {}).get("role") != "admin": raise HTTPException(403, "Admins only.")
        return {"source": "redis" if bus.status()["ready"] else "in-process", "events": bus.recent(limit, set(kind.split(",")) if kind else None)}

    @r.get("/app")
    @r.get("/app/{rest:path}")
    def react_app(rest: str = ""):
        f = app_dir / "index.html"
        if not f.exists(): raise HTTPException(404, "The React front end isn't built: cd frontend/react && npm ci && npm run build")
        return FileResponse(f)

    return r
