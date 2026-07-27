# ============================================================
#  main.py  —  Friend Lights Open
# ============================================================
# Runs identically on every lamp. Only config.py differs, and within it
# only LAMP_ID has to.

import gc
import os
import sys
import utime
import ujson
import machine

sys.path.append("/lamp")

import codec
from shared_state import SharedColour
from palette import BASE_WARM_WHITE
from driver import Strip
from touch import TouchManager
from engine import Engine
from net.transport import Router

import config

FIRMWARE_VERSION = "2026-07-27.1"
FRAME_MS         = 16
STATE_FILE       = "state.json"
STATE_FLUSH_MS   = 5 * 60 * 1000
HEARTBEAT_MS     = 60 * 60 * 1000     # re-send our totals hourly even if idle

wdt = None


def feed():
    if wdt:
        wdt.feed()


def _cfg(name, default):
    """Config values must be read with a fallback: config.py is never
    overwritten, so a lamp already in someone's house will not have keys
    added by a later version."""
    return getattr(config, name, default)


# ── Flash ────────────────────────────────────────────────────

def _write_json(fname, obj):
    """Atomic write — a power cut mid-write must not corrupt state."""
    tmp = fname + ".tmp"
    with open(tmp, "w") as f:
        ujson.dump(obj, f)
    os.rename(tmp, fname)


_saved = None


def save_state(shared, engine, force=False):
    """Persist power, brightness and the convergent counters.

    The counters matter most: losing a peer's contribution on reboot
    would visibly undo their colour, which is the one failure a
    friendship light cannot have. Writes are skipped when nothing
    changed, so this can be called freely without wearing the flash.
    """
    global _saved
    snap = {"on": engine.is_on,
            "brightness": round(engine.brightness, 3),
            "shared": shared.snapshot()}
    if not force and snap == _saved:
        return
    try:
        _write_json(STATE_FILE, snap)
        _saved = snap
    except Exception as e:
        print("[state] save failed: %s" % e)


def restore_state(shared):
    """Returns (on, brightness). Junk on flash must never block boot."""
    global _saved
    try:
        with open(STATE_FILE) as f:
            data = ujson.load(f)
        shared.restore(data.get("shared") or {})
        _saved = data
        return bool(data.get("on", True)), float(data.get("brightness", 0.6))
    except Exception:
        return True, _cfg("LED_BRIGHTNESS", 0.6)


# ── Transports ───────────────────────────────────────────────

def build_transports(tick=None):
    router = Router()

    if _cfg("LORA_ENABLED", False):
        try:
            from machine import UART, Pin
            from net.lorawan_e5 import LoRaWANE5
            uart = UART(_cfg("LORA_UART_ID", 1),
                        baudrate=_cfg("LORA_BAUD", 9600),
                        tx=Pin(_cfg("LORA_TX_PIN", 43)),
                        rx=Pin(_cfg("LORA_RX_PIN", 44)))
            lora = LoRaWANE5(
                uart,
                _cfg("LORA_DEV_EUI", ""), _cfg("LORA_APP_EUI", ""),
                _cfg("LORA_APP_KEY", ""),
                region=_cfg("LORA_REGION", "EU868"),
                lora_class=_cfg("LORA_CLASS", "C"),
                port=_cfg("LORA_PORT", 8),
                min_interval_ms=_cfg("LORA_MIN_INTERVAL_MS", 900_000))
            lora.start(tick=tick)
            router.add(lora)
        except Exception as e:
            print("[lora] unavailable: %s" % e)

    if _cfg("WIFI_ENABLED", False):
        try:
            from net.mqtt_wifi import MQTTWiFi
            prefix = _cfg("MQTT_PREFIX", "friendlights")
            mqtt = MQTTWiFi(_mqtt_factory,
                            prefix + "/state",
                            prefix + "/status/%d" % config.LAMP_ID)
            mqtt.start(tick=tick)
            router.add(mqtt)
        except Exception as e:
            print("[wifi] unavailable: %s" % e)

    return router


def _mqtt_factory():
    """Connect WiFi if needed, then return a connected MQTT client."""
    import network
    import ubinascii
    from umqtt.simple import MQTTClient

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        for ssid, password in _cfg("WIFI_NETWORKS", []):
            print("[wifi] trying %s..." % ssid)
            wlan.connect(ssid, password)
            deadline = utime.ticks_add(utime.ticks_ms(), 12_000)
            while not wlan.isconnected():
                if utime.ticks_diff(deadline, utime.ticks_ms()) <= 0:
                    wlan.disconnect()
                    break
                feed()
                utime.sleep_ms(50)
            if wlan.isconnected():
                print("[wifi] connected — %s" % wlan.ifconfig()[0])
                break
        else:
            raise OSError("no known WiFi network")

    uid = ubinascii.hexlify(machine.unique_id()).decode()
    client = MQTTClient("lamp%d_%s" % (config.LAMP_ID, uid),
                        _cfg("MQTT_BROKER", ""),
                        port=_cfg("MQTT_PORT", 1883),
                        user=_cfg("MQTT_USER", "") or None,
                        password=_cfg("MQTT_PASSWORD", "") or None,
                        keepalive=60)
    client.connect()
    return client


# ── Setup pulse ──────────────────────────────────────────────

