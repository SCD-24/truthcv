"""Company board resolution store — persist recorded and resolved company careers board URLs."""

from dataclasses import dataclass, field
from pathlib import Path
from truth.store import data_dir
import json


@dataclass
class CompanyBoard:
    """Resolved company careers board entry."""

    company: str
    careers_url: str
    ats: str = ""
    status: str = "ok"
    resolved_at: str = ""
    # Operator-granted, company-level trust. Clears deferral blockers for any
    # role here; never bypasses per-role screening. record_company_board takes
    # no such argument, so the agent cannot set it.
    approved: bool = False

    @classmethod
    def from_dict(cls, raw: dict) -> "CompanyBoard":
        """Construct from a dict, ignoring unknown keys and falling back to defaults on wrong types."""
        kwargs = {}

        # company: str
        if "company" in raw and isinstance(raw["company"], str):
            kwargs["company"] = raw["company"]

        # careers_url: str
        if "careers_url" in raw and isinstance(raw["careers_url"], str):
            kwargs["careers_url"] = raw["careers_url"]

        # ats: str
        if "ats" in raw and isinstance(raw["ats"], str):
            kwargs["ats"] = raw["ats"]

        # status: str
        if "status" in raw and isinstance(raw["status"], str):
            kwargs["status"] = raw["status"]

        # resolved_at: str
        if "resolved_at" in raw and isinstance(raw["resolved_at"], str):
            kwargs["resolved_at"] = raw["resolved_at"]

        # approved: bool
        if "approved" in raw and isinstance(raw["approved"], bool):
            kwargs["approved"] = raw["approved"]

        return cls(**kwargs)

    def to_dict(self) -> dict:
        """Serialize to a dict with snake_case keys."""
        return {
            "company": self.company,
            "careers_url": self.careers_url,
            "ats": self.ats,
            "status": self.status,
            "resolved_at": self.resolved_at,
            "approved": self.approved,
        }


def board_path() -> Path:
    """Path to the company_boards.json file."""
    return data_dir() / "company_boards.json"


def load() -> dict[str, CompanyBoard]:
    """Load company boards from storage, returning empty dict on missing/corrupt file."""
    path = board_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        boards = {}
        for key, item in raw.items():
            if isinstance(item, dict):
                boards[key] = CompanyBoard.from_dict(item)
        return boards
    except (json.JSONDecodeError, OSError):
        return {}


def save(boards: dict[str, CompanyBoard]) -> None:
    """Atomically save boards to storage using tmp + replace."""
    path = board_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {name: board.to_dict() for name, board in boards.items()}
    tmp_path = path.parent / (path.name + ".tmp")
    try:
        tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def _normalize_company(name: str) -> str:
    """Normalize company name with consistent casing."""
    return name.strip().casefold()


def record(company: str, careers_url: str, ats: str = "", status: str = "ok") -> None:
    """Record or update a company board entry.

    Merges onto any existing entry rather than replacing it. The agent
    re-records boards every run, and rebuilding from these arguments alone would
    silently drop the operator's `approved` flag (and the resolution stamp).
    """
    boards = load()
    normalized = _normalize_company(company)
    existing = boards.get(normalized)
    boards[normalized] = CompanyBoard(
        company=company,
        careers_url=careers_url,
        ats=ats,
        status=status,
        resolved_at=existing.resolved_at if existing else "",
        approved=existing.approved if existing else False,
    )
    save(boards)


def set_approved(company: str, approved: bool) -> CompanyBoard | None:
    """Grant or revoke company-level approval.

    Returns the updated entry so callers need not re-normalise the name to read
    it back; None when the company has no board.
    """
    boards = load()
    normalized = _normalize_company(company)
    if normalized not in boards:
        return None
    boards[normalized].approved = approved
    save(boards)
    return boards[normalized]


def mark_dead(company: str) -> None:
    """Mark a company board as dead (no active careers board)."""
    boards = load()
    normalized = _normalize_company(company)
    if normalized in boards:
        boards[normalized].status = "dead"
        save(boards)


def prune(target_companies: list[str]) -> None:
    """Remove board entries whose company is not in the target watchlist."""
    boards = load()
    normalized_targets = {_normalize_company(name) for name in target_companies}

    # Filter to only keep boards for companies still on the watchlist
    pruned = {k: v for k, v in boards.items() if k in normalized_targets}

    if len(pruned) != len(boards):
        save(pruned)
