"""Monitoring (5.1: the spec's "OpenTelemetry + Prometheus + Grafana").

- Prometheus: GET /metrics in the text exposition format, for a scraper holding METRICS_TOKEN (Authorization: Bearer …);
  without METRICS_TOKEN the endpoint answers 404. Request counts and latency by route template (never by raw path: no
  ids in labels), agent runs started/finished (from the event stream, bus.py), model calls in flight, missions by status,
  and what the stack runs (database, mission runtime, Redis).
- OpenTelemetry: with OTEL_EXPORTER_OTLP_ENDPOINT (e.g. http://tempo:4318) and the opentelemetry packages, a span per HTTP
  request (continuing an incoming traceparent) and a span per agent run, exported over OTLP/HTTP as service "axor"
  (OTEL_SERVICE_NAME overrides). Without either, nothing is traced.
- Grafana: k8s/stack/monitoring.yaml provisions Prometheus, Tempo and Grafana with an AXoR dashboard over both.
"""
import hmac, logging, os, threading, time

from fastapi import HTTPException, Request
from fastapi.responses import PlainTextResponse

from . import bus

log = logging.getLogger("metrics")
TOKEN = os.getenv("METRICS_TOKEN", "").strip()
OTLP = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30)

_lock = threading.Lock()
_req = {}        # (method, route, status) -> count
_lat = {}        # route -> [bucket counts..., +Inf count, sum]
_runs = {}       # ("started", system) / ("finished", status) -> count
_tracer = None
_spans = {}      # run id -> (span, started)


def _route(request):
    r = request.scope.get("route")
    return getattr(r, "path", None) or "unmatched"


def observe(method, route, status, seconds):
    with _lock:
        k = (method, route, str(status))
        _req[k] = _req.get(k, 0) + 1
        h = _lat.setdefault(route, [0] * (len(BUCKETS) + 2))
        for i, b in enumerate(BUCKETS):
            if seconds <= b: h[i] += 1
        h[len(BUCKETS)] += 1
        h[-1] += seconds


def _on_event(ev):
    kind = ev.get("kind")
    if kind == "run.started":
        with _lock: _runs[("started", ev.get("system") or "?")] = _runs.get(("started", ev.get("system") or "?"), 0) + 1
        if _tracer is not None:
            sp = _tracer.start_span("agent.run", attributes={k: str(v) for k, v in (("axor.system", ev.get("system")), ("axor.agent", ev.get("agent")),
                                    ("axor.ref", ev.get("ref")), ("axor.model", ev.get("model")), ("axor.run", ev.get("run"))) if v is not None})
            with _lock:
                _spans[ev.get("run")] = (sp, time.time())
                if len(_spans) > 5000:  # runs that never finish (a crash): drop the oldest
                    for k in sorted(_spans, key=lambda r: _spans[r][1])[:1000]: _spans.pop(k)[0].end()
    elif kind == "run.finished":
        with _lock: _runs[("finished", ev.get("status") or "?")] = _runs.get(("finished", ev.get("status") or "?"), 0) + 1
        with _lock: item = _spans.pop(ev.get("run"), None)
        if item:
            sp = item[0]
            if ev.get("tokens") is not None: sp.set_attribute("axor.tokens", int(ev["tokens"] or 0))
            sp.set_attribute("axor.status", str(ev.get("status")))
            if ev.get("status") not in ("done", None):
                from opentelemetry.trace import Status, StatusCode
                sp.set_status(Status(StatusCode.ERROR, str(ev.get("error") or ev.get("status"))))
            sp.end()


def _otel():
    global _tracer
    if not OTLP: return None
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        log.warning("OTEL_EXPORTER_OTLP_ENDPOINT is set but the opentelemetry packages aren't installed: no traces")
        return None
    prov = TracerProvider(resource=Resource.create({"service.name": os.getenv("OTEL_SERVICE_NAME", "axor")}))
    prov.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=OTLP.rstrip("/") + "/v1/traces")))
    trace.set_tracer_provider(prov)
    _tracer = trace.get_tracer("axor")
    log.info("opentelemetry: traces to %s", OTLP)
    return _tracer


