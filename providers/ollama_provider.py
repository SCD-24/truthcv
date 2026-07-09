"""Ollama implementation of LLMProvider (local, offline-capable)."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from .base import LLMProvider, ProviderError, env_model
from ._json import parse_json_object


class OllamaProvider(LLMProvider):
    def __init__(self, model: str | None = None, host: str | None = None) -> None:
        self._host = (host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")).rstrip(
            "/"
        )
        self._model = env_model("llama3.1", model)

    def _chat(self, system: str, messages: list[dict[str, str]], fmt_json: bool) -> str:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": "system", "content": system}, *messages],
            "stream": False,
        }
        if fmt_json:
            payload["format"] = "json"
        try:
            resp = httpx.post(f"{self._host}/api/chat", json=payload, timeout=120)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"Ollama request failed: {exc}") from exc
        return resp.json().get("message", {}).get("content", "")

    def complete(self, system: str, messages: list[dict[str, str]]) -> str:
        return self._chat(system, messages, fmt_json=False)

    def extract_json(
        self, system: str, messages: list[dict[str, str]], schema: dict[str, Any]
    ) -> dict[str, Any]:
        instruction = (
            "Respond with a single JSON object conforming to this JSON schema:\n"
            + json.dumps(schema)
        )
        text = self._chat(f"{system}\n\n{instruction}", messages, fmt_json=True)
        return parse_json_object(text)
