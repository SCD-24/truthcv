# Gmail Sync — Design

Date: 2026-08-18
Status: Approved design, not yet implemented

## Purpose

Match employer reply emails in the operator's Gmail inbox to entries in the
application tracker, and turn them into reviewable suggestions — "this email
looks like a rejection for Acme — Backend Engineer" — that the operator accepts
or dismisses. Accepting a suggestion sets `response_received`, applies a
suggested status, and records provenance. Nothing changes in the tracker
without an explicit accept.

## Decisions (settled with the operator)

- **Access**: Gmail REST API with OAuth, `gmail.readonly` scope only.
- **Trigger**: on-demand ("Sync now") plus an automatic sync on Applications
  page load, throttled server-side to once per hour. No background jobs.
- **Write mode**: propose-and-confirm. Sync produces suggestions; the tracker
  changes only on operator accept.
- **Classification**: matched emails are classified by the app's existing LLM
  provider layer (rejection / interview invite / offer / automated
  confirmation / other) and mapped to a suggested status.

## Out of scope

Sending mail, writing anything to Gmail, syncing labels or folders,
multi-account support, background daemons or schedulers in the app service,
and auto-applying matches without confirmation.

## Architecture

Four pieces, all inside the existing `app` service:

1. A **Gmail connection** following the provider-connections pattern
   (`docs/superpowers/specs/2026-08-17-llm-provider-connections-design.md`).
2. A **sync engine** in a new `gmailsync/` package: fetch → match → classify →
   suggestions file.
3. **API routes** in `api/routes.py` for sync, suggestion listing, and
   accept/dismiss, with a `save_reply` helper in `applications/store.py`.
4. **UI** on the Applications page: auto-sync, Sync now button, and a
   suggestion review strip.

The agent container is not involved and never holds Gmail tokens.

## 1. Gmail connection

- New `gmail` card in `connections/catalog.py`, rendered as an Accounts card in
  the Settings modal (`web/src/settings/AccountsSection.tsx`).
- New `connections/auth/gmail.py` implementing the Google browser-redirect
  flow already designed for the `antigravity` card in the provider-connections
  spec: authorization redirect with `access_type=offline&prompt=consent`,
  scope `https://www.googleapis.com/auth/gmail.readonly`, callback at
  `GET /api/auth/gmail/callback`. Pending OAuth state (verifier, `state`)
  lives in module memory, never persisted.
- Tokens stored under `connections.gmail.oauth` in secretstore v2
  (`secretstore/`). Tokens never reach the browser; status responses carry
  booleans and metadata (connected email, `expiresAt`, `connectedAt`) only.
- Refresh is lazy at call time with a 5-minute expiry skew and a
  per-connection lock, mirroring `connections/auth/claude.py`. No background
  refresh.
- Requires `ENCRYPTION_KEY`: without it the secretstore is read-only and the
  Gmail card shows an "encryption unavailable" state instead of a connect
  button.
