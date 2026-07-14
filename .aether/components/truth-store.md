# Component Specification: Truth Store
- **Identifier**: `truth-store`
- **Component Type**: BACKEND

> This file is generated dynamically from the spatial architecture canvas. Do not edit directly—use the visual workspaces instead.


## Intent & Scope Description (TEXT)

Owns truth.yaml, the single origin of all facts (truth/). Extracts text from the uploaded LinkedIn PDF via pypdf, uses a provider to build a structured truth file (every role/company/date/bullet/skill tagged source:linkedin-pdf with a stable id), and builds/validates/persists it. User-confirmed inferences are written back tagged source:user-confirmed.

---

## Tech Stack Profiles (TECHSTACK)

Supported tools, frameworks, and packages:
- **Python**
- **pypdf**
- **PyYAML**

---

## truth.yaml entry (SCHEMA)

| Field Name | Data Type | Key/Flags | Notes & Constraints |
|---|---|---|---|
| id | string | stable id | Referenced by the tailor engine when selecting facts. |
| kind | enum | - | role | company | date | bullet | skill |
| value | string | - | The factual content. |
| source | enum | provenance | linkedin-pdf | user-confirmed — the trust tag. |

---

## Schema enums & envelope (NOTE)

> **Schema enums & envelope**: TruthEntry.kind ∈ {role, company, date, bullet, skill}; TruthEntry.source ∈ {linkedin-pdf, user-confirmed}. The store enforces non-empty, unique id and valid kind/source. Persisted YAML is wrapped as { entries: [...] }, not a bare list.

---

## profile header (SCHEMA)

| Field Name | Data Type | Key/Flags | Notes & Constraints |
|---|---|---|---|
| name | string | - | Full name — identity, guardrail-exempt. |
| email | string | - | Contact — identity, guardrail-exempt. |
| phone | string | - | Contact — identity, guardrail-exempt. |
| location | string | - | Contact — identity, guardrail-exempt. |
| links | array&lt;{label,url}&gt; | - | Profile links — identity, guardrail-exempt. |
| summary | string | - | Free-text description/headline — a CLAIM; validated by the guardrail against the truth/source. |

---
