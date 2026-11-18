"""Help: AXoR's documentation inside the app (the Help page, help.js).

The docs are Markdown files in data/help/. Each starts with `key: value` lines between `---` fences: title, section
(start, guide, admin, api or dev), order, audience (all, or admin for administrators only), icon and summary. They're
read again whenever a file changes, so editing one needs no restart.

The API reference is built from the app's own routes: methods, paths, parameters and body fields from FastAPI's
OpenAPI schema, the handler's docstring, and who may call it, read from the handler's source (sudo(req), admin(req),
require(req) / user(req)) or its dependencies. Administrators see every doc and endpoint; everyone else sees theirs.
"""
import inspect, re, threading
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.routing import APIRoute, APIWebSocketRoute

DOCS = Path(__file__).resolve().parent / "data/help"
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}$")
# id, title, line, icon, admins only
SECTIONS = [
    ("start", "Get started", "Your account, a tour of AXoR, and finding a subnet to mine.", "rocket", False),
    ("guide", "User guide", "Every page: what it shows and how to get the most from it.", "book", False),
    ("admin", "Administration", "Users and sign-in, models, the platform, integrations and running the server.", "shield", True),
    ("api", "API", "Sign in from code and call AXoR's REST API.", "code", False),
    ("dev", "Developers", "How AXoR is built, running it locally, and adding a feature.", "terminal", False),
]
# id, title, what it covers, the first path segments under /api/ it holds
GROUPS = [
    ("core", "Subnets and recommendations", "The live chain snapshot, hardware tiers and fields, the recommender, the update stream and the health check.",
     ("subnets", "meta", "recommend", "stream", "health")),
    ("auth", "Accounts and sign-in", "Register, sign in (password, then the authenticator code when asked), sign out, change your password, recovery codes and your synced settings.", ("auth",)),
    ("dashboard", "Dashboard, notifications and news", "The dashboard's figures, your notifications and their settings, and subnet news.", ("dashboard", "alerts", "news")),
    ("push", "Push notifications", "Your devices, push settings and history; for admins, the push server and announcements.", ("push",)),
    ("workspace", "Workspace", "Your subnets and their mining briefs, notes, files, workspace agents and chats, and the project team's PDCA cycles.", ("workspace",)),
    ("agents", "Agents", "The agent hub: built-in and custom agents, chats, skills, memory, models and usage, and approvals.", ("agents", "assist", "assistant")),
    ("study", "Study", "Tracks and progress, practice drills, flashcards, the study team's chats and the Lab.", ("study",)),
    ("boards", "Whiteboards", "Boards, sharing, the live channel and the board assistant.", ("boards",)),
    ("profile", "My profile", "Your profile, publishing, Netlify deploys and the AI review.", ("profile",)),
    ("wallet", "Wallets", "Tracked wallets, quotes, validators, transactions signed in your browser wallet, the btcli terminal and runbooks.", ("wallet",)),
    ("drive", "Drive", "Files and folders, sharing, share links, versions, search and the trash.", ("drive",)),
    ("source", "Source hub", "GitHub sources and repositories: code, commits, pull requests, Actions runs and deployments.", ("source",)),
    ("slack", "Slack", "The team's Slack channel, threads, posting and sharing.", ("slack",)),
    ("tech", "Tech Daily", "The day's edition of new technology, earlier editions, and rebuilding today's.", ("tech",)),
    ("help", "Help", "These docs and this reference.", ("help",)),
    ("admin", "User administration", "Accounts, roles, sign-up and sign-in settings, sudo and the audit log.", ("admin",)),
    ("connectors", "Keys", "Workforce → Keys: every model provider and outside service AXoR holds a key for, and OpenRouter keys.", ("connectors",)),
    ("system", "System", "This server's CPU, memory, disk and load.", ("system",)),
    ("docker", "Docker", "Containers and images through AXoR's restricted Docker proxy.", ("docker",)),
    ("devops", "DevOps", "Pipelines that build, test and deploy Source hub repositories, their runs and apps.", ("devops",)),
    ("cluster", "Cluster", "The Kubernetes node, AXoR's namespaces, deployments, pods and warnings.", ("cluster",)),
    ("platform", "Platform: apps and functions", "The domain and HTTPS, apps (PaaS) and functions (FaaS).", ("platform",)),
    ("machines", "Machines", "Linux and Windows virtual machines and their console.", ("machines",)),
    ("dns", "DNS", "AXoR DNS's zones and records, lookups and the delegation check.", ("dns",)),
    ("hq", "Agent HQ", "Field agents' issues and fixes, the hourly reports, the roster of every agent, and HQ's settings.", ("hq",)),
    ("mining", "My subnets", "Campaigns on a subnet: the competition, your miners, the team's briefs, recommendations, actions and alerts, agent runs and their traces, and the live stream; competition teams (/work): their agents, board, autopilot, notebook, files, sandbox runs and Import competitions (sources, URL/JSON/CSV imports, the review queue: /work/intake); the portfolio (/portfolio) and shared knowledge (/knowledge); the command center (/command): measurements and the evaluator's ingest, experiments, miners, rewards, approvals, monitoring and the agent directory.", ("mining",)),
    ("workforce", "Workforce", "Missions and their plans, work, blackboard, proposals, runs and traces; the org and its agents' versions; memory; scores; improvements; benchmarks; settings and the live stream.", ("workforce",)),
    ("company", "Company", "The AI agent company: divisions, projects and tasks, the team builder and team runs (messages, deliverables, evaluations), the agent registry and contracts, approval requests, decisions and the execution gateway, knowledge, the leadership brief and the audit log.", ("company",)),
    ("org", "Organization", "The hierarchy over the Company, Workforce and your agents: units, managers and reporting lines, the agent registry and profiles, missions and temporary assignments, Atlas's recommendations, delegation and escalation, authority levels, performance and approval requests.", ("org",)),
    ("learning", "Learning", "How agents get better from results: mission lessons (and forgetting one), Workforce and Workflow improvements, watches after a promotion, upgrade sprints.", ("learning",)),
    ("evolution", "Evolution Lab, Analytics and Governance", "AXoR 5.0: the Evolution Engine's benchmarks, proposals (and model drafts), experiments, recorded evidence, promotion, rollback, agent capability packages and policy; cost per validated deliverable and the Generation 5 scorecard; governance (policy, budgets, autonomy levels, waiting decisions, rollback points, audit).", ("evolution", "analytics", "governance")),
    ("infiagent", "Long tasks", "Long-horizon tasks on InfiAgent: tasks and runs, pause, resume and follow-ups, agents' thinking records and action windows, the trace, workspace files and the coverage audit.", ("infiagent",)),
    ("market", "Agent Marketplace", "Discovery across your library, Agent Cards and GitHub, packages (find, import, versions, restore), role tasks, evaluations, hash-bound approvals, activation, continuous re-evaluation and comparisons.", ("market",)),
    ("knowledge", "Knowledge Hub and My Knowledge", "Both spaces: folders, capture (notes, web pages, files), organize and derive, links and the graph, Ask, communications imports and the Slack sync, publishing; company records, review decisions bound to the content hash, AI review, outcomes and grants; retrieval & quality (RAG: passages, hybrid search, try as an agent, the evaluation center, the retrieval log); plus items, ideas, imports (preview, AI extraction, apply, undo), adopt proposals, search, export and the audit log.", ("knowledge",)),
    ("dev", "Developer", "Administrators' Developer page: the file explorer and editor (roots, list, read, write, move, upload, zip), terminals on the server (sessions and their WebSocket) and the Claude Code / Codex panel (runs, host sessions, history, usage, attachments).", ("dev",)),
    ("public", "Public pages", "Pages served without signing in: share links, published profiles and AXoR's root certificate.", ()),
]
# the checks, strictest first: called on the request (or passed with it, as the console's WebSocket does), or through a
# module's own wrapper around them (the Source hub's repo_of: admins to write, everyone signed in to read)
ACCESS = [("sudo", re.compile(r"\bsudo(\(|,\s*)(req|request|ws|websocket)\b")),
          ("admin", re.compile(r"\badmin\((req|request|ws|websocket)\b|\brepo_of\(req[^)]*write=True")),
          ("user", re.compile(r"\b(require|user|require_user)\((req|request|ws|websocket)\b|\brepo_of\(req"))]
