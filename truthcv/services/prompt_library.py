"""Prompt fragment and preset writes, with the seeded/default 403-vs-400 policy.

Exists so the HTTP routes stay wire-shaping only: which library ValueErrors
mean "forbidden" (seeded or default records) and which mean "bad request" is
a policy and lives here, not in the route module.
"""

from __future__ import annotations

from truthcv.engines.prompts.fragments import Fragment, Preset
from truthcv.engines.prompts.library import (
    delete_fragment,
    delete_preset,
    get_fragment,
    get_preset,
    upsert_fragment,
    upsert_preset,
)
from truthcv.services.errors import BadRequest, Forbidden


def _seeded_or_bad_request(exc: ValueError) -> Forbidden | BadRequest:
    message = str(exc)
    if "seeded" in message or "default" in message:
        return Forbidden(message)
    return BadRequest(message)


def save_fragment(id: str, slot: str, title: str, text: str) -> Fragment:
    """Upsert a fragment and return the stored record; a rejected write is Forbidden."""
    fragment = Fragment(id=id, slot=slot, title=title, text=text)
    try:
        upsert_fragment(fragment)
    except ValueError as exc:
        raise Forbidden(str(exc)) from exc
    return get_fragment(fragment.id)


def save_preset(id: str, name: str, fragment_ids: list[str], is_default: bool) -> Preset:
    """Upsert a preset and return the stored record; a rejected write is Forbidden."""
    preset = Preset(id=id, name=name, fragment_ids=fragment_ids, is_default=is_default)
    try:
        upsert_preset(preset)
    except ValueError as exc:
        raise Forbidden(str(exc)) from exc
    return get_preset(preset.id)


def remove_fragment(id: str) -> None:
    """Delete a fragment; seeded/default refusals are Forbidden, other ValueErrors BadRequest.

    An unknown id still raises KeyError for the caller to map to 404.
    """
    try:
        delete_fragment(id)
    except ValueError as exc:
        raise _seeded_or_bad_request(exc) from exc


def remove_preset(id: str) -> None:
    """Delete a preset; same error policy as ``remove_fragment``."""
    try:
        delete_preset(id)
    except ValueError as exc:
        raise _seeded_or_bad_request(exc) from exc
