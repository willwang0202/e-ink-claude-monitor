#!/bin/sh
# Statusline bridge: captures Claude Code's per-turn payload (which
# includes rate_limits — the plan usage meters) into a file for the
# e-ink dashboard, then delegates rendering to the user's real
# statusline so the terminal HUD is unaffected.
#
# Install: point settings.json statusLine.command at this script.
PAYLOAD="$(cat)"

DASH_PAYLOAD="$PAYLOAD" /usr/bin/python3 -c '
import json, os, tempfile, time
try:
    data = json.loads(os.environ.get("DASH_PAYLOAD", ""))
except ValueError:
    raise SystemExit(0)
limits = data.get("rate_limits")
if not limits:
    raise SystemExit(0)
out = {"captured_at": time.time(), "rate_limits": limits}
target = os.path.expanduser("~/.claude-dash-limits.json")
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(target))
with os.fdopen(fd, "w") as handle:
    json.dump(out, handle)
os.replace(tmp, target)
' 2>/dev/null

# Delegate to the original statusline (claude-hud).
printf '%s' "$PAYLOAD" | bash -c '"/opt/homebrew/bin/node" "$(ls -td ~/.claude/plugins/cache/claude-hud/claude-hud/*/ 2>/dev/null | head -1)dist/index.js"'
