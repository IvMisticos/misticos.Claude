. "$(dirname "${BASH_SOURCE[0]}")/real_tool.sh"

mise_shims="${MISE_DATA_DIR:-${XDG_DATA_HOME:-${HOME-}/.local/share}/mise}/shims"

tool_search_path() {
  printf '%s' "$PATH:${HOME-}/.local/bin:$mise_shims"
}

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

plugin_free_path() {
  path_without is_shim_dir "$PATH"
}

find_mise() {
  REAL_TOOL_PATH=$(tool_search_path) real_tool mise 2>/dev/null
}

run_without_plugin_shims() {
  local path
  path=$(plugin_free_path)
  PATH=$path "$@"
}

run_uv_outside_projects() {
  local search uv mise
  search=$(path_without is_mise_shim_dir "$(tool_search_path)")
  if uv=$(REAL_TOOL_PATH=$search real_tool uv 2>/dev/null); then
    (cd / && run_without_plugin_shims "$uv" "$@")
  elif mise=$(find_mise); then
    (cd / && run_without_plugin_shims "$mise" --quiet x uv -- uv "$@")
  else
    REAL_TOOL_PATH=$search real_tool uv
  fi
}

find_python() {
  run_uv_outside_projects python find --no-config --system '>=3.13'
}

hook_python() {
  if [ -x "${HARNESS_HOOK_PYTHON-}" ]; then
    printf '%s\n' "$HARNESS_HOOK_PYTHON"
    return
  fi
  find_python 2>/dev/null && return
  run_uv_outside_projects python install --no-bin 3.13 >&2 || return
  find_python
}
