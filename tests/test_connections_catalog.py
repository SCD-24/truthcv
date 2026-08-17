from connections.catalog import CARDS, card, card_keys


def test_stage1_cards_present():
    assert card_keys() == ("claude", "codex", "openrouter", "ollama")


def test_card_shapes():
    assert card("claude")["modes"] == ("subscription", "apikey")
    assert card("codex")["modes"] == ("apikey",)
    assert card("openrouter")["modes"] == ("apikey",)
    assert card("ollama")["modes"] == ("url",)
    for c in CARDS.values():
        assert c["label"]


def test_unknown_card_raises():
    import pytest
    with pytest.raises(KeyError):
        card("copilot")
