"""Docker: this server's containers and images, managed from the app (admins only).

Scout never mounts the Docker socket. It talks to docker-proxy (wollomatic/socket-proxy, docker-compose profile
"docker") at DOCKER_URL over a private network, and the proxy passes on only what this page uses: listing,
inspecting, logs and stats; start, stop and restart; removing a container; pulling, removing and pruning images.
Creating containers, exec, builds, volumes and everything else is refused by the proxy itself, so even a compromised
Scout can't start a privileged container. Outside Docker, DOCKER_URL can be unix:///var/run/docker.sock instead.

Reads need an admin session, changes also need sudo, and every change is audited. Scout's own container can't be
touched here; containers labelled scout.protected (the drive and the proxy) can be restarted but not stopped or removed.
"""
import http.client, json, logging, os, re, socket, struct, urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

log = logging.getLogger("docker")
URL = os.getenv("DOCKER_URL", "")
PROTECTED = "scout.protected"
SELF = socket.gethostname()  # Docker names a container's host after its short ID unless compose sets a hostname
SELF = SELF if re.fullmatch(r"[0-9a-f]{12}", SELF) else "-"  # outside a container: matches no ID
CID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")
IMAGE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._/:@-]{0,254}$")  # redis:7, ghcr.io/org/app:1.2, name@sha256:…, sha256:…
ACTIONS = ("start", "stop", "restart", "remove")
SETUP = "Start the Docker proxy with `docker compose --profile docker up -d` (see Docker in the README)."

class _Unix(http.client.HTTPConnection):
    def __init__(self, path, timeout):
        super().__init__("localhost", timeout=timeout); self.sock_path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout); self.sock.connect(self.sock_path)

def _demux(b):
    """Container logs without a TTY come in frames: 1 byte stream, 3 zero bytes, 4 bytes length, then the data."""
    out, i = [], 0
    while i + 8 <= len(b) and b[i] in (0, 1, 2) and b[i + 1:i + 4] == b"\0\0\0":
        n = struct.unpack(">I", b[i + 4:i + 8])[0]
        out.append(b[i + 8:i + 8 + n]); i += 8 + n
    return b"".join(out) + b[i:]

