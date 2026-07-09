"""Renders a usage snapshot into an e-ink friendly grayscale PNG.

Layout: header, a large stage for Clawd (Claude Code's mascot, canonical
14x8 pixel grid from the official clawd-animation spec), the 7-day bar
chart, and the month total. One animation frame per refresh.
"""

import datetime as dt
import io
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

import config

BLACK = 0
DARK = 60
MID = 140
LIGHT = 210
WHITE = 255

MARGIN = 56
CHART_HEIGHT = 230
BAR_HEIGHT = 44

# Vertical space reserved below Clawd's stage for chart + month + footer.
LOWER_SECTIONS_HEIGHT = 700


def _first_existing(paths: List[str]) -> Optional[str]:
    for path in paths:
        if Path(path).exists():
            return path
    return None


def _load_fonts() -> Dict[str, Any]:
    """Best-available fonts; falls back to Pillow's bitmap font."""
    pair = next(
        (
            (regular, bold)
            for regular, bold in config.FONT_CANDIDATES
            if Path(regular).exists() and Path(bold).exists()
        ),
        None,
    )
    mono_path = _first_existing(config.MONO_FONT_CANDIDATES)

    def load(path: Optional[str], size: int) -> Any:
        if path is None:
            return ImageFont.load_default()
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            return ImageFont.load_default()

    regular, bold = pair if pair else (None, None)
    return {
        "title": load(bold, 64),
        "big": load(bold, 78),
        "section": load(bold, 38),
        "body": load(regular, 44),
        "body_bold": load(bold, 44),
        "small": load(regular, 34),
        "tiny": load(mono_path or regular, 28),
        "zzz": load(bold, 52),
    }


def _fmt_money(value: float) -> str:
    return "${:,.2f}".format(value)


def _fmt_tokens(value: int) -> str:
    if value >= 1_000_000_000:
        return "{:.1f}B".format(value / 1_000_000_000)
    if value >= 1_000_000:
        return "{:.1f}M".format(value / 1_000_000)
    if value >= 1_000:
        return "{:.0f}K".format(value / 1_000)
    return str(value)


def _fmt_reset(iso_value: Optional[str]) -> str:
    if not iso_value:
        return ""
    try:
        stamp = dt.datetime.fromisoformat(str(iso_value).replace("Z", "+00:00"))
    except ValueError:
        return ""
    local = stamp.astimezone()
    now = dt.datetime.now().astimezone()
    day = "" if local.date() == now.date() else local.strftime(" %a")
    return local.strftime("%H:%M") + day


class Canvas:
    """Tracks a vertical cursor while drawing sections top to bottom."""

    def __init__(self, width: int, height: int, fonts: Dict[str, Any]):
        self.image = Image.new("L", (width, height), WHITE)
        self.draw = ImageDraw.Draw(self.image)
        self.fonts = fonts
        self.width = width
        self.y = MARGIN

    def text(self, x: int, text: str, font_name: str,
             fill: int = BLACK, y: Optional[int] = None) -> Tuple[int, int]:
        font = self.fonts[font_name]
        position_y = self.y if y is None else y
        self.draw.text((x, position_y), text, font=font, fill=fill)
        box = self.draw.textbbox((x, position_y), text, font=font)
        return box[2] - box[0], box[3] - position_y

    def text_right(self, text: str, font_name: str,
                   fill: int = BLACK, y: Optional[int] = None) -> None:
        font = self.fonts[font_name]
        box = self.draw.textbbox((0, 0), text, font=font)
        x = self.width - MARGIN - (box[2] - box[0])
        self.draw.text((x, self.y if y is None else y), text,
                       font=font, fill=fill)

    def advance(self, pixels: int) -> None:
        self.y += pixels

    def rule(self, weight: int = 3, fill: int = BLACK) -> None:
        self.draw.rectangle(
            [MARGIN, self.y, self.width - MARGIN, self.y + weight], fill=fill
        )
        self.advance(weight + 30)

    def section_title(self, label: str) -> None:
        self.text(MARGIN, label.upper(), "section", fill=DARK)
        self.advance(58)

    def progress_bar(self, label: str, pct: float, note: str) -> None:
        bar_x = MARGIN + 220
        bar_width = self.width - MARGIN - bar_x - 170
        clamped = max(0.0, min(pct, 100.0))
        self.text(MARGIN, label, "body_bold")
        outline = [bar_x, self.y, bar_x + bar_width, self.y + BAR_HEIGHT]
        self.draw.rectangle(outline, outline=BLACK, width=3)
        fill_width = int(bar_width * clamped / 100.0)
        if fill_width > 6:
            shade = BLACK if clamped < 80 else DARK
            self.draw.rectangle(
                [bar_x + 3, self.y + 3,
                 bar_x + 3 + fill_width - 6, self.y + BAR_HEIGHT - 3],
                fill=shade,
            )
        self.text_right("{:.0f}%".format(pct), "body_bold")
        if note:
            self.text(bar_x, note, "tiny", fill=MID, y=self.y + BAR_HEIGHT + 8)
            self.advance(BAR_HEIGHT + 52)
        else:
            self.advance(BAR_HEIGHT + 28)


