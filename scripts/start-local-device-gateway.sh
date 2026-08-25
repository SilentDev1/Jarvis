#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
. .venv/bin/activate
set -a; [ -f .env ] && . ./.env; set +a
gateway_port=${LOCAL_DEVICE_GATEWAY_PORT:-8767}
mdns_pid=
cleanup() {
  [ -z "$mdns_pid" ] || kill "$mdns_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

gateway_address=${LOCAL_DEVICE_GATEWAY_ADDRESS:-}
if [ -z "$gateway_address" ] && command -v route >/dev/null 2>&1 && command -v ipconfig >/dev/null 2>&1; then
  gateway_interface=$(route -n get default 2>/dev/null | awk '/interface:/{print $2; exit}')
  [ -z "$gateway_interface" ] || gateway_address=$(ipconfig getifaddr "$gateway_interface" 2>/dev/null || true)
fi
if [ -n "$gateway_address" ] && command -v dns-sd >/dev/null 2>&1; then
  dns-sd -P "Jarvis Device Gateway" _jarvis-device._tcp local "$gateway_port" \
    jarvis.local "$gateway_address" >/dev/null 2>&1 &
  mdns_pid=$!
fi

uvicorn jarvis_home.devices.local_gateway:app --app-dir src \
  --host "${LOCAL_DEVICE_GATEWAY_HOST:-0.0.0.0}" \
  --port "$gateway_port" \
  --no-access-log
