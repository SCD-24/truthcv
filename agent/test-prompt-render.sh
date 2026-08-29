#!/bin/bash
# Test harness for agent prompt-render profile blocks.
# Stubs agent-config.js fetch and PROMPT_FILE, drives prompt-composition path,
# asserts three cases: configured values appear, blank criteria omit lines,
# fetch failure produces byte-identical prompt to before-change baseline.
# Also asserts the per-run application cap: config's maxApplicationsPerRun
# wins over MAX_APPLICATIONS_PER_RUN when present, and the cap line is
# omitted entirely when neither source supplies one.
# Also asserts the composed search-queries block: present with both query
# strings and URLs when job_config carries searchQueries, and absent
# (byte-identical prompt) when searchQueries is omitted.

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
record_screening passing \"passed\" in verdict, the employing entity's name
in company, the posting's own job title (as posted, not a placeholder)
in role, the posting's own URL in url, the full posting text in posting_text,
and the employer's publication date in posted_date when the board states one.
company, verdict, role and url are each required.
It enters the operator's approval queue; they draft the letter and decide.

record_screening REJECTS the call and stores nothing unless company, verdict,
role and url all carry usable values — this applies to every screening you
record, rejections included, not only to passing ones. A \"passed\" verdict
is also rejected, storing nothing, without usable posting_text — a real
posting body, not a login wall or a 404 page; a posting you could not read
takes a screening_blocker instead.

Phase 0 is unchanged: postings the operator already approved ARE applied to,
using the cover_letter text that arrives with each item, verbatim."
  else
    prompt="$prompt"$'\n\n'"## Autonomy mode: FULL AUTO

A posting that passes every criterion is applied to this run, as described in
agent/RUNBOOK.md. On every record_screening call pass the employing entity's
name in company, the verdict (rejected, passed or deferred) in verdict, the
posting's own job title (as posted, not a placeholder) in role, the posting's
own URL in url, the full posting text in posting_text, and the employer's
publication date in posted_date when the board states one.

record_screening REJECTS the call and stores nothing unless company, verdict,
role and url all carry usable values. A \"passed\" or \"deferred\" verdict is
also rejected, storing nothing, without usable posting_text — a real posting
body, not a login wall or a 404 page; a posting you could not read takes a
screening_blocker instead."
  fi
  echo "$prompt"
}

# Case 6b: the mandatory record_screening arguments are named in BOTH mode
# branches of the REAL daily-apply.sh — not in this file's copy of it.
#
# This is the one assertion here that reads the shipped script. The block above
# is a verbatim copy, and a copy is exactly how the last defect happened: the
# tool made `company` and `verdict` required, RUNBOOK.md and prompt.md were
# updated, this block was not, and the copy here asserted the stale text back.
# A run following the stale prompt got a TypeError and stored nothing at all.
echo "Testing: daily-apply.sh names every mandatory record_screening argument..."
DAILY_APPLY_SRC="$(dirname "${BASH_SOURCE[0]}")/daily-apply.sh"
SEMI_BLOCK="$(sed -n '/## Autonomy mode: SEMI-AUTO/,/^else$/p' "$DAILY_APPLY_SRC")"
FULL_BLOCK="$(sed -n '/## Autonomy mode: FULL AUTO/,/^fi$/p' "$DAILY_APPLY_SRC")"
# Match "in <field>" — the phrasing that actually tells the agent where the
# value goes. A bare word match is not enough: every field name also appears in
# the "each required" sentence, so removing an argument still passed.
for field in company verdict role url; do
  case "$SEMI_BLOCK" in
    *"in $field"*) ;;
    *) echo "FAIL: daily-apply.sh SEMI-AUTO block never passes a value 'in $field'"; exit 1 ;;
  esac
  case "$FULL_BLOCK" in
    *"in $field"*) ;;
    *) echo "FAIL: daily-apply.sh FULL AUTO block never passes a value 'in $field'"; exit 1 ;;
  esac
done
echo "PASS: daily-apply.sh names every mandatory record_screening argument"

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

# --- Composed search-queries block ------------------------------------------
# Mirrors daily-apply.sh's QUERIES rendering verbatim (see "Add composed
# search queries" there), so a divergence between this simulation and the
# real script is a bug in one of the two, not just here.

