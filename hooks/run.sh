#!/usr/bin/env bash

set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"

install_lock="$HOME/.local/tool-install.pid"

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

register_uv_in_mise() {
  if mise config get --global tools.uv >/dev/null 2>&1; then
    mise install uv
  else
    mise use --global uv@latest
  fi
}

uv_from_mise_config() {
  register_uv_in_mise >&2 && mise which uv
}

uv_without_mise_config() {
  mise --quiet x uv@latest -- sh -c 'command -v uv'
}

install_uv_with_mise() {
  local uv
  command -v mise >/dev/null || curl -fsSL https://mise.run | sh
  uv=$(uv_from_mise_config) || uv=$(uv_without_mise_config)
  mkdir -p "$HOME/.local/bin"
  ln -sf "$uv" "$HOME/.local/bin/uv"
}

install_uv_once() {
  mkdir -p "$HOME/.local"
  until take_install_lock; do
    install_lock_holder_is_gone && rm -f "$install_lock"
    sleep 0.2
  done
  trap release_install_lock EXIT
  if ! command -v uv >/dev/null; then
    (cd "$HOME"; install_uv_with_mise) >&2
  fi
  release_install_lock
}

hash_file() {
  { sha256sum "$1" || shasum -a 256 "$1"; } 2>/dev/null | cut -d' ' -f1
}

hooks_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

remember_completion=false
if [ "${1-}" = --once ]; then
  shift
  if [ -n "${CLAUDE_PLUGIN_DATA-}" ] && [ -f "$hooks_dir/${1-}" ]; then
    completion_marker="$CLAUDE_PLUGIN_DATA/${1%.py}-complete"
    if completion_key=$(hash_file "$hooks_dir/$1") && [ -n "$completion_key" ]; then
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