class Docker:
    def __init__(self, db, url=URL):
        self.db, self.url, self._ver = db, url, None

    # ---------- engine API ----------
    def _conn(self, timeout):
        u = urllib.parse.urlparse(self.url)
        if u.scheme == "unix": return _Unix(u.path, timeout)
        return http.client.HTTPConnection(u.hostname, u.port or 2375, timeout=timeout)

    def version(self):
        # Engines refuse API versions below their minimum (1.44 on Docker 29), so use the daemon's own
        if not self._ver: self._ver = self._call("GET", "/version", versioned=False)["ApiVersion"]
        return self._ver

    def _call(self, method, path, params=None, timeout=30, raw=False, versioned=True):
        if not self.url: raise HTTPException(503, "Docker management isn't set up on this server (DOCKER_URL). " + SETUP)
        if versioned: path = f"/v{self.version()}{path}"
        q = "?" + urllib.parse.urlencode(params) if params else ""
        c = self._conn(timeout)
        try:
            c.request(method, path + q, headers={"Host": "docker"})
            res = c.getresponse(); body = res.read()
        except OSError as e:
            self._ver = None  # the proxy or engine may come back as a different version
            raise HTTPException(502, f"Can't reach Docker at {self.url} ({e}). {SETUP}")
        finally:
            c.close()
        if res.status == 304: return None  # already started / stopped
        if res.status >= 400:
            try: msg = json.loads(body).get("message")
            except ValueError: msg = None
            if not msg and res.status == 403: msg = "The Docker proxy doesn't allow this request."
            log.info("docker %s %s -> %s %s", method, path, res.status, msg)
            raise HTTPException(res.status if res.status in (400, 403, 404, 409) else 502, msg or f"Docker answered {res.status}.")
        if raw: return body
        return json.loads(body) if body.strip() else None

    def _inspect(self, cid):
        if not CID.match(cid): raise HTTPException(400, "Unknown container.")
        return self._call("GET", f"/containers/{cid}/json")

    # ---------- reads ----------
    def overview(self):
        info = self._call("GET", "/info")
        cs = self._call("GET", "/containers/json", {"all": 1})
        ims = self._call("GET", "/images/json")
        used = Counter(c["ImageID"] for c in cs)
        port = lambda p: f'{p["PublicPort"]}→{p["PrivatePort"]}/{p["Type"]}' if p.get("PublicPort") else f'{p["PrivatePort"]}/{p["Type"]}'
        containers = [{
            "id": c["Id"][:12], "name": (c.get("Names") or ["/" + c["Id"][:12]])[0].lstrip("/"),
            "image": c["Image"], "image_id": c["ImageID"], "state": c["State"], "status": c["Status"], "created": c["Created"],
            "ports": sorted({port(p) for p in c.get("Ports") or []}),  # IPv4 and IPv6 bindings list the same port twice
            "project": (c.get("Labels") or {}).get("com.docker.compose.project", ""),
            "protected": PROTECTED in (c.get("Labels") or {}), "self": c["Id"].startswith(SELF),
        } for c in cs]
        images = [{
            "id": i["Id"], "short": i["Id"].split(":")[-1][:12], "size": i.get("Size", 0), "created": i["Created"],
            "tags": [t for t in i.get("RepoTags") or [] if t != "<none>:<none>"], "containers": used[i["Id"]],
        } for i in ims]
        return {"engine": {k: info.get(v) for k, v in (("version", "ServerVersion"), ("os", "OperatingSystem"),
                                                        ("cpus", "NCPU"), ("memory", "MemTotal"))},
                "containers": containers, "images": images}

    def _stat(self, cid):
        try: s = self._call("GET", f"/containers/{cid}/stats", {"stream": "false"}, timeout=10)
        except HTTPException: return None
        cpu, pre, mem = s.get("cpu_stats") or {}, s.get("precpu_stats") or {}, s.get("memory_stats") or {}
        d_cpu = cpu.get("cpu_usage", {}).get("total_usage", 0) - pre.get("cpu_usage", {}).get("total_usage", 0)
        d_sys = cpu.get("system_cpu_usage", 0) - pre.get("system_cpu_usage", 0)
        n = cpu.get("online_cpus") or len(cpu.get("cpu_usage", {}).get("percpu_usage") or [1])
        used = mem.get("usage", 0) - (mem.get("stats") or {}).get("inactive_file", 0)  # what `docker stats` shows
        return {"cpu": round(d_cpu / d_sys * n * 100, 1) if d_sys > 0 else 0.0, "mem": max(used, 0), "mem_limit": mem.get("limit", 0)}

    def stats(self):
        ids = [c["Id"] for c in self._call("GET", "/containers/json")]
        with ThreadPoolExecutor(8) as pool:  # each one waits ~1 s for two samples
            return dict(zip((i[:12] for i in ids), pool.map(self._stat, ids)))

    def logs(self, cid, tail=300):
        c = self._inspect(cid)
        body = self._call("GET", f"/containers/{cid}/logs",
                          {"stdout": 1, "stderr": 1, "timestamps": 1, "tail": max(1, min(int(tail), 5000))}, timeout=20, raw=True)
        text = (body if c["Config"].get("Tty") else _demux(body)).decode("utf-8", "replace")
        return {"name": c["Name"].lstrip("/"), "text": text[-400_000:]}

    # ---------- changes (caller must have verified admin + sudo) ----------
    def act(self, me, cid, action, ip):
        if action not in ACTIONS: raise HTTPException(400, "Unknown action.")
        c = self._inspect(cid)
        name = c["Name"].lstrip("/")
        if c["Id"].startswith(SELF):
            raise HTTPException(400, f"{name} is AXoR itself. Restart it with docker compose on the server.")
        if action in ("stop", "remove") and PROTECTED in (c["Config"].get("Labels") or {}):
            raise HTTPException(400, f"AXoR needs {name}, so it can't be stopped or removed here. Restarting works.")
        if action == "restart" and PROTECTED in (c["Config"].get("Labels") or {}):
            self.db.log("docker.restart", me["username"], name, ip, c["Config"]["Image"])  # the proxy may restart before answering
            return self._restart_protected(cid, name)
        if action == "remove":
            if c["State"]["Running"]: raise HTTPException(409, f"{name} is running. Stop it first.")
            self._call("DELETE", f"/containers/{cid}")
        else:
            self._call("POST", f"/containers/{cid}/{action}", timeout=60)
        self.db.log("docker." + action, me["username"], name, ip, c["Config"]["Image"])
        return {"ok": True, "name": name, "action": action}

    def _restart_protected(self, cid, name):
        try: self._call("POST", f"/containers/{cid}/restart", timeout=60)
        except HTTPException as e:
            if e.status_code != 502: raise
        return {"ok": True, "name": name, "action": "restart"}

    def pull(self, me, ref, ip):
        ref = ref.strip()
        if not IMAGE.match(ref) or ref.startswith("sha256:"):
            raise HTTPException(400, "That isn't an image name. Try e.g. redis:7 or ghcr.io/org/app:1.2.")
        name, tag = ref, None
        if "@" not in ref and ":" in ref.rsplit("/", 1)[-1]: name, tag = ref.rsplit(":", 1)
        params = {"fromImage": name, **({} if "@" in ref else {"tag": tag or "latest"})}
        body = self._call("POST", "/images/create", params, timeout=900, raw=True)  # newline-delimited progress
        msgs = [json.loads(x) for x in body.splitlines() if x.strip().startswith(b"{")]
        err = next((m["error"] for m in msgs if m.get("error")), None)
        if err: raise HTTPException(400, err)
        full = ref if "@" in ref else f"{name}:{tag or 'latest'}"
        self.db.log("docker.pull", me["username"], full, ip, "")
        return {"ok": True, "image": full, "status": msgs[-1].get("status", "") if msgs else ""}

    def remove_image(self, me, ref, ip):
        if not IMAGE.match(ref): raise HTTPException(400, "Unknown image.")
        out = self._call("DELETE", "/images/" + urllib.parse.quote(ref, safe="/:@")) or []  # never forced: in-use images stay
        self.db.log("docker.rmi", me["username"], ref, ip, f"{sum('Deleted' in x for x in out)} layers deleted")
        return {"ok": True, "deleted": sum("Deleted" in x for x in out), "untagged": sum("Untagged" in x for x in out)}

    def prune(self, me, all_, ip):
        r = self._call("POST", "/images/prune", {"filters": json.dumps({"dangling": ["false" if all_ else "true"]})}, timeout=300) or {}
        out = {"ok": True, "deleted": len(r.get("ImagesDeleted") or []), "reclaimed": r.get("SpaceReclaimed", 0)}
        self.db.log("docker.prune", me["username"], "all unused" if all_ else "dangling", ip, f"{out['reclaimed']} bytes reclaimed")
        return out

