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
LAMP_NAME = ""                # optional; appears in the WiFi network name

# ── Which radio ─────────────────────────────────────────────
# "SX1262" Wio-SX1262 — a bare radio, so the LoRaWAN stack runs on the
#          ESP32 in Python. Uses ABP, because an OTAA join needs a
#          receive window opened 5 s after transmitting and held for
#          milliseconds, which MicroPython's garbage collector can pause
#          straight through.
# "E5"     Wio-E5 — runs the LoRaWAN stack itself, driven by AT commands
#          over UART. Uses OTAA. Certified firmware, so lower risk, but
#          it is a different module — it does not fit the XIAO kit.
LORA_RADIO = "SX1262"

# ── SX1262: the ABP session, from the TTN console ───────────
# Register the device with Activation mode = ABP, then copy these.
# DevAddr is shown big-endian; the firmware reverses it for the air.
LORA_DEV_ADDR = ""             # 8 hex characters
LORA_NWK_SKEY = ""             # 32 hex
LORA_APP_SKEY = ""             # 32 hex
LORA_SF       = 9              # must match RX2 on your frequency plan
LORA_TX_POWER = 14             # dBm; EU868 legal ceiling

# Which code drives the chip (the LoRaWAN layer above is ours either
# way). "upstream" = micropython-lib's SX1262 driver, maintained by
# MicroPython's own maintainers — the default. "native" = this
# project's register-level driver, kept as probe and fallback.
LORA_DRIVER   = "upstream"

# SPI to the Wio-SX1262 — the BOARD-TO-BOARD kit pins.
#
# You can usually ignore this block. There are two ways to attach the
# module and they use different pins, so the firmware probes both at
# startup and keeps whichever answers; these are only the first guess.
# Set them for a board that is neither.
SX_SPI_ID    = 1
SX_SCK_PIN   = 7
SX_MOSI_PIN  = 9
SX_MISO_PIN  = 8
SX_NSS_PIN   = 41
SX_RESET_PIN = 42
SX_BUSY_PIN  = 40
SX_DIO1_PIN  = 39

# Whether this lamp uses LoRa at all. Applies to BOTH radios — it is
# not part of the E5 block below.
LORA_ENABLED = True

# ── E5 only: OTAA keys (The Things Network) ─────────────────
# Ignore all of this if LORA_RADIO is "SX1262".
# Register the device in the TTN console, then paste its values here.
# Use OTAA. DevEui is per-device; AppEui and AppKey come from the
# application you registered it under.
# DevEUI: unique per lamp — let TTN generate it.
LORA_DEV_EUI = "0000000000000000"
# JoinEUI (called AppEUI in the older spec): identifies the join server,
# so it is the SAME on both lamps. TTN's docs say all-zeros is fine, and
# it usually is — but some LoRaWAN stacks read all-zeros as "not
# configured yet" and silently refuse to join. Making one up costs
# nothing and removes the possibility, so use any non-zero value and put
# the identical one in the TTN console.
LORA_APP_EUI = "0011223344556677"
LORA_APP_KEY = "00000000000000000000000000000000"
LORA_REGION  = "EU868"        # EU868 / US915 / AU915 / AS923 ...
LORA_CLASS   = "C"            # C: mains-powered, receives at any time
LORA_PORT    = 8

# UART pins to the Wio-E5. Any two free pins will do.
LORA_UART_ID = 1
LORA_TX_PIN  = 43
LORA_RX_PIN  = 44
LORA_BAUD    = 9600

# How many messages a day this lamp may send, and how many may go out
# back-to-back before that average applies. Spent as a token bucket, so
# the first LORA_BURST touches of a quiet day transmit IMMEDIATELY and
# the budget refills steadily; only an unusually busy run ever waits.
#
# 0 = no daily budget. That is allowed, and it is NOT unlimited: the
# EU868 duty cycle still applies (see below), so the fastest this lamp
# will ever speak is one message every 30 s.
#
# Worth knowing before you raise it: every message you send becomes a
# DOWNLINK on your friend's lamp, and downlinks are the expensive
# direction. TTN's Fair Use Policy asks for at most 10 a day per
# device, and while nothing enforces that, a gateway physically cannot
# receive while it transmits — so heavy downlink use degrades the
# shared gateway for everyone near it, including you. 48 is generous
# and still neighbourly.
LORA_DAILY_BUDGET = 48
LORA_BURST        = 6

# The duty cycle is the one limit that is LAW rather than etiquette.
# EU868 allows a device 1% per sub-band; at ~0.25 s of airtime per
# frame that is a gap of ~25 s, and nothing else in the stack enforces
# it. The firmware therefore never sends faster than every 30 s, no
# matter what the budget above says.
#
# LORA_MIN_INTERVAL_MS still works if you prefer to set the gap
# directly — it overrides LORA_DAILY_BUDGET when present.

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
LED_PIN        = 2             # data line, through the 330 ohm resistor
NUM_LEDS       = 10            # how many LEDs on your strip
LED_BRIGHTNESS = 0.6
LED_ORDER      = "GRBW"        # SK6812 RGBW. "GRB" for WS2812 (no white)
REVERSE_LEDS   = False         # True if wired from the far end

# ── Colour zones ────────────────────────────────────────────
# The strip is split into zones, each its own colour, reshuffled on every
# touch — as in the original project. Both lamps derive identical zones
# from the shared counter, so this costs nothing on the wire.
#
# NUM_GROUPS = 1 gives one colour across the whole strip.
NUM_GROUPS     = 3
GROUP_MIN_LEDS = 1             # smallest a zone may be
GROUP_MAX_LEDS = 8             # largest a zone may be
GROUP_SPREAD   = 0.35          # how far zones stray from the main colour
                               # 0.0 = all identical, 1.0 = wildly apart

# ── Touch ───────────────────────────────────────────────────
# On ESP32-S3 these are native capacitive touch channels — no external
# resistor, no calibration hack. Set to [] for a lamp with no touch pad.
TOUCH_PINS      = [4]
TOUCH_THRESHOLD = 20000

# ── Feel ────────────────────────────────────────────────────
# How long the colour takes to settle once a friend's touch arrives.
# A few seconds reads as almost-instant; 90 seconds reads as post
# arriving rather than a text. Taste, not protocol — the radio path
# itself takes ~5-10 s either way.
ARRIVAL_FADE_MS = 6 * 1000

BREATHE_SPEED = 0.0008
BREATHE_DEPTH = 0.04



# ── Control network ─────────────────────────────────────────
# The lamp runs its own WiFi network permanently, so you can control it
# from a phone at any time without spending any of the daily message
# budget. Join the network named below and the page opens by itself; if
# it does not, browse to http://192.168.4.1
#
# WPA2 needs at least 8 characters. A shorter one is silently ignored by
# the ESP32 and you would get an OPEN network without being told.
PORTAL_ENABLED   = True
PORTAL_ALWAYS_ON = True
PORTAL_SSID      = "deLENIghted-1"   # max 32 characters
PORTAL_PASSWORD  = "lightupleni"        # min 8 — see above

# ── Watchdog ────────────────────────────────────────────────
# Reboots the board if the main loop stops feeding it for 8 s, so a hang
# becomes one restart rather than a dead lamp.
WATCHDOG_ENABLED = True
