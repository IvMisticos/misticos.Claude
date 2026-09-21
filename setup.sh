#!/usr/bin/env bash

set -euo pipefail

apt-get update && apt-get install -y git-lfs curl jq gh python3 unzip

curl -fsSL https://bun.sh/install | bash -s canary
curl -LsSf https://astral.sh/uv/install.sh | INSTALLER_NO_MODIFY_PATH=1 sh
curl -fsSL https://dot.net/v1/dotnet-install.sh | bash -s -- --channel LTS
mkdir -p /root/.local/bin
ln -sf /root/.dotnet/dotnet /root/.local/bin/dotnet

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

cp "$repo/CLAUDE.md" "$d/"
rm -f "$d/reminder.py" "$d/output-styles/short.md"

jq --arg command '~/.claude/reminder.py' '
def without_reminder:
  map_values([ .[] | .hooks = [ (.hooks // [])[] | select((.command // "") | startswith($command) | not) ] | select(.hooks != []) ])
  | with_entries(select(.value != []));
.attribution = {
  commit: "",
  pr: "",
  sessionUrl: false
}
| .autoMemoryEnabled = false
| del(.outputStyle)
| .hooks = ((.hooks // {}) | without_reminder)
' "$settings" > "$settings.installed"
mv "$settings.installed" "$settings"

claude plugin marketplace add GoogleChrome/modern-web-guidance
claude plugin install modern-web-guidance@googlechrome --scope user
claude plugin marketplace add "$repo"
claude plugin install misticos@misticos --scope user

if command -v codex >/dev/null; then
  codex_config=/root/.codex/config.toml
  mkdir -p /root/.codex
  cp "$repo/CLAUDE.md" /root/.codex/AGENTS.md
  touch "$codex_config"
  if ! grep -q '^personality' "$codex_config"; then
    { printf 'personality = "none"\n'; cat "$codex_config"; } > "$codex_config.installed"
    mv "$codex_config.installed" "$codex_config"
  fi
  grep -q '^\[memories\]' "$codex_config" || printf '\n[memories]\nuse_memories = false\ngenerate_memories = false\n' >> "$codex_config"
  codex plugin marketplace add "$repo"
  codex plugin add misticos@misticos
fi
