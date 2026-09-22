"""Jev (TypeSafe System One) cross-check client: optional hard-requirement
verification for a job posting via natural-language "Noul" questions.

Jev is a third-party service the operator opts into from the Settings page.
Given a body of text (the "state") and a set of named questions, it answers
each with a confidence score in [0, 1] ("Noul") that the state matches the
question's instructions. This module turns a job profile's hard requirements
into one batch of Noul questions per posting, sends them in a single request,
and reports back which ones Jev flagged as true — i.e. the posting appears to
violate that requirement — at or above JEV_REJECT_THRESHOLD.

Like jobfeeds.remoterocketship, a call here NEVER raises for the caller's
benefit: any transport failure, timeout, or unexpected response shape fails
open (an empty result), because Jev is a cross-check on top of the operator's
own screening criteria, not the source of truth. The API key is never logged,
echoed, or returned.
"""

from __future__ import annotations

import http.client
import json
import logging
import urllib.error
import urllib.request

from agentconfig.store import JobProfile

logger = logging.getLogger(__name__)

#: Jev's single question-answering endpoint.
API_URL = "https://api.typesafe.ai/v1/systemone"

#: The only model this client speaks to.
MODEL = "jev-latest"

TIMEOUT_SECONDS = 8.0

# A Noul answer at or above this confidence is treated as Jev confirming the
# posting violates that requirement. Below it, the answer is inconclusive and
# treated as a pass rather than a false rejection.
JEV_REJECT_THRESHOLD = 0.8


def _saved_key() -> str:
    """The saved Jev API key, or "" if none is configured.

    Resolution (secrets.enc, then the JEV_API_KEY env var) is handled by
    secretstore.get_connection itself.
    """
    import secretstore

    key = secretstore.get_connection("jev").get("apiKey", "")
    return key.strip() if isinstance(key, str) else ""


def enabled() -> bool:
    """Whether Jev cross-checking should run for screening.

    True only when a key is available AND the operator has opted in via the
    ``useForScreening`` toggle — a saved key alone does not turn this on.
    """
    import secretstore

    if not _saved_key():
        return False
    return secretstore.get_connection("jev").get("useForScreening") is True


