"""gateway: the reliability layer in front of a model provider (rate limiting, retries, SLOs), in Google SRE style."""
from ._common import BUILD_WHEEL, block, changelog, gitignore, makefile, pyproject

ONBOARDING = r"""# Welcome to the gateway team 👋

The **gateway** sits between our product and the model provider's API. Every model call goes through it, so when it's wrong, everything is wrong. It has three jobs:

- **Rate limiting** (`gateway/ratelimit.py`): a token bucket keeps us under the provider's quota instead of collecting 429s.
- **Retries** (`gateway/retry.py`): calls that fail for a reason that passes are retried, with exponential backoff and jitter.
- **SLO reporting** (`gateway/slo.py`): how available and how fast we were, against the targets we promised.

How we work follows practices Google made public in its *Site Reliability Engineering* book and its engineering-practices docs: service level objectives and error budgets, hermetic tests, small changes that each come with a test.

## Codebase tour

| Path | What's there |
|---|---|
| `gateway/errors.py` | the provider's errors, and which ones are `retryable` |
| `gateway/clock.py` | `SystemClock` for production, `FakeClock` for tests |
| `gateway/ratelimit.py` | `TokenBucket` |
| `gateway/retry.py` | `backoff()` and `call_with_retries()` |
| `gateway/slo.py` | loading request logs, and the SLO `report()` |
| `gateway/cli.py` | `python -m gateway slo logs/requests.jsonl` |
| `scripts/make_logs.py` | writes a made-up day of request logs (`make logs`) |
| `tests/` | `test_smoke.py` now, one file per ticket as you pick them up |

## Your dev loop

```sh
cd ~/projects/gateway
make                              # lists the targets
make test                         # the whole suite
pytest tests/test_clock.py -q     # one file, while you work on it
make slo                          # write logs/requests.jsonl, then print its SLO report
make build                        # dist/gateway-<version>-py3-none-any.whl
```

Edit in the Lab's **Python** tab (or type `edit gateway/clock.py` in the terminal). **Run CI** on a ticket runs its acceptance tests plus everything already merged.

## How we work

- **Hermetic tests.** A test never sleeps for real, never touches the network and never depends on luck. Code that waits takes a `clock` (tests pass a `FakeClock`); code that's random takes an `rng` (tests pass a seeded or scripted one). The whole suite runs in well under a second.
- **SLOs before features.** We promise that **99.5%** of requests succeed over 30 days. The 0.5% that may fail is the **error budget**: while there's budget left we ship features; once it's spent, reliability work comes first.
- **Small changes, each with its test.** One ticket per pull request, and CI must be green: it runs your ticket's tests and those of every merged ticket.
- **Don't edit acceptance tests to pass them.** CI runs its own copy.

## Your first week

{tickets}

Welcome aboard!
"""

README = r"""# gateway

The reliability layer between our product and the model provider: a token-bucket rate limiter, retries with exponential backoff and full jitter, and SLO reports from request logs. Python 3.11+, no dependencies.

```python
from gateway import TokenBucket, call_with_retries

bucket = TokenBucket(rate=5, capacity=10)        # 5 requests a second, bursts of 10
bucket.acquire()
answer = call_with_retries(lambda: client.complete(prompt), attempts=4, deadline=30)
```

```sh
python -m gateway slo logs/requests.jsonl --target 0.995
```

New to the codebase? Start with [ONBOARDING.md](ONBOARDING.md).
"""

INIT = r'''"""gateway: the reliability layer in front of the model provider: rate limiting, retries and SLO reporting."""
from .clock import FakeClock, SystemClock
from .errors import GatewayError, InvalidRequest, RateLimited, Timeout, Unavailable
from .ratelimit import TokenBucket
from .retry import backoff, call_with_retries

__version__ = "0.1.0.dev0"
__all__ = ["FakeClock", "GatewayError", "InvalidRequest", "RateLimited", "SystemClock", "Timeout", "TokenBucket",
           "Unavailable", "backoff", "call_with_retries"]
'''

ERRORS = r'''"""The provider's errors, and which ones are worth retrying."""


class GatewayError(Exception):
    """Base class. retryable: whether the same call can succeed if we try again later."""
    retryable = False
    status = 500


class InvalidRequest(GatewayError):
    """400: the request itself is wrong; retrying sends the same wrong request."""
    status = 400


class RateLimited(GatewayError):
    """429: too many requests. retry_after: the seconds the provider asked us to wait, if it said."""
    retryable = True
    status = 429

    def __init__(self, message: str = "rate limited", retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class Unavailable(GatewayError):
    """503: the provider is overloaded, or down for a moment."""
    retryable = True
    status = 503


class Timeout(GatewayError):
    """The call took longer than we were willing to wait."""
    retryable = True
    status = 504
'''

