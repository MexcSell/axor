"""G5 closure, T-5 (runner cluster objects; e2e/G5_REMAINING_BLOCKERS.md row T-5): the acceptance tests of
g5-plan/closure/T5_RUNNER_CLUSTER_CONTRACT.md (A-T5-1 .. A-T5-14).

NOTHING HERE PROVES T-5. T-5 closes only when the cluster-gated tests below pass against an authorized staging cluster.

Three groups:
- AXoR side, no cluster (A-T5-1 .. A-T5-6 and A-T5-9): what AXoR's runner code puts in a job's pod, checked against the manifests in k8s/runner when
  they can be found. They run in the normal suite; the ones that read a manifest skip (with the reason) when k8s/ isn't mounted: suite.sh mounts only
  backend/app and tests/unit. Set AXOR_T5_MANIFESTS to the folder that holds 58-runner.yaml to run them there.
- Cluster objects (A-T5-7, A-T5-8, A-T5-10, A-T5-11): read-only kubectl against the cluster named by AXOR_T5_CLUSTER, which must be the PATH of a kubeconfig file
  made for the authorized staging cluster. The ambient kubeconfig and KUBECONFIG are never used. AXOR_T5_KUBECTL names the binary (default: kubectl).
- Cluster behaviour (A-T5-12 .. A-T5-14 and the dynamic cases): a job driver ran the case on the cluster and wrote case-<id>.json into AXOR_T5_EVIDENCE;
  the test checks that file is well formed, says PASS, is not from a stand-in, and belongs to THIS cluster (its kube-system namespace uid). The tests do
  not produce the evidence: they refuse to pass without it.
Without AXOR_T5_CLUSTER every cluster test is skipped, and a skip is not a pass.
"""
import json, os, re, subprocess, sys, unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import yaml  # noqa: E402

from app import runner as V  # noqa: E402
import test_vm_runner as tv  # noqa: E402

OFFICIAL_CHALLENGE = "redteamsubnet61/rest-bex-challenge@sha256:1be2236585bc10012b14e91caaa9f37d7b61d5004976fdeab02faea249e089bb"
NODE_IMAGE = "node@sha256:18a6d90fd60542269850c80ca03b29b1d9b14d6b221ac7ee8e35b0d33ef904bd"
CLUSTER = os.getenv("AXOR_T5_CLUSTER", "")
EVIDENCE = os.getenv("AXOR_T5_EVIDENCE", "")
DYNAMIC_CASES = {"A-T5-12": "result delivered across namespaces", "A-T5-13": "kubelet deadline, cancel and cleanup",
                 "A-T5-14": "egress: direct connection refused, proxy allowlist, DNS state, pod process limit"}
EVIDENCE_KEYS = ("case", "status", "cluster_uid", "tree_commit", "runner_image", "runner_image_digest", "base_disk_sha256", "started_utc", "ended_utc",
                 "stand_in", "observations")


def manifest_dir():
    """The folder with 58-runner.yaml, or None: AXOR_T5_MANIFESTS, else k8s/runner above this file (it isn't there in suite.sh's mounts)."""
    if os.getenv("AXOR_T5_MANIFESTS"): cands = [Path(os.environ["AXOR_T5_MANIFESTS"])]
    else: cands = [p / "k8s" / "runner" for p in Path(__file__).resolve().parents]
    return next((c for c in cands if (c / "58-runner.yaml").is_file()), None)


def docs(name):
    d = manifest_dir()
    if d is None or not (d / name).is_file(): raise unittest.SkipTest(f"k8s/runner/{name} not found (set AXOR_T5_MANIFESTS); the manifest checks did not run")
    return [x for x in yaml.safe_load_all((d / name).read_text()) if x]


def kind(items, k, name=None):
    return [x for x in items if x["kind"] == k and (name is None or x["metadata"]["name"] == name)]


