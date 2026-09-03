"""Tests for applications/sorting.py, mirroring web/src/applications/sorting.test.ts."""

import pytest
from datetime import date
import applications as app_store
from applications.sorting import (
    sort_applications,
    status_rank,
    DEFAULT_SORT,
    DEFAULT_DIRECTION,
    STATUS_ORDER,
)


@pytest.fixture
def mock_app():
    """Factory for creating mock Application objects."""
    def _make(**kwargs):
        defaults = {
            "id": "x",
            "company": "",
            "website": "",
            "application_url": "",
            "submitted": False,
            "submission_type": "",
            "reached_out": False,
            "to_who": "",
            "response_received": False,
            "method": "",
            "posting": "",
            "application_date": "",
            "status": "",
            "notes": "",
            "cv_document": None,
            "cover_letter_document": None,
            "fields_submitted": [],
        }
        defaults.update(kwargs)
        return type("Application", (), defaults)()
    return _make


class TestSorting:
    """Application sorting tests."""

    def test_company_sorts_case_insensitively(self, mock_app):
        """Company column: case-insensitive sorting."""
        a = mock_app(company="acme")
        b = mock_app(company="Beta")
        
        sorted_asc = sort_applications([b, a], sort="company", direction="asc")
        assert sorted_asc[0].company == "acme"
        assert sorted_asc[1].company == "Beta"
        
        sorted_desc = sort_applications([a, b], sort="company", direction="desc")
        assert sorted_desc[0].company == "Beta"
        assert sorted_desc[1].company == "acme"

    def test_date_sorts_chronologically(self, mock_app):
        """Date column: sorts chronologically, respects direction."""
        early = mock_app(application_date="2026-01-02")
        late = mock_app(application_date="2026-03-01")
        
        sorted_asc = sort_applications([late, early], sort="date", direction="asc")
        assert sorted_asc[0].application_date == "2026-01-02"
        assert sorted_asc[1].application_date == "2026-03-01"
        
        sorted_desc = sort_applications([early, late], sort="date", direction="desc")
        assert sorted_desc[0].application_date == "2026-03-01"
        assert sorted_desc[1].application_date == "2026-01-02"

    def test_undated_rows_stay_at_bottom_both_directions(self, mock_app):
        """Date blanks stay at the bottom in BOTH asc and desc (special handling)."""
        dated = mock_app(application_date="2026-01-02")
        undated = mock_app(application_date="")
        
        sorted_asc = sort_applications([dated, undated], sort="date", direction="asc")
        assert sorted_asc[0].application_date == "2026-01-02"
        assert sorted_asc[1].application_date == ""
        
        sorted_desc = sort_applications([dated, undated], sort="date", direction="desc")
        assert sorted_desc[0].application_date == "2026-01-02"
        assert sorted_desc[1].application_date == ""

    def test_table_defaults_newest_first(self, mock_app):
        """Table defaults to Date column, desc direction (newest first)."""
        assert DEFAULT_SORT == "date"
        assert DEFAULT_DIRECTION == "desc"
        
        early = mock_app(application_date="2026-01-02")
        late = mock_app(application_date="2026-03-01")
        
        sorted_default = sort_applications([early, late])
        assert sorted_default[0].application_date == "2026-03-01"

    def test_website_compares_by_host(self, mock_app):
        """Website column sorts by extracted URL host."""
        a = mock_app(website="https://alpha.example/page")
        b = mock_app(website="https://beta.example/page")
        
        sorted_asc = sort_applications([b, a], sort="website", direction="asc")
        assert sorted_asc[0].website == "https://alpha.example/page"
        assert sorted_asc[1].website == "https://beta.example/page"

    def test_boolean_sorts_yes_first_ascending(self, mock_app):
        """Boolean columns: yes (True) first in ascending order."""
        yes = mock_app(submitted=True)
        no = mock_app(submitted=False)
        
        sorted_asc = sort_applications([no, yes], sort="submitted", direction="asc")
        assert sorted_asc[0].submitted is True
        assert sorted_asc[1].submitted is False
        
        # Descending flips it
        sorted_desc = sort_applications([yes, no], sort="submitted", direction="desc")
        assert sorted_desc[0].submitted is False
        assert sorted_desc[1].submitted is True

    def test_status_uses_status_rank_order(self, mock_app):
        """Status column sorts by STATUS_ORDER rank."""
        offer = mock_app(status="Offer")
        rejected = mock_app(status="Rejected")
        applied = mock_app(status="Applied")
        
        sorted_asc = sort_applications([rejected, offer, applied], sort="status", direction="asc")
        assert sorted_asc[0].status == "Offer"
        assert sorted_asc[1].status == "Applied"
        assert sorted_asc[2].status == "Rejected"

    def test_status_rank_unlisted_statuses_at_bottom(self, mock_app):
        """Unlisted statuses sort to the bottom."""
        offer = mock_app(status="Offer")
        unknown = mock_app(status="Unknown")
        
        sorted_asc = sort_applications([unknown, offer], sort="status", direction="asc")
        assert sorted_asc[0].status == "Offer"
        assert sorted_asc[1].status == "Unknown"

    def test_documents_sorts_by_presence(self, mock_app):
        """Documents column sorts by presence of cv_document or cover_letter_document."""
        has_doc = mock_app(cv_document={"source": "", "pdfUrl": None, "docxUrl": None, "updatedAt": ""})
        no_doc = mock_app(cv_document=None, cover_letter_document=None)
        
        sorted_asc = sort_applications([no_doc, has_doc], sort="documents", direction="asc")
        assert sorted_asc[0].cv_document is not None
        assert sorted_asc[1].cv_document is None

    def test_filled_form_sorts_by_presence(self, mock_app):
        """Filled form column sorts by presence of fields_submitted."""
        has_form = mock_app(fields_submitted=[{"label": "Full name", "value": "Jane Doe", "source": "profile"}])
        no_form = mock_app(fields_submitted=[])
        
        sorted_asc = sort_applications([no_form, has_form], sort="filledForm", direction="asc")
        assert len(sorted_asc[0].fields_submitted) > 0
        assert len(sorted_asc[1].fields_submitted) == 0

    def test_url_sorts_by_presence(self, mock_app):
        """URL column sorts by presence."""
        with_url = mock_app(application_url="https://example.com/apply")
        without_url = mock_app(application_url="")
        
        sorted_asc = sort_applications([without_url, with_url], sort="url", direction="asc")
        assert sorted_asc[0].application_url != ""
        assert sorted_asc[1].application_url == ""

    def test_posting_sorts_by_presence(self, mock_app):
        """Posting column sorts by presence."""
        with_posting = mock_app(posting="Job description here")
        without_posting = mock_app(posting="")
        
        sorted_asc = sort_applications([without_posting, with_posting], sort="posting", direction="asc")
        assert sorted_asc[0].posting != ""
        assert sorted_asc[1].posting == ""

    def test_unknown_sort_key_raises_error(self, mock_app):
        """Unknown sort key raises ValueError."""
        app = mock_app()
        with pytest.raises(ValueError, match="Unknown sort key"):
            sort_applications([app], sort="invalid_key", direction="asc")

    def test_invalid_direction_raises_error(self, mock_app):
        """Invalid direction raises ValueError."""
        app = mock_app()
        with pytest.raises(ValueError, match="Invalid sort direction"):
            sort_applications([app], sort="date", direction="invalid")

    def test_all_sort_keys_are_valid(self, mock_app):
        """All expected sort keys work without raising."""
        app = mock_app()
        expected_keys = [
            "company", "date", "website", "url", "submitted", "type", "status",
            "reachedOut", "toWho", "response", "method", "notes", "posting", 
            "documents", "filledForm"
        ]
        for key in expected_keys:
            result = sort_applications([app], sort=key, direction="asc")
            assert result == [app]

    def test_status_rank_function(self):
        """status_rank returns expected ranks."""
        assert status_rank("Offer") == 0
        assert status_rank("Interviewing") == 1
        assert status_rank("Rejected") == 5
        assert status_rank("Unknown") == len(STATUS_ORDER)
