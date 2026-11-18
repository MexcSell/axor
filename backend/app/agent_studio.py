"""Agent Operations (agent-studio.js): one workspace over every agent AXoR already has, instead of a fifth agent system.

- Systems read here, each in its own tables and with its own access rules: your agents and the built-in ones (agent_hub.py,
  agents.py, ops_agents.py), the Company's registry (company.py, company_agents.py), Workforce (workforce.py), Competition teams
  (mining_work.py), the Workflow's engineers (mining_bench.py, mining_loadout.py; administrators) and Agent HQ (hq.py;
  administrators). An agent is addressed as "<system>:<id>"; ids are never mixed between systems.
- `GET /api/studio` Overview and Live operations: every agent with its state, what runs now, what failed in the last day, the
  approval queue (the Approval Center's, command.py), tokens by system and the activity feed.
- `GET /api/studio/agents/{key}` the Agent Studio: one payload with overview, instructions, skills, tools, memory, tasks,
  evaluations (metrics from the runs, by version), versions and activity, plus where the agent is managed.
- `GET /api/studio/traces/{key}` one run's execution trace: Workforce and Competition-team spans, Company task messages, an
  Agent HQ round's events, or a chat's tool calls.
- Your own agents (the agent hub's) are the only ones changed here: every save becomes a version (aos_versions), a version can
  be restored, and a draft can be tried on one message before it's saved (`POST …/test`, nothing kept but the token count).
  The other systems' agents are changed on their own pages, where their approval rules live; the Studio links there.

Nothing here approves anything, and nothing runs except a test you start.
"""
import json, logging, time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from . import agent_core, company, hq, mining, workforce
from .agent_hub import BASE, DEVOPS_TOOLS, EXTRA, REMEMBER, SOURCE_TOOLS, STUDY_BASE, AgentIn
from .agents import run_loop, view_items
from .llm import LLMError
from .mining import _clip
try: from . import mcp_hub  # Tools & MCP: the MCP tools an agent was given show in its Tools tab
except ImportError: mcp_hub = None

def _mcp_tools(scope, me):
    return [{"name": call, "label": f"{server} · {tool}", "enabled": True, "kind": "mcp"} for server, tool, call in mcp_hub.listed(scope, me)] if mcp_hub else []

CACHE = 8
DAY = 86400
SYSTEMS = {"hub": "Your agents", "builtin": "Built-in", "company": "Company", "workforce": "Workforce", "teams": "Competition teams",
           "workflow": "Workflow", "hq": "Agent HQ", "team": "Project team", "missions": "Mission OS", "marketplace": "Agent Marketplace", "longtask": "Long tasks", "other": "Other"}
GO = {"hub": {"view": "agents"}, "builtin": {"view": "agents"}, "company": {"view": "company", "tab": "agents"}, "workforce": {"view": "workforce"},
      "teams": {"view": "teams"}, "workflow": {"view": "teams"}, "hq": {"view": "hq"}, "team": {"view": "workspace", "tab": "team"},
      "missions": {"view": "mos"}, "longtask": {"view": "infiagent"}, "other": {"view": "studio"}}
TRACED = ("wf", "mw", "co", "hq")  # runs whose own system keeps a trace; every other ledger run is traced from its ac_runs row
OK, BAD = ("done", "succeeded", "success", "merged", "pass"), ("failed", "error", "timeout")
# llm_usage sources → (system, label)
USAGE = {"chat": ("hub", "Agent chats"), "workspace": ("hub", "Agent chats"), "study": ("hub", "Study tutors"), "test": ("hub", "Studio tests"),
         "company": ("company", "Company"), "workforce": ("workforce", "Workforce"), "mining": ("teams", "My subnets & teams"), "team": ("teams", "Project team"),
         "hq": ("hq", "Agent HQ"), "infiagent": ("other", "Long tasks")}
log = logging.getLogger("studio")


def _j(x, default):
    try: return json.loads(x) if x else default
    except (TypeError, ValueError): return default


def metrics(runs):
    """Runs (status, started, finished, tokens, score?, attempt?) → success rate, first-attempt success, latency, tokens per success."""
    done = [r for r in runs if r.get("status") in OK]
    bad = [r for r in runs if r.get("status") in BAD]
    ended = done + bad
    lat = [r["finished"] - r["started"] for r in ended if r.get("finished") and r.get("started") and r["finished"] >= r["started"]]
    first = [r for r in ended if r.get("attempt") is not None]
    scores = [r["score"] for r in runs if r.get("score") is not None]
    toks = sum(r.get("tokens") or 0 for r in runs) if any(r.get("tokens") is not None for r in runs) else None  # the Workflow counts dollars, not tokens
    return {"runs": len(runs), "done": len(done), "failed": len(bad),
            "success_rate": round(len(done) / len(ended), 3) if ended else None,
            "first_attempt": round(sum(1 for r in first if r["status"] in OK and (r["attempt"] or 0) <= 1) / len(first), 3) if first else None,
            "avg_latency": round(sum(lat) / len(lat), 1) if lat else None, "tokens": toks,
            "tokens_per_success": round(toks / len(done)) if done and toks is not None else None, "avg_score": round(sum(scores) / len(scores), 2) if scores else None}


def by_version(runs):
    """Metrics per version, oldest first, each compared with the version before it (a drop in success rate is a regression)."""
    out, prev = [], None
    for v in sorted({r["version"] for r in runs if r.get("version") is not None}):
        m = {"version": v, **metrics([r for r in runs if r.get("version") == v])}
        if prev and m["success_rate"] is not None and prev["success_rate"] is not None:
            m["delta"] = round(m["success_rate"] - prev["success_rate"], 3)
            m["regression"] = m["delta"] < -0.05 and m["done"] + m["failed"] >= 3
        out.append(m); prev = m
    return out


def _agent(system, id_, name, role="", team="", status="active", state="idle", **kw):
    return {"key": f"{system}:{id_}", "system": system, "system_label": SYSTEMS[system], "id": id_, "name": name or f"#{id_}", "role": role or "",
            "team": team or "", "status": status or "active", "state": state, "tokens_week": 0, "last": None, "icon": "bot", "color": "slate",
            "go": GO[system], **kw}


def _blank():
    return {"instructions": {"text": "", "note": ""}, "skills": [], "tools": [], "memory": [], "tasks": [], "runs": [], "versions": [], "activity": [],
            "settings": [], "evaluations": {"items": []}}


class TestIn(BaseModel):
    message: str
    instructions: str | None = None  # a draft; empty = the saved instructions
    version: int | None = None       # or a saved version's instructions
    model: str | None = None
    effort: str = "medium"


class BudgetIn(BaseModel):
    daily_tokens: int | None = None  # None or 0: no limit
    unlimited: bool | None = None    # true: run without a daily cap, acknowledged; false: take that back (limits are never touched by it)


class RestoreIn(BaseModel):
    version: int


