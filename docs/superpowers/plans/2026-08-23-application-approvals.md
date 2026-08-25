# Application Approvals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the operator approve postings the agent deferred, so the agent applies to them on the next scheduled run.

**Architecture:** Approval state rides on the existing `Screening` record, written only by dedicated store functions the agent cannot reach. A new Approvals page lists pending items; a new Phase 0 in the agent run works the approved queue before discovery, with the double-submit and cooldown guards enforced server-side.

**Tech Stack:** Python 3.11 / FastAPI / dataclass stores over JSON files; React + TypeScript + MUI + Vitest; pytest.

**Spec:** `docs/superpowers/specs/2026-08-23-application-approvals-design.md`

## Global Constraints

- The three approval fields MUST NOT be added to `Screening.EDITABLE`. `EDITABLE` is what `store.create()`/`update()` copy from caller-supplied fields, and the agent's `record_screening(**fields)` calls `create()` directly. A field in `EDITABLE` is a field the agent can set.
- Approval-writing routes MUST live outside `/api/agent/*`. That prefix is where the agent's `X-Agent-Token` authenticates.
- `PATCH /api/screenings/approvals` MUST be declared before `PATCH /api/screenings/{id}`, or the router binds `approvals` as an id.
- Approval never overrides cooldown or `generate_cover_letter`'s truthfulness guardrail.
- Posting approval = apply, skip screening. Company approval = clears deferral blockers only; role still screened.
- Run tests with `python3 -m pytest` from the repo root. `tests/test_company_boards_store.py` has 5 pre-existing `PermissionError` failures (root-owned `data/`) — not yours, do not fix.
- Frontend commands run from `web/`: `npx vitest run`, `npx tsc -b`.

---

### Task 1: Approval fields on the Screening model

**Files:**
- Modify: `screening/model.py:13-44`
- Test: `tests/test_screening_approval_store.py` (create)

**Interfaces:**
- Produces: `Screening.approval: str`, `Screening.apply_attempts: int`, `Screening.apply_error: str`; constant `APPROVAL_VALUES = ("", "pending", "approved", "rejected", "applied")`

- [ ] **Step 1: Write the failing test**

```python
"""Approval state on the Screening record."""

from __future__ import annotations

from screening.model import APPROVAL_VALUES, Screening


def test_approval_fields_default_to_empty():
    s = Screening()
    assert s.approval == ""
    assert s.apply_attempts == 0
    assert s.apply_error == ""


def test_approval_fields_are_not_editable():
    """EDITABLE is what the agent's record_screening can set. If approval is in
    it, the agent can approve its own applications."""
    assert "approval" not in Screening.EDITABLE
    assert "apply_attempts" not in Screening.EDITABLE
    assert "apply_error" not in Screening.EDITABLE


def test_approval_values():
    assert APPROVAL_VALUES == ("", "pending", "approved", "rejected", "applied")


def test_round_trip_preserves_approval():
    s = Screening(id="x", approval="approved", apply_attempts=2, apply_error="boom")
    assert Screening.from_dict(s.to_dict()) == s
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_screening_approval_store.py -v`
Expected: FAIL — `ImportError: cannot import name 'APPROVAL_VALUES'`

- [ ] **Step 3: Write minimal implementation**

In `screening/model.py`, beside `VERDICT_VALUES`:

```python
APPROVAL_VALUES = ("", "pending", "approved", "rejected", "applied")
```

Add to the `Screening` dataclass, after `source: str = ""`:

```python
    # Approval state. Deliberately absent from EDITABLE: that tuple is what
    # store.create()/update() copy from caller-supplied fields, and the agent's
    # record_screening(**fields) reaches create() directly. Listing these there
    # would let the agent approve its own applications. They are written only by
    # set_approval / record_apply_failure / mark_applied.
    approval: str = ""
    apply_attempts: int = 0
    apply_error: str = ""
```

Leave `EDITABLE` unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_screening_approval_store.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add screening/model.py tests/test_screening_approval_store.py
git commit -m "feat(screening): approval state fields, kept out of EDITABLE"
```

---

### Task 2: Store functions that write approval state

**Files:**
- Modify: `screening/store.py:62-71` (`create`), append new functions after `delete`
- Test: `tests/test_screening_approval_store.py` (extend)

**Interfaces:**
- Consumes: `Screening.approval`, `APPROVAL_VALUES` (Task 1)
- Produces:
  - `set_approval(screening_id: str, approval: str) -> Screening | None`
  - `record_apply_failure(screening_id: str, error: str) -> Screening | None`
  - `mark_applied(screening_id: str) -> Screening | None`
  - `create()` sets `approval="pending"` when `verdict == "deferred"`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_screening_approval_store.py`:

