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
LORA_RADIO   = "{radio}"             # SX1262 (ABP) or E5 (AT + OTAA)

# ABP session, used when LORA_RADIO is "SX1262"
LORA_DEV_ADDR = "{dev_addr}"
LORA_NWK_SKEY = "{nwk_skey}"
LORA_APP_SKEY = "{app_skey}"
LORA_SF       = 9                    # must match RX2 on your plan
LORA_TX_POWER = 14                   # dBm, EU868 ceiling

# OTAA, used when LORA_RADIO is "E5"
LORA_DEV_EUI = "{dev_eui}"          # unique to this lamp
LORA_APP_EUI = "{join_eui}"          # SAME on both lamps
LORA_APP_KEY = "{app_key}"

# SPI to the Wio-SX1262 — the board-to-board kit pins, tried first. If
# the module is on the through-hole header instead, the firmware finds
# that by itself; you do not have to change anything here.
SX_SPI_ID    = 1
SX_SCK_PIN   = 7
SX_MOSI_PIN  = 9
SX_MISO_PIN  = 8
SX_NSS_PIN   = 41
SX_RESET_PIN = 42
SX_BUSY_PIN  = 40
SX_DIO1_PIN  = 39
LORA_REGION  = "{region}"
LORA_CLASS   = "C"                   # mains-powered: listens continuously
LORA_PORT    = 8

# XIAO TX -> E5 RX, XIAO RX -> E5 TX. They cross over.
LORA_UART_ID = 1
LORA_TX_PIN  = 43
LORA_RX_PIN  = 44
LORA_BAUD    = 9600

# Ten downlinks a day is your FRIEND's allowance, and every uplink the
# bridge forwards spends one of theirs. Spent as a token bucket: up to
# LORA_BURST touches go out immediately, refilling one per interval —
# so touches arrive in seconds until a day gets unusually busy.
LORA_MIN_INTERVAL_MS = 3 * 60 * 60 * 1000
LORA_BURST           = 6

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
NUM_LEDS       = {num_leds}
LED_BRIGHTNESS = 0.6
LED_ORDER      = "{led_order}"              # "GRB" for WS2812 (no white)
REVERSE_LEDS   = False

# ── Colour zones ────────────────────────────────────────────
# The strip splits into zones, each its own colour, reshuffled on every
# touch. Both lamps derive identical zones from the shared counter, so
# this costs nothing on the wire. NUM_GROUPS = 1 for one flat colour.
NUM_GROUPS     = {num_groups}
GROUP_MIN_LEDS = 1
GROUP_MAX_LEDS = {group_max}
GROUP_SPREAD   = {spread}

# ── Touch ───────────────────────────────────────────────────
TOUCH_PINS      = [4]                # [] for a lamp with no pad
TOUCH_THRESHOLD = 20000

