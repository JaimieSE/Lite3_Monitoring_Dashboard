#!/usr/bin/env bash
# Run the full dashboard on macOS against the built-in simulator (no robot).
#   ./scripts/mac/start-sim.sh            # production build, faults on
#   ./scripts/mac/start-sim.sh --dev      # next dev (hot reload)
#   ./scripts/mac/start-sim.sh --dropouts # also simulate Wi-Fi drops (TELEMETRY LOST)
#   ./scripts/mac/start-sim.sh --no-faults
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DEV=0
BRIDGE_ARGS=(--sim)
for a in "$@"; do
  case "$a" in
    --dev) DEV=1 ;;
    --dropouts) BRIDGE_ARGS+=(--sim-link-dropouts) ;;
    --no-faults) BRIDGE_ARGS+=(--sim-no-faults) ;;
    *) echo "unknown option $a" >&2; exit 2 ;;
  esac
done

PY="$ROOT/bridge/.venv/bin/python"
[ -x "$PY" ] || { echo "Run ./scripts/mac/install.sh first." >&2; exit 1; }

cleanup() { trap - EXIT INT TERM; kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo "==> Simulated bridge on ws://127.0.0.1:8765/ws"
(cd "$ROOT/bridge" && "$PY" -m lite3_bridge "${BRIDGE_ARGS[@]}") &

cd "$ROOT/web"
export LITE3_BRIDGE_WS_URL="ws://127.0.0.1:8765/ws"
if [ "$DEV" = 1 ]; then
  npm run dev &
else
  npm run build
  npm run start &
fi
sleep 2
echo "==> Dashboard: http://127.0.0.1:3000   (Ctrl-C to stop everything)"
(command -v open >/dev/null && sleep 3 && open "http://127.0.0.1:3000") >/dev/null 2>&1 &
wait
