"""Collects Claude Code usage data.

Two independent sources, each optional:
  1. ccusage (local JSONL parsing) — costs, tokens, burn rate.
  2. api.anthropic.com/api/oauth/usage — plan limit percentages, same
     numbers the /usage command shows. Auth comes from Claude Code's own
     credentials (~/.claude/.credentials.json or the macOS Keychain).
"""

import datetime as dt
import json
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

import config


def _run(cmd: List[str], timeout: int) -> Optional[str]:
    """Run a command, returning stdout or None on any failure."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _ccusage_cmd() -> List[str]:
    on_path = shutil.which("ccusage")
    if on_path:
        return [on_path]
    # Common install locations that may be missing from this process's PATH.
    candidates = [
        Path.home() / ".npm-global" / "bin" / "ccusage",
        Path("/opt/homebrew/bin/ccusage"),
        Path("/usr/local/bin/ccusage"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return [str(candidate)]
    return ["npx", "-y", "ccusage@latest"]


def _parse_json(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


# ---------------------------------------------------------------- ccusage

def claude_totals(entry: Dict[str, Any]) -> Dict[str, float]:
    """Sum cost/tokens for Claude models only from a ccusage daily entry.

    ccusage aggregates every agent it finds (Gemini, Codex, ...); we only
    want rows whose modelName starts with the Claude prefix.
    """
    cost = 0.0
    tokens = 0
    models: List[str] = []
    for row in entry.get("modelBreakdowns", []):
        name = str(row.get("modelName", ""))
        if not name.startswith(config.CLAUDE_MODEL_PREFIX):
            continue
        cost += float(row.get("cost", 0) or 0)
        tokens += sum(
            int(row.get(key, 0) or 0)
            for key in ("inputTokens", "outputTokens",
                        "cacheCreationTokens", "cacheReadTokens")
        )
        models.append(name)
    return {"cost": cost, "tokens": tokens, "models": models}


def summarize_daily(payload: Dict[str, Any],
                    today: dt.date) -> Dict[str, Any]:
    """Reduce a ccusage `daily --json` payload to dashboard numbers."""
    per_day: Dict[str, Dict[str, float]] = {}
    for entry in payload.get("daily", []):
        period = str(entry.get("period", ""))
        totals = claude_totals(entry)
        if period in per_day:
            merged = per_day[period]
            totals = {
                "cost": merged["cost"] + totals["cost"],
                "tokens": merged["tokens"] + totals["tokens"],
                "models": list(merged["models"]) + list(totals["models"]),
            }
        per_day[period] = totals

    chart: List[Dict[str, Any]] = []
    for offset in range(config.CHART_DAYS - 1, -1, -1):
        day = today - dt.timedelta(days=offset)
        key = day.isoformat()
        totals = per_day.get(key, {"cost": 0.0, "tokens": 0, "models": []})
        chart.append({
            "date": key,
            "label": day.strftime("%a")[0],
            "cost": totals["cost"],
        })

    today_totals = per_day.get(
        today.isoformat(), {"cost": 0.0, "tokens": 0, "models": []}
    )
    month_prefix = today.strftime("%Y-%m")
    month_cost = sum(
        totals["cost"] for period, totals in per_day.items()
        if period.startswith(month_prefix)
    )
    week_cost = sum(day["cost"] for day in chart)

    return {
        "today_cost": today_totals["cost"],
        "today_tokens": today_totals["tokens"],
        "today_models": sorted(set(today_totals["models"])),
        "week_cost": week_cost,
        "month_cost": month_cost,
        "chart": chart,
    }


def summarize_active_block(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Reduce a ccusage `blocks --active --json` payload."""
    blocks = payload.get("blocks", [])
    active = next((block for block in blocks if block.get("isActive")), None)
    if active is None:
        return None
    burn = active.get("burnRate") or {}
    projection = active.get("projection") or {}
    return {
        "cost": float(active.get("costUSD", 0) or 0),
        "tokens": int(active.get("totalTokens", 0) or 0),
        "cost_per_hour": float(burn.get("costPerHour", 0) or 0),
        "remaining_minutes": int(projection.get("remainingMinutes", 0) or 0),
        "projected_cost": float(projection.get("totalCost", 0) or 0),
        "end_time": active.get("endTime"),
        "models": [
            model for model in active.get("models", [])
            if str(model).startswith(config.CLAUDE_MODEL_PREFIX)
        ],
    }


