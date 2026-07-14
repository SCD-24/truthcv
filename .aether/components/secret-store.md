# Component Specification: Secret Store
- **Identifier**: `secret-store`
- **Component Type**: BACKEND

> This file is generated dynamically from the spatial architecture canvas. Do not edit directly—use the visual workspaces instead.


## Intent & Scope Description (TEXT)

Neutral encrypted credential/secrets vault (secretstore/), extracted from the API to break the api↔providers import cycle. Resolves LLM credentials — reading data/secrets.enc (Fernet, gated on ENCRYPTION_KEY) and falling back to environment variables — and persists them via atomic tmp-rename. A leaf that uses truth.store.data_dir only for the data path. Depended on downward by both the API and the LLM Provider Layer.

---

## Tech Stack Profiles (TECHSTACK)

Supported tools, frameworks, and packages:
- **Python**
- **cryptography (Fernet)**

---
