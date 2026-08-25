"""Posting URL validation: strips usable urls, rejects empty and malformed."""

from __future__ import annotations

import pytest

from screening.url import normalize_application_url, validate_posting_url


def test_valid_https_url_returned_stripped():
    assert validate_posting_url("  https://acme.example/jobs/1  ") == (
        "https://acme.example/jobs/1"
    )


def test_valid_http_url_accepted():
    assert validate_posting_url("http://acme.example/jobs/1") == (
        "http://acme.example/jobs/1"
    )


def test_empty_string_raises():
    with pytest.raises(ValueError):
        validate_posting_url("")


def test_whitespace_only_raises():
    with pytest.raises(ValueError):
        validate_posting_url("   ")


def test_missing_scheme_raises():
    with pytest.raises(ValueError):
        validate_posting_url("acme.example/jobs/1")


def test_non_http_scheme_raises():
    with pytest.raises(ValueError):
        validate_posting_url("ftp://x/1")


def test_screening_and_application_urls_normalize_equal():
    screening = "https://x.example.com/j/4d090169-xxxx/"
    application = "https://X.example.com/j/4d090169-xxxx/application"
    assert normalize_application_url(screening) == (
        normalize_application_url(application)
    )


def test_tracking_query_params_ignored():
    plain = "https://x.example.com/j/4d090169-xxxx/"
    tracked = "https://x.example.com/j/4d090169-xxxx/?src=li&utm_x=y"
    assert normalize_application_url(plain) == normalize_application_url(tracked)


def test_case_and_trailing_slash_insensitive():
    a = "HTTPS://X.Example.COM/j/4d090169-xxxx"
    b = "https://x.example.com/j/4d090169-xxxx/"
    assert normalize_application_url(a) == normalize_application_url(b)


def test_empty_input_returns_empty_string():
    assert normalize_application_url("") == ""


def test_garbage_input_does_not_raise():
    result = normalize_application_url("not a url at all")
    assert isinstance(result, str)
