"""AXoR DNS: this server's own authoritative name server, managed from AXoR's DNS page.

It answers for the zones AXoR gives it and nothing else. It never recurses, so it can't be used as an open resolver,
and questions about other names get REFUSED. Zones, records and settings live in SQLite (DNS_DATA/dns.db); every
answer comes from an in-memory index rebuilt after each change, and every change bumps the zone's SOA serial.

- DNS over UDP and TCP on DNS_PORT (5353 in the container, so it needs no privileges; the cluster maps the host's
  port 53 to it when k8s/cutover.sh opens it). Records: A, AAAA, CNAME, MX, TXT, NS (delegations), SRV, CAA, with
  wildcards (*.apps.example.com) as RFC 4592 has them. The SOA and the apex NS records come from the zone's settings.
- Over UDP, answers fit in 512 bytes, or the EDNS(0) size the client offers (1232 at most); bigger ones are sent
  truncated so resolvers retry over TCP. ANY gets the RFC 8482 short answer, and zone transfers are refused.
- UDP responses are limited per client network (/24 or /56) to DNS_RATE a second, so the server can't be used to
  amplify floods at a spoofed address. Every other response over the limit is sent truncated ("slip"), so a real
  resolver behind a busy network still gets through over TCP.
- AXoR manages it over HTTP on DNS_API_PORT with a shared secret (DNS_SECRET, or the file DNS_SECRET_FILE written on
  first start). The edge's Let's Encrypt resolver gets a second, narrower secret (DNS_ACME_SECRET[_FILE]) that can
  only put _acme-challenge TXT records in place for DNS-01 challenges (lego's "httpreq" provider: /acme/present,
  /acme/cleanup); they expire after ten minutes in case cleanup never comes.
Run: DNS_SECRET_FILE=/secret/dns.key uvicorn dns:app --port 8400
"""
import asyncio, base64, hmac, ipaddress, json, logging, os, re, secrets, socket, sqlite3, threading, time
from collections import Counter, deque
from pathlib import Path

from dnslib import AAAA, CAA, CNAME, EDNS0, MX, NS, QTYPE, RCODE, RR, SOA, SRV, TXT, A, DNSRecord
from dnslib.dns import RD
from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("dns")
DATA = Path(os.getenv("DNS_DATA", Path(__file__).resolve().parent / "var"))
PORT = int(os.getenv("DNS_PORT", "5353"))
BIND = [b.strip() for b in os.getenv("DNS_BIND", "0.0.0.0").split(",") if b.strip()]
RATE = max(1, int(os.getenv("DNS_RATE", "50")))  # UDP responses per second per client network
EDNS_MAX = 1232  # the DNS flag day 2020 size: no IP fragmentation
TYPES = ("A", "AAAA", "CNAME", "MX", "TXT", "NS", "SRV", "CAA")
MAX_ZONES, MAX_RECORDS = 500, 10_000
ACME_TTL, ACME_KEEP = 60, 600
LABEL = re.compile(r"^(?!-)[a-z0-9_-]{1,63}(?<!-)$")
DATA.mkdir(parents=True, exist_ok=True)

def _secret(env, file_env, default_name):
    if os.getenv(env): return os.getenv(env)
    path = Path(os.getenv(file_env) or Path(os.getenv("DNS_SECRET_FILE", DATA / "dns.key")).parent / default_name)
    if not path.exists():  # first start: make one; AXoR (or the edge) reads the same file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_urlsafe(32))
        os.chmod(path, 0o600)
    return path.read_text().strip()

SECRET = _secret("DNS_SECRET", "DNS_SECRET_FILE", "dns.key")
ACME_SECRET = _secret("DNS_ACME_SECRET", "DNS_ACME_SECRET_FILE", "acme.key")

# ---------- names and values ----------
def domain(name):
    """A zone or host name as lowercase ASCII without the final dot; ValueError if it isn't one."""
    n = (name or "").strip().rstrip(".").lower()
    try: n = n.encode("idna").decode() if any(ord(c) > 127 for c in n) else n
    except UnicodeError: raise ValueError(f"{name!r} isn't a valid domain name.")
    if not n or len(n) > 253 or not all(LABEL.match(p) for p in n.split(".")): raise ValueError(f"{name!r} isn't a valid domain name.")
    return n

def rel_name(name, zone):
    """A record's name inside its zone: '@' for the apex, else labels (a leading '*' for a wildcard)."""
    n = (name or "@").strip().lower().rstrip(".")
    if n in ("@", "", zone): return "@"
    if n.endswith("." + zone): n = n[: -len(zone) - 1]
    labels = n.split(".")
    if any(l == "*" for l in labels[1:]): raise ValueError("A wildcard '*' can only be the first label, e.g. *.apps.")
    domain(".".join(l for l in labels if l != "*") + "." + zone if labels != ["*"] else zone)
    return n

