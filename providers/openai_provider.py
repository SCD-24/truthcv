"""OpenAI implementation of LLMProvider."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from .base import LLMProvider, ProviderError, env_model, supports_effort_levels
from ._json import parse_json_object


class OpenAIProvider(LLMProvider):
    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        effort: str | None = None,
    ) -> None:
        try:
            import openai  # noqa: F401
        except ImportError as exc:  # pragma: no cover - import guard
            raise ProviderError(
                "The 'openai' package is required for LLM_PROVIDER=openai."
            ) from exc
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ProviderError("OPENAI_API_KEY is not set.")
        kwargs: dict[str, Any] = {"api_key": key}
        if base_url is not None:
            kwargs["base_url"] = base_url
        self._client = openai.OpenAI(**kwargs)
        # Derived from base_url so effort validation uses the right pattern set.
        self._provider_key = "openrouter" if base_url else "codex"
        # OpenRouter namespaces every model id as vendor/model and rejects a
        # bare "gpt-4o", so the fallback for a route with no model chosen has
        # to be the namespaced form of the same model.
        default_model = "openai/gpt-4o" if self._provider_key == "openrouter" else "gpt-4o"
        self._model = env_model(default_model, model)
        self._effort = effort or ""

    def _chat(self, system: str, messages: list[dict[str, str]], json_mode: bool) -> str:
        # Intentionally no max_tokens: unset lets the model use its full output
        # budget, so a long extraction isn't truncated. Do NOT add a small
        # max_tokens here (it would reintroduce the truncation bug and also break
        # the o-series, which rejects max_tokens). See base.py MAX_OUTPUT_TOKENS.
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": "system", "content": system}, *messages],
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if self._effort and supports_effort_levels(self._provider_key, self._model):
            kwargs["reasoning_effort"] = self._effort
        resp = self._client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    def list_models(self) -> list[dict[str, str]]:
        """Live model list from the Models API.

        OpenAI's endpoint also returns embeddings/audio/image models we can't
        chat with, so its ids are narrowed to the chat families. OpenRouter
        serves only chat models and namespaces every id as ``vendor/model``
        (``openai/gpt-4o``, ``anthropic/claude-sonnet-4``), which that narrowing
        would reject wholesale — leaving the model picker empty. So it is
        applied to OpenAI only.
        """
        ids = [m.id for m in self._client.models.list().data]
        if self._provider_key != "openrouter":
            ids = [i for i in ids if i.startswith("gpt-") or re.match(r"o\d", i)]
        return [{"id": i, "label": i} for i in sorted(ids)]

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
