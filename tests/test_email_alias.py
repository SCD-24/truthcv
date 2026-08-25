"""Per-company email aliasing: company_slug and alias_email."""

from __future__ import annotations

from truth.emailalias import ALIAS_PREFIX, alias_email, company_slug


def test_company_slug_basic():
    assert company_slug("Acme Co.") == "acme_co"


def test_company_slug_n26():
    assert company_slug("N26 GmbH") == "n26_gmbh"


def test_company_slug_blank():
    assert company_slug("  ") == ""


def test_company_slug_all_punctuation():
    assert company_slug("!!!") == ""


def test_company_slug_truncates_without_trailing_underscore():
    long_company = "A" * 50 + " Very Long Company Name Indeed"
    slug = company_slug(long_company)
    assert len(slug) <= 36
    assert not slug.endswith("_")


def test_alias_email_happy_path():
    assert (
        alias_email("glenn.chon.de@gmail.com", "Acme Co.")
        == "glenn.chon.de+tcv_acme_co@gmail.com"
    )


def test_alias_email_contains_alias_prefix_marker():
    result = alias_email("glenn.chon.de@gmail.com", "Acme Co.")
    assert f"+{ALIAS_PREFIX}" in result


def test_alias_email_passthrough_blank_company():
    email = "glenn.chon.de@gmail.com"
    assert alias_email(email, "") == email


def test_alias_email_passthrough_company_slugs_to_empty():
    email = "glenn.chon.de@gmail.com"
    assert alias_email(email, "!!!") == email


def test_alias_email_passthrough_no_at_sign():
    email = "not-an-email"
    assert alias_email(email, "Acme Co.") == email


def test_alias_email_passthrough_two_at_signs():
    email = "a@b@c.com"
    assert alias_email(email, "Acme Co.") == email


def test_alias_email_passthrough_empty_local_part():
    email = "@gmail.com"
    assert alias_email(email, "Acme Co.") == email


def test_alias_email_passthrough_empty_domain():
    email = "glenn.chon.de@"
    assert alias_email(email, "Acme Co.") == email


def test_alias_email_passthrough_local_already_has_plus():
    email = "glenn.chon.de+other@gmail.com"
    assert alias_email(email, "Acme Co.") == email


def test_alias_email_non_gmail_domain():
    assert (
        alias_email("jane.doe@example.org", "N26 GmbH")
        == "jane.doe+tcv_n26_gmbh@example.org"
    )
