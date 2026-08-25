"""Pin the numeric page-target parser and its non-interference with prose.

page_target_pages() is a numeric helper layered over CvConventions.page_target,
which prompts/style.py and prompts/coverletter.py still read as free-form prose.
These tests guard both: the parser's behaviour, and that the string itself is
untouched.
"""

from prompts.conventions import CvConventions, DEFAULT_CONVENTIONS, page_target_pages


def test_default_conventions_parse_to_one_page():
    assert page_target_pages(DEFAULT_CONVENTIONS) == 1


def test_two_pages_word_form():
    assert page_target_pages(CvConventions(page_target="two pages")) == 2


def test_digit_with_page_word():
    assert page_target_pages(CvConventions(page_target="1 page")) == 1


def test_bare_digit():
    assert page_target_pages(CvConventions(page_target="2")) == 2


def test_unparseable_string_returns_none():
    assert page_target_pages(CvConventions(page_target="as short as possible")) is None


def test_page_target_is_still_prose_for_the_prompt_builders():
    assert CvConventions().page_target == "one page"
    assert isinstance(DEFAULT_CONVENTIONS.page_target, str)
