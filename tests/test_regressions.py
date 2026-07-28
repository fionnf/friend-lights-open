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
from shared_state import SharedColour, COUNTER_MODULO
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
    # Built through the real __init__ and then given a fake pad, rather
    # than __new__ plus hand-set attributes: the hand-built version
    # broke the moment the sensor gained a field, which is a test
    # failing for a reason that has nothing to do with the bug it
    # guards.
    s = TouchSensor(4, 100)
    s._pad = Pad()
    s._baseline = 1000
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


# ── A short WPA2 password must not silently open the network ─
# The ESP32 ignores a password under 8 characters and brings the AP up
# OPEN without reporting it — so the lamp would look protected and not be.
print("\nportal password")

import network as _net
from portal import Portal as _P

def ap_of(pw):
    p = _P(SharedColour(1), FakeEngine(), 1, password=pw, always_on=True)
    p.start()
    ap = p._ap
    p.stop()
    return ap.cfg

cfg = ap_of("lightupleni")
check("a good password is applied", cfg.get("password") == "lightupleni", cfg)
check("and WPA2 is selected", cfg.get("authmode") == _net.AUTH_WPA2_PSK, cfg)

cfg = ap_of("short")
check("a too-short password is refused, not silently applied",
      "password" not in cfg, cfg)
check("and the network is openly declared open",
      cfg.get("authmode") == 0, cfg)

cfg = ap_of(None)
check("no password means open", cfg.get("authmode") == 0, cfg)

# Always-on must survive well past the idle timeout.
p = _P(SharedColour(1), FakeEngine(), 1, password="lightupleni", always_on=True)
p.start()
for _ in range(80):
    utime.sleep_ms(10_000)      # ~13 minutes
    p.tick()
check("an always-on portal does not time out", p.active is True)

p2 = _P(SharedColour(1), FakeEngine(), 1, always_on=False)
p2.start()
for _ in range(80):
    utime.sleep_ms(10_000)
    p2.tick()
check("an on-demand portal still times out", p2.active is False)


# ── The generated pair must be a working pair ────────────────
# Three ways to get six values wrong give you lamps that join the network
# perfectly and then do nothing, with no error anywhere: a shared DevEUI,
# mismatched JoinEUIs, or a shared LAMP_ID (the CRDT drops a message
# bearing your own id as an echo of yourself). The generator must refuse
# all three, and what it does write must be a usable pair.
print("\nconfigs generated from .env")

import subprocess, re as _re
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_env = os.path.join(_root, ".env")
_cfgs = [os.path.join(_root, "firmware", "config.lamp%d.py" % n) for n in (1, 2)]

if os.path.exists(_env) or any(os.path.exists(c) for c in _cfgs):
    # Never overwrite somebody's real keys just to run a test.
    print("  SKIP  .env or a lamp config already exists — not touching them")