STREAM = re.compile(r"StreamingResponse|text/event-stream|EventSourceResponse")
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")

class Library:
    """The Markdown docs, re-read when a file changes."""
    def __init__(self, folder=DOCS):
        self.folder, self.lock, self.key, self.docs = Path(folder), threading.Lock(), None, []

    def _read(self, path):
        raw = path.read_text("utf-8")
        meta, body = {}, raw
        m = re.match(r"^---\n(.*?)\n---\n", raw, re.S)
        if m:
            for line in m.group(1).splitlines():
                k, _, v = line.partition(":")
                if k.strip(): meta[k.strip().lower()] = v.strip()
            body = raw[m.end():]
        try: order = int(meta.get("order", 99))
        except ValueError: order = 99
        return {"slug": path.stem, "title": meta.get("title") or path.stem.replace("-", " ").capitalize(), "section": meta.get("section", "guide"),
                "order": order, "audience": "admin" if meta.get("audience") == "admin" else "all", "icon": meta.get("icon", "doc"),
                "summary": meta.get("summary", ""), "text": body.strip()}

    def all(self):
        files = sorted(p for p in self.folder.glob("*.md") if SLUG.match(p.stem)) if self.folder.is_dir() else []
        key = tuple((p.name, p.stat().st_mtime_ns) for p in files)
        with self.lock:
            if key != self.key:
                order = {s[0]: i for i, s in enumerate(SECTIONS)}
                self.docs = sorted((self._read(p) for p in files), key=lambda d: (order.get(d["section"], 99), d["order"], d["title"]))
                self.key = key
            return self.docs

    def index(self, admin):
        admin_sections = {s[0] for s in SECTIONS if s[4]}
        docs = [d for d in self.all() if admin or (d["audience"] == "all" and d["section"] not in admin_sections)]
        shown = {d["section"] for d in docs}
        return {"admin": admin, "docs": docs,
                "sections": [{"id": i, "title": t, "line": l, "icon": ic} for i, t, l, ic, only in SECTIONS if (admin or not only) and (i in shown or i == "api")]}

