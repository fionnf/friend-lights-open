# The Pico W bench lamp

Two Raspberry Pi Pico Ws, one WiFi network, the whole lamp working —
before the LoRa boards arrive.

**It is the same firmware.** Not a mock, not a cut-down version: the
same `firmware/lamp/` package, byte for byte. Only `config.py` differs,
and the radio is swapped for WiFi broadcast.

| Real on the bench | Stubbed |
|---|---|
| the CRDT and its convergence | the LoRa radio |
| the 10-byte wire format | TTN, the bridge, the daily budget |
| the colour engine, fades, zones | |
| tap / hold / long-hold gestures | |
| the control page over WiFi | |
| state surviving a reboot | |

So if two Picos agree on a colour here, the logic is right and the only
thing left to prove later is the radio.

**The limit worth knowing up front:** the lamps find each other by
broadcasting to the subnet, so they must be on the **same network**.
This links two lamps on one table, not two homes — which is exactly
what LoRa is for, and exactly what you cannot test yet.

---

## What you need

| | |
|---|---|
| 2 × Raspberry Pi Pico W | the W matters — WiFi |
| 2 × SK6812 or WS2812 strip | any length |
| 2 × push button | optional; the page works without one |
| 330 Ω resistor each | on the LED data line |

The WiFi network is already set: **Gaydar** / `rainb0wLAN`, hardcoded in
`config.lamp1.py` and `config.lamp2.py`. Change it there if you move.

---

## Wiring

```
Pico GP2  ──[330Ω]── DIN   LED strip
Pico VBUS ──────────  VCC        (5 V from USB)
Pico GND  ──────────  GND

Pico GP15 ──── button ──── GND   (optional)
```

The button needs **no resistor** — the firmware enables the RP2040's
internal pull-up, so a bare switch between GP15 and any GND pin is the
whole circuit.

> **Why a button and not a touch pad?** The RP2040 has no capacitive
> touch peripheral — that is an ESP32 feature, and it is why the real
> lamp uses a XIAO. A button gives the identical three gestures, so
> nothing above it can tell the difference.

⚠️ **VBUS is 5 V and only present when USB is plugged in.** For more
than a handful of LEDs, power the strip from its own 5 V supply and
join the grounds — a Pico cannot source much through VBUS.

---

## Install

1. **MicroPython on each Pico W.** In Thonny: hold **BOOTSEL** while
   plugging the board in, then **Tools → Options → Interpreter →
   Install or update MicroPython**, and pick *Raspberry Pi • Pico W*.
   Make sure it says **Pico W** and not plain Pico — the plain build
   has no `network` module and the lamp will not start.

2. **Stage both lamps:**

   ```bash
   python3 tools/prepare_upload.py --pico
   ```

   That writes `upload/pico1/` and `upload/pico2/`.

3. **Upload.** In Thonny: **View → Files**, open `upload/pico1`, select
   everything (**Ctrl-A**), right-click → **Upload to /**. Repeat with
   `upload/pico2` on the second board.

   `upload/pico1` and `upload/pico2` are **not interchangeable** — they
   differ by `LAMP_ID`, and two lamps sharing an id ignore each other's
   messages forever, because the CRDT reads your own id as an echo of
   yourself.

4. **Press the reset**, or in Thonny **Stop/Restart**.

The full Thonny walkthrough, with every failure mode, is in
[docs/FLASHING.md](../docs/FLASHING.md) — everything there applies,
except that the Pico W enters bootloader mode with **BOOTSEL** rather
than the XIAO's B-and-R dance.

---

## What you should see

```
[boot] friend-lights-open 2026-07-27.1 — lamp 1 (pico1)
[wifi] trying Gaydar...
[wifi] connected — 192.168.1.47
[udp] listening on port 41234, broadcasting to 255.255.255.255
[portal] up — join WiFi 'deLENIghted-1-pico'
```

Then, with both running: **press the button on lamp 1** and lamp 2's
strip drifts toward the new colour within a second or two, its zones
reshuffling to match. That is the entire product working.

You can also reach either lamp from a phone: join its own network
(`deLENIghted-1-pico`, password `lightupleni`) and the page opens by
itself, or browse to **http://192.168.4.1**. The Pico W runs its access
point and its connection to *Gaydar* at the same time.

---

## Checking the strip on its own

```bash
mpremote connect /dev/ttyACM0 run strip_test.py
```

Flashes through the colours and prints what each step should look like,
so a wiring fault shows up as a mismatch rather than as a mystery. It
never transmits, so nothing can be damaged. (`radio_check.py` is also
on the board but is **not** for this one — there is no radio.)

---

## When it doesn't work

| Symptom | Cause |
|---|---|
| `no known network in range` | SSID or password — check `config.py`, and that it is 2.4 GHz. The Pico W has no 5 GHz radio |
| WiFi connects, lamps ignore each other | Different networks, or one is on a guest SSID. Guest networks usually block client-to-client traffic, which is exactly what this needs |
| Both lamps light but never agree | Same `LAMP_ID` — you uploaded `pico1` to both |
| `ImportError: no module named 'network'` | Plain Pico firmware, not Pico W |
| Strip wrong colours | `LED_ORDER` — run `strip_test.py` |
| Nothing on the strip | `LED_PIN`, the resistor, or no 5 V. Grounds must be joined |
| Button does nothing | Wrong pin, or wired to 3V3 rather than GND |

**Home network blocks broadcast?** Some routers do, especially with
"AP isolation" or "client isolation" on. Two fixes: turn that setting
off, or run the pair off a phone hotspot, which does not isolate.

---

## Moving to the real lamps later

Nothing to port. The XIAO lamps run this same firmware with a different
`config.py` — `LORA_ENABLED = True`, `UDP_ENABLED = False`, and the TTN
keys. Everything you tuned here (`NUM_LEDS`, `NUM_GROUPS`,
`GROUP_SPREAD`, `ARRIVAL_FADE_MS`) carries straight over.

The one behaviour that will change is *pace*. On WiFi every touch goes
out instantly and unmetered. On LoRa the budget is real — see
[docs/PROTOCOL.md](../docs/PROTOCOL.md) — so a touch arrives in seconds
on a quiet day and waits when the day has been busy. Worth feeling
before you decide it is broken:

```bash
python3 tools/simulate.py --hours 168
```
