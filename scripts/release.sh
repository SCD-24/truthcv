#!/usr/bin/env bash
# Build the distributable zip.
#
# Uses `git archive`, which can only emit tracked files. .env, data/ and
# answers.local.yaml are all gitignored, so they are excluded structurally
# rather than by a list someone has to keep correct. A plain `zip -r` of the
# working directory would ship the maintainer's API keys, ledger and
# secrets.enc; this cannot, and the assertions below prove it.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

OUT_DIR="$REPO/dist"
REF="HEAD"
while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT_DIR="$2"; shift 2 ;;
    --ref) REF="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

mkdir -p "$OUT_DIR"
SHORT="$(git rev-parse --short "$REF")"
ARCHIVE="$OUT_DIR/truthcv-$SHORT.zip"

git archive --format=zip --prefix="truthcv-$SHORT/" -o "$ARCHIVE" "$REF"

# git archive should make these impossible. Assert anyway: this is the one
# failure in the project that cannot be walked back once the zip is sent.
for forbidden in '.env' 'data/' 'answers.local.yaml'; do
  if unzip -Z1 "$ARCHIVE" | grep -qE "(^|/)${forbidden%/}(/|$)"; then
    rm -f "$ARCHIVE"
    echo "ABORT: $forbidden found in the archive. Not shipping it." >&2
    exit 1
  fi
done

echo "Built $ARCHIVE"
