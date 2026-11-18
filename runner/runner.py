"""AXoR Runner: builds, tests and runs the apps of AXoR's DevOps pipelines on this server's Docker engine.

It runs as its own service (own container) and is the only part of AXoR allowed to build images and create
containers. AXoR reaches it over a private network with a shared secret (RUNNER_SECRET, or the file
RUNNER_SECRET_FILE written on first start) and sends it a repository snapshot or a deploy request; the runner
decides how every container is set up, so nothing AXoR sends can widen what a container may do:

- Builds use the engine's builder on the tar context AXoR sends (the repository at one commit). RUN steps get the
  builder's own sandbox: no host paths, no privileges, memory capped at RUNNER_MAX_MEMORY_MB.
- Every container it creates (tests, deployed apps, health checks) gets the same hardened settings: not privileged,
  no host paths, devices, host network or host namespaces, no-new-privileges, NET_RAW/MKNOD/AUDIT_WRITE/SETFCAP
  dropped, memory, CPU and process limits, rotated logs, on its own bridge network (RUNNER_NETWORK) away from AXoR.
- It only runs images it built for that app, only publishes host ports in RUNNER_PORTS (bound to RUNNER_BIND),
  and only lists, changes or removes containers, images and volumes with its label (axor.devops), so it can't
  touch AXoR or anything else on the host.
- A deploy stops the running version, starts the new one and checks its health (an HTTP path answered from the
  apps' network, or the container staying up); if the new one fails, the previous container is started again.

Long operations answer with newline-delimited JSON: {"log": text} lines, then {"done": ...} or {"error": ...}.
AXoR keeps the pipelines, history, secrets and audit log; the runner's only state is what its labels say.
Run: RUNNER_SECRET_FILE=/secret/runner.key uvicorn runner:app --port 8200
"""
import codecs, hmac, http.client, json, logging, os, re, secrets, socket, struct, tempfile, threading, time, urllib.parse
from collections import defaultdict
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("runner")
DOCKER = os.getenv("RUNNER_DOCKER", "unix:///var/run/docker.sock")
NETWORK = os.getenv("RUNNER_NETWORK", "axor-apps")
BIND = os.getenv("RUNNER_BIND", "0.0.0.0")
_lo, _, _hi = os.getenv("RUNNER_PORTS", "9200-9299").partition("-")
PORTS = range(int(_lo), int(_hi or _lo) + 1)
MAX_MEMORY = int(os.getenv("RUNNER_MAX_MEMORY_MB", "4096"))
MAX_CPUS = float(os.getenv("RUNNER_MAX_CPUS", "4"))
CONTEXT_MAX = int(os.getenv("RUNNER_CONTEXT_MB", "200")) * 2**20
BUILD_SECONDS = int(os.getenv("RUNNER_BUILD_MINUTES", "30")) * 60
BUILDS = threading.Semaphore(max(1, int(os.getenv("RUNNER_BUILDS", "2"))))
LABEL = "axor.devops"  # app | test | check on containers, image on images, volume on volumes, network on the network
DROP = ["NET_RAW", "MKNOD", "AUDIT_WRITE", "SETFCAP"]  # of Docker's default capabilities, the ones apps don't need
APP = re.compile(r"^[a-z][a-z0-9-]{0,29}$")
TAG = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
PATH = re.compile(r"^/[A-Za-z0-9._~/-]{0,199}$")
DOCKERFILE = re.compile(r"^(?!/)(?!.*\.\.)[A-Za-z0-9._/-]{1,200}$")

def load_secret():
    if os.getenv("RUNNER_SECRET"): return os.getenv("RUNNER_SECRET")
    path = Path(os.getenv("RUNNER_SECRET_FILE", Path(__file__).resolve().parent / "var" / "runner.key"))
    if not path.exists():  # first start: make one; AXoR reads the same file (a shared volume in docker-compose)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_urlsafe(32))
        os.chmod(path, 0o600)
    return path.read_text().strip()

SECRET = load_secret()

# ---------- engine API ----------
class EngineError(Exception):
    def __init__(self, status, msg):
        super().__init__(msg); self.status = status

class _Unix(http.client.HTTPConnection):
    def __init__(self, path, timeout):
        super().__init__("localhost", timeout=timeout); self.sock_path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout); self.sock.connect(self.sock_path)

