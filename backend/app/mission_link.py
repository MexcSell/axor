"""Mission Control ⇄ My subnets (missions.py ⇄ mining_work.py): the mission asks for a Competition team instead of falling back
silently, and the command map shows who commands whom, live.

The team request. A mission whose work belongs on a Competition team (the Mission Engine picks engine=mining) but has none that fits
doesn't quietly run on the Workforce any more. AXoR works out the target (the subnet and the competition: the goal's own words,
"SN62", "competition 28", first; the model's reading next), and the mission waits for the user with one request: create that team.
- Approve: the team is created exactly as the request says (the hash binds it), autopilot off. Without a campaign on that subnet,
  My subnets' campaign is started too, and the request says so up front: it runs one kickoff planning cycle. The mission goes on, on
  the new team.
- Use a team you already have: the mission goes on, on that one.
- Reject (or the request expires): the mission goes on, on the Workforce, and its timeline says so in plain words.
Creating a team is something only the user does: the request carries it out only on the user's approval, never on its own.

The command map: you → missions → the engines → (for a Competition team) the Director → its squads' heads → the agents, with what
each is doing right now, what's waiting for you, and what's missing (a team the mission needs and doesn't have). It reads the
tables as they are: nothing here writes, and a team you don't own never shows.
"""
import re, time

from fastapi import HTTPException

from . import mining, mining_packs, mining_work
from .task_lifecycle import not_dropped  # D-018: dropped work isn't completed work

SN = re.compile(r"\b(?:sn|subnet|netuid)\s*[-#:]?\s*(\d{1,4})\b", re.I)
COMP = re.compile(r"\b(?:comp|competition|contest)\s*[-#:]?\s*(\d{1,6})\b", re.I)
TEAM_HOURS = 72          # a team request waits this long; then the mission goes on without one
MAP_AGENTS = 40          # agents drawn per team on the map
MAP_TEAMS = 8            # teams drawn on the overview


def _clip(s, n): s = str(s or ""); return s if len(s) <= n else s[:n - 1] + "…"


def target(text, u=None):
    """The subnet and competition a mission is about: {"netuid": int|None, "number": int|None}. The goal's own words first (they are
    the user's), the model's reading of them next."""
    t = (u or {}).get("mining_target") or {}
    net = int(x.group(1)) if (x := SN.search(text or "")) else int(t.get("netuid") or 0)
    num = int(x.group(1)) if (x := COMP.search(text or "")) else int(t.get("competition") or 0)
    return {"netuid": net if 1 <= net <= 4096 else None, "number": num if num > 0 else None}


def fits(t, tgt):
    """Whether a team works on what the goal names: its subnet, and its competition when one is named."""
    return (not tgt["netuid"] or t.get("netuid") == tgt["netuid"]) and (tgt["number"] is None or t.get("number") == tgt["number"])


def match(teams, tgt, picked=None):
    """The user's team for the target, or None. The model's pick when it fits what the goal names; else, with a competition named,
    only that competition's team; with only a subnet, the first team on it; with neither, the only team there is."""
    if picked is not None and (t := next((t for t in teams if t["id"] == picked), None)) and fits(t, tgt): return picked
    if not tgt["netuid"]: return teams[0]["id"] if len(teams) == 1 else None
    same = [t for t in teams if fits(t, tgt)]
    return same[0]["id"] if same else None


def proposal(db, uid, tgt, title, others=0):
    """What the team request creates, in full: the hash binds the user's approval to exactly this."""
    camp = db.q("SELECT id FROM mh_campaigns WHERE user_id=? AND netuid=? ORDER BY COALESCE(mech, 0), id LIMIT 1", (uid, tgt["netuid"]), one=True)
    name = "" if tgt["number"] is not None else _clip(title or f"SN{tgt['netuid']} mission team", 80)
    pack = mining_packs.pick(name)  # what Work.create's team="auto" picks for a team without a Ridges link
    p = mining_packs.PACKS[pack]
    return {"netuid": tgt["netuid"], "number": tgt["number"], "name": name, "campaign": camp["id"] if camp else None,
            "pack": pack, "pack_label": p["label"], "agents": len(p["agents"]), "others": others}


def action(prop):
    """The request's wording: what approving does, the campaign's kickoff included."""
    where = f"SN{prop['netuid']}" + (f" · competition {prop['number']}" if prop["number"] is not None else f" · “{prop['name']}”")
    s = f"Create a Competition team for {where}: the {prop['pack_label']} ({prop['agents']} agents), autopilot off, and run this mission on it"
    if prop.get("others"):  # a team imported without a competition number may be this very competition
        s += (f". You already have {prop['others']} team{'s' if prop['others'] != 1 else ''} on SN{prop['netuid']}: "
              "if one of them is this competition, use it below instead")
    if prop["campaign"] is None:
        s += f". You have no SN{prop['netuid']} campaign yet: approving also starts one in My subnets, which runs one kickoff planning cycle"
    return s


