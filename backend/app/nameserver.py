"""DNS: the zones AXoR DNS (dns/, a service of its own) answers for, managed on the DNS page (admins only).

AXoR reaches the name server's API at DNS_URL with a shared secret (DNS_SECRET, or the file DNS_SECRET_FILE the
server writes on first start). The page lists zones and their records, adds, edits and removes records, changes a
zone's name servers, imports and exports BIND zone files, asks the server a question as a resolver would, checks
whether public resolvers see the zone delegated here, and shows query statistics.
Reads need an admin session; changes also need sudo and are audited. Records the platform keeps (owner "platform":
the AXoR address, *.apps and *.fn, custom app domains) and challenge records are shown but changed by the platform.
The platform's own zone can't be deleted here.
"""
import json, logging, os, urllib.error, urllib.parse, urllib.request
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

log = logging.getLogger("nameserver")
URL = (os.getenv("DNS_URL") or "").rstrip("/")
SETUP = "AXoR DNS isn't set up on this server (DNS_URL). It runs on Kubernetes: see k8s/ in the README."

class DNSError(Exception):
    def __init__(self, msg, status=502):
        super().__init__(msg); self.status = status

class NameServer:
    """Client for AXoR DNS."""
    def __init__(self, url=URL):
        self.url, self._secret = url, None

    @property
    def enabled(self): return bool(self.url)

    def secret(self):
        if self._secret is None:
            s = os.getenv("DNS_SECRET")
            if not s and os.getenv("DNS_SECRET_FILE"):
                try: s = Path(os.getenv("DNS_SECRET_FILE")).read_text().strip()
                except OSError: s = None  # the server hasn't written it yet: try again next call
            self._secret = s
        return self._secret

    def call(self, method, path, params=None, body=None, timeout=15):
        if not self.url: raise DNSError(SETUP, 503)
        if not self.secret(): raise DNSError("AXoR can't read the DNS server's secret yet (DNS_SECRET / DNS_SECRET_FILE).", 503)
        q = "?" + urllib.parse.urlencode(params) if params else ""
        h = {"Authorization": f"Bearer {self.secret()}"}
        data = None
        if body is not None: data, h["Content-Type"] = json.dumps(body).encode(), "application/json"
        try:
            with urllib.request.urlopen(urllib.request.Request(self.url + path + q, data=data, headers=h, method=method), timeout=timeout) as r:
                out = r.read()
        except urllib.error.HTTPError as e:
            if e.code == 401:
                self._secret = None
                raise DNSError("AXoR DNS rejected AXoR's secret. Check that both have the same DNS_SECRET.")
            try: detail = json.load(e).get("detail")
            except ValueError: detail = None
            raise DNSError(detail if isinstance(detail, str) else f"AXoR DNS answered HTTP {e.code}.", e.code if e.code in (400, 404, 409) else 502)
        except (urllib.error.URLError, OSError) as e:
            raise DNSError(f"Can't reach AXoR DNS at {self.url} ({getattr(e, 'reason', e)}).")
        return json.loads(out) if out.strip() else None

    def zone(self, name):
        try: return self.call("GET", f"/zones/{urllib.parse.quote(name)}")
        except DNSError as e:
            if e.status == 404: return None
            raise

def _q(z): return urllib.parse.quote(z, safe="")

class ZoneIn(BaseModel):
    name: str = Field(..., max_length=253)
    nameservers: list[str] = Field(default_factory=list, max_length=8)
    email: str = Field("", max_length=253)
    ttl: int = Field(300, ge=30, le=86400)
    ip: str | None = Field(None, max_length=45)

class ZoneSet(BaseModel):
    nameservers: list[str] | None = Field(None, max_length=8)
    email: str | None = Field(None, max_length=253)
    ttl: int | None = Field(None, ge=30, le=86400)

class RecordIn(BaseModel):
    name: str = Field("@", max_length=253)
    type: str = Field(..., max_length=8)
    value: str = Field(..., max_length=4100)
    ttl: int | None = Field(None, ge=30, le=604800)
    note: str = Field("", max_length=200)

class ImportIn(BaseModel):
    text: str = Field(..., max_length=2_000_000)
    replace: bool = False

