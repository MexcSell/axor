"""Machines: Linux and Windows virtual machines on AXoR's Kubernetes platform (the Machines page, admins only).

A machine is a KVM virtual machine: QEMU in a container, one pod in axor-machines (k8s/base/55-machines.yaml).
- Linux runs on qemux/qemu. It downloads the distribution's installer or live image at first start, and you install it
  from the console as on a new PC. Arch Linux comes ready-made, and any other ISO or disk image can be given by URL.
- Windows runs on dockurr/windows. It downloads Windows from Microsoft and installs it unattended, with the account,
  password and language set here. The editions are unactivated or evaluation ones: activate them with your own licence.
The disk is a volume (<name>-disk) that outlives restarts and edits; deleting the machine deletes it. The pod gets
/dev/kvm from the KVM device plugin (resource axor.dev/kvm) and nothing else from the host: no privileges, no extra
capabilities, no API token. The VM's network is user-mode (passt), so it reaches what the pod may reach: the internet,
but not AXoR, this host or private ranges. Its CPU and memory limits sit a little above the VM's own.
The console: the page's VNC client (noVNC, frontend/vendor/novnc) speaks to AXoR over a WebSocket, and AXoR relays it
to QEMU's VNC port through the machine's Service. Only AXoR can reach that port (the namespace's network policy), so
opening the console takes an admin session with sudo, like every change here, and it is audited.
"""
import asyncio, base64, json, logging, re, time
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException, Request, WebSocket
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from .kube import KubeError, deploy_out, event_out, mem, pod_out, ts

log = logging.getLogger("machines")
NS, LABEL = "axor-machines", "axor.dev/machine"
KVM = "axor.dev/kvm"  # the device plugin's resource: one per running machine
IMAGES = {"linux": "qemux/qemu:7.50", "windows": "dockurr/windows:6.06"}
VNC = 5900
EXTRA_GB = 16  # room on the volume for the installer image next to the disk
NAME = re.compile(r"^[a-z]([a-z0-9-]{0,28}[a-z0-9])?$")
URL = re.compile(r"^https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?/[A-Za-z0-9._~/%+=&?:@,-]{1,480}$")
WIN_USER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,18}[A-Za-z0-9_-]$|^[A-Za-z0-9]$")
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
# id: the image's BOOT (Linux) or VERSION (Windows), the least memory it installs with, suggested memory and disk (GB)
OS = {
    "ubuntu": {"family": "linux", "title": "Ubuntu Desktop", "boot": "ubuntu", "min_ram": 2, "ram": 4, "disk": 32},
    "ubuntus": {"family": "linux", "title": "Ubuntu Server", "boot": "ubuntus", "min_ram": 2, "ram": 2, "disk": 20},
    "debian": {"family": "linux", "title": "Debian", "boot": "debian", "min_ram": 1, "ram": 2, "disk": 20},
    "fedora": {"family": "linux", "title": "Fedora Workstation", "boot": "fedora", "min_ram": 2, "ram": 4, "disk": 32},
    "centos": {"family": "linux", "title": "CentOS Stream", "boot": "centos", "min_ram": 2, "ram": 4, "disk": 32},
    "rocky": {"family": "linux", "title": "Rocky Linux", "boot": "rocky", "min_ram": 2, "ram": 4, "disk": 32},
    "alma": {"family": "linux", "title": "AlmaLinux", "boot": "alma", "min_ram": 2, "ram": 4, "disk": 32},
    "opensuse": {"family": "linux", "title": "openSUSE Leap", "boot": "opensuse", "min_ram": 2, "ram": 4, "disk": 32},
    "arch": {"family": "linux", "title": "Arch Linux", "boot": "arch", "min_ram": 1, "ram": 2, "disk": 20,
             "note": "Ready-made: sign in as arch, password arch."},
    "alpine": {"family": "linux", "title": "Alpine Linux", "boot": "alpine", "min_ram": 1, "ram": 1, "disk": 8},
    "kali": {"family": "linux", "title": "Kali Linux", "boot": "kali", "min_ram": 2, "ram": 4, "disk": 32},
    "mint": {"family": "linux", "title": "Linux Mint", "boot": "mint", "min_ram": 2, "ram": 4, "disk": 32},
    "manjaro": {"family": "linux", "title": "Manjaro", "boot": "manjaro", "min_ram": 2, "ram": 4, "disk": 32},
    "nixos": {"family": "linux", "title": "NixOS", "boot": "nixos", "min_ram": 2, "ram": 4, "disk": 32},
    "custom": {"family": "linux", "title": "Another Linux (an ISO or disk image URL)", "boot": None, "min_ram": 1, "ram": 2, "disk": 32},
    "win11": {"family": "windows", "title": "Windows 11 Pro", "version": "11", "min_ram": 4, "ram": 8, "disk": 64},
    "win11ltsc": {"family": "windows", "title": "Windows 11 LTSC", "version": "11l", "min_ram": 4, "ram": 8, "disk": 64},
    "win10": {"family": "windows", "title": "Windows 10 Pro", "version": "10", "min_ram": 2, "ram": 4, "disk": 64},
    "win2025": {"family": "windows", "title": "Windows Server 2025", "version": "2025", "min_ram": 4, "ram": 8, "disk": 64},
    "win2022": {"family": "windows", "title": "Windows Server 2022", "version": "2022", "min_ram": 2, "ram": 4, "disk": 64},
    "win2019": {"family": "windows", "title": "Windows Server 2019", "version": "2019", "min_ram": 2, "ram": 4, "disk": 64},
}
LANGUAGES = {"en": "English (United States)", "gb": "English (United Kingdom)", "zh": "Chinese (Simplified)", "tw": "Chinese (Traditional)",
             "ja": "Japanese", "ko": "Korean", "de": "German", "fr": "French", "es": "Spanish", "br": "Portuguese (Brazil)",
             "it": "Italian", "nl": "Dutch", "pl": "Polish", "ru": "Russian", "tr": "Turkish", "ar": "Arabic"}
