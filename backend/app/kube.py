"""Kubernetes: the cluster AXoR runs on, shown and managed on the Cluster page (admins only), and the API client the
platform (platform.py) uses.

AXoR talks to the API server as its own service account (axor/web) with the rights k8s/base/10-rbac.yaml gives it:
read its namespaces and kube-system, restart and scale deployments, recycle pods. In AXoR's own namespaces an
admission policy rejects anything beyond a restart or a scale, so even a compromised AXoR can't change what its
services run. Inside the cluster it finds the API server and its token itself; outside (tests, or AXoR still on
Docker Compose) set KUBE_API, KUBE_TOKEN or KUBE_TOKEN_FILE, and KUBE_CA_FILE.
Reads need an admin session; changes also need sudo and are audited. AXoR can restart itself but not stop itself,
and its own services (one database each) run one pod at most.
"""
import json, logging, os, re, ssl, time, urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

log = logging.getLogger("kube")
SA = Path("/var/run/secrets/kubernetes.io/serviceaccount")
SYSTEM = ("axor", "axor-edge", "axor-host")          # AXoR's own services: restart, and scale between 0 and 1
WORKLOADS = ("axor-apps", "axor-functions", "axor-machines")  # PaaS apps, functions and VMs (the Apps, Functions and Machines pages)
READ_ONLY = ("kube-system",)
NAMESPACES = SYSTEM + WORKLOADS + READ_ONLY
TITLES = {"axor": "AXoR", "axor-edge": "Edge & DNS", "axor-host": "Host access", "axor-apps": "Apps", "axor-functions": "Functions",
          "axor-machines": "Machines", "kube-system": "Kubernetes"}
SELF = ("axor", "web")
NAME = re.compile(r"^[a-z0-9]([-a-z0-9.]{0,251}[a-z0-9])?$")
SETUP = "AXoR isn't running on Kubernetes (no service account, and KUBE_API isn't set). See Kubernetes in the README."

class KubeError(Exception):
    def __init__(self, status, msg):
        super().__init__(msg); self.status = status

def ts(s):
    """An API timestamp (RFC 3339) as Unix time."""
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() if s else None

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def cpu(q):
    """A CPU quantity (2, 250m, 12345n) in cores."""
    if not q: return 0.0
    q = str(q)
    for suf, f in (("n", 1e-9), ("u", 1e-6), ("m", 1e-3)):
        if q.endswith(suf): return float(q[:-1]) * f
    return float(q)

def mem(q):
    """A memory quantity (512Mi, 1G, 1048576) in bytes."""
    if not q: return 0
    m = re.fullmatch(r"([0-9.]+)([KMGTPE]i?|k|m)?", str(q))
    if not m: return 0
    n, suf = float(m[1]), m[2] or ""
    if suf == "m": return int(n / 1000)
    p = "KMGTPE".index(suf[0].upper()) + 1 if suf else 0
    return int(n * (1024 if suf.endswith("i") else 1000) ** p)

