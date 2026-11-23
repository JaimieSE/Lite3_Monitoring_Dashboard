#!/usr/bin/env bash
# Start the READ-ONLY telemetry bridge on the NUC (run in tmux/screen).
# Binds to 127.0.0.1 only; reach it from the Mac via scripts/mac/start-robot.sh.
# Runs at low CPU priority. Stopping it (Ctrl-C) has no effect on the robot.
set -euo pipefail
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
exec nice -n 10 "$DIR/.venv/bin/python" -m lite3_bridge "${CONFIG_ARGS[@]}" "$@"
