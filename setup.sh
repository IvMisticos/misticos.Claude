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

# Claude config
jq -n '
.attribution = {
  commit: "",
  pr: "",
  sessionUrl: false
}
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
