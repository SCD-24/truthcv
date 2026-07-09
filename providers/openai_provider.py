"""OpenAI implementation of LLMProvider."""

from __future__ import annotations

import json
import os
from typing import Any

from .base import LLMProvider, ProviderError, env_model
from ._json import parse_json_object


class OpenAIProvider(LLMProvider):
    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        try:
            import openai  # noqa: F401
        except ImportError as exc:  # pragma: no cover - import guard
            raise ProviderError(
                "The 'openai' package is required for LLM_PROVIDER=openai."
            ) from exc
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ProviderError("OPENAI_API_KEY is not set.")
        self._client = openai.OpenAI(api_key=key)
        self._model = env_model("gpt-4o", model)

    def _chat(self, system: str, messages: list[dict[str, str]], json_mode: bool) -> str:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": "system", "content": system}, *messages],
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = self._client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    def complete(self, system: str, messages: list[dict[str, str]]) -> str:
        return self._chat(system, messages, json_mode=False)

    def extract_json(
        self, system: str, messages: list[dict[str, str]], schema: dict[str, Any]
    ) -> dict[str, Any]:
        instruction = (
            "Respond with a single JSON object conforming to this JSON schema:\n"
            + json.dumps(schema)
        )
        text = self._chat(f"{system}\n\n{instruction}", messages, json_mode=True)
        return parse_json_object(text)
