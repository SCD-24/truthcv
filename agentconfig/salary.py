"""Pure salary helpers for job profiles: clamping asks and formatting for display.

No I/O; operates only on JobProfile instances and plain values.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentconfig.store import JobProfile


def clamp_ask(profile: "JobProfile", proposed: int | None) -> int | None:
    """Clamp a proposed salary ask into [profile.salary_ask_min, profile.salary_ask_max].

    If proposed is None, returns salary_ask_min instead. If either bound is
    None, returns None: we decline to guess a number rather than invent one.
    If salary_ask_min > salary_ask_max (a misconfigured profile), returns the
    lesser of the two bounds rather than raising.
    """
    ask_min = profile.salary_ask_min
    ask_max = profile.salary_ask_max

    if ask_min is None or ask_max is None:
        return None

    if ask_min > ask_max:
        ask_min, ask_max = ask_max, ask_min

    if proposed is None:
        return ask_min

    return max(ask_min, min(proposed, ask_max))


def format_ask(profile: "JobProfile", amount: int | None) -> str:
    """Format an amount for display as '<currency> <amount with thousands separators>'.

    E.g. format_ask(profile, 105000) with profile.currency == "EUR" yields
    'EUR 105,000'. If amount is None, returns an empty string.
    """
    if amount is None:
        return ""

    return f"{profile.currency} {amount:,}"
