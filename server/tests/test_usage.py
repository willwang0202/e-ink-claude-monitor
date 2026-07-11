import datetime as dt
import json
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


DUMP_FIXTURE = '''
    0x00000007 <blob>="Claude Safe Storage"
    "svce"<blob>="Claude Safe Storage"
    0x00000007 <blob>="Claude Code-credentials-9de0d0a7"
    "svce"<blob>="Claude Code-credentials-9de0d0a7"
    0x00000007 <blob>="Claude Code-credentials-c1481fca"
    "svce"<blob>="Claude Code-credentials-c1481fca"
    0x00000007 <blob>="Claude Code-credentials"
    "svce"<blob>="Claude Code-credentials"
    0x00000007 <blob>="Claude Code-credentials-9de0d0a7"
    "svce"<blob>="Claude Code-credentials-9de0d0a7"
'''


class KeychainDiscoveryTest(unittest.TestCase):
    STUB = {"claudeAiOauth": {"accessToken": "", "expiresAt": 0}}
    LIVE = {"claudeAiOauth": {"accessToken": "tok", "expiresAt": 0,
                              "subscriptionType": "pro"}}

    def setUp(self):
        self._run = usage._run
        self._memo = usage._keychain_service_memo
        usage._keychain_service_memo = None

    def tearDown(self):
        usage._run = self._run
        usage._keychain_service_memo = self._memo

    def _fake_run(self, records):
        def run(cmd, timeout):
            if cmd[:2] == ["security", "dump-keychain"]:
                return DUMP_FIXTURE
            if cmd[:2] == ["security", "find-generic-password"]:
                service = cmd[cmd.index("-s") + 1]
                record = records.get(service)
                return json.dumps(record) if record else None
            return None
        return run

    def test_candidates_parse_suffixed_names_deduped(self):
        usage._run = self._fake_run({})
        self.assertEqual(usage._keychain_service_candidates(),
                         ["Claude Code-credentials-9de0d0a7",
                          "Claude Code-credentials-c1481fca"])

    def test_finds_live_token_behind_stub(self):
        usage._run = self._fake_run({
            "Claude Code-credentials": self.STUB,
            "Claude Code-credentials-9de0d0a7": self.STUB,
            "Claude Code-credentials-c1481fca": self.LIVE,
        })
        oauth = usage._oauth_from_keychain()
        self.assertEqual(oauth["accessToken"], "tok")
        self.assertEqual(usage._keychain_service_memo,
                         "Claude Code-credentials-c1481fca")

    def test_memo_skips_rescan(self):
        usage._keychain_service_memo = "Claude Code-credentials-c1481fca"

        def run(cmd, timeout):
            if cmd[:2] == ["security", "dump-keychain"]:
                raise AssertionError("re-scanned despite memo")
            return json.dumps(self.LIVE)
        usage._run = run
        self.assertEqual(usage._oauth_from_keychain()["accessToken"], "tok")

    def test_falls_back_to_stub_when_no_live_token(self):
        usage._run = self._fake_run({
            "Claude Code-credentials": self.STUB,
        })
        oauth = usage._oauth_from_keychain()
        self.assertEqual(oauth.get("accessToken"), "")


class OauthMemoTest(unittest.TestCase):
    def setUp(self):
        self._file = usage._oauth_from_credentials_file
        self._keychain = usage._oauth_from_keychain
        self._memo = usage._oauth_memo

    def tearDown(self):
        usage._oauth_from_credentials_file = self._file
        usage._oauth_from_keychain = self._keychain
        usage._oauth_memo = self._memo

    def test_falls_back_to_memo_when_keychain_locks(self):
        record = {"accessToken": "x", "expiresAt": 0}
        usage._oauth_from_credentials_file = lambda: None
        usage._oauth_from_keychain = lambda: record
        self.assertEqual(usage.read_oauth(), record)
        # Screen locks: keychain reads start failing.
        usage._oauth_from_keychain = lambda: None
        self.assertEqual(usage.read_oauth(), record)

    def test_no_memo_no_credentials(self):
        usage._oauth_memo = None
        usage._oauth_from_credentials_file = lambda: None
        usage._oauth_from_keychain = lambda: None
        self.assertIsNone(usage.read_oauth())


class TokenFreshnessTest(unittest.TestCase):
    def test_future_expiry_is_fresh(self):
        future_ms = (dt.datetime.now()
                     + dt.timedelta(hours=1)).timestamp() * 1000
        self.assertTrue(usage.token_is_fresh({"expiresAt": future_ms}))

    def test_past_expiry_is_stale(self):
        past_ms = (dt.datetime.now()
                   - dt.timedelta(hours=1)).timestamp() * 1000
        self.assertFalse(usage.token_is_fresh({"expiresAt": past_ms}))

    def test_unknown_expiry_is_optimistic(self):
        # Newer Claude Code stores expiresAt as 0; missing/garbage values
        # also mean "unknown" — attempt the call, let a 401 decide.
        self.assertTrue(usage.token_is_fresh({}))
        self.assertTrue(usage.token_is_fresh({"expiresAt": 0}))
        self.assertTrue(usage.token_is_fresh({"expiresAt": "not-a-number"}))

    def test_stale_token_skips_endpoint(self):
        saved = usage._limits_cache
        usage._limits_cache = {"limits": None, "fetched_at": None,
                               "next_attempt_at": None}
        try:
            past_ms = (dt.datetime.now()
                       - dt.timedelta(hours=1)).timestamp() * 1000
            result = usage.fetch_plan_limits(
                {"accessToken": "x", "expiresAt": past_ms}
            )
            self.assertIsNone(result)
        finally:
            usage._limits_cache = saved


