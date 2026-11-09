"""Pipeline helper tools for the agent tool surface.

Same module rule as tools_runs.py: every parameter has a default (the MCP
schema is derived from ``inspect.signature``; a defaultless parameter would be
marked required) and nothing here can fail a run.
"""

from __future__ import annotations

from services import pipeline as _pipeline


def filter_unscreened_urls(urls: list[str] = []) -> dict:  # noqa: B006 - never mutated
    """Given candidate posting URLs, return only those not already screened,
    in input order, without duplicates. URL fragments are ignored when
    comparing. LinkedIn search/listing pages (linkedin.com URLs that are not
    /jobs/view/<id>) are not postings and are dropped; the same LinkedIn job
    on any subdomain counts as one posting.
    """
    return _pipeline.filter_unscreened_urls(urls)


def finish_application(
    run_id: str = "", url: str = "", outcome: str = "", note: str = ""
) -> dict:
    """Note the outcome of one application on the run record. Non-terminal:
    never changes run status and never ends the run.
    """
    return _pipeline.finish_application(run_id, url, outcome, note)