def fqdn(rel, zone): return (zone if rel == "@" else f"{rel}.{zone}") + "."

def _target(v):
    v = v.strip()
    return "." if v == "." else domain(v) + "."

def value(rtype, v):
    """Checks a record's value and returns it in zone-file form."""
    v = (v or "").strip()
    if not v: raise ValueError("The value is empty.")
    try:
        if rtype == "A": return str(ipaddress.IPv4Address(v))
        if rtype == "AAAA": return str(ipaddress.IPv6Address(v))
        if rtype in ("CNAME", "NS"): return _target(v)
        if rtype == "MX":
            pref, host = v.split(None, 1)
            if not 0 <= int(pref) <= 65535: raise ValueError
            return f"{int(pref)} {_target(host)}"
        if rtype == "SRV":
            pr, w, port, host = v.split()
            if not all(0 <= int(x) <= 65535 for x in (pr, w, port)): raise ValueError
            return f"{int(pr)} {int(w)} {int(port)} {_target(host)}"
        if rtype == "CAA":
            m = re.fullmatch(r'(\d{1,3})\s+(issue|issuewild|iodef)\s+"?([^"]*)"?', v)
            if not m or int(m[1]) > 255: raise ValueError
            return f'{int(m[1])} {m[2]} "{m[3]}"'
        if rtype == "TXT":
            v = v[1:-1] if len(v) > 1 and v[0] == v[-1] == '"' else v
            if len(v.encode()) > 4000 or any(ord(c) < 32 for c in v): raise ValueError
            return v
    except ValueError as e:
        if str(e) and "valid domain" in str(e): raise
    raise ValueError({"A": "An A record needs an IPv4 address, e.g. 203.0.113.10.", "AAAA": "An AAAA record needs an IPv6 address.",
                      "CNAME": "A CNAME needs a host name.", "NS": "An NS record needs a host name.",
                      "MX": "An MX record needs a preference and a host, e.g. 10 mail.example.com.",
                      "SRV": "An SRV record needs priority, weight, port and target, e.g. 10 5 5060 sip.example.com.",
                      "CAA": 'A CAA record needs flags, a tag and a value, e.g. 0 issue "letsencrypt.org".',
                      "TXT": "TXT values are at most 4000 bytes of printable text."}.get(rtype, "Unsupported record type."))

def rdata(rtype, v):
    if rtype == "A": return A(v)
    if rtype == "AAAA": return AAAA(v)
    if rtype == "CNAME": return CNAME(v)
    if rtype == "NS": return NS(v)
    if rtype == "MX": p, h = v.split(); return MX(h, int(p))
    if rtype == "SRV": p, w, port, h = v.split(); return SRV(int(p), int(w), int(port), h)
    if rtype == "CAA": f, tag, val = v.split(None, 2); return CAA(int(f), tag, val.strip('"'))
    if rtype == "TXT":
        b = v.encode()
        return TXT([b[i:i + 255] for i in range(0, len(b), 255)] or [b""])
    raise ValueError(rtype)

# ---------- storage ----------
class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.db.executescript("""
            PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS zones (name TEXT PRIMARY KEY, serial INTEGER NOT NULL, ttl INTEGER NOT NULL,
                nameservers TEXT NOT NULL, email TEXT NOT NULL, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS records (id INTEGER PRIMARY KEY, zone TEXT NOT NULL REFERENCES zones(name) ON DELETE CASCADE,
                name TEXT NOT NULL, type TEXT NOT NULL, ttl INTEGER NOT NULL, value TEXT NOT NULL, owner TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '', created REAL NOT NULL, updated REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS records_zone ON records(zone);""")

    def q(self, sql, args=()):
        with self.lock: return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def tx(self, fn):
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try: out = fn(self.db); self.db.execute("COMMIT"); return out
            except BaseException: self.db.execute("ROLLBACK"); raise

def _bump(db, zone):
    today = int(time.strftime("%Y%m%d00"))
    db.execute("UPDATE zones SET serial = MAX(serial + 1, ?) WHERE name=?", (today, zone))

