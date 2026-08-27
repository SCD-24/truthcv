"""The agent-config update workflow: normalize and merge a PUT body onto the
stored AgentConfig.
"""

from __future__ import annotations

from agentconfig import boards, store as agent_config_store

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
    effective_signin_url, is_default) are stripped — they are derived, and a
    stored copy is a second writer that can go stale — and any default-source
    entry with a blank signin_url is DROPPED, so a client echoing back the
    resolved GET list does not bloat storage with the four defaults. A
    default-source entry WITH a signin_url is kept, since that is a
    legitimate override.
    """
    sent = dict(sent)
    if "job_boards" in sent and sent["job_boards"] is not None:
        normalised = []
        for item in sent["job_boards"]:
            source = item.get("source", "")
            signin_url = item.get("signin_url", "")
            if boards.is_default_source(source) and not signin_url.strip():
                continue
            normalised.append({"source": source, "signin_url": signin_url})
        sent["job_boards"] = normalised

    merged = agent_config_store.load().to_dict()
    merged.update({k: v for k, v in sent.items() if v is not None})
    for nullable in _NULLABLE_FIELDS:
        if nullable in sent and sent[nullable] is None:
            merged[nullable] = None

    cfg = agent_config_store.AgentConfig.from_dict(merged)
    return agent_config_store.save(cfg)
