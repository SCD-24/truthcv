# LLM Provider Connections — Stage 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Per-task model routing threaded through every LLM call site with a Task-models UI, plus the unattended agent running on the routed connection (Claude subscription token or API key) with a chosen model.

**Architecture:** The routing store and `get_provider(task)` ladder already exist (Stage 1); this stage passes real task names at the five call sites (giving `tailor()` a per-task provider resolver), adds the first guarded endpoint (`GET /api/agent/llm-credentials`, `X-Agent-Token` shared secret via compose), extends `agent-config.js`/`daily-apply.sh` to fetch credentials + `--model`, and builds the Task-models and Agents-page Model UI on a picker extracted from `DefaultModelSection`.

**Tech Stack:** Python 3.11/FastAPI/pytest (run via `.venv/bin/python -m pytest tests/ -q`), bash + node (agent container), React/TS/MUI/vitest (`cd web && npm test`, `npm run build`).

**Spec:** `docs/superpowers/specs/2026-08-17-llm-provider-connections-design.md` (sections "Routing", "Agent wiring", "Frontend"). Stage 3 (Codex/Copilot/Antigravity OAuth) stays out of scope.

## Global Constraints

- Task names are exactly `modelrouting.TASK_NAMES = ("truth_extract", "keywords", "tailor", "infer", "cover_letter")`.
- The agent credentials endpoint returns a live token: it MUST be guarded. Guard: request header `X-Agent-Token` must equal env `AGENT_API_TOKEN`; when the env var is unset or the header is wrong/missing, respond **404** (indistinguishable from absent). Token/key material never appears in logs — neither app-side nor in the agent's `RUN_LOG`.
- The agent runs the Claude Code CLI: only the `claude` connection is valid for the agent slot (endpoint enforces; UI offers only Anthropic-family).
- Fallback behavior preserved: with no routing/credentials configured, every call site behaves exactly as today (env `ANTHROPIC_API_KEY` for the agent; `legacy_default()` for the app).
- Existing wire shapes unchanged except additive.
- Commit per task on branch `feat/task-routing-agent` (create from current `main`; PR after, never direct to main).

Observed while scoping, deliberately NOT fixed here (out of scope, note for the user): `docker-compose.yml` never passes `RUN_DAYS` to the agent service even though `entrypoint.sh` reads it.

---

### Task 1: Thread task names through the call sites (incl. `tailor()` resolver)

**Files:**
- Modify: `tailor/__init__.py` (signature at :80, sub-calls :86-88), `api/routes.py:157,185,769`, `mcp/tools_letter.py:56`
- Test: `tests/test_task_routing_callsites.py` (new); update any existing test constructing `tailor(...)` (grep `tailor_engine.tailor\|from tailor import` in tests/ first)

**Interfaces:**
- Consumes: `providers.get_provider(task)` (existing).
- Produces: `tailor(posting: str, truth: Truth, provider_for: Callable[[str | None], LLMProvider]) -> dict[str, Any]` — the third parameter becomes a **resolver**; internal calls become `extract_keywords(posting, provider_for("keywords"))`, `select_and_rephrase(..., provider_for("tailor"))`, `detect_inferences(..., provider_for("infer"))`. Sub-function signatures unchanged.
- Call sites: `api/routes.py:157` → `get_provider("truth_extract")`; `:185` → `tailor_engine.tailor(body.posting, load(), get_provider)` (pass the function itself); `:769` → `get_provider("cover_letter")`; `mcp/tools_letter.py:56` → `get_provider("cover_letter")`. `/settings/test` (`routes.py:886`) stays task-less.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_task_routing_callsites.py
"""Each call site asks get_provider for its own task name."""
from providers.fake import FakeProvider


def test_tailor_resolves_per_subtask(data_dir, monkeypatch):
    asked: list[str | None] = []

    def provider_for(task=None):
        asked.append(task)
        return FakeProvider()

    import tailor as tailor_engine
    from truth.model import Truth

    tailor_engine.tailor("posting text", Truth(), provider_for)
    assert asked == ["keywords", "tailor", "infer"]


