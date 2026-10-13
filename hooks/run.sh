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
  local keyword names
  while read -r keyword names; do
    case "$keyword" in
      from) echo "${names%%[ .]*}" ;;
      import) modules_in_import_list "$names" ;;
    esac
  done < "$hooks_dir/$1"
}

modules_in_import_list() {
  local entries entry module rest
  IFS=, read -ra entries <<< "$1"
  for entry in "${entries[@]}"; do
    read -r module rest <<< "$entry"
    echo "${module%%.*}"
  done
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

completion_marker_of() {
  echo "$CLAUDE_PLUGIN_DATA/${1%.py}-complete"
}

wait_for_completion_of() {
  [ -n "${CLAUDE_PLUGIN_DATA-}" ] && [ -f "$hooks_dir/$1" ] || return 0
  local key attempts=300
  key=$(completion_key_of "$1") && [ -n "$key" ] || return 0
  until [ "$(cat "$(completion_marker_of "$1")" 2>/dev/null)" = "$key" ]; do
    attempts=$((attempts - 1))
    [ "$attempts" -gt 0 ] || return 0
    sleep 0.2
  done
}

hooks_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

run_once=false
run_after=""
while true; do
  case "${1-}" in
    --once) run_once=true; shift ;;
    --after) run_after=$2; shift 2 ;;
    *) break ;;
  esac
done

remember_completion=false
if [ "$run_once" = true ] && [ -n "${CLAUDE_PLUGIN_DATA-}" ] && [ -f "$hooks_dir/${1-}" ]; then
  completion_marker=$(completion_marker_of "$1")
  if completion_key=$(completion_key_of "$1") && [ -n "$completion_key" ]; then
    remember_completion=true
    [ "$(cat "$completion_marker" 2>/dev/null)" = "$completion_key" ] && exit 0
  fi
fi

if [ -n "$run_after" ]; then
  wait_for_completion_of "$run_after"
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
