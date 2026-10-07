"""gmailsync.matcher: company keyword extraction skips stopwords/short words."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from gmailsync.matcher import _app_domains, _company_token, match_message


def _app(**overrides):
    fields = {"id": "a1", "company": "The Quality Group GmbH", "website": "", "application_url": "", "role": ""}
    fields.update(overrides)
    return SimpleNamespace(**fields)


@pytest.mark.parametrize(
    "company,expected",
    [
        ("The Quality Group GmbH", "quality"),
        ("TP Infinity Germany GmbH", "infinity"),
        ("Acme Corp", "acme"),
        ("The Group GmbH", ""),
    ],
)
def test_company_token(company, expected):
    """Stopwords and short words are skipped."""
    assert _company_token(company) == expected


def test_app_domains_has_no_stopword_token():
    """No 'the' domain term is produced."""
    domains = _app_domains(_app())
    assert "the" not in domains
    assert "quality" in domains


def test_job_alert_with_the_and_there_does_not_match():
    """Generic words in a job alert do not match the company."""
    result = match_message(
        [_app()],
        sender="Remote Rocketship <alerts@remoterocketship.com>",
        subject="New jobs for you: there are roles in the market",
        snippet="Check out the latest openings there",
    )
    assert result is None


def test_quality_mention_matches_low():
    """A message mentioning the real keyword still matches low."""
    result = match_message(
        [_app()],
        sender="News <news@unrelated.example>",
        subject="Update from Quality",
        snippet="",
    )
    assert result is not None
    assert result.confidence == "low"
