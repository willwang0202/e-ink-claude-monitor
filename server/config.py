"""Shared constants for the Claude e-ink dashboard server."""

# Kobo Libra 2 native panel resolution (portrait).
SCREEN_WIDTH = 1264
SCREEN_HEIGHT = 1680

DEFAULT_PORT = 8090
DEFAULT_REFRESH_SECONDS = 60

# How many days of history to show in the bar chart.
CHART_DAYS = 7

# Subprocess limits.
CCUSAGE_TIMEOUT_SECONDS = 120
KEYCHAIN_TIMEOUT_SECONDS = 20
OAUTH_HTTP_TIMEOUT_SECONDS = 15

OAUTH_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
OAUTH_BETA_HEADER = "oauth-2025-04-20"

# Only usage rows for these model prefixes count toward the dashboard.
CLAUDE_MODEL_PREFIX = "claude"

# Grayscale palette shared by the renderer and the Clawd scene engine.
GRAY_BLACK = 0
GRAY_DARK = 60
GRAY_MID = 140
GRAY_LIGHT = 210
GRAY_WHITE = 255
PAGE_MARGIN = 56

# Candidate (regular, bold) font pairs, first existing pair wins.
FONT_CANDIDATES = [
    ("/System/Library/Fonts/Supplemental/Arial.ttf",
     "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ("/System/Library/Fonts/Helvetica.ttc",
     "/System/Library/Fonts/Helvetica.ttc"),
    ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf"),
]
MONO_FONT_CANDIDATES = [
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Monaco.ttf",
]
