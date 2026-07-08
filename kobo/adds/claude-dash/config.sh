# Claude Dash configuration — edit over USB; the loop re-reads this
# file every cycle, so changes apply within one refresh.
# URL of the dashboard server running on your Mac (no trailing slash).
# (scripts/install-to-kobo.sh fills in your Mac's IP automatically; the
# loop also auto-discovers the server on the local /24 if this is wrong)
SERVER_URL="http://192.168.0.1:8090"
# Seconds between screen refreshes.
REFRESH_SECS=60
# Seconds to wait for the download before giving up.
FETCH_TIMEOUT=20
