"""Unified control panel (topology.js, /api/topology, view #topology): AXoR as one typed graph with seven synchronized projections.

One graph, not seven diagrams: every node has one id wherever it appears, so a sandbox is the same node in the agent execution
graph (the run that used it), the infrastructure topology (the sandbox namespace) and the network topology (the egress proxy and
the hosts it reached). The page shows one projection, several, or all of them at once (the unified view), and moves between three
levels (global: the company; operational: agents, tasks, runs, pods, hosts; deep: tool calls, mission stages, containers, events).

Layers and where each comes from (read-only: nothing here calls a model or changes a row):
- org: Organization → Departments → Teams → Agents, the Control Hub's own tree (control_hub.tree).
- mission: missions (predefined: a Competition team's ctl_fixed record, ref comp:<id>; custom: mx_missions, ref mx:<id>), their
  stages, Control Hub tasks (ctl_tasks: mission, parent_id, unit, agent, the board task or mission it was sent to) and the
  Competition teams' board tasks (mw_tasks).
- exec: the run ledger (agent_core's ac_runs): agent → run → model → provider; a team run's spans (mw_spans: tool and model calls),
  MCP tool calls (mcp_calls) and sandbox runs (mw_sbx).
- infra: the Kubernetes cluster (kube.Cluster.overview: nodes, namespaces, deployments, pods, containers; administrators only, and
  only when AXoR runs on Kubernetes) and the sandbox namespace with each sandbox run in it (everyone, for their own teams).
- net: sandbox → egress proxy → hosts reached (or refused) → internet, from each internet run's record (mw_sbx.net); model and
  MCP providers as the external APIs agents reach.
- knowledge: sources → knowledge items → who used them (kb_uses: agents, Mission Control, you), and items' links.
- obs: failures and alerts attached to the component they are about: failed runs, subnet alerts, team and mission events that
  report errors, Kubernetes warning events.

Every element carries its time (t0, and t1 when it ended), so the page can replay the window (time travel) without asking again,
and edges carry `dep` (which end depends on the other) for dependency analysis: "fwd" = the source depends on the target, "rev" =
the target depends on the source, "" = no dependency (an alert is about something, it doesn't run on it). The organization's
containment is "fwd" (a team's work depends on its agents); infrastructure's is "rev" (a pod depends on its namespace and cluster,
not the other way round), except a deployment, which is its pods.
"""
import json, re, threading, time

from fastapi import APIRouter, HTTPException, Request

from . import agent_core

LAYERS = {"org": "Organization", "mission": "Missions & workflow", "exec": "Agent execution", "infra": "Infrastructure",
          "net": "Network", "knowledge": "Knowledge & lineage", "obs": "Observability"}
LEVELS = {"global": 0, "operational": 1, "deep": 2}
CACHE_S = 8
KUBE_CACHE_S = 20
MAX = {"runs": 300, "ctl_tasks": 150, "mw_tasks": 200, "mx": 40, "sbx": 120, "spans": 500, "kb_items": 120, "kb_src": 30,
       "alerts": 40, "events": 80, "pods": 200}
MX_STAGES = ("understand", "discover", "plan", "allocate", "execute", "verify", "deliver", "learn")
RUN_ST = {"running": "busy", "done": "ok", "ok": "ok", "failed": "fail", "lost": "fail", "error": "fail", "timeout": "fail", "cancelled": "off"}
TASK_ST = {"proposed": "idle", "todo": "idle", "queued": "busy", "working": "busy", "running": "busy", "checking": "busy", "review": "warn",
           "needs_input": "warn", "done": "ok", "failed": "fail", "error": "fail", "cancelled": "off", "skipped": "off"}
MX_ST = {"running": "busy", "active": "busy", "planning": "busy", "paused": "warn", "waiting": "warn", "done": "ok", "delivered": "ok",
         "failed": "fail", "cancelled": "off", "draft": "idle"}
ORG_ST = {"ok": "ok", "busy": "busy", "warn": "warn", "stop": "fail", "idle": "idle", "off": "off"}
RUNNING = ("run", "sandbox", "span", "pod", "task", "stage")  # what "running" counts: work in progress, not the units it sits in
BAD_EVENT = re.compile(r"error|fail|block|refus|budget|quota|timeout|stuck|alert|crash|lost", re.I)


def _j(s, d=None):
    if not s: return d
    try: return json.loads(s)
    except (TypeError, ValueError): return d


def _clip(s, n):
    s = str(s or "").strip()
    return s if len(s) <= n else s[:n - 1] + "…"


def _provider(model):
    """'anthropic:claude-x' → 'anthropic'; a bare model name → a guess from its name."""
    m = str(model or "")
    if ":" in m: return m.split(":", 1)[0]
    for k, p in (("claude", "anthropic"), ("gpt", "openai"), ("o1", "openai"), ("o3", "openai"), ("o4", "openai"), ("gemini", "google"),
                 ("llama", "meta"), ("qwen", "qwen"), ("deepseek", "deepseek"), ("mistral", "mistral")):
        if m.lower().startswith(k): return p
    return "provider"


