"""A brief rate limit is not the plan's usage limit (Agent_Company's V1): a per-minute 429 or an overloaded API is waited out
and tried once more, and holds no login; only the plan's usage limit holds a login until its reset (llm.limit_kind)."""
import contextlib, time, unittest
from unittest import mock

from app import codex_cli, llm
from app.llm import LLMError, QuotaError, RateLimited
from app.mining_autoloop import classify
from test_codex_cli import Fake, failed, ok

BRIEF = ["Rate limit reached for gpt-5 in organization org-x on tokens per min (TPM): Limit 30000. Please try again in 1.2s.",
         "Rate limit exceeded for requests", "Error code: 429 - rate_limit_exceeded", "429 Too Many Requests",
         'API Error: 429 {"type":"error","error":{"type":"rate_limit_error","message":"This request would exceed the rate limit"}}']
PLAN = ["You've hit your limit · resets 3pm", "You've hit your session limit · resets 9:50pm (Europe/Berlin)", "5-hour limit reached ∙ resets 3pm",
        "Claude AI usage limit reached|1762200000", "Weekly limit reached for Claude Opus", "You've hit your usage limit. Try again at 3:45 PM.",
        "Rate limit reached; please try again in 45 minutes."]  # a "rate limit" that long holds the login like the plan's
NEITHER = ["Budget limit reached for this run", "Reached maximum budget ($1.00)", "Output token limit exceeded", "Prompt is too long",
           "API Error: 529 Overloaded", "429 You exceeded your current quota, please check your plan and billing details."]



@contextlib.contextmanager
def llm_sleep():
    """Patches the sleep `llm` itself calls (`retry_brief`'s wait), not the global `time.sleep`. Patching the global one also
    counts the polls `subprocess.run(timeout=…)` makes while a CLI child exits after closing its pipes, so the Codex cases
    failed whenever the fake child was a few milliseconds slow (R-23). Everything else on `llm.time` is the real module's."""
    slept = mock.Mock()
    class LlmTime:
        sleep = slept
        def __getattr__(self, name): return getattr(time, name)
    with mock.patch.object(llm, "time", LlmTime()): yield slept

class Kinds(unittest.TestCase):
    def test_messages_are_told_apart(self):
        for m in BRIEF: self.assertEqual(llm.limit_kind(m)[0], "brief", m)
        for m in PLAN: self.assertEqual(llm.limit_kind(m)[0], "plan", m)
        for m in NEITHER: self.assertEqual(llm.limit_kind(m), (None, None), m)

    def test_the_wait_a_message_asks_for(self):
        self.assertEqual(llm.limit_wait("try again in 1.2s"), 1.2)
        self.assertEqual(llm.limit_wait("Please retry after 30"), 30)
        self.assertEqual(llm.limit_wait("try again in 250ms"), 0.25)
        self.assertEqual(llm.limit_wait("try again in 20 minutes"), 1200)
        self.assertEqual(llm.limit_wait("try again in 2 hours"), 7200)
        self.assertIsNone(llm.limit_wait("API Error: 529 Overloaded"))


class ClaudeCode(unittest.TestCase):
    def setUp(self): llm._QUOTA["until"] = 0.0
    def tearDown(self): llm._QUOTA["until"] = 0.0

    def test_a_brief_limit_holds_nothing_and_counts_as_rate(self):
        for m in BRIEF:
            with self.assertRaises(RateLimited) as e: llm._cli_fail(m, cli=True)
            self.assertNotIsInstance(e.exception, QuotaError)
            self.assertEqual(classify(str(e.exception)), "rate", m)
            self.assertEqual(llm.quota_until(), 0, m)

    def test_the_plans_usage_limit_still_holds_the_login(self):
        with self.assertRaises(QuotaError) as e: llm._cli_fail("You've hit your limit · resets 3pm", cli=True)
        self.assertEqual(classify(str(e.exception)), "quota")
        self.assertGreater(llm.quota_until(), time.time())

    def test_a_long_rate_limit_holds_the_login_for_the_wait_it_names(self):
        t = time.time()
        with self.assertRaises(QuotaError): llm._cli_fail("Rate limit reached; please try again in 45 minutes.", cli=True)
        self.assertAlmostEqual(llm.quota_until() - t, 2700, delta=5)

    def test_other_limits_are_plain_errors(self):
        for m in NEITHER:
            with self.assertRaises(LLMError) as e: llm._cli_fail(m, cli=True)
            self.assertNotIsInstance(e.exception, (QuotaError, RateLimited), m)
            self.assertEqual(llm.quota_until(), 0, m)


class Retry(unittest.TestCase):
    def test_a_brief_limit_is_waited_out_once(self):
        calls = []
        def once(x):
            calls.append(x)
            if len(calls) == 1: raise RateLimited("rate-limited", 1.2)
            return "ok"
        with llm_sleep() as slept:
            self.assertEqual(llm.retry_brief(once, 7), "ok")
        self.assertEqual(calls, [7, 7]); slept.assert_called_once_with(1.2)

    def test_no_named_wait_takes_the_default_and_a_second_limit_is_raised(self):
        def once(): raise RateLimited("rate-limited")
        with llm_sleep() as slept, self.assertRaises(RateLimited): llm.retry_brief(once)
        slept.assert_called_once_with(llm.RATE_RETRY_DEFAULT)

    def test_a_long_wait_is_not_slept_in_place(self):
        def once(): raise RateLimited("rate-limited", llm.RATE_RETRY_MAX + 1)
        with llm_sleep() as slept, self.assertRaises(RateLimited): llm.retry_brief(once)
        slept.assert_not_called()


class Codex(Fake):
    def test_a_per_minute_limit_is_tried_again_and_holds_nothing(self):
        self.plays([{"type": "turn.started"}, failed(BRIEF[0])], ok("The answer."))
        with llm_sleep() as slept:
            self.assertEqual(codex_cli.run("p", "s", "m", "low"), ("The answer.", 120))
        slept.assert_called_once_with(1.2)
        self.assertEqual(len(self.calls()), 2)
        self.assertEqual(llm.quota_until("codex"), 0)

    def test_two_in_a_row_fail_as_rate_not_quota(self):
        self.plays([{"type": "turn.started"}, failed(BRIEF[0])])
        with llm_sleep(), self.assertRaises(RateLimited) as e: codex_cli.run("p", "s", "m", "low")
        self.assertEqual(classify(str(e.exception)), "rate")
        self.assertEqual(llm.quota_until("codex"), 0)

    def test_the_usage_limit_is_not_retried(self):
        self.plays([{"type": "turn.started"}, failed("You've hit your usage limit. Try again at 11:59 PM.")])
        with llm_sleep() as slept, self.assertRaises(QuotaError): codex_cli.run("p", "s", "m", "low")
        slept.assert_not_called()
        self.assertEqual(len(self.calls()), 1)
        self.assertGreater(llm.quota_until("codex"), time.time())


if __name__ == "__main__":
    unittest.main()
