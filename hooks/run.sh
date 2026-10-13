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

imported_modules() {
  local keyword module rest
  while read -r keyword module rest; do
    case "$keyword" in
      from | import) echo "${module%%[.,]*}" ;;
    esac
  done < "$hooks_dir/$1"
}

hash_script_and_local_imports() {
  case " $hashed_sources " in
    *" $1 "*) return ;;
  esac
  hashed_sources="$hashed_sources $1"
  hash_stdin < "$hooks_dir/$1"
  local module
  for module in $(imported_modules "$1"); do
    if [ -f "$hooks_dir/$module.py" ]; then
      hash_script_and_local_imports "$module.py"
    fi
  done
}

completion_key_of() {
  local hashed_sources=""
  hash_script_and_local_imports "$1" | hash_stdin | cut -d' ' -f1
}

hooks_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

remember_completion=false
if [ "${1-}" = --once ]; then
  shift
  if [ -n "${CLAUDE_PLUGIN_DATA-}" ] && [ -f "$hooks_dir/${1-}" ]; then
    completion_marker="$CLAUDE_PLUGIN_DATA/${1%.py}-complete"
    if completion_key=$(completion_key_of "$1") && [ -n "$completion_key" ]; then
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
