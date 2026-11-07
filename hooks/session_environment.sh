[ -n "${1-}" ] || return 0
command . "$1/lib/git_identity.sh" || return 0
PATH=${PATH#"$1":}
mise_shims="${MISE_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/mise}/shims"
case :$PATH: in
  *":$mise_shims:"*) ;;
  *) [ ! -d "$mise_shims" ] || PATH="$mise_shims:$PATH" ;;
esac
export PATH="$1:$PATH"
export HARNESS_PROJECT_DIR="$2"
[ -z "${3-}" ] || export HARNESS_HOOK_PYTHON="$3"
if [ -z "${harness_git_identity_recorded-}" ]; then
  harness_git_identity_recorded=1
  HARNESS_GIT_IDENTITY=$(git_identity_from_environment)
  export HARNESS_GIT_IDENTITY
fi
