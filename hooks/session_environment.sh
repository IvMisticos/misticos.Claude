[ -n "${1-}" ] || return 0
PATH=${PATH#"$1":}
mise_shims="${MISE_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/mise}/shims"
case :$PATH: in
  *":$mise_shims:"*) ;;
  *) [ ! -d "$mise_shims" ] || PATH="$mise_shims:$PATH" ;;
esac
export PATH="$1:$PATH"
export HARNESS_PROJECT_DIR="$2"
if [ -z "${harness_git_identity_recorded-}" ]; then
  harness_git_identity_recorded=1
  export HARNESS_GIT_IDENTITY="${GIT_AUTHOR_NAME-}|${GIT_AUTHOR_EMAIL-}|${GIT_COMMITTER_NAME-}|${GIT_COMMITTER_EMAIL-}"
fi
