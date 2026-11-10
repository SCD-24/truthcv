"""Wizard REST routes wired to the backend modules.

The one hard rule lives in /api/render: the guardrail runs BEFORE any file is
produced, and if it fails nothing is rendered — the response is blocked=true with
the unverifiable tokens.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
from urllib.parse import urlencode

from fastapi import APIRouter, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, StreamingResponse

from providers import ProviderError, get_provider
from truth import load, save
from truth.answers import load as load_answers
from services.inferences import confirm_inferences as confirm_inferences_service
import services.screenings as screenings_service
import services.agent_config as agent_config_service
import services.agent_credentials as agent_credentials_service
import services.applications as applications_service
import services.supervisor as supervisor_service
import services.gmail as gmail_service
import services.job_boards as job_boards_service
import services.browser as browser_service
from api import guards
import services.settings as settings_service
import services.truth as truth_service
import services.onboarding as onboarding_service
import services.tailor as tailor_service
import services.connections as connections_service
from truth.model import Truth
from truth.pdf import has_profile

import applications as app_store
import modelrouting
import secretstore
from services.render_cv import (
    DraftMissing,
    _require_application,
    render_cv,
)
from services.cover_letter import generate_cover_letter
from connections import catalog
from connections.auth import gmail as gmail_auth
from providers import build_connection_provider
from runs import store as runs_store

from .company_finding_routes import router as company_finding_router
from .run_routes import router as run_router
from .screening_routes import router as screening_router
from .route_support import (
    _application_model,
    _models_result,
)
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
    AnswersModel,
    AnswersUpdate,
    ApiKeyRequest,
    ApplicationCreate,
    ApplicationListResponse,
    ApplicationModel,
    ApplicationUpdate,
    AtsWarning,
    CompleteLoginRequest,
    ConfirmInferencesRequest,
    ConnectionList,
    ConnectionStatus,
    ConnectionTestRequest,
    CoverLetterRequest,
    CoverLetterResult,
    GmailStatusModel,
    GmailSyncRequest,
    JevSettingsStatus,
    JevSettingsUpdate,
    JobBoardKeyStatus,
    JobBoardKeyUpdate,
    ModelList,
    BlockedClaimModel,
    OnboardingState,
    OnboardingUpdate,
    ProfileStatus,
    RenderRequest,
    RenderResult,
    RouteModel,
    RoutingModel,
    RoutingUpdate,
    SaveCoverLetterRequest,
    SaveCvRequest,
    SaveDocumentResult,
    SettingsStatus,
    SettingsUpdate,
    SigninQueue,
    SigninQueueSite,
    BrowserSession,
    BrowserSessionClosed,
    BrowserSessionRequest,
    PollLoginResult,
    StartLoginResult,
    TailorRequest,
    TailorResult,
    TestResult,
    TruthDoc,
)

router = APIRouter(prefix="/api")

logger = logging.getLogger(__name__)


router.include_router(screening_router)
router.include_router(run_router)
router.include_router(company_finding_router)


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


@router.post("/tailor", response_model=TailorResult)
def tailor_route(body: TailorRequest) -> TailorResult:
    result = tailor_service.tailor_posting(body.posting, get_provider)
    return TailorResult.model_validate(result)


@router.post("/confirm-inferences", status_code=204)
def confirm_inferences(body: ConfirmInferencesRequest) -> None:
    confirm_inferences_service(body.approved, body.approved_ids)


@router.post("/render", response_model=RenderResult)
def render_route(body: RenderRequest | None = None) -> RenderResult:
    # Thin marshalling: pull the request-derived arguments, run the framework-
    # free render workflow, and translate its outcome (or its DraftMissing) into
    # the HTTP response. All business logic — the guardrail, scope-building and
    # approval-filtering — lives in services/render_cv.py.
    app_id = body.application_id if body else None
    approved: set[str] = set()
    denied: set[str] = set()
    if body and body.approvals:
        approved = set(body.approvals.approved_claim_ids)
        denied = set(body.approvals.denied_claim_ids)

    try:
        outcome = render_cv(application_id=app_id, approved=approved, denied=denied)
    except DraftMissing:
        raise HTTPException(
            status_code=400, detail="Tailor a posting before rendering."
        ) from None

    if outcome.blocked:
        blocked = [
            BlockedClaimModel(
                claim_id=c.claim_id,
                experience_id=c.experience_id,
                text=c.text,
                tokens=c.tokens,
            )
            for c in outcome.blocked_claims
        ]
        return RenderResult(
            blocked=True, unverifiable=outcome.unverifiable, blocked_claims=blocked
        )

    # A pure wizard preview (no application) has no saved document to fall back
    # on, so an unavailable backend is still a hard error there. An attached
    # render keeps its saved link even when nothing could be produced.
    if outcome.pdf_url is None and outcome.docx_url is None and not app_id:
        raise HTTPException(
            status_code=500,
            detail="Rendering backend unavailable (WeasyPrint/pandoc not installed).",
        )

    return RenderResult(
        blocked=False,
        ats_warnings=[AtsWarning(**w) for w in outcome.ats_warnings],
        pdf_url=outcome.pdf_url,
        docx_url=outcome.docx_url,
        html=outcome.html,
        render_unavailable=outcome.render_unavailable,
    )


@router.get("/applications", response_model=list[ApplicationModel])
def list_applications(q: str = "") -> list[ApplicationModel]:
    """Every tracked job application, most recent first.

    q: case-insensitive substring filter over company, website, application URL,
    notes, posting and role; empty returns everything
    """
    apps = applications_service.list_applications(q)
    return [_application_model(a) for a in apps]


@router.get("/applications/page", response_model=ApplicationListResponse)
def list_applications_page(
    limit: int = 25, offset: int = 0, sort: str = "date", direction: str = "desc", q: str = ""
) -> ApplicationListResponse:
    """One page of applications, server-sorted and paginated.

    ``q`` is the same case-insensitive substring filter as GET /api/applications
    (company, website, application URL, notes, posting, role); it is applied
    before paging so ``total`` counts matches.

    Reads the application store in-process and returns a paginated, sorted page
    of applications with the total count across all records. Sort keys and
    direction are passed through and echoed in the response.

    A negative offset is clamped to 0 rather than rejected: it is a client that
    paged past the start, and an empty first page is a worse answer than the
    first page. An offset past the end yields an empty page — the total tells
    the client it overshot.
    """
    offset = max(0, offset)
    try:
        apps, total = applications_service.list_applications_page(
            limit=limit, offset=offset, sort=sort, direction=direction, q=q
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ApplicationListResponse(
        applications=[_application_model(a) for a in apps],
        total=total,
        limit=limit,
        offset=offset,
        sort=sort,
        direction=direction,
    )


@router.get("/applications/export")
def export_applications() -> StreamingResponse:
    """Download every application as a CSV plus per-company document folders.

    Bundled as one zip so a user gets an offline, portable record of the whole
    tracker: the table as `applications.csv`, and each application's rendered
    files grouped under a folder named for its company.
    """
    apps = applications_service.list_applications()
    archive = applications_service.build_export_zip(apps)
    headers = {"Content-Disposition": 'attachment; filename="applications.zip"'}
    return StreamingResponse(archive, media_type="application/zip", headers=headers)


@router.post("/applications", response_model=ApplicationModel, status_code=201)
def create_application(body: ApplicationCreate) -> ApplicationModel:
    """Create a new application record from client-supplied fields."""
    app = applications_service.create_application_record(body.model_dump(by_alias=False))
    return _application_model(app)


@router.put("/applications/{app_id}", response_model=ApplicationModel)
def update_application(app_id: str, body: ApplicationUpdate) -> ApplicationModel:
    """Patch an application's editable fields (None fields are left unchanged)."""
    patch = body.model_dump(by_alias=False, exclude_none=True)
    app = applications_service.update_application_record(app_id, patch)
    if app is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    return _application_model(app)


