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
from portal import Portal
from net.transport import Router

import config

FIRMWARE_VERSION = "2026-07-27.1"
FRAME_MS         = 16
STATE_FILE       = "state.json"
STATE_FLUSH_MS   = 5 * 60 * 1000
# Every uplink the bridge forwards becomes a DOWNLINK on the peer, and
# the peer may only receive ten a day. So this is budgeted against the
# friend's allowance, not our own airtime: 2 heartbeats a day, leaving 8
# for actual changes. See docs/PROTOCOL.md.
HEARTBEAT_MS     = 12 * 60 * 60 * 1000

wdt = None


def feed():
    if wdt:
        wdt.feed()


PROVISION_FILE = "provision.json"
_provision = {}


def load_provision():
    """Values entered through the setup portal, which win over config.py.

    Kept as a JSON overlay rather than rewriting config.py: generating
    Python source on a device that then has to import it is a good way to
    brick a lamp that cannot be recovered over the air.
    """
    global _provision
    try:
        with open(PROVISION_FILE) as f:
            data = ujson.load(f)
        _provision = data if isinstance(data, dict) else {}
    except Exception:
        _provision = {}


def _cfg(name, default):
    """Config values must be read with a fallback: config.py is never
    overwritten, so a lamp already in someone's house will not have keys
    added by a later version."""
    if name in _provision:
        return _provision[name]
    return getattr(config, name, default)


# ── Provisioning from the portal ─────────────────────────────

def _is_hex(value, length):
    if not isinstance(value, str) or len(value) != length:
        return False
    for c in value:
        if c not in "0123456789abcdefABCDEF":
            return False
    return True


def apply_provision(data):
    """Validate and persist settings from the setup portal.

    Returns True if anything was saved. Everything is checked here rather
    than in the browser: the portal is an open access point, so the page
    is not a trustworthy source, and bad TTN keys would leave the lamp
    unable to join with no obvious reason why.
    """
    update = {}

    if "lamp_id" in data:
        try:
            lamp_id = int(data["lamp_id"])
        except (TypeError, ValueError):
            return False
        if not (1 <= lamp_id <= 255):
            return False
        update["LAMP_ID"] = lamp_id

    for field, key, length in (("dev_eui", "LORA_DEV_EUI", 16),
                               ("app_eui", "LORA_APP_EUI", 16),
                               ("app_key", "LORA_APP_KEY", 32)):
        if field in data:
            value = str(data[field]).replace(" ", "")
            if not _is_hex(value, length):
                return False
            update[key] = value.upper()

    ssid = data.get("wifi_ssid")
    if isinstance(ssid, str) and 0 < len(ssid) <= 32:
        password = data.get("wifi_pass")
        password = password if isinstance(password, str) else ""
        if len(password) <= 64:
            update["WIFI_NETWORKS"] = [[ssid, password]]
            update["WIFI_ENABLED"] = True

    if not update:
        return False

    global _provision
    merged = dict(_provision)
    merged.update(update)
    try:
        _write_json(PROVISION_FILE, merged)
    except Exception as e:
        print("[provision] save failed: %s" % e)
        return False
    # Keep the in-memory copy in step, or a second save in the same
    # session would merge against a stale (usually empty) dict and
    # silently drop everything entered before it.
    _provision = merged
    print("[provision] saved: %s" % sorted(update.keys()))
    return True


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

def _find_sx1262():
    """Locate the Wio-SX1262, whichever way it is attached.

    Called from the transport rather than at boot, so a module that was
    not seated at power-on is picked up on the next retry.

    Nothing here has to be configured: the two ways of attaching the
    module are probed in turn. Naming the pins in config.py only becomes
    necessary for a board that is neither.
    """
    from net.sx1262 import open_radio

    named = ("SX_NSS_PIN" in _provision) or hasattr(config, "SX_NSS_PIN")
    preferred = None
    if named:
        preferred = {"sck": _cfg("SX_SCK_PIN", 7),
                     "mosi": _cfg("SX_MOSI_PIN", 9),
                     "miso": _cfg("SX_MISO_PIN", 8),
                     "nss": _cfg("SX_NSS_PIN", 41),
                     "reset": _cfg("SX_RESET_PIN", 42),
                     "busy": _cfg("SX_BUSY_PIN", 40),
                     "dio1": _cfg("SX_DIO1_PIN", 39)}

    # Pins the lamp is already using. Probing means driving them, and
    # driving the LED data line writes garbage down the strip.
    in_use = [_cfg("LED_PIN", 2)] + list(_cfg("TOUCH_PINS", []))

    radio, detail = open_radio(spi_id=_cfg("SX_SPI_ID", 1),
                               preferred=preferred, avoid=in_use)
    if radio is None:
        print("[lora] no SX1262 answered — %s" % detail)
        print("       check the board-to-board connector is seated, then")
        print("       run tools/radio_check.py for a pin-by-pin report")
        return None

    # The probe found the pins with the native driver. Which driver
    # then RUNS the radio is a separate choice: "upstream" (default) is
    # micropython-lib's SX1262 driver, maintained by MicroPython's own
    # maintainers; "native" is this project's register-level one. If
    # the upstream driver cannot come up, fall back rather than dark.
    if str(_cfg("LORA_DRIVER", "upstream")).lower() != "native":
        pins = dict(radio.pins)
        radio.close()
        try:
            from net.sx1262_mplib import UpstreamSX1262
            radio = UpstreamSX1262(spi_id=_cfg("SX_SPI_ID", 1), **pins)
            print("[lora] driver: micropython-lib sx126x")
        except Exception as e:
            print("[lora] upstream driver failed (%s) — using native" % e)
            from net.sx1262 import SX1262
            radio = SX1262(spi_id=_cfg("SX_SPI_ID", 1), **pins)
    return radio