def fetch_ccusage(today: Optional[dt.date] = None) -> Dict[str, Any]:
    """Run ccusage and return {'daily': ..., 'block': ...} (values may be None)."""
    today = today or dt.date.today()
    # First of the month or 7 days back, whichever is earlier, covers both
    # the weekly chart and the month total in a single call.
    month_start = today.replace(day=1)
    week_start = today - dt.timedelta(days=config.CHART_DAYS - 1)
    since = min(month_start, week_start).strftime("%Y%m%d")

    base = _ccusage_cmd()
    daily_payload = _parse_json(_run(
        base + ["daily", "--json", "--since", since],
        config.CCUSAGE_TIMEOUT_SECONDS,
    ))
    block_payload = _parse_json(_run(
        base + ["blocks", "--active", "--json"],
        config.CCUSAGE_TIMEOUT_SECONDS,
    ))

    return {
        "daily": summarize_daily(daily_payload, today) if daily_payload else None,
        "block": summarize_active_block(block_payload) if block_payload else None,
    }


# ----------------------------------------------------------- plan limits

def _oauth_from_credentials_file() -> Optional[Dict[str, Any]]:
    path = Path.home() / ".claude" / ".credentials.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return data.get("claudeAiOauth")


def _oauth_from_keychain() -> Optional[Dict[str, Any]]:
    raw = _run(
        ["security", "find-generic-password",
         "-s", "Claude Code-credentials", "-w"],
        config.KEYCHAIN_TIMEOUT_SECONDS,
    )
    data = _parse_json(raw)
    if data is None:
        return None
    return data.get("claudeAiOauth")


# The macOS keychain locks with the screen; keep the last good read so
# the dashboard keeps working while the Mac is locked overnight.
_oauth_memo: Optional[Dict[str, Any]] = None


def read_oauth() -> Optional[Dict[str, Any]]:
    """Claude Code's own OAuth record (token, expiry, plan metadata)."""
    global _oauth_memo
    oauth = _oauth_from_credentials_file() or _oauth_from_keychain()
    if isinstance(oauth, dict):
        _oauth_memo = oauth
        return oauth
    if _oauth_memo is not None:
        print("[oauth] keychain unavailable — using cached credentials")
    return _oauth_memo


def token_is_fresh(oauth: Dict[str, Any]) -> bool:
    """False only when the stored token is *provably* expired.

    Claude Code rotates this token whenever it talks to the API; we
    never refresh it ourselves (consuming the refresh token could
    invalidate the user's login). Newer Claude Code versions store
    expiresAt as 0 — an unknown expiry means we attempt the request and
    let a 401 hide the section instead of pre-emptively skipping.
    """
    expires_ms = oauth.get("expiresAt")
    if not isinstance(expires_ms, (int, float)) or expires_ms <= 0:
        return True
    expiry = dt.datetime.fromtimestamp(expires_ms / 1000.0)
    return expiry > dt.datetime.now() + dt.timedelta(minutes=1)


def _limit_label(entry: Dict[str, Any]) -> str:
    scope = entry.get("scope") or {}
    model = (scope.get("model") or {}).get("display_name")
    if model:
        return str(model)
    kind = str(entry.get("kind", ""))
    if kind == "session":
        return "5 hour"
    if kind == "weekly_all":
        return "Week"
    return kind.replace("_", " ") or "limit"