```python
import pytest

import screening.store as store


def test_deferred_create_becomes_pending(data_dir):
    s = store.create({"company": "Contoso", "role": "Staff", "verdict": "deferred"})
    assert s.approval == "pending"


def test_rejected_create_is_not_an_approval_item(data_dir):
    s = store.create({"company": "Soylent", "role": "Staff", "verdict": "rejected"})
    assert s.approval == ""


def test_caller_cannot_set_approval_through_create(data_dir):
    """The agent's record_screening(**fields) lands here."""
    s = store.create({"company": "X", "verdict": "rejected", "approval": "approved"})
    assert s.approval == ""


def test_caller_cannot_set_approval_through_update(data_dir):
    s = store.create({"company": "X", "verdict": "deferred"})
    store.update(s.id, {"approval": "approved", "company": "Y"})
    reloaded = store.get(s.id)
    assert reloaded.approval == "pending"
    assert reloaded.company == "Y"


def test_set_approval(data_dir):
    s = store.create({"company": "Contoso", "verdict": "deferred"})
    updated = store.set_approval(s.id, "approved")
    assert updated.approval == "approved"
    assert store.get(s.id).approval == "approved"


def test_set_approval_unknown_id_returns_none(data_dir):
    assert store.set_approval("nope", "approved") is None


def test_set_approval_rejects_bad_value(data_dir):
    s = store.create({"company": "Contoso", "verdict": "deferred"})
    with pytest.raises(ValueError):
        store.set_approval(s.id, "yes-please")


def test_record_apply_failure_increments_and_keeps_approval(data_dir):
    s = store.create({"company": "Contoso", "verdict": "deferred"})
    store.set_approval(s.id, "approved")
    store.record_apply_failure(s.id, "browser died")
    store.record_apply_failure(s.id, "form 404")
    reloaded = store.get(s.id)
    assert reloaded.apply_attempts == 2
    assert reloaded.apply_error == "form 404"
    assert reloaded.approval == "approved"


def test_mark_applied(data_dir):
    s = store.create({"company": "Contoso", "verdict": "deferred"})
    store.set_approval(s.id, "approved")
    assert store.mark_applied(s.id).approval == "applied"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_screening_approval_store.py -v`
Expected: FAIL — `AttributeError: module 'screening.store' has no attribute 'set_approval'`

- [ ] **Step 3: Write minimal implementation**

In `screening/store.py`, add the import:

```python
from .model import APPROVAL_VALUES, Screening, new_id
```

In `create()`, after `_apply_editable(screening, fields)`:

```python
    # A deferred screening is an unresolved decision, so it enters the operator's
    # approval queue. Set here rather than accepted from `fields`: the agent's
    # record_screening reaches this function directly.
    if screening.verdict == "deferred":
        screening.approval = "pending"
```

Append after `delete()`:

```python
def set_approval(screening_id: str, approval: str) -> Screening | None:
    """Set a screening's approval state. The operator's decision, never the agent's.

    Raises ValueError on an unknown state rather than writing it.
    """
    if approval not in APPROVAL_VALUES:
        raise ValueError(f"Unknown approval state '{approval}'.")
    return _mutate(screening_id, lambda s: setattr(s, "approval", approval))


def record_apply_failure(screening_id: str, error: str) -> Screening | None:
    """Count one failed application attempt and keep its error for the operator.

    Leaves `approval` untouched: a failure is not a decision, and the item stays
    queued for the next run.
    """

    def _bump(s: Screening) -> None:
        s.apply_attempts += 1
        s.apply_error = error

    return _mutate(screening_id, _bump)


def mark_applied(screening_id: str) -> Screening | None:
    """Retire an approved item once its application is confirmed."""
    return _mutate(screening_id, lambda s: setattr(s, "approval", "applied"))


def _mutate(screening_id: str, apply) -> Screening | None:
    """Load, mutate one record outside EDITABLE, stamp, and write back."""
    screenings = load_all()
    screening = next((s for s in screenings if s.id == screening_id), None)
    if screening is None:
        return None
    apply(screening)
    screening.updated_at = _now()
    _write_all(screenings)
    return screening
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_screening_approval_store.py -v`
Expected: PASS (13 tests)

- [ ] **Step 5: Commit**

```bash
git add screening/store.py tests/test_screening_approval_store.py
git commit -m "feat(screening): store functions for approval state"
```

---

### Task 3: CompanyBoard approval that survives re-recording

**Files:**
- Modify: `companyboards/store.py:9-20` (dataclass), `companyboards/store.py:101-112` (`record`)
- Test: `tests/test_company_board_approval.py` (create)

**Interfaces:**
- Produces: `CompanyBoard.approved: bool`; `companyboards.store.set_approved(company: str, approved: bool) -> CompanyBoard | None`

- [ ] **Step 1: Write the failing test**

```python
"""Company-level approval on the board record.

The agent re-records a company board every run. If record() rebuilds the entry
from its arguments, that silently un-approves the company — the defect this
guards.
"""

from __future__ import annotations

import companyboards.store as boards


def test_approved_defaults_false(data_dir):
    boards.record("Contoso Labs", "https://contoso.example/careers")
    assert boards.load()["contoso labs"].approved is False


def test_set_approved(data_dir):
    boards.record("Contoso Labs", "https://contoso.example/careers")
    assert boards.set_approved("Contoso Labs", True).approved is True
    assert boards.load()["contoso labs"].approved is True


def test_set_approved_unknown_company(data_dir):
    assert boards.set_approved("Nobody", True) is None


def test_record_preserves_approval(data_dir):
    """The agent re-recording the board must not un-approve the company."""
    boards.record("Contoso Labs", "https://contoso.example/careers")
    boards.set_approved("Contoso Labs", True)
    boards.record("Contoso Labs", "https://contoso.example/jobs", ats="greenhouse")
    entry = boards.load()["contoso labs"]
    assert entry.approved is True
    assert entry.careers_url == "https://contoso.example/jobs"
    assert entry.ats == "greenhouse"


def test_record_round_trips_approved_through_disk(data_dir):
    boards.record("Contoso Labs", "https://contoso.example/careers")
    boards.set_approved("Contoso Labs", True)
    assert boards.load()["contoso labs"].approved is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_company_board_approval.py -v`
Expected: FAIL — `AttributeError: 'CompanyBoard' object has no attribute 'approved'`

- [ ] **Step 3: Write minimal implementation**

