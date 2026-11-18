"""Stopping a run that's going in circles (stuck.py): the rules, and agents.run_loop ending such a run early."""
import unittest

from app import agents, stuck


class Rules(unittest.TestCase):
    def test_the_same_call_and_result_five_times_in_a_row(self):
        w = stuck.Watch()
        for _ in range(4): self.assertEqual(w.result("file_read", {"path": "a"}, {"text": "x"}), "")
        self.assertIn("file_read 5 times in a row", w.result("file_read", {"path": "a"}, {"text": "x"}))
        self.assertIn("going in circles", w.result("other", {}, "y"), "the reason stays")

    def test_a_different_call_breaks_the_streak(self):
        w = stuck.Watch()
        for _ in range(4): w.result("file_read", {"path": "a"}, "x")
        w.result("file_list", {}, "a")
        for _ in range(4): self.assertEqual(w.result("file_read", {"path": "a"}, "x"), "")

    def test_polling_while_the_answer_changes_is_not_stuck(self):
        w = stuck.Watch()
        for i in range(12): self.assertEqual(w.result("run_status", {"id": 7}, {"state": "running", "step": i}), "")

    def test_input_key_order_and_spacing_dont_matter(self):
        w = stuck.Watch()
        for i in range(4): w.result("q", {"a": 1, "b": 2} if i % 2 else {"b": 2, "a": 1}, "r  s" if i % 2 else "r s")
        self.assertTrue(w.result("q", {"a": 1, "b": 2}, "r s"))

    def test_the_same_error_three_times_even_with_other_calls_between(self):
        w = stuck.Watch()
        for _ in range(2):
            self.assertEqual(w.result("sandbox_run", {"cmd": "make"}, {"error": "No rule to make target"}, True), "")
            w.result("file_list", {}, "a")
        self.assertIn("sandbox_run failed 3 times", w.result("sandbox_run", {"cmd": "make"}, {"error": "No rule to make target"}, True))

    def test_off(self):
        w = stuck.Watch(0, 0)
        self.assertFalse(w.on)
        for _ in range(20): self.assertEqual(w.result("q", {}, "r", True), "")


class RunLoop(unittest.TestCase):
    def loop(self, answers):
        n, ran, messages = [0], [], [{"role": "user", "content": [{"type": "text", "text": "go"}]}]
        def complete(system, tools, msgs):
            n[0] += 1
            return [{"type": "tool_use", "id": f"t{n[0]}", "name": "lookup", "input": {"q": "same"}}], "tool_use", 10
        def run_tool(name, args):
            ran.append(name)
            return answers(len(ran))
        agents._run_loop(complete, "s", [], messages, run_tool)
        return n[0], messages

    def test_a_run_repeating_itself_ends_at_five_with_the_reason(self):
        turns, messages = self.loop(lambda i: {"found": "nothing"})
        self.assertEqual(turns, 5)
        self.assertEqual(messages[-1]["role"], "assistant")
        self.assertIn("going in circles", messages[-1]["content"][0]["text"])
        self.assertEqual(messages[-2]["role"], "user")  # the last tool results are kept: the turns stay well formed
        self.assertEqual(messages[-2]["content"][0]["type"], "tool_result")

    def test_a_tool_that_keeps_failing_the_same_way_ends_at_three(self):
        turns, messages = self.loop(lambda i: {"error": "not found"})
        self.assertEqual(turns, 3)
        self.assertIn("failed 3 times", messages[-1]["content"][0]["text"])

    def test_an_empty_error_field_is_not_a_failure(self):
        n = [0]
        def answers(i):  # the same answer, re-read between other calls: not a repeat in a row, and not an error
            n[0] += 1
            return {"status": "ok", "error": None} if n[0] % 2 else {"other": n[0]}
        turns, messages = self.loop(answers)
        self.assertEqual(turns, agents.MAX_STEPS)

    def test_changing_answers_run_to_the_step_cap(self):
        turns, messages = self.loop(lambda i: {"step": i})
        self.assertEqual(turns, agents.MAX_STEPS)
        self.assertIn("I stopped after several steps", messages[-1]["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
