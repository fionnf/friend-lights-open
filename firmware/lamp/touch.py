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

try:
    from machine import TouchPad, Pin
except ImportError:                    # port without touch support
    TouchPad = None
    Pin = None

HOLD_TIME_MS = 1200
# The baseline chases the resting value slowly enough that a finger — even
# one resting for a minute — never gets absorbed into it.
BASELINE_ALPHA = 0.002


class TouchSensor:
    """Events from update(): "tap", "hold", or None."""

    def __init__(self, pin, threshold):
        self._pad = TouchPad(Pin(pin))
        self._threshold = threshold
        self._baseline = self._read()
        self._touched = False
        self._started = 0
        self._hold_fired = False

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
            self._hold_fired = False
        elif touched and self._touched:
            if (not self._hold_fired and
                    utime.ticks_diff(now, self._started) >= HOLD_TIME_MS):
                self._hold_fired = True
                return "hold"
        elif not touched and self._touched:
            self._touched = False
            if not self._hold_fired:
                return "tap"
        return None


class TouchManager:
    """Merges several pads. A lamp with no pads is entirely valid — it is
    then controlled from the app, or simply reflects its friend."""

    def __init__(self, pins, threshold):
        self.sensors = []
        if TouchPad is None:
            if pins:
                print("[touch] no touch peripheral on this port — disabled")
            return
        for p in pins:
            try:
                self.sensors.append(TouchSensor(p, threshold))
            except Exception as e:
                print("[touch] pin %s unavailable: %s" % (p, e))

    def calibrate_all(self):
        for s in self.sensors:
            s.calibrate()

    def update(self):
        for s in self.sensors:
            event = s.update()
            if event:
                return event
        return None
