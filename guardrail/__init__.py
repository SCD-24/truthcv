"""Guardrail Validator: the deterministic truthfulness gate.

Pure, provider-agnostic. No draft may be rendered unless validate() returns
ok=True. It never trusts anything an LLM produced — it diffs the draft's factual
tokens against the union of truth.yaml entry values.
"""

from .validate import validate, ValidationResult, Scope, BlockedClaim

__all__ = ["validate", "ValidationResult", "Scope", "BlockedClaim"]
