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

hash_stdin() {
  { sha256sum || shasum -a 256; } 2>/dev/null
}

hooks_key() {
  local source
  for source in "$hooks_dir"/*.py; do
    hash_stdin < "$source"
  done | hash_stdin | cut -d' ' -f1
}

hooks_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

remember_completion=false
if [ "${1-}" = --once ]; then
  shift
  if [ -n "${CLAUDE_PLUGIN_DATA-}" ] && [ -f "$hooks_dir/${1-}" ]; then
    completion_marker="$CLAUDE_PLUGIN_DATA/${1%.py}-complete"
    if completion_key=$(hooks_key) && [ -n "$completion_key" ]; then
      remember_completion=true
      [ "$(cat "$completion_marker" 2>/dev/null)" = "$completion_key" ] && exit 0
    fi
  fi
fi

command -v uv >/dev/null || install_uv_once

if [ $# -gt 0 ] && [ -f "$hooks_dir/$1" ]; then
  set -- "$hooks_dir/$1" "${@:2}"
fi

if [ "$remember_completion" = false ]; then
  exec uv run "$@"
fi

uv run "$@"
mkdir -p "$CLAUDE_PLUGIN_DATA"
echo "$completion_key" > "$completion_marker"
