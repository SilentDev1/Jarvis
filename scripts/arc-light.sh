#!/bin/sh
# Control the AiPi arc reactor light.
#
# Wraps the admin-gated endpoint so ordinary use never involves handling a
# token by hand. Brightness and quiet hours are settings, not firmware
# constants, so nothing here needs a rebuild or a reflash.
#
#   ./scripts/arc-light.sh off
#   ./scripts/arc-light.sh on              # normal brightness
#   ./scripts/arc-light.sh dim             # low
#   ./scripts/arc-light.sh bright          # high
#   ./scripts/arc-light.sh on 20 60        # custom idle and active percent
#   ./scripts/arc-light.sh status
set -eu
cd "$(dirname "$0")/.."
[ -f .env ] || { echo "no .env found" >&2; exit 1; }
set -a; . ./.env; set +a

GATEWAY="http://127.0.0.1:${LOCAL_DEVICE_GATEWAY_PORT:-8767}"
TOKEN="${JARVIS_ADMIN_TOKEN:?JARVIS_ADMIN_TOKEN is not set in .env}"

post() {
  curl -s -m 10 -X POST "$GATEWAY/internal/arc-light" \
    -H "x-jarvis-admin-token: $TOKEN" \
    -H "content-type: application/json" \
    -d "$1"
  echo
}

case "${1:-status}" in
  off)    post '{"enabled":false}' ;;
  dim)    post '{"enabled":true,"idleBrightness":6,"activeBrightness":20}' ;;
  on)     post "{\"enabled\":true,\"idleBrightness\":${2:-15},\"activeBrightness\":${3:-55}}" ;;
  bright) post '{"enabled":true,"idleBrightness":30,"activeBrightness":75}' ;;
  status)
    curl -s -m 10 "$GATEWAY/health" | "$PWD/.venv/bin/python" -c "
import sys, json
d = json.load(sys.stdin)['device']
print('firmware :', d['firmware_version'])
print('available:', d['arc_light_available'])
print('enabled  :', d['arc_light_enabled'])
"
    ;;
  *)
    echo "usage: $0 [off|dim|on [idle] [active]|bright|status]" >&2
    exit 2
    ;;
esac
