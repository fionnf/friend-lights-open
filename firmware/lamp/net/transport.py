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
    # Average gap between outbound frames. 0 = send whatever you like.
    min_interval_ms = 0
    # How many sends may happen back-to-back before the average gap
    # kicks in. See the throttling section below.
    burst = 4

    # Backoff bounds for automatic reconnection.
    RETRY_MIN_MS = 60_000
    RETRY_MAX_MS = 30 * 60 * 1000

    def __init__(self):
        # Two tokens at boot, not a full bucket: the boot announcement
        # spends one, leaving one so the first touch after power-on
        # still goes out immediately — while a lamp on flaky power
        # can't mint a full burst per brownout.
        self._tokens = 2.0
        self._last_refill = utime.ticks_ms()
        self._retry_at = None
        self._retry_backoff = 0
        self.connected = False

    # ── Lifecycle ───────────────────────────────────────────

    def start(self, tick=None):
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
    # A token bucket, not a fixed gap. The budget being protected is
    # the FRIEND's ten downlinks a day, and a fixed three-hour gap
    # spends it in the most annoying way possible: evenly, so even the
    # first touch of a quiet day waits hours. The bucket holds `burst`
    # sends and refills one per `min_interval_ms` — so the first few
    # touches of the day travel in seconds, the wait only appears once
    # the burst is spent, and the steady-state daily total is identical.

    def _refill(self, now):
        elapsed = utime.ticks_diff(now, self._last_refill)
        if elapsed > 0:
            self._tokens = min(float(self.burst),
                               self._tokens + elapsed / self.min_interval_ms)
            self._last_refill = now

    def ready_to_send(self, now=None):
        if not self.connected:
            return False
        if self.min_interval_ms <= 0:
            return True
        now = utime.ticks_ms() if now is None else now
        self._refill(now)
        return self._tokens >= 1.0

    def send(self, payload, force=False):
        """Transmit if the budget allows. Returns True if it went out.

        `force` bypasses the bucket but not the connection check — used
        for things that must not wait, like a power-off. It still spends
        a token when one is there: a forced send is a real downlink on
        the friend's lamp, whatever the reason for forcing it.
        """
        if not self.connected:
            return False
        if self.min_interval_ms > 0:
            self._refill(utime.ticks_ms())
            if not force and self._tokens < 1.0:
                return False
        try:
            self._send(payload)
        except Exception as e:
            print("[%s] send failed: %s" % (self.name, e))
            self.connected = False
            return False
        if self.min_interval_ms > 0:
            self._tokens = max(0.0, self._tokens - 1.0)
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

    def service(self, tick=None):
        """Retry any transport that has dropped, with backoff.

        Without this a link is lost permanently. A UART hiccup sets
        `connected` to False, nothing ever calls start() again, and there
        is no daily reboot in this firmware to paper over it — so a lamp
        would sit there looking fine and silently stop reaching its
        friend until someone unplugged it.

        `tick` is handed to start() so a 90 s LoRaWAN join keeps the lamp
        rendering and the watchdog fed instead of freezing mid-breath.
        """
        now = utime.ticks_ms()
        for t in self.transports:
            if t.connected:
                t._retry_at = None          # recovered; forget the backoff
                t._retry_backoff = 0
                continue
            if t._retry_at is None:
                # Wait one interval before the first retry — a transport
                # that just failed to start is unlikely to succeed now.
                t._retry_backoff = t.RETRY_MIN_MS
                t._retry_at = utime.ticks_add(now, t._retry_backoff)
                continue
            if utime.ticks_diff(now, t._retry_at) < 0:
                continue
            print("[net] retrying %s" % t.name)
            try:
                t.start(tick=tick)
            except Exception as e:
                print("[net] %s retry failed: %s" % (t.name, e))
            t._retry_backoff = min(t._retry_backoff * 2, t.RETRY_MAX_MS)
            t._retry_at = utime.ticks_add(now, t._retry_backoff)

    def ready(self):
        """True if any transport would accept a frame right now.

        Callers check this BEFORE building a payload. Without it, code of
        the shape

            if dirty and router.send(build_frame()):

        rebuilds the frame on every pass of the render loop — Python
        evaluates the argument before it can be refused. With LoRaWAN
        throttled to 15 minutes that is roughly a million discarded
        allocations between two sends, and if no transport is connected
        at all, it never stops.
        """
        return any(t.ready_to_send() for t in self.transports)

    def any_connected(self):
        return any(t.connected for t in self.transports)

    def status(self):
        return {t.name: t.connected for t in self.transports}
