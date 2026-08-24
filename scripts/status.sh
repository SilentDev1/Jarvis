#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
set -a; [ -f .env ] && . ./.env; set +a
if [ -f run/jarvis.pid ] && kill -0 "$(cat run/jarvis.pid)" 2>/dev/null; then echo "RUNNING pid=$(cat run/jarvis.pid)"; curl -fsS "http://${JARVIS_HOST:-127.0.0.1}:${JARVIS_PORT:-8765}/health"; echo; else echo "STOPPED"; exit 1; fi
if [ -f run/device-gateway.pid ] && kill -0 "$(cat run/device-gateway.pid)" 2>/dev/null; then echo "DEVICE GATEWAY RUNNING pid=$(cat run/device-gateway.pid)"; else echo "DEVICE GATEWAY STOPPED"; exit 1; fi
if [ -n "${CLOUDFLARE_TUNNEL_CONFIG:-}" ]; then
  if [ -f run/cloudflared.pid ] && kill -0 "$(cat run/cloudflared.pid)" 2>/dev/null; then echo "CLOUDFLARE TUNNEL RUNNING pid=$(cat run/cloudflared.pid)"; else echo "CLOUDFLARE TUNNEL STOPPED"; exit 1; fi
fi
