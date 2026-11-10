"""Agent routes: config, LLM credentials, run accounting and the supervisor controls."""

from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, Header, HTTPException

import services.agent_config as agent_config_service
import services.agent_credentials as agent_credentials_service
import services.supervisor as supervisor_service
import modelrouting
from runs import store as runs_store

from .schemas import (
    AgentConfigModel,
    AgentCancelResult,
    AgentConfigUpdate,
    AgentLlmCredentials,
    AgentLlmTokenRefresh,
    AgentLlmTokenResult,
    AgentRunAccountingResult,
    AgentRunFinish,
    AgentRunResult,
    AgentRunStart,
    AgentStatus,
)

router = APIRouter()


@router.get("/agent/config", response_model=AgentConfigModel)
def get_agent_config(include_feed: bool = False) -> AgentConfigModel:
    """Fetch agent config with resolved company boards and composed search queries.

    Prunes board entries for companies no longer on the target watchlist.

    ``include_feed`` opts into pulling postings from the configured API-backed
    boards, which means an outbound HTTP call. It is off by default and only
    the agent asks for it: the web UI loads this endpoint on two pages, and
    making every page load wait on a third-party API — or fail with it — is a
    cost paid for nothing, since the browser never renders the postings.
    """
    return AgentConfigModel.model_validate(
        agent_config_service.build_agent_config(include_feed)
    )


@router.put("/agent/config", response_model=AgentConfigModel)
def put_agent_config(body: AgentConfigUpdate) -> AgentConfigModel:
    """Merge only the fields the client sent onto the stored config.

    Profiles are WHOLESALE-REPLACED (not merged) because a null or omitted
    profiles field never reaches the merge dict. job_boards is replaced the
    same way, but first NORMALISED: the response-only keys (domain,
    effective_signin_url, is_default, is_api, key_required) are stripped — they are
    derived, and a stored copy is a second writer that can go stale — and a default-source
    entry is DROPPED only when it carries neither a signin_url NOR a disabled
    flag, so a client echoing back the resolved GET list does not bloat
    storage with the defaults. A default-source entry WITH a signin_url
    override or with ``enabled: false`` is kept, since both are legitimate
    per-board state that would otherwise have nowhere to live.

    The optional numeric windows are the exception to exclude_none: for them a
    null is a real value meaning "unset", and dropping it made those fields
    impossible to clear once set. Emptying the box on the Agents page sends
    null, the merge discarded it, and the UI then repainted the old value
    beside a "saved" indicator. They are re-applied explicitly below, still
    only when the client actually sent the key.
    """
    sent = body.model_dump(exclude_unset=True, by_alias=False)
    saved = agent_config_service.update_agent_config(sent)
    data = saved.to_dict()
    data["job_boards"] = agent_config_service.resolved_job_boards(saved)
    return AgentConfigModel.model_validate(data)


@router.get("/agent/llm-credentials", response_model=AgentLlmCredentials)
def get_agent_llm_credentials(x_agent_token: str = Header(default="")) -> AgentLlmCredentials:
    """Guarded: only the unattended agent (holding AGENT_API_TOKEN) may call this.

    Returns 404 rather than 401/403 so the response carries no authentication hint.
    Serves all four connection cards; the caller picks its wire format from the
    `wire` field on the response rather than assuming Anthropic.
    """
    secret = os.environ.get("AGENT_API_TOKEN", "").strip()
    given = x_agent_token.encode("utf-8", "surrogateescape")
    if not secret or not hmac.compare_digest(given, secret.encode("utf-8")):
        raise HTTPException(status_code=404)

    return AgentLlmCredentials.model_validate(
        agent_credentials_service.credentials_for_route(modelrouting.load().agent)
    )


@router.post("/agent/llm-token/refresh", response_model=AgentLlmTokenResult)
def post_agent_llm_token_refresh(
    body: AgentLlmTokenRefresh, x_agent_token: str = Header(default="")
) -> AgentLlmTokenResult:
    """Guarded (404 without AGENT_API_TOKEN): force a fresh subscription token
    after the caller saw `rejectedTokenSha256` rejected. 404 when the card has
    no oauth token or is in apikey mode; 503 when reconnecting is needed.
    The token is response-only and never logged."""
    if not _agent_token_ok(x_agent_token):
        raise HTTPException(status_code=404)
    token = agent_credentials_service.refresh_token(body.provider, body.rejected_token_sha256)
    return AgentLlmTokenResult(token=token)


@router.get("/agent/llm-routes")
def get_agent_llm_routes(x_agent_token: str = Header(default="")) -> dict:
    """Guarded (404 without AGENT_API_TOKEN): credentials for the apply route
    and each agent stage. A stage with no route resolves to null. Response-only
    egress; tokens are never logged."""
    if not _agent_token_ok(x_agent_token):
        raise HTTPException(status_code=404)
    return agent_credentials_service.stage_routes()


