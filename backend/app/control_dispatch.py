"""The Control Hub's task dispatcher: Mission Planner → Dispatcher → team board or agent, so a mission's open tasks move.

Before it, nothing picked up a Control Hub task that wasn't started by hand: the competition template's fixed tasks were
seeded as 'todo' with no board task, Mission Intelligence's agent tasks were made with start=False, and a server restart
turned running tasks back into 'todo' ("start it again"). The Command Center then showed open tasks with none in progress.

In Hybrid and Auto mode ("AXoR assigns tasks to agents itself"), every DISPATCH_EVERY seconds, per user:
- an undispatched task (todo, no board task or mission yet) made by AXoR (the template, Mission Intelligence, a recurring
  task due again, an approved proposal) or stopped by a restart goes out: board tasks onto the team's board (its Director
  hands them out), agent tasks to their agent (or one picked from the team) within the user's runs at once (RUNS_PER_USER).
  A task you made without starting it stays yours to start.
- a failed agent task is retried by policy: failures outside the work (restart, quota, provider, rate limit, timeout,
  sandbox, tool) run again on the same agent, up to MAX_TRIES with a growing wait; a budget or cap refusal is never retried
  (a limit is a decision); the task's own failure waits for you.
- an agent task that ended without a deliverable (control_hub._run_task: "done" with no real result) goes to another agent
  of the team once, then waits for you.
Manual mode dispatches nothing. Nothing here registers, deploys or submits: those stay the user's on every path.

why() names, for every open task, why it isn't moving (or that it is), and summary() counts them for the Command Center and
the Intelligence layers' Task dispatch part, so "14 open, 0 in progress" comes with its reasons.
"""
import json, logging, os, re, threading, time

from fastapi import HTTPException

from . import mission_ops as mo, task_lifecycle as tl

log = logging.getLogger("scout.control.dispatch")
ENABLED = os.getenv("CONTROL_DISPATCH", "1") == "1"
DISPATCH_EVERY = max(10, int(os.getenv("CONTROL_DISPATCH_EVERY", "60") or 60))  # seconds between passes
MAX_TRIES = 3            # automatic retries, reassignments and failed dispatches per task
RETRY_AFTER = 300        # seconds before retry n (× n)
WAIT = {"quota": 3600, "provider": 1800}  # a plan's usage limit or a provider refusal lasts longer than a glitch
PER_PASS = 8             # board dispatches per user per pass
RECENT = 86400           # a failure older than this isn't retried (the first deploy doesn't revive old history)
STALE = 3600             # an open task that hasn't moved for this long is stuck
EMPTY = {"", "-", "n/a", "na", "none", "nothing", "todo", "tbd", "null", "done", "ok"}  # a "done" agent task's result that delivers nothing
RESTARTED = "Stopped by a server restart"
NO_DELIVERABLE = "Finished without a deliverable"
RESEARCHING = "Being researched first"  # task_research.py: a fixed task waits for its Intelligence brief, minutes at most
from .orchestrator import DISPATCH_NEVER as NEVER, DISPATCH_RETRY as RETRY  # noqa: E402  one taxonomy (G5 Phase 1): outside the work → run it again; a limit is a decision, not a glitch
PRI = {"high": 0, "medium": 1, "low": 2}
_last = {}               # user id → last pass (time, result)
_lock = threading.Lock()


def ensure_schema(db):
    cols = {c["name"] for c in db.q("PRAGMA table_info(ctl_tasks)")}
    for name, ddl in [("attempts", "INTEGER DEFAULT 0"), ("next_try", "REAL"), ("retry_claim", "TEXT"), ("claimed_at", "REAL")]:  # claim: G5-2
        if name not in cols: db.q(f"ALTER TABLE ctl_tasks ADD COLUMN {name} {ddl}")
    from . import task_lifecycle
    task_lifecycle.ensure_schema(db)  # run_key (one run per start), accept/outputs (the contract), verify (the checks' report)


def _j(s, d=None):
    try: return json.loads(s) if s else d
    except (TypeError, ValueError): return d


def _hist(r, what, by="AXoR"):
    return json.dumps(((_j(r["history"], []) or []) + [{"ts": time.time(), "by": by, "what": what}])[-40:])


def _cls(summary):
    from .intel_layers import fail_class
    return fail_class("failed", summary or "")