def test_routes_pass_task_names(data_dir, monkeypatch):
    """The API handlers hand get_provider their task name (patched at the
    api.routes seam, the same one existing tests patch)."""
    asked: list[str | None] = []

    def fake_get_provider(task=None, refresh=False):
        asked.append(task)
        return FakeProvider()

    import api.routes as routes

    monkeypatch.setattr(routes, "get_provider", fake_get_provider)
    # Exercise the cover-letter path far enough to hit the provider resolution:
    # reuse the request pattern from tests/test_cover_letter_api.py (read it;
    # its fixtures set up posting.txt + truth). Assert "cover_letter" in asked.
```

(Complete the second test by copying the minimal setup from `tests/test_cover_letter_api.py` — the assertion that matters is `"cover_letter" in asked`. Add the equivalent for `/api/extract` asserting `"truth_extract"`, using `tests/test_api.py`'s upload/extract fixtures.)

- [ ] **Step 2: Run to verify failure** — `.venv/bin/python -m pytest tests/test_task_routing_callsites.py -q` → FAIL (`tailor()` takes a provider, not a resolver; handlers pass no task)
- [ ] **Step 3: Implement** the signature + call-site changes per Interfaces. Update existing tests that call `tailor(...)` with a bare provider to pass `lambda task=None: fake` instead — list each in the report.
- [ ] **Step 4: Full suite** — `.venv/bin/python -m pytest tests/ -q` → all green
- [ ] **Step 5: Commit** — `git commit -m "feat: thread per-task routing through LLM call sites"`

---

### Task 2: Guarded agent credentials endpoint

**Files:**
- Modify: `api/schemas.py` (append), `api/routes.py` (append; endpoint goes on `router` — anything registered after `_mount_static()` is shadowed)
- Test: `tests/test_agent_credentials_api.py`

**Interfaces:**
- Produces (schema): `AgentLlmCredentials(_Camel)`: `auth_type: str` (`"oauth" | "api_key"`), `token: str`, `model: str = ""`.
- Produces (route): `GET /api/agent/llm-credentials`:
  1. `secret = os.environ.get("AGENT_API_TOKEN", "").strip()`; if unset → 404. Header `X-Agent-Token` (via `Header(default="")`) compared with `hmac.compare_digest` → mismatch/missing → 404. (First guarded endpoint in the app — there is deliberately no shared auth infrastructure to reuse.)
  2. Resolve `route = modelrouting.load().agent`; `card = route.connection if route else "claude"`; non-`claude` card → 409 `"Agent supports only the Claude connection."`; `model = route.model if route else ""`.
  3. Credentials: if the claude connection has an oauth record and `authMode != "apikey"` → `token = connections.auth.claude.get_valid_access_token()` (fresh, refreshes if near expiry; `AuthError` → 503 `"Claude subscription needs reconnecting."`), `auth_type="oauth"`. Else `apiKey` from `secretstore.get_connection("claude")` (env fallback included) → `auth_type="api_key"`. Neither → 404.
  4. Never log the token; the response model is the only egress.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_agent_credentials_api.py
import time

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

import modelrouting
import secretstore
from api.main import app
from modelrouting import Route, Routing


@pytest.fixture()
def client(data_dir, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("AGENT_API_TOKEN", "shared-secret")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return TestClient(app)


def _hdr(v="shared-secret"):
    return {"X-Agent-Token": v}


def test_no_env_secret_404(client, monkeypatch):
    monkeypatch.delenv("AGENT_API_TOKEN")
    assert client.get("/api/agent/llm-credentials", headers=_hdr()).status_code == 404


def test_wrong_or_missing_header_404(client):
    assert client.get("/api/agent/llm-credentials").status_code == 404
    assert client.get("/api/agent/llm-credentials", headers=_hdr("nope")).status_code == 404


def test_api_key_path(client):
    secretstore.set_connection("claude", {"apiKey": "sk-ant-agent", "authMode": "apikey"})
    modelrouting.save(Routing(agent=Route("claude", "claude-opus-4-8")))
    body = client.get("/api/agent/llm-credentials", headers=_hdr()).json()
    assert body == {"authType": "api_key", "token": "sk-ant-agent", "model": "claude-opus-4-8"}


def test_oauth_path_uses_fresh_token(client, monkeypatch):
    secretstore.set_connection("claude", {
        "oauth": {"accessToken": "at", "refreshToken": "rt", "expiresAt": time.time() + 3600},
        "authMode": "subscription",
    })
    monkeypatch.setattr("api.routes.get_valid_agent_token", lambda: "fresh-tok", raising=False)
    # patch target: whatever name the implementation imports for
    # connections.auth.claude.get_valid_access_token — keep it module-level
    # patchable and adjust this line to the real seam.
    body = client.get("/api/agent/llm-credentials", headers=_hdr()).json()
    assert body["authType"] == "oauth" and body["token"] == "fresh-tok"


def test_non_claude_agent_route_409(client):
    secretstore.set_connection("ollama", {"baseUrl": "http://x:11434"})
    modelrouting.save(Routing(agent=Route("ollama", "llama3.1")))
    assert client.get("/api/agent/llm-credentials", headers=_hdr()).status_code == 409


def test_nothing_configured_404(client):
    assert client.get("/api/agent/llm-credentials", headers=_hdr()).status_code == 404
```

