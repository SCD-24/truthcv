# Agents Page — Design

Approved 2026-08-17. Moves agent-related settings out of the settings modal
into a dedicated Agents page, and adds two new agent controls: a company
blocklist and an enable/disable switch, plus a UI-editable run schedule.

## Goals

- The settings modal keeps only provider settings (LLM provider, key, model).
- A new Agents page owns everything agent-related: enabled toggle, run
  schedule, company blocklist, profile answers, screening/cooldown records.
- Disabling the agent means scheduled runs wake, see the flag, log
  "disabled, skipping", and exit. Per-run granularity; no container
  orchestration from the web app.
- The blocklist prevents the agent submitting applications to listed
  companies, matched by company name, case-insensitively.
- The run schedule (times + weekdays) is editable from the page and takes
  effect without recreating the agent container.

## Non-goals

- Multiple agents. The page is named "Agents" but configures the single
  application agent.
- Mid-run cancellation. Disabling between runs is the contract.
- Domain- or substring-based blocklist matching.
- Exposing the remaining seed-file-only profile answer fields (a separate,
  pre-existing gap).

## 1. Config store and API

New file `data/agent_config.json`, following the one-file-per-concern
pattern (`data/answers.yaml`, `data/screenings.json`), written atomically.

```json
{
  "enabled": true,
  "blocked_companies": [],
  "run_at": ["09:00", "15:00"],
  "run_days": ["mon", "tue", "wed", "thu", "fri"]
}
```

- Missing file or missing field → the defaults above. Defaults mirror the
  current `agent/entrypoint.sh` env defaults.
- Endpoints: `GET /api/agent/config`, `PUT /api/agent/config`. PUT accepts
  partial bodies and merges onto the stored record (the
  `/api/profile/answers` pattern), validating:
  - `run_at`: non-empty list of `HH:MM` (24h) strings.
  - `run_days`: non-empty list drawn from `mon..sun`.
  - `blocked_companies`: list of non-empty strings; stored as entered,
    matched normalized (see §3).
- Storage/access module lives beside the other stores (same layer as
  `screening/store.py`); exact placement decided at planning.

## 2. Enable/disable enforcement

- `agent/daily-apply.sh` fetches `GET /api/agent/config` after its existing
  preconditions and before invoking `claude`. The agent image has no curl;
  the fetch is a small `node` helper (the `agent/smoke-test.sh` pattern),
  targeting the app service host derived from `TRUTHCV_MCP_URL`.
- `enabled: false` → log "agent disabled, skipping run", exit 0. The
  scheduler loop continues; re-enabling takes effect at the next slot.
- Config endpoint unreachable → skip the run (fail closed) with a distinct
  log line. Rationale: if the app service is down, the MCP tools the run
  depends on are down too, and "did not run" is the safe failure for an
  unattended submitter.

## 3. Company blocklist enforcement

Submission happens in the operator's browser via the interceptor, so there
is no code path that can physically stop it; enforcement lives in the two
server-side tools the RUNBOOK makes mandatory for every application:

- `check_cooldown` reports a blocked company as permanently blocked
  (never-expiring), so the agent's existing "cooldown → do not apply"
  behaviour covers the blocklist with no new tool. The tool allow-list in
  `agent/daily-apply.sh`, the "exactly six tools" contract in
  `agent/prompt.md`, and the tool docs stay untouched.
- `generate_cover_letter` refuses for a blocked company (defense-in-depth;
  RUNBOOK §5.3 forbids hand-written letters, making it the second
  unavoidable gate).
- Matching uses the existing cooldown rule — `strip().casefold()` equality
  on company name (`screening/cooldown.py:_matches`) — so blocklist and
  cooldown can never disagree on identical input. Exact-equality is a known
  limitation ("Acme" does not block "Acme GmbH"); accepted.
- `agent/RUNBOOK.md` §8 documents the blocklist alongside cooldowns.

## 4. Editable schedule

- `agent/entrypoint.sh` treats the config API as the schedule source of
  truth. Each scheduler-loop iteration re-fetches `run_at`/`run_days` (same
  node helper); the `RUN_AT`/`RUN_DAYS` env vars remain only as fallback
  when the API is unreachable or fields are absent.
- Sleeps are chunked (≤300 s per sleep, recomputing the next slot on each
  wake), so a schedule edited from the UI takes effect within ~5 minutes
  even mid-sleep.
- `--check-schedule` reads the same source, so it previews what will
  actually run.
- The four-way hand-sync (compose, entrypoint defaults, the UI's hardcoded
  `AGENT_RUN_TIMES` literal, README) collapses: the UI reads the API, the
  README documents the config as authoritative and env as fallback.

## 5. Agents page and modal cleanup

- Navigation: extend the hand-rolled `View` union in `web/src/App.tsx`
  (`"wizard" | "applications" | "analytics" | "agents"`), add the fourth
  rail button in `StepRail.tsx` with the existing `active`/`aria-current`
  pattern. Non-wizard views already get the wide layout.
- Page sections, top to bottom:
  1. **Agent** — enabled switch with a one-line description of what off
     means (runs skip until re-enabled).
  2. **Schedule** — run-time editor (add/remove `HH:MM` entries) and
     weekday checkboxes; saves via `PUT /api/agent/config`.
  3. **Blocked companies** — add/remove list of names.
  4. **Profile answers** — the five fields moved from the modal, with their
     own save (a partial `PUT /api/profile/answers`), decoupled from
     provider settings.
  5. **Screening & cooldowns** — the read-only table with per-row delete,
     moved as-is.
- `SettingsModal` keeps only the Provider section; its save no longer
  touches profile answers.

## 6. Error handling

- Config writes are atomic; a failed PUT leaves the previous file intact.
- Validation happens at PUT time, so the agent never sees a malformed
  schedule; the entrypoint additionally falls back to env defaults if a
  fetched value fails its own sanity parse.
- UI surfaces save failures inline per section (existing modal pattern).

## 7. Testing

- Python: config store round-trip and defaults; route validation
  (bad `HH:MM`, bad day, empty lists); blocklist folded into
  `check_cooldown` (blocked, not-blocked, casefold/whitespace variants);
  `generate_cover_letter` refusal.
- Web: pure helpers (schedule formatting/validation, blocklist entry
  normalization) unit-tested in the existing pure-module style
  (`settings/cooldown.ts` precedent).
- Agent scripts: `--check-schedule` run against a live app to verify the
  fetched schedule; a disabled-flag run exercised manually. No e2e suite
  exists; not added here.
