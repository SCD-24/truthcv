"""REST API for operator-editable prompt fragments and presets."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, status

from api.schemas import (
    PresetValidateRequest,
    PromptConflict,
    PromptFragmentIn,
    PromptFragmentOut,
    PromptPresetIn,
    PromptPresetOut,
)
from prompts.fragments import Fragment, Preset
from prompts.library import (
    PresetConflictError,
    Conflict,
    delete_fragment,
    delete_preset,
    get_fragment,
    get_preset,
    list_fragments,
    list_presets,
    set_default_preset,
    upsert_fragment,
    upsert_preset,
    validate_preset,
)

prompt_router = APIRouter(prefix="/api")


def _slugify(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def _conflict_out(conflict: Conflict) -> PromptConflict:
    return PromptConflict(
        kind=conflict.kind,
        fragment_ids=conflict.fragment_ids,
        slot=conflict.slot,
        message=conflict.message,
    )


def _raise_seeded_or_bad_request(exc: ValueError) -> None:
    message = str(exc)
    if "seeded" in message or "default" in message:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message) from exc
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


@prompt_router.get("/prompt-fragments", response_model=list[PromptFragmentOut])
def get_prompt_fragments() -> list[PromptFragmentOut]:
    return [PromptFragmentOut(**f.to_dict()) for f in list_fragments()]


def _save_fragment(body: PromptFragmentIn) -> PromptFragmentOut:
    fragment = Fragment(
        id=body.id,
        slot=body.slot,
        title=body.title,
        text=body.text,
        conflicts_with=body.conflicts_with,
    )
    try:
        upsert_fragment(fragment)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return PromptFragmentOut(**get_fragment(fragment.id).to_dict())


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
        delete_fragment(id)
    except ValueError as exc:
        _raise_seeded_or_bad_request(exc)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@prompt_router.get("/prompt-presets", response_model=list[PromptPresetOut])
def get_prompt_presets() -> list[PromptPresetOut]:
    return [PromptPresetOut(**p.to_dict()) for p in list_presets()]


def _save_preset(body: PromptPresetIn) -> PromptPresetOut:
    preset = Preset(
        id=body.id,
        name=body.name,
        fragment_ids=body.fragment_ids,
        is_default=body.is_default,
    )
    try:
        upsert_preset(preset)
    except PresetConflictError as exc:
        conflicts = [_conflict_out(c).model_dump(by_alias=True) for c in exc.conflicts]
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"conflicts": conflicts}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return PromptPresetOut(**get_preset(preset.id).to_dict())


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
        delete_preset(id)
    except ValueError as exc:
        _raise_seeded_or_bad_request(exc)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@prompt_router.post("/prompt-presets/validate")
def validate_prompt_preset(body: PresetValidateRequest) -> dict:
    conflicts = validate_preset(body.fragment_ids)
    return {"conflicts": [_conflict_out(c).model_dump(by_alias=True) for c in conflicts]}


@prompt_router.put("/prompt-presets/{id}/default", response_model=PromptPresetOut)
def set_prompt_preset_default(id: str) -> PromptPresetOut:
    try:
        set_default_preset(id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return PromptPresetOut(**get_preset(id).to_dict())
