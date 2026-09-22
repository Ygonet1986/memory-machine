#!/usr/bin/env bash
# Install the Memory Machine OpenCode integration into ~/.config/opencode.
#
# Idempotent and safe: existing files are backed up with a timestamp suffix
# before being replaced. Override the destination with OPENCODE_CONFIG.
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="${OPENCODE_CONFIG:-$HOME/.config/opencode}"
STAMP="$(date +%Y%m%d%H%M%S)"

backup() {
  if [[ -e "$1" ]]; then
    cp -p "$1" "$1.bak.$STAMP"
    echo "backed up: $1 -> $1.bak.$STAMP"
  fi
}

install_file() {
  local rel="$1"
  mkdir -p "$DEST/$(dirname "$rel")"
  backup "$DEST/$rel"
  cp -p "$SRC/$rel" "$DEST/$rel"
  echo "installed: $DEST/$rel"
}

install_file "plugins/memory.ts"
install_file "AGENTS.md"
install_file "skills/memory/SKILL.md"
install_file "skills/memory-capture/SKILL.md"
install_file "agent/memory.md"

echo
echo "Memory Machine OpenCode integration installed into $DEST"
echo "Restart opencode (plugins and config load at startup)."
echo "The plugin calls the installed 'memory-cli'; install the package first:"
echo "  pipx install memory-machine"
