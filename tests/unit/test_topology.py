"""topology.py: the Unified control panel's graph: one identity per entity across the projections, dependency directions for
impact analysis, the infrastructure layer's admin gate, and one failing source leaving the other projections standing."""
import json, os, tempfile, time, unittest

from app import agent_core, topology
from app.auth import AuthDB

NOW = time.time()


class FakeControl:
    """control_hub.tree for one organization with one Competition team (comp 1) and two agents."""
    def tree(self, me):
        team = {"id": "u:5", "kind": "competition", "name": "SN62 · Ridges", "status": "busy", "comp_id": 1, "subnet": 62, "open_tasks": 1,
                "agents": [{"key": "teams:1", "name": "Ada", "title": "Engineer", "system": "teams", "status": "busy"},
                           {"key": "teams:2", "name": "Gus", "title": "Director", "system": "teams", "status": "ok"}]}
        return {"org": {"name": "Co", "owner": "you", "ceo": None, "pending": 0, "counts": {"agents": 2, "working": 1}},
                "bittensor": {"id": "bittensor", "unit_id": 4, "name": "Bittensor", "departments": [
                    {"id": "sn:62", "netuid": 62, "name": "SN62", "status": "busy", "teams": [team]}], "teams": [], "staff": []},
                "departments": [], "unplaced": []}


class K:
    enabled = True


class FakeCluster:
    k = K()
    broken = False

    def overview(self):
        if self.broken: raise RuntimeError("API down")
        pod = lambda ns, name, dep, problem=None: {"name": name, "namespace": ns, "phase": "Running", "deleting": False, "ready": 1, "containers": ["main"],
                                                   "restarts": 0, "node": "host1", "ip": "10.42.0.9", "created": NOW - 60, "deployment": dep,
                                                   "problem": problem, "cpu": .1, "memory": 1e8}
        dep = lambda name: {"name": name, "namespace": "axor", "replicas": 1, "ready": 1, "updated": 1, "available": 1, "rolling": False, "failed": False,
                            "message": None, "images": ["x"], "strategy": "Recreate", "created": NOW - 600, "restarted": None, "labels": {}}
        return {"nodes": [{"name": "host1", "ready": True, "pressure": [], "roles": ["control-plane"], "version": "v1", "cpu": 8, "memory": 1e10,
                           "cpu_used": 1, "memory_used": 1e9}],
                "namespaces": [{"name": "axor", "title": "AXoR", "deployments": [dep("web")], "pods": [pod("axor", "web-1", "web", "CrashLoopBackOff")]}],
                "events": [{"type": "Warning", "reason": "BackOff", "message": "restarting", "kind": "Pod", "name": "web-1", "namespace": "axor", "count": 3, "time": NOW}]}