def _post(
    key: str, state: str, questions: dict[str, dict[str, str]]
) -> tuple[dict | None, str | None]:
    """POST one systemone request. Returns ``(data, None)`` on success or
    ``(None, detail)`` on failure, where ``detail`` is a caller-safe summary
    of what went wrong. Never raises; never logs or returns the key or the
    posting text."""
    payload = json.dumps({"state": state, "model": MODEL, "questions": questions}).encode()
    request = urllib.request.Request(
        API_URL,
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        data=payload,
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            data = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        # MUST be caught before URLError: HTTPError subclasses it.
        logger.warning("Jev request failed with HTTP %s", exc.code)
        if exc.code in (401, 403):
            return None, f"Jev rejected the API key (HTTP {exc.code})."
        return None, f"Jev returned HTTP {exc.code}."
    except urllib.error.URLError as exc:
        logger.warning("Jev request failed: %s", type(exc).__name__)
        return None, "Could not reach Jev."
    except TimeoutError as exc:
        logger.warning("Jev request timed out: %s", type(exc).__name__)
        return None, "Could not reach Jev."
    except (OSError, http.client.HTTPException) as exc:
        logger.warning("Jev request failed: %s", type(exc).__name__)
        return None, "Could not reach Jev."
    except ValueError as exc:
        logger.warning("Jev returned an unparseable response: %s", type(exc).__name__)
        return None, "Jev returned an unexpected response."

    if not isinstance(data, dict):
        logger.warning("Jev returned an unexpected response shape: %s", type(data).__name__)
        return None, "Jev returned an unexpected response."
    return data, None


def check_key(key: str) -> tuple[bool, str]:
    """Verify a key with a single minimal live request. Returns (ok, detail).

    Used by the settings "test connection" route. Never raises.
    """
    key = key.strip() if isinstance(key, str) else ""
    if not key:
        return False, "No API key saved."
    result, detail = _post(
        key,
        "This is a connectivity check.",
        {"ping": {"type": "noul", "instructions": "This text is a connectivity check."}},
    )
    if result is None:
        return False, detail
    if not isinstance(result.get("answers"), dict):
        return False, "Jev returned an unexpected response shape."
    return True, "Jev accepted the key."


def _email_tracking_enabled() -> bool:
    """Whether Jev should be consulted for Gmail response-tracking decisions.

    True only when a key is available AND the operator has opted in via the
    ``useForEmailTracking`` toggle — distinct from ``useForScreening``, and
    defaults to False/off when the flag is absent.
    """
    import secretstore

    if not _saved_key():
        return False
    return secretstore.get_connection("jev").get("useForEmailTracking") is True


def confirm(statement: str, state: str) -> bool:
    """Ask Jev a single yes/no Noul question about ``state``.

    Used to gate an automatic decision (e.g. "this email is a rejection") on
    a Jev cross-check rather than acting on the classifier alone. Keys the
    one question by a stable name so the request shape never depends on the
    caller's statement text. Fails open to False (no confirmation) when
    email-tracking isn't enabled, or on ANY transport/shape failure. Never
    logs the key or ``state``.
    """
    if not _email_tracking_enabled():
        return False
    result, _detail = _post(
        _saved_key(), state, {"decision": {"type": "noul", "instructions": statement}}
    )
    if result is None:
        return False
    answers = result.get("answers")
    if not isinstance(answers, dict):
        logger.warning("Jev returned an unexpected response shape.")
        return False
    answer = answers.get("decision")
    score = answer.get("noul") if isinstance(answer, dict) else None
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        return False
    return score >= JEV_REJECT_THRESHOLD


def _hard_requirement_questions(profile: JobProfile) -> dict[str, str]:
    """Build one Noul question per hard requirement the profile actually sets.

    Keyed by a stable criterion name, so a flagged answer can be traced back
    to the requirement it corresponds to. A profile that sets none of these
    fields yields an empty dict, and no request is made.
    """
    questions: dict[str, str] = {}

    for role_type in profile.rejected_role_types:
        role_type = role_type.strip()
        if not role_type:
            continue
        questions[f"rejected_role_type:{role_type}"] = f"This posting is for a {role_type} role."

    if profile.salary_floor is not None and profile.salary_floor > 0:
        currency = (profile.currency or "").strip() or "the stated currency"
        questions["salary_floor"] = (
            f"The posting states a maximum salary below {profile.salary_floor} {currency}."
        )

    country = (profile.employment_country or "").strip()
    if country:
        questions["employment_country"] = (
            f"The posting requires the employee to be employed outside {country}."
        )

    if profile.eor_allowed is False:
        questions["eor_allowed"] = (
            "The employer hires through an EOR / employer-of-record arrangement."
        )

    if (profile.remote_model or "").strip().casefold() == "remote":
        questions["remote_model"] = (
            "The posting requires the employee to work on-site rather than fully remote."
        )

    return questions


def evaluate_hard_requirements(profile: JobProfile, posting_text: str) -> list[tuple[str, str]]:
    """Cross-check a posting against a profile's hard requirements via Jev.

    Builds one question per hard requirement the profile sets
    (``_hard_requirement_questions``) and sends them all in a SINGLE request,
    with ``posting_text`` as the state. Returns a ``(failing_criterion,
    reason)`` pair for every question whose Noul answer is at or above
    JEV_REJECT_THRESHOLD.

    Fails open (returns ``[]``) when Jev is not enabled, the profile sets no
    applicable requirement, or the request fails for any reason — a
    transport error, a timeout, or an unexpected response shape.
    """
    if not enabled():
        return []
    questions = _hard_requirement_questions(profile)
    if not questions:
        return []

    key = _saved_key()
    result, _detail = _post(
        key,
        posting_text,
        {name: {"type": "noul", "instructions": instructions} for name, instructions in questions.items()},
    )
    if result is None:
        return []

    answers = result.get("answers")
    if not isinstance(answers, dict):
        logger.warning("Jev returned an unexpected response shape.")
        return []

    failures: list[tuple[str, str]] = []
    for name, instructions in questions.items():
        answer = answers.get(name)
        score = answer.get("noul") if isinstance(answer, dict) else None
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            continue
        if score >= JEV_REJECT_THRESHOLD:
            failures.append((name, f"{instructions} (confidence {score:.2f})"))
    return failures
