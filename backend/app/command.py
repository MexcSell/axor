"""AXoR 2.0 Command Center and Approval Center (command.js): one read of everything the user's agents do and everything that waits
for them, across the agent systems.

- `GET /api/command`: My workspace's Overview (overview.py: needs, teams, at work, miners, spend, activity) plus the
  organization's shape (the Company's projects, tasks and agents, Workforce's missions and agents, long tasks) and the
  approval queue below, so the Command Center draws from one call.
- The approval queue: each request on its own, not a count, from My subnets (the Captain's actions), the Company (hash-bound
  approvals), Workforce (actions, mission plans, tested improvements), Agent HQ (fixes, administrators), the Portfolio (findings
  to share everywhere), and the waits the Overview already works out (Competition teams, the Workflow, the project team).
  The history is the latest decisions in the same systems.

Nothing here approves, rejects or starts anything: every item carries where it is decided (`go`), and the decision is made on
that page, with its evidence, by the system that owns it (Company approvals stay single-use and bound to their artifact).
Each source is read on its own and gated like its own page; one that fails lands in `errors`.
"""
import json, logging, re, time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import company, hq, infiagent, mining, workforce
from .mining import _clip

CACHE = 8  # seconds an answer is kept per user, like the Overview's
STALE_H = 72  # a request waiting this long is flagged stale: decide it, or archive it where its system allows (Approval Center)
OVERVIEW_WAITS = ("teams", "workflow", "projects")  # needs the Overview works out that aren't single requests in a table
log = logging.getLogger("command")


def _ts(x):
    return x or 0