def make_team(work, me, prop, ip=""):
    """Creates the team the approved request describes and returns its id. A team for that competition made meanwhile is used as is."""
    db, cid = work.db, prop["campaign"]
    if cid is not None and not db.q("SELECT 1 FROM mh_campaigns WHERE id=? AND user_id=?", (cid, me["id"]), one=True): cid = None
    if cid is None:
        r = db.q("SELECT id FROM mh_campaigns WHERE user_id=? AND netuid=? ORDER BY COALESCE(mech, 0), id LIMIT 1", (me["id"], prop["netuid"]), one=True)
        if r: cid = r["id"]
        else:
            try: cid = work.m.create(me, mining.CampaignIn(netuid=prop["netuid"], mechs=[0]), ip)["id"]
            except HTTPException as e:
                raise HTTPException(e.status_code, f"Couldn't start the SN{prop['netuid']} campaign: {e.detail} Start it in My subnets, then use that team.")
    if prop["number"] is not None and (w := db.q("SELECT id FROM mw_comps WHERE campaign_id=? AND number=?", (cid, prop["number"]), one=True)):
        return w["id"]
    view = work.create(me, cid, mining_work.CompIn(number=prop["number"], name=prop["name"], team="auto",
                                                    notes="Made from a Mission Control request the user approved."), ip)
    return view["comp"]["id"]


# ---------- the command map ----------
def _team_node(db, w, deep):
    """One Competition team on the map: the Director (the team's lead), its squads and their heads, and the agents."""
    n = db.q(f"""SELECT COUNT(*) total, SUM(status='done' AND {not_dropped(db)}) done, SUM(status IN ('queued','working','checking')) busy,
                       SUM(status IN ('review','blocked')) waiting FROM mw_tasks WHERE comp_id=?""", (w["id"],), one=True)
    planning = bool(db.q("SELECT 1 FROM mw_runs WHERE comp_id=? AND kind='plan' AND status='running'", (w["id"],), one=True))
    report = db.q("SELECT COUNT(*) n FROM mw_reports WHERE comp_id=? AND status='new'", (w["id"],), one=True)["n"] if _has(db, "mw_reports") else 0
    out = {"id": w["id"], "label": w["label"], "netuid": w.get("netuid"), "number": w["number"], "status": w["status"],
           "autopilot": bool(w.get("autopilot")), "paused": bool(w.get("paused")), "relay": bool(w.get("relay", 1)), "planning": planning,
           "report": report, "tasks": {"total": n["total"] or 0, "done": n["done"] or 0, "busy": n["busy"] or 0, "waiting": n["waiting"] or 0}}
    agents = db.q("SELECT id, name, title, role, lead, active, squad, head FROM mw_agents WHERE comp_id=? ORDER BY lead DESC, head DESC, id", (w["id"],))
    out["agent_count"] = len(agents)
    if not deep: return out
    running = {r["agent_id"]: r for r in db.q("SELECT agent_id, task_id, kind FROM mw_runs WHERE comp_id=? AND status='running'", (w["id"],))}
    titles = {t["id"]: t["title"] for t in db.q("SELECT id, title FROM mw_tasks WHERE comp_id=? AND status IN ('queued','working','checking')", (w["id"],))}
    queued = {r["agent_id"] for r in db.q("SELECT DISTINCT agent_id FROM mw_tasks WHERE comp_id=? AND status='queued'", (w["id"],))}
    def node(a):
        r = running.get(a["id"])
        st = "off" if not a["active"] else "working" if r else "queued" if a["id"] in queued else "idle"
        return {"id": a["id"], "name": a["name"], "title": a["title"], "state": st, "squad": a["squad"] or "", "head": bool(a["head"]),
                "doing": _clip(titles.get(r["task_id"]) if r and r["task_id"] else ("Planning" if r and r["kind"] == "plan" else ""), 90)}
    lead = next((a for a in agents if a["lead"]), None)
    out["director"] = node(lead) if lead else None
    squads = {}
    for a in agents:
        if lead and a["id"] == lead["id"]: continue
        squads.setdefault(a["squad"] or "", []).append(node(a))
    out["squads"] = [{"key": k, "label": mining_packs.SQUADS.get(k, k.title() if k else "Team"),
                      "head": next((x for x in xs if x["head"]), None),
                      "agents": [x for x in xs if not x["head"]][:MAP_AGENTS],
                      "working": sum(x["state"] == "working" for x in xs), "count": len(xs)}
                     for k, xs in sorted(squads.items(), key=lambda kv: (kv[0] == "", kv[0]))]
    return out