def _budget(ch, me, r, key):
    """agent_core.preflight for a Control Hub agent task about to be dispatched to `key`: the run's own system, agent, ref
    ctl:t<id> and mission. None (ALLOW) when it may start; else the refusal (decision REFUSE) or unknown() (decision UNKNOWN)."""
    if not key: return None
    from . import agent_core
    try:
        p = ch.persona(me, key)
        system = p["system"] if p.get("system") in agent_core.SYSTEMS else "other"
    except Exception:  # noqa: BLE001 - an unknown agent: the generic system
        system = "other"
    ref = f"ctl:t{r['id']}"
    return agent_core.preflight(me["id"], system, agent_key=key, ref=ref, corr=r.get("mission") or ref, contract=ref)


def _budget_hold(ch, r, refused, out):
    """A dispatch the budget check didn't allow: the task stays where it is, its summary says why (the same text every pass, so
    the history gets one line per change, with the error and time for an UNKNOWN), no attempt is used, nothing starts."""
    from . import agent_core
    if agent_core.is_unknown(refused):
        text = f"Held: {agent_core.VERIFY}; it starts after a successful check. Not counted against the agent."
        what = f"held: budget verification failed ({refused.get('error') or 'no answer'})"[:300]
        out["budget_unknown"] = out.get("budget_unknown", 0) + 1
    else:
        text = f"Held by budget ({refused['scope']}): {refused['reason']} Not counted against the agent."
        what = "held by budget"
        out["budget_held"] = out.get("budget_held", 0) + 1
    if (r["summary"] or "") != text: _note(ch, r, what, {"summary": text})


def _budget_hold_retry(ch, r, refused, out):
    """A retry or correction the budget check didn't allow: it stays failed (or needing input) with its own summary, which the
    retry decision reads, so only the counts and the history line record it; no attempt is used, nothing starts."""
    from . import agent_core
    unk = agent_core.is_unknown(refused)
    out["budget_unknown" if unk else "budget_held"] = out.get("budget_unknown" if unk else "budget_held", 0) + 1
    what = (f"retry held: budget verification failed ({refused.get('error') or 'no answer'})" if unk
            else f"retry held by budget ({refused['scope']})")[:300]
    hist = _j(r.get("history"), []) or []
    if not hist or hist[-1].get("what") != what:
        ch.db.q("UPDATE ctl_tasks SET history=? WHERE id=?", (_hist(r, what), r["id"]))


def _readiness(ch, uid, r):
    """mission_ops.task_readiness for a Control Hub agent task (its team's competition, when it has one, for the sign-in check)."""
    if not mo.GATE_ON: return None
    comp = None
    m = re.fullmatch(r"comp:(\d+)", r.get("mission") or "")
    if m and ch._has("mw_comps"): comp = ch.db.q("SELECT * FROM mw_comps WHERE id=?", (int(m.group(1)),), one=True)
    return mo.task_readiness(ch, uid, comp, r, r.get("mission"), f"ctl:t{r['id']}")


CLAIM_STALE = 600  # a retry claimed but never started (the worker died in between) can be claimed again after this


def _claim(ch, r, key, now):
    """The atomic claim of one retry (G5-2, Owner review 2026-11-11 §2A): a conditional UPDATE in the database, so of any number of
    dispatcher passes (threads, workers, pods) only the first to write this retry's key wins. The claim holds while the task is
    still the failed attempt it was read as; a claim left behind by a pass that died before it started the run expires after
    CLAIM_STALE and can be taken again."""
    return bool(ch.db.q("""UPDATE ctl_tasks SET retry_claim=?, claimed_at=? WHERE id=? AND status='failed' AND COALESCE(attempts, 0)=?
                           AND (retry_claim IS NULL OR retry_claim!=? OR claimed_at<?) RETURNING id""",
                        (key, now, r["id"], r.get("attempts") or 0, key, now - CLAIM_STALE), one=True))


def _decide(r, now=None):
    """orchestrator.decide for a failed Control Hub task (its summary holds the error); the retry key is the task's."""
    from .orchestrator import decide
    return decide("failed", r.get("summary") or "", tries=r.get("attempts") or 0, key=f"ctl:t{r['id']}", now=now)


def deliverable_ok(out):
    """control_hub._run_task: a "done" answer counts only with a result to show for it."""
    return (out.get("result") or "").strip().strip(".!").lower() not in EMPTY