# ---------- the index answers come from ----------
class Index:
    def __init__(self, zones, records):
        self.zones, self.rrsets, self.names = {}, {}, set()
        for z in zones:
            apex = z["name"] + "."
            self.zones[apex] = z
            ns = json.loads(z["nameservers"])
            mail = z["email"].replace("@", ".", 1) if "@" in z["email"] else z["email"]
            self._add(apex, "SOA", z["ttl"], SOA(ns[0] if ns else apex, domain(mail) + ".",
                                                 (z["serial"], 3600, 600, 1209600, min(z["ttl"], 300))))
            for n in ns: self._add(apex, "NS", z["ttl"], NS(n))
        for r in records:
            name = fqdn(r["name"], r["zone"])
            self._add(name, r["type"], r["ttl"], rdata(r["type"], r["value"]))
            apex, p = r["zone"] + ".", name
            while p != apex and p.endswith("." + apex):  # empty non-terminals exist too (a.b exists if x.a.b does)
                self.names.add(p); p = p.split(".", 1)[1]
        self.order = sorted(self.zones, key=len, reverse=True)

    def _add(self, name, rtype, ttl, rd):
        self.rrsets.setdefault(name, {}).setdefault(getattr(QTYPE, rtype), []).append((ttl, rd))
        self.names.add(name)

    def zone_of(self, name):
        return next((z for z in self.order if name == z or name.endswith("." + z)), None)

    def _node(self, name, zone):
        """(rrsets, synthesized from a wildcard) for a name in a zone, or (None, False) when it doesn't exist."""
        if name in self.rrsets: return self.rrsets[name], False
        if name in self.names: return {}, False
        p = name.split(".", 1)[1]
        while p != zone and p not in self.names: p = p.split(".", 1)[1]  # the closest encloser
        w = self.rrsets.get("*." + p)
        return (w, True) if w else (None, False)

    def _cut(self, name, zone):
        """The highest delegation (NS below the apex) on the way down to a name, if any."""
        labels = name[: -len(zone)].rstrip(".").split(".") if name != zone else []
        for i in range(len(labels) - 1, -1, -1):
            n = ".".join(labels[i:]) + "." + zone
            if QTYPE.NS in self.rrsets.get(n, {}): return n
        return None

    def lookup(self, qname, qtype):
        """(rcode, authoritative, answer, authority, additional) as lists of RR."""
        name = qname.lower().rstrip(".") + "."
        zone = self.zone_of(name)
        if not zone: return RCODE.REFUSED, False, [], [], []
        if qtype == QTYPE.ANY: return RCODE.NOERROR, True, [RR(qname, QTYPE.HINFO, ttl=3600, rdata=RD(b"\x07RFC8482\x00"))], [], []
        answer, owner = [], qname
        for hop in range(8):
            cut = self._cut(name, zone)
            if cut:
                if hop: break  # a CNAME into a delegated name: the resolver follows it from here
                ns = [RR(cut, QTYPE.NS, ttl=t, rdata=rd) for t, rd in self.rrsets[cut][QTYPE.NS]]
                return RCODE.NOERROR, False, [], ns, self._glue(rd.label for _, rd in self.rrsets[cut][QTYPE.NS])
            node, _ = self._node(name, zone)
            soa = [RR(zone, QTYPE.SOA, ttl=min(self.zones[zone]["ttl"], 300), rdata=self.rrsets[zone][QTYPE.SOA][0][1])]
            if node is None: return RCODE.NXDOMAIN, True, answer, soa, []
            if qtype in node:
                answer += [RR(owner, qtype, ttl=t, rdata=rd) for t, rd in node[qtype]]
                targets = [getattr(rd, "label", None) or getattr(rd, "target", None) for _, rd in node[qtype]] if qtype in (QTYPE.MX, QTYPE.SRV, QTYPE.NS) else []
                return RCODE.NOERROR, True, answer, [], self._glue(t for t in targets if t)
            if QTYPE.CNAME in node and qtype != QTYPE.CNAME:
                t, rd = node[QTYPE.CNAME][0]
                answer.append(RR(owner, QTYPE.CNAME, ttl=t, rdata=rd))
                target = str(rd.label).lower()
                zone = self.zone_of(target)
                if not zone or target in (str(r.rname).lower() for r in answer): break  # outside our zones, or a loop
                name = owner = target
                continue
            return RCODE.NOERROR, True, answer, ([] if answer else soa), []
        return RCODE.NOERROR, True, answer, [], []

    def _glue(self, hosts):
        out = []
        for h in hosts:
            h = str(h).lower()
            for t in (QTYPE.A, QTYPE.AAAA):
                out += [RR(h, t, ttl=ttl, rdata=rd) for ttl, rd in self.rrsets.get(h, {}).get(t, [])]
        return out

# ---------- the name server ----------
class Stats:
    def __init__(self):
        self.lock = threading.Lock()
        self.total, self.rcodes, self.types, self.names = 0, Counter(), Counter(), Counter()
        self.limited, self.started = 0, time.time()
        self.per_sec = deque(maxlen=600)  # [second, queries] for the last ten minutes
        self.recent = deque(maxlen=300)

    def note(self, client, proto, qname, qtype, rcode):
        now = time.time()
        with self.lock:
            self.total += 1; self.rcodes[rcode] += 1; self.types[qtype] += 1
            if len(self.names) > 5000: self.names = Counter(dict(self.names.most_common(500)))
            self.names[qname.lower()] += 1
            s = int(now)
            if self.per_sec and self.per_sec[-1][0] == s: self.per_sec[-1][1] += 1
            else: self.per_sec.append([s, 1])
            self.recent.append({"t": round(now, 3), "client": client, "proto": proto, "name": qname, "type": qtype, "rcode": rcode})

    def view(self):
        with self.lock:
            return {"total": self.total, "limited": self.limited, "since": self.started, "rcodes": dict(self.rcodes),
                    "types": dict(self.types.most_common(12)), "top": self.names.most_common(15),
                    "per_sec": [list(x) for x in self.per_sec], "recent": list(self.recent)[::-1]}

