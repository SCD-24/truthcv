"""Prune/watchlist behaviour of the company board store.

The agent records a company board for every company on the watchlist. prune()
keeps only boards whose company is still on the watchlist, while an empty
watchlist means "unconfigured" and prunes nothing.
"""

from __future__ import annotations

import companyboards.store as boards


def test_prune_with_an_empty_watchlist_keeps_everything(data_dir):
    """An empty watchlist means "unconfigured", not "delete every board"."""
    boards.record("Contoso Labs", "https://contoso.example/careers")
    boards.prune([])
    assert "contoso labs" in boards.load()


def test_prune_drops_companies_off_the_watchlist(data_dir):
    boards.record("Contoso Labs", "https://contoso.example/careers")
    boards.prune(["Other Co"])
    assert "contoso labs" not in boards.load()
