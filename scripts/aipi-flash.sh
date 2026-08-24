#!/bin/sh
set -eu
: "${AIPI_PORT:?Set the exact verified USB serial device}"
: "${AIPI_FACTORY_BACKUP_DIR:?Set the exact timestamped private factory backup directory}"
case "$AIPI_FACTORY_BACKUP_DIR" in */private-backups/aipi/*) ;; *) exit 2 ;; esac
[ -f "$AIPI_FACTORY_BACKUP_DIR/RECOVERY_GATE_PASSED" ] || {
  echo "FLASH BLOCKED: verified recovery gate marker is absent." >&2
  exit 10
}
(cd "$AIPI_FACTORY_BACKUP_DIR" && shasum -a 256 -c SHA256SUMS)
: "${AIPI_ALLOW_CUSTOM_FLASH:?Set AIPI_ALLOW_CUSTOM_FLASH=YES only after reviewing the recovery gate}"
[ "$AIPI_ALLOW_CUSTOM_FLASH" = YES ] || exit 11
command -v idf.py >/dev/null 2>&1 || { echo "ESP-IDF idf.py is required" >&2; exit 3; }
cd "$(dirname "$0")/../firmware/aipi-jarvis"
idf.py -p "$AIPI_PORT" flash