class Limiter:
    def __init__(self, rate):
        self.rate, self.buckets, self.slip, self.last_sweep = rate, {}, {}, time.monotonic()

    def allow(self, ip):
        """True to answer, False to drop; 'slip' to send a truncated reply."""
        try: a = ipaddress.ip_address(ip)
        except ValueError: return True
        if a.is_loopback: return True
        net = str(ipaddress.ip_network(f"{ip}/{24 if a.version == 4 else 56}", strict=False))
        now = time.monotonic()
        if now - self.last_sweep > 60:
            self.buckets = {k: v for k, v in self.buckets.items() if now - v[1] < 60}; self.slip.clear(); self.last_sweep = now
        tokens, t = self.buckets.get(net, (self.rate * 2, now))
        tokens = min(self.rate * 2, tokens + (now - t) * self.rate)
        if tokens >= 1: self.buckets[net] = (tokens - 1, now); return True
        self.buckets[net] = (tokens, now)
        self.slip[net] = self.slip.get(net, 0) + 1
        return "slip" if self.slip[net] % 2 == 0 else False

class Server:
    def __init__(self, store):
        self.store, self.stats, self.limiter = store, Stats(), Limiter(RATE)
        self.index, self.transports = Index([], []), []
        self.reload()

    def reload(self):
        with self.store.lock:
            zones = self.store.q("SELECT * FROM zones")
            records = self.store.q("SELECT * FROM records WHERE owner != 'acme' OR updated > ?", (time.time() - ACME_KEEP,))
        self.index = Index(zones, records)

    def answer(self, data, client, proto):
        """The response to a query as bytes, the UDP size limit it must fit, or None to send nothing."""
        try: req = DNSRecord.parse(data)
        except Exception: return None, 0  # not DNS: no answer at all
        if req.header.qr or not req.questions: return None, 0
        opt = next((r for r in req.ar if r.rtype == QTYPE.OPT), None)
        limit = min(max(512, opt.rclass), EDNS_MAX) if opt else 512
        reply = req.reply(ra=0, aa=0)
        reply.header.rd, reply.header.ad = req.header.rd, 0  # no DNSSEC here: never claim answers are authenticated
        q = req.questions[0]
        qname, qtype = str(q.qname), q.qtype
        if opt: reply.add_ar(EDNS0(udp_len=EDNS_MAX))
        if req.header.opcode != 0: reply.header.rcode = RCODE.NOTIMP
        elif qtype in (QTYPE.AXFR, QTYPE.IXFR) or q.qclass not in (1, 255): reply.header.rcode = RCODE.REFUSED
        else:
            rcode, aa, ans, auth, add = self.index.lookup(qname, qtype)
            reply.header.rcode, reply.header.aa = rcode, int(aa)
            for r in ans: reply.add_answer(r)
            for r in auth: reply.add_auth(r)
            for r in add: reply.add_ar(r)
        self.stats.note(client, proto, qname, QTYPE.get(qtype, str(qtype)), RCODE.get(reply.header.rcode))
        return reply, limit

    @staticmethod
    def pack(reply, limit=None):
        out = reply.pack()
        if limit and len(out) > limit:  # over UDP: send the header and question only, with TC, and let TCP carry it
            reply.rr, reply.auth = [], []
            reply.ar = [r for r in reply.ar if r.rtype == QTYPE.OPT]
            reply.header.tc = 1
            out = reply.pack()
        return out

    # ---------- transports ----------
    async def start(self):
        loop = asyncio.get_running_loop()
        for host in BIND:
            fam = socket.AF_INET6 if ":" in host else socket.AF_INET
            t, _ = await loop.create_datagram_endpoint(lambda: _UDP(self), local_addr=(host, PORT), family=fam)
            tcp = await asyncio.start_server(self._tcp, host, PORT, family=fam, limit=65536, backlog=256)
            self.transports += [t, tcp]
            log.info("answering on %s port %s (UDP and TCP)", host, PORT)

    async def _tcp(self, reader, writer):
        client = writer.get_extra_info("peername")[0]
        try:
            for _ in range(100):  # queries per connection
                n = int.from_bytes(await asyncio.wait_for(reader.readexactly(2), 10), "big")
                data = await asyncio.wait_for(reader.readexactly(n), 10)
                reply, _ = self.answer(data, client, "tcp")
                if reply is None: break
                out = self.pack(reply)
                writer.write(len(out).to_bytes(2, "big") + out); await writer.drain()
        except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionError, OSError): pass
        finally:
            writer.close()

