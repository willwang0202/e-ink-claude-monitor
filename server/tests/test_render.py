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
    "limits": {
        "five_hour": {"utilization": 43.0,
                      "resets_at": "2026-07-07T20:00:00Z"},
        "seven_day": {"utilization": 21.5,
                      "resets_at": "2026-07-10T00:00:00Z"},
        "seven_day_opus": {"utilization": 96.0, "resets_at": None},
        "seven_day_sonnet": None,
    },
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

    def test_custom_dimensions(self):
        image = render.render_dashboard(FULL_SNAPSHOT, width=800, height=600)
        self.assertEqual(image.size, (800, 600))


class FormattersTest(unittest.TestCase):
    def test_money(self):
        self.assertEqual(render._fmt_money(1234.5), "$1,234.50")

    def test_tokens(self):
        self.assertEqual(render._fmt_tokens(999), "999")
        self.assertEqual(render._fmt_tokens(1524405), "1.5M")
        self.assertEqual(render._fmt_tokens(2_100_000_000), "2.1B")

    def test_reset_bad_input(self):
        self.assertEqual(render._fmt_reset(None), "")
        self.assertEqual(render._fmt_reset("garbage"), "")


if __name__ == "__main__":
    unittest.main()
