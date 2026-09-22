#!/usr/bin/env bash
# Remove the Memory Machine OpenCode integration from ~/.config/opencode.
#
# Files installed by install.sh are moved aside (timestamped) and the most
# recent backup, if any, is restored. Override with OPENCODE_CONFIG.
set -euo pipefail

DEST="${OPENCODE_CONFIG:-$HOME/.config/opencode}"
STAMP="$(date +%Y%m%d%H%M%S)"

remove_file() {
  local rel="$1"
  local target="$DEST/$rel"
  [[ -e "$target" ]] || return 0
  mv "$target" "$target.removed.$STAMP"
  local latest
  latest="$(ls -1t "$target".bak.* 2>/dev/null | head -1 || true)"
  if [[ -n "$latest" ]]; then
    cp -p "$latest" "$target"
    echo "restored: $target (from $latest)"
  else
    echo "removed: $target"
  fi
}

remove_file "plugins/memory.ts"
remove_file "AGENTS.md"
remove_file "skills/memory/SKILL.md"
remove_file "skills/memory-capture/SKILL.md"
remove_file "agent/memory.md"

echo
echo "Memory Machine OpenCode integration removed from $DEST."
echo "Restart opencode for the change to take effect."