CLOCK = (r'''"""Clocks. Code that waits takes a clock instead of calling time itself, so tests can pass a FakeClock and run
instantly and deterministically (hermetic tests: no real time, no network, no luck)."""
import time


class SystemClock:
    """Real time, for production."""

    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class FakeClock:
    """A clock tests control: time moves only when the test, or the code under test, says so."""

    def __init__(self, start: float = 0.0):
        self._now = float(start)
        self.sleeps: list[float] = []  # every sleep, in order: what tests assert on

    def now(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        """Moves time forward without anyone sleeping (say, while another request runs)."""
        if seconds < 0:
            raise ValueError("time doesn't go backwards")
        self._now += seconds

    def sleep(self, seconds: float) -> None:
        """Like time.sleep, but instant: time moves forward by `seconds`, and the sleep is recorded."""
«sleep»
''', {"sleep": block("GW-1", r'''
        self.sleeps.append(seconds)
''', r'''
        if seconds < 0:
            raise ValueError("sleep length must be non-negative")
        self.sleeps.append(seconds)
        self._now += seconds
''')})

RATELIMIT = (r'''"""A token bucket: the rate limiter in front of the provider, so we stay under our quota instead of collecting 429s.

The bucket holds up to `capacity` tokens and refills at `rate` tokens a second. A request takes tokens (one per request,
or one per 1,000 model tokens: the caller decides); when there aren't enough, it's refused or it waits.
"""
from .clock import SystemClock

EPSILON = 1e-9  # float slack: after waiting exactly long enough, the bucket may hold 0.9999999 of a token


class TokenBucket:
    def __init__(self, rate: float, capacity: float, clock=None):
        if rate <= 0 or capacity <= 0:
            raise ValueError("rate and capacity must be positive")
        self.rate = float(rate)
        self.capacity = float(capacity)
        self.clock = clock or SystemClock()
«bucket»
''', {"bucket": block("GW-2", r'''
        # GW-2: the bucket's state goes here (it starts full)

    @property
    def available(self) -> float:
        """The tokens in the bucket now."""
        raise NotImplementedError("GW-2: the token bucket")

    def try_acquire(self, tokens: float = 1.0) -> bool:
        """Takes `tokens` if they're all there and returns True; otherwise takes nothing and returns False."""
        raise NotImplementedError("GW-2: the token bucket")

    def wait_time(self, tokens: float = 1.0) -> float:
        """The seconds until `tokens` are there (0 if they are now). Takes nothing."""
        raise NotImplementedError("GW-2: the token bucket")

    def acquire(self, tokens: float = 1.0) -> float:
        """Waits on the clock until `tokens` are there, takes them, and returns the seconds it waited."""
        raise NotImplementedError("GW-2: the token bucket")
''', r'''
        self._tokens = self.capacity
        self._at = self.clock.now()

    def _refill(self) -> None:
        now = self.clock.now()
        self._tokens = min(self.capacity, self._tokens + (now - self._at) * self.rate)
        self._at = now

    def _check(self, tokens: float) -> None:
        if tokens <= 0:
            raise ValueError("ask for a positive number of tokens")
        if tokens > self.capacity:
            raise ValueError(f"{tokens} tokens never fit in a bucket of {self.capacity}")

    @property
    def available(self) -> float:
        """The tokens in the bucket now."""
        self._refill()
        return self._tokens

    def try_acquire(self, tokens: float = 1.0) -> bool:
        """Takes `tokens` if they're all there and returns True; otherwise takes nothing and returns False."""
        self._check(tokens)
        self._refill()
        if self._tokens + EPSILON < tokens:
            return False
        self._tokens = max(0.0, self._tokens - tokens)
        return True

    def wait_time(self, tokens: float = 1.0) -> float:
        """The seconds until `tokens` are there (0 if they are now). Takes nothing."""
        self._check(tokens)
        self._refill()
        return max(0.0, (tokens - self._tokens) / self.rate)

    def acquire(self, tokens: float = 1.0) -> float:
        """Waits on the clock until `tokens` are there, takes them, and returns the seconds it waited."""
        waited = self.wait_time(tokens)
        if waited > 0:
            self.clock.sleep(waited)
        if not self.try_acquire(tokens):
            raise RuntimeError("someone else took the tokens while we waited")
        return waited
''')})

