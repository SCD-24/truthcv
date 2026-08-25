"""Tests for screening.company.company_identity_key."""

from screening.company import company_identity_key


def test_robco_suffix_variants_collapse_to_same_key():
    """A legal-entity suffix, casing, punctuation and whitespace all wash out."""
    keys = {
        company_identity_key("RobCo"),
        company_identity_key("RobCo GmbH"),
        company_identity_key("RobCo gmbh."),
        company_identity_key("  RobCo   GmbH "),
    }
    assert keys == {"robco"}


def test_parenthesised_legal_form_is_not_stripped():
    """A suffix that sits inside parentheses, not at the true end, is untouched."""
    assert company_identity_key("Klar (Klar Technologies GmbH)") == (
        "klar (klar technologies gmbh)"
    )
    assert company_identity_key("Noxtua (Xayn AG)") == "noxtua (xayn ag)"


def test_suffix_only_name_is_non_empty():
    """A name that is only a suffix must still return a non-empty key."""
    limited_key = company_identity_key("Limited")
    gmbh_key = company_identity_key("GmbH")
    assert limited_key != ""
    assert gmbh_key != ""
    # Different suffix words are different companies; they must not collide.
    assert limited_key != gmbh_key


def test_non_str_and_none_return_empty_string():
    """A non-str input (including None) never raises and yields ''."""
    assert company_identity_key(None) == ""
    assert company_identity_key(123) == ""
    assert company_identity_key([]) == ""


def test_compound_suffix_reduces_cleanly():
    """A compound German legal form reduces down to the bare trade name."""
    assert company_identity_key("Foo GmbH & Co. KG") == "foo"


def test_different_legal_forms_of_same_root_collapse_known_false_positive():
    """KNOWN AND ACCEPTED: differing legal forms of an unrelated pair can collide.

    "Acme AG" and "Acme Ltd" are, in the general case, potentially different
    legal entities that merely share a trade name. Collapsing them to the
    same identity key is the one accepted false-positive class of this
    function: per the plan, it is deliberately tolerated because it can only
    ever cause a *merge* when the normalized posting URL is also identical.
    """
    assert company_identity_key("Acme AG") == company_identity_key("Acme Ltd")
