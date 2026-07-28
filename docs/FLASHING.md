# Flashing

Getting MicroPython onto a XIAO ESP32S3, then the lamp firmware on top.
Allow 20 minutes for the first board, about 5 for the second.

There are two ways, and they do the same thing:

| | |
|---|---|
| **[Thonny](#the-thonny-way)** — a small, free Python editor with a file browser. Nothing to install but Thonny itself, and you can see the board's files. **Start here.** |
| **[The command line](#the-command-line-way)** — `python3 tools/install.py` does the whole thing in one command, including the parts Thonny makes you click. Better if you are comfortable in a terminal or are doing this repeatedly. |

Both end with the same files on the board. Use whichever you like; you
can switch between them freely.

> **One rule if you use both:** only one program can hold the serial
> port. If Thonny is connected, `mpremote` and `install.py` cannot talk
> to the board, and vice versa. In Thonny, **Stop/Restart** does not
> release it — use **Run → Disconnect**, or just close Thonny.

---

## The Thonny way

### 1. Install Thonny

Download from **[thonny.org](https://thonny.org)** and install it.
Windows, macOS and Linux all have a normal installer. Thonny bundles
its own Python, so nothing else is needed.

**Use Thonny 4.0 or newer** — it can install MicroPython by itself.
Check under **Help → About Thonny**.

### 2. Plug the board in

Connect the XIAO to your computer with a **USB-C data cable**.

> If nothing appears in later steps, suspect the cable first. Many
> USB-C cables sold with phones and power banks are **charge-only** —
> they carry power but no data, and the board looks dead through one.
> This is the single most common problem on this page.

### 3. Put the board in bootloader mode

Only needed for this first firmware install, not for uploading files
later.

On the XIAO there are two tiny buttons beside the USB socket, marked
**B** (boot) and **R** (reset):

1. Press and **hold B**
2. While holding it, **press and release R**
3. **Release B**

The board is now waiting to be flashed. Nothing visible happens — that
is normal.

### 4. Install MicroPython

In Thonny:

1. **Tools → Options… → Interpreter**
2. Set the interpreter to **MicroPython (ESP32)**
3. Click **Install or update MicroPython (esptool)** at the bottom of
   the dialog
4. In the window that opens:

   | Field | What to choose |
   |---|---|
   | **Target port** | the one that appeared in bootloader mode — often labelled *USB JTAG/serial debug unit* or *CP210x*. If you see several, unplug the board, reopen the list, plug it back in, and take the new one. |
   | **MicroPython family** | `ESP32-S3` |
   | **variant** | `Espressif • ESP32-S3` (the generic one — correct for the XIAO) |
   | **version** | the newest offered |

5. Click **Install** and wait. It erases, writes and verifies — a
   minute or two. Do not unplug it.
6. Close both dialogs, then **press R** on the board once.

Thonny's Shell pane at the bottom should now show something like:

```
MicroPython v1.27.0 on 2026-07-15; Generic ESP32S3 module with ESP32S3
>>>
```

**That prompt is the whole test.** If it is there, MicroPython is
installed and the hard part is over.

> Nothing in the Shell? Click **Stop/Restart** (the red button), or
> press **R** on the board again. If the port vanished from Thonny's
> bottom-right corner, pick it again there.

### 5. Get the lamp's files ready

The repo's layout is not the board's layout, so let a script arrange
them rather than picking and renaming files by hand:

```bash
python3 tools/prepare_upload.py
```

This creates `upload/lamp1/` and `upload/lamp2/` — each one is exactly
what that lamp's filesystem should contain, with the right config file
already renamed to `config.py`.

**No TTN keys yet?** It still works. You get a `config.py` with the
three TTN values blank and everything else filled in, and it says so.
The lamp boots on that as it stands — strip, touch pad and control page
all work — and simply has nothing to talk to until you fill them in.
You can do that in Thonny afterwards: double-click `config.py` in the
device pane, paste the three values, **Ctrl-S**, press **R**.

If you would rather not edit by hand, put the keys in `.env` once and
run `python3 tools/apply_env.py` before this step ([SETUP.md step
5](SETUP.md#5-configure-and-load)). It writes both lamps' configs and
checks the pair for the mistakes that stay invisible until they are
expensive.

**The two folders are not interchangeable.** `upload/lamp1/` goes on
lamp 1 and `upload/lamp2/` on lamp 2. Putting the same one on both
gives you two lamps sharing a LoRaWAN session and a lamp id: they will
fight over the session, ignore each other's messages, and look for all
the world like a broken radio.

### 6. Upload the files

Still in Thonny:

1. **View → Files**. The left side now has two panes: your computer on
   top, **MicroPython device** underneath.
2. In the top pane, navigate into `upload/lamp1`.
3. Select **everything** inside it — click one item, then **Ctrl-A**
   (**Cmd-A** on a Mac). That is `main.py`, `radio_check.py` and the
   `lamp` folder.
4. **Right-click → Upload to /**

Thonny copies the folders and their contents for you. It takes a few
seconds — around 20 files.

When it finishes, the device pane should show:

```
lamp
config.py
main.py
radio_check.py
```

Nothing else needs to be there, and anything else that is does no harm.

### 7. First light

Press **R** on the board, and watch the Shell:

```
[boot] friend-lights-open 2026-07-27.1 — lamp 1
[sx1262] found on the B2B kit pinout — NSS 41, RST 42, BUSY 40, DIO1 39
[lorawan] radio up, listening on 869.525 MHz SF9, fcnt 0
[portal] up — join WiFi 'deLENIghted-1'
```

The strip breathes warm white through startup, then settles.

Now repeat steps 5–7 for the second board, using **`upload/lamp2`**.

---

## Re-flashing a lamp that already works

Uploading to a board that is *already running the firmware* has one
trap: the lamp arms an **8-second hardware watchdog**, and on the ESP32
a watchdog cannot be switched off — only given a longer deadline. Left
alone, it reboots the board partway through your upload, and a
half-copied firmware on a LoRa-only lamp is the one way to genuinely
brick one.

So before uploading to a working lamp, click into Thonny's **Shell**
and press **Ctrl-C** to stop the program, then paste:

```python
from machine import WDT
WDT(timeout=600000)
```

That buys ten minutes, which is ample. Then upload as usual and press
**R** when you are done — the reset re-arms the normal 8-second
watchdog.

`tools/install.py` and `tools/deploy.sh` do this for you automatically;
it is only the by-hand path that needs the reminder.

> Fresh board, straight after installing MicroPython? Skip all this —
> there is no watchdog running yet.

---

## The command line way

One command does everything above, including choosing the firmware
image and walking you through bootloader mode:

```bash
python3 tools/install.py
```

It is **rerunnable** — it looks at what is already done and does the
next thing — so a second board, a half-finished install, and a firmware
update are all the same command. Full detail:
[SETUP.md](SETUP.md).

To update the code on a board that is already set up:

```bash
python3 tools/install.py --deploy --lamp 1
./tools/deploy.sh --lamp 1            # the same thing, shorter to type
```

That runs every test first and refuses to copy anything if one fails,
which matters here: a LoRa-only lamp has no over-the-air recovery, so a
boot loop means USB, or the post. It also stretches the watchdog before
copying and resets the board after — see
[re-flashing](#re-flashing-a-lamp-that-already-works) for why.

<details>
<summary>Doing it manually with esptool and mpremote</summary>

```bash
pip install esptool mpremote
```

Enter bootloader mode (hold **B**, tap **R**, release **B** — the port
number often changes when you do this, so re-check it), then:

```bash
esptool.py --chip esp32s3 --port /dev/ttyACM0 erase_flash
esptool.py --chip esp32s3 --port /dev/ttyACM0 --baud 921600 \
           write_flash -z 0 ESP32_GENERIC_S3-*.bin
```

Image from
[micropython.org](https://micropython.org/download/ESP32_GENERIC_S3/).
Note **`-z 0`** — the S3 image goes at offset `0`, not `0x1000` like
the older ESP32. Tap **R**, then check:

```bash
mpremote connect /dev/ttyACM0 exec "import sys; print(sys.implementation)"
```

</details>

---

## Check the strip first

Before the radio, before TTN, before anything: does the strip work and
is it wired the way `config.py` thinks it is?

```bash
mpremote connect /dev/ttyACM0 run tools/strip_test.py
```

In Thonny: open `strip_test.py` and press **F5**. (It is also copied
onto the board, so `run strip_test.py` works from anywhere.)

It flashes the strip through a known sequence and **prints what each
step should look like**, because the board cannot see its own LEDs —
so every fault shows up as a mismatch between what it says and what you
see. Ninety seconds, and it ends with a table mapping each mismatch to
the one line in `config.py` that fixes it:

| What you see | What it means |
|---|---|
| It says RED, it looks GREEN | `LED_ORDER` — SK6812 is `GRBW`, WS2812 is `GRB` |
| The chase stops partway | `NUM_LEDS` is higher than the strip really is — count the lit ones |
| The chase runs from the far end | `REVERSE_LEDS = True` |
| Only the first pixel or two light | Data line: the resistor, lead length, or no shared ground |
| Flicker, or the board resets | Power — feed the strip from 5 V, not through the XIAO |
| Nothing at all | `LED_PIN`, the resistor on the wrong line, or no 5 V at the strip |

It also reads the touch pad live for five seconds so you can see what
your pad actually does and set `TOUCH_THRESHOLD` from real numbers
rather than from the default.

It never transmits, so the antenna does not matter and nothing can be
damaged. Worth running the moment the firmware is on: a miswired strip
looks exactly like broken firmware, and this rules it out.

---

## The radio

**Neither radio module gets flashed.** The Wio-SX1262 has no processor
in it — the LoRaWAN stack runs on the XIAO with everything else. (A
Wio-E5 has one, but arrives with its AT firmware already on it.)

Once the firmware is on, you can check the radio at any time. In
Thonny, open `radio_check.py` from the device pane and press **F5**;
from a terminal:

```bash
mpremote connect /dev/ttyACM0 run tools/radio_check.py
```

⚠️ **It transmits — screw the antenna on first.** Transmitting into an
open connector can damage the radio's power amplifier.

It probes both ways the module can attach, keeps whichever answers, and
then works upward: SPI, the TCXO, a real LoRaWAN frame, and finally
listening for a downlink. It stops at the first thing that is wrong, so
you learn *which* thing.

If neither pinout answers, it is the connector rather than a setting —
no value in `config.py` can make both fail. Press the two boards
together until they click.

If everything passes but nothing appears in TTN's Live data, the radio
is fine and there is no gateway in range. That is coverage, not
hardware.

---

## When it won't cooperate

### No port appears at all

**The cable.** Far and away the most common cause — many USB-C cables
are charge-only. Swap it for one you know carries data before
suspecting anything else.

Then: try a different USB socket, and avoid hubs for the first install.

### Thonny says the port is busy

Something else is holding it — another Thonny window, a serial monitor,
`mpremote`, or `install.py`. Close them. On Linux, if you get a
permission error, add yourself to the `dialout` group and log out and
back in:

```bash
sudo usermod -aG dialout $USER
```

### The Shell shows nothing but a blinking cursor

Press **Ctrl-C** to interrupt whatever is running, then **Ctrl-D** for a
soft reboot. If the lamp firmware is running, Ctrl-C stops it — see
[Re-flashing a lamp that already works](#re-flashing-a-lamp-that-already-works)
about the watchdog before you upload anything.

### "Upload to /" is greyed out, or there is no device pane

Thonny is not connected to the board. Check the **bottom-right corner**
— it names the current interpreter and port. Set it to *MicroPython
(ESP32)* and pick the port.

### It boot-loops after uploading

Read the Shell — the firmware prints the exception before it restarts.
The usual cause is a missing file, so open the device pane and compare
against `upload/lamp1/`; everything there should be on the board, in
the same folders. Re-uploading the lot is harmless.

### It works, then stops responding after a few minutes

Almost always power. Either radio draws a current spike when it
transmits — an SX1262 at 14 dBm pulls around 45 mA on top of everything
else — and if it shares a weak 3V3 rail with an LED strip, the brownout
takes the whole board down. Power the strip from **5 V directly**, not
through the XIAO.

### Starting over

Erase the board completely and begin at step 3. In Thonny the installer
dialog erases before writing, so simply reinstalling MicroPython is
enough. From a terminal:

```bash
esptool.py --chip esp32s3 --port /dev/ttyACM0 erase_flash
```

Nothing on the board is precious — `config.py` is regenerated from your
`.env`, and the lamp's colour state is restored from its friend on the
next message.

---

Stuck on something not listed here? →
[TROUBLESHOOTING.md](TROUBLESHOOTING.md)
