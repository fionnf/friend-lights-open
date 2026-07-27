# ============================================================
#  portal.py  —  The lamp as its own access point
# ============================================================
# When you are standing next to the lamp there is no reason to spend a
# downlink on it. The lamp raises its own WiFi network, serves a page,
# and you control it directly: instant, free, and it never touches the
# ten-a-day budget.
#
# This is also where TTN keys get entered, so nobody has to edit
# config.py over USB to set up a lamp.
#
# ── Why an access point and not Bluetooth ────────────────────────────
# Web Bluetooth does not exist on iOS — not in Safari, and not in Chrome
# or Firefox there either, because they are all WebKit underneath. A BLE
# control app would simply not work for anyone with an iPhone, which is
# not something to discover after posting a lamp to a friend. A captive
# portal works on every phone ever made, with no app to install.
#
# ── Why it must never block ──────────────────────────────────────────
# The render loop runs at ~60 fps and feeds an 8 s watchdog. A blocking
# accept() would freeze the lamp mid-breath and eventually reboot it. So
# every socket here is non-blocking and driven from tick().

import socket
import ujson
import utime

try:
    import network
except ImportError:
    network = None

AP_IP        = "192.168.4.1"
IDLE_TIMEOUT = 5 * 60 * 1000        # only used when always_on is False
CONN_TIMEOUT = 5_000                # abandon a half-sent request
MAX_REQUEST  = 4096                 # refuse anything larger

# Phones probe these to decide whether a network has internet. Answering
# with a redirect is what makes the login page pop up on its own instead
# of the user having to know to open a browser.
PROBE_PATHS = (
    "/generate_204",                # Android
    "/gen_204",
    "/hotspot-detect.html",         # iOS / macOS
    "/library/test/success.html",
    "/ncsi.txt",                    # Windows
    "/connecttest.txt",
    "/canonical.html",              # Firefox
    "/success.txt",
)


