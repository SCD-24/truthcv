# Component Specification: Tailor Engine
- **Identifier**: `tailor-engine`
- **Component Type**: BACKEND

> This file is generated dynamically from the spatial architecture canvas. Do not edit directly—use the visual workspaces instead.


## Intent & Scope Description (TEXT)

Tailors a CV to a specific posting (tailor/). Extracts the posting's keywords/requirements via a provider, then selects, reorders, and rephrases ONLY entries referenced by id from truth.yaml. Detects any claim the LLM wants to add that is not already in the truth file and surfaces it as an approval checklist (confirm-inferences step); nothing unapproved reaches the CV.

---

## Tech Stack Profiles (TECHSTACK)

Supported tools, frameworks, and packages:
- **Python**

---
