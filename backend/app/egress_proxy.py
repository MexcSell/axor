"""AXoR egress: the only way out to the internet for sandbox runs that a team has given internet (k8s/base/57-egress.yaml).

It runs as its own pod (namespace axor-egress) from AXoR's web image: `python /app/backend/app/egress_proxy.py`. Stdlib only.

- Proxy (EGRESS_PORT, 3128): HTTP CONNECT (HTTPS, any TLS) and plain http:// requests, which is what pip, npm, git over HTTPS,
  curl, wget, requests and httpx speak when HTTP(S)_PROXY is set. Every connection carries a run's token as the proxy user
  (`http://<token>:x@egress…:3128`); a token AXoR didn't register, or one whose run ended, gets 407.
- Never inside: the name is resolved here and every address it resolves to must be a public one (ipaddress.is_global), and not
  in EGRESS_BLOCK (the server's own public IP); the connection then goes to the address that was checked, so a name can't
  rebind to an internal address in between. The pod's NetworkPolicy blocks the same ranges again.
- Only the ports in EGRESS_PORTS (80 and 443 by default): no mail, no IRC, no raw TCP elsewhere.
- Per run: a cap on bytes sent out (exfiltration) and on bytes received, a rate limit each way, a cap on open connections, and
  a record of every host reached (connections, bytes each way) and every refusal. AXoR reads it when the run ends.
- Exit address (EGRESS_UPSTREAM, optional): http://user:pass@host:port of a proxy elsewhere (a small VPS); every connection
  then leaves through it, so abuse reports land on that address, not on this server's. Unset: the server's own address.
- Control (EGRESS_CONTROL_PORT, 3129), only for AXoR's web pod (NetworkPolicy) and only with EGRESS_SECRET:
  POST /runs {token, up_mb, down_mb, ttl_s} registers a run; GET /runs/<token> reads its record; DELETE /runs/<token> ends
  it (open connections are cut) and returns the record; GET /health says whether an exit proxy is set
  (no secret: it is the health answer; `python egress_proxy.py --health` checks it and the proxy port, for the Docker HEALTHCHECK).
- Two optional fields on POST /runs (AEF, D-032 X4; without them a run and its record are exactly as before):
  `deny`: hosts refused for this run even when its lists would allow them (the host or anything under it). Its one use, and
  the reason its refusal text says so: a mission's policy names the package indexes the Owner hasn't approved here. It wins
  over `hosts` and `hosts_exact`. A list with an entry that isn't a host name, or with more than DENY_MAX entries, is
  refused whole (400, nothing registered): a run never gets less denied than was asked for.
  What it is not: enforcement. It is a blocklist of known names on a run that otherwise reaches the public web. It doesn't
  stop an install from a mirror, a Git URL, a tarball on any web host or an index nobody listed, and the proxy sees only the
  CONNECT host (or a plain-http URL's host), never what is asked of the far side inside TLS. Only a host list (`hosts`,
  `hosts_exact`) enforces what a run can reach.
  `https_only`: true lets the run speak HTTPS on port 443 and nothing else: a plain http:// request, or a CONNECT to another
  port, is refused and listed ("only https on port 443 for this run"). A mission's allowlist for package installs uses it, so
  an index can't be read, nor a package fetched, over an unencrypted connection.
  `conns`: true keeps each connection the run made (when, host, port, bytes each way, how long), finished or broken off,
  at most CONNS_KEPT; the record then has "conns" and "conns_dropped". Never a path, a header or a token. A request that
  was refused, or whose far side couldn't be reached, is in "refused", not here.
"""
import asyncio, base64, hashlib, hmac, ipaddress, json, os, re, sys, time
from urllib.parse import urlsplit