def render(db=None):
    """The Prometheus text exposition."""
    from . import busy, db_pg, mission_temporal
    out = []
    def metric(name, typ, help_, rows):
        out.append(f"# HELP {name} {help_}"); out.append(f"# TYPE {name} {typ}")
        for labels, v in rows:
            lab = ",".join(f'{k}="{str(x).replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"' for k, x in labels.items())
            out.append(f"{name}{{{lab}}} {v}" if lab else f"{name} {v}")
    with _lock:
        req, lat, runs = dict(_req), {k: list(v) for k, v in _lat.items()}, dict(_runs)
    metric("axor_http_requests_total", "counter", "HTTP requests by route template and status.",
           [({"method": m, "route": r, "status": s}, n) for (m, r, s), n in sorted(req.items())])
    out.append("# HELP axor_http_request_seconds HTTP request duration by route template.")
    out.append("# TYPE axor_http_request_seconds histogram")
    for r, h in sorted(lat.items()):
        for i, b in enumerate(BUCKETS): out.append(f'axor_http_request_seconds_bucket{{route="{r}",le="{b}"}} {h[i]}')
        out.append(f'axor_http_request_seconds_bucket{{route="{r}",le="+Inf"}} {h[len(BUCKETS)]}')
        out.append(f'axor_http_request_seconds_sum{{route="{r}"}} {h[-1]:.6f}')
        out.append(f'axor_http_request_seconds_count{{route="{r}"}} {h[len(BUCKETS)]}')
    metric("axor_agent_runs_started_total", "counter", "Agent runs started (the agent core's ledger) by system.",
           [({"system": s}, n) for (k, s), n in sorted(runs.items()) if k == "started"])
    metric("axor_agent_runs_finished_total", "counter", "Agent runs finished by status.",
           [({"status": s}, n) for (k, s), n in sorted(runs.items()) if k == "finished"])
    metric("axor_busy", "gauge", "Agent loops and model calls in flight.", [({}, busy.count())])
    if db is not None:
        try:
            rows = db.q("SELECT status, COUNT(*) n FROM mx_missions GROUP BY status")
            metric("axor_missions", "gauge", "Missions by status.", [({"status": r["status"]}, r["n"]) for r in rows])
            r = db.q("SELECT COUNT(*) n FROM ac_runs WHERE status='running'", one=True)
            metric("axor_agent_runs_running", "gauge", "Agent runs open in the ledger.", [({}, r["n"] if r else 0)])
        except Exception as e:  # noqa: BLE001 - a table that isn't there yet
            log.debug("metrics db: %s", e)
    t, b = mission_temporal.status(), bus.status()
    metric("axor_stack_info", "gauge", "What this server runs (always 1).",
           [({"database": db_pg.describe()["engine"], "missions_runtime": "temporal" if t.get("ready") else "in-process",
              "events": "redis" if b["ready"] else "in-process", "tracing": "otlp" if _tracer is not None else "off"}, 1)])
    metric("axor_temporal_ready", "gauge", "1 when Mission Control hands missions to Temporal.", [({}, int(bool(t.get("ready"))))])
    metric("axor_redis_ready", "gauge", "1 when the event stream and shared limits use Redis.", [({}, int(b["ready"]))])
    metric("axor_events_in_process_total", "counter", "Events kept in this process because Redis was off or down.", [({}, b["in_process"])])
    return "\n".join(out) + "\n"


def install(app, db=None):
    """The /metrics route, the request middleware and the run observer; tracing when configured."""
    bus.subscribe(_on_event)
    _otel()

    @app.middleware("http")
    async def _measure(request: Request, call_next):
        t0 = time.perf_counter()
        span, token = None, None
        if _tracer is not None:
            from opentelemetry import context, propagate, trace
            ctx = propagate.extract(dict(request.headers))
            span = _tracer.start_span(f"{request.method}", context=ctx, kind=trace.SpanKind.SERVER,
                                      attributes={"http.method": request.method, "url.path": request.url.path})
            token = context.attach(trace.set_span_in_context(span, ctx))
        status = 500
        try:
            resp = await call_next(request)
            status = resp.status_code
            return resp
        finally:
            route = _route(request)
            if route != "/metrics": observe(request.method, route, status, time.perf_counter() - t0)
            if span is not None:
                from opentelemetry import context
                span.update_name(f"{request.method} {route}")
                span.set_attribute("http.route", route); span.set_attribute("http.status_code", status)
                span.end(); context.detach(token)

    @app.get("/metrics", include_in_schema=False)
    def prometheus(request: Request):
        if not TOKEN: raise HTTPException(404, "Not Found")
        got = request.headers.get("authorization", "")
        if not hmac.compare_digest(got.encode(), f"Bearer {TOKEN}".encode()): raise HTTPException(401, "Bearer token required.")
        return PlainTextResponse(render(db), media_type="text/plain; version=0.0.4")


def status():
    return {"prometheus": bool(TOKEN), "tracing": _tracer is not None, "otlp": OTLP or None}
