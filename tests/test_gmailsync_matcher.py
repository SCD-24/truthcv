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
        ("EY", "ey"),
        ("HP Inc", "hp"),
        ("3M Deutschland GmbH", "3m"),
        ("XY GmbH", ""),
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


def test_short_name_matches_as_whole_word():
    """EY matches low as a whole word, not inside 'key'."""
    app = _app(company="EY")
    hit = match_message([app], sender="x@unrelated.example", subject="Your EY application", snippet="")
    assert hit is not None
    assert hit.confidence == "low"
    assert match_message([app], sender="x@unrelated.example", subject="They have the key to money", snippet="") is None


def test_short_name_sender_domain_exact_label():
    """ey.com matches an EY app; survey.com does not."""
    app = _app(company="EY")
    assert match_message([app], sender="no-reply@ey.com", subject="Hello", snippet="") is not None
    assert match_message([app], sender="no-reply@survey.com", subject="Hello", snippet="") is None


def test_ats_sender_with_company_and_role_is_high():
    """Greenhouse sender + greenhouse application URL + company + role -> high."""
    app = _app(
        company="Nebius",
        role="Data Engineer",
        application_url="https://job-boards.eu.greenhouse.io/nebius/jobs/123",
    )
    result = match_message(
        [app],
        sender="Nebius <no-reply@eu.greenhouse-mail.io>",
        subject="Your application for Data Engineer",
        snippet="Thanks from Nebius",
    )
    assert result is not None
    assert result.confidence == "high"
    assert "hiring platform matched greenhouse" in result.evidence


def test_ats_with_company_only_is_medium():
    """Lever platform + company keyword (no role) -> medium."""
    app = _app(company="Acme", role="Data Engineer", application_url="https://jobs.lever.co/acme/1")
    result = match_message([app], sender="hire@hire.eu.lever.co", subject="Update from Acme", snippet="")
    assert result is not None
    assert result.confidence == "medium"


def test_ats_only_is_low():
    """Same ATS family with no company/role text -> low."""
    app = _app(company="Acme", role="Data Engineer", application_url="https://jobs.lever.co/acme/1")
    result = match_message([app], sender="hire@hire.eu.lever.co", subject="Hello", snippet="")
    assert result is not None
    assert result.confidence == "low"


def test_two_apps_same_ats_only_tie_returns_none():
    """Two applications on one ATS with only platform evidence tie -> None."""
    apps = [
        _app(id="a1", company="Acme", application_url="https://boards.greenhouse.io/acme/1"),
        _app(id="a2", company="Beta", application_url="https://boards.greenhouse.io/beta/2"),
    ]
    assert match_message(apps, sender="x@greenhouse-mail.io", subject="Hello", snippet="") is None


def test_company_and_role_with_unrelated_sender_is_medium():
    """Company + role in text floors at medium even with an unrelated sender."""
    app = _app(company="Acme", role="Data Engineer")
    result = match_message(
        [app], sender="x@unrelated.example", subject="Acme: Data Engineer", snippet=""
    )
    assert result is not None
    assert result.confidence == "medium"


def test_hp_does_not_match_php():
    """HP app ignores 'php developer'."""
    result = match_message([_app(company="HP Inc")], sender="x@unrelated.example", subject="Jobs", snippet="php developer")
    assert result is None
