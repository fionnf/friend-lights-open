# ============================================================
#  lorawan_e5.py  —  LoRaWAN transport via a Wio-E5 module
# ============================================================
# The Wio-E5 (STM32WLE5) carries a complete LoRaWAN stack in its own
# firmware and is driven by AT commands over UART. That is the whole
# reason it is here rather than a bare SX1262: the OTAA join, the MAC
# layer, the EU868 channel plan and the duty-cycle accounting all happen
# inside the module. MicroPython has no LoRaWAN stack worth betting a
# project on, and this makes that irrelevant.
#
# Wiring (4 wires):
#   XIAO TX  ──► E5 RX
#   XIAO RX  ◄── E5 TX
#   3V3      ──► VCC
#   GND      ──► GND
#
# ── What actually limits how often we may speak ──────────────────────
# Not our own airtime. TTN allows 30 s of uplink airtime per device per
# day and a 10-byte frame at SF9 costs ~0.2 s, so roughly 150 uplinks a
# day are available. That is not the constraint.
#
# The constraint is the FRIEND's allowance. Every uplink the bridge
# forwards becomes a downlink on their lamp, and TTN permits each device
# only TEN downlinks a day. Uplinking more often than that does not send
# more — it just means the surplus is discarded somewhere between here
# and them, having cost us the transmission anyway.
#
# So the send budget is ten a day, split: two heartbeats (main.py) and up
# to eight change-driven sends at the default budget, spent as a token
# bucket rather than a fixed gap — see transport.py.
#
# This is not a limitation to be worked around. A lamp that changes a
# handful of times a day is the product.

import utime

from .transport import Transport

DEFAULT_MIN_INTERVAL_MS = 3 * 60 * 60 * 1000
JOIN_TIMEOUT_MS         = 90_000
AT_TIMEOUT_MS           = 3_000


def _hex(payload):
    """b'\\x0a\\x1b' -> '0A 1B' — the format AT+MSGHEX expects."""
    return " ".join("%02X" % b for b in bytes(payload))


def _unhex(text):
    """'0A 1B' or '0A1B' -> b'\\x0a\\x1b'. Returns None if unparseable."""
    cleaned = text.replace(" ", "").strip()
    if not cleaned or len(cleaned) % 2:
        return None
    try:
        return bytes(int(cleaned[i:i + 2], 16)
                     for i in range(0, len(cleaned), 2))
    except ValueError:
        return None


