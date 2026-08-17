"""Ledger, screening and profile tools for the agent tool surface.

Every function here delegates to an existing store or pure function — none of
them re-implements persistence, cooldown matching, or file I/O. They exist
only to give the agent a stable, per-call vocabulary (``applied_date``,
``fields_submitted``, ...) over the same modules the wizard's HTTP routes use,
so the agent and the wizard can never disagree about what happened.
"""

from __future__ import annotations

from applications.model import Attachment, Confirmation, FieldSubmitted
from applications.store import create as create_application
from applications.store import save_attachments as _save_attachments
from applications.store import save_confirmation as _save_confirmation
from applications.store import save_fields_submitted as _save_fields_submitted
from applications.store import save_screening as _save_screening
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
    """The registered canonical CV's asset id and path, or both None if unset."""
    asset = _canonical_cv()
    if asset is None:
        return {"asset_id": None, "path": None}
    return {"asset_id": asset.asset_id, "path": str(asset.path)}


def get_profile_answers() -> dict:
    """The canonical ATS screening answers (runbook §3), as a plain dict."""
    return _load_answers().to_dict()