@router.delete("/applications/{app_id}", status_code=204)
def delete_application(app_id: str) -> None:
    """Delete an application and remove its owned document files."""
    if not app_store.delete(app_id):
        raise HTTPException(status_code=404, detail="Application not found.")


@router.put("/applications/{app_id}/cv", response_model=SaveDocumentResult)
def save_application_cv(app_id: str, body: SaveCvRequest) -> SaveDocumentResult:
    """Render and save edited CV HTML onto an application.

    A manual edit is a deliberate human decision, so it is trusted and saved
    as-is — the truthfulness guardrail only gates the automatic AI generation
    (/render, /tailor), not a document the user edited by hand.
    """
    app, produced = applications_service.save_cv(app_id, body.html)
    return SaveDocumentResult(
        blocked=False,
        application=_application_model(app),
        render_unavailable=not produced,
    )


@router.put("/applications/{app_id}/cover-letter", response_model=SaveDocumentResult)
def save_application_cover_letter(
    app_id: str, body: SaveCoverLetterRequest
) -> SaveDocumentResult:
    """Render and save edited cover-letter text on an app.

    A manual edit is trusted and saved as-is; the truthfulness guardrail only
    gates the automatic AI generation, not a hand-edited document.
    """
    app, produced = applications_service.save_cover_letter(app_id, body.text)
    return SaveDocumentResult(
        blocked=False,
        application=_application_model(app),
        render_unavailable=not produced,
    )


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


