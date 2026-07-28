# ============================================================
#  lorawan_abp.py  —  TTN over a bare SX1262
# ============================================================
# The same transport interface as lorawan_e5.py, so nothing above it
# changes: the CRDT, the codec, the engine and the router cannot tell
# which radio is underneath.
#
# ── Frame counters are the thing to get right ────────────────────────
# ABP has no join, so the network has no way to reset its idea of where
# we are in the sequence. It simply drops any uplink whose counter it
# has already seen. That makes the counter the one piece of state that
# absolutely must survive a power cut, and the one bug that presents as
# "everything looks perfect and the console shows nothing".
#
# So it is persisted BEFORE the frame goes out, not after, and in
# batches: writing every single frame would wear the flash, and writing
# afterwards would replay the counter if power failed mid-transmission.
# We reserve a block of counters, then spend them.

import utime

try:
    import ujson as json
except ImportError:
    import json

from .transport import Transport
from . import lorawan_crypto as lw

# Reserve this many counters per flash write. A power cut costs us the
# unused ones — which is harmless, since the network only cares that the
# counter never goes BACKWARDS.
COUNTER_BATCH = 20
COUNTER_FILE = "lorawan_fcnt.json"

# EU868. Uplinks rotate across the three mandatory join channels so no
# single one carries everything; RX2 is fixed by the network.
EU868_UPLINK_CHANNELS = (868_100_000, 868_300_000, 868_500_000)
EU868_RX2_FREQUENCY = 869_525_000
# TTN sets RX2 to SF9. It is on the frequency plan you picked in the
# console — "Europe 863-870 MHz (SF9 for RX2)".
EU868_RX2_SF = 9

DEFAULT_MIN_INTERVAL_MS = 3 * 60 * 60 * 1000


def _hex(value, length):
    """Parse a hex string, or return None. Never raises on junk config."""
    if not isinstance(value, str):
        return None
    cleaned = value.replace(" ", "").replace("0x", "")
    if len(cleaned) != length * 2:
        return None
    try:
        return bytes(int(cleaned[i:i + 2], 16)
                     for i in range(0, len(cleaned), 2))
    except ValueError:
        return None


