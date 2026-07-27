#!/usr/bin/env python3
"""
Write both lamp configs from .env.

  cp .env.example .env      # fill it in once
  python3 tools/apply_env.py
  ./tools/deploy.sh --lamp 1 /dev/ttyACM0

.env is the only place your keys live. It is gitignored, and so are the
config files this generates — so there is no file you have to remember
not to commit.

It refuses to write anything if the values would produce a broken pair.
Three of the ways to get six values wrong give you a lamp that joins the
network perfectly and then does nothing, with no error anywhere:

  * both lamps sharing a DevEUI     -> they fight over one session
  * lamps with different JoinEUIs   -> one never joins at all
  * both lamps sharing a LAMP_ID    -> they join, then ignore each other
                                       forever, because the CRDT drops a
                                       message bearing your own id as an
                                       echo of yourself
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ENV = os.path.join(ROOT, ".env")

HEX = re.compile(r"^[0-9A-Fa-f]+$")


def load_env(path):
    """KEY = value, # comments, no quoting rules to remember."""
    values = {}
    with open(path) as f:
        for raw in f:
            line = raw.split("#", 1)[0].strip()
            if not line or "=" not in line:
                continue
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip().strip('"').strip("'")
    return values


TEMPLATE = '''# ============================================================
#  config.lamp{n}.py  —  {name}
#  GENERATED from .env by tools/apply_env.py — edit .env, not this.
# ============================================================
# Deploy:  ./tools/deploy.sh --lamp {n} /dev/ttyACM0
# It lands on the board as config.py.

LAMP_ID   = {n}
LAMP_NAME = "{name}"

# ── LoRaWAN (The Things Network) ────────────────────────────
LORA_ENABLED = True
LORA_DEV_EUI = "{dev_eui}"          # unique to this lamp
LORA_APP_EUI = "{join_eui}"          # SAME on both lamps
LORA_APP_KEY = "{app_key}"
LORA_REGION  = "{region}"
LORA_CLASS   = "C"                   # mains-powered: listens continuously
LORA_PORT    = 8

# XIAO TX -> E5 RX, XIAO RX -> E5 TX. They cross over.
LORA_UART_ID = 1
LORA_TX_PIN  = 43
LORA_RX_PIN  = 44
LORA_BAUD    = 9600

# Ten downlinks a day is your FRIEND's allowance, and every uplink the
# bridge forwards spends one of theirs. 2 heartbeats + 8 changes = 10.
LORA_MIN_INTERVAL_MS = 3 * 60 * 60 * 1000

# ── Home WiFi (optional) ────────────────────────────────────
# Can also be entered from the lamp's own page later, with no cable.
WIFI_ENABLED  = {wifi_enabled}
WIFI_NETWORKS = {wifi_networks}

MQTT_BROKER   = ""
MQTT_PORT     = 1883
MQTT_USER     = ""
MQTT_PASSWORD = ""
MQTT_PREFIX   = "friendlights_{slug}"

# ── LED strip ───────────────────────────────────────────────
LED_PIN        = 2                   # data line, via the 330 ohm resistor
NUM_LEDS       = 10
LED_BRIGHTNESS = 0.6
LED_ORDER      = "GRBW"              # "GRB" for WS2812 (no white channel)
REVERSE_LEDS   = False

# ── Touch ───────────────────────────────────────────────────
TOUCH_PINS      = [4]                # [] for a lamp with no pad
TOUCH_THRESHOLD = 20000

# ── Feel ────────────────────────────────────────────────────
# How long a colour takes to arrive after your friend touches theirs.
# `python3 tools/simulate.py --arrival-fade 5` to feel the difference.
ARRIVAL_FADE_MS = 90 * 1000
BREATHE_SPEED   = 0.0008
BREATHE_DEPTH   = 0.04

# ── The lamp's own WiFi network ─────────────────────────────
# Join "{ssid}", then the page opens by itself;
# otherwise browse to http://192.168.4.1
PORTAL_ENABLED   = True
PORTAL_ALWAYS_ON = True
PORTAL_SSID      = "{ssid}"
PORTAL_PASSWORD  = "{portal_password}"

WATCHDOG_ENABLED = True
'''


