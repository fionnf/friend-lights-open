#!/usr/bin/env python3
"""
Two lamps, a whole day, in your terminal — no hardware.

Runs the REAL colour engine, CRDT and wire format against a fake network
that behaves like The Things Network at its worst: ten downlinks a day,
seconds of latency, dropped and reordered frames. Compressed time, so a
day takes about a minute.

  python3 tools/simulate.py                      # a day
  python3 tools/simulate.py --hours 72 --loss 0.5
  python3 tools/simulate.py --arrival-fade 10    # what a mirror feels like

This is how to tune the feel before committing to it. ARRIVAL_FADE_MS is
the single number that decides whether the lamp reads as post or as a
notification, and it is much easier to judge here than by waiting fifteen
minutes next to a real one.

Needs a terminal with 24-bit colour, which is nearly all of them.
"""
import argparse
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tests", "stubs"))
sys.path.insert(0, os.path.join(ROOT, "firmware", "lamp"))

import utime
import codec
import palette
from shared_state import SharedColour
from engine import Engine

RESET = "\x1b[0m"


def block(rgbw):
    """One LED as a coloured terminal cell. The white channel is folded
    into RGB the same way a WS2812 build would have to."""
    r, g, b, w = rgbw
    r = min(255, r + w)
    g = min(255, int(g + w * 0.82))
    b = min(255, int(b + w * 0.55))
    return "\x1b[48;2;%d;%d;%dm  %s" % (r, g, b, RESET)


class CaptureStrip:
    """Stands in for the LED driver and remembers the last frame."""

    def __init__(self, n):
        self.num_leds = n
        self.pixels = [(0, 0, 0, 0)] * n
        self.brightness = 1.0

    def set(self, i, r=0, g=0, b=0, w=0):
        if 0 <= i < self.num_leds:
            self.pixels[i] = (r, g, b, w)

    def set_all(self, r=0, g=0, b=0, w=0):
        self.pixels = [(r, g, b, w)] * self.num_leds

    def set_brightness(self, v):
        self.brightness = v

    def show(self):
        pass

    def off(self):
        self.set_all(0, 0, 0, 0)

    def render(self):
        br = self.brightness
        return "".join(block(tuple(int(c * br) for c in p)) for p in self.pixels)


