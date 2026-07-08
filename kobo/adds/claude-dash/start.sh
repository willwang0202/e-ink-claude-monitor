#!/bin/sh
# Claude Dash — launcher (diagnostic build: reports each stage to the
# server's log via GET /diag?..., so failures are visible off-device).
BASE=/mnt/onboard/.adds/claude-dash
RUN=/tmp/claude-dash
export LD_LIBRARY_PATH="$RUN:${LD_LIBRARY_PATH:-}"

SERVER_URL="http://192.168.0.167:8090"
[ -f "$BASE/config.sh" ] && . "$BASE/config.sh"

mkdir -p "$RUN"

log() {
    echo "$(date '+%H:%M:%S') $*" >> "$RUN/log"
    [ -d "$BASE" ] && echo "$(date '+%H:%M:%S') $*" >> "$BASE/device.log" 2>/dev/null
}
diag() {
    wget -q -T 5 -O /dev/null "$SERVER_URL/diag?$1" 2>/dev/null
}
san() {
    tr -c 'A-Za-z0-9._=-' '_' | head -c 200
}

diag "stage=start_v5"
log "start.sh v5 (diag)"

# Kill any previous loop unconditionally — a silently-surviving old loop
# has already hidden one failure from us.
OLDPID="$(cat "$RUN/pid" 2>/dev/null)"
[ -n "$OLDPID" ] && kill "$OLDPID" 2>/dev/null
rm -f "$RUN/pid"

if ! cp "$BASE/fbink" "$RUN/fbink" || ! cp "$BASE/libfbink.so.1" "$RUN/libfbink.so.1"; then
    diag "stage=copy&rc=fail"
    log "binary copy FAILED"
    exit 1
fi
chmod +x "$RUN/fbink"

# Run the loop from tmpfs: a long-running script held open on the USB
# partition prevents the Kobo from releasing it during USB mode, which
# makes the device serve stale cached files after every sync.
cp "$BASE/loop.sh" "$RUN/loop.sh" || exit 1

VER="$("$RUN/fbink" --version 2>&1 | san)"
diag "stage=version&v=$VER"
log "fbink --version: $VER"

ERR="$("$RUN/fbink" -mp -y -3 "Claude Dash: starting (diag)..." 2>&1)"
RC=$?
diag "stage=text&rc=$RC&err=$(printf %s "$ERR" | san)"
log "text draw rc=$RC err=$ERR"

nohup sh "$RUN/loop.sh" >>"$RUN/log" 2>&1 &
diag "stage=spawned"
