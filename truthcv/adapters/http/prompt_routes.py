"""REST API for operator-editable prompt fragments and presets."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, status

from truthcv.adapters.http.schemas import (
    PromptFragmentIn,
    PromptFragmentOut,
    PromptPresetIn,
    PromptPresetOut,
)
from truthcv.engines.prompts.library import (
    get_preset,
    list_fragments,
    list_presets,
    set_default_preset,
)

from truthcv.services import prompt_library

prompt_router = APIRouter(prefix="/api")


def _slugify(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


@prompt_router.get("/prompt-fragments", response_model=list[PromptFragmentOut])
def get_prompt_fragments() -> list[PromptFragmentOut]:
    return [PromptFragmentOut(**f.to_dict()) for f in list_fragments()]


def _save_fragment(body: PromptFragmentIn) -> PromptFragmentOut:
    fragment = prompt_library.save_fragment(body.id, body.slot, body.title, body.text)
    return PromptFragmentOut(**fragment.to_dict())


@prompt_router.post("/prompt-fragments", response_model=PromptFragmentOut)
def create_prompt_fragment(body: PromptFragmentIn) -> PromptFragmentOut:
    if not body.id:
        body = body.model_copy(update={"id": _slugify(body.title)})
    return _save_fragment(body)


@prompt_router.put("/prompt-fragments/{id}", response_model=PromptFragmentOut)
def update_prompt_fragment(id: str, body: PromptFragmentIn) -> PromptFragmentOut:
    body = body.model_copy(update={"id": id})
    return _save_fragment(body)


@prompt_router.delete("/prompt-fragments/{id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_prompt_fragment(id: str) -> None:
    try:
        prompt_library.remove_fragment(id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@prompt_router.get("/prompt-presets", response_model=list[PromptPresetOut])
def get_prompt_presets() -> list[PromptPresetOut]:
    return [PromptPresetOut(**p.to_dict()) for p in list_presets()]


def _save_preset(body: PromptPresetIn) -> PromptPresetOut:
    preset = prompt_library.save_preset(body.id, body.name, body.fragment_ids, body.is_default)
    return PromptPresetOut(**preset.to_dict())


@prompt_router.post("/prompt-presets", response_model=PromptPresetOut)
def create_prompt_preset(body: PromptPresetIn) -> PromptPresetOut:
    return _save_preset(body)


@prompt_router.put("/prompt-presets/{id}", response_model=PromptPresetOut)
def update_prompt_preset(id: str, body: PromptPresetIn) -> PromptPresetOut:
    body = body.model_copy(update={"id": id})
    return _save_preset(body)


@prompt_router.delete("/prompt-presets/{id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_prompt_preset(id: str) -> None:
    try:
        prompt_library.remove_preset(id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@prompt_router.put("/prompt-presets/{id}/default", response_model=PromptPresetOut)
def set_prompt_preset_default(id: str) -> PromptPresetOut:
    try:
        set_default_preset(id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return PromptPresetOut(**get_preset(id).to_dict())
