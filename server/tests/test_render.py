import datetime as dt
import io
import sys
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
import render  # noqa: E402

FULL_SNAPSHOT = {
    "fetched_at": "2026-07-07T14:30:00+08:00",
    "plan": "PRO",
    "limits": [
        {"label": "5 hour", "percent": 43.0,
         "resets_at": "2026-07-09T02:00:00+00:00"},
        {"label": "Week", "percent": 27.0,
         "resets_at": "2026-07-14T05:00:00+00:00"},
        {"label": "Fable", "percent": 41.0,
         "resets_at": "2026-07-14T05:00:00+00:00"},
    ],
    "block": {
        "cost": 5.03, "tokens": 1524405, "cost_per_hour": 20.0,
        "remaining_minutes": 259, "projected_cost": 153.12,
        "end_time": "2026-07-07T20:00:00Z",
        "models": ["claude-fable-5", "claude-sonnet-4-6"],
    },
    "daily": {
        "today_cost": 5.03, "today_tokens": 1524405,
        "today_models": ["claude-fable-5"],
        "week_cost": 42.42, "month_cost": 225.60,
        "chart": [
            {"date": "2026-07-0{}".format(i), "label": label, "cost": cost}
            for i, (label, cost) in enumerate(
                [("W", 12.0), ("T", 0.0), ("F", 3.3), ("S", 8.1),
                 ("S", 6.2), ("M", 7.8), ("T", 5.0)], start=1)
        ],
    },
}

EMPTY_SNAPSHOT = {"fetched_at": "bad-timestamp", "limits": None,
                  "block": None, "daily": None}

BLOCK = FULL_SNAPSHOT["block"]
WEDNESDAY = dt.datetime(2026, 7, 8, 10, 23)   # weekday, daytime
SATURDAY = dt.datetime(2026, 7, 11, 15, 23)


def block_with(**overrides):
    merged = dict(BLOCK)
    merged.update(overrides)
    return merged


class RenderTest(unittest.TestCase):
    def test_full_snapshot_renders_at_native_resolution(self):
        image = render.render_dashboard(FULL_SNAPSHOT, footer="test footer",
                                        when=WEDNESDAY)
        self.assertEqual(image.size,
                         (config.SCREEN_WIDTH, config.SCREEN_HEIGHT))
        self.assertEqual(image.mode, "L")

    def test_render_actually_draws_content(self):
        image = render.render_dashboard(FULL_SNAPSHOT, when=WEDNESDAY)
        extrema = image.getextrema()
        self.assertEqual(extrema[1], 255)
        self.assertLess(extrema[0], 100)

    def test_missing_sections_do_not_crash(self):
        image = render.render_dashboard(EMPTY_SNAPSHOT, when=WEDNESDAY)
        self.assertEqual(image.size,
                         (config.SCREEN_WIDTH, config.SCREEN_HEIGHT))

    def test_png_bytes_is_valid_png(self):
        data = render.render_png_bytes(FULL_SNAPSHOT)
        decoded = Image.open(io.BytesIO(data))
        self.assertEqual(decoded.format, "PNG")

    def test_every_mode_renders_without_crashing(self):
        cases = [
            (WEDNESDAY, FULL_SNAPSHOT),                        # brisk+book
            (WEDNESDAY.replace(hour=3), FULL_SNAPSHOT),        # nightcap
            (WEDNESDAY, EMPTY_SNAPSHOT),                       # sleep
            (SATURDAY, FULL_SNAPSHOT),                         # surf
        ]
        for when, snapshot in cases:
            image = render.render_dashboard(snapshot, when=when)
            self.assertEqual(image.mode, "L")


class SceneStateTest(unittest.TestCase):
    def test_nightcap_beats_everything(self):
        state = render._scene_state(WEDNESDAY.replace(hour=3),
                                    block_with(), 99.0)
        self.assertEqual(state["mode"], "nightcap")

    def test_sleeps_when_idle(self):
        state = render._scene_state(WEDNESDAY, None)
        self.assertEqual(state["mode"], "sleep")
        self.assertEqual(state["eye"], "blink")

    def test_confetti_on_fresh_window(self):
        state = render._scene_state(WEDNESDAY,
                                    block_with(remaining_minutes=298))
        self.assertEqual(state["mode"], "confetti")

    def test_anxious_above_80_percent(self):
        state = render._scene_state(WEDNESDAY, block_with(), 85.0)
        self.assertEqual(state["mode"], "anxious")
        self.assertFalse(state["panic"])

    def test_panic_above_95_percent(self):
        state = render._scene_state(WEDNESDAY, block_with(), 97.0)
        self.assertTrue(state["panic"])

    def test_weekend_surfs_the_chart(self):
        state = render._scene_state(SATURDAY, block_with(), 40.0)
        self.assertEqual(state["mode"], "surf")

    def test_burn_rate_moods(self):
        self.assertEqual(render._scene_state(
            WEDNESDAY, block_with(cost_per_hour=5))["mode"], "stroll")
        self.assertEqual(render._scene_state(
            WEDNESDAY, block_with(cost_per_hour=20))["mode"], "brisk")
        self.assertEqual(render._scene_state(
            WEDNESDAY, block_with(cost_per_hour=50))["mode"], "sprint")

    def test_fable_model_carries_a_book(self):
        state = render._scene_state(WEDNESDAY, block_with())
        self.assertTrue(state["book"])
        no_fable = block_with(models=["claude-sonnet-4-6"])
        self.assertFalse(render._scene_state(WEDNESDAY, no_fable)["book"])

    def test_walks_across_the_hour(self):
        early = render._scene_state(WEDNESDAY.replace(minute=5), block_with())
        late = render._scene_state(WEDNESDAY.replace(minute=55), block_with())
        self.assertLess(early["progress"], late["progress"])

    def test_waves_every_seventh_minute(self):
        state = render._scene_state(WEDNESDAY.replace(minute=21),
                                    block_with())
        self.assertTrue(state["wave"])

    def test_five_hour_percent_lookup(self):
        self.assertEqual(
            render._five_hour_percent(FULL_SNAPSHOT["limits"]), 43.0)
        self.assertIsNone(render._five_hour_percent(None))

    def test_body_matches_canonical_dimensions(self):
        self.assertEqual(len(render.CLAWD_BODY), 8)
        self.assertTrue(all(len(row) == 14 for row in render.CLAWD_BODY))


class FormattersTest(unittest.TestCase):
    def test_money(self):
        self.assertEqual(render._fmt_money(1234.5), "$1,234.50")

    def test_tokens(self):
        self.assertEqual(render._fmt_tokens(999), "999")
        self.assertEqual(render._fmt_tokens(1524405), "1.5M")
        self.assertEqual(render._fmt_tokens(2_100_000_000), "2.1B")

    def test_reset_formatter_handles_bad_input(self):
        self.assertEqual(render._fmt_reset(None), "")
        self.assertEqual(render._fmt_reset("garbage"), "")


if __name__ == "__main__":
    unittest.main()
