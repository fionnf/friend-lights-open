#!/usr/bin/env bash
# Copy the firmware onto a XIAO ESP32S3.
#   ./tools/deploy.sh [port]
set -euo pipefail

PORT="${1:-/dev/ttyACM0}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ ! -f "$ROOT/firmware/config.py" ]; then
  echo "firmware/config.py is missing." >&2
  echo "  cp firmware/config.example.py firmware/config.py" >&2
  echo "then set LAMP_ID and your TTN keys. See the README." >&2
  exit 1
fi

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

mp cp "$ROOT/firmware/main.py"   :
mp cp "$ROOT/firmware/config.py" :
for f in "$ROOT"/firmware/lamp/*.py;     do mp cp "$f" :lamp/;     done
for f in "$ROOT"/firmware/lamp/net/*.py; do mp cp "$f" :lamp/net/; done

echo
echo "done. watch it boot with:"
echo "  mpremote connect $PORT repl"