class _UDP(asyncio.DatagramProtocol):
    def __init__(self, srv): self.srv = srv

    def connection_made(self, transport): self.t = transport

    def datagram_received(self, data, addr):
        ok = self.srv.limiter.allow(addr[0])
        if ok is False:
            self.srv.stats.limited += 1; return
        reply, limit = self.srv.answer(data, addr[0], "udp")
        if reply is None: return
        if ok == "slip": limit = 0  # truncated: the client retries over TCP, which a spoofed address can't
        out = self.srv.pack(reply, limit or 1)
        self.t.sendto(out, addr)

store = Store(DATA / "dns.db")
srv = Server(store)

# ---------- zones and records ----------
def _zone(name):
    try: z = domain(name)
    except ValueError as e: raise HTTPException(400, str(e))
    rows = store.q("SELECT * FROM zones WHERE name=?", (z,))
    if not rows: raise HTTPException(404, f"There's no zone {z}.")
    return rows[0]

def _zone_out(z, records=None):
    out = {"name": z["name"], "serial": z["serial"], "ttl": z["ttl"], "nameservers": [n.rstrip(".") for n in json.loads(z["nameservers"])],
           "email": z["email"], "created": z["created"]}
    if records is not None: out["records"] = records
    return out

def _check(db, zone, name, rtype, val, rid=None):
    """Rules a zone must keep: no CNAME at the apex or next to other records, and no exact duplicates."""
    rows = [dict(r) for r in db.execute("SELECT id, type, value FROM records WHERE zone=? AND name=? AND owner != 'acme'", (zone, name)) if r["id"] != rid]
    if rtype == "CNAME":
        if name == "@": raise HTTPException(400, "The zone's apex can't be a CNAME (it has the SOA and NS records). Use an A record.")
        if rows: raise HTTPException(409, f"{fqdn(name, zone)} already has records, so it can't also be a CNAME.")
    elif any(r["type"] == "CNAME" for r in rows):
        raise HTTPException(409, f"{fqdn(name, zone)} is a CNAME, so it can't have other records.")
    if rtype == "NS" and name == "@": raise HTTPException(400, "The apex's NS records are the zone's name servers: change them in the zone's settings.")
    if any(r["type"] == rtype and r["value"] == val for r in rows): raise HTTPException(409, "That record already exists.")

class ZoneIn(BaseModel):
    name: str = Field(..., max_length=253)
    nameservers: list[str] = Field(default_factory=list, max_length=8)
    email: str = Field("", max_length=253)
    ttl: int = Field(300, ge=30, le=86400)
    ip: str | None = Field(None, max_length=45)  # A (or AAAA) record for the zone's own name servers (glue)

class ZoneSet(BaseModel):
    nameservers: list[str] | None = Field(None, max_length=8)
    email: str | None = Field(None, max_length=253)
    ttl: int | None = Field(None, ge=30, le=86400)

class RecordIn(BaseModel):
    name: str = Field("@", max_length=253)
    type: str
    value: str = Field(..., max_length=4100)
    ttl: int | None = Field(None, ge=30, le=604800)
    note: str = Field("", max_length=200)

class Owned(BaseModel):
    records: list[RecordIn] = Field(default_factory=list, max_length=500)

class ImportIn(BaseModel):
    text: str = Field(..., max_length=2_000_000)
    replace: bool = False

class Acme(BaseModel):
    fqdn: str = Field(..., max_length=253)
    value: str = Field(..., max_length=200)

app = FastAPI(title="AXoR DNS", docs_url=None, redoc_url=None, openapi_url=None)

def auth(req: Request):
    if not hmac.compare_digest(req.headers.get("authorization", "").encode(), f"Bearer {SECRET}".encode()):
        raise HTTPException(401, "Bad or missing secret.")

def acme_auth(req: Request):
    h = req.headers.get("authorization", "")
    try: pw = base64.b64decode(h[6:]).decode().partition(":")[2] if h.startswith("Basic ") else ""  # any user name: lego sends "acme"
    except (ValueError, UnicodeError): pw = ""
    if not hmac.compare_digest(pw.encode(), ACME_SECRET.encode()):
        raise HTTPException(401, "Bad or missing ACME credentials.")

@app.on_event("startup")
async def _start():
    await srv.start()

@app.get("/health")
def health():
    return {"ok": True, "zones": len(srv.index.zones)}

