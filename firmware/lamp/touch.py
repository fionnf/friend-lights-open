# ============================================================
#  touch.py  —  Native capacitive touch on ESP32-S3
# ============================================================
# The original firmware measured charge time on a bare GPIO with a 1 MΩ
# pull-down and a hand-tuned threshold, because the RP2040 has no touch
# peripheral. The ESP32-S3 does, so this is now a peripheral read.
#
# What that removes: the external resistor, the per-build threshold
# tuning, and the calibration hack. One less thing for a friend
# assembling their own lamp to get wrong.
#
# On the ESP32-S3 the reading RISES when a pad is touched (the original
# ESP32 fell), so this detects a rise above a slowly-tracked baseline.
# Tracking the baseline matters: capacitance drifts with temperature and
# humidity, and a fixed baseline taken at boot would slowly stop firing —
# or start firing continuously — over a few days.

import utime

from machine import Pin

try:
    from machine import TouchPad
except ImportError:                    # RP2040 and others: no touch
    TouchPad = None

HOLD_TIME_MS      = 1200
# A second, much longer press opens the setup portal. It has to be hard
# to do by accident — raising an open access point because someone leaned
# on the lamp would be a poor surprise.
LONG_HOLD_TIME_MS = 5000
# How fast the resting baseline chases the current reading, as a time
# constant rather than a per-call fraction. Long enough that a finger —
# even one resting for a minute — never gets absorbed into it.
BASELINE_TAU_MS = 30000


class TouchSensor:
    """Events from update(): "tap", "hold", "long_hold", or None.

    tap        — nudge the colour
    hold       (1.2 s) — power on/off
    long_hold  (5 s)   — open the setup portal

    All three fire on RELEASE, not when their threshold passes. Firing at
    the threshold meant a single five-second press emitted "hold" on the
    way to "long_hold", so opening the setup portal always toggled the
    lamp off first. You cannot tell a long press from a short one until
    the finger lifts, so that is when the decision is made.

    The cost is that a hold gives no feedback until release. For a lamp
    that is a fair trade against a gesture that always did two things.
    """

    def __init__(self, pin, threshold):
        self._pad = TouchPad(Pin(pin))
        self._threshold = threshold
        self._baseline = self._read()
        self._touched = False
        self._started = 0
        self._drifted = utime.ticks_ms()

    def _read(self):
        try:
            self._last = self._pad.read()
            return self._last
        except Exception:
            # Never 0: that reads as a huge negative excursion, drags
            # the baseline toward zero, and once reads resume the pad
            # latches "touched" and starts toggling the lamp on its own.
            return getattr(self, "_last", 0)

    def calibrate(self):
        total = 0
        for _ in range(16):
            total += self._read()
            utime.sleep_ms(2)
        self._baseline = total / 16

    def update(self):
        value = self._read()
        touched = (value - self._baseline) > self._threshold

        now = utime.ticks_ms()

        if not touched:
            # Only track the baseline while untouched, or a held finger
            # would slowly become the new normal and the release would
            # register as a phantom second touch.
            #
            # Rate is measured in TIME, not in calls. This runs from the
            # render loop, whose rate depends on strip length and on
            # whatever else the lamp is doing — so a per-call constant
            # silently retunes itself between builds, and at ~1000 calls
            # a second it was a 0.5 s time constant: fast enough to
            # absorb a slowly approaching finger before it ever crossed
            # the threshold.
            dt = utime.ticks_diff(now, self._drifted)
            if dt > 0:
                self._drifted = now
                k = dt / BASELINE_TAU_MS
                if k > 1.0:
                    k = 1.0
                self._baseline += (value - self._baseline) * k

        if touched and not self._touched:
            self._touched = True
            self._started = now
        elif not touched and self._touched:
            self._touched = False
            held = utime.ticks_diff(now, self._started)
            if held >= LONG_HOLD_TIME_MS:
                return "long_hold"
            if held >= HOLD_TIME_MS:
                return "hold"
            return "tap"
        return None


