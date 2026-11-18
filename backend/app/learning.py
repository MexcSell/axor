"""Learning (Agents → Learning, hub-learning.js): how AXoR's agents get better from results, read across every system that
already learns. It sits beside Knowledge (the sidebar section: what AXoR knows) and Intelligence (what AXoR does with it: a
mission's Intelligence Analyst brief, recommendations). On a mission the three come in order: DISCOVER retrieves knowledge,
the brief analyses it, LEARN keeps lessons that the next mission's DISCOVER reads back.

`GET /api/learning` reads, for the signed-in user:
- loop: the three capabilities in numbers: knowledge (Knowledge hub items, Workforce memories, mission lessons), intelligence
  (missions that got an Intelligence brief), learning (lessons read back by later missions, improvements adopted, promoted
  versions kept after their watch).
- lessons: Mission Control's lessons (mx_lessons), each with the mission it came from and how often later missions used it.
- improvements: Workforce improvements (wf_improvements: root cause, change, trial result, promoted or not) and, for
  administrators, the Competition teams' Workflow improvements (mb_improvements via mb_flows: the Improvement Engineer's
  diagnoses and trials). Workflow data is admin-only, as on the Workflow and in My workspace → Overview.
- watches: after a Workflow improvement is promoted on its own, the watch that keeps it or rolls it back (mb_watches, admins).
- sprints: the Agent Upgrade Factory's sprints on the user's Competition teams (au_sprints) and the versions they produced.
- memory: Workforce memory in use (active, cited, helped).
Only open Competition teams count (Hubs._comps), like Agent evaluation: a closed competition's Workflow improvements drop off.

`DELETE /api/learning/lessons/{id}` forgets one of the user's own mission lessons, so a wrong lesson stops steering future plans.
It's the one write on a hub page (hubs.py's pages are read-only); it never touches another system's data.

Each source is read on its own; a missing table or a failing source is left out (or lands in `errors`), never failing the page.
Nothing here starts work or spends tokens. Answers are kept per user for a few seconds (Hubs.cached).
"""
import time

from fastapi import APIRouter, HTTPException, Request

from . import mining, orchestrator, workforce
from .hubs import Hubs, _j
from .mining import _clip

LESSONS = 200   # lessons listed
ROWS = 60       # improvements, watches and sprints listed per source
BRIEFS = 500    # recent missions checked for an Intelligence brief


