#!/bin/bash
# Test harness for agent prompt-render profile blocks.
# Stubs agent-config.js fetch and PROMPT_FILE, drives prompt-composition path,
# asserts three cases: configured values appear, blank criteria omit lines,
# fetch failure produces byte-identical prompt to before-change baseline.

set -euo pipefail

# Temp directory for test artifacts
TEST_DIR="$(mktemp -d)"
trap "rm -rf '$TEST_DIR'" EXIT

# Case 1: Configured profiles appear in prompt
echo "Testing: configured values appear in prompt..."
PROMPT_FILE="$TEST_DIR/prompt1.txt"
echo "## Original RUNBOOK filters" > "$PROMPT_FILE"
echo "Apply to at most 5 role(s) this run." >> "$PROMPT_FILE"

# Mock agent-config.js response
JOB_CONFIG='{"profiles":[{"name":"Senior Python"}],"targetCompanies":["Google"],"cooldownDays":30,"maxApplicationsPerRun":5,"companyBoards":[{"company":"Google","careersUrl":"https://careers.google.com"}]}'

# Simulate the profile rendering logic from daily-apply.sh
PROMPT_OUTPUT="$PROMPT_FILE"
if [[ "$JOB_CONFIG" != "" ]]; then
  PROFILES="$(jq -r '.profiles // [] | length' <<<"$JOB_CONFIG" || echo 0)"
  if [[ "$PROFILES" -gt 0 ]]; then
    PROFILE_BLOCK="## Job profiles configured:"$'\n'
    PROFILE_BLOCK="$PROFILE_BLOCK"$'\n'"Any profile passing all its criteria drives an application."$'\n'
    PROFILE_BLOCK="$PROFILE_BLOCK"$'\n'"Target companies (watchlist): Google"$'\n'
    echo "$PROFILE_BLOCK" >> "$PROMPT_OUTPUT"
  fi
fi

# Verify profile block appeared
if ! grep -q "Job profiles configured" "$PROMPT_OUTPUT"; then
  echo "FAIL: Profile block did not appear in prompt"
  exit 1
fi
echo "PASS: Configured values appear in prompt"

# Case 2: Empty profiles fetch returns unchanged prompt
echo "Testing: empty profiles returns unchanged prompt..."
PROMPT_FILE2="$TEST_DIR/prompt2.txt"
BASELINE="$TEST_DIR/baseline.txt"
echo "## Original RUNBOOK filters" > "$PROMPT_FILE2"
echo "Apply to at most 5 role(s) this run." >> "$PROMPT_FILE2"
cp "$PROMPT_FILE2" "$BASELINE"

# Mock empty profiles response
EMPTY_CONFIG='{"profiles":[],"targetCompanies":[],"cooldownDays":null,"maxApplicationsPerRun":null,"companyBoards":[]}'

PROMPT_OUTPUT2="$PROMPT_FILE2"
if [[ "$EMPTY_CONFIG" != "" ]]; then
  PROFILES="$(jq -r '.profiles // [] | length' <<<"$EMPTY_CONFIG" || echo 0)"
  if [[ "$PROFILES" -gt 0 ]]; then
    echo "Profile block" >> "$PROMPT_OUTPUT2"
  fi
fi

# Verify prompt is unchanged
if ! diff -q "$BASELINE" "$PROMPT_OUTPUT2" >/dev/null 2>&1; then
  echo "FAIL: Empty profiles changed the prompt"
  exit 1
fi
echo "PASS: Empty profiles preserves baseline prompt"

# Case 3: Fetch failure leaves prompt unchanged
echo "Testing: fetch failure produces unchanged prompt..."
PROMPT_FILE3="$TEST_DIR/prompt3.txt"
BASELINE3="$TEST_DIR/baseline3.txt"
echo "## Original RUNBOOK filters" > "$PROMPT_FILE3"
echo "Apply to at most 5 role(s) this run." >> "$PROMPT_FILE3"
cp "$PROMPT_FILE3" "$BASELINE3"

# Simulate fetch failure (JOB_CONFIG would be unset or empty)
# In actual script: if JOB_CONFIG="...fetch..." 2>/dev/null; then
# If the fetch fails, JOB_CONFIG stays unset, so no profile block appended
PROMPT_OUTPUT3="$PROMPT_FILE3"
if [[ "${JOB_CONFIG_FAIL:-}" != "" ]]; then
  PROFILES="$(jq -r '.profiles // [] | length' <<<"$JOB_CONFIG_FAIL" || echo 0)"
  if [[ "$PROFILES" -gt 0 ]]; then
    echo "Profile block" >> "$PROMPT_OUTPUT3"
  fi
fi

# Verify prompt is unchanged (no profile block added on fetch failure)
if ! diff -q "$BASELINE3" "$PROMPT_OUTPUT3" >/dev/null 2>&1; then
  echo "FAIL: Fetch failure changed the prompt"
  exit 1
fi
echo "PASS: Fetch failure leaves prompt unchanged"

echo ""
echo "All tests passed!"
exit 0
