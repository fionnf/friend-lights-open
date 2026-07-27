# ============================================================
#  sx1262.py  —  Just enough SX1262 to talk to a LoRaWAN gateway
# ============================================================
# The Wio-E5 has a radio AND an MCU running a LoRaWAN stack. The
# Wio-SX1262 is only the radio, so everything it would have done lives
# in Python now: this file drives the chip, lorawan_crypto.py builds the
# frames, lorawan_abp.py ties them together.
#
# Deliberately minimal. Only what EU868 Class C needs — transmit a LoRa
# packet, and listen continuously. No FSK, no ranging, no sleep modes,
# no CAD. Every extra register write here is one more thing that can be
# wrong on hardware nobody has yet.
#
# ── Wiring ───────────────────────────────────────────────────────────
# The XIAO ESP32S3 + Wio-SX1262 kit joins the two boards with a
# board-to-board connector, NOT the through-hole header, and the two use
# completely different pins. Defaults below are the B2B kit:
#
#   SCK  GPIO7   MOSI GPIO9   MISO GPIO8
#   NSS  GPIO41  RST  GPIO42  BUSY GPIO40  DIO1 GPIO39
#
# If you have the standalone module on the header instead, NSS is GPIO4
# and RST/BUSY/DIO1 move too — set them in config.py.
#
# Corroborated by Seeed's own RadioLib example for this kit:
#     SX1262 radio = new Module(41, 39, 42, 40);
# which is Module(cs, irq, rst, gpio) — NSS 41, DIO1 39, RST 42, BUSY 40.
#
# ── The TCXO ─────────────────────────────────────────────────────────
# This module has no crystal. Its reference is an active TCXO powered
# from the SX1262's own DIO3 pin at 1.8 V, so until DIO3 is told to
# supply that voltage the chip has no clock and does nothing at all: SPI
# answers, registers read back, and every transmission goes nowhere.
# It is the single most likely reason a board like this appears dead.

import utime
from machine import Pin, SPI

# ── Commands (datasheet chapter 13) ──────────────────────────
_SET_SLEEP = 0x84
_SET_STANDBY = 0x80
_SET_TX = 0x83
_SET_RX = 0x82
_SET_RF_FREQUENCY = 0x86
_SET_PACKET_TYPE = 0x8A
_SET_MODULATION_PARAMS = 0x8B
_SET_PACKET_PARAMS = 0x8C
_SET_TX_PARAMS = 0x8E
_SET_BUFFER_BASE = 0x8F
_SET_PA_CONFIG = 0x95
_SET_DIO_IRQ_PARAMS = 0x08
_GET_IRQ_STATUS = 0x12
_CLR_IRQ_STATUS = 0x02
_SET_REGULATOR_MODE = 0x96
_CALIBRATE = 0x89
_WRITE_BUFFER = 0x0E
_READ_BUFFER = 0x1E
_WRITE_REGISTER = 0x0D
_READ_REGISTER = 0x1D
_GET_RX_BUFFER_STATUS = 0x13
_SET_DIO2_AS_RF_SWITCH = 0x9D
_SET_DIO3_AS_TCXO_CTRL = 0x97

_PACKET_TYPE_LORA = 0x01
_STANDBY_RC = 0x00

IRQ_TX_DONE = 0x0001
IRQ_RX_DONE = 0x0002
IRQ_CRC_ERR = 0x0040
IRQ_TIMEOUT = 0x0200

_REG_SYNC_WORD = 0x0740
# 0x3444 is the public network sync word — the one every LoRaWAN gateway
# listens for. 0x1424 is private. Getting this wrong is the classic
# "transmits fine, nothing ever hears it" fault.
SYNC_WORD_PUBLIC = 0x3444


