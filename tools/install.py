#!/usr/bin/env python3
"""
One command from a bare board to a lit lamp.

    python3 tools/install.py            everything, start to finish
    python3 tools/install.py --deploy --lamp 1 [--port /dev/ttyACM0]
                                        just reload the code

Rerun it any time — it looks at what exists and does the next thing:
installs the flashing tools, finds the board, fetches and flashes
MicroPython, asks for the TTN values (or reads your .env), runs every
test, loads the firmware, and offers a radio check.

It never deletes anything, and it stops rather than guesses: every
answer it needs that it cannot detect, it asks for.

What it cannot do for you, because they happen in a browser:
registering the two devices in the TTN console (docs/SETUP.md step 3)
and pasting the bridge into Cloudflare (step 4).
"""
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

IMAGE_PAGE = "https://micropython.org/download/ESP32_GENERIC_S3/"
# Stable builds only — a dated preview link looks identical but says
# "preview" in the version, and nobody's first lamp should be on one.
IMAGE_LINK = re.compile(
    r'href="(/resources/firmware/ESP32_GENERIC_S3-\d{8}-v[\d.]+\.bin)"')


def say(text=""):
    print(text)


def step(title):
    print("\n== %s ==" % title)


def run(cmd, **kw):
    """Run a command, echoing it first so nothing happens invisibly."""
    print("   $ " + " ".join(cmd))
    return subprocess.run(cmd, **kw)


def mpremote(port, *args, **kw):
    """Always `python -m mpremote`, never the bare script: a pip
    --user install puts that script in a directory that is often not on
    PATH, and the module form works either way."""
    try:
        return run([sys.executable, "-m", "mpremote", "connect", port]
                   + list(args), **kw)
    except subprocess.TimeoutExpired:
        # A port that enumerates but never answers — wrong device, a
        # wedged board, or something else holding it open. Reported as
        # a failed command, which every caller already handles.
        say("   (no answer from %s)" % port)
        return subprocess.CompletedProcess(args, 1, "", "timed out")


# ── Pure helpers (tested in tests/test_install.py) ───────────

def clean_hex(value, length):
    """Forgive every way a hex value gets pasted: spaces, 0x, colons,
    mixed case. Returns the cleaned string or None."""
    cleaned = re.sub(r"^0[xX]|[\s:,-]", "", str(value))
    if len(cleaned) != length or not re.match(r"^[0-9A-Fa-f]+$", cleaned):
        return None
    if set(cleaned) == {"0"}:
        return None                     # a real key is never all zeros
    return cleaned.upper()


def image_links(html):
    """Stable firmware links from the MicroPython download page,
    newest first (the page lists them that way)."""
    return IMAGE_LINK.findall(html)


def device_files(root=ROOT):
    """(local, remote) for everything the board needs except config.py,
    derived by walking firmware/ so this can never drift from what the
    firmware actually is."""
    out = [(os.path.join(root, "firmware", "main.py"), ":main.py"),
           (os.path.join(root, "tools", "radio_check.py"), ":radio_check.py")]
    lamp = os.path.join(root, "firmware", "lamp")
    for dirpath, _dirs, files in os.walk(lamp):
        for name in sorted(files):
            if not (name.endswith(".py") or name.endswith(".html")):
                continue
            local = os.path.join(dirpath, name)
            rel = os.path.relpath(local, os.path.dirname(lamp))
            out.append((local, ":" + rel.replace(os.sep, "/")))
    return out


def remote_dirs(files):
    """Every directory the remote paths need, parents first."""
    dirs = set()
    for _local, remote in files:
        parts = remote.lstrip(":").split("/")[:-1]
        for i in range(1, len(parts) + 1):
            dirs.add(":" + "/".join(parts[:i]))
    return sorted(dirs)


def env_text(answers):
    """A minimal .env from the wizard's answers. .env.example remains
    the commented reference; this only holds what was actually given."""
    lines = ["# Written by tools/install.py — edit freely, or rerun it.",
             "LORA_RADIO = SX1262", ""]
    for n in (1, 2):
        # apply_env.py strips from the first '#', so a name containing
        # one would silently lose its tail.
        name = answers.get("name%d" % n, "").split("#")[0].strip()
        lines.append("LAMP%d_NAME    = %s" % (n, name))
        for key in ("DEV_ADDR", "NWK_SKEY", "APP_SKEY"):
            lines.append("LAMP%d_%s = %s"
                         % (n, key, answers["%s%d" % (key.lower(), n)]))
        lines.append("")
    lines.append("NUM_LEDS      = %s" % answers.get("num_leds", "10"))
    lines.append("NUM_GROUPS    = %s" % answers.get("num_groups", "3"))
    lines.append("PORTAL_PASSWORD = %s"
                 % answers.get("portal_password", "lightupleni"))
    return "\n".join(lines) + "\n"


