# Attended Browser Sign-in Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the operator open a browser they can drive, sign in to a job site at a time of their choosing, and have that session persist for every later unattended run.

**Architecture:** A control server inside the `browser` container owns an attended Chromium session, mirroring how `agent/supervisor.js` owns runs. The `app` service forwards session control to it and relays the noVNC WebSocket, so the viewport is reached through the app rather than a published port. The agent reports login walls through the existing `report_apply_failure` tool, and those reports become a per-host sign-in queue in the UI.

**Tech Stack:** Python 3.14 / FastAPI / uvicorn[standard] / pytest; Node 20 (plain `http` module, no framework) inside the browser container; React 18 / MUI / Vite / vitest; Docker Compose.

**Spec:** `docs/superpowers/specs/2026-08-25-attended-browser-signin-design.md`

## Global Constraints

- The agent **never creates an account** and never guesses credentials. Registration walls are reported, not passed.
- The agent's experience is the **only** source of truth for whether a site needs a sign-in. No probing, no operator-asserted "signed in" flags, no status ticks in the UI.
- Sign-in queue entries are deduplicated by **full host** (`acme.wd3.myworkdayjobs.com`), never by registrable domain (`myworkdayjobs.com`).
- Session-server port: **8932**, in-network only, never published.
- Session-server auth: the `X-Agent-Token` header carrying `AGENT_API_TOKEN`, matching `agent/supervisor.js`'s `tokenOk()`. An empty `AGENT_API_TOKEN` rejects every request.
- Eviction grace period: **3 minutes** (180 seconds).
- Unreachable dependencies **fail closed**: an unreachable supervisor refuses a session; an unreachable session server aborts a run.
- `apply_blocker` and `signin_url` must NOT be added to `Screening.EDITABLE` — that tuple is what the agent's `record_screening(**fields)` can set directly, and these fields are written only by `record_apply_failure`.
- Run all Python tests with `pytest` from the repo root. Run all web tests with `npm --prefix web run test`.
- Baseline at the start of this plan: 991 passed, 2 skipped (pytest); 221 passed across 30 files (vitest).

---

### Task 1: Screening fields for login walls

**Files:**
- Modify: `screening/model.py:68-69`
- Modify: `screening/store.py:161-173`
- Test: `tests/test_screening_login_blocker.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `Screening.apply_blocker: str` and `Screening.signin_url: str`; `screening.store.record_apply_failure(screening_id: str, error: str, blocker: str = "", signin_url: str = "") -> Screening | None`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_screening_login_blocker.py`:

```python
"""Screening records carry a structured login-wall blocker, not just free text."""

from __future__ import annotations

from screening import store
from screening.model import Screening


def test_new_screening_defaults_to_no_blocker(data_dir):
    s = store.create({"company": "Acme", "role": "Dev", "verdict": "passed"})
    assert s.apply_blocker == ""
    assert s.signin_url == ""


def test_record_apply_failure_stores_blocker_and_url(data_dir):
    s = store.create({"company": "Acme", "role": "Dev", "verdict": "passed"})
    updated = store.record_apply_failure(
        s.id,
        "sign-in required",
        blocker="login_required",
        signin_url="https://acme.wd3.myworkdayjobs.com/login",
    )
    assert updated is not None
    assert updated.apply_blocker == "login_required"
    assert updated.signin_url == "https://acme.wd3.myworkdayjobs.com/login"
    assert updated.apply_attempts == 1
    assert updated.apply_error == "sign-in required"


def test_record_apply_failure_without_blocker_leaves_fields_empty(data_dir):
    """The existing two-argument call must keep working unchanged."""
    s = store.create({"company": "Acme", "role": "Dev", "verdict": "passed"})
    updated = store.record_apply_failure(s.id, "form timed out")
    assert updated is not None
    assert updated.apply_blocker == ""
    assert updated.signin_url == ""


def test_blocker_fields_are_not_editable_by_the_agent():
    """record_screening(**fields) reaches store.create(); these must not be settable there."""
    assert "apply_blocker" not in Screening.EDITABLE
    assert "signin_url" not in Screening.EDITABLE


def test_records_persisted_before_these_fields_existed_still_load():
    """from_dict filters to known fields, so an old record loads with defaults."""
    old = {"id": "abc123", "company": "Acme", "role": "Dev", "verdict": "passed"}
    s = Screening.from_dict(old)
    assert s.apply_blocker == ""
    assert s.signin_url == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_screening_login_blocker.py -v`
Expected: FAIL with `AttributeError: 'Screening' object has no attribute 'apply_blocker'`

- [ ] **Step 3: Add the fields to the model**

In `screening/model.py`, the block at lines 68-69 currently reads:

```python
    approval: str = ""
    apply_attempts: int = 0
    apply_error: str = ""
    created_at: str = ""
```

Change it to:

```python
    approval: str = ""
    apply_attempts: int = 0
    apply_error: str = ""
    # Why the application could not be completed, when the reason is one the
    # app can act on rather than only display. Empty, or "login_required" when
    # the form sat behind a sign-in or registration wall. `apply_error` stays
    # the human-readable detail; this is what the sign-in queue filters on.
    apply_blocker: str = ""
    # The page the operator should sign in at, recorded alongside the blocker.
    signin_url: str = ""
    created_at: str = ""
```

Do NOT add either name to the `EDITABLE` tuple below it.

- [ ] **Step 4: Widen record_apply_failure**

In `screening/store.py`, replace lines 161-173:

```python
def record_apply_failure(screening_id: str, error: str) -> Screening | None:
    """Count one failed application attempt and keep its error for the operator.

    Leaves `approval` untouched: a failure is not a decision, and the item stays
    queued for the next run.
    """

    def _bump(s: Screening) -> None:
        s.apply_attempts += 1
        s.apply_error = error

    return _mutate(screening_id, _bump)
```

with:

```python
def record_apply_failure(
    screening_id: str,
    error: str,
    blocker: str = "",
    signin_url: str = "",
) -> Screening | None:
    """Count one failed application attempt and keep its error for the operator.

    Leaves `approval` untouched: a failure is not a decision, and the item stays
    queued for the next run.

    `blocker` is the structured reason when there is one the app can act on —
    only "login_required" today — and `signin_url` the page to sign in at. Both
    default to empty so the original two-argument call is unchanged.
    """

    def _bump(s: Screening) -> None:
        s.apply_attempts += 1
        s.apply_error = error
        s.apply_blocker = blocker
        s.signin_url = signin_url

    return _mutate(screening_id, _bump)
```

- [ ] **Step 5: Run the new test and the full suite**

Run: `pytest tests/test_screening_login_blocker.py -v`
Expected: PASS (5 tests)

Run: `pytest`
Expected: 996 passed, 2 skipped

- [ ] **Step 6: Commit**

```bash
git add screening/model.py screening/store.py tests/test_screening_login_blocker.py
git commit -m "feat: record login walls as a structured screening blocker"
```

---

### Task 2: Expose the blocker through the MCP tool and the RUNBOOK

**Files:**
- Modify: `agenttools/tools_ledger.py:520-530`
- Modify: `agenttools/mcp_app.py:70-73`
- Modify: `agent/RUNBOOK.md`
- Test: `tests/test_login_wall_tool.py` (create)

**Interfaces:**
- Consumes: `screening.store.record_apply_failure(screening_id, error, blocker="", signin_url="")` from Task 1.
- Produces: `agenttools.tools_ledger.report_apply_failure(screening_id: str, error: str, blocker: str = "", signin_url: str = "") -> dict`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_login_wall_tool.py`:

```python
"""report_apply_failure carries the structured login-wall blocker through to the store."""

from __future__ import annotations

from agenttools.tools_ledger import report_apply_failure
from agenttools.mcp_app import TOOLS
from screening import store


def test_reports_a_login_wall_with_its_url(data_dir):
    s = store.create({"company": "Acme", "role": "Dev", "verdict": "passed"})
    result = report_apply_failure(
        s.id,
        "sign-in required",
        blocker="login_required",
        signin_url="https://acme.wd3.myworkdayjobs.com/login",
    )
    assert result == {"ok": True, "attempts": 1}
    stored = store.get(s.id)
    assert stored.apply_blocker == "login_required"
    assert stored.signin_url == "https://acme.wd3.myworkdayjobs.com/login"


def test_plain_failure_still_works(data_dir):
    s = store.create({"company": "Acme", "role": "Dev", "verdict": "passed"})
    result = report_apply_failure(s.id, "form timed out")
    assert result["ok"] is True
    assert store.get(s.id).apply_blocker == ""


def test_unknown_id_is_still_reported_cleanly(data_dir):
    result = report_apply_failure("nope", "x", blocker="login_required")
    assert result == {"ok": False, "reason": "unknown screening id"}


def test_tool_description_tells_the_agent_about_login_walls():
    _fn, description = TOOLS["report_apply_failure"]
    assert "login_required" in description
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_login_wall_tool.py -v`
Expected: FAIL with `TypeError: report_apply_failure() got an unexpected keyword argument 'blocker'`

- [ ] **Step 3: Widen the tool function**

In `agenttools/tools_ledger.py`, replace lines 520-530:

```python
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

with:

```python
def report_apply_failure(
    screening_id: str,
    error: str,
    blocker: str = "",
    signin_url: str = "",
) -> dict:
    """Record why an approved application could not be completed this run.

    Leaves the item approved and queued: the operator chose retry-on-next-run,
    and this tool cannot change an approval either way.

    `blocker="login_required"` with `signin_url` set is what puts the site in
    the operator's sign-in queue. Without them the failure is recorded but the
    operator is never told which site to go and authorise.
    """
    updated = _screening_store.record_apply_failure(
        screening_id, error, blocker=blocker, signin_url=signin_url
    )
    if updated is None:
        return {"ok": False, "reason": "unknown screening id"}
    return {"ok": True, "attempts": updated.apply_attempts}
```

- [ ] **Step 4: Update the MCP tool description**

In `agenttools/mcp_app.py`, replace the entry at lines 70-73:

```python
    "report_apply_failure": (
        _report_apply_failure,
        "Records why an approved application could not be completed. The item stays queued for the next run.",
    ),
```

with:

```python
    "report_apply_failure": (
        _report_apply_failure,
        "Records why an approved application could not be completed. The item "
        "stays queued for the next run. When the form sat behind a sign-in or "
        "registration wall, also pass blocker='login_required' and signin_url "
        "(the login page URL) — that is what tells the operator which site to "
        "sign in to. Never create an account yourself.",
    ),
```

