# Application approvals

The agent discovers and screens continuously. Roles it cannot decide alone wait
in a queue the operator reviews; approved ones are applied to on the next
scheduled run.

## Why

The agent applies immediately when a role passes every criterion, and abandons
the role when one is unverifiable. The 2026-08-23 19:09 run deferred three roles
that way — a Grafana Labs staff role at €109k–€137k among them — because it
could not verify the German hiring entity from non-browser fetches. Nothing
carried those decisions to the operator except prose in a run log, and nothing
carried the operator's answer back to the next run.

## Two kinds of approval, kept apart

The tool surface deliberately exposes no way for the agent to approve an
unverifiable claim (`agent/prompt.md` §"The approve/deny boundary",
`agent/RUNBOOK.md` §6). That boundary is unchanged and unchangeable here.

This feature adds a second, unrelated kind:

| | Claim approval | Application approval |
|---|---|---|
| Approves | An unverifiable fact in a letter | Applying to a posting |
| Who | Operator, in the wizard | Operator, on the Approvals page |
| Agent access | None, ever | Reads the decision; never grants it |

The prompt and runbook must state the distinction explicitly. An agent that
learns "approvals exist now" and generalises to claim approval is the failure
this section prevents.

## Approval semantics

**Posting approval** — apply, skipping the screening judgements that caused the
deferral. Two checks still bind and are not overridable:

- **Cooldown.** Prevents a duplicate application to a company applied to
  recently.
- **Cover-letter truthfulness.** `generate_cover_letter` blocking on
  unverifiable claims is untouched. Approval means "apply to this posting", not
  "assert anything needed to get in".

**Company approval** — weaker, and deliberately so: the operator vetted the
employer, not the role. It clears deferral blockers (unverified entity,
unverifiable Glassdoor) for any role at that company. Every role still passes
salary, remote, country and role-type screening.

## Data model

### Screening

Three fields, added to `Screening` and to `EDITABLE`:

| Field | Values | Meaning |
|---|---|---|
| `approval` | `""`, `pending`, `approved`, `rejected`, `applied` | `""` = not an approval item |
| `apply_attempts` | int, default 0 | Incremented per failed attempt |
| `apply_error` | str | Last failure, shown on the page |

`record_screening(verdict="deferred")` sets `approval="pending"` server-side.
The agent never writes `approval`. Existing `deferred` records are queue
entries as they stand; no migration.

`Screening` thereby stops being a pure audit record and gains mutable state.
Accepted deliberately: a `deferred` screening already denotes an unresolved
decision rather than a finished verdict.

### CompanyBoard

One field: `approved: bool = False`.

`companyboards.store.record()` currently rebuilds the entry from its arguments.
It must **merge** onto the existing entry instead, or the agent re-recording a
board silently un-approves the company. This is the single most likely defect
in the feature and has its own test.

`record_company_board` takes no `approved` parameter, so the agent cannot set
it — the same structural guarantee used for `Screening.approval`.

## API

| Route | Purpose |
|---|---|
| `GET /api/screenings?approval=pending` | The queue, and the nav badge count |
| `PATCH /api/screenings/{id}` | Sets `approval` only. 404 unknown id, 422 bad value |
| `PATCH /api/screenings/approvals` | Bulk: `{ids: [...], approval: ...}`, per-id results |
| `PATCH /api/company-boards/{company}` | Sets `approved` only |

These sit outside `/api/agent/*`, which is where the agent's `X-Agent-Token`
authenticates. The agent cannot reach them. That is what makes "the human
approves" structural rather than instructional, and it is asserted by test.

Bulk returns per-id outcomes rather than failing wholesale, so a partial
failure is visible instead of silent.

`PATCH /api/screenings/approvals` must be declared **before**
`PATCH /api/screenings/{id}`, or the router binds `approvals` as an id and the
bulk route becomes unreachable.

## Agent run loop

A new **Phase 0**, before discovery: work the approved queue first, because
those postings are already vetted and should get the browser budget ahead of
speculative screening.

Two new tools (nine → ten; `test_mcp_tools_list_returns_nine_tools` updates):

- **`get_approved_applications()`** — read-only. Returns approved items with
  company, role, url, screening id.
- **`report_apply_failure(screening_id, error)`** — increments
  `apply_attempts`, sets `apply_error`. Cannot touch `approval`.

`record_application` gains an optional `screening_id`. When supplied, the
server transitions that screening to `applied`. The agent never selects that
transition; it follows from a confirmed application.

### The double-submit hazard

Retrying indefinitely (the chosen failure policy) means a submission that
succeeded but whose confirmation capture failed would be re-applied. Therefore
`get_approved_applications` filters **server-side**:

- Any item whose URL already appears in the applications ledger is excluded.
- Any item whose company is in cooldown is returned flagged with
  `blocked_reason`, not omitted — so the agent reports it and the operator sees
  why it did not go out.

Server-side because the agent cannot then get it wrong by reasoning badly.

### Failure policy

A failed apply increments attempts, records the error, and stays queued for the
next run. Dead postings therefore retry until removed by hand; the page shows
attempt count and last error so they are visible. This is the operator's chosen
trade-off, taken to keep transient failures — like the browser outage of
2026-08-23 — self-healing.

## UI

A new top-level **Approvals** page beside Agents and Screenings.

- Lists `approval=pending`: company, role, linked URL, and the agent's recorded
  `failing_criterion` and `reason`.
- **Approve** / **Reject** per row; checkboxes and select-all for bulk.
- Approved-but-not-yet-applied items remain visible with attempt count and last
  error, giving the manual drain for permanently failing postings.
- Empty state is the normal state: "Nothing waiting."
- Nav badge shows the pending count.

Rejecting sets `approval="rejected"`; the record stays as ordinary screening
history and leaves the queue permanently.

Each pending item names its company with an "approve this company" toggle
alongside the per-posting actions, so the operator can grant the weaker
company-level trust without leaving the queue.

## Testing

- **Store/model** — field defaults; `deferred` → `pending`; `EDITABLE`
  round-trip; `companyboards.record()` preserves `approved` across re-records.
- **API** — PATCH transitions; the `approval` filter; 404 and 422 paths; bulk
  partial-failure reporting; and that an `X-Agent-Token` request cannot reach
  any approval-writing route.
- **Hazards** — an already-applied URL is excluded from the queue; a
  cooldown company is returned flagged rather than absent.
- **Semantics** — company approval clears deferral blockers but does not bypass
  salary/remote/country/role-type screening.
- **Tool surface** — ten tools listed with correct schemas;
  `report_apply_failure` cannot alter `approval`.
- **Frontend** — pending list renders; approve/reject and bulk call through;
  empty state; failure detail visible; badge count matches the filter.

## Out of scope

Email or push notification of new queue items (in-app badge only). Expiry of
approvals. Approving a role type or salary band rather than a company.
