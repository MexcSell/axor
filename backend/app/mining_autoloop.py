"""Competition teams, the Autoloop: the rules autopilot (mining_work.py) runs by, so a team improves its miner instead of just
making activity. The cycle is observe → plan → execute → verify → learn → optimize → repeat; this module is the part between
the steps that keeps it honest.

- Budget governor: before any work starts, five checks: the team's 24-hour budget (new tasks stop when only the reserve is
  left, 15% by default, which stays for reviews of finished work), the competition's lifetime budget, the model provider's
  health (a cooldown after refused keys, spent credit or rate limits), whether the next task is likely to fit (the median
  cost of the team's recent task runs against what's left) and a free slot. When a check fails the work stays in the queue:
  it doesn't start, fail and count as a failure. Each task run also has a token cap: past it the agent's tools stop and it
  must file what it has; at one and a half times the cap the run stops.
- Failures are classified before anything retries them: budget (back in the queue, not counted), provider (back in the
  queue, the team cools down), rate limit and transient errors (timeouts, restarts, 5xx: retried after 1, 4 and 16 minutes,
  `retries` times at most), and the task's own failures (too long, nothing filed, the sandbox: counted as before; twice and
  autopilot leaves it to the user).
- Queue manager: autopilot keeps at most `queue_cap` tasks queued (three per slot by default); the Director doesn't plan
  while `backlog_cap` tasks are already open and agents suggest one follow-up at most; near-duplicate open tasks and agents
  with long queues are listed, with a way to spread a queue over idle squad-mates.
- One agent per file: an agent can't write a file another running agent wrote in this run.
- Recovery: after a server restart, the tasks it cut off on autopilot teams go back in the queue, in their place.
- Observe mode: autopilot on, but it only records what it would start, plan and send to review, and does none of it.
  Each entry is then matched against what you did (you started that task, you planned), which gives an agreement rate to
  judge it by before you let it act. Teams start in "act" (as before); observe is opted into on the Autoloop tab.
- Optimizer: rule-based suggestions from the last day (lower concurrency on rate limits, raise or spread the budget, clear the
  backlog, check an agent that only fails) and the economics: tokens per run, per filed task, per verified task.

Agents never upload, register or submit: that stays the user's, with or without the Autoloop.
"""
import json, re, statistics, threading, time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .llm import PLAN_PROVIDERS, plan_parallel, quota_until
from .task_lifecycle import not_dropped  # D-018: dropped work isn't completed work
from .mining import _clip
from .mining_work import BUDGET, PLAN_GAP


def _hm(ts):
    """A clock time in text the server writes (checks, queue notes, events): the server's zone is named (UTC in the pod), so a
    reader in another zone doesn't take 07:11 UTC for 07:11 their time. Live checks also carry the timestamp (`until`) for the page to show locally."""
    return time.strftime("%H:%M %Z", time.localtime(ts))
from . import agent_core, model_router

DAY = 86400
ALT_TIER = 2            # D-038 B3: a free model counts as somewhere else for routed work only at this tier (review/plan need it)
RESERVE = 15.0          # % of the daily budget new tasks leave for reviews
RETRIES = 2             # automatic retries of a transient failure
TASK_CAP_MIN = 60_000   # the automatic per-task cap: 15% of the daily budget, never under this
QUEUE_PER_SLOT = 3      # queued tasks autopilot keeps per slot
BACKLOG_MIN = 12        # open tasks that hold the Director's next plan: this many at least, or four per slot
BACKOFF = (60, 240, 960)
COOL_PROVIDER = 900     # a refused key or spent credit: wait 15 min (doubling, 2 h at most)
COOL_RATE = 120         # a rate limit: wait 2 min (doubling, 30 min at most)
RESTART = "Stopped by a server restart."
PLAN_NAME = {"terminal": "Claude plan", "codex": "ChatGPT plan (Codex)"}  # the subscription each plan provider's CLI runs on
from .orchestrator import AUTOLOOP_PATTERNS as CLASSES, autoloop_class, decide  # noqa: E402  (class, pattern) in order: one recognizer (orchestrator, G5 Phase 1)
from .orchestrator import AUTOLOOP_LABEL as LABEL, AUTOLOOP_POLICY as POLICY  # noqa: E402  one taxonomy (orchestrator.FAILURE_CLASSES, G5 Phase 1)
STAGES = ("observe", "plan", "execute", "verify", "learn", "optimize", "repeat")
STOP = set("a an the and or of to in on for with by from at is are be it its this that as into our your their we you".split())


def classify(err):
    return autoloop_class(err)


def _words(s):
    return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(w) > 2 and w not in STOP}


class PolicyIn(BaseModel):
    reserve: float | None = Field(None, ge=0, le=50)           # % of the daily budget kept for reviews
    retries: int | None = Field(None, ge=0, le=5)
    task_cap: int | None = Field(None, ge=0, le=5_000_000)      # tokens per task run; 0 = none, null = automatic
    total_cap: int | None = Field(None, ge=0, le=2_000_000_000)  # tokens over the competition's life; 0 = none
    queue_cap: int | None = Field(None, ge=0, le=400)           # null = three per slot
    backlog_cap: int | None = Field(None, ge=0, le=400)         # null = automatic

class ModeIn(BaseModel):
    mode: str = Field(..., pattern=r"^(act|observe)$")

class SpreadIn(BaseModel):
    agent: int
    keep: int = Field(2, ge=0, le=20)


