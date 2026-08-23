"""Ledger, screening and profile tools for the agent tool surface.

Every function here delegates to an existing store or pure function — none of
them re-implements persistence, cooldown matching, or file I/O. They exist
only to give the agent a stable, per-call vocabulary (``applied_date``,
``fields_submitted``, ...) over the same modules the wizard's HTTP routes use,
so the agent and the wizard can never disagree about what happened.
"""

from __future__ import annotations

import agentconfig.store as _agentconfig_store
from agentconfig.salary import clamp_ask as _clamp_ask
from agentconfig.salary import format_ask as _format_ask
from applications.model import Attachment, Confirmation, FieldSubmitted
from applications.store import create as create_application
from applications.store import save_attachments as _save_attachments
from applications.store import save_confirmation as _save_confirmation
from applications.store import save_fields_submitted as _save_fields_submitted
from applications.store import save_screening as _save_screening
import applications.store as _apps_store
import screening.store as _screening_store
from screening.cooldown import cooldown as _cooldown
from screening.store import create as create_screening
from truth.answers import canonical_cv as _canonical_cv
from truth.answers import load as _load_answers


def record_application(**fields) -> dict:
    """Persist one tracked application with its full evidence trail.

    ``applications.store.create`` only accepts ``Application.EDITABLE``
    fields, so the structured evidence — ``fields_submitted``,
    ``confirmation``, ``screening`` (the pre-application filter verdicts) and
    ``attachments`` — is stripped out first, the editable record is created,
    and then each structured field is persisted through its own
    ``save_*`` helper in ``applications.store``. Those helpers are the only
    writers of ``applications.json`` (via the store's atomic ``_write_all``);
    nothing here touches the file directly. ``applied_date`` is accepted as
    the agent-facing alias for the record's ``application_date`` field.
    """
    fields = dict(fields)
    # Not an Application field: it names the approved queue item this
    # application settles.
    screening_id = fields.pop("screening_id", "")
    applied_date = fields.pop("applied_date", None)
    if applied_date is not None:
        fields["application_date"] = applied_date
    fields_submitted = fields.pop("fields_submitted", None)
    confirmation = fields.pop("confirmation", None)
    screening = fields.pop("screening", None)
    attachments = fields.pop("attachments", None)

    app = create_application(fields)

    if fields_submitted is not None:
        values = [FieldSubmitted.from_dict(f) for f in fields_submitted]
        app = _save_fields_submitted(app.id, values) or app
    if confirmation is not None:
        app = _save_confirmation(app.id, Confirmation.from_dict(confirmation)) or app
    if screening is not None:
        app = _save_screening(app.id, screening) or app
    if attachments is not None:
        values = [Attachment.from_dict(a) for a in attachments]
        app = _save_attachments(app.id, values) or app

    # An approved queue item retires on evidence of a confirmed application,
    # not on the agent electing to retire it.
    if screening_id:
        _screening_store.mark_applied(screening_id)

    return app.to_dict()


def record_screening(**fields) -> dict:
    """Persist one screening verdict via ``screening.store.create``."""
    screening = create_screening(fields)
    return screening.to_dict()


def check_cooldown(company: str, role: str | None = None) -> dict:
    """Whether ``company`` (optionally narrowed by ``role``) is in cooldown.

    Delegates to ``screening.cooldown.cooldown``, the same function behind
    ``GET /api/cooldown``, so the two surfaces can never disagree.
    """
    status = _cooldown(company, role)
    return {"in_cooldown": status.in_cooldown, "expires": status.expires, "blocked": status.blocked}


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


def get_profile_answers() -> dict:
    """The canonical ATS screening answers (runbook §3), as a plain dict."""
    return _load_answers().to_dict()


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


def get_approved_applications() -> list[dict]:
    """Postings the operator approved and this run should apply to.

    Two guards live here rather than in the prompt, because a wrong judgement by
    the model would be costly and silent:

    - An item whose URL already appears in the applications ledger is dropped.
      The retry policy keeps failed items queued indefinitely, so a submission
      whose confirmation capture failed would otherwise be sent twice.
    - An item whose company is in cooldown comes back with ``blocked_reason``
      set instead of being hidden, so the run report can say why it did not go
      out rather than the posting silently vanishing.
    """
    applied_urls = {
        a.application_url for a in _apps_store.load_all() if a.application_url
    }
    items = []
    for s in _screening_store.load_all():
        if s.approval != "approved":
            continue
        if s.url and s.url in applied_urls:
            continue
        status = _cooldown(s.company, s.role or None)
        items.append(
            {
                "screening_id": s.id,
                "company": s.company,
                "role": s.role,
                "url": s.url,
                "attempts": s.apply_attempts,
                "blocked_reason": "cooldown" if status.blocked else "",
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
