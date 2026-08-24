#!/bin/sh
set -eu

: "${AIPI_PORT:?Set the exact verified USB serial device}"
: "${AIPI_FACTORY_BACKUP_DIR:?Set the exact timestamped private factory backup directory}"
: "${AIPI_EXPECTED_MAC:?Set the MAC recorded in the private device-info.txt}"
case "$AIPI_PORT" in /dev/cu.*|/dev/tty.*) ;; *) exit 2 ;; esac
case "$AIPI_FACTORY_BACKUP_DIR" in */private-backups/aipi/*) ;; *) echo "Invalid private backup path" >&2; exit 2 ;; esac
[ -f "$AIPI_FACTORY_BACKUP_DIR/full-flash.bin" ]
[ -f "$AIPI_FACTORY_BACKUP_DIR/SHA256SUMS" ]
[ "$(stat -f '%z' "$AIPI_FACTORY_BACKUP_DIR/full-flash.bin")" = 16777216 ]
(cd "$AIPI_FACTORY_BACKUP_DIR" && shasum -a 256 -c SHA256SUMS)

if command -v esptool >/dev/null 2>&1; then ESPTOOL=esptool
elif python3 -m esptool version >/dev/null 2>&1; then ESPTOOL="python3 -m esptool"
else echo "esptool is required" >&2; exit 3; fi

IDENTITY=$($ESPTOOL --chip esp32s3 --port "$AIPI_PORT" chip-id)
echo "$IDENTITY" | grep -q "ESP32-S3"
echo "$IDENTITY" | grep -Fq "$AIPI_EXPECTED_MAC"

if [ "${AIPI_RESTORE_DRY_RUN:-NO}" = YES ]; then
  echo "DRY RUN PASS: hashes, 16MB length, ESP32-S3 identity, MAC, port, and restore base 0x0 verified."
  exit 0
fi

: "${AIPI_ALLOW_FACTORY_RESTORE:?Set AIPI_ALLOW_FACTORY_RESTORE=RESTORE_FACTORY_IMAGE only when restoration is intentionally required}"
[ "$AIPI_ALLOW_FACTORY_RESTORE" = RESTORE_FACTORY_IMAGE ] || { echo "Restore not authorized" >&2; exit 2; }
echo "WARNING: this writes the complete factory image to $AIPI_PORT."
echo "Press Ctrl-C now unless a factory restore is intentionally required."
sleep 10
# shellcheck disable=SC2086
$ESPTOOL --chip esp32s3 --port "$AIPI_PORT" write-flash 0x0 "$AIPI_FACTORY_BACKUP_DIR/full-flash.bin"
# shellcheck disable=SC2086
$ESPTOOL --chip esp32s3 --port "$AIPI_PORT" verify-flash 0x0 "$AIPI_FACTORY_BACKUP_DIR/full-flash.bin"
echo "Factory image restored and verified. Reset the device and run the physical checklist."