- Google OAuth client credentials are operator-supplied via environment:
  `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` in `.env`, passed
  through `docker-compose.yml` to the app service. One-time setup: a Google
  Cloud project with an OAuth client, redirect URI
  `http://localhost:8080/api/auth/gmail/callback` registered (8080 is the
  app's published port in `docker-compose.yml`).

## 2. Sync engine (`gmailsync/`)

### Fetch

- Gmail API `users.messages.list` with a query scoped to mail addressed to the
  answer-sheet email (`truth/answers.py` `email` field) and
  `after:<last_synced_at>`, so each sync is incremental.
- Sync state lives in `data/gmail_sync.json` (non-secret, beside
  `applications.json`): last-sync timestamp and processed Gmail message IDs.
- Message headers and snippet are fetched for matching; the full body is
  fetched only for messages that match an application, and only for
  classification.

### Match

- Candidate pool: applications with `response_received` false.
- Primary signal: sender domain against the application's `company` /
  `website` / `application_url` domains. Secondary: subject and body keywords
  against `role` and `company`.
- Each match records a confidence level and the evidence that produced it
  (which signals fired). Emails matching nothing are recorded as processed and
  never resurface.

### Classify

- Matched emails go through the existing LLM provider layer with a
  classification prompt returning one of: `rejection`, `interview`, `offer`,
  `confirmation`, `other`.
- Mapping to suggested status (the UI's existing vocabulary):
  `rejection → Rejected`, `interview → Interviewing`, `offer → Offer`,
  `confirmation`/`other` → `Waiting`.
- LLM failure degrades gracefully: the suggestion is still produced,
  unclassified, with no suggested status change beyond `response_received`.

### Suggestions store

- `data/gmail_suggestions.json`, atomic tmp+replace writes like
  `applications/store.py`, fail-safe to `[]` on malformed content.
- One record per Gmail message ID (dedup key): application ID, sender,
  subject, date, snippet, classification, suggested status, match evidence,
  and state `pending` / `accepted` / `dismissed`.

## 3. API

New routes in `api/routes.py` (registered before the SPA catch-all):

- `POST /api/gmail/sync` — runs a sync. Server-side throttle: skipped (with
  the last-sync time returned) if the last sync is under an hour old, unless
  `force` is set (the Sync now button sets it).
- `GET /api/gmail/suggestions` — pending suggestions plus last-sync metadata
  and connection state.
- `POST /api/gmail/suggestions/{id}/accept` and `.../dismiss`.

Accepting goes through a new `save_reply(application_id, reply)` helper in
`applications/store.py` — the existing dedicated-`save_*` pattern, not a
widening of the `EDITABLE` whitelist. It sets `response_received = True`,
applies the suggested status, and stores a nested `Reply` object on the
application (date, sender, subject, Gmail message ID, classification),
mirroring how `Confirmation` and `Screening` nest in
`applications/model.py`. The wire mapper (`_application_model` in
`api/routes.py`) and `ApplicationModel` schema are extended to expose `reply`
so the UI can show provenance. Wire schemas for suggestions follow the
camelCase `_Camel` convention in `api/schemas.py`.

## 4. UI (Applications page)

- On page load, if Gmail is connected and the last sync is over an hour old,
  sync fires automatically in the background; the page never blocks on it.
  A **Sync now** button forces a sync. Last-sync time is shown beside it.
- Pending suggestions render as a review strip above the applications table:
  sender, matched application, classification, suggested status, snippet, and
  Accept / Dismiss actions.
- Accepted suggestions update the row through the existing Replied chip and
  status colors; a small provenance marker distinguishes synced statuses from
  manually set ones (backed by the `reply` object).
- If Gmail is not connected, the strip and button do not render; the Accounts
  card in Settings is the entry point.

## Error handling

- Revoked or expired grant: sync returns a distinct "reconnect Gmail" state;
  the Sync button and Accounts card both surface it.
- Malformed `gmail_sync.json` or `gmail_suggestions.json`: fail safe to empty,
  same policy as the applications store.
- Gmail API or network failure: sync reports the error and leaves state
  untouched; nothing is marked processed for a fetch that failed.
- LLM failure: unclassified suggestion, see above.

## Privacy

- Read-only Gmail scope; the app never writes to the mailbox.
- Only headers and snippets are fetched for non-matching mail; full bodies
  only for matched messages, and those go only to the operator's configured
  LLM provider for classification.
- Tokens live encrypted in the secretstore and never reach the browser or the
  agent container.

## Testing

- Matcher unit tests: domain match, keyword match, no-match, ambiguous sender.
- Store tests: `save_reply`, suggestions store round-trip, dedup by message
  ID, fail-safe on malformed files.
- API tests: sync/suggestions/accept/dismiss with a faked Gmail client and
  faked classifier, via the existing `TestClient` + `data_dir` fixtures in
  `tests/conftest.py`.
- Live OAuth flow is verified manually; no test depends on network access.
