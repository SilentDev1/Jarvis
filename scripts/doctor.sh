#!/bin/sh
set -u
cd "$(dirname "$0")/.."
pass=0;warn=0
check(){ if command -v "$1" >/dev/null 2>&1; then echo "OK   $1: $(command -v "$1")"; pass=$((pass+1)); else echo "WARN $1: not found"; warn=$((warn+1)); fi; }
echo "Jarvis Home doctor"; uname -a; df -h . | tail -1
check python3; check ffmpeg; check ollama; check docker; check tesseract
[ -x .venv/bin/python ] && echo "OK   Python environment" || echo "WARN Run ./scripts/setup.sh"
[ -f .env ] && echo "OK   .env exists" || echo "WARN Copy .env.example to .env"
if curl -fsS --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then echo "OK   Ollama API"; else echo "WARN Ollama API unavailable"; fi
if [ "${CAMERA_MODE:-test}" = live ]; then ffprobe -v error -rtsp_transport tcp -i "${CAMERA_RTSP_URL_SUB:-}" -show_entries stream=codec_name -of default=nw=1 2>/dev/null && echo "OK   Camera RTSP" || echo "WARN Camera RTSP unavailable"; else echo "OK   Camera simulator mode"; fi
echo "Database and API are verified by ./scripts/test.sh and /health/database."