def qty(v):
    """A Kubernetes quantity as a number: cpu in cores, memory and storage in bytes."""
    s = str(v); m = re.fullmatch(r"([0-9.]+)(m|Ki|Mi|Gi|Ti|k|M|G)?", s)
    if not m: raise ValueError(s)
    n, u = float(m.group(1)), m.group(2)
    return n * {None: 1, "m": 1e-3, "Ki": 1024, "Mi": 1024 ** 2, "Gi": 1024 ** 3, "Ti": 1024 ** 4, "k": 1e3, "M": 1e6, "G": 1e9}[u]


SCRATCH = {"Dockerfile": "FROM scratch\nCOPY app.py /\n", "app.py": "", "bench/run.sh": "true\n"}   # a job with network none may only build FROM scratch


def files_for(net): return SCRATCH if net == "none" else tv.FILES


EP = {"proxy_url": "http://axor-aef-web:8091", "egress_proxy": "axor-aef-egress:3128", "no_proxy": "axor-aef-web", "by_address": False}


class Fixture(unittest.TestCase):
    """The module globals test_vm_runner patches (image, base disk, sleep) are put back in tearDown: a leak only shows in the full run."""
    def setUp(self):
        self._env = (V.IMAGE, V.BASE_SHA, V.time.sleep); V.IMAGE, V.BASE_SHA = "axor/runner:test", tv.BASE; V.time.sleep = lambda s: None

    def tearDown(self): V.IMAGE, V.BASE_SHA, V.time.sleep = self._env

    def pod(self, network="registry", **kw):
        sp = tv.spec(kind="bench", command="sh bench/run.sh", score_file="bench_out/live.json", network=network, **kw)
        job, _ = V.validate(sp, files_for(network), ["pypi.org"] if network == "build" else ())
        build = "build" if network == "build" else None
        r = V.Runner(tv.FakeKube(), tv.FakeProxy(), tv.FakeEgress())
        wall = job["timeout_s"] + (job["build_timeout_s"] if job.get("dockerfile") else 0) + 300
        return job, wall, r._pod("job-1", job, "tok-" + "x" * 24, None if network == "none" else "net-tok", ["cm-1"], "SN61", wall, build_token="bld-tok" if build else None, ep=EP)


class ImagesPinned(Fixture):
    """A-T5-1: every image a job pulls is named by digest, and the official SN61 challenge image is exactly the one the plan names."""
    def test_a_tag_is_refused_everywhere_an_image_can_be_named(self):
        for imgs in (["python:3.12-slim"], ["redteamsubnet61/rest-bex-challenge:1.0.0"], [f"node@sha256:{'a' * 63}"]):
            with self.assertRaises(V.RunnerError): V.validate(tv.spec(images=imgs), tv.FILES)
        with self.assertRaises(V.RunnerError): V.validate(tv.spec(), {**tv.FILES, "Dockerfile": "FROM node:20\n"})

    def test_the_official_sn61_challenge_image_is_accepted_by_digest_and_only_that_form(self):
        job, _ = V.validate(tv.spec(images=[NODE_IMAGE, OFFICIAL_CHALLENGE]), tv.FILES)
        self.assertEqual(job["images"], [NODE_IMAGE, OFFICIAL_CHALLENGE])
        self.assertTrue(OFFICIAL_CHALLENGE.endswith("sha256:1be2236585bc10012b14e91caaa9f37d7b61d5004976fdeab02faea249e089bb"))
        self.assertEqual(V._registry_host(OFFICIAL_CHALLENGE), "registry-1.docker.io")

    def test_the_job_hash_changes_when_an_image_changes(self):
        a, _ = V.validate(tv.spec(images=[OFFICIAL_CHALLENGE]), tv.FILES)
        b, _ = V.validate(tv.spec(images=[OFFICIAL_CHALLENGE.replace("1be22365", "1be22366")]), tv.FILES)
        self.assertNotEqual(V.job_sha(a), V.job_sha(b))

    def test_the_runner_pod_image_is_the_configured_one_and_a_base_disk_hash_gates_the_result(self):
        # What the code does today (contract gap G-1): the pod's own image is whatever RUNNER_IMAGE says (a tag, pull policy Never), checked
        # against the base disk's sha256 (RUNNER_BASE_SHA256) when a result comes back. Only the jobs' images are pinned by digest.
        _, _, pod = self.pod()
        self.assertEqual(pod["spec"]["containers"][0]["image"], V.IMAGE)
        self.assertEqual(pod["spec"]["containers"][0]["imagePullPolicy"], V.PULL)
        self.assertEqual(len(tv.BASE), 64)

    @unittest.expectedFailure
    def test_GAP_G1_the_runner_pod_image_is_pinned_by_digest(self):
        """Desired by the contract (section 4): RUNNER_IMAGE must be name@sha256:<64 hex>. The code does not enforce it today, so this is an
        expected failure; when AXoR starts to refuse a tag-only runner image this test turns into an unexpected success, which is the signal to
        remove the decorator."""
        V.IMAGE = "axor/runner:test"
        self.assertTrue(V.PIN.match(self.pod()[2]["spec"]["containers"][0]["image"]), "the runner pod image is a tag")