CAP_DROP = ["NET_RAW", "MKNOD", "AUDIT_WRITE", "SETFCAP"]  # as for apps: QEMU, passt and nginx need none of them

def _b64(s): return base64.b64encode(s.encode()).decode()

class MachineIn(BaseModel):
    name: str = Field(..., max_length=30)
    os: str = Field(..., max_length=20)
    url: str = Field("", max_length=500)  # the image of "custom"
    cores: int = Field(2, ge=1, le=16)
    ram: int = Field(4, ge=1, le=64)  # GB
    disk: int = Field(32, ge=8, le=500)  # GB, set when it's made
    username: str = Field("", max_length=20)  # Windows, when it's made: the account its setup makes
    password: str | None = Field(None, max_length=127)  # Windows, when it's made: that account's password
    language: str = Field("en", max_length=5)  # Windows, when it's made

class Act(BaseModel):
    action: str

class Machines:
    def __init__(self, db, kube):
        self.db, self.k = db, kube

    def _ready(self):
        if not self.k.enabled: raise HTTPException(503, "AXoR isn't running on Kubernetes, so machines aren't available. See k8s/ in the README.")

    def _get(self, name):
        if not NAME.match(name or ""): raise HTTPException(404, "There's no such machine.")
        d = self.k.get(f"/apis/apps/v1/namespaces/{NS}/deployments/{name}")
        if not d or LABEL not in (d["metadata"].get("labels") or {}): raise HTTPException(404, f"There's no machine called {name}.")
        return d

    @staticmethod
    def _settings(d):
        return json.loads((d["metadata"].get("annotations") or {}).get("axor.dev/settings", "{}"))

    def kvm(self):
        """How many machines this server's KVM can run at once (the device plugin's count), or 0 without the plugin."""
        try: nodes = self.k.call("GET", "/api/v1/nodes")["items"]
        except KubeError: return None
        return sum(int((n["status"].get("allocatable") or {}).get(KVM, 0) or 0) for n in nodes)

    @staticmethod
    def _status(d, pods):
        o = deploy_out(d)
        live = [p for p in pods if not p["deleting"]]
        if o["replicas"] == 0: return ("stopping", None) if pods else ("stopped", None)
        bad = next((p["problem"] for p in live if p["problem"]), None)
        if bad and "Insufficient " + KVM in bad:
            return "waiting", "Every KVM slot is taken (the server runs 8 machines at a time), or the KVM device plugin isn't running. It starts when one frees up."
        if bad and re.search(r"Unschedulable|Insufficient", bad): return "waiting", bad
        if bad and re.search(r"CrashLoopBackOff|ImagePull|ErrImage|InvalidImageName|CreateContainer|OOMKilled|Error", bad): return "failing", bad
        if any(p["ready"] for p in live): return "running", None
        return "starting", bad

    def _progress(self, pods):
        """The machine's last log line while it sets up (downloading, installing), for the Overview."""
        p = next((p for p in sorted(pods, key=lambda p: -(p["created"] or 0)) if p["phase"] == "Running" and not p["deleting"]), None)
        if not p: return None
        try: text = self.k.logs(NS, p["name"], "vm", 30, timestamps=False)
        except KubeError: return None
        lines = [ANSI.sub("", l).replace("\r", "").strip(" ❯") for l in text.splitlines()]
        return next((l[:300] for l in reversed(lines) if l and not set(l) <= set("-=#.")), None)

    def _out(self, d, pods):
        s, o = self._settings(d), deploy_out(d)
        status, msg = self._status(d, pods)
        osd = OS.get(s.get("os"), {})
        return {"name": d["metadata"]["name"], "status": status, "message": msg, "os": s.get("os"), "title": osd.get("title", s.get("os")),
                "family": osd.get("family"), "cores": s.get("cores"), "ram": s.get("ram"), "disk": s.get("disk"),
                "cpu": round(sum(p["cpu"] or 0 for p in pods), 3), "memory": sum(p["memory"] or 0 for p in pods),
                "created": o["created"], "started": max(filter(None, [p["created"] for p in pods]), default=None)}

    def catalog(self):
        return {"os": {k: {x: v[x] for x in ("family", "title", "min_ram", "ram", "disk")} | ({"note": v["note"]} if "note" in v else {})
                       for k, v in OS.items()},
                "languages": LANGUAGES, "limits": {"cores": 16, "ram": 64, "disk": 500}}

    def list(self):
        self._ready()
        with ThreadPoolExecutor(4) as pool:
            fd = pool.submit(self.k.items, f"/apis/apps/v1/namespaces/{NS}/deployments", {"labelSelector": LABEL})
            fp = pool.submit(self.k.items, f"/api/v1/namespaces/{NS}/pods", {"labelSelector": LABEL})
            fm = pool.submit(self.k.metrics, NS)
            fk = pool.submit(self.kvm)
            deps, usage = fd.result(), fm.result()
            pods = [pod_out(p, usage) for p in fp.result()]
        items = [self._out(d, [p for p in pods if p["deployment"] == d["metadata"]["name"]]) for d in sorted(deps, key=lambda d: d["metadata"]["name"])]
        return {"items": items, "kvm": fk.result(), **self.catalog()}

    def view(self, name):
        self._ready()
        d = self._get(name)
        sel = {"labelSelector": f"{LABEL}={name}"}
        usage = self.k.metrics(NS)
        pods = [pod_out(p, usage) for p in self.k.items(f"/api/v1/namespaces/{NS}/pods", sel)]
        names = {name, f"{name}-disk"} | {r["metadata"]["name"] for r in self.k.items(f"/apis/apps/v1/namespaces/{NS}/replicasets", sel)} | {p["name"] for p in pods}
        events = sorted((event_out(e) for e in self.k.items(f"/api/v1/namespaces/{NS}/events") if (e.get("involvedObject") or {}).get("name") in names),
                        key=lambda e: e["time"] or 0, reverse=True)[:30]
        pvc = self.k.get(f"/api/v1/namespaces/{NS}/persistentvolumeclaims/{name}-disk") or {}
        out = self._out(d, pods)
        if out["status"] == "starting": out["progress"] = self._progress(pods)
        s = self._settings(d)
        tpl = d["spec"]["template"]["metadata"].get("annotations") or {}
        return {**out, "settings": {k: s.get(k) for k in ("os", "url", "cores", "ram", "disk", "username", "language")},
                "image": IMAGES.get(out["family"] or "linux"), "note": OS.get(s.get("os"), {}).get("note"),
                "volume": {"name": f"{name}-disk", "phase": (pvc.get("status") or {}).get("phase"),
                           "size": mem(((pvc.get("spec") or {}).get("resources") or {}).get("requests", {}).get("storage"))},
                "change": tpl.get("axor.dev/change"), "pods": pods, "events": events}

    def logs(self, name, tail=300):
        self._ready()
        self._get(name)
        pods = sorted(self.k.items(f"/api/v1/namespaces/{NS}/pods", {"labelSelector": f"{LABEL}={name}"}),
                      key=lambda p: p["metadata"]["creationTimestamp"], reverse=True)[:3]
        lines = []
        for p in pods:
            try: text = self.k.logs(NS, p["metadata"]["name"], "vm", tail)
            except KubeError: continue
            lines += [(t, ANSI.sub("", m).replace("\r", "")) for t, _, m in (ln.partition(" ") for ln in text.splitlines())]
        lines.sort(key=lambda x: x[0])
        return {"text": "\n".join(f"{t[11:19]} {m}" for t, m in lines[-int(tail):])[-400_000:]}

    # ---------- changes (the caller has checked admin and sudo) ----------
    def save(self, me, b: MachineIn, ip, create):
        self._ready()
        if not NAME.match(b.name): raise HTTPException(400, "Names are 1-30 lowercase letters, digits or dashes, starting with a letter.")
        cur = self.k.get(f"/apis/apps/v1/namespaces/{NS}/deployments/{b.name}")
        if create and cur: raise HTTPException(409, f"There's already a machine called {b.name}.")
        if not create and (not cur or LABEL not in (cur["metadata"].get("labels") or {})): raise HTTPException(404, f"There's no machine called {b.name}.")
        old = self._settings(cur) if cur else {}
        if old and (b.os != old.get("os") or b.disk != old.get("disk")):
            raise HTTPException(400, "A machine's system and disk are set when it's made. Make a new machine for another one.")
        osd = OS.get(b.os)
        if not osd: raise HTTPException(400, "Pick an operating system from the list.")
        if b.ram < osd["min_ram"]: raise HTTPException(400, f"{osd['title']} needs at least {osd['min_ram']} GB of memory.")
        if b.disk < 20 and osd["family"] == "windows": raise HTTPException(400, "Windows needs a disk of at least 20 GB (64 GB is comfortable).")
        win = osd["family"] == "windows"
        settings = {"os": b.os, "cores": b.cores, "ram": b.ram, "disk": b.disk}
        # what the system's setup reads (the image, the Windows account and language) is kept from when it was made
        if old: settings.update({k: old[k] for k in ("url", "username", "language") if k in old})
        elif win:
            user = b.username.strip() or "admin"
            if not WIN_USER.match(user) or user.lower() in ("administrator", "guest", "none", "defaultaccount", "system", "wdagutilityaccount"):
                raise HTTPException(400, "The Windows account is 1-20 letters, digits, dots, dashes or spaces, and not a built-in name such as Administrator.")
            if b.password is None or not 4 <= len(b.password) <= 127 or re.search(r"[\x00-\x1f\x7f]", b.password):
                raise HTTPException(400, "Set a password for the Windows account: 4-127 characters, without control characters.")
            settings.update({"username": user, "language": b.language if b.language in LANGUAGES else "en"})
        elif b.os == "custom":
            if not URL.match(b.url.strip()):
                raise HTTPException(400, "Give the image's address, e.g. https://example.org/distro.iso (an ISO, or a qcow2, img, raw, vhd, vhdx or vmdk disk).")
            settings["url"] = b.url.strip()
        changed = [k for k in settings if settings[k] != old.get(k)]
        if old and not changed: return self.view(b.name)  # an unchanged pod template: no restart for nothing
        env = {"CPU_CORES": str(b.cores), "RAM_SIZE": f"{b.ram}G", "DISK_SIZE": f"{b.disk}G",
               "NETWORK": "user",  # passt: needs no NET_ADMIN or /dev/net/tun
               "RAM_CHECK": "N"}  # the pod's memory limit is the VM's plus room for QEMU: no need to guess from free memory
        if win: env.update({"VERSION": osd["version"], "LANGUAGE": settings["language"]})
        else: env["BOOT"] = settings.get("url") or osd["boot"]
        cause = f"{me['username']} created it" if create else f"{me['username']} changed {', '.join(changed)}"
        labels = {LABEL: b.name, "app.kubernetes.io/managed-by": "axor"}
        if win and create:  # read by Windows setup only: the account's password lives in Windows after that
            self.k.apply(f"/api/v1/namespaces/{NS}/secrets", {"apiVersion": "v1", "kind": "Secret", "type": "Opaque",
                                                              "metadata": {"name": f"{b.name}-login", "namespace": NS, "labels": labels},
                                                              "data": {"USERNAME": _b64(settings["username"]), "PASSWORD": _b64(b.password)}})
        pvc = f"/api/v1/namespaces/{NS}/persistentvolumeclaims"
        have = self.k.get(f"{pvc}/{b.name}-disk")  # (left by a make that failed half-way, it's empty: use it)
        if have and have["metadata"].get("deletionTimestamp"):
            raise HTTPException(409, f"The disk of an earlier machine called {b.name} is still being deleted. Try again in a minute.")
        if not have:
            self.k.call("POST", pvc, body={"apiVersion": "v1", "kind": "PersistentVolumeClaim", "metadata": {"name": f"{b.name}-disk", "labels": labels},
                                           "spec": {"accessModes": ["ReadWriteOnce"], "resources": {"requests": {"storage": f"{b.disk + EXTRA_GB}Gi"}}}})
        c = {"name": "vm", "image": IMAGES[osd["family"]], "env": [{"name": k, "value": v} for k, v in sorted(env.items())],
             "ports": [{"name": "vnc", "containerPort": VNC}],
             "resources": {"limits": {"cpu": f"{b.cores * 1000 + 500}m", "memory": f"{(b.ram + 1) * 1024}Mi", KVM: "1"},
                           "requests": {"cpu": f"{b.cores * 250}m", "memory": f"{b.ram * 1024 + 256}Mi", KVM: "1"}},
             "readinessProbe": {"tcpSocket": {"port": VNC}, "periodSeconds": 5, "failureThreshold": 2},
             "volumeMounts": [{"name": "disk", "mountPath": "/storage"}],
             "securityContext": {"allowPrivilegeEscalation": False, "capabilities": {"drop": CAP_DROP}, "seccompProfile": {"type": "RuntimeDefault"}}}
        if win: c["envFrom"] = [{"secretRef": {"name": f"{b.name}-login"}}]
        pod = {"automountServiceAccountToken": False, "enableServiceLinks": False, "hostname": b.name,
               "terminationGracePeriodSeconds": 130,  # the image shuts the guest down (ACPI) and waits up to 105 s
               "containers": [c], "volumes": [{"name": "disk", "persistentVolumeClaim": {"claimName": f"{b.name}-disk"}}]}
        prev = (cur or {}).get("spec", {}).get("template", {}).get("metadata", {}).get("annotations") or {}
        tpl_ann = {"axor.dev/change": cause, **{k: v for k, v in prev.items() if k == "kubectl.kubernetes.io/restartedAt"}}
        self.k.apply(f"/apis/apps/v1/namespaces/{NS}/deployments", {
            "apiVersion": "apps/v1", "kind": "Deployment",
            "metadata": {"name": b.name, "namespace": NS, "labels": labels, "annotations": {"axor.dev/settings": json.dumps(settings, sort_keys=True)}},
            "spec": {"replicas": (cur or {}).get("spec", {}).get("replicas", 1), "selector": {"matchLabels": {LABEL: b.name}},
                     "strategy": {"type": "Recreate"},  # one VM per disk, always
                     "revisionHistoryLimit": 2, "progressDeadlineSeconds": 86400,  # a first start downloads the system: it may take a while
                     "template": {"metadata": {"labels": labels, "annotations": tpl_ann}, "spec": pod}}})
        self.k.apply(f"/api/v1/namespaces/{NS}/services", {
            "apiVersion": "v1", "kind": "Service", "metadata": {"name": b.name, "namespace": NS, "labels": labels},
            "spec": {"selector": {LABEL: b.name}, "ports": [{"name": "vnc", "port": VNC, "targetPort": VNC}]}})
        self.db.log("machine.create" if create else "machine.update", me["username"], b.name, ip,
                    (f"{osd['title']}, {b.cores} cores, {b.ram} GB, {b.disk} GB disk" if create else cause)[:200])
        return self.view(b.name)

    def act(self, me, name, action, ip):
        self._ready()
        d = self._get(name)
        if action == "restart":
            if d["spec"].get("replicas", 1) == 0: raise HTTPException(409, "It's stopped: start it instead.")
            self.k.patch(f"/apis/apps/v1/namespaces/{NS}/deployments/{name}",
                         {"spec": {"template": {"metadata": {"annotations": {"kubectl.kubernetes.io/restartedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}}}}})
        elif action in ("stop", "start"):
            self.k.patch(f"/apis/apps/v1/namespaces/{NS}/deployments/{name}/scale", {"spec": {"replicas": 0 if action == "stop" else 1}}, kind="merge")
        else: raise HTTPException(400, "Unknown action.")
        self.db.log(f"machine.{action}", me["username"], name, ip, "")
        return {"ok": True}

    def delete(self, me, name, ip):
        self._ready()
        self._get(name)
        sel = {"labelSelector": f"{LABEL}={name}"}
        self.k.delete(f"/apis/apps/v1/namespaces/{NS}/deployments/{name}", {"propagationPolicy": "Foreground"})
        self.k.delete(f"/api/v1/namespaces/{NS}/services/{name}")
        for plural in ("secrets", "persistentvolumeclaims"):  # the disk goes once the pod has (its protection finalizer waits)
            for x in self.k.items(f"/api/v1/namespaces/{NS}/{plural}", sel): self.k.delete(f"/api/v1/namespaces/{NS}/{plural}/{x['metadata']['name']}")
        self.db.log("machine.delete", me["username"], name, ip, "disk deleted")
        return {"ok": True}

    def target(self, name):
        """Where the console connects: the machine's Service, once QEMU (and so its VNC port) is up."""
        self._ready()
        d = self._get(name)
        if d["spec"].get("replicas", 1) == 0: raise HTTPException(409, "The machine is stopped. Start it to use its console.")
        if not (d.get("status") or {}).get("readyReplicas"):
            raise HTTPException(409, "The machine is still starting: the console opens once its virtual machine runs (Logs shows how far it is).")
        svc = self.k.get(f"/api/v1/namespaces/{NS}/services/{name}")
        if not svc or not svc["spec"].get("clusterIP"): raise HTTPException(409, "It has no service yet.")
        return svc["spec"]["clusterIP"]

def build(db, helpers, ip, kube):
    r = APIRouter(prefix="/api/machines")
    admin, sudo = helpers["admin"], helpers["sudo"]
    m = Machines(db, kube)
    r.state = {"machines": m}

    def call(fn, *a):
        try: return fn(*a)
        except KubeError as e: raise HTTPException(e.status if e.status in (400, 403, 404, 409, 422, 503) else 502, str(e))

    @r.get("")
    def items(req: Request):
        admin(req)
        return call(m.list)

    @r.post("")
    def create(b: MachineIn, req: Request):
        return call(m.save, sudo(req), b, ip(req), True)

    @r.get("/{name}")
    def view(name: str, req: Request):
        admin(req)
        return call(m.view, name)

    @r.put("/{name}")
    def update(name: str, b: MachineIn, req: Request):
        if b.name != name: raise HTTPException(400, "Machines can't be renamed.")
        return call(m.save, sudo(req), b, ip(req), False)

    @r.delete("/{name}")
    def delete(name: str, req: Request):
        return call(m.delete, sudo(req), name, ip(req))

    @r.post("/{name}/action")
    def act(name: str, a: Act, req: Request):
        return call(m.act, sudo(req), name, a.action, ip(req))

    @r.get("/{name}/logs")
    def logs(name: str, req: Request, tail: int = 300):
        admin(req)
        return call(m.logs, name, max(1, min(tail, 5000)))

    @r.get("/{name}/console")
    def console_check(name: str, req: Request):
        """Asked before the WebSocket opens, so a sudo prompt or "still starting" shows as a message, not a dropped socket."""
        sudo(req)
        call(m.target, name)
        return {"ok": True}

    @r.websocket("/{name}/console")
    async def console(ws: WebSocket, name: str):
        """The console: noVNC's RFB stream relayed to QEMU's VNC port. Close codes 4400-4599 carry an HTTP status and a reason."""
        offered = [p.strip() for p in ws.headers.get("sec-websocket-protocol", "").split(",")]
        await ws.accept(subprotocol="binary" if "binary" in offered else None)
        async def refuse(status, reason):
            await ws.close(code=4000 + status if 400 <= status < 600 else 4500, reason=str(reason)[:120])
        origin, host = ws.headers.get("origin", ""), ws.headers.get("x-forwarded-host") or ws.headers.get("host", "")
        if not origin or origin.split("://", 1)[-1] != host: return await refuse(403, "Cross-site connection refused.")
        try:
            me = await run_in_threadpool(sudo, ws)
            addr = await run_in_threadpool(call, m.target, name)
        except HTTPException as e: return await refuse(e.status_code, e.detail)
        try: reader, writer = await asyncio.wait_for(asyncio.open_connection(addr, VNC), 10)
        except (OSError, asyncio.TimeoutError) as e: return await refuse(502, f"Can't reach the machine's screen ({e or 'timed out'}).")
        await run_in_threadpool(db.log, "machine.console", me["username"], name, ip(ws), "")

        async def up():  # browser → QEMU
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect": return
                writer.write(msg.get("bytes") or (msg.get("text") or "").encode())
                await writer.drain()
        async def down():  # QEMU → browser
            while data := await reader.read(65536): await ws.send_bytes(data)
        async def session():  # signing out (or losing admin) ends the console too
            while True:
                await asyncio.sleep(30)
                try: await run_in_threadpool(admin, ws)
                except HTTPException: return
        tasks = [asyncio.create_task(f()) for f in (up, down, session)]
        try: await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in tasks: t.cancel()
            writer.close()
            try: await ws.close()
            except RuntimeError: pass  # the browser went first

    return r
