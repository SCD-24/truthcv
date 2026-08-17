"""Static catalog of provider connection cards.

Stage 1 ships claude (subscription + apikey), codex (apikey only — its
subscription OAuth lands in stage 3), openrouter, ollama. Model lists are
never hardcoded; they are discovered live per connection.
"""

from __future__ import annotations

CARDS: dict[str, dict] = {
    "claude": {"label": "Claude (Anthropic)", "modes": ("subscription", "apikey")},
    "codex": {"label": "ChatGPT (OpenAI)", "modes": ("apikey",)},
    "openrouter": {"label": "OpenRouter", "modes": ("apikey",)},
    "ollama": {"label": "Ollama", "modes": ("url",)},
}


def card_keys() -> tuple[str, ...]:
    return tuple(CARDS.keys())


def card(key: str) -> dict:
    return CARDS[key]
