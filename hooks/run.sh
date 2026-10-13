#!/usr/bin/env bash

set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"

install_lock="$HOME/.local/uv-install.pid"

take_install_lock() {
  (set -C; echo $$ > "$install_lock") 2>/dev/null
}

release_install_lock() {
  rm -f "$install_lock"
  trap - EXIT
}

install_lock_holder_is_gone() {
  local holder
  holder=$(cat "$install_lock" 2>/dev/null) || return 1
  ! kill -0 "$holder" 2>/dev/null
}

install_uv_once() {
  mkdir -p "$HOME/.local"
  until take_install_lock; do
    install_lock_holder_is_gone && rm -f "$install_lock"
    sleep 0.2
  done
  trap release_install_lock EXIT
  command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | INSTALLER_NO_MODIFY_PATH=1 sh >&2
  release_install_lock
}

hash_file() {
  { sha256sum "$1" || shasum -a 256 "$1"; } 2>/dev/null | cut -d' ' -f1
}

setup_key() {
  local hash boot_id
  hash=$(hash_file "$1") && [ -n "$hash" ] || return 1
  boot_id=$(cat "${SETUP_BOOT_ID_FILE:-/proc/sys/kernel/random/boot_id}" 2>/dev/null || true)
  echo "$hash $boot_id"
}

hooks_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

remember_setup=false
if [ "${1-}" = setup.py ] && [ -n "${CLAUDE_PLUGIN_DATA-}" ]; then
  setup_marker="$CLAUDE_PLUGIN_DATA/setup-complete"
  if setup_key_value=$(setup_key "$hooks_dir/setup.py"); then
    remember_setup=true
    [ "$(cat "$setup_marker" 2>/dev/null)" = "$setup_key_value" ] && exit 0
  fi
fi

command -v uv >/dev/null || install_uv_once

if [ $# -gt 0 ] && [ -f "$hooks_dir/$1" ]; then
  set -- "$hooks_dir/$1" "${@:2}"
fi

if [ "$remember_setup" = false ]; then
  exec uv run "$@"
fi

uv run "$@"
mkdir -p "$CLAUDE_PLUGIN_DATA"
echo "$setup_key_value" > "$setup_marker"
