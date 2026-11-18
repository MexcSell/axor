"""Organization HQ: the executive layer, squads, unit assignments, budgets, the authority ladder and the knowledge read-through,
on top of organization.py's hierarchy + matrix (a mixin of Organization; organization.js draws both).

What it adds, each tied to something that already exists:
- Executive Office. The CEO's executive staff each hold one company-wide portfolio (CTO, CRO, COO, CFO, CSO, CSecO), seeded
  from the Company leadership's own roles (Cyrus is the Company's CTO Agent, so he is the CTO; Ezra the Research Director, so the
  CRO). Each shared department has one executive sponsor: a dotted line (oversight, scope, the specialist requests that go
  through it), never a permanent reporting line, so nobody's manager or escalation path changes.
- Shared departments. Eight, each a service layer every division draws on: Research & Intelligence, Software Engineering,
  Data & Evaluation, AI & Model Intelligence, Security & Compliance, Quality Assurance, Infrastructure & DevOps, Knowledge
  Management. The seeded ones are renamed only while they still carry the seeded name; a department you dissolved stays gone.
- Squads. Each Competition team's squads (mw_agents.squad, its own data) become squad units inside the team's unit, led by the
  squad's head; the team's agents move into their squad (only while still sitting in the team unit: a move you made stands) and
  report to the squad lead, who reports to the Director, as the team's own review chain already works.
- Matrix. An agent keeps one permanent home (unit + manager) and a department affiliation (its profession: Hana's home is the
  Bittensor Division, her department Research & Intelligence), and carries assignments to other units (a squad, a team, a
  division) with a scoped authority level that is never above its own. Specialists are lent, never copied: one identity,
  many assignments. Requests for a specialist go to Approvals unless your "assign" policy says apply.
- Budgets. Daily tokens, the unit the agent core's daily limit and each team's 24-hour budget already use. A unit's allocation
  can't exceed its parent's; the top units' can't exceed your daily limit (Agent Operations → Budget). Teams keep their own
  budget (their governor enforces it); it is read here and counted against the division.
- Authority ladder. Organizational authority by position: you (owner · chairman) → CEO → executive staff → division and
  department managers → competition directors → squad and team leaders → agents. Execution authority (L0-L4) stays separate.
- Knowledge & experience. Read through from the Knowledge hub (kb_items), the teams' notebooks (mw_notes) and lessons
  (mk_items), files and experiments: counted and listed, never copied.
"""
import json, time

from fastapi import HTTPException

DAY = 86400

PORTFOLIOS = {
    "cto": {"short": "CTO", "title": "Chief Technology Officer", "about": "Technology, engineering standards, models and infrastructure."},
    "cro": {"short": "CRO", "title": "Chief Research Officer", "about": "Research, data, evaluation and the organization's knowledge."},
    "coo": {"short": "COO", "title": "Chief Operations Officer", "about": "Delivery across divisions, quality and day-to-day operations."},
    "cfo": {"short": "CFO", "title": "Chief Financial Officer", "about": "Budgets, spend and cost recommendations."},
    "cso": {"short": "CSO", "title": "Chief Strategy Officer", "about": "Strategy, priorities and the portfolio of divisions and projects."},
    "csec": {"short": "CSecO", "title": "Chief Security Officer", "about": "Security, compliance, sandboxing and risk."},
}
# a Company leadership agent's portfolio, by its role in the Company (not by the order of names)
CO_PORTFOLIO = {"cto": "cto", "research_director": "cro", "coo": "coo", "cfo": "cfo", "ceo": "cso", "governance": "csec"}

# (key, name, purpose, sponsor portfolio, link, the seeded name it replaces)
DEPARTMENTS = [
    ("research", "Research & Intelligence", "Research, discovery and technical analysis for every division.", "cro", "wf_team:research", "Research"),
    ("engineering", "Software Engineering", "Python, TypeScript and infrastructure code; the engineering standard every project uses.", "cto", "wf_team:engineering", "Engineering"),
    ("data", "Data & Evaluation", "Datasets, benchmarks and validation: scores work against its objective, never its own.", "cro", "wf_team:evaluation", "Evaluation"),
    ("ai", "AI & Model Intelligence", "Model selection, fine-tuning and routing.", "cto", "dept:ai", None),
    ("security", "Security & Compliance", "Sandboxing, access and risk assessment.", "csec", "wf_team:security", "Security"),
    ("qa", "Quality Assurance", "Independent testing and verification.", "coo", "dept:qa", None),
    ("infra", "Infrastructure & DevOps", "Servers, deployments, releases and monitoring.", "cto", "wf_team:operations", "Operations"),
    ("knowledge", "Knowledge Management", "Memory, documentation and reusable skills.", "cro", "dept:knowledge", None),
]
DEPT_BY_LINK = {d[4]: d for d in DEPARTMENTS}
SPONSOR_BY_LINK = {**{d[4]: d[3] for d in DEPARTMENTS}, "wf_team:strategy": "cso"}
# Company agents' profession (department affiliation) and their role in their division's leadership, by their Company role
CO_DEPT = {"subnet_intel": "research", "miner_engineer": "engineering", "benchmark": "data", "perf_analyst": "data", "experiment_designer": "ai",
           "reliability": "infra", "protocol_researcher": "research", "core_dev": "engineering", "test_engineer": "qa", "security_analyst": "security",
           "ecosystem_researcher": "research", "product_researcher": "research", "software_engineer": "engineering", "qa": "qa", "doc_agent": "knowledge"}
CO_UNIT_ROLE = {"subnet_intel": "Mining Research Lead", "miner_engineer": "Engineering Lead", "benchmark": "Evaluation & Performance Lead",
                "protocol_researcher": "Research Lead", "core_dev": "Engineering Lead", "product_researcher": "Research Lead",
                "software_engineer": "Engineering Lead"}