class Pulser:
    """Warm-white breath shown while the LoRaWAN join runs. The join can
    take a minute; without this the lamp looks dead for that whole time."""

    def __init__(self, strip):
        self.strip = strip
        self.phase = 0.0
        self.last = utime.ticks_ms()

    def tick(self):
        feed()
        import math
        now = utime.ticks_ms()
        dt = utime.ticks_diff(now, self.last)
        self.last = now
        self.phase += 0.004 * dt
        w = int(60 + 50 * math.sin(self.phase))
        self.strip.set_all(0, 0, 0, max(0, w))
        self.strip.show()

    def stop(self):
        for step in range(20):
            self.strip.set_all(0, 0, 0, int(60 * (1 - step / 20)))
            self.strip.show()
            utime.sleep_ms(15)
        self.strip.off()


# ── Main ─────────────────────────────────────────────────────

def main():
    global wdt

    lamp_id = _cfg("LAMP_ID", 1)
    print("[boot] friend-lights-open %s — lamp %d (%s)"
          % (FIRMWARE_VERSION, lamp_id, _cfg("LAMP_NAME", "")))

    if _cfg("WATCHDOG_ENABLED", True) and wdt is None:
        wdt = machine.WDT(timeout=8000)

    strip = Strip(_cfg("LED_PIN", 2), _cfg("NUM_LEDS", 10),
                  brightness=_cfg("LED_BRIGHTNESS", 0.6),
                  order=_cfg("LED_ORDER", "GRBW"),
                  reverse=_cfg("REVERSE_LEDS", False))
    pulser = Pulser(strip)

    shared = SharedColour(lamp_id)
    on, brightness = restore_state(shared)

    touch = TouchManager(_cfg("TOUCH_PINS", []), _cfg("TOUCH_THRESHOLD", 20000))
    touch.calibrate_all()

    router = build_transports(tick=pulser.tick)

    engine = Engine(shared, _cfg("NUM_LEDS", 10),
                    brightness=brightness,
                    arrival_fade_ms=_cfg("ARRIVAL_FADE_MS", 90_000),
                    breathe_speed=_cfg("BREATHE_SPEED", 0.0008),
                    breathe_depth=_cfg("BREATHE_DEPTH", 0.04))
    engine.set_power(on)
    if not on:
        engine._power_level = 0.0      # instant off, no fade-in at boot

    pulser.stop()

    def current_frame(touched=False):
        h, w, t = shared.my_totals()
        return codec.encode(lamp_id, h, w, t,
                            brightness=engine.brightness,
                            on=engine.is_on, touched=touched)

    now = utime.ticks_ms()
    next_frame     = now
    next_flush     = utime.ticks_add(now, STATE_FLUSH_MS)
    next_heartbeat = utime.ticks_add(now, HEARTBEAT_MS)
    next_gc        = utime.ticks_add(now, 60_000)
    dirty          = False              # we have news the peers lack

    # One write per boot guarantees the file exists, so a lamp that loses
    # power before its first flush still comes back with its counters.
    save_state(shared, engine, force=True)
    router.send(current_frame(), force=True)

    while True:
        now = utime.ticks_ms()
        feed()

        # ── Receive ──
        for raw in router.poll():
            try:
                msg = codec.decode(raw)
            except codec.DecodeError:
                continue                # junk on a public medium is normal
            if shared.apply_remote(msg["lamp_id"],
                                   msg["hue_total"], msg["warm_total"],
                                   msg["touch_count"],
                                   on=msg["on"], brightness=msg["brightness"]):
                print("[net] lamp %d -> hue %.3f" % (msg["lamp_id"], shared.hue()))
                engine.note_arrival()

        # ── Touch ──
        event = touch.update()
        if event == "tap":
            shared.touch()
            engine.note_arrival()       # keep our own touches out of the pulse
            dirty = True
            # Persist immediately. The 5-minute flush is fine for
            # brightness, but losing our own counter is worse than losing
            # a setting: a peer that already saw a higher total for us
            # would see it go BACKWARDS after our reboot, and the shared
            # colour would visibly jump back. Taps happen a few times a
            # day, so this costs nothing in flash wear.
            save_state(shared, engine)
            print("[touch] tap -> hue %.3f" % shared.hue())
        elif event == "hold":
            engine.toggle_power()
            dirty = True
            save_state(shared, engine, force=True)

        # ── Send ──
        # The transports throttle themselves, so this may simply be
        # declined; `dirty` stays set until something actually takes it.
        if dirty and router.send(current_frame(touched=True)):
            dirty = False

        if utime.ticks_diff(now, next_heartbeat) >= 0:
            # Costs one uplink an hour and means a lamp that missed
            # everything still converges without anyone touching anything.
            router.send(current_frame())
            next_heartbeat = utime.ticks_add(now, HEARTBEAT_MS)

        # ── Housekeeping ──
        if utime.ticks_diff(now, next_flush) >= 0:
            save_state(shared, engine)
            next_flush = utime.ticks_add(now, STATE_FLUSH_MS)

        if utime.ticks_diff(now, next_gc) >= 0:
            gc.collect()
            next_gc = utime.ticks_add(now, 60_000)

        # ── Render ──
        if utime.ticks_diff(now, next_frame) >= 0:
            engine.tick(strip)
            next_frame = utime.ticks_add(now, FRAME_MS)

        utime.sleep_ms(1)


if __name__ == "__main__":
    while True:
        try:
            main()
        except Exception as e:
            sys.print_exception(e)
            print("[FATAL] rebooting in 5 s")
            for _ in range(5):
                feed()
                utime.sleep(1)
            machine.reset()
