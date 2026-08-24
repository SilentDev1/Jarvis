#!/bin/sh
set -eu
command -v idf.py >/dev/null 2>&1 || { echo "ESP-IDF idf.py is required" >&2; exit 3; }
cd "$(dirname "$0")/../firmware/aipi-jarvis"
idf.py build