- [ ] **Step 5: Add the RUNBOOK rule**

In `agent/RUNBOOK.md`, find the numbered apply sequence in §5 that begins `4. Fill every field from the get_profile_answers result (§3)`. Insert this as a new numbered item immediately before it, renumbering the items after it:

```markdown
4. **A sign-in or registration wall stops this application — it does not start
   a detour.** If reaching the form needs an account, a login, an SSO
   challenge, or an emailed verification code you do not already have a
   session for: do not create an account, do not invent a password, do not
   reuse the operator's address as a login unless the site already recognises
   it. Call `report_apply_failure` with `blocker="login_required"`, `error`
   describing what you saw, and `signin_url` set to the login page's URL, then
   move to the next posting. The operator signs in once, on the Agents page,
   and the item is retried on a later run.
```

- [ ] **Step 6: Run the tests**

Run: `pytest tests/test_login_wall_tool.py -v`
Expected: PASS (4 tests)

Run: `pytest`
Expected: 1000 passed, 2 skipped

Note: `tests/test_doc_cross_references.py` checks that RUNBOOK section citations resolve. If it fails, the section reference in the new text needs to match an existing heading — read the failure and fix the citation, do not weaken the test.

- [ ] **Step 7: Commit**

```bash
git add agenttools/tools_ledger.py agenttools/mcp_app.py agent/RUNBOOK.md tests/test_login_wall_tool.py
git commit -m "feat: let the agent report a login wall with its sign-in URL"
```

---

### Task 3: The sign-in queue endpoint

**Files:**
- Modify: `api/schemas.py` (append near `AgentStatus`, around line 952)
- Modify: `api/routes.py` (add after the `/agent/cancel` route, around line 1222)
- Test: `tests/test_signin_queue_api.py` (create)

**Interfaces:**
- Consumes: `Screening.apply_blocker`, `Screening.signin_url` from Task 1.
- Produces: `GET /api/browser/signin-queue` returning `{"sites": [{"host", "signinUrl", "waiting", "lastBlockedAt", "companies"}]}`; schema classes `SigninQueueSite` and `SigninQueue`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_signin_queue_api.py`:

```python
"""GET /api/browser/signin-queue: derived from screenings, deduplicated by full host."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app
from screening import store


@pytest.fixture()
def client(data_dir):
    return TestClient(app)


def _blocked(company: str, url: str, signin_url: str) -> str:
    s = store.create({"company": company, "role": "Dev", "verdict": "passed", "url": url})
    store.set_approval(s.id, "approved")
    store.record_apply_failure(
        s.id, "sign-in required", blocker="login_required", signin_url=signin_url
    )
    return s.id


def test_empty_when_nothing_is_blocked(client, data_dir):
    r = client.get("/api/browser/signin-queue")
    assert r.status_code == 200
    assert r.json() == {"sites": []}


def test_plain_failures_do_not_appear(client, data_dir):
    s = store.create({"company": "Acme", "role": "Dev", "verdict": "passed"})
    store.set_approval(s.id, "approved")
    store.record_apply_failure(s.id, "form timed out")
    r = client.get("/api/browser/signin-queue")
    assert r.json() == {"sites": []}


def test_one_blocked_posting_becomes_one_site(client, data_dir):
    _blocked(
        "Acme",
        "https://acme.wd3.myworkdayjobs.com/careers/job/1",
        "https://acme.wd3.myworkdayjobs.com/login",
    )
    sites = client.get("/api/browser/signin-queue").json()["sites"]
    assert len(sites) == 1
    assert sites[0]["host"] == "acme.wd3.myworkdayjobs.com"
    assert sites[0]["signinUrl"] == "https://acme.wd3.myworkdayjobs.com/login"
    assert sites[0]["waiting"] == 1
    assert sites[0]["companies"] == ["Acme"]


def test_many_postings_at_one_tenant_collapse_to_one_entry(client, data_dir):
    for n in (1, 2, 3):
        _blocked(
            "Acme",
            f"https://acme.wd3.myworkdayjobs.com/careers/job/{n}",
            "https://acme.wd3.myworkdayjobs.com/login",
        )
    sites = client.get("/api/browser/signin-queue").json()["sites"]
    assert len(sites) == 1
    assert sites[0]["waiting"] == 3


def test_different_tenants_of_one_platform_stay_separate(client, data_dir):
    """The unit is the full host, never the registrable domain."""
    _blocked("Acme", "https://acme.wd3.myworkdayjobs.com/j/1", "https://acme.wd3.myworkdayjobs.com/login")
    _blocked("Globex", "https://globex.wd1.myworkdayjobs.com/j/1", "https://globex.wd1.myworkdayjobs.com/login")
    sites = client.get("/api/browser/signin-queue").json()["sites"]
    hosts = sorted(s["host"] for s in sites)
    assert hosts == ["acme.wd3.myworkdayjobs.com", "globex.wd1.myworkdayjobs.com"]


def test_applied_items_drop_off_the_queue(client, data_dir):
    """Truth is the agent's experience: getting through clears the entry."""
    sid = _blocked("Acme", "https://acme.wd3.myworkdayjobs.com/j/1", "https://acme.wd3.myworkdayjobs.com/login")
    store.mark_applied(sid)
    assert client.get("/api/browser/signin-queue").json() == {"sites": []}


def test_rejected_items_drop_off_the_queue(client, data_dir):
    sid = _blocked("Acme", "https://acme.wd3.myworkdayjobs.com/j/1", "https://acme.wd3.myworkdayjobs.com/login")
    store.set_approval(sid, "rejected")
    assert client.get("/api/browser/signin-queue").json() == {"sites": []}


def test_entry_without_a_usable_signin_url_falls_back_to_the_posting(client, data_dir):
    s = store.create(
        {"company": "Acme", "role": "Dev", "verdict": "passed",
         "url": "https://acme.wd3.myworkdayjobs.com/careers/job/1"}
    )
    store.set_approval(s.id, "approved")
    store.record_apply_failure(s.id, "sign-in required", blocker="login_required")
    sites = client.get("/api/browser/signin-queue").json()["sites"]
    assert sites[0]["host"] == "acme.wd3.myworkdayjobs.com"
    assert sites[0]["signinUrl"] == "https://acme.wd3.myworkdayjobs.com/careers/job/1"


def test_unparseable_urls_are_dropped_rather_than_grouped_under_a_blank_host(client, data_dir):
    s = store.create({"company": "Acme", "role": "Dev", "verdict": "passed", "url": "not a url"})
    store.set_approval(s.id, "approved")
    store.record_apply_failure(s.id, "sign-in required", blocker="login_required")
    assert client.get("/api/browser/signin-queue").json() == {"sites": []}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_signin_queue_api.py -v`
Expected: FAIL — all tests 404, since the route does not exist.

- [ ] **Step 3: Add the schemas**

In `api/schemas.py`, immediately after the `AgentStatus` class (which ends at line 952 with `last_cancelled: bool = False`), append:

```python
class SigninQueueSite(_Camel):
    """One host the agent could not get past a sign-in wall on."""

    # The full host, e.g. "acme.wd3.myworkdayjobs.com". Deliberately not the
    # registrable domain: each Workday tenant is a separate account, so
    # collapsing to "myworkdayjobs.com" would merge unrelated sign-ins.
    host: str
    signin_url: str
    # How many approved postings are stuck behind this one sign-in.
    waiting: int
    last_blocked_at: str
    companies: list[str]


class SigninQueue(_Camel):
    """GET /api/browser/signin-queue — sites needing the operator to sign in."""

    sites: list[SigninQueueSite]
```

- [ ] **Step 4: Add the route**

In `api/routes.py`, add `from urllib.parse import urlparse` to the imports at the top if it is not already there, add `SigninQueue` and `SigninQueueSite` to the existing `api.schemas` import list, and add this after the `post_agent_cancel` function (which ends around line 1222):

```python
def _host_of(url: str) -> str:
    """The full host of an absolute http(s) URL, or "" if it is not one.

    Anything without a scheme and a netloc is not addressable, so it cannot be
    a sign-in destination — returning "" drops it rather than grouping several
    unrelated records under a blank host.
    """
    try:
        parsed = urlparse(url or "")
    except ValueError:
        return ""
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    return parsed.netloc.casefold()


@router.get("/browser/signin-queue", response_model=SigninQueue)
def get_signin_queue() -> SigninQueue:
    """Sites the agent hit a sign-in wall on, grouped by host.

    Derived from the screening store on every call rather than kept as its own
    state: the agent's experience is the only source of truth here, so an entry
    exists exactly as long as a posting is still waiting behind that sign-in.
    """
    grouped: dict[str, dict] = {}
    for s in screening_store.load_all():
        if s.apply_blocker != "login_required":
            continue
        # Only items still queued to be applied to. Applied or rejected means
        # nothing is waiting on this sign-in any more.
        if s.approval not in ("pending", "approved"):
            continue
        url = s.signin_url or s.url
        host = _host_of(url)
        if not host:
            continue
        entry = grouped.setdefault(
            host,
            {"host": host, "signin_url": url, "waiting": 0, "last_blocked_at": "", "companies": []},
        )
        entry["waiting"] += 1
        if s.updated_at > entry["last_blocked_at"]:
            entry["last_blocked_at"] = s.updated_at
        if s.company and s.company not in entry["companies"]:
            entry["companies"].append(s.company)
    sites = [SigninQueueSite(**e) for e in grouped.values()]
    sites.sort(key=lambda s: (-s.waiting, s.host))
    return SigninQueue(sites=sites)
```

If `screening_store` is not already the name `api/routes.py` imports the screening store under, use whatever name that file already uses — check the imports at the top of the file rather than adding a second import.

- [ ] **Step 5: Run the tests**

Run: `pytest tests/test_signin_queue_api.py -v`
Expected: PASS (9 tests)

Run: `pytest`
Expected: 1009 passed, 2 skipped

- [ ] **Step 6: Commit**

```bash
git add api/schemas.py api/routes.py tests/test_signin_queue_api.py
git commit -m "feat: derive a per-host sign-in queue from blocked screenings"
```

---

### Task 4: The browser session server

**Files:**
- Create: `browser/session-server.js`
- Modify: `browser/entrypoint.sh` (start it alongside the other services)
- Modify: `browser/Dockerfile` (window manager, `EXPOSE`)
- Test: `browser/session-server.test.js` (create), run with `node --test`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: HTTP control surface on port 8932 — `GET /session`, `POST /session {url}`, `POST /session/close`, `POST /session/evict`. All require header `X-Agent-Token`. `GET /session` returns `{open: boolean, url: string|null, startedAt: string|null, evictDeadline: string|null}`.

- [ ] **Step 1: Write the failing test**

Create `browser/session-server.test.js`:

```javascript
// Unit tests for the session server's decision logic, with process launching
// and the supervisor probe injected so nothing real is started.
const test = require("node:test");
const assert = require("node:assert");

