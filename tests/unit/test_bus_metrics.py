"""5.1 Redis + monitoring: the event stream and shared limits (bus.py), Prometheus /metrics and OpenTelemetry spans (metrics.py).

In-process by default; the live Redis tests need REDIS_TEST_URL (and redis-py), the tracing test the opentelemetry SDK."""
import importlib, os, time, unittest
from unittest import mock

from fastapi import HTTPException

from app import auth, bus, metrics


class InProcess(unittest.TestCase):
    def test_events_go_to_the_ring_and_subscribers(self):
        seen = []
        bus.subscribe(seen.append)
        try:
            bus.publish("run.started", run=1, system="missions", model=None)
            bus.publish("mission.event", mission=3, stage="plan", text="x")
        finally:
            bus._subs.remove(seen.append)
        self.assertEqual([e["kind"] for e in seen], ["run.started", "mission.event"])
        self.assertNotIn("model", seen[0])  # None fields are left out
        last = bus.recent(2)
        self.assertEqual(last[0]["kind"], "mission.event")
        self.assertEqual(bus.recent(5, {"run.started"})[0]["run"], 1)
        self.assertIsNone(bus.hit("x", 1, 60))  # no Redis: the caller's own limiter decides

    def test_local_limiter_still_limits(self):
        rl = auth.RateLimiter()
        for _ in range(3): rl.check(("t", "1.2.3.4"), 3, 60)
        with self.assertRaises(HTTPException) as e: rl.check(("t", "1.2.3.4"), 3, 60)
        self.assertEqual(e.exception.status_code, 429)

    def test_prometheus_text(self):
        metrics.observe("GET", "/api/x/{id}", 200, 0.03)
        metrics._on_event({"kind": "run.started", "system": "workforce", "run": 7})
        metrics._on_event({"kind": "run.finished", "status": "done", "run": 7})
        t = metrics.render()
        self.assertIn('axor_http_requests_total{method="GET",route="/api/x/{id}",status="200"} 1', t)
        self.assertIn('axor_http_request_seconds_bucket{route="/api/x/{id}",le="0.05"} 1', t)
        self.assertIn('axor_agent_runs_started_total{system="workforce"}', t)
        self.assertIn('axor_agent_runs_finished_total{status="done"}', t)
        self.assertIn("# TYPE axor_busy gauge", t)
        self.assertIn('axor_stack_info{database="', t)

    def test_redis_down_falls_back(self):
        with mock.patch.multiple(bus, URL="redis://127.0.0.1:1/0"), mock.patch.dict(bus._state, {"client": None, "down_until": 0}):
            if not bus.installed(): self.skipTest("redis-py isn't installed")
            n = bus._state["fallback"]
            bus.publish("x.y", a=1)
            self.assertEqual(bus._state["fallback"], n + 1)
            self.assertIsNone(bus.hit("k", 1, 60))  # backing off: local limiter
            self.assertFalse(bus.status()["ready"])


@unittest.skipUnless(bus.installed() and os.getenv("REDIS_TEST_URL"), "needs redis-py and REDIS_TEST_URL")
class LiveRedis(unittest.TestCase):
    def setUp(self):
        self.p = mock.patch.multiple(bus, URL=os.environ["REDIS_TEST_URL"], STREAM=f"axor:test:{time.time_ns()}")
        self.p.start()
        bus._state.update(client=None, down_until=0, error=None)

    def tearDown(self):
        c = bus._client()
        if c: c.delete(bus.STREAM)
        self.p.stop()
        bus._state.update(client=None, down_until=0)

    def test_stream_round_trip(self):
        for i in range(5): bus.publish("run.finished", run=i, status="done")
        bus.publish("mission.event", mission=9, text="hello")
        got = bus.recent(3)
        self.assertEqual(got[0]["kind"], "mission.event")
        self.assertTrue(got[0]["id"])
        self.assertEqual([e["run"] for e in bus.recent(10, {"run.finished"})], [4, 3, 2, 1, 0])
        self.assertTrue(bus.status()["ready"])

    def test_limits_are_shared_between_servers(self):
        a, b = auth.RateLimiter(), auth.RateLimiter()  # two servers' limiters, one Redis
        key = ("login", f"10.0.0.{time.time_ns() % 250}")
        a.check(key, 2, 60); b.check(key, 2, 60)
        with self.assertRaises(HTTPException) as e: a.check(key, 2, 60)
        self.assertEqual(e.exception.status_code, 429)
        self.assertEqual(a.hits, {})  # counted in Redis, not in the process


class Tracing(unittest.TestCase):
    def test_agent_runs_become_spans(self):
        try:
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import SimpleSpanProcessor
            from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
        except ImportError:
            self.skipTest("opentelemetry SDK isn't installed")
        exp = InMemorySpanExporter()
        prov = TracerProvider(); prov.add_span_processor(SimpleSpanProcessor(exp))
        with mock.patch.object(metrics, "_tracer", prov.get_tracer("t")):
            metrics._on_event({"kind": "run.started", "run": 41, "system": "missions", "model": "m"})
            metrics._on_event({"kind": "run.finished", "run": 41, "status": "failed", "tokens": 120, "error": "boom"})
        (sp,) = exp.get_finished_spans()
        self.assertEqual(sp.name, "agent.run")
        self.assertEqual(sp.attributes["axor.system"], "missions")
        self.assertEqual(sp.attributes["axor.tokens"], 120)
        self.assertEqual(sp.status.status_code.name, "ERROR")


if __name__ == "__main__":
    unittest.main()
