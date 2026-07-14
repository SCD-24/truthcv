# Component Specification: Application Tracker
- **Identifier**: `application-tracker`
- **Component Type**: BACKEND

> This file is generated dynamically from the spatial architecture canvas. Do not edit directly—use the visual workspaces instead.


## Intent & Scope Description (TEXT)

Owns the user's job-application records (applications/) persisted as applications.json on the Truth Data Volume. Each Application tracks a submission (Company, Website, Application URL, Submitted, Submission Type, Reached Out, To Who, Response Received, Method) and OWNS its generated documents: an editable CV and cover letter saved per-application (so old outputs are retained and traceable to the application they went out with). Applications may exist WITHOUT a job posting (General/portal submissions). CRUD helpers use atomic writes mirroring truth/store.py; re-renders edited document content via the Renderer.

---

## Tech Stack Profiles (TECHSTACK)

Supported tools, frameworks, and packages:
- **Python**
- **PyYAML/JSON**

---

## Application record (SCHEMA)

| Field Name | Data Type | Key/Flags | Notes & Constraints |
|---|---|---|---|
| id | string | Primary Key | Stable application id (used in per-application filenames). |
| company | string | - | - |
| website | string | - | Company website URL. |
| application_url | string | - | Direct posting/portal URL, or N/A. |
| submitted | bool | - | - |
| submission_type | string | - | e.g. General (portal) or Tailored (to a posting). |
| reached_out | bool | - | - |
| to_who | string | - | Contact person reached out to. |
| response_received | bool | - | - |
| method | string | - | Outreach method, e.g. LinkedIn, Email. |
| cv_document | object | - | Owned editable CV: saved HTML/text source + rendered pdf/docx filenames. |
| cover_letter_document | object | - | Owned editable cover letter: saved text source + rendered pdf/docx filenames. |
| posting | string | - | Optional linked job posting text (absent for General submissions). |
| created_at / updated_at | string | - | ISO timestamps. |
| application_date | string | - | User-set date the application was submitted (ISO yyyy-mm-dd); distinct from the auto created_at/updated_at timestamps. |
| notes | string | - | Free-text notes the user attaches to the application record. |

---