const { createSessionManager } = require("./session-server.js");

function manager(overrides = {}) {
  return createSessionManager({
    supervisorIdle: async () => true,
    profileInUse: async () => false,
    launch: () => ({ pid: 4242, kill() { this.killed = true; }, killed: false }),
    now: () => new Date("2026-08-25T12:00:00.000Z"),
    graceMs: 180000,
    ...overrides,
  });
}

test("a fresh manager reports no session", async () => {
  const m = manager();
  assert.deepStrictEqual(m.state(), {
    open: false, url: null, startedAt: null, evictDeadline: null,
  });
});

test("opening a session records its url", async () => {
  const m = manager();
  const result = await m.open("https://example.com/login");
  assert.strictEqual(result.ok, true);
  assert.strictEqual(m.state().open, true);
  assert.strictEqual(m.state().url, "https://example.com/login");
});

test("a second open is refused and names the session already running", async () => {
  const m = manager();
  await m.open("https://example.com/login");
  const result = await m.open("https://other.com/login");
  assert.strictEqual(result.ok, false);
  assert.strictEqual(result.reason, "session_open");
  assert.strictEqual(result.url, "https://example.com/login");
});

test("a running agent refuses the session", async () => {
  const m = manager({ supervisorIdle: async () => false });
  const result = await m.open("https://example.com/login");
  assert.strictEqual(result.ok, false);
  assert.strictEqual(result.reason, "agent_running");
});

test("an unreachable supervisor refuses the session (fails closed)", async () => {
  const m = manager({ supervisorIdle: async () => { throw new Error("ECONNREFUSED"); } });
  const result = await m.open("https://example.com/login");
  assert.strictEqual(result.ok, false);
  assert.strictEqual(result.reason, "agent_unreachable");
});

test("a profile already held by another chromium refuses the session", async () => {
  const m = manager({ profileInUse: async () => true });
  const result = await m.open("https://example.com/login");
  assert.strictEqual(result.ok, false);
  assert.strictEqual(result.reason, "profile_busy");
});

test("only http and https urls are accepted", async () => {
  const m = manager();
  for (const bad of ["file:///etc/passwd", "javascript:alert(1)", "not a url", ""]) {
    const result = await m.open(bad);
    assert.strictEqual(result.ok, false, `expected ${bad} to be refused`);
    assert.strictEqual(result.reason, "bad_url");
  }
});

test("closing kills the browser and clears the session", async () => {
  const proc = { pid: 1, kill() { this.killed = true; }, killed: false };
  const m = manager({ launch: () => proc });
  await m.open("https://example.com/login");
  m.close();
  assert.strictEqual(proc.killed, true);
  assert.strictEqual(m.state().open, false);
});

test("evicting sets a deadline without killing immediately", async () => {
  const m = manager();
  await m.open("https://example.com/login");
  const result = m.evict();
  assert.strictEqual(result.evicting, true);
  assert.strictEqual(m.state().evictDeadline, "2026-08-25T12:03:00.000Z");
  assert.strictEqual(m.state().open, true);
});

test("evicting with no session open is a no-op, not an error", async () => {
  const m = manager();
  const result = m.evict();
  assert.strictEqual(result.evicting, false);
});

test("a second evict does not extend the first deadline", async () => {
  let t = new Date("2026-08-25T12:00:00.000Z");
  const m = manager({ now: () => t });
  await m.open("https://example.com/login");
  m.evict();
  t = new Date("2026-08-25T12:01:00.000Z");
  m.evict();
  assert.strictEqual(m.state().evictDeadline, "2026-08-25T12:03:00.000Z");
});

test("the deadline passing closes the session", async () => {
  let t = new Date("2026-08-25T12:00:00.000Z");
  const proc = { pid: 1, kill() { this.killed = true; }, killed: false };
  const m = manager({ now: () => t, launch: () => proc });
  await m.open("https://example.com/login");
  m.evict();
  t = new Date("2026-08-25T12:03:01.000Z");
  m.tick();
  assert.strictEqual(proc.killed, true);
  assert.strictEqual(m.state().open, false);
});

test("a browser that exits on its own clears the session", async () => {
  const m = manager();
  await m.open("https://example.com/login");
  m.onBrowserExit();
  assert.strictEqual(m.state().open, false);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test browser/session-server.test.js`
Expected: FAIL — `Cannot find module './session-server.js'`

- [ ] **Step 3: Write the session server**

Create `browser/session-server.js`:

```javascript
#!/usr/bin/env node
// Attended browser session control server.
//
// Owns ONE attended Chromium session on the persistent profile, so the
// operator can sign in to a site by hand at a time of their choosing. Mirrors
// agent/supervisor.js: same token header, same jsonReply idiom, plain node
// http with no framework.
//
// The agent's own browser is driven by @playwright/mcp in this same container
// and launches Chromium lazily per run. Only one process may hold
// /browser-profile at a time, so this server refuses to open a session while a
// run is in progress, and daily-apply.sh evicts an open session before a run
// starts. Both halves are required: either alone leaves a race.

const http = require("http");
const { spawn, execFileSync } = require("child_process");
const crypto = require("crypto");

const PORT = parseInt(process.env.SESSION_SERVER_PORT || "8932", 10);
const TOKEN = (process.env.AGENT_API_TOKEN || "").trim();
const PROFILE_DIR = process.env.BROWSER_PROFILE_DIR || "/browser-profile";
const AGENT_CONTROL_PORT = process.env.AGENT_CONTROL_PORT || "9099";
const GRACE_MS = parseInt(process.env.SESSION_GRACE_MS || "180000", 10);
const CHROME_BIN = process.env.SESSION_CHROME_BIN || "chromium";
const TICK_MS = 5000;

function log(...args) {
  console.log(new Date().toISOString().slice(11, 19), ...args);
}

// ---------------------------------------------------------------------------
// Auth — identical rule to agent/supervisor.js: no token configured means no
// request is ever accepted.
// ---------------------------------------------------------------------------
function tokenOk(given) {
  if (!TOKEN) return false;
  const a = Buffer.from(given || "", "utf8");
  const b = Buffer.from(TOKEN, "utf8");
  const len = Math.max(a.length, b.length);
  const pa = Buffer.concat([a, Buffer.alloc(Math.max(0, len - a.length))]);
  const pb = Buffer.concat([b, Buffer.alloc(Math.max(0, len - b.length))]);
  return crypto.timingSafeEqual(pa, pb) && a.length === b.length;
}

// ---------------------------------------------------------------------------
// Session manager — pure decision logic, with every side effect injected so it
// can be tested without launching a browser or reaching the agent.
// ---------------------------------------------------------------------------
function createSessionManager(deps) {
  const { supervisorIdle, profileInUse, launch, now, graceMs } = deps;
  let session = null; // { url, proc, startedAt, evictDeadline }

  function state() {
    return {
      open: session !== null,
      url: session ? session.url : null,
      startedAt: session ? session.startedAt : null,
      evictDeadline: session ? session.evictDeadline : null,
    };
  }

  function validUrl(url) {
    let parsed;
    try {
      parsed = new URL(url);
    } catch {
      return false;
    }
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  }

  async function open(url) {
    if (!validUrl(url)) return { ok: false, reason: "bad_url" };
    if (session) return { ok: false, reason: "session_open", url: session.url };

    let idle;
    try {
      idle = await supervisorIdle();
    } catch {
      // Fail closed. daily-apply.sh already treats an unreachable config API
      // as "do not run" rather than assuming a safe state; the same rule
      // applies here, in the other direction.
      return { ok: false, reason: "agent_unreachable" };
    }
    if (!idle) return { ok: false, reason: "agent_running" };

    if (await profileInUse()) return { ok: false, reason: "profile_busy" };

    const proc = launch(url);
    session = { url, proc, startedAt: now().toISOString(), evictDeadline: null };
    if (proc && typeof proc.on === "function") {
      proc.on("exit", () => onBrowserExit());
    }
    log(`session opened at ${url} (pid ${proc && proc.pid})`);
    return { ok: true };
  }

  function close() {
    if (!session) return { closed: false };
    try {
      session.proc.kill("SIGTERM");
    } catch (err) {
      log(`kill failed: ${err.message}`);
    }
    log("session closed");
    session = null;
    return { closed: true };
  }

  function evict() {
    if (!session) return { evicting: false };
    // Never extend an existing deadline: a run that asks twice must not push
    // the browser further out of its own reach.
    if (session.evictDeadline) {
      return { evicting: true, deadline: session.evictDeadline };
    }
    session.evictDeadline = new Date(now().getTime() + graceMs).toISOString();
    log(`session eviction scheduled for ${session.evictDeadline}`);
    return { evicting: true, deadline: session.evictDeadline };
  }

  function tick() {
    if (!session || !session.evictDeadline) return;
    if (now().getTime() >= Date.parse(session.evictDeadline)) {
      log("eviction deadline reached");
      close();
    }
  }

  function onBrowserExit() {
    if (!session) return;
    log("browser exited on its own");
    session = null;
  }

  return { state, open, close, evict, tick, onBrowserExit };
}

// ---------------------------------------------------------------------------
// Real side effects
// ---------------------------------------------------------------------------
function supervisorIdle() {
  return new Promise((resolve, reject) => {
    const req = http.get(
      `http://agent:${AGENT_CONTROL_PORT}/status`,
      { timeout: 5000, headers: { "X-Agent-Token": TOKEN } },
      (res) => {
        let body = "";
        res.on("data", (c) => (body += c));
        res.on("end", () => {
          try {
            const parsed = JSON.parse(body);
            resolve(parsed.running !== true);
          } catch (err) {
            reject(err);
          }
        });
      }
    );
    req.on("timeout", () => { req.destroy(); reject(new Error("timeout")); });
    req.on("error", reject);
  });
}

async function profileInUse() {
  // Any chromium process at all in this container means the profile may be
  // held. Cheaper and safer than interpreting SingletonLock a second time —
  // browser/entrypoint.sh already adjudicates that on startup.
  try {
    const out = execFileSync("pgrep", ["-c", "chrome"], { encoding: "utf8" });
    return parseInt(out.trim(), 10) > 0;
  } catch {
    // pgrep exits non-zero when nothing matches.
    return false;
  }
}

function launchBrowser(url) {
  return spawn(
    CHROME_BIN,
    [
      `--user-data-dir=${PROFILE_DIR}`,
      "--no-first-run",
      "--no-default-browser-check",
      "--start-maximized",
      url,
    ],
    { env: { ...process.env, DISPLAY: process.env.DISPLAY || ":99" }, stdio: "ignore" }
  );
}

// ---------------------------------------------------------------------------
// HTTP server
// ---------------------------------------------------------------------------
function jsonReply(res, status, body) {
  const data = JSON.stringify(body);
  res.writeHead(status, {
    "Content-Type": "application/json",
    "Content-Length": Buffer.byteLength(data),
  });
  res.end(data);
}

function readJson(req) {
  return new Promise((resolve) => {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      try {
        resolve(JSON.parse(body || "{}"));
      } catch {
        resolve({});
      }
    });
  });
}

