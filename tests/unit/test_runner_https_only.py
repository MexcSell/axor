"""Https-only on VM jobs (the package policy's rule, applied to the runner's own proxy runs).

Every run a job opens at the egress proxy is opened https-only: its pulls and its build's installs may speak https on port 443
and nothing else. There is no switch. The job's record says what was asked and whether the proxy confirmed it:
- a proxy whose answer says https_only: true        -> confirmed;
- a proxy whose answer doesn't say (an older one)   -> the job isn't started: nobody confirmed the rule;
- a proxy whose answer says anything else           -> the job isn't started: never a run with less than was asked.
The proxy's own enforcement (a plain http:// request refused) is the proxy's test; here it is checked that the proxy the tree
ships reads the runner's request as https-only."""
import os, sys, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
import test_egress_policy as tep  # noqa: E402  (the proxy in a thread with an origin on localhost; as modules, so their own tests don't run again here)
import test_vm_runner as tv  # noqa: E402
from app import egress_proxy, mining_work, runner as V  # noqa: E402

UNSET = object()


class Egress(tv.FakeEgress):
    """The proxy's control side, answering a run's opening with or without the https_only line."""
    def __init__(self, says=UNSET): super().__init__(); self.says = says
    def _call(self, method, path, body=None, timeout=10):
        self.calls.append((method, path, body))
        return {"ok": True} if self.says is UNSET else {"ok": True, "https_only": self.says}