class Loop:
    def __init__(self, work):
        self.w, self.db = work, work.db
        q = self.db.q
        q("""CREATE TABLE IF NOT EXISTS ml_policy (comp_id INTEGER PRIMARY KEY, reserve REAL, retries INTEGER, task_cap INTEGER, total_cap INTEGER,
             queue_cap INTEGER, backlog_cap INTEGER, updated REAL)""")
        q("""CREATE TABLE IF NOT EXISTS ml_state (comp_id INTEGER PRIMARY KEY, cool_until REAL, cool_reason TEXT, cool_n INTEGER DEFAULT 0,
             plan_held TEXT, recovered INTEGER DEFAULT 0, recovered_at REAL, tick REAL)""")
        q("""CREATE TABLE IF NOT EXISTS ml_observed (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, kind TEXT, task_id INTEGER, key TEXT,
             text TEXT, ts REAL, outcome TEXT, outcome_at REAL)""")
        q("CREATE INDEX IF NOT EXISTS ml_observed_c ON ml_observed (comp_id, id)")
        for table, cols in (("mw_tasks", "retries INTEGER DEFAULT 0, retry_at REAL, fail_class TEXT"), ("mw_runs", "fail_class TEXT"), ("ml_policy", "mode TEXT")):
            have = {c["name"] for c in q(f"PRAGMA table_info({table})")}
            for col in cols.split(", "):
                if col.split()[0] not in have: q(f"ALTER TABLE {table} ADD COLUMN {col}")
        self.leases, self.lk, self.ticked = {}, threading.Lock(), 0.0
        self._recover()

    # ---------- policy and state ----------
    def policy(self, w):
        p = self.db.q("SELECT * FROM ml_policy WHERE comp_id=?", (w["id"],), one=True) or {}
        budget = BUDGET if w["budget"] is None else w["budget"]
        parallel = w["parallel"] or 4
        auto_cap = max(TASK_CAP_MIN, int(budget * 0.15)) if budget else 0
        return {"reserve": RESERVE if p.get("reserve") is None else p["reserve"], "retries": RETRIES if p.get("retries") is None else p["retries"],
                "task_cap": auto_cap if p.get("task_cap") is None else p["task_cap"], "task_cap_auto": p.get("task_cap") is None,
                "total_cap": p.get("total_cap") or 0,
                "queue_cap": parallel * QUEUE_PER_SLOT if p.get("queue_cap") is None else p["queue_cap"], "queue_cap_auto": p.get("queue_cap") is None,
                "backlog_cap": max(BACKLOG_MIN, parallel * 4) if p.get("backlog_cap") is None else p["backlog_cap"], "backlog_cap_auto": p.get("backlog_cap") is None,
                "budget": budget, "parallel": parallel}

    def _state(self, wid):
        return self.db.q("SELECT * FROM ml_state WHERE comp_id=?", (wid,), one=True) or {"comp_id": wid, "cool_until": None, "cool_reason": None,
                                                                                          "cool_n": 0, "plan_held": None, "recovered": 0, "recovered_at": None}

    def _set(self, wid, **kw):
        self.db.q("INSERT OR IGNORE INTO ml_state (comp_id) VALUES (?)", (wid,))
        self.db.q(f"UPDATE ml_state SET {', '.join(f'{k}=?' for k in kw)} WHERE comp_id=?", (*kw.values(), wid))

    def _comp(self, wid):
        return self.db.q("SELECT * FROM mw_comps WHERE id=?", (wid,), one=True)

    def _routes(self, c, a):
        """Where one agent's work can run (D-038 B3). plans: the plan providers it can go to; alt: those with a live model of
        ALT_TIER or more; other: a live model of that tier billed per token; routed: the router picks (an Auto agent on an Auto
        campaign with a live pool model, agent_core.route). A model the agent or campaign picked, or no live pool, is one plan
        or none, as before."""
        hub = self.w.m.hub
        if hub and (a.get("model") or "auto") == "auto" and (c["settings"].get("model") or "auto") == "auto":
            try: pool = model_router.effective((agent_core.pool(c["user_id"]) or {}).get("pool"))
            except Exception: pool = []  # noqa: BLE001 - the governor never fails on routing: as before
            live = [e for e in pool if hub.llm.configured(e["model"].partition(":")[0])]
            if live:
                prov = lambda e: e["model"].partition(":")[0]
                strong = [e for e in live if e["tier"] >= ALT_TIER]
                return {"plans": {prov(e) for e in live} & set(PLAN_PROVIDERS), "alt": {prov(e) for e in strong} & set(PLAN_PROVIDERS),
                        "other": any(prov(e) not in PLAN_PROVIDERS for e in strong), "routed": True}
        pp = (self.w._model(c, a) or "").partition(":")[0]
        return {"plans": {pp} & set(PLAN_PROVIDERS), "alt": set(), "other": False, "routed": False}

    def routes(self, w):
        """_routes() of every active agent of the team."""
        try: c = self.w.m._campaign(w["campaign_id"])
        except HTTPException: return []
        return [self._routes(c, a) for a in self.w._agents(w["id"]) if a["active"]]

    def on_plan(self, w, routes=None):
        """The plan providers the team's active agents can run on: "terminal" (the owner's Claude plan) and/or "codex" (their
        ChatGPT plan); empty when none do. Auto agents count every plan their pool routes to (D-038 B3)."""
        used = set().union(*(r["plans"] for r in (self.routes(w) if routes is None else routes)))
        return [p for p in PLAN_PROVIDERS if p in used]

    def _routed_elsewhere(self, wid, agent_id, pp):
        """True when this agent's work is routed, plan `pp` shows its limit on the owner's clock (so the router skips it now,
        B1) and, with the clocks as they stand, the team isn't held for a plan limit on its account (plan_hold): a free plan
        model of ALT_TIER, or such a per-token model, can take it (D-038 B3). Anything else: False, the team waits as before."""
        w = self._comp(wid)
        if not w or not agent_id or not quota_until(pp, self._owner(w)): return False
        try: c = self.w.m._campaign(w["campaign_id"])
        except HTTPException: return False
        a = next((x for x in self.w._agents(wid) if x["id"] == agent_id), None)
        if not a: return False
        r = self._routes(c, a)
        if not r["routed"]: return False
        owner = self._owner(w)
        return self.plan_hold([r], {pp: quota_until(pp, owner) for pp in r["plans"]})[0] is None

    @staticmethod
    def plan_hold(routes, waits):
        """(plan, until) a plan's usage limit holds the team for, else (None, 0). waits: {plan: quota_until}. An agent on a
        picked plan that waits holds the team, as before. Routed work holds it only when no free plan model of ALT_TIER and
        no such per-token model can take it, and then until the first of its plans resets (D-038 B3)."""
        hold = []
        for r in routes:
            w8 = {pp: waits.get(pp, 0) for pp in r["plans"]}
            if not w8 or not any(w8.values()): continue
            if r["routed"]:
                if r["other"] or any(not waits.get(pp, 0) for pp in r["alt"]): continue
                waiting = {pp: u for pp, u in w8.items() if u}
                pp = min(waiting, key=waiting.get)
            else:
                pp = max(w8, key=w8.get)
            hold.append((w8[pp], pp))
        if not hold: return None, 0
        until, pp = max(hold)
        return pp, until

    def _owner(self, w):
        """The team's owner: their own Claude Code / Codex login (cli_accounts.py), when connected, is the plan its agents use."""
        try: return self.w.m._campaign(w["campaign_id"])["user_id"] if w else None
        except HTTPException: return None

    # ---------- the governor ----------
    def gate(self, wid, w=None):
        """The five checks before work starts. tasks/reviews/plans say what may start; checks explain each."""
        w = w or self._comp(wid)
        if not w: return {"tasks": False, "reviews": False, "plans": False, "checks": [], "title": "", "reason": ""}
        p, now, q = self.policy(w), time.time(), self.db.q
        budget, reserve = p["budget"], p["reserve"]
        day = self.w.day_tokens(wid)
        line = budget * (1 - reserve / 100) if budget else None
        st = self._state(wid)
        total = q("SELECT COALESCE(SUM(tokens),0) n FROM mw_runs WHERE comp_id=?", (wid,), one=True)["n"] if p["total_cap"] else None
        recent = [r["tokens"] for r in q("""SELECT tokens FROM mw_runs WHERE comp_id=? AND kind='task' AND status='done' AND tokens>0
                                             ORDER BY id DESC LIMIT 20""", (wid,))]
        expected = int(statistics.median(recent)) if len(recent) >= 3 else None
        room = int(line - day) if line is not None else None
        running = q("SELECT COUNT(*) n FROM mw_runs WHERE comp_id=? AND status='running'", (wid,), one=True)["n"]
        cooling = st["cool_until"] and st["cool_until"] > now
        routes = self.routes(w)
        plans = self.on_plan(w, routes)
        waits = {pp: quota_until(pp, self._owner(w)) for pp in plans}  # one team hit a plan's limit: every team on that plan waits
        held, plan_wait = self.plan_hold(routes, waits)  # D-038 B3: not while the router can send the work to a free model
        waiting = [pp for pp in plans if waits[pp]]
        free = [pp for pp in plans if not waits[pp]] or plans
        cap = min((plan_parallel(pp) for pp in free), default=None)
        slots = min(p["parallel"], cap) if cap else p["parallel"]  # the CLI runs this many turns at once
        short = lambda n: f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.0f}k" if n >= 1e3 else str(int(n))
        C = []
        add = lambda key, label, ok, detail, level="ok", until=None: C.append({"key": key, "label": label, "ok": ok, "detail": detail, "level": level if not ok else "ok", "until": until})
        if not budget: add("budget", "Team budget", True, "No daily cap.")
        elif day >= budget: add("budget", "Team budget", False, f"{short(day)} of {short(budget)} tokens in 24 hours: spent. Nothing starts until older runs leave the window.", "stop")
        elif day >= line: add("budget", "Team budget", False, f"{short(day)} of {short(budget)}: only the {reserve:g}% reserve is left, kept for reviews of finished work.", "warn")
        else: add("budget", "Team budget", True, f"{short(day)} of {short(budget)} today; new tasks stop at {short(line)}.")
        if p["total_cap"]: add("total", "Competition budget", total < p["total_cap"], f"{short(total)} of {short(p['total_cap'])} tokens over the competition so far.", "stop")
        else: add("total", "Competition budget", True, "No lifetime cap.")
        if plan_wait: add("provider", "Model provider", False, f"The {PLAN_NAME[held]}'s usage limit is reached: {'Codex' if held == 'codex' else 'Terminal'} work resumes at {_hm(plan_wait)}.", "stop", until=plan_wait)
        elif cooling: add("provider", "Model provider", False, f"{st['cool_reason'] or 'Cooling down'}: work resumes at {_hm(st['cool_until'])}.", "stop", until=st['cool_until'])
        elif waiting: add("provider", "Model provider", True, f"The {PLAN_NAME[waiting[0]]}'s usage limit is reached until "
                          f"{_hm(waits[waiting[0]])}: meanwhile the router sends work to the pool's other models.", until=waits[waiting[0]])
        else: add("provider", "Model provider", True, "No refusals or rate limits lately.")
        if expected is None or room is None: add("fit", "Next task fits", True, "Not enough finished runs to estimate yet." if expected is None else f"A task run costs about {short(expected)}.")
        elif room >= expected: add("fit", "Next task fits", True, f"A task run costs about {short(expected)}; {short(room)} left before the reserve.")
        else: add("fit", "Next task fits", False, f"A task run costs about {short(expected)}, only {short(max(room, 0))} left before the reserve.", "warn")
        add("slot", "Free slot", running < slots, f"{running} of {slots} at work" + (f" (the {PLAN_NAME[min(free, key=plan_parallel)]} runs {cap} at once)." if slots < p["parallel"] else "."), "info")
        ok = {c["key"]: c["ok"] for c in C}
        spent = bool(budget) and day >= budget
        tasks = all(ok[k] for k in ("budget", "total", "provider", "fit"))
        reviews = not spent and ok["total"] and ok["provider"]
        bad = next((c for c in C if not c["ok"] and c["key"] != "slot"), None)
        return {"tasks": tasks, "reviews": reviews, "plans": tasks, "checks": C, "day": day, "budget": budget, "line": line, "room": room,
                "expected": expected, "total": total, "running": running, "cooling": bool(cooling or plan_wait), "plan": bool(plans), "plan_providers": plans, "slots": slots,
                "title": f"The governor holds new work: {bad['label'].lower()}" if bad else "", "reason": bad["detail"] if bad else ""}

    def capped(self, w, spent):
        cap = self.policy(w)["task_cap"]
        return bool(cap) and spent >= cap

    def guard(self, w, spent):
        cap = self.policy(w)["task_cap"]
        if cap and spent >= cap * 1.5:
            raise LookupError(f"Stopped at the task's token cap ({spent:,} of {cap:,} tokens) without filing: split the task or raise the cap in the Autoloop.")

    # ---------- the queue ----------
    def _backlog(self, wid):
        return self.db.q("""SELECT COUNT(*) n FROM mw_tasks WHERE comp_id=? AND (status IN ('queued','working')
                            OR (status='todo' AND agent_id IS NOT NULL AND hold IS NULL))""", (wid,), one=True)["n"]

    def enqueue_room(self, wid, w):
        cap = self.policy(w)["queue_cap"]
        if not cap: return 10_000
        n = self.db.q("SELECT COUNT(*) n FROM mw_tasks WHERE comp_id=? AND status='queued'", (wid,), one=True)["n"]
        return max(0, cap - n)

    def plan_held(self, wid, w):
        """Why the Director's scheduled plan waits, or ""."""
        p = self.policy(w)
        why = ""
        if p["backlog_cap"] and (n := self._backlog(wid)) >= p["backlog_cap"]:
            why = f"{n} tasks are already open: the Director plans when fewer than {p['backlog_cap']} are."
        elif not (g := self.gate(wid, w))["plans"]: why = g["reason"]
        if (self._state(wid)["plan_held"] or "") != why: self._set(wid, plan_held=why or None)
        return why

    def _blocked(self, wid):
        return self.db.q("SELECT COUNT(*) n FROM mw_tasks WHERE comp_id=? AND status='blocked'", (wid,), one=True)["n"]

    def followup_room(self, wid):
        """How many follow-ups one run may add: any number while the backlog is shallow, one at most while `backlog_cap` tasks
        are open, none while twice that many are. Blocked tasks count here (not in the Director's plan hold): a run that ends
        blocked and files follow-ups, whose runs end blocked in turn, grew a board without bound while they didn't (team 23,
        2026-11-18: 182 blocked). The board then shrinks until a person answers what waits."""
        w = self._comp(wid)
        cap = self.policy(w)["backlog_cap"]
        if not cap: return 99
        n = self._backlog(wid) + self._blocked(wid)
        return 0 if n >= 2 * cap else 1 if n >= cap else 99

    # ---------- failures ----------
    def failed(self, tid, rid, error, note):
        """Classifies a failed task run and handles what isn't the task's fault. True when it did (the caller skips counting it)."""
        k, now, q = classify(error), time.time(), self.db.q
        q("UPDATE mw_runs SET fail_class=? WHERE id=?", (k, rid))
        q("UPDATE mw_tasks SET fail_class=? WHERE id=?", (k, tid))
        t = q("SELECT comp_id, retries, title, agent_id FROM mw_tasks WHERE id=?", (tid,), one=True)
        if not t: return False
        wid = t["comp_id"]
        d = decide("failed", error, tries=t["retries"] or 0, key=f"mw:{tid}")
        if d["action"] == "stop" and d["cls"] in ("credential", "provider", "tool", "capability"):
            # G5-2 (Owner D-015): D1 not the agent's failure (not counted); D2 no blind retry: the task waits for the fix, with it
            q("""UPDATE mw_tasks SET status='blocked', question=?, note=?, updated=? WHERE id=? AND status='working'""",
              (f"{d['why']}. {d['remediation']} Then send it back to the queue.", f"Stopped, not counted: {_clip(error, 200)}", now, tid))
            if d["cls"] in ("credential", "provider"): self._cool(wid, "provider", error)  # nothing new starts on that login meanwhile
            self.w._event(wid, "pilot", f"Autoloop: “{_clip(t['title'], 80)}” stopped ({d['why'].lower()}); it waits for the fix, not counted against the agent")
            return True
        if k == "quota":  # the plan's limit lasts hours: wait for its reset instead of spending retries on it
            pp = "codex" if "codex" in (error or "").lower() else "terminal"  # llm.QuotaError names the CLI
            at = quota_until(pp, self._owner(self._comp(wid))) or now + 1800
            if self._routed_elsewhere(wid, t["agent_id"], pp):  # D-038 B3: the router skips that plan now (B1); the team goes on
                q("""UPDATE mw_tasks SET status='queued', note=?, updated=? WHERE id=? AND status='working'""",
                  (f"Back in the queue: the {PLAN_NAME[pp]}'s usage limit is reached until {_hm(at)}; "
                   "the router sends it to another model.", now, tid))
                self.w._event(wid, "pilot", f"Autoloop: the {PLAN_NAME[pp]}'s usage limit is reached until {_hm(at)}; "
                              f"“{_clip(t['title'], 80)}” goes back to the queue for another model, the team goes on")
                return True
            self._set(wid, cool_until=at, cool_reason=f"The {PLAN_NAME[pp]}'s usage limit is reached")
            q("""UPDATE mw_tasks SET status='queued', note=?, updated=? WHERE id=? AND status='working'""",
              (f"Back in the queue: the {PLAN_NAME[pp]}'s usage limit is reached; it resumes at {_hm(at)}.", now, tid))
            self.w._event(wid, "pilot", f"Autoloop: the {PLAN_NAME[pp]}'s usage limit is reached; nothing new starts until {_hm(at)}")
            return True
        if k in ("provider", "rate"): self._cool(wid, k, error)
        if k == "budget":
            # G5-2 budget safety (Owner decision 2026-11-11; the 199-run staging incident): a budget refusal is orchestrator.decide's
            # HOLD, never a requeue. The task stays out of the queue with the refusing limit and its release condition on record;
            # the board's start loop puts it back only after a fresh agent_core.preflight passes. Not counted against the agent.
            info = self.w.budget_hold_info(wid, {**(q("SELECT * FROM mw_tasks WHERE id=?", (tid,), one=True) or {"id": tid}), "comp_id": wid},
                                           self._owner(self._comp(wid)), error)
            from .mining_work import _budget_note
            q("""UPDATE mw_tasks SET status='todo', hold='budget', hold_info=?, note=?, updated=? WHERE id=? AND status='working'""",
              (json.dumps(info), _budget_note(info), now, tid))
            self.w._event(wid, "pilot", f"Autoloop: “{_clip(t['title'], 80)}” held by budget ({info.get('scope')}); not counted, not retried until it frees up")
            return True
        if k == "provider":
            q("""UPDATE mw_tasks SET status='queued', note=?, updated=? WHERE id=? AND status='working'""",
              ("Back in the queue: the model provider refused it; the team cools down.", now, tid))
            return True
        if k in ("rate", "transient"):
            w = self._comp(wid)
            n = t["retries"] or 0
            if w and n < self.policy(w)["retries"]:
                at = now + max(d["delay"], 1)  # G5-2 (Owner A): a timeout retries shortly, a rate limit waits longer; both jittered
                q("""UPDATE mw_tasks SET status='todo', hold='retry', retry_at=?, retries=retries+1, note=?, updated=? WHERE id=? AND status='working'""",
                  (at, f"Retry {n + 1} of {self.policy(w)['retries']} at {_hm(at)}: {_clip(error, 200)}", now, tid))
                return True
        return False

    def _cool(self, wid, k, error):
        st, now = self._state(wid), time.time()
        n = (st["cool_n"] or 0) + 1 if st["cool_until"] and st["cool_until"] > now - 3600 else 1
        span = min(COOL_PROVIDER * 2 ** (n - 1), 7200) if k == "provider" else min(COOL_RATE * 2 ** (n - 1), 1800)
        reason = ("The model provider refused the key or the account is out of credit" if k == "provider" else "The model provider is rate-limiting")
        self._set(wid, cool_until=now + span, cool_reason=reason, cool_n=n)
        self.w._event(wid, "pilot", f"Autoloop: {reason.lower()}; nothing new starts for {span // 60} min ({_clip(error, 160)})")

    def clear_cool(self, me, wid):
        self.w._own(me, wid)
        self._set(wid, cool_until=None, cool_reason=None, cool_n=0)
        self.w._event(wid, "pilot", f"{me['username']} ended the Autoloop's cooldown")
        self.w._kick(wid)
        return self.view(me, wid)

    # ---------- one agent per file ----------
    def lease(self, wid, path, rid, name):
        with self.lk:
            held = self.leases.get((wid, path))
            if held and held[0] != rid:
                r = self.db.q("SELECT status FROM mw_runs WHERE id=?", (held[0],), one=True)
                if r and r["status"] == "running":
                    raise HTTPException(409, f"{held[1]} is editing {path} right now: work on another file, or read it later and build on their version.")
            self.leases[(wid, path)] = (rid, name)
            if len(self.leases) > 2000:  # finished runs' leases
                live = {r["id"] for r in self.db.q("SELECT id FROM mw_runs WHERE status='running'")}
                self.leases = {k: v for k, v in self.leases.items() if v[0] in live}

    # ---------- the tick (from the autopilot thread) and recovery ----------
    def tick(self):
        now, q = time.time(), self.db.q
        due = q("""SELECT t.id FROM mw_tasks t JOIN mw_comps w ON w.id=t.comp_id WHERE t.status='todo' AND t.hold='retry' AND t.retry_at<=?
                   AND w.status!='closed'""", (now,))
        for t in due:
            q("UPDATE mw_tasks SET status='queued', hold=NULL, queued=?, updated=? WHERE id=? AND status='todo' AND hold='retry'", (now, now, t["id"]))
        # a queue moves when a run ends or autopilot ticks; this moves it when a budget frees up or a cooldown ends too, and
        # re-checks budget holds (G5-2: a board whose only tasks are held would otherwise never be checked again). A readiness
        # hold is re-checked here only while AXoR's own check for that team is under way (D-030, D-035; mission_ops.awaiting,
        # bounded in time and in restarts): found in staging on 2026-11-13, a task stayed held after its check had passed. Every
        # other readiness hold waits for an event or a person, as before: re-probing those every tick would start check runs
        # and real sign-in prompts for as long as the task stays held.
        try:
            from . import mission_ops
            waiting = sorted(mission_ops.awaiting())
        except Exception: waiting = []  # noqa: BLE001
        boards = q("""SELECT DISTINCT t.comp_id FROM mw_tasks t JOIN mw_comps w ON w.id=t.comp_id WHERE (t.status IN ('queued','checking')
                      OR (t.status='todo' AND t.hold='budget')) AND w.paused=0 AND w.status!='closed'""")
        if waiting:
            have = {r["comp_id"] for r in boards}
            boards = list(boards) + [r for r in q(f"""SELECT DISTINCT t.comp_id FROM mw_tasks t JOIN mw_comps w ON w.id=t.comp_id WHERE t.status='todo' AND t.hold='readiness'
                                                       AND w.paused=0 AND w.status!='closed' AND t.comp_id IN ({','.join('?' * len(waiting))})""", tuple(waiting))
                                     if r["comp_id"] not in have]
        for r in boards:
            try: self.w._kick(r["comp_id"])
            except Exception: pass  # noqa: BLE001 - the next tick tries again
        self.ticked = now

    def _recover(self):
        """Tasks a restart cut off (mining_work.py already put them back on the board as 'todo', with its note).
        - A task whose run was cut off goes under the transient retry rule (D-015 D2), as failed() does for a timeout: held for
          a counted, delayed retry while it has one left under the team's policy; with none left it stays parked for a person.
          On every team that isn't paused, closed or in observe mode, autopilot or not. Before (to 2026-11-13) such a task
          was put straight back in the queue on autopilot teams, uncounted, on every restart, and left for a person elsewhere.
        - A task that was only queued (nothing failed) goes back in the queue on autopilot teams, uncounted, as before."""
        now, q = time.time(), self.db.q
        live = """w.paused=0 AND w.status='active' AND w.id NOT IN (SELECT comp_id FROM ml_policy WHERE mode='observe') AND t.status='todo' AND t.hold IS NULL
                  AND t.agent_id IS NOT NULL AND t.note LIKE 'Stopped by a server restart%' AND t.updated>?"""
        cut = q(f"""SELECT t.id, t.comp_id, t.retries, t.title, (SELECT r.id FROM mw_runs r WHERE r.task_id=t.id AND r.kind='task' ORDER BY r.id DESC LIMIT 1) rid
                    FROM mw_tasks t JOIN mw_comps w ON w.id=t.comp_id WHERE {live}""", (now - 300,))
        runs = {r["id"]: r for r in q(f"SELECT id, error, finished FROM mw_runs WHERE id IN ({','.join('?' * len(cut))})", tuple(c["rid"] or 0 for c in cut))} if cut else {}
        cut = [c for c in cut if (runs.get(c["rid"]) or {}).get("error", "") and str(runs[c["rid"]]["error"]).startswith("Stopped by a server restart")
               and (runs[c["rid"]]["finished"] or 0) > now - 300]   # its run was cut off by THIS restart; the others were only queued
        again, parked = {}, {}
        for c in cut:
            w = self._comp(c["comp_id"])
            n, limit = c["retries"] or 0, (self.policy(w)["retries"] if w else 0)
            q("UPDATE mw_runs SET fail_class='transient' WHERE id=?", (c["rid"],))
            if n < limit:
                at = now + max(decide("failed", "Stopped by a server restart.", tries=n, key=f"mw:{c['id']}")["delay"], 1)
                if q("""UPDATE mw_tasks SET hold='retry', retry_at=?, retries=?, fail_class='transient', note=?, updated=? WHERE id=? AND status='todo' AND hold IS NULL RETURNING id""",
                     (at, n + 1, f"Retry {n + 1} of {limit} at {_hm(at)}: stopped by a server restart.", now, c["id"]), one=True):
                    again.setdefault(c["comp_id"], []).append(at)
            else:  # its retries are used: a restart doesn't start it again by itself (no loop)
                q("UPDATE mw_tasks SET fail_class='transient', note=?, updated=? WHERE id=? AND status='todo' AND hold IS NULL",
                  (f"Stopped by a server restart, and its {limit} automatic retr{'y is' if limit == 1 else 'ies are'} used: start it again.", now, c["id"]))
                parked[c["comp_id"]] = parked.get(c["comp_id"], 0) + 1
        for wid, ats in again.items():
            self.w._event(wid, "pilot", f"Autoloop: {len(ats)} task{'s' if len(ats) > 1 else ''} a server restart cut off retr{'y' if len(ats) > 1 else 'ies'} by "
                                        f"{'themselves' if len(ats) > 1 else 'itself'} at {_hm(min(ats))} (counted as a retry)")
        for wid, k in parked.items():
            self.w._event(wid, "pilot", f"Autoloop: {k} task{'s' if k > 1 else ''} a server restart cut off {'have' if k > 1 else 'has'} no automatic retry left: {'they wait' if k > 1 else 'it waits'} for you")
        skip = [c["id"] for c in cut] or [0]
        for r in q(f"""SELECT w.id, COUNT(t.id) n FROM mw_comps w JOIN mw_tasks t ON t.comp_id=w.id WHERE w.autopilot=1 AND {live}
                       AND t.id NOT IN ({','.join('?' * len(skip))}) GROUP BY w.id""", (now - 300, *skip)):
            q(f"""UPDATE mw_tasks SET status='queued', note='Back in the queue after a server restart.', queued=COALESCE(queued, ?), updated=?
                  WHERE comp_id=? AND status='todo' AND hold IS NULL AND agent_id IS NOT NULL AND note LIKE 'Stopped by a server restart%'
                  AND id NOT IN ({','.join('?' * len(skip))})""", (now, now, r["id"], *skip))
            self._set(r["id"], recovered=r["n"] + len(again.get(r["id"], [])), recovered_at=now); again.pop(r["id"], None)
            self.w._event(r["id"], "pilot", f"Autoloop put {r['n']} task{'s' if r['n'] > 1 else ''} a server restart cut off back in the queue")
        for wid, ats in again.items(): self._set(wid, recovered=len(ats), recovered_at=now)

    # ---------- observe mode ----------
    def observing(self, wid):
        r = self.db.q("SELECT mode FROM ml_policy WHERE comp_id=?", (wid,), one=True)
        return bool(r) and r["mode"] == "observe"

    def _would(self, wid, kind, tid, key, text):
        """One entry per decision: the same "would start #12" isn't logged again every tick while it's still open."""
        if self.db.q("SELECT 1 FROM ml_observed WHERE comp_id=? AND key=? AND outcome IS NULL", (wid, key), one=True): return False
        self.db.q("INSERT INTO ml_observed (comp_id, kind, task_id, key, text, ts) VALUES (?,?,?,?,?,?)", (wid, kind, tid, key, _clip(text, 300), time.time()))
        return True

    def observe(self, w, rows, lead):
        """Autopilot's step in observe mode (mining_work._pilot_one): records what it would start and whether it would have the
        Director plan, and does neither. Your own starts, plans and reviews run as usual."""
        wid, now, q = w["id"], time.time(), self.db.q
        new = 0
        for r in rows:
            t = q("SELECT t.title, a.name FROM mw_tasks t LEFT JOIN mw_agents a ON a.id=t.agent_id WHERE t.id=?", (r["id"],), one=True)
            if t: new += self._would(wid, "start", r["id"], f"start:{r['id']}", f"Start “{t['title']}” with {t['name'] or 'its agent'}")
        busy = q("""SELECT COUNT(*) n FROM mw_tasks WHERE comp_id=? AND (status IN ('queued','working','checking')
                    OR (status='todo' AND agent_id IS NOT NULL AND hold IS NULL))""", (wid,), one=True)["n"]
        since = now - (w["last_plan"] or 0)
        if lead and not self.plan_held(wid, w) and (since >= (w["plan_every"] or 6) * 3600 or (not busy and since >= PLAN_GAP)):
            new += self._would(wid, "plan", None, f"plan:{w['last_plan'] or 0}", f"Ask {lead['name']} to plan" + ("" if busy else ": the board ran dry"))
        if new: self._prune(wid)
        n = q("SELECT COUNT(*) n FROM ml_observed WHERE comp_id=? AND outcome IS NULL", (wid,), one=True)["n"]
        self.w._pilot_say(w, "Observe only: autopilot records what it would do and starts nothing" + (f" ({n} open in the Autoloop tab)." if n else "."))

    def would_review(self, wid, tid, rev):
        """In observe mode a finished task goes to you, not to its squad lead: logs who would have reviewed it. Returns None."""
        t = self.db.q("SELECT title FROM mw_tasks WHERE id=?", (tid,), one=True)
        self._would(wid, "review", tid, f"review:{tid}:{time.time():.0f}", f"Send “{(t or {}).get('title') or f'#{tid}'}” to {rev['name']} for review")
        return None

    def _prune(self, wid):
        q = self.db.q
        q("DELETE FROM ml_observed WHERE comp_id=? AND ts<?", (wid, time.time() - 30 * DAY))
        q("DELETE FROM ml_observed WHERE comp_id=? AND id NOT IN (SELECT id FROM ml_observed WHERE comp_id=? ORDER BY id DESC LIMIT 500)", (wid, wid))

    def _resolve(self, w):
        """Matches open entries against what happened since: you started that task, someone planned, its review ran."""
        wid, now, q = w["id"], time.time(), self.db.q
        for o in q("SELECT * FROM ml_observed WHERE comp_id=? AND outcome IS NULL", (wid,)):
            out = None
            if o["kind"] == "plan":
                if (w["last_plan"] or 0) > o["ts"]: out = "agreed"
            elif o["kind"] == "start":
                t = q("SELECT status, queued FROM mw_tasks WHERE id=?", (o["task_id"],), one=True)
                if not t: out = "gone"
                elif (t["queued"] or 0) > o["ts"]: out = "agreed"
            elif o["kind"] == "review":
                t = q("SELECT status FROM mw_tasks WHERE id=?", (o["task_id"],), one=True)
                if not t: out = "gone"
                elif q("SELECT 1 FROM mw_runs WHERE task_id=? AND kind='review' AND started>?", (o["task_id"], o["ts"]), one=True): out = "agreed"
                elif t["status"] not in ("review", "checking"): out = "yours"  # you reviewed it yourself
            if not out and now - o["ts"] > DAY: out = "differed"  # a day on, you hadn't done it
            if out: q("UPDATE ml_observed SET outcome=?, outcome_at=? WHERE id=?", (out, now, o["id"]))

    def _observed(self, w):
        self._resolve(w)
        rows = self.db.q("SELECT * FROM ml_observed WHERE comp_id=? ORDER BY id DESC LIMIT 40", (w["id"],))
        week = self.db.q("SELECT outcome, COUNT(*) n FROM ml_observed WHERE comp_id=? AND ts>? GROUP BY outcome", (w["id"], time.time() - 7 * DAY))
        n = {r["outcome"] or "open": r["n"] for r in week}
        decided = n.get("agreed", 0) + n.get("differed", 0)
        return {"mode": "observe" if self.observing(w["id"]) else "act", "entries": rows, "agreed": n.get("agreed", 0), "differed": n.get("differed", 0),
                "open": n.get("open", 0), "yours": n.get("yours", 0), "rate": n.get("agreed", 0) / decided if decided else None}

    def set_mode(self, me, wid, b):
        w, _ = self.w._own(me, wid)
        if b.mode == ("observe" if self.observing(wid) else "act"): return self.view(me, wid)
        self.db.q("INSERT OR IGNORE INTO ml_policy (comp_id) VALUES (?)", (wid,))
        self.db.q("UPDATE ml_policy SET mode=?, updated=? WHERE comp_id=?", (b.mode, time.time(), wid))
        if b.mode == "observe":
            self.w._event(wid, "pilot", f"{me['username']} set autopilot to observe only: it records what it would start, plan and review, and starts nothing")
        else:
            self.w._event(wid, "pilot", f"{me['username']} let autopilot act")
            # what it would have done is now its own doing: open entries close, so they never count as yours
            self.db.q("UPDATE ml_observed SET outcome='ended', outcome_at=? WHERE comp_id=? AND outcome IS NULL", (time.time(), wid))
            self.w._pilot_say(self._comp(wid), "")
        if w["autopilot"] and not w["paused"]: self.w.pool.submit(self.w._pilot_one, wid)
        return self.view(me, wid)

    # ---------- the user's actions ----------
    def set_policy(self, me, wid, b: PolicyIn):
        self.w._own(me, wid)
        sets = b.model_dump(exclude_unset=True)
        self.db.q("INSERT OR IGNORE INTO ml_policy (comp_id) VALUES (?)", (wid,))
        if sets: self.db.q(f"UPDATE ml_policy SET {', '.join(f'{k}=?' for k in sets)}, updated=? WHERE comp_id=?", (*sets.values(), time.time(), wid))
        self.w._event(wid, "settings", f"{me['username']} changed the Autoloop's " + ", ".join(sorted(k.replace("_", " ") for k in sets)) if sets else f"{me['username']} saved the Autoloop's rules")
        self.w._kick(wid)
        return self.view(me, wid)

    def spread(self, me, wid, b: SpreadIn):
        """Moves an agent's queue beyond its first `keep` tasks to idle squad-mates, one each in turn."""
        self.w._own(me, wid)
        a = self.w._agent_row(wid, b.agent)
        if not a: raise HTTPException(404, "There's no such agent on this team.")
        q = self.db.q
        open_ = lambda aid: q("SELECT COUNT(*) n FROM mw_tasks WHERE agent_id=? AND status IN ('todo','queued','working','checking')", (aid,), one=True)["n"]
        mates = [m for m in self.w._agents(wid) if m["id"] != a["id"] and m["active"] and not m["head"] and not m["lead"]
                 and (m["squad"] or "") == (a["squad"] or "") and open_(m["id"]) <= 1]
        if not mates: raise HTTPException(409, f"Nobody in {a['name']}'s squad is free to take some of the queue.")
        tasks = q("""SELECT id, title FROM mw_tasks WHERE comp_id=? AND agent_id=? AND (status='queued' OR (status='todo' AND hold IS NULL))
                     ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, id""", (wid, a["id"]))[b.keep:]
        moved = 0
        for i, t in enumerate(tasks[:len(mates) * 2]):
            m = mates[i % len(mates)]
            q("UPDATE mw_tasks SET agent_id=?, updated=? WHERE id=? AND status IN ('queued','todo')", (m["id"], time.time(), t["id"]))
            moved += 1
        if not moved: raise HTTPException(409, f"{a['name']} has no more than {b.keep} tasks waiting.")
        self.w._event(wid, "settings", f"{me['username']} spread {moved} of {a['name']}'s tasks over {', '.join(m['name'] for m in mates[:moved])}", agent=a["id"])
        self.w._kick(wid)
        return self.view(me, wid)

    # ---------- the view ----------
    def view(self, me, wid):
        w, c = self.w._own(me, wid)
        now, q = time.time(), self.db.q
        p, g, st = self.policy(w), self.gate(wid, w), self._state(wid)
        agents = {a["id"]: a for a in self.w._agents(wid)}
        name = lambda aid: agents[aid]["name"] if aid in agents else "someone"
        tasks = q("SELECT id, title, status, priority, agent_id, hold, fails, retries, retry_at, fail_class, queued, note FROM mw_tasks WHERE comp_id=?", (wid,))
        runs = q("SELECT id, kind, status, agent_id, task_id, tokens, started, finished, fail_class, error FROM mw_runs WHERE comp_id=? AND started>?", (wid, now - 7 * DAY))
        day = [r for r in runs if r["started"] > now - DAY]
        running = [r for r in runs if r["status"] == "running"]
        by = lambda *s: [t for t in tasks if t["status"] in s]
        notes_day = q("SELECT COUNT(*) n FROM mw_notes WHERE comp_id=? AND ts>?", (wid, now - DAY), one=True)["n"]
        notes_all = q("SELECT COUNT(*) n FROM mw_notes WHERE comp_id=?", (wid,), one=True)["n"]
        verified = q("SELECT COUNT(*) n FROM mw_tasks WHERE comp_id=? AND status='done' AND " + not_dropped(self.db) + " AND done_at>?", (wid, now - DAY), one=True)["n"]
        reviews = [r for r in day if r["kind"] == "review" and r["status"] == "done"]
        sent_back = q("SELECT COUNT(*) n FROM mw_events WHERE comp_id=? AND kind='revise' AND ts>?", (wid, now - DAY), one=True)["n"]
        plans = [r for r in day if r["kind"] == "plan"]
        last_plan = w["last_plan"]
        next_plan = (last_plan or 0) + (w["plan_every"] or 6) * 3600 if w["autopilot"] else None
        open_ = len([t for t in tasks if t["status"] in ("queued", "working") or (t["status"] == "todo" and t["agent_id"] is not None and not t["hold"])])

        # failures by class, last 24 hours
        fails = [r for r in day if r["status"] == "failed"]
        fc = {}
        for r in fails:
            k = "restart" if r["error"] == RESTART else r["fail_class"] or classify(r["error"])
            x = fc.setdefault(k, {"key": k, "label": LABEL[k], "policy": POLICY[k], "n": 0, "last": 0, "example": ""})
            x["n"] += 1
            if (r["finished"] or 0) >= x["last"]: x["last"], x["example"] = r["finished"] or 0, _clip(r["error"], 200)
        retrying = sorted(({"id": t["id"], "title": t["title"], "at": t["retry_at"], "n": t["retries"], "agent": name(t["agent_id"]), "cls": t["fail_class"]}
                           for t in tasks if t["status"] == "todo" and t["hold"] == "retry"), key=lambda x: x["at"] or 0)
        held = [{"id": t["id"], "title": t["title"], "agent": name(t["agent_id"]), "cls": t["fail_class"]} for t in tasks if t["status"] == "todo" and t["hold"] == "failed"]

        # the queue
        queued = by("queued")
        per = {}
        for t in tasks:
            if t["agent_id"] is not None and (t["status"] == "queued" or (t["status"] == "todo" and not t["hold"])): per[t["agent_id"]] = per.get(t["agent_id"], 0) + 1
        busy = {r["agent_id"] for r in running}
        free = [a for a in agents.values() if a["active"] and a["id"] not in busy]
        idle = lambda a: not per.get(a["id"]) and a["id"] not in busy
        piles = []
        for aid, n in sorted(per.items(), key=lambda x: -x[1]):
            if n < 4 or aid not in agents: continue
            a = agents[aid]
            mates = [m["name"] for m in agents.values() if m["id"] != aid and m["active"] and not m["head"] and not m["lead"]
                     and (m["squad"] or "") == (a["squad"] or "") and idle(m)]
            piles.append({"agent": aid, "name": a["name"], "n": n, "squad": a["squad"] or "", "mates": mates[:6]})
        oldest = min((t["queued"] for t in queued if t["queued"]), default=None)
        dupes = self._dupes([t for t in tasks if t["status"] in ("todo", "queued") and t["hold"] != "retry"], name)

        # economics
        tok = lambda rs: sum(r["tokens"] or 0 for r in rs)
        filed = [r for r in day if r["kind"] == "task" and r["status"] == "done"]
        kinds = {}
        for r in day: kinds[r["kind"]] = kinds.get(r["kind"], 0) + (r["tokens"] or 0)
        week = []
        for i in range(6, -1, -1):
            lo, hi = now - (i + 1) * DAY, now - i * DAY
            week.append({"tokens": tok(r for r in runs if lo < r["started"] <= hi),
                         "verified": q("SELECT COUNT(*) n FROM mw_tasks WHERE comp_id=? AND status='done' AND " + not_dropped(self.db) + " AND done_at>? AND done_at<=?", (wid, lo, hi), one=True)["n"]})
        econ = {"tokens": tok(day), "runs": len(day), "per_run": tok(day) // len(day) if day else None,
                "filed": len(filed), "per_filed": tok(day) // len(filed) if filed else None,
                "verified": verified, "per_verified": tok(day) // verified if verified else None, "kinds": kinds, "week": week,
                "fail_share": len(fails) / len(day) if day else 0, "wasted": tok(fails)}

        # the cycle
        obs = self._observed(w)
        watching = obs["mode"] == "observe" and bool(w["autopilot"])
        kinds_running = {r["kind"] for r in running}
        recs = self._advice(w, p, g, fc, piles, dupes, open_, agents, day)
        stages = {
            "observe": {"active": True, "line": f"Checks the team every 15 s; last {int(now - self.ticked)} s ago" if self.ticked else "Checks the team every 15 s",
                        "n": open_, "unit": "open"},
            "plan": {"active": "plan" in kinds_running, "line": "The Director is planning" if "plan" in kinds_running else
                     ((st["plan_held"] if w["autopilot"] else "") or (f"Next plan {'due' if next_plan and next_plan <= now else 'at ' + _hm(next_plan)}" if next_plan else "Autopilot is off: you plan")),
                     "n": len(plans), "unit": "plans today", "held": bool(st["plan_held"]) and bool(w["autopilot"])},
            "execute": {"active": "task" in kinds_running, "line": f"{sum(r['kind'] == 'task' for r in running)} at work, {len(queued)} queued, {p['parallel']} slots",
                        "n": len(filed), "unit": "filed today", "held": not g["tasks"]},
            "verify": {"active": "review" in kinds_running, "line": f"{len(by('checking'))} with reviewers, {len(by('review'))} with you; {sent_back} sent back today",
                       "n": len(reviews), "unit": "reviews today"},
            "learn": {"active": notes_day > 0, "line": f"{notes_all} findings in the notebook", "n": notes_day, "unit": "new today"},
            "optimize": {"active": bool(recs), "line": f"{len(recs)} suggestion{'s' if len(recs) != 1 else ''}" if recs else "Nothing to change", "n": len(recs), "unit": "suggestions"},
            "repeat": {"active": bool(w["autopilot"]) and not w["paused"], "line": ("Paused" if w["paused"] else "Observe only: records what it would do" if watching else "Runs again on its own" if w["autopilot"] else "Off: switch autopilot on"),
                       "n": len(retrying), "unit": "retries waiting"},
        }
        rules = [
            {"key": "classify", "on": True, "text": "Never retry a failed task without classifying its failure", "detail": "Every failed run gets a class; the class decides what happens."},
            {"key": "retry", "on": p["retries"] > 0, "text": f"Retry transient failures only, {p['retries']} time{'s' if p['retries'] != 1 else ''} at most",
             "detail": "Timeouts, restarts, rate limits and server errors retry after 1, 4 and 16 minutes; the task's own failures don't."},
            {"key": "budget", "on": True, "text": "No retries or new work while the budget is spent", "detail": "Work waits in the queue instead of failing."},
            {"key": "lease", "on": True, "text": "One agent edits a file at a time", "detail": "A file another running agent wrote is refused until that run ends."},
            {"key": "observe", "on": watching, "text": "Autopilot only observes" if watching else "Autopilot acts on its own",
             "detail": "It records what it would start, plan and review and starts nothing; you compare before you let it act." if watching
             else "Switch it to observe only to see what it would do before trusting it." if w["autopilot"] else "Autopilot is off."},
            {"key": "verify", "on": bool(w["autopilot"]) and not watching, "text": "Independent review before work counts", "detail": "Observe only: finished work comes to you; the log says who would have reviewed it." if watching
             else "Squad leads review on autopilot; you review the rest." if w["autopilot"] else "Autopilot is off: you review every result."},
            {"key": "compare", "on": True, "text": "Compare candidate miners on the same tasks", "detail": "The Lab scores each commit against the base on the same eval set.", "go": "lab"},
            {"key": "approval", "on": True, "text": "Nothing is uploaded or promoted without your approval", "detail": "Agents only read, draft and test; uploads, registration and payments are yours."},
        ]
        return {"comp": wid, "at": now, "autopilot": bool(w["autopilot"]), "paused": bool(w["paused"]), "status": w["status"],
                "policy": p, "gate": g, "observe": obs, "stages": stages, "stage_order": STAGES, "rules": rules, "advice": recs,
                "queue": {"queued": len(queued), "open": open_, "running": len([r for r in running if r["kind"] == "task"]), "slots": p["parallel"],
                          "free_agents": len(free), "agents": sum(1 for a in agents.values() if a["active"]), "oldest": oldest,
                          "piles": piles[:8], "dupes": dupes[:8], "queue_cap": p["queue_cap"], "backlog_cap": p["backlog_cap"],
                          "ready": len([t for t in tasks if t["status"] == "todo" and t["agent_id"] is not None and not t["hold"]])},
                "failures": {"classes": sorted(fc.values(), key=lambda x: -x["n"]), "total": len(fails), "retrying": retrying[:12], "held": held[:12]},
                "economics": econ,
                "recovery": {"recovered": st["recovered"] or 0, "at": st["recovered_at"], "cool_until": st["cool_until"] if g["cooling"] else None,
                             "cool_reason": st["cool_reason"] if g["cooling"] else None}}

    def _dupes(self, tasks, name):
        ws = [(t, _words(t["title"])) for t in tasks]
        out, seen = [], set()
        for i, (t, a) in enumerate(ws):
            if t["id"] in seen or len(a) < 2: continue
            group = [t]
            for u, b in ws[i + 1:]:
                if u["id"] in seen or len(b) < 2: continue
                if len(a & b) / len(a | b) >= 0.75: group.append(u); seen.add(u["id"])
            if len(group) > 1:
                seen.add(t["id"])
                out.append([{"id": x["id"], "title": x["title"], "agent": name(x["agent_id"]), "status": x["status"]} for x in group])
        return out

    def _advice(self, w, p, g, fc, piles, dupes, open_, agents, day):
        R = []
        add = lambda key, level, title, detail, act=None: R.append({"key": key, "level": level, "title": title, "detail": detail, "act": act})
        plans = g.get("plan_providers") or []
        cap = min((plan_parallel(pp) for pp in plans), default=0)
        if plans and p["parallel"] > cap:
            pp = min(plans, key=plan_parallel)
            tip = ("Opus for the Director and reviews, Sonnet or Haiku for field agents, stretches the quota." if pp == "terminal" else
                   "A smaller model at low effort for field agents stretches the quota.")
            add("plan", "info", f"Let {cap} work at once instead of {p['parallel']}",
                f"This team runs on your {PLAN_NAME[pp]}, which takes {cap} at a time and shares its quota with your own "
                f"{'Claude Code' if pp == 'terminal' else 'Codex'}: the others only wait. {tip}", {"kind": "parallel", "value": cap})
        rate = next((x["n"] for x in fc.values() if x["key"] == "rate"), 0)
        if rate >= 3 and p["parallel"] > 2:
            n = max(2, p["parallel"] - 2)
            add("parallel", "warn", f"Let {n} work at once instead of {p['parallel']}", f"{rate} runs hit rate limits today: fewer at once finish more.", {"kind": "parallel", "value": n})
        if g["budget"] and g["day"] >= (g["line"] or 0):
            add("budget", "warn", "The budget runs out before the day does",
                "Raise the team's budget, share a pool from My subnets → Teams, or plan less often." + (f" A task costs about {g['expected']:,} tokens." if g["expected"] else ""), {"kind": "edit"})
        if p["backlog_cap"] and open_ >= p["backlog_cap"]:
            add("backlog", "info", f"{open_} tasks are open: planning waits",
                "Work the backlog down before the Director adds more" + (f"; {sum(len(d) - 1 for d in dupes)} look like duplicates." if dupes else "."), {"kind": "queue"})
        elif dupes: add("dupes", "info", f"{sum(len(d) - 1 for d in dupes)} open tasks look like duplicates", "Delete the extra copies so the same work isn't paid for twice.", {"kind": "queue"})
        for x in piles[:2]:
            if x["mates"]: add(f"pile{x['agent']}", "info", f"{x['name']} has {x['n']} tasks waiting", f"Idle in the same squad: {', '.join(x['mates'][:4])}.", {"kind": "spread", "agent": x["agent"]})
        stats = {}
        for r in day:
            if r["kind"] != "task" or r["agent_id"] not in agents: continue
            s = stats.setdefault(r["agent_id"], [0, 0])
            s[0 if r["status"] == "done" else 1] += r["status"] in ("done", "failed")
        for aid, (ok, bad) in stats.items():
            if bad >= 3 and not ok:
                add(f"agent{aid}", "warn", f"{agents[aid]['name']} failed {bad} runs today and finished none", "Check its model and instructions, or switch it off.", {"kind": "agent", "agent": aid})
        task_fails = next((x["n"] for x in fc.values() if x["key"] == "task"), 0)
        if task_fails >= 3: add("task", "info", f"{task_fails} runs failed on the task itself", "Too big or unclear tasks: split them, or give them a clearer detail.", {"kind": "errors"})
        if (cap := next((x["n"] for x in fc.values() if x["key"] == "cap"), 0)): add("cap", "info", f"{cap} runs stopped at the token cap", "Split those tasks, or raise the per-task cap below.", {"kind": "policy"})
        return R


def build(work, require):
    r = APIRouter(prefix="/api/mining/work")
    gate = work.m.hub.gate if work.m.hub else (lambda me: me)
    user = lambda req: gate(require(req))
    lp = Loop(work)
    work.loop = lp
    r.state = {"loop": lp}

    @r.get("/comps/{wid}/autoloop")
    def view(wid: int, req: Request): return lp.view(user(req), wid)

    @r.put("/comps/{wid}/autoloop/policy")
    def policy(wid: int, b: PolicyIn, req: Request): return lp.set_policy(user(req), wid, b)

    @r.post("/comps/{wid}/autoloop/spread")
    def spread(wid: int, b: SpreadIn, req: Request): return lp.spread(user(req), wid, b)

    @r.put("/comps/{wid}/autoloop/mode")
    def mode(wid: int, b: ModeIn, req: Request): return lp.set_mode(user(req), wid, b)

    @r.post("/comps/{wid}/autoloop/cooldown/clear")
    def clear(wid: int, req: Request): return lp.clear_cool(user(req), wid)

    return r
