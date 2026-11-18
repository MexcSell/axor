"""G5-4 V4.2 (D-013, D013_VM_RUNNER_DESIGN.md; Owner decision D-8, Q-4, Q-5): the VM Docker runner, as far as it can be tested
without a cluster or a VM. A real job in a VM is not tested here.

- A job is refused before any VM exists unless every image it pulls is pinned by digest (images, FROM, COPY --from, the syntax
  directive, Compose); Compose services can't reach past their container; secrets and pushes are held, never started.
- The pod has /dev/kvm and nothing else: not privileged, no capabilities, no API token; only a pulling job gets the label
  that opens the egress proxy, and the proxy is opened for registry hosts only.
- A result counts only when the VM reported it: no report is an error or a timeout, never done. A job that ran another job
  than the one validated, or on another base disk than this server expects, is an error.
- A benchmark's score is the one in the job's own output file (job:<id>), never the one an agent files; the file's score and
  the exit code are separate; an edited result file is no longer evidence. D-004's internal measure reads all of that.
- The docker probe passes only after a real clean job on the current base disk.
"""
import hashlib, json, os, sys, tempfile, threading, time, types, unittest

sys.path.insert(0, os.path.dirname(__file__))
from app import egress_proxy, mining_release as R, mining_work, mission_ops as mo, runner as V  # noqa: E402
from app.auth import AuthDB  # noqa: E402
from app.kube import KubeError  # noqa: E402
import test_mission_persistent_evidence as tp  # noqa: E402
from test_g54_release_evidence import own_tests, sbx_table  # noqa: E402

D1, D2 = "sha256:" + "a1" * 32, "sha256:" + "b2" * 32
PY, NGINX = f"python@{D1}", f"ghcr.io/acme/nginx@{D2}"
WID, RUN, CAND = 7, 41, "abc1234def5678"
BASE = "c3" * 32
FILES = {"Dockerfile": f"FROM {PY}\nCOPY app.py /app.py\nCMD [\"python\", \"/app.py\"]\n", "app.py": "print('hi')\n",
         "bench/run.sh": "#!/bin/sh\necho '{\"score\": 0.5}' > bench_out/live.json\n"}


def spec(**kw): return {"kind": "build", "dockerfile": "Dockerfile", "network": "registry", **kw}


def close_db(db):
    """On Postgres every AuthDB holds a connection for as long as it lives, and a finished test's objects live until the garbage
    collector gets to them: closed here, so a full run stays under the test server's connection limit (PX-R13)."""
    try: db.db.close()
    except Exception: pass  # noqa: BLE001 - already closed, or never opened