def _draw_header(canvas: Canvas, snapshot: Dict[str, Any]) -> None:
    width, _ = canvas.text(MARGIN, "CLAUDE CODE", "title")
    plan = snapshot.get("plan")
    if plan:
        canvas.text(MARGIN + width + 28, plan, "section",
                    fill=MID, y=canvas.y + 22)
    updated = ""
    try:
        stamp = dt.datetime.fromisoformat(snapshot.get("fetched_at", ""))
        updated = stamp.strftime("%H:%M")
    except ValueError:
        pass
    canvas.text_right(updated, "title", fill=MID)
    canvas.advance(96)
    canvas.rule(6)


def _draw_limits(canvas: Canvas,
                 limits: Optional[List[Dict[str, Any]]]) -> None:
    canvas.section_title("Plan limits")
    if not limits:
        canvas.text(MARGIN, "unavailable — refreshes on next claude run",
                    "small", fill=MID)
        canvas.advance(64)
        canvas.rule()
        return
    for window in limits:
        reset = _fmt_reset(window.get("resets_at"))
        note = "resets " + reset if reset else ""
        canvas.progress_bar(window["label"], window["percent"], note)
    canvas.advance(16)
    canvas.rule()


# ---------------------------------------------------------------- Clawd
# Canonical sprite from the official clawd-animation spec: 14x8 flat
# body, 1x1 eyes at (4,1)/(9,1), no mouth. Coral #CD6E58 maps to MID.

CLAWD_BODY = [
    [0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0],
    [0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0],
    [0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0],
    [0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0],
    [0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0],
    [0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0],
    [0, 0, 0, 1, 0, 1, 0, 0, 1, 0, 1, 0, 0, 0],
    [0, 0, 0, 1, 0, 1, 0, 0, 1, 0, 1, 0, 0, 0],
]
CLAWD_EYE_LEFT = (4, 1)
CLAWD_EYE_RIGHT = (9, 1)
CLAWD_EYES = {
    "forward": (0, 0),
    "look_right": (1, 0),
    "look_left": (-1, 0),
    "look_down": (0, 1),
    "blink": None,
}
CLAWD_HEART = [
    [1, 0, 1, 0, 0],
    [1, 1, 1, 1, 0],
    [0, 1, 1, 1, 0],
    [0, 0, 1, 0, 0],
]
CLAWD_SCALE = 24

# Fixed starfield for the stage, as (x-fraction, y-fraction, shade).
STAGE_STARS = [
    (0.08, 0.10, MID), (0.30, 0.05, LIGHT), (0.55, 0.12, MID),
    (0.76, 0.06, LIGHT), (0.92, 0.16, MID), (0.14, 0.34, LIGHT),
    (0.44, 0.28, MID), (0.68, 0.35, LIGHT), (0.88, 0.44, LIGHT),
    (0.05, 0.52, LIGHT), (0.26, 0.55, MID), (0.61, 0.52, LIGHT),
]


