"""The sandbox: model-written code runs in a throwaway Kubernetes pod (namespace axor-sandbox), never in AXoR itself.

- One pod per run: the runner (axor/sandbox: Python, git, Go, Node and the database clients; uid 1000, no privileges, no service
  account token) plus PostgreSQL and/or ClickHouse as sidecars on localhost when the run asks for them. The files arrive in a
  ConfigMap and are unpacked into /work (/repo is an empty, writable directory, as Ridges mounts the task's repository there);
  the command runs in /work with a time limit; the pod and the ConfigMap are deleted when it ends.
- No internet: the namespace's NetworkPolicy (k8s/base/56-sandbox.yaml) lets the pods reach cluster DNS and AXoR's model proxy
  (port 8091 on the web pod), nothing else.
- The proxy speaks Ridges' sandbox protocol: $SANDBOX_PROXY_URL/api/v1/chat/completions and /api/v1/embeddings, forwarded to
  OpenRouter with the administrator's key. Every run has a dollar cap and, like Ridges, a cap per problem: POST
  $SANDBOX_PROXY_URL/window {"cap": 0.29} starts a problem, GET $SANDBOX_PROXY_URL/usage reports what it spent.
- Internet, for teams that have it on (run(internet=True)): the pod is labelled axor.dev/internet=on, which lets it reach the
  egress proxy (egress_proxy.py, k8s/base/57-egress.yaml) and nothing more; HTTP(S)_PROXY carries a token of the run's own,
  registered with the proxy for the run's length. It runs under gVisor (RuntimeClass "gvisor", k8s/install-gvisor.sh), and
  files that look like secrets (.env, keys, credentials) are held back. The proxy keeps out internal addresses, caps bytes
  each way, and reports every host reached; the result carries that record as "net". Runs with internet are refused while
  the proxy or gVisor isn't ready, never started without them.
- Checkpoints, so long work survives a restart, a timeout or a lost pod: a run keeps its progress in $AXOR_STATE
  (/work/.axor/state) and saves it with `python3 .axor/checkpoint.py` whenever it likes; the runner saves it once more when
  the command ends, timed out or not. The save goes through the model proxy ($SANDBOX_PROXY_URL/checkpoint, the run's own
  token), at most CKPT_BYTES, to run(checkpoint=…)'s save function, so it's in AXoR the moment it's made, even if the pod
  dies a second later. The next run given that checkpoint starts with it unpacked in $AXOR_STATE and AXOR_RESUMED=1.
"""
import hashlib, ipaddress, json, logging, os, re, secrets, socket, threading, time, urllib.error, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .kube import KubeError
from .llm import OPENROUTER_URL