def build_transports(tick=None):
    router = Router()

    if _cfg("LORA_ENABLED", False):
        # Two radios, one interface. The Wio-E5 runs a LoRaWAN stack in
        # its own firmware and speaks AT commands; the SX1262 is a bare
        # radio, so the stack runs here instead. Nothing above this line
        # can tell the difference.
        radio_kind = _cfg("LORA_RADIO", "E5").upper()
        try:
            if radio_kind.startswith("SX"):
                from net.lorawan_abp import LoRaWANABP, _hex
                lora = LoRaWANABP(
                    _find_sx1262,
                    _hex(_cfg("LORA_DEV_ADDR", ""), 4),
                    _hex(_cfg("LORA_NWK_SKEY", ""), 16),
                    _hex(_cfg("LORA_APP_SKEY", ""), 16),
                    port=_cfg("LORA_PORT", 8),
                    sf=_cfg("LORA_SF", 9),
                    tx_power=_cfg("LORA_TX_POWER", 14),
                    min_interval_ms=_cfg("LORA_MIN_INTERVAL_MS",
                                         3 * 60 * 60 * 1000),
                    burst=_cfg("LORA_BURST", 4))
            else:
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
                    min_interval_ms=_cfg("LORA_MIN_INTERVAL_MS",
                                         3 * 60 * 60 * 1000),
                    burst=_cfg("LORA_BURST", 4))
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
                            prefix + "/status/%d" % _cfg("LAMP_ID", 1))
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

    load_provision()                    # portal settings win over config.py

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
                    breathe_depth=_cfg("BREATHE_DEPTH", 0.04),
                    num_groups=_cfg("NUM_GROUPS", 3),
                    group_min_leds=_cfg("GROUP_MIN_LEDS", 1),
                    group_max_leds=_cfg("GROUP_MAX_LEDS", 8),
                    group_spread=_cfg("GROUP_SPREAD", 0.35))
    engine.set_power(on)
    if not on:
        engine._power_level = 0.0      # instant off, no fade-in at boot

    pulser.stop()

    # Local control and provisioning, raised on demand by a 5 s press.
    # Never on by default: an always-up open access point is needless
    # exposure and pointless RF noise.
    restart_at = [None]

    def on_config(data):
        if not apply_provision(data):
            return False
        # Reboot from the main loop, not from here — this runs inside the
        # HTTP handler and resetting now would drop the response, leaving
        # the user staring at a failed save that actually worked.
        restart_at[0] = utime.ticks_add(utime.ticks_ms(), 2_000)
        return True

    name = _cfg("LAMP_NAME", "")
    portal = Portal(
        shared, engine, lamp_id, on_config=on_config,
        password=_cfg("PORTAL_PASSWORD", None),
        always_on=_cfg("PORTAL_ALWAYS_ON", True),
        ssid=_cfg("PORTAL_SSID",
                  ("lamp-%s" % name.lower().replace(" ", "-")) if name
                  else "lamp-%d" % lamp_id))
    if _cfg("PORTAL_ENABLED", True) and _cfg("PORTAL_ALWAYS_ON", True):
        portal.start()

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
    next_retry     = utime.ticks_add(now, 30_000)
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
            except Exception:
                # Deliberately broad. Junk on a public radio medium is
                # normal, and no malformed frame may ever be able to take
                # down a lamp that has no over-the-air recovery.
                continue
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
            # Advance the pulse baseline WITHOUT pulsing: a pulse means
            # "your friend reached for their lamp". Flashing at your own
            # touch would drown the only signal it carries.
            engine.note_arrival(pulse=False)
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
        elif event == "long_hold" and _cfg("PORTAL_ENABLED", True):
            if portal.active:
                portal.stop()
            elif portal.start():
                print("[portal] join WiFi '%s' then open any page" % portal.ssid)

        # ── Local control portal ──
        portal.tick()

        if restart_at[0] is not None and utime.ticks_diff(now, restart_at[0]) >= 0:
            print("[provision] restarting to apply new settings")
            save_state(shared, engine, force=True)
            portal.stop()
            machine.reset()

        # ── Send ──
        # router.ready() is checked FIRST so the frame is only built when
        # something will actually take it. `dirty` stays set until then,
        # and this loop runs ~1000×/s, so building it unconditionally
        # meant a million discarded allocations between two LoRa sends.
        if dirty and router.ready():
            if router.send(current_frame(touched=True)):
                dirty = False

        if utime.ticks_diff(now, next_heartbeat) >= 0:
            # Costs one uplink an hour and means a lamp that missed
            # everything still converges without anyone touching anything.
            if router.ready():
                router.send(current_frame())
            next_heartbeat = utime.ticks_add(now, HEARTBEAT_MS)

        # ── Housekeeping ──
        if utime.ticks_diff(now, next_flush) >= 0:
            save_state(shared, engine)
            next_flush = utime.ticks_add(now, STATE_FLUSH_MS)

        if utime.ticks_diff(now, next_gc) >= 0:
            gc.collect()
            next_gc = utime.ticks_add(now, 60_000)

        # ── Bring dropped links back ──
        # Keep rendering and feeding the watchdog through a reconnect: a
        # LoRaWAN join blocks for up to 90 s and would otherwise freeze
        # the lamp mid-breath and then trip the watchdog.
        if utime.ticks_diff(now, next_retry) >= 0:
            router.service(tick=lambda: (feed(), engine.tick(strip)))
            next_retry = utime.ticks_add(now, 30_000)

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
