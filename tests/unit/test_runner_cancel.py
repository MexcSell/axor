"""The VM runner and a job that is cancelled before it starts (runner.Runner.run): a job cancelled while it waits for a VM, or
found cancelled when its turn comes, is never started. No proxy run, no ConfigMap and no pod is made for it, its slot is given
back, and its result is "cancelled", which is never evidence. A job that isn't cancelled runs as before."""
import os, sys, unittest

sys.path.insert(0, os.path.dirname(__file__))
import test_vm_runner as tv  # noqa: E402  (as a module, so its own tests don't run again here)
from app import runner as V  # noqa: E402


@tv.own_tests
class Cancelled(tv.Running):
    def setUp(self):
        super().setUp()
        self._step = V.SLOT_STEP; V.SLOT_STEP = 0.01
        self.proxy, self.egress = tv.FakeProxy(), tv.FakeEgress()
        self.kube = tv.FakeKube(report=lambda pod: tv.vm_report(self.job), proxy=self.proxy)
        self.r = V.Runner(self.kube, self.proxy, self.egress)

    def tearDown(self): V.SLOT_STEP = self._step; super().tearDown()

    def run_job(self, cancelled): return self.r.run({**self.job, "id": 9}, tv.FILES, cancelled=cancelled)
    def nothing_made(self): return (self.kube.created, self.kube.deleted, self.egress.calls, self.proxy.hooks, self.proxy.closed) == ([], [], [], {}, [])
    def free_slots(self):
        n = 0
        while self.r.slots.acquire(blocking=False): n += 1
        for _ in range(n): self.r.slots.release()
        return n

    def test_a_job_found_cancelled_when_its_turn_comes_is_never_started(self):
        out = self.run_job(lambda: True)
        self.assertEqual((out["status"], out["exit"]), ("cancelled", None)); self.assertIn("nothing was created", out["error"])
        self.assertTrue(self.nothing_made()); self.assertEqual(self.free_slots(), V.AT_ONCE)  # its slot is given back
        self.assertIsNone(out.get("score")); self.assertFalse(out.get("artifacts"))  # a cancelled job carries no score: runner.stored takes a done job only

    def test_a_job_cancelled_while_it_waits_for_a_vm_is_never_started(self):
        for _ in range(V.AT_ONCE): self.r.slots.acquire()  # every VM is busy
        asked = []
        def cancelled(): asked.append(1); return len(asked) >= 3  # the stop arrives while it waits
        out = self.run_job(cancelled)
        self.assertEqual(out["status"], "cancelled"); self.assertGreaterEqual(len(asked), 3)
        self.assertTrue(self.nothing_made()); self.assertEqual(self.free_slots(), 0)  # it never held a slot, so it gives none back
        for _ in range(V.AT_ONCE): self.r.slots.release()

    def test_a_waiting_job_that_is_not_cancelled_starts_when_a_vm_is_free(self):
        for _ in range(V.AT_ONCE): self.r.slots.acquire()
        asked = []
        def cancelled():
            asked.append(1)
            if len(asked) == 3: self.r.slots.release()  # a VM frees up
            return False
        out = self.run_job(cancelled)
        self.assertEqual(out["status"], "done"); self.assertEqual(out["score"]["score"], 0.81)
        self.assertEqual([k for k, _ in self.kube.created].count("pods"), 1)  # the control: the same wait, no stop, one pod
        self.assertEqual(self.free_slots(), 1)
        for _ in range(V.AT_ONCE - 1): self.r.slots.release()


if __name__ == "__main__":
    unittest.main()
