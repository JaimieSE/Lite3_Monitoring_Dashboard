# shellcheck shell=bash
# Shared helpers for the Mac -> NUC scripts.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="$ROOT/scripts/mac/robot.env"
[ -f "$ENV_FILE" ] || { echo "Missing $ENV_FILE (copy robot.env.example and fill it in)." >&2; exit 1; }
# shellcheck disable=SC1090
source "$ENV_FILE"
if [ -n "${NUC_SSH_TARGET:-}" ]; then
  SSH_DEST="$NUC_SSH_TARGET"
else
  [ -n "${NUC_HOST:-}" ] && [ -n "${NUC_USER:-}" ] || { echo "Set NUC_HOST and NUC_USER (or NUC_SSH_TARGET) in robot.env" >&2; exit 1; }
  SSH_DEST="$NUC_USER@$NUC_HOST"
fi
SSH_OPTS=(-p "${NUC_SSH_PORT:-22}" -o ServerAliveInterval=5 -o ServerAliveCountMax=3 -o ConnectTimeout=8)

confirm() {
  read -r -p "$1 [y/N] " ans
  [[ "$ans" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 1; }
}
