# Agent job profiles — design & implementation handoff

Status: **design approved, nothing implemented.** This doc is the specification
and task list for making the unattended application agent's job search fully
user-configurable via multiple job profiles.

Read this section order as written: risky parts first.

---

## 1. NOT DONE

Everything. No code has been written for this feature. Every task in §6 is open.

## 2. UNVERIFIED

All `file:line` references below came from two read-only exploration passes in
the design session, not from the implementer's own reading. Line numbers drift.
**Each task's implementer must re-read its target files before editing; treat
every reference here as a pointer, not a fact.** Specifically re-verify before
building on them:

- `PUT /api/agent/config` does a partial merge via
  `model_dump(exclude_unset=True, exclude_none=True)` (`api/routes.py:704-715`).
  The profiles feature depends on this merge NOT clobbering sibling sections.
  Caution: partial merge is shallow at the top level — decide explicitly whether
  `profiles` is replaced wholesale on PUT (recommended: yes, the client sends the
  full list) and write a test proving concurrent schedule saves don't erase
  profiles.
- `agent-config.js` hard-allowlists exactly `enabled|run_at|run_days|llm_credentials`
  (`agent/agent-config.js:8`). New fields are silently dropped until added there.
- The `Screening` dataclass accepts exactly six verdict keys
  (`applications/model.py:110-130`); `from_dict` drops unknown keys silently.
- Cooldown default is 90 days read from `APPLICATION_COOLDOWN_DAYS` env in
  `screening/cooldown.py:25-31`, settable only on the `app` service, not the agent.
- The agent's composed prompt is exactly `prompt.md` + date + optional cap line
  (`agent/daily-apply.sh:82-90`); RUNBOOK.md is read separately per run but is
  baked into the image (`agent/Dockerfile`, COPY lines ~50-70) — the agent
  container mounts no data volume by explicit design (`docker-compose.yml:80-85`).
- No web-UI exploration was done beyond section names in
  `web/src/agents/AgentsPage.tsx` (docstring ~:137, sections ~:251-601).

## 3. IN FLIGHT

Nothing. No other session or worktree is editing these files as of 2026-08-18.

## 4. DONE

Design only (this document). No commits belong to this feature yet.

---

## 5. Design

### 5.1 Background facts the design rests on

- The agent's job filters today are **prose**, not data: six "hard filters" in
  `agent/RUNBOOK.md` §2 (fully-remote; German employment entity, EOR
  disqualifies; salary ≥ €85k with ask range 95–110k; English working language;
  Glassdoor ≥ 3.5 waived under 20 reviews; agentic-AI/data-engineering role
  types, reject generic full-stack/frontend/SRE/Java-heavy backend). RUNBOOK.md
  is baked into the agent image; changing a filter today means a rebuild.
- **Job discovery is entirely unspecified.** No scraper, no board client, no
  search keywords, no board list anywhere in the agent's runtime inputs. The
  model improvises web searches each run. Filters only reject what it stumbles
  on. `agent/targets.md` is never read by the agent and is not in the image.
- Config that IS structured (`agentconfig/store.py`, persisted at
  `data/agent_config.json`): `enabled`, `blocked_companies`, `run_at`,
  `run_days`. Flows: Agents page → `PUT /api/agent/config` → fetched per run by
  `agent/agent-config.js` (called from `agent/entrypoint.sh` loop and
  `agent/daily-apply.sh`). Fetch failure falls back to env defaults.
- App and agent share **no filesystem and no DB**. Channels: the MCP tool
  surface (`http://app:8080/mcp`, served by `mcp/server.py`), plus two plain
  HTTP endpoints (`/api/agent/config`, `/api/agent/llm-credentials`).
- The applications ledger records screening verdicts under exactly six fixed
  keys: `entity, remote, salary, language, role_type, glassdoor`
  (`applications/model.py`); `applications/log_render.py` renders them,
  including a Glassdoor "waived" state.

### 5.2 Decisions (with the reason each was made)

