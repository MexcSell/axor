"""The egress proxy's two optional per-run fields (AEF, D-032 X4, Proposed): `deny` (hosts refused even when the run's lists
would allow them: a mission's unapproved package indexes) and `conns` (each connection of the run kept in its record).
Pinned here: a run that passes neither is exactly as before (the record's keys, Run()'s positional arguments); deny wins over
`hosts` and `hosts_exact`; a denied connection is in the existing refusals list; a kept connection holds when, host, port, bytes
and time, and nothing else."""
import asyncio, json, socket, threading, unittest, urllib.error, urllib.request
from unittest import mock

from app import egress_proxy as ep

RECORD_KEYS = {"up_bytes", "down_bytes", "up_cap", "down_cap", "connections", "hosts", "refused", "exit", "https_only"}  # every run's record; https_only says what the run was held to


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


class Denied(unittest.TestCase):
    def test_host_and_everything_under_it(self):
        self.assertTrue(ep.denied("pypi.org", ("pypi.org",)))
        self.assertTrue(ep.denied("Files.PyPI.org.", ("pypi.org",)))
        self.assertFalse(ep.denied("notpypi.org", ("pypi.org",)))       # a suffix alone isn't a subdomain
        self.assertFalse(ep.denied("pypi.org.example.com", ("pypi.org",)))
        self.assertFalse(ep.denied("github.com", ()))
        self.assertFalse(ep.denied("github.com", None))

    def test_run_keeps_its_positional_arguments(self):
        r = ep.Run("t" * 24, 1, 2, 10, ("a.example",), ("b.example",))     # as runner.py's callers and the control API build it
        self.assertEqual((r.allow, r.exact, r.deny, r.kept), (("a.example",), ("b.example",), (), None))
        self.assertEqual(set(r.record()), RECORD_KEYS)


