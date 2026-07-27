class MQTTClient:
    def __init__(self, *a, **kw): self.published = []
    def connect(self): raise OSError("no broker in tests")
    def set_callback(self, cb): pass
    def subscribe(self, t): pass
    def publish(self, t, m, retain=False): self.published.append((t, m))
    def check_msg(self): pass
    def disconnect(self): pass
