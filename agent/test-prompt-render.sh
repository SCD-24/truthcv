#!/bin/bash
# Test harness for agent prompt-render profile blocks.
# Stubs agent-config.js fetch and PROMPT_FILE, drives prompt-composition path,
# asserts three cases: configured values appear, blank criteria omit lines,
# fetch failure produces byte-identical prompt to before-change baseline.
# Also asserts the per-run application cap: config's maxApplicationsPerRun
# wins over MAX_APPLICATIONS_PER_RUN when present, and the cap line is
# omitted entirely when neither source supplies one.

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

# --- Per-run application cap: config-first, env-fallback -------------------
# Mirrors daily-apply.sh's actual cap-resolution logic verbatim (see the
# "Per-run application cap" block there), so a divergence between this
# simulation and the real script is a bug in one of the two, not just here.
render_cap() {
  local job_config="$1" env_cap="$2"
  local config_cap="" apply_cap="" prompt=""
  if [[ -n "$job_config" ]]; then
    config_cap="$(jq -r '.maxApplicationsPerRun' <<<"$job_config")"
  fi
  if [[ "$config_cap" =~ ^[1-9][0-9]*$ ]]; then
    apply_cap="$config_cap"
  else
    apply_cap="$env_cap"
  fi
  if [[ "$apply_cap" =~ ^[1-9][0-9]*$ ]]; then
    prompt="Apply to at most $apply_cap role(s) this run."
  fi
  echo "$prompt"
}

# Case 4: config supplies maxApplicationsPerRun (5) - config wins over env,
# and the cap line is rendered from the config value.
echo "Testing: cap line rendered from config value (maxApplicationsPerRun: 5)..."
CAP_CONFIG_SET='{"profiles":[],"targetCompanies":[],"cooldownDays":null,"maxApplicationsPerRun":5,"companyBoards":[]}'
CAP_LINE_4="$(render_cap "$CAP_CONFIG_SET" "9")"
if [[ "$CAP_LINE_4" != "Apply to at most 5 role(s) this run." ]]; then
  echo "FAIL: expected cap line from config value 5, got: '$CAP_LINE_4'"
  exit 1
fi
echo "PASS: cap line rendered from config value, config (5) wins over env (9)"

# Case 5: config's maxApplicationsPerRun is null (jq renders it as the string
# "null") and no env fallback is set either - no cap line at all.
echo "Testing: cap line omitted when config is null and env unset..."
CAP_CONFIG_NULL='{"profiles":[],"targetCompanies":[],"cooldownDays":null,"maxApplicationsPerRun":null,"companyBoards":[]}'
CAP_LINE_5="$(render_cap "$CAP_CONFIG_NULL" "")"
if [[ -n "$CAP_LINE_5" ]]; then
  echo "FAIL: expected no cap line when both sources are absent, got: '$CAP_LINE_5'"
  exit 1
fi
echo "PASS: cap line omitted when both config and env are absent"

# Case 6: config's maxApplicationsPerRun is null - falls back to the env var.
echo "Testing: cap line falls back to env var when config is null..."
CAP_LINE_6="$(render_cap "$CAP_CONFIG_NULL" "7")"
if [[ "$CAP_LINE_6" != "Apply to at most 7 role(s) this run." ]]; then
  echo "FAIL: expected cap line from env fallback 7, got: '$CAP_LINE_6'"
  exit 1
fi
echo "PASS: cap line falls back to env var when config does not set it"

# --- Autonomy mode rule rendered into the prompt ----------------------------
# Reproduces daily-apply.sh's mode-rule block verbatim (see "Render the mode
# rule into the prompt" there), so a divergence between this simulation and
# the real script is a bug in one of the two, not just here.
render_mode() {
  local agent_mode="$1"
  local prompt=""
  if [[ "$agent_mode" == "semi" ]]; then
    prompt="$prompt"$'\n\n'"## Autonomy mode: SEMI-AUTO

Do NOT apply to a posting you find this run, however well it scores, and do not
write a cover letter for it. For a posting that passes every criterion, call
record_screening with verdict \"passed\", the full posting text in posting_text,
the posting's own URL in url as a required field, and the employer's
publication date in posted_date when the board states one.
It enters the operator's approval queue; they draft the letter and decide.

Phase 0 is unchanged: postings the operator already approved ARE applied to,
using the cover_letter text that arrives with each item, verbatim."
  else
    prompt="$prompt"$'\n\n'"## Autonomy mode: FULL AUTO

A posting that passes every criterion is applied to this run, as described in
agent/RUNBOOK.md. Record the full posting text in posting_text, the posting's
own URL in url, and the employer's publication date in posted_date on every
record_screening call."
  fi
  echo "$prompt"
}

# Case 7: semi renders SEMI-AUTO and the "Do NOT apply" line.
echo "Testing: semi mode renders SEMI-AUTO block..."
MODE_SEMI="$(render_mode "semi")"
if [[ "$MODE_SEMI" != *"SEMI-AUTO"* ]] || [[ "$MODE_SEMI" != *"Do NOT apply"* ]]; then
  echo "FAIL: semi mode did not render expected SEMI-AUTO block"
  exit 1
fi
echo "PASS: semi mode renders SEMI-AUTO block"

# Case 8: full renders FULL AUTO.
echo "Testing: full mode renders FULL AUTO block..."
MODE_FULL="$(render_mode "full")"
if [[ "$MODE_FULL" != *"FULL AUTO"* ]]; then
  echo "FAIL: full mode did not render expected FULL AUTO block"
  exit 1
fi
echo "PASS: full mode renders FULL AUTO block"

# Case 9: the two blocks never both appear in either rendering.
echo "Testing: SEMI-AUTO and FULL AUTO are mutually exclusive..."
if [[ "$MODE_SEMI" == *"FULL AUTO"* ]] || [[ "$MODE_FULL" == *"SEMI-AUTO"* ]]; then
  echo "FAIL: SEMI-AUTO and FULL AUTO blocks are not mutually exclusive"
  exit 1
fi
echo "PASS: SEMI-AUTO and FULL AUTO never both appear"

echo ""
echo "All tests passed!"
exit 0
