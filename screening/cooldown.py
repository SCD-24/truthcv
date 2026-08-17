"""Cooldown checks: has this company (optionally role) been recently ruled out?

A rejected screening carries its own ``cooldown_expires``. A tracked
application has no explicit cooldown field, so one is derived from its
``application_date`` plus a configurable duration — having already applied is
itself a reason to wait before reconsidering the same company/role. Whichever
source yields the later expiry wins.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from agentconfig.store import is_blocked as agent_config_is_blocked
from agentconfig.store import load as agent_config_load
from applications.store import load_all as load_applications

from .store import load_all as load_screenings


def application_cooldown_days() -> int:
    """Days after an application's date before the company clears cooldown."""
    raw = os.environ.get("APPLICATION_COOLDOWN_DAYS", "90")
    if not raw or not raw.strip():
        return 90
    try:
        return int(raw)
    except ValueError:
        return 90


@dataclass
class CooldownStatus:
    """Whether a company (optionally role) is currently in cooldown."""

    in_cooldown: bool
    expires: str | None = None
    blocked: bool = False


def _matches(company: str, role: str | None, rec_company: str, rec_role: str) -> bool:
    """Case/whitespace-insensitive company match; role matched only if given.

    Records with a non-string company/role never match (fail-safe skip).
    """
    if not isinstance(rec_company, str):
        return False
    if company.strip().casefold() != rec_company.strip().casefold():
        return False
    if role:
        if not isinstance(rec_role, str):
            return False
        if role.strip().casefold() != rec_role.strip().casefold():
            return False
    return True


def _parse(ts: str) -> datetime | None:
    """Parse an ISO-8601 timestamp/date; None if blank, non-string, or unparsable."""
    if not isinstance(ts, str) or not ts.strip():
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _screening_expiries(company: str, role: str | None) -> list[datetime]:
    """Explicit ``cooldown_expires`` from screening records matching company/role."""
    expiries = []
    for s in load_screenings():
        if _matches(company, role, s.company, s.role):
            dt = _parse(s.cooldown_expires)
            if dt:
                expiries.append(dt)
    return expiries


def _application_expiries(company: str, role: str | None) -> list[datetime]:
    """Derived expiries (application_date + configured duration) for matches."""
    days = application_cooldown_days()
    expiries = []
    for a in load_applications():
        if _matches(company, role, a.company, a.role):
            dt = _parse(a.application_date)
            if dt:
                expiries.append(dt + timedelta(days=days))
    return expiries


def cooldown(company: str, role: str | None = None) -> CooldownStatus:
    """Whether ``company`` (optionally narrowed by ``role``) is in cooldown.

    Considers both screening records' own ``cooldown_expires`` and a derived
    expiry for tracked applications; the latest expiry across both wins.

    A blank/whitespace (or non-string) ``company`` never matches anything and
    always reports no cooldown.

    A blocklisted company is permanently in cooldown (blocked=True, no expiry).
    """
    if not isinstance(company, str) or not company.strip():
        return CooldownStatus(in_cooldown=False, expires=None)
    cfg = agent_config_load()
    if agent_config_is_blocked(cfg, company):
        return CooldownStatus(in_cooldown=True, expires=None, blocked=True)
    expiries = _screening_expiries(company, role) + _application_expiries(company, role)
    if not expiries:
        return CooldownStatus(in_cooldown=False)
    latest = max(expiries)
    return CooldownStatus(
        in_cooldown=latest > datetime.now(timezone.utc), expires=latest.isoformat()
    )
