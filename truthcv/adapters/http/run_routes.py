"""Run routes: the agent run history, a run's URL ledger and stopping a run."""

from __future__ import annotations

from fastapi import APIRouter

import truthcv.services.runs as runs_service

from .schemas import RunListResponse, RunModel, RunStopResult, UrlLedgerResponse

router = APIRouter()


@router.get("/runs", response_model=RunListResponse)
def list_runs(limit: int = 50, offset: int = 0) -> RunListResponse:
    """One page of the most recently started agent runs, newest first.

    Reads the shared data volume in-process via runs.store — this does NOT
    proxy to the supervisor, unlike the /agent/* routes, because the run
    records live on the volume the API already has access to.

    A negative offset is clamped to 0 rather than rejected: it is a client
    that paged past the start, and an empty first page is a worse answer than
    the first page. An offset past the end yields an empty page — the total
    tells the client it overshot.

    The page and its total come from one read of the store, so they always
    describe the same set of runs; a run recorded between two reads would
    otherwise be reported as an older run that had gone missing.
    """
    offset = max(0, offset)
    runs, total = runs_service.list_runs_page(limit, offset)
    return RunListResponse(
        runs=[RunModel(**r) for r in runs],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/runs/{run_id}", response_model=RunModel)
def get_run(run_id: str) -> RunModel:
    """A single run record, or 404 if no run with this id has been recorded."""
    return RunModel(**runs_service.get_run(run_id))


# Page size bounds for GET /runs/{run_id}/urls.
URL_LEDGER_DEFAULT_LIMIT = runs_service.URL_LEDGER_DEFAULT_LIMIT
URL_LEDGER_MAX_LIMIT = runs_service.URL_LEDGER_MAX_LIMIT


@router.get("/runs/{run_id}/urls", response_model=UrlLedgerResponse)
def get_run_urls(
    run_id: str,
    source: str = "",
    outcome: str = "",
    limit: int = URL_LEDGER_DEFAULT_LIMIT,
    offset: int = 0,
    channel: str = "",
) -> UrlLedgerResponse:
    """One page of the run's URL ledger, optionally filtered by source and
    outcome. 404 for an unknown run, 400 for an unknown outcome; limit is
    clamped to 1..URL_LEDGER_MAX_LIMIT and a negative offset to 0."""
    entries, total = runs_service.url_ledger_page(
        run_id, source, outcome, limit, offset, channel
    )
    return UrlLedgerResponse(entries=entries, total=total)


@router.post("/runs/{run_id}/stop", response_model=RunStopResult)
def post_run_stop(run_id: str) -> RunStopResult:
    """Stop a run: cancel it through the supervisor if it owns the run, or
    close an orphaned record as failed/orphaned otherwise.
    """
    outcome, run = runs_service.stop_run(run_id)
    return RunStopResult(outcome=outcome, run=RunModel(**run))
