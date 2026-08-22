#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ -f run/jarvis.pid ]; then pid=$(cat run/jarvis.pid); kill "$pid" 2>/dev/null || true; rm -f run/jarvis.pid; echo "Jarvis Home stopped"; else echo "Jarvis Home is not running"; fi