class Validation(unittest.TestCase):
    def bad(self, text, **kw):
        files = kw.pop("files", FILES)
        with self.assertRaises(V.RunnerError) as e: V.validate(spec(**kw), files)
        self.assertIn(text, str(e.exception))

    def test_a_pinned_build_is_taken_and_capped(self):
        job, held = V.validate(spec(timeout_s=99999, memory_mb=99999, cpus=64, artifacts=["out/log.txt", "./out/log.txt"]), FILES)
        self.assertEqual(held, [])
        self.assertEqual((job["kind"], job["dockerfile"], job["context"], job["network"]), ("build", "Dockerfile", ".", "registry"))
        self.assertEqual((job["timeout_s"], job["memory_mb"], job["cpus"], job["artifacts"]), (V.MAX_TIMEOUT, V.MAX_MEM, V.MAX_CPUS, ["out/log.txt"]))
        self.assertEqual(job["check_hosts"], ["registry-1.docker.io"])
        for ref, host in ((f"python:3.12-slim@{D1}", "registry-1.docker.io"), (f"library/python@{D1}", "registry-1.docker.io"), (f"ghcr.io/acme/x:1@{D1}", "ghcr.io"),
                          (f"registry.example.org:5000/a/b@{D1}", "registry.example.org"), (f"docker.io/library/python@{D1}", "registry-1.docker.io")):
            self.assertEqual(V._registry_host(ref), host, ref)                  # a tag's colon isn't a port: found by the first real SN61 job

    def test_every_image_must_be_pinned_by_digest(self):
        self.bad("isn't pinned", images=["python:3.12-slim"])
        self.bad("isn't pinned", images=[f"python@sha256:{'a' * 63}"])
        for df in ("FROM python:3.12-slim\n", "FROM python\n", f"FROM {PY}\nCOPY --from=nginx:latest /a /a\n", f"# syntax=docker/dockerfile:1\nFROM {PY}\n",
                   f"FROM {PY} AS base\nFROM alpine\n", f"FROM {PY}\nRUN --mount=type=bind,from=golang:1.22,target=/x true\n"):
            self.bad("isn't pinned", files={**FILES, "Dockerfile": df})
        self.bad("build argument", files={**FILES, "Dockerfile": "ARG BASE=python\nFROM ${BASE}\n"})
        self.bad("no FROM", files={**FILES, "Dockerfile": "RUN true\n"})

    def test_stages_scratch_and_continuations_are_understood(self):
        df = f"FROM --platform=linux/amd64 {PY} AS build\nRUN pip install \\\n  flask\nFROM scratch AS empty\nFROM build\nCOPY --from=build /a /a\nCOPY --from=0 /b /b\n"
        self.assertEqual(V.dockerfile_images(df), [PY])
        job, _ = V.validate(spec(network="none"), {"Dockerfile": "FROM scratch\nCOPY app.py /\n", "app.py": ""})
        self.assertEqual(job["network"], "none")

    def test_pulls_need_the_registry_network(self):
        self.bad("needs network: registry", network="none")
        self.bad("needs network: registry", network="none", kind="run", dockerfile="", images=[PY], command="true")
        self.bad("network is none, registry", network="internet")

    def test_the_build_network_needs_a_dockerfile_and_hosts_the_owner_approved(self):
        """Owner decision D1 (2026-11-13): package indexes for build jobs, an explicit host list, nothing without it."""
        with self.assertRaises(V.RunnerError) as e: V.validate(spec(network="build"), FILES)
        self.assertIn("No package index is approved", str(e.exception))
        with self.assertRaises(V.RunnerError) as e: V.validate(spec(kind="run", dockerfile="", images=[PY], command="true", network="build"), FILES, ["pypi.org"])
        self.assertIn("builds a Dockerfile", str(e.exception))
        job, held = V.validate(spec(network="build"), FILES, ["files.pythonhosted.org", "PyPI.org.", "*.evil.org", "pypi.org:8080", "10.0.0.1", "https://x.org/simple"])
        self.assertEqual((job["network"], job["package_hosts"], held), ("build", ["files.pythonhosted.org", "pypi.org"], []))
        other, _ = V.validate(spec(network="build"), FILES, ["pypi.org"])
        self.assertNotEqual(V.job_sha(job), V.job_sha(other))                 # the job's hash says which indexes its build could reach
        self.assertEqual(V.job_sha({**job, "build_proxy": "http://t@x"}), V.job_sha(job))
        self.assertEqual(V.package_hosts('["pypi.org", 5, "a b"]'), ["pypi.org"]); self.assertEqual(V.package_hosts("not json"), [])

    def test_compose_services_cannot_reach_past_their_container(self):
        ok = f"services:\n  api:\n    build: .\n    ports: ['18000:8000']\n    volumes: ['./data:/data', 'cache:/c']\n  web:\n    image: {NGINX}\nvolumes: {{cache: {{}}}}\n"
        job, _ = V.validate(spec(kind="run", dockerfile="", compose="compose.yaml"), {**FILES, "compose.yaml": ok})
        self.assertEqual(job["check_hosts"], ["ghcr.io", "registry-1.docker.io"])
        for bad, why in (("    privileged: true", "may not set privileged"), ("    network_mode: host", "share the VM's network_mode"),
                         ("    pid: host", "share the VM's pid"), ("    volumes: ['/:/host']", "may mount only"),
                         ("    volumes: ['/var/run/docker.sock:/var/run/docker.sock']", "may mount only"), ("    volumes: ['../x:/x']", "may mount only"),
                         ("    cap_add: [SYS_ADMIN]", "may not set cap_add"), ("    devices: ['/dev/kvm']", "may not set devices")):
            self.bad(why, kind="run", dockerfile="", compose="compose.yaml", files={**FILES, "compose.yaml": f"services:\n  api:\n    image: {NGINX}\n{bad}\n"})
        self.bad("isn't pinned", kind="run", dockerfile="", compose="c.yaml", files={"c.yaml": "services:\n  api:\n    image: nginx:latest\n"})
        self.bad("isn't among the job's files", kind="run", dockerfile="", compose="c.yaml", files={"c.yaml": "services:\n  api:\n    build: ./svc\n"})
        self.bad("neither an image nor a build", kind="run", dockerfile="", compose="c.yaml", files={"c.yaml": "services:\n  api: {}\n"})
        self.bad("may not include", kind="run", dockerfile="", compose="c.yaml", files={"c.yaml": f"include: [x.yaml]\nservices:\n  api:\n    image: {NGINX}\n"})

    def test_what_a_job_must_and_may_not_name(self):
        self.bad("kind must be one of", kind="shell")
        self.bad("names a dockerfile or a compose", dockerfile="")
        self.bad("gives a command", kind="bench", dockerfile="")
        self.bad("There's no Dockerfile.gpu", dockerfile="Dockerfile.gpu")
        for p in ("/etc/passwd", "../x", "a/../../b", ""):
            if p: self.bad("must be a path inside", artifacts=[p])
        self.bad("Only a bench job names a score_file", score_file="bench_out/live.json")
        self.bad("at most 20 artifact", artifacts=[f"a{i}" for i in range(21)])
        self.bad("never given by value", secrets=["sk-live-123"])

    def test_secrets_and_pushes_are_held_never_started(self):
        job, held = V.validate(spec(kind="bench", command="sh bench/run.sh", secrets=["BEX_CHALLENGE_API_KEY"]), FILES)
        self.assertEqual(held, ["it names the secret BEX_CHALLENGE_API_KEY"])
        _, held = V.validate(spec(kind="push"), FILES)
        self.assertEqual(held, ["it pushes an image to a registry"])
        r = V.Runner(FakeKube(), FakeProxy(), FakeEgress())
        with self.assertRaises(V.RunnerError): r.run({**job, "id": 1}, FILES)
        self.assertEqual(r.kube.created, [])

    def test_the_job_hash_ignores_the_run_and_changes_with_the_job(self):
        a, _ = V.validate(spec(), FILES); b, _ = V.validate(spec(memory_mb=2048), FILES)
        self.assertEqual(V.job_sha({**a, "id": 5, "proxy": "http://t@x"}), V.job_sha(a))
        self.assertNotEqual(V.job_sha(a), V.job_sha(b))
        self.assertNotEqual(V.inputs(a, FILES)["files_sha256"], V.inputs(a, {**FILES, "app.py": "print('ho')\n"})["files_sha256"])

    def test_the_score_file(self):
        self.assertEqual(V.read_score('{"score": 0.81, "solved": 13, "tasks": 16, "x": 1}'), ({"score": 0.81, "solved": 13, "tasks": 16}, ""))
        self.assertEqual(V.read_score('{"score": 0}')[0], {"score": 0.0})
        for bad in ("", "0.8", '{"score": "0.8"}', '{"score": true}', '{"result": 1}', "[1]"): self.assertIsNone(V.read_score(bad)[0], bad)

    def test_the_egress_proxy_allowlist(self):
        allow = egress_proxy.Run("t" * 24, 1, 1, 60, ["docker.io", "GHCR.io.", "bad host!"]).allow
        self.assertEqual(allow, ("docker.io", "ghcr.io"))
        for h, ok in (("registry-1.docker.io", True), ("docker.io", True), ("ghcr.io", True), ("evildocker.io", False), ("pypi.org", False), ("docker.io.evil.com", False)):
            self.assertEqual(egress_proxy.allowed(h, allow), ok, h)
        self.assertTrue(egress_proxy.allowed("pypi.org", ()))  # a sandbox run with internet has no list, as before
        run = egress_proxy.Run("t" * 24, 1, 1, 60, ["docker.io"], ["pypi.org", "files.pythonhosted.org"])  # a build: registries, and exactly these indexes
        for h, ok in (("pypi.org", True), ("files.pythonhosted.org", True), ("test.pypi.org", False), ("pypi.org.evil.com", False), ("registry-1.docker.io", True), ("github.com", False)):
            self.assertEqual(egress_proxy.allowed(h, run.allow, run.exact), ok, h)
        self.assertFalse(egress_proxy.allowed("docker.io", (), ("pypi.org",)))  # an exact list alone is a list too


