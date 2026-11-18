"""My workspace → Overview: everything your agents do across AXoR on one page, and what waits for you.

- Needs you: everything that waits for the user, worst first, each with where to go: a Competition team's blockers and the
  Director's asks (mining_status.py works them out; the team's Status tab shows the same), the Workflow's plans to approve,
  work to send to the reviewer, reviews to merge and failures (administrators), the project team's decisions (team.py, the
  workspace's Reports tab), My subnets' actions to approve and critical alerts, Workforce plans, actions and improvements,
  and Agent HQ's fixes and critical issues (administrators).
- Teams: each open Competition team's verdict (working, stuck, waiting, idle), progress, the week's done tasks, its agents,
  today's tokens against its budget and, for administrators, the Workflow's step. Closed teams are only counted.
- Projects: the project team's latest cycle on each subnet.
- At work now: every agent run going on right now, whichever system started it.
- Performance: your miners from My subnets' latest briefs (best rank of how many, τ a day, the gap to the goal) and the
  teams' throughput (done in 7 days, failed runs in 24 hours).
- Spend: your tokens (today, 7 days, by source, the last 14 days), each team's day against its budget, the Workflow's dollars.
- Activity: the latest events of the teams, the Workflow and the project team, and what Company, Workforce and Mission Control
  finished, merged. `week` counts done work per day (today last) across all of them.

Each source is read on its own: one that's off or not allowed for the user is left out, and one that fails lands in `errors`,
never failing the whole page. Nothing here starts work or spends tokens. The page polls it, so it only reads the database (no
chain reads, no ranking of a whole board, no Ridges sync) and keeps each user's answer for a few seconds.
"""
import json, logging, time

from fastapi import APIRouter, HTTPException, Request

from . import agent_core, company, hq, mining, missions, workforce
from .mining import _clip
from .mining_status import Status

DAY = 86400
LEDGER_ONLY = {"company": ("Company", {"view": "company"}), "missions": ("Mission OS", {"view": "mos"}), "longtask": ("Long tasks", {"view": "infiagent"})}
CACHE = 8  # seconds an answer is kept per user
LEVELS = ("stop", "warn", "info")
# the blocker's fix (mining_status.py) → the team's tab that has its button
FIX_TAB = {"director": "report", "board": "tasks", "team": "team"}
# Workflow tasks that wait for the user: the same statuses mining-bench.js counts on its tab (mining_bench.py may add more)
BENCH_WAIT = (("proposed", "warn", "Plan to approve", "The Director proposed {n} task{s}: edit, untick and approve them"),
              ("handoff", "warn", "{n} task{s} to send to the reviewer", "The engineer finished; read the result and send it on"),
              ("ready", "warn", "{n} task{s} to merge or send back", "The reviewer has read the diff; run the checks, then decide"),
              ("failed", "stop", "{n} Workflow task{s} failed", "Open the task to read why, then start it again or drop it"))
log = logging.getLogger("overview")


def _s(n):
    return "" if n == 1 else "s"


