# Setup

About 30 minutes for the first lamp, 10 for each one after.

---

## 1. Flash MicroPython

Download the **ESP32-S3** build from
[micropython.org/download/ESP32_GENERIC_S3](https://micropython.org/download/ESP32_GENERIC_S3/).

Hold **BOOT** on the XIAO, tap **RESET**, release BOOT, then:

```bash
pip install esptool mpremote
esptool.py --chip esp32s3 erase_flash
esptool.py --chip esp32s3 --baud 921600 write_flash -z 0 ESP32_GENERIC_S3-*.bin
```

Check it took:

```bash
mpremote connect /dev/ttyACM0 exec "import sys; print(sys.implementation)"
```

---

## 2. Register the lamp on TTN

In the [TTN console](https://console.cloud.thethings.network) (choose the
**eu1** cluster):

1. Create an application — one application, both lamps inside it. They
   need to share it so that one lamp's uplink can be routed to the other.
2. **Register end device** → *Manually*.
3. Frequency plan: **Europe 863–870 MHz (SF9 for RX2)**.
4. LoRaWAN version: **1.0.3**. Regional parameters: **RP001 1.0.3 rev A**.
5. Activation mode: **OTAA**.
6. Generate a **DevEUI**, **AppEUI** (zeros are fine) and **AppKey**.
7. In the device's **General settings → Network layer**, set class to
   **Class C**.

> Class C matters. The lamp is mains-powered, so it can keep its receiver
> open and take a downlink the moment it is sent. In Class A a downlink
> waits until the lamp next transmits — up to 15 minutes.

Repeat for the second lamp. Same application, different DevEUI.

---

## 3. Configure

```bash
cp firmware/config.example.py firmware/config.py
```

Edit `config.py`:

- `LAMP_ID` — **1** on one lamp, **2** on the other. This is the only
  value that *must* differ.
- `LAMP_NAME` — anything.
- `LORA_DEV_EUI`, `LORA_APP_EUI`, `LORA_APP_KEY` — paste from TTN.
- Pins, LED count, touch — only if your build differs from
  [HARDWARE.md](HARDWARE.md).

`config.py` is gitignored. Keys live on the lamp, never in the repo.

---

## 4. Load it

```bash
./tools/deploy.sh /dev/ttyACM0
```

Or by hand:

```bash
mpremote connect /dev/ttyACM0 mkdir :lamp
mpremote connect /dev/ttyACM0 mkdir :lamp/net
mpremote connect /dev/ttyACM0 cp firmware/main.py :
mpremote connect /dev/ttyACM0 cp firmware/config.py :
mpremote connect /dev/ttyACM0 cp firmware/lamp/*.py :lamp/
mpremote connect /dev/ttyACM0 cp firmware/lamp/net/*.py :lamp/net/
```

---

## 5. Watch it come up

```bash
mpremote connect /dev/ttyACM0 repl
```

Reset the board. You should see:

```
[boot] friend-lights-open ... — lamp 1 (Zurich)
[lorawan] joining...
[lorawan] joined
```

The strip breathes warm white while the join runs — it can take a minute
— then settles into the shared colour.

If it says **join failed**, the lamp is not hearing a gateway. Move it to
a window and try again; see [HARDWARE.md](HARDWARE.md#antenna).

Touch the pad. The colour moves, and within 15 minutes the other lamp
starts drifting toward it.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `no response — check wiring and baud rate` | TX/RX swapped | They cross: XIAO TX → E5 RX |
| `join failed` | No gateway in range | Move to a window; check the [TTN map](https://www.thethingsnetwork.org/map) |
| Joins, but the lamps never agree | Different TTN applications | Both devices must be in **one** application |
| Both lamps same colour, ignoring one's touches | Same `LAMP_ID` | They must differ — the CRDT keys on it |
| Strip lights white, wrong colours | `LED_ORDER` | SK6812 is `GRBW`, WS2812 is `GRB` |
| Touch never fires | Threshold too high | Lower `TOUCH_THRESHOLD` |
| Touch fires constantly | Threshold too low | Raise it; print `TouchPad.read()` to pick |
| Colour changes feel far too slow | Working as intended | Lower `ARRIVAL_FADE_MS` if you want a mirror |

---

## Updating a lamp later

There is **no over-the-air update path on a LoRa-only lamp** — 10 bytes a
message and ten messages a day is not a firmware channel. Updates need
USB, or a temporary WiFi connection (a phone hotspot is enough).

This is why `tests/test_firmware.py` actually runs `main()` rather than
just compiling it: on the original project a bad push could be fixed over
the air, and here it cannot. Run the tests before loading anything onto a
lamp that is about to be posted to a friend.
