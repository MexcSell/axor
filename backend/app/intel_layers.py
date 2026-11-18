"""Intelligence layers (Control Hub → Intelligence layers, hub-layers.js, /api/layers): AXoR read as six capability layers,
each made of the parts that already do that layer's work, with live figures and health checks for the signed-in user.

The six names (mission, workforce, execution, knowledge intelligence, evaluation, adaptive intelligence) are a framing over
systems that keep their own names: Mission Intelligence and the Intelligence brief, the agent core and the model router,
Autoloop and long tasks, the Knowledge Hub and its retrieval, the Lab, Upgrade sprints and the Evolution Lab. Agent
Operations → Ecosystem (ecosystem.py) cuts the same systems into eight layers instead; neither replaces the other.

Round 2 (2026-11-09, from a review of the live page): "configured" isn't "working", so the page measures operation.
- Each part: what it does, the page that owns it, figures, and checks on its own data. A part is ok (worked this week, no
  failed check), degraded (a check failed), idle (there, quiet this week) or missing (its table or system isn't there).
- Each layer names its required parts. Operational: every required part worked this week and no part is degraded.
  Degraded: a part's check failed. Incomplete: a required part is missing. Round 5 puts the handoff ledger in the same rule:
  operational also needs work to have crossed into or out of the layer this week (when the orchestrator runs); partly working
  is some of it (a required part, or a handoff) without all of it; idle is none of it.
- Dependencies between layers, and the loop's handoffs this week (mission → workforce → execution → knowledge/evaluation →
  adaptive → back to missions), each flowing or broken.
- Execution failures classified from the run ledger (restart, quota, budget, provider, rate, timeout or network, sandbox,
  tool, the task itself) plus finished runs scored under LOW: the review asked to tell them apart.
- Improvement evidence: this week against the week before (score, failure rate, tokens and dollars per run), the regression
  rate of promotions and the last promotion, and the Evolution engine's stages with this week's counts.
- "Fix first": failed checks, warnings and quiet required parts, ordered by the review's priorities (evaluation, adaptive and
  mission first).
- /api/layers/trace?mission=N: one Mission Control mission through the six layers, from the records each layer left.

Round 5 (2026-11-10, a second review): the mission lifecycle acceptance test is the review's eight steps with the records
behind each (loop_check), the Evolution stages add Approve (your decision) and Roll back, and the Adaptive → Mission handoff
says why it's broken (no plan this week, or plans that took nothing learned).

Round 3 (G5, 2026-11-09, orchestrator.py): the layers read the orchestrator's records too. Knowledge counts items without a passage
of their current version (the old check compared items with chunk rows) and splits empty searches into "nothing readable" (access
or ingestion) and "ranked nothing in" (ranking), next to the known-item retrieval benchmark. Run scores show coverage: scored,
excluded with a reason, or named gaps by system. New parts: Learned guidance (Adaptive → Mission), Budget gateway (scoped hard
limits), Promotion monitor. Sandboxes name the top class of why runs couldn't run. The mission trace follows the correlation id.
The orchestrator's own card (handoff events, dead letters, diagnoses, limits, history) is /api/g5, fetched beside this one.

Competition teams' Workflow figures (Lab evals, Workflow improvements, watches) are for administrators only, like the Workflow
itself; only the user's open Competition teams count (Hubs._comps).

Read-only: nothing here starts work or spends tokens. Each layer is read on its own; one that fails lands in `errors` and the
rest still show. Answers are kept per user for a few seconds (Hubs.cached).
"""
import re, time

from fastapi import APIRouter, HTTPException, Request

from . import mining, workforce
from .hubs import Hubs, _j

WEEK = 7 * 86400
BRIEFS = 500      # recent missions checked for an Intelligence brief
FAILED = ("failed", "error", "lost")
LOW = 50          # a finished run scored under this is poor output
GOOD = 70         # a scored run at or over this is useful output
FAIL_RATE = 0.10  # more failed or lost runs than this (of at least MIN_N finished) degrades execution
MIN_N = 20
OPEN_DAYS = 14    # a recall still waiting for its outcome after this long is suspect
TRACE_LIST = 25
WEB = re.compile(r"exa|search|web|brave|tavily|serp|perplexity|fetch|browser", re.I)

LAYERS = (
    ("mission", "Mission intelligence", "target",
     "Understands a goal, researches it, plans the work and decides what comes next.", "P0"),
    ("workforce", "Workforce intelligence", "group",
     "Knows who does the work: agents, teams, roles, reporting lines and which model each call runs on.", "P1"),
    ("execution", "Execution intelligence", "zap",
     "Carries the work out: runs, tools, sandboxes, budgets, retries and recovery after a restart.", "P1"),
    ("knowledge", "Knowledge intelligence", "book",
     "What agents know and find: the Knowledge Hub, retrieval with citations, lessons and memory.", "P1"),
    ("evaluation", "Evaluation", "trophy",
     "Scores the work and tests every change against the current version before it counts.", "P0"),
    ("adaptive", "Adaptive intelligence", "cycle",
     "Changes from results: promotes what measured better, rolls back what didn't, reuses lessons.", "P0"),
)
TITLE = {k: t for k, t, *_ in LAYERS}
# the parts a layer can't work without: missing → incomplete; all of them working this week (and nothing degraded) → operational
REQUIRED = {"mission": ("Mission engine", "Intelligence brief"), "workforce": ("Agent registry", "Model router"),
            "execution": ("Agent runs",), "knowledge": ("Knowledge Hub", "Retrieval"),
            "evaluation": ("Run scores", "Evolution experiments"), "adaptive": ("Evolution Lab", "Recall track record")}
DEPENDS = {
    "mission": (("knowledge", "Research reads the Knowledge Hub, lessons and earlier missions"),
                ("evaluation", "The next mission is planned from verified outcomes")),
    "workforce": (("evaluation", "The router picks each model from scored runs"),
                  ("knowledge", "Agents recall memories and lessons")),
    "execution": (("mission", "Runs carry out a plan"), ("workforce", "Who runs it, on which model")),
    "knowledge": (("execution", "Lessons, notes and experiences come from finished work"),),
    "evaluation": (("execution", "Without runs there's nothing to score"),),
    "adaptive": (("evaluation", "A change is promoted only on measured evidence"), ("knowledge", "Lessons and recall outcomes"),
                 ("execution", "Failures to diagnose")),
}
# failure classes, from a failed run's error text: since 2026-11-11 one taxonomy in orchestrator.py (G5 Phase 1); these names
# stay importable from here for the modules that used them
from .orchestrator import FAIL_LABEL, fail_class  # noqa: E402
from .orchestrator import _SANDBOX_ERR as SANDBOX, _TOOL_ERR as TOOL  # noqa: E402,F401


def brief_state(disc):
    """A mission's Intelligence brief: researched / no_web (researched without the open web) / skipped / none (discovery ran
    without one) / pending (not discovered yet)."""
    if not isinstance(disc, dict) or not disc: return "pending", ""
    b = disc.get("brief")
    if not isinstance(b, dict) or not b: return "none", ""
    if b.get("skipped"): return "skipped", str(b["skipped"])
    return ("no_web" if b.get("web") is False else "researched"), ""


def pct(a, b):
    return None if not b else round(100 * a / b)


