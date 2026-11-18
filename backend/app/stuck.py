"""Stopping a run that's going in circles (after Agent_Company's StuckWatch, itself after OpenHands' stuck detection).

A Watch is fed each finished tool call of one run and names why the run must end:
- the same call (tool + input) giving the same result REPEAT times in a row. The result is part of it, so a tool that is
  polled while something changes (a status, a log) isn't stuck: its answers differ;
- the same call failing with the same error ERRORS times, in a row or not.
0 turns a rule off. Used by agents.run_loop (every tool-loop agent), infiagent's Long tasks; workbench/workbench.py keeps its
own copy of the rules (it's a single standard-library file on the host).

Until now a run that repeated itself only ended at its step cap, or when Control Hub's dispatcher noticed a task that hadn't
moved for an hour (control_dispatch.STALE).
"""
import hashlib, json

REPEAT = 5  # the same call with the same result, in a row
ERRORS = 3  # the same call with the same error, in all


def _text(x):
    return x if isinstance(x, str) else json.dumps(x, sort_keys=True, default=str)


def _key(*parts):
    return hashlib.sha1("\0".join(" ".join(_text(p).split()) for p in parts).encode("utf-8", "replace")).hexdigest()


class Watch:
    def __init__(self, repeat=REPEAT, errors=ERRORS):
        self.repeat, self.errors = repeat, errors
        self.last, self.streak, self.failed, self.reason = None, 0, {}, ""

    @property
    def on(self):
        return self.repeat > 0 or self.errors > 0

    def result(self, name, args, out, error=False):
        """Feed one finished call: tool name, its input, its output (text or JSON-able), whether it failed. Returns the
        reason to stop the run, or "" (and keeps returning that reason once there is one)."""
        if self.reason or not self.on: return self.reason
        same = _key(name, args or {}, out)
        self.streak = self.streak + 1 if same == self.last else 1
        self.last = same
        if 0 < self.repeat <= self.streak:
            self.reason = (f"Stopped: the run was going in circles. It called {name} {self.streak} times in a row with the same "
                           "input and got the same result each time.")
        elif error and self.errors > 0:
            self.failed[same] = self.failed.get(same, 0) + 1
            if self.failed[same] >= self.errors:
                self.reason = (f"Stopped: the run was going in circles. {name} failed {self.failed[same]} times with the same "
                               "input and the same error.")
        return self.reason
