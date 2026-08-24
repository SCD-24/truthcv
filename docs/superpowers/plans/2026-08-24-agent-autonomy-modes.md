# Agent Autonomy Modes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the operator a three-way choice — agent off, semi-auto (agent finds and queues, operator drafts the letter and approves), or full auto (agent finds and applies) — with the approval queue split into needs-approval, did-not-pass and rejected lists.

**Architecture:** A `mode` field on `AgentConfig` replaces the stored `enabled` boolean (which becomes derived, so every existing consumer keeps working). `screening.store.create` reads the mode and queues a `passed` verdict in semi-auto, mirroring how it already queues a `deferred` one — the enforcement is server-side, never in the prompt. Cover letters become a per-screening store written only on operator demand through three new routes, and `get_approved_applications` hands the stored text to the agent so it applies with the operator's words verbatim.

**Tech Stack:** Python 3.14, FastAPI, Pydantic v2, plain dataclass + JSON stores on the data volume, pytest; React 19 + TypeScript + MUI v6 + vitest; bash for the agent run scripts.

**Spec:** `docs/superpowers/specs/2026-08-24-agent-autonomy-modes-design.md`

## Global Constraints

- **Python tests run with an isolated data dir.** `./data` in this repo is root-owned; unrelated tests fail against it at baseline. Always run: `DATA_DIR=$(mktemp -d) python3 -m pytest`. Never read a pass/fail status off a piped command — a pipeline reports its last stage's exit code.
- **Baseline is 523 passed, 2 skipped.** Every task must leave the full suite green, not just its own file.
- **`approval` must never enter `Screening.EDITABLE`.** That tuple is what `store.create()`/`update()` copy from caller-supplied fields, and the agent's `record_screening(**fields)` reaches `create()` directly. `tests/test_approvals_api.py::test_no_agent_route_writes_approval` asserts this and must keep passing untouched.
- **Stores write atomically:** tmp file then `replace()`. Follow the existing idiom in `screening/store.py:_write_all` and `companyboards/store.py:save`.
- **Stores fail safe on read:** a missing or corrupt file yields the empty value, never an exception.
- **`from_dict` is defensive per key:** check `in raw` and `isinstance` before assigning, falling back to the default. Follow `agentconfig/store.py:AgentConfig.from_dict` exactly.
- **Wire models are camelCase** via the `_Camel` base in `api/schemas.py`; stores are snake_case. `mode` is the same in both.
- **Web verification is three commands, all must pass:** `npm run typecheck`, `npm test`, `npm run build`, run from `web/`.
- **Comments explain why, not what.** These files are densely commented and the comments are load-bearing; match that register and update any comment your change makes untrue.
- **Do not commit to `main`.** Branch first. The repo already carries unrelated working-tree changes to `docs/`, `.aether/drift.json` and `api/static/` — leave them alone.

---

### Task 1: `mode` on AgentConfig, with `enabled` derived

**Files:**
- Modify: `agentconfig/store.py:123-196` (the `AgentConfig` dataclass, `from_dict`, `to_dict`)
- Test: `tests/test_agent_config_mode.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `AgentConfig.mode: str` (`"off" | "semi" | "full"`, default `"full"`); `AgentConfig.enabled` as a read-only `@property` returning `self.mode != "off"`; `AgentConfig.MODES: tuple[str, ...] = ("off", "semi", "full")`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_agent_config_mode.py`:

```python
"""The agent's autonomy mode, and its migration from the old `enabled` flag.

`enabled` was a stored boolean and is now derived from `mode`. Existing configs
on the volume carry only `enabled`, so the migration in from_dict is what keeps
a running deployment behaving exactly as it did before the upgrade.
"""

from __future__ import annotations

from agentconfig.store import AgentConfig


def test_mode_defaults_to_full():
    assert AgentConfig().mode == "full"


def test_enabled_is_derived_from_mode():
    assert AgentConfig(mode="full").enabled is True
    assert AgentConfig(mode="semi").enabled is True
    assert AgentConfig(mode="off").enabled is False


def test_migrates_enabled_true_to_full():
    """A config written before modes existed keeps the behaviour it had."""
    assert AgentConfig.from_dict({"enabled": True}).mode == "full"


def test_migrates_enabled_false_to_off():
    assert AgentConfig.from_dict({"enabled": False}).mode == "off"


def test_explicit_mode_wins_over_a_stale_enabled():
    assert AgentConfig.from_dict({"enabled": True, "mode": "semi"}).mode == "semi"


def test_unknown_mode_falls_back_to_full():
    """A malformed config must not silently disable the agent."""
    assert AgentConfig.from_dict({"mode": "sideways"}).mode == "full"
    assert AgentConfig.from_dict({"mode": 3}).mode == "full"
    # The combined case is the one that matters: an invalid mode must resolve
    # to the default rather than deferring to a stale `enabled`.
    assert AgentConfig.from_dict({"mode": "sideways", "enabled": False}).mode == "full"
    assert AgentConfig.from_dict({"mode": "sideways", "enabled": True}).mode == "full"


def test_to_dict_carries_mode_and_derived_enabled():
    d = AgentConfig(mode="semi").to_dict()
    assert d["mode"] == "semi"
    assert d["enabled"] is True
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd /home/glenn/Documents/truthcv && DATA_DIR=$(mktemp -d) python3 -m pytest tests/test_agent_config_mode.py -v`

Expected: FAIL — `TypeError: AgentConfig.__init__() got an unexpected keyword argument 'mode'`.

- [ ] **Step 3: Implement**

In `agentconfig/store.py`, in the `AgentConfig` dataclass, replace the `enabled: bool = True` field with a `mode` field and a derived property. The field order matters only for readability; put `mode` where `enabled` was.

```python
@dataclass
class AgentConfig:
    """Agent configuration: autonomy mode, blocklist, schedule, and job profiles."""

    MODES = ("off", "semi", "full")

    mode: str = "full"
    blocked_companies: list[str] = field(default_factory=list)
    # ... the remaining fields are unchanged ...

    @property
    def enabled(self) -> bool:
        """Whether a scheduled run does anything at all.

        Derived rather than stored: two writers for one piece of state is how
        they diverge. Every existing consumer — agent/agent-config.js, the
        run gate in agent/daily-apply.sh, the Agents page's Run now section —
        reads this and keeps working unchanged.
        """
        return self.mode != "off"
```

`MODES` is a plain class attribute, not a dataclass field: it has no annotation, so `@dataclass` ignores it.

In `from_dict`, replace the `enabled` block with:

```python
        # mode: str. Migrated from the pre-mode `enabled` boolean when absent,
        # so a config already on the volume keeps the behaviour it has: an
        # enabled agent was a full-auto agent. An explicit mode wins over a
        # stale enabled, and an unrecognised one falls back to the default
        # rather than disabling the agent by accident.
        if "mode" in raw:
            # Present but unrecognised resolves to the default and must NOT
            # fall through to `enabled`: a corrupt or hand-edited mode sitting
            # beside a stale `enabled: false` would otherwise disable the agent
            # silently, which is the one outcome this fallback exists to stop.
            kwargs["mode"] = raw["mode"] if raw["mode"] in cls.MODES else "full"
        elif "enabled" in raw and isinstance(raw["enabled"], bool):
            kwargs["mode"] = "full" if raw["enabled"] else "off"
```

In `to_dict`, replace `"enabled": self.enabled,` with:

```python
            "mode": self.mode,
            # Derived, not stored — emitted so existing readers of the wire
            # shape (agent-config.js, the Agents page) need no change.
            "enabled": self.enabled,
```

- [ ] **Step 4: Run the new test, then the whole suite**

Run: `cd /home/glenn/Documents/truthcv && DATA_DIR=$(mktemp -d) python3 -m pytest tests/test_agent_config_mode.py -v`
Expected: PASS, 7 tests.

Run: `cd /home/glenn/Documents/truthcv && DATA_DIR=$(mktemp -d) python3 -m pytest`
Expected: PASS. `tests/test_agent_config_api.py` may fail here if it constructs `AgentConfig(enabled=...)` — that is Task 2's job to fix; if so, note it and continue to Task 2 before committing.

- [ ] **Step 5: Commit**

```bash
git add agentconfig/store.py tests/test_agent_config_mode.py
git commit -m "feat(agentconfig): autonomy mode, with enabled derived from it"
```

---

### Task 2: `mode` on the config API

**Files:**
- Modify: `api/schemas.py:321-352` (`AgentConfigModel`, `AgentConfigUpdate`)
- Modify: `api/routes.py:804-816` (`put_agent_config`)
- Test: `tests/test_agent_config_api.py` (append)

**Interfaces:**
- Consumes: `AgentConfig.mode`, `AgentConfig.MODES` from Task 1.
- Produces: `mode` on the `GET /api/agent/config` response and accepted by `PUT /api/agent/config`; `enabled` rejected as a writable field.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agent_config_api.py`:

```python
def test_get_returns_mode_and_derived_enabled(client, data_dir):
    r = client.get("/api/agent/config")
    assert r.status_code == 200
    assert r.json()["mode"] == "full"
    assert r.json()["enabled"] is True


