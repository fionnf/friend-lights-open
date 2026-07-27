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
> executes `main()`. Nothing has yet met a real Wio-E5 or a real gateway.

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

**→ [docs/SETUP.md](docs/SETUP.md)** walks the whole thing, about an hour.

| | | |
|---|---|---|
| 1 | Build the lamp | XIAO ESP32S3 + Wio-E5 + an LED strip |
| 2 | Flash MicroPython | one USB cable |
| 3 | Set up The Things Network | free; a glossary comes first |
| 4 | Deploy the bridge | 40 lines, pasted into Cloudflare |
| 5 | Configure and load | `cp .env.example .env`, fill it in, `tools/apply_env.py` |
| 6 | First light | |

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
that would produce a broken pair: a shared DevEUI, mismatched JoinEUIs,
or a password WPA2 would silently ignore.

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
| [Seeed Grove Wio-E5](https://www.seeedstudio.com/Grove-LoRa-E5-STM32WLE5JC-p-4867.html) | €14 | LoRaWAN stack runs **on the module** |
| SK6812 RGBW strip | €5 | WS2812 works too, minus the white channel |
| 5 V supply, 330 Ω resistor | — | |

**Get the Wio-E5, not the Wio-SX1262.** The SX1262 is a bare modem, and
MicroPython has no LoRaWAN stack worth betting a project on — you would
be rewriting everything in C++. The E5 carries a complete stack in its
own firmware, driven by AT strings over UART.

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
tools/                      # apply_env, deploy, simulate, preview, test
.env                        # every secret, in one gitignored file
tests/                      # five suites, no dependencies
docs/
```

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
