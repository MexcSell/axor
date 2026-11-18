"""Sandbox internet: egress_proxy.py (tokens, internal addresses, ports, byte caps, the per-run record), sandbox.py's pod for
a run with internet (label, proxy env, gVisor, secret-looking files held back, refusal while not ready) and what agents of
a team with internet are told (mining_work.sandbox_tool, mining_web.tools / sandbox_hint)."""
import asyncio, base64, json, socket, threading, time, unittest, urllib.request
from unittest import mock

from app import egress_proxy as ep, mining_web, mining_work, sandbox


class Public(unittest.TestCase):
    def test_inside_addresses_are_not_public(self):
        for a in ("10.43.0.1", "172.17.0.1", "192.168.1.1", "127.0.0.1", "169.254.169.254", "100.64.0.1", "0.0.0.0", "::1",
                  "fd00::1", "fe80::1", "::ffff:10.0.0.1", "224.0.0.1"):
            self.assertFalse(ep.public(a), a)
        for a in ("1.1.1.1", "140.82.112.3", "2606:4700::1111"):
            self.assertTrue(ep.public(a), a)

    def test_block_list(self):
        with mock.patch.object(ep, "BLOCK", [ep.ipaddress.ip_network("65.108.79.94/32")]):
            self.assertFalse(ep.public("65.108.79.94"))
            self.assertTrue(ep.public("65.108.79.95"))


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


class Proxy(unittest.TestCase):
    """The proxy in a thread, an origin server on localhost (allowed here by patching public())."""
    @classmethod
    def setUpClass(cls):
        cls.origin_port, cls.port, cls.ctl = free_port(), free_port(), free_port()
        cls.got = []

        async def origin(r, w):  # answers any request with 200 and how many body bytes it got
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

    def ctl_call(self, method, path, body=None, secret="s"):
        req = urllib.request.Request(f"http://127.0.0.1:{self.ctl}{path}", method=method, data=json.dumps(body).encode() if body else None,
                                     headers={"X-Egress-Secret": secret})
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

    def test_control_needs_the_secret(self):
        self.assertEqual(self.ctl_call("POST", "/runs", {"token": "t" * 24}, secret="wrong")[0], 403)
        self.assertEqual(self.ctl_call("GET", "/health")[0], 200)  # health is open: it says nothing secret

    def test_unknown_or_finished_run_gets_407(self):
        code, body = self.through("n" * 24, f"http://127.0.0.1:{self.origin_port}/")
        self.assertEqual(code, 407); self.assertIn("no internet", body)
        tok = "f" * 24
        self.ctl_call("POST", "/runs", {"token": tok}); self.ctl_call("DELETE", f"/runs/{tok}")
        self.assertEqual(self.through(tok, f"http://127.0.0.1:{self.origin_port}/")[0], 407)

    def test_request_is_forwarded_without_proxy_credentials_and_recorded(self):
        tok = "a" * 24
        self.assertEqual(self.ctl_call("POST", "/runs", {"token": tok})[0], 200)
        code, body = self.through(tok, f"http://127.0.0.1:{self.origin_port}/x?y=1")
        self.assertEqual((code, body), (200, "ok 0"))
        head = self.got[-1]
        self.assertTrue(head.startswith("GET /x?y=1 HTTP/1.1")); self.assertNotIn("Proxy-Authorization", head)
        _, rec = self.ctl_call("DELETE", f"/runs/{tok}")
        self.assertEqual(rec["hosts"]["127.0.0.1"]["conns"], 1); self.assertGreater(rec["down_bytes"], 0)

    def test_inside_address_and_port_are_refused_and_listed(self):
        tok = "b" * 24
        self.ctl_call("POST", "/runs", {"token": tok})
        with mock.patch.object(ep, "public", lambda a: False):
            code, body = self.through(tok, f"http://127.0.0.1:{self.origin_port}/")
        self.assertEqual(code, 403); self.assertIn("inside", body)
        self.assertEqual(self.through(tok, "http://127.0.0.1:25/")[0], 403)
        _, rec = self.ctl_call("DELETE", f"/runs/{tok}")
        self.assertEqual(len(rec["refused"]), 2); self.assertEqual(rec["hosts"], {})

    def test_upload_cap_cuts_the_run(self):
        tok = "c" * 24
        self.ctl_call("POST", "/runs", {"token": tok, "up_mb": 0.05})
        code, _ = self.through(tok, f"http://127.0.0.1:{self.origin_port}/up", data=b"x" * 200_000)
        self.assertNotEqual(code, 200)
        self.assertEqual(self.through(tok, f"http://127.0.0.1:{self.origin_port}/")[0], 407)  # the run is over
        _, rec = self.ctl_call("GET", f"/runs/{tok}")
        self.assertLessEqual(rec["up_bytes"], 50_000); self.assertIn("cap", rec["refused"][-1]["why"])

    def test_token_in_password_works_too(self):
        tok = "d" * 24
        self.ctl_call("POST", "/runs", {"token": tok})
        hdr = [("Proxy-Authorization", "Basic " + base64.b64encode(f"user:{tok}".encode()).decode())]
        self.assertEqual(ep.token_of(hdr), tok)