@router.get("/settings/jev", response_model=JevSettingsStatus)
def get_jev_settings() -> JevSettingsStatus:
    """Whether Jev cross-checking is configured. The key itself is never returned."""
    return JevSettingsStatus(**settings_service.jev_status())


@router.put("/settings/jev", response_model=JevSettingsStatus)
def put_jev_settings(body: JevSettingsUpdate) -> JevSettingsStatus:
    """Save (or, with an empty string, clear) the Jev API key and/or the
    useForScreening / useForEmailTracking toggles. Saving a non-empty key
    requires encryption."""
    status = settings_service.update_jev(
        body.api_key, body.use_for_screening, body.use_for_email_tracking
    )
    return JevSettingsStatus(**status)


@router.post("/settings/jev/test", response_model=TestResult)
def test_jev_settings() -> TestResult:
    """Verify the saved Jev key with one live request."""
    from screening import jev

    ok, detail = jev.check_key(secretstore.get_connection("jev").get("apiKey", ""))
    return TestResult(ok=ok, detail=detail)


@router.post("/auth/gmail/start", response_model=StartLoginResult)
def start_gmail_login(request: Request) -> StartLoginResult:
    """Begin the Gmail OAuth flow. Gated on the useForEmailTracking opt-in."""
    guards.require_gmail_tracking_enabled()
    redirect_uri = gmail_auth.redirect_uri_override() or str(request.url_for("gmail_callback"))
    try:
        return StartLoginResult.model_validate(gmail_auth.start_login(redirect_uri))
    except gmail_auth.AuthError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/auth/gmail/callback", name="gmail_callback")
def complete_gmail_login(
    code: str | None = None, state: str | None = None, error: str | None = None
) -> RedirectResponse:
    """Complete the Gmail OAuth flow, then redirect back to the app root.

    Gated the same as /start: a request reaching here without the feature
    enabled 403s rather than silently completing a login the operator can't
    use yet.

    Unlike a JSON API route, this one is a browser redirect target: there is
    nowhere for a JSON error page to be seen. Google's own denied-consent
    redirect (`?error=access_denied`, with no `code`/`state`) and a failed
    token exchange are therefore never raised as HTTP errors — both redirect
    back to the app root with a `gmailError` query param instead of the
    normal success redirect, so `code`/`state` are optional here. The same
    goes for the feature gate: closed mid-flow (key cleared or the toggle
    turned off while the consent screen was open), it redirects with
    `gmailError=not_enabled` rather than rendering a 403 JSON body.
    """
    code_error = gmail_service.complete_login(code, state, error)
    if code_error:
        query = urlencode({"gmailError": code_error})
        return RedirectResponse(url=f"/?{query}")
    return RedirectResponse(url="/")