class Command:
    def __init__(self, db, ov, co=None):
        self.db, self.ov, self.co = db, ov, co
        self.cache = {}

    def _has(self, table):
        return bool(self.db.q("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,), one=True))

    def view(self, me, fresh=False):
        hit = self.cache.get(me["id"])
        if hit and not fresh and time.time() - hit[0] < CACHE: return hit[1]
        out = self._build(me, fresh)
        self.cache[me["id"]] = (time.time(), out)
        return out

    def _build(self, me, fresh):
        admin, agents = me.get("role") == "admin", self.ov._agents_ok(me)
        out = {"at": time.time(), "admin": admin, "agents": agents, "overview": self.ov.view(me, fresh),
               "pending": [], "history": [], "org": {}, "sources": {}, "errors": []}
        steps = (("mining", "My subnets", agents and mining.ENABLED and self._has("mh_actions"), self._mining),
                 ("company", "Company", agents and self.co is not None, self._company),
                 ("workforce", "Workforce", agents and workforce.ENABLED and self._has("wf_actions"), self._workforce),
                 ("hq", "Agent HQ", admin and hq.ENABLED and self._has("hq_fixes"), self._hq),
                 ("portfolio", "Portfolio", agents and mining.ENABLED and self._has("mk_items"), self._portfolio),
                 ("longtasks", "Long tasks", agents and infiagent.ENABLED and self._has("ia_tasks"), self._longtasks),
                 ("knowledge", "Knowledge hub", agents and self._has("kb_proposals"), self._knowledge),
                 ("market", "Agent Marketplace", agents and self._has("amp_approvals"), self._market),
                 ("missions", "Mission Control", agents and self._has("mx_missions"), self._missions),
                 ("org", "Organization", agents and self._has("og_requests"), self._organization))
        for key, label, on, fn in steps:
            out["sources"][key] = bool(on)
            if not on: continue
            try: fn(me, out)
            except Exception as e:  # noqa: BLE001 - one source failing leaves the rest
                log.exception("command %s", key)
                out["sources"][key] = False
                out["errors"].append(f"{label}: {_clip(str(e), 200)}")
        for n in out["overview"]["needs"]:
            if n["source"] in OVERVIEW_WAITS:
                out["pending"].append({"source": n["source"], "id": None, "kind": "wait", "level": n["level"], "title": n["title"], "detail": n["detail"],
                                       "where": n["where"], "go": n["go"], "label": n["label"], "ts": n.get("ts"), "risk": None, "expires": None})
        rank = {"stop": 0, "warn": 1, "info": 2}
        out["pending"].sort(key=lambda x: (rank.get(x["level"], 1), -_ts(x["ts"])))
        out["pending"], dupes = self._tidy(out["pending"], out["at"])
        out["history"] = sorted(out["history"], key=lambda x: -_ts(x["ts"]))[:40]
        by = {}
        for p in out["pending"]: by[p["source"]] = by.get(p["source"], 0) + 1
        out["counts"] = {"pending": len(out["pending"]), "urgent": sum(p["level"] == "stop" for p in out["pending"]), "by_source": by,
                         "stale": sum(1 for p in out["pending"] if p["stale"]), "duplicates": dupes, "stale_h": STALE_H}
        return out

    @staticmethod
    def _tidy(pending, now):
        """Each request once: the same request asked again (same system, same kind, same subject) folds into the newest, which
        lists the copies. And how long each has waited: STALE_H hours or more is stale. Returns (pending, copies folded)."""
        subject = lambda p: re.sub(r"\s+", " ", re.sub(r"^[^:]{0,40}:\s*", "", p["title"] or "")).strip().lower()
        first, out, folded = {}, [], 0
        for p in sorted(pending, key=lambda x: -_ts(x["ts"])):
            p["age_h"] = round((now - p["ts"]) / 3600, 1) if p.get("ts") else None
            p["stale"] = bool(p["age_h"] is not None and p["age_h"] >= STALE_H)
            p["archive"] = p["source"] == "mining" and p["kind"] == "import" and p["id"] is not None  # imports can be saved for later (mining_sources draft)
            key = (p["source"], p["kind"], subject(p)) if p["id"] is not None else None
            if key and key in first:
                keep = first[key]; keep.setdefault("copies", []).append({"id": p["id"], "ts": p["ts"], "archive": p["archive"]}); folded += 1
                keep["stale"] = keep["stale"] or p["stale"]
                if p["age_h"] is not None and (keep["age_h"] is None or p["age_h"] > keep["age_h"]): keep["age_h"] = p["age_h"]  # waiting since the first ask
                continue
            if key: first[key] = p
            out.append(p)
        order = {id(p): i for i, p in enumerate(pending)}
        return sorted(out, key=lambda p: order[id(p)]), folded

    sources = None  # mining_sources.Sources (main.py): imports archived from here are "saved for later" there, by its own rule

    def archive(self, me, b, ip):
        """Take a stale or repeated request out of the queue without deciding it, through its own system: an imported competition is
        saved for later (Import competitions → Drafts), where it can be put back in the queue. Other systems decide on their pages."""
        if b.source == "mining" and b.kind == "import":
            if self.sources is None: raise HTTPException(503, "Import competitions isn't running on this server.")
            for cid in b.ids: self.sources.draft(me, cid, True, ip)
            self.cache.pop(me["id"], None)
            return {"archived": len(b.ids), **self.view(me, True)}
        raise HTTPException(400, "Requests of this kind are decided on their own page: open it to approve or reject.")

    @staticmethod
    def _item(out, source, id_, kind, level, title, detail, where, go, label, ts, risk=None, expires=None):
        out["pending"].append({"source": source, "id": id_, "kind": kind, "level": level, "title": _clip(title or "", 160), "detail": _clip(detail or "", 400),
                               "where": where, "go": go, "label": label, "ts": ts, "risk": risk, "expires": expires})

    @staticmethod
    def _done(out, source, title, status, by, ts, note=""):
        out["history"].append({"source": source, "title": _clip(title or "", 160), "status": status, "by": by or "", "ts": ts, "note": _clip(note or "", 240)})

    # ---------- My subnets: the Captain's actions ----------
    def _mining(self, me, out):
        camps = {r["id"]: r["netuid"] for r in self.db.q("SELECT id, netuid FROM mh_campaigns WHERE user_id=?", (me["id"],))}
        if not camps: return
        ids, marks = list(camps), ",".join("?" * len(camps))
        for a in self.db.q(f"SELECT id, campaign_id, kind, title, detail, reason, safe, created FROM mh_actions WHERE campaign_id IN ({marks}) AND status='awaiting' ORDER BY id DESC", ids):
            self._item(out, "mining", a["id"], a["kind"] or "action", "warn", a["title"], a["reason"] or a["detail"], f"SN{camps[a['campaign_id']]}", {"view": "mining"},
                       "Review in My subnets", a["created"], None if a["safe"] else "needs care")
        for a in self.db.q(f"""SELECT title, status, decided_by, decided, result FROM mh_actions WHERE campaign_id IN ({marks}) AND decided IS NOT NULL
                               ORDER BY decided DESC LIMIT 12""", ids):
            self._done(out, "mining", a["title"], a["status"], a["decided_by"], a["decided"], a["result"])
        if self._has("mw_candidates"):  # Import competitions: what waits for review (mining_sources.py)
            for c in self.db.q("SELECT id, kind, fields, verdict, created FROM mw_candidates WHERE user_id=? AND status='ready' ORDER BY id DESC LIMIT 40", (me["id"],)):
                f = json.loads(c["fields"] or "{}")
                self._item(out, "mining", c["id"], "import", "warn" if c["verdict"] == "fail" else "info",
                           f"{'Update from a source' if c['kind'] == 'update' else 'Imported competition'}: {f.get('name') or f.get('url') or 'unnamed'}",
                           {"pass": "Checks pass.", "warning": "Some fields need a look.", "fail": "A check fails: fix it before approving."}.get(c["verdict"] or "", ""),
                           f"SN{f['netuid']}" if f.get("netuid") is not None else "Import competitions", {"view": "teams", "intake": True}, "Review the import", c["created"])
            for c in self.db.q("SELECT fields, status, reviewer, reviewed, note FROM mw_candidates WHERE user_id=? AND status IN ('approved','rejected') ORDER BY reviewed DESC LIMIT 8", (me["id"],)):
                self._done(out, "mining", f"Import: {json.loads(c['fields'] or '{}').get('name') or 'a competition'}", c["status"], c["reviewer"], c["reviewed"], c["note"])

    # ---------- the Company: hash-bound approvals, and the organization's shape ----------
    def _company(self, me, out):
        c = self.co._company(me, create=False)  # never creates the user's company just by looking
        if not c: out["org"]["company"] = None; return
        cid, now = c["id"], time.time()
        projects = {p["id"]: p for p in self.db.q("SELECT id, name, status FROM co_projects WHERE company_id=?", (cid,))}
        for a in self.db.q("SELECT id, project_id, action_type, title, reason, risk, requested_by, created, expires_at FROM co_approvals WHERE company_id=? AND status='pending' AND expires_at>? ORDER BY id DESC",
                           (cid, now)):
            label = (company.ACTIONS.get(a["action_type"]) or [a["action_type"]])[0]
            self._item(out, "company", a["id"], a["action_type"], "warn", f"{label}: {a['title']}", a["reason"], (projects.get(a["project_id"]) or {}).get("name") or c["name"],
                       {"view": "company", "tab": "approvals"}, "Decide in Company", a["created"], a["risk"], a["expires_at"])
        for a in self.db.q("SELECT title, status, decided_by, decided_at, decision_reason FROM co_approvals WHERE company_id=? AND decided_at IS NOT NULL ORDER BY decided_at DESC LIMIT 12", (cid,)):
            self._done(out, "company", a["title"], a["status"], a["decided_by"], a["decided_at"], a["decision_reason"])
        n = lambda sql, *p: self.db.q(sql, (cid, *p), one=True)["n"]
        out["org"]["company"] = {"name": c["name"], "projects": sum(p["status"] != "archived" for p in projects.values()),
                                 "active_projects": sum(p["status"] == "active" for p in projects.values()),
                                 "divisions": n("SELECT COUNT(*) n FROM co_divisions WHERE company_id=?"),
                                 "agents": n("SELECT COUNT(*) n FROM co_agents WHERE company_id=? AND status!='archived'"),
                                 "busy": n("""SELECT COUNT(DISTINCT m.agent_id) n FROM co_members m JOIN co_teams t ON t.id=m.team_id WHERE t.company_id=? AND t.status='active'"""),
                                 "running": n("SELECT COUNT(*) n FROM co_tasks WHERE company_id=? AND status IN ('running','evaluating')"),
                                 "open": n("SELECT COUNT(*) n FROM co_tasks WHERE company_id=? AND status IN ('pending','proposed','running','evaluating')"),
                                 "done_week": n("SELECT COUNT(*) n FROM co_tasks WHERE company_id=? AND status='done' AND finished>?", now - 7 * 86400)}

    # ---------- the Organization: change requests, task go-aheads and tasks escalated to you (organization.py) ----------
    def _organization(self, me, out):
        go = {"view": "org", "tab": "approvals"}
        for r in self.db.q("SELECT id, kind, title, why, by, created, expires FROM og_requests WHERE user_id=? AND status='pending' AND expires>? ORDER BY id DESC",
                           (me["id"], time.time())):
            self._item(out, "org", r["id"], r["kind"], "warn" if r["kind"] in ("autonomy", "task_go") else "info", r["title"], r["why"],
                       f"Proposed by {r['by']}", go, "Decide in Organization", r["created"], "needs care" if r["kind"] in ("autonomy", "task_go") else None, r["expires"])
        for t in self.db.q("SELECT id, title, created, updated FROM og_tasks WHERE user_id=? AND status='escalated' AND holder_key IS NULL ORDER BY id DESC", (me["id"],)):
            self._item(out, "org", t["id"], "escalation", "warn", f"Escalated to you: {t['title']}", "Nobody below you could resolve it: decide, reassign or cancel.",
                       "Organization", {"view": "org", "tab": "delegation"}, "Open in Organization", t["updated"])
        for r in self.db.q("SELECT title, status, decided_by, decided, note FROM og_requests WHERE user_id=? AND decided IS NOT NULL ORDER BY decided DESC LIMIT 12", (me["id"],)):
            self._done(out, "org", r["title"], r["status"], r["decided_by"], r["decided"], r["note"])

    # ---------- Workforce: actions, mission plans and tested improvements ----------
    def _workforce(self, me, out):
        uid, go = me["id"], {"view": "workforce"}
        for a in self.db.q("SELECT id, agent, action, details, risk, risk_why, reason, created FROM wf_actions WHERE user_id=? AND status='pending' ORDER BY id DESC", (uid,)):
            self._item(out, "workforce", a["id"], "action", "stop" if a["risk"] == "high" else "warn", f"{a['agent'] or 'An agent'}: {a['action']}",
                       a["reason"] or a["risk_why"] or a["details"], "Workforce", go, "Decide in Workforce", a["created"], a["risk"])
        for m in self.db.q("SELECT id, title, goal, updated FROM wf_missions WHERE user_id=? AND status='waiting' ORDER BY id DESC", (uid,)):
            self._item(out, "workforce", m["id"], "plan", "warn", f"Mission plan: {m['title']}", m["goal"], "Workforce", go, "Review the plan", m["updated"])
        if self._has("wf_improvements"):
            for i in self.db.q("SELECT id, change, root_cause, updated FROM wf_improvements WHERE user_id=? AND status='better' ORDER BY id DESC", (uid,)):
                self._item(out, "workforce", i["id"], "improvement", "info", f"Tested improvement: {_clip(i['change'] or '', 120)}", i["root_cause"], "Workforce", go,
                           "Promote or drop", i["updated"])
        for a in self.db.q("SELECT agent, action, status, decided_by, decided, decision_note FROM wf_actions WHERE user_id=? AND decided IS NOT NULL ORDER BY decided DESC LIMIT 12", (uid,)):
            self._done(out, "workforce", f"{a['agent'] or 'An agent'}: {a['action']}", a["status"], a["decided_by"], a["decided"], a["decision_note"])
        q = lambda sql: self.db.q(sql, (uid,), one=True)["n"]
        out["org"]["workforce"] = {"agents": q("SELECT COUNT(*) n FROM wf_agents WHERE user_id=?") if self._has("wf_agents") else 0,
                                   "running": q("SELECT COUNT(*) n FROM wf_missions WHERE user_id=? AND status='running'"),
                                   "missions": q("SELECT COUNT(*) n FROM wf_missions WHERE user_id=?"),
                                   "done": q("SELECT COUNT(*) n FROM wf_missions WHERE user_id=? AND status='done'")}

    # ---------- Agent HQ: fixes the leads reviewed (administrators) ----------
    def _hq(self, me, out):
        go = {"view": "hq"}
        for f in self.db.q("SELECT id, label, reason, team, safe, created FROM hq_fixes WHERE status='awaiting' ORDER BY id DESC LIMIT 50"):
            self._item(out, "hq", f["id"], "fix", "warn", f["label"] or "A fix", f["reason"], f"Agent HQ · {f['team'] or ''}".rstrip(" ·"), go, "Decide in Agent HQ",
                       f["created"], None if f["safe"] else "needs care")
        for f in self.db.q("SELECT label, status, decided_by, decided, result FROM hq_fixes WHERE decided IS NOT NULL ORDER BY decided DESC LIMIT 10"):
            self._done(out, "hq", f["label"], f["status"], f["decided_by"], f["decided"], f["result"])

    # ---------- the Portfolio: findings waiting to be shared everywhere ----------
    def _portfolio(self, me, out):
        rows = self.db.q("SELECT id, netuid, lesson, why, updated FROM mk_items WHERE user_id=? AND scope='global_candidate' ORDER BY id DESC LIMIT 30", (me["id"],))
        for k in rows:
            self._item(out, "portfolio", k["id"], "finding", "info", f"Share everywhere: {_clip(k['lesson'] or '', 120)}", k["why"], f"SN{k['netuid']}" if k["netuid"] is not None else "Portfolio",
                       {"view": "portfolio"}, "Review in Portfolio", k["updated"])

    # ---------- the Knowledge hub: proposals to adopt imported capabilities, imports waiting in preview ----------
    def _knowledge(self, me, out):
        for p in self.db.q("SELECT id, title, why, created FROM kb_proposals WHERE user_id=? AND status='pending' ORDER BY id DESC LIMIT 40", (me["id"],)):
            self._item(out, "knowledge", p["id"], "adopt", "info", p["title"], p["why"], "Knowledge hub", {"view": "knowledge", "tab": "adopt", "id": p["id"]},
                       "Review the change", p["created"], "changes an agent")
        for s in self.db.q("SELECT id, name, kind, created FROM kb_sources WHERE user_id=? AND status='preview' ORDER BY id DESC LIMIT 10", (me["id"],)):
            self._item(out, "knowledge", s["id"], "import", "info", f"Import waiting: {s['name']}", "Pick what to keep, then apply it.", "Knowledge hub",
                       {"view": "knowledge", "tab": "import", "id": s["id"]}, "Review the import", s["created"])
        for p in self.db.q("SELECT title, status, decided_by, decided, result FROM kb_proposals WHERE user_id=? AND decided IS NOT NULL ORDER BY decided DESC LIMIT 10", (me["id"],)):
            self._done(out, "knowledge", p["title"], p["status"], p["decided_by"], p["decided"], p["result"])
        try:  # company knowledge waiting for review (knowledge_spaces.py): agents' contributions and what was published from My Knowledge
            for k in self.db.q("""SELECT id, title, contributor, owner, created FROM kb_items WHERE user_id=? AND space='company' AND state='submitted' AND status='kept'
                                  ORDER BY id DESC LIMIT 40""", (me["id"],)):
                self._item(out, "knowledge", k["id"], "review", "info", f"Review knowledge: {k['title']}", f"Submitted by {k['owner'] or k['contributor'] or 'you'}",
                           "Knowledge Hub", {"view": "knowledge", "tab": "review", "id": k["id"]}, "Review it", k["created"], "becomes company knowledge agents rely on")
        except Exception:  # an older database without the space columns yet
            pass
        try:  # agents asking to read a scope they can't (knowledge_improve.py)
            for r in self.db.q("SELECT id, label, scope_label, reason, created FROM kb_access WHERE user_id=? AND status='pending' ORDER BY id DESC LIMIT 20", (me["id"],)):
                self._item(out, "knowledge", r["id"], "access", "warn", f"{r['label']} asks to read {r['scope_label']}", r["reason"], "Knowledge Hub",
                           {"view": "knowledge", "tab": "review"}, "Decide", r["created"], "widens what an agent may read")
        except Exception:  # no kb_access table yet
            pass

    # ---------- the Agent Marketplace: versions waiting for approval to join the workforce, regressions found by re-evaluation ----------
    def _market(self, me, out):
        for a in self.db.q("""SELECT a.id, a.package_id, a.version, a.summary, a.requested, p.name FROM amp_approvals a JOIN amp_packages p ON p.id=a.package_id
                              WHERE a.user_id=? AND a.status='pending' ORDER BY a.id DESC LIMIT 30""", (me["id"],)):
            self._item(out, "market", a["id"], "approve", "warn", f"Activate {a['name']} v{a['version']}", a["summary"], "Agent Marketplace",
                       {"view": "market", "id": a["package_id"]}, "Review the agent", a["requested"], "an imported agent joins your workforce")
        for p in self.db.q("SELECT id, name, alert, updated FROM amp_packages WHERE user_id=? AND status='active' AND alert IS NOT NULL", (me["id"],)):
            self._item(out, "market", p["id"], "regression", "info", f"{p['name']}: score dropped", p["alert"], "Agent Marketplace",
                       {"view": "market", "id": p["id"]}, "Look at the evaluation", p["updated"])
        for a in self.db.q("""SELECT a.version, a.status, a.decided_by, a.decided, a.note, p.name FROM amp_approvals a JOIN amp_packages p ON p.id=a.package_id
                              WHERE a.user_id=? AND a.decided IS NOT NULL ORDER BY a.decided DESC LIMIT 10""", (me["id"],)):
            self._done(out, "market", f"{a['name']} v{a['version']}", a["status"], a["decided_by"], a["decided"], a["note"])

    # ---------- Mission Control: questions a mission can't start without, paused missions, hash-bound requests ----------
    def _missions(self, me, out):
        uid, now = me["id"], time.time()
        for m in self.db.q("SELECT id, title, status, pause_reason, updated FROM mx_missions WHERE user_id=? AND status IN ('needs_input','paused') ORDER BY id DESC LIMIT 20", (uid,)):
            ask = m["status"] == "needs_input"
            if ask and self.db.q("SELECT 1 FROM mx_requests WHERE mission_id=? AND kind IN ('team','plan','recover') AND status='pending'", (m["id"],), one=True): continue  # its request row says it
            self._item(out, "missions", m["id"], "question" if ask else "paused", "warn" if ask else "info", f"{'Answer' if ask else 'Paused'}: {m['title']}",
                       "The mission can't start without your answers." if ask else m["pause_reason"], "Mission Control", {"view": "mos", "id": m["id"]},
                       "Answer" if ask else "Open the mission", m["updated"])
        for r in self.db.q("""SELECT r.id, r.mission_id, r.kind, r.label, r.action, r.created, r.expires, m.title FROM mx_requests r JOIN mx_missions m ON m.id=r.mission_id
                              WHERE r.user_id=? AND r.status='pending' AND r.expires>? ORDER BY r.id DESC LIMIT 40""", (uid, now)):
            self._item(out, "missions", r["id"], "approval", "warn", r["action"], f"From the mission “{r['title']}”. " +
                       ("Approved, AXoR creates the team and the mission runs on it; or use a team you have, or go on without one." if r["kind"] == "team"
                        else "Approved, the mission runs exactly this plan; declined with a note, AXoR plans again." if r["kind"] == "plan"
                        else "Approved, AXoR tries again; declined, it delivers what's done." if r["kind"] == "recover"
                        else "AXoR doesn't carry it out: approved, it's yours to do."),
                       "Mission Control", {"view": "mos", "id": r["mission_id"]}, "Review the request", r["created"], r["label"], r["expires"])
        for r in self.db.q("SELECT action, status, decided FROM mx_requests WHERE user_id=? AND decided IS NOT NULL ORDER BY decided DESC LIMIT 10", (uid,)):
            self._done(out, "missions", r["action"], r["status"], me["username"], r["decided"])
        rows = self.db.q("SELECT status, COUNT(*) n FROM mx_missions WHERE user_id=? GROUP BY status", (uid,))
        out["org"]["missions"] = {r["status"]: r["n"] for r in rows}

    # ---------- long tasks (InfiAgent) ----------
    def _longtasks(self, me, out):
        rows = self.db.q("SELECT status, COUNT(*) n FROM ia_tasks WHERE user_id=? GROUP BY status", (me["id"],))
        by = {r["status"]: r["n"] for r in rows}
        out["org"]["longtasks"] = {"total": sum(by.values()), "running": by.get("running", 0), "by_status": by}


class ArchiveIn(BaseModel):
    source: str = Field(..., max_length=20)
    kind: str = Field(..., max_length=20)
    ids: list[int] = Field(..., min_length=1, max_length=50)


def build(db, require, ov, co=None, ip=None):
    r = APIRouter(prefix="/api/command")
    cmd = Command(db, ov, co)
    r.state = {"command": cmd}

    @r.get("")
    def view(req: Request, fresh: bool = False): return cmd.view(require(req), fresh)

    @r.post("/archive")
    def archive(b: ArchiveIn, req: Request): return cmd.archive(require(req), b, (ip or (lambda q: q.client.host if q.client else ""))(req))

    return r
