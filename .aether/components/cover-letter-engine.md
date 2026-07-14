# Component Specification: Cover Letter Engine
- **Identifier**: `cover-letter-engine`
- **Component Type**: BACKEND

> This file is generated dynamically from the spatial architecture canvas. Do not edit directly—use the visual workspaces instead.


## Intent & Scope Description (TEXT)

Guardrailed cover-letter generation (coverletter/). build_letter() asks the LLM (via the provider layer) for a cover letter as tagged paragraphs, each declaring the factual claims it makes. Every claim is validated by the Guardrail Validator against the Truth Store; if any claim is unverifiable the letter is BLOCKED (returns {blocked: true, unverifiable, text: ""}). Otherwise the paragraph text is joined and handed to the Renderer for HTML/PDF/DOCX output. Serves /api/cover-letter together with render/.

---

## Tech Stack Profiles (TECHSTACK)

Supported tools, frameworks, and packages:
- **Python**

---
