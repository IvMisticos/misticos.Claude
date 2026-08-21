#!/usr/bin/env bash

set -euo pipefail

apt-get update && apt-get install -y git-lfs curl jq gh

if [ -f "${BASH_SOURCE[0]:-}" ]; then
  repo=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
else
  repo=/usr/local/share/misticos.claude
  rm -rf "$repo"
  git clone --depth 1 https://github.com/IvMisticos/misticos.Claude "$repo"
fi

hook_command='~/.claude/reminder.py'

jq -n --arg command "$hook_command" '
def reminder(matcher):
  [ {
    matcher: matcher,
    hooks: [ {
      type: "command",
      command: $command
    } ]
  } ];
.attribution = {
  commit: "",
  pr: "",
  sessionUrl: false
}
| .autoMemoryEnabled = false
| .hooks = {
  SessionStart: reminder("compact"),
  UserPromptSubmit: reminder(""),
  PostToolBatch: reminder("")
}
' > /tmp/settings.json

d=/root/.claude
mkdir -p "$d"

if [ -f "$d/settings.json" ]; then
  jq -s --arg command "$hook_command" '
  (.[0] * .[1])
  | .hooks.PostToolUse = ((.hooks.PostToolUse // []) | map(select([.hooks[].command] | index($command) | not)))
  | if (.hooks.PostToolUse | length) == 0 then del(.hooks.PostToolUse) else . end
  ' "$d/settings.json" /tmp/settings.json > "$d/settings.json.merged"
  mv "$d/settings.json.merged" "$d/settings.json"
else
  cp /tmp/settings.json "$d/settings.json"
fi

cp "$repo/CLAUDE.md" "$d/"
install -m 755 "$repo/hooks/reminder.py" "$d/"