In `companyboards/store.py`, add to the `CompanyBoard` dataclass after `status: str = "ok"`:

```python
    # Operator-granted, company-level trust. Clears deferral blockers for any
    # role here; never bypasses per-role screening. record_company_board takes
    # no such argument, so the agent cannot set it.
    approved: bool = False
```

Add to `from_dict`, following the existing per-field pattern:

```python
        # approved: bool
        if "approved" in raw and isinstance(raw["approved"], bool):
            kwargs["approved"] = raw["approved"]
```

Replace `record()`:

```python
def record(company: str, careers_url: str, ats: str = "", status: str = "ok") -> None:
    """Record or update a company board entry.

    Merges onto any existing entry rather than replacing it: the agent
    re-records boards every run, and rebuilding the entry from these arguments
    would silently drop the operator's `approved` flag.
    """
    boards = load()
    normalized = _normalize_company(company)
    existing = boards.get(normalized)
    boards[normalized] = CompanyBoard(
        company=company,
        careers_url=careers_url,
        ats=ats,
        status=status,
        approved=existing.approved if existing else False,
    )
    save(boards)


def set_approved(company: str, approved: bool) -> CompanyBoard | None:
    """Grant or revoke company-level approval.

    Returns the updated entry so callers need not re-normalise the name to read
    it back; None when the company has no board.
    """
    boards = load()
    normalized = _normalize_company(company)
    if normalized not in boards:
        return None
    boards[normalized].approved = approved
    save(boards)
    return boards[normalized]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_company_board_approval.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add companyboards/store.py tests/test_company_board_approval.py
git commit -m "feat(companyboards): company-level approval that survives re-recording"
```

---

### Task 4: Approval API routes

**Files:**
- Modify: `api/schemas.py:571-586` (`ScreeningModel`), append two request models
- Modify: `api/routes.py:106-138` (`_screening_model`, `list_screenings`), add routes
- Test: `tests/test_approvals_api.py` (create)

**Interfaces:**
- Consumes: `set_approval`, `record_apply_failure` (Task 2); `set_approved` (Task 3)
- Produces: `GET /api/screenings?approval=`, `PATCH /api/screenings/approvals`, `PATCH /api/screenings/{id}`, `PATCH /api/company-boards/{company}`

- [ ] **Step 1: Write the failing test**

```python
"""Approval routes: the operator's surface, unreachable from the agent."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import companyboards.store as boards
import screening.store as store
from api.main import app


@pytest.fixture()
def client(data_dir):
    return TestClient(app)


def _deferred(company="Contoso Labs", role="Staff AI Engineer"):
    return store.create({"company": company, "role": role, "verdict": "deferred"})


def test_list_filters_by_approval(client):
    _deferred()
    store.create({"company": "Soylent", "verdict": "rejected"})
    rows = client.get("/api/screenings?approval=pending").json()
    assert [r["company"] for r in rows] == ["Contoso Labs"]


def test_list_unfiltered_returns_everything(client):
    _deferred()
    store.create({"company": "Soylent", "verdict": "rejected"})
    assert len(client.get("/api/screenings").json()) == 2


def test_wire_model_exposes_approval_fields(client):
    _deferred()
    row = client.get("/api/screenings").json()[0]
    assert row["approval"] == "pending"
    assert row["applyAttempts"] == 0
    assert row["applyError"] == ""


def test_patch_sets_approval(client):
    s = _deferred()
    body = client.patch(f"/api/screenings/{s.id}", json={"approval": "approved"}).json()
    assert body["approval"] == "approved"
    assert store.get(s.id).approval == "approved"


def test_patch_unknown_id_404(client):
    assert client.patch("/api/screenings/nope", json={"approval": "approved"}).status_code == 404


def test_patch_bad_value_422(client):
    s = _deferred()
    assert client.patch(f"/api/screenings/{s.id}", json={"approval": "sure"}).status_code == 422


def test_bulk_patch_reports_per_id(client):
    a, b = _deferred("Contoso Labs"), _deferred("Aperture")
    body = client.patch(
        "/api/screenings/approvals",
        json={"ids": [a.id, b.id, "missing"], "approval": "approved"},
    ).json()
    assert body["results"] == [
        {"id": a.id, "ok": True},
        {"id": b.id, "ok": True},
        {"id": "missing", "ok": False},
    ]
    assert store.get(a.id).approval == "approved"


def test_bulk_route_is_not_shadowed_by_the_id_route(client):
    """PATCH /screenings/approvals must not bind 'approvals' as an id."""
    resp = client.patch("/api/screenings/approvals", json={"ids": [], "approval": "approved"})
    assert resp.status_code == 200
    assert resp.json() == {"results": []}


def test_company_approval(client):
    boards.record("Contoso Labs", "https://contoso.example/careers")
    body = client.patch("/api/company-boards/Contoso Labs", json={"approved": True}).json()
    assert body["approved"] is True
    assert boards.load()["contoso labs"].approved is True


def test_company_approval_unknown_404(client):
    assert client.patch("/api/company-boards/Nobody", json={"approved": True}).status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_approvals_api.py -v`
Expected: FAIL — 405 Method Not Allowed on the PATCH routes

- [ ] **Step 3: Write minimal implementation**

In `api/schemas.py`, add to `ScreeningModel` after `source: str = ""`:

```python
    approval: str = ""
    apply_attempts: int = 0
    apply_error: str = ""
```

Append after `ScreeningCreate`:

