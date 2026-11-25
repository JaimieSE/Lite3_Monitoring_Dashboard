#!/usr/bin/env bash
# Start the READ-ONLY telemetry bridge on the NUC (run in tmux/screen).
# Binds to 127.0.0.1 only; reach it from the Mac via scripts/mac/start-robot.sh.
# Runs at low CPU priority. Stopping it (Ctrl-C) has no effect on the robot.
#   start-bridge.sh            start (refuses if a bridge already runs)
#   start-bridge.sh --restart  stop OUR running bridge first (e.g. after git pull), then start
set -euo pipefail
RESTART=0
ARGS=()
for a in "$@"; do
  if [ "$a" = "--restart" ]; then RESTART=1; else ARGS+=("$a"); fi
done
PORT="${LITE3_PORT:-8765}"

port_busy() {
  python3 -c "import socket,sys; s=socket.socket(); s.settimeout(0.5); sys.exit(0 if s.connect_ex(('127.0.0.1', $PORT)) == 0 else 1)"
}
our_bridge_pids() { pgrep -f "python.* -m lite3_bridge" || true; }

if port_busy; then
  PIDS="$(our_bridge_pids)"
  if [ -n "$PIDS" ] && [ "$RESTART" = 1 ]; then
    echo "Stopping the running lite3_bridge (PID $(echo $PIDS)) - the robot is not affected"
    kill $PIDS 2>/dev/null || true
    for _ in $(seq 1 20); do port_busy || break; sleep 0.5; done
    port_busy && { kill -9 $PIDS 2>/dev/null || true; sleep 1; }
  elif [ -n "$PIDS" ]; then
    echo "A lite3_bridge is ALREADY RUNNING (PID $(echo $PIDS)) - nothing to do."
    echo "  To replace it with the current code (e.g. after git pull):"
    echo "    $0 --restart"
    echo "  To look at it:  tmux attach -t monitor"
    exit 0
  else
    echo "Port $PORT is used by ANOTHER program (not lite3_bridge):" >&2
    ss -ltnp 2>/dev/null | grep ":$PORT " >&2 || echo "  (run: ss -ltnp | grep :$PORT)" >&2
    echo "Do not stop it if it is not yours (e.g. another team's container). Instead run the" >&2
    echo "bridge on another port: add 'server: {port: 8775}' to bridge/config/local.yaml," >&2
    echo "set REMOTE_PORT=8775 in each laptop's robot.env, and start with LITE3_PORT=8775." >&2
    exit 1
  fi
fi
DIR="$(cd "$(dirname "$0")/../.." && pwd)"
LITE3_WS="${LITE3_WS:-$HOME/lite3_ws}"

set +u
source /opt/ros/humble/setup.bash
# Source the robot workspace read-only so custom message types can be imported.
if [ -f "$LITE3_WS/install/setup.bash" ]; then source "$LITE3_WS/install/setup.bash"; fi
set -u

echo "hostname=$(hostname) ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-unset(0)} RMW=${RMW_IMPLEMENTATION:-default}"
# Robot profile (config/<profile>.yaml) then optional NUC-local overrides.
PROFILE="${LITE3_PROFILE:-group8}"
CONFIG_ARGS=(--config "config/$PROFILE.yaml")
[ -f "$DIR/bridge/config/local.yaml" ] && CONFIG_ARGS+=(--config "config/local.yaml")
cd "$DIR/bridge"
[ -f "config/$PROFILE.yaml" ] || { echo "No profile config/$PROFILE.yaml" >&2; exit 1; }
echo "profile=$PROFILE"
exec nice -n 10 "$DIR/.venv/bin/python" -m lite3_bridge "${CONFIG_ARGS[@]}" ${ARGS[@]+"${ARGS[@]}"}