@router.get("/gmail/status", response_model=GmailStatusModel)
def get_gmail_status() -> GmailStatusModel:
    """Gmail connection status for the Settings page.

    Unlike /auth/gmail/start and /callback, this route never 403s: it
    reports the useForEmailTracking gate's own state (tracking_enabled) so
    the UI can explain why Gmail is unavailable, rather than getting a
    blanket error.
    """
    return GmailStatusModel(**gmail_service.status())


@router.post("/gmail/responses/sync")
def sync_gmail_responses(body: GmailSyncRequest | None = None) -> dict:
    """Trigger a Gmail response-tracking sync. Gated the same as the OAuth
    routes: requires a saved Jev key and useForEmailTracking enabled.

    Returns gmailsync.service.run_sync's own summary dict unchanged.
    """
    guards.require_gmail_tracking_enabled()
    from gmailsync import service as gmailsync_service

    force = body.force if body is not None else False
    return gmailsync_service.run_sync(force=force)


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


@router.get("/browser/signin-queue", response_model=SigninQueue)
def get_signin_queue() -> SigninQueue:
    """Sites the agent hit a sign-in wall on, grouped by host.

    Derived from the screening store on every call rather than kept as its own
    state: the agent's experience is the only source of truth here, so an entry
    exists exactly as long as a posting is still waiting behind that sign-in.
    """
    sites = [SigninQueueSite(**e) for e in screenings_service.signin_queue()]
    return SigninQueue(sites=sites)


def _session_from(data: dict) -> BrowserSession:
    return BrowserSession(
        open=data.get("open", False),
        url=data.get("url"),
        started_at=data.get("startedAt"),
        evict_deadline=data.get("evictDeadline"),
    )


@router.get("/browser/session", response_model=BrowserSession)
def get_browser_session() -> BrowserSession:
    """Whether an attended sign-in session is open, and at which URL."""
    return _session_from(browser_service.forward_to_session_server("/session", method="GET"))


@router.post("/browser/session", response_model=BrowserSession)
def post_browser_session(payload: BrowserSessionRequest) -> BrowserSession:
    """Open an attended sign-in session at a URL.

    Refused with 409 while a run is in progress: unattended runs win, and the
    operator is told to try again shortly rather than the run being disturbed.
    """
    if screenings_service.host_of(payload.url) == "":
        raise HTTPException(status_code=422, detail="An http(s) URL is required")
    return _session_from(
        browser_service.forward_to_session_server("/session", method="POST", body={"url": payload.url})
    )


@router.delete("/browser/session", response_model=BrowserSessionClosed)
def delete_browser_session() -> BrowserSessionClosed:
    """Close the attended session and release the browser.
    
    When closing a session, re-arm any login-blocked items whose host matches
    the closed session's URL, so they re-enter the queue for the next run.
    """
    data = browser_service.close_session()
    return BrowserSessionClosed(
        closed=data["closed"],
        closing=data["closing"],
        reserving=data["reserving"],
        signins_cleared=data["signins_cleared"],
    )