```python
class ApprovalUpdate(_Camel):
    """PATCH /screenings/{id}: the operator's approval decision."""

    approval: str


class BulkApprovalUpdate(_Camel):
    """PATCH /screenings/approvals: one decision across many screenings."""

    ids: list[str] = []
    approval: str


class BulkApprovalResult(_Camel):
    """Per-id outcome, so a partial failure is visible rather than silent."""

    results: list[dict] = []


class CompanyApprovalUpdate(_Camel):
    """PATCH /company-boards/{company}: company-level trust."""

    approved: bool
```

In `api/routes.py`, import the new schemas alongside the existing ones and add
`import companyboards.store as companyboards_store`.

Replace `_screening_model`:

```python
def _screening_model(screening: Screening) -> ScreeningModel:
    """Map a stored Screening to its wire model.

    The approval fields sit outside EDITABLE (so the agent cannot set them), so
    they are mapped explicitly rather than picked up by the loop below.
    """
    data = {f: getattr(screening, f) for f in Screening.EDITABLE}
    return ScreeningModel(
        id=screening.id,
        created_at=screening.created_at,
        updated_at=screening.updated_at,
        approval=screening.approval,
        apply_attempts=screening.apply_attempts,
        apply_error=screening.apply_error,
        **data,
    )
```

Replace `list_screenings`:

```python
@router.get("/screenings", response_model=list[ScreeningModel])
def list_screenings(approval: str | None = None) -> list[ScreeningModel]:
    """Every screening record, most recent first; `approval` narrows to the queue."""
    screenings = sorted(
        screening_store.load_all(), key=lambda s: s.created_at, reverse=True
    )
    if approval is not None:
        screenings = [s for s in screenings if s.approval == approval]
    return [_screening_model(s) for s in screenings]
```

Add the routes. **The bulk route must be declared before `/screenings/{screening_id}`**:

```python
@router.patch("/screenings/approvals", response_model=BulkApprovalResult)
def bulk_set_approval(body: BulkApprovalUpdate) -> BulkApprovalResult:
    """Apply one approval decision to many screenings.

    Reports per-id outcomes rather than failing wholesale, so a partial failure
    is visible instead of silently dropping some ids.
    """
    try:
        results = [
            {"id": sid, "ok": screening_store.set_approval(sid, body.approval) is not None}
            for sid in body.ids
        ]
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return BulkApprovalResult(results=results)


@router.patch("/screenings/{screening_id}", response_model=ScreeningModel)
def set_screening_approval(screening_id: str, body: ApprovalUpdate) -> ScreeningModel:
    """The operator's approval decision for one screening."""
    try:
        screening = screening_store.set_approval(screening_id, body.approval)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    if screening is None:
        raise HTTPException(status_code=404, detail="Screening not found.")
    return _screening_model(screening)


@router.patch("/company-boards/{company}", response_model=CompanyBoardModel)
def set_company_approval(company: str, body: CompanyApprovalUpdate) -> CompanyBoardModel:
    """Grant or revoke company-level trust."""
    entry = companyboards_store.set_approved(company, body.approved)
    if entry is None:
        raise HTTPException(status_code=404, detail="Company board not found.")
    return CompanyBoardModel(
        company=entry.company,
        careers_url=entry.careers_url,
        ats=entry.ats,
        status=entry.status,
        approved=entry.approved,
    )
```

Add `CompanyBoardModel` to `api/schemas.py`:

```python
class CompanyBoardModel(_Camel):
    """A company's resolved careers board and the operator's trust in it."""

    company: str = ""
    careers_url: str = ""
    ats: str = ""
    status: str = ""
    approved: bool = False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_approvals_api.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add api/routes.py api/schemas.py tests/test_approvals_api.py
git commit -m "feat(api): approval routes for screenings and company boards"
```

---

### Task 5: The agent cannot reach the approval routes

**Files:**
- Test: `tests/test_approvals_api.py` (extend)

**Interfaces:**
- Consumes: the routes from Task 4

This task is a guard, not a feature: it pins the property the whole design rests on.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_approvals_api.py`:

```python
def test_agent_token_does_not_authorise_approval(client, monkeypatch):
    """The agent authenticates only against /api/agent/*. Its token must not be
    an approval credential anywhere else — the structural half of "the human
    approves, the agent never does"."""
    monkeypatch.setenv("AGENT_API_TOKEN", "shared-secret")
    s = _deferred()
    hdr = {"X-Agent-Token": "shared-secret"}

    # The route exists and ignores the header entirely — it is not an auth
    # surface. What must not exist is an /api/agent/* path that writes approval.
    agent_routes = [
        r.path for r in app.routes if getattr(r, "path", "").startswith("/api/agent")
    ]
    for path in agent_routes:
        assert "approval" not in path
        assert "approvals" not in path

    # And the agent's own tool surface exposes no approval writer.
    from agenttools.mcp_app import _TOOL_REGISTRY

    assert not any("approve" in name for name in _TOOL_REGISTRY)
    assert client.patch(f"/api/screenings/{s.id}", json={"approval": "approved"}, headers=hdr).status_code == 200
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `python3 -m pytest tests/test_approvals_api.py::test_agent_token_does_not_authorise_approval -v`
Expected: PASS immediately — the property already holds. If it FAILS, an approval writer leaked onto the agent surface; stop and report rather than weakening the test.

- [ ] **Step 3: Commit**

```bash
git add tests/test_approvals_api.py
git commit -m "test(api): pin that the agent surface cannot write approvals"
```

---

### Task 6: Agent tools for the approved queue

