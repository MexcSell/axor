"""Agent Operations → Ecosystem: AXoR seen as one AI ecosystem, eight layers from the mission you give it down to governance,
each read live from the parts of AXoR that do that layer's work (agent-studio.js draws it as a section of Agent Operations).

- Layers: mission interface, mission intelligence, agent workforce, model intelligence, knowledge, execution, verification and
  evolution, governance and control. Each shows what's there and what ran this week for the signed-in user, and a status:
  active (it did something this week), ready (set up, quiet), or not set up. Nothing here is estimated: a part that isn't
  there says so. The figures come from the systems' own tables (counts only, the user's own rows), and the agent figures from
  Agent Operations' directory, so a number here matches the page it links to.
- Interoperability: where AXoR stands on MCP (agents ↔ tools: Workflow agents get MCP servers through their loadouts) and
  A2A (agent ↔ agent): AXoR doesn't talk A2A. The external-agent registry keeps the Agent Cards the user pastes (name,
  description, skills, endpoint as written in the card) for discovery only. Every entry is untrusted until the user marks it
  reviewed, and nothing in AXoR sends work to an external agent: no fetch, no call, no delegation.
"""
import json, time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import agent_core

WEEK = 7 * 86400
MAX_AGENTS = 100
CARD_CHARS = 20000


class CardIn(BaseModel):
    card: str = Field(..., min_length=2, max_length=CARD_CHARS)  # the Agent Card JSON, pasted
    url: str = Field("", max_length=500)                        # where it was found (kept as text, never fetched)
    note: str = Field("", max_length=400)


class TrustIn(BaseModel):
    trust: str = Field(..., pattern="^(untrusted|reviewed|blocked)$")


def parse_card(text):
    """The fields of an A2A Agent Card that matter for discovery, or a ValueError saying what's wrong."""
    try: c = json.loads(text)
    except ValueError: raise ValueError("That isn't JSON: paste the Agent Card (the agent's /.well-known/agent-card.json).")
    if not isinstance(c, dict) or not str(c.get("name") or "").strip(): raise ValueError("An Agent Card needs at least a name.")
    skills = []
    for s in c.get("skills") or []:
        if isinstance(s, dict) and (s.get("name") or s.get("id")):
            skills.append({"name": str(s.get("name") or s.get("id"))[:120], "description": str(s.get("description") or "")[:300],
                           "tags": [str(t)[:40] for t in (s.get("tags") or [])][:8]})
    caps = c.get("capabilities") if isinstance(c.get("capabilities"), dict) else {}
    prov = c.get("provider") if isinstance(c.get("provider"), dict) else {}
    return {"name": str(c["name"]).strip()[:120], "description": str(c.get("description") or "")[:600],
            "endpoint": str(c.get("url") or "")[:300], "version": str(c.get("version") or c.get("protocolVersion") or "")[:40],
            "provider": str(prov.get("organization") or "")[:120], "skills": skills[:30],
            "capabilities": sorted(k for k, v in caps.items() if v is True)[:10],
            "auth": sorted((c.get("securitySchemes") or {}).keys())[:6] if isinstance(c.get("securitySchemes"), dict) else []}