def _scene_state(when: dt.datetime, is_active: bool) -> Dict[str, Any]:
    """Pure animation state for one frame: where Clawd is and his mood.

    He crosses the stage once per hour (ping-pong on odd hours), blinks
    every 5th minute, waves every 7th, and sleeps when no Claude Code
    session is active.
    """
    minute = when.minute
    if not is_active:
        return {"progress": 0.5, "eye": "blink", "wave": False,
                "asleep": True, "facing_right": True, "step": 0}
    progress = minute / 59.0
    facing_right = when.hour % 2 == 0
    if not facing_right:
        progress = 1.0 - progress
    wave = minute % 7 == 0
    if wave:
        eye = "forward"
    elif minute % 5 == 0:
        eye = "blink"
    else:
        eye = "look_right" if facing_right else "look_left"
    return {"progress": progress, "eye": eye, "wave": wave,
            "asleep": False, "facing_right": facing_right,
            "step": minute % 2}


def _draw_star(draw: ImageDraw.ImageDraw, x: int, y: int, shade: int) -> None:
    arm = 12
    thickness = 4
    draw.rectangle([x - arm, y - thickness // 2,
                    x + arm, y + thickness // 2], fill=shade)
    draw.rectangle([x - thickness // 2, y - arm,
                    x + thickness // 2, y + arm], fill=shade)


def _draw_clawd_sprite(draw: ImageDraw.ImageDraw, x0: int, y0: int,
                       state: Dict[str, Any]) -> None:
    scale = CLAWD_SCALE

    def cell(col: float, row: float, shade: int) -> None:
        x = x0 + int(col * scale)
        y = y0 + int(row * scale)
        draw.rectangle([x, y, x + scale - 1, y + scale - 1], fill=shade)

    for row_index, row in enumerate(CLAWD_BODY):
        for col_index, filled in enumerate(row):
            if filled:
                cell(col_index, row_index, MID)

    if state["wave"]:  # raised claw on the leading side
        if state["facing_right"]:
            cell(13, 1, MID)
            cell(14, 0, MID)
        else:
            cell(0, 1, MID)
            cell(-1, 0, MID)

    eye_offset = CLAWD_EYES[state["eye"]]
    if eye_offset is not None:
        dx, dy = eye_offset
        for ex, ey in (CLAWD_EYE_LEFT, CLAWD_EYE_RIGHT):
            cell(ex + dx, ey + dy, BLACK)


def _draw_clawd_stage(canvas: Canvas, is_active: bool,
                      when: Optional[dt.datetime] = None) -> None:
    now = when if when is not None else dt.datetime.now()
    state = _scene_state(now, is_active)

    top = canvas.y
    bottom = canvas.image.height - LOWER_SECTIONS_HEIGHT
    for x_frac, y_frac, shade in STAGE_STARS:
        _draw_star(canvas.draw,
                   MARGIN + int(x_frac * (canvas.width - 2 * MARGIN)),
                   top + int(y_frac * (bottom - top)), shade)

    sprite_width = len(CLAWD_BODY[0]) * CLAWD_SCALE
    sprite_height = len(CLAWD_BODY) * CLAWD_SCALE
    ground = bottom - 30
    track = canvas.width - 2 * MARGIN - sprite_width - 2 * CLAWD_SCALE
    x0 = MARGIN + CLAWD_SCALE + int(track * state["progress"])
    # Walk cycle: a half-cell hop on alternating minutes.
    y0 = ground - sprite_height - (CLAWD_SCALE // 2 if state["step"] else 0)

    _draw_clawd_sprite(canvas.draw, x0, y0, state)

    if state["asleep"]:
        for index, letter in enumerate(("z", "Z", "Z")):
            canvas.draw.text(
                (x0 + sprite_width + 10 + index * 42,
                 y0 - 40 - index * 52),
                letter, font=canvas.fonts["zzz"], fill=MID,
            )
    elif now.minute % 13 == 0:  # occasional little heart
        heart_x = x0 + sprite_width + 14
        heart_y = y0 - 3 * CLAWD_SCALE
        for row_index, row in enumerate(CLAWD_HEART):
            for col_index, filled in enumerate(row):
                if filled:
                    x = heart_x + col_index * (CLAWD_SCALE // 2)
                    y = heart_y + row_index * (CLAWD_SCALE // 2)
                    canvas.draw.rectangle(
                        [x, y, x + CLAWD_SCALE // 2 - 1,
                         y + CLAWD_SCALE // 2 - 1], fill=DARK)

    canvas.draw.rectangle(
        [MARGIN, ground + 6, canvas.width - MARGIN, ground + 9], fill=LIGHT
    )
    canvas.y = bottom + 10
    canvas.rule()


# ------------------------------------------------------------- sections

def _draw_chart(canvas: Canvas, daily: Optional[Dict[str, Any]]) -> None:
    canvas.section_title("Last 7 days")
    if not daily:
        canvas.text(MARGIN, "ccusage unavailable", "body", fill=MID)
        canvas.advance(76)
        canvas.rule()
        return
    canvas.text_right(_fmt_money(daily["week_cost"]), "body_bold",
                      y=canvas.y - 58)
    chart = daily.get("chart", [])
    if not chart:
        return
    top = canvas.y
    plot_width = canvas.width - 2 * MARGIN
    slot = plot_width // len(chart)
    bar_width = int(slot * 0.62)
    peak = max((day["cost"] for day in chart), default=0.0) or 1.0
    baseline = top + CHART_HEIGHT
    for index, day in enumerate(chart):
        x = MARGIN + index * slot + (slot - bar_width) // 2
        height = int((day["cost"] / peak) * (CHART_HEIGHT - 40))
        is_today = index == len(chart) - 1
        fill = BLACK if is_today else MID
        if height > 2:
            canvas.draw.rectangle(
                [x, baseline - height, x + bar_width, baseline], fill=fill
            )
        else:
            canvas.draw.rectangle(
                [x, baseline - 3, x + bar_width, baseline], fill=LIGHT
            )
        if day["cost"] >= 0.005:
            label = "{:.0f}".format(day["cost"])
            box = canvas.draw.textbbox((0, 0), label, font=canvas.fonts["tiny"])
            canvas.draw.text(
                (x + (bar_width - (box[2] - box[0])) // 2,
                 baseline - height - 38),
                label, font=canvas.fonts["tiny"], fill=DARK,
            )
        box = canvas.draw.textbbox((0, 0), day["label"],
                                   font=canvas.fonts["small"])
        canvas.draw.text(
            (x + (bar_width - (box[2] - box[0])) // 2, baseline + 12),
            day["label"], font=canvas.fonts["small"],
            fill=BLACK if is_today else MID,
        )
    canvas.draw.rectangle(
        [MARGIN, baseline, canvas.width - MARGIN, baseline + 3], fill=BLACK
    )
    canvas.y = baseline + 66
    canvas.rule()


def _draw_month(canvas: Canvas, daily: Optional[Dict[str, Any]]) -> None:
    if not daily:
        return
    canvas.section_title("This month (API-equivalent)")
    canvas.text(MARGIN, _fmt_money(daily["month_cost"]), "big")
    canvas.advance(112)


def _draw_footer(canvas: Canvas, footer: str) -> None:
    if not footer:
        return
    box = canvas.draw.textbbox((0, 0), footer, font=canvas.fonts["tiny"])
    footer_y = canvas.image.height - MARGIN - (box[3] - box[1])
    if canvas.y > footer_y - 20:  # no room left — skip rather than overlap
        return
    canvas.draw.text(
        ((canvas.width - (box[2] - box[0])) // 2, footer_y),
        footer, font=canvas.fonts["tiny"], fill=MID,
    )


def render_dashboard(snapshot: Dict[str, Any],
                     width: int = config.SCREEN_WIDTH,
                     height: int = config.SCREEN_HEIGHT,
                     footer: str = "",
                     when: Optional[dt.datetime] = None) -> Image.Image:
    canvas = Canvas(width, height, _load_fonts())
    _draw_header(canvas, snapshot)
    _draw_limits(canvas, snapshot.get("limits"))
    _draw_clawd_stage(canvas, snapshot.get("block") is not None, when)
    _draw_chart(canvas, snapshot.get("daily"))
    _draw_month(canvas, snapshot.get("daily"))
    _draw_footer(canvas, footer)
    return canvas.image


def render_png_bytes(snapshot: Dict[str, Any], footer: str = "") -> bytes:
    buffer = io.BytesIO()
    render_dashboard(snapshot, footer=footer).save(buffer, format="PNG")
    return buffer.getvalue()
