# Hardware

Roughly **€35 a lamp**, no recurring cost.

| Part | ~Cost | Notes |
|---|---|---|
| Seeed XIAO ESP32S3 | €13 | WiFi + BLE + native capacitive touch |
| Seeed Wio-SX1262 | €14 | The radio. Clips straight onto the XIAO |
| SK6812 RGBW strip | €5 | WS2812 also works, without the white channel |
| 5 V supply | — | USB is fine for a short strip |
| 330 Ω resistor | — | In series on the LED data line |

The Wio-E5 is supported as an alternative — see
[Two radios](#two-radios-one-interface) — but it is a separate module on
a UART rather than something that clips on, so the SX1262 is the default.

---

## Wiring

The radio needs none. It has a board-to-board connector that mates with
the XIAO's underside: press the two together until they click. That is
the whole job, and there is nothing to get backwards.

Everything else:

```
XIAO GPIO2 ──[330Ω]── DIN   SK6812 strip
XIAO 5V    ──────────  VCC
XIAO GND   ──────────  GND

XIAO GPIO4  ──────────  copper pad / foil    (touch, optional)
```

If you have the **Wio-E5** instead, it goes on a UART:

```
XIAO TX (GPIO43) ──►  RX    Wio-E5
XIAO RX (GPIO44) ◄──  TX
XIAO 3V3         ──►  VCC
XIAO GND         ──►  GND
```

Data flows DIN → DOUT, so connect to the **DIN** end of the strip. If
yours is wired from the far end, set `REVERSE_LEDS = True`.

The touch pad needs **no external resistor** — the ESP32-S3 has hardware
touch channels. A bare copper pad, a strip of foil, or a screw head all
work. `TOUCH_PINS = []` if you don't want one.

All pins are set in `config.py`, which is generated from `.env` — the
defaults above are just defaults.

### Strip length and zones

Any length works. Put it in `.env`:

```
NUM_LEDS     = 10      # however many you soldered
NUM_GROUPS   = 3       # colour zones; 1 for one flat colour
GROUP_SPREAD = 0.35    # 0 = zones identical, 1 = wildly apart
```

The strip splits into that many zones, each its own colour, reshuffled on
every touch. Both lamps derive identical zones from the shared counter,
so the two strips match even though nothing about the layout is ever
transmitted — see [PROTOCOL.md](PROTOCOL.md#zones-without-paying-for-them).

The two lamps do **not** need the same strip length. Zones are computed
from whatever each lamp has, so a 10-LED lamp and a 60-LED lamp show the
same colours across different numbers of pixels.

Longer strips draw more current: 60 RGBW LEDs at full white is around
3.5 A, which is well past what USB will give you. Power the strip
directly from a 5 V supply rather than through the XIAO.

---

## Two radios, one interface

| | Wio-SX1262 *(default)* | Wio-E5 |
|---|---|---|
| Attaches by | board-to-board, no wiring | 4 wires to a UART |
| LoRaWAN stack | on the ESP32, in Python | **on the module** |
| Driven by | SPI, register level | AT commands |
| Activation | **ABP** | OTAA |
| Config | `LORA_RADIO = SX1262` | `LORA_RADIO = E5` |
| Risk | this project's own stack | certified firmware |

Nothing above the radio can tell which one it has: the CRDT, the codec
and the engine all sit behind one transport interface. The choice is one
line in `.env`, and the keys it then asks you for.

The E5 is the lower-risk board — its stack has shipped in thousands of
products, while the SX1262 path runs a LoRaWAN implementation written
for this project. It is checked against the published RFC 4493 and
FIPS-197 vectors, which is the most that can be done without a gateway,
but it is ours. The SX1262 is the default anyway because it is the
module that clips onto the XIAO.

### Why the SX1262 path uses ABP

An OTAA join means catching the join-accept in a window that opens 5 s
after transmitting and lasts milliseconds. MicroPython's garbage
collector can pause straight through it. **ABP has no join at all**, and
Class C leaves the receiver open continuously — so nothing in the whole
path is timing-critical, which is what makes a Python implementation
sane rather than heroic.

The cost is frame counters: ABP gives the network no way to resync, so
it drops any uplink whose counter it has seen. The firmware reserves
counters in blocks and persists them **before** transmitting, so a power
cut skips forward rather than repeating. If you ever reset the counter
in the TTN console, delete `lorawan_fcnt.json` from the lamp to match.

### Which pins — you don't have to know

**There are two ways to attach a Wio-SX1262 and they share no control
pins.** The XIAO kit mates the boards with a board-to-board connector;
the standalone module goes on the through-hole header. Choosing wrong
gives you SPI that reads back all zeros, which looks exactly like a dead
board.

So the firmware doesn't ask. At startup it probes each in turn — write a
register, read it back — and keeps whichever answers:

```
[sx1262] not on the header module pinout: SPI returned 0000 — check MISO...
[sx1262] found on the B2B kit pinout — NSS 41, RST 42, BUSY 40, DIO1 39
```

| | B2B kit | Header module |
|---|---|---|
| SCK | GPIO7 | GPIO7 |
| MOSI | GPIO9 | GPIO9 |
| MISO | GPIO8 | GPIO8 |
| **NSS** | **GPIO41** | **GPIO4** |
| **RST** | **GPIO42** | GPIO3 |
| **BUSY** | **GPIO40** | GPIO2 |
| **DIO1** | **GPIO39** | GPIO1 |

A pinout is skipped rather than probed if it collides with something the
lamp already uses, since probing means driving those pins and driving
the LED data line writes garbage down the strip. With the default
`LED_PIN = 2` that rules out the header pinout — so **move the LED to
another pin if you have the standalone module**, and the firmware will
find it.

`SX_*_PIN` in `config.py` is tried first, before either guess. It only
matters for a board that is neither of the above.

The B2B column matches Seeed's own RadioLib example for this kit —
`SX1262 radio = new Module(41, 39, 42, 40)`, which is
`Module(cs, irq, rst, gpio)`, so NSS 41, DIO1 39, RST 42, BUSY 40. Two
independent sources agreeing is about as much certainty as is available
without the hardware in hand.

### The TCXO — read this before deciding the board is dead

This module has **no crystal.** Its reference clock is an active TCXO
powered from the SX1262's own **DIO3 pin at 1.8 V**. Until DIO3 is told
to supply that voltage, the chip has no clock — and it fails in the most
confusing way possible: SPI answers, registers read and write correctly,
commands are accepted, and every transmission goes nowhere.

The firmware sets it in `begin()`, before anything else, and calibrates
*after* rather than before — calibrating against a clock that is not yet
running produces a radio that looks configured and transmits nothing
usable.

If you ever port this or compare against another driver, that ordering is
the first thing to check.

### The silicon errata

The SX1262 has documented chip faults (datasheet chapter 15), and the
driver applies the documented fixes: the inverted-IQ receive fix
(15.4 — without it a fraction of all downlinks is silently lost), the
PA clamping fix (15.2 — without it transmit power falls ~5 dB short),
and per-band image calibration (without it the receiver is quietly less
sensitive). None of these ever fails as an error; each just makes the
link worse than the numbers say it should be. `tests/test_sx1262.py`
checks the exact bytes for all of them.

### Check the radio before blaming anything else

```bash
mpremote connect /dev/ttyACM0 run tools/radio_check.py
```

It works from the bottom up and stops at the first failure, so you learn
whether it is wiring, the TCXO, or simply no gateway in range:

1. probes both pinouts and reports which one answered
2. SPI + reset — writes a register and reads it back
3. `begin()` with the TCXO powered
4. transmits a **real LoRaWAN frame** if ABP keys are set, so it should
   appear in the TTN console
5. listens on RX2 for 30 s, to test a queued downlink

⚠️ It transmits. **Attach the antenna first** — transmitting into an open
connector can damage the PA.

If steps 1–4 pass but nothing appears in TTN Live data, the radio is
fine and there is no gateway in range. That is a coverage problem, not a
hardware one.

If step 1 finds nothing on either pinout, it is the connector rather
than a setting — nothing in `config.py` can cause both to fail. Press
the two boards together again until they click.

### A second opinion in C++

If `radio_check.py` fails and you want to know whether it is the
hardware or this project's driver, `tools/validate_hw/validate_hw.ino`
is a small Arduino sketch using **RadioLib** — the same library as
Seeed's own examples for this kit. If the sketch transmits and the
firmware doesn't, the fault is in the Python driver (please open an
issue); if neither does, it is the module, the seating, or the antenna.
Flashing it erases MicroPython; `python3 tools/install.py` puts
everything back.

Why isn't the whole firmware C++, then? Because RadioLib's LoRaWAN
stack is **Class A only** — it listens for a few seconds after each
uplink and is otherwise deaf. This lamp receives at most ten messages a
day at unpredictable times, so it must listen *continuously* (Class C),
and the practical way to have Class C on this module is the stack this
project carries. The sketch stays what it is: a hardware truth-teller,
not a lamp.

## Antenna

Both modules ship with a small antenna, which is fine to start. Before
buying anything better, know that **placement beats antenna by about an
order of magnitude**:

- **Both lamps' antennas vertical.** Polarisation mismatch costs 10–20 dB
  and costs nothing to fix. Most common mistake there is.
- **Near a window.** An external wall is 10–20 dB; modern low-E or
  metallised glazing is 20–30 dB. Since 6 dB doubles your range, moving
  the antenna to a window can be worth 10×. A better antenna is worth
  maybe 1.5×.
- **Away from metal** — radiators, mains wiring, metal lamp bodies. If
  the enclosure is metal the antenna must be outside it.

If you do upgrade, get an **868 MHz half-wave** whip, not a quarter-wave:
a quarter-wave monopole needs a ground plane as a counterpoise and a XIAO
is far too small to be one, so it detunes and you lose the gain you paid
for. Add a u.FL-to-SMA pigtail (~€3) — u.FL connectors are rated for
about 30 mating cycles and snap easily.

⚠️ **Never transmit with no antenna connected.** It can damage the
radio's PA, and it is easy to do by accident on the bench.

### Legal

EU868 is capped at **14 dBm ERP (25 mW)**, with 2.15 dBi as the reference
antenna gain. So a higher-gain antenna does not let you transmit further
— you must reduce power by the same amount. Receive gain is unregulated,
though, and both ends of the link receive, so a better antenna at each
end still helps.

---

## Coverage

Check both addresses on the [TTN map](https://www.thethingsnetwork.org/map),
then cross-check with **TTN Mapper**, which shows *measured* coverage
rather than claimed gateway locations.

You are not short of link budget — 14 dBm into LoRa's ~-137 dBm
sensitivity at SF12 is over 150 dB, which is 100 km in free space. You are
short of line of sight. Everything above is about buildings.

---

## Networks that are not TTN

The lamp doesn't care. If a home does get WiFi later, set `WIFI_ENABLED`
and it runs both transports at once — identical payloads, and the CRDT
absorbs the duplicates without any handover logic. A **phone hotspot**
counts, and works on iPhone and Android alike.

One gotcha if you try that: the Pico W and similar chips often can't see
an iPhone hotspot in a scan even with Maximise Compatibility on. Attempt
the connection directly rather than filtering on scan results.
