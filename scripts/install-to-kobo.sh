#!/bin/sh
# Installs the Claude Dash client onto a USB-connected Kobo.
#
# Usage: scripts/install-to-kobo.sh [--skip-nickelmenu]
#
# What it does:
#   1. Copies kobo/adds/* to KOBOeReader/.adds/ (scripts, fbink, menu config)
#   2. Writes the server URL (this Mac's IP) into the on-device config
#   3. Unless --skip-nickelmenu: stages NickelMenu's KoboRoot.tgz in .kobo/
#      (installs automatically after you eject + unplug; safe to re-run)
set -eu

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
KOBO="/Volumes/KOBOeReader"
PORT=8090
NICKELMENU_URL="https://github.com/pgaskin/NickelMenu/releases/latest/download/KoboRoot.tgz"

if [ ! -d "$KOBO/.kobo" ]; then
    echo "ERROR: no Kobo mounted at $KOBO"
    echo "Plug the Kobo in over USB and tap 'Connect' on its screen."
    exit 1
fi

MAC_IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)"
if [ -z "$MAC_IP" ]; then
    echo "ERROR: could not determine this Mac's LAN IP." && exit 1
fi

echo "Kobo found at $KOBO — installing Claude Dash..."
mkdir -p "$KOBO/.adds/claude-dash" "$KOBO/.adds/nm"
cp "$REPO_DIR"/kobo/adds/claude-dash/fbink \
   "$REPO_DIR"/kobo/adds/claude-dash/start.sh \
   "$REPO_DIR"/kobo/adds/claude-dash/loop.sh \
   "$REPO_DIR"/kobo/adds/claude-dash/stop.sh \
   "$KOBO/.adds/claude-dash/"
cp "$REPO_DIR/kobo/adds/nm/claude_dash" "$KOBO/.adds/nm/claude_dash"

# Point the device at this Mac (preserve an existing customized config).
if [ -f "$KOBO/.adds/claude-dash/config.sh" ]; then
    echo "Kept existing config.sh on device."
else
    sed "s|^SERVER_URL=.*|SERVER_URL=\"http://$MAC_IP:$PORT\"|" \
        "$REPO_DIR/kobo/adds/claude-dash/config.sh" \
        > "$KOBO/.adds/claude-dash/config.sh"
    echo "Wrote config.sh pointing at http://$MAC_IP:$PORT"
fi

if [ "${1:-}" != "--skip-nickelmenu" ]; then
    echo "Downloading NickelMenu (menu launcher) installer..."
    curl -fsSL -o "$KOBO/.kobo/KoboRoot.tgz" "$NICKELMENU_URL"
    echo "Staged NickelMenu at .kobo/KoboRoot.tgz (installs on unplug)."
fi

echo ""
echo "Done. Next steps:"
echo "  1. Eject the Kobo in Finder, then unplug it."
echo "     It will reboot once to install NickelMenu."
echo "  2. On the Kobo: connect to your home WiFi."
echo "  3. Settings -> Energy saving: sleep timer 'never' (while docked)."
echo "  4. Start the server on this Mac:  scripts/start-server.sh"
echo "  5. On the Kobo: NickelMenu (top-left 'three lines' menu) ->"
echo "     'Claude Dash Force WiFi' once, then 'Claude Dash Start'."
