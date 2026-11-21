#!/usr/bin/env bash
# Copy the bridge (source only) to the NUC. ONLY run after the team approves
# NUC integration. Copies into its own directory; never touches lite3_ws.
set -euo pipefail
source "$(dirname "$0")/_common.sh"
DEST="${NUC_INSTALL_DIR:-~/lite3-monitor}"
echo "Will copy lite3-monitor/bridge and scripts/nuc to $SSH_DEST:$DEST"
echo "(no packages are installed by this step; see scripts/nuc/install.sh)"
confirm "Proceed?"
ssh "${SSH_OPTS[@]}" "$SSH_DEST" "mkdir -p $DEST/bridge $DEST/scripts"
rsync -az --delete -e "ssh -p ${NUC_SSH_PORT:-22}" \
  --exclude '.venv' --exclude '__pycache__' --exclude 'tests' --exclude 'config/local.yaml' \
  "$ROOT/bridge/" "$SSH_DEST:$DEST/bridge/"
rsync -az -e "ssh -p ${NUC_SSH_PORT:-22}" "$ROOT/scripts/nuc/" "$SSH_DEST:$DEST/scripts/nuc/"
echo "Deployed. On the NUC: $DEST/scripts/nuc/install.sh (once), then $DEST/scripts/nuc/start-bridge.sh"
