# ============================================================
#  shared_state.py  —  The colour both lamps agree on
# ============================================================
# The Things Network's Fair Use Policy allows a device to RECEIVE ten
# downlink messages per day. Ten. That single number decides the whole
# design of this file.
#
# A conventional "send the new colour, other lamp applies it" protocol
# cannot survive that. Miss a message — and you will miss most of them —
# and the two lamps disagree forever, with no way to notice or recover.
#
# So the lamps do not exchange colours. Each lamp owns one grow-only
# counter and only ever increments its OWN. The displayed colour is a
# function of the SUM of every lamp's counter. This is a G-Counter CRDT,
# and it buys three properties that matter here:
#
#   1. ORDER-INDEPENDENT. Addition commutes, so messages arriving out of
#      order converge to the same colour.
#   2. SELF-HEALING. Each message carries the sender's running TOTAL, not
#      a delta. A lost message is repaired by the next one — no
#      retransmission, no acknowledgement, no sequence numbers.
#   3. BATCHABLE FOR FREE. Ten touches collapse into one downlink with no
#      information lost, because the total already contains them.
#
# The last one is what makes ten downlinks a day survivable rather than
# crippling. The network's meanest constraint costs us nothing.
#
# ── Why wrapping counters are safe ──────────────────────────────────
# The counters are uint16 and wrap at 65536. For hue that is not a
# compromise, it is the point: hue is a circle, so a wrapping counter IS
# the colour wheel. Warmth is not circular, so its counter is mapped
# through a triangle wave — it rises, then falls, and never jumps.
#
# Wrapping does mean the state is only convergent so long as no lamp
# silently races more than a full revolution ahead of the other between
# messages. At the touch step sizes below that is thousands of touches
# between two downlinks, which the airtime budget makes impossible.

COUNTER_MODULO = 0x10000
HALF_MODULO    = COUNTER_MODULO // 2

# One touch advances the hue by 1/16 of the wheel, so a run of sixteen
# taps travels right around it. Tuned for feel, not for maths.
TOUCH_HUE_STEP  = COUNTER_MODULO // 16
TOUCH_WARM_STEP = COUNTER_MODULO // 24


def _wrap(n):
    return int(n) % COUNTER_MODULO


def _mix(seed, salt):
    """A small deterministic hash to 0.0-1.0.

    Both lamps must compute byte-identical results from the same inputs,
    so this cannot use urandom, the clock, or anything else that differs
    between two devices. Integer ops only, masked to 32 bits so
    MicroPython and CPython agree.
    """
    x = (int(seed) * 2654435761 + int(salt) * 2246822519) & 0xFFFFFFFF
    x ^= x >> 13
    x = (x * 1274126177) & 0xFFFFFFFF
    x ^= x >> 16
    return x / 4294967296.0


def _triangle(counter):
    """Map a wrapping counter to 0.0-1.0 and back again.

    Used for anything that is a range rather than a circle. A raw
    wrapping counter would snap from 1.0 to 0.0 at the wrap point; a
    triangle reverses direction instead, so the value oscillates
    smoothly while the counter underneath stays monotonic (and therefore
    still converges).
    """
    c = _wrap(counter)
    if c < HALF_MODULO:
        return c / HALF_MODULO
    return (COUNTER_MODULO - c) / HALF_MODULO


