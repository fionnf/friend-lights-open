# ============================================================
#  strip_test.py  —  Does the strip work, and is it wired right?
# ============================================================
# Runs ON the lamp, over USB. It flashes the strip through a known
# sequence and prints what each step SHOULD look like, so you can
# compare what you see against what the board thinks it sent.
#
#   mpremote connect /dev/ttyACM0 run tools/strip_test.py
#
# In Thonny: open this file, make sure the interpreter is the board,
# press F5.
#
# It does not transmit, so the antenna does not matter here and nothing
# can be damaged. Run it before radio_check.py — a strip that is wired
# wrong looks exactly like firmware that does not work, and this rules
# that out in ninety seconds.
#
# ── Why "print the results" is the whole point ───────────────────────
# The board cannot see its own LEDs. So the useful output is not a
# verdict — it is the board stating, in order, exactly what it drove.
# Every wiring and config fault shows up as a mismatch between that and
# what you saw, and the table at the end maps each mismatch to the one
# line in config.py that fixes it.

import sys

sys.path.append("/lamp")

import utime                                     # noqa: E402
from driver import Strip                         # noqa: E402

try:
    import config
except ImportError:
    config = None


def cfg(name, default):
    return getattr(config, name, default) if config else default


def banner(text):
    print("\n" + text)
    print("-" * len(text))


HOLD_MS = 1200          # long enough to see, short enough to sit through


def hold(ms=HOLD_MS):
    # sleep_ms in one go would be fine here — there is no watchdog
    # running, because main.py is not what is executing.
    utime.sleep_ms(ms)


print("\n=== strip test ===")

# ── 1. What the config says ──────────────────────────────────
# Printed first and in full: three of the four common faults are a
# config value rather than the wiring, and seeing NUM_LEDS = 10 next to
# a strip of 24 answers the question before any LED lights.
pin = cfg("LED_PIN", 2)
num = cfg("NUM_LEDS", 10)
order = cfg("LED_ORDER", "GRBW")
reverse = cfg("REVERSE_LEDS", False)
bright = cfg("LED_BRIGHTNESS", 0.6)

banner("1. config")
print("   LED_PIN        %s" % pin)
print("   NUM_LEDS       %s" % num)
print("   LED_ORDER      %s   (SK6812 is GRBW, WS2812 is GRB)" % order)
print("   REVERSE_LEDS   %s" % reverse)
print("   LED_BRIGHTNESS %s" % bright)
if config is None:
    print("\n   No config.py found — using defaults. That is fine for")
    print("   this test, but the lamp itself needs one.")

# ── 2. Can we drive it at all? ───────────────────────────────
banner("2. driver")
try:
    # Full brightness deliberately: this is a test of the hardware, and
    # a dim strip is harder to judge. The lamp's own brightness is
    # applied at runtime, not here.
    strip = Strip(pin, num, brightness=1.0, order=order, reverse=reverse)
except Exception as e:
    print("   FAILED to open the strip: %s" % e)
    print("\n   That is a bad LED_PIN, or a pin the board does not have.")
    raise SystemExit(1)

print("   ok — %d pixels, %d bytes each, white channel: %s"
      % (num, 4 if strip.has_white else 3,
         "yes" if strip.has_white else "no"))

# ── 3. One channel at a time ─────────────────────────────────
# The single most useful step. If the strip lights the WRONG colour
# here, LED_ORDER is wrong — and that is the fault most likely to be
# mistaken for "the board is broken", because everything else works.
banner("3. colour channels — watch what you actually see")

channels = [("RED",   (255, 0, 0, 0)),
            ("GREEN", (0, 255, 0, 0)),
            ("BLUE",  (0, 0, 255, 0))]
if strip.has_white:
    channels.append(("WHITE (the white LED, not R+G+B)", (0, 0, 0, 255)))

for name, (r, g, b, w) in channels:
    print("   driving %-34s -> should look %s"
          % ("r=%d g=%d b=%d w=%d" % (r, g, b, w), name))
    strip.set_all(r, g, b, w)
    strip.show()
    hold()

strip.off()
strip.show()
hold(400)

