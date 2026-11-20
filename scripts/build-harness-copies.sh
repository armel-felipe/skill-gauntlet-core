#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
name="gauntlet-core"

for target in "agents/skills" ".claude/skills" "opencode/skills"; do
  dest="$root/$target/$name"
  mkdir -p "$dest"
  cp "$root/SKILL.md" "$dest/SKILL.md"
  cp "$root/gauntlet_core.py" "$dest/gauntlet_core.py"
  rm -rf "$dest/contracts" "$dest/examples"
  cp -R "$root/contracts" "$dest/contracts"
  cp -R "$root/examples" "$dest/examples"
done

echo "copias geradas para $name"
