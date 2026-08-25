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

d=/root/.claude
settings="$d/settings.json"
mkdir -p "$d"
grep -q '[^[:space:]]' "$settings" 2>/dev/null || echo '{}' > "$settings"

jq --arg command '~/.claude/reminder.py' '
def reminder(matcher):
  {
    matcher: matcher,
    hooks: [ {
      type: "command",
      command: $command
    } ]
  };
def without_reminder:
  map_values([ .[] | .hooks = [ (.hooks // [])[] | select(.command != $command) ] | select(.hooks != []) ])
  | with_entries(select(.value != []));
.attribution = {
  commit: "",
  pr: "",
  sessionUrl: false
}
| .autoMemoryEnabled = false
| .hooks = ((.hooks // {}) | without_reminder)
| .hooks.SessionStart += [ reminder("compact") ]
| .hooks.UserPromptSubmit += [ reminder("") ]
| .hooks.PostToolBatch += [ reminder("") ]
' "$settings" > "$settings.installed"
mv "$settings.installed" "$settings"

cp "$repo/CLAUDE.md" "$d/"
install -m 755 "$repo/hooks/reminder.py" "$d/"
