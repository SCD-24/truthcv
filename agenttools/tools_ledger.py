"""Ledger, screening and profile tools for the agent tool surface.

Note on ``record_application``: it accepts a blank ``company`` or ``role``,
unlike ``record_screening``, which rejects both. That is a deliberate gap and
not an oversight — the backfill from an approved queue item is the normal path
and supplies them — but it does mean an application row can be stored that
cooldown matching and the blocklist cannot key on. Tightening it is a contract
change for every existing caller and has not been made.

Every function here delegates to an existing store or pure function — none of
them re-implements persistence, cooldown matching, or file I/O. They exist
only to give the agent a stable, per-call vocabulary (``applied_date``,
``fields_submitted``, ...) over the same modules the wizard's HTTP routes use,
so the agent and the wizard can never disagree about what happened.
"""

from __future__ import annotations

import json

import agentconfig.store as _agentconfig_store
from agentconfig.salary import clamp_ask as _clamp_ask
from agentconfig.salary import format_ask as _format_ask
from companyresearch.store import open_contradictions as _open_contradictions
from applications.model import Attachment, Confirmation, FieldSubmitted, Screening
from applications.store import create as create_application
from applications.store import save_attachments as _save_attachments
from applications.store import save_confirmation as _save_confirmation
from applications.store import save_fields_submitted as _save_fields_submitted
from applications.store import save_screening as _save_screening
import applications.store as _apps_store
import coverletter.store as _letter_store
import screening.store as _screening_store
from screening.company import validate_company_name as _validate_company_name
from screening.cooldown import cooldown as _cooldown
from screening.model import validate_verdict as _validate_verdict
from screening.role import validate_role_title as _validate_role_title
from screening.store import create as create_screening
from screening.url import validate_posting_url as _validate_posting_url
from screening.url import normalize_application_url as _normalize_application_url
from truth.answers import canonical_cv as _canonical_cv
from truth.answers import load as _load_answers
from truth.emailalias import alias_email as _alias_email


def _backfill_from_screening(fields: dict, screening_id: str) -> dict:
    """Fill identity fields the caller left absent or empty from the screening.

    An application recorded against an approved queue item should carry that
    item's company, role, URL and posting so the Applications row is populated
    without the agent having to repeat them. Caller-supplied non-empty values
    always win; an unknown ``screening_id`` changes nothing (the caller's
    fields stand, exactly as before this backfill existed).
    """
    if not screening_id:
        return fields
    s = _screening_store.get(screening_id)
    if s is None:
        return fields
    inherited = {
        "company": s.company,
        "role": s.role,
        "application_url": s.url,
        "posting": s.posting_text,
    }
    for key, value in inherited.items():
        if not fields.get(key):
            fields[key] = value
    return fields


def _as_list(value, name: str):
    """Coerce a structured-list argument to a ``list``, or fail loudly.

    ``None`` means "not provided" and is passed straight back for the caller to
    interpret. A ``list`` is returned unchanged. A ``str`` is ``json.loads``-ed
    (the agent occasionally sends a JSON-encoded string) and accepted only if it
    decodes to a list; anything else raises ``ValueError`` naming the argument,
    so the failure points at the bad input rather than surfacing later as
    ``'str' object has no attribute 'get'``.
    """
    if value is None:
        return None
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        decoded = json.loads(value)
        if not isinstance(decoded, list):
            raise ValueError(
                f"{name} must be a list; got JSON string decoding to "
                f"{type(decoded).__name__}"
            )
        return decoded
    raise ValueError(f"{name} must be a list; got {type(value).__name__}")


