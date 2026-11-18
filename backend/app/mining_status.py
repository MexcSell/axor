"""Competition teams, the team's status (mining_work.py runs the work): how far the team has got, what it's doing right now and,
when nothing moves, why, each reason with what fixes it.

- Progress: tasks done of all, done per day over the last week, the roadmap's milestones, findings in the notebook, the time
  left in the competition, and at the recent pace how long the open work still takes.
- Right now: one verdict (working, stalled, paused, out of budget, waiting for you, idle…) with the sentence that explains it,
  who's working on what and since when, and the queue: how many slots the team has, how deep each agent's queue is.
- Why it isn't moving: every blocker found, worst first: no model, the day's budget spent (and when it frees up), the team
  paused or closed, autopilot off with work ready, a queue nobody picks up, failing runs (grouped by error, with the likely
  cause), tasks held after failures or stopped, tasks on agents who are off, reviews nobody can do, questions and reviews
  waiting for the user, no lead, no goal, a board run dry.

`POST /comps/{wid}/status/kick` restarts a queue that stopped moving (the same step a finished run takes).
"""
import re, time

from fastapi import APIRouter, HTTPException, Request

from .mining import _clip
from .mining_work import MAX_TASKS, PLAN_GAP

DAY = 86400
QUIET = 2 * 3600         # autopilot on, work open, nothing finished or started for this long: say so
PILE = 6                 # tasks queued on one agent that make a pile-up
CAUSES = (  # (pattern in the error, what it most likely means)
    (r"server restart", "The server restarted while it ran (a deploy does that): start it again."),
    (r"rate.?limit|\b429\b|too many requests|overloaded|\b529\b", "The model provider is rate-limiting or overloaded: lower how many work at once, or wait."),
    (r"credit|insufficient|quota|billing|payment", "The model account is out of credit or quota: an administrator tops it up in Agents → Models."),
    (r"\b401\b|\b403\b|unauthori[sz]ed|invalid.{0,12}key|authentication|permission", "The model's API key was refused: an administrator checks it in Agents → Models."),
    (r"timed? ?out|timeout|deadline", "Runs time out: the task may be too big for one run; split it or simplify it."),
    (r"no model|not connected|unknown model|model .*not found|LLMError", "The agent's model isn't available: pick another model for it, or connect one."),
    (r"context|too long|max.?tokens|prompt is too long", "The prompt got too long for the model: trim the task's detail or the agent's history (Prompts tab)."),
    (r"name resolution|could not resolve|ENOTFOUND|EAI_AGAIN|network is unreachable|failed to connect|curl: \(\d+\)|no matching distribution|"
     r"max retries exceeded|connection refused",
     "Code in the sandbox tried to reach the internet, which it can't, by design: agents fetch live data with web_read and pass the file to the sandbox."),
    (r"sandbox|pod|kube|image", "The sandbox couldn't run: check Files & sandbox and the cluster (the axor-sandbox namespace)."),
    (r"budget", "The token budget ran out mid-run: raise the team's budget in its settings."),
)


def _cause(err):
    for pat, why in CAUSES:
        if re.search(pat, err or "", re.I): return why
    return ""


def _key(err):  # errors that differ only in ids, numbers and quotes group together
    return re.sub(r"\s+", " ", re.sub(r"[\"'“”][^\"'“”]{0,80}[\"'“”]|[\w-]*\d[\w-]*", "#", err or "")).strip()[:120]


