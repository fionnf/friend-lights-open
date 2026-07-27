STA_IF = 0
class WLAN:
    def __init__(self, mode=0): pass
    def active(self, v=None): return True
    def isconnected(self): return False
    def connect(self, *a): pass
    def disconnect(self): pass
    def ifconfig(self): return ("192.0.2.1",)
