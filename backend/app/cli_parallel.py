"""How many turns each CLI login runs at once (Terminal = Claude Code, Codex), set in Agents → Models.

The limit is AXoR's, not Claude's or OpenAI's: one login can run many CLI instances. It's there because every run spends
the same plan's usage window (the owner's own Claude Code sessions too), and each run is a CLI process in the web pod.
A higher number finishes parallel work sooner and uses the plan up sooner.

Gate is a semaphore whose size is read on every acquire, so a new limit applies at once without a restart: raising it
lets waiting runs start, lowering it lets runs already going finish and holds new ones until there's room. Every login
(the server's and each person's own, cli_accounts.py) has its own Gate with the same limit."""
import os, threading, time

MAX = 24  # the web pod has room for ~24 CLI processes (~300 MB each, k8s/base/30-axor.yaml)
KEYS = {"terminal": "terminal_parallel", "codex": "codex_parallel"}
DEFAULT = {"terminal": max(1, int(os.getenv("TERMINAL_PARALLEL", "2"))), "codex": max(1, int(os.getenv("CODEX_PARALLEL", "2")))}
_limits = dict(DEFAULT)
S = {"db": None}


def load(db):
    """At start: the saved limits (Agents → Models) over the environment's defaults."""
    S["db"] = db
    for p, k in KEYS.items():
        v = db.setting(k)
        _limits[p] = _clamp(v) if v else DEFAULT[p]


def _clamp(n):
    try: return max(1, min(MAX, int(n)))
    except (TypeError, ValueError): return 2


def limit(p):
    return _limits.get(p, 2)


def saved(p):
    """True when an admin set it (not the environment's default)."""
    return bool(S["db"] and S["db"].setting(KEYS[p]))


def set_limit(p, n):
    if p not in KEYS: raise ValueError("Unknown CLI.")
    n = int(n)
    if not 1 <= n <= MAX: raise ValueError(f"Pick 1 to {MAX}.")
    _limits[p] = n
    if S["db"]: S["db"].setting(KEYS[p], v=n)
    return n


class Gate:
    """A BoundedSemaphore-like gate sized by limit(p) at the moment of each acquire (`with gate:` or acquire/release)."""
    def __init__(self, p):
        self.p, self.held, self._cv = p, 0, threading.Condition()

    def acquire(self, blocking=True, timeout=None):
        end = None if timeout is None else time.monotonic() + timeout
        with self._cv:
            while self.held >= limit(self.p):
                if not blocking: return False
                left = None if end is None else end - time.monotonic()
                if left is not None and left <= 0: return False
                self._cv.wait(1.0 if left is None else min(left, 1.0))  # re-reads the limit: a raised one applies within a second
            self.held += 1
            return True

    def release(self):
        with self._cv:
            if self.held <= 0: raise ValueError("Gate released too many times")
            self.held -= 1
            self._cv.notify()

    @property
    def _value(self):
        """Free slots now, as threading.Semaphore names it (tests check a run gave its slot back)."""
        return limit(self.p) - self.held

    def __enter__(self):
        self.acquire(); return self

    def __exit__(self, *exc):
        self.release()