def _auto(r):
    """Made by AXoR, or stopped by a restart: the dispatcher's to start. A task you made unstarted stays yours."""
    return (r["origin"] or "") != "you" or (r["summary"] or "").startswith(RESTARTED)


# ---------- one status for a task linked to a board task or a mission ----------
# A board task's or mission's own status is the truth; control_hub._task_out shows it, sync() writes the final ones back to
# ctl_tasks.status (before, a board task finished or merged away stayed 'todo' in every count read straight from the table:
# "14 open, 0 under way"), and counts() reads open tasks the way the Control Hub list shows them.
BOARD = {"working": "running", "queued": "running", "checking": "running", "review": "review", "done": "done"}
MISSION = {"queued": "running", "running": "running", "needs_input": "needs_input", "paused": "todo", "delivered": "done", "done": "done",
           "failed": "failed", "cancelled": "cancelled"}
FINAL = ("done", "failed", "cancelled")
OPEN = ("todo", "running", "review", "needs_input")


def linked(db, ref):
    """What a task's board task (mw_task:N) or mission (mx:N) says, as {"status", …details}; {"gone": True} for a board task
    that's no longer there; None for a task with no such link (or without the tables)."""
    ref = ref or ""
    try:
        if ref.startswith("mw_task:"):
            bid = int(ref.split(":")[1])
            t = db.q("SELECT * FROM mw_tasks WHERE id=?", (bid,), one=True)  # *: older boards lack hold/summary, older teams paused/autopilot
            if not t: return {"status": None, "gone": True, "board_id": bid}
            w = db.q("SELECT * FROM mw_comps WHERE id=?", (t.get("comp_id"),), one=True) or {}
            return {"status": BOARD.get(t["status"], "todo"), "board_id": bid, "board_status": t["status"], "board_hold": t.get("hold"),
                    "board_agent": t.get("agent_id"), "team_paused": bool(w.get("paused")), "team_autopilot": bool(w.get("autopilot")) if "autopilot" in w else None,
                    "done_at": t.get("done_at"), "board_summary": t.get("summary")}
        if ref.startswith("mx:"):
            m = db.q("SELECT status, finished FROM mx_missions WHERE id=?", (int(ref.split(":")[1]),), one=True)
            return {"status": MISSION.get(m["status"], m["status"]), "done_at": m["finished"]} if m else None
    except Exception:  # noqa: BLE001 - no board or missions on this server (or an odd ref): the stored status stands
        return None
    return None


def _keeper(db, bid):
    """The board task a removed one was merged into (mining_release.dedupe notes "Merged duplicates …: #12 (Ana), #15")."""
    try:
        for k in db.q("SELECT id, detail FROM mw_tasks WHERE detail LIKE ?", (f"%Merged duplicates%#{bid}%",)):
            if any(re.search(rf"#{bid}\b", line) for line in (k["detail"] or "").splitlines() if line.startswith("Merged duplicates")):
                return k["id"]
    except Exception:  # noqa: BLE001
        return None
    return None


