"""The agent-config update workflow: normalize and merge a PUT body onto the
stored AgentConfig.
"""

from __future__ import annotations

from agentconfig import boards, store as agent_config_store
from agentconfig.salary import clamp_ask as _clamp_ask
from agentconfig.salary import format_ask as _format_ask

# The optional numeric windows are the exception to exclude_none: for them a
# null is a real value meaning "unset", and dropping it made those fields
# impossible to clear once set. Emptying the box on the Agents page sends
# null, the merge discarded it, and the UI then repainted the old value beside
# a "saved" indicator. They are re-applied explicitly below, still only when
# the client actually sent the key.
_NULLABLE_FIELDS = (
    "cooldown_days",
    "cooldown_days_same_role",
    "cooldown_days_same_company",
    "max_applications_per_run",
    "max_posting_age_days",
)


def update_agent_config(sent: dict) -> agent_config_store.AgentConfig:
    """Merge only the fields present in ``sent`` (already `exclude_unset`d by
    the caller) onto the stored config, and persist the result.

    Profiles are WHOLESALE-REPLACED (not merged) because a null or omitted
    profiles field never reaches the merge dict. job_boards is replaced the
    same way, but first NORMALISED: the response-only keys (domain,
    effective_signin_url, is_default, is_api, key_required, mode_locked) are stripped — they
    are derived, and a stored copy is a second writer that can go stale — and a
    default-source entry is DROPPED only when it carries a blank signin_url
    AND is enabled, so a client echoing back the resolved GET list does not
    bloat storage with the defaults. A default-source entry WITH a
    signin_url, or one the operator has disabled, is kept — both are
    legitimate per-board state with nowhere else to live. ``mode`` IS carried
    through (it is the one board-level field the operator can actually set)
    — dropping it here would silently revert a custom board's mode back to
    "dork" on every save.
    """
    sent = dict(sent)
    if "job_boards" in sent and sent["job_boards"] is not None:
        normalised = []
        for item in sent["job_boards"]:
            source = item.get("source", "")
            signin_url = item.get("signin_url", "")
            mode = item.get("mode", "")
            search_url = item.get("search_url", "")
            enabled = item.get("enabled", True)
            if not isinstance(enabled, bool):
                enabled = True
            posting_url_pattern = item.get("posting_url_pattern", "")
            if (
                boards.is_default_source(source)
                and not signin_url.strip()
                and not posting_url_pattern.strip()
                and enabled
            ):
                continue
            normalised.append({
                "source": source,
                "signin_url": signin_url,
                "mode": mode,
                "search_url": search_url,
                "enabled": enabled,
                "posting_url_pattern": posting_url_pattern,
            })
        sent["job_boards"] = normalised

    merged = agent_config_store.load().to_dict()
    merged.update({k: v for k, v in sent.items() if v is not None})
    for nullable in _NULLABLE_FIELDS:
        if nullable in sent and sent[nullable] is None:
            merged[nullable] = None

    cfg = agent_config_store.AgentConfig.from_dict(merged)
    return agent_config_store.save(cfg)


def load_enabled_profile(profile_name: str):
    """Return the named ENABLED JobProfile, or raise ``ValueError`` naming the enabled ones.

    Evaluating hard requirements against a profile nobody is currently
    searching under would be meaningless, so a disabled or unknown name is
    refused rather than silently matched.

    Public because the screening gate (services/screenings.py) and the agent
    tools both need the same lookup; one definition keeps the match rule and
    the refusal text from drifting apart.
    """
    cfg = agent_config_store.load()
    enabled = [p for p in cfg.profiles if p.enabled]
    needle = profile_name.strip().casefold()
    profile = next((p for p in enabled if p.name.strip().casefold() == needle), None)
    if profile is None:
        names = ", ".join(p.name for p in enabled) or "(none enabled)"
        raise ValueError(
            f"Unknown or disabled profile {profile_name!r}. Enabled profiles: {names}."
        )
    return profile


def recommend_salary(profile_name: str, proposed: int | None = None) -> dict:
    """Recommend a salary ask for a named profile, clamped to its configured band.

    Looks up ``profile_name`` in the configured job profiles and clamps
    ``proposed`` (or the band minimum, if omitted) into
    ``[salary_ask_min, salary_ask_max]`` via ``agentconfig.salary.clamp_ask``.
    Returns a refusal dict if the profile is unknown or has no salary band.

    Lives here so the agent's ``recommend_salary`` tool is a thin adapter and
    the band-lookup and refusal strings have one home next to the config they
    read.
    """
    cfg = agent_config_store.load()
    profile = next((p for p in cfg.profiles if p.name == profile_name), None)
    if profile is None:
        return {"refused": f"Profile not found: {profile_name}"}

    clamped = _clamp_ask(profile, proposed)
    if clamped is None:
        return {"refused": "Profile has no salary band configured"}

    return {
        "amount": clamped,
        "formatted": _format_ask(profile, clamped),
        "band": {"min": profile.salary_ask_min, "max": profile.salary_ask_max},
        # Only a figure the caller actually proposed can be "clamped"; with
        # proposed=None the band minimum is supplied, not adjusted.
        "clamped": proposed is not None and proposed != clamped,
    }