class Engine:
    def __init__(self, url):
        self.url, self._ver = url, None

    def _conn(self, timeout):
        u = urllib.parse.urlparse(self.url)
        if u.scheme == "unix": return _Unix(u.path, timeout)
        return http.client.HTTPConnection(u.hostname, u.port or 2375, timeout=timeout)

    def version(self):
        # Engines refuse API versions below their minimum (1.44 on Docker 29), so use the daemon's own
        if not self._ver: self._ver = self.call("GET", "/version", versioned=False)["ApiVersion"]
        return self._ver

    def open(self, method, path, params=None, body=None, headers=None, timeout=60, versioned=True):
        """Sends a request and returns (connection, response) with the body unread, for streaming; close the connection."""
        if versioned: path = f"/v{self.version()}{path}"
        q = "?" + urllib.parse.urlencode(params) if params else ""
        h = {"Host": "docker", **(headers or {})}
        if isinstance(body, (dict, list)): body, h["Content-Type"] = json.dumps(body).encode(), "application/json"
        c = self._conn(timeout)
        try:
            c.request(method, path + q, body=body, headers=h)
            res = c.getresponse()
        except OSError as e:
            c.close(); self._ver = None
            raise EngineError(502, f"Can't reach the Docker engine at {self.url} ({e}).")
        if res.status >= 400:
            data = res.read(); c.close()
            try: msg = json.loads(data).get("message")
            except ValueError: msg = None
            raise EngineError(res.status, msg or f"Docker answered {res.status}.")
        return c, res

    def call(self, method, path, params=None, body=None, timeout=60, versioned=True):
        c, res = self.open(method, path, params, body, timeout=timeout, versioned=versioned)
        try: data = res.read()
        finally: c.close()
        return json.loads(data) if data.strip() else None

    def get(self, path, params=None):
        """GET, or None when it doesn't exist."""
        try: return self.call("GET", path, params)
        except EngineError as e:
            if e.status == 404: return None
            raise

E = Engine(DOCKER)
JOBS, CANCELLED, LOCKS, _locks = {}, set(), defaultdict(threading.Lock), threading.Lock()
_check_image = None

def line(**k): return json.dumps(k) + "\n"

def _shut(c):
    """Unblocks a reader on another thread: closing the engine connection also cancels a build."""
    try:
        if c.sock: c.sock.shutdown(socket.SHUT_RDWR)
    except OSError: pass

def _quiet(fn):
    try: return fn()
    except EngineError as e: log.info("ignored: %s", e)

def _frames(res):
    """Container output without a TTY comes in frames: 1 byte stream, 3 zero bytes, 4 bytes length, then the data."""
    dec = codecs.getincrementaldecoder("utf-8")("replace")
    while True:
        h = res.read(8)
        if len(h) < 8: return
        n = struct.unpack(">I", h[4:8])[0]
        text = dec.decode(res.read(n))
        if text: yield text

def _flt(**labels):
    return json.dumps({"label": [f"{k}={v}" if v is not None else k for k, v in labels.items()]})

def _lock(app_):
    with _locks: return LOCKS[app_]

def network():
    if E.get(f"/networks/{NETWORK}"): return
    try: E.call("POST", "/networks/create", body={"Name": NETWORK, "Driver": "bridge", "Labels": {LABEL: "network"}})
    except EngineError as e:
        if e.status != 409: raise  # made meanwhile by another request

def check_image():
    """The image health checks run in: the runner's own (it has Python), or RUNNER_CHECK_IMAGE outside Docker."""
    global _check_image
    if not _check_image:
        me = E.get(f"/containers/{socket.gethostname()}/json")
        _check_image = os.getenv("RUNNER_CHECK_IMAGE") or (me["Image"] if me else "python:3.12-slim")
    return _check_image

