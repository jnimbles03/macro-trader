#!/usr/bin/env bash
# Install the macro-scout ingest launchd job.
#
#   ./scripts/install-launchd.sh
#
# Substitutes the working dir + venv path into the plist template and copies
# it into ~/Library/LaunchAgents/, then loads it.

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
DEST="$LA_DIR/com.macroscout.ingest.plist"

sed \
  -e "s|__MACRO_SCOUT_HOME__|$REPO_ROOT|g" \
  -e "s|__VENV_BIN__|$VENV_BIN|g" \
  "$REPO_ROOT/scripts/com.macroscout.ingest.plist" > "$DEST"

# Reload if already loaded.
launchctl unload "$DEST" 2>/dev/null || true
launchctl load "$DEST"

echo "Installed: $DEST"
echo "Logs:"
echo "  $REPO_ROOT/data/launchd-ingest.out.log"
echo "  $REPO_ROOT/data/launchd-ingest.err.log"
echo
echo "Verify: launchctl list | grep com.macroscout.ingest"
echo "Uninstall: ./scripts/uninstall-launchd.sh"