@router.post("/cover-letter", response_model=CoverLetterResult)
def cover_letter(body: CoverLetterRequest) -> CoverLetterResult:
    # Thin marshalling: validate the id (404 on miss), run the framework-free
    # cover-letter workflow, and translate its outcome — or its DraftMissing, or
    # an LLM failure — into the HTTP response. All business logic (posting
    # resolution, render-scoped approvals, the guardrail and best-effort render)
    # lives in services/cover_letter.py.
    _require_application(body.application_id)

    approved_ids = set(body.approvals.approved_claim_ids) if body.approvals else set()
    denied_ids = set(body.approvals.denied_claim_ids) if body.approvals else set()
    app_id = body.application_id if body.application_id else None

    try:
        outcome = generate_cover_letter(
            application_id=app_id,
            posting=body.posting,
            preset_id=body.preset_id,
            length=body.length,
            provider=get_provider("cover_letter"),
            approved_ids=approved_ids,
            denied_ids=denied_ids,
        )
    except DraftMissing:
        raise HTTPException(
            status_code=400, detail="Tailor a posting before generating a cover letter."
        ) from None
    except ProviderError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=f"The language model call failed: {type(e).__name__}: {e}",
        ) from e

    if outcome.blocked:
        blocked_claims = [
            BlockedClaimModel(
                claim_id=c.claim_id,
                experience_id=c.experience_id,
                text=c.text,
                tokens=c.tokens,
            )
            for c in outcome.blocked_claims
        ]
        return CoverLetterResult(
            blocked=True,
            unverifiable=outcome.unverifiable,
            blocked_claims=blocked_claims,
        )

    # Only a pure preview (no application) hard-errors on an unavailable backend;
    # an attached save keeps its recorded link.
    if outcome.pdf_url is None and outcome.docx_url is None and not app_id:
        raise HTTPException(
            status_code=500,
            detail="Rendering backend unavailable (WeasyPrint/pandoc not installed).",
        )
    return CoverLetterResult(
        blocked=False,
        pdf_url=outcome.pdf_url,
        docx_url=outcome.docx_url,
        text=outcome.text,
        render_unavailable=outcome.render_unavailable,
        style_warnings=[AtsWarning(**w) for w in outcome.style_warnings],
    )


@router.get("/settings", response_model=SettingsStatus)
def get_settings() -> SettingsStatus:
    return SettingsStatus(**settings_service.settings_status())


@router.post("/settings", response_model=SettingsStatus)
def post_settings(body: SettingsUpdate) -> SettingsStatus:
    """Old single-provider POST shape, shimmed onto the v2 store: the key/host
    lands in that provider's connection, and {connection, model} becomes the
    routing default."""
    status = settings_service.save_v1_settings(
        body.active_provider, body.api_key, body.ollama_host, body.model
    )
    return SettingsStatus(**status)


@router.post("/settings/test", response_model=TestResult)
def test_settings(body: SettingsUpdate) -> TestResult:
    ok, detail = settings_service.test_v1_settings(
        body.active_provider,
        body.api_key,
        body.ollama_host,
        body.model,
        provider_factory=lambda: get_provider(refresh=True),
    )
    return TestResult(ok=ok, detail=detail)


@router.post("/models", response_model=ModelList)
def list_models(body: SettingsUpdate) -> ModelList:
    """Live model list for the selected provider, pulled from its API/SDK."""
    models, card = settings_service.list_v1_models(
        body.active_provider, body.api_key, body.ollama_host
    )
    return _models_result(models, card)


def _connection_status(card_key: str) -> ConnectionStatus:
    meta = catalog.card(card_key)
    conn = secretstore.get_connection(card_key)
    oauth = conn.get("oauth") or {}
    has_key = bool(conn.get("apiKey")) or (card_key == "ollama" and bool(conn.get("baseUrl")))
    return ConnectionStatus(
        provider=card_key,
        label=meta["label"],
        modes=list(meta["modes"]),
        subscription_connected=bool(oauth.get("accessToken")),
        api_key_connected=has_key,
        auth_mode=conn.get("authMode", ""),
        expires_at=oauth.get("expiresAt"),
        connected_at=oauth.get("connectedAt"),
    )


@router.get("/auth/status", response_model=ConnectionList)
def get_connection_status() -> ConnectionList:
    return ConnectionList(
        encryption_available=secretstore.encryption_available(),
        connections=[_connection_status(key) for key in catalog.card_keys()],
    )


@router.post("/auth/{provider}/start", response_model=StartLoginResult)
def start_connection_login(provider: str) -> StartLoginResult:
    return StartLoginResult.model_validate(connections_service.start_login(provider))


# Specific route must come BEFORE the generic /{provider}/complete to avoid
# FastAPI matching /api/auth/claude/complete against the general pattern.
@router.post("/auth/claude/complete", response_model=ConnectionStatus)
def complete_claude_login_alias(body: CompleteLoginRequest) -> ConnectionStatus:
    """Deprecated: delegates to the generic /complete handler. Retained so a
    deployed web bundle from before this change does not break mid-deploy."""
    return _complete_login("claude", body)


