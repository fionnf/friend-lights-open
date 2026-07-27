# Troubleshooting

The single most useful distinction: **an uplink visible in TTN with no
matching downlink on the other lamp is always the bridge, never the
radio.** That is the thing people misdiagnose, because a lamp that does
nothing feels like a hardware fault.

Where to look is covered in
[TESTING.md — Reading what happened](TESTING.md#reading-what-happened).

| Symptom | Cause | Fix |
|---|---|---|
| `no response — check wiring and baud rate` | TX/RX not crossed | XIAO TX → E5 RX, XIAO RX → E5 TX |
| `join failed` | No gateway hearing you | Move to a window; check the [TTN map](https://www.thethingsnetwork.org/map) |
| Joins, uplinks visible in TTN, other lamp never changes | **The bridge isn't running** | The single most common failure. Cloudflare → your worker → **Logs** |
| Bridge returns 500 "missing downlink headers" | No Downlink API key on the webhook | Create one under **Application → API keys** with *Write downlink application traffic*, then paste it into the webhook |
| Can't find the API key you made | TTN shows it once, at creation | Delete it and make a new one; there is no way to view it again |
| Bridge returns 403 | Shared secret mismatch | The `x-shared-secret` header must match the worker secret |
| Downlinks queue in TTN but never arrive | Device is Class A | Set **Class C** in Network layer settings |
| Both lamps ignore each other's touches | Same `LAMP_ID` | They must differ |
| Colour jumps backwards after a reboot | Counters weren't persisted | Should not happen — please open an issue |
| Strip lights white, wrong colours | `LED_ORDER` | SK6812 is `GRBW`, WS2812 is `GRB` |
| Touch never fires / fires constantly | Threshold | Print `TouchPad.read()` and set `TOUCH_THRESHOLD` between resting and touched |
| `deLENIghted-…` network doesn't appear | `PORTAL_ENABLED = False`, or toggled off by a 5 s hold | Hold the pad 5 s again; the strip keeps rendering throughout |
| Network appears but the password is rejected | `PORTAL_PASSWORD` under 8 characters | The ESP32 silently ignores short passwords and comes up **open** — the boot log says which mode it used |
| Joined, but no page opened | Phone suppressed the captive-portal prompt | Browse to **http://192.168.4.1** |
| Page loads, buttons do nothing | Lamp busy joining LoRaWAN | Wait for `[lorawan] joined`, then reload |
| Colour changes feel far too slow | Working as intended | See [the README](../README.md#living-with-ten-messages-a-day) |

---