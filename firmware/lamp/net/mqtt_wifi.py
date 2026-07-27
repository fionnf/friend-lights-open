# ============================================================
#  mqtt_wifi.py  —  The same 10 bytes, over WiFi
# ============================================================
# Identical payload to the LoRaWAN transport, so a lamp on WiFi and a
# lamp on TTN speak the same language and neither knows the difference.
#
# Note what this transport does NOT have to do:
#
#   * no echo suppression — the payload names its sender, and
#     SharedColour.apply_remote() ignores our own lamp_id
#   * no sequence numbers, no acks, no retry — the counters are absolute,
#     so the next message repairs whatever this one lost
#   * no reconciliation with what arrived over LoRa — folding the same
#     total in twice is a no-op
#
# The original two-board firmware needed all three of those, and the
# `echo` flag in its protocol existed solely because a state report was
# indistinguishable from a command. Absolute counters make the whole
# category of problem disappear.

import utime

from .transport import Transport

# Retained, so a lamp that has been unplugged (or that has just spent the
# night with no hotspot) learns the group's current state the instant it
# reconnects, rather than waiting for someone to touch a lamp. This is
# what makes intermittent connectivity converge instead of just lag.
RETAIN = True


class MQTTWiFi(Transport):

    name = "mqtt"
    # WiFi is effectively free. Send whatever we like; the throttle exists
    # only for LoRaWAN.
    min_interval_ms = 0

    def __init__(self, client_factory, topic, status_topic=None):
        """`client_factory` returns a connected umqtt client, or raises.

        Passing a factory rather than a client keeps every credential and
        broker detail in config, and lets reconnection be a matter of
        calling it again.
        """
        Transport.__init__(self)
        self._factory      = client_factory
        self.topic         = topic.encode() if isinstance(topic, str) else topic
        self.status_topic  = (status_topic.encode()
                              if isinstance(status_topic, str) else status_topic)
        self._client = None
        self._rx = []

    # ── Lifecycle ───────────────────────────────────────────

    def start(self, tick=None):
        self.connected = False
        try:
            self._client = self._factory()
            self._client.set_callback(self._on_message)
            self._client.subscribe(self.topic)
            self.connected = True
            print("[mqtt] subscribed to %s" % self.topic)
            return True
        except Exception as e:
            print("[mqtt] connect failed: %s" % e)
            self._client = None
            return False

    def stop(self):
        self.connected = False
        try:
            if self._client:
                self._client.disconnect()
        except Exception:
            pass
        self._client = None

    # ── Data ────────────────────────────────────────────────

    def _on_message(self, topic, msg):
        """Called from inside check_msg(). Must never raise — an
        exception here tears down the MQTT connection, so one malformed
        retained message would cause a permanent reconnect loop."""
        try:
            if msg:
                self._rx.append(bytes(msg))
        except Exception:
            pass

    def poll(self):
        if not self._client:
            return []
        try:
            self._client.check_msg()      # non-blocking
        except Exception as e:
            print("[mqtt] poll failed: %s" % e)
            self.connected = False
            self._client = None
            return []
        if not self._rx:
            return []
        got, self._rx = self._rx, []
        return got

    def _send(self, payload):
        if not self._client:
            raise OSError("not connected")
        self._client.publish(self.topic, bytes(payload), retain=RETAIN)

    # ── Presence ────────────────────────────────────────────

    def publish_status(self, payload):
        """Retained presence, separate from lamp state. Best-effort."""
        if not (self._client and self.status_topic):
            return
        try:
            self._client.publish(self.status_topic, payload, retain=True)
        except Exception as e:
            print("[mqtt] status publish failed: %s" % e)
            self.connected = False
