class NeoPixel:
    def __init__(self, pin, n, bpp=3):
        self.n = n; self.bpp = bpp; self.buf = [(0,)*bpp]*n; self.writes = 0
    def __setitem__(self, i, v):
        assert len(v) == self.bpp, "wrong tuple width for bpp=%d" % self.bpp
        assert all(0 <= c <= 255 for c in v), "channel out of range: %r" % (v,)
        self.buf[i] = v
    def __getitem__(self, i): return self.buf[i]
    def write(self): self.writes += 1
