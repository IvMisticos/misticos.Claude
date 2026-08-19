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
reminder='~/.claude/claudemd-reminder.py'
register_reminder='
def register(event; matcher):
  .hooks[event] = ((.hooks[event] // [])
    | map(select([.hooks[]?.command] | index($command) | not))
    + [ { matcher: matcher, hooks: [ { type: "command", command: $command } ] } ]);
.attribution.commit = ""
| .attribution.pr = ""
| .attribution.sessionUrl = false
| register("SessionStart"; "compact")
| register("UserPromptSubmit"; "")
| register("PostToolUse"; "")
'

# CLAUDE.md and its reminder hook
for d in /home/user/.claude /root/.claude; do
  mkdir -p "$d"
  [ -f "$d/settings.json" ] || echo '{}' > "$d/settings.json"
  jq --arg command "$reminder" "$register_reminder" "$d/settings.json" > "$d/settings.json.patched"
  mv "$d/settings.json.patched" "$d/settings.json"
  cp "$repo/CLAUDE.md" "$d/"
  install -m 755 "$repo/hooks/claudemd-reminder.py" "$d/"
done

chown -R user:user /home/user/.claude 2>/dev/null || true