1. **Structured fields, not a free-text filter editor.** The ledger's fixed
   six-key screening schema silently drops unknown verdict keys, so free-text
   criteria would produce unrecordable verdicts. Filter *kinds* stay fixed;
   *values* become editable.
2. **Comma-delimited multi-item entry.** Every multi-item field is a single
   text input; the user types comma-separated values. API validators split on
   commas, trim, drop empties, store as lists. UI joins with `", "` on load.
   Applies to all current and future multi-item filter fields.
3. **Multiple named job profiles.** `agent_config.json` gains `profiles: []`.
   A posting qualifies if it passes **any single enabled profile in full** — no
   mixing criteria across profiles. Rationale: one applicant can credibly
   target several roles (e.g. systems engineer / Python developer / agentic
   engineer), each with its own search terms and requirements.
4. **Per-profile vs global split.** Per profile: name, enabled toggle, search
   group (keywords, locations, preferred sources), and the full requirements
   set (remote model; employment country + `eor_allowed` +
   `require_entity_verification`; salary floor + ask range; working-language
   rule; Glassdoor threshold + min-review waiver count; accepted/rejected role
   types). Global: blocklist, `cooldown_days`, `max_applications_per_run`
   (a single budget across all profiles, so adding profiles cannot silently
   multiply application volume), schedule.
5. **Blank field = criterion off.** Every requirement field is nullable; a
   blank field means "do not screen on this." Only `name` is mandatory on a
   profile. The rendered prompt includes only the criteria that are set.
6. **Unfindable data = waiver, never rejection.** If a set criterion's
   real-world data cannot be found (e.g. company has no Glassdoor page, no
   posted salary band), the criterion is waived: the posting passes it and the
   verdict is recorded as waived. Salary additionally: no posted band → agent
   states the configured ask range.
7. **Entity verification is the one configurable exception.** Per-profile
   checkbox `require_entity_verification`, default **checked** = today's
   fail-closed behavior ("couldn't determine the employing entity" rejects,
   because that is how EOR arrangements hide; the imprint/entity verification
   procedure is included in the prompt). Unchecked = entity behaves like other
   criteria (waives on absence, rejects only on positive evidence such as a
   named EOR vendor when EOR is disallowed). UI helper text states the
   trade-off. The mandatory-verification prose is included in the rendered
   prompt only when checked.
8. **Delivery via the existing config channel, not an MCP tool.** Filters must
   be in the prompt before the agent starts searching; an MCP tool only helps
   if the model remembers to call it. Schedule/enabled already flow through
   `/api/agent/config` + `agent-config.js`. (Flagged judgment call: this puts
   more config on the plain-HTTP channel instead of the MCP surface.)
9. **Discovery becomes deterministic, no APIs.** Three channels in order:
   (a) composed search URLs — each profile's keywords/locations rendered into
   concrete search URLs on the configured `preferred_sources` boards, which the
   agent opens in Chrome; (b) a global `target_companies` watchlist browsed
   directly; (c) free-form WebSearch demoted to backfill. All navigation, no
   job-board APIs.
10. **Watchlist is names-only; slugs are auto-resolved and cached.** The user
    types company names. A server-side store `data/company_boards.json` maps
    normalized name → discovered careers URL (+ ATS type, resolved date).
    Resolved entries are injected into the prompt each run. Unresolved names:
    the prompt instructs the agent to find the careers page (prefer the
    ATS-hosted board — Ashby `jobs.ashbyhq.com/<slug>`, Greenhouse
    `boards.greenhouse.io/<slug>`, Lever, Personio — over marketing pages) and
    record it via a new MCP tool `record_company_board`. Dead cached URL →
    agent records the failure, re-resolves. UI shows the resolved URL read-only
    per name, with "clear to force re-resolution" and an optional manual URL
    override. Removing a company removes its cache entry.
