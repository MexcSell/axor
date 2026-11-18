"""Organization: one hierarchical + matrix organization over the agent systems you already run (organization.js draws it).

The Company, Workforce and your own agents each keep their agents, runs and pages. This module is the layer above them that
says who belongs where, who manages whom, who works together on what, and what each agent may do. It never changes another
system's tables: it reads them and keeps its own (og_*).

Four concepts, kept apart on purpose:
- Organization (permanent): you (the owner) → the CEO → business divisions (Bittensor, Handshake, …) and shared departments
  (Engineering, Evaluation, Research, Operations, …) → their managers → team leaders → specialists. Every agent has at most
  one home unit and exactly one permanent manager (og_lines; none = it reports to you). A change is validated before it's
  written: no reporting cycle, no unit inside itself, one manager per agent (a partial unique index makes it hard).
- Workforce (temporary): missions (og_missions) with a mission manager and mission assignments (og_assign). Joining a
  mission never touches the permanent reporting line: Lena stays Kenji's report while Gus runs her competition work. Ending
  a mission releases its people. Work an agent carries in its own system (a Company team, a Workforce assignment) is read
  through and shown next to these, never copied.
- Agent registry: one identity per agent, keyed by the agent core's key "<system>:<id>" (company:12, workforce:3, hub:7),
  with a readable id (agent_software_engineer_001). Two agents may share a display name (say, a Company and a Workforce agent both called Ivo):
  they are two identities, and the integrity checks say so. Skills and an org title are the organization's own fields.
- Runtime (Agent HQ's question, "is it working?"): read from the agent core's run ledger (ac_runs): working now, last
  activity, runs, failures and tokens. Nothing is stored here.

Authority. Organizational authority comes from position (a unit's manager manages it). Execution authority is a separate
level per agent, L0 Observe, L1 Recommend, L2 Sandbox, L3 Approved execution, L4 Restricted autonomy, and position never
raises it: making an agent a manager leaves its level as it was. Raising a level to L3 or more needs your approval. Production
deploys, external actions, budget changes and destructive operations always need your approval (locked policies).

Management. Managers delegate tasks down their reporting line (or, inside a mission, the mission manager to the mission's
people); a task needs at least its level of authority from the agent it goes to, and a task at L3 or more waits for your
approval first. A blocked or overdue task escalates to the holder's permanent manager, then up, and finally to you.
Allocation (Atlas's recommendation) and performance (scores and promotion recommendations) are deterministic: no model call,
no tokens. Recommendations are proposals: they become an approval request, and only your decision applies them, once.
"""
import hashlib, json, logging, os, re, threading, time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .organization_hq import HQ
from .task_lifecycle import not_dropped  # D-018: dropped work isn't completed work

log = logging.getLogger("organization")
ENABLED = os.getenv("ORGANIZATION", "1") == "1"
TICK = float(os.getenv("ORGANIZATION_TICK", "300"))
DAY = 86400
REQUEST_DAYS = 7          # an approval request expires after this
WEEK = 7 * DAY
MIN_EVIDENCE = 5          # finished pieces of work before a performance score counts
DEFAULT_CAP = 3           # assignments an agent carries at once unless its system says otherwise

LEVELS = [
    {"level": 0, "name": "Observe", "about": "Observe and analyze; no proposals of its own."},
    {"level": 1, "name": "Recommend", "about": "Recommend actions for someone else to decide."},
    {"level": 2, "name": "Sandbox", "about": "Execute in a sandbox: tests and drafts, nothing outside it."},
    {"level": 3, "name": "Approved execution", "about": "Execute operations you approved, one approval each."},
    {"level": 4, "name": "Restricted autonomy", "about": "Execute on its own within defined limits; sensitive actions still need you."},
]
APPROVAL_FROM = 3         # raising an agent to this level or a task needing it waits for your approval
# actions that always need your approval, whatever an agent's level or position: they can't be turned off
LOCKED = {"production_deploy": "Production deployment", "external_action": "External commitments and sensitive actions (messages, posts, payments)",
          "budget_change": "Budget changes", "destructive": "Destructive operations (deleting data, dissolving work)",
          "strategy": "Company strategy and other decisions you reserve"}
# organization changes: "owner" = proposals wait for your approval; "direct" = your own edits apply at once (yours always do)
ORG_ACTIONS = {"move_agent": "Moving an agent to another unit or manager", "set_manager": "Changing a unit's manager",
               "promote": "Promotions and role changes", "assign": "Mission assignments proposed by Atlas",
               "dissolve": "Dissolving a unit"}
RANKS = {"ceo": "CEO", "executive": "Executive", "division_manager": "Division manager", "department_manager": "Department manager",
         "competition_director": "Competition director", "team_leader": "Team leader", "squad_leader": "Squad leader",
         "specialist": "Specialist", "unplaced": "Not placed yet"}
KINDS = ("division", "department", "team", "squad")  # a squad sits only inside a team (a Competition team's squads)
TASK_STATES = ("awaiting", "open", "blocked", "escalated", "done", "cancelled")

# seeding: Workforce teams become shared departments; Company divisions stay business divisions
WF_DEPARTMENTS = {"engineering": "Engineering", "evaluation": "Evaluation", "research": "Research", "operations": "Operations",
                  "security": "Security", "strategy": "Strategy"}
DEFAULT_DEPARTMENTS = ("engineering", "evaluation", "research", "operations")
DEPT_PURPOSE = {"engineering": "Software, miners and the engineering standard every project uses.",
                "evaluation": "Independent evaluation: scores work against its objective, never its own.",
                "research": "Sources, opportunities, prior work and the numbers behind decisions.",
                "operations": "Reliability, releases and keeping running systems healthy.",
                "security": "Threat models, risk and safe defaults across the organization.",
                "strategy": "Plans, priorities and economics."}
# Company shared specialists whose department is plain from their role; everyone else starts unplaced, for you to place
CO_SHARED = {"code_reviewer": "engineering", "db_specialist": "engineering", "security_reviewer": "security", "evaluator": "evaluation",
             "browser_research": "research", "data_analyst": "research"}
WF_SKILLS = {"engineering": {"python": 4, "architecture": 3, "code_review": 3}, "research": {"research": 4, "data_analysis": 3},
             "evaluation": {"evaluation": 4, "testing": 3, "benchmarking": 3}, "operations": {"reliability": 4, "coordination": 3},
             "security": {"security": 4, "code_review": 2}, "strategy": {"strategy": 4, "finance": 3}, "exec": {"coordination": 5, "strategy": 4}}
WF_ROLE_SKILLS = {"software-engineer": {"python": 5}, "ml-engineer": {"python": 4, "experiments": 4}, "economist": {"finance": 5},
                  "market-researcher": {"subnet_analysis": 4}, "tech-researcher": {"research": 5}, "fact-checker": {"evaluation": 4},
                  "improvement-engineer": {"experiments": 4}, "sre": {"reliability": 5}, "release-manager": {"reliability": 3},
                  "red-teamer": {"security": 5}, "risk-auditor": {"security": 4}, "planner": {"project_management": 4}}


def _j(s, d=None):
    try: return json.loads(s) if s else d
    except (TypeError, ValueError): return d


def _clip(s, n): s = str(s or ""); return s if len(s) <= n else s[:n - 1] + "…"


def _slug(s): return re.sub(r"[^a-z0-9]+", "_", str(s or "agent").lower()).strip("_")[:32] or "agent"


def _sha(obj): return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


class OrgError(HTTPException):
    def __init__(self, msg, code=409): super().__init__(code, msg)


