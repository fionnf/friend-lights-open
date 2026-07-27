"""Minimal MicroPython `machine` stub."""
class ResetCalled(BaseException):
    """Reset never returns on hardware, so it must bypass `except Exception`."""
reset_count = [0]
class Pin:
    OUT = 0; IN = 1
    def __init__(self, num, mode=OUT): self.num = num
    def init(self, mode): pass
    def value(self, v=None): return 0
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
