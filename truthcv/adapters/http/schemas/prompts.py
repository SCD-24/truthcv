"""Wire models for the prompt fragment and preset library."""

from __future__ import annotations

from .common import _Camel


class PromptFragmentIn(_Camel):
    """Input for creating/updating a prompt fragment."""

    id: str
    slot: str
    title: str
    text: str


class PromptFragmentOut(_Camel):
    """Response fragment from the library."""

    id: str
    slot: str
    title: str
    text: str
    seeded: bool
    recommended: bool = False


class PromptPresetIn(_Camel):
    """Input for creating/updating a prompt preset."""

    id: str
    name: str
    fragment_ids: list[str]
    is_default: bool = False


class PromptPresetOut(_Camel):
    """Response preset from the library."""

    id: str
    name: str
    fragment_ids: list[str]
    is_default: bool
    seeded: bool
