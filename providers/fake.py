"""Deterministic in-memory provider for tests and CI (no network).

Two ways to script it:
  * pass `completions` / `json_responses` as queues consumed in order, or
  * pass `router(system, messages, schema) -> str | dict` for smart responses.
With neither, it echoes a minimal, schema-shaped empty object so calls never
hit the network.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Callable

from .base import LLMProvider, ProviderError

Router = Callable[[str, list[dict[str, str]], dict[str, Any] | None], "str | dict"]


class FakeProvider(LLMProvider):
    def __init__(
        self,
        completions: list[str] | None = None,
        json_responses: list[dict[str, Any]] | None = None,
        router: Router | None = None,
    ) -> None:
        self._completions: deque[str] = deque(completions or [])
        self._json: deque[dict[str, Any]] = deque(json_responses or [])
        self._router = router
        self.calls: list[dict[str, Any]] = []

    def complete(self, system: str, messages: list[dict[str, str]]) -> str:
        self.calls.append({"kind": "complete", "system": system, "messages": messages})
        if self._router is not None:
            out = self._router(system, messages, None)
            if isinstance(out, str):
                return out
        if self._completions:
            return self._completions.popleft()
        return ""

    def extract_json(
        self, system: str, messages: list[dict[str, str]], schema: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls.append(
            {"kind": "json", "system": system, "messages": messages, "schema": schema}
        )
        if self._router is not None:
            out = self._router(system, messages, schema)
            if isinstance(out, dict):
                return out
        if self._json:
            return self._json.popleft()
        # Return an empty object shaped by the schema's top-level properties.
        props = (schema or {}).get("properties", {})
        result: dict[str, Any] = {}
        for key, spec in props.items():
            t = spec.get("type")
            result[key] = [] if t == "array" else {} if t == "object" else ""
        return result

    def expect_empty(self) -> None:
        if self._completions or self._json:
            raise ProviderError("FakeProvider still has scripted responses queued.")
