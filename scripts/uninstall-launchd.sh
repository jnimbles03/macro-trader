#!/usr/bin/env bash
set -euo pipefail

LA_DIR="$HOME/Library/LaunchAgents"

uninstall_plist() {
  local label="$1"
  local dest="$LA_DIR/${label}.plist"
  if [ ! -f "$dest" ]; then
    echo "Not installed: $dest"
    return
  fi
  launchctl unload "$dest" 2>/dev/null || true
  rm -f "$dest"
  echo "Removed: $dest"
}

uninstall_plist "com.macroscout.ingest"
uninstall_plist "com.macroscout.daily-brief"
