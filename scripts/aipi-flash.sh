#!/bin/sh
set -eu
: "${AIPI_PORT:?Set the exact verified USB serial device}"
[ -f backups/aipi-factory/RECOVERY_GATE_PASSED ] || {
  echo "FLASH BLOCKED: verified recovery gate marker is absent." >&2
  exit 10
}
: "${AIPI_ALLOW_CUSTOM_FLASH:?Set AIPI_ALLOW_CUSTOM_FLASH=YES only after reviewing the recovery gate}"
[ "$AIPI_ALLOW_CUSTOM_FLASH" = YES ] || exit 11
command -v idf.py >/dev/null 2>&1 || { echo "ESP-IDF idf.py is required" >&2; exit 3; }
cd "$(dirname "$0")/../firmware/aipi-jarvis"
idf.py -p "$AIPI_PORT" flash
