#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
[ -x .venv/bin/python ] || { echo "Run ./scripts/setup.sh first"; exit 1; }
mkdir -p run logs
. .venv/bin/activate
set -a; [ -f .env ] && . ./.env; set +a
if command -v ollama >/dev/null 2>&1 && ! curl -fsS --max-time 2 "${OLLAMA_URL:-http://127.0.0.1:11434}/api/tags" >/dev/null 2>&1; then
  nohup ollama serve > logs/ollama.log 2>&1 &
  sleep 1
fi
if ! [ -f run/jarvis.pid ] || ! kill -0 "$(cat run/jarvis.pid)" 2>/dev/null; then
  nohup python -m uvicorn jarvis_home.app:app --app-dir src --host "${JARVIS_HOST:-127.0.0.1}" --port "${JARVIS_PORT:-8765}" > logs/server.log 2>&1 &
  echo $! > run/jarvis.pid
fi
if ! [ -f run/device-gateway.pid ] || ! kill -0 "$(cat run/device-gateway.pid)" 2>/dev/null; then
  nohup python -m uvicorn jarvis_home.devices.mcp_gateway:app --app-dir src --host "${DEVICE_GATEWAY_HOST:-127.0.0.1}" --port "${DEVICE_GATEWAY_PORT:-8766}" > logs/device-gateway.log 2>&1 &
  echo $! > run/device-gateway.pid
fi
if ! [ -f run/local-device-gateway.pid ] || ! kill -0 "$(cat run/local-device-gateway.pid)" 2>/dev/null; then
  nohup ./scripts/start-local-device-gateway.sh > logs/local-device-gateway.log 2>&1 &
  echo $! > run/local-device-gateway.pid
fi
if [ -n "${CLOUDFLARE_TUNNEL_CONFIG:-}" ] && command -v cloudflared >/dev/null 2>&1; then
  if ! [ -f run/cloudflared.pid ] || ! kill -0 "$(cat run/cloudflared.pid)" 2>/dev/null; then
    nohup cloudflared tunnel --config "$CLOUDFLARE_TUNNEL_CONFIG" run > logs/cloudflared.log 2>&1 &
    echo $! > run/cloudflared.pid
  fi
fi
echo "Jarvis Home started: http://${JARVIS_HOST:-127.0.0.1}:${JARVIS_PORT:-8765}"
echo "Device gateway started: http://${DEVICE_GATEWAY_HOST:-127.0.0.1}:${DEVICE_GATEWAY_PORT:-8766}/mcp"
echo "Local AiPi gateway started on LAN port ${LOCAL_DEVICE_GATEWAY_PORT:-8767}"
[ -z "${CLOUDFLARE_TUNNEL_CONFIG:-}" ] || echo "Named Cloudflare tunnel startup configured"
