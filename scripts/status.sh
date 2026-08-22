#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ -f run/jarvis.pid ] && kill -0 "$(cat run/jarvis.pid)" 2>/dev/null; then echo "RUNNING pid=$(cat run/jarvis.pid)"; curl -fsS "http://${JARVIS_HOST:-127.0.0.1}:${JARVIS_PORT:-8765}/health"; echo; else echo "STOPPED"; exit 1; fi

