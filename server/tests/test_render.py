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
        "cost": 5.03, "tokens": 1524405, "cost_per_hour": 34.31,
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

WALK_TIME = dt.datetime(2026, 7, 9, 10, 23)   # even hour, plain walking
WAVE_TIME = dt.datetime(2026, 7, 9, 10, 21)   # minute % 7 == 0 -> wave
BLINK_TIME = dt.datetime(2026, 7, 9, 11, 25)  # odd hour, minute % 5 == 0


class RenderTest(unittest.TestCase):
    def test_full_snapshot_renders_at_native_resolution(self):
        image = render.render_dashboard(FULL_SNAPSHOT, footer="test footer")
        self.assertEqual(image.size,
                         (config.SCREEN_WIDTH, config.SCREEN_HEIGHT))
        self.assertEqual(image.mode, "L")

    def test_render_actually_draws_content(self):
        image = render.render_dashboard(FULL_SNAPSHOT)
        extrema = image.getextrema()
        self.assertEqual(extrema[1], 255)      # white background present
        self.assertLess(extrema[0], 100)       # dark ink present

    def test_missing_sections_do_not_crash(self):
        image = render.render_dashboard(EMPTY_SNAPSHOT)
        self.assertEqual(image.size,
                         (config.SCREEN_WIDTH, config.SCREEN_HEIGHT))

    def test_png_bytes_is_valid_png(self):
        data = render.render_png_bytes(FULL_SNAPSHOT)
        decoded = Image.open(io.BytesIO(data))
        self.assertEqual(decoded.format, "PNG")

    def test_removed_sections_stay_removed(self):
        for name in ("_draw_today", "_draw_block"):
            self.assertFalse(hasattr(render, name), name + " came back")

    def test_reset_formatter_handles_bad_input(self):
        self.assertEqual(render._fmt_reset(None), "")
        self.assertEqual(render._fmt_reset("garbage"), "")


class ClawdSceneTest(unittest.TestCase):
    def test_body_matches_canonical_dimensions(self):
        self.assertEqual(len(render.CLAWD_BODY), 8)
        self.assertTrue(all(len(row) == 14 for row in render.CLAWD_BODY))

    def test_walks_left_to_right_on_even_hours(self):
        early = render._scene_state(WALK_TIME.replace(minute=5), True)
        late = render._scene_state(WALK_TIME.replace(minute=55), True)
        self.assertTrue(early["facing_right"])
        self.assertLess(early["progress"], late["progress"])

    def test_walks_right_to_left_on_odd_hours(self):
        state = render._scene_state(BLINK_TIME.replace(minute=10), True)
        self.assertFalse(state["facing_right"])
        self.assertGreater(state["progress"], 0.5)

    def test_waves_every_seventh_minute(self):
        self.assertTrue(render._scene_state(WAVE_TIME, True)["wave"])
        self.assertFalse(render._scene_state(WALK_TIME, True)["wave"])

    def test_blinks_every_fifth_minute(self):
        self.assertEqual(render._scene_state(BLINK_TIME, True)["eye"],
                         "blink")

    def test_sleeps_when_no_active_block(self):
        state = render._scene_state(WALK_TIME, False)
        self.assertTrue(state["asleep"])
        self.assertEqual(state["eye"], "blink")

    def test_frames_differ_across_minutes(self):
        image_a = render.render_dashboard(FULL_SNAPSHOT, when=WALK_TIME)
        image_b = render.render_dashboard(FULL_SNAPSHOT, when=WAVE_TIME)
        self.assertNotEqual(list(image_a.getdata()), list(image_b.getdata()))

    def test_sleeping_render_does_not_crash(self):
        image = render.render_dashboard(EMPTY_SNAPSHOT, when=WALK_TIME)
        self.assertEqual(image.mode, "L")


class FormattersTest(unittest.TestCase):
    def test_money(self):
        self.assertEqual(render._fmt_money(1234.5), "$1,234.50")

    def test_tokens(self):
        self.assertEqual(render._fmt_tokens(999), "999")
        self.assertEqual(render._fmt_tokens(1524405), "1.5M")
        self.assertEqual(render._fmt_tokens(2_100_000_000), "2.1B")


if __name__ == "__main__":
    unittest.main()
