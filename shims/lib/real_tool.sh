is_shim_dir() {
  [ -f "$1/../hooks/work_queue.py" ]
}

handoff_variable() {
  printf 'REAL_TOOL_HANDOFF_%s' "${1//[^A-Za-z0-9]/_}"
}

directories_handed_off_by_this_process() {
  local handoff
  handoff=$(handoff_variable "$1")
  handoff=${!handoff-}
  [ "${handoff%%:*}" = "$$" ] || return 0
  printf '%s' "${handoff#*:}"
}

real_tool() {
  local name=$1 dir handed_off
  local -a dirs
  handed_off=":$(directories_handed_off_by_this_process "$name"):"
  IFS=: read -ra dirs <<< "${REAL_TOOL_PATH:-$PATH}"
  for dir in "${dirs[@]}"; do
    [[ $handed_off == *":$dir:"* ]] && continue
    if [ -f "$dir/$name" ] && [ -x "$dir/$name" ] && ! is_shim_dir "$dir"; then
      printf '%s\n' "$dir/$name"
      return 0
    fi
  done
  echo "$(basename "$0"): $name is not installed" >&2
  return 127
}

exec_real_tool() {
  local name=$1 tool=$2 handoff
  shift 2
  handoff=$(handoff_variable "$name")
  export "$handoff=$$:$(directories_handed_off_by_this_process "$name"):$(dirname "$tool")"
  exec "$tool" "$@"
}