RETRY = (r'''"""Retries with exponential backoff and full jitter.

A call that failed for a reason that passes (the provider is overloaded, we were rate limited, it timed out) is tried
again after a wait. Waits grow exponentially so a struggling provider gets room to recover, and they're random
("jitter") so a thousand clients that failed together don't all come back together. "Exponential Backoff And Jitter"
on the AWS Architecture Blog shows why full jitter works best.
"""
import random

from .clock import SystemClock
from .errors import GatewayError, RateLimited


def backoff(attempt: int, base: float = 0.5, cap: float = 30.0) -> float:
    """The longest wait before retry number `attempt` (0 before the first retry): base * 2**attempt, at most cap."""
«backoff»


def call_with_retries(fn, *, attempts: int = 4, base: float = 0.5, cap: float = 30.0, deadline: float | None = None,
                      clock=None, rng=None):
    """Calls fn() until it succeeds, at most `attempts` times in all, and returns what it returns (GW-3)."""
«retries»
''', {
    "backoff": block("GW-3", r'''
    raise NotImplementedError("GW-3: exponential backoff")
''', r'''
    return min(cap, base * 2 ** attempt)
'''),
    "retries": block("GW-3", r'''
    raise NotImplementedError("GW-3: retries")
''', r'''
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    clock = clock or SystemClock()
    rng = rng or random.Random()
    start = clock.now()
    for attempt in range(attempts):
        try:
            return fn()
        except GatewayError as e:
            if not e.retryable or attempt == attempts - 1:
                raise
            wait = rng.uniform(0, backoff(attempt, base, cap))  # full jitter
            if isinstance(e, RateLimited) and e.retry_after is not None:
                wait = max(wait, e.retry_after)
            if deadline is not None and clock.now() - start + wait > deadline:
                raise
            clock.sleep(wait)
'''),
})

SLO = (r'''"""SLO reporting: how available and how fast the gateway was, against the targets we promised (SRE-book style).

A request is good when it didn't fail on our side: status below 500, and not 429 (we throttled our own user). Other 4xx
are the caller's mistake and count as good. Availability is good / all; the error budget is what the target lets fail
(1 - target), and budget_spent is the share of it used up: above 1, the SLO is broken.
"""
import json
import math


def load(path: str) -> list[dict]:
    """Request records from a JSON Lines log: one {"ts", "model", "status", "latency_ms"} object per line."""
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def is_good(record: dict) -> bool:
    return record["status"] < 500 and record["status"] != 429


def percentile(values, p: float) -> float:
    """The nearest-rank percentile: the smallest value with at least p% of the values at or below it (GW-4)."""
«percentile»


def report(records: list[dict], target: float = 0.995, latency_ms: float = 2000) -> dict:
    """The SLO report for a window of requests (GW-4): the ticket lists its keys."""
«report»
''', {
    "percentile": block("GW-4", r'''
    raise NotImplementedError("GW-4: nearest-rank percentile")
''', r'''
    if not values:
        raise ValueError("no values")
    if not 0 < p <= 100:
        raise ValueError("p must be in (0, 100]")
    ordered = sorted(values)
    return ordered[math.ceil(p * len(ordered) / 100) - 1]
'''),
    "report": block("GW-4", r'''
    raise NotImplementedError("GW-4: the SLO report")
''', r'''
    if not records:
        raise ValueError("no requests in this window")
    good = [r for r in records if is_good(r)]
    availability = len(good) / len(records)
    latencies = [r["latency_ms"] for r in records]
    by_model = {}
    for model in sorted({r["model"] for r in records}):
        rs = [r for r in records if r["model"] == model]
        by_model[model] = {"requests": len(rs), "availability": sum(map(is_good, rs)) / len(rs),
                           "p95_ms": percentile([r["latency_ms"] for r in rs], 95)}
    return {
        "requests": len(records), "good": len(good), "availability": availability,
        "target": target, "slo_met": availability >= target, "budget_spent": (1 - availability) / (1 - target),
        "p50_ms": percentile(latencies, 50), "p95_ms": percentile(latencies, 95), "p99_ms": percentile(latencies, 99),
        "fast": sum(r["latency_ms"] <= latency_ms for r in good) / len(good) if good else 0.0,
        "by_model": by_model,
    }
'''),
})

