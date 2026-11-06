git_identity_from_environment() {
  printf '%s|%s|%s|%s' "${GIT_AUTHOR_NAME-}" "${GIT_AUTHOR_EMAIL-}" \
    "${GIT_COMMITTER_NAME-}" "${GIT_COMMITTER_EMAIL-}"
}

git_identity_environment_is_set() {
  [ "$(git_identity_from_environment)" != "|||" ]
}
