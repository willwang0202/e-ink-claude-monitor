"""Renders a usage snapshot into an e-ink friendly grayscale PNG.

Layout: header, plan-limit bars, Clawd's stage (see clawd.py for the
scene engine), the 7-day chart, and the month total.
"""

import datetime as dt
import io
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

import clawd
import config
from config import (GRAY_BLACK as BLACK, GRAY_DARK as DARK,
                    GRAY_MID as MID, GRAY_LIGHT as LIGHT,
                    GRAY_WHITE as WHITE, PAGE_MARGIN as MARGIN)

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


def _draw_limits(canvas: Canvas, snapshot: Dict[str, Any]) -> None:
    limits = snapshot.get("limits")
    canvas.section_title("Plan limits")
    if not limits:
        canvas.text(MARGIN, "waiting for the usage API (rate-limited)",
                    "small", fill=MID)
        canvas.advance(64)
        canvas.rule()
        return
    for window in limits:
        reset = _fmt_reset(window.get("resets_at"))
        note = "resets " + reset if reset else ""
        canvas.progress_bar(window["label"], window["percent"], note)
    stale_note = _limits_stale_note(snapshot.get("limits_as_of"))
    if stale_note:
        canvas.text_right(stale_note, "tiny", fill=MID, y=canvas.y - 12)
    canvas.advance(16)
    canvas.rule()


def _limits_stale_note(as_of_iso: Optional[str]) -> str:
    if not as_of_iso:
        return ""
    try:
        as_of = dt.datetime.fromisoformat(as_of_iso)
    except ValueError:
        return ""
    age = (dt.datetime.now() - as_of).total_seconds()
    if age < config.LIMITS_STALE_NOTE_SECONDS:
        return ""
    return "as of " + as_of.strftime("%H:%M")


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
    surfing = scene is not None and scene.get("scene") == "surf"
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
        if day["cost"] >= 0.005 and not (surfing and index == peak_index):
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
    if surfing:
        peak_height = int((chart[peak_index]["cost"] / peak)
                          * (CHART_HEIGHT - 40))
        bar_x = MARGIN + peak_index * slot + (slot - bar_width) // 2
        clawd.draw_chart_peeker(
            canvas, bar_x, bar_width, baseline - peak_height, baseline,
            BLACK if peak_index == len(chart) - 1 else MID, scene)
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
    _draw_limits(canvas, snapshot)
    scene = clawd.draw_stage(canvas, snapshot,
                             height - LOWER_SECTIONS_HEIGHT, when)
    _draw_chart(canvas, snapshot.get("daily"), scene)
    _draw_month(canvas, snapshot.get("daily"))
    _draw_footer(canvas, footer)
    return canvas.image


def render_png_bytes(snapshot: Dict[str, Any], footer: str = "") -> bytes:
    buffer = io.BytesIO()
    render_dashboard(snapshot, footer=footer).save(buffer, format="PNG")
    return buffer.getvalue()