class Kube:
    """A small client for the API server: JSON in and out, server-side apply, logs."""
    def __init__(self):
        host = os.getenv("KUBERNETES_SERVICE_HOST")
        self.url = (os.getenv("KUBE_API") or (f"https://{host}:{os.getenv('KUBERNETES_SERVICE_PORT', '443')}" if host else "")).rstrip("/")
        self.token_file = os.getenv("KUBE_TOKEN_FILE") or (str(SA / "token") if (SA / "token").exists() else "")
        ca = os.getenv("KUBE_CA_FILE") or (str(SA / "ca.crt") if (SA / "ca.crt").exists() else None)
        self.ctx = ssl.create_default_context(cafile=ca)
        self.namespace = (SA / "namespace").read_text().strip() if (SA / "namespace").exists() else "axor"
        self._token, self._read = os.getenv("KUBE_TOKEN"), 0.0

    @property
    def enabled(self): return bool(self.url)

    def token(self):
        if self.token_file and time.time() - self._read > 60:  # projected tokens rotate: read the file again now and then
            try: self._token, self._read = Path(self.token_file).read_text().strip(), time.time()
            except OSError: pass
        return self._token

    def call(self, method, path, params=None, body=None, ctype="application/json", timeout=30, raw=False):
        if not self.url: raise KubeError(503, SETUP)
        q = "?" + urllib.parse.urlencode(params, doseq=True) if params else ""
        h = {"Authorization": f"Bearer {self.token()}", "Accept": "application/json"}
        data = None
        if body is not None: data, h["Content-Type"] = json.dumps(body).encode(), ctype
        req = urllib.request.Request(self.url + path + q, data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=self.ctx) as r: out = r.read()
        except urllib.error.HTTPError as e:
            try: msg = json.load(e).get("message")
            except ValueError: msg = None
            if e.code == 401: self._read = 0  # a rotated token: read it again next time
            raise KubeError(e.code, msg or f"The Kubernetes API answered {e.code}.")
        except (urllib.error.URLError, OSError) as e:
            raise KubeError(502, f"Can't reach the Kubernetes API at {self.url} ({getattr(e, 'reason', e)}).")
        if raw: return out
        return json.loads(out) if out.strip() else None

    def get(self, path, params=None):
        """GET, or None when it doesn't exist."""
        try: return self.call("GET", path, params)
        except KubeError as e:
            if e.status == 404: return None
            raise

    def items(self, path, params=None):
        try: return (self.call("GET", path, params) or {}).get("items", [])
        except KubeError as e:
            if e.status in (403, 404): return []  # a namespace that isn't there (yet), or one AXoR may not read
            raise

    def apply(self, path, obj):
        """Server-side apply: the object as AXoR wants it; fields other managers set are left alone."""
        return self.call("PATCH", f"{path}/{obj['metadata']['name']}", {"fieldManager": "axor", "force": "true"}, obj,
                         ctype="application/apply-patch+yaml")

    def patch(self, path, body, kind="strategic"):
        ctype = {"strategic": "application/strategic-merge-patch+json", "merge": "application/merge-patch+json"}[kind]
        return self.call("PATCH", path, body=body, ctype=ctype)

    def delete(self, path, params=None):
        try: return self.call("DELETE", path, params)
        except KubeError as e:
            if e.status != 404: raise

    def logs(self, ns, pod, container=None, tail=300, previous=False, timestamps=True):
        p = {"tailLines": max(1, min(int(tail), 5000)), "timestamps": str(timestamps).lower()}
        if container: p["container"] = container
        if previous: p["previous"] = "true"
        return self.call("GET", f"/api/v1/namespaces/{ns}/pods/{pod}/log", p, timeout=20, raw=True).decode("utf-8", "replace")

    # ---------- shapes the pages use ----------
    def metrics(self, ns):
        """{pod: (cores, bytes)} from metrics-server, or {} without it."""
        try: items = self.items(f"/apis/metrics.k8s.io/v1beta1/namespaces/{ns}/pods")
        except KubeError: return {}
        return {m["metadata"]["name"]: (sum(cpu(c["usage"].get("cpu")) for c in m["containers"]),
                                        sum(mem(c["usage"].get("memory")) for c in m["containers"])) for m in items}

