# ============================================================
#  codec.py  —  Binary wire format for the shared lamp state
# ============================================================
# LoRaWAN payloads are small and expensive. At SF12 the EU868 maximum
# payload is 51 bytes, and The Things Network's Fair Use Policy allows
# 30 s of uplink airtime per device per day. Every byte costs airtime,
# and airtime is the budget that decides how often the lamps can speak.
#
# So the whole shared state is packed into 10 bytes:
#
#   byte 0   version (high nibble) | flags (low nibble)
#   byte 1   lamp_id           1-255  (0 is reserved / invalid)
#   byte 2-3 hue_total         uint16 big-endian, wrapping G-counter
#   byte 4-5 warm_total        uint16 big-endian, wrapping G-counter
#   byte 6-7 touch_count       uint16 big-endian, wrapping G-counter
#   byte 8   brightness        uint8  0-255
#   byte 9   reserved          always 0 — reject non-zero on decode? no:
#                              ignored, so the format can grow later
#
# Flags (low nibble of byte 0):
#   bit 0  lamp is powered on
#   bit 1  lamp was touched since the last uplink (activity hint)
#   bit 2  reserved
#   bit 3  reserved
#
# Big-endian because it is the conventional byte order for a documented
# wire protocol, and because TTN's own payload formatters and most
# decoders people will paste into the console assume it.

VERSION = 1
PAYLOAD_LEN = 10

FLAG_ON      = 0x1
FLAG_TOUCHED = 0x2

# Counters are uint16 and deliberately allowed to wrap. See shared_state.py
# for why wrapping is safe (and, for hue, actually the point).
COUNTER_MODULO = 0x10000


class DecodeError(ValueError):
    """Payload could not be understood. Callers must treat this as
    'drop the packet', never as a fatal error — the radio is a public
    medium and malformed frames are a normal occurrence, not a bug."""


def _u16(value):
    """Coerce to a wrapped uint16. Accepts negatives (Python's % is
    floored, so -1 becomes 65535, which is the wrap we want)."""
    return int(value) % COUNTER_MODULO


def encode(lamp_id, hue_total, warm_total, touch_count,
           brightness=0.6, on=True, touched=False):
    """Pack lamp state into exactly PAYLOAD_LEN bytes.

    brightness is taken as a float 0.0-1.0 and quantised to a byte;
    the counters are wrapped rather than clamped.
    """
    if not (1 <= int(lamp_id) <= 255):
        raise ValueError("lamp_id must be 1-255")

    flags = 0
    if on:
        flags |= FLAG_ON
    if touched:
        flags |= FLAG_TOUCHED

    hue   = _u16(hue_total)
    warm  = _u16(warm_total)
    touch = _u16(touch_count)

    bright = int(round(max(0.0, min(1.0, float(brightness))) * 255))

    return bytes((
        ((VERSION & 0xF) << 4) | (flags & 0xF),
        int(lamp_id) & 0xFF,
        (hue   >> 8) & 0xFF, hue   & 0xFF,
        (warm  >> 8) & 0xFF, warm  & 0xFF,
        (touch >> 8) & 0xFF, touch & 0xFF,
        bright & 0xFF,
        0,
    ))


def decode(payload):
    """Unpack a payload into a dict. Raises DecodeError on anything
    unusable — short frames, wrong version, reserved lamp_id 0."""
    if payload is None:
        raise DecodeError("no payload")
    data = bytes(payload)
    if len(data) < PAYLOAD_LEN:
        raise DecodeError("payload too short: %d bytes" % len(data))

    version = (data[0] >> 4) & 0xF
    if version != VERSION:
        # Refusing unknown versions is deliberate. A future format that
        # reuses these byte positions differently must not be silently
        # misread as a colour change.
        raise DecodeError("unsupported version: %d" % version)

    flags   = data[0] & 0xF
    lamp_id = data[1]
    if lamp_id == 0:
        raise DecodeError("lamp_id 0 is reserved")

    return {
        "lamp_id":     lamp_id,
        "hue_total":   (data[2] << 8) | data[3],
        "warm_total":  (data[4] << 8) | data[5],
        "touch_count": (data[6] << 8) | data[7],
        "brightness":  data[8] / 255.0,
        "on":          bool(flags & FLAG_ON),
        "touched":     bool(flags & FLAG_TOUCHED),
    }
