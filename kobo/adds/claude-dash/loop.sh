#!/bin/sh
# Claude Dash — fetch/display loop (diagnostic build).
BASE=/mnt/onboard/.adds/claude-dash
RUN=/tmp/claude-dash
FB="$RUN/fbink"
export LD_LIBRARY_PATH="$RUN:${LD_LIBRARY_PATH:-}"

echo $$ > "$RUN/pid"
FAILS=0
LAST_SUM=""

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

# Own IP on the WLAN, e.g. 192.168.0.42 (busybox ifconfig format).
my_ip() {
    ifconfig 2>/dev/null \
        | sed -n 's/.*inet addr:\([0-9.]*\).*/\1/p' \
        | grep -v '^127\.' | head -n 1
}

# The Mac's DHCP address can change. Probe our /24 for a host answering
# /health on the dashboard port and persist the find back into config.sh.
discover_server() {
    PORT="${SERVER_URL##*:}"
    case "$PORT" in *[!0-9]*|"") PORT=8090 ;; esac
    MYIP="$(my_ip)"
    [ -n "$MYIP" ] || return 1
    PREFIX="${MYIP%.*}"
    "$FB" -q -mp -y -2 "Claude Dash: searching $PREFIX.x for server..."
    for LAST in $(seq 1 254); do
        CAND="$PREFIX.$LAST"
        [ "$CAND" = "$MYIP" ] && continue
        if wget -q -T 2 -O /dev/null "http://$CAND:$PORT/health" 2>/dev/null; then
            SERVER_URL="http://$CAND:$PORT"
            sed -i "s|^SERVER_URL=.*|SERVER_URL=\"$SERVER_URL\"|" \
                "$BASE/config.sh" 2>/dev/null
            "$FB" -q -mp -y -2 "Claude Dash: found server at $CAND"
            return 0
        fi
    done
    return 1
}

while : ; do
    # Re-read config every cycle so USB edits apply without a restart.
    SERVER_URL="http://192.168.0.1:8090"
    REFRESH_SECS=60
    FETCH_TIMEOUT=20
    [ -f "$BASE/config.sh" ] && . "$BASE/config.sh"

    if wget -q -T "$FETCH_TIMEOUT" -O "$RUN/dash.png.tmp" \
            "$SERVER_URL/dashboard.png" 2>>"$RUN/log" \
       && [ -s "$RUN/dash.png.tmp" ]; then
        FAILS=0
        SUM="$(md5sum "$RUN/dash.png.tmp" 2>/dev/null | cut -d' ' -f1)"
        # Skip the e-ink flash when the image hasn't changed.
        if [ -z "$SUM" ] || [ "$SUM" != "$LAST_SUM" ]; then
            mv "$RUN/dash.png.tmp" "$RUN/dash.png"
            # -c clear, -f flash (full refresh), -g draw image
            ERR="$("$FB" -c -f \
                -g file="$RUN/dash.png",halign=CENTER,valign=CENTER 2>&1)"
            RC=$?
            diag "stage=draw&rc=$RC&err=$(printf %s "$ERR" | san)"
            log "draw rc=$RC err=$ERR"
            LAST_SUM="$SUM"
        fi
    else
        FAILS=$((FAILS + 1))
        diag "stage=fetchfail&n=$FAILS"
        log "fetch failed ($FAILS) from $SERVER_URL"
        # Leave the last good image up briefly, then try to re-find the
        # server (its DHCP address may have changed).
        if [ "$FAILS" -ge 3 ]; then
            if discover_server; then
                FAILS=0
                continue
            fi
            "$FB" -q -mp -y -2 "Claude Dash: cannot reach server (is WiFi on?)"
        fi
    fi
    sleep "$REFRESH_SECS"
done
