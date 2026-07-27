# ============================================================
#  engine.py  —  Turning agreed state into light
# ============================================================
# The CRDT in shared_state.py decides WHAT colour the lamps agree on.
# This decides HOW it arrives, and the answer is: slowly.
#
# A lamp that jumped the instant a message landed would still be correct.
# It would also announce, several times a day, that a packet had been
# received — which is not the thing anyone wants to be told. Fading over
# a minute or two makes the network invisible, and turns a message into
# something you notice rather than something you watch happen.
#
# It also happens to be what the transport requires. Ten downlinks a day
# means colour arrives a handful of times a day no matter what this file
# does; the slow fade means that reads as weather rather than as lag.

import math
import utime

import palette

# One pulse per peer touch when news arrives, capped — fifty touches
# should read as "a lot", not as a minute of strobing.
MAX_PULSES  = 5
PULSE_MS    = 700
PULSE_DEPTH = 0.35


def _shortest_delta(current, target):
    """Signed distance around a circle, in (-0.5, 0.5].

    Hue wraps, so fading from 0.95 to 0.05 must travel 0.1 forwards
    through the wrap point, not 0.9 backwards through every other colour
    on the wheel.
    """
    return (target - current + 0.5) % 1.0 - 0.5


class Engine:

    def __init__(self, shared, num_leds, brightness=0.6,
                 arrival_fade_ms=90_000,
                 breathe_speed=0.0008, breathe_depth=0.04):
        self.shared = shared
        self.num_leds = num_leds

        self._brightness = brightness
        self._powered_on = True
        self._power_level = 1.0
        self._power_dir = 0

        # Displayed values chase the agreed ones. Seeded from the agreed
        # state so a reboot comes back at the right colour rather than
        # sweeping to it from warm white.
        self._hue = shared.hue()
        self._warmth = shared.warmth()

        # Max distance on the wheel is 0.5, so this is the worst-case
        # arrival time; nearer colours land sooner.
        self._hue_rate = 0.5 / max(1, arrival_fade_ms)
        self._warm_rate = 1.0 / max(1, arrival_fade_ms)

        self._breathe_speed = breathe_speed
        self._breathe_depth = breathe_depth
        self._phase = [i * 6.283185 / max(1, num_leds) for i in range(num_leds)]

        self._last_ms = utime.ticks_ms()
        self._known_touches = shared.total_touches()
        self._pulses = 0
        self._pulse_phase = 0.0

    # ── Power ───────────────────────────────────────────────

    def set_power(self, on):
        if bool(on) != self._powered_on:
            self._powered_on = bool(on)
            self._power_dir = 1 if self._powered_on else -1

    def toggle_power(self):
        self.set_power(not self._powered_on)

    @property
    def is_on(self):
        return self._powered_on

    def set_brightness(self, value):
        self._brightness = max(0.0, min(1.0, value))

    @property
    def brightness(self):
        return self._brightness

    # ── News ────────────────────────────────────────────────

    def note_arrival(self):
        """Called when a peer's state has been folded in.

        The difference in the shared touch total is how many times someone
        reached for their lamp since we last looked — so the lamp pulses
        that many times before settling. This is the whole 'while you were
        out' idea, and it costs nothing extra on the wire because the
        touch counter was already in the payload.
        """
        now_total = self.shared.total_touches()
        delta = (now_total - self._known_touches) % 0x10000
        self._known_touches = now_total
        if 0 < delta <= 0x8000:
            self._pulses = min(MAX_PULSES, self._pulses + delta)

    # ── Frame ───────────────────────────────────────────────

    def tick(self, strip):
        now = utime.ticks_ms()
        dt = utime.ticks_diff(now, self._last_ms)
        self._last_ms = now
        if dt <= 0:
            dt = 1

        # Power fade
        if self._power_dir:
            self._power_level += self._power_dir * (dt / 800.0)
            if self._power_level >= 1.0:
                self._power_level, self._power_dir = 1.0, 0
            elif self._power_level <= 0.0:
                self._power_level, self._power_dir = 0.0, 0
                strip.off()
                return
        if not self._powered_on and self._power_level <= 0.0:
            strip.off()
            return

        self._chase(dt)

        pulse = self._pulse(dt)
        r, g, b, w = palette.rgbw(self._hue, self._warmth)

        strip.set_brightness(self._brightness)
        depth = self._breathe_depth
        speed = self._breathe_speed
        for i in range(self.num_leds):
            # Phase wraps at 2π so it never grows large enough for float
            # precision loss to make the breath jerky — it would otherwise
            # reach ~10^6 radians after a few weeks of uptime.
            ph = self._phase[i] + speed * dt
            if ph > 6.283185:
                ph -= 6.283185
            self._phase[i] = ph
            scale = (1.0 + math.sin(ph) * depth) * self._power_level * pulse
            strip.set(i,
                      min(255, int(r * scale)),
                      min(255, int(g * scale)),
                      min(255, int(b * scale)),
                      min(255, int(w * scale)))
        strip.show()

    # ── Internal ────────────────────────────────────────────

    def _chase(self, dt):
        """Move the displayed colour toward the agreed one, slowly."""
        target_hue = self.shared.hue()
        delta = _shortest_delta(self._hue, target_hue)
        step = self._hue_rate * dt
        if abs(delta) <= step:
            self._hue = target_hue
        else:
            self._hue = (self._hue + (step if delta > 0 else -step)) % 1.0

        target_warm = self.shared.warmth()
        d = target_warm - self._warmth
        step = self._warm_rate * dt
        if abs(d) <= step:
            self._warmth = target_warm
        else:
            self._warmth += step if d > 0 else -step

    def _pulse(self, dt):
        """Brightness multiplier for the arrival pulses, 1.0 when idle."""
        if self._pulses <= 0:
            return 1.0
        self._pulse_phase += dt / PULSE_MS
        if self._pulse_phase >= 1.0:
            self._pulse_phase = 0.0
            self._pulses -= 1
            return 1.0
        return 1.0 + PULSE_DEPTH * math.sin(self._pulse_phase * 3.141593)
