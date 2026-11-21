#!/usr/bin/env bash
# READ-ONLY discovery of the NUC's ROS 2 graph, with zero footprint:
# the discovery script is streamed over SSH to `python3 -` and nothing is
# installed or written on the NUC. Requires your approval each run.
set -euo pipefail
source "$(dirname "$0")/_common.sh"
SECONDS_ARG="${1:-8}"
OUT="$ROOT/docs/discovery"
mkdir -p "$OUT"
STAMP="$(date +%Y%m%d-%H%M%S)"

echo "This will SSH to $SSH_DEST and run a read-only ROS 2 discovery for ${SECONDS_ARG}s:"
echo "  - lists nodes/topics/services/actions/TF frames, samples topic rates (subscriptions only)"
echo "  - never publishes, never calls services/actions, never touches parameters"
echo "  - installs nothing and writes no files on the NUC"
confirm "Proceed?"

# Build one script for `bash -s` on the NUC: source ROS (+ workspace, read-only),
# then feed discover.py to python3 through a quoted heredoc.
{
  echo 'source /opt/ros/humble/setup.bash >/dev/null 2>&1'
  echo "WS=${NUC_LITE3_WS:-~/lite3_ws}"
  echo 'if [ -f "$WS/install/setup.bash" ]; then source "$WS/install/setup.bash" >/dev/null 2>&1; fi'
  echo 'echo "# hostname: $(hostname)  ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-unset}" >&2'
  echo "python3 - --seconds $SECONDS_ARG <<'__LITE3_DISCOVER_PY__'"
  cat "$ROOT/bridge/lite3_bridge/discover.py"
  echo '__LITE3_DISCOVER_PY__'
} | ssh "${SSH_OPTS[@]}" "$SSH_DEST" bash -s | tee "$OUT/discovery-$STAMP.md"
echo
echo "Saved to docs/discovery/discovery-$STAMP.md - commit it so the next agent can use it."
