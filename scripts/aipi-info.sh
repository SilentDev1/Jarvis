#!/bin/sh
set -eu

: "${AIPI_PORT:?Set AIPI_PORT to the exact USB serial device, for example /dev/cu.usbmodemXXXX}"
case "$AIPI_PORT" in
  /dev/cu.*|/dev/tty.*) ;;
  *) echo "Refusing non-serial AIPI_PORT: $AIPI_PORT" >&2; exit 2 ;;
esac

if command -v esptool >/dev/null 2>&1; then
  ESPTOOL=esptool
elif python3 -m esptool version >/dev/null 2>&1; then
  ESPTOOL="python3 -m esptool"
else
  echo "esptool is not installed. Install it before connecting the device." >&2
  exit 3
fi

echo "Read-only AiPi probe on $AIPI_PORT"
# shellcheck disable=SC2086
$ESPTOOL --chip esp32s3 --port "$AIPI_PORT" chip-id
# shellcheck disable=SC2086
$ESPTOOL --chip esp32s3 --port "$AIPI_PORT" flash-id
