case $PATH in
  "$1" | "$1":*) ;;
  *) export PATH="$1:$PATH" ;;
esac
export HARNESS_PROJECT_DIR="$2"
if [ -z "${harness_git_identity_recorded-}" ]; then
  harness_git_identity_recorded=1
  export HARNESS_GIT_IDENTITY="${GIT_AUTHOR_NAME-}|${GIT_AUTHOR_EMAIL-}|${GIT_COMMITTER_NAME-}|${GIT_COMMITTER_EMAIL-}"
fi
