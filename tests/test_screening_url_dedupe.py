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


class TestScreenedDedupeKeys:
    """Feed filtering support: which postings the agent has already screened."""

    def test_a_normal_screenings_key_is_included(self):
        url = "https://x.example.com/j/abc"
        store.create_or_get(_fields(url))
        assert posting_dedupe_key(url) in store.screened_dedupe_keys()

    def test_an_unread_placeholder_is_excluded(self):
        """It may be superseded by a real screening, so the agent must still
        see it in the feed rather than have it look already screened."""
        store.create_or_get(
            {
                "company": "Acme",
                "role": "Backend Engineer",
                "url": "https://x.example.com/j/abc",
                "verdict": "",
                "screening_blocker": "not_found",
            }
        )
        assert store.screened_dedupe_keys() == set()

    def test_a_blank_url_contributes_no_key(self):
        store.create_or_get(_fields(""))
        assert store.screened_dedupe_keys() == set()

    def test_url_variants_sharing_a_dedupe_key_match(self):
        url = "https://job-boards.greenhouse.io/grafanalabs/jobs/6117334004"
        store.create_or_get(_fields(url))
        variant_key = posting_dedupe_key(url + "/apply?utm_source=alert")
        assert variant_key in store.screened_dedupe_keys()


class TestPerProfileRecords:
    URL = "https://x.example.com/j/abc"

    def _rec(self, profile, verdict="rejected"):
        return store.create_or_get(_fields(self.URL, profile=profile, verdict=verdict))

    def test_rejected_for_a_then_recorded_for_b(self):
        assert self._rec("A")[1] is True
        assert self._rec("B")[1] is True
        assert len(store.load_all()) == 2

    def test_same_profile_twice_is_a_duplicate(self):
        self._rec("A")
        assert self._rec("A")[1] is False

    def test_url_wide_record_blocks_profiles(self):
        first, _ = self._rec("")
        assert self._rec("A") == (first, False)
        assert self._rec("B")[1] is False

    def test_second_queueing_record_returns_the_first(self):
        first, _ = self._rec("A", "passed")
        again, created = self._rec("B", "passed")
        assert created is False
        assert again.id == first.id

    def test_deferred_then_passed_is_blocked(self):
        self._rec("A", "deferred")
        assert self._rec("B", "passed")[1] is False

    def test_placeholder_superseded_by_profiled_screening(self):
        first, _ = store.create_or_get(
            {"company": "Acme", "role": "R", "url": self.URL, "verdict": "",
             "screening_blocker": "not_found"}
        )
        again, created = self._rec("A")
        assert created is True
        assert again.id == first.id
        assert len(store.load_all()) == 1

    def test_screened_keys_with_enabled_profiles(self):
        key = posting_dedupe_key(self.URL)
        self._rec("A")
        assert key not in store.screened_dedupe_keys(["A", "B"])
        assert key in store.screened_dedupe_keys()
        self._rec("B")
        assert key in store.screened_dedupe_keys(["A", "B"])

    def test_a_pass_under_one_profile_covers_all(self):
        self._rec("A", "passed")
        assert posting_dedupe_key(self.URL) in store.screened_dedupe_keys(["A", "B"])


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

    `not_found`, `expired` and `unreadable` records never queue (QUEUEING_BLOCKERS), so the
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

    @pytest.mark.parametrize("blocker", ["not_found", "expired", "unreadable"])
    def test_a_later_real_screening_replaces_it_in_place(self, blocker):
        first, _ = self._blocked(blocker)

        again, created = store.create_or_get(
            _fields(self.URL, company="Acme", verdict="deferred")
        )

        assert created is True
        assert again.id == first.id
        assert again.created_at == first.created_at
        assert again.verdict == "deferred"
        assert again.screening_blocker == ""
        assert again.approval == "pending"
        assert len(store.load_all()) == 1

    def test_agent_tool_reports_created_true_when_a_pass_supersedes(self):
        import agentconfig.store as config_store

        cfg = config_store.load()
        cfg.profiles = [config_store.JobProfile(name="default", enabled=True)]
        config_store.save(cfg)
        self._blocked("unreadable")
        text = "Backend Engineer at Acme. Remote. " + "Build reliable services. " * 20
        got = tools_ledger.record_screening(
            url=self.URL,
            role="Backend Engineer",
            company="Acme",
            verdict="passed",
            posting_text=text,
            profile="default",
            remote_arrangement="remote",
        )
        assert got["created"] is True

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

    @pytest.mark.parametrize("blocker", ["login_required"])
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


class TestProfileCaseAndApprovalConflict:
    """Profile names compare case-insensitively; one approval per posting."""

    URL = "https://x.example.com/j/case1"

    def test_profile_case_is_ignored_when_blocking(self):
        store.create_or_get(_fields(self.URL, profile="backend"))
        _, created = store.create_or_get(_fields(self.URL, profile="Backend"))
        assert created is False

    def test_screened_keys_fold_case_and_whitespace(self):
        store.create_or_get(_fields(self.URL, profile="backend "))
        assert posting_dedupe_key(self.URL) in store.screened_dedupe_keys(["Backend"])

    def test_second_approval_conflicts_until_first_is_rejected(self):
        a, _ = store.create_or_get(_fields(self.URL, profile="A"))
        b, _ = store.create_or_get(_fields(self.URL, profile="B"))
        assert store.set_approval(a.id, "approved").approval == "approved"
        with pytest.raises(store.ApprovalConflict) as exc:
            store.set_approval(b.id, "approved")
        assert a.id in str(exc.value)
        store.set_approval(a.id, "rejected")
        assert store.set_approval(b.id, "approved").approval == "approved"


class TestActiveRecordInvariant:
    """A posting has at most one pending/approved/applied record."""

    URL = "https://x.example.com/j/active1"

    def _pair(self):
        a, _ = store.create_or_get(_fields(self.URL, profile="A"))
        b, _ = store.create_or_get(_fields(self.URL, profile="B"))
        return a, b

    def test_new_deferred_is_blocked_by_an_approved_record(self):
        a, _ = store.create_or_get(_fields(self.URL, profile="A"))
        store.set_approval(a.id, "approved")
        got, created = store.create_or_get(
            _fields(self.URL, profile="B", verdict="deferred")
        )
        assert (got.id, created) == (a.id, False)

    def test_approving_conflicts_with_an_applied_record(self):
        a, b = self._pair()
        store.set_approval(a.id, "applied")
        with pytest.raises(store.ApprovalConflict):
            store.set_approval(b.id, "approved")

    def test_claim_for_apply_refused_when_another_record_applied(self):
        a, b = self._pair()
        store.set_approval(a.id, "applied")
        assert store.claim_for_apply(b.id) is None
        assert store._apply_refusal(store.get(b.id), store.load_all()) == "already_applied"

    def test_screened_keys_count_an_approved_rejected_record(self):
        a, _ = store.create_or_get(_fields(self.URL, profile="A"))
        store.set_approval(a.id, "approved")
        assert posting_dedupe_key(self.URL) in store.screened_dedupe_keys(["A", "B"])
