# ============================================================
#  config.lamp1.py  —  Zurich
# ============================================================
# Deploy with:  ./tools/deploy.sh --lamp 1 /dev/ttyACM0
# It lands on the board as config.py.
#
# Gitignored. Real keys live here and on the lamp, never in the repo.
#
# ── FILL IN THREE VALUES ────────────────────────────────────
# From the TTN console: Applications -> your app -> End devices -> lamp-1
#   DevEUI   on the device overview page
#   AppKey   General settings -> Join settings -> reveal with the eye icon
# The JoinEUI below must be IDENTICAL in the console and in config.lamp2.py.

LAMP_ID   = 1
LAMP_NAME = "Zurich"

# ── LoRaWAN (The Things Network) ────────────────────────────
LORA_ENABLED = True

LORA_DEV_EUI = "PASTE_LAMP1_DEVEUI"          # 16 hex — unique to THIS lamp
LORA_APP_EUI = "0011223344556677"            # 16 hex — SAME on both lamps
LORA_APP_KEY = "PASTE_LAMP1_APPKEY"          # 32 hex — unique to THIS lamp

LORA_REGION  = "EU868"
LORA_CLASS   = "C"        # mains-powered, so it can listen continuously
LORA_PORT    = 8

# UART to the Wio-E5. These cross over: XIAO TX -> E5 RX.
LORA_UART_ID = 1
LORA_TX_PIN  = 43
LORA_RX_PIN  = 44
LORA_BAUD    = 9600

# Ten downlinks a day is your FRIEND's allowance, and every uplink the
# bridge forwards spends one of theirs. 2 heartbeats + 8 changes = 10.
LORA_MIN_INTERVAL_MS = 3 * 60 * 60 * 1000

# ── WiFi (optional) ─────────────────────────────────────────
# Leave off. LoRa alone is the intended setup, and WiFi can be added
# later through the setup portal without touching a cable.
WIFI_ENABLED  = False
WIFI_NETWORKS = []

MQTT_BROKER   = ""
MQTT_PORT     = 1883
MQTT_USER     = ""
MQTT_PASSWORD = ""
MQTT_PREFIX   = "friendlights_zurich"

# ── LED strip ───────────────────────────────────────────────
LED_PIN        = 2         # data line, via the 330 ohm resistor
NUM_LEDS       = 10
LED_BRIGHTNESS = 0.6
LED_ORDER      = "GRBW"    # SK6812 RGBW. Use "GRB" for WS2812.
REVERSE_LEDS   = False     # True if wired from the far end of the strip

# ── Touch ───────────────────────────────────────────────────
# Native ESP32-S3 touch — no resistor needed. [] for no pad.
TOUCH_PINS      = [4]
TOUCH_THRESHOLD = 20000

# ── Feel ────────────────────────────────────────────────────
# How long a colour takes to arrive after your friend touches theirs.
# Try `python3 tools/simulate.py --arrival-fade 5` to feel the difference
# before deciding.
ARRIVAL_FADE_MS = 90 * 1000

BREATHE_SPEED = 0.0008
BREATHE_DEPTH = 0.04



# ── Control network ─────────────────────────────────────────
# The lamp runs its own WiFi network permanently, so you can control it
# from a phone at any time without spending one of the ten daily
# messages. Join "lamp-zurich" and the page opens by itself; if it
# does not, browse to http://192.168.4.1
#
# WPA2 needs at least 8 characters. A shorter one is silently ignored by
# the ESP32 and you would get an OPEN network without being told.
PORTAL_ENABLED   = True
PORTAL_ALWAYS_ON = True
PORTAL_SSID      = "deLENIghted-1-Zurich"   # max 32 characters
PORTAL_PASSWORD  = "lightupleni"        # min 8 — see above

WATCHDOG_ENABLED = True
