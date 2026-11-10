"""API-backed job feeds: boards TruthCV pulls postings from instead of searching.

A feed differs from every other job board in the catalog in that TruthCV, not
the agent, does the discovery: the operator saves an API key (or other
credential/config), the app calls the board's API with each enabled profile's
criteria, and the agent receives the resulting postings as concrete URLs in
its run prompt. There is no browser sign-in and no Google dork for these
boards.

The fetcher contract, so a second fetcher (e.g. an ATS fetcher) can implement
the same shape as jobfeeds.remoterocketship:

  - A fetcher is a callable that takes the enabled job profiles plus its own
    credential/config, and returns a ``FeedResult``.
  - It NEVER raises. Every failure — a bad credential, a timeout, a malformed
    response — comes back as a ``FeedResult`` with ``error`` set, so the
    caller (a config route serving other data alongside the feed) keeps
    working when the board does not.

This package is a leaf on the data path: it imports agentconfig.store for the
profile shape and secretstore for the key, and nothing imports it but api/.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FeedPosting:
    """One posting from a feed, in the shape the agent's run prompt renders."""

    profile: str = ""
    source: str = ""
    title: str = ""
    company: str = ""
    url: str = ""
    employment_type: str = ""
    salary_range: str = ""
    posted_at: str = ""
    # The extraction tier that produced this posting, e.g. "api" for a
    # feed hit directly against a board's own API.
    tier: str = "api"

    def to_dict(self) -> dict:
        return {
            "profile": self.profile,
            "source": self.source,
            "title": self.title,
            "company": self.company,
            "url": self.url,
            "employment_type": self.employment_type,
            "salary_range": self.salary_range,
            "posted_at": self.posted_at,
            "tier": self.tier,
        }


@dataclass
class FeedResult:
    """Outcome of a fetch: postings, plus a human-readable error when one failed.

    ``error`` being set does not mean ``postings`` is empty — with several
    profiles, one can fail while the others succeed, and dropping the
    successful ones would make a transient failure look like an empty feed.
    """

    postings: list[FeedPosting] = field(default_factory=list)
    error: str = ""
