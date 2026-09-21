#!/usr/bin/env bash

set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | INSTALLER_NO_MODIFY_PATH=1 sh >&2

exec uv run "$@"
