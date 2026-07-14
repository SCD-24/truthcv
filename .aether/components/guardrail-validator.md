# Component Specification: Guardrail Validator
- **Identifier**: `guardrail-validator`
- **Component Type**: BACKEND

> This file is generated dynamically from the spatial architecture canvas. Do not edit directly—use the visual workspaces instead.


## Intent & Scope Description (TEXT)

The core truthfulness guardrail (guardrail/): a pure, deterministic, scoped token-diff of a draft against truth — no LLM. validate(scopes, global_values) returns ok plus BOTH a flat unverifiable[] token list (back-compat) and structured blocked_claims grouping untraceable tokens under the specific source text (bullet) and scope id they came from, so callers can present whole-claim approve/deny. A token is verifiable if it is a stopword or appears (post-tokenization) in its own scope's allowed set (or global skills). Render-scoped approvals are passed in by merging an approved claim's text into that scope's allowed set for a single render — the guardrail itself never mutates truth.

---

## Tech Stack Profiles (TECHSTACK)

Supported tools, frameworks, and packages:
- **Python**

---

## Profile header scope (NOTE)

> **Profile header scope**: The Profile summary is validated in its own Scope against the truth/source, exactly like a bullet — an edited summary that introduces tokens not in the Truth File is blocked at render. Profile identity fields (name, email, phone, location, links) are NOT claims and are exempt from validation; never tokenize them into a guardrail scope.

---
