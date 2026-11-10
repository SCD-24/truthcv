"""Job-board routes: the API key for an API-backed job board."""

from __future__ import annotations

from fastapi import APIRouter

import truthcv.services.job_boards as job_boards_service

from .schemas import (
    JobBoardKeyStatus,
    JobBoardKeyUpdate,
    TestResult,
)

router = APIRouter()


@router.get("/job-boards/{source}/key", response_model=JobBoardKeyStatus)
def get_job_board_key(source: str) -> JobBoardKeyStatus:
    """Whether an API-backed board has a key saved. The key itself is never returned."""
    return JobBoardKeyStatus(**job_boards_service.key_status(source))


@router.put("/job-boards/{source}/key", response_model=JobBoardKeyStatus)
def put_job_board_key(source: str, body: JobBoardKeyUpdate) -> JobBoardKeyStatus:
    """Save (or, with an empty string, clear) an API-backed board's key."""
    return JobBoardKeyStatus(**job_boards_service.set_key(source, body.api_key))


@router.post("/job-boards/{source}/key/test", response_model=TestResult)
def test_job_board_key(source: str) -> TestResult:
    """Verify the saved key with one live request against the board's API."""
    ok, detail = job_boards_service.test_key(source)
    return TestResult(ok=ok, detail=detail)