class Learning(Hubs):
    def view(self, me, fresh=False):
        self._agents(me)
        return self.cached("learning", me, self._learning, fresh)

    def forget(self, me, lid):
        self._agents(me)
        if not self._has("mx_lessons"): raise HTTPException(404, "No such lesson.")
        if not self.db.q("SELECT 1 FROM mx_lessons WHERE id=? AND user_id=?", (lid, me["id"]), one=True):
            raise HTTPException(404, "No such lesson.")
        self.db.q("DELETE FROM mx_lessons WHERE id=? AND user_id=?", (lid, me["id"]))
        self.cache.pop(("learning", me["id"]), None)
        return {"ok": True}

    def _learning(self, me, out):
        uid, admin = me["id"], me.get("role") == "admin"
        loop = {"knowledge": {"kb": 0, "memories": 0, "lessons": 0}, "intelligence": {"briefs": 0, "missions": 0},
                "learning": {"used": 0, "adopted": 0, "kept": 0, "rolled_back": 0}}
        out.update({"loop": loop, "lessons": [], "improvements": [], "watches": [], "sprints": [], "memory": None,
                    "sources": {"missions": False, "workforce": False, "workflow": False, "upgrade": False, "knowledge": False}})
        comps = self._comps(me)
        labels = {w["id"]: self._label(w) for w in comps}

        def knowledge():
            if not self._has("kb_items"): return
            loop["knowledge"]["kb"] = self.db.q("SELECT COUNT(*) n FROM kb_items WHERE user_id=? AND status='kept'", (uid,), one=True)["n"]
            out["sources"]["knowledge"] = True

        def missions():
            if not self._has("mx_lessons"): return
            out["sources"]["missions"] = True
            titles = {}
            if self._has("mx_missions"):
                ms = self.db.q("SELECT id, title, discovery FROM mx_missions WHERE user_id=? ORDER BY id DESC LIMIT ?", (uid, BRIEFS))
                titles = {m["id"]: m["title"] for m in ms}
                loop["intelligence"]["missions"] = len(ms)
                loop["intelligence"]["briefs"] = sum(1 for m in ms if (_j(m["discovery"], {}) or {}).get("brief"))
            agg = self.db.q("SELECT COUNT(*) n, COALESCE(SUM(used), 0) used FROM mx_lessons WHERE user_id=?", (uid,), one=True)
            loop["knowledge"]["lessons"], loop["learning"]["used"] = agg["n"], agg["used"]
            for x in self.db.q("SELECT id, mission_id, kind, text, outcome, used, created FROM mx_lessons WHERE user_id=? ORDER BY id DESC LIMIT ?", (uid, LESSONS)):
                out["lessons"].append({"id": x["id"], "kind": x["kind"] or "worked", "text": _clip(x["text"] or "", 400), "outcome": x["outcome"] or "",
                                       "used": x["used"] or 0, "mission": titles.get(x["mission_id"]) or (f"Mission #{x['mission_id']}" if x["mission_id"] else ""),
                                       "mission_id": x["mission_id"], "ts": x["created"],
                                       "planners": orchestrator.lesson_for_planners(x["outcome"])})  # G5-5 L5.2: else an observation

        def workforce_():
            if not (workforce.ENABLED and self._has("wf_improvements")): return
            out["sources"]["workforce"] = True
            names = {a["id"]: a["name"] for a in self.db.q("SELECT id, name FROM wf_agents WHERE user_id=?", (uid,))} if self._has("wf_agents") else {}
            for i in self.db.q("""SELECT id, agent_id, root_cause, change, status, trials, result, tokens, version, decided_by, created, updated
                                  FROM wf_improvements WHERE user_id=? ORDER BY id DESC LIMIT ?""", (uid, ROWS)):
                out["improvements"].append({"system": "workforce", "who": names.get(i["agent_id"]) or f"Agent #{i['agent_id']}", "where": "Workforce",
                                            "why": _clip(i["root_cause"] or "", 400), "change": _clip(i["change"] or "", 400), "status": i["status"] or "",
                                            "result": _clip(i["result"] or "", 400), "version": i["version"], "by": i["decided_by"] or "",
                                            "ts": i["updated"] or i["created"], "go": {"view": "workforce"}})
            loop["learning"]["adopted"] += self.db.q("SELECT COUNT(*) n FROM wf_improvements WHERE user_id=? AND status='promoted'", (uid,), one=True)["n"]
            if self._has("wf_memory"):
                m = self.db.q("SELECT COUNT(*) n, COALESCE(SUM(cited), 0) cited, COALESCE(SUM(helped), 0) helped FROM wf_memory WHERE user_id=? AND status='active'", (uid,), one=True)
                out["memory"] = {"active": m["n"], "cited": m["cited"], "helped": m["helped"]}
                loop["knowledge"]["memories"] = m["n"]

        def workflow():
            # administrators only, like the Workflow itself; flows of the user's open teams
            if not (admin and mining.ENABLED and comps and self._has("mb_flows") and self._has("mb_improvements")): return
            ids = list(labels)
            flows = {f["id"]: f["comp_id"] for f in self.db.q(f"SELECT id, comp_id FROM mb_flows WHERE comp_id IN ({','.join('?' * len(ids))})", ids)}
            out["sources"]["workflow"] = True
            if not flows: return
            fids, ph = list(flows), ",".join("?" * len(flows))
            names = {a["id"]: a["name"] for a in self.db.q(f"SELECT id, name FROM mb_agents WHERE flow_id IN ({ph})", fids)} if self._has("mb_agents") else {}
            for i in self.db.q(f"""SELECT id, flow_id, agent_id, trigger, root_cause, change, status, result, cost, version, decided_by, margin, created, updated
                                   FROM mb_improvements WHERE flow_id IN ({ph}) ORDER BY id DESC LIMIT ?""", (*fids, ROWS)):
                wid = flows[i["flow_id"]]
                out["improvements"].append({"system": "teams", "who": names.get(i["agent_id"]) or f"Agent #{i['agent_id']}", "where": labels.get(wid, ""),
                                            "why": _clip(i["root_cause"] or i["trigger"] or "", 400), "change": _clip(i["change"] or "", 400), "status": i["status"] or "",
                                            "result": _clip(i["result"] or "", 400), "version": i["version"], "by": i["decided_by"] or "", "cost": i["cost"],
                                            "ts": i["updated"] or i["created"], "go": {"view": "teams", "wid": wid, "sub": "flow"}})
            loop["learning"]["adopted"] += self.db.q(f"SELECT COUNT(*) n FROM mb_improvements WHERE flow_id IN ({ph}) AND status IN ('promoted','applied')", fids, one=True)["n"]
            if self._has("mb_watches"):
                for w in self.db.q(f"""SELECT flow_id, agent_id, from_version, to_version, baseline, status, score, basis, result, started, ended
                                       FROM mb_watches WHERE flow_id IN ({ph}) ORDER BY id DESC LIMIT ?""", (*fids, ROWS)):
                    wid = flows[w["flow_id"]]
                    out["watches"].append({"who": names.get(w["agent_id"]) or f"Agent #{w['agent_id']}", "where": labels.get(wid, ""), "from": w["from_version"],
                                           "to": w["to_version"], "status": w["status"] or "", "score": w["score"], "baseline": w["baseline"], "basis": w["basis"],
                                           "result": _clip(w["result"] or "", 300), "ts": w["ended"] or w["started"], "go": {"view": "teams", "wid": wid, "sub": "flow"}})
                for k in ("kept", "rolled_back"):
                    loop["learning"][k] = self.db.q(f"SELECT COUNT(*) n FROM mb_watches WHERE flow_id IN ({ph}) AND status=?", (*fids, k), one=True)["n"]

        def upgrade():
            if not (mining.ENABLED and comps and self._has("au_sprints")): return
            out["sources"]["upgrade"] = True
            ids = list(labels)
            ph = ",".join("?" * len(ids))
            made = {}
            if self._has("au_versions"):
                for v in self.db.q(f"SELECT comp_id, COUNT(*) n FROM au_versions WHERE comp_id IN ({ph}) AND version>1 GROUP BY comp_id", ids):
                    made[v["comp_id"]] = v["n"]
            for s in self.db.q(f"""SELECT id, comp_id, status, minutes, tokens, token_cap, started, deadline, finished, note FROM au_sprints
                                   WHERE comp_id IN ({ph}) AND user_id=? ORDER BY id DESC LIMIT ?""", (*ids, uid, ROWS)):
                agents = self.db.q("SELECT status, COUNT(*) n FROM au_agents WHERE sprint_id=? GROUP BY status", (s["id"],)) if self._has("au_agents") else []
                out["sprints"].append({"where": labels.get(s["comp_id"], ""), "status": s["status"] or "", "minutes": s["minutes"], "tokens": s["tokens"],
                                       "cap": s["token_cap"], "agents": {a["status"] or "": a["n"] for a in agents}, "versions": made.get(s["comp_id"], 0),
                                       "note": _clip(s["note"] or "", 300), "ts": s["finished"] or s["started"],
                                       "go": {"view": "teams", "wid": s["comp_id"], "sub": "upgrade"}})

        for label, fn in (("Knowledge hub", knowledge), ("Mission lessons", missions), ("Workforce", workforce_),
                          ("Workflow improvements", workflow), ("Upgrade sprints", upgrade)):
            self._try(out, label, fn)
        out["improvements"].sort(key=lambda x: -(x["ts"] or 0))


def build(db, require, ov, co=None):
    r = APIRouter(prefix="/api/learning")
    h = Learning(db, ov, co)
    r.state = {"learning": h}

    @r.get("")
    def learning(req: Request, fresh: bool = False): return h.view(require(req), fresh)

    @r.delete("/lessons/{lid}")
    def forget(lid: int, req: Request): return h.forget(require(req), lid)

    return r