PORT = int(os.getenv("EGRESS_PORT_NUMBER", "3128"))      # not EGRESS_PORT: a Service named egress would set that (service links)
CONTROL = int(os.getenv("EGRESS_CONTROL_PORT_NUMBER", "3129"))
SECRET = os.getenv("EGRESS_SECRET", "")
UPSTREAM = os.getenv("EGRESS_UPSTREAM", "").strip()
PORTS = {int(p) for p in re.findall(r"\d+", os.getenv("EGRESS_PORTS", "80,443"))}
BLOCK = [ipaddress.ip_network(n.strip(), strict=False) for n in os.getenv("EGRESS_BLOCK", "").split(",") if n.strip()]
UP_RATE = float(os.getenv("EGRESS_UP_MBPS", "4")) * 1e6        # bytes per second per run, each way
DOWN_RATE = float(os.getenv("EGRESS_DOWN_MBPS", "40")) * 1e6
MAX_CONNS = int(os.getenv("EGRESS_RUN_CONNS", "64"))           # open at once, per run
MAX_TOTAL = int(os.getenv("EGRESS_TOTAL_CONNS", "1024"))
IDLE = int(os.getenv("EGRESS_IDLE_S", "300"))
HEAD_MAX = 65536
HOSTS_KEPT, REFUSALS_KEPT, CONNS_KEPT = 200, 50, 500
DENY_WHY, DENY_MAX = "package index not approved for this mission", 200
HTTPS_WHY = "only https on port 443 for this run"

RUNS = {}       # token -> run record
OPEN = [0]


def public(addr):
    """True for an address the internet can be reached at: no private, loopback, link-local, shared or reserved range,
    nothing in EGRESS_BLOCK. IPv4-mapped IPv6 addresses are judged as the IPv4 address they carry."""
    ip = ipaddress.ip_address(addr.split("%", 1)[0])
    if ip.version == 6 and ip.ipv4_mapped: ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast and not any(ip in n for n in BLOCK)


def allowed(host, allow, exact=()):
    """True when a run has no list at all, or the host is one of `allow`'s entries or a subdomain of one (D-013 D8-c: a VM runner
    job reaches only the registries it was opened for), or is exactly one of `exact` (the Owner's package indexes for builds:
    the named host and nothing under it, so no mirror or test index rides along)."""
    h = (host or "").lower().rstrip(".")
    return (not allow and not exact) or any(h == a or h.endswith("." + a) for a in allow) or h in exact


def denied(host, deny):
    """True when the host is one of a run's `deny` entries or under one. Checked before the run's lists: it wins over both."""
    h = (host or "").lower().rstrip(".")
    return any(h == d or h.endswith("." + d) for d in deny or ())


