"""G5-2 M2: planner schema v2 "needs" (Owner D-015 D3, clarification E) and capability probes that check real usability
(clarifications B and C).

v2 planners declare needs for every task ("[]" = nothing special); v1 outputs (no "needs") stay valid and leave the task
undeclared. A probe answers PASS only on a live answer or a recent successful use; configuration alone is UNKNOWN, and UNKNOWN
is never PASS."""
import json, os, sys, tempfile, time, types, unittest
from unittest import mock

from app import llm, mining_work, mission_ops as mo, task_lifecycle as tl
from app.auth import AuthDB

sys.path.insert(0, os.path.dirname(__file__))
from test_mission_ref import ME, WID, Base as BoardBase  # noqa: E402


class PlannerSchema(unittest.TestCase):
    def test_v2_declares_needs_and_v1_stays_valid(self):
        self.assertEqual(tl.planner_needs({"title": "x", "needs": ["docker", "RAM:8"]}), ('["docker", "ram:8"]', 2))
        self.assertEqual(tl.planner_needs({"title": "x", "needs": []}), ("[]", 2))          # declared: nothing special
        self.assertEqual(tl.planner_needs({"title": "x"}), (None, 1))                       # a version-1 output
        self.assertEqual(tl.planner_needs({"title": "x", "needs": ["docker", "warp-drive"]}), ('["docker"]', 2))  # unknown ones dropped
        self.assertTrue(tl.declared({"needs": "[]"}))
        self.assertFalse(tl.declared({"needs": None}))

    def test_new_planner_outputs_must_declare_needs(self):
        self.assertIn("needs", mining_work.PLAN["properties"]["tasks"]["items"]["required"])
        self.assertIn("needs", mining_work.SUBMIT_WORK["input_schema"]["properties"]["followups"]["items"]["required"])
        from app import control_missions
        self.assertIn("needs", control_missions.INTEL["properties"]["proposals"]["items"]["required"])
        self.assertIn("AXoR checks each", mining_work.PLAN_SYSTEM)


class PlannerOnTheBoard(BoardBase):
    def setUp(self):
        super().setUp()
        self.db.q("ALTER TABLE mw_tasks ADD COLUMN needs TEXT")

    def stored(self):
        return {r["title"]: r["needs"] for r in self.db.q("SELECT title, needs FROM mw_tasks ORDER BY id")}

    def test_a_v2_plan_stores_declared_needs_even_empty(self):
        self.w.plan_out = {"summary": "Plan", "tasks": [
            {"title": "Run the live bench", "detail": "", "assignee": "Devon", "priority": "high", "needs": ["docker", "credential:BEX_CHALLENGE_API_KEY"]},
            {"title": "Read the scoring rules", "detail": "", "assignee": "Devon", "priority": "low", "needs": []}]}
        self.w.plan(ME, WID, mining_work.PlanIn(note="", start=False))
        s = self.stored()
        self.assertEqual(json.loads(s["Run the live bench"]), ["docker", "credential:BEX_CHALLENGE_API_KEY"])
        self.assertEqual(s["Read the scoring rules"], "[]")

    def test_a_v1_plan_still_works_and_leaves_needs_undeclared(self):
        self.plan(["Start the challenge container"])  # the fixture's plan has no "needs": an older planner
        t = self.db.q("SELECT * FROM mw_tasks WHERE title='Start the challenge container'", one=True)
        self.assertIsNone(t["needs"])
        self.assertEqual([(n["cap"], n["source"]) for n in tl.needs_of(t)], [("docker", "inferred")])  # a confirmation item later, not a block


class FakeEgress:
    def __init__(self, ready): self.ready = ready
    def status(self, fresh=False): return {"ready": self.ready, "why": "" if self.ready else "The egress proxy doesn't answer", "gvisor": True}


class FakeKube:
    enabled = True
    def __init__(self, kvm="0", gpus=0, quota_error=None, nodes_error=None): self.kvm, self.gpus, self.err, self.nerr = kvm, gpus, quota_error, nodes_error
    def get(self, path):
        if self.err: raise RuntimeError(self.err)
        return {"spec": {"hard": {"requests.axor.dev/kvm": self.kvm}}}
    def items(self, path): return [] if self.nerr else self.call("GET", path)["items"]  # as Kube.items: [] when refused
    def call(self, method, path, params=None):
        if self.nerr: raise RuntimeError(self.nerr)
        return {"items": [{"status": {"allocatable": {"cpu": "32", **({"nvidia.com/gpu": str(self.gpus)} if self.gpus else {})}}}]}


