#!/bin/sh
# Starts the dashboard server (creates the venv on first run).
set -eu
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$REPO_DIR/.venv"

if [ ! -x "$VENV/bin/python" ]; then
    echo "Creating virtualenv..."
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install --quiet pillow
fi

exec "$VENV/bin/python" "$REPO_DIR/server/server.py" "$@"
