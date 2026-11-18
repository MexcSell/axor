"""Missions and tasks in the Control Hub (control-missions.js; /api/control/missions…, /api/control/mission-tasks/…): two levels
kept apart, with Bittensor as the company's primary initiative.

    Initiative     Bittensor (primary) · Other initiatives
      Mission      what the company wants to achieve        predefined | custom
        Task       what agents do to get there              fixed | dynamic   (a task may have subtasks, or stand alone)
          Teams and agents carry the tasks out.

- A predefined mission is a Bittensor competition: one Competition team's objective (mw_comps + ctl_fixed: target rank,
  objectives, constraints, deadline, daily budget), set up by the Control Hub's mission wizard. Ref "comp:<mw_comps.id>".
  Its fixed tasks come from the competition template (TEMPLATE), seeded once per mission (keyed by `template`, so a re-read
  never duplicates them). Predefined doesn't mean unmodifiable: a fixed task can be edited, given a cadence, or skipped.
  A recurring fixed task (cadence_days) opens again once it's due after it was done.
- A custom mission is a Mission Control mission (mx_missions, ref "mx:<id>"): a goal you or an agent define. The mission
  engine plans its own tasks (its plan's tasks are its dynamic tasks, read-only here). A custom mission launched for a
  Competition team (mx_missions.team) belongs to the Bittensor initiative and to that team's predefined mission.
- Dynamic tasks (ctl_tasks.kind = 'dynamic'): made by you, by an agent (a chat proposal you approved) or by Mission
  Intelligence. A Competition team's task belongs to its predefined mission unless it's made standalone. A dynamic task can
  be made fixed (mandatory, optionally recurring): you clicking it is the approval, and it's audited.
- Standalone tasks (mission NULL): routine work that serves no mission, e.g. infrastructure maintenance.
- Mission Intelligence reads a predefined mission's results (standing against the target, the latest brief, open alerts,
  failed runs, the open tasks) and proposes dynamic tasks and priority changes, with the reason for each. Manual mode: they
  wait for you as proposals. Hybrid and Auto: the tasks go on the team's board (its Director hands them out) and the
  priorities change. It never does anything external: registering, deploying and submitting stay yours. It runs when you
  ask, and in Auto mode also on a schedule (every EVERY_H hours per mission), held while the lead team has used HOLD_TEAM of
  its daily budget, you've used HOLD_USER of your daily limit, or MAX_OPEN_INTEL of its earlier tasks are still open.
- Several teams on one mission: the Competition team leads (it holds the target and its board gets the fixed tasks); any
  other team can join as a supporting team with a duty (ctl_mission_teams). A task can go to any of the mission's teams (a
  task given to a team that isn't on the mission yet brings it in, audited), and Mission Intelligence picks the team for
  each task it makes. Custom missions keep their engine's own staffing.
"""
import json, logging, os, re, threading, time

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

from . import agent_core, mining_work, task_lifecycle
from .llm import LLMError

log = logging.getLogger("scout.control.missions")
DAY = 86400
PRIMARY = "bittensor"
INITIATIVES = {"bittensor": "Bittensor", "other": "Other initiatives"}
OPEN = ("proposed", "todo", "running", "review", "needs_input")
CLOSED = ("done", "cancelled", "skipped", "failed")
MX_ACTIVE = ("queued", "running", "needs_input", "paused")
MAX_PROPOSALS = 4
EVERY_H = float(os.getenv("CONTROL_INTEL_EVERY_HOURS", "24") or 0)  # the scheduled review in Auto mode; 0 turns it off
TICK = max(5, int(os.getenv("CONTROL_INTEL_TICK", "600") or 600))  # seconds between the schedule's checks
HOLD_TEAM = .8               # no scheduled review once the lead team has used this share of its daily token budget
HOLD_USER = .9               # nor once its owner has used this share of their daily token limit
MAX_OPEN_INTEL = 6           # nor while this many of Mission Intelligence's earlier tasks are still open on the mission
_running, _lock, _thread = set(), threading.Lock(), None
# A Bittensor competition's fixed tasks: predefined, mandatory or recurring work every competition needs. Agents prepare;
# anything that registers, deploys or submits waits for you.
TEMPLATE = [
    ("infra", "Configure the miner infrastructure",
     "Set up and document what the miner runs on: hardware or sandbox, dependencies, the validator-facing endpoint, monitoring. "
     "Registering a hotkey or spending TAO stays yours: list what's needed.", "high", None),
    ("interfaces", "Implement the competition's required interfaces",
     "Read the competition's rules and implement every interface and output format a validator scores; test them in the sandbox.",
     "high", None),
    ("availability", "Keep the miner available",
     "Check the miner is up, reachable and scored; look at errors and restarts since the last check, and report what to fix.",
     "medium", 7),
    ("deliverables", "Prepare the required deliverables",
     "Prepare everything the competition asks you to submit, checked against its rules, by its deadline. Submitting it is yours.",
     "high", None),
]
INTEL = {"type": "object", "additionalProperties": False, "required": ["summary", "proposals", "reprioritize"], "properties": {
    "summary": {"type": "string", "description": "Two sentences: where the mission stands and what matters most now."},
    "proposals": {"type": "array", "description": f"Up to {MAX_PROPOSALS} new dynamic tasks the results call for; none if the open tasks already cover it.",
                  "items": {"type": "object", "additionalProperties": False, "required": ["title", "detail", "priority", "reason", "team", "needs"], "properties": {
                      "title": {"type": "string", "description": "An imperative task title, at most 12 words."},
                      "detail": {"type": "string", "description": "What to do and what it delivers."},
                      "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                      "reason": {"type": "string", "description": "The result or signal that calls for it."},
                      "team": {"type": "string", "description": "The name of the mission's team that should do it; empty for the lead team."},
                      "needs": task_lifecycle.NEEDS_SCHEMA}}},  # planner schema v2 (G5-2, D-015 D3)
    "reprioritize": {"type": "array", "description": "Open tasks (by id) whose priority should change, with why.",
                     "items": {"type": "object", "additionalProperties": False, "required": ["id", "priority", "reason"], "properties": {
                         "id": {"type": "integer"}, "priority": {"type": "string", "enum": ["high", "medium", "low"]}, "reason": {"type": "string"}}}}}}


def _j(s, d=None):
    try: return json.loads(s) if s else d
    except (TypeError, ValueError): return d


def _clip(s, n): s = str(s or ""); return s if len(s) <= n else s[:n - 1] + "…"