11. **Cooldown becomes config.** `cooldown_days` on the Agents page;
    `screening/cooldown.py` reads agent config first, `APPLICATION_COOLDOWN_DAYS`
    env as fallback, hardcoded 90 last. The rendered prompt states the
    configured number (the RUNBOOK prose currently self-contradicts: 3 months
    vs the env-driven 90).
12. **Per-run cap becomes config.** `max_applications_per_run` field; existing
    env var stays as fallback when the field is unset.
13. **Fallback philosophy unchanged.** Config fetch failure, or an empty/absent
    `profiles` list, → the baked RUNBOOK defaults act as a single implicit
    profile. Same as the schedule's env fallback today.
14. **Ledger gains an optional `profile` name** on the application record so
    reports show which profile drove each application. Additive; old records
    unaffected. Screening verdict keys unchanged.
15. **Explicitly out of scope** (recorded so it is not re-litigated):
    - Renaming `authorized_non_german_country` (`truth/answers.py:42`, mirrored
      in `api/schemas.py` and `answers.example.yaml`). Load-bearing persisted
      -data rename; known limitation — the answers schema stays German-shaped
      even when `employment_country` is changed.
    - The apply-channel rule (apply on the employer's own site, never via an
      aggregator) and its ATS name list stay as prose.
    - Truthfulness/verification procedure, report format, schedule mechanics,
      cover-letter guardrail: untouched.
    - German anecdotes inside RUNBOOK §2 (Jobfeed/Initech, Duff/EOR
      vendors): dropped from the *rendered* filter block, which states
      configured values only; the RUNBOOK file keeps them as default prose.

### 5.3 Default profile values

New profiles are pre-filled from today's RUNBOOK values (also the implicit
fallback profile): fully remote; employment country Germany, EOR disallowed,
entity verification required; salary floor €85,000, ask range €95,000–110,000;
working language English (reject "German required", allow "German is a plus");
Glassdoor ≥ 3.5 waived under 20 reviews; accepted roles "agentic / AI
engineering, data engineering"; rejected roles "generic full-stack, frontend,
SRE, Java-heavy backend". "Duplicate profile" is the primary creation path in
the UI.

---

## 6. Implementation plan

Sequencing: T1 → T2 → {T3, T4, T5, T6 in any order} → T7. Each task is one
coder dispatch with an independent review. Verification commands (verified
against `pyproject.toml` and `web/package.json` this session):

- Backend: `pytest` from repo root (testpaths = `tests/`).
- Web: `npm test` (vitest) and `npm run typecheck` in `web/`.

Conventions that bind every task: no formatting/import churn outside touched
lines; preserve existing comments; camelCase over the wire via the existing
`_Camel` base in `api/schemas.py`; match each file's surrounding style. Do not
commit to a default branch; branch for the feature. Every behavior change ships
tests; a bugfix-shaped change ships a test that fails against the old code.

### T1 — config store: profiles + new globals
Files: `agentconfig/store.py`, `tests/test_agent_config_store.py`.
Add a `JobProfile` dataclass (fields per §5.2 items 4–7, all requirement fields
optional/nullable, `enabled: bool = True`) and extend `AgentConfig` with
`profiles: list[JobProfile]`, `target_companies: list[str]`,
`cooldown_days: int | None`, `max_applications_per_run: int | None`.
Round-trip (load/save) preserves unknown keys the way the existing store does —
re-read the store's current load/save behavior first; only lines ~22-60 were
examined in design. Done: `pytest tests/test_agent_config_store.py` passes with
new round-trip, defaulting, and empty-profiles cases.

### T2 — API schema + routes
Files: `api/schemas.py`, `api/routes.py` (only if the merge needs changes),
`tests/test_agent_config_api.py`.
Extend `AgentConfigModel`/`AgentConfigUpdate` with the new fields. Validators:
comma-split/trim/drop-empties for all multi-item fields (mirror the existing
blocklist normalization); salary values > 0 and floor ≤ ask-min ≤ ask-max when
all present; Glassdoor 0–5; cooldown_days ≥ 0; cap ≥ 1; profile names non-empty
and unique after trim. `profiles` replaces wholesale on PUT; sibling top-level
fields still merge partially. Done: API tests cover each validator's reject
case, a wholesale-profiles-replace case, and a "schedule PUT does not erase
profiles" case; `pytest` green.