def test_put_sets_mode(client, data_dir):
    r = client.put("/api/agent/config", json={"mode": "semi"})
    assert r.status_code == 200
    assert r.json()["mode"] == "semi"
    assert r.json()["enabled"] is True
    assert client.get("/api/agent/config").json()["mode"] == "semi"


def test_put_off_derives_enabled_false(client, data_dir):
    assert client.put("/api/agent/config", json={"mode": "off"}).json()["enabled"] is False


def test_put_rejects_an_unknown_mode(client, data_dir):
    assert client.put("/api/agent/config", json={"mode": "sideways"}).status_code == 422


def test_put_ignores_enabled(client, data_dir):
    """`enabled` is derived. Accepting a write to it would give one piece of
    state two writers."""
    client.put("/api/agent/config", json={"mode": "semi"})
    r = client.put("/api/agent/config", json={"enabled": False})
    assert r.status_code == 422
    assert client.get("/api/agent/config").json()["mode"] == "semi"
```

- [ ] **Step 2: Run and watch them fail**

Run: `cd /home/glenn/Documents/truthcv && DATA_DIR=$(mktemp -d) python3 -m pytest tests/test_agent_config_api.py -v -k "mode or enabled"`
Expected: FAIL — the response has no `mode` key.

- [ ] **Step 3: Implement**

In `api/schemas.py`, in `AgentConfigModel`, replace `enabled: bool = True` with:

```python
    mode: str = "full"
    # Derived server-side from mode; present so existing readers need no change.
    enabled: bool = True
```

In `AgentConfigUpdate`, replace `enabled: bool | None = None` with `mode: str | None = None` and add a validator beside the existing ones:

```python
    @field_validator("mode")
    @classmethod
    def _known_mode(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in AgentConfig.MODES:
            raise ValueError(f"Unknown mode '{v}'. Expected one of {', '.join(AgentConfig.MODES)}.")
        return v
```

Import `AgentConfig` at the top of `api/schemas.py` beside the other store imports: `from agentconfig.store import AgentConfig`.

Removing `enabled` from `AgentConfigUpdate` is what makes `{"enabled": false}` a 422: `_Camel` must forbid unknown fields for that to hold. Check the `_Camel` base — if it does not already set `model_config = ConfigDict(extra="forbid", ...)`, do **not** change the base class (that would change every model in the file). Instead add to `AgentConfigUpdate` only:

```python
    model_config = ConfigDict(extra="forbid", populate_by_name=True, alias_generator=to_camel)
```

matching whatever `_Camel` sets, plus `extra="forbid"`. Import `ConfigDict` and `to_camel` from where `_Camel` already imports them.

`put_agent_config` in `api/routes.py` needs no change: it merges `model_dump(exclude_unset=True, exclude_none=True)` onto `load().to_dict()` and reconstructs via `from_dict`, which now understands `mode`.

- [ ] **Step 4: Verify**

Run: `cd /home/glenn/Documents/truthcv && DATA_DIR=$(mktemp -d) python3 -m pytest tests/test_agent_config_api.py -v`
Expected: PASS, including the pre-existing tests in that file.

Run: `cd /home/glenn/Documents/truthcv && DATA_DIR=$(mktemp -d) python3 -m pytest`
Expected: PASS, whole suite.

- [ ] **Step 5: Commit**

```bash
git add api/schemas.py tests/test_agent_config_api.py
git commit -m "feat(api): expose agent mode, reject writes to derived enabled"
```

---

### Task 3: Semi-auto queues a passing screening

**Files:**
- Modify: `screening/store.py:61-76` (`create`)
- Modify: `screening/model.py:43-53` (`EDITABLE`), `screening/model.py:19-41` (the dataclass)
- Test: `tests/test_screening_mode_queueing.py` (create)

**Interfaces:**
- Consumes: `AgentConfig.mode` from Task 1.
- Produces: `Screening.posting_text: str`, `Screening.posted_date: str`, both in `EDITABLE`; `create()` sets `approval = "pending"` for a `passed` verdict when the mode is `semi`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_screening_mode_queueing.py`:

```python
"""Semi-auto queues a posting the agent would otherwise apply to.

Enforced in the store rather than the prompt, for the same reason a `deferred`
verdict is: record_screening(**fields) reaches create() directly, so a model
that ignores its instructions still cannot put a posting past the operator.
"""

from __future__ import annotations

import agentconfig.store as config_store
import screening.store as store


def _set_mode(mode: str) -> None:
    config_store.save(config_store.AgentConfig(mode=mode))


def test_passed_is_queued_in_semi(data_dir):
    _set_mode("semi")
    s = store.create({"company": "Grafana Labs", "verdict": "passed"})
    assert s.approval == "pending"


def test_passed_is_not_queued_in_full(data_dir):
    _set_mode("full")
    s = store.create({"company": "Grafana Labs", "verdict": "passed"})
    assert s.approval == ""


def test_deferred_is_queued_in_both_modes(data_dir):
    _set_mode("full")
    assert store.create({"company": "A", "verdict": "deferred"}).approval == "pending"
    _set_mode("semi")
    assert store.create({"company": "B", "verdict": "deferred"}).approval == "pending"


def test_rejected_is_never_queued(data_dir):
    _set_mode("semi")
    assert store.create({"company": "A", "verdict": "rejected"}).approval == ""


def test_posting_text_and_posted_date_round_trip(data_dir):
    s = store.create(
        {
            "company": "Grafana Labs",
            "verdict": "passed",
            "posting_text": "Staff AI Engineer. Germany (Remote). EUR 109k-137k.",
            "posted_date": "2026-08-20",
        }
    )
    loaded = store.get(s.id)
    assert loaded.posting_text.startswith("Staff AI Engineer")
    assert loaded.posted_date == "2026-08-20"


def test_approval_still_cannot_be_set_by_a_caller(data_dir):
    """The invariant the whole approval boundary rests on."""
    s = store.create({"company": "A", "verdict": "rejected", "approval": "approved"})
    assert s.approval == ""
```

- [ ] **Step 2: Run and watch it fail**

Run: `cd /home/glenn/Documents/truthcv && DATA_DIR=$(mktemp -d) python3 -m pytest tests/test_screening_mode_queueing.py -v`
Expected: FAIL — `test_passed_is_queued_in_semi` gets `""`, and the posting-text test gets an `AttributeError`.

- [ ] **Step 3: Implement**

In `screening/model.py`, add two fields to the `Screening` dataclass after `source: str = ""`:

```python
    # The posting as the agent read it. Stored because the operator drafts the
    # letter from it later, in the app, long after the run that found it — and
    # several of these boards cannot be re-fetched at all.
    posting_text: str = ""
    # The employer's publication date, best-effort: many boards publish none.
    # Empty means unknown and is never inferred. `screened_date` is the date
    # this posting was found, which is a different thing.
    posted_date: str = ""
```

Add both to `EDITABLE`, after `"source",`:

```python
        "posting_text",
        "posted_date",
```

In `screening/store.py`, extend the block in `create()` that already sets the deferred case:

```python
    # A deferred screening is an unresolved decision, so it enters the operator's
    # approval queue. In semi-auto a *passing* one does too: the operator, not
    # the agent, decides whether to apply. Set here rather than accepted from
    # `fields`: the agent's record_screening reaches this function directly, and
    # approval is not its to grant.
    if screening.verdict == "deferred":
        screening.approval = "pending"
    elif screening.verdict == "passed" and _agent_config_load().mode == "semi":
        screening.approval = "pending"
```

Import at the top of `screening/store.py`, beside the existing `from truth.store import data_dir`:

```python
from agentconfig.store import load as _agent_config_load
```

Check for an import cycle before running: `agentconfig/store.py` must not import `screening.store`. Verify with `grep -n "^from\|^import" agentconfig/store.py`. It imports only `truth.store` and stdlib, so this direction is safe.

- [ ] **Step 4: Verify**

Run: `cd /home/glenn/Documents/truthcv && DATA_DIR=$(mktemp -d) python3 -m pytest tests/test_screening_mode_queueing.py -v`
Expected: PASS, 6 tests.

Run: `cd /home/glenn/Documents/truthcv && DATA_DIR=$(mktemp -d) python3 -m pytest`
Expected: PASS, whole suite. `tests/test_screening_approval_store.py` and `tests/test_approvals_api.py` both exercise `create()` and must be unaffected — the default mode is `full`.

- [ ] **Step 5: Commit**

```bash
git add screening/model.py screening/store.py tests/test_screening_mode_queueing.py
git commit -m "feat(screening): queue passing postings in semi-auto; store posting text and date"
```

---

### Task 4: The cover-letter draft store

**Files:**
- Create: `coverletter/store.py`
- Test: `tests/test_cover_letter_store.py` (create)

**Interfaces:**
- Consumes: `truth.store.data_dir`.
- Produces:
  - `CoverLetterDraft` dataclass: `text: str`, `paragraphs: list[dict]`, `source: str` (`"generated" | "operator"`), `updated_at: str`; `from_dict`/`to_dict`.
  - `letters_dir() -> Path`, `draft_path(screening_id: str) -> Path`
  - `load(screening_id: str) -> CoverLetterDraft | None`
  - `save(screening_id: str, draft: CoverLetterDraft) -> CoverLetterDraft`
  - `delete(screening_id: str) -> bool`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cover_letter_store.py`:

```python
"""Per-screening cover letter drafts.

One file per screening rather than a field on the screening record: the letter
is rewritten repeatedly and is orders of magnitude larger than the record, and
screenings.json is loaded in full on every screening read.
"""

from __future__ import annotations

import coverletter.store as letters


def _draft(text="Dear hiring team,", source="generated"):
    return letters.CoverLetterDraft(
        text=text, paragraphs=[{"text": text, "claims": []}], source=source
    )


def test_load_missing_returns_none(data_dir):
    assert letters.load("nope") is None


def test_save_and_load_round_trip(data_dir):
    saved = letters.save("s1", _draft())
    assert saved.updated_at
    loaded = letters.load("s1")
    assert loaded.text == "Dear hiring team,"
    assert loaded.source == "generated"
    assert loaded.paragraphs == [{"text": "Dear hiring team,", "claims": []}]


def test_operator_save_overwrites_a_generated_draft(data_dir):
    letters.save("s1", _draft())
    letters.save("s1", _draft(text="My own words.", source="operator"))
    loaded = letters.load("s1")
    assert loaded.text == "My own words."
    assert loaded.source == "operator"


def test_corrupt_file_loads_as_none(data_dir):
    letters.save("s1", _draft())
    letters.draft_path("s1").write_text("{ not json", encoding="utf-8")
    assert letters.load("s1") is None


def test_unknown_source_falls_back_to_generated(data_dir):
    """A wrong-typed field must not make text look operator-authored when it
    is not: `source` is the audit trail for what the guardrail vouched for."""
    letters.save("s1", _draft())
    letters.draft_path("s1").write_text('{"text": "x", "source": 7}', encoding="utf-8")
    assert letters.load("s1").source == "generated"


def test_delete(data_dir):
    letters.save("s1", _draft())
    assert letters.delete("s1") is True
    assert letters.load("s1") is None
    assert letters.delete("s1") is False


def test_screening_id_cannot_escape_the_letters_dir(data_dir):
    """Ids come from the store, but the id also arrives in a URL path."""
    import pytest

    with pytest.raises(ValueError):
        letters.draft_path("../../etc/passwd")
```

- [ ] **Step 2: Run and watch it fail**

Run: `cd /home/glenn/Documents/truthcv && DATA_DIR=$(mktemp -d) python3 -m pytest tests/test_cover_letter_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'coverletter.store'`.

- [ ] **Step 3: Implement**

Create `coverletter/store.py`:

```python
"""Per-screening cover letter drafts on the data volume.

One JSON file per screening under data/letters/. Kept out of screenings.json
because the letter is rewritten repeatedly and dwarfs the record it belongs to,
and that file is loaded in full on every screening read.

`source` is the audit trail: "generated" means the text is exactly what
generate_cover_letter produced and the guardrail validated, "operator" means a
human rewrote it and the guardrail no longer vouches for it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from truth.store import data_dir

SOURCES = ("generated", "operator")


@dataclass
class CoverLetterDraft:
    """One screening's current letter."""

    text: str = ""
    paragraphs: list[dict] = field(default_factory=list)
    source: str = "generated"
    updated_at: str = ""

    @classmethod
    def from_dict(cls, raw: dict) -> "CoverLetterDraft":
        kwargs = {}
        if "text" in raw and isinstance(raw["text"], str):
            kwargs["text"] = raw["text"]
        if "paragraphs" in raw and isinstance(raw["paragraphs"], list):
            kwargs["paragraphs"] = [p for p in raw["paragraphs"] if isinstance(p, dict)]
        # A wrong-typed source must not read as operator-authored: that would
        # claim a human vouched for text the guardrail wrote.
        if "source" in raw and raw["source"] in SOURCES:
            kwargs["source"] = raw["source"]
        if "updated_at" in raw and isinstance(raw["updated_at"], str):
            kwargs["updated_at"] = raw["updated_at"]
        return cls(**kwargs)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "paragraphs": self.paragraphs,
            "source": self.source,
            "updated_at": self.updated_at,
        }


