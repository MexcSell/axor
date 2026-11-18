"""PaaS and FaaS: AXoR's platform (apps) and FaaS (functions) on its Kubernetes cluster, and the domain and HTTPS they use.

Domain & HTTPS. The platform has one domain (axor.internal until an admin sets one): AXoR answers at its console
address (the domain itself unless set otherwise), apps at <app>.apps.<domain>, functions at <fn>.fn.<domain>.
AXoR keeps AXoR DNS's zone for the domain in step: the console, *.apps and *.fn point at this server, and so do apps'
custom domains in zones AXoR DNS has (records owned by "platform"). HTTPS: AXoR's own certificate authority, made on
first use with its key encrypted in AXoR's database and name-constrained to the platform domain (so trusting it can't
let anyone impersonate other sites), signs the edge's default certificate for all those names. Its root certificate
can be downloaded to trust the platform before the domain is public. With ACME on, the edge gets Let's Encrypt
certificates instead: one for the domain, *.apps and *.fn over DNS-01 (answered by AXoR DNS, so the domain must be
delegated here), and one per custom domain (DNS-01 when AXoR DNS has its zone, TLS-ALPN-01 otherwise).

Apps (PaaS). A container image from any registry the cluster can pull from, with a port, replicas (or autoscaling),
CPU and memory limits, environment variables and secrets, an optional health check path, command, persistent volume
and custom domains. AXoR makes the Deployment, Service, Ingress, Secret (and volume and autoscaler) in axor-apps.
Functions (FaaS). Python or Node.js code typed in AXoR, with a handler, packages, environment, limits, a timeout and
replicas. It runs on the stock runtime image under AXoR's bootstrap (faas/), in axor-functions, which is restricted:
non-root, read-only root file system, no capabilities. Packages are installed at start into scratch space.
Both: every change is a revision, and the environment (and a function's code) goes into a new immutable Secret
(ConfigMap) named after its hash, so a rollback brings back image, code and environment together. The cluster is
the source of truth: settings live in the Deployment's annotations. Apps and functions get no Kubernetes API token,
can't reach AXoR or this host, and are held to limits by the axor-workloads policy (k8s/base/10-rbac.yaml).
Everything is for admins; changes need sudo and are audited.
"""
import base64, hashlib, ipaddress, json, logging, re, secrets, shlex, statistics, threading, time, urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .kube import Kube, KubeError, deploy_out, event_out, pod_out, ts
from .nameserver import DNSError, NameServer
from .secretbox import SecretBox

log = logging.getLogger("platform")
FAAS = Path(__file__).resolve().parent / "faas"
NS = {"apps": "axor-apps", "functions": "axor-functions"}
LABEL = {"apps": "axor.dev/app", "functions": "axor.dev/function"}
SUB = {"apps": "apps", "functions": "fn"}
A = {"apps": "an app", "functions": "a function"}
EDGE, AXOR = "axor-edge", "axor"
DEFAULT_DOMAIN = "axor.internal"
ACME_CA = {False: "https://acme-v02.api.letsencrypt.org/directory", True: "https://acme-staging-v02.api.letsencrypt.org/directory"}
NAME = re.compile(r"^[a-z]([a-z0-9-]{0,28}[a-z0-9])?$")
ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
IMAGE = re.compile(r"^[a-z0-9]([a-z0-9._/:-]{0,200}[a-z0-9])?(:[A-Za-z0-9_][A-Za-z0-9_.-]{0,127})?(@sha256:[a-f0-9]{64})?$")
HPATH = re.compile(r"^/[A-Za-z0-9._~/?=&%+-]{0,199}$")
HOST = re.compile(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,61}[a-z0-9]$")
PY_REQ = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(\[[A-Za-z0-9,._-]+\])?\s*([<>=!~]=?\s*[A-Za-z0-9.*+!_-]+\s*,?\s*)*$")
NODE_PKG = re.compile(r"^(@[a-z0-9][a-z0-9._~-]*/)?[a-z0-9][a-z0-9._~-]{0,213}(@[A-Za-z0-9.^~<>=*| -]{1,64})?$")
CAP_DROP = ["NET_RAW", "MKNOD", "AUDIT_WRITE", "SETFCAP"]  # of the default capabilities, those apps don't need (as the runner)
REQ_HEADERS = re.compile(r"^(content-type|accept|authorization|x-[a-z0-9-]{1,60})$")
RUNTIMES = {
    "python3.12": {"title": "Python 3.12", "image": "python:3.12.14-slim", "file": "main.py", "deps": "requirements.txt",
                   "handler": "handle", "boot": "bootstrap.py", "cmd": ["python", "-u", "/axor/bootstrap.py"],
                   "install": ["pip", "install", "--no-cache-dir", "--disable-pip-version-check", "--target", "/deps", "-r", "/code/requirements.txt"]},
    "node22": {"title": "Node.js 22", "image": "node:22.23.2-slim", "file": "index.js", "deps": "package.json",
               "handler": "handler", "boot": "bootstrap.js", "cmd": ["node", "/axor/bootstrap.js"],
               "install": ["sh", "-c", "cp /code/package.json /deps/ && cd /deps && npm install --no-audit --no-fund --omit=dev --loglevel=error"]},
}
TEMPLATES = {
    "python3.12": '''def handle(event):
    """Runs for every request. event has method, path, query, headers, body, json, client and context.
    Return a str, bytes, a dict or list (sent as JSON), (body, status), or
    {"statusCode": 201, "headers": {...}, "body": ...}."""
    name = event["query"].get("name") or (event["json"] or {}).get("name") or "world"
    return {"message": f"Hello, {name}!", "method": event["method"], "path": event["path"]}
''',
    "node22": '''// Runs for every request. event has method, path, query, headers, body, json, client and context.
// Return a string, a Buffer, an object (sent as JSON) or { statusCode, headers, body }. It may be async.
exports.handler = async (event) => {
  const name = event.query.name || event.json?.name || "world";
  return { message: `Hello, ${name}!`, method: event.method, path: event.path };
};
''',
}

def _b64(s): return base64.b64encode(s.encode() if isinstance(s, str) else s).decode()
def _hash(obj): return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()[:10]
def _ann(obj): return ((obj.get("metadata") or {}).get("annotations")) or {}

class EnvVar(BaseModel):
    key: str = Field(..., max_length=64)
    value: str | None = Field(None, max_length=32768)  # None on an existing secret: keep its value
    secret: bool = False

class AppIn(BaseModel):
    name: str = Field(..., max_length=30)
    image: str = Field(..., max_length=300)
    port: int = Field(8080, ge=1, le=65535)
    replicas: int = Field(1, ge=0, le=20)
    autoscale_max: int = Field(0, ge=0, le=20)  # 0 = fixed replicas; else scale between replicas and this on CPU
    cpu: float = Field(0.5, ge=0.05, le=8)
    memory: int = Field(256, ge=32, le=16384)  # MB
    health: str = Field("", max_length=200)
    command: str = Field("", max_length=2000)
    env: list[EnvVar] = Field(default_factory=list, max_length=100)
    domains: list[str] = Field(default_factory=list, max_length=10)
    public: bool = True
    volume: str = Field("", max_length=200)
    volume_gb: int = Field(1, ge=1, le=100)

class FnIn(BaseModel):
    name: str = Field(..., max_length=30)
    runtime: str = "python3.12"
    code: str = Field(..., min_length=1, max_length=400_000)
    handler: str = Field("", max_length=64)
    packages: str = Field("", max_length=8000)
    env: list[EnvVar] = Field(default_factory=list, max_length=100)
    cpu: float = Field(0.25, ge=0.05, le=4)
    memory: int = Field(128, ge=64, le=4096)
    timeout: int = Field(30, ge=1, le=900)
    replicas: int = Field(1, ge=1, le=20)
    autoscale_max: int = Field(0, ge=0, le=50)
    public: bool = True