def pod_out(p, usage=None):
    st, spec = p.get("status") or {}, p["spec"]
    cs = st.get("containerStatuses") or []
    labels = p["metadata"].get("labels") or {}
    owner = next((o for o in p["metadata"].get("ownerReferences") or [] if o.get("controller")), None)
    deploy = owner["name"][: -len(labels["pod-template-hash"]) - 1] if owner and owner["kind"] == "ReplicaSet" and labels.get("pod-template-hash") else None
    problem = None
    for c in (st.get("initContainerStatuses") or []) + cs:
        w = (c.get("state") or {}).get("waiting") or {}
        if w.get("reason") and w["reason"] not in ("ContainerCreating", "PodInitializing"):
            problem = f"{w['reason']}: {w.get('message', '')}".strip(": ")[:300]; break
        t = (c.get("lastState") or {}).get("terminated") or {}
        if t.get("reason") in ("OOMKilled", "Error") and c.get("restartCount"):
            problem = problem or f"Last exit: {t['reason']} (code {t.get('exitCode')})"
    if not problem and st.get("phase") == "Pending":
        cond = next((c for c in st.get("conditions") or [] if c["type"] == "PodScheduled" and c["status"] == "False"), None)
        if cond: problem = f"{cond.get('reason')}: {cond.get('message', '')}"[:300]
    u = (usage or {}).get(p["metadata"]["name"])
    return {"name": p["metadata"]["name"], "namespace": p["metadata"]["namespace"], "phase": st.get("phase"),
            "deleting": bool(p["metadata"].get("deletionTimestamp")),
            "ready": sum(1 for c in cs if c.get("ready")), "containers": [c["name"] for c in spec["containers"]],
            "restarts": sum(c.get("restartCount", 0) for c in cs), "node": spec.get("nodeName"), "ip": st.get("podIP"),
            "created": ts(p["metadata"].get("creationTimestamp")), "deployment": deploy, "problem": problem,
            "cpu": round(u[0], 3) if u else None, "memory": u[1] if u else None}

def deploy_out(d):
    spec, st, tpl = d["spec"], d.get("status") or {}, d["spec"]["template"]
    conds = {c["type"]: c for c in st.get("conditions") or []}
    prog = conds.get("Progressing") or {}
    failed = prog.get("reason") == "ProgressDeadlineExceeded"
    return {"name": d["metadata"]["name"], "namespace": d["metadata"]["namespace"], "replicas": spec.get("replicas", 1),
            "ready": st.get("readyReplicas", 0), "updated": st.get("updatedReplicas", 0), "available": st.get("availableReplicas", 0),
            "rolling": st.get("observedGeneration", 0) < d["metadata"].get("generation", 0) or st.get("updatedReplicas", 0) < spec.get("replicas", 1)
                       or st.get("replicas", 0) > spec.get("replicas", 1),
            "failed": failed, "message": prog.get("message") if failed else (conds.get("Available") or {}).get("message"),
            "images": [c["image"] for c in tpl["spec"]["containers"]], "strategy": (spec.get("strategy") or {}).get("type"),
            "created": ts(d["metadata"].get("creationTimestamp")),
            "restarted": ts((tpl["metadata"].get("annotations") or {}).get("kubectl.kubernetes.io/restartedAt")),
            "labels": d["metadata"].get("labels") or {}}

def event_out(e):
    o = e.get("involvedObject") or e.get("regarding") or {}
    last = e.get("lastTimestamp") or e.get("eventTime") or (e.get("metadata") or {}).get("creationTimestamp")
    return {"type": e.get("type"), "reason": e.get("reason"), "message": (e.get("message") or e.get("note") or "")[:500],
            "kind": o.get("kind"), "name": o.get("name"), "namespace": o.get("namespace"), "count": e.get("count") or 1,
            "time": ts(last)}

