# ============================================================
#  lorawan_crypto.py  —  LoRaWAN 1.0.x framing, on a bare radio
# ============================================================
# The Wio-E5 hides all of this inside its own firmware. With a bare
# SX1262 the host has to do it, so here it is.
#
# Only what ABP Class C needs: build an unconfirmed uplink, parse an
# unconfirmed downlink. No join, no MAC command handling, no ADR.
#
# ── Why ABP rather than OTAA ─────────────────────────────────────────
# An OTAA join means catching the join-accept in a receive window that
# opens 5 s after transmitting and lasts milliseconds. MicroPython's
# garbage collector can pause straight through it. ABP has no join at
# all, and Class C leaves the receiver open continuously, so nothing
# here is timing-critical. That is the whole reason this is feasible in
# Python rather than C.
#
# The cost is frame counters: they must never repeat, or the network
# drops everything as a replay. See lorawan_abp.py for how they are
# persisted.
#
# Everything below is checked against published test vectors in
# tests/test_lorawan.py — RFC 4493 for AES-CMAC, and a LoRaWAN frame
# built and parsed back. That matters more here than anywhere else in
# the project, because a radio bug cannot be diagnosed from the sofa.

try:
    from cryptolib import aes
except ImportError:                      # older MicroPython
    try:
        from ucryptolib import aes
    except ImportError:                  # CPython, for the tests
        aes = None

MODE_ECB = 1

# Message types in the MAC header.
MHDR_UNCONFIRMED_UP = 0x40
MHDR_UNCONFIRMED_DOWN = 0x60
MHDR_CONFIRMED_DOWN = 0xA0

DIR_UP = 0
DIR_DOWN = 1

_ZERO16 = b"\x00" * 16


def _ecb(key, block):
    """One AES-128 ECB block. The only primitive LoRaWAN actually needs."""
    if aes is not None:
        return aes(key, MODE_ECB).encrypt(block)
    from _aes_fallback import encrypt_block      # tests only
    return encrypt_block(key, block)


def _shift_left(data):
    """One-bit left shift of a 16-byte block, for CMAC subkeys."""
    out = bytearray(16)
    carry = 0
    for i in range(15, -1, -1):
        value = (data[i] << 1) | carry
        out[i] = value & 0xFF
        carry = (value >> 8) & 1
    return bytes(out)


def cmac(key, message):
    """AES-CMAC (RFC 4493). Returns 16 bytes.

    LoRaWAN's message integrity code is the first four bytes of this.
    """
    const_rb = 0x87

    # Subkeys
    l = _ecb(key, _ZERO16)
    k1 = _shift_left(l)
    if l[0] & 0x80:
        k1 = bytes(k1[:15]) + bytes([k1[15] ^ const_rb])
    k2 = _shift_left(k1)
    if k1[0] & 0x80:
        k2 = bytes(k2[:15]) + bytes([k2[15] ^ const_rb])

    message = bytes(message)
    n = (len(message) + 15) // 16
    complete = n > 0 and len(message) % 16 == 0
    if n == 0:
        n = 1
        complete = False

    if complete:
        last = bytes(x ^ y for x, y in zip(message[(n - 1) * 16:], k1))
    else:
        tail = message[(n - 1) * 16:]
        padded = tail + b"\x80" + b"\x00" * (15 - len(tail))
        last = bytes(x ^ y for x, y in zip(padded, k2))

    x = _ZERO16
    for i in range(n - 1):
        block = message[i * 16:(i + 1) * 16]
        x = _ecb(key, bytes(a ^ b for a, b in zip(x, block)))
    return _ecb(key, bytes(a ^ b for a, b in zip(x, last)))


def _b0(direction, dev_addr, fcnt, length):
    """The pseudo-header the MIC is computed over."""
    return (b"\x49\x00\x00\x00\x00"
            + bytes([direction])
            + dev_addr                      # little-endian, 4 bytes
            + bytes([fcnt & 0xFF, (fcnt >> 8) & 0xFF,
                     (fcnt >> 16) & 0xFF, (fcnt >> 24) & 0xFF])
            + b"\x00"
            + bytes([length]))


def mic(nwk_skey, direction, dev_addr, fcnt, msg):
    """The 4-byte message integrity code for a frame."""
    return cmac(nwk_skey, _b0(direction, dev_addr, fcnt, len(msg)) + msg)[:4]


def encrypt_payload(key, direction, dev_addr, fcnt, payload):
    """LoRaWAN payload encryption — its own AES-CTR variant.

    Symmetric: the same call decrypts, which is why downlinks reuse it.
    """
    payload = bytes(payload)
    out = bytearray()
    blocks = (len(payload) + 15) // 16
    for i in range(1, blocks + 1):
        a = (b"\x01\x00\x00\x00\x00"
             + bytes([direction])
             + dev_addr
             + bytes([fcnt & 0xFF, (fcnt >> 8) & 0xFF,
                      (fcnt >> 16) & 0xFF, (fcnt >> 24) & 0xFF])
             + b"\x00"
             + bytes([i]))
        s = _ecb(key, a)
        chunk = payload[(i - 1) * 16:i * 16]
        out.extend(x ^ y for x, y in zip(chunk, s))
    return bytes(out)


def build_uplink(dev_addr, nwk_skey, app_skey, fcnt, port, payload,
                 adr=False):
    """A complete unconfirmed data-up PHYPayload, ready to transmit.

    dev_addr is 4 bytes LITTLE-ENDIAN — i.e. the console's "260BXXXX"
    reversed. Getting that backwards produces a frame the network simply
    ignores, with nothing in the console to say why, so lorawan_abp.py
    does the reversing in one place.
    """
    fctrl = 0x80 if adr else 0x00
    fhdr = (dev_addr
            + bytes([fctrl])
            + bytes([fcnt & 0xFF, (fcnt >> 8) & 0xFF]))
    enc = encrypt_payload(app_skey if port else nwk_skey,
                          DIR_UP, dev_addr, fcnt, payload)
    mac_payload = fhdr + bytes([port]) + enc
    msg = bytes([MHDR_UNCONFIRMED_UP]) + mac_payload
    return msg + mic(nwk_skey, DIR_UP, dev_addr, fcnt, msg)


def parse_downlink(dev_addr, nwk_skey, app_skey, frame):
    """Decode a downlink addressed to us.

    Returns {"port", "payload", "fcnt"} or None. None covers every
    reason to ignore a frame — wrong address, bad MIC, not a downlink,
    truncated — because on a shared radio band those are all normal
    traffic rather than errors worth reporting.
    """
    frame = bytes(frame)
    if len(frame) < 12:                       # MHDR + FHDR + MIC minimum
        return None
    mhdr = frame[0]
    if mhdr not in (MHDR_UNCONFIRMED_DOWN, MHDR_CONFIRMED_DOWN):
        return None
    if frame[1:5] != dev_addr:
        return None                           # somebody else's device

    fctrl = frame[5]
    fopts_len = fctrl & 0x0F
    fcnt = frame[6] | (frame[7] << 8)

    body, received_mic = frame[:-4], frame[-4:]
    if mic(nwk_skey, DIR_DOWN, dev_addr, fcnt, body) != received_mic:
        return None                           # not ours, or corrupted

    index = 8 + fopts_len
    if index >= len(body):
        return {"port": None, "payload": b"", "fcnt": fcnt}   # MAC only
    port = body[index]
    enc = body[index + 1:]
    key = app_skey if port else nwk_skey
    return {"port": port,
            "payload": encrypt_payload(key, DIR_DOWN, dev_addr, fcnt, enc),
            "fcnt": fcnt}