class Studio:
    def __init__(self, db, ov, hub, co=None, cmd=None):
        self.db, self.ov, self.hub, self.co, self.cmd = db, ov, hub, co, cmd
        self.cache = {}
        self.restoring = set()  # agent ids being restored: their save is versioned by restore() with its own note
        db.q("""CREATE TABLE IF NOT EXISTS aos_versions (id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id INTEGER, version INTEGER, snap TEXT,
                  note TEXT, author TEXT, created REAL, UNIQUE (agent_id, version))""")
        db.q("""CREATE TABLE IF NOT EXISTS aos_tests (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, agent_id INTEGER, version INTEGER,
                  draft INTEGER, message TEXT, answer TEXT, model TEXT, tokens INTEGER, ms INTEGER, error TEXT, ts REAL)""")
        if hub is not None: hub.on_update = self._saved

    # ---------- plumbing ----------
    def _has(self, table):
        return bool(self.db.q("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,), one=True))

    def _gate(self, me):
        if not self.ov._agents_ok(me): raise HTTPException(403, "Agents aren't turned on for your account. An administrator can turn them on for members.")
        return me

    @staticmethod
    def _admin(me):
        return me.get("role") == "admin"

    def _try(self, out, label, fn, *a):
        try: return fn(*a)
        except HTTPException: raise
        except Exception as e:  # noqa: BLE001 - one source failing leaves the rest
            log.exception("studio %s", label)
            out.setdefault("errors", []).append(f"{label}: {_clip(str(e), 200)}")

    def _company(self, me):
        return self.co._company(me, create=False) if self.co is not None and company.ENABLED else None

    def _comps(self, me):
        if not (mining.ENABLED and self._has("mw_comps")): return []
        return self.db.q("""SELECT w.id, w.number, w.name, c.netuid FROM mw_comps w JOIN mh_campaigns c ON c.id=w.campaign_id
                            WHERE c.user_id=? AND w.status!='closed' ORDER BY c.netuid, w.number""", (me["id"],))

    @staticmethod
    def _comp_label(w):
        return f"SN{w['netuid']} · {w['name'] or ('Competition ' + str(w['number']))}"

    def _flows(self, me):
        if not (self._admin(me) and mining.ENABLED and self._has("mb_flows")): return []
        return self.db.q("SELECT id, comp_id FROM mb_flows WHERE user_id=?", (me["id"],))

    def _hq_on(self, me):
        return self._admin(me) and hq.ENABLED and self._has("hq_agents")

    # ---------- the directory ----------
    def directory(self, me):
        out, week = {"errors": []}, time.time() - 7 * DAY
        agents = []
        for label, fn in (("Your agents", self._dir_hub), ("Built-in", self._dir_builtin), ("Company", self._dir_company),
                          ("Workforce", self._dir_workforce), ("Competition teams", self._dir_teams), ("Workflow", self._dir_workflow),
                          ("Agent HQ", self._dir_hq)):
            got = self._try(out, label, fn, me, week)
            if got: agents += got
        return agents, out["errors"]

    def _dir_hub(self, me, week):
        if self.hub is None: return []
        lists = self.hub.list(me)
        toks = {r["agent_id"]: r["n"] for r in self.db.q("SELECT agent_id, SUM(tokens) n FROM llm_usage WHERE user_id=? AND ts>? AND agent_id IS NOT NULL GROUP BY agent_id",
                                                         (me["id"], week))}
        seen, out = set(), []
        for group in ("mine", "shared", "from_directory"):
            for a in lists.get(group, []):
                if a["id"] in seen: continue
                seen.add(a["id"])
                x = _agent("hub", a["id"], a["name"], a["role"], "Yours" if a["mine"] else f"By {a['owner']}", a["status"],
                           "paused" if a["status"] != "live" else "idle", icon=a["icon"], color=a["color"], face=a.get("face"), mine=a["mine"])
                x["tokens_week"], x["last"] = toks.get(a["id"], 0), a.get("my_last_chat") or a.get("last_activity")
                x["go"] = {"view": "agents", "agent": a["id"]}
                out.append(x)
        return out

    def _dir_builtin(self, me, week):
        if self.hub is None: return []
        out = []
        last = {r["agent"]: r["t"] for r in self.db.q("SELECT agent, MAX(updated) t FROM agent_conversations WHERE user_id=? GROUP BY agent", (me["id"],))}
        for b in self.hub.builtins.values():
            if b.get("admin_only") and not self._admin(me): continue
            x = _agent("builtin", b["id"], b["name"], b.get("role"), "AXoR", "live", "idle", icon=b.get("icon") or "bot", color=b.get("color") or "slate")
            x["last"], x["go"] = last.get(b["id"]), {"view": "agents", "agent": b["id"]}
            out.append(x)
        return out

    def _dir_company(self, me, week):
        c = self._company(me)
        if not c: return []
        cid = c["id"]
        busy = {r["agent_id"]: r["n"] for r in self.db.q("""SELECT m.agent_id, COUNT(*) n FROM co_members m JOIN co_teams t ON t.id=m.team_id JOIN co_tasks k ON k.team_id=t.id
                                                             WHERE t.company_id=? AND k.status='running' GROUP BY m.agent_id""", (cid,))}
        failed = {r["agent_id"] for r in self.db.q("""SELECT DISTINCT m.agent_id FROM co_members m JOIN co_tasks k ON k.team_id=m.team_id
                                                      WHERE k.company_id=? AND k.status='failed' AND COALESCE(k.finished, k.created)>?""", (cid, time.time() - DAY))}
        toks = {r["agent_id"]: r["n"] for r in self.db.q("SELECT agent_id, SUM(tokens) n FROM co_usage WHERE company_id=? AND ts>? GROUP BY agent_id", (cid, week))}
        divs = {d["id"]: d["name"] for d in self.db.q("SELECT id, name FROM co_divisions WHERE company_id=?", (cid,))}
        out = []
        for a in self.db.q("SELECT id, name, title, category, division_id, status, updated FROM co_agents WHERE company_id=? AND status!='archived' ORDER BY lead DESC, id", (cid,)):
            st = "working" if busy.get(a["id"]) else "attention" if a["id"] in failed else "paused" if a["status"] == "paused" else "idle"
            x = _agent("company", a["id"], a["name"], a["title"] or a["category"], divs.get(a["division_id"], ""), a["status"], st, icon="layers", color="blue")
            x["tokens_week"], x["last"] = toks.get(a["id"], 0), a["updated"]
            out.append(x)
        return out

    def _dir_workforce(self, me, week):
        if not (workforce.ENABLED and self._has("wf_agents")): return []
        uid = me["id"]
        run = {r["agent"] for r in self.db.q("SELECT DISTINCT agent FROM wf_runs WHERE user_id=? AND status='running'", (uid,))}
        bad = {r["agent"] for r in self.db.q("SELECT DISTINCT agent FROM wf_runs WHERE user_id=? AND status='failed' AND COALESCE(finished, started)>?", (uid, time.time() - DAY))}
        toks = {r["agent"]: (r["n"], r["t"]) for r in self.db.q("SELECT agent, SUM(tokens) n, MAX(started) t FROM wf_runs WHERE user_id=? AND started>? GROUP BY agent", (uid, week))}
        out = []
        for a in self.db.q("SELECT id, key, team, level, role, name, title, icon, color, status FROM wf_agents WHERE user_id=? AND status!='archived' ORDER BY team, level='lead' DESC, id", (uid,)):
            st = "working" if a["key"] in run else "attention" if a["key"] in bad else "paused" if a["status"] == "paused" else "idle"
            x = _agent("workforce", a["id"], a["name"], a["title"] or a["role"], workforce.TEAM_NAME.get(a["team"], (a["team"] or "").capitalize()), a["status"], st,
                       icon=a["icon"] or "bot", color=a["color"] or "slate")
            x["tokens_week"], x["last"] = toks.get(a["key"], (0, None))
            x["tokens_week"] = x["tokens_week"] or 0
            out.append(x)
        return out

    def _dir_teams(self, me, week):
        comps = self._comps(me)
        if not comps: return []
        ids = [w["id"] for w in comps]
        marks = ",".join("?" * len(ids))
        labels = {w["id"]: self._comp_label(w) for w in comps}
        live = {r["agent_id"] for r in self.db.q(f"SELECT DISTINCT agent_id FROM mw_runs WHERE comp_id IN ({marks}) AND status IN ('queued','running')", ids)}
        bad = {r["agent_id"] for r in self.db.q(f"SELECT DISTINCT agent_id FROM mw_runs WHERE comp_id IN ({marks}) AND status='failed' AND COALESCE(finished, started)>?", ids + [time.time() - DAY])}
        blocked = {r["agent_id"] for r in self.db.q(f"SELECT DISTINCT agent_id FROM mw_tasks WHERE comp_id IN ({marks}) AND status IN ('review','blocked')", ids)}
        toks = {r["agent_id"]: (r["n"], r["t"]) for r in self.db.q(f"SELECT agent_id, SUM(tokens) n, MAX(started) t FROM mw_runs WHERE comp_id IN ({marks}) AND started>? GROUP BY agent_id", ids + [week])}
        out = []
        for a in self.db.q(f"SELECT id, comp_id, role, name, title, icon, color, active FROM mw_agents WHERE comp_id IN ({marks}) AND active=1 ORDER BY comp_id, head DESC, lead DESC, id", ids):
            st = "working" if a["id"] in live else "review" if a["id"] in blocked else "attention" if a["id"] in bad else "idle"
            x = _agent("teams", a["id"], a["name"], a["title"] or a["role"], labels.get(a["comp_id"], ""), "active", st, icon=a["icon"] or "bot", color=a["color"] or "slate")
            x["tokens_week"], x["last"] = toks.get(a["id"], (0, None))
            x["tokens_week"] = x["tokens_week"] or 0
            x["go"] = {"view": "teams", "wid": a["comp_id"], "sub": "team"}
            out.append(x)
        return out

    def _dir_workflow(self, me, week):
        flows = self._flows(me)
        if not flows: return []
        marks = ",".join("?" * len(flows))
        comp = {f["id"]: f["comp_id"] for f in flows}
        out = []
        for a in self.db.q(f"SELECT id, flow_id, role, name, model, on_team FROM mb_agents WHERE flow_id IN ({marks}) ORDER BY flow_id, id", [f["id"] for f in flows]):
            x = _agent("workflow", a["id"], a["name"], (a["role"] or "").capitalize(), f"Workflow #{a['flow_id']}", "active" if a["on_team"] else "off",
                       "idle" if a["on_team"] else "paused", icon="code", color="teal")
            x["go"] = {"view": "teams", "wid": comp.get(a["flow_id"]), "sub": "workflow"}
            out.append(x)
        return out

    def _dir_hq(self, me, week):
        if not self._hq_on(me): return []
        st = {r["id"]: r for r in self.db.q("SELECT id, status, errors, last_run FROM hq_agents")}
        out = []
        for a in hq.STAFF + hq.FIELD:
            s = st.get(a["id"]) or {}
            off = s.get("status") == "off"
            x = _agent("hq", a["id"], a["name"], a["title"], hq.TEAMS.get(a.get("team"), {}).get("name", "Headquarters"), s.get("status") or "on",
                       "paused" if off else "attention" if (s.get("errors") or 0) else "idle", icon=a.get("icon") or "bot", color=a.get("color") or "slate")
            x["last"] = s.get("last_run")
            out.append(x)
        return out

    # ---------- Overview and Live operations ----------
    def overview(self, me, fresh=False):
        self._gate(me)
        hit = self.cache.get(me["id"])
        if hit and not fresh and time.time() - hit[0] < CACHE: return hit[1]
        agents, errors = self.directory(me)
        self._from_ledger(me, agents)
        out = {"at": time.time(), "admin": self._admin(me), "agents": agents, "errors": errors, "running": [], "failed": [], "activity": [],
               "approvals": [], "tokens": [], "systems": {}}
        for label, fn in (("Live runs", self._runs), ("Activity", self._activity), ("Approvals", self._approvals), ("Tokens", self._tokens)):
            self._try(out, label, fn, me, out)
        for a in agents:
            s = out["systems"].setdefault(a["system"], {"label": a["system_label"], "agents": 0, "working": 0, "go": GO[a["system"]]})
            s["agents"] += 1; s["working"] += a["state"] == "working"
        out["counts"] = {"agents": len(agents), "working": sum(a["state"] == "working" for a in agents),
                         "review": sum(a["state"] == "review" for a in agents) + sum(1 for x in out["running"] if x["status"] in ("review", "waiting")),
                         "attention": sum(a["state"] == "attention" for a in agents), "running": len(out["running"]), "failed": len(out["failed"]),
                         "approvals": len(out["approvals"]), "tokens_week": sum(t["tokens"] for t in out["tokens"])}
        self.cache[me["id"]] = (time.time(), out)
        return out

    def _from_ledger(self, me, agents):
        """Each system's adapter decides which agents you see; the agent core's ledger says which are at work and what they spent."""
        core = agent_core.get()
        if core is None: return
        try: core.sync()
        except Exception as e:  # noqa: BLE001 - the mirror never fails the page
            log.warning("agent core sync: %s", e)
        st = core.agent_stats(self._owners(me), time.time() - 7 * DAY)
        for a in agents:
            x = st.get(a["key"])
            if not x: continue
            if x["running"] and a["state"] in ("idle", "attention"): a["state"] = "working"
            elif x["failed"] and a["state"] == "idle": a["state"] = "attention"
            if x["tokens"]: a["tokens_week"] = x["tokens"]
            a["last"] = max(a.get("last") or 0, x["last"] or 0) or None

    def _owners(self, me):
        return (me["id"], 0) if self._hq_on(me) else (me["id"],)  # Agent HQ runs as account 0

    def _runs(self, me, out):
        """Running runs everywhere and the last day's failures, from the agent core's run ledger (agent_core.py), each with the
        key of its trace: its own system's where it keeps one, else the ledger row's."""
        if agent_core.get() is None: return
        names = {a["key"]: a["name"] for a in out["agents"]}
        for r in agent_core.get().runs(self._owners(me), time.time() - DAY, ("running", "failed", "lost"), 200):
            kind = (r["ref"] or "").partition(":")[0]
            system = r["system"] if r["system"] in SYSTEMS else "other"
            item = {"trace": r["ref"] if kind in TRACED else f"ac:{r['id']}", "agent_key": r["agent_key"] or "",
                    "agent": names.get(r["agent_key"], (r["agent_key"] or ":").split(":", 1)[1]) if r["agent_key"] else SYSTEMS[system],
                    "title": _clip(r["title"] or r["kind"] or "", 160), "status": "failed" if r["status"] == "lost" else r["status"], "started": r["started"],
                    "finished": r["finished"], "tokens": r["tokens"] or 0, "error": _clip(r["error"] or "", 300), "where": SYSTEMS[system], "go": GO[system], "system": system}
            (out["running"] if r["status"] == "running" else out["failed"]).append(item)
        out["running"].sort(key=lambda x: -(x["started"] or 0))
        out["failed"].sort(key=lambda x: -(x["finished"] or x["started"] or 0))

    def _activity(self, me, out):
        uid, items = me["id"], []
        if workforce.ENABLED and self._has("wf_events"):
            for e in self.db.q("SELECT ts, agent, kind, text, tokens FROM wf_events WHERE user_id=? ORDER BY id DESC LIMIT 25", (uid,)):
                items.append({"ts": e["ts"], "system": "workforce", "who": e["agent"] or "Workforce", "kind": e["kind"], "text": _clip(e["text"] or "", 240), "go": {"view": "workforce"}})
        comps = self._comps(me)
        if comps and self._has("mw_events"):
            ids, labels = [w["id"] for w in comps], {w["id"]: self._comp_label(w) for w in comps}
            names = {a["id"]: a["name"] for a in self.db.q(f"SELECT id, name FROM mw_agents WHERE comp_id IN ({','.join('?' * len(ids))})", ids)}
            for e in self.db.q(f"SELECT comp_id, ts, agent_id, kind, text FROM mw_events WHERE comp_id IN ({','.join('?' * len(ids))}) ORDER BY id DESC LIMIT 25", ids):
                items.append({"ts": e["ts"], "system": "teams", "who": names.get(e["agent_id"], labels.get(e["comp_id"], "")), "kind": e["kind"], "text": _clip(e["text"] or "", 240),
                              "go": {"view": "teams", "wid": e["comp_id"], "sub": "team"}})
        c = self._company(me)
        if c and self._has("co_agent_activity"):
            names = {a["id"]: a["name"] for a in self.db.q("SELECT id, name FROM co_agents WHERE company_id=?", (c["id"],))}
            for e in self.db.q("SELECT ts, agent_id, kind, summary, tokens FROM co_agent_activity WHERE company_id=? ORDER BY id DESC LIMIT 25", (c["id"],)):
                items.append({"ts": e["ts"], "system": "company", "who": names.get(e["agent_id"], "Company"), "kind": e["kind"], "text": _clip(e["summary"] or "", 240),
                              "go": {"view": "company", "tab": "agents"}})
        if c and self._has("co_audit"):
            for e in self.db.q("SELECT ts, actor, action, target_type FROM co_audit WHERE company_id=? AND actor_type='agent' ORDER BY id DESC LIMIT 15", (c["id"],)):
                items.append({"ts": e["ts"], "system": "company", "who": e["actor"] or "Company", "kind": e["action"], "text": f"{e['action']} · {e['target_type'] or ''}".strip(" ·"),
                              "go": {"view": "company"}})
        if self._hq_on(me) and self._has("hq_events"):
            for e in self.db.q("SELECT ts, agent, kind, text, tokens FROM hq_events ORDER BY id DESC LIMIT 20"):
                items.append({"ts": e["ts"], "system": "hq", "who": e["agent"] or "Agent HQ", "kind": e["kind"], "text": _clip(e["text"] or "", 240), "go": {"view": "hq"}})
        out["activity"] = sorted(items, key=lambda x: -(x["ts"] or 0))[:50]

    def _approvals(self, me, out):
        if self.cmd is None: return
        v = self.cmd.view(me)
        out["approvals"] = v.get("pending", [])[:40]

    def _tokens(self, me, out):
        """The last 7 days by system, from the agent core's run ledger: every model call of every system lands there."""
        if agent_core.get() is None: return
        by = agent_core.get().tokens_by_system(self._owners(me), time.time() - 7 * DAY)
        out["tokens"] = sorted(({"system": k if k in SYSTEMS else "other", "label": SYSTEMS.get(k, "Other"), "tokens": n} for k, n in by.items() if n),
                               key=lambda r: -r["tokens"])
        out["budget"] = agent_core.get().budget(me["id"])

    # ---------- the Agent Studio ----------
    def agent(self, me, key):
        self._gate(me)
        system, _, id_ = key.partition(":")
        fn = {"hub": self._hub, "builtin": self._builtin, "company": self._co, "workforce": self._wf, "teams": self._mw,
              "workflow": self._mb, "hq": self._hq}.get(system)
        if not fn or not id_: raise HTTPException(404, "Agent not found.")
        d = fn(me, id_)
        runs = d.pop("runs", [])
        d["evaluations"].update(metrics=metrics(runs), versions=by_version(runs))
        d["recent_runs"] = sorted(runs, key=lambda r: -(r.get("started") or 0))[:30]
        d.setdefault("can_edit", False); d.setdefault("can_test", False)
        return d

    def _base(self, a, about=""):
        return {**a, "about": about or "", **_blank()}

    def _find(self, me, system, id_):
        agents, _ = self.directory(me)
        a = next((x for x in agents if x["key"] == f"{system}:{id_}"), None)
        if not a: raise HTTPException(404, "Agent not found.")
        return a

    # your agents: the agent hub's
    def _hub(self, me, id_):
        if self.hub is None: raise HTTPException(404, "Agent not found.")
        try: aid = int(id_)
        except ValueError: raise HTTPException(404, "Agent not found.")
        a = self.hub._usable(aid, me)
        try: row = self._find(me, "hub", aid)
        except HTTPException:  # a directory agent you haven't added: usable, just not in your list
            row = _agent("hub", aid, a["name"], a["role"], "Agent directory", a["status"], "paused" if a["status"] != "live" else "idle",
                         icon=a["icon"] or "bot", color=a["color"] or "slate", mine=False)
        d = self._base(row, a["description"])
        mine = a["owner_id"] == me["id"]
        d.update(can_edit=mine, can_test=a["status"] == "live", kind=a["kind"] or "", examples=a["examples"], owner=row["team"])
        d["instructions"] = {"text": a["instructions"] if mine else "", "note": "" if mine else "Only its creator sees and changes its instructions."}
        skills = self.hub.skills(me)
        allsk = {s["id"]: s for s in skills["builtin"] + skills["custom"]}
        d["skills"] = [{"id": s, "name": allsk[s]["name"] if s in allsk else s, "description": allsk.get(s, {}).get("description", ""), "on": True} for s in a["skills"]]
        d["skill_catalog"] = [{"id": s["id"], "name": s["name"], "description": s.get("description", "")} for s in skills["builtin"] + skills["custom"]][:80] if mine else []
        d["tools"] = ([{"name": k, "label": v, "enabled": True, "kind": "read"} for k, v in self.hub._labels(a).items()] + [{"name": "remember", "label": "Remember facts about you", "enabled": True, "kind": "write"}]
                      + _mcp_tools(f"hub:{aid}", me))
        d["memory"] = [{"text": m["text"], "source": m["source"], "ts": m["created"]} for m in
                       self.db.q("SELECT text, source, created FROM agent_memory WHERE agent_id=? AND user_id=? ORDER BY created DESC LIMIT 60", (aid, me["id"]))]
        convs = self.db.q("SELECT id, title, created, updated, messages FROM agent_conversations WHERE agent=? AND user_id=? ORDER BY updated DESC LIMIT 40", (f"custom:{aid}", me["id"]))
        runs = []
        for c in convs:
            msgs = _j(c["messages"], [])
            toks = sum((m.get("meta") or {}).get("tokens") or 0 for m in msgs if m.get("role") == "assistant")
            turns = sum(1 for m in msgs if m.get("role") == "user" and any(b.get("type") == "text" for b in (m["content"] if isinstance(m["content"], list) else [])))
            rates = [(m.get("meta") or {}).get("rating") for m in msgs if (m.get("meta") or {}).get("rating")]
            runs.append({"trace": f"chat:{aid}:{c['id']}", "title": c["title"], "status": "done", "started": c["created"], "finished": c["updated"], "tokens": toks,
                         "score": round(sum(rates) / len(rates), 2) if rates else None, "detail": f"{turns} message{'' if turns == 1 else 's'}"})
        d["tasks"] = [{"title": r["title"], "status": "chat", "ts": r["finished"], "tokens": r["tokens"], "trace": r["trace"]} for r in runs]
        d["runs"] = []  # chats aren't tasks: success and latency don't apply; ratings and tests are the evaluation
        tests = self.db.q("SELECT version, draft, message, answer, model, tokens, ms, error, ts FROM aos_tests WHERE agent_id=? AND user_id=? ORDER BY id DESC LIMIT 20", (aid, me["id"]))
        rated = [r for r in runs if r["score"] is not None]
        d["evaluations"] = {"items": [{"title": f"Test · {'draft' if t['draft'] else 'v' + str(t['version'])}", "detail": _clip(t["message"], 160), "score": None,
                                       "status": "failed" if t["error"] else "done", "ts": t["ts"], "tokens": t["tokens"], "ms": t["ms"]} for t in tests]
                            + [{"title": f"Rated chat · {r['title']}", "detail": "", "score": r["score"], "status": "done", "ts": r["finished"]} for r in rated[:20]],
                            "note": "Chat ratings (👍 = 1, 👎 = −1) and the tests you run here. Benchmarks with fixed test sets live in Agent evaluation."}
        d["versions"] = self._versions(aid) if mine else []
        d["activity"] = [{"ts": r["ts"], "kind": "tokens", "text": f"{r['source']} · {r['model'] or 'model'}", "tokens": r["tokens"]} for r in
                         self.db.q("SELECT ts, source, model, tokens FROM llm_usage WHERE user_id=? AND agent_id=? ORDER BY id DESC LIMIT 40", (me["id"], aid))]
        d["settings"] = [["Status", a["status"]], ["Shared in the directory", "yes" if a["in_directory"] else "no"], ["Kind", "Study tutor" if a["kind"] == "study" else "Subnet data"],
                         ["Model", "The one picked in the chat (shared model menu)"], ["Tokens, all time", a["tokens"] or 0]]
        d["manage"] = [{"label": "Chat with it", "go": {"view": "agents", "agent": aid}}]
        return d

    def _builtin(self, me, id_):
        b = (self.hub.builtins if self.hub is not None else {}).get(id_)
        if not b or (b.get("admin_only") and not self._admin(me)): raise HTTPException(404, "Agent not found.")
        row = self._find(me, "builtin", id_)
        d = self._base(row, b.get("description", ""))
        d["instructions"] = {"text": "", "note": "Built into AXoR; its instructions are part of the code."}
        d["tools"] = [{"name": x, "label": x, "enabled": True, "kind": "write" if "approve" in x.lower() or "proposal" in x.lower() else "read"} for x in b.get("abilities", [])]
        convs = self.db.q("SELECT id, title, created, updated FROM agent_conversations WHERE agent=? AND user_id=? ORDER BY updated DESC LIMIT 30", (id_, me["id"]))
        d["tasks"] = [{"title": c["title"], "status": "chat", "ts": c["updated"], "tokens": None, "trace": f"chat:{id_}:{c['id']}"} for c in convs]
        if self._has("agent_proposals"):
            d["evaluations"]["items"] = [{"title": f"Proposal · {p['kind']}", "detail": _clip(p["reason"] or "", 160), "status": p["status"], "ts": p["decided"] or p["created"]}
                                         for p in self.db.q("""SELECT p.kind, p.reason, p.status, p.created, p.decided FROM agent_proposals p JOIN agent_conversations c ON c.id=p.conversation_id
                                                               WHERE c.agent=? AND c.user_id=? ORDER BY p.id DESC LIMIT 30""", (id_, me["id"]))]
            d["evaluations"]["note"] = "Its proposals and what you decided. Each change it proposes waits for your approval in the chat."
        d["manage"] = [{"label": "Chat with it", "go": {"view": "agents", "agent": id_}}]
        return d

    def _co(self, me, id_):
        c = self._company(me)
        if not c: raise HTTPException(404, "Agent not found.")
        a = self.db.q("SELECT * FROM co_agents WHERE id=? AND company_id=?", (id_, c["id"]), one=True)
        if not a: raise HTTPException(404, "Agent not found.")
        row = self._find(me, "company", a["id"])
        d = self._base(row, a["about"])
        cfg = self.db.q("SELECT * FROM co_agent_config WHERE agent_id=?", (a["id"],), one=True) if self._has("co_agent_config") else None
        d["instructions"] = {"text": "\n\n".join(x for x in ((cfg or {}).get("mission") and "Mission: " + cfg["mission"], (cfg or {}).get("instructions")) if x),
                             "note": "Mission and standing instructions from its Company workspace."}
        d["skills"] = [{"id": k, "name": k.replace("_", " ").capitalize(), "description": f"Level {v} of 5", "on": True} for k, v in _j(a["skills"], {}).items()]
        perms = _j(a["permissions"], {})
        chat = {r["tool"]: bool(r["enabled"]) for r in self.db.q("SELECT tool, enabled FROM co_agent_tool_permissions WHERE agent_id=?", (a["id"],))} if self._has("co_agent_tool_permissions") else {}
        d["tools"] = ([{"name": p, "label": p.replace("_", " "), "enabled": True, "kind": kind} for kind in ("read", "write", "execute") for p in perms.get(kind, [])]
                      + [{"name": t, "label": f"Chat · {t}", "enabled": on, "kind": "chat"} for t, on in chat.items()])
        if self._has("co_agent_memory"):
            d["memory"] = [{"text": m["body"], "source": m["source"], "ts": m["created"]} for m in
                           self.db.q("SELECT body, source, created FROM co_agent_memory WHERE agent_id=? ORDER BY id DESC LIMIT 60", (a["id"],))]
        tasks = self.db.q("""SELECT k.id, k.title, k.status, k.tokens, k.created, k.started, k.finished, k.error, m.role FROM co_tasks k JOIN co_members m ON m.team_id=k.team_id
                             WHERE k.company_id=? AND m.agent_id=? ORDER BY k.id DESC LIMIT 60""", (c["id"], a["id"]))
        d["tasks"] = [{"title": t["title"], "status": t["status"], "ts": t["finished"] or t["started"] or t["created"], "tokens": t["tokens"], "trace": f"co:{t['id']}",
                       "detail": t["role"] or ""} for t in tasks]
        d["runs"] = [{"trace": f"co:{t['id']}", "title": t["title"], "status": t["status"], "started": t["started"], "finished": t["finished"], "tokens": t["tokens"],
                      "version": cfg and None, "error": t["error"]} for t in tasks]
        items = [{"title": "Evaluator score", "detail": e["verdict"] or "", "score": e["score"], "status": e["verdict"] or "", "ts": e["ts"]} for e in
                 self.db.q("SELECT e.score, e.verdict, e.ts FROM co_evals e JOIN co_artifacts r ON r.id=e.artifact_id WHERE r.by_agent=? ORDER BY e.id DESC LIMIT 30", (a["id"],))]
        if self._has("co_agent_evaluations"):
            items += [{"title": "Your rating of a chat answer", "detail": e["note"] or "", "score": e["score"], "status": "rated", "ts": e["ts"]} for e in
                      self.db.q("SELECT score, note, ts FROM co_agent_evaluations WHERE agent_id=? ORDER BY id DESC LIMIT 30", (a["id"],))]
        d["evaluations"] = {"items": sorted(items, key=lambda x: -(x["ts"] or 0)), "note": "Evaluator scores of its deliverables and your ratings of its chat answers."}
        vers = []
        for tbl, what in (("co_agent_config_versions", "Configuration"), ("co_agent_versions", "Contract")):
            if self._has(tbl):
                vers += [{"version": v["version"], "label": f"{what} v{v['version']}", "author": v["by_actor"], "ts": v["ts"],
                          "text": json.dumps(_j(v["config"], {}), indent=1)[:4000], "current": False} for v in
                         self.db.q(f"SELECT version, config, ts, by_actor FROM {tbl} WHERE agent_id=? ORDER BY id DESC LIMIT 20", (a["id"],))]
        d["versions"] = sorted(vers, key=lambda v: -(v["ts"] or 0))
        if self._has("co_agent_activity"):
            d["activity"] = [{"ts": e["ts"], "kind": e["kind"], "text": e["summary"], "tokens": e["tokens"]} for e in
                             self.db.q("SELECT ts, kind, summary, tokens FROM co_agent_activity WHERE agent_id=? ORDER BY id DESC LIMIT 50", (a["id"],))]
        if cfg:
            d["settings"] = [["Model profile", cfg["profile"]], ["Own model", cfg["model"] or "the company's"], ["Autonomy", cfg["autonomy"]],
                             ["Monthly token budget", cfg["budget"] or "none"], ["Configuration version", cfg["version"]]]
        d["settings"] += [["Status", a["status"]], ["Stage", a["stage"] or ""], ["Max parallel tasks", a["max_load"]], ["Contract version", a["version"]]]
        d["manage"] = [{"label": "Open its Company workspace", "go": {"view": "company", "tab": "agents", "agent": a["id"]}}]
        return d

    def _wf(self, me, id_):
        if not (workforce.ENABLED and self._has("wf_agents")): raise HTTPException(404, "Agent not found.")
        a = self.db.q("SELECT * FROM wf_agents WHERE id=? AND user_id=?", (id_, me["id"]), one=True)
        if not a: raise HTTPException(404, "Agent not found.")
        row = self._find(me, "workforce", a["id"])
        d = self._base(row, a["job"])
        vers = self.db.q("SELECT version, instructions, note, source, author, created FROM wf_versions WHERE agent_id=? ORDER BY version DESC", (a["id"],))
        cur = next((v for v in vers if v["version"] == a["version"]), vers[0] if vers else None)
        d["instructions"] = {"text": cur["instructions"] if cur else "", "note": f"Version {a['version']}. Changes go through Workforce → Improvements, with trials and your approval."}
        d["tools"] = [{"name": t, "label": t.replace("_", " "), "enabled": True, "kind": "read"} for t in _j(a["tools"], [])]
        d["memory"] = [{"text": m["text"], "source": m["kind"], "ts": m["updated"] or m["created"]} for m in
                       self.db.q("SELECT kind, text, created, updated FROM wf_memory WHERE user_id=? AND status='active' AND (team=? OR team IS NULL OR team='') ORDER BY id DESC LIMIT 40",
                                 (me["id"], a["team"]))]
        asg = self.db.q("""SELECT s.id, s.mission_id, s.title, s.status, s.attempt, s.version, s.tokens, s.created, s.finished, m.title mission FROM wf_assignments s
                           JOIN wf_missions m ON m.id=s.mission_id WHERE m.user_id=? AND s.agent=? ORDER BY s.id DESC LIMIT 60""", (me["id"], a["key"])) \
            if "created" in {c["name"] for c in self.db.q("PRAGMA table_info(wf_assignments)")} else \
            self.db.q("""SELECT s.id, s.mission_id, s.title, s.status, s.attempt, s.version, s.tokens, NULL created, NULL finished, m.title mission FROM wf_assignments s
                         JOIN wf_missions m ON m.id=s.mission_id WHERE m.user_id=? AND s.agent=? ORDER BY s.id DESC LIMIT 60""", (me["id"], a["key"]))
        runs = self.db.q("""SELECT r.id, r.assignment_id, r.mission_id, r.step, r.task, r.status, r.started, r.finished, r.tokens, r.score, r.error, r.model, s.attempt, s.version
                            FROM wf_runs r LEFT JOIN wf_assignments s ON s.id=r.assignment_id WHERE r.user_id=? AND r.agent=? ORDER BY r.id DESC LIMIT 100""", (me["id"], a["key"]))
        d["tasks"] = [{"title": s["title"], "status": s["status"], "ts": s["finished"] or s["created"], "tokens": s["tokens"], "detail": s["mission"],
                       "trace": next((f"wf:{r['id']}" for r in runs if r["assignment_id"] == s["id"]), None)} for s in asg]
        d["runs"] = [{"trace": f"wf:{r['id']}", "title": r["task"] or r["step"], "status": r["status"], "started": r["started"], "finished": r["finished"], "tokens": r["tokens"],
                      "score": r["score"], "attempt": r["attempt"], "version": r["version"], "error": r["error"], "model": r["model"]} for r in runs]
        imps = self.db.q("SELECT id, base_version, root_cause, change, status, result, created, version FROM wf_improvements WHERE agent_id=? ORDER BY id DESC LIMIT 20", (a["id"],)) \
            if self._has("wf_improvements") else []
        d["evaluations"] = {"items": [{"title": f"Run · {r['title']}", "detail": r["model"] or "", "score": r["score"], "status": r["status"], "ts": r["finished"] or r["started"]}
                                     for r in d["runs"] if r["score"] is not None][:30],
                            "improvements": [{"title": _clip(i["change"] or i["root_cause"] or "Improvement", 160), "status": i["status"], "from": i["base_version"], "to": i["version"],
                                              "result": _clip(i["result"] or "", 240), "ts": i["created"]} for i in imps],
                            "note": "Scores from the chief evaluator on each run. Improvements are trialled and wait for your approval in Workforce."}
        d["versions"] = [{"version": v["version"], "label": f"v{v['version']}", "author": v["author"] or v["source"], "note": v["note"], "ts": v["created"], "text": v["instructions"],
                          "current": v["version"] == a["version"]} for v in vers]
        if self._has("wf_events"):
            d["activity"] = [{"ts": e["ts"], "kind": e["kind"], "text": e["text"], "tokens": e["tokens"]} for e in
                             self.db.q("SELECT ts, kind, text, tokens FROM wf_events WHERE user_id=? AND agent=? ORDER BY id DESC LIMIT 50", (me["id"], a["key"]))]
        d["settings"] = [["Team", row["team"]], ["Level", a["level"]], ["Status", a["status"]], ["Version", a["version"]], ["Built in", "yes" if a["builtin"] else "no"]]
        d["manage"] = [{"label": "Open Workforce", "go": {"view": "workforce"}}]
        return d

    def _mw(self, me, id_):
        comps = {w["id"]: w for w in self._comps(me)}
        a = self.db.q("SELECT * FROM mw_agents WHERE id=?", (id_,), one=True) if comps else None
        if not a or a["comp_id"] not in comps: raise HTTPException(404, "Agent not found.")
        row = self._find(me, "teams", a["id"])
        d = self._base(row, a["job"])
        d["instructions"] = {"text": a["instructions"] or "", "note": "Set in the competition team's Team tab."}
        d["memory"] = [{"text": _clip((n["title"] + ": " if n["title"] else "") + (n["body"] or ""), 600), "source": n["reviewer"] or "notebook", "ts": n["ts"]} for n in
                       self.db.q("SELECT title, body, reviewer, ts FROM mw_notes WHERE agent_id=? ORDER BY id DESC LIMIT 40", (a["id"],))]
        tasks = self.db.q("SELECT id, title, status, runs, updated, run_id FROM mw_tasks WHERE agent_id=? ORDER BY id DESC LIMIT 60", (a["id"],))
        d["tasks"] = [{"title": t["title"], "status": t["status"], "ts": t["updated"], "tokens": None, "detail": f"{t['runs'] or 0} run{'' if t['runs'] == 1 else 's'}",
                       "trace": f"mw:{t['run_id']}" if t["run_id"] else None} for t in tasks]
        runs = self.db.q("""SELECT r.id, r.task_id, r.kind, r.status, r.started, r.finished, r.tokens, r.model, r.summary, r.error,
                                   (SELECT COUNT(*) FROM mw_runs p WHERE p.task_id=r.task_id AND p.id<r.id) prior FROM mw_runs r WHERE r.agent_id=? ORDER BY r.id DESC LIMIT 100""", (a["id"],))
        d["runs"] = [{"trace": f"mw:{r['id']}", "title": r["summary"] or r["kind"], "status": r["status"], "started": r["started"], "finished": r["finished"], "tokens": r["tokens"],
                      "attempt": (r["prior"] or 0) + 1 if r["task_id"] else None, "error": r["error"], "model": r["model"]} for r in runs]
        d["evaluations"] = {"items": [{"title": f"Run · {_clip(r['summary'] or r['kind'], 120)}", "detail": r["model"] or "", "score": None, "status": r["status"],
                                       "ts": r["finished"] or r["started"]} for r in runs[:30]],
                            "note": "Run outcomes. The team's Lab scores commits; My subnets → Improvements trials changes."}
        if self._has("mw_prompts"):
            d["versions"] = [{"version": p["id"], "label": f"Prompt · {p['title'] or p['kind']}", "author": p["by_user"] or "agent", "ts": p["ts"],
                              "text": _clip(p["system"] or "", 4000), "current": False} for p in
                             self.db.q("SELECT id, kind, title, system, by_user, ts FROM mw_prompts WHERE agent_id=? AND keep=1 ORDER BY id DESC LIMIT 10", (a["id"],))]
        d["activity"] = [{"ts": e["ts"], "kind": e["kind"], "text": e["text"], "tokens": None} for e in
                         self.db.q("SELECT ts, kind, text FROM mw_events WHERE agent_id=? ORDER BY id DESC LIMIT 50", (a["id"],))]
        d["settings"] = [["Team", row["team"]], ["Role", a["role"]], ["Squad", a["squad"] or ""], ["Model", a["model"] or "auto"], ["Lead", "yes" if a["lead"] or a["head"] else "no"]]
        d["manage"] = [{"label": "Open the team", "go": {"view": "teams", "wid": a["comp_id"], "sub": "team"}}]
        d["tools"] = (d.get("tools") or []) + _mcp_tools(f"team:{a['comp_id']}", me)
        return d

    def _mb(self, me, id_):
        flows = {f["id"]: f for f in self._flows(me)}
        a = self.db.q("SELECT * FROM mb_agents WHERE id=?", (id_,), one=True) if flows else None
        if not a or a["flow_id"] not in flows: raise HTTPException(404, "Agent not found.")
        row = self._find(me, "workflow", a["id"])
        d = self._base(row)
        lo = self.db.q("SELECT * FROM ml_loadouts WHERE agent_id=?", (a["id"],), one=True) if self._has("ml_loadouts") else None
        d["instructions"] = {"text": a["instructions"] or "", "note": "The Workflow engineer's instructions; its loadout adds skills, plugins and MCP servers."}
        d["skills"] = [{"id": s, "name": s, "description": "", "on": True} for s in _j((lo or {}).get("skills"), [])]
        d["tools"] = ([{"name": p, "label": f"Plugin · {p}", "enabled": True, "kind": "plugin"} for p in _j((lo or {}).get("plugins"), [])]
                      + [{"name": m, "label": f"MCP · {m}", "enabled": True, "kind": "mcp"} for m in _j((lo or {}).get("mcp"), [])])
        if self._has("ml_memory"):
            d["memory"] = [{"text": m["text"], "source": m["source"], "ts": m["created"]} for m in self.db.q("SELECT text, source, created FROM ml_memory WHERE agent_id=? ORDER BY id DESC LIMIT 40", (a["id"],))]
        runs = self.db.q("""SELECT l.run, l.version, l.kind, b.status, b.started, b.finished, b.error, b.label FROM ml_runs l LEFT JOIN mb_runs b ON b.run=l.run
                            WHERE l.agent_id=? ORDER BY l.created DESC LIMIT 100""", (a["id"],)) if self._has("ml_runs") else []
        d["runs"] = [{"trace": None, "title": r["label"] or r["kind"], "status": r["status"], "started": r["started"], "finished": r["finished"], "tokens": None,
                      "version": r["version"], "error": r["error"]} for r in runs]
        d["tasks"] = [{"title": r["title"], "status": r["status"], "ts": r["finished"] or r["started"], "tokens": None} for r in d["runs"][:40]]
        if self._has("ml_outcomes"):
            d["evaluations"]["items"] = [{"title": f"{o['kind']} · v{o['version']}", "detail": _clip(o["detail"] or "", 160), "score": None, "status": o["value"], "ts": o["ts"]}
                                         for o in self.db.q("SELECT kind, value, detail, version, ts FROM ml_outcomes WHERE agent_id=? ORDER BY id DESC LIMIT 40", (a["id"],))]
            d["evaluations"]["note"] = "Outcomes recorded against the loadout version that produced them (review verdicts, checks, merges)."
        if self._has("ml_versions"):
            d["versions"] = [{"version": v["n"], "label": f"Loadout v{v['n']}", "author": v["user"] or v["source"], "note": v["note"], "ts": v["created"],
                              "text": json.dumps(_j(v["snap"], {}), indent=1)[:4000], "current": False} for v in
                             self.db.q("SELECT n, snap, note, source, user, created FROM ml_versions WHERE agent_id=? ORDER BY n DESC LIMIT 20", (a["id"],))]
            if d["versions"]: d["versions"][0]["current"] = True
        d["settings"] = [["Role", a["role"]], ["Model", a["model"] or "auto"], ["Effort", (lo or {}).get("effort") or "default"], ["Budget per run", (lo or {}).get("budget") or "none"]]
        d["manage"] = [{"label": "Open the Workflow", "go": row["go"]}]
        return d

    def _hq(self, me, id_):
        if not self._hq_on(me): raise HTTPException(404, "Agent not found.")
        a = hq.STAFF_BY_ID.get(id_)
        if not a: raise HTTPException(404, "Agent not found.")
        row = self._find(me, "hq", id_)
        d = self._base(row, a.get("job") or f"Watches {a.get('watch', '')}.")
        d["instructions"] = {"text": "\n".join(f"- {c}" for c in a.get("checks", [])), "note": "Its checks. Agent HQ's prompts are part of the code; its settings are on the Agent HQ page."}
        d["tools"] = ([{"name": t, "label": t.split(".")[1].replace("_", " "), "enabled": True, "kind": "read"} for t in a.get("reads", [])]
                      + [{"name": t, "label": t.split(".")[1].replace("_", " "), "enabled": True, "kind": "fix (needs approval)"} for t in a.get("fixes", [])])
        issues = self.db.q("SELECT id, title, severity, status, last_seen, resolution FROM hq_issues WHERE agent=? ORDER BY id DESC LIMIT 40", (id_,)) if self._has("hq_issues") else []
        d["tasks"] = [{"title": i["title"], "status": i["status"], "ts": i["last_seen"], "tokens": None, "detail": i["severity"]} for i in issues]
        fixes = self.db.q("SELECT label, status, lead_decision, verified, created, decided FROM hq_fixes WHERE agent=? ORDER BY id DESC LIMIT 40", (id_,)) if self._has("hq_fixes") else []
        d["evaluations"] = {"items": [{"title": f"Fix · {f['label'] or ''}", "detail": f"Lead: {f['lead_decision'] or 'pending'}" + (f" · verified: {f['verified']}" if f["verified"] else ""),
                                       "score": None, "status": f["status"], "ts": f["decided"] or f["created"]} for f in fixes],
                            "note": "Its proposed fixes: the lead's review and whether the fix was verified afterwards."}
        rounds = {r["round_id"] for r in self.db.q("SELECT DISTINCT round_id FROM hq_events WHERE agent=? AND round_id IS NOT NULL ORDER BY round_id DESC LIMIT 30", (id_,))} if self._has("hq_events") else set()
        if rounds:
            d["runs"] = [{"trace": f"hq:{r['id']}", "title": f"{(r['kind'] or 'patrol').capitalize()} round", "status": r["status"], "started": r["ts"], "finished": r["finished"], "tokens": r["tokens"],
                          "error": r["error"]} for r in self.db.q(f"SELECT * FROM hq_rounds WHERE id IN ({','.join('?' * len(rounds))}) ORDER BY id DESC", list(rounds))]
        if self._has("hq_events"):
            d["activity"] = [{"ts": e["ts"], "kind": e["kind"], "text": e["text"], "tokens": e["tokens"]} for e in
                             self.db.q("SELECT ts, kind, text, tokens FROM hq_events WHERE agent=? ORDER BY id DESC LIMIT 50", (id_,))]
        d["settings"] = [["Tier", a.get("tier", "field")], ["Team", row["team"]], ["Status", row["status"]]]
        d["manage"] = [{"label": "Open Agent HQ", "go": {"view": "hq"}}]
        return d

    # ---------- traces ----------
    def trace(self, me, key):
        self._gate(me)
        kind, _, rest = key.partition(":")
        if kind == "wf":
            r = self.db.q("SELECT * FROM wf_runs WHERE id=? AND user_id=?", (rest, me["id"]), one=True) if workforce.ENABLED and self._has("wf_runs") else None
            if not r: raise HTTPException(404, "Run not found.")
            spans = self.db.q("SELECT ts, end, kind, name, input, output, tokens, error FROM wf_spans WHERE run_id=? ORDER BY id", (r["id"],))
            return self._trace(r["task"] or r["step"], r, spans, f"Workforce · {r['agent']}")
        if kind == "mw":
            r = self.db.q("SELECT * FROM mw_runs WHERE id=?", (rest,), one=True) if self._has("mw_runs") else None
            if not r or r["comp_id"] not in {w["id"] for w in self._comps(me)}: raise HTTPException(404, "Run not found.")
            spans = self.db.q("SELECT ts, end, kind, name, input, output, tokens, error FROM mw_spans WHERE run_id=? ORDER BY id", (r["id"],))
            name = self.db.q("SELECT name FROM mw_agents WHERE id=?", (r["agent_id"],), one=True)
            return self._trace(r["summary"] or r["kind"], r, spans, (name or {}).get("name", "agent"), output=r["output"])
        if kind == "co":
            c = self._company(me)
            t = self.db.q("SELECT * FROM co_tasks WHERE id=? AND company_id=?", (rest, c["id"]), one=True) if c else None
            if not t: raise HTTPException(404, "Run not found.")
            names = {a["id"]: a["name"] for a in self.db.q("SELECT id, name FROM co_agents WHERE company_id=?", (c["id"],))}
            spans = [{"ts": m["ts"], "end": None, "kind": m["type"], "name": f"{names.get(m['from_agent'], 'you' if m['from_agent'] is None else '#' + str(m['from_agent']))} → "
                                                                              f"{names.get(m['to_agent'], '#' + str(m['to_agent']) if m['to_agent'] else 'everyone')}",
                      "input": "", "output": m["payload"], "tokens": m["tokens"], "error": 0}
                     for m in self.db.q("SELECT ts, type, from_agent, to_agent, payload, tokens FROM co_messages WHERE task_id=? ORDER BY id", (t["id"],))]
            return self._trace(t["title"], {**t, "started": t["started"] or t["created"]}, spans, "Company task")
        if kind == "hq":
            if not self._hq_on(me): raise HTTPException(404, "Run not found.")
            r = self.db.q("SELECT * FROM hq_rounds WHERE id=?", (rest,), one=True)
            if not r: raise HTTPException(404, "Run not found.")
            spans = [{"ts": e["ts"], "end": None, "kind": e["kind"], "name": e["agent"], "input": "", "output": e["text"], "tokens": e["tokens"], "error": 0}
                     for e in self.db.q("SELECT ts, agent, kind, text, tokens FROM hq_events WHERE round_id=? ORDER BY id", (r["id"],))]
            return self._trace(f"{(r['kind'] or 'patrol').capitalize()} round", {**r, "started": r["ts"]}, spans, "Agent HQ")
        if kind == "chat":
            agent, _, cid = rest.partition(":")
            if self.hub is None: raise HTTPException(404, "Run not found.")
            tag = f"custom:{agent}" if agent.isdigit() else agent
            c = self.db.q("SELECT * FROM agent_conversations WHERE id=? AND user_id=? AND agent=?", (cid, me["id"], tag), one=True)
            if not c: raise HTTPException(404, "Run not found.")
            spans = []
            for it in view_items(_j(c["messages"], [])):
                k = it.get("kind")
                if k == "tool": spans.append({"ts": None, "end": None, "kind": "tool", "name": it.get("name") or it.get("label") or "tool", "input": json.dumps(it.get("input") or {})[:600], "output": "", "tokens": 0, "error": 0})
                elif k in ("user", "assistant", "note"): spans.append({"ts": None, "end": None, "kind": k, "name": {"user": "You", "assistant": "Agent", "note": "Status"}[k],
                                                                        "input": "", "output": _clip(it.get("text") or "", 1500), "tokens": (it.get("meta") or {}).get("tokens") or 0, "error": 0})
            return self._trace(c["title"], {"status": "done", "started": c["created"], "finished": c["updated"], "tokens": sum(s["tokens"] for s in spans)}, spans, "Chat")
        if kind == "ac" and agent_core.get() is not None:
            r = self.db.q("SELECT * FROM ac_runs WHERE id=?", (rest,), one=True)
            if not r or r["owner_id"] not in self._owners(me): raise HTTPException(404, "Run not found.")
            spans = [{"ts": r["started"], "end": r["finished"], "kind": "model", "name": r["model"] or "model calls", "input": r["kind"] or "",
                      "output": f"{r['tokens']:,} tokens" + (f", ${r['cost']:.2f}" if r["cost"] else ""), "tokens": r["tokens"], "error": r["status"] in ("failed", "lost")}]
            return self._trace(r["title"] or r["kind"], r, spans, SYSTEMS.get(r["system"], "Other"))
        raise HTTPException(404, "Run not found.")

    @staticmethod
    def _trace(title, r, spans, who, output=None):
        return {"title": title or "Run", "who": who, "status": r.get("status"), "started": r.get("started"), "finished": r.get("finished"), "tokens": r.get("tokens") or 0,
                "error": r.get("error"), "model": r.get("model"), "output": _clip(output or r.get("output") or r.get("summary") or "", 6000),
                "spans": [{"ts": s["ts"], "end": s["end"], "kind": s["kind"], "name": s["name"], "input": _clip(s["input"] or "", 2000), "output": _clip(s["output"] or "", 3000),
                           "tokens": s["tokens"] or 0, "error": bool(s["error"])} for s in spans]}

    # ---------- versions, restore and tests (your agents) ----------
    @staticmethod
    def _snap(a):
        return {k: a[k] for k in ("name", "role", "description", "instructions", "icon", "color", "face", "kind", "skills", "examples")}

    def _versions(self, aid):
        rows = self.db.q("SELECT version, snap, note, author, created FROM aos_versions WHERE agent_id=? ORDER BY version DESC LIMIT 50", (aid,))
        if not rows: return []
        cur = self._snap(self.hub._get(aid))
        out = []
        for v in rows:
            s = _j(v["snap"], {})
            out.append({"version": v["version"], "label": f"v{v['version']}", "note": v["note"], "author": v["author"], "ts": v["created"], "text": s.get("instructions", ""),
                        "snap": s, "current": s == cur and not any(o["current"] for o in out)})
        return out

    def snapshot(self, me, aid, note):
        """Keep the agent's configuration as a new version unless it equals the latest one."""
        a = self.hub._get(aid)
        snap = self._snap(a)
        last = self.db.q("SELECT version, snap FROM aos_versions WHERE agent_id=? ORDER BY version DESC LIMIT 1", (aid,), one=True)
        if last and _j(last["snap"], {}) == snap: return last["version"]
        n = (last["version"] if last else 0) + 1
        self.db.q("INSERT INTO aos_versions (agent_id, version, snap, note, author, created) VALUES (?,?,?,?,?,?)",
                  (aid, n, json.dumps(snap), _clip(note or "", 200), me["username"], time.time()))
        return n

    def _saved(self, me, aid, before):
        """Agent hub hook: called after an owner saves an agent, with its configuration before the save."""
        if aid in self.restoring: return
        try:
            if not self.db.q("SELECT 1 FROM aos_versions WHERE agent_id=?", (aid,), one=True):
                self.db.q("INSERT INTO aos_versions (agent_id, version, snap, note, author, created) VALUES (?,?,?,?,?,?)",
                          (aid, 1, json.dumps(self._snap(before)), "Before the first tracked change", me["username"], before.get("updated") or time.time()))
            self.snapshot(me, aid, "Saved")
        except Exception:  # noqa: BLE001 - a version failing never blocks the save
            log.exception("studio version")

    def _owned(self, me, key):
        self._gate(me)
        system, _, id_ = key.partition(":")
        if system != "hub" or not id_.isdigit() or self.hub is None:
            raise HTTPException(400, "Only your own agents are changed here; the others are changed on their own pages.")
        return self.hub._owned(int(id_), me)

    def restore(self, me, key, version):
        a = self._owned(me, key)
        v = self.db.q("SELECT snap FROM aos_versions WHERE agent_id=? AND version=?", (a["id"], version), one=True)
        if not v: raise HTTPException(404, "No such version.")
        s = _j(v["snap"], {})
        body = AgentIn(name=s["name"], role=s.get("role") or "", description=s.get("description") or "", instructions=s.get("instructions") or "",
                       icon=s.get("icon") or "bot", color=s.get("color") or "violet", skills=s.get("skills") or [], examples=s.get("examples") or [],
                       shared_with=[u["username"] for u in self.db.q("SELECT username FROM users WHERE id IN (%s)" % ",".join("?" * len(a["shared_with"])), a["shared_with"])] if a["shared_with"] else [],
                       in_directory=bool(a["in_directory"]), status=a["status"], face=s.get("face") or "", kind=s.get("kind") or "")
        self.restoring.add(a["id"])  # versioned below with its own note; other agents' saves keep their hook
        try: self.hub.update(me, a["id"], body)
        finally: self.restoring.discard(a["id"])
        n = self.snapshot(me, a["id"], f"Restored v{version}")
        self.db.log("agent.restored", me["username"], "", "", f"#{a['id']} v{version} -> v{n}")
        self.cache.pop(me["id"], None)
        return self.agent(me, key)

    def test(self, me, key, t: TestIn):
        """One message to the agent with its saved, a saved version's or a draft's instructions. Read-only tools; nothing is kept
        but the test record, and the tokens count against the agent like a chat's."""
        system_, _, id_ = key.partition(":")
        self._gate(me)
        if system_ != "hub" or not id_.isdigit() or self.hub is None: raise HTTPException(400, "Tests run on your own agents.")
        a = self.hub._usable(int(id_), me)
        mine = a["owner_id"] == me["id"]
        msg = t.message.strip()
        if not msg: raise HTTPException(400, "Type a test message.")
        if len(msg) > 4000: raise HTTPException(400, "Message too long.")
        instructions, draft, version = a["instructions"], 0, None
        if t.version is not None:
            if not mine: raise HTTPException(403, "Only the agent's creator can test its versions.")
            v = self.db.q("SELECT snap FROM aos_versions WHERE agent_id=? AND version=?", (a["id"], t.version), one=True)
            if not v: raise HTTPException(404, "No such version.")
            instructions, version = _j(v["snap"], {}).get("instructions") or "", t.version
        elif t.instructions is not None and t.instructions.strip() and t.instructions.strip() != (a["instructions"] or "").strip():
            if not mine: raise HTTPException(403, "Only the agent's creator can test a draft.")
            instructions, draft = t.instructions.strip()[:8000], 1
        if version is None and not draft:
            last = self.db.q("SELECT version FROM aos_versions WHERE agent_id=? ORDER BY version DESC LIMIT 1", (a["id"],), one=True)
            version = last["version"] if last else None
        study = a["kind"] == "study"
        system = ((STUDY_BASE if study else BASE).format(name=a["name"], role=a["role"] or "assistant", instructions=instructions)
                  + self.hub._skill_text(a["skills"]) + EXTRA + "\n\n<memory>\n</memory>"
                  + f"\n\nThis is a test run in the Agent Studio by {me['username']}: answer as you would in a chat. Current time (UTC): {time.strftime('%Y-%m-%d %H:%M')}.")
        messages = [{"role": "user", "content": [{"type": "text", "text": msg}]}]
        used, error, model_id, t0 = [0], None, None, time.time()
        try:
            complete, model_id = self.hub.llm.completer(t.model, t.effort if t.effort in ("low", "medium", "high") else "medium")
            def tool(name, args):
                if name == "remember": return {"ok": True, "note": "Not kept: this is a test."}
                if study: raise KeyError(name)  # study tools write the learner's progress: not in a test
                if name == "my_subnets": return self.hub.my_subnets(me)
                if name in SOURCE_TOOLS: return self.hub.source_tool(name, args)
                if name in DEVOPS_TOOLS: return self.hub.devops_tool(me, name, args)
                return self.hub.run_tool(name, args)
            tools = ([] if study else self.hub.tools_for(me)) + [REMEMBER]
            run_loop(complete, system, tools, messages, tool, on_usage=lambda n: used.__setitem__(0, used[0] + n), model=model_id)
        except LLMError as e:
            error = str(e)
        ms = int((time.time() - t0) * 1000)
        items = view_items(messages[1:]) if not error else []
        answer = "\n\n".join(i["text"] for i in items if i.get("kind") == "assistant" and i.get("text"))
        tools_used = [i.get("label") or i.get("name") for i in items if i.get("kind") == "tool"]
        self.db.q("INSERT INTO aos_tests (user_id, agent_id, version, draft, message, answer, model, tokens, ms, error, ts) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (me["id"], a["id"], version, draft, msg, answer[:20000], model_id, used[0], ms, error, time.time()))
        self.hub.log_usage(me, "test", used[0], a["id"], model_id)
        return {"answer": answer, "tools": tools_used, "model": model_id, "tokens": used[0], "ms": ms, "error": error, "version": version, "draft": bool(draft)}


def build(require, ov, hub, co=None, cmd=None):
    r = APIRouter(prefix="/api/studio")
    s = Studio(ov.db, ov, hub, co, cmd)
    r.state = {"studio": s}

    @r.get("")
    def overview(req: Request, fresh: bool = False): return s.overview(require(req), fresh)

    @r.get("/agents/{key}")
    def agent(key: str, req: Request): return s.agent(require(req), key)

    @r.get("/traces/{key:path}")
    def trace(key: str, req: Request): return s.trace(require(req), key)

    @r.put("/budget")
    def budget(b: BudgetIn, req: Request):
        """Your daily token limit over every agent system (agent_core.py); 0 or none: no limit."""
        me = require(req)
        s._gate(me)
        if agent_core.get() is None: raise HTTPException(503, "The agent core isn't running.")
        if b.daily_tokens is not None and not (0 <= b.daily_tokens <= 10**10): raise HTTPException(422, "Between 0 and 10,000,000,000 tokens.")
        if "daily_tokens" in b.model_fields_set or b.unlimited is None:  # a body with only "unlimited" leaves the limit as it is
            agent_core.get().set_cap(me["id"], b.daily_tokens or None, me["username"])
        if b.unlimited is not None: agent_core.get().set_unlimited(me["id"], b.unlimited, me["username"])
        s.cache.pop(me["id"], None)
        return agent_core.get().budget(me["id"])

    @r.post("/agents/{key}/test")
    def test(key: str, t: TestIn, req: Request): return s.test(require(req), key, t)

    @r.post("/agents/{key}/restore")
    def restore(key: str, b: RestoreIn, req: Request): return s.restore(require(req), key, b.version)

    @r.post("/agents/{key}/snapshot")
    def snapshot(key: str, req: Request):
        me = require(req)
        a = s._owned(me, key)
        return {"version": s.snapshot(me, a["id"], "Kept by hand")}

    return r