# ---------- the pod and the result ----------
class FakeProxy:
    server = object()
    def __init__(self): self.hooks, self.closed = {}, []
    def open(self, cap, hook=None, save=None): self.hooks["tok-" + "x" * 24] = (cap, hook); return "tok-" + "x" * 24
    def close(self, token): self.closed.append(token); return {"spent": 0.0, "calls": 0}


class FakeEgress:
    def __init__(self, fail=False): self.calls, self.fail = [], fail
    def _call(self, method, path, body=None, timeout=10):
        if self.fail: raise OSError("refused")
        self.calls.append((method, path, body))
        return {"ok": True, **({"https_only": (body or {}).get("https_only") is True} if method == "POST" and path == "/runs" else {})}  # as the proxy answers
    def close(self, token): self.calls.append(("DELETE", token, None)); return {"hosts": {"registry-1.docker.io": {"conns": 3, "up": 900, "down": 52_000_000}}, "refused": []}


class FakeKube:
    """A cluster that runs the pod at once: on the first status read it posts `report` to the job's result hook, then says terminated."""
    enabled = True
    def __init__(self, kvm="2", report=None, exit_code=0, missing=False, proxy=None):
        self.kvm, self.report, self.exit, self.missing, self.proxy = kvm, report, exit_code, missing, proxy
        self.created, self.deleted, self.posted = [], [], None
    def call(self, method, path, params=None, body=None, timeout=30, **k):
        if self.missing: raise KubeError(404, "namespaces \"axor-runner\" not found")
        if method == "POST": self.created.append((path.rsplit("/", 1)[-1], body))
        return {"items": []}
    def get(self, path):
        if path.endswith("/resourcequotas/runner"): return {"spec": {"hard": {"requests.axor.dev/kvm": self.kvm}}}
        if self.report is not None and self.posted is None:
            _, hook = next(iter(self.proxy.hooks.values()))
            self.posted = hook("POST", V.RESULT_PATH, self.report(self.pod()))
        return {"status": {"containerStatuses": [{"name": "vm", "state": {"terminated": {"exitCode": self.exit}}}]}}
    def items(self, path, params=None): return []
    def delete(self, path, params=None): self.deleted.append(path.rsplit("/", 2)[-2:])
    def logs(self, ns, pod, container=None, tail=300, timestamps=True): return "[runner +  0s] booting the VM"
    def pod(self): return next(b for k, b in self.created if k == "pods")
    def maps(self): return [b for k, b in self.created if k == "configmaps"]