class Run:
    def __init__(self, token, up_cap, down_cap, ttl, allow=(), exact=(), deny=(), conns=False, https_only=False):
        self.token, self.up_cap, self.down_cap, self.expires = token, up_cap, down_cap, time.time() + ttl
        self.allow = tuple(a for a in (str(x).lower().strip(".") for x in allow or ()) if re.fullmatch(r"[a-z0-9.-]{3,253}", a))[:40]
        self.exact = tuple(a for a in (str(x).lower().strip(".") for x in exact or ()) if re.fullmatch(r"[a-z0-9.-]{3,253}", a))[:40]
        self.deny = tuple(a for a in (str(x).lower().strip(".") for x in deny or ()) if re.fullmatch(r"[a-z0-9.-]{3,253}", a))[:DENY_MAX]
        self.kept, self.dropped = ([] if conns else None), 0   # the run's connections, only when asked for
        self.https_only = bool(https_only)
        self.up = self.down = self.conns = 0
        self.hosts, self.refused, self.writers, self.ended = {}, [], set(), False
        self.buckets = {"up": [UP_RATE, time.monotonic()], "down": [DOWN_RATE, time.monotonic()]}

    def live(self): return not self.ended and time.time() < self.expires

    def refuse(self, host, why):
        if len(self.refused) < REFUSALS_KEPT: self.refused.append({"host": host[:200], "why": why, "at": round(time.time(), 1)})

    def host(self, host):
        if host not in self.hosts and len(self.hosts) >= HOSTS_KEPT: host = "(other hosts)"
        return self.hosts.setdefault(host, {"conns": 0, "up": 0, "down": 0})

    def keep(self, at, host, port, up, down):
        if self.kept is None: return
        if len(self.kept) >= CONNS_KEPT: self.dropped += 1; return
        self.kept.append({"at": round(at, 1), "host": host[:200], "port": port, "up": up, "down": down, "ms": int((time.time() - at) * 1000)})

    def record(self):
        return {"up_bytes": self.up, "down_bytes": self.down, "up_cap": self.up_cap, "down_cap": self.down_cap, "connections": self.conns,
                "hosts": dict(sorted(self.hosts.items(), key=lambda kv: -(kv[1]["up"] + kv[1]["down"]))), "refused": self.refused,
                "exit": "separate" if UPSTREAM else "server", "https_only": self.https_only,
                **({"conns": self.kept, "conns_dropped": self.dropped} if self.kept is not None else {})}

    async def throttle(self, way, n):
        """Token bucket: waits until n bytes fit the run's rate that way."""
        rate = UP_RATE if way == "up" else DOWN_RATE
        b = self.buckets[way]
        while True:
            now = time.monotonic()
            b[0], b[1] = min(rate, b[0] + (now - b[1]) * rate), now
            if b[0] >= n or b[0] >= rate: b[0] -= n; return
            await asyncio.sleep(min(1.0, (n - b[0]) / rate))

    def cut(self):
        self.ended = True
        for w in list(self.writers):
            try: w.close()
            except Exception: pass


def log(**kv): print(json.dumps({"t": round(time.time(), 1), **kv}), flush=True)


def _tag(token):
    """A run's name in the logs: a hash of its token, never any of its characters (D-019)."""
    return hashlib.sha256(str(token or "").encode()).hexdigest()[:10]


# ---------------------------------------------------------------- the proxy
async def read_head(reader):
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = await asyncio.wait_for(reader.read(4096), 30)
        if not chunk: raise ConnectionError("closed")
        data += chunk
        if len(data) > HEAD_MAX: raise ValueError("headers too large")
    head, rest = data.split(b"\r\n\r\n", 1)
    lines = head.decode("latin-1").split("\r\n")
    method, target, version = (lines[0].split(" ", 2) + ["", ""])[:3]
    headers = [tuple(x.strip() for x in ln.split(":", 1)) for ln in lines[1:] if ":" in ln]
    return method, target, version, headers, rest


def token_of(headers):
    for k, v in headers:
        if k.lower() == "proxy-authorization" and v.lower().startswith("basic "):
            try: user, _, pw = base64.b64decode(v[6:].strip()).decode().partition(":")
            except Exception: return ""
            return user if user in RUNS else pw if pw in RUNS else user
    return ""


async def answer(writer, code, text, extra=""):
    body = (text + "\n").encode()
    writer.write(f"HTTP/1.1 {code} {text[:60]}\r\n{extra}Content-Type: text/plain\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body)
    try: await writer.drain()
    except Exception: pass


async def resolve(host, port):
    """The public addresses of host (raises LookupError naming why not)."""
    try: ipaddress.ip_address(host.strip("[]")); infos = [(None, None, None, None, (host.strip("[]"), port))]
    except ValueError:
        try: infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=1)
        except OSError as e: raise LookupError(f"can't resolve {host}: {e}")
    addrs = sorted(dict.fromkeys(i[4][0] for i in infos), key=lambda a: ":" in a)  # IPv4 first: the exit proxy may have no IPv6
    if not addrs: raise LookupError(f"{host} has no address")
    bad = [a for a in addrs if not public(a)]
    if bad: raise LookupError(f"{host} points inside ({bad[0]}): only public internet addresses are allowed")
    return addrs


