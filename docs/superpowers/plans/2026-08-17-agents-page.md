# Agents Page + Applications Table Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A dedicated Agents page owning agent config (enable toggle, editable schedule, company blocklist, profile answers, screenings), enforced server-side and in the agent scripts; plus three approved applications-page fixes (per-column sorting, notes clamp, dark-mode text colors).

**Architecture:** New `data/agent_config.json` store + `GET/PUT /api/agent/config`; blocklist folded into the existing `screening.cooldown.cooldown()` chokepoint (which both `GET /api/cooldown` and the MCP `check_cooldown` tool delegate to) and into `generate_cover_letter` via a new optional `company` arg; agent shell scripts fetch config over HTTP with node (image has no curl); new hand-rolled `agents` view in the React shell.

**Tech Stack:** FastAPI + pydantic (api/), Python dataclass stores (JSON on the data volume), bash agent scripts + node one-liners, React 18 + TS + MUI + vitest (web/).

**Spec:** `docs/superpowers/specs/2026-08-17-agents-page-design.md`

## Global Constraints

- Python tests: `python -m pytest` (pytest.ini_options: testpaths=tests, pythonpath=.). Use the `data_dir` fixture from `tests/conftest.py` (sets `DATA_DIR` to tmp) in every test that touches stores.
- Web tests: `cd web && npm test` (vitest run). Typecheck: `npm run typecheck`.
- Company matching everywhere: `strip().casefold()` equality, exactly like `screening/cooldown.py:_matches`.
- Config defaults (must mirror `agent/entrypoint.sh` env defaults): `enabled=true`, `blocked_companies=[]`, `run_at=["09:00","15:00"]`, `run_days=["mon","tue","wed","thu","fri"]`.
- API wire format is camelCase (`_Camel` base in `api/schemas.py`): `blockedCompanies`, `runAt`, `runDays`.
- The agent image has node but no curl/nc/socat. All agent-side HTTP goes through node one-liners (pattern: `agent/smoke-test.sh:109-116`).
- Never commit to main; work on `jobs-into-truthcv`. Commit per task.
- No formatting/import churn outside touched lines; preserve existing comments.

---

### Task 1: Dark-mode palette text fix

**Files:**
- Modify: `web/src/theme.ts:33`
- Test: `web/src/theme.test.ts` (create)

**Interfaces:** none consumed/produced.

Background: `theme.ts` palette holds light-mode hexes because `createTheme` augments *main* colors (primary/error/...) and a `var(--x)` there throws at module eval (see comment `theme.ts:25-31`). `text` colors are NOT augmented, so vars should be safe — the test proves it.

- [ ] **Step 1: Write the failing test**

```ts
// web/src/theme.test.ts
import { describe, expect, it } from "vitest";
import { theme } from "./theme";

describe("theme", () => {
  // Palette text colours must be CSS vars so tokens.css can flip them in
  // dark mode; concrete hexes here are the dark-text-on-dark-ground bug.
  it("uses token vars for text colours", () => {
    expect(theme.palette.text.primary).toBe("var(--ink)");
    expect(theme.palette.text.secondary).toBe("var(--ink-soft)");
  });
});
```

- [ ] **Step 2: Run it — expect FAIL** (`cd web && npx vitest run src/theme.test.ts`) with received `#1a211c`.
- [ ] **Step 3: Implement** — in `web/src/theme.ts` replace line 33:

```ts
    text: { primary: 'var(--ink)', secondary: 'var(--ink-soft)' },
```

Also amend the palette comment (lines 25-31) minimally: append a sentence "text colours are not augmented, so they can and do use vars." If `createTheme` throws (test crashes on import), fall back: keep hexes and instead add a `MuiTypography` styleOverride `root: { '&.MuiTypography-root': {} }` — do NOT guess further, report back.

- [ ] **Step 4: Run test + typecheck** — `npx vitest run src/theme.test.ts && npm run typecheck`. Expect PASS.
- [ ] **Step 5: Visual check** — with the app running (`docker compose up app` or `npm run dev`), open Settings modal in dark mode (OS dark or devtools emulate `prefers-color-scheme: dark`); body text must be light on the dark dialog.
- [ ] **Step 6: Commit** — `git add web/src/theme.ts web/src/theme.test.ts && git commit -m "fix: palette text colours follow dark-mode tokens"`

---

### Task 2: Applications table per-column sorting

**Files:**
- Create: `web/src/applications/sorting.ts`
- Create: `web/src/applications/sorting.test.ts`
- Modify: `web/src/applications/ApplicationsPage.tsx` (COLUMNS `:42-58`, header render `:278-280`, sort call `:284-285`)

