# Hardware

Roughly **€35 a lamp**, no recurring cost.

| Part | ~Cost | Notes |
|---|---|---|
| Seeed XIAO ESP32S3 | €13 | WiFi + BLE + native capacitive touch |
| Seeed Grove Wio-E5 | €14 | LoRaWAN stack lives **on the module** |
| SK6812 RGBW strip | €5 | WS2812 also works, without the white channel |
| 5 V supply | — | USB is fine for a short strip |
| 330 Ω resistor | — | In series on the LED data line |

---

## Wiring

```
XIAO GPIO2 ──[330Ω]── DIN   SK6812 strip
XIAO 5V    ──────────  VCC
XIAO GND   ──────────  GND

XIAO TX (GPIO43) ──►  RX    Wio-E5
XIAO RX (GPIO44) ◄──  TX
XIAO 3V3         ──►  VCC
XIAO GND         ──►  GND

XIAO GPIO4  ──────────  copper pad / foil    (touch, optional)
```

Data flows DIN → DOUT, so connect to the **DIN** end of the strip. If
yours is wired from the far end, set `REVERSE_LEDS = True`.

The touch pad needs **no external resistor** — the ESP32-S3 has hardware
touch channels. A bare copper pad, a strip of foil, or a screw head all
work. `TOUCH_PINS = []` if you don't want one.

All pins are set in `config.py`; the defaults above are just defaults.

---

## Antenna

The Wio-E5 ships with a small antenna, which is fine to start. Before
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
