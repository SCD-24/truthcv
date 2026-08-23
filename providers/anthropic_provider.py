"""Anthropic implementation of LLMProvider."""

from __future__ import annotations

import json
import os
from typing import Any

from .base import MAX_OUTPUT_TOKENS, _EFFORT_BUDGET, LLMProvider, ProviderError, env_model, supports_effort_levels
from ._json import parse_json_object


class AnthropicProvider(LLMProvider):
    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        oauth: bool = False,
        effort: str | None = None,
    ) -> None:
        try:
            import anthropic  # noqa: F401
        except ImportError as exc:  # pragma: no cover - import guard
            raise ProviderError(
                "The 'anthropic' package is required for LLM_PROVIDER=anthropic."
            ) from exc
        self._anthropic = anthropic
        self._oauth = oauth
        if not oauth:
            key = api_key or os.environ.get("ANTHROPIC_API_KEY")
            if not key:
                raise ProviderError("ANTHROPIC_API_KEY is not set.")
            self._client = anthropic.Anthropic(api_key=key)
        self._model = env_model("claude-opus-4-8", model)
        self._effort = effort or ""

    def _get_client(self):
        """Key mode: the cached client. OAuth mode: per-call client with a
        fresh subscription token (lazy refresh lives in the auth module)."""
        if not self._oauth:
            return self._client
        from connections.auth.claude import get_valid_access_token

        return self._anthropic.Anthropic(
            auth_token=get_valid_access_token(),
            default_headers={"anthropic-beta": "oauth-2025-04-20"},
        )

    def _system_param(self, system: str):
        if not self._oauth:
            return system
        from connections.auth.claude import CLAUDE_CODE_PREAMBLE

        # Subscription tokens are rejected unless this exact preamble is the
        # first system block.
        return [
            {"type": "text", "text": CLAUDE_CODE_PREAMBLE},
            {"type": "text", "text": system},
        ]

    def list_models(self) -> list[dict[str, str]]:
        """Live model list from the Anthropic Models API (auto-paginates)."""
        out: list[dict[str, str]] = []
        for m in self._get_client().models.list():
            out.append({"id": m.id, "label": getattr(m, "display_name", "") or m.id})
        return out

    def _thinking_param(self) -> dict:
        """Build the Anthropic thinking block from the configured effort level.

        When effort is set and the model supports extended thinking, returns an
        enabled block with a budget_tokens value derived from the level; otherwise
        returns the disabled sentinel.  Budget is clamped to MAX_OUTPUT_TOKENS.
        """
        if self._effort and supports_effort_levels("claude", self._model):
            budget = min(_EFFORT_BUDGET.get(self._effort, 8192), MAX_OUTPUT_TOKENS)
            return {"type": "enabled", "budget_tokens": budget}
        return {"type": "disabled"}

    def complete(self, system: str, messages: list[dict[str, str]]) -> str:
        resp = self._get_client().messages.create(
            model=self._model,
            # Generous ceiling so a long extraction isn't truncated mid-JSON;
            # stays under the SDK's non-streaming timeout guard. See base.py.
            max_tokens=MAX_OUTPUT_TOKENS,
            thinking=self._thinking_param(),
            system=self._system_param(system),
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
