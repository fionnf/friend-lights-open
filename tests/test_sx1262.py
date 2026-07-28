#!/usr/bin/env python3
"""
Finding the radio.

The register-level driver cannot be tested without the chip — reading a
register back is the whole test, and a stub that returns whatever it was
given would only be testing itself. What CAN be tested, and is worth
testing, is the layer above: which pinout gets tried, in what order, and
what happens to the attempts that fail.

That matters because there are two ways to attach a Wio-SX1262 to a XIAO
and they share no control pins. Getting it wrong reads back as all
zeros, which is indistinguishable from a dead board — so the firmware
tries both rather than asking anyone to know which they bought.

Run from the repo root:   python3 tests/test_sx1262.py
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "stubs"))
sys.path.insert(0, os.path.join(ROOT, "firmware", "lamp"))

from net import sx1262                                       # noqa: E402
from net.sx1262 import SX1262, PINOUTS, open_radio           # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name +
          (("\n          " + str(detail)) if detail and not cond else ""))
    if not cond:
        failures.append(name)


def quiet(*args):
    pass


B2B = dict(PINOUTS[0][1])
HEADER = dict(PINOUTS[1][1])


class FakeRadio:
    """Answers only if it was built on the pinout the 'board' has."""

    present = None          # which pins the imaginary module is wired to
    built = []
    closed = []

    def __init__(self, spi_id=1, **pins):
        self.pins = pins
        FakeRadio.built.append(dict(pins))

    def probe(self):
        if self.pins == FakeRadio.present:
            return True, "SPI ok, register read-back matches"
        return False, "SPI returned 0000 — check MISO, MOSI, SCK and NSS"

    def close(self):
        FakeRadio.closed.append(dict(self.pins))


class Patched:
    """Swap the driver for the fake, for the duration of a test."""

    def __enter__(self):
        self.real = sx1262.SX1262
        sx1262.SX1262 = FakeRadio
        FakeRadio.built = []
        FakeRadio.closed = []
        return FakeRadio

    def __exit__(self, *exc):
        sx1262.SX1262 = self.real
        return False


# ── The two ways a module can be attached ────────────────────
print("\nFinding the module")

with Patched() as fake:
    fake.present = B2B
    radio, name = open_radio(log=quiet)
    check("the kit's board-to-board module is found",
          radio is not None and name == "B2B kit", name)
    check("and nothing else was tried after it",
          len(fake.built) == 1, fake.built)

with Patched() as fake:
    fake.present = HEADER
    radio, name = open_radio(log=quiet)
    check("the standalone module on the header is found too",
          radio is not None and name == "header module", name)
    check("after the B2B pinout was tried first",
          len(fake.built) == 2 and fake.built[0] == B2B, fake.built)
    # A failed attempt that keeps NSS and RST driven holds the chip on
    # the other pinout in reset, so the second attempt would fail for a
    # reason the first one created.
    check("and the failed attempt let go of its pins",
          fake.closed == [B2B], fake.closed)

with Patched() as fake:
    fake.present = None
    radio, reason = open_radio(log=quiet)
    check("no module at all is reported, not raised",
          radio is None and isinstance(reason, str), reason)
    check("both pinouts were tried before giving up",
          len(fake.built) == 2, fake.built)
    check("and both were released",
          len(fake.closed) == 2, fake.closed)


# ── config.py wins ───────────────────────────────────────────
print("\nWhat config.py asks for")

ODD = {"sck": 7, "mosi": 9, "miso": 8,
       "nss": 20, "reset": 21, "busy": 22, "dio1": 23}

with Patched() as fake:
    fake.present = ODD
    radio, name = open_radio(preferred=ODD, log=quiet)
    check("a board that is neither is found from config.py",
          radio is not None and name == "config.py", name)
    check("and it was tried before the guesses",
          fake.built[0] == ODD, fake.built)

with Patched() as fake:
    # Naming the standard pins in config.py is the common case — every
    # generated config does it. It must not cost a duplicate probe.
    fake.present = None
    open_radio(preferred=B2B, log=quiet)
    check("naming a known pinout does not probe it twice",
          len(fake.built) == 2, fake.built)


# ── Pins the lamp is already using ───────────────────────────
print("\nNot trampling the strip")

with Patched() as fake:
    fake.present = HEADER
    # GPIO2 is BUSY on the header pinout and the LED data line by
    # default. Probing drives it, and driving it writes garbage down the
    # strip — so it must be skipped rather than tried.
    radio, reason = open_radio(avoid=[2], log=quiet)
    check("a pinout that collides with the LED line is not probed",
          all(p != HEADER for p in fake.built), fake.built)
    check("and the reason says which pin and why",
          radio is None and "GPIO2" in reason, reason)

with Patched() as fake:
    fake.present = B2B
    radio, name = open_radio(avoid=[2, 4], log=quiet)
    check("while the B2B pinout, which collides with neither, still works",
          radio is not None and name == "B2B kit", name)


# ── The real driver, as far as it can go without a chip ──────
print("\nThe driver itself")

# Not a functional test — the stub bus reads back zeros. It only proves
# the constructor and close() actually run, which is the one thing about
# this file that a syntax-clean import would otherwise hide.
radio = SX1262(spi_id=1, **B2B)
check("it constructs on the stub bus", radio.pins == B2B, radio.pins)
ok, detail = radio.probe()
check("and reports an all-zero bus as absent, not as working",
      ok is False and "MISO" in detail, detail)
radio.close()
check("close() releases the bus", radio._spi.deinit_count == 1)
check("and stops driving NSS and RST",
      radio._nss.mode == 1 and radio._reset.mode == 1)


# ── The bytes on the wire ────────────────────────────────────
# The chip cannot be simulated, but the SPI transactions can be READ.
# Each check below pins a byte sequence to the datasheet, because every
# fault in this family is silent on hardware: a response mis-framed by
# one byte reads as "TX never completes" on a radio that is transmitting
# perfectly, and a missing errata write reads as nothing at all — just
# fewer of the friend's messages arriving. This is the only place these
# can fail loudly.
print("\nThe bytes on the wire")


class ScriptedSPI:
    """Records every write; serves queued reads, then zeros."""

    def __init__(self):
        self.written = []
        self.queue = []

    def write(self, data):
        self.written.append(bytes(data))

    def read(self, n, write=0x00):
        if self.queue:
            out = self.queue.pop(0)
            return bytes(out[:n]) + bytes(n - len(out[:n]))
        return bytes(n)

    def deinit(self):
        pass

    def wrote(self, prefix):
        return any(w[:len(prefix)] == bytes(prefix) for w in self.written)


bus = ScriptedSPI()
radio = SX1262(spi=bus, **B2B)

ok = radio.begin(frequency=868_100_000, sf=9, power=14)
check("begin() succeeds on the scripted bus", ok is True)

# ── Response framing — THE regression ──
# GetIrqStatus answers [status][irq 15:8][irq 7:0] starting at the byte
# AFTER the opcode. SPI is full duplex, so a NOP included in the write
# consumes the status byte invisibly and every later index is off by
# one: TX_DONE (0x0001) reads back as 0x01xx, the driver waits for a
# completion that already happened, and every send "times out" on
# hardware that transmitted. probe() still passes. This is the exact
# fault this file exists to keep out.
bus.written = []
bus.queue = [b"\x00\x00\x01"]        # status, irq15:8, irq7:0 = TX_DONE
status = radio.irq_status()
check("GET_IRQ_STATUS writes the opcode alone, no NOP",
      bus.written[-1] == b"\x12", bus.written[-1])
check("so TX_DONE in the low byte reads back as 0x0001",
      status == 0x0001, hex(status))

# ── Frequency ──
# 868.1 MHz in PLL steps of 32 MHz / 2^25, computed in exact integer
# math — hz << 25 needs 55 bits and this port's floats carry 24.
expected = (868_100_000 << 25) // 32_000_000
freq_cmd = bytes([0x86, (expected >> 24) & 0xFF, (expected >> 16) & 0xFF,
                  (expected >> 8) & 0xFF, expected & 0xFF])
bus.written = []
radio.set_frequency(868_100_000)
check("frequency bytes are the exact PLL steps for 868.1 MHz",
      any(w == freq_cmd for w in bus.written), bus.written)

# ── Image calibration ──
# Receive-side only, so a missing one is invisible from the TX side.
check("image calibration ran for the 863-870 MHz band",
      radio._cal_band == b"\xD7\xDB", radio._cal_band)
bus.written = []
radio.set_frequency(869_525_000)     # RX2 — same band
check("and is not repeated while staying inside the band",
      not bus.wrote(b"\x98"), bus.written)

# ── The errata, by register ──
bus.written = []
radio._set_packet_params(32, rx=True)
check("RX (inverted IQ) clears bit 2 of 0x0736 — errata 15.4",
      any(w[:3] == b"\x0D\x07\x36" and not (w[3] & 0x04)
          for w in bus.written if len(w) == 4), bus.written)
bus.written = []
radio._set_packet_params(32, rx=False)
check("TX (standard IQ) sets it again",
      any(w[:3] == b"\x0D\x07\x36" and (w[3] & 0x04)
          for w in bus.written if len(w) == 4), bus.written)

bus.written = []
radio._set_pa(14)
check("PA clamp bits 4:1 are set in 0x08D8 — errata 15.2",
      any(w[:3] == b"\x0D\x08\xD8" and (w[3] & 0x1E) == 0x1E
          for w in bus.written if len(w) == 4), bus.written)

# ── The rest of begin(), against the datasheet ──
bus2 = ScriptedSPI()
r2 = SX1262(spi=bus2, **B2B)
r2.begin(frequency=868_100_000, sf=9, power=14)
check("TCXO: DIO3 at 1.8 V (code 0x02), before anything else",
      bus2.wrote(b"\x97\x02"), None)
check("device errors cleared after the TCXO-less calibrate",
      bus2.wrote(b"\x07\x00\x00"), None)
check("sync word 0x3444 — the public network's, not the default",
      bus2.wrote(b"\x0D\x07\x40\x34\x44"), None)
check("boosted RX gain (0x96) for the always-open Class C receiver",
      bus2.wrote(b"\x0D\x08\xAC\x96"), None)
check("DIO2 switches the antenna path",
      bus2.wrote(b"\x9D\x01"), None)

# ── A whole send ──
bus.written = []
bus.queue = [b"\x00\x00\x00",        # first irq poll: nothing yet
             b"\x00\x00\x01"]        # then TX_DONE
sent = radio.send(b"0123456789")
check("send() completes when TX_DONE arrives", sent is True)
check("the payload went to buffer offset 0",
      bus.wrote(b"\x0E\x00" + b"0123456789"), bus.written)
check("and TX started with no chip-side timeout",
      bus.wrote(b"\x83\x00\x00\x00"), None)


# ── The vendored upstream driver ─────────────────────────────
# mp_lora/ is byte-identical micropython-lib code, so its behaviour is
# upstream's to answer for — but that it PARSES, IMPORTS against the
# stubs, and still exposes the class the adapter names is ours to
# check, because a vendoring mistake fails at someone's kitchen table.
print("\nThe vendored upstream driver")

import py_compile

MP_LORA = os.path.join(ROOT, "firmware", "lamp", "net", "mp_lora")
for name in sorted(os.listdir(MP_LORA)):
    if name.endswith(".py"):
        try:
            py_compile.compile(os.path.join(MP_LORA, name), doraise=True)
            ok = True
        except py_compile.PyCompileError as e:
            ok = False
        check("%s compiles" % name, ok)

# MicroPython's `time` is our utime; alias it so the import works here.
import utime
sys.modules.setdefault("time", utime)
try:
    import net.mp_lora as mp_lora
    check("the package imports against the stubs", True)
    check("and exposes the SX1262 the adapter constructs",
          hasattr(mp_lora, "SX1262"))
except Exception as e:
    check("the package imports against the stubs", False, repr(e))

from net.sx1262_mplib import UpstreamSX1262
for method in ("begin", "listen", "receive", "send",
               "set_frequency", "set_modulation", "sleep", "close"):
    check("the facade speaks %s()" % method,
          callable(getattr(UpstreamSX1262, method, None)))


print("\n%d failed\n" % len(failures) if failures else "\nall passed\n")
sys.exit(1 if failures else 0)
