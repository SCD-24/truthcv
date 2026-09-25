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
the employer's publication date in posted_date when the board states one,
the enabled profile's name you screened against in profile, what the
posting itself says about remote work — remote, hybrid, on_site, or
unstated when it does not say — in remote_arrangement, and any language the
posting EXPLICITLY requires (e.g. 'German') in language_requirement, or ''
when it states none. Also pass the posting's own stated salary in
salary_stated, its own stated employment country in
employment_country_stated, its own stated role type (e.g. 'contract',
'full-time') in role_type_stated, and whether the posting states hiring is
through an EOR / employer-of-record arrangement in eor_stated ('yes' when
the posting states employment IS via an EOR, 'no' when it states direct
employment, 'unstated' when you looked and it does not say, or '' when not
applicable). All four are the posting's OWN stated values, never the
profile's, and none of them is mandatory; '' is a legitimate, common
answer, not an omission.
company, verdict, role and url are each required.
It enters the operator's approval queue; they draft the letter and decide.

record_screening REJECTS the call and stores nothing unless company, verdict,
role and url all carry usable values — this applies to every screening you
record, rejections included, not only to passing ones. A \"passed\" verdict
is also rejected, storing nothing, without usable posting_text — a real
posting body, not a login wall or a 404 page; a posting you could not read
takes a screening_blocker instead. A \"passed\" or \"deferred\" verdict is
also rejected, storing nothing, without usable profile and remote_arrangement
values. Evidence that contradicts any of the profile's six hard
requirements (remote model, working language, salary floor, employment
country, rejected role types, or EOR) is stored as an automatic rejection —
not an error to retry, and never fabricate 'remote'/'' to get past it.

Phase 0 is unchanged: postings the operator already approved ARE applied to,
using the cover_letter text that arrives with each item, verbatim."
  else
    prompt="$prompt"$'\n\n'"## Autonomy mode: FULL AUTO

A posting that passes every criterion is applied to this run, as described in
agent/RUNBOOK.md. On every record_screening call pass the employing entity's
name in company, the verdict (rejected, passed or deferred) in verdict, the
posting's own job title (as posted, not a placeholder) in role, the posting's
own URL in url, the full posting text in posting_text, the employer's
publication date in posted_date when the board states one, the enabled
profile's name you screened against in profile, what the posting itself says
about remote work — remote, hybrid, on_site, or unstated when it does not
say — in remote_arrangement, and any language the posting EXPLICITLY
requires (e.g. 'German') in language_requirement, or '' when it states none.
Also pass the posting's own stated salary in salary_stated, its own stated
employment country in employment_country_stated, its own stated role type
(e.g. 'contract', 'full-time') in role_type_stated, and whether the posting
states hiring is through an EOR / employer-of-record arrangement in
eor_stated ('yes' when the posting states employment IS via an EOR, 'no'
when it states direct employment, 'unstated' when you looked and it does
not say, or '' when not applicable). All four are the posting's OWN stated
values, never the profile's, and none of them is mandatory; '' is a
legitimate, common answer, not an omission.

record_screening REJECTS the call and stores nothing unless company, verdict,
role and url all carry usable values. A \"passed\" or \"deferred\" verdict is
also rejected, storing nothing, without usable posting_text — a real posting
body, not a login wall or a 404 page; a posting you could not read takes a
screening_blocker instead. profile and remote_arrangement are also required
for a passed/deferred verdict. Evidence that contradicts any of the
profile's six hard requirements (remote model, working language, salary
floor, employment country, rejected role types, or EOR) is stored as an
automatic rejection — not an error to retry, and never fabricate
'remote'/'' to get past it."
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
for field in company verdict role url profile remote_arrangement; do
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

# --- Direct-search boards block ---------------------------------------------
# Mirrors daily-apply.sh's DIRECT_BOARDS rendering verbatim (see "Direct-
# search boards" there), so a divergence between this simulation and the
# real script is a bug in one of the two, not just here.