DEPT_LINK = {d[0]: d[4] for d in DEPARTMENTS}

TIERS = [
    {"tier": "owner", "name": "Owner · Chairman", "authority": "Company strategy and reserved decisions", "who": "You"},
    {"tier": "ceo", "name": "CEO", "authority": "Organization-wide coordination and resource allocation"},
    {"tier": "executive", "name": "Executive staff", "authority": "Functional leadership: each owns one company-wide portfolio"},
    {"tier": "division", "name": "Division and department managers", "authority": "Division strategy and execution, within the allocated budget"},
    {"tier": "director", "name": "Competition directors", "authority": "Competition delivery, inside their own team only"},
    {"tier": "squad", "name": "Squad and team leaders", "authority": "Task allocation and supervision"},
    {"tier": "agent", "name": "Agents", "authority": "Assigned execution"},
]
RANK_TIER = {"ceo": "ceo", "executive": "executive", "division_manager": "division", "department_manager": "division",
             "competition_director": "director", "team_leader": "squad", "squad_leader": "squad", "specialist": "agent", "unplaced": "agent"}
RESERVED = ["Company strategy and the organization's direction", "Major budgets: your daily limit and every allocation an agent proposes",
            "External commitments: messages, posts, payments and anything that binds you outside", "Production deployments",
            "Destructive operations: deleting data, dissolving work"]
TEAM_BUDGET = 150_000  # mining_work.BUDGET: a team without its own budget runs on this many tokens a day


def _j(s, d=None):
    try: return json.loads(s) if s else d
    except (TypeError, ValueError): return d


def _clip(s, n): s = str(s or ""); return s if len(s) <= n else s[:n - 1] + "…"


def _tok(n): return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{round(n / 1e3)}k" if n >= 1e3 else str(n)