def _has(db, table):
    return bool(db.q("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,), one=True))


def _predefined(db, uid, teams, team=None):
    """Predefined missions on the map: each open Competition team's own (comp:<id>, Control Hub). They run on the team's board
    through the Control Hub's dispatcher, not through Mission Control, so the map drew "No mission running" over a team at work."""
    out = []
    tasks = _has(db, "ctl_tasks")
    briefs = _has(db, "ctl_briefs")
    for t in teams:
        if (t.get("status") or "active") == "closed" or (team is not None and t["id"] != team): continue
        ref = f"comp:{t['id']}"
        c = db.q("""SELECT COUNT(*) n, SUM(kind='fixed') fixed, SUM(status='running') running, SUM(status IN ('review','needs_input')) waiting
                    FROM ctl_tasks WHERE user_id=? AND mission=? AND status IN ('todo','running','review','needs_input')""", (uid, ref), one=True) if tasks else {}
        r = db.q("SELECT COUNT(*) n FROM ctl_briefs WHERE user_id=? AND mission=? AND state='running'", (uid, ref), one=True)["n"] if briefs else 0
        n = (c or {}).get("n") or 0
        out.append({"ref": ref, "team": t["id"], "title": f"SN{t.get('netuid') or '?'} · {t['label']}", "open": n, "fixed": (c or {}).get("fixed") or 0,
                    "dynamic": n - ((c or {}).get("fixed") or 0), "running": (c or {}).get("running") or 0, "waiting": (c or {}).get("waiting") or 0,
                    "researching": r, "working": t.get("working") or 0, "autopilot": bool(t.get("autopilot")), "paused": bool(t.get("paused"))})
    return out


def command_map(mx, me, mission=None, team=None):
    """The chain of command, live: you, your missions, the engines and the Competition teams under them. mission= focuses on one
    mission's chain; team= on one team (My subnets' team page)."""
    db, uid = mx.db, me["id"]
    if mission is not None: rows = [mx._own(me, mission)]
    else:
        rows = [mx._m(r["id"]) for r in db.q("SELECT id FROM mx_missions WHERE user_id=? AND status IN ('queued','running','needs_input','paused') ORDER BY id DESC LIMIT 12", (uid,))]
    if team is not None:
        if not mx.mw: raise HTTPException(404, "My subnets isn't on this server.")
        mx.mw._own(me, team)  # 404 for a team that isn't the user's
        # the team's live missions, and its last two results (cancelled ones aren't part of the chain)
        live = db.q("SELECT id FROM mx_missions WHERE user_id=? AND team=? AND status IN ('queued','running','needs_input','paused') ORDER BY id DESC LIMIT 10", (uid, team))
        done = db.q("SELECT id FROM mx_missions WHERE user_id=? AND team=? AND status IN ('delivered','failed') ORDER BY id DESC LIMIT 2", (uid, team))
        rows = [mx._m(r["id"]) for r in live + done]
    teams = mx._teams(uid)
    reqs = db.q("SELECT id, mission_id, kind, label, action, hash, status, expires FROM mx_requests WHERE user_id=? AND status='pending' AND expires>?", (uid, time.time()))
    missions = []
    for m in rows:
        c = mx._card(m)
        missions.append({k: c[k] for k in ("id", "title", "status", "stage", "engine", "team", "doing", "spent", "budget", "outcome")} |
                        {"team_request": c.get("team_request"), "requests": sum(r["mission_id"] == m["id"] for r in reqs)})
    av = mx._engines(uid)
    from .missions import ENGINES  # noqa: PLC0415 - missions imports this module
    engines = [{"key": k, "label": l, "available": bool(av.get(k)), "missions": [x["id"] for x in missions if x["engine"] == k]} for k, l in ENGINES.items()]
    pre = [] if mission is not None else _predefined(db, uid, teams, team)
    want = {team} if team is not None else {x["team"] for x in missions if x["engine"] == "mining" and x["team"]}
    shown = [t for t in teams if t["id"] in want] if (team is not None or mission is not None) else \
        sorted(teams, key=lambda t: (t["id"] not in want, -t["id"]))[:MAP_TEAMS]
    tnodes = []
    for t in shown:
        w = db.q("SELECT * FROM mw_comps WHERE id=?", (t["id"],), one=True)
        if not w: continue
        node = _team_node(db, dict(w) | {"label": t["label"], "netuid": t["netuid"]}, deep=t["id"] in want or team is not None)
        node["missions"] = [x["id"] for x in missions if x["team"] == t["id"]]
        node["predefined"] = next((p["ref"] for p in pre if p["team"] == t["id"]), None)
        tnodes.append(node)
    # what's missing: a team a mission waits for
    wanted = [{"mission": x["id"], **x["team_request"]} for x in missions if x.get("team_request")]
    return {"you": {"name": me.get("username"), "requests": len(reqs), "needs": sum(x["status"] == "needs_input" for x in missions)},
            "missions": missions, "predefined": pre, "engines": engines, "teams": tnodes, "wanted": wanted, "team_count": len(teams),
            "focus": {"mission": mission, "team": team}}


def team_missions(mx, me, wid):
    """My subnets' team page: the missions that ran or run on this team."""
    if not mx.mw: raise HTTPException(404, "My subnets isn't on this server.")
    mx.mw._own(me, wid)
    rows = [mx._card(mx._m(r["id"])) for r in mx.db.q("SELECT id FROM mx_missions WHERE user_id=? AND team=? ORDER BY id DESC LIMIT 20", (me["id"], wid))]
    return {"missions": rows}
