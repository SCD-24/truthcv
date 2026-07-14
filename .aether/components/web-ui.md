# Component Specification: Web UI
- **Identifier**: `web-ui`
- **Component Type**: FRONTEND

> This file is generated dynamically from the spatial architecture canvas. Do not edit directly—use the visual workspaces instead.


## Intent & Scope Description (TEXT)

React single-page wizard (web/) that walks the user through Upload LinkedIn PDF → Review extracted truth → Paste job posting (with optional Fetch-from-URL) → Confirm inferences → Download PDF/DOCX. Built by Vite into a static bundle that the API serves. No auth, single-user per deployment.

---

## Tech Stack Profiles (TECHSTACK)

Supported tools, frameworks, and packages:
- **React**
- **Vite**
- **TypeScript**
- **MUI (@mui/material)**
- **Emotion (@emotion/react)**

---

## MUI themed to the ledger design (NOTE)

> **MUI themed to the ledger design**: The UI uses MUI components, but MUI is themed via createTheme from the existing "provenance ledger" design tokens (web/src/styles/tokens.css + DESIGN.md) — NOT stock Material Design. Preserve the semantics: mono "record voice" typography for ids/dates/eyebrows, seal-green (--attest) strictly for attested/confirmed provenance, oxblood (--flag) strictly for unverified/inference. tokens.css stays the source of truth and the theme references its CSS vars so light/dark keeps working.

---
