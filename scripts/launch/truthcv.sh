#!/usr/bin/env bash
# Shared launcher for macOS and Linux. truthcv.command and truthcv.desktop
# both delegate here so there is one implementation, not three.
#
# All real logic lives in `python -m launcher`, run inside a container: macOS
# and Linux ship Python 3 but Windows does not, and Docker is already a hard
# requirement, so it is the one interpreter guaranteed present everywhere.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO"

BOOTSTRAP_IMAGE="python:3-alpine"
MAX_PORT_ATTEMPTS=10

fail() { printf '\n%s\n' "$1" >&2; read -r -p "Press Enter to close." _; exit 1; }

if ! command -v docker >/dev/null 2>&1; then
  fail "TruthCV needs Docker Desktop, which isn't installed.
Download it from https://docs.docker.com/get-docker/ then run this again."
fi

if ! docker info >/dev/null 2>&1; then
  fail "Docker Desktop isn't running. Start it, wait for the whale icon to
settle, then run this again."
fi

# Files the container creates must belong to the user, not root — otherwise
# the generated .env reproduces the PermissionError the README documents for
# the data volume.
run_bootstrap() {
  docker run --rm \
    --user "$(id -u):$(id -g)" \
    -v "$REPO:/work" -w /work \
    "$BOOTSTRAP_IMAGE" python -m launcher --repo /work "$@"
}

APP_PORT="$(run_bootstrap | cut -d= -f2)"

if ! docker compose images -q app 2>/dev/null | grep -q .; then
  printf '%s\n' "Setting up TruthCV for the first time.
This takes about 10 minutes and only happens once."
fi

attempt=1
until docker compose up -d --build 2>compose.err; do
  if ! grep -qiE 'port is already allocated|address already in use|bind for' compose.err; then
    cat compose.err >&2
    fail "TruthCV couldn't start. The log above says why; compose.err has the full text."
  fi
  if [ "$attempt" -ge "$MAX_PORT_ATTEMPTS" ]; then
    fail "Tried $MAX_PORT_ATTEMPTS ports and every one was busy. Something
unusual is holding them — restart the machine and try again."
  fi
  APP_PORT="$(run_bootstrap --bump APP_PORT | cut -d= -f2)"
  attempt=$((attempt + 1))
done
rm -f compose.err

URL="http://localhost:${APP_PORT}"
printf '%s\n' "TruthCV is starting at $URL"

for _ in $(seq 1 60); do
  if curl -fsS -o /dev/null "$URL"; then break; fi
  sleep 2
done

if command -v open >/dev/null 2>&1; then open "$URL"
elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"
else printf '%s\n' "Open $URL in your browser."
fi
