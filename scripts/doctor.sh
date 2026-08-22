#!/bin/sh
set -u
cd "$(dirname "$0")/.."
pass=0; warn=0
ok(){ echo "PASS $1${2:+: $2}"; pass=$((pass+1)); }
bad(){ echo "WARN $1${2:+: $2}"; warn=$((warn+1)); }
has(){ command -v "$1" >/dev/null 2>&1 && ok "$1" "$(command -v "$1")" || bad "$1" "not found"; }
echo "Jarvis Home doctor"
uname -a
df -h . | tail -1
has python3; has ffmpeg; has ffprobe; has tesseract; has ollama; has docker
[ -x .venv/bin/python ] && ok "Python environment" || bad "Python environment" "run ./scripts/setup.sh"
if [ -f .env ]; then
  ok ".env exists"
  set -a; . ./.env; set +a
else
  bad ".env" "copy .env.example and configure it"
fi
if curl -fsS --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  ok "Ollama API"
  if ollama list 2>/dev/null | awk 'NR>1 {print $1}' | grep -Fx "${OLLAMA_MODEL:-qwen3.5:4b}" >/dev/null; then ok "Ollama model" "${OLLAMA_MODEL:-qwen3.5:4b}"; else bad "Ollama model" "${OLLAMA_MODEL:-qwen3.5:4b} not installed"; fi
else bad "Ollama API" "unavailable"; fi
if .venv/bin/python -c 'import cv2; print(cv2.__version__)' >/dev/null 2>&1; then ok "OpenCV/vision runtime"; else bad "OpenCV/vision runtime" "install .[vision]"; fi
if .venv/bin/python -c 'import pytesseract' >/dev/null 2>&1 && tesseract --version >/dev/null 2>&1; then ok "OCR provider"; else bad "OCR provider"; fi
if PYTHONPATH=src .venv/bin/python -c 'from jarvis_home.persistence import Store; from jarvis_home.config import get_settings; s=Store(get_settings().data_dir/"jarvis.db"); s.init()' 2>/dev/null; then ok "Database"; else bad "Database"; fi
if [ "${CAMERA_MODE:-test}" = live ]; then
  if [ -n "${CAMERA_HOST:-}" ] || [ -n "${CAMERA_RTSP_URL_MAIN:-}" ]; then ok "Tapo configuration"; else bad "Tapo configuration" "run configure-tapo.sh"; fi
  ./scripts/test-camera.sh || bad "Live camera validation"
else ok "Camera simulator mode"; fi
if curl -fsS --max-time 2 "http://${JARVIS_HOST:-127.0.0.1}:${JARVIS_PORT:-8765}/health" >/dev/null 2>&1; then
  ok "Dashboard/API" "http://${JARVIS_HOST:-127.0.0.1}:${JARVIS_PORT:-8765}"
  curl -fsS --max-time 2 "http://${JARVIS_HOST:-127.0.0.1}:${JARVIS_PORT:-8765}/health/database" >/dev/null 2>&1 && ok "Database health API" || bad "Database health API"
else bad "Dashboard/API" "not running"; fi
free_kb=$(df -k . | awk 'NR==2 {print $4}'); [ "$free_kb" -gt 5242880 ] && ok "Disk space" "more than 5 GiB free" || bad "Disk space" "low"
echo "Summary: $pass passed, $warn warnings"
[ "$warn" -eq 0 ]
