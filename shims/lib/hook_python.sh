mise_shims="${MISE_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/mise}/shims"
tool_search_path="$PATH:$HOME/.local/bin:$mise_shims"

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

mise_tool_providing() {
  case $1 in
    bun | bunx) echo bun ;;
    cargo) echo rust ;;
    dotnet) echo dotnet ;;
    uv | uvx) echo uv ;;
    *) return 1 ;;
  esac
}

run_through_mise() {
  local name=$1 provider mise
  provider=$(mise_tool_providing "$name") || return 1
  mise=$(REAL_TOOL_PATH=$tool_search_path real_tool mise 2>/dev/null) || return 1
  run_without_plugin_shims "$mise" --quiet x "$provider" -- "$name"
}

find_uv() {
  local uv uv_search_path
  uv_search_path=$(path_without is_mise_shim_dir "$tool_search_path")
  if uv=$(REAL_TOOL_PATH=$uv_search_path real_tool uv 2>/dev/null); then
    run_without_plugin_shims "$uv"
  elif ! run_through_mise uv; then
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
  find_uv
  if ! python=$(find_python 2>/dev/null); then
    run_uv_outside_projects python install --no-bin 3.13 >&2
    python=$(find_python)
  fi
}