class SettingsIn(BaseModel):
    domain: str = Field(..., max_length=253)
    console: str = Field("", max_length=253)
    acme: bool = False
    acme_email: str = Field("", max_length=254)
    acme_staging: bool = False
    public_ip: str = Field("", max_length=45)

class Act(BaseModel):
    action: str

class Rollback(BaseModel):
    revision: int = Field(..., ge=1)

class Req(BaseModel):
    method: str = "GET"
    path: str = Field("/", max_length=2000)
    headers: dict[str, str] = Field(default_factory=dict, max_length=20)
    body: str = Field("", max_length=1_000_000)

class Platform:
    def __init__(self, db, data_dir, kube=None, dns=None):
        self.db, self.k, self.dns, self.box = db, kube or Kube(), dns or NameServer(), SecretBox(db, data_dir)
        self.lock = threading.RLock()
        self._ip, self._thread, self.state, self._domain_cache = None, None, {"synced": None, "error": None}, None

    # ---------- settings ----------
    def settings(self):
        s = {"domain": DEFAULT_DOMAIN, "console": "", "acme": False, "acme_email": "", "acme_staging": False, "public_ip": ""}
        try: s.update(json.loads(self.db.setting("platform", "{}")))
        except ValueError: pass
        s["console"] = s["console"] or s["domain"]
        return s

    def host(self, kind, name, s=None):
        return f"{name}.{SUB[kind]}.{(s or self.settings())['domain']}"

    def public_ip(self):
        s = self.settings()
        if s["public_ip"]: return s["public_ip"]
        if not self._ip and self.k.enabled:
            try:
                addrs = [a for n in self.k.call("GET", "/api/v1/nodes")["items"] for a in n["status"].get("addresses") or []]
                self._ip = next((a["address"] for t in ("ExternalIP", "InternalIP") for a in addrs if a["type"] == t), None)
            except KubeError: pass
        return self._ip

    def save_settings(self, me, b: SettingsIn, ip):
        domain = b.domain.strip().rstrip(".").lower()
        console = (b.console.strip().rstrip(".").lower() or domain)
        if not HOST.match(domain): raise HTTPException(400, "That isn't a domain name. Try e.g. example.com or cloud.example.com.")
        if console != domain and not console.endswith("." + domain):
            raise HTTPException(400, f"AXoR's address must be {domain} or a name under it, e.g. axor.{domain}.")
        if console.endswith((f".apps.{domain}", f".fn.{domain}")): raise HTTPException(400, "That name is where apps or functions live.")
        if b.public_ip:
            try: ipaddress.IPv4Address(b.public_ip)
            except ValueError: raise HTTPException(400, "The public address must be an IPv4 address.")
        if b.acme and domain.endswith((".internal", ".local", ".test", ".localhost", ".example", ".invalid", ".lan", ".home.arpa")):
            raise HTTPException(400, f"Let's Encrypt only signs public names, and {domain} isn't one. Set a domain you own first.")
        if b.acme_email and not re.fullmatch(r"[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,}", b.acme_email):
            raise HTTPException(400, "That isn't an email address.")
        old = self.settings()
        new = {"domain": domain, "console": console, "acme": b.acme, "acme_email": b.acme_email.strip(), "acme_staging": b.acme_staging,
               "public_ip": b.public_ip.strip()}
        self.db.setting("platform", v=json.dumps(new))
        self._ip, self._domain_cache = None, None
        self.db.log("platform.settings", me["username"], domain, ip, f"console {console}, ACME {'on' if b.acme else 'off'}"
                    + (" (staging)" if b.acme and b.acme_staging else ""))
        if self.k.enabled:
            if (old["acme_email"], old["acme_staging"]) != (new["acme_email"], new["acme_staging"]): self._edge_acme(new)
            self.sync(routes=True)
        return self.overview()

    # ---------- certificate authority ----------
    def ca(self, domain=None):
        """(certificate, key) of AXoR's CA for the platform domain, made on first use (and again for a new domain)."""
        domain = domain or self.settings()["domain"]
        pem, key = self.db.setting("platform.ca_cert"), self.box.get("platform.ca_key")
        if pem and key and self.db.setting("platform.ca_domain") == domain:
            return x509.load_pem_x509_certificate(pem.encode()), serialization.load_pem_private_key(key.encode(), None)
        k = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "AXoR"),
                          x509.NameAttribute(NameOID.COMMON_NAME, f"AXoR CA for {domain} {secrets.token_hex(2)}")])
        ip = self.public_ip()
        allowed_ips = [x509.IPAddress(ipaddress.ip_network(f"{ip}/32"))] if ip else [x509.IPAddress(ipaddress.ip_network("0.0.0.0/32"))]
        now = datetime.now(timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(k.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(hours=1)).not_valid_after(now + timedelta(days=3650))
                .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False,
                                             key_encipherment=False, data_encipherment=False, key_agreement=False, encipher_only=False,
                                             decipher_only=False), critical=True)
                .add_extension(x509.NameConstraints(permitted_subtrees=[x509.DNSName(domain)] + allowed_ips, excluded_subtrees=None), critical=True)
                .add_extension(x509.SubjectKeyIdentifier.from_public_key(k.public_key()), critical=False)
                .sign(k, hashes.SHA256()))
        self.db.setting("platform.ca_cert", v=cert.public_bytes(serialization.Encoding.PEM).decode())
        self.box.set("platform.ca_key", k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                        serialization.NoEncryption()).decode())
        self.db.setting("platform.ca_domain", v=domain)
        self.db.setting("platform.leaf", v="{}")  # the old leaf was signed by the old CA
        log.info("made a new certificate authority for %s", domain)
        return cert, k

    def _leaf_names(self, s):
        d = s["domain"]
        return sorted({d, s["console"], f"*.{d}", f"*.apps.{d}", f"*.fn.{d}"})

    def edge_cert(self, force=False):
        """Signs the edge's default certificate when its names, the CA or the expiry call for it, and hands it to the edge."""
        s = self.settings()
        ca, ca_key = self.ca(s["domain"])
        names, ip = self._leaf_names(s), self.public_ip()
        leaf = json.loads(self.db.setting("platform.leaf", "{}") or "{}")
        cur = self.k.get(f"/api/v1/namespaces/{EDGE}/secrets/edge-tls")
        have = base64.b64decode(((cur or {}).get("data") or {}).get("tls.yaml", "")).decode(errors="replace")
        if (not force and leaf.get("names") == names and leaf.get("ip") == ip and leaf.get("not_after", 0) - time.time() > 30 * 86400
                and leaf.get("fp") and leaf["fp"] in have):
            return leaf
        k = ec.generate_private_key(ec.SECP256R1())
        now = datetime.now(timezone.utc)
        sans = [x509.DNSName(n) for n in names] + ([x509.IPAddress(ipaddress.ip_address(ip))] if ip else [])
        cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, s["console"])]))
                .issuer_name(ca.subject).public_key(k.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(hours=1)).not_valid_after(now + timedelta(days=397))
                .add_extension(x509.SubjectAlternativeName(sans), critical=False)
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=False, crl_sign=False, content_commitment=False,
                                             key_encipherment=False, data_encipherment=False, key_agreement=False, encipher_only=False,
                                             decipher_only=False), critical=True)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
                .sign(ca_key, hashes.SHA256()))
        chain = (cert.public_bytes(serialization.Encoding.PEM) + ca.public_bytes(serialization.Encoding.PEM)).decode()
        key = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
        fp = cert.fingerprint(hashes.SHA256()).hex()[:32]
        ind = lambda t: "\n".join("          " + l for l in t.strip().splitlines())
        y = (f"# written by AXoR: the edge's default certificate ({fp}), signed by AXoR's CA\ntls:\n  stores:\n    default:\n"
             f"      defaultCertificate:\n        certFile: |\n{ind(chain)}\n        keyFile: |\n{ind(key)}\n")
        self.k.patch(f"/api/v1/namespaces/{EDGE}/secrets/edge-tls", {"data": {"tls.yaml": _b64(y)}}, kind="merge")
        leaf = {"names": names, "ip": ip, "fp": fp, "not_after": cert.not_valid_after_utc.timestamp(), "issued": time.time()}
        self.db.setting("platform.leaf", v=json.dumps(leaf))
        log.info("edge certificate %s for %s", fp, ", ".join(names))
        return leaf

    def _edge_acme(self, s):
        self.k.patch(f"/api/v1/namespaces/{EDGE}/configmaps/edge-config",
                     {"data": {"ACME_EMAIL": s["acme_email"], "ACME_CA": ACME_CA[bool(s["acme_staging"])]}}, kind="merge")
        self.k.patch(f"/apis/apps/v1/namespaces/{EDGE}/deployments/edge",  # the edge reads them at start
                     {"spec": {"template": {"metadata": {"annotations": {"kubectl.kubernetes.io/restartedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}}}}})

    # ---------- keeping the edge, DNS and routes in step ----------
    def _tls(self, s, group, hosts=()):
        a = {"traefik.ingress.kubernetes.io/router.entrypoints": "websecure"}
        if not s["acme"]: return a  # the edge's default certificate (AXoR's CA) covers the platform's names
        if group == "platform":
            d = s["domain"]
            sans = [f"*.apps.{d}", f"*.fn.{d}"] + ([s["console"]] if s["console"] != d else [])
            a.update({"traefik.ingress.kubernetes.io/router.tls.certresolver": "dns",
                      "traefik.ingress.kubernetes.io/router.tls.domains.0.main": d,
                      "traefik.ingress.kubernetes.io/router.tls.domains.0.sans": ",".join(sans)})
        else:  # custom domains: DNS-01 where AXoR DNS has the zone, TLS-ALPN-01 elsewhere
            a["traefik.ingress.kubernetes.io/router.tls.certresolver"] = "dns" if group == "zone" else "alpn"
        return a

    def _zones(self):
        try: return [z["name"] for z in self.dns.call("GET", "/zones")["zones"]]
        except DNSError: return []

    @staticmethod
    def _zone_of(host, zones):
        return max((z for z in zones if host == z or host.endswith("." + z)), key=len, default=None)

    def _console_ingress(self, s):
        self.k.apply(f"/apis/networking.k8s.io/v1/namespaces/{AXOR}/ingresses", {
            "apiVersion": "networking.k8s.io/v1", "kind": "Ingress",
            "metadata": {"name": "web-domain", "namespace": AXOR, "annotations": self._tls(s, "platform")},
            "spec": {"ingressClassName": "axor", "rules": [{"host": s["console"], "http": {"paths": [
                {"path": "/", "pathType": "Prefix", "backend": {"service": {"name": "web", "port": {"number": 8000}}}}]}}]}})

    def _dns(self, s):
        """AXoR DNS: the platform's zone exists, and every zone has the platform's records and no stale ones."""
        ip = self.public_ip()
        if not self.dns.enabled or not ip: return
        zones = self._zones()
        if not self._zone_of(s["domain"], zones):
            self.dns.call("POST", "/zones", body={"name": s["domain"], "ip": ip})
            zones.append(s["domain"])
        want = {z: [] for z in zones}
        def put(host, note):
            z = self._zone_of(host, zones)
            if z: want[z].append({"name": "@" if host == z else host[: -len(z) - 1], "type": "A", "value": ip, "note": note})
        put(s["console"], "AXoR")
        put(f"*.apps.{s['domain']}", "Apps")
        put(f"*.fn.{s['domain']}", "Functions")
        seen = set()
        for d in self.k.items(f"/apis/apps/v1/namespaces/{NS['apps']}/deployments", {"labelSelector": LABEL["apps"]}):
            routes = json.loads(_ann(d).get("axor.dev/routes", "{}"))
            for h in routes.get("domains", []) if routes.get("public") else []:
                if h not in seen: seen.add(h); put(h, f"App {d['metadata']['name']}")
        for z, recs in want.items():
            self.dns.call("PUT", f"/zones/{z}/owned/platform", body={"records": recs})

    def sync(self, routes=False):
        """Brings the edge certificate, DNS, AXoR's Ingress (and with routes=True every app's and function's) in step."""
        with self.lock:
            s = self.settings()
            errors = []
            for step, fn in (("certificate", self.edge_cert), ("AXoR's address", lambda: self._console_ingress(s)), ("DNS", lambda: self._dns(s))):
                try: fn()
                except (KubeError, DNSError) as e: errors.append(f"{step}: {e}")
            if routes:
                zones = self._zones()
                for kind in NS:
                    for d in self.k.items(f"/apis/apps/v1/namespaces/{NS[kind]}/deployments", {"labelSelector": LABEL[kind]}):
                        try: self._routes(kind, d["metadata"]["name"], json.loads(_ann(d).get("axor.dev/routes", "{}")), s, zones)
                        except KubeError as e: errors.append(f"{d['metadata']['name']}: {e}")
            self.state = {"synced": time.time(), "error": "; ".join(errors) or None}
            return self.state

    def start(self):
        if self._thread or not self.k.enabled: return
        def run():
            delay = 5
            while True:
                time.sleep(delay)
                try:
                    st = self.sync(routes=delay == 5)
                    delay = 6 * 3600 if not st["error"] else 60  # then checks the certificate's expiry four times a day
                except Exception as e:  # noqa: BLE001 - keep trying; the page shows the error
                    log.warning("platform sync failed: %s", e); self.state = {"synced": time.time(), "error": str(e)}; delay = 60
        self._thread = threading.Thread(target=run, daemon=True, name="platform-sync"); self._thread.start()

    def overview(self):
        s = self.settings()
        ca = leaf = None
        if self.db.setting("platform.ca_cert"):
            c = x509.load_pem_x509_certificate(self.db.setting("platform.ca_cert").encode())
            ca = {"subject": c.subject.rfc4514_string(), "fingerprint": c.fingerprint(hashes.SHA256()).hex(":").upper(),
                  "not_after": c.not_valid_after_utc.timestamp(), "domain": self.db.setting("platform.ca_domain")}
            leaf = json.loads(self.db.setting("platform.leaf", "{}") or "{}") or None
        edge = None
        if self.k.enabled:
            try:
                e = self.k.get(f"/apis/apps/v1/namespaces/{EDGE}/deployments/edge")
                cm = self.k.get(f"/api/v1/namespaces/{EDGE}/configmaps/edge-config") or {}
                edge = {**deploy_out(e), "acme_ca": (cm.get("data") or {}).get("ACME_CA")} if e else None
            except KubeError as ex: edge = {"error": str(ex)}
        return {"settings": s, "kubernetes": self.k.enabled, "dns": self.dns.enabled, "public_ip": self.public_ip(),
                "hosts": {"console": s["console"], "apps": f"*.apps.{s['domain']}", "functions": f"*.fn.{s['domain']}"},
                "ca": ca, "leaf": leaf, "edge": edge, "sync": self.state, "runtimes": {k: v["title"] for k, v in RUNTIMES.items()}}

    def guard(self):
        """Middleware: a name under *.apps or *.fn that no app or function has reaches AXoR through its catch-all route;
        answer 404 there instead of showing AXoR's sign-in page."""
        async def mw(req, call_next):
            host = (req.headers.get("x-forwarded-host") or req.headers.get("host") or "").split(":")[0].lower()
            d = self._domain_cache or self.settings()["domain"]
            self._domain_cache = d
            if host.endswith((f".apps.{d}", f".fn.{d}")):
                return Response("No app or function answers at this address.\n", status_code=404, media_type="text/plain")
            return await call_next(req)
        return mw

    def delegation(self):
        return self.dns.call("GET", f"/zones/{self.settings()['domain']}/delegation", timeout=20)

    # ---------- shared by apps and functions ----------
    def _ready(self):
        if not self.k.enabled: raise HTTPException(503, "AXoR isn't running on Kubernetes, so apps and functions aren't available. See k8s/ in the README.")

    def _get(self, kind, name):
        if not NAME.match(name or ""): raise HTTPException(404, f"There's no such {kind[:-1]}.")
        d = self.k.get(f"/apis/apps/v1/namespaces/{NS[kind]}/deployments/{name}")
        if not d or LABEL[kind] not in (d["metadata"].get("labels") or {}): raise HTTPException(404, f"There's no {kind[:-1]} called {name}.")
        return d

    def _env(self, kind, name, env, current):
        """(values, secret keys) for the new revision; secrets sent without a value keep the current one."""
        old = {}
        if current:
            sec = next((x["secretRef"]["name"] for x in current["spec"]["template"]["spec"]["containers"][0].get("envFrom") or [] if "secretRef" in x), None)
            o = self.k.get(f"/api/v1/namespaces/{NS[kind]}/secrets/{sec}") if sec else None
            old = {k: base64.b64decode(v).decode() for k, v in ((o or {}).get("data") or {}).items()}
        vals, secret_keys = {}, []
        for e in env:
            if not ENV_KEY.match(e.key): raise HTTPException(400, f"{e.key!r} isn't a valid environment variable name.")
            if e.key in vals: raise HTTPException(400, f"{e.key} is set twice.")
            if e.value is None:
                if not e.secret or e.key not in old: raise HTTPException(400, f"{e.key} needs a value.")
                vals[e.key] = old[e.key]
            else: vals[e.key] = e.value
            if e.secret: secret_keys.append(e.key)
        return vals, sorted(secret_keys)

    def _object(self, kind, plural, api, name, owner, data_key, data, immutable=True):
        """An immutable Secret or ConfigMap named after its content's hash (so it belongs to one revision)."""
        ns, h = NS[kind], _hash(data)
        obj_name = f"{owner}-{name}-{h}"
        if not self.k.get(f"/api/v1/namespaces/{ns}/{plural}/{obj_name}"):
            body = {"apiVersion": "v1", "kind": api, "immutable": immutable,
                    "metadata": {"name": obj_name, "namespace": ns, "labels": {LABEL[kind]: owner, "app.kubernetes.io/managed-by": "axor"}},
                    data_key: {k: _b64(v) for k, v in data.items()} if data_key == "data" and api == "Secret" else data}
            try: self.k.call("POST", f"/api/v1/namespaces/{ns}/{plural}", body=body)
            except KubeError as e:
                if e.status != 409: raise
        return obj_name

    @staticmethod
    def _settings(d):
        """An app's or function's settings: the pod template's, plus replicas and autoscaling from the Deployment."""
        tpl = (d["spec"]["template"]["metadata"].get("annotations") or {}).get("axor.dev/settings", "{}")
        return {**json.loads(tpl), **json.loads(_ann(d).get("axor.dev/scale", '{"replicas": 1, "autoscale_max": 0}'))}

    def _template_meta(self, kind, name, settings, cause, current):
        """Pod template annotations: the settings, and what changed (only when the pods themselves change)."""
        h = _hash(settings)
        prev = (current or {}).get("spec", {}).get("template", {}).get("metadata", {}).get("annotations") or {}
        same = prev.get("axor.dev/hash") == h
        return {"axor.dev/settings": json.dumps(settings, sort_keys=True), "axor.dev/hash": h,
                "axor.dev/change": prev.get("axor.dev/change", cause) if same else cause,
                **({"kubectl.kubernetes.io/restartedAt": prev["kubectl.kubernetes.io/restartedAt"]} if "kubectl.kubernetes.io/restartedAt" in prev else {})}

    def _deployment(self, kind, name, routes, scale, pod, tpl_ann, strategy="RollingUpdate"):
        replicas = None if scale.get("autoscale_max", 0) > scale.get("replicas", 1) else scale.get("replicas", 1)  # the autoscaler sets it
        labels = {LABEL[kind]: name, "app.kubernetes.io/managed-by": "axor"}
        spec = {"selector": {"matchLabels": {LABEL[kind]: name}}, "revisionHistoryLimit": 10, "progressDeadlineSeconds": 300,
                "strategy": {"type": "Recreate"} if strategy == "Recreate" else {"type": "RollingUpdate", "rollingUpdate": {"maxUnavailable": 0, "maxSurge": 1}},
                "template": {"metadata": {"labels": labels, "annotations": tpl_ann}, "spec": pod}}
        if replicas is not None: spec["replicas"] = replicas
        return {"apiVersion": "apps/v1", "kind": "Deployment",
                "metadata": {"name": name, "namespace": NS[kind], "labels": labels,
                             "annotations": {"axor.dev/routes": json.dumps(routes, sort_keys=True), "axor.dev/scale": json.dumps(scale, sort_keys=True)}},
                "spec": spec}

    def _service(self, kind, name, port):
        self.k.apply(f"/api/v1/namespaces/{NS[kind]}/services", {
            "apiVersion": "v1", "kind": "Service",
            "metadata": {"name": name, "namespace": NS[kind], "labels": {LABEL[kind]: name, "app.kubernetes.io/managed-by": "axor"}},
            "spec": {"selector": {LABEL[kind]: name}, "ports": [{"name": "http", "port": 80, "targetPort": port}]}})

    def _autoscale(self, kind, name, lo, hi, cpu_limit):
        path = f"/apis/autoscaling/v2/namespaces/{NS[kind]}/horizontalpodautoscalers"
        if hi <= lo: return self.k.delete(f"{path}/{name}")
        self.k.apply(path, {"apiVersion": "autoscaling/v2", "kind": "HorizontalPodAutoscaler",
                            "metadata": {"name": name, "namespace": NS[kind], "labels": {LABEL[kind]: name, "app.kubernetes.io/managed-by": "axor"}},
                            "spec": {"scaleTargetRef": {"apiVersion": "apps/v1", "kind": "Deployment", "name": name},
                                     "minReplicas": max(1, lo), "maxReplicas": hi,
                                     "metrics": [{"type": "Resource", "resource": {"name": "cpu", "target": {
                                         "type": "AverageValue", "averageValue": f"{int(cpu_limit * 700)}m"}}}]}})  # 70% of the limit

    def _routes(self, kind, name, routes, s=None, zones=None):
        """The Ingresses for an app or function: its platform name, and custom domains grouped by how they get certificates."""
        s, ns = s or self.settings(), NS[kind]
        zones = self._zones() if zones is None else zones
        groups = {}
        if routes.get("public"):
            groups[name] = ("platform", [self.host(kind, name, s)])
            for h in routes.get("domains", []):
                g = "zone" if self._zone_of(h, zones) else "ext"
                groups.setdefault(f"{name}-{g}", (g, []))[1].append(h)
        path = f"/apis/networking.k8s.io/v1/namespaces/{ns}/ingresses"
        for ing_name, (group, hosts) in groups.items():
            self.k.apply(path, {"apiVersion": "networking.k8s.io/v1", "kind": "Ingress",
                                "metadata": {"name": ing_name, "namespace": ns, "annotations": self._tls(s, group),
                                             "labels": {LABEL[kind]: name, "app.kubernetes.io/managed-by": "axor"}},
                                "spec": {"ingressClassName": "axor", "rules": [{"host": h, "http": {"paths": [{"path": "/", "pathType": "Prefix",
                                         "backend": {"service": {"name": name, "port": {"number": 80}}}}]}} for h in hosts]}})
        for i in self.k.items(path, {"labelSelector": f"{LABEL[kind]}={name}"}):
            if i["metadata"]["name"] not in groups: self.k.delete(f"{path}/{i['metadata']['name']}")

    def _gc(self, kind, name):
        """Removes the Secrets and ConfigMaps no revision kept in the Deployment's history uses any more."""
        ns, sel = NS[kind], {"labelSelector": f"{LABEL[kind]}={name}"}
        used = set()
        objs = [self.k.get(f"/apis/apps/v1/namespaces/{ns}/deployments/{name}")] + self.k.items(f"/apis/apps/v1/namespaces/{ns}/replicasets", sel)
        for o in filter(None, objs):
            spec = o["spec"]["template"]["spec"]
            for c in spec["containers"] + (spec.get("initContainers") or []):
                used |= {x["secretRef"]["name"] for x in c.get("envFrom") or [] if "secretRef" in x}
            used |= {v["configMap"]["name"] for v in spec.get("volumes") or [] if "configMap" in v}
        for plural in ("secrets", "configmaps"):
            for x in self.k.items(f"/api/v1/namespaces/{ns}/{plural}", sel):
                if x["metadata"]["name"] not in used and time.time() - (ts(x["metadata"]["creationTimestamp"]) or 0) > 60:
                    self.k.delete(f"/api/v1/namespaces/{ns}/{plural}/{x['metadata']['name']}")

    def _status(self, d, pods):
        o = deploy_out(d)
        live = [p for p in pods if not p["deleting"]]
        bad = next((p["problem"] for p in live if p["problem"]), None)
        if o["replicas"] == 0: return "stopped", None
        if o["failed"]: return "failed", o["message"] or bad
        if bad and re.search(r"CrashLoopBackOff|ImagePull|ErrImage|InvalidImageName|CreateContainer|OOMKilled|Error", bad):
            return ("failing" if o["ready"] == 0 or o["rolling"] else "degraded"), bad
        if o["rolling"]: return "deploying", bad
        return ("running", None) if o["ready"] >= o["replicas"] else ("starting", bad)

    def list(self, kind):
        self._ready()
        ns, lab = NS[kind], LABEL[kind]
        with ThreadPoolExecutor(4) as pool:
            fd = pool.submit(self.k.items, f"/apis/apps/v1/namespaces/{ns}/deployments", {"labelSelector": lab})
            fp = pool.submit(self.k.items, f"/api/v1/namespaces/{ns}/pods", {"labelSelector": lab})
            fm = pool.submit(self.k.metrics, ns)
            deps, usage = fd.result(), fm.result()
            pods = [pod_out(p, usage) for p in fp.result()]
        s = self.settings()
        out = []
        for d in sorted(deps, key=lambda d: d["metadata"]["name"]):
            name, mine = d["metadata"]["name"], [p for p in pods if p["deployment"] == d["metadata"]["name"]]
            status, msg = self._status(d, mine)
            tpl = d["spec"]["template"]["metadata"].get("annotations") or {}
            settings, routes = self._settings(d), json.loads(_ann(d).get("axor.dev/routes", "{}"))
            o = deploy_out(d)
            out.append({"name": name, "status": status, "message": msg, "replicas": o["replicas"], "ready": o["ready"],
                        "image": settings.get("image"), "runtime": settings.get("runtime"),
                        "url": f"https://{self.host(kind, name, s)}/" if routes.get("public") else None, "domains": routes.get("domains", []),
                        "cpu": round(sum(p["cpu"] or 0 for p in mine), 3), "memory": sum(p["memory"] or 0 for p in mine),
                        "cpu_limit": settings.get("cpu"), "memory_limit": settings.get("memory"), "restarts": sum(p["restarts"] for p in mine),
                        "change": tpl.get("axor.dev/change"), "updated": max(filter(None, [o["created"], o["restarted"]] +
                                                                                 [p["created"] for p in mine]), default=None)})
        return {"items": out, "domain": s["domain"], "suffix": f".{SUB[kind]}.{s['domain']}"}

    def view(self, kind, name):
        self._ready()
        ns, d = NS[kind], self._get(kind, name)
        sel = {"labelSelector": f"{LABEL[kind]}={name}"}
        usage = self.k.metrics(ns)
        pods = [pod_out(p, usage) for p in self.k.items(f"/api/v1/namespaces/{ns}/pods", sel)]
        rss = self.k.items(f"/apis/apps/v1/namespaces/{ns}/replicasets", sel)
        names = {name} | {r["metadata"]["name"] for r in rss} | {p["name"] for p in pods}
        events = sorted((event_out(e) for e in self.k.items(f"/api/v1/namespaces/{ns}/events") if (e.get("involvedObject") or {}).get("name") in names),
                        key=lambda e: e["time"] or 0, reverse=True)[:30]
        cur_rev = _ann(d).get("deployment.kubernetes.io/revision")
        history = []
        for r in rss:
            a = r["spec"]["template"]["metadata"].get("annotations") or {}
            st = json.loads(a.get("axor.dev/settings", "{}"))
            rev = _ann(r).get("deployment.kubernetes.io/revision")
            history.append({"revision": int(rev or 0), "current": rev == cur_rev, "change": a.get("axor.dev/change"),
                            "image": st.get("image"), "runtime": st.get("runtime"), "created": ts(r["metadata"].get("creationTimestamp")),
                            "ready": (r.get("status") or {}).get("readyReplicas", 0)})
        history.sort(key=lambda h: -h["revision"])
        tpl = d["spec"]["template"]
        settings, routes = self._settings(d), json.loads(_ann(d).get("axor.dev/routes", "{}"))
        c = tpl["spec"]["containers"][0]
        sec = next((x["secretRef"]["name"] for x in c.get("envFrom") or [] if "secretRef" in x), None)
        envs = {k: base64.b64decode(v).decode(errors="replace") for k, v in (((self.k.get(f"/api/v1/namespaces/{ns}/secrets/{sec}") or {}).get("data") or {}) if sec else {}).items()}
        hidden = set(settings.get("secrets", []))
        status, msg = self._status(d, pods)
        out = {"name": name, "status": status, "message": msg, **{k: v for k, v in deploy_out(d).items() if k in ("replicas", "ready", "updated", "rolling")},
               "settings": settings, "public": routes.get("public", False), "domains": routes.get("domains", []),
               "env": [{"key": k, "value": None if k in hidden else v, "secret": k in hidden} for k, v in sorted(envs.items())],
               "url": f"https://{self.host(kind, name)}/" if routes.get("public") else None, "host": self.host(kind, name),
               "pods": pods, "events": events, "history": history,
               "autoscaler": self.k.get(f"/apis/autoscaling/v2/namespaces/{ns}/horizontalpodautoscalers/{name}") is not None}
        if kind == "functions":
            cm = next((v["configMap"]["name"] for v in tpl["spec"].get("volumes") or [] if v["name"] == "code"), None)
            data = ((self.k.get(f"/api/v1/namespaces/{ns}/configmaps/{cm}") or {}).get("data") or {}) if cm else {}
            rt = RUNTIMES.get(settings.get("runtime"), RUNTIMES["python3.12"])
            out["code"] = data.get(rt["file"], "")
            out["packages"] = settings.get("packages", "")
        return out

    def logs(self, kind, name, tail=300):
        self._ready()
        ns = NS[kind]
        self._get(kind, name)
        pods = sorted(self.k.items(f"/api/v1/namespaces/{ns}/pods", {"labelSelector": f"{LABEL[kind]}={name}"}),
                      key=lambda p: p["metadata"]["creationTimestamp"], reverse=True)[:6]
        lines = []
        for p in pods:
            short = p["metadata"]["name"].rsplit("-", 1)[-1]
            names = [c["name"] for c in p["spec"].get("initContainers") or []] + [c["name"] for c in p["spec"]["containers"]]
            for c in names:
                try: text = self.k.logs(ns, p["metadata"]["name"], c, tail)
                except KubeError: continue
                for ln in text.splitlines():
                    t, _, msg = ln.partition(" ")
                    lines.append((t, short + ("" if c in ("app", "fn") else f"/{c}"), msg))
        lines.sort(key=lambda x: x[0])
        many = len({x[1] for x in lines}) > 1
        return {"text": "\n".join(f"{t[11:19]} {p + ' │ ' if many else ''}{m}" for t, p, m in lines[-int(tail):])[-400_000:]}

    def act(self, me, kind, name, action, ip):
        self._ready()
        d = self._get(kind, name)
        ns = NS[kind]
        settings = self._settings(d)
        if action == "restart":
            self.k.patch(f"/apis/apps/v1/namespaces/{ns}/deployments/{name}",
                         {"spec": {"template": {"metadata": {"annotations": {"kubectl.kubernetes.io/restartedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}}}}})
        elif action in ("stop", "start"):
            n = 0 if action == "stop" else max(1, settings.get("replicas", 1))
            self.k.patch(f"/apis/apps/v1/namespaces/{ns}/deployments/{name}/scale", {"spec": {"replicas": n}}, kind="merge")
        else: raise HTTPException(400, "Unknown action.")
        self.db.log(f"{kind[:-1]}.{action}", me["username"], name, ip, "")
        return {"ok": True}

    def delete(self, me, kind, name, volume, ip):
        self._ready()
        self._get(kind, name)
        ns, sel = NS[kind], {"labelSelector": f"{LABEL[kind]}={name}"}
        self.k.delete(f"/apis/apps/v1/namespaces/{ns}/deployments/{name}", {"propagationPolicy": "Foreground"})
        self.k.delete(f"/api/v1/namespaces/{ns}/services/{name}")
        self.k.delete(f"/apis/autoscaling/v2/namespaces/{ns}/horizontalpodautoscalers/{name}")
        for plural, api in (("ingresses", "/apis/networking.k8s.io/v1"), ("secrets", "/api/v1"), ("configmaps", "/api/v1")):
            for x in self.k.items(f"{api}/namespaces/{ns}/{plural}", sel): self.k.delete(f"{api}/namespaces/{ns}/{plural}/{x['metadata']['name']}")
        if volume: self.k.delete(f"/api/v1/namespaces/{ns}/persistentvolumeclaims/{name}-data")
        self.db.log(f"{kind[:-1]}.delete", me["username"], name, ip, "volume deleted" if volume else "")
        if kind == "apps": self._dns_quiet()
        return {"ok": True}

    def rollback(self, me, kind, name, revision, ip):
        self._ready()
        d = self._get(kind, name)
        ns = NS[kind]
        rs = next((r for r in self.k.items(f"/apis/apps/v1/namespaces/{ns}/replicasets", {"labelSelector": f"{LABEL[kind]}={name}"})
                   if _ann(r).get("deployment.kubernetes.io/revision") == str(revision)), None)
        if not rs: raise HTTPException(404, f"Revision {revision} isn't kept any more (the last 10 are).")
        tpl = rs["spec"]["template"]
        tpl["metadata"]["labels"].pop("pod-template-hash", None)
        ann = tpl["metadata"].setdefault("annotations", {})
        ann["axor.dev/change"] = f"{me['username']} rolled back to revision {revision}"
        scale = json.loads(_ann(d).get("axor.dev/scale", '{"replicas": 1, "autoscale_max": 0}'))  # today's scale and routes stay
        obj = self._deployment(kind, name, json.loads(_ann(d).get("axor.dev/routes", "{}")), scale, tpl["spec"], ann, d["spec"]["strategy"]["type"])
        self.k.apply(f"/apis/apps/v1/namespaces/{ns}/deployments", obj)
        self._autoscale(kind, name, scale["replicas"], scale["autoscale_max"], json.loads(ann.get("axor.dev/settings", "{}")).get("cpu", 0.5))
        self.db.log(f"{kind[:-1]}.rollback", me["username"], name, ip, f"to revision {revision}")
        return {"ok": True}

    def request(self, kind, name, b: Req):
        """Sends a request to the app or function from inside the cluster (its Service), as the Test and Invoke panels do."""
        self._ready()
        d = self._get(kind, name)
        svc = self.k.get(f"/api/v1/namespaces/{NS[kind]}/services/{name}")
        if not svc or not svc["spec"].get("clusterIP"): raise HTTPException(409, "It has no service yet.")
        method = b.method.upper()
        if method not in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"): raise HTTPException(400, "Unknown method.")
        path = b.path if b.path.startswith("/") else "/" + b.path
        if re.search(r"[\x00-\x20#]", path): raise HTTPException(400, "That isn't a path (encode spaces as %20).")
        headers = {k: v for k, v in b.headers.items() if REQ_HEADERS.match(k.lower()) and "\n" not in v and "\r" not in v}
        headers.setdefault("User-Agent", "AXoR")
        settings = self._settings(d)
        data = b.body.encode() if b.body and method not in ("GET", "HEAD") else None
        req = urllib.request.Request(f"http://{svc['spec']['clusterIP']}:80{urllib.parse.quote(path, safe='/?=&%:+,;@~-._')}",
                                     data=data, headers=headers, method=method)
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=settings.get("timeout", 30) + 5) as r:
                status, rh, body = r.status, dict(r.headers), r.read(1_000_001)
        except urllib.error.HTTPError as e:
            status, rh, body = e.code, dict(e.headers), e.read(1_000_001)
        except (urllib.error.URLError, OSError) as e:
            raise HTTPException(502, f"No answer from {name}: {getattr(e, 'reason', e)}. Is it running?")
        ms = round((time.monotonic() - t0) * 1000, 1)
        try: text, binary = body[:1_000_000].decode("utf-8"), False
        except UnicodeDecodeError: text, binary = f"{len(body)} bytes of binary data", True
        return {"status": status, "headers": rh, "body": text, "binary": binary, "truncated": len(body) > 1_000_000, "ms": ms}

    def _dns_quiet(self):
        try: self._dns(self.settings())
        except (DNSError, KubeError) as e: log.warning("dns sync: %s", e); self.state = {**self.state, "error": f"DNS: {e}"}

    def _common(self, kind, b, create):
        if not NAME.match(b.name): raise HTTPException(400, "Names are 1-30 lowercase letters, digits or dashes, starting with a letter.")
        cur = self.k.get(f"/apis/apps/v1/namespaces/{NS[kind]}/deployments/{b.name}")
        if create and cur: raise HTTPException(409, f"There's already {A[kind]} called {b.name}.")
        if not create and (not cur or LABEL[kind] not in (cur["metadata"].get("labels") or {})): raise HTTPException(404, f"There's no {kind[:-1]} called {b.name}.")
        if b.autoscale_max and b.autoscale_max <= b.replicas: raise HTTPException(400, "Autoscaling's maximum must be above the replicas it starts from.")
        return cur

    # ---------- apps ----------
    def save_app(self, me, b: AppIn, ip, create):
        self._ready()
        cur = self._common("apps", b, create)
        image = b.image.strip()
        if not IMAGE.match(image): raise HTTPException(400, "That isn't an image reference. Try e.g. nginx:1.27 or ghcr.io/org/app:1.2.")
        if b.health and not HPATH.match(b.health): raise HTTPException(400, "The health check is a path, e.g. /health.")
        if b.volume and (not HPATH.match(b.volume) or b.volume == "/"): raise HTTPException(400, "The volume is mounted at a path, e.g. /data.")
        if b.volume and (b.replicas > 1 or b.autoscale_max): raise HTTPException(400, "An app with a volume runs one pod (the volume belongs to one at a time).")
        try: args = shlex.split(b.command) if b.command.strip() else None
        except ValueError as e: raise HTTPException(400, f"The command can't be read: {e}.")
        s = self.settings()
        domains = sorted({h.strip().rstrip(".").lower() for h in b.domains if h.strip()})
        for h in domains:
            if not HOST.match(h): raise HTTPException(400, f"{h} isn't a domain name.")
            if h == s["console"] or h.endswith((f".apps.{s['domain']}", f".fn.{s['domain']}")): raise HTTPException(400, f"{h} is one of the platform's own names.")
        for other in self.k.items(f"/apis/apps/v1/namespaces/{NS['apps']}/deployments", {"labelSelector": LABEL["apps"]}):
            taken = set(json.loads(_ann(other).get("axor.dev/routes", "{}")).get("domains", [])) & set(domains)
            if taken and other["metadata"]["name"] != b.name: raise HTTPException(409, f"{', '.join(taken)} already belongs to {other['metadata']['name']}.")
        vals, secret_keys = self._env("apps", b.name, b.env, cur)
        env_name = self._object("apps", "secrets", "Secret", "env", b.name, "data", vals)
        settings = {"image": image, "port": b.port, "cpu": b.cpu, "memory": b.memory, "health": b.health, "command": b.command.strip(),
                    "volume": b.volume, "volume_gb": b.volume_gb, "secrets": secret_keys, "env": env_name}
        scale = {"replicas": b.replicas, "autoscale_max": b.autoscale_max}
        routes = {"public": b.public, "domains": domains}
        old = {**(self._settings(cur) if cur else {}), **json.loads(_ann(cur or {}).get("axor.dev/routes", "{}"))}
        new = {**settings, **scale, **routes}
        cause = (f"{me['username']} created it" if create else f"{me['username']} deployed {image}" if old.get("image") != image
                 else f"{me['username']} changed {', '.join(k for k in new if new[k] != old.get(k)) or 'nothing'}")
        probe = {"httpGet": {"path": b.health, "port": b.port}} if b.health else {"tcpSocket": {"port": b.port}}
        c = {"name": "app", "image": image, "ports": [{"name": "http", "containerPort": b.port}],
             "envFrom": [{"secretRef": {"name": env_name}}],
             "resources": {"limits": {"cpu": f"{int(b.cpu * 1000)}m", "memory": f"{b.memory}Mi"},
                           "requests": {"cpu": f"{max(10, int(b.cpu * 100))}m", "memory": f"{max(16, b.memory // 2)}Mi"}},
             "readinessProbe": {**probe, "periodSeconds": 5, "failureThreshold": 3},
             "securityContext": {"allowPrivilegeEscalation": False, "capabilities": {"drop": CAP_DROP}, "seccompProfile": {"type": "RuntimeDefault"}}}
        if b.health: c["livenessProbe"] = {**probe, "initialDelaySeconds": 30, "periodSeconds": 20, "failureThreshold": 6}
        if args: c["args"] = args
        pod = {"automountServiceAccountToken": False, "enableServiceLinks": False, "containers": [c]}
        if b.volume:
            c["volumeMounts"] = [{"name": "data", "mountPath": b.volume}]
            pod["volumes"] = [{"name": "data", "persistentVolumeClaim": {"claimName": f"{b.name}-data"}}]
            pvc = f"/api/v1/namespaces/{NS['apps']}/persistentvolumeclaims"
            if not self.k.get(f"{pvc}/{b.name}-data"):
                self.k.call("POST", pvc, body={"apiVersion": "v1", "kind": "PersistentVolumeClaim",
                                               "metadata": {"name": f"{b.name}-data", "labels": {LABEL["apps"]: b.name, "app.kubernetes.io/managed-by": "axor"}},
                                               "spec": {"accessModes": ["ReadWriteOnce"], "resources": {"requests": {"storage": f"{b.volume_gb}Gi"}}}})
        tpl_ann = self._template_meta("apps", b.name, settings, cause, cur)
        self.k.apply(f"/apis/apps/v1/namespaces/{NS['apps']}/deployments",
                     self._deployment("apps", b.name, routes, scale, pod, tpl_ann, "Recreate" if b.volume else "RollingUpdate"))
        self._service("apps", b.name, b.port)
        self._autoscale("apps", b.name, b.replicas, b.autoscale_max, b.cpu)
        self._routes("apps", b.name, routes, s)
        self._gc("apps", b.name)
        self._dns_quiet()
        self.db.log("app.create" if create else "app.update", me["username"], b.name, ip, cause[:200])
        return self.view("apps", b.name)

    # ---------- functions ----------
    def save_fn(self, me, b: FnIn, ip, create):
        self._ready()
        cur = self._common("functions", b, create)
        rt = RUNTIMES.get(b.runtime)
        if not rt: raise HTTPException(400, f"Runtimes: {', '.join(RUNTIMES)}.")
        handler = b.handler.strip() or rt["handler"]
        if not re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]{0,63}", handler): raise HTTPException(400, "The handler is a function name, e.g. " + rt["handler"] + ".")
        lines = [l.strip() for l in b.packages.splitlines() if l.strip() and not l.strip().startswith("#")]
        if len(lines) > 60: raise HTTPException(400, "At most 60 packages.")
        pat = PY_REQ if b.runtime == "python3.12" else NODE_PKG
        bad = next((l for l in lines if not pat.match(l)), None)
        if bad: raise HTTPException(400, f"{bad!r} isn't a package{' requirement (e.g. requests==2.32.3)' if b.runtime == 'python3.12' else ' (e.g. lodash or lodash@4.17.21)'}.")
        files = {rt["file"]: b.code, rt["boot"]: (FAAS / rt["boot"]).read_text()}
        if lines:
            if b.runtime == "python3.12": files["requirements.txt"] = "\n".join(lines) + "\n"
            else:
                deps = {}
                for l in lines:
                    at = l.rfind("@")
                    n, v = (l[:at], l[at + 1:]) if at > 0 else (l, "latest")
                    deps[n] = v.strip() or "latest"
                files["package.json"] = json.dumps({"name": b.name, "private": True, "dependencies": deps}, indent=2)
        code_name = self._object("functions", "configmaps", "ConfigMap", "code", b.name, "data", files)
        vals, secret_keys = self._env("functions", b.name, b.env, cur)
        env_name = self._object("functions", "secrets", "Secret", "env", b.name, "data", vals)
        settings = {"runtime": b.runtime, "handler": handler, "packages": "\n".join(lines), "cpu": b.cpu, "memory": b.memory,
                    "timeout": b.timeout, "secrets": secret_keys, "env": env_name, "code": code_name}
        scale = {"replicas": b.replicas, "autoscale_max": b.autoscale_max}
        routes = {"public": b.public, "domains": []}
        old = {**(self._settings(cur) if cur else {}), **json.loads(_ann(cur or {}).get("axor.dev/routes", "{}"))}
        new = {**settings, **scale, **routes}
        changed = [k for k in new if new[k] != old.get(k)]
        cause = f"{me['username']} created it" if create else f"{me['username']} changed {', '.join(changed) if changed else 'nothing'}"
        restricted = {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]}}
        env = [{"name": "FN_NAME", "value": b.name}, {"name": "FN_HANDLER", "value": handler}, {"name": "FN_TIMEOUT", "value": str(b.timeout)},
               {"name": "PORT", "value": "8080"}, {"name": "HOME", "value": "/tmp"}, {"name": "PYTHONDONTWRITEBYTECODE", "value": "1"},
               {"name": "NODE_ENV", "value": "production"}, {"name": "NODE_PATH", "value": "/deps/node_modules"}]
        mounts = [{"name": "code", "mountPath": "/code", "readOnly": True}, {"name": "boot", "mountPath": "/axor", "readOnly": True},
                  {"name": "deps", "mountPath": "/deps"}, {"name": "tmp", "mountPath": "/tmp"}]
        c = {"name": "fn", "image": rt["image"], "command": rt["cmd"], "env": env, "envFrom": [{"secretRef": {"name": env_name}}],
             "ports": [{"name": "http", "containerPort": 8080}], "volumeMounts": mounts, "securityContext": restricted,
             "resources": {"limits": {"cpu": f"{int(b.cpu * 1000)}m", "memory": f"{b.memory}Mi"},
                           "requests": {"cpu": f"{max(10, int(b.cpu * 100))}m", "memory": f"{max(32, b.memory // 2)}Mi"}},
             "readinessProbe": {"httpGet": {"path": "/__axor/health", "port": 8080}, "periodSeconds": 3, "failureThreshold": 2},
             "livenessProbe": {"httpGet": {"path": "/__axor/health", "port": 8080}, "initialDelaySeconds": 10, "periodSeconds": 20, "failureThreshold": 3}}
        pod = {"automountServiceAccountToken": False, "enableServiceLinks": False, "containers": [c],
               "securityContext": {"runAsNonRoot": True, "runAsUser": 1000, "runAsGroup": 1000, "fsGroup": 1000, "seccompProfile": {"type": "RuntimeDefault"}},
               "volumes": [{"name": "code", "configMap": {"name": code_name, "items": [{"key": k, "path": k} for k in files if k != rt["boot"]]}},
                           {"name": "boot", "configMap": {"name": code_name, "items": [{"key": rt["boot"], "path": rt["boot"]}]}},
                           {"name": "deps", "emptyDir": {"sizeLimit": "1Gi"}}, {"name": "tmp", "emptyDir": {"sizeLimit": "256Mi"}}]}
        if lines:
            pod["initContainers"] = [{"name": "deps", "image": rt["image"], "command": rt["install"], "securityContext": restricted,
                                      "env": [{"name": "HOME", "value": "/tmp"}, {"name": "npm_config_cache", "value": "/tmp/.npm"},
                                              {"name": "npm_config_update_notifier", "value": "false"}],
                                      "volumeMounts": [m for m in mounts if m["name"] in ("code", "deps", "tmp")],
                                      "resources": {"limits": {"cpu": "1", "memory": "1Gi"}, "requests": {"cpu": "100m", "memory": "128Mi"}}}]
        tpl_ann = self._template_meta("functions", b.name, settings, cause, cur)
        self.k.apply(f"/apis/apps/v1/namespaces/{NS['functions']}/deployments", self._deployment("functions", b.name, routes, scale, pod, tpl_ann))
        self._service("functions", b.name, 8080)
        self._autoscale("functions", b.name, b.replicas, b.autoscale_max, b.cpu)
        self._routes("functions", b.name, routes)
        self._gc("functions", b.name)
        self.db.log("function.create" if create else "function.update", me["username"], b.name, ip, cause[:200])
        return self.view("functions", b.name)

    def stats(self, name):
        """Calls, errors and durations from the function's own log lines (since its pods last started)."""
        self._ready()
        self._get("functions", name)
        calls = []
        for p in self.k.items(f"/api/v1/namespaces/{NS['functions']}/pods", {"labelSelector": f"{LABEL['functions']}={name}"}):
            try: text = self.k.logs(NS["functions"], p["metadata"]["name"], "fn", 5000)
            except KubeError: continue
            for ln in text.splitlines():
                t, _, msg = ln.partition(" ")
                if not msg.startswith('{"axor": "call"') and not msg.startswith('{"axor":"call"'): continue
                try: x = json.loads(msg)
                except ValueError: continue
                calls.append((ts(t[:19] + "Z") if len(t) >= 19 else None, x.get("status", 0), x.get("ms", 0.0)))
        ms = sorted(c[2] for c in calls)
        now = time.time()
        per_min = [0] * 60
        for t, _, _ in calls:
            if t and now - t < 3600: per_min[59 - min(59, max(0, int((now - t) // 60)))] += 1  # a line stamped "now" may be ahead
        q = lambda f: ms[min(len(ms) - 1, int(f * len(ms)))] if ms else None
        return {"calls": len(calls), "errors": sum(1 for c in calls if c[1] >= 500), "client_errors": sum(1 for c in calls if 400 <= c[1] < 500),
                "avg_ms": round(statistics.fmean(ms), 1) if ms else None, "p50_ms": q(0.5), "p95_ms": q(0.95), "max_ms": ms[-1] if ms else None,
                "last": max((c[0] for c in calls if c[0]), default=None), "per_minute": per_min}

def build(db, helpers, ip, data_dir, kube=None, dns=None):
    r = APIRouter(prefix="/api/platform")
    admin, sudo = helpers["admin"], helpers["sudo"]
    p = Platform(db, data_dir, kube, dns)
    r.state = {"platform": p, "guard": p.guard()}

    def call(fn, *a):
        try: return fn(*a)
        except KubeError as e: raise HTTPException(e.status if e.status in (400, 403, 404, 409, 422, 503) else 502, str(e))
        except DNSError as e: raise HTTPException(e.status, str(e))

    def kind_ok(kind):
        if kind not in NS: raise HTTPException(404, "Not found.")
        return kind

    @r.get("")
    def overview(req: Request):
        admin(req)
        return call(p.overview)

    @r.post("/sudo")
    def unlock(req: Request):  # asked before a form opens, so a sudo prompt can't replace a half-filled form
        sudo(req)
        return {"ok": True}

    @r.put("/settings")
    def settings(b: SettingsIn, req: Request):
        return call(p.save_settings, sudo(req), b, ip(req))

    @r.post("/sync")
    def sync(req: Request):
        me = sudo(req)
        p._ready()
        st = call(lambda: p.sync(routes=True))
        db.log("platform.sync", me["username"], "", ip(req), st["error"] or "ok")
        return call(p.overview)

    @r.post("/certificate")
    def renew(req: Request):
        me = sudo(req)
        p._ready()
        leaf = call(lambda: p.edge_cert(force=True))
        db.log("platform.certificate", me["username"], "", ip(req), leaf["fp"])
        return call(p.overview)

    @r.get("/ca.crt")
    def ca_cert():
        """AXoR's root certificate, to trust the platform's HTTPS before its domain is public (it isn't secret)."""
        pem = db.setting("platform.ca_cert")
        if not pem: raise HTTPException(404, "AXoR hasn't made its certificate authority yet.")
        return Response(pem, media_type="application/x-x509-ca-cert", headers={"Content-Disposition": 'attachment; filename="axor-ca.crt"'})

    @r.get("/delegation")
    def delegation(req: Request):
        admin(req)
        return call(p.delegation)

    @r.get("/templates")
    def templates(req: Request):
        admin(req)
        return {"templates": TEMPLATES, "runtimes": {k: {"title": v["title"], "handler": v["handler"], "image": v["image"],
                                                         "deps": "requirements.txt" if k.startswith("python") else "packages"} for k, v in RUNTIMES.items()}}

    @r.get("/{kind}")
    def items(kind: str, req: Request):
        admin(req)
        return call(p.list, kind_ok(kind))

    @r.post("/apps")
    def create_app(b: AppIn, req: Request):
        return call(p.save_app, sudo(req), b, ip(req), True)

    @r.put("/apps/{name}")
    def update_app(name: str, b: AppIn, req: Request):
        if b.name != name: raise HTTPException(400, "Apps can't be renamed.")
        return call(p.save_app, sudo(req), b, ip(req), False)

    @r.post("/functions")
    def create_fn(b: FnIn, req: Request):
        return call(p.save_fn, sudo(req), b, ip(req), True)

    @r.put("/functions/{name}")
    def update_fn(name: str, b: FnIn, req: Request):
        if b.name != name: raise HTTPException(400, "Functions can't be renamed.")
        return call(p.save_fn, sudo(req), b, ip(req), False)

    @r.get("/functions/{name}/stats")
    def fn_stats(name: str, req: Request):
        admin(req)
        return call(p.stats, name)

    @r.get("/{kind}/{name}")
    def view(kind: str, name: str, req: Request):
        admin(req)
        return call(p.view, kind_ok(kind), name)

    @r.delete("/{kind}/{name}")
    def delete(kind: str, name: str, req: Request, volume: bool = False):
        return call(p.delete, sudo(req), kind_ok(kind), name, volume, ip(req))

    @r.post("/{kind}/{name}/action")
    def act(kind: str, name: str, a: Act, req: Request):
        return call(p.act, sudo(req), kind_ok(kind), name, a.action, ip(req))

    @r.post("/{kind}/{name}/rollback")
    def rollback(kind: str, name: str, b: Rollback, req: Request):
        return call(p.rollback, sudo(req), kind_ok(kind), name, b.revision, ip(req))

    @r.get("/{kind}/{name}/logs")
    def logs(kind: str, name: str, req: Request, tail: int = 300):
        admin(req)
        return call(p.logs, kind_ok(kind), name, max(1, min(tail, 5000)))

    @r.post("/{kind}/{name}/request")
    def request(kind: str, name: str, b: Req, req: Request):
        admin(req)
        return call(p.request, kind_ok(kind), name, b)

    return r