def _words(s): return set(re.findall(r"[a-z0-9]{3,}", (s or "").lower()))


def _similar(a, b):
    A, B = _words(a), _words(b)
    return bool(A and B) and (A == B or len(A & B) / len(A | B) >= .7)


def ensure_schema(db):
    cols = {c["name"] for c in db.q("PRAGMA table_info(ctl_tasks)")}
    for name, ddl in [("mission", "TEXT"), ("kind", "TEXT DEFAULT 'dynamic'"), ("parent_id", "INTEGER"), ("template", "TEXT"),
                      ("cadence_days", "INTEGER"), ("done_at", "REAL")]:
        if name not in cols: db.q(f"ALTER TABLE ctl_tasks ADD COLUMN {name} {ddl}")
    db.q("CREATE INDEX IF NOT EXISTS ctl_tasks_m ON ctl_tasks (user_id, mission)")
    db.q("""CREATE TABLE IF NOT EXISTS ctl_intel (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, mission TEXT, ts REAL, source TEXT,
            summary TEXT, items TEXT, revisions TEXT, tokens INTEGER DEFAULT 0, model TEXT, error TEXT, by_user TEXT)""")
    db.q("CREATE INDEX IF NOT EXISTS ctl_intel_m ON ctl_intel (user_id, mission, id)")
    db.q("""CREATE TABLE IF NOT EXISTS ctl_mission_teams (user_id INTEGER, mission TEXT, unit_id INTEGER, duty TEXT, added REAL, by_user TEXT,
            PRIMARY KEY (user_id, mission, unit_id))""")
    from . import control_dispatch
    control_dispatch.ensure_schema(db)  # attempts, next_try: the dispatcher's retry policy


# ---------- reading ----------
def RUNS_PER_USER():  # noqa: N802 - control_hub's constant, read late (it imports this module)
    from .control_hub import RUNS_PER_USER as n
    return n


def _units(ch, me):
    """{comp id: its og unit} for the user's Competition teams."""
    return {ch._comp_of(u): u for u in ch._view(me)["units"] if ch._comp_of(u)}


def _task(ch, r, v=None):
    """One task as the hub shows it, with its level: kind, mission, parent, template, cadence, when it's due again."""
    out = ch._task_out(r, v)
    out.update(kind=r["kind"] or "dynamic", mission=r["mission"], parent_id=r["parent_id"], template=r["template"], cadence_days=r["cadence_days"])
    if r["status"] in ("proposed", "skipped") and not r["ref"]: out["status"] = r["status"]
    done = out["status"] == "done"
    fin = None
    if done and not r["done_at"] and (r["ref"] or "").startswith("mw_task:") and ch._has("mw_tasks"):  # when the board finished it, not when it was sent
        fin = (ch.db.q("SELECT done_at FROM mw_tasks WHERE id=?", (int(r["ref"].split(":")[1]),), one=True) or {}).get("done_at")
    out["done_at"] = r["done_at"] or fin or (r["updated"] if done else None)
    out["due"] = out["done_at"] + r["cadence_days"] * DAY if done and r["cadence_days"] and out["done_at"] else None
    return out


def _recur(ch, me):
    """Recurring fixed tasks whose cadence has come round since they were done open again."""
    db, now = ch.db, time.time()
    for r in db.q("SELECT * FROM ctl_tasks WHERE user_id=? AND kind='fixed' AND cadence_days>0 AND status NOT IN ('skipped','cancelled')", (me["id"],)):
        t = _task(ch, r)
        if t["status"] != "done": continue
        if not r["done_at"]:
            db.q("UPDATE ctl_tasks SET done_at=? WHERE id=?", (t["done_at"] or now, r["id"])); continue
        if t["due"] and t["due"] <= now:
            hist = (_j(r["history"], []) or []) + [{"ts": now, "by": "AXoR", "what": f"due again (every {r['cadence_days']} days)"}]
            db.q("UPDATE ctl_tasks SET status='todo', ref=NULL, done_at=NULL, result=NULL, summary=?, history=?, updated=? WHERE id=?",
                 (f"Due again: every {r['cadence_days']} days.", json.dumps(hist[-40:]), now, r["id"]))


def ensure_fixed(ch, me, wid):
    """Seed a predefined mission's fixed tasks from the competition template, once (idempotent by template key)."""
    w = ch._comps(me["id"]).get(wid)
    if not w or (w["status"] or "active") == "closed": return 0
    ref, uid = f"comp:{wid}", me["id"]
    have = {r["template"] for r in ch.db.q("SELECT template FROM ctl_tasks WHERE user_id=? AND mission=? AND template IS NOT NULL", (uid, ref))}
    unit = _units(ch, me).get(wid)
    now, n = time.time(), 0
    for key, title, detail, prio, cadence in TEMPLATE:
        if key in have: continue
        hist = [{"ts": now, "by": "AXoR", "what": "added from the competition template"}]
        ch.db.q("""INSERT INTO ctl_tasks (user_id, unit_id, agent_key, title, detail, priority, route, status, origin, history, by_user, created, updated,
                   mission, kind, template, cadence_days) VALUES (?,?,NULL,?,?,?,'board','todo','template',?,?,?,?,?,'fixed',?,?)""",
                (uid, unit["id"] if unit else None, title, detail, prio, json.dumps(hist), "AXoR", now, now, ref, key, cadence))
        n += 1
    return n


def _predefined(ch, me, w, f, unit, tasks):
    s = ch._standing(w["campaign_id"])
    out = {"ref": f"comp:{w['id']}", "type": "predefined", "initiative": PRIMARY, "comp_id": w["id"], "subnet": w["netuid"],
           "title": ch._label(w), "unit": f"u:{unit['id']}" if unit else None, "status": "closed" if w["status"] == "closed" else "active",
           "target_rank": f["target_rank"] if f else None, "objective": (f or {}).get("objectives") or w["goal"] or "",
           "deadline": (f or {}).get("deadline") or w["ends"] or "", "budget": w["budget"], "used_today": ch._day_tokens(w["id"]),
           "standing": s, "configured": bool(f), "link": w["link"]}
    out["gap"] = ch._gap(out)
    mine = [t for t in tasks if t["mission"] == out["ref"]]
    out["tasks"] = {"fixed": sum(1 for t in mine if t["kind"] == "fixed" and t["status"] not in CLOSED),
                    "fixed_total": sum(1 for t in mine if t["kind"] == "fixed" and t["status"] != "skipped"),
                    "fixed_done": sum(1 for t in mine if t["kind"] == "fixed" and t["status"] == "done"),
                    "dynamic": sum(1 for t in mine if t["kind"] != "fixed" and t["status"] in OPEN and t["status"] != "proposed"),
                    "proposed": sum(1 for t in mine if t["status"] == "proposed")}
    return out


