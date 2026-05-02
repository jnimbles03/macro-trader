#!/usr/bin/env bash
# Install macro-scout launchd jobs.
#
#   ./scripts/install-launchd.sh
#
# Installs two jobs:
#   1. com.macroscout.ingest      — every 15 min, ingest-all + chains
#   2. com.macroscout.daily-brief — 8am ET weekdays, full poke -> morning-brief-YYYYMMDD.md

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_BIN="$REPO_ROOT/.venv/bin"

if [ ! -x "$VENV_BIN/macro-scout" ]; then
  echo "ERROR: $VENV_BIN/macro-scout not found." >&2
  echo "Run 'uv venv && source .venv/bin/activate && uv pip install -e \".[dev]\"' first." >&2
  exit 1
fi

mkdir -p "$REPO_ROOT/data"

LA_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$LA_DIR"

install_plist() {
  local label="$1"
  local src="$REPO_ROOT/scripts/${label}.plist"
  local dest="$LA_DIR/${label}.plist"

  sed \
    -e "s|__MACRO_SCOUT_HOME__|$REPO_ROOT|g" \
    -e "s|__VENV_BIN__|$VENV_BIN|g" \
    "$src" > "$dest"

  launchctl unload "$dest" 2>/dev/null || true
  launchctl load "$dest"
  echo "Installed: $dest"
}

install_plist "com.macroscout.ingest"
install_plist "com.macroscout.daily-brief"

echo
echo "Logs:"
echo "  $REPO_ROOT/data/launchd-ingest.{out,err}.log"
echo "  $REPO_ROOT/data/launchd-daily-brief.{out,err}.log"
echo
echo "Verify: launchctl list | grep com.macroscout"
echo "Uninstall: ./scripts/uninstall-launchd.sh"