@app.get("/zones", dependencies=[Depends(auth)])
def zones():
    counts = dict((r["zone"], r["n"]) for r in store.q("SELECT zone, COUNT(*) n FROM records WHERE owner != 'acme' GROUP BY zone"))
    return {"zones": [{**_zone_out(z), "records": counts.get(z["name"], 0)} for z in store.q("SELECT * FROM zones ORDER BY name")],
            "port": PORT, "bind": BIND, "rate": RATE}

@app.post("/zones", dependencies=[Depends(auth)])
def create_zone(b: ZoneIn):
    try:
        name = domain(b.name)
        ns = [_target(n) for n in (b.nameservers or [f"ns1.{name}", f"ns2.{name}"])]
        email = b.email.strip() or f"hostmaster@{name}"
        domain(email.replace("@", ".", 1))
        ip = ipaddress.ip_address(b.ip) if b.ip else None
    except ValueError as e: raise HTTPException(400, str(e))
    if not ns: raise HTTPException(400, "A zone needs at least one name server.")
    now = time.time()
    def do(db):
        if db.execute("SELECT 1 FROM zones WHERE name=?", (name,)).fetchone(): raise HTTPException(409, f"{name} is already a zone here.")
        if db.execute("SELECT COUNT(*) FROM zones").fetchone()[0] >= MAX_ZONES: raise HTTPException(400, f"At most {MAX_ZONES} zones.")
        db.execute("INSERT INTO zones VALUES (?,?,?,?,?,?)", (name, int(time.strftime("%Y%m%d01")), b.ttl, json.dumps(ns), email, now))
        for n in ns:  # glue for name servers inside the zone itself
            if ip and n.endswith("." + name + "."):
                db.execute("INSERT INTO records (zone, name, type, ttl, value, owner, note, created, updated) VALUES (?,?,?,?,?,?,?,?,?)",
                           (name, rel_name(n, name), "A" if ip.version == 4 else "AAAA", b.ttl, str(ip), "zone", "Name server", now, now))
    store.tx(do); srv.reload()
    return view_zone(name)

@app.get("/zones/{zone}", dependencies=[Depends(auth)])
def view_zone(zone: str):
    z = _zone(zone)
    recs = store.q("SELECT * FROM records WHERE zone=? AND (owner != 'acme' OR updated > ?) ORDER BY name='@' DESC, name, type, value",
                   (z["name"], time.time() - ACME_KEEP))
    return _zone_out(z, [{k: r[k] for k in ("id", "name", "type", "ttl", "value", "owner", "note", "updated")} for r in recs])

@app.patch("/zones/{zone}", dependencies=[Depends(auth)])
def set_zone(zone: str, b: ZoneSet):
    z = _zone(zone)
    try:
        ns = [_target(n) for n in b.nameservers] if b.nameservers is not None else json.loads(z["nameservers"])
        email = b.email.strip() if b.email else z["email"]
        domain(email.replace("@", ".", 1))
    except ValueError as e: raise HTTPException(400, str(e))
    if not ns: raise HTTPException(400, "A zone needs at least one name server.")
    def do(db):
        db.execute("UPDATE zones SET nameservers=?, email=?, ttl=? WHERE name=?", (json.dumps(ns), email, b.ttl or z["ttl"], z["name"]))
        _bump(db, z["name"])
    store.tx(do); srv.reload()
    return view_zone(z["name"])

@app.delete("/zones/{zone}", dependencies=[Depends(auth)])
def delete_zone(zone: str):
    z = _zone(zone)
    store.tx(lambda db: db.execute("DELETE FROM zones WHERE name=?", (z["name"],))); srv.reload()
    return {"ok": True}

def _record(z, b):
    rtype = b.type.upper()
    if rtype not in TYPES: raise HTTPException(400, f"Record types: {', '.join(TYPES)}.")
    try: return rel_name(b.name, z["name"]), rtype, value(rtype, b.value)
    except ValueError as e: raise HTTPException(400, str(e))

@app.post("/zones/{zone}/records", dependencies=[Depends(auth)])
def add_record(zone: str, b: RecordIn):
    z = _zone(zone)
    name, rtype, val = _record(z, b)
    now = time.time()
    def do(db):
        if db.execute("SELECT COUNT(*) FROM records WHERE zone=?", (z["name"],)).fetchone()[0] >= MAX_RECORDS:
            raise HTTPException(400, f"At most {MAX_RECORDS} records a zone.")
        _check(db, z["name"], name, rtype, val)
        rid = db.execute("INSERT INTO records (zone, name, type, ttl, value, note, created, updated) VALUES (?,?,?,?,?,?,?,?)",
                         (z["name"], name, rtype, b.ttl or z["ttl"], val, b.note.strip(), now, now)).lastrowid
        _bump(db, z["name"]); return rid
    rid = store.tx(do); srv.reload()
    return {"ok": True, "id": rid}

