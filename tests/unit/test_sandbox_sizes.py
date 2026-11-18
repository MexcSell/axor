"""Sandbox run sizes, the fair slot queue, a run's egress policy and the image id in the result (AEF X2/X4, D-032 Proposed).
Pinned first: a run that names none of the new arguments gets the pod, the proxy registration and the result it got before."""
import json, threading, time, unittest
from unittest import mock

from app import sandbox

BEFORE_LIMITS = {"cpu": "2", "memory": "4Gi", "ephemeral-storage": "4Gi"}   # every run's limits before sizes existed
BEFORE_KEYS = {"status", "exit", "output", "error", "seconds", "pod", "cost", "calls", "services"}


class Kube:
    enabled = True
    def __init__(self, image_id=None): self.made, self.image_id = {}, image_id
    def call(self, method, path, params=None, body=None, **k): self.made["cm" if path.endswith("/configmaps") else "pod"] = body
    def get(self, path):
        cs = {"name": "runner", "state": {"terminated": {"exitCode": 0}}, **({"imageID": self.image_id} if self.image_id else {})}
        return {"status": {"phase": "Running", "containerStatuses": [cs]}}
    def logs(self, *a, **k): return "@@AXOR-EXIT 0"
    def delete(self, *a, **k): pass


def box(kube=None):
    s = sandbox.Sandbox(None, lambda: "")
    s.ready = lambda: (True, "")
    s.kube = kube or Kube()
    return s


class Unchanged(unittest.TestCase):
    def test_pod_without_a_size_is_the_pod_as_before(self):
        s = box()
        p = s._pod("n", "true", [], 60, "tok", "x")
        self.assertEqual(p["spec"]["containers"][0]["resources"]["limits"], BEFORE_LIMITS)
        self.assertEqual(p, s._pod("n", "true", [], 60, "tok", "x", size="M"))   # M is the old pod, exactly

    def test_result_keys_without_the_new_arguments(self):
        with mock.patch.object(sandbox.time, "sleep", lambda n: None):
            r = box().run({"a.py": ""}, "true")
        self.assertEqual(set(r), BEFORE_KEYS)

    def test_egress_registration_without_a_policy(self):
        e, sent = sandbox.Egress(None), []
        e._call = lambda method, path, body=None, timeout=10: sent.append(body)
        e.open("t" * 24, 100)
        self.assertEqual(sent, [{"token": "t" * 24, "up_mb": sandbox.NET_UP_MB, "down_mb": sandbox.NET_DOWN_MB, "ttl_s": 100}])

    def test_an_older_two_argument_egress_open_still_works(self):  # callers and test doubles that take (token, ttl) only
        s, got = box(), []
        s.egress.status = lambda fresh=False: {"ready": True, "why": "", "exit": "server", "gvisor": True}
        s.egress.open = lambda tok, ttl: got.append(ttl)
        s.egress.close = lambda tok: {"hosts": {}}
        with mock.patch.object(sandbox.time, "sleep", lambda n: None): s.run({"a.py": ""}, "true", internet=True, timeout=60)
        self.assertEqual(got, [960])