class G:
    """The graph being built: nodes merge their layers; edges are keyed by (source, target, kind) and count repeats."""

    def __init__(self):
        self.n, self.e = {}, {}

    def node(self, nid, typ, layer, label, lv=1, status=None, **kw):
        x = self.n.get(nid)
        if x is None:
            x = self.n[nid] = {"id": nid, "type": typ, "layers": [layer], "label": _clip(label, 80), "lv": lv, "status": status or "ok", **kw}
        else:
            if layer not in x["layers"]: x["layers"].append(layer)
            x["lv"] = min(x["lv"], lv)
            for k, v in kw.items():
                if v is not None and x.get(k) in (None, "", 0): x[k] = v
            if status and x.get("status") in ("ok", "idle", None) and status in ("busy", "warn", "fail"): x["status"] = status
        return x

    def has(self, nid): return nid in self.n

    def edge(self, s, t, kind, layer, dep="fwd", lv=None, **kw):
        if s not in self.n or t not in self.n or s == t: return None
        eid = f"{s}>{t}>{kind}"
        x = self.e.get(eid)
        if x is None:
            lvl = lv if lv is not None else max(self.n[s]["lv"], self.n[t]["lv"])
            x = self.e[eid] = {"id": eid, "source": s, "target": t, "kind": kind, "layer": layer, "dep": dep, "lv": lvl, "n": 0, **kw}
        x["n"] += kw.get("count", 1) if "count" in kw else 1
        for k in ("t0",):
            if kw.get(k) and (not x.get(k) or kw[k] < x[k]): x[k] = kw[k]
        if kw.get("status") == "fail": x["status"] = "fail"
        return x

    def metric(self, nid, **kw):
        x = self.n.get(nid)
        if not x: return
        m = x.setdefault("m", {})
        for k, v in kw.items():
            if v: m[k] = round(m.get(k, 0) + v, 4) if isinstance(v, float) else m.get(k, 0) + v