def collect_env(ask):
    """Interactive .env answers. `ask` is input(), injectable for tests.

    Validation happens here, at the moment of typing, because the
    alternative is apply_env.py refusing later with the same message
    and a trip back to the TTN console."""
    say("\n  The six values from the TTN console (docs/SETUP.md step 3).")
    say("  Each is on the device page under General settings -> Session")
    say("  information; the two keys are behind an eye icon. Paste them")
    say("  however they come — spaces and 0x are fine.\n")

    answers = {}
    for n in (1, 2):
        say("  -- Lamp %d --" % n)
        answers["name%d" % n] = ask("  name (optional, shows in its "
                                    "WiFi name): ").strip()
        for label, key, length in (("DevAddr", "dev_addr", 8),
                                   ("NwkSKey", "nwk_skey", 32),
                                   ("AppSKey", "app_skey", 32)):
            while True:
                value = clean_hex(ask("  %s (%d hex): " % (label, length)),
                                  length)
                if value:
                    answers["%s%d" % (key, n)] = value
                    break
                say("     that wasn't %d hex characters — try again"
                    % length)
    leds = ask("  How many LEDs on the strip? [10]: ").strip()
    if leds.isdigit():
        answers["num_leds"] = leds

    # The one pair that must not match — same check apply_env makes,
    # surfaced now while the console is still open in the other tab.
    for key in ("dev_addr", "nwk_skey", "app_skey"):
        if answers[key + "1"] == answers[key + "2"]:
            say("\n  Lamp 1 and lamp 2 have the same %s. Each lamp needs"
                % key.upper())
            say("  its own, or they fight over one session. Start over.\n")
            return None
    return answers


# ── Steps ────────────────────────────────────────────────────

def ensure_tools():
    step("flashing tools")
    missing = []
    for module in ("mpremote", "esptool", "serial"):
        try:
            __import__(module)
        except ImportError:
            missing.append("pyserial" if module == "serial" else module)
    if not missing:
        say("   esptool and mpremote already installed")
        return True
    say("   installing: %s" % ", ".join(missing))
    r = run([sys.executable, "-m", "pip", "install"] + missing)
    if r.returncode != 0:
        say("   pip refused — trying a user install")
        r = run([sys.executable, "-m", "pip", "install", "--user"] + missing)
    if r.returncode != 0:
        say("\n  Could not install. Run this yourself, then rerun me:")
        say("      %s -m pip install esptool mpremote\n" % sys.executable)
        return False
    return True


def find_port(ask):
    step("finding the board")
    from serial.tools import list_ports
    while True:
        ports = list(list_ports.comports())
        # The XIAO's native USB is Espressif's VID. Filtering on it
        # hides the user's other serial junk, which on a machine with a
        # debugger attached is the difference between one obvious
        # answer and a guessing game.
        espressif = [p for p in ports if p.vid == 0x303A]
        candidates = espressif or ports
        if len(candidates) == 1:
            say("   found %s (%s)" % (candidates[0].device,
                                      candidates[0].description))
            return candidates[0].device
        if candidates:
            say("   more than one port:")
            for i, p in enumerate(candidates, 1):
                say("     %d. %s (%s)" % (i, p.device, p.description))
            choice = ask("   which one? [1]: ").strip() or "1"
            if choice.isdigit() and 1 <= int(choice) <= len(candidates):
                return candidates[int(choice) - 1].device
            continue
        say("   no serial port found.")
        say("   Plug the XIAO in over USB-C — and if it is already")
        say("   plugged in, suspect the cable: many are charge-only.")
        if ask("   press Enter to look again, or q to quit: ").strip() == "q":
            return None


def board_has_micropython(port):
    r = mpremote(port, "exec",
                 "import sys; print(sys.implementation.name)",
                 capture_output=True, text=True, timeout=15)
    return r.returncode == 0 and "micropython" in (r.stdout or "")


