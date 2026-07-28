#!/usr/bin/env python3
"""
Firmware smoke test — actually RUNS main() against stubbed MicroPython
modules.

`python -m py_compile` cannot catch runtime faults. In the original
project a stray function-level import once shadowed a module-level one
for the whole of main(), and every board boot-looped, unreachable until
somebody pushed a fix over the air. Only executing main() catches that
class of bug, and on a LoRa-only lamp there is no over-the-air fix at
all — a bricked lamp means a friend posts it back to you.

Run from the repo root:   python3 tests/test_firmware.py
"""
import os, shutil, sys, tempfile
import traceback as _tb

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

failures = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name +
          (("  " + str(detail)) if detail and not cond else ""))
    if not cond:
        failures.append(name)


def run(label="", config_extra=""):
    work = tempfile.mkdtemp(prefix="flo-")
    shutil.copytree(os.path.join(ROOT, "firmware", "lamp"),
                    os.path.join(work, "lamp"))
    shutil.copy(os.path.join(ROOT, "firmware", "main.py"), work)
    # The portal serves the page from an absolute path on the board.
    os.makedirs(os.path.join(work, "lamp", "www"), exist_ok=True)
    for item in os.listdir(os.path.join(HERE, "stubs")):
        src = os.path.join(HERE, "stubs", item)
        dst = os.path.join(work, item)
        (shutil.copytree if os.path.isdir(src) else shutil.copy)(src, dst)
    if config_extra:
        # Later assignments win on import, so appending overrides.
        with open(os.path.join(work, "config.py"), "a") as f:
            f.write("\n" + config_extra + "\n")

    # The firmware does sys.path.append("/lamp"); on a real board that is
    # where the package lives. Mirror it here.
    sys.path.insert(0, work)
    sys.path.insert(0, os.path.join(work, "lamp"))
    os.chdir(work)                       # state.json lands in the sandbox

    for m in list(sys.modules):
        if m.split(".")[0] in ("machine", "utime", "network", "neopixel",
                               "ujson", "ubinascii", "umqtt", "config",
                               "main", "engine", "driver", "touch", "codec",
                               "palette", "shared_state", "net", "portal", "socket"):
            del sys.modules[m]

    import traceback as _tb
    if not hasattr(sys, "print_exception"):
        sys.print_exception = lambda e, *a: _tb.print_exception(
            type(e), e, e.__traceback__)

    # Tag every check with which radio this boot was, so a failure names
    # the configuration and not just the symptom.
    tag = (" [%s]" % label) if label else ""
    _check = globals()["check"]     # rebinding `check` makes it local here

    def check(name, cond, detail=""):           # noqa: shadows on purpose
        _check(name + tag, cond, detail)

    import machine, utime
    import main as fw

    # ── Stop the infinite loop after enough iterations ──
    class Done(Exception):
        pass

    LIMIT = 400
    iters = [0]
    real_sleep = utime.sleep_ms

    def counting_sleep(ms):
        real_sleep(ms)
        iters[0] += 1
        if iters[0] > LIMIT:
            raise Done()

    utime.sleep_ms = counting_sleep
    fw.utime.sleep_ms = counting_sleep

    print("\nboot")
    try:
        fw.main()
        check("main() exited unexpectedly", False)
    except Done:
        check("main() booted and ran the loop", True)
    except machine.ResetCalled:
        check("main() booted without triggering a reset", False)
    except Exception as e:
        _tb.print_exc()
        check("main() booted without raising", False, repr(e))
        return
    finally:
        # Later suites share this utime module and sleep for real
        # (simulated) time; the counting patch must not outlive main().
        utime.sleep_ms = real_sleep
        fw.utime.sleep_ms = real_sleep

    # The Pico W bench lamp turns the watchdog off on purpose: the
    # RP2040's maxes out around 8.4 s and cannot be stretched the way
    # the ESP32's can, so it would reset the board partway through
    # every re-upload. Both states are correct — what must never happen
    # is main() assuming one of them.
    import config as cfg_mod
    wants_wdt = getattr(cfg_mod, "WATCHDOG_ENABLED", True)
    if wants_wdt:
        check("watchdog was armed", fw.wdt is not None)
        check("watchdog is being fed",
              fw.wdt is not None and fw.wdt.feeds > 10,
              fw.wdt.feeds if fw.wdt else None)
    else:
        check("watchdog stayed off, as the config asked", fw.wdt is None)
        check("...and the loop ran anyway", iters[0] > 10, iters[0])
    check("no reset was triggered", machine.reset_count[0] == 0)

    print("\npersistence")
    check("state.json was written", os.path.exists("state.json"))
    import ujson
    with open("state.json") as f:
        saved = ujson.load(f)
    check("counters were persisted", "shared" in saved, saved)

    print("\nrendering")
    # The neopixel stub asserts channel range and tuple width on every
    # write, so reaching this many frames means the engine never produced
    # an out-of-range value or a wrong-width pixel for bpp=4.
    check("frames were rendered", iters[0] > LIMIT)


