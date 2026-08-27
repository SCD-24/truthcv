---
name: truthcv-agents-profile-422-eor-findings
description: Investigation findings for the "422 on save job profile + EOR select unclickable" bug on the Agents page
type: project
---

MEMBER REF: <repo root>. Single-member workspace effectively. Plan set 4d72085e-a778-46f1-bce0-8adb0ee5c56b (unnamed) — I am in ITS planning conversation, so omit `set` on plan_component_work.

USER BUG REPORT: "when trying to save job profile on agents page, I get 'That didn't work (error 422). Try again.' — for the EOR field, I'm unable to select one of the choices (can't even click them)"

=== BUG 2 (CONFIRMED, root cause found) ===
web/src/agents/AgentsPage.tsx lines ~703-719: the "EOR allowed" field is
  <TextField select label="EOR allowed" size="small" value={draft.eorAllowed} onChange={...} sx={{minWidth:140}}>
    <option value="">Not set</option>
    <option value="true">Allowed</option>
    <option value="false">Not allowed</option>
  </TextField>
MUI `<TextField select>` renders a NON-NATIVE MUI <Select>/<Menu>; children must be <MenuItem>, not raw <option>. That is exactly why the choices render but cannot be clicked. FIX: swap to <MenuItem value="…">, or add SelectProps={{native:true}}. These are the ONLY 3 `<option value=` occurrences in the entire repo (grep confirmed) — every other select on the page uses MenuItem.

=== BUG 1 (422) — cause narrowed, not yet proven ===
Client error path: web/src/api/client.ts line ~63-68 — `const detail = await res.json().then(b => b && typeof b.detail === "string" ? b.detail : "").catch(()=> ""); throw new Error(detail || \`That didn't work (error ${res.status}). Try again.\`)`. FastAPI RequestValidationError returns `detail` as a LIST of error objects, so `typeof detail === "string"` is FALSE and the user always gets the generic fallback. ⇒ the generic message PROVES it is a pydantic 422 on AgentConfigUpdate, and ALSO means the real reason is never shown. Two separate defects: the validation failure AND the swallowed detail.

Validators that can 422 (api/schemas.py):
- JobProfileModel (line ~259): salary_floor/salary_ask_min/salary_ask_max must be > 0; glassdoor_min 0..5; glassdoor_min_reviews >= 0; list fields comma-split (mode="before").
- AgentConfigUpdate._validate_profiles (line ~419): **"profile name must not be empty"** (after .strip()), "duplicate profile name: X", "salary_floor must be <= salary_ask_min", "salary_ask_min must be <= salary_ask_max".
- _validate_cooldown_days >= 0; _validate_max_applications_per_run >= 1; run_at HH:MM regex; run_days enum.
_Camel base = ConfigDict(alias_generator=to_camel, populate_by_name=True) — extras are IGNORED, so companyBoards in the body is NOT the cause (tests/test_agent_config_api.py::test_put_does_not_accept_company_boards_field asserts 200).

MOST LIKELY CAUSE: AgentsPage.tsx `emptyDraft()` (line ~513) returns `name: ""`. "Add profile" creates a fully blank card; Save then always 422s with "profile name must not be empty" and the user sees only the generic message. NOTE the staged spec (docs/superpowers/specs/agent-job-profiles-staged-plans.json) said a new profile should be PRE-FILLED with §5.3 defaults (fully remote; Germany; EOR disallowed; entity verification required; salary floor 70000, ask 80000-100000; English; Glassdoor 3.5 waived under 20 reviews; accepted "backend engineering, platform engineering"; rejected "sales, marketing") and that there should be a DUPLICATE action — NEITHER was implemented. So the implementation diverged from the plan.
SECOND CANDIDATE: user typed a salary that violates floor <= askMin <= askMax, or a Glassdoor rating > 5.
STILL UNVERIFIED: the actual request body / stored profiles. data/agent_config.json is only 228 bytes (root-owned, live volume at <repo root>/data) — I never managed to cat it (run_command blocked `cat data/agent_config.json` when chained; a bare `cat data/agent_config.json` was not tried).

=== KEY SOURCE LOCATIONS ===
- web/src/agents/AgentsPage.tsx (1040 lines): ProfileDraft iface ~l.445; listToText/textToList/numberToText/textToIntOrNull/textToFloatOrNull ~l.462-490; profileToDraft ~l.492; emptyDraft ~l.513; draftToProfile ~l.536; ProfilesSection ~l.566; handleSave ~l.593 calls updateAgentConfig({profiles, cooldownDays, maxApplicationsPerRun}); EOR TextField ~l.703.
- web/src/api/types.ts: JobProfile iface l.306, AgentConfig l.~334 (profiles, targetCompanies, cooldownDays, maxApplicationsPerRun, readonly companyBoards); AgentConfigUpdate = Partial<AgentConfig>.
- web/src/api/client.ts: request() wrapper l.45-72; getAgentConfig l.293; updateAgentConfig l.298 (PUT /api/agent/config).
- api/schemas.py: JobProfileModel l.259, CompanyBoardModel l.~312, AgentConfigModel l.~320, AgentConfigUpdate l.~340, _validate_profiles l.419.
- api/routes.py: get_agent_config l.705, put_agent_config l.730 (merged = load().to_dict(); apply body.model_dump(exclude_unset=True, by_alias=False); AgentConfig.from_dict(merged); save).
- agentconfig/store.py: JobProfile dataclass l.22 (eor_allowed l.34, from_dict l.46, to_dict l.104), AgentConfig l.~120 with profiles l.125, from_dict profiles loop l.154-160, load() l.193, save() l.213, path = data_dir()/"agent_config.json" l.13.
- Tests: tests/test_agent_config_api.py (366 lines), tests/test_agent_config_store.py, web/src/agents/AgentsPage.profiles.test.tsx (makeProfile at l.46, eorAllowed:null at l.55), web/src/agents/AgentsPage.model.test.tsx (has `// @vitest-environment jsdom` line-1 pragma — REQUIRED, vite.config.ts default env is node).

=== VERIFY COMMANDS ===
cd web && npm run typecheck ; cd web && npm test   (vitest); python -m pytest tests/ -q -p no:warnings --no-header 2>&1 | tail -6
Global rules: docstrings required, functions <=25 lines, max nesting 3, Vitest for frontend.
