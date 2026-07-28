# Friend Lights Open

Two lamps in two homes, sharing one colour. Touch yours, and your
friend's drifts toward it over the next hour.

Built for the awkward case: **neither home has WiFi.** The lamps reach
each other over [The Things Network](https://www.thethingsnetwork.org) — a
free, community-run LoRaWAN network — by borrowing the internet
connection of whoever hosts the nearest gateway. No router, no SIM, no
hotspot, no monthly bill.

**~€35 a lamp, once. Nothing after that.**

> **Status:** complete and loadable, **not yet tested on real hardware.**
> Everything is green against stubbed MicroPython, including a test that
> executes `main()`. Nothing has yet met a real radio or a real gateway.

---

## Using a lamp

| | |
|---|---|
| **Tap** the pad | nudge the colour |
| **Hold 1 s** | on / off |
| **Hold 5 s** | toggle the control network |

Each lamp runs its own WiFi network, always on, so you can control it
from a phone without spending one of its ten daily messages:

| | |
|---|---|
| **Network** | `deLENIghted-1` and `deLENIghted-2` |
| **Password** | `lightupleni` |
| **Page** | opens by itself, or **http://192.168.4.1** |

Your phone will warn the network has no internet. Correct — the lamp is
not a router. Stay connected anyway.

---

## Build one

Everything that happens over the USB cable is one command:

```bash
python3 tools/install.py
```

It installs the flashing tools, finds the board, fetches and flashes
MicroPython, asks for your TTN values (or reads `.env` if it exists),
runs every test, loads the firmware, and offers a radio check. **Rerun
it any time** — it looks at what exists and does the next thing, so a
half-finished install or a firmware update is the same command.

What it cannot do for you, because they happen in a browser: clicking
the radio module onto the XIAO and soldering the strip, registering the
two devices with TTN, and pasting the bridge into Cloudflare.

**→ [docs/SETUP.md](docs/SETUP.md)** walks all of it, about an hour:

| | | Covered by `install.py` |
|---|---|---|
| 1 | Build the lamp | no — it clicks and solders nothing |
| 2 | Flash MicroPython | **yes** |
| 3 | Set up The Things Network | no — free account, a glossary comes first |
| 4 | Deploy the bridge | no — 40 lines, pasted into Cloudflare |
| 5 | Configure and load | **yes** |
| 6 | First light | **yes** — it ends with a radio check |

**Check coverage before you order anything.** Look up both addresses on
the [TTN map](https://www.thethingsnetwork.org/map). No gateway in range
at either end means none of this works, and no antenna will fix it.

You can prove everything except the radio with a laptop while you wait
for parts — **→ [docs/TESTING.md](docs/TESTING.md)**.

---

## Your keys live in one file

```bash
cp .env.example .env       # fill in six values from the TTN console
python3 tools/apply_env.py # writes both lamp configs
```

`.env` is gitignored, and so are the configs it generates — there is no
file you have to remember not to commit. It refuses to write anything
that would produce a broken pair: two lamps sharing a session, a
half-filled key, or a password WPA2 would silently ignore.

---

## The idea

A lamp on a network that delivers **ten messages a day**, out of order,
with losses, and no acknowledgements. That sounds like a problem. It
turned out to be the design.

The lamps never send each other colours. Each owns a **grow-only
counter** and only ever increments its own; the colour you see is a
function of the sum. That makes updates commutative, idempotent and
self-healing — a lost message is repaired by the next one, and ten
touches collapse into a single message with nothing lost.

So the colour is not a mirror of your friend's lamp. It is a **joint
artifact** neither of you fully controls, and you can see their influence
in it. Both of you push; the light is where you ended up.

And it arrives *slowly*, over a minute or two. That began as an aesthetic
choice and turned out to be exactly what ten downlinks a day requires.
Colour that arrives like post rather than like a text.

### Zones

The strip splits into zones, each its own colour, reshuffled on every
touch — as in the original project. Set `NUM_LEDS` and `NUM_GROUPS` in
`.env`; `NUM_GROUPS = 1` gives one flat colour.

They cost **nothing on the wire.** Rather than transmitting a colour per
zone on a link that allows ten messages a day, both lamps run the same
small hash over the same agreed counter and arrive at identical stripes.
Convergence comes free: same counter in, same pattern out.

**→ [docs/PROTOCOL.md](docs/PROTOCOL.md)** for how, and why ten a day
shaped all of it.

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

Three things worth knowing before you start:

**Your lamp has no idea gateways exist.** It transmits into the air; any
gateway in earshot forwards it over *its owner's* internet. Nothing to
pair, nothing to configure. That is why neither of you needs internet.

**TTN does not route device-to-device.** Putting both lamps in one
application does *not* make one reach the other — uplinks stop at the
network server. The bridge is the glue that turns lamp A's uplink into
lamp B's downlink.

**Reading is free, writing is rationed.** 30 s of uplink airtime a day,
but only **ten downlinks**. Everything follows from that one number.

---

## What you need

| Part | ~Cost | Notes |
|---|---|---|
| [Seeed XIAO ESP32S3](https://www.seeedstudio.com/XIAO-ESP32S3-p-5627.html) | €13 | WiFi + BLE + native capacitive touch |
| [Wio-SX1262](https://thepihut.com/products/wio-sx1262-for-xiao) | €14 | clips onto the XIAO — no wiring |
| SK6812 RGBW strip | €5 | WS2812 works too, minus the white channel |
| 5 V supply, 330 Ω resistor | — | |

The radio needs no wiring at all: it has a board-to-board connector that
mates with the XIAO's underside, and the firmware works out for itself
which pins it landed on. Press them together until they click.

**A second radio is supported.** The
[Wio-E5](https://www.seeedstudio.com/Grove-LoRa-E5-STM32WLE5JC-p-4867.html)
carries a certified LoRaWAN stack in its own firmware and is driven by
AT strings over four wires — lower risk, but a separate module rather
than something that clips on. `LORA_RADIO = E5` in `.env` and nothing
else changes. The SX1262 is a bare radio, so the stack runs on the ESP32
in Python: ABP rather than OTAA, and Class C, which together mean
nothing in the path is timing-critical.

The crypto for that stack is checked against **RFC 4493 and FIPS-197
test vectors**, because a wrong message integrity code produces a lamp
that transmits perfectly and is silently ignored by the network, with
nothing in the TTN console to say a frame arrived.

**→ [docs/HARDWARE.md](docs/HARDWARE.md)** for wiring, antennas, and why
placement beats any antenna you can buy.

---

## Living with ten messages a day

The catch is that the ten are *your friend's*. Every message you send
becomes a downlink on their lamp, so however freely yours could transmit,
it must not send more than they can receive.

So a lamp sends at most **ten times a day**: a heartbeat every 12 hours
so an idle pair still converges, plus up to eight change-driven messages,
throttled to one every three hours.

Touch it twenty times in an evening and your friend does not get twenty
messages. They get one containing all twenty, and their lamp pulses to
say so. Nothing is lost; it travels together.

**This is the product, not a limitation.** Want a mirror instead? Lower
`ARRIVAL_FADE_MS` and `LORA_MIN_INTERVAL_MS` — and hit the ceiling by
mid-morning. Try `python3 tools/simulate.py --arrival-fade 5` first.

---

## Adding WiFi later

If a home gets internet, set `WIFI_ENABLED = True`. This does **not**
replace LoRa — both transports run at once, carrying identical 10-byte
payloads, with no handover logic at all. If both are up, the friend's
lamp hears the same state twice and the CRDT absorbs it without noticing.
A phone hotspot counts, on iPhone and Android alike.

---

## Layout

```
firmware/
├── main.py                 # the loop
├── config.lamp*.py         # generated from .env, never committed
└── lamp/
    ├── shared_state.py     # the CRDT — the heart of the project
    ├── codec.py            # the 10-byte wire format
    ├── engine.py           # slow arrival, breathing, pulses
    ├── palette.py          # the original project's palette, unchanged
    ├── driver.py  touch.py
    ├── portal.py           # the control network + page
    ├── www/index.html
    └── net/                # transport.py, lorawan_e5.py, mqtt_wifi.py
bridge/worker.js            # uplink -> the other lamp's downlink
.env                        # every secret, in one gitignored file
tests/                      # eight suites, no dependencies
docs/
```

| Tool | |
|---|---|
| `tools/install.py` | **the whole install, one command, rerunnable** |
| `tools/apply_env.py` | write both lamp configs from `.env` |
| `tools/deploy.sh --lamp N` | test, then load a lamp |
| `tools/preview_portal.py` | the lamp's page, on your laptop |
| `tools/simulate.py` | two lamps over a week, in your terminal |
| `tools/test_bridge.py` | prove the Cloudflare bridge works |
| `tools/radio_check.py` | run on the lamp when a radio won't talk |
| `tools/run_bridge_locally.mjs` | run the bridge offline |

| Doc | |
|---|---|
| [SETUP.md](docs/SETUP.md) | build it, start to finish |
| [TESTING.md](docs/TESTING.md) | prove it works with no hardware |
| [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | when it doesn't |
| [HARDWARE.md](docs/HARDWARE.md) | wiring, antennas, placement |
| [FLASHING.md](docs/FLASHING.md) | every way flashing goes wrong |
| [PROTOCOL.md](docs/PROTOCOL.md) | the CRDT, the wire format, the budget |

---

## Tests

```bash
for t in tests/test_*.py; do python3 "$t"; done
```

Or see everything working before the parts arrive:

```bash
python3 tools/preview_portal.py --lamps 2   # the page, on your laptop
python3 tools/simulate.py --hours 168       # a week of two lamps
```

No dependencies, no runner. `tools/deploy.sh` runs them and refuses to
load anything if they fail — because **a LoRa-only lamp has no
over-the-air recovery.** Ten bytes a message is not a firmware channel,
so a boot loop means USB, or the post.

---

## Not built yet

- **Remote viewer.** Seeing your lamps from anywhere. Needs the bridge
  extended with Cloudflare KV: TTN's MQTT has no WebSocket support, so a
  browser cannot talk to it directly.
- **Over-the-air updates.** Possible, but only when a lamp has WiFi.
- **Alarms.** Sunrise/sunset, as in the original project. Needs a clock
  source first.

---

## Licence

MIT — see [LICENSE](LICENSE). Build one, change it, give it to a friend.

Descended from
[linked_friend_lights](https://github.com/fionnf/linked_friend_lights).
