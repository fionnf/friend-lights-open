STA_IF = 0
AP_IF = 1
AUTH_OPEN = 0
AUTH_WPA2_PSK = 3
class WLAN:
    def __init__(self, mode=0):
        self.mode = mode
        self.cfg = {}
        self._active = False
    def active(self, v=None):
        if v is None:
            return self._active
        self._active = v
        return v
    def config(self, **kw):
        self.cfg.update(kw)
    def isconnected(self): return False
    def connect(self, *a): pass
    def disconnect(self): pass
    def ifconfig(self): return ("192.168.4.1",)