def run_transport_checks():
    """Drive the LoRaWAN transport directly — the smoke test above only
    proves it starts, not that it speaks the protocol."""
    print("\nlorawan transport")
    import machine
    from net.lorawan_e5 import LoRaWANE5, _hex, _unhex
    import codec

    check("hex encoding", _hex(b"\x0a\x1b") == "0A 1B", _hex(b"\x0a\x1b"))
    check("hex decoding", _unhex("0A 1B") == b"\x0a\x1b")
    check("odd-length hex rejected", _unhex("0A1") is None)
    check("non-hex rejected", _unhex("ZZ") is None)

    uart = machine.UART()
    lora = LoRaWANE5(uart, "00" * 8, "00" * 8, "00" * 16)
    check("joins against a well-behaved module", lora.start() is True)
    check("reports connected", lora.connected is True)

    frame = codec.encode(2, 1234, 567, 8)
    import utime as _t
    gap = lora.min_gap_ms

    # Two budgets are in play and they answer different questions. The
    # BUCKET rations messages per day. The GAP is the EU868 duty cycle:
    # the minimum spacing between any two transmissions, which is law
    # and therefore holds even against `force`.
    check("the first send goes out", lora.send(frame) is True)
    check("a second one straight after is refused — duty cycle",
          lora.send(frame) is False)
    check("...and force does not buy past the duty cycle",
          lora.send(frame, force=True) is False)

    _t.sleep_ms(gap + 1)
    check("a gap later it goes — the boot allowance is two",
          lora.send(frame) is True)

    _t.sleep_ms(gap + 1)
    check("the third is refused, budget spent", lora.send(frame) is False)
    check("but force spends past the daily budget",
          lora.send(frame, force=True) is True)

    _t.sleep_ms(3 * 60 * 60 * 1000)            # one refill
    check("one refill interval buys exactly one send",
          lora.send(frame) is True)
    _t.sleep_ms(gap + 1)
    check("...and no more", lora.send(frame) is False)

    _t.sleep_ms(24 * 60 * 60 * 1000)           # a quiet day
    sent = 0
    for _ in range(lora.burst + 2):
        if lora.send(frame):
            sent += 1
        _t.sleep_ms(gap + 1)
    check("a quiet day fills the bucket to the burst, and no further",
          sent == lora.burst, sent)

    check("payload was sent as hex",
          any("MSGHEX" in w for w in uart.written))

    # A Class C downlink can arrive at any moment, not just after a send.
    uart._out += b'+MSGHEX: PORT: 8; RX: "%s"\r\n' % _hex(frame).encode()
    got = lora.poll()
    check("downlink received", len(got) == 1, len(got))
    if got:
        decoded = codec.decode(got[0])
        check("downlink round trips", decoded["hue_total"] == 1234,
              decoded["hue_total"])

    uart._out += b'+MSGHEX: PORT: 8; RX: "garbage"\r\n'
    check("malformed downlink does not raise", lora.poll() == [])


