# Agent autonomy modes

The operator chooses how much the agent decides alone: off, semi-auto (find and
queue, the operator drafts and approves), or full auto (find and apply). One
three-stop control on the Agents page.

## Why

The agent has exactly one behaviour today: it applies the moment a posting
passes every criterion, and queues only what it could not decide. The operator
sees the letter that went out after it went out, in a run log. There is no
setting between "submits on its own" and "switched off", and no point at which
the operator can read the posting and the letter and change either before an
application reaches a real employer under their real name.

Semi-auto is that point. It costs a scheduled run of latency — approve today,
apply on the next run — which is the existing approval queue's behaviour and is
deliberate: the agent applies from a decision the operator already made, never
from one made mid-run.

## The three modes

| Mode | Discovery | Passing posting | Deferred posting |
|---|---|---|---|
| `off` | none — the run exits | — | — |
| `semi` | yes | queued for the operator; no letter written | queued, no letter |
| `full` | yes | applied to immediately | queued (unchanged) |

Phase 0 is identical in `semi` and `full`: every run starts by applying to what
the operator approved since the last one. Approval is what licenses an
application, and it is granted between runs in both modes.

`off` is not "pause discovery" — the run exits before the model is invoked at
all, exactly as the current `enabled: false` gate does.

**The agent never drafts a letter in `semi`.** Drafting is an operator action,
taken per posting, from the Approvals page. In `full` the agent still generates
its own letter at apply time through `generate_cover_letter`, guardrailed,
exactly as today; nothing about that path changes.

## The operator's sequence in semi-auto

For one queued posting, in order:

1. Read the posting, the posted date, and the date it was found.
2. Press **Generate cover letter**. Nothing is drafted before this.
3. Optionally edit the generated text and save it.
4. **Approve** or **Reject**.

Approve is unavailable until a letter exists — the agent applies with the stored
text verbatim, so approving without one would queue an application with nothing
to send. Reject is available at every step, including before generating.

## Data model

### AgentConfig

One new field, `mode: str = "full"`, persisted in `data/agent_config.json`.

`enabled` stops being persisted and becomes **derived** — `mode != "off"` — on
the wire model and in `to_dict()`. Every current consumer keeps working
untouched: `agent/agent-config.js enabled`, `daily-apply.sh`'s fail-closed
enable gate, `RunNowSection`, and the `AgentConfigModel` field the Agents page
already reads.

Migration lives in `AgentConfig.from_dict`: a stored config with `enabled` and
no `mode` reads as `"full"` when `enabled` is true and `"off"` when false.
Existing installations therefore keep exactly the behaviour they have now, which
is full auto. An unknown `mode` value falls back to `"full"` for the same
reason `from_dict` already falls back per-key on a wrong type — a malformed
config must not silently disable the agent.

`PUT /api/agent/config` accepts `mode` and rejects `enabled` as a writable
field: two writers for one piece of state is how they diverge.

### Screening

Two fields, both in `EDITABLE` so `record_screening(**fields)` can set them:

- `posting_text: str` — the posting as the agent read it. Stored because the
  operator drafts the letter from it later, in the app, long after the run that
  found it; without it, drafting would mean re-fetching a page that may be
  unreachable. Several boards in the existing history (Dealfront's careers page
  and its Workable board among them) could not be reached on five consecutive
  runs; a design that depends on re-fetching would fail on exactly those.
- `posted_date: str` — the employer's publication date, best-effort. Empty when
  the board does not publish one, which is common. Never inferred.

`found_date` is **not** added: `screened_date` already carries it.

`approval` stays out of `EDITABLE`. That is the invariant making "the human
approves, the agent never does" structural rather than instructional, and it is
asserted by `tests/test_approvals_api.py::test_no_agent_route_writes_approval`.

### CoverLetterDraft

A new store, `coverletter/store.py`, one JSON file per screening at
`data/letters/{screening_id}.json`:

```
{ "text": str, "paragraphs": list[dict], "source": "generated" | "operator", "updated_at": str }
```

Separate from `screenings.json` because the letter is rewritten repeatedly and
is one to two orders of magnitude larger than the record it belongs to; folding
it in would make the file the whole system loads on every screening read.

`paragraphs` is kept because `coverletter.generate.build_letter` accepts it to
re-validate or re-render a letter without a second LLM call.

`source` distinguishes guardrailed text from text the operator altered.
`"generated"` means it is exactly what `generate_cover_letter` produced and
validated; `"operator"` means a human rewrote it and the guardrail no longer
vouches for it. The distinction is the audit trail and is shown in the UI.

Writes are atomic (tmp + replace), matching every other store on the volume.

## The guardrail boundary

`PUT /api/screenings/{id}/letter` saves the operator's text **verbatim, with no
guardrail validation**.

This is a deliberate hole in an otherwise absolute rule, and it is consistent
with the rule it appears to break. `guardrail/validate.py` exists to stop the
*agent* asserting facts it cannot ground in the operator's truth document. The
operator is the source of that document. A claim they type is, by definition,
one they are asserting on their own behalf — the same authority the wizard's
claim-approval flow already grants them.

What follows from it, and must be stated wherever this route is documented:

- Text saved through this route reaches an employer exactly as typed.
- `source: "operator"` marks such a draft permanently. The agent applies with it
  verbatim and never regenerates over it.
- Generation itself is unchanged: `POST .../letter` runs
  `generate_cover_letter`, which still validates, still blocks, and still
  exposes no parameter that could approve a claim. A blocked generation returns
  the blocked claims and writes no draft.

## API