class PodLimits(Fixture):
    """A-T5-2 (resource limits in the pod) and A-T5-3 (what the pod may be)."""
    def test_every_resource_has_a_limit_and_a_request(self):
        _, _, pod = self.pod()
        c = pod["spec"]["containers"][0]; lim, req = c["resources"]["limits"], c["resources"]["requests"]
        for k in ("cpu", "memory", "ephemeral-storage", "axor.dev/kvm"): self.assertIn(k, lim, k)
        for k in ("cpu", "memory", "axor.dev/kvm"): self.assertIn(k, req, k)
        self.assertEqual((lim["axor.dev/kvm"], req["axor.dev/kvm"]), ("1", "1"))
        self.assertGreater(qty(lim["memory"]), qty(req["memory"]) - 1)
        self.assertEqual(pod["spec"]["volumes"][1]["emptyDir"]["sizeLimit"], "28Gi")
        self.assertLess(qty(pod["spec"]["volumes"][1]["emptyDir"]["sizeLimit"]), qty(lim["ephemeral-storage"]))

    def test_the_pod_asks_for_more_than_the_vm_it_runs(self):
        job, _, pod = self.pod(memory_mb=4096, cpus=2)
        lim = pod["spec"]["containers"][0]["resources"]["limits"]
        self.assertGreater(qty(lim["memory"]), job["memory_mb"] * 1024 ** 2)
        self.assertGreater(qty(lim["cpu"]), job["cpus"])

    def test_the_pod_is_no_more_than_a_kvm_user(self):
        _, _, pod = self.pod()
        s, c = pod["spec"], pod["spec"]["containers"][0]
        self.assertEqual((s["automountServiceAccountToken"], s["restartPolicy"], s["enableServiceLinks"], s.get("hostNetwork"), s.get("hostPID"), s.get("hostIPC")),
                         (False, "Never", False, None, None, None))
        self.assertEqual(s["securityContext"], {"seccompProfile": {"type": "RuntimeDefault"}})
        self.assertEqual(c["securityContext"], {"privileged": False, "allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]}})
        self.assertEqual([v for v in s["volumes"] if set(v) - {"name", "projected", "emptyDir"}], [])   # no hostPath, secret, PVC, docker socket
        self.assertNotIn("initContainers", s); self.assertEqual(len(s["containers"]), 1)

    def test_the_pod_environment_carries_no_secret_of_axor(self):
        _, _, pod = self.pod("build")
        env = {e["name"]: e["value"] for e in pod["spec"]["containers"][0]["env"]}
        self.assertEqual(sorted(env), sorted(["AXOR_RESULT_URL", "AXOR_TIMEOUT", "AXOR_NETWORK", "VM_CPUS", "VM_MEM_MB", "NO_PROXY", "no_proxy", "AXOR_PROXY", "AXOR_BUILD_PROXY"]))
        for v in env.values(): self.assertNotRegex(v, r"(?i)api[_-]?key|secret|password|bearer")


class Timeouts(Fixture):
    """A-T5-4: a job can't outlive its limits, and the pod's own deadline is the last line."""
    def test_the_pod_deadline_is_after_the_supervisor_timeout_which_is_after_the_job_timeout(self):
        for net in ("none", "registry", "build"):
            sp = tv.spec(kind="bench", command="sh bench/run.sh", network=net, timeout_s=99999)
            job, _ = V.validate(sp, files_for(net), ["pypi.org"] if net == "build" else ())
            self.assertEqual(job["timeout_s"], V.MAX_TIMEOUT)
            _, wall, pod = self.pod(net, timeout_s=99999)
            env = {e["name"]: e["value"] for e in pod["spec"]["containers"][0]["env"]}
            self.assertGreaterEqual(int(env["AXOR_TIMEOUT"]), job["timeout_s"])
            self.assertEqual(pod["spec"]["activeDeadlineSeconds"], wall + 300)
            self.assertGreater(pod["spec"]["activeDeadlineSeconds"], int(env["AXOR_TIMEOUT"]) + 240 - 1)

    def test_a_job_with_no_report_is_a_timeout_or_an_error_never_done(self):
        # the existing runner test with the same name pins this; here it is the contract's A-T5-4 AXoR half, for a pod that ended without a report
        r = V.finish({"kind": "bench", "network": "none", "timeout_s": 60}, {}, "timeout", None, "The job took too long (or never started) and was stopped.", "", "p", None, 1.0)
        self.assertEqual(r["status"], "timeout"); self.assertNotEqual(r["status"], "done")


class Egress(Fixture):
    """A-T5-5: what a pod may reach is declared on the pod (a label) and by the namespace's policies (the manifest)."""
    def test_only_a_pulling_job_has_the_internet_label(self):
        self.assertEqual(self.pod("none")[2]["metadata"]["labels"], {"app": "axor-runner"})
        for net in ("registry", "build"): self.assertEqual(self.pod(net)[2]["metadata"]["labels"], {"app": "axor-runner", "axor.dev/internet": "on"})

    def test_the_proxy_is_opened_for_registry_hosts_only(self):
        self.assertEqual(V.REGISTRY_HOSTS, ("docker.io", "docker.com", "ghcr.io", "pkg-containers.githubusercontent.com"))   # D8-c; the env can change it: pinned for this tree

    def test_the_manifest_is_default_deny_with_two_destinations(self):
        pols = {p["metadata"]["name"]: p for p in kind(docs("58-runner.yaml"), "NetworkPolicy")}
        base = pols["runner"]["spec"]
        self.assertEqual((base["podSelector"], sorted(base["policyTypes"]), base["ingress"]), ({}, ["Egress", "Ingress"], []))
        ports = sorted((r["ports"][0]["port"], r["to"][0]["namespaceSelector"]["matchLabels"]["kubernetes.io/metadata.name"]) for r in base["egress"])
        self.assertEqual(ports, [(53, "kube-system"), (8091, "axor")])                  # DNS is still there: Owner item O-10 decides it, not this test
        reg = pols["runner-registry"]["spec"]
        self.assertEqual(reg["podSelector"]["matchLabels"], {"axor.dev/internet": "on"})
        self.assertEqual([r["ports"][0]["port"] for r in reg["egress"]], [3128])
        self.assertEqual(reg["egress"][0]["to"][0]["namespaceSelector"]["matchLabels"]["kubernetes.io/metadata.name"], "axor-egress")

    def test_the_labels_the_manifest_selects_are_the_labels_the_pod_gets(self):
        pod = self.pod("registry")[2]["metadata"]["labels"]
        extra = docs("58-runner-base-ingress.candidate.yaml")
        for pol in extra:
            for r in pol["spec"]["ingress"]:
                for k, v in r["from"][0]["podSelector"]["matchLabels"].items(): self.assertEqual(pod.get(k), v, f"{pol['metadata']['name']} selects {k}={v}")
        reg = [p for p in kind(docs("58-runner.yaml"), "NetworkPolicy", "runner-registry")][0]["spec"]["podSelector"]["matchLabels"]
        for k, v in reg.items(): self.assertEqual(pod.get(k), v)

    def test_the_two_policies_the_base_files_lack_name_the_runner_and_only_it(self):
        pols = {p["metadata"]["name"]: p for p in docs("58-runner-base-ingress.candidate.yaml")}
        self.assertEqual(sorted(pols), ["runner-pull", "runner-result"])
        self.assertEqual((pols["runner-result"]["metadata"]["namespace"], pols["runner-pull"]["metadata"]["namespace"]), ("axor", "axor-egress"))
        for p in pols.values(): self.assertEqual(p["spec"]["policyTypes"], ["Ingress"])


class Manifest(Fixture):
    """A-T5-6 (and A-T5-3, the account and namespace): the namespace's objects, as written, agree with what AXoR asks of them."""
    def test_namespace_names_and_pod_security(self):
        items = docs("58-runner.yaml")
        ns, = kind(items, "Namespace")
        self.assertEqual((ns["metadata"]["name"], V.NS), ("axor-runner", "axor-runner"))
        self.assertEqual(ns["metadata"]["labels"]["pod-security.kubernetes.io/enforce"], "baseline")
        sa, = kind(items, "ServiceAccount", "default"); self.assertIs(sa["automountServiceAccountToken"], False)
        self.assertTrue(all(x["metadata"]["namespace"] == "axor-runner" for x in items if x["kind"] != "Namespace"))

    def test_the_worst_pod_fits_the_limit_range_and_two_of_them_fit_the_quota(self):
        items = docs("58-runner.yaml")
        lr, = kind(items, "LimitRange"); q, = kind(items, "ResourceQuota", "runner")
        job, _ = V.validate(tv.spec(kind="bench", command="x", network="build", memory_mb=10 ** 6, cpus=10 ** 6, timeout_s=10 ** 6), tv.FILES, ["pypi.org"])
        self.assertEqual((job["memory_mb"], job["cpus"]), (V.MAX_MEM, V.MAX_CPUS))
        _, _, pod = self.pod("build", memory_mb=10 ** 6, cpus=10 ** 6)
        lim = pod["spec"]["containers"][0]["resources"]["limits"]
        mx = lr["spec"]["limits"][0]["max"]
        for k in ("cpu", "memory", "ephemeral-storage"): self.assertLessEqual(qty(lim[k]), qty(mx[k]), f"limit range max {k}")
        hard, n = q["spec"]["hard"], V.AT_ONCE
        self.assertLessEqual(n, qty(hard["pods"]))
        self.assertLessEqual(n * qty(lim["cpu"]), qty(hard["limits.cpu"]))
        self.assertLessEqual(n * qty(lim["memory"]), qty(hard["limits.memory"]))
        self.assertLessEqual(n * qty(lim["ephemeral-storage"]), qty(hard["limits.ephemeral-storage"]))
        self.assertLessEqual(n * qty(lim["axor.dev/kvm"]), qty(hard["requests.axor.dev/kvm"]))
        self.assertLessEqual(n * V.INPUT_CHUNKS, qty(hard["configmaps"]))
        for k in ("persistentvolumeclaims", "services", "services.nodeports", "services.loadbalancers"): self.assertEqual(hard[k], "0")

    def test_the_default_limits_a_pod_gets_cover_the_kvm_pod(self):
        lr, = kind(docs("58-runner.yaml"), "LimitRange")
        d = lr["spec"]["limits"][0]
        _, _, pod = self.pod()
        for k in ("cpu", "memory", "ephemeral-storage"): self.assertLessEqual(qty(pod["spec"]["containers"][0]["resources"]["limits"][k]), qty(lr["spec"]["limits"][0]["max"][k]))
        self.assertIn("default", d)

    def test_axors_account_gets_pods_configmaps_logs_and_the_quota_read_and_nothing_else(self):
        items = docs("58-runner.yaml")
        role, = kind(items, "Role", "axor-runner"); rb, = kind(items, "RoleBinding", "axor-runner")
        got = {(g, r, v) for rule in role["rules"] for g in rule["apiGroups"] for r in rule["resources"] for v in rule["verbs"]}
        self.assertEqual({r for _, r, _ in got}, {"pods", "configmaps", "pods/log", "resourcequotas"})
        self.assertEqual({v for _, r, v in got if r == "resourcequotas"}, {"get"})
        self.assertEqual({v for _, r, v in got if r == "pods/log"}, {"get"})
        self.assertTrue({v for _, r, v in got if r in ("pods", "configmaps")} <= {"get", "list", "watch", "create", "delete"})
        self.assertEqual({v for _, r, v in got if r == "pods"} >= {"create", "delete", "list", "get"}, True)
        self.assertEqual(rb["subjects"], [{"kind": "ServiceAccount", "name": "web", "namespace": "axor"}])
        self.assertEqual(rb["roleRef"]["name"], "axor-runner")

    def test_the_names_axor_reads_are_the_names_in_the_manifest(self):
        q, = kind(docs("58-runner.yaml"), "ResourceQuota")
        self.assertEqual(q["metadata"]["name"], "runner")                               # runner.Runner.quota reads .../resourcequotas/runner
        self.assertIn("requests.axor.dev/kvm", q["spec"]["hard"])


class Cleanup(Fixture):
    """A-T5-9: nothing a job made stays behind. AXoR half: every object created is deleted, and the proxy runs are closed."""
    def test_every_pod_and_configmap_created_is_deleted_and_the_proxy_run_closed(self):
        proxy, egress = tv.FakeProxy(), tv.FakeEgress()
        job, _ = V.validate(tv.spec(kind="bench", command="sh bench/run.sh", score_file="bench_out/live.json"), tv.FILES)
        kube = tv.FakeKube(report=lambda pod: tv.vm_report(job), proxy=proxy)
        r = V.Runner(kube, proxy, egress).run({**job, "id": 9}, tv.FILES, label="T-5 contract")
        self.assertEqual(r["status"], "done")
        made = {(k, body["metadata"]["name"]) for k, body in kube.created}
        self.assertTrue(any(k == "pods" for k, _ in made) and any(k == "configmaps" for k, _ in made))
        self.assertEqual(made, {tuple(d) for d in kube.deleted})
        self.assertEqual(len(proxy.closed), 1)


# ---------------------------------------------------------------- cluster tests


def kubectl(*args, check=True):
    """Read-only kubectl against the named kubeconfig only. The ambient environment's KUBECONFIG is not passed."""
    exe = os.getenv("AXOR_T5_KUBECTL", "kubectl")
    env = {k: v for k, v in os.environ.items() if k not in ("KUBECONFIG", "KUBERNETES_MASTER")}
    p = subprocess.run([exe, "--kubeconfig", CLUSTER, "--request-timeout=20s", *args], capture_output=True, text=True, timeout=60, env=env)
    if check and p.returncode: raise AssertionError(f"kubectl {' '.join(args)} failed: {p.stderr.strip()[:300]}")
    return p.stdout


def kjson(*args): return json.loads(kubectl(*args, "-o", "json"))


def cluster_uid(): return kjson("get", "namespace", "kube-system")["metadata"]["uid"]


def need_cluster():
    if not CLUSTER: raise unittest.SkipTest("AXOR_T5_CLUSTER is not set: no authorized staging cluster, T-5 is not tested")
    if not os.path.isfile(CLUSTER): raise AssertionError("AXOR_T5_CLUSTER must be the path of a kubeconfig file for the staging cluster")


def check_evidence(doc, case, uid):
    """What is wrong with a case's evidence file (a list; empty = acceptable). It does not make the evidence: it refuses what could not be a real run."""
    bad = []
    if not isinstance(doc, dict): return ["not a JSON object"]
    for k in EVIDENCE_KEYS:
        if doc.get(k) in (None, "", []): bad.append(f"missing {k}")
    if doc.get("case") != case: bad.append("case id differs")
    if doc.get("status") != "PASS": bad.append(f"status is {doc.get('status')!r}, not PASS")
    if doc.get("stand_in") is not False: bad.append("stand_in must be false: a stand-in is not a cluster")
    if doc.get("cluster_uid") != uid: bad.append("cluster_uid is not this cluster's kube-system uid")
    if not re.fullmatch(r"[0-9a-f]{7,40}", str(doc.get("tree_commit") or "")): bad.append("tree_commit is not a git commit")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(doc.get("runner_image_digest") or "")): bad.append("runner_image_digest is not sha256:<64 hex>")
    if not re.fullmatch(r"[0-9a-f]{64}", str(doc.get("base_disk_sha256") or "")): bad.append("base_disk_sha256 is not 64 hex")
    if not isinstance(doc.get("observations"), list) or not all(isinstance(o, str) and o for o in doc.get("observations") or [None]): bad.append("observations must be non-empty strings")
    return bad


GOOD = {"case": "A-T5-12", "status": "PASS", "cluster_uid": "u-1", "tree_commit": "8d1188a", "runner_image": "axor/runner-vm:t", "runner_image_digest": "sha256:" + "a" * 64,
        "base_disk_sha256": "b" * 64, "started_utc": "2026-11-15T10:00:00Z", "ended_utc": "2026-11-15T10:03:00Z", "stand_in": False, "observations": ["result row stored"]}


class EvidenceChecker(unittest.TestCase):
    """The checker the cluster tests use is itself tested here, offline: it must refuse a stand-in, another cluster, a failed or thin record."""
    def test_a_well_formed_record_passes(self): self.assertEqual(check_evidence(GOOD, "A-T5-12", "u-1"), [])

    def test_each_defect_is_refused(self):
        for patch, why in (({"stand_in": True}, "stand-in"), ({"cluster_uid": "u-2"}, "this cluster"), ({"status": "FAIL"}, "not PASS"), ({"observations": []}, "missing observations"),
                           ({"tree_commit": "not-a-commit"}, "git commit"), ({"base_disk_sha256": "b" * 63}, "64 hex"), ({"runner_image_digest": "axor/runner:tag"}, "sha256"),
                           ({"case": "A-T5-13"}, "case id"), ({"started_utc": ""}, "missing started_utc")):
            self.assertTrue(any(why in b for b in check_evidence({**GOOD, **patch}, "A-T5-12", "u-1")), why)
        self.assertEqual(check_evidence([], "A-T5-12", "u-1"), ["not a JSON object"])


class ClusterObjects(unittest.TestCase):
    """A-T5-7 (objects exist as the contract says), A-T5-8 (identity), A-T5-10 (node and image), A-T5-11 (policies). Read-only."""
    @classmethod
    def setUpClass(cls): need_cluster()

    def test_a_t5_7_namespace_quota_limitrange_and_default_account(self):
        ns = kjson("get", "namespace", "axor-runner")
        self.assertEqual(ns["metadata"]["labels"].get("pod-security.kubernetes.io/enforce"), "baseline")
        q = kjson("-n", "axor-runner", "get", "resourcequota", "runner"); self.assertEqual(q["spec"]["hard"].get("requests.axor.dev/kvm"), "2")
        kjson("-n", "axor-runner", "get", "limitrange", "runner")
        self.assertIs(kjson("-n", "axor-runner", "get", "serviceaccount", "default").get("automountServiceAccountToken"), False)
        self.assertEqual(kjson("-n", "axor-runner", "get", "pods")["items"], [], "the namespace must be empty when idle")

    def test_a_t5_8_axors_account_can_do_what_the_contract_lists_and_nothing_more(self):
        who = ["--as=system:serviceaccount:axor:web", "-n", "axor-runner"]
        for verb, res in (("create", "pods"), ("delete", "pods"), ("create", "configmaps"), ("delete", "configmaps"), ("get", "pods/log"), ("get", "resourcequotas")):
            self.assertEqual(kubectl("auth", "can-i", verb, res, *who, check=False).strip(), "yes", f"{verb} {res}")
        for verb, res in (("create", "secrets"), ("create", "deployments"), ("patch", "pods"), ("create", "pods/exec"), ("create", "rolebindings"), ("delete", "networkpolicies")):
            self.assertEqual(kubectl("auth", "can-i", verb, res, *who, check=False).strip(), "no", f"{verb} {res}")
        self.assertEqual(kubectl("auth", "can-i", "create", "pods", "--as=system:serviceaccount:axor:web", "-n", "axor", check=False).strip() in ("yes", "no"), True)
        self.assertEqual(kubectl("auth", "can-i", "create", "pods", "--as=system:serviceaccount:axor-runner:default", "-n", "axor-runner", check=False).strip(), "no")

    def test_a_t5_10_a_node_offers_kvm_and_the_runner_image_is_there_by_digest(self):
        nodes = kjson("get", "nodes")["items"]
        self.assertTrue(any(int(n["status"]["allocatable"].get("axor.dev/kvm", "0")) >= 2 for n in nodes), "no node offers 2 axor.dev/kvm")
        want = os.getenv("AXOR_T5_RUNNER_IMAGE_DIGEST", "")
        self.assertRegex(want, r"^sha256:[0-9a-f]{64}$", "set AXOR_T5_RUNNER_IMAGE_DIGEST to the digest of the runner image the web deployment is set to")
        have = {i for n in nodes for im in n["status"].get("images", []) for i in im.get("names", [])}
        self.assertTrue(any(want in h for h in have), "the runner image is not on a node")
        web = kjson("-n", "axor", "get", "deployment", "web")["spec"]["template"]["spec"]["containers"][0]["env"]
        env = {e["name"]: e.get("value", "") for e in web}
        self.assertTrue(env.get("RUNNER_IMAGE"), "RUNNER_IMAGE is not set on the web deployment"); self.assertRegex(env.get("RUNNER_BASE_SHA256", ""), r"^[0-9a-f]{64}$")

    def test_a_t5_11_policies_admit_the_runner_and_default_deny_holds(self):
        axor = {p["metadata"]["name"] for p in kjson("-n", "axor", "get", "networkpolicy")["items"]}
        egress = {p["metadata"]["name"] for p in kjson("-n", "axor-egress", "get", "networkpolicy")["items"]}
        mine = {p["metadata"]["name"]: p for p in kjson("-n", "axor-runner", "get", "networkpolicy")["items"]}
        self.assertIn("runner-result", axor); self.assertIn("runner-pull", egress)
        base = mine["runner"]["spec"]
        self.assertEqual((base["podSelector"], base["ingress"] if "ingress" in base else []), ({}, []))
        self.assertIn("runner-registry", mine)


class ClusterBehaviour(unittest.TestCase):
    """A-T5-12 .. A-T5-14: a case counts only with a well formed PASS record made on this cluster (see the module docstring)."""
    @classmethod
    def setUpClass(cls):
        need_cluster()
        if not EVIDENCE or not os.path.isdir(EVIDENCE): raise AssertionError("AXOR_T5_EVIDENCE must name the folder with case-<id>.json records")
        cls.uid = cluster_uid()

    def case(self, cid):
        f = Path(EVIDENCE) / f"case-{cid}.json"
        self.assertTrue(f.is_file(), f"{f} is missing: {DYNAMIC_CASES[cid]} was not run")
        self.assertEqual(check_evidence(json.loads(f.read_text()), cid, self.uid), [])

    def test_a_t5_12_result_delivered_across_namespaces(self): self.case("A-T5-12")
    def test_a_t5_13_deadline_cancel_and_cleanup(self): self.case("A-T5-13")
    def test_a_t5_14_egress_dns_and_process_limit(self): self.case("A-T5-14")


if __name__ == "__main__":
    unittest.main()