def letters_dir() -> Path:
    """The directory holding one draft per screening."""
    return data_dir() / "letters"


def draft_path(screening_id: str) -> Path:
    """Path to one screening's draft.

    The id reaches this function from a URL path segment, so it is validated
    rather than trusted: anything with a separator or a parent reference could
    otherwise read or write outside the volume.
    """
    if not screening_id or "/" in screening_id or "\\" in screening_id or screening_id.startswith("."):
        raise ValueError(f"Unsafe screening id '{screening_id}'.")
    return letters_dir() / f"{screening_id}.json"


def load(screening_id: str) -> CoverLetterDraft | None:
    """The stored draft, or None when there is none or the file is unreadable."""
    try:
        p = draft_path(screening_id)
    except ValueError:
        return None
    if not p.exists():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(raw, dict):
        return None
    return CoverLetterDraft.from_dict(raw)


def save(screening_id: str, draft: CoverLetterDraft) -> CoverLetterDraft:
    """Persist a draft atomically, stamping updated_at."""
    p = draft_path(screening_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    draft.updated_at = datetime.now(timezone.utc).isoformat()
    tmp = p.with_suffix(".json.tmp")
    try:
        tmp.write_text(
            json.dumps(draft.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        tmp.replace(p)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise
    return draft


def delete(screening_id: str) -> bool:
    """Remove a draft. True if it existed."""
    try:
        p = draft_path(screening_id)
    except ValueError:
        return False
    if not p.exists():
        return False
    p.unlink()
    return True
```

- [ ] **Step 4: Verify**

Run: `cd /home/glenn/Documents/truthcv && DATA_DIR=$(mktemp -d) python3 -m pytest tests/test_cover_letter_store.py -v`
Expected: PASS, 7 tests.

Run: `cd /home/glenn/Documents/truthcv && DATA_DIR=$(mktemp -d) python3 -m pytest`
Expected: PASS, whole suite.

- [ ] **Step 5: Commit**

```bash
git add coverletter/store.py tests/test_cover_letter_store.py
git commit -m "feat(coverletter): per-screening draft store"
```

---

### Task 5: The three letter routes

**Files:**
- Modify: `api/routes.py` (add three routes after the existing `PATCH /screenings/{screening_id}`)
- Modify: `api/schemas.py` (add two models beside `ApprovalUpdate`)
- Test: `tests/test_letter_routes.py` (create)

**Interfaces:**
- Consumes: `coverletter.store` from Task 4; `Screening.posting_text` from Task 3; `agenttools.tools_letter.generate_cover_letter`.
- Produces:
  - `GET /api/screenings/{id}/letter` → `CoverLetterDraftModel`, 404 when no draft
  - `POST /api/screenings/{id}/letter` → `CoverLetterDraftModel`, body `LetterGenerateRequest`, 404 unknown screening, 409 empty `posting_text`, 409 over an operator draft without `force`, 422 when generation is blocked
  - `PUT /api/screenings/{id}/letter` → `CoverLetterDraftModel`, body `LetterSaveRequest`, 404 unknown screening
  - `CoverLetterDraftModel`: `text`, `paragraphs`, `source`, `updated_at`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_letter_routes.py`:

```python
"""The operator's on-demand cover letter: generate, read, edit, save.

Generation is guardrailed exactly as the agent's is. Saving an edit is NOT: the
operator is the source of the truth document, so a claim they type is one they
are asserting on their own behalf. That asymmetry is the point of these routes
and is asserted below.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import coverletter.store as letters
import screening.store as store
from api.main import app


@pytest.fixture()
def client(data_dir):
    return TestClient(app)


def _queued(posting_text="Staff AI Engineer, Germany (Remote). Python, LLMs."):
    return store.create(
        {
            "company": "Grafana Labs",
            "role": "Staff AI Engineer",
            "verdict": "deferred",
            "posting_text": posting_text,
        }
    )


class _StubProvider:
    """Returns one paragraph whose every content token is a stopword, so the
    guardrail has nothing to block. Keeps these tests off the network."""

    def extract_json(self, system, messages, schema=None):
        return {"paragraphs": [{"text": "It is the work that was created.", "claims": []}]}


@pytest.fixture()
def stub_provider(monkeypatch):
    import agenttools.tools_letter as tools_letter

    monkeypatch.setattr(tools_letter, "get_provider", lambda _name: _StubProvider())
    return _StubProvider()


def test_get_letter_404_when_none(client):
    s = _queued()
    assert client.get(f"/api/screenings/{s.id}/letter").status_code == 404


def test_generate_writes_a_generated_draft(client, stub_provider):
    s = _queued()
    r = client.post(f"/api/screenings/{s.id}/letter", json={})
    assert r.status_code == 200
    assert r.json()["source"] == "generated"
    assert r.json()["text"]
    assert letters.load(s.id).source == "generated"


def test_generate_404_on_unknown_screening(client, stub_provider):
    assert client.post("/api/screenings/nope/letter", json={}).status_code == 404


def test_generate_409_without_posting_text(client, stub_provider):
    """Every imported screening is in this state — there is nothing to draft
    from, and the UI must say so rather than offer a button that cannot work."""
    s = _queued(posting_text="")
    r = client.post(f"/api/screenings/{s.id}/letter", json={})
    assert r.status_code == 409
    assert "posting" in r.json()["detail"].lower()


def test_save_stores_operator_text_verbatim(client):
    s = _queued()
    r = client.put(
        f"/api/screenings/{s.id}/letter",
        json={"text": "I personally shipped the thing, unverifiably."},
    )
    assert r.status_code == 200
    assert r.json()["source"] == "operator"
    assert r.json()["text"] == "I personally shipped the thing, unverifiably."
    assert client.get(f"/api/screenings/{s.id}/letter").json()["text"] == (
        "I personally shipped the thing, unverifiably."
    )


def test_save_404_on_unknown_screening(client):
    assert client.put("/api/screenings/nope/letter", json={"text": "x"}).status_code == 404


def test_regenerate_refuses_over_an_operator_draft(client, stub_provider):
    s = _queued()
    client.put(f"/api/screenings/{s.id}/letter", json={"text": "Mine."})
    r = client.post(f"/api/screenings/{s.id}/letter", json={})
    assert r.status_code == 409
    assert letters.load(s.id).text == "Mine."


def test_regenerate_with_force_replaces_an_operator_draft(client, stub_provider):
    s = _queued()
    client.put(f"/api/screenings/{s.id}/letter", json={"text": "Mine."})
    r = client.post(f"/api/screenings/{s.id}/letter", json={"force": True})
    assert r.status_code == 200
    assert r.json()["source"] == "generated"
    assert letters.load(s.id).text != "Mine."


def test_blocked_generation_writes_nothing_and_names_the_claims(client, monkeypatch):
    """The guardrail still binds on generation. A blocked letter must not be
    stored: a draft on disk is what unlocks Approve, so storing a blocked one
    would let an ungrounded claim through the one gate that catches it."""
    import agenttools.tools_letter as tools_letter

    class _Overclaiming:
        def extract_json(self, system, messages, schema=None):
            return {
                "paragraphs": [
                    {
                        "text": "I personally invented Kubernetes at Grafana Labs.",
                        "claims": ["invented Kubernetes"],
                    }
                ]
            }

    monkeypatch.setattr(tools_letter, "get_provider", lambda _name: _Overclaiming())
    s = _queued()
    r = client.post(f"/api/screenings/{s.id}/letter", json={})
    assert r.status_code == 422
    assert letters.load(s.id) is None


def test_letter_routes_are_outside_the_agent_prefix(client):
    """The agent authenticates only against /api/agent/*. Nothing it can reach
    may write a letter the operator is meant to own."""
    for path in app.openapi()["paths"]:
        assert not (path.startswith("/api/agent/") and path.endswith("/letter"))
```

- [ ] **Step 2: Run and watch them fail**

Run: `cd /home/glenn/Documents/truthcv && DATA_DIR=$(mktemp -d) python3 -m pytest tests/test_letter_routes.py -v`
Expected: FAIL — 404 from FastAPI for every route (they do not exist).

- [ ] **Step 3: Implement the schemas**

In `api/schemas.py`, after `ApprovalUpdate`:

```python
class CoverLetterDraftModel(_Camel):
    """A screening's current cover letter draft.

    `source` says whether the guardrail vouches for this text: "generated" is
    exactly what generate_cover_letter produced and validated, "operator" is
    text a human wrote, which is saved verbatim and never validated.
    """

    text: str = ""
    paragraphs: list[dict] = Field(default_factory=list)
    source: str = "generated"
    updated_at: str = ""


class LetterGenerateRequest(_Camel):
    """POST /screenings/{id}/letter: draft from the stored posting text.

    `force` is the operator's explicit "discard my edits and redraft"; without
    it, regenerating over text a human wrote is refused.
    """

    force: bool = False
    tone: str = "Professional"
    length: str = "Standard"


class LetterSaveRequest(_Camel):
    """PUT /screenings/{id}/letter: the operator's own text, saved verbatim."""

    text: str
```

- [ ] **Step 4: Implement the routes**

In `api/routes.py`, add beside the other screening imports:

```python
import coverletter.store as letter_store
from agenttools.tools_letter import generate_cover_letter as _generate_letter
```

and add the schema names to the existing `from api.schemas import (...)` block: `CoverLetterDraftModel`, `LetterGenerateRequest`, `LetterSaveRequest`.

Add these three routes immediately after `set_screening_approval` and **before** `delete_screening`:

```python
def _draft_model(draft: letter_store.CoverLetterDraft) -> CoverLetterDraftModel:
    return CoverLetterDraftModel.model_validate(draft.to_dict())


@router.get("/screenings/{screening_id}/letter", response_model=CoverLetterDraftModel)
def get_screening_letter(screening_id: str) -> CoverLetterDraftModel:
    """The screening's current draft."""
    draft = letter_store.load(screening_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="No cover letter drafted yet.")
    return _draft_model(draft)


@router.post("/screenings/{screening_id}/letter", response_model=CoverLetterDraftModel)
def generate_screening_letter(
    screening_id: str, body: LetterGenerateRequest
) -> CoverLetterDraftModel:
    """Draft the letter for one screening, on the operator's request.

    Guardrailed exactly as the agent's own generation is — this is the same
    function the agent calls. A blocked generation writes nothing and reports
    the claims that blocked it, so the operator can fix the truth document
    rather than discovering the block at approval time.
    """
    screening = screening_store.get(screening_id)
    if screening is None:
        raise HTTPException(status_code=404, detail="Screening not found.")
    if not screening.posting_text.strip():
        raise HTTPException(
            status_code=409,
            detail="No posting text stored for this screening, so there is nothing to draft from.",
        )
    existing = letter_store.load(screening_id)
    if existing is not None and existing.source == "operator" and not body.force:
        raise HTTPException(
            status_code=409,
            detail="This letter was edited by you. Redrafting would discard those edits.",
        )
    result = _generate_letter(
        posting=screening.posting_text,
        tone=body.tone,
        length=body.length,
        company=screening.company or None,
    )
    if result["blocked"]:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "The letter was blocked by the truthfulness guardrail.",
                "blockedReason": result.get("blocked_reason", ""),
                "blockedClaims": result["blocked_claims"],
            },
        )
    draft = letter_store.CoverLetterDraft(
        text=result["text"], paragraphs=result["paragraphs"], source="generated"
    )
    return _draft_model(letter_store.save(screening_id, draft))


@router.put("/screenings/{screening_id}/letter", response_model=CoverLetterDraftModel)
def save_screening_letter(
    screening_id: str, body: LetterSaveRequest
) -> CoverLetterDraftModel:
    """Save the operator's own text, verbatim and unvalidated.

    The one path in the system where text reaches an employer without passing
    guardrail/validate.py, and deliberately so: the guardrail exists to stop the
    AGENT asserting facts it cannot ground in the operator's truth document. The
    operator is the source of that document. `source` records that a human wrote
    this, and the agent applies with it unchanged.
    """
    if screening_store.get(screening_id) is None:
        raise HTTPException(status_code=404, detail="Screening not found.")
    existing = letter_store.load(screening_id)
    draft = letter_store.CoverLetterDraft(
        text=body.text,
        paragraphs=existing.paragraphs if existing else [],
        source="operator",
    )
    return _draft_model(letter_store.save(screening_id, draft))
```

Route-order note: `/screenings/{screening_id}/letter` cannot be shadowed by `/screenings/{screening_id}` — the paths differ in segment count — but it must still be declared before `delete_screening` for readability of the block.

- [ ] **Step 5: Verify**

Run: `cd /home/glenn/Documents/truthcv && DATA_DIR=$(mktemp -d) python3 -m pytest tests/test_letter_routes.py -v`
Expected: PASS, 9 tests. If the stub provider is reached differently than expected, read `agenttools/tools_letter.py` — it calls `get_provider("cover_letter")` at module scope of the function, which is what the fixture patches.

Run: `cd /home/glenn/Documents/truthcv && DATA_DIR=$(mktemp -d) python3 -m pytest`
Expected: PASS, whole suite.

- [ ] **Step 6: Commit**

```bash
git add api/routes.py api/schemas.py tests/test_letter_routes.py
git commit -m "feat(api): generate, read and save a screening's cover letter"
```

---

### Task 6: Approval requires a draft; the agent applies with it

**Files:**
- Modify: `api/routes.py` (`set_screening_approval`, `bulk_set_approval`)
- Modify: `agenttools/tools_ledger.py:152-195` (`get_approved_applications`)
- Test: `tests/test_approvals_api.py` (append), `tests/test_approved_queue_tools.py` (append)

**Interfaces:**
- Consumes: `coverletter.store.load` from Task 4.
- Produces: 409 on approving a draftless screening; `cover_letter` and `letter_source` keys on each `get_approved_applications` item.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_approvals_api.py`:

```python
def test_approving_without_a_letter_is_refused(client):
    """The agent applies with the stored letter verbatim, so approving with no
    letter would queue an application with nothing to send."""
    s = _deferred()
    r = client.patch(f"/api/screenings/{s.id}", json={"approval": "approved"})
    assert r.status_code == 409
    assert store.get(s.id).approval == "pending"


def test_approving_with_a_letter_succeeds(client):
    import coverletter.store as letters

    s = _deferred()
    letters.save(s.id, letters.CoverLetterDraft(text="Dear team,", source="operator"))
    r = client.patch(f"/api/screenings/{s.id}", json={"approval": "approved"})
    assert r.status_code == 200
    assert store.get(s.id).approval == "approved"


def test_rejecting_never_needs_a_letter(client):
    s = _deferred()
    assert client.patch(f"/api/screenings/{s.id}", json={"approval": "rejected"}).status_code == 200


def test_bulk_approve_reports_a_draftless_item_instead_of_approving_it(client):
    import coverletter.store as letters

    a, b = _deferred("Grafana Labs"), _deferred("n8n")
    letters.save(a.id, letters.CoverLetterDraft(text="Dear team,"))
    body = client.patch(
        "/api/screenings/approvals", json={"ids": [a.id, b.id], "approval": "approved"}
    ).json()
    assert {r["id"]: r["ok"] for r in body["results"]} == {a.id: True, b.id: False}
    assert store.get(b.id).approval == "pending"
```

Append to `tests/test_approved_queue_tools.py`:

```python
def test_approved_item_carries_the_stored_letter(data_dir):
    """The agent applies with the operator's text verbatim; regenerating would
    discard the edit, which is the whole point of semi-auto."""
    import coverletter.store as letters

    s = _approved()
    letters.save(s.id, letters.CoverLetterDraft(text="My own words.", source="operator"))
    item = get_approved_applications()[0]
    assert item["cover_letter"] == "My own words."
    assert item["letter_source"] == "operator"


def test_approved_item_without_a_letter_reports_empty(data_dir):
    s = _approved()
    item = get_approved_applications()[0]
    assert item["cover_letter"] == ""
    assert item["letter_source"] == ""
```

- [ ] **Step 2: Run and watch them fail**

Run: `cd /home/glenn/Documents/truthcv && DATA_DIR=$(mktemp -d) python3 -m pytest tests/test_approvals_api.py tests/test_approved_queue_tools.py -v`
Expected: FAIL — approval succeeds where a 409 is expected; `KeyError: 'cover_letter'`.

- [ ] **Step 3: Implement the approval guard**

In `api/routes.py`, add a helper above `bulk_set_approval`:

```python
def _has_draft(screening_id: str) -> bool:
    """Whether a letter exists to apply with.

    Approval licenses the agent to submit on the operator's behalf using the
    stored text verbatim. Approving with no text queues an application with
    nothing to send, so the check lives here rather than only in the UI.
    """
    draft = letter_store.load(screening_id)
    return draft is not None and bool(draft.text.strip())
```

In `set_screening_approval`, before the `set_approval` call:

```python
    if body.approval == "approved" and not _has_draft(screening_id):
        raise HTTPException(
            status_code=409,
            detail="Draft a cover letter before approving — the agent applies with it verbatim.",
        )
```

In `bulk_set_approval`, replace the comprehension body so a draftless item is reported rather than approved:

```python
        results = []
        for sid in body.ids:
            if body.approval == "approved" and not _has_draft(sid):
                results.append({"id": sid, "ok": False})
                continue
            results.append(
                {"id": sid, "ok": screening_store.set_approval(sid, body.approval) is not None}
            )
```

- [ ] **Step 4: Implement the letter hand-off**

In `agenttools/tools_ledger.py`, import the store beside the others:

```python
import coverletter.store as _letter_store
```

In `get_approved_applications`, inside the loop, after the `blocked_reason` block, and add the two keys to the appended dict:

```python
        draft = _letter_store.load(s.id)
```

```python
                "cover_letter": draft.text if draft else "",
                "letter_source": draft.source if draft else "",
```

Extend the docstring's guard list:

```
    - The operator's stored letter travels with the item. The agent applies with
      that text verbatim and does not regenerate: regenerating would discard the
      operator's edit, which is the whole point of semi-auto.
```

- [ ] **Step 5: Verify**

Run: `cd /home/glenn/Documents/truthcv && DATA_DIR=$(mktemp -d) python3 -m pytest tests/test_approvals_api.py tests/test_approved_queue_tools.py -v`
Expected: PASS.

Run: `cd /home/glenn/Documents/truthcv && DATA_DIR=$(mktemp -d) python3 -m pytest`
Expected: PASS, whole suite.

- [ ] **Step 6: Commit**

```bash
git add api/routes.py agenttools/tools_ledger.py tests/test_approvals_api.py tests/test_approved_queue_tools.py
git commit -m "feat(approvals): require a drafted letter to approve; hand it to the agent"
```

---

### Task 7: The run script reads the mode

**Files:**
- Modify: `agent/agent-config.js:8` (the allowed-field list), `:47-56` (the field dispatch)
- Modify: `agent/daily-apply.sh:136-144` (the enable gate), and the prompt-assembly block around `:216-245`
- Modify: `agent/test-prompt-render.sh` (append cases)

**Interfaces:**
- Consumes: `mode` on `GET /api/agent/config` from Task 2.
- Produces: `node agent-config.js mode` printing `off|semi|full`; `daily-apply.sh` exiting 0 on `off` and rendering a mode rule into the prompt otherwise.

- [ ] **Step 1: Add the field to agent-config.js**

In `agent/agent-config.js`, add `"mode"` to the allowed-field list on line 8:

```js
if (!base || !["enabled", "mode", "run_at", "run_days", "llm_credentials", "job_config"].includes(field)) process.exit(1);
```

and add the dispatch beside the `enabled` branch:

```js
      if (field === "mode") {
        if (typeof cfg.mode !== "string") { process.exit(1); return; }
        process.stdout.write(cfg.mode);
      }
      else if (field === "enabled") {
```

- [ ] **Step 2: Replace the enable gate in daily-apply.sh**

Replace the `--- Agent enable gate ---` block (currently reading `enabled`) with:

```bash
# --- Agent mode gate ----------------------------------------------------------
# The Agents page sets the agent's autonomy mode; the flag lives in the app
# service's agent config (GET /api/agent/config). Unreachable config fails
# CLOSED: if the app is down, the MCP tools this run depends on are down too,
# and "did not run" is the safe failure for an unattended submitter.
#
#   off  - exit before the model is invoked at all
#   semi - discover and screen, queue what passes for the operator, apply only
#          to what the operator already approved
#   full - discover, screen and apply, the pre-mode behaviour
AGENT_MODE="$(node "${AGENT_CONFIG_JS:-/app/agent/agent-config.js}" mode)" || AGENT_MODE=""
if [[ "$AGENT_MODE" == "off" ]]; then
  log "agent mode is off - skipping run"
  exit 0
elif [[ "$AGENT_MODE" != "semi" && "$AGENT_MODE" != "full" ]]; then
  abort "agent config unreachable or mode unrecognised ('$AGENT_MODE') - skipping run (fail closed)"
fi
log "agent mode: $AGENT_MODE"
```

- [ ] **Step 3: Render the mode rule into the prompt**

In `daily-apply.sh`, immediately after the `PROMPT="$(cat "$PROMPT_FILE")"...` line, add:

```bash
# The mode changes what the agent does with a posting that passes every
# criterion, so it is rendered into the prompt rather than left implicit. The
# queueing itself is enforced server-side in screening.store.create - this text
# tells the agent what to expect, it is not what makes it true.
if [[ "$AGENT_MODE" == "semi" ]]; then
  PROMPT="$PROMPT"$'\n\n'"## Autonomy mode: SEMI-AUTO

Do NOT apply to a posting you find this run, however well it scores, and do not
write a cover letter for it. For a posting that passes every criterion, call
record_screening with verdict \"passed\", the full posting text in posting_text,
and the employer's publication date in posted_date when the board states one.
It enters the operator's approval queue; they draft the letter and decide.

Phase 0 is unchanged: postings the operator already approved ARE applied to,
using the cover_letter text that arrives with each item, verbatim."
else
  PROMPT="$PROMPT"$'\n\n'"## Autonomy mode: FULL AUTO

A posting that passes every criterion is applied to this run, as described in
agent/RUNBOOK.md. Record the full posting text in posting_text and the
employer's publication date in posted_date on every record_screening call."
fi
```

- [ ] **Step 4: Extend the render test**

In `agent/test-prompt-render.sh`, following the existing `render_cap` simulation pattern, add a `render_mode` function that reproduces the block above verbatim, and three cases: `semi` renders "SEMI-AUTO" and the "Do NOT apply" line; `full` renders "FULL AUTO"; and the two never both appear.

- [ ] **Step 5: Verify**

Run: `cd /home/glenn/Documents/truthcv && bash -n agent/daily-apply.sh && bash -n agent/smoke-test.sh && node --check agent/agent-config.js && echo SYNTAX_OK`
Expected: `SYNTAX_OK`.

Run: `cd /home/glenn/Documents/truthcv && agent/test-prompt-render.sh`
Expected: all cases pass, including the pre-existing ones.

Run: `cd /home/glenn/Documents/truthcv && grep -n "enabled" agent/daily-apply.sh`
Expected: no remaining gate on `enabled` — only comments, if any.

- [ ] **Step 6: Commit**

```bash
git add agent/agent-config.js agent/daily-apply.sh agent/test-prompt-render.sh
git commit -m "feat(agent): gate and prompt the run on the autonomy mode"
```

---

### Task 8: Agent instructions for semi-auto

**Files:**
- Modify: `agent/prompt.md` (the tool list and a new mode section)
- Modify: `agent/RUNBOOK.md` (§0 and the screening section)

**Interfaces:**
- Consumes: the mode block rendered by Task 7; the `cover_letter` item key from Task 6.
- Produces: no code interface. Documentation the agent reads at run time.

- [ ] **Step 1: Update prompt.md**

In the Phase 0 section, add to the bullet list:

```markdown
- Each entry carries `cover_letter`, the text the operator approved. Submit it
  verbatim. Do not regenerate it, do not edit it, and do not call
  `generate_cover_letter` for an approved entry — the operator may have written
  that text themselves, and rewriting it discards their decision.
- An entry whose `cover_letter` is empty must not be applied to. Report it.
```

In the `record_screening` tool description, add:

```markdown
  Always pass `posting_text` (the posting as you read it) and, when the board
  states one, `posted_date`. The operator drafts the cover letter from that
  stored text, days later, on a page you never see — and several of these
  boards cannot be re-fetched at all.
```

Add a short section after "The approve/deny boundary":

```markdown
## Autonomy mode

The run's mode is stated at the end of this prompt. In SEMI-AUTO you never
apply to a posting you found this run and never write a letter for it; you
record it and the operator decides. In FULL AUTO you apply as the runbook
describes. Phase 0 — the already-approved queue — runs identically in both.
```

- [ ] **Step 2: Update RUNBOOK.md §0**

Add to the approved-queue section:

```markdown
Each item carries the cover letter the operator approved, in `cover_letter`.
That text is submitted verbatim. It may have been written or edited by the
operator, in which case it did not pass the guardrail and does not need to —
they are the source of the truth document. Regenerating it would discard their
work, so do not.
```

- [ ] **Step 3: Verify**

Run: `cd /home/glenn/Documents/truthcv && grep -n "cover_letter\|posting_text\|SEMI-AUTO\|semi-auto" agent/prompt.md agent/RUNBOOK.md`
Expected: the new text appears in both files.

Run: `cd /home/glenn/Documents/truthcv && DATA_DIR=$(mktemp -d) python3 -m pytest`
Expected: PASS. (No code changed; this catches any test that asserts on the prompt text.)

- [ ] **Step 4: Commit**

```bash
git add agent/prompt.md agent/RUNBOOK.md
git commit -m "docs(agent): semi-auto rules and verbatim letter submission"
```

---

### Task 9: The mode slider on the Agents page

**Files:**
- Modify: `web/src/api/types.ts` (the `AgentConfig` type)
- Modify: `web/src/agents/AgentsPage.tsx:343-388` (`EnabledSection`)
- Modify: `web/src/agents/AgentsPage.cv.test.tsx`, `AgentsPage.model.test.tsx`, `AgentsPage.profiles.test.tsx` — each defines its own `makeConfig` fixture, and all three need `mode: "full"` added or they stop type-checking
- Test: `web/src/agents/AgentsPage.mode.test.tsx` (create)

**Interfaces:**
- Consumes: `mode` on the config wire model from Task 2.
- Produces: `AgentConfig.mode: "off" | "semi" | "full"` in the TS types; a three-stop slider writing it.

- [ ] **Step 1: Write the failing tests**

Create `web/src/agents/AgentsPage.mode.test.tsx`. The mock list, `makeConfig`, `makeAnswers`, `makeAgentStatus`, `makeRouting` and the `renderLoaded` helper are copied from `AgentsPage.model.test.tsx` — that file is the pattern for driving this page, and each Agents test file already carries its own copies rather than sharing them.

```tsx
// @vitest-environment jsdom
/** The autonomy slider: off / semi-auto / full auto. Stubbing follows
 * AgentsPage.model.test.tsx — mock the API client module, render with jsdom. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  getAgentConfig,
  getAgentStatus,
  getProfileAnswers,
  getRouting,
  listConnectionModels,
  listConnections,
  updateAgentConfig,
} from "../api/client";
import type { AgentConfig } from "../api/types";
import { AgentsPage } from "./AgentsPage";

vi.mock("../api/client", () => ({
  getAgentConfig: vi.fn(),
  getAgentStatus: vi.fn(),
  getProfileAnswers: vi.fn(),
  getRouting: vi.fn(),
  listConnections: vi.fn(),
  listConnectionModels: vi.fn(),
  triggerAgentRun: vi.fn(),
  updateAgentConfig: vi.fn(),
  saveProfileAnswers: vi.fn(),
  updateRouting: vi.fn(),
}));

function makeConfig(overrides: Partial<AgentConfig> = {}): AgentConfig {
  return {
    mode: "full",
    enabled: true,
    blockedCompanies: [],
    runAt: ["09:00"],
    runDays: ["mon"],
    profiles: [],
    targetCompanies: [],
    cooldownDays: null,
    maxApplicationsPerRun: null,
    companyBoards: [],
    ...overrides,
  };
}

/** Copy makeAnswers / makeAgentStatus / makeRouting verbatim from
 * AgentsPage.model.test.tsx — they are long, unchanged, and already correct. */

async function renderWithMode(mode: AgentConfig["mode"]) {
  vi.mocked(getAgentConfig).mockResolvedValue(makeConfig({ mode, enabled: mode !== "off" }));
  vi.mocked(getAgentStatus).mockResolvedValue(makeAgentStatus());
  vi.mocked(getProfileAnswers).mockResolvedValue(makeAnswers());
  vi.mocked(getRouting).mockResolvedValue(makeRouting());
  vi.mocked(listConnections).mockResolvedValue({ connections: [] } as never);
  vi.mocked(listConnectionModels).mockResolvedValue([]);
  render(<AgentsPage onBack={vi.fn()} />);
  await screen.findByRole("slider", { name: "Agent autonomy" });
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AgentsPage autonomy slider", () => {
  it("sits at the stored mode and explains it", async () => {
    await renderWithMode("semi");
    expect(screen.getByRole("slider", { name: "Agent autonomy" }).getAttribute("value")).toBe("1");
    expect(screen.getByText(/You draft the cover letter and approve/)).toBeTruthy();
  });

  it("moving it writes the new mode", async () => {
    await renderWithMode("semi");
    vi.mocked(updateAgentConfig).mockResolvedValue(makeConfig({ mode: "full" }));
    fireEvent.change(screen.getByRole("slider", { name: "Agent autonomy" }), {
      target: { value: "2" },
    });
    await waitFor(() => expect(updateAgentConfig).toHaveBeenCalledWith({ mode: "full" }));
  });

  it("off is reachable and explains that nothing is submitted", async () => {
    await renderWithMode("full");
    vi.mocked(updateAgentConfig).mockResolvedValue(makeConfig({ mode: "off", enabled: false }));
    fireEvent.change(screen.getByRole("slider", { name: "Agent autonomy" }), {
      target: { value: "0" },
    });
    await waitFor(() => expect(updateAgentConfig).toHaveBeenCalledWith({ mode: "off" }));
    expect(await screen.findByText(/Nothing is submitted/)).toBeTruthy();
  });

  it("reverts to the previous mode when the save fails", async () => {
    await renderWithMode("semi");
    vi.mocked(updateAgentConfig).mockRejectedValue(new Error("nope"));
    fireEvent.change(screen.getByRole("slider", { name: "Agent autonomy" }), {
      target: { value: "2" },
    });
    expect(await screen.findByText("nope")).toBeTruthy();
    await waitFor(() =>
      expect(screen.getByRole("slider", { name: "Agent autonomy" }).getAttribute("value")).toBe("1"),
    );
  });
});
```

MUI's `Slider` renders a hidden `<input type="range">` carrying the `slider` role and the `aria-label`, which is why `fireEvent.change` on it works and why the component below must set `aria-label="Agent autonomy"`.

- [ ] **Step 2: Run and watch them fail**

Run: `cd /home/glenn/Documents/truthcv/web && npm test -- AgentsPage`
Expected: FAIL — no slider in the DOM.

- [ ] **Step 3: Update the TS type**

In `web/src/api/types.ts`, in the `AgentConfig` interface, add beside `enabled`:

```ts
  /** Autonomy: "off" runs nothing, "semi" queues what passes for approval,
   * "full" applies on its own. `enabled` is derived from this server-side and
   * is read-only. */
  mode: "off" | "semi" | "full";
```

Leave `enabled` in place: `RunNowSection` reads it.

- [ ] **Step 4: Replace the switch with a slider**

Rename `EnabledSection` to `ModeSection` (update its call site in the page body) and replace its body:

```tsx
const MODES = ["off", "semi", "full"] as const;
type Mode = (typeof MODES)[number];

const MODE_HELP: Record<Mode, string> = {
  off: "Scheduled runs wake, log that the agent is off, and exit. Nothing is submitted.",
  semi: "The agent finds and screens roles, then waits. You draft the cover letter and approve; approved roles are applied to on the next scheduled run.",
  full: "The agent finds, screens, writes the letter and applies on its own. Roles it cannot decide alone still wait for you.",
};

function ModeSection({
  config,
  onChange,
}: {
  config: AgentConfig;
  onChange: (updater: (prev: AgentConfig) => AgentConfig) => void;
}) {
  const [error, setError] = useState<string | null>(null);

  async function handleMode(mode: Mode) {
    const previous = config.mode;
    setError(null);
    onChange((prev) => ({ ...prev, mode }));
    try {
      const fresh = await updateAgentConfig({ mode });
      onChange((prev) => ({ ...prev, mode: fresh.mode, enabled: fresh.enabled }));
    } catch (e) {
      onChange((prev) => ({ ...prev, mode: previous }));
      setError(e instanceof Error ? e.message : "Couldn't update the agent.");
    }
  }

  const index = Math.max(0, MODES.indexOf(config.mode));

  return (
    <Section title="Agent">
      <Slider
        value={index}
        min={0}
        max={2}
        step={null}
        marks={[
          { value: 0, label: "Off" },
          { value: 1, label: "Semi-auto" },
          { value: 2, label: "Full auto" },
        ]}
        onChange={(_e, v) => handleMode(MODES[v as number])}
        sx={{ maxWidth: 360, ml: 1 }}
        aria-label="Agent autonomy"
      />
      <Typography variant="body2" color="text.secondary">
        {MODE_HELP[config.mode]}
      </Typography>
      {error && <Alert severity="error">{error}</Alert>}
    </Section>
  );
}
```

Add `import Slider from "@mui/material/Slider";` and drop the now-unused `Switch` and `FormControlLabel` imports **only if nothing else in the file uses them** — check with `grep -n "Switch\|FormControlLabel" web/src/agents/AgentsPage.tsx` before removing.

The optimistic-update comment above the old component explains why `onChange` takes an updater rather than a snapshot; keep it, adjusted to say `mode` instead of `enabled`.

- [ ] **Step 5: Verify**

Run: `cd /home/glenn/Documents/truthcv/web && npm run typecheck && npm test && npm run build`
Expected: all three exit 0.

- [ ] **Step 6: Commit**

```bash
git add web/src/api/types.ts web/src/agents/AgentsPage.tsx web/src/agents/AgentsPage.test.tsx
git commit -m "feat(web): three-stop autonomy slider on the Agents page"
```

---

### Task 10: Letter drafting and editing on the Approvals page

**Files:**
- Modify: `web/src/api/client.ts` (three functions), `web/src/api/types.ts` (`CoverLetterDraft`, `ScreeningRecord` fields)
- Modify: `web/src/approvals/ApprovalsPage.tsx` (`PendingCard`)
- Test: `web/src/api/approvals.client.test.ts`, `web/src/approvals/ApprovalsPage.test.tsx`

**Interfaces:**
- Consumes: the three letter routes from Task 5; the 409 from Task 6.
- Produces: `getScreeningLetter(id)`, `generateScreeningLetter(id, force?)`, `saveScreeningLetter(id, text)`; `CoverLetterDraft` type; `postingText`/`postedDate` on `ScreeningRecord`.

- [ ] **Step 1: Write the failing client tests**

Append to `web/src/api/approvals.client.test.ts`, mirroring the existing cases exactly:

```ts
  it("generateScreeningLetter POSTs JSON with the JSON content type", async () => {
    const fetchMock = stubFetch({ text: "Dear team,", source: "generated" });
    await generateScreeningLetter("s1");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/screenings/s1/letter");
    expect(init.method).toBe("POST");
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(init.body)).toEqual({ force: false });
  });

  it("saveScreeningLetter PUTs the text verbatim", async () => {
    const fetchMock = stubFetch({ text: "Mine.", source: "operator" });
    await saveScreeningLetter("s1", "Mine.");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/screenings/s1/letter");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body)).toEqual({ text: "Mine." });
  });
```

- [ ] **Step 2: Run and watch them fail**

Run: `cd /home/glenn/Documents/truthcv/web && npm test -- approvals.client`
Expected: FAIL — the functions are not exported.

- [ ] **Step 3: Implement the client functions**

In `web/src/api/types.ts`:

```ts
/** A screening's current cover letter. `source` says whether the guardrail
 * vouches for the text: "generated" is what the model wrote and the guardrail
 * validated, "operator" is text you wrote, saved verbatim and unvalidated. */
export interface CoverLetterDraft {
  text: string;
  paragraphs: Record<string, unknown>[];
  source: "generated" | "operator";
  updatedAt: string;
}
```

and add to `ScreeningRecord`: `postingText: string;` and `postedDate: string;`.

In `web/src/api/client.ts`, beside `setScreeningUrl`:

```ts
/** The stored draft, or null when none has been generated yet. */
export async function getScreeningLetter(id: string): Promise<CoverLetterDraft | null> {
  try {
    return await request<CoverLetterDraft>("/api/screenings/" + encodeURIComponent(id) + "/letter");
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}

/** Draft the letter from the stored posting text. `force` discards an edit of
 * yours; without it the server refuses to overwrite your own words. */
export function generateScreeningLetter(id: string, force = false): Promise<CoverLetterDraft> {
  return request("/api/screenings/" + encodeURIComponent(id) + "/letter", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ force }),
  });
}