def _custom(m, origin=None, comps=None):
    plan = _j(m.get("plan"), {}) or {}
    team = m.get("team")
    w = (comps or {}).get(team) if team else None
    return {"ref": f"mx:{m['id']}", "type": "custom", "initiative": PRIMARY if team else "other", "mx_id": m["id"],
            "title": m["title"] or _clip(m.get("goal"), 80) or f"Mission {m['id']}", "status": m["status"], "stage": m.get("stage"),
            "progress": m.get("progress"), "budget": m.get("budget"), "spent": m.get("spent"), "updated": m.get("updated"),
            "parent": f"comp:{team}" if w else None, "parent_title": f"SN{w['netuid']} · " + (w["name"] or f"Competition {w['number']}") if w else None,
            "from_task": origin, "tasks": {"plan": len(plan.get("tasks") or [])}}


def _mx_rows(ch, uid):
    if not ch._has("mx_missions"): return []
    cols = ch._cols("mx_missions")
    want = [c for c in ("id", "title", "goal", "status", "stage", "progress", "budget", "spent", "team", "plan", "updated", "created") if c in cols]
    return ch.db.q(f"""SELECT {', '.join(want)} FROM mx_missions WHERE user_id=? ORDER BY CASE WHEN status IN ('queued','running','needs_input','paused')
                       THEN 0 ELSE 1 END, id DESC LIMIT 40""", (uid,))


def _mission_teams(ch, v, ref, lead, support, tasks):
    """The mission's teams: the lead (its Competition team) and the supporting teams, each with its open tasks on the mission."""
    by_id = {u["id"]: u for u in v["units"]}
    out = [{"ref": f"u:{lead['id']}", "name": lead["name"], "role": "lead", "duty": "Holds the target; its board gets the fixed tasks", "board": True}] if lead else []
    for s in support:
        u = by_id.get(s["unit_id"])
        if u: out.append({"ref": f"u:{u['id']}", "name": u["name"], "role": "support", "duty": s["duty"] or "", "board": bool(ch._comp_of(u)), "added": s["added"], "by": s["by_user"]})
    for t in out: t["open"] = sum(1 for x in tasks if x["mission"] == ref and x["team"] == t["ref"] and x["status"] in OPEN and x["status"] != "proposed")
    return out


def _hold(ch, me, ms, open_intel):
    """Why the scheduled review waits, or None: the lead team's budget, the owner's daily limit, its earlier tasks still open."""
    from .control_hub import _cap, _spent
    if ms.get("budget") and ms["used_today"] >= ms["budget"] * HOLD_TEAM:
        return f"The team has used {round(ms['used_today'] / ms['budget'] * 100)}% of its daily token budget."
    cap = _cap(me["id"])
    if cap and _spent(me["id"]) >= cap * HOLD_USER: return "You're near your daily token limit."
    if open_intel >= MAX_OPEN_INTEL: return f"{open_intel} of its earlier tasks are still open: they come first."
    return None


def _schedule(ch, me, ms, mode, last, tasks):
    on = mode == "auto" and EVERY_H > 0
    open_intel = sum(1 for t in tasks if t["mission"] == ms["ref"] and t["origin"] == "intelligence" and t["status"] in OPEN)
    return {"on": on, "every_h": EVERY_H, "last": last, "next": last + EVERY_H * 3600 if on and last else None,  # None: due now
            "hold": _hold(ch, me, ms, open_intel) if on else None}


def missions(ch, me):
    """Every mission by initiative (Bittensor first), every task by level, and the counts the Command Center shows."""
    uid = me["id"]
    comps = ch._comps(uid)
    for wid, w in comps.items():
        if (w["status"] or "active") != "closed": ensure_fixed(ch, me, wid)
    _recur(ch, me)
    v = ch._view(me)
    units = _units(ch, me)
    fixed = {r["comp_id"]: r for r in ch.db.q("SELECT * FROM ctl_fixed WHERE user_id=?", (uid,))}
    rows = ch.db.q("""SELECT * FROM ctl_tasks WHERE user_id=? AND (status NOT IN ('done','cancelled','skipped','failed') OR kind='fixed' OR updated>?)
                      ORDER BY id DESC LIMIT 400""", (uid, time.time() - 14 * DAY))
    tasks = [_task(ch, r, v) for r in rows]
    from . import control_dispatch as cd  # why each open task isn't moving (or that it is)
    mode, now = ch.mode(uid), time.time()
    busy = RUNS_PER_USER() - ch._busy(uid)
    for r, t in zip(rows, tasks):
        if t["status"] in OPEN or t["status"] == "failed":
            t["why"] = dict(zip(("state", "text"), cd.why(t, r, mode, now, busy)))
            t["why"]["owner"] = cd.owner(t["why"]["state"])  # who moves it next
    origin = {t["ref"]: t["id"] for t in tasks if (t["ref"] or "").startswith("mx:")}
    pre = [_predefined(ch, me, w, fixed.get(wid), units.get(wid), tasks) for wid, w in sorted(comps.items(), key=lambda x: (x[1]["netuid"], x[0]))
           if (w["status"] or "active") != "closed"]
    support = {}
    for s in ch.db.q("SELECT * FROM ctl_mission_teams WHERE user_id=? ORDER BY added", (uid,)): support.setdefault(s["mission"], []).append(s)
    last = {r["mission"]: r["ts"] for r in ch.db.q("SELECT mission, MAX(ts) ts FROM ctl_intel WHERE user_id=? GROUP BY mission", (uid,))}
    for p in pre:
        p["teams"] = _mission_teams(ch, v, p["ref"], units.get(p["comp_id"]), support.get(p["ref"], []), tasks)
        p["schedule"] = _schedule(ch, me, p, mode, last.get(p["ref"]), tasks)
    cus = [_custom(m, origin.get(f"mx:{m['id']}"), comps) for m in _mx_rows(ch, uid)]
    spent = sum(p["used_today"] for p in pre) + (ch.db.q("SELECT COALESCE(SUM(tokens), 0) n FROM ctl_intel WHERE user_id=? AND mission LIKE 'comp:%' AND ts>=?",
                                                        (uid, agent_core._today()), one=True)["n"] or 0)  # the teams' work and Mission Intelligence's reviews
    total = 0
    try: total = int(agent_core.get().spent_today(uid)) if agent_core.get() else 0
    except Exception: total = 0  # noqa: BLE001 - no ledger
    ranks = [p["standing"]["rank"] for p in pre if p.get("standing") and p["standing"].get("rank")]
    bt = {"key": PRIMARY, "name": INITIATIVES[PRIMARY], "primary": True,
          "about": "AXoR's primary initiative: competing on Bittensor subnets. Each competition you take on is a predefined mission.",
          "missions": pre + [c for c in cus if c["initiative"] == PRIMARY],
          "summary": {"subnets": len({p["subnet"] for p in pre}), "predefined": len(pre), "custom": sum(1 for c in cus if c["initiative"] == PRIMARY),
                      "met": sum(1 for p in pre if p["gap"]["state"] == "met"), "behind": sum(1 for p in pre if p["gap"]["state"] == "behind"),
                      "unranked": sum(1 for p in pre if p["gap"]["state"] in ("unknown", "unset")), "best_rank": min(ranks) if ranks else None,
                      "tokens_today": spent, "share_today": round(spent / total, 3) if total else None}}
    other = {"key": "other", "name": INITIATIVES["other"], "primary": False,
             "about": "Custom missions outside Bittensor: goals you give Mission Control.",
             "missions": [c for c in cus if c["initiative"] != PRIMARY]}
    open_ = [t for t in tasks if t["status"] in OPEN]
    counts = {"predefined": len(pre), "custom": len(cus),
              "active": len(pre) + sum(1 for c in cus if c["status"] in MX_ACTIVE),
              "tasks_open": sum(1 for t in open_ if t["status"] != "proposed"),
              "fixed_open": sum(1 for t in open_ if t["kind"] == "fixed"), "dynamic_open": sum(1 for t in open_ if t["kind"] != "fixed" and t["status"] != "proposed"),
              "proposed": sum(1 for t in open_ if t["status"] == "proposed"), "standalone_open": sum(1 for t in open_ if not t["mission"]),
              "in_progress": sum(1 for t in open_ if t["status"] in ("running", "review"))}
    lp = cd.last(uid)
    dispatch = {**cd.summary(open_, now), "on": cd.ENABLED and mode != "manual", "every": cd.DISPATCH_EVERY, "last": lp[0] if lp else None,
                "held": (lp[1].get("held") if lp else None)}
    titles = {p["ref"]: p["title"] for p in pre} | {c["ref"]: c["title"] for c in cus}
    for t in tasks: t["mission_title"] = titles.get(t["mission"]) if t["mission"] else None
    return {"at": time.time(), "mode": mode, "primary": PRIMARY, "initiatives": [bt, other], "tasks": tasks, "counts": counts, "dispatch": dispatch}