| Route | Purpose |
|---|---|
| `GET /api/screenings/{id}/letter` | Read the stored draft; 404 when none exists |
| `POST /api/screenings/{id}/letter` | Generate from `posting_text`; 409 when it is empty, or when the stored draft is `source: "operator"` and `force` was not sent |
| `PUT /api/screenings/{id}/letter` | Save operator-edited text verbatim, sets `source: "operator"` |

`POST` is the **Generate cover letter** button. It is also the redraft path:
regeneration never silently discards operator text, so it refuses when the
stored draft is the operator's unless the caller sends `force: true`, which the
UI sends only from an explicit "Discard my edits and redraft" action. A record
whose `posting_text` is empty — every imported one — gets a 409, and the UI says
the posting text is missing rather than offering a button that cannot work.

`PATCH /api/screenings/{id}` gains one guard: setting `approval: "approved"` on
a screening with no stored draft returns 409. The button is disabled in the UI
for the same reason, but the rule belongs on the server, where it also covers
the bulk route — `PATCH /screenings/approvals` skips such an item and reports it
in its per-id results, which is what that route's per-id shape is for.

Moving a posting back to the queue — from either the did-not-pass list or the
rejected list — is the existing `PATCH /api/screenings/{id}` with
`approval: "pending"`. No new route: it is an approval-state change, and that
route already owns approval state. Any draft the item already had is kept.

These sit outside `/api/agent/*`, where the agent's token authenticates, so the
agent cannot reach any of them.

## Agent run loop

`daily-apply.sh` fetches `mode` next to the schedule and branches:

- `off` → log and exit 0, before the model is invoked. This replaces reading
  `enabled`; an unreachable config still aborts, fail-closed.
- `semi` / `full` → the mode and its rule are rendered into the prompt, from the
  config, the same way the profile criteria block already is.

In `semi`, the agent's instruction for a posting that passes every criterion is:
do not apply and do not draft — call `record_screening` with
`verdict: "passed"`, the posting text, and the posted date.

**The queueing is enforced server-side, not by the prompt.** In
`screening.store.create`, when the mode is `semi` and the verdict is `passed`,
`approval` is set to `"pending"` — exactly where and why `verdict == "deferred"`
already does. A model that ignores the instruction and applies anyway is a
separate failure, but it cannot cause the record to skip the queue.

`get_approved_applications` returns the stored letter text with each item. The
agent applies with that text verbatim and does not regenerate — regenerating
would discard the operator's edit, which is the entire point of the mode. Every
approved item has a draft, because approval without one is refused.

No new agent tool and no new tool grant: `record_screening(**fields)` already
forwards arbitrary fields, and the two new ones ride along on the call the agent
already makes.

## UI

**Agents page.** The `enabled` `Switch` becomes a three-stop `Slider` with marks
(Off / Semi-auto / Full auto), keeping the existing optimistic-update-and-revert
behaviour: move immediately, PUT, revert on failure. The helper text names what
each stop does, because "semi-auto" alone does not say who applies or when.

**Approvals page.** Three sections.

*Needs approval* — company, role, posted date, found date, the posting in a
collapsible block, and one of: a **Generate cover letter** button when no draft
exists, or the draft in an editable field with Save, labelled with whether the
text is as generated or operator-edited. Then Approve — disabled until a draft
exists, with the reason stated — and Reject, always available. Plus the existing
Approve company control and the URL field for a record that has none.

*Did not pass* — postings the agent rejected on a criterion: company, role,
failing criterion, reason, and **Move to approvals**.

*Rejected* — postings the operator rejected: the same fields plus **Move to
approvals**, which returns the item to the queue with any draft it already had.

The two lists are kept apart rather than merged behind a badge. They differ in
volume and in meaning — the agent rejects nine postings in a run on hard
criteria, while an operator rejection is a decision worth being able to find
again — and merging them would bury the small list in the large one.

## Testing

- `AgentConfig.from_dict` migration: `enabled: true` → `full`, `false` → `off`,
  an explicit `mode` wins over a stale `enabled`, an unknown mode → `full`.
- `screening.store.create` queues a `passed` verdict in `semi` and does not in
  `full`; `deferred` queues in both.
- Letter store round-trip; an operator save overwrites a generated draft and
  flips `source`; `POST` over an operator draft is refused without `force` and
  succeeds with it.
- The three letter routes, including 409 on empty `posting_text` and 404 on a
  missing draft.
- Approving a screening with no draft returns 409, single and bulk; approving
  one with a draft still succeeds.
- Moving a rejected screening back to `pending` keeps its draft.
- `get_approved_applications` returns the operator's edited text verbatim.
- `daily-apply.sh` renders the mode rule for `semi` and `full`, and exits 0
  without invoking the model for `off`.
- Frontend: the slider writes `mode`; all three lists render; generate, edit,
  save; Approve disabled until a draft exists; both move-back paths.
- The existing `test_no_agent_route_writes_approval` invariant must keep
  passing unchanged.

## Cost

Drafting is opt-in and per posting, so a run that queues ten candidates writes
zero letters. The LLM cost lands only where the operator asks for it, and a
posting rejected without generating costs nothing.

`MAX_APPLICATIONS_PER_RUN` continues to cap applications. It has nothing to cap
here: no drafting happens on a run.

## Out of scope

- Making `CompanyBoard.approved` do anything. It is currently written and never
  read; that gap predates this work and is unrelated to it.
- Backfilling `url` or `posting_text` on the 117 imported screenings. Their
  source, `SCREENING_LOG.md`, is prose with no URL column and no posting text —
  there is nothing to backfill from.
- Per-profile modes. One mode governs the agent.
- Scheduling a run at approval time. Approval is honoured on the next scheduled
  run, as it is today.
