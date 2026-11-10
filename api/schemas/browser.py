"""Wire models for the browser service: sessions and the sign-in queue."""

from __future__ import annotations

from .common import _Camel


class SigninQueueSite(_Camel):
    """One host the agent could not get past a sign-in wall on."""

    # The full host, e.g. "acme.wd3.myworkdayjobs.com". Deliberately not the
    # registrable domain: each Workday tenant is a separate account, so
    # collapsing to "myworkdayjobs.com" would merge unrelated sign-ins.
    host: str
    signin_url: str
    # How many approved postings are stuck behind this one sign-in.
    waiting: int
    last_blocked_at: str
    companies: list[str]


class SigninQueue(_Camel):
    """GET /api/browser/signin-queue — sites needing the operator to sign in."""

    sites: list[SigninQueueSite]


class BrowserSession(_Camel):
    """GET/POST /api/browser/session — forwarded from browser/session-server.js."""

    open: bool
    url: str | None = None
    started_at: str | None = None
    # Set once a run has asked for the browser back. The session page counts
    # down to this and the session server closes the session when it passes.
    evict_deadline: str | None = None


class BrowserSessionRequest(_Camel):
    """POST /api/browser/session body."""

    url: str


class BrowserSessionClosed(_Camel):
    """DELETE /api/browser/session.

    `closed`, `closing` and `reserving` are three distinct states, not two
    opposed bits: the session server confirms a browser actually exited
    before reporting `closed`, so an ordinary close reports `closed=false,
    closing=true` while it waits; a close arriving while open() is still
    resolving the request (no browser launched yet) is refused outright as
    `closed=false, reserving=true` rather than either applied or silently
    dropped — see browser/session-server.js's close(). All three false only
    for a request that named no session to close.
    """

    closed: bool
    closing: bool = False
    reserving: bool = False
    signins_cleared: int = 0
