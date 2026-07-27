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

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

failures = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name +
          (("  " + str(detail)) if detail and not cond else ""))
    if not cond:
        failures.append(name)


def run():
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

    check("watchdog was armed", fw.wdt is not None)
    check("watchdog is being fed", fw.wdt.feeds > 10, fw.wdt.feeds)
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
    check("first send goes out", lora.send(frame) is True)
    check("second send is throttled", lora.send(frame) is False)
    check("force bypasses the throttle", lora.send(frame, force=True) is True)
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
    run()
    run_transport_checks()
    run_router_checks()
    print("\n%d failed" % len(failures) if failures else "\nall passed")
    sys.exit(1 if failures else 0)
