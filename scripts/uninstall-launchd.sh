#!/usr/bin/env bash
set -euo pipefail

DEST="$HOME/Library/LaunchAgents/com.macroscout.ingest.plist"
if [ ! -f "$DEST" ]; then
  echo "Not installed: $DEST"
  exit 0
fi

launchctl unload "$DEST" 2>/dev/null || true
rm -f "$DEST"
echo "Removed: $DEST"
