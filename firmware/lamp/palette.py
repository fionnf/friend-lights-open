# ============================================================
#  palette.py  —  Palette position to RGBW
# ============================================================
# Lifted from linked_friend_lights, deliberately unchanged. A single
# `pos` sets hue AND saturation together:
#
#   pos = 0.0   pure warm white — W channel only, no tint at all
#   pos = 0.5   halfway round the palette, half saturated
#   pos = 1.0   the far end of the palette, fully saturated, W gone
#
# Coupling them is what makes the lamp read as a lamp. Independent hue
# and saturation gives you a light that can sit at "fully saturated
# green", which looks like test equipment; here everything low is warm
# and only a deliberate push gets you real colour.
#
# It is also why a lamp with its counters at zero is warm white, with no
# special case anywhere: zero IS warm white.
#
# In its own module rather than config.py because config.py holds
# per-lamp secrets and is never overwritten — a palette living there
# could never be improved on a lamp already in someone's house.

BASE_WARM_WHITE = (0, 0, 0, 200)

TINT_PALETTE = (
    (255, 200,  80),   #  0  golden yellow
    (255, 160,   0),   #  1  warm amber
    (255, 120,   0),   #  2  deep amber
    (255,  60,   0),   #  3  orange-red
    (255,   0,   0),   #  4  pure red
    (255,   0,  60),   #  5  red-pink
    (255,   0, 140),   #  6  hot pink
    (200,   0, 200),   #  7  magenta
    (140,   0, 255),   #  8  violet
    ( 80,   0, 255),   #  9  indigo
    (  0,   0, 255),   # 10  pure blue
    (  0,  60, 255),   # 11  blue
    (  0, 140, 255),   # 12  sky blue
    (  0, 200, 255),   # 13  cyan-blue
    (  0, 255, 220),   # 14  cyan
    (  0, 255, 160),   # 15  cyan-green
    (  0, 255,  80),   # 16  green
    (  0, 220,   0),   # 17  pure green
    ( 80, 255,   0),   # 18  yellow-green
    (160, 255,   0),   # 19  lime
    (220, 255,   0),   # 20  yellow-lime
    (255, 240,   0),   # 21  yellow
    (255, 180,  40),   # 22  sunflower
    (255, 100,  80),   # 23  coral
    (255,  80, 160),   # 24  salmon-pink
    (180,  40, 255),   # 25  purple
    ( 40, 100, 255),   # 26  periwinkle
    (  0, 180, 180),   # 27  teal
    ( 20, 255, 120),   # 28  mint
    (255, 220, 120),   # 29  pale gold
)


def _lerp(a, b, t):
    return a + (b - a) * t


def tint(position):
    """The RGB tint at `position`, before saturation is applied."""
    n = len(TINT_PALETTE)
    scaled = position * (n - 1)
    idx = int(scaled)
    if idx >= n - 1:
        return TINT_PALETTE[-1]
    c1, c2 = TINT_PALETTE[idx], TINT_PALETTE[idx + 1]
    frac = scaled - idx
    return tuple(int(_lerp(a, b, frac)) for a, b in zip(c1, c2))


def rgbw(position, w_level=1.0):
    """RGBW at palette `position`, with the W channel scaled by w_level.

    Matches ColourEngine in the original project: the tint is blended in
    by `sat = position`, and W fades out by the same amount, so the two
    always trade against each other. `w_level` is the separate per-lamp
    warm-white trim, applied on top exactly as the original applied it
    per group.
    """
    position = max(0.0, min(1.0, position))
    w_level = max(0.0, min(1.0, w_level))
    tr, tg, tb = tint(position)
    sat = position
    return (int(_lerp(BASE_WARM_WHITE[0], tr, sat)),
            int(_lerp(BASE_WARM_WHITE[1], tg, sat)),
            int(_lerp(BASE_WARM_WHITE[2], tb, sat)),
            int(BASE_WARM_WHITE[3] * (1.0 - sat) * w_level))


# ── Sunrise gradient ─────────────────────────────────────────
# Also from the original, and deliberately NOT taken from TINT_PALETTE:
# there a single position sets hue and saturation together, so anything
# warm is also nearly white and a dawn would be an invisible tint.
SUNRISE_STOPS = (
    (255,  20,   0,   0),   # 0.00  ember red
    (255,  70,   0,   0),   # 0.33  deep orange
    (255, 140,  20,  40),   # 0.66  amber, white creeping in
    (255, 190, 110, 190),   # 1.00  warm white
)


def sunrise(t):
    """RGBW along the sunrise gradient for t in 0.0-1.0."""
    t = max(0.0, min(1.0, t))
    n = len(SUNRISE_STOPS) - 1
    scaled = t * n
    i = int(scaled)
    if i >= n:
        return SUNRISE_STOPS[-1]
    a, b = SUNRISE_STOPS[i], SUNRISE_STOPS[i + 1]
    frac = scaled - i
    return tuple(int(_lerp(x, y, frac)) for x, y in zip(a, b))