def vm_report(job, files=None, status="done", code=0, base=BASE, job_sha=None, **over):
    """What supervise.py hands over for a job the VM ran."""
    files = {"bench_out/live.json": '{"score": 0.81, "solved": 13, "tasks": 16}'} if files is None else files
    res = {"status": status, "exit": code, "error": "", "output": "[+ 1.0s] $ docker build\n(exit 0)\n",
           "images": [{"ref": "axor-job:9", "id": D2, "how": "built"}, {"ref": PY, "id": D1, "digests": [D1], "how": "pulled"}],
           "stats": {"containers": {"api": {"peak_memory_mb": 412.5, "peak_cpu_percent": 88.0}}, "vm_peak_memory_mb": 900, "cpu_seconds": 41.0, "disk_used_mb": 300,
                     "bytes_in": 52_000_000, "bytes_out": 900, "seconds": 131.0, "retries": 0, "oom_kills": 0},
           "health": [{"name": "api", "status": "running", "health": "healthy", "oom_killed": False, "restarts": 0}],
           "environment": {"runner_script_sha256": "d4" * 32, "docker": "29.9.3", "compose": "5.7.0", "kernel": "6.1.0", "cpus": 2, "memory_mb": 4096},
           "net": {"vm": {"dns": [{"host": "registry-1.docker.io", "ok": True}], "https": [{"host": "registry-1.docker.io", "ok": True, "status": 401}]},
                   "container": {"ok": True}},
           "files": {p: {"sha256": hashlib.sha256(t.encode()).hexdigest(), "bytes": len(t)} for p, t in files.items()}, **over}
    return {"supervisor": {"base": {"sha256": base}, "vm": {"cpus": 2, "memory_mb": 4096}, "inputs": {"job_sha256": job_sha or V.job_sha(job)}},
            "result": res, "files": {p: {"text": t} for p, t in files.items()}}


