"""The Claude Code preamble is duplicated across two languages; pin them together.

A Claude subscription (OAuth) token is rejected by the Messages API unless this
exact string is the FIRST system block. The rejection is a 429
``rate_limit_error`` whose message is the bare word "Error", which reads as an
exhausted quota and is not one — so a drift here costs a long diagnosis, not a
quick one. The app sends it from ``connections/auth/claude.py``; the unattended
agent's harness is TypeScript and cannot import that, so it carries its own copy.
"""

from __future__ import annotations

import re
from pathlib import Path

from connections.auth.claude import CLAUDE_CODE_PREAMBLE

_ADAPTER = Path(__file__).resolve().parents[1] / "agent/harness/providers/anthropicMessages.ts"


def _harness_preamble() -> str:
    source = _ADAPTER.read_text(encoding="utf-8")
    match = re.search(r"const CLAUDE_CODE_PREAMBLE = \"([^\"]+)\";", source)
    assert match, f"no CLAUDE_CODE_PREAMBLE literal found in {_ADAPTER}"
    return match.group(1)


def test_harness_preamble_matches_the_apps():
    assert _harness_preamble() == CLAUDE_CODE_PREAMBLE


def test_harness_sends_the_preamble_first_for_oauth():
    """Order is the requirement, not mere presence: the API gates on the block
    being first."""
    source = _ADAPTER.read_text(encoding="utf-8")
    assert "blocks: unknown[] = [{ type: 'text', text: CLAUDE_CODE_PREAMBLE }]" in source


def test_harness_sends_the_oauth_beta_header():
    """Matches providers/anthropic_provider.py's default_headers."""
    source = _ADAPTER.read_text(encoding="utf-8")
    assert "'anthropic-beta'] = 'oauth-2025-04-20'" in source