def summary(ch, me):
    """The Command Center's figures: missions and tasks counted apart, and the primary initiative's line."""
    d = missions(ch, me)
    bt = d["initiatives"][0]
    return {"counts": d["counts"], "dispatch": d["dispatch"], "initiative": {"key": bt["key"], "name": bt["name"], **bt["summary"]}}


def mission(ch, me, ref):
    m = re.fullmatch(r"(comp|mx):(\d+)", ref or "")
    if not m: raise HTTPException(404, "There's no such mission.")
    d = missions(ch, me)
    ms = next((x for i in d["initiatives"] for x in i["missions"] if x["ref"] == ref), None)
    if not ms: raise HTTPException(404, "There's no such mission, or it's closed.")
    mine = [t for t in d["tasks"] if t["mission"] == ref]
    out = {"mission": ms, "mode": d["mode"],
           "fixed": sorted([t for t in mine if t["kind"] == "fixed"], key=lambda t: ([k for k, *_ in TEMPLATE] + [t["template"]]).index(t["template"]) if t["template"] else 99),
           "dynamic": [t for t in mine if t["kind"] != "fixed" and t["status"] != "proposed"],
           "proposed": [t for t in mine if t["status"] == "proposed"]}
    if m.group(1) == "comp":
        out["custom"] = [c for c in d["initiatives"][0]["missions"] if c.get("parent") == ref]
        last = ch.db.q("SELECT * FROM ctl_intel WHERE user_id=? AND mission=? ORDER BY id DESC LIMIT 1", (me["id"], ref), one=True)
        out["intelligence"] = {**{k: last[k] for k in ("ts", "source", "summary", "tokens", "model", "error", "by_user")},
                               "items": _j(last["items"], []) or [], "revisions": _j(last["revisions"], []) or []} if last else None
    else:
        r = ch.db.q("SELECT plan FROM mx_missions WHERE id=? AND user_id=?", (int(m.group(2)), me["id"]), one=True) if ch._has("mx_missions") else None
        out["plan"] = [{"id": t.get("id"), "title": t.get("title"), "owner": t.get("owner"), "done_when": t.get("done_when"), "depends": t.get("depends") or []}
                       for t in ((_j((r or {}).get("plan"), {}) or {}).get("tasks") or [])]
        out["intelligence"] = None
    return out


# ---------- placing and changing tasks ----------
def place(ch, me, tid, b, u, wid):
    """A new task's level, from POST /api/control/tasks: the parent it's a subtask of, else the mission it serves (a
    Competition team's task serves its predefined mission unless it's made standalone)."""
    uid, ref, parent = me["id"], None, None
    if getattr(b, "parent", None):
        p = ch.db.q("SELECT id, mission FROM ctl_tasks WHERE id=? AND user_id=?", (b.parent, uid), one=True)
        if not p: raise HTTPException(404, "There's no such parent task.")
        parent, ref = p["id"], p["mission"]
    else:
        want = (getattr(b, "mission", "") or "").strip()
        if want == "none": ref = None
        elif want: ref = _check_ref(ch, uid, want)
        elif wid and wid in ch._comps(uid): ref = f"comp:{wid}"
    if ref and ref.startswith("comp:") and u: _join(ch, me, ref, u, "Joined with a task")
    ch.db.q("UPDATE ctl_tasks SET mission=?, parent_id=?, kind='dynamic' WHERE id=?", (ref, parent, tid))


def _join(ch, me, ref, u, duty):
    """A team given a task on a predefined mission it isn't on yet becomes a supporting team (audited). True if it joined."""
    lead = _units(ch, me).get(int(ref.split(":")[1]))
    if lead and lead["id"] == u["id"]: return False
    r = ch.db.q("INSERT OR IGNORE INTO ctl_mission_teams (user_id, mission, unit_id, duty, added, by_user) VALUES (?,?,?,?,?,?) RETURNING unit_id",
                (me["id"], ref, u["id"], _clip(duty, 200), time.time(), me["username"]), one=True)
    if r: ch._audit(me["id"], me["username"], "mission.team.add", ref, f"{u['name']}: {duty}")
    return bool(r)