const REFUSAL_STATUS = {
  bad_url: 400,
  session_open: 409,
  agent_running: 409,
  agent_unreachable: 503,
  profile_busy: 409,
};

function createServer(manager) {
  return http.createServer(async (req, res) => {
    if (!tokenOk(req.headers["x-agent-token"] || "")) {
      return jsonReply(res, 403, { detail: "Forbidden" });
    }
    if (req.method === "GET" && req.url === "/session") {
      return jsonReply(res, 200, manager.state());
    }
    if (req.method === "POST" && req.url === "/session") {
      const body = await readJson(req);
      const result = await manager.open(body.url);
      if (!result.ok) {
        return jsonReply(res, REFUSAL_STATUS[result.reason] || 409, result);
      }
      return jsonReply(res, 200, { ...result, ...manager.state() });
    }
    if (req.method === "POST" && req.url === "/session/close") {
      return jsonReply(res, 200, manager.close());
    }
    if (req.method === "POST" && req.url === "/session/evict") {
      return jsonReply(res, 200, manager.evict());
    }
    jsonReply(res, 404, { detail: "Not found" });
  });
}

module.exports = { createSessionManager, createServer, tokenOk };

if (require.main === module) {
  const manager = createSessionManager({
    supervisorIdle,
    profileInUse,
    launch: launchBrowser,
    now: () => new Date(),
    graceMs: GRACE_MS,
  });
  setInterval(() => manager.tick(), TICK_MS).unref();
  const server = createServer(manager);
  server.listen(PORT, "0.0.0.0", () => log(`session server listening on port ${PORT}`));
  server.on("error", (err) => {
    log(`server error: ${err.message}`);
    process.exit(1);
  });
}
```

- [ ] **Step 4: Run the tests**

Run: `node --test browser/session-server.test.js`
Expected: PASS (13 tests)

- [ ] **Step 5: Install a window manager and expose the port**

In `browser/Dockerfile`, change the apt install block:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
      xvfb x11vnc novnc websockify \
 && rm -rf /var/lib/apt/lists/*
```

to:

```dockerfile
#   openbox:    Window manager. Without one, Chromium's windows are unmanaged:
#               no title bar, no move, resize, raise or close. SSO flows open a
#               second top-level window for the identity provider, which lands
#               stacked over or under the first with no way to switch — so a
#               manual sign-in through the viewport is unusable without this.
#   procps:     pgrep, used by session-server.js to check whether any Chromium
#               already holds the profile.
RUN apt-get update && apt-get install -y --no-install-recommends \
      xvfb x11vnc novnc websockify openbox procps \
 && rm -rf /var/lib/apt/lists/*
```

Change the `EXPOSE` line and its comment:

```dockerfile
# Expose ports:
#   8931: @playwright/mcp HTTP server (internal to compose network)
#   8932: attended session control server (internal to compose network)
#   7900: noVNC (proxied by the app; not published to the host)
EXPOSE 8931 8932 7900
```

Add the session server to the image beside the entrypoint copy:

```dockerfile
COPY browser/session-server.js /browser/session-server.js
```

- [ ] **Step 6: Start openbox and the session server from the entrypoint**

In `browser/entrypoint.sh`, after the x11vnc block and before the noVNC block, insert:

```bash
# Start the window manager. Chromium's windows are unmanaged without one, and
# an SSO popup then cannot be raised, moved or closed from the viewport.
log "starting openbox on $DISPLAY..."
openbox &
OPENBOX_PID=$!
sleep 1

if ! kill -0 "$OPENBOX_PID" 2>/dev/null; then
  abort "openbox failed to start (PID $OPENBOX_PID)"
fi
log "openbox running on PID $OPENBOX_PID"
```

After the noVNC block and before the SingletonLock handling, insert:

```bash
# Start the attended session control server (see browser/session-server.js).
log "starting session server on port ${SESSION_SERVER_PORT:-8932}..."
node /browser/session-server.js &
SESSION_PID=$!
sleep 1

if ! kill -0 "$SESSION_PID" 2>/dev/null; then
  abort "session server failed to start (PID $SESSION_PID)"
fi
log "session server running on PID $SESSION_PID"
```

- [ ] **Step 7: Verify the image builds and the services come up**

Run: `docker compose build browser`
Expected: builds cleanly.

Run: `docker compose up -d browser && sleep 20 && docker compose logs browser | tail -20`
Expected: log lines for Xvfb, x11vnc, openbox, noVNC, session server, and `@playwright/mcp`.

Run: `docker compose exec browser sh -c 'ps -eo comm= | sort -u'`
Expected: includes `openbox` and two `node` processes.

- [ ] **Step 8: Commit**

```bash
git add browser/session-server.js browser/session-server.test.js browser/Dockerfile browser/entrypoint.sh
git commit -m "feat: attended browser session server with a window manager"
```

---

### Task 5: App routes forwarding to the session server

**Files:**
- Modify: `api/schemas.py` (append after `SigninQueue` from Task 3)
- Modify: `api/routes.py` (add after `get_signin_queue` from Task 3)
- Test: `tests/test_browser_session_api.py` (create)

**Interfaces:**
- Consumes: the session server's HTTP surface from Task 4.
- Produces: `GET /api/browser/session`, `POST /api/browser/session {url}`, `DELETE /api/browser/session`; schema class `BrowserSession`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_browser_session_api.py`:

```python
"""/api/browser/session: forwarding, refusal passthrough, 503 when the browser is down."""

from __future__ import annotations

import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture()
def client(data_dir):
    return TestClient(app)


def _response(payload: dict):
    body = json.dumps(payload).encode()
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _http_error(status: int, payload: dict):
    return urllib.error.HTTPError(
        url="http://browser:8932/session",
        code=status,
        msg="refused",
        hdrs=None,
        fp=None,
    )


class TestGetSession:
    def test_reports_no_session(self, client, monkeypatch):
        monkeypatch.setenv("AGENT_API_TOKEN", "t")
        upstream = {"open": False, "url": None, "startedAt": None, "evictDeadline": None}
        with patch("urllib.request.urlopen", return_value=_response(upstream)):
            r = client.get("/api/browser/session")
        assert r.status_code == 200
        assert r.json()["open"] is False

    def test_reports_an_open_session(self, client, monkeypatch):
        monkeypatch.setenv("AGENT_API_TOKEN", "t")
        upstream = {
            "open": True,
            "url": "https://example.com/login",
            "startedAt": "2026-08-25T12:00:00.000Z",
            "evictDeadline": None,
        }
        with patch("urllib.request.urlopen", return_value=_response(upstream)):
            r = client.get("/api/browser/session")
        body = r.json()
        assert body["open"] is True
        assert body["url"] == "https://example.com/login"

    def test_browser_down_is_503(self, client, monkeypatch):
        monkeypatch.setenv("AGENT_API_TOKEN", "t")
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            r = client.get("/api/browser/session")
        assert r.status_code == 503


class TestPostSession:
    def test_opens_a_session(self, client, monkeypatch):
        monkeypatch.setenv("AGENT_API_TOKEN", "t")
        upstream = {
            "open": True,
            "url": "https://example.com/login",
            "startedAt": "2026-08-25T12:00:00.000Z",
            "evictDeadline": None,
        }
        with patch("urllib.request.urlopen", return_value=_response(upstream)):
            r = client.post("/api/browser/session", json={"url": "https://example.com/login"})
        assert r.status_code == 200
        assert r.json()["open"] is True

    def test_agent_running_is_forwarded_as_409(self, client, monkeypatch):
        """The UI needs to distinguish 'busy' from 'broken' — a 409 must not become a 503."""
        monkeypatch.setenv("AGENT_API_TOKEN", "t")
        with patch("urllib.request.urlopen", side_effect=_http_error(409, {"reason": "agent_running"})):
            r = client.post("/api/browser/session", json={"url": "https://example.com/login"})
        assert r.status_code == 409

    def test_a_non_http_url_is_rejected_before_forwarding(self, client, monkeypatch):
        monkeypatch.setenv("AGENT_API_TOKEN", "t")
        with patch("urllib.request.urlopen") as urlopen:
            r = client.post("/api/browser/session", json={"url": "file:///etc/passwd"})
        assert r.status_code == 422
        assert urlopen.call_count == 0


