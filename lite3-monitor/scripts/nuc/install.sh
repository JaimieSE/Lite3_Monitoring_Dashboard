#!/usr/bin/env bash
# NUC one-time setup (run ON the NUC, only after approval).
# Creates an isolated venv inside the lite3-monitor directory that can still see
# the system rclpy (--system-site-packages). No apt packages, no sudo, no
# changes to /opt/ros or lite3_ws.
set -euo pipefail
DIR="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="$DIR/.venv"
echo "Will create $VENV and pip-install: $(grep -v '^#' "$DIR/bridge/requirements.txt" | xargs)"
read -r -p "Proceed? [y/N] " a; [[ "$a" =~ ^[Yy]$ ]] || exit 1
python3 -m venv --system-site-packages "$VENV"
"$VENV/bin/pip" install --quiet -r "$DIR/bridge/requirements.txt"
[ -f "$DIR/bridge/config/local.yaml" ] || cat > "$DIR/bridge/config/local.yaml" <<'YAML'
# NUC-local overrides (merged over default.yaml). Fill identity after discovery.
identity:
  robot_name: "Lite3"
  expected_hostname: ""        # `hostname` of THIS NUC
  expected_ros_domain_id: null # our ROS_DOMAIN_ID
YAML
echo "Done. Edit $DIR/bridge/config/local.yaml, then run scripts/nuc/start-bridge.sh"
