"""Agents → Models → a connected model → Usage (plan_usage.py): the plan's 5-hour, weekly and monthly windows with % used
and the reset time. The payloads are real answers captured 2026-11-10 (Claude's /api/oauth/usage, Claude Code's
stream-json rate_limit_event, `codex app-server` account/rateLimits/read, GitHub's copilot_internal/user), trimmed."""
import unittest
from datetime import datetime, timezone

from app import plan_usage as U

CLAUDE = {
    "five_hour": {"utilization": 3.0, "resets_at": "2026-11-10T23:50:00.126762+00:00"},
    "seven_day": {"utilization": 56.0, "resets_at": "2026-11-14T18:00:00.126784+00:00"},
    "seven_day_opus": None,
    "extra_usage": {"is_enabled": False, "monthly_limit": None},
    "limits": [
        {"kind": "session", "group": "session", "percent": 3, "resets_at": "2026-11-10T23:50:00.244040+00:00", "scope": None},
        {"kind": "weekly_all", "group": "weekly", "percent": 56, "resets_at": "2026-11-14T18:00:00.244064+00:00", "scope": None},
        {"kind": "weekly_scoped", "group": "weekly", "percent": 18, "resets_at": "2026-11-14T18:00:00.244226+00:00",
         "scope": {"model": {"id": None, "display_name": "Fable"}, "surface": None}},
    ],
}
RATE_EVENT = {"status": "allowed", "resetsAt": 1794354600, "rateLimitType": "five_hour", "unifiedWindows": {
    "five_hour": {"utilization": 0.03, "resetsAt": 1794354600, "status": "allowed"},
    "seven_day": {"utilization": 0.55, "resetsAt": 1794679200, "status": "allowed"}}}
CODEX = {"limitId": "codex", "primary": {"usedPercent": 0, "windowDurationMins": 300, "resetsAt": 1794361977},
         "secondary": {"usedPercent": 55, "windowDurationMins": 10080, "resetsAt": 1794595047},
         "credits": {"hasCredits": False, "unlimited": False, "balance": "0"}, "planType": "plus"}
COPILOT = {"login": "someone", "copilot_plan": "individual", "access_type_sku": "free_limited_copilot",
           "quota_reset_date": "2026-12-01", "quota_reset_date_utc": "2026-12-01T00:00:00.000Z", "quota_snapshots": {
               "chat": {"percent_remaining": 98.6, "remaining": 197, "entitlement": 200, "unlimited": False, "quota_reset_at": 0},
               "completions": {"percent_remaining": 99.9, "remaining": 1999, "entitlement": 2000, "unlimited": False},
               "premium_interactions": {"percent_remaining": 0.0, "remaining": 0, "entitlement": 0, "unlimited": False, "has_quota": False}}}


class PlanUsage(unittest.TestCase):
    def test_claude_limits_like_usage_page(self):
        w = U.claude_windows(CLAUDE)
        self.assertEqual([x["label"] for x in w], ["5-hour session", "Weekly limit", "Weekly limit · Fable"])
        self.assertEqual([x["group"] for x in w], ["session", "weekly", "weekly"])
        self.assertEqual([x["used"] for x in w], [3.0, 56.0, 18.0])  # already percents
        self.assertEqual(w[1]["resets_at"], datetime(2026, 11, 14, 18, 0, 0, 244064, timezone.utc).timestamp())

    def test_claude_without_limits_list(self):
        w = U.claude_windows({k: v for k, v in CLAUDE.items() if k != "limits"})
        self.assertEqual([(x["label"], x["used"]) for x in w], [("5-hour session", 3.0), ("Weekly limit", 56.0)])

    def test_claude_extra_usage_is_monthly(self):
        d = {**CLAUDE, "extra_usage": {"is_enabled": True, "monthly_limit": 50, "used_credits": 10, "utilization": 20.0, "currency": "USD"}}
        ex = [x for x in U.claude_windows(d) if x["group"] == "monthly"]
        self.assertEqual(len(ex), 1); self.assertEqual(ex[0]["used"], 20.0)

    def test_rate_event_fractions_become_percents(self):
        w = U.claude_rate_event(RATE_EVENT)
        self.assertEqual([(x["label"], x["used"]) for x in w], [("5-hour session", 3.0), ("Weekly limit", 55.0)])
        self.assertEqual(w[0]["resets_at"], 1794354600.0)

    def test_codex_windows_named_by_length(self):
        w = U.codex_windows(CODEX)
        self.assertEqual([(x["label"], x["group"], x["used"]) for x in w], [("5-hour session", "session", 0.0), ("Weekly limit", "weekly", 55.0)])
        self.assertEqual(U._window_name(43200), ("Monthly limit", "monthly"))

    def test_copilot_monthly_inverted_and_unentitled_left_out(self):
        w = U.copilot_windows(COPILOT)
        self.assertEqual([x["id"] for x in w], ["chat", "completions"])  # premium requests: entitlement 0 on this plan
        self.assertEqual(w[0]["used"], 1.4)
        self.assertEqual(w[0]["group"], "monthly")
        self.assertEqual(w[0]["resets_at"], datetime(2026, 12, 1, tzinfo=timezone.utc).timestamp())

    def test_openrouter_key_limit_and_spend(self):
        now = datetime(2026, 11, 10, 22, 0, tzinfo=timezone.utc).timestamp()  # a Tuesday
        w = U.openrouter_windows({"limit": 20, "limit_remaining": 15, "limit_reset": "monthly", "usage_weekly": 3.2, "usage_monthly": 5}, now)
        self.assertEqual(w[0]["used"], 25.0)
        self.assertEqual(w[0]["resets_at"], datetime(2026, 12, 1, tzinfo=timezone.utc).timestamp())
        week = next(x for x in w if x["id"] == "usage_weekly")
        self.assertIsNone(week["used"])  # no limit on the week: spend only
        self.assertEqual(week["resets_at"], datetime(2026, 11, 16, tzinfo=timezone.utc).timestamp())  # next Monday

    def test_per_token_providers_have_no_windows(self):
        a = U.per_token("anthropic")
        self.assertEqual(a["windows"], []); self.assertIn("no weekly or monthly", a["note"])

    def test_cache(self):
        n = []
        f = lambda: n.append(1) or U._answer()
        U._cache.pop("x", None)
        U.cached("x", f); U.cached("x", f); self.assertEqual(len(n), 1)
        U.cached("x", f, fresh=True); self.assertEqual(len(n), 2)


if __name__ == "__main__":
    unittest.main()