# A plain ESP32_GENERIC_S3 build, dated, stable. Deliberately strict:
# "ESP32_GENERIC_S3_SPIRAM_OCT" also starts with ESP32_GENERIC_S3 and
# will not boot on a XIAO, and "_" sorts AFTER "-", so a loose copy of
# it in ~/Downloads used to win a naive newest-first pick.
IMAGE_FILE = re.compile(
    r"^ESP32_GENERIC_S3-(\d{8})-v[\d.]+\.bin$")


def local_images(names):
    """The usable images among `names`, newest first."""
    dated = [(m.group(1), n) for n in names for m in [IMAGE_FILE.match(n)] if m]
    return [n for _d, n in sorted(dated, reverse=True)]


def find_or_fetch_image(ask):
    """A MicroPython .bin, from disk if one is lying around, else from
    micropython.org with permission."""
    for folder in (ROOT, os.getcwd(), os.path.expanduser("~/Downloads")):
        if not os.path.isdir(folder):
            continue
        found = local_images(os.listdir(folder))
        if found:
            path = os.path.join(folder, found[0])
            say("   using %s" % path)
            return path
    if ask("   download the latest MicroPython for the ESP32-S3? "
           "[Y/n]: ").strip().lower() == "n":
        say("   get it yourself from %s and rerun me" % IMAGE_PAGE)
        return None
    try:
        from urllib.request import urlopen
        html = urlopen(IMAGE_PAGE, timeout=30).read().decode()
        links = image_links(html)
        if not links:
            raise OSError("no firmware links on the page")
        url = "https://micropython.org" + links[0]
        path = os.path.join(ROOT, os.path.basename(links[0]))
        say("   downloading %s" % url)
        with open(path, "wb") as f:
            f.write(urlopen(url, timeout=120).read())
        return path
    except Exception as e:
        say("   download failed (%s)" % e)
        say("   get the ESP32_GENERIC_S3 .bin from %s" % IMAGE_PAGE)
        say("   put it next to this repo, and rerun me")
        return None


def flash_micropython(port, ask):
    step("flashing MicroPython")
    image = find_or_fetch_image(ask)
    if not image:
        return None
    say("")
    say("   Put the board in bootloader mode:")
    say("     hold  B (BOOT), tap  R (RESET), release  B")
    ask("   then press Enter... ")
    # The port number usually changes in bootloader mode. If the user
    # gives up here, stop — `or port` used to swallow the refusal and
    # erase a board on the stale pre-bootloader port.
    port = find_port(ask)
    if not port:
        return None
    if run([sys.executable, "-m", "esptool", "--chip", "esp32s3",
            "--port", port, "erase_flash"]).returncode != 0:
        return None
    if run([sys.executable, "-m", "esptool", "--chip", "esp32s3",
            "--port", port, "--baud", "460800",
            "write_flash", "-z", "0", image]).returncode != 0:
        return None
    say("")
    ask("   tap R (RESET), then press Enter... ")
    port = find_port(ask)
    if not port:
        return None
    if not board_has_micropython(port):
        say("   the board did not come back speaking MicroPython —")
        say("   see docs/FLASHING.md for the failure modes")
        return None
    say("   MicroPython is on")
    return port


def ensure_config(ask):
    step("configuration")
    have = [n for n in (1, 2) if os.path.exists(
        os.path.join(ROOT, "firmware", "config.lamp%d.py" % n))]
    if len(have) == 2:
        say("   both lamp configs exist")
        return True
    env = os.path.join(ROOT, ".env")
    if not os.path.exists(env):
        answers = collect_env(ask)
        if not answers:
            return False
        with open(env, "w") as f:
            f.write(env_text(answers))
        say("   wrote .env (gitignored)")
    r = run([sys.executable, os.path.join(HERE, "apply_env.py")])
    return r.returncode == 0


def run_tests():
    step("tests")
    tests = sorted(
        f for f in os.listdir(os.path.join(ROOT, "tests"))
        if f.startswith("test_") and f.endswith(".py"))
    for t in tests:
        r = run([sys.executable, os.path.join(ROOT, "tests", t)],
                capture_output=True, text=True)
        say("   %-26s %s" % (t, "ok" if r.returncode == 0 else "FAILED"))
        if r.returncode != 0:
            say((r.stdout or "") + (r.stderr or ""))
            say("   Not deploying on a failing suite — a LoRa-only lamp")
            say("   has no over-the-air recovery from a bad load.")
            return False
    return True


