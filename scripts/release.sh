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
#
# Extended regexes matched against the archive's path listing. `.env.example`
# must NOT match — it is meant to ship. `.env.backup-*` must match: the
# launcher writes those beside .env and they carry the same live secrets.
FORBIDDEN_PATTERNS=(
  '(^|/)\.env(/|$)'
  '(^|/)\.env\.backup-'
  '(^|/)data(/|$)'
  '(^|/)answers\.local\.yaml(/|$)'
)
for pattern in "${FORBIDDEN_PATTERNS[@]}"; do
  if unzip -Z1 "$ARCHIVE" | grep -qE "$pattern"; then
    rm -f "$ARCHIVE"
    echo "ABORT: archive matched forbidden pattern $pattern. Not shipping it." >&2
    exit 1
  fi
done

echo "Built $ARCHIVE"
