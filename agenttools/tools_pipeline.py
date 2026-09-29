"""Pipeline helper tools for the agent tool surface.

Same module rule as tools_runs.py: every parameter has a default (the MCP
schema is derived from ``inspect.signature``; a defaultless parameter would be
marked required) and nothing here can fail a run.
"""

from __future__ import annotations

import runs.store as _runs_store
from screening import store as _screening_store
from screening.url import posting_dedupe_key


def _strip_fragment(url: str) -> str:
    return url.split("#", 1)[0].strip()


def filter_unscreened_urls(urls: list[str] = []) -> dict:  # noqa: B006 - never mutated
    """Given candidate posting URLs, return only those not already screened,
    in input order, without duplicates. URL fragments are ignored when
    comparing.
    """
    try:
        screened = _screening_store.screened_dedupe_keys()
    except Exception:
        screened = set()
    seen: set[str] = set()
    unscreened: list[str] = []
    for url in urls or []:
        if not isinstance(url, str):
            continue
        bare = _strip_fragment(url)
        if not bare:
            continue
        # Dedupe on the store's own posting key so candidates the store
        # treats as one posting are screened once.
        key = posting_dedupe_key(bare) or bare
        if key in seen:
            continue
        seen.add(key)
        if key in screened:
            continue
        unscreened.append(bare)
    return {"unscreened": unscreened}


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
