"""Validation for a job posting URL.

A screening is only actionable if the operator can open the posting it came
from. This module provides a strict check for that URL, kept standalone and
deliberately separate from ``screening.store`` — the store stays lenient about
urls so the legacy importer (``scripts/migrate_jobs_history.py``) can bring in
historical records that predate this requirement.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_APPLICATION_SEGMENTS = frozenset(
    {"apply", "application", "applications", "apply-now"}
)


def validate_posting_url(url: str) -> str:
    """Return ``url`` stripped, or raise ``ValueError`` if it is unusable.

    A usable posting URL is non-empty after stripping, has an ``http`` or
    ``https`` scheme, and names a host. Anything else raises ``ValueError``:
    an empty input has its own message, and a malformed URL is reported with
    the offending value included.
    """
    stripped = url.strip()
    if not stripped:
        raise ValueError(
            "A posting URL is required — a screening the operator cannot open "
            "cannot be applied to."
        )

    parsed = urlparse(stripped)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"Not a valid posting URL: {stripped!r}")

    return stripped


def normalize_application_url(url: str) -> str:
    """Return a normalized form of ``url`` for equality comparison.

    The "already applied" guard compares the URL of the screening being worked
    against the URL recorded when the operator applied. Those two strings refer
    to the same posting but are rarely byte-identical: the screening might hold
    ``https://x.example.com/j/4d090169-xxxx/`` while the recorded application
    URL is ``https://x.example.com/j/4d090169-xxxx/application`` — same job,
    different trailing segment — so the guard never matched and let duplicate
    applications through. This function collapses such cosmetic differences
    (scheme/host case, tracking query params, a trailing slash, and a trailing
    ``apply``/``application`` segment) to a canonical string so the pair
    compares equal.

    This is a matching helper, not a validator: it never raises. An empty or
    unparseable input yields ``""``.
    """
    stripped = url.strip()
    if not stripped:
        return ""

    try:
        parsed = urlparse(stripped)
    except ValueError:
        return ""

    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()

    path = parsed.path
    # Strip exactly one trailing slash.
    if path.endswith("/"):
        path = path[:-1]
    # Strip exactly one trailing application-ish segment.
    head, sep, last = path.rpartition("/")
    if sep and last.lower() in _APPLICATION_SEGMENTS:
        path = head

    # Drop the query string and fragment.
    return urlunparse((scheme, netloc, path, parsed.params, "", ""))


# Query parameters that identify the *campaign*, not the posting. Dropping
# these lets the same job survive arriving from a job alert, a search page and
# a direct link; keeping everything else is deliberate, because on several
# boards the query string is the only thing that names the job at all
# (``https://upsun.com/job/?gh_jid=8656285002`` has no job id in its path, so
# discarding the query would collapse every Upsun posting into one key).
_TRACKING_PARAMS = frozenset(
    {
        "gh_src",
        "lever-origin",
        "lever-source",
        "ref",
        "referrer",
        "source",
        "src",
        "trk",
        "trackingid",
    }
)


def posting_dedupe_key(url: str) -> str:
    """Return the identity of the posting ``url`` points at, for dedupe.

    Two URLs that yield the same key are the same job posting, and the
    screening store refuses to hold a second record for one (see
    ``screening.store.create_or_get``). The key collapses only differences
    that are cosmetic for that purpose: scheme and host case, a trailing
    slash, a trailing ``apply``/``application`` segment, the fragment, and
    tracking parameters (``_TRACKING_PARAMS``, plus anything ``utm_``-
    prefixed). Parameter order is normalized so ``?a=1&b=2`` and ``?b=2&a=1``
    agree.

    Deliberately NOT the same function as ``normalize_application_url``: that
    one drops the whole query string, which is safe for its own job (matching
    one screening against one recorded application, both for a company the
    caller already matched) but not safe here, where a false match silently
    discards a real posting the operator would never learn about.

    A matching helper, not a validator: it never raises. An input that does
    not resolve to a posting — blank, or lacking an http(s) scheme and a host
    — yields ``""``, which callers must read as "no identity" and never as a
    key two such records share. The legacy importer is the one writer that
    can store such a row, and two rows the store cannot resolve to a posting
    are not thereby the same posting.
    """
    stripped = url.strip()
    if not stripped:
        return ""

    try:
        parsed = urlparse(stripped)
    except ValueError:
        return ""
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        return ""

    path = parsed.path
    if path.endswith("/"):
        path = path[:-1]
    head, sep, last = path.rpartition("/")
    if sep and last.lower() in _APPLICATION_SEGMENTS:
        path = head

    kept = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in _TRACKING_PARAMS
        and not key.lower().startswith("utm_")
    ]

    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            parsed.params,
            urlencode(sorted(kept)),
            "",
        )
    )