class Graph(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        db = self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        agent_core.init(db)
        q = db.q
        q("CREATE TABLE mw_runs (id INTEGER PRIMARY KEY, comp_id INTEGER, task_id INTEGER, agent_id INTEGER)")
        q("CREATE TABLE mw_spans (id INTEGER PRIMARY KEY, run_id INTEGER, ts REAL, end REAL, kind TEXT, name TEXT, input TEXT, output TEXT, tokens INTEGER, error INTEGER)")
        q("""CREATE TABLE mw_sbx (id INTEGER PRIMARY KEY, comp_id INTEGER, task_id INTEGER, run_id INTEGER, agent_id INTEGER, command TEXT, status TEXT,
             exit_code INTEGER, error TEXT, started REAL, finished REAL, cost REAL, calls INTEGER, pod TEXT, net TEXT)""")
        q("INSERT INTO mw_runs (id, comp_id, task_id, agent_id) VALUES (9, 1, NULL, 1)")
        q("""INSERT INTO ac_runs (system, owner_id, agent_key, kind, ref, title, status, tokens, model, started, finished)
             VALUES ('teams', 1, 'teams:1', 'task', 'mw:9', 'Fix it', 'failed', 100, 'anthropic:claude-x', ?, ?)""", (NOW - 300, NOW - 200))
        self.run_id = q("SELECT id FROM ac_runs", one=True)["id"]
        for i, (kind, name) in enumerate((("model", "claude-x"), ("tool", "read_file"), ("tool", "ext_exa__search"))):
            q("INSERT INTO mw_spans (run_id, ts, end, kind, name, input, output, tokens, error) VALUES (9,?,?,?,?,'in','out',0,0)", (NOW - 290 + i, NOW - 289 + i, kind, name))
        net = {"up_bytes": 10, "down_bytes": 2000, "connections": 2, "hosts": {"pypi.org": {"conns": 2, "up": 10, "down": 2000}},
               "refused": [{"host": "10.0.0.5", "why": "an internal address", "at": NOW - 250}]}
        q("""INSERT INTO mw_sbx (id, comp_id, run_id, agent_id, command, status, exit_code, started, finished, pod, net)
             VALUES (3, 1, 9, 1, 'pytest', 'error', 1, ?, ?, 'sbx-3', ?)""", (NOW - 260, NOW - 210, json.dumps(net)))
        self.cluster = FakeCluster()
        self.t = topology.Topology(db, FakeControl(), self.cluster)

    def tearDown(self):
        agent_core._core = None
        self.dir.cleanup()

    def graph(self, role="admin", deep=False):
        g = topology.Topology(self.db, FakeControl(), self.cluster).graph({"id": 1, "role": role, "username": "u"}, 24, deep)
        return g, {n["id"]: n for n in g["nodes"]}, g["edges"]

    @staticmethod
    def impact(edges, x):
        """What depends on x: the page's dependency analysis (topology.js impactOf), over the edges' dep."""
        seen, front = {x}, [x]
        while front:
            nxt = []
            for c in front:
                for e in edges:
                    o = e["source"] if e["dep"] == "fwd" and e["target"] == c else e["target"] if e["dep"] == "rev" and e["source"] == c else None
                    if o and o not in seen: seen.add(o); nxt.append(o)
            front = nxt
        return seen - {x}

    def test_a_sandbox_is_one_node_in_execution_infrastructure_and_network(self):
        g, N, E = self.graph()
        sbx = N["sbx:3"]
        self.assertEqual(set(sbx["layers"]), {"exec", "infra", "net", "obs"})  # obs: it failed
        self.assertEqual(sbx["status"], "fail")
        kinds = {(e["source"], e["target"]): e["kind"] for e in E}
        self.assertEqual(kinds[(f"run:{self.run_id}", "sbx:3")], "sandboxed")
        self.assertEqual(kinds[("k8s:ns:axor-sandbox", "sbx:3")], "contains")
        self.assertEqual(kinds[("sbx:3", "host:pypi.org")], "reached")
        self.assertEqual(kinds[("sbx:3", "host:10.0.0.5")], "blocked")
        self.assertEqual(N["host:10.0.0.5"]["status"], "fail")
        self.assertGreater(g["stats"]["shared"], 0)
        self.assertFalse([e for e in E if e["source"] not in N or e["target"] not in N])  # no edge points nowhere

    def test_impact_follows_dependencies_not_containment_upwards(self):
        _, N, E = self.graph()
        self.assertIn("agent:teams:1", N)
        # the failed sandbox takes its run down; its namespace and the cluster don't depend on it
        self.assertIn(f"run:{self.run_id}", self.impact(E, "sbx:3"))
        self.assertNotIn("k8s:ns:axor-sandbox", self.impact(E, "sbx:3"))
        # a node failing reaches the pods on it, their deployment, and the organization that runs on AXoR's web deployment
        down = self.impact(E, "k8s:node:host1")
        self.assertTrue({"k8s:pod:axor/web-1", "k8s:dep:axor/web", "org"} <= down, down)
        # a team depends on its agents
        self.assertIn("u:5", self.impact(E, "agent:teams:2"))

    def test_tool_calls_are_aggregated_and_only_listed_one_by_one_at_the_deep_level(self):
        _, N, E = self.graph()
        self.assertIn("tool:read_file", N)
        self.assertEqual(N["tool:ext_exa__search"]["label"], "search")
        self.assertFalse([n for n in N if n.startswith("span:")])
        _, N2, _ = self.graph(deep=True)
        self.assertEqual(len([n for n in N2 if n.startswith("span:")]), 3)

    def test_members_see_their_sandboxes_but_not_the_cluster(self):
        g, N, _ = self.graph(role="member")
        infra = next(l for l in g["layers"] if l["key"] == "infra")
        self.assertFalse(infra["ok"])
        self.assertIn("administrators", infra["why"])
        self.assertFalse([n for n in N if n.startswith(("k8s:node:", "k8s:pod:", "k8s:dep:"))])
        self.assertIn("infra", N["sbx:3"]["layers"])

    def test_a_failing_source_leaves_the_other_projections_standing(self):
        self.cluster.broken = True
        g, N, _ = self.graph()
        infra = next(l for l in g["layers"] if l["key"] == "infra")
        self.assertFalse(infra["ok"])
        self.assertIn("API down", infra["why"])
        self.assertIn("sbx:3", N)
        self.assertIn("agent:teams:1", N)
        self.assertTrue(next(l for l in g["layers"] if l["key"] == "org")["ok"])

    def test_kubernetes_warnings_hang_on_the_pod_they_are_about(self):
        _, N, E = self.graph()
        self.assertTrue([e for e in E if e["kind"] == "about" and e["target"] == "k8s:pod:axor/web-1"])
        self.assertIn("obs", N["k8s:pod:axor/web-1"]["layers"])


if __name__ == "__main__":
    unittest.main()