- [ ] **Step 2: RED** — `.venv/bin/python -m pytest tests/test_agent_credentials_api.py -q` → FAIL (404 from SPA catch-all… actually 404 everywhere: the meaningful RED is the api-key/oauth/409 tests)
- [ ] **Step 3: Implement** per Interfaces (import `get_valid_access_token` at module level in `api/routes.py` so the test seam is patchable; adjust the test's patch target accordingly).
- [ ] **Step 4: Full suite** green. **Step 5: Commit** — `"feat: guarded /api/agent/llm-credentials endpoint"`

---

### Task 3: Compose + env surface

**Files:**
- Modify: `docker-compose.yml` (app env + agent env), `.env.example`

**Interfaces:**
- `app` service env gains `- AGENT_API_TOKEN=${AGENT_API_TOKEN:-}`.
- `agent` service env gains `- AGENT_API_TOKEN=${AGENT_API_TOKEN:-}` (same value; compose interpolates both from one `.env` entry).
- `.env.example` documents: `AGENT_API_TOKEN=` — "shared secret letting the agent container fetch LLM credentials from the app; generate with `openssl rand -hex 32`; leave empty to keep the agent on ANTHROPIC_API_KEY only". No other compose changes (the `RUN_DAYS` gap is noted in the plan header, not fixed).

- [ ] **Step 1: Edit both files** per Interfaces
- [ ] **Step 2: Verify** — `docker compose config >/dev/null` exits 0 and `docker compose config | grep -c AGENT_API_TOKEN` shows 2
- [ ] **Step 3: Commit** — `"feat: AGENT_API_TOKEN shared secret in compose"`

---

### Task 4: Agent-side fetch (`agent-config.js` + `daily-apply.sh` + `entrypoint.sh`)

**Files:**
- Modify: `agent/agent-config.js`, `agent/daily-apply.sh` (claude invocation block :99-112, config read :70), `agent/entrypoint.sh` (preflight :53-59)
- Test: no JS/bash test framework exists in the repo — verification is (a) `bash -n` both scripts, (b) `node agent/agent-config.js llm_credentials` against a locally running TestClient-equivalent is impossible; instead add `tests/test_agent_credentials_api.py::test_response_shape_matches_agent_parser` asserting the exact JSON keys the JS parses (`authType`, `token`, `model`) — the contract test IS the seam guard.

**Interfaces:**
- `agent-config.js` gains verb `llm_credentials`: GET `<base>/api/agent/llm-credentials` with header `X-Agent-Token: process.env.AGENT_API_TOKEN` (verb errors with exit 2 immediately when that env is empty — distinct from exit 1 fetch failure). On 200, prints EXACTLY three lines: `authType`, `token`, `model` (possibly empty third line). On any non-200/error: exit 1, nothing on stdout. The token is never written anywhere else.
- `daily-apply.sh`, before the claude invocation:

```bash
# Fetch routed LLM credentials from the app (Stage 2). Fallback: the
# container's ANTHROPIC_API_KEY env, exactly the pre-Stage-2 behavior.
AGENT_MODEL=""
if [[ -n "${AGENT_API_TOKEN:-}" ]]; then
  if CREDS="$(node "${AGENT_CONFIG_JS:-/app/agent/agent-config.js}" llm_credentials 2>/dev/null)"; then
    AUTH_TYPE="$(sed -n 1p <<<"$CREDS")"
    AUTH_TOKEN="$(sed -n 2p <<<"$CREDS")"
    AGENT_MODEL="$(sed -n 3p <<<"$CREDS")"
    if [[ "$AUTH_TYPE" == "oauth" ]]; then
      export CLAUDE_CODE_OAUTH_TOKEN="$AUTH_TOKEN"
      unset ANTHROPIC_API_KEY
      log "using Claude subscription credentials from app"
    elif [[ "$AUTH_TYPE" == "api_key" ]]; then
      export ANTHROPIC_API_KEY="$AUTH_TOKEN"
      log "using API key credentials from app"
    fi
    unset CREDS AUTH_TOKEN
  else
    log "credential fetch failed; falling back to container ANTHROPIC_API_KEY"
  fi
fi
MODEL_ARGS=()
[[ -n "$AGENT_MODEL" ]] && MODEL_ARGS=(--model "$AGENT_MODEL")
```

  and the invocation gains `"${MODEL_ARGS[@]}"` after `-p "$PROMPT"`. (`log` writes to `RUN_LOG` — the messages above contain no token material.)
- `entrypoint.sh` preflight (:55) becomes: abort only when BOTH `ANTHROPIC_API_KEY` and `AGENT_API_TOKEN` are empty; when only `AGENT_API_TOKEN` is set, log `"credentials will be fetched from app at run time"` and pass.

- [ ] **Step 1: Add the contract test** (three keys, in `tests/test_agent_credentials_api.py`) and see it pass/fail appropriately against Task 2's endpoint
- [ ] **Step 2: Implement** the three files per Interfaces
- [ ] **Step 3: Verify** — `bash -n agent/daily-apply.sh agent/entrypoint.sh`; `node --check agent/agent-config.js`; full pytest suite still green
- [ ] **Step 4: Commit** — `"feat: agent fetches routed LLM credentials and model from app"`

---

### Task 5: Extract shared `ModelRoutePicker` (web refactor, no behavior change)

**Files:**
- Create: `web/src/settings/ModelRoutePicker.tsx`
- Modify: `web/src/settings/DefaultModelSection.tsx` (becomes a thin wrapper)
- Test: existing `DefaultModelSection.test.tsx` must pass UNCHANGED (that is the refactor's acceptance bar); add `ModelRoutePicker.test.tsx` only for props not exercised via the wrapper (`filterCards`, `allowClear`).

**Interfaces:**
- Produces: `export function ModelRoutePicker({ connections, route, onSave, title, description, saveLabel, filterCards, allowClear, showTest }: { connections: ConnectionStatus[]; route: RouteChoice | null; onSave: (route: RouteChoice | null) => Promise<void>; title: string; description?: string; saveLabel?: string; filterCards?: string[]; allowClear?: boolean; showTest?: boolean })` — owns the connection select (connected cards only, further filtered by `filterCards`), model select with `CUSTOM_MODEL` + Reload, the stale-connection reconciliation effects, the Test button (when `showTest`), and a Clear button (when `allowClear`, calling `onSave(null)`).
- `DefaultModelSection` keeps its exact public props and copy, delegating to the picker with `onSave` = `updateRouting({default: route})`.

- [ ] **Step 1:** Run `cd web && npm test -- DefaultModelSection` — green baseline
- [ ] **Step 2: Extract** per Interfaces; DefaultModelSection tests must pass without edits
- [ ] **Step 3:** Write + pass picker-specific tests (`filterCards` hides cards; `allowClear` calls `onSave(null)`)
- [ ] **Step 4:** `npm test && npm run build` clean; `git restore api/static web/tsconfig.tsbuildinfo`
- [ ] **Step 5: Commit** — `"refactor(web): extract ModelRoutePicker from DefaultModelSection"`

---

### Task 6: Task-models section (Settings)

**Files:**
- Create: `web/src/settings/TaskModelsSection.tsx`
- Modify: `web/src/settings/SettingsModal.tsx` (render after `DefaultModelSection`, :125, same `routing`/`onSaved={setRouting}` wiring)
- Test: `web/src/settings/TaskModelsSection.test.tsx`; extend `SettingsModal.test.tsx` to assert the third section renders

**Interfaces:**
- Produces: `TaskModelsSection({ connections, routing, onSaved })` — five rows (labels: "Truth extraction", "Keyword extraction", "CV tailoring", "Inference detection", "Cover letter"; task keys from a local `TASKS` constant matching backend `TASK_NAMES` exactly), each a `ModelRoutePicker` with `allowClear`, `showTest=false`, `onSave` = `updateRouting({tasks: {<name>: route}})` (route `null` clears via the Stage-1 null-clear semantics), refreshing `onSaved` with the returned Routing. Description: "Overrides the default model per task; cleared tasks use the default."
- Seam guard: a vitest test asserting the local `TASKS` keys equal `["truth_extract","keywords","tailor","infer","cover_letter"]` (mirror of the backend tuple — same drift protection pattern as the mode-strings guard).

- [ ] **Step 1: RED** — write tests (rows render; saving a row calls `updateRouting` with that task key; clearing sends null; seam guard)
- [ ] **Step 2: Implement**; **Step 3:** `npm test && npm run build` clean, restore build byproducts
- [ ] **Step 4: Commit** — `"feat(web): per-task model routing section"`

---

### Task 7: Agents-page Model section

**Files:**
- Modify: `web/src/agents/AgentsPage.tsx` (new section at :190, between Enabled and Schedule; add `getRouting()` to the mount `Promise.all` at :143; import `updateRouting`; local `Section` wrapper stays as-is)
- Test: extend `web/src/agents/` tests (check for an existing AgentsPage test file first; if none, create `AgentsPage.model.test.tsx` with the jsdom docblock, mocking the client like `AccountsSection.test.tsx`)

**Interfaces:**
- New `ModelSection` inside AgentsPage using `ModelRoutePicker` with `filterCards={["claude"]}`, `allowClear`, `showTest=false`, `route={routing.agent}`, `onSave` = `updateRouting({agent: route})`. Needs `connections` — add `listConnections()` to the mount Promise.all as well. Description: "Model and account the unattended agent runs on. Cleared = the container's ANTHROPIC_API_KEY."

- [ ] **Step 1: RED** tests (section renders only claude among mixed connections; save calls `updateRouting({agent:…})`; clear sends null)
- [ ] **Step 2: Implement**; **Step 3:** `npm test && npm run build` clean, restore byproducts
- [ ] **Step 4: Commit** — `"feat(web): agent model routing section"`

---

### Task 8: Docs

**Files:**
- Modify: `agent/README.md` (Configuration table: `AGENT_API_TOKEN` row; credentials/model now fetched from the app when set, env fallback documented — current behavior only, no history), `README.md` + `.env.example` (already touched in Task 3; ensure README mentions per-task routing under Settings), `docs/reference/api.md` (one row for `GET /api/agent/llm-credentials` marked "internal, X-Agent-Token guarded"; outside generated blocks)

- [ ] **Step 1: Edit**; **Step 2:** verify no `generated:` block touched; full backend suite green once
- [ ] **Step 3: Commit** — `"docs: agent credential fetch + task routing"`

---

## Accepted risks / assumptions (flagged, not blocking)

- **Token TTL vs run length:** the agent fetches one access token at run start; a subscription token expiring mid-run fails that run's remaining CLI calls. Accepted for now — runs are typically much shorter than the token TTL; revisit only if observed.
- `CLAUDE_CODE_OAUTH_TOKEN` is the CLI's documented env for subscription tokens (same mechanism `claude setup-token` feeds); our `user:inference`-scoped token matches what setup-token mints.
- The credentials endpoint is reachable from the host's published port 8080 too; the shared secret is the entire guard (spec accepted this posture; the API is otherwise unauthenticated by design).

## Self-review notes

- Spec coverage: task threading ✔ (T1), guarded endpoint + agent wiring ✔ (T2-T4), Task-models UI ✔ (T5-T6), Agents-page model ✔ (T7), docs ✔ (T8). Spec's "UI offers only Anthropic-family for the agent" ✔ via `filterCards` (T7) + 409 enforcement (T2).
- Type consistency: `Route`/`RouteChoice`, `updateRouting` partials, and `TASK_NAMES` labels checked across T1/T2/T6/T7; `provider_for` name consistent between T1's interface and tests.
- Placeholder scan: T1's second test intentionally delegates fixture details to named existing test files (real files verified by the scout: `tests/test_cover_letter_api.py`, `tests/test_api.py`); T2's oauth patch target is explicitly marked adjust-to-real-seam. No TBDs.
