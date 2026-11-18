"""agent_core.register_resolver keeps one resolver per function (PX-R13).

On Postgres every test's Orchestrator registered its bound resolve() in agent_core's module-level list and stayed there, with its
database connection, until the server ran out of connections. A system built again now replaces its own resolver: the list never
keeps an earlier instance alive, and runs never ask a system that was replaced."""
import gc
import sys
import unittest
import weakref
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app import agent_core  # noqa: E402


class System:
    def __init__(self, corr): self.corr = corr
    def resolve(self, system, ref): return {"corr": self.corr}


class Other:
    def resolve(self, system, ref): return {"team": "t-other"}


class ResolverRegistry(unittest.TestCase):
    def setUp(self):
        self.saved = list(agent_core._resolvers)
        agent_core._resolvers.clear()

    def tearDown(self):
        agent_core._resolvers[:] = self.saved

    def test_a_system_built_again_replaces_its_resolver_and_the_old_one_is_freed(self):
        a = System("mx:1"); gone = weakref.ref(a)
        agent_core.register_resolver(a.resolve)
        b = System("mx:2")
        agent_core.register_resolver(b.resolve)
        self.assertEqual(len(agent_core._resolvers), 1)
        self.assertEqual(agent_core._resolve("wfm", "wfm:1")["corr"], "mx:2")  # the newest system answers, never the replaced one
        del a; gc.collect()
        self.assertIsNone(gone(), "the registry still holds the replaced system (and would hold its database connection)")

    def test_the_same_system_registered_twice_is_there_once(self):
        a = System("mx:1")
        agent_core.register_resolver(a.resolve); agent_core.register_resolver(a.resolve)
        self.assertEqual(len(agent_core._resolvers), 1)

    def test_resolvers_of_different_functions_all_answer_in_their_order(self):
        a, o = System("mx:1"), Other()
        agent_core.register_resolver(a.resolve); agent_core.register_resolver(o.resolve)
        agent_core.register_resolver(System("mx:3").resolve)  # replaced in its place: still first
        self.assertEqual([getattr(f, "__self__").__class__.__name__ for f in agent_core._resolvers], ["System", "Other"])
        self.assertEqual(agent_core._resolve("wfm", "wfm:1"), {"corr": "mx:3", "team": "t-other", "contract": None})

    def test_negative_control_the_old_append_keeps_every_instance(self):
        """The old rule (append unless equal): bound methods of two instances aren't equal, so both stay and the first is never freed.
        Shows the first test checks something the old code fails."""
        def old_register(fn):
            if fn not in agent_core._resolvers: agent_core._resolvers.append(fn)
        a = System("mx:1"); gone = weakref.ref(a)
        old_register(a.resolve); old_register(System("mx:2").resolve)
        del a; gc.collect()
        self.assertEqual(len(agent_core._resolvers), 2)
        self.assertIsNotNone(gone())


if __name__ == "__main__":
    unittest.main()
