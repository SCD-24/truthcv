"""One posting, one screening record.

The bug these pin down: the operator rejected a posting in the approval queue,
and the agent re-screened the same URL on the next run and queued it again —
ten records for one Grafana Labs job, every one of them rejected by hand. The
operator's decision lives in `approval` on a single record, so a second record
for the same posting is a second decision they never made.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agenttools import tools_ledger
from api.main import app
from screening import store
from screening.url import posting_dedupe_key

client = TestClient(app)


def _fields(url: str, **over) -> dict:
    base = {
        "company": "Grafana Labs",
        "role": "Senior Backend Engineer",
        "url": url,
        "verdict": "rejected",
    }
    base.update(over)
    return base


class TestPostingDedupeKey:
    """What counts as the same posting."""

    @pytest.mark.parametrize(
        "a,b",
        [
            # Scheme and host case are cosmetic.
            ("https://Job-Boards.Greenhouse.io/x/jobs/1", "https://job-boards.greenhouse.io/x/jobs/1"),
            # A trailing slash is cosmetic.
            ("https://x.example.com/j/abc/", "https://x.example.com/j/abc"),
            # The board's own apply page is the same posting.
            ("https://x.example.com/j/abc/application", "https://x.example.com/j/abc"),
            ("https://x.example.com/j/abc/apply", "https://x.example.com/j/abc"),
            # Fragments and tracking params name the campaign, not the job.
            ("https://x.example.com/j/abc#top", "https://x.example.com/j/abc"),
            ("https://x.example.com/j/abc?utm_source=alert", "https://x.example.com/j/abc"),
            ("https://x.example.com/j/abc?gh_src=board", "https://x.example.com/j/abc"),
            # Parameter order is not identity.
            ("https://x.example.com/j?a=1&b=2", "https://x.example.com/j?b=2&a=1"),
        ],
    )
    def test_the_same_posting_yields_one_key(self, a, b):
        assert posting_dedupe_key(a) == posting_dedupe_key(b)

    def test_a_job_id_in_the_query_is_not_dropped(self):
        """The regression `normalize_application_url` would have caused.

        Several boards put the job id only in the query string, so discarding
        the query would collapse every posting on that board into one key and
        silently swallow real jobs.
        """
        one = posting_dedupe_key("https://upsun.com/job/?gh_jid=8656285002")
        two = posting_dedupe_key("https://upsun.com/job/?gh_jid=9999999999")
        assert one != two

    @pytest.mark.parametrize("blank", ["", "   ", "not a url"])
    def test_an_unresolvable_url_has_no_key(self, blank):
        assert posting_dedupe_key(blank) == ""


class TestStoreRefusesASecondRecord:
    def test_a_second_screening_for_one_posting_is_not_written(self):
        url = "https://job-boards.greenhouse.io/grafanalabs/jobs/6117334004"
        first, created = store.create_or_get(_fields(url))
        assert created is True

        again, created_again = store.create_or_get(
            _fields(url, verdict="passed", posting_text="x" * 400)
        )
        assert created_again is False
        assert again.id == first.id
        assert len(store.load_all()) == 1

    def test_the_stored_record_is_returned_untouched(self):
        """The second call must not overwrite the first verdict.

        The first screening is the one the operator's decision is attached to;
        letting a later run rewrite it would change the record under them.
        """
        url = "https://x.example.com/j/abc"
        first, _ = store.create_or_get(_fields(url, reason="under-levelled"))
        store.set_approval(first.id, "rejected")

        again, created = store.create_or_get(
            _fields(url, verdict="passed", reason="looks good", posting_text="x" * 400)
        )
        assert created is False
        assert again.verdict == "rejected"
        assert again.reason == "under-levelled"
        assert again.approval == "rejected"

    def test_a_rejected_posting_does_not_return_to_the_queue(self):
        """The reported bug, end to end at the store."""
        url = "https://job-boards.greenhouse.io/grafanalabs/jobs/6117334004"
        first, _ = store.create_or_get(_fields(url, verdict="deferred"))
        store.set_approval(first.id, "rejected")

        store.create_or_get(_fields(url, verdict="deferred"))

        pending = [s for s in store.load_all() if s.approval == "pending"]
        assert pending == []

    def test_a_cosmetically_different_url_is_the_same_posting(self):
        url = "https://job-boards.greenhouse.io/grafanalabs/jobs/6117334004"
        store.create_or_get(_fields(url))
        _, created = store.create_or_get(
            _fields(url + "/apply?utm_source=alert")
        )
        assert created is False
        assert len(store.load_all()) == 1

    def test_a_different_posting_still_creates_a_record(self):
        store.create_or_get(_fields("https://x.example.com/j/abc"))
        _, created = store.create_or_get(_fields("https://x.example.com/j/def"))
        assert created is True
        assert len(store.load_all()) == 2

    def test_records_with_no_resolvable_url_never_match_each_other(self):
        """Two records the store cannot resolve to a posting are not thereby
        the same posting — the legacy importer writes such rows."""
        store.create_or_get(_fields(""))
        store.create_or_get(_fields(""))
        assert len(store.load_all()) == 2

    def test_deleting_the_record_frees_the_posting(self):
        """The escape hatch: a genuinely re-listed job can be screened again."""
        url = "https://x.example.com/j/abc"
        first, _ = store.create_or_get(_fields(url))
        assert store.delete(first.id) is True
        _, created = store.create_or_get(_fields(url))
        assert created is True

    def test_find_by_url_matches_on_posting_identity(self):
        url = "https://x.example.com/j/abc"
        first, _ = store.create_or_get(_fields(url))
        assert store.find_by_url(url + "/apply").id == first.id
        assert store.find_by_url("https://x.example.com/j/other") is None
        assert store.find_by_url("") is None

    def test_create_still_returns_the_record(self):
        """`create` keeps its single-value contract for existing callers."""
        url = "https://x.example.com/j/abc"
        assert store.create(_fields(url)).url == url
        assert store.create(_fields(url)).url == url
        assert len(store.load_all()) == 1


class TestAgentToolReportsTheDuplicate:
    def test_record_screening_reports_created_false_and_persists_nothing(self):
        url = "https://job-boards.greenhouse.io/grafanalabs/jobs/6117334004"
        first = tools_ledger.record_screening(
            url=url,
            role="Senior Backend Engineer",
            company="Grafana Labs",
            verdict="rejected",
        )
        assert first["created"] is True

        second = tools_ledger.record_screening(
            url=url,
            role="Senior Backend Engineer",
            company="Grafana Labs",
            verdict="rejected",
        )
        assert second["created"] is False
        assert second["id"] == first["id"]
        assert len(store.load_all()) == 1


class TestApiRefusesTheDuplicate:
    def test_post_screenings_409s_on_a_posting_already_screened(self):
        body = {
            "company": "Grafana Labs",
            "role": "Senior Backend Engineer",
            "url": "https://job-boards.greenhouse.io/grafanalabs/jobs/6117334004",
            "verdict": "rejected",
        }
        assert client.post("/api/screenings", json=body).status_code == 201

        conflict = client.post("/api/screenings", json=body)
        assert conflict.status_code == 409
        assert "already been screened" in conflict.json()["detail"]
        assert len(store.load_all()) == 1


class TestUnreadPlaceholdersAreSuperseded:
    """A posting the agent could not read at all is not a judgement.

    `not_found` and `expired` records never queue (QUEUEING_BLOCKERS), so the
    operator never sees them — if one of those suppressed re-screening
    forever, a board that 404s for an afternoon would blacklist a live posting
    invisibly, with no record for anyone to delete.
    """

    URL = "https://x.example.com/j/abc"

    def _blocked(self, blocker: str):
        return store.create_or_get(
            {
                "company": "Acme",
                "role": "Backend Engineer",
                "url": self.URL,
                "verdict": "",
                "screening_blocker": blocker,
            }
        )

    @pytest.mark.parametrize("blocker", ["not_found", "expired"])
    def test_a_later_real_screening_replaces_it_in_place(self, blocker):
        first, _ = self._blocked(blocker)

        again, created = store.create_or_get(
            _fields(self.URL, company="Acme", verdict="deferred")
        )

        assert created is False
        assert again.id == first.id
        assert again.created_at == first.created_at
        assert again.verdict == "deferred"
        assert again.screening_blocker == ""
        assert again.approval == "pending"
        assert len(store.load_all()) == 1

    def test_the_superseding_record_keeps_the_original_run(self):
        """Nothing else records that this posting was first seen by that run."""
        store.create_or_get(
            {
                "company": "Acme",
                "role": "Backend Engineer",
                "url": self.URL,
                "verdict": "",
                "screening_blocker": "not_found",
                "run_id": "run-1",
            }
        )
        again, _ = store.create_or_get(_fields(self.URL, company="Acme"))
        assert again.run_id == "run-1"

    @pytest.mark.parametrize("blocker", ["login_required", "unreadable"])
    def test_a_queued_blocker_is_a_pending_decision_and_is_not_replaced(self, blocker):
        """These DO reach the operator, so overwriting one would change a
        record they are currently looking at."""
        first, _ = self._blocked(blocker)
        assert first.approval == "pending"

        again, created = store.create_or_get(
            _fields(self.URL, company="Acme", verdict="deferred")
        )
        assert created is False
        assert again.screening_blocker == blocker
        assert again.verdict == ""

    def test_an_unread_record_the_operator_decided_on_is_not_replaced(self):
        """Once they have ruled on it, it is their decision, not a placeholder."""
        first, _ = self._blocked("not_found")
        store.set_approval(first.id, "rejected")

        again, created = store.create_or_get(
            _fields(self.URL, company="Acme", verdict="passed", posting_text="x" * 400)
        )
        assert created is False
        assert again.approval == "rejected"
        assert again.verdict == ""