class Pod(unittest.TestCase):
    def setUp(self):
        self.s = sandbox.Sandbox(None, lambda: "")

    def test_without_internet_nothing_changes(self):
        p = self.s._pod("n", "true", [], 60, "tok", "x")
        self.assertNotIn("axor.dev/internet", p["metadata"]["labels"]); self.assertNotIn("runtimeClassName", p["spec"])
        self.assertFalse(any(e["name"].lower().endswith("_proxy") for e in p["spec"]["containers"][0]["env"]))

    def test_with_internet(self):
        p = self.s._pod("n", "true", ["postgres"], 60, "tok", "x", net_token="T" * 24)
        env = {e["name"]: e["value"] for e in p["spec"]["containers"][0]["env"]}
        self.assertEqual(p["metadata"]["labels"]["axor.dev/internet"], "on")
        self.assertEqual(p["spec"]["runtimeClassName"], "gvisor")
        self.assertEqual(env["HTTPS_PROXY"], f"http://{'T' * 24}:x@{sandbox.EGRESS_PROXY}"); self.assertEqual(env["https_proxy"], env["HTTPS_PROXY"])
        for host in ("127.0.0.1", "localhost", ".cluster.local"): self.assertIn(host, env["NO_PROXY"])  # model proxy and sidecars stay direct
        self.assertIn("web.axor.svc.cluster.local", env["SANDBOX_PROXY_URL"])

    def test_secret_paths(self):
        for p in (".env", "app/.env.local", "id_rsa", ".ssh/config", "keys/server.pem", "tls.key", "aws_credentials", "credentials.json",
                  "config/secrets.yaml", "secret", ".netrc", ".git-credentials", ".npmrc"):
            self.assertTrue(sandbox.SECRET_PATH.search(p), p)
        for p in ("agent.py", "secretary.py", "keyboard.py", "tasks/env/run.sh", "README.md", "data/web/x.json", "envs.py"):
            self.assertFalse(sandbox.SECRET_PATH.search(p), p)

    def test_internet_run_refused_while_not_ready(self):
        s = self.s
        s.ready = lambda: (True, "")
        s.egress.status = lambda fresh=False: {"ready": False, "why": "gVisor isn't installed on the server yet", "exit": "", "gvisor": False}
        with self.assertRaisesRegex(sandbox.SandboxError, "gVisor"): s.run({"a.py": ""}, "true", internet=True)

    def test_internet_run_holds_back_secrets_and_returns_the_record(self):
        s, made = self.s, {}
        s.ready = lambda: (True, "")
        s.egress.status = lambda fresh=False: {"ready": True, "why": "", "exit": "server", "gvisor": True}
        s.egress.open = lambda tok, ttl: made.setdefault("tok", tok)
        s.egress.close = lambda tok: {"hosts": {"pypi.org": {"conns": 1, "up": 10, "down": 99}}, "up_bytes": 10, "down_bytes": 99, "refused": [], "exit": "server"}

        class Kube:
            enabled = True
            def call(self, method, path, params=None, body=None, **k):
                if path.endswith("/configmaps"): made["cm"] = body
                else: made["pod"] = body
            def get(self, path): return {"status": {"phase": "Running", "containerStatuses": [{"name": "runner", "state": {"terminated": {"exitCode": 0}}}]}}
            def logs(self, *a, **k): return "@@AXOR-EXIT 0"
            def delete(self, *a, **k): pass
        s.kube = Kube()
        with mock.patch.object(sandbox.time, "sleep", lambda n: None):
            r = s.run({"agent.py": "print(1)", ".env": "KEY=1", "keys/a.pem": "x"}, "pip install x", internet=True)
        self.assertEqual(r["withheld"], [".env", "keys/a.pem"])
        sent = set(json.loads(made["cm"]["data"]["manifest.json"]).values())
        self.assertIn("agent.py", sent); self.assertFalse(sent & {".env", "keys/a.pem"})
        self.assertEqual(made["pod"]["metadata"]["labels"]["axor.dev/internet"], "on")
        self.assertEqual(r["net"]["hosts"]["pypi.org"]["down"], 99)
        self.assertEqual(mining_work.net_brief(r)["summary"], "1 host, 0.0 MB in, 0.0 MB out via this server's address")


class AgentText(unittest.TestCase):
    def test_tool_descriptions_follow_the_switch(self):
        self.assertIn("no internet", mining_work.sandbox_tool(False)["description"])
        on = mining_work.sandbox_tool(True)["description"]
        self.assertNotIn("no internet", on); self.assertIn("egress proxy", on)
        self.assertIn("has no internet", mining_web.tools(False)[0]["description"])
        self.assertNotIn("has no internet", mining_web.tools(True)[0]["description"])
        self.assertIs(mining_web.tools(False), mining_web.TOOLS)

    def test_hint_follows_the_switch(self):
        out = "Could not resolve host: github.com"
        self.assertIn("NO internet".lower(), mining_web.sandbox_hint(out).lower())
        self.assertIn("egress proxy", mining_web.sandbox_hint(out, True))
        self.assertIsNone(mining_web.sandbox_hint("all fine", True))


if __name__ == "__main__":
    unittest.main()
