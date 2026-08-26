#!/bin/sh
# Supervises the local AiPi device gateway and its mDNS service advertisement.
#
# This script owns the whole local-device-gateway lifecycle: the application
# process, the discovery name the AiPi resolves, duplicate-instance protection,
# and cleanup. Never start the gateway with a bare `uvicorn` command. Doing so
# leaves the discovery name unpublished, the device cannot resolve Jarvis, it
# never reaches ONLINE, and the speaker appears broken even though the codec is
# fine. See docs/AIPI_SPEAKER_VALIDATION.md.
set -eu
cd "$(dirname "$0")/.."
[ -x .venv/bin/python ] || { echo "Run ./scripts/setup.sh first" >&2; exit 1; }
mkdir -p run logs
. .venv/bin/activate
set -a; [ -f .env ] && . ./.env; set +a

gateway_port=${LOCAL_DEVICE_GATEWAY_PORT:-8767}
gateway_host=${LOCAL_DEVICE_GATEWAY_HOST:-0.0.0.0}
discovery_host=${LOCAL_DEVICE_GATEWAY_DISCOVERY_HOST:-jarvis.local}
lock_dir=run/local-device-gateway.lock
mdns_pid=
app_pid=

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) local-device-gateway: $*"; }

# Single-instance protection. `mkdir` is atomic, so two concurrent starts cannot
# both win. A stale lock from a killed supervisor is reclaimed.
if ! mkdir "$lock_dir" 2>/dev/null; then
  holder=$(cat "$lock_dir/pid" 2>/dev/null || echo "")
  if [ -n "$holder" ] && kill -0 "$holder" 2>/dev/null; then
    log "already running under pid=$holder; not starting a second instance"
    exit 0
  fi
  log "reclaiming stale lock from pid=${holder:-unknown}"
  rm -rf "$lock_dir"
  mkdir "$lock_dir"
fi
echo $$ > "$lock_dir/pid"
# Publish the supervisor pid where start.sh, stop.sh and status.sh look. When a
# second start is refused by the lock, start.sh would otherwise record the
# refused shell's pid and status.sh would report the gateway STOPPED while it
# was running.
echo $$ > run/local-device-gateway.pid

cleanup() {
  status=$?
  trap - EXIT INT TERM
  [ -z "$mdns_pid" ] || kill "$mdns_pid" 2>/dev/null || true
  [ -z "$app_pid" ] || kill "$app_pid" 2>/dev/null || true
  # Reap children so the supervisor never exits while they are still holding
  # the port or the discovery name. Escalate if they ignore SIGTERM.
  waited=0
  while [ -n "$app_pid" ] && kill -0 "$app_pid" 2>/dev/null && [ "$waited" -lt 10 ]; do
    sleep 1
    waited=$((waited + 1))
  done
  [ -z "$app_pid" ] || kill -9 "$app_pid" 2>/dev/null || true
  [ -z "$mdns_pid" ] || kill -9 "$mdns_pid" 2>/dev/null || true
  rm -rf "$lock_dir"
  # Only clear the shared pidfile if it still refers to this supervisor.
  [ "$(cat run/local-device-gateway.pid 2>/dev/null)" = "$$" ] &&
    rm -f run/local-device-gateway.pid
  log "stopped"
  exit $status
}
trap cleanup EXIT INT TERM

# Refuse to fight an unmanaged listener (for example a bare `uvicorn`) rather
# than starting an application process that will fail to bind.
if command -v lsof >/dev/null 2>&1; then
  # Test actual output, not exit status: lsof's status is not a reliable
  # "found nothing" signal once warnings are suppressed.
  listeners=$(lsof -nP -iTCP:"$gateway_port" -sTCP:LISTEN -t 2>/dev/null || true)
  if [ -n "$listeners" ]; then
    log "port $gateway_port is already in use by unmanaged pid(s): $listeners"
    log "stop them first, then start the gateway through this script"
    exit 1
  fi
fi

resolve_lan_address() {
  [ -z "${LOCAL_DEVICE_GATEWAY_ADDRESS:-}" ] || { echo "$LOCAL_DEVICE_GATEWAY_ADDRESS"; return; }
  command -v route >/dev/null 2>&1 || return 0
  command -v ipconfig >/dev/null 2>&1 || return 0
  interface=$(route -n get default 2>/dev/null | awk '/interface:/{print $2; exit}')
  [ -n "$interface" ] || return 0
  ipconfig getifaddr "$interface" 2>/dev/null || true
}

start_mdns() {
  mdns_pid=
  command -v dns-sd >/dev/null 2>&1 || { log "dns-sd unavailable; discovery not published"; return; }
  address=$(resolve_lan_address)
  if [ -z "$address" ]; then
    log "LAN address undetermined; discovery not published"
    return
  fi
  dns-sd -P "Jarvis Device Gateway" _jarvis-device._tcp local "$gateway_port" \
    "$discovery_host" "$address" >/dev/null 2>&1 &
  mdns_pid=$!
  log "advertising $discovery_host -> $address:$gateway_port pid=$mdns_pid"
}

start_mdns
python -m uvicorn jarvis_home.devices.local_gateway:app --app-dir src \
  --host "$gateway_host" --port "$gateway_port" --no-access-log &
app_pid=$!
log "gateway pid=$app_pid on $gateway_host:$gateway_port supervisor pid=$$"

# Supervise. The advertisement is restarted if it dies, because losing it
# silently breaks device discovery without stopping the gateway itself.
while kill -0 "$app_pid" 2>/dev/null; do
  if [ -n "$mdns_pid" ] && ! kill -0 "$mdns_pid" 2>/dev/null; then
    log "discovery advertisement died; restarting it"
    start_mdns
  fi
  # Sleep in the background and wait on it. A blocking foreground `sleep` would
  # defer the shutdown trap until it expired, which orphans the children and
  # leaks the lock; `wait` is interrupted by the signal immediately.
  sleep 5 &
  wait $! 2>/dev/null || true
done
wait "$app_pid" 2>/dev/null || true