def sync(db, uid=None, now=None):
    """Write a linked task's final state back to ctl_tasks: done/failed/cancelled from its board task or mission, a board task
    merged into another followed to its keeper, one deleted from the board cancelled with the reason, and a 'done' one reopened
    on the board open again. Only final states are written: a board task being worked stays 'todo' in the table (counting it
    'running' would take one of the user's run slots, control_hub RUNS_PER_USER). Returns the number of tasks changed."""
    now = now or time.time()
    try:
        rows = db.q(f"""SELECT id, ref, status, summary, history, done_at FROM ctl_tasks WHERE (ref LIKE 'mw_task:%' OR ref LIKE 'mx:%')
                        AND (status IN ({','.join('?' * len(OPEN))}) OR (status IN ('done','failed') AND updated>?))""" + (" AND user_id=?" if uid else ""),
                    (*OPEN, now - 7 * 86400, *((uid,) if uid else ())))
    except Exception:  # noqa: BLE001 - no Control Hub tasks table yet
        return 0
    n = 0
    for r in rows:
        L = linked(db, r["ref"])
        if not L: continue
        if L.get("gone"):
            k = _keeper(db, L["board_id"])
            if k:
                db.q("UPDATE ctl_tasks SET ref=?, history=?, updated=? WHERE id=?",
                     (f"mw_task:{k}", _hist(r, f"its board task #{L['board_id']} was merged into #{k} (a repeat): follows #{k}"), now, r["id"]))
            else:
                db.q("UPDATE ctl_tasks SET status='cancelled', summary=?, history=?, updated=? WHERE id=?",
                     (f"Its board task #{L['board_id']} was deleted from the team's board.", _hist(r, f"board task #{L['board_id']} deleted: cancelled"), now, r["id"]))
            n += 1; continue
        s = L["status"]
        if s in FINAL and s != r["status"]:
            what = {"done": "finished", "failed": "failed", "cancelled": "cancelled"}[s]
            db.q("UPDATE ctl_tasks SET status=?, done_at=?, summary=?, history=?, updated=? WHERE id=?",
                 (s, (r["done_at"] or L.get("done_at") or now) if s == "done" else r["done_at"],
                  r["summary"] or L.get("board_summary"), _hist(r, f"{'the team board' if 'board_id' in L else 'its mission'} {what} it"), now, r["id"]))
            n += 1
        elif r["status"] in FINAL and s not in FINAL:
            db.q("UPDATE ctl_tasks SET status='todo', done_at=NULL, history=?, updated=? WHERE id=?",
                 (_hist(r, f"open again on {'the team board' if 'board_id' in L else 'its mission'}"), now, r["id"]))
            n += 1
    return n


def counts(db, uid, mode, now=None):
    """Open tasks read the way the Control Hub list shows them (linked status, why(), owner): what moves, and of the ones that
    haven't moved for STALE, whose move it is. The Intelligence layers' Task dispatch part reads this, not the raw table."""
    now = now or time.time()
    try:
        rows = db.q(f"SELECT * FROM ctl_tasks WHERE user_id=? AND status IN ({','.join('?' * len(OPEN))})", (uid, *OPEN))
    except Exception:  # noqa: BLE001
        return {"open": 0, "moving": 0, "system": 0, "yours": 0, "reasons": []}
    tasks = []
    for r in rows:
        r = {"summary": None, "attempts": 0, "next_try": None, "origin": None, "ref": None, "route": None, "updated": None, **r}
        L = linked(db, r["ref"]) or {}
        t = {"status": L.get("status") or r["status"], "updated": r["updated"], **{k: v for k, v in L.items() if k != "status"}}
        if t["status"] in FINAL: continue  # sync() writes it on its next pass
        t["why"] = dict(zip(("state", "text"), why(t, r, mode, now)))
        tasks.append(t)
    s = summary(tasks, now)
    return {"open": len(tasks), "moving": s["moving"], "system": s["stuck"] - s["yours"], "yours": s["yours"], "reasons": s["reasons"],
            "states": s["states"]}