class TeamIn(BaseModel):
    team: str = Field(min_length=3, max_length=20)   # "u:<unit id>"
    duty: str = Field("", max_length=200)


def add_team(ch, me, ref, b: TeamIn):
    if not re.fullmatch(r"comp:\d+", ref or ""): raise HTTPException(400, "Teams join predefined (Bittensor) missions; a custom mission's engine staffs itself.")
    _check_ref(ch, me["id"], ref)
    u = ch._unit_ref(ch._view(me), b.team)
    if u["kind"] != "team" and not ch._comp_of(u): raise HTTPException(400, "Pick a team, not a department.")
    lead = _units(ch, me).get(int(ref.split(":")[1]))
    if lead and lead["id"] == u["id"]: raise HTTPException(409, "That's the mission's lead team.")
    if not _join(ch, me, ref, u, b.duty.strip() or "Supports the mission"): raise HTTPException(409, f"{u['name']} is on this mission already.")
    return mission(ch, me, ref)


def remove_team(ch, me, ref, team):
    m = re.fullmatch(r"u:(\d+)", team or "")
    r = ch.db.q("DELETE FROM ctl_mission_teams WHERE user_id=? AND mission=? AND unit_id=? RETURNING unit_id", (me["id"], ref, int(m.group(1)) if m else -1), one=True)
    if not r: raise HTTPException(404, "That team isn't supporting this mission.")
    ch._audit(me["id"], me["username"], "mission.team.remove", ref, team)
    return mission(ch, me, ref)


def _check_ref(ch, uid, ref):
    m = re.fullmatch(r"(comp|mx):(\d+)", ref or "")
    ok = m and (int(m.group(2)) in ch._comps(uid) if m.group(1) == "comp" else
                ch._has("mx_missions") and ch.db.q("SELECT 1 FROM mx_missions WHERE id=? AND user_id=?", (int(m.group(2)), uid), one=True))
    if not ok: raise HTTPException(404, "There's no such mission.")
    return ref


def _own(ch, me, tid):
    r = ch.db.q("SELECT * FROM ctl_tasks WHERE id=? AND user_id=?", (tid, me["id"]), one=True)
    if not r: raise HTTPException(404, "There's no such task.")
    return r


def _hist(r, by, what):
    return json.dumps(((_j(r["history"], []) or []) + [{"ts": time.time(), "by": by, "what": what}])[-40:])


def _declared_needs(r):
    """A Control Hub task's declared capabilities, carried onto the board task it becomes (G5 Phase 1); [] when declared none,
    None when undeclared."""
    try: v = json.loads(r.get("needs") or "null")
    except (TypeError, ValueError): return None
    return [str(x) for x in v][:20] if isinstance(v, list) else None  # [] is a declaration too: no external dependency (D-017)


def _to_board(ch, me, r, actor=None):
    """Put a task on its Competition team's board (the Director hands it out); returns the board task id."""
    u = next((x for x in ch._view(me)["units"] if x["id"] == r["unit_id"]), None) if r["unit_id"] else None
    wid = ch._comp_of(u) if u else None
    m = re.fullmatch(r"comp:(\d+)", r["mission"] or "")
    if not wid and u is None and m: wid = int(m.group(1))  # no team yet: the mission's lead team
    if not wid or wid not in ch._comps(me["id"]): raise HTTPException(409, "Only a Competition team has a board: give this task to one of its team's agents.")
    ref = r["mission"] if re.fullmatch(mining_work.MISSION_REF[1:-1], r["mission"] or "") else None  # the board task works for the same mission
    return ch.w._add_task(me, wid, mining_work.TaskIn(title=_clip(r["title"], 160), detail=r["detail"] or "", priority=r["priority"] or "medium", agent=None,
                                                      start=False, mission=ref, needs=_declared_needs(r)), actor=actor)


def run(ch, me, tid):
    """Start a fixed task (or an approved proposal): onto the team's board, or as the agent's run."""
    r = _own(ch, me, tid)
    t = _task(ch, r)
    if t["status"] in ("running", "review"): raise HTTPException(409, "It's under way already.")
    if r["route"] == "agent":
        key = r["agent_key"] or _pick_agent(ch, me, r)
        if not key: raise HTTPException(409, "Nobody on that team can take it: add an agent to the team first.")
        ch.db.q("UPDATE ctl_tasks SET status='todo', agent_key=? WHERE id=?", (key, tid))
        return ch.start_task(me, tid)
    bid = _to_board(ch, me, r)
    ch.db.q("UPDATE ctl_tasks SET ref=?, status='todo', done_at=NULL, history=?, updated=? WHERE id=?",
            (f"mw_task:{bid}" if bid else None, _hist(r, me["username"], "sent to the team's board"), time.time(), tid))
    ch._audit(me["id"], me["username"], "task.run", f"ctl:t{tid}", r["title"])
    return ch.task(me, tid) | {"kind": r["kind"]}


def _pick_agent(ch, me, r):
    """An agent of the task's team with room for it (the team's lead last), else AXoR's recommendation for the team."""
    v = ch._view(me)
    u = next((x for x in v["units"] if x["id"] == r["unit_id"]), None)
    if not u: return None
    sq = set(u.get("squads") or [])
    own = [a for a in v["agents"] if (a["unit_id"] == u["id"] or a["unit_id"] in sq) and a["status"] == "active" and a["load"] < a["cap"]]
    if own: return sorted(own, key=lambda a: (a["key"] == u["manager_key"], a["load"]))[0]["key"]
    from .control_hub import RecommendIn
    picks = ch.recommend(me, f"u:{u['id']}", RecommendIn(skills=re.findall(r"[a-z]{4,}", (r["title"] or "").lower())[:4], size=1)).get("picks") or []
    return picks[0]["key"] if picks else None


class MTaskPatch(BaseModel):
    title: str | None = Field(None, min_length=3, max_length=160)
    detail: str | None = Field(None, max_length=4000)
    priority: str | None = Field(None, pattern="^(high|medium|low)$")
    cadence_days: int | None = Field(None, ge=0, le=365)      # 0: not recurring
    kind: str | None = Field(None, pattern="^fixed$")         # dynamic → fixed (mandatory); fixed never goes back by itself
    mission: str | None = Field(None, max_length=24)          # "none": standalone; "comp:N" / "mx:N"
    skip: bool | None = None                                  # a fixed task this mission doesn't need (False: needed again)