class Running(unittest.TestCase):
    def setUp(self):
        self._env = (V.IMAGE, V.BASE_SHA); V.IMAGE, V.BASE_SHA = "axor/runner:test", BASE
        self._sleep = V.time.sleep; V.time.sleep = lambda s: None
        self.job, _ = V.validate(spec(kind="bench", command="sh bench/run.sh", score_file="bench_out/live.json", artifacts=["out/log.txt"]), FILES)

    def tearDown(self): V.IMAGE, V.BASE_SHA = self._env; V.time.sleep = self._sleep

    def go(self, report=vm_report, job=None, files=FILES, **kube):
        self.proxy, self.egress = FakeProxy(), FakeEgress()
        job = job or self.job
        self.kube = FakeKube(report=(lambda pod: report(job)) if report else None, proxy=self.proxy, **kube)
        self.r = V.Runner(self.kube, self.proxy, self.egress)
        return self.r.run({**job, "id": 9}, files, label="SN61 team #9")

    def test_not_ready_without_an_image_a_namespace_or_a_kvm_quota(self):
        V.IMAGE = ""
        self.assertEqual(V.Runner(FakeKube(), FakeProxy(), FakeEgress()).ready()[0], False)
        V.IMAGE = "axor/runner:test"
        self.assertIn("isn't set up", V.Runner(FakeKube(missing=True), FakeProxy(), FakeEgress()).ready()[1])
        self.assertIn("no KVM", V.Runner(FakeKube(kvm="0"), FakeProxy(), FakeEgress()).ready()[1])
        self.assertEqual(V.Runner(FakeKube(), FakeProxy(), FakeEgress()).ready(), (True, ""))
        off = types.SimpleNamespace(enabled=False)
        self.assertEqual(V.Runner(off, FakeProxy(), FakeEgress()).ready()[0], False)

    def test_the_pod_has_kvm_and_nothing_else(self):
        self.go()
        pod = self.kube.pod()
        c, s = pod["spec"]["containers"][0], pod["spec"]
        self.assertEqual((s["automountServiceAccountToken"], s["restartPolicy"], s.get("hostNetwork"), s.get("hostPID")), (False, "Never", None, None))
        self.assertEqual(c["securityContext"], {"privileged": False, "allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]}})
        self.assertEqual(c["resources"]["limits"]["axor.dev/kvm"], "1")
        self.assertEqual([v for v in s["volumes"] if "hostPath" in v or "persistentVolumeClaim" in v], [])
        self.assertEqual(len(s["containers"]), 1); self.assertNotIn("initContainers", s)
        env = {e["name"]: e["value"] for e in c["env"]}
        self.assertTrue(env["AXOR_RESULT_URL"].endswith("/t/tok-" + "x" * 24 + V.RESULT_PATH))
        self.assertEqual((env["AXOR_NETWORK"], env["VM_CPUS"], env["VM_MEM_MB"]), ("registry", "2", "4096"))
        self.assertEqual(self.proxy.hooks["tok-" + "x" * 24][0], 0.0)  # no inference budget behind the job's token

    def test_only_a_pulling_job_gets_the_egress_label_and_only_registry_hosts(self):
        self.go()
        self.assertEqual(self.kube.pod()["metadata"]["labels"], {"app": "axor-runner", "axor.dev/internet": "on"})
        (m, path, body), = [c for c in self.egress.calls if c[0] == "POST"]
        self.assertEqual((path, body["hosts"]), ("/runs", list(V.REGISTRY_HOSTS)))
        job, _ = V.validate(spec(network="none"), {"Dockerfile": "FROM scratch\nCOPY app.py /\n", "app.py": ""})
        r = self.go(job=job, files={"Dockerfile": "FROM scratch\nCOPY app.py /\n", "app.py": ""}, report=lambda j: vm_report(j, files={}, net=None))
        self.assertEqual(self.kube.pod()["metadata"]["labels"], {"app": "axor-runner"})
        self.assertNotIn("AXOR_PROXY", {e["name"] for e in self.kube.pod()["spec"]["containers"][0]["env"]})
        self.assertEqual((self.egress.calls, r["net"], r["status"]), ([], None, "done"))

    def test_a_build_job_gets_a_second_proxy_run_for_the_package_indexes_only(self):
        job, _ = V.validate(spec(kind="bench", command="sh bench/run.sh", score_file="bench_out/live.json", network="build"), FILES, ["pypi.org", "files.pythonhosted.org"])
        r = self.go(job=job)
        opened = [b for m, p, b in self.egress.calls if m == "POST"]
        self.assertEqual([(b["hosts"], b.get("hosts_exact")) for b in opened], [(list(V.REGISTRY_HOSTS), None), (list(V.REGISTRY_HOSTS), ["files.pythonhosted.org", "pypi.org"])])
        self.assertNotEqual(opened[0]["token"], opened[1]["token"])
        env = {e["name"]: e["value"] for e in self.kube.pod()["spec"]["containers"][0]["env"]}
        self.assertIn(opened[0]["token"], env["AXOR_PROXY"]); self.assertIn(opened[1]["token"], env["AXOR_BUILD_PROXY"])
        self.assertEqual(env["AXOR_NETWORK"], "build")
        self.assertEqual(len([c for c in self.egress.calls if c[0] == "DELETE"]), 2)   # both runs are closed and read
        self.assertEqual((r["status"], r["net"]["build_egress"]["package_hosts"]), ("done", ["files.pythonhosted.org", "pypi.org"]))
        self.assertIn("hosts", r["net"]["build_egress"]); self.assertNotIn("build_egress", self.go()["net"])  # a registry job has none

    def test_the_job_and_its_files_go_in_and_everything_is_deleted(self):
        r = self.go(files={**FILES, ".env": "KEY=1", "certs/server.key": "x"})
        data = {}
        for m in self.kube.maps(): data.update(m["data"])
        sent = {path: data[k] for k, path in json.loads(data["manifest.json"]).items()}
        self.assertEqual(sorted(sent), sorted([*FILES, V.JOB_FILE]))                      # secret-looking files are held back from a job with a network
        self.assertEqual(json.loads(sent[V.JOB_FILE])["id"], 9)
        self.assertEqual(r["net"]["withheld"], [".env", "certs/server.key"])
        self.assertEqual(sorted(k for k, _ in self.kube.deleted), ["configmaps", "pods"])
        self.assertEqual(len(self.proxy.closed), 1)

    def test_a_reported_job_returns_what_was_measured(self):
        r = self.go()
        self.assertEqual((r["status"], r["exit"], r["services"], r["cost"]), ("done", 0, ["vm-docker"], 0.0))
        self.assertEqual(r["score"], {"score": 0.81, "solved": 13, "tasks": 16})
        self.assertEqual(r["images"][0], {"ref": "axor-job:9", "id": D2, "how": "built"})
        self.assertEqual(r["stats"]["containers"]["api"]["peak_memory_mb"], 412.5)
        self.assertEqual((r["environment"]["base_disk_sha256"], r["environment"]["docker"], r["environment"]["pod_image"]), (BASE, "29.9.3", "axor/runner:test"))
        self.assertEqual((r["inputs"]["job_sha256"], r["inputs"]["files"]), (V.job_sha(self.job), len(FILES)))
        self.assertEqual(r["net"]["egress"]["hosts"]["registry-1.docker.io"]["conns"], 3)
        self.assertEqual(r["files"], {"bench_out/live.json": '{"score": 0.81, "solved": 13, "tasks": 16}'})

    def test_without_a_report_a_job_is_never_done(self):
        r = self.go(report=None)                                           # the pod exited 0 but handed nothing over
        self.assertEqual((r["status"], r["exit"], r["score"]), ("error", None, None)); self.assertIn("without a result", r["error"])
        r = self.go(report=lambda j: {"supervisor": {"error": "The job ran past its time limit and the VM was stopped."}, "result": None, "files": {}}, exit_code=1)
        self.assertEqual(r["status"], "timeout")

    def test_another_job_or_another_base_disk_is_an_error(self):
        self.assertIn("another job", self.go(report=lambda j: vm_report(j, job_sha="0" * 64))["error"])
        r = self.go(report=lambda j: vm_report(j, base="e5" * 32))
        self.assertEqual(r["status"], "error"); self.assertIn("base disk", r["error"])

    def test_a_failed_job_keeps_its_exit_and_its_score_apart(self):
        r = self.go(report=lambda j: vm_report(j, status="failed", code=3))
        self.assertEqual((r["status"], r["exit"], r["score"]), ("failed", 3, {"score": 0.81, "solved": 13, "tasks": 16}))  # Q-5: the score is reported, the exit is too
        r = self.go(report=lambda j: vm_report(j, files={}))
        self.assertEqual((r["status"], r["score"]), ("done", None)); self.assertIn("returned no bench_out/live.json", r["score_error"])

    def test_an_artifact_that_is_not_the_one_the_vm_hashed_is_dropped(self):
        def forged(j):
            b = vm_report(j); b["files"]["bench_out/live.json"] = {"text": '{"score": 0.99}'}; return b
        r = self.go(report=forged)
        self.assertEqual((r["files"], r["score"]), ({}, None)); self.assertIn("isn't the one the VM hashed", r["artifacts"]["bench_out/live.json"]["error"])

    def test_the_egress_proxy_refusing_stops_the_job_before_a_pod(self):
        self.proxy, self.egress = FakeProxy(), FakeEgress(fail=True)
        self.kube = FakeKube(proxy=self.proxy)
        r = V.Runner(self.kube, self.proxy, self.egress).run({**self.job, "id": 9}, FILES)
        self.assertEqual((r["status"], [k for k, _ in self.kube.created]), ("error", [])); self.assertIn("egress proxy", r["error"])


# ---------- the team board, the benchmark row and D-004's internal measure ----------
class FakeRunner:
    """Stands in for Runner.run: returns what a VM that ran the job would, through the real finish()."""
    def __init__(self, **report): self.report, self.jobs = report, []
    def ready(self): return True, ""
    def configured(self): return True, ""
    def quota(self): return 2
    def run(self, job, files, label="", cancelled=None, started=None, workspace=None):
        self.jobs.append((job, files)); started and started("job-1-abc")
        clean = {k: v for k, v in job.items() if k != "id"}
        return V.finish(clean, vm_report(clean, **self.report), "done", 0, "", "", "job-1-abc", V.inputs(clean, files, workspace), 131.0, {"hosts": {}}, [], [])


def board(db, **report):
    w = object.__new__(mining_work.Work)
    w.db, w.lock, w.events = db, threading.Lock(), []
    w._event = lambda wid, kind, text, **k: w.events.append(text)
    w._label = lambda x: "team"
    w.runner = FakeRunner(**report)
    return w


@own_tests
class Board(tp.Base):
    """mining_work._docker_job → mw_sbx + the kept result → record_benchmark → missions._ev_bench."""
    def setUp(self):
        super().setUp()
        self._base = V.BASE_SHA; V.BASE_SHA = BASE
        self.db.q("DROP TABLE IF EXISTS mw_sbx"); sbx_table(self.db.q)
        self.db.q("ALTER TABLE mw_sbx ADD COLUMN net TEXT")
        self.db.q("DROP TABLE IF EXISTS mw_files")
        self.db.q("""CREATE TABLE mw_files (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, path TEXT, content TEXT, size INTEGER, agent_id INTEGER,
                     updated REAL, UNIQUE (comp_id, path))""")
        self.db.q("""CREATE TABLE IF NOT EXISTS mw_tasks (id INTEGER PRIMARY KEY, comp_id INTEGER, title TEXT, detail TEXT, status TEXT, agent_id INTEGER,
                     priority TEXT, due TEXT, origin TEXT, created REAL, updated REAL, mission TEXT)""")
        self.db.q("CREATE TABLE IF NOT EXISTS mw_agents (id INTEGER PRIMARY KEY, name TEXT)")
        for p, t in FILES.items(): self.db.q("INSERT INTO mw_files (comp_id, path, content, size) VALUES (?,?,?,?)", (tp.WID, p, t, len(t)))
        self.w = board(self.db)
        work = types.SimpleNamespace(db=self.db, lock=threading.Lock(), _own=lambda me, wid: ({"id": wid}, {"id": 1}), _agents=lambda wid: [],
                                     _event=lambda *a, **k: None)
        self.rel = R.Release(work)
        self.rel.freeze({"id": 1, "username": "leo"}, tp.WID, R.FreezeIn(commit=CAND, suite="swe-mini", tasks=16, repeats=1, image_digest=D2))
        self.c, self.comp, self.agent = {"netuid": 61}, {"id": tp.WID}, {"id": 1, "name": "Morgan"}

    def tearDown(self):
        V.BASE_SHA = self._base; db = self.db
        super().tearDown(); close_db(db)

    def job(self, run=RUN, **kw):
        return self.w._docker_job(self.comp, self.c, spec(kind="bench", command="sh bench/run.sh", score_file="bench_out/live.json", **kw), task=5, run=run, agent=self.agent)

    def bench(self, run=RUN, score=0.99):
        return self.rel.record(tp.WID, self.rel.current(tp.WID), {"candidate": CAND, "suite": "swe-mini", "tasks": 16, "repeats": 1, "score": score}, task=5, agent=1, run=run)

    def measure(self):
        if not hasattr(self, "mid"): self.mid = self.create([tp.chain_measure(), tp.bench_measure()], keys=[])  # a persistent mission needs an external measure too
        return self.one(self.mid, 1)

    def test_a_job_is_a_sandbox_run_row_with_its_result_kept_and_named_by_hash(self):
        out = self.job()
        s = self.db.q("SELECT * FROM mw_sbx WHERE id=?", (out["sbx"],), one=True)
        self.assertEqual((s["services"], s["status"], s["exit_code"], s["run_id"], s["task_id"], s["agent_id"], s["pod"]), ("vm-docker", "done", 0, RUN, 5, 1, "job-1-abc"))
        self.assertTrue(s["command"].startswith("docker_job bench dockerfile=Dockerfile: sh bench/run.sh"))
        doc = self.db.q("SELECT content FROM mw_files WHERE comp_id=? AND path=?", (tp.WID, f"runs/sbx-{s['id']}/result.json"), one=True)["content"]
        self.assertIn(f"@@AXOR-RESULT sha256:{hashlib.sha256(doc.encode()).hexdigest()} runs/sbx-{s['id']}/result.json", s["output"])
        d = V.stored(self.db, tp.WID, s["id"])
        self.assertEqual((d["score"], d["environment"]["base_disk_sha256"], d["inputs"]["job_sha256"]), ({"score": 0.81, "solved": 13, "tasks": 16}, BASE, out["inputs"]["job_sha256"]))
        self.assertEqual(out["kept"], [f"runs/sbx-{s['id']}/result.json", f"runs/sbx-{s['id']}/files/bench_out/live.json"])
        self.assertNotIn("files", out)                                                   # the agent gets the facts, not the artifact texts
        self.assertIn("score 0.81 from bench_out/live.json", self.w.events[-1])

    def test_job_results_do_not_use_up_the_teams_file_limits(self):
        for _ in range(3): self.job()
        kept = self.db.q("SELECT COUNT(*) n FROM mw_files WHERE comp_id=? AND path LIKE 'runs/sbx-%'", (tp.WID,), one=True)["n"]
        self.assertEqual(kept, 6)
        old = mining_work.MAX_FILES; mining_work.MAX_FILES = len(FILES) + 1    # room for exactly one more file of the team's own
        try:
            self.w._write_file(tp.WID, "notes.md", "the team's own file")
            with self.assertRaises(LookupError): self.w._write_file(tp.WID, "more.md", "one too many")
        finally: mining_work.MAX_FILES = old

    def test_earlier_results_are_not_sent_into_the_next_job(self):
        self.job(); self.job()
        self.assertEqual(sorted(self.w.runner.jobs[1][1]), sorted(FILES))

    def test_only_the_owner_names_the_package_indexes_and_the_board_passes_them_on(self):
        owner, admin = self.me(tp.OWNER), self.me(tp.ADMIN)
        with self.assertRaises(LookupError) as e: self.job(network="build")
        self.assertIn("No package index is approved", str(e.exception))
        for who in (admin, self.me(tp.TEAM_ACCOUNT)):
            with self.assertRaises(Exception) as e: self.w.set_package_hosts(who, ["pypi.org"])
            self.assertEqual(e.exception.status_code, 403)
        with self.assertRaises(Exception) as e: self.w.set_package_hosts(owner, ["pypi.org", "*.pythonhosted.org"])
        self.assertEqual(e.exception.status_code, 422)
        self.assertEqual(self.w.set_package_hosts(owner, ["pypi.org", "files.pythonhosted.org"], "10.0.0.9"), {"hosts": ["files.pythonhosted.org", "pypi.org"]})
        a = self.db.q("SELECT actor, ip, detail FROM audit WHERE action='runner.package_hosts'", one=True)
        self.assertEqual((a["actor"], a["ip"], a["detail"]), ("the-owner", "10.0.0.9", "none -> files.pythonhosted.org,pypi.org"))
        self.job(network="build")
        self.assertEqual(self.w.runner.jobs[-1][0]["package_hosts"], ["files.pythonhosted.org", "pypi.org"])
        self.w.set_package_hosts(owner, [])                                                # an empty list turns it off again
        with self.assertRaises(LookupError): self.job(network="build")

    def test_a_job_that_names_a_secret_is_held_and_never_run(self):
        out = self.job(secrets=["BEX_CHALLENGE_API_KEY"])
        s = self.db.q("SELECT status, error, finished FROM mw_sbx WHERE id=?", (out["sbx"],), one=True)
        self.assertEqual((out["status"], s["status"], self.w.runner.jobs), ("held", "held", [])); self.assertIn("person's approval", s["error"])
        self.assertIsNone(V.stored(self.db, tp.WID, out["sbx"]))
        self.assertEqual(self.rel.evidence(tp.WID, RUN), None)

    def test_an_unpinned_job_is_refused_and_leaves_no_row(self):
        self.db.q("UPDATE mw_files SET content='FROM python:3.12\n' WHERE path='Dockerfile'")
        with self.assertRaises(LookupError): self.job()
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM mw_sbx", one=True)["n"], 0)

    def test_the_benchmark_row_takes_the_score_from_the_job_not_from_the_agent(self):
        out = self.job()
        r = self.bench(score=0.99)                                                        # the agent files 0.99; the job's file says 0.81
        b = self.db.q("SELECT * FROM mw_bench ORDER BY id DESC LIMIT 1", one=True)
        self.assertEqual((r["evidence_ref"], r["score"], r["score_source"], b["score"], b["solved"], b["evidence_ref"], b["comparable"]),
                         (f"job:{out['sbx']}", 0.81, "job_output", 0.81, 13, f"job:{out['sbx']}", 1))
        self.assertIn("[filed as 0.99; the job's output file says 0.81]", b["note"])

    def test_a_score_file_that_counts_other_tasks_is_not_comparable(self):
        self.w.runner = FakeRunner(files={"bench_out/live.json": '{"score": 0.9, "tasks": 30}'})
        self.job()
        r = self.bench()
        self.assertEqual(r["comparable"], False); self.assertIn("counts 30 tasks", "; ".join(r["why"]))

    def test_a_job_without_a_score_or_a_plain_sandbox_run_stays_an_sbx_reference(self):
        self.w.runner = FakeRunner(files={})
        out = self.job()
        self.assertEqual(self.rel.evidence(tp.WID, RUN), f"sbx:{out['sbx']}")
        r = self.bench(score=0.7)
        self.assertEqual((r["score"], r["score_source"]), (0.7, "filed"))

    def test_a_failed_job_backs_nothing(self):
        self.w.runner = FakeRunner(status="failed", code=2)
        out = self.job()
        self.assertEqual((out["status"], out["score"]["score"]), ("failed", 0.81))      # reported, but not evidence
        self.assertIsNone(V.stored(self.db, tp.WID, out["sbx"])); self.assertIsNone(self.rel.evidence(tp.WID, RUN))

    def test_the_internal_measure_is_valid_on_a_job_reference_and_says_where_the_score_came_from(self):
        out = self.job(); self.bench(score=0.99)
        e = self.measure()
        self.assertEqual((e["status"], e["value"], e["pass"], e["category"]), ("valid", 0.81, True, "internal"))
        ref = e["evidence_ref"]
        self.assertEqual((ref["sandbox_run"], ref["score_source"], ref["image_digest"]), (f"job:{out['sbx']}", "read from the job's output file", D2))
        self.assertEqual((ref["job"]["base_disk_sha256"], ref["job"]["inputs"]["job_sha256"]), (BASE, out["inputs"]["job_sha256"]))

    def test_an_edited_result_file_is_no_longer_evidence(self):
        out = self.job(); self.bench()
        self.db.q("UPDATE mw_files SET content=REPLACE(content, '0.81', '0.95') WHERE path=?", (f"runs/sbx-{out['sbx']}/result.json",))
        self.assertIsNone(V.stored(self.db, tp.WID, out["sbx"]))
        self.assertEqual(self.measure()["status"], "unverifiable")

    def test_a_row_whose_score_is_not_the_jobs_is_unverifiable(self):
        out = self.job(); self.bench()
        self.db.q("UPDATE mw_bench SET score=0.95")
        self.assertEqual(self.measure()["status"], "unverifiable")

    def test_a_job_of_another_team_backs_nothing(self):
        out = self.job(); self.bench()
        self.db.q("UPDATE mw_sbx SET comp_id=99 WHERE id=?", (out["sbx"],))
        self.assertEqual(self.measure()["status"], "unverifiable")

    def test_the_docker_probe_passes_only_after_a_real_job_on_the_current_base_disk(self):
        mo._probe_cache.clear()
        ch = types.SimpleNamespace(db=self.db, w=types.SimpleNamespace(sbx=None, runner=None), _has=lambda t: True)
        state = lambda cap: mo.probe(ch, {"id": tp.WID}, cap, fresh=True)
        self.assertEqual((state("docker")["state"], state("vm")["state"], state("registry")["state"]), ("FAIL", "UNKNOWN", "FAIL"))  # no runner installed
        ch.w.runner = self.w.runner
        self.assertEqual((state("docker")["state"], state("vm")["state"]), ("UNKNOWN", "PASS"))  # installed, quota 2, but no job yet
        out = self.job()
        p = state("docker")
        self.assertEqual((p["state"], p["how"]), ("PASS", "job")); self.assertIn(f"job #{out['sbx']}", p["evidence"])
        V.BASE_SHA = "f6" * 32                                                             # the base disk was rebuilt: the old job doesn't count
        self.assertEqual(state("docker")["state"], "UNKNOWN")
        V.BASE_SHA = BASE
        self.db.q("UPDATE mw_sbx SET finished=?", (time.time() - 8 * 86400,))
        self.assertEqual(state("docker")["state"], "UNKNOWN")                              # older than 7 days
        self.assertEqual(state("registry")["state"], "FAIL")
        ch.w.runner.ready = lambda: (False, "The axor-runner namespace isn't set up for AXoR.")
        self.assertEqual(state("docker")["state"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
