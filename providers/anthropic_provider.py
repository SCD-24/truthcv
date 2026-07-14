"""Anthropic implementation of LLMProvider."""

from __future__ import annotations

import json
import os
from typing import Any

from .base import MAX_OUTPUT_TOKENS, LLMProvider, ProviderError, env_model
from ._json import parse_json_object


class AnthropicProvider(LLMProvider):
    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        try:
            import anthropic  # noqa: F401
        except ImportError as exc:  # pragma: no cover - import guard
            raise ProviderError(
                "The 'anthropic' package is required for LLM_PROVIDER=anthropic."
            ) from exc
        self._anthropic = anthropic
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise ProviderError("ANTHROPIC_API_KEY is not set.")
        self._client = anthropic.Anthropic(api_key=key)
        self._model = env_model("claude-opus-4-8", model)

    def list_models(self) -> list[dict[str, str]]:
        """Live model list from the Anthropic Models API (auto-paginates)."""
        out: list[dict[str, str]] = []
        for m in self._client.models.list():
            out.append({"id": m.id, "label": getattr(m, "display_name", "") or m.id})
        return out

    def complete(self, system: str, messages: list[dict[str, str]]) -> str:
        resp = self._client.messages.create(
            model=self._model,
            # Generous ceiling so a long extraction isn't truncated mid-JSON;
            # stays under the SDK's non-streaming timeout guard. See base.py.
            max_tokens=MAX_OUTPUT_TOKENS,
            thinking={"type": "disabled"},
            system=system,
            messages=messages,
        )
        return "".join(block.text for block in resp.content if block.type == "text")

    def extract_json(
        self, system: str, messages: list[dict[str, str]], schema: dict[str, Any]
    ) -> dict[str, Any]:
        instruction = (
            "Respond with a single JSON object that conforms to this JSON schema. "
            "Output JSON only, no prose:\n" + json.dumps(schema)
        )
        full_system = f"{system}\n\n{instruction}"
        text = self.complete(full_system, messages)
        return parse_json_object(text)
