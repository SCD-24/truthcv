<!-- generated:start cap:agent-workflow -->
# Agent Workflow — Aether Agent Workspace

Seeded scaffold; the workflow below is agent/team-owned.
<!-- generated:end cap:agent-workflow -->

> _Drafted by Aether from source — not human-verified._

## Per-change workflow

Follow these ordered steps for any change in this repository (TruthCV — a FastAPI + React CV/cover-letter tailoring app). These extend the generic workflow in `docs/conventions/agent-workflow.md` with the concrete tooling that actually exists here.

1. **Orient from the docs first.** Read [`docs/conventions/agent-operating-contract.md`](../conventions/agent-operating-contract.md) and the relevant [`docs/architecture/`](../architecture/system-map.md) pages. Build your understanding from the docs alone; open source only when a section is not marked **Verified**, is ambiguous, or you need exact implementation detail. Note: every architecture page currently carries the *"not verified at the current commit"* banner, so treat all of them as snapshots and verify against source before relying on them.

2. **Locate the right component.** Map your task to a canonical component (see the Canonical Names table in the operating contract) and its top-level directory. Backend logic lives in per-component packages — `api/` (FastAPI routes, config, schemas, secrets), `truth/`, `tailor/`, `coverletter/`, `guardrail/`, `render/`, `applications/`, `providers/`, `prompts/`, `secretstore/`. The frontend lives in `web/src/` (`api/`, `wizard/`, `steps/`, `applications/`, `settings/`, `styles/`). Keep the change scoped to that component and respect the declared interactions in the system map (most are in-process; `web-ui → api` is HTTP/REST).

3. **Make the change following the Global Guidelines.** Functions under ~25 lines and max 3 nesting levels; `snake_case` for Python, `camelCase` for TS, `PascalCase` for classes; write docstrings on public APIs/routes that explain the *why*. Do not invent new cross-component dependencies not present in the system map; if the architecture must change, that is a doc-affecting change (step 6).

4. **Add/adjust tests.** Backend tests live in `tests/` (pytest, one `test_*.py` per component, e.g. `test_tailor.py`, `test_guardrail.py`, `test_api.py`). Use the `data_dir` fixture from `tests/conftest.py` for anything that touches the persisted data volume so tests never write to real `./data`. Target ≥80% coverage of custom business logic (per the Global Guidelines). There is **no** configured frontend test runner (`web/package.json` defines only `dev`/`build`/`preview`/`typecheck`), so validate frontend changes via typecheck/build rather than unit tests.

5. **Validate locally.**
   - Backend: `pip install -r requirements-dev.txt` then `pytest` (config in `pyproject.toml`: `testpaths=["tests"]`, `pythonpath=["."]`).
   - Frontend: from `web/`, run `npm run typecheck` and `npm run build` (the build emits into `api/static`, which the API serves in production).
   - Note: PDF/DOCX rendering shells out to native libs (WeasyPrint deps, pandoc, DejaVu fonts) that `pip` does not install — run render-dependent paths inside Docker (`docker compose up --build`) or install the OS packages listed in `README.md`.

6. **Keep docs and architecture coherent.** Update only agent-owned Markdown sections you invalidated — **never edit inside `<!-- generated:start ... -->` / `<!-- generated:end -->` markers** (e.g. the generated blocks in `CLAUDE.md`, `agent-workflow.md`, and the architecture pages). If your change alters components, interactions, or the system boundary, that must be reflected through the architecture-canvas tooling, not by hand-editing generated blocks. Consult a doc-change matrix if one exists (tooling-owned; **none is present in this repo today**).

7. **Final self-check.** If you are working outside the Aether IDE or any commit has landed since the last drift sweep, treat all "Verified" labels as stale and confirm your change against source. Run `git status` to confirm a clean, intended tree (be aware it cannot tell you the swept commit has advanced).