log = logging.getLogger("sandbox")
NS = os.getenv("SANDBOX_NAMESPACE", "axor-sandbox")
IMAGE = os.getenv("SANDBOX_IMAGE", "")
PULL = os.getenv("SANDBOX_IMAGE_PULL", "Never")  # deploy.sh loads axor/sandbox into k3s, like AXoR's own images
PG_IMAGE = os.getenv("SANDBOX_POSTGRES_IMAGE", "postgres:16-alpine")
CH_IMAGE = os.getenv("SANDBOX_CLICKHOUSE_IMAGE", "clickhouse/clickhouse-server:24.8")
PROXY_PORT = int(os.getenv("SANDBOX_PROXY_PORT", "8091") or 0)
PROXY_BIND = os.getenv("SANDBOX_PROXY_BIND", "0.0.0.0")  # in the web pod; the NetworkPolicies decide who reaches it
PROXY_URL = os.getenv("SANDBOX_PROXY_URL", f"http://web.axor.svc.cluster.local:{PROXY_PORT}").rstrip("/")
AT_ONCE = max(1, int(os.getenv("SANDBOX_MAX_RUNS", "2")))
SERVICES = ("postgres", "clickhouse")
# A run's size (AEF X2, D-032 Proposed): CPUs, memory, and how many of the AT_ONCE slots it takes. M is what every run had before
# sizes existed and is what a run gets when it names none. L is the namespace's ceiling per container (56-sandbox.yaml's LimitRange).
SIZES = {"S": ("1", "2Gi", 1), "M": ("2", "4Gi", 1), "L": ("4", "8Gi", 2)}
MAX_TIMEOUT = 1800
INPUT_BYTES = 900_000         # a ConfigMap holds 1 MiB
# a run's files go in up to INPUT_CHUNKS ConfigMaps (one projected volume): the namespace's quota is 30 ConfigMaps (56-sandbox.yaml),
# one of them the cluster's CA, so runs at once × chunks stays under it
INPUT_CHUNKS = max(1, min(4, 29 // AT_ONCE))
CODE_EXT = re.compile(r"\.(py|pyi|js|mjs|ts|tsx|jsx|rs|go|java|kt|c|h|cc|cpp|hpp|rb|php|sh|bash|toml|cfg|ini|ya?ml|json|md|rst|txt|sql|proto|html|css)$", re.I)
OUTPUT_CHARS = 60_000
PER_PROBLEM = 0.29            # Ridges' RIDGES_MAX_COST_USD at the time of writing
CKPT_BYTES = 400_000          # a checkpoint, base64 of a .tar.gz of $AXOR_STATE: it goes back in as an input file, so it must leave room
CKPT_FILE = ".axor/checkpoint.b64"
FILES = Path(__file__).parent / "sandbox_files"  # shipped into every run under .axor/
EGRESS_URL = os.getenv("EGRESS_URL", "http://egress.axor-egress.svc.cluster.local:3129").rstrip("/")
EGRESS_PROXY = os.getenv("EGRESS_PROXY", "egress.axor-egress.svc.cluster.local:3128")
EGRESS_SECRET = os.getenv("EGRESS_SECRET", "")
INTERNET_RUNTIME = os.getenv("SANDBOX_INTERNET_RUNTIME", "gvisor")  # "" runs them on runc, by an administrator's explicit choice only
NET_UP_MB = float(os.getenv("SANDBOX_NET_UP_MB", "50"))      # bytes a run may send out: what it could leak
NET_DOWN_MB = float(os.getenv("SANDBOX_NET_DOWN_MB", "5000"))
NO_PROXY = "127.0.0.1,localhost,.svc,.cluster.local"           # the model proxy and the sidecars stay direct
# With SANDBOX_BY_ADDRESS=1 a pod is told where the run port and the egress proxy are by ADDRESS, resolved here in AXoR, so a run
# needs no DNS at all. That is the product's half of closing DNS as a way out of a run (measured 2026-11-13: the cluster's DNS
# answers every run for public names, so a string chosen inside a run reaches the upstream resolver); the other half is the
# sandbox policy without its DNS rule, which is a k8s/base change and the Owner's decision. Off by default: pods get names, as before.
BY_ADDRESS = os.getenv("SANDBOX_BY_ADDRESS", "0") == "1"
SECRET_PATH = re.compile(r"(^|/)(\.env(\.[^/]*)?|\.netrc|\.npmrc|\.pypirc|\.git-credentials|\.ssh/.*|id_(rsa|dsa|ecdsa|ed25519)[^/]*|"
                         r"[^/]*credentials[^/]*|[^/]*secrets?(\.[a-z]+)?|[^/]*\.(pem|key|p12|pfx|kdbx|keystore|jks))$", re.I)

RUNNER = r"""set -u
python3 - <<'PY'
import json, pathlib
m = json.load(open("/input/manifest.json"))
for key, path in m.items():
    p = (pathlib.Path("/work") / path).resolve()
    if not str(p).startswith("/work/"): continue
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(open(f"/input/{key}", "rb").read())
    if p.suffix in (".sh", ".py"): p.chmod(0o755)
PY
mkdir -p "$AXOR_STATE"
if [ -s /work/.axor/checkpoint.b64 ]; then
  if base64 -d /work/.axor/checkpoint.b64 | tar -xz -C "$AXOR_STATE"; then export AXOR_RESUMED=1; echo "@@AXOR-RESUMED from a checkpoint"; fi
  rm -f /work/.axor/checkpoint.b64
fi
echo "@@AXOR-START $(date -u +%H:%M:%S)"
timeout -k 5 "$AXOR_TIMEOUT" bash -c "$AXOR_COMMAND"
code=$?
[ "$code" = 124 ] && echo "@@AXOR-TIMEOUT the command ran past ${AXOR_TIMEOUT} s"
[ -n "$(ls -A "$AXOR_STATE" 2>/dev/null)" ] && python3 /work/.axor/checkpoint.py --final
timeout -k 2 20 python3 - <<'PY' 2>/dev/null || true
import json, os, re, subprocess
found = []
for root in ("/work", "/repo"):
    for d, dirs, _ in os.walk(root):
        if ".git" in dirs:
            def g(*a, d=d):
                try: return subprocess.run(["git", "-C", d, *a], capture_output=True, text=True, timeout=10).stdout.strip()
                except Exception: return ""
            head = g("rev-parse", "HEAD")
            if re.fullmatch(r"[0-9a-f]{40,64}", head):
                found.append({"path": d, "url": re.sub(r"//[^/@]*@", "//", g("config", "--get", "remote.origin.url"))[:300], "commit": head,
                              "ref": g("rev-parse", "--abbrev-ref", "HEAD")[:120], "dirty": bool(g("status", "--porcelain", "--untracked-files=no"))})
            dirs[:] = []
        elif d.count("/") - root.count("/") >= 4: dirs[:] = []
        else: dirs[:] = [x for x in dirs if x not in (".axor", "node_modules", ".venv", "venv", "__pycache__", "site-packages")]
        if len(found) >= 20: break
print("@@AXOR-SOURCE " + json.dumps(found[:20]))
PY
echo "@@AXOR-EXIT $code"
"""
SOURCE_LINE = re.compile(r"^@@AXOR-SOURCE (\[.*\])\n@@AXOR-EXIT \d+\s*\Z", re.M)


def source_of(output):
    """The run's source record: the git checkouts found under /work and /repo when the command ended, [{path, url, commit, ref,
    dirty}]. The RUNNER reads them from git itself and always prints the line (an empty list when there are none), right before
    its exit line; credentials in a remote's address are cut there. Only that position counts: a marker the command printed
    earlier, or anything printed after the runner's line, gives no record."""
    m = SOURCE_LINE.findall(output or "")
    if not m: return []
    try: rows = json.loads(m[-1].strip())
    except ValueError: return []
    out = []
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, dict) and re.fullmatch(r"[0-9a-f]{40,64}", str(r.get("commit") or "")):
            out.append({"path": str(r.get("path") or "")[:200], "url": str(r.get("url") or "")[:300], "commit": r["commit"],
                        "ref": str(r.get("ref") or "")[:120], "dirty": bool(r.get("dirty"))})
    return out[:20]

# ---- what a network or git command's own output says happened (2026-11-13, consolidated directive C1). One classifier for the
# readiness probes (mission_ops) and the register's sandbox feed (orchestrator), kept here because this module imports neither.
READINESS_USER = "AXoR readiness check"   # mw_sbx.by_user of AXoR's own check runs: a measurement of the environment, not team work
REACH = {
    "ok": "It worked.",
    "no_executable": "The program isn't in the run's image (nothing was attempted on the network).",
    "private": "The repository asked for a login: it is private, or it doesn't exist. Runs carry no repository credentials. Git and the network worked.",
    "credentials": "The server rejected the credentials it was given (or required some for a page).",
    "policy": "AXoR's egress proxy refused the destination: not a public address, not an allowed port, or not on this run's list.",
    "no_internet": "The run has no internet: its team's switch is off, or its proxy token had ended.",
    "dns": "The name didn't resolve (the command's own lookup: the run had no proxy).",
    "connection": "The destination couldn't be connected, or the connection was cut or timed out (through the proxy this includes a name it couldn't resolve).",
    "timeout": "The command ran past its time limit.",
    "failed": "The command ran and failed for a reason of its own.",
}
_REACH_RULES = (  # first match wins; the most specific statements first
    ("no_executable", r"(?:^|\n)(?:bash: (?:line \d+: )?)?[\w./-]+: (?:command )?not found|exec: \"[^\"]+\": executable file not found"),
    ("no_internet", r"response 407|HTTP code 407 from proxy"),
    ("policy", r"response 403|HTTP code 403 from proxy|response 429|HTTP code 429 from proxy"),
    ("private", r"could not read Username|terminal prompts disabled|Repository not found|repository '[^']+' not found"),
    ("credentials", r"Authentication failed|Invalid username or password|HTTP Basic: Access denied|The requested URL returned error: 40[13]|\b401 Unauthorized\b"),
    ("dns", r"Could not resolve host|Could not resolve proxy|Name or service not known|Temporary failure in name resolution|getaddrinfo"),
    ("connection", r"Connection refused|Failed to connect|Connection timed out|Operation timed out|Connection reset|Empty reply from server|"
                   r"(?:response|HTTP code) 50[234]|SSL_ERROR|TLS connect error|unexpected disconnect|early EOF|RPC failed"),
)
_REACH_RES = [(c, re.compile(rx, re.I)) for c, rx in _REACH_RULES]


def reach_class(exit_code, output, status=None):
    """One of REACH's keys for a finished command that used git or the network, from its exit code and what it printed. A clean
    exit is "ok" whatever it printed. Through the egress proxy a name that doesn't resolve and a far end that can't be connected
    both reach the command as "502 from proxy": that reads "connection" here, and the run's own network record (net.refused)
    carries the proxy's exact reason. "dns" is what the command's own resolver said, which happens only without the proxy."""
    out = output or ""
    if status == "timeout" or exit_code == 124 or "@@AXOR-TIMEOUT" in out: return "timeout"
    if exit_code == 0 and status in (None, "done"): return "ok"
    if exit_code == 127: return "no_executable"
    for cls, rx in _REACH_RES:
        if rx.search(out): return cls
    return "failed"


class SandboxError(Exception):
    """A run couldn't start or finish; the message is safe to show."""


_ADDR = {}  # service name -> (address, when it was resolved)


def _address(host):
    """A service name's address, resolved in AXoR and kept a minute; the host itself when it already is an address. A name that
    doesn't resolve raises: a pod that can't be told where its endpoint is isn't started."""
    try: ipaddress.ip_address(host); return host
    except ValueError: pass
    hit = _ADDR.get(host)
    if hit and time.time() - hit[1] < 60: return hit[0]
    try: addr = socket.gethostbyname(host)
    except OSError as e: raise SandboxError(f"AXoR couldn't find the address of {host} for the run ({e}).")
    _ADDR[host] = (addr, time.time())
    return addr


def endpoints():
    """Where a pod reaches AXoR's run port and the egress proxy, and what it must never send through the proxy:
    {"proxy_url", "egress_proxy", "no_proxy", "by_address"}. The one place the sandbox's pods take them from, and the interface for
    the VM runner's pod (runner.py) to take them from too. Asked once per pod, when its specification is made.
    by_address False (the default): the configured names, as always. True (SANDBOX_BY_ADDRESS=1): both services by address, and the
    run port's address in no_proxy, so a program that honours the proxy variables still calls the run port directly."""
    if not BY_ADDRESS: return {"proxy_url": PROXY_URL, "egress_proxy": EGRESS_PROXY, "no_proxy": NO_PROXY, "by_address": False}
    u = urllib.parse.urlsplit(PROXY_URL)
    run_port = _address(u.hostname or "")
    host, _, port = EGRESS_PROXY.rpartition(":")
    return {"proxy_url": f"{u.scheme}://{run_port}{':%d' % u.port if u.port else ''}{u.path}".rstrip("/"), "egress_proxy": f"{_address(host)}:{port}",
            "no_proxy": f"{NO_PROXY},{run_port}", "by_address": True}

class Proxy:
    """Ridges' inference protocol for sandbox pods, on its own port so they reach nothing else of AXoR's."""
    def __init__(self, key_fn):
        self.key_fn, self.runs, self.lock, self.server = key_fn, {}, threading.Lock(), None

    def start(self, port=PROXY_PORT):
        if self.server or not port: return
        proxy = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def _send(self, code, body):
                raw = json.dumps(body).encode()
                self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(raw)))
                self.end_headers(); self.wfile.write(raw)
            def do_GET(self): self._send(*proxy.handle("GET", self.path, None))
            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                if n > 8_000_000: return self._send(413, {"error": {"message": "The request is too large.", "code": 413}})
                self._send(*proxy.handle("POST", self.path, self.rfile.read(n) if n else b""))

        try: self.server = ThreadingHTTPServer((PROXY_BIND, port), H)
        except OSError as e:
            log.warning("sandbox proxy: can't listen on %s: %s", port, e)
            return
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True, name="sandbox-proxy").start()
        log.info("sandbox proxy listening on %s", port)

    def open(self, cap, hook=None, save=None):
        token = secrets.token_urlsafe(24)
        with self.lock: self.runs[token] = {"cap": cap, "spent": 0.0, "start": 0.0, "window": None, "calls": 0, "tokens": 0, "hook": hook,
                                            "save": save, "saved": 0, "saves": 0}
        return token

    def close(self, token):
        with self.lock: return self.runs.pop(token, None) or {"spent": 0.0, "calls": 0, "tokens": 0, "saved": 0, "saves": 0}

    def handle(self, method, path, raw):
        if path == "/health": return 200, {"ok": True}
        m = re.match(r"^/t/([A-Za-z0-9_-]{20,64})(/.*)$", path.split("?", 1)[0])
        run = self.runs.get(m.group(1)) if m else None
        if not run: return 404, {"error": {"message": "Unknown or finished sandbox run.", "code": 404}}
        sub = m.group(2)
        usage = lambda: {"spent_usd": round(run["spent"], 6), "cap_usd": run["cap"], "calls": run["calls"], "tokens": run["tokens"],
                         "problem_spent_usd": round(run["spent"] - run["start"], 6), "problem_cap_usd": run["window"]}
        if sub == "/usage" and method == "GET": return 200, usage()
        try: body = json.loads(raw or b"{}") if method == "POST" else {}
        except ValueError: return 400, {"error": {"message": "The body isn't JSON.", "code": 400}}
        if not isinstance(body, dict): return 400, {"error": {"message": "The body must be a JSON object.", "code": 400}}
        if sub.startswith("/rlm/") and run.get("hook"): return run["hook"](method, sub, body)  # the RLM's REPL (rlm.py)
        if sub == "/checkpoint" and method == "POST":  # .axor/checkpoint.py: the run's progress, kept in AXoR right away
            data = body.get("data")
            if not run.get("save"): return 409, {"error": {"message": "This run has no checkpoint store: only a task's runs keep one.", "code": 409}}
            if not isinstance(data, str) or not re.fullmatch(r"[A-Za-z0-9+/=\s]*", data): return 400, {"error": {"message": "data must be base64.", "code": 400}}
            data = re.sub(r"\s", "", data)
            if len(data) > CKPT_BYTES:
                return 413, {"error": {"message": f"The checkpoint is {len(data) // 1000} kB; at most {CKPT_BYTES // 1000} kB is kept. Keep only what resuming needs.", "code": 413}}
            try: run["save"](data)
            except Exception as e:  # noqa: BLE001 - the run keeps going without it
                log.warning("sandbox checkpoint: %s", e)
                return 500, {"error": {"message": "AXoR couldn't keep the checkpoint.", "code": 500}}
            with self.lock: run["saved"], run["saves"] = len(data), run["saves"] + 1
            return 200, {"saved_bytes": len(data), "saves": run["saves"]}
        if sub == "/window" and method == "POST":
            cap = body.get("cap")
            with self.lock: run["start"], run["window"] = run["spent"], float(cap) if isinstance(cap, (int, float)) and cap > 0 else None
            return 200, usage()
        target = {"/api/v1/chat/completions": "/chat/completions", "/api/v1/embeddings": "/embeddings"}.get(sub)
        if not target or method != "POST": return 404, {"error": {"message": f"No such endpoint: {sub}", "code": 404}}
        if run["spent"] >= run["cap"] or (run["window"] and run["spent"] - run["start"] >= run["window"]):
            return 402, {"error": {"message": "The inference budget is spent: stop and return the best patch you have.", "code": 402, "type": "budget_exceeded"}}
        key = self.key_fn()
        if not key: return 503, {"error": {"message": "No OpenRouter key is connected in AXoR (Agents → Models), so the sandbox has no inference.", "code": 503}}
        body["stream"] = False  # one JSON answer: the cost is in it
        if target == "/chat/completions": body["usage"] = {"include": True}
        code, out = self._forward(target, body, key)
        u = out.get("usage") if isinstance(out, dict) else None
        if isinstance(u, dict):
            toks = int(u.get("total_tokens") or 0)
            cost = u.get("cost") if isinstance(u.get("cost"), (int, float)) else toks * 2e-6  # no price given: count 2 USD per million
            with self.lock: run["spent"] += cost; run["tokens"] += toks
        with self.lock: run["calls"] += 1
        return code, out

    @staticmethod
    def _forward(path, body, key):
        req = urllib.request.Request(OPENROUTER_URL + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "X-Title": "AXoR sandbox"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r: return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try: return e.code, json.loads(e.read() or b"{}")
            except ValueError: return e.code, {"error": {"message": f"OpenRouter answered {e.code}.", "code": e.code}}
        except (OSError, ValueError) as e:
            return 502, {"error": {"message": f"Couldn't reach OpenRouter: {getattr(e, 'reason', e)}", "code": 502}}

class Egress:
    """The egress proxy's control side (egress_proxy.py): is internet available, and the record of each run."""
    def __init__(self, kube):
        self.kube, self._state, self._checked = kube, {"ready": False, "why": "Not checked yet.", "exit": "", "gvisor": False}, 0.0

    def _call(self, method, path, body=None, timeout=10):
        req = urllib.request.Request(EGRESS_URL + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"X-Egress-Secret": EGRESS_SECRET, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r: return json.loads(r.read() or b"{}")

    def _gvisor(self):
        try: nodes = self.kube.items("/api/v1/nodes")
        except KubeError: return False
        return any((n["metadata"].get("labels") or {}).get("axor.dev/gvisor") == "ready" for n in nodes)

    def status(self, fresh=False):
        """{ready, why, exit ("separate": an exit proxy elsewhere, "server": this server's address), gvisor}."""
        if not fresh and time.time() - self._checked < 30: return self._state
        st = {"ready": False, "why": "", "exit": "", "gvisor": False}
        if os.getenv("SANDBOX_INTERNET", "1") == "0": st["why"] = "Internet for sandbox runs is switched off on this server (SANDBOX_INTERNET=0)."
        elif not self.kube or not self.kube.enabled: st["why"] = "Sandbox internet needs Kubernetes."
        elif not EGRESS_SECRET: st["why"] = "The egress proxy isn't set up (no EGRESS_SECRET): k8s/deploy.sh makes it."
        else:
            try: st["exit"] = self._call("GET", "/health", timeout=2).get("exit", "")
            except (OSError, ValueError) as e: st["why"] = f"The egress proxy doesn't answer ({getattr(e, 'reason', e)}): it may be switched off (kubectl -n axor-egress get deploy egress)."
            st["gvisor"] = bool(INTERNET_RUNTIME) and self._gvisor()
            if not st["why"] and INTERNET_RUNTIME and not st["gvisor"]:
                st["why"] = "gVisor isn't installed on the server yet, and runs with internet only start under it: run k8s/install-gvisor.sh as root."
            st["ready"] = not st["why"]
        self._state, self._checked = st, time.time()
        return st

    def open(self, token, ttl, policy=None):
        """policy (AEF X4): any of hosts, hosts_exact, deny, conns, https_only, up_mb, down_mb for this run; byte caps can only be lowered."""
        body = {"token": token, "up_mb": NET_UP_MB, "down_mb": NET_DOWN_MB, "ttl_s": ttl}
        for k in ("hosts", "hosts_exact", "deny", "conns", "https_only"):
            if (policy or {}).get(k): body[k] = policy[k]
        for k, top in (("up_mb", NET_UP_MB), ("down_mb", NET_DOWN_MB)):
            if (policy or {}).get(k) is not None: body[k] = max(0.001, min(float(policy[k]), top))
        try: self._call("POST", "/runs", body)
        except (OSError, ValueError) as e:
            self._checked = 0.0
            raise SandboxError(f"The egress proxy didn't take the run ({getattr(e, 'reason', e)}), so it can't have internet.")

    def close(self, token):
        try: return self._call("DELETE", f"/runs/{token}")
        except (OSError, ValueError) as e:
            log.warning("egress: couldn't read run %s: %s", hashlib.sha256(token.encode()).hexdigest()[:10], e)  # D-019: never a token prefix
            return {"error": f"The egress proxy's record of this run couldn't be read: {getattr(e, 'reason', e)}"}

def pack(files, command, limit, per_file=INPUT_BYTES):
    """(kept, omitted) for a run whose files are over `limit` bytes: harness files and files the command names always go; then
    code and text before data, smallest first, while they fit. omitted: [(path, bytes)], biggest first. None when the files that
    must go don't fit by themselves."""
    size = {p: len(t.encode()) + len(p) + 16 for p, t in files.items()}  # + the manifest's line for it
    words = {w.strip("'\"").lstrip("./") for w in re.split(r"[\s=;|&<>()]+", command or "") if w}
    must = [p for p in files if p.startswith(".axor/") or p in words or p.rsplit("/", 1)[-1] in words]
    used = sum(size[p] for p in must)
    if used > limit or any(size[p] > per_file for p in must): return None
    kept = {p: files[p] for p in must}
    for p in sorted((p for p in files if p not in kept), key=lambda p: (0 if CODE_EXT.search(p) else 1, size[p], p)):
        if size[p] <= per_file and used + size[p] <= limit:
            kept[p] = files[p]; used += size[p]
    omitted = sorted(((p, len(files[p].encode())) for p in files if p not in kept), key=lambda x: -x[1])
    return kept, omitted


def chunks(data, limit=INPUT_BYTES):
    """The ConfigMaps' data: keys placed biggest first into the first map they fit (`limit` bytes each), manifest.json in the first."""
    out, room = [{"manifest.json": data["manifest.json"]}], [limit - len(data["manifest.json"])]
    for k in sorted((k for k in data if k != "manifest.json"), key=lambda k: -len(data[k].encode())):
        b = len(data[k].encode()) + len(k)
        i = next((i for i, r in enumerate(room) if b <= r), None)
        if i is None: out.append({}); room.append(limit); i = len(out) - 1
        out[i][k] = data[k]; room[i] -= b
    return out


class Slots:
    """The sandbox's run slots, handed out fairly (AEF X2). `total` runs at once, as the semaphore this replaces. When a slot frees,
    it goes to the waiting run whose queue (a mission, say) has the fewest slots in use, earliest first among equals: one mission's
    burst can't hold every slot while another waits. Runs that name no queue share one, which is plain first come, first served:
    exactly the old behaviour. A run of weight 2 (size L) takes two slots; a weight over the total is cut to the total. A run that
    has waited PATIENCE seconds and still doesn't fit is served before anyone behind it, so small runs can't starve a large one."""
    PATIENCE = 60

    def __init__(self, total):
        self.total, self.used, self.by, self.waiting, self.cv, self.n = max(1, int(total)), 0, {}, [], threading.Condition(), 0

    def _next(self):
        if not self.waiting: return None
        first = self.waiting[0]
        if self.used + first[2] > self.total and time.monotonic() - first[3] > self.PATIENCE: return None  # hold the slots that free up for it
        fit = [w for w in self.waiting if self.used + w[2] <= self.total]
        return min(fit, key=lambda w: (self.by.get(w[1], 0), w[0])) if fit else None

    def acquire(self, timeout=None, queue=None, weight=1):
        weight = max(1, min(int(weight), self.total))
        with self.cv:
            self.n += 1
            me = (self.n, queue, weight, time.monotonic())
            self.waiting.append(me)
            end = None if timeout is None else time.monotonic() + timeout
            while self._next() is not me:
                left = None if end is None else end - time.monotonic()
                if left is not None and left <= 0:
                    self.waiting.remove(me); self.cv.notify_all(); return False
                self.cv.wait(min(left, 5) if left is not None else 5)  # wakes by itself too: patience is a matter of time
            self.waiting.remove(me)
            self.used += weight; self.by[queue] = self.by.get(queue, 0) + weight
            self.cv.notify_all()
            return True

    def release(self, queue=None, weight=1):
        weight = max(1, min(int(weight), self.total))
        with self.cv:
            self.used = max(0, self.used - weight)
            left = self.by.get(queue, 0) - weight
            if left > 0: self.by[queue] = left
            else: self.by.pop(queue, None)
            self.cv.notify_all()

    def resize(self, total):
        """The number of slots, changed while runs wait (the Owner's setting, exec_env.py). Runs already going keep theirs."""
        total = max(1, int(total))
        with self.cv:
            if total != self.total: self.total = total; self.cv.notify_all()

    def state(self):
        with self.cv: return {"total": self.total, "used": self.used, "by_queue": dict(self.by), "waiting": [{"queue": q, "weight": w} for _, q, w, _t in self.waiting]}


class Sandbox:
    def __init__(self, kube, key_fn):
        self.kube, self.proxy, self.egress = kube, Proxy(key_fn), Egress(kube)
        self.slots = Slots(AT_ONCE)
        self._ready, self._checked = (False, ""), 0.0
        if self.kube and self.kube.enabled and IMAGE and os.getenv("SANDBOX", "1") != "0":
            self.proxy.start()
            threading.Thread(target=self._sweep, daemon=True, name="sandbox-sweep").start()

    def _sweep(self):
        """At start: runs cut off by a restart left their pod and ConfigMap behind (one web pod runs them all, so none is live)."""
        for kind in ("pods", "configmaps"):
            try:
                for o in self.kube.items(f"/api/v1/namespaces/{NS}/{kind}", {"labelSelector": "app=axor-sandbox"}):
                    self.kube.delete(f"/api/v1/namespaces/{NS}/{kind}/{o['metadata']['name']}", {"gracePeriodSeconds": 0} if kind == "pods" else None)
            except KubeError as e: log.info("sandbox: couldn't sweep %s: %s", kind, e)

    def ready(self):
        """(True, "") when runs can start, else (False, why)."""
        if os.getenv("SANDBOX", "1") == "0": return False, "The sandbox is switched off on this server (SANDBOX=0)."
        if not self.kube or not self.kube.enabled: return False, "The sandbox runs on Kubernetes, and this AXoR isn't on a cluster."
        if not IMAGE: return False, "No sandbox image is set (SANDBOX_IMAGE): k8s/deploy.sh builds and sets it."
        if not self.proxy.server: return False, f"The sandbox's model proxy couldn't listen on port {PROXY_PORT}."
        if time.time() - self._checked > 60:
            try: self.kube.call("GET", f"/api/v1/namespaces/{NS}/pods", {"limit": 1}, timeout=10); self._ready = (True, "")
            except KubeError as e:
                self._ready = (False, f"The {NS} namespace isn't set up for AXoR yet (k8s/deploy.sh does it)." if e.status in (403, 404)
                               else f"Kubernetes didn't answer: {e}")
            self._checked = time.time()
        return self._ready

    @staticmethod
    def harness():
        """Files every run gets under .axor/ (the Ridges-style runner)."""
        return {f".axor/{p.name}": p.read_text() for p in sorted(FILES.glob("*")) if p.is_file()}

    def run(self, files, command, services=(), timeout=600, cap=2.0, label="", cancelled=lambda: False, started=lambda pod: None, hook=None,
            internet=False, checkpoint=None, size=None, queue=None, net=None):
        """Runs command in a fresh pod with files under /work; blocks until it ends. Returns {status, exit, output, seconds,
        cost, calls, pod}: status done (exit 0), failed (another exit), timeout, cancelled or error. hook(method, path, body)
        answers the pod's requests to $SANDBOX_PROXY_URL/rlm/... (rlm.py's REPL). internet: through the egress proxy, under
        gVisor; the result then has "net" (hosts reached, bytes each way, refusals) and "withheld" (secret-looking files).
        "source" (when the run left git checkouts behind): each one's remote address and commit, read by the runner itself.
        checkpoint: {"load": base64 or None, "save": fn(base64)}: the run starts from `load` and saves through `save`; the
        result then has "checkpoint": {"resumed", "saves", "saved_bytes"}.
        size (AEF X2): "S", "M" or "L" (SIZES); None is M, as every run was. queue: whose share of the slots this run counts
        against (Slots). net: the run's egress policy (Egress.open). The result also names the image the pod ran, by id."""
        halted = self.gate() if getattr(self, "gate", None) else None   # an emergency stop of every mission (exec_env.py sets the gate): no caller gets past it
        if halted: raise SandboxError(halted)
        ok, why = self.ready()
        if size is not None and size not in SIZES: raise SandboxError(f"A run's size is one of {', '.join(SIZES)}.")
        weight = SIZES[size or "M"][2]
        if not ok: raise SandboxError(why)
        withheld = []
        if internet:
            st = self.egress.status(fresh=not self.egress.status()["ready"])
            if not st["ready"]: raise SandboxError(f"This team has internet on, but the run can't have it: {st['why']}")
            withheld = sorted(p for p in files if SECRET_PATH.search(p))
            files = {p: t for p, t in files.items() if p not in withheld}
        services = [s for s in SERVICES if s in (services or ())]
        timeout = max(10, min(int(timeout), MAX_TIMEOUT))
        files = {**files, **self.harness()}
        resumed = bool(checkpoint and checkpoint.get("load"))
        if resumed: files[CKPT_FILE] = checkpoint["load"]  # under .axor/: pack() always keeps it
        cap, omitted = INPUT_BYTES * INPUT_CHUNKS - 8192, []
        total = sum(len(t.encode()) + len(p) + 16 for p, t in files.items())
        if total > cap or any(len(t.encode()) > INPUT_BYTES - 1024 for t in files.values()):
            got = pack(files, command, cap - 16384, INPUT_BYTES - 1024)
            if got is None:
                raise SandboxError(f"The files come to {total // 1000} kB, and the ones the command names don't fit by themselves: a run takes at most "
                                   f"{cap // 1000} kB. Narrow it with paths.")
            files, omitted = got
            files[".axor/omitted.txt"] = "Left out of this run: the files came to more than the sandbox's input limit.\n" + \
                                        "".join(f"{b // 1000} kB\t{p}\n" for p, b in omitted[:2000])
        manifest, data = {}, {}
        for i, (path, text) in enumerate(sorted(files.items())):
            manifest[f"f{i}"], data[f"f{i}"] = path, text
        data["manifest.json"] = json.dumps(manifest)
        parts = chunks(data)
        if len(parts) > INPUT_CHUNKS: raise SandboxError(f"The files don't fit the sandbox's {INPUT_CHUNKS} input maps. Narrow it with paths.")
        if not self.slots.acquire(timeout=300, queue=queue, weight=weight): raise SandboxError(f"The sandbox is busy ({self.slots.total} runs at once): try again in a few minutes.")
        if cancelled():  # stopped while it waited for a slot: it never starts (no pod, no token, nothing to clean up)
            self.slots.release(queue=queue, weight=weight)
            return {"status": "cancelled", "exit": None, "output": "", "error": "Stopped before it started.", "seconds": 0.0, "pod": None, "cost": 0.0, "calls": 0,
                    "services": services}
        name = f"sbx-{int(time.time())}-{secrets.token_hex(3)}"
        maps = [name] + [f"{name}-{i}" for i in range(1, len(parts))]
        token = self.proxy.open(cap, hook, (checkpoint or {}).get("save"))
        net_token = secrets.token_urlsafe(24) if internet else None
        t0, status, code, out, err, policy, net, image_id = time.time(), "error", None, "", "", net, None, None
        try:
            if net_token: self.egress.open(net_token, timeout + 900, policy) if policy else self.egress.open(net_token, timeout + 900)
            for cm, part in zip(maps, parts):
                self.kube.call("POST", f"/api/v1/namespaces/{NS}/configmaps",
                               body={"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": cm, "labels": {"app": "axor-sandbox"}}, "data": part})
            self.kube.call("POST", f"/api/v1/namespaces/{NS}/pods", body=self._pod(name, command, services, timeout, token, label, net_token, maps, size))
            started(name)
            status, code, err = self._wait(name, timeout, cancelled)
            try:  # the image the runner actually ran, by id: what a manifest can be checked against
                cs = ((self.kube.get(f"/api/v1/namespaces/{NS}/pods/{name}") or {}).get("status") or {}).get("containerStatuses") or []
                image_id = next((c.get("imageID") for c in cs if c.get("name") == "runner"), None) or None
            except KubeError: pass
            try: out = self.kube.logs(NS, name, "runner", tail=3000, timestamps=False)
            except KubeError as e: out = f"(couldn't read the output: {e})"
            m = re.search(r"^@@AXOR-EXIT (\d+)$", out, re.M)
            if m and status in ("done", "failed"): code = int(m.group(1)); status = "done" if code == 0 else "timeout" if code == 124 else "failed"
        except KubeError as e:
            err = f"Kubernetes refused the run: {e}"
        except SandboxError as e:
            err = str(e)
        finally:
            for kind, n in [("pods", name)] + [("configmaps", cm) for cm in maps]:
                try: self.kube.delete(f"/api/v1/namespaces/{NS}/{kind}/{n}", {"gracePeriodSeconds": 0} if kind == "pods" else None)
                except KubeError as e: log.warning("sandbox: couldn't delete %s %s: %s", kind, n, e)
            use = self.proxy.close(token)
            if net_token: net = self.egress.close(net_token)
            self.slots.release(queue=queue, weight=weight)
        source = source_of(out) if status in ("done", "failed", "timeout") else []
        if omitted: out = f"@@AXOR-PACKED {len(omitted)} file{'s' if len(omitted) != 1 else ''} left out: the input was over the limit (list in .axor/omitted.txt)\n" + out
        if len(out) > OUTPUT_CHARS: out = out[:8000] + f"\n… ({len(out) - OUTPUT_CHARS} characters cut) …\n" + out[-(OUTPUT_CHARS - 8000):]
        return {"status": status, "exit": code, "output": out, "error": err, "seconds": round(time.time() - t0, 1), "pod": name,
                "cost": round(use["spent"], 6), "calls": use["calls"], "services": services, **({"source": source} if source else {}),
                **({"image_id": image_id} if image_id else {}), **({"size": size} if size else {}),
                **({"net": net, "withheld": withheld} if internet else {}), **({"omitted": [p for p, _ in omitted]} if omitted else {}),
                **({"checkpoint": {"resumed": resumed, "saves": use.get("saves", 0), "saved_bytes": use.get("saved", 0)}} if checkpoint else {})}

    def _wait(self, name, timeout, cancelled):
        """(status, exit code, error) once the runner has ended, the time is up or the run is cancelled."""
        deadline, pulled = time.time() + timeout + 300, False  # pulling the database images the first time takes a while
        while True:
            time.sleep(2)
            if cancelled(): return "cancelled", None, "Stopped before it finished."
            try: p = self.kube.get(f"/api/v1/namespaces/{NS}/pods/{name}")
            except KubeError as e: return "error", None, f"Lost track of the run: {e}"
            if not p: return "error", None, "The run's pod disappeared."
            st = p.get("status") or {}
            for cs in (st.get("initContainerStatuses") or []) + (st.get("containerStatuses") or []):
                w = (cs.get("state") or {}).get("waiting") or {}
                if w.get("reason") in ("ErrImagePull", "ImagePullBackOff", "InvalidImageName", "CreateContainerConfigError", "CreateContainerError"):
                    return "error", None, f"{cs['name']} couldn't start: {w.get('reason')}: {(w.get('message') or '')[:300]}"
            runner = next((cs for cs in st.get("containerStatuses") or [] if cs["name"] == "runner"), None)
            if runner and runner.get("state", {}).get("running") and not pulled: pulled, deadline = True, time.time() + timeout + 30
            done = (runner or {}).get("state", {}).get("terminated")
            if done: return ("done" if done.get("exitCode") == 0 else "failed"), done.get("exitCode"), ""
            if st.get("phase") in ("Succeeded", "Failed"): return "failed", None, st.get("message") or st.get("reason") or "The pod ended."
            if time.time() > deadline: return "timeout", None, "The run took too long (or never started) and was stopped."

    def _pod(self, name, command, services, timeout, token, label, net_token=None, maps=None, size=None):
        ep = endpoints()
        env = {"AXOR_COMMAND": command, "AXOR_TIMEOUT": str(timeout), "HOME": "/work", "PYTHONUNBUFFERED": "1", "AXOR_STATE": "/work/.axor/state",
               "SANDBOX_PROXY_URL": f"{ep['proxy_url']}/t/{token}", "OPENROUTER_API_KEY": "sandbox-proxy", "RIDGES_MAX_COST_USD": str(PER_PROBLEM),
               "AGENT_TIMEOUT": str(max(60, min(600, timeout - 30)))}
        side, vols = [], [{"name": "input", "projected": {"sources": [{"configMap": {"name": cm}} for cm in (maps or [name])]}}, {"name": "work", "emptyDir": {"sizeLimit": "2Gi"}},
                          {"name": "repo", "emptyDir": {"sizeLimit": "2Gi"}}, {"name": "tmp", "emptyDir": {"sizeLimit": "2Gi"}}]
        if "postgres" in services:
            env.update({"PGHOST": "127.0.0.1", "PGPORT": "5432", "PGUSER": "postgres", "PGPASSWORD": "sandbox", "PGDATABASE": "postgres",
                        "DATABASE_URL": "postgresql://postgres:sandbox@127.0.0.1:5432/postgres"})
            side.append({"name": "postgres", "image": PG_IMAGE, "imagePullPolicy": "IfNotPresent", "restartPolicy": "Always",
                         "env": [{"name": "POSTGRES_PASSWORD", "value": "sandbox"}, {"name": "PGDATA", "value": "/var/lib/postgresql/data/db"}],
                         "startupProbe": {"exec": {"command": ["pg_isready", "-h", "127.0.0.1", "-U", "postgres"]}, "periodSeconds": 2, "failureThreshold": 120},
                         "securityContext": {"allowPrivilegeEscalation": False},
                         "resources": {"requests": {"cpu": "100m", "memory": "256Mi"}, "limits": {"cpu": "2", "memory": "2Gi"}},
                         "volumeMounts": [{"name": "pg", "mountPath": "/var/lib/postgresql/data"}]})
            vols.append({"name": "pg", "emptyDir": {"sizeLimit": "4Gi"}})
        if "clickhouse" in services:
            env.update({"CLICKHOUSE_HOST": "127.0.0.1", "CLICKHOUSE_PORT": "9000", "CLICKHOUSE_URL": "http://127.0.0.1:8123"})
            side.append({"name": "clickhouse", "image": CH_IMAGE, "imagePullPolicy": "IfNotPresent", "restartPolicy": "Always",
                         "startupProbe": {"httpGet": {"path": "/ping", "port": 8123}, "periodSeconds": 2, "failureThreshold": 120},
                         "securityContext": {"allowPrivilegeEscalation": False},
                         "resources": {"requests": {"cpu": "100m", "memory": "512Mi"}, "limits": {"cpu": "2", "memory": "3Gi"}},
                         "volumeMounts": [{"name": "ch", "mountPath": "/var/lib/clickhouse"}]})
            vols.append({"name": "ch", "emptyDir": {"sizeLimit": "4Gi"}})
        runner = {"name": "runner", "image": IMAGE, "imagePullPolicy": PULL, "command": ["/bin/bash", "-c", RUNNER], "workingDir": "/work",
                  "env": [{"name": k, "value": v} for k, v in env.items()],
                  "securityContext": {"runAsNonRoot": True, "runAsUser": 1000, "runAsGroup": 1000, "allowPrivilegeEscalation": False,
                                      "capabilities": {"drop": ["ALL"]}},
                  "resources": {"requests": {"cpu": "250m", "memory": "512Mi"},
                                "limits": {"cpu": SIZES[size or "M"][0], "memory": SIZES[size or "M"][1], "ephemeral-storage": "4Gi"}},
                  "volumeMounts": [{"name": "input", "mountPath": "/input", "readOnly": True}, {"name": "work", "mountPath": "/work"},
                                   {"name": "repo", "mountPath": "/repo"}, {"name": "tmp", "mountPath": "/tmp"}]}
        labels, extra = {"app": "axor-sandbox"}, {}
        if net_token:  # the label opens the way to the egress proxy (56-sandbox.yaml); the token is what the proxy lets through
            labels["axor.dev/internet"] = "on"
            via = f"http://{net_token}:x@{ep['egress_proxy']}"
            for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"): runner["env"].append({"name": k, "value": via})
            for k in ("NO_PROXY", "no_proxy"): runner["env"].append({"name": k, "value": ep["no_proxy"]})
            runner["env"].append({"name": "AXOR_INTERNET", "value": "1"})
            if INTERNET_RUNTIME: extra["runtimeClassName"] = INTERNET_RUNTIME
        return {"apiVersion": "v1", "kind": "Pod",
                "metadata": {"name": name, "labels": labels, "annotations": {"axor.dev/run": label[:200]}},
                "spec": {"restartPolicy": "Never", "activeDeadlineSeconds": timeout + 600, "automountServiceAccountToken": False,
                         "enableServiceLinks": False, "terminationGracePeriodSeconds": 5,
                         "securityContext": {"fsGroup": 1000, "seccompProfile": {"type": "RuntimeDefault"}},
                         "initContainers": side, "containers": [runner], "volumes": vols, **extra}}