class Act(BaseModel):
    action: str

class Pull(BaseModel):
    image: str = Field(..., max_length=255)

class Prune(BaseModel):
    all: bool = False

def build(db, helpers, ip):
    r = APIRouter(prefix="/api/docker")
    admin, sudo = helpers["admin"], helpers["sudo"]
    d = Docker(db)
    r.state = {"docker": d}

    @r.get("")
    def overview(req: Request):
        admin(req)
        return d.overview()

    @r.get("/stats")
    def stats(req: Request):
        admin(req)
        return d.stats()

    @r.get("/containers/{cid}/logs")
    def logs(cid: str, req: Request, tail: int = 300):
        admin(req)
        return d.logs(cid, tail)

    @r.post("/containers/{cid}")
    def act(cid: str, a: Act, req: Request):
        return d.act(sudo(req), cid, a.action, ip(req))

    @r.post("/images/pull")
    def pull(p: Pull, req: Request):
        return d.pull(sudo(req), p.image, ip(req))

    @r.post("/images/prune")
    def prune(p: Prune, req: Request):
        return d.prune(sudo(req), p.all, ip(req))

    @r.delete("/images/{ref:path}")
    def remove_image(ref: str, req: Request):
        return d.remove_image(sudo(req), ref, ip(req))

    return r
