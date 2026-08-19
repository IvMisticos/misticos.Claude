#!/usr/bin/env bash

set -euo pipefail

payload=$(cat)
file=$(printf '%s' "$payload" | jq -r '.tool_input.file_path // empty')
[ -n "$file" ] && [ -f "$file" ] || exit 0

summary=$(NO_COLOR=1 vale --minAlertLevel=error "$file" 2>/dev/null) && exit 0

[ -n "$summary" ] || exit 0

jq -n --arg ctx "$summary" '
{
  hookSpecificOutput: {
    hookEventName: "PostToolUse",
    additionalContext: $ctx
  }
}
'