class ByAddress(unittest.TestCase):
    """SANDBOX_BY_ADDRESS: a pod is told where the run port and the egress proxy are by address, resolved in AXoR, so a run needs
    no DNS. Off by default: the pod is the pod as before."""
    NAMES = {"web.axor.svc.cluster.local": "10.43.7.7", "egress.axor-egress.svc.cluster.local": "10.43.9.9"}

    def setUp(self):
        sandbox._ADDR.clear(); self.asked = []
        def lookup(host):
            self.asked.append(host)
            if host not in self.NAMES: raise OSError("Name or service not known")
            return self.NAMES[host]
        self.dns = mock.patch.object(sandbox.socket, "gethostbyname", lookup); self.dns.start()
        self.cfg = mock.patch.multiple(sandbox, PROXY_URL="http://web.axor.svc.cluster.local:8091", EGRESS_PROXY="egress.axor-egress.svc.cluster.local:3128"); self.cfg.start()

    def tearDown(self): self.cfg.stop(); self.dns.stop(); sandbox._ADDR.clear()

    def env(self, **kw):
        p = box()._pod("n", "true", [], 60, "tok", "x", **kw)
        return {e["name"]: e["value"] for e in p["spec"]["containers"][0]["env"]}

    def test_off_by_default_the_pod_is_told_names_and_nothing_is_resolved(self):
        self.assertFalse(sandbox.BY_ADDRESS)
        e = self.env(net_token="T" * 24)
        self.assertEqual(e["SANDBOX_PROXY_URL"], "http://web.axor.svc.cluster.local:8091/t/tok")
        self.assertEqual(e["HTTPS_PROXY"], f"http://{'T' * 24}:x@egress.axor-egress.svc.cluster.local:3128"); self.assertEqual(e["NO_PROXY"], sandbox.NO_PROXY)
        self.assertEqual(self.asked, []); self.assertEqual(sandbox.endpoints()["by_address"], False)

    def test_on_the_pod_is_told_addresses_and_holds_no_service_name(self):
        with mock.patch.object(sandbox, "BY_ADDRESS", True):
            e = self.env(net_token="T" * 24)
            self.assertEqual(e["SANDBOX_PROXY_URL"], "http://10.43.7.7:8091/t/tok")
            for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"): self.assertEqual(e[k], f"http://{'T' * 24}:x@10.43.9.9:3128")
            for k in ("NO_PROXY", "no_proxy"): self.assertEqual(e[k], sandbox.NO_PROXY + ",10.43.7.7")   # the run port stays direct for a program that honours the proxy variables
            self.assertFalse([k for k, v in e.items() if "svc.cluster.local" in v and k not in ("NO_PROXY", "no_proxy")])
            plain = self.env()                                                                             # a run without internet: the run port by address, no proxy variables at all
            self.assertEqual(plain["SANDBOX_PROXY_URL"], "http://10.43.7.7:8091/t/tok"); self.assertNotIn("HTTPS_PROXY", plain)
            self.assertEqual(sorted(set(self.asked)), sorted(self.NAMES)); n = len(self.asked)
            self.env(net_token="T" * 24); self.assertEqual(len(self.asked), n)                            # kept a minute: not asked again for every pod
            self.assertEqual(sandbox.endpoints(), {"proxy_url": "http://10.43.7.7:8091", "egress_proxy": "10.43.9.9:3128", "no_proxy": sandbox.NO_PROXY + ",10.43.7.7", "by_address": True})

    def test_a_service_that_does_not_resolve_starts_no_pod(self):
        with mock.patch.object(sandbox, "BY_ADDRESS", True), mock.patch.object(sandbox, "PROXY_URL", "http://nowhere.axor.svc.cluster.local:8091"):
            with self.assertRaises(sandbox.SandboxError) as e: self.env()
            self.assertIn("nowhere.axor.svc.cluster.local", str(e.exception))

    def test_a_configured_address_is_used_as_it_is(self):
        with mock.patch.object(sandbox, "BY_ADDRESS", True), mock.patch.multiple(sandbox, PROXY_URL="http://10.1.2.3:8091", EGRESS_PROXY="10.1.2.4:3128"):
            self.assertEqual(sandbox.endpoints()["proxy_url"], "http://10.1.2.3:8091"); self.assertEqual(self.asked, [])


class Sizes(unittest.TestCase):
    def test_sizes_set_the_runner_limits(self):
        s = box()
        for size, (cpu, mem, _w) in sandbox.SIZES.items():
            lim = s._pod("n", "true", [], 60, "tok", "x", size=size)["spec"]["containers"][0]["resources"]["limits"]
            self.assertEqual((lim["cpu"], lim["memory"]), (cpu, mem))
        self.assertEqual(sandbox.SIZES["L"][:2], ("4", "8Gi"))   # the namespace's per-container ceiling (k8s/base/56-sandbox.yaml LimitRange max)

    def test_unknown_size_is_refused_before_anything_is_made(self):
        s = box()
        with self.assertRaisesRegex(sandbox.SandboxError, "size"): s.run({"a.py": ""}, "true", size="XL")
        self.assertEqual(s.kube.made, {})

    def test_result_names_the_size_and_the_image_id(self):
        s = box(Kube("docker.io/axor/sandbox@sha256:" + "a" * 64))
        with mock.patch.object(sandbox.time, "sleep", lambda n: None): r = s.run({"a.py": ""}, "true", size="L")
        self.assertEqual((r["size"], r["image_id"]), ("L", "docker.io/axor/sandbox@sha256:" + "a" * 64))
        self.assertEqual(s.kube.made["pod"]["spec"]["containers"][0]["resources"]["limits"]["memory"], "8Gi")
        self.assertEqual(s.slots.state()["used"], 0)   # both of an L run's slots came back


