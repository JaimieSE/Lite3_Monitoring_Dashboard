#!/usr/bin/env bash
# macOS one-time setup: web dependencies + a local Python venv for the simulator.
# Touches nothing outside this repository. Does not contact the robot.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

need() { command -v "$1" >/dev/null 2>&1 || { echo "ERROR: '$1' not found. $2" >&2; exit 1; }; }
need node "Install Node.js 20 LTS or newer (e.g. 'brew install node@20')."
need npm "It ships with Node.js."
need python3 "Install Python 3.10+ (e.g. 'brew install python@3.12')."

NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
if [ "$NODE_MAJOR" -lt 20 ]; then echo "ERROR: Node >= 20 required (found $(node -v))." >&2; exit 1; fi

echo "==> Installing web dependencies (lite3-monitor/web)"
(cd "$ROOT/web" && npm ci --no-audit --no-fund)

echo "==> Creating simulator venv (lite3-monitor/bridge/.venv)"
python3 -m venv "$ROOT/bridge/.venv"
"$ROOT/bridge/.venv/bin/pip" install --quiet --upgrade pip
"$ROOT/bridge/.venv/bin/pip" install --quiet -r "$ROOT/bridge/requirements-dev.txt"

if [ ! -f "$ROOT/web/.env.local" ]; then
  cp "$ROOT/web/.env.example" "$ROOT/web/.env.local"
  echo "==> Created web/.env.local from .env.example"
fi
if [ ! -f "$ROOT/scripts/mac/robot.env" ]; then
  cp "$ROOT/scripts/mac/robot.env.example" "$ROOT/scripts/mac/robot.env"
  echo "==> Created scripts/mac/robot.env - fill in the NUC details before live use"
fi

echo
echo "Done. Start the simulator dashboard with:  ./scripts/mac/start-sim.sh"