CLI = r'''"""python -m gateway slo LOG [--target 0.995] [--latency-ms 2000]: the SLO report of a request log.
It exits 1 when the SLO is missed, so a scheduled job can page someone."""
import argparse

from .slo import load, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gateway")
    sub = parser.add_subparsers(dest="command", required=True)
    slo = sub.add_parser("slo", help="the SLO report of a JSON Lines request log")
    slo.add_argument("log")
    slo.add_argument("--target", type=float, default=0.995)
    slo.add_argument("--latency-ms", type=float, default=2000)
    args = parser.parse_args(argv)
    r = report(load(args.log), args.target, args.latency_ms)
    print(f"requests      {r['requests']:,}")
    print(f"availability  {r['availability']:.3%}  (target {r['target']:.1%}: {'met' if r['slo_met'] else 'MISSED'})")
    print(f"error budget  {r['budget_spent']:.0%} spent")
    print(f"latency       p50 {r['p50_ms']:,.0f} ms · p95 {r['p95_ms']:,.0f} ms · p99 {r['p99_ms']:,.0f} ms"
          f" · {r['fast']:.1%} of good requests under {args.latency_ms:,.0f} ms")
    for model, m in r["by_model"].items():
        print(f"  {model:<8} {m['requests']:>6,} requests  {m['availability']:.2%} good  p95 {m['p95_ms']:,.0f} ms")
    return 0 if r["slo_met"] else 1
'''

MAIN = r'''from .cli import main

raise SystemExit(main())
'''

MAKE_LOGS = r'''"""Writes logs/requests.jsonl: a made-up day of gateway traffic. Seeded, so everyone gets the same file."""
import json
import pathlib
import random

rng = random.Random(42)
MODELS = {"small": (180, 0.35), "large": (650, 0.45)}  # median latency (ms) and spread of each model
out = pathlib.Path(__file__).resolve().parent.parent / "logs" / "requests.jsonl"
out.parent.mkdir(exist_ok=True)
with out.open("w", encoding="utf-8") as f:
    for i in range(5000):
        model = "small" if rng.random() < 0.7 else "large"
        median, spread = MODELS[model]
        roll = rng.random()
        status = 503 if roll < 0.0015 else 429 if roll < 0.0025 else 400 if roll < 0.012 else 200
        record = {"ts": 1767225600 + i * 17, "model": model, "status": status,
                  "latency_ms": round(median * rng.lognormvariate(0, spread))}
        f.write(json.dumps(record) + "\n")
print("wrote logs/requests.jsonl: 5,000 requests")
'''

SMOKE = r'''"""Smoke tests: the package imports, and what already works keeps working."""
import gateway
from gateway import InvalidRequest, RateLimited, Timeout, Unavailable
from gateway.slo import is_good


def test_version():
    """The package imports and has a version"""
    assert gateway.__version__


def test_retryable_errors():
    """429, 503 and timeouts are retryable; 400 isn't"""
    assert RateLimited().retryable and Unavailable().retryable and Timeout().retryable
    assert not InvalidRequest().retryable
    assert RateLimited(retry_after=3).retry_after == 3


def test_is_good():
    """Our failures (5xx and 429) are bad requests; the caller's (other 4xx) aren't"""
    assert is_good({"status": 200}) and is_good({"status": 404})
    assert not is_good({"status": 503}) and not is_good({"status": 429})
'''

T_CLOCK = r'''"""GW-1: FakeClock.sleep moves time forward, as a real sleep does, only instantly."""
from gateway import FakeClock


def test_sleep_advances_time():
    """sleep(s) moves now() forward by s"""
    clock = FakeClock(start=10)
    clock.sleep(2.5)
    assert clock.now() == 12.5, f"after sleep(2.5) from 10, now() is {clock.now()}"


def test_sleeps_are_recorded():
    """Each sleep is recorded, in order, and they add up"""
    clock = FakeClock()
    clock.sleep(1)
    clock.sleep(0.5)
    assert clock.sleeps == [1, 0.5], f"sleeps are {clock.sleeps}"
    assert clock.now() == 1.5, f"now() is {clock.now()}"


def test_negative_sleep_rejected():
    """A negative sleep raises ValueError, as time.sleep does, and changes nothing"""
    clock = FakeClock()
    try:
        clock.sleep(-1)
    except ValueError:
        pass
    else:
        raise AssertionError("sleep(-1) should raise ValueError")
    assert clock.now() == 0 and clock.sleeps == [], "a rejected sleep shouldn't change the clock"


def test_advance_still_works():
    """advance() moves time and refuses to go back"""
    clock = FakeClock()
    clock.advance(3)
    assert clock.now() == 3
    try:
        clock.advance(-1)
    except ValueError:
        return
    raise AssertionError("advance(-1) should raise ValueError")
'''

