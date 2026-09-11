#!/bin/sh
# Suggested Q8B wiring; see docs/q8b-wiring.md before hardware use.
set -eu
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PROJECT_DIR"
E6_PYTHON=${E6_PYTHON:-"$PROJECT_DIR/.venv/bin/python"}
E6_GPIOCHIP=${E6_GPIOCHIP:-/dev/gpiochip4}
exec "$E6_PYTHON" -m e6 \
  --mosi "$E6_GPIOCHIP:88" \
  --clk "$E6_GPIOCHIP:89" \
  --cs "$E6_GPIOCHIP:90" \
  --dc "$E6_GPIOCHIP:92" \
  --rst "$E6_GPIOCHIP:110" \
  --busy "$E6_GPIOCHIP:68" \
  "$@"
