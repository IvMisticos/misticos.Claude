#!/usr/bin/env bash

set -euo pipefail

# Dependencies and common tools
apt-get update && apt-get install -y git-lfs ffmpeg curl jq gh

# Claude hooks
claude_hooks=/usr/local/share/claude-hooks
mkdir -p $claude_hooks
curl -fsSL -o "$claude_hooks/vale.sh" "https://gist.github.com/IvMisticos/25d43c86fe27d7cd90377dd04299c4d1/raw/vale.sh"
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
curl -fsSL -o /tmp/CLAUDE.md "https://gist.github.com/IvMisticos/25d43c86fe27d7cd90377dd04299c4d1/raw/CLAUDE.md"
[ -s /tmp/CLAUDE.md ] || { echo "CLAUDE.md is empty" >&2; exit 1; }

for d in /home/user/.claude /root/.claude; do
  mkdir -p "$d"
  cp /tmp/settings.json /tmp/CLAUDE.md "$d/"
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
curl -fsSL -o /tmp/.vale.ini "https://gist.github.com/IvMisticos/25d43c86fe27d7cd90377dd04299c4d1/raw/.vale.ini"
[ -s /tmp/.vale.ini ] || { echo ".vale.ini is empty" >&2; exit 1; }

for d in /home/user/.config/vale /root/.config/vale; do
  mkdir -p "$d"
  cp /tmp/.vale.ini "$d/"
done

vale sync

# Git hooks
git_hooks=/usr/local/share/git-hooks
mkdir -p $git_hooks
curl -fsSL -o $git_hooks/commit-msg "https://gist.github.com/IvMisticos/25d43c86fe27d7cd90377dd04299c4d1/raw/commit-msg"
chmod +x $git_hooks/*

git config --global core.hooksPath $git_hooks