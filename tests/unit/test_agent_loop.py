"""agents.run_loop (the tool loop most agents share) and busy.py (what a deploy waits for)."""
import threading, unittest

from app import agents, busy


def script(*turns):
    """A fake model: each turn is (blocks, stop). Records how busy the process looked during each call."""
    seen, it = [], iter(turns)
    def complete(system, tools, messages):
        seen.append(busy.count())
        blocks, stop = next(it)
        return blocks, stop, 7
    return complete, seen


def tool(name, i="t1", **inp): return {"type": "tool_use", "id": i, "name": name, "input": inp}
def text(t): return {"type": "text", "text": t}


class Loop(unittest.TestCase):
    def test_tool_call_then_answer(self):
        complete, _ = script(([tool("lookup", q="sn1")], "tool_use"), ([text("done")], "end_turn"))
        msgs, used = [{"role": "user", "content": "hi"}], []
        agents.run_loop(complete, "sys", [], msgs, lambda n, a: {"got": a["q"]}, on_usage=used.append, model="m")
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant", "user", "assistant"])
        self.assertEqual(msgs[2]["content"][0]["content"], '{"got": "sn1"}')
        self.assertFalse(msgs[2]["content"][0]["is_error"])
        self.assertEqual(msgs[-1]["meta"], {"model": "m"})
        self.assertEqual(used, [7, 7])

    def test_tool_errors_go_back_to_the_model(self):
        def boom(n, a): raise LookupError("no such subnet")
        complete, _ = script(([tool("lookup")], "tool_use"), ([text("sorry")], "end_turn"))
        msgs = [{"role": "user", "content": "hi"}]
        agents.run_loop(complete, "sys", [], msgs, boom)
        self.assertTrue(msgs[2]["content"][0]["is_error"])
        self.assertIn("no such subnet", msgs[2]["content"][0]["content"])

    def test_refusal_closes_the_turn(self):
        complete, _ = script(([], "refusal"))
        msgs = [{"role": "user", "content": "hi"}]
        agents.run_loop(complete, "sys", [], msgs, lambda n, a: None)
        self.assertEqual(msgs[-1]["content"][0]["text"], "I can't help with that request.")

    def test_stops_after_max_steps_without_two_user_messages_in_a_row(self):
        complete, _ = script(*[([tool("x", i=str(n), step=n)], "tool_use") for n in range(agents.MAX_STEPS)])  # different calls: not going in circles (stuck.py)
        msgs = [{"role": "user", "content": "hi"}]
        agents.run_loop(complete, "sys", [], msgs, lambda n, a: {})
        self.assertEqual(msgs[-1]["role"], "assistant")
        self.assertIn("stopped after several steps", msgs[-1]["content"][0]["text"])

    def test_the_loop_counts_as_one_piece_of_work(self):
        complete, seen = script(([tool("x")], "tool_use"), ([text("ok")], "end_turn"))
        during_tool = []
        agents.run_loop(busy.counted(complete), "sys", [], [{"role": "user", "content": "hi"}], lambda n, a: during_tool.append(busy.count()) or {})
        self.assertEqual(seen, [1, 1])  # the model call inside the loop isn't counted again
        self.assertEqual(during_tool, [1])  # a tool run still holds a deploy
        self.assertEqual(busy.count(), 0)


class Busy(unittest.TestCase):
    def test_released_on_error(self):
        with self.assertRaises(RuntimeError):
            with busy.working("agent"): raise RuntimeError("x")
        self.assertEqual(busy.count(), 0)

    def test_threads_count_separately(self):
        go, hold = threading.Event(), threading.Event()
        def work():
            with busy.working("agent"): go.set(); hold.wait(5)
        t = threading.Thread(target=work); t.start(); go.wait(5)
        try:
            with busy.working("model"):
                snap = busy.snapshot()
                self.assertEqual(snap["busy"], 2)
                self.assertEqual(snap["kinds"], {"agent": 1, "model": 1})
        finally:
            hold.set(); t.join(5)
        self.assertEqual(busy.count(), 0)


if __name__ == "__main__":
    unittest.main()
