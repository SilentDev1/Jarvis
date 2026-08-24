#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
. .venv/bin/activate
set -a; [ -f .env ] && . ./.env; set +a
exec uvicorn jarvis_home.devices.mcp_gateway:app --app-dir src \
  --host "${DEVICE_GATEWAY_HOST:-127.0.0.1}" \
  --port "${DEVICE_GATEWAY_PORT:-8766}"