class Lamp:
    def __init__(self, lamp_id, name, leds, arrival_fade_ms):
        self.id = lamp_id
        self.name = name
        self.shared = SharedColour(lamp_id)
        self.engine = Engine(self.shared, leds, brightness=0.7,
                             arrival_fade_ms=arrival_fade_ms)
        self.strip = CaptureStrip(leds)
        self.next_uplink = 0
        self.next_heartbeat = 0
        self.dirty = False
        self.downlinks_today = 0
        self.uplinks = 0
        self.dropped = 0

    def touch(self):
        self.shared.touch()
        self.engine.note_arrival(pulse=False)
        self.dirty = True

    def frame(self):
        h, w, t = self.shared.my_totals()
        return codec.encode(self.id, h, w, t,
                            brightness=self.engine.brightness,
                            on=self.engine.is_on)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=24)
    ap.add_argument("--leds", type=int, default=10)
    ap.add_argument("--loss", type=float, default=0.3,
                    help="fraction of frames the network eats (0-1)")
    ap.add_argument("--touches", type=int, default=14,
                    help="touches per lamp per day")
    ap.add_argument("--arrival-fade", type=float, default=90,
                    help="seconds for a colour to arrive (firmware default 90)")
    ap.add_argument("--uplink-interval", type=float, default=180,
                    help="minutes between change-driven uplinks")
    ap.add_argument("--heartbeat-hours", type=float, default=12,
                    help="hours between idle heartbeats")
    ap.add_argument("--downlink-cap", type=int, default=10,
                    help="TTN Fair Use Policy downlinks per lamp per day")
    ap.add_argument("--settle-hours", type=float, default=26,
                    help="quiet time after the last touch, so the verdict "
                         "means 'converged' rather than 'ended mid-cycle'")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--rows", type=int, default=40, help="lines of output")
    args = ap.parse_args()

    random.seed(args.seed)
    fade_ms = int(args.arrival_fade * 1000)
    a = Lamp(1, "lamp 1", args.leds, fade_ms)
    b = Lamp(2, "lamp 2", args.leds, fade_ms)
    lamps = {1: a, 2: b}

    total_ms = int(args.hours * 3600 * 1000)
    step_ms = 500                       # simulated tick
    uplink_ms = int(args.uplink_interval * 60 * 1000)
    heartbeat_ms = int(args.heartbeat_hours * 3600 * 1000)
    row_every = (max(1, total_ms // step_ms // args.rows)
                 if args.rows > 0 else 0)

    # When each friend reaches for their lamp.
    schedule = []
    for lamp in (a, b):
        for _ in range(int(args.touches * args.hours / 24)):
            schedule.append((random.randrange(0, total_ms), lamp))
    schedule.sort()
    schedule.reverse()                  # pop() from the end = earliest first

    in_flight = []                      # (deliver_at, target, payload)
    day = 0
    delivered = 0
    lost = 0

    print("\n  %s and %s, %g hours, %.0f%% packet loss, %d downlinks/day"
          % (a.name, b.name, args.hours, args.loss * 100, args.downlink_cap))
    print("  colour arrives over %gs; uplinks at most every %gmin; "
          "heartbeat every %gh\n"
          % (args.arrival_fade, args.uplink_interval, args.heartbeat_hours))
    print("   time    %-*s   %-*s  events" % (args.leds * 2, a.name,
                                              args.leds * 2, b.name))

    # Run past the last touch in silence. Without this the pair almost
    # always finishes a few touches apart — not because they diverged,
    # but because the newest touches are still sitting behind the send
    # throttle. A verdict that cannot distinguish those two is useless.
    settle_ms = int(args.settle_hours * 3600 * 1000)
    run_ms = total_ms + settle_ms

    elapsed = 0
    tick = 0
    while elapsed < run_ms:
        utime.sleep_ms(step_ms)
        elapsed += step_ms
        tick += 1
        events = []

        if elapsed // 86_400_000 > day:
            day = elapsed // 86_400_000
            a.downlinks_today = b.downlinks_today = 0
            events.append("new day, budgets reset")

        # ── Touches ── (none during the settle period)
        while schedule and schedule[-1][0] <= elapsed and elapsed < total_ms:
            _, lamp = schedule.pop()
            lamp.touch()
            events.append("%s touched" % lamp.name)

        # ── Uplinks, exactly as the firmware decides to send ──
        # Not "every N minutes": the firmware sends when something has
        # changed (throttled), plus a heartbeat so an idle pair still
        # converges. Modelling it as unconditional would badly overstate
        # how much of the downlink budget gets spent.
        for lamp in (a, b):
            due_change = lamp.dirty and elapsed >= lamp.next_uplink
            due_beat = elapsed >= lamp.next_heartbeat
            if not (due_change or due_beat):
                continue
            peer = b if lamp is a else a
            payload = lamp.frame()
            lamp.uplinks += 1
            lamp.dirty = False
            lamp.next_uplink = elapsed + uplink_ms
            if due_beat:
                lamp.next_heartbeat = elapsed + heartbeat_ms

            if peer.downlinks_today >= args.downlink_cap:
                events.append("%s OVER BUDGET, dropped" % peer.name)
                continue
            if random.random() < args.loss:
                lamp.dropped += 1
                lost += 1
                continue
            peer.downlinks_today += 1
            # Latency varies, so frames genuinely arrive out of order —
            # which is the whole reason the state is a CRDT.
            delay = random.randint(2000, 12000)
            in_flight.append((elapsed + delay, peer, payload))

        # ── Delivery ──
        for item in list(in_flight):
            when, target, payload = item
            if when > elapsed:
                continue
            in_flight.remove(item)
            try:
                msg = codec.decode(payload)
            except codec.DecodeError:
                continue
            if target.shared.apply_remote(
                    msg["lamp_id"], msg["hue_total"], msg["warm_total"],
                    msg["touch_count"], on=msg["on"],
                    brightness=msg["brightness"]):
                target.engine.note_arrival()
                delivered += 1
                events.append("%s received" % target.name)

        # ── Render ──
        a.engine.tick(a.strip)
        b.engine.tick(b.strip)

        if row_every and (tick % row_every == 0 or events):
            hrs, mins = divmod(elapsed // 60000, 60)
            gap = abs(a.shared.hue() - b.shared.hue())
            gap = min(gap, 1 - gap)                 # hue is a circle
            note = "; ".join(events)
            if not note:
                note = "apart by %.3f" % gap if gap > 0.002 else "agreed"
            print("  %3d:%02d  %s   %s  %s"
                  % (hrs, mins, a.strip.render(), b.strip.render(), note))

    # ── Verdict ──
    gap = abs(a.shared.hue() - b.shared.hue())
    gap = min(gap, 1 - gap)
    print("\n  uplinks sent      %d / %d" % (a.uplinks, b.uplinks))
    print("  frames delivered  %d   lost %d" % (delivered, lost))
    print("  touches shared    %d / %d"
          % (a.shared.total_touches(), b.shared.total_touches()))
    print("  final hue         %.4f / %.4f" % (a.shared.hue(), b.shared.hue()))

    ok = gap < 1e-9 and a.shared.total_touches() == b.shared.total_touches()
    if ok:
        print("\n  CONVERGED after %gh of quiet — both lamps agree despite "
              "%d lost frames.\n" % (args.settle_hours, lost))
        return 0
    print("\n  DID NOT CONVERGE: %.4f apart, %d frame(s) still in flight."
          % (gap, len(in_flight)))
    print("  If nothing is in flight this is a real divergence — the whole "
          "point of the CRDT is that it cannot happen.")
    print("  Try a longer --settle-hours first; a heartbeat has to fit "
          "inside it.\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
