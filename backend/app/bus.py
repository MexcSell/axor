"""Events and shared counters (5.1: the spec's "Cache and queues: Redis" and "Event infrastructure: Redis Streams initially").

REDIS_URL=redis://host:6379/0 (k8s/stack/redis.yaml) turns it on; unset, everything here runs in-process as before.

- Event stream: publish(kind, **fields) appends to the Redis Stream axor:events (XADD, trimmed to about STREAM_MAX entries);
  recent() reads it back newest first. AXoR publishes every agent run that starts and finishes (agent_core) and every mission
  event (missions._event), so other services can follow AXoR's work without polling its database. Without Redis the same
  events go to a ring buffer of RING_MAX in this process. publish() never raises and never blocks the caller for long: a
  Redis that is down costs one short timeout, then a backoff during which events go to the ring buffer.
- Shared rate limits: hit(key, limit, window) counts in a Redis sorted set, so several AXoR servers share one sign-in limit
  (auth.RateLimiter). Redis errors fall back to the in-process limiter: limits never switch off.

redis (redis-py) is in requirements.txt from 5.1; without it REDIS_URL is reported as "not installed" and nothing changes.
"""
import collections, json, logging, os, threading, time, uuid

log = logging.getLogger("bus")

URL = os.getenv("REDIS_URL", "").strip()
STREAM = os.getenv("REDIS_STREAM", "axor:events")
STREAM_MAX, RING_MAX = 10000, 2000
TIMEOUT, BACKOFF = 0.5, 30

_ring = collections.deque(maxlen=RING_MAX)
_lock = threading.Lock()
_state = {"client": None, "down_until": 0.0, "error": None, "published": 0, "fallback": 0}


def installed():
    try:
        import redis  # noqa: F401
        return True
    except ImportError:
        return False


def _client():
    """The Redis client, or None (not configured, not installed, or backing off after an error)."""
    if not URL or time.time() < _state["down_until"]: return None
    c = _state["client"]
    if c is None:
        try:
            import redis
            c = redis.Redis.from_url(URL, socket_timeout=TIMEOUT, socket_connect_timeout=TIMEOUT, decode_responses=True)
            _state["client"] = c
        except Exception as e:  # noqa: BLE001
            _down(e); return None
    return c


def _down(e):
    _state["error"], _state["down_until"] = f"{type(e).__name__}: {e}", time.time() + BACKOFF
    log.warning("redis unavailable (%s): in-process for %ss", e, BACKOFF)


_subs = []


def subscribe(fn):
    """fn(event) for every event published in this process (metrics.py counts runs and traces them)."""
    if fn not in _subs: _subs.append(fn)


def publish(kind, **fields):
    """Append an event {kind, ts, …fields}. Never raises."""
    ev = {"kind": kind, "ts": round(time.time(), 3), **{k: v for k, v in fields.items() if v is not None}}
    for fn in list(_subs):
        try: fn(ev)
        except Exception as e:  # noqa: BLE001 - an observer never stops the event
            log.debug("bus subscriber: %s", e)
    c = _client()
    if c is not None:
        try:
            c.xadd(STREAM, {"e": json.dumps(ev, default=str)}, maxlen=STREAM_MAX, approximate=True)
            _state["published"] += 1
            return
        except Exception as e:  # noqa: BLE001
            _down(e)
    with _lock:
        _ring.append(ev)
        _state["fallback"] += 1


def recent(limit=100, kinds=None):
    """The newest events first (Redis when on, else this process's ring buffer)."""
    limit = max(1, min(int(limit), 1000))
    c = _client()
    if c is not None:
        try:
            out = []
            for _id, f in c.xrevrange(STREAM, count=limit * (4 if kinds else 1)):
                ev = json.loads(f.get("e") or "{}")
                ev["id"] = _id
                if not kinds or ev.get("kind") in kinds: out.append(ev)
                if len(out) >= limit: break
            return out
        except Exception as e:  # noqa: BLE001
            _down(e)
    with _lock: evs = list(_ring)
    evs.reverse()
    return [e for e in evs if not kinds or e.get("kind") in kinds][:limit]


def hit(key, limit, window):
    """(allowed, seconds until the oldest hit expires) for one more hit on `key`; None when Redis isn't there (use local)."""
    c = _client()
    if c is None: return None
    now = time.time()
    k = f"axor:rl:{key}"
    try:
        p = c.pipeline()
        p.zremrangebyscore(k, 0, now - window)
        p.zcard(k)
        p.zrange(k, 0, 0, withscores=True)
        _, n, first = p.execute()
        if n >= limit:
            oldest = first[0][1] if first else now
            return False, int(oldest + window - now) + 1
        p = c.pipeline()
        p.zadd(k, {f"{now}:{uuid.uuid4().hex[:8]}": now})
        p.expire(k, int(window) + 1)
        p.execute()
        return True, 0
    except Exception as e:  # noqa: BLE001
        _down(e)
        return None


def status():
    c = _client() if URL else None
    ok = False
    if c is not None:
        try: ok = bool(c.ping())
        except Exception as e:  # noqa: BLE001
            _down(e)
    return {"enabled": bool(URL), "installed": installed(), "ready": ok, "stream": STREAM if URL else None,
            "published": _state["published"], "in_process": _state["fallback"], "error": _state["error"] if URL else None}
