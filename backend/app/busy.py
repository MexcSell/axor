"""Agent work in flight in this process: tool loops and model calls that a restart would cut off.

/api/health reports the count as `busy`, and a deploy waits for it to reach 0 before it swaps the web pod
(k8s/redeploy.sh refuses while it isn't, the auto-updater waits for it up to a limit), the way AgentForge's supervisor waits
until no agent is mid-task. Work that resumes by itself after a restart (missions, long tasks, the Autoloop) doesn't need
to hold a deploy, but its model calls still count while they run.

A call nested in a counted one on the same thread (a model call inside a tool loop) isn't counted again.
"""
import threading, time
from collections import Counter

_lock = threading.Lock()
_active = {}  # token -> (kind, started)
_local = threading.local()


class working:
    """with busy.working("agent"): ... counts the block as one piece of work in flight."""
    def __init__(self, kind="work"): self.kind, self.token = kind, None

    def __enter__(self):
        depth = getattr(_local, "depth", 0)
        _local.depth = depth + 1
        if depth == 0:
            self.token = object()
            with _lock: _active[id(self.token)] = (self.kind, time.time())
        return self

    def __exit__(self, *exc):
        _local.depth -= 1
        if self.token is not None:
            with _lock: _active.pop(id(self.token), None)
            self.token = None
        return False


def counted(fn, kind="model"):
    """fn wrapped so each call counts while it runs."""
    def wrapper(*a, **kw):
        with working(kind): return fn(*a, **kw)
    wrapper.__wrapped__ = fn
    return wrapper


def count():
    with _lock: return len(_active)


def snapshot():
    """{"busy": n, "kinds": {kind: n}, "oldest": seconds the longest-running piece has run}."""
    now = time.time()
    with _lock: items = list(_active.values())
    return {"busy": len(items), "kinds": dict(Counter(k for k, _ in items)),
            "oldest": round(now - min(t for _, t in items)) if items else 0}
