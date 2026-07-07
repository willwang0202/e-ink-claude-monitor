# e-ink-claude-monitor

Turn a **Kobo Libra 2** into an always-on desk monitor for your **Claude Code
usage** — no browser tabs. Your Mac renders a 1264×1680 grayscale PNG; the
Kobo fetches it over WiFi every few minutes and paints it straight to the
e-ink framebuffer with [FBInk](https://github.com/NiLuJe/FBInk).

```
Mac                                        Kobo Libra 2 (stock firmware)
┌─────────────────────────────┐            ┌──────────────────────────┐
│ ccusage (local JSONL)  ──┐  │            │ NickelMenu → start.sh    │
│ oauth/usage (plan %)   ──┼─→│ PNG        │ loop.sh: wget dash.png   │
│ server.py + Pillow     ──┘  │ :8090 ──→  │          fbink -g …      │
└─────────────────────────────┘   WiFi     └──────────────────────────┘
```

## What it shows

- **Plan limit meters** (5-hour session %, weekly %, per-model %) — the same
  numbers `/usage` shows, read best-effort from Claude Code's own OAuth
  credentials (see [Plan limits](#plan-limits) below)
- **Current 5-hour block**: cost so far, tokens, burn rate $/hr, time left,
  projected block cost
- **Today**: API-equivalent cost, tokens, models used
- **Last 7 days**: per-day bar chart + weekly total
- **This month**: API-equivalent total

Data comes from [ccusage](https://github.com/ccusage/ccusage) (16.9k★, parses
`~/.claude/projects/**/*.jsonl` locally). Non-Claude agents that ccusage also
aggregates (Gemini, Codex, …) are filtered out.

## Prior art (research notes)

No existing project does Claude-usage-on-Kobo/Kindle. Closest matches:

| Project | What it is | Why not used directly |
|---|---|---|
| [ccusage](https://github.com/ccusage/ccusage) | Claude Code usage CLI | **Used** as the data engine |
| [emaspa/trmnl-claude](https://github.com/emaspa/trmnl-claude), [ikraamg/trmnl-claude-usage](https://github.com/ikraamg/trmnl-claude-usage) | Claude usage on TRMNL e-ink | TRMNL is dedicated ESP32 hardware, not a Kobo |
| [Mavireck/Kobo-Dashboard](https://github.com/Mavireck/Kobo-Dashboard) | Clock/weather dashboard on Kobo | Needs full Python-on-Kobo install; unmaintained |
| [paulakfleck/kobo-dashboard](https://github.com/paulakfleck/kobo-dashboard) | Calendar/weather PNG via KOReader | Requires KOReader + Docker stack |
| kindle-dash family | Server-rendered PNG → Kindle | Kindle-specific jailbreak tooling |

This repo uses the proven *server-rendered-PNG* pattern with the lightest
possible Kobo client: three busybox shell scripts + one `fbink` binary
(FBInk v1.25.0 official Kobo build, GPLv3 — note that KOReader's bundled
fbink is a *minimal* build without image support and won't work here). Nothing on the Kobo's
root filesystem is modified except by NickelMenu's own standard installer.

## Setup

### 1. Mac server

```sh
scripts/start-server.sh            # http://<your-ip>:8090/dashboard.png
```

First run creates `.venv` and installs Pillow. Useful endpoints:
`/dashboard.png`, `/status.json`, `/health`. Options: `--port`, `--interval`,
`--once out.png` (render one frame and exit — good for previewing).

Optional: auto-start at login with the launchd plist (instructions inside
`scripts/com.eink-claude-monitor.plist`). Speed tip: `npm i -g ccusage`
avoids the `npx` startup tax on every refresh.

### 2. Kobo (one-time, ~3 minutes)

1. Plug the Kobo into the Mac over USB and tap **Connect** on its screen.
2. Run `scripts/install-to-kobo.sh`. It copies the client to `.adds/`,
   points the config at this Mac's IP, and stages the
   [NickelMenu](https://pgaskin.net/NickelMenu/) installer
   (firmware 4.x only — 5.x isn't supported by NickelMenu yet; the Libra 2
   on 4.38 is fine).
3. Eject in Finder, unplug. The Kobo reboots once to install NickelMenu.
4. On the Kobo: join your home WiFi, and set
   **Settings → Energy saving → sleep timer: never** (dashboard mode keeps
   the device awake; keep it on the charger).
5. Open the NickelMenu menu (top-left ⋮ on the home screen):
   - tap **Claude Dash Force WiFi** once (keeps WiFi from napping),
   - tap **Claude Dash Start**.

The screen refreshes every minute (`REFRESH_SECS` in
`.adds/claude-dash/config.sh` on the device, re-read every cycle; the
loop skips the e-ink flash when the image is unchanged). **Claude Dash Stop** returns
you to normal reading; so does a reboot.

### Uninstall

Delete `.adds/claude-dash/` and `.adds/nm/claude_dash` from the Kobo over
USB. NickelMenu itself can stay (it's independently useful) or be removed
with its own uninstaller (create a file named `.adds/nm/uninstall`).

## Plan limits

The limit meters call `api.anthropic.com/api/oauth/usage` with the access
token Claude Code already stores (macOS Keychain item
`Claude Code-credentials`, or `~/.claude/.credentials.json`). The token is
only read, never printed, and **never refreshed** by this project —
refreshing could rotate the refresh token and log your CLI out. When the
stored token is expired the section simply disappears until your next
`claude` session refreshes it. First Keychain access may show a macOS
prompt — click **Always Allow**.

## Development

```sh
.venv/bin/python -m unittest discover -s server/tests -v   # 25 tests
.venv/bin/python server/server.py --once /tmp/preview.png  # render a frame
```

Layout: `server/usage.py` (data), `server/render.py` (Pillow → PNG),
`server/server.py` (HTTP + refresh loop), `kobo/adds/` (device client),
`scripts/` (install/run helpers).

## Troubleshooting

- **"cannot reach server" on the Kobo** — Mac asleep? Firewall blocking
  port 8090 (System Settings → Network → Firewall)? Same WiFi network?
  Check `http://<mac-ip>:8090/health` from a phone browser.
- **Mac IP changed** — edit `SERVER_URL` in `.adds/claude-dash/config.sh`
  over USB, or give the Mac a DHCP reservation.
- **Nickel repaints over the dashboard** — tap Claude Dash Start again, or
  just wait one refresh cycle; the loop redraws on top.
- **Kindle instead of Kobo?** The server half works as-is; replace the
  client with [pascalw/kindle-dash](https://github.com/pascalw/kindle-dash)
  pointed at `/dashboard.png` (Kindle needs a jailbreak).