class HQ:
    """Mixin of organization.Organization (which provides db, _agent, _unit, _org, _set_line, _auto_manager, _op_set_manager …)."""

    def _hq_schema(self):
        q = self.db.q
        for table, cols in (("og_agents", "portfolio TEXT, dept_id INTEGER, unit_role TEXT"), ("og_units", "sponsor_key TEXT"),
                            ("og_assign", "unit_id INTEGER, scope INTEGER")):
            have = {c["name"] for c in q(f"PRAGMA table_info({table})")}
            for col in cols.split(", "):
                if col.split()[0] not in have: q(f"ALTER TABLE {table} ADD COLUMN {col}")
        # one active assignment per agent and unit (mission assignments have their own index; NULL missions don't collide there)
        q("CREATE UNIQUE INDEX IF NOT EXISTS og_assign_unit ON og_assign (unit_id, agent_key) WHERE status='active' AND mission_id IS NULL")

    def _cols(self, table):
        return {c["name"] for c in self.db.q(f"PRAGMA table_info({table})")} if self._has(table) else set()

    # ---------- sync: before the agents (units) and after them (people) ----------
    def _ensure_departments(self, uid):
        """The eight shared departments: the seeded ones renamed while they still carry the seeded name, the missing ones added.
        A department you dissolved isn't made again."""
        q, now = self.db.q, time.time()
        from .organization import DEPT_PURPOSE
        for key, name, purpose, _s, link, old in DEPARTMENTS:
            u = q("SELECT id, name, purpose, status FROM og_units WHERE user_id=? AND link=? ORDER BY id DESC LIMIT 1", (uid, link), one=True)
            if not u:
                q("INSERT INTO og_units (user_id, kind, name, purpose, link, created, updated) VALUES (?,?,?,?,?,?,?)", (uid, "department", name, purpose, link, now, now))
            elif u["status"] == "active" and old and u["name"] == old:
                seeded = DEPT_PURPOSE.get(link.split(":", 1)[1], "")
                q("UPDATE og_units SET name=?, purpose=?, updated=? WHERE id=?", (name, purpose if (u["purpose"] or "") in ("", seeded) else u["purpose"], now, u["id"]))

    def _team_squads(self, uid):
        """(comp_id, squad) for the open teams' active agents that sit in a squad (not the Director)."""
        if "squad" not in self._cols("mw_agents"): return []
        # the Director's own squad (Command) isn't a squad unit: its people work straight under the Director
        return self.db.q("""SELECT DISTINCT a.comp_id, a.squad FROM mw_agents a JOIN mw_comps w ON w.id=a.comp_id JOIN mh_campaigns c ON c.id=w.campaign_id
                            WHERE c.user_id=? AND COALESCE(w.status,'active')!='closed' AND a.active=1 AND COALESCE(a.lead,0)=0 AND COALESCE(a.squad,'')!=''
                            AND a.squad NOT IN (SELECT l.squad FROM mw_agents l WHERE l.comp_id=a.comp_id AND l.lead=1 AND l.active=1 AND l.squad IS NOT NULL)""", (uid,))

    def _ensure_squad_units(self, uid):
        """A squad unit inside each team unit for every squad its agents sit in; a squad you dissolved isn't made again; squads of
        a team that closed close with it (their people unplaced), and reopen with it."""
        q, now = self.db.q, time.time()
        teams = {r["link"]: r for r in q("SELECT id, link, status FROM og_units WHERE user_id=? AND link LIKE 'mw_comp:%' ORDER BY id", (uid,))}
        have = {r["link"]: r for r in q("SELECT id, link, status, parent_id FROM og_units WHERE user_id=? AND link LIKE 'mw_squad:%'", (uid,))}
        try:
            from .mining_packs import SQUADS
        except Exception:  # noqa: BLE001 - names only
            SQUADS = {}
        for r in self._team_squads(uid):
            t = teams.get(f"mw_comp:{r['comp_id']}")
            link = f"mw_squad:{r['comp_id']}:{r['squad']}"
            if not t or t["status"] != "active" or link in have: continue
            name = SQUADS.get(r["squad"]) or str(r["squad"]).replace("_", " ").capitalize()
            q("INSERT INTO og_units (user_id, kind, name, purpose, parent_id, link, created, updated) VALUES (?,?,?,?,?,?,?,?)",
              (uid, "squad", name, "A squad of this Competition team: its lead allocates and reviews the squad's work.", t["id"], link, now, now))
        for s in have.values():
            t = teams.get("mw_comp:" + s["link"].split(":")[1])
            up = bool(t and t["status"] == "active")
            if s["status"] == "active" and not up:
                q("UPDATE og_units SET status='closed', updated=? WHERE id=?", (now, s["id"]))
                q("UPDATE og_agents SET unit_id=NULL, updated=? WHERE user_id=? AND unit_id=?", (now, uid, s["id"]))
            elif s["status"] == "closed" and up:
                q("UPDATE og_units SET status='active', parent_id=?, updated=? WHERE id=?", (t["id"], now, s["id"]))

    def _ensure_squad_people(self, uid):
        """Each squad led by its head (unless you gave it someone else); the team's agents still in the team unit move into their
        squad and report to its lead (the lead to the Director). An agent you moved stays where you put it."""
        q = self.db.q
        squads = {r["link"]: r for r in q("SELECT id, link, manager_key, parent_id FROM og_units WHERE user_id=? AND link LIKE 'mw_squad:%' AND status='active'", (uid,))}
        if not squads: return
        team_agents = [a for a in self._team_agents(uid) if a.get("squad") and not a["lead"] and a["active"]]
        for link, s in squads.items():
            _, comp, squad = link.split(":", 2)
            head = next((a for a in team_agents if str(a["comp_id"]) == comp and a["squad"] == squad and a.get("head")), None)
            want, cur = (f"teams:{head['id']}" if head else None), s["manager_key"]
            ours = cur is None or (cur.startswith("teams:") and (self._agent(uid, cur, need=False) or {}).get("unit_id") == s["id"])
            if want and cur != want and ours and self._agent(uid, want, need=False):
                try: self._op_set_manager(uid, {"unit_id": s["id"], "key": want}, "system")
                except HTTPException: pass
        for a in team_agents:
            s = squads.get(f"mw_squad:{a['comp_id']}:{a['squad']}")
            k = f"teams:{a['id']}"
            ag = self._agent(uid, k, need=False)
            if not s or not ag or ag["status"] in ("archived", "gone") or ag["unit_id"] != s["parent_id"]: continue
            q("UPDATE og_agents SET unit_id=?, updated=? WHERE user_id=? AND key=?", (s["id"], time.time(), uid, k))
            try: self._set_line(uid, k, self._auto_manager(uid, k, s["id"]), "system", "joined its squad")
            except HTTPException: pass

    def _ensure_people(self, uid):
        """Portfolios for the Company's leadership, sponsors for the departments, departments and division roles for the Company's
        division agents, and a place for agents whose department exists now (only those nobody has placed by hand)."""
        q, now = self.db.q, time.time()
        co = {}
        if self._has("co_agents") and self._has("co_company"):
            co = {f"company:{r['id']}": r for r in q("""SELECT a.id, a.key, a.category, a.division_id FROM co_agents a JOIN co_company c ON c.id=a.company_id
                                                       WHERE c.user_id=?""", (uid,))}
        dept_unit = {r["link"]: r["id"] for r in q("SELECT id, link FROM og_units WHERE user_id=? AND kind='department' AND status='active'", (uid,))}
        ex = q("SELECT id FROM og_units WHERE user_id=? AND link='exec' AND status='active'", (uid,), one=True)
        held = {r["portfolio"] for r in q("SELECT portfolio FROM og_agents WHERE user_id=? AND COALESCE(portfolio,'')!='' AND status NOT IN ('archived','gone')", (uid,))}
        rows = q("SELECT key, portfolio, dept_id, unit_role, unit_id, status FROM og_agents WHERE user_id=? AND status NOT IN ('archived','gone')", (uid,))
        for a in rows:
            src = co.get(a["key"])
            if not src: continue
            sets = {}
            if a["portfolio"] is None and src["category"] == "leadership":
                p = CO_PORTFOLIO.get(src["key"])
                if p and p not in held: sets["portfolio"] = p; held.add(p)
            if a["dept_id"] is None and src["key"] in CO_DEPT and dept_unit.get(DEPT_LINK[CO_DEPT[src["key"]]]):
                sets["dept_id"] = dept_unit[DEPT_LINK[CO_DEPT[src["key"]]]]
            if a["unit_role"] is None and src["key"] in CO_UNIT_ROLE: sets["unit_role"] = CO_UNIT_ROLE[src["key"]]
            if sets:
                q(f"UPDATE og_agents SET {', '.join(k + '=?' for k in sets)}, updated=? WHERE user_id=? AND key=?", [*sets.values(), now, uid, a["key"]])
            # an unplaced agent whose plain place exists now (e.g. Security & Compliance for the Security Reviewer), if nobody moved it by hand
            if not a["unit_id"] and a["status"] == "active":
                touched = q("SELECT 1 FROM og_lines WHERE user_id=? AND agent_key=? AND by!='system'", (uid, a["key"]), one=True)
                s = {"system": "company", "src": {**src, "key": src["key"]}}
                place = None if touched else self._place(uid, s)
                if place:
                    q("UPDATE og_agents SET unit_id=?, updated=? WHERE user_id=? AND key=?", (place, now, uid, a["key"]))
                    try: self._set_line(uid, a["key"], self._auto_manager(uid, a["key"], place), "system", "placed in its department")
                    except HTTPException: pass
        # executives sit in Executive staff
        if ex:
            for a in q("SELECT key FROM og_agents WHERE user_id=? AND COALESCE(portfolio,'')!='' AND unit_id IS NULL AND status='active'", (uid,)):
                q("UPDATE og_agents SET unit_id=?, updated=? WHERE user_id=? AND key=?", (ex["id"], now, uid, a["key"]))
                try: self._set_line(uid, a["key"], self._auto_manager(uid, a["key"], ex["id"]), "system", "joined Executive staff")
                except HTTPException: pass
        # each department's sponsor: the executive holding its portfolio (unless you picked someone, or cleared it: '')
        holders = {r["portfolio"]: r["key"] for r in q("SELECT key, portfolio FROM og_agents WHERE user_id=? AND COALESCE(portfolio,'')!='' AND status='active'", (uid,))}
        for u in q("SELECT id, link FROM og_units WHERE user_id=? AND kind='department' AND status='active' AND sponsor_key IS NULL", (uid,)):
            k = holders.get(SPONSOR_BY_LINK.get(u["link"] or ""))
            if k: q("UPDATE og_units SET sponsor_key=?, updated=? WHERE id=?", (k, now, u["id"]))

    # ---------- the view ----------
    def _tokens_day(self, uid, keys):
        if not keys or not self._has("ac_runs"): return {}
        marks = ",".join("?" * len(keys))
        return {r["agent_key"]: r["n"] or 0 for r in self.db.q(f"""SELECT agent_key, SUM(tokens) n FROM ac_runs WHERE owner_id=? AND started>=?
                                                                    AND agent_key IN ({marks}) GROUP BY agent_key""", [uid, time.time() - DAY] + keys)}

    def _cap(self, uid):
        """Your daily token limit over every agent system (the agent core's), and what was spent today."""
        if not self._has("ac_budget"): return None, None
        r = self.db.q("SELECT daily_tokens FROM ac_budget WHERE owner_id=?", (uid,), one=True)
        cap = r["daily_tokens"] if r and r["daily_tokens"] else None
        today = None
        if self._has("ac_runs"):
            from datetime import date
            today = self.db.q("SELECT COALESCE(SUM(tokens),0) n FROM ac_runs WHERE owner_id=? AND started>=?", (uid, time.mktime(date.today().timetuple())), one=True)["n"]
        return cap, today

    def _team_budgets(self, uid):
        """Each open team's own daily budget (its governor enforces it), by comp id."""
        if "budget" not in self._cols("mw_comps"): return {}
        return {w["id"]: (w["budget"] if w["budget"] is not None else TEAM_BUDGET) for w in
                self.db.q("""SELECT w.id, w.budget FROM mw_comps w JOIN mh_campaigns c ON c.id=w.campaign_id WHERE c.user_id=? AND COALESCE(w.status,'active')!='closed'""", (uid,))}

    def _team_env(self, uid, comps):
        """Per Competition team, its operational environment: goal, knowledge, files, experiments, sandbox runs (all read through)."""
        out, q = {c: {} for c in comps}, self.db.q
        if not comps: return out
        marks = ",".join("?" * len(comps))
        week = time.time() - 7 * DAY
        if "goal" in self._cols("mw_comps"):
            for r in q(f"SELECT id, goal, ends FROM mw_comps WHERE id IN ({marks})", comps): out[r["id"]].update(goal=_clip(r["goal"], 300), ends=r["ends"])
        for table, key, extra in (("mw_notes", "notes", ""), ("mw_files", "files", ""), ("mk_items", "lessons", " AND COALESCE(lesson,'')!=''"),
                                  ("mw_sbx", "sandbox_week", f" AND started>={week}")):
            if self._has(table) and "comp_id" in self._cols(table):
                for r in q(f"SELECT comp_id, COUNT(*) n FROM {table} WHERE comp_id IN ({marks}){extra} GROUP BY comp_id", comps): out[r["comp_id"]][key] = r["n"]
        if self._has("mb_experiments") and self._has("mb_flows"):
            for r in q(f"""SELECT f.comp_id, COUNT(*) n, SUM(e.decision='adopt') adopted FROM mb_experiments e JOIN mb_flows f ON f.id=e.flow_id
                           WHERE f.comp_id IN ({marks}) GROUP BY f.comp_id""", comps):
                out[r["comp_id"]].update(experiments=r["n"], adopted=r["adopted"] or 0)
        return out

    def _subtree(self, units, uid_):
        """A unit and every unit below it (ids), from the view's units."""
        out, todo = set(), [uid_]
        while todo:
            u = todo.pop()
            if u in out: continue
            out.add(u)
            todo.extend(x["id"] for x in units if x["parent_id"] == u)
        return out

    def _hq_view(self, uid, out):
        q = self.db.q
        units, agents = out["units"], out["agents"]
        U = {u["id"]: u for u in units}
        A = {a["key"]: a for a in agents}
        raw = {r["key"]: r for r in q("SELECT key, title, portfolio, dept_id, unit_role, created FROM og_agents WHERE user_id=?", (uid,))}
        urow = {r["id"]: r for r in q("SELECT id, sponsor_key FROM og_units WHERE user_id=? AND status='active'", (uid,))}
        day = self._tokens_day(uid, list(A))
        team_budget = self._team_budgets(uid)
        comps = [int(u["link"].split(":", 1)[1]) for u in units if (u["link"] or "").startswith("mw_comp:")]
        env = self._team_env(uid, comps)
        done = {r["agent_key"]: r["n"] for r in q("SELECT agent_key, COUNT(*) n FROM og_assign WHERE user_id=? AND status='released' GROUP BY agent_key", (uid,))}
        mdone = {r["manager_key"]: r["n"] for r in q("SELECT manager_key, COUNT(*) n FROM og_missions WHERE user_id=? AND status='done' GROUP BY manager_key", (uid,))}
        for a in agents:
            r = raw.get(a["key"], {})
            a["portfolio"] = r.get("portfolio") or None
            if a["portfolio"] and not r.get("title"): a["title"] = PORTFOLIOS[a["portfolio"]]["title"]
            home = U.get(a["unit_id"])
            a["dept_id"] = a["unit_id"] if home and home["kind"] == "department" and home.get("link") != "exec" else (r.get("dept_id") if r.get("dept_id") in U else None)
            a["unit_role"] = r.get("unit_role") or None
            if a["rank"] == "division_manager" and not a["unit_role"]: a["unit_role"] = "General Manager"
            a["tier"] = RANK_TIER.get(a["rank"], "agent")
            a["assignments"] = []
            a["tokens_day"] = day.get(a["key"], 0)
            a["experience"] = {"since": r.get("created"), "assignments_done": done.get(a["key"], 0), "missions_led": mdone.get(a["key"], 0),
                               "runs_ok": ((a.get("perf") or {}).get("detail") or {}).get("runs_ok")}
        for r in q("SELECT * FROM og_assign WHERE user_id=? AND status='active' AND mission_id IS NULL AND unit_id IS NOT NULL ORDER BY id", (uid,)):
            a = A.get(r["agent_key"])
            if not a or r["unit_id"] not in U: continue
            a["assignments"].append({"id": r["id"], "unit_id": r["unit_id"], "role": r["role"], "duty": r["duty"], "scope": r["scope"], "since": r["since"], "by": r["by"]})
            a["load"] += 1
        for u in units:
            u["sponsor_key"] = (urow.get(u["id"]) or {}).get("sponsor_key") or None
            d = DEPT_BY_LINK.get(u["link"] or "")
            u["dept"] = d[0] if d else ("strategy" if u["link"] == "wf_team:strategy" else None)
            u["squads"] = [x["id"] for x in units if x["parent_id"] == u["id"] and x["kind"] == "squad"]
            u["loaned_in"] = [{"key": a["key"], "role": s["role"], "scope": s["scope"]} for a in agents for s in a["assignments"] if s["unit_id"] == u["id"]]
            u["affiliated"] = sum(1 for a in agents if a["dept_id"] == u["id"] and a["unit_id"] != u["id"]) if u["kind"] == "department" else 0
            comp = int(u["link"].split(":", 1)[1]) if (u["link"] or "").startswith("mw_comp:") else None
            u["allocation"] = team_budget.get(comp) if comp else u["budget"]
            u["allocation_source"] = "team" if comp else ("unit" if u["budget"] is not None else None)
            if comp and u.get("team") is not None: u["team"].update(env.get(comp, {}))
        for u in units:  # spend over the subtree: its people and its units' people, last 24 hours
            ids = self._subtree(units, u["id"])
            u["spent_day"] = sum(a["tokens_day"] for a in agents if a["unit_id"] in ids)
            kids = [x for x in units if x["parent_id"] == u["id"] and x["allocation"] is not None]
            u["allocated_below"] = sum(x["allocation"] for x in kids)
        mu = {m["id"]: m["unit_id"] for m in out["missions"]}
        for a in agents:
            a["scope"] = sorted(self._scope_calc(a["key"], a["unit_id"], units, [s["unit_id"] for s in a["assignments"]],
                                                 [mu.get(m["id"]) for m in a["missions"]], out["org"]["ceo"]))
        cap, today = self._cap(uid)
        top = sum(u["allocation"] or 0 for u in units if not u["parent_id"])
        out["budget"] = {"cap": cap, "today": today, "allocated": top}
        issues = out["issues"]
        for u in units:
            if u["allocation"] is not None and u["allocated_below"] > u["allocation"]:
                issues.append({"level": "warn", "kind": "over_allocated", "unit": u["id"], "keys": [],
                               "title": f"{u['name']}'s units get more than it has",
                               "detail": f"Its units are allocated {_tok(u['allocated_below'])} tokens a day of its {_tok(u['allocation'])}. Raise its allocation or lower theirs (a team's budget is set on its page)."})
            if u["allocation"] and u["spent_day"] > u["allocation"]:
                issues.append({"level": "warn", "kind": "over_budget", "unit": u["id"], "keys": [],
                               "title": f"{u['name']} spent more than its allocation", "detail": f"{_tok(u['spent_day'])} tokens in the last 24 hours of {_tok(u['allocation'])} a day."})
        if cap and top > cap:
            issues.append({"level": "warn", "kind": "over_cap", "keys": [], "title": "Allocations exceed your daily limit",
                           "detail": f"The divisions and departments are allocated {_tok(top)} tokens a day; your limit is {_tok(cap)} (Agent Operations → Budget)."})
        held = {a["portfolio"]: a["key"] for a in agents if a["portfolio"]}
        out["portfolios"] = [{"key": k, **v, "holder": held.get(k), "sponsors": [u["id"] for u in units if u["sponsor_key"] and u["sponsor_key"] == held.get(k)]}
                             for k, v in PORTFOLIOS.items()]
        tier_n = {}
        for a in agents: tier_n[a["tier"]] = tier_n.get(a["tier"], 0) + 1
        out["tiers"] = [{**t, "count": 1 if t["tier"] == "owner" else tier_n.get(t["tier"], 0)} for t in TIERS]
        out["reserved"] = RESERVED
        out["safeguards"] = self._safeguards(out)
        out["departments"] = [{"key": d[0], "name": d[1], "sponsor": d[3]} for d in DEPARTMENTS]
        c = out["counts"]
        c.update(executives=sum(1 for a in agents if a["tier"] == "executive"), squads=sum(1 for u in units if u["kind"] == "squad"),
                 assignments=sum(len(a["assignments"]) for a in agents), issues=sum(1 for i in issues if i["level"] != "info"))
        return out

    def _safeguards(self, out):
        """The governance rules and where each one is enforced, said plainly."""
        pol = out["org"]["policies"]
        return [
            {"rule": "The CEO can't override your reserved decisions", "how": "Strategy, budgets, external commitments, production and destructive operations are locked: they always come to you.", "where": "Enforced here"},
            {"rule": "Managers can't exceed their allocated budget", "how": "A unit's allocation can't pass its parent's, nor the top units' your daily limit. Teams' governors stop new work at their own budget.", "where": "Enforced here and by each team's governor"},
            {"rule": "Competition directors can't read unrelated project data", "how": "Each agent's data scope is its own units and assignments; a team's agents work in that team's own sandbox and files.", "where": "Enforced by the team sandboxes; scope shown here"},
            {"rule": "Shared specialists get scoped permissions", "how": "An assignment carries its own authority level, never above the agent's own.", "where": "Enforced here"},
            {"rule": "External commitments and production deploys need you", "how": "Tasks marked with a locked action wait for your approval.", "where": "Enforced here"},
            {"rule": "Agents recommend, they can't grant themselves authority", "how": "A proposal that would raise, promote or assign its own author is refused; every request applies once, after your decision.", "where": "Enforced here"},
            {"rule": "Specialist requests", "how": "Waits for your approval" if pol.get("assign") != "direct" else "Applied at once (your policy)", "where": "Your policy (Governance → Policies)"},
        ]

    # ---------- data scope ----------
    def _scope_calc(self, key, home, units, assigned, missions, ceo):
        """The units whose data an agent may read: what it manages or sponsors (and below), its home, its team's environment (a
        squad's whole team), its assignments (and below), its missions' units; the CEO all. One rule for the view and /access."""
        if key == ceo: return {u["id"] for u in units}
        U = {u["id"]: u for u in units}
        out = set()
        for u in units:
            if u["manager_key"] == key or u.get("sponsor_key") == key: out |= self._subtree(units, u["id"])
        if home in U:
            out.add(home)
            if U[home]["kind"] == "squad" and U[home]["parent_id"] in U: out |= self._subtree(units, U[home]["parent_id"])
        for x in assigned:
            if x in U: out |= self._subtree(units, x)
        out |= {m for m in missions if m in U}
        return out

    def scope_units(self, uid, key):
        q = self.db.q
        units = q("SELECT id, kind, parent_id, manager_key, link, sponsor_key FROM og_units WHERE user_id=? AND status='active'", (uid,))
        a = self._agent(uid, key, need=False)
        if not a: return set()
        assigned = [r["unit_id"] for r in q("SELECT unit_id FROM og_assign WHERE user_id=? AND agent_key=? AND status='active' AND unit_id IS NOT NULL", (uid, key))]
        missions = [r["unit_id"] for r in q("""SELECT m.unit_id FROM og_assign a JOIN og_missions m ON m.id=a.mission_id WHERE a.user_id=? AND a.agent_key=?
                                               AND a.status='active' AND m.unit_id IS NOT NULL""", (uid, key))]
        return self._scope_calc(key, a["unit_id"], units, assigned, missions, (self._org(uid) or {}).get("ceo_key"))

    def may_access(self, uid, key, unit_id):
        return unit_id in self.scope_units(uid, key)

    def scoped_level(self, uid, key, unit_id):
        """An agent's execution level inside a unit: its own level, or an assignment's lower scope there."""
        lvl = self.level(uid, key)
        r = self.db.q("SELECT scope FROM og_assign WHERE user_id=? AND agent_key=? AND unit_id=? AND status='active'", (uid, key, unit_id), one=True)
        return min(lvl, r["scope"]) if lvl is not None and r and r["scope"] is not None else lvl

    # ---------- budgets ----------
    def _check_budget(self, uid, unit_id, budget, parent_id):
        """A unit's allocation fits its parent's (with its siblings) and covers its own units; the top units' fit your limit."""
        if budget is None: return
        try: budget = int(budget)
        except (TypeError, ValueError): raise HTTPException(400, "A budget is a number of tokens a day.")
        if budget < 0 or budget > 2_000_000_000: raise HTTPException(400, "A budget is 0 to 2 billion tokens a day.")
        q = self.db.q
        teams = self._team_budgets(uid)
        def alloc(u):
            if (u["link"] or "").startswith("mw_comp:"): return teams.get(int(u["link"].split(":", 1)[1]))
            return u["budget"]
        sibs = q("SELECT id, link, budget FROM og_units WHERE user_id=? AND status='active' AND COALESCE(parent_id,0)=COALESCE(?,0) AND id!=COALESCE(?,0)",
                 (uid, parent_id, unit_id))
        others = sum(alloc(s) or 0 for s in sibs)
        if parent_id:
            p = q("SELECT id, name, link, budget FROM og_units WHERE id=?", (parent_id,), one=True)
            pa = alloc(p) if p else None
            if pa is not None and others + budget > pa:
                raise HTTPException(409, f"{p['name']} has {_tok(pa)} tokens a day and its other units already get {_tok(others)}: this unit can have {_tok(max(0, pa - others))} at most.")
        else:
            cap, _ = self._cap(uid)
            if cap and others + budget > cap:
                raise HTTPException(409, f"Your daily limit is {_tok(cap)} tokens and the other top units already get {_tok(others)}: this unit can have {_tok(max(0, cap - others))} at most.")
        if unit_id:
            below = sum(alloc(k) or 0 for k in q("SELECT id, link, budget FROM og_units WHERE user_id=? AND status='active' AND parent_id=?", (uid, unit_id)))
            if budget < below:
                raise HTTPException(409, f"Its own units already get {_tok(below)} tokens a day: lower theirs first.")

    def _op_budget(self, uid, p, actor):
        u = self._unit(uid, p.get("unit_id"))
        if (u["link"] or "").startswith("mw_comp:"):
            raise HTTPException(400, "A Competition team's budget is set on its own page (its governor enforces it).")
        b = p.get("budget")
        b = None if b in (None, "") else int(b)
        self._check_budget(uid, u["id"], b, u["parent_id"])
        self.db.q("UPDATE og_units SET budget=?, updated=? WHERE id=?", (b, time.time(), u["id"]))
        return f"{u['name']}: {_tok(b) + ' tokens a day' if b is not None else 'no allocation'}"

    # ---------- executives, sponsors, affiliation ----------
    def _op_portfolio(self, uid, p, actor):
        """An executive's portfolio: one holder each. The holder joins Executive staff; departments the old holder sponsored
        (or nobody did) move to the new one."""
        a = self._agent(uid, p.get("key"))
        port = p.get("portfolio") or ""
        if port and port not in PORTFOLIOS: raise HTTPException(400, "Unknown portfolio.")
        if a["status"] != "active": raise HTTPException(409, "Only an active agent can hold a portfolio.")
        o, q, now = self._org(uid), self.db.q, time.time()
        if port and a["key"] == o["ceo_key"]: raise HTTPException(409, "The CEO coordinates the executives; pick someone else for this portfolio.")
        ex = q("SELECT id FROM og_units WHERE user_id=? AND link='exec' AND status='active'", (uid,), one=True)
        if port and ex and a["unit_id"] != ex["id"]:
            led = q("SELECT name FROM og_units WHERE user_id=? AND status='active' AND manager_key=?", (uid, a["key"]), one=True)
            if led: raise HTTPException(409, f"{a['name']} manages {led['name']}: pick a new manager for it first, then make {a['name']} an executive.")
        prev = q("SELECT key FROM og_agents WHERE user_id=? AND portfolio=? AND key!=?", (uid, port, a["key"]), one=True) if port else None
        if prev: q("UPDATE og_agents SET portfolio='', updated=? WHERE user_id=? AND key=?", (now, uid, prev["key"]))
        old = a.get("portfolio")
        q("UPDATE og_agents SET portfolio=?, updated=? WHERE user_id=? AND key=?", (port, now, uid, a["key"]))
        if port and ex and a["unit_id"] != ex["id"]:
            q("UPDATE og_agents SET unit_id=?, updated=? WHERE user_id=? AND key=?", (ex["id"], now, uid, a["key"]))
            self._set_line(uid, a["key"], self._auto_manager(uid, a["key"], ex["id"]), actor, "joined Executive staff")
        if old and old != port:  # departments it sponsored for its old portfolio go to nobody (you pick, or the next holder)
            q("UPDATE og_units SET sponsor_key=NULL, updated=? WHERE user_id=? AND sponsor_key=? AND kind='department'", (now, uid, a["key"]))
        if port:
            for u in q("SELECT id, link, sponsor_key FROM og_units WHERE user_id=? AND kind='department' AND status='active'", (uid,)):
                if SPONSOR_BY_LINK.get(u["link"] or "") == port and (u["sponsor_key"] in (None, "") or (prev and u["sponsor_key"] == prev["key"])):
                    q("UPDATE og_units SET sponsor_key=?, updated=? WHERE id=?", (a["key"], now, u["id"]))
        return f"{a['name']}: {PORTFOLIOS[port]['title'] if port else 'no portfolio'}" + (f" (taken from {self._agent(uid, prev['key'])['name']})" if prev else "")

    def _op_sponsor(self, uid, p, actor):
        u = self._unit(uid, p.get("unit_id"))
        if u["kind"] != "department" or u["link"] == "exec": raise HTTPException(400, "Only a shared department has an executive sponsor.")
        key = p.get("key") or ""
        if key:
            a = self._agent(uid, key)
            if not a.get("portfolio"): raise HTTPException(409, f"{a['name']} holds no executive portfolio: give them one first (Executive Office).")
        self.db.q("UPDATE og_units SET sponsor_key=?, updated=? WHERE id=?", (key, time.time(), u["id"]))
        return f"{u['name']} sponsored by {self._agent(uid, key)['name'] if key else 'nobody'}"

    def _op_affiliation(self, uid, p, actor):
        """An agent's profession (department) and its role in its unit; its home and manager don't change."""
        a = self._agent(uid, p.get("key"))
        sets, args = [], []
        if "dept_id" in p:
            d = p.get("dept_id")
            if d:
                u = self._unit(uid, d)
                if u["kind"] != "department" or u["link"] == "exec": raise HTTPException(400, "Pick a shared department.")
            sets.append("dept_id=?"); args.append(d or None)
        if "unit_role" in p:
            sets.append("unit_role=?"); args.append(_clip(str(p.get("unit_role") or "").strip(), 80))
        if not sets: return "nothing changed"
        self.db.q(f"UPDATE og_agents SET {', '.join(sets)}, updated=? WHERE user_id=? AND key=?", args + [time.time(), uid, a["key"]])
        return f"{a['name']}'s department and role saved"

    # ---------- unit assignments: one identity, many controlled assignments ----------
    def _op_assign_unit(self, uid, p, actor):
        u = self._unit(uid, p.get("unit_id"))
        a = self._agent(uid, p.get("key"))
        if a["status"] != "active": raise HTTPException(409, f"{a['name']} isn't active.")
        o = self._org(uid)
        if a["key"] == o["ceo_key"]: raise HTTPException(409, "The CEO coordinates every unit already.")
        if a["unit_id"] == u["id"] or u["manager_key"] == a["key"]: raise HTTPException(409, f"{u['name']} is {a['name']}'s home already.")
        q = self.db.q
        if q("SELECT 1 FROM og_assign WHERE user_id=? AND unit_id=? AND agent_key=? AND status='active' AND mission_id IS NULL", (uid, u["id"], a["key"]), one=True):
            raise HTTPException(409, f"{a['name']} is assigned to {u['name']} already.")
        scope = p.get("scope")
        scope = a["autonomy"] if scope in (None, "") else int(scope)
        if not 0 <= scope <= 4: raise HTTPException(400, "Levels are L0 to L4.")
        if scope > a["autonomy"]:
            raise HTTPException(403, f"{a['name']} is L{a['autonomy']}: an assignment can narrow an agent's authority, never raise it.")
        busy = q("SELECT COUNT(*) n FROM og_assign WHERE user_id=? AND agent_key=? AND status='active'", (uid, a["key"]), one=True)["n"]
        if busy >= (a["cap"] or 3) and not p.get("over_cap"):
            raise HTTPException(409, f"{a['name']} carries {busy} assignments, their capacity: release one, or raise the capacity in their profile.")
        q("INSERT INTO og_assign (user_id, mission_id, unit_id, agent_key, role, duty, scope, status, since, by) VALUES (?,NULL,?,?,?,?,?,'active',?,?)",
          (uid, u["id"], a["key"], _clip(p.get("role") or a["title"] or a["role"] or "specialist", 80), _clip(p.get("duty") or "", 300), scope, time.time(), actor))
        return f"{a['name']} assigned to {u['name']} at L{scope}; home and manager unchanged"

    def _op_release_unit(self, uid, p, actor):
        n = len(self.db.q("UPDATE og_assign SET status='released', released=? WHERE user_id=? AND unit_id=? AND agent_key=? AND status='active' AND mission_id IS NULL RETURNING id",
                          (time.time(), uid, p.get("unit_id"), p.get("key"))))
        return "released: back to their home unit only" if n else "wasn't assigned there"

    def specialists(self, me, unit_id, dept_id, skills=None):
        """Who a department could lend to a unit: its people and its affiliated agents elsewhere, by skill match, free capacity and
        performance; never the unit's own people. Deterministic, no model call."""
        v = self.view(me)
        U = {u["id"]: u for u in v["units"]}
        if unit_id not in U: raise HTTPException(404, "No such unit.")
        if dept_id not in U or U[dept_id]["kind"] != "department": raise HTTPException(400, "Pick a shared department.")
        own = self._subtree(v["units"], unit_id)
        need = [s for s in (skills or []) if s]
        out = []
        for a in v["agents"]:
            if a["status"] != "active" or a["key"] == v["org"]["ceo"] or a["unit_id"] in own: continue
            if not (a["unit_id"] == dept_id or a["dept_id"] == dept_id): continue
            if any(s["unit_id"] == unit_id for s in a["assignments"]): continue
            sk = a["skills"]
            match = (sum(min(sk.get(s, 0), 5) for s in need) / (5 * len(need))) if need else 0.5
            free = max(0.0, 1 - a["load"] / max(1, a["cap"]))
            perf = (a["perf"]["score"] / 100) if a.get("perf") and a["perf"].get("score") is not None else 0.6
            why = [f"{s} {sk[s]}/5" for s in need if sk.get(s)] or ["general fit"]
            why.append(f"{a['load']} of {a['cap']} busy")
            out.append({"key": a["key"], "name": a["name"], "title": a["title"], "score": round(100 * (0.55 * match + 0.3 * free + 0.15 * perf), 1),
                        "why": " · ".join(why), "full": a["load"] >= a["cap"], "level": a["autonomy"],
                        "home": U.get(a["unit_id"], {}).get("name")})
        out.sort(key=lambda c: (c["full"], -c["score"]))
        return {"unit": unit_id, "dept": dept_id, "need": need, "candidates": out[:20]}

    # ---------- knowledge & experience (read through) ----------
    def knowledge(self, me):
        self.ensure(me)
        uid, q = me["id"], self.db.q
        out = {"company": None, "teams": [], "lessons": []}
        if self._has("kb_items"):
            by = q("SELECT type, COUNT(*) n FROM kb_items WHERE user_id=? AND COALESCE(status,'kept')='kept' GROUP BY type", (uid,))
            latest = q("SELECT id, type, title, trust, updated FROM kb_items WHERE user_id=? AND COALESCE(status,'kept')='kept' ORDER BY COALESCE(updated, created) DESC LIMIT 8", (uid,))
            out["company"] = {"total": sum(r["n"] for r in by), "by_type": {r["type"] or "note": r["n"] for r in by}, "latest": latest}
        comps = self._comps(uid)
        ids = [w["id"] for w in comps]
        env = self._team_env(uid, ids)
        units = {r["link"]: r["id"] for r in q("SELECT id, link FROM og_units WHERE user_id=? AND status='active' AND link LIKE 'mw_comp:%'", (uid,))}
        for w in comps:
            out["teams"].append({"comp": w["id"], "name": self._comp_label(w), "unit_id": units.get(f"mw_comp:{w['id']}"), **env.get(w["id"], {})})
        if ids and self._has("mk_items"):
            marks = ",".join("?" * len(ids))
            label = {w["id"]: self._comp_label(w) for w in comps}
            for r in q(f"""SELECT id, comp_id, lesson, why, sure, scope, created FROM mk_items WHERE comp_id IN ({marks}) AND COALESCE(lesson,'')!=''
                           ORDER BY id DESC LIMIT 15""", ids):
                out["lessons"].append({"team": label.get(r["comp_id"]), "comp": r["comp_id"], "lesson": _clip(r["lesson"], 300), "why": _clip(r["why"], 300),
                                       "sure": r["sure"], "scope": r["scope"], "ts": r["created"]})
        return out
