"""MCP tools for recording company board resolutions."""

from companyboards import store


def record_company_board(company: str, careers_url: str, ats: str = "", status: str = "ok") -> dict:
    """Record or update a resolved company board entry.

    Args:
        company: Company name (normalized to lowercase for deduplication).
        careers_url: URL of the careers/apply page.
        ats: ATS system name (Lever, Greenhouse, BambooHR, etc.).
        status: Status of the board ("ok" or "dead").

    Returns:
        Dict with the recorded company name and careers_url.
    """
    store.record(company, careers_url, ats, status)
    return {"company": company, "careers_url": careers_url, "ats": ats, "status": status}