/** Save your own text. It is stored verbatim and never validated. */
export function saveScreeningLetter(id: string, text: string): Promise<CoverLetterDraft> {
  return request("/api/screenings/" + encodeURIComponent(id) + "/letter", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
}
```

Read `web/src/api/client.ts`'s `request` helper and its error type first: if it does not throw a typed error carrying `status`, do not invent `ApiError` — instead have `getScreeningLetter` catch broadly and return `null` only when the message contains the 404 detail string, and say so in a comment. Check `web/src/api/errorDetail.test.ts` for the shape the repo already relies on.

- [ ] **Step 4: Write the failing page test, then build the card**

In `web/src/approvals/ApprovalsPage.test.tsx`, add the three new client functions to the `vi.mock("../api/client", ...)` factory, add `postingText: "Staff AI Engineer, Germany (Remote)."` and `postedDate: "2026-08-20"` to `makeRecord`, make `renderPage` stub `getScreeningLetter` (default `null`), and append:

```tsx
describe("ApprovalsPage cover letter", () => {
  it("offers Generate when there is no draft, and blocks Approve until there is one", async () => {
    vi.mocked(getScreeningLetter).mockResolvedValue(null);
    await renderPage([makeRecord()]);
    expect(await screen.findByRole("button", { name: /Generate cover letter/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Approve" }).hasAttribute("disabled")).toBe(true);
    expect(screen.getByRole("button", { name: "Reject" }).hasAttribute("disabled")).toBe(false);
  });

  it("generating shows the text and unblocks Approve", async () => {
    vi.mocked(getScreeningLetter).mockResolvedValue(null);
    vi.mocked(generateScreeningLetter).mockResolvedValue({
      text: "Dear hiring team,",
      paragraphs: [],
      source: "generated",
      updatedAt: "2026-08-24T10:00:00Z",
    });
    await renderPage([makeRecord()]);
    fireEvent.click(await screen.findByRole("button", { name: /Generate cover letter/ }));
    await waitFor(() => expect(generateScreeningLetter).toHaveBeenCalledWith("s1"));
    expect(await screen.findByDisplayValue("Dear hiring team,")).toBeTruthy();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Approve" }).hasAttribute("disabled")).toBe(false),
    );
  });

  it("saving an edit sends the text verbatim and marks it as yours", async () => {
    vi.mocked(getScreeningLetter).mockResolvedValue({
      text: "Dear hiring team,",
      paragraphs: [],
      source: "generated",
      updatedAt: "2026-08-24T10:00:00Z",
    });
    vi.mocked(saveScreeningLetter).mockResolvedValue({
      text: "My own words.",
      paragraphs: [],
      source: "operator",
      updatedAt: "2026-08-24T10:05:00Z",
    });
    await renderPage([makeRecord()]);
    const field = await screen.findByDisplayValue("Dear hiring team,");
    fireEvent.change(field, { target: { value: "My own words." } });
    fireEvent.click(screen.getByRole("button", { name: "Save letter" }));
    await waitFor(() => expect(saveScreeningLetter).toHaveBeenCalledWith("s1", "My own words."));
    expect(await screen.findByText(/not checked/)).toBeTruthy();
  });

  it("says why Generate is unavailable when no posting text was captured", async () => {
    vi.mocked(getScreeningLetter).mockResolvedValue(null);
    await renderPage([makeRecord({ postingText: "" })]);
    const button = await screen.findByRole("button", { name: /Generate cover letter/ });
    expect(button.hasAttribute("disabled")).toBe(true);
    expect(screen.getByText(/No posting text/)).toBeTruthy();
  });

  it("shows the posted and found dates", async () => {
    vi.mocked(getScreeningLetter).mockResolvedValue(null);
    await renderPage([makeRecord()]);
    expect(await screen.findByText(/Posted 2026-08-20/)).toBeTruthy();
    expect(screen.getByText(/Found 2026-08-23/)).toBeTruthy();
  });
});
```

Then extend `PendingCard` in `web/src/approvals/ApprovalsPage.tsx`:

- On mount, `getScreeningLetter(record.id)` into local state (the list endpoint does not carry drafts).
- No draft → a **Generate cover letter** button, disabled while busy or when `!record.postingText`, with the reason shown when the posting text is missing.
- Draft present → a multiline `TextField` seeded from `draft.text`, a **Save** button, and a caption reading "As generated — checked against your CV" or "Edited by you — saved as written, not checked" from `draft.source`.
- **Approve** disabled with `title="Draft a cover letter first"` until a draft exists. **Reject** always enabled.
- Show `postedDate` ("Posted") and `screenedDate` ("Found") beside the company, each omitted when empty, and the posting text in a `<details>`-style collapsible using MUI `Accordion` or a plain toggle — follow whatever collapsible pattern the repo already has; if none, a `Button` toggling a `Collapse`.

- [ ] **Step 5: Verify**

Run: `cd /home/glenn/Documents/truthcv/web && npm run typecheck && npm test && npm run build`
Expected: all three exit 0.

- [ ] **Step 6: Commit**

```bash
git add web/src/api/client.ts web/src/api/types.ts web/src/approvals/ApprovalsPage.tsx web/src/api/approvals.client.test.ts web/src/approvals/ApprovalsPage.test.tsx
git commit -m "feat(web): draft, edit and save a posting's cover letter before approving"
```

---

### Task 11: The did-not-pass and rejected lists

**Files:**
- Modify: `web/src/api/client.ts` (two list functions)
- Modify: `web/src/approvals/ApprovalsPage.tsx` (two new sections)
- Test: `web/src/approvals/ApprovalsPage.test.tsx`

**Interfaces:**
- Consumes: `GET /api/screenings?approval=` and the full list route, both existing; `setScreeningApproval` from the existing client.
- Produces: `listRejectedApprovals()`, `listDidNotPass()`; a `moveToApprovals(id)` handler.

- [ ] **Step 1: Write the failing test**

Add `listRejectedApprovals` and `listDidNotPass` to the `vi.mock("../api/client", ...)` factory and to `renderPage`'s stubs (both defaulting to `[]`), then append to `web/src/approvals/ApprovalsPage.test.tsx`:

```tsx
describe("ApprovalsPage reviewable lists", () => {
  it("lists what the agent rejected on a criterion, apart from what you rejected", async () => {
    vi.mocked(listDidNotPass).mockResolvedValue([
      makeRecord({ id: "d1", company: "SumUp", verdict: "rejected", approval: "", failingCriterion: "remote" }),
    ]);
    vi.mocked(listRejectedApprovals).mockResolvedValue([
      makeRecord({ id: "r1", company: "Pleo", approval: "rejected" }),
    ]);
    await renderPage([]);
    expect(await screen.findByRole("heading", { name: "Did not pass" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Rejected" })).toBeTruthy();
    expect(screen.getByText("SumUp")).toBeTruthy();
    expect(screen.getByText("Pleo")).toBeTruthy();
  });

  it("moving one back queues it and takes it out of the list it came from", async () => {
    vi.mocked(listRejectedApprovals).mockResolvedValue([
      makeRecord({ id: "r1", company: "Pleo", approval: "rejected" }),
    ]);
    vi.mocked(setScreeningApproval).mockResolvedValue(
      makeRecord({ id: "r1", company: "Pleo", approval: "pending" }),
    );
    await renderPage([]);
    fireEvent.click(await screen.findByRole("button", { name: "Move to approvals" }));
    await waitFor(() => expect(setScreeningApproval).toHaveBeenCalledWith("r1", "pending"));
    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: "Move to approvals" }).length).toBe(0),
    );
  });
});
```

`getAllByRole` is used for the disappearance assertion because `getByRole` throws when the element is absent, which is the state being asserted; `getAllByRole` returns an empty array instead. If the repo's testing-library version throws there too, use `queryAllByRole`.

- [ ] **Step 2: Run and watch it fail**

Run: `cd /home/glenn/Documents/truthcv/web && npm test -- ApprovalsPage`
Expected: FAIL — neither section exists.

- [ ] **Step 3: Implement the client functions**

In `web/src/api/client.ts`, beside `listPendingApprovals`:

```ts
/** Postings you rejected. Kept listed so a decision can be reversed. */
export function listRejectedApprovals(): Promise<ScreeningRecord[]> {
  return request("/api/screenings?approval=rejected");
}

/** Postings the agent rejected on a criterion — never queued, and reviewable
 * so a filter you disagree with does not silently lose a role. */
export async function listDidNotPass(): Promise<ScreeningRecord[]> {
  const all = await request<ScreeningRecord[]>("/api/screenings");
  return all.filter((s) => s.verdict === "rejected" && !s.approval);
}
```

The filter is client-side because `GET /api/screenings?approval=` filters on approval, and an agent-rejected record's approval is the empty string — which the existing route treats as "no filter" when omitted and as a literal match when sent. Verify that behaviour in `api/routes.py:list_screenings` before relying on it; if `?approval=` with an empty value works as a literal match, use it and drop the client-side filter.

- [ ] **Step 4: Add the two sections**

In `ApprovalsPage`, load both lists alongside the existing two, and render two more sections below "Approved, not yet applied", each row showing company, role, failing criterion, reason, and a **Move to approvals** button calling:

```tsx
  async function moveToApprovals(id: string) {
    setBusy(true);
    setError("");
    try {
      const updated = await setScreeningApproval(id, "pending");
      setRejected((rows) => rows.filter((r) => r.id !== id));
      setDidNotPass((rows) => rows.filter((r) => r.id !== id));
      setPending((rows) => [updated, ...rows]);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
```

Keep the two lists as separate sections: they differ in volume and meaning — the agent rejects nine postings in a run on hard criteria, an operator rejection is a decision worth finding again — and merging them buries the small list in the large one.

- [ ] **Step 5: Verify**

Run: `cd /home/glenn/Documents/truthcv/web && npm run typecheck && npm test && npm run build`
Expected: all three exit 0.

- [ ] **Step 6: Commit**

```bash
git add web/src/api/client.ts web/src/approvals/ApprovalsPage.tsx web/src/approvals/ApprovalsPage.test.tsx
git commit -m "feat(web): did-not-pass and rejected lists, with move back to approvals"
```

---

### Task 12: End-to-end check against the running stack

**Files:** none modified. This task is verification only.

- [ ] **Step 1: Rebuild and restart**

```bash
cd /home/glenn/Documents/truthcv && docker compose build app agent && docker compose up -d app agent
```

- [ ] **Step 2: Confirm the config round-trips**

```bash
docker exec truthcv-app-1 python3 -c "
import urllib.request, json
print(json.loads(urllib.request.urlopen('http://localhost:8080/api/agent/config').read())['mode'])
"
```
Expected: `full` — the migration from the existing `enabled: true`.

- [ ] **Step 3: Confirm the agent reads it**

```bash
docker exec truthcv-agent-1 node /app/agent/agent-config.js mode
```
Expected: `full`.

- [ ] **Step 4: Confirm the queue hands over letters**

```bash
docker exec truthcv-app-1 python3 -c "
import urllib.request, json
req=urllib.request.Request('http://localhost:8080/mcp',
  data=json.dumps({'jsonrpc':'2.0','id':1,'method':'tools/call',
                   'params':{'name':'get_approved_applications','arguments':{}}}).encode(),
  headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream'})
print(urllib.request.urlopen(req).read().decode()[:800])
"
```
Expected: each item carries `cover_letter` and `letter_source` keys.

- [ ] **Step 5: Report**

Write down what was checked and what was not. In particular: no scheduled run is exercised by this task, so semi-auto's effect on a real run is **unverified** until one happens. Say so rather than implying otherwise.

---

## Notes for the executor

- **Tasks 1-3 are a chain.** Task 1 may leave `tests/test_agent_config_api.py` red until Task 2 lands; that is expected and called out in Task 1's Step 4.
- **Tasks 9-11 all touch `ApprovalsPage.tsx`.** Run them in order, in one worktree, not in parallel.
- **The stub provider in Task 5** keeps the letter tests off the network. If a later task needs a letter in a test, reuse that fixture rather than calling a real provider.
- **If a test you did not write fails**, read it before changing it. Two of them (`test_no_agent_route_writes_approval`, and the cooldown tests) encode invariants this plan must not break.
