"""ChatGPT Codex Responses transport.

A thin module that performs ONE Responses call against the ChatGPT Codex
backend (over the SSE streaming transport — the endpoint does not support
non-streaming mode) and returns the assembled text. No JSON, no tool calls,
no state — callers consume the wire's plain-text completion through the
existing LLMProvider.complete / extract_json signatures.
"""

from __future__ import annotations

import json as _json
import re
from typing import Any

from .base import ProviderError


# Hardcoded because the wire exposes no list endpoint. Update this tuple when
# the Codex model family rotates; this is the one place to do it.
CODEX_SUBSCRIPTION_MODELS: tuple[str, ...] = (
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.5",
    "gpt-5.6-sol",
    "gpt-5.6-luna",
    "gpt-5.3-codex-spark",
)

DEFAULT_BASE_URL = "https://chatgpt.com/backend-api/codex"
USAGE_LIMIT_CODES = frozenset({"usage_limit_reached", "usage_not_included", "rate_limit_exceeded"})


def _headers(token: str, account_id: str) -> dict[str, str]:
    """Return the documented set of request headers."""
    return {
        "Authorization": f"Bearer {token}",
        "chatgpt-account-id": account_id,
        "originator": "truthcv",
        "User-Agent": "truthcv",
        "OpenAI-Beta": "responses=experimental",
        "accept": "text/event-stream",
        "content-type": "application/json",
    }


def _build_body(
    model: str,
    system: str,
    messages: list[dict[str, Any]],
    effort: str | None,
) -> dict[str, Any]:
    """Build the request body. Never sends max_output_tokens or store:true."""
    body: dict[str, Any] = {
        "model": model,
        "store": False,
        "stream": True,
        "instructions": system,
        "input": messages,
        "include": ["reasoning.encrypted_content"],
        "parallel_tool_calls": True,
        "tool_choice": "auto",
    }
    if effort:
        body["reasoning"] = {"effort": effort, "summary": "auto"}
    return body


def _parse_event(line: str) -> dict[str, Any] | None:
    """Parse one SSE `data: ...` payload line into a dict, or None."""
    if not line.startswith("data: "):
        return None
    payload = line[len("data: "):].strip()
    if not payload or payload == "[DONE]":
        return None
    try:
        return _json.loads(payload)
    except _json.JSONDecodeError:
        return None


def _stream_events(response: Any) -> Any:
    """Yield parsed SSE event dicts from an httpx streaming response."""
    buffer = ""
    for chunk in response.iter_lines():
        buffer += chunk + "\n"
        # Some servers send many events per chunk; split on newlines.
        for line in buffer.split("\n"):
            line = line.strip()
            if not line or line.startswith(":"):
                continue
            event = _parse_event(line)
            if event is not None:
                yield event
        buffer = ""


def _accumulate(events: Any) -> str:
    """Walk the SSE event stream and assemble the assistant text."""
    text = ""
    completed = False
    for event in events:
        evt_type = event.get("type")

        if evt_type == "error":
            err = event.get("error") or {}
            code = err.get("code") if isinstance(err, dict) else None
            message = err.get("message") if isinstance(err, dict) else str(err)
            if code in USAGE_LIMIT_CODES:
                resets = err.get("resets_at") if isinstance(err, dict) else None
                suffix = f" (resets at {resets})" if isinstance(resets, (int, float)) else ""
                raise ProviderError(f"ChatGPT usage limit reached{suffix}")
            raise ProviderError(f"{code or 'error'}: {message}")

        if evt_type == "response.failed":
            err = (event.get("response") or {}).get("error") or {}
            code = err.get("code") if isinstance(err, dict) else None
            message = err.get("message") if isinstance(err, dict) else str(err)
            raise ProviderError(f"{code or 'failed'}: {message}")

        # Text delta
        if evt_type == "response.output_text.delta":
            delta = (event.get("response") or {}).get("output_text", {}).get("delta")
            if delta:
                text += delta

        # Stream completion marker
        if evt_type == "response.completed":
            completed = True
            break

    if not completed:
        raise ProviderError("Stream ended without a completion event")
    return text


def complete_via_responses(
    access_token: str,
    account_id: str,
    model: str,
    system: str,
    messages: list[dict[str, Any]],
    effort: str | None = None,
    base_url: str | None = None,
) -> str:
    """Stream one Responses call against the ChatGPT Codex backend and return text."""
    import httpx

    url = f"{base_url or DEFAULT_BASE_URL}/responses"
    body = _build_body(model, system, messages, effort)

    try:
        with httpx.stream(
            "POST",
            url,
            headers=_headers(access_token, account_id),
            json=body,
            timeout=httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0),
        ) as response:
            if response.status_code // 100 != 2:
                try:
                    err_body = response.read()
                    err_json = _json.loads(err_body)
                    code = (err_json.get("error") or {}).get("code") or err_json.get("code")
                    message = (err_json.get("error") or {}).get("message") or err_json.get("message", "")
                except Exception:
                    code = None
                    message = ""
                if response.status_code == 429 or code in USAGE_LIMIT_CODES:
                    resets = (err_json.get("error") or {}).get("resets_at") if isinstance(err_json, dict) else None
                    suffix = f" (resets at {resets})" if isinstance(resets, (int, float)) else ""
                    raise ProviderError(f"ChatGPT usage limit reached{suffix}")
                raise ProviderError(f"{code or response.status_code}: {message}")

            return _accumulate(_stream_events(response))
    except ProviderError:
        raise
    except httpx.HTTPError as exc:
        raise ProviderError(f"Codex Responses request failed: {exc}") from exc


__all__ = ["CODEX_SUBSCRIPTION_MODELS", "complete_via_responses"]