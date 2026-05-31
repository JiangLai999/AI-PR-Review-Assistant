#!/usr/bin/env sh

set -eu

PACKAGE_NAME="ai-pr-review"
PACKAGE_SPEC_PYPI="$PACKAGE_NAME"
GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-JiangLai999/AI-PR-Review-Assistant}"
INSTALL_SOURCE="${INSTALL_SOURCE:-pypi}"

log() {
  printf '%s\n' "$1"
}

fail() {
  printf 'Error: %s\n' "$1" >&2
  exit 1
}

need_command() {
  command -v "$1" >/dev/null 2>&1
}

python_cmd() {
  if need_command python3; then
    printf 'python3'
    return
  fi

  if need_command python; then
    printf 'python'
    return
  fi

  fail "Python 3.12+ was not found. Please install Python first."
}

ensure_pipx() {
  if need_command pipx; then
    return
  fi

  PYTHON_BIN="$(python_cmd)"
  log "pipx not found, installing with $PYTHON_BIN --user..."
  "$PYTHON_BIN" -m pip install --user --upgrade pipx

  USER_BASE="$($PYTHON_BIN -m site --user-base)"
  PATH="$USER_BASE/bin:$PATH"
  export PATH

  "$PYTHON_BIN" -m pipx ensurepath >/dev/null 2>&1 || true

  if ! need_command pipx; then
    fail "pipx installation succeeded but is not on PATH yet. Reopen your shell and retry."
  fi
}

package_spec() {
  case "$INSTALL_SOURCE" in
    pypi)
      printf '%s' "$PACKAGE_SPEC_PYPI"
      ;;
    github)
      printf 'git+https://github.com/%s.git' "$GITHUB_REPOSITORY"
      ;;
    *)
      fail "Unsupported INSTALL_SOURCE: $INSTALL_SOURCE. Use 'pypi' or 'github'."
      ;;
  esac
}

main() {
  log "Installing AI PR Review Assistant"
  log "Source: $INSTALL_SOURCE"
  if [ "$INSTALL_SOURCE" = "github" ]; then
    log "Repository: $GITHUB_REPOSITORY"
  fi

  ensure_pipx

  SPEC="$(package_spec)"
  pipx install --force "$SPEC"

  log ""
  log "Installation completed."
  log "Run: pr-review --help"
  log "Then configure: pr-review config"
}

main "$@"
