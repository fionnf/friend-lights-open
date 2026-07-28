#!/usr/bin/env python3
"""
The install wizard's decisions, without a board.

The wizard is mostly glue around esptool and mpremote, and glue is
tested on hardware. What can go wrong on a laptop is the deciding:
which hex survives cleaning, which firmware link gets picked, what ends
up in .env, and which files would land on the board. Each of those has
a way of being wrong that only shows up at someone's kitchen table.

Run from the repo root:   python3 tests/test_install.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import install                                              # noqa: E402
from install import (clean_hex, collect_env, device_files,  # noqa: E402
                     env_text, image_links, remote_dirs)

failures = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name +
          (("\n          " + str(detail)) if detail and not cond else ""))
    if not cond:
        failures.append(name)


# ── Hex the way people actually paste it ─────────────────────
print("\ncleaning pasted hex")

check("clean value passes", clean_hex("260B1111", 8) == "260B1111")
check("lowercase is uppercased", clean_hex("260b1111", 8) == "260B1111")
check("spaces are forgiven", clean_hex("26 0B 11 11", 8) == "260B1111")
check("colons are forgiven", clean_hex("26:0B:11:11", 8) == "260B1111")
check("a 0x prefix is forgiven", clean_hex("0x260B1111", 8) == "260B1111")
check("wrong length is refused", clean_hex("260B11", 8) is None)
check("non-hex is refused", clean_hex("ZZZZZZZZ", 8) is None)
check("all zeros is refused — that is never a real key",
      clean_hex("00000000", 8) is None)


# ── Picking a MicroPython image ──────────────────────────────
print("\nthe firmware download page")

HTML = """
<a href="/resources/firmware/ESP32_GENERIC_S3-20260715-v1.27.0.bin">v1.27.0</a>
<a href="/resources/firmware/ESP32_GENERIC_S3-20260801-v1.28.0-preview.171.bin">preview</a>
<a href="/resources/firmware/ESP32_GENERIC-20260715-v1.27.0.bin">wrong board</a>
<a href="/resources/firmware/ESP32_GENERIC_S3-20260101-v1.26.0.bin">v1.26.0</a>
"""
links = image_links(HTML)
check("stable builds are found", len(links) == 2, links)
check("the newest listed comes first",
      links and "v1.27.0" in links[0], links)
check("previews are never offered",
      all("preview" not in l for l in links), links)
check("other boards' images are never offered",
      all("ESP32_GENERIC_S3" in l for l in links), links)


# ── What lands on the board ──────────────────────────────────
print("\nthe file list")

files = device_files()
remotes = [r for _l, r in files]
check("main.py goes to the board root", ":main.py" in remotes)
check("radio_check goes along for later", ":radio_check.py" in remotes)
check("the LoRaWAN stack is included",
      ":lamp/net/lorawan_abp.py" in remotes
      and ":lamp/net/sx1262.py" in remotes, remotes)
check("the portal page is included", ":lamp/www/index.html" in remotes)
check("no config file — that is chosen per lamp",
      not any("config" in r for r in remotes), remotes)
check("nothing from __pycache__ sneaks on",
      not any("__pycache__" in r for r in remotes), remotes)
check("every local file actually exists",
      all(os.path.exists(l) for l, _r in files),
      [l for l, _r in files if not os.path.exists(l)])
check("directories are created parents-first",
      remote_dirs(files).index(":lamp") <
      remote_dirs(files).index(":lamp/net"))

# The list is derived by walking firmware/, and this asserts the walk
# actually caught everything. A file the firmware imports but nobody
# copies gives a board that boot-loops on ImportError — and on a
# LoRa-only lamp there is no over-the-air fix, so it means USB or the
# post. This exact bug shipped once: lamp/net/mp_lora/ was added and
# deploy.sh's hand-written globs did not know about it.
on_board = set(r.lstrip(":") for _l, r in files)
expected = set()
for dirpath, _dirs, names in os.walk(os.path.join(ROOT, "firmware", "lamp")):
    if "__pycache__" in dirpath:
        continue
    for name in names:
        if name.endswith(".py") or name.endswith(".html"):
            rel = os.path.relpath(os.path.join(dirpath, name),
                                  os.path.join(ROOT, "firmware"))
            expected.add(rel.replace(os.sep, "/"))
missing = sorted(expected - on_board)
check("every file under firmware/lamp/ is copied to the board",
      not missing, missing)
check("including the vendored upstream driver package",
      any(r.startswith(":lamp/net/mp_lora/") for _l, r in files), on_board)
check("and its directory is created before its files",
      ":lamp/net/mp_lora" in remote_dirs(files), remote_dirs(files))

# deploy.sh asks install.py for this same list rather than keeping its
# own. If that ever gets forked back into two lists, they will drift.
with open(os.path.join(ROOT, "tools", "deploy.sh")) as f:
    deploy = f.read()
check("deploy.sh derives its file list from install.py",
      "device_files" in deploy and "remote_dirs" in deploy)
check("and no longer hand-globs firmware/lamp",
      "firmware/lamp/*.py" not in deploy, "stale glob still present")


# ── The interactive .env ─────────────────────────────────────
print("\nanswers to .env")

SCRIPT = ["leni",                       # lamp 1 name
          "26 0B 11 11", "01" * 16, "23" * 16,
          "",                           # lamp 2, no name
          "0x260B2222", "45" * 16, "67" * 16,
          "24"]                         # LEDs


def scripted(prompts):
    feed = list(prompts)
    return lambda _q: feed.pop(0) if feed else ""


answers = collect_env(scripted(SCRIPT))
check("a full session is accepted", answers is not None)

text = env_text(answers)
sys.path.insert(0, os.path.join(ROOT, "tools"))
from apply_env import load_env                              # noqa: E402
import tempfile

with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as f:
    f.write(text)
    envfile = f.name
try:
    parsed = load_env(envfile)
finally:
    os.unlink(envfile)

check("apply_env can read what the wizard writes",
      parsed.get("LAMP1_DEV_ADDR") == "260B1111"
      and parsed.get("LAMP2_DEV_ADDR") == "260B2222", parsed)
check("messy pastes were cleaned on the way in",
      parsed.get("LAMP1_NWK_SKEY") == "01" * 16, parsed)
check("the radio is the one that clips onto the XIAO",
      parsed.get("LORA_RADIO") == "SX1262", parsed)
check("the strip length made it through",
      parsed.get("NUM_LEDS") == "24", parsed)
check("the portal password default survives WPA2's minimum",
      len(parsed.get("PORTAL_PASSWORD", "")) >= 8, parsed)

# A retyped value on lamp 2 that matches lamp 1 must be caught NOW,
# while the TTN console is still open — not by apply_env later.
DUPED = SCRIPT[:5] + ["26 0B 11 11", "45" * 16, "67" * 16, ""]
check("a duplicated DevAddr is refused at entry time",
      collect_env(scripted(DUPED)) is None)

# Garbage then a correction: the wizard re-asks instead of giving up.
RETRY = ["", "junk", "260B1111", "01" * 16, "23" * 16,
         "", "260B2222", "45" * 16, "67" * 16, ""]
check("a typo is re-asked, not fatal",
      collect_env(scripted(RETRY)) is not None)


print("\n%d failed\n" % len(failures) if failures else "\nall passed\n")
sys.exit(1 if failures else 0)