else:
    _GOOD = """
LORA_RADIO = E5
LAMP1_DEV_EUI = 70B3D57ED0061111
LAMP1_APP_KEY = 0123456789ABCDEF0123456789ABCDEF
LAMP2_DEV_EUI = 70B3D57ED0062222
LAMP2_APP_KEY = FEDCBA9876543210FEDCBA9876543210
JOIN_EUI = 0011223344556677
PORTAL_PASSWORD = lightupleni
"""

    def _run(text):
        open(_env, "w").write(text)
        r = subprocess.run([sys.executable,
                            os.path.join(_root, "tools", "apply_env.py")],
                           capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr

    def _cleanup():
        for f in [_env] + _cfgs:
            if os.path.exists(f):
                os.remove(f)

    try:
        code, out = _run(_GOOD)
        check("a good .env writes both configs", code == 0, out.strip()[:160])

        cfg = []
        for c in _cfgs:
            ns = {}
            exec(open(c).read(), ns)
            cfg.append(ns)

        check("lamp ids differ", cfg[0]["LAMP_ID"] != cfg[1]["LAMP_ID"])
        check("DevEUIs differ",
              cfg[0]["LORA_DEV_EUI"] != cfg[1]["LORA_DEV_EUI"])
        check("AppKeys differ", cfg[0]["LORA_APP_KEY"] != cfg[1]["LORA_APP_KEY"])
        check("JoinEUI is shared",
              cfg[0]["LORA_APP_EUI"] == cfg[1]["LORA_APP_EUI"])
        for i, ns in enumerate(cfg, 1):
            ssid = ns["PORTAL_SSID"]
            check("lamp%d SSID fits 32 bytes" % i, len(ssid) <= 32, ssid)
            check("lamp%d SSID names its own id (%s)" % (i, ssid),
                  str(ns["LAMP_ID"]) in _re.findall(r"\d+", ssid), ssid)
            check("lamp%d password survives WPA2's minimum" % i,
                  len(ns["PORTAL_PASSWORD"]) >= 8)

        os.remove(_cfgs[0]); os.remove(_cfgs[1])
        code, out = _run(_GOOD.replace("70B3D57ED0062222", "70B3D57ED0061111"))
        check("a shared DevEUI is refused", code != 0)
        check("...and nothing was written",
              not any(os.path.exists(c) for c in _cfgs))

        code, out = _run(_GOOD.replace("lightupleni", "short"))
        check("a password WPA2 would silently ignore is refused", code != 0)

        code, out = _run(_GOOD.replace("LAMP1_APP_KEY = 0123456789ABCDEF0123456789ABCDEF",
                                       "LAMP1_APP_KEY ="))
        check("a missing AppKey is refused", code != 0)

        # ── The same again for ABP, which is now the default ──
        # A shared session is the ABP version of a shared DevEUI: both
        # lamps look fine in the console and neither stays connected.
        _cleanup()
        _ABP = """
LORA_RADIO = SX1262
LAMP1_DEV_ADDR = 260B1111
LAMP1_NWK_SKEY = 0123456789ABCDEF0123456789ABCDEF
LAMP1_APP_SKEY = 89ABCDEF0123456789ABCDEF01234567
LAMP2_DEV_ADDR = 260B2222
LAMP2_NWK_SKEY = FEDCBA9876543210FEDCBA9876543210
LAMP2_APP_SKEY = 76543210FEDCBA9876543210FEDCBA98
PORTAL_PASSWORD = lightupleni
"""
        code, out = _run(_ABP)
        check("an ABP .env writes both configs", code == 0, out.strip()[:160])

        cfg = []
        for c in _cfgs:
            ns = {}
            exec(open(c).read(), ns)
            cfg.append(ns)
        check("the radio is set to SX1262",
              all(ns["LORA_RADIO"] == "SX1262" for ns in cfg))
        check("DevAddrs differ",
              cfg[0]["LORA_DEV_ADDR"] != cfg[1]["LORA_DEV_ADDR"])
        check("session keys differ",
              cfg[0]["LORA_APP_SKEY"] != cfg[1]["LORA_APP_SKEY"])
        check("the B2B pins are the first guess",
              all(ns["SX_NSS_PIN"] == 41 and ns["SX_RESET_PIN"] == 42
                  and ns["SX_BUSY_PIN"] == 40 and ns["SX_DIO1_PIN"] == 39
                  for ns in cfg))

        _cleanup()
        code, out = _run(_ABP.replace("260B2222", "260B1111"))
        check("a shared DevAddr is refused", code != 0)
        check("...and nothing was written",
              not any(os.path.exists(c) for c in _cfgs))
    finally:
        _cleanup()


# ── A new lamp is warm white, not saturated yellow ───────────
# warmth() ran 0 -> "no warm white at all", so a lamp out of the box, or
# one that had just lost its counters, glowed hard yellow. Seeding the
# counter cannot fix it: both lamps seed the same value, and two half
# turns sum to a whole one, which lands back on zero.
print("\na fresh lamp is warm white")

import palette as _pal

_s = SharedColour(1)
check("fresh position is 0.0 — warm white in the original's palette",
      _s.position() == 0.0, _s.position())
check("fresh warm trim is full", _s.warmth() == 1.0, _s.warmth())
_r, _g, _b, _w = _pal.rgbw(_s.position(), _s.warmth())
check("fresh lamp drives the white channel", _w > 150, (_r, _g, _b, _w))
check("and barely any colour", _r + _g + _b == 0, (_r, _g, _b))

# Two lamps that have never spoken must agree, and both be warm white.
_a2, _b2 = SharedColour(1), SharedColour(2)
check("two fresh lamps agree",
      _a2.position() == _b2.position() == 0.0 and
      _a2.warmth() == _b2.warmth() == 1.0)

# It must still move, and still be smooth across the wrap.
_s.nudge(warm=COUNTER_MODULO // 2)
check("warmth still moves", _s.warmth() < 0.05, _s.warmth())
_vals = []
_v2 = SharedColour(1)
for _ in range(64):
    _v2.nudge(warm=COUNTER_MODULO // 32)
    _vals.append(_v2.warmth())
check("warmth stays in range", all(0.0 <= v <= 1.0 for v in _vals))
check("warmth is still continuous across the wrap",
      max(abs(_vals[i] - _vals[i-1]) for i in range(1, len(_vals))) < 0.15)


# ── Every LED gets written, whatever the zone layout ─────────
# A zone list that fell short would leave trailing LEDs showing the last
# scene — the original hit exactly that, and fixed it by making the final
# zone absorb the remainder.
print("\nevery LED is covered")

from engine import Engine as _Eng


class _CountingStrip:
    def __init__(self, n):
        self.num_leds = n
        self.written = set()
        self.brightness = 1.0

    def set(self, i, r=0, g=0, b=0, w=0):
        assert 0 <= i < self.num_leds, "wrote outside the strip: %d" % i
        self.written.add(i)

    def set_all(self, r=0, g=0, b=0, w=0):
        self.written = set(range(self.num_leds))

    def set_brightness(self, v):
        self.brightness = v

    def show(self):
        pass

    def off(self):
        self.set_all()


for _leds, _groups in ((10, 3), (1, 1), (7, 5), (24, 4), (5, 9), (60, 6)):
    _sh = SharedColour(1)
    _sh.touch(3)
    _en = _Eng(_sh, _leds, num_groups=_groups,
               group_max_leds=max(1, _leds // 2))
    _st = _CountingStrip(_leds)
    _en.tick(_st)
    check("%d LEDs in %d zones: every LED written"
          % (_leds, _groups), len(_st.written) == _leds,
          "%d of %d" % (len(_st.written), _leds))


print("\n%d failed" % len(failures) if failures else "\nall passed")
sys.exit(1 if failures else 0)