@tv.own_tests
class HttpsOnly(tv.Running):
    def run_with(self, says=UNSET, job=None):
        job = job or self.job
        self.proxy, self.egress = tv.FakeProxy(), Egress(says)
        self.kube = tv.FakeKube(report=lambda pod: tv.vm_report(job), proxy=self.proxy)
        self.r = V.Runner(self.kube, self.proxy, self.egress)
        return self.r.run({**job, "id": 9}, tv.FILES)

    def opened(self): return [b for m, p, b in self.egress.calls if m == "POST"]
    def build_job(self): return V.validate(tv.spec(kind="bench", command="sh bench/run.sh", score_file="bench_out/live.json", network="build"), tv.FILES, ["pypi.org", "files.pythonhosted.org"])[0]

    def test_a_pulling_jobs_run_is_opened_https_only(self):
        r = self.run_with(True)
        (b,) = self.opened()
        self.assertIs(b["https_only"], True)
        self.assertEqual((b["hosts"], "hosts_exact" in b), (list(V.REGISTRY_HOSTS), False))        # and its hosts are as before
        self.assertEqual(r["status"], "done")

    def test_both_runs_of_a_building_job_are_opened_https_only(self):
        self.run_with(True, job=self.build_job())
        reg, build = self.opened()
        self.assertEqual((reg["https_only"], build["https_only"]), (True, True))
        self.assertEqual(build["hosts_exact"], ["files.pythonhosted.org", "pypi.org"])               # D1's exact hosts, unchanged

    def test_the_proxy_the_tree_ships_reads_the_request_as_https_only(self):
        """The same fields the proxy's control side reads (egress_proxy.control): a true boolean, which it never turns down."""
        b = V.proxy_run("t" * 24, 600, ["pypi.org"])
        self.assertIsInstance(b["https_only"], bool)
        run = egress_proxy.Run(b["token"], 1, 1, 60, b["hosts"], b["hosts_exact"], https_only=b.get("https_only") is True)
        self.assertTrue(run.https_only)
        self.assertFalse(egress_proxy.Run("t" * 24, 1, 1, 60, b["hosts"]).https_only)              # the control: a run opened without it isn't

    def test_a_proxy_that_does_not_say_means_the_job_is_not_started(self):
        """A proxy from before it could say, or something else answering in its place: nobody confirmed the rule, so no job."""
        r = self.run_with()
        self.assertEqual(r["status"], "error"); self.assertIn("didn't say it enforces https-only", r["error"]); self.assertIn("so the job isn't started", r["error"])
        self.assertEqual(self.kube.created, [])                                                     # no ConfigMap and no pod
        self.assertEqual(len([c for c in self.egress.calls if c[0] == "DELETE"]), 1)                 # the run it opened is closed
        self.assertEqual(r["net"]["https_only"], {"asked": True, "confirmed": False, "runs": {}}); self.assertIsNone(r.get("score"))

    def test_a_proxy_that_confirms_is_recorded_as_confirmed(self):
        r = self.run_with(True)
        self.assertEqual(r["net"]["https_only"], {"asked": True, "confirmed": True, "runs": {"registry": True}})
        r = self.run_with(True, job=self.build_job())
        self.assertEqual(r["net"]["https_only"], {"asked": True, "confirmed": True, "runs": {"registry": True, "build": True}})

    def test_a_building_job_needs_both_of_its_runs_confirmed(self):
        """A building job opens two runs. The first confirmed and the second not: the job isn't started, and both are closed."""
        job = self.build_job()
        self.proxy, self.egress = tv.FakeProxy(), Egress(True)
        real, n = self.egress._call, {"posts": 0}
        def second_does_not_say(method, path, body=None, timeout=10):
            out = real(method, path, body, timeout)
            if method == "POST": n["posts"] += 1
            return {"ok": True} if method == "POST" and n["posts"] == 2 else out
        self.egress._call = second_does_not_say
        self.kube = tv.FakeKube(report=lambda pod: tv.vm_report(job), proxy=self.proxy)
        r = V.Runner(self.kube, self.proxy, self.egress).run({**job, "id": 9}, tv.FILES)
        self.assertEqual(r["status"], "error"); self.assertIn("the job's build run", r["error"])
        self.assertEqual((self.kube.created, len([c for c in self.egress.calls if c[0] == "DELETE"])), ([], 2))
        self.assertEqual(r["net"]["https_only"], {"asked": True, "confirmed": False, "runs": {"registry": True}})

    def test_a_closing_record_that_says_otherwise_is_not_confirmed(self):
        """The proxy's record of a run says whether it was https-only. One that says it wasn't can't stand as confirmed."""
        job = self.job
        for rec, want in (({"https_only": True}, True), ({"https_only": False}, False), ({}, True)):   # a record without the line says nothing against it
            self.proxy, self.egress = tv.FakeProxy(), Egress(True)
            self.egress.close = lambda token, rec=rec: {"hosts": {}, "refused": [], **rec}
            self.kube = tv.FakeKube(report=lambda pod: tv.vm_report(job), proxy=self.proxy)
            r = V.Runner(self.kube, self.proxy, self.egress).run({**job, "id": 9}, tv.FILES)
            self.assertEqual((r["status"], r["net"]["https_only"]["confirmed"]), ("done", want), rec)

    def test_a_proxy_that_says_no_means_the_job_is_not_started(self):
        for says in (False, "yes", 1):
            r = self.run_with(says)
            self.assertEqual(r["status"], "error", says); self.assertIn("without https-only, so the job isn't started", r["error"])
            self.assertEqual([c for c in self.kube.created if c[0] == "pods"], [], says)             # no pod was made
            self.assertEqual(len([c for c in self.egress.calls if c[0] == "DELETE"]), 1, says)       # and the run it did open is closed
            self.assertEqual(r["net"]["https_only"]["confirmed"], False)
            self.assertIsNone(r.get("score"))

    def test_a_container_probe_that_did_not_reach_is_explained(self):
        """Seen in the real job: an alpine image's probe falls back to plain http, which an https-only run refuses."""
        job = self.job
        self.proxy, self.egress = tv.FakeProxy(), Egress()
        self.egress = Egress(True)
        for probe, noted in (({"image": "axor-job:9", "host": "registry-1.docker.io", "ok": False}, True), ({"image": "axor-job:9", "host": "registry-1.docker.io", "ok": True, "how": "https"}, False),
                             ({"ok": None, "error": "not measured"}, False)):
            self.kube = tv.FakeKube(report=lambda pod, probe=probe: tv.vm_report(job, net={"vm": {}, "container": probe}), proxy=self.proxy)
            c = V.Runner(self.kube, self.proxy, self.egress).run({**job, "id": 9}, tv.FILES)["net"]["container"]
            self.assertEqual("note" in c, noted, probe)
            self.assertEqual({k: v for k, v in c.items() if k != "note"}, probe)
        self.assertIn("This run is https-only", c["note"] if "note" in c else V.finish(job, {"result": {"status": "done", "exit": 0, "net": {"container": {"ok": False}}}}, "done", 0, "", "", "p",
                                                                                         V.inputs(job, tv.FILES), 1.0)["net"]["container"]["note"])

    def test_a_job_stopped_before_it_started_asked_the_proxy_for_nothing(self):
        self.proxy, self.egress = tv.FakeProxy(), Egress(True)
        self.kube = tv.FakeKube(report=lambda pod: tv.vm_report(self.job), proxy=self.proxy)
        r = V.Runner(self.kube, self.proxy, self.egress).run({**self.job, "id": 9}, tv.FILES, cancelled=lambda: True)
        self.assertEqual((r["status"], self.egress.calls), ("cancelled", []))
        self.assertNotIn("https_only", r["net"])                                                    # no run was opened, so nothing was asked
        self.assertIn("https_only", self.run_with(True)["net"])                                     # the control: a job that ran has the line

    def test_the_tool_tells_an_agent_where_a_jobs_files_come_from(self):
        """Not "the workspace": with the mission workspace on, that word names a place a VM job doesn't read."""
        d = mining_work.DOCKER_TOOL["description"]
        self.assertIn("Files come from the team's files", d); self.assertNotIn("come from the workspace", d)

    def test_a_job_without_a_network_opens_no_run_and_records_none(self):
        job, _ = V.validate(tv.spec(network="none"), {"Dockerfile": "FROM scratch\nCOPY app.py /\n", "app.py": ""})
        self.proxy, self.egress = tv.FakeProxy(), Egress(True)
        self.kube = tv.FakeKube(report=lambda pod: tv.vm_report(job, files={}, net=None), proxy=self.proxy)
        r = V.Runner(self.kube, self.proxy, self.egress).run({**job, "id": 9}, {"Dockerfile": "FROM scratch\nCOPY app.py /\n", "app.py": ""})
        self.assertEqual((self.egress.calls, r["net"], r["status"]), ([], None, "done"))


