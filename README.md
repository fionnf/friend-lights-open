# Friend Lights Open

Two lamps in two homes, sharing one colour. Touch yours, and your
friend's drifts toward it over the next hour.

Built for the awkward case: **neither home has WiFi.** The lamps reach
each other over [The Things Network](https://www.thethingsnetwork.org) —
a free, community-run LoRaWAN network — by borrowing the internet
connection of whoever hosts the nearest gateway. No router, no SIM, no
hotspot, no monthly bill.

> Status: **complete enough to load on a board, untested on real
> hardware.** Everything runs green against stubbed MicroPython, including
> a smoke test that actually executes `main()`. Nothing has yet met a real
> Wio-E5 or a real gateway. Descended from
> [linked_friend_lights](https://github.com/fionnf/linked_friend_lights).

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

Which means the colour is not a mirror of your friend's lamp. It is a
**joint artifact** neither of you fully controls, and you can see their
influence in it. Both of you push; the light is where you ended up.

See [docs/PROTOCOL.md](docs/PROTOCOL.md) for how and why.

---

## Hardware

| Part | ~Cost | Notes |
|---|---|---|
| Seeed XIAO ESP32S3 | €13 | WiFi + BLE + native capacitive touch |
| Seeed Grove Wio-E5 | €14 | LoRaWAN stack runs **on the module**, driven by AT commands |
| SK6812 RGBW strip | €5 | WS2812 works too, without the white channel |
| 5 V supply | — | |

Roughly **€35 a lamp.** No recurring cost.

The Wio-E5 matters: MicroPython has no LoRaWAN stack worth betting a
project on, and the E5 carries a complete one in its own firmware. The
OTAA join, MAC layer, EU868 channel plan and duty-cycle accounting all
happen inside the module, so the lamp just writes AT strings over UART.

Before ordering anything, check both addresses on the
[TTN map](https://www.thethingsnetwork.org/map) and cross-check with
**TTN Mapper**, which shows measured rather than claimed coverage.

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
docs/   PROTOCOL.md  HARDWARE.md  SETUP.md
tools/  deploy.sh
tests/
```

---

## Tests

```bash
python3 tests/test_codec.py         # wire format, and rejecting junk
python3 tests/test_shared_state.py  # CRDT convergence
python3 tests/test_firmware.py      # actually runs main() against stubs
```

No dependencies, no test runner — same convention as the original
project. `tools/deploy.sh` runs all three and refuses to load anything if
they fail.

`test_shared_state.py` is the one that matters: each case is a specific
way the network will misbehave (reordering, duplication, heavy loss,
simultaneous edits, reboots) and asserts the lamps still agree anyway.

`test_firmware.py` executes `main()` rather than compiling it, because
compiling cannot catch a runtime fault — and **a LoRa-only lamp has no
over-the-air recovery.** On the original project a bad push could be
fixed remotely; here a boot loop means USB, or the post.

---

## Setup

1. Flash MicroPython to the XIAO ESP32S3.
2. `cp firmware/config.example.py firmware/config.py` and set `LAMP_ID`
   plus your TTN keys.
3. Register the device in the TTN console as an **OTAA** device, EU868,
   **Class C** (the lamp is mains-powered, so it can listen continuously
   rather than only after transmitting).
4. `./tools/deploy.sh` — runs the tests, then copies everything over.

Full walkthrough including the TTN console steps: [docs/SETUP.md](docs/SETUP.md).

WiFi is optional and off by default. Turning it on doesn't replace
LoRa — both run at once, carrying identical payloads, and the CRDT
absorbs the duplicates. See
[Running LoRaWAN and WiFi together](docs/PROTOCOL.md#running-lorawan-and-wifi-together).

---

## Licence

MIT — see [LICENSE](LICENSE). Build one, change it, give it to a friend.
