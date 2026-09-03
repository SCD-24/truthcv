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
from agenttools.letter_files import (
    NO_FILE as _NO_LETTER_FILE,
    render_screening_letter as _render_screening_letter,
)
from applications.model import Attachment, Confirmation, FieldSubmitted, Screening
from applications.store import save_attachments as _save_attachments
from applications.store import save_confirmation as _save_confirmation
from applications.store import save_fields_submitted as _save_fields_submitted
from applications.store import save_screening as _save_screening
import applications.store as _apps_store
import screening.store as _screening_store
import agenttools.tools_runs as _tools_runs
from screening.company import company_identity_key as _company_identity_key
from screening.company import validate_company_name as _validate_company_name
from screening.cooldown import cooldown as _cooldown
from screening.model import validate_blocker as _validate_blocker
from screening.model import validate_verdict as _validate_verdict
from screening.posting import validate_posting_text as _validate_posting_text
from screening.role import validate_role_title as _validate_role_title
from services.screenings import create_screening as create_or_get_screening
import services.applications as _applications_service
from screening.url import validate_posting_url as _validate_posting_url
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
    run_id: str = "",
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
        # Run linkage, written onto the record itself (before the store write,
        # not in the accounting block below) so the run's applications-submitted
        # counter can be derived from the applications this run produced.
        ("run_id", run_id),
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
            app = _applications_service.update_application_record(app.id, fields) or app
    else:
        app = _applications_service.create_application_record(backfilled)
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
        # Read the claim before mark_applied clears it, so a submission for an
        # item this run did not hold can be flagged. Best-effort throughout:
        # the ledger write above already happened, so nothing here may raise
        # or change the return shape — a real submission must never be lost
        # over an accounting failure.
        # applications_submitted is NOT bumped here: it is derived on read from
        # the application records themselves (runs/derive.py), and bumping it
        # too would double-count. over_cap_writes stays an incremented counter
        # because it records a lease violation with no derivable source.
        if run_id:
            try:
                held = _screening_store.get(screening_id)
                over_cap = bool(held) and held.claimed_by_run != run_id
                if over_cap:
                    _tools_runs.bump_run_counters(run_id=run_id, over_cap_writes=1)
            except Exception:
                pass
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
    screening_blocker: str = "",
    run_id: str = "",
    **fields,
) -> dict:
    """Persist one screening verdict via ``screening.store.create``.

    ``run_id`` links the screening to the agent run that produced it. It is
    what makes the run record's coverage counters — screenings recorded,
    blocked, queued for approval — derivable from real records instead of
    fabricated: without it the screening is attributed to no run and the run
    under-reports its own work. Named explicitly for the same schema-visibility
    reason as every other field below.

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

    ``verdict`` must be one of ``VERDICT_VALUES``, or blank if and only if
    ``screening_blocker`` is set. A posting the agent could not read at all —
    403, login wall, dead link, expired listing — has no merits to judge, so it
    takes a ``screening_blocker`` (one of ``BLOCKER_VALUES``) and no verdict.
    Never guess a verdict for a posting you could not read; that fabricates an
    evaluation that never happened. Absent a blocker, an empty verdict fails
    silently rather than loudly: ``screening.store.create`` routes a record
    into the operator's queue by comparing the verdict against
    "deferred"/"passed", so a blank or misspelled one produces a stored record
    the operator never sees.

    ``posting_text`` is mandatory whenever the record is about to queue for
    the operator's decision — a validated verdict of "passed" or "deferred"
    with no ``screening_blocker`` — because the operator drafts the cover
    letter from this text days later, on a page the agent never sees: no
    usable text means no decision the operator can make and nothing to draft
    from. It is validated by ``screening.posting.validate_posting_text``,
    which rejects blank, too-short, or wall/error-page text (a login prompt, a
    cookie banner, a 404) and normalizes what passes; its ``ValueError`` is
    left to propagate, so a passed/deferred call with no usable posting text
    persists nothing. A "rejected" verdict, or any call carrying a
    ``screening_blocker``, is exempt and keeps today's lenient behaviour — a
    posting the agent could not read takes a blocker instead of posting_text.

    One posting gets one record, forever. If the store already holds a
    screening for this ``url``, nothing is written and the EXISTING record is
    returned with ``created: false`` — the verdict you just reached is
    discarded, because that posting has already been judged and, if the
    operator rejected it, re-recording it would put it back in front of them.
    This is a normal outcome, not an error: do not retry the call, do not
    vary the URL to get past it, and count the posting as a skip.

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
    validated_blocker = _validate_blocker(screening_blocker) if screening_blocker else ""
    validated_verdict = _validate_verdict(verdict, blocker=validated_blocker)
    fields["verdict"] = validated_verdict
    if validated_verdict in ("passed", "deferred") and not validated_blocker:
        # This is about to queue for the operator's decision: no usable
        # posting text means nothing to draft the letter from, so the call is
        # rejected and nothing is stored (see the posting_text docstring
        # paragraph above).
        posting_text = _validate_posting_text(posting_text)
    named = {
        "failing_criterion": failing_criterion,
        "reason": reason,
        "cooldown_expires": cooldown_expires,
        "source": source,
        "screened_date": screened_date,
        "posting_text": posting_text,
        "posted_date": posted_date,
        "screening_blocker": validated_blocker,
        "run_id": run_id,
    }
    for name, value in named.items():
        if value:
            fields[name] = value
    screening, created = create_or_get_screening(fields)
    result = screening.to_dict()
    result["created"] = created
    return result


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

    Alias freezing: once an application already exists for a company (by
    identity key — see ``screening.company.company_identity_key``), the alias
    is computed from THAT application's stored ``company`` string, not the
    company string passed in this call. This keeps the tracking address
    stable for an employer already applied to even if a later call spells
    the same company with a different (or no) legal-entity suffix — e.g. an
    existing "RobCo GmbH" application keeps producing the same
    "tcv_robco_gmbh" address whether this call passes "RobCo" or
    "RobCo GmbH". Only a genuinely new company (no matching application row)
    is aliased from its normalized identity key.
    """
    data = _load_answers().to_dict()
    email = data.get("email")
    if isinstance(email, str) and email:
        data["email"] = _alias_email(email, _resolve_alias_company(company))
    return data


