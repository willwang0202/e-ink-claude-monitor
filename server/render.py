"""Renders a usage snapshot into an e-ink friendly grayscale PNG.

Layout: header, plan-limit bars, a stage for Clawd (Claude Code's
mascot, canonical 14x8 rectangle sprite), the 7-day chart, month total.

Clawd is a mood engine — one frame per refresh, priority-ordered:
night (00-07) nightcap sleep > idle sleep > fresh-window confetti >
limit anxiety (5h >= 80%) > weekend chart-surfing > burn-rate walk
(stroll / brisk+sweat / sprint). Carrying a book means Fable is active.
"""

import datetime as dt
import io
import random
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

# Mood thresholds.
NIGHT_END_HOUR = 7
BURN_BRISK_PER_HOUR = 10.0
BURN_SPRINT_PER_HOUR = 35.0
ANXIETY_PERCENT = 80.0
PANIC_PERCENT = 95.0
# A 5h block starts with 300 minutes; this fresh means it just reset.
CONFETTI_REMAINING_MINUTES = 296


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
WALK_MODES = ("stroll", "brisk", "sprint")

# Fixed starfield for the stage, as (x-fraction, y-fraction, shade).
STAGE_STARS = [
    (0.08, 0.10, MID), (0.30, 0.05, LIGHT), (0.55, 0.12, MID),
    (0.76, 0.06, LIGHT), (0.92, 0.16, MID), (0.14, 0.34, LIGHT),
    (0.44, 0.28, MID), (0.68, 0.35, LIGHT), (0.88, 0.44, LIGHT),
    (0.05, 0.52, LIGHT), (0.26, 0.55, MID), (0.61, 0.52, LIGHT),
]


def _five_hour_percent(limits: Optional[List[Dict[str, Any]]]
                       ) -> Optional[float]:
    for window in limits or []:
        if window.get("label") == "5 hour":
            return float(window.get("percent", 0))
    return None


def _scene_state(when: dt.datetime, block: Optional[Dict[str, Any]],
                 five_hour_pct: Optional[float] = None) -> Dict[str, Any]:
    """Pure mood selection for one frame. See module docstring for the
    priority ladder."""
    minute = when.minute
    facing_right = when.hour % 2 == 0
    progress = minute / 59.0
    if not facing_right:
        progress = 1.0 - progress
    base = {
        "mode": "stroll", "progress": progress, "eye": "forward",
        "wave": False, "step": minute % 2, "facing_right": facing_right,
        "book": False, "panic": False, "minute": minute,
    }
    if when.hour < NIGHT_END_HOUR:
        return {**base, "mode": "nightcap", "eye": "blink",
                "progress": 0.5, "step": 0}
    if block is None:
        return {**base, "mode": "sleep", "eye": "blink",
                "progress": 0.5, "step": 0}
    if block.get("remaining_minutes", 0) >= CONFETTI_REMAINING_MINUTES:
        return {**base, "mode": "confetti", "wave": True,
                "progress": 0.5, "step": 0}
    if five_hour_pct is not None and five_hour_pct >= ANXIETY_PERCENT:
        return {**base, "mode": "anxious", "progress": 0.5, "step": 0,
                "panic": five_hour_pct >= PANIC_PERCENT}
    book = any("fable" in str(model) for model in block.get("models", []))
    if when.weekday() >= 5:  # weekend: surf the chart
        return {**base, "mode": "surf", "eye": "look_down",
                "wave": minute % 7 == 0, "book": book, "step": 0}
    burn = float(block.get("cost_per_hour", 0) or 0)
    if burn >= BURN_SPRINT_PER_HOUR:
        mode = "sprint"
    elif burn >= BURN_BRISK_PER_HOUR:
        mode = "brisk"
    else:
        mode = "stroll"
    wave = minute % 7 == 0
    if wave:
        eye = "forward"
    elif minute % 5 == 0:
        eye = "blink"
    else:
        eye = "look_right" if facing_right else "look_left"
    return {**base, "mode": mode, "eye": eye, "wave": wave, "book": book}


