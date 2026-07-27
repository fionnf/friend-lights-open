# ============================================================
#  radio_check.py  —  Run this on the lamp before anything else
# ============================================================
# Copy to the board and run it. It checks the radio from the bottom up
# and stops at the first thing that is wrong, so you find out whether it
# is wiring, the TCXO, or the network — rather than staring at a lamp
# that does nothing.
#
#   mpremote connect /dev/ttyACM0 cp tools/radio_check.py :
#   mpremote connect /dev/ttyACM0 run radio_check.py
#
# It transmits. Attach the antenna first — transmitting into an open
# connector can damage the PA.

import sys
import utime

sys.path.append("/lamp")

from net.sx1262 import SX1262            # noqa: E402
from net.lorawan_crypto import build_uplink   # noqa: E402

try:
    import config
except ImportError:
    config = None


def cfg(name, default):
    return getattr(config, name, default) if config else default


def hexb(value, length):
    cleaned = str(value).replace(" ", "")
    if len(cleaned) != length * 2:
        return None
    try:
        return bytes(int(cleaned[i:i + 2], 16)
                     for i in range(0, len(cleaned), 2))
    except ValueError:
        return None


print("\n=== Wio-SX1262 check ===\n")

# ── 1. Pins ──────────────────────────────────────────────────
# The kit's board-to-board connector and the standalone module's header
# use completely different pins. Picking the wrong set is the most
# common reason for "SPI reads all zeros".
pins = dict(sck=cfg("SX_SCK_PIN", 7), mosi=cfg("SX_MOSI_PIN", 9),
            miso=cfg("SX_MISO_PIN", 8), nss=cfg("SX_NSS_PIN", 41),
            reset=cfg("SX_RESET_PIN", 42), busy=cfg("SX_BUSY_PIN", 40),
            dio1=cfg("SX_DIO1_PIN", 39))
print("1. pins: %s" % pins)
print("   B2B kit expects NSS 41, RST 42, BUSY 40, DIO1 39")
print("   header module expects NSS 4 — set SX_*_PIN in config.py\n")

radio = SX1262(spi_id=cfg("SX_SPI_ID", 1), **pins)

# ── 2. Is the chip there? ────────────────────────────────────
ok, detail = radio.probe()
print("2. SPI + reset: %s" % ("OK" if ok else "FAILED"))
print("   %s\n" % detail)
if not ok:
    print("   Stop here. Nothing else can work until this passes.")
    print("   Check the B2B connector is seated, or the header wiring.")
    raise SystemExit(1)

# ── 3. Bring it up, TCXO and all ─────────────────────────────
# probe() only proves SPI. The TCXO is what decides whether the radio
# has a clock, and without it everything above still "succeeds" while
# transmitting nothing.
started = radio.begin(frequency=868_100_000, sf=cfg("LORA_SF", 9),
                      power=cfg("LORA_TX_POWER", 14))
print("3. begin() with TCXO on DIO3: %s" % ("OK" if started else "FAILED"))
if not started:
    print("   The chip answered SPI but would not configure.")
    print("   Usually the TCXO voltage — this module wants 1.8 V.")
    raise SystemExit(1)
print("   frequency 868.1 MHz, SF%d, sync word 3444 (public)\n"
      % cfg("LORA_SF", 9))

# ── 4. Transmit ──────────────────────────────────────────────
# A real LoRaWAN frame if keys are configured, so a gateway in range can
# actually decode it and it shows up in the TTN console.
dev_addr = hexb(cfg("LORA_DEV_ADDR", ""), 4)
nwk = hexb(cfg("LORA_NWK_SKEY", ""), 16)
app = hexb(cfg("LORA_APP_SKEY", ""), 16)

if dev_addr and nwk and app:
    frame = build_uplink(bytes(reversed(dev_addr)), nwk, app,
                         0, cfg("LORA_PORT", 8), b"radiocheck")
    print("4. transmitting a real LoRaWAN frame (fcnt 0)")
    print("   %d bytes: %s" % (len(frame), frame.hex()))
else:
    frame = b"radio check"
    print("4. transmitting a plain LoRa packet")
    print("   No ABP keys in config, so this will NOT appear in TTN —")
    print("   it only proves the radio transmits.")

sent = radio.send(frame)
print("   TX_DONE: %s\n" % ("yes" if sent else "NO — timed out"))
if not sent:
    print("   The chip accepted the packet but never reported finishing.")
    print("   Almost always the TCXO, or DIO2 not switching the antenna.")
    raise SystemExit(1)

# ── 5. Listen ────────────────────────────────────────────────
print("5. listening on RX2 (869.525 MHz SF9) for 30 s")
print("   Queue a downlink in the TTN console to test this.")
radio.listen(869_525_000, 9)
deadline = utime.ticks_add(utime.ticks_ms(), 30_000)
heard = None
while utime.ticks_diff(deadline, utime.ticks_ms()) > 0:
    heard = radio.receive()
    if heard:
        break
    utime.sleep_ms(50)

if heard:
    print("   heard %d bytes: %s\n" % (len(heard), heard.hex()))
else:
    print("   nothing heard — expected unless you queued a downlink\n")

print("=== done ===")
print("If 1-4 passed, the radio works and the antenna is connected.")
print("Whether TTN SEES you is a separate question: check Live data in")
print("the console. An uplink that never appears there, when this")
print("passed, means no gateway is in range — not a hardware fault.")