def hardened(app_, image, kind, env, memory_mb, cpus, run="", entrypoint=None, cmd=None, port=None, host_port=None, volume=""):
    """The only container settings the runner ever uses; nothing in a request can add host access to them."""
    labels = {LABEL: kind, "axor.app": app_, "axor.run": run}
    mem = int(memory_mb) * 2**20
    host = {"Privileged": False, "CapDrop": DROP, "SecurityOpt": ["no-new-privileges:true"], "Init": True,
            "Memory": mem, "MemorySwap": mem, "NanoCpus": int(cpus * 1e9), "PidsLimit": 512, "NetworkMode": NETWORK,
            "LogConfig": {"Type": "json-file", "Config": {"max-size": "10m", "max-file": "3"}},
            "RestartPolicy": {"Name": "unless-stopped" if kind == "app" else "no"}}
    cfg = {"Image": image, "Env": [f"{k}={v}" for k, v in (env or {}).items()], "Labels": labels, "Tty": False, "HostConfig": host,
           "NetworkingConfig": {"EndpointsConfig": {NETWORK: {"Aliases": [app_] if kind == "app" else []}}}}
    if entrypoint is not None: cfg["Entrypoint"] = entrypoint
    if cmd is not None: cfg["Cmd"] = cmd
    if port:
        cfg["ExposedPorts"] = {f"{port}/tcp": {}}
        if host_port:
            host["PortBindings"] = {f"{port}/tcp": [{"HostIp": BIND, "HostPort": str(host_port)}]}
            labels["axor.port"] = str(host_port)
    if volume:
        host["Mounts"] = [{"Type": "volume", "Source": f"axor-app-{app_}", "Target": volume,
                           "VolumeOptions": {"Labels": {LABEL: "volume", "axor.app": app_}}}]
    return cfg

def _ours(c):
    return LABEL in ((c.get("Config") or {}).get("Labels") or c.get("Labels") or {})

def _remove(name):
    c = E.get(f"/containers/{name}/json")
    if c and _ours(c): E.call("DELETE", f"/containers/{c['Id']}", {"force": 1, "v": 1})

def _own_image(app_, image):
    i = E.get(f"/images/{urllib.parse.quote(image, safe='/:@')}/json")
    if not i or (i["Config"].get("Labels") or {}).get("axor.app") != app_:
        raise HTTPException(400, f"{image} isn't an image the runner built for {app_}.")
    return i

def _apps():
    return E.call("GET", "/containers/json", {"all": 1, "filters": _flt(**{LABEL: "app"})})

def _app_out(c):
    lb = c.get("Labels") or {}
    return {"app": lb.get("axor.app"), "name": c["Names"][0].lstrip("/"), "id": c["Id"][:12], "state": c["State"], "status": c["Status"],
            "image": c["Image"], "run": lb.get("axor.run", ""), "host_port": int(lb["axor.port"]) if lb.get("axor.port") else None,
            "created": c["Created"]}

def _images(app_):
    ims = E.call("GET", "/images/json", {"filters": _flt(**{LABEL: "image", "axor.app": app_})})
    return sorted(ims, key=lambda i: i["Created"], reverse=True)

def _prune(app_, keep):
    """Removes an app's images except the ones named in keep and any a container still uses."""
    used = {c["ImageID"] for c in E.call("GET", "/containers/json", {"all": 1, "filters": _flt(**{"axor.app": app_})})}
    gone = 0
    for i in _images(app_):
        if i["Id"] in used or set(i.get("RepoTags") or []) & keep: continue
        if _quiet(lambda: E.call("DELETE", f"/images/{i['Id']}", {"force": 1})) is not None: gone += 1
    return gone

def _job(job, cancel):
    if job: JOBS[job] = cancel

def _done(job):
    JOBS.pop(job, None); CANCELLED.discard(job)

def _app_ok(name):
    if not APP.match(name or ""): raise HTTPException(400, "App names are 1-30 lowercase letters, digits or dashes, starting with a letter.")
    return name

def _env_ok(env):
    if len(env) > 100: raise HTTPException(400, "Too many environment variables (100 at most).")
    for k, v in env.items():
        if not ENV_KEY.match(k): raise HTTPException(400, f"{k!r} isn't a valid environment variable name.")
        if len(v) > 8192 or "\0" in v: raise HTTPException(400, f"The value of {k} is too long.")
    return env

def _limits(memory_mb, cpus):
    if not 32 <= memory_mb <= MAX_MEMORY: raise HTTPException(400, f"Memory must be 32-{MAX_MEMORY} MB on this server.")
    if not 0.1 <= cpus <= MAX_CPUS: raise HTTPException(400, f"CPUs must be 0.1-{MAX_CPUS:g} on this server.")

# ---------- API ----------
app = FastAPI(title="AXoR Runner", docs_url=None, redoc_url=None, openapi_url=None)

