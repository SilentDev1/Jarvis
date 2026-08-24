#!/bin/sh
set -eu

: "${AIPI_PORT:?Set AIPI_PORT to the exact verified USB serial device}"
: "${AIPI_FLASH_SIZE_BYTES:?Set the byte count reported by aipi-info.sh; do not guess}"
case "$AIPI_PORT" in /dev/cu.*|/dev/tty.*) ;; *) exit 2 ;; esac
case "$AIPI_FLASH_SIZE_BYTES" in *[!0-9]*|'') exit 2 ;; esac
[ "$AIPI_FLASH_SIZE_BYTES" -ge 4194304 ] || { echo "Implausible flash size" >&2; exit 2; }

if command -v esptool >/dev/null 2>&1; then
  ESPTOOL=esptool
elif python3 -m esptool version >/dev/null 2>&1; then
  ESPTOOL="python3 -m esptool"
else
  echo "esptool is required" >&2; exit 3
fi

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
DEST="backups/aipi-factory/$STAMP"
mkdir -p "$DEST"
FIRST="$DEST/full-flash.read1.bin"
SECOND="$DEST/full-flash.read2.bin"

echo "Reading full flash twice. Nothing will be erased or written."
# shellcheck disable=SC2086
$ESPTOOL --chip esp32s3 --port "$AIPI_PORT" read-flash 0 "$AIPI_FLASH_SIZE_BYTES" "$FIRST"
# shellcheck disable=SC2086
$ESPTOOL --chip esp32s3 --port "$AIPI_PORT" read-flash 0 "$AIPI_FLASH_SIZE_BYTES" "$SECOND"
cmp "$FIRST" "$SECOND"
mv "$FIRST" "$DEST/full-flash.bin"
rm "$SECOND"
[ "$(wc -c < "$DEST/full-flash.bin" | tr -d ' ')" = "$AIPI_FLASH_SIZE_BYTES" ]
(cd "$DEST" && shasum -a 256 full-flash.bin > SHA256SUMS)

{
  echo "port=$AIPI_PORT"
  echo "flash_size_bytes=$AIPI_FLASH_SIZE_BYTES"
  echo "read_utc=$STAMP"
  echo "status=FULL_FLASH_DOUBLE_READ_MATCH"
  echo "partition_status=NOT_YET_PARSED"
} > "$DEST/device-info.txt"

echo "Full flash double-read verified at $DEST"
echo "FLASH GATE REMAINS CLOSED until the partition map and required partition images are verified."
