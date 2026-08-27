#!/usr/bin/env bash
#
# Run TruthCV's checks (lint or test) from any checkout, including a forest
# worktree.
#
# A git worktree gets the tracked files and nothing else: no .venv, and no
# web/node_modules or agent/node_modules. Both live beside the MAIN checkout
# and are shared, so this script resolves the main checkout from git's common
# dir and links the node_modules directories in if they are missing (the
# symlink convention .gitignore already documents) rather than reinstalling
# hundreds of megabytes per worktree.
#
# Usage: scripts/check.sh lint
#        scripts/check.sh test         (all three suites)
#        scripts/check.sh test-python
#        scripts/check.sh test-web
#        scripts/check.sh test-agent
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

# In a worktree, --git-common-dir points at the MAIN checkout's .git; in the
# main checkout it points at its own. Its parent is the main working tree,
# which owns the shared .venv and node_modules.
main_root="$(cd "$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")" && pwd)"

link_node_modules() {
  local pkg="$1"
  if [ ! -e "$repo_root/$pkg/node_modules" ] && [ -d "$main_root/$pkg/node_modules" ]; then
    ln -s "$main_root/$pkg/node_modules" "$repo_root/$pkg/node_modules"
  fi
}

link_node_modules web
link_node_modules agent

pytest_bin="$main_root/.venv/bin/pytest"
[ -x "$pytest_bin" ] || pytest_bin="pytest"

case "${1:-}" in
  lint)
    # There is no Python linter configured in this repo; the TypeScript
    # projects' typecheck is the standing static check.
    npm --prefix web run typecheck
    npm --prefix agent run typecheck
    ;;
  test)
    "$pytest_bin" -q
    npm --prefix web run test
    npm --prefix agent run test
    ;;
  test-python)
    "$pytest_bin" -q
    ;;
  test-web)
    npm --prefix web run test
    ;;
  test-agent)
    npm --prefix agent run test
    ;;
  *)
    echo "usage: scripts/check.sh {lint|test|test-python|test-web|test-agent}" >&2
    exit 2
    ;;
esac
