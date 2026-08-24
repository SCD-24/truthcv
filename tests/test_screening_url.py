"""Posting URL validation: strips usable urls, rejects empty and malformed."""

from __future__ import annotations

import pytest

from screening.url import validate_posting_url


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