class Ecosystem:
    def __init__(self, db, studio, hub=None):
        self.db, self.studio, self.hub = db, studio, hub
        db.q("""CREATE TABLE IF NOT EXISTS eco_agents (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, card TEXT, info TEXT,
                url TEXT, note TEXT, trust TEXT DEFAULT 'untrusted', created REAL, updated REAL)""")
        db.q("CREATE INDEX IF NOT EXISTS eco_agents_u ON eco_agents (user_id, id)")

    def _n(self, sql, args=()):
        try:
            r = self.db.q(sql, args, one=True)
            return (r or {}).get("n") or 0
        except Exception:  # noqa: BLE001 - a table that isn't there (yet) counts as nothing
            return None

    def _layers(self, me, ov):
        uid, wk = me["id"], time.time() - WEEK
        n = self._n
        comps = f"SELECT w.id FROM mw_comps w JOIN mh_campaigns c ON c.id=w.campaign_id WHERE c.user_id={int(uid)}"
        flows = f"SELECT id FROM mb_flows WHERE comp_id IN ({comps})"
        co = f"SELECT id FROM co_company WHERE user_id={int(uid)}"
        sysc = ov.get("systems", {})
        models = sum(len(e["models"]) for e in (self.hub.llm.catalog() if self.hub else []) if e["configured"])
        providers = [e["label"] for e in (self.hub.llm.catalog() if self.hub else []) if e["configured"]]
        def item(label, value, view=None, extra=None):
            return {"label": label, "value": value, "view": view, **(extra or {})}
        L = []
        def layer(key, title, about, items, active, ready):
            vals = [i["value"] for i in items if isinstance(i["value"], (int, float))]
            status = "active" if active else "ready" if ready or any(vals) else "missing"
            L.append({"key": key, "title": title, "about": about, "items": items, "status": status})
        mx_open = n("SELECT COUNT(*) n FROM mx_missions WHERE user_id=? AND status IN ('queued','running','needs_input')", (uid,))
        mx_week = n("SELECT COUNT(*) n FROM mx_missions WHERE user_id=? AND created>?", (uid, wk))
        wf_week = n("SELECT COUNT(*) n FROM wf_missions WHERE user_id=? AND created>?", (uid, wk))
        layer("mission", "Mission interface", "Goals, budget, deadline and constraints in; the system plans the rest.",
              [item("Missions open", mx_open, "missions"), item("Missions this week", mx_week, "missions"),
               item("Workforce missions this week", wf_week, "workforce")],
              bool(mx_week) or bool(wf_week), mx_open is not None)
        layer("intelligence", "Mission intelligence", "Understand, plan, decide, coordinate: the Directors, the CEO and the planners.",
              [item("Competition teams on autopilot", n(f"SELECT COUNT(*) n FROM mw_comps WHERE id IN ({comps}) AND autopilot=1"), "teams"),
               item("Company projects active", n(f"SELECT COUNT(*) n FROM co_projects WHERE company_id IN ({co}) AND status='active'"), "company"),
               item("Long tasks running", n("SELECT COUNT(*) n FROM ia_tasks WHERE user_id=? AND status='running'", (uid,)), "infiagent")],
              bool(n(f"SELECT COUNT(*) n FROM mw_runs WHERE kind='plan' AND started>? AND comp_id IN ({comps})", (wk,))), False)
        c = ov.get("counts", {})
        layer("workforce", "Agent workforce", "Teams, specialists and their identities, across every agent system.",
              [item("Agents", c.get("agents", 0), "studio"), item("Working now", c.get("working", 0), "studio"),
               item("Systems", len(sysc), "studio", {"detail": ", ".join(f"{s['label']} {s['agents']}" for s in sysc.values())})],
              bool(c.get("working")) or bool(c.get("tokens_week")), bool(c.get("agents")))
        # the agent core's run ledger (agent_core.py): every system's model calls, where llm_usage has only some
        led = "ac_runs" if agent_core.get() is not None else None
        tok = n(f"SELECT COALESCE(SUM(tokens),0) n FROM {led} WHERE owner_id=? AND started>?" if led else "SELECT COALESCE(SUM(tokens),0) n FROM llm_usage WHERE user_id=? AND ts>?", (uid, wk))
        used = []
        try: used = self.db.q(f"SELECT model, SUM(tokens) t FROM {led} WHERE owner_id=? AND started>? AND model IS NOT NULL GROUP BY model ORDER BY t DESC LIMIT 4" if led
                              else "SELECT model, SUM(tokens) t FROM llm_usage WHERE user_id=? AND ts>? GROUP BY model ORDER BY t DESC LIMIT 4", (uid, wk))
        except Exception: pass  # noqa: BLE001
        layer("models", "Model intelligence", "The model pool and which model does which work.",
              [item("Providers connected", len(providers), "settings", {"detail": ", ".join(providers)}), item("Models offered", models, "settings"),
               item("Tokens this week", tok, "studio", {"detail": ", ".join(f"{(u['model'] or '?').split(':')[-1]} {u['t']:,}" for u in used if u["t"])})],
              bool(tok), bool(providers))
        layer("knowledge", "Knowledge system", "Memory, notes, skills and experience shared across agents.",
              [item("Knowledge hub items", n("SELECT COUNT(*) n FROM kb_items WHERE user_id=?", (uid,)), "knowledge"),
               item("Workforce memories", n("SELECT COUNT(*) n FROM wf_memory WHERE user_id=?", (uid,)), "workforce"),
               item("Team notebook findings", n(f"SELECT COUNT(*) n FROM mw_notes WHERE comp_id IN ({comps})"), "teams")],
              bool(n(f"SELECT COUNT(*) n FROM mw_notes WHERE ts>? AND comp_id IN ({comps})", (wk,))) or bool(n("SELECT COUNT(*) n FROM wf_memory WHERE user_id=? AND created>?", (uid, wk))), False)
        layer("execution", "Execution system", "Tools, code, sandboxes and the runs that use them, with recovery.",
              [item("Agent runs this week", n(f"SELECT COUNT(*) n FROM mw_runs WHERE started>? AND comp_id IN ({comps})", (wk,)), "teams"),
               item("Sandbox runs this week", n(f"SELECT COUNT(*) n FROM mw_sbx WHERE started>? AND comp_id IN ({comps})", (wk,)), "teams"),
               item("Failed in the last day", c.get("failed", 0), "studio")],
              bool(c.get("running")) or bool(n(f"SELECT COUNT(*) n FROM mw_runs WHERE started>? AND comp_id IN ({comps})", (wk,))), False)
        evals = n(f"SELECT COUNT(*) n FROM mb_experiments WHERE status='done' AND finished>? AND flow_id IN ({flows})", (wk,))
        sprints = n(f"SELECT COUNT(*) n FROM au_sprints WHERE started>? AND comp_id IN ({comps})", (wk,))
        layer("evolution", "Verification and evolution", "Tests, benchmarks, independent review, and improvements kept only when measured better.",
              [item("Lab evals this week", evals, "teams"), item("Upgrade sprints this week", sprints, "teams"),
               item("Upgrades promoted", n(f"SELECT COUNT(*) n FROM au_agents WHERE decision='promoted' AND comp_id IN ({comps})"), "teams"),
               item("Experiments in the Command center", n("SELECT COUNT(*) n FROM mc_experiments WHERE user_id=?", (uid,)), "mining")],
              bool(evals) or bool(sprints), False)
        pend = c.get("approvals", 0)
        layer("governance", "Governance and control", "Identity, permissions, budgets, approvals and the audit trail.",
              [item("Approvals waiting for you", pend, "approvals"),
               item("Company approvals decided", n(f"SELECT COUNT(*) n FROM co_approvals WHERE company_id IN ({co}) AND status IN ('approved','consumed')"), "company"),
               item("Audit entries this week", n(f"SELECT COUNT(*) n FROM co_audit WHERE company_id IN ({co}) AND ts>?", (wk,)), "company")],
              bool(pend), True)
        return L

    def view(self, me):
        ov = self.studio.overview(me)
        L = self._layers(me, ov)
        reg = self.db.q("SELECT id, name, info, url, note, trust, created, updated FROM eco_agents WHERE user_id=? ORDER BY id DESC", (me["id"],))
        for r in reg: r["info"] = json.loads(r["info"] or "{}")
        return {"at": time.time(), "layers": L,
                "score": {"active": sum(1 for x in L if x["status"] == "active"), "ready": sum(1 for x in L if x["status"] == "ready"), "total": len(L)},
                "interop": [
                    {"key": "mcp", "title": "MCP · agents ↔ tools", "status": "partial",
                     "text": "Workflow agents get MCP servers through their loadouts on the AXoR Workbench; chat and team agents use AXoR's own tools.", "view": "teams"},
                    {"key": "a2a", "title": "A2A · agent ↔ agent", "status": "discovery",
                     "text": "AXoR doesn't speak A2A. The registry below keeps external agents' cards for discovery; nothing is sent to them."},
                    {"key": "identity", "title": "Agent identity and discovery", "status": "internal",
                     "text": "Every AXoR agent has an identity, role, model, tools and history in Agent Operations' directory, across all its systems.", "view": "studio"}],
                "registry": reg}

    def add(self, me, b: CardIn):
        try: info = parse_card(b.card)
        except ValueError as e: raise HTTPException(422, str(e))
        if self.db.q("SELECT COUNT(*) n FROM eco_agents WHERE user_id=?", (me["id"],), one=True)["n"] >= MAX_AGENTS:
            raise HTTPException(409, f"The registry holds at most {MAX_AGENTS} agents.")
        now = time.time()
        self.db.q("INSERT INTO eco_agents (user_id, name, card, info, url, note, trust, created, updated) VALUES (?,?,?,?,?,?,'untrusted',?,?)",
                  (me["id"], info["name"], b.card, json.dumps(info), b.url.strip(), b.note.strip(), now, now))
        return self.view(me)

    def _own(self, me, eid):
        r = self.db.q("SELECT * FROM eco_agents WHERE id=? AND user_id=?", (eid, me["id"]), one=True)
        if not r: raise HTTPException(404, "There's no such agent in your registry.")
        return r

    def trust(self, me, eid, b: TrustIn):
        self._own(me, eid)
        self.db.q("UPDATE eco_agents SET trust=?, updated=? WHERE id=?", (b.trust, time.time(), eid))
        return self.view(me)

    def delete(self, me, eid):
        self._own(me, eid)
        self.db.q("DELETE FROM eco_agents WHERE id=?", (eid,))
        return self.view(me)


def build(require, studio, hub=None):
    r = APIRouter(prefix="/api/ecosystem")
    e = Ecosystem(studio.db, studio, hub)
    r.state = {"ecosystem": e}
    user = lambda req: studio._gate(require(req))

    @r.get("")
    def view(req: Request): return e.view(user(req))

    @r.post("/agents")
    def add(b: CardIn, req: Request): return e.add(user(req), b)

    @r.patch("/agents/{eid}")
    def trust(eid: int, b: TrustIn, req: Request): return e.trust(user(req), eid, b)

    @r.delete("/agents/{eid}")
    def delete(eid: int, req: Request): return e.delete(user(req), eid)

    return r
