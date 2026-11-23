#!/usr/bin/env bash
# Live mode: keep an SSH tunnel to OUR NUC open (auto-reconnect) and run the dashboard.
# Assumes the bridge is already running on the NUC (scripts/nuc/start-bridge.sh).
# This script never starts, stops or changes anything on the robot.
set -euo pipefail
source "$(dirname "$0")/_common.sh"
LOCAL_PORT="${LOCAL_PORT:-8765}"
REMOTE_PORT="${REMOTE_PORT:-8765}"

# The tunnel needs LOCAL_PORT free on this laptop. If something already listens there
# (an old tunnel from a closed window, or the simulator), stop instead of looping.
if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"$LOCAL_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port $LOCAL_PORT on this laptop is already in use by:"
  lsof -nP -iTCP:"$LOCAL_PORT" -sTCP:LISTEN | sed 's/^/   /'
  echo
  echo "Usually an old tunnel or the simulator. Stop it with:"
  echo "   pkill -f \"$LOCAL_PORT:127.0.0.1:$REMOTE_PORT\"     # old tunnel"
  echo "   pkill -f \"lite3_bridge --sim\"               # simulator"
  echo "then run this script again."
  exit 1
fi

cleanup() { trap - EXIT INT TERM; kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

tunnel_loop() {
  local delay=1
  while true; do
    echo "[tunnel] $SSH_DEST : 127.0.0.1:$LOCAL_PORT -> NUC 127.0.0.1:$REMOTE_PORT"
    local start=$SECONDS
    ssh -N "${SSH_OPTS[@]}" -o ExitOnForwardFailure=yes \
      -L "127.0.0.1:$LOCAL_PORT:127.0.0.1:$REMOTE_PORT" "$SSH_DEST" || true
    # reset backoff if the tunnel had been up for a while
    if (( SECONDS - start > 30 )); then delay=1; fi
    echo "[tunnel] disconnected; retrying in ${delay}s"
    sleep "$delay"
    delay=$(( delay < 10 ? delay * 2 : 10 ))
  done
}
tunnel_loop &

cd "$ROOT/web"
export LITE3_BRIDGE_WS_URL="ws://127.0.0.1:$LOCAL_PORT/ws"
export LITE3_EXPECTED_HOSTNAME="${EXPECTED_HOSTNAME:-}"
export LITE3_EXPECTED_DOMAIN_ID="${EXPECTED_DOMAIN_ID:-}"
[ -n "$LITE3_EXPECTED_HOSTNAME" ] || echo "WARNING: EXPECTED_HOSTNAME not set - robot identity will be shown as unverified."
[ -d .next ] || npm run build
npm run start &
echo "==> Dashboard: http://127.0.0.1:3000   (Ctrl-C stops the tunnel and the dashboard only)"
wait
