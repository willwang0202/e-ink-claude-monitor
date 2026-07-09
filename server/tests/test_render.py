import datetime as dt
import io
import sys
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import clawd   # noqa: E402
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
    "kobo_battery": 62.0,
}

EMPTY_SNAPSHOT = {"fetched_at": "bad-timestamp", "limits": None,
                  "block": None, "daily": None}

WEDNESDAY = dt.datetime(2026, 7, 8, 10, 23)
SATURDAY = dt.datetime(2026, 7, 11, 15, 23)


def snapshot_with(**overrides):
    merged = dict(FULL_SNAPSHOT)
    merged.update(overrides)
    return merged


def block_with(**overrides):
    merged = dict(FULL_SNAPSHOT["block"])
    merged.update(overrides)
    return merged


class RenderTest(unittest.TestCase):
    def test_full_snapshot_renders_at_native_resolution(self):
        image = render.render_dashboard(FULL_SNAPSHOT, footer="test",
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

    def test_every_scene_painter_renders(self):
        """Force every scene through the full dashboard pipeline."""
        original = clawd._rotation_scene
        try:
            for scene in clawd.SCENE_PAINTERS:
                if scene in ("night", "sleep", "fishing",
                             "confetti", "anxious"):
                    continue  # exercised via their own triggers below
                clawd._rotation_scene = (
                    lambda *_args, _s=scene: _s)  # noqa: E731
                image = render.render_dashboard(FULL_SNAPSHOT,
                                                when=WEDNESDAY)
                self.assertEqual(image.mode, "L", scene)
        finally:
            clawd._rotation_scene = original

    def test_priority_scenes_render(self):
        cases = [
            (WEDNESDAY.replace(hour=3), FULL_SNAPSHOT),          # night
            (WEDNESDAY, EMPTY_SNAPSHOT),                         # sleep
            (WEDNESDAY.replace(hour=19), EMPTY_SNAPSHOT),        # fishing-ish
            (WEDNESDAY, snapshot_with(
                block=block_with(remaining_minutes=298))),       # confetti
            (WEDNESDAY, snapshot_with(limits=[
                {"label": "5 hour", "percent": 97.0,
                 "resets_at": None}])),                          # panic
            (SATURDAY, FULL_SNAPSHOT),                           # maybe surf
        ]
        for when, snapshot in cases:
            image = render.render_dashboard(snapshot, when=when)
            self.assertEqual(image.mode, "L")


class SceneEngineTest(unittest.TestCase):
    def test_night_beats_everything(self):
        state = clawd.scene_state(WEDNESDAY.replace(hour=3), FULL_SNAPSHOT)
        self.assertEqual(state["scene"], "night")

    def test_idle_sleeps_or_fishes(self):
        day = clawd.scene_state(WEDNESDAY, EMPTY_SNAPSHOT)
        self.assertEqual(day["scene"], "sleep")
        evening = clawd.scene_state(WEDNESDAY.replace(hour=20),
                                    EMPTY_SNAPSHOT)
        self.assertIn(evening["scene"], ("fishing", "sleep"))

    def test_confetti_on_fresh_window(self):
        snapshot = snapshot_with(block=block_with(remaining_minutes=299))
        state = clawd.scene_state(WEDNESDAY, snapshot)
        self.assertEqual(state["scene"], "confetti")

    def test_anxiety_overrides_rotation(self):
        snapshot = snapshot_with(limits=[
            {"label": "5 hour", "percent": 85.0, "resets_at": None}])
        state = clawd.scene_state(WEDNESDAY, snapshot)
        self.assertEqual(state["scene"], "anxious")
        self.assertFalse(state["panic"])
        snapshot["limits"][0]["percent"] = 96.0
        self.assertTrue(clawd.scene_state(WEDNESDAY, snapshot)["panic"])

    def test_rotation_is_deterministic(self):
        first = clawd.scene_state(WEDNESDAY, FULL_SNAPSHOT)["scene"]
        second = clawd.scene_state(WEDNESDAY, FULL_SNAPSHOT)["scene"]
        self.assertEqual(first, second)

    def test_rotation_never_repeats_consecutive_buckets(self):
        pool = clawd._scene_pool(WEDNESDAY, FULL_SNAPSHOT)
        for bucket in range(200, 260):
            here = clawd._bucket_pick(bucket, pool)
            prev = clawd._bucket_pick(bucket - 1, pool)
            if here == prev:
                when = dt.datetime.fromtimestamp(
                    bucket * clawd.SCENE_BUCKET_MINUTES * 60)
                resolved = clawd._rotation_scene(when, FULL_SNAPSHOT)
                self.assertNotEqual(resolved, prev)

    def test_rotation_varies_across_a_day(self):
        seen = {
            clawd.scene_state(WEDNESDAY.replace(hour=h, minute=m),
                              FULL_SNAPSHOT)["scene"]
            for h in range(9, 17) for m in (2, 12, 22, 32, 42, 52)
        }
        self.assertGreaterEqual(len(seen), 5)

    def test_gm_only_in_the_morning(self):
        afternoon_pool = clawd._scene_pool(WEDNESDAY, FULL_SNAPSHOT)
        morning_pool = clawd._scene_pool(WEDNESDAY.replace(hour=8),
                                         FULL_SNAPSHOT)
        self.assertNotIn("gm", afternoon_pool)
        self.assertIn("gm", morning_pool)

    def test_surf_only_on_weekends(self):
        self.assertNotIn("surf", clawd._scene_pool(WEDNESDAY, FULL_SNAPSHOT))
        self.assertIn("surf", clawd._scene_pool(SATURDAY, FULL_SNAPSHOT))

    def test_data_gated_scenes_drop_without_data(self):
        pool = clawd._scene_pool(WEDNESDAY, EMPTY_SNAPSHOT)
        for gated in ("sisyphus", "tide", "garden", "tetris"):
            self.assertNotIn(gated, pool)

    def test_fable_model_carries_a_book(self):
        state = clawd.scene_state(WEDNESDAY, FULL_SNAPSHOT)
        self.assertTrue(state["book"])

    def test_burn_tiers(self):
        self.assertEqual(clawd._burn_tier({"cost_per_hour": 5}), 1)
        self.assertEqual(clawd._burn_tier({"cost_per_hour": 20}), 2)
        self.assertEqual(clawd._burn_tier({"cost_per_hour": 50}), 3)

    def test_body_matches_canonical_dimensions(self):
        self.assertEqual(len(clawd.CLAWD_BODY), 8)
        self.assertTrue(all(len(row) == 14 for row in clawd.CLAWD_BODY))


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
