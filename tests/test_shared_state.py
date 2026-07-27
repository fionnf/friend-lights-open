#!/usr/bin/env python3
"""
CRDT convergence tests.

These are the load-bearing tests of the whole project. The lamps talk
over a network that delivers ten messages a day, out of order, with
losses and duplicates, and there is no acknowledgement layer to hide any
of that. Convergence is not a nice property here — it is the only reason
two lamps ever show the same colour.

Each test below corresponds to a specific way the network will misbehave.

Run from the repo root:   python3 tests/test_shared_state.py
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "firmware", "lamp"))

from shared_state import SharedColour, TOUCH_HUE_STEP, COUNTER_MODULO

failures = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name +
          (("  " + str(detail)) if detail and not cond else ""))
    if not cond:
        failures.append(name)


def gossip(sender, receiver):
    """Deliver sender's current totals to receiver."""
    h, w, t = sender.my_totals()
    return receiver.apply_remote(sender.lamp_id, h, w, t)


# ── Basics ───────────────────────────────────────────────────
print("\nbasics")

a = SharedColour(1)
check("starts at warm white", a.position() == 0.0, a.position())

a.touch()
check("own touch moves the palette position", a.position() > 0, a.position())
check("own touch counts", a.total_touches() == 1, a.total_touches())

check("cannot be spoofed by an echo of ourselves",
      a.apply_remote(1, 0, 0, 0) is False)
check("echo left our counter alone", a.total_touches() == 1)


# ── Convergence ──────────────────────────────────────────────
print("\nconvergence")

a, b = SharedColour(1), SharedColour(2)
a.touch(); a.touch()
b.touch()
gossip(a, b); gossip(b, a)
check("both lamps agree after exchange",
      abs(a.position() - b.position()) < 1e-9,
      "%s vs %s" % (a.position(), b.position()))
check("touch totals agree", a.total_touches() == b.total_touches() == 3)


# ── Order independence ───────────────────────────────────────
# LoRaWAN gives no ordering guarantee, and a WiFi message can overtake a
# LoRa one that was sent first. Applying the same set of updates in a
# different order must land on the same colour.
print("\norder independence")

x, y = SharedColour(9), SharedColour(9)
updates = [(1, 5000, 400, 3), (2, 12000, 900, 7), (3, 200, 60, 1)]
for u in updates:
    x.apply_remote(*u)
for u in reversed(updates):
    y.apply_remote(*u)
check("reversed delivery order converges", x.position() == y.position(),
      "%s vs %s" % (x.position(), y.position()))
check("reversed delivery order converges (warmth)", x.warmth() == y.warmth())


# ── Idempotence ──────────────────────────────────────────────
# The same state can legitimately arrive twice: once over LoRa and once
# over WiFi, or as a retained MQTT message replayed on reconnect.
print("\nidempotence")

c = SharedColour(1)
c.apply_remote(2, 8000, 500, 4)
once = c.hue()
changed = c.apply_remote(2, 8000, 500, 4)
check("duplicate does not move the colour", c.hue() == once)
check("duplicate reports 'no change'", changed is False)
check("a real change reports 'changed'", c.apply_remote(2, 8001, 500, 4) is True)


# ── Loss recovery ────────────────────────────────────────────
# The whole reason for sending absolute totals rather than deltas. Drop
# messages at random and the next one delivered must repair the state
# completely, with no retransmission.
print("\nloss recovery")

sender, receiver = SharedColour(1), SharedColour(2)
delivered = 0
for i in range(50):
    sender.touch()
    if i % 7 == 0:                     # deliver roughly 1 in 7
        gossip(sender, receiver)
        delivered += 1
gossip(sender, receiver)               # the one that finally gets through
h_s, w_s, t_s = sender.my_totals()
check("receiver caught up after heavy loss",
      receiver.apply_remote(1, h_s, w_s, t_s) is False,
      "still behind after final delivery")
check("50 touches survived %d deliveries" % delivered,
      receiver.total_touches() == 50, receiver.total_touches())


# ── Simultaneous edits ───────────────────────────────────────
# Both friends touch their lamps before either message is delivered.
# Neither contribution may be lost — that is the point of a light you
# share rather than mirror.
print("\nsimultaneous edits")

p, q = SharedColour(1), SharedColour(2)
p.touch(); p.touch(); p.touch()
q.touch(); q.touch()
gossip(p, q); gossip(q, p)
check("both contributions survive", p.total_touches() == 5, p.total_touches())
check("no lost update", p.position() == q.position())