class TestDeleteSession:
    def test_closes_the_session(self, client, monkeypatch):
        monkeypatch.setenv("AGENT_API_TOKEN", "t")
        with patch("urllib.request.urlopen", return_value=_response({"closed": True})):
            r = client.delete("/api/browser/session")
        assert r.status_code == 200
        assert r.json()["closed"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_browser_session_api.py -v`
Expected: FAIL — 404 on every route.

- [ ] **Step 3: Add the schemas**

In `api/schemas.py`, after the `SigninQueue` class added in Task 3, append:

```python
class BrowserSession(_Camel):
    """GET/POST /api/browser/session — forwarded from browser/session-server.js."""

    open: bool
    url: str | None = None
    started_at: str | None = None
    # Set once a run has asked for the browser back. The session page counts
    # down to this and the session server closes the session when it passes.
    evict_deadline: str | None = None


class BrowserSessionRequest(_Camel):
    """POST /api/browser/session body."""

    url: str


class BrowserSessionClosed(_Camel):
    """DELETE /api/browser/session."""

    closed: bool
```

- [ ] **Step 4: Add the forwarding helper and routes**

In `api/routes.py`, after `get_signin_queue`, add:

```python
def _browser_control_url(path: str) -> str:
    """Build the session-server control URL from env, defaulting port 8932."""
    port = os.environ.get("SESSION_SERVER_PORT", "8932")
    return f"http://browser:{port}{path}"


def _forward_to_session_server(path: str, method: str = "GET", body: dict | None = None) -> dict:
    """Forward a request to browser/session-server.js.

    Distinguishes three outcomes the UI must tell apart: a normal answer, a
    refusal the session server made deliberately (4xx/503 — forwarded with its
    own status so "the agent is applying right now" does not read as "the
    browser is broken"), and the container being unreachable (503).
    """
    token = os.environ.get("AGENT_API_TOKEN", "")
    data = json.dumps(body or {}).encode() if method == "POST" else None
    req = urllib.request.Request(
        _browser_control_url(path),
        method=method,
        headers={"X-Agent-Token": token, "Content-Type": "application/json"},
        data=data,
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=exc.code, detail="Session refused") from exc
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=503, detail="Browser service unreachable") from exc


def _session_from(data: dict) -> BrowserSession:
    return BrowserSession(
        open=data.get("open", False),
        url=data.get("url"),
        started_at=data.get("startedAt"),
        evict_deadline=data.get("evictDeadline"),
    )


@router.get("/browser/session", response_model=BrowserSession)
def get_browser_session() -> BrowserSession:
    """Whether an attended sign-in session is open, and at which URL."""
    return _session_from(_forward_to_session_server("/session", method="GET"))


@router.post("/browser/session", response_model=BrowserSession)
def post_browser_session(payload: BrowserSessionRequest) -> BrowserSession:
    """Open an attended sign-in session at a URL.

    Refused with 409 while a run is in progress: unattended runs win, and the
    operator is told to try again shortly rather than the run being disturbed.
    """
    if _host_of(payload.url) == "":
        raise HTTPException(status_code=422, detail="An http(s) URL is required")
    return _session_from(
        _forward_to_session_server("/session", method="POST", body={"url": payload.url})
    )


@router.delete("/browser/session", response_model=BrowserSessionClosed)
def delete_browser_session() -> BrowserSessionClosed:
    """Close the attended session and release the browser."""
    data = _forward_to_session_server("/session/close", method="POST")
    return BrowserSessionClosed(closed=data.get("closed", False))
```

Add `BrowserSession`, `BrowserSessionRequest` and `BrowserSessionClosed` to the `api.schemas` import list.

- [ ] **Step 5: Run the tests**

Run: `pytest tests/test_browser_session_api.py -v`
Expected: PASS (7 tests)

Run: `pytest`
Expected: 1016 passed, 2 skipped

- [ ] **Step 6: Commit**

```bash
git add api/schemas.py api/routes.py tests/test_browser_session_api.py
git commit -m "feat: app routes for opening and closing a browser sign-in session"
```

---

### Task 6: The WebSocket relay, with an Origin check

**Files:**
- Modify: `requirements.txt`
- Create: `api/browser_stream.py`
- Modify: `api/main.py` (register the WebSocket route)
- Test: `tests/test_browser_stream.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `WS /api/browser/session/stream`; `api.browser_stream.origin_allowed(origin: str, host: str) -> bool`.

**Why this task exists as its own gate:** WebSocket connections are not subject to the same-origin policy, and the CORS middleware at `api/main.py:124` does not apply to them. Without the `Origin` check below, any web page the operator visits while a session is open can connect to this socket and drive a browser logged into their accounts.

- [ ] **Step 1: Write the failing test**

Create `tests/test_browser_stream.py`:

```python
"""The noVNC WebSocket relay refuses cross-origin connections.

WebSockets bypass the same-origin policy and CORS does not apply to them, so
this check is the only thing standing between a page the operator happens to
visit and keyboard control of a browser logged into their accounts.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from api.browser_stream import origin_allowed
from api.main import app


@pytest.fixture()
def client(data_dir):
    return TestClient(app)


class TestOriginAllowed:
    def test_same_origin_is_allowed(self):
        assert origin_allowed("http://localhost:5627", "localhost:5627") is True

    def test_https_same_host_is_allowed(self):
        assert origin_allowed("https://localhost:5627", "localhost:5627") is True

    def test_a_different_host_is_refused(self):
        assert origin_allowed("http://evil.example", "localhost:5627") is False

    def test_a_different_port_on_the_same_host_is_refused(self):
        assert origin_allowed("http://localhost:9999", "localhost:5627") is False

    def test_a_missing_origin_is_refused(self):
        """A browser always sends Origin on a WebSocket handshake. Absence is not a browser."""
        assert origin_allowed("", "localhost:5627") is False

    def test_a_host_prefix_attack_is_refused(self):
        assert origin_allowed("http://localhost:5627.evil.example", "localhost:5627") is False

    def test_a_garbage_origin_is_refused(self):
        assert origin_allowed("not a url", "localhost:5627") is False


class TestRelayHandshake:
    def test_cross_origin_connection_is_rejected(self, client):
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "/api/browser/session/stream",
                headers={"Origin": "http://evil.example"},
            ):
                pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_browser_stream.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.browser_stream'`

- [ ] **Step 3: Declare the dependency**

In `requirements.txt`, add below the `uvicorn` line:

```
# Used directly by api/browser_stream.py as a WebSocket *client*, to relay the
# browser container's noVNC socket. uvicorn[standard] happens to pull this in
# as a server transport, but relying on that would make a direct dependency
# invisible.
websockets>=12
```

- [ ] **Step 4: Write the relay**

Create `api/browser_stream.py`:

```python
"""Relay the browser container's noVNC WebSocket through the app.

The `browser` service's noVNC port is not published: the operator reaches the
viewport through this route instead, so there is one address and one place to
guard rather than a second passwordless port on every interface.

That guard is `origin_allowed`. WebSocket handshakes are exempt from the
same-origin policy and the CORS middleware in `api/main.py` does not see them,
so without an explicit check any page the operator visits while a session is
open could open this socket and drive a browser holding their live sessions.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

import websockets
from fastapi import WebSocket, WebSocketDisconnect
from starlette.concurrency import run_until_first_complete


def origin_allowed(origin: str, host: str) -> bool:
    """True when `origin`'s host:port is exactly the app's own `host` header.

    Compares the full authority, so neither a different port on the same host
    nor a hostname that merely starts with ours ("localhost:5627.evil.example")
    passes. An absent Origin is refused: every browser sends one on a WebSocket
    handshake, so its absence means the caller is not a browser.
    """
    if not origin or not host:
        return False
    try:
        parsed = urlparse(origin)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False
    return parsed.netloc.casefold() == host.casefold()


def novnc_url() -> str:
    """The in-network websockify endpoint the browser container serves."""
    port = os.environ.get("BROWSER_NOVNC_PORT", "7900")
    return f"ws://browser:{port}/websockify"


async def relay(websocket: WebSocket) -> None:
    """Accept a viewer socket and pump bytes both ways to the browser container."""
    origin = websocket.headers.get("origin", "")
    host = websocket.headers.get("host", "")
    if not origin_allowed(origin, host):
        # 1008 = policy violation. Closed before accept, so nothing is relayed.
        await websocket.close(code=1008)
        return

    await websocket.accept(subprotocol="binary")
    try:
        async with websockets.connect(novnc_url(), subprotocols=["binary"]) as upstream:

            async def viewer_to_browser() -> None:
                try:
                    while True:
                        await upstream.send(await websocket.receive_bytes())
                except (WebSocketDisconnect, RuntimeError):
                    return

            async def browser_to_viewer() -> None:
                try:
                    async for message in upstream:
                        await websocket.send_bytes(message)
                except websockets.ConnectionClosed:
                    return

            await run_until_first_complete(
                (viewer_to_browser, {}),
                (browser_to_viewer, {}),
            )
    except OSError:
        # The browser container is unreachable. 1011 = internal error; the page
        # shows its "browser unavailable" state rather than a blank canvas.
        await websocket.close(code=1011)
```

- [ ] **Step 5: Register the route**

In `api/main.py`, after `app.include_router(mcp_router)` (line 133), add:

```python
from api.browser_stream import relay as _browser_relay  # noqa: E402


@app.websocket("/api/browser/session/stream")
async def browser_session_stream(websocket: WebSocket) -> None:
    """noVNC relay for the attended sign-in session. See api/browser_stream.py."""
    await _browser_relay(websocket)
```

Add `WebSocket` to the existing `fastapi` import at the top of the file.

- [ ] **Step 6: Run the tests**

Run: `pytest tests/test_browser_stream.py -v`
Expected: PASS (8 tests)

Run: `pytest`
Expected: 1024 passed, 2 skipped

- [ ] **Step 7: Commit**

```bash
git add requirements.txt api/browser_stream.py api/main.py tests/test_browser_stream.py
git commit -m "feat: relay the noVNC socket through the app, origin-checked"
```

---

### Task 7: Runs evict an open session

**Files:**
- Modify: `agent/daily-apply.sh` (the precondition block ending around line 92)
- Test: `tests/test_daily_apply_eviction.py` (create)

**Interfaces:**
- Consumes: `POST /session/evict` and `GET /session` from Task 4.
- Produces: nothing later tasks depend on.

**Why both halves are needed:** `POST /session` checks the supervisor at a moment in time, so a run can start immediately afterwards. This precondition is the other half of the interlock. Without it there is a window in which a run and an attended session both drive the same profile, which is the documented "Browser is already in use" failure that poisons the volume.

- [ ] **Step 1: Write the failing test**

Create `tests/test_daily_apply_eviction.py`:

```python
"""daily-apply.sh evicts an attended sign-in session before taking the browser."""

from __future__ import annotations

from pathlib import Path

SCRIPT = Path("agent/daily-apply.sh").read_text()


def test_the_script_evicts_before_running():
    assert "/session/evict" in SCRIPT


def test_it_waits_for_the_session_to_close():
    """A grace period the run does not actually wait out is not a grace period."""
    assert "wait_for_session_release" in SCRIPT


def test_it_aborts_when_the_session_server_is_unreachable():
    """Fails closed, like every other precondition in this script."""
    assert "session server unreachable" in SCRIPT


def test_the_wait_is_bounded():
    """An unbounded wait turns a forgotten tab into a permanently skipped run."""
    assert "SESSION_EVICT_TIMEOUT" in SCRIPT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_daily_apply_eviction.py -v`