def main():
    if not os.path.exists(ENV):
        print("\n  No .env yet:\n")
        print("      cp .env.example .env\n")
        print("  Then fill in the DevEUI and AppKey for each lamp.\n")
        return 1

    env = load_env(ENV)
    problems = []
    missing = []

    def need(key):
        v = env.get(key, "").strip()
        if not v:
            missing.append(key)
        return v

    join_eui = need("JOIN_EUI")
    lamps = []
    for n in (1, 2):
        lamps.append({
            "n": n,
            "name": env.get("LAMP%d_NAME" % n, "").strip() or "lamp%d" % n,
            "dev_eui": need("LAMP%d_DEV_EUI" % n),
            "app_key": need("LAMP%d_APP_KEY" % n),
        })

    if missing:
        print("\n  .env is missing values:\n")
        for k in missing:
            print("      %s" % k)
        print("\n  DevEUI is on the TTN device page; AppKey is under")
        print("  General settings -> Join settings, behind the eye icon.\n")
        return 1

    # ── Shape ──
    for label, value, length in (
            [("JOIN_EUI", join_eui, 16)] +
            [("LAMP%d_DEV_EUI" % l["n"], l["dev_eui"], 16) for l in lamps] +
            [("LAMP%d_APP_KEY" % l["n"], l["app_key"], 32) for l in lamps]):
        if len(value) != length or not HEX.match(value):
            problems.append("%s must be %d hex characters (got %d: %r)"
                            % (label, length, len(value), value))
        elif set(value) == {"0"}:
            problems.append("%s is all zeros" % label)

    # ── The pair ──
    if lamps[0]["dev_eui"].upper() == lamps[1]["dev_eui"].upper():
        problems.append(
            "Both lamps have the same DevEUI. Each device needs its own, "
            "or they fight over one session and neither stays joined.")
    if lamps[0]["app_key"].upper() == lamps[1]["app_key"].upper():
        problems.append("Both lamps have the same AppKey. Generate two.")

    password = env.get("PORTAL_PASSWORD", "").strip()
    if password and len(password) < 8:
        problems.append(
            "PORTAL_PASSWORD is under 8 characters. The ESP32 silently "
            "ignores short ones and brings the network up OPEN.")

    if problems:
        print("\n  Not writing anything:\n")
        for p in problems:
            print("    - %s" % p)
        print()
        return 1

    ssid_pw = password or "lightupleni"
    wifi_ssid = env.get("WIFI_SSID", "").strip()
    wifi_pass = env.get("WIFI_PASSWORD", "").strip()

    for lamp in lamps:
        slug = re.sub(r"[^a-z0-9]+", "-", lamp["name"].lower()).strip("-")
        ssid = "deLENIghted-%d-%s" % (lamp["n"], lamp["name"])
        if len(ssid) > 32:
            ssid = ssid[:32]
        path = os.path.join(ROOT, "firmware", "config.lamp%d.py" % lamp["n"])
        with open(path, "w") as f:
            f.write(TEMPLATE.format(
                n=lamp["n"], name=lamp["name"], slug=slug or "lamp",
                dev_eui=lamp["dev_eui"].upper(),
                join_eui=join_eui.upper(),
                app_key=lamp["app_key"].upper(),
                region=env.get("LORA_REGION", "EU868") or "EU868",
                wifi_enabled=bool(wifi_ssid),
                wifi_networks=repr([[wifi_ssid, wifi_pass]]) if wifi_ssid
                else "[]",
                ssid=ssid, portal_password=ssid_pw))
        print("  wrote firmware/config.lamp%d.py   %-8s  %s"
              % (lamp["n"], lamp["name"], ssid))

    print("\n  Both configs written from .env. Neither is tracked by git.")
    print("\n  Next:  ./tools/deploy.sh --lamp 1 /dev/ttyACM0\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
