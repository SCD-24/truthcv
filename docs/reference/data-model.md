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
<!-- generated:end comp:application-tracker -->
