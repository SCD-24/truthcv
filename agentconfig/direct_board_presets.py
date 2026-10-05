"""Built-in search/posting URL presets for well-known direct-mode boards.

Leaf module: imports only ``agentconfig.boards.resolve_domain``. A preset
fills in a direct board's blank ``search_url`` / ``posting_url_pattern``;
a non-blank operator value always wins (see dorks.compose_direct_boards).
"""

from __future__ import annotations

from agentconfig.boards import resolve_domain

# Keyed by resolve_domain host (www stripped). An empty search_url means the
# board's search URL is unverified, so none is supplied.
DIRECT_BOARD_PRESETS: dict[str, dict[str, str]] = {
    "arbeitsagentur.de": {
        "search_url": "https://www.arbeitsagentur.de/jobsuche/suche?was={keywords}&wo={location}",
        "posting_url_pattern": "https://www.arbeitsagentur.de/jobsuche/jobdetail/*",
    },
    "startupjobs.de": {
        "search_url": "https://startupjobs.de/jobs?q={keywords}",
        "posting_url_pattern": "https://startupjobs.de/*jobs/*",
    },
    "talentsift.de": {
        "search_url": "https://talentsift.de/jobs?q={keywords}",
        "posting_url_pattern": "https://talentsift.de/jobs/*",
    },
    "nomado24.de": {
        "search_url": "",
        "posting_url_pattern": "https://www.nomado24.de/*remote-jobs/job/*",
    },
}


def preset_for(source: str) -> dict[str, str] | None:
    """Return a copy of the preset for a board source, or None if unknown.

    The source (URL or bare host, with or without ``www.``) is normalised
    through resolve_domain before lookup.
    """
    domain = resolve_domain(source)
    preset = DIRECT_BOARD_PRESETS.get(domain) if domain else None
    return dict(preset) if preset else None
