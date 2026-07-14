"""Backwards-compatible shim: the secrets store now lives in `secretstore`.

Kept so existing `from api import secrets` callers keep working. The real
implementation moved to the neutral `secretstore` package so the provider layer
can resolve credentials without importing the api layer (which had formed the
project's only import cycle). Prefer importing from `secretstore` in new code.
"""

from __future__ import annotations

from secretstore import (
    SecretsUnavailable,
    encryption_available,
    read_secrets,
    resolve_credentials,
    write_secrets,
)

__all__ = [
    "SecretsUnavailable",
    "encryption_available",
    "read_secrets",
    "resolve_credentials",
    "write_secrets",
]
