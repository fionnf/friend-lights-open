"""Sockets that never block and never connect — the portal tests only
exercise parsing and routing, never the network."""
AF_INET = 2
SOCK_STREAM = 1
SOCK_DGRAM = 2
SOL_SOCKET = 1
SO_REUSEADDR = 2
class socket:
    def __init__(self, *a): self.sent = []
    def setsockopt(self, *a): pass
    def setblocking(self, v): pass
    def bind(self, a): pass
    def listen(self, n): pass
    def accept(self): raise OSError("EAGAIN")
    def recv(self, n): raise OSError("EAGAIN")
    def recvfrom(self, n): raise OSError("EAGAIN")
    def sendto(self, d, a): pass
    def send(self, d): self.sent.append(d)
    def close(self): pass