**Interfaces:**
- Consumes: `Application` from `web/src/api/types.ts:223-242`; `STATUS_ORDER`/`statusRank` currently at `ApplicationsPage.tsx:78-90` (move into sorting.ts).
- Produces: `type SortDirection = "asc" | "desc"`; `type ColumnDef = { label: string; sortable: boolean; compare?: (a: Application, b: Application) => number }`; `const COLUMN_DEFS: ColumnDef[]`; `function compareApplications(a: Application, b: Application, col: ColumnDef | null, dir: SortDirection): number`; `function defaultCompare(a: Application, b: Application): number` (status rank — today's behaviour).

- [ ] **Step 1: Write failing tests** in `web/src/applications/sorting.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import type { Application } from "../api/types";
import { COLUMN_DEFS, compareApplications, defaultCompare } from "./sorting";

const app = (over: Partial<Application>): Application =>
  ({ id: "x", company: "", applicationDate: "", website: "", applicationUrl: "",
     submitted: false, submissionType: "", status: "", reachedOut: false,
     toWho: "", responseReceived: false, method: "", notes: "", posting: "",
     role: "", cvDocument: null, coverLetterDocument: null,
     createdAt: "", updatedAt: "" } as unknown as Application);
// NOTE to implementer: build this helper from the real Application fields in
// api/types.ts:223-242 — do not invent field names; adjust the literal above
// to the actual interface so it typechecks without the `unknown` cast if possible.

const col = (label: string) => COLUMN_DEFS.find((c) => c.label === label)!;

describe("sorting", () => {
  it("company sorts case-insensitively, blanks last", () => {
    const a = app({ company: "acme" }), b = app({ company: "Beta" }), blank = app({ company: "" });
    expect(compareApplications(a, b, col("Company"), "asc")).toBeLessThan(0);
    expect(compareApplications(blank, a, col("Company"), "asc")).toBeGreaterThan(0);
  });
  it("date sorts chronologically", () => {
    const early = app({ applicationDate: "2026-01-02" }), late = app({ applicationDate: "2026-03-01" });
    expect(compareApplications(early, late, col("Date"), "asc")).toBeLessThan(0);
    expect(compareApplications(early, late, col("Date"), "desc")).toBeGreaterThan(0);
  });
  it("boolean columns sort yes-first ascending", () => {
    const yes = app({ submitted: true }), no = app({ submitted: false });
    expect(compareApplications(yes, no, col("Submitted"), "asc")).toBeLessThan(0);
  });
  it("status uses the status rank order", () => {
    const offer = app({ status: "Offer" }), rejected = app({ status: "Rejected" });
    expect(compareApplications(offer, rejected, col("Status"), "asc")).toBeLessThan(0);
    expect(defaultCompare(offer, rejected)).toBeLessThan(0);
  });
  it("documents sorts by presence", () => {
    const has = app({ cvDocument: { } as never }), not = app({});
    expect(compareApplications(has, not, col("Documents"), "asc")).toBeLessThan(0);
  });
  it("actions column is not sortable", () => {
    expect(COLUMN_DEFS[COLUMN_DEFS.length - 1].sortable).toBe(false);
  });
});
```

- [ ] **Step 2: Run — expect FAIL** (module missing): `npx vitest run src/applications/sorting.test.ts`
- [ ] **Step 3: Implement `web/src/applications/sorting.ts`**:

```ts
import type { Application } from "../api/types";

export type SortDirection = "asc" | "desc";
export type ColumnDef = {
  label: string;
  sortable: boolean;
  compare?: (a: Application, b: Application) => number;
};

// Moved verbatim from ApplicationsPage.tsx:78-90 (STATUS_ORDER + statusRank),
// including its comment. Delete them from the page when wiring up.
const STATUS_ORDER = [/* ... move exact array ... */];
export function statusRank(status: string): number { /* moved body */ }

const text = (get: (a: Application) => string | null | undefined) =>
  (a: Application, b: Application) => {
    const av = (get(a) ?? "").trim(), bv = (get(b) ?? "").trim();
    if (!av && !bv) return 0;
    if (!av) return 1;           // blanks last regardless of direction handled by caller? No:
    if (!bv) return -1;          // blanks last in ascending; desc flips (accepted).
    return av.toLowerCase().localeCompare(bv.toLowerCase());
  };
const bool = (get: (a: Application) => boolean) =>
  (a: Application, b: Application) => Number(get(b)) - Number(get(a)); // yes-first asc
const presence = (get: (a: Application) => unknown) =>
  (a: Application, b: Application) => Number(Boolean(get(b))) - Number(Boolean(get(a)));

const host = (url: string | null | undefined): string => {
  if (!url) return "";
  try { return new URL(url).host; } catch { return url; }
};

export const COLUMN_DEFS: ColumnDef[] = [
  { label: "Company", sortable: true, compare: text((a) => a.company) },
  { label: "Date", sortable: true, compare: text((a) => a.applicationDate) }, // ISO strings: lexicographic = chronological
  { label: "Website", sortable: true, compare: text((a) => host(a.website)) },
  { label: "Application URL", sortable: true, compare: presence((a) => a.applicationUrl) },
  { label: "Submitted", sortable: true, compare: bool((a) => a.submitted) },
  { label: "Submission Type", sortable: true, compare: text((a) => a.submissionType) },
  { label: "Status", sortable: true, compare: (a, b) => statusRank(a.status) - statusRank(b.status) },
  { label: "Reached Out", sortable: true, compare: bool((a) => a.reachedOut) },
  { label: "To Who", sortable: true, compare: text((a) => a.toWho) },
  { label: "Response Received", sortable: true, compare: bool((a) => a.responseReceived) },
  { label: "Method", sortable: true, compare: text((a) => a.method) },
  { label: "Notes", sortable: true, compare: text((a) => a.notes) },
  { label: "Posting", sortable: true, compare: presence((a) => a.posting) },
  { label: "Documents", sortable: true, compare: presence((a) => a.cvDocument ?? a.coverLetterDocument) },
  { label: "", sortable: false },
];

export function defaultCompare(a: Application, b: Application): number {
  return statusRank(a.status) - statusRank(b.status);
}

export function compareApplications(
  a: Application, b: Application, col: ColumnDef | null, dir: SortDirection,
): number {
  if (!col?.compare) return defaultCompare(a, b);
  const r = col.compare(a, b);
  return dir === "desc" ? -r : r;
}
```

Adjust field access to the real `Application` interface (`web/src/api/types.ts:223-242`) — if a field named here doesn't exist, use the actual name; do not add fields.

- [ ] **Step 4: Run tests — expect PASS.** Fix implementation, not tests (unless a test used a wrong field name).
- [ ] **Step 5: Wire the page.** In `ApplicationsPage.tsx`:
  - Delete local `COLUMNS` (`:42-58`) and `STATUS_ORDER`/`statusRank` (`:76-90`); import from `./sorting`.
  - Add state: `const [sortCol, setSortCol] = useState<ColumnDef | null>(null); const [sortDir, setSortDir] = useState<SortDirection>("asc");`
  - Header render (was `:278-280`):

```tsx
{COLUMN_DEFS.map((c) => (
  <TableCell key={c.label || "actions"}>
    {c.sortable ? (
      <TableSortLabel
        active={sortCol?.label === c.label}
        direction={sortCol?.label === c.label ? sortDir : "asc"}
        onClick={() => {
          if (sortCol?.label === c.label) setSortDir(sortDir === "asc" ? "desc" : "asc");
          else { setSortCol(c); setSortDir("asc"); }
        }}
      >
        {c.label}
      </TableSortLabel>
    ) : (
      c.label
    )}
  </TableCell>
))}
```

  - Row sort (was `:284-285`): `[...apps].sort((a, b) => compareApplications(a, b, sortCol, sortDir))`. Every other use of `COLUMNS.length` (colSpan at `:263` and `:289` area) becomes `COLUMN_DEFS.length`.
  - Import `TableSortLabel` from `@mui/material/TableSortLabel`.
- [ ] **Step 6: Verify** — `npm run typecheck && npm test`; then in the running app click each header: order flips, default (no column chosen) unchanged from today.
- [ ] **Step 7: Commit** — `git add web/src/applications && git commit -m "feat: per-column sorting on the applications table"`

---

### Task 3: Notes 2-line clamp

**Files:**
- Modify: `web/src/applications/ApplicationsPage.tsx:402-404` (notes cell)

No unit test (pure CSS presentation); verified visually.

- [ ] **Step 1: Implement** — replace the notes cell sx:

```tsx
<TableCell
  sx={{
    maxWidth: 220,
    whiteSpace: "normal",
    display: "-webkit-box",
    WebkitLineClamp: 2,
    WebkitBoxOrient: "vertical",
    overflow: "hidden",
  }}
>
  {app.notes || "—"}
</TableCell>
```

- [ ] **Step 2: Verify** — typecheck; in the app, a long note shows two lines ending in an ellipsis; Edit still shows the full text (the multiline Notes field, `ApplicationForm`).
- [ ] **Step 3: Commit** — `git commit -am "fix: clamp notes to two lines in the applications table"`

---

### Task 4: Agent config store (Python)

**Files:**
- Create: `agentconfig/__init__.py` (empty), `agentconfig/store.py`
- Test: `tests/test_agent_config_store.py`

**Interfaces:**
- Consumes: `truth.store.data_dir` (same pattern as `truth/answers.py:94-123`).
- Produces: `@dataclass AgentConfig` with `enabled: bool = True`, `blocked_companies: list[str] = field(default_factory=list)`, `run_at: list[str] = field(default_factory=lambda: ["09:00", "15:00"])`, `run_days: list[str] = field(default_factory=lambda: ["mon","tue","wed","thu","fri"])`; `AgentConfig.from_dict(raw: dict) -> AgentConfig`; `AgentConfig.to_dict() -> dict` (snake_case keys); `load() -> AgentConfig`; `save(cfg: AgentConfig) -> AgentConfig`; `is_blocked(cfg: AgentConfig, company: str) -> bool` (strip/casefold equality; blank/non-string company → False).
- Storage: `data_dir() / "agent_config.json"`, atomic write via `.tmp` + `replace` (the `truth/answers.py:114-123` pattern, json instead of yaml).

- [ ] **Step 1: Write failing tests** `tests/test_agent_config_store.py`:

```python
"""Agent config store: defaults, round-trip, atomicity, blocklist matching."""

from agentconfig import store


def test_defaults_when_missing(data_dir):
    cfg = store.load()
    assert cfg.enabled is True
    assert cfg.blocked_companies == []
    assert cfg.run_at == ["09:00", "15:00"]
    assert cfg.run_days == ["mon", "tue", "wed", "thu", "fri"]


def test_round_trip(data_dir):
    cfg = store.load()
    cfg.enabled = False
    cfg.blocked_companies = ["Acme GmbH"]
    cfg.run_at = ["07:30"]
    cfg.run_days = ["sat", "sun"]
    store.save(cfg)
    again = store.load()
    assert again == cfg
    assert (data_dir / "agent_config.json").exists()


def test_corrupt_file_yields_defaults(data_dir):
    (data_dir / "agent_config.json").write_text("not json", encoding="utf-8")
    assert store.load() == store.AgentConfig()


def test_partial_file_keeps_defaults_for_missing_fields(data_dir):
    (data_dir / "agent_config.json").write_text('{"enabled": false}', encoding="utf-8")
    cfg = store.load()
    assert cfg.enabled is False
    assert cfg.run_at == ["09:00", "15:00"]


def test_is_blocked_matches_like_cooldown(data_dir):
    cfg = store.AgentConfig(blocked_companies=["  Acme GmbH "])
    assert store.is_blocked(cfg, "acme gmbh")
    assert store.is_blocked(cfg, "ACME GMBH  ")
    assert not store.is_blocked(cfg, "Acme")          # exact equality, not substring
    assert not store.is_blocked(cfg, "")
    assert not store.is_blocked(cfg, None)  # type: ignore[arg-type]
```

- [ ] **Step 2: Run — expect FAIL** (`python -m pytest tests/test_agent_config_store.py -v`, ModuleNotFoundError).
- [ ] **Step 3: Implement `agentconfig/store.py`** — dataclass + `from_dict` (ignore unknown keys, fall back to defaults on wrong types per-field), `load` returning defaults on missing/corrupt/non-dict file, atomic `save`, `is_blocked` guarding non-string/blank company then `company.strip().casefold()` against each entry's `strip().casefold()`. Module docstring: one sentence naming the file and that env stays the agent's fallback.
- [ ] **Step 4: Run — expect PASS.** Also run the whole suite once: `python -m pytest`.
- [ ] **Step 5: Commit** — `git add agentconfig tests/test_agent_config_store.py && git commit -m "feat: agent config store (enabled, blocklist, schedule)"`

---

### Task 5: `GET/PUT /api/agent/config`

**Files:**
- Modify: `api/schemas.py` (new models near `AnswersUpdate`, `:219`), `api/routes.py` (new routes near the screening block, `:85-110`)
- Test: `tests/test_agent_config_api.py`

**Interfaces:**
- Consumes: Task 4's `agentconfig.store` (`load`, `save`, `AgentConfig`).
- Produces: wire model `AgentConfigModel(_Camel)` with `enabled: bool`, `blocked_companies: list[str]`, `run_at: list[str]`, `run_days: list[str]` (camelCase on the wire via `_Camel`); `AgentConfigUpdate(_Camel)` with all four optional; routes `GET /api/agent/config` and `PUT /api/agent/config` (merge semantics like `put_profile_answers`, `routes.py:659-670`).
- Validation in `AgentConfigUpdate` (pydantic `field_validator`s): `run_at` non-empty, each matching `^([01][0-9]|2[0-3]):[0-5][0-9]$`; `run_days` non-empty, each in `{"mon","tue","wed","thu","fri","sat","sun"}`, deduped preserving order; `blocked_companies` entries stripped, empties dropped. Invalid → 422 (pydantic default).

- [ ] **Step 1: Write failing tests** `tests/test_agent_config_api.py` (copy client-fixture style from `tests/test_settings_api.py` — read it first; it builds a `TestClient` over the app with `data_dir`):

```python
"""/api/agent/config: defaults, merge-on-PUT, validation."""


def test_get_returns_defaults(client, data_dir):
    r = client.get("/api/agent/config")
    assert r.status_code == 200
    assert r.json() == {
        "enabled": True,
        "blockedCompanies": [],
        "runAt": ["09:00", "15:00"],
        "runDays": ["mon", "tue", "wed", "thu", "fri"],
    }


def test_put_merges_partial(client, data_dir):
    r = client.put("/api/agent/config", json={"enabled": False})
    assert r.status_code == 200
    assert r.json()["enabled"] is False
    assert r.json()["runAt"] == ["09:00", "15:00"]  # untouched


def test_put_blocklist_strips_and_drops_empties(client, data_dir):
    r = client.put("/api/agent/config", json={"blockedCompanies": [" Acme ", "", "  "]})
    assert r.json()["blockedCompanies"] == ["Acme"]


def test_put_rejects_bad_time(client, data_dir):
    assert client.put("/api/agent/config", json={"runAt": ["9:00"]}).status_code == 422
    assert client.put("/api/agent/config", json={"runAt": ["25:00"]}).status_code == 422
    assert client.put("/api/agent/config", json={"runAt": []}).status_code == 422


def test_put_rejects_bad_day(client, data_dir):
    assert client.put("/api/agent/config", json={"runDays": ["monday"]}).status_code == 422
    assert client.put("/api/agent/config", json={"runDays": []}).status_code == 422
```

Match the actual fixture names in `tests/test_settings_api.py`; if there is no shared `client` fixture, create one locally the same way that file does.

- [ ] **Step 2: Run — expect FAIL** (404s).
- [ ] **Step 3: Implement** — schemas + two route functions:

```python
@router.get("/agent/config", response_model=AgentConfigModel)
def get_agent_config() -> AgentConfigModel:
    return AgentConfigModel.model_validate(agent_config_store.load().to_dict())


@router.put("/agent/config", response_model=AgentConfigModel)
def put_agent_config(body: AgentConfigUpdate) -> AgentConfigModel:
    """Merge only the fields the client sent onto the stored config."""
    merged = agent_config_store.load().to_dict()
    merged.update(body.model_dump(exclude_unset=True, by_alias=False))
    cfg = agent_config_store.AgentConfig.from_dict(merged)
    return AgentConfigModel.model_validate(agent_config_store.save(cfg).to_dict())
```

Import as `from agentconfig import store as agent_config_store` alongside the existing store imports at the top of `routes.py`.

- [ ] **Step 4: Run task tests + full suite — expect PASS.**
- [ ] **Step 5: Commit** — `git add api tests/test_agent_config_api.py && git commit -m "feat: GET/PUT /api/agent/config"`

---

### Task 6: Blocklist enforced in cooldown

**Files:**
- Modify: `screening/cooldown.py` (`CooldownStatus` `:32-37`, `cooldown()` `:91-108`), `mcp/tools_ledger.py:68-76` (`check_cooldown` return), `api/schemas.py` `CooldownResult` (`:415`), `api/routes.py` `get_cooldown` (`:108`)
- Test: extend `tests/test_screening_api.py` and add cases to a new `tests/test_cooldown_blocklist.py`

**Interfaces:**
- Consumes: Task 4's `agentconfig.store.load` / `is_blocked`.
- Produces: `CooldownStatus` gains `blocked: bool = False`. Blocked company → `CooldownStatus(in_cooldown=True, expires=None, blocked=True)` (permanent: no expiry). `check_cooldown` tool dict and `CooldownResult` wire model gain the same `blocked` field (default False — additive, no caller breaks).

- [ ] **Step 1: Write failing tests** `tests/test_cooldown_blocklist.py`:

```python
"""Blocklisted companies report permanent cooldown through every surface."""

from agentconfig import store as agent_config_store
from screening.cooldown import cooldown


def _block(data_dir, name):
    cfg = agent_config_store.load()
    cfg.blocked_companies = [name]
    agent_config_store.save(cfg)


def test_blocked_company_is_permanently_in_cooldown(data_dir):
    _block(data_dir, "Acme GmbH")
    status = cooldown("acme gmbh")
    assert status.in_cooldown is True
    assert status.blocked is True
    assert status.expires is None


def test_unblocked_company_unaffected(data_dir):
    _block(data_dir, "Acme GmbH")
    status = cooldown("Beta AG")
    assert status.in_cooldown is False
    assert status.blocked is False


def test_block_beats_role_narrowing(data_dir):
    _block(data_dir, "Acme GmbH")
    assert cooldown("Acme GmbH", role="Engineer").blocked is True


def test_api_and_tool_carry_blocked_flag(client, data_dir):
    _block(data_dir, "Acme GmbH")
    r = client.get("/api/cooldown", params={"company": "Acme GmbH"})
    assert r.json() == {"inCooldown": True, "expires": None, "blocked": True}
    from mcp.tools_ledger import check_cooldown
    assert check_cooldown("Acme GmbH") == {"in_cooldown": True, "expires": None, "blocked": True}
```

(Reuse the same client fixture arrangement as Task 5. Check the actual camelCase key the `CooldownResult` model produces — read the existing `/api/cooldown` test in `tests/test_screening_api.py` and match its shape.)

- [ ] **Step 2: Run — expect FAIL** (no `blocked` attr).
- [ ] **Step 3: Implement** — in `cooldown()` (after the blank-company guard at `:100-101`):

```python
    cfg = agent_config_load()
    if agent_config_is_blocked(cfg, company):
        return CooldownStatus(in_cooldown=True, expires=None, blocked=True)
```

with `from agentconfig.store import is_blocked as agent_config_is_blocked, load as agent_config_load` at the top, `blocked: bool = False` on the dataclass, docstring sentence: "A blocklisted company is permanently in cooldown (blocked=True, no expiry)." Thread `blocked` through `check_cooldown`'s dict and `CooldownResult`.

- [ ] **Step 4: Run task tests + full suite — expect PASS** (existing cooldown tests must be untouched and green: `blocked` defaults False).
- [ ] **Step 5: Commit** — `git add screening mcp api tests && git commit -m "feat: company blocklist reports permanent cooldown"`

---

### Task 7: `generate_cover_letter` refusal for blocked companies

**Files:**
- Modify: `mcp/tools_letter.py:24` (signature + guard)
- Test: `tests/test_agent_mcp.py` (add cases; read its existing style first)

**Interfaces:**
- Consumes: Task 4's `is_blocked`/`load`.
- Produces: `generate_cover_letter(posting, tone, length, denied_texts=None, paragraphs=None, provider=None, company: str | None = None)` — new optional kwarg LAST so existing positional callers are unaffected. When `company` is given and blocked, return `{"text": "", "blocked": True, "blocked_reason": "company_blocked", "paragraphs": []}` **before** any provider call (no LLM cost for a refused letter). `company=None` keeps today's behaviour (the wizard's route doesn't pass it).

- [ ] **Step 1: Write failing tests** (append to `tests/test_agent_mcp.py`, following its fixture style):

```python
def test_generate_cover_letter_refuses_blocked_company(data_dir):
    from agentconfig import store as agent_config_store
    cfg = agent_config_store.load()
    cfg.blocked_companies = ["Acme GmbH"]
    agent_config_store.save(cfg)

    from mcp.tools_letter import generate_cover_letter
    result = generate_cover_letter(
        "posting text", "neutral", "short", company="acme gmbh"
    )
    assert result == {
        "text": "", "blocked": True,
        "blocked_reason": "company_blocked", "paragraphs": [],
    }
    # provider must never be touched: passing provider=None would normally
    # resolve one; the refusal path returns before that. If this test errors
    # trying to build a provider, the guard is in the wrong place.
```

Adjust the expected dict to include exactly the keys the existing return dict has (read the end of `tools_letter.py`) with refusal values; keep `blocked_reason` as the one new key.

- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement** the guard as the first statements of the function, before `get_provider()`:

```python
    if company is not None:
        from agentconfig.store import is_blocked, load as load_agent_config
        if is_blocked(load_agent_config(), company):
            return {"text": "", "blocked": True,
                    "blocked_reason": "company_blocked", "paragraphs": []}
```

(Top-level import is fine too if it creates no cycle — prefer top-level, drop to local only if `python -m pytest` shows an import cycle.) Docstring gains: "`company`, when given, is refused outright if blocklisted in the agent config."

- [ ] **Step 4: Run task tests + full suite — expect PASS.**
- [ ] **Step 5: Commit** — `git add mcp tests/test_agent_mcp.py && git commit -m "feat: cover-letter tool refuses blocklisted companies"`

---

### Task 8: Agent scripts — enabled gate + fetched schedule

**Files:**
- Create: `agent/agent-config.js` (node helper)
- Modify: `agent/daily-apply.sh` (gate between `:63` and `:65`), `agent/entrypoint.sh` (schedule source + chunked sleep), `docker-compose.yml:47-49` comment, `agent/README.md` env table (`:97-107` region) and schedule section (`:109-112`)
- No automated test harness exists for bash; verification is by running the scripts (steps below).

**Interfaces:**
- Consumes: Task 5's `GET /api/agent/config` (camelCase JSON).
- Produces: `agent/agent-config.js` — invoked as `node /app/agent/agent-config.js <field>` where `<field>` ∈ `enabled|run_at|run_days`. Derives the config URL from `TRUTHCV_MCP_URL` by replacing a trailing `/mcp` with `/api/agent/config`. Prints: for `enabled` → `true`/`false`; `run_at` → comma-joined `HH:MM` list; `run_days` → comma-joined ISO day numbers (mon=1..sun=7, converting the API's names). Exit 0 on success; **exit 1 and print nothing on any error** (unreachable, bad JSON, missing field) so bash callers can fall back.

- [ ] **Step 1: Write `agent/agent-config.js`:**

```js
// Fetch one field of the agent config from the app service. The agent image
// has no curl (see daily-apply.sh's note); node is the only HTTP client.
// Usage: node agent-config.js enabled|run_at|run_days
// Errors print nothing and exit 1 — callers fall back to env defaults.
const field = process.argv[2];
const DAY_NUM = { mon: 1, tue: 2, wed: 3, thu: 4, fri: 5, sat: 6, sun: 7 };
const base = process.env.TRUTHCV_MCP_URL;
if (!base || !["enabled", "run_at", "run_days"].includes(field)) process.exit(1);
let u;
try { u = new URL(base.replace(/\/mcp\/?$/, "") + "/api/agent/config"); } catch { process.exit(1); }
const http = require(u.protocol === "https:" ? "https" : "http");
const req = http.get(u, { timeout: 5000 }, (res) => {
  if (res.statusCode !== 200) { res.resume(); process.exit(1); }
  let body = "";
  res.on("data", (c) => (body += c));
  res.on("end", () => {
    try {
      const cfg = JSON.parse(body);
      if (field === "enabled") process.stdout.write(String(cfg.enabled === true));
      else if (field === "run_at") process.stdout.write(cfg.runAt.join(","));
      else process.stdout.write(cfg.runDays.map((d) => DAY_NUM[d]).filter(Boolean).join(","));
      process.exit(0);
    } catch { process.exit(1); }
  });
});
req.on("error", () => process.exit(1));
req.on("timeout", () => { req.destroy(); process.exit(1); });
```

- [ ] **Step 2: Gate in `daily-apply.sh`** — insert after `log "preconditions OK"` (`:63`), before the Run section:

```bash
# --- Agent enable gate --------------------------------------------------------
# The Agents page can switch the agent off; the flag lives in the app service's
# agent config (GET /api/agent/config). Unreachable config fails CLOSED: if the
# app is down, the MCP tools this run depends on are down too, and "did not
# run" is the safe failure for an unattended submitter.
ENABLED="$(node "${AGENT_CONFIG_JS:-/app/agent/agent-config.js}" enabled)" || ENABLED=""
if [[ "$ENABLED" == "false" ]]; then
  log "agent disabled in config - skipping run"
  exit 0
elif [[ "$ENABLED" != "true" ]]; then
  abort "agent config unreachable - skipping run (fail closed)"
fi
```

- [ ] **Step 3: Schedule in `entrypoint.sh`:**
  - Rename the env reads (`:19-20`) to defaults: `RUN_AT_DEFAULT="${RUN_AT:-09:00,15:00}"`, `RUN_DAYS_DEFAULT="${RUN_DAYS:-1,2,3,4,5}"`, and add:

```bash
# Schedule source of truth is the app's agent config (Agents page); the RUN_AT/
# RUN_DAYS env values are only the fallback when the config API is unreachable.
refresh_schedule() {
  local at days
  at="$(node "${AGENT_CONFIG_JS:-/app/agent/agent-config.js}" run_at 2>/dev/null)" || at=""
  days="$(node "${AGENT_CONFIG_JS:-/app/agent/agent-config.js}" run_days 2>/dev/null)" || days=""
  RUN_AT="${at:-$RUN_AT_DEFAULT}"
  RUN_DAYS="${days:-$RUN_DAYS_DEFAULT}"
  validate_run_at || { RUN_AT="$RUN_AT_DEFAULT"; RUN_DAYS="$RUN_DAYS_DEFAULT"; }
}
```

  - Main loop (`:129-137`) becomes chunked so mid-sleep edits land within ~5 min:

```bash
while true; do
  refresh_schedule
  if ! secs=$(seconds_until_next_slot); then
    log "ERROR: could not compute next slot from RUN_AT=$RUN_AT RUN_DAYS=$RUN_DAYS"
    exit 1
  fi
  if (( secs > 300 )); then
    sleep 300
    continue          # re-fetch and recompute; the slot may have moved
  fi
  log "next run in ${secs}s ($(date -d "@$(( $(date +%s) + secs ))" '+%a %Y-%m-%d %H:%M %Z'))"
  sleep "$secs"
  do_run || log "run failed; continuing to next slot"
done
```

  Keep the "next run in" log only on the final (<300 s) leg — one log line per 5 minutes forever would flood `docker logs`; if you want a periodic heartbeat, log at most once per hour by counting iterations.
  - `check_schedule()` (`:100-111`) calls `refresh_schedule` first (after `validate_run_at` moves inside it) and prints which source it used: extend its echo line with `source=$([[ -n "$at" ]] && echo config || echo env)` — implement by having `refresh_schedule` set a global `SCHEDULE_SOURCE=config|env`.
  - Update the header comment (`:10-15`): the four-way sync note is replaced by "schedule lives in the agent config (Agents page); env is the fallback."
- [ ] **Step 4: Verify** — `bash -n agent/entrypoint.sh agent/daily-apply.sh` (syntax); `shellcheck` if installed (advisory). Then against a live app (`docker compose up -d app`):
  - `TRUTHCV_MCP_URL=http://localhost:8080/mcp node agent/agent-config.js enabled` prints `true`.
  - `curl -X PUT localhost:8080/api/agent/config -H 'content-type: application/json' -d '{"runAt":["12:34"],"runDays":["sat"]}'` then `TRUTHCV_MCP_URL=http://localhost:8080/mcp agent/entrypoint.sh --check-schedule` shows Saturday 12:34 slots sourced from config; with the app stopped it falls back to env values. Reset config afterwards: `curl -X PUT ... -d '{"runAt":["09:00","15:00"],"runDays":["mon","tue","wed","thu","fri"]}'`.
  - Disabled gate: PUT `{"enabled": false}`, run `daily-apply.sh` with preconditions satisfiable or read the gate path in isolation; at minimum verify the two log lines by temporarily stubbing (do not commit stubs). Reset `enabled` to true.
- [ ] **Step 5: Update `agent/README.md`** — env table: `RUN_AT`/`RUN_DAYS` become "fallback when the config API is unreachable"; add a paragraph on the Agents page as the schedule/enable source; document `agent-config.js`.
- [ ] **Step 6: Commit** — `git add agent docker-compose.yml && git commit -m "feat: agent reads enabled flag and schedule from agent config API"`

---

### Task 9: RUNBOOK blocklist documentation

**Files:**
- Modify: `agent/RUNBOOK.md` §8 (`:234-293`) and §5.3 (cover-letter step), `agent/prompt.md` only if it enumerates check_cooldown semantics (read it; do not change the "exactly six tools" list — no tool was added).

**Interfaces:** none; documentation of Tasks 6-7 behaviour.

- [ ] **Step 1: §8 addition** (after the cooldown rules, matching the section's voice):

```markdown
### Blocked companies

The operator can blocklist companies on the Agents page. A blocklisted
company reports `in_cooldown: true` with `blocked: true` and no expiry from
`check_cooldown` — treat it exactly like a cooldown that never expires:
do not apply, do not retry later, do not attempt to work around it.
`generate_cover_letter` will also refuse (`blocked_reason:
"company_blocked"`) when you pass the company name.
```

- [ ] **Step 2: §5.3** — add: "Always pass `company` (the name as posted) to `generate_cover_letter` so the blocklist can refuse before any text is generated."
- [ ] **Step 3: Verify** — reread both sections in context; no contradiction with §8's existing open-issue note on cooldown windows.
- [ ] **Step 4: Commit** — `git add agent/RUNBOOK.md agent/prompt.md && git commit -m "docs: blocklist semantics in the agent runbook"`

---

### Task 10: Web API client + types for agent config

**Files:**
- Modify: `web/src/api/types.ts`, `web/src/api/client.ts`
- Test: extend the API-client test in `web/src/settings/SettingsModal.test.tsx` only if it already stubs `fetch` for client functions (read it); otherwise no test — the client functions are one-liners over `request`.

**Interfaces:**
- Produces:

```ts
// types.ts
export interface AgentConfig {
  enabled: boolean;
  blockedCompanies: string[];
  runAt: string[];
  runDays: string[];
}
export type AgentConfigUpdate = Partial<AgentConfig>;

// client.ts (same request() idiom as updateApplication, client.ts:214-224)
export function getAgentConfig(): Promise<AgentConfig>;
export function updateAgentConfig(body: AgentConfigUpdate): Promise<AgentConfig>;
```

- [ ] **Step 1: Implement** both files (client bodies: `request("/api/agent/config")` and `request("/api/agent/config", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })`).
- [ ] **Step 2: Typecheck** — `npm run typecheck`.
- [ ] **Step 3: Commit** — `git add web/src/api && git commit -m "feat: agent config API client"`

---

### Task 11: Agents page component

**Files:**
- Create: `web/src/agents/AgentsPage.tsx`
- Create: `web/src/agents/schedule.ts` + `web/src/agents/schedule.test.ts` (pure helpers)
- Modify: `web/src/styles/settings.css` only if the moved sections referenced classes from it (check while moving).

**Interfaces:**
- Consumes: Task 10's client functions; `getProfileAnswers`/`updateProfileAnswers` (or actual names — read `web/src/api/client.ts`), `listScreenings`/`deleteScreening`; the JSX being moved: profile answers fields `SettingsModal.tsx:504-551`, screenings table `:555-587`; `isCooldownActive` from `web/src/settings/cooldown.ts` and `lastAgentActivity` from `web/src/settings/agentActivity.ts` (imports move with the table).
- Produces: `export function AgentsPage({ onBack }: { onBack: () => void })` — same page contract as `AnalyticsPage` (`App.tsx:128`). `schedule.ts` exports `isValidRunTime(s: string): boolean` (regex `^([01]\d|2[0-3]):[0-5]\d$`), `WEEKDAYS: { key: string; label: string }[]` (`mon..sun` → `Mon..Sun`), `formatRunTimes(times: string[]): string` (join " and ").

- [ ] **Step 1: Write failing tests** `web/src/agents/schedule.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { formatRunTimes, isValidRunTime, WEEKDAYS } from "./schedule";

describe("schedule helpers", () => {
  it("validates HH:MM", () => {
    expect(isValidRunTime("09:00")).toBe(true);
    expect(isValidRunTime("23:59")).toBe(true);
    expect(isValidRunTime("9:00")).toBe(false);
    expect(isValidRunTime("24:00")).toBe(false);
    expect(isValidRunTime("09:60")).toBe(false);
  });
  it("lists seven ordered weekdays keyed for the API", () => {
    expect(WEEKDAYS.map((d) => d.key)).toEqual(["mon","tue","wed","thu","fri","sat","sun"]);
  });
  it("formats run times", () => {
    expect(formatRunTimes(["09:00", "15:00"])).toBe("09:00 and 15:00");
    expect(formatRunTimes(["07:00"])).toBe("07:00");
  });
});
```

- [ ] **Step 2: Run — FAIL; implement `schedule.ts`; run — PASS.**
- [ ] **Step 3: Build `AgentsPage.tsx`.** Structure (follow `AnalyticsPage`'s page scaffolding — header with back button, sections as MUI `Paper variant="outlined"` blocks):
  1. **Agent** — `Switch` bound to `config.enabled`, label "Agent enabled", helper `Typography variant="body2" color="text.secondary"`: "When off, scheduled runs wake, log that the agent is disabled, and exit. Nothing is submitted until re-enabled." Toggling calls `updateAgentConfig({ enabled })` immediately (optimistic, revert on error).
  2. **Schedule** — chips of current `runAt` each with delete; `TextField` + Add button gated on `isValidRunTime` (inline error otherwise, and forbid removing the last time); `Checkbox` row from `WEEKDAYS` bound to `runDays` (at least one required). Save button per section → `updateAgentConfig({ runAt, runDays })`. Helper text: "Changes take effect within about five minutes; the agent re-reads its schedule between runs."
  3. **Blocked companies** — list of names each with a remove button; `TextField` + Add (trim, ignore empty, case-insensitive duplicate check against existing entries). Saves immediately via `updateAgentConfig({ blockedCompanies })`. Helper: "The agent will never apply to a blocked company. Matching is by exact name, ignoring case."
  4. **Profile answers** — the five fields moved verbatim from `SettingsModal.tsx:504-551`, with their own Save calling only the profile-answers PUT (partial body of the five fields).
  5. **Screening & cooldowns** — the table moved verbatim from `SettingsModal.tsx:555-587` with its delete handler (`:341-354` logic) and its `cooldown.ts`/`agentActivity.ts` imports.
  - Load on mount with `Promise.all([getAgentConfig(), getProfileAnswers(), listScreenings()])`; per-section error/success state following the modal's existing pattern; loading spinner like `App.tsx:80-94`'s idiom.
- [ ] **Step 4: Verify** — `npm run typecheck && npm test`. Page renders (wired next task, or temporarily via a scratch render — do not commit scratch).
- [ ] **Step 5: Commit** — `git add web/src/agents && git commit -m "feat: Agents page (enable, schedule, blocklist, answers, screenings)"`

---

### Task 12: Wire navigation; slim the settings modal

**Files:**
- Modify: `web/src/App.tsx` (`View` `:20`, rail props `:98-113`, view branch `:122-129`), `web/src/wizard/StepRail.tsx` (Props `:9-20`, bottom buttons `:71-105`), `web/src/settings/SettingsModal.tsx` (delete moved sections + their state/imports; save no longer PUTs answers)

**Interfaces:**
- Consumes: Task 11's `AgentsPage`.
- Produces: `View = "wizard" | "applications" | "analytics" | "agents"`; `StepRail` gains `onOpenAgents: () => void` and `agentsActive?: boolean`.

- [ ] **Step 1: StepRail** — add the two props (JSDoc matching neighbours) and a fourth button between Analytics and Settings, `startIcon={<SmartToyOutlinedIcon fontSize="small" />}` (import from `@mui/icons-material/SmartToyOutlined`), label "Agents", same `variant`/`aria-current` pattern as Applications (`:77-86`).
- [ ] **Step 2: App.tsx** — extend the union and the doc comment (`:19-20`); pass `onOpenAgents={() => setView("agents")}` and `agentsActive={view === "agents"}`; add branch `view === "agents" ? <AgentsPage onBack={() => setView("wizard")} /> :` after analytics (`:127-128`); import.
- [ ] **Step 3: Slim SettingsModal** — delete the profile-answers section (`:504-551`), screenings section (`:555-587`), schedule chips (`:591-596`) and `AGENT_RUN_TIMES` (`:128-134`); remove their state, the `getProfileAnswers`/`listScreenings`/delete-screening plumbing from the mount `Promise.all` (`:259-285`) and `handleSave`'s answers PUT (`:298-320`); prune now-unused imports (including `cooldown.ts`/`agentActivity.ts` if unreferenced). The modal keeps Provider + Test connection only. Update the modal's own header/copy if it mentions the removed sections.
- [ ] **Step 4: Verify** — `npm run typecheck && npm test && npm run build`. In the app: Agents button navigates; all five sections function against the live API (toggle, schedule save, blocklist add/remove, answers save, screening delete); Settings modal shows only Provider and still saves provider settings.
- [ ] **Step 5: Commit** — `git add web/src && git commit -m "feat: Agents page navigation; settings modal keeps provider only"`

---

### Task 13: Full verification pass

- [ ] **Step 1:** `python -m pytest` — all green.
- [ ] **Step 2:** `cd web && npm run typecheck && npm test && npm run build` — all green.
- [ ] **Step 3:** `bash -n agent/entrypoint.sh agent/daily-apply.sh`.
- [ ] **Step 4:** End-to-end against `docker compose up -d app`: block a company on the Agents page → `GET /api/cooldown?company=<it>` returns blocked; disable the agent → `node agent/agent-config.js enabled` prints `false`; edit schedule → `entrypoint.sh --check-schedule` reflects it. Re-enable and restore schedule afterwards.
- [ ] **Step 5:** Commit anything outstanding; report status with the boundary: what was verified by execution vs read-only (the agent's in-container run path is exercised only via `--check-schedule` and the config helper, not a live scheduled run).