class Layers(Hubs):
    def view(self, me, fresh=False):
        self._agents(me)
        return self.cached("layers", me, self._layers, fresh)

    def _n(self, sql, args=()):
        r = self.db.q(sql, args, one=True)
        return (r or {}).get("n") or 0

    def _layers(self, me, out):
        uid, admin, now = me["id"], me.get("role") == "admin", time.time()
        wk, wk2 = now - WEEK, now - 2 * WEEK
        comps = [w["id"] for w in self._comps(me)]
        cph = ",".join("?" * len(comps))
        flows = []
        if admin and comps and self._has("mb_flows"):
            flows = [f["id"] for f in self.db.q(f"SELECT id FROM mb_flows WHERE comp_id IN ({cph})", comps)]
        fph = ",".join("?" * len(flows))
        teams_on = mining.ENABLED and bool(comps)
        parts = {k: [] for k, *_ in LAYERS}
        n, has = self._n, self._has
        out.update(failures=[], evidence={}, pipeline=[], links=[], acceptance=None)

        def part(layer, name, what, view, present, figures, active=False, note="", checks=()):
            checks = [{"level": lv, "text": t} for lv, t in checks if t] if present else []
            st = "missing" if not present else "degraded" if any(c["level"] == "fail" for c in checks) else "ok" if active else "idle"
            parts[layer].append({"name": name, "what": what, "view": view, "present": bool(present), "active": bool(present and active), "state": st,
                                 "required": name in REQUIRED.get(layer, ()), "checks": checks,
                                 "figures": [{"label": l, "value": v} for l, v in figures] if present else [], "note": note})

        # ---------- mission intelligence ----------
        def mission():
            from . import mission_intel
            h = has("ctl_intel")
            week = n("SELECT COUNT(*) n FROM ctl_intel WHERE user_id=? AND ts>?", (uid, wk)) if h else 0
            bad = n("SELECT COUNT(*) n FROM ctl_intel WHERE user_id=? AND ts>? AND error IS NOT NULL AND error!=''", (uid, wk)) if h else 0
            auto = bool(h and has("ctl_settings") and self.db.q("SELECT 1 FROM ctl_settings WHERE user_id=? AND mode='auto'", (uid,), one=True))
            part("mission", "Mission Intelligence", "Reviews a predefined mission's results and proposes the next tasks (on a schedule in Auto mode).", "control",
                 h, [("Reviews this week", week), ("Reviews in all", n("SELECT COUNT(*) n FROM ctl_intel WHERE user_id=?", (uid,)) if h else 0)],
                 week - bad > 0, "Auto mode: scheduled reviews on" if auto else "Manual mode: reviews when you ask",
                 [("fail", f"All {week} review{'s' if week != 1 else ''} this week failed") if week and bad == week else
                  ("warn", f"{bad} of {week} reviews this week failed") if bad else ("", "")])
            h = has("mx_missions")
            ms = self.db.q("SELECT discovery, created, status, outcome FROM mx_missions WHERE user_id=? ORDER BY id DESC LIMIT ?", (uid, BRIEFS)) if h else []
            st = [(brief_state(_j(m["discovery"], {})), m["created"] or 0) for m in ms]
            cnt = {k: sum(1 for (s, _), _t in st if s == k) for k in ("researched", "no_web", "skipped", "none", "pending")}
            done_wk = [s for (s, _), t in st if t > wk and s != "pending"]
            res_wk = sum(1 for s in done_wk if s in ("researched", "no_web"))
            why = {}
            for (s, r), _t in st:
                if s == "skipped":
                    r = r.split(":")[0].strip() if len(r) > 120 else r  # the reason, without the figures that differ per mission
                    why[r] = why.get(r, 0) + 1
            top = max(why, key=why.get) if why else ""
            checks = []
            if not mission_intel.ENABLED: checks.append(("fail", "Research is turned off on this server (MISSION_RESEARCH=0): missions plan from memory only"))
            elif done_wk and not res_wk: checks.append(("fail", f"None of this week's {len(done_wk)} discovered mission{'s' if len(done_wk) != 1 else ''} was researched before planning" + (f". Most common reason: {top}" if top else "")))
            elif cnt["skipped"]: checks.append(("warn", f"{cnt['skipped']} brief{'s were' if cnt['skipped'] != 1 else ' was'} skipped. Most common reason: {top}"))
            if cnt["no_web"]: checks.append(("warn", f"{cnt['no_web']} brief{'s' if cnt['no_web'] != 1 else ''} had no web source: give your missions a web search tool in Agents → Tools & MCP"))
            # the same brief before a predefined mission's fixed tasks (task_research.py) and the competitor harvest it reads (mining_rivals.py)
            from . import task_research
            trc = task_research.counts(self.db, uid, wk)
            tr = trc or {"researched": 0, "no_web": 0, "skipped": 0, "running": 0, "week": 0, "why": {}}
            rv = self.db.q(f"""SELECT COUNT(DISTINCT a.comp_id) teams, COUNT(*) n, MAX(s.last_at) last FROM rv_agents a LEFT JOIN rv_state s ON s.comp_id=a.comp_id
                               WHERE a.comp_id IN ({cph or 'NULL'})""", tuple(comps), one=True) if has("rv_agents") and comps else None
            if tr["skipped"] and not (tr["researched"] + tr["no_web"]):
                checks.append(("warn", f"{tr['skipped']} fixed task{'s went' if tr['skipped'] != 1 else ' went'} out without a brief. Most common reason: {max(tr['why'], key=tr['why'].get)}"))
            if not task_research.ENABLED: checks.append(("warn", "Research before fixed tasks is off on this server (TASK_RESEARCH=0)"))
            part("mission", "Intelligence brief", "Researches the data, the latest material and competitors before a mission is planned, and before a "
                 "Competition team starts a fixed task (rules, interfaces, deliverables), with the whole field of a Ridges competition harvested.", "mos",
                 h or trc is not None, [("Missions researched", cnt["researched"] + cnt["no_web"]), ("Skipped", cnt["skipped"]), ("Without the web", cnt["no_web"]),
                     ("Of recent missions", len(ms)), ("Fixed tasks researched", tr["researched"] + tr["no_web"]), ("Researching now", tr["running"]),
                     ("Fixed tasks without a brief", tr["skipped"]), ("Competitor agents harvested", (rv or {}).get("n") or 0)],
                 res_wk + tr["week"] + tr["running"], checks=checks)
            open_ = n("SELECT COUNT(*) n FROM mx_missions WHERE user_id=? AND status IN ('queued','running','needs_input')", (uid,)) if h else 0
            week = n("SELECT COUNT(*) n FROM mx_missions WHERE user_id=? AND created>?", (uid, wk)) if h else 0
            failed = n("SELECT COUNT(*) n FROM mx_missions WHERE user_id=? AND created>? AND (status='failed' OR outcome='failed')", (uid, wk)) if h else 0
            deliv = n("SELECT COUNT(*) n FROM mx_missions WHERE user_id=? AND finished>? AND outcome IN ('verified','partial')", (uid, wk)) if h else 0
            # predefined missions (a Competition team each) count as open missions too: the 11-10 review read "0 open missions" here
            # next to "15 open tasks" in Task dispatch, the tasks being the competitions' (task_lifecycle.reconcile); a task whose
            # mission is closed or gone is an orphan and named
            pre = n("""SELECT COUNT(*) n FROM mw_comps w JOIN mh_campaigns c ON c.id=w.campaign_id WHERE c.user_id=? AND COALESCE(w.status,'active')!='closed'""",
                    (uid,)) if has("mw_comps") and has("mh_campaigns") else 0
            orph = 0
            if has("ctl_tasks"):
                try:
                    for t in self.db.q("""SELECT mission FROM ctl_tasks WHERE user_id=? AND status IN ('todo','running','review','needs_input') AND mission IS NOT NULL""", (uid,)):
                        m = t["mission"] or ""
                        if m.startswith("comp:"):
                            ok = has("mw_comps") and has("mh_campaigns") and self.db.q("""SELECT 1 FROM mw_comps w JOIN mh_campaigns c ON c.id=w.campaign_id
                                     WHERE w.id=? AND c.user_id=? AND COALESCE(w.status,'active')!='closed'""", (int(m[5:]), uid), one=True)
                        else:
                            ok = h and m.startswith("mx:") and self.db.q("SELECT 1 FROM mx_missions WHERE id=? AND user_id=? AND status IN ('queued','running','needs_input','paused')",
                                                                         (int(m[3:]), uid), one=True)
                        orph += 0 if ok else 1
                except Exception:  # noqa: BLE001 - an older table without mission
                    orph = 0
            part("mission", "Mission engine", "Turns a goal, budget and deadline into a plan, runs it and verifies the result.", "mos",
                 h, [("Open custom missions", open_), ("Predefined missions active", pre), ("Started this week", week), ("Delivered and verified", deliv), ("Failed", failed)],
                 week or open_, "Predefined missions are your Competition teams' (their tasks are in Task dispatch); custom ones are Mission Control's",
                 [("warn", f"{orph} open task{'s belong' if orph != 1 else ' belongs'} to a mission that's closed or gone: Control Hub → Tasks → Execution monitor") if orph else ("", ""),
                  ("fail", f"{failed} of this week's {week} missions failed") if failed >= 2 and week >= 3 and failed / week > 0.3 else
                  ("warn", f"{failed} of this week's {week} missions failed") if failed else
                  ("warn", f"{week} mission{'s' if week != 1 else ''} started this week, none delivered with a verified result yet") if week and not deliv and not open_ else ("", "")])
            h = has("ctl_tasks")  # Planner → Dispatcher → board/agent (control_dispatch.py): open tasks must move, not just exist
            if h:
                from . import control_dispatch as cd
                mode = (self.db.q("SELECT mode FROM ctl_settings WHERE user_id=?", (uid,), one=True) or {}).get("mode") if has("ctl_settings") else None
                mode = mode or "hybrid"
                # open tasks read as the Control Hub list shows them (board task / mission status, why(), owner), not the raw table: a
                # board task finished or merged away used to count as open and not under way. A stall is the system's (Dispatcher,
                # team) or yours (a decision, an answer, Manual mode, a task you made unstarted); only the system's fails the part.
                c = cd.counts(self.db, uid, mode, now)
                op, run, sysn, yours = c["open"], c["moving"], c["system"], c["yours"]
                aud = {x["action"]: x["n"] for x in self.db.q("""SELECT action, COUNT(*) n FROM og_audit WHERE user_id=? AND ts>?
                       AND action IN ('control.task.dispatch','control.task.retry','control.task.reassign') GROUP BY action""", (uid, wk))} if has("og_audit") else {}
                try:  # what the retry/reassign policy had to work on this week: a 0 above means nothing, or the policy didn't act
                    retry_ok = n("""SELECT COUNT(*) n FROM ctl_tasks WHERE user_id=? AND route='agent' AND updated>? AND (status='failed'
                                    OR (status='needs_input' AND summary LIKE ?))""", (uid, wk, cd.NO_DELIVERABLE + "%"))
                except Exception:  # noqa: BLE001 - an older table without summary
                    retry_ok = 0
                reasons = "; ".join(f"{x['n']} {x['why'].lower().rstrip('.')} ({x['owner'] or 'moving'})" for x in c["reasons"][:3])
                off = ("Manual mode dispatches nothing" if mode == "manual" else "the dispatcher is off on this server (CONTROL_DISPATCH=0)" if not cd.ENABLED else "")
                dl = 0
                try:  # the dead letters (task_lifecycle.dead): no automatic path left, escalated to you
                    from . import task_lifecycle as tl
                    for r in self.db.q("SELECT * FROM ctl_tasks WHERE user_id=? AND (status IN ('todo','needs_input') OR (status='failed' AND updated>?))", (uid, wk)):
                        L = cd.linked(self.db, r["ref"]) or {}
                        t = {**{k: v for k, v in L.items() if k != "status"}, "status": L.get("status") or r["status"]}
                        if t["status"] in ("done", "cancelled"): continue
                        t["why"] = dict(zip(("state", "text"), cd.why(t, {"attempts": 0, "next_try": None, "origin": None, "route": None, "summary": None, **r}, mode, now)))
                        dl += 1 if tl.dead(t, r) else 0
                except Exception:  # noqa: BLE001 - an older table
                    dl = 0
                part("mission", "Task dispatch", "Sends a mission's open tasks to the team's board or an agent, retries failures outside the work, reassigns empty deliverables.", "control",
                     h, [("Open tasks", op), ("Under way", run), (f"Stalled {cd.STALE // 3600} h+, AXoR's move", sysn), (f"Stalled {cd.STALE // 3600} h+, yours", yours),
                         ("Dead letters (escalated to you)", dl), ("Dispatched this week", aud.get("control.task.dispatch", 0)),
                         ("Retried or reassigned", f"{aud.get('control.task.retry', 0) + aud.get('control.task.reassign', 0)} of {retry_ok} failed or empty")],
                     run or aud.get("control.task.dispatch"), f"{mode.title()} mode" + ("" if cd.ENABLED else " · dispatcher off"),
                     [("fail", f"{op} open tasks and none under way; {sysn} stalled on AXoR's side: {reasons or off}") if op and not run and sysn else
                      ("warn", f"{sysn} open task{'s' if sysn != 1 else ''} stalled on AXoR's side: {reasons or off}") if sysn else
                      ("warn", f"{yours} open task{'s wait' if yours != 1 else ' waits'} for you: {reasons}") if yours else ("", "")])
            h = has("io_events")  # G5: Adaptive → Mission (orchestrator.guidance)
            # by planner (the ref the event names): Mission Control missions (mx:), Mission Intelligence reviews (ctl:mi:), team lead plans (mw:);
            # the check compares Mission Control's own count with its discoveries, so team plans can't hide an unguided mission
            G = {x["p"]: x["n"] for x in self.db.q("""SELECT CASE WHEN ref LIKE 'mx:%' THEN 'mx' WHEN ref LIKE 'ctl:mi:%' THEN 'mi' WHEN ref LIKE 'mw:%' THEN 'mw' ELSE 'other' END p,
                                                     COUNT(*) n FROM io_events WHERE owner_id=? AND kind='mission.guided' AND created>? GROUP BY p""", (uid, wk))} if h else {}
            gw = G.get("mx", 0)
            part("mission", "Learned guidance", "Before a mission plans, what the loop learned: failure classes to plan around, changes promoted or rolled back, the best-scoring models.", "mos",
                 h, [("Missions guided this week", gw), ("Missions discovered this week", len(done_wk)), ("Mission Intelligence reviews guided", G.get("mi", 0)),
                     ("Team lead plans guided", G.get("mw", 0))], sum(G.values()), "",
                 [("warn", f"{len(done_wk) - gw} of this week's {len(done_wk)} discovered missions planned without learned guidance (nothing was learned yet, or discovery ran before the orchestrator)") if done_wk and gw < len(done_wk) and gw == 0 else ("", "")])
            # Research & Discovery (the review's 5A): where a mission's research can reach, from what's granted to missions
            h = has("mcp_grants") and has("mcp_servers")
            tools = self.db.q("""SELECT s.name, s.slug FROM mcp_grants g JOIN mcp_servers s ON s.id=g.server_id
                                 WHERE g.scope=? AND s.enabled=1""", (f"missions:{uid}",)) if h else []
            web = [t for t in tools if WEB.search(f"{t['name']} {t['slug']}")]
            calls = self.db.q("SELECT COUNT(*) n, SUM(ok=0) bad FROM mcp_calls WHERE user_id=? AND scope=? AND ts>?", (uid, f"missions:{uid}", wk), one=True) \
                if h and has("mcp_calls") else {}
            part("mission", "Research sources", "What a mission's research can reach: AXoR's live data, your Knowledge Hub and the MCP tools you gave missions (web search, papers, docs).", "tools",
                 h, [("Tools for missions", len(tools)), ("Web search", "Yes" if web else "No"), ("Tool calls this week", (calls or {}).get("n") or 0)],
                 (calls or {}).get("n"), ", ".join(t["name"] for t in tools[:5]),
                 [("warn", "No web search is granted to missions: briefs can't read the open web or current competitors") if not web else ("", ""),
                  ("warn", f"{calls['bad']} of {calls['n']} research tool calls this week failed") if (calls or {}).get("bad") else ("", "")])

        # ---------- workforce intelligence ----------
        def workforce_():
            h = has("ac_agents")
            runs = has("ac_runs")
            running = n("SELECT COUNT(*) n FROM ac_runs WHERE owner_id=? AND status='running'", (uid,)) if runs else 0
            total = n("SELECT COUNT(*) n FROM ac_agents WHERE owner_id=? AND COALESCE(status,'')!='gone'", (uid,)) if h else 0
            worked = n("SELECT COUNT(DISTINCT agent_key) n FROM ac_runs WHERE owner_id=? AND started>? AND status='done' AND agent_key IS NOT NULL", (uid, wk)) if runs else 0
            useful = n("SELECT COUNT(DISTINCT agent_key) n FROM ac_runs WHERE owner_id=? AND started>? AND score>=? AND agent_key IS NOT NULL", (uid, wk, GOOD)) if runs else 0
            part("workforce", "Agent registry", "One directory of every agent across every agent system; counts the ones that produced work, not just the ones that exist.", "agents",
                 h, [("Agents", total), ("Did work this week", worked), (f"Scored {GOOD}+ this week", useful), ("Working now", running)], worked or running, "",
                 [("warn", f"Only {worked} of {total} agents did any work this week: retire or merge the idle ones") if total >= MIN_N and worked < total * 0.1 else ("", "")])
            h = workforce.ENABLED and has("wf_agents")
            week = n("SELECT COUNT(*) n FROM wf_missions WHERE user_id=? AND created>?", (uid, wk)) if h and has("wf_missions") else 0
            part("workforce", "Workforce", "A CEO and six teams that split a mission into assignments for the right specialists.", "workforce",
                 h, [("Agents", n("SELECT COUNT(*) n FROM wf_agents WHERE user_id=?", (uid,)) if h else 0), ("Missions this week", week)], week)
            h = workforce.ENABLED and has("sw_swarms")  # the Agent Swarm (swarm.py): temporary teams of Workforce agents on task contracts
            week = n("SELECT COUNT(*) n FROM sw_swarms WHERE user_id=? AND created>?", (uid, wk)) if h else 0
            part("workforce", "Agent Swarm", "A Swarm Controller sizes a temporary team of Workforce agents, picks a swarm pattern and runs the mission as checked task contracts.", "swarm",
                 h, [("Swarms this week", week), ("Contracts fulfilled", n("SELECT COUNT(*) n FROM sw_contracts c JOIN sw_swarms s ON s.id=c.swarm_id WHERE s.user_id=? AND c.status='done'", (uid,)) if h and has("sw_contracts") else 0)], week)
            h = has("og_units")
            part("workforce", "Organization", "Departments, teams, reporting lines, budgets and each agent's level of authority.", "org",
                 h, [("Units", n("SELECT COUNT(*) n FROM og_units WHERE user_id=?", (uid,)) if h else 0),
                     ("Agents placed", n("SELECT COUNT(*) n FROM og_agents WHERE user_id=?", (uid,)) if h and has("og_agents") else 0)])
            routed = n("SELECT COUNT(*) n FROM ac_runs WHERE owner_id=? AND started>? AND decision IS NOT NULL", (uid, wk)) if runs else 0
            fb = n("SELECT COUNT(*) n FROM ac_runs WHERE owner_id=? AND started>? AND decision LIKE '%\"source\": \"fallback\"%'", (uid, wk)) if runs else 0
            pool = self.db.q("SELECT pool FROM ac_pool WHERE owner_id=?", (uid,), one=True) if has("ac_pool") else None
            size = len(_j((pool or {}).get("pool"), []) or [])
            part("workforce", "Model router", "Picks the model for each call from past scores, cost, speed and failures.", "control",
                 runs, [("Calls routed this week", routed), ("Models in your pool", size), ("Fell back", fb)], routed, "",
                 [("warn", "No model pool: \"auto\" work runs on the default model, nothing is routed") if not size else ("", ""),
                  ("warn", f"{fb} of {routed} routed calls this week fell back to another model") if routed and fb / routed > 0.2 else ("", "")])

        # ---------- execution intelligence ----------
        def execution():
            h = has("ac_runs")
            week = n("SELECT COUNT(*) n FROM ac_runs WHERE owner_id=? AND started>?", (uid, wk)) if h else 0
            fin = n("SELECT COUNT(*) n FROM ac_runs WHERE owner_id=? AND started>? AND status!='running'", (uid, wk)) if h else 0
            bad = self.db.q(f"SELECT status, error FROM ac_runs WHERE owner_id=? AND started>? AND status IN ({','.join('?' * len(FAILED))})",
                            (uid, wk, *FAILED)) if h else []
            low = n("SELECT COUNT(*) n FROM ac_runs WHERE owner_id=? AND started>? AND status='done' AND score<?", (uid, wk, LOW)) if h else 0
            cls = {}
            for r in bad:
                k = fail_class(r["status"], r["error"]); cls[k] = cls.get(k, 0) + 1
            if low: cls["low"] = low
            out["failures"] = [{"key": k, "label": FAIL_LABEL.get(k, k), "n": v} for k, v in sorted(cls.items(), key=lambda x: -x[1])]
            rate = len(bad) / fin if fin else 0
            top = next((f for f in out["failures"] if f["key"] != "low"), None)
            from . import agent_core
            oc = agent_core.get().outcomes(uid, wk) if h and agent_core.get() else None  # every run in one state; the parts add up to the runs
            more = [("Succeeded", oc["success"]), ("Failed", oc["failed"]), ("Timed out", oc["timeout"]), ("Cut off by a restart", oc["restarted"]),
                    ("Cancelled", oc["cancelled"]), ("Still running", oc["running"])] + ([("Other status", oc["other"])] if oc["other"] else []) if oc else []
            part("execution", "Agent runs", "Every agent system's model runs in one ledger, under a daily token budget; failures are classified by cause.", "studio",
                 h, [("Runs this week", week), ("Failed or lost", len(bad)), ("Failure rate", f"{pct(len(bad), fin)}%" if fin else None)] + more, week,
                 "This week = the last 7 days. Each run is in exactly one of succeeded, failed, timed out, cut off by a restart, cancelled or still running." if oc else "",
                 [("fail", f"{round(rate * 100)}% of this week's finished runs failed or were lost ({len(bad)} of {fin})" + (f"; most: {top['label'].lower()} ({top['n']})" if top else ""))
                  if fin >= MIN_N and rate > FAIL_RATE else ("warn", f"{len(bad)} of {fin} runs failed this week") if len(bad) and rate > FAIL_RATE else ("", "")])
            h = teams_on and has("mw_runs")
            week = n(f"SELECT COUNT(*) n FROM mw_runs WHERE started>? AND comp_id IN ({cph})", (wk, *comps)) if h else 0
            part("execution", "Autoloop", "Runs the Competition teams' work with budget limits, failure classes, retries and restart recovery.", "teams",
                 h, [("Teams on autopilot", n(f"SELECT COUNT(*) n FROM mw_comps WHERE autopilot=1 AND id IN ({cph})", comps) if h else 0),
                     ("Team runs this week", week)], week, "" if comps or not mining.ENABLED else "No open Competition team")
            h = teams_on and has("mw_sbx")
            # the orchestrator's definition (orchestrator.SBX_FAILED): an error and a timeout both count, so its class breakdown adds up to this
            r = self.db.q(f"SELECT COUNT(*) n, SUM(status IN ('error','timeout')) err FROM mw_sbx WHERE started>? AND comp_id IN ({cph})", (wk, *comps), one=True) if h else {}
            sw, se = (r or {}).get("n") or 0, (r or {}).get("err") or 0
            r = self.db.q(f"SELECT COUNT(*) n, SUM(status IN ('error','timeout')) err FROM mw_sbx WHERE started>? AND comp_id IN ({cph})", (now - 86400, *comps), one=True) if h else {}
            dn, de = (r or {}).get("n") or 0, (r or {}).get("err") or 0  # the last 24 h apart: a fix shows here before the week's figure catches up
            topc = None
            if h and se and has("io_sbx"):  # G5: why they couldn't run (orchestrator.sbx_class)
                from .orchestrator import SBX_LABEL
                t = self.db.q(f"""SELECT d.cls, COUNT(*) n, MAX(d.recovery) fix FROM io_sbx d JOIN mw_sbx s ON s.id=d.sbx_id WHERE s.started>? AND s.comp_id IN ({cph})
                                  GROUP BY d.cls ORDER BY n DESC LIMIT 1""", (wk, *comps), one=True)
                if t and t["cls"]: topc = f"; most: {SBX_LABEL.get(t['cls'], t['cls']).lower()} ({t['n']}). {t['fix']}"
            big = {}  # oversized inputs, the week against the last 24 h: inputs are split into several ConfigMaps since 11-10 (sandbox.chunks)
            if h and has("io_sbx"):
                big = self.db.q(f"""SELECT SUM(CASE WHEN s.started>? THEN 1 ELSE 0 END) AS week_count, SUM(CASE WHEN s.started>? THEN 1 ELSE 0 END) AS today_count
                                    FROM io_sbx d JOIN mw_sbx s ON s.id=d.sbx_id
                                    WHERE d.cls='too_large' AND s.started>? AND s.comp_id IN ({cph})""", (wk, now - 86400, wk, *comps), one=True) or {}
            bw, bd = big.get("week_count") or 0, big.get("today_count") or 0  # `day` is a keyword Postgres refuses as a bare alias (42601)
            if bw and topc: topc += f" Input over the size limit: {bw} this week, {bd} in the last 24 h" + (" (none since the fix that splits big inputs)" if not bd else "") + "."
            part("execution", "Sandboxes", "Isolated pods where team agents run code, with per-team internet when granted.", "teams",
                 h, [("Sandbox runs this week", sw), ("Couldn't run or timed out", se), ("Last 24 h: runs", dn), ("Last 24 h: couldn't run", de)]
                    + ([("Input too large: week / 24 h", f"{bw} / {bd}")] if bw else []), sw, "",
                 [("fail", f"{se} of {sw} sandbox runs this week couldn't run or timed out (pod, proxy or input errors, not the code's result){topc or ''}") if sw >= 10 and se / sw > 0.2 else
                  ("warn", f"{se} sandbox run{'s' if se != 1 else ''} couldn't run or timed out this week{topc or ''}") if se else ("", "")])
            h = has("ac_limits")  # G5: scoped hard limits, checked before every model call (agent_core.over)
            lim = n("SELECT COUNT(*) n FROM ac_limits WHERE owner_id=?", (uid,)) if h else 0
            cap = n("SELECT COUNT(*) n FROM ac_budget WHERE owner_id=? AND daily_tokens>0", (uid,)) if has("ac_budget") else 0
            hits = n("SELECT COUNT(*) n FROM ac_limit_hits WHERE owner_id=? AND ts>?", (uid, wk)) if h and has("ac_limit_hits") else 0
            ack = (self.db.q("SELECT unlimited, unlimited_by FROM ac_budget WHERE owner_id=?", (uid,), one=True) or {}) \
                if has("ac_budget") and "unlimited" in {c["name"] for c in self.db.q("PRAGMA table_info(ac_budget)")} else {}
            part("execution", "Budget gateway", "Hard token limits checked before every model call: your daily limit, and limits per mission, team, agent, task contract, system and per call.", "studio",
                 h, [("Daily limit", "On" if cap else "Off"), ("Scoped limits", lim), ("Calls refused this week", hits)], lim or cap,
                 "Missions get their dollar budget as a hard limit when they launch; set the others in Agent Operations → Budget.",
                 [(("warn", "Running without a hard limit, acknowledged" + (f" by {ack['unlimited_by']}" if ack.get("unlimited_by") else "") + ": only missions stop at a budget")
                   if ack.get("unlimited") else
                   ("fail", "No hard limit is set and no decision to run without one: only missions stop at a budget. Set one before raising autonomy "
                            "(Performance → Budgets suggests limits from what you spent), or confirm no cap in Agents → Operations → Daily budget"))
                  if not (lim or cap) else ("", "")])
            h = has("ia_tasks")
            running = n("SELECT COUNT(*) n FROM ia_tasks WHERE user_id=? AND status='running'", (uid,)) if h else 0
            part("execution", "Long tasks", "File-centric agents for long-horizon work that resume after a restart.", "infiagent",
                 h, [("Running", running), ("In all", n("SELECT COUNT(*) n FROM ia_tasks WHERE user_id=?", (uid,)) if h else 0)], running)
            h = has("ctl_tasks")
            done = n("SELECT COUNT(*) n FROM ctl_tasks WHERE user_id=? AND status='done' AND updated>?", (uid, wk)) if h else 0
            failed = n("SELECT COUNT(*) n FROM ctl_tasks WHERE user_id=? AND status='failed' AND updated>?", (uid, wk)) if h else 0
            part("execution", "Control Hub tasks", "Fixed and dynamic tasks given to departments, teams and agents.", "control",
                 h, [("Open", n("SELECT COUNT(*) n FROM ctl_tasks WHERE user_id=? AND status NOT IN ('done','cancelled','failed','declined')", (uid,)) if h else 0),
                     ("Done this week", done), ("Failed this week", failed)], done, "",
                 [("warn", f"{failed} task{'s' if failed != 1 else ''} failed this week, {done} done") if failed > done else ("", "")])

        # ---------- knowledge intelligence ----------
        def knowledge():
            h = has("kb_items")
            new = n("SELECT COUNT(*) n FROM kb_items WHERE user_id=? AND status='kept' AND updated>?", (uid, wk)) if h else 0
            items = n("SELECT COUNT(*) n FROM kb_items WHERE user_id=? AND status='kept'", (uid,)) if h else 0
            hc = h and has("kb_chunks")
            # G5: passages of each item's current version only, and items with none (the old check compared items with all chunk rows:
            # one long document has many, an edited one kept its old version's until re-chunked, so it was wrong both ways)
            chunks = n("""SELECT COUNT(*) n FROM kb_chunks c JOIN kb_items k ON k.id=c.item_id AND k.version=c.ver AND k.status='kept' WHERE k.user_id=?""", (uid,)) if hc else 0
            unindexed = n("""SELECT COUNT(*) n FROM kb_items k WHERE k.user_id=? AND k.status='kept'
                             AND NOT EXISTS (SELECT 1 FROM kb_chunks c WHERE c.item_id=k.id AND c.ver=k.version)""", (uid,)) if hc else 0
            stale_old = n("""SELECT COUNT(*) n FROM kb_items k WHERE k.user_id=? AND k.status='kept' AND k.updated<?
                             AND NOT EXISTS (SELECT 1 FROM kb_chunks c WHERE c.item_id=k.id AND c.ver=k.version)""", (uid, now - 3600)) if hc else 0
            hq = has("kb_queries")
            r = self.db.q("""SELECT COUNT(*) n, SUM(COALESCE(results,0)=0) empty, SUM(COALESCE(results,0)=0 AND COALESCE(candidates,0)=0) unreadable
                             FROM kb_queries WHERE user_id=? AND ts>?""", (uid, wk), one=True) if hq else {}
            sq, se, su = (r or {}).get("n") or 0, (r or {}).get("empty") or 0, (r or {}).get("unreadable") or 0
            sm = se - su  # searched something and ranked nothing in
            part("knowledge", "Knowledge Hub", "Documents, notes and sources agents can read, with scopes and review.", "knowledge",
                 h, [("Items kept", items), ("Passages indexed", chunks), ("Items not indexed yet", unindexed), ("Added this week", new)], new or (chunks and sq), "",
                 [("warn", f"{sq} searches this week over {chunks} indexed passage{'s' if chunks != 1 else ''}: the hub is small for how often it's searched. Link folders or import documents") if sq >= MIN_N and chunks < 50 else ("", ""),
                  ("fail", f"{stale_old} kept item{'s have' if stale_old != 1 else ' has'} no passage of {'their' if stale_old != 1 else 'its'} current version after an hour: the background index isn't keeping up or isn't running (KNOWLEDGE_INDEX)")
                  if stale_old >= 5 else ("warn", f"{unindexed} kept item{'s' if unindexed != 1 else ''} waiting for the index") if unindexed else ("", "")])
            cited = n("SELECT COUNT(*) n FROM kb_queries WHERE user_id=? AND ts>? AND cited IS NOT NULL AND cited NOT IN ('', '[]')", (uid, wk)) if hq else 0
            from . import orchestrator
            rb = orchestrator.get().retrieval_status(uid) if orchestrator.get() else None
            rm = (rb or {}).get("metrics") or {}
            checks = [("fail", f"{pct(sm, sq)}% of this week's searches had records to rank and found nothing ({sm} of {sq}): a ranking or indexing problem") if sq >= MIN_N and sm / sq > 0.5 else
                      ("warn", f"{sm} of {sq} searches this week had records to rank and found nothing") if sm and sq and sm / sq > 0.25 else ("", ""),
                      ("warn", f"{su} of {sq} searches this week had nothing they were allowed to read: an access or ingestion gap, not ranking (grant the asker a scope, or add records)") if su and sq and su / sq > 0.25 else ("", "")]
            if rb and not rb["passed"]:
                checks.append(("fail", f"The retrieval benchmark failed: recall@{rm.get('k')} {rm.get('recall@' + str(rm.get('k')))} against a pass line of {rm.get('pass_line')}"
                                       f" ({rm.get('not_indexed', 0)} not indexed, {rm.get('ranked_out', 0)} ranked out)"))
            part("knowledge", "Retrieval", "Hybrid search (keywords, meaning, rerank) that answers with citations, for you and your agents.", "knowledge",
                 hq, [("Searches this week", sq), ("Ranked nothing in", sm), ("Nothing readable", su), ("With citations", cited)] +
                     ([(f"Benchmark recall@{rm.get('k')}", rm.get(f"recall@{rm.get('k')}")), ("Benchmark", "Pass" if rb["passed"] else "Fail")] if rb else []),
                 sq - se > 0, "" if rb else "The known-item retrieval benchmark hasn't run yet (it runs daily once you keep 5 items with text)", checks)
            h = has("mx_lessons")
            agg = self.db.q("SELECT COUNT(*) n, COALESCE(SUM(used), 0) used FROM mx_lessons WHERE user_id=?", (uid,), one=True) if h else {}
            part("knowledge", "Mission lessons", "What worked and what failed, kept by each mission and read by the next.", "learning",
                 h, [("Lessons", agg.get("n") or 0), ("Times reused", agg.get("used") or 0)],
                 n("SELECT COUNT(*) n FROM mx_lessons WHERE user_id=? AND created>?", (uid, wk)) if h else 0)
            h = workforce.ENABLED and has("wf_memory")
            part("knowledge", "Workforce memory", "Facts and lessons Workforce agents recall, cite and rate.", "workforce",
                 h, [("Active memories", n("SELECT COUNT(*) n FROM wf_memory WHERE user_id=? AND status='active'", (uid,)) if h else 0)],
                 n("SELECT COUNT(*) n FROM wf_memory WHERE user_id=? AND created>?", (uid, wk)) if h else 0)
            h = teams_on and has("mw_notes")
            part("knowledge", "Team notebooks", "Findings the Competition teams' agents write down for each other.", "teams",
                 h, [("Findings", n(f"SELECT COUNT(*) n FROM mw_notes WHERE comp_id IN ({cph})", comps) if h else 0)],
                 n(f"SELECT COUNT(*) n FROM mw_notes WHERE ts>? AND comp_id IN ({cph})", (wk, *comps)) if h else 0)
            h = has("ex_recalls")
            r = self.db.q("SELECT COUNT(*) n, SUM(COALESCE(found,0)=0) empty FROM ex_recalls WHERE user_id=? AND ts>?", (uid, wk), one=True) if h else {}
            rw, re_ = (r or {}).get("n") or 0, (r or {}).get("empty") or 0
            part("knowledge", "Experience recall", "Before they act, missions, Workforce and team tasks recall the earlier experiences that fit the work.", "learning",
                 h, [("Recalls this week", rw), ("Found nothing", re_), ("Experiences indexed", n("SELECT COUNT(DISTINCT ref) n FROM ex_vecs WHERE user_id=?", (uid,)) if h and has("ex_vecs") else 0)],
                 rw - re_ > 0, "", [("warn", f"{re_} of {rw} recalls this week found nothing") if rw >= MIN_N and re_ / rw > 0.5 else ("", "")])

        # ---------- evaluation ----------
        def evaluation():
            h = has("ac_runs")
            r = self.db.q("SELECT COUNT(*) n, AVG(score) a, SUM(score<?) low FROM ac_runs WHERE owner_id=? AND started>? AND score IS NOT NULL", (LOW, uid, wk), one=True) if h else {}
            done = n("SELECT COUNT(*) n FROM ac_runs WHERE owner_id=? AND started>? AND status='done'", (uid, wk)) if h else 0
            sn = (r or {}).get("n") or 0
            from . import orchestrator
            cov = orchestrator.get().coverage(uid, wk) if orchestrator.get() and h else None
            if cov:  # G5: every finished run scored, excluded with its reason, or a named gap (orchestrator.py)
                top = cov["gaps"][0] if cov["gaps"] else None
                checks = [("fail", f"Only {cov['scored_pct']}% of this week's scoreable runs got a score ({cov['scored']} of {cov['scored'] + cov['gap']}); "
                                   f"most unscored: {top['label']} '{top['kind']}' runs ({top['n']})") if top and cov["scored_pct"] is not None and cov["scored_pct"] < 50 and cov["gap"] >= MIN_N else
                          ("warn", f"{cov['scored_pct']}% of this week's scoreable runs got a score, under the {cov['target']}% target; {cov['gap']} without a verdict, most: {top['label']} '{top['kind']}' ({top['n']})")
                          if top and (cov["scored_pct"] or 0) < cov["target"] else ("", ""),
                          ("warn", f"{cov['waiting']} finished run{'s' if cov['waiting'] != 1 else ''} not classified yet (the orchestrator runs every minute)") if cov["waiting"] > 50 else ("", "")]
                figs = [("Scored this week", sn), ("Average score", round(r["a"]) if (r or {}).get("a") is not None else None),
                        ("Of scoreable runs", f"{cov['scored_pct']}%" if cov["scored_pct"] is not None else None), ("Excluded with a reason", cov["excluded"]),
                        ("No evaluator", cov["gap"]), ("Under 50", (r or {}).get("low") or 0)]
            else:
                checks = [("warn", f"Only {pct(sn, done)}% of this week's finished runs were scored ({sn} of {done}): the rest can't be compared or learned from") if done >= MIN_N and sn / done < 0.2 else ("", "")]
                figs = [("Scored this week", sn), ("Average score", round(r["a"]) if (r or {}).get("a") is not None else None),
                        ("Of finished runs", f"{pct(sn, done)}%" if done else None), ("Under 50", (r or {}).get("low") or 0)]
            part("evaluation", "Run scores", "An evaluator's or verifier's 0-100 score on finished runs; the router reads them. Runs nobody can score are excluded with a reason or named as gaps.", "evaluation",
                 h, figs, sn, "", checks)
            h = bool(flows) and has("mb_experiments")
            week = n(f"SELECT COUNT(*) n FROM mb_experiments WHERE status='done' AND finished>? AND flow_id IN ({fph})", (wk, *flows)) if h else 0
            part("evaluation", "Lab evals", "Scores each Workflow commit on the competition's own checks against its base: competition performance, not just task completion.", "teams",
                 h, [("Evals this week", week)], week, "" if admin else "Administrators only")
            h = teams_on and has("au_sprints")
            week = n(f"SELECT COUNT(*) n FROM au_sprints WHERE started>? AND comp_id IN ({cph})", (wk, *comps)) if h else 0
            part("evaluation", "Upgrade exams", "Blind tests on held-out tasks before an upgraded agent is promoted.", "teams",
                 h, [("Sprints this week", week)], week)
            h = has("ev_trials") and has("ev_proposals")
            week = n("""SELECT COUNT(*) n FROM ev_trials t JOIN ev_proposals p ON p.id=t.proposal_id WHERE p.user_id=? AND t.ts>?""", (uid, wk)) if h else 0
            bench = n("SELECT COUNT(*) n FROM ev_benchmarks WHERE user_id=?", (uid,)) if h and has("ev_benchmarks") else None
            part("evaluation", "Evolution experiments", "Current and candidate versions answer the same cases; a judge scores them blind.", "evolution",
                 h, [("Blind trials this week", week)] + ([("Benchmarks", bench)] if bench is not None else []), week, "",
                 [("warn", "No benchmark yet: write a test set before any change can be measured") if bench == 0 else ("", "")])
            h = has("kb_eval_runs")
            week = n("SELECT COUNT(*) n FROM kb_eval_runs WHERE user_id=? AND ts>?", (uid, wk)) if h else 0
            part("evaluation", "Retrieval evals", "Checks that knowledge search finds what known questions need.", "knowledge",
                 h, [("Eval runs this week", week), ("Test questions", n("SELECT COUNT(*) n FROM kb_evals WHERE user_id=?", (uid,)) if h and has("kb_evals") else 0)], week)

        # ---------- adaptive intelligence ----------
        def adaptive():
            h = has("ev_proposals")
            prom = n("SELECT COUNT(*) n FROM ev_proposals WHERE user_id=? AND status='promoted'", (uid,)) if h else 0
            waiting = n("SELECT COUNT(*) n FROM ev_proposals WHERE user_id=? AND status='verified'", (uid,)) if h else 0
            part("adaptive", "Evolution Lab", "Promotes a change only with measured evidence; one click rolls it back.", "evolution",
                 h, [("Promoted", prom), ("Rolled back", n("SELECT COUNT(*) n FROM ev_proposals WHERE user_id=? AND status='rolled_back'", (uid,)) if h else 0),
                     ("Verified, waiting", waiting)],
                 n("SELECT COUNT(*) n FROM ev_proposals WHERE user_id=? AND (promoted>? OR tested>?)", (uid, wk, wk)) if h else 0, "",
                 [("warn", f"{waiting} change{'s' if waiting != 1 else ''} measured better and wait{'s' if waiting == 1 else ''} for your decision") if waiting else ("", "")])
            wf = workforce.ENABLED and has("wf_improvements")
            mb = bool(flows) and has("mb_improvements")
            adopted = (n("SELECT COUNT(*) n FROM wf_improvements WHERE user_id=? AND status='promoted'", (uid,)) if wf else 0) + \
                      (n(f"SELECT COUNT(*) n FROM mb_improvements WHERE flow_id IN ({fph}) AND status IN ('promoted','applied')", flows) if mb else 0)
            better = n("SELECT COUNT(*) n FROM wf_improvements WHERE user_id=? AND status='better'", (uid,)) if wf else 0
            week = (n("SELECT COUNT(*) n FROM wf_improvements WHERE user_id=? AND updated>?", (uid, wk)) if wf else 0) + \
                   (n(f"SELECT COUNT(*) n FROM mb_improvements WHERE flow_id IN ({fph}) AND updated>?", (*flows, wk)) if mb else 0)
            part("adaptive", "Improvements", "Diagnoses why an agent's work failed, proposes a change and trials it before adoption.", "learning",
                 wf or mb, [("Adopted", adopted), ("Worked on this week", week), ("Better, waiting", better)], week, "",
                 [("warn", f"{better} improvement{'s' if better != 1 else ''} trialled better and wait{'s' if better == 1 else ''} for adoption") if better else ("", "")])
            h = has("ex_uses")
            r = self.db.q("""SELECT SUM(outcome='success') s, SUM(outcome='partial') p, SUM(outcome='failure') f, COUNT(outcome) n FROM ex_uses
                             WHERE user_id=? AND settled>?""", (uid, wk), one=True) if h else {}
            a = self.db.q("""SELECT SUM(outcome='success') s, SUM(outcome='failure') f, SUM(outcome IS NULL) o, SUM(outcome IS NULL AND ts<?) stale
                             FROM ex_uses WHERE user_id=?""", (now - OPEN_DAYS * 86400, uid), one=True) if h else {}
            s_all, f_all, o_all, stale = ((a or {}).get(k) or 0 for k in ("s", "f", "o", "stale"))
            part("adaptive", "Recall track record", "How work that used each recalled experience went; the next recall ranks the better ones higher.", "learning",
                 h, [("Settled on success", (r or {}).get("s") or 0), ("Partial", (r or {}).get("p") or 0), ("Settled on failure", (r or {}).get("f") or 0),
                     ("Still open", o_all)], (r or {}).get("n"), "This week's settled outcomes; still open counts every recall without an outcome yet.",
                 [("warn", f"{s_all} successes and no failure ever settled: failed work may not be reporting its outcome, so the ranking can't learn what to avoid") if s_all >= MIN_N and not f_all else ("", ""),
                  ("warn", f"{stale} recalled experience{'s have' if stale != 1 else ' has'} waited over {OPEN_DAYS} days for an outcome") if stale else ("", "")])
            h = has("io_monitor")  # G5: promoted Evolution changes watched on later scored runs (orchestrator.monitor)
            mon = {r["state"]: r["n"] for r in self.db.q("SELECT state, COUNT(*) n FROM io_monitor WHERE owner_id=? GROUP BY state", (uid,))} if h else {}
            part("adaptive", "Promotion monitor", "After an Evolution promotion, compares the agent's later scored runs with its runs before; a regression rolls back under an auto policy, else waits for you.", "evolution",
                 h, [("Watching", mon.get("watching", 0)), ("Kept", mon.get("kept", 0)), ("Rolled back", mon.get("rolled_back", 0)), ("Regressed, waiting", mon.get("regressed", 0))],
                 n("SELECT COUNT(*) n FROM io_monitor WHERE owner_id=? AND checked>?", (uid, wk)) if h else 0, "",
                 [("fail", f"{mon['regressed']} promoted change{'s' if mon['regressed'] != 1 else ''} scored worse after promotion and wait{'s' if mon['regressed'] == 1 else ''} for your rollback") if mon.get("regressed") else ("", "")])
            h = bool(flows) and has("mb_watches")
            kept = n(f"SELECT COUNT(*) n FROM mb_watches WHERE flow_id IN ({fph}) AND status='kept'", flows) if h else 0
            back = n(f"SELECT COUNT(*) n FROM mb_watches WHERE flow_id IN ({fph}) AND status='rolled_back'", flows) if h else 0
            part("adaptive", "Watches", "After a promotion, keeps the new version or rolls it back on real outcomes.", "learning",
                 h, [("Kept", kept), ("Rolled back", back)],
                 n(f"SELECT COUNT(*) n FROM mb_watches WHERE flow_id IN ({fph}) AND COALESCE(ended, started)>?", (*flows, wk)) if h else 0,
                 "" if admin else "Administrators only",
                 [("warn", f"{back} of {kept + back} watched promotions were rolled back") if back and back >= kept else ("", "")])
            h = teams_on and has("au_agents")
            part("adaptive", "Upgrade promotions", "Agent versions an upgrade sprint produced and you promoted.", "teams",
                 h, [("Promoted", n(f"SELECT COUNT(*) n FROM au_agents WHERE decision='promoted' AND comp_id IN ({cph})", comps) if h else 0)])
            h = has("ac_runs")
            part("adaptive", "Router track record", "Scored runs the model router learns from when it picks the next model.", "control",
                 h, [("Scored runs", n("SELECT COUNT(*) n FROM ac_runs WHERE owner_id=? AND score IS NOT NULL", (uid,)) if h else 0)],
                 n("SELECT COUNT(*) n FROM ac_runs WHERE owner_id=? AND started>? AND score IS NOT NULL AND decision IS NOT NULL", (uid, wk)) if h else 0)

        # ---------- improvement evidence: this week against the week before ----------
        def evidence():
            ev = {}
            if has("ac_runs"):
                def wkstats(a, b):
                    r = self.db.q("""SELECT COUNT(*) n, SUM(status IN ('failed','error','lost')) bad, AVG(score) sc, COUNT(score) scored,
                                     SUM(CASE WHEN status='done' THEN tokens END) tok, SUM(status='done') ok, SUM(cost) usd, COUNT(cost) costed
                                     FROM ac_runs WHERE owner_id=? AND started>? AND started<=? AND status!='running'""", (uid, a, b), one=True) or {}
                    fin = r.get("n") or 0
                    return {"runs": fin, "score": round(r["sc"], 1) if r.get("sc") is not None else None, "scored": r.get("scored") or 0,
                            "fail_rate": round(100 * (r.get("bad") or 0) / fin, 1) if fin else None,
                            "tokens_per_run": round((r.get("tok") or 0) / r["ok"]) if r.get("ok") else None,
                            "usd_per_run": round(r["usd"] / r["costed"], 4) if r.get("costed") and r.get("usd") is not None else None}
                ev["now"], ev["before"] = wkstats(wk, now), wkstats(wk2, wk)
            decided, back, last = 0, 0, None
            def newer(when, what, where, view, ref=None):
                nonlocal last
                if when and (not last or when > last["when"]): last = {"when": when, "what": what, "where": where, "view": view, **(ref or {})}
            if has("ev_proposals"):
                r = self.db.q("SELECT SUM(status IN ('promoted','rolled_back')) d, SUM(status='rolled_back') b FROM ev_proposals WHERE user_id=?", (uid,), one=True) or {}
                decided, back = decided + (r.get("d") or 0), back + (r.get("b") or 0)
                p = self.db.q("SELECT title, target_name, evidence, promoted FROM ev_proposals WHERE user_id=? AND status='promoted' ORDER BY promoted DESC LIMIT 1", (uid,), one=True)
                if p:
                    e = _j(p["evidence"], {}) or {}
                    newer(p["promoted"], p["title"], f"Evolution Lab · {p['target_name'] or ''}".strip(" ·"), "evolution",
                          {"before": e.get("baseline"), "after": e.get("candidate"), "cases": e.get("cases")})
            if workforce.ENABLED and has("wf_improvements"):
                p = self.db.q("SELECT change, updated FROM wf_improvements WHERE user_id=? AND status='promoted' ORDER BY updated DESC LIMIT 1", (uid,), one=True)
                if p: newer(p["updated"], str(p["change"] or "Workforce improvement")[:160], "Workforce improvement", "learning")
            if teams_on and has("au_agents"):
                p = self.db.q(f"SELECT name, decided, base_score, cand_score FROM au_agents WHERE decision='promoted' AND comp_id IN ({cph}) ORDER BY decided DESC LIMIT 1", comps, one=True)
                if p: newer(p["decided"], f"{p['name']} upgraded", "Upgrade sprint", "teams", {"before": p["base_score"], "after": p["cand_score"]})
            if flows and has("mb_watches"):
                r = self.db.q(f"SELECT SUM(status IN ('kept','rolled_back')) d, SUM(status='rolled_back') b FROM mb_watches WHERE flow_id IN ({fph})", flows, one=True) or {}
                decided, back = decided + (r.get("d") or 0), back + (r.get("b") or 0)
            ev["regression"] = {"decided": decided, "rolled_back": back, "rate": pct(back, decided)}
            ev["last_promotion"] = last
            out["evidence"] = ev

        # ---------- the Evolution engine's nine stages, this week (the review's observe → … → monitor → roll back) ----------
        def pipeline():
            def c(t, sql, args=()): return n(sql, args) if has(t) else 0
            wf = workforce.ENABLED and has("wf_improvements")
            mb = bool(flows) and has("mb_improvements")
            mbq = lambda cond, *a: n(f"SELECT COUNT(*) n FROM mb_improvements WHERE flow_id IN ({fph}) AND {cond}", (*flows, *a)) if mb else 0
            wfq = lambda cond, *a: n(f"SELECT COUNT(*) n FROM wf_improvements WHERE user_id=? AND {cond}", (uid, *a)) if wf else 0
            obs = c("ac_runs", "SELECT COUNT(*) n FROM ac_runs WHERE owner_id=? AND started>? AND (status IN ('failed','error','lost') OR score<?)", (uid, wk, LOW))
            diag = wfq("created>?", wk) + mbq("created>? AND root_cause IS NOT NULL", wk) + \
                   c("io_diag", "SELECT COUNT(*) n FROM io_diag WHERE owner_id=? AND ts>?", (uid, wk))  # G5: every failed run's class and recovery
            prop = c("ev_proposals", "SELECT COUNT(*) n FROM ev_proposals WHERE user_id=? AND created>?", (uid, wk)) + wfq("created>? AND change IS NOT NULL", wk) + \
                   mbq("created>? AND change IS NOT NULL", wk)
            from . import orchestrator
            o = orchestrator.get()
            if o is not None:  # the ledger's measured changes: the Evaluation → Adaptive handoff counts the same rows
                exp = next(k["done"] for k in o.handoffs(uid, wk) if k["kind"] == "proposal.tested")
            else:
                exp = c("ev_proposals", "SELECT COUNT(*) n FROM ev_proposals WHERE user_id=? AND tested>?", (uid, wk)) + \
                      wfq("updated>? AND trials>0", wk) + mbq("updated>? AND status IN ('testing','better','same','worse','trial_failed')", wk)
            evl = (c("ev_trials", "SELECT COUNT(*) n FROM ev_trials t JOIN ev_proposals p ON p.id=t.proposal_id WHERE p.user_id=? AND t.ts>?", (uid, wk)) if has("ev_proposals") else 0) + \
                  (n(f"SELECT COUNT(*) n FROM mb_experiments WHERE status='done' AND finished>? AND flow_id IN ({fph})", (wk, *flows)) if flows and has("mb_experiments") else 0) + \
                  (n(f"SELECT COUNT(*) n FROM au_sprints WHERE started>? AND comp_id IN ({cph})", (wk, *comps)) if teams_on and has("au_sprints") else 0)
            prom = c("ev_proposals", "SELECT COUNT(*) n FROM ev_proposals WHERE user_id=? AND promoted>?", (uid, wk)) + wfq("status='promoted' AND updated>?", wk) + \
                   mbq("status IN ('promoted','applied') AND updated>?", wk) + \
                   (n(f"SELECT COUNT(*) n FROM au_agents WHERE decision='promoted' AND decided>? AND comp_id IN ({cph})", (wk, *comps)) if teams_on and has("au_agents") else 0)
            # a person's decision on a measured change: promote or reject (Evolution Lab, Workforce improvements, Upgrade sprints)
            appr = c("ev_proposals", "SELECT COUNT(*) n FROM ev_proposals WHERE user_id=? AND decision='human' AND status IN ('promoted','rejected','rolled_back') AND updated>?", (uid, wk)) + \
                   wfq("decided_by IS NOT NULL AND status IN ('promoted','rejected') AND updated>?", wk) + \
                   (n(f"SELECT COUNT(*) n FROM au_agents WHERE decision IS NOT NULL AND decided>? AND comp_id IN ({cph})", (wk, *comps)) if teams_on and has("au_agents") else 0)
            mon = (n(f"SELECT COUNT(*) n FROM mb_watches WHERE flow_id IN ({fph}) AND status='kept' AND COALESCE(ended, started)>?", (*flows, wk)) if flows and has("mb_watches") else 0) + \
                  c("io_monitor", "SELECT COUNT(*) n FROM io_monitor WHERE owner_id=? AND state IN ('watching','kept','regressed') AND checked>?", (uid, wk))
            waits = c("ev_proposals", "SELECT COUNT(*) n FROM ev_proposals WHERE user_id=? AND status='verified'", (uid,)) + wfq("status='better'")
            back = (n(f"SELECT COUNT(*) n FROM mb_watches WHERE flow_id IN ({fph}) AND status='rolled_back' AND COALESCE(ended, started)>?", (*flows, wk)) if flows and has("mb_watches") else 0) + \
                   c("ev_proposals", "SELECT COUNT(*) n FROM ev_proposals WHERE user_id=? AND status='rolled_back' AND updated>?", (uid, wk))
            steps = (("observe", "Observe", "Failed, lost or poorly scored runs", obs, "studio"),
                     ("diagnose", "Diagnose", "Failed runs classified with a recovery, and root causes written", diag, "learning"),
                     ("propose", "Propose", "Changes proposed to prompts, skills, tools or models", prop, "evolution"),
                     ("experiment", "Experiment", "Candidates tested in isolation", exp, "evolution"),
                     ("evaluate", "Evaluate", "Blind trials, Lab evals and exam sprints", evl, "evolution"),
                     ("approve", "Approve", "Your decisions on measured changes: promote or reject", appr, "evolution"),
                     ("promote", "Promote", "Changes promoted on evidence", prom, "evolution"),
                     ("monitor", "Monitor", "Promoted changes watched on later work", mon, "learning"),
                     ("rollback", "Roll back", "Changes rolled back after they scored worse", back, "evolution"))
            seen, stall = False, None
            for k, *_rest in steps:
                if k == "rollback" or (k == "approve" and not waits): continue  # nothing to roll back, or nothing measured better to decide: no stall
                v = _rest[2]
                if v: seen = True
                elif seen and stall is None: stall = k
            out["pipeline"] = [{"key": k, "label": l, "what": w, "n": v, "view": vw, "stall": k == stall} for k, l, w, v, vw in steps]

        # ---------- the loop's handoffs this week: the orchestrator's event ledger, the same rows and window as its own table ----------
        def links():
            from . import orchestrator
            o = orchestrator.get()
            out["links"], out["links_since"] = (o.edges(uid, wk) if o is not None else []), wk  # no orchestrator (tests): nothing recorded

        for label, fn in (("Mission intelligence", mission), ("Workforce intelligence", workforce_), ("Execution intelligence", execution),
                          ("Knowledge intelligence", knowledge), ("Evaluation", evaluation), ("Adaptive intelligence", adaptive),
                          ("Improvement evidence", evidence), ("Evolution engine", pipeline), ("Loop handoffs", links),
                          ("Loop acceptance", lambda: out.update(acceptance=self.acceptance(uid)))):
            self._try(out, label, fn)

        out["layers"] = []
        moved, ledger = {}, bool(out["links"])  # handoffs this week into or out of each layer, from the same ledger as the handoff table
        for e in out["links"]:
            for k in (e["from"], e["to"]):
                if k in TITLE: moved[k] = moved.get(k, 0) + (e["done"] or 0)
        for key, title, ic, about, prio in LAYERS:
            ps = parts[key]
            req = [p for p in ps if p["required"]]
            if any(not p["present"] for p in req): status = "incomplete"
            elif any(p["state"] == "degraded" for p in ps): status = "degraded"
            elif req and all(p["active"] for p in req) and (moved.get(key) or not ledger): status = "operational"
            elif moved.get(key) or any(p["active"] for p in req): status = "partial"  # some of it worked this week, not all of it
            else: status = "idle"
            out["layers"].append({"key": key, "title": title, "icon": ic, "about": about, "status": status, "priority": prio, "parts": ps,
                                  "present": sum(1 for p in ps if p["present"]), "total": len(ps), "moved": moved.get(key, 0),
                                  "required": len(req), "working": sum(1 for p in req if p["active"])})
        st = {x["key"]: x["status"] for x in out["layers"]}
        for x in out["layers"]:
            x["depends"] = [{"key": k, "title": TITLE[k], "why": why, "status": st[k]} for k, why in DEPENDS.get(x["key"], ())]
        out["score"] = {s: sum(1 for x in out["layers"] if x["status"] == s) for s in ("operational", "partial", "degraded", "idle", "incomplete")}
        out["fix"] = self._fix(out["layers"])

    @staticmethod
    def _fix(layers):
        """What to fix first: failed checks, then missing required parts, then warnings, then quiet required parts; the review's
        priorities (evaluation, adaptive, mission = P0) order within each."""
        rank = {"P0": 0, "P1": 1, "P2": 2}
        items = []
        for L in layers:
            for p in L["parts"]:
                base = {"layer": L["key"], "layer_title": L["title"], "part": p["name"], "view": p["view"], "priority": L["priority"]}
                for c in p["checks"]:
                    items.append({**base, "level": c["level"], "text": c["text"], "o": (0 if c["level"] == "fail" else 2, rank[L["priority"]])})
                if p["required"] and not p["present"]:
                    items.append({**base, "level": "fail", "text": f"{p['name']} isn't set up, so {L['title'].lower()} can't work", "o": (1, rank[L["priority"]])})
                elif p["required"] and p["state"] == "idle":
                    items.append({**base, "level": "idle", "text": f"{p['name']} did nothing this week", "o": (3, rank[L["priority"]])})
        items.sort(key=lambda x: x.pop("o"))
        return items[:10]

    # ---------- the mission lifecycle acceptance test (the review's eight steps), from the records each step leaves ----------
    def loop_check(self, uid, m):
        """[{n, key, label, state, detail, evidence}]: pass / fail / pending / na for each of the eight steps, each with the records
        that show it (evidence: short refs). Steps 1-6 are the mission's own lifecycle; 7 (Evolve) is exercised when something about
        the mission failed or scored low, else na; 8 (Improve the next mission) passes when a later plan took what this one left."""
        has, ref = self._has, f"mx:{m['id']}"
        u, d, plan, v = (_j(m[k], {}) or {} for k in ("understanding", "discovery", "plan", "verification"))
        corr = has("ac_runs") and "corr" in {r["name"] for r in self.db.q("PRAGMA table_info(ac_runs)")}
        runs = self.db.q(f"SELECT id, status, decision, kind, agent_key, score FROM ac_runs WHERE owner_id=? AND {'(ref=? OR corr=?)' if corr else 'ref=?'}",
                         (uid, ref, ref) if corr else (uid, ref)) if has("ac_runs") else []
        ended = m["status"] in ("delivered", "done", "failed", "cancelled") or bool(m["outcome"])
        out = []
        def step(key, label, state, detail, evidence=()): out.append({"n": len(out) + 1, "key": key, "label": label, "state": state, "detail": detail,
                                                                      "evidence": [e for e in evidence if e][:6]})
        bs, why = brief_state(d)
        b = d.get("brief") or {}
        step("understand", "Understand: research the objective and gather current information", {"researched": "pass", "no_web": "pass", "pending": "pending"}.get(bs, "fail"),
             {"researched": "Researched with the web", "no_web": "Researched without the open web", "skipped": f"Skipped: {why}", "none": "No brief was filed",
              "pending": "Not discovered yet"}[bs] + (f"; {len(d.get('knowledge') or [])} Knowledge Hub record(s), {len(d.get('lessons') or [])} lesson(s) read" if d else ""),
             [f"brief: {len(b.get('facts') or [])} fact(s), {b.get('lookups') or 0} lookup(s)" if b and not b.get("skipped") else "", f"{ref} discovery" if d else ""])
        crit, tasks = u.get("criteria") or [], plan.get("tasks") or []
        dl = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(m["deadline"])) if m["deadline"] else "no deadline"
        step("plan", "Plan: deliverables, budget, deadline and validation criteria", "pass" if crit and tasks and m["budget"] else "pending" if not ended else "fail",
             f"{len(tasks)} task{'s' if len(tasks) != 1 else ''}, {len(crit)} acceptance criteri{'a' if len(crit) != 1 else 'on'}, "
             f"budget ${m['budget'] or 0:g} (hard limit), {dl}", [f"{ref} plan" if tasks else ""])
        routed = [r for r in runs if r["decision"]]
        model = (_j(m["allocation"], {}) or {}).get("model")
        step("assemble", "Assemble: agents, models, skills and tools", "pass" if m["engine"] and (routed or model) else "pending" if not ended else "fail",
             f"Engine {m['engine'] or '–'}" + (f" on {model}" if model else "") + (f", {len(routed)} routed call{'s' if len(routed) != 1 else ''}" if routed else ""),
             [f"{ref} allocation: {m['engine']}" + (f" on {model}" if model else "") if m["engine"] else ""] + [f"run #{r['id']} routed" for r in routed[:3]])
        work = [r for r in runs if r["kind"] not in ("understand", "discover", "plan", "allocate", "verify", "deliver", "learn")]
        done = [r for r in work if r["status"] == "done"]
        bad = [r for r in work if r["status"] in FAILED]
        sbx = []  # a Competition team mission's sandbox runs: its team's, from when the mission handed the work over until it ended
        if m["engine"] == "mining" and m["child"] and has("mw_sbx") and m.get("child_started"):
            sbx = self.db.q("SELECT id, status, exit_code FROM mw_sbx WHERE comp_id=? AND started>=? AND started<=? ORDER BY id",
                            (m["child"], m["child_started"] - 5, m["finished"] or time.time()))
        ran = [x for x in sbx if x["status"] in ("done", "failed")]  # the code ran to an exit (pass or fail); errors and timeouts didn't
        step("execute", "Execute: run the mission's work", "pass" if done else "pending" if not ended else "fail",
             f"{len(done)} work run{'s' if len(done) != 1 else ''} finished" + (f", {len(bad)} failed" if bad else "")
             + (f" by the {m['engine']} engine (child #{m['child']})" if m["child"] else "")
             + (f"; {len(sbx)} sandbox run{'s' if len(sbx) != 1 else ''}, {len(ran)} ran to an exit" if sbx else "; no sandbox run" if m["engine"] == "mining" and ended else ""),
             [f"run #{r['id']}" for r in done[:3]] + [f"sandbox #{x['id']} {x['status']}" + (f" (exit {x['exit_code']})" if x["exit_code"] is not None else "") for x in sbx[-3:]])
        res, ds = v.get("results") or [], v.get("dataset") or {}
        ind = v.get("independent", True)
        step("evaluate", "Evaluate: independently verify the deliverables against the frozen criteria",
             "pass" if res and ind else "fail" if res or ended else "pending",
             (f"{sum(1 for x in res if x.get('status') == 'met')} of {len(res)} criteria met" + ("" if ind else "; the checker ran on the worker's own model")
              + (f"; criteria frozen as dataset v{ds['version']}" + ("" if ds["version"] == 1 else ", changed after the work began") if ds.get("version") else "")) if res else "Not checked",
             [f"verified by {v.get('model')}" if res and v.get("model") else "", f"dataset {ds['sha'][:8]}" if ds.get("sha") else ""])
        les = self.db.q("SELECT id FROM mx_lessons WHERE user_id=? AND mission_id=?", (uid, m["id"])) if has("mx_lessons") else []
        lids = {x["id"] for x in les}
        step("learn", "Learn: keep methods, failures and reusable knowledge", "pass" if les else "pending" if not ended else "fail",
             f"{len(les)} lesson{'s' if len(les) != 1 else ''} kept", [f"lesson #{i}" for i in sorted(lids)[:4]])
        # 7 Evolve: diagnose → propose → experiment → your approval → monitor, for this mission's genuine weak points. A run that
        # failed for the environment's reason (restart, quota, budget, provider, rate limit, timeout, sandbox, tool: anything but
        # orchestrator.OWN_FAULT) is no weakness of the work, so it doesn't call for evolving; one not classified yet keeps it pending.
        from .orchestrator import FAILURE_CLASSES, OWN_CANON  # G5-2 (D-015 D1): the canonical class decides whose fault it is
        fids = [r["id"] for r in runs if r["status"] in FAILED]
        dcols = "run_id, cls, recoverable" + (", canon" if has("io_diag") and "canon" in {c["name"] for c in self.db.q("PRAGMA table_info(io_diag)")} else ", NULL AS canon")
        dg = {x["run_id"]: x for x in self.db.q(f"SELECT {dcols} FROM io_diag WHERE run_id IN ({','.join('?' * len(fids))})", fids)} \
            if fids and has("io_diag") else {}
        kind = lambda i: dg[i]["canon"] or dg[i]["cls"]
        own = [i for i in fids if i in dg and kind(i) in OWN_CANON]
        unclassified = [i for i in fids if i not in dg]
        env = sorted({FAILURE_CLASSES.get(kind(i), {}).get("label", kind(i)) for i in fids if i in dg and kind(i) not in OWN_CANON})
        low = [r for r in runs if r["score"] is not None and r["score"] < LOW]
        weak = own or low or any(x.get("status") in ("not_met", "partly") for x in res) or m["outcome"] == "failed"
        agents = sorted({r["agent_key"] for r in runs if r["agent_key"]})
        props = self.db.q(f"""SELECT id, status, tested, decision, promoted FROM ev_proposals WHERE user_id=? AND created>=?
                              AND target_key IN ({','.join('?' * len(agents))})""", (uid, m["created"] or 0, *agents)) if agents and has("ev_proposals") else []
        if not weak and unclassified:
            step("evolve", "Evolve: diagnose weaknesses, propose changes and test candidates", "pending",
                 f"{len(unclassified)} failed run{'s' if len(unclassified) != 1 else ''} not classified yet (the orchestrator does it within a minute)")
        elif not weak:
            step("evolve", "Evolve: diagnose weaknesses, propose changes and test candidates", "na",
                 "Nothing in the work failed, scored low or missed a criterion: no weakness to evolve from this mission"
                 + (f". {len(fids)} run{'s' if len(fids) != 1 else ''} failed for the environment ({', '.join(env)}), not the work" if env else ""),
                 [f"run #{i} {dg[i]['cls']}" for i in fids[:3]])
        else:
            diag = sum(1 for i in fids if i in dg)
            tested = [p for p in props if p["tested"]]
            decided = [p for p in props if p["status"] in ("promoted", "rolled_back") and p["decision"] == "human"]
            waiting = [p for p in props if p["status"] == "verified"]
            pids = [p["id"] for p in props if p["promoted"]]
            mon = self.db.q(f"SELECT state FROM io_monitor WHERE proposal_id IN ({','.join('?' * len(pids))})", pids) if pids and has("io_monitor") else []
            parts = [f"{diag} failed run{'s' if diag != 1 else ''} diagnosed", f"{len(props)} proposal{'s' if len(props) != 1 else ''} for its agents",
                     f"{len(tested)} measured against the current version on a frozen benchmark"]
            if decided: parts.append(f"{len(decided)} promoted or rolled back by you")
            if waiting: parts.append(f"{len(waiting)} measured better, waiting for your approval")
            if mon: parts.append("monitor: " + ", ".join(sorted({x["state"].replace("_", " ") for x in mon})))
            step("evolve", "Evolve: diagnose weaknesses, propose changes and test candidates",
                 "pass" if tested else "pending",
                 "; ".join(parts) + ("" if props else ". The Evolution engine proposes a change once one agent fails or scores low repeatedly; "
                                                     "approve its experiment in Adaptive evolution"),
                 [f"proposal #{p['id']}" for p in props[:4]])
        # 8 Improve the next mission: a later plan took this mission's lessons or what was learned from its agents
        pset = {p["id"] for p in props}
        later, how = None, ""
        if ended and has("mx_missions"):
            for x in self.db.q("SELECT id, title, discovery FROM mx_missions WHERE user_id=? AND id>? AND discovery IS NOT NULL ORDER BY id LIMIT 50", (uid, m["id"])):
                dx = _j(x["discovery"], {}) or {}
                took = lids & {y.get("id") for y in dx.get("lessons") or []}
                if took or m["id"] in {y.get("id") for y in dx.get("missions") or []}:
                    later, how = f"mx:{x['id']}", f"Mission #{x['id']} planned with " + (f"{len(took)} of its lesson{'s' if len(took) != 1 else ''}" if took else "it as an earlier mission")
                    break
        if ended and not later and has("io_events") and (lids or pset):
            for e in self.db.q("SELECT id, corr, payload FROM io_events WHERE owner_id=? AND kind='mission.guided' AND created>=? ORDER BY id LIMIT 200",
                               (uid, m["finished"] or m["updated"] or 0)):
                R = (_j(e["payload"], {}) or {}).get("refs") or {}
                if lids & set(R.get("lessons") or []) or pset & set(R.get("proposals") or []):
                    later, how = e["corr"], f"{e['corr']} was planned with what this mission left (event #{e['id']})"
                    break
        step("improve", "Improve the next mission: feed what was verified into the next plan", "pass" if later else "pending",
             how or ("Waiting for the mission to end" if not ended else "No later plan has taken its lessons yet: start a follow-up mission on the same goal"),
             [later or ""])
        return out

    def acceptance(self, uid):
        """The newest missions that passed the lifecycle (steps 1-6) and the whole loop (1-6 and 8 pass, 7 passes or had nothing to
        evolve), of the last TRACE_LIST; and the newest ended mission still waiting for step 8 (its follow-up is the next test)."""
        if not self._has("mx_missions"): return None
        life = full = follow = None
        ms = self.db.q("SELECT * FROM mx_missions WHERE user_id=? ORDER BY id DESC LIMIT ?", (uid, TRACE_LIST))
        for m in ms:
            c = self.loop_check(uid, m)
            row = {"id": m["id"], "title": m["title"], "goal": m["goal"], "finished": m["finished"], "passed": sum(1 for x in c if x["state"] == "pass"),
                   "steps": len(c), "engine": m["engine"], "sandbox": any(e.startswith("sandbox #") for e in c[3]["evidence"])}
            life_ok = all(x["state"] == "pass" for x in c[:6])
            if not life and life_ok: life = row
            if not full and life_ok and c[6]["state"] in ("pass", "na") and c[7]["state"] == "pass": full = row
            if not follow and not full and life_ok and c[7]["state"] == "pending" and m["finished"]: follow = row
            if life and full: break
        return {"checked": len(ms), "lifecycle": life, "loop": full, "follow_up": follow,
                "open": self._n("SELECT COUNT(*) n FROM mx_missions WHERE user_id=? AND status IN ('queued','running','needs_input','paused')", (uid,))}

    # ---------- one mission through the six layers ----------
    def trace(self, me, mission=None):
        self._agents(me)
        uid = me["id"]
        if not self._has("mx_missions"): return {"missions": [], "trace": None}
        ms = self.db.q("SELECT id, title, status, outcome, created FROM mx_missions WHERE user_id=? ORDER BY id DESC LIMIT ?", (uid, TRACE_LIST))
        if mission is None: return {"missions": ms, "trace": None}
        m = self.db.q("SELECT * FROM mx_missions WHERE id=? AND user_id=?", (mission, uid), one=True)
        if not m: raise HTTPException(404, "No such mission of yours.")
        ref, n, has = f"mx:{m['id']}", self._n, self._has
        u, d, plan = _j(m["understanding"], {}) or {}, _j(m["discovery"], {}) or {}, _j(m["plan"], {}) or {}
        v, alloc = _j(m["verification"], {}) or {}, _j(m["allocation"], {}) or {}
        L = []

        def layer(key, lines, state=None):
            L.append({"key": key, "title": TITLE[key], "state": state or ("done" if lines else "empty"), "lines": lines or ["Nothing recorded for this mission."]})

        # mission
        bs, why = brief_state(d)
        b = d.get("brief") or {}
        lines = []
        if u.get("objective"): lines.append(f"Objective: {u['objective']}")
        if u.get("criteria"): lines.append(f"{len(u['criteria'])} acceptance criteria")
        lines.append({"researched": f"Researched: {len(b.get('facts') or [])} facts, {len(b.get('competitors') or [])} competitors, {len(b.get('latest') or [])} recent developments",
                      "no_web": f"Researched without the web: {len(b.get('facts') or [])} facts, {len(b.get('competitors') or [])} competitors",
                      "skipped": f"Research skipped: {why}", "none": "Not researched (no brief was filed)", "pending": "Not discovered yet"}[bs])
        if plan.get("tasks"): lines.append(f"Plan: {len(plan['tasks'])} task{'s' if len(plan['tasks']) != 1 else ''}")
        layer("mission", lines, "broken" if bs in ("skipped", "none") else None)
        # workforce
        corr = has("ac_runs") and "corr" in {r["name"] for r in self.db.q("PRAGMA table_info(ac_runs)")}
        # G5: with correlation ids, the mission's child engine's runs count too (they carry corr mx:N); their tokens are then in the ledger
        runs = self.db.q(f"SELECT status, model, decision, score, tokens, cost, error, kind, ref FROM ac_runs WHERE owner_id=? AND {'(ref=? OR corr=?)' if corr else 'ref=?'}",
                         (uid, ref, ref) if corr else (uid, ref)) if has("ac_runs") else []
        child_in_ledger = any(r["ref"] != ref for r in runs)
        lines = []
        if m["engine"]: lines.append(f"Engine: {m['engine']}" + (f" (child #{m['child']})" if m["child"] else ""))
        if alloc.get("model"): lines.append(f"Worker model: {alloc['model']}")
        models = sorted({r["model"] for r in runs if r["model"]})
        if models: lines.append("Models used: " + ", ".join(models[:6]))
        routed = sum(1 for r in runs if r["decision"])
        if routed: lines.append(f"{routed} call{'s' if routed != 1 else ''} routed by the model router")
        layer("workforce", lines)
        # execution
        bad = [r for r in runs if r["status"] in FAILED]
        lines = []
        if runs: lines.append(f"{len(runs)} run{'s' if len(runs) != 1 else ''} in the ledger, {len(bad)} failed or lost")
        tok = sum(r["tokens"] or 0 for r in runs) + (0 if child_in_ledger else (m["child_tokens"] or 0))
        if tok: lines.append(f"{tok:,} tokens" + (f", ${(m['own_usd'] or 0) + (m['child_usd'] or 0):.2f}" if (m["own_usd"] or 0) + (m["child_usd"] or 0) else ""))
        if m["attempts"]: lines.append(f"{m['attempts']} attempt{'s' if m['attempts'] != 1 else ''}")
        cls = {}
        for r in bad:
            k = fail_class(r["status"], r["error"]); cls[k] = cls.get(k, 0) + 1
        if cls: lines.append("Failures: " + ", ".join(f"{FAIL_LABEL.get(k, k).lower()} {v}" for k, v in cls.items()))
        if m["failure"] or m["error"]: lines.append(f"Last failure: {str(m['failure'] or m['error'])[:240]}")
        layer("execution", lines, "broken" if m["status"] == "failed" else None)
        # knowledge
        lines = []
        found = {k: len(d.get(k) or []) for k in ("knowledge", "lessons", "missions", "memories", "experience") if isinstance(d.get(k), list)}
        if found: lines.append(("Found at discovery: " + ", ".join(f"{v} {k}" for k, v in found.items() if v)) if any(found.values()) else "Found nothing at discovery")
        if has("ex_recalls"):
            r = self.db.q("SELECT COUNT(*) n, COALESCE(SUM(found),0) f FROM ex_recalls WHERE user_id=? AND context=?", (uid, ref), one=True) or {}
            if r.get("n"): lines.append(f"{r['n']} experience recall{'s' if r['n'] != 1 else ''}, {r['f']} experience{'s' if r['f'] != 1 else ''} found")
        layer("knowledge", lines)
        # evaluation
        lines = []
        res = v.get("results") or []
        if res:
            c = {s: sum(1 for x in res if x.get("status") == s) for s in ("met", "partly", "not_met", "unverifiable")}
            lines.append(f"Independent check: {c['met']} met, {c['partly']} partly, {c['not_met']} not met, {c['unverifiable']} unverifiable of {len(res)}")
            if v.get("independent") is False: lines.append("The checker ran on the worker's own model: not independent")
        if m["outcome"]: lines.append(f"Outcome: {m['outcome']}")
        sc = [r["score"] for r in runs if r["score"] is not None]
        if sc: lines.append(f"{len(sc)} scored run{'s' if len(sc) != 1 else ''}, average {round(sum(sc) / len(sc))}")
        layer("evaluation", lines, "broken" if m["outcome"] in ("failed",) else None)
        # adaptive
        lines = []
        les = self.db.q("SELECT id, kind, used FROM mx_lessons WHERE user_id=? AND mission_id=?", (uid, m["id"])) if has("mx_lessons") else []
        if les: lines.append(f"{len(les)} lesson{'s' if len(les) != 1 else ''} kept, reused {sum(x['used'] or 0 for x in les)} time(s) since")
        if has("ex_uses"):
            o = self.db.q("SELECT outcome, COUNT(*) n FROM ex_uses WHERE user_id=? AND context=? GROUP BY outcome", (uid, ref))
            if o: lines.append("Recalled experiences settled: " + ", ".join(f"{x['n']} {x['outcome'] or 'still open'}" for x in o))
            refs = [ref] + [f"mxl:{x['id']}" for x in les]
            later = n(f"SELECT COUNT(*) n FROM ex_uses WHERE user_id=? AND context!=? AND ref IN ({','.join('?' * len(refs))})", (uid, ref, *refs))
            lines.append(f"Recalled by later work {later} time{'s' if later != 1 else ''}" if later else "Not recalled by later work yet")
        layer("adaptive", lines)
        from . import orchestrator
        g5 = None
        if orchestrator.get():  # G5: every run correlated to the mission (its child engine's too) and its handoff events
            try: g5 = orchestrator.get().trace(uid, ref)
            except Exception as e:  # noqa: BLE001 - the trace stands without it
                g5 = {"error": str(e)}
        return {"missions": ms, "trace": {"id": m["id"], "title": m["title"], "goal": m["goal"], "status": m["status"], "outcome": m["outcome"],
                                          "created": m["created"], "finished": m["finished"], "layers": L, "g5": g5, "acceptance": self.loop_check(uid, m)}}


def build(db, require, ov, co=None):
    r = APIRouter(prefix="/api/layers")
    h = Layers(db, ov, co)
    r.state = {"layers": h}

    @r.get("")
    def layers(req: Request, fresh: bool = False): return h.view(require(req), fresh)

    @r.get("/trace")
    def trace(req: Request, mission: int | None = None): return h.trace(require(req), mission)

    return r
