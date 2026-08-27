"""Render workflow: build guardrail scopes, validate, then produce CV files.

Framework-free — nothing here imports FastAPI. The HTTP adapter in
``api/routes.py`` marshals a ``RenderRequest`` into the explicit arguments this
module takes and turns the returned :class:`RenderOutcome` back into the wire
``RenderResult``.

The one hard rule lives here: the guardrail runs BEFORE any file is produced,
and if it fails nothing is rendered — the outcome comes back ``blocked=True``
with the unverifiable tokens and the flagged claims.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import applications as app_store
import tailor as tailor_engine
from guardrail import Scope, validate
from render import lint, render_docx, render_html, render_pdf, verify_pdf
from render.pdf import RenderUnavailable
from render.verify import default_max_pages
from services.errors import NotFound
from truth import load


class DraftMissing(Exception):
    """No tailored draft exists to render.

    Not a ``ServiceError``: the HTTP contract for this case is 400 (not the 404
    a ``NotFound`` would map to), so the adapter catches this explicitly and
    raises its own 400 response.
    """


@dataclass
class RenderedClaim:
    """A whole draft bullet/line that tripped the guardrail, with a stable id."""

    claim_id: str
    experience_id: str
    text: str
    tokens: list[str] = field(default_factory=list)


@dataclass
class RenderOutcome:
    """Everything the HTTP adapter needs to build a ``RenderResult``.

    ``ats_warnings`` are the raw warning dicts from the linter/verifier; the
    adapter converts them to its wire model. The service deliberately does NOT
    decide the "no application and no output" hard-error case — the adapter
    owns that (it maps to HTTP 500, not the 503 a ``services.errors`` exception
    would produce).
    """

    blocked: bool = False
    unverifiable: list[str] = field(default_factory=list)
    blocked_claims: list[RenderedClaim] = field(default_factory=list)
    ats_warnings: list[dict] = field(default_factory=list)
    pdf_url: str | None = None
    docx_url: str | None = None
    html: str | None = None
    render_unavailable: bool = False


def _claim_id(scope_id: str, text: str) -> str:
    """Deterministic id for a blocked claim so the UI can round-trip decisions."""
    import hashlib

    return hashlib.sha256(f"{scope_id}\n{text}".encode("utf-8")).hexdigest()[:16]


def _contact_line(profile) -> str:
    """Compose the header's single contact line from identity fields.

    Identity is guardrail-exempt, so this is presentation only: email, phone,
    location and any link urls, joined with a middot, skipping blanks.
    """
    parts = [profile.email, profile.phone, profile.location]
    parts += [link.url for link in profile.links if link.url]
    return " · ".join(p for p in parts if p)


def _render_scopes(draft, truth) -> list[Scope]:
    """One guardrail scope per draft block, keyed by its truth source id."""
    exp_by_id = {e.id: e for e in truth.experiences}
    edu_by_id = {e.id: e for e in truth.education}
    scopes: list[Scope] = []
    for de in draft.experiences:
        te = exp_by_id.get(de.source_id)
        allowed = (
            [te.role, te.company, te.start, te.end] + [b.value for b in te.bullets]
            if te else []
        )
        scopes.append(
            Scope(id=de.source_id, texts=[de.role, de.company, de.dates, *de.bullets], allowed=allowed)
        )
    for de in draft.education:
        te = edu_by_id.get(de.source_id)
        allowed = [te.degree, te.school, te.start, te.end] if te else []
        scopes.append(Scope(id=de.source_id, texts=[de.degree, de.school, de.dates], allowed=allowed))
    scopes.append(Scope(id="skills", texts=list(draft.skills), allowed=[s.value for s in truth.skills]))
    # The profile summary is a claim: validate it (in its own scope) against
    # every truth fact it may legitimately draw on — role/company/dates/bullets
    # across all experiences and education. Identity fields (name/contact/links)
    # are exempt and never enter a scope. Skills flow in via global_values.
    summary = truth.profile.summary.strip()
    if summary:
        allowed_summary: list[str] = []
        for te in truth.experiences:
            allowed_summary += [te.role, te.company, te.start, te.end]
            allowed_summary += [b.value for b in te.bullets]
        for te in truth.education:
            allowed_summary += [te.degree, te.school, te.start, te.end]
        scopes.append(Scope(id="summary", texts=[summary], allowed=allowed_summary))
    return scopes


def _apply_approvals(scopes: list[Scope], approved: set[str], denied: set[str]) -> None:
    """Render-scoped only: approve => allow the claim's text here (NO truth
    write); deny => remove it from the draft texts so it can't ship."""
    for scope in scopes:
        kept: list[str] = []
        for text in scope.texts:
            cid = _claim_id(scope.id, text)
            if cid in denied:
                continue  # dropped from this render entirely
            if cid in approved:
                scope.allowed.append(text)  # traceable for THIS render only
            kept.append(text)
        scope.texts = kept


