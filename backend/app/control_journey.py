"""Model routing and work journeys in the Control Hub (control-journey.js; /api/control/routing, /journeys, /journey/{ref}).

Two read-only views over what the systems already record. Nothing here calls a model or changes a row.

- Model routing: the owner's pool as the router sees it now (each model's provider connected? can this person use it?), what
  each (system, kind of work) ran on last and why (ac_runs.decision, written by agent_core.route/begin), what the router
  would pick for it now (a dry run of model_router.rank on the same statistics, which is pure), how often a run fell back to
  the default model, and each model's runs, failures, time, tokens, cost and scores.
- Journey: one piece of work from where it started to where it is now, as ordered steps (done / current / waiting / failed /
  pending / skipped), each with who, when, the model runs it made and the routing decision behind each. Two kinds of ref:
  "ctl:t<id>" (a Control Hub task: created → sent to → assigned → the work on its route → your review) and "mx:<id>" (a
  mission: its origin, then UNDERSTAND … LEARN). A task sent to Mission Control continues with its mission's stages.
"""
import json, time

from fastapi import HTTPException, Request

from . import agent_core, model_router

DAY = 86400
TLABEL = {"agent": "Agent run", "board": "Team board", "mission": "Mission Control"}
SRC = {"routed": "Routed", "picked": "Picked", "fallback": "Fell back", "no_pool": "Default model"}
MX_LABEL = {"understand": "Understand", "discover": "Discover", "plan": "Plan", "allocate": "Allocate", "execute": "Execute",
            "verify": "Verify", "deliver": "Deliver", "learn": "Learn"}
MX_ABOUT = {"understand": "Turns the goal into targets, criteria and an engine", "discover": "Earlier work, lessons and an intelligence brief",
            "plan": "The tasks and their order", "allocate": "Models and budget for the engine", "execute": "The engine does the work",
            "verify": "An independent check against each criterion", "deliver": "The report", "learn": "Lessons for the next missions"}
BOARD = {"todo": "pending", "queued": "current", "working": "current", "running": "current", "checking": "current", "review": "done",
         "done": "done", "failed": "failed", "error": "failed", "cancelled": "skipped"}


def _j(s, d=None):
    if not s: return d
    try: return json.loads(s)
    except (TypeError, ValueError): return d


def _clip(s, n):
    s = str(s or "")
    return s if len(s) <= n else s[:n - 1] + "…"


