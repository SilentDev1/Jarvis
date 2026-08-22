#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
[ -x .venv/bin/python ] || { echo "Run ./scripts/setup.sh first"; exit 1; }
mkdir -p run logs
if [ -f run/jarvis.pid ] && kill -0 "$(cat run/jarvis.pid)" 2>/dev/null; then echo "Jarvis Home is already running"; exit 0; fi
. .venv/bin/activate
set -a; [ -f .env ] && . ./.env; set +a
nohup python -m uvicorn jarvis_home.app:app --app-dir src --host "${JARVIS_HOST:-127.0.0.1}" --port "${JARVIS_PORT:-8765}" > logs/server.log 2>&1 &
echo $! > run/jarvis.pid
echo "Jarvis Home started: http://${JARVIS_HOST:-127.0.0.1}:${JARVIS_PORT:-8765}"
