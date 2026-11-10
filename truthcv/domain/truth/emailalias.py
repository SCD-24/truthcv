"""Per-company email aliasing.

Pure, deterministic helpers that turn a stored email address plus a company
name into a per-company tracking address, so replies from a given employer
can be identified (and filtered) in the operator's mailbox.
"""

import re

# Marks an address as TruthCV-generated so it is recognisable and filterable
# in the mailbox. Every alias this module produces carries it.
ALIAS_PREFIX = "tcv_"

_NON_SLUG_RUN = re.compile(r"[^a-z0-9]+")


def company_slug(company: str) -> str:
    """Return a bare (unprefixed) filesystem/email-safe slug for `company`.

    Casefolds the input, collapses every run of characters outside
    [a-z0-9] into a single '_', strips leading/trailing '_', and truncates
    to 36 characters (leaving room for the 4-character ALIAS_PREFIX inside
    a 40-character budget), stripping any trailing '_' left by truncation.
    """
    slug = _NON_SLUG_RUN.sub("_", company.casefold()).strip("_")
    slug = slug[:36].rstrip("_")
    return slug


def alias_email(email: str, company: str) -> str:
    """Return `email` rewritten as a per-company tracking address.

    Strips surrounding whitespace from `email`. Returns it unchanged when
    `company` slugs to an empty string, `email` does not contain exactly
    one '@', the local part is empty, the domain is empty, or the local
    part already contains a '+'. Otherwise returns
    f"{local}+{ALIAS_PREFIX}{slug}@{domain}".

    Only the company slug is lowercased; the email itself is left as-is.
    """
    email = email.strip()
    slug = company_slug(company)
    if not slug:
        return email
    parts = email.split("@")
    if len(parts) != 2:
        return email
    local, domain = parts
    if not local or not domain or "+" in local:
        return email
    return f"{local}+{ALIAS_PREFIX}{slug}@{domain}"