**Files:**
- Modify: `agenttools/tools_ledger.py` (add two functions, extend `record_application`)
- Modify: `agenttools/mcp_app.py:28-64` (`_TOOL_REGISTRY`)
- Modify: `tests/test_mcp_transport.py` (the nine-tool assertion)
- Test: `tests/test_approved_queue_tools.py` (create)

**Interfaces:**
- Consumes: `set_approval`, `record_apply_failure`, `mark_applied` (Task 2)
- Produces: `get_approved_applications() -> list[dict]`, `report_apply_failure(screening_id: str, error: str) -> dict`

- [ ] **Step 1: Write the failing test**

```python
"""The agent's read-only view of the approved queue, and its failure reporting.

Two hazards are guarded server-side rather than by prompt: an item already
applied to must not be handed back (the retry policy would double-submit), and
a company in cooldown must come back flagged rather than vanish, so the agent
reports why it did not go out.
"""

from __future__ import annotations

import applications.store as apps
import screening.store as store
from agenttools.tools_ledger import get_approved_applications, report_apply_failure


def _approved(company="Contoso Labs", url="https://contoso.example/jobs/1"):
    s = store.create({"company": company, "role": "Staff", "url": url, "verdict": "deferred"})
    store.set_approval(s.id, "approved")
    return s


def test_returns_approved_items(data_dir):
    s = _approved()
    items = get_approved_applications()
    assert [(i["screening_id"], i["company"], i["url"]) for i in items] == [
        (s.id, "Contoso Labs", "https://contoso.example/jobs/1")
    ]


def test_excludes_pending_and_rejected(data_dir):
    store.create({"company": "A", "verdict": "deferred"})
    r = store.create({"company": "B", "verdict": "deferred"})
    store.set_approval(r.id, "rejected")
    assert get_approved_applications() == []


def test_excludes_already_applied_url(data_dir):
    """Retry-forever would otherwise re-submit an application whose confirmation
    capture failed."""
    _approved(url="https://contoso.example/jobs/1")
    apps.create({"company": "Contoso Labs", "application_url": "https://contoso.example/jobs/1"})
    assert get_approved_applications() == []


def test_cooldown_company_is_flagged_not_hidden(data_dir):
    s = _approved(company="Aperture")
    apps.create({"company": "Aperture", "application_url": "https://aperture.example/other"})
    items = get_approved_applications()
    assert len(items) == 1
    assert items[0]["screening_id"] == s.id
    assert items[0]["blocked_reason"]


def test_report_apply_failure_counts_and_keeps_approval(data_dir):
    s = _approved()
    report_apply_failure(s.id, "browser died")
    reloaded = store.get(s.id)
    assert reloaded.apply_attempts == 1
    assert reloaded.apply_error == "browser died"
    assert reloaded.approval == "approved"


def test_report_apply_failure_unknown_id(data_dir):
    assert report_apply_failure("nope", "x")["ok"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_approved_queue_tools.py -v`
Expected: FAIL — `ImportError: cannot import name 'get_approved_applications'`

- [ ] **Step 3: Write minimal implementation**

In `agenttools/tools_ledger.py`, add near the other imports:

```python
import applications.store as _apps_store
import screening.store as _screening_store
from screening.cooldown import cooldown as _cooldown_for
```

Append:

```python
def get_approved_applications() -> list[dict]:
    """Postings the operator approved and this run should apply to.

    Two guards live here rather than in the prompt, because a wrong judgement by
    the model would be costly and silent:

    - An item whose URL already appears in the applications ledger is dropped.
      The retry policy keeps failed items queued forever, so a submission whose
      confirmation capture failed would otherwise be sent twice.
    - An item whose company is in cooldown comes back with `blocked_reason` set
      instead of being hidden, so the run report can say why it did not go out.
    """
    applied_urls = {a.application_url for a in _apps_store.load_all() if a.application_url}
    items = []
    for s in _screening_store.load_all():
        if s.approval != "approved":
            continue
        if s.url and s.url in applied_urls:
            continue
        status = _cooldown_for(s.company, s.role or None)
        items.append(
            {
                "screening_id": s.id,
                "company": s.company,
                "role": s.role,
                "url": s.url,
                "attempts": s.apply_attempts,
                "blocked_reason": "cooldown" if status.blocked else "",
            }
        )
    return items


def report_apply_failure(screening_id: str, error: str) -> dict:
    """Record why an approved application could not be completed this run.

    Leaves the item approved and queued: the operator chose retry-on-next-run,
    and this tool cannot change an approval either way.
    """
    updated = _screening_store.record_apply_failure(screening_id, error)
    if updated is None:
        return {"ok": False, "reason": "unknown screening id"}
    return {"ok": True, "attempts": updated.apply_attempts}
```

Extend `record_application` to retire the queue item. Immediately before its
`return`, add:

```python
    # An approved queue item retires on evidence of a confirmed application, not
    # on the agent electing to retire it.
    if screening_id:
        _screening_store.mark_applied(screening_id)
```

and take `screening_id` out of the `**fields` passthrough at the top of the
function:

```python
    fields = dict(fields)
    screening_id = fields.pop("screening_id", "")
```

In `agenttools/mcp_app.py`, import the two new functions alongside the existing
`tools_ledger` imports and register them:

```python
    "get_approved_applications": (
        _get_approved_applications,
        "Returns the postings the operator approved for this run to apply to. "
        "An entry with a non-empty blocked_reason must not be applied to; report it instead.",
    ),
    "report_apply_failure": (
        _report_apply_failure,
        "Records why an approved application could not be completed. The item stays queued for the next run.",
    ),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_approved_queue_tools.py -v`
Expected: PASS (6 tests)