# ── Feel ────────────────────────────────────────────────────
# How long the colour settles once your friend's touch arrives. A few
# seconds feels immediate; 90000 feels like post arriving.
# `python3 tools/simulate.py --arrival-fade 90` to feel the slow one.
ARRIVAL_FADE_MS = 6 * 1000
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

    radio = (env.get("LORA_RADIO", "").strip() or "SX1262").upper()
    abp = radio.startswith("SX")

    lamps = []
    if abp:
        # ABP: a session, not a join. Different three values per lamp.
        join_eui = "0000000000000000"
        for n in (1, 2):
            lamps.append({
                "n": n,
                "name": env.get("LAMP%d_NAME" % n, "").strip(),
                "dev_addr": need("LAMP%d_DEV_ADDR" % n),
                "nwk_skey": need("LAMP%d_NWK_SKEY" % n),
                "app_skey": need("LAMP%d_APP_SKEY" % n),
                "dev_eui": "", "app_key": "",
            })
    else:
        join_eui = need("JOIN_EUI")
        for n in (1, 2):
            lamps.append({
                "n": n,
                # Optional and cosmetic — it only shows up in the SSID.
                "name": env.get("LAMP%d_NAME" % n, "").strip(),
                "dev_eui": need("LAMP%d_DEV_EUI" % n),
                "app_key": need("LAMP%d_APP_KEY" % n),
                "dev_addr": "", "nwk_skey": "", "app_skey": "",
            })

    if missing:
        print("\n  .env is missing values:\n")
        for k in missing:
            print("      %s" % k)
        print("\n  DevEUI is on the TTN device page; AppKey is under")
        print("  General settings -> Join settings, behind the eye icon.\n")
        return 1

    # ── Shape ──
    if abp:
        shapes = ([("LAMP%d_DEV_ADDR" % l["n"], l["dev_addr"], 8) for l in lamps]
                  + [("LAMP%d_NWK_SKEY" % l["n"], l["nwk_skey"], 32) for l in lamps]
                  + [("LAMP%d_APP_SKEY" % l["n"], l["app_skey"], 32) for l in lamps])
    else:
        shapes = ([("JOIN_EUI", join_eui, 16)]
                  + [("LAMP%d_DEV_EUI" % l["n"], l["dev_eui"], 16) for l in lamps]
                  + [("LAMP%d_APP_KEY" % l["n"], l["app_key"], 32) for l in lamps])
    for label, value, length in shapes:
        if len(value) != length or not HEX.match(value):
            problems.append("%s must be %d hex characters (got %d: %r)"
                            % (label, length, len(value), value))
        elif set(value) == {"0"}:
            problems.append("%s is all zeros" % label)

    # ── The pair ──
    ident = "dev_addr" if abp else "dev_eui"
    secret = "app_skey" if abp else "app_key"
    if lamps[0][ident].upper() == lamps[1][ident].upper():
        problems.append(
            "Both lamps have the same %s. Each device needs its own, or "
            "they fight over one session and neither stays connected."
            % ("DevAddr" if abp else "DevEUI"))
    if lamps[0][secret].upper() == lamps[1][secret].upper():
        problems.append("Both lamps have the same session key. Use two.")

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

    def _int(key, default, lo, hi):
        try:
            return max(lo, min(hi, int(env.get(key, "") or default)))
        except ValueError:
            return default

    num_leds = _int("NUM_LEDS", 10, 1, 300)
    num_groups = _int("NUM_GROUPS", 3, 1, num_leds)
    led_order = (env.get("LED_ORDER", "").strip() or "GRBW").upper()
    wifi_ssid = env.get("WIFI_SSID", "").strip()
    wifi_pass = env.get("WIFI_PASSWORD", "").strip()

    for lamp in lamps:
        slug = re.sub(r"[^a-z0-9]+", "-", lamp["name"].lower()).strip("-")
        ssid = "deLENIghted-%d" % lamp["n"]
        if lamp["name"]:
            ssid += "-" + lamp["name"]
        if len(ssid) > 32:
            ssid = ssid[:32]
        path = os.path.join(ROOT, "firmware", "config.lamp%d.py" % lamp["n"])
        with open(path, "w") as f:
            f.write(TEMPLATE.format(
                n=lamp["n"], name=lamp["name"], slug=slug or ("lamp%d" % lamp["n"]),
                dev_eui=lamp["dev_eui"].upper(),
                join_eui=join_eui.upper(),
                app_key=lamp["app_key"].upper(),
                region=env.get("LORA_REGION", "EU868") or "EU868",
                wifi_enabled=bool(wifi_ssid),
                wifi_networks=repr([[wifi_ssid, wifi_pass]]) if wifi_ssid
                else "[]",
                radio=radio,
                dev_addr=lamp["dev_addr"].upper(),
                nwk_skey=lamp["nwk_skey"].upper(),
                app_skey=lamp["app_skey"].upper(),
                ssid=ssid, portal_password=ssid_pw,
                num_leds=num_leds, led_order=led_order,
                num_groups=num_groups, group_max=max(1, num_leds // 2),
                spread=env.get("GROUP_SPREAD", "0.35") or "0.35"))
        print("  wrote firmware/config.lamp%d.py   %s" % (lamp["n"], ssid))

    print("\n  Both configs written from .env. Neither is tracked by git.")
    print("\n  Next:  ./tools/deploy.sh --lamp 1 /dev/ttyACM0\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
