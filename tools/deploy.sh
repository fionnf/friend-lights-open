#!/usr/bin/env bash
# Update the code on a lamp that is already set up.
#
#   ./tools/deploy.sh --lamp 1 [/dev/ttyACM0]
#
# A wrapper, deliberately. This used to be a second implementation of
# the install procedure in bash, and it drifted from the Python one in
# four separate ways — a missing directory in the copy list, a stale
# mpremote invocation, a board left with its watchdog stretched, and
# quoting that broke on any path containing an apostrophe. One
# procedure, one place, one set of bugs to fix.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

LAMP=1
if [ "${1:-}" = "--lamp" ]; then
  if [ -z "${2:-}" ]; then echo "--lamp needs a number (1 or 2)" >&2; exit 1; fi
  LAMP="$2"; shift 2
fi

ARGS=(--deploy --lamp "$LAMP")
[ -n "${1:-}" ] && ARGS+=(--port "$1")

exec python3 "$ROOT/tools/install.py" "${ARGS[@]}"
