#!/usr/bin/env bash
# Make sure the READ-ONLY monitor bridge is running on the NUC; start it in tmux if not.
# Streamed over SSH by scripts/mac/start-all.sh and scripts/windows/start-all.ps1:
#     ssh user@nuc bash -s -- <domain_id> <port> [monitor_dir] < ensure-bridge.sh
# It only starts/inspects lite3_bridge (this project). It never touches robot nodes.
DOMAIN="${1:?usage: ensure-bridge.sh <ros_domain_id> <port> [monitor_dir]}"
PORT="${2:-8765}"
DIR="${3:-$HOME/Lite3_Monitoring_Dashboard/lite3-monitor}"
DIR="${DIR/#\~/$HOME}"
START="$DIR/scripts/nuc/start-bridge.sh"

healthy() {
  python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:$PORT/healthz', timeout=1)" 2>/dev/null
}

if healthy; then
  echo "BRIDGE: already running on the NUC (port $PORT)"
  exit 0
fi
if pgrep -f "python.* -m lite3_bridge" >/dev/null; then
  echo "BRIDGE: a bridge process exists but is not answering yet - waiting"
else
  [ -x "$START" ] || { echo "BRIDGE: not installed at $DIR (see docs/STARTUP_MANUAL.md section 6)"; exit 2; }
  CMD="export ROS_DOMAIN_ID=$DOMAIN; $START; echo; echo '[bridge stopped - press Enter to close]'; read _"
  if command -v tmux >/dev/null 2>&1; then
    if tmux has-session -t monitor 2>/dev/null; then
      tmux new-window -t monitor -n bridge "bash -ic \"$CMD\""
    else
      tmux new-session -d -s monitor -n bridge "bash -ic \"$CMD\""
    fi
    echo "BRIDGE: starting in tmux session 'monitor' (domain $DOMAIN)"
  else
    nohup bash -ic "export ROS_DOMAIN_ID=$DOMAIN; $START" > "$HOME/lite3-bridge.log" 2>&1 < /dev/null &
    echo "BRIDGE: starting in the background, log: ~/lite3-bridge.log (tmux not installed)"
  fi
fi

for _ in $(seq 1 25); do
  sleep 1
  if healthy; then echo "BRIDGE: running"; exit 0; fi
done
echo "BRIDGE: did not come up within 25 s. Last output:"
{ tmux capture-pane -p -t monitor:bridge 2>/dev/null || tail -n 40 "$HOME/lite3-bridge.log" 2>/dev/null; } | grep -v "graph-scan" | tail -n 25
exit 3