Expected: FAIL — all four assertions.

- [ ] **Step 3: Add the eviction precondition**

In `agent/daily-apply.sh`, inside the `browser)` branch of the `case "$AGENT_BROWSER_DRIVER"` block, after the existing `probe_browser || abort ...` line, add:

```bash
    # An attended sign-in session holds the same profile this run needs, so ask
    # for it back and wait out the grace period before proceeding. The session
    # server closes the session itself when its deadline passes; this loop only
    # waits for that to happen.
    #
    # Both halves of the interlock are required. session-server.js refuses to
    # OPEN a session while a run is in progress, but that is a moment-in-time
    # check — a run can start straight afterwards. Without this, both would
    # drive one profile, which is the "Browser is already in use" failure
    # browser/entrypoint.sh exists to clean up after.
    SESSION_EVICT_TIMEOUT="${SESSION_EVICT_TIMEOUT:-240}"

    session_request() {
      node -e '
        const http = require("http");
        const [method, path] = [process.argv[1], process.argv[2]];
        const req = http.request(
          { host: "browser", port: process.env.SESSION_SERVER_PORT || 8932, path, method,
            timeout: 5000, headers: { "X-Agent-Token": process.env.AGENT_API_TOKEN || "" } },
          (res) => {
            let body = "";
            res.on("data", (c) => (body += c));
            res.on("end", () => { process.stdout.write(body); process.exit(0); });
          }
        );
        req.on("timeout", () => { req.destroy(); process.exit(1); });
        req.on("error", () => process.exit(1));
        req.end(method === "POST" ? "{}" : undefined);
      ' "$1" "$2" 2>/dev/null
    }

    wait_for_session_release() {
      local waited=0
      while (( waited < SESSION_EVICT_TIMEOUT )); do
        local state
        state="$(session_request GET /session)" || return 1
        if ! grep -q '"open":true' <<<"$state"; then
          return 0
        fi
        sleep 5
        waited=$((waited + 5))
      done
      return 2
    }

    session_state="$(session_request GET /session)" \
      || abort "session server unreachable at browser:${SESSION_SERVER_PORT:-8932} - cannot tell whether a sign-in session holds the browser (docker compose logs browser)"

    if grep -q '"open":true' <<<"$session_state"; then
      log "an attended sign-in session is open - requesting the browser back"
      session_request POST /session/evict >/dev/null \
        || abort "session server unreachable while evicting the sign-in session"
      wait_for_session_release
      case $? in
        0) log "sign-in session released the browser" ;;
        1) abort "session server unreachable while waiting for the sign-in session to close" ;;
        2) abort "sign-in session did not release the browser within ${SESSION_EVICT_TIMEOUT}s" ;;
      esac
    fi
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_daily_apply_eviction.py -v`
Expected: PASS (4 tests)

Run: `bash -n agent/daily-apply.sh`
Expected: no output (syntax valid).

Run: `pytest`
Expected: 1028 passed, 2 skipped

- [ ] **Step 5: Commit**

```bash
git add agent/daily-apply.sh tests/test_daily_apply_eviction.py
git commit -m "feat: runs reclaim the browser from an open sign-in session"
```

---

### Task 8: Close the exposed ports

**Files:**
- Modify: `docker-compose.yml` (app `ports`, browser `ports`, agent/browser env)
- Modify: `launcher/ports.py:16`, `launcher/__main__.py:45`
- Modify: `README.md:53-55`, `browser/README.md`, `agent/README.md:24-29`
- Test: `tests/test_compose_exposure.py` (create); existing `tests/test_launcher_ports.py`

**Interfaces:**
- Consumes: the app-proxied viewport from Task 6.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the failing test**

Create `tests/test_compose_exposure.py`:

```python
"""The compose file must not publish a passwordless remote-control surface.

The noVNC viewport gives keyboard and mouse control of a browser holding the
operator's live ATS and email sessions, and x11vnc runs with -nopw. It is
reachable through the app's origin-checked relay instead.
"""

from __future__ import annotations

from pathlib import Path

import yaml

COMPOSE = yaml.safe_load(Path("docker-compose.yml").read_text())


def test_the_novnc_port_is_not_published():
    browser = COMPOSE["services"]["browser"]
    for entry in browser.get("ports", []):
        assert "7900" not in str(entry), f"noVNC must not be published: {entry}"


def test_the_session_server_port_is_not_published():
    browser = COMPOSE["services"]["browser"]
    for entry in browser.get("ports", []):
        assert "8932" not in str(entry), f"session server must not be published: {entry}"


def test_the_app_is_bound_to_loopback():
    """The app has no authentication; it must not listen on every interface."""
    ports = COMPOSE["services"]["app"]["ports"]
    assert len(ports) == 1
    assert str(ports[0]).startswith("127.0.0.1:"), ports[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_compose_exposure.py -v`
Expected: FAIL on all three.

- [ ] **Step 3: Close the ports**

In `docker-compose.yml`, in the `app` service replace:

```yaml
      - "${APP_PORT:-5627}:8080"
```

with:

```yaml
      # Loopback only. The app has NO user authentication — the sole guard in
      # api/routes.py is AGENT_API_TOKEN, and it protects one agent-facing
      # endpoint — and it now proxies a remote-control view of a browser
      # holding the operator's live sessions. Listening on every interface
      # would put both on the local network. The launcher opens localhost, so
      # this matches how it is actually reached.
      - "127.0.0.1:${APP_PORT:-5627}:8080"
```

In the `browser` service, delete the entire `ports:` block, including the noVNC comment above it, and replace it with:

```yaml
    # No published ports. noVNC (7900) and the session control server (8932)
    # are reached only from the `app` service over the compose network:
    # /api/browser/session/stream relays the viewport with an Origin check,
    # which a published passwordless VNC port would render pointless.
```

Add the session-server settings to the `browser` service's `environment:` block:

```yaml
      - SESSION_SERVER_PORT=${SESSION_SERVER_PORT:-8932}
      - AGENT_API_TOKEN=${AGENT_API_TOKEN:-}
      - AGENT_CONTROL_PORT=${AGENT_CONTROL_PORT:-9099}
      - SESSION_GRACE_MS=${SESSION_GRACE_MS:-180000}
```

Add to the `agent` service's `environment:` block:

```yaml
      # Where session-server.js listens, used by daily-apply.sh to reclaim the
      # browser from an attended sign-in session before a run.
      - SESSION_SERVER_PORT=${SESSION_SERVER_PORT:-8932}
```

Add to the `app` service's `environment:` block:

```yaml
      - SESSION_SERVER_PORT=${SESSION_SERVER_PORT:-8932}
      - BROWSER_NOVNC_PORT=${BROWSER_NOVNC_PORT:-7900}
```

- [ ] **Step 4: Drop the dead launcher port**

In `launcher/ports.py`, change line 16:

```python
DEFAULTS: dict[str, int] = {"APP_PORT": 5627, "NOVNC_HOST_PORT": 5628}
```

to:

```python
DEFAULTS: dict[str, int] = {"APP_PORT": 5627}
```

Then read the docstring at `launcher/ports.py:30` — it explains that an app port advancing past 5627 cannot land on the noVNC default. That reasoning no longer applies; rewrite the comment to describe only the app port rather than deleting the explanation wholesale.

In `launcher/__main__.py`, delete line 45:

```python
        "NOVNC_HOST_PORT": str(ports.default_for("NOVNC_HOST_PORT")),
```

Run `pytest tests/test_launcher_ports.py -v` and update any test that asserts on `NOVNC_HOST_PORT`. These tests are asserting the old behaviour deliberately, so change them to assert the new behaviour — do not delete them.

- [ ] **Step 5: Rewrite the docs**

Three files instruct the operator to visit `http://localhost:5628`. All three now describe the in-app flow.

`README.md:53-55` — replace the blockquote with:

```markdown
> container, not this one. Watch a run live, or do the one-time manual login
> an ATS needs (SSO, CAPTCHA, SMS MFA), from the **Agents page → Site
> sign-ins**. That login persists on the `browser-profile` volume, so it
> survives restarts and later runs reuse it.
```

`agent/README.md:24-29` — replace the blockquote with:

```markdown
> **A login-walled site (SSO, CAPTCHA, SMS MFA) needs a one-time manual
> sign-in.** Open **Agents → Site sign-ins** in TruthCV and click Sign in; a
> browser you can drive opens in the app. The session persists on the named
> volume `browser-profile`, so you should not need to sign in again. A run in
> progress takes priority — the button is refused while the agent is applying,
> and a run that starts during a session asks for the browser back with three
> minutes' notice. See [`browser/README.md`](../browser/README.md) for detail.
```

`browser/README.md` — replace the "noVNC Viewport" section's address and the "Manually complete any one-time login" mitigation bullet with the in-app route, and state that the port is no longer published. Keep the Profile Persistence, Data Volume and Bot Detection sections as they are.

Check no stale references remain:

```bash
grep -rn "5628\|NOVNC_HOST_PORT" --include="*.md" --include="*.py" --include="*.yml" . | grep -v node_modules | grep -v docs/superpowers
```

Expected: no results.

- [ ] **Step 6: Run the tests**

Run: `pytest tests/test_compose_exposure.py tests/test_launcher_ports.py tests/test_launcher_main.py -v`
Expected: PASS

Run: `pytest`
Expected: 1031 passed, 2 skipped

Note: `tests/test_doc_cross_references.py` may fail if a rewritten doc link no longer resolves. Read the failure and fix the link.

- [ ] **Step 7: Commit**

```bash
git add docker-compose.yml launcher/ports.py launcher/__main__.py README.md agent/README.md browser/README.md tests/test_compose_exposure.py tests/test_launcher_ports.py
git commit -m "fix: stop publishing the passwordless viewport, bind the app to loopback"
```

---

### Task 9: The Site sign-ins section on the Agents page

**Files:**
- Modify: `web/src/api/types.ts`
- Modify: `web/src/api/client.ts`
- Create: `web/src/agents/SigninSection.tsx`
- Modify: `web/src/agents/AgentsPage.tsx` (render the section)
- Modify: `web/src/routes.ts`
- Test: `web/src/agents/SigninSection.test.tsx` (create)