class LoRaWANE5(Transport):

    name = "lorawan"
    # EU868 gives a device 1% duty cycle per sub-band, and our
    # three uplink channels share one. At ~0.25 s of airtime a
    # frame that is a 25 s gap; 30 s keeps a margin. Nothing else
    # in the stack enforces this, and it is the one limit here
    # that is law rather than etiquette.
    min_gap_ms = 30_000

    def __init__(self, uart, dev_eui, app_eui, app_key,
                 region="EU868", lora_class="C", port=8,
                 min_interval_ms=DEFAULT_MIN_INTERVAL_MS, burst=6):
        Transport.__init__(self)
        self.uart      = uart
        self.dev_eui   = dev_eui
        self.app_eui   = app_eui
        self.app_key   = app_key
        self.region    = region
        # Class C keeps the receiver open continuously, so a downlink
        # arrives when it is sent rather than waiting for our next
        # uplink. It costs power the lamp does not have to care about,
        # because the lamp is plugged into a wall.
        self.lora_class = lora_class
        self.port       = port
        self.min_interval_ms = min_interval_ms
        self.burst = burst
        self._rx = []
        self._buf = b""

    # ── AT plumbing ─────────────────────────────────────────

    def _write(self, cmd):
        self.uart.write(cmd + "\r\n")

    def _drain(self):
        """Read whatever is waiting, split into lines, harvest downlinks.

        Never blocks. Downlinks can arrive at any moment in Class C, so
        every read is scanned for them, not just the ones that follow a
        command we sent.
        """
        try:
            waiting = self.uart.any()
        except Exception:
            return []
        if waiting:
            try:
                chunk = self.uart.read(waiting)
            except Exception:
                chunk = None
            if chunk:
                self._buf += chunk

        lines = []
        while b"\n" in self._buf:
            raw, self._buf = self._buf.split(b"\n", 1)
            line = raw.decode("utf-8", "ignore").strip()
            if line:
                lines.append(line)
                self._harvest(line)
        # A runaway buffer would eventually exhaust the heap on a board
        # that runs for months; the module never sends a single line
        # anywhere near this long.
        if len(self._buf) > 512:
            self._buf = self._buf[-256:]
        return lines

    def _harvest(self, line):
        """Pull a payload out of a downlink notification, if this is one.

        The module reports these as:
            +MSGHEX: PORT: 8; RX: "0A 1B 2C"
        """
        if "RX:" not in line:
            return
        try:
            after = line.split("RX:", 1)[1]
            start = after.index('"') + 1
            end   = after.index('"', start)
        except (ValueError, IndexError):
            return
        data = _unhex(after[start:end])
        if data:
            self._rx.append(data)

    def _expect(self, needle, timeout_ms, tick=None):
        """Wait for a line containing `needle`. Returns True if seen.

        `tick` is called while waiting so the caller can keep rendering
        and feed the watchdog — a 90 s join must not freeze the lamp.
        """
        deadline = utime.ticks_add(utime.ticks_ms(), timeout_ms)
        while utime.ticks_diff(deadline, utime.ticks_ms()) > 0:
            for line in self._drain():
                if needle in line:
                    return True
                if "ERROR" in line:
                    print("[lorawan] %s" % line)
                    return False
            if tick:
                tick()
            utime.sleep_ms(20)
        return False

    def _cmd(self, cmd, needle="+", timeout_ms=AT_TIMEOUT_MS, tick=None):
        self._write(cmd)
        return self._expect(needle, timeout_ms, tick)

    # ── Lifecycle ───────────────────────────────────────────

    def start(self, tick=None):
        """Configure and join. Blocking, but calls `tick` throughout.

        Returns True on a successful join. A failure is not fatal: the
        lamp runs standalone and start() can simply be called again
        later.
        """
        self.connected = False
        try:
            self._drain()

            if not self._cmd("AT", "+AT", 2000, tick):
                print("[lorawan] no response — check wiring and baud rate")
                return False

            self._cmd('AT+ID=DevEui,"%s"' % self.dev_eui, "+ID", 2000, tick)
            self._cmd('AT+ID=AppEui,"%s"' % self.app_eui, "+ID", 2000, tick)
            self._cmd('AT+KEY=APPKEY,"%s"' % self.app_key, "+KEY", 2000, tick)
            self._cmd("AT+DR=%s" % self.region, "+DR", 2000, tick)
            self._cmd("AT+MODE=LWOTAA", "+MODE", 2000, tick)
            self._cmd("AT+CLASS=%s" % self.lora_class, "+CLASS", 2000, tick)
            # Let the module enforce the ETSI duty cycle for us. Doing it
            # here rather than in our own send throttle means a bug in
            # our throttle cannot make the lamp transmit illegally.
            self._cmd("AT+LW=DC,ON", "+LW", 2000, tick)

            print("[lorawan] joining...")
            self._write("AT+JOIN")
            if self._expect("Network joined", JOIN_TIMEOUT_MS, tick):
                self.connected = True
                print("[lorawan] joined")
                return True
            print("[lorawan] join failed — no gateway in range?")
            return False
        except Exception as e:
            print("[lorawan] start failed: %s" % e)
            return False

    def stop(self):
        self.connected = False

    # ── Data ────────────────────────────────────────────────

    def poll(self):
        self._drain()
        if not self._rx:
            return []
        got, self._rx = self._rx, []
        return got

    def _send(self, payload):
        self._write("AT+PORT=%d" % self.port)
        self._drain()
        # Unconfirmed: a confirmed uplink asks the network for an ACK,
        # and every ACK is a downlink billed against the ten-per-day
        # allowance. The CRDT does not need delivery guarantees — the
        # next uplink repairs whatever this one lost — so paying for
        # acknowledgement would buy nothing and cost the budget.
        self._write('AT+MSGHEX="%s"' % _hex(payload))
