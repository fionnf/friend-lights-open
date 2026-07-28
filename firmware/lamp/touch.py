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
# The baseline chases the resting value slowly enough that a finger — even
# one resting for a minute — never gets absorbed into it.
BASELINE_ALPHA = 0.002


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

    def _read(self):
        try:
            return self._pad.read()
        except Exception:
            return 0

    def calibrate(self):
        total = 0
        for _ in range(16):
            total += self._read()
            utime.sleep_ms(2)
        self._baseline = total / 16

    def update(self):
        value = self._read()
        touched = (value - self._baseline) > self._threshold

        if not touched:
            # Only track the baseline while untouched, or a held finger
            # would slowly become the new normal and the release would
            # register as a phantom second touch.
            self._baseline += (value - self._baseline) * BASELINE_ALPHA

        now = utime.ticks_ms()

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

    def __init__(self, pins, threshold, buttons=()):
        self.sensors = []
        if pins and TouchPad is None:
            print("[touch] no touch peripheral on this port — "
                  "use BUTTON_PINS instead")
        elif TouchPad is not None:
            for p in pins:
                try:
                    self.sensors.append(TouchSensor(p, threshold))
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
