#!/usr/bin/env bash
# macOS double-click entry. Finder runs .command files in Terminal; all logic
# lives in truthcv.sh so there is one implementation to maintain.
exec "$(dirname "${BASH_SOURCE[0]}")/truthcv.sh"