class SharedColour:
    """The colour agreed between every lamp in a group.

    Each lamp constructs this with its own id. It increments only its own
    counter (via touch/nudge) and folds in whatever it hears from peers
    (via apply_remote). Every lamp that has heard the same set of
    messages — in any order, with any duplicates — computes the same
    colour.
    """

    def __init__(self, lamp_id):
        if not (1 <= int(lamp_id) <= 255):
            raise ValueError("lamp_id must be 1-255")
        self.lamp_id = int(lamp_id)
        # lamp_id -> counters. Our own entry is authoritative and only we
        # may write it; peers' entries are only ever overwritten by their
        # own messages.
        self._hue   = {self.lamp_id: 0}
        self._warm  = {self.lamp_id: 0}
        self._touch = {self.lamp_id: 0}
        # Peer metadata, not part of the convergent state
        self.peer_on = {}
        self.peer_brightness = {}

    # ── Local input ─────────────────────────────────────────

    def touch(self, steps=1):
        """A physical touch on THIS lamp. Advances our own counters."""
        self.nudge(hue=TOUCH_HUE_STEP * steps,
                   warm=TOUCH_WARM_STEP * steps,
                   touches=steps)

    def nudge(self, hue=0, warm=0, touches=0):
        """Advance our own counters by arbitrary amounts.

        Only ever called for our own lamp_id — that invariant is what
        makes the merge safe. Increments are non-negative by convention;
        a negative one still converges but makes the counter no longer
        grow-only, so peers could see it go backwards.
        """
        me = self.lamp_id
        self._hue[me]   = _wrap(self._hue[me] + hue)
        self._warm[me]  = _wrap(self._warm[me] + warm)
        self._touch[me] = _wrap(self._touch[me] + touches)

    # ── Remote input ────────────────────────────────────────

    def apply_remote(self, lamp_id, hue_total, warm_total, touch_count,
                     on=None, brightness=None):
        """Fold in a peer's reported totals.

        Returns True if this changed anything — callers use that to
        decide whether to start a fade, so a duplicate frame does not
        restart an in-progress transition.

        A message claiming to be from us is ignored: we are the only
        authority on our own counter, and accepting an echo of our own
        state would let a repeater roll us backwards.
        """
        lamp_id = int(lamp_id)
        if lamp_id == self.lamp_id:
            return False

        hue   = _wrap(hue_total)
        warm  = _wrap(warm_total)
        touch = _wrap(touch_count)

        changed = (self._hue.get(lamp_id)   != hue or
                   self._warm.get(lamp_id)  != warm or
                   self._touch.get(lamp_id) != touch)

        self._hue[lamp_id]   = hue
        self._warm[lamp_id]  = warm
        self._touch[lamp_id] = touch

        if on is not None:
            self.peer_on[lamp_id] = bool(on)
        if brightness is not None:
            self.peer_brightness[lamp_id] = float(brightness)
        return changed

    # ── Groups ──────────────────────────────────────────────
    # The original project splits the strip into zones, each its own
    # colour, with sizes reshuffled on every touch. Sending all that
    # would need a byte or three per group on a link that allows ten
    # messages a day.
    #
    # So it is DERIVED instead. Both lamps run the same tiny hash over
    # the same agreed counter, so they compute identical zones without a
    # single extra byte on the wire. Convergence comes for free: same
    # counter in, same stripe pattern out.

    def group_position(self, index, count, spread=0.35):
        """Palette position for one zone.

        Zone 0 is the agreed position exactly, so a slider on the page
        still means what it says. The rest sit around it by a fixed
        offset that reshuffles whenever the counter moves — which is what
        makes a touch feel like the original's impulse() rather than the
        whole strip sliding as one.
        """
        base = self.position()
        if count <= 1 or index <= 0:
            return base
        seed = _wrap(sum(self._hue.values()))
        off = (_mix(seed, index) - 0.5) * spread
        return max(0.0, min(1.0, base + off))

    def group_sizes(self, num_leds, count, min_leds=1, max_leds=8):
        """How many LEDs each zone covers. Always sums to num_leds.

        Deterministic from the same counter, so both lamps show the same
        stripes, and reshuffled on a touch exactly as the original did.
        """
        count = max(1, min(int(count), int(num_leds)))
        if count == 1:
            return [num_leds]
        seed = _wrap(sum(self._hue.values()))
        sizes, remaining = [], num_leds
        for i in range(count):
            left = count - i
            lo = max(min_leds, remaining - (left - 1) * max_leds)
            hi = min(max_leds, remaining - (left - 1) * min_leds)
            if left == 1 or lo >= hi:
                size = max(lo, min(hi, remaining - (left - 1) * min_leds))
            else:
                size = lo + int(_mix(seed, 100 + i) * (hi - lo + 1))
                size = max(lo, min(hi, size))
            sizes.append(size)
            remaining -= size
        # Rounding can leave a LED over; the last zone absorbs it so no
        # LED is ever left showing a stale colour from the last scene.
        sizes[-1] += remaining
        return sizes

    # ── Derived colour ──────────────────────────────────────

    def position(self):
        """Agreed palette position, 0.0-1.0. See palette.py.

        A triangle rather than a raw wrap. In the original project `pos`
        couples hue and saturation, so 0.0 is pure warm white and 1.0 is
        fully saturated — the two ends are nothing alike, and a wrapping
        counter would snap from vivid straight back to white. Folding it
        back instead keeps the counter monotonic (so it still converges)
        while the light only ever drifts.

        It also means a lamp whose counters are zero — brand new, or just
        restored from nothing — is warm white, with no special case.
        """
        return _triangle(sum(self._hue.values()))

    # The colour engine and the page both called this `hue` first.
    hue = position

    def warmth(self):
        """The warm-white trim, 0.0-1.0 — the original's per-group `w`.

        Inverted so a counter of zero means 1.0, i.e. full warm white.
        Seeding the counter instead would not work: both lamps would seed
        the same value, and two half-turns sum to a whole one, landing
        straight back on zero.
        """
        return 1.0 - _triangle(sum(self._warm.values()))

    def total_touches(self):
        """Every touch by every lamp. Drives the 'while you were out'
        playback — the difference between two readings is how many times
        someone reached for their lamp since you last looked."""
        return _wrap(sum(self._touch.values()))

    def delta_to_position(self, target):
        """The increment that would put position() at `target`.

        The page can only ask for "make it this colour", but the CRDT can
        only ever ADD. Because position is a triangle, two different sums
        give the same position — one on the way up, one on the way down —
        so this picks whichever is the shorter move from where we are.
        Anything else would make the slider lurch the long way round.
        """
        target = max(0.0, min(1.0, float(target)))
        current = _wrap(sum(self._hue.values()))
        up = int(target * HALF_MODULO)                 # ascending branch
        down = _wrap(COUNTER_MODULO - up)              # descending branch
        best = None
        for candidate in (up, down):
            d = _wrap(candidate - current)
            if d > HALF_MODULO:
                d -= COUNTER_MODULO                    # shorter going back
            if best is None or abs(d) < abs(best):
                best = d
        return best

    # ── Wire helpers ────────────────────────────────────────

    def my_totals(self):
        """Our own counters, for encoding into an uplink."""
        me = self.lamp_id
        return (self._hue[me], self._warm[me], self._touch[me])

    def snapshot(self):
        """Full convergent state — for persisting to flash so a reboot
        does not lose a peer's contribution and undo their colour."""
        return {"hue":   dict(self._hue),
                "warm":  dict(self._warm),
                "touch": dict(self._touch)}

    def restore(self, snap):
        """Reload a snapshot, tolerating junk on flash."""
        try:
            for name, target in (("hue",   self._hue),
                                 ("warm",  self._warm),
                                 ("touch", self._touch)):
                stored = snap.get(name) or {}
                for k, v in stored.items():
                    k = int(k)          # JSON turns int keys into strings
                    if 1 <= k <= 255:
                        target[k] = _wrap(v)
            self._hue.setdefault(self.lamp_id, 0)
            self._warm.setdefault(self.lamp_id, 0)
            self._touch.setdefault(self.lamp_id, 0)
        except Exception:
            pass                        # corrupt state must not block boot