class Portal:
    """Non-blocking AP + captive portal. Call tick() from the main loop."""

    def __init__(self, shared, engine, lamp_id, on_config=None,
                 page="/lamp/www/index.html", password=None,
                 always_on=False, ssid=None):
        self.shared = shared
        self.engine = engine
        self.lamp_id = lamp_id
        self.on_config = on_config          # called with a dict when saved
        self.page = page
        # WPA2 needs 8 characters. Anything shorter is silently refused by
        # the ESP32 and you get an OPEN network without being told, so it
        # is better to fall back deliberately and say so.
        self.password = password if (password and len(password) >= 8) else None
        if password and not self.password:
            print("[portal] password under 8 chars — network will be OPEN")
        self.always_on = always_on
        self._ssid_override = ssid
        self.active = False
        self.ssid = None
        self._ap = None
        self._http = None
        self._dns = None
        self._conns = []                    # (sock, buffer, deadline)
        self._deadline = 0

    # ── Lifecycle ───────────────────────────────────────────

    def start(self):
        if self.active or network is None:
            return False
        self.ssid = self._ssid_override or ("lamp-%d" % self.lamp_id)
        # 802.11 caps an SSID at 32 bytes. Longer is rejected by the
        # driver, and the lamp would come up with no network at all.
        if len(self.ssid) > 32:
            self.ssid = self.ssid[:32]
            print("[portal] SSID truncated to '%s'" % self.ssid)
        try:
            self._ap = network.WLAN(network.AP_IF)
            self._ap.active(True)
            if self.password:
                # WPA2. With the network up permanently rather than for
                # five minutes on demand, a password is what keeps it
                # from being an open door onto the lamp for the street.
                authmode = getattr(network, "AUTH_WPA2_PSK", 3)
                self._ap.config(essid=self.ssid, password=self.password,
                                authmode=authmode)
            else:
                self._ap.config(essid=self.ssid, authmode=0)

            self._http = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._http.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._http.bind(("0.0.0.0", 80))
            self._http.listen(4)
            self._http.setblocking(False)

            self._dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._dns.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._dns.bind(("0.0.0.0", 53))
            self._dns.setblocking(False)

            self.active = True
            self._deadline = utime.ticks_add(utime.ticks_ms(), IDLE_TIMEOUT)
            print("[portal] up — join WiFi '%s'%s then open http://%s"
                  % (self.ssid,
                     " (password set)" if self.password else " (open)",
                     AP_IP))
            return True
        except Exception as e:
            print("[portal] failed to start: %s" % e)
            self.stop()
            return False

    def stop(self):
        for sock in [c[0] for c in self._conns] + [self._http, self._dns]:
            try:
                if sock:
                    sock.close()
            except Exception:
                pass
        self._conns = []
        self._http = self._dns = None
        try:
            if self._ap:
                self._ap.active(False)
        except Exception:
            pass
        self._ap = None
        if self.active:
            print("[portal] down")
        self.active = False

    def keep_alive(self):
        self._deadline = utime.ticks_add(utime.ticks_ms(), IDLE_TIMEOUT)

    # ── Pump ────────────────────────────────────────────────

    def tick(self):
        """Service the portal. Returns quickly, always."""
        if not self.active:
            return
        now = utime.ticks_ms()
        if not self.always_on and utime.ticks_diff(now, self._deadline) >= 0:
            print("[portal] idle timeout")
            self.stop()
            return
        self._pump_dns()
        self._pump_http(now)

    def _pump_dns(self):
        """Answer every A query with our own address, so the phone's
        connectivity probe resolves here and the portal opens itself."""
        for _ in range(4):                  # bounded: never drain forever
            try:
                query, addr = self._dns.recvfrom(256)
            except Exception:
                return
            if len(query) < 12:
                continue
            try:
                self._dns.sendto(self._dns_reply(query), addr)
            except Exception:
                return

    @staticmethod
    def _dns_reply(query):
        # Minimal A-record answer pointing at AP_IP. We echo the question
        # section verbatim rather than parsing it — every name resolves
        # here anyway, so the name itself does not matter.
        end = 12
        while end < len(query) and query[end] != 0:
            end += 1 + query[end]
        question = query[12:end + 5]        # name + null + qtype + qclass
        return (query[:2]                   # transaction id
                + b"\x81\x80"               # standard response, no error
                + b"\x00\x01\x00\x01"       # 1 question, 1 answer
                + b"\x00\x00\x00\x00"
                + question
                + b"\xc0\x0c"               # pointer back to the name
                + b"\x00\x01\x00\x01"       # A, IN
                + b"\x00\x00\x00\x1e"       # TTL 30 s
                + b"\x00\x04"
                + bytes(int(o) for o in AP_IP.split(".")))

    def _pump_http(self, now):
        try:
            conn, _ = self._http.accept()
            conn.setblocking(False)
            self._conns.append([conn, b"", utime.ticks_add(now, CONN_TIMEOUT)])
        except Exception:
            pass                            # nothing waiting; normal

        for entry in list(self._conns):
            conn, buf, deadline = entry
            try:
                chunk = conn.recv(512)
            except Exception:
                chunk = None                # would block

            if chunk:
                buf += chunk
                entry[1] = buf

            if self._complete(buf):
                self._conns.remove(entry)
                try:
                    self._respond(conn, buf)
                except Exception as e:
                    print("[portal] request failed: %s" % e)
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass
                self.keep_alive()
            elif (chunk == b"" or len(buf) > MAX_REQUEST
                  or utime.ticks_diff(now, deadline) >= 0):
                # Peer hung up, sent something absurd, or stalled. A
                # leaked socket here would exhaust the heap over an
                # afternoon of a phone reconnecting in someone's pocket.
                self._conns.remove(entry)
                try:
                    conn.close()
                except Exception:
                    pass

    @staticmethod
    def _complete(buf):
        """True once the whole request (headers + any body) has arrived."""
        if b"\r\n\r\n" not in buf:
            return False
        head, body = buf.split(b"\r\n\r\n", 1)
        length = 0
        for line in head.split(b"\r\n"):
            if line.lower().startswith(b"content-length:"):
                try:
                    length = int(line.split(b":", 1)[1].strip())
                except ValueError:
                    length = 0
        return len(body) >= length

    # ── Routing ─────────────────────────────────────────────

    def _respond(self, conn, raw):
        head, _, body = raw.partition(b"\r\n\r\n")
        request = head.split(b"\r\n")[0].decode("utf-8", "ignore")
        parts = request.split(" ")
        if len(parts) < 2:
            return
        method, path = parts[0], parts[1].split("?")[0]

        if path in PROBE_PATHS:
            # 302 rather than serving the page directly — this is what
            # makes the phone show its "sign in to network" banner.
            self._send(conn, 302, "text/plain", b"",
                       extra="Location: http://%s/\r\n" % AP_IP)
            return

        if method == "GET" and path in ("/", "/index.html"):
            self._send_file(conn)
            return

        if method == "GET" and path == "/state":
            self._json(conn, {
                "lamp_id": self.lamp_id,
                "hue": round(self.shared.hue(), 4),
                "warmth": round(self.shared.warmth(), 4),
                "touches": self.shared.total_touches(),
                "brightness": round(self.engine.brightness, 3),
                "on": self.engine.is_on,
            })
            return

        if method == "POST":
            try:
                data = ujson.loads(body) if body else {}
            except Exception:
                self._json(conn, {"error": "bad json"}, status=400)
                return
            if not isinstance(data, dict):
                self._json(conn, {"error": "bad json"}, status=400)
                return

            if path == "/touch":
                self.shared.touch()
                self.engine.note_arrival()
                self._json(conn, {"hue": round(self.shared.hue(), 4)})
                return

            if path == "/set":
                if "brightness" in data:
                    try:
                        self.engine.set_brightness(float(data["brightness"]))
                    except (TypeError, ValueError):
                        pass
                if "on" in data:
                    self.engine.set_power(bool(data["on"]))
                if "hue_steps" in data:
                    try:
                        # Clamped: the access point is open, so anything
                        # on it can post here, and an unbounded step would
                        # let one request spin the colour wheel arbitrarily
                        # far — which then propagates to the friend's lamp.
                        steps = int(data["hue_steps"])
                        steps = max(1, min(16, steps))
                        self.shared.touch(steps)
                        self.engine.note_arrival()
                    except (TypeError, ValueError):
                        pass
                self._json(conn, {"ok": True})
                return

            if path == "/config":
                saved = bool(self.on_config and self.on_config(data))
                self._json(conn, {"saved": saved})
                return

        self._send(conn, 404, "text/plain", b"not found")

    # ── Responses ───────────────────────────────────────────

    REASONS = {200: "OK", 302: "Found", 400: "Bad Request",
               404: "Not Found", 500: "Internal Server Error"}

    def _send(self, conn, status, ctype, body, extra=""):
        # The reason phrase has to match the code. Sending "404 OK" is
        # tolerated by browsers but is a lie to anything stricter.
        header = ("HTTP/1.1 %d %s\r\nContent-Type: %s\r\n"
                  "Content-Length: %d\r\nConnection: close\r\n%s\r\n"
                  % (status, self.REASONS.get(status, "OK"),
                     ctype, len(body), extra))
        conn.send(header.encode())
        if body:
            conn.send(body)

    def _json(self, conn, obj, status=200):
        self._send(conn, status, "application/json", ujson.dumps(obj).encode())

    def _send_file(self, conn):
        """Stream the page from flash rather than holding it in RAM.

        The ESP32-S3 has plenty of flash and much less RAM; loading a
        page into a Python string on every request would fragment the
        heap over an evening of use."""
        try:
            size = 0
            with open(self.page, "rb") as f:
                while True:
                    chunk = f.read(512)
                    if not chunk:
                        break
                    size += len(chunk)
            conn.send(("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n"
                       "Content-Length: %d\r\nConnection: close\r\n\r\n"
                       % size).encode())
            with open(self.page, "rb") as f:
                while True:
                    chunk = f.read(512)
                    if not chunk:
                        break
                    conn.send(chunk)
        except OSError:
            self._send(conn, 500, "text/plain",
                       b"index.html missing from the board")