@app.put("/zones/{zone}/records/{rid}", dependencies=[Depends(auth)])
def set_record(zone: str, rid: int, b: RecordIn):
    z = _zone(zone)
    name, rtype, val = _record(z, b)
    def do(db):
        row = db.execute("SELECT owner FROM records WHERE id=? AND zone=?", (rid, z["name"])).fetchone()
        if not row: raise HTTPException(404, "There's no such record.")
        if row["owner"] not in ("", "zone"): raise HTTPException(409, f"This record is kept up to date by {row['owner']}: change it there.")
        _check(db, z["name"], name, rtype, val, rid)
        db.execute("UPDATE records SET name=?, type=?, ttl=?, value=?, note=?, updated=? WHERE id=?",
                   (name, rtype, b.ttl or z["ttl"], val, b.note.strip(), time.time(), rid))
        _bump(db, z["name"])
    store.tx(do); srv.reload()
    return {"ok": True}

@app.delete("/zones/{zone}/records/{rid}", dependencies=[Depends(auth)])
def delete_record(zone: str, rid: int):
    z = _zone(zone)
    def do(db):
        row = db.execute("SELECT owner FROM records WHERE id=? AND zone=?", (rid, z["name"])).fetchone()
        if not row: raise HTTPException(404, "There's no such record.")
        if row["owner"] not in ("", "zone"): raise HTTPException(409, f"This record is kept up to date by {row['owner']}: change it there.")
        db.execute("DELETE FROM records WHERE id=?", (rid,)); _bump(db, z["name"])
    store.tx(do); srv.reload()
    return {"ok": True}

@app.put("/zones/{zone}/owned/{owner}", dependencies=[Depends(auth)])
def set_owned(zone: str, owner: str, b: Owned):
    """Replaces every record one manager (e.g. AXoR's platform) keeps in a zone; the SOA serial moves only on a change."""
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,30}", owner) or owner in ("zone", "acme"): raise HTTPException(400, "Bad owner.")
    z = _zone(zone)
    want = sorted({(*_record(z, r), r.ttl or z["ttl"], r.note.strip()) for r in b.records})
    now = time.time()
    def do(db):
        have = sorted((r["name"], r["type"], r["value"], r["ttl"], r["note"]) for r in
                      db.execute("SELECT name, type, value, ttl, note FROM records WHERE zone=? AND owner=?", (z["name"], owner)))
        if have == want: return False
        db.execute("DELETE FROM records WHERE zone=? AND owner=?", (z["name"], owner))
        for name, rtype, val, ttl, note in want:
            _check(db, z["name"], name, rtype, val)
            db.execute("INSERT INTO records (zone, name, type, ttl, value, owner, note, created, updated) VALUES (?,?,?,?,?,?,?,?,?)",
                       (z["name"], name, rtype, ttl, val, owner, note, now, now))
        _bump(db, z["name"]); return True
    changed = store.tx(do)
    if changed: srv.reload()
    return {"ok": True, "changed": changed}

@app.get("/zones/{zone}/export", dependencies=[Depends(auth)])
def export(zone: str):
    z = _zone(zone)
    apex = z["name"] + "."
    lines = [f"; {z['name']}, exported by AXoR DNS {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}", f"$ORIGIN {apex}", f"$TTL {z['ttl']}"]
    node = srv.index.rrsets.get(apex, {})
    lines += [RR(apex, QTYPE.SOA, ttl=t, rdata=rd).toZone() for t, rd in node.get(QTYPE.SOA, [])]
    lines += [RR(apex, QTYPE.NS, ttl=t, rdata=rd).toZone() for t, rd in node.get(QTYPE.NS, [])]
    for r in store.q("SELECT * FROM records WHERE zone=? AND owner != 'acme' ORDER BY name='@' DESC, name, type", (z["name"],)):
        lines.append(RR(fqdn(r["name"], z["name"]), getattr(QTYPE, r["type"]), ttl=r["ttl"], rdata=rdata(r["type"], r["value"])).toZone())
    return {"text": "\n".join(lines) + "\n"}

