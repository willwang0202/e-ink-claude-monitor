"""Clawd — the mascot scene engine.

Canonical 14x8 rectangle sprite from the official clawd-animation spec.
Data-driven priority states always win (night, idle, fresh-window
confetti, limit anxiety); otherwise a seeded 10-minute rotation picks
one scene from a pool, never repeating the previous pick. Gated scenes
join the pool only when they apply (GM flag in the morning, chart
surfing on weekends, Sisyphus only when limit data exists).
"""

import datetime as dt
import random
from typing import Any, Dict, List, Optional

from PIL import ImageDraw

from config import (GRAY_BLACK as BLACK, GRAY_DARK as DARK,
                    GRAY_MID as MID, GRAY_LIGHT as LIGHT,
                    GRAY_WHITE as WHITE, PAGE_MARGIN as MARGIN)

# ---------------------------------------------------------------- sprite

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
EYE_LEFT = (4, 1)
EYE_RIGHT = (9, 1)
EYES = {
    "forward": (0, 0),
    "look_right": (1, 0),
    "look_left": (-1, 0),
    "look_down": (0, 1),
    "blink": None,
}
HEART = [
    [1, 0, 1, 0, 0],
    [1, 1, 1, 1, 0],
    [0, 1, 1, 1, 0],
    [0, 0, 1, 0, 0],
]
SCALE = 22
SPRITE_COLS = len(CLAWD_BODY[0])
SPRITE_ROWS = len(CLAWD_BODY)

# Mood thresholds.
NIGHT_END_HOUR = 7
BURN_BRISK_PER_HOUR = 10.0
BURN_SPRINT_PER_HOUR = 35.0
ANXIETY_PERCENT = 80.0
PANIC_PERCENT = 95.0
CONFETTI_REMAINING_MINUTES = 296
SCENE_BUCKET_MINUTES = 10

STAGE_STARS = [
    (0.08, 0.10), (0.30, 0.05), (0.55, 0.12), (0.76, 0.06), (0.92, 0.16),
    (0.14, 0.34), (0.44, 0.28), (0.68, 0.35), (0.88, 0.44),
]


def sprite_size(scale: int):
    return SPRITE_COLS * scale, SPRITE_ROWS * scale


def draw_sprite(draw: ImageDraw.ImageDraw, x0: int, y0: int,
                state: Dict[str, Any], scale: int = SCALE) -> None:
    def cell(col: float, row: float, shade: int) -> None:
        x = x0 + int(col * scale)
        y = y0 + int(row * scale)
        draw.rectangle([x, y, x + scale - 1, y + scale - 1], fill=shade)

    for row_index, row in enumerate(CLAWD_BODY):
        for col_index, filled in enumerate(row):
            if filled:
                cell(col_index, row_index, MID)
    if state.get("wave"):
        if state.get("facing_right", True):
            cell(13, 1, MID)
            cell(14, 0, MID)
        else:
            cell(0, 1, MID)
            cell(-1, 0, MID)
    eye_offset = EYES[state.get("eye", "forward")]
    if eye_offset is not None:
        dx, dy = eye_offset
        for ex, ey in (EYE_LEFT, EYE_RIGHT):
            cell(ex + dx, ey + dy, BLACK)


# ----------------------------------------------------------- data taps

def _limit_percent(limits, label: str) -> Optional[float]:
    for window in limits or []:
        if window.get("label") == label:
            return float(window.get("percent", 0))
    return None


def _burn(block) -> float:
    return float((block or {}).get("cost_per_hour", 0) or 0)


def _burn_tier(block) -> int:
    burn = _burn(block)
    if burn >= BURN_SPRINT_PER_HOUR:
        return 3
    if burn >= BURN_BRISK_PER_HOUR:
        return 2
    return 1


# -------------------------------------------------------- scene choice

def _scene_pool(when: dt.datetime, snapshot: Dict[str, Any]) -> List[str]:
    pool = ["walk", "walk", "desk", "pair", "train", "snail", "workout",
            "rain", "story"]
    if _limit_percent(snapshot.get("limits"), "5 hour") is not None:
        pool += ["sisyphus", "tide"]
    if _limit_percent(snapshot.get("limits"), "Week") is not None:
        pool.append("garden")
    if snapshot.get("daily"):
        pool.append("tetris")
    if 7 <= when.hour <= 9:
        pool.append("gm")
    if when.weekday() >= 5 and snapshot.get("daily"):
        pool += ["surf", "surf"]
    return pool