class Topology:
    def __init__(self, db, control=None, cluster=None, hub=None):
        self.db, self.ch, self.cluster, self.hub = db, control, cluster, hub
        self.lock, self._cache, self._kube = threading.Lock(), {}, (0, None, None)

    def _has(self, t): return bool(self.db.q("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,), one=True))

    def _cols(self, t): return {c["name"] for c in self.db.q(f"PRAGMA table_info({t})")}

    # ---------- the graph ----------
    def graph(self, me, hours=24, deep=False):
        hours = max(1, min(int(hours or 24), 168))
        key = (me["id"], hours, bool(deep), me.get("role") == "admin")
        hit = self._cache.get(key)
        if hit and time.time() - hit[0] < CACHE_S: return hit[1]
        out = self._build(me, hours, deep)
        self._cache[key] = (time.time(), out)
        if len(self._cache) > 64: self._cache = dict(list(self._cache.items())[-32:])
        return out

    def _build(self, me, hours, deep):
        now = time.time()
        since, g, avail = now - hours * 3600, G(), {k: {"ok": True, "why": ""} for k in LAYERS}
        ctx = {"me": me, "uid": me["id"], "since": since, "now": now, "deep": deep, "teams": {}, "agents": set(), "admin": me.get("role") == "admin"}
        for name, fn in (("org", self._org), ("mission", self._missions), ("exec", self._exec), ("infra", self._infra),
                         ("net", self._net), ("knowledge", self._knowledge), ("obs", self._obs)):
            try:
                why = fn(g, ctx)
                if why: avail[name] = {"ok": False, "why": why}
            except HTTPException as e:
                avail[name] = {"ok": False, "why": str(e.detail)}
            except Exception as e:  # noqa: BLE001 - one source failing leaves the other projections standing
                avail[name] = {"ok": False, "why": f"Couldn't read this layer: {_clip(e, 200)}"}
        counts = {k: sum(1 for x in g.n.values() if k in x["layers"]) for k in LAYERS}
        shared = sum(1 for x in g.n.values() if len(x["layers"]) > 1)
        return {"at": now, "since": since, "hours": hours, "deep": deep,
                "layers": [{"key": k, "label": v, "count": counts[k], **avail[k]} for k, v in LAYERS.items()],
                "nodes": list(g.n.values()), "edges": list(g.e.values()),
                "stats": {"nodes": len(g.n), "edges": len(g.e), "shared": shared,
                          "running": sum(1 for x in g.n.values() if x["status"] == "busy" and x["type"] in RUNNING),  # work, not a busy team
                          "failing": sum(1 for x in g.n.values() if x["status"] == "fail")}}

    # ---------- 1. organization ----------
    def _org(self, g, c):
        if not self.ch: return "The Control Hub is off on this server."
        try: t = self.ch.tree(c["me"])
        except HTTPException as e: return str(e.detail)
        L = "org"
        root = g.node("org", "org", L, t["org"]["name"] or "Organization", 0, "ok", sub=f"Owner: {t['org'].get('owner') or 'you'}", link="#control")

        def agent(a, parent, rel="member"):
            nid = f"agent:{a['key']}"
            g.node(nid, "agent", L, a["name"], 1, ORG_ST.get(a.get("status"), "ok"), sub=a.get("title") or "", system=a.get("system"),
                   key=a["key"], link=f"#control/agent:{a['key']}")
            c["agents"].add(a["key"])
            g.edge(parent, nid, rel, L, "fwd")

        def team(tm, parent):
            g.node(tm["id"], "team", L, tm["name"], 0, ORG_ST.get(tm.get("status"), "ok"),
                   sub=("Competition team" if tm.get("kind") == "competition" else "Team") + (f" · SN{tm['subnet']}" if tm.get("subnet") is not None else ""),
                   link=f"#control/{tm['id']}", open_tasks=tm.get("open_tasks") or 0)
            g.edge(parent, tm["id"], "contains", L, "fwd")
            if tm.get("comp_id"): c["teams"][tm["comp_id"]] = tm["id"]
            for a in tm.get("agents") or []: agent(a, tm["id"])

        if t["org"].get("ceo"): agent(t["org"]["ceo"], "org", "leads")
        bt = t.get("bittensor")
        if bt:
            bid = f"u:{bt['unit_id']}" if bt.get("unit_id") else "bittensor"
            g.node(bid, "division", L, bt["name"], 0, "ok", sub="Primary initiative", link=f"#control/{bid}" if bt.get("unit_id") else "#control")
            g.edge("org", bid, "contains", L, "fwd")
            for d in bt.get("departments") or []:
                g.node(d["id"], "department", L, d["name"], 0, ORG_ST.get(d.get("status"), "ok"), sub=f"Subnet {d['netuid']}", link=f"#control/{d['id']}",
                       netuid=d["netuid"])
                g.edge(bid, d["id"], "contains", L, "fwd")
                for tm in d.get("teams") or []: team(tm, d["id"])
            for tm in bt.get("teams") or []: team(tm, bid)
            for a in bt.get("staff") or []: agent(a, bid)
        for d in t.get("departments") or []:
            g.node(d["id"], "department" if d["kind"] != "division" else "division", L, d["name"], 0, ORG_ST.get(d.get("status"), "ok"),
                   sub={"exec": "Executive staff", "division": "Division"}.get(d["kind"], "Department"), link=f"#control/{d['id']}")
            g.edge("org", d["id"], "contains", L, "fwd")
            for tm in d.get("teams") or []: team(tm, d["id"])
            for a in d.get("staff") or []: agent(a, d["id"])
        for a in t.get("unplaced") or []: agent(a, "org", "unplaced")
        root["m"] = {"agents": t["org"]["counts"]["agents"], "working": t["org"]["counts"]["working"], "pending": t["org"].get("pending") or 0}

    # ---------- 2. missions and workflow ----------
    def _missions(self, g, c):
        uid, since, L = c["uid"], c["since"], "mission"
        if self._has("ctl_fixed"):
            for f in self.db.q("SELECT comp_id, netuid, target_rank, objectives, deadline, created FROM ctl_fixed WHERE user_id=?", (uid,)):
                tid = c["teams"].get(f["comp_id"])
                mid = f"mission:comp:{f['comp_id']}"
                g.node(mid, "mission", L, f"Top {f['target_rank'] or '?'} miner on SN{f['netuid']}", 0, g.n[tid]["status"] if tid and g.has(tid) else "idle",
                       sub="Predefined mission (Bittensor)", t0=f["created"], link=f"#control/{tid}" if tid else "#control", ref=f"comp:{f['comp_id']}")
                if tid: g.edge(mid, tid, "staffed_by", L, "fwd")
        if self._has("mx_missions"):
            for m in self.db.q(f"""SELECT id, title, goal, status, stage, team, budget, spent, own_tokens, child_tokens, created, finished FROM mx_missions
                                   WHERE user_id=? AND (status NOT IN ('done','failed','cancelled') OR updated>=?) ORDER BY id DESC LIMIT {MAX['mx']}""", (uid, since)):
                mid = f"mission:mx:{m['id']}"
                st = MX_ST.get(m["status"], "busy" if m["status"] not in ("done",) else "ok")
                g.node(mid, "mission", L, m["title"] or _clip(m["goal"], 60), 0, st, sub=f"Custom mission · {m['stage'] or m['status']}", t0=m["created"],
                       t1=m["finished"], link="#mos", ref=f"mx:{m['id']}")
                g.metric(mid, tokens=(m["own_tokens"] or 0) + (m["child_tokens"] or 0), cost=float(m["spent"] or 0))
                if m["team"] and c["teams"].get(m["team"]): g.edge(mid, c["teams"][m["team"]], "staffed_by", L, "fwd")
                if c["deep"]:
                    cur = MX_STAGES.index(m["stage"]) if m["stage"] in MX_STAGES else -1
                    prev = None
                    for i, s in enumerate(MX_STAGES):
                        sid = f"stage:mx:{m['id']}:{s}"
                        sst = ("ok" if i < cur or m["status"] == "done" else ("fail" if m["status"] == "failed" else st) if i == cur else "idle")
                        g.node(sid, "stage", L, s.capitalize(), 2, sst, sub=f"Stage {i + 1} of {len(MX_STAGES)}", t0=m["created"])
                        g.edge(mid, sid, "stage", L, "fwd", 2)
                        if prev: g.edge(prev, sid, "then", L, "rev", 2)
                        prev = sid
        if self._has("ctl_mission_teams"):
            for r in self.db.q("SELECT mission, unit_id, duty FROM ctl_mission_teams WHERE user_id=?", (uid,)):
                g.edge(f"mission:{r['mission']}", f"u:{r['unit_id']}", "supported_by", L, "fwd", duty=_clip(r["duty"], 80))
        if self._has("ctl_tasks"):
            cols = self._cols("ctl_tasks")
            extra = ", mission, parent_id, kind" if "parent_id" in cols else ""
            rows = self.db.q(f"""SELECT id, unit_id, agent_key, title, route, ref, status, tokens, created, updated{extra} FROM ctl_tasks WHERE user_id=?
                                 AND (status IN ('proposed','todo','running','review','needs_input') OR updated>=?) ORDER BY id DESC LIMIT {MAX['ctl_tasks']}""", (uid, since))
            for r in rows:
                nid = f"task:ctl:{r['id']}"
                g.node(nid, "task", L, r["title"], 1, TASK_ST.get(r["status"], "idle"), sub=f"{(r.get('kind') or 'dynamic').capitalize()} task · {r['status']}",
                       t0=r["created"], t1=r["updated"] if r["status"] in ("done", "failed", "cancelled") else None, link="#control", ref=f"ctl:t{r['id']}")
                g.metric(nid, tokens=r["tokens"] or 0)
            for r in rows:
                nid = f"task:ctl:{r['id']}"
                if r.get("mission") and g.has(f"mission:{r['mission']}"): g.edge(f"mission:{r['mission']}", nid, "has_task", L, "fwd")
                if r.get("parent_id"): g.edge(f"task:ctl:{r['parent_id']}", nid, "subtask", L, "fwd")
                if r["unit_id"] and not r.get("mission"): g.edge(f"u:{r['unit_id']}", nid, "owns_task", L, "fwd")
                if r["agent_key"]: g.edge(nid, f"agent:{r['agent_key']}", "assigned", L, "fwd")
                m = re.fullmatch(r"mx:(\d+)", r["ref"] or "")
                if m: g.edge(nid, f"mission:mx:{m.group(1)}", "sent_to", L, "fwd")
        if self._has("mw_tasks") and c["teams"]:
            ids = list(c["teams"])
            marks = ",".join("?" * len(ids))
            for r in self.db.q(f"""SELECT id, comp_id, title, status, agent_id, priority, created, updated, done_at FROM mw_tasks WHERE comp_id IN ({marks})
                                   AND (status NOT IN ('done','cancelled') OR updated>=?) ORDER BY id DESC LIMIT {MAX['mw_tasks']}""", (*ids, since)):
                nid = f"task:mw:{r['id']}"
                g.node(nid, "task", L, r["title"], 1, TASK_ST.get(r["status"], "idle"), sub=f"Board task · {r['status']} · {r['priority'] or 'medium'}",
                       t0=r["created"], t1=r["done_at"], link="#teams")
                parent = f"mission:comp:{r['comp_id']}" if g.has(f"mission:comp:{r['comp_id']}") else c["teams"][r["comp_id"]]
                g.edge(parent, nid, "has_task", L, "fwd")
                if r["agent_id"]: g.edge(nid, f"agent:teams:{r['agent_id']}", "assigned", L, "fwd")
            for r in self.db.q(f"SELECT id, ref FROM ctl_tasks WHERE user_id=? AND ref LIKE 'mw:%'", (uid,)) if self._has("ctl_tasks") else []:
                g.edge(f"task:ctl:{r['id']}", f"task:mw:{r['ref'][3:]}", "sent_to", L, "fwd")

    # ---------- 3. agent execution ----------
    def _exec(self, g, c):
        core = agent_core.get()
        if not core: return "The run ledger (agent core) is off on this server."
        uid, since, L, deep = c["uid"], c["since"], "exec", c["deep"]
        names = {r["key"]: r for r in self.db.q("SELECT key, system, name, role FROM ac_agents WHERE owner_id=?", (uid,))}
        runs = core.runs((uid,), since, limit=MAX["runs"])
        mw_run = {}   # mw_runs.id → run node id
        for r in runs:
            nid = f"run:{r['id']}"
            st = RUN_ST.get(r["status"], "ok")
            g.node(nid, "run", L, r["title"] or r["kind"] or "Run", 1, st, sub=f"{r['system']} · {r['kind'] or 'run'} · {r['status']}",
                   t0=r["started"], t1=r["finished"], error=_clip(r["error"], 300) if r["error"] else None, score=r.get("score"))
            g.metric(nid, tokens=r["tokens"] or 0, cost=float(r["cost"] or 0))
            ak = r["agent_key"]
            if ak:
                aid = f"agent:{ak}"
                a = names.get(ak) or {}
                g.node(aid, "agent", L, a.get("name") or ak, 1, None, sub=a.get("role") or r["system"], system=r["system"], key=ak, link=f"#control/agent:{ak}")
                g.metric(aid, runs=1, tokens=r["tokens"] or 0, failures=1 if st == "fail" else 0)
                if st == "busy": g.n[aid]["status"] = "busy"
                g.edge(aid, nid, "ran", L, "rev", t0=r["started"])
            if r["model"]:
                md = f"model:{r['model']}"
                g.node(md, "model", L, r["model"].split(":", 1)[-1], 1, "ok", sub=f"Model · {_provider(r['model'])}")
                g.edge(nid, md, "called", L, "fwd", t0=r["started"], status="fail" if st == "fail" else None)
                g.metric(md, calls=1, tokens=r["tokens"] or 0)
                api = f"api:{_provider(r['model'])}"
                g.node(api, "api", L, _provider(r["model"]).capitalize() + " API", 1, "ok", sub="Model provider")
                g.node(api, "api", "net", _provider(r["model"]).capitalize() + " API", 1)
                g.edge(md, api, "served_by", L, "fwd")
            ref = r["ref"] or ""
            m = re.fullmatch(r"mw:(\d+)", ref)
            if m: mw_run[int(m.group(1))] = nid
            m2 = re.fullmatch(r"ctl:t(\d+)", ref)
            if m2: g.edge(f"task:ctl:{m2.group(1)}", nid, "executed_as", "mission", "fwd")
            m3 = re.fullmatch(r"mx:(\d+)", ref)
            if m3: g.edge(f"mission:mx:{m3.group(1)}", nid, "executed_as", "mission", "fwd")
        c["mw_run"] = mw_run
        if mw_run and self._has("mw_runs"):
            ids = list(mw_run)
            marks = ",".join("?" * len(ids))
            for r in self.db.q(f"SELECT id, task_id FROM mw_runs WHERE id IN ({marks})", ids):
                if r["task_id"]: g.edge(f"task:mw:{r['task_id']}", mw_run[r["id"]], "executed_as", "mission", "fwd")
            if self._has("mw_spans"):
                for s in self.db.q(f"""SELECT run_id, kind, name, COUNT(*) n, SUM(error) bad, MIN(ts) t0, SUM(tokens) tok FROM mw_spans WHERE run_id IN ({marks})
                                      GROUP BY run_id, kind, name""", ids):
                    if s["kind"] != "tool": continue
                    tid = self._tool(g, s["name"])
                    g.edge(mw_run[s["run_id"]], tid, "invoked", L, "fwd", count=s["n"], t0=s["t0"], status="fail" if s["bad"] else None, errors=s["bad"] or 0)
                    g.metric(tid, calls=s["n"], failures=s["bad"] or 0)
                if deep:
                    latest = sorted(ids, reverse=True)[:25]
                    lm = ",".join("?" * len(latest))
                    for s in self.db.q(f"""SELECT id, run_id, ts, end, kind, name, input, output, tokens, error FROM mw_spans WHERE run_id IN ({lm})
                                          ORDER BY id DESC LIMIT {MAX['spans']}""", latest):
                        sid = f"span:{s['id']}"
                        g.node(sid, "span", L, f"{s['kind']}: {s['name']}", 2, "fail" if s["error"] else "ok", sub=_clip(s["input"], 140),
                               t0=s["ts"], t1=s["end"], output=_clip(s["output"], 300), tokens=s["tokens"] or 0)
                        g.edge(mw_run[s["run_id"]], sid, "span", L, "fwd", 2)
                        target = self._tool(g, s["name"]) if s["kind"] == "tool" else None
                        if target: g.edge(sid, target, "calls", L, "fwd", 2)
        if self._has("mcp_calls"):
            srv = {r["id"]: r for r in self.db.q("SELECT id, name, slug FROM mcp_servers")} if self._has("mcp_servers") else {}
            for r in self.db.q("""SELECT scope, server_id, tool, COUNT(*) n, SUM(1-ok) bad, MIN(ts) t0, AVG(ms) ms FROM mcp_calls WHERE user_id=? AND ts>=?
                                  GROUP BY scope, server_id, tool""", (uid, since)):
                s = srv.get(r["server_id"]) or {"name": f"MCP server {r['server_id']}", "slug": str(r["server_id"])}
                api = f"api:mcp:{s['slug']}"
                g.node(api, "api", L, s["name"], 1, "ok", sub="MCP server")
                g.node(api, "api", "net", s["name"], 1)
                tid = self._tool(g, f"ext_{s['slug']}__{r['tool']}")
                g.edge(tid, api, "served_by", L, "fwd")
                kind, _, ident = (r["scope"] or "").partition(":")
                who = c["teams"].get(int(ident)) if kind == "team" and ident.isdigit() else f"agent:hub:{ident}" if kind == "hub" else None
                if who and g.has(who): g.edge(who, tid, "invoked", L, "fwd", count=r["n"], t0=r["t0"], status="fail" if r["bad"] else None, errors=r["bad"] or 0)
                g.metric(tid, calls=r["n"], failures=r["bad"] or 0)
        self._sandboxes(g, c)

    def _tool(self, g, name):
        tid = f"tool:{name}"
        m = re.fullmatch(r"ext_([a-z0-9_-]+?)__(.+)", name or "")
        g.node(tid, "tool", "exec", m.group(2) if m else name, 1, "ok", sub=f"External tool · {m.group(1)}" if m else "Internal tool")
        if m and g.has(f"api:mcp:{m.group(1)}"): g.edge(tid, f"api:mcp:{m.group(1)}", "served_by", "exec", "fwd")
        return tid

    def _sandboxes(self, g, c):
        """Sandbox runs: one node in three layers (the run that used it, the sandbox namespace, the network it reached)."""
        if not (self._has("mw_sbx") and c["teams"]): return
        ids = list(c["teams"])
        marks = ",".join("?" * len(ids))
        g.node("k8s:cluster", "cluster", "infra", "Kubernetes cluster", 0, "ok", sub="Where AXoR and its sandboxes run", link="#cluster" if c["admin"] else None)
        g.node("k8s:ns:axor-sandbox", "namespace", "infra", "axor-sandbox", 0, "ok", sub="Sandbox namespace (gVisor)")
        g.edge("k8s:cluster", "k8s:ns:axor-sandbox", "contains", "infra", "rev")
        have = self._cols("mw_sbx")   # the Agent Execution Fabric's columns (exec_env.py, D-032) exist once a planned run has been made
        aef = "".join(f", {k}" if k in have else f", NULL AS {k}" for k in ("stats", "manifest", "ws_from", "ws_to"))
        rows = self.db.q(f"""SELECT id, comp_id, task_id, run_id, agent_id, command, status, exit_code, error, started, finished, cost, calls, pod, net{aef}
                             FROM mw_sbx WHERE comp_id IN ({marks}) AND (started>=? OR status='running') ORDER BY id DESC LIMIT {MAX['sbx']}""", (*ids, c["since"]))
        c["sbx"] = rows
        for r in rows:
            sid = f"sbx:{r['id']}"
            st = "busy" if r["status"] == "running" else "ok" if r["status"] in ("ok", "done", "success", "passed") or r["exit_code"] == 0 else "fail"
            g.node(sid, "sandbox", "exec", r["pod"] or f"sandbox #{r['id']}", 1, st, sub=_clip(r["command"], 120), t0=r["started"], t1=r["finished"],
                   pod=r["pod"], exit=r["exit_code"], error=_clip(r["error"], 300) if r["error"] else None, internet=bool(r["net"]), link="#teams")
            g.node(sid, "sandbox", "infra", r["pod"] or f"sandbox #{r['id']}", 1)
            g.metric(sid, cost=float(r["cost"] or 0), calls=r["calls"] or 0)
            stats, man = _j(r["stats"], {}) or {}, _j(r["manifest"], {}) or {}
            if stats.get("live") and not man:  # a planned run that is still going: what it has used so far (its own report, every few seconds)
                g.metric(sid, cpu_s=float(stats.get("cpu_seconds") or 0), mem_mb=float(stats.get("peak_rss_mb") or 0), procs=int(stats.get("peak_procs") or 0))
                g.n[sid].update(run=r["id"], live=True, live_at=stats.get("at"))
            if man:  # a planned run: what it used (its own report), its size and policy, the workspace snapshots it started from and left
                res, pl = man.get("result") or {}, man.get("plan") or {}
                g.metric(sid, cpu_s=float(stats.get("cpu_seconds") or 0), mem_mb=float(stats.get("peak_rss_mb") or 0), procs=int(stats.get("peak_procs") or 0),
                         disk_mb=float((stats.get("disk_mb") or {}).get("work") or 0), events=len(res.get("events") or []))
                x = g.n[sid]
                x.update(run=r["id"], size=pl.get("size"), mission=pl.get("mission"), egress=(pl.get("egress") or {}).get("mode"),
                         ws=f"#{r['ws_from'] or 0} → #{r['ws_to']}" if r["ws_to"] else (f"#{r['ws_from']} (unchanged)" if r["ws_from"] else None))
                if any(e.get("kind") in ("refused_save", "secret_refused", "conflict") for e in res.get("events") or []) and x.get("status") == "ok": x["status"] = "warn"
            g.edge("k8s:ns:axor-sandbox", sid, "contains", "infra", "rev")
            run = (c.get("mw_run") or {}).get(r["run_id"])
            if run: g.edge(run, sid, "sandboxed", "exec", "fwd", t0=r["started"])
            elif r["agent_id"] and g.has(f"agent:teams:{r['agent_id']}"): g.edge(f"agent:teams:{r['agent_id']}", sid, "sandboxed", "exec", "fwd", t0=r["started"])
            elif r["task_id"] and g.has(f"task:mw:{r['task_id']}"): g.edge(f"task:mw:{r['task_id']}", sid, "sandboxed", "exec", "fwd", t0=r["started"])
            else: g.edge(c["teams"][r["comp_id"]], sid, "sandboxed", "exec", "fwd", t0=r["started"])

    # ---------- 4. infrastructure ----------
    def _overview(self):
        t, ov, err = self._kube
        if time.time() - t < KUBE_CACHE_S: return ov, err
        ov, err = None, None
        try:
            if not self.cluster or not self.cluster.k.enabled: err = "AXoR isn't running on Kubernetes here, so only the sandbox namespace is shown."
            else: ov = self.cluster.overview()
        except Exception as e:  # noqa: BLE001 - KubeError, network: the layer says why
            err = f"The Kubernetes API didn't answer: {_clip(e, 200)}"
        self._kube = (time.time(), ov, err)
        return ov, err

    def _infra(self, g, c):
        L, deep = "infra", c["deep"]
        g.node("k8s:cluster", "cluster", L, "Kubernetes cluster", 0, "ok", sub="Where AXoR and its sandboxes run", link="#cluster" if c["admin"] else None)
        if not c["admin"]: return "Nodes, namespaces and pods are for administrators; you see the sandbox namespace and your teams' sandboxes."
        ov, err = self._overview()
        if err: return err
        bad = False
        for n in ov["nodes"]:
            nid = f"k8s:node:{n['name']}"
            st = "fail" if not n["ready"] else "warn" if n["pressure"] else "ok"
            bad |= st != "ok"
            g.node(nid, "k8s-node", L, n["name"], 0, st, sub=f"Node · {', '.join(n['roles']) or 'worker'} · {n.get('version') or ''}", link="#cluster",
                   cpu=n["cpu"], cpu_used=n["cpu_used"], memory=n["memory"], memory_used=n["memory_used"])
            g.edge("k8s:cluster", nid, "contains", L, "rev")
        for ns in ov["namespaces"]:
            nsid = f"k8s:ns:{ns['name']}"
            g.node(nsid, "namespace", L, ns["name"], 0, "ok", sub=ns["title"], link="#cluster")
            g.edge("k8s:cluster", nsid, "contains", L, "rev")
            for d in ns["deployments"]:
                did = f"k8s:dep:{ns['name']}/{d['name']}"
                st = "fail" if d["failed"] or (d["replicas"] and not d["ready"]) else "busy" if d["rolling"] else "ok" if d["replicas"] else "off"
                g.node(did, "deployment", L, d["name"], 1, st, sub=f"Deployment · {d['ready']}/{d['replicas']} ready", link="#cluster",
                       images=d["images"][:3], message=_clip(d.get("message"), 200) if d.get("message") else None)
                g.edge(nsid, did, "contains", L, "rev")
            for p in ns["pods"][:MAX["pods"]]:
                pid = f"k8s:pod:{ns['name']}/{p['name']}"
                st = "fail" if p["problem"] else "busy" if p["phase"] == "Pending" or p["deleting"] else "ok" if p["phase"] in ("Running", "Succeeded") else "warn"
                g.node(pid, "pod", L, p["name"], 1, st, sub=f"Pod · {p['phase']} · {p['ready']}/{len(p['containers'])} ready · {p['restarts']} restarts",
                       t0=p["created"], problem=p["problem"], cpu_used=p["cpu"], memory_used=p["memory"], ip=p["ip"], link="#cluster")
                parent = f"k8s:dep:{ns['name']}/{p['deployment']}" if p.get("deployment") and g.has(f"k8s:dep:{ns['name']}/{p['deployment']}") else nsid
                g.edge(parent, pid, "contains", L, "rev" if parent == nsid else "fwd")  # a deployment is its pods
                if p["node"]: g.edge(pid, f"k8s:node:{p['node']}", "runs_on", L, "fwd")
                if deep:
                    for cn in p["containers"]:
                        cid = f"k8s:ctr:{ns['name']}/{p['name']}/{cn}"
                        g.node(cid, "container", L, cn, 2, st if st == "fail" else "ok", sub="Container")
                        g.edge(pid, cid, "contains", L, "fwd", 2)
        # cross-layer: the organization's agents run inside AXoR's own web deployment
        if g.has("k8s:dep:axor/web") and g.has("org"): g.edge("org", "k8s:dep:axor/web", "runs_on", L, "fwd")
        c["kube_events"] = ov.get("events") or []

    # ---------- 5. network ----------
    def _net(self, g, c):
        L = "net"
        apis = [x for x in g.n.values() if x["type"] == "api"]
        rows = [r for r in c.get("sbx") or [] if r["net"]]
        if not apis and not rows: return "No external calls in this window: no model or MCP calls, and no sandbox run with internet."
        g.node("net:internet", "internet", L, "Internet", 0, "ok", sub="Public addresses only")
        for a in apis: g.edge(a["id"], "net:internet", "over", L, "fwd")
        if g.has("org"):
            g.node("org", "org", L, g.n["org"]["label"], 0)
            for a in apis: g.edge("org", a["id"], "reaches", L, "fwd")
        if not rows: return None
        g.node("net:egress", "gateway", L, "Egress proxy", 0, "ok", sub="The sandboxes' only way out: ports 80/443, public addresses, per-run caps")
        g.node("net:egress", "gateway", "infra", "Egress proxy", 0)
        g.edge("k8s:cluster", "net:egress", "contains", "infra", "rev")
        g.edge("net:egress", "net:internet", "over", L, "fwd")
        for r in rows:
            sid, rec = f"sbx:{r['id']}", _j(r["net"], {}) or {}
            g.node(sid, "sandbox", L, r["pod"] or f"sandbox #{r['id']}", 1)
            e = g.edge(sid, "net:egress", "via", L, "fwd", t0=r["started"])
            if e: e.update(up=rec.get("up_bytes") or 0, down=rec.get("down_bytes") or 0)
            g.metric(sid, up=rec.get("up_bytes") or 0, down=rec.get("down_bytes") or 0, conns=rec.get("connections") or 0)
            for host, h in list((rec.get("hosts") or {}).items())[:40]:
                hid = f"host:{host}"
                g.node(hid, "host", L, host, 1, "ok", sub="Host reached through the egress proxy")
                g.edge(sid, hid, "reached", L, "fwd", t0=r["started"], up=h.get("up") or 0, down=h.get("down") or 0, conns=h.get("conns") or 0)
                g.edge("net:egress", hid, "routes", L, "")
                g.edge(hid, "net:internet", "on", L, "fwd")
                g.metric(hid, up=h.get("up") or 0, down=h.get("down") or 0, conns=h.get("conns") or 0)
            for f in (rec.get("refused") or [])[:20]:
                hid = f"host:{f.get('host') or '?'}"
                g.node(hid, "host", L, f.get("host") or "?", 1, "fail", sub="Refused by the egress proxy")
                g.edge(sid, hid, "blocked", L, "", t0=f.get("at") or r["started"], status="fail", why=_clip(f.get("why"), 160))
                g.n[hid]["why"] = _clip(f.get("why"), 160)

    # ---------- 6. knowledge and data lineage ----------
    def _knowledge(self, g, c):
        if not self._has("kb_items"): return "The Knowledge Hub is off on this server."
        uid, since, L = c["uid"], c["since"], "knowledge"
        uses = self.db.q("""SELECT item_id, actor, label, COUNT(*) n, MIN(ts) t0, SUM(CASE WHEN useful=0 THEN 1 ELSE 0 END) bad FROM kb_uses
                            WHERE user_id=? AND ts>=? GROUP BY item_id, actor""", (uid, since)) if self._has("kb_uses") else []
        used_ids = {u["item_id"] for u in uses}
        recent = self.db.q(f"SELECT id FROM kb_items WHERE user_id=? AND status='kept' AND (created>=? OR updated>=?) ORDER BY id DESC LIMIT {MAX['kb_items']}",
                           (uid, since, since))
        ids = list(dict.fromkeys(list(used_ids) + [r["id"] for r in recent]))[:MAX["kb_items"]]
        if not ids: return "No knowledge was added or used in this window."
        marks = ",".join("?" * len(ids))
        items = self.db.q(f"SELECT id, source_id, type, title, trust, used, origin_ref, created, updated FROM kb_items WHERE user_id=? AND id IN ({marks})", (uid, *ids))
        srcs = {s["id"]: s for s in self.db.q(f"""SELECT id, kind, name, platform, status, created FROM kb_sources WHERE user_id=? AND id IN
                                                 (SELECT DISTINCT source_id FROM kb_items WHERE id IN ({marks}))""", (uid, *ids))} if self._has("kb_sources") else {}
        for s in list(srcs.values())[:MAX["kb_src"]]:
            g.node(f"kb:src:{s['id']}", "source", L, s["name"] or s["kind"], 0, "ok", sub=f"Source · {s['platform'] or s['kind']}", t0=s["created"], link="#knowledge")
        for k in items:
            nid = f"kb:{k['id']}"
            g.node(nid, "knowledge", L, k["title"], 1, "ok", sub=f"{(k['type'] or 'item').capitalize()} · trust {k['trust'] or '?'} · used {k['used'] or 0}×",
                   t0=k["created"], link="#knowledge")
            if k["source_id"] and g.has(f"kb:src:{k['source_id']}"): g.edge(f"kb:src:{k['source_id']}", nid, "produced", L, "rev")
            m = re.fullmatch(r"(mx|mw|ctl:t|comp):?(\d+)", k["origin_ref"] or "")
            if m:
                origin = {"mx": f"mission:mx:{m.group(2)}", "mw": f"task:mw:{m.group(2)}", "ctl:t": f"task:ctl:{m.group(2)}", "comp": f"mission:comp:{m.group(2)}"}[m.group(1)]
                g.edge(origin, nid, "produced", L, "rev")
        for u in uses:
            nid = f"kb:{u['item_id']}"
            if not g.has(nid): continue
            actor = u["actor"] or "agent"
            if actor in c["agents"] or g.has(f"agent:{actor}"): who = f"agent:{actor}"
            elif actor == "you": who = "person:you"; g.node(who, "person", L, "You", 1, "ok", sub="Asked My Knowledge")
            elif actor == "missions": who = "consumer:missions"; g.node(who, "consumer", L, "Mission Control", 1, "ok", sub="Reads knowledge before planning", link="#mos")
            else: who = f"consumer:{actor}"; g.node(who, "consumer", L, u["label"] or actor, 1, "ok", sub="Reads knowledge")
            g.node(who, g.n[who]["type"], L, g.n[who]["label"], g.n[who]["lv"])
            g.edge(nid, who, "used_by", L, "rev", count=u["n"], t0=u["t0"], status="fail" if u["bad"] else None)
        if self._has("kb_links"):
            for l in self.db.q(f"SELECT item_id, ref, rel FROM kb_links WHERE user_id=? AND item_id IN ({marks})", (uid, *ids)):
                if (l["ref"] or "").startswith("kb:") and g.has(l["ref"]): g.edge(f"kb:{l['item_id']}", l["ref"], l["rel"] or "related", L, "")

    # ---------- 7. observability ----------
    def _obs(self, g, c):
        L, since, uid = "obs", c["since"], c["uid"]
        for x in list(g.n.values()):  # what failed or is failing is part of the observability projection, with what it hangs from
            if x["status"] == "fail" and x["type"] in ("run", "agent", "pod", "deployment", "k8s-node", "sandbox", "task", "mission", "team", "host", "span"):
                x["layers"].append(L) if L not in x["layers"] else None
        nets = {x["netuid"]: x["id"] for x in g.n.values() if x.get("netuid") is not None}
        if self._has("alerts") and nets:
            marks = ",".join("?" * len(nets))
            for a in self.db.q(f"SELECT id, ts, kind, netuid, title, body, level FROM alerts WHERE ts>=? AND netuid IN ({marks}) ORDER BY id DESC LIMIT {MAX['alerts']}",
                               (since, *nets)):
                aid = f"alert:{a['id']}"
                lvl = (a["level"] or "").lower()
                g.node(aid, "alert", L, a["title"] or a["kind"], 1, "fail" if lvl in ("critical", "crit", "high") else "warn", sub=f"Alert · {a['kind']}",
                       t0=a["ts"], body=_clip(a["body"], 300), link="#notifications")
                g.edge(aid, nets[a["netuid"]], "about", L, "")
                g.n[nets[a["netuid"]]]["layers"].append(L) if L not in g.n[nets[a["netuid"]]]["layers"] else None
        if self._has("mw_events") and c["teams"]:
            ids = list(c["teams"])
            marks = ",".join("?" * len(ids))
            rows = [e for e in self.db.q(f"""SELECT id, comp_id, ts, agent_id, task_id, kind, text FROM mw_events WHERE comp_id IN ({marks}) AND ts>=?
                                             ORDER BY id DESC LIMIT 600""", (*ids, since)) if BAD_EVENT.search(f"{e['kind']} {e['text']}")][:MAX["events"]]
            for e in rows:
                eid = f"evt:mw:{e['id']}"
                g.node(eid, "event", L, _clip(e["text"], 70), 2 if not c["deep"] else 1, "warn", sub=f"Team event · {e['kind']}", t0=e["ts"], body=_clip(e["text"], 400))
                about = (f"task:mw:{e['task_id']}" if e["task_id"] and g.has(f"task:mw:{e['task_id']}") else
                         f"agent:teams:{e['agent_id']}" if e["agent_id"] and g.has(f"agent:teams:{e['agent_id']}") else c["teams"][e["comp_id"]])
                g.edge(eid, about, "about", L, "")
        if self._has("mx_events"):
            mids = [int(x["id"].split(":")[2]) for x in g.n.values() if x["id"].startswith("mission:mx:")]
            if mids:
                marks = ",".join("?" * len(mids))
                for e in self.db.q(f"SELECT id, mission_id, ts, stage, kind, text FROM mx_events WHERE mission_id IN ({marks}) AND ts>=? ORDER BY id DESC LIMIT 400",
                                   (*mids, since)):
                    if not BAD_EVENT.search(f"{e['kind']} {e['text']}"): continue
                    eid = f"evt:mx:{e['id']}"
                    g.node(eid, "event", L, _clip(e["text"], 70), 2, "warn", sub=f"Mission event · {e['stage'] or ''} {e['kind']}", t0=e["ts"], body=_clip(e["text"], 400))
                    st = f"stage:mx:{e['mission_id']}:{e['stage']}"
                    g.edge(eid, st if g.has(st) else f"mission:mx:{e['mission_id']}", "about", L, "")
        for i, e in enumerate(c.get("kube_events") or []):
            if not e.get("name"): continue
            ns, kind = e.get("namespace"), (e.get("kind") or "").lower()
            target = f"k8s:pod:{ns}/{e['name']}" if kind == "pod" else f"k8s:dep:{ns}/{e['name']}" if kind == "deployment" else f"k8s:node:{e['name']}" if kind == "node" else None
            if not target or not g.has(target): continue
            eid = f"evt:k8s:{i}"
            g.node(eid, "event", L, f"{e['reason']}: {_clip(e['message'], 60)}", 1, "warn", sub=f"Kubernetes warning ×{e['count']}", t0=e.get("time"), body=_clip(e["message"], 400))
            g.edge(eid, target, "about", L, "")
            g.n[target]["layers"].append(L) if L not in g.n[target]["layers"] else None
        # what a failure sits in comes along (a failed run's agent, a failing pod's deployment, a failed task's mission), so the
        # projection shows where it happened, not a loose dot
        CONTEXT = ("agent", "team", "deployment", "namespace", "mission", "run", "sandbox", "department")
        for e in list(g.e.values()):
            s, t = g.n[e["source"]], g.n[e["target"]]
            if t["status"] == "fail" and L in t["layers"] and L not in s["layers"] and s["type"] in CONTEXT and e["dep"] != "": s["layers"].append(L)
            if s["status"] == "fail" and L in s["layers"] and L not in t["layers"] and t["type"] in CONTEXT and e["dep"] == "rev": t["layers"].append(L)
        if not any(L in x["layers"] for x in g.n.values()): return None


def build(db, require, control=None, cluster=None, hub=None):
    r = APIRouter(prefix="/api/topology")
    t = Topology(db, control, cluster, hub)
    r.state = {"topology": t}
    gate = hub.gate if hub and hasattr(hub, "gate") else (lambda me: me)

    @r.get("")
    def graph(req: Request, hours: int = 24, level: str = "operational"):
        me = gate(require(req))
        if level not in LEVELS: raise HTTPException(400, "level is global, operational or deep.")
        return t.graph(me, hours, deep=level == "deep")

    return r
