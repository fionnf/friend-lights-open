#!/usr/bin/env python3
"""
Build a folder that IS the lamp's filesystem, ready to upload.

    python3 tools/prepare_upload.py

Writes upload/lamp1/ and upload/lamp2/. Open one in Thonny, select
everything inside it, right-click -> "Upload to /". Done.

Why this exists: the repo's layout is not the board's layout. On the
board the firmware lives at /main.py and /lamp/..., and the config file
is named config.py — but in the repo it is firmware/main.py,
firmware/lamp/... and config.lamp1.py. Uploading by hand therefore
means picking the right files out of two directories AND renaming one
of them, and renaming the WRONG lamp's config onto a board is a mistake
that produces two lamps sharing a LoRaWAN session, which looks like
"the radio doesn't work" for an evening.

So the renaming and the picking happen here, once, where they can be
tested — and Thonny is left with the one job it is genuinely good at:
copying a folder to a device.
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

sys.path.insert(0, HERE)
from install import device_files                              # noqa: E402


def build(lamp, root=ROOT, out_root=None):
    """Stage one lamp's board filesystem. Returns (path, warning)."""
    out_root = out_root or os.path.join(root, "upload")
    out = os.path.join(out_root, "lamp%d" % lamp)

    # Rebuild from scratch: a leftover file from an older version would
    # otherwise ride along forever, and stale firmware on a LoRa-only
    # lamp cannot be fixed over the air.
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)

    for local, remote in device_files(root):
        dest = os.path.join(out, remote.lstrip(":").replace("/", os.sep))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy(local, dest)

    warning = None
    config = os.path.join(root, "firmware", "config.lamp%d.py" % lamp)
    dest = os.path.join(out, "config.py")
    if os.path.exists(config):
        # Lands as config.py — the board only ever knows that name.
        shutil.copy(config, dest)
    else:
        # No generated config, so stage a fill-in-the-blanks one rather
        # than a folder that is quietly incomplete. The lamp boots with
        # this as it stands — strip, touch and control page all work —
        # and stays off the radio until the three TTN values are in.
        with open(dest, "w") as f:
            f.write(STARTER_CONFIG.format(lamp=lamp))
        warning = "config.py is a template — fill in the three TTN values"
    return out, warning


