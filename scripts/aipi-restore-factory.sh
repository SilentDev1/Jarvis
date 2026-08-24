#!/bin/sh
set -eu

: "${AIPI_PORT:?Set the exact verified USB serial device}"
: "${AIPI_FACTORY_BACKUP_DIR:?Set the exact timestamped factory backup directory}"
: "${AIPI_ALLOW_FACTORY_RESTORE:?Set AIPI_ALLOW_FACTORY_RESTORE=YES only when restoration is intentionally required}"
[ "$AIPI_ALLOW_FACTORY_RESTORE" = YES ] || { echo "Restore not authorized" >&2; exit 2; }
case "$AIPI_PORT" in /dev/cu.*|/dev/tty.*) ;; *) exit 2 ;; esac
case "$AIPI_FACTORY_BACKUP_DIR" in backups/aipi-factory/*) ;; *) echo "Invalid backup path" >&2; exit 2 ;; esac
[ -f "$AIPI_FACTORY_BACKUP_DIR/full-flash.bin" ]
[ -f "$AIPI_FACTORY_BACKUP_DIR/SHA256SUMS" ]
(cd "$AIPI_FACTORY_BACKUP_DIR" && shasum -a 256 -c SHA256SUMS)

if command -v esptool >/dev/null 2>&1; then ESPTOOL=esptool
elif python3 -m esptool version >/dev/null 2>&1; then ESPTOOL="python3 -m esptool"
else echo "esptool is required" >&2; exit 3; fi

echo "WARNING: this writes the complete factory image to $AIPI_PORT."
echo "Press Ctrl-C now unless a factory restore is intentionally required."
sleep 10
# shellcheck disable=SC2086
$ESPTOOL --port "$AIPI_PORT" write_flash 0 "$AIPI_FACTORY_BACKUP_DIR/full-flash.bin"
# shellcheck disable=SC2086
$ESPTOOL --port "$AIPI_PORT" verify_flash 0 "$AIPI_FACTORY_BACKUP_DIR/full-flash.bin"
echo "Factory image restored and verified. Reset the device and run the physical checklist."
