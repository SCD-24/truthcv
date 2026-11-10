"""Browser routes: the sign-in queue and the attended sign-in session."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

import services.screenings as screenings_service
import services.browser as browser_service

from .schemas import (
    BrowserSession,
    BrowserSessionClosed,
    BrowserSessionRequest,
    SigninQueue,
    SigninQueueSite,
)

router = APIRouter()


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
