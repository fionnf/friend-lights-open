"""Sockets that never block and never reach a network.

The portal tests exercise parsing and routing; the UDP transport tests
exercise framing and error handling. Neither wants a real network, so
this records what was sent and serves what a test puts in `inbox`.
"""
AF_INET = 2
SOCK_STREAM = 1
SOCK_DGRAM = 2
SOL_SOCKET = 1
SO_REUSEADDR = 2
SO_BROADCAST = 32


class socket:
    def __init__(self, *a):
        self.sent = []          # [(data, addr)] for sendto, data for send
        self.inbox = []         # [(data, addr)] a test wants delivered
        self.closed = False

    def setsockopt(self, *a): pass
    def setblocking(self, v): pass
    def bind(self, a): pass
    def listen(self, n): pass
    def accept(self): raise OSError("EAGAIN")
    def recv(self, n): raise OSError("EAGAIN")

    def recvfrom(self, n):
        # EAGAIN is how a non-blocking socket says "nothing waiting",
        # and the transport must treat that as normal rather than as a
        # fault — it is called from the render loop many times a second.
        if not self.inbox:
            raise OSError("EAGAIN")
        return self.inbox.pop(0)

    def sendto(self, d, a):
        self.sent.append((bytes(d), a))

    def send(self, d):
        self.sent.append(d)

    def close(self):
        self.closed = True
