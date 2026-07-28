# Troubleshooting

The single most useful distinction: **an uplink visible in TTN with no
matching downlink on the other lamp is always the bridge, never the
radio.** That is the thing people misdiagnose, because a lamp that does
nothing feels like a hardware fault.

Where to look is covered in
[TESTING.md — Reading what happened](TESTING.md#reading-what-happened).

| Symptom | Cause | Fix |
|---|---|---|
| `[lora] no SX1262 answered` | Neither pinout replied, so it is the connector, not a setting | Press the boards together until they click, then `tools/radio_check.py` |
| radio_check fails and you suspect the driver itself | — | Flash `tools/validate_hw/validate_hw.ino` (RadioLib, Seeed's own library) for an independent verdict; `install.py` restores MicroPython after |
| Radio found, uplinks never appear in TTN | No gateway in range — the most likely single cause | Move to a window; check the [TTN map](https://www.thethingsnetwork.org/map) |
| Uplinks stop appearing after a reset in the console | Frame counters out of step | Delete `lorawan_fcnt.json` from the lamp so it starts from zero too |
| *(E5)* `no response — check wiring and baud rate` | TX/RX not crossed | XIAO TX → E5 RX, XIAO RX → E5 TX |
| *(E5)* `join failed` | No gateway hearing you | Move to a window; check the [TTN map](https://www.thethingsnetwork.org/map) |
| Uplinks visible in TTN, other lamp never changes | **The bridge isn't running** | The single most common failure. Cloudflare → your worker → **Logs** |
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
| Page loads, buttons do nothing | Lamp busy bringing the radio up | Wait for `[lorawan] radio up`, then reload |
| Colour arrives slower than expected | `ARRIVAL_FADE_MS`, or the daily budget is spent | Lower the fade; see [the README](../README.md#living-with-a-rationed-radio) |

---

---

## Setup and config

Most of this section is avoided entirely by `python3 tools/install.py`,
which detects what exists and does the next thing.

| Symptom | Cause | Fix |
|---|---|---|
| `apply_env.py` says "Not writing anything" | It found something that would break the pair | Read the reason — it names the exact field |
| `No .env yet` | Not created | `python3 tools/install.py` asks for the values, or `cp .env.example .env` |
| Deploy says "No config for lamp N" | `.env` not applied | `python3 tools/apply_env.py` |
| Board resets partway through a deploy | The old firmware's 8 s watchdog — it cannot be stopped, only stretched | Both `install.py` and `deploy.sh` stretch it before copying; rerun either and it completes |
| Real keys showed up in `git status` | `.env` or a lamp config got tracked | `git rm --cached .env firmware/config.lamp*.py` — untracks without deleting |

## The strip

| Symptom | Cause | Fix |
|---|---|---|
| Wrong colours entirely | `LED_ORDER` | SK6812 is `GRBW`, WS2812 is `GRB` |
| Only part of the strip lights | `NUM_LEDS` too low | Set it to what you actually soldered, in `.env` |
| Zones look identical | `GROUP_SPREAD` near 0, or `NUM_GROUPS = 1` | Raise the spread, or add zones |
| Whole strip one colour and you wanted zones | `NUM_GROUPS = 1` | Set it higher, then re-run `apply_env.py` |
| Colours differ between the two lamps | They disagree on the counter | Give it a heartbeat cycle; if it persists, check both are in one TTN application |
| Strip flickers or the lamp resets under load | Strip powered through the XIAO | Feed the strip from 5 V directly — 60 RGBW LEDs at white is ~3.5 A |

## The control page

| Symptom | Cause | Fix |
|---|---|---|
| Network is there, password rejected | `PORTAL_PASSWORD` under 8 characters | The ESP32 silently ignores short ones and comes up **open**; the boot log says which mode it used |
| Joined, no page appeared | Phone suppressed the captive-portal prompt | Browse to **http://192.168.4.1** |
| Page loads, buttons do nothing | Lamp still bringing the radio up | Wait for `[lorawan] radio up`, then reload |
| Slider snaps back | The lamp is the authority and disagreed | It is applying a slow fade — give it a moment |
| Want to check the page without a lamp | | `python3 tools/preview_portal.py --lamps 2` |