class LoRaWANABP(Transport):

    name = "lorawan"

    def __init__(self, radio, dev_addr, nwk_skey, app_skey,
                 port=8, sf=9, tx_power=14,
                 min_interval_ms=DEFAULT_MIN_INTERVAL_MS, burst=6,
                 channels=EU868_UPLINK_CHANNELS,
                 rx2_frequency=EU868_RX2_FREQUENCY, rx2_sf=EU868_RX2_SF):
        Transport.__init__(self)
        # `radio` may be a driver, or a callable that goes and finds one.
        # The callable form matters: opening the radio inside start()
        # rather than here means a lamp that boots with the module not
        # seated — or browns out mid-probe — is retried by
        # Router.service() instead of staying dark until someone
        # power-cycles it.
        self._find_radio = radio if callable(radio) else None
        self.radio = None if self._find_radio else radio
        # The console shows DevAddr big-endian; the air format is little-
        # endian. Reversing it here, once, is why nothing else has to
        # think about it — and getting it wrong produces a frame the
        # network ignores with no error anywhere.
        self.dev_addr = bytes(reversed(dev_addr)) if dev_addr else None
        self.nwk_skey = nwk_skey
        self.app_skey = app_skey
        self.port = port
        self.sf = sf
        self.tx_power = tx_power
        self.min_interval_ms = min_interval_ms
        self.burst = burst
        self.channels = tuple(channels)
        self.rx2_frequency = rx2_frequency
        self.rx2_sf = rx2_sf

        self._channel = 0
        self._fcnt_up = 0
        self._reserved_until = 0
        self._last_down_fcnt = None
        self._rx = []

    # ── Frame counter ───────────────────────────────────────

    def _load_counter(self):
        try:
            with open(COUNTER_FILE) as f:
                data = json.load(f)
            # Resume from the end of the last reserved block, never the
            # last one used: anything inside that block may already have
            # been transmitted before the power went out.
            self._fcnt_up = int(data.get("reserved", 0))
        except Exception:
            self._fcnt_up = 0
        self._reserved_until = self._fcnt_up

    def _reserve(self):
        """Claim the next block of counters and persist it before use."""
        self._reserved_until = self._fcnt_up + COUNTER_BATCH
        tmp = COUNTER_FILE + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump({"reserved": self._reserved_until}, f)
            import os
            os.rename(tmp, COUNTER_FILE)
        except Exception as e:
            print("[lorawan] could not persist frame counter: %s" % e)
            # Carry on rather than go silent — a lamp that transmits and
            # might be ignored is better than one that never tries.

    def _next_fcnt(self):
        if self._fcnt_up >= self._reserved_until:
            self._reserve()
        value = self._fcnt_up
        self._fcnt_up += 1
        return value

    def reset_counter(self):
        """After resetting the frame counter in the TTN console."""
        self._fcnt_up = 0
        self._reserved_until = 0
        try:
            import os
            os.remove(COUNTER_FILE)
        except OSError:
            pass

    # ── Lifecycle ───────────────────────────────────────────

    def start(self, tick=None):
        self.connected = False
        if not (self.dev_addr and self.nwk_skey and self.app_skey):
            print("[lorawan] no ABP keys — put LORA_DEV_ADDR, LORA_NWK_SKEY")
            print("          and LORA_APP_SKEY in config.py, from the TTN")
            print("          console with Activation mode = ABP")
            return False
        if self.radio is None:
            try:
                self.radio = self._find_radio()
            except Exception as e:
                print("[lorawan] looking for the radio failed: %s" % e)
                return False
            if self.radio is None:
                return False            # already explained by the finder
        try:
            if not self.radio.begin(frequency=self.channels[0], sf=self.sf,
                                    power=self.tx_power):
                print("[lorawan] radio did not respond — check SPI wiring")
                return False
            self._load_counter()
            # Class C: park on RX2 and stay there, so a downlink can
            # arrive at any moment rather than only after we transmit.
            self.radio.listen(self.rx2_frequency, self.rx2_sf)
            self.connected = True
            print("[lorawan] radio up, listening on %.3f MHz SF%d, fcnt %d"
                  % (self.rx2_frequency / 1e6, self.rx2_sf, self._fcnt_up))
            return True
        except Exception as e:
            print("[lorawan] start failed: %s" % e)
            return False

    def stop(self):
        self.connected = False
        try:
            self.radio.sleep()
        except Exception:
            pass

    # ── Data ────────────────────────────────────────────────

    def poll(self):
        if not self.connected:
            return []
        try:
            raw = self.radio.receive()
        except Exception as e:
            print("[lorawan] receive failed: %s" % e)
            self.connected = False
            return []
        if not raw:
            return []

        frame = lw.parse_downlink(self.dev_addr, self.nwk_skey,
                                  self.app_skey, raw)
        if not frame or not frame.get("payload"):
            return []                       # someone else's, or MAC only
        # The network resends a downlink it thinks we missed. Applying it
        # twice would be harmless — the CRDT is idempotent — but dropping
        # it keeps the logs honest about what actually arrived.
        if frame["fcnt"] == self._last_down_fcnt:
            return []
        self._last_down_fcnt = frame["fcnt"]
        return [frame["payload"]]

    def _send(self, payload):
        fcnt = self._next_fcnt()
        frame = lw.build_uplink(self.dev_addr, self.nwk_skey, self.app_skey,
                                fcnt, self.port, payload)
        # Spread across the three mandatory channels, so one is not
        # carrying every transmission.
        channel = self.channels[self._channel % len(self.channels)]
        self._channel += 1

        self.radio.set_frequency(channel)
        self.radio.set_modulation(self.sf, 125000, 1)
        ok = self.radio.send(frame)
        # Back to listening whatever happened: in Class C the receiver
        # must not be left closed, or downlinks stop arriving silently.
        self.radio.listen(self.rx2_frequency, self.rx2_sf)
        if not ok:
            raise OSError("transmit timed out")
        print("[lorawan] sent fcnt %d on %.1f MHz" % (fcnt, channel / 1e6))
