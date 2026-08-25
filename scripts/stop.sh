#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ -f run/jarvis.pid ]; then pid=$(cat run/jarvis.pid); kill "$pid" 2>/dev/null || true; rm -f run/jarvis.pid; echo "Jarvis Home stopped"; else echo "Jarvis Home is not running"; fi
if [ -f run/device-gateway.pid ]; then pid=$(cat run/device-gateway.pid); kill "$pid" 2>/dev/null || true; rm -f run/device-gateway.pid; echo "Device gateway stopped"; else echo "Device gateway is not running"; fi
if [ -f run/local-device-gateway.pid ]; then pid=$(cat run/local-device-gateway.pid); kill "$pid" 2>/dev/null || true; rm -f run/local-device-gateway.pid; echo "Local AiPi gateway stopped"; else echo "Local AiPi gateway is not running"; fi
if [ -f run/cloudflared.pid ]; then pid=$(cat run/cloudflared.pid); kill "$pid" 2>/dev/null || true; rm -f run/cloudflared.pid; echo "Cloudflare tunnel stopped"; fi