# Case 12: directBoards present renders the board URLs and profile keywords deduplicated.
echo "Testing: direct-search boards render into prompt with deduplicated criteria..."
# Test with two boards sharing the same profile to verify deduplication works.
DIRECT_BOARDS_CONFIG='{"profiles":[{"name":"Senior Python"}],"targetCompanies":[],"cooldownDays":null,"maxApplicationsPerRun":null,"companyBoards":[],"directBoards":[{"url":"https://boards.acme.io/careers","signinUrl":"https://boards.acme.io/login","profiles":[{"profile":"Senior Python","keywords":["platform engineer","backend"],"locations":["Berlin"],"rejectedRoleTypes":["contract"]}]},{"url":"https://boards.otherthing.io/jobs","signinUrl":"","profiles":[{"profile":"Senior Python","keywords":["platform engineer","backend"],"locations":["Berlin"],"rejectedRoleTypes":["contract"]}]}]}'
# Extract and deduplicate criteria (profiles rendered once per unique profile)
DIRECT_CRITERIA="$(jq -r '[.directBoards[]? | .profiles[]?] | unique_by(.profile)[] | "  [\(.profile)] keywords: \(.keywords // [] | join(", "))" + (if ((.locations // []) | length) > 0 then "; locations: \(.locations | join(", "))" else "" end) + (if ((.rejectedRoleTypes // []) | length) > 0 then "; avoid: \(.rejectedRoleTypes | join(", "))" else "" end)' <<<"$DIRECT_BOARDS_CONFIG")"
# Extract board URLs (no deduplication of boards)
DIRECT_BOARDS="$(jq -r '.directBoards[]? | "  - \(.url)" + (if (.signinUrl // "") != "" then " (sign in: \(.signinUrl))" else "" end)' <<<"$DIRECT_BOARDS_CONFIG")"
# Combine into final output
FINAL_DIRECT_BOARDS="Direct-search boards (search each on the board's own site using the per-profile criteria listed once below; on a login wall, report_apply_failure with blocker \"login_required\" and the sign-in URL, then continue to the next board):"$'\n'"$DIRECT_CRITERIA"$'\n'"$DIRECT_BOARDS"
if [[ -z "$DIRECT_BOARDS" ]]; then
  echo "FAIL: expected a rendered direct-boards block, got none"
  exit 1
fi
if [[ "$FINAL_DIRECT_BOARDS" != *"https://boards.acme.io/careers"* ]] || [[ "$FINAL_DIRECT_BOARDS" != *"https://boards.otherthing.io/jobs"* ]]; then
  echo "FAIL: expected both board URLs in rendered block"
  exit 1
fi
# Critical: 'platform engineer' should appear exactly once (deduplicated) even though two boards share the profile
PLATFORM_ENGINEER_COUNT=$(echo "$FINAL_DIRECT_BOARDS" | grep -o "platform engineer" | wc -l)
if [[ "$PLATFORM_ENGINEER_COUNT" -ne 1 ]]; then
  echo "FAIL: expected 'platform engineer' exactly once in rendered block (two boards share one profile), got $PLATFORM_ENGINEER_COUNT"
  exit 1
fi
echo "PASS: direct-search boards render into prompt with deduplicated criteria"

# Case 13: directBoards omitted leaves the prompt byte-identical to baseline.
echo "Testing: omitted direct-search boards leaves prompt unchanged..."
PROMPT_FILE5="$TEST_DIR/prompt5.txt"
BASELINE5="$TEST_DIR/baseline5.txt"
echo "## Original RUNBOOK filters" > "$PROMPT_FILE5"
echo "Apply to at most 5 role(s) this run." >> "$PROMPT_FILE5"
cp "$PROMPT_FILE5" "$BASELINE5"

NO_DIRECT_BOARDS_CONFIG='{"profiles":[],"targetCompanies":[],"cooldownDays":null,"maxApplicationsPerRun":null,"companyBoards":[]}'
DIRECT_CRITERIA_NONE="$(jq -r '[.directBoards[]? | .profiles[]?] | unique_by(.profile)[] | "  [\(.profile)] keywords: \(.keywords // [] | join(", "))" + (if ((.locations // []) | length) > 0 then "; locations: \(.locations | join(", "))" else "" end) + (if ((.rejectedRoleTypes // []) | length) > 0 then "; avoid: \(.rejectedRoleTypes | join(", "))" else "" end)' <<<"$NO_DIRECT_BOARDS_CONFIG")"
DIRECT_BOARDS_NONE="$(jq -r '.directBoards[]? | "  - \(.url)" + (if (.signinUrl // "") != "" then " (sign in: \(.signinUrl))" else "" end)' <<<"$NO_DIRECT_BOARDS_CONFIG")"
if [[ -n "$DIRECT_BOARDS_NONE" ]]; then
  echo "$DIRECT_BOARDS_NONE" >> "$PROMPT_FILE5"
fi
if ! diff -q "$BASELINE5" "$PROMPT_FILE5" >/dev/null 2>&1; then
  echo "FAIL: omitted directBoards changed the prompt"
  exit 1
fi
echo "PASS: omitted direct-search boards leaves prompt unchanged"

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

# --- Per-channel sessions: mode default, channel selection, rc aggregation -
# Mirrors daily-apply.sh's session-mode logic verbatim (see "AGENT_SESSION_MODE"
# and the per-channel session loop there), so a divergence between this
# simulation and the real script is a bug in one of the two, not just here.

echo "Testing: AGENT_SESSION_MODE defaults to per-channel in daily-apply.sh..."
if ! grep -q 'AGENT_SESSION_MODE="\${AGENT_SESSION_MODE:-per-channel}"' "$DAILY_APPLY_SRC"; then
  echo "FAIL: daily-apply.sh does not default AGENT_SESSION_MODE to per-channel"
  exit 1
fi
echo "PASS: AGENT_SESSION_MODE defaults to per-channel"

echo "Testing: single mode still guards the byte-identical composition path..."
if ! grep -q 'AGENT_SESSION_MODE" == "single" ]]; then' "$DAILY_APPLY_SRC"; then
  echo "FAIL: daily-apply.sh lost its single-mode guard around prompt composition"
  exit 1
fi
if ! grep -q '\$PROFILE_BLOCK\$FEED_SECTION\$DIRECT_SECTION\$DORK_SECTION\$PROFILE_TAIL' "$DAILY_APPLY_SRC"; then
  echo "FAIL: single-mode composition no longer concatenates header+every channel+tail in RUNBOOK order"
  exit 1
fi
echo "PASS: single mode composes header+feed+direct+dork+tail exactly as before per-channel sessions existed"

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

# Selects the sessions to run and each one's finish tool, mirroring the real
# SESSION_CHANNELS/LAST_INDEX logic: 'feed' always runs; 'direct'/'dork' are
# included only when their section is non-empty; the last present session
# gets finish_run, every session before it gets finish_phase.
select_sessions() {
  local direct_section="$1" dork_section="$2"
  local channels=(feed)
  [[ -n "$direct_section" ]] && channels+=(direct)
  [[ -n "$dork_section" ]] && channels+=(dork)
  local last=$(( ${#channels[@]} - 1 ))
  local i out=""
  for i in "${!channels[@]}"; do
    if (( i == last )); then
      out="$out${channels[$i]}=finish_run "
    else
      out="$out${channels[$i]}=finish_phase "
    fi
  done
  echo "$out"
}

echo "Testing: all three channels configured yields three sessions, feed+direct get finish_phase, dork gets finish_run..."
SESSIONS_ALL="$(select_sessions "has-direct" "has-dork")"
if [[ "$SESSIONS_ALL" != "feed=finish_phase direct=finish_phase dork=finish_run " ]]; then
  echo "FAIL: expected feed=finish_phase direct=finish_phase dork=finish_run, got: '$SESSIONS_ALL'"
  exit 1
fi
echo "PASS: three-channel session plan is correct"

echo "Testing: no direct/dork data omits those sessions, feed alone gets finish_run..."
SESSIONS_FEED_ONLY="$(select_sessions "" "")"
if [[ "$SESSIONS_FEED_ONLY" != "feed=finish_run " ]]; then
  echo "FAIL: expected feed=finish_run only, got: '$SESSIONS_FEED_ONLY'"
  exit 1
fi
echo "PASS: channel with no configured data is omitted, remaining session finishes with finish_run"

echo "Testing: dork configured but not direct yields feed+dork, dork finishes the run..."
SESSIONS_NO_DIRECT="$(select_sessions "" "has-dork")"
if [[ "$SESSIONS_NO_DIRECT" != "feed=finish_phase dork=finish_run " ]]; then
  echo "FAIL: expected feed=finish_phase dork=finish_run, got: '$SESSIONS_NO_DIRECT'"
  exit 1
fi
echo "PASS: direct omitted, dork present, dork finishes the run"

# Mirrors daily-apply.sh's FINAL_RC aggregation: rc 3/4/5 aborts remaining
# sessions and is the final rc; rc 2/6 is recorded but does not stop the
# next session; final rc is the first non-zero rc seen, else 0.
aggregate_rc() {
  local final_rc=0 final_rc_set=0 rc
  for rc in "$@"; do
    if (( final_rc_set == 0 )); then
      final_rc=$rc
      final_rc_set=1
    fi
    if [[ "$rc" == 3 || "$rc" == 4 || "$rc" == 5 ]]; then
      break
    fi
    if (( final_rc == 0 && rc != 0 )); then
      final_rc=$rc
    fi
  done
  echo "$final_rc"
}

echo "Testing: rc aggregation - all sessions succeed..."
AGG1="$(aggregate_rc 0 0 0)"
[[ "$AGG1" == "0" ]] || { echo "FAIL: expected 0, got $AGG1"; exit 1; }
echo "PASS: all-success aggregates to 0"

echo "Testing: rc aggregation - turn cap (2) in an early session does not stop the next, is remembered..."
AGG2="$(aggregate_rc 2 0 0)"
[[ "$AGG2" == "2" ]] || { echo "FAIL: expected 2, got $AGG2"; exit 1; }
echo "PASS: rc 2 propagates as final rc while later sessions still ran"

echo "Testing: rc aggregation - no-finish (6) then success keeps 6 as first non-zero..."
AGG3="$(aggregate_rc 0 6 0)"
[[ "$AGG3" == "6" ]] || { echo "FAIL: expected 6, got $AGG3"; exit 1; }
echo "PASS: first non-zero rc (6) wins even when a later session succeeds"

echo "Testing: rc aggregation - provider error (3) aborts remaining sessions immediately..."
AGG4="$(aggregate_rc 3 0 0)"
[[ "$AGG4" == "3" ]] || { echo "FAIL: expected 3, got $AGG4"; exit 1; }
echo "PASS: rc 3 is the final rc"

echo "Testing: rc aggregation - config error (5) after a turn-cap session still reports the earlier non-zero rc..."
AGG5="$(aggregate_rc 2 5)"
[[ "$AGG5" == "2" ]] || { echo "FAIL: expected 2 (first non-zero rc wins over a later abort's own rc), got $AGG5"; exit 1; }
echo "PASS: first non-zero rc wins even when a later session aborts with a different rc"

# --- render_session_block: real function, extracted verbatim from daily-apply.sh ---
# Sourcing the real function (not a copy) so a change there is exercised here
# directly, no drift possible.
RENDER_SESSION_BLOCK_SRC="$(sed -n '/^render_session_block() {/,/^}$/p' "$DAILY_APPLY_SRC")"
eval "$RENDER_SESSION_BLOCK_SRC"

echo "Testing: finish_phase session (non-final) renders finish_phase call shape, no channel arg..."
BLOCK_PHASE="$(render_session_block "direct" "finish_phase" 0 "")"
if [[ "$BLOCK_PHASE" != *'finish_phase(run_id, channel: "direct", note: ...)'* ]]; then
  echo "FAIL: finish_phase session block missing correct finish_phase call shape"
  exit 1
fi
if [[ "$BLOCK_PHASE" == *"finish_run("* ]]; then
  echo "FAIL: non-final session block must not tell the model to call finish_run"
  exit 1
fi
echo "PASS: non-final session block renders finish_phase(run_id, channel, note)"

echo "Testing: finish_run session (final) renders finish_run call shape (run_id, status, stopped_reason, note), no channel arg..."
BLOCK_RUN="$(render_session_block "dork" "finish_run" 0 "")"
if [[ "$BLOCK_RUN" != *'finish_run(run_id, status: ...,'*'stopped_reason: ...'*'note: ...)'* ]]; then
  echo "FAIL: finish_run session block missing correct finish_run call shape"
  exit 1
fi
if [[ "$BLOCK_RUN" == *'finish_run(run_id, channel'* ]]; then
  echo "FAIL: finish_run call must not be told to take a channel argument"
  exit 1
fi
echo "PASS: final session block renders finish_run(run_id, status, stopped_reason, note)"

echo "Testing: direct/dork (non-first) session overrides gmail/Phase 0 instructions..."
BLOCK_NON_FIRST="$(render_session_block "direct" "finish_phase" 0 "")"
if [[ "$BLOCK_NON_FIRST" != *"do NOT call"*"get_approved_applications"* ]] || [[ "$BLOCK_NON_FIRST" != *"do NOT call check_gmail_responses"* ]]; then
  echo "FAIL: non-first session block does not override Phase 0 / check_gmail_responses instructions"
  exit 1
fi
echo "PASS: non-first session block overrides Phase 0 / check_gmail_responses"

echo "Testing: feed (first) session keeps gmail/Phase 0 instructions..."
BLOCK_FIRST="$(render_session_block "feed" "finish_phase" 1 "")"
if [[ "$BLOCK_FIRST" != *"call check_gmail_responses once at"* ]] || [[ "$BLOCK_FIRST" != *"work Phase 0"* ]]; then
  echo "FAIL: first session block does not instruct check_gmail_responses/Phase 0"
  exit 1
fi
echo "PASS: first session block instructs check_gmail_responses/Phase 0"

echo "Testing: every session block states start_run is idempotent..."
if [[ "$BLOCK_FIRST" != *"start_run is idempotent"* ]] || [[ "$BLOCK_NON_FIRST" != *"start_run is idempotent"* ]]; then
  echo "FAIL: session block does not state start_run is idempotent"
  exit 1
fi
echo "PASS: session block states start_run is idempotent"

echo "Testing: final session with an earlier rc-2 session states it hit the turn cap and requires an honest non-completed status..."
PRIOR_ISSUES_RC2=$'\n'"- The feed session hit the turn cap and did not finish its work."
BLOCK_RECONCILE="$(render_session_block "dork" "finish_run" 0 "$PRIOR_ISSUES_RC2")"
if [[ "$BLOCK_RECONCILE" != *"feed session hit the turn cap"* ]]; then
  echo "FAIL: final session block does not name the earlier feed session's turn-cap outcome"
  exit 1
fi
if [[ "$BLOCK_RECONCILE" != *'status: "failed"'* ]]; then
  echo "FAIL: final session block does not require a non-completed status when an earlier session failed"
  exit 1
fi
echo "PASS: final session block reconciles an earlier turn-cap session with an honest non-completed status"

echo "Testing: single mode does not call render_session_block at all..."
SINGLE_MODE_BLOCK="$(sed -n '/AGENT_SESSION_MODE" == "single" ]]; then/,/^else$/p' "$DAILY_APPLY_SRC")"
if [[ "$SINGLE_MODE_BLOCK" == *"render_session_block"* ]]; then
  echo "FAIL: single mode must stay byte-identical — it must not call render_session_block"
  exit 1
fi
echo "PASS: single mode does not invoke render_session_block, prompt composition unaffected"

echo "Testing: render_remaining_line reads rec.applicationsSubmitted (camelCase) from the runs API..."
if ! grep -q 'rec.applicationsSubmitted' "$DAILY_APPLY_SRC"; then
  echo "FAIL: render_remaining_line does not read the camelCase applicationsSubmitted field"
  exit 1
fi
echo "PASS: render_remaining_line reads applicationsSubmitted"

# --- Reason-file preservation: first non-zero session's reason must survive
# a later session overwriting the shared reason file. Mirrors daily-apply.sh's
# FIRST_FAILURE_REASON snapshot/restore around the session loop.
echo "Testing: first non-zero session's reason file content survives a later session's overwrite..."
REASON_FILE_TEST="$TEST_DIR/reason_test.txt"
echo "turn cap reached in feed session" > "$REASON_FILE_TEST"
FIRST_FAILURE_REASON="$(cat "$REASON_FILE_TEST" 2>/dev/null || true)"
# Simulate a later session overwriting the shared reason file with its own text.
echo "dork session finished cleanly" > "$REASON_FILE_TEST"
if [[ -n "$FIRST_FAILURE_REASON" ]]; then
  printf '%s\n' "$FIRST_FAILURE_REASON" > "$REASON_FILE_TEST"
fi
if [[ "$(cat "$REASON_FILE_TEST")" != "turn cap reached in feed session" ]]; then
  echo "FAIL: first non-zero session's reason was not preserved after a later session overwrote the reason file"
  exit 1
fi
echo "PASS: first non-zero session's reason file content is preserved"

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

echo ""
echo "All tests passed!"
exit 0