def why(t, r, mode, now=None, busy=None):
    """(state, text) for an open task: why it isn't moving, or that it is. `t` is the hub's task (status read through its
    board task or mission), `r` its ctl_tasks row."""
    now, st = now or time.time(), t["status"]
    tries, nxt = r.get("attempts") or 0, r.get("next_try")
    if st == "proposed": return "decision", "A Mission Intelligence proposal waiting for your approval (Manual mode)."
    if st == "running":
        if (r["ref"] or "").startswith("mw_task:"): return "moving", "On the team's board, being worked."
        return "moving", "Running."
    if st == "review": return "review", "Delivered: waiting for a review."
    if st == "needs_input":
        s = r["summary"] or ""
        if s.startswith(NO_DELIVERABLE) and tries < MAX_TRIES and mode != "manual" and r["route"] == "agent":
            return "dispatch", "Ended without a deliverable: AXoR gives it to another agent of the team."
        if s.startswith(tl.FAILED_CHECK) and tries < MAX_TRIES and mode != "manual" and r["route"] == "agent":
            return "dispatch", "Failed its checks: AXoR sends it back to the agent with the checks' notes."
        if s.startswith(tl.INVALID): return "stuck", s[:300]
        return "waiting", f"Waiting for you: {s}" if s else "Waiting for your answer."
    if st == "failed":
        d = _decide(r)
        if d["action"] == "hold" or d["cls"] in NEVER: return "held", "Stopped at a token limit: raise the limit or run it again yourself."  # cap too, as before
        if mode != "manual" and r["route"] == "agent" and d["retry"] and (r["updated"] or 0) > now - RECENT:
            return "retry", f"Failed ({d['cls']}); retry {tries + 1} of {d['max_tries']}" + (f" after {time.strftime('%H:%M', time.localtime(nxt))}." if nxt and nxt > now else " on the next pass.")
        if d["action"] == "stop": return "failed", f"Failed ({d['why']}): {d['remediation']}"
        return "failed", "Failed: " + ((r["summary"] or "no reason recorded")[:200]) + (" (the task's own failure: look at it, then run it again)" if d["agent_fault"] else "")
    if st != "todo": return "moving", st
    if (r["ref"] or "").startswith("mw_task:"):
        if t.get("board_status") == "blocked": return "waiting", "Blocked on the team's board: it waits for an answer (Competition teams → its task)."
        if t.get("board_hold") == "failed": return "failed", "The team gave up on it after failed runs: look at it on the board (Competition teams → its task)."
        if t.get("board_hold") == "retry": return "queued", "Failed on the team's board: its Autoloop runs it again."
        if t.get("team_paused"): return "waiting", "Its team is paused: resume the team (My subnets → Teams) to have it handed out."
        if t.get("board_agent") is None and t.get("team_autopilot") is False:
            return "waiting", "On the team's board with nobody on it, and the team's autopilot is off: assign it, or turn autopilot on."
        if t.get("board_agent") is not None: return "queued", "On the team's board, assigned: waits for a free slot on the team."
        return "queued", "On the team's board, waiting for its Director to hand it out."
    if r["route"] == "mission": return "stuck", "No mission was started for it: open it and start it again."
    if mode == "manual": return "manual", "Manual mode: waiting for you to run it (Hybrid or Auto mode dispatches it)."
    if not _auto(r): return "manual", "You made it without starting it: start it when you want it done."
    if not ENABLED: return "manual", "The dispatcher is off on this server (CONTROL_DISPATCH=0): run it yourself."
    if (r["summary"] or "").startswith(tl.INVALID): return "stuck", r["summary"][:300]
    if tries >= MAX_TRIES: return "stuck", f"Couldn't be dispatched in {tries} tries: " + ((r["summary"] or "")[:200] or "see its history.")
    if nxt and nxt > now: return "retry", f"Dispatch {tries + 1} of {MAX_TRIES} after {time.strftime('%H:%M', time.localtime(nxt))}: {(r['summary'] or '')[:160]}"
    if r["route"] == "agent" and busy is not None and busy <= 0: return "busy", "Waiting for a free run slot: your agents are all working."
    if (r["summary"] or "").startswith(RESEARCHING): return "queued", r["summary"][:300]
    return "dispatch", "AXoR dispatches it on its next pass (within a minute)."


STUCK = ("stuck", "failed", "held", "manual", "decision", "waiting")  # need someone; dispatch/retry/busy/queued are on their way
# who moves an open task next, by its why() state: every task that doesn't move has an owner, not only a reason
OWNER = {"decision": "you", "waiting": "you", "failed": "you", "held": "you", "manual": "you", "stuck": "you",
         "dispatch": "Dispatcher", "retry": "Dispatcher", "busy": "Dispatcher", "queued": "the team's Director", "moving": "", "review": "you"}


def owner(state): return OWNER.get(state, "you")


def summary(tasks, now=None):
    """Counts over the hub's open tasks (each with its 'why'): what moves, what's on its way, what needs someone."""
    now = now or time.time()
    st = {}
    for t in tasks:
        k = (t.get("why") or {}).get("state")
        if k: st[k] = st.get(k, 0) + 1
    moving = st.get("moving", 0) + st.get("review", 0)
    old = [t for t in tasks if (t.get("why") or {}).get("state") not in ("moving", "review", None) and (t.get("updated") or now) < now - STALE]
    top, who = {}, {}
    for t in old:
        k = t["why"]["text"].split(":")[0]
        top[k] = top.get(k, 0) + 1
        who[k] = owner(t["why"]["state"])
    return {"states": st, "moving": moving, "stuck": len(old), "yours": sum(1 for t in old if owner(t["why"]["state"]) == "you"),
            "reasons": [{"why": k, "n": v, "owner": who[k]} for k, v in sorted(top.items(), key=lambda x: -x[1])[:4]]}


def _note(ch, r, what, sets):
    sets = {**sets, "history": _hist(r, what), "updated": time.time()}
    ch.db.q(f"UPDATE ctl_tasks SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?", (*sets.values(), r["id"]))


