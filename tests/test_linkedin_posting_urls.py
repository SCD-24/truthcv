import pytest

from screening import store as screening_store
from screening.url import is_posting_url, linkedin_job_id, posting_dedupe_key

CANON = "https://www.linkedin.com/jobs/view/123456"
SPAM = [
    "https://ie.linkedin.com/jobs/%E6%B5%99%E6%B1%9F-jobs?position=1&pageNum=0",
    "https://ch.linkedin.com/jobs/%E5%B0%A4-stellen",
]


def test_variants_collapse():
    for url in (
        "https://uk.linkedin.com/jobs/view/123456",
        "https://www.linkedin.com/jobs/view/some-title-at-acme-123456/",
        "https://ch.linkedin.com/jobs/view/engineer-123456?trk=x",
    ):
        assert posting_dedupe_key(url) == CANON


def test_different_ids_distinct():
    a = posting_dedupe_key("https://www.linkedin.com/jobs/view/1")
    b = posting_dedupe_key("https://www.linkedin.com/jobs/view/2")
    assert a != b


@pytest.mark.parametrize("url", SPAM)
def test_spam_not_posting(url):
    assert linkedin_job_id(url) is None
    assert is_posting_url(url) is False


def test_empty_slug_is_not_posting():
    url = "https://ie.linkedin.com/jobs/view/-123"
    assert linkedin_job_id(url) is None
    assert is_posting_url(url) is False


def test_non_linkedin_unchanged():
    url = "https://example.com/jobs/2/?utm_x=1"
    assert is_posting_url(url) is True
    assert posting_dedupe_key(url) == "https://example.com/jobs/2"
    assert is_posting_url("not a url") is True


def test_record_screening_rejects_spam(data_dir):
    from agenttools.tools_ledger import record_screening

    with pytest.raises(ValueError):
        record_screening(url=SPAM[0], company="Acme", role="Engineer", verdict="rejected")
    assert screening_store.load_all() == []


def test_record_screening_accepts_job_view(data_dir):
    from agenttools.tools_ledger import record_screening

    record_screening(
        url="https://uk.linkedin.com/jobs/view/123456",
        company="Acme",
        role="Engineer",
        verdict="rejected",
    )
    assert len(screening_store.load_all()) == 1