def patch(ch, me, tid, b: MTaskPatch):
    r = _own(ch, me, tid)
    sets, what = {}, []
    if b.title is not None: sets["title"] = b.title.strip(); what.append("renamed")
    if b.detail is not None: sets["detail"] = b.detail.strip(); what.append("detail edited")
    if b.priority is not None and b.priority != r["priority"]: sets["priority"] = b.priority; what.append(f"priority {b.priority}")
    if b.kind == "fixed" and r["kind"] != "fixed":
        if r["status"] == "proposed": raise HTTPException(409, "Approve the proposal first.")
        sets["kind"] = "fixed"; what.append("made a fixed task (mandatory)")
    if b.cadence_days is not None:
        if (sets.get("kind") or r["kind"]) != "fixed": raise HTTPException(400, "Only a fixed task recurs: make it fixed first.")
        sets["cadence_days"] = b.cadence_days or None; what.append(f"recurs every {b.cadence_days} days" if b.cadence_days else "no longer recurs")
    if b.mission is not None:
        if b.mission == "none": sets["mission"] = None; what.append("made standalone")
        else:
            sets["mission"] = _check_ref(ch, me["id"], b.mission)  # its kind and parent stay as they are
            what.append(f"moved to {b.mission}")
    if b.skip is not None:
        if r["kind"] != "fixed": raise HTTPException(400, "Only a fixed task is skipped: cancel a dynamic one.")
        if b.skip and _task(ch, r)["status"] == "running": raise HTTPException(409, "It's running: wait for it first.")
        sets["status"] = "skipped" if b.skip else "todo"; sets["ref"] = None; sets["done_at"] = None
        what.append("skipped: not needed for this mission" if b.skip else "needed again")
    if not sets and not what: return ch.task(me, tid)
    sets["history"], sets["updated"] = _hist(r, me["username"], "; ".join(what)), time.time()
    ch.db.q(f"UPDATE ctl_tasks SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?", (*sets.values(), tid))
    ch._audit(me["id"], me["username"], "task.edit", f"ctl:t{tid}", "; ".join(what))
    return _task(ch, _own(ch, me, tid), ch._view(me))


def decide(ch, me, tid, ok):
    """A Mission Intelligence proposal (manual mode): approved, it goes on the team's board; declined, it's closed."""
    r = _own(ch, me, tid)
    if r["status"] != "proposed": raise HTTPException(409, "It isn't waiting for a decision.")
    if not ok:
        ch.db.q("UPDATE ctl_tasks SET status='cancelled', summary='Declined.', history=?, updated=? WHERE id=?", (_hist(r, me["username"], "declined"), time.time(), tid))
        ch._audit(me["id"], me["username"], "task.decline", f"ctl:t{tid}", r["title"])
        return {"ok": True, "status": "cancelled"}
    ch.db.q("UPDATE ctl_tasks SET status='todo', history=?, updated=? WHERE id=?", (_hist(r, me["username"], "approved"), time.time(), tid))
    ch._audit(me["id"], me["username"], "task.approve", f"ctl:t{tid}", r["title"])
    return run(ch, me, tid)


# ---------- Mission Intelligence ----------
def _signals(ch, me, ms, open_):
    """The results Mission Intelligence reads, and what they call for without a model (its fallback)."""
    uid, q, now = me["id"], ch.db.q, time.time()
    s, g, tgt = ms.get("standing") or {}, ms["gap"], ms.get("target_rank")
    alerts, failed = [], []
    if ch._has("mh_alerts") and "created" in ch._cols("mh_alerts"):
        alerts = q("""SELECT a.level, a.title, a.detail FROM mh_alerts a JOIN mw_comps w ON w.campaign_id=a.campaign_id WHERE w.id=? AND a.status='open'
                      ORDER BY a.id DESC LIMIT 5""", (ms["comp_id"],))
    if ch._has("ac_runs"):
        keys = [k for k in [a["key"] for a in ch._view(me)["agents"] if a["unit_id"] == (int(ms["unit"][2:]) if ms.get("unit") else -1)]]
        if keys:
            failed = q(f"""SELECT title, error FROM ac_runs WHERE owner_id=? AND status IN ('failed','lost') AND started>? AND agent_key IN ({','.join('?' * len(keys))})
                           ORDER BY id DESC LIMIT 6""", (uid, now - 7 * DAY, *keys))
    calls = []
    if g["state"] == "behind":
        calls.append(("Close the gap to the top %d" % tgt, f"Compare our miner with the ones ranked {tgt} to {g['rank'] - 1}: what they do better, and the change that would gain most.",
                      "high", g["text"]))
    elif g["state"] == "unknown":
        calls.append(("Get the miner ranked and tracked", "Make sure the miner is registered by you, scored by validators, and its hotkey is on My subnets so the team sees its rank.",
                      "high", g["text"]))
    elif g["state"] == "met":
        calls.append((f"Guard the top {tgt}", "Watch new entrants and our own regressions since the last brief; report what threatens the rank.", "low", g["text"]))
    if failed:
        calls.append(("Investigate this week's failed runs", "Find what the failed runs have in common and fix the cause: " + "; ".join(_clip(f["title"] or f["error"], 60) for f in failed[:3]),
                      "high", f"{len(failed)} failed run(s) in 7 days"))
    for a in alerts[:2]:
        calls.append((_clip(f"Look into: {a['title']}", 120), _clip(a["detail"] or a["title"], 600), "high" if a["level"] == "critical" else "medium", "An open alert on the competition"))
    return {"standing": s, "gap": g, "alerts": alerts, "failed": failed, "calls": calls}


def intelligence(ch, me, ref, by=None):
    """Read a predefined mission's results and propose (manual) or create (hybrid/auto) the dynamic tasks they call for.
    `by`: "schedule" for the scheduled review (Auto mode), else the user who asked."""
    key = (me["id"], ref)
    with _lock:
        if key in _running: raise HTTPException(409, "Mission Intelligence is reviewing this mission already.")
        _running.add(key)
    try: return _review(ch, me, ref, by)
    finally:
        with _lock: _running.discard(key)


