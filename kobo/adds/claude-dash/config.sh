# Claude Dash configuration — edit over USB, takes effect on next Start.
# URL of the dashboard server running on your Mac (no trailing slash).
SERVER_URL="http://192.168.0.167:8090"
# Seconds between screen refreshes.
REFRESH_SECS=60
# Seconds to wait for the download before giving up.
FETCH_TIMEOUT=20

# --- one-shot remote diagnostics v2 (sourced by the running loop every
# --- cycle; retries through the post-USB WiFi-reconnect window and only
# --- disables itself once a report actually reaches the server).
if [ ! -f /tmp/claude-dash/diag2_mark ]; then
    touch /tmp/claude-dash/diag2_mark 2>/dev/null
    (
        R=/tmp/claude-dash
        U="http://192.168.0.167:8090/diag"
        D() { wget -q -T 5 -O /dev/null "$U?$1" 2>/dev/null; }
        S() { tr -c 'A-Za-z0-9._=-' '_' | head -c 180; }
        TRY=0
        while [ $TRY -lt 12 ]; do
            TRY=$((TRY + 1))
            if D "cfg=alive&try=$TRY"; then
                D "cfg=fbink_size&sz=$(wc -c < "$R/fbink" 2>/dev/null | tr -d ' ')"
                D "cfg=rundir&f=$(ls "$R" 2>&1 | tr '\n' '-' | S)"
                D "cfg=looppid&pid=$(cat "$R/pid" 2>/dev/null)"
                D "cfg=ver&v=$("$R/fbink" --version 2>&1 | S)"
                ERR="$(LD_LIBRARY_PATH=$R "$R/fbink" -mp -y -4 'Claude Dash diag: text OK' 2>&1)"
                D "cfg=text&rc=$?&err=$(printf %s "$ERR" | S)"
                ERR="$(LD_LIBRARY_PATH=$R "$R/fbink" -c -f -g file=$R/dash.png,halign=CENTER,valign=CENTER 2>&1)"
                D "cfg=draw&rc=$?&err=$(printf %s "$ERR" | S)"
                D "cfg=done"
                exit 0
            fi
            sleep 10
        done
    ) &
fi
