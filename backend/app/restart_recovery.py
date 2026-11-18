"""What became of the work a server restart (a deploy) cut off: recovered by itself, waiting with an owner who moves it next,
or waiting on you. From the 2026-11-10 operations review: the Control Hub showed seven failed runs "associated with a server
restart" and no one could tell whether anything had picked them up.

follow(db, run) reads the run's own system (agent_core ac_runs.ref):
  mw:<rid>   a Competition team's run: its task ran again, is done, or is back on the board; Autoloop starts it again when the
             team's autopilot is on and the task isn't held, else the user does
  ctl:t<id>  a Control Hub task: running again or done; back to "todo", the dispatcher restarts it in Hybrid/Auto mode
  mx:<id>    a Mission Control mission: running, queued or delivered again; paused waits for the user's Resume
  anything else: a later run with the same ref counts as recovered
Returns {"state": "recovered"|"waiting"|"yours", "owner", "action", "detail"}. Nothing here starts anything.
"""
import re

RESTARTED = "server restart"


def _one(db, sql, args):
    try: return db.q(sql, args, one=True)
    except Exception: return None  # noqa: BLE001 - a table this server doesn't have


def is_restart(run):
    return (run.get("status") or "") == "lost" or RESTARTED in (run.get("error") or "").lower()


def follow(db, run, mode=None):
    p, _, rest = (run.get("ref") or "").partition(":")
    if p == "mw" and rest.isdigit():
        r = _one(db, "SELECT task_id, comp_id, kind FROM mw_runs WHERE id=?", (int(rest),))
        if r and r["task_id"]:
            later = _one(db, "SELECT id, status FROM mw_runs WHERE task_id=? AND id>? ORDER BY id DESC LIMIT 1", (r["task_id"], int(rest)))
            t = _one(db, "SELECT status, hold, agent_id FROM mw_tasks WHERE id=?", (r["task_id"],))
            w = _one(db, "SELECT autopilot, paused, status FROM mw_comps WHERE id=?", (r["comp_id"],))
            if not t: return {"state": "recovered", "owner": "you", "action": "", "detail": "Its task was deleted since."}
            if t["status"] == "done": return {"state": "recovered", "owner": "Autoloop", "action": "", "detail": "Its task is done since."}
            if later: return {"state": "recovered", "owner": "Autoloop", "action": "", "detail": f"Its task ran again (run #{later['id']}, {later['status']})."}
            if t["status"] in ("queued", "working", "checking", "review"):
                return {"state": "recovered", "owner": "Autoloop", "action": "", "detail": f"Its task is {t['status']} again."}
            if w and w["autopilot"] and not w["paused"] and w["status"] != "closed" and not t["hold"] and t["agent_id"]:
                return {"state": "waiting", "owner": "Autoloop", "action": "", "detail": "Back on the board: Autoloop starts it when a slot frees."}
            why = "the team's autopilot is off" if w and not w["autopilot"] else "the team is paused" if w and w["paused"] else \
                "the task is held" if t["hold"] else "the task has no agent" if not t["agent_id"] else "the team is closed"
            return {"state": "yours", "owner": "you", "action": "Start the task on the team's board", "detail": f"Back on the board, but {why}."}
        if r: return {"state": "recovered", "owner": "Autoloop", "action": "", "detail": f"A team {r['kind'] or 'run'}: the next plan or review takes over."}
    if p == "ctl" and re.fullmatch(r"t\d+", rest or ""):
        t = _one(db, "SELECT status FROM ctl_tasks WHERE id=?", (int(rest[1:]),))
        if not t: return {"state": "recovered", "owner": "you", "action": "", "detail": "The task was deleted since."}
        if t["status"] in ("running", "review", "done"): return {"state": "recovered", "owner": "Dispatcher", "action": "", "detail": f"The task is {t['status']} again."}
        if t["status"] == "todo" and mode in ("hybrid", "auto"):
            return {"state": "waiting", "owner": "Dispatcher", "action": "", "detail": "Back to do: the dispatcher starts it again on its next pass."}
        return {"state": "yours", "owner": "you", "action": "Start the task (Control Hub → Missions → Tasks)", "detail": f"The task is {t['status']}" + (" and the Control Hub is in Manual mode." if mode == "manual" else ".")}
    if p == "mx" and rest.isdigit():
        m = _one(db, "SELECT status FROM mx_missions WHERE id=?", (int(rest),))
        if not m: return {"state": "recovered", "owner": "you", "action": "", "detail": "The mission was deleted since."}
        if m["status"] in ("running", "queued", "delivered", "needs_input"):
            return {"state": "recovered", "owner": "Mission Control", "action": "", "detail": f"The mission is {m['status'].replace('_', ' ')} again."}
        if m["status"] == "paused": return {"state": "yours", "owner": "you", "action": "Resume the mission (Mission Control)", "detail": "The mission is paused."}
        return {"state": "recovered", "owner": "Mission Control", "action": "", "detail": f"The mission ended {m['status']}."}
    if run.get("ref") and run.get("id"):
        later = _one(db, "SELECT id, status FROM ac_runs WHERE ref=? AND id>? ORDER BY id DESC LIMIT 1", (run["ref"], run["id"]))
        if later: return {"state": "recovered", "owner": "its system", "action": "", "detail": f"It ran again (run #{later['id']}, {later['status']})."}
    return {"state": "yours", "owner": "you", "action": "Run it again from where it started", "detail": "Nothing has run it again yet."}


def summary(db, runs, mode=None):
    """The restart-cut runs among `runs` (ac_runs rows with id, ref, status, error), each followed, and counts."""
    out = []
    for r in runs:
        if not is_restart(r): continue
        out.append({**{k: r.get(k) for k in ("id", "ref", "title", "system", "started")}, **follow(db, r, mode)})
    n = lambda s: sum(1 for x in out if x["state"] == s)
    return {"interrupted": len(out), "recovered": n("recovered"), "waiting": n("waiting"), "yours": n("yours"), "runs": out}
