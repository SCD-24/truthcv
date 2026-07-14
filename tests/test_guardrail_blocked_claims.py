"""Guardrail structured blocked-claims reporting (current Scope API).

Pins the behavior the download-step approve/deny flow depends on: untraceable
tokens are grouped under the specific source text (bullet) and scope they came
from, so a whole claim can be approved or denied.
"""

from __future__ import annotations

from guardrail import validate, Scope


def test_blocked_claims_group_tokens_under_source_text():
    scopes = [
        Scope(id="exp-1", texts=["Built a payments API in Rust"], allowed=["Built a payments API in Python"]),
    ]
    result = validate(scopes, global_values=[])
    assert not result.ok
    assert len(result.blocked_claims) == 1
    claim = result.blocked_claims[0]
    assert claim.scope_id == "exp-1"
    assert claim.text == "Built a payments API in Rust"
    assert "rust" in claim.tokens
    assert "python" not in claim.tokens  # traceable token not flagged


def test_all_traceable_yields_no_blocked_claims():
    scopes = [Scope(id="exp-1", texts=["Shipped 3 microservices"], allowed=["Shipped 3 microservices"])]
    result = validate(scopes, global_values=[])
    assert result.ok
    assert result.blocked_claims == []


def test_each_flagged_bullet_is_its_own_claim():
    scopes = [
        Scope(
            id="exp-1",
            texts=["Led migration to Kubernetes", "Managed a team of 12"],
            allowed=["Led migration to production"],
        )
    ]
    result = validate(scopes, global_values=[])
    texts = {c.text for c in result.blocked_claims}
    assert "Led migration to Kubernetes" in texts
    assert "Managed a team of 12" in texts


def test_approved_text_merged_into_allowed_passes():
    # Mirrors the render-scoped approval: appending the claim text to allowed
    # makes it traceable without any truth write.
    scope = Scope(id="exp-1", texts=["Built in Rust"], allowed=[])
    assert not validate([scope], global_values=[]).ok
    scope.allowed.append("Built in Rust")
    assert validate([scope], global_values=[]).ok
