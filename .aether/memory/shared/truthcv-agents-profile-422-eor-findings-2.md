---
name: truthcv-agents-profile-422-eor-findings-2
description: DECISIVE follow-up: stored agent_config.json has NO profiles key — confirms the 422 is the empty-name new-profile path
type: project
---

Companion to [[truthcv-agents-profile-422-eor-findings]] — read that first for all source locations.

DECISIVE FACT: `cat data/agent_config.json` (live volume, member <repo root>) returns ONLY:
{"enabled": true, "blocked_companies": ["acme","acme gmbh"], "run_at": ["09:00","15:00","03:00","18:00"], "run_days": ["mon","tue","wed","thu","fri"]}
NO "profiles" key, NO target_companies, NO cooldown_days, NO max_applications_per_run.

⇒ The user has ZERO saved profiles. So the only way they can be "saving a job profile" is: click "Add profile" → `emptyDraft()` → name "" → Save → AgentConfigUpdate._validate_profiles raises "profile name must not be empty" → FastAPI 422 → client.ts can't read the list-shaped `detail` → generic "That didn't work (error 422). Try again."

THIS IS THE CONFIRMED ROOT CAUSE of bug 1. Even if they typed a name, the diagnosis stands as the primary path; the secondary paths (salary ordering, glassdoor > 5) remain possible but the blank-name path is certain to fire because nothing pre-fills the card.

THREE DEFECTS TO FIX (all in one plan against component web-ui, plus one on api if we surface detail server-side — prefer fixing the CLIENT):
D1. web/src/agents/AgentsPage.tsx EOR field: replace the three raw `<option>` children of `<TextField select>` with MUI `<MenuItem>` (the ONLY 3 `<option value=` in the repo). Non-native MUI Select cannot use <option> — that is why choices are unclickable.
D2. web/src/api/client.ts request() error path: FastAPI 422 `detail` is a LIST of {loc,msg,type} objects; current code only accepts `typeof b.detail === "string"` so the real reason is thrown away. Make it also flatten an array detail into a readable message (e.g. join `msg` values, optionally with the last `loc` segment). This is what turns every future validation failure from mystery into a message.
D3. web/src/agents/AgentsPage.tsx: stop letting a blank profile reach the server. Either (a) pre-fill `emptyDraft()` with the spec §5.3 defaults incl. a placeholder name, and/or (b) validate client-side before PUT and show an inline error on the Name field. The staged spec (docs/superpowers/specs/agent-job-profiles-staged-plans.json) intended §5.3 defaults + a "duplicate profile" action; neither was implemented.

TESTS: add to web/src/agents/AgentsPage.profiles.test.tsx (needs line-1 `// @vitest-environment jsdom` pragma) for the MenuItem/EOR selection and the blank-name guard; add a pure test for the client detail-flattening. VERIFY: `cd web && npm run typecheck` then `cd web && npm test`. Python untouched.
