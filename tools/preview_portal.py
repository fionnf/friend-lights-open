#!/usr/bin/env python3
"""
Open the lamp's control page in your browser, with no lamp.

  python3 tools/preview_portal.py
  -> http://127.0.0.1:8080

Every request goes through the REAL Portal._respond, driving the REAL
SharedColour and Engine. So this is not a mock of the page — it is the
page, served by the same routing code the lamp runs, against the same
CRDT. If a button works here it works there.

The engine ticks in the background at 60 fps against a fake strip, so
slow arrivals, breathing and the arrival pulses all behave as they will
on hardware.

  --lamps 2   also simulate a friend's lamp, which touches its own every
              --friend-every seconds, so you can watch colour arrive.
"""
import argparse
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tests", "stubs"))
sys.path.insert(0, os.path.join(ROOT, "firmware", "lamp"))

import utime                      # noqa: E402  (stub clock)
import codec                      # noqa: E402
from shared_state import SharedColour   # noqa: E402
from engine import Engine               # noqa: E402
from portal import Portal               # noqa: E402

PAGE = os.path.join(ROOT, "firmware", "lamp", "www", "index.html")


class FakeStrip:
    def __init__(self, n):
        self.num_leds = n
        self.pixels = [(0, 0, 0, 0)] * n
        self.brightness = 1.0

    def set(self, i, r=0, g=0, b=0, w=0):
        if 0 <= i < self.num_leds:
            self.pixels[i] = (r, g, b, w)

    def set_all(self, r=0, g=0, b=0, w=0):
        self.pixels = [(r, g, b, w)] * self.num_leds

    def set_brightness(self, v):
        self.brightness = v

    def show(self):
        pass

    def off(self):
        self.set_all(0, 0, 0, 0)


class Capture:
    """Stands in for a socket, collecting what the portal writes."""

    def __init__(self):
        self.out = b""

    def send(self, data):
        self.out += data if isinstance(data, bytes) else data.encode()

    def close(self):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--leds", type=int, default=10)
    ap.add_argument("--lamps", type=int, default=1, choices=(1, 2),
                    help="2 simulates a friend touching theirs")
    ap.add_argument("--friend-every", type=float, default=20,
                    help="seconds between the friend's touches")
    ap.add_argument("--arrival-fade", type=float, default=90,
                    help="seconds for a colour to arrive")
    args = ap.parse_args()

    shared = SharedColour(1)
    engine = Engine(shared, args.leds, brightness=0.6,
                    arrival_fade_ms=int(args.arrival_fade * 1000))
    strip = FakeStrip(args.leds)

    saved = {}

    def on_config(data):
        saved.update(data)
        print("  config received: %s" % sorted(data))
        return True          # accepted, so the page shows the real path

    portal = Portal(shared, engine, 1, on_config=on_config, page=PAGE,
                    always_on=True)
    portal.ssid = "deLENIghted-1-preview"

    stop = threading.Event()

    def run_engine():
        """Advance the stub clock in real time and render."""
        friend_at = time.time() + args.friend_every
        while not stop.is_set():
            utime.sleep_ms(16)          # the stub clock the engine reads
            engine.tick(strip)
            if args.lamps == 2 and time.time() >= friend_at:
                friend_at = time.time() + args.friend_every
                h, w, t = shared._hue.get(2, 0), shared._warm.get(2, 0), \
                    shared._touch.get(2, 0)
                shared.apply_remote(2, h + 4096, w + 2730, t + 1)
                engine.note_arrival()
                print("  friend touched theirs -> hue %.3f" % shared.hue())
            time.sleep(0.016)

    threading.Thread(target=run_engine, daemon=True).start()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def _serve(self, method):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            raw = ("%s %s HTTP/1.1\r\nContent-Length: %d\r\n\r\n"
                   % (method, self.path, length)).encode() + body

            conn = Capture()
            portal._respond(conn, raw)          # the real routing code

            head, _, payload = conn.out.partition(b"\r\n\r\n")
            lines = head.split(b"\r\n")
            status = int(lines[0].split(b" ")[1]) if lines and lines[0] else 500
            self.send_response(status)
            for line in lines[1:]:
                if b":" in line:
                    k, v = line.split(b":", 1)
                    if k.lower() not in (b"content-length", b"connection"):
                        self.send_header(k.decode(), v.strip().decode())
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            self._serve("GET")

        def do_POST(self):
            self._serve("POST")

        def log_message(self, *a):
            pass                                 # too noisy at 1 poll/2 s

    # The page asks for a name the firmware supplies; the portal's /state
    # does not include one, so nothing here needs to fake it.
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print("\n  The lamp's page, running on your laptop:")
    print("      http://127.0.0.1:%d\n" % args.port)
    print("  Real Portal routing, real CRDT, real colour engine.")
    if args.lamps == 2:
        print("  A friend touches their lamp every %gs — watch the colour"
              % args.friend_every)
        print("  drift over ~%gs rather than jumping." % args.arrival_fade)
    else:
        print("  Add --lamps 2 to watch a friend's colour arrive.")
    print("\n  Ctrl-C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped\n")
    finally:
        stop.set()


if __name__ == "__main__":
    main()
