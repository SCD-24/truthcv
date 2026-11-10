"""check_style: deterministic AI-writing tell warnings."""

import pytest

from truthcv.engines.render.style_tells import MAX_SNIPPETS, check_style

EM = "—"
EN = "–"


def _codes(text: str) -> list[str]:
    return [w["code"] for w in check_style(text)]


def _found(warning: dict[str, str]) -> int:
    return warning["message"].split("Found:")[1].count(",") + 1


def test_clean_text_returns_empty():
    assert check_style("Built a billing service in Python.") == []


def test_cv_boilerplate_is_clean():
    text = (
        "Jane Doe\nname@example.com | +1 555 0100 | City\n"
        "Experience\nEngineer, Acme  2019 " + EN + " 2021\n"
        "Education\nSkills\nPython, SQL\n"
    )
    assert check_style(text) == []


def test_warning_shape():
    (w,) = check_style("a " + EM + " b")
    assert set(w) == {"code", "message"}


def test_dash_variants_fire_once_each_code():
    assert _codes("a " + EM + " b " + EM + " c") == ["style-dash"]
    assert _codes("a " + EN + " b") == ["style-dash"]
    assert _codes("a -- b") == ["style-dash"]


@pytest.mark.parametrize(
    "rng",
    [
        "2019 " + EN + " 2021",
        "2019" + EN + "2021",
        "Jan 2019 " + EN + " Present",
        "Jan 2019 " + EN + " Mar 2021",
        "Sept. 2019 " + EN + " March 2021",
        "2019 " + EN + " Present",
        "03/2020 " + EN + " 05/2022",
        "3/2020 " + EN + " 5/2022",
        "03/2020" + EN + "05/2022",
        "2020-03 " + EN + " 2022-05",
        "2020/03 " + EN + " 2022/05",
        "03.2020 " + EN + " 05.2022",
        "jan 2019 " + EN + " current",
        "2019 " + EN + " now",
        "2019 " + EN + " ongoing",
        "2019 " + EN + " Today",
    ],
)
def test_en_dash_in_date_ranges_is_exempt(rng):
    assert check_style(rng) == []


@pytest.mark.parametrize(
    "text",
    [
        "Python " + EN + " Go",
        "pages 3 " + EN + " 5 of the report",
        "Python " + EN + " fast. 2019 " + EN + " 2021",
        "2019 " + EM + " 2021",
        "2019 -- 2021",
    ],
)
def test_non_date_dashes_still_warn(text):
    assert _codes(text) == ["style-dash"]


def test_original_casing_kept_in_snippets():
    (w,) = check_style("Leverage Python")
    assert "'Leverage'" in w["message"]


def test_curly_quotes_fire():
    for ch in "‘’“”":
        assert _codes("it" + ch + "s") == ["style-curly-quote"]


def test_tell_word_whole_word_case_insensitive():
    assert _codes("Leverage the API") == ["style-tell-word"]
    assert _codes("We leveraged the API and delved in") == []


def test_chatbot_residue_phrases():
    for phrase in (
        "Here is your CV",
        "here's your CV",
        "here’s your CV",
        "I hope this helps",
        "Let me know if",
        "Certainly! Done",
        "Of course! Done",
        "As an AI model",
        "Great question",
    ):
        assert "style-chatbot-residue" in _codes(phrase), phrase


def test_weak_tells_need_two_hits():
    one = "Shipped features, ensuring uptime."
    assert check_style(one) == []
    two = one + " Was involved in launches."
    assert _codes(two) == ["style-weak-tells"]


def test_weak_tells_cover_all_families():
    text = "Played a key role, highlighting wins. Associated with the team."
    assert _codes(text) == ["style-weak-tells"]


def test_weak_tells_cover_association_and_significance():
    for phrase in ("Contributed to the launch", "Marking a shift in scope"):
        text = phrase + ". Was involved in releases."
        assert _codes(text) == ["style-weak-tells"], phrase


def test_snippets_capped_and_distinct():
    text = " ".join(f"a{EM}b{i}" for i in range(MAX_SNIPPETS + 3))
    (w,) = check_style(text)
    assert _found(w) == MAX_SNIPPETS
    dup = check_style("x " + EM + " y x " + EM + " y")
    assert _found(dup[0]) == 1
