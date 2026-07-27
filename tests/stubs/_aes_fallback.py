"""AES-128 ECB encrypt, for tests only.

MicroPython on ESP32 provides this in `cryptolib`; CPython does not ship
AES at all and this project has no dependencies, so the test suite needs
its own. Correctness here is guaranteed by the FIPS-197 vector in
tests/test_lorawan.py, not by trust.
"""
_SBOX = None


def _build():
    global _SBOX
    p = q = 1
    sbox = [0] * 256
    while True:
        # p *= 3 in GF(2^8)
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)
        # q /= 3
        q ^= (q << 1) & 0xFF
        q ^= (q << 2) & 0xFF
        q ^= (q << 4) & 0xFF
        if q & 0x80:
            q ^= 0x09
        x = q ^ ((q << 1) | (q >> 7)) ^ ((q << 2) | (q >> 6)) \
            ^ ((q << 3) | (q >> 5)) ^ ((q << 4) | (q >> 4))
        sbox[p] = (x ^ 0x63) & 0xFF
        if p == 1:
            break
    sbox[0] = 0x63
    _SBOX = sbox


def _xtime(a):
    a <<= 1
    return (a ^ 0x1B) & 0xFF if a & 0x100 else a


def _expand(key):
    if _SBOX is None:
        _build()
    w = [list(key[i * 4:i * 4 + 4]) for i in range(4)]
    rcon = 1
    for i in range(4, 44):
        t = list(w[i - 1])
        if i % 4 == 0:
            t = t[1:] + t[:1]
            t = [_SBOX[b] for b in t]
            t[0] ^= rcon
            rcon = _xtime(rcon)
        w.append([a ^ b for a, b in zip(w[i - 4], t)])
    return w


def encrypt_block(key, block):
    if _SBOX is None:
        _build()
    w = _expand(bytes(key))
    s = [list(bytes(block)[c * 4:c * 4 + 4]) for c in range(4)]

    def add(rnd):
        for c in range(4):
            for r in range(4):
                s[c][r] ^= w[rnd * 4 + c][r]

    add(0)
    for rnd in range(1, 11):
        for c in range(4):
            for r in range(4):
                s[c][r] = _SBOX[s[c][r]]
        rows = [[s[c][r] for c in range(4)] for r in range(4)]
        for r in range(1, 4):
            rows[r] = rows[r][r:] + rows[r][:r]
        for c in range(4):
            for r in range(4):
                s[c][r] = rows[r][c]
        if rnd != 10:
            for c in range(4):
                a = s[c]
                t = a[0] ^ a[1] ^ a[2] ^ a[3]
                a0 = a[0]
                a[0] ^= t ^ _xtime(a[0] ^ a[1])
                a[1] ^= t ^ _xtime(a[1] ^ a[2])
                a[2] ^= t ^ _xtime(a[2] ^ a[3])
                a[3] ^= t ^ _xtime(a[3] ^ a0)
        add(rnd)
    return bytes(s[c][r] for c in range(4) for r in range(4))
