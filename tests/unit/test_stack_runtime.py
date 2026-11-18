"""5.1 stack: LangGraph agent reasoning (agent_graph.py) and Temporal mission runtime (mission_temporal.py).

Both are optional in the image and off by default; these tests skip what isn't installed. The live Temporal test needs a server:
TEMPORAL_TEST_ADDRESS=host:7233 (e.g. `temporal server start-dev`, see k8s/stack/README.md)."""
import os, threading, time, unittest
from unittest import mock

from app import agent_graph, mission_temporal


class Off(unittest.TestCase):
    def test_off_by_default(self):
        self.assertFalse(mission_temporal.ENABLED)
        self.assertIsNone(mission_temporal.start(lambda mid: None))
        self.assertFalse(agent_graph.ENABLED)
        self.assertFalse(mission_temporal.status(None)["ready"])

    def test_missions_submit_prefers_temporal_and_falls_back(self):
        from app import missions
        m = missions.Missions.__new__(missions.Missions)
        m.lock, m.busy = threading.Lock(), set()
        m.pool = mock.Mock()
        m.temporal = mock.Mock()
        m.temporal.submit.return_value = True
        m._submit(4)
        m.temporal.submit.assert_called_once_with(4)
        m.pool.submit.assert_not_called()
        m.temporal.submit.return_value = False  # Temporal down: the in-process pool takes it
        m._submit(5)
        m.pool.submit.assert_called_once()
        m.temporal = None
        m._submit(6)
        self.assertEqual(m.pool.submit.call_count, 2)


class Stop(Exception):
    def __init__(self, why): super().__init__(why); self.why = why


@unittest.skipUnless(agent_graph.installed(), "langgraph isn't installed in this image")
class Graph(unittest.TestCase):
    def test_review_loop_until_it_meets(self):
        reviews = iter([{"meets": False, "gaps": ["no sources"]}, {"meets": True, "gaps": []}])
        g = agent_graph.build(lambda st: {"deliverable": "v1"}, lambda st: next(reviews),
                              lambda st: {"deliverable": "v2 with " + st["gaps"][0]})
        out = g.invoke({"rounds": 0})
        self.assertEqual(out["out"]["deliverable"], "v2 with no sources")
        self.assertEqual(out["rounds"], 1)
        self.assertTrue(out["meets"])
        self.assertEqual(len(out["reviews"]), 2)

    def test_round_cap_and_budget_stop(self):
        g = agent_graph.build(lambda st: {"deliverable": "v1"}, lambda st: {"meets": False, "gaps": ["x"]},
                              lambda st: {"deliverable": f"v{st['rounds'] + 2}"}, max_rounds=2)
        out = g.invoke({"rounds": 0})
        self.assertEqual((out["rounds"], out["out"]["deliverable"], out["meets"]), (2, "v3", False))
        def broke(st): raise Stop("The budget can't cover the review")
        out = agent_graph.build(lambda st: {"deliverable": "v1"}, broke, lambda st: {}, stop=(Stop,)).invoke({"rounds": 0})
        self.assertEqual(out["out"]["deliverable"], "v1")
        self.assertIn("budget", out["stopped"])

    def test_direct_engine_on_the_graph(self):
        from app import missions
        calls = []
        def ask(m, stage, schema, name, prompt, tokens=0, effort=""):
            calls.append(name)
            if name == "review": return ({"meets": len(calls) > 2, "gaps": [] if len(calls) > 2 else ["missing table"]}, "fake-model")
            return ({"deliverable": f"{name} text", "summary": "s", "limits": []}, "fake-model")
        ms = mock.Mock()
        ms._ask.side_effect = ask
        m = {"id": 9, "understanding": {"criteria": ["has a table"]}}
        out, model = agent_graph.direct(ms, m, "Write it", missions.DIRECT, 1000)
        self.assertEqual(calls, ["deliverable", "review", "revision", "review"])
        self.assertEqual((out["deliverable"], model, out["graph"]["rounds"], out["graph"]["meets"]), ("revision text", "fake-model", 1, True))
        ms._event.assert_called_once()


@unittest.skipUnless(mission_temporal.installed() and os.getenv("TEMPORAL_TEST_ADDRESS"), "needs temporalio and TEMPORAL_TEST_ADDRESS")
class TemporalLive(unittest.TestCase):
    def test_submit_runs_advance_as_a_workflow(self):
        ran = []
        done = threading.Event()
        def advance(mid):
            ran.append(mid); done.set()
        with mock.patch.multiple(mission_temporal, ENABLED=True, ADDRESS=os.environ["TEMPORAL_TEST_ADDRESS"], QUEUE=f"axor-test-{time.time_ns()}"):
            rt = mission_temporal.start(advance)
            self.assertTrue(rt.ready, rt.error)
            mid = time.time_ns() % 10 ** 9  # workflow ids outlive a test run on the server: a fresh mission id each run
            self.assertTrue(rt.submit(mid))
            self.assertTrue(rt.submit(mid))  # already running (or just finished and restarted): never an error
            self.assertTrue(done.wait(30))
            self.assertEqual(ran[0], mid)
            rt.close()
            self.assertEqual(rt.status()["submitted"], 2)

    def test_unreachable_server_falls_back(self):
        with mock.patch.multiple(mission_temporal, ENABLED=True, ADDRESS="127.0.0.1:1", CONNECT_TIMEOUT=2):
            rt = mission_temporal.start(lambda mid: None)
            self.assertFalse(rt.ready)
            self.assertFalse(rt.submit(1))
            self.assertEqual(rt.status()["fallbacks"], 1)


if __name__ == "__main__":
    unittest.main()
