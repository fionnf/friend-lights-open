# ============================================================
#  config.example.py  —  copy to config.py and edit per lamp
# ============================================================
# config.py is gitignored and is NEVER overwritten by an update. Real
# keys and passwords live only on the lamp itself, never in the repo.
#
#   cp firmware/config.example.py firmware/config.py

# ── Identity ────────────────────────────────────────────────
# Must be unique within your group, 1-255. This is the only thing that
# has to differ between two lamps — everything else can be identical.
LAMP_ID   = 1
LAMP_NAME = "Zurich"          # shown in the app; free text

# ── LoRaWAN (The Things Network) ────────────────────────────
# Register the device in the TTN console, then paste its values here.
# Use OTAA. DevEui is per-device; AppEui and AppKey come from the
# application you registered it under.
LORA_ENABLED = True
LORA_DEV_EUI = "0000000000000000"
LORA_APP_EUI = "0000000000000000"
LORA_APP_KEY = "00000000000000000000000000000000"
LORA_REGION  = "EU868"        # EU868 / US915 / AU915 / AS923 ...
LORA_CLASS   = "C"            # C: mains-powered, receives at any time
LORA_PORT    = 8

# UART pins to the Wio-E5. Any two free pins will do.
LORA_UART_ID = 1
LORA_TX_PIN  = 43
LORA_RX_PIN  = 44
LORA_BAUD    = 9600

# How often we may transmit. TTN allows 30 s of airtime per device per
# day; a 10-byte frame at SF9 costs ~0.2 s, so ~150 uplinks/day exist.
# 15 minutes spends about half of that and leaves headroom.
LORA_MIN_INTERVAL_MS = 15 * 60 * 1000

# ── WiFi (optional) ─────────────────────────────────────────
# Entirely optional. A lamp with no WiFi works perfectly over LoRa alone;
# WiFi just makes it faster and unmetered when it happens to be there.
# A phone hotspot counts — see docs/HARDWARE.md.
WIFI_ENABLED  = False
WIFI_NETWORKS = [
    # ("YourNetwork", "YourPassword"),
]

MQTT_BROKER   = ""
MQTT_PORT     = 1883
MQTT_USER     = ""
MQTT_PASSWORD = ""
MQTT_PREFIX   = "friendlights_changeme"   # ← make this unguessable

# ── LED strip ───────────────────────────────────────────────
LED_PIN        = 2
NUM_LEDS       = 10
LED_BRIGHTNESS = 0.6
LED_ORDER      = "GRBW"       # SK6812 RGBW. Use "GRB" for WS2812 (no W)
REVERSE_LEDS   = False

# ── Touch ───────────────────────────────────────────────────
# On ESP32-S3 these are native capacitive touch channels — no external
# resistor, no calibration hack. Set to [] for a lamp with no touch pad.
TOUCH_PINS      = [4]
TOUCH_THRESHOLD = 20000

# ── Feel ────────────────────────────────────────────────────
# How long a colour takes to arrive after a friend touches theirs.
# Deliberately slow: the light is meant to read as post, not as a text.
# Set to a few seconds if you want a mirror instead.
ARRIVAL_FADE_MS = 90 * 1000

BREATHE_SPEED = 0.0008
BREATHE_DEPTH = 0.04

# ── Setup portal ────────────────────────────────────────────
# Hold the touch pad for 5 seconds and the lamp raises its own WiFi
# network, "lamp-<id>-setup". Join it and a page opens by itself: colour,
# brightness, power, and the TTN keys.
#
# Local control costs nothing — it never spends one of the ten daily
# messages. The access point shuts itself off after 5 minutes.
PORTAL_ENABLED = True

# ── Watchdog ────────────────────────────────────────────────
WATCHDOG_ENABLED = True