def _has(db, t): return bool(db.q("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,), one=True))


def _short(model): return (model or "").partition(":")[2] or (model or "")


def _same(a, b): return bool(a and b) and (a == b or _short(a) == _short(b))


# ---------- model routing ----------
def routing(ch, me):
    db, uid, llm, core = ch.db, me["id"], ch.hub.llm if ch.hub else None, agent_core.get()
    now = time.time()
    shared = core.pool(uid) if core else {"pool": [], "weights": "balanced"}
    pool = model_router.effective(shared["pool"])
    has_runs = _has(db, "ac_runs")
    week = {}
    if has_runs:
        for r in db.q("""SELECT model, COUNT(*) n, SUM(status='failed') failed, SUM(status='running') running, AVG(CASE WHEN finished IS NOT NULL THEN finished-started END) latency,
                                SUM(tokens) tokens, AVG(score) score, COUNT(score) scored, MAX(started) last, SUM(cost) cost
                         FROM ac_runs WHERE owner_id=? AND model IS NOT NULL AND model!='' AND started>=? GROUP BY model""", (uid, now - 7 * DAY)):
            week[r["model"]] = dict(r)

    def price_of(m):
        hit = next((p for p in pool if _same(p["model"], m)), None)
        return hit["price"] if hit else model_router.guess(m if ":" in m else f"x:{m}")[1]

    models = []
    for p in pool:
        prov = p["model"].partition(":")[0]
        connected, why = False, ""
        try: connected = bool(llm and llm.configured(prov))
        except Exception as e: why = str(e)  # noqa: BLE001 - shown, never fatal
        usable = connected
        if connected:
            try: llm.resolve(p["model"])
            except Exception as e: usable, why = False, str(getattr(e, "detail", None) or e)  # noqa: BLE001 - e.g. a plan with no login for you
        elif not why: why = "Its provider isn't connected (Agents → Models)."
        st = next((v for k, v in week.items() if _same(k, p["model"])), None) or {}
        models.append({"model": p["model"], "tier": p["tier"], "price": p["price"], "connected": connected, "usable": usable, "why": _clip(why, 220),
                       "in_pool": True, **_mstats(st, p["price"])})
    for k, st in sorted(week.items(), key=lambda x: -(x[1]["n"] or 0)):  # models runs used that aren't in the pool (picked, or the default)
        if any(_same(k, p["model"]) for p in pool): continue
        tier = model_router.guess(k if ":" in k else f"x:{k}")[0]
        models.append({"model": k, "tier": tier, "price": price_of(k), "connected": None, "usable": None, "why": "", "in_pool": False, **_mstats(st, price_of(k))})

    counts, recent, lanes, unrecorded = {s: 0 for s in SRC}, [], [], 0
    if has_runs:
        for r in db.q("SELECT decision, COUNT(*) n FROM ac_runs WHERE owner_id=? AND started>=? AND kind!='earlier' GROUP BY decision IS NULL, json_extract(decision, '$.source')",
                      (uid, now - DAY)):
            src = (_j(r["decision"], {}) or {}).get("source") if r["decision"] else None
            if src in counts: counts[src] += r["n"]
            elif not r["decision"]: unrecorded += r["n"]
        for r in db.q("""SELECT id, system, kind, ref, title, model, status, decision, started, finished, tokens FROM ac_runs
                         WHERE owner_id=? AND decision IS NOT NULL ORDER BY id DESC LIMIT 30""", (uid,)):
            recent.append(_run_out(r))
        # each (system, kind) that recorded a decision in the last 30 days: what it ran on last, and what the router picks now
        live = [p for p in pool if next((m for m in models if m["model"] == p["model"]), {}).get("connected")]
        stats_cache = {}
        for r in db.q("""SELECT system, kind, MAX(id) last_id, COUNT(*) n FROM ac_runs WHERE owner_id=? AND decision IS NOT NULL AND started>=?
                         GROUP BY system, kind ORDER BY MAX(id) DESC LIMIT 40""", (uid, now - 30 * DAY)):
            last = db.q("SELECT id, system, kind, ref, title, model, status, decision, started, finished, tokens FROM ac_runs WHERE id=?", (r["last_id"],), one=True)
            lane = {"system": r["system"], "label": agent_core.SYSTEMS.get(r["system"], r["system"]), "kind": r["kind"], "runs": r["n"], "last": _run_out(last), "now": None}
            if live and lane["last"]["source"] in ("routed", "fallback", "no_pool"):
                try:
                    if r["system"] not in stats_cache: stats_cache[r["system"]] = core.stats(uid, r["system"]) if core else {}
                    m, d = model_router.rank(live, stats_cache[r["system"]], r["kind"], shared["weights"])
                    est = " (An estimate from the run ledger: the Workforce routes on its own run statistics.)" if r["system"] == "workforce" else ""
                    lane["now"] = {"model": m, "reason": d["reason"] + est, "changed": not _same(m, lane["last"]["model"]), "estimate": bool(est)}
                except Exception as e:  # noqa: BLE001 - one lane never stops the panel
                    lane["now"] = {"model": None, "reason": f"Can't rank now: {e}", "changed": False}
            lanes.append(lane)
    return {"weights": shared["weights"], "weights_about": dict(zip(("quality", "cost", "time", "failures"), model_router.WEIGHTS.get(shared["weights"], model_router.WEIGHTS["balanced"]))),
            "pool": models, "pool_size": len(pool), "usable": sum(1 for m in models if m["in_pool"] and m["usable"]),
            "counts": counts, "unrecorded": unrecorded, "lanes": lanes, "recent": recent,
            "fallbacks": [x for x in recent if x["source"] == "fallback" and x["started"] >= now - DAY]}


def _mstats(st, price):
    n = st.get("n") or 0
    tokens = st.get("tokens") or 0
    cost = st.get("cost") if st.get("cost") else tokens * (price or 0) / 1e6
    return {"runs": n, "failed": st.get("failed") or 0, "running": st.get("running") or 0, "fail_rate": round((st.get("failed") or 0) / n, 3) if n else None,
            "latency": round(st["latency"], 1) if st.get("latency") else None, "tokens": tokens, "cost": round(cost, 4),
            "score": round(st["score"], 1) if st.get("score") is not None else None, "scored": st.get("scored") or 0, "last": st.get("last")}


def _run_out(r):
    d = _j(r["decision"], None) if "decision" in r.keys() else None
    return {"id": r["id"], "system": r["system"], "label": agent_core.SYSTEMS.get(r["system"], r["system"]), "kind": r["kind"], "ref": r["ref"],
            "title": r["title"], "model": r["model"], "status": r["status"], "started": r["started"], "finished": r["finished"], "tokens": r["tokens"],
            "secs": round(r["finished"] - r["started"], 1) if r["finished"] and r["started"] else None,
            "source": (d or {}).get("source"), "decision": d}


# ---------- journeys ----------
def _runs(db, uid, refs, kinds=None):
    refs = [x for x in refs if x]
    if not refs or not _has(db, "ac_runs"): return []
    extra = f" AND kind IN ({','.join('?' * len(kinds))})" if kinds else ""
    rows = db.q(f"""SELECT id, system, kind, ref, title, model, status, decision, started, finished, tokens FROM ac_runs
                    WHERE owner_id=? AND ref IN ({','.join('?' * len(refs))}){extra} ORDER BY id LIMIT 60""", (uid, *refs, *(kinds or ())))
    return [_run_out(r) for r in rows]


def _step(key, label, status, ts=None, who="", text="", note="", runs=None, items=None, about=""):
    return {"key": key, "label": label, "status": status, "ts": ts, "who": who, "text": text, "note": note, "runs": runs or [], "items": items or [], "about": about}


def _now(steps, status, label, text, waiting_on=""):
    cur = next((s for s in steps if s["status"] in ("current", "waiting", "failed")), None)
    if not cur: cur = next((s for s in steps if s["status"] == "pending"), None)  # nothing under way: the next step
    if not cur and all(s["status"] in ("done", "skipped") for s in steps): cur = steps[-1] if steps else None
    return {"status": status, "label": label, "text": text, "waiting_on": waiting_on, "step": cur["key"] if cur else None,
            "done": sum(1 for s in steps if s["status"] == "done"), "total": len(steps)}


def journey(ch, me, ref):
    ref = (ref or "").strip()
    if ref.startswith("ctl:t") and ref[5:].isdigit(): return _task_journey(ch, me, int(ref[5:]))
    if ref.startswith("mx:") and ref[3:].isdigit(): return _mission_journey(ch, me, int(ref[3:]))
    raise HTTPException(400, "A journey is for a Control Hub task (ctl:t<id>) or a mission (mx:<id>).")


def _task_journey(ch, me, tid):
    db, uid = ch.db, me["id"]
    r = db.q("SELECT * FROM ctl_tasks WHERE id=? AND user_id=?", (tid, uid), one=True)
    if not r: raise HTTPException(404, "There's no such task.")
    v = ch._view(me)
    t = ch._task_out(r, v)
    hist = t["history"]
    unit = next((u for u in v.get("units", []) if u.get("id") == r["unit_id"]), None) if isinstance(v, dict) else None
    uname = (unit or {}).get("name") or _unit_name(db, r["unit_id"])
    first = hist[0] if hist else {}
    steps = [_step("origin", "Started", "done", r["created"], r["by_user"] or "you",
                   f"{r['by_user'] or 'You'} created it in the Control Hub" + (f" · {first.get('what')}" if first.get("what") and first.get("what") != "created" else ""),
                   _clip(r["detail"], 300))]
    why = {"board": "A Competition team's work goes on its board, where the team's Director hands it out.",
           "agent": "One agent does it here and hands it back for your review.",
           "mission": "Mission Control runs it as a mission: understand, plan, an engine, an independent check."}.get(r["route"], "")
    steps.append(_step("route", "Sent to", "done", r["created"], "", f"{TLABEL.get(r['route'], r['route'])}" + (f" · {uname}" if uname else ""), why))
    st, now = t["status"], None
    if r["route"] == "mission":
        mid = int(r["ref"].split(":")[1]) if (r["ref"] or "").startswith("mx:") else None
        if mid and ch.mx:
            try:
                mj = _mission_journey(ch, me, mid, from_task=r)
                steps += [s for s in mj["steps"] if s["key"] != "origin"]
                return {"ref": f"ctl:t{tid}", "kind": "task", "route": r["route"], "title": r["title"], "unit": uname, "status": st, "mission": mid,
                        "steps": steps, "now": mj["now"], "updated": max(r["updated"] or 0, mj.get("updated") or 0)}
            except HTTPException:
                pass
        steps.append(_step("mission", "Mission", "failed", r["updated"], "", "The mission isn't there any more." if mid else "No mission was created for it."))
        now = _now(steps, st, "Not running", steps[-1]["text"])
    elif r["route"] == "board":
        mt = None
        if (r["ref"] or "").startswith("mw_task:") and _has(db, "mw_tasks"):
            mt = db.q("SELECT * FROM mw_tasks WHERE id=?", (int(r["ref"].split(":")[1]),), one=True)
        if not mt:
            steps.append(_step("board", "On the board", "failed", r["updated"], "", "The board task isn't there any more."))
            now = _now(steps, st, "Not on the board", "The board task was deleted or never created.")
        else:
            keys = mt.keys()
            agent = db.q("SELECT name, title FROM mw_agents WHERE id=?", (mt["agent_id"],), one=True) if mt["agent_id"] and _has(db, "mw_agents") else None
            steps.append(_step("assign", "Assigned", "done" if agent else ("waiting" if mt["status"] == "todo" else "done"), mt["created"] if "created" in keys else None,
                               agent["name"] if agent else "", f"{agent['name']}, {agent['title']}" if agent else "Not yet: the team's Director hands it out",
                               "" if agent else "The Director assigns board work on the team's next plan."))
            mruns, items = [], []
            if _has(db, "mw_runs"):
                for x in db.q("SELECT * FROM mw_runs WHERE task_id=? ORDER BY id LIMIT 30", (mt["id"],)):
                    items.append({"label": f"{(x['kind'] or 'run').capitalize()}" + (f": {_clip(x['summary'], 120)}" if x["summary"] else ""), "status": x["status"],
                                  "ts": x["started"], "error": _clip(x["error"], 200)})
                    mruns.append(f"mw:{x['id']}")
            work = BOARD.get(mt["status"], "current")
            if mt["status"] == "todo" and (mt["question"] if "question" in keys else None): work = "waiting"
            steps.append(_step("work", "Work", work if work != "done" or mt["status"] != "review" else "done", mt["updated"] if "updated" in keys else None,
                               agent["name"] if agent else "", _clip(mt["summary"], 240) if "summary" in keys and mt["summary"] else {"todo": "Not started", "queued": "Queued",
                               "working": "Working on it", "review": "Delivered for review", "done": "Done"}.get(mt["status"], mt["status"]),
                               _clip(mt["question"], 240) if "question" in keys and mt["question"] else "", _runs(db, uid, mruns), items))
            rv = {"review": "current", "done": "done"}.get(mt["status"], "skipped" if mt["status"] in ("cancelled",) else "pending")
            steps.append(_step("review", "Review", rv, mt["done_at"] if "done_at" in keys else None, "the team's reviewer",
                               {"current": "The team's reviewer checks it", "done": "Accepted"}.get(rv, "After the work")))
            label = {"todo": "Waiting to start", "queued": "Queued", "working": "Working", "review": "In review", "done": "Done"}.get(mt["status"], mt["status"])
            wait = "you: answer its question on the board" if work == "waiting" else ""
            now = _now(steps, st, label, _clip(mt["question"], 200) if wait else steps[-2]["text"], wait)
    else:  # an agent's own run, here
        name = t.get("agent") or ""
        steps.append(_step("assign", "Assigned", "done" if r["agent_key"] else "waiting", r["created"], name,
                           f"{name}" + (" (picked by AXoR)" if r["origin"] == "AXoR" else "") if name else "Nobody yet: pick the agent who does it"))
        runs = _runs(db, uid, [f"ctl:t{tid}"])
        work = {"running": "current", "review": "done", "done": "done", "needs_input": "waiting", "failed": "failed", "cancelled": "skipped"}.get(st, "pending")
        steps.append(_step("work", "Work", work, r["updated"] if work != "pending" else None, name,
                           _clip(r["summary"], 240) or {"pending": "Not started", "current": "Working on it"}.get(work, ""), "", runs,
                           [{"label": h["what"], "status": "", "ts": h["ts"], "by": h.get("by")} for h in hist[1:]][-8:]))
        rv = {"review": "current", "done": "done", "cancelled": "skipped"}.get(st, "pending")
        steps.append(_step("review", "Your review", rv, r["updated"] if rv != "pending" else None, "you",
                           {"current": "Accept it, or send it back with a note", "done": "Accepted", "skipped": "Cancelled"}.get(rv, "After the work")))
        label = {"todo": "Not started", "running": "Working", "review": "Waiting for your review", "needs_input": "Needs you", "failed": "Failed",
                 "done": "Done", "cancelled": "Cancelled"}.get(st, st)
        wait = "you" if st in ("review", "needs_input") else ""
        now = _now(steps, st, label, _clip(r["summary"], 240) if st in ("needs_input", "failed", "review") else "", wait)
    return {"ref": f"ctl:t{tid}", "kind": "task", "route": r["route"], "title": r["title"], "unit": uname, "status": st, "steps": steps, "now": now,
            "updated": r["updated"]}


def _unit_name(db, unit_id):
    if not unit_id or not _has(db, "og_units"): return ""
    u = db.q("SELECT name FROM og_units WHERE id=?", (unit_id,), one=True)
    return u["name"] if u else ""


def _mission_journey(ch, me, mid, from_task=None):
    if not ch.mx: raise HTTPException(409, "Mission Control isn't running on this server.")
    db, uid = ch.db, me["id"]
    s = ch.mx.state(me, mid)  # 404 unless it's yours
    m, events, stages = s["mission"], s["events"], list(s["stages"])
    if from_task is None:
        from_task = db.q("SELECT id, title, by_user, created FROM ctl_tasks WHERE user_id=? AND ref=?", (uid, f"mx:{mid}"), one=True) if _has(db, "ctl_tasks") else None
    origin = (f"From the Control Hub task “{_clip(from_task['title'], 80)}”" if from_task else "Started in Mission Control")
    steps = [_step("origin", "Started", "done", m["created"], (from_task or {})["by_user"] if from_task else "you", origin, _clip(m["goal"], 300))]
    stage, status = m["stage"] if m["stage"] in stages else stages[0], m["status"]
    idx = stages.index(stage)
    finished = status in ("delivered", "failed", "cancelled")
    by_stage = {}
    for e in events: by_stage.setdefault(e["stage"], []).append(e)
    runs = _runs(db, uid, [f"mx:{mid}"])
    child_runs, child_items = [], []
    if m.get("child") is not None and m.get("engine"):
        child_runs, child_items = _child(db, uid, m)
    for i, k in enumerate(stages):
        if status == "delivered": stt = "done"
        elif i < idx: stt = "done"
        elif i == idx:
            stt = {"queued": "current", "running": "current", "needs_input": "waiting", "paused": "waiting", "failed": "failed", "cancelled": "skipped"}.get(status, "current")
        else: stt = "skipped" if finished else "pending"
        ev = by_stage.get(k, [])
        text = ev[-1]["text"] if ev else ("" if stt == "pending" else MX_ABOUT.get(k, ""))
        if k == "execute" and m.get("engine"):
            eng = s["engines"].get(m["engine"], m["engine"])
            text = f"Planned: {eng}" if stt == "pending" else eng + (f" · attempt {m['attempts']}" if (m.get("attempts") or 0) > 1 else "") + (f" · {text}" if ev else "")
        if i == idx and status in ("needs_input", "paused"): note = m.get("doing") or m.get("pause_reason") or ""
        elif i == idx and status == "failed": note = m.get("error") or m.get("doing") or ""
        else: note = ""
        items = [{"label": _clip(e["text"], 200), "status": e["kind"], "ts": e["ts"]} for e in ev[-6:]]
        if k == "execute": items += child_items
        steps.append(_step(k, MX_LABEL.get(k, k.capitalize()), stt, ev[0]["ts"] if ev else None, "", _clip(text, 260), _clip(note, 300),
                           [x for x in runs if x["kind"] == k] + (child_runs if k == "execute" else []), items, MX_ABOUT.get(k, "")))
    pend = [x for x in s.get("requests") or [] if x["status"] == "pending"]
    wait = "you: " + (pend[0]["label"] if pend else "answer its questions" if status == "needs_input" else "resume it") if status in ("needs_input", "paused") else ""
    label = {"queued": "Queued", "running": "Working", "needs_input": "Needs you", "paused": "Paused", "delivered": "Delivered", "failed": "Failed",
             "cancelled": "Cancelled"}.get(status, status)
    return {"ref": f"mx:{mid}", "kind": "mission", "title": m["title"] or _clip(m["goal"], 80), "status": status, "steps": steps,
            "now": _now(steps, status, label, m.get("doing") or "", wait) | {"spent": m.get("spent"), "budget": m.get("budget"), "outcome": m.get("outcome")},
            "updated": m.get("updated")}


def _child(db, uid, m):
    """The engine's own runs during EXECUTE: Workforce runs of its child mission, the long task's segments, or the team's board."""
    eng, child = m["engine"], m["child"]
    try:
        if eng == "workforce" and _has(db, "wf_runs"):
            refs = [f"wf:{r['id']}" for r in db.q("SELECT id FROM wf_runs WHERE mission_id=? ORDER BY id DESC LIMIT 40", (child,))]
            return _runs(db, uid, refs), []
        if eng == "longtask":
            return _runs(db, uid, [f"ia:{child}"]), []
        if eng == "mining" and _has(db, "mw_tasks"):
            rows = db.q("SELECT title, status, updated FROM mw_tasks WHERE comp_id=? AND mission=? ORDER BY id LIMIT 20", (child, f"mx:{m['id']}"))
            return [], [{"label": f"Board: {_clip(r['title'], 120)}", "status": r["status"], "ts": r["updated"]} for r in rows]
    except Exception:  # noqa: BLE001 - an engine's tables missing: show the mission's own steps
        pass
    return [], []


def journeys(ch, me):
    """Work in flight and finished in the last two days: Control Hub tasks and missions, each with where it is now."""
    db, uid, now = ch.db, me["id"], time.time()
    out, seen = [], set()
    if _has(db, "ctl_tasks"):
        for r in db.q("""SELECT id, ref FROM ctl_tasks WHERE user_id=? AND (status NOT IN ('done','cancelled') OR updated>=?) ORDER BY updated DESC LIMIT 30""",
                      (uid, now - 2 * DAY)):
            try: j = _task_journey(ch, me, r["id"])
            except HTTPException: continue
            if (r["ref"] or "").startswith("mx:"): seen.add(r["ref"])
            out.append(_brief(j))
    if ch.mx and _has(db, "mx_missions"):
        for r in db.q("""SELECT id FROM mx_missions WHERE user_id=? AND (status IN ('queued','running','needs_input','paused') OR updated>=?) ORDER BY updated DESC LIMIT 20""",
                      (uid, now - 2 * DAY)):
            if f"mx:{r['id']}" in seen: continue
            try: out.append(_brief(_mission_journey(ch, me, r["id"])))
            except HTTPException: continue
    rank = {"waiting": 0, "failed": 1, "current": 2}
    for x in out: x["_r"] = rank.get(x["step_status"], 3)
    out.sort(key=lambda x: (x.pop("_r"), -(x["updated"] or 0)))
    return {"items": out}


def _brief(j):
    cur = next((s for s in j["steps"] if s["key"] == j["now"]["step"]), None)
    return {"ref": j["ref"], "kind": j["kind"], "route": j.get("route"), "title": j["title"], "status": j["status"], "label": j["now"]["label"],
            "step": cur["label"] if cur else "", "step_status": cur["status"] if cur else "", "waiting_on": j["now"]["waiting_on"],
            "done": j["now"]["done"], "total": j["now"]["total"], "updated": j.get("updated"), "unit": j.get("unit"),
            "dots": [s["status"] for s in j["steps"]]}


def mount(r, ch, user):
    """Adds the routes to the Control Hub's router (control_hub.build)."""
    @r.get("/routing")
    def routing_(req: Request): return routing(ch, user(req))

    @r.get("/journeys")
    def journeys_(req: Request): return journeys(ch, user(req))

    @r.get("/journey/{ref}")
    def journey_(ref: str, req: Request): return journey(ch, user(req), ref)
