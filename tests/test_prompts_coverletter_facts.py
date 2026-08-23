"""Test cover_letter_facts_block output with profile and answers."""

from truth.answers import Answers
from truth.model import Bullet, Experience, Link, Profile, Skill, Truth
from prompts.coverletter import cover_letter_facts_block

EM_DASH = "\u2014"
EN_DASH = "\u2013"
CURLY = "\u2018\u2019\u201c\u201d"  # ' ' " "


def _truth() -> Truth:
    """Build a Truth with profile, experience, skills for testing."""
    return Truth(
        profile=Profile(
            name="Alice Developer",
            email="alice@example.com",
            phone="+1 555-0123",
            location="San Francisco, CA",
            links=[Link(label="LinkedIn", url="https://linkedin.com/in/alice")],
            summary="Experienced software engineer with a focus on backend systems.",
        ),
        experiences=[
            Experience(
                id="e1",
                role="Senior Engineer",
                company="TechCorp",
                start="2020",
                end="2023",
                source="linkedin-pdf",
                bullets=[Bullet(id="b1", value="Built distributed systems", source="linkedin-pdf")],
            )
        ],
        skills=[Skill(id="s1", value="Python", source="linkedin-pdf")],
    )


def _answers() -> Answers:
    """Build an Answers with several non-blank fields for testing."""
    return Answers(
        phone="+1 555-0123",
        work_authorisation="Yes",
        notice_period="2 weeks",
        location_preference="San Francisco",
        name="Alice Developer",
        email="alice@example.com",
        linkedin="https://linkedin.com/in/alice",
        github="",  # Blank, should be skipped
        website="",  # Blank, should be skipped
        requires_sponsorship="No",
        authorized_non_german_country="USA",
        languages="English, Spanish",
        highest_relevant_degree="BS Computer Science",
        other_degree="",  # Blank, should be skipped
        cs_degree="Yes",
        gpa="3.8",
        gender="",  # Blank, should be skipped
        years_of_experience="5",
        current_role="Staff Engineer",
        how_did_you_hear="Recruiter",
        canonical_cv_asset_id="cv-12345",  # Should NEVER appear in output
    )


def test_facts_block_backwards_compatible():
    """Single argument call produces same output as before (no profile/answers)."""
    truth = Truth(
        experiences=[
            Experience(
                id="e1",
                role="Engineer",
                company="Acme",
                start="2020",
                end="2023",
                source="linkedin-pdf",
                bullets=[Bullet(id="b1", value="Built X", source="linkedin-pdf")],
            )
        ],
        skills=[Skill(id="s1", value="Python", source="linkedin-pdf")],
    )
    output = cover_letter_facts_block(truth)
    # Should not contain profile section
    assert "Candidate profile:" not in output
    # Should contain experience and skills
    assert "Engineer at Acme (2020 to 2023):" in output
    assert "Skills: Python" in output


def test_facts_block_profile_summary_included():
    """With answers, the profile summary is included."""
    truth = _truth()
    answers = _answers()
    output = cover_letter_facts_block(truth, answers)
    assert "Alice Developer" in output
    assert "San Francisco, CA" in output
    assert "Experienced software engineer with a focus on backend systems." in output
    assert "https://linkedin.com/in/alice" in output


def test_facts_block_answer_values_included():
    """Non-blank answer values are included in the output."""
    truth = _truth()
    answers = _answers()
    output = cover_letter_facts_block(truth, answers)
    # Check non-blank answers appear
    assert "Current role: Staff Engineer" in output
    assert "Years of experience: 5" in output
    assert "Languages: English, Spanish" in output
    assert "GPA: 3.8" in output
    assert "Work authorisation: Yes" in output


def test_facts_block_canonical_cv_asset_id_excluded():
    """canonical_cv_asset_id value never appears in output."""
    truth = _truth()
    answers = _answers()
    output = cover_letter_facts_block(truth, answers)
    assert "cv-12345" not in output
    assert "canonical_cv_asset_id" not in output.lower()


def test_facts_block_blank_answers_skipped():
    """Blank answer fields produce no output lines."""
    truth = _truth()
    answers = _answers()
    output = cover_letter_facts_block(truth, answers)
    # github and website are blank, should not appear with dangling labels
    assert "GitHub:" not in output
    assert "Website:" not in output
    assert "Other degree:" not in output


def test_facts_block_with_none_answers():
    """Calling with answers=None omits all answer lines."""
    truth = _truth()
    output_with_none = cover_letter_facts_block(truth, None)
    output_without = cover_letter_facts_block(truth)
    # Both should be identical (no answer section)
    assert output_with_none == output_without
    # Should not contain specific answer value that wouldn't appear in truth
    assert "Recruiter" not in output_with_none  # how_did_you_hear value


def test_facts_block_no_forbidden_characters():
    """Neither profile nor answers introduce em dash, en dash, or curly quotes."""
    truth = _truth()
    answers = _answers()
    output = cover_letter_facts_block(truth, answers)
    assert EM_DASH not in output, "em dash must not appear"
    assert EN_DASH not in output, "en dash must not appear"
    for ch in CURLY:
        assert ch not in output, f"curly quote {repr(ch)} must not appear"


def test_facts_block_blank_profile_skipped():
    """When profile is entirely blank, no profile section appears."""
    truth = Truth(
        profile=Profile(),  # All fields blank
        experiences=[
            Experience(
                id="e1",
                role="Engineer",
                company="Acme",
                start="2020",
                end="2023",
                source="linkedin-pdf",
                bullets=[],
            )
        ],
        skills=[],
    )
    answers = _answers()
    output = cover_letter_facts_block(truth, answers)
    # No "Candidate profile:" header when profile is blank
    assert "Candidate profile:" not in output
    # But answer values should still appear
    assert "Current role: Staff Engineer" in output