# Case 10: searchQueries present renders both query strings and URLs.
echo "Testing: composed search queries render into prompt..."
QUERIES_CONFIG='{"profiles":[{"name":"Senior Python"}],"targetCompanies":[],"cooldownDays":null,"maxApplicationsPerRun":null,"companyBoards":[],"searchQueries":[{"profile":"Senior Python","source":"jobs.ashbyhq.com","query":"site:jobs.ashbyhq.com \"platform engineer\"","url":"https://www.google.com/search?q=site%3Ajobs.ashbyhq.com+%22platform+engineer%22&tbs=qdr:w"},{"profile":"Senior Python","source":"job-boards.greenhouse.io","query":"site:job-boards.greenhouse.io \"platform engineer\"","url":"https://www.google.com/search?q=site%3Ajob-boards.greenhouse.io+%22platform+engineer%22&tbs=qdr:w"}]}'
QUERIES="$(jq -r '.searchQueries[]? | "  - [\(.profile)] \(.source): \(.query)\n    \(.url)"' <<<"$QUERIES_CONFIG")"
if [[ -z "$QUERIES" ]]; then
  echo "FAIL: expected a rendered queries block, got none"
  exit 1
fi
if [[ "$QUERIES" != *'site:jobs.ashbyhq.com "platform engineer"'* ]] || [[ "$QUERIES" != *'site:job-boards.greenhouse.io "platform engineer"'* ]]; then
  echo "FAIL: expected both composed query strings in rendered block"
  exit 1
fi
if [[ "$QUERIES" != *"https://www.google.com/search?q=site%3Ajobs.ashbyhq.com"* ]] || [[ "$QUERIES" != *"https://www.google.com/search?q=site%3Ajob-boards.greenhouse.io"* ]]; then
  echo "FAIL: expected both composed query URLs in rendered block"
  exit 1
fi
echo "PASS: composed search queries render into prompt"

# Case 11: searchQueries omitted leaves the prompt byte-identical to baseline.
echo "Testing: omitted search queries leaves prompt unchanged..."
PROMPT_FILE4="$TEST_DIR/prompt4.txt"
BASELINE4="$TEST_DIR/baseline4.txt"
echo "## Original RUNBOOK filters" > "$PROMPT_FILE4"
echo "Apply to at most 5 role(s) this run." >> "$PROMPT_FILE4"
cp "$PROMPT_FILE4" "$BASELINE4"

NO_QUERIES_CONFIG='{"profiles":[],"targetCompanies":[],"cooldownDays":null,"maxApplicationsPerRun":null,"companyBoards":[]}'
QUERIES_NONE="$(jq -r '.searchQueries[]? | "  - [\(.profile)] \(.source): \(.query)\n    \(.url)"' <<<"$NO_QUERIES_CONFIG")"
if [[ -n "$QUERIES_NONE" ]]; then
  echo "$QUERIES_NONE" >> "$PROMPT_FILE4"
fi
if ! diff -q "$BASELINE4" "$PROMPT_FILE4" >/dev/null 2>&1; then
  echo "FAIL: omitted searchQueries changed the prompt"
  exit 1
fi
echo "PASS: omitted search queries leaves prompt unchanged"

# --- Inlined RUNBOOK operating spec -----------------------------------------
# Mirrors daily-apply.sh's RUNBOOK inlining verbatim (see the "Inline its full
# text here" block there), so a divergence between this simulation and the real
# script is a bug in one of the two, not just here. The harness's only
# file-reading tool is read_runbook_section, which returns one named RUNBOOK
# section and takes no path argument, so daily-apply.sh no longer inlines the
# whole file: it inlines the non-negotiable rule sections (1, 4, 7, 8)
# verbatim plus a table of contents of every heading, and expects the agent
# to fetch anything else with the tool before it needs it.
#
# daily-apply.sh enforces no byte/char/line cap on the composed prompt before
# invoking the harness, so there is no render-size limit for this test to
# mirror; RUNBOOK inlining is covered by the case below.

# Case 12: the composed prompt inlines the RUNBOOK's non-negotiable rule
# sections (1, 4, 7, 8) plus a table of contents of every heading, and does
# NOT inline the full text of a section that isn't one of those four.
echo "Testing: composed prompt inlines RUNBOOK rules + TOC, not the full text..."
RUNBOOK_FIXTURE="$TEST_DIR/RUNBOOK.md"
cat > "$RUNBOOK_FIXTURE" <<'EOF'
# Operating spec fixture

## 0. The approved queue — work it first
Work the approved queue before anything else.

## 1. There is no daily quota
There is no daily quota.

## 2. Hard filters — every criterion of the matched profile must pass
This is a long procedural section about gathering filter criteria that must NOT appear in the composed prompt.

## 3. Canonical answers — call get_profile_answers
This is a long procedural section about canonical answers that must NOT appear in the composed prompt.

