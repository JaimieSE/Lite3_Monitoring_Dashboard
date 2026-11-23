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
if ! python3 -m venv --system-site-packages "$VENV" 2>/dev/null; then
  # Ubuntu without python3.X-venv (needs sudo apt). Avoid sudo: create the venv
  # without pip and bootstrap pip into it (inside this folder only).
  echo "Standard venv failed (python3-venv not installed); using no-sudo fallback."
  rm -rf "$VENV"
  python3 -m venv --without-pip --system-site-packages "$VENV"
  python3 -c "import urllib.request; urllib.request.urlretrieve('https://bootstrap.pypa.io/get-pip.py', '$VENV/get-pip.py')"
  "$VENV/bin/python" "$VENV/get-pip.py" --quiet
  rm -f "$VENV/get-pip.py"
fi
"$VENV/bin/python" -m pip install --quiet -r "$DIR/bridge/requirements.txt"
# sanity: rclpy (from /opt/ros) must be importable inside the venv once ROS is sourced
echo "Installed: $("$VENV/bin/python" -c 'import fastapi, uvicorn, websockets, yaml; print("fastapi", fastapi.__version__, "uvicorn", uvicorn.__version__)')"
[ -f "$DIR/bridge/config/local.yaml" ] || cat > "$DIR/bridge/config/local.yaml" <<'YAML'
# NUC-local overrides, merged after default.yaml and the robot profile
# (config/group8.yaml). Identity, map and TF settings already come from the profile;
# put only machine-specific tweaks here.
{}
YAML
echo "Done. Run scripts/nuc/start-bridge.sh (uses config/group8.yaml; optional tweaks in config/local.yaml)"
