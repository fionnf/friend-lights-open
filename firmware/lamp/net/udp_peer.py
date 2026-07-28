# ============================================================
#  udp_peer.py  —  The same 10 bytes, straight across the LAN
# ============================================================
# For two lamps on one WiFi network. No broker, no account, no
# internet, nothing to deploy: each lamp broadcasts its 10-byte frame to
# the subnet and listens for everyone else's.
#
# This exists because it is the shortest path from "two boards and a
# router" to "the whole lamp works". Every layer above it — the CRDT,
# the codec, the colour engine, the zones, the control page — is the
# same code the LoRaWAN lamp runs, so testing here tests all of that
# for real. Only the radio is left.
#
# Why broadcast rather than MQTT for this:
#
#   * MicroPython on the Pico W does not ship umqtt, so MQTT means
#     installing a dependency onto a board that may have no internet
#   * a broker means an account, a hostname and a password, all of
#     which can be wrong, on the day you are trying to find out
#     whether your soldering is right
#   * broadcast finds the other lamp with nothing configured at all
#
# What it gives up, and why that is fine here: broadcast does not leave
# the subnet, so this is not a way to link two HOMES — that is what the
# LoRaWAN transport is for. It is a way to link two lamps on one table.

import utime

from .transport import Transport

DEFAULT_PORT = 41234
# Frames are 10 bytes; anything larger is not ours. Reading into a fixed
# buffer keeps this allocation-free in the render loop.
MAX_FRAME = 64


class UDPPeer(Transport):
    """Broadcast to the subnet, listen to the subnet.

    WiFi is unmetered, so unlike the LoRaWAN transports there is no
    budget and no duty cycle here: min_interval_ms stays 0 and every
    change goes out immediately. That is the point of testing on it —
    you see the lamp's behaviour without waiting on a radio budget.
    """

    name = "udp"

    def __init__(self, connect, port=DEFAULT_PORT, broadcast="255.255.255.255"):
        Transport.__init__(self)
        # `connect` brings WiFi up and returns True; it is passed in
        # rather than done here so the same routine serves this and any
        # other WiFi transport, and so a test can supply its own.
        self._connect = connect
        self.port = port
        self.broadcast = broadcast
        self._sock = None
        self._buf = bytearray(MAX_FRAME)

    # ── Lifecycle ───────────────────────────────────────────

    def start(self, tick=None):
        self.connected = False
        self.stop()                      # never leak a socket on retry
        try:
            if not self._connect(tick=tick):
                return False
        except Exception as e:
            print("[udp] wifi failed: %s" % e)
            return False

        import socket
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            except Exception:
                # Some ports do not expose SO_BROADCAST and broadcast
                # anyway. Not worth failing over.
                pass
            sock.bind(("0.0.0.0", self.port))
            # Non-blocking: poll() is called from the render loop and
            # must never wait, or the lamp stops animating.
            sock.setblocking(False)
            self._sock = sock
            self.connected = True
            print("[udp] listening on port %d, broadcasting to %s"
                  % (self.port, self.broadcast))
            return True
        except Exception as e:
            print("[udp] socket failed: %s" % e)
            self.stop()
            return False

    def stop(self):
        self.connected = False
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    # ── Data ────────────────────────────────────────────────

    def poll(self):
        if not self.connected or self._sock is None:
            return []
        out = []
        # Drain whatever arrived. A bounded loop rather than `while
        # True`: a broadcast storm must not be able to hold the render
        # loop, and anything we skip is repaired by the next frame
        # anyway — the counters are absolute.
        for _ in range(8):
            try:
                data, _addr = self._sock.recvfrom(MAX_FRAME)
            except OSError:
                break                    # EAGAIN — nothing waiting
            except Exception as e:
                print("[udp] receive failed: %s" % e)
                self.connected = False
                break
            if data:
                out.append(bytes(data))
        return out

    def _send(self, payload):
        if self._sock is None:
            raise OSError("no socket")
        self._sock.sendto(payload, (self.broadcast, self.port))