T_RATELIMIT = r'''"""GW-2: the token bucket rate limiter."""
import math

from gateway import FakeClock, TokenBucket


def bucket(rate=2, capacity=4):
    clock = FakeClock()
    return TokenBucket(rate, capacity, clock), clock


def test_starts_full():
    """A new bucket holds `capacity` tokens"""
    b, _ = bucket()
    assert b.available == 4, f"a new bucket holds {b.available}"


def test_takes_until_empty():
    """try_acquire takes tokens while there are enough, then refuses without taking any"""
    b, _ = bucket()
    got = [b.try_acquire() for _ in range(5)]
    assert got == [True, True, True, True, False], f"five try_acquire() on a bucket of 4 gave {got}"
    assert b.try_acquire(0.5) is False and b.available == 0


def test_refills_at_rate_up_to_capacity():
    """Tokens come back at `rate` a second, never above capacity"""
    b, clock = bucket(rate=2, capacity=4)
    b.try_acquire(4)
    clock.advance(1.5)
    assert math.isclose(b.available, 3), f"after 1.5 s at 2 a second: 3 tokens, got {b.available}"
    clock.advance(60)
    assert b.available == 4, f"never more than capacity, got {b.available}"


def test_wait_time():
    """wait_time says how long until the tokens are there, and takes nothing"""
    b, _ = bucket(rate=2, capacity=4)
    assert b.wait_time(3) == 0
    b.try_acquire(4)
    assert math.isclose(b.wait_time(3), 1.5), f"3 tokens at 2 a second: 1.5 s, got {b.wait_time(3)}"
    assert math.isclose(b.wait_time(3), 1.5), "asking twice gives the same answer: wait_time takes nothing"


def test_acquire_sleeps_on_the_clock():
    """acquire waits on the clock (never for real), then takes the tokens"""
    b, clock = bucket(rate=2, capacity=4)
    b.try_acquire(4)
    waited = b.acquire(1)
    assert math.isclose(waited, 0.5) and clock.sleeps == [waited], f"waited {waited}, the clock slept {clock.sleeps}"
    assert b.available < 1e-6, "the token it waited for is taken"


def test_bad_requests():
    """More than capacity, or 0 tokens, raises ValueError"""
    b, _ = bucket(capacity=4)
    for call in (lambda: b.try_acquire(5), lambda: b.wait_time(5), lambda: b.acquire(5), lambda: b.try_acquire(0)):
        try:
            call()
        except ValueError:
            continue
        raise AssertionError("asking for 5 tokens from a bucket of 4, or for 0, should raise ValueError")
'''

T_RETRY = r'''"""GW-3: call_with_retries: exponential backoff with full jitter, retry_after and deadlines."""
import random

from gateway import FakeClock, InvalidRequest, RateLimited, Timeout, Unavailable, backoff, call_with_retries


class MaxRng:
    """Stands in for random.Random: uniform(a, b) always picks b, so each wait is exactly the backoff."""

    def uniform(self, a, b):
        return b


def flaky(*errors, result="ok"):
    """A function that raises each error in turn, then returns result; .calls counts the calls."""
    errors = list(errors)

    def fn():
        fn.calls += 1
        if errors:
            raise errors.pop(0)
        return result
    fn.calls = 0
    return fn


def test_backoff_doubles_up_to_cap():
    """backoff() doubles from base and stops at cap"""
    got = [backoff(k, base=0.5, cap=3) for k in range(5)]
    assert got == [0.5, 1, 2, 3, 3], f"got {got}"


def test_success_needs_no_wait():
    """A call that works at once returns its result without sleeping"""
    clock, fn = FakeClock(), flaky()
    assert call_with_retries(fn, clock=clock, rng=MaxRng()) == "ok"
    assert fn.calls == 1 and clock.sleeps == [], f"{fn.calls} calls, sleeps {clock.sleeps}"


def test_retries_with_backoff():
    """Retryable errors are retried, waiting up to base, 2×base, 4×base…"""
    clock, fn = FakeClock(), flaky(Unavailable(), Timeout(), Unavailable())
    assert call_with_retries(fn, attempts=4, base=0.5, clock=clock, rng=MaxRng()) == "ok"
    assert fn.calls == 4, f"expected 4 calls, got {fn.calls}"
    assert clock.sleeps == [0.5, 1.0, 2.0], f"sleeps were {clock.sleeps}"


def test_full_jitter():
    """Each wait is rng.uniform(0, backoff): full jitter"""
    clock = FakeClock()
    call_with_retries(flaky(Unavailable(), Unavailable(), Unavailable()), attempts=4, base=1, clock=clock, rng=random.Random(7))
    r = random.Random(7)
    want = [r.uniform(0, 1), r.uniform(0, 2), r.uniform(0, 4)]
    assert clock.sleeps == want, f"sleeps were {clock.sleeps}, expected {want}: one rng.uniform(0, backoff(k)) per wait"


def test_retry_after_is_respected():
    """RateLimited.retry_after is the least we wait"""
    clock = FakeClock()
    call_with_retries(flaky(RateLimited(retry_after=5)), base=0.5, clock=clock, rng=MaxRng())
    assert clock.sleeps == [5], f"sleeps were {clock.sleeps}: wait at least retry_after"


def test_non_retryable_raised_at_once():
    """InvalidRequest isn't retried"""
    clock, fn = FakeClock(), flaky(InvalidRequest("bad"))
    try:
        call_with_retries(fn, clock=clock, rng=MaxRng())
    except InvalidRequest:
        pass
    else:
        raise AssertionError("InvalidRequest should be raised")
    assert fn.calls == 1 and clock.sleeps == [], f"{fn.calls} calls and sleeps {clock.sleeps}: don't retry a 400"


def test_gives_up_after_attempts():
    """After `attempts` failures the last error is raised"""
    clock, last = FakeClock(), Timeout("third")
    fn = flaky(Unavailable("first"), Unavailable("second"), last)
    try:
        call_with_retries(fn, attempts=3, clock=clock, rng=MaxRng())
    except Timeout as e:
        assert e is last, "raise the last error, not an earlier one"
    else:
        raise AssertionError("expected the last error to be raised")
    assert fn.calls == 3 and len(clock.sleeps) == 2, f"{fn.calls} calls, sleeps {clock.sleeps}"


def test_deadline():
    """No wait that would end past the deadline: give up instead"""
    clock, fn = FakeClock(), flaky(*[Unavailable() for _ in range(10)])
    try:
        call_with_retries(fn, attempts=10, base=1, deadline=6, clock=clock, rng=MaxRng())
    except Unavailable:
        pass
    else:
        raise AssertionError("expected Unavailable once the next wait would pass the deadline")
    assert clock.sleeps == [1, 2], f"sleeps were {clock.sleeps}: 1 + 2 = 3 s, and the next 4 s would end at 7 s, past 6"
'''

