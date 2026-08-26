#!/bin/sh
# Installs the Jarvis launch agents so normal operation survives a reboot.
#
# Installs the local AiPi device gateway, which must be running and advertising
# its discovery name before the physical terminal can reach ONLINE.
#
#   ./scripts/install-launch-agents.sh             install and start
#   ./scripts/install-launch-agents.sh --uninstall stop and remove
#
# macOS note. If this repository lives under a TCC-protected directory
# (~/Documents, ~/Desktop, ~/Downloads), a launchd job cannot read it until the
# owner grants Full Disk Access. TCC attributes a shell script's access to its
# interpreter, so granting it to the supervisor script would really mean
# granting it to /bin/sh, and therefore to every shell script on the machine.
# This installer instead compiles a dedicated launcher binary whose only
# action is to exec the supervisor, so the grant applies to one purpose-built
# executable. The installer reports whether the grant is required.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
LABEL=com.jarvishome.local-device-gateway
TEMPLATE="$ROOT/deploy/mac/$LABEL.plist"
TARGET_DIR="$HOME/Library/LaunchAgents"
TARGET="$TARGET_DIR/$LABEL.plist"
SUPPORT_DIR="$HOME/Library/Application Support/JarvisHome"
LAUNCHER="$SUPPORT_DIR/jarvis-gateway-launcher"
LOG_DIR="$HOME/Library/Logs/JarvisHome"
DOMAIN="gui/$(id -u)"

[ "$(uname -s)" = Darwin ] || { echo "launch agents are macOS-only" >&2; exit 1; }

unload() { launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true; }

if [ "${1:-}" = --uninstall ]; then
  unload
  rm -f "$TARGET" "$LAUNCHER"
  echo "uninstalled $LABEL"
  echo "If you granted Full Disk Access to the launcher, remove it in"
  echo "System Settings > Privacy & Security > Full Disk Access."
  exit 0
fi

[ -f "$TEMPLATE" ] || { echo "missing template: $TEMPLATE" >&2; exit 1; }
command -v clang >/dev/null 2>&1 || {
  echo "clang is required to build the launcher; install Xcode command line tools" >&2
  exit 1
}
mkdir -p "$TARGET_DIR" "$SUPPORT_DIR" "$LOG_DIR"

# Build the launcher with the supervisor path baked in, so it takes no
# arguments and cannot be repurposed to run anything else.
clang -Os -Wall -Wextra -Werror \
  -DJARVIS_GATEWAY_SCRIPT="\"$ROOT/scripts/start-local-device-gateway.sh\"" \
  -o "$LAUNCHER" "$ROOT/deploy/mac/launcher/jarvis_gateway_launcher.c"
chmod 755 "$LAUNCHER"

sed -e "s#__LAUNCHER__#$LAUNCHER#g" -e "s#__LOGDIR__#$LOG_DIR#g" \
  "$TEMPLATE" > "$TARGET"
plutil -lint "$TARGET" >/dev/null

unload
launchctl bootstrap "$DOMAIN" "$TARGET"
launchctl enable "$DOMAIN/$LABEL"

echo "installed $LABEL"
echo "  launcher: $LAUNCHER"
echo "  plist:    $TARGET"
echo "  logs:     $LOG_DIR/local-device-gateway.log"

# Detect whether TCC will block the agent, and say so plainly rather than
# leaving a silently dead gateway.
case "$ROOT" in
  "$HOME"/Documents/*|"$HOME"/Desktop/*|"$HOME"/Downloads/*)
    echo
    echo "ACTION REQUIRED: this repository is inside a macOS protected folder."
    echo "Grant Full Disk Access to the launcher, then re-run this script:"
    echo "  System Settings > Privacy & Security > Full Disk Access > +"
    echo "  Choose: $LAUNCHER"
    echo "  (Shift-Cmd-G in the file picker to paste that path.)"
    ;;
esac