@app.post("/zones/{zone}/import", dependencies=[Depends(auth)])
def import_zone(zone: str, b: ImportIn):
    """Reads a BIND zone file. SOA lines are skipped; the apex's NS records become the zone's name servers."""
    z = _zone(zone)
    apex = z["name"] + "."
    try: rrs = RR.fromZone(b.text, origin=apex, ttl=z["ttl"])
    except Exception as e: raise HTTPException(400, f"That zone file couldn't be read: {e}")
    rows, ns, skipped = [], [], 0
    for rr in rrs:
        t, owner = QTYPE.get(rr.rtype), str(rr.rname).lower()
        if t == "SOA" or not (owner == apex or owner.endswith("." + apex)): skipped += 1; continue
        if t == "NS" and owner == apex: ns.append(str(rr.rdata.label)); continue
        if t not in TYPES: skipped += 1; continue
        v = b"".join(rr.rdata.data).decode(errors="replace") if t == "TXT" else rr.rdata.toZone()
        try: rows.append((rel_name(owner, z["name"]), t, value(t, v), max(30, min(rr.ttl, 604800))))
        except ValueError: skipped += 1
    now = time.time()
    def do(db):
        if b.replace: db.execute("DELETE FROM records WHERE zone=? AND owner=''", (z["name"],))
        added = 0
        for name, t, v, ttl in rows:
            try: _check(db, z["name"], name, t, v)
            except HTTPException: continue
            db.execute("INSERT INTO records (zone, name, type, ttl, value, created, updated) VALUES (?,?,?,?,?,?,?)", (z["name"], name, t, ttl, v, now, now))
            added += 1
        if ns: db.execute("UPDATE zones SET nameservers=? WHERE name=?", (json.dumps([_target(n) for n in ns]), z["name"]))
        _bump(db, z["name"]); return added
    added = store.tx(do); srv.reload()
    return {"ok": True, "added": added, "skipped": skipped + len(rows) - added, "nameservers": bool(ns)}

@app.get("/resolve", dependencies=[Depends(auth)])
def resolve(name: str, type: str = "A"):
    """Asks this server, as a resolver would, and shows the reply like dig does."""
    qtype = getattr(QTYPE, type.upper(), None)
    if qtype is None: raise HTTPException(400, "Unknown record type.")
    try: q = DNSRecord.question(domain(name), type.upper())
    except ValueError as e: raise HTTPException(400, str(e))
    reply, _ = srv.answer(q.pack(), "127.0.0.1", "api")
    sec = lambda rrs: [r.toZone() for r in rrs if r.rtype != QTYPE.OPT]
    return {"rcode": RCODE.get(reply.header.rcode), "aa": bool(reply.header.aa), "answer": sec(reply.rr),
            "authority": sec(reply.auth), "additional": sec(reply.ar)}

@app.get("/zones/{zone}/delegation", dependencies=[Depends(auth)])
def delegation(zone: str, resolvers: str = "1.1.1.1,8.8.8.8"):
    """What public resolvers say the zone's name servers are, next to what this server says."""
    z = _zone(zone)
    want = sorted(n.rstrip(".") for n in json.loads(z["nameservers"]))
    out = []
    for ip in resolvers.split(",")[:3]:
        try:
            ipaddress.ip_address(ip)
            r = DNSRecord.parse(DNSRecord.question(z["name"], "NS").send(ip, 53, timeout=3))
            got = sorted(str(x.rdata.label).rstrip(".").lower() for x in r.rr if x.rtype == QTYPE.NS)
            out.append({"resolver": ip, "rcode": RCODE.get(r.header.rcode), "nameservers": got, "match": got == want})
        except (OSError, ValueError, socket.timeout) as e:
            out.append({"resolver": ip, "error": str(e) or "no answer", "nameservers": [], "match": False})
    return {"zone": z["name"], "nameservers": want, "public": out, "delegated": any(x["match"] for x in out)}

@app.get("/stats", dependencies=[Depends(auth)])
def stats():
    return srv.stats.view()

# ---------- ACME DNS-01 (lego's httpreq provider) ----------
@app.post("/acme/present", dependencies=[Depends(acme_auth)])
def acme_present(b: Acme):
    name = domain(b.fqdn)
    if not name.startswith("_acme-challenge."): raise HTTPException(400, "Only _acme-challenge names.")
    z = srv.index.zone_of(name + ".")
    if not z: raise HTTPException(404, f"{name} isn't in a zone this server answers for.")
    zone, now = z.rstrip("."), time.time()
    def do(db):
        db.execute("DELETE FROM records WHERE owner='acme' AND updated < ?", (now - ACME_KEEP,))
        db.execute("INSERT INTO records (zone, name, type, ttl, value, owner, note, created, updated) VALUES (?,?,?,?,?,?,?,?,?)",
                   (zone, rel_name(name, zone), "TXT", ACME_TTL, value("TXT", b.value), "acme", "Let's Encrypt challenge", now, now))
        _bump(db, zone)
    store.tx(do); srv.reload()
    log.info("acme challenge for %s", name)
    return {"ok": True}

@app.post("/acme/cleanup", dependencies=[Depends(acme_auth)])
def acme_cleanup(b: Acme):
    name = domain(b.fqdn)
    z = srv.index.zone_of(name + ".")
    if not z: return {"ok": True}
    zone = z.rstrip(".")
    def do(db):
        db.execute("DELETE FROM records WHERE owner='acme' AND zone=? AND name=? AND value=?", (zone, rel_name(name, zone), b.value.strip()))
        _bump(db, zone)
    store.tx(do); srv.reload()
    return {"ok": True}
