from connections.catalog import CARDS, card, card_keys


def test_stage1_cards_present():
    assert card_keys() == ("claude", "codex", "openrouter", "ollama")


def test_card_shapes():
    assert card("claude")["modes"] == ("subscription", "apikey")
    assert card("codex")["modes"] == ("subscription", "apikey")
    assert card("openrouter")["modes"] == ("apikey",)
    assert card("ollama")["modes"] == ("url",)
    for c in CARDS.values():
        assert c["label"]


def test_unknown_card_raises():
    import pytest
    with pytest.raises(KeyError):
        card("copilot")


def test_modes_are_the_seam_the_frontend_derives_from():
    """Pins the catalog's mode strings to the seam the frontend's
    CONNECTION_MODES constant (web/src/api/types.ts) is derived from. A mode
    string here that isn't one of these three silently breaks the UI's
    mode-gated rendering (AccountsSection.tsx) without either side's tests
    failing on their own."""
    known = {"subscription", "apikey", "url"}
    for c in CARDS.values():
        assert set(c["modes"]) <= known
