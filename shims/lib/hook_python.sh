. "$(dirname "${BASH_SOURCE[0]}")/real_tool.sh"

mise_shims="${MISE_DATA_DIR:-${XDG_DATA_HOME:-${HOME-}/.local/share}/mise}/shims"
tool_search_path="$PATH:${HOME-}/.local/bin:$mise_shims"

is_mise_shim_dir() {
  [ "${1%/}" = "$mise_shims" ]
}

path_without() {
  local unwanted=$1 dir
  local -a dirs kept=()
  IFS=: read -ra dirs <<< "$2"
  for dir in "${dirs[@]}"; do
    "$unwanted" "$dir" || kept+=("$dir")
  done
  local IFS=:
  printf '%s' "${kept[*]}"
}

run_without_plugin_shims() {
  local env plugin_free_path
  env=$(REAL_TOOL_PATH=$tool_search_path real_tool env)
  plugin_free_path=$(path_without is_shim_dir "$PATH")
  tool_command=("$env" "PATH=$plugin_free_path" "$@")
}

run_through_mise() {
  local provider=$1 name=$2 mise
  mise=$(REAL_TOOL_PATH=$tool_search_path real_tool mise 2>/dev/null) || return 1
  run_without_plugin_shims "$mise" --quiet x "$provider" -- "$name"
}

find_uv() {
  local uv uv_search_path
  uv_search_path=$(path_without is_mise_shim_dir "$tool_search_path")
  if uv=$(REAL_TOOL_PATH=$uv_search_path real_tool uv 2>/dev/null); then
    run_without_plugin_shims "$uv"
  elif ! run_through_mise uv uv; then
    REAL_TOOL_PATH=$uv_search_path real_tool uv
  fi
  uv_command=("${tool_command[@]}")
}

run_uv_outside_projects() {
  (cd / && "${uv_command[@]}" "$@")
}

find_python() {
  run_uv_outside_projects python find --no-config --system '>=3.13'
}

find_hook_python() {
  python=${HARNESS_HOOK_PYTHON-}
  [ ! -x "$python" ] || return 0
  find_uv
  if ! python=$(find_python 2>/dev/null); then
    run_uv_outside_projects python install --no-bin 3.13 >&2
    python=$(find_python)
  fi
}