class Overview:
    def __init__(self, db, work, pdca=None, wf=None, hub=None):
        self.db, self.w, self.m, self.pdca, self.wf, self.hub = db, work, work.m, pdca, wf, hub
        self.st = Status(work)
        self.cache = {}

    def _has(self, table):
        return bool(self.db.q("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,), one=True))

    def _agents_ok(self, me):
        if not self.hub: return False
        try: self.hub.gate(me); return True
        except HTTPException: return False

    def view(self, me, fresh=False):
        """fresh: the page opened or Refresh was pressed, so skip the cache (polls use it)."""
        hit = self.cache.get(me["id"])
        if hit and not fresh and time.time() - hit[0] < CACHE: return hit[1]
        out = self._build(me)
        self.cache[me["id"]] = (time.time(), out)
        return out

    def _build(self, me):
        admin, agents = me.get("role") == "admin", self._agents_ok(me)
        out = {"at": time.time(), "admin": admin, "needs": [], "teams": [], "closed": 0, "projects": [], "running": [], "miners": [],
               "spend": None, "activity": [], "sources": {}, "errors": []}
        steps = (("teams", "Competition teams", agents and mining.ENABLED, self._teams),
                 ("workflow", "Workflow", admin and mining.ENABLED and getattr(self.w, "bench", None) is not None and self._has("mb_flows"), self._workflow),
                 ("projects", "Project team", agents and self.pdca is not None, self._projects),
                 ("mining", "My subnets", agents and mining.ENABLED, self._mining),
                 ("workforce", "Workforce", agents and workforce.ENABLED and self.wf is not None, self._workforce),
                 ("hq", "Agent HQ", admin and hq.ENABLED and self._has("hq_fixes"), self._hq),
                 ("ledger", "Other agent systems", agents and agent_core.get() is not None, self._ledger),
                 ("finished", "Company, Workforce and Mission Control", agents, self._finished),
                 ("spend", "Spend", agents, self._spend))
        for key, label, on, fn in steps:
            out["sources"][key] = bool(on)
            if not on: continue
            try: fn(me, out)
            except Exception as e:  # noqa: BLE001 - one source failing leaves the rest of the page
                log.exception("overview %s", key)
                out["sources"][key] = False
                out["errors"].append(f"{label}: {_clip(str(e), 200)}")
        out["needs"].sort(key=lambda x: (LEVELS.index(x["level"]), -(x.get("ts") or 0)))
        out["running"].sort(key=lambda x: x.get("since") or 0)
        out["activity"] = sorted(out["activity"], key=lambda x: -(x["ts"] or 0))[:20]
        t = out["teams"]
        # done per day, last 7 days (today last), across every system: the teams' tasks plus finished Company tasks,
        # Workforce missions and delivered Mission Control missions (_finished), each counted once, not per model call
        other = out.pop("_week", None) or [0] * 7
        out["week"] = [sum(x["week"][i] for x in t) + other[i] for i in range(7)]
        out["counts"] = {"waiting": sum(x["level"] != "info" for x in out["needs"]), "stop": sum(x["level"] == "stop" for x in out["needs"]),
                         "working": len(out["running"]), "teams": len(t), "stuck": sum(x["state"] == "stuck" for x in t),
                         "done_week": sum(out["week"]), "done_day": out["week"][6],
                         "failed_day": sum(x["fails_day"] for x in t), "ok_day": sum(x["ok_day"] for x in t),
                         "tokens_today": (out["spend"] or {}).get("today")}
        return out

    @staticmethod
    def _need(out, level, source, title, detail, where, go, label, ts=None):
        out["needs"].append({"level": level, "source": source, "title": _clip(title, 160), "detail": _clip(detail, 300), "where": where,
                             "go": go, "label": label, "ts": ts})

    # ---------- Competition teams (mining_work.py, mining_status.py) ----------
    def _comps(self, me):
        """(workspace, campaign) for each of the user's teams, listed without Work.all (that one also starts a Ridges sync)."""
        rows = []
        for r in self.db.q("SELECT id FROM mh_campaigns WHERE user_id=? ORDER BY netuid, mech, id", (me["id"],)):
            c = self.m._campaign(r["id"])
            rows += [(w, c) for w in self.w._order(self.db.q("SELECT * FROM mw_comps WHERE campaign_id=?", (c["id"],)))]
        return rows

    def _teams(self, me, out):
        live = []
        for w, c in self._comps(me):
            if w["status"] == "closed": out["closed"] += 1; continue
            s, st = self.w._summary(w, c), self.st.status(me, w["id"])
            p, now = st["progress"], st["now"]
            where = f"SN{c['netuid']} · {s['label']}"
            go = lambda sub: {"view": "teams", "wid": w["id"], "sub": sub}
            out["teams"].append({"id": w["id"], "label": s["label"], "number": s["number"], "netuid": c["netuid"], "subnet": s.get("subnet") or "",
                                 "status": w["status"], "state": st["state"], "line": st["line"], "why": st["why"],
                                 "done": p["done"], "total": p["total"], "week": p["week"], "done_day": p["done_day"], "eta": p["eta"],
                                 "milestone": p["milestones"]["current"], "ends": s["ends"], "agents": s["agents"], "active": s["active"],
                                 "working": len(now["running"]), "queued": now["queued"], "autopilot": s["autopilot"], "paused": s["paused"],
                                 "day": s["day"], "budget": s["budget"], "fails_day": st["fails_day"], "ok_day": st["ok_day"],
                                 "relaying": s["relaying"], "workflow": None})
            for b in st["blockers"]:
                if b["level"] == "info": continue
                act = (b.get("fix") or {}).get("act")
                self._need(out, b["level"], "teams", b["title"], b["detail"], where,
                           {"view": "agents"} if act == "agents" else go(FIX_TAB.get(act, "status")),
                           "Read the report" if act == "director" else (b.get("fix") or {}).get("label") or "Open the team")
            for r in now["running"]:
                out["running"].append({"source": "teams", "who": r["agent"], "what": r["title"] or r["kind"], "since": r["since"], "where": where, "go": go("status")})
            live.append(w["id"])
        if live:
            names = {t["id"]: f"SN{t['netuid']} · {t['label']}" for t in out["teams"]}
            for e in self.db.q(f"SELECT comp_id, ts, kind, text FROM mw_events WHERE comp_id IN ({','.join('?' * len(live))}) ORDER BY id DESC LIMIT 15", live):
                out["activity"].append({"ts": e["ts"], "source": "teams", "kind": e["kind"], "text": _clip(e["text"], 240), "where": names.get(e["comp_id"], ""),
                                        "go": {"view": "teams", "wid": e["comp_id"], "sub": "activity"}})

    # ---------- the Workflow (mining_bench.py): administrators ----------
    def _workflow(self, me, out):
        teams = {t["id"]: t for t in out["teams"]}
        if not teams: return
        bench, ids = self.w.bench, list(teams)
        flows = self.db.q(f"SELECT * FROM mb_flows WHERE comp_id IN ({','.join('?' * len(ids))})", ids)
        for f in flows:
            t = teams[f["comp_id"]]
            where, go = f"SN{t['netuid']} · {t['label']}", {"view": "teams", "wid": t["id"], "sub": "flow"}
            tasks = self.db.q("SELECT id, title, status, updated FROM mb_tasks WHERE flow_id=? AND status!='dropped'", (f["id"],))
            runs = self.db.q("SELECT who, label, kind, started FROM mb_runs WHERE flow_id=? AND status IN ('queued','running') ORDER BY started", (f["id"],))
            week = self.db.q("SELECT COALESCE(SUM(cost), 0) usd FROM mb_runs WHERE flow_id=? AND started>?", (f["id"], time.time() - 7 * DAY), one=True)["usd"]
            waiting = 0
            for status, level, title, detail in BENCH_WAIT:
                hits = [x for x in tasks if x["status"] == status]
                if not hits: continue
                waiting += len(hits)
                n = len(hits)
                self._need(out, level, "workflow", title.format(n=n, s=_s(n)), detail.format(n=n, s=_s(n)) + (f": “{_clip(hits[0]['title'], 80)}”" if n == 1 else "."),
                           where, go, "Open the Workflow", max(x["updated"] or 0 for x in hits))
            if f["plan_error"]: self._need(out, "warn", "workflow", "The Director's plan failed", f["plan_error"], where, go, "Open the Workflow")
            for r in runs:
                out["running"].append({"source": "workflow", "who": r["who"] or r["kind"], "what": r["label"] or r["kind"], "since": r["started"], "where": where, "go": go})
            t["workflow"] = {"step": bench.step(f, tasks), "goal": _clip(f["goal"] or "", 200), "tasks": len(tasks), "waiting": waiting,
                             "running": len(runs), "merged": sum(x["status"] == "merged" for x in tasks), "usd_week": round(week or 0, 2)}
            for e in self.db.q("SELECT ts, kind, text FROM mb_log WHERE flow_id=? ORDER BY id DESC LIMIT 8", (f["id"],)):
                out["activity"].append({"ts": e["ts"], "source": "workflow", "kind": e["kind"], "text": _clip(e["text"], 240), "where": where, "go": go})

    # ---------- the project team (team.py): PDCA cycles in My workspace ----------
    def _projects(self, me, out):
        uid = me["id"]
        for c in self.db.q("""SELECT id, netuid, goal, status, round, tokens, budget, error, next_run, updated FROM team_cycles
                              WHERE id IN (SELECT MAX(id) FROM team_cycles WHERE user_id=? GROUP BY netuid) ORDER BY updated DESC""", (uid,)):
            asks = self.db.q("SELECT title, kind, created FROM team_decisions WHERE cycle_id=? AND status='pending' ORDER BY id", (c["id"],))
            out["projects"].append({**c, "goal": _clip(c["goal"] or "", 200), "error": _clip(c["error"] or "", 200), "pending": len(asks)})
            go = {"view": "workspace", "netuid": c["netuid"], "tab": "reports"}
            if asks:
                self._need(out, "warn", "projects", f"{len(asks)} decision{_s(len(asks))} for the project team" if len(asks) > 1 else asks[0]["title"],
                           "The team waits for your approval: " + "; ".join(_clip(a["title"], 70) for a in asks[:3]), f"SN{c['netuid']}", go, "Open Reports",
                           asks[-1]["created"])
            if c["status"] in ("plan", "do", "check", "act"):
                out["running"].append({"source": "projects", "who": "Project team", "what": f"{c['status'].capitalize()}: {_clip(c['goal'] or '', 90)}",
                                       "since": c["updated"], "where": f"SN{c['netuid']}", "go": {**go, "tab": "team"}})
        for e in self.db.q("SELECT e.ts, e.kind, e.text, c.netuid FROM team_events e JOIN team_cycles c ON c.id=e.cycle_id WHERE e.user_id=? ORDER BY e.id DESC LIMIT 8", (uid,)):
            out["activity"].append({"ts": e["ts"], "source": "projects", "kind": e["kind"], "text": _clip(e["text"], 240), "where": f"SN{e['netuid']}",
                                    "go": {"view": "workspace", "netuid": e["netuid"], "tab": "team"}})

    # ---------- My subnets (mining.py): your miners and their campaigns ----------
    def _mining(self, me, out):
        for r in self.db.q("SELECT id FROM mh_campaigns WHERE user_id=? ORDER BY netuid, mech, id", (me["id"],)):
            c = self.m._campaign(r["id"])
            b = self.db.q("SELECT headline, standing, ts, stats FROM mh_briefs WHERE campaign_id=? ORDER BY id DESC LIMIT 1", (c["id"],), one=True)
            stats = json.loads(b["stats"] or "{}") if b else {}
            acts = self.db.q("SELECT title, created FROM mh_actions WHERE campaign_id=? AND status='awaiting' ORDER BY id", (c["id"],))
            crit = self.db.q("SELECT title, detail, last_seen FROM mh_alerts WHERE campaign_id=? AND status='open' AND level='critical' ORDER BY id DESC", (c["id"],))
            name = self.m._name(c)
            name = "" if name == f"SN{c['netuid']}" else name  # without the subnet's data the name is just its number
            where, go = f"SN{c['netuid']}" + (f" · {name}" if name else ""), {"view": "mining"}
            out["miners"].append({"campaign": c["id"], "netuid": c["netuid"], "name": name, "status": c["status"], "target": c["settings"]["target"],
                                  "rank": stats.get("rank"), "of": stats.get("of"), "em": stats.get("em"), "gap": stats.get("gap"), "top1": stats.get("top1"),
                                  "miners": stats.get("miners_mine"), "headline": _clip((b or {}).get("headline") or "", 200), "standing": (b or {}).get("standing"),
                                  "ts": (b or {}).get("ts"), "waiting": len(acts), "critical": len(crit), "running": c["id"] in self.m.running})
            for a in crit:
                self._need(out, "stop", "mining", a["title"], a["detail"] or "", where, go, "Open My subnets", a["last_seen"])
            if acts:
                self._need(out, "warn", "mining", f"{len(acts)} action{_s(len(acts))} to approve" if len(acts) > 1 else acts[0]["title"],
                           "The Captain proposed: " + "; ".join(_clip(a["title"], 70) for a in acts[:3]), where, go, "Open My subnets", acts[-1]["created"])
            if c["id"] in self.m.running:
                out["running"].append({"source": "mining", "who": "mining team", "what": "Studying the field and your miners", "since": (self.m.running[c["id"]] or {}).get("started"),
                                       "where": where, "go": go})

    # ---------- Workforce (workforce.py) ----------
    def _workforce(self, me, out):
        p, go = self.wf._pending(me["id"]), {"view": "workforce"}
        for k, title in (("plans", "mission plan{s} to approve"), ("actions", "Workforce action{s} to approve"), ("improvements", "tested improvement{s} to promote")):
            if p[k]: self._need(out, "warn", "workforce", f"{p[k]} {title.format(s=_s(p[k]))}", "Workforce waits for your decision.", "Workforce", go, "Open Workforce")
        for m in self.db.q("SELECT title, step, updated FROM wf_missions WHERE user_id=? AND status='running' AND bench_id IS NULL ORDER BY updated", (me["id"],)):
            out["running"].append({"source": "workforce", "who": "Workforce", "what": _clip(f"{m['title']}" + (f" ({m['step']})" if m["step"] else ""), 120),
                                   "since": m["updated"], "where": "Workforce", "go": go})

    # ---------- finished work in Company, Workforce and Mission Control ----------
    def _finished(self, me, out):
        """What those systems finished in 7 days: activity entries and a per-day count (`_week`, merged in _build).
        A Company task, a Workforce mission and a Mission Control mission each count once, however many model calls it took."""
        now, week, since, shown = time.time(), [0] * 7, time.time() - 7 * DAY, {}
        def add(ts, ok, source, kind, text, where, go):
            if ok and (d := int((now - ts) // DAY)) < 7: week[6 - max(d, 0)] += 1
            if (n := shown.get(source, 0)) >= 15: return  # the feed keeps the newest 20 overall; the count above sees every row
            shown[source] = n + 1
            out["activity"].append({"ts": ts, "source": source, "kind": kind, "text": _clip(text, 240), "where": where, "go": go})
        if company.ENABLED and self._has("co_tasks") and self._has("co_company"):
            for r in self.db.q("""SELECT t.title, t.status, t.error, t.finished FROM co_tasks t JOIN co_company c ON c.id=t.company_id
                                  WHERE c.user_id=? AND t.finished>? AND t.status IN ('done','failed') ORDER BY t.finished DESC LIMIT 200""", (me["id"], since)):
                ok = r["status"] == "done"
                add(r["finished"], ok, "company", r["status"], f"Task {'done' if ok else 'failed'}: {r['title']}" + ("" if ok else f" ({r['error'] or 'no reason given'})"),
                    "Company", {"view": "company"})
        kids = set()  # Workforce missions a Mission Control mission ran on (engine workforce): its own row below stands for them
        if self._has("mx_missions"):
            for r in self.db.q("SELECT history FROM mx_missions WHERE user_id=? AND updated>? AND history IS NOT NULL", (me["id"], since - 7 * DAY)):
                try: kids.update(int(h["child"]) for h in json.loads(r["history"]) or [] if h.get("engine") == "workforce" and h.get("child"))
                except (ValueError, TypeError, AttributeError): pass
        if workforce.ENABLED and self.wf is not None and self._has("wf_missions"):
            for r in self.db.q("""SELECT id, title, status, verdict, error, COALESCE(finished, updated) ts FROM wf_missions
                                  WHERE user_id=? AND bench_id IS NULL AND status IN ('done','failed') AND COALESCE(finished, updated)>?
                                  ORDER BY ts DESC LIMIT 200""", (me["id"], since)):
                if r["id"] in kids: continue
                ok = r["status"] == "done"
                add(r["ts"], ok, "workforce", r["status"], f"Mission {'done' if ok else 'failed'}: {r['title']}"
                    + (f" ({r['verdict']})" if ok and r["verdict"] else "" if ok else f" ({r['error'] or 'no reason given'})"), "Workforce", {"view": "workforce"})
        if missions.ENABLED and self._has("mx_missions"):
            for r in self.db.q("""SELECT title, status, outcome, error, COALESCE(finished, updated) ts FROM mx_missions
                                  WHERE user_id=? AND status IN ('delivered','failed') AND COALESCE(finished, updated)>?
                                  ORDER BY ts DESC LIMIT 200""", (me["id"], since)):
                ok = r["status"] == "delivered"
                add(r["ts"], ok, "missions", "done" if ok else "failed", f"Mission {'delivered' if ok else 'failed'}: {r['title']}"
                    + (f" ({r['outcome']})" if ok and r["outcome"] else "" if ok else f" ({r['error'] or 'no reason given'})"), "Mission Control", {"view": "mos"})
        out["_week"] = week

    # ---------- Agent HQ (hq.py): administrators ----------
    def _hq(self, me, out):
        go = {"view": "hq"}
        w = self.db.q("SELECT COUNT(*) n FROM hq_fixes WHERE status='awaiting'", one=True)["n"]
        crit = self.db.q("SELECT title, last_seen FROM hq_issues WHERE status='open' AND severity='critical' AND (snoozed_until IS NULL OR snoozed_until<?) ORDER BY id DESC LIMIT 5",
                         (time.time(),)) if self._has("hq_issues") else []
        if w: self._need(out, "warn", "hq", f"{w} fix{'es' if w > 1 else ''} to approve", "Agent HQ's leads reviewed them; they wait for an administrator.", "Agent HQ", go, "Open Agent HQ")
        for i in crit: self._need(out, "stop", "hq", i["title"], "A critical issue on the services nobody has snoozed.", "Agent HQ", go, "Open Agent HQ", i.get("last_seen"))

    # ---------- spend ----------
    def _ledger(self, me, out):
        """At work now in the systems the sources above don't cover (Company, Mission OS, Long tasks), from the agent core's ledger."""
        for r in agent_core.get().runs((me["id"],), time.time() - DAY, ("running",), 40):
            if r["system"] not in LEDGER_ONLY: continue
            label, go = LEDGER_ONLY[r["system"]]
            out["running"].append({"source": r["system"], "who": label, "what": _clip(r["title"] or r["kind"] or "", 120), "since": r["started"], "where": label, "go": go})

    def _spend(self, me, out):
        u = self.hub.usage(me)
        core = agent_core.get()
        if core is not None:  # the run ledger has every system's model calls (llm_usage only some): today and 7 days from it
            u = {**u, "today": core.spent_today(me["id"]), "week": sum(core.tokens_by_system((me["id"],), time.time() - 7 * DAY).values())}
            out["budget"] = core.budget(me["id"])
        teams = [{"label": f"SN{t['netuid']} · {t['label']}", "id": t["id"], "day": t["day"], "budget": t["budget"]} for t in out["teams"]]
        usd = sum((t["workflow"] or {}).get("usd_week", 0) for t in out["teams"])
        out["spend"] = {"today": u["today"], "week": u["week"], "month": u["month"], "calls_today": u["calls_today"], "days": u["days"],
                        "by_source": u["by_source"][:6], "teams": teams, "workflow_usd_week": round(usd, 2) if out["sources"].get("workflow") else None}


def build(db, require, work, pdca=None, wf=None, hub=None):
    r = APIRouter(prefix="/api/workspace")
    ov = Overview(db, work, pdca, wf, hub)
    r.state = {"overview": ov}

    @r.get("/overview")
    def overview(req: Request, fresh: bool = False): return ov.view(require(req), fresh)

    return r