**Interfaces:**
- Consumes: `GET /api/browser/signin-queue` from Task 3.
- Produces: `SigninSection` component; `ROUTES.browserSession = "/browser-session"`; `browserSessionPath(url: string): string`; client functions `getSigninQueue()`, `getBrowserSession()`, `openBrowserSession(url)`, `closeBrowserSession()`; the error class `BrowserSessionError` carrying a numeric `status`.

- [ ] **Step 1: Write the failing test**

Create `web/src/agents/SigninSection.test.tsx`:

```tsx
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { SigninSection } from "./SigninSection";

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return { ...actual, useNavigate: () => mockNavigate };
});

function renderSection() {
  return render(
    <MemoryRouter>
      <SigninSection sources={["linkedin", "greenhouse"]} />
    </MemoryRouter>
  );
}

describe("SigninSection", () => {
  beforeEach(() => {
    mockNavigate.mockReset();
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ sites: [] }),
    })));
  });

  it("says nothing needs attention when the queue is empty", async () => {
    renderSection();
    await waitFor(() => {
      expect(screen.getByText(/no sites are waiting/i)).toBeTruthy();
    });
  });

  it("lists a blocked site with how many postings are waiting", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        sites: [{
          host: "acme.wd3.myworkdayjobs.com",
          signinUrl: "https://acme.wd3.myworkdayjobs.com/login",
          waiting: 4,
          lastBlockedAt: "2026-08-25T15:02:00Z",
          companies: ["Acme"],
        }],
      }),
    })));
    renderSection();
    await waitFor(() => {
      expect(screen.getByText(/acme\.wd3\.myworkdayjobs\.com/)).toBeTruthy();
    });
    expect(screen.getByText(/4 postings waiting/i)).toBeTruthy();
  });

  it("lists the configured job boards so they can be signed in to ahead of time", async () => {
    renderSection();
    await waitFor(() => {
      expect(screen.getByText(/linkedin/i)).toBeTruthy();
    });
  });

  it("shows no signed-in status for configured boards", async () => {
    // The agent's experience is the only source of truth, so claiming a board
    // is signed in would be an assertion nothing checks.
    renderSection();
    await waitFor(() => {
      expect(screen.getByText(/linkedin/i)).toBeTruthy();
    });
    expect(screen.queryByText(/signed in/i)).toBeNull();
  });

  it("navigates to the session page with the url when Sign in is clicked", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        sites: [{
          host: "acme.wd3.myworkdayjobs.com",
          signinUrl: "https://acme.wd3.myworkdayjobs.com/login",
          waiting: 1,
          lastBlockedAt: "2026-08-25T15:02:00Z",
          companies: ["Acme"],
        }],
      }),
    })));
    renderSection();
    const button = await screen.findByRole("button", {
      name: /sign in to acme\.wd3\.myworkdayjobs\.com/i,
    });
    button.click();
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith(
        expect.stringContaining("/browser-session")
      );
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix web run test -- SigninSection`
Expected: FAIL — cannot resolve `./SigninSection`.

- [ ] **Step 3: Add the types and client call**

In `web/src/api/types.ts`, append:

```ts
/** One host the agent could not get past a sign-in wall on. */
export type SigninQueueSite = {
  host: string;
  signinUrl: string;
  waiting: number;
  lastBlockedAt: string;
  companies: string[];
};

export type SigninQueue = { sites: SigninQueueSite[] };

/** State of the attended sign-in session, if one is open. */
export type BrowserSession = {
  open: boolean;
  url: string | null;
  startedAt: string | null;
  evictDeadline: string | null;
};
```

In `web/src/api/client.ts`, add `SigninQueue` and `BrowserSession` to the type import block at the top, then append:

```ts
/** Sites the agent could not get past a sign-in wall on. */
export function getSigninQueue(): Promise<SigninQueue> {
  return request("/api/browser/signin-queue");
}

/** Whether an attended sign-in session is open, and at which URL. */
export function getBrowserSession(): Promise<BrowserSession> {
  return request("/api/browser/session");
}

/** Close the attended session and release the browser. */
export function closeBrowserSession(): Promise<void> {
  return request<void>("/api/browser/session", { method: "DELETE" });
}

/** Raised by openBrowserSession so the session page can tell the three
 * outcomes apart. `request` collapses every failure into one message, which
 * is right for the wizard but wrong here: "the agent is busy" and "the
 * browser is broken" call for different words and different buttons. */
export class BrowserSessionError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "BrowserSessionError";
    this.status = status;
  }
}

/** Open an attended sign-in session at a URL.
 *
 * Deliberately does not go through `request`: this is the one call whose
 * status code the caller must branch on (409 = a run is in progress). */
export async function openBrowserSession(url: string): Promise<BrowserSession> {
  let res: Response;
  try {
    res = await fetch("/api/browser/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
  } catch {
    throw new BrowserSessionError(0, "Can't reach the server. Check that TruthCV is running, then try again.");
  }
  if (!res.ok) {
    const detail = await res
      .json()
      .then((b) => errorDetailToMessage(b))
      .catch(() => "");
    throw new BrowserSessionError(res.status, detail || `That didn't work (error ${res.status}).`);
  }
  return (await res.json()) as BrowserSession;
}
```

- [ ] **Step 4: Add the route constant**

In `web/src/routes.ts`, add to `ROUTES`:

```ts
  browserSession: "/browser-session",
```

and below `filledFormPath`:

```ts
/** Builds the URL for signing in to a site in the in-app browser session. */
export function browserSessionPath(url: string): string {
  return `/browser-session?url=${encodeURIComponent(url)}`;
}
```

- [ ] **Step 5: Write the section**

Create `web/src/agents/SigninSection.tsx`:

```tsx
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Alert, Button, Divider, Paper, Stack, Typography } from "@mui/material";

import { getSigninQueue } from "../api/client";
import type { SigninQueueSite } from "../api/types";
import { browserSessionPath } from "../routes";

/** Sign-in landing pages for the platforms agentconfig/dorks.py can target.
 * Kept in step with SOURCE_DOMAINS there — a source missing here simply gets
 * no proactive row, which is a gap in convenience, never in correctness. */
const SOURCE_SIGNIN_URLS: Record<string, string> = {
  linkedin: "https://www.linkedin.com/login",
  ashby: "https://jobs.ashbyhq.com",
  greenhouse: "https://job-boards.greenhouse.io",
  lever: "https://jobs.lever.co",
  personio: "https://jobs.personio.de",
  workday: "https://www.myworkdayjobs.com",
};

function hostLabel(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** Sites needing a manual sign-in: the ones the agent was actually blocked by,
 * and the boards this operator's profiles target.
 *
 * There is deliberately no signed-in indicator. The agent's experience is the
 * only source of truth, so a tick here would be an assertion nothing checks —
 * and a stale one would send the operator looking in the wrong place. */
export function SigninSection({ sources }: { sources: string[] }) {
  const navigate = useNavigate();
  const [sites, setSites] = useState<SigninQueueSite[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    getSigninQueue()
      .then((q) => live && setSites(q.sites))
      .catch((e: Error) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, []);

  const boards = sources.filter((s) => SOURCE_SIGNIN_URLS[s]);

  return (
    <Paper variant="outlined" sx={{ p: 3 }}>
      <Stack spacing={2}>
        <Stack spacing={0.5}>
          <Typography variant="h6">Site sign-ins</Typography>
          <Typography variant="body2" color="text.secondary">
            Some job sites need you to sign in once. The session is saved and
            reused by every later run.
          </Typography>
        </Stack>

        {error && <Alert severity="error">{error}</Alert>}

        <Typography variant="subtitle2">Needs attention</Typography>
        {sites && sites.length === 0 && (
          <Typography variant="body2" color="text.secondary">
            No sites are waiting on a sign-in.
          </Typography>
        )}
        {sites?.map((site) => (
          <Stack
            key={site.host}
            direction="row"
            spacing={2}
            alignItems="center"
            justifyContent="space-between"
          >
            <Stack spacing={0.25}>
              <Typography variant="body2">{site.host}</Typography>
              <Typography variant="caption" color="text.secondary">
                {site.waiting} {site.waiting === 1 ? "posting" : "postings"} waiting
                {site.companies.length > 0 && ` · ${site.companies.join(", ")}`}
                {hostLabel(site.lastBlockedAt) && ` · last blocked ${hostLabel(site.lastBlockedAt)}`}
              </Typography>
            </Stack>
            <Button
              variant="contained"
              size="small"
              onClick={() => navigate(browserSessionPath(site.signinUrl))}
            >
              Sign in to {site.host}
            </Button>
          </Stack>
        ))}

        <Divider />

        <Typography variant="subtitle2">Your job boards</Typography>
        <Typography variant="body2" color="text.secondary">
          Sign in ahead of time if you like. There is no status here — TruthCV
          only learns a site needs a sign-in when the agent is actually blocked
          by one.
        </Typography>
        {boards.map((source) => (
          <Stack
            key={source}
            direction="row"
            spacing={2}
            alignItems="center"
            justifyContent="space-between"
          >
            <Typography variant="body2">{source}</Typography>
            <Button
              variant="outlined"
              size="small"
              onClick={() => navigate(browserSessionPath(SOURCE_SIGNIN_URLS[source]))}
            >
              Sign in to {source}
            </Button>
          </Stack>
        ))}
      </Stack>
    </Paper>
  );
}
```

- [ ] **Step 6: Render it on the Agents page**

In `web/src/agents/AgentsPage.tsx`, import `SigninSection` and render it alongside the other sections, passing the enabled profiles' `preferred_sources` deduplicated:

```tsx
<SigninSection
  sources={Array.from(
    new Set(
      (config.profiles ?? [])
        .filter((p) => p.enabled)
        .flatMap((p) => p.preferredSources ?? []),
    ),
  )}
/>
```

Check the exact field names against `web/src/api/types.ts` before writing this — if the profile type spells them differently, use its spelling rather than adding a second one.

- [ ] **Step 7: Run the tests**

Run: `npm --prefix web run test -- SigninSection`
Expected: PASS (5 tests)

Run: `npm --prefix web run typecheck`
Expected: no errors.

Run: `npm --prefix web run test`
Expected: 226 passed.

- [ ] **Step 8: Commit**

```bash
git add web/src/api/types.ts web/src/api/client.ts web/src/routes.ts web/src/agents/SigninSection.tsx web/src/agents/SigninSection.test.tsx web/src/agents/AgentsPage.tsx
git commit -m "feat: Site sign-ins section on the Agents page"
```

---

### Task 10: The session page

**Files:**
- Create: `web/src/browser/BrowserSessionPage.tsx`
- Modify: `web/src/App.tsx` (register the route)
- Modify: `web/package.json` (add `@novnc/novnc`)
- Test: `web/src/browser/BrowserSessionPage.test.tsx` (create)

**Interfaces:**
- Consumes: `openBrowserSession(url)`, `getBrowserSession()`, `closeBrowserSession()` and `BrowserSessionError` (with `.status`) from Task 9; `browserSessionPath` / `ROUTES.browserSession` from Task 9; `WS /api/browser/session/stream` from Task 6.
- Produces: the page at `ROUTES.browserSession`.

- [ ] **Step 1: Add the dependency**

Run: `npm --prefix web install @novnc/novnc`

- [ ] **Step 2: Write the failing test**

Create `web/src/browser/BrowserSessionPage.test.tsx`:

```tsx
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { BrowserSessionPage } from "./BrowserSessionPage";

vi.mock("@novnc/novnc/lib/rfb", () => ({
  default: class {
    addEventListener() {}
    disconnect() {}
  },
}));

function renderPage(url = "https://example.com/login") {
  return render(
    <MemoryRouter initialEntries={[`/browser-session?url=${encodeURIComponent(url)}`]}>
      <BrowserSessionPage />
    </MemoryRouter>
  );
}

describe("BrowserSessionPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ open: true, url: "https://example.com/login", startedAt: "x", evictDeadline: null }),
    })));
  });

  it("shows a starting state before the session is open", () => {
    renderPage();
    expect(screen.getByText(/starting/i)).toBeTruthy();
  });

  it("shows the site host once the session is live", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("example.com")).toBeTruthy();
    });
  });

  it("explains that the agent is busy when the session is refused with 409", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: false,
      status: 409,
      json: async () => ({ detail: "Session refused" }),
    })));
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/agent is applying right now/i)).toBeTruthy();
    });
  });

  it("counts down when a run has asked for the browser back", async () => {
    const deadline = new Date(Date.now() + 165000).toISOString();
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ open: true, url: "https://example.com/login", startedAt: "x", evictDeadline: deadline }),
    })));
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/the agent needs the browser in 2:4/i)).toBeTruthy();
    });
  });

  it("does not claim the sign-in succeeded when closed", async () => {
    renderPage();
    const done = await screen.findByRole("button", { name: /done/i });
    done.click();
    await waitFor(() => {
      expect(screen.getByText(/if it worked, the next run will get through/i)).toBeTruthy();
    });
    expect(screen.queryByText(/signed in/i)).toBeNull();
  });

  it("reports when the browser service is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: false,
      status: 503,
      json: async () => ({ detail: "Browser service unreachable" }),
    })));
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/browser is unavailable/i)).toBeTruthy();
    });
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `npm --prefix web run test -- BrowserSessionPage`
Expected: FAIL — cannot resolve `./BrowserSessionPage`.