def _miss(ch, r, err):
    """A dispatch that didn't take: counted, with a growing wait before the next try."""
    n = (r.get("attempts") or 0) + 1
    _note(ch, r, f"couldn't dispatch ({n}/{MAX_TRIES}): {err[:200]}", {"attempts": n, "next_try": time.time() + tl.backoff(RETRY_AFTER, n), "summary": f"Couldn't dispatch: {err[:300]}"})


def _start(ch, me, r, key, what, extra=None, feedback=""):
    """Give an agent task to `key` and start it; HTTPException when it can't start now. The note is written first: the run
    appends its own history line when it ends, possibly before this function returns."""
    _note(ch, r, what, {"agent_key": key, "status": "todo", "next_try": None, **(extra or {})})
    ch._start_task(me, r["id"], feedback)  # 429 when the user's runs at once are taken (the task stays todo); 409 when it's running already


def dispatch(ch, me, now=None):
    """One pass for one user. Returns {"mode", "board", "agent", "retried", "reassigned", "missed", "held"}."""
    from . import control_missions as cm
    from .control_hub import RUNS_PER_USER, _cap, _spent
    uid, now = me["id"], now or time.time()
    mode = ch.mode(uid)
    out = {"mode": mode, "board": 0, "agent": 0, "retried": 0, "reassigned": 0, "corrected": 0, "claimed": 0, "blocked": 0, "escalated": 0,
           "missed": 0, "held": None}
    if mode == "manual" or not ENABLED: return out
    try: out["claimed"] = tl.unclaimed(ch, me, now)  # board tasks nobody took for CLAIM_TIMEOUT: to the team's least-loaded agent
    except Exception as e:  # noqa: BLE001 - the pass goes on
        log.warning("dispatch: claim timeouts: %s", e)
    cap = _cap(uid)
    hold = bool(cap and _spent(uid) >= cap * cm.HOLD_USER)
    if hold: out["held"] = "You're near your daily token limit: agent tasks wait (board tasks follow their team's own budget)."
    slots = RUNS_PER_USER - ch._busy(uid)
    rows = ch.db.q("""SELECT * FROM ctl_tasks WHERE user_id=? AND route IN ('board','agent') AND (next_try IS NULL OR next_try<=?)
                      AND ((status='todo' AND (ref IS NULL OR ref='')) OR (status IN ('failed','needs_input') AND updated>?))""", (uid, now, now - RECENT))
    rows.sort(key=lambda r: (PRI.get(r["priority"], 1), r["id"]))
    names = {}
    try: names = ch._view(me)["names"]
    except Exception: pass  # noqa: BLE001 - names are only for the history line
    for r in rows:
        tries = r.get("attempts") or 0
        try:
            if r["status"] == "todo":
                if not _auto(r) or tries >= MAX_TRIES: continue
                c = tl.contract(ch, me, r)
                if not c["ok"]:  # a task that can't be dispatched as written is stopped with the reason, never retried
                    _note(ch, r, "invalid task contract: " + "; ".join(c["problems"]), {"attempts": MAX_TRIES, "next_try": None,
                          "summary": f"{tl.INVALID}: " + "; ".join(c["problems"]) + ". Fix the task (team, agent or route), then retry it."})
                    out["blocked"] += 1; continue
                if r["route"] == "board":
                    if out["board"] >= PER_PASS: continue
                    bid = tl.adopt(ch, r)  # a pass that stopped between making the board task and linking it: link that one
                    if not bid:
                        from . import task_research  # research before a fixed task (the Intelligence brief): it waits while that runs, never longer
                        go, detail = task_research.ready(ch, me, r)
                        if not go: out["researching"] = out.get("researching", 0) + 1; continue
                        _note(ch, r, tl.DISPATCHING, {})
                        bid = cm._to_board(ch, me, {**r, "detail": detail}, actor="automatic dispatch")  # the acceptance criteria (and the brief's digest) travel with it
                    if not bid: raise HTTPException(409, "The board didn't take it.")
                    _note(ch, ch.db.q("SELECT * FROM ctl_tasks WHERE id=?", (r["id"],), one=True) or r, "dispatched to the team's board",
                          {"ref": f"mw_task:{bid}", "done_at": None, "next_try": None})
                    out["board"] += 1
                    ch._audit(uid, "AXoR", "task.dispatch", f"ctl:t{r['id']}", f"{r['title']} → board")
                else:
                    if hold or slots <= 0: continue
                    gate = _readiness(ch, uid, r)  # G5-2 (D-011): declared needs probed before an agent gets it
                    if gate and gate["state"] == "BLOCKED":
                        held_why = mo.gate_text(gate)  # not "why": that name is this module's function, used below
                        if (r["summary"] or "") != held_why: _note(ch, r, "held by readiness", {"summary": held_why})
                        out["readiness_held"] = out.get("readiness_held", 0) + 1; continue  # "held" is the daily-limit message
                    key, note = (r["agent_key"], "") if r["agent_key"] else tl.pick(ch, me, r)  # its team, then the mission's supporting teams
                    refused = _budget(ch, me, r, key)  # G5-2 budget safety: the same decision the gateway makes, before a run exists
                    if refused: _budget_hold(ch, r, refused, out); continue  # REFUSE or UNKNOWN: nothing starts
                    if not key: raise HTTPException(409, note)
                    _start(ch, me, r, key, f"dispatched to {names.get(key, key)}" + (f" ({note})" if note else ""))
                    for i in (gate or {}).get("items", []):  # a one-time approval is used by this start
                        if i.get("consume"):
                            from . import orchestrator
                            orchestrator.approval_consume(uid, i["consume"])
                    slots -= 1; out["agent"] += 1
                    ch._audit(uid, "AXoR", "task.dispatch", f"ctl:t{r['id']}", f"{r['title']} → {names.get(key, key)}")
            elif r["status"] == "failed" and r["route"] == "agent":
                d = _decide(r, now)  # G5-2 (D-015 D2): only transient causes retry; immediate vs delayed; bounded, jittered
                if not d["retry"] or hold or not r["agent_key"]: continue
                due = (r["updated"] or now) + d["delay"]
                if due > now:  # not yet: the pass that's due picks it up
                    ch.db.q("UPDATE ctl_tasks SET next_try=? WHERE id=?", (due, r["id"])); continue
                if slots <= 0: continue
                refused = _budget(ch, me, r, r["agent_key"])  # G5-2 Blocker A: a retry is a start too; checked before the claim uses it
                if refused: _budget_hold_retry(ch, r, refused, out); continue
                if not _claim(ch, r, d["retry_key"], now): continue  # another pass has this retry: exactly one starts it
                k = d["cls"]
                _start(ch, me, r, r["agent_key"], f"retry {tries + 1}/{d['max_tries']} after a '{k}' failure ({d['retry_key']})", {"attempts": tries + 1})
                slots -= 1; out["retried"] += 1
                ch._audit(uid, "AXoR", "task.retry", f"ctl:t{r['id']}", f"{r['title']}: {k}")
            elif r["status"] == "needs_input" and r["route"] == "agent" and (r["summary"] or "").startswith(tl.FAILED_CHECK):
                if tries >= MAX_TRIES or hold or slots <= 0 or not r["agent_key"]: continue
                refused = _budget(ch, me, r, r["agent_key"])  # G5-2 Blocker A: a correction is a start too
                if refused: _budget_hold_retry(ch, r, refused, out); continue
                fb = (_j(r.get("verify"), {}) or {}).get("why") or r["summary"]  # the checks' notes go back with it: a correction, not a rerun
                _start(ch, me, r, r["agent_key"], f"sent back to {names.get(r['agent_key'], 'the agent')} for a correction: {fb[:160]}", {"attempts": tries + 1}, feedback=fb)
                slots -= 1; out["corrected"] += 1
                ch._audit(uid, "AXoR", "task.retry", f"ctl:t{r['id']}", f"{r['title']}: failed its checks")
            elif r["status"] == "needs_input" and r["route"] == "agent" and (r["summary"] or "").startswith(NO_DELIVERABLE):
                if tries >= MAX_TRIES or hold or slots <= 0: continue
                other = _other_agent(ch, me, r)
                if not other:  # handed back to you, said so (why(): "Waiting for you: …")
                    _note(ch, r, "nobody else on the team can take it: back to you", {"attempts": MAX_TRIES,
                          "summary": (r["summary"] or NO_DELIVERABLE)[:300] + " Nobody else on the team can take it: send it back with a note, or give it to another agent."})
                    continue
                _start(ch, me, r, other, f"reassigned to {names.get(other, other)}: {names.get(r['agent_key'], 'the agent')} ended without a deliverable", {"attempts": tries + 1})
                slots -= 1; out["reassigned"] += 1
                ch._audit(uid, "AXoR", "task.reassign", f"ctl:t{r['id']}", r["title"])
        except HTTPException as e:
            if e.status_code == 429: slots = 0; continue  # runs at once taken: next pass
            cur = ch.db.q("SELECT status FROM ctl_tasks WHERE id=?", (r["id"],), one=True)
            if cur and cur["status"] == "running": continue  # started meanwhile (by you, or another pass): one run, not two
            _miss(ch, ch.db.q("SELECT * FROM ctl_tasks WHERE id=?", (r["id"],), one=True) or r, str(e.detail)); out["missed"] += 1
        except Exception as e:  # noqa: BLE001 - one task's trouble doesn't stop the pass
            log.warning("dispatch task %s: %s", r["id"], e)
            _miss(ch, ch.db.q("SELECT * FROM ctl_tasks WHERE id=?", (r["id"],), one=True) or r, str(e)); out["missed"] += 1
    try:  # the dead letters: no automatic path left, so they go to you (an audit line and a push, once a day per task)
        pairs = []
        for r in ch.db.q("SELECT * FROM ctl_tasks WHERE user_id=? AND (status IN ('todo','needs_input') OR (status='failed' AND updated>?))", (uid, now - RECENT)):
            L = linked(ch.db, r["ref"]) or {}
            t = {**{k: v for k, v in L.items() if k != "status"}, "status": L.get("status") or r["status"]}
            if t["status"] in ("done", "cancelled"): continue
            t["why"] = dict(zip(("state", "text"), why(t, r, mode, now)))
            pairs.append((t, r))
        out["escalated"] = tl.escalate(ch, me, pairs, now)
    except Exception as e:  # noqa: BLE001
        log.warning("dispatch: escalation: %s", e)
    with _lock: _last[uid] = (now, out)
    return out