def _review(ch, me, ref, by=None):
    if not re.fullmatch(r"comp:\d+", ref or ""): raise HTTPException(400, "Mission Intelligence works on predefined (Bittensor) missions; a custom mission's engine plans its own tasks.")
    d = mission(ch, me, ref)
    ms, uid, mode = d["mission"], me["id"], d["mode"]
    open_ = [t for t in d["fixed"] + d["dynamic"] + d["proposed"] if t["status"] in OPEN]
    sig = _signals(ch, me, ms, open_)
    from . import orchestrator  # Adaptive → Mission: what the loop learned (failure classes, changes measured or promoted, best models, lessons)
    g = orchestrator.guidance(uid, f"{ms['title']} {ms['objective'] or ''}") or {}
    learned = (g.get("lines") or [])[:8]
    top = next((f for f in g.get("failures") or [] if f["n"] >= 3), None)
    if top:
        sig["calls"].append((_clip(f"Plan around '{top['label']}' failures", 120), _clip(f"{top['n']} recent runs failed as '{top['label']}'. {top['fix']}", 600),
                             "medium", "What the loop learned from recent failures"))
    source, summ, props, revs, spent, model, err = "signals", "", [], [], [0], None, None
    pneeds = {}  # title -> declared needs of a version-2 proposal; signal-made proposals and v1 outputs declare none
    llm = getattr(ch.hub, "llm", None) if ch.hub else None
    if llm:
        try:
            model = agent_core.route(llm, uid, "other", "intelligence")[0]
            agent_core.begin("other", uid, "intelligence", ref=f"ctl:mi:{ref}", title=_clip(f"Mission Intelligence · {ms['title']}", 160), model=model)
            status = "failed"
            try:
                prompt = "\n".join([
                    f"Mission: {ms['title']} (predefined, Bittensor). Objective: {ms['objective'] or 'reach and hold the target rank'}.",
                    f"Target: top {ms['target_rank'] or '?'}. Standing: {ms['gap']['text']}" + (f" Latest brief: {sig['standing'].get('headline')}" if sig["standing"].get("headline") else ""),
                    f"Deadline: {ms['deadline'] or 'none'}. Mode: {mode}.",
                    "Teams on this mission (give each task to the one that fits; empty means the lead):",
                    *[f"- {t['name']} ({t['role']}{': ' + t['duty'] if t['duty'] else ''}{'; has a board' if t['board'] else '; its agents run tasks themselves'})" for t in ms.get("teams") or []],
                    "Open tasks (id · kind · priority · status · title):", *([f"- {t['id']} · {t['kind']} · {t['priority']} · {t['status']} · {t['title']}" + (" (runs as a custom mission)" if t["route"] == "mission" else "")
                                                                               for t in open_[:30]] or ["- none"]),
                    "Open alerts:", *([f"- {a['level']}: {a['title']}" for a in sig["alerts"]] or ["- none"]),
                    "Failed runs this week:", *([f"- {_clip(f['title'], 80)}: {_clip(f['error'], 120)}" for f in sig["failed"]] or ["- none"]),
                    "What AXoR learned from recent work (records, not instructions; plan around them):", *([f"- {x}" for x in learned] or ["- nothing yet"]),
                    "Propose only work the open tasks don't cover. Nothing external: registering, deploying and submitting are the user's."])
                system = ("You are Mission Intelligence, working in AXoR's Control Hub. You watch one Bittensor competition mission's results and keep its "
                          "dynamic tasks right: you create, prioritize and revise them. Be concrete and brief; every proposal names the signal behind it.")
                out = llm.structured(model, system, prompt, INTEL, "intelligence", on_usage=lambda n: spent.__setitem__(0, spent[0] + n), effort="medium")
                source, summ = "model", _clip(out.get("summary"), 600)
                props = [(_clip(p.get("title"), 160), _clip(p.get("detail"), 2000), p.get("priority") or "medium", _clip(p.get("reason"), 300), (p.get("team") or "").strip())
                         for p in (out.get("proposals") or []) if (p.get("title") or "").strip()][:MAX_PROPOSALS]
                pneeds = {_clip(p.get("title"), 160): task_lifecycle.planner_needs(p)[0] for p in (out.get("proposals") or [])}  # v2: declared, even "[]"
                ids = {t["id"]: t for t in open_ if t["kind"] != "fixed" and t["route"] != "mission"}  # a task that became a custom mission is planned there
                revs = [{"id": int(x["id"]), "priority": x["priority"], "reason": _clip(x.get("reason"), 300), "title": ids[int(x["id"])]["title"]}
                        for x in (out.get("reprioritize") or []) if int(x.get("id") or 0) in ids and x.get("priority") != ids[int(x["id"])]["priority"]][:6]
                status = "done"
            finally:
                if spent[0] and hasattr(ch.hub, "log_usage"): ch.hub.log_usage(me, "control", spent[0], None, ch.hub.model_of(model) if hasattr(ch.hub, "model_of") else model)
                agent_core.end(status, tokens=spent[0])
        except (LLMError, HTTPException, ValueError, KeyError, TypeError) as e:
            err = _clip(getattr(e, "detail", None) or str(e), 300)
            log.info("mission intelligence %s: %s", ref, err)
    if source == "signals":
        props = [(*c, "") for c in sig["calls"][:MAX_PROPOSALS]]
        summ = ms["gap"]["text"] + (" No model answered, so these come from the mission's signals." if err or not llm else "")
    items, unit, teams = [], ms.get("unit"), ms.get("teams") or []
    def team_of(name):
        n = name.lower()
        t = next((t for t in teams if n and t["name"].lower() == n), None) or next((t for t in teams if n and (n in t["name"].lower() or t["name"].lower() in n)), None)
        return t or next((t for t in teams if t["role"] == "lead"), None)
    taken = [t["title"] for t in open_]
    for title, detail, prio, reason, tname in props:
        tm = team_of(tname)
        tref, board = (tm["ref"], tm["board"]) if tm else (unit, True)
        if any(_similar(title, x) for x in taken):
            items.append({"title": title, "reason": reason, "priority": prio, "outcome": "covered", "team": tm["name"] if tm else None}); continue
        taken.append(title)
        tid = None
        if mode != "manual" and tref:
            from .control_hub import TaskIn
            try:
                tid = ch.add_task(me, TaskIn(team=tref, title=title if len(title) >= 3 else title + " …", detail=f"{detail}\n\nWhy: {reason}".strip(), priority=prio,
                                             agent="auto", route="board" if board else "agent", start=False, mission=ref))["id"]
                ch.db.q("UPDATE ctl_tasks SET origin='intelligence' WHERE id=?", (tid,))
                if pneeds.get(title) is not None: ch.db.q("UPDATE ctl_tasks SET needs=? WHERE id=?", (pneeds[title], tid))
                items.append({"title": title, "reason": reason, "priority": prio, "outcome": "created", "task": tid, "team": tm["name"] if tm else None}); continue
            except HTTPException as e:
                log.info("mission intelligence %s: couldn't create %r: %s", ref, title, e.detail)
        now = time.time()
        tid = ch.db.q("""INSERT INTO ctl_tasks (user_id, unit_id, title, detail, priority, route, status, origin, history, by_user, created, updated, mission, kind)
                         VALUES (?,?,?,?,?,?,'proposed','intelligence',?,?,?,?,?,'dynamic') RETURNING id""",
                      (uid, int(tref[2:]) if tref else None, title, f"{detail}\n\nWhy: {reason}".strip(), prio, "board" if board else "agent",
                       json.dumps([{"ts": now, "by": "Mission Intelligence", "what": f"proposed: {reason}"}]), "Mission Intelligence", now, now, ref), one=True)["id"]
        if pneeds.get(title) is not None: ch.db.q("UPDATE ctl_tasks SET needs=? WHERE id=?", (pneeds[title], tid))
        items.append({"title": title, "reason": reason, "priority": prio, "outcome": "proposed", "task": tid, "team": tm["name"] if tm else None})
    for x in revs:
        x["outcome"] = "suggested"
        if mode != "manual":
            r = ch.db.q("SELECT * FROM ctl_tasks WHERE id=? AND user_id=?", (x["id"], uid), one=True)
            if r:
                ch.db.q("UPDATE ctl_tasks SET priority=?, history=?, updated=? WHERE id=?", (x["priority"], _hist(r, "Mission Intelligence", f"priority {x['priority']}: {x['reason']}"), time.time(), x["id"]))
                x["outcome"] = "applied"
    iid = ch.db.q("""INSERT INTO ctl_intel (user_id, mission, ts, source, summary, items, revisions, tokens, model, error, by_user) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                     RETURNING id""", (uid, ref, time.time(), source, summ, json.dumps(items), json.dumps(revs), spent[0], model, err, by or me["username"]), one=True)["id"]
    if learned: orchestrator.guided(uid, None, g, corr=ref, key=f"ctl:mi:{iid}:guided")
    ch._audit(uid, "Mission Intelligence", "mission.intelligence", ref, ("Scheduled review: " if by == "schedule" else "") +
              f"{sum(1 for i in items if i['outcome'] == 'created')} created, {sum(1 for i in items if i['outcome'] == 'proposed')} proposed, {len(revs)} priority change(s)"
              + (f", planned with {len(learned)} learned record(s)" if learned else ""))
    return mission(ch, me, ref)


