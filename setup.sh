#!/usr/bin/env bash

set -euo pipefail

apt-get update && apt-get install -y git-lfs curl jq gh python3

if [ -f "${BASH_SOURCE[0]:-}" ]; then
  repo=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
else
  repo=/usr/local/share/misticos.claude
  rm -rf "$repo"
  git clone --depth 1 https://github.com/IvMisticos/misticos.Claude "$repo"
fi

d="$HOME/.claude"
settings="$d/settings.json"
mkdir -p "$d"
grep -q '[^[:space:]]' "$settings" 2>/dev/null || echo '{}' > "$settings"

cp "$repo/CLAUDE.md" "$d/"
parts=$(python3 "$repo/hooks/reminder.py" --entries)

jq --arg command '~/.claude/reminder.py' --argjson parts "$parts" '
def reminder(part):
  {
    type: "command",
    command: "\($command) \(part) \($parts)"
  };
def every_part(matcher):
  [ {
    matcher: matcher,
    hooks: [ range(1; $parts + 1) | reminder(.) ]
  } ];
def without_reminder:
  map_values([ .[] | .hooks = [ (.hooks // [])[] | select((.command // "") | startswith($command) | not) ] | select(.hooks != []) ])
  | with_entries(select(.value != []));
.attribution = {
  commit: "",
  pr: "",
  sessionUrl: false
}
| .autoMemoryEnabled = false
| .hooks = ((.hooks // {}) | without_reminder)
| .hooks.SessionStart += [ { matcher: "compact", hooks: [ reminder(1) ] } ]
| .hooks.UserPromptSubmit += every_part("")
| .hooks.PostToolBatch += every_part("")
' "$settings" > "$settings.installed"

install -m 755 "$repo/hooks/reminder.py" "$d/"
mv "$settings.installed" "$settings"
