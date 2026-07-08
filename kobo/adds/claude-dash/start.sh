#!/bin/sh
# Claude Dash — launcher. FAT32 can't hold an exec bit, so fbink and its
# library are copied to tmpfs and made executable there.
BASE=/mnt/onboard/.adds/claude-dash
RUN=/tmp/claude-dash
export LD_LIBRARY_PATH="$RUN:${LD_LIBRARY_PATH:-}"

mkdir -p "$RUN"

# Kill any previous loop unconditionally — a silently-surviving old
# loop once hid a failure for days.
OLDPID="$(cat "$RUN/pid" 2>/dev/null)"
[ -n "$OLDPID" ] && kill "$OLDPID" 2>/dev/null
rm -f "$RUN/pid"

# Always re-copy so upgrades on the FAT partition take effect.
cp "$BASE/fbink" "$RUN/fbink" || exit 1
cp "$BASE/libfbink.so.1" "$RUN/libfbink.so.1" || exit 1
chmod +x "$RUN/fbink"

# Run the loop from tmpfs: a long-running script held open on the USB
# partition prevents the Kobo from releasing it during USB mode, which
# makes the device serve stale cached files after every sync.
cp "$BASE/loop.sh" "$RUN/loop.sh" || exit 1

"$RUN/fbink" -q -mp -y -3 "Claude Dash: starting..." 2>>"$RUN/log"

nohup sh "$RUN/loop.sh" >>"$RUN/log" 2>&1 &