API_LIMITS_RESPONSE = {
    "five_hour": {"utilization": 43.0, "resets_at": "2026-07-09T02:00:00Z"},
    "seven_day": {"utilization": 27.0, "resets_at": "2026-07-14T05:00:00Z"},
    "limits": [
        {"kind": "session", "group": "session", "percent": 43,
         "resets_at": "2026-07-09T02:00:00Z", "scope": None},
        {"kind": "weekly_all", "group": "weekly", "percent": 27,
         "resets_at": "2026-07-14T05:00:00Z", "scope": None},
        {"kind": "weekly_scoped", "group": "weekly", "percent": 41,
         "resets_at": "2026-07-14T05:00:00Z",
         "scope": {"model": {"id": None, "display_name": "Fable"},
                   "surface": None}},
    ],
}


class LimitsCacheTest(unittest.TestCase):
    T0 = dt.datetime(2026, 7, 10, 9, 0, 0)
    WINDOW = [{"label": "5 hour", "percent": 10.0, "resets_at": None}]

    def setUp(self):
        self._orig_fetch = usage._fetch_limits_now
        self._orig_cache = usage._limits_cache
        usage._limits_cache = {"limits": None, "fetched_at": None,
                               "next_attempt_at": None}

    def tearDown(self):
        usage._fetch_limits_now = self._orig_fetch
        usage._limits_cache = self._orig_cache

    def _prime(self):
        usage._fetch_limits_now = lambda oauth: (self.WINDOW, 0)
        return usage.fetch_plan_limits(oauth={}, now=self.T0)

    def test_second_call_within_window_skips_the_endpoint(self):
        self._prime()

        def explode(_oauth):
            raise AssertionError("endpoint hit inside poll window")
        usage._fetch_limits_now = explode
        result = usage.fetch_plan_limits(
            oauth={}, now=self.T0 + dt.timedelta(seconds=60))
        self.assertEqual(result, self.WINDOW)

    def test_failure_serves_last_good_reading(self):
        self._prime()
        usage._fetch_limits_now = lambda oauth: (None, 0)  # e.g. network
        result = usage.fetch_plan_limits(
            oauth={}, now=self.T0 + dt.timedelta(seconds=400))
        self.assertEqual(result, self.WINDOW)

    def test_grace_expires_eventually(self):
        self._prime()
        usage._fetch_limits_now = lambda oauth: (None, 0)
        stale = self.T0 + dt.timedelta(
            seconds=usage.config.LIMITS_GRACE_SECONDS + 400)
        self.assertIsNone(usage.fetch_plan_limits(oauth={}, now=stale))

    def test_retry_after_is_honored(self):
        usage._fetch_limits_now = lambda oauth: (None, 851)  # a 429
        usage.fetch_plan_limits(oauth={}, now=self.T0)
        penalty = max(usage.config.LIMITS_POLL_SECONDS, 851 + 30)

        def explode(_oauth):
            raise AssertionError("retried before Retry-After elapsed")
        usage._fetch_limits_now = explode
        # Inside the penalty window -> no request.
        usage.fetch_plan_limits(
            oauth={}, now=self.T0 + dt.timedelta(seconds=penalty - 60))
        # After the penalty: a request goes out again.
        usage._fetch_limits_now = lambda oauth: (self.WINDOW, 0)
        result = usage.fetch_plan_limits(
            oauth={}, now=self.T0 + dt.timedelta(seconds=penalty + 60))
        self.assertEqual(result, self.WINDOW)


class ParseLimitsTest(unittest.TestCase):
    def test_parses_limits_array_in_order(self):
        windows = usage.parse_limits(API_LIMITS_RESPONSE)
        self.assertEqual([w["label"] for w in windows],
                         ["5 hour", "Week", "Fable"])
        self.assertEqual([w["percent"] for w in windows],
                         [43.0, 27.0, 41.0])

    def test_model_scoped_entry_uses_display_name(self):
        windows = usage.parse_limits(API_LIMITS_RESPONSE)
        fable = windows[2]
        self.assertEqual(fable["label"], "Fable")
        self.assertEqual(fable["resets_at"], "2026-07-14T05:00:00Z")

    def test_falls_back_to_legacy_fields(self):
        legacy = {key: value for key, value in API_LIMITS_RESPONSE.items()
                  if key != "limits"}
        windows = usage.parse_limits(legacy)
        self.assertEqual([w["label"] for w in windows], ["5 hour", "Week"])

    def test_skips_malformed_entries(self):
        windows = usage.parse_limits(
            {"limits": [{"kind": "session"}, "junk",
                        {"kind": "weekly_all", "percent": 10}]}
        )
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0]["label"], "Week")

    def test_empty_response_returns_none(self):
        self.assertIsNone(usage.parse_limits({}))
        self.assertIsNone(usage.parse_limits({"limits": []}))


if __name__ == "__main__":
    unittest.main()