class StoppedBeforeItStarts(unittest.TestCase):
    def test_a_run_cancelled_while_it_waited_for_a_slot_makes_no_pod_and_gives_its_slot_back(self):
        s = box()
        with mock.patch.object(sandbox.time, "sleep", lambda n: None): r = s.run({"a.py": ""}, "true", cancelled=lambda: True, queue="mx:1", size="L")
        self.assertEqual((r["status"], r["pod"], r["error"]), ("cancelled", None, "Stopped before it started."))
        self.assertEqual(s.kube.made, {}); self.assertEqual(s.slots.state()["used"], 0); self.assertEqual(s.proxy.runs, {})
        with mock.patch.object(sandbox.time, "sleep", lambda n: None): ok = s.run({"a.py": ""}, "true")   # the control: not cancelled, it runs
        self.assertEqual(ok["status"], "done"); self.assertIn("pod", s.kube.made)

    def test_a_gate_refuses_every_caller_before_anything_is_made(self):
        s = box()
        self.assertIsNone(getattr(s, "gate", None))                 # none unless something sets one: every run as before
        s.gate = lambda: "Runs are stopped (every mission): test"
        with self.assertRaisesRegex(sandbox.SandboxError, "every mission"): s.run({"a.py": ""}, "true")
        self.assertEqual(s.kube.made, {})
        s.gate = lambda: None
        with mock.patch.object(sandbox.time, "sleep", lambda n: None): self.assertEqual(s.run({"a.py": ""}, "true")["status"], "done")


class Policy(unittest.TestCase):
    def test_policy_reaches_the_proxy_and_caps_only_go_down(self):
        e, sent = sandbox.Egress(None), []
        e._call = lambda method, path, body=None, timeout=10: sent.append(body)
        e.open("t" * 24, 100, {"hosts": ["github.com"], "deny": ["pypi.org"], "conns": True, "up_mb": 5, "down_mb": 10 ** 9, "hosts_exact": [], "https_only": True})
        b = sent[0]
        self.assertEqual((b["hosts"], b["deny"], b["conns"], b["https_only"]), (["github.com"], ["pypi.org"], True, True))
        self.assertNotIn("hosts_exact", b)                       # an empty list is never sent: the proxy reads a list as "only these"
        self.assertEqual((b["up_mb"], b["down_mb"]), (5.0, sandbox.NET_DOWN_MB))

    def test_run_passes_its_policy(self):
        s, got = box(), {}
        s.egress.status = lambda fresh=False: {"ready": True, "why": "", "exit": "server", "gvisor": True}
        s.egress.open = lambda tok, ttl, policy=None: got.update(policy=policy)
        s.egress.close = lambda tok: {"hosts": {}}
        with mock.patch.object(sandbox.time, "sleep", lambda n: None): s.run({"a.py": ""}, "true", internet=True, net={"hosts": ["github.com"]})
        self.assertEqual(got["policy"], {"hosts": ["github.com"]})


