# Flashing

Getting MicroPython onto a XIAO ESP32S3, and the lamp firmware on top of
it. Allow 20 minutes the first time, 5 minutes for each lamp after.

If something goes wrong, jump to [When it won't
cooperate](#when-it-wont-cooperate) — nearly every failure is one of five
things, and two of them are the cable.

---

## 0. Tools

```bash
pip install esptool mpremote
```

- **esptool** writes the MicroPython firmware image (used once per board).
- **mpremote** copies Python files and opens the REPL (used constantly).

No drivers are needed on macOS or Linux. The ESP32-S3 has native USB and
enumerates as a standard CDC serial device.

**Windows:** usually driverless too. If the board shows as an unknown
device, install the [CP210x
driver](https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers)
— some XIAO batches use it.

**Prefer a GUI?** [Thonny](https://thonny.org) can do all of this
(*Tools → Options → Interpreter → MicroPython (ESP32) → Install or update
firmware*). The commands below are the same operations.

---

## 1. Find the port

Plug the board in.

**macOS**
```bash
ls /dev/cu.usbmodem*
# /dev/cu.usbmodem101
```

**Linux**
```bash
ls /dev/ttyACM*
# /dev/ttyACM0
```

**Windows** — Device Manager → Ports (COM & LPT) → something like `COM7`.

If nothing appears at all, go straight to [When it won't
cooperate](#when-it-wont-cooperate).

> **Linux permissions.** If you get `Permission denied`, add yourself to
> the serial group rather than reaching for `sudo`:
> ```bash
> sudo usermod -a -G dialout $USER   # Arch/Fedora: group is 'uucp'
> ```
> Then **log out and back in** — it doesn't take effect in the current
> shell.

Every command below uses `/dev/ttyACM0`. Substitute your own.

---

## 2. Enter bootloader mode

The XIAO ESP32S3 has two tiny buttons: **B** (BOOT) and **R** (RESET).

1. Hold **B**
2. Tap **R**
3. Release **B**

The board is now in download mode. It will sit there quietly — no LED, no
sign of life. That's correct.

The port often **changes** when it enters bootloader mode (a new
`usbmodem`/`ttyACM` number). Re-check before flashing:

```bash
ls /dev/ttyACM*
```

---

## 3. Erase, then write

Erasing first is not optional in practice — leftover data from Arduino or
a factory Meshtastic image causes MicroPython to boot into confusing
half-states.

```bash
esptool.py --chip esp32s3 --port /dev/ttyACM0 erase_flash
```

Download the **ESP32_GENERIC_S3** `.bin` from
[micropython.org/download/ESP32_GENERIC_S3](https://micropython.org/download/ESP32_GENERIC_S3/)
— take the latest stable release, not a nightly.

```bash
esptool.py --chip esp32s3 --port /dev/ttyACM0 --baud 921600 \
           write_flash -z 0 ESP32_GENERIC_S3-20260602-v1.26.0.bin
```

Note `-z 0` — the ESP32-S3 image is written at offset **0**, not `0x1000`
like the older ESP32. Using the wrong offset produces a board that
enumerates but never boots.

If it fails partway, drop the speed: `--baud 460800`, or `115200`.

Then **tap R** to leave bootloader mode.

---

## 4. Check it took

```bash
mpremote connect /dev/ttyACM0 exec "import sys; print(sys.implementation)"
```

Expect something like:

```
(name='micropython', version=(1, 26, 0), _machine='Generic ESP32S3 module with ESP32S3', ...)
```

Confirm the flash and PSRAM are visible:

```bash
mpremote connect /dev/ttyACM0 exec "import esp; print(esp.flash_size())"
```

~8388608 (8 MB) on a standard XIAO ESP32S3.

---

## 5. Load the lamp firmware

From the repo root, once `.env` is filled in and
`python3 tools/apply_env.py` has been run (see
[SETUP.md step 5](SETUP.md#5-configure-and-load)):

```bash
./tools/deploy.sh --lamp 1 /dev/ttyACM0
```

That runs the test suite first and refuses to deploy if anything fails.

By hand, if you prefer:

```bash
mpremote connect /dev/ttyACM0 mkdir :lamp
mpremote connect /dev/ttyACM0 mkdir :lamp/net
mpremote connect /dev/ttyACM0 mkdir :lamp/www
mpremote connect /dev/ttyACM0 cp firmware/main.py :
mpremote connect /dev/ttyACM0 cp firmware/config.lamp1.py :config.py
mpremote connect /dev/ttyACM0 cp firmware/lamp/*.py :lamp/
mpremote connect /dev/ttyACM0 cp firmware/lamp/net/*.py :lamp/net/
mpremote connect /dev/ttyACM0 cp firmware/lamp/www/index.html :lamp/www/
```

Check what landed:

```bash
mpremote connect /dev/ttyACM0 ls
mpremote connect /dev/ttyACM0 ls :lamp
```

---

## 6. Watch it boot

```bash
mpremote connect /dev/ttyACM0 repl
```

Tap **R**. You want:

```
[boot] friend-lights-open 2026-07-27.1 — lamp 1 
[lorawan] joining...
[lorawan] joined
```

`Ctrl-]` exits the REPL. `Ctrl-C` interrupts the running program — useful
when you need to stop the main loop to poke at something.

---

## 7. The radio

**Neither module gets flashed.** The Wio-SX1262 has no processor in it —
the LoRaWAN stack runs on the XIAO with everything else. The Wio-E5 has
one, but arrives with AT firmware already on it.

### Wio-SX1262

Check it before building anything on top of it:

```bash
mpremote connect /dev/ttyACM0 cp tools/radio_check.py :
mpremote connect /dev/ttyACM0 run radio_check.py
```

⚠️ It transmits — **screw the antenna on first.** Transmitting into an
open connector can damage the PA.

It probes both ways the module can be attached, keeps whichever answers,
and then works upward: SPI, the TCXO, a real LoRaWAN frame, and finally
listening for a downlink. It stops at the first thing that is wrong, so
you learn *which* thing.

If neither pinout answers, it is the connector rather than a setting —
no value in `config.py` can make both fail. Press the two boards
together until they click.

If everything passes but nothing shows up in TTN's Live data, the radio
is fine and there is no gateway in range. That is coverage, not
hardware, and no amount of poking at the board will change it.

### Wio-E5

Worth confirming it's alive and at the expected baud rate before blaming
anything else. With the module wired up and MicroPython running:

```bash
mpremote connect /dev/ttyACM0 repl
```

```python
from machine import UART, Pin
u = UART(1, baudrate=9600, tx=Pin(43), rx=Pin(44))
u.write("AT\r\n");        # expect  +AT: OK
import time; time.sleep(1); print(u.read())

u.write("AT+VER\r\n")     # firmware version
time.sleep(1); print(u.read())
```

`None` back means the module isn't talking. In order of likelihood:

1. **TX/RX not crossed.** XIAO TX → E5 **RX**, XIAO RX → E5 **TX**.
2. **Wrong baud.** 9600 is the factory default, but some modules ship at
   115200. Try both.
3. **Power.** The E5 wants a solid 3V3. Transmit bursts brown out a weak
   supply.

---

## When it won't cooperate

### No serial port appears at all

**The cable.** This is the single most common cause. Many USB-C cables
sold with phones and power banks are **charge-only** — no data lines.
Swap it for one you know carries data. It costs nothing to rule out and
is right more often than anything else on this list.

**Not in bootloader mode.** Hold **B**, tap **R**, release **B**. If the
board has a firmware image that crashes instantly, it may never enumerate
long enough to be seen except in bootloader mode.

**A USB hub.** Try a port directly on the machine.

### `A fatal error occurred: Failed to connect to ESP32-S3`

Re-do the BOOT/RESET dance, then re-check the port number — it changes
when entering bootloader mode. Try `--baud 115200`.

### Flashes fine, but nothing on the REPL

Tap **R** to leave bootloader mode — a freshly flashed board is still
sitting in it.

Also check you used `-z 0` and not `0x1000`.

### Boot loop, or garbage on the serial output

Interrupt before `main.py` runs:

```bash
mpremote connect /dev/ttyACM0
# then hit Ctrl-C repeatedly while tapping R
```

Once you have a `>>>` prompt, remove the offending file:

```python
import os; os.remove("main.py")
```

If you can't interrupt it at all, `erase_flash` and start from step 3.
Nothing on the board is precious except `config.py`, and that's a copy of
what's on your machine.

> **This is why `tools/deploy.sh` runs the tests first.** A LoRa-only lamp
> has **no over-the-air recovery** — ten bytes a message is not a firmware
> channel. On the original project a bad push could be fixed remotely;
> here a boot loop means USB, and if the lamp is at a friend's house, the
> post.

### `OSError: [Errno 2] ENOENT` on boot

A file didn't copy. `mpremote ls :lamp` and compare against
[Layout](../README.md#layout).

### It works, then stops responding after a few minutes

Almost always power. Either radio draws a current spike when it
transmits — an SX1262 at 14 dBm pulls around 45 mA on top of everything
else — and if it shares a weak 3V3 rail with an LED strip the brownout
takes the whole board down. Power the strip from 5 V directly, not
through the XIAO.

---

## Starting over

```bash
esptool.py --chip esp32s3 --port /dev/ttyACM0 erase_flash
```

Wipes everything including `config.py`. Go back to step 3, then
re-deploy — your keys are safe in `.env` on your laptop. There is no
state on the board worth preserving: the lamp's counters come back from
its peer at the next heartbeat.