class Status:
    def __init__(self, work):
        self.w, self.db = work, work.db

    def kick(self, me, wid):
        w, _ = self.w._own(me, wid)
        if w["paused"]: raise HTTPException(409, "The team is paused: resume it first.")
        if w["status"] == "closed": raise HTTPException(409, "This competition is closed.")
        self.w._kick(wid)
        self.w._event(wid, "pilot", f"{me['username']} restarted the queue")
        return self.status(me, wid)

    def status(self, me, wid):
        w, c = self.w._own(me, wid)
        now, q = time.time(), self.db.q
        agents = self.w._agents(wid)
        A = {a["id"]: a for a in agents}
        tasks = q("SELECT id, title, status, priority, agent_id, hold, fails, reviewer, run_id, updated, done_at, queued, note FROM mw_tasks WHERE comp_id=?", (wid,))
        running = q("""SELECT r.id, r.agent_id, r.task_id, r.kind, r.started, t.title FROM mw_runs r LEFT JOIN mw_tasks t ON t.id=r.task_id
                       WHERE r.comp_id=? AND r.status='running' ORDER BY r.started""", (wid,))
        summ = self.w._summary(w, c)
        budget, used = summ["budget"], summ["day"]
        parallel = w["parallel"] or 4
        by = lambda *s: [t for t in tasks if t["status"] in s]
        on = lambda aid: aid in A and A[aid]["active"]
        model = self.w._model(c, next((a for a in agents if a["lead"] and a["active"]), agents[0])) if agents else self.w.m._model(c)
        lead = next((a for a in agents if a["lead"] and a["active"]), None)
        name = lambda aid: A[aid]["name"] if aid in A else "someone"

        # ---------- progress ----------
        done = by("done")
        week = [0] * 7
        for t in done:
            d = int((now - (t["done_at"] or t["updated"] or now)) // DAY)
            if 0 <= d < 7: week[6 - d] += 1
        miles = q("SELECT title, due, status FROM mw_milestones WHERE comp_id=? ORDER BY COALESCE(due, '9999'), id", (wid,)) if self._has("mw_milestones") else []
        current = next((m for m in miles if m["status"] != "done"), None)
        fin = q("""SELECT started, finished FROM mw_runs WHERE comp_id=? AND kind='task' AND status='done' AND finished>? AND finished IS NOT NULL""", (wid, now - DAY))
        avg = sum(r["finished"] - r["started"] for r in fin) / len(fin) if fin else None
        ready = [t for t in tasks if t["status"] in ("queued", "working") or (t["status"] == "todo" and on(t["agent_id"]) and not t["hold"])]
        lanes = min(parallel, len({t["agent_id"] for t in ready}) or 1)
        per = {}
        for t in ready: per[t["agent_id"]] = per.get(t["agent_id"], 0) + 1
        # the open work takes as long as the longer of: the queue spread over the slots, the deepest single agent's queue
        eta = avg * max(len(ready) / lanes, max(per.values(), default=0)) if avg and ready else None
        last_done = max(done, key=lambda t: t["done_at"] or 0, default=None)
        last_run = q("SELECT MAX(started) s, MAX(finished) f FROM mw_runs WHERE comp_id=?", (wid,), one=True)
        notes = q("SELECT COUNT(*) n FROM mw_notes WHERE comp_id=?", (wid,), one=True)["n"]
        progress = {"total": len(tasks), "done": len(done), "week": week, "done_day": week[6], "findings": notes,
                    "counts": {s: len(by(s)) for s in ("todo", "queued", "working", "checking", "review", "blocked", "done")},
                    "milestones": {"total": len(miles), "done": sum(m["status"] == "done" for m in miles),
                                   "current": {"title": current["title"], "due": current["due"]} if current else None},
                    "avg_run": avg, "eta": eta, "ready": len(ready), "lanes": lanes,
                    "last_done": {"id": last_done["id"], "title": last_done["title"], "at": last_done["done_at"], "agent": name(last_done["agent_id"])} if last_done and last_done["done_at"] else None,
                    "last_activity": max(filter(None, (last_run["s"], last_run["f"])), default=None), "ends": w["ends"] or "", "starts": w["starts"] or ""}

        # ---------- failures, last 24 hours ----------
        fails = q("""SELECT r.error, r.finished, r.kind, r.agent_id, t.title, t.id tid FROM mw_runs r LEFT JOIN mw_tasks t ON t.id=r.task_id
                     WHERE r.comp_id=? AND r.status='failed' AND r.started>? ORDER BY r.id DESC""", (wid, now - DAY))
        ok_day = q("SELECT COUNT(*) n FROM mw_runs WHERE comp_id=? AND status='done' AND started>?", (wid, now - DAY), one=True)["n"]
        # a failure is history once its task is done or ran fine after it (for runs without a task: a later run of the same kind did)
        ok_task = {r["task_id"]: r["f"] for r in q("""SELECT task_id, MAX(finished) f FROM mw_runs WHERE comp_id=? AND kind='task' AND status='done'
                                                     AND task_id IS NOT NULL AND started>? GROUP BY task_id""", (wid, now - 2 * DAY))}
        ok_kind = {r["kind"]: r["f"] for r in q("SELECT kind, MAX(finished) f FROM mw_runs WHERE comp_id=? AND status='done' AND started>? GROUP BY kind", (wid, now - 2 * DAY))}
        tstate = {t["id"]: t["status"] for t in tasks}
        past = lambda f: (tstate.get(f["tid"]) == "done" or (ok_task.get(f["tid"]) or 0) > (f["finished"] or 0)) if f["tid"] \
            else (ok_kind.get(f["kind"]) or 0) > (f["finished"] or 0)
        live = [f for f in fails if not past(f)]
        groups = {}
        for f in fails:
            g = groups.setdefault(_key(f["error"]), {"error": _clip(f["error"] or "No error recorded.", 300), "n": 0, "open": 0, "last": f["finished"], "agents": set(),
                                                     "task": {"id": f["tid"], "title": f["title"]} if f["tid"] else None, "cause": _cause(f["error"])})
            g["n"] += 1
            g["open"] += not past(f)
            g["agents"].add(name(f["agent_id"]))
        errors = sorted(({**g, "agents": sorted(g["agents"])[:6], "resolved": not g["open"]} for g in groups.values()),
                        key=lambda g: (not g["open"], -g["n"], -(g["last"] or 0)))[:6]

        # ---------- right now ----------
        held = [t for t in tasks if t["status"] == "todo" and t["hold"] == "failed"]
        retrying = [t for t in tasks if t["status"] == "todo" and t["hold"] == "retry"]
        stopped = [t for t in tasks if t["status"] == "todo" and t["hold"] == "stopped"]
        queued, review, blocked = by("queued"), by("review"), by("blocked")
        mine = [t for t in tasks if t["status"] == "todo" and t["agent_id"] is None]
        off = [t for t in tasks if t["status"] in ("todo", "queued") and t["agent_id"] is not None and not on(t["agent_id"])]
        startable = [t for t in tasks if t["status"] == "todo" and on(t["agent_id"]) and not t["hold"]]
        orphan_reviews = [t for t in by("checking") if not on(t["reviewer"])]
        live_runs = {r["task_id"] for r in running if r["kind"] == "task"}
        ghosts = [t for t in by("working") if t["id"] not in live_runs]
        pile = sorted(((name(a), n) for a, n in per.items() if n >= PILE), key=lambda x: -x[1])
        free = [a for a in agents if a["active"] and a["id"] not in {r["agent_id"] for r in running}]
        director = self.w.director.view(w) if getattr(self.w, "director", None) else None
        relaying = bool(director and director.get("relaying"))
        frees = self._frees(wid, budget, used, now) if budget and used >= budget else None
        busy = len(running)

        B = []  # blockers: (level, key, title, detail, fix)
        add = lambda level, key, title, detail="", fix=None: B.append({"level": level, "key": key, "title": title, "detail": detail, "fix": fix})
        if w["status"] == "closed": add("stop", "closed", "The competition is closed", "Nothing starts on a closed team.", {"act": "edit", "label": "Reopen it"})
        elif w["status"] == "upcoming": add("info", "upcoming", "The competition hasn't started", "The team can prepare; autopilot runs as usual.")
        if not model: add("stop", "model", "No model is connected", "Agents can't run without one: an administrator connects one in Agents → Models.", {"act": "agents", "label": "Open Agents"})
        if frees: add("stop", "budget", "Today's token budget is spent",
                      f"{used:,} of {budget:,} tokens in the last 24 hours. Work resumes as older runs leave the window, {self._when(frees, now)}, or raise the budget.",
                      {"act": "edit", "label": "Raise the budget"})
        if w["paused"]: add("stop", "paused", "The team is paused", "Nothing new starts until you resume it" + (f"; {len(startable)} assigned task{'s are' if len(startable) > 1 else ' is'} ready." if startable else "."), {"act": "resume", "label": "Resume"})
        gov = self.w.loop.gate(wid, w) if getattr(self.w, "loop", None) else None  # the budget governor (mining_autoloop.py)
        held_back = bool(gov and not gov["tasks"] and not frees and not w["paused"])
        watching = bool(w["autopilot"] and getattr(self.w, "loop", None) and self.w.loop.observing(wid))  # observe mode: autopilot starts nothing
        if watching and not w["paused"]: add("info", "observe", "Autopilot only observes", "It records what it would start, plan and review, and starts nothing: compare it with what you do in the Autoloop tab, then let it act.",
                                             {"act": "autoloop", "label": "Open the Autoloop"})
        if held_back: add("warn", "governor", gov["title"], gov["reason"] + " Work waits in the queue instead of failing.", {"act": "autoloop", "label": "Open the Autoloop"})
        if queued and not busy and not w["paused"] and model and not frees and not held_back:
            stuck = [t for t in queued if on(t["agent_id"])]
            if stuck: add("stop", "stalled", f"{len(stuck)} queued, but nobody is working",
                          "The queue stopped moving (it moves when a run ends or autopilot ticks). Restart it.", {"act": "kick", "label": "Restart the queue"})
        if ghosts: add("warn", "ghosts", f"{len(ghosts)} task{'s' if len(ghosts) > 1 else ''} marked working with no run behind {'them' if len(ghosts) > 1 else 'it'}",
                       ", ".join(f"“{_clip(t['title'], 60)}”" for t in ghosts[:3]) + ". Stop and start again.", {"act": "task", "id": ghosts[0]["id"], "label": "Open it"})
        if live:  # only failures nothing has fixed since; the rest stay in the errors list, marked as earlier
            top = errors[0]
            level = "stop" if len(live) >= 3 and ok_day == 0 else "warn"
            add(level, "failing", f"{len(live)} failed run{'s' if len(live) > 1 else ''} in 24 hours not fixed since" + (", none succeeded" if not ok_day else f" ({ok_day} succeeded)"),
                (top["cause"] + " " if top["cause"] else "") + f"Most common: {_clip(top['error'], 160)}", {"act": "errors", "label": "See the errors"})
        if held: add("warn", "held", f"{len(held)} task{'s' if len(held) > 1 else ''} held after failing twice",
                     "Autopilot won't retry them" + (": the Director picks them up in its next report." if relaying else ": open one, read why it failed, then start it again or change it."),
                     {"act": "task", "id": held[0]["id"], "label": "Open the first"})
        if off: add("warn", "off", f"{len(off)} task{'s' if len(off) > 1 else ''} on agents who are off",
                    ", ".join(sorted({name(t['agent_id']) for t in off})[:5]) + ": switch them back on or reassign the tasks.", {"act": "team", "label": "Open the team"})
        if orphan_reviews: add("warn", "reviews", f"{len(orphan_reviews)} review{'s' if len(orphan_reviews) > 1 else ''} with no one to do {'them' if len(orphan_reviews) > 1 else 'it'}",
                               "Their reviewer is off: they move to you within a few minutes, or switch the reviewer back on.")
        if not w["autopilot"] and startable and not w["paused"]:
            add("warn", "manual", f"Autopilot is off: {len(startable)} assigned task{'s wait' if len(startable) > 1 else ' waits'} to be started",
                "With autopilot off, nothing starts by itself.", {"act": "autopilot", "label": "Switch autopilot on"})
        if pile and busy >= parallel:
            add("info", "pile", "One agent at a time per task, " + f"{parallel} at once in the team",
                "Deepest queues: " + ", ".join(f"{n} ({k})" for n, k in pile[:4]) + ". Each agent works through its own queue one task at a time; raise how many work at once, or reassign some.",
                {"act": "parallel", "label": f"Let {min(24, parallel + 2)} work at once"} if parallel < 24 else None)
        elif busy >= parallel and len(queued) > parallel:
            add("info", "slots", f"All {parallel} slots are busy, {len(queued)} queued",
                f"{len(free)} agents are free but only {parallel} work at once.", {"act": "parallel", "label": f"Let {min(24, parallel + 2)} work at once"} if parallel < 24 else None)
        elif pile:
            add("info", "pile", "Some agents have long queues", ", ".join(f"{n} has {k}" for n, k in pile[:4]) + ": each works one task at a time; reassign some to free teammates.")
        wait_n = len(review) + len(blocked) + len(mine)
        if relaying:
            if director.get("waiting"): add("warn", "report", f"The Director's report asks you {director['waiting']} thing{'s' if director['waiting'] > 1 else ''}",
                                            "Answer the report: the tasks behind the asks wait for it.", {"act": "director", "label": "Read the report"})
            elif director.get("with_director"): add("info", "director", f"{director['with_director']} item{'s' if director['with_director'] > 1 else ''} with the Director",
                                                     "Finished work, questions and failures go to the Director first; it settles them in its next report.")
        elif wait_n:
            add("warn", "you", f"{wait_n} task{'s wait' if wait_n > 1 else ' waits'} for you",
                ", ".join(x for x in (f"{len(review)} to review" if review else "", f"{len(blocked)} question{'s' if len(blocked) > 1 else ''}" if blocked else "",
                                      f"{len(mine)} on your list" if mine else "") if x) + ". Work that depends on them can't go on.",
                {"act": "board", "label": "Open the board"})
        if retrying: add("info", "retrying", f"{len(retrying)} task{'s' if len(retrying) > 1 else ''} will retry on {'their' if len(retrying) > 1 else 'its'} own",
                         "They failed on something passing (a timeout, a rate limit, a restart); the Autoloop starts them again after a short wait.", {"act": "autoloop", "label": "Open the Autoloop"})
        if stopped: add("info", "stopped", f"{len(stopped)} task{'s' if len(stopped) > 1 else ''} you stopped", "They stay out of the queue until you start them.")
        missing = self.w.web.ungranted(w, self.w.m._owner(c)) if getattr(self.w, "web", None) else []
        if missing: add("warn", "tools", f"Added but not granted to this team: {', '.join(missing[:4])}{'…' if len(missing) > 4 else ''}",
                        "The team's agents can't use them until you grant them (Agents → Tools & MCP → grant to this team). Reading public pages live (web_read) works without them.",
                        {"act": "tools", "label": "Open Tools & MCP"})
        if not lead and agents: add("warn", "lead", "No active lead", "Nobody plans: make an agent the Director (Team tab).", {"act": "team", "label": "Open the team"})
        if not agents: add("stop", "empty", "The team has no agents", "Add agents, or create the team again from a pack.", {"act": "team", "label": "Open the team"})
        if not (w["goal"] or "").strip(): add("info", "goal", "No goal", "The Director plans better with one.", {"act": "edit", "label": "Add a goal"})
        quiet = now - (progress["last_activity"] or w["created"] or now)
        if w["autopilot"] and not w["paused"] and not busy and (ready or queued) and quiet > QUIET and not held_back and not watching and not any(b["level"] == "stop" for b in B):
            add("warn", "quiet", f"Nothing has run for {self._span(quiet)}", "Autopilot is on and work is ready, yet nothing starts.", {"act": "kick", "label": "Restart the queue"})
        planning = any(r["kind"] == "plan" for r in running)
        open_n = sum(t["status"] != "done" for t in tasks)
        full = open_n >= MAX_TASKS
        if full and lead and w["status"] != "closed":
            add("warn", "full", f"The board holds {open_n} open tasks, the most it takes",
                "A plan or a follow-up can't add anything until some are finished, dropped or deleted; autopilot doesn't plan meanwhile.", {"act": "board", "label": "Open the board"})
        dry = not full and not ready and not queued and not by("checking", "review", "blocked") and not planning and lead and w["status"] != "closed"
        replan = None  # when autopilot plans an empty board: PLAN_GAP after the last plan (mining_work._pilot_one)
        if dry:
            auto = w["autopilot"] and not w["paused"] and not watching and not full and not frees
            if auto and not held_back: replan = (w["last_plan"] or 0) + PLAN_GAP
            add("info", "dry", "The board has run dry", "No assigned work is left" +
                (f": autopilot asks the Director to plan {'now' if replan <= now else 'in ' + self._span(replan - now)}." if replan else
                 ": autopilot plans once the governor lets work start again." if auto else "."),
                {"act": "plan", "label": "Plan now"})
        B.sort(key=lambda b: ("stop", "warn", "info").index(b["level"]))

        # ---------- the verdict ----------
        stop = next((b for b in B if b["level"] == "stop"), None)
        if w["status"] == "closed": state, line = "closed", "The competition is closed."
        elif stop: state, line = "stuck", stop["title"] + "."
        elif busy: state, line = "working", f"{busy} at work" + (f", {len(queued)} queued" if queued else "") + (", the Director is planning" if planning else "") + "."
        elif any(b["key"] in ("you", "report") for b in B): state, line = "waiting", next(b for b in B if b["key"] in ("you", "report"))["title"] + "."
        elif any(b["key"] == "manual" for b in B): state, line = "idle", "Autopilot is off and nothing is started."
        elif any(b["key"] == "dry" for b in B): state, line = "idle", "Nothing left to do: the board has run dry."
        else: state, line = "idle", "Nobody is at work right now."
        why = next((b["detail"] for b in B if b["level"] in ("stop", "warn")), "")

        return {"comp": wid, "at": now, "state": state, "line": line, "why": why, "blockers": B, "progress": progress, "errors": errors,
                "fails_day": len(fails), "ok_day": ok_day,
                "now": {"running": [{"agent": name(r["agent_id"]), "agent_id": r["agent_id"], "kind": r["kind"], "task": r["task_id"],
                                     "title": r["title"] or ("Planning the board" if r["kind"] == "plan" else "Writing the report" if r["kind"] == "report" else ""),
                                     "since": r["started"]} for r in running],
                        "queued": len(queued), "parallel": parallel, "free": len(free), "autopilot": bool(w["autopilot"]), "paused": bool(w["paused"]),
                        "pilot_note": w["pilot_note"] or "", "piles": [{"agent": k, "n": n} for k, n in pile[:6]],
                        "next_plan": min(filter(None, ((w["last_plan"] or 0) + (w["plan_every"] or 6) * 3600, replan))) if w["autopilot"] and not full else None},
                "budget": {"used": used, "budget": budget, "frees": frees},
                "director": {k: director.get(k) for k in ("relaying", "waiting", "with_director", "reporting", "last_report")} if director else None}

    def _has(self, table):
        return bool(self.db.q("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,), one=True))

    def _frees(self, wid, budget, used, now):
        """When enough of the last 24 hours' tokens leave the window for the team to work again."""
        for r in self.db.q("SELECT started, tokens FROM mw_runs WHERE comp_id=? AND started>? ORDER BY started", (wid, now - DAY)):
            used -= r["tokens"] or 0
            if used < budget: return r["started"] + DAY
        return now

    @staticmethod
    def _when(ts, now):
        t = time.localtime(ts)
        if time.strftime("%Y%m%d", t) == time.strftime("%Y%m%d", time.localtime(now)): return time.strftime("from about %H:%M", t)
        return time.strftime("from about %H:%M ", t) + ("tomorrow" if ts - now < 2 * DAY else time.strftime("on %a", t))

    @staticmethod
    def _span(s):
        return f"{int(s // 3600)} h" if s >= 3600 else f"{int(s // 60)} min"


def build(work, require):
    r = APIRouter(prefix="/api/mining/work")
    gate = work.m.hub.gate if work.m.hub else (lambda me: me)
    user = lambda req: gate(require(req))
    st = Status(work)
    r.state = {"status": st}

    @r.get("/comps/{wid}/status")
    def status(wid: int, req: Request): return st.status(user(req), wid)

    @r.post("/comps/{wid}/status/kick")
    def kick(wid: int, req: Request): return st.kick(user(req), wid)

    return r
