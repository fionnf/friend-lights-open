# ============================================================
#  palette.py  —  Hue position to RGBW
# ============================================================
# Kept in its own module, separate from config.py, deliberately: config.py
# holds per-lamp secrets and is never overwritten by an update, so a
# palette living there could never be improved on a lamp already in
# someone's house. This file can be updated freely.

# Warm white is carried almost entirely by the W channel of an SK6812.
BASE_WARM_WHITE = (0, 0, 0, 200)

# Adjacent entries interpolate, so the wheel is continuous. The last
# entry wraps back to the first — hue is a circle, and the CRDT counter
# that drives it wraps too, so the palette must close the loop or a lamp
# would visibly jump when its counter rolled over.
TINT_PALETTE = (
    (255, 200,  80),   # golden yellow
    (255, 160,   0),   # warm amber
    (255, 120,   0),   # deep amber
    (255,  60,   0),   # orange-red
    (255,   0,   0),   # pure red
    (255,   0,  60),   # red-pink
    (255,   0, 140),   # hot pink
    (200,   0, 200),   # magenta
    (140,   0, 255),   # violet
    ( 80,   0, 255),   # indigo
    (  0,   0, 255),   # pure blue
    (  0,  60, 255),   # blue
    (  0, 140, 255),   # sky blue
    (  0, 200, 255),   # cyan-blue
    (  0, 255, 220),   # cyan
    (  0, 255, 160),   # cyan-green
    (  0, 255,  80),   # green
    (  0, 220,   0),   # pure green
    ( 80, 255,   0),   # yellow-green
    (160, 255,   0),   # lime
    (220, 255,   0),   # yellow-lime
    (255, 240,   0),   # yellow
    (255, 180,  40),   # sunflower
)


def _lerp(a, b, t):
    return a + (b - a) * t


def tint(pos):
    """RGB tint at wheel position `pos` (0.0-1.0, wrapping)."""
    n = len(TINT_PALETTE)
    scaled = (pos % 1.0) * n          # % n, not n-1: the wheel closes
    i = int(scaled)
    frac = scaled - i
    c1 = TINT_PALETTE[i % n]
    c2 = TINT_PALETTE[(i + 1) % n]
    return tuple(int(_lerp(c1[k], c2[k], frac)) for k in range(3))


def rgbw(pos, warmth):
    """Colour at wheel position `pos`, blended toward warm white.

    `warmth` 1.0 is pure warm white (W channel only, no tint); 0.0 is the
    fully saturated hue. The W channel fades out as the tint comes up,
    otherwise every colour would read as a pale wash.
    """
    warmth = max(0.0, min(1.0, warmth))
    sat = 1.0 - warmth
    r, g, b = tint(pos)
    return (int(_lerp(BASE_WARM_WHITE[0], r, sat)),
            int(_lerp(BASE_WARM_WHITE[1], g, sat)),
            int(_lerp(BASE_WARM_WHITE[2], b, sat)),
            int(BASE_WARM_WHITE[3] * warmth))
