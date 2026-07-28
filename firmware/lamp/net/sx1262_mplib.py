# ============================================================
#  sx1262_mplib.py — the official driver, wearing our interface
# ============================================================
# A facade: micropython-lib's SX1262 driver underneath, this project's
# radio interface on top, so lorawan_abp.py cannot tell which driver it
# is talking to. The native register-level driver (sx1262.py) remains
# as the probe (its cheap register test finds the pins) and as the
# fallback (`LORA_DRIVER = "native"`).
#
# Why prefer the upstream driver once the pins are known: it is written
# and maintained by MicroPython's own maintainers, it validates the
# chip's status on construction, and it carries the pieces that took
# this project a datasheet audit to get right — the TCXO dance, the
# inverted-IQ erratum, image calibration, IRQ hygiene. Fewer lines that
# are ours to be wrong.

from machine import Pin, SPI

# LoRaWAN EU868: explicit header, CR 4/5, public sync word. The driver
# maps a single-byte 0x34 to the two-byte register form (0x3444) itself.
_SYNC_PUBLIC = 0x34


class UpstreamSX1262:

    def __init__(self, spi_id=1, sck=7, mosi=9, miso=8,
                 nss=41, reset=42, busy=40, dio1=39,
                 tcxo_millivolts=1800, tcxo_start_us=5000):
        self.pins = {"sck": sck, "mosi": mosi, "miso": miso, "nss": nss,
                     "reset": reset, "busy": busy, "dio1": dio1}
        from .mp_lora import SX1262 as _Modem
        self._spi = SPI(spi_id, baudrate=2_000_000, polarity=0, phase=0,
                        sck=Pin(sck), mosi=Pin(mosi), miso=Pin(miso))
        # Constructor resets the chip and verifies its status over SPI —
        # it raises on a dead or miswired bus, so a constructed object
        # is already evidence the radio is there.
        self._modem = _Modem(self._spi, cs=Pin(nss), busy=Pin(busy),
                             dio1=Pin(dio1), reset=Pin(reset),
                             dio2_rf_sw=True,
                             dio3_tcxo_millivolts=tcxo_millivolts,
                             dio3_tcxo_start_time_us=tcxo_start_us)

    # ── The interface lorawan_abp.py speaks ─────────────────

    def begin(self, frequency, sf=9, bw=125_000, cr=1, power=14,
              sync_word=None, preamble=8):
        try:
            self._modem.standby()
            self._modem.configure({
                "freq_khz": frequency // 1000,
                "sf": sf,
                "bw": str(bw // 1000),
                "coding_rate": 4 + cr,          # our cr=1 means 4/5
                "output_power": power,
                "preamble_len": preamble,
                "syncword": _SYNC_PUBLIC,
                # LoRaWAN: uplinks standard IQ with CRC, downlinks
                # inverted IQ without. The driver applies the silicon
                # erratum for inverted-IQ receive by itself.
                "invert_iq_tx": False,
                "invert_iq_rx": True,
                # ~2 dB extra sensitivity for ~0.7 mA — free on a
                # mains-powered lamp that listens continuously.
                "rx_boost": True,
            })
            return True
        except Exception as e:
            print("[sx1262-mplib] begin failed: %s" % e)
            return False

    def set_frequency(self, hz):
        self._modem.standby()                   # configure() refuses mid-RX
        self._modem.configure({"freq_khz": int(hz) // 1000})

    def set_modulation(self, sf, bw=125_000, cr=1):
        self._modem.standby()
        self._modem.configure({"sf": sf, "bw": str(int(bw) // 1000),
                               "coding_rate": 4 + cr})

    def send(self, frame):
        # Blocks for the frame's airtime (~a third of a second at SF9).
        # Returns a truthy timestamp on success.
        return bool(self._modem.send(frame))

    def listen(self, frequency, sf):
        """Class C: park on RX2 and stay there."""
        self._modem.standby()
        self._modem.configure({"freq_khz": int(frequency) // 1000, "sf": sf})
        self._modem.start_recv(continuous=True)

    def receive(self):
        """One received payload, or None. Called from the render loop.
        poll_recv() also restarts a receive that a send interrupted —
        which is what keeps Class C listening across our own uplinks."""
        got = self._modem.poll_recv()
        if isinstance(got, (bytes, bytearray)):
            return bytes(got)
        return None

    def sleep(self):
        try:
            self._modem.sleep()
        except Exception:
            pass

    def close(self):
        self.sleep()
        try:
            self._spi.deinit()
        except Exception:
            pass