def parse_limits(data: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """Normalize the usage endpoint into ordered progress-bar rows.

    Prefers the newer `limits` array (which carries model-scoped windows
    like Fable's weekly meter); falls back to the legacy five_hour /
    seven_day fields.
    """
    windows: List[Dict[str, Any]] = []
    entries = data.get("limits")
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("percent") is None:
                continue
            windows.append({
                "label": _limit_label(entry),
                "percent": float(entry["percent"]),
                "resets_at": entry.get("resets_at"),
            })
    if not windows:
        for key, label in (("five_hour", "5 hour"), ("seven_day", "Week")):
            raw = data.get(key)
            if isinstance(raw, dict) and raw.get("utilization") is not None:
                windows.append({
                    "label": label,
                    "percent": float(raw["utilization"]),
                    "resets_at": raw.get("resets_at"),
                })
    return windows or None


def _fetch_limits_now(oauth: Optional[Dict[str, Any]]):
    """One request to the usage endpoint.

    Returns (limits_or_None, backoff_seconds). A 429's Retry-After
    becomes the backoff — retrying sooner re-trips the penalty window.
    """
    if not oauth:
        print("[limits] no credentials available")
        return None, 0
    if not token_is_fresh(oauth):
        print("[limits] stored token is expired")
        return None, 0
    token = oauth.get("accessToken")
    if not token:
        print("[limits] credential record has no access token")
        return None, 0
    request = urllib.request.Request(
        config.OAUTH_USAGE_URL,
        headers={
            "Authorization": "Bearer " + token,
            "anthropic-beta": config.OAUTH_BETA_HEADER,
            "User-Agent": "e-ink-claude-monitor",
        },
    )
    try:
        with urllib.request.urlopen(
            request, timeout=config.OAUTH_HTTP_TIMEOUT_SECONDS
        ) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        backoff = 0
        if error.code == 429:
            try:
                backoff = int(error.headers.get("Retry-After", "0"))
            except (TypeError, ValueError):
                backoff = 0
        print("[limits] endpoint returned HTTP {}".format(error.code))
        return None, backoff
    except (urllib.error.URLError, OSError, ValueError) as error:
        print("[limits] request failed: {}: {}".format(
            type(error).__name__, error))
        return None, 0
    return parse_limits(data), 0


# Poll throttle + last-good cache: the endpoint 429s under per-minute
# polling, and a momentary failure shouldn't blank the section.
_limits_cache: Dict[str, Any] = {
    "limits": None, "fetched_at": None, "next_attempt_at": None,
}


def fetch_plan_limits(oauth: Optional[Dict[str, Any]] = None,
                      now: Optional[dt.datetime] = None
                      ) -> Optional[List[Dict[str, Any]]]:
    """Rate-limited fetch of the subscription meters with a grace cache."""
    global _limits_cache
    now = now or dt.datetime.now()
    cache = _limits_cache

    if cache["next_attempt_at"] is None or now >= cache["next_attempt_at"]:
        oauth = oauth if oauth is not None else read_oauth()
        fresh, backoff = _fetch_limits_now(oauth)
        wait = max(config.LIMITS_POLL_SECONDS, backoff + 30)
        if fresh is not None:
            print("[limits {}] ok — {} window(s)".format(
                now.strftime("%H:%M:%S"), len(fresh)))
            _limits_cache = {
                "limits": fresh, "fetched_at": now,
                "next_attempt_at": now + dt.timedelta(
                    seconds=config.LIMITS_POLL_SECONDS),
            }
            return fresh
        print("[limits {}] failed (retry-after={}s) — next try in {}s".format(
            now.strftime("%H:%M:%S"), backoff, wait))
        _limits_cache = {
            **cache,
            "next_attempt_at": now + dt.timedelta(seconds=wait),
        }
        cache = _limits_cache

    fetched_at = cache["fetched_at"]
    if fetched_at is not None and (
            (now - fetched_at).total_seconds() < config.LIMITS_GRACE_SECONDS):
        return cache["limits"]
    return None


# -------------------------------------------------------------- snapshot

def build_snapshot() -> Dict[str, Any]:
    """Gather everything the renderer needs. Sections are None when a
    source is unavailable — the renderer degrades gracefully."""
    ccusage_data = fetch_ccusage()
    oauth = read_oauth()
    plan = (oauth or {}).get("subscriptionType")
    limits = fetch_plan_limits(oauth)
    limits_at = _limits_cache.get("fetched_at")
    return {
        "fetched_at": dt.datetime.now().astimezone().isoformat(),
        "plan": plan.upper() if isinstance(plan, str) else None,
        "limits": limits,
        "limits_as_of": limits_at.isoformat() if limits_at else None,
        "daily": ccusage_data["daily"],
        "block": ccusage_data["block"],
    }
