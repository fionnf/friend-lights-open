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


print("\n%d failed\n" % len(failures) if failures else "\nall passed\n")
sys.exit(1 if failures else 0)