def _resolve_alias_company(company: str) -> str:
    """Resolve the company string ``get_profile_answers`` should alias against.

    If an application row already exists whose company matches ``company``'s
    identity key, that row's stored ``company`` string is returned (the
    earliest-created one wins, when several match) so the alias stays frozen
    to the address already submitted to that employer. Otherwise the
    identity key itself is returned, so a brand-new company is aliased from
    its normalized slug rather than its raw, possibly differently-cased or
    -suffixed, spelling. Never raises: a blank/non-str ``company``, or a
    failure to load the applications store, falls back to ``company``
    unchanged (aliasing degrades to today's plain per-call transform).
    """
    if not isinstance(company, str) or not company.strip():
        return company
    target_key = _company_identity_key(company)
    if not target_key:
        return company
    try:
        rows = _apps_store.load_all()
    except Exception:
        return company
    candidates = [
        row
        for row in rows
        if isinstance(row.company, str) and _company_identity_key(row.company) == target_key
    ]
    if not candidates:
        return target_key
    earliest = min(candidates, key=lambda row: row.created_at or "")
    return earliest.company


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


# How long a hand-out claim holds before another run may reclaim the item —
# long enough to cover one application's browser interaction, short enough
# that a crashed run's work comes back reasonably soon.
_CLAIM_LEASE_SECONDS = 900