class Probes(unittest.TestCase):
    def setUp(self):
        mo._probe_cache.clear()
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        self.db.q("""CREATE TABLE mw_sbx (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, services TEXT, status TEXT, finished REAL)""")
        self.sbx = types.SimpleNamespace(kube=FakeKube(), egress=FakeEgress(True), ready=lambda: (True, ""))
        self.agents = [{"id": 1, "active": 1, "model": "terminal:sonnet"}]
        w = types.SimpleNamespace(sbx=self.sbx, m=types.SimpleNamespace(_campaign=lambda cid: {"user_id": 7}),
                                  _agents=lambda wid: self.agents, _model=lambda c, a: a["model"])
        self.ch = types.SimpleNamespace(db=self.db, w=w, _has=lambda t: True)
        self.comp = {"id": 3, "campaign_id": 1, "internet": 1}

    def tearDown(self): self.dir.cleanup()

    def state(self, cap, value=None, comp="default"):
        return mo.probe(self.ch, self.comp if comp == "default" else comp, cap, value, fresh=True)["state"]

    def test_docker_and_registry_fail_until_the_runner_exists(self):
        self.assertEqual((self.state("docker"), self.state("registry")), ("FAIL", "FAIL"))

    def test_vm_reads_the_real_quota_and_is_never_pass_without_a_vm_run(self):
        self.assertEqual(self.state("vm"), "FAIL")                                 # quota 0, as on this cluster
        self.sbx.kube = FakeKube(kvm="2"); self.assertEqual(self.state("vm"), "UNKNOWN")
        self.sbx.kube = FakeKube(quota_error="403 forbidden"); self.assertEqual(self.state("vm"), "UNKNOWN")

    def test_internet_needs_the_team_switch_and_a_live_proxy(self):
        # 2026-11-13: a proxy that answers AXoR's server is no longer PASS by itself; the proof is a run inside the sandbox that
        # reached a host (tests/unit/test_mission_exec_access.py). Here there is none, and no board to start a check run on.
        self.assertEqual(self.state("internet"), "UNKNOWN")
        self.sbx.egress = FakeEgress(False); self.assertEqual(self.state("internet"), "FAIL")
        self.assertEqual(self.state("internet", comp={"id": 4, "internet": 0}), "FAIL")

    def test_a_service_passes_only_on_a_recent_successful_use(self):
        self.assertEqual(self.state("postgres"), "UNKNOWN")                        # configured and up, never used: not proven
        self.db.q("INSERT INTO mw_sbx (comp_id, services, status, finished) VALUES (3, '[\"postgres\"]', 'done', ?)", (time.time(),))
        self.assertEqual(self.state("postgres"), "PASS")
        self.sbx.ready = lambda: (False, "The sandbox is switched off on this server (SANDBOX=0).")
        self.assertEqual(self.state("postgres"), "FAIL")

    def test_gpu_ram_credential_approval(self):
        self.assertEqual(self.state("gpu"), "FAIL")
        self.sbx.kube = FakeKube(gpus=2); self.assertEqual(self.state("gpu"), "UNKNOWN")
        self.assertEqual((self.state("ram", "4"), self.state("ram", "16")), ("PASS", "FAIL"))
        self.assertEqual(self.state("credential", "BEX_CHALLENGE_API_KEY"), "UNKNOWN")  # B: presence isn't proof
        self.assertEqual(self.state("approval"), "UNKNOWN")

    def test_sign_in_is_a_real_prompt(self):
        with mock.patch.object(llm, "cli_check", side_effect=llm.LLMError("Claude Code on the server isn't signed in.")):
            p = mo.probe(self.ch, self.comp, "auth", fresh=True)
        self.assertEqual(p["state"], "FAIL"); self.assertIn("isn't signed in", p["evidence"])
        with mock.patch.object(llm, "cli_check", return_value=None):
            self.assertEqual(self.state("auth"), "PASS")
        with mock.patch.object(llm, "cli_check", side_effect=llm.QuotaError("plan rate limit reached")):
            self.assertEqual(self.state("auth"), "PASS")                           # signed in; the limit is the quota class's business
        self.agents[0]["model"] = "openrouter:anthropic/claude"
        self.assertEqual(self.state("auth"), "UNKNOWN")                            # API keys: nothing to sign in

    def test_a_refused_node_read_is_unknown_never_absent(self):  # found in G5-2 staging with the least-privilege account
        self.sbx.kube = FakeKube(nodes_error="403 forbidden: nodes")
        self.assertEqual(self.state("gpu"), "UNKNOWN")                             # not "No node offers a GPU"
        self.sbx.egress = types.SimpleNamespace(status=lambda fresh=False: {"ready": False, "gvisor": False,
                                                "why": "gVisor isn't installed on the server yet, and runs with internet only start under it"})
        p = mo.probe(self.ch, self.comp, "internet", fresh=True)
        self.assertEqual(p["state"], "UNKNOWN"); self.assertIn("can't be confirmed", p["evidence"])
        self.sbx.kube = FakeKube()                                                 # nodes readable, and really no gVisor label
        self.assertEqual(self.state("internet"), "FAIL")

    def test_answers_are_cached_and_a_broken_probe_is_unknown(self):
        a = mo.probe(self.ch, self.comp, "docker")
        self.assertIs(mo.probe(self.ch, self.comp, "docker"), a)
        self.sbx.kube = types.SimpleNamespace(enabled=True, get=None)            # get() isn't callable: the probe breaks
        self.assertEqual(self.state("vm"), "UNKNOWN")
        self.assertEqual(mo.probe(self.ch, self.comp, "teleporter", fresh=True)["state"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