def _agent_token_ok(given: str) -> bool:
    """Whether `given` matches AGENT_API_TOKEN. Same rule as
    get_agent_llm_credentials: an unset secret matches nothing."""
    secret = os.environ.get("AGENT_API_TOKEN", "").strip()
    if not secret:
        return False
    return hmac.compare_digest(
        given.encode("utf-8", "surrogateescape"), secret.encode("utf-8")
    )


@router.post("/agent/runs/{run_id}/start", response_model=AgentRunAccountingResult)
def post_agent_run_start(
    run_id: str,
    body: AgentRunStart,
    x_agent_token: str = Header(default=""),
) -> AgentRunAccountingResult:
    """Create the run record for `run_id`, before the run does any work.

    Guarded by AGENT_API_TOKEN and 404 on mismatch, matching
    get_agent_llm_credentials — this writes to the ledger the operator reads,
    so it is deliberately NOT on the unauthenticated /mcp tool surface and is
    not a capability the model can reach.

    Until this existed the only way a run record came into being was the model
    calling the ``start_run`` MCP tool, so a run that failed before its first
    turn — the LLM provider rejecting every attempt, a precondition abort, an
    MCP connection failure — left no trace in Recent runs at all. That is the
    exact case an operator most needs to see.

    ``runs.store.start`` is idempotent, so the model's later ``start_run`` with
    the same id joins this record rather than resetting it.
    """
    if not _agent_token_ok(x_agent_token):
        raise HTTPException(status_code=404)
    runs_store.start(run_id, trigger=body.trigger, apply_cap=body.apply_cap)
    return AgentRunAccountingResult(recorded=True)


@router.post("/agent/runs/{run_id}/finish", response_model=AgentRunAccountingResult)
def post_agent_run_finish(
    run_id: str,
    body: AgentRunFinish,
    x_agent_token: str = Header(default=""),
) -> AgentRunAccountingResult:
    """Close out `run_id` — but only while it is still running.

    The supervisor calls this on every child exit, including the ones no
    in-container code survives (SIGKILL after a cancel, spawn failure). It
    reports ``recorded=False`` when the model's own ``finish_run`` already
    closed the record: that account names where the run actually stopped and
    must win over an exit-code-derived one.
    """
    if not _agent_token_ok(x_agent_token):
        raise HTTPException(status_code=404)
    try:
        record = runs_store.finish_if_running(
            run_id, status=body.status, stopped_reason=body.stopped_reason
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AgentRunAccountingResult(recorded=record is not None)


@router.get("/agent/status", response_model=AgentStatus)
def get_agent_status() -> AgentStatus:
    """Return the agent supervisor's running/idle state.

    Forwards to supervisor.js GET /status over the compose network.
    Returns 503 when the agent container is unreachable, 502 when it answers
    with an error (403 = AGENT_API_TOKEN mismatch).
    """
    data = supervisor_service.forward_to_supervisor("/status", method="GET")
    return AgentStatus(
        running=data.get("running", False),
        cancelling=data.get("cancelling", False),
        last_started_at=data.get("lastStartedAt"),
        last_finished_at=data.get("lastFinishedAt"),
        last_exit_code=data.get("lastExitCode"),
        last_cancelled=data.get("lastCancelled", False),
        # Absent on an older supervisor image — .get() defaults to None rather
        # than raising, so this route does not 500 against one.
        current_run_id=data.get("currentRunId"),
        last_run_id=data.get("lastRunId"),
    )


@router.post("/agent/run", response_model=AgentRunResult)
def post_agent_run() -> AgentRunResult:
    """Trigger an immediate agent run via the supervisor control server.

    Fire-and-forget: returns as soon as the supervisor acknowledges the
    trigger — does NOT wait for the run to complete. Returns 503 when the
    agent container is unreachable.
    """
    data = supervisor_service.forward_to_supervisor("/run", method="POST")
    return AgentRunResult(
        started=data.get("started", False),
        running=data.get("running", False),
    )


@router.post("/agent/cancel", response_model=AgentCancelResult)
def post_agent_cancel() -> AgentCancelResult:
    """Stop the run in progress via the supervisor control server.

    Fire-and-forget, like the trigger: the supervisor signals the run's process
    group and answers immediately, so the run may still be tearing down when
    this returns. Poll GET /api/agent/status for the transition to idle.
    Returns 503 when the agent container is unreachable, 502 when it answers
    with an error (403 = AGENT_API_TOKEN mismatch).
    """
    data = supervisor_service.forward_to_supervisor("/cancel", method="POST")
    return AgentCancelResult(
        cancelled=data.get("cancelled", False),
        running=data.get("running", False),
    )
