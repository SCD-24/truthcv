# Component Specification: Prompt Store
- **Identifier**: `prompt-store`
- **Component Type**: BACKEND

> This file is generated dynamically from the spatial architecture canvas. Do not edit directly—use the visual workspaces instead.


## Intent & Scope Description (TEXT)

The single home for every LLM prompt in TruthCV (prompts/). A shared, fact-free prompt-template library: style-only fragments (CV_STYLE, LETTER_STYLE), the truth-extraction prompt, tailoring prompts (keyword extraction, missing-qualification inference, CV selection) with truth-block renderers, and cover-letter prompts. A pure leaf that depends downward only on truth.model; imported by truth-store, tailor-engine and cover-letter-engine.

---

## Tech Stack Profiles (TECHSTACK)

Supported tools, frameworks, and packages:
- **Python**

---
