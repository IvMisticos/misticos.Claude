#!/usr/bin/env bash

set -euo pipefail

# Dependencies and common tools
apt-get update && apt-get install -y git-lfs ffmpeg curl jq gh

# Repository
if [ -f "${BASH_SOURCE[0]:-}" ]; then
  repo=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
else
  repo=/usr/local/share/misticos.claude
  rm -rf "$repo"
  git clone --depth 1 https://github.com/IvMisticos/misticos.Claude "$repo"
fi

# Claude hooks
claude_hooks=/usr/local/share/claude-hooks
mkdir -p $claude_hooks
cp "$repo/vale.sh" "$claude_hooks/vale.sh"
chmod +x $claude_hooks/*

# Claude config
jq -n --arg vale "$claude_hooks/vale.sh" '
.attribution = {
  commit: "",
  pr: "",
  sessionUrl: false
} |
.hooks.PostToolUse = [
  {
    matcher: "Write|Edit",
    hooks: [ { type: "command", command: $vale, timeout: 30 } ]
  }
]
' > /tmp/settings.json

# CLAUDE.md
for d in /home/user/.claude /root/.claude; do
  mkdir -p "$d"
  if [ -f "$d/settings.json" ]; then
    jq -s '.[0] * .[1]' "$d/settings.json" /tmp/settings.json > "$d/settings.json.merged"
    mv "$d/settings.json.merged" "$d/settings.json"
  else
    cp /tmp/settings.json "$d/settings.json"
  fi
  cp "$repo/CLAUDE.md" "$d/"
done

chown -R user:user /home/user/.claude 2>/dev/null || true

# Install vale
tag=$(git ls-remote --tags --refs https://github.com/vale-cli/vale \
  | awk -F/ '{print $NF}' \
  | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' \
  | sort -V | tail -1)
[ -n "$tag" ] || { echo "no vale tag found" >&2; exit 1; }

curl -fsSL -o /tmp/vale.tar.gz "https://github.com/vale-cli/vale/releases/download/${tag}/vale_${tag#v}_Linux_64-bit.tar.gz"
tar -xzf /tmp/vale.tar.gz -C /usr/local/bin vale

# Vale config
for d in /home/user/.config/vale /root/.config/vale; do
  mkdir -p "$d"
  cp "$repo/.vale.ini" "$d/"
done

vale sync

# Git hooks
git_hooks=/usr/local/share/git-hooks
mkdir -p $git_hooks
cp "$repo/commit-msg" $git_hooks/commit-msg
chmod +x $git_hooks/*

git config --global core.hooksPath $git_hooks