"""daily-apply.sh renders API-backed feed postings into the run prompt.

The jq expressions are EXTRACTED FROM THE SCRIPT AND RUN, not grepped for. The
failure this guards against is a field-name mismatch: jobfeeds emits snake_case
dataclass fields, but what reaches the script is the API's camelCase wire shape,
and a wrong key makes jq render an empty string rather than fail — so the
postings would silently vanish from the prompt with nothing to notice.
"""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path("agent/daily-apply.sh").read_text()

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="jq is not installed")


def _expression(marker: str) -> str:
    """Pull one `jq -r '<expr>'` out of the script by a substring of the expression."""
    line = next(ln for ln in SCRIPT.splitlines() if marker in ln and "jq -r" in ln)
    return line.split("jq -r '", 1)[1].rsplit("'", 1)[0]


def _run(expression: str, payload: dict) -> str:
    result = subprocess.run(
        ["jq", "-r", expression],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _rendered_feed_block(payload: dict) -> str:
    """Execute the exact two if-blocks that build the feed portion of
    PROFILE_BLOCK — via real bash + jq, against the script's OWN current
    text — so a header swapped onto the wrong group's if-block (BLOCKING 3)
    makes the rendered text visibly wrong. Asserting on the header strings
    and the jq bodies independently (as the rest of this file does) cannot
    see which if-block either one actually lives in; this can."""
    start = SCRIPT.index('    FEED_PROFILE_MATCHED="$(jq -r')
    company_boards_start = SCRIPT.index('    FEED_COMPANY_BOARDS="$(jq -r')
    end = SCRIPT.index("\n    fi\n", company_boards_start) + len("\n    fi")
    snippet = SCRIPT[start:end]
    script = (
        "JOB_CONFIG=" + shlex.quote(json.dumps(payload)) + "\n"
        'PROFILE_BLOCK=""\n' + snippet + "\n"
        'printf \'%s\' "$PROFILE_BLOCK"\n'
    )
    result = subprocess.run(["bash"], input=script, capture_output=True, text=True, check=True)
    return result.stdout


# Two feed groups are rendered separately (see BLOCKING 2): Remote Rocketship
# postings, matched against a profile and carrying `.profile`, and ATS/company
# board postings, which carry no profile at all.
RR_EXPR = _expression('select((.profile // "") != "")')
ATS_EXPR = _expression('select((.profile // "") == "")')
ERROR_EXPR = _expression(".feedError")

POSTING = {
    "profile": "Senior Python",
    "source": "remoterocketship",
    "title": "Senior Platform Engineer",
    "company": "Acme",
    "url": "https://acme.example/jobs/1",
    "employmentType": "full-time",
    "salaryRange": "$120k-$150k",
    "postedAt": "2026-08-26T09:00:00.000Z",
    "tier": "api",
}

ATS_POSTING = {
    "profile": "",
    "source": "greenhouse",
    "title": "Warehouse Associate",
    "company": "Acme",
    "url": "https://boards.greenhouse.io/acme/jobs/1",
    "postedAt": "2026-08-26T09:00:00.000Z",
    "tier": "api",
}


def test_a_posting_renders_its_profile_title_company_salary_and_url():
    out = _run(RR_EXPR, {"feedPostings": [POSTING]})
    assert "[Senior Python]" in out
    assert "Senior Platform Engineer" in out
    assert "Acme" in out
    assert "$120k-$150k" in out
    assert "https://acme.example/jobs/1" in out


def test_a_posting_renders_its_source_and_tier():
    out = _run(RR_EXPR, {"feedPostings": [POSTING]})
    assert "remoterocketship" in out
    assert "api" in out


def test_a_posting_missing_tier_still_renders():
    """An older app image serving no tier must not break the render — a
    posting missing the field still renders its title, source and URL."""
    no_tier = {k: v for k, v in POSTING.items() if k != "tier"}
    out = _run(RR_EXPR, {"feedPostings": [no_tier]})
    assert "null" not in out
    assert "Senior Platform Engineer" in out
    assert "remoterocketship" in out
    assert "https://acme.example/jobs/1" in out


def test_a_posting_missing_company_and_salary_still_renders_title_and_url():
    """Those two are optional on the wire. Rendering "null" or dropping the
    posting entirely are both worse than an unadorned line."""
    bare = {**POSTING, "company": "", "salaryRange": ""}
    out = _run(RR_EXPR, {"feedPostings": [bare]})
    assert "null" not in out
    assert "Senior Platform Engineer" in out
    assert "https://acme.example/jobs/1" in out


def test_absent_company_and_salary_keys_do_not_break_the_render():
    """A field the API stopped sending must not abort the whole prompt build —
    the script runs under `set -e`, so a jq error would end the run."""
    stripped = {k: v for k, v in POSTING.items() if k not in ("company", "salaryRange")}
    out = _run(RR_EXPR, {"feedPostings": [stripped]})
    assert "https://acme.example/jobs/1" in out


def test_an_empty_feed_renders_nothing():
    assert _run(RR_EXPR, {"feedPostings": []}).strip() == ""
    assert _run(RR_EXPR, {}).strip() == ""
    assert _run(ATS_EXPR, {"feedPostings": []}).strip() == ""
    assert _run(ATS_EXPR, {}).strip() == ""


def test_the_feed_error_is_extracted_so_it_can_be_shown():
    """An empty feed and a rejected API key look identical in the prompt
    otherwise, and the agent would apply to fewer jobs with no reason logged."""
    assert _run(ERROR_EXPR, {"feedError": "Invalid API key"}).strip() == "Invalid API key"
    assert _run(ERROR_EXPR, {}).strip() == ""


def test_the_feed_block_tells_the_agent_the_postings_are_not_pre_approved():
    """A pulled posting is a discovery result, not a decision. Without this the
    prompt reads as a work list and the profile criteria become advisory."""
    assert "still subject to every profile criterion" in SCRIPT


def test_a_feed_failure_does_not_instruct_the_agent_to_stop():
    assert "do not treat this as a reason to stop" in SCRIPT


# --- BLOCKING 2: ATS postings must not claim to be profile-filtered, and an
# empty profile must not render as an empty "[]" -------------------------


def test_an_ats_posting_with_no_profile_renders_a_meaningful_placeholder():
    """Regression: ats.py never sets `.profile`, so it stays "" and used to
    render "- [] Warehouse Associate ..." — an empty bracket, not a label."""
    out = _run(ATS_EXPR, {"feedPostings": [ATS_POSTING]})
    assert "[]" not in out
    assert "[Company board]" in out
    assert "Warehouse Associate" in out
    assert "https://boards.greenhouse.io/acme/jobs/1" in out


def test_an_ats_posting_does_not_match_the_profile_filtered_expression():
    """A profile-matched posting (non-empty `.profile`) must not also appear
    under the company-board rendering, and vice versa — the two groups are
    mutually exclusive partitions of `.feedPostings`."""
    assert _run(ATS_EXPR, {"feedPostings": [POSTING]}).strip() == ""
    assert _run(RR_EXPR, {"feedPostings": [ATS_POSTING]}).strip() == ""


def test_the_pre_filtered_claim_is_scoped_to_remote_rocketship_only_and_hedged():
    """The prompt must not tell the agent every posting in the feed block was
    already filtered by profile criteria — that is only true of the
    Remote-Rocketship/profile-matched group, and even for them not absolutely
    (see jobfeeds.remoterocketship.filters_for_profile: an unstated salary
    still passes a salary floor, and an unrecognised location narrows
    nothing), so the claim must be hedged rather than absolute."""
    assert "pre-filtered by the board's own keyword and location matching" in SCRIPT
    assert "already filtered by profile keywords, locations and salary floor" not in SCRIPT
    assert "NOT filtered by profile keywords" in SCRIPT


def test_each_header_is_pinned_to_its_own_groups_postings():
    """Regression (BLOCKING 3): swapping the two header strings between the
    two if-blocks made company-board postings claim to be pre-filtered and
    Remote Rocketship postings claim NOT to be, and every other test in this
    file still passed — because they check the jq expressions and the header
    strings independently of which if-block either actually sits in. This
    renders both groups from one real payload, through real bash + jq, and
    checks each header sits directly beside its OWN group's posting."""
    out = _rendered_feed_block({"feedPostings": [POSTING, ATS_POSTING]})
    rr_header_at = out.index("pre-filtered by the board's own keyword and location matching")
    ats_header_at = out.index("NOT filtered by profile keywords")
    rr_posting_at = out.index("Senior Platform Engineer")
    ats_posting_at = out.index("Warehouse Associate")
    assert rr_header_at < rr_posting_at < ats_header_at < ats_posting_at


def test_tier_renders_even_when_source_is_absent():
    """Fix 5 (unrelated to the ATS/RR split): the tier segment used to live
    nested inside the `.source` check, so a posting with a tier but no source
    rendered no bracket at all."""
    tier_only = {**ATS_POSTING, "source": "", "tier": "api"}
    out = _run(ATS_EXPR, {"feedPostings": [tier_only]})
    assert "[api]" in out
    assert "null" not in out