def _bucket_pick(bucket: int, pool: List[str]) -> str:
    rng = random.Random(bucket)
    return pool[rng.randrange(len(pool))]


def _rotation_scene(when: dt.datetime, snapshot: Dict[str, Any]) -> str:
    """Seeded pick per 10-minute bucket; never repeats the previous
    bucket's pick, so the stage stays varied but uncluttered."""
    pool = _scene_pool(when, snapshot)
    bucket = int(when.timestamp() // (SCENE_BUCKET_MINUTES * 60))
    pick = _bucket_pick(bucket, pool)
    if pick == _bucket_pick(bucket - 1, pool):
        start = pool.index(pick)
        for offset in range(1, len(pool)):
            candidate = pool[(start + offset) % len(pool)]
            if candidate != pick:
                return candidate
    return pick


def scene_state(when: dt.datetime,
                snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Pure frame state: priority moods first, then the rotation."""
    block = snapshot.get("block")
    pct = _limit_percent(snapshot.get("limits"), "5 hour")
    minute = when.minute
    facing_right = when.hour % 2 == 0
    progress = minute / 59.0
    if not facing_right:
        progress = 1.0 - progress
    base = {
        "scene": "walk", "progress": progress, "eye": "forward",
        "wave": minute % 7 == 0, "step": minute % 2,
        "facing_right": facing_right, "minute": minute,
        "burn_tier": _burn_tier(block), "panic": False,
        "book": any("fable" in str(m)
                    for m in (block or {}).get("models", [])),
    }
    if when.hour < NIGHT_END_HOUR:
        return {**base, "scene": "night", "eye": "blink",
                "progress": 0.35, "step": 0, "wave": False}
    if block is None:
        idle = "fishing" if 17 <= when.hour <= 23 else "sleep"
        bucket = int(when.timestamp() // (SCENE_BUCKET_MINUTES * 60))
        if idle == "fishing" and random.Random(bucket).random() < 0.4:
            idle = "sleep"
        eye = "look_right" if idle == "fishing" else "blink"
        return {**base, "scene": idle, "eye": eye, "progress": 0.4,
                "step": 0, "wave": False}
    if block.get("remaining_minutes", 0) >= CONFETTI_REMAINING_MINUTES:
        return {**base, "scene": "confetti", "wave": True,
                "progress": 0.5, "step": 0}
    if pct is not None and pct >= ANXIETY_PERCENT:
        return {**base, "scene": "anxious", "progress": 0.5, "step": 0,
                "wave": False, "panic": pct >= PANIC_PERCENT}
    scene = _rotation_scene(when, snapshot)
    if base["wave"]:
        eye = "forward"
    elif minute % 5 == 0:
        eye = "blink"
    else:
        eye = "look_right" if facing_right else "look_left"
    return {**base, "scene": scene, "eye": eye}


# ------------------------------------------------------------ helpers

def _star(draw, x, y, shade):
    draw.rectangle([x - 12, y - 2, x + 12, y + 2], fill=shade)
    draw.rectangle([x - 2, y - 12, x + 2, y + 12], fill=shade)


def _zzz(canvas, x, y):
    for index, letter in enumerate(("z", "Z", "Z")):
        canvas.draw.text((x + index * 42, y - index * 52), letter,
                         font=canvas.fonts["zzz"], fill=MID)


def _exclaim(canvas, x, y):
    canvas.draw.rectangle([x, y, x + 14, y + 42], fill=BLACK)
    canvas.draw.rectangle([x, y + 56, x + 14, y + 70], fill=BLACK)


def _walk_x(canvas, geom, state, width, margin_cells=1):
    track = canvas.width - 2 * MARGIN - width - 2 * margin_cells * SCALE
    return MARGIN + margin_cells * SCALE + int(track * state["progress"])


class _Geom:
    def __init__(self, top, bottom):
        self.top = top
        self.bottom = bottom
        self.ground = bottom - 30


# -------------------------------------------------------------- scenes

def _scene_walk(canvas, geom, state, snapshot):
    w, h = sprite_size(SCALE)
    x0 = _walk_x(canvas, geom, state, w)
    hop = SCALE // 2 if state["step"] else 0
    y0 = geom.ground - h - hop
    tier = state["burn_tier"]
    if tier == 3:
        for index in range(3):
            line_y = y0 + 24 + index * 40
            length = 90 - index * 14
            if state["facing_right"]:
                x1, x2 = x0 - 40 - length, x0 - 40
            else:
                x1, x2 = x0 + w + 40, x0 + w + 40 + length
            canvas.draw.rectangle([x1, line_y, x2, line_y + 8], fill=LIGHT)
    draw_sprite(canvas.draw, x0, y0, state)
    if tier == 3:
        edge = x0 + w + 20 if state["facing_right"] else x0 - 40
        _exclaim(canvas, edge, y0 - 60)
    elif tier == 2:
        edge = x0 + w - 6 if state["facing_right"] else x0 - 20
        canvas.draw.rectangle([edge + 6, y0 - 44, edge + 16, y0 - 32],
                              fill=MID)
        canvas.draw.rectangle([edge, y0 - 32, edge + 22, y0 - 4], fill=MID)
    if state["book"]:
        _book(canvas, x0, y0, w, state["facing_right"])
    if state["minute"] % 13 == 0:
        _heart(canvas, x0 + w + 14, y0 - 3 * SCALE)


def _book(canvas, x0, y0, sprite_w, facing_right):
    book_w, book_h = int(3.2 * SCALE), int(2.2 * SCALE)
    by = y0 + 2 * SCALE - 8
    bx = (x0 + sprite_w - SCALE // 2 if facing_right
          else x0 - book_w + SCALE // 2)
    canvas.draw.rectangle([bx, by, bx + book_w, by + book_h],
                          fill=WHITE, outline=BLACK, width=4)
    canvas.draw.rectangle([bx + book_w // 2 - 2, by,
                           bx + book_w // 2 + 2, by + book_h], fill=BLACK)


def _heart(canvas, x, y):
    half = SCALE // 2
    for r, row in enumerate(HEART):
        for c, filled in enumerate(row):
            if filled:
                canvas.draw.rectangle(
                    [x + c * half, y + r * half,
                     x + c * half + half - 1, y + r * half + half - 1],
                    fill=DARK)


def _scene_sleep(canvas, geom, state, snapshot):
    w, h = sprite_size(SCALE)
    x0 = int(canvas.width * 0.4) - w // 2
    y0 = geom.ground - h
    draw_sprite(canvas.draw, x0, y0, state)
    _zzz(canvas, x0 + w + 16, y0 - 40)


def _scene_night(canvas, geom, state, snapshot):
    """Night diorama: constellation of the week's chart, nightcap sleep,
    campfire."""
    daily = snapshot.get("daily") or {}
    chart = daily.get("chart") or []
    if chart:
        peak = max((day["cost"] for day in chart), default=0) or 1.0
        span = canvas.width - 2 * MARGIN - 120
        points = []
        for index, day in enumerate(chart):
            x = MARGIN + 60 + int(span * index / max(len(chart) - 1, 1))
            band = geom.top + 30
            y = band + int((1 - day["cost"] / peak) * 140)
            points.append((x, y))
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            for t in range(12):
                ix = x1 + (x2 - x1) * t // 12
                iy = y1 + (y2 - y1) * t // 12
                canvas.draw.rectangle([ix, iy, ix + 3, iy + 3], fill=LIGHT)
        for x, y in points:
            _star(canvas.draw, x, y, DARK)
    w, h = sprite_size(SCALE)
    x0 = int(canvas.width * 0.3) - w // 2
    y0 = geom.ground - h
    draw_sprite(canvas.draw, x0, y0, state)
    cap_x = x0 + 3 * SCALE
    for tier in range(4):
        width = (5 - tier) * SCALE
        canvas.draw.rectangle(
            [cap_x + tier * 8, y0 - (tier + 1) * SCALE,
             cap_x + tier * 8 + width, y0 - tier * SCALE], fill=DARK)
    _zzz(canvas, x0 + w + 16, y0 - 40)
    fx = int(canvas.width * 0.72)
    canvas.draw.rectangle([fx - 34, geom.ground - 12, fx + 54,
                           geom.ground - 2], fill=DARK)
    for index, (width, shade) in enumerate(((48, MID), (32, DARK),
                                            (18, BLACK))):
        canvas.draw.rectangle(
            [fx + 10 - width // 2, geom.ground - 12 - (index + 1) * 24,
             fx + 10 + width // 2, geom.ground - 12 - index * 24],
            fill=shade)
    for index in range(3):
        sx = fx + 16 + index * 6 + (state["minute"] % 3) * 4
        sy = geom.ground - 104 - index * 26
        canvas.draw.rectangle([sx, sy, sx + 8, sy + 8], fill=LIGHT)


def _scene_fishing(canvas, geom, state, snapshot):
    w, h = sprite_size(SCALE)
    x0 = int(canvas.width * 0.25)
    y0 = geom.ground - h
    draw_sprite(canvas.draw, x0, y0, state)
    for index in range(7):
        canvas.draw.rectangle(
            [x0 + w - 20 + index * 20, y0 - 10 - index * 15,
             x0 + w - 6 + index * 20, y0 - index * 15], fill=DARK)
    tip_x = x0 + w - 13 + 6 * 20
    bob = (state["minute"] % 2) * 8
    canvas.draw.rectangle([tip_x, y0 - 80, tip_x + 3, geom.ground - 28 + bob],
                          fill=LIGHT)
    canvas.draw.rectangle([tip_x - 9, geom.ground - 28 + bob,
                           tip_x + 12, geom.ground - 10 + bob], fill=BLACK)
    for wx in range(MARGIN + 30, canvas.width - MARGIN - 60, 110):
        canvas.draw.rectangle([wx, geom.ground + 16, wx + 44,
                               geom.ground + 20], fill=LIGHT)


def _scene_confetti(canvas, geom, state, snapshot):
    w, h = sprite_size(SCALE)
    x0 = int(canvas.width * 0.5) - w // 2
    y0 = geom.ground - h
    draw_sprite(canvas.draw, x0, y0, state)
    rng = random.Random(state["minute"])
    for _ in range(30):
        cx = x0 + rng.randint(-170, w + 170)
        cy = rng.randint(geom.top + 10, y0 + 40)
        if x0 + 40 < cx < x0 + w - 40 and cy > y0 - 30:
            continue
        size = rng.choice((8, 10, 12))
        canvas.draw.rectangle([cx, cy, cx + size, cy + size],
                              fill=rng.choice((BLACK, DARK, MID, LIGHT)))


def _scene_anxious(canvas, geom, state, snapshot):
    w, h = sprite_size(SCALE)
    x0 = int(canvas.width * 0.5) - w // 2
    y0 = geom.ground - h
    draw_sprite(canvas.draw, x0, y0, state)
    center = x0 + w // 2
    _exclaim(canvas, center - 7, y0 - 100)
    if state["panic"]:
        _exclaim(canvas, center + 21, y0 - 100)


def _scene_desk(canvas, geom, state, snapshot):
    w, h = sprite_size(SCALE)
    x0 = int(canvas.width * 0.35) - w // 2
    y0 = geom.ground - h - 46
    draw_sprite(canvas.draw, x0, y0, {**state, "eye": "look_down"})
    d = canvas.draw
    d.rectangle([x0 - 50, geom.ground - 80, x0 + w + 50, geom.ground - 62],
                fill=DARK)
    d.rectangle([x0 - 38, geom.ground - 62, x0 - 20, geom.ground], fill=DARK)
    d.rectangle([x0 + w + 20, geom.ground - 62, x0 + w + 38, geom.ground],
                fill=DARK)
    lx = x0 + w // 2 + 30
    d.rectangle([lx - 12, geom.ground - 98, lx + 118, geom.ground - 82],
                fill=BLACK)
    d.rectangle([lx, geom.ground - 180, lx + 106, geom.ground - 98],
                fill=WHITE, outline=BLACK, width=4)
    d.rectangle([lx + 12, geom.ground - 162, lx + 76, geom.ground - 154],
                fill=MID)
    d.rectangle([lx + 12, geom.ground - 142, lx + 92, geom.ground - 134],
                fill=LIGHT)
    d.rectangle([lx + 12, geom.ground - 122, lx + 58, geom.ground - 114],
                fill=LIGHT)


def _scene_sisyphus(canvas, geom, state, snapshot):
    pct = _limit_percent(snapshot.get("limits"), "5 hour") or 0.0
    bar_h = 64
    bx = MARGIN + 40
    bw = canvas.width - 2 * MARGIN - 220
    by = geom.ground - bar_h - 40
    d = canvas.draw
    d.rectangle([bx, by, bx + bw, by + bar_h], outline=BLACK, width=5)
    fill_w = int((bw - 10) * min(pct, 100.0) / 100.0)
    d.rectangle([bx + 5, by + 5, bx + 5 + fill_w, by + bar_h - 5],
                fill=BLACK)
    d.text((bx + bw + 20, by + 8), "{:.0f}%".format(pct),
           font=canvas.fonts["body_bold"], fill=BLACK)
    mini = 10
    w, h = sprite_size(mini)
    px = min(bx + 5 + fill_w + 6, bx + bw - w - 6)
    draw_sprite(canvas.draw, px, by + bar_h - h - 4,
                {"eye": "look_left", "wave": True, "facing_right": False},
                scale=mini)
    d.rectangle([px + w // 2, by - 30, px + w // 2 + 10, by - 8], fill=MID)


def _scene_pair(canvas, geom, state, snapshot):
    w, h = sprite_size(SCALE)
    x0 = _walk_x(canvas, geom, state, w + 200)
    hop = SCALE // 2 if state["step"] else 0
    draw_sprite(canvas.draw, x0 + 200, geom.ground - h - hop, state)
    baby = 10
    bw_, bh_ = sprite_size(baby)
    draw_sprite(canvas.draw, x0, geom.ground - bh_ - (baby if hop else 0),
                {**state, "wave": False}, scale=baby)


def _scene_train(canvas, geom, state, snapshot):
    d = canvas.draw
    cars = state["burn_tier"]
    rail_y = geom.ground - 8
    d.rectangle([MARGIN, rail_y + 24, canvas.width - MARGIN, rail_y + 28],
                fill=DARK)
    for tx in range(MARGIN + 10, canvas.width - MARGIN - 30, 52):
        d.rectangle([tx, rail_y + 28, tx + 24, rail_y + 34], fill=LIGHT)
    train_w = 130 + cars * 140
    span = canvas.width - 2 * MARGIN - train_w
    ex = MARGIN + max(0, int(span * state["progress"])) + cars * 140
    d.rectangle([ex, rail_y - 74, ex + 124, rail_y + 24], fill=DARK)
    d.rectangle([ex + 86, rail_y - 116, ex + 124, rail_y - 74], fill=DARK)
    d.rectangle([ex + 8, rail_y - 112, ex + 42, rail_y - 74], fill=MID)
    mini = 7
    draw_sprite(d, ex + 74, rail_y - 116 - 3 * mini,
                {**state, "eye": "look_right", "wave": False}, scale=mini)
    for car in range(cars):
        cx0 = ex - (car + 1) * 140 + 8
        d.rectangle([cx0, rail_y - 58, cx0 + 118, rail_y + 24], fill=MID)
        d.text((cx0 + 44, rail_y - 48), str(cars - car),
               font=canvas.fonts["body_bold"], fill=WHITE)
    for index in range(3):
        d.rectangle([ex + 134 + index * 26, rail_y - 150 - index * 20,
                     ex + 152 + index * 26, rail_y - 134 - index * 20],
                    fill=LIGHT)


def _scene_snail(canvas, geom, state, snapshot):
    d = canvas.draw
    for fx, shade in ((MARGIN + 10, DARK),
                      (canvas.width - MARGIN - 46, BLACK)):
        d.rectangle([fx, geom.ground - 92, fx + 5, geom.ground], fill=shade)
        d.rectangle([fx + 5, geom.ground - 92, fx + 42, geom.ground - 64],
                    fill=shade)
    span = canvas.width - 2 * MARGIN - 260
    snail_frac = state["minute"] / 59.0
    clawd_frac = min(1.0, snail_frac * (0.5 + state["burn_tier"] * 0.45))
    snx = MARGIN + 80 + int(span * snail_frac)
    d.rectangle([snx + 10, geom.ground - 46, snx + 60, geom.ground - 8],
                fill=DARK)
    d.rectangle([snx + 22, geom.ground - 34, snx + 46, geom.ground - 20],
                fill=MID)
    d.rectangle([snx - 16, geom.ground - 18, snx + 20, geom.ground],
                fill=MID)
    d.rectangle([snx - 16, geom.ground - 34, snx - 10, geom.ground - 18],
                fill=MID)
    d.rectangle([snx - 14, geom.ground - 38, snx - 10, geom.ground - 34],
                fill=BLACK)
    w, h = sprite_size(SCALE)
    cx0 = MARGIN + 80 + int(span * clawd_frac)
    hop = SCALE // 2 if state["step"] else 0
    draw_sprite(d, cx0, geom.ground - h - hop,
                {**state, "eye": "look_right"})


def _scene_tetris(canvas, geom, state, snapshot):
    d = canvas.draw
    daily = snapshot.get("daily") or {}
    tokens = int(daily.get("today_tokens", 0) or 0)
    blocks = max(1, min(tokens // 400_000, 14))
    sx = int(canvas.width * 0.55)
    rng = random.Random(dt.date.today().toordinal())
    heights = [0, 0, 0, 0]
    for _ in range(blocks):
        col = rng.randrange(4)
        x0 = sx + col * 62
        y0 = geom.ground - heights[col] - 52
        d.rectangle([x0, y0, x0 + 56, y0 + 48],
                    fill=rng.choice((MID, DARK, LIGHT)))
        heights[col] += 54
    fall_col = state["minute"] % 4
    fall_y = geom.top + 20 + (state["minute"] * 37) % 120
    d.rectangle([sx + fall_col * 62, fall_y, sx + fall_col * 62 + 56,
                 fall_y + 48], fill=BLACK)
    w, h = sprite_size(SCALE)
    draw_sprite(d, MARGIN + 60, geom.ground - h,
                {**state, "eye": "look_right", "wave": False})


def _scene_workout(canvas, geom, state, snapshot):
    d = canvas.draw
    w, h = sprite_size(SCALE)
    x0 = int(canvas.width * 0.45) - w // 2
    lift = SCALE if state["step"] else 0
    y0 = geom.ground - h
    draw_sprite(d, x0, y0, {**state, "wave": False, "eye": "forward"})
    bar_y = y0 - 44 - lift
    for side_x in (x0 - SCALE, x0 + w):
        d.rectangle([side_x, bar_y + 10, side_x + SCALE, y0 + SCALE],
                    fill=MID)
    d.rectangle([x0 - 2 * SCALE, bar_y, x0 + w + 2 * SCALE, bar_y + 10],
                fill=BLACK)
    for px in (x0 - 3 * SCALE, x0 + w + 2 * SCALE):
        d.rectangle([px, bar_y - 26, px + SCALE, bar_y + 36], fill=DARK)
    d.rectangle([x0 + w + 34, y0 - 90, x0 + w + 56, y0 - 62], fill=MID)


def _scene_rain(canvas, geom, state, snapshot):
    d = canvas.draw
    w, h = sprite_size(SCALE)
    x0 = int(canvas.width * 0.4) - w // 2
    y0 = geom.ground - h
    draw_sprite(d, x0, y0, {**state, "wave": False})
    uw = int(w * 1.3)
    ux = x0 - (uw - w) // 2
    for tier in range(4):
        inset = tier * (uw // 8)
        d.rectangle([ux + inset, y0 - 64 - (tier + 1) * 20,
                     ux + uw - inset, y0 - 64 - tier * 20], fill=DARK)
    d.rectangle([x0 + w // 2 - 3, y0 - 64, x0 + w // 2 + 3, y0], fill=DARK)
    rng = random.Random(state["minute"])
    for _ in range(28):
        rx = rng.randint(MARGIN + 10, canvas.width - MARGIN - 20)
        ry = rng.randint(geom.top + 6, geom.ground - 40)
        if ux - 12 < rx < ux + uw + 12 and ry > y0 - 160:
            continue
        d.rectangle([rx, ry, rx + 8, ry + 16], fill=LIGHT)


def _scene_gm(canvas, geom, state, snapshot):
    d = canvas.draw
    w, h = sprite_size(SCALE)
    x0 = int(canvas.width * 0.35) - w // 2
    y0 = geom.ground - h
    draw_sprite(d, x0, y0, {**state, "wave": True, "facing_right": True})
    pole_x = x0 + w + 16
    d.rectangle([pole_x, y0 - 130, pole_x + 6, geom.ground], fill=DARK)
    d.rectangle([pole_x + 6, y0 - 130, pole_x + 140, y0 - 44], fill=BLACK)
    d.text((pole_x + 36, y0 - 118), "GM", font=canvas.fonts["body_bold"],
           fill=WHITE)


def _scene_garden(canvas, geom, state, snapshot):
    d = canvas.draw
    pct = _limit_percent(snapshot.get("limits"), "Week") or 0.0
    max_h = geom.ground - geom.top - 60
    stem_h = max(30, int(max_h * min(pct, 100.0) / 100.0))
    px = int(canvas.width * 0.62)
    d.rectangle([px, geom.ground - stem_h, px + 8, geom.ground], fill=DARK)
    for index in range(1, max(2, stem_h // 55)):
        side = -38 if index % 2 else 8
        ly = geom.ground - index * 52
        d.rectangle([px + side, ly, px + side + 38, ly + 12], fill=MID)
    top_y = geom.ground - stem_h
    if pct >= 90:  # bloom just before the weekly reset
        d.rectangle([px - 16, top_y - 30, px + 26, top_y], fill=DARK)
        d.rectangle([px - 4, top_y - 20, px + 14, top_y - 10], fill=WHITE)
    else:
        d.rectangle([px - 8, top_y - 16, px + 18, top_y], fill=DARK)
    w, h = sprite_size(SCALE)
    x0 = int(canvas.width * 0.22) - w // 2
    y0 = geom.ground - h
    draw_sprite(d, x0, y0, {**state, "eye": "look_right", "wave": True})
    can_x = x0 + w + 4
    d.rectangle([can_x, y0 - 6, can_x + 52, y0 + 30], fill=MID)
    d.rectangle([can_x + 52, y0 + 2, can_x + 78, y0 + 10], fill=MID)
    for index in range(3):
        d.rectangle([can_x + 84 + index * 12, y0 + 24 + index * 22,
                     can_x + 92 + index * 12, y0 + 34 + index * 22],
                    fill=LIGHT)


def _scene_tide(canvas, geom, state, snapshot):
    d = canvas.draw
    pct = _limit_percent(snapshot.get("limits"), "5 hour") or 0.0
    tide_w = int((canvas.width - 2 * MARGIN) * min(pct, 100.0) / 100.0)
    tide_x = canvas.width - MARGIN - tide_w
    d.rectangle([tide_x, geom.ground - 22, canvas.width - MARGIN,
                 geom.ground + 2], fill=LIGHT)
    d.rectangle([tide_x, geom.ground - 22, canvas.width - MARGIN,
                 geom.ground - 14], fill=MID)
    for wx in range(tide_x + 24, canvas.width - MARGIN - 40, 84):
        d.rectangle([wx, geom.ground - 8, wx + 36, geom.ground - 4],
                    fill=WHITE)
    text_x = min(tide_x + 60, canvas.width - MARGIN - 130)
    d.text((text_x, geom.ground - 110), "{:.0f}%".format(pct),
           font=canvas.fonts["body_bold"], fill=DARK)
    w, h = sprite_size(SCALE)
    x0 = max(MARGIN + 10, tide_x - w - 40)
    draw_sprite(d, x0, geom.ground - h,
                {**state, "eye": "look_right", "wave": False})


def _scene_story(canvas, geom, state, snapshot):
    """A four-minute tale, one panel per refresh."""
    d = canvas.draw
    panel = state["minute"] % 4
    captions = ("a box appears...", "what's inside?", "confetti!!",
                "...a new book")
    w, h = sprite_size(SCALE)
    x0 = int(canvas.width * 0.38) - w // 2
    y0 = geom.ground - h
    box_x = x0 + w + 70
    if panel == 0:
        draw_sprite(d, x0, y0, {**state, "eye": "look_right",
                                "wave": False})
        d.rectangle([box_x, geom.ground - 70, box_x + 90, geom.ground],
                    fill=DARK)
    elif panel == 1:
        draw_sprite(d, x0 + 40, y0, {**state, "eye": "look_right",
                                     "wave": True})
        d.rectangle([box_x, geom.ground - 56, box_x + 90, geom.ground],
                    fill=DARK)
        d.rectangle([box_x - 8, geom.ground - 96, box_x + 98,
                     geom.ground - 64], fill=MID)
    elif panel == 2:
        draw_sprite(d, x0 + 20, y0, {**state, "eye": "forward",
                                     "wave": True})
        rng = random.Random(11)
        for _ in range(22):
            fx = rng.randint(x0 - 120, x0 + w + 220)
            fy = rng.randint(geom.top + 10, y0 - 20)
            d.rectangle([fx, fy, fx + 9, fy + 9],
                        fill=rng.choice((BLACK, DARK, MID, LIGHT)))
    else:
        draw_sprite(d, x0, y0, {**state, "eye": "look_down",
                                "wave": False})
        _book_at = x0 + w - SCALE // 2
        d.rectangle([_book_at, y0 + 2 * SCALE - 8,
                     _book_at + int(3.2 * SCALE),
                     y0 + 2 * SCALE - 8 + int(2.2 * SCALE)],
                    fill=WHITE, outline=BLACK, width=4)
    d.text((MARGIN + 10, geom.top + 6), captions[panel],
           font=canvas.fonts["tiny"], fill=MID)


SCENE_PAINTERS = {
    "walk": _scene_walk,
    "sleep": _scene_sleep,
    "night": _scene_night,
    "fishing": _scene_fishing,
    "confetti": _scene_confetti,
    "anxious": _scene_anxious,
    "desk": _scene_desk,
    "sisyphus": _scene_sisyphus,
    "pair": _scene_pair,
    "train": _scene_train,
    "snail": _scene_snail,
    "tetris": _scene_tetris,
    "workout": _scene_workout,
    "rain": _scene_rain,
    "gm": _scene_gm,
    "garden": _scene_garden,
    "tide": _scene_tide,
    "story": _scene_story,
}
# Scenes that draw their own backdrop and skip the star field.
BUSY_SCENES = {"night", "rain", "story", "tetris", "sisyphus", "tide"}


def _battery_gauge(canvas, top: int, percent: float) -> None:
    x = canvas.width - MARGIN - 96
    y = top + 4
    canvas.draw.rectangle([x, y, x + 72, y + 32], outline=DARK, width=4)
    canvas.draw.rectangle([x + 72, y + 9, x + 80, y + 23], fill=DARK)
    fill = int(60 * max(0.0, min(percent, 100.0)) / 100.0)
    canvas.draw.rectangle([x + 6, y + 6, x + 6 + fill, y + 26],
                          fill=DARK if percent > 20 else BLACK)
    canvas.draw.text((x - 66, y + 2), "{:.0f}%".format(percent),
                     font=canvas.fonts["tiny"], fill=MID)


def draw_stage(canvas, snapshot: Dict[str, Any], bottom: int,
               when: Optional[dt.datetime] = None) -> Dict[str, Any]:
    """Draw the mascot stage between canvas.y and `bottom`; returns the
    frame state (the chart uses it for the weekend surf Easter egg)."""
    now = when if when is not None else dt.datetime.now()
    state = scene_state(now, snapshot)
    geom = _Geom(canvas.y, bottom)

    if state["scene"] not in BUSY_SCENES:
        for x_frac, y_frac in STAGE_STARS:
            _star(canvas.draw,
                  MARGIN + int(x_frac * (canvas.width - 2 * MARGIN)),
                  geom.top + int(y_frac * (bottom - geom.top)),
                  LIGHT if (x_frac * 10) % 2 < 1 else MID)

    canvas.draw.rectangle(
        [MARGIN, geom.ground + 6, canvas.width - MARGIN, geom.ground + 9],
        fill=LIGHT)

    if state["scene"] != "surf":  # surf draws on the chart instead
        SCENE_PAINTERS[state["scene"]](canvas, geom, state, snapshot)

    battery = snapshot.get("kobo_battery")
    if battery is not None:
        _battery_gauge(canvas, geom.top, float(battery))

    canvas.y = bottom + 10
    canvas.rule()
    return state


def draw_chart_peeker(canvas, bar_x: int, bar_width: int, bar_top: int,
                      baseline: int, bar_shade: int,
                      state: Dict[str, Any]) -> None:
    """Weekend Easter egg: mini Clawd peeking from behind a chart bar."""
    mini = 14
    w, h = sprite_size(mini)
    x = bar_x + bar_width // 2 - w // 2
    x = max(MARGIN, min(x, canvas.width - MARGIN - w))
    draw_sprite(canvas.draw, x, bar_top - int(h * 0.55),
                {**state, "eye": "forward"}, scale=mini)
    canvas.draw.rectangle([bar_x, bar_top, bar_x + bar_width, baseline],
                          fill=bar_shade)
