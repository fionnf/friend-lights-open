# Friend Lights Open

Two lamps in two homes, sharing one colour. Touch yours, and your
friend's drifts toward it over the next hour.

Built for the awkward case: **neither home has WiFi.** The lamps reach
each other over [The Things Network](https://www.thethingsnetwork.org) — a
free, community-run LoRaWAN network — by borrowing the internet
connection of whoever hosts the nearest gateway. No router, no SIM, no
hotspot, no monthly bill. About **€35 a lamp**, once.

> **Status:** complete and loadable, **not yet tested on real hardware.**
> Everything runs green against stubbed MicroPython, including a smoke
> test that executes `main()`. Nothing has yet met a real Wio-E5 or a
> real gateway. Descended from
> [linked_friend_lights](https://github.com/fionnf/linked_friend_lights).

---

## Contents

- [The idea](#the-idea)
- [How it actually works](#how-it-actually-works)
- [What you need](#what-you-need)
- [1. Build the lamp](#1-build-the-lamp)
- [2. Flash MicroPython](#2-flash-micropython)
- [3. Set up The Things Network](#3-set-up-the-things-network)
- [4. Deploy the bridge](#4-deploy-the-bridge)
- [5. Configure and load](#5-configure-and-load)
- [6. First light](#6-first-light)
- [Living with ten messages a day](#living-with-ten-messages-a-day)
- [Adding WiFi later](#adding-wifi-later)
- [Troubleshooting](#troubleshooting)
- [Flashing in depth](docs/FLASHING.md)
- [Tests](#tests)
- [Not built yet](#not-built-yet)

---

## The idea

A lamp on a network that delivers **ten messages a day**, out of order,
with losses, and no acknowledgements. That sounds like a problem. It
turned out to be the design.

The lamps never send each other colours. Each owns a **grow-only counter**
and only ever increments its own; the colour you see is a function of the
sum. That makes updates commutative, idempotent and self-healing — a lost
message is repaired by the next one, and ten touches collapse into a
single message with nothing lost.

Which means the colour is not a mirror of your friend's lamp. It is a
**joint artifact** neither of you fully controls, and you can see their
influence in it. Both of you push; the light is where you ended up.

And it arrives *slowly* — over a minute or two, not instantly. That began
as an aesthetic choice, and then turned out to be exactly what ten
downlinks a day requires. Colour that arrives like post rather than like
a text.

---

## How it actually works

```
   your lamp                                          their lamp
       │                                                   ▲
       │ uplink (10 bytes)                       downlink  │
       ▼                                                   │
  ┌─────────┐      ┌──────────────┐      ┌────────────┐    │
  │ someone │─────►│     TTN      │─────►│   bridge   │────┘
  │ else's  │      │   network    │      │ (worker)   │
  │ gateway │      │    server    │◄─────│            │
  └─────────┘      └──────────────┘      └────────────┘
```

Three things worth understanding before you start:

**Your lamp has no idea gateways exist.** It transmits into the air. Any
gateway in earshot hears it and forwards it over *its owner's* internet.
No pairing, no association, nothing to configure. That is why neither of
you needs internet at home.

**TTN does not route device-to-device.** This trips everyone up. Putting
both lamps in one application does *not* make one lamp's uplink reach the
other — uplinks go up to the network server and stop. You need a small
piece of glue that turns lamp A's uplink into lamp B's downlink. That is
[the bridge](#4-deploy-the-bridge), and it's about forty lines running
free on Cloudflare.

**Reading is free, writing is rationed.** TTN's Fair Use Policy allows
30 s of uplink airtime and **ten downlinks per device per day**. Your lamp
can *talk* freely and can only *listen* ten times. Everything about the
design follows from that one number.

---

## What you need

| Part | ~Cost | Notes |
|---|---|---|
| [Seeed XIAO ESP32S3](https://www.seeedstudio.com/XIAO-ESP32S3-p-5627.html) | €13 | WiFi + BLE + native capacitive touch |
| [Seeed Grove Wio-E5](https://www.seeedstudio.com/Grove-LoRa-E5-STM32WLE5JC-p-4867.html) | €14 | LoRaWAN stack runs **on the module** |
| SK6812 RGBW strip | €5 | WS2812 works too, without the white channel |
| 5 V supply | — | USB is fine for a short strip |
| 330 Ω resistor | — | In series on the LED data line |

**Get the Wio-E5, not the Wio-SX1262.** The SX1262 is a bare modem, and
MicroPython has no LoRaWAN stack worth betting a project on — you'd be
rewriting everything in C++. The E5 carries a complete, certified stack
in its own firmware and is driven by AT strings over UART. That single
choice is why this project is 1,500 lines of Python instead of a C++ port.

### Before you order: check coverage

Look up **both** addresses on the [TTN map](https://www.thethingsnetwork.org/map),
then cross-check with **TTN Mapper**, which shows *measured* coverage
rather than claimed gateway locations. If either end has no gateway, none
of this works and no antenna will fix it.

---

## 1. Build the lamp

```
XIAO GPIO2 ──[330Ω]── DIN   SK6812 strip
XIAO 5V    ──────────  VCC
XIAO GND   ──────────  GND

XIAO TX (GPIO43) ──►  RX    Wio-E5      ← they cross over
XIAO RX (GPIO44) ◄──  TX
XIAO 3V3         ──►  VCC
XIAO GND         ──►  GND

XIAO GPIO4  ──────────  copper pad / foil    (touch, optional)
```

Data flows DIN → DOUT, so connect to the **DIN** end of the strip. If
yours is wired from the far end, set `REVERSE_LEDS = True`.

The touch pad needs **no external resistor** — the ESP32-S3 has hardware
touch channels. Bare copper, foil, or a screw head all work. Set
`TOUCH_PINS = []` if you don't want one.

⚠️ **Never power the Wio-E5 without its antenna attached.** Transmitting
into an open connector can damage the radio.

More on antennas and placement in [docs/HARDWARE.md](docs/HARDWARE.md) —
the short version is that putting the lamp near a window is worth about
ten times more than any antenna you can buy.

---

## 2. Flash MicroPython

Full walkthrough with per-OS port hunting and every failure mode:
**[docs/FLASHING.md](docs/FLASHING.md)**. The short version:

```bash
pip install esptool mpremote
```

Enter bootloader mode — hold **B** (BOOT), tap **R** (RESET), release
**B**. The port number often changes when you do this, so re-check it.

```bash
esptool.py --chip esp32s3 --port /dev/ttyACM0 erase_flash
esptool.py --chip esp32s3 --port /dev/ttyACM0 --baud 921600 \
           write_flash -z 0 ESP32_GENERIC_S3-*.bin
```

Grab the image from
[micropython.org](https://micropython.org/download/ESP32_GENERIC_S3/).
Note `-z 0` — the S3 image goes at offset **0**, not `0x1000` like the
older ESP32. Tap **R**, then confirm:

```bash
mpremote connect /dev/ttyACM0 exec "import sys; print(sys.implementation)"
```

> If no serial port appears at all, suspect **the cable** before anything
> else. Plenty of USB-C cables are charge-only.

The **Wio-E5 needs no flashing** — its LoRaWAN AT firmware is already on
it, which is the whole reason for choosing it over a bare SX1262.

---

## 3. Set up The Things Network

Go to the [TTN console](https://console.cloud.thethings.network) and pick
the **eu1 (Europe)** cluster. It's free; the Sandbox plan is what you
want.

### 3a. Create one application

**Applications → Create application.** ID something like
`friend-lights`. Both lamps go in this one application — not because TTN
routes between them (it doesn't), but so the bridge has a single webhook
and API key to work with.

### 3b. Register each lamp

**End devices → Register end device → Enter end device specifics
manually.**

| Field | Value |
|---|---|
| Frequency plan | **Europe 863–870 MHz (SF9 for RX2 — recommended)** |
| LoRaWAN version | **LoRaWAN Specification 1.0.3** |
| Regional Parameters | **RP001 Regional Parameters 1.0.3 revision A** |
| Activation mode | **Over the air activation (OTAA)** |
| JoinEUI / AppEUI | all zeros is fine: `0000000000000000` |
| DevEUI | click **Generate** |
| AppKey | click **Generate** |
| End device ID | `lamp-1` (then `lamp-2` — **remember these**) |

Then open the device → **General settings → Network layer → Advanced MAC
settings** and set **LoRaWAN class: Class C**.

> **Class C is not optional here.** The lamp is plugged into a wall, so it
> can keep its receiver open and take a downlink the moment it is sent. In
> Class A a downlink waits until the lamp next transmits — up to 15
> minutes. Same ten-per-day budget either way; Class C just means they
> arrive when they're sent.

Repeat for lamp 2. Same application, its own DevEUI and AppKey.

Keep the **DevEUI, JoinEUI and AppKey** for each — they go into
`config.py` in step 5.

---

## 4. Deploy the bridge

This is the part that makes two lamps into one lamp. Without it they will
join the network happily and never hear each other.

It's stateless, so Cloudflare's free tier runs it forever.

```bash
npm create cloudflare@latest friend-lights-bridge
cd friend-lights-bridge
# replace src/index.js with bridge/worker.js from this repo
npx wrangler secret put SHARED_SECRET      # invent a long random string
npx wrangler deploy
```

Set the lamp IDs to match what you registered (skip if you used the
defaults `lamp-1` / `lamp-2`) by adding to `wrangler.toml`:

```toml
[vars]
LAMPS = "lamp-1,lamp-2"
```

### Point TTN at it

In your application: **Integrations → Webhooks → Add webhook → Custom
webhook.**

| Field | Value |
|---|---|
| Webhook ID | `bridge` |
| Webhook format | **JSON** |
| Base URL | `https://<your-worker>.workers.dev` |
| Downlink API key | click **Generate API key** |
| Enabled event types | tick **Uplink message** only |
| Additional headers | `x-shared-secret` : *the secret you set above* |

The **Downlink API key** matters — without it TTN won't send the
`X-Downlink-APIKey` header and the bridge has no way to reply. The shared
secret matters too: the worker URL is public, and without it anyone could
drive your lamps and burn the daily budget.

> **Why the bridge uses `replace` rather than `push`:** TTN queues
> downlinks. If a lamp is unreachable while five uplinks arrive from its
> friend, `push` would queue five and spend five of that lamp's ten daily
> messages delivering four that are already superseded. Because the
> payload carries absolute counters, the newest one contains everything
> the older ones did — so `replace` collapses the backlog to one. The CRDT
> paying for itself a second time, on a part of the system that isn't even
> on the device.

---

## 5. Configure and load

```bash
cp firmware/config.example.py firmware/config.py
```

Edit it:

```python
LAMP_ID   = 1              # 1 on one lamp, 2 on the other — MUST differ
LAMP_NAME = "Zurich"

LORA_DEV_EUI = "..."       # from the TTN console
LORA_APP_EUI = "0000000000000000"
LORA_APP_KEY = "..."
```

`LAMP_ID` is the only value that *has* to differ between lamps — the CRDT
keys on it, and two lamps sharing an ID will silently ignore each other's
touches. Everything else can be identical.

`config.py` is gitignored. Keys live on the lamp, never in the repo.

```bash
./tools/deploy.sh /dev/ttyACM0
```

That runs the full test suite first and refuses to load anything if it
fails — see [Tests](#tests) for why that guard is there.

---

## 6. First light

```bash
mpremote connect /dev/ttyACM0 repl
```

Reset the board:

```
[boot] friend-lights-open 2026-07-27.1 — lamp 1 (Zurich)
[lorawan] joining...
[lorawan] joined
```

The strip breathes warm white while the join runs — it can take a minute
— then settles into the shared colour.

Now touch the pad. You should see the hue move locally, and in the TTN
console under **Live data** an uplink appear, followed by your worker
scheduling a downlink for the other lamp. Within 15 minutes the other
lamp starts drifting toward it.

---

## Living with ten messages a day

This is the part to explain to whoever you give the second lamp to.

| | Budget |
|---|---|
| Uplink airtime | 30 s/day ≈ 150 messages |
| **Downlinks** | **10/day** ← the real limit |
| Payload | 10 bytes |
| Latency | 2–10 s, plus the deliberate slow fade |

The lamp sends when you touch it — throttled to one message per **15
minutes**, which spends about half the daily airtime — plus one hourly
heartbeat so a lamp that missed everything still converges without anyone
touching anything.

Touch it twenty times in an evening and your friend does not get twenty
messages. They get one, containing all twenty, and their lamp pulses to
say so. Nothing is lost; it just travels together.

**This is the product, not a limitation.** If you want a mirror instead,
drop `ARRIVAL_FADE_MS` and `LORA_MIN_INTERVAL_MS` in `config.py` — but
you'll hit the ten-downlink ceiling by mid-morning and spend the rest of
the day disconnected.

---

## Adding WiFi later

If a home does get internet, set `WIFI_ENABLED = True` and fill in
`MQTT_*`. This does **not** replace LoRa — both transports run at once,
carrying identical 10-byte payloads.

No handover logic, no primary link, no failover. If both are up, the
friend's lamp simply hears the same state twice, and the CRDT absorbs the
duplicate without noticing. That is the entire payoff of paying the
CRDT's design cost up front.

A **phone hotspot** counts, and works on iPhone and Android alike. Details
in [docs/PROTOCOL.md](docs/PROTOCOL.md#running-lorawan-and-wifi-together).

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `no response — check wiring and baud rate` | TX/RX not crossed | XIAO TX → E5 RX, XIAO RX → E5 TX |
| `join failed` | No gateway hearing you | Move to a window; check the [TTN map](https://www.thethingsnetwork.org/map) |
| Joins, uplinks visible in TTN, other lamp never changes | **The bridge isn't running** | Check the worker logs; this is the usual culprit |
| Bridge returns 500 "missing downlink headers" | No Downlink API key on the webhook | Generate one in the webhook settings |
| Bridge returns 403 | Shared secret mismatch | The `x-shared-secret` header must match the worker secret |
| Downlinks queue in TTN but never arrive | Device is Class A | Set **Class C** in Network layer settings |
| Both lamps ignore each other's touches | Same `LAMP_ID` | They must differ |
| Colour jumps backwards after a reboot | Counters weren't persisted | Should not happen — please open an issue |
| Strip lights white, wrong colours | `LED_ORDER` | SK6812 is `GRBW`, WS2812 is `GRB` |
| Touch never fires / fires constantly | Threshold | Print `TouchPad.read()` and set `TOUCH_THRESHOLD` between resting and touched |
| Colour changes feel far too slow | Working as intended | See [above](#living-with-ten-messages-a-day) |

---

## Tests

```bash
python3 tests/test_codec.py         # wire format, and rejecting junk
python3 tests/test_shared_state.py  # CRDT convergence
python3 tests/test_firmware.py      # actually runs main() against stubs
```

No dependencies, no test runner. `tools/deploy.sh` runs all three and
refuses to load anything if they fail.

`test_shared_state.py` is the one that matters: each case is a specific
way the network will misbehave — reordering, duplication, heavy loss,
simultaneous edits, reboots — and asserts the lamps still agree anyway.

`test_firmware.py` **executes** `main()` rather than compiling it. On the
original project a bad push could be fixed over the air. Here it cannot:
ten bytes a message is not a firmware channel, so **a LoRa-only lamp has
no over-the-air recovery** and a boot loop means USB, or the post. Run the
tests before loading anything onto a lamp you're about to give away.

---

## Layout

```
firmware/
├── main.py                 # the loop
├── config.example.py       # copy to config.py; never committed
└── lamp/
    ├── shared_state.py     # the CRDT — the heart of the project
    ├── codec.py            # the 10-byte wire format
    ├── engine.py           # slow arrival, breathing, pulses
    ├── palette.py          # hue -> RGBW
    ├── driver.py           # SK6812/WS2812 via ESP32 RMT
    ├── touch.py            # native ESP32-S3 capacitive touch
    └── net/
        ├── transport.py    # one interface, several radios
        ├── lorawan_e5.py   # Wio-E5 over AT commands
        └── mqtt_wifi.py    # the same 10 bytes over WiFi
bridge/worker.js            # uplink -> the other lamp's downlink
docs/   PROTOCOL.md  HARDWARE.md
tools/  deploy.sh
tests/
```

---

## Not built yet

- **Local control app.** A SoftAP captive portal served by the lamp, for
  when you're in the room — instant, free, and it never touches the
  downlink budget. This is also where TTN key entry should live, so a
  friend never has to edit `config.py` over USB.
- **Remote viewer.** A static page subscribed read-only to TTN's MQTT.
  Reading is unmetered, so showing both lamps live costs nothing.
- **Alarms.** Sunrise/sunset, as in the original project. The clock needs
  a source first — LoRaWAN `DeviceTimeReq`, or the local app.

---

## Licence

MIT — see [LICENSE](LICENSE). Build one, change it, give it to a friend.
