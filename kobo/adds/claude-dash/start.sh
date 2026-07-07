#!/bin/sh
# Claude Dash — launcher. FAT32 can't hold an exec bit, so fbink and its
# library are copied to tmpfs and made executable there.
BASE=/mnt/onboard/.adds/claude-dash
RUN=/tmp/claude-dash
export LD_LIBRARY_PATH="$RUN:${LD_LIBRARY_PATH:-}"

mkdir -p "$RUN"

# Already running? Do nothing.
if [ -f "$RUN/pid" ] && kill -0 "$(cat "$RUN/pid")" 2>/dev/null; then
    exit 0
fi

# Always re-copy so a binary upgrade on the FAT partition takes effect.
cp "$BASE/fbink" "$RUN/fbink" || exit 1
cp "$BASE/libfbink.so.1" "$RUN/libfbink.so.1" || exit 1
chmod +x "$RUN/fbink"

"$RUN/fbink" -q -mp -y -3 "Claude Dash: starting..." 2>>"$RUN/log"

nohup sh "$BASE/loop.sh" >>"$RUN/log" 2>&1 &