T_SLO = r'''"""GW-4: the SLO report: availability, error budget and latency percentiles."""
import math

from gateway.slo import percentile, report


def req(status=200, ms=100, model="small"):
    return {"ts": 0, "model": model, "status": status, "latency_ms": ms}


def test_percentile_nearest_rank():
    """percentile() takes the nearest rank, with no interpolation"""
    xs = [35, 20, 15, 50, 40]
    got = [percentile(xs, p) for p in (5, 30, 40, 50, 100)]
    assert got == [15, 20, 20, 35, 50], f"got {got}"


def test_percentile_validates():
    """percentile() refuses empty input and p outside (0, 100]"""
    for bad in (lambda: percentile([], 50), lambda: percentile([1], 0), lambda: percentile([1], 101)):
        try:
            bad()
        except ValueError:
            continue
        raise AssertionError("expected ValueError for no values, p=0 or p=101")


def test_availability_counts_5xx_and_429():
    """5xx and 429 are bad; other 4xx are good (the caller's fault)"""
    r = report([req(200)] * 90 + [req(400)] * 5 + [req(429)] * 3 + [req(503)] * 2)
    assert r["requests"] == 100 and r["good"] == 95, f"good = {r['good']}: 200 and 400 are good, 429 and 503 aren't"
    assert math.isclose(r["availability"], 0.95)


def test_error_budget():
    """budget_spent is the share of the error budget used up; slo_met compares with the target"""
    r = report([req(200)] * 998 + [req(500)] * 2, target=0.995)
    assert math.isclose(r["budget_spent"], 0.4), f"2 bad in 1,000 with a 0.5% budget is 40% spent, got {r['budget_spent']}"
    assert r["slo_met"] is True and r["target"] == 0.995
    r = report([req(200)] * 990 + [req(500)] * 10, target=0.995)
    assert math.isclose(r["budget_spent"], 2.0) and r["slo_met"] is False


def test_latency_percentiles():
    """p50, p95 and p99 over all requests, and `fast` over the good ones"""
    r = report([req(200, ms) for ms in range(10, 1010, 10)], latency_ms=500)  # 10, 20, … 1,000 ms
    got = (r["p50_ms"], r["p95_ms"], r["p99_ms"])
    assert got == (500, 950, 990), f"got p50, p95, p99 = {got}"
    assert math.isclose(r["fast"], 0.5), f"half the requests take 500 ms or less, got fast = {r['fast']}"


def test_by_model():
    """The report breaks down by model, sorted by name"""
    r = report([req(200, 100, "large")] * 9 + [req(503, 3000, "large")] + [req(200, 50, "small")] * 10)
    assert list(r["by_model"]) == ["large", "small"], f"got {list(r['by_model'])}"
    assert r["by_model"]["large"] == {"requests": 10, "availability": 0.9, "p95_ms": 3000}, f"got {r['by_model']['large']}"
    assert r["by_model"]["small"]["availability"] == 1.0


def test_empty_window():
    """An empty window raises ValueError instead of dividing by zero"""
    try:
        report([])
    except ValueError:
        return
    raise AssertionError("report([]) should raise ValueError")
'''

