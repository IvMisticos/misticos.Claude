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
    | map(.hooks = ((.hooks // []) | map(select(.command != $command))))
    | map(select(.hooks | length > 0))
    + [ { matcher: matcher, hooks: [ { type: "command", command: $command } ] } ]);
.attribution.commit = ""
| .attribution.pr = ""
| .attribution.sessionUrl = false
| register("SessionStart"; "compact")
| register("UserPromptSubmit"; "")
| register("PostToolUse"; "")
'

register_reminder_in() {
  local settings=$1
  if [ ! -e "$settings" ] || ! grep -q '[^[:space:]]' "$settings"; then
    echo '{}' > "$settings"
  elif ! jq -e 'type == "object"' "$settings" > /dev/null 2>&1; then
    echo "setup: $settings holds no JSON object, leaving it alone" >&2
    return
  fi
  jq --arg command "$reminder" "$register_reminder" "$settings" > "$settings.new"
  mv "$settings.new" "$settings"
}

# CLAUDE.md and its reminder hook
for d in /home/user/.claude /root/.claude; do
  mkdir -p "$d"
  register_reminder_in "$d/settings.json"
  cp "$repo/CLAUDE.md" "$d/"
  install -m 755 "$repo/hooks/claudemd-reminder.py" "$d/"
done

chown -R user:user /home/user/.claude 2>/dev/null || true
