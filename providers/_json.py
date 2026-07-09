"""Shared helpers for coercing model output into a JSON object."""

from __future__ import annotations

import json
import re
from typing import Any

from .base import ProviderError

_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)


def parse_json_object(text: str) -> dict[str, Any]:
    """Best-effort parse of a JSON object from a model response.

    Accepts a bare JSON object, a fenced ```json block, or an object embedded in
    surrounding prose. Raises ProviderError if nothing parseable is found.
    """
    text = text.strip()
    # 1. Direct parse.
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # 2. Fenced code block.
    m = _FENCE.search(text)
    if m:
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

    # 3. First balanced { ... } span.
    start = text.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start : i + 1])
                        if isinstance(obj, dict):
                            return obj
                    except json.JSONDecodeError:
                        break

    raise ProviderError("Model did not return a parseable JSON object.")