def run_budget_checks():
    """How a messages-per-day budget becomes a send interval.

    The duty-cycle floor is the part that matters: it is a legal limit
    rather than a policy one, nothing else in the stack enforces it,
    and it must survive every way a config can ask to go faster —
    including a config that asks for no budget at all."""
    print("\nsend budget")
    import main as fw

    day = 24 * 60 * 60 * 1000
    check("48 a day is every half hour",
          fw.send_interval_ms(48) == day // 48, fw.send_interval_ms(48))
    check("10 a day is the TTN Fair Use rate",
          fw.send_interval_ms(10) == day // 10, fw.send_interval_ms(10))

    floor = fw.DUTY_CYCLE_FLOOR_MS
    check("a huge budget is still held at the duty-cycle floor",
          fw.send_interval_ms(100000) == floor, fw.send_interval_ms(100000))
    check("no budget means the floor, not zero",
          fw.send_interval_ms(0) == floor, fw.send_interval_ms(0))
    check("...and so does a missing one",
          fw.send_interval_ms(None) == floor)
    check("...and so does junk in the config",
          fw.send_interval_ms("lots") == floor)
    check("a negative budget cannot invert the gap",
          fw.send_interval_ms(-5) == floor, fw.send_interval_ms(-5))

    # Zero would divide by zero inside the token bucket's refill.
    check("the interval is never zero, whatever is asked for",
          all(fw.send_interval_ms(b) > 0
              for b in (0, -1, None, "x", 10, 48, 999999)))

    check("an explicit interval still wins, for older configs",
          fw.send_interval_ms(48, explicit=3 * 60 * 60 * 1000)
          == 3 * 60 * 60 * 1000)
    check("but not below the floor",
          fw.send_interval_ms(48, explicit=5) == floor)


def run_abp_checks():
    """The SX1262 path. The radio itself needs hardware, but everything
    around it — a module that is not there, a retry, a frame going out —
    does not, and those are what decide whether a lamp with a loose
    board-to-board connector is a lamp or a brick."""
    print("\nabp transport (SX1262)")
    from net.lorawan_abp import LoRaWANABP
    import codec

    # ── No module attached ──
    looked = []

    def nothing_there():
        looked.append(1)
        return None

    lora = LoRaWANABP(nothing_there, b"\x26\x0b\x11\x11",
                      b"\x00" * 16, b"\x11" * 16)
    check("a missing radio does not raise", lora.start() is False)
    check("...and the lamp is simply not connected", lora.connected is False)
    check("...and sending is refused rather than crashing",
          lora.send(codec.encode(1, 0, 0, 0)) is False)
    lora.start()
    # Looking again on every retry is the whole point: a module seated
    # after power-on, or a brownout during the probe, must recover
    # without anyone unplugging the lamp.
    check("...and every retry looks again", len(looked) == 2, looked)

    # ── Module attached ──
    class FakeRadio:
        def __init__(self):
            self.sent = []
            self.listening = None

        def begin(self, **kw):
            return True

        def listen(self, freq, sf):
            self.listening = (freq, sf)

        def set_frequency(self, hz):
            self.freq = hz

        def set_modulation(self, sf, bw, cr):
            pass

        def send(self, frame):
            self.sent.append(frame)
            return True

        def receive(self):
            return None

        def sleep(self):
            pass

    radio = FakeRadio()
    lora = LoRaWANABP(lambda: radio, b"\x26\x0b\x11\x11",
                      b"\x00" * 16, b"\x11" * 16)
    check("a radio that answers brings the link up", lora.start() is True)
    check("and Class C parks on RX2",
          radio.listening == (869_525_000, 9), radio.listening)

    check("a frame goes out", lora.send(codec.encode(2, 7, 8, 9)) is True)
    check("...as a full LoRaWAN uplink, not a bare payload",
          len(radio.sent) == 1 and len(radio.sent[0]) == 10 + 13,
          [len(f) for f in radio.sent])
    check("...and the receiver was reopened afterwards",
          radio.listening == (869_525_000, 9))
    lora.send(codec.encode(2, 7, 8, 9))        # spends the boot allowance
    check("an empty bucket throttles",
          lora.send(codec.encode(2, 7, 8, 9)) is False)

    # ── No keys ──
    blind = LoRaWANABP(lambda: radio, None, None, None)
    check("no ABP keys is refused before touching the radio",
          blind.start() is False)


def run_finder_checks():
    """main.py's radio finder, against the stub bus — which reads back
    zeros, exactly like a bus with nothing on the other end."""
    print("\nfinding the radio from main.py")
    import main as fw

    import contextlib, io
    log = io.StringIO()
    with contextlib.redirect_stdout(log):
        radio = fw._find_sx1262()
    said = log.getvalue()

    check("no module found on a bus with nothing on it", radio is None)
    # config.py in the stubs puts the LEDs on GPIO2, which is BUSY on the
    # header pinout. Probing means driving it, and driving it writes
    # garbage down the strip — so that pinout must be skipped, not tried.
    check("the pinout that collides with the LED line was skipped",
          "skipping" in said and "GPIO2" in said, said)
    check("and the failure says what to do next",
          "radio_check" in said, said)


def run_strip_test_checks():
    """Execute tools/strip_test.py against the stubs.

    It is a hardware tool, so nothing here can tell whether an LED lit
    — but the neopixel stub asserts channel range and tuple width on
    every write, so running it end to end proves the tool never drives
    an out-of-range value or a wrong-width pixel, and never raises. It
    is the first thing anyone runs on a new board; it failing at that
    moment would be the worst possible first impression."""
    print("\nstrip test tool")
    import io, contextlib
    path = os.path.join(ROOT, "tools", "strip_test.py")
    src = open(path).read()

    # It sleeps ~25 s of real time when run for a human. The stub clock
    # advances instead of waiting, so this is instant — but only if the
    # tool takes its sleeps from utime rather than time.
    check("it sleeps via utime, so the stub clock applies",
          "import time" not in src and "utime" in src)

    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            exec(compile(src, path, "exec"), {"__name__": "__main__"})
        ran = True
    except SystemExit as e:
        ran = (e.code in (None, 0))
    except Exception as e:
        _tb.print_exc()
        ran = False
        check("strip_test.py ran without raising", False, repr(e))
    text = out.getvalue()

    check("strip_test.py runs end to end", ran)
    check("it reports the config it is using", "LED_ORDER" in text)
    check("it names the colour it expects for each channel",
          all(c in text for c in ("RED", "GREEN", "BLUE")), text[:200])
    check("it flashes between colours, as asked",
          "6/6" in text and "amber" in text)
    check("it ends with what to change when something looked wrong",
          "what to change" in text and "REVERSE_LEDS" in text)
    check("and it points at the radio check next",
          "radio_check" in text)


def run_udp_checks():
    """The WiFi broadcast transport the Pico W bench lamp runs on."""
    print("\nudp transport")
    from net.udp_peer import UDPPeer
    import codec

    calls = []

    def wifi(tick=None):
        calls.append(1)
        return True

    udp = UDPPeer(wifi)
    check("it starts once WiFi is up", udp.start() is True)
    check("...and asked for WiFi rather than assuming it", len(calls) == 1)

    # WiFi is unmetered: no budget, no duty cycle. That is the point of
    # testing on it — the lamp's behaviour without a radio's rationing.
    check("no daily budget", udp.min_interval_ms == 0)
    check("no duty-cycle floor", udp.min_gap_ms == 0)

    frame = codec.encode(2, 1234, 567, 8)
    check("a frame goes out", udp.send(frame) is True)
    check("and so does the next, immediately", udp.send(frame) is True)

    sock = udp._sock
    check("it broadcast to the subnet",
          sock.sent and sock.sent[0][1][0] == "255.255.255.255", sock.sent)
    check("on the configured port",
          sock.sent[0][1][1] == udp.port, sock.sent)

    # Receiving: a real frame, then nothing, then junk.
    sock.inbox.append((frame, ("192.168.1.9", udp.port)))
    got = udp.poll()
    check("a peer's frame is delivered", got == [frame], got)
    check("an empty socket is not an error", udp.poll() == [])

    sock.inbox.append((b"not a frame", ("192.168.1.9", udp.port)))
    raw = udp.poll()
    check("junk is passed up, not raised on", len(raw) == 1)
    try:
        codec.decode(raw[0])
        decoded = True
    except Exception:
        decoded = False
    check("...and the codec is what rejects it", decoded is False)

    # A failed WiFi connect must degrade, never raise.
    dead = UDPPeer(lambda tick=None: False)
    check("no WiFi means not connected, not a crash",
          dead.start() is False and dead.connected is False)
    check("...and sending is simply refused", dead.send(frame) is False)

    boom = UDPPeer(lambda tick=None: 1 / 0)
    check("a raising connect is caught too", boom.start() is False)

    udp.stop()
    check("stop() releases the socket", udp._sock is None)


def run_router_checks():
    print("\nrouter")
    from net.transport import Router, Transport

    class Fake(Transport):
        def __init__(self, name):
            Transport.__init__(self)
            self.name = name
            self.sent = []
            self.connected = True
            self.inbox = []

        def _send(self, payload):
            self.sent.append(payload)

        def poll(self):
            got, self.inbox = self.inbox, []
            return got

    a, b = Fake("a"), Fake("b")
    r = Router([a, b])
    check("sends to every transport", r.send(b"xyz") == 2)
    check("both received it", a.sent == b.sent == [b"xyz"])

    b.connected = False
    check("skips a down transport", r.send(b"2") == 1)
    check("still reports connected", r.any_connected() is True)

    class Exploding(Transport):
        name = "boom"

        def poll(self):
            raise RuntimeError("radio on fire")

    r2 = Router([Exploding(), a])
    a.inbox = [b"ok"]
    check("a broken transport cannot take down the loop",
          r2.poll() == [b"ok"])


if __name__ == "__main__":
    # Boot the firmware once per radio configuration. The SX1262 boot is
    # the one real hardware takes: ABP keys present, both pinouts
    # probed, nothing answering — and the lamp must still come up,
    # render, and keep retrying, because a loose board-to-board
    # connector must never mean a dark lamp.
    run(label="E5")
    # The Pico W bench lamp: no radio, WiFi broadcast instead, a button
    # where the ESP32 has a touch pad, and no watchdog. It is the
    # configuration someone will actually boot first, so it gets the
    # same executed-not-compiled treatment as the real one.
    pico = open(os.path.join(ROOT, "pico_w", "config.lamp1.py")).read()
    run(label="pico-w", config_extra=pico)
    run(label="SX1262", config_extra=(
        'LORA_RADIO = "SX1262"\n'
        'LORA_DEV_ADDR = "260B1111"\n'
        'LORA_NWK_SKEY = "0123456789ABCDEF0123456789ABCDEF"\n'
        'LORA_APP_SKEY = "89ABCDEF0123456789ABCDEF01234567"\n'))
    run_transport_checks()
    run_budget_checks()
    run_abp_checks()
    run_finder_checks()
    run_strip_test_checks()
    run_udp_checks()
    run_router_checks()
    print("\n%d failed" % len(failures) if failures else "\nall passed")
    sys.exit(1 if failures else 0)