def build(db, helpers, ip, ns=None, platform_zone=lambda: None, public_ip=lambda: None):
    r = APIRouter(prefix="/api/dns")
    admin, sudo = helpers["admin"], helpers["sudo"]
    d = ns or NameServer()
    r.state = {"dns": d}

    def call(*a, **k):
        try: return d.call(*a, **k)
        except DNSError as e: raise HTTPException(e.status, str(e))

    @r.get("")
    def overview(req: Request):
        admin(req)
        out = call("GET", "/zones")
        try: stats = d.call("GET", "/stats")
        except DNSError: stats = None
        return {**out, "stats": stats, "platform_zone": platform_zone(), "public_ip": public_ip()}

    @r.get("/stats")
    def stats(req: Request):
        admin(req)
        return call("GET", "/stats")

    @r.post("/zones")
    def create(b: ZoneIn, req: Request):
        me = sudo(req)
        body = b.model_dump()
        if not body["ip"]: body["ip"] = public_ip()  # glue for ns1/ns2.<zone>: this server
        out = call("POST", "/zones", body=body)
        db.log("dns.zone.create", me["username"], out["name"], ip(req), ", ".join(out["nameservers"]))
        return out

    @r.get("/zones/{zone}")
    def view(zone: str, req: Request):
        admin(req)
        return call("GET", f"/zones/{_q(zone)}")

    @r.patch("/zones/{zone}")
    def settings(zone: str, b: ZoneSet, req: Request):
        me = sudo(req)
        out = call("PATCH", f"/zones/{_q(zone)}", body=b.model_dump(exclude_none=True))
        db.log("dns.zone.update", me["username"], out["name"], ip(req), ", ".join(out["nameservers"]))
        return out

    @r.delete("/zones/{zone}")
    def delete(zone: str, req: Request):
        me = sudo(req)
        if zone.strip(".").lower() == (platform_zone() or ""):
            raise HTTPException(400, "This is the platform's domain: AXoR, apps and functions are served from it. Change the platform domain first.")
        call("DELETE", f"/zones/{_q(zone)}")
        db.log("dns.zone.delete", me["username"], zone, ip(req), "")
        return {"ok": True}

    @r.post("/zones/{zone}/records")
    def add(zone: str, b: RecordIn, req: Request):
        me = sudo(req)
        out = call("POST", f"/zones/{_q(zone)}/records", body=b.model_dump())
        db.log("dns.record.add", me["username"], f"{b.name}.{zone}", ip(req), f"{b.type} {b.value}"[:200])
        return out

    @r.put("/zones/{zone}/records/{rid}")
    def change(zone: str, rid: int, b: RecordIn, req: Request):
        me = sudo(req)
        out = call("PUT", f"/zones/{_q(zone)}/records/{rid}", body=b.model_dump())
        db.log("dns.record.update", me["username"], f"{b.name}.{zone}", ip(req), f"{b.type} {b.value}"[:200])
        return out

    @r.delete("/zones/{zone}/records/{rid}")
    def remove(zone: str, rid: int, req: Request):
        me = sudo(req)
        out = call("DELETE", f"/zones/{_q(zone)}/records/{rid}")
        db.log("dns.record.delete", me["username"], zone, ip(req), f"record {rid}")
        return out

    @r.get("/zones/{zone}/export")
    def export(zone: str, req: Request):
        admin(req)
        return call("GET", f"/zones/{_q(zone)}/export")

    @r.post("/zones/{zone}/import")
    def import_(zone: str, b: ImportIn, req: Request):
        me = sudo(req)
        out = call("POST", f"/zones/{_q(zone)}/import", body=b.model_dump(), timeout=60)
        db.log("dns.zone.import", me["username"], zone, ip(req), f"{out['added']} added, {out['skipped']} skipped" + (", replaced" if b.replace else ""))
        return out

    @r.get("/resolve")
    def resolve(name: str, req: Request, type: str = "A"):
        admin(req)
        return call("GET", "/resolve", {"name": name, "type": type})

    @r.get("/zones/{zone}/delegation")
    def delegation(zone: str, req: Request):
        admin(req)
        return call("GET", f"/zones/{_q(zone)}/delegation", timeout=20)

    return r
