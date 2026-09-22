#!/usr/bin/env bash

set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"

install_uv_once() {
  local lock="$HOME/.local/uv-install.lock"
  mkdir -p "$HOME/.local"
  until mkdir "$lock" 2>/dev/null; do sleep 0.2; done
  trap 'rmdir "$lock"' EXIT
  command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | INSTALLER_NO_MODIFY_PATH=1 sh >&2
}

command -v uv >/dev/null || install_uv_once

exec uv run "$@"