@router.post("/auth/{provider}/complete", response_model=ConnectionStatus)
def _complete_login(provider: str, body: CompleteLoginRequest) -> ConnectionStatus:
    connections_service.complete_login(provider, body.code)
    return _connection_status(provider)


@router.post("/auth/{provider}/poll", response_model=PollLoginResult)
def _poll_login(provider: str) -> PollLoginResult:
    result = connections_service.poll_login(provider)
    if result.get("status") == "complete":
        return PollLoginResult(
            status="complete",
            connected_at=result.get("connectedAt"),
            expires_at=result.get("expiresAt"),
            scope=result.get("scope"),
        )
    return PollLoginResult(
        status="pending",
        interval_seconds=result.get("intervalSeconds"),
    )


@router.post("/auth/{provider}/key", response_model=ModelList)
def post_connection_key(provider: str, body: ApiKeyRequest) -> ModelList:
    models = connections_service.save_key(provider, body.api_key, body.base_url, body.bearer)
    return _models_result(models, provider)


@router.get("/auth/{provider}/models", response_model=ModelList)
def get_connection_models(provider: str) -> ModelList:
    connections_service.require_card(provider)
    try:
        models = build_connection_provider(provider, None).list_models()
    except ProviderError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001 — surface upstream LLM/SDK errors cleanly
        raise HTTPException(status_code=502, detail=f"{type(e).__name__}: {e}") from e
    return _models_result(models, provider)


@router.post("/auth/{provider}/test", response_model=TestResult)
def test_connection(provider: str, body: ConnectionTestRequest) -> TestResult:
    connections_service.require_card(provider)
    try:
        provider_obj = build_connection_provider(provider, body.model)
        provider_obj.complete("ping", [{"role": "user", "content": "ping"}])
        return TestResult(ok=True, detail="Connection succeeded.")
    except HTTPException as e:
        return TestResult(ok=False, detail=str(e.detail))
    except Exception as e:  # noqa: BLE001
        return TestResult(ok=False, detail=f"{type(e).__name__}: {e}")


@router.post("/auth/{provider}/logout", response_model=ConnectionStatus)
def logout_connection(provider: str, mode: str | None = None) -> ConnectionStatus:
    """Disconnect `provider`, defaulting to the card's currently active mode.

    Without an explicit `mode`, we clear whichever mode is currently active
    (oauth or apikey), so the card no longer reports a connection in either
    mode. Passing `mode` clears just that mode and leaves the other intact —
    that is the same semantics the existing per-mode logout tests pin.
    """
    connections_service.logout(provider, mode)
    return _connection_status(provider)


@router.get("/routing", response_model=RoutingModel)
def get_routing() -> RoutingModel:
    """Get the current model routing configuration."""
    return _routing_model(modelrouting.load())


@router.put("/routing", response_model=RoutingModel)
def put_routing(body: RoutingUpdate) -> RoutingModel:
    """Merge only the fields the client sent onto the stored routing.

    A field explicitly sent as null is not the same as an absent field: it
    clears that route (`default`/`agent` sent as null, or a `tasks` entry
    sent as null, removes it) instead of leaving the stored value untouched.
    """
    # Prepare update from body — exclude_unset only, so an explicit null
    # survives into update_dict and is distinguishable from an absent field.
    update_dict = body.model_dump(exclude_unset=True, by_alias=False)
    return _routing_model(settings_service.update_routing(update_dict))


def _routing_model(routing: modelrouting.Routing) -> RoutingModel:
    """Convert a stored Routing to its API wire model."""
    return RoutingModel(
        tasks={k: _route_model(v) for k, v in routing.tasks.items()},
        agent=_route_model(routing.agent) if routing.agent else None,
        default=_route_model(routing.default) if routing.default else None,
        agent_stages={k: _route_model(v) for k, v in routing.agent_stages.items()},
    )


def _route_model(route: modelrouting.Route) -> RouteModel:
    """Convert a stored Route to its API wire model."""
    return RouteModel(
        connection=route.connection,
        model=route.model,
        effort=route.effort,
    )