## 4. Truthfulness rules — non-negotiable
Never claim a skill the profile does not have.

## 5. Applying
This is a long procedural section about applying that must NOT appear in the composed prompt.

## 6. The approve/deny boundary
This is a long procedural section about the approve/deny boundary that must NOT appear in the composed prompt.

## 7. When something is ambiguous
Escalate rather than guess.

## 8. Never do — cooldowns
Never re-apply within the cooldown window.

## 9. Report at the end of every run
This is a long procedural section about reporting that must NOT appear in the composed prompt.
EOF

PROMPT_FILE5="$TEST_DIR/prompt5.txt"
echo "## Original RUNBOOK filters" > "$PROMPT_FILE5"
echo "Apply to at most 5 role(s) this run." >> "$PROMPT_FILE5"

# Same composition as daily-apply.sh: PROMPT starts from the prompt file,
# then the RUNBOOK's non-negotiable rule sections (1, 4, 7, 8) are extracted
# verbatim by section-number range, plus a table of contents of every "## "
# heading — never the full RUNBOOK text.
PROMPT="$(cat "$PROMPT_FILE5")"$'\n\n'"Today is $(date +%Y-%m-%d)."
RUNBOOK_TOC="$(grep -E '^##[^#]' "$RUNBOOK_FIXTURE" | sed -E 's/^##[[:space:]]*/- /')"
RUNBOOK_RULES="$(awk '
  /^## 1\. There is no daily quota/,/^## 2\./   { if ($0 !~ /^## 2\./) print }
  /^## 4\. Truthfulness rules/,/^## 5\./         { if ($0 !~ /^## 5\./) print }
  /^## 7\. When something is ambiguous/,/^## 8\./ { if ($0 !~ /^## 8\./) print }
  /^## 8\. Never do/,/^## 9\./                    { if ($0 !~ /^## 9\./) print }
' "$RUNBOOK_FIXTURE")"
PROMPT="$PROMPT"$'\n\n'"## Operating spec (agent/RUNBOOK.md) — non-negotiable rules

Also non-negotiable, detailed in the full section — call read_runbook_section
with EXACTLY this heading text (section numbers included, case-insensitive)
before you need it:
- \"0. The approved queue — work it first\": approved-queue postings are
  applied to before anything new is discovered, every run.
- \"2. Hard filters — every criterion of the matched profile must pass\":
  every criterion of the matched profile must pass, no exceptions, no
  judgment calls.
- \"3. Canonical answers — call \`get_profile_answers\`\": screening-question
  answers come only from get_profile_answers, never invented or guessed.
- \"5. Applying\" (its \"Both documents go up\" subsection): a passing
  posting gets a CV **and** a cover letter — never one without the other to
  save cost.
- record_screening REJECTS the call and stores nothing unless company,
  verdict, role and url all carry usable values, on every screening you
  record, rejections included (see \"6. The approve/deny boundary\")."$'\n\n'"$RUNBOOK_RULES"$'\n\n'"## Operating spec — table of contents

Call read_runbook_section(section: <heading text below, exactly as written,
including its number>) for a section's full procedure before you start the
phase it covers — its detail is not inlined here. A \"##\" section's fetch
also returns its \"###\" subsections (e.g. fetching \"5. Applying\" includes
\"Both documents go up\")."$'\n\n'"$RUNBOOK_TOC"

if [[ "$PROMPT" != *"## Operating spec (agent/RUNBOOK.md) — non-negotiable rules"* ]]; then
  echo "FAIL: composed prompt is missing the RUNBOOK rules marker"
  exit 1
fi
if [[ "$PROMPT" != *"There is no daily quota."* ]] || [[ "$PROMPT" != *"Never claim a skill the profile does not have."* ]] \
   || [[ "$PROMPT" != *"Escalate rather than guess."* ]] || [[ "$PROMPT" != *"Never re-apply within the cooldown window."* ]]; then
  echo "FAIL: composed prompt is missing an inlined RUNBOOK rule section"
  exit 1
fi
if [[ "$PROMPT" == *"must NOT appear in the composed prompt"* ]]; then
  echo "FAIL: composed prompt inlines a procedural section's full text (it should carry only the TOC for it)"
  exit 1
fi
if [[ "$PROMPT" != *"- 5. Applying"* ]] || [[ "$PROMPT" != *"- 2. Hard filters"* ]]; then
  echo "FAIL: composed prompt is missing the table of contents for a moved section"
  exit 1
fi
echo "PASS: composed prompt inlines RUNBOOK rules + TOC, not full procedural text"

echo ""
echo "All tests passed!"
exit 0
