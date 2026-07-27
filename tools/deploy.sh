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
    echo "  python3 tools/make_config.py --lamp $LAMP" >&2
    exit 1
  fi
else
  CONFIG="$ROOT/firmware/config.py"
  if [ ! -f "$CONFIG" ]; then
    echo "firmware/config.py is missing." >&2
    echo "  python3 tools/make_config.py        (recommended)" >&2
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

mp mkdir :lamp     2>/dev/null || true
mp mkdir :lamp/net 2>/dev/null || true
mp mkdir :lamp/www 2>/dev/null || true

mp cp "$ROOT/firmware/main.py"   :
# Always lands on the board as config.py, whichever file it came from.
mp cp "$CONFIG" :config.py
for f in "$ROOT"/firmware/lamp/*.py;     do mp cp "$f" :lamp/;     done
for f in "$ROOT"/firmware/lamp/net/*.py; do mp cp "$f" :lamp/net/; done
mp cp "$ROOT/firmware/lamp/www/index.html" :lamp/www/
# Handy to have on the board when a radio will not talk.
mp cp "$ROOT/tools/radio_check.py" : 2>/dev/null || true

echo
echo "done. watch it boot with:"
echo "  mpremote connect $PORT repl"
