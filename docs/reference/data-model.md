<!-- generated:start cap:data-model-intro -->
# Data Model

Projected from `schema` widgets on the architecture canvas.
<!-- generated:end cap:data-model-intro -->

<!-- generated:start comp:truth-store -->
## Truth Store (`truth-store`)

### truth.yaml entry

| Field | Type | Flags | Notes |
|---|---|---|---|
| `id` | string | stable id | Referenced by the tailor engine when selecting facts. |
| `kind` | enum | - | role \| company \| date \| bullet \| skill |
| `value` | string | - | The factual content. |
| `source` | enum | provenance | linkedin-pdf \| user-confirmed — the trust tag. |

### profile header

| Field | Type | Flags | Notes |
|---|---|---|---|
| `name` | string | - | Full name — identity, guardrail-exempt. |
| `email` | string | - | Contact — identity, guardrail-exempt. |
| `phone` | string | - | Contact — identity, guardrail-exempt. |
| `location` | string | - | Contact — identity, guardrail-exempt. |
| `links` | array&lt;{label,url}&gt; | - | Profile links — identity, guardrail-exempt. |
| `summary` | string | - | Free-text description/headline — a CLAIM; validated by the guardrail against the truth/source. |
<!-- generated:end comp:truth-store -->

<!-- generated:start comp:application-tracker -->
## Application Tracker (`application-tracker`)

### Application record

| Field | Type | Flags | Notes |
|---|---|---|---|
| `id` | string | Primary Key | Stable application id (used in per-application filenames). |
| `company` | string | - | - |
| `website` | string | - | Company website URL. |
| `application_url` | string | - | Direct posting/portal URL, or N/A. |
| `submitted` | bool | - | - |
| `submission_type` | string | - | e.g. General (portal) or Tailored (to a posting). |
| `reached_out` | bool | - | - |
| `to_who` | string | - | Contact person reached out to. |
| `response_received` | bool | - | - |
| `method` | string | - | Outreach method, e.g. LinkedIn, Email. |
| `cv_document` | object | - | Owned editable CV: saved HTML/text source + rendered pdf/docx filenames. |
| `cover_letter_document` | object | - | Owned editable cover letter: saved text source + rendered pdf/docx filenames. |
| `posting` | string | - | Optional linked job posting text (absent for General submissions). |
| `created_at / updated_at` | string | - | ISO timestamps. |
| `application_date` | string | - | User-set date the application was submitted (ISO yyyy-mm-dd); distinct from the auto created_at/updated_at timestamps. |
| `notes` | string | - | Free-text notes the user attaches to the application record. |
| `screening_id` | string |  | The approved screening this application was recorded against. The dedupe key: record_application creates-or-fetches by it under one lock, so a retried agent call updates the existing row instead of adding another. |
| `fields_submitted` | list<{label,value,source}> |  | Every form field the agent actually submitted, with its provenance (observed \| canonical). Written only by the agent via MCP; read-only to the client. |
| `confirmation` | {text, confirmed_at, evidence} |  | Verbatim success message proving the submission went through. |
| `attachments` | list<{kind,path}> |  | The files actually uploaded with the application. |
| `screening` | {entity, remote, salary, language, role_type, glassdoor} |  | The pre-application filter verdicts recorded against this application. |
<!-- generated:end comp:application-tracker -->

<!-- generated:start comp:connections -->
## Connections (`connections`)

### gmail connection record (secretstore "gmail".oauth)

| Field | Type | Flags | Notes |
|---|---|---|---|
| `accessToken` | string | - | Current Gmail access token; blanked when reconnect is required. |
| `refreshToken` | string | - | Offline refresh token; carried over when Google omits it on refresh. |
| `expiresAt` | float (epoch seconds) | - | Refreshed lazily once within 300s of expiry. |
| `scope` | string | - | Defaults to https://www.googleapis.com/auth/gmail.readonly. |
| `connectedAt` | float (epoch seconds) | - | Preserved across refreshes. |
| `email` | string | - | Account address read from the Gmail profile endpoint at login. |
| `reauthRequired` | bool | - | Set by mark_reconnect_required when refresh is rejected. |
<!-- generated:end comp:connections -->
