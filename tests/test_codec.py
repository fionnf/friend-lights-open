#!/usr/bin/env python3
"""
Wire format tests.

The radio is a public medium and a LoRaWAN downlink can be anything at
all. Every malformed frame must be rejected cleanly, because the
alternative — a garbled frame read as a colour change — is a lamp that
turns a strange colour for no reason and never explains why.

Run from the repo root:   python3 tests/test_codec.py
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "firmware", "lamp"))

import codec
from codec import encode, decode, DecodeError, PAYLOAD_LEN

failures = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name +
          (("  " + str(detail)) if detail and not cond else ""))
    if not cond:
        failures.append(name)


def rejects(name, payload):
    try:
        decode(payload)
        check(name, False, "accepted bad payload")
    except DecodeError:
        check(name, True)
    except Exception as e:
        check(name, False, "raised %s instead of DecodeError" % type(e).__name__)


# ── Size ─────────────────────────────────────────────────────
# Airtime is the daily budget, and payload length is what spends it.
print("\nsize")

frame = encode(1, 1000, 2000, 3, brightness=0.6, on=True)
check("payload is exactly %d bytes" % PAYLOAD_LEN, len(frame) == PAYLOAD_LEN,
      len(frame))
check("fits an SF12 uplink (51 bytes)", len(frame) <= 51)


# ── Round trip ───────────────────────────────────────────────
print("\nround trip")

out = decode(encode(7, 4242, 1337, 99, brightness=0.5, on=True, touched=True))
check("lamp_id",     out["lamp_id"] == 7, out["lamp_id"])
check("hue_total",   out["hue_total"] == 4242, out["hue_total"])
check("warm_total",  out["warm_total"] == 1337, out["warm_total"])
check("touch_count", out["touch_count"] == 99, out["touch_count"])
check("on flag",     out["on"] is True)
check("touched flag", out["touched"] is True)
check("brightness within a quantisation step",
      abs(out["brightness"] - 0.5) < 1 / 255.0, out["brightness"])

off = decode(encode(1, 0, 0, 0, on=False, touched=False))
check("off flag round trips", off["on"] is False)
check("touched flag round trips", off["touched"] is False)


# ── Boundaries ───────────────────────────────────────────────
print("\nboundaries")

hi = decode(encode(255, 65535, 65535, 65535, brightness=1.0))
check("max lamp_id",   hi["lamp_id"] == 255)
check("max counters",  hi["hue_total"] == 65535, hi["hue_total"])
check("max brightness", hi["brightness"] == 1.0, hi["brightness"])

lo = decode(encode(1, 0, 0, 0, brightness=0.0))
check("min brightness", lo["brightness"] == 0.0, lo["brightness"])

wrapped = decode(encode(1, 65536 + 5, 0, 0))
check("counters wrap rather than overflow", wrapped["hue_total"] == 5,
      wrapped["hue_total"])
negative = decode(encode(1, -1, 0, 0))
check("negative counter wraps to top", negative["hue_total"] == 65535,
      negative["hue_total"])

clamped = decode(encode(1, 0, 0, 0, brightness=99.0))
check("brightness clamps rather than wrapping", clamped["brightness"] == 1.0,
      clamped["brightness"])


# ── Rejection ────────────────────────────────────────────────
print("\nrejection")

rejects("empty payload",     b"")
rejects("None",              None)
rejects("truncated frame",   b"\x10\x01\x00")
rejects("lamp_id 0 reserved", bytes([0x10, 0, 0, 0, 0, 0, 0, 0, 0, 0]))
rejects("unknown version",   bytes([0xF0, 1, 0, 0, 0, 0, 0, 0, 0, 0]))

# A frame longer than we expect is a future version adding fields, not an
# error — decoding the part we understand keeps old lamps working.
longer = decode(encode(3, 11, 22, 33) + b"\xde\xad\xbe\xef")
check("trailing bytes ignored, not rejected", longer["lamp_id"] == 3)


# ── Invalid input to encode ──────────────────────────────────
print("\nencode guards")

for bad in (0, 256, -1):
    try:
        encode(bad, 0, 0, 0)
        check("rejects lamp_id %s" % bad, False, "accepted")
    except ValueError:
        check("rejects lamp_id %s" % bad, True)


print("\n%d failed" % len(failures) if failures else "\nall passed")
sys.exit(1 if failures else 0)
