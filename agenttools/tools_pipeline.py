"""Pipeline helper tools for the agent tool surface.

Same module rule as tools_runs.py: every parameter has a default (the MCP
schema is derived from ``inspect.signature``; a defaultless parameter would be
marked required) and nothing here can fail a run.
"""

from __future__ import annotations

import runs.store as _runs_store
from agentconfig.store import load as _agent_config_load
from screening import store as _screening_store
from screening.url import is_posting_url, posting_dedupe_key


def _strip_fragment(url: str) -> str:
    return url.split("#", 1)[0].strip()


def filter_unscreened_urls(urls: list[str] = []) -> dict:  # noqa: B006 - never mutated
    """Given candidate posting URLs, return only those not already screened,
    in input order, without duplicates. URL fragments are ignored when
    comparing. LinkedIn search/listing pages (linkedin.com URLs that are not
    /jobs/view/<id>) are not postings and are dropped; the same LinkedIn job
    on any subdomain counts as one posting.
    """
    try:
        profiles = [p.name for p in _agent_config_load().profiles if p.enabled]
    except Exception:
        profiles = None  # fail open: today's any-record behaviour
    try:
        screened = _screening_store.screened_dedupe_keys(profiles)
    except Exception:
        screened = set()
    seen: dict[str, str] = {}  # posting key -> first bare URL
    unscreened: list[str] = []
    dropped: list[dict] = []
    for url in urls or []:
        if not isinstance(url, str) or not url:
            continue
        bare = _strip_fragment(url)
        reason = _drop_reason(bare, seen, screened)
        if reason is None:
            unscreened.append(bare)
        else:
            dropped.append({"url": bare or url, **reason})
    return {"unscreened": unscreened, "dropped": dropped}


def _drop_reason(bare: str, seen: dict[str, str], screened: set) -> dict | None:
    """Why ``bare`` is dropped (a ``{reason, duplicate_of?}`` dict), or None
    to keep it. Records the posting key in ``seen`` on first sight."""
    if not bare or not is_posting_url(bare):
        return {"reason": "not_a_posting"}
    # Dedupe on the store's own posting key so candidates the store
    # treats as one posting are screened once.
    key = posting_dedupe_key(bare) or bare
    if key in seen:
        return {"reason": "duplicate", "duplicate_of": seen[key]}
    seen[key] = bare
    if key in screened:
        return {"reason": "previously_screened"}
    return None


def finish_application(
    run_id: str = "", url: str = "", outcome: str = "", note: str = ""
) -> dict:
    """Note the outcome of one application on the run record. Non-terminal:
    never changes run status and never ends the run.
    """
    if not run_id:
        return {"ok": True, "recorded": False, "reason": "run_id required"}
    text = "[application]"
    if url:
        text += f" {url}"
    if outcome:
        text += f" outcome={outcome}"
    if note:
        text += f" - {note}"
    try:
        record = _runs_store.append_note(run_id, text)
    except Exception:
        return {"ok": True, "recorded": False, "reason": "store error"}
    if record is None:
        return {"ok": True, "recorded": False, "reason": "unknown run_id"}
    return {"ok": True, "recorded": True}
