# ============================================================
#  driver.py  —  SK6812 RGBW / WS2812 RGB on ESP32-S3
# ============================================================
# The original firmware drove the strip with a hand-written RP2040 PIO
# program because the RP2040 has no hardware peripheral for this. The
# ESP32 does (RMT), and MicroPython's built-in `neopixel` module already
# wraps it — including bpp=4 for the SK6812's white channel, with the
# GRBW byte reordering handled internally.
#
# So the entire PIO program collapses into this file. It is the one part
# of the port that got simpler rather than harder.

from machine import Pin
import neopixel


class Strip:

    def __init__(self, pin, num_leds, brightness=1.0, order="GRBW",
                 reverse=False):
        self.num_leds   = num_leds
        self.brightness = max(0.0, min(1.0, brightness))
        self.reverse    = reverse
        self.has_white  = "W" in order.upper()
        self._np = neopixel.NeoPixel(Pin(pin), num_leds,
                                     bpp=4 if self.has_white else 3)
        self._pixels = [(0, 0, 0, 0)] * num_leds

    # ── Public API ──────────────────────────────────────────

    def set(self, index, r=0, g=0, b=0, w=0):
        if 0 <= index < self.num_leds:
            self._pixels[index] = (r, g, b, w)

    def set_all(self, r=0, g=0, b=0, w=0):
        self._pixels = [(r, g, b, w)] * self.num_leds

    def set_brightness(self, brightness):
        self.brightness = max(0.0, min(1.0, brightness))

    def show(self):
        br = self.brightness
        n  = self.num_leds
        for i in range(n):
            r, g, b, w = self._pixels[i]
            if not self.has_white and w:
                # A WS2812 strip has no white channel, so warm white would
                # simply not render. Fold it into RGB instead — the lamp
                # looks slightly different, but it lights up.
                r = min(255, r + w)
                g = min(255, int(g + w * 0.82))
                b = min(255, int(b + w * 0.55))
            out = (int(r * br), int(g * br), int(b * br))
            if self.has_white:
                out += (int(w * br),)
            self._np[(n - 1 - i) if self.reverse else i] = out
        self._np.write()

    def off(self):
        self.set_all(0, 0, 0, 0)
        self.show()