Then update the tool-count assertion in `tests/test_mcp_transport.py`: rename
`test_mcp_tools_list_returns_nine_tools` to
`test_mcp_tools_list_returns_eleven_tools` and change its expected count from 9
to 11, including the two new names in any list it asserts.

Run: `python3 -m pytest tests/test_mcp_transport.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agenttools/tools_ledger.py agenttools/mcp_app.py tests/test_approved_queue_tools.py tests/test_mcp_transport.py
git commit -m "feat(agent): approved-queue tools with server-side double-submit and cooldown guards"
```

---

### Task 7: Prompt and runbook — separate the two approvals

**Files:**
- Modify: `agent/prompt.md:48-67`
- Modify: `agent/RUNBOOK.md:229-262`

**Interfaces:**
- Consumes: the tools from Task 6

No test: these are instructions to the model. The guarantee they describe is
enforced by Tasks 1, 4 and 5.

- [ ] **Step 1: Edit `agent/prompt.md`**

Replace the closing paragraph of "The approve/deny boundary" — the one beginning
"Never assert a fact the guardrail could not ground." — keeping its first two
sentences and replacing the final sentence about approval:

```markdown
Never assert a fact the guardrail could not ground. Never work around a
block by rewording a claim, typing it directly into a form field, or any
other route that bypasses `generate_cover_letter`'s validation.

**Two different things are called approval. Do not confuse them.**

*Claim approval* — approving an unverifiable fact — remains impossible for
you, mid-run or ever. No tool grants it. Never wait for, request, or
fabricate it.

*Application approval* — permission to apply to one posting — is a decision
the operator already made between runs. You read it with
`get_approved_applications` and act on it. You never grant it, and holding an
application approval never licenses a claim the guardrail rejects.
```

- [ ] **Step 2: Add Phase 0 to `agent/prompt.md`**

Before the section describing discovery, add:

```markdown
## Phase 0: the approved queue

Start every run by calling `get_approved_applications`. These postings the
operator already approved, so apply to them before spending time on discovery.

- Apply without re-screening: the operator's approval settles the judgement
  that deferred it.
- An entry with a non-empty `blocked_reason` must NOT be applied to. Report it
  in the run report and move on.
- The cover-letter guardrail still binds. An approval is not permission to
  assert an ungrounded claim.
- On success call `record_application` with that entry's `screening_id`.
- If you cannot complete one, call `report_apply_failure` with the reason. It
  stays queued for the next run.
```

- [ ] **Step 3: Mirror both edits into `agent/RUNBOOK.md` §6**

Apply the same two-kinds-of-approval distinction to §6, and add the Phase 0
description to the run-order section, in that document's voice.

- [ ] **Step 4: Verify the smoke test still passes**

Run: `docker compose run --rm --entrypoint /app/agent/smoke-test.sh agent`
Expected: all checks pass

- [ ] **Step 5: Commit**

```bash
git add agent/prompt.md agent/RUNBOOK.md
git commit -m "docs(agent): separate claim approval from application approval; add Phase 0"
```

---

### Task 8: API client and types

**Files:**
- Modify: `web/src/api/types.ts:311-325` (`ScreeningRecord`)
- Modify: `web/src/api/client.ts:276-285`
- Test: none (thin wrappers; covered through Task 9)

**Interfaces:**
- Produces: `setScreeningApproval(id, approval)`, `bulkSetApproval(ids, approval)`, `listPendingApprovals()`, `setCompanyApproval(company, approved)`

- [ ] **Step 1: Extend the type**

Add to `ScreeningRecord`, after `source: string;`:

```typescript
  /** "" when this record is not an approval item. */
  approval: "" | "pending" | "approved" | "rejected" | "applied";
  applyAttempts: number;
  applyError: string;
```

- [ ] **Step 2: Add the client functions**

Append after `deleteScreening`:

```typescript
/** The approval queue: screenings the agent deferred and is waiting on. */
export function listPendingApprovals(): Promise<ScreeningRecord[]> {
  return request("/api/screenings?approval=pending");
}

/** Approved-but-not-yet-applied items, kept visible so failures are noticed. */
export function listApprovedApplications(): Promise<ScreeningRecord[]> {
  return request("/api/screenings?approval=approved");
}

/** Record the operator's decision on one screening. */
export function setScreeningApproval(
  id: string,
  approval: "approved" | "rejected",
): Promise<ScreeningRecord> {
  return request("/api/screenings/" + encodeURIComponent(id), {
    method: "PATCH",
    body: JSON.stringify({ approval }),
  });
}

/** One decision across many screenings; the result reports each id separately. */
export function bulkSetApproval(
  ids: string[],
  approval: "approved" | "rejected",
): Promise<{ results: { id: string; ok: boolean }[] }> {
  return request("/api/screenings/approvals", {
    method: "PATCH",
    body: JSON.stringify({ ids, approval }),
  });
}

/** Company-level trust: clears deferral blockers, never skips role screening. */
export function setCompanyApproval(
  company: string,
  approved: boolean,
): Promise<{ company: string; approved: boolean }> {
  return request("/api/company-boards/" + encodeURIComponent(company), {
    method: "PATCH",
    body: JSON.stringify({ approved }),
  });
}
```

- [ ] **Step 3: Typecheck**

Run (from `web/`): `npx tsc -b --pretty false`
Expected: exit 0

- [ ] **Step 4: Commit**

```bash
git add web/src/api/client.ts web/src/api/types.ts
git commit -m "feat(web): approval API client functions"
```

---

### Task 9: Approvals page