STARTER_CONFIG = '''# ============================================================
#  config.py  —  lamp {lamp}
# ============================================================
# Fill in the three values under "FROM THE TTN CONSOLE" and save. In
# Thonny you can edit this file directly on the board: double-click
# config.py in the device pane, change it, Ctrl-S, then press R.
#
# Everything else already works. A lamp with no TTN values still runs:
# the strip lights, the touch pad works, and its WiFi control page is
# up — it simply has nothing to talk to yet.
#
# Prefer not to edit by hand? Put your keys in .env once and run
#   python3 tools/apply_env.py && python3 tools/prepare_upload.py
# and this file is written for you, for both lamps, with the pair
# checked for the mistakes that are invisible until they are expensive.

# ── Identity ────────────────────────────────────────────────
# The ONLY value that must differ between your two lamps.
LAMP_ID   = {lamp}
LAMP_NAME = ""

# ── FROM THE TTN CONSOLE ────────────────────────────────────
# Your device page -> General settings -> Session information.
# The two keys are behind an eye icon. Register the device with
# Activation mode = ABP and Class C. See docs/SETUP.md step 3.
#
# Each lamp needs its OWN three values. Two lamps sharing a session
# fight over it and neither stays connected — which looks exactly like
# a broken radio, so it is worth double-checking here.
LORA_ENABLED  = True
LORA_RADIO    = "SX1262"
LORA_DEV_ADDR = ""             # 8 hex   e.g. "260B1234"
LORA_NWK_SKEY = ""             # 32 hex
LORA_APP_SKEY = ""             # 32 hex

# ── The strip ───────────────────────────────────────────────
LED_PIN        = 2             # data line, through the 330 ohm resistor
NUM_LEDS       = 10            # however many you soldered
LED_BRIGHTNESS = 0.6
LED_ORDER      = "GRBW"        # SK6812 RGBW; "GRB" for WS2812
REVERSE_LEDS   = False         # True if wired from the far end

NUM_GROUPS     = 3             # colour zones; 1 for one flat colour
GROUP_MIN_LEDS = 1
GROUP_MAX_LEDS = 8
GROUP_SPREAD   = 0.35

# ── Touch ───────────────────────────────────────────────────
TOUCH_PINS      = [4]          # [] for a lamp with no pad
TOUCH_THRESHOLD = 20000

# ── Feel ────────────────────────────────────────────────────
# How long the colour takes to settle once a touch arrives. A few
# seconds reads as immediate; 90000 reads as post arriving.
ARRIVAL_FADE_MS = 6 * 1000
BREATHE_SPEED   = 0.0008
BREATHE_DEPTH   = 0.04

# ── How often it may speak ──────────────────────────────────
# Messages a day, spent as a token bucket: the first LORA_BURST touches
# of a quiet day go out immediately, then it refills steadily. 0 = no
# daily budget (the EU868 duty cycle still caps it at one per 30 s).
LORA_DAILY_BUDGET = 48
LORA_BURST        = 6

LORA_SF       = 9              # must match RX2 on your frequency plan
LORA_TX_POWER = 14             # dBm; EU868 legal ceiling
LORA_REGION   = "EU868"
LORA_CLASS    = "C"            # mains-powered: listens continuously
LORA_PORT     = 8
LORA_DRIVER   = "upstream"

# The radio's pins are found automatically — both ways of attaching the
# module are probed at startup. Nothing to set here.

# ── The lamp's own WiFi network ─────────────────────────────
# Join it from a phone to control the lamp. At least 8 characters, or
# the ESP32 silently brings the network up OPEN.
PORTAL_ENABLED   = True
PORTAL_ALWAYS_ON = True
PORTAL_SSID      = "deLENIghted-{lamp}"
PORTAL_PASSWORD  = "lightupleni"

# ── Optional home WiFi ──────────────────────────────────────
# A lamp with no WiFi works perfectly over LoRa alone. A phone hotspot
# counts. Can also be entered later from the lamp's own page.
WIFI_ENABLED  = False
WIFI_NETWORKS = [
    # ("YourNetwork", "YourPassword"),
]
MQTT_BROKER   = ""
MQTT_PORT     = 1883
MQTT_USER     = ""
MQTT_PASSWORD = ""
MQTT_PREFIX   = "friendlights_changeme"

WATCHDOG_ENABLED = True
'''


def tree(path, prefix=""):
    """The staged folder, so what you are about to upload is visible
    before you upload it rather than after."""
    entries = sorted(os.listdir(path),
                     key=lambda n: (os.path.isdir(os.path.join(path, n)), n))
    for i, name in enumerate(entries):
        last = i == len(entries) - 1
        full = os.path.join(path, name)
        print("   %s%s%s" % (prefix, "`- " if last else "|- ", name))
        if os.path.isdir(full):
            tree(full, prefix + ("   " if last else "|  "))


def main():
    print("\nStaging what goes on each board...\n")
    problems = []
    for lamp in (1, 2):
        out, warning = build(lamp)
        rel = os.path.relpath(out, ROOT)
        if warning:
            print("  %s  -- %s" % (rel, warning))
            problems.append(warning)
        else:
            print("  %s" % rel)
    print()

    first = os.path.join(ROOT, "upload", "lamp1")
    if os.path.isdir(first):
        print("  upload/lamp1/ contains:")
        tree(first)
        print()

    if problems:
        print("  The folders are complete and will boot as they are —")
        print("  strip, touch pad and control page all work. What is")
        print("  missing is only the three TTN values, so the lamp has")
        print("  nothing to talk to yet. Two ways to add them:\n")
        print("    * upload now, then edit config.py on the board in")
        print("      Thonny: double-click it, paste, Ctrl-S, press R")
        print("    * or put your keys in .env once and run")
        print("      python3 tools/apply_env.py && python3 %s\n"
              % os.path.relpath(__file__, ROOT))

    print("  Now, in Thonny:")
    print("    1. View -> Files")
    print("    2. In the top pane, open  upload/lamp1")
    print("    3. Select everything in it  (Ctrl-A / Cmd-A)")
    print("    4. Right-click -> Upload to /")
    print("    5. Repeat with upload/lamp2 on the other board")
    print("\n  Full walkthrough: docs/FLASHING.md\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