class Cluster:
    def __init__(self, db, kube=None):
        self.db, self.k = db, kube or Kube()

    def _ns(self, ns, write=False):
        if ns not in NAMESPACES: raise HTTPException(404, "AXoR doesn't manage that namespace.")
        if write and ns in READ_ONLY: raise HTTPException(400, "Kubernetes' own services are shown read-only.")
        return ns

    def overview(self):
        k = self.k
        def ns_view(ns):
            usage = k.metrics(ns)
            return ns, {"deployments": [deploy_out(d) for d in k.items(f"/apis/apps/v1/namespaces/{ns}/deployments")],
                        "pods": [pod_out(p, usage) for p in k.items(f"/api/v1/namespaces/{ns}/pods")],
                        "events": [event_out(e) for e in k.items(f"/api/v1/namespaces/{ns}/events") if e.get("type") == "Warning"]}
        with ThreadPoolExecutor(8) as pool:
            nodes_f = pool.submit(k.call, "GET", "/api/v1/nodes")
            nmet_f = pool.submit(lambda: {m["metadata"]["name"]: m["usage"] for m in k.items("/apis/metrics.k8s.io/v1beta1/nodes")})
            spaces = dict(pool.map(ns_view, NAMESPACES))
            nodes, nmet = nodes_f.result()["items"], nmet_f.result()
        pods = [p for s in spaces.values() for p in s["pods"]]
        out_nodes = []
        for n in nodes:
            st, alloc, info = n["status"], n["status"].get("allocatable") or {}, n["status"].get("nodeInfo") or {}
            ready = next((c["status"] == "True" for c in st.get("conditions") or [] if c["type"] == "Ready"), False)
            pressure = [c["type"] for c in st.get("conditions") or [] if c["type"] != "Ready" and c["status"] == "True"]
            u = nmet.get(n["metadata"]["name"]) or {}
            out_nodes.append({"name": n["metadata"]["name"], "ready": ready, "pressure": pressure,
                              "roles": sorted(l.split("/", 1)[1] for l in n["metadata"].get("labels", {}) if l.startswith("node-role.kubernetes.io/")),
                              "version": info.get("kubeletVersion"), "os": info.get("osImage"), "kernel": info.get("kernelVersion"),
                              "runtime": info.get("containerRuntimeVersion"),
                              "address": next((a["address"] for a in st.get("addresses") or [] if a["type"] in ("ExternalIP", "InternalIP")), None),
                              "cpu": cpu(alloc.get("cpu")), "memory": mem(alloc.get("memory")), "pods_max": int(alloc.get("pods") or 0),
                              "cpu_used": round(cpu(u.get("cpu")), 2) if u else None, "memory_used": mem(u.get("memory")) if u else None,
                              "created": ts(n["metadata"].get("creationTimestamp"))})
        events = sorted((e for s in spaces.values() for e in s["events"]), key=lambda e: e["time"] or 0, reverse=True)[:60]
        return {"nodes": out_nodes, "pods_total": len(pods), "api": self.k.url,
                "namespaces": [{"name": ns, "title": TITLES[ns], "read_only": ns in READ_ONLY, "system": ns in SYSTEM,
                                "deployments": spaces[ns]["deployments"], "pods": spaces[ns]["pods"]} for ns in NAMESPACES],
                "events": events, "self": {"namespace": SELF[0], "deployment": SELF[1]}}

    def deployment(self, ns, name):
        self._ns(ns)
        d = self.k.get(f"/apis/apps/v1/namespaces/{ns}/deployments/{name}")
        if not d: raise HTTPException(404, "There's no such deployment.")
        sel = ",".join(f"{a}={b}" for a, b in d["spec"]["selector"].get("matchLabels", {}).items())
        rss = self.k.items(f"/apis/apps/v1/namespaces/{ns}/replicasets", {"labelSelector": sel})
        usage = self.k.metrics(ns)
        pods = [pod_out(p, usage) for p in self.k.items(f"/api/v1/namespaces/{ns}/pods", {"labelSelector": sel})]
        names = {name} | {r["metadata"]["name"] for r in rss} | {p["name"] for p in pods}
        events = sorted((event_out(e) for e in self.k.items(f"/api/v1/namespaces/{ns}/events") if (e.get("involvedObject") or {}).get("name") in names),
                        key=lambda e: e["time"] or 0, reverse=True)[:40]
        c = d["spec"]["template"]["spec"]["containers"][0]
        history = sorted(({"revision": int((r["metadata"].get("annotations") or {}).get("deployment.kubernetes.io/revision", 0)),
                           "images": [x["image"] for x in r["spec"]["template"]["spec"]["containers"]],
                           "replicas": r["spec"].get("replicas", 0), "ready": (r.get("status") or {}).get("readyReplicas", 0),
                           "created": ts(r["metadata"].get("creationTimestamp"))} for r in rss), key=lambda r: -r["revision"])
        return {**deploy_out(d), "pods": pods, "events": events, "history": history,
                "container": {"ports": [p.get("containerPort") for p in c.get("ports") or []], "resources": c.get("resources") or {},
                              "env": sorted({e["name"] for e in c.get("env") or []}),
                              "env_from": [x.get("secretRef", x.get("configMapRef", {})).get("name") for x in c.get("envFrom") or []]}}

    # ---------- changes (caller must have verified admin + sudo) ----------
    def restart(self, me, ns, name, ip):
        self._ns(ns, write=True)
        self.k.patch(f"/apis/apps/v1/namespaces/{ns}/deployments/{name}",
                     {"spec": {"template": {"metadata": {"annotations": {"kubectl.kubernetes.io/restartedAt": now_iso()}}}}})
        self.db.log("cluster.restart", me["username"], f"{ns}/{name}", ip, "")
        return {"ok": True}

    def scale(self, me, ns, name, replicas, ip):
        self._ns(ns, write=True)
        if (ns, name) == SELF and replicas < 1: raise HTTPException(400, "That's AXoR itself: it can't stop itself from here.")
        if ns in SYSTEM and replicas > 1:
            raise HTTPException(400, "AXoR's own services run one pod each (each has its own database, or holds a host port).")
        if ns == "axor-machines" and replicas > 1:
            raise HTTPException(400, "A machine runs one pod: two virtual machines on one disk would wreck it.")
        self.k.patch(f"/apis/apps/v1/namespaces/{ns}/deployments/{name}/scale", {"spec": {"replicas": replicas}}, kind="merge")
        self.db.log("cluster.scale", me["username"], f"{ns}/{name}", ip, f"replicas={replicas}")
        return {"ok": True}

    def delete_pod(self, me, ns, pod, ip):
        self._ns(ns, write=True)
        if not NAME.match(pod): raise HTTPException(400, "Unknown pod.")
        self.k.delete(f"/api/v1/namespaces/{ns}/pods/{pod}")
        self.db.log("cluster.recycle", me["username"], f"{ns}/{pod}", ip, "")
        return {"ok": True}

    def pod_logs(self, ns, pod, container, tail, previous):
        self._ns(ns)
        if not NAME.match(pod) or (container and not NAME.match(container)): raise HTTPException(400, "Unknown pod.")
        try: return {"name": pod, "text": self.k.logs(ns, pod, container or None, tail, previous)[-400_000:]}
        except KubeError as e:
            if e.status == 400 and previous: return {"name": pod, "text": "No earlier run: this container hasn't restarted."}
            raise