# ── 4. Every pixel, one at a time ────────────────────────────
# Proves NUM_LEDS and which end is which. A pixel that stops partway
# means NUM_LEDS is higher than the strip really is; a chase that runs
# the wrong way means REVERSE_LEDS.
banner("4. chase — one lit pixel, index 0 first")
print("   %d pixels, about %d ms each" % (num, max(60, 1200 // max(1, num))))
print("   Watch WHICH END starts. Index 0 should be the end you")
print("   consider the beginning; if it is not, set REVERSE_LEDS.")

step_ms = max(60, 1200 // max(1, num))
for i in range(num):
    strip.set_all(0, 0, 0, 0)
    strip.set(i, 255, 120, 0, 0)          # amber: visible, unlike white
    strip.show()
    hold(step_ms)

strip.off()
strip.show()
hold(400)

# ── 5. Brightness ────────────────────────────────────────────
# A strip that flickers or resets the board here is a power fault, not
# a data one — and it is the only fault on this page that gets worse
# with more LEDs.
banner("5. brightness ramp")
print("   Smooth fade up and down. Flicker, colour shifts toward the")
print("   far end, or the board resetting = the strip is drawing more")
print("   than the supply can give. Power it from 5 V directly.")

for level in list(range(0, 256, 8)) + list(range(255, -1, -8)):
    strip.set_all(level, level, level, 0)
    strip.show()
    utime.sleep_ms(12)

strip.off()
strip.show()

# ── 6. Flash, as asked ───────────────────────────────────────
banner("6. flashing between colours")
print("   Six cycles. Nothing to diagnose here — it is the")
print("   'yes, it works' one.")

palette = [("red", (255, 0, 0, 0)), ("green", (0, 255, 0, 0)),
           ("blue", (0, 0, 255, 0)), ("amber", (255, 120, 0, 0)),
           ("violet", (140, 0, 255, 0)), ("cyan", (0, 200, 200, 0))]

for cycle in range(6):
    name, (r, g, b, w) = palette[cycle % len(palette)]
    print("   %d/6  %s" % (cycle + 1, name))
    strip.set_all(r, g, b, w)
    strip.show()
    hold(500)
    strip.off()
    strip.show()
    hold(150)

# ── 7. Touch, if there is a pad ──────────────────────────────
# Printed as live numbers rather than a pass/fail: the threshold is a
# property of your pad, your wiring and your hand, so the only useful
# answer is what the numbers actually do when you touch it.
pads = cfg("TOUCH_PINS", [4])
buttons = cfg("BUTTON_PINS", [])
banner("7. touch")

if not pads and not buttons:
    print("   TOUCH_PINS and BUTTON_PINS are both empty — skipping.")
elif buttons and not pads:
    from machine import Pin
    pin = Pin(buttons[0], Pin.IN, Pin.PULL_UP)
    print("   button on pin %s — press it now (5 s)\n" % buttons[0])
    seen = False
    for i in range(50):
        if not pin.value():
            seen = True
        if i % 10 == 0:
            print("      %s" % ("PRESSED" if not pin.value() else "released"))
        utime.sleep_ms(100)
    print("\n   %s" % ("-> the button works." if seen else
                        "-> never saw a press. Wrong pin, or wired to 3V3 "
                        "rather than GND."))
else:
    # Two completely different techniques and two completely different
    # scales, so the numbers below only mean something next to the
    # threshold for THIS board.
    try:
        from machine import TouchPad, Pin
        native = True
    except ImportError:
        native = False

    if native:
        pad = TouchPad(Pin(pads[0]))
        read = pad.read
        threshold = cfg("TOUCH_THRESHOLD", 20000)
        print("   pin %s, ESP32 touch peripheral" % pads[0])
    else:
        # RP2040 and friends: charge-time against the 1 MOhm pull-down.
        sys.path.append("/lamp")
        from touch import ChargeTimeSensor
        sensor = ChargeTimeSensor(pads[0])
        read = sensor._measure
        threshold = cfg("TOUCH_THRESHOLD_CHARGE",
                        ChargeTimeSensor.DEFAULT_THRESHOLD)
        print("   pin %s, charge-time (needs 1 MOhm to GND)" % pads[0])

    base = 0
    for _ in range(16):
        base += read()
        utime.sleep_ms(5)
    base //= 16

    print("   resting value %d, threshold %s" % (base, threshold))
    print("   A touch must RAISE the reading by more than that.")
    print("   Put a finger on the pad now:\n")

    peak = base
    quiet = base
    for i in range(50):                # ~5 seconds
        value = read()
        peak = max(peak, value)
        quiet = min(quiet, value)
        if i % 5 == 0:
            print("      %7d   (%+d from resting)" % (value, value - base))
        utime.sleep_ms(100)

    rise = peak - base
    noise = base - quiet
    print("\n   biggest rise: %d      idle noise: %d" % (rise, noise))
    if rise > threshold and rise > noise * 3:
        print("   -> comfortably above the threshold, and well clear of")
        print("      the noise. Good.")
    elif rise > noise * 3:
        suggested = max(1, (rise + noise) // 3)
        print("   -> it responds, but the threshold is too high.")
        if native:
            print("      Set TOUCH_THRESHOLD = %d" % suggested)
        else:
            print("      Set TOUCH_THRESHOLD_CHARGE = %d" % suggested)
    elif rise > 0:
        print("   -> the change is not much bigger than the idle noise.")
        print("      A larger pad, or a shorter lead to it, helps most.")
        if not native:
            print("      Check the 1 MOhm resistor is really 1 MOhm and")
            print("      really goes to GND — that is what makes the pad")
            print("      hold charge long enough to time.")
    else:
        print("   -> no change at all. Either nothing touched the pad,")
        print("      or it is not connected to pin %s." % pads[0])
        if not native:
            print("      With no pull-down at all the reading pins at 0")
            print("      or at the safety cap and never moves.")

# ── What to change ───────────────────────────────────────────
banner("what to change in config.py")
print("""
   Nothing lit at all
       LED_PIN is wrong, the 330 ohm resistor is on the wrong line,
       or the strip has no 5 V. Check power at the strip first.

   Colours are wrong — step 3 said RED and it looked GREEN
       LED_ORDER. SK6812 is "GRBW", WS2812 is "GRB". Swapping the
       first two letters fixes the usual red/green transposition.

   Only some pixels lit, or the chase stopped partway
       NUM_LEDS is higher than the strip really is. In step 4 count
       how many lit and use that.

   The chase ran from the far end
       REVERSE_LEDS = True

   Only the first pixel or two lit, rest dark or random
       Data line integrity: the resistor, a long lead, or a bad
       ground between the board and the strip. They must share GND.

   Flicker, or the board reset during step 5
       Power. 60 RGBW LEDs at white is about 3.5 A, well past USB.
       Feed the strip from 5 V directly, not through the XIAO.

   Nothing in step 7 when you touched the pad
       Wrong pin, or nothing attached. Bare copper, foil or a screw
       head all work. On an ESP32 no resistor is needed; on a Pico the
       pad needs a 1 MOhm resistor from the pin to GND, and without it
       the reading never moves.

   All of it looked right
       The strip is good. Next: tools/radio_check.py — and attach
       the antenna first, because that one transmits.
""")

strip.off()
strip.show()
print("=== done ===")
