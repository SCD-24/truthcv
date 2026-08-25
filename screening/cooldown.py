"""Cooldown checks: has this company (optionally role) been recently ruled out?

A rejected screening carries its own ``cooldown_expires``. A tracked
application has no explicit cooldown field, so one is derived from its
``application_date`` plus a configurable duration — having already applied is
itself a reason to wait before reconsidering the same company/role. Whichever
source yields the later expiry wins.

Company matching is by identity key (``screening.company.company_identity_key``),
not raw casefold equality, so a legal-entity suffix does not manufacture a
second company: an application to "RobCo GmbH" puts "RobCo" in cooldown too.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from agentconfig.store import is_blocked as agent_config_is_blocked
from agentconfig.store import load as agent_config_load
from applications.store import load_all as load_applications

from .company import company_identity_key
from .store import load_all as load_screenings


def _window_from_env() -> int:
    """APPLICATION_COOLDOWN_DAYS env value, or 90 when blank/unparsable."""
    raw = os.environ.get("APPLICATION_COOLDOWN_DAYS", "90")
    if not raw or not raw.strip():
        return 90
    try:
        return int(raw)
    except ValueError:
        return 90


def _configured_days(window: int | None, legacy: int | None) -> int | None:
    """Resolve one cooldown window from config values.

    A window's own field wins when set (>= 0); otherwise the legacy single
    `cooldown_days` applies so present installs are unchanged; None means no
    configured value and the caller falls back to the environment.
    """
    for value in (window, legacy):
        if value is not None and value >= 0:
            return value
    return None


def same_role_cooldown_days() -> int:
    """Cooldown days for re-applying to a role already applied to.

    Precedence: AgentConfig.cooldown_days_same_role -> AgentConfig.cooldown_days
    (legacy single window) -> APPLICATION_COOLDOWN_DAYS env -> 90. Config-load
    failures fail safe to the env/default path.
    """
    try:
        cfg = agent_config_load()
        days = _configured_days(cfg.cooldown_days_same_role, cfg.cooldown_days)
    except Exception:
        days = None
    return days if days is not None else _window_from_env()


def application_cooldown_days() -> int:
    """Cooldown days for a company-only match (same-company window).

    Precedence: AgentConfig.cooldown_days_same_company ->
    AgentConfig.cooldown_days (legacy single window) -> APPLICATION_COOLDOWN_DAYS
    env -> 90. Kept as the historical name; it now resolves the SAME-COMPANY
    window, used whenever no role was supplied or the record's role differs.
    """
    try:
        cfg = agent_config_load()
        days = _configured_days(cfg.cooldown_days_same_company, cfg.cooldown_days)
    except Exception:
        days = None
    return days if days is not None else _window_from_env()


@dataclass
class CooldownStatus:
    """Whether a company (optionally role) is currently in cooldown.

    ``window`` names which cooldown window produced the block — 'same_role'
    or 'same_company' — so the UI can tell the user which setting to change.
    None when not in cooldown, or when blocked via the permanent blocklist
    (which has no window).
    """

    in_cooldown: bool
    expires: str | None = None
    blocked: bool = False
    window: str | None = None


def _matches(company: str, role: str | None, rec_company: str, rec_role: str) -> bool:
    """Identity-key company match; role matched (case/whitespace-insensitive) only if given.

    Records with a non-string company/role never match (fail-safe skip). A
    blank/whitespace-only ``company`` never matches anything, since
    ``company_identity_key`` never returns "" for a non-empty input (so an
    empty key here would otherwise risk matching a similarly-degenerate
    record company).
    """
    if not isinstance(rec_company, str):
        return False
    if not company.strip():
        return False
    if company_identity_key(company) != company_identity_key(rec_company):
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


def _screening_expiries(company: str, role: str | None) -> list[tuple[datetime, str]]:
    """(expiry, window) pairs from screening records' own ``cooldown_expires``.

    A screening record carries an explicit expiry set when it was recorded, so
    the window that produced it is not re-derived here; the record's role is
    what matched, so a role-matched record reports the same-role window and
    any other match the same-company one.
    """
    expiries = []
    for s in load_screenings():
        if _matches(company, role, s.company, s.role):
            dt = _parse(s.cooldown_expires)
            if dt:
                window = "same_role" if role else "same_company"
                expiries.append((dt, window))
    return expiries


def _application_expiries(company: str, role: str | None) -> list[tuple[datetime, str]]:
    """Derived (expiry, window) pairs for matching applications.

    The same-role window applies only when a role was supplied AND the
    record's role matches; every other match uses the same-company window.
    """
    same_role_days = None
    if role:
        same_role_days = same_role_cooldown_days()
    company_days = application_cooldown_days()
    expiries = []
    for a in load_applications():
        if not isinstance(a.company, str):
            continue
        if not company.strip():
            continue
        company_matched = company_identity_key(company) == company_identity_key(
            a.company
        )
        if not company_matched:
            continue
        role_matched = bool(role) and _matches(company, role, a.company, a.role)
        days = same_role_days if role_matched else company_days
        dt = _parse(a.application_date)
        if not dt:
            continue
        # A single application can block under BOTH windows: its own role
        # (same-role window) and the company as a whole (same-company
        # window). Emit each window's expiry; the later one governs.
        expiries.append((dt + timedelta(days=days), "same_role" if role_matched else "same_company"))
        if role_matched:
            expiries.append((dt + timedelta(days=company_days), "same_company"))
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
    latest_expiry, latest_window = max(expiries, key=lambda pair: pair[0])
    return CooldownStatus(
        in_cooldown=latest_expiry > datetime.now(timezone.utc),
        expires=latest_expiry.isoformat(),
        window=None if not (latest_expiry > datetime.now(timezone.utc)) else latest_window,
    )
