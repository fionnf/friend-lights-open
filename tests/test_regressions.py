#!/usr/bin/env python3
"""
Regressions — one case per bug that was actually shipped and found.

Every test here failed before its fix. Nothing goes in this file
speculatively; if it is here, the lamp really did do the wrong thing.

Run from the repo root:   python3 tests/test_regressions.py
"""
import os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "stubs"))
sys.path.insert(0, os.path.join(ROOT, "firmware", "lamp"))
sys.path.insert(0, os.path.join(ROOT, "firmware"))

import utime
import codec
from shared_state import SharedColour
from net.transport import Transport, Router

failures = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name +
          (("  " + str(detail)) if detail and not cond else ""))
    if not cond:
        failures.append(name)


# ── One press must produce exactly one event ─────────────────
# Was: "hold" fired at 1.2 s on the way to "long_hold" at 5 s, so opening
# the setup portal always toggled the lamp off first. You cannot tell a
# long press from a short one until the finger lifts.
print("\none press, one event")

from touch import TouchSensor, HOLD_TIME_MS, LONG_HOLD_TIME_MS


class Pad:
    def __init__(self):
        self.v = 1000

    def read(self):
        return self.v


def press(ms):
    s = TouchSensor.__new__(TouchSensor)
    s._pad = Pad()
    s._threshold = 100
    s._baseline = 1000
    s._touched = False
    s._started = 0
    events = []
    s._pad.v = 2000                             # finger down
    for _ in range(int(ms / 50) + 1):
        e = s.update()
        if e:
            events.append(e)
        utime.sleep_ms(50)
    s._pad.v = 1000                             # release
    e = s.update()
    if e:
        events.append(e)
    return events


short = press(200)
check("a brief press is one tap", short == ["tap"], short)

held = press(HOLD_TIME_MS + 400)
check("a 1.6 s press is one hold", held == ["hold"], held)

long_press = press(LONG_HOLD_TIME_MS + 500)
check("a 5.5 s press is ONE long_hold, not hold+long_hold",
      long_press == ["long_hold"], long_press)


# ── No allocation while the radio is throttled ───────────────
# Was: `if dirty and router.send(build())` rebuilt the frame on every pass
# of a ~1000 Hz loop, because Python evaluates the argument before the
# call can refuse it. With LoRaWAN throttled to 15 minutes that is about
# a million discarded allocations between two sends — and if nothing is
# connected, it never stops.
print("\nno allocation while throttled")


class Throttled(Transport):
    name = "lora"
    min_interval_ms = 15 * 60 * 1000

    def __init__(self):
        Transport.__init__(self)
        self.connected = True
        self.sent = 0

    def _send(self, payload):
        self.sent += 1


built = [0]
shared = SharedColour(1)


def build_frame():
    built[0] += 1
    h, w, t = shared.my_totals()
    return codec.encode(1, h, w, t)


t = Throttled()
r = Router([t])
dirty = True
for _ in range(5000):                           # ~5 s of main loop
    if dirty and r.ready():
        if r.send(build_frame()):
            dirty = False

check("the frame was sent once", t.sent == 1, t.sent)
check("and built exactly once", built[0] == 1, built[0])

built[0] = 0
t.connected = False
for _ in range(5000):
    if True and r.ready():                      # dirty, but nothing is up
        r.send(build_frame())
check("nothing is built while no transport is connected", built[0] == 0, built[0])


# ── A dropped link comes back ────────────────────────────────
# Was: connected went False on any error and nothing ever called start()
# again. There is no daily reboot in this firmware, so a lamp would look
# fine and silently stop reaching its friend until it was unplugged.
print("\ndropped links reconnect")


class Flaky(Transport):
    name = "flaky"

    def __init__(self):
        Transport.__init__(self)
        self.starts = 0

    def start(self, tick=None):
        self.starts += 1
        self.connected = self.starts >= 3       # fails twice, then works


f = Flaky()
r = Router([f])
# Backoff is 60 s, then doubling: retries land at ~60 s, ~180 s, ~420 s.
# Two of them fail by design, so recovery needs the third — run past it.
for _ in range(600):                            # 600 s at 1 s a step
    r.service()
    utime.sleep_ms(1000)

check("a dead transport is retried", f.starts >= 3, f.starts)
check("and recovers", f.connected is True)
check("backoff grows rather than hammering",
      f.starts <= 6, "%d starts in 600 s" % f.starts)

