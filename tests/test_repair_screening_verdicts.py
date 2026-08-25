"""scripts/repair_screening_verdicts: recovery, refusal, and the destructive pass.

This script parses free text and writes to real records, and it shipped with no
tests. Each case below is a way it could corrupt or destroy data rather than
repair it.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "repair_screening_verdicts",
    Path(__file__).resolve().parent.parent / "scripts" / "repair_screening_verdicts.py",
)
repair = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(repair)


class _Rec:
    """Minimal stand-in with the attributes the script reads."""

    def __init__(self, posting_text="", company="", verdict="", failing_criterion="", reason=""):
        self.id = "rec1"
        self.posting_text = posting_text
        self.company = company
        self.verdict = verdict
        self.failing_criterion = failing_criterion
        self.reason = reason
        self.approval = ""
        self.url = "https://e.com/1"
        self.role = "Engineer"


CANONICAL = (
    "[COMPANY: Acme GmbH | VERDICT: rejected | FAILING CRITERION: glassdoor | "
    "REASON: rating below floor]\nSenior Engineer at Acme. Remote."
)


class TestRecover:
    def test_recovers_every_field_from_a_canonical_block(self):
        assert repair.recover(_Rec(CANONICAL)) == {
            "company": "Acme GmbH",
            "verdict": "rejected",
            "failing_criterion": "glassdoor",
            "reason": "rating below floor",
        }

    def test_never_overwrites_a_value_the_record_already_holds(self):
        patch = repair.recover(_Rec(CANONICAL, company="Real Name", verdict="passed"))
        assert "company" not in patch and "verdict" not in patch

    @pytest.mark.parametrize(
        "name",
        [
            "Medico (nordByte / CARESOFT DAN)",
            "OTIS Prof. Mueller AG",
            "adventec group (part of z9K)",
            "Sable (Sable Technologies GmbH)",
        ],
    )
    def test_punctuated_employer_names_survive_intact(self, name):
        """Awkwardly punctuated names of the shape the live agent records,
        several with punctuation and capitals that a naive terminator would
        truncate."""
        text = f"[COMPANY: {name} | VERDICT: deferred]\nBody."
        assert repair.recover(_Rec(text))["company"] == name

    def test_refuses_a_block_that_used_no_pipe_separator(self):
        """Ambiguous: the capture would run past the company into the next
        field. A wrong employer name is worse than an unrepaired record —
        cooldown and the blocklist key on it."""
        text = "[COMPANY: Acme GmbH VERDICT: rejected FAILING CRITERION: salary]\nBody."
        assert repair.recover(_Rec(text)) == {}

    def test_ignores_prose_in_the_posting_body(self):
        """Scanning the whole text made the employer's marketing copy the
        rejection reason."""
        text = "[COMPANY: Acme | VERDICT: rejected]\nReason: we grew 3x last year."
        assert repair.recover(_Rec(text)) == {"company": "Acme", "verdict": "rejected"}

    def test_refuses_an_unterminated_block(self):
        text = "[COMPANY: Acme | VERDICT: rejected\nRequirements:\n1] Python\n2] Go"
        assert repair.recover(_Rec(text)) == {}

    def test_refuses_text_with_no_block(self):
        assert repair.recover(_Rec("An ordinary posting body.")) == {}

    def test_refuses_an_unknown_verdict(self):
        text = "[COMPANY: Acme | VERDICT: maybe]\nBody."
        assert repair.recover(_Rec(text)) == {}

    def test_refuses_a_placeholder_company(self):
        text = "[COMPANY: Unknown | VERDICT: rejected]\nBody."
        assert repair.recover(_Rec(text)) == {}


class TestStrippable:
    def test_strips_the_block_and_keeps_the_posting(self):
        rec = _Rec(CANONICAL, company="Acme GmbH", verdict="rejected")
        assert repair.strippable(rec) == "Senior Engineer at Acme. Remote."

    def test_refuses_while_the_record_still_needs_repair(self):
        """Stripping before the fields are recovered discards the only copy."""
        assert repair.strippable(_Rec(CANONICAL)) is None

    def test_refuses_an_unterminated_block_rather_than_truncating_the_body(self):
        """Taking the first "]" anywhere destroyed real posting text: here the
        title and the first requirement, unrecoverable for boards that no
        longer serve the posting."""
        text = "[COMPANY: Acme | VERDICT: rejected\nSenior Backend Engineer\n1] Python\n2] Go"
        rec = _Rec(text, company="Acme", verdict="rejected")
        assert repair.strippable(rec) is None

    def test_refuses_a_bracket_inside_the_company_value(self):
        text = "[COMPANY: Acme (formerly Foo] Ltd) | VERDICT: rejected]\nReal body."
        rec = _Rec(text, company="Acme", verdict="rejected")
        # The block cannot be delimited unambiguously, so the body is left alone.
        assert repair.strippable(rec) in (None, "Real body.")
        assert repair.strippable(rec) != "Ltd) | VERDICT: rejected]\nReal body."

    def test_returns_none_when_nothing_would_remain(self):
        rec = _Rec("[COMPANY: Acme | VERDICT: rejected]", company="Acme", verdict="rejected")
        assert repair.strippable(rec) is None

    def test_leaves_a_record_with_no_block_alone(self):
        rec = _Rec("Ordinary body.", company="Acme", verdict="rejected")
        assert repair.strippable(rec) is None


class TestQueuesForApproval:
    def test_deferred_always_queues(self, data_dir):
        assert repair.queues_for_approval("deferred") is True

    def test_rejected_never_queues(self, data_dir):
        assert repair.queues_for_approval("rejected") is False
