"""Salary helpers (agentconfig/salary.py) and the recommend_salary /
get_job_profiles MCP tools: clamping a proposed ask into a profile's
configured band, formatting an ask for display, and the tool-level
refusals when a profile is unknown or has no band configured.
"""

from __future__ import annotations

import pytest

from agentconfig.salary import clamp_ask, format_ask
from agentconfig.store import AgentConfig, JobProfile
from agentconfig.store import save as save_config
from mcp.tools_ledger import recommend_salary

_BAND_MIN = 95000
_BAND_MAX = 110000


def _save_profile(profile: JobProfile) -> JobProfile:
    """Persist a single-profile agent config and return the profile."""
    save_config(AgentConfig(profiles=[profile]))
    return profile


@pytest.fixture()
def banded_profile(data_dir):
    """A saved profile named 'Test Profile' with an EUR 95k-110k ask band."""
    profile = JobProfile(
        name="Test Profile",
        salary_ask_min=_BAND_MIN,
        salary_ask_max=_BAND_MAX,
        currency="EUR",
    )
    return _save_profile(profile)


# --- clamp_ask -------------------------------------------------------------


def test_clamp_ask_proposal_below_minimum_clamps_up():
    """A proposal under the band floor is clamped up to the minimum."""
    profile = JobProfile(salary_ask_min=95000, salary_ask_max=110000)
    assert clamp_ask(profile, 90000) == 95000


def test_clamp_ask_proposal_above_maximum_clamps_down():
    """A proposal over the band ceiling is clamped down to the maximum."""
    profile = JobProfile(salary_ask_min=95000, salary_ask_max=110000)
    assert clamp_ask(profile, 120000) == 110000


def test_clamp_ask_proposal_within_band_passes_through():
    """A proposal already inside the band is returned unchanged."""
    profile = JobProfile(salary_ask_min=95000, salary_ask_max=110000)
    assert clamp_ask(profile, 100000) == 100000


def test_clamp_ask_proposed_none_yields_minimum():
    """No proposal at all defaults to the band minimum."""
    profile = JobProfile(salary_ask_min=95000, salary_ask_max=110000)
    assert clamp_ask(profile, None) == 95000


def test_clamp_ask_missing_bound_returns_none():
    """Either bound missing means we decline to guess: return None."""
    no_min = JobProfile(salary_ask_min=None, salary_ask_max=110000)
    no_max = JobProfile(salary_ask_min=95000, salary_ask_max=None)
    assert clamp_ask(no_min, 100000) is None
    assert clamp_ask(no_max, 100000) is None


def test_clamp_ask_inverted_bounds_defensive():
    """A misconfigured profile (min > max) must not crash or invent a
    number outside the sorted bounds; None or a swapped clamp is fine."""
    profile = JobProfile(salary_ask_min=110000, salary_ask_max=95000)
    result = clamp_ask(profile, 100000)
    assert result is None or 95000 <= result <= 110000


# --- format_ask --------------------------------------------------------


def test_format_ask_with_eur_and_thousands_separator():
    """EUR amounts are formatted with a thousands separator."""
    profile = JobProfile(currency="EUR")
    assert format_ask(profile, 105000) == "EUR 105,000"


def test_format_ask_with_non_eur_currency():
    """Non-EUR currencies use the profile's own currency code."""
    profile = JobProfile(currency="GBP")
    assert format_ask(profile, 50000) == "GBP 50,000"


def test_format_ask_with_none_amount_returns_empty():
    """A None amount formats as an empty string, not 'EUR None'."""
    profile = JobProfile(currency="EUR")
    assert format_ask(profile, None) == ""


# --- recommend_salary MCP tool ------------------------------------------


def test_recommend_salary_clamps_proposal(banded_profile):
    """A proposal above the band is clamped down and marked as clamped."""
    result = recommend_salary(profile_name=banded_profile.name, proposed=120000)
    assert result["amount"] == _BAND_MAX
    assert result["clamped"] is True


def test_recommend_salary_omitted_proposal_is_supplied_not_clamped(banded_profile):
    """With no proposal the band minimum is supplied, so nothing was clamped.

    Reporting clamped=True here would tell the agent its own figure had been
    overridden when it never offered one.
    """
    result = recommend_salary(profile_name=banded_profile.name)
    assert result["amount"] == _BAND_MIN
    assert result["clamped"] is False


def test_recommend_salary_refuses_unknown_profile(data_dir):
    """An unrecognised profile name yields a refusal, not a guessed figure."""
    result = recommend_salary(profile_name="Does Not Exist")
    assert "refused" in result


def test_recommend_salary_refuses_profile_with_no_band(data_dir):
    """A profile missing either ask bound yields a refusal."""
    profile = JobProfile(name="No Band", salary_ask_min=None, salary_ask_max=110000)
    _save_profile(profile)
    result = recommend_salary(profile_name="No Band")
    assert "refused" in result


@pytest.mark.parametrize(
    "proposed", [-1_000_000, -1, 0, 94999, 95000, 100000, 110000, 110001, 10**9]
)
def test_recommend_salary_never_returns_amount_outside_band(banded_profile, proposed):
    """Whatever is proposed, the returned amount never escapes the band."""
    result = recommend_salary(profile_name=banded_profile.name, proposed=proposed)
    amount = result.get("amount")
    assert amount is None or _BAND_MIN <= amount <= _BAND_MAX


# --- JobProfile currency round-trip --------------------------------------


def test_job_profile_currency_defaults_to_eur():
    """from_dict without a currency key defaults to EUR."""
    profile = JobProfile.from_dict({"name": "Test"})
    assert profile.currency == "EUR"


def test_job_profile_currency_round_trips():
    """A non-default currency survives from_dict -> to_dict unchanged."""
    profile = JobProfile.from_dict({"name": "Test", "currency": "GBP"})
    assert profile.to_dict()["currency"] == "GBP"
