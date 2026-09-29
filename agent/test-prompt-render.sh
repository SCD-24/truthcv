#!/bin/bash
# Test harness for daily-apply.sh's pipeline path.
# Pipeline is the only mode: code discovers/screens, then one short apply
# session runs per posting. This file asserts, against the shipped script:
#  - the pipeline body, apply-failures-file hand-off and rc 3/4/5 loop break;
#  - conditional --screening-* flags and no RUNBOOK text in the posting prompt;
#  - no single/per-channel branch remains, and AGENT_SESSION_MODE=single is
#    actually rejected (behavioural run);
#  - run_harness(prompt_file, finish_tool) and render_remaining_line wiring;
#  - REASON_FILE handling (cleared before each apply session, first failure
#    reason snapshotted and restored).

set -euo pipefail

# Temp directory for test artifacts
TEST_DIR="$(mktemp -d)"
trap "rm -rf '$TEST_DIR'" EXIT

DAILY_APPLY_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/daily-apply.sh"

echo "Testing: daily-apply.sh pipeline branch and harness flags..."
DA_ALL="$(cat "$DAILY_APPLY_SRC")"
case "$DA_ALL" in *'PIPELINE_CLI='*) ;; *) echo "FAIL: no pipeline body"; exit 1 ;; esac
case "$DA_ALL" in *'--apply-failures-file "$APPLY_FAILURES_FILE"'*) ;; *) echo "FAIL: finish is not passed --apply-failures-file"; exit 1 ;; esac
case "$DA_ALL" in *'[[ "$SESSION_RC" == 3 || "$SESSION_RC" == 4 || "$SESSION_RC" == 5 ]]'*) ;; *) echo "FAIL: rc 3/4/5 no longer break the apply loop"; exit 1 ;; esac
case "$DA_ALL" in *'note_rc apply "$SESSION_RC"'*) ;; *) echo "FAIL: systemic apply rc is not recorded via note_rc"; exit 1 ;; esac
case "$DA_ALL" in *'[[ -n "${AGENT_SCREENING_MODEL:-}" ]] && extra+='*) ;; *) echo "FAIL: --screening-* not conditional"; exit 1 ;; esac
case "$DA_ALL" in *'--screening-model "${AGENT_SCREENING_MODEL:-'*) echo "FAIL: run_harness still defaults --screening-*"; exit 1 ;; esac
PIPE_BODY="$(grep 'printf .Date:' "$DAILY_APPLY_SRC" || true)"
case "$PIPE_BODY" in *RUNBOOK*) echo "FAIL: per-posting prompt carries RUNBOOK text"; exit 1 ;; esac
echo "PASS: pipeline branch, conditional screening flags, no RUNBOOK in posting prompt"

echo "Testing: daily-apply.sh has no single/per-channel branch and rejects AGENT_SESSION_MODE=single..."
if grep -q -e 'per-channel"' -e '== "single"' -e 'render_session_block' -e 'run_session' "$DAILY_APPLY_SRC"; then
  echo "FAIL: daily-apply.sh still carries a single/per-channel branch"
  exit 1
fi
MODE_ERR="$TEST_DIR/mode.err"
MODE_RC=0
AGENT_SESSION_MODE=single RUN_LOG_DIR="$TEST_DIR/runs" TRUTHCV_RUN_ID=modetest bash "$DAILY_APPLY_SRC" >/dev/null 2>"$MODE_ERR" || MODE_RC=$?
if [[ "$MODE_RC" -eq 0 ]]; then
  echo "FAIL: AGENT_SESSION_MODE=single exited 0"
  exit 1
fi
if ! grep -q 'pipeline is the only mode' "$MODE_ERR"; then
  echo "FAIL: AGENT_SESSION_MODE=single did not report 'pipeline is the only mode' on stderr (got: $(cat "$MODE_ERR"))"
  exit 1
fi
echo "PASS: pipeline is the only mode; AGENT_SESSION_MODE=single is rejected (rc=$MODE_RC)"

echo "Testing: run_harness takes a prompt file and finish tool as arguments..."
if ! grep -q 'local prompt_file="\$1" finish_tool="\$2"' "$DAILY_APPLY_SRC"; then
  echo "FAIL: run_harness was not refactored to take (prompt_file, finish_tool) arguments"
  exit 1
fi
if ! grep -q -- '--finish-tool "\$finish_tool"' "$DAILY_APPLY_SRC"; then
  echo "FAIL: run_harness does not pass --finish-tool to the CLI"
  exit 1
fi
echo "PASS: run_harness(prompt_file, finish_tool) refactor present"

echo "Testing: render_remaining_line reads rec.applicationsSubmitted (camelCase) from the runs API..."
if ! grep -q 'rec.applicationsSubmitted' "$DAILY_APPLY_SRC"; then
  echo "FAIL: render_remaining_line does not read the camelCase applicationsSubmitted field"
  exit 1
fi
echo "PASS: render_remaining_line reads applicationsSubmitted"

echo "Testing: daily-apply.sh snapshots FIRST_FAILURE_REASON and restores it after the session loop..."
if ! grep -q 'FIRST_FAILURE_REASON="\$(cat "\$REASON_FILE"' "$DAILY_APPLY_SRC"; then
  echo "FAIL: daily-apply.sh does not snapshot the reason file on the first non-zero session rc"
  exit 1
fi
if ! grep -q 'printf .%s\\n. "\$FIRST_FAILURE_REASON" >"\$REASON_FILE"' "$DAILY_APPLY_SRC"; then
  echo "FAIL: daily-apply.sh does not restore FIRST_FAILURE_REASON to REASON_FILE after the session loop"
  exit 1
fi
echo "PASS: daily-apply.sh snapshots and restores the first non-zero session's reason"

echo "Testing: REASON_FILE is cleared immediately before each apply session..."
if ! grep -B1 'run_harness "\$POSTING_PROMPT_FILE"' "$DAILY_APPLY_SRC" | grep -q 'rm -f "\$REASON_FILE"'; then
  echo "FAIL: apply loop does not rm -f REASON_FILE right before run_harness"
  exit 1
fi
echo "PASS: REASON_FILE cleared before each apply session"

echo ""
echo "All tests passed!"
exit 0