def deploy(port, lamp):
    step("loading lamp %d" % lamp)
    # A lamp that has run before has an 8 s hardware watchdog armed, and
    # on the ESP32 a watchdog cannot be stopped — only stretched. Left
    # alone it resets the board partway through the copy, and a partial
    # copy of firmware with no over-the-air recovery is the one way this
    # project can genuinely brick a lamp. Harmless on a fresh board.
    mpremote(port, "exec",
             "from machine import WDT\nWDT(timeout=600000)",
             capture_output=True, timeout=15)

    files = device_files()
    for d in remote_dirs(files):
        mpremote(port, "mkdir", d, capture_output=True)
    config = os.path.join(ROOT, "firmware", "config.lamp%d.py" % lamp)
    for local, remote in [(config, ":config.py")] + files:
        if mpremote(port, "cp", local, remote,
                    capture_output=True, text=True).returncode != 0:
            say("   FAILED copying %s" % local)
            return False
    mpremote(port, "reset", capture_output=True)
    say("   loaded and rebooted")
    return True


def offer_radio_check(port, ask):
    step("radio check")
    say("   Optional, and it TRANSMITS — the antenna must be attached,")
    say("   or the radio's power amplifier can be damaged.")
    if ask("   antenna attached — run it now? [y/N]: "
           ).strip().lower() != "y":
        say("   later:  mpremote connect %s run tools/radio_check.py" % port)
        return
    time.sleep(2)                       # let the board finish booting
    mpremote(port, "exec",
             "from machine import WDT\nWDT(timeout=600000)",
             capture_output=True, timeout=15)
    mpremote(port, "run", os.path.join(HERE, "radio_check.py"))
    mpremote(port, "reset", capture_output=True)


def deploy_only(lamp, port=None):
    """Update the code on a board that is already set up.

    The whole of `deploy.sh`, which used to be a second copy of this
    procedure in bash — and every tooling defect the audit found lived
    only in that copy.
    """
    if not ensure_tools():
        return 1
    port = port or find_port(input)
    if not port:
        return 1
    config = os.path.join(ROOT, "firmware", "config.lamp%d.py" % lamp)
    if not os.path.exists(config):
        say("\n  No config for lamp %d.\n" % lamp)
        say("      python3 tools/apply_env.py\n")
        return 1
    if not run_tests():
        return 1
    return 0 if deploy(port, lamp) else 1


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv

    if "--help" in argv or "-h" in argv:
        say(__doc__)
        return 0

    if "--deploy" in argv:
        lamp, port = 1, None
        for flag, cast in (("--lamp", int), ("--port", str)):
            if flag in argv:
                try:
                    value = cast(argv[argv.index(flag) + 1])
                except (IndexError, ValueError):
                    say("  %s needs a value" % flag)
                    return 1
                if flag == "--lamp":
                    lamp = value
                else:
                    port = value
        if lamp not in (1, 2):
            say("  --lamp must be 1 or 2")
            return 1
        return deploy_only(lamp, port)

    say("Friend Lights — install")
    say("Rerunnable: it does whatever it finds not yet done.")

    if not ensure_tools():
        return 1
    port = find_port(input)
    if not port:
        return 1

    step("checking the board")
    if board_has_micropython(port):
        say("   MicroPython already on the board")
    else:
        say("   no MicroPython yet")
        port = flash_micropython(port, input)
        if not port:
            return 1

    if not ensure_config(input):
        return 1
    if not run_tests():
        return 1

    lamp = (input("\nWhich lamp is this board? [1/2]: ").strip() or "1")
    if lamp not in ("1", "2"):
        say("  1 or 2.")
        return 1
    if not deploy(port, int(lamp)):
        return 1
    offer_radio_check(port, input)

    say("\n== done ==")
    say("The lamp's own WiFi network is up:")
    say("   network   deLENIghted-%s   (plus its name, if you gave one)" % lamp)
    say("   password  lightupleni  (or your PORTAL_PASSWORD)")
    say("   page      http://192.168.4.1")
    say("Watch it reach TTN: console -> your device -> Live data.")
    say("Then rerun me with the other board plugged in.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        say("\nstopped — rerun any time, it picks up where things are")
        sys.exit(1)