- [ ] **Step 4: Write the page**

Create `web/src/browser/BrowserSessionPage.tsx`:

```tsx
import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Alert, AppBar, Box, Button, Stack, Toolbar, Typography } from "@mui/material";
import RFB from "@novnc/novnc/lib/rfb";

import {
  BrowserSessionError,
  closeBrowserSession,
  getBrowserSession,
  openBrowserSession,
} from "../api/client";
import { ROUTES } from "../routes";

type State = "starting" | "live" | "refused" | "unavailable" | "closed";

function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

/** Seconds remaining until an eviction deadline, floored at zero. */
function secondsLeft(deadline: string): number {
  const ms = Date.parse(deadline) - Date.now();
  return ms > 0 ? Math.ceil(ms / 1000) : 0;
}

function mmss(total: number): string {
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

/** The attended sign-in viewport.
 *
 * The noVNC socket is same-origin (`/api/browser/session/stream`) and the
 * server rejects any other Origin — the browser container's own port is not
 * published, so this is the only route to it. */
export function BrowserSessionPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const url = params.get("url") || "";
  const [state, setState] = useState<State>("starting");
  const [message, setMessage] = useState("");
  const [deadline, setDeadline] = useState<string | null>(null);
  const [remaining, setRemaining] = useState(0);
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const rfbRef = useRef<RFB | null>(null);

  // Open the session once on mount.
  useEffect(() => {
    let live = true;
    openBrowserSession(url)
      .then((s) => {
        if (!live) return;
        setState("live");
        setDeadline(s.evictDeadline);
      })
      .catch((e: BrowserSessionError) => {
        if (!live) return;
        if (e.status === 409) {
          setState("refused");
          setMessage("The agent is applying right now. Try again in a few minutes.");
        } else {
          setState("unavailable");
          setMessage("The browser is unavailable.");
        }
      });
    return () => {
      live = false;
    };
  }, [url]);

  // Attach noVNC once the session is live.
  useEffect(() => {
    if (state !== "live" || !canvasRef.current || rfbRef.current) return;
    const wsUrl = `${location.origin.replace(/^http/, "ws")}/api/browser/session/stream`;
    const rfb = new RFB(canvasRef.current, wsUrl);
    rfb.addEventListener("disconnect", () => setState("closed"));
    rfbRef.current = rfb;
    return () => {
      rfb.disconnect();
      rfbRef.current = null;
    };
  }, [state]);

  // Poll for an eviction the run may have requested.
  useEffect(() => {
    if (state !== "live") return;
    const id = setInterval(() => {
      getBrowserSession()
        .then((s) => {
          if (!s.open) setState("closed");
          else setDeadline(s.evictDeadline);
        })
        .catch(() => setState("unavailable"));
    }, 5000);
    return () => clearInterval(id);
  }, [state]);

  // Tick the countdown once a deadline exists.
  useEffect(() => {
    if (!deadline) {
      setRemaining(0);
      return;
    }
    setRemaining(secondsLeft(deadline));
    const id = setInterval(() => setRemaining(secondsLeft(deadline)), 1000);
    return () => clearInterval(id);
  }, [deadline]);

  async function onDone() {
    try {
      await closeBrowserSession();
    } catch {
      // The session is going away either way; the operator does not need to
      // hear about a failure to close something they are finished with.
    }
    setState("closed");
  }

  const back = (
    <Button onClick={() => navigate(ROUTES.agents)}>Back to Agents</Button>
  );

  if (state === "starting") {
    return (
      <Stack spacing={2} sx={{ p: 3 }}>
        <Typography>Starting the browser…</Typography>
      </Stack>
    );
  }

  if (state === "refused" || state === "unavailable") {
    return (
      <Stack spacing={2} sx={{ p: 3 }}>
        <Alert severity={state === "refused" ? "info" : "error"}>{message}</Alert>
        {back}
      </Stack>
    );
  }

  if (state === "closed") {
    return (
      <Stack spacing={2} sx={{ p: 3 }}>
        {/* Deliberately not a success message. Nothing here checks whether the
            sign-in worked — only the next run finds out. */}
        <Typography>
          Closed. If it worked, the next run will get through; if not, this site
          will show up here again.
        </Typography>
        {back}
      </Stack>
    );
  }

  return (
    <Stack sx={{ height: "100%" }}>
      <AppBar position="static" color="default" elevation={0}>
        <Toolbar sx={{ gap: 2 }}>
          <Typography variant="subtitle1" sx={{ flexGrow: 1 }}>
            {hostOf(url)}
          </Typography>
          <Button size="small" onClick={() => rfbRef.current?.disconnect()}>
            Reload
          </Button>
          <Button size="small" variant="contained" onClick={onDone}>
            Done
          </Button>
        </Toolbar>
      </AppBar>
      {deadline && (
        <Alert severity="warning">
          The agent needs the browser in {mmss(remaining)} — finish up.
        </Alert>
      )}
      <Box ref={canvasRef} sx={{ flexGrow: 1, minHeight: 480, bgcolor: "black" }} />
    </Stack>
  );
}
```

- [ ] **Step 5: Register the route**

In `web/src/App.tsx`, add a `<Route path={ROUTES.browserSession} element={<BrowserSessionPage />} />` following the existing route registrations. Do NOT add it to `SideNav` — it is reached from the Agents page, as `/applications/:id/filled-form` is.

- [ ] **Step 6: Run the tests**

Run: `npm --prefix web run test -- BrowserSessionPage`
Expected: PASS (6 tests)

Run: `npm --prefix web run typecheck`
Expected: no errors.

Run: `npm --prefix web run test`
Expected: 232 passed.

Run: `pytest`
Expected: 1031 passed, 2 skipped.

- [ ] **Step 7: Manual end-to-end check**

This is the only way to see the feature work; nothing above proves the viewport actually renders.

```bash
docker compose up -d --build
```

Open `http://localhost:5627`, go to **Agents → Site sign-ins**, click Sign in on a configured board. Confirm: the browser appears in the page, you can type in it, an SSO popup can be raised and moved (this is what openbox buys), Done returns you to Agents, and `docker compose exec browser sh -c 'ps -eo comm= | sort -u'` shows no `chrome` afterwards.

Then confirm the interlock: with a session open, run `curl -X POST localhost:5627/api/agent/run` and watch the countdown appear and the session close.

- [ ] **Step 8: Commit**

```bash
git add web/package.json web/package-lock.json web/src/browser/BrowserSessionPage.tsx web/src/browser/BrowserSessionPage.test.tsx web/src/App.tsx
git commit -m "feat: in-app browser session page for manual sign-in"
```

---

## Notes for the executor

**What is not verified anywhere in this plan:** an actual sign-in against a real
employer, and the platform login assumptions in the spec's "Which sites need a
sign-in" table. Both need a human with a real account. Task 10 Step 7 is the
closest this gets.

**If Task 4 Step 7 shows Chromium already running** when no run is in progress,
stop and investigate before continuing — the whole design rests on the profile
being free while idle, and that measurement is what established it.

**The Done copy in Task 10 and the "no status" caption in Task 9** are load-bearing,
not placeholder wording. They exist because nothing in this system checks
whether a sign-in worked, and stronger wording would be a claim the code cannot
support.