class Fair(unittest.TestCase):
    def order(self, total, asks, hold=0.05):
        """Starts one thread per (queue, weight) in order, each holding its slots for `hold` s; returns the order they got them."""
        sl, got, lock, ths = sandbox.Slots(total), [], threading.Lock(), []
        def one(i, q, w):
            self.assertTrue(sl.acquire(timeout=10, queue=q, weight=w))
            with lock: got.append(i)
            time.sleep(hold); sl.release(queue=q, weight=w)
        for i, (q, w) in enumerate(asks):
            t = threading.Thread(target=one, args=(i, q, w)); t.start(); ths.append(t); time.sleep(0.01)  # arrival order is the list's
        for t in ths: t.join()
        self.assertEqual(sl.state()["used"], 0); self.assertEqual(sl.state()["by_queue"], {})
        return got

    def test_no_queue_is_first_come_first_served(self):
        self.assertEqual(self.order(1, [(None, 1)] * 5), [0, 1, 2, 3, 4])

    def test_a_burst_from_one_mission_doesnt_shut_another_out(self):
        """Mission a holds both slots and has four more runs waiting when mission b's one run arrives last. The next slot that
        frees goes to b. No timing: each step waits for the queue to be in the state it describes."""
        def next_served(queues):
            sl, got, lock = sandbox.Slots(2), [], threading.Lock()
            self.assertTrue(sl.acquire(queue=queues[0])); self.assertTrue(sl.acquire(queue=queues[0]))     # both slots taken
            def one(i, q):
                sl.acquire(timeout=20, queue=q)
                with lock: got.append(i)
            ths = []
            for i, q in enumerate(queues[1:]):
                t = threading.Thread(target=one, args=(i, q)); t.start(); ths.append(t)
                for _ in range(2000):                                                                   # until it is in the queue, in arrival order
                    if len(sl.state()["waiting"]) == i + 1: break
                    time.sleep(0.001)
            sl.release(queue=queues[0])                                                                 # one slot frees
            for _ in range(2000):
                if got: break
                time.sleep(0.001)
            first = list(got)
            for _ in range(len(queues)): sl.release(queue=None)                                         # let everyone finish
            for t in ths: t.join(5)
            return first
        self.assertEqual(next_served(["a", "a", "a", "a", "a", "b"]), [4])       # b, the last to arrive, is served first: it holds no slot
        self.assertEqual(next_served([None] * 6), [0])                           # the control: one shared queue is first come, first served

    def test_never_more_than_total_at_once(self):
        sl, peak, now, lock = sandbox.Slots(3), [0], [0], threading.Lock()
        def one(q, w):
            sl.acquire(timeout=10, queue=q, weight=w)
            with lock: now[0] += w; peak[0] = max(peak[0], now[0])
            time.sleep(0.02)
            with lock: now[0] -= w
            sl.release(queue=q, weight=w)
        ths = [threading.Thread(target=one, args=(f"m{i % 4}", 1 + (i % 5 == 0))) for i in range(30)]
        for t in ths: t.start()
        for t in ths: t.join()
        self.assertLessEqual(peak[0], 3); self.assertEqual(sl.state()["used"], 0)

    def test_a_wait_that_runs_out_gives_up_and_leaves_no_trace(self):
        sl = sandbox.Slots(1)
        self.assertTrue(sl.acquire(timeout=1))
        self.assertFalse(sl.acquire(timeout=0.1, queue="b"))
        self.assertEqual(sl.state()["waiting"], [])
        sl.release()
        self.assertTrue(sl.acquire(timeout=1, queue="b"))

    def test_a_weight_over_the_total_is_cut_to_it(self):
        sl = sandbox.Slots(1)
        self.assertTrue(sl.acquire(timeout=1, weight=2)); sl.release(weight=2)
        self.assertEqual(sl.state()["used"], 0)

    def test_small_runs_cant_starve_a_large_one(self):
        sl = sandbox.Slots(2)
        with mock.patch.object(sandbox.Slots, "PATIENCE", 0.2):
            self.assertTrue(sl.acquire(queue="s", weight=1))             # one small run holds a slot
            got = []
            big = threading.Thread(target=lambda: got.append(("L", sl.acquire(timeout=10, queue="big", weight=2)))); big.start()
            time.sleep(0.3)                                              # the large run has now waited past its patience
            late = threading.Thread(target=lambda: got.append(("S", sl.acquire(timeout=10, queue="t", weight=1)))); late.start()
            time.sleep(0.2)
            self.assertEqual(got, [])                                    # the free slot is held for the large run, not given to the latecomer
            sl.release(queue="s", weight=1); big.join(5)
            self.assertEqual(got, [("L", True)])
            sl.release(queue="big", weight=2); late.join(5)
            self.assertEqual(got, [("L", True), ("S", True)])


if __name__ == "__main__":
    unittest.main()
