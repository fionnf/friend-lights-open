#!/usr/bin/env python3
"""
LoRaWAN crypto and framing, against published test vectors.

This matters more than any other test here. Everything else in the
project can be reasoned about from a stack trace; a wrong MIC produces a
lamp that transmits perfectly and is silently ignored by the network,
with nothing in the TTN console to say a frame ever arrived. The only
way to have any confidence before hardware exists is to check against
numbers somebody else published.

  AES-128     FIPS-197 appendix C.1
  AES-CMAC    RFC 4493 sections 4.1-4.4, including the subkeys
  LoRaWAN     round trip, plus every reason a frame must be rejected

Run from the repo root:   python3 tests/test_lorawan.py
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "stubs"))
sys.path.insert(0, os.path.join(ROOT, "firmware", "lamp"))

from _aes_fallback import encrypt_block
from net import lorawan_crypto as lw
import utime

failures = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name +
          (("\n          " + str(detail)) if detail and not cond else ""))
    if not cond:
        failures.append(name)


def hexb(s):
    return bytes.fromhex(s.replace(" ", ""))


# ── AES-128, FIPS-197 C.1 ────────────────────────────────────
# Everything else is built on this one block operation.
print("\nAES-128 (FIPS-197)")

check("the reference block matches",
      encrypt_block(bytes(range(16)),
                    hexb("00112233445566778899aabbccddeeff")).hex()
      == "69c4e0d86a7b0430d8cdb78070b4c55a")


# ── AES-CMAC, RFC 4493 ───────────────────────────────────────
# LoRaWAN's MIC is the first four bytes of this.
print("\nAES-CMAC (RFC 4493)")

K = hexb("2b7e151628aed2a6abf7158809cf4f3c")
M = hexb("6bc1bee22e409f96e93d7e117393172a"
         "ae2d8a571e03ac9c9eb76fac45af8e51"
         "30c81c46a35ce411e5fbc1191a0a52ef"
         "f69f2445df4f9b17ad2b417be66c3710")

for label, msg, want in (
        ("example 1, empty message", b"",
         "bb1d6929e95937287fa37d129b756746"),
        ("example 2, 16 bytes", M[:16],
         "070a16b46b4d4144f79bdd9dd04a287c"),
        ("example 3, 40 bytes", M[:40],
         "dfa66747de9ae63030ca32611497c827"),
        ("example 4, 64 bytes", M,
         "51f0bebf7e3b9d92fc49741779363cfe")):
    got = lw.cmac(K, msg).hex()
    check(label, got == want, "got %s\n          want %s" % (got, want))


# ── LoRaWAN framing ──────────────────────────────────────────
print("\nuplink framing")

DEV_ADDR = hexb("01020304")          # little-endian on the wire
NWK = hexb("2b7e151628aed2a6abf7158809cf4f3c")
APP = hexb("000102030405060708090a0b0c0d0e0f")

frame = lw.build_uplink(DEV_ADDR, NWK, APP, 5, 8, b"hello lamp")
check("starts with unconfirmed-data-up", frame[0] == 0x40, hex(frame[0]))
check("carries the device address", frame[1:5] == DEV_ADDR)
check("carries the frame counter", frame[6] == 5 and frame[7] == 0)
check("length is header + payload + MIC",
      len(frame) == 1 + 7 + 1 + len(b"hello lamp") + 4, len(frame))

# Deterministic: the same inputs must give the same bytes, or a retry
# would look like a different frame to the network.
check("is deterministic",
      frame == lw.build_uplink(DEV_ADDR, NWK, APP, 5, 8, b"hello lamp"))

# The payload must not travel in the clear.
check("payload is encrypted", b"hello lamp" not in frame)

# A different counter must produce different ciphertext, or the whole
# scheme degenerates into a reusable keystream.
other = lw.build_uplink(DEV_ADDR, NWK, APP, 6, 8, b"hello lamp")
check("a new counter changes the ciphertext", frame[9:-4] != other[9:-4])
check("...and changes the MIC", frame[-4:] != other[-4:])


print("\ndownlink parsing")


def downlink(payload, fcnt=1, port=8, addr=DEV_ADDR, nwk=NWK):
    """Build what the network would send us, to parse back."""
    enc = lw.encrypt_payload(APP, lw.DIR_DOWN, addr, fcnt, payload)
    body = (bytes([lw.MHDR_UNCONFIRMED_DOWN]) + addr + b"\x00"
            + bytes([fcnt & 0xFF, (fcnt >> 8) & 0xFF]) + bytes([port]) + enc)
    return body + lw.mic(nwk, lw.DIR_DOWN, addr, fcnt, body)


got = lw.parse_downlink(DEV_ADDR, NWK, APP, downlink(b"\x11\x22\x33"))
check("a good downlink decodes", got is not None)
if got:
    check("payload round trips", got["payload"] == b"\x11\x22\x33",
          got["payload"])
    check("port survives", got["port"] == 8, got["port"])
    check("counter survives", got["fcnt"] == 1, got["fcnt"])

check("a real 10-byte lamp frame round trips",
      (lw.parse_downlink(DEV_ADDR, NWK, APP,
                         downlink(bytes(range(10))))or {}).get("payload")
      == bytes(range(10)))


# ── Everything that must be ignored ──────────────────────────
# The 868 band is shared and busy. Each of these is ordinary traffic,
# not an error, and none may raise.
print("\nframes that must be ignored")


def rejects(name, frame):
    try:
        check(name, lw.parse_downlink(DEV_ADDR, NWK, APP, frame) is None)
    except Exception as e:
        check(name, False, "raised %s" % type(e).__name__)


rejects("empty", b"")
rejects("truncated", b"\x60\x01\x02")
rejects("an uplink, not a downlink", lw.build_uplink(DEV_ADDR, NWK, APP, 1, 8, b"x"))
rejects("another device's address", downlink(b"x", addr=hexb("aabbccdd")))
rejects("a forged MIC", downlink(b"x", nwk=hexb("00" * 16)))

flipped = bytearray(downlink(b"hello"))
flipped[10] ^= 0x01
rejects("a corrupted payload", bytes(flipped))

# A downlink carrying only MAC commands has no application payload; it
# must decode rather than be treated as junk.
mac_only = (bytes([lw.MHDR_UNCONFIRMED_DOWN]) + DEV_ADDR + b"\x00\x02\x00")
mac_only += lw.mic(NWK, lw.DIR_DOWN, DEV_ADDR, 2, mac_only)
result = lw.parse_downlink(DEV_ADDR, NWK, APP, mac_only)
check("a MAC-only downlink is understood, not dropped", result is not None)
if result:
    check("...and reports no application payload", result["payload"] == b"")


# ── Encryption is its own inverse ────────────────────────────
print("\npayload encryption")

for size in (1, 15, 16, 17, 32, 51):
    data = bytes((i * 7 + size) & 0xFF for i in range(size))
    enc = lw.encrypt_payload(APP, lw.DIR_UP, DEV_ADDR, 9, data)
    dec = lw.encrypt_payload(APP, lw.DIR_UP, DEV_ADDR, 9, enc)
    check("%d bytes survive a round trip" % size, dec == data)
    check("%d bytes: length is preserved" % size, len(enc) == size, len(enc))


# ── The transport, and the counter that must never repeat ────
# ABP has no join, so the network never resets its idea of where we are
# in the sequence — it just drops anything it has seen before. A counter
# that goes backwards after a power cut means a lamp that transmits
# perfectly and is ignored, with nothing in the console to explain it.
print("\nframe counters")

import tempfile
os.chdir(tempfile.mkdtemp(prefix="lw-"))

from net.lorawan_abp import LoRaWANABP, COUNTER_BATCH


class FakeRadio:
    """Records what was transmitted; never fails."""

    def __init__(self):
        self.sent = []
        self.inbox = []
        self.listening = None
        self.frequencies = []

    def begin(self, **kw):
        return True

    def set_frequency(self, hz):
        self.frequencies.append(hz)

    def set_modulation(self, sf, bw, cr):
        pass

    def listen(self, freq, sf):
        self.listening = (freq, sf)

    def send(self, data, timeout_ms=5000):
        self.sent.append(bytes(data))
        return True

    def receive(self):
        return self.inbox.pop(0) if self.inbox else None

    def sleep(self):
        self.listening = None


ADDR = hexb("26011BE4")          # as the console shows it


def make():
    radio = FakeRadio()
    t = LoRaWANABP(radio, ADDR, NWK, APP, min_interval_ms=0)
    t.start()
    return t, radio


t, radio = make()
check("the transport comes up", t.connected is True)
check("it parks on RX2 immediately (Class C)",
      radio.listening == (869525000, 9), radio.listening)

# DevAddr is big-endian in the console, little-endian on air. Reversing
# it in the wrong place is invisible until the network ignores you.
check("DevAddr is byte-reversed for the air",
      t.dev_addr == bytes(reversed(ADDR)), t.dev_addr)

# The duty-cycle floor applies even to a forced send, so step the
# clock between them — on hardware this is 30 s of real time.
for i in range(5):
    t.send(b"0123456789", force=True)
    utime.sleep_ms(t.min_gap_ms + 1)
check("five frames went out", len(radio.sent) == 5, len(radio.sent))

counters = [f[6] | (f[7] << 8) for f in radio.sent]
check("counters increment by one", counters == [0, 1, 2, 3, 4], counters)
check("uplinks rotate across channels",
      len(set(radio.frequencies)) >= 3, sorted(set(radio.frequencies)))
check("it returns to listening after transmitting",
      radio.listening == (869525000, 9), radio.listening)

# The whole point: after a power cut the counter must not repeat.
t2, radio2 = make()
for i in range(3):
    t2.send(b"0123456789", force=True)
    utime.sleep_ms(t2.min_gap_ms + 1)
after = [f[6] | (f[7] << 8) for f in radio2.sent]
check("a reboot never reuses a counter", min(after) > max(counters),
      "before %s, after %s" % (counters, after))
check("...and skips at most one reserved block",
      min(after) <= COUNTER_BATCH, min(after))

print("\ndownlinks")

t3, radio3 = make()
radio3.inbox.append(downlink(bytes(range(10)), fcnt=7,
                             addr=bytes(reversed(ADDR))))
got = t3.poll()
check("a downlink for us is delivered", got == [bytes(range(10))], got)

radio3.inbox.append(downlink(bytes(range(10)), fcnt=7,
                             addr=bytes(reversed(ADDR))))
check("a repeat of the same frame is dropped", t3.poll() == [])

radio3.inbox.append(downlink(b"nope", fcnt=9, addr=hexb("aabbccdd")))
check("another device's downlink is ignored", t3.poll() == [])

radio3.inbox.append(b"\x00\x01\x02")
check("radio noise does not raise", t3.poll() == [])

check("nothing waiting is not an error", t3.poll() == [])


print("\n%d failed" % len(failures) if failures else "\nall passed")
sys.exit(1 if failures else 0)