async def open_to(host, port, addrs):
    """A connection to host:port: through the exit proxy when one is set, else straight to the checked address."""
    if UPSTREAM:
        u = urlsplit(UPSTREAM)
        r, w = await asyncio.wait_for(asyncio.open_connection(u.hostname, u.port or 3128), 20)
        auth = ""
        if u.username:
            auth = "Proxy-Authorization: Basic " + base64.b64encode(f"{u.username}:{u.password or ''}".encode()).decode() + "\r\n"
        # the exit proxy connects to the address checked here, so its own resolver can't send it anywhere else
        a = addrs[0]
        target = f"[{a}]:{port}" if ":" in a else f"{a}:{port}"
        w.write(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n{auth}\r\n".encode()); await w.drain()
        _version, code, _reason, _h, _rest = await read_head(r)  # "HTTP/1.1 200 Connection established"
        if not code.startswith("2"): w.close(); raise ConnectionError(f"the exit proxy refused ({code})")
        return r, w
    last = None
    for a in addrs:
        try: return await asyncio.wait_for(asyncio.open_connection(a, port), 20)
        except (OSError, asyncio.TimeoutError) as e: last = e
    raise ConnectionError(f"can't connect to {host}:{port}: {last}")


async def pump(run, way, src, dst, stat, mine=None):
    cap = run.up_cap if way == "up" else run.down_cap
    try:
        while run.live():
            chunk = await asyncio.wait_for(src.read(65536), IDLE)
            if not chunk: break
            n = len(chunk)
            total = run.up if way == "up" else run.down
            if total + n > cap:
                run.refuse("*", f"{way}load cap of {cap // 1_000_000} MB reached; the run's connections were cut")
                log(ev="cap", run=_tag(getattr(run, "token", "")), way=way); run.cut(); break  # D-019: the run is named by a hash, never its token
            await run.throttle(way, n)
            if way == "up": run.up += n
            else: run.down += n
            stat[way] += n
            if mine is not None: mine[way] += n
            dst.write(chunk); await dst.drain()
    except (asyncio.TimeoutError, ConnectionError, OSError): pass
    finally:
        try: dst.write_eof() if dst.can_write_eof() else dst.close()
        except Exception: pass


async def client(reader, writer):
    run, writers, counted = None, [], None   # counted: (when, host, port, its own bytes) once the connection is one of the run's
    try:
        if OPEN[0] >= MAX_TOTAL: return await answer(writer, 503, "The egress proxy is full: try again shortly.")
        OPEN[0] += 1
        try: method, target, _v, headers, rest = await read_head(reader)
        except (ValueError, ConnectionError, asyncio.TimeoutError): return
        tok = token_of(headers)
        run = RUNS.get(tok)
        if not run or not run.live():
            return await answer(writer, 407, "This sandbox run has no internet (unknown or finished run).", 'Proxy-Authenticate: Basic realm="axor"\r\n')
        if method == "CONNECT":
            host, _, port = target.rpartition(":")
            host, port = host.strip("[]"), int(port) if port.isdigit() else 443
        else:
            u = urlsplit(target)
            if u.scheme != "http" or not u.hostname:
                return await answer(writer, 400, "Send http:// URLs or CONNECT (https goes through CONNECT).")
            host, port = u.hostname, u.port or 80
        if port not in PORTS:
            run.refuse(f"{host}:{port}", "port not allowed"); return await answer(writer, 403, f"Port {port} isn't allowed: only {sorted(PORTS)}.")
        if run.https_only and (method != "CONNECT" or port != 443):
            run.refuse(f"{host}:{port}", HTTPS_WHY); log(ev="refused", run=_tag(tok), host=host, why=HTTPS_WHY)
            return await answer(writer, 403, f"Only https on port 443 is allowed for this run (asked: {'http' if method != 'CONNECT' else 'a tunnel'} to {host}:{port}).")
        if denied(host, run.deny):
            run.refuse(host, DENY_WHY); log(ev="refused", run=_tag(tok), host=host, why=DENY_WHY)
            return await answer(writer, 403, f"{host} is a package index that isn't approved for this mission.")
        if not allowed(host, run.allow, run.exact):
            run.refuse(host, "host not on this run's list"); log(ev="refused", run=_tag(tok), host=host, why="not on the run's list")
            return await answer(writer, 403, f"{host} isn't on this run's list of hosts.")
        if len(run.writers) // 2 >= MAX_CONNS:
            run.refuse(host, "too many open connections"); return await answer(writer, 429, f"At most {MAX_CONNS} connections at once per run.")
        try: addrs = await resolve(host, port)
        except LookupError as e:
            run.refuse(host, str(e)); log(ev="refused", run=_tag(tok), host=host, why=str(e)); return await answer(writer, 403, str(e))
        try: ur, uw = await open_to(host, port, addrs)
        except (ConnectionError, OSError, asyncio.TimeoutError) as e:
            run.refuse(host, str(e)[:200]); return await answer(writer, 502, str(e)[:200])
        run.writers.update((writer, uw)); writers = [writer, uw]
        run.conns += 1
        stat = run.host(host.lower()); stat["conns"] += 1
        mine = {"up": 0, "down": 0}   # this connection's own bytes (stat is the host's total)
        counted = (time.time(), host.lower(), port, mine)
        if method == "CONNECT":
            writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n"); await writer.drain()
        else:  # plain http: the request again in origin form, without the proxy's headers, one request per connection
            u = urlsplit(target)
            path = (u.path or "/") + (f"?{u.query}" if u.query else "")
            keep = [(k, v) for k, v in headers if k.lower() not in ("proxy-authorization", "proxy-connection", "connection", "keep-alive")]
            head = f"{method} {path} HTTP/1.1\r\n" + "".join(f"{k}: {v}\r\n" for k, v in keep) + "Connection: close\r\n\r\n"
            raw = head.encode("latin-1")
            run.up += len(raw); stat["up"] += len(raw); mine["up"] += len(raw)
            uw.write(raw)
        if rest:
            run.up += len(rest); stat["up"] += len(rest); mine["up"] += len(rest); uw.write(rest)
        await uw.drain()
        up = asyncio.ensure_future(pump(run, "up", reader, uw, stat, mine))
        down = asyncio.ensure_future(pump(run, "down", ur, writer, stat, mine))
        await down  # the far side is done (or the run was cut): the connection is over, whatever the client still holds
        up.cancel()
        try: await up
        except asyncio.CancelledError: pass
        log(ev="conn", run=_tag(tok), host=host, port=port, up=stat["up"], down=stat["down"])
    except Exception as e:  # noqa: BLE001 - one connection's failure is logged, never the proxy's end
        log(ev="error", err=str(e)[:200])
    finally:
        OPEN[0] = max(0, OPEN[0] - 1)
        if counted: run.keep(counted[0], counted[1], counted[2], counted[3]["up"], counted[3]["down"])  # also one that failed while it ran
        for w in writers + [writer]:
            if run: run.writers.discard(w)
            try: w.close()
            except Exception: pass


# ---------------------------------------------------------------- control (AXoR's web pod only)
async def control(reader, writer):
    async def send(code, obj):
        body = json.dumps(obj).encode()
        writer.write(f"HTTP/1.1 {code} X\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body)
        await writer.drain(); writer.close()
    try:
        method, path, _v, headers, rest = await read_head(reader)
        h = {k.lower(): v for k, v in headers}
        if path == "/health": return await send(200, {"ok": True, "exit": "separate" if UPSTREAM else "server", "runs": len(RUNS), "open": OPEN[0]})
        if not SECRET or not hmac.compare_digest(h.get("x-egress-secret", ""), SECRET): return await send(403, {"error": "forbidden"})
        n = int(h.get("content-length") or 0)
        while len(rest) < min(n, 65536): rest += await reader.read(65536)
        for t in [t for t, r in RUNS.items() if time.time() > r.expires + 600]: RUNS.pop(t).cut()  # forgotten runs
        if method == "POST" and path == "/runs":
            b = json.loads(rest or b"{}")
            tok = str(b.get("token") or "")
            if not re.fullmatch(r"[A-Za-z0-9_-]{20,64}", tok): return await send(400, {"error": "bad token"})
            hosts, exact, deny = b.get("hosts"), b.get("hosts_exact"), b.get("deny")
            if deny is not None and not isinstance(deny, list): return await send(400, {"error": "deny must be a list"})
            if "https_only" in b and not isinstance(b["https_only"], bool):  # asked for and not understood: never a run with less than was asked
                return await send(400, {"error": "https_only must be true or false"})
            if any(x is not None and (not isinstance(x, list) or not x) for x in (hosts, exact)):  # a list was asked for: never fall back to "everything"
                return await send(400, {"error": "hosts and hosts_exact must be non-empty lists"})
            run = Run(tok, int(float(b.get("up_mb") or 50) * 1e6), int(float(b.get("down_mb") or 5000) * 1e6), int(b.get("ttl_s") or 2400), hosts, exact,
                      deny=deny or (), conns=b.get("conns") is True, https_only=b.get("https_only") is True)
            if (hosts is not None and not run.allow) or (exact is not None and not run.exact): return await send(400, {"error": "no valid host in the list"})
            if len(run.deny) != len(deny or ()):  # an entry that isn't a host, or more than the cap: never a run with less denied than was asked
                return await send(400, {"error": f"deny holds an entry that isn't a host name, or more than {DENY_MAX} entries"})
            RUNS[tok] = run
            log(ev="open", run=_tag(tok))   # the answer says what this run is held to, so a caller can refuse to go on with a proxy that didn't take the field
            return await send(200, {"ok": True, "exit": "separate" if UPSTREAM else "server", "https_only": run.https_only})
        m = re.fullmatch(r"/runs/([A-Za-z0-9_-]{20,64})", path)
        if m and method in ("GET", "DELETE"):
            r = RUNS.get(m[1]) if method == "GET" else RUNS.pop(m[1], None)
            if not r: return await send(404, {"error": "no such run"})
            if method == "DELETE": r.cut(); log(ev="close", run=_tag(m[1]), up=r.up, down=r.down, conns=r.conns)
            return await send(200, r.record())
        return await send(404, {"error": "not found"})
    except Exception as e:  # noqa: BLE001
        try: await send(400, {"error": str(e)[:200]})
        except Exception: pass


def health(host="127.0.0.1"):
    """`egress_proxy.py --health`, the container's health check: 0 only when the proxy listener (PORT) accepts a connection and the
    control port (CONTROL) answers GET /health with 200 and "ok": true. Both are checked because they are two listeners: a proxy
    that took only one of them up is not healthy. No secret is needed (/health answers before the secret check) and nothing is changed."""
    import socket, urllib.request
    try:
        socket.create_connection((host, PORT), timeout=3).close()
        with urllib.request.urlopen(f"http://{host}:{CONTROL}/health", timeout=3) as r:
            return 0 if r.status == 200 and json.load(r).get("ok") is True else 1
    except Exception as e:  # noqa: BLE001 - any failure is "not healthy"
        print(f"egress unhealthy: {e}", file=sys.stderr); return 1


async def main():
    if not SECRET: print("EGRESS_SECRET isn't set", file=sys.stderr); sys.exit(1)
    a = await asyncio.start_server(client, "0.0.0.0", PORT)
    b = await asyncio.start_server(control, "0.0.0.0", CONTROL)
    log(ev="start", port=PORT, control=CONTROL, exit="separate" if UPSTREAM else "server", ports=sorted(PORTS))
    async with a, b: await asyncio.gather(a.serve_forever(), b.serve_forever())


if __name__ == "__main__":
    if "--health" in sys.argv[1:]: sys.exit(health())
    asyncio.run(main())
