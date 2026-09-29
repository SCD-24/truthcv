import importlib.util
from pathlib import Path

from screening import store as screening_store

_PATH = Path(__file__).resolve().parent.parent / "scripts" / "purge_non_posting_screenings.py"
_spec = importlib.util.spec_from_file_location("purge_non_posting_screenings", _PATH)
purge = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(purge)

SPAM = "https://ch.linkedin.com/jobs/%E5%B0%A4-stellen"
GOOD = "https://www.linkedin.com/jobs/view/123"


def _add(url, approval="", verdict="passed"):
    rec = screening_store.create_or_get(
        {"company": "Acme", "role": "E", "url": url, "verdict": verdict}
    )
    rec = rec[0] if isinstance(rec, tuple) else rec
    if approval:
        screening_store.set_approval(rec.id, approval)
    return rec


def _seed():
    _add(SPAM + "?a=1", verdict="passed")
    _add(SPAM + "?a=2", verdict="rejected")
    _add(SPAM + "?a=3", approval="approved")
    _add(GOOD)


def test_dry_run_deletes_nothing(data_dir):
    _seed()
    before = len(screening_store.load_all())
    assert purge.main([]) == 0
    assert len(screening_store.load_all()) == before


def test_apply_removes_spam_keeps_approved_and_real(data_dir):
    _seed()
    assert purge.main(["--apply"]) == 0
    urls = sorted(s.url for s in screening_store.load_all())
    assert urls == sorted([SPAM + "?a=3", GOOD])