def access(route):
    """Who may call a route: public, user (signed in), admin, or sudo (an admin who confirmed it's them in the last 10 minutes)."""
    try: src = inspect.getsource(route.endpoint)
    except (OSError, TypeError): src = ""
    for name, rx in ACCESS:
        if rx.search(src): return name
    deps = getattr(getattr(route, "dependant", None), "dependencies", [])
    if any(getattr(d.call, "__name__", "") in ("user", "require_user", "require") for d in deps): return "user"
    return "public"

def _type(s, comps):
    if not isinstance(s, dict): return "any"
    if "$ref" in s: return s["$ref"].rsplit("/", 1)[-1]
    if "anyOf" in s or "oneOf" in s:
        parts = [_type(x, comps) for x in s.get("anyOf") or s.get("oneOf") if x.get("type") != "null"]
        return " or ".join(dict.fromkeys(parts)) or "null"
    if "enum" in s: return " | ".join(map(str, s["enum"]))
    if s.get("type") == "array": return f"array of {_type(s.get('items') or {}, comps)}"
    if s.get("type") == "object" and s.get("additionalProperties"): return "object"
    return s.get("type") or "any"

def _fields(schema, comps):
    """A request body's fields, one level deep (nested models are named by their type)."""
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        schema = comps.get(name, {})
    req = set(schema.get("required") or [])
    out = []
    for k, v in (schema.get("properties") or {}).items():
        f = {"name": k, "type": _type(v, comps), "required": k in req}
        for a in ("default", "maxLength", "minLength", "maximum", "minimum", "maxItems"):
            if a in v: f[a] = v[a]
        if v.get("description"): f["description"] = v["description"]
        out.append(f)
    return out

