# Component Specification: Truth Data Volume
- **Identifier**: `truth-data-volume`
- **Component Type**: STORAGE

> This file is generated dynamically from the spatial architecture canvas. Do not edit directly—use the visual workspaces instead.


## Intent & Scope Description (TEXT)

The single mounted volume (./data) that persists truth.yaml and generated CVs (PDF/DOCX) across container restarts. There is no database — this flat, id-referenced file store is the entire persistence layer.

---

## Tech Stack Profiles (TECHSTACK)

Supported tools, frameworks, and packages:
- **Docker volume**
- **YAML files**

---

## Encrypted secrets vault (NOTE)

> **Encrypted secrets vault**: Beyond truth.yaml, the volume also holds data/secrets.enc — a Fernet-encrypted credential vault (activeProvider, anthropicApiKey, openaiApiKey, ollamaHost, model), gated by ENCRYPTION_KEY. resolve_credentials() layers secrets.enc OVER env vars (encrypted store wins, else env, else default). profile.pdf and rendered artifacts also live here.

---