def auth(req: Request):
    if not hmac.compare_digest(req.headers.get("authorization", "").encode(), f"Bearer {SECRET}".encode()):
        raise HTTPException(401, "Unauthorized.")

def engine(fn):
    try: return fn()
    except EngineError as e: raise HTTPException(e.status if e.status in (400, 404, 409) else 502, str(e))

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/info", dependencies=[Depends(auth)])
def info():
    def go():
        v = E.call("GET", "/version", versioned=False)
        return {"engine": v.get("Version"), "api": v.get("ApiVersion"), "network": NETWORK, "bind": BIND, "ports": [PORTS.start, PORTS.stop - 1],
                "max_memory_mb": MAX_MEMORY, "max_cpus": MAX_CPUS, "context_mb": CONTEXT_MAX // 2**20,
                "build_minutes": BUILD_SECONDS // 60, "apps": [_app_out(c) for c in _apps()]}
    return engine(go)

@app.post("/build", dependencies=[Depends(auth)])
async def build(req: Request, name: str, tag: str, dockerfile: str = "Dockerfile", job: str = "", args: str = "{}", nocache: bool = False):
    """Body: the build context as a tar (gzip allowed). Answers with the build output, then {"done": true, "image": ...}."""
    _app_ok(name)
    if not TAG.match(tag): raise HTTPException(400, "Bad tag.")
    if not DOCKERFILE.match(dockerfile): raise HTTPException(400, "The Dockerfile path must be relative, inside the build context.")
    try: buildargs = _env_ok({str(k): str(v) for k, v in json.loads(args).items()})
    except (ValueError, AttributeError): raise HTTPException(400, "Build arguments must be a JSON object.")
    fd, path = tempfile.mkstemp(prefix="context-", suffix=".tar")
    size = 0
    try:
        with os.fdopen(fd, "wb") as f:
            async for chunk in req.stream():
                size += len(chunk)
                if size > CONTEXT_MAX: raise HTTPException(413, f"The build context is over {CONTEXT_MAX // 2**20} MB.")
                f.write(chunk)
    except BaseException:
        os.unlink(path); raise
    return StreamingResponse(_build(name, tag, dockerfile, buildargs, nocache, path, size, job), media_type="application/x-ndjson")

def _build(name, tag, dockerfile, buildargs, nocache, path, size, job):
    image, c, timer, timed = f"axor-app/{name}:{tag}", None, None, []
    try:
        if not BUILDS.acquire(blocking=False):
            yield line(log="Waiting for another build to finish…\n")
            BUILDS.acquire()
        try:
            if job in CANCELLED: yield line(error="Cancelled."); return
            params = {"t": image, "dockerfile": dockerfile, "rm": 1, "forcerm": 1, "version": "1", "nocache": int(nocache),
                      "labels": json.dumps({LABEL: "image", "axor.app": name, "axor.run": tag}), "buildargs": json.dumps(buildargs),
                      "memory": MAX_MEMORY * 2**20, "memswap": MAX_MEMORY * 2**20}
            with open(path, "rb") as f:
                c, res = E.open("POST", "/build", params, body=f, headers={"Content-Type": "application/x-tar", "Content-Length": str(size)},
                                timeout=BUILD_SECONDS)
            _job(job, lambda: _shut(c))
            timer = threading.Timer(BUILD_SECONDS, lambda: (timed.append(1), _shut(c))); timer.start()
            iid, err = None, None
            try:
                for raw in res:  # one JSON message per line
                    try: m = json.loads(raw)
                    except ValueError: continue
                    if m.get("error"): err = m["error"]
                    elif "stream" in m: yield line(log=m["stream"])
                    elif (m.get("aux") or {}).get("ID"): iid = m["aux"]["ID"]
                    elif m.get("status") and not m.get("progressDetail"): yield line(log=f"{m['status']} {m.get('id', '')}".rstrip() + "\n")
            except OSError:
                err = err or "The build was interrupted."
            if job in CANCELLED: yield line(error="Cancelled."); return
            if timed: yield line(error=f"The build took longer than {BUILD_SECONDS // 60} minutes."); return
            if err: yield line(error=err.strip()); return
            i = E.get(f"/images/{urllib.parse.quote(image, safe='/:')}/json")
            if not i: yield line(error="The build finished without an image."); return
            yield line(done=True, image=image, id=iid or i["Id"], size=i.get("Size", 0))
        finally:
            BUILDS.release()
    except EngineError as e:
        yield line(error=str(e))
    finally:
        if timer: timer.cancel()
        if c: c.close()
        os.unlink(path); _done(job)

class TestIn(BaseModel):
    app: str
    image: str = Field(..., max_length=200)
    command: str = Field(..., min_length=1, max_length=4000)
    env: dict[str, str] = {}
    timeout: int = Field(600, ge=10, le=7200)
    memory_mb: int = 1024
    cpus: float = 1.0
    job: str = Field("", max_length=64)

@app.post("/test", dependencies=[Depends(auth)])
def test(t: TestIn):
    """Runs the command (with sh -c) in a throwaway container of a built image; answers with its output and exit code."""
    _app_ok(t.app); _env_ok(t.env); _limits(t.memory_mb, t.cpus)
    engine(lambda: (network(), _own_image(t.app, t.image)))
    return StreamingResponse(_test(t), media_type="application/x-ndjson")

def _test(t):
    cid, c, timer, timed = None, None, None, []
    try:
        cfg = hardened(t.app, t.image, "test", t.env, t.memory_mb, t.cpus, run=t.image.rsplit(":", 1)[-1], entrypoint=["sh", "-c"], cmd=[t.command])
        cid = E.call("POST", "/containers/create", {"name": f"axor-{t.app}-test-{secrets.token_hex(3)}"}, body=cfg)["Id"]
        kill = lambda: _quiet(lambda: E.call("POST", f"/containers/{cid}/kill"))
        _job(t.job, kill)
        if t.job in CANCELLED: yield line(error="Cancelled."); return
        E.call("POST", f"/containers/{cid}/start")
        timer = threading.Timer(t.timeout, lambda: (timed.append(1), kill())); timer.start()
        c, res = E.open("GET", f"/containers/{cid}/logs", {"follow": 1, "stdout": 1, "stderr": 1}, timeout=t.timeout + 60)
        try:
            for text in _frames(res): yield line(log=text)
        except OSError: pass
        code = E.call("POST", f"/containers/{cid}/wait", timeout=60).get("StatusCode")
        if t.job in CANCELLED: yield line(error="Cancelled.")
        elif timed: yield line(error=f"The tests took longer than {t.timeout} seconds.", exit=code)
        else: yield line(done=True, exit=code)
    except EngineError as e:
        yield line(error=str(e))
    finally:
        if timer: timer.cancel()
        if c: c.close()
        if cid: _quiet(lambda: E.call("DELETE", f"/containers/{cid}", {"force": 1, "v": 1}))
        _done(t.job)

class DeployIn(BaseModel):
    app: str
    image: str = Field(..., max_length=200)
    port: int = Field(..., ge=1, le=65535)        # the port the app listens on inside its container
    host_port: int                                # where it's published on the server, within RUNNER_PORTS
    env: dict[str, str] = {}
    health: str = Field("", max_length=200)       # an HTTP path that answers 2xx/3xx once the app is up, or "" to only check it stays up
    health_timeout: int = Field(60, ge=5, le=600)
    memory_mb: int = 512
    cpus: float = 1.0
    volume: str = Field("", max_length=200)       # a path in the container for the app's named volume, or ""
    job: str = Field("", max_length=64)

@app.post("/deploy", dependencies=[Depends(auth)])
def deploy(d: DeployIn):
    _app_ok(d.app); _env_ok(d.env); _limits(d.memory_mb, d.cpus)
    if d.host_port not in PORTS: raise HTTPException(400, f"The host port must be in {PORTS.start}-{PORTS.stop - 1} on this server.")
    if d.health and not PATH.match(d.health): raise HTTPException(400, "The health check path must start with / (for example /health).")
    if d.volume and (not PATH.match(d.volume) or d.volume == "/"): raise HTTPException(400, "The volume path must be a folder such as /data.")
    def pre():
        network(); _own_image(d.app, d.image)
        owner = next((c["Labels"].get("axor.app") for c in E.call("GET", "/containers/json", {"all": 1, "filters": _flt(**{LABEL: "app", "axor.port": d.host_port})})), None)
        if owner and owner != d.app: raise HTTPException(409, f"Port {d.host_port} is already used by {owner}.")
    engine(pre)
    return StreamingResponse(_deploy(d), media_type="application/x-ndjson")

def _deploy(d):
    name, prev, old = f"axor-{d.app}", f"axor-{d.app}-prev", None
    lock = _lock(d.app)
    if not lock.acquire(blocking=False):
        yield line(log="Waiting for another deploy of this app to finish…\n")
        lock.acquire()
    try:
        _remove(prev)  # left over from an interrupted deploy
        old = E.get(f"/containers/{name}/json")
        if old and not _ours(old):
            yield line(error=f"A container named {name} exists that the runner didn't create. Rename or remove it first."); return
        running = bool(old and old["State"]["Running"])
        if old:
            yield line(log=f"Stopping the running version ({old['Config']['Image']})…\n" if running else "Setting the stopped version aside…\n")
            if running: E.call("POST", f"/containers/{name}/stop", {"t": 20}, timeout=60)
            E.call("POST", f"/containers/{name}/rename", {"name": prev})
        cid, ok, why = None, False, ""
        try:
            cfg = hardened(d.app, d.image, "app", d.env, d.memory_mb, d.cpus, run=d.image.rsplit(":", 1)[-1], port=d.port,
                           host_port=d.host_port, volume=d.volume)
            cid = E.call("POST", "/containers/create", {"name": name}, body=cfg)["Id"]
            E.call("POST", f"/containers/{cid}/start")
            yield line(log=f"Started {d.image} on port {d.host_port}; checking health…\n")
            ok, why = yield from _healthy(d, cid)
        except EngineError as e:
            why = str(e)
        if ok:
            if old: _quiet(lambda: _remove(prev))
            yield line(log="Healthy.\n")
            yield line(done=True, container=cid[:12], image=d.image, host_port=d.host_port); return
        yield line(log=f"The new version failed: {why}\n")
        if cid:
            tail = _quiet(lambda: _tail(cid, 40))
            if tail: yield line(log="--- its last output ---\n" + tail + ("" if tail.endswith("\n") else "\n"))
            _quiet(lambda: E.call("DELETE", f"/containers/{cid}", {"force": 1, "v": 1}))
        if old:
            E.call("POST", f"/containers/{prev}/rename", {"name": name})
            if running: E.call("POST", f"/containers/{name}/start")
            yield line(log="Rolled back: the previous version is running again.\n" if running else "Rolled back to the previous container.\n")
        yield line(error=why, rolled_back=bool(old))
    except EngineError as e:
        yield line(error=str(e), rolled_back=False)
    finally:
        lock.release(); _done(d.job)

CHECK = """import sys, time, urllib.request, urllib.error
url, end, last = sys.argv[1], time.time() + float(sys.argv[2]), "no answer"
while time.time() < end:
    try:
        with urllib.request.urlopen(url, timeout=5) as r: print("HTTP", r.status); sys.exit(0)
    except urllib.error.HTTPError as e: last = f"HTTP {e.code}"
    except Exception as e: last = str(getattr(e, "reason", e))
    time.sleep(2)
print(last); sys.exit(1)
"""

def _healthy(d, cid):
    """Generator: yields log lines, returns (ok, why). Fails as soon as the app exits or restarts."""
    end, chk = time.time() + d.health_timeout, None
    try:
        if d.health:
            url = f"http://{d.app}:{d.port}{d.health}"
            cfg = hardened(d.app, check_image(), "check", {}, 128, 0.5, entrypoint=["python", "-c", CHECK], cmd=[url, str(d.health_timeout)])
            chk = E.call("POST", "/containers/create", {"name": f"axor-{d.app}-check-{secrets.token_hex(3)}"}, body=cfg)["Id"]
            E.call("POST", f"/containers/{chk}/start")
            yield line(log=f"Waiting for {d.health} to answer (up to {d.health_timeout}s)…\n")
        else:
            end = time.time() + min(10, d.health_timeout)  # no health path: it must stay up this long
        while True:
            if d.job in CANCELLED: return False, "Cancelled."
            s = E.call("GET", f"/containers/{cid}/json")
            st = s["State"]
            if st["Restarting"] or s.get("RestartCount"):  # once Docker has restarted it, the exit code shown is the new run's
                return False, "the app crashed on start (Docker had to restart it)"
            if not st["Running"]: return False, f"the app exited on start (code {st['ExitCode']})"
            if chk:
                st = E.call("GET", f"/containers/{chk}/json")["State"]
                if not st["Running"]:
                    said = (_tail(chk, 5) or "").strip().splitlines()
                    if st["ExitCode"] == 0: return True, ""
                    return False, f"{d.health} didn't answer in {d.health_timeout}s ({said[-1] if said else 'no answer'})"
            elif time.time() >= end:
                return True, ""
            if time.time() > end + 15: return False, "the health check didn't finish"
            time.sleep(1)
    finally:
        if chk: _quiet(lambda: E.call("DELETE", f"/containers/{chk}", {"force": 1}))

def _tail(cid, n):
    c, res = E.open("GET", f"/containers/{cid}/logs", {"stdout": 1, "stderr": 1, "tail": n}, timeout=20)
    try: return "".join(_frames(res))
    finally: c.close()

def _app_container(name):
    c = E.get(f"/containers/axor-{_app_ok(name)}/json")
    if not c or not _ours(c): raise HTTPException(404, f"{name} isn't deployed.")
    return c

@app.get("/apps", dependencies=[Depends(auth)])
def apps():
    return engine(lambda: [_app_out(c) for c in _apps()])

@app.get("/apps/{name}/images", dependencies=[Depends(auth)])
def images(name: str):
    _app_ok(name)
    def go():
        used = {c["ImageID"] for c in E.call("GET", "/containers/json", {"all": 1, "filters": _flt(**{"axor.app": name})})}
        return [{"image": next((t for t in i.get("RepoTags") or [] if t.startswith(f"axor-app/{name}:")), i["Id"]), "id": i["Id"],
                 "run": (i.get("Labels") or {}).get("axor.run", ""), "created": i["Created"], "size": i.get("Size", 0), "in_use": i["Id"] in used}
                for i in _images(name)]
    return engine(go)

@app.get("/apps/{name}/logs", dependencies=[Depends(auth)])
def app_logs(name: str, tail: int = 300):
    return engine(lambda: {"text": _tail(_app_container(name)["Id"], max(1, min(int(tail), 5000)))[-400_000:]})

class PruneIn(BaseModel):
    keep: list[str] = Field([], max_length=200)  # image names to keep: AXoR keeps the last few successful runs' images

@app.post("/apps/{name}/prune", dependencies=[Depends(auth)])  # before /apps/{name}/{action}, which would catch it
def prune(name: str, b: PruneIn):
    _app_ok(name)
    def go():
        with _lock(name): return {"deleted": _prune(name, set(b.keep))}
    return engine(go)

@app.post("/apps/{name}/{action}", dependencies=[Depends(auth)])
def app_action(name: str, action: str):
    if action not in ("start", "stop", "restart"): raise HTTPException(400, "Unknown action.")
    def go():
        with _lock(name):
            c = _app_container(name)
            E.call("POST", f"/containers/{c['Id']}/{action}", {"t": 20} if action != "start" else None, timeout=60)
            return {"ok": True, "state": E.call("GET", f"/containers/{c['Id']}/json")["State"]["Status"]}
    return engine(go)

@app.delete("/apps/{name}", dependencies=[Depends(auth)])
def remove_app(name: str, volume: bool = False):
    """Removes the app's containers and images, and its volume if asked."""
    _app_ok(name)
    def go():
        with _lock(name):
            gone = {"containers": 0, "images": 0, "volume": False}
            for c in E.call("GET", "/containers/json", {"all": 1, "filters": _flt(**{LABEL: None, "axor.app": name})}):
                E.call("DELETE", f"/containers/{c['Id']}", {"force": 1, "v": 1}); gone["containers"] += 1
            for i in _images(name):
                _quiet(lambda: E.call("DELETE", f"/images/{i['Id']}", {"force": 1})); gone["images"] += 1
            v = E.get(f"/volumes/axor-app-{name}")
            if volume and v and (v.get("Labels") or {}).get(LABEL):
                E.call("DELETE", f"/volumes/axor-app-{name}"); gone["volume"] = True
            return gone
    return engine(go)

@app.post("/jobs/{job}/cancel", dependencies=[Depends(auth)])
def cancel(job: str):
    CANCELLED.add(job)
    fn = JOBS.get(job)
    if fn: fn()
    return {"ok": True, "running": bool(fn)}
