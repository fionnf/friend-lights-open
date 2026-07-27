# ============================================================
#  transport.py  —  One interface, several radios
# ============================================================
# A lamp may reach its friends over LoRaWAN, over WiFi, or over both at
# once, and which it has can change while it is running. The rest of the
# firmware should never know or care.
#
# What makes this cheap is the CRDT in shared_state.py. Because every
# message carries an absolute total rather than a delta, and because
# folding a total in is idempotent and commutative:
#
#   * the SAME message arriving over both transports is harmless
#   * a LoRa message arriving after the WiFi message that superseded it
#     is harmless
#   * a transport appearing or vanishing mid-run needs no handover logic
#
# So transports do not need to be coordinated, deduplicated or ranked.
# They are just mouths and ears. That is the entire payoff of paying the
# CRDT's design cost up front.
#
# ── Why the transports still are not interchangeable ──────────────────
# They carry identical payloads but have wildly different budgets:
#
#              latency     payload    messages/day inbound
#   WiFi/MQTT  ~100 ms     any        unlimited
#   LoRaWAN    2-10 s      10 bytes   10  (TTN Fair Use Policy)
#
# So sending policy differs even though the format does not. That is what
# `min_interval_ms` is for: each transport throttles itself, and the
# router simply offers every change to every transport.

import utime


class Transport:
    """Base class. Subclasses override start/poll/send/stop.

    None of these may raise. A radio that is unplugged, unjoined or
    misconfigured must degrade to 'sends nothing, receives nothing' —
    never to an exception that takes the lamp down. A lamp with a dead
    radio is still a lamp.
    """

    name = "transport"
    # Minimum gap between outbound frames. 0 = send whatever you like.
    min_interval_ms = 0

    def __init__(self):
        self._next_send_at = 0
        self.connected = False

    # ── Lifecycle ───────────────────────────────────────────

    def start(self):
        """Bring the link up. Best-effort; set self.connected."""
        self.connected = False

    def stop(self):
        self.connected = False

    # ── Data ────────────────────────────────────────────────

    def poll(self):
        """Return a list of raw payloads (bytes) received since the last
        call. Empty list is the normal case and must be cheap — this is
        called from the render loop."""
        return []

    def _send(self, payload):
        """Actually transmit. Subclasses implement this."""
        raise NotImplementedError

    # ── Throttling ──────────────────────────────────────────

    def ready_to_send(self, now=None):
        if not self.connected:
            return False
        if self.min_interval_ms <= 0:
            return True
        now = utime.ticks_ms() if now is None else now
        return utime.ticks_diff(now, self._next_send_at) >= 0

    def send(self, payload, force=False):
        """Transmit if the budget allows. Returns True if it went out.

        `force` bypasses the interval but not the connection check — used
        for things that must not wait, like a power-off, accepting that
        it spends from the airtime budget.
        """
        if not self.connected:
            return False
        now = utime.ticks_ms()
        if not force and not self.ready_to_send(now):
            return False
        try:
            self._send(payload)
        except Exception as e:
            print("[%s] send failed: %s" % (self.name, e))
            self.connected = False
            return False
        self._next_send_at = utime.ticks_add(now, self.min_interval_ms)
        return True


class Router:
    """Fans one payload out to every transport, and gathers what they hear.

    Deliberately dumb: no preference order, no failover, no 'primary'
    link. Every transport gets offered every change and decides for
    itself whether its budget allows sending. If both a WiFi and a LoRa
    link are up, the friend's lamp simply hears the same state twice,
    which the CRDT absorbs without noticing.
    """

    def __init__(self, transports=None):
        self.transports = list(transports or [])

    def add(self, transport):
        self.transports.append(transport)

    def start(self):
        for t in self.transports:
            try:
                t.start()
                print("[net] %s: %s" % (t.name,
                                        "up" if t.connected else "unavailable"))
            except Exception as e:
                print("[net] %s failed to start: %s" % (t.name, e))

    def poll(self):
        """Every payload heard on any transport, in no particular order."""
        out = []
        for t in self.transports:
            try:
                got = t.poll()
            except Exception as e:
                print("[net] %s poll failed: %s" % (t.name, e))
                t.connected = False
                continue
            if got:
                out.extend(got)
        return out

    def send(self, payload, force=False):
        """Offer a payload to every transport. Returns how many took it."""
        sent = 0
        for t in self.transports:
            if t.send(payload, force=force):
                sent += 1
        return sent

    def any_connected(self):
        return any(t.connected for t in self.transports)

    def status(self):
        return {t.name: t.connected for t in self.transports}
