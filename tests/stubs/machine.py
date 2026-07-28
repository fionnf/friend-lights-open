"""Minimal MicroPython `machine` stub."""
class ResetCalled(BaseException):
    """Reset never returns on hardware, so it must bypass `except Exception`."""
reset_count = [0]
class Pin:
    OUT = 0; IN = 1
    def __init__(self, num, mode=OUT, value=None):
        self.num = num; self.mode = mode; self._v = value or 0
    def init(self, mode): self.mode = mode
    def value(self, v=None):
        if v is None:
            # BUSY is read to decide whether the radio is still chewing.
            # Always low: the stub chip is never busy.
            return 0
        self._v = v
class SPI:
    """Enough of a bus to construct a driver. Reads return zeros, which
    is what a real bus with nothing on the other end also does — so a
    driver probed against this stub correctly reports 'not there'."""
    def __init__(self, id=0, baudrate=0, polarity=0, phase=0,
                 sck=None, mosi=None, miso=None):
        self.id = id; self.written = []; self.deinit_count = 0
    def write(self, data): self.written.append(bytes(data))
    def read(self, n, write=0): return bytes(n)
    def deinit(self): self.deinit_count += 1
class WDT:
    def __init__(self, timeout=0): self.timeout = timeout; self.feeds = 0
    def feed(self): self.feeds += 1
class TouchPad:
    def __init__(self, pin): self.pin = pin
    def read(self): return 1000            # steady, untouched
class UART:
    """Echoes the AT responses the Wio-E5 would give, so start() joins."""
    def __init__(self, *a, **kw): self._out = b""; self.written = []
    def write(self, s):
        self.written.append(s)
        cmd = s.strip()
        if cmd == "AT": self._out += b"+AT: OK\r\n"
        elif cmd == "AT+JOIN": self._out += b"+JOIN: Network joined\r\n"
        elif cmd.startswith("AT+"): self._out += b"+" + cmd[3:].split("=")[0].encode() + b": OK\r\n"
    def any(self): return len(self._out)
    def read(self, n=None):
        data, self._out = self._out, b""
        return data or None
def unique_id(): return b"\xde\xad\xbe\xef"
def reset():
    reset_count[0] += 1
    raise ResetCalled()
