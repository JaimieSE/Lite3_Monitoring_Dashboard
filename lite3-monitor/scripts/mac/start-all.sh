#!/usr/bin/env bash
# ONE command for live monitoring:
#   1. on the NUC: start the read-only bridge in tmux (skipped if it is already running)
#   2. on this Mac: SSH tunnel + dashboard (start-robot.sh), browser opens
# Safe for every team-mate to run: it never starts a second bridge.
set -euo pipefail
source "$(dirname "$0")/_common.sh"
[ -n "${EXPECTED_DOMAIN_ID:-}" ] || { echo "Set EXPECTED_DOMAIN_ID in robot.env" >&2; exit 1; }

echo "==> Checking the bridge on the NUC ($SSH_DEST) - enter the NUC password if asked"
set +e
MONITOR_DIR="$(nuc_path "${NUC_MONITOR_DIR:-~/Lite3_Monitoring_Dashboard/lite3-monitor}")"
ssh "${SSH_OPTS[@]}" "$SSH_DEST" bash -s -- "$EXPECTED_DOMAIN_ID" "${REMOTE_PORT:-8765}" \
  "$MONITOR_DIR" < "$ROOT/scripts/nuc/ensure-bridge.sh"
rc=$?
set -e
if [ $rc -ne 0 ]; then
  echo "The bridge is not running on the NUC (see above). Fix that first; the robot is unaffected." >&2
  exit $rc
fi

echo "==> Starting tunnel + dashboard (enter the NUC password again if asked)"
exec "$ROOT/scripts/mac/start-robot.sh"