class Policy(unittest.TestCase):
    """The proxy in a thread and an origin on localhost (allowed here by patching public()), as tests/unit/test_sandbox_internet.py."""
    @classmethod
    def setUpClass(cls):
        cls.origin_port, cls.port, cls.ctl = free_port(), free_port(), free_port()
        cls.got = []

        async def origin(r, w):
            data = await r.read(65536)
            while b"\r\n\r\n" not in data: data += await r.read(65536)
            head, body = data.split(b"\r\n\r\n", 1)
            n = int(next((ln.split(b":")[1] for ln in head.split(b"\r\n") if ln.lower().startswith(b"content-length")), b"0"))
            while len(body) < n:
                chunk = await r.read(65536)
                if not chunk: break
                body += chunk
            cls.got.append(head.decode())
            out = b"ok %d" % len(body)
            w.write(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\nConnection: close\r\n\r\n%s" % (len(out), out)); await w.drain(); w.close()

        cls.loop = asyncio.new_event_loop()
        cls.patches = [mock.patch.object(ep, "public", lambda a: a.startswith("127.")), mock.patch.object(ep, "SECRET", "s"),
                       mock.patch.object(ep, "PORTS", {cls.origin_port}), mock.patch.object(ep, "log", lambda **k: None)]
        for p in cls.patches: p.start()

        async def boot():
            await asyncio.start_server(origin, "127.0.0.1", cls.origin_port)
            await asyncio.start_server(ep.client, "127.0.0.1", cls.port)
            await asyncio.start_server(ep.control, "127.0.0.1", cls.ctl)
        cls.loop.run_until_complete(boot())
        threading.Thread(target=cls.loop.run_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.loop.call_soon_threadsafe(cls.loop.stop)
        for p in cls.patches: p.stop()

    def ctl_call(self, method, path, body=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.ctl}{path}", method=method, data=json.dumps(body).encode() if body else None,
                                     headers={"X-Egress-Secret": "s"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r: return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e: return e.code, json.loads(e.read())

    def through(self, token, url, data=None):
        h = urllib.request.ProxyHandler({"http": f"http://{token}:x@127.0.0.1:{self.port}"})
        req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
        try:
            with urllib.request.build_opener(h).open(req, timeout=10) as r: return r.status, r.read().decode()
        except urllib.error.HTTPError as e: return e.code, e.read().decode()
        except (urllib.error.URLError, ConnectionError, OSError) as e: return 0, str(e)

    def url(self, host="127.0.0.1", path="/"): return f"http://{host}:{self.origin_port}{path}"

    def test_without_the_fields_the_record_is_as_before(self):
        tok = "a" * 24
        self.assertEqual(self.ctl_call("POST", "/runs", {"token": tok})[0], 200)
        self.assertEqual(self.through(tok, self.url())[0], 200)
        _, rec = self.ctl_call("DELETE", f"/runs/{tok}")
        self.assertEqual(set(rec), RECORD_KEYS)

    def test_deny_wins_over_both_lists_and_is_listed_as_a_refusal(self):
        for i, lists in enumerate(({}, {"hosts": ["127.0.0.1"]}, {"hosts_exact": ["127.0.0.1"]}, {"hosts": ["127.0.0.1"], "hosts_exact": ["127.0.0.1"]})):
            tok, before = chr(ord("b") + i) * 24, len(self.got)
            self.assertEqual(self.ctl_call("POST", "/runs", {"token": tok, **lists, "deny": ["127.0.0.1"]})[0], 200)
            code, body = self.through(tok, self.url())
            self.assertEqual(code, 403, lists); self.assertIn("isn't approved", body)
            self.assertEqual(len(self.got), before, "the origin was reached")
            _, rec = self.ctl_call("DELETE", f"/runs/{tok}")
            self.assertEqual([(r["host"], r["why"]) for r in rec["refused"]], [("127.0.0.1", ep.DENY_WHY)])
            self.assertEqual(rec["hosts"], {}); self.assertEqual(set(rec), RECORD_KEYS)  # no second list

    def test_removing_deny_lets_the_same_request_through(self):  # the control for the test above: the refusal is the deny list's doing
        tok = "g" * 24
        self.ctl_call("POST", "/runs", {"token": tok, "hosts": ["127.0.0.1"]})
        self.assertEqual(self.through(tok, self.url())[0], 200)
        self.ctl_call("DELETE", f"/runs/{tok}")

    def test_deny_leaves_other_hosts_alone(self):
        tok = "h" * 24
        self.ctl_call("POST", "/runs", {"token": tok, "deny": ["localhost", "pypi.org"]})
        self.assertEqual(self.through(tok, self.url("127.0.0.1"))[0], 200)
        self.assertEqual(self.through(tok, self.url("localhost"))[0], 403)
        _, rec = self.ctl_call("DELETE", f"/runs/{tok}")
        self.assertEqual([(r["host"], r["why"]) for r in rec["refused"]], [("localhost", ep.DENY_WHY)])  # the deny list's refusal, not the address check's

    def test_deny_must_be_a_list(self):
        self.assertEqual(self.ctl_call("POST", "/runs", {"token": "i" * 24, "deny": "pypi.org"})[0], 400)

    def test_a_deny_list_that_cant_be_honoured_whole_registers_nothing(self):
        """Fails closed, as the host lists do: a run never gets less denied than its caller asked for."""
        for n, bad in enumerate((["pypi.org", "https://files.pythonhosted.org/simple"], ["pypi.org", "bad host"], ["pypi.org", 7], ["ok.example", "x"],
                                 [f"h{i}.example" for i in range(ep.DENY_MAX + 1)])):
            tok = chr(ord("m") + n) * 24
            code, body = self.ctl_call("POST", "/runs", {"token": tok, "deny": bad})
            self.assertEqual(code, 400, bad[:2]); self.assertIn("deny", body["error"])
            self.assertEqual(self.ctl_call("GET", f"/runs/{tok}")[0], 404)                       # nothing was registered
            self.assertEqual(self.through(tok, self.url())[0], 407)                              # and the token opens nothing
        tok = "r" * 24                                                                           # the cap itself is fine
        self.assertEqual(self.ctl_call("POST", "/runs", {"token": tok, "deny": [f"h{i}.example" for i in range(ep.DENY_MAX)]})[0], 200)
        self.ctl_call("DELETE", f"/runs/{tok}")

    def test_an_empty_deny_list_is_no_deny(self):
        tok = "s" * 24
        self.assertEqual(self.ctl_call("POST", "/runs", {"token": tok, "deny": []})[0], 200)
        self.assertEqual(self.through(tok, self.url())[0], 200)
        _, rec = self.ctl_call("DELETE", f"/runs/{tok}")
        self.assertEqual(set(rec), RECORD_KEYS)

    def test_a_connection_that_breaks_while_it_runs_is_still_listed(self):
        tok = "u" * 24
        self.ctl_call("POST", "/runs", {"token": tok, "conns": True})
        async def boom(run, way, *a):                       # the download side fails after the connection was counted
            if way == "down": raise RuntimeError("the far side vanished")
        with mock.patch.object(ep, "pump", boom):
            self.through(tok, self.url())
        _, rec = self.ctl_call("DELETE", f"/runs/{tok}")
        self.assertEqual(rec["connections"], 1)
        self.assertEqual([(c["host"], c["port"]) for c in rec["conns"]], [("127.0.0.1", self.origin_port)])   # counted, so listed

    def test_conns_keeps_each_connection_and_nothing_private(self):
        tok = "j" * 24
        self.ctl_call("POST", "/runs", {"token": tok, "conns": True})
        self.through(tok, self.url(path="/secret-path?key=abc")); self.through(tok, self.url(path="/two"), data=b"x" * 3000)
        _, rec = self.ctl_call("DELETE", f"/runs/{tok}")
        self.assertEqual(len(rec["conns"]), 2); self.assertEqual(rec["conns_dropped"], 0)
        for c in rec["conns"]:
            self.assertEqual(set(c), {"at", "host", "port", "up", "down", "ms"})
            self.assertEqual((c["host"], c["port"]), ("127.0.0.1", self.origin_port)); self.assertGreater(c["down"], 0)
        self.assertGreater(rec["conns"][1]["up"], 3000)          # the second connection carried the body: its own bytes, not the host's total
        self.assertLess(rec["conns"][0]["up"], 1000)
        self.assertEqual(sum(c["up"] for c in rec["conns"]), rec["up_bytes"])
        dumped = json.dumps(rec)
        for private in ("secret-path", "key=abc", tok, "Proxy-Authorization"): self.assertNotIn(private, dumped)

    def test_conns_is_capped_and_counts_what_it_dropped(self):
        tok = "k" * 24
        with mock.patch.object(ep, "CONNS_KEPT", 2):
            self.ctl_call("POST", "/runs", {"token": tok, "conns": True})
            for _ in range(3): self.assertEqual(self.through(tok, self.url())[0], 200)
            _, rec = self.ctl_call("DELETE", f"/runs/{tok}")
        self.assertEqual((len(rec["conns"]), rec["conns_dropped"], rec["connections"]), (2, 1, 3))

    def test_https_only_refuses_plain_http_and_other_ports_for_that_run_alone(self):
        tok, other = "v" * 24, "w" * 24
        code, said = self.ctl_call("POST", "/runs", {"token": tok, "https_only": True})
        self.assertEqual((code, said["https_only"]), (200, True))                    # the answer confirms it: a caller can refuse a proxy that says nothing
        self.assertIs(self.ctl_call("POST", "/runs", {"token": other})[1]["https_only"], False)
        self.assertIs(self.ctl_call("GET", f"/runs/{tok}")[1]["https_only"], True)
        before = len(self.got)
        code, body = self.through(tok, self.url())                                   # a plain http request
        self.assertEqual(code, 403); self.assertIn("Only https on port 443", body); self.assertEqual(len(self.got), before)
        self.assertEqual(self.connect(tok, "127.0.0.1", self.origin_port), 403)        # a tunnel to another port
        with mock.patch.object(ep, "PORTS", {self.origin_port, 443}), mock.patch.object(ep, "open_to", self.to_origin):
            self.assertEqual(self.connect(tok, "127.0.0.1", 443), 200)                 # https on 443 goes through
        self.assertEqual(self.through(other, self.url())[0], 200)                      # another run is as before: the rule is per run
        _, rec = self.ctl_call("DELETE", f"/runs/{tok}")
        self.assertEqual([(r["host"], r["why"]) for r in rec["refused"]], [(f"127.0.0.1:{self.origin_port}", ep.HTTPS_WHY)] * 2)
        self.assertEqual(set(rec), RECORD_KEYS); self.assertIs(rec["https_only"], True)
        _, rec2 = self.ctl_call("DELETE", f"/runs/{other}")
        self.assertEqual(rec2["refused"], []); self.assertIs(rec2["https_only"], False)

    def test_https_only_must_be_a_boolean_or_nothing_is_registered(self):
        for n, bad in enumerate(("yes", 1, "true", None, [True])):
            tok = chr(ord("A") + n) * 24
            self.assertEqual(self.ctl_call("POST", "/runs", {"token": tok, "https_only": bad})[0], 400, bad)
            self.assertEqual(self.ctl_call("GET", f"/runs/{tok}")[0], 404)
        tok = "x" * 24                                                                 # false is a value too: the run is as before
        self.assertEqual(self.ctl_call("POST", "/runs", {"token": tok, "https_only": False})[0], 200)
        self.assertEqual(self.through(tok, self.url())[0], 200)
        self.ctl_call("DELETE", f"/runs/{tok}")

    def connect(self, token, host, port):
        """A CONNECT through the proxy as a client's https would make it; returns the proxy's status code. When the tunnel opens, one
        whole request goes through it and its answer is read, so the far side is left with nothing half-open."""
        import base64
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as s:
            auth = base64.b64encode(f"{token}:x".encode()).decode()
            s.sendall(f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\nProxy-Authorization: Basic {auth}\r\n\r\n".encode())
            head = s.recv(4096).decode("latin-1")
            code = int(head.split()[1]) if head else 0
            if code == 200:
                s.sendall(b"GET /through-the-tunnel HTTP/1.1\r\nHost: x\r\n\r\n")
                self.assertIn(b"200 OK", s.recv(4096))
            return code

    @staticmethod
    async def to_origin(host, port, addrs):   # stands in for the far side on 443: the test can't listen there
        return await asyncio.open_connection("127.0.0.1", Policy.origin_port)

    def test_conns_only_when_true(self):
        tok = "l" * 24
        self.ctl_call("POST", "/runs", {"token": tok, "conns": "yes"})
        _, rec = self.ctl_call("DELETE", f"/runs/{tok}")
        self.assertNotIn("conns", rec)


class Health(unittest.TestCase):
    """`egress_proxy.py --health` (the container's health check): healthy only when the proxy port AND the control port answer."""
    def serve(self, proxy=True, control=True):
        loop, ports = asyncio.new_event_loop(), (free_port(), free_port())
        servers = []

        async def boot():
            if proxy: servers.append(await asyncio.start_server(ep.client, "127.0.0.1", ports[0]))
            if control: servers.append(await asyncio.start_server(ep.control, "127.0.0.1", ports[1]))
        loop.run_until_complete(boot())
        threading.Thread(target=loop.run_forever, daemon=True).start()
        self.addCleanup(loop.call_soon_threadsafe, loop.stop)
        return ports

    def check(self, **kw):
        ports = self.serve(**kw)
        with mock.patch.object(ep, "PORT", ports[0]), mock.patch.object(ep, "CONTROL", ports[1]), mock.patch.object(ep, "log", lambda **k: None):
            return ep.health()

    def test_healthy_when_both_listeners_answer(self): self.assertEqual(self.check(), 0)
    def test_unhealthy_without_the_proxy_listener(self): self.assertEqual(self.check(proxy=False), 1)
    def test_unhealthy_without_the_control_listener(self): self.assertEqual(self.check(control=False), 1)
    def test_unhealthy_when_nothing_listens(self): self.assertEqual(self.check(proxy=False, control=False), 1)


if __name__ == "__main__":
    unittest.main()
