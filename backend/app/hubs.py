"""AXoR 2.0 hubs (hubs.js): one read-only page per area, over the systems that already do the work, each item leading to the page
that owns it. Nothing here starts work, spends tokens or decides anything; the agent pages themselves are unchanged.

- `/api/hub/org` Organization & Workforce: the hierarchy (you → the Company's divisions, Workforce's teams, each Competition
  team's squad, your own agents, Agent HQ for administrators), every agent's role and workload, the teams and task forces at
  work, and who works with whom (the Company's agent messages, Workforce's board).
- `/api/hub/projects` Portfolio & Project HQ, and Missions & Tasks: every project across the Company, Competition teams,
  Workforce missions, the project team and long tasks, on one scale; every task on one board (five systems' statuses mapped
  to five lanes); and how projects depend on each other.
- `/api/hub/governance` the Approval Center's other tabs: agent recommendations, executions, the audit trail, permissions.
- `/api/hub/evaluation` Intelligence & Evaluation: agent scores, benchmarks and experiments, models (use, routes, scores),
  long tasks, knowledge and skills.
- `/api/hub/workspace` the personal workspace in numbers: notes, files, boards, study, workspace subnets.
- `/api/hub/settings` your account's security and notification settings (administrators also read /api/admin/overview).

Each source is read on its own; one that fails lands in `errors`. Answers are kept per user for a few seconds.
"""
import json, logging, time

from fastapi import APIRouter, HTTPException, Request

from . import company, infiagent, mining, workforce
from .mining import _clip

CACHE = 8
DAY = 86400
# five systems' task statuses → the board's lanes; cancelled and skipped tasks are only counted
LANES = ("todo", "doing", "review", "blocked", "done")
LANE = {"pending": "todo", "proposed": "todo", "queued": "todo", "todo": "todo", "planning": "todo",
        "running": "doing", "evaluating": "doing", "working": "doing", "checking": "doing", "plan": "doing", "do": "doing", "check": "doing", "act": "doing",
        "review": "review", "waiting": "review", "paused": "review",
        "blocked": "blocked", "failed": "blocked", "error": "blocked",
        "done": "done"}
OPEN_MW = ("todo", "queued", "working", "checking", "review", "blocked")
log = logging.getLogger("hubs")


def _j(x, default):
    try: return json.loads(x) if x else default
    except (TypeError, ValueError): return default


