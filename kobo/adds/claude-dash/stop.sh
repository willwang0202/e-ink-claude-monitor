#!/bin/sh
# Claude Dash — stop the refresh loop.
RUN=/tmp/claude-dash
export LD_LIBRARY_PATH="$RUN:${LD_LIBRARY_PATH:-}"

if [ -f "$RUN/pid" ]; then
    kill "$(cat "$RUN/pid")" 2>/dev/null
    rm -f "$RUN/pid"
fi

if [ -x "$RUN/fbink" ]; then
    "$RUN/fbink" -q -mp -y -2 "Claude Dash: stopped"
fi