class Organization(HQ):
    def __init__(self, db, hub=None):
        self.db, self.hub = db, hub
        self.lock = threading.RLock()
        q = db.q
        q("""CREATE TABLE IF NOT EXISTS og_org (user_id INTEGER PRIMARY KEY, name TEXT, owner_name TEXT, owner_title TEXT, ceo_key TEXT,
             policies TEXT, created REAL, updated REAL)""")
        q("""CREATE TABLE IF NOT EXISTS og_units (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, kind TEXT, name TEXT, purpose TEXT,
             parent_id INTEGER, manager_key TEXT, link TEXT, budget INTEGER, status TEXT DEFAULT 'active', created REAL, updated REAL)""")
        q("CREATE INDEX IF NOT EXISTS og_units_u ON og_units (user_id, status)")
        q("UPDATE og_units SET purpose=REPLACE(purpose, 'Mining HQ, subnet and competition teams', 'My subnets and their competition teams') WHERE purpose LIKE '%Mining HQ%'")
        q("""CREATE TABLE IF NOT EXISTS og_agents (user_id INTEGER, key TEXT, ident TEXT, system TEXT, name TEXT, role TEXT, title TEXT,
             unit_id INTEGER, autonomy INTEGER DEFAULT 1, cap INTEGER, skills TEXT, status TEXT, src_status TEXT, created REAL, updated REAL,
             PRIMARY KEY (user_id, key), UNIQUE (user_id, ident))""")
        # one permanent manager per agent: history kept, the current line is the one not ended
        q("""CREATE TABLE IF NOT EXISTS og_lines (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, agent_key TEXT, manager_key TEXT,
             since REAL, ended REAL, by TEXT, reason TEXT)""")
        q("CREATE UNIQUE INDEX IF NOT EXISTS og_lines_one ON og_lines (user_id, agent_key) WHERE ended IS NULL")
        q("""CREATE TABLE IF NOT EXISTS og_missions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, objective TEXT,
             unit_id INTEGER, manager_key TEXT, skills TEXT, link TEXT, status TEXT DEFAULT 'active', due REAL, created REAL, ended REAL)""")
        q("""CREATE TABLE IF NOT EXISTS og_assign (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, mission_id INTEGER, agent_key TEXT,
             role TEXT, duty TEXT, status TEXT DEFAULT 'active', since REAL, released REAL, by TEXT)""")
        q("CREATE UNIQUE INDEX IF NOT EXISTS og_assign_one ON og_assign (mission_id, agent_key) WHERE status='active'")
        q("""CREATE TABLE IF NOT EXISTS og_tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, mission_id INTEGER, title TEXT,
             detail TEXT, level INTEGER DEFAULT 1, sensitive TEXT, from_key TEXT, to_key TEXT, holder_key TEXT, status TEXT, due REAL,
             history TEXT, created REAL, updated REAL)""")
        q("""CREATE TABLE IF NOT EXISTS og_requests (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, kind TEXT, title TEXT, why TEXT,
             payload TEXT, sha TEXT, by TEXT, status TEXT DEFAULT 'pending', created REAL, expires REAL, decided REAL, decided_by TEXT,
             note TEXT, result TEXT)""")
        q("""CREATE TABLE IF NOT EXISTS og_perf (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, agent_key TEXT, ts REAL, evidence INTEGER,
             success REAL, quality REAL, reliability REAL, score REAL, detail TEXT)""")
        q("CREATE INDEX IF NOT EXISTS og_perf_a ON og_perf (user_id, agent_key, ts)")
        q("""CREATE TABLE IF NOT EXISTS og_audit (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, ts REAL, actor TEXT, action TEXT,
             target TEXT, detail TEXT)""")
        self._hq_schema()  # Organization HQ's columns (portfolio, department, sponsor, unit assignments)
        self.stopped = threading.Event()

    # ---------- small helpers ----------
    def _has(self, t): return bool(self.db.q("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,), one=True))

    def _audit(self, uid, actor, action, target, detail=""):
        self.db.q("INSERT INTO og_audit (user_id, ts, actor, action, target, detail) VALUES (?,?,?,?,?,?)",
                  (uid, time.time(), actor, action, _clip(target, 200), _clip(detail, 600)))

    def _org(self, uid):
        o = self.db.q("SELECT * FROM og_org WHERE user_id=?", (uid,), one=True)
        if o: o["policies"] = {**{k: "owner" for k in ORG_ACTIONS}, **(_j(o["policies"], {}) or {})}
        return o

    def _agent(self, uid, key, need=True):
        a = self.db.q("SELECT * FROM og_agents WHERE user_id=? AND key=?", (uid, key), one=True)
        if not a and need: raise OrgError("No such agent in your organization.", 404)
        return a

    def _unit(self, uid, unit_id, need=True):
        u = self.db.q("SELECT * FROM og_units WHERE user_id=? AND id=? AND status='active'", (uid, unit_id), one=True)
        if not u and need: raise OrgError("No such unit in your organization.", 404)
        return u

    def manager_of(self, uid, key):
        r = self.db.q("SELECT manager_key FROM og_lines WHERE user_id=? AND agent_key=? AND ended IS NULL", (uid, key), one=True)
        return r["manager_key"] if r else None

    def chain(self, uid, key, limit=64):
        """The permanent managers above an agent, nearest first (you, the owner, are above the last one)."""
        out, seen, cur = [], {key}, key
        for _ in range(limit):
            m = self.manager_of(uid, cur)
            if not m or m in seen: break
            out.append(m); seen.add(m); cur = m
        return out

    def _set_line(self, uid, key, manager, by, reason=""):
        """The one place a permanent reporting line changes. Refuses a cycle (the new manager may not report, at any depth, to the agent)."""
        if manager == key: raise OrgError("An agent can't manage itself.")
        if manager:
            m = self._agent(uid, manager, need=False)
            if not m or m["status"] in ("archived", "gone"): raise OrgError("That manager isn't an active agent of your organization.")
            if key in self.chain(uid, manager): raise OrgError(f"That would make a reporting cycle: {m['name']} already reports to this agent.")
        if self.manager_of(uid, key) == manager and self.db.q("SELECT 1 FROM og_lines WHERE user_id=? AND agent_key=? AND ended IS NULL", (uid, key), one=True):
            return False
        now = time.time()
        self.db.q("UPDATE og_lines SET ended=? WHERE user_id=? AND agent_key=? AND ended IS NULL", (now, uid, key))
        self.db.q("INSERT INTO og_lines (user_id, agent_key, manager_key, since, by, reason) VALUES (?,?,?,?,?,?)", (uid, key, manager, now, by, _clip(reason, 300)))
        return True

    def _unit_chain(self, uid, unit_id, limit=32):
        out, cur = [], unit_id
        for _ in range(limit):
            u = self.db.q("SELECT id, parent_id FROM og_units WHERE user_id=? AND id=?", (uid, cur), one=True)
            if not u: break
            out.append(u["id"])
            if not u["parent_id"] or u["parent_id"] in out: break
            cur = u["parent_id"]
        return out

    def _auto_manager(self, uid, key, unit_id):
        """Who an agent reports to by its place: its unit's manager; a unit's own manager reports to the parent unit's manager,
        a top unit's manager to the CEO; the CEO and unplaced agents report to you (None)."""
        o = self._org(uid)
        ceo = o and o["ceo_key"]
        if key == ceo: return None
        if not unit_id: return None
        u = self._unit(uid, unit_id, need=False)
        if not u: return None
        if u["manager_key"] and u["manager_key"] != key: return u["manager_key"]
        return self._above(uid, u, key)

    def _above(self, uid, u, key):
        """The manager above unit u for its own manager `key`: the nearest parent unit's manager, else the CEO, else you (None)."""
        p, seen = (self._unit(uid, u["parent_id"], need=False) if u["parent_id"] else None), {u["id"]}
        while p and p["id"] not in seen:
            seen.add(p["id"])
            if p["manager_key"] and p["manager_key"] != key: return p["manager_key"]
            p = self._unit(uid, p["parent_id"], need=False) if p["parent_id"] else None
        o = self._org(uid)
        ceo = o and o["ceo_key"]
        return ceo if ceo and ceo != key else None

    # ---------- sources: the agents other systems keep ----------
    def _sources(self, uid):
        """Every agent this user owns in the systems the organization covers: (key, system, name, role, status, extra)."""
        q, out = self.db.q, []
        if self._has("co_agents") and self._has("co_company"):
            c = q("SELECT id, name FROM co_company WHERE user_id=?", (uid,), one=True)
            if c:
                divs = {d["id"]: d for d in q("SELECT id, key, name FROM co_divisions WHERE company_id=?", (c["id"],))} if self._has("co_divisions") else {}
                for a in q("SELECT id, key, name, title, category, division_id, skills, max_load, lead, evaluator, permissions, status FROM co_agents WHERE company_id=?", (c["id"],)):
                    out.append({"key": f"company:{a['id']}", "system": "company", "name": a["name"], "role": a["title"] or a["category"] or "",
                                "status": a["status"], "src": a, "division": divs.get(a["division_id"])})
        if self._has("wf_agents"):
            for a in q("SELECT id, key, team, level, role, name, title, tools, status FROM wf_agents WHERE user_id=?", (uid,)):
                out.append({"key": f"workforce:{a['id']}", "system": "workforce", "name": a["name"], "role": a["title"] or a["role"] or "", "status": a["status"], "src": a})
        if self._has("custom_agents"):
            for a in q("SELECT id, name, role, skills, status FROM custom_agents WHERE owner_id=?", (uid,)):
                out.append({"key": f"hub:{a['id']}", "system": "hub", "name": a["name"], "role": a["role"] or "Agent", "status": a["status"], "src": a})
        for a in self._team_agents(uid):  # Competition teams: each team's Director (its lead) and its agents, in their team's unit
            out.append({"key": f"teams:{a['id']}", "system": "teams", "name": a["name"], "role": "Director" if a["lead"] else (a["title"] or a["role"] or "Agent"),
                        "status": "active" if a["active"] else "off", "src": a})
        return out

    # ---------- Competition teams: a team unit per open team, under the Bittensor division ----------
    def _comps(self, uid):
        """The owner's open Competition teams: id, label, subnet."""
        if not (self._has("mw_comps") and self._has("mh_campaigns")): return []
        return self.db.q("""SELECT w.id, w.number, w.name, c.netuid FROM mw_comps w JOIN mh_campaigns c ON c.id=w.campaign_id
                            WHERE c.user_id=? AND COALESCE(w.status,'active')!='closed' ORDER BY w.id""", (uid,))

    def _team_agents(self, uid):
        if not (self._has("mw_agents") and self._has("mw_comps") and self._has("mh_campaigns")): return []
        sq = ", a.squad, a.head" if "squad" in self._cols("mw_agents") else ""
        return self.db.q(f"""SELECT a.id, a.comp_id, a.name, a.title, a.role, a.lead, a.active{sq} FROM mw_agents a JOIN mw_comps w ON w.id=a.comp_id
                            JOIN mh_campaigns c ON c.id=w.campaign_id WHERE c.user_id=? AND COALESCE(w.status,'active')!='closed'""", (uid,))

    @staticmethod
    def _comp_label(w):
        name = w["name"] or (f"Competition {w['number']}" if w["number"] is not None else f"Team {w['id']}")
        return f"SN{w['netuid']} · {name}"

    def _bittensor_unit(self, uid, now):
        """The unit Competition teams sit in: the Company's Bittensor division, else a Bittensor division of the organization's own."""
        q = self.db.q
        if self._has("co_divisions") and self._has("co_company"):
            d = q("""SELECT d.id FROM co_divisions d JOIN co_company c ON c.id=d.company_id WHERE c.user_id=? AND d.key='bittensor'""", (uid,), one=True)
            if d:
                u = q("SELECT id FROM og_units WHERE user_id=? AND link=? AND status='active'", (uid, f"co_division:{d['id']}"), one=True)
                if u: return u["id"]
        u = q("SELECT id, status FROM og_units WHERE user_id=? AND link='og:bittensor'", (uid,), one=True)
        if u: return u["id"] if u["status"] == "active" else None
        return q("""INSERT INTO og_units (user_id, kind, name, purpose, link, created, updated) VALUES (?,?,?,?,?,?,?) RETURNING id""",
                 (uid, "division", "Bittensor Division", "Miner engineering and competition teams: the subnets you mine (My subnets) and their teams.",
                  "og:bittensor", now, now), one=True)["id"]

    def _ensure_units(self, uid):
        """Before the agents sync: the Executive staff unit, a team unit for each open Competition team (never one you dissolved),
        and closing the units of teams that closed."""
        q, now = self.db.q, time.time()
        if not q("SELECT 1 FROM og_units WHERE user_id=? AND link='exec'", (uid,), one=True):
            q("""INSERT INTO og_units (user_id, kind, name, purpose, link, created, updated) VALUES (?,?,?,?,?,?,?)""",
              (uid, "department", "Executive staff", "The CEO's staff: chief of staff, operations, technology, finance, research and governance.", "exec", now, now))
        comps = self._comps(uid)
        open_links = {f"mw_comp:{w['id']}" for w in comps}
        have = {r["link"] for r in q("SELECT link FROM og_units WHERE user_id=? AND link LIKE 'mw_comp:%'", (uid,))}
        parent = self._bittensor_unit(uid, now) if [w for w in comps if f"mw_comp:{w['id']}" not in have] else None
        for w in comps:
            link = f"mw_comp:{w['id']}"
            if link in have: continue
            q("""INSERT INTO og_units (user_id, kind, name, purpose, parent_id, link, created, updated) VALUES (?,?,?,?,?,?,?,?)""",
              (uid, "team", self._comp_label(w), "A Competition team: its Director leads the squads and sends you one report.", parent, link, now, now))
        for u in q("SELECT id, link FROM og_units WHERE user_id=? AND link LIKE 'mw_comp:%' AND status='closed'", (uid,)):
            if u["link"] in open_links: q("UPDATE og_units SET status='active', updated=? WHERE id=?", (now, u["id"]))  # the team reopened
        for u in q("SELECT id, link FROM og_units WHERE user_id=? AND link LIKE 'mw_comp:%' AND status='active'", (uid,)):
            if u["link"] not in open_links:
                q("UPDATE og_units SET status='closed', updated=? WHERE id=?", (now, u["id"]))
                q("UPDATE og_agents SET unit_id=NULL, updated=? WHERE user_id=? AND unit_id=?", (now, uid, u["id"]))
        self._ensure_late_units(uid)    # divisions and Workforce teams that appeared after the organization was made
        self._ensure_departments(uid)   # the eight shared departments (Organization HQ)
        self._ensure_squad_units(uid)   # each team's squads, inside its unit

    # ---------- systems that arrived after the organization was made ----------
    # _seed reads the Company and Workforce as they are when Organization first opens. Opened before Workforce had made its
    # staff (or before the Company existed), the organization had no CEO, no units for those teams and divisions, and left
    # their agents unplaced for good. These fill only what was never set: never a unit you dissolved, a manager you changed
    # or cleared, or an agent you moved (your changes are in og_audit; the system's own fills aren't).
    def _touched(self, uid, op, needle):
        return bool(self.db.q("SELECT 1 FROM og_audit WHERE user_id=? AND action=? AND (target LIKE ? OR target LIKE ?) LIMIT 1",
                              (uid, op, f"%{needle},%", f"%{needle}}}%"), one=True))

    def _late_leads(self, uid):
        """{unit link: the key of the agent who leads it in its system}: Company division leads, Workforce team leads."""
        out = {}
        for s in self._sources(uid):
            if s["system"] == "company" and s["src"]["division_id"] and s["src"]["lead"]: out.setdefault(f"co_division:{s['src']['division_id']}", s["key"])
            if s["system"] == "workforce" and (s["src"]["team"] or "exec") != "exec" and s["src"]["level"] == "lead": out.setdefault(f"wf_team:{s['src']['team']}", s["key"])
        return out

    def _ensure_late_units(self, uid):
        q, now = self.db.q, time.time()
        have = {r["link"] for r in q("SELECT link FROM og_units WHERE user_id=? AND link IS NOT NULL", (uid,))}  # any status: dissolved stays dissolved
        want = []
        if self._has("co_divisions") and self._has("co_company"):
            c = q("SELECT id FROM co_company WHERE user_id=?", (uid,), one=True)
            for d in (q("SELECT id, name, description FROM co_divisions WHERE company_id=? ORDER BY id", (c["id"],)) if c else []):
                want.append((f"co_division:{d['id']}", "division", d["name"], _clip(d["description"] or "", 300)))
        if self._has("wf_agents"):
            for t in dict.fromkeys(r["team"] for r in q("SELECT team FROM wf_agents WHERE user_id=? AND team IS NOT NULL AND team!='exec' ORDER BY id", (uid,))):
                want.append((f"wf_team:{t}", "department", WF_DEPARTMENTS.get(t, t.capitalize()), DEPT_PURPOSE.get(t, "")))
        want = [w for w in want if w[0] not in have]
        if not want: return
        leads = self._late_leads(uid)
        for link, kind, name, purpose in want:
            q("""INSERT INTO og_units (user_id, kind, name, purpose, manager_key, link, created, updated) VALUES (?,?,?,?,?,?,?,?)""",
              (uid, kind, name, purpose, leads.get(link), link, now, now))
        self._audit(uid, "system", "sync", "units", f"{len(want)} unit(s) for divisions and teams that arrived later: " + ", ".join(w[2] for w in want))

    def _ensure_late_people(self, uid):
        """After the agents sync: the CEO if none was ever set, a lead for the division/team units that never had a manager,
        and the agents left unplaced because their unit didn't exist yet."""
        q, now, o = self.db.q, time.time(), self._org(uid)
        if not o["ceo_key"]:  # a CEO can be changed, never cleared: none means never set
            ceo = q("""SELECT g.key FROM og_agents g JOIN wf_agents w ON g.key='workforce:' || w.id WHERE g.user_id=? AND w.user_id=? AND w.level='ceo'
                       AND g.status='active' ORDER BY w.id LIMIT 1""", (uid, uid), one=True) if self._has("wf_agents") else None
            if ceo:
                self._op_set_ceo(uid, {"key": ceo["key"]}, "system")
                self._audit(uid, "system", "sync", ceo["key"], "the Workforce CEO arrived after the organization was made: CEO")
        leads = self._late_leads(uid)
        for u in q("SELECT id, link FROM og_units WHERE user_id=? AND status='active' AND manager_key IS NULL AND (link LIKE 'co_division:%' OR link LIKE 'wf_team:%')", (uid,)):
            k = leads.get(u["link"])
            if not k or self._touched(uid, "set_manager", f'"unit_id": {u["id"]}'): continue
            a = self._agent(uid, k, need=False)
            if not a or a["status"] != "active": continue
            try: self._op_set_manager(uid, {"unit_id": u["id"], "key": k}, "system")
            except HTTPException as e: log.info("organization: unit %s lead: %s", u["link"], e.detail)
        by_key, ceo = {s["key"]: s for s in self._sources(uid)}, self._org(uid)["ceo_key"]
        for a in q("SELECT key FROM og_agents WHERE user_id=? AND unit_id IS NULL AND status='active' AND key NOT LIKE 'teams:%'", (uid,)):
            s = by_key.get(a["key"])
            if not s or a["key"] == ceo or not (unit := self._place(uid, s)): continue  # most unplaced agents have no default unit: no audit read
            if self._touched(uid, "move_agent", f'"key": "{a["key"]}"'): continue
            q("UPDATE og_agents SET unit_id=?, updated=? WHERE user_id=? AND key=?", (unit, now, uid, a["key"]))
            try: self._set_line(uid, a["key"], self._auto_manager(uid, a["key"], unit), "system", "placed in its unit, which arrived later")
            except HTTPException: pass

    def _ensure_leads(self, uid):
        """After the agents sync: each team unit led by its team's Director (unless you gave it someone else), the Company's
        leadership in Executive staff (only those not placed yet), and the Company's CEO agent titled Chief of Staff: one CEO."""
        q = self.db.q
        leads = {a["comp_id"]: f"teams:{a['id']}" for a in self._team_agents(uid) if a["lead"] and a["active"]}
        for u in q("SELECT id, link, manager_key FROM og_units WHERE user_id=? AND link LIKE 'mw_comp:%' AND status='active'", (uid,)):
            want = leads.get(int(u["link"].split(":", 1)[1]))
            cur = u["manager_key"]
            ours = cur is None or (cur.startswith("teams:") and (self._agent(uid, cur, need=False) or {}).get("unit_id") == u["id"])
            if want and cur != want and ours:
                try: self._op_set_manager(uid, {"unit_id": u["id"], "key": want}, "system")
                except HTTPException as e: log.info("organization: team %s lead: %s", u["link"], e.detail)
        ex = q("SELECT id FROM og_units WHERE user_id=? AND link='exec' AND status='active'", (uid,), one=True)
        if ex and self._has("co_agents") and self._has("co_company"):
            for r in q("""SELECT a.id, a.key FROM co_agents a JOIN co_company c ON c.id=a.company_id WHERE c.user_id=? AND a.category='leadership'""", (uid,)):
                k = f"company:{r['id']}"
                a = self._agent(uid, k, need=False)
                if not a or a["status"] in ("archived", "gone"): continue
                if r["key"] == "ceo" and not a["title"]:
                    q("UPDATE og_agents SET title='Chief of Staff', updated=? WHERE user_id=? AND key=?", (time.time(), uid, k))
                if not a["unit_id"]:
                    q("UPDATE og_agents SET unit_id=?, updated=? WHERE user_id=? AND key=?", (ex["id"], time.time(), uid, k))
                    try: self._set_line(uid, k, self._auto_manager(uid, k, ex["id"]), "system", "joined Executive staff")
                    except HTTPException: pass

    @staticmethod
    def _seed_skills(s):
        src = s["src"]
        if s["system"] == "company":
            return {k: int(v) for k, v in (_j(src["skills"], {}) or {}).items() if isinstance(v, (int, float))}
        if s["system"] == "workforce":
            k = {**WF_SKILLS.get(src["team"] or "exec", {})}
            k.update(WF_ROLE_SKILLS.get(src["key"], {}))
            if src["level"] == "lead": k["coordination"] = max(k.get("coordination", 0), 4)
            return k
        return {str(x): 3 for x in (_j(src.get("skills"), []) or [])[:8] if isinstance(x, str)}

    @staticmethod
    def _seed_level(s):
        if s["system"] == "teams": return 2  # they work in sandbox pods: drafts and tests, nothing outside
        if s["system"] == "company":
            return 2 if (_j(s["src"]["permissions"], {}) or {}).get("execute") else 1
        return 1

    def _ident(self, uid, role):
        base = f"agent_{_slug(role)}"
        used = {r["ident"] for r in self.db.q("SELECT ident FROM og_agents WHERE user_id=? AND ident LIKE ?", (uid, base + "_%"))}
        i = 1
        while f"{base}_{i:03d}" in used: i += 1
        return f"{base}_{i:03d}"

    def ensure(self, me):
        """The organization, made on first use from the systems' agents (additive: only og_* rows are written), then kept in step."""
        uid = me["id"]
        with self.lock:
            o = self._org(uid)
            first = not o
            if first: self._seed(me)
            self._sync(me, first)
            return self._org(uid)

    def _seed(self, me):
        uid, now, q = me["id"], time.time(), self.db.q
        sources = self._sources(uid)
        cname = None
        if self._has("co_company"):
            c = q("SELECT name FROM co_company WHERE user_id=?", (uid,), one=True)
            cname = c and c["name"]
        ceo = next((s["key"] for s in sources if s["system"] == "workforce" and s["src"]["level"] == "ceo" and s["status"] != "archived"), None)
        owner = me.get("display_name") or me.get("name") or me["username"]
        q("INSERT INTO og_org (user_id, name, owner_name, owner_title, ceo_key, policies, created, updated) VALUES (?,?,?,?,?,?,?,?)",
          (uid, cname or f"{owner}'s organization", owner, "Owner · Chairman", ceo, "{}", now, now))
        units = {}
        # business divisions: the Company's divisions, led by each division's lead agent
        if self._has("co_divisions") and self._has("co_company"):
            c = q("SELECT id FROM co_company WHERE user_id=?", (uid,), one=True)
            for d in (q("SELECT id, key, name, description, status FROM co_divisions WHERE company_id=? ORDER BY id", (c["id"],)) if c else []):
                lead = next((s["key"] for s in sources if s["system"] == "company" and s["src"]["division_id"] == d["id"] and s["src"]["lead"]), None)
                units[f"co_division:{d['id']}"] = q("""INSERT INTO og_units (user_id, kind, name, purpose, manager_key, link, created, updated)
                                                      VALUES (?,?,?,?,?,?,?,?) RETURNING id""",
                                                    (uid, "division", d["name"], _clip(d["description"] or "", 300), lead, f"co_division:{d['id']}", now, now), one=True)["id"]
        # shared departments: Workforce's teams (and the four the organization always has)
        teams = []
        for s in sources:
            if s["system"] == "workforce" and (s["src"]["team"] or "exec") != "exec" and s["src"]["team"] not in teams: teams.append(s["src"]["team"])
        for t in list(DEFAULT_DEPARTMENTS) + [t for t in teams if t not in DEFAULT_DEPARTMENTS]:
            lead = next((s["key"] for s in sources if s["system"] == "workforce" and s["src"]["team"] == t and s["src"]["level"] == "lead"), None)
            units[f"wf_team:{t}"] = q("""INSERT INTO og_units (user_id, kind, name, purpose, manager_key, link, created, updated)
                                         VALUES (?,?,?,?,?,?,?,?) RETURNING id""",
                                      (uid, "department", WF_DEPARTMENTS.get(t, t.capitalize()), DEPT_PURPOSE.get(t, ""), lead, f"wf_team:{t}", now, now), one=True)["id"]
        self._audit(uid, "system", "seed", "organization", f"{len(units)} units from Company divisions and Workforce teams")

    def _place(self, uid, s):
        """Where a source agent starts: Company division agents in their division, Workforce staff in their team's department,
        the shared specialists whose department is plain; the rest unplaced (you place them)."""
        src, link = s["src"], None
        if s["system"] == "company":
            if src["division_id"]: link = f"co_division:{src['division_id']}"
            elif src["key"] in CO_SHARED: link = f"wf_team:{CO_SHARED[src['key']]}"
            elif src["category"] == "leadership": link = "exec"
        elif s["system"] == "teams":
            link = f"mw_comp:{src['comp_id']}"
            if src.get("squad") and not src["lead"]:  # into its squad when the squad's unit is there
                sq = self.db.q("SELECT id FROM og_units WHERE user_id=? AND link=? AND status='active'", (uid, f"mw_squad:{src['comp_id']}:{src['squad']}"), one=True)
                if sq: return sq["id"]
        elif s["system"] == "workforce" and (src["team"] or "exec") != "exec":
            link = f"wf_team:{src['team']}"
        if not link: return None
        u = self.db.q("SELECT id FROM og_units WHERE user_id=? AND link=? AND status='active'", (uid, link), one=True)
        return u and u["id"]

    def _sync(self, me, first=False):
        uid, now, q = me["id"], time.time(), self.db.q
        self._ensure_units(uid)
        seen, new = set(), []
        for s in self._sources(uid):
            seen.add(s["key"])
            st = "archived" if s["status"] == "archived" else ("paused" if s["status"] in ("paused", "off") else "active")
            a = self._agent(uid, s["key"], need=False)
            if not a:
                if st == "archived": continue
                q("""INSERT INTO og_agents (user_id, key, ident, system, name, role, unit_id, autonomy, cap, skills, status, src_status, created, updated)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (uid, s["key"], self._ident(uid, s["role"] or s["name"]), s["system"], s["name"], s["role"], self._place(uid, s), self._seed_level(s),
                   (s["src"].get("max_load") if s["system"] == "company" else None) or DEFAULT_CAP, json.dumps(self._seed_skills(s)), st, s["status"], now, now))
                new.append(s["key"])
            elif (a["name"], a["role"], a["src_status"]) != (s["name"], s["role"], s["status"]) or (a["status"] == "gone"):
                keep = a["status"] if a["status"] == "paused" and st == "active" and a["src_status"] == s["status"] else st
                q("UPDATE og_agents SET name=?, role=?, src_status=?, status=?, updated=? WHERE user_id=? AND key=?", (s["name"], s["role"], s["status"], keep, now, uid, s["key"]))
        for a in q("SELECT key FROM og_agents WHERE user_id=? AND status!='gone'", (uid,)):
            if a["key"] not in seen: q("UPDATE og_agents SET status='gone', updated=? WHERE user_id=? AND key=?", (now, uid, a["key"]))
        self._ensure_leads(uid)  # before the newcomers' lines: a team's agents then report to its Director, not past it
        self._ensure_late_people(uid)  # CEO, unit leads and placements for systems that arrived after the organization was made
        self._ensure_squad_people(uid)  # squad leads, and the team's agents into their squads
        self._ensure_people(uid)  # portfolios, sponsors, departments and division roles
        for k in new:  # a reporting line for each newcomer, by its place
            if self.manager_of(uid, k) is not None: continue  # placed under its unit's new manager just now
            a = self._agent(uid, k)
            try: self._set_line(uid, k, self._auto_manager(uid, k, a["unit_id"]), "system", "joined the organization")
            except HTTPException: self._set_line(uid, k, None, "system", "joined the organization")
        if new and not first:
            self._audit(uid, "system", "sync", "registry", f"{len(new)} new agent(s) from their systems")

    # ---------- the view ----------
    def view(self, me):
        o = self.ensure(me)
        uid, q, now = me["id"], self.db.q, time.time()
        agents = q("SELECT * FROM og_agents WHERE user_id=? AND status NOT IN ('archived','gone') ORDER BY name", (uid,))
        lines = {r["agent_key"]: r for r in q("SELECT agent_key, manager_key, since FROM og_lines WHERE user_id=? AND ended IS NULL", (uid,))}
        units = q("SELECT * FROM og_units WHERE user_id=? AND status='active' ORDER BY CASE kind WHEN 'division' THEN 0 WHEN 'department' THEN 1 ELSE 2 END, id", (uid,))
        missions = q("SELECT * FROM og_missions WHERE user_id=? AND status IN ('planning','active') ORDER BY id DESC", (uid,))
        past = q("SELECT id, name, status, ended, manager_key FROM og_missions WHERE user_id=? AND status IN ('done','cancelled') ORDER BY ended DESC LIMIT 20", (uid,))
        assign = q("""SELECT a.*, m.name mission, m.manager_key mission_manager FROM og_assign a JOIN og_missions m ON m.id=a.mission_id
                      WHERE a.user_id=? AND a.status='active'""", (uid,))
        engine = self._engine_work(uid)
        runtime = self._runtime(uid, [a["key"] for a in agents])
        perf = self._perf_latest(uid)
        managed = {u["manager_key"]: u for u in units if u["manager_key"]}
        names = {a["key"]: a["name"] for a in q("SELECT key, name FROM og_agents WHERE user_id=?", (uid,))}
        out_agents = []
        for a in agents:
            k = a["key"]
            mine = [x for x in assign if x["agent_key"] == k]
            eng = engine.get(k, [])
            out_agents.append({
                "key": k, "ident": a["ident"], "system": a["system"], "name": a["name"], "role": a["role"], "title": a["title"] or a["role"],
                "unit_id": a["unit_id"], "manager": lines.get(k, {}).get("manager_key"), "since": lines.get(k, {}).get("since"),
                "rank": self._rank(o, a, managed, units), "autonomy": a["autonomy"], "cap": a["cap"] or DEFAULT_CAP, "status": a["status"],
                "skills": _j(a["skills"], {}) or {}, "load": len(mine) + len(eng),
                "missions": [{"id": x["mission_id"], "name": x["mission"], "role": x["role"], "duty": x["duty"], "manager": x["mission_manager"], "since": x["since"]} for x in mine],
                "work": eng, "runtime": runtime.get(k, {}), "perf": perf.get(k)})
        tasks = q("SELECT * FROM og_tasks WHERE user_id=? AND (status NOT IN ('done','cancelled') OR updated>?) ORDER BY id DESC LIMIT 200", (uid, now - 14 * DAY))
        for t in tasks: t["history"] = _j(t["history"], []) or []
        reqs = self._requests(uid)
        units_out, tinfo = [], self._teams_info(uid)
        for u in units:
            members = [a for a in out_agents if a["unit_id"] == u["id"]]
            comp = int(u["link"].split(":", 1)[1]) if (u["link"] or "").startswith("mw_comp:") else None
            units_out.append({**{k: u[k] for k in ("id", "kind", "name", "purpose", "parent_id", "manager_key", "link", "budget")},
                              "team": tinfo.get(comp) if comp else None,
                              "headcount": len(members), "busy": sum(1 for a in members if a["load"]),
                              "tokens_week": sum((a["runtime"].get("tokens_week") or 0) for a in members),
                              "missions": sum(1 for m in missions if m["unit_id"] == u["id"]),
                              "score": (lambda xs: round(sum(xs) / len(xs)) if xs else None)([a["perf"]["score"] for a in members if a.get("perf") and a["perf"]["score"] is not None])})
        mout = []
        for m in missions:
            people = [x for x in assign if x["mission_id"] == m["id"]]
            mout.append({**{k: m[k] for k in ("id", "name", "objective", "unit_id", "manager_key", "link", "status", "due", "created")},
                         "skills": _j(m["skills"], []) or [], "people": [{"key": x["agent_key"], "role": x["role"], "duty": x["duty"], "since": x["since"]} for x in people],
                         "tasks": sum(1 for t in tasks if t["mission_id"] == m["id"] and t["status"] not in ("done", "cancelled"))})
        out = {"at": now, "org": {"name": o["name"], "owner": o["owner_name"], "owner_title": o["owner_title"], "ceo": o["ceo_key"], "policies": o["policies"],
                                  "mission_control": self._mission_control(uid)},
               "agents": out_agents, "names": names, "units": units_out, "missions": mout, "past": past, "tasks": tasks, "requests": reqs,
               "levels": LEVELS, "locked": LOCKED, "org_actions": ORG_ACTIONS, "ranks": RANKS, "approval_from": APPROVAL_FROM,
               "links": self._links(uid), "issues": self.integrity(uid, out_agents, units_out)}
        act = [a for a in out_agents if a["status"] == "active"]
        out["counts"] = {"agents": len(out_agents), "active": len(act), "busy": sum(1 for a in act if a["load"]), "working": sum(1 for a in act if a["runtime"].get("running")),
                         "divisions": sum(1 for u in units if u["kind"] == "division"), "departments": sum(1 for u in units if u["kind"] == "department"),
                         "teams": sum(1 for u in units if u["kind"] == "team"), "missions": len(mout),
                         "pending": sum(1 for r in reqs if r["status"] == "pending"),
                         "escalated": sum(1 for t in tasks if t["status"] == "escalated" and not t["holder_key"]),
                         "open_tasks": sum(1 for t in tasks if t["status"] in ("open", "blocked", "escalated", "awaiting")),
                         "overdue": sum(1 for t in tasks if t["status"] in ("open", "blocked") and t["due"] and t["due"] < now),
                         "tokens_week": sum((a["runtime"].get("tokens_week") or 0) for a in out_agents),
                         "failed_week": sum((a["runtime"].get("failed_week") or 0) for a in out_agents),
                         "issues": sum(1 for i in out["issues"] if i["level"] != "info")}
        return self._hq_view(uid, out)  # executives, squads, assignments, budgets, the authority ladder

    def _rank(self, o, a, managed, units):
        if a["key"] == o["ceo_key"]: return "ceo"
        u = managed.get(a["key"])
        if u:
            if u["kind"] == "team" and (u["link"] or "").startswith("mw_comp:"): return "competition_director"
            return {"division": "division_manager", "department": "department_manager", "team": "team_leader", "squad": "squad_leader"}.get(u["kind"], "team_leader")
        if a.get("portfolio") or any(x["id"] == a["unit_id"] and x["link"] == "exec" for x in units): return "executive"
        return "specialist" if a["unit_id"] else "unplaced"

    def _links(self, uid):
        """Where each system's agents live, for the profile's 'Open' buttons; and whether the systems are there at all."""
        return {"company": self._has("co_company") and bool(self.db.q("SELECT 1 FROM co_company WHERE user_id=?", (uid,), one=True)),
                "workforce": self._has("wf_agents") and bool(self.db.q("SELECT 1 FROM wf_agents WHERE user_id=? LIMIT 1", (uid,), one=True)),
                "hub": self._has("custom_agents"), "teams": bool(self._comps(uid))}

    def _engine_work(self, uid):
        """Work agents carry in their own systems right now (read through, never copied): Company teams, Workforce assignments."""
        out, q = {}, self.db.q
        if self._has("co_members") and self._has("co_teams") and self._has("co_company"):
            for r in q("""SELECT m.agent_id, t.id team_id, t.name, t.lead_id, p.name project FROM co_members m JOIN co_teams t ON t.id=m.team_id
                          JOIN co_company c ON c.id=t.company_id LEFT JOIN co_projects p ON p.id=t.project_id
                          WHERE c.user_id=? AND t.status='active'""", (uid,)):
                out.setdefault(f"company:{r['agent_id']}", []).append({"system": "company", "what": r["name"] or r["project"] or f"Team {r['team_id']}",
                                                                       "lead": f"company:{r['lead_id']}" if r["lead_id"] else None, "go": {"view": "company", "tab": "projects"}})
        if self._has("wf_assignments") and self._has("wf_missions") and self._has("wf_agents"):
            keys = {r["key"]: r["id"] for r in q("SELECT id, key FROM wf_agents WHERE user_id=?", (uid,))}
            ceo = next((f"workforce:{i}" for k, i in keys.items() if k == "ceo"), None)
            for r in q("""SELECT a.agent, a.title, m.title mission FROM wf_assignments a JOIN wf_missions m ON m.id=a.mission_id
                          WHERE m.user_id=? AND a.status IN ('running','queued','todo')""", (uid,)):
                if r["agent"] in keys:
                    out.setdefault(f"workforce:{keys[r['agent']]}", []).append({"system": "workforce", "what": f"{r['mission'] or 'Mission'}: {r['title'] or ''}".strip(": "),
                                                                                 "lead": ceo, "go": {"view": "workforce"}})
        if self._has("mw_tasks"):
            agents = {a["id"]: a for a in self._team_agents(uid)}
            leads = {a["comp_id"]: f"teams:{a['id']}" for a in agents.values() if a["lead"]}
            if agents:
                marks = ",".join("?" * len(agents))
                for r in q(f"""SELECT id, comp_id, title, status, agent_id, reviewer FROM mw_tasks WHERE status IN ('working','checking')
                               AND (agent_id IN ({marks}) OR reviewer IN ({marks}))""", (*agents, *agents)):
                    who = r["reviewer"] if r["status"] == "checking" else r["agent_id"]
                    if who in agents:
                        out.setdefault(f"teams:{who}", []).append({"system": "teams", "what": ("Reviewing: " if r["status"] == "checking" else "") + (r["title"] or f"Task {r['id']}"),
                                                                   "lead": leads.get(r["comp_id"]), "go": {"view": "teams", "comp": r["comp_id"]}})
            if self._has("mx_missions"):  # Mission Control's missions running on a team land on its Director
                for r in q("""SELECT id, title, team FROM mx_missions WHERE user_id=? AND engine='mining' AND team IS NOT NULL
                              AND status IN ('queued','running','needs_input')""", (uid,)):
                    if r["team"] in leads:
                        out.setdefault(leads[r["team"]], []).append({"system": "missions", "what": f"Mission: {r['title'] or r['id']}", "lead": None, "go": {"view": "mos"}})
        return out

    def _teams_info(self, uid):
        """Per Competition team: open and finished tasks, and the Director's latest report (what a division manager reads)."""
        out, q = {}, self.db.q
        comps = [w["id"] for w in self._comps(uid)]
        if not comps: return out
        marks, week = ",".join("?" * len(comps)), time.time() - WEEK
        for c in comps: out[c] = {"comp": c, "open": 0, "done_week": 0, "report": None}
        if self._has("mw_tasks"):
            for r in q(f"""SELECT comp_id, SUM(status NOT IN ('done','dropped','cancelled')) open, SUM(status='done' AND {not_dropped(self.db)} AND done_at>=?) done_week
                           FROM mw_tasks WHERE comp_id IN ({marks}) GROUP BY comp_id""", (week, *comps)):
                out[r["comp_id"]].update(open=r["open"] or 0, done_week=r["done_week"] or 0)
        if self._has("mw_reports"):
            for r in q(f"""SELECT comp_id, headline, status, ts, asks FROM mw_reports WHERE id IN (SELECT MAX(id) FROM mw_reports WHERE comp_id IN ({marks}) GROUP BY comp_id)""", comps):
                out[r["comp_id"]]["report"] = {"headline": _clip(r["headline"], 200), "status": r["status"], "ts": r["ts"], "asks": len(_j(r["asks"], []) or [])}
        return out

    def _mission_control(self, uid):
        """Mission Control's missions, which the CEO owns: running, waiting for you, delivered this week."""
        if not self._has("mx_missions"): return None
        r = self.db.q("""SELECT SUM(status IN ('queued','running')) running, SUM(status='needs_input') waiting, SUM(status='delivered' AND finished>=?) delivered_week
                         FROM mx_missions WHERE user_id=?""", (time.time() - WEEK, uid), one=True)
        return {"running": r["running"] or 0, "waiting": r["waiting"] or 0, "delivered_week": r["delivered_week"] or 0}

    def _runtime(self, uid, keys):
        """Agent HQ's question for these agents, from the agent core's run ledger: working now, last activity, runs, failures, tokens."""
        if not keys or not self._has("ac_runs"): return {}
        out, week = {}, time.time() - WEEK
        marks = ",".join("?" * len(keys))
        for r in self.db.q(f"""SELECT agent_key, MAX(status='running') running, MAX(COALESCE(finished, started)) last,
                               SUM(CASE WHEN started>=? THEN 1 ELSE 0 END) runs_week,
                               SUM(CASE WHEN started>=? AND status IN ('failed','lost') THEN 1 ELSE 0 END) failed_week,
                               SUM(CASE WHEN started>=? THEN tokens ELSE 0 END) tokens_week
                               FROM ac_runs WHERE owner_id=? AND agent_key IN ({marks}) GROUP BY agent_key""", [week, week, week, uid] + keys):
            out[r["agent_key"]] = {"running": bool(r["running"]), "last": r["last"], "runs_week": r["runs_week"] or 0, "failed_week": r["failed_week"] or 0,
                                   "tokens_week": r["tokens_week"] or 0}
        for r in self.db.q(f"""SELECT agent_key, title, started FROM ac_runs WHERE owner_id=? AND status='running' AND agent_key IN ({marks}) ORDER BY id DESC""", [uid] + keys):
            out.setdefault(r["agent_key"], {}).setdefault("current", r["title"])
        for r in self.db.q(f"""SELECT agent_key, error FROM ac_runs WHERE owner_id=? AND status IN ('failed','lost') AND started>=? AND agent_key IN ({marks})
                               ORDER BY id DESC""", [uid, week] + keys):
            out.setdefault(r["agent_key"], {}).setdefault("last_error", _clip(r["error"] or "", 200))
        return out

    # ---------- integrity ----------
    def integrity(self, uid, agents, units=()):
        """What's inconsistent in the organization, each with a plain fix. Reporting cycles can't be written; this finds old ones anyway."""
        o, out = self._org(uid), []
        by_name = {}
        for a in agents:  # each team's squads reuse names (and borrow common ones): their team tells them apart
            if a["system"] != "teams": by_name.setdefault(a["name"].strip().lower(), []).append(a)
        for n, xs in sorted(by_name.items()):
            if len(xs) > 1:
                out.append({"level": "warn", "kind": "duplicate_name", "title": f"{len(xs)} agents are called {xs[0]['name']}",
                            "detail": " · ".join(f"{x['ident']} ({x['title']}, {x['system']})" for x in xs) + ". They are separate identities; give one an org title, or rename it in its system, so assignments name the right one.",
                            "keys": [x["key"] for x in xs]})
        ceos = [a for a in agents if re.search(r"\bceo\b", a["title"] or "", re.I) and a["key"] != o["ceo_key"]]
        if ceos:
            out.append({"level": "warn", "kind": "two_ceos", "title": "More than one agent carries a CEO title",
                        "detail": f"The organization's CEO is {next((a['name'] for a in agents if a['key'] == o['ceo_key']), 'not set')}; "
                                  + ", ".join(f"{a['name']} ({a['system']}, {a['title']})" for a in ceos) + " also says CEO. Give them an executive org title, or make one of them the CEO.",
                        "keys": [a["key"] for a in ceos]})
        if not o["ceo_key"]:
            out.append({"level": "warn", "kind": "no_ceo", "title": "No CEO", "detail": "Pick the agent that coordinates the organization (Atlas, in Workforce).", "keys": []})
        unplaced = [a for a in agents if not a["unit_id"] and a["key"] != o["ceo_key"]]
        if unplaced:
            out.append({"level": "info", "kind": "unplaced", "title": f"{len(unplaced)} agent{'s' if len(unplaced) != 1 else ''} not placed yet",
                        "detail": "They report to you directly until you give them a division or department: " + ", ".join(a["name"] for a in unplaced[:12]) + ("…" if len(unplaced) > 12 else ""),
                        "keys": [a["key"] for a in unplaced]})
        keys = {a["key"]: a for a in agents}
        for u in units or []:
            if not u["manager_key"] and u.get("link") != "exec" and not u["headcount"]: continue  # an empty unit: nobody to manage yet
            if not u["manager_key"] and u.get("link") != "exec":  # Executive staff report to the CEO by design
                out.append({"level": "info", "kind": "no_manager", "title": f"{u['name']} has no manager", "detail": f"Its {u['headcount']} member(s) report up the line instead. Pick a manager for this {u['kind']}.", "unit": u["id"], "keys": []})
            elif u["manager_key"] and u["manager_key"] not in keys:
                out.append({"level": "warn", "kind": "manager_gone", "title": f"{u['name']}'s manager is no longer active", "detail": "Pick a new manager.", "unit": u["id"], "keys": []})
        for a in agents:
            m = a["manager"]
            if m and m not in keys:
                out.append({"level": "warn", "kind": "manager_inactive", "title": f"{a['name']} reports to an inactive agent", "detail": "Move the agent or set a new manager.", "keys": [a["key"]]})
            if a["key"] in self.chain(uid, a["key"]):
                out.append({"level": "stop", "kind": "cycle", "title": f"{a['name']} is in a reporting cycle", "detail": "Set a new manager for one agent in the loop.", "keys": [a["key"]]})
        return out

    # ---------- organization changes (yours apply at once; proposals wait for your decision) ----------
    def apply(self, me, op, p, actor=None):
        """One organization change, validated, written and audited. Every path (your edit, an approved request) comes through here."""
        uid, actor = me["id"], actor or me["username"]
        self.ensure(me)
        with self.lock:
            fn = getattr(self, "_op_" + op, None)
            if not fn: raise OrgError(f"Unknown change: {op}", 400)
            res = fn(uid, p, actor)
            self._audit(uid, actor, op, json.dumps(p, sort_keys=True)[:200], res or "")
            return res

    def _op_settings(self, uid, p, actor):
        o = self._org(uid)
        sets, args = [], []
        for f in ("name", "owner_name", "owner_title"):
            if p.get(f) is not None:
                v = str(p[f]).strip()[:80]
                if not v: raise OrgError("That can't be empty.", 400)
                sets.append(f"{f}=?"); args.append(v)
        if p.get("policies") is not None:
            pol = {**o["policies"]}
            for k, v in p["policies"].items():
                if k not in ORG_ACTIONS or v not in ("owner", "direct"): raise OrgError(f"Unknown policy {k}={v}.", 400)
                pol[k] = v
            sets.append("policies=?"); args.append(json.dumps(pol))
        if not sets: return "nothing changed"
        self.db.q(f"UPDATE og_org SET {', '.join(sets)}, updated=? WHERE user_id=?", args + [time.time(), uid])
        return "settings saved"

    def _op_set_ceo(self, uid, p, actor):
        key = p.get("key")
        a = self._agent(uid, key)
        if a["status"] != "active": raise OrgError("Only an active agent can be the CEO.")
        o = self._org(uid)
        self.db.q("UPDATE og_org SET ceo_key=?, updated=? WHERE user_id=?", (key, time.time(), uid))
        self._set_line(uid, key, None, actor, "became the CEO")
        # managers of top units (and unplaced agents' old CEO lines) now report to the new CEO
        for u in self.db.q("SELECT manager_key FROM og_units WHERE user_id=? AND status='active' AND parent_id IS NULL AND manager_key IS NOT NULL", (uid,)):
            if u["manager_key"] != key and self.manager_of(uid, u["manager_key"]) in (None, o["ceo_key"]):
                self._set_line(uid, u["manager_key"], key, actor, "a new CEO")
        if o["ceo_key"] and o["ceo_key"] != key:
            old = self._agent(uid, o["ceo_key"], need=False)
            if old: self._set_line(uid, o["ceo_key"], self._auto_manager(uid, o["ceo_key"], old["unit_id"]), actor, "no longer the CEO")
        return f"{a['name']} is the CEO"

    def _op_add_unit(self, uid, p, actor):
        kind, name = p.get("kind"), str(p.get("name") or "").strip()[:80]
        if kind not in KINDS: raise OrgError("A unit is a division, a department or a team.", 400)
        if not name: raise OrgError("Give the unit a name.", 400)
        parent = p.get("parent_id")
        if kind in ("team", "squad"):
            if not parent: raise OrgError("A team sits inside a division, a department or another team." if kind == "team" else "A squad sits inside a team.", 400)
            pu = self._unit(uid, parent)
            if kind == "squad" and pu["kind"] != "team": raise OrgError("A squad sits inside a team.", 400)
            if kind == "team" and pu["kind"] == "squad": raise OrgError("A team can't sit inside a squad.", 400)
        elif parent: raise OrgError("Divisions and departments sit directly under the CEO.", 400)
        if p.get("budget") not in (None, ""): self._check_budget(uid, None, p["budget"], parent)
        if self.db.q("SELECT 1 FROM og_units WHERE user_id=? AND status='active' AND lower(name)=lower(?) AND COALESCE(parent_id,0)=COALESCE(?,0)", (uid, name, parent), one=True):
            raise OrgError(f"There is already a unit called {name} there.")
        now = time.time()
        uid_ = self.db.q("INSERT INTO og_units (user_id, kind, name, purpose, parent_id, budget, created, updated) VALUES (?,?,?,?,?,?,?,?) RETURNING id",
                         (uid, kind, name, _clip(p.get("purpose") or "", 300), parent, p.get("budget"), now, now), one=True)["id"]
        if p.get("manager_key"): self._op_set_manager(uid, {"unit_id": uid_, "key": p["manager_key"]}, actor)
        return f"{kind} {name} created"

    def _op_edit_unit(self, uid, p, actor):
        u = self._unit(uid, p.get("unit_id"))
        name = str(p.get("name") or u["name"]).strip()[:80]
        parent = p.get("parent_id", u["parent_id"])
        if parent != u["parent_id"]:
            if u["kind"] not in ("team", "squad"): raise OrgError("Only a team or a squad can move under another unit.", 400)
            if not parent: raise OrgError("A team needs a parent unit.", 400)
            pu = self._unit(uid, parent)
            if u["kind"] == "squad" and pu["kind"] != "team": raise OrgError("A squad sits inside a team.", 400)
            if u["kind"] == "team" and pu["kind"] == "squad": raise OrgError("A team can't sit inside a squad.", 400)
            if u["id"] in self._unit_chain(uid, parent): raise OrgError("A unit can't sit inside itself or one of its own teams.")
        if "budget" in p and p["budget"] != u["budget"]:
            if (u["link"] or "").startswith("mw_comp:"): raise OrgError("A Competition team's budget is set on its own page (its governor enforces it).", 400)
            self._check_budget(uid, u["id"], None if p["budget"] in (None, "") else p["budget"], parent)
        self.db.q("UPDATE og_units SET name=?, purpose=?, parent_id=?, budget=?, updated=? WHERE id=?",
                  (name, _clip(p.get("purpose", u["purpose"]) or "", 300), parent, p.get("budget", u["budget"]), time.time(), u["id"]))
        if parent != u["parent_id"] and u["manager_key"]:
            self._set_line(uid, u["manager_key"], self._auto_manager(uid, u["manager_key"], u["id"]), actor, f"{name} moved")
        return f"{name} saved"

    def _op_set_manager(self, uid, p, actor):
        """A unit's manager: placed in the unit, reports to the parent unit's manager (or the CEO); the unit's members who reported
        to the old manager now report to the new one. Their authority level stays as it was: position never raises it."""
        u = self._unit(uid, p.get("unit_id"))
        key, old = p.get("key"), u["manager_key"]
        if key == old: return "no change"
        if key:
            a = self._agent(uid, key)
            if a["status"] != "active": raise OrgError("Only an active agent can manage a unit.")
            o = self._org(uid)
            if key == o["ceo_key"]: raise OrgError("The CEO manages the whole organization; pick someone else for this unit.")
            other = self.db.q("SELECT name FROM og_units WHERE user_id=? AND status='active' AND manager_key=? AND id!=?", (uid, key, u["id"]), one=True)
            if other: raise OrgError(f"{a['name']} already manages {other['name']}. Pick a manager for {other['name']} first.")
            # checked before anything is written: the new manager's own manager-to-be may not report to them
            boss = self._above(uid, u, key)
            if boss and key in self.chain(uid, boss):
                raise OrgError(f"That would make a reporting cycle: {self._agent(uid, boss)['name']} reports to {a['name']}.")
        self.db.q("UPDATE og_units SET manager_key=?, updated=? WHERE id=?", (key, time.time(), u["id"]))
        try:
            if key:
                self.db.q("UPDATE og_agents SET unit_id=?, updated=? WHERE user_id=? AND key=?", (u["id"], time.time(), uid, key))
                self._set_line(uid, key, None, actor, "taking over a unit")  # clear first, so the members can be re-pointed without a cycle
            for m in self.db.q("SELECT key FROM og_agents WHERE user_id=? AND unit_id=? AND status NOT IN ('archived','gone')", (uid, u["id"])):
                if m["key"] == key: continue
                cur = self.manager_of(uid, m["key"])
                if m["key"] == old or cur in (old, None) or cur == key: self._set_line(uid, m["key"], key or self._auto_manager(uid, m["key"], u["id"]), actor, f"new manager of {u['name']}")
            for t in self.db.q("SELECT id, manager_key FROM og_units WHERE user_id=? AND parent_id=? AND status='active' AND manager_key IS NOT NULL", (uid, u["id"])):
                self._set_line(uid, t["manager_key"], self._auto_manager(uid, t["manager_key"], t["id"]), actor, f"new manager of {u['name']}")
            if key: self._set_line(uid, key, self._auto_manager(uid, key, u["id"]), actor, f"manages {u['name']}")
        except HTTPException:
            self.db.q("UPDATE og_units SET manager_key=? WHERE id=?", (old, u["id"]))
            raise
        return f"{u['name']} is managed by {self._agent(uid, key)['name'] if key else 'nobody'}"

    def _op_dissolve(self, uid, p, actor):
        """A unit closes: its teams and people move to the parent unit (or become unplaced); missions and lines stay valid."""
        u = self._unit(uid, p.get("unit_id"))
        now = time.time()
        if self.db.q("SELECT 1 FROM og_missions WHERE user_id=? AND unit_id=? AND status IN ('planning','active')", (uid, u["id"]), one=True):
            raise OrgError(f"{u['name']} still owns an active mission: end or move the mission first.")
        self.db.q("UPDATE og_units SET status='dissolved', updated=? WHERE id=?", (now, u["id"]))
        moved = set()
        for s in self.db.q("SELECT id FROM og_units WHERE user_id=? AND parent_id=? AND kind='squad' AND status='active'", (uid, u["id"])):
            # a squad can't outlive its team: it dissolves with it, its people move where the team's go
            self.db.q("UPDATE og_units SET status='dissolved', updated=? WHERE id=?", (now, s["id"]))
            moved |= {r["key"] for r in self.db.q("SELECT key FROM og_agents WHERE user_id=? AND unit_id=?", (uid, s["id"]))}
            self.db.q("UPDATE og_agents SET unit_id=?, updated=? WHERE user_id=? AND unit_id=?", (u["parent_id"], now, uid, s["id"]))
        self.db.q("UPDATE og_assign SET status='released', released=? WHERE user_id=? AND unit_id=? AND status='active' AND mission_id IS NULL", (now, uid, u["id"]))
        self.db.q("UPDATE og_units SET parent_id=?, updated=? WHERE user_id=? AND parent_id=? AND status='active'", (u["parent_id"], now, uid, u["id"]))
        if not u["parent_id"]:  # a top unit's teams become … teams need a parent: they close too, members unplaced
            for t in self.db.q("SELECT id FROM og_units WHERE user_id=? AND parent_id IS NULL AND kind='team' AND status='active'", (uid,)):
                self.db.q("UPDATE og_units SET status='dissolved', updated=? WHERE id=?", (now, t["id"]))
                self.db.q("UPDATE og_agents SET unit_id=NULL, updated=? WHERE user_id=? AND unit_id=?", (now, uid, t["id"]))
        self.db.q("UPDATE og_agents SET unit_id=?, updated=? WHERE user_id=? AND unit_id=?", (u["parent_id"], now, uid, u["id"]))
        for a in self.db.q("SELECT key, unit_id FROM og_agents WHERE user_id=? AND status NOT IN ('archived','gone')", (uid,)):
            m = self.manager_of(uid, a["key"])
            if m == u["manager_key"] or (m and not self._agent(uid, m, need=False)) or a["key"] == u["manager_key"] or a["key"] in moved:
                self._set_line(uid, a["key"], self._auto_manager(uid, a["key"], a["unit_id"]), actor, f"{u['name']} dissolved")
        return f"{u['name']} dissolved"

    def _op_move_agent(self, uid, p, actor):
        """An agent's permanent home and manager. manager 'auto' (the default) = the unit's manager. Missions are untouched."""
        key = p.get("key")
        a = self._agent(uid, key)
        if a["status"] in ("archived", "gone"): raise OrgError("That agent is no longer active.")
        unit = p.get("unit_id")
        if unit: self._unit(uid, unit)
        o = self._org(uid)
        if key == o["ceo_key"] and unit: raise OrgError("The CEO sits above every unit.")
        led = self.db.q("SELECT id, name FROM og_units WHERE user_id=? AND status='active' AND manager_key=?", (uid, key), one=True)
        if led and unit != led["id"]: raise OrgError(f"{a['name']} manages {led['name']}: pick a new manager for it first.")
        manager = p.get("manager", "auto")
        if manager == "auto": manager = self._auto_manager(uid, key, unit)
        self._set_line(uid, key, manager, actor, p.get("reason") or "moved")  # validates (cycle) before the home changes
        self.db.q("UPDATE og_agents SET unit_id=?, updated=? WHERE user_id=? AND key=?", (unit, time.time(), uid, key))
        un = self._unit(uid, unit, need=False) if unit else None
        return f"{a['name']} → {un['name'] if un else 'not placed'}, reports to {self._agent(uid, manager)['name'] if manager else 'you'}"

    def _op_profile(self, uid, p, actor):
        a = self._agent(uid, p.get("key"))
        sets, args = [], []
        if p.get("title") is not None: sets.append("title=?"); args.append(str(p["title"]).strip()[:80] or None)
        if p.get("skills") is not None:
            sk = {}
            for k, v in dict(p["skills"]).items():
                k = _slug(k)
                try: v = int(v)
                except (TypeError, ValueError): raise OrgError("A skill's level is 1 to 5.", 400)
                if not 1 <= v <= 5: raise OrgError("A skill's level is 1 to 5.", 400)
                sk[k] = v
            sets.append("skills=?"); args.append(json.dumps(sk))
        if p.get("cap") is not None:
            c = int(p["cap"])
            if not 1 <= c <= 12: raise OrgError("Capacity is 1 to 12 assignments.", 400)
            sets.append("cap=?"); args.append(c)
        if p.get("status") is not None:
            if p["status"] not in ("active", "paused"): raise OrgError("An agent is active or paused here.", 400)
            sets.append("status=?"); args.append(p["status"])
        if not sets: return "nothing changed"
        self.db.q(f"UPDATE og_agents SET {', '.join(sets)}, updated=? WHERE user_id=? AND key=?", args + [time.time(), uid, a["key"]])
        return f"{a['name']}'s profile saved"

    def _op_autonomy(self, uid, p, actor):
        """Execution authority. Lowering applies at once; raising to L3 or more is only ever applied by an approved request."""
        a = self._agent(uid, p.get("key"))
        lvl = int(p.get("level", -1))
        if not 0 <= lvl <= 4: raise OrgError("Levels are L0 to L4.", 400)
        if lvl >= APPROVAL_FROM and lvl > a["autonomy"] and not p.get("_approved"):
            raise OrgError(f"Raising {a['name']} to L{lvl} needs your approval: ask for it as a request.", 403)
        self.db.q("UPDATE og_agents SET autonomy=?, updated=? WHERE user_id=? AND key=?", (lvl, time.time(), uid, a["key"]))
        return f"{a['name']}: L{a['autonomy']} → L{lvl}"

    def _op_promote(self, uid, p, actor):
        """A promotion = leading a team (an existing one without a leader, or a new team inside the agent's unit). Its level stays."""
        a = self._agent(uid, p.get("key"))
        if p.get("unit_id"):
            return self._op_set_manager(uid, {"unit_id": p["unit_id"], "key": a["key"]}, actor)
        if not a["unit_id"]: raise OrgError(f"Place {a['name']} in a unit first.")
        name = str(p.get("team") or f"{a['name']}'s team").strip()[:80]
        r = self._op_add_unit(uid, {"kind": "team", "name": name, "parent_id": a["unit_id"], "purpose": p.get("purpose") or ""}, actor)
        t = self.db.q("SELECT id FROM og_units WHERE user_id=? AND parent_id=? AND name=? AND status='active' ORDER BY id DESC LIMIT 1", (uid, a["unit_id"], name), one=True)
        self._op_set_manager(uid, {"unit_id": t["id"], "key": a["key"]}, actor)
        return f"{r}, led by {a['name']}"

    def _op_retitle(self, uid, p, actor): return self._op_profile(uid, {"key": p.get("key"), "title": p.get("title")}, actor)

    # ---------- missions (temporary; never touch reporting lines) ----------
    def _op_add_mission(self, uid, p, actor):
        name = str(p.get("name") or "").strip()[:120]
        if not name: raise OrgError("Give the mission a name.", 400)
        mgr = p.get("manager_key")
        if mgr:
            a = self._agent(uid, mgr)
            if a["status"] != "active": raise OrgError("The mission manager must be an active agent.")
        if p.get("unit_id"): self._unit(uid, p["unit_id"])
        skills = [_slug(s) for s in (p.get("skills") or []) if str(s).strip()][:12]
        now = time.time()
        mid = self.db.q("""INSERT INTO og_missions (user_id, name, objective, unit_id, manager_key, skills, link, status, due, created)
                           VALUES (?,?,?,?,?,?,?,'active',?,?) RETURNING id""",
                        (uid, name, _clip(p.get("objective") or "", 1000), p.get("unit_id"), mgr, json.dumps(skills), p.get("link"), p.get("due"), now), one=True)["id"]
        return {"mission_id": mid, "msg": f"mission {name} started"}

    def _mission(self, uid, mid, active=True):
        m = self.db.q("SELECT * FROM og_missions WHERE user_id=? AND id=?", (uid, mid), one=True)
        if not m: raise OrgError("No such mission.", 404)
        if active and m["status"] not in ("planning", "active"): raise OrgError("That mission has ended.")
        return m

    def _op_assign(self, uid, p, actor):
        m = self._mission(uid, p.get("mission_id"))
        keys = p.get("keys") or ([p["key"]] if p.get("key") else [])
        done = []
        for key in keys:
            a = self._agent(uid, key)
            if a["status"] != "active": raise OrgError(f"{a['name']} isn't active.")
            if self.db.q("SELECT 1 FROM og_assign WHERE mission_id=? AND agent_key=? AND status='active'", (m["id"], key), one=True): continue
            self.db.q("INSERT INTO og_assign (user_id, mission_id, agent_key, role, duty, status, since, by) VALUES (?,?,?,?,?,'active',?,?)",
                      (uid, m["id"], key, _clip(p.get("role") or a["title"] or a["role"] or "member", 80), _clip(p.get("duty") or "", 300), time.time(), actor))
            done.append(a["name"])
        return f"{', '.join(done) or 'nobody new'} on {m['name']}"

    def _op_release(self, uid, p, actor):
        m = self._mission(uid, p.get("mission_id"), active=False)
        n = len(self.db.q("UPDATE og_assign SET status='released', released=? WHERE mission_id=? AND agent_key=? AND status='active' RETURNING id",
                          (time.time(), m["id"], p.get("key"))))
        return f"released from {m['name']}" if n else "wasn't on the mission"

    def _op_end_mission(self, uid, p, actor):
        """A mission ends (done or cancelled): everyone returns to their permanent unit; open tasks of the mission are cancelled."""
        m = self._mission(uid, p.get("mission_id"))
        st = "cancelled" if p.get("cancelled") else "done"
        now = time.time()
        self.db.q("UPDATE og_missions SET status=?, ended=? WHERE id=?", (st, now, m["id"]))
        n = len(self.db.q("UPDATE og_assign SET status='released', released=? WHERE mission_id=? AND status='active' RETURNING id", (now, m["id"])))
        for t in self.db.q("SELECT id, history FROM og_tasks WHERE mission_id=? AND status NOT IN ('done','cancelled')", (m["id"],)):
            self._task_note(t, "cancelled", actor, "the mission ended")
            self.db.q("UPDATE og_tasks SET status='cancelled', history=?, updated=? WHERE id=?", (json.dumps(t["_h"]), now, t["id"]))
        return f"{m['name']} {st}; {n} agent(s) back to their departments"

    def _op_mission_manager(self, uid, p, actor):
        m = self._mission(uid, p.get("mission_id"))
        if p.get("key"):
            a = self._agent(uid, p["key"])
            if a["status"] != "active": raise OrgError("The mission manager must be an active agent.")
        self.db.q("UPDATE og_missions SET manager_key=? WHERE id=?", (p.get("key"), m["id"]))
        return "mission manager set"

    # ---------- delegation and escalation ----------
    @staticmethod
    def _task_note(t, what, by, note="", to=None):
        h = _j(t.get("history"), []) if isinstance(t.get("history"), str) else list(t.get("history") or [])
        h.append({"ts": time.time(), "what": what, "by": by, "note": _clip(note, 300), **({"to": to} if to else {})})
        t["_h"] = h[-40:]

    def may_delegate(self, uid, frm, to, mission_id=None):
        """frm may hand work to `to` when frm sits above `to` in the permanent line, or frm manages a mission `to` is on (and the task
        belongs to that mission). The owner (frm None) and the CEO may delegate to anyone."""
        o = self._org(uid)
        if frm is None or frm == o["ceo_key"]: return True
        if frm in self.chain(uid, to): return True
        if mission_id:
            m = self.db.q("SELECT manager_key FROM og_missions WHERE user_id=? AND id=? AND status IN ('planning','active')", (uid, mission_id), one=True)
            on = self.db.q("SELECT 1 FROM og_assign WHERE mission_id=? AND agent_key=? AND status='active'", (mission_id, to), one=True)
            if m and m["manager_key"] == frm and on: return True
        return False

    def _op_delegate(self, uid, p, actor):
        title = str(p.get("title") or "").strip()[:200]
        if not title: raise OrgError("What's the task?", 400)
        frm, to, mid = p.get("from_key") or None, p.get("to_key"), p.get("mission_id")
        target = self._agent(uid, to)
        if target["status"] != "active": raise OrgError(f"{target['name']} isn't active.")
        if frm: self._agent(uid, frm)
        if mid: self._mission(uid, mid)
        if not self.may_delegate(uid, frm, to, mid):
            fn = self._agent(uid, frm)["name"]
            raise OrgError(f"{fn} doesn't manage {target['name']}: delegate down the reporting line, or inside a mission {fn} manages.", 403)
        lvl = int(p.get("level", 1))
        if not 0 <= lvl <= 4: raise OrgError("Levels are L0 to L4.", 400)
        sens = p.get("sensitive") or None
        if sens and sens not in LOCKED: raise OrgError("Unknown sensitive action.", 400)
        if target["autonomy"] < lvl:
            raise OrgError(f"{target['name']} is L{target['autonomy']} {LEVELS[target['autonomy']]['name']}; this task needs L{lvl} {LEVELS[lvl]['name']}. "
                           f"Pick an agent with that authority, lower the task's level, or raise {target['name']}'s level first.", 403)
        needs = lvl >= APPROVAL_FROM or bool(sens)
        now = time.time()
        t = {"history": []}
        self._task_note(t, "delegated", actor, f"from {self._agent(uid, frm)['name'] if frm else 'you'} to {target['name']}")
        tid = self.db.q("""INSERT INTO og_tasks (user_id, mission_id, title, detail, level, sensitive, from_key, to_key, holder_key, status, due, history, created, updated)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
                        (uid, mid, title, _clip(p.get("detail") or "", 2000), lvl, sens, frm, to, to, "awaiting" if needs else "open", p.get("due"),
                         json.dumps(t["_h"]), now, now), one=True)["id"]
        if needs:
            why = LOCKED[sens] if sens else f"L{lvl} {LEVELS[lvl]['name']}"
            self._request(uid, "task_go", f"Let {target['name']} start: {title}", f"{why} needs your approval before the work starts.",
                          {"task_id": tid}, actor)
        return {"task_id": tid, "msg": "waiting for your approval" if needs else f"delegated to {target['name']}"}

    def _op_task(self, uid, p, actor):
        """A task moves: done, blocked, cancelled, escalate (one step up), or reassigned back down by whoever holds it now."""
        t = self.db.q("SELECT * FROM og_tasks WHERE user_id=? AND id=?", (uid, p.get("task_id")), one=True)
        if not t: raise OrgError("No such task.", 404)
        act = p.get("action")
        if t["status"] in ("done", "cancelled"): raise OrgError("That task is closed.")
        if t["status"] == "awaiting" and act not in ("cancel",): raise OrgError("That task waits for your approval first.")
        now, status, holder = time.time(), t["status"], t["holder_key"]
        if act == "done": status = "done"
        elif act == "cancel": status = "cancelled"
        elif act == "block": status = "blocked"
        elif act == "resume": status = "open" if holder else "escalated"
        elif act == "escalate":
            holder = self._escalate_to(uid, t)
            status = "escalated"
        elif act == "assign":  # whoever holds it (or you) hands it back down
            to = p.get("to_key")
            target = self._agent(uid, to)
            if target["autonomy"] < t["level"]: raise OrgError(f"{target['name']} doesn't have L{t['level']} authority.", 403)
            if holder and not self.may_delegate(uid, holder, to, t["mission_id"]): raise OrgError("The holder can only hand it down its own line.", 403)
            holder, status = to, "open"
        else: raise OrgError("Unknown task action.", 400)
        self._task_note(t, act, actor, p.get("note") or (f"now with {self._agent(uid, holder)['name']}" if holder else "now with you" if act == "escalate" else ""),
                        to=holder if act in ("escalate", "assign") else None)
        self.db.q("UPDATE og_tasks SET status=?, holder_key=?, history=?, updated=? WHERE id=?", (status, holder, json.dumps(t["_h"]), now, t["id"]))
        if act == "escalate" and p.get("due_extend"): self.db.q("UPDATE og_tasks SET due=? WHERE id=?", (now + DAY, t["id"]))
        return f"task {act}"

    def _escalate_to(self, uid, t):
        """One step up from the holder: its permanent manager; inside a mission, the mission manager first. Above the CEO: you (None)."""
        cur = t["holder_key"]
        if not cur: raise OrgError("It's with you already: decide, reassign or cancel it.")
        if t["mission_id"]:
            m = self.db.q("SELECT manager_key FROM og_missions WHERE id=?", (t["mission_id"],), one=True)
            hist = t["history"] if isinstance(t["history"], list) else (_j(t["history"], []) or [])
            mm = m and m["manager_key"]
            if mm and mm != cur and cur not in self.chain(uid, mm) and not any(h.get("to") == mm for h in hist):
                return mm
        return self.manager_of(uid, cur)

    def tick(self):
        """Overdue tasks escalate one step (the due date moves a day on), and stale requests expire."""
        now = time.time()
        self.db.q("UPDATE og_requests SET status='expired', decided=? WHERE status='pending' AND expires<?", (now, now))
        for t in self.db.q("SELECT * FROM og_tasks WHERE status IN ('open','blocked') AND due IS NOT NULL AND due<? AND holder_key IS NOT NULL", (now,)):
            try:
                with self.lock:
                    holder = self._escalate_to(t["user_id"], t)
                    self._task_note(t, "escalate", "system", "overdue", to=holder)
                    self.db.q("UPDATE og_tasks SET status='escalated', holder_key=?, due=?, history=?, updated=? WHERE id=?",
                              (holder, now + DAY, json.dumps(t["_h"]), now, t["id"]))
                    self._audit(t["user_id"], "system", "escalate", f"task {t['id']}", "overdue")
            except Exception:  # noqa: BLE001 - one task never stops the others
                log.exception("organization: escalating task %s", t["id"])

    # ---------- approval requests: proposals wait for your decision, applied once ----------
    def _request(self, uid, kind, title, why, payload, by):
        now = time.time()
        return self.db.q("""INSERT INTO og_requests (user_id, kind, title, why, payload, sha, by, status, created, expires)
                            VALUES (?,?,?,?,?,?,?,'pending',?,?) RETURNING id""",
                         (uid, kind, _clip(title, 200), _clip(why, 600), json.dumps(payload), _sha({"kind": kind, "payload": payload}), by, now, now + REQUEST_DAYS * DAY), one=True)["id"]

    def _requests(self, uid):
        rows = self.db.q("SELECT * FROM og_requests WHERE user_id=? AND (status='pending' OR decided>?) ORDER BY status='pending' DESC, id DESC LIMIT 60", (uid, time.time() - 14 * DAY))
        for r in rows: r["payload"] = _j(r["payload"], {})
        return rows

    def propose(self, me, kind, p, by=None):
        """A change waits for your decision (a request), or applies at once when your policy says 'direct' for it (never for locked
        kinds: autonomy L3+ and task go-aheads)."""
        uid = me["id"]
        o = self.ensure(me)
        by = by or me["username"]
        author = o["ceo_key"] if by == "atlas" else (by if self._agent(uid, by, need=False) else None)
        if author and author == p.get("key") and kind in ("autonomy", "promote", "set_manager", "assign_unit", "move_agent"):
            raise OrgError("An agent can recommend changes, but never grant itself authority: someone else has to propose this.", 403)
        if kind == "budget":  # locked: always your decision
            u = self._unit(uid, p.get("unit_id"))
            title, why = p.get("title") or f"Budget for {u['name']}: {p.get('budget')} tokens a day", p.get("why") or LOCKED["budget_change"] + " always need your approval."
        elif kind == "assign_unit":
            if o["policies"].get("assign") == "direct": return {"applied": self.apply(me, kind, {k: v for k, v in p.items() if k not in ("title", "why")}, by)}
            title, why = p.get("title") or "Assign a specialist", p.get("why") or ""
        elif kind == "autonomy":
            a = self._agent(uid, p.get("key"))
            lvl = int(p.get("level", 0))
            if lvl < APPROVAL_FROM or lvl <= a["autonomy"]: return {"applied": self.apply(me, "autonomy", p)}
            title, why = f"Raise {a['name']} to L{lvl} {LEVELS[lvl]['name']}", p.get("why") or "Execution authority at this level needs your approval."
        elif kind in ("move_agent", "promote", "assign", "set_manager", "dissolve"):
            if o["policies"].get(kind) == "direct": return {"applied": self.apply(me, kind, p, by)}
            title, why = p.get("title") or f"{ORG_ACTIONS[kind]}", p.get("why") or ""
        else: raise OrgError("That can't be proposed.", 400)
        p = {k: v for k, v in p.items() if k not in ("title", "why")}
        if self.db.q("SELECT 1 FROM og_requests WHERE user_id=? AND status='pending' AND sha=?", (uid, _sha({"kind": kind, "payload": p})), one=True):
            raise OrgError("The same request is already waiting for you.")
        return {"request_id": self._request(uid, kind, title, why, p, by)}

    def decide(self, me, rid, ok, note=""):
        uid = me["id"]
        with self.lock:
            r = self.db.q("SELECT * FROM og_requests WHERE user_id=? AND id=?", (uid, rid), one=True)
            if not r: raise OrgError("No such request.", 404)
            if r["status"] != "pending": raise OrgError(f"That request is {r['status']} already.")
            if r["expires"] < time.time():
                self.db.q("UPDATE og_requests SET status='expired', decided=? WHERE id=?", (time.time(), rid))
                raise OrgError("That request expired.")
            payload = _j(r["payload"], {})
            if _sha({"kind": r["kind"], "payload": payload}) != r["sha"]: raise OrgError("That request changed after it was made; it can't be applied.")
            # the request is consumed first, in one statement: it can only ever be applied once
            if not self.db.q("UPDATE og_requests SET status=?, decided=?, decided_by=?, note=? WHERE id=? AND status='pending' RETURNING id",
                             ("approved" if ok else "rejected", time.time(), me["username"], _clip(note, 400), rid)):
                raise OrgError("Someone decided that request a moment ago.")
            if not ok:
                if r["kind"] == "task_go":
                    t = self.db.q("SELECT * FROM og_tasks WHERE id=? AND user_id=?", (payload.get("task_id"), uid), one=True)
                    if t and t["status"] == "awaiting":
                        self._task_note(t, "rejected", me["username"], note)
                        self.db.q("UPDATE og_tasks SET status='cancelled', history=?, updated=? WHERE id=?", (json.dumps(t["_h"]), time.time(), t["id"]))
                self._audit(uid, me["username"], "reject", r["title"], note)
                return {"status": "rejected"}
            try:
                if r["kind"] == "task_go":
                    t = self.db.q("SELECT * FROM og_tasks WHERE id=? AND user_id=?", (payload.get("task_id"), uid), one=True)
                    if not t or t["status"] != "awaiting": raise OrgError("That task isn't waiting any more.")
                    self._task_note(t, "approved", me["username"], note)
                    self.db.q("UPDATE og_tasks SET status='open', history=?, updated=? WHERE id=?", (json.dumps(t["_h"]), time.time(), t["id"]))
                    res = "the task may start"
                elif r["kind"] == "autonomy": res = self.apply(me, "autonomy", {**payload, "_approved": True}, f"{me['username']} (approved)")
                else: res = self.apply(me, r["kind"], payload, f"{me['username']} (approved {r['by']}'s request)")
            except HTTPException as e:
                self.db.q("UPDATE og_requests SET status='failed', result=? WHERE id=?", (_clip(e.detail, 300), rid))
                raise OrgError(f"Approved, but it couldn't be applied: {e.detail}")
            res = res["msg"] if isinstance(res, dict) else res
            self.db.q("UPDATE og_requests SET status='applied', result=? WHERE id=?", (_clip(res, 300), rid))
            return {"status": "applied", "result": res}

    # ---------- allocation: Atlas's recommendation, deterministic ----------
    def recommend(self, me, mid, size=None):
        """Best agents for a mission: skill match against what it needs, free capacity, performance, and the mission's division.
        Plus an independent evaluator from Evaluation who isn't on it. No model call."""
        v = self.view(me)
        m = next((x for x in v["missions"] if x["id"] == mid), None)
        if not m: raise OrgError("No such active mission.", 404)
        need = m["skills"] or []
        on = {p["key"] for p in m["people"]}
        units = {u["id"]: u for u in v["units"]}
        evals = {u["id"] for u in v["units"] if u["kind"] == "department" and (u["link"] == "wf_team:evaluation" or "evaluat" in u["name"].lower())}
        cands = []
        for a in v["agents"]:
            if a["status"] != "active" or a["key"] in on or a["key"] in (v["org"]["ceo"], m["manager_key"]): continue
            sk = a["skills"]
            match = (sum(min(sk.get(s, 0), 5) for s in need) / (5 * len(need))) if need else 0.5
            free = max(0.0, 1 - a["load"] / max(1, a["cap"]))
            perf = (a["perf"]["score"] / 100) if a.get("perf") and a["perf"].get("score") is not None else 0.6
            home = 0.1 if m["unit_id"] and (a["unit_id"] == m["unit_id"] or (a["unit_id"] in units and units[a["unit_id"]]["parent_id"] == m["unit_id"])) else 0.0
            score = round(100 * (0.5 * match + 0.25 * free + 0.15 * perf + home), 1)
            if need and match == 0 and a["unit_id"] not in evals: continue
            why = [f"{s} {sk[s]}/5" for s in need if sk.get(s)] or ["general fit"]
            why.append(f"{a['load']} of {a['cap']} busy")
            if a.get("perf") and a["perf"].get("score") is not None: why.append(f"score {round(a['perf']['score'])}")
            cands.append({"key": a["key"], "name": a["name"], "title": a["title"], "unit": units.get(a["unit_id"], {}).get("name"), "score": score,
                          "why": " · ".join(why), "full": a["load"] >= a["cap"], "covers": [s for s in need if sk.get(s, 0) >= 3],
                          "evaluator": a["unit_id"] in evals, "eval_skill": sk.get("evaluation", 0), "manager": a["manager"]})
        cands.sort(key=lambda c: (c["full"], -c["score"]))
        team, covered = [], set()
        for s in need:  # the smallest team that covers the skills, best first, skipping full agents
            if s in covered: continue
            pick = next((c for c in cands if not c["full"] and s in c["covers"] and c["key"] not in {t["key"] for t in team} and not c["evaluator"]), None)
            if pick: team.append(pick); covered.update(pick["covers"])
        if size: team = team[:size]
        evs = [c for c in cands if c["evaluator"] and not c["full"] and c["key"] not in {t["key"] for t in team}]
        ev = max(evs, key=lambda c: (c["eval_skill"], c["score"])) if evs else None  # the strongest evaluator, not the best skill match
        return {"mission": m["id"], "need": need, "missing": [s for s in need if s not in covered], "team": team, "evaluator": ev, "candidates": cands[:24]}

    # ---------- performance: scores from real work, promotion recommendations ----------
    def compute_perf(self, me):
        """Scores every agent from what it finished: success (runs and assignments done vs failed), quality (evaluation scores on its
        work), reliability (delegated tasks done vs escalated or overdue). Under MIN_EVIDENCE pieces of work, no score."""
        o = self.ensure(me)
        uid, q, now, since = me["id"], self.db.q, time.time(), time.time() - 90 * DAY
        agents = q("SELECT key, system FROM og_agents WHERE user_id=? AND status NOT IN ('archived','gone')", (uid,))
        runs = {}
        if self._has("ac_runs"):
            for r in q("""SELECT agent_key, SUM(status='done') ok, SUM(status IN ('failed','lost')) bad FROM ac_runs WHERE owner_id=? AND started>=?
                          AND kind!='earlier' AND agent_key IS NOT NULL GROUP BY agent_key""", (uid, since)):
                runs[r["agent_key"]] = (r["ok"] or 0, r["bad"] or 0)
        quality = {}
        if self._has("wf_assignments") and self._has("wf_agents"):
            keys = {r["key"]: f"workforce:{r['id']}" for r in q("SELECT id, key FROM wf_agents WHERE user_id=?", (uid,))}
            for r in q("""SELECT a.agent, a.verdict, a.score FROM wf_assignments a JOIN wf_missions m ON m.id=a.mission_id
                          WHERE m.user_id=? AND a.finished>=? AND a.verdict IS NOT NULL""", (uid, since)):
                k = keys.get(r["agent"])
                if not k: continue
                d = quality.setdefault(k, {"scores": [], "pass": 0, "fail": 0})
                if r["score"] is not None: d["scores"].append(max(0, min(100, r["score"])))
                d["pass" if r["verdict"] == "pass" else "fail"] += 1
        if self._has("co_evals") and self._has("co_artifacts") and self._has("co_company"):
            for r in q("""SELECT a.by_agent, e.score, e.verdict FROM co_evals e JOIN co_artifacts a ON a.id=e.artifact_id JOIN co_company c ON c.id=a.company_id
                          WHERE c.user_id=? AND e.ts>=?""", (uid, since)):
                d = quality.setdefault(f"company:{r['by_agent']}", {"scores": [], "pass": 0, "fail": 0})
                if r["score"] is not None: d["scores"].append(max(0, min(100, r["score"])))
                v = (r["verdict"] or "").lower()
                if v in ("pass", "fail"): d[v] += 1  # 'revise' counts by its score only
        rel = {}
        for r in q("SELECT to_key, history, status, due, updated FROM og_tasks WHERE user_id=? AND created>=?", (uid, since)):
            d = rel.setdefault(r["to_key"], [0, 0])
            hist = _j(r["history"], []) or []
            if r["status"] == "done" and not any(h.get("what") == "escalate" for h in hist): d[0] += 1
            elif r["status"] in ("done", "escalated", "cancelled") or (r["due"] and r["due"] < now and r["status"] != "done"): d[1] += 1
        for a in agents:
            k = a["key"]
            ok, bad = runs.get(k, (0, 0))
            qd = quality.get(k, {"scores": [], "pass": 0, "fail": 0})
            ok2, bad2 = ok + qd["pass"], bad + qd["fail"]
            r_ok, r_bad = rel.get(k, (0, 0))
            evidence = ok2 + bad2 + r_ok + r_bad
            success = ok2 / (ok2 + bad2) if ok2 + bad2 else None
            qual = sum(qd["scores"]) / len(qd["scores"]) / 100 if qd["scores"] else None
            reli = r_ok / (r_ok + r_bad) if r_ok + r_bad else None
            parts = [(w, x) for w, x in ((0.4, success), (0.4, qual), (0.2, reli)) if x is not None]
            score = round(100 * sum(w * x for w, x in parts) / sum(w for w, _ in parts), 1) if parts and evidence >= MIN_EVIDENCE else None
            q("""INSERT INTO og_perf (user_id, agent_key, ts, evidence, success, quality, reliability, score, detail) VALUES (?,?,?,?,?,?,?,?,?)""",
              (uid, k, now, evidence, success, qual, reli, score, json.dumps({"runs_ok": ok, "runs_failed": bad, "evals": len(qd["scores"]), "pass": qd["pass"],
                                                                                "fail": qd["fail"], "tasks_ok": r_ok, "tasks_bad": r_bad})))
        q("DELETE FROM og_perf WHERE user_id=? AND ts<?", (uid, now - 180 * DAY))
        self._audit(uid, me["username"], "performance", "all agents", f"{len(agents)} scored")
        return self.recommendations(me)

    def _perf_latest(self, uid):
        out = {}
        for r in self.db.q("""SELECT p.* FROM og_perf p JOIN (SELECT agent_key, MAX(ts) t FROM og_perf WHERE user_id=? GROUP BY agent_key) x
                              ON x.agent_key=p.agent_key AND x.t=p.ts WHERE p.user_id=?""", (uid, uid)):
            out[r["agent_key"]] = {"score": r["score"], "evidence": r["evidence"], "success": r["success"], "quality": r["quality"],
                                   "reliability": r["reliability"], "ts": r["ts"], "detail": _j(r["detail"], {})}
        return out

    def recommendations(self, me):
        """Promotions (lead a team), reviews (lower autonomy, coaching) and staffing gaps, from the latest scores. Proposals only."""
        v = self.view(me)
        units = {u["id"]: u for u in v["units"]}
        out = []
        for a in v["agents"]:
            p = a.get("perf")
            if a["status"] != "active" or not p or p["score"] is None: continue
            if p["score"] >= 80 and p["evidence"] >= MIN_EVIDENCE and a["rank"] == "specialist":
                u = units.get(a["unit_id"])
                free = next((t for t in v["units"] if t["kind"] == "team" and t["parent_id"] == a["unit_id"] and not t["manager_key"]), None)
                out.append({"kind": "promote", "key": a["key"], "name": a["name"], "score": p["score"], "evidence": p["evidence"],
                            "title": f"Promote {a['name']} to team leader" + (f" of {free['name']}" if free else f" (a new team in {u['name']})" if u else ""),
                            "why": f"Score {round(p['score'])} over {p['evidence']} finished pieces of work. Execution authority stays L{a['autonomy']}.",
                            "payload": {"key": a["key"], **({"unit_id": free["id"]} if free else {})}})
            elif p["score"] < 45 and p["evidence"] >= MIN_EVIDENCE:
                out.append({"kind": "review", "key": a["key"], "name": a["name"], "score": p["score"], "evidence": p["evidence"],
                            "title": f"Review {a['name']}'s role", "why": f"Score {round(p['score'])} over {p['evidence']} pieces of work: coach, change the role, or lower its authority.",
                            "payload": {"key": a["key"], "level": max(0, a["autonomy"] - 1)} if a["autonomy"] > 0 else None})
        for u in v["units"]:
            if not u["manager_key"] and u["headcount"]:
                best = sorted([a for a in v["agents"] if a["unit_id"] == u["id"] and a["status"] == "active"],
                              key=lambda a: -((a.get("perf") or {}).get("score") or 0))
                if best:
                    out.append({"kind": "manager", "key": best[0]["key"], "name": best[0]["name"], "score": (best[0].get("perf") or {}).get("score"),
                                "title": f"Make {best[0]['name']} manager of {u['name']}", "why": f"{u['name']} has {u['headcount']} member(s) and no manager.",
                                "payload": {"unit_id": u["id"], "key": best[0]["key"]}})
        return {"recommendations": out}

    # ---------- audit ----------
    def audit(self, me, before=None):
        self.ensure(me)
        return {"audit": self.db.q(f"SELECT * FROM og_audit WHERE user_id=? {'AND id<?' if before else ''} ORDER BY id DESC LIMIT 80",
                                   (me["id"], before) if before else (me["id"],))}

    def agent_history(self, me, key):
        self.ensure(me)
        uid = me["id"]
        a = self._agent(uid, key)
        lines = self.db.q("SELECT manager_key, since, ended, by, reason FROM og_lines WHERE user_id=? AND agent_key=? ORDER BY id DESC LIMIT 30", (uid, key))
        missions = self.db.q("""SELECT m.id, m.name, m.status, m.manager_key, a.role, a.since, a.released FROM og_assign a JOIN og_missions m ON m.id=a.mission_id
                                WHERE a.user_id=? AND a.agent_key=? ORDER BY a.id DESC LIMIT 30""", (uid, key))
        perf = self.db.q("SELECT ts, score, evidence FROM og_perf WHERE user_id=? AND agent_key=? ORDER BY ts DESC LIMIT 20", (uid, key))
        return {"key": key, "ident": a["ident"], "lines": lines, "missions": missions, "perf": perf}

    # ---------- the authority question other systems can ask ----------
    def level(self, uid, key):
        """An agent's execution level, or None when the organization doesn't know it (callers then keep their own rules)."""
        r = self.db.q("SELECT autonomy FROM og_agents WHERE user_id=? AND key=? AND status='active'", (uid, key), one=True)
        return r["autonomy"] if r else None

    def allowed(self, uid, key, level, action=None):
        """'yes', 'approval' or 'no' for an agent doing work at `level` (and maybe a locked action)."""
        have = self.level(uid, key)
        if have is not None and have < level: return "no"
        return "approval" if action in LOCKED or level >= APPROVAL_FROM else "yes"

    def start(self):
        if TICK <= 0: return
        def loop():
            while not self.stopped.wait(TICK):
                try: self.tick()
                except Exception: log.exception("organization tick")  # noqa: BLE001
        threading.Thread(target=loop, daemon=True, name="organization").start()


# ---------- API ----------
class ChangeIn(BaseModel):
    op: str = Field(max_length=40)
    p: dict = Field(default_factory=dict)


class ProposeIn(BaseModel):
    kind: str = Field(max_length=40)
    p: dict = Field(default_factory=dict)


class DecideIn(BaseModel):
    ok: bool
    note: str = Field("", max_length=400)


DIRECT_OPS = ("settings", "set_ceo", "add_unit", "edit_unit", "set_manager", "dissolve", "move_agent", "profile", "autonomy", "promote", "retitle",
              "add_mission", "assign", "release", "end_mission", "mission_manager", "delegate", "task",
              "portfolio", "sponsor", "affiliation", "assign_unit", "release_unit", "budget")


def build(db, require, hub):
    r = APIRouter(prefix="/api/org")
    gate = hub.gate if hub else (lambda me: me)
    o = Organization(db, hub) if ENABLED else None
    r.state = {"org": o}

    def user(req):
        if not o: raise HTTPException(404, "The organization is turned off on this server.")
        return gate(require(req))

    @r.get("")
    def view(req: Request): return o.view(user(req))

    @r.post("/change")
    def change(b: ChangeIn, req: Request):
        me = user(req)
        if b.op not in DIRECT_OPS: raise HTTPException(400, "Unknown change.")
        res = o.apply(me, b.op, b.p)
        return {"result": res, "view": o.view(me)}

    @r.post("/propose")
    def propose(b: ProposeIn, req: Request):
        me = user(req)
        return {**o.propose(me, b.kind, b.p, b.p.get("by") if b.p.get("by") in ("atlas", "performance") else None), "view": o.view(me)}

    @r.post("/requests/{rid}")
    def decide(rid: int, b: DecideIn, req: Request):
        me = user(req)
        return {**o.decide(me, rid, b.ok, b.note), "view": o.view(me)}

    @r.get("/missions/{mid}/recommend")
    def recommend(mid: int, req: Request): return o.recommend(user(req), mid)

    @r.post("/performance")
    def perf(req: Request):
        me = user(req)
        return {**o.compute_perf(me), "view": o.view(me)}

    @r.get("/recommendations")
    def recs(req: Request): return o.recommendations(user(req))

    @r.get("/agents/{key}/history")
    def history(key: str, req: Request): return o.agent_history(user(req), key)

    @r.get("/audit")
    def audit(req: Request, before: int | None = None): return o.audit(user(req), before)

    @r.get("/knowledge")
    def knowledge(req: Request): return o.knowledge(user(req))

    @r.get("/units/{unit_id}/specialists")
    def specialists(unit_id: int, req: Request, dept: int, skills: str = ""):
        return o.specialists(user(req), unit_id, dept, [s.strip() for s in skills.split(",") if s.strip()][:12])

    @r.get("/access")
    def access(req: Request, key: str, unit: int):
        """May this agent read this unit's data? (Its scope: what it manages, its home and team, its assignments.)"""
        me = user(req)
        o.ensure(me)
        return {"key": key, "unit": unit, "allowed": o.may_access(me["id"], key, unit), "level": o.scoped_level(me["id"], key, unit)}

    return r