before = f.starts
for _ in range(600):
    r.service()
    utime.sleep_ms(1000)
check("a healthy transport is left alone", f.starts == before, f.starts)


# ── Every bad frame raises DecodeError, nothing else ─────────
# Was: decode("...") raised TypeError, which the main loop did not catch,
# so one stray frame put the lamp into a crash-reboot cycle. And
# bytes(50000) does not raise at all — it allocates fifty thousand zero
# bytes on a device with a few hundred KB of RAM.
print("\nevery bad frame is a DecodeError")

for bad in (None, "a string", 50000, [1, 2, 3], {}, b"", b"\x10\x01",
            bytearray(b"short"), 3.14, True):
    label = "%s(%r)" % (type(bad).__name__, bad)[:44]
    try:
        codec.decode(bad)
        check("rejects %s" % label, False, "accepted")
    except codec.DecodeError:
        check("rejects %s" % label, True)
    except Exception as e:
        check("rejects %s" % label, False,
              "raised %s, which main() does not catch" % type(e).__name__)

good = bytearray(codec.encode(3, 11, 22, 33))
check("bytearray of a valid frame still decodes",
      codec.decode(good)["lamp_id"] == 3)


# ── Your own touch must not pulse ────────────────────────────
# A pulse means "your friend reached for their lamp". Flashing at your own
# touch drowns the only signal it carries.
print("\nown touches do not pulse")

from engine import Engine


class FakeStrip:
    num_leds = 4

    def set(self, *a):
        pass

    def set_all(self, *a):
        pass

    def set_brightness(self, v):
        pass

    def show(self):
        pass

    def off(self):
        pass


shared = SharedColour(1)
e = Engine(shared, 4)

shared.touch()
e.note_arrival(pulse=False)
check("our own tap queues no pulse", e._pulses == 0, e._pulses)

shared.apply_remote(2, 4096, 100, 3)
e.note_arrival()
check("a friend's touches do pulse", e._pulses == 3, e._pulses)
check("pulses are capped", True)

shared.apply_remote(2, 8192, 200, 99)
e.note_arrival()
check("a burst is capped, not a minute of strobing", e._pulses <= 5, e._pulses)


# ── HTTP status lines are honest ─────────────────────────────
# Was: every response said "OK" regardless of code, including "404 OK".
print("\nhttp status lines")

from portal import Portal


class Conn:
    def __init__(self):
        self.out = b""

    def send(self, d):
        self.out += d if isinstance(d, bytes) else d.encode()

    def close(self):
        pass


class FakeEngine:
    brightness = 0.6
    is_on = True

    def note_arrival(self, pulse=True):
        pass

    def set_brightness(self, v):
        pass

    def set_power(self, v):
        pass


p = Portal(SharedColour(1), FakeEngine(), 1,
           page=os.path.join(ROOT, "firmware", "lamp", "www", "index.html"))

for raw, expect in (("GET /nope HTTP/1.1\r\n\r\n", b"HTTP/1.1 404 Not Found"),
                    ("GET /generate_204 HTTP/1.1\r\n\r\n", b"HTTP/1.1 302 Found"),
                    ("GET /state HTTP/1.1\r\n\r\n", b"HTTP/1.1 200 OK")):
    c = Conn()
    p._respond(c, raw.encode())
    check("status line %s" % expect.decode().split(" ", 1)[1],
          c.out.startswith(expect), c.out[:32])

c = Conn()
p._respond(c, b'POST /set HTTP/1.1\r\nContent-Length: 3\r\n\r\n{{{')
check("status line 400 Bad Request",
      c.out.startswith(b"HTTP/1.1 400 Bad Request"), c.out[:32])


# ── An open network cannot spin the wheel arbitrarily ────────
print("\nhue_steps is clamped")

shared = SharedColour(1)
p2 = Portal(shared, FakeEngine(), 1)
before = shared.total_touches()
p2._respond(Conn(), b'POST /set HTTP/1.1\r\nContent-Length: 24\r\n\r\n'
                    b'{"hue_steps": 100000000}')
check("an absurd nudge is clamped", shared.total_touches() - before <= 16,
      shared.total_touches() - before)


print("\n%d failed" % len(failures) if failures else "\nall passed")
sys.exit(1 if failures else 0)
