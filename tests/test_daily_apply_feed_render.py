"""daily-apply.sh renders API-backed feed postings into the run prompt.

The jq expressions are EXTRACTED FROM THE SCRIPT AND RUN, not grepped for. The
failure this guards against is a field-name mismatch: jobfeeds emits snake_case
dataclass fields, but what reaches the script is the API's camelCase wire shape,
and a wrong key makes jq render an empty string rather than fail — so the
postings would silently vanish from the prompt with nothing to notice.
"""

from __future__ import annotations

import json
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


FEED_EXPR = _expression(".feedPostings[]?")
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
}


def test_a_posting_renders_its_profile_title_company_salary_and_url():
    out = _run(FEED_EXPR, {"feedPostings": [POSTING]})
    assert "[Senior Python]" in out
    assert "Senior Platform Engineer" in out
    assert "Acme" in out
    assert "$120k-$150k" in out
    assert "https://acme.example/jobs/1" in out


def test_a_posting_missing_company_and_salary_still_renders_title_and_url():
    """Those two are optional on the wire. Rendering "null" or dropping the
    posting entirely are both worse than an unadorned line."""
    bare = {**POSTING, "company": "", "salaryRange": ""}
    out = _run(FEED_EXPR, {"feedPostings": [bare]})
    assert "null" not in out
    assert "Senior Platform Engineer" in out
    assert "https://acme.example/jobs/1" in out


def test_absent_company_and_salary_keys_do_not_break_the_render():
    """A field the API stopped sending must not abort the whole prompt build —
    the script runs under `set -e`, so a jq error would end the run."""
    stripped = {k: v for k, v in POSTING.items() if k not in ("company", "salaryRange")}
    out = _run(FEED_EXPR, {"feedPostings": [stripped]})
    assert "https://acme.example/jobs/1" in out


def test_an_empty_feed_renders_nothing():
    assert _run(FEED_EXPR, {"feedPostings": []}).strip() == ""
    assert _run(FEED_EXPR, {}).strip() == ""


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
