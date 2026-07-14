"""LLMProvider abstraction.

A thin interface over an LLM so the rest of TruthCV never depends on which
provider is active. IMPORTANT: no truthfulness logic may depend on the concrete
provider — the guardrail is deterministic and provider-agnostic. Providers are
used only to *propose* structure/text; nothing they return is trusted until it
has passed through the truth store and the guardrail.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal


# Generous ceiling on output tokens. A full profile extracts to a long JSON
# entries list; too small a cap truncates it mid-array and JSON parsing fails.
# A ceiling only — shorter replies cost nothing extra. Anthropic requires an
# explicit max; Ollama's default can be small, so we set it there too. OpenAI is
# intentionally left uncapped (its default is already the model's full budget,
# and forcing max_tokens would break the o-series, which rejects it).
MAX_OUTPUT_TOKENS = 16000


def env_model(default: str, override: str | None = None) -> str:
    """Resolve a model id: explicit override, else LLM_MODEL, else default.

    Treats an unset OR empty/whitespace LLM_MODEL as 'use the default' — an empty
    string in .env must not be passed through to the provider API.
    """
    if override and override.strip():
        return override.strip()
    env = os.environ.get("LLM_MODEL", "")
    return env.strip() if env.strip() else default

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class Message:
    """A single chat message. `role` is one of system|user|assistant."""

    role: Role
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


def to_messages(messages: list[dict[str, str]] | list[Message]) -> list[dict[str, str]]:
    """Normalize a list of Message or plain dicts to provider-ready dicts."""
    out: list[dict[str, str]] = []
    for m in messages:
        if isinstance(m, Message):
            out.append(m.as_dict())
        else:
            out.append({"role": m["role"], "content": m["content"]})
    return out


class LLMProvider(ABC):
    """Interface every provider implements."""

    @abstractmethod
    def complete(self, system: str, messages: list[dict[str, str]]) -> str:
        """Return a plain-text completion."""

    @abstractmethod
    def extract_json(
        self, system: str, messages: list[dict[str, str]], schema: dict[str, Any]
    ) -> dict[str, Any]:
        """Return a JSON object conforming to `schema` (a JSON Schema dict)."""

    def list_models(self) -> list[dict[str, str]]:
        """Discover selectable models as ``[{"id": ..., "label": ...}]``.

        Pulled live from the provider's API/SDK by concrete implementations.
        Default: nothing discoverable (caller falls back to free-text entry).
        """
        return []


class ProviderError(RuntimeError):
    """Raised when a provider is misconfigured or a call fails irrecoverably."""