class SX1262:

    def __init__(self, spi=None, *, sck=7, mosi=9, miso=8,
                 nss=41, reset=42, busy=40, dio1=39, spi_id=1,
                 tcxo_voltage=1.8, tcxo_delay_us=5000):
        self._nss = Pin(nss, Pin.OUT, value=1)
        self._reset = Pin(reset, Pin.OUT, value=1)
        self._busy = Pin(busy, Pin.IN)
        self._dio1 = Pin(dio1, Pin.IN)
        self._spi = spi or SPI(spi_id, baudrate=2_000_000, polarity=0,
                               phase=0, sck=Pin(sck), mosi=Pin(mosi),
                               miso=Pin(miso))
        self._rx_active = False
        self._tcxo_voltage = tcxo_voltage
        self._tcxo_delay_us = tcxo_delay_us

    # ── Plumbing ────────────────────────────────────────────

    def _wait(self, timeout_ms=100):
        """BUSY high means the chip is still chewing on the last command.

        Writing during that is ignored silently, which is the sort of
        fault that looks like bad wiring for a whole evening.
        """
        deadline = utime.ticks_add(utime.ticks_ms(), timeout_ms)
        while self._busy.value():
            if utime.ticks_diff(deadline, utime.ticks_ms()) <= 0:
                return False
            utime.sleep_us(100)
        return True

    def _cmd(self, opcode, data=b"", read=0):
        self._wait()
        self._nss.value(0)
        self._spi.write(bytes([opcode]) + bytes(data))
        out = self._spi.read(read) if read else b""
        self._nss.value(1)
        return out

    def _write_register(self, address, values):
        self._cmd(_WRITE_REGISTER,
                  bytes([(address >> 8) & 0xFF, address & 0xFF]) + bytes(values))

    def _write_buffer(self, data):
        self._cmd(_WRITE_BUFFER, b"\x00" + bytes(data))

    def _read_buffer(self, offset, length):
        self._wait()
        self._nss.value(0)
        self._spi.write(bytes([_READ_BUFFER, offset, 0x00]))
        data = self._spi.read(length)
        self._nss.value(1)
        return data

    def irq_status(self):
        raw = self._cmd(_GET_IRQ_STATUS, b"\x00", read=3)
        return (raw[1] << 8) | raw[2] if len(raw) >= 3 else 0

    def clear_irq(self, mask=0xFFFF):
        self._cmd(_CLR_IRQ_STATUS, bytes([(mask >> 8) & 0xFF, mask & 0xFF]))

    # ── Setup ───────────────────────────────────────────────

    def reset(self):
        self._reset.value(0)
        utime.sleep_ms(2)
        self._reset.value(1)
        utime.sleep_ms(20)
        return self._wait(1000)

    def begin(self, frequency=868_100_000, sf=9, bw=125_000, cr=1,
              power=14, preamble=8, sync_word=SYNC_WORD_PUBLIC):
        if not self.reset():
            return False
        self._cmd(_SET_STANDBY, bytes([_STANDBY_RC]))

        # TCXO FIRST. The module has no crystal — its reference clock is
        # a TCXO powered from DIO3 — so nothing else configured before
        # this means anything.
        self._set_tcxo()

        self._cmd(_SET_PACKET_TYPE, bytes([_PACKET_TYPE_LORA]))
        # The module switches its own antenna path from DIO2: high for
        # transmit, low for receive. Without this the chip transmits into
        # a disconnected port and nothing hears it.
        self._cmd(_SET_DIO2_AS_RF_SWITCH, b"\x01")
        self._cmd(_SET_REGULATOR_MODE, b"\x01")        # DC-DC

        # Calibrate AFTER the TCXO is running. Calibrating first tunes
        # the chip against a clock that is not yet there, and the result
        # is a radio that looks configured and transmits nothing usable.
        self._cmd(_CALIBRATE, b"\x7F")
        utime.sleep_ms(5)
        self._wait(1000)

        self.set_frequency(frequency)
        self._set_pa(power)
        self.set_modulation(sf, bw, cr)
        self._cmd(_SET_BUFFER_BASE, b"\x00\x00")
        self._write_register(_REG_SYNC_WORD,
                             bytes([(sync_word >> 8) & 0xFF, sync_word & 0xFF]))
        self._preamble = preamble
        self._sf = sf
        # Everything on DIO1, since that is the only interrupt line wired.
        mask = IRQ_TX_DONE | IRQ_RX_DONE | IRQ_TIMEOUT | IRQ_CRC_ERR
        self._cmd(_SET_DIO_IRQ_PARAMS,
                  bytes([(mask >> 8) & 0xFF, mask & 0xFF,
                         (mask >> 8) & 0xFF, mask & 0xFF,
                         0, 0, 0, 0]))
        self.clear_irq()
        return True

    def _set_tcxo(self):
        """Tell DIO3 to power the TCXO, then wait for it to settle."""
        code = {1.6: 0x00, 1.7: 0x01, 1.8: 0x02, 2.2: 0x03,
                2.4: 0x04, 2.7: 0x05, 3.0: 0x06, 3.3: 0x07}.get(
                    self._tcxo_voltage, 0x02)
        # Timeout is in 15.625 us steps, 24-bit.
        ticks = int(self._tcxo_delay_us / 15.625)
        self._cmd(_SET_DIO3_AS_TCXO_CTRL,
                  bytes([code, (ticks >> 16) & 0xFF,
                         (ticks >> 8) & 0xFF, ticks & 0xFF]))
        utime.sleep_ms(max(1, self._tcxo_delay_us // 1000 + 1))
        self._wait(1000)

    def probe(self):
        """Is the radio actually there and clocked?

        Writes a register and reads it back. SPI that answers with all
        zeros or all ones is wiring; a value that will not stick is
        usually the chip being held in reset or unpowered.
        """
        try:
            if not self.reset():
                return False, "BUSY never went low — check RST and BUSY"
            self._cmd(_SET_STANDBY, bytes([_STANDBY_RC]))
            self._write_register(_REG_SYNC_WORD, b"\x34\x44")
            back = self._read_register(_REG_SYNC_WORD, 2)
            if back == b"\x34\x44":
                return True, "SPI ok, register read-back matches"
            if back in (b"\x00\x00", b"\xff\xff"):
                return False, ("SPI returned %s — check MISO, MOSI, SCK "
                               "and NSS" % back.hex())
            return False, "register read back as %s, expected 3444" % back.hex()
        except Exception as e:
            return False, "SPI failed: %s" % e

    def _read_register(self, address, length):
        self._wait()
        self._nss.value(0)
        self._spi.write(bytes([_READ_REGISTER, (address >> 8) & 0xFF,
                               address & 0xFF, 0x00]))
        data = self._spi.read(length)
        self._nss.value(1)
        return data

    def set_frequency(self, hz):
        # 2^25 / 32 MHz crystal
        raw = int(hz * 33554432 / 32000000)
        self._cmd(_SET_RF_FREQUENCY,
                  bytes([(raw >> 24) & 0xFF, (raw >> 16) & 0xFF,
                         (raw >> 8) & 0xFF, raw & 0xFF]))

    def _set_pa(self, dbm):
        # SX1262 high-power PA, then clamp to the EU868 legal ceiling.
        self._cmd(_SET_PA_CONFIG, b"\x04\x07\x00\x01")
        dbm = max(-9, min(22, int(dbm)))
        self._cmd(_SET_TX_PARAMS, bytes([dbm & 0xFF, 0x04]))   # 200us ramp

    def set_modulation(self, sf, bw, cr):
        bw_code = {7800: 0x00, 10400: 0x08, 15600: 0x01, 20800: 0x09,
                   31250: 0x02, 41700: 0x0A, 62500: 0x03, 125000: 0x04,
                   250000: 0x05, 500000: 0x06}.get(bw, 0x04)
        # Low-data-rate optimise is mandatory when a symbol exceeds 16 ms,
        # which at 125 kHz means SF11 and SF12.
        ldro = 1 if (sf >= 11 and bw <= 125000) else 0
        self._cmd(_SET_MODULATION_PARAMS,
                  bytes([sf, bw_code, cr, ldro]))
        self._sf = sf

    def _set_packet_params(self, length, rx=False):
        # Uplinks are explicit-header with CRC on; downlinks come back
        # with CRC OFF and an inverted IQ, which is what stops a device
        # from hearing other devices' uplinks.
        self._cmd(_SET_PACKET_PARAMS,
                  bytes([(self._preamble >> 8) & 0xFF, self._preamble & 0xFF,
                         0x00,                       # explicit header
                         length & 0xFF,
                         0x00 if rx else 0x01,       # CRC off for downlink
                         0x01 if rx else 0x00]))     # invert IQ for downlink

    # ── Transmit ────────────────────────────────────────────

    def send(self, data, timeout_ms=5000):
        data = bytes(data)
        self._rx_active = False
        self._cmd(_SET_STANDBY, bytes([_STANDBY_RC]))
        self.clear_irq()
        self._set_packet_params(len(data), rx=False)
        self._write_buffer(data)
        self._cmd(_SET_TX, b"\x00\x00\x00")          # no chip timeout
        deadline = utime.ticks_add(utime.ticks_ms(), timeout_ms)
        while utime.ticks_diff(deadline, utime.ticks_ms()) > 0:
            status = self.irq_status()
            if status & IRQ_TX_DONE:
                self.clear_irq()
                return True
            if status & IRQ_TIMEOUT:
                self.clear_irq()
                return False
            utime.sleep_ms(2)
        return False

    # ── Receive (Class C: always listening) ─────────────────

    def listen(self, frequency=869_525_000, sf=9):
        """Park on the RX2 channel and stay there.

        Class C is what makes this whole approach viable in Python: with
        the receiver open continuously there is no window to hit, so a
        garbage collection pause cannot lose a downlink.
        """
        self._cmd(_SET_STANDBY, bytes([_STANDBY_RC]))
        self.set_frequency(frequency)
        self.set_modulation(sf, 125000, 1)
        self._set_packet_params(255, rx=True)
        self.clear_irq()
        self._cmd(_SET_RX, b"\xFF\xFF\xFF")          # continuous
        self._rx_active = True

    def receive(self):
        """A packet if one has arrived, else None. Never blocks."""
        if not self._rx_active:
            return None
        status = self.irq_status()
        if not (status & IRQ_RX_DONE):
            return None
        self.clear_irq()
        if status & IRQ_CRC_ERR:
            return None
        info = self._cmd(_GET_RX_BUFFER_STATUS, b"\x00", read=3)
        if len(info) < 3:
            return None
        length, start = info[1], info[2]
        data = self._read_buffer(start, length)
        # SET_RX with a continuous timeout stays in RX after a packet, so
        # there is nothing to restart here.
        return data

    def sleep(self):
        self._rx_active = False
        self._cmd(_SET_SLEEP, b"\x00")
