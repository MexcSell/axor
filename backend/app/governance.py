"""Governance (AXoR 5.0, governance.js, /api/governance): permissions, spending, autonomy, approvals, audit and rollback in one
place, over the controls that already exist. It adds no approval path of its own: the organization's requests (og_requests),
Mission Control's requests (mx_requests) and the Approval Center (command.py) stay where decisions are made; the Evolution
Engine's policy (evolution.py, ev_policy) is changed from this page through PUT /api/evolution/policy.

- Autonomy: the spec's five levels (observe and recommend → develop and propose organizational improvements) shown beside the
  organization's execution levels (organization.py LEVELS, L0 Observe … L4 Restricted autonomy), which stay the ones enforced,
  with how many of your agents sit at each.
- Always yours: the actions no level or policy can take on its own (organization.LOCKED), plus code changes and external
  actions in the Evolution Engine.
- Budgets: your daily token limit over every agent system (agent_core, set on Agents → Models or here through
  PUT /api/studio/budget) and the Evolution Engine's own daily limit.
- Waiting for you: verified evolution changes, organization and mission requests.
- Rollback points: every promoted change with the version it replaced.
- Audit: the Evolution Engine's and the organization's audit trails, merged.
Read-only (cached a few seconds like the other hubs).
"""
from fastapi import APIRouter, Request

from . import agent_core
from .hubs import Hubs, _j
from .mining import _clip

RULES = [
    {"rule": "No improvement without measured evidence", "how": "A change is promoted only after its experiment (or recorded measurements) beat the current version on the same cases by the policy's margin.", "where": "Evolution Engine"},
    {"rule": "Evidence is bound to what it measured", "how": "If the agent changed after the experiment, promotion is refused until it runs again.", "where": "Evolution Engine"},
    {"rule": "Every promotion can be rolled back", "how": "The version before each promoted change is kept; rollback restores it in one click.", "where": "Evolution Engine · Agent Studio"},
    {"rule": "Code and external actions always need you", "how": "The policy never promotes them; only configuration changes of your own agents can be promoted by policy.", "where": "Evolution Engine"},
    {"rule": "Position never raises execution authority", "how": "Raising an agent to L3 or more waits for your approval; a manager keeps its own level.", "where": "Organization"},
    {"rule": "Locked actions", "how": "Production deployment, external commitments, budget changes, destructive operations and strategy always need you.", "where": "Organization · Approval Center"},
    {"rule": "Daily budgets", "how": "Model calls stop when your daily token limit is used up, in every agent system.", "where": "Agent core"},
    {"rule": "Approvals are single-use", "how": "A request applies once, after your decision, and expires if left waiting.", "where": "Organization · Mission Control · Company"},
]


class Governance(Hubs):
    def __init__(self, db, ov, co=None, evo=None):
        super().__init__(db, ov, co)
        self.evo = evo

    def view(self, me, fresh=False):
        self._agents(me)
        return self.cached("governance5", me, self._view, fresh)

    def _view(self, me, out):
        uid, q = me["id"], self.db.q
        from . import organization, evolution
        out.update({"rules": RULES, "levels": [], "spec_levels": evolution.SPEC_LEVELS, "locked": [{"k": k, "label": v} for k, v in organization.LOCKED.items()],
                    "policy": None, "modes": evolution.MODES, "budget": None, "pending": [], "rollback": [], "audit": [], "admin": me.get("role") == "admin"})

        def levels():
            counts = {}
            if self._has("og_agents"):
                counts = {r["autonomy"]: r["n"] for r in q("SELECT autonomy, COUNT(*) n FROM og_agents WHERE user_id=? AND status NOT IN ('archived','gone') GROUP BY autonomy", (uid,))}
            out["levels"] = [dict(l, agents=counts.get(l["level"], 0), needs_approval=l["level"] >= organization.APPROVAL_FROM) for l in organization.LEVELS]

        def policy():
            if self.evo is None: return
            p = self.evo.policy(uid)
            p["spent_today"] = self.evo._spent_today(uid)
            out["policy"] = p

        def budget():
            core = agent_core.get()
            if core is None: return
            out["budget"] = core.budget(uid)

        def pending():
            if self._has("ev_proposals"):
                for r in q("SELECT id, target_name, title, evidence, risk, updated FROM ev_proposals WHERE user_id=? AND status='verified' ORDER BY id DESC LIMIT 30", (uid,)):
                    e = _j(r["evidence"], {}) or {}
                    out["pending"].append({"source": "evolution", "title": f"{r['target_name']}: {r['title']}", "detail": f"verified {e.get('baseline')} → {e.get('candidate')} on {e.get('cases')} cases · {r['risk']}",
                                           "ts": r["updated"], "go": {"view": "evolution", "proposal": r["id"]}})
            if self._has("og_requests"):
                for r in q("SELECT kind, title, by, created FROM og_requests WHERE user_id=? AND status='pending' ORDER BY id DESC LIMIT 30", (uid,)):
                    out["pending"].append({"source": "organization", "title": r["title"] or r["kind"], "detail": f"proposed by {r['by'] or 'an agent'}", "ts": r["created"], "go": {"view": "approvals"}})
            if self._has("mx_requests"):
                for r in q("SELECT label, kind, created FROM mx_requests WHERE user_id=? AND status='pending' ORDER BY id DESC LIMIT 30", (uid,)):
                    out["pending"].append({"source": "missions", "title": r["label"] or r["kind"], "detail": "Mission Control", "ts": r["created"], "go": {"view": "approvals"}})
            out["pending"].sort(key=lambda x: -(x["ts"] or 0))

        def rollback():
            if not self._has("ev_proposals"): return
            for r in q("""SELECT id, target_name, title, before_version, after_version, decided_by, decision, promoted FROM ev_proposals
                          WHERE user_id=? AND status='promoted' ORDER BY promoted DESC LIMIT 40""", (uid,)):
                out["rollback"].append({"id": r["id"], "title": f"{r['target_name']}: {r['title']}", "before": r["before_version"], "after": r["after_version"],
                                        "by": r["decided_by"], "decision": r["decision"], "ts": r["promoted"]})

        def audit():
            rows = []
            if self._has("ev_audit"):
                rows += [{"ts": r["ts"], "actor": r["actor"], "action": r["action"], "target": r["target"], "detail": _clip(r["detail"] or "", 300), "source": "evolution"}
                         for r in q("SELECT ts, actor, action, target, detail FROM ev_audit WHERE user_id=? ORDER BY id DESC LIMIT 80", (uid,))]
            if self._has("og_audit"):
                rows += [{"ts": r["ts"], "actor": r["actor"], "action": r["action"], "target": r["target"], "detail": _clip(r["detail"] or "", 300), "source": "organization"}
                         for r in q("SELECT ts, actor, action, target, detail FROM og_audit WHERE user_id=? ORDER BY id DESC LIMIT 80", (uid,))]
            out["audit"] = sorted(rows, key=lambda x: -(x["ts"] or 0))[:120]

        for label, fn in (("Autonomy levels", levels), ("Evolution policy", policy), ("Budget", budget), ("Waiting for you", pending),
                          ("Rollback points", rollback), ("Audit", audit)):
            self._try(out, label, fn)


def build(db, require, ov, co=None, evo=None):
    r = APIRouter(prefix="/api/governance")
    h = Governance(db, ov, co, evo)
    r.state = {"governance": h}

    @r.get("")
    def governance(req: Request, fresh: bool = False): return h.view(require(req), fresh)

    return r
