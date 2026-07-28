#!/usr/bin/env bash
# Copy the firmware onto a XIAO ESP32S3.
#   ./tools/deploy.sh [port]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

LAMP=""
if [ "${1:-}" = "--lamp" ]; then
  LAMP="$2"; shift 2
fi
PORT="${1:-/dev/ttyACM0}"

# With --lamp N, deploy that lamp's prepared config. Without it, fall back
# to a single firmware/config.py.
if [ -n "$LAMP" ]; then
  CONFIG="$ROOT/firmware/config.lamp$LAMP.py"
  if [ ! -f "$CONFIG" ]; then
    echo "No config for lamp $LAMP." >&2
    echo "  python3 tools/apply_env.py          (writes both from .env)" >&2
    exit 1
  fi
else
  CONFIG="$ROOT/firmware/config.py"
  if [ ! -f "$CONFIG" ]; then
    echo "firmware/config.py is missing." >&2
    echo "  python3 tools/apply_env.py          (recommended)" >&2
    echo "  cp firmware/config.example.py firmware/config.py" >&2
    exit 1
  fi
fi
echo "config: $(basename "$CONFIG")"

# Never load firmware onto a lamp without running the tests: a LoRa-only
# lamp has no over-the-air recovery, so a boot loop means USB or the post.
echo "== tests =="
for t in "$ROOT"/tests/test_*.py; do
  echo "-- $(basename "$t")"
  python3 "$t" > /dev/null || { echo "FAILED: $t — not deploying" >&2; exit 1; }
done
echo "all passed"

echo
echo "== deploying to $PORT =="
mp() { mpremote connect "$PORT" "$@"; }

# A lamp that has run before has an 8 s hardware watchdog armed, and on
# the ESP32 a watchdog cannot be stopped — only stretched. Left alone it
# resets the board partway through the copy below, and a partial copy of
# firmware with no over-the-air recovery is the one way this project can
# genuinely brick a lamp. Harmless on a fresh board.
mp exec "from machine import WDT
WDT(timeout=600000)" 2>/dev/null || true

# What to copy comes from install.py, which derives it by WALKING
# firmware/ — one source of truth for both tools. This used to be a
# hand-written list of globs here, and it silently missed
# lamp/net/mp_lora/ the day that directory was added: the lamp booted,
# fell back to the other driver, and said nothing about why.
PLAN=$(python3 -c "
import sys; sys.path.insert(0, '$ROOT/tools')
from install import device_files, remote_dirs
files = device_files('$ROOT')
for d in remote_dirs(files):
    print('D\t' + d)
for local, remote in files:
    print('F\t%s\t%s' % (local, remote))
") || { echo "could not work out what to copy" >&2; exit 1; }

# Always lands on the board as config.py, whichever file it came from.
mp cp "$CONFIG" :config.py

while IFS=$'\t' read -r kind a b; do
  case "$kind" in
    D) mp mkdir "$a" 2>/dev/null || true ;;
    F) mp cp "$a" "$b" || { echo "FAILED copying $a" >&2; exit 1; } ;;
  esac
done <<< "$PLAN"

echo
echo "done. watch it boot with:"
echo "  mpremote connect $PORT repl"
