"""The screening workflows shared by the HTTP route and the MCP tool.

Only the parts that genuinely coincide are here. The two adapters keep their
own, deliberately different, contracts on top:

* **Duplicate handling.** `create_screening` returns ``(screening, created)``.
  The HTTP route raises a 409 carrying the existing screening's id when
  ``created`` is False; the MCP tool instead returns the existing record with
  ``created: false``. Both are correct for their caller and neither is
  "fixed" to match the other — see api/routes.py's create_screening
  docstring for why.
* **Validation and error tiers.** Each adapter validates its own inputs
  (the route via ``ScreeningCreate``'s pydantic validators, the tool via
  ``record_screening_verdict``'s direct calls to
  ``identity.company``/``screening.model``/``screening.posting``)
  and raises in its own idiom (HTTPException vs ValueError/refusal dict).
  Only the terminal store call is shared: the MCP tool's queueing gate
  (``record_screening_verdict``) lives here too, but the HTTP route
  deliberately does not go through it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import screening.jev as _jev
import screening.store as screening_store
from coverletter import store as _coverletter_store
from identity.company import validate_company_name as _validate_company_name
from identity.url import is_posting_url as _is_posting_url
from identity.url import validate_posting_url as _validate_posting_url
from screening.criteria import evaluate_hard_requirements as _evaluate_hard_requirements
from screening.criteria import holds_for_review as _holds_for_review
from screening.criteria import validate_eor_stated as _validate_eor_stated
from screening.criteria import validate_language_requirement as _validate_language_requirement
from screening.criteria import validate_remote_arrangement as _validate_remote_arrangement
from screening.criteria import validate_stated_text as _validate_stated_text
from screening.model import validate_blocker as _validate_blocker
from screening.model import validate_verdict as _validate_verdict
from screening.posting import validate_posting_text as _validate_posting_text
from screening.role import validate_role_title as _validate_role_title
from screening.store import Screening
from services.agent_config import load_enabled_profile as _load_enabled_profile

logger = logging.getLogger(__name__)


def create_screening(fields: dict) -> tuple[Screening, bool]:
    """Create-or-get a screening from already-validated ``fields``.

    Returns ``(screening, created)`` — ``created`` is False when a screening
    for this posting already existed. What that means to the caller is the
    caller's decision (see the module docstring).
    """
    return screening_store.create_or_get(fields)


def delete_screening(screening_id: str) -> bool:
    """Delete a screening and, if it was removed, its cover-letter draft.

    The draft cascade lives here rather than in ``screening.store`` so the
    domain store does not reach up into the cover-letter engine.

    Returns:
        True if the screening existed and was removed.
    """
    if not screening_store.delete(screening_id):
        return False
    # Outside the lock: a different file, and holding one file's lock while
    # touching another is how two writers deadlock on opposite orderings.
    _coverletter_store.delete(screening_id)
    return True


def delete_screenings(ids: list[str]) -> list[tuple[str, bool]]:
    """Delete several screenings and the cover-letter drafts of those removed.

    Same cascade as ``delete_screening``, kept out of ``screening.store`` for
    the same reason. Unknown ids are reported False and have no draft touched.

    Returns:
        One (id, ok) pair per input id, in input order.
    """
    results = screening_store.delete_many(ids)
    # Outside the lock: a different file, and holding one file's lock while
    # touching another is how two writers deadlock on opposite orderings.
    for deleted_id in dict.fromkeys(i for i, ok in results if ok):
        _coverletter_store.delete(deleted_id)
    return results


def clear_login_blockers_for_host(host: str) -> int:
    """Clear login_required blockers for approved/pending items at a given host.

    When the operator signs in to a site, re-arm the queued items that were
    blocked waiting for that sign-in. Iterate all screenings, find those with
    apply_blocker == "login_required" and approval in ("pending", "approved")
    whose signin_url (falling back to url) has the same host, and clear their
    apply_blocker. Preserve apply_attempts and other fields.

    Host comparison parses each record URL with urlparse and casefolded netloc,
    matching the same logic as api/routes.py's _host_of.

    Return the count of items cleared.
    """
    from urllib.parse import urlparse

    def _host_of_local(url: str) -> str:
        """The full host of an absolute http(s) URL, or "" if it is not one."""
        try:
            parsed = urlparse(url or "")
        except ValueError:
            return ""
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return ""
        return parsed.netloc.casefold()

    target_host = host.casefold() if host else ""
    count = 0
    for s in screening_store.load_all():
        if s.apply_blocker != "login_required":
            continue
        if s.approval not in ("pending", "approved"):
            continue
        # Use signin_url if available, otherwise fall back to the posting url
        url_to_check = s.signin_url or s.url
        if _host_of_local(url_to_check) == target_host:
            screening_store.clear_apply_failure(s.id)
            count += 1
    return count


@dataclass
class ApplyClaimResult:
    """The outcome of claiming a screening for a manual/agent apply."""

    screening: Screening | None = None
    refused_screening: Screening | None = None
    reason: str = ""

    @property
    def refused(self) -> bool:
        return self.screening is None


def claim_screening_for_apply(screening_id: str) -> ApplyClaimResult:
    """Atomically retire ``screening_id`` so it can become an Application.

    Retire FIRST, atomically, and only the caller that wins the claim may go
    on to create the resulting Application row — two requests racing to
    create-then-retire would otherwise both succeed and leave two Application
    rows for the one screening.

    When the claim is refused, ``refused_screening`` is the current record
    (or None if it no longer exists at all) and ``reason`` is the same
    machine-readable refusal reason ``screening.store``'s private
    ``_apply_refusal`` derives — callers must not reach into that private
    function themselves; this is the one place that does.
    """
    screening = screening_store.claim_for_apply(screening_id)
    if screening is not None:
        return ApplyClaimResult(screening=screening)
    refused_screening = screening_store.get(screening_id)
    reason = (
        screening_store._apply_refusal(refused_screening, screening_store.load_all())
        if refused_screening
        else "already_applied"
    )
    return ApplyClaimResult(refused_screening=refused_screening, reason=reason)


def _evaluate_profile_criteria(profile_name: str, evidence: dict, agent_reason: str) -> dict:
    """Check ``profile_name``'s six hard requirements against the posting's stated evidence.

    Loads the named ENABLED profile via ``load_enabled_profile`` (which
    raises ``ValueError`` naming the enabled ones for an unknown/disabled
    name), then runs ``screening.criteria.evaluate_hard_requirements`` over
    ``evidence``. Returns ``{}`` when the posting is compatible with every
    one of remote model, working language, salary floor, employment country,
    rejected role types, and EOR/PEO allowance. Otherwise returns a dict with
    ``verdict='rejected'``, the failing criterion, and a reason that prefixes
    the criteria evidence onto whatever reason the agent supplied, so the
    operator sees both why the posting failed and what the agent said about
    it.
    """
    profile = _load_enabled_profile(profile_name)
    failing_criterion, evidence_reason = _evaluate_hard_requirements(profile, evidence)
    if not failing_criterion:
        return {}
    combined_reason = f"{evidence_reason} {agent_reason}".strip()
    return {
        "verdict": "rejected",
        "failing_criterion": failing_criterion,
        "reason": combined_reason,
    }


def _evaluate_jev_criteria(profile_name: str, posting_text: str, agent_reason: str) -> dict:
    """Cross-check the posting against Jev's opinion of the profile's hard requirements.

    Called only after the deterministic checks in ``_evaluate_profile_criteria``
    pass, since Jev never overrides a deterministic rejection. Returns ``{}``
    when Jev is disabled, reports no failures, or errors for any reason — a
    transport error, a timeout, or an unexpected response must never break
    screening, so any exception is logged and swallowed here. Otherwise uses
    only the FIRST reported failure and returns the same ``verdict='rejected'``/
    ``failing_criterion``/``reason`` shape as ``_evaluate_profile_criteria``,
    with the reason prefixed 'Jev: '.
    """
    try:
        if not _jev.enabled():
            return {}
        profile = _load_enabled_profile(profile_name)
        failures = _jev.evaluate_hard_requirements(profile, posting_text)
    except Exception:
        logger.warning("Jev hard-requirement cross-check failed; ignoring.", exc_info=True)
        return {}
    if not failures:
        return {}
    failing_criterion, jev_reason = failures[0]
    combined_reason = f"Jev: {jev_reason} {agent_reason}".strip()
    return {
        "verdict": "rejected",
        "failing_criterion": failing_criterion,
        "reason": combined_reason,
    }


def _gate_queueing_verdict(
    validated_verdict: str,
    posting_text: str,
    profile: str,
    remote_arrangement: str,
    language_requirement: str,
    salary_stated: str,
    employment_country_stated: str,
    role_type_stated: str,
    eor_stated: str,
    failing_criterion: str,
    reason: str,
) -> dict:
    """Enforce the queueing gate for a validated 'passed'/'deferred' verdict.

    Called only when the record is about to queue (no ``screening_blocker``).
    Validates ``posting_text``, refuses (raises ``ValueError``) a call with no
    ``profile`` or no ``remote_arrangement``, normalises all six evidence
    fields, then evaluates them against the named ENABLED profile's six hard
    requirements (remote model, working language, salary floor, employment
    country, rejected role types, EOR). A contradicted verdict is downgraded
    to ``rejected`` — with ``failing_criterion`` set and the criteria evidence
    prefixed onto ``reason`` — rather than raised, so a genuinely bad call
    still gets a stored, explained record instead of nothing. When the
    deterministic checks all pass and Jev cross-checking is enabled, Jev's own
    opinion of the same six requirements is checked too (see
    ``_evaluate_jev_criteria``); its first reported failure downgrades the
    verdict the same way, with the reason prefixed 'Jev: '. Returns the
    (possibly updated) posting_text/verdict/failing_criterion/reason plus the
    six (possibly normalised) evidence fields, as a dict.
    """
    posting_text = _validate_posting_text(posting_text)
    if not profile or not remote_arrangement:
        raise ValueError(
            "profile and remote_arrangement are required to queue a "
            "passed/deferred verdict — without profile the operator cannot "
            "tell which profile's criteria this posting supposedly met, and "
            "an unchecked remote_arrangement is how non-remote postings "
            "reached the queue. Pass the JobProfile name and the posting's "
            "stated remote arrangement (screening_blocker exempts a posting "
            "the agent could not read)."
        )
    remote_arrangement = _validate_remote_arrangement(remote_arrangement)
    language_requirement = _validate_language_requirement(language_requirement)
    eor_stated = _validate_eor_stated(eor_stated)
    if salary_stated:
        salary_stated = _validate_stated_text(salary_stated)
    if employment_country_stated:
        employment_country_stated = _validate_stated_text(employment_country_stated)
    if role_type_stated:
        role_type_stated = _validate_stated_text(role_type_stated)
    evidence = {
        "remote_arrangement": remote_arrangement,
        "language_requirement": language_requirement,
        "salary_stated": salary_stated,
        "employment_country_stated": employment_country_stated,
        "role_type_stated": role_type_stated,
        "eor_stated": eor_stated,
    }
    override = _evaluate_profile_criteria(profile, evidence, reason)
    if override:
        validated_verdict = override["verdict"]
        failing_criterion = override["failing_criterion"]
        reason = override["reason"]
    else:
        override = _evaluate_jev_criteria(profile, posting_text, reason)
        if override:
            validated_verdict = override["verdict"]
            failing_criterion = override["failing_criterion"]
            reason = override["reason"]
    return {
        "posting_text": posting_text,
        "verdict": validated_verdict,
        "failing_criterion": failing_criterion,
        "reason": reason,
        "remote_arrangement": remote_arrangement,
        "language_requirement": language_requirement,
        "salary_stated": salary_stated,
        "employment_country_stated": employment_country_stated,
        "role_type_stated": role_type_stated,
        "eor_stated": eor_stated,
    }


def _finalize_screening(fields: dict, named: dict) -> tuple[Screening, bool]:
    """Merge non-empty ``named`` fields into ``fields`` and persist.

    Split out of ``record_screening`` purely to keep that function short: the
    optional-field merge (an omitted field never overwrites a stored value,
    which is why only truthy values are copied) and the store call belong
    together as one step. Shaping the result (``created`` on the dict) is the
    MCP adapter's job.
    """
    for name, value in named.items():
        if value:
            fields[name] = value
    return create_screening(fields)


def record_screening_verdict(
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
    profile: str = "",
    remote_arrangement: str = "",
    language_requirement: str = "",
    salary_stated: str = "",
    employment_country_stated: str = "",
    role_type_stated: str = "",
    eor_stated: str = "",
    extra_fields: dict | None = None,
) -> tuple[Screening, bool]:
    """Validate, gate and create-or-get one agent-reported screening verdict.

    This is the agent's screening workflow, behind the ``record_screening`` MCP
    tool (whose docstring is the contract for every field). It exists so the
    domain rules — the LinkedIn search-page rejection, hold-for-review
    deferral, the queueing gate against the profile's hard requirements and
    Jev, and today's-UTC-date stamping — live in the services layer rather
    than in the tool adapter. ``extra_fields`` carries any further fields the
    caller passed through ``**fields``.

    The HTTP ``POST /api/screenings`` route deliberately does NOT go through
    this function: it validates via ``ScreeningCreate`` and calls
    ``create_screening`` directly, without the queueing gate.

    Returns ``(screening, created)`` exactly as ``create_screening`` does.
    Every validation failure raises ``ValueError`` and persists nothing.
    """
    fields = dict(extra_fields or {})
    validated_url = _validate_posting_url(url)
    if not _is_posting_url(validated_url):
        raise ValueError(
            f"{validated_url!r} is a LinkedIn search/listing page, not a "
            "posting. Only linkedin.com/jobs/view/<id> URLs are accepted."
        )
    validated_role = _validate_role_title(role)
    fields["url"] = validated_url
    fields["role"] = validated_role
    fields["company"] = _validate_company_name(company)
    validated_blocker = _validate_blocker(screening_blocker) if screening_blocker else ""
    validated_verdict = _validate_verdict(verdict, blocker=validated_blocker)
    if not validated_blocker and _holds_for_review(
        validated_verdict, failing_criterion, remote_arrangement
    ):
        validated_verdict = "deferred"
        failing_criterion = ""
        reason = (
            "Remote arrangement not stated in the posting — held for your "
            "review. " + reason
        )
    fields["verdict"] = validated_verdict
    if validated_verdict in ("passed", "deferred") and not validated_blocker:
        # This is about to queue for the operator's decision: see
        # _gate_queueing_verdict for the posting_text/profile/criteria checks
        # that guard what reaches the approval queue.
        gated = _gate_queueing_verdict(
            validated_verdict,
            posting_text,
            profile,
            remote_arrangement,
            language_requirement,
            salary_stated,
            employment_country_stated,
            role_type_stated,
            eor_stated,
            failing_criterion,
            reason,
        )
        posting_text = gated["posting_text"]
        validated_verdict = gated["verdict"]
        fields["verdict"] = validated_verdict
        failing_criterion = gated["failing_criterion"]
        reason = gated["reason"]
        remote_arrangement = gated["remote_arrangement"]
        language_requirement = gated["language_requirement"]
        salary_stated = gated["salary_stated"]
        employment_country_stated = gated["employment_country_stated"]
        role_type_stated = gated["role_type_stated"]
        eor_stated = gated["eor_stated"]
    if not screened_date:
        # The caller left it blank: stamp today's UTC date rather than leave
        # it empty, since that is what an operator scanning screening dates
        # expects a just-recorded screening to carry. An explicitly supplied
        # date is always kept as given.
        screened_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
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
        "profile": profile,
        "remote_arrangement": remote_arrangement,
        "language_requirement": language_requirement,
        "salary_stated": salary_stated,
        "employment_country_stated": employment_country_stated,
        "role_type_stated": role_type_stated,
        "eor_stated": eor_stated,
    }
    return _finalize_screening(fields, named)