class ChargeTimeSensor:
    """Capacitive touch on a board with no touch peripheral.

    The RP2040 has no touch hardware, but it can still sense a finger —
    this is the technique the original project used on a Pico, and it
    works here unchanged:

        1. drive the pin HIGH briefly, charging the pad (and your
           finger, which is why it works)
        2. switch to INPUT and count loops until it discharges through
           an external pull-down
        3. more capacitance takes longer, so a touched pad counts higher

    Wiring per pad — the pull-down is the extra part:

        GPIO ──┬── 1 MΩ ── GND
               `── pad (bare copper, foil, a screw head)

    1 MΩ is what makes the discharge slow enough to count. Much lower
    and it empties before the loop notices; much higher and it drifts.

    Two things are done differently from the original, both because of
    faults this project has already hit:

      * gestures fire on RELEASE, so a five-second press cannot emit
        "hold" on its way to "long_hold" and toggle the lamp off before
        opening the portal
      * the baseline keeps tracking while untouched, so it follows
        temperature and humidity instead of being a single measurement
        taken at boot
    """

    # Counting stops here regardless. Without it, a pin held high by a
    # wiring fault spins this loop forever inside the render loop.
    MAX_COUNT = 5000
    # The scale is nothing like the ESP32's — raw counts here are
    # single or double digits, not tens of thousands.
    DEFAULT_THRESHOLD = 8

    def __init__(self, pin, threshold=None, samples=8):
        # One Pin object, reused. Constructing one per measurement is an
        # allocation ~1000 times a second in the hottest path there is.
        self._pin = Pin(pin, Pin.OUT)
        self._threshold = threshold or self.DEFAULT_THRESHOLD
        self._samples = samples
        self._baseline = self._measure_avg()
        self._last = self._baseline
        self._touched = False
        self._started = 0
        self._drifted = utime.ticks_ms()

    def _measure(self):
        """One charge-time reading."""
        pin = self._pin
        try:
            pin.init(Pin.OUT)
            pin.value(1)
            utime.sleep_us(10)          # charge the pad
            pin.init(Pin.IN)            # let it drain through the 1 MΩ
            count = 0
            while pin.value():
                count += 1
                if count >= self.MAX_COUNT:
                    break
            self._last = count
            return count
        except Exception:
            # Never return 0 on failure: 0 reads as an enormous NEGATIVE
            # excursion, which drags the baseline down until the pad
            # latches "touched" and the lamp starts toggling itself.
            return self._last

    def _measure_avg(self):
        total = 0
        for _ in range(self._samples):
            total += self._measure()
            utime.sleep_us(200)
        return total / self._samples

    def calibrate(self):
        self._baseline = self._measure_avg()

    def update(self):
        value = self._measure()
        touched = (value - self._baseline) > self._threshold
        now = utime.ticks_ms()

        if not touched:
            # Track drift in real time rather than per call. The loop
            # rate is not a constant — it changes with strip length and
            # with whatever else the lamp is doing — so a per-call alpha
            # silently retunes itself, and at ~1000 calls a second it is
            # fast enough to absorb a slowly approaching finger before
            # it ever crosses the threshold.
            dt = utime.ticks_diff(now, self._drifted)
            if dt > 0:
                self._drifted = now
                # ~30 s time constant.
                k = dt / 30000.0
                if k > 1.0:
                    k = 1.0
                self._baseline += (value - self._baseline) * k

        if touched and not self._touched:
            self._touched = True
            self._started = now
        elif not touched and self._touched:
            self._touched = False
            held = utime.ticks_diff(now, self._started)
            if held >= LONG_HOLD_TIME_MS:
                return "long_hold"
            if held >= HOLD_TIME_MS:
                return "hold"
            return "tap"
        return None

    def reading(self):
        """Raw count and baseline, for strip_test.py to print."""
        return self._measure(), self._baseline


class ButtonSensor:
    """A plain push button to GND, for boards with no touch peripheral.

    The RP2040 in a Pico W has none — the original project measured
    charge time on a bare GPIO with a 1 MΩ pull-down to fake it, which
    worked but needed per-build tuning. A button needs none, costs
    nothing, and produces exactly the same three gestures, so the rest
    of the firmware cannot tell which one a lamp has.

    Wire it between the pin and GND; the internal pull-up does the rest.
    """

    # Contacts bounce for a few milliseconds on both edges. Ignoring
    # changes for longer than that turns one press into one event
    # instead of a burst of taps.
    DEBOUNCE_MS = 30

    def __init__(self, pin, threshold=None):
        self._pin = Pin(pin, Pin.IN, Pin.PULL_UP)
        self._down = False
        self._started = 0
        self._changed = 0

    def calibrate(self):
        pass                              # nothing to calibrate

    def update(self):
        now = utime.ticks_ms()
        if utime.ticks_diff(now, self._changed) < self.DEBOUNCE_MS:
            return None
        # Pulled up, so a press reads LOW.
        pressed = not self._pin.value()

        if pressed and not self._down:
            self._down = True
            self._started = now
            self._changed = now
        elif not pressed and self._down:
            self._down = False
            self._changed = now
            held = utime.ticks_diff(now, self._started)
            # Same thresholds and the same fire-on-release rule as the
            # touch pad, for the same reason: you cannot tell a long
            # press from a short one until the finger lifts.
            if held >= LONG_HOLD_TIME_MS:
                return "long_hold"
            if held >= HOLD_TIME_MS:
                return "hold"
            return "tap"
        return None


class TouchManager:
    """Merges several inputs. A lamp with none is entirely valid — it is
    then controlled from the app, or simply reflects its friend.

    Takes touch pads and buttons together and yields one stream of
    events, so a Pico W with a button and a XIAO with a copper pad are
    indistinguishable to everything above."""

    def __init__(self, pins, threshold, buttons=(), charge_threshold=None):
        self.sensors = []
        # TOUCH_PINS means "a capacitive pad" on both platforms; only
        # the technique differs, so the config does not have to know
        # which board it is on. The ESP32 has touch hardware; the
        # RP2040 measures charge time against an external 1 MΩ
        # pull-down. Same pins, same gestures, same config key.
        for p in pins:
            try:
                if TouchPad is not None:
                    self.sensors.append(TouchSensor(p, threshold))
                else:
                    self.sensors.append(
                        ChargeTimeSensor(p, charge_threshold))
                    print("[touch] pin %s: charge-time (needs a 1 MOhm "
                          "pull-down to GND)" % p)
            except Exception as e:
                print("[touch] pin %s unavailable: %s" % (p, e))
        for p in buttons or ():
            try:
                self.sensors.append(ButtonSensor(p))
                print("[touch] button on pin %s" % p)
            except Exception as e:
                print("[touch] button pin %s unavailable: %s" % (p, e))

    def calibrate_all(self):
        for s in self.sensors:
            s.calibrate()

    def update(self):
        for s in self.sensors:
            event = s.update()
            if event:
                return event
        return None
