#!/usr/bin/env python3
"""
Setup portal tests.

The portal raises an OPEN access point and parses HTTP from whatever
connects to it. Two things therefore matter more than the features:

  1. It must never block. The render loop feeds an 8 s watchdog, so a
     socket call that waits would reboot the lamp mid-breath.
  2. It must never leak a socket. A phone reconnecting in someone's
     pocket all afternoon would otherwise exhaust the heap.

Run from the repo root:   python3 tests/test_portal.py
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "stubs"))
sys.path.insert(0, os.path.join(ROOT, "firmware", "lamp"))
sys.path.insert(0, os.path.join(ROOT, "firmware"))

import ujson
from shared_state import SharedColour
from portal import Portal, PROBE_PATHS, AP_IP

failures = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name +
          (("  " + str(detail)) if detail and not cond else ""))
    if not cond:
        failures.append(name)


class FakeConn:
    """Captures what the portal writes, and whether it closed."""

    def __init__(self):
        self.out = b""
        self.closed = False

    def send(self, data):
        self.out += data if isinstance(data, bytes) else data.encode()

    def close(self):
        self.closed = True

    # Response helpers
    def status(self):
        return int(self.out.split(b" ", 2)[1])

    def body(self):
        return self.out.split(b"\r\n\r\n", 1)[1] if b"\r\n\r\n" in self.out else b""

    def json(self):
        return ujson.loads(self.body())

    def header(self, name):
        for line in self.out.split(b"\r\n"):
            if line.lower().startswith(name.lower().encode() + b":"):
                return line.split(b":", 1)[1].strip().decode()
        return None


class FakeEngine:
    def __init__(self):
        self.brightness = 0.6
        self.is_on = True
        self.arrivals = 0

    def set_brightness(self, v):
        self.brightness = max(0.0, min(1.0, float(v)))

    def set_power(self, on):
        self.is_on = bool(on)

    def note_arrival(self):
        self.arrivals += 1


def make(on_config=None):
    shared = SharedColour(1)
    engine = FakeEngine()
    page = os.path.join(ROOT, "firmware", "lamp", "www", "index.html")
    return Portal(shared, engine, 1, on_config=on_config, page=page), shared, engine


def request(portal, raw):
    conn = FakeConn()
    portal._respond(conn, raw if isinstance(raw, bytes) else raw.encode())
    return conn


def post(path, obj):
    body = ujson.dumps(obj)
    return ("POST %s HTTP/1.1\r\nContent-Length: %d\r\n\r\n%s"
            % (path, len(body), body))


# ── Request framing ──────────────────────────────────────────
# A phone can split a request across packets. Acting on half of one would
# mean a truncated JSON body silently parsed as something else.
print("\nrequest framing")

p, _, _ = make()
check("incomplete headers are not acted on",
      p._complete(b"GET / HTTP/1.1\r\nHost: x") is False)
check("headers with no body are complete",
      p._complete(b"GET / HTTP/1.1\r\n\r\n") is True)
check("body still arriving is not complete",
      p._complete(b"POST /set HTTP/1.1\r\nContent-Length: 20\r\n\r\n{\"on\"") is False)
check("full body is complete",
      p._complete(b'POST /set HTTP/1.1\r\nContent-Length: 11\r\n\r\n{"on":true}') is True)
check("case-insensitive Content-Length",
      p._complete(b'POST /s HTTP/1.1\r\ncontent-length: 2\r\n\r\n{}') is True)
check("junk Content-Length does not hang the connection",
      p._complete(b'POST /s HTTP/1.1\r\nContent-Length: abc\r\n\r\n') is True)


# ── Captive portal ───────────────────────────────────────────
# Without these redirects the phone joins the network, decides it has no
# internet, and silently drops back to mobile data.
print("\ncaptive portal")

for probe in ("/generate_204", "/hotspot-detect.html", "/ncsi.txt"):
    conn = request(p, "GET %s HTTP/1.1\r\n\r\n" % probe)
    ok = conn.status() == 302 and AP_IP in (conn.header("Location") or "")
    check("redirects %s" % probe, ok, conn.out[:60])

check("every known probe path is covered", len(PROBE_PATHS) >= 6)


# ── State ────────────────────────────────────────────────────
print("\nstate")

p, shared, engine = make()
state = request(p, "GET /state HTTP/1.1\r\n\r\n").json()
check("reports lamp id", state["lamp_id"] == 1)
check("reports hue", state["hue"] == 0.0, state["hue"])
check("reports power", state["on"] is True)


# ── Control ──────────────────────────────────────────────────
print("\ncontrol")

conn = request(p, post("/touch", {}))
check("touch moves the hue", shared.hue() > 0, shared.hue())
check("touch is counted", shared.total_touches() == 1)
check("touch pulses the lamp", engine.arrivals == 1)

request(p, post("/set", {"brightness": 0.25}))
check("brightness applied", abs(engine.brightness - 0.25) < 1e-9, engine.brightness)

request(p, post("/set", {"on": False}))
check("power applied", engine.is_on is False)

request(p, post("/set", {"brightness": 99}))
check("out-of-range brightness clamps", engine.brightness == 1.0, engine.brightness)

request(p, post("/set", {"brightness": "banana"}))
check("junk brightness is ignored, not fatal", engine.brightness == 1.0)


# ── Bad input ────────────────────────────────────────────────
# The AP is open, so anything on the network can send anything at all.
print("\nbad input")

conn = request(p, "POST /set HTTP/1.1\r\nContent-Length: 5\r\n\r\n{{{{{")
check("malformed json rejected with 400", conn.status() == 400, conn.status())

conn = request(p, post("/set", ["not", "an", "object"]))
check("json array rejected", conn.status() == 400, conn.status())

conn = request(p, "GET /../../secrets HTTP/1.1\r\n\r\n")
check("unknown path 404s", conn.status() == 404, conn.status())

conn = request(p, "\r\n\r\n")
check("empty request line does not raise", conn.out == b"")

conn = request(p, "GET /state?cache=1 HTTP/1.1\r\n\r\n")
check("query string is stripped", conn.status() == 200)


# ── Provisioning ─────────────────────────────────────────────
print("\nprovisioning")

seen = []
p, _, _ = make(on_config=lambda d: (seen.append(d), True)[1])
conn = request(p, post("/config", {"dev_eui": "0011223344556677"}))
check("config reaches the handler", len(seen) == 1)
check("config reports saved", conn.json()["saved"] is True)

p2, _, _ = make(on_config=lambda d: False)
conn = request(p2, post("/config", {"dev_eui": "nope"}))
check("rejected config reports not saved", conn.json()["saved"] is False)


# ── Page ─────────────────────────────────────────────────────
print("\npage")

conn = request(p, "GET / HTTP/1.1\r\n\r\n")
check("serves the page", conn.status() == 200, conn.status())
html = conn.body()
check("page is non-trivial", len(html) > 2000, len(html))
check("declares its length", conn.header("Content-Length") == str(len(html)))

# The phone has NO internet on this AP, so any external reference would
# hang the page load behind a DNS timeout.
text = html.decode()
for needle in ("http://", "https://", "//cdn", "<link"):
    check("no external reference: %s" % needle, needle not in text)


# ── Validation (main.apply_provision) ────────────────────────
# Checked on the lamp, not in the browser: the portal is an open network
# and the page is not a trustworthy source.
print("\nkey validation")

import tempfile
os.chdir(tempfile.mkdtemp(prefix="portal-"))
import main as fw
fw.load_provision()

check("rejects short DevEUI", fw.apply_provision({"dev_eui": "00112233"}) is False)
check("rejects non-hex AppKey",
      fw.apply_provision({"app_key": "Z" * 32}) is False)
check("rejects lamp_id 0", fw.apply_provision({"lamp_id": 0}) is False)
check("rejects lamp_id 256", fw.apply_provision({"lamp_id": 256}) is False)
check("rejects empty config", fw.apply_provision({}) is False)
check("accepts a valid DevEUI",
      fw.apply_provision({"dev_eui": "00112233aabbccdd"}) is True)
check("normalises hex to upper case",
      fw._provision.get("LORA_DEV_EUI") == "00112233AABBCCDD"
      or ujson.load(open("provision.json"))["LORA_DEV_EUI"] == "00112233AABBCCDD")

fw.apply_provision({"lamp_id": 7})
saved = ujson.load(open("provision.json"))
check("merges rather than overwriting", saved.get("LORA_DEV_EUI") is not None)
check("stores lamp id", saved.get("LAMP_ID") == 7, saved.get("LAMP_ID"))

fw.load_provision()
check("provisioned value overrides config.py", fw._cfg("LAMP_ID", 1) == 7)
check("unprovisioned value still falls through",
      fw._cfg("NUM_LEDS", 99) == 10, fw._cfg("NUM_LEDS", 99))

fw.apply_provision({"wifi_ssid": "home", "wifi_pass": "hunter2"})
saved = ujson.load(open("provision.json"))
check("wifi saved", saved["WIFI_NETWORKS"] == [["home", "hunter2"]])
check("wifi enables the transport", saved["WIFI_ENABLED"] is True)

check("oversized ssid ignored",
      fw.apply_provision({"wifi_ssid": "x" * 40}) is False)


print("\n%d failed" % len(failures) if failures else "\nall passed")
sys.exit(1 if failures else 0)