class Hubs:
    def __init__(self, db, ov, co=None):
        self.db, self.ov, self.co = db, ov, co
        self.cache = {}

    # ---------- plumbing ----------
    def _has(self, table):
        return bool(self.db.q("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,), one=True))

    def _agents(self, me):
        if not self.ov._agents_ok(me): raise HTTPException(403, "Agents aren't turned on for your account. An administrator can turn them on for members.")

    def cached(self, kind, me, fn, fresh=False):
        k = (kind, me["id"])
        hit = self.cache.get(k)
        if hit and not fresh and time.time() - hit[0] < CACHE: return hit[1]
        out = {"at": time.time(), "admin": me.get("role") == "admin", "errors": []}
        fn(me, out)
        self.cache[k] = (time.time(), out)
        return out

    @staticmethod
    def _try(out, label, fn, *a):
        try: return fn(*a)
        except Exception as e:  # noqa: BLE001 - one source failing leaves the rest
            log.exception("hub %s", label)
            out["errors"].append(f"{label}: {_clip(str(e), 200)}")

    def _company(self, me):
        return self.co._company(me, create=False) if self.co is not None and company.ENABLED else None

    def _comps(self, me):
        """The user's open Competition teams with their subnet, straight from the tables (never Work.all: it starts a Ridges sync)."""
        if not (mining.ENABLED and self._has("mw_comps")): return []
        return self.db.q("""SELECT w.id, w.number, w.name, w.status, w.budget, w.goal, w.autopilot, w.paused, w.updated, c.netuid FROM mw_comps w
                            JOIN mh_campaigns c ON c.id=w.campaign_id WHERE c.user_id=? AND w.status!='closed' ORDER BY c.netuid, w.number""", (me["id"],))

    @staticmethod
    def _label(w):
        return f"SN{w['netuid']} · {w['name'] or ('Competition ' + str(w['number']))}"

    # ---------- Organization & Workforce ----------
    def org(self, me, fresh=False):
        self._agents(me)
        return self.cached("org", me, self._org, fresh)

    def _org(self, me, out):
        uid, now, week = me["id"], time.time(), time.time() - 7 * DAY
        out.update({"tree": {"name": me["username"], "title": "You · the one who decides", "kind": "you", "children": []},
                    "agents": [], "teams": [], "forces": [], "edges": [], "board": [], "counts": {}})
        root = out["tree"]["children"]

        def company_part():
            c = self._company(me)
            if not c: return
            cid = c["id"]
            busy = {r["agent_id"]: r["n"] for r in self.db.q("""SELECT m.agent_id, COUNT(*) n FROM co_members m JOIN co_teams t ON t.id=m.team_id
                                                                 WHERE t.company_id=? AND t.status='active' GROUP BY m.agent_id""", (cid,))}
            toks = {r["agent_id"]: r["n"] for r in self.db.q("SELECT agent_id, SUM(tokens) n FROM co_usage WHERE company_id=? AND ts>? GROUP BY agent_id", (cid, week))}
            done = {r["by_agent"]: r["n"] for r in self.db.q("SELECT by_agent, COUNT(*) n FROM co_artifacts WHERE company_id=? AND created>? GROUP BY by_agent", (cid, week))}
            agents = self.db.q("SELECT id, name, title, category, division_id, stage, max_load, lead, evaluator, status FROM co_agents WHERE company_id=? AND status!='archived' ORDER BY lead DESC, id", (cid,))
            divs = []
            for d in self.db.q("SELECT id, name, description, status FROM co_divisions WHERE company_id=? ORDER BY id", (cid,)):
                kids = [a for a in agents if a["division_id"] == d["id"]]
                divs.append({"name": d["name"], "title": _clip(d["description"] or "", 120), "kind": "division", "go": {"view": "company", "tab": "agents"},
                             "children": [{"name": a["name"], "title": a["title"], "kind": "agent", "lead": bool(a["lead"]), "status": a["status"],
                                           "load": busy.get(a["id"], 0), "max": a["max_load"], "go": {"view": "company", "tab": "agents"}} for a in kids]})
            loose = [a for a in agents if a["division_id"] not in {d["id"] for d in self.db.q("SELECT id FROM co_divisions WHERE company_id=?", (cid,))}]
            if loose: divs.append({"name": "Unassigned", "kind": "division", "children": [{"name": a["name"], "title": a["title"], "kind": "agent", "go": {"view": "company", "tab": "agents"}} for a in loose]})
            root.append({"name": c["name"], "title": "Organization · divisions, projects and agent contracts", "kind": "system", "system": "company", "go": {"view": "company"}, "children": divs})
            for a in agents:
                out["agents"].append({"system": "company", "name": a["name"], "role": a["title"] or a["category"] or "", "team": next((d["name"] for d in divs if any(k["name"] == a["name"] for k in d["children"])), ""),
                                      "status": a["status"], "lead": bool(a["lead"] or a["evaluator"]), "load": busy.get(a["id"], 0), "max": a["max_load"] or 0,
                                      "done_week": done.get(a["id"], 0), "tokens_week": toks.get(a["id"], 0), "go": {"view": "company", "tab": "agents"}})
            names = {a["id"]: a["name"] for a in agents}
            projects = {p["id"]: p["name"] for p in self.db.q("SELECT id, name FROM co_projects WHERE company_id=?", (cid,))}
            for t in self.db.q("SELECT id, project_id, name, kind, status, lead_id, activated FROM co_teams WHERE company_id=? AND status='active' ORDER BY id DESC", (cid,)):
                n = self.db.q("SELECT COUNT(*) n FROM co_members WHERE team_id=?", (t["id"],), one=True)["n"]
                out["teams"].append({"system": "company", "name": t["name"] or f"Team {t['id']}", "kind": t["kind"] or "team", "lead": names.get(t["lead_id"], ""),
                                     "members": n, "where": projects.get(t["project_id"], ""), "since": t["activated"], "go": {"view": "company", "tab": "projects"}})
            for e in self.db.q("""SELECT m.from_agent, m.to_agent, COUNT(*) n FROM co_messages m JOIN co_tasks t ON t.id=m.task_id
                                  WHERE t.company_id=? AND m.ts>? AND m.from_agent IS NOT NULL AND m.to_agent IS NOT NULL GROUP BY m.from_agent, m.to_agent ORDER BY n DESC LIMIT 15""", (cid, week)):
                out["edges"].append({"system": "company", "from": names.get(e["from_agent"], f"#{e['from_agent']}"), "to": names.get(e["to_agent"], f"#{e['to_agent']}"), "n": e["n"]})

        def workforce_part():
            if not (workforce.ENABLED and self._has("wf_agents")): return
            agents = self.db.q("SELECT key, team, level, role, name, title, status FROM wf_agents WHERE user_id=? AND status!='archived' ORDER BY team, level='lead' DESC, id", (uid,))
            if not agents: return
            run = {r["agent"]: r["n"] for r in self.db.q("""SELECT a.agent, COUNT(*) n FROM wf_assignments a JOIN wf_missions m ON m.id=a.mission_id
                                                          WHERE m.user_id=? AND a.status='running' GROUP BY a.agent""", (uid,))}
            done = {r["agent"]: (r["n"], r["t"]) for r in self.db.q("""SELECT a.agent, COUNT(*) n, SUM(a.tokens) t FROM wf_assignments a JOIN wf_missions m ON m.id=a.mission_id
                                                                     WHERE m.user_id=? AND a.status='done' AND a.finished>? GROUP BY a.agent""", (uid, week))}
            teams = {}
            for a in agents: teams.setdefault(a["team"] or "exec", []).append(a)
            kids = []
            for tid, members in teams.items():
                name = workforce.TEAM_NAME.get(tid, tid.capitalize())
                kids.append({"name": name, "title": next((t["job"] for t in workforce.TEAMS if t["id"] == tid), ""), "kind": "team", "go": {"view": "workforce"},
                             "children": [{"name": a["name"], "title": a["title"] or a["role"] or "", "kind": "agent", "lead": a["level"] == "lead", "status": a["status"],
                                           "load": run.get(a["key"], 0), "go": {"view": "workforce"}} for a in members]})
                out["teams"].append({"system": "workforce", "name": name, "kind": "standing team", "lead": next((a["name"] for a in members if a["level"] == "lead"), ""),
                                     "members": len(members), "where": "Workforce", "running": sum(run.get(a["key"], 0) for a in members), "go": {"view": "workforce"}})
                for a in members:
                    out["agents"].append({"system": "workforce", "name": a["name"], "role": a["title"] or a["role"] or "", "team": name, "status": a["status"], "lead": a["level"] == "lead",
                                          "load": run.get(a["key"], 0), "max": None, "done_week": done.get(a["key"], (0, 0))[0], "tokens_week": done.get(a["key"], (0, 0))[1] or 0, "go": {"view": "workforce"}})
            root.append({"name": "Workforce", "title": "Standing teams that run missions", "kind": "system", "system": "workforce", "go": {"view": "workforce"}, "children": kids})
            byname = {a["key"]: a["name"] for a in agents}
            for b in self.db.q("SELECT author, kind, COUNT(*) n FROM wf_board WHERE user_id=? AND created>? GROUP BY author, kind ORDER BY n DESC LIMIT 12", (uid, week)):
                out["board"].append({"system": "workforce", "who": byname.get(b["author"], b["author"] or ""), "kind": b["kind"], "n": b["n"]})

        def teams_part():
            comps = self._comps(me)
            if not comps: return
            ids = [w["id"] for w in comps]
            marks = ",".join("?" * len(ids))
            agents = self.db.q(f"SELECT id, comp_id, role, name, title, lead, active, squad, head FROM mw_agents WHERE comp_id IN ({marks}) ORDER BY comp_id, head DESC, lead DESC, id", ids)
            open_ = {r["agent_id"]: r["n"] for r in self.db.q(f"SELECT agent_id, COUNT(*) n FROM mw_tasks WHERE comp_id IN ({marks}) AND status IN ({','.join('?' * len(OPEN_MW))}) GROUP BY agent_id", ids + list(OPEN_MW))}
            runs = {r["agent_id"]: (r["n"], r["t"]) for r in self.db.q(f"SELECT agent_id, COUNT(*) n, SUM(tokens) t FROM mw_runs WHERE comp_id IN ({marks}) AND started>? GROUP BY agent_id", ids + [week])}
            live = {r["agent_id"] for r in self.db.q(f"SELECT agent_id FROM mw_runs WHERE comp_id IN ({marks}) AND status IN ('queued','running')", ids)}
            kids = []
            for w in comps:
                mem = [a for a in agents if a["comp_id"] == w["id"]]
                go = {"view": "teams", "wid": w["id"], "sub": "team"}
                kids.append({"name": self._label(w), "title": _clip(w["goal"] or "", 120), "kind": "team", "go": go,
                             "children": [{"name": a["name"], "title": a["title"] or a["role"] or "", "kind": "agent", "lead": bool(a["lead"] or a["head"]),
                                           "status": "active" if a["active"] else "off", "load": open_.get(a["id"], 0), "go": go} for a in mem]})
                out["teams"].append({"system": "teams", "name": self._label(w), "kind": "competition team", "lead": next((a["name"] for a in mem if a["head"] or a["lead"]), ""),
                                     "members": sum(1 for a in mem if a["active"]), "where": f"SN{w['netuid']}", "running": sum(1 for a in mem if a["id"] in live), "go": go})
                for a in mem:
                    if not a["active"]: continue
                    out["agents"].append({"system": "teams", "name": a["name"], "role": a["title"] or a["role"] or "", "team": self._label(w), "status": "working" if a["id"] in live else "active",
                                          "lead": bool(a["lead"] or a["head"]), "load": open_.get(a["id"], 0), "max": None, "done_week": runs.get(a["id"], (0, 0))[0],
                                          "tokens_week": runs.get(a["id"], (0, 0))[1] or 0, "go": go})
            root.append({"name": "Competition teams", "title": "A squad per subnet competition", "kind": "system", "system": "teams", "go": {"view": "teams"}, "children": kids})

        def forces_part():
            if not self._has("mp_forces"): return
            labels = {w["id"]: self._label(w) for w in self._comps(me)}
            for f in self.db.q("SELECT id, comp_id, goal, status, members, created, ends FROM mp_forces WHERE user_id=? AND status IN ('active','dissolving') ORDER BY id DESC", (uid,)):
                out["forces"].append({"goal": _clip(f["goal"] or "", 200), "status": f["status"], "members": len(_j(f["members"], [])), "where": labels.get(f["comp_id"], ""),
                                      "since": f["created"], "ends": f["ends"], "go": {"view": "portfolio"}})

        def own_part():
            rows = self.db.q("SELECT name, role, status, tokens, last_activity FROM custom_agents WHERE owner_id=? AND status!='archived' ORDER BY last_activity DESC", (uid,)) if self._has("custom_agents") else []
            if rows:
                root.append({"name": "Your agents", "title": "Agents you made in the agent hub", "kind": "system", "system": "agents", "go": {"view": "agents"},
                             "children": [{"name": a["name"], "title": a["role"] or "", "kind": "agent", "status": a["status"], "go": {"view": "agents"}} for a in rows[:24]]})
            if me.get("role") == "admin" and self._has("hq_agents"):
                hq = self.db.q("SELECT id, status, errors, last_run FROM hq_agents ORDER BY id")
                if hq: root.append({"name": "Agent HQ", "title": "Boss, managers, leads and field agents watching the services", "kind": "system", "system": "hq", "go": {"view": "hq"},
                                    "children": [{"name": a["id"], "title": f"last run {time.strftime('%H:%M', time.localtime(a['last_run']))}" if a["last_run"] else "", "kind": "agent",
                                                  "status": a["status"], "load": a["errors"] or 0, "go": {"view": "hq"}} for a in hq]})

        for label, fn in (("Company", company_part), ("Workforce", workforce_part), ("Competition teams", teams_part), ("Task forces", forces_part), ("Agents", own_part)):
            self._try(out, label, fn)
        a = out["agents"]
        out["counts"] = {"agents": len(a), "busy": sum(1 for x in a if x["load"]), "teams": len(out["teams"]), "forces": len(out["forces"]),
                         "systems": len(root), "tokens_week": sum(x["tokens_week"] or 0 for x in a), "done_week": sum(x["done_week"] or 0 for x in a)}

    # ---------- Portfolio & Project HQ, Missions & Tasks ----------
    def projects(self, me, fresh=False):
        self._agents(me)
        return self.cached("projects", me, self._projects, fresh)

    def _projects(self, me, out):
        uid, now = me["id"], time.time()
        out.update({"projects": [], "tasks": [], "deps": [], "lanes": list(LANES), "dropped": 0})
        P, T = out["projects"], out["tasks"]

        def proj(system, id_, name, goal, status, done, total, running, tokens, budget, updated, where, go, extra=None):
            P.append({"system": system, "id": id_, "name": name, "goal": _clip(goal or "", 240), "status": status, "done": done or 0, "total": total or 0,
                      "running": running or 0, "tokens": tokens or 0, "budget": budget or 0, "updated": updated, "where": where, "go": go, **(extra or {})})

        def task(system, title, status, project, who, updated, go, detail=""):
            lane = LANE.get(status)
            if lane is None: out["dropped"] += 1; return
            T.append({"system": system, "title": _clip(title or "", 160), "status": status, "lane": lane, "project": project, "who": who or "", "updated": updated, "go": go,
                      "detail": _clip(detail or "", 200)})

        def company_part():
            c = self._company(me)
            if not c: return
            cid = c["id"]
            agents = {a["id"]: a["name"] for a in self.db.q("SELECT id, name FROM co_agents WHERE company_id=?", (cid,))}
            leads = {t["id"]: agents.get(t["lead_id"], "") for t in self.db.q("SELECT id, lead_id FROM co_teams WHERE company_id=?", (cid,))}
            projects = self.db.q("SELECT * FROM co_projects WHERE company_id=? AND status!='archived' ORDER BY id", (cid,))
            names = {p["id"]: p["name"] for p in projects}
            tasks = self.db.q("SELECT id, project_id, team_id, title, status, tokens, created, started, finished, error FROM co_tasks WHERE company_id=? ORDER BY id DESC LIMIT 300", (cid,))
            for p in projects:
                ts = [t for t in tasks if t["project_id"] == p["id"]]
                link = _j(p["link"], None) if p["link"] and str(p["link"]).startswith("{") else p["link"]
                proj("company", p["id"], p["name"], p["objective"], p["status"], sum(t["status"] == "done" for t in ts), sum(t["status"] != "cancelled" for t in ts),
                     sum(t["status"] in ("running", "evaluating") for t in ts), p["spent"], p["budget"], p["updated"], "Company", {"view": "company", "tab": "projects"},
                     {"success": _clip(p["success"] or "", 200)})
                if link:
                    out["deps"].append({"from": {"system": "company", "name": p["name"], "go": {"view": "company", "tab": "projects"}},
                                        "to": {"system": "mining", "name": f"My subnets{' · SN' + str(link.get('netuid')) if isinstance(link, dict) and link.get('netuid') else ''}", "go": {"view": "mining"}},
                                        "kind": "reads live from"})
            for t in tasks:
                task("company", t["title"], t["status"], names.get(t["project_id"], ""), leads.get(t["team_id"], ""), t["finished"] or t["started"] or t["created"],
                     {"view": "company", "tab": "projects"}, t["error"])

        def teams_part():
            ov = self.ov.view(me)
            byid = {t["id"]: t for t in ov["teams"]}
            comps = self._comps(me)
            for w in comps:
                t = byid.get(w["id"]) or {}
                go = {"view": "teams", "wid": w["id"], "sub": "status"}
                proj("teams", w["id"], self._label(w), w["goal"], "paused" if w["paused"] else t.get("state") or w["status"], t.get("done"), t.get("total"), t.get("working"),
                     t.get("day"), t.get("budget"), w["updated"], f"SN{w['netuid']}", go, {"state": t.get("state"), "line": t.get("line", "")})
            if not comps: return
            ids, labels = [w["id"] for w in comps], {w["id"]: self._label(w) for w in comps}
            names = {a["id"]: a["name"] for a in self.db.q(f"SELECT id, name FROM mw_agents WHERE comp_id IN ({','.join('?' * len(ids))})", ids)}
            for x in self.db.q(f"""SELECT id, comp_id, title, status, agent_id, updated, question FROM mw_tasks WHERE comp_id IN ({','.join('?' * len(ids))})
                                   AND (status!='done' OR done_at>?) ORDER BY updated DESC LIMIT 300""", ids + [now - 14 * DAY]):
                task("teams", x["title"], x["status"], labels.get(x["comp_id"], ""), names.get(x["agent_id"], ""), x["updated"],
                     {"view": "teams", "wid": x["comp_id"], "sub": "tasks"}, x["question"])

        def workforce_part():
            if not (workforce.ENABLED and self._has("wf_missions")): return
            ms = self.db.q("""SELECT id, title, goal, status, step, budget, tokens, bench_id, parent, created, updated FROM wf_missions WHERE user_id=?
                              AND (status IN ('queued','running','waiting') OR updated>?) ORDER BY id DESC LIMIT 40""", (uid, now - 30 * DAY))
            if not ms: return
            ids = [m["id"] for m in ms]
            marks = ",".join("?" * len(ids))
            asg = self.db.q(f"SELECT mission_id, agent, title, status, started, finished, summary FROM wf_assignments WHERE mission_id IN ({marks}) ORDER BY id DESC LIMIT 400", ids)
            names = {a["key"]: a["name"] for a in self.db.q("SELECT key, name FROM wf_agents WHERE user_id=?", (uid,))}
            titles = {m["id"]: m["title"] for m in ms}
            for m in ms:
                a = [x for x in asg if x["mission_id"] == m["id"]]
                proj("workforce", m["id"], m["title"], m["goal"], m["status"], sum(x["status"] == "done" for x in a), sum(x["status"] != "skipped" for x in a),
                     sum(x["status"] == "running" for x in a), m["tokens"], m["budget"], m["updated"], "Workforce", {"view": "workforce"}, {"step": m["step"]})
                if m["bench_id"] and self._has("mb_flows"):
                    f = self.db.q("SELECT comp_id FROM mb_flows WHERE id=?", (m["bench_id"],), one=True)
                    w = f and next((w for w in self._comps(me) if w["id"] == f["comp_id"]), None)
                    if w: out["deps"].append({"from": {"system": "workforce", "name": m["title"], "go": {"view": "workforce"}},
                                              "to": {"system": "teams", "name": self._label(w), "go": {"view": "teams", "wid": w["id"], "sub": "flow"}}, "kind": "researches for"})
                if m["parent"] and m["parent"] in titles:
                    out["deps"].append({"from": {"system": "workforce", "name": m["title"], "go": {"view": "workforce"}},
                                        "to": {"system": "workforce", "name": titles[m["parent"]], "go": {"view": "workforce"}}, "kind": "follows up"})
            for x in asg:
                task("workforce", x["title"], x["status"], titles.get(x["mission_id"], ""), names.get(x["agent"], x["agent"]), x["finished"] or x["started"], {"view": "workforce"}, x["summary"])
            live = [m["id"] for m in ms if m["status"] in ("queued", "running", "waiting")]  # a finished mission's order no longer matters
            items = self.db.q(f"SELECT mission_id, seq, title, depends FROM wf_items WHERE mission_id IN ({','.join('?' * len(live))})", live) if live else []
            seqs = {(x["mission_id"], x["seq"]): x["title"] for x in items}
            for it in items:
                for d in _j(it["depends"], [])[:3]:
                    if (it["mission_id"], d) in seqs:
                        out["deps"].append({"from": {"system": "workforce", "name": it["title"], "go": {"view": "workforce"}},
                                            "to": {"system": "workforce", "name": seqs[(it["mission_id"], d)], "go": {"view": "workforce"}},
                                            "kind": f"waits on · {titles.get(it['mission_id'], '')}"})

        def cycles_part():
            if not self._has("team_cycles"): return
            for c in self.db.q("""SELECT id, netuid, goal, status, budget, tokens, parent, updated FROM team_cycles
                                  WHERE id IN (SELECT MAX(id) FROM team_cycles WHERE user_id=? GROUP BY netuid) ORDER BY updated DESC""", (uid,)):
                ts = self.db.q("SELECT role, title, status, started, finished FROM team_tasks WHERE cycle_id=?", (c["id"],))
                go = {"view": "workspace", "netuid": c["netuid"], "tab": "team"}
                proj("projects", c["id"], f"SN{c['netuid']} project team", c["goal"], c["status"], sum(t["status"] == "done" for t in ts), sum(t["status"] != "skipped" for t in ts),
                     sum(t["status"] == "running" for t in ts), c["tokens"], c["budget"], c["updated"], f"SN{c['netuid']}", go)
                for t in ts: task("projects", t["title"], t["status"], f"SN{c['netuid']} project team", t["role"], t["finished"] or t["started"], go)

        def long_part():
            if not (infiagent.ENABLED and self._has("ia_tasks")): return
            for t in self.db.q("SELECT id, title, status, steps, budget, tokens, pause_reason, error, updated FROM ia_tasks WHERE user_id=? ORDER BY updated DESC LIMIT 30", (uid,)):
                proj("longtasks", t["id"], t["title"], t["pause_reason"] or t["error"] or "", t["status"], None, None, int(t["status"] == "running"), t["tokens"], t["budget"], t["updated"],
                     "Long tasks", {"view": "infiagent"})
                task("longtasks", t["title"], t["status"], "Long tasks", "InfiAgent", t["updated"], {"view": "infiagent"}, t["error"])

        def forces_part():
            if not self._has("mp_forces"): return
            labels = {w["id"]: (w, self._label(w)) for w in self._comps(me)}
            for f in self.db.q("SELECT comp_id, goal FROM mp_forces WHERE user_id=? AND status IN ('active','dissolving')", (uid,)):
                if f["comp_id"] in labels:
                    w, name = labels[f["comp_id"]]
                    out["deps"].append({"from": {"system": "portfolio", "name": f"Task force: {_clip(f['goal'] or '', 80)}", "go": {"view": "portfolio"}},
                                        "to": {"system": "teams", "name": name, "go": {"view": "teams", "wid": w["id"], "sub": "status"}}, "kind": "works inside"})

        for label, fn in (("Company", company_part), ("Competition teams", teams_part), ("Workforce", workforce_part), ("Project team", cycles_part),
                          ("Long tasks", long_part), ("Task forces", forces_part)):
            self._try(out, label, fn)
        T.sort(key=lambda x: -(x["updated"] or 0))
        del T[600:]
        out["counts"] = {"projects": len(P), "active": sum(p["status"] in ("active", "running", "working", "plan", "do", "check", "act") for p in P),
                         "tasks": len(T), **{k: sum(t["lane"] == k for t in T) for k in LANES}, "deps": len(out["deps"])}

    # ---------- Governance: recommendations, executions, audit trail, permissions ----------
    def governance(self, me, fresh=False):
        return self.cached("governance", me, self._governance, fresh)

    def _governance(self, me, out):
        uid, admin, agents = me["id"], me.get("role") == "admin", self.ov._agents_ok(me)
        out.update({"agents": agents, "recs": [], "runs": [], "audit": [], "perms": {"role": me.get("role"), "company": None, "agents": [], "teams": [], "workforce": []}})
        camps = {r["id"]: r["netuid"] for r in self.db.q("SELECT id, netuid FROM mh_campaigns WHERE user_id=?", (uid,))} if agents and self._has("mh_campaigns") else {}
        cmarks = ",".join("?" * len(camps))

        def recs():
            if camps and self._has("mh_recs"):
                for r in self.db.q(f"SELECT agent, kind, title, detail, impact, effort, created FROM mh_recs WHERE campaign_id IN ({cmarks}) AND status='open' ORDER BY id DESC LIMIT 30", list(camps)):
                    out["recs"].append({"source": "mining", "who": r["agent"] or "My subnets", "title": r["title"], "detail": _clip(r["detail"] or "", 300), "impact": r["impact"], "effort": r["effort"],
                                        "ts": r["created"], "go": {"view": "mining"}})
            if self._has("wf_improvements"):
                for r in self.db.q("SELECT change, root_cause, status, updated FROM wf_improvements WHERE user_id=? AND status IN ('proposed','testing','better') ORDER BY id DESC LIMIT 20", (uid,)):
                    out["recs"].append({"source": "workforce", "who": "Improvement engineer", "title": _clip(r["change"] or "", 160), "detail": _clip(r["root_cause"] or "", 300),
                                        "impact": "tested better" if r["status"] == "better" else r["status"], "effort": None, "ts": r["updated"], "go": {"view": "workforce"}})
            if self._has("agent_proposals"):
                for r in self.db.q("SELECT kind, payload, reason, created FROM agent_proposals WHERE user_id=? AND status='pending' ORDER BY id DESC LIMIT 20", (uid,)):
                    p = _j(r["payload"], {})
                    out["recs"].append({"source": "agents", "who": "Your agent", "title": _clip(p.get("title") or p.get("name") or r["kind"] or "", 160), "detail": _clip(r["reason"] or "", 300),
                                        "impact": None, "effort": None, "ts": r["created"], "go": {"view": "agents"}})
            if self._has("mp_reviews"):
                r = self.db.q("SELECT headline, ts, finished FROM mp_reviews WHERE user_id=? AND status='done' AND (applied IS NULL OR applied='' OR applied='0') ORDER BY id DESC LIMIT 1", (uid,), one=True)
                if r and r["headline"]:
                    out["recs"].append({"source": "portfolio", "who": "Portfolio Manager", "title": _clip(r["headline"], 160), "detail": "The latest portfolio review: apply its moves or start a task force.",
                                        "impact": None, "effort": None, "ts": r["finished"] or r["ts"], "go": {"view": "portfolio"}})
            if admin and self._has("hq_issues"):
                for r in self.db.q("""SELECT title, recommendation, severity, last_seen FROM hq_issues WHERE status='open' AND recommendation IS NOT NULL AND recommendation!=''
                                      ORDER BY last_seen DESC LIMIT 10"""):
                    out["recs"].append({"source": "hq", "who": "Agent HQ", "title": r["title"], "detail": _clip(r["recommendation"] or "", 300), "impact": r["severity"], "effort": None,
                                        "ts": r["last_seen"], "go": {"view": "hq"}})
            out["recs"].sort(key=lambda x: -(x["ts"] or 0))

        def runs():
            c = self._company(me) if agents else None
            if c:
                for r in self.db.q("""SELECT e.status, e.result, e.started, e.finished, e.by_user, a.title, a.action_type FROM co_executions e JOIN co_approvals a ON a.id=e.approval_id
                                      WHERE a.company_id=? ORDER BY e.id DESC LIMIT 20""", (c["id"],)):
                    out["runs"].append({"source": "company", "title": f"{(company.ACTIONS.get(r['action_type']) or [r['action_type']])[0]}: {r['title']}", "status": r["status"],
                                        "result": _clip(r["result"] or "", 300), "by": r["by_user"], "ts": r["finished"] or r["started"]})
            if camps:
                for r in self.db.q(f"""SELECT title, status, result, decided, decided_by FROM mh_actions WHERE campaign_id IN ({cmarks}) AND status IN ('done','failed','running')
                                       ORDER BY decided DESC LIMIT 20""", list(camps)):
                    out["runs"].append({"source": "mining", "title": r["title"], "status": r["status"], "result": _clip(r["result"] or "", 300), "by": r["decided_by"], "ts": r["decided"]})
            if admin and self._has("hq_fixes"):
                for r in self.db.q("SELECT label, status, result, verified, decided, decided_by FROM hq_fixes WHERE status IN ('done','failed','running') ORDER BY decided DESC LIMIT 15"):
                    out["runs"].append({"source": "hq", "title": r["label"], "status": r["status"], "result": _clip(r["result"] or "", 300), "verified": r["verified"], "by": r["decided_by"], "ts": r["decided"]})
            if self._has("agent_proposals"):
                for r in self.db.q("SELECT kind, status, result, decided FROM agent_proposals WHERE user_id=? AND decided IS NOT NULL ORDER BY decided DESC LIMIT 10", (uid,)):
                    out["runs"].append({"source": "agents", "title": r["kind"] or "Proposal", "status": r["status"], "result": _clip(r["result"] or "", 300), "by": me["username"], "ts": r["decided"]})
            out["runs"].sort(key=lambda x: -(x["ts"] or 0))

        def audit():
            c = self._company(me) if agents else None
            if c:
                for r in self.db.q("SELECT ts, actor_type, actor, action, target_type, target_id FROM co_audit WHERE company_id=? ORDER BY id DESC LIMIT 60", (c["id"],)):
                    out["audit"].append({"source": "company", "ts": r["ts"], "actor": f"{r['actor']}" + (" (agent)" if r["actor_type"] == "agent" else ""), "action": r["action"],
                                         "target": f"{r['target_type'] or ''} {r['target_id'] or ''}".strip()})
            # the account's own sign-ins and changes; administrators read everyone's from the Audit log page
            for r in self.db.q("SELECT ts, actor, action, target, ip FROM audit WHERE actor=? OR target=? ORDER BY id DESC LIMIT 40", (me["username"], me["username"])):
                out["audit"].append({"source": "account", "ts": r["ts"], "actor": r["actor"], "action": r["action"], "target": r["target"] or "", "ip": r["ip"] if admin else None})
            out["audit"].sort(key=lambda x: -(x["ts"] or 0))
            del out["audit"][80:]

        def perms():
            P = out["perms"]
            c = self._company(me) if agents else None
            if c:
                s = _j(c["settings"], {})
                P["company"] = {"autonomy": s.get("autonomy"), "organization": s.get("organization"), "actions_off": s.get("actions_off") or [],
                                "actions": {k: v[0] for k, v in company.ACTIONS.items()}}
                tools = {}
                for t in self.db.q("SELECT agent_id, SUM(enabled) n, COUNT(*) total FROM co_agent_tool_permissions GROUP BY agent_id") if self._has("co_agent_tool_permissions") else []:
                    tools[t["agent_id"]] = (t["n"] or 0, t["total"])
                for a in self.db.q("SELECT id, name, title, stage, permissions, max_load, status FROM co_agents WHERE company_id=? AND status!='archived' ORDER BY id", (c["id"],)):
                    pm = _j(a["permissions"], {})
                    P["agents"].append({"system": "company", "name": a["name"], "role": a["title"] or "", "stage": a["stage"], "max_load": a["max_load"],
                                        "may": {k: pm.get(k) or [] for k in ("read", "write", "execute")} if isinstance(pm, dict) else {},  # the agent's contract
                                        "tools": tools.get(a["id"]), "go": {"view": "company", "tab": "agents"}})
            if agents and workforce.ENABLED and self._has("wf_agents"):
                for a in self.db.q("SELECT name, title, team, level, tools FROM wf_agents WHERE user_id=? AND status!='archived' ORDER BY team, id", (uid,)):
                    P["workforce"].append({"name": a["name"], "role": a["title"] or "", "team": workforce.TEAM_NAME.get(a["team"], a["team"] or ""), "level": a["level"],
                                           "tools": _j(a["tools"], [])})
            for w in self._comps(me) if agents else []:
                P["teams"].append({"name": self._label(w), "autopilot": bool(w["autopilot"]), "paused": bool(w["paused"]), "budget": w["budget"],
                                   "go": {"view": "teams", "wid": w["id"], "sub": "settings"}})

        for label, fn in (("Recommendations", recs), ("Executions", runs), ("Audit trail", audit), ("Permissions", perms)):
            self._try(out, label, fn)

    # ---------- Intelligence & Evaluation ----------
    def evaluation(self, me, fresh=False):
        self._agents(me)
        return self.cached("evaluation", me, self._evaluation, fresh)

    def _evaluation(self, me, out):
        uid, now = me["id"], time.time()
        month = now - 30 * DAY
        out.update({"scores": [], "benchmarks": [], "experiments": [], "models": [], "sources": [], "routes": [], "long": [], "knowledge": {}, "skills": {}})

        def scores():
            c = self._company(me)
            if c:
                for r in self.db.q("""SELECT a.by_agent, g.name, g.title, COUNT(*) n, AVG(e.score) avg, SUM(e.verdict IN ('pass','accept','approved')) ok FROM co_evals e
                                      JOIN co_artifacts a ON a.id=e.artifact_id LEFT JOIN co_agents g ON g.id=a.by_agent WHERE a.company_id=? AND e.ts>? GROUP BY a.by_agent
                                      ORDER BY avg DESC""", (c["id"], month)):
                    out["scores"].append({"system": "company", "name": r["name"] or f"#{r['by_agent']}", "role": r["title"] or "", "n": r["n"], "avg": round(r["avg"], 1) if r["avg"] is not None else None,
                                          "scale": 10, "ok": None, "fail": None, "go": {"view": "company", "tab": "agents"}})
            if workforce.ENABLED and self._has("wf_assignments"):
                names = {a["key"]: (a["name"], a["team"]) for a in self.db.q("SELECT key, name, team FROM wf_agents WHERE user_id=?", (uid,))}
                for r in self.db.q("""SELECT a.agent, COUNT(*) n, AVG(a.score) avg, SUM(a.status='done') ok, SUM(a.status='failed') bad FROM wf_assignments a JOIN wf_missions m ON m.id=a.mission_id
                                      WHERE m.user_id=? AND a.finished>? GROUP BY a.agent""", (uid, month)):
                    nm, team = names.get(r["agent"], (r["agent"], ""))
                    out["scores"].append({"system": "workforce", "name": nm, "role": workforce.TEAM_NAME.get(team, team or ""), "n": r["n"], "avg": round(r["avg"], 1) if r["avg"] is not None else None,
                                          "scale": 10, "ok": r["ok"], "fail": r["bad"], "go": {"view": "workforce"}})
            comps = self._comps(me)
            if comps:
                ids = [w["id"] for w in comps]
                labels = {w["id"]: self._label(w) for w in comps}
                for r in self.db.q(f"""SELECT r.agent_id, g.name, g.title, r.comp_id, COUNT(*) n, SUM(r.status='done') ok, SUM(r.status IN ('failed','error')) bad FROM mw_runs r
                                       LEFT JOIN mw_agents g ON g.id=r.agent_id WHERE r.comp_id IN ({','.join('?' * len(ids))}) AND r.started>? GROUP BY r.agent_id""", ids + [month]):
                    out["scores"].append({"system": "teams", "name": r["name"] or "Agent", "role": f"{r['title'] or ''} · {labels.get(r['comp_id'], '')}".strip(" ·"), "n": r["n"], "avg": None, "scale": None,
                                          "ok": r["ok"], "fail": r["bad"], "go": {"view": "teams", "wid": r["comp_id"], "sub": "team"}})

        def benches():
            if self._has("wf_benchmarks"):
                for b in self.db.q("SELECT title, goal, arms, trials, status, created, finished FROM wf_benchmarks WHERE user_id=? ORDER BY id DESC LIMIT 12", (uid,)):
                    out["benchmarks"].append({"title": b["title"], "goal": _clip(b["goal"] or "", 200), "arms": len(_j(b["arms"], [])), "trials": b["trials"], "status": b["status"],
                                              "ts": b["finished"] or b["created"], "go": {"view": "workforce"}})
            comps = self._comps(me)
            if comps and self._has("mb_experiments") and self._has("mb_flows"):
                labels = {w["id"]: (w["id"], self._label(w)) for w in comps}
                flows = {f["id"]: labels[f["comp_id"]] for f in self.db.q("SELECT id, comp_id FROM mb_flows") if f["comp_id"] in labels}
                if flows:
                    for e in self.db.q(f"""SELECT flow_id, kind, label, tasks, solved, runs, passed, cost, status, decision, created, finished FROM mb_experiments
                                           WHERE flow_id IN ({','.join('?' * len(flows))}) ORDER BY id DESC LIMIT 20""", list(flows)):
                        wid, name = flows[e["flow_id"]]
                        out["experiments"].append({"label": e["label"] or e["kind"], "where": name, "tasks": e["tasks"], "solved": e["solved"], "runs": e["runs"], "passed": e["passed"],
                                                   "cost": e["cost"], "status": e["status"], "decision": e["decision"], "ts": e["finished"] or e["created"],
                                                   "go": {"view": "teams", "wid": wid, "sub": "lab"}})

        def models():
            if self._has("llm_usage"):
                day = time.strftime("%Y-%m-%d", time.gmtime(month))
                out["models"] = self.db.q("SELECT model, SUM(tokens) tokens, COUNT(*) calls FROM llm_usage WHERE user_id=? AND day>=? GROUP BY model ORDER BY tokens DESC LIMIT 12", (uid, day))
                out["sources"] = self.db.q("SELECT source, SUM(tokens) tokens, COUNT(*) calls FROM llm_usage WHERE user_id=? AND day>=? GROUP BY source ORDER BY tokens DESC LIMIT 12", (uid, day))
            if workforce.ENABLED and self._has("wf_runs"):
                out["routes"] = self.db.q("""SELECT COALESCE(route, '') route, COALESCE(model, '') model, COUNT(*) runs, AVG(score) avg, SUM(status='failed') failed, SUM(tokens) tokens
                                             FROM wf_runs WHERE user_id=? AND started>? GROUP BY route, model ORDER BY runs DESC LIMIT 15""", (uid, month))
                for r in out["routes"]: r["avg"] = round(r["avg"], 1) if r["avg"] is not None else None

        def long():
            if infiagent.ENABLED and self._has("ia_tasks"):
                for t in self.db.q("SELECT id, title, status, steps, budget, tokens, pause_reason, error, created, updated FROM ia_tasks WHERE user_id=? ORDER BY updated DESC LIMIT 20", (uid,)):
                    runs = self.db.q("SELECT COUNT(*) n FROM ia_runs WHERE task_id=?", (t["id"],), one=True)["n"] if self._has("ia_runs") else 0
                    out["long"].append({**{k: t[k] for k in ("title", "status", "steps", "budget", "tokens", "created", "updated")}, "runs": runs,
                                        "note": _clip(t["pause_reason"] or t["error"] or "", 200), "go": {"view": "infiagent"}})

        def knowledge():
            K = out["knowledge"]
            if workforce.ENABLED and self._has("wf_memory"):
                K["memory"] = {"by_kind": self.db.q("SELECT kind, COUNT(*) n, SUM(cited) cited, SUM(helped) helped FROM wf_memory WHERE user_id=? AND status='active' GROUP BY kind ORDER BY n DESC", (uid,)),
                               "top": self.db.q("SELECT kind, text, cited, helped FROM wf_memory WHERE user_id=? AND status='active' ORDER BY helped DESC, cited DESC LIMIT 6", (uid,))}
                for t in K["memory"]["top"]: t["text"] = _clip(t["text"] or "", 200)
            if mining.ENABLED and self._has("mk_items"):
                K["portfolio"] = self.db.q("SELECT scope, COUNT(*) n FROM mk_items WHERE user_id=? GROUP BY scope", (uid,))
            c = self._company(me)
            if c: K["company"] = self.db.q("SELECT scope, COUNT(*) n FROM co_knowledge WHERE company_id=? GROUP BY scope", (c["id"],))
            S = out["skills"]
            if self._has("agent_skills"): S["skills"] = self.db.q("SELECT COUNT(*) n FROM agent_skills WHERE owner_id=?", (uid,), one=True)["n"]
            if self._has("custom_agents"): S["agents"] = self.db.q("SELECT COUNT(*) n FROM custom_agents WHERE owner_id=? AND status!='archived'", (uid,), one=True)["n"]
            if self._has("ml_skills") and self._has("ml_loadouts"): S["loadouts"] = self.db.q("SELECT COUNT(*) n FROM ml_loadouts", one=True)["n"] if me.get("role") == "admin" else None

        for label, fn in (("Agent scores", scores), ("Benchmarks", benches), ("Models", models), ("Long tasks", long), ("Knowledge", knowledge)):
            self._try(out, label, fn)
        out["scores"].sort(key=lambda x: (-(x["n"] or 0)))

    # ---------- Personal workspace ----------
    def workspace(self, me, fresh=False):
        return self.cached("workspace", me, self._workspace, fresh)

    def _workspace(self, me, out):
        uid, now = me["id"], time.time()
        out.update({"notes": {}, "files": {}, "boards": [], "study": {}, "subnets": 0, "tokens_week": None, "agents": self.ov._agents_ok(me)})

        def notes():
            rows = self.db.q("SELECT id, netuid, text, kind, pinned, stage, updated FROM workspace_notes WHERE user_id=? ORDER BY updated DESC", (uid,))
            out["notes"] = {"total": len(rows), "pinned": sum(bool(r["pinned"]) for r in rows), "daily": sum(r["kind"] == "daily" for r in rows),
                            "week": sum((r["updated"] or 0) > now - 7 * DAY for r in rows),
                            "stages": {s: sum(r["stage"] == s for r in rows) for s in ("plan", "do", "check", "act")},
                            "recent": [{"id": r["id"], "netuid": r["netuid"], "kind": r["kind"], "text": _clip((r["text"] or "").strip().split("\n")[0].lstrip("#").strip(), 120), "updated": r["updated"]} for r in rows[:6]]}
            f = self.db.q("SELECT COUNT(*) n, COALESCE(SUM(size), 0) size FROM workspace_files WHERE user_id=?", (uid,), one=True)
            out["files"] = {"n": f["n"], "size": f["size"]}
            out["subnets"] = self.db.q("SELECT COUNT(*) n FROM workspace_subnets WHERE user_id=?", (uid,), one=True)["n"]

        def boards():
            if not self._has("boards"): return
            for b in self.db.q("SELECT id, owner_id, name, shared_with, updated, updated_by FROM boards ORDER BY updated DESC LIMIT 200"):
                shared = _j(b["shared_with"], [])
                if b["owner_id"] == uid or me["username"] in shared or "*" in shared:
                    out["boards"].append({"id": b["id"], "name": b["name"], "mine": b["owner_id"] == uid, "shared": len(shared), "updated": b["updated"], "by": b["updated_by"]})
            del out["boards"][12:]

        def study():
            if not self._has("study_topics"): return
            by = self.db.q("SELECT track, COUNT(*) n, SUM(done) done FROM study_topics WHERE user_id=? GROUP BY track", (uid,))
            days = self.db.q("SELECT day, actions FROM study_days WHERE user_id=? ORDER BY day DESC LIMIT 14", (uid,)) if self._has("study_days") else []
            out["study"] = {"tracks": by, "days": [{"day": d["day"], "n": len(_j(d["actions"], [])) if str(d["actions"] or "").startswith("[") else (d["actions"] or 0)} for d in days]}

        def tokens():
            if self._has("llm_usage"):
                out["tokens_week"] = self.db.q("SELECT COALESCE(SUM(tokens), 0) n FROM llm_usage WHERE user_id=? AND ts>?", (uid, now - 7 * DAY), one=True)["n"]

        for label, fn in (("Notes", notes), ("Whiteboards", boards), ("Study", study), ("Tokens", tokens)):
            self._try(out, label, fn)

    # ---------- Settings: the account ----------
    def settings(self, me, fresh=False):
        return self.cached("settings", me, self._settings, fresh)

    def _settings(self, me, out):
        uid, now = me["id"], time.time()
        u = self.db.q("SELECT username, email, role, totp_enabled, recovery, created, last_login, last_ip, settings FROM users WHERE id=?", (uid,), one=True)
        rec = _j(u["recovery"], [])
        out["me"] = {"username": u["username"], "email": bool(u["email"]), "role": u["role"], "totp": bool(u["totp_enabled"]),
                     "recovery_left": len(rec) if isinstance(rec, list) else None, "created": u["created"], "last_login": u["last_login"], "last_ip": u["last_ip"]}
        out["sessions"] = self.db.q("SELECT stage, created, last_seen, ip, ua FROM sessions WHERE user_id=? AND expires>? ORDER BY last_seen DESC LIMIT 10", (uid, now))
        for s in out["sessions"]: s["ua"] = _clip(s["ua"] or "", 120)
        p = self.db.q("SELECT prefs FROM alert_prefs WHERE user_id=?", (uid,), one=True) if self._has("alert_prefs") else None
        prefs = _j(p["prefs"], {}) if p else {}
        out["alerts"] = {"set": bool(p), "on": sum(1 for v in prefs.values() if v is True or (isinstance(v, dict) and v.get("on", True))) if isinstance(prefs, dict) else None,
                         "total": len(prefs) if isinstance(prefs, dict) else None}
        out["push"] = bool(self.db.q("SELECT 1 FROM push_prefs WHERE user_id=?", (uid,), one=True)) if self._has("push_prefs") else False
        out["recent"] = self.db.q("SELECT ts, action, ip FROM audit WHERE actor=? ORDER BY id DESC LIMIT 8", (u["username"],))


def build(db, require, ov, co=None):
    r = APIRouter(prefix="/api/hub")
    h = Hubs(db, ov, co)
    r.state = {"hubs": h}

    @r.get("/org")
    def org(req: Request, fresh: bool = False): return h.org(require(req), fresh)

    @r.get("/projects")
    def projects(req: Request, fresh: bool = False): return h.projects(require(req), fresh)

    @r.get("/governance")
    def governance(req: Request, fresh: bool = False): return h.governance(require(req), fresh)

    @r.get("/evaluation")
    def evaluation(req: Request, fresh: bool = False): return h.evaluation(require(req), fresh)

    @r.get("/workspace")
    def workspace_(req: Request, fresh: bool = False): return h.workspace(require(req), fresh)

    @r.get("/settings")
    def settings(req: Request, fresh: bool = False): return h.settings(require(req), fresh)

    return r