def _other_agent(ch, me, r):
    """Another active agent of the task's team with room, not the one that came back empty."""
    v = ch._view(me)
    u = next((x for x in v["units"] if x["id"] == r["unit_id"]), None)
    if not u: return None
    sq = set(u.get("squads") or [])
    own = [a for a in v["agents"] if (a["unit_id"] == u["id"] or a["unit_id"] in sq) and a["status"] == "active" and a["load"] < a["cap"] and a["key"] != r["agent_key"]]
    return sorted(own, key=lambda a: (a["key"] == u["manager_key"], a["load"]))[0]["key"] if own else None


def last(uid):
    with _lock: return _last.get(uid)


def tick(ch, now=None):
    """A pass for every user with work the dispatcher could move. Returns the number of tasks it moved."""
    now = now or time.time()
    try: sync(ch.db, now=now)  # final states of board tasks and missions first, dispatcher on or off: every count reads the table
    except Exception as e:  # noqa: BLE001
        log.warning("dispatch: status sync: %s", e)
    try: tl.watchdog(ch.db, now)  # agent runs with no sign of life: TIMEOUT (a transient failure the retry policy picks up)
    except Exception as e:  # noqa: BLE001
        log.warning("dispatch: watchdog: %s", e)
    if not ENABLED: return 0
    from . import control_missions as cm
    n = 0
    for s in ch.db.q("""SELECT DISTINCT user_id FROM ctl_tasks WHERE route IN ('board','agent')
                        AND ((status='todo' AND (ref IS NULL OR ref='')) OR (status IN ('failed','needs_input') AND updated>?))""", (now - RECENT,)):
        if ch.mode(s["user_id"]) == "manual": continue
        me = cm._owner(ch, s["user_id"])
        if not me: continue
        try:
            if ch.hub and hasattr(ch.hub, "gate"): me = ch.hub.gate(dict(me)) or me
            o = dispatch(ch, me, now)
            n += o["board"] + o["agent"] + o["retried"] + o["reassigned"] + o["corrected"] + o["claimed"]
        except HTTPException: continue  # no agent access any more
        except Exception as e:  # noqa: BLE001 - one user's trouble doesn't stop the others
            log.warning("dispatch: user %s: %s", s["user_id"], e)
    return n