def _draw_star(draw: ImageDraw.ImageDraw, x: int, y: int, shade: int) -> None:
    arm = 12
    thickness = 4
    draw.rectangle([x - arm, y - thickness // 2,
                    x + arm, y + thickness // 2], fill=shade)
    draw.rectangle([x - thickness // 2, y - arm,
                    x + thickness // 2, y + arm], fill=shade)


def _draw_clawd_sprite(draw: ImageDraw.ImageDraw, x0: int, y0: int,
                       state: Dict[str, Any],
                       scale: Optional[int] = None) -> None:
    scale = scale if scale is not None else CLAWD_SCALE

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


def _draw_zzz(canvas: Canvas, x: int, y: int, letters=("z", "Z", "Z")) -> None:
    for index, letter in enumerate(letters):
        canvas.draw.text((x + index * 42, y - index * 52),
                         letter, font=canvas.fonts["zzz"], fill=MID)


def _draw_nightcap(canvas: Canvas, x0: int, y0: int) -> None:
    scale = CLAWD_SCALE
    cap_x = x0 + 3 * scale
    for tier in range(4):
        width = (5 - tier) * scale
        canvas.draw.rectangle(
            [cap_x + tier * 10, y0 - (tier + 1) * scale,
             cap_x + tier * 10 + width, y0 - tier * scale], fill=DARK)
    tassel = cap_x + 3 * 10 + 2 * scale
    canvas.draw.rectangle(
        [tassel, y0 - 5 * scale, tassel + 14, y0 - 5 * scale + 14],
        fill=LIGHT)


def _draw_exclaim(canvas: Canvas, x: int, y: int) -> None:
    canvas.draw.rectangle([x, y, x + 14, y + 42], fill=BLACK)
    canvas.draw.rectangle([x, y + 56, x + 14, y + 70], fill=BLACK)


def _draw_sweat(canvas: Canvas, x: int, y: int) -> None:
    canvas.draw.rectangle([x + 6, y, x + 16, y + 12], fill=MID)
    canvas.draw.rectangle([x, y + 12, x + 22, y + 40], fill=MID)


def _draw_speed_lines(canvas: Canvas, x0: int, y0: int,
                      facing_right: bool) -> None:
    for index in range(3):
        line_y = y0 + 24 + index * 40
        length = 90 - index * 14
        if facing_right:
            x1, x2 = x0 - 40 - length, x0 - 40
        else:
            sprite_w = len(CLAWD_BODY[0]) * CLAWD_SCALE
            x1, x2 = x0 + sprite_w + 40, x0 + sprite_w + 40 + length
        canvas.draw.rectangle([x1, line_y, x2, line_y + 8], fill=LIGHT)


def _draw_confetti(canvas: Canvas, x0: int, y0: int, top: int,
                   minute: int) -> None:
    rng = random.Random(minute)
    sprite_w = len(CLAWD_BODY[0]) * CLAWD_SCALE
    for _ in range(30):
        cx = x0 + rng.randint(-160, sprite_w + 160)
        cy = rng.randint(top + 10, y0 + 40)
        # keep confetti off his face
        if x0 + 40 < cx < x0 + sprite_w - 40 and cy > y0 - 30:
            continue
        size = rng.choice((8, 10, 12))
        shade = rng.choice((BLACK, DARK, MID, LIGHT))
        canvas.draw.rectangle([cx, cy, cx + size, cy + size], fill=shade)


def _draw_book(canvas: Canvas, x0: int, y0: int,
               facing_right: bool) -> None:
    scale = CLAWD_SCALE
    sprite_w = len(CLAWD_BODY[0]) * scale
    book_w, book_h = int(3.2 * scale), int(2.2 * scale)
    by = y0 + 2 * scale - 8
    if facing_right:
        bx = x0 + sprite_w - scale // 2
        text_x = bx + book_w + 12
    else:
        bx = x0 - book_w + scale // 2
        text_x = bx - 120
    canvas.draw.rectangle([bx, by, bx + book_w, by + book_h],
                          fill=WHITE, outline=BLACK, width=4)
    canvas.draw.rectangle([bx + book_w // 2 - 2, by,
                           bx + book_w // 2 + 2, by + book_h], fill=BLACK)
    canvas.draw.text((text_x, by + book_h + 6), "a fable",
                     font=canvas.fonts["tiny"], fill=MID)


def _draw_heart(canvas: Canvas, x: int, y: int) -> None:
    half = CLAWD_SCALE // 2
    for row_index, row in enumerate(CLAWD_HEART):
        for col_index, filled in enumerate(row):
            if filled:
                px = x + col_index * half
                py = y + row_index * half
                canvas.draw.rectangle(
                    [px, py, px + half - 1, py + half - 1], fill=DARK)


def _draw_clawd_stage(canvas: Canvas, snapshot: Dict[str, Any],
                      when: Optional[dt.datetime] = None) -> Dict[str, Any]:
    now = when if when is not None else dt.datetime.now()
    state = _scene_state(now, snapshot.get("block"),
                         _five_hour_percent(snapshot.get("limits")))

    top = canvas.y
    bottom = canvas.image.height - LOWER_SECTIONS_HEIGHT
    for x_frac, y_frac, shade in STAGE_STARS:
        _draw_star(canvas.draw,
                   MARGIN + int(x_frac * (canvas.width - 2 * MARGIN)),
                   top + int(y_frac * (bottom - top)), shade)

    ground = bottom - 30
    canvas.draw.rectangle(
        [MARGIN, ground + 6, canvas.width - MARGIN, ground + 9], fill=LIGHT
    )

    if state["mode"] == "surf":
        # Clawd appears on the chart instead; stage keeps just the stars.
        canvas.y = bottom + 10
        canvas.rule()
        return state

    sprite_w = len(CLAWD_BODY[0]) * CLAWD_SCALE
    sprite_h = len(CLAWD_BODY) * CLAWD_SCALE
    track = canvas.width - 2 * MARGIN - sprite_w - 2 * CLAWD_SCALE
    x0 = MARGIN + CLAWD_SCALE + int(track * state["progress"])
    hop = CLAWD_SCALE // 2 if (state["mode"] in WALK_MODES
                               and state["step"]) else 0
    y0 = ground - sprite_h - hop

    if state["mode"] == "sprint":
        _draw_speed_lines(canvas, x0, y0, state["facing_right"])
    _draw_clawd_sprite(canvas.draw, x0, y0, state)

    if state["mode"] in ("sleep", "nightcap"):
        _draw_zzz(canvas, x0 + sprite_w + 16, y0 - 40)
        if state["mode"] == "nightcap":
            _draw_nightcap(canvas, x0, y0)
    elif state["mode"] == "confetti":
        _draw_confetti(canvas, x0, y0, top, state["minute"])
    elif state["mode"] == "anxious":
        center = x0 + sprite_w // 2
        _draw_exclaim(canvas, center - 7, y0 - 100)
        if state["panic"]:
            _draw_exclaim(canvas, center + 21, y0 - 100)
    elif state["mode"] == "sprint":
        edge = x0 + sprite_w + 20 if state["facing_right"] else x0 - 40
        _draw_exclaim(canvas, edge, y0 - 60)
    elif state["mode"] == "brisk":
        edge = x0 + sprite_w - 6 if state["facing_right"] else x0 - 20
        _draw_sweat(canvas, edge, y0 - 44)

    if state["book"] and state["mode"] in WALK_MODES:
        _draw_book(canvas, x0, y0, state["facing_right"])
    if state["mode"] in WALK_MODES and state["minute"] % 13 == 0:
        _draw_heart(canvas, x0 + sprite_w + 14, y0 - 3 * CLAWD_SCALE)

    canvas.y = bottom + 10
    canvas.rule()
    return state


# ------------------------------------------------------------- sections

def _draw_chart(canvas: Canvas, daily: Optional[Dict[str, Any]],
                scene: Optional[Dict[str, Any]] = None) -> None:
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
    peak_index = max(range(len(chart)), key=lambda i: chart[i]["cost"])
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
        surfing_here = (scene is not None
                        and scene.get("mode") == "surf"
                        and index == peak_index)
        if day["cost"] >= 0.005 and not surfing_here:
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
    if scene and scene.get("mode") == "surf":
        # Weekend Easter egg: a mini Clawd peeks from behind the week's
        # tallest bar (his lower body is occluded by the bar itself).
        mini = 14
        sprite_w = len(CLAWD_BODY[0]) * mini
        sprite_h = len(CLAWD_BODY) * mini
        peak_height = int((chart[peak_index]["cost"] / peak)
                          * (CHART_HEIGHT - 40))
        bar_x = MARGIN + peak_index * slot + (slot - bar_width) // 2
        x = bar_x + bar_width // 2 - sprite_w // 2
        x = max(MARGIN, min(x, canvas.width - MARGIN - sprite_w))
        bar_top = baseline - peak_height
        _draw_clawd_sprite(canvas.draw, x,
                           bar_top - int(sprite_h * 0.55),
                           {**scene, "eye": "forward"}, scale=mini)
        canvas.draw.rectangle(
            [bar_x, bar_top, bar_x + bar_width, baseline],
            fill=BLACK if peak_index == len(chart) - 1 else MID)
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
    scene = _draw_clawd_stage(canvas, snapshot, when)
    _draw_chart(canvas, snapshot.get("daily"), scene)
    _draw_month(canvas, snapshot.get("daily"))
    _draw_footer(canvas, footer)
    return canvas.image


def render_png_bytes(snapshot: Dict[str, Any], footer: str = "") -> bytes:
    buffer = io.BytesIO()
    render_dashboard(snapshot, footer=footer).save(buffer, format="PNG")
    return buffer.getvalue()
