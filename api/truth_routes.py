"""Truth/profile routes: CV upload, extraction, the truth document, inference
confirmation, profile status, onboarding state and profile answers."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, File, HTTPException, UploadFile

from providers import get_provider
from truth import load, save
from truth.answers import load as load_answers
from services.inferences import confirm_inferences as confirm_inferences_service
import services.truth as truth_service
import services.onboarding as onboarding_service
from truth.model import Truth
from truth.pdf import has_profile

from .schemas import (
    AnswersModel,
    AnswersUpdate,
    ConfirmInferencesRequest,
    OnboardingState,
    OnboardingUpdate,
    ProfileStatus,
    TruthDoc,
)

router = APIRouter()


def _truth_doc(truth: Truth) -> TruthDoc:
    return TruthDoc.model_validate(truth.to_dict())


MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MiB — a CV/cover-letter upload has no legitimate reason to exceed this


@router.post("/upload", status_code=204)
async def upload(file: UploadFile = File(...)) -> None:
    # Read one byte past the cap so an oversized upload is detected without
    # ever buffering the whole body into process memory.
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413, detail="Upload exceeds the maximum allowed size."
        )
    await asyncio.to_thread(truth_service.ingest_upload, file.filename or "", data)


@router.post("/extract", response_model=TruthDoc)
def extract() -> TruthDoc:
    return _truth_doc(
        truth_service.extract_truth(lambda: get_provider("truth_extract"))
    )


@router.get("/truth", response_model=TruthDoc)
def get_truth() -> TruthDoc:
    return _truth_doc(load())


@router.put("/truth", status_code=204)
def put_truth(body: TruthDoc) -> None:
    truth = Truth.from_dict(body.model_dump(by_alias=False))
    try:
        save(truth)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/confirm-inferences", status_code=204)
def confirm_inferences(body: ConfirmInferencesRequest) -> None:
    confirm_inferences_service(body.approved, body.approved_ids)


@router.get("/profile", response_model=ProfileStatus)
def profile() -> ProfileStatus:
    return ProfileStatus(has_profile=has_profile())


@router.get("/onboarding", response_model=OnboardingState)
def onboarding() -> OnboardingState:
    """First-run onboarding progress: provider setup, profile, CV review, tour."""
    return OnboardingState(**onboarding_service.get_state())


@router.put("/onboarding", response_model=OnboardingState)
def put_onboarding(body: OnboardingUpdate) -> OnboardingState:
    """Merge only the fields the client actually sent onto the stored state."""
    sent = body.model_dump(exclude_unset=True, by_alias=False)
    return OnboardingState(**onboarding_service.update_state(sent))


@router.get("/profile/answers", response_model=AnswersModel)
def get_profile_answers() -> AnswersModel:
    return AnswersModel.model_validate(load_answers().to_dict())


@router.put("/profile/answers", response_model=AnswersModel)
def put_profile_answers(body: AnswersUpdate) -> AnswersModel:
    """Merge only the fields the client actually sent onto the stored answers.

    Omitted fields must survive untouched — the wizard's field-by-field save
    flow means most PUTs carry a strict subset of the 21 fields, and treating
    absence the same as "clear this" would silently blank the rest.
    """
    sent = body.model_dump(exclude_unset=True, by_alias=False)
    return AnswersModel.model_validate(truth_service.update_answers(sent).to_dict())