def _summary(fn):
    doc = inspect.getdoc(fn) or ""
    return " ".join(doc.split("\n\n")[0].split())

def reference(app):
    """Every route, grouped like the docs, with its access level, parameters and body."""
    spec = app.openapi()
    comps = (spec.get("components") or {}).get("schemas") or {}
    by_seg = {seg: g[0] for g in GROUPS for seg in g[3]}
    groups = {g[0]: {"id": g[0], "title": g[1], "blurb": g[2], "endpoints": []} for g in GROUPS}
    for route in app.routes:
        if isinstance(route, APIWebSocketRoute):
            methods, op = ["WS"], {}
        elif isinstance(route, APIRoute) and route.include_in_schema:
            methods = [m for m in METHODS if m in route.methods]
            op = None
        else:
            continue
        path = route.path
        if path == "/": continue  # the app's page itself
        parts = path.strip("/").split("/")
        gid = by_seg.get(parts[1] if parts[0] == "api" and len(parts) > 1 else "", "public" if parts[0] != "api" else None)
        if gid is None:
            gid = parts[1]
            groups.setdefault(gid, {"id": gid, "title": gid.replace("-", " ").capitalize(), "blurb": "", "endpoints": []})
        try: src = inspect.getsource(route.endpoint)
        except (OSError, TypeError): src = ""
        for m in methods:
            o = op if op is not None else ((spec.get("paths") or {}).get(path) or {}).get(m.lower()) or {}
            params = [{"name": p["name"], "in": p["in"], "required": bool(p.get("required")), "type": _type(p.get("schema") or {}, comps),
                       **({"default": p["schema"]["default"]} if "default" in (p.get("schema") or {}) else {})}
                      for p in o.get("parameters") or []]
            if m == "WS": params = [{"name": n, "in": "path", "required": True, "type": "string"} for n in re.findall(r"\{(\w+)", path)]
            body = None
            content = ((o.get("requestBody") or {}).get("content") or {})
            if "application/json" in content:
                sch = content["application/json"].get("schema") or {}
                body = {"type": _type(sch, comps), "fields": _fields(sch, comps), "required": bool((o.get("requestBody") or {}).get("required"))}
            groups[gid]["endpoints"].append({"method": m, "path": path, "access": access(route), "summary": _summary(route.endpoint),
                                             "params": params, "body": body, "stream": m == "WS" or bool(STREAM.search(src))})
    order = {g[0]: i for i, g in enumerate(GROUPS)}
    out = [g for g in groups.values() if g["endpoints"]]
    for g in out: g["endpoints"].sort(key=lambda e: (e["path"], METHODS.index(e["method"]) if e["method"] in METHODS else 9))
    return sorted(out, key=lambda g: (order.get(g["id"], 50), g["title"]))

def build(user, app):
    """`user(req)`: the signed-in user (None when sign-in is off); `app`: the FastAPI app, for the API reference."""
    r = APIRouter(prefix="/api/help")
    lib, cache = Library(), {}
    is_admin = lambda me: bool(me and me.get("role") == "admin")

    @r.get("")
    def docs(req: Request):
        """The docs you can read, with their sections."""
        return lib.index(is_admin(user(req)))

    @r.get("/api")
    def api_reference(req: Request):
        """The API reference: every endpoint you may call, grouped, with its access level, parameters and body."""
        admin = is_admin(user(req))
        if "all" not in cache: cache["all"] = reference(app)  # routes are fixed once the app has started
        if admin: return {"admin": True, "groups": cache["all"]}
        mine = [{**g, "endpoints": [e for e in g["endpoints"] if e["access"] in ("public", "user")]} for g in cache["all"]]
        return {"admin": False, "groups": [g for g in mine if g["endpoints"]]}

    r.state = {"library": lib}
    return r
