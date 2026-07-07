#!/bin/sh
# Claude Dash — launcher. FAT32 can't hold an exec bit, so the fbink
# binary is copied to tmpfs and made executable there.
BASE=/mnt/onboard/.adds/claude-dash
RUN=/tmp/claude-dash

mkdir -p "$RUN"

# Already running? Do nothing.
if [ -f "$RUN/pid" ] && kill -0 "$(cat "$RUN/pid")" 2>/dev/null; then
    exit 0
fi

if [ ! -x "$RUN/fbink" ]; then
    cp "$BASE/fbink" "$RUN/fbink" || exit 1
    chmod +x "$RUN/fbink"
fi

"$RUN/fbink" -q -mp -y -3 "Claude Dash: starting..." 2>/dev/null

nohup sh "$BASE/loop.sh" >"$RUN/log" 2>&1 &
