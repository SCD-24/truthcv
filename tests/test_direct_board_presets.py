"""Direct-board presets: lookup, operator precedence, validity, URL matching."""

import re

import pytest

from agentconfig import boards
from agentconfig.direct_board_presets import DIRECT_BOARD_PRESETS, preset_for
from agentconfig.dorks import compose_direct_boards
from agentconfig.store import JobBoard, JobProfile


def _glob_to_regexp(pattern):
    """Mirror harvestLinks.ts globToRegExp: escape, * -> \\S*, start-anchored."""
    parts = [re.escape(p) for p in pattern.split("*")]
    return re.compile("^" + r"\S*".join(parts))


def _compose(board):
    p = JobProfile(name="p", enabled=True, keywords=["backend"])
    return compose_direct_boards([p], [board])[0]


def test_lookup_with_and_without_www():
    assert preset_for("https://www.arbeitsagentur.de/") == preset_for("arbeitsagentur.de")
    assert preset_for("arbeitsagentur.de") is not None


def test_unknown_host_has_no_preset_and_is_unchanged():
    assert preset_for("boards.acme.io") is None
    entry = _compose(JobBoard(source="https://boards.acme.io/careers", mode="direct"))
    assert entry["search_url"] == ""
    assert entry["posting_url_pattern"] == ""


def test_blank_operator_fields_are_filled_from_preset():
    entry = _compose(JobBoard(source="https://talentsift.de", mode="direct"))
    assert entry["search_url"] == "https://talentsift.de/jobs?q={keywords}"
    assert entry["posting_url_pattern"] == "https://talentsift.de/jobs/*"


def test_operator_values_win():
    board = JobBoard(
        source="https://talentsift.de",
        mode="direct",
        search_url="https://talentsift.de/s?q={keywords}",
        posting_url_pattern="https://talentsift.de/p/*",
    )
    entry = _compose(board)
    assert entry["search_url"] == "https://talentsift.de/s?q={keywords}"
    assert entry["posting_url_pattern"] == "https://talentsift.de/p/*"


@pytest.mark.parametrize("host", sorted(DIRECT_BOARD_PRESETS))
def test_preset_values_pass_validators(host):
    preset = DIRECT_BOARD_PRESETS[host]
    assert boards.search_url_error(preset["search_url"]) is None
    assert boards.posting_url_pattern_error(preset["posting_url_pattern"]) is None


SAMPLES = {
    "arbeitsagentur.de": ["https://www.arbeitsagentur.de/jobsuche/jobdetail/12345-ABC"],
    "startupjobs.de": [
        "https://startupjobs.de/jobs/3f2b8c1e-aaaa-bbbb-cccc-1234567890ab",
        "https://startupjobs.de/en/jobs/3f2b8c1e-aaaa-bbbb-cccc-1234567890ab",
    ],
    "talentsift.de": ["https://talentsift.de/jobs/some-slug"],
    "nomado24.de": ["https://www.nomado24.de/en/remote-jobs/job/some-slug"],
}


@pytest.mark.parametrize("host", sorted(SAMPLES))
def test_pattern_matches_postings_but_not_its_search_url(host):
    preset = DIRECT_BOARD_PRESETS[host]
    rx = _glob_to_regexp(preset["posting_url_pattern"])
    for url in SAMPLES[host]:
        assert rx.match(url), url
    search = preset["search_url"].format(keywords="python", location="berlin")
    if search:
        assert not rx.match(search)