# ── Wrapping ─────────────────────────────────────────────────
# Hue is a circle, so the counter is meant to wrap. Warmth is a range, so
# it must reverse rather than snap.
print("\nwrapping")

# Position folds back rather than wrapping: 0.0 is warm white and 1.0 is
# fully saturated, so a raw wrap would snap from vivid straight to white.
w = SharedColour(1)
check("a fresh lamp is at warm white", w.position() == 0.0, w.position())
poss = []
for _ in range(96):
    w.nudge(hue=COUNTER_MODULO // 48)
    poss.append(w.position())
check("position stays in range", all(0.0 <= p <= 1.0 for p in poss))
check("position reaches full saturation", max(poss) > 0.99, max(poss))
check("position comes back to warm white", min(poss[10:]) < 0.05, min(poss[10:]))
check("position never jumps",
      max(abs(poss[i] - poss[i-1]) for i in range(1, len(poss))) < 0.1)

warms = []
v = SharedColour(1)
for _ in range(64):
    v.nudge(warm=COUNTER_MODULO // 32)
    warms.append(v.warmth())
check("warmth stays in range", all(0.0 <= x <= 1.0 for x in warms))
jumps = [abs(warms[i] - warms[i - 1]) for i in range(1, len(warms))]
check("warmth never jumps discontinuously", max(jumps) < 0.15, max(jumps))


# ── Zones ────────────────────────────────────────────────────
# The strip splits into zones, each its own colour, as in the original.
# They are DERIVED from the agreed counter rather than transmitted — so
# they cost nothing on a link that allows ten messages a day, but they
# only work if two lamps compute byte-identical results.
print("\nzones")

za, zb = SharedColour(1), SharedColour(2)
za.touch(); za.touch(); za.touch()
gossip(za, zb)

for n in (1, 2, 3, 5, 8):
    sa = za.group_sizes(10, n)
    sb = zb.group_sizes(10, n)
    check("%d zones: both lamps compute the same sizes" % n, sa == sb,
          "%s vs %s" % (sa, sb))
    check("%d zones: sizes cover the strip exactly" % n, sum(sa) == 10, sa)
    check("%d zones: none is empty" % n, all(x >= 1 for x in sa), sa)
    pa = [round(za.group_position(i, n), 6) for i in range(n)]
    pb = [round(zb.group_position(i, n), 6) for i in range(n)]
    check("%d zones: both lamps compute the same colours" % n, pa == pb,
          "%s vs %s" % (pa, pb))
    check("%d zones: all in range" % n, all(0.0 <= x <= 1.0 for x in pa), pa)

check("zone 0 is the agreed position, so a slider still means something",
      za.group_position(0, 4) == za.position())

# A touch must reshuffle the layout, or the strip would only ever slide
# as one block — the original picked a fresh partition on every impulse.
before_sizes = za.group_sizes(10, 3)
before_pos = [za.group_position(i, 3) for i in range(3)]
layouts = set()
for _ in range(12):
    za.touch()
    layouts.add(tuple(za.group_sizes(10, 3)))
check("a touch reshuffles the zones", len(layouts) > 3, layouts)

# More zones than LEDs must not produce empty or negative ones.
tiny = SharedColour(1)
tiny.touch()
sizes = tiny.group_sizes(4, 9)
check("more zones than LEDs is clamped, not broken",
      sum(sizes) == 4 and all(x >= 1 for x in sizes), sizes)

# Zones must be stable while nothing changes, or the strip would crawl.
still = SharedColour(1)
still.touch()
check("zones are stable between touches",
      still.group_sizes(10, 3) == still.group_sizes(10, 3))


# ── Persistence ──────────────────────────────────────────────
# A reboot must not discard a friend's contribution — that would visibly
# undo their colour, which is the one failure a friendship light cannot
# have.
print("\npersistence")

s = SharedColour(1)
s.touch()
s.apply_remote(2, 4321, 765, 9)
snap = s.snapshot()

restored = SharedColour(1)
restored.restore(snap)
check("survives a reboot", restored.position() == s.position())
check("peer contribution survives", restored.total_touches() == s.total_touches())

json_ish = {k: {str(i): val for i, val in d.items()} for k, d in snap.items()}
from_json = SharedColour(1)
from_json.restore(json_ish)
check("survives JSON string keys", from_json.position() == s.position())

junk = SharedColour(1)
junk.restore({"hue": "not a dict", "nonsense": 5})
check("corrupt flash does not crash the boot", junk.position() == 0.0)


print("\n%d failed" % len(failures) if failures else "\nall passed")
sys.exit(1 if failures else 0)
