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
check("starts at hue 0", a.hue() == 0.0, a.hue())

a.touch()
check("own touch moves hue",
      abs(a.hue() - TOUCH_HUE_STEP / COUNTER_MODULO) < 1e-9, a.hue())
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
check("both lamps agree after exchange", abs(a.hue() - b.hue()) < 1e-9,
      "%s vs %s" % (a.hue(), b.hue()))
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
check("reversed delivery order converges", x.hue() == y.hue(),
      "%s vs %s" % (x.hue(), y.hue()))
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
check("no lost update", p.hue() == q.hue())


# ── Wrapping ─────────────────────────────────────────────────
# Hue is a circle, so the counter is meant to wrap. Warmth is a range, so
# it must reverse rather than snap.
print("\nwrapping")

w = SharedColour(1)
w.nudge(hue=COUNTER_MODULO - 10)
before = w.hue()
w.nudge(hue=20)
check("hue wraps past the top of the wheel", w.hue() < before,
      "%s -> %s" % (before, w.hue()))
check("hue stays in range", 0.0 <= w.hue() < 1.0, w.hue())

warms = []
v = SharedColour(1)
for _ in range(64):
    v.nudge(warm=COUNTER_MODULO // 32)
    warms.append(v.warmth())
check("warmth stays in range", all(0.0 <= x <= 1.0 for x in warms))
jumps = [abs(warms[i] - warms[i - 1]) for i in range(1, len(warms))]
check("warmth never jumps discontinuously", max(jumps) < 0.15, max(jumps))


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
check("survives a reboot", restored.hue() == s.hue())
check("peer contribution survives", restored.total_touches() == s.total_touches())

json_ish = {k: {str(i): val for i, val in d.items()} for k, d in snap.items()}
from_json = SharedColour(1)
from_json.restore(json_ish)
check("survives JSON string keys", from_json.hue() == s.hue())

junk = SharedColour(1)
junk.restore({"hue": "not a dict", "nonsense": 5})
check("corrupt flash does not crash the boot", junk.hue() == 0.0)


print("\n%d failed" % len(failures) if failures else "\nall passed")
sys.exit(1 if failures else 0)