PROJECT = {
    "id": "gateway", "name": "gateway", "package": "gateway", "like": "Google's SRE practices", "org": "Google",
    "title": "A reliable LLM API gateway",
    "blurb": "Join the team that keeps model calls reliable: fix a test clock, build a token-bucket rate limiter, retries with "
             "backoff and jitter, and an SLO report with error budgets, then ship 0.1.0.",
    "level": "Intermediate", "hours": 3, "skills": ["Rate limiting", "Retries & jitter", "SLOs", "Hermetic tests", "Packaging"],
    "topics": ["api.reliability", "prod.observe", "found.python"],
    "smoke": SMOKE,
    "files": {
        "README.md": README, "ONBOARDING.md": ONBOARDING, "CHANGELOG.md": changelog("gateway", "Project scaffolding: the provider's errors, the clocks and the CLI."),
        "pyproject.toml": pyproject("gateway", "Rate limiting, retries and SLO reports for model API calls"),
        ".gitignore": gitignore("logs/"),
        "Makefile": makefile("gateway", """
logs:  ## write logs/requests.jsonl: a made-up day of traffic
    python scripts/make_logs.py

slo: logs  ## the SLO report of logs/requests.jsonl
    python -m gateway slo logs/requests.jsonl --target 0.995
""", "logs"),
        "gateway/__init__.py": INIT, "gateway/__main__.py": MAIN, "gateway/cli.py": CLI, "gateway/errors.py": ERRORS,
        "gateway/clock.py": CLOCK, "gateway/ratelimit.py": RATELIMIT, "gateway/retry.py": RETRY, "gateway/slo.py": SLO,
        "scripts/build_wheel.py": BUILD_WHEEL, "scripts/make_logs.py": MAKE_LOGS,
    },
    "tickets": [
        {"id": "GW-1", "kind": "good first issue", "title": "FakeClock.sleep doesn't move time", "estimate": 15, "topic": "api.reliability",
         "touch": ["gateway/clock.py"], "test_path": "tests/test_clock.py", "tests": T_CLOCK,
         "body": r"""**Reported by** Priya (on call for retries) · **Labels** `bug` `good first issue` `testing`

> I was testing a retry loop with a deadline and the test never finished: `FakeClock.now()` stays at 0 however long the code sleeps.

`FakeClock.sleep(seconds)` records the sleep but forgets to move time forward, so code that waits *until* something happens never gets there under test. Make a fake sleep behave like a real one, only instantly:

- `sleep(s)` moves `now()` forward by `s` and records `s` in `sleeps`;
- a negative `s` raises `ValueError` (as `time.sleep(-1)` does) and changes nothing.

**Where:** `FakeClock.sleep` in `gateway/clock.py`. **Done when** `tests/test_clock.py` passes (`pytest tests/test_clock.py -q`) and **Run CI** is green.
""",
         "hints": ["Look at `advance()` just above: it already does most of what `sleep()` needs.",
                   "Check the argument before touching `sleeps` or the time, so a rejected sleep changes nothing."]},
        {"id": "GW-2", "kind": "feature", "title": "Token bucket rate limiter", "estimate": 40, "topic": "api.reliability",
         "touch": ["gateway/ratelimit.py"], "test_path": "tests/test_ratelimit.py", "tests": T_RATELIMIT,
         "body": r"""**Labels** `feature` · **Needs** GW-1

We collect 429s from the provider at peak. Implement `TokenBucket` in `gateway/ratelimit.py`, so we pace ourselves instead:

- The bucket holds up to `capacity` tokens, **starts full**, and refills continuously at `rate` tokens a second, never above `capacity`. Refill lazily: whenever you look at the bucket, add `elapsed × rate` since the last look.
- `try_acquire(n=1)`: if `n` tokens are there, take them and return `True`; otherwise take nothing and return `False`.
- `wait_time(n=1)`: the seconds until `n` tokens will be there (0 if they are now). It takes nothing.
- `acquire(n=1)`: sleep on the clock until `n` tokens are there, take them, and return the seconds waited.
- `available`: the tokens in the bucket now.
- Asking for more than `capacity` (it could never be satisfied), or for 0 or fewer tokens, raises `ValueError`.

Time comes from `self.clock` only (`now()` and `sleep()`), never from `time`: that's what keeps the tests hermetic. Mind float rounding: after `acquire` sleeps exactly `wait_time`, the bucket may hold 0.9999999 of the token you need (`EPSILON` is there for that).

**Done when** `tests/test_ratelimit.py` passes and CI is green.
""",
         "hints": ["Keep two fields, the tokens and the time you last refilled; a `_refill()` method updates both and every public method calls it first.",
                   "`wait_time` is `(n - tokens) / rate` when you're short, and 0 otherwise.",
                   "In `try_acquire`, allow a little slack (`tokens + EPSILON >= n`) and never let the count go below 0."]},
        {"id": "GW-3", "kind": "feature", "title": "Retries with exponential backoff and jitter", "estimate": 45, "topic": "api.reliability",
         "touch": ["gateway/retry.py"], "test_path": "tests/test_retry.py", "tests": T_RETRY,
         "body": r"""**Labels** `feature` · **Needs** GW-1

At our volume calls fail all the time: 503s when the provider is busy, 429s when we're over quota, timeouts. Most succeed a moment later, but hammering a struggling provider makes it worse. Implement `backoff()` and `call_with_retries()` in `gateway/retry.py`:

- `backoff(attempt, base, cap)`: `base × 2^attempt`, at most `cap`. With `base=0.5`: 0.5, 1, 2, 4… seconds.
- `call_with_retries(fn, attempts=4, base=0.5, cap=30, deadline=None, clock=None, rng=None)` calls `fn()` and returns what it returns. When `fn()` raises:
  - an error that isn't `retryable` (`InvalidRequest`, or anything that isn't a `GatewayError`): raise it at once;
  - a retryable one (`Unavailable`, `RateLimited`, `Timeout`): wait, then call again. Before retry number *k* (0 for the first), wait **`rng.uniform(0, backoff(k, base, cap))`** seconds: *full jitter*. Call `rng.uniform` exactly once per wait;
  - a `RateLimited` with a `retry_after`: wait at least that long (the provider told us to);
  - after `attempts` calls in all, raise the last error;
  - with a `deadline` (seconds since the first call): if a wait would end past it, don't wait: raise the error.
- Wait with `clock.sleep()`, never `time.sleep()`. Without a clock or an rng, use `SystemClock()` and `random.Random()`.

**Done when** `tests/test_retry.py` passes and CI is green.
""",
         "hints": ["A `for attempt in range(attempts):` loop with `try: return fn()` inside does most of the work.",
                   "`if not e.retryable or attempt == attempts - 1: raise` re-raises the error you caught, the last one included.",
                   "Work out the wait first, then check the deadline (`clock.now() - start + wait > deadline`), then sleep."]},
        {"id": "GW-4", "kind": "feature", "title": "SLO report with error budget", "estimate": 40, "topic": "prod.observe",
         "touch": ["gateway/slo.py"], "test_path": "tests/test_slo.py", "tests": T_SLO,
         "body": r"""**Labels** `feature` `observability` · **Needs** GW-1

We promise that **99.5%** of requests succeed over 30 days, and today nobody can tell whether we keep that promise. Implement the SLO report in `gateway/slo.py`:

- `percentile(values, p)`: the **nearest-rank** percentile. Sort, and take the value at position `ceil(p × n / 100)`, counting from 1. No interpolation. No values, or `p` outside (0, 100], raise `ValueError`.
- `report(records, target=0.995, latency_ms=2000)` returns a dict:

| key | meaning |
|---|---|
| `requests`, `good` | all requests, and the good ones (`is_good()`: status below 500 and not 429) |
| `availability` | good ÷ requests |
| `target`, `slo_met` | the target, and whether availability ≥ target |
| `budget_spent` | (1 − availability) ÷ (1 − target): 0.4 means 40% of the error budget is gone; above 1, the SLO is broken |
| `p50_ms`, `p95_ms`, `p99_ms` | latency percentiles over all requests |
| `fast` | the share of **good** requests that took `latency_ms` or less |
| `by_model` | per model, sorted by name: `{"requests", "availability", "p95_ms"}` |

An empty list raises `ValueError`. Then try a day of traffic: `make slo` writes `logs/requests.jsonl` and prints its report.

**Done when** `tests/test_slo.py` passes and CI is green.
""",
         "hints": ["`math.ceil(p * len(values) / 100) - 1` is the index into the sorted list.",
                   "Loop over `sorted({r[\"model\"] for r in records})` so `by_model` comes out in order.",
                   "`fast` divides by the good requests, not all of them: mind the case where there are none."]},
    ],
}
