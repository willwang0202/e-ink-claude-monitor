import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import usage  # noqa: E402

TODAY = dt.date(2026, 7, 7)

DAILY_PAYLOAD = {
    "daily": [
        {
            "period": "2026-07-05",
            "totalCost": 6.18,
            "modelBreakdowns": [
                {"modelName": "claude-fable-5", "cost": 6.18,
                 "inputTokens": 626, "outputTokens": 24142,
                 "cacheCreationTokens": 0, "cacheReadTokens": 3109138},
            ],
        },
        {
            "period": "2026-07-07",
            "totalCost": 5.50,
            "modelBreakdowns": [
                {"modelName": "claude-sonnet-4-6", "cost": 0.32,
                 "inputTokens": 5, "outputTokens": 234,
                 "cacheCreationTokens": 47869, "cacheReadTokens": 95205},
                {"modelName": "claude-fable-5", "cost": 4.71,
                 "inputTokens": 29905, "outputTokens": 28060,
                 "cacheCreationTokens": 88835, "cacheReadTokens": 1234292},
                # Non-Claude usage that ccusage also aggregates — must be
                # excluded from every dashboard number.
                {"modelName": "gemini-2.5-pro", "cost": 100.0,
                 "inputTokens": 1, "outputTokens": 1,
                 "cacheCreationTokens": 0, "cacheReadTokens": 0},
            ],
        },
        {
            # Same month but outside the 7-day chart window.
            "period": "2026-06-30",
            "modelBreakdowns": [
                {"modelName": "claude-fable-5", "cost": 3.00,
                 "inputTokens": 10, "outputTokens": 10,
                 "cacheCreationTokens": 0, "cacheReadTokens": 0},
            ],
        },
    ]
}

BLOCK_PAYLOAD = {
    "blocks": [
        {"isActive": False, "costUSD": 9.99},
        {
            "isActive": True,
            "costUSD": 5.03,
            "totalTokens": 1524405,
            "endTime": "2026-07-07T20:00:00.000Z",
            "burnRate": {"costPerHour": 34.31},
            "projection": {"remainingMinutes": 259, "totalCost": 153.12},
            "models": ["claude-sonnet-4-6", "claude-fable-5", "gemini-2.5-pro"],
        },
    ]
}


class ClaudeTotalsTest(unittest.TestCase):
    def test_excludes_non_claude_models(self):
        entry = DAILY_PAYLOAD["daily"][1]
        totals = usage.claude_totals(entry)
        self.assertAlmostEqual(totals["cost"], 5.03, places=2)
        self.assertNotIn("gemini-2.5-pro", totals["models"])

    def test_sums_all_token_kinds(self):
        entry = DAILY_PAYLOAD["daily"][0]
        totals = usage.claude_totals(entry)
        self.assertEqual(totals["tokens"], 626 + 24142 + 3109138)

    def test_empty_entry_is_zero(self):
        totals = usage.claude_totals({})
        self.assertEqual(totals["cost"], 0.0)
        self.assertEqual(totals["tokens"], 0)


class SummarizeDailyTest(unittest.TestCase):
    def setUp(self):
        self.summary = usage.summarize_daily(DAILY_PAYLOAD, TODAY)

    def test_today_cost_is_claude_only(self):
        self.assertAlmostEqual(self.summary["today_cost"], 5.03, places=2)

    def test_week_cost_covers_chart_window_only(self):
        # 2026-06-30 is 7 days before today — outside the 7-day chart.
        self.assertAlmostEqual(self.summary["week_cost"], 6.18 + 5.03,
                               places=2)

    def test_month_cost_only_includes_current_month(self):
        self.assertAlmostEqual(self.summary["month_cost"], 6.18 + 5.03,
                               places=2)

    def test_chart_has_seven_days_ending_today(self):
        chart = self.summary["chart"]
        self.assertEqual(len(chart), 7)
        self.assertEqual(chart[-1]["date"], "2026-07-07")
        self.assertEqual(chart[0]["date"], "2026-07-01")

    def test_days_without_usage_are_zero(self):
        by_date = {day["date"]: day["cost"] for day in self.summary["chart"]}
        self.assertEqual(by_date["2026-07-06"], 0.0)


class SummarizeActiveBlockTest(unittest.TestCase):
    def test_picks_active_block(self):
        block = usage.summarize_active_block(BLOCK_PAYLOAD)
        self.assertAlmostEqual(block["cost"], 5.03)
        self.assertEqual(block["remaining_minutes"], 259)
        self.assertAlmostEqual(block["projected_cost"], 153.12)

    def test_filters_models_to_claude(self):
        block = usage.summarize_active_block(BLOCK_PAYLOAD)
        self.assertEqual(
            block["models"], ["claude-sonnet-4-6", "claude-fable-5"]
        )

    def test_no_active_block_returns_none(self):
        self.assertIsNone(usage.summarize_active_block({"blocks": []}))


class TokenFreshnessTest(unittest.TestCase):
    def test_future_expiry_is_fresh(self):
        future_ms = (dt.datetime.now()
                     + dt.timedelta(hours=1)).timestamp() * 1000
        self.assertTrue(usage.token_is_fresh({"expiresAt": future_ms}))

    def test_past_expiry_is_stale(self):
        past_ms = (dt.datetime.now()
                   - dt.timedelta(hours=1)).timestamp() * 1000
        self.assertFalse(usage.token_is_fresh({"expiresAt": past_ms}))

    def test_missing_expiry_is_stale(self):
        self.assertFalse(usage.token_is_fresh({}))
        self.assertFalse(usage.token_is_fresh({"expiresAt": "not-a-number"}))

    def test_stale_token_skips_endpoint(self):
        past_ms = (dt.datetime.now()
                   - dt.timedelta(hours=1)).timestamp() * 1000
        result = usage.fetch_plan_limits(
            {"accessToken": "x", "expiresAt": past_ms}
        )
        self.assertIsNone(result)


class LimitWindowTest(unittest.TestCase):
    def test_valid_window(self):
        window = usage._limit_window(
            {"utilization": 43, "resets_at": "2026-07-07T20:00:00Z"}
        )
        self.assertEqual(window["utilization"], 43.0)

    def test_missing_utilization_returns_none(self):
        self.assertIsNone(usage._limit_window({"resets_at": "x"}))
        self.assertIsNone(usage._limit_window(None))


if __name__ == "__main__":
    unittest.main()
