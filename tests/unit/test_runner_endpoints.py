"""The VM runner's pods take AXoR's run port and the egress proxy from the sandbox's one answer (sandbox.endpoints). With
SANDBOX_BY_ADDRESS=1 that answer is two addresses resolved in AXoR, so a job's pod needs no DNS; with the runner's policy without
its DNS rule (k8s/runner/58-runner-no-dns.candidate.yaml, a candidate for the Owner) DNS stops being a way out of a job's VM.

- Off (the default), or on a tree without sandbox.endpoints: the pod gets the configured names, exactly as before.
- On: the result URL, both proxy URLs and NO_PROXY carry addresses. The supervisor needs no change: it posts the result without
  a proxy, and hands the VM the proxy URL it was given.
- A service name that can't be resolved: the job isn't started and nothing is created for it.
"""
import os, sys, unittest

sys.path.insert(0, os.path.dirname(__file__))
import test_vm_runner as tv  # noqa: E402  (as a module, so its own tests don't run again here)
from app import runner as V, sandbox  # noqa: E402

ADDR = {"proxy_url": "http://10.43.7.21:8091", "egress_proxy": "10.43.9.4:3128", "no_proxy": sandbox.NO_PROXY + ",10.43.7.21", "by_address": True}


@tv.own_tests
class Endpoints(tv.Running):
    def setUp(self):
        super().setUp()
        self._had, self._fn = hasattr(sandbox, "endpoints"), getattr(sandbox, "endpoints", None)

    def tearDown(self):
        if self._had: sandbox.endpoints = self._fn
        elif hasattr(sandbox, "endpoints"): del sandbox.endpoints
        super().tearDown()

    def env(self): return {e["name"]: e["value"] for e in self.kube.pod()["spec"]["containers"][0]["env"]}
    def build_job(self):
        job, _ = V.validate(tv.spec(kind="build", network="build"), tv.FILES, ["pypi.org"])
        return job

    def test_by_name_as_before_when_the_switch_is_off_or_the_tree_has_no_such_function(self):
        for case in ("absent", "off"):
            if case == "absent" and hasattr(sandbox, "endpoints"): del sandbox.endpoints
            if case == "off": sandbox.endpoints = lambda: {"proxy_url": sandbox.PROXY_URL, "egress_proxy": sandbox.EGRESS_PROXY, "no_proxy": sandbox.NO_PROXY, "by_address": False}
            self.go()
            e = self.env()
            self.assertTrue(e["AXOR_RESULT_URL"].startswith(f"{sandbox.PROXY_URL}/t/"), (case, e["AXOR_RESULT_URL"])); self.assertTrue(e["AXOR_RESULT_URL"].endswith(V.RESULT_PATH))
            self.assertEqual((e["NO_PROXY"], e["no_proxy"]), (sandbox.NO_PROXY, sandbox.NO_PROXY))
            self.assertTrue(e["AXOR_PROXY"].endswith(f"@{sandbox.EGRESS_PROXY}"), e["AXOR_PROXY"])

    def test_by_address_the_pod_is_given_no_name_to_look_up(self):
        sandbox.endpoints = lambda: dict(ADDR)
        r = self.go(job=self.build_job(), report=lambda j: tv.vm_report(j))
        self.assertEqual(r["status"], "done")
        e = self.env()
        self.assertTrue(e["AXOR_RESULT_URL"].startswith("http://10.43.7.21:8091/t/")); self.assertTrue(e["AXOR_RESULT_URL"].endswith(V.RESULT_PATH))
        for k in ("AXOR_PROXY", "AXOR_BUILD_PROXY"): self.assertTrue(e[k].startswith("http://") and e[k].endswith(":x@10.43.9.4:3128"), e[k])
        self.assertEqual((e["NO_PROXY"], e["no_proxy"]), (ADDR["no_proxy"], ADDR["no_proxy"]))  # the run port's address is never sent through the proxy
        for k, v in e.items(): self.assertNotIn(".svc", v.replace(sandbox.NO_PROXY, ""), k)     # no service name left anywhere but the NO_PROXY list itself

    def test_a_name_that_cant_be_resolved_starts_nothing(self):
        def gone(): raise sandbox.SandboxError("AXoR couldn't find the address of web.axor.svc.cluster.local for the run (no such host).")
        sandbox.endpoints = gone
        r = self.go(job=self.build_job())
        self.assertEqual(r["status"], "error"); self.assertIn("wasn't started", r["error"]); self.assertIn("couldn't find the address", r["error"])
        self.assertEqual(([k for k, _ in self.kube.created], [c for c in self.egress.calls if c[0] == "POST"]), ([], []))  # no ConfigMap, no pod, no proxy run
        self.assertTrue(self.r.slots.acquire(blocking=False)); self.assertTrue(self.r.slots.acquire(blocking=False))        # both VM slots are free again
        self.r.slots.release(); self.r.slots.release()


if __name__ == "__main__":
    unittest.main()