def get_approved_applications(run_id: str = "", limit: int = 0) -> list[dict]:
    """Postings the operator approved and this run should apply to.

    ``run_id`` and ``limit`` are both optional (and must stay defaulted: the
    MCP schema in agenttools/mcp_app.py marks a defaultless parameter
    required). With an empty ``run_id`` this behaves exactly as it always
    has, apart from the cap described below — that keeps the operator-facing
    and test call paths unchanged.

    With a non-empty ``run_id``:

    - The per-run apply cap is ``limit`` when it is > 0, else
      ``maxApplicationsPerRun`` from the agent config, else uncapped. Only
      items that are actually applicable (``blocked_reason == ""``) consume
      this budget; a blocked item is still reported (so the run report can
      say why it did not go out) but never counts against the cap and is
      never claimed.
    - An item already live-leased to a DIFFERENT run is left out entirely —
      this run must not step on another run's in-flight work. An item whose
      lease has expired is available again.
    - Every unblocked item returned up to the cap is claimed for this run via
      screening.store.claim_for_run, and its ``claimed_by_run`` reflects
      that. A shorter list than the cap means the cap was reached, not that
      work was lost.

    Three further guards live here rather than in the prompt, because a wrong judgement by
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
    - An item blocked by a login wall (the posting sat behind a sign-in) comes
      back with ``blocked_reason`` set to "login_required" rather than retried
      every run, since the operator must authorize the site first.
    - The operator's stored letter travels with the item, as text and — for an
      item that is actually going out — as ``cover_letter_path``, a rendered
      PDF of that same text on the data volume for the agent to upload where
      the form takes a file rather than a textarea. The path is None when no
      rendering backend is installed; the text is then all there is. The agent
      applies with that text verbatim and does not regenerate: regenerating
      would discard the operator's edit, which is the whole point of semi-auto. Approval only
      checks the draft exists at approval time, not afterward, so an item whose
      draft was since blanked or deleted comes back with ``blocked_reason`` set
      to "" rather than reaching the agent with nothing to send.
    """
    cap = 0
    if limit and limit > 0:
        cap = limit
    else:
        cfg = _agentconfig_store.load()
        cap = getattr(cfg, "max_applications_per_run", None) or 0

    # The reusable reads and the blocked-reason cascade live in the service; the
    # per-run cap and the claim-lease below are agent-only and stay here, since
    # only the agent claims work.
    items = []
    claimed_count = 0
    for entry in _applications_service.gather_approvable_screenings():
        s = entry["screening"]
        blocked_reason = entry["blocked_reason"]

        claimed_by_run = s.claimed_by_run
        if not blocked_reason and run_id:
            if cap and claimed_count >= cap:
                continue  # over this run's cap: leave it for a later run
            claimed = _screening_store.claim_for_run(s.id, run_id, _CLAIM_LEASE_SECONDS)
            if claimed is None:
                continue  # lost a race for this item; skip rather than misreport it
            claimed_by_run = claimed.claimed_by_run
            claimed_count += 1
        elif not blocked_reason and cap and claimed_count >= cap:
            continue
        elif not blocked_reason:
            claimed_count += 1

        # Only an item that is actually going out gets a file rendered for it:
        # a blocked item is reported, never applied to, so rendering it would
        # buy nothing and cost a WeasyPrint pass per blocked item per run.
        letter_file = (
            _render_screening_letter(s.id, entry["cover_letter"])
            if not blocked_reason
            else dict(_NO_LETTER_FILE)
        )

        items.append(
            {
                "screening_id": s.id,
                "company": s.company,
                "role": s.role,
                "url": s.url,
                "attempts": s.apply_attempts,
                "blocked_reason": blocked_reason,
                "contradictions": entry["contradictions"],
                "cover_letter": entry["cover_letter"],
                "letter_source": entry["letter_source"],
                "cover_letter_asset_id": letter_file["asset_id"],
                "cover_letter_path": letter_file["path"],
                "cover_letter_download_url": letter_file["download_url"],
                "claimed_by_run": claimed_by_run,
            }
        )
    return items


def report_apply_failure(
    screening_id: str,
    error: str,
    blocker: str = "",
    signin_url: str = "",
) -> dict:
    """Record why an approved application could not be completed this run.

    Leaves the item approved and queued: the operator chose retry-on-next-run,
    and this tool cannot change an approval either way.

    `blocker="login_required"` with `signin_url` set is what puts the site in
    the operator's sign-in queue. Without them the failure is recorded but the
    operator is never told which site to go and authorise.
    """
    updated = _screening_store.record_apply_failure(
        screening_id, error, blocker=blocker, signin_url=signin_url
    )
    if updated is None:
        return {"ok": False, "reason": "unknown screening id"}
    return {"ok": True, "attempts": updated.apply_attempts}
