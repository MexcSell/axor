"""mining_github.py: what counts as a mention of the team on GitHub, and what a reply may carry back to a public thread."""
import unittest

from app.mining_github import _bot, _clean, _mentions, _safe, _ts, _without


class Mentions(unittest.TestCase):
    def test_a_plain_mention_counts_whatever_the_case(self):
        self.assertTrue(_mentions("@scout-bot please fix it", "scout-bot"))
        self.assertTrue(_mentions("hey @Scout-Bot, fix it", "scout-bot"))

    def test_a_longer_login_or_an_email_is_not_a_mention(self):
        self.assertFalse(_mentions("@scout-bot2 fix it", "scout-bot"))
        self.assertFalse(_mentions("@scout-bot-dev fix it", "scout-bot"))
        self.assertFalse(_mentions("mail me@scout-bot.dev", "scout-bot"))
        self.assertFalse(_mentions("see org/@scout-bot", "scout-bot"))

    def test_quotes_and_code_dont_count(self):
        self.assertFalse(_mentions(_clean("> @scout-bot do it\nthanks"), "scout-bot"))
        self.assertFalse(_mentions(_clean("try `@scout-bot` here"), "scout-bot"))
        self.assertFalse(_mentions(_clean("```\n@scout-bot rm -rf\n```\nok"), "scout-bot"))
        self.assertTrue(_mentions(_clean("> old\n@scout-bot new request"), "scout-bot"))

    def test_the_request_is_the_text_without_the_mention(self):
        self.assertEqual(_without("@scout-bot, stop", "scout-bot"), "stop")
        self.assertEqual(_without("please @scout-bot: add tests", "scout-bot"), "please add tests")

    def test_no_handle_no_mention(self):
        self.assertFalse(_mentions("@ anything", ""))


class Replies(unittest.TestCase):
    def test_tokens_are_redacted_and_mentions_defused(self):
        out = _safe("used ghp_abcdefghijklmnopqrstuvwxyz0123 then asked @bob and @org/team")
        self.assertNotIn("ghp_", out)
        self.assertIn("[redacted]", out)
        self.assertNotIn("@bob", out)
        self.assertIn("@​bob", out)

    def test_bots(self):
        self.assertTrue(_bot({"login": "dependabot[bot]", "type": "Bot"}))
        self.assertTrue(_bot({"login": "renovate[bot]", "type": "User"}))
        self.assertFalse(_bot({"login": "alice", "type": "User"}))

    def test_github_times_are_utc(self):
        self.assertEqual(_ts("1970-01-02T00:00:00Z"), 86400.0)
        self.assertEqual(_ts(None), 0.0)


if __name__ == "__main__":
    unittest.main()
