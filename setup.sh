#!/usr/bin/env bash

set -euo pipefail

apt-get update && apt-get install -y git-lfs ffmpeg curl jq gh

if [ -f "${BASH_SOURCE[0]:-}" ]; then
  repo=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
else
  repo=/usr/local/share/misticos.claude
  rm -rf "$repo"
  git clone --depth 1 https://github.com/IvMisticos/misticos.Claude "$repo"
fi

for d in /home/user/.claude /root/.claude; do
  mkdir -p "$d"
  [ -s "$d/settings.json" ] || echo '{}' > "$d/settings.json"
  jq --arg command '~/.claude/reminder.py' '
    def register(event; matcher):
      .hooks[event] = ((.hooks[event] // [])
        | map(.hooks = ((.hooks // []) | map(select(.command != $command))))
        | map(select(.hooks | length > 0))
        + [ { matcher: matcher, hooks: [ { type: "command", command: $command } ] } ]);
    .attribution.commit = ""
    | .attribution.pr = ""
    | .attribution.sessionUrl = false
    | register("SessionStart"; "compact")
    | register("UserPromptSubmit"; "")
    | register("PostToolUse"; "")
  ' "$d/settings.json" > "$d/settings.json.new"
  mv "$d/settings.json.new" "$d/settings.json"
  cp "$repo/CLAUDE.md" "$d/"
  install -m 755 "$repo/hooks/reminder.py" "$d/"
done

chown -R user:user /home/user/.claude 2>/dev/null || true