@tv.own_tests
class Redirects(tep.Policy):
    """The directive's "redirects" and "mirrors", at the proxy, for a run opened with the runner's own request. The proxy never
    sees a redirect: it happens inside https. A client that follows one makes a NEW request through the proxy, and that request
    is judged like any other. So a redirect from an approved https host to plain http is refused (https-only), and one to
    another host (a mirror) is refused unless that host is on the run's list. Https-only alone says nothing about which https
    host answers: that is the list's job."""
    @staticmethod
    async def to_origin(host, port, addrs):   # the far side on 443, as the base class has it, but this class's own origin (the base names its own port)
        import asyncio
        return await asyncio.open_connection("127.0.0.1", Redirects.origin_port)

    def test_where_a_redirect_leads_is_judged_like_any_other_request(self):
        tok, ep = "R" * 24, egress_proxy
        self.assertEqual(self.ctl_call("POST", "/runs", {**V.proxy_run(tok, 600), "hosts": ["127.0.0.1"]})[0], 200)  # the approved host stands in for a registry
        with mock.patch.object(ep, "PORTS", {self.origin_port, 443}), mock.patch.object(ep, "open_to", self.to_origin):
            self.assertEqual(self.connect(tok, "127.0.0.1", 443), 200)                              # the approved host over https: through
            reached = len(self.got)
            code, text = self.through(tok, self.url())                                              # led to plain http on the SAME approved host
            self.assertEqual(code, 403); self.assertIn("Only https on port 443", text)
            self.assertEqual(self.connect(tok, "mirror.example", 443), 403)                         # led to https on a host that isn't on the list
            self.assertEqual(self.through(tok, self.url("mirror.example"))[0], 403)                 # led to plain http on such a host
        self.assertEqual(len(self.got), reached)                                                    # none of the three reached any far side
        _, rec = self.ctl_call("DELETE", f"/runs/{tok}")
        self.assertEqual([(r["host"], r["why"]) for r in rec["refused"]],
                         [(f"127.0.0.1:{self.origin_port}", ep.HTTPS_WHY), ("mirror.example", "host not on this run's list"), (f"mirror.example:{self.origin_port}", ep.HTTPS_WHY)])

    def test_the_control_without_https_only_plain_http_to_the_approved_host_goes_through(self):
        tok = "S" * 24
        body = {k: v for k, v in V.proxy_run(tok, 600).items() if k != "https_only"} | {"hosts": ["127.0.0.1"]}
        self.assertEqual(self.ctl_call("POST", "/runs", body)[0], 200)
        self.assertEqual(self.through(tok, self.url())[0], 200)                                     # so the refusal above is https-only's doing
        self.assertEqual(self.through(tok, self.url("mirror.example"))[0], 403)                     # and the list still holds without it
        self.ctl_call("DELETE", f"/runs/{tok}")


if __name__ == "__main__":
    unittest.main()