def _as_dict(value, name: str):
    """Coerce a structured-object argument to a ``dict``, or fail loudly.

    Same contract as ``_as_list``: ``None`` passes through, a ``dict`` is
    returned unchanged, a ``str`` is ``json.loads``-ed and accepted only if it
    decodes to a dict, and anything else raises ``ValueError`` naming the
    argument.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        decoded = json.loads(value)
        if not isinstance(decoded, dict):
            raise ValueError(
                f"{name} must be a dict; got JSON string decoding to "
                f"{type(decoded).__name__}"
            )
        return decoded
    raise ValueError(f"{name} must be a dict; got {type(value).__name__}")


def record_application(
    company: str = "",
    role: str = "",
    application_url: str = "",
    screening_id: str = "",
    applied_date: str = "",
    submission_type: str = "",
    method: str = "",
    status: str = "",
    posting: str = "",
    ats: str = "",
    capture_method: str = "",
    profile: str = "",
    notes: str = "",
    fields_submitted: list | None = None,
    confirmation: dict | None = None,
    screening: dict | None = None,
    attachments: list | None = None,
    submitted: bool = True,
    **fields,
) -> dict:
    """Persist one tracked application with its full evidence trail.

    The fields above are named rather than left to ``**fields`` because the MCP
    inputSchema is derived from this signature: an unnamed field is invisible to
    the agent reading the schema, and the tool then advertises an empty property
    set for a record with eighteen editable fields. That is the same defect that
    silently emptied ``company`` and ``verdict`` on 36 consecutive screenings,
    on the tool that records real applications rather than verdicts. The four
    structured-evidence params — ``fields_submitted``, ``confirmation``,
    ``screening`` and ``attachments`` — are named for the same reason: they were
    the same defect one level deeper, still swallowed by ``**fields`` and so
    invisible in the schema until promoted here.

    Nothing here is a *required* argument, unlike ``record_screening``:
    ``_backfill_from_screening`` is designed to supply ``company``, ``role`` and
    the posting from the approved queue item when ``screening_id`` is given, and
    a caller that does so legitimately passes neither. This tool therefore still
    accepts a blank company or role — see the note in the module docstring.

    ``applications.store.create`` only accepts ``Application.EDITABLE``
    fields, so the structured evidence — ``fields_submitted``,
    ``confirmation``, ``screening`` (the pre-application filter verdicts) and
    ``attachments`` — is stripped out first, the editable record is created,
    and then each structured field is persisted through its own
    ``save_*`` helper in ``applications.store``. Those helpers are the only
    writers of ``applications.json`` (via the store's atomic ``_write_all``);
    nothing here touches the file directly. ``applied_date`` is accepted as
    the agent-facing alias for the record's ``application_date`` field.

    These four evidence fields are now named parameters too, not left to
    ``**fields``, for the same inputSchema-visibility reason given for the
    identity fields above: an agent reading the schema needs to see that the
    tool accepts this evidence, not just the identity fields. They still fall
    back to ``**fields`` for any caller routing them that way.
    """
    fields = dict(fields)
    if company:
        fields["company"] = company
    if role:
        fields["role"] = role
    # Named optionals are written only when non-empty, so an omitted one never
    # overwrites a value `_backfill_from_screening` would otherwise supply.
    for name, value in (
        ("application_url", application_url),
        ("submission_type", submission_type),
        ("method", method),
        ("status", status),
        ("posting", posting),
        ("ats", ats),
        ("capture_method", capture_method),
        ("profile", profile),
        ("notes", notes),
    ):
        if value:
            fields[name] = value
    if applied_date:
        fields["application_date"] = applied_date
    # Written unconditionally, and named rather than left to `**fields`, because
    # `get_approved_applications` keys its double-submit guard on it: a row that
    # reaches the ledger with `submitted` still at its dataclass default of False
    # is indistinguishable from a reconstructed placeholder, and the approved item
    # it came from would be handed straight back on the next run. The default is
    # True because that is this tool's contract — it records an application that
    # was submitted; a caller recording anything else passes submitted=False.
    fields["submitted"] = bool(submitted)
    # `main` kept a `**fields` fallback for these four when the named parameter
    # is absent, so a caller still routing evidence through `**fields` keeps
    # working; the coercion and validation below then apply either way.
    if fields_submitted is None:
        fields_submitted = fields.pop("fields_submitted", None)
    if confirmation is None:
        confirmation = fields.pop("confirmation", None)
    if screening is None:
        screening = fields.pop("screening", None)
    if attachments is None:
        attachments = fields.pop("attachments", None)

    # Parse and validate the structured evidence BEFORE any store write. Doing
    # this first is the fix for the orphan-row bug: the row used to be created
    # first and a malformed evidence payload blew up the parse afterward,
    # leaving a written application row with no evidence attached.
    parsed_fields_submitted = (
        [FieldSubmitted.from_dict(f) for f in _as_list(fields_submitted, "fields_submitted")]
        if fields_submitted is not None else None
    )
    parsed_confirmation = (
        Confirmation.from_dict(_as_dict(confirmation, "confirmation"))
        if confirmation is not None else None
    )
    parsed_screening = (
        Screening.from_dict(_as_dict(screening, "screening"))
        if screening is not None else None
    )
    parsed_attachments = (
        [Attachment.from_dict(a) for a in _as_list(attachments, "attachments")]
        if attachments is not None else None
    )

    backfilled = _backfill_from_screening(fields, screening_id)
    if screening_id:
        app, created = _apps_store.create_for_screening(backfilled, screening_id)
        if not created:
            # A retry against an existing row: apply the caller's editable
            # fields so the re-record improves the record instead of being
            # silently dropped. Use `fields`, not `backfilled`, so inherited
            # values the caller did not actually send are not reintroduced.
            app = _apps_store.update(app.id, fields) or app
    else:
        app = create_application(backfilled)
        created = True

    if parsed_fields_submitted is not None:
        app = _save_fields_submitted(app.id, parsed_fields_submitted) or app
    if parsed_confirmation is not None:
        app = _save_confirmation(app.id, parsed_confirmation) or app
    if parsed_screening is not None:
        app = _save_screening(app.id, parsed_screening) or app
    if parsed_attachments is not None:
        app = _save_attachments(app.id, parsed_attachments) or app

    # An approved queue item retires on evidence of a confirmed application,
    # not on the agent electing to retire it.
    if screening_id:
        _screening_store.mark_applied(screening_id)

    result = app.to_dict()
    result["created"] = created
    return result


def record_screening(
    url: str,
    role: str,
    company: str,
    verdict: str,
    failing_criterion: str = "",
    reason: str = "",
    cooldown_expires: str = "",
    source: str = "",
    screened_date: str = "",
    posting_text: str = "",
    posted_date: str = "",
    **fields,
) -> dict:
    """Persist one screening verdict via ``screening.store.create``.

    The posting's own ``url`` is mandatory: the operator must be able to open
    the posting to act on this verdict, and the agent cannot apply to a
    posting it has no URL for. The URL is validated by
    ``screening.url.validate_posting_url``; a ``ValueError`` it raises is left
    to propagate, which is the intended rejection of a call that gave no
    usable URL.

    ``role`` is equally mandatory: the operator screens the approval queue on
    the job title, so a blank or garbled one makes the verdict unreadable and
    the record useless for that purpose. It is validated by
    ``screening.role.validate_role_title``, which normalizes whitespace and
    rejects placeholder text (e.g. "Apply now", "Remote", an empty string) or
    a value that looks like a URL or a posting body rather than a title; its
    ``ValueError`` is likewise left to propagate, so a call with no usable
    role title persists nothing.

    ``company`` is mandatory for the same reason: cooldown matching, the
    blocked-company list and the approval queue all key on the employer, so a
    blank one makes the record unusable for every one of them. It is validated
    by ``screening.company.validate_company_name``, which rejects placeholders
    ("Unknown", "Confidential", an empty string) and pasted URLs.

    ``verdict`` is mandatory and must be one of ``VERDICT_VALUES``. This is the
    one field whose absence fails silently rather than loudly:
    ``screening.store.create`` routes a record into the operator's queue by
    comparing the verdict against "deferred"/"passed", so a blank or misspelled
    one produces a stored record the operator never sees.

    Every field above is named explicitly rather than left to ``**fields``,
    because the MCP inputSchema is derived from this signature: a field absent
    from it is invisible to the agent reading the schema, and one model will
    pass it from the RUNBOOK's instructions while another will not. Unnamed,
    ``company`` and ``verdict`` were left blank on 36 consecutive records and
    none of them reached the approval queue. The optional fields are written
    only when non-empty, so an omitted one never overwrites a stored value.
    """
    validated_url = _validate_posting_url(url)
    validated_role = _validate_role_title(role)
    fields["url"] = validated_url
    fields["role"] = validated_role
    fields["company"] = _validate_company_name(company)
    fields["verdict"] = _validate_verdict(verdict)
    named = {
        "failing_criterion": failing_criterion,
        "reason": reason,
        "cooldown_expires": cooldown_expires,
        "source": source,
        "screened_date": screened_date,
        "posting_text": posting_text,
        "posted_date": posted_date,
    }
    for name, value in named.items():
        if value:
            fields[name] = value
    screening = create_screening(fields)
    return screening.to_dict()


def check_cooldown(company: str, role: str | None = None) -> dict:
    """Whether ``company`` (optionally narrowed by ``role``) is in cooldown.

    Delegates to ``screening.cooldown.cooldown``, the same function behind
    ``GET /api/cooldown``, so the two surfaces can never disagree.
    """
    status = _cooldown(company, role)
    return {
        "in_cooldown": status.in_cooldown,
        "expires": status.expires,
        "blocked": status.blocked,
        # Kept byte-identical with GET /api/cooldown (tests/test_agent_mcp.py
        # asserts the two dicts are equal) — both surfaces change together.
        "window": getattr(status, "window", None),
    }


def get_canonical_cv() -> dict:
    """The registered canonical CV's asset id, path, and download_url.

    Returns:
        dict with three keys:
        - asset_id: the asset's bare filename on the data volume, which is
                    also the {name} the download route resolves
        - path: filesystem path valid only where the data volume is mounted
                (e.g. /app/data/canonical_cv.pdf for the browser container)
        - download_url: HTTP fallback for a client that cannot see that
                        filesystem — GET /api/download/{asset_id}
        When no canonical CV is registered, all three keys are None.
    """
    asset = _canonical_cv()
    if asset is None:
        return {"asset_id": None, "path": None, "download_url": None}
    return {
        "asset_id": asset.asset_id,
        "path": str(asset.path),
        "download_url": f"/api/download/{asset.asset_id}",
    }


def get_profile_answers(company: str = "") -> dict:
    """The canonical ATS screening answers (runbook §3), as a plain dict.

    When ``company`` (the employing entity for the application currently
    being filled in) is given, the returned ``email`` is rewritten as a
    per-company tracking address: local+tcv_<company_slug>@domain, so
    replies from that employer are identifiable. This is a per-call
    transformation only — it is never persisted. The stored answers, the
    wizard's profile route, and the CV/cover-letter contact lines all
    continue to see the real, un-aliased address. With ``company`` blank,
    the returned email is unchanged from what is stored.
    """
    data = _load_answers().to_dict()
    email = data.get("email")
    if isinstance(email, str) and email:
        data["email"] = _alias_email(email, company)
    return data


def get_job_profiles() -> list[dict]:
    """The configured job search profiles from agent_config.json, as plain dicts."""
    cfg = _agentconfig_store.load()
    return [profile.to_dict() for profile in cfg.profiles]


def recommend_salary(profile_name: str, proposed: int | None = None) -> dict:
    """Recommend a salary ask for a named profile, clamped to its configured band.

    Looks up ``profile_name`` in the configured job profiles and clamps
    ``proposed`` (or the band minimum, if omitted) into
    ``[salary_ask_min, salary_ask_max]`` via ``agentconfig.salary.clamp_ask``.
    Returns a refusal dict if the profile is unknown or has no salary band.
    """
    cfg = _agentconfig_store.load()
    profile = next((p for p in cfg.profiles if p.name == profile_name), None)
    if profile is None:
        return {"refused": f"Profile not found: {profile_name}"}

    clamped = _clamp_ask(profile, proposed)
    if clamped is None:
        return {"refused": "Profile has no salary band configured"}

    return {
        "amount": clamped,
        "formatted": _format_ask(profile, clamped),
        "band": {"min": profile.salary_ask_min, "max": profile.salary_ask_max},
        # Only a figure the caller actually proposed can be "clamped"; with
        # proposed=None the band minimum is supplied, not adjusted.
        "clamped": proposed is not None and proposed != clamped,
    }


def _is_submission(app) -> bool:
    """Whether a ledger row records an application that was actually sent.

    ``submitted`` is the field that means this, but it defaults to False on the
    dataclass and predates ``record_application`` naming it, so a row that was
    genuinely submitted can still carry False. Confirmation text is accepted as
    the corroborating evidence: nothing writes it but a captured confirmation.
    """
    return bool(app.submitted or app.confirmation.text.strip())


def get_approved_applications() -> list[dict]:
    """Postings the operator approved and this run should apply to.

    Three guards live here rather than in the prompt, because a wrong judgement by
    the model would be costly and silent:

    - An item whose URL already appears in the applications ledger *as a
      submission* comes back with ``blocked_reason`` set to "already_applied".
      The retry policy keeps failed items queued indefinitely, so a submission
      whose confirmation capture failed would otherwise be sent twice. Only rows
      carrying evidence of a submission count: the ledger also holds
      reconstructed placeholders for postings nobody applied to, and matching
      those hid a legitimately approved item from every run — silently, since
      this guard used to drop the item instead of flagging it, so the operator
      saw a queued item stuck at zero attempts with no reason recorded.
    - An item whose company has an unresolved company-research contradiction
      comes back with ``blocked_reason`` set to "contradictory_research"
      rather than hidden. The agent must not apply to a company whose own
      research disagrees with itself, so this ranks directly after
      already_applied: like that guard it describes an item that must not go
      out at all, not one that cannot go out yet. It is flagged rather than
      hidden so the run report can say why it did not go out.
    - An item whose company is in cooldown comes back with ``blocked_reason``
      set instead of being hidden, so the run report can say why it did not go
      out rather than the posting silently vanishing.
    - An item with no URL (many imported records predate URL capture) comes
      back with ``blocked_reason`` set to "no_url" rather than hidden, since
      the agent has nothing to open and would otherwise flail trying to apply.
    - The operator's stored letter travels with the item. The agent applies with
      that text verbatim and does not regenerate: regenerating would discard the
      operator's edit, which is the whole point of semi-auto. Approval only
      checks the draft exists at approval time, not afterward, so an item whose
      draft was since blanked or deleted comes back with ``blocked_reason`` set
      to "no_letter" rather than reaching the agent with nothing to send.
    """
    applied_urls = {
        norm
        for a in _apps_store.load_all()
        if _is_submission(a)
        for norm in (_normalize_application_url(a.application_url),)
        if norm
    }
    applied_screening_ids = {
        a.screening_id
        for a in _apps_store.load_all()
        if _is_submission(a) and a.screening_id
    }
    items = []
    for s in _screening_store.load_all():
        if s.approval != "approved":
            continue
        draft = _letter_store.load(s.id)
        status = _cooldown(s.company, s.role or None)
        contradictions = [
            {"claim": g["claim"], "findings": [f.to_dict() for f in g["findings"]]}
            for g in _open_contradictions(s.company)
        ]
        # already_applied and contradictory_research outrank the rest: those
        # two describe an item that must not go out at all, the others one
        # that cannot go out yet.
        if s.id in applied_screening_ids or (s.url and _normalize_application_url(s.url) in applied_urls):
            blocked_reason = "already_applied"
        elif contradictions:
            blocked_reason = "contradictory_research"
        elif status.blocked:
            blocked_reason = "cooldown"
        elif not s.url.strip():
            blocked_reason = "no_url"
        elif draft is None or not draft.text.strip():
            blocked_reason = "no_letter"
        else:
            blocked_reason = ""
        items.append(
            {
                "screening_id": s.id,
                "company": s.company,
                "role": s.role,
                "url": s.url,
                "attempts": s.apply_attempts,
                "blocked_reason": blocked_reason,
                "contradictions": contradictions,
                "cover_letter": draft.text if draft else "",
                "letter_source": draft.source if draft else "",
            }
        )
    return items


def report_apply_failure(screening_id: str, error: str) -> dict:
    """Record why an approved application could not be completed this run.

    Leaves the item approved and queued: the operator chose retry-on-next-run,
    and this tool cannot change an approval either way.
    """
    updated = _screening_store.record_apply_failure(screening_id, error)
    if updated is None:
        return {"ok": False, "reason": "unknown screening id"}
    return {"ok": True, "attempts": updated.apply_attempts}
