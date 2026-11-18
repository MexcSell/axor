"""Live web retrieval's address guard (G5-2.2 Milestone 3, workstream 3): mining_web.fetch, which web_read, the live-data check
and the importers use, over techboard's guard and opener.

Every test runs with MINING_INTAKE_ALLOW_LOCAL off, so the guard and the redirect checks are the ones production runs (the
Milestone 2 fixtures had it on, which skips both). Nothing leaves the container: names resolve through a fake resolver, and a
connection to the one documentation-free public address used here (PUBLIC) is carried to a local test server by a fake
connect, so a request that reaches the local server proves which address the fetcher actually connected to."""
import datetime, http.server, ipaddress, os, socket, socketserver, ssl, tempfile, threading, time, unittest
from unittest import mock

from app import mining_sources, mining_web, techboard

PUBLIC = "93.184.215.14"     # a public address; connections to it are carried to the local server
STALL = "93.184.215.16"      # another public address, carried to a server that accepts and never answers
META = "169.254.169.254"     # the cloud metadata endpoint


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class Handler(http.server.BaseHTTPRequestHandler):
    hits = []

    def log_message(self, *a): pass

    def do_GET(self):
        Handler.hits.append((self.headers.get("Host"), self.path))
        p = self.path
        if p.startswith("/redir?to="):
            self.send_response(302); self.send_header("Location", p[len("/redir?to="):]); self.end_headers(); return
        if p.startswith("/hop/"):
            n = int(p.split("/")[2])
            self.send_response(302); self.send_header("Location", f"/hop/{n + 1}"); self.end_headers(); return
        if p.startswith("/status/"):
            code = int(p.split("/")[2]); self.send_response(code); self.send_header("Content-Type", "text/plain"); self.end_headers()
            self.wfile.write(b"status"); return
        if p == "/loop":
            self.send_response(302); self.send_header("Location", "/loop"); self.end_headers(); return
        if p == "/big":  # more than web_read keeps: read up to its cap, marked truncated, never all of it
            n = mining_web.PAGE_BYTES + 50_000
            self.send_response(200); self.send_header("Content-Type", "text/plain"); self.send_header("Content-Length", str(n)); self.end_headers()
            try:
                for _ in range(n // 65536 + 1): self.wfile.write(b"x" * 65536)
            except OSError: pass
            return
        if p == "/drip":  # a body that never stops: one byte every 0.3 s, so no single read ever times out
            self.send_response(200); self.send_header("Content-Type", "text/plain"); self.end_headers()
            try:
                for _ in range(200):
                    self.wfile.write(b"x"); self.wfile.flush(); time.sleep(.3)
            except OSError: pass
            return
        if p == "/slowhead":  # headers one line every 0.3 s
            try:
                self.wfile.write(b"HTTP/1.1 200 OK\r\n"); self.wfile.flush()
                for i in range(200):
                    self.wfile.write(f"X-Slow-{i}: y\r\n".encode()); self.wfile.flush(); time.sleep(.3)
            except OSError: pass
            return
        body = b"<html><body>internal secret page</body></html>"
        self.send_response(200); self.send_header("Content-Type", "text/html"); self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)


def _stall_server():
    """Accepts connections and never answers: a stalled TLS handshake, or a server that never sends a status line."""
    s = socket.socket(); s.bind(("127.0.0.1", 0)); s.listen(16)
    held = []
    def loop():
        while True:
            try: c, _ = s.accept(); held.append(c)
            except OSError: return
    threading.Thread(target=loop, daemon=True).start()
    return s