class Act(BaseModel):
    action: str
    replicas: int | None = Field(None, ge=0, le=20)

def build(db, helpers, ip, kube=None):
    r = APIRouter(prefix="/api/cluster")
    admin, sudo = helpers["admin"], helpers["sudo"]
    c = Cluster(db, kube)
    r.state = {"cluster": c, "kube": c.k}

    def call(fn, *a):
        try: return fn(*a)
        except KubeError as e: raise HTTPException(e.status if e.status in (400, 403, 404, 409, 422, 503) else 502, str(e))

    @r.get("")
    def overview(req: Request):
        admin(req)
        return call(c.overview)

    @r.get("/deployments/{ns}/{name}")
    def deployment(ns: str, name: str, req: Request):
        admin(req)
        return call(c.deployment, ns, name)

    @r.post("/deployments/{ns}/{name}")
    def act(ns: str, name: str, a: Act, req: Request):
        me = sudo(req)
        if a.action == "restart": return call(c.restart, me, ns, name, ip(req))
        if a.action == "scale" and a.replicas is not None: return call(c.scale, me, ns, name, a.replicas, ip(req))
        raise HTTPException(400, "Unknown action.")

    @r.delete("/pods/{ns}/{pod}")
    def recycle(ns: str, pod: str, req: Request):
        return call(c.delete_pod, sudo(req), ns, pod, ip(req))

    @r.get("/pods/{ns}/{pod}/logs")
    def logs(ns: str, pod: str, req: Request, container: str = "", tail: int = 300, previous: bool = False):
        admin(req)
        return call(c.pod_logs, ns, pod, container, tail, previous)

    return r
