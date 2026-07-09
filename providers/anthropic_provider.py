"""Anthropic implementation of LLMProvider."""

from __future__ import annotations

import json
import os
from typing import Any

from .base import LLMProvider, ProviderError, env_model
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
        self._model = env_model("claude-3-5-sonnet-latest", model)

    def complete(self, system: str, messages: list[dict[str, str]]) -> str:
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=4096,
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