**Files:**
- Create: `web/src/approvals/ApprovalsPage.tsx`
- Test: `web/src/approvals/ApprovalsPage.test.tsx` (create)

**Interfaces:**
- Consumes: Task 8's client functions
- Produces: `ApprovalsPage({ onBack }: { onBack: () => void })`

- [ ] **Step 1: Write the failing test**

```tsx
// @vitest-environment jsdom
/** Approvals page: the operator's queue. Stubbing follows ScreeningsPage.test.tsx. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  bulkSetApproval,
  listApprovedApplications,
  listPendingApprovals,
  setScreeningApproval,
} from "../api/client";
import type { ScreeningRecord } from "../api/types";
import { ApprovalsPage } from "./ApprovalsPage";

vi.mock("../api/client", () => ({
  listPendingApprovals: vi.fn(),
  listApprovedApplications: vi.fn(),
  setScreeningApproval: vi.fn(),
  bulkSetApproval: vi.fn(),
  setCompanyApproval: vi.fn(),
}));

afterEach(cleanup);

function makeRecord(overrides: Partial<ScreeningRecord> = {}): ScreeningRecord {
  return {
    id: "s1",
    company: "Contoso Labs",
    role: "Staff AI Engineer",
    url: "https://contoso.example/jobs/1",
    screenedDate: "2026-08-23",
    verdict: "deferred",
    failingCriterion: "entity",
    reason: "German hiring entity unverified",
    cooldownExpires: "",
    source: "agent",
    createdAt: "2026-08-23T19:00:00Z",
    updatedAt: "2026-08-23T19:00:00Z",
    approval: "pending",
    applyAttempts: 0,
    applyError: "",
    ...overrides,
  };
}

async function renderPage(pending: ScreeningRecord[], approved: ScreeningRecord[] = []) {
  vi.mocked(listPendingApprovals).mockResolvedValue(pending);
  vi.mocked(listApprovedApplications).mockResolvedValue(approved);
  render(<ApprovalsPage onBack={() => {}} />);
  await waitFor(() => expect(listPendingApprovals).toHaveBeenCalled());
}

describe("ApprovalsPage", () => {
  it("renders a pending item with the agent's deferral reason", async () => {
    await renderPage([makeRecord()]);
    expect(await screen.findByText("Contoso Labs")).toBeTruthy();
    expect(screen.getByText(/German hiring entity unverified/)).toBeTruthy();
  });

  it("shows the empty state when nothing is waiting", async () => {
    await renderPage([]);
    expect(await screen.findByText(/nothing waiting/i)).toBeTruthy();
  });

  it("approving calls through and removes the row", async () => {
    vi.mocked(setScreeningApproval).mockResolvedValue(makeRecord({ approval: "approved" }));
    await renderPage([makeRecord()]);
    fireEvent.click(await screen.findByRole("button", { name: /^approve$/i }));
    await waitFor(() => expect(setScreeningApproval).toHaveBeenCalledWith("s1", "approved"));
  });

  it("rejecting calls through", async () => {
    vi.mocked(setScreeningApproval).mockResolvedValue(makeRecord({ approval: "rejected" }));
    await renderPage([makeRecord()]);
    fireEvent.click(await screen.findByRole("button", { name: /^reject$/i }));
    await waitFor(() => expect(setScreeningApproval).toHaveBeenCalledWith("s1", "rejected"));
  });

  it("bulk approve sends every selected id", async () => {
    vi.mocked(bulkSetApproval).mockResolvedValue({ results: [] });
    await renderPage([makeRecord(), makeRecord({ id: "s2", company: "Aperture" })]);
    fireEvent.click(await screen.findByRole("checkbox", { name: /select all/i }));
    fireEvent.click(screen.getByRole("button", { name: /approve selected/i }));
    await waitFor(() =>
      expect(bulkSetApproval).toHaveBeenCalledWith(["s1", "s2"], "approved"),
    );
  });

  it("shows attempt count and last error for a failing approved item", async () => {
    await renderPage([], [makeRecord({ approval: "approved", applyAttempts: 3, applyError: "form 404" })]);
    expect(await screen.findByText(/form 404/)).toBeTruthy();
    expect(screen.getByText(/3 attempts/i)).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `web/`): `npx vitest run src/approvals/ApprovalsPage.test.tsx`
Expected: FAIL — cannot resolve `./ApprovalsPage`

- [ ] **Step 3: Implement the page**

Create `web/src/approvals/ApprovalsPage.tsx` following `ScreeningsPage.tsx`'s
structure and MUI usage. It must:

- Load both lists on mount (`listPendingApprovals`, `listApprovedApplications`).
- Render each pending item as a card: company, role, URL as a link,
  `failingCriterion` and `reason`, a row checkbox, and **Approve** / **Reject**
  buttons calling `setScreeningApproval` then dropping the row from local state.
- Render a "Select all" checkbox and an **Approve selected** button calling
  `bulkSetApproval` with the checked ids.
- Render the approved list below, each showing `applyAttempts` as
  "N attempts" and `applyError` when non-empty.
- Show "Nothing waiting." when both lists are empty.
- Offer an "Approve this company" control per card calling `setCompanyApproval`,
  labelled to say it clears deferral blockers only and does not skip screening.
- Take an `onBack` prop rendered as a back button, as the other pages do.

- [ ] **Step 4: Run tests to verify they pass**

Run (from `web/`): `npx vitest run src/approvals/ApprovalsPage.test.tsx`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add web/src/approvals/
git commit -m "feat(web): approvals page"
```

---

### Task 10: Navigation and pending badge

