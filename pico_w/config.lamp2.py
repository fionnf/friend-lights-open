# ============================================================
#  config.py  —  Pico W test lamp 2
# ============================================================
# A bench version of the lamp for a Raspberry Pi Pico W, so the whole
# thing can be tried before the LoRa boards arrive.
#
# What is REAL here: the CRDT, the 10-byte wire format, the colour
# engine, the zones, the touch/button gestures, the control page, the
# state that survives a reboot. All of it is the same code the LoRaWAN
# lamp runs.
#
# What is stubbed: the radio. The two lamps talk over WiFi by
# broadcasting to the subnet, so they must be on the SAME network — and
# this is therefore a way to link two lamps on one table, not two
# homes. That is what LoRa is for.

LAMP_ID   = 2
LAMP_NAME = "pico2"

# ── The network, hardcoded for the bench ────────────────────
# Both lamps join this and find each other with nothing configured.
WIFI_ENABLED  = True
WIFI_NETWORKS = [
    ("Gaydar", "rainb0wLAN"),
]

# Broadcast to the subnet: no broker, no account, no internet. Both
# lamps must use the same port; any free one will do.
UDP_ENABLED = True
UDP_PORT    = 41234

# No broker, so the MQTT transport stays out of the way. (It needs
# umqtt, which MicroPython does not ship on the Pico W anyway.)
MQTT_BROKER = ""

# ── No radio on this board ──────────────────────────────────
LORA_ENABLED = False

# ── LED strip ───────────────────────────────────────────────
# GP2 is a free pin next to a GND on the Pico W header. Data line
# through the 330 ohm resistor, as on the real lamp.
LED_PIN        = 2
NUM_LEDS       = 10
LED_BRIGHTNESS = 0.6
LED_ORDER      = "GRBW"        # SK6812 RGBW; "GRB" for WS2812
REVERSE_LEDS   = False

NUM_GROUPS     = 3
GROUP_MIN_LEDS = 1
GROUP_MAX_LEDS = 8
GROUP_SPREAD   = 0.35

# ── Input ───────────────────────────────────────────────────
# The RP2040 has NO capacitive touch peripheral — that is an ESP32
# feature — so a plain push button stands in. Wire it between GP15 and
# any GND pin; the internal pull-up does the rest, no resistor needed.
# Same three gestures as the real lamp: tap, hold 1.2 s, hold 5 s.
TOUCH_PINS  = []
BUTTON_PINS = [15]

# No button either? Leave BUTTON_PINS empty and drive it entirely from
# the control page below.

# ── Feel ────────────────────────────────────────────────────
ARRIVAL_FADE_MS = 6 * 1000
BREATHE_SPEED   = 0.0008
BREATHE_DEPTH   = 0.04

# ── The lamp's own WiFi network ─────────────────────────────
# Runs alongside the connection to "Gaydar" — the Pico W can be an
# access point and a client at once. Join this from a phone to control
# the lamp directly.
PORTAL_ENABLED   = True
PORTAL_ALWAYS_ON = True
PORTAL_SSID      = "deLENIghted-2-pico"
PORTAL_PASSWORD  = "lightupleni"

# ── Watchdog: OFF on the bench, deliberately ────────────────
# On the RP2040 the watchdog maxes out at about 8.4 s and cannot be
# stretched the way the ESP32's can, so the usual "give it ten minutes
# before re-uploading" trick does not work here — it would reset the
# board partway through every file copy. A bench lamp does not need
# the protection, and leaving it off makes this board pleasant to
# iterate on.
WATCHDOG_ENABLED = False
