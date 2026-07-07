"""HTTP server that serves the Claude usage dashboard PNG for the Kobo.

Usage:
  python3 server.py                 # serve on :8090, refresh every 5 min
  python3 server.py --once out.png  # render one PNG and exit
"""

import argparse
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import config
import render
import usage


def local_ip() -> str:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


class DashboardState:
    """Holds the latest rendered PNG; refreshed by a background thread."""

    def __init__(self, port: int, interval: int):
        self.interval = interval
        self.footer = "{}:{}  ·  refresh {}s".format(local_ip(), port, interval)
        self._lock = threading.Lock()
        self._png = b""
        self._snapshot = {}

    def refresh(self) -> None:
        snapshot = usage.build_snapshot()
        png = render.render_png_bytes(snapshot, footer=self.footer)
        with self._lock:
            self._snapshot = snapshot
            self._png = png

    def refresh_forever(self) -> None:
        # main() already did the initial refresh, so sleep first.
        while True:
            time.sleep(self.interval)
            started = time.monotonic()
            try:
                self.refresh()
                print("[refresh] ok in {:.1f}s".format(
                    time.monotonic() - started))
            except Exception as error:  # keep serving the last good image
                print("[refresh] FAILED: {}".format(error))

    @property
    def png(self) -> bytes:
        with self._lock:
            return self._png

    @property
    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._snapshot)


def make_handler(state: DashboardState):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/dashboard.png"):
                self._send(200, "image/png", state.png)
            elif self.path.startswith("/status.json"):
                body = json.dumps(state.snapshot, indent=2).encode("utf-8")
                self._send(200, "application/json", body)
            elif self.path.startswith("/health"):
                self._send(200, "text/plain", b"ok")
            else:
                self._send(404, "text/plain", b"not found")

        def _send(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            print("[http] {} {}".format(self.address_string(), fmt % args))

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=config.DEFAULT_PORT)
    parser.add_argument("--interval", type=int,
                        default=config.DEFAULT_REFRESH_SECONDS,
                        help="seconds between data refreshes")
    parser.add_argument("--once", metavar="OUT_PNG",
                        help="render a single PNG to this path and exit")
    args = parser.parse_args()

    state = DashboardState(args.port, args.interval)

    if args.once:
        state.refresh()
        with open(args.once, "wb") as handle:
            handle.write(state.png)
        print("wrote", args.once)
        return

    print("[startup] first data refresh (may take ~10s)...")
    try:
        state.refresh()
    except Exception as error:
        print("[startup] initial refresh failed: {}".format(error))

    refresher = threading.Thread(target=state.refresh_forever, daemon=True)
    refresher.start()

    server = ThreadingHTTPServer(("0.0.0.0", args.port), make_handler(state))
    print("[startup] serving http://{}:{}/dashboard.png".format(
        local_ip(), args.port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[shutdown]")


if __name__ == "__main__":
    main()