**Files:**
- Modify: `web/src/App.tsx:25` (`View`), `:100-142`
- Modify: `web/src/wizard/StepRail.tsx:19,27,43,47,118-127`
- Test: `web/src/wizard/StepRail.approvals.test.tsx` (create)

**Interfaces:**
- Consumes: `ApprovalsPage` (Task 9), `listPendingApprovals` (Task 8)

- [ ] **Step 1: Write the failing test**

```tsx
// @vitest-environment jsdom
/** The rail's Approvals entry and its pending badge. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { StepRail } from "./StepRail";

afterEach(cleanup);

const props = {
  current: "upload" as const,
  reached: "upload" as const,
  onNavigate: () => {},
  onOpenSettings: () => {},
  onOpenApplications: () => {},
  onOpenAnalytics: () => {},
  onOpenAgents: () => {},
  onOpenScreenings: () => {},
  onOpenApprovals: () => {},
};

describe("StepRail approvals entry", () => {
  it("renders an Approvals button", () => {
    render(<StepRail {...props} />);
    expect(screen.getByRole("button", { name: /approvals/i })).toBeTruthy();
  });

  it("shows the pending count when there is one", () => {
    render(<StepRail {...props} pendingApprovals={3} />);
    expect(screen.getByText("3")).toBeTruthy();
  });

  it("shows no badge at zero", () => {
    render(<StepRail {...props} pendingApprovals={0} />);
    expect(screen.queryByText("0")).toBeNull();
  });

  it("calls onOpenApprovals when clicked", () => {
    const onOpenApprovals = vi.fn();
    render(<StepRail {...props} onOpenApprovals={onOpenApprovals} />);
    screen.getByRole("button", { name: /approvals/i }).click();
    expect(onOpenApprovals).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `web/`): `npx vitest run src/wizard/StepRail.approvals.test.tsx`
Expected: FAIL — no Approvals button

- [ ] **Step 3: Implement**

In `StepRail.tsx`, add `onOpenApprovals: () => void;`, `approvalsActive?: boolean;`
and `pendingApprovals?: number;` to the props type and destructuring
(`approvalsActive = false`, `pendingApprovals = 0`), then add a button beside the
Screenings one, wrapping its icon in a MUI `Badge`:

```tsx
        <Button
          fullWidth
          variant={approvalsActive ? "contained" : "outlined"}
          startIcon={
            <Badge badgeContent={pendingApprovals} color="primary">
              <PlaylistAddCheckOutlinedIcon fontSize="small" />
            </Badge>
          }
          onClick={onOpenApprovals}
          aria-current={approvalsActive ? "page" : undefined}
          sx={{ justifyContent: "flex-start" }}
        >
          Approvals
        </Button>
```

Import `Badge` from `@mui/material/Badge` and
`PlaylistAddCheckOutlinedIcon` from `@mui/icons-material/PlaylistAddCheckOutlined`.
MUI's `Badge` renders nothing at 0 by default, which satisfies the zero case.

In `App.tsx`: add `"approvals"` to `View`; import `ApprovalsPage`; add
`onOpenApprovals={() => setView("approvals")}` and
`approvalsActive={view === "approvals"}` to `StepRail`; add the render branch
`view === "approvals" ? <ApprovalsPage onBack={() => setView("wizard")} /> :`
alongside the others; and hold `pendingApprovals` in state, refreshed by
`listPendingApprovals()` on mount and after returning from the Approvals page.

- [ ] **Step 4: Run the full frontend suite**

Run (from `web/`): `npx vitest run` then `npx tsc -b --pretty false`
Expected: all tests pass; tsc exit 0

- [ ] **Step 5: Commit**

```bash
git add web/src/App.tsx web/src/wizard/StepRail.tsx web/src/wizard/StepRail.approvals.test.tsx
git commit -m "feat(web): approvals navigation with pending badge"
```

---

### Task 11: End-to-end verification

**Files:** none — verification only.

- [ ] **Step 1: Full backend suite**

Run: `python3 -m pytest -q --ignore=tests/test_company_boards_store.py`
Expected: no FAILED or ERROR lines. (That file's 5 `PermissionError` failures are pre-existing and excluded.)

- [ ] **Step 2: Full frontend suite and typecheck**

Run (from `web/`): `npx vitest run && npx tsc -b --pretty false`
Expected: all pass, exit 0

- [ ] **Step 3: Rebuild and exercise the live stack**

```bash
docker compose build app && docker compose up -d app
curl -s "http://localhost:8080/api/screenings?approval=pending" | head -c 400
```

Expected: the three roles the 2026-08-23 19:09 run deferred appear as pending
items. If the list is empty, check whether those records predate Task 2's
`create()` change — they were written with `approval=""` and need
`set_approval(id, "pending")` once each.

- [ ] **Step 4: Confirm the agent sees an approved item**

```bash
docker compose exec -T app python -c "
import screening.store as s
from agenttools.tools_ledger import get_approved_applications
pending = [x for x in s.load_all() if x.approval == 'pending']
print('pending:', len(pending))
if pending:
    s.set_approval(pending[0].id, 'approved')
print('queue:', get_approved_applications())
"
```

Expected: the approved item appears with its `screening_id`, `url`, and an
empty `blocked_reason`.

- [ ] **Step 5: Agent smoke test**

Run: `docker compose run --rm --entrypoint /app/agent/smoke-test.sh agent`
Expected: all checks pass, including the MCP handshake listing eleven tools.

- [ ] **Step 6: Commit any fixes**

```bash
git add -A
git commit -m "test: end-to-end verification of the approvals flow"
```