class DecideIn(BaseModel):
    ok: bool


def _owner(ch, uid):
    return ch.db.q("SELECT id, username, role FROM users WHERE id=?", (uid,), one=True) if ch._has("users") else None


def tick(ch, now=None):
    """The scheduled review: each Auto-mode user's predefined missions that are due and not held. Returns how many ran."""
    if EVERY_H <= 0: return 0
    now, n = now or time.time(), 0
    for s in ch.db.q("SELECT user_id FROM ctl_settings WHERE mode='auto'"):
        me = _owner(ch, s["user_id"])
        if not me: continue
        try:
            if ch.hub and hasattr(ch.hub, "gate"): me = ch.hub.gate(dict(me)) or me
            d = missions(ch, me)
        except HTTPException: continue  # no agent access any more
        except Exception as e:  # noqa: BLE001 - one user's trouble doesn't stop the others
            log.warning("mission schedule: user %s: %s", s["user_id"], e); continue
        for ms in d["initiatives"][0]["missions"]:
            sch = ms.get("schedule") or {}
            if ms["type"] != "predefined" or not sch.get("on") or sch.get("hold") or (sch.get("next") and sch["next"] > now): continue
            try: intelligence(ch, me, ms["ref"], by="schedule"); n += 1
            except HTTPException as e: log.info("mission schedule %s: %s", ms["ref"], e.detail)
            except Exception as e:  # noqa: BLE001
                log.warning("mission schedule %s: %s", ms["ref"], e)
    return n


def start(ch):
    """Runs tick() every TICK seconds and the task dispatcher (control_dispatch.tick) every DISPATCH_EVERY seconds in the
    background (once per process)."""
    global _thread
    from . import control_dispatch as cd
    review = EVERY_H > 0 and os.getenv("CONTROL_INTEL_SCHEDULE", "1") == "1"
    if _thread: return  # always: with neither the schedule nor the dispatcher on, the pass still syncs end states
    def loop():
        step = min(TICK, cd.DISPATCH_EVERY) if cd.ENABLED else TICK
        time.sleep(min(TICK / 2, step))
        nxt = time.time() + (TICK / 2 if review else 0)
        while True:
            try: cd.tick(ch)  # with the dispatcher off it only syncs board/mission end states into ctl_tasks
            except Exception as e:  # noqa: BLE001 - the loop keeps going
                log.warning("task dispatch: %s", e)
            if review and time.time() >= nxt:
                try: tick(ch)
                except Exception as e:  # noqa: BLE001 - the loop keeps going
                    log.warning("mission schedule: %s", e)
                nxt = time.time() + TICK
            time.sleep(step)
    _thread = threading.Thread(target=loop, name="mission-intel", daemon=True)
    _thread.start()


def mount(r, ch, user):
    """Adds the routes to the Control Hub's router (control_hub.build), and starts the scheduled review."""
    ensure_schema(ch.db)
    start(ch)

    @r.post("/missions/{ref}/teams")
    def add_team_(ref: str, b: TeamIn, req: Request): return add_team(ch, user(req), ref, b)

    @r.delete("/missions/{ref}/teams/{team}")
    def remove_team_(ref: str, team: str, req: Request): return remove_team(ch, user(req), ref, team)

    @r.get("/missions")
    def missions_(req: Request): return missions(ch, user(req))

    @r.get("/missions/{ref}")
    def mission_(ref: str, req: Request): return mission(ch, user(req), ref)

    @r.post("/missions/{ref}/intelligence")
    def intel_(ref: str, req: Request): return intelligence(ch, user(req), ref)

    @r.post("/mission-tasks/{tid}/run")
    def run_(tid: int, req: Request): return run(ch, user(req), tid)

    @r.patch("/mission-tasks/{tid}")
    def patch_(tid: int, b: MTaskPatch, req: Request): return patch(ch, user(req), tid, b)

    @r.post("/mission-tasks/{tid}/decide")
    def decide_(tid: int, b: DecideIn, req: Request): return decide(ch, user(req), tid, b.ok)