def _filter_denied_draft(draft, denied: set[str]):
    """Rebuild the draft without denied claims so the rendered CV omits them."""
    from copy import deepcopy

    out = deepcopy(draft)
    for de in out.experiences:
        de.bullets = [b for b in de.bullets if _claim_id(de.source_id, b) not in denied]
    out.skills = [s for s in out.skills if _claim_id("skills", s) not in denied]
    return out


def _require_application(app_id: str | None) -> str | None:
    """Validate an optional application id at an entry point.

    Returns None unchanged for a falsy id (the unattached-preview case), and
    the id unchanged once confirmed to exist. Raises ``NotFound`` for a
    non-empty id that does not resolve to a real application, so a stale/typo'd
    id fails loudly instead of silently falling back to a shared scratch
    preview. The HTTP adapter's ``ServiceError`` handler maps this to 404 with
    "Application not found." — the exact existing response.
    """
    if not app_id:
        return None
    if app_store.get(app_id) is None:
        raise NotFound("Application not found.")
    return app_id


def render_cv(
    *,
    application_id: str | None,
    approved: set[str],
    denied: set[str],
) -> RenderOutcome:
    """Run the full render workflow and return a plain :class:`RenderOutcome`.

    Raises ``NotFound`` if ``application_id`` is a non-empty id that does not
    resolve, and ``DraftMissing`` if no tailored draft exists to render.
    """
    _require_application(application_id)
    draft = tailor_engine.load_draft()
    if draft is None:
        raise DraftMissing()

    truth = load()
    skill_values = [s.value for s in truth.skills]

    scopes = _render_scopes(draft, truth)
    _apply_approvals(scopes, approved, denied)

    # Guardrail FIRST — nothing renders unless it passes.
    result = validate(scopes, global_values=skill_values)
    if not result.ok:
        # Return whole flagged claims (bullets), each with a stable id, so the
        # download step can offer per-claim approve/deny instead of dead-ending.
        blocked = [
            RenderedClaim(
                claim_id=_claim_id(c.scope_id, c.text),
                experience_id=c.scope_id,
                text=c.text,
                tokens=c.tokens,
            )
            for c in result.blocked_claims
        ]
        return RenderOutcome(blocked=True, unverifiable=result.unverifiable, blocked_claims=blocked)

    draft = _filter_denied_draft(draft, denied)
    html = render_html(
        draft,
        name=truth.profile.name or "Your Name",
        contact=_contact_line(truth.profile),
        summary=truth.profile.summary,
        email=truth.profile.email,
        phone=truth.profile.phone,
        location=truth.profile.location,
        links=[{"label": link.label, "url": link.url} for link in truth.profile.links],
    )
    ats: list[dict] = list(lint(html, draft.keywords, draft.keyword_aliases))

    # Attach to an application when asked: render to that application's own files
    # (retained + traceable) and persist the CV document; otherwise use the
    # shared scratch filenames (today's preview behavior). The id was already
    # validated at entry, so a truthy app_id here is known to exist.
    app_id = application_id
    if app_id:
        pdf_name, docx_name = app_store.cv_filenames(app_id)
    else:
        pdf_name, docx_name = "cv.pdf", "cv.docx"

    # When attaching to an application, record the CV FIRST so the link always
    # persists; then render best-effort.
    if app_id:
        app_store.save_cv_document(app_id, html)

    pdf_url = docx_url = None
    try:
        pdf_path = render_pdf(html, pdf_name)
        pdf_url = f"/api/download/{pdf_path.name}"
        try:
            ats.extend(verify_pdf(pdf_path, html, default_max_pages()))
        except Exception:  # noqa: BLE001 — verification must never cost the render
            pass
    except RenderUnavailable:
        pass
    try:
        docx_path = render_docx(html, docx_name)
        docx_url = f"/api/download/{docx_path.name}"
    except RenderUnavailable:
        pass

    return RenderOutcome(
        blocked=False,
        ats_warnings=ats,
        pdf_url=pdf_url,
        docx_url=docx_url,
        html=html,
        # Attached save that produced no file: the CV source is recorded but its
        # links are null, so tell the UI rather than silently show no download.
        render_unavailable=bool(app_id) and pdf_url is None and docx_url is None,
    )
