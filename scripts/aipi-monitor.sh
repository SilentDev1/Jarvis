#!/bin/sh
set -eu
: "${AIPI_PORT:?Set the exact verified USB serial device}"
command -v idf.py >/dev/null 2>&1 || { echo "ESP-IDF idf.py is required" >&2; exit 3; }
cd "$(dirname "$0")/../firmware/aipi-jarvis"
idf.py -p "$AIPI_PORT" monitor