### T3 — agent-side delivery + prompt rendering
Files: `agent/agent-config.js` (allowlist), `agent/daily-apply.sh`,
`agent/RUNBOOK.md` (§2 marked as defaults-when-unconfigured), possibly
`agent/entrypoint.sh`.
Fetch the new fields; render per enabled profile: a search-strategy block
(concrete search URLs composed from keywords × locations × preferred sources;
state the deterministic order: boards → watchlist → WebSearch backfill) and a
requirements block containing only set criteria, each with waiver semantics
("if this information cannot be found, treat as waived and record it as
waived"), entity fail-closed prose only when `require_entity_verification`.
Render global lines: cap (config over env), cooldown number, watchlist with
resolved URLs and resolve-instructions for unresolved names. Any-profile-passes
rule and record-which-profile instruction. Fetch failure or empty profiles →
baked defaults, unchanged behavior. Done: a shell-level test or fixture render
proving (a) configured values appear, (b) blank criteria are absent, (c)
fallback path emits the default block. Note: check how `daily-apply.sh` is
currently tested before inventing a harness; none was identified in design.

### T4 — company-board resolution store + MCP tool
Files: new store module (follow `agentconfig/store.py`'s pattern; persists
`data/company_boards.json`), `mcp/server.py` registration, new
`mcp/tools_*.py` for `record_company_board` (inputs: company name, careers URL,
ats type optional, status ok|dead), read-side injection used by T3's fetch
path (decide: extend `/api/agent/config` response vs a sibling endpoint — keep
it on the same fetch `agent-config.js` already makes). Normalize company names
the way the blocklist/cooldown normalization already does — reuse, don't
duplicate. Removing a company from `target_companies` prunes its entry. Done:
`pytest` covering record/overwrite/dead-marking/prune; tool visible in the MCP
tool list test if one exists.

### T5 — cooldown from config
Files: `screening/cooldown.py`, its tests.
Read order: agent config `cooldown_days` → `APPLICATION_COOLDOWN_DAYS` env →
90. Done: tests for all three precedence levels; existing cooldown tests
untouched and green.

### T6 — ledger: profile attribution
Files: `applications/model.py`, `applications/log_render.py`, their tests.
Optional `profile: str | None` on the application record; `from_dict` tolerant
of its absence (old records). Render it in the log/report where the
application row is rendered. Screening verdict keys unchanged. Done: round-trip
test with and without the field; render test.

### T7 — web UI
Files: `web/src/agents/AgentsPage.tsx` (new `ProfilesSection` + global fields
into existing sections or a small new one), `web/src/api/client.ts`,
`web/src/api/types.ts`, tests alongside existing `AgentsPage.*.test.tsx`.
Profile cards with add/duplicate/remove; duplicate pre-fills from the source
profile; new-profile defaults per §5.3. Comma-delimited text inputs for all
multi-item fields. Explicit Save per the `ScheduleSection` pattern (not
blocklist's save-on-change) — these edits are consequential. Watchlist rows:
name, resolved URL read-only, clear-resolution, manual-URL override.
Entity-verification checkbox helper text per §5.2.7. Done: `npm test` and
`npm run typecheck` green; tests cover comma-splitting round-trip, blank-field
= criterion off display, and that saving one section does not clobber another.

---

## 7. Open items for the implementing session

- T3/T4 seam: exactly how resolved boards ride the config fetch (same endpoint
  vs sibling). Decide when reading `agent-config.js`; either is acceptable.
- Where `cooldown_days` and cap surface in the UI (own "Limits" section vs
  appended to an existing one) — implementer's call, follow the page's pattern.
- The design assumed `data/agent_config.json`'s writer is the only writer; if
  T4's store and T1's config are ever written in one request, check for
  read-modify-write races the existing store may already handle.
