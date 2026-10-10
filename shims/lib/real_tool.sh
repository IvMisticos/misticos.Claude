is_shim_dir() {
  [ -f "$1/../hooks/work_queue.py" ]
}

real_tool() {
  local name=$1 dir
  local -a dirs
  IFS=: read -ra dirs <<< "${REAL_TOOL_PATH:-$PATH}"
  for dir in "${dirs[@]}"; do
    if [ -f "$dir/$name" ] && [ -x "$dir/$name" ] && ! is_shim_dir "$dir"; then
      printf '%s\n' "$dir/$name"
      return 0
    fi
  done
  echo "$(basename "$0"): $name is not installed" >&2
  return 127
}