class Guard(unittest.TestCase):
    scheme = "http"

    @classmethod
    def setUpClass(cls):
        cls.srv = Server(("127.0.0.1", 0), Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.stall = _stall_server(); cls.stall_port = cls.stall.getsockname()[1]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close()

    def setUp(self):
        Handler.hits.clear()
        p = mock.patch.object(mining_sources, "ALLOW_LOCAL", False); p.start(); self.addCleanup(p.stop)
        p = mock.patch.object(techboard, "PORTS", {80, 443, self.port, self.stall_port}); p.start(); self.addCleanup(p.stop)  # the fixtures' ports
        self.names = {"stall.test": [STALL], "pub.test": [PUBLIC], "meta.test": [META], "metadata.google.internal": [META], "loop.test": ["127.0.0.1"],
                      "mixed.test": [PUBLIC, "10.0.0.5"], "v6meta.test": ["fd00:ec2::254"]}
        self.rebind = {}  # name → answers in turn: the first lookup and the next ones differ (DNS rebinding)
        self.connected, self.lookups = [], {}  # the addresses actually connected to; lookups per name
        real_gai, real_conn = socket.getaddrinfo, socket.create_connection
        def gai(host, port, family=0, type=0, proto=0, flags=0):
            h = host.decode() if isinstance(host, bytes) else host
            self.lookups[h] = self.lookups.get(h, 0) + 1
            if h == "slowdns.test": time.sleep(6); return real_gai("127.0.0.1", port, family, type, proto, flags)   # a resolver that hangs
            if h in self.rebind:
                seq = self.rebind[h]
                ip = seq.pop(0) if len(seq) > 1 else seq[0]
                ips = [ip]
            elif h in self.names: ips = self.names[h]
            else: return real_gai(host, port, family, type, proto, flags)   # IP literals and numeric forms parse locally
            out = []
            for ip in ips:
                fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
                out.append((fam, socket.SOCK_STREAM, 6, "", (ip, port or 80) if fam == socket.AF_INET else (ip, port or 80, 0, 0)))
            return out
        def conn(addr, timeout=None, source_address=None, **kw):
            host, port = addr[0], addr[1]
            ips = {i[4][0] for i in gai(host, port)} if not _ip(host) else {host}
            self.connected.append(sorted(ips))
            if PUBLIC in ips and len(ips) == 1: return real_conn(("127.0.0.1", self.port), timeout)   # PUBLIC is the test server
            if STALL in ips and len(ips) == 1: return real_conn(("127.0.0.1", self.stall_port), timeout)  # a server that accepts and says nothing
            if ips & {"127.0.0.1"}: return real_conn(("127.0.0.1", self.port), timeout)                # a loopback that got through
            raise OSError(101, "Network is unreachable (test: no egress)")
        for target, fn in ((socket, "getaddrinfo"), (socket, "create_connection")):
            p = mock.patch.object(target, fn, gai if fn == "getaddrinfo" else conn); p.start(); self.addCleanup(p.stop)

    def url(self, host, path="/ok"):
        return f"{self.scheme}://{host}:{self.port}{path}"

    def blocked(self, url, kinds=("address", "network", "http")):
        with self.assertRaises(mining_web.WebError) as e: mining_web.fetch(url, timeout=3)
        self.assertIn(e.exception.kind, kinds)
        self.assertEqual(Handler.hits, [], f"the fetcher reached the internal server for {url}")
        return e.exception

    # ---- the baseline: a public address is read
    def test_a_public_address_is_read(self):
        page = mining_web.fetch(self.url("pub.test"), timeout=3)
        self.assertIn("internal secret page", page["text"])          # here: the fixture behind PUBLIC

    # ---- private, loopback, link-local and metadata addresses
    def test_private_and_internal_addresses_are_refused(self):
        for host in ("127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.1.1", "100.64.0.1", "0.0.0.0", "localhost", "loop.test",
                     META, "meta.test", "metadata.google.internal", "100.100.100.200", "198.18.0.1", "224.0.0.1", "255.255.255.255"):
            with self.subTest(host=host): self.blocked(self.url(host))

    def test_a_name_with_one_private_answer_is_refused(self):
        self.blocked(self.url("mixed.test"))

    def test_numeric_forms_of_loopback_are_refused(self):
        for host in ("2130706433", "0x7f000001", "0177.0.0.1", "127.1", "0x7f.1"):
            with self.subTest(host=host): self.blocked(self.url(host))

    def test_userinfo_and_fragment_tricks_are_refused(self):
        for url in (f"http://pub.test@127.0.0.1:{self.port}/ok", f"http://127.0.0.1:{self.port}#@pub.test/ok",
                    f"http://127.0.0.1:{self.port}\\@pub.test/ok"):
            with self.subTest(url=url): self.blocked(url)

    # ---- IPv6
    def test_ipv6_internal_addresses_are_refused(self):
        for host in ("[::1]", "[::]", "[fe80::1]", "[fc00::1]", "[fd00:ec2::254]", "v6meta.test", "[ff02::1]"):
            with self.subTest(host=host): self.blocked(self.url(host))

    def test_ipv6_forms_that_embed_an_internal_ipv4_are_refused(self):
        # IPv4-mapped, the NAT64 well-known prefix, 6to4 and IPv4-compatible forms of loopback and of the metadata address
        for host in ("[::ffff:127.0.0.1]", "[::ffff:a9fe:a9fe]", "[64:ff9b::7f00:1]", "[64:ff9b::a9fe:a9fe]", "[2002:7f00:1::1]",
                     "[2002:a9fe:a9fe::1]", "[::127.0.0.1]"):
            with self.subTest(host=host): self.blocked(self.url(host))

    # ---- redirects
    def test_a_redirect_to_an_internal_address_is_refused(self):
        for to in (f"http://127.0.0.1:{self.port}/ok", f"http://{META}/latest/meta-data/", "http://metadata.google.internal/",
                   f"http://[::ffff:127.0.0.1]:{self.port}/ok", f"http://loop.test:{self.port}/ok"):
            with self.subTest(to=to):
                Handler.hits.clear()
                with self.assertRaises(mining_web.WebError): mining_web.fetch(self.url("pub.test", "/redir?to=" + to), timeout=3)
                self.assertEqual([h for h in Handler.hits if not h[1].startswith("/redir")], [])   # only the public hop was served

    def test_a_redirect_to_another_protocol_is_refused(self):
        for to in ("file:///etc/passwd", "ftp://pub.test/x", "gopher://pub.test/x", "data:text/html,hi", "javascript:alert(1)"):
            with self.subTest(to=to):
                Handler.hits.clear()
                with self.assertRaises(mining_web.WebError): mining_web.fetch(self.url("pub.test", "/redir?to=" + to), timeout=3)

    def test_redirect_chains_are_cut_short(self):
        with self.assertRaises(mining_web.WebError): mining_web.fetch(self.url("pub.test", "/hop/0"), timeout=5)
        self.assertLessEqual(len(Handler.hits), 6)                    # at most 5 redirects followed

    # ---- DNS rebinding: the name answers public to the check and loopback to the connection
    def test_dns_rebinding_cannot_reach_an_internal_address(self):
        self.rebind["rebind.test"] = [PUBLIC, "127.0.0.1"]
        with self.assertRaises(mining_web.WebError) as e: mining_web.fetch(self.url("rebind.test", "/rebound"), timeout=3)
        # the early check saw PUBLIC; the connection looked the name up for itself, got loopback, and refused it: the
        # connection only ever goes to addresses checked in the lookup it connects with
        self.assertNotIn(["127.0.0.1"], self.connected, f"connected to {self.connected} after checking {PUBLIC}")
        self.assertEqual(Handler.hits, [])
        self.assertEqual(e.exception.kind, "address")

    # ---- protocols
    def test_other_protocols_are_refused(self):
        for url in ("file:///etc/passwd", "ftp://pub.test/", "gopher://pub.test/", "data:text/plain,hi", "dict://pub.test:11211/",
                    "//pub.test/ok", "pub.test/ok"):
            with self.subTest(url=url):
                with self.assertRaises(mining_web.WebError) as e: mining_web.fetch(url, timeout=3)
                self.assertEqual(e.exception.kind, "address")

    # ---- time
    def test_a_body_that_drips_is_cut_at_the_total_timeout(self):
        t0 = time.time()
        with self.assertRaises(mining_web.WebError) as e: mining_web.fetch(self.url("pub.test", "/drip"), timeout=2)
        took = time.time() - t0
        self.assertEqual(e.exception.kind, "timeout")
        self.assertLess(took, 4, f"took {took:.1f} s for a 2 s timeout")

    def test_headers_that_drip_are_cut_at_the_total_timeout(self):
        t0 = time.time()
        with self.assertRaises(mining_web.WebError) as e: mining_web.fetch(self.url("pub.test", "/slowhead"), timeout=2)
        took = time.time() - t0
        self.assertEqual(e.exception.kind, "timeout")
        self.assertLess(took, 4, f"took {took:.1f} s for a 2 s timeout")

    def test_a_name_that_does_not_resolve_is_unknown_not_a_failure(self):
        # D-024: AXoR can't tell a wrong source from its own lookup failing: "network" (UNKNOWN), never "address" (FAIL)
        e = self.blocked(self.url("nowhere.invalid"))
        self.assertEqual(e.kind, "network")
        Handler.hits.clear()
        with self.assertRaises(mining_web.WebError) as r: mining_web.fetch(self.url("pub.test", f"/redir?to={self.scheme}://nowhere.invalid/x"), timeout=3)
        self.assertEqual(r.exception.kind, "network")

    # ---- Milestone 4
    def test_only_allowed_ports_are_read(self):
        with mock.patch.object(techboard, "PORTS", {443}):
            e = self.blocked(self.url("pub.test"))                      # the fixture's own port isn't 443
        self.assertEqual(e.kind, "address")
        Handler.hits.clear()
        with self.assertRaises(mining_web.WebError):                   # a redirect to another port is refused the same way
            with mock.patch.object(techboard, "PORTS", {self.port}): mining_web.fetch(self.url("pub.test", "/redir?to=http://pub.test:6379/"), timeout=3)

    def test_a_slow_resolver_is_cut_at_the_deadline(self):
        t0 = time.time()
        with self.assertRaises(mining_web.WebError) as e: mining_web.fetch(self.url("slowdns.test"), timeout=2)
        self.assertLess(time.time() - t0, 3.5)
        self.assertEqual(e.exception.kind, "timeout")

    def test_a_server_that_never_answers_is_cut_at_the_deadline(self):
        t0 = time.time()
        with self.assertRaises(mining_web.WebError) as e: mining_web.fetch(f"{self.scheme}://stall.test:{self.stall_port}/", timeout=2)
        self.assertLess(time.time() - t0, 3.5)                          # over https: a stalled TLS handshake
        self.assertEqual(e.exception.kind, "timeout")

    def test_429_and_5xx_are_http_answers(self):
        for code in (429, 500, 502, 503):
            with self.subTest(code=code):
                with self.assertRaises(mining_web.WebError) as e: mining_web.fetch(self.url("pub.test", f"/status/{code}"), timeout=3)
                self.assertEqual((e.exception.kind, e.exception.code), ("http", code))   # the live-data check: UNKNOWN

    def test_an_oversized_response_is_cut_at_the_cap(self):
        page = mining_web.fetch(self.url("pub.test", "/big"), timeout=10)
        self.assertTrue(page["truncated"])
        self.assertEqual(len(page["text"]), mining_web.PAGE_BYTES)

    def test_a_redirect_loop_is_cut(self):
        with self.assertRaises(mining_web.WebError): mining_web.fetch(self.url("pub.test", "/loop"), timeout=5)
        self.assertLessEqual(len([h for h in Handler.hits if h[1] == "/loop"]), 6)

    def test_the_importer_is_cut_at_its_deadline(self):
        t0 = time.time()
        with self.assertRaises(mining_sources.IntakeError): mining_sources.fetch(self.url("pub.test", "/drip"))
        self.assertLess(time.time() - t0, 18)                          # its 15 s, a dripping body included

    def test_an_unreachable_public_address_is_a_network_failure_not_a_pass(self):
        self.names["far.test"] = ["93.184.215.15"]
        e = self.blocked(self.url("far.test"))
        self.assertEqual(e.kind, "network")                           # the live-data check reads this as UNKNOWN


class GuardTLS(Guard):
    """Every check above again over https, as production reads (the pinned TLS connection, its handshake and the deadline's
    watchdog on the TLS socket). The fixture's certificate is made here for pub.test and trusted by a test opener only."""
    scheme = "https"

    @classmethod
    def setUpClass(cls):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
        cls.tmp = tempfile.TemporaryDirectory()
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "pub.test")])
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=2))
                .add_extension(x509.SubjectAlternativeName([x509.DNSName("pub.test"), x509.DNSName("rebind.test"), x509.DNSName("far.test")]), critical=False)
                .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True).sign(key, hashes.SHA256()))
        cls.cert, keyf = os.path.join(cls.tmp.name, "c.pem"), os.path.join(cls.tmp.name, "k.pem")
        open(cls.cert, "wb").write(cert.public_bytes(serialization.Encoding.PEM))
        open(keyf, "wb").write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        sctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); sctx.load_cert_chain(cls.cert, keyf)
        cls.srv = Server(("127.0.0.1", 0), Handler)
        cls.srv.socket = sctx.wrap_socket(cls.srv.socket, server_side=True)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass(); cls.tmp.cleanup()

    def setUp(self):
        super().setUp()
        ctx = ssl.create_default_context(cafile=self.cert)
        p = mock.patch.object(techboard, "_opener", techboard._build_opener(ctx)); p.start(); self.addCleanup(p.stop)

    def test_a_redirect_from_https_to_http_is_refused(self):
        with self.assertRaises(mining_web.WebError) as e: mining_web.fetch(self.url("pub.test", f"/redir?to=http://pub.test:{self.port}/ok"), timeout=3)
        self.assertEqual(e.exception.kind, "address")                  # refused before any plain-http connection

    def test_an_untrusted_certificate_is_refused(self):
        with mock.patch.object(techboard, "_opener", techboard._build_opener()):   # the system's trust store: the fixture's certificate isn't in it
            with self.assertRaises(mining_web.WebError) as e: mining_web.fetch(self.url("pub.test"), timeout=3)
        self.assertEqual(e.exception.kind, "network")                  # refused, never read: UNKNOWN (AXoR can't tell a broken site from interception)

    def test_the_certificate_is_checked_against_the_name(self):
        self.names["other.test"] = [PUBLIC]                           # the right server, the wrong name: refused by TLS
        with self.assertRaises(mining_web.WebError) as e: mining_web.fetch(self.url("other.test"), timeout=3)
        self.assertEqual(e.exception.kind, "network")


def _ip(s):
    try: ipaddress.ip_address(str(s).strip("[]").split("%")[0]); return True
    except ValueError: return False


if __name__ == "__main__":
    unittest.main()
