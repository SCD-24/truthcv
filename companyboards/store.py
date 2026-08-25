"""Company board resolution store — persist recorded and resolved company careers board URLs."""

from dataclasses import dataclass, field
from pathlib import Path
from truth.store import data_dir
from screening.company import company_identity_key
import json


@dataclass
class CompanyBoard:
    """Resolved company careers board entry."""

    company: str
    careers_url: str
    ats: str = ""
    status: str = "ok"
    resolved_at: str = ""

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

        return cls(**kwargs)

    def to_dict(self) -> dict:
        """Serialize to a dict with snake_case keys."""
        return {
            "company": self.company,
            "careers_url": self.careers_url,
            "ats": self.ats,
            "status": self.status,
            "resolved_at": self.resolved_at,
        }


def board_path() -> Path:
    """Path to the company_boards.json file."""
    return data_dir() / "company_boards.json"


def load() -> dict[str, CompanyBoard]:
    """Load company boards from storage, returning empty dict on missing/corrupt file.

    The stored dict keys are re-keyed onto each entry's identity key (see
    ``_reconcile_keys``) before being returned, so callers never see two
    entries for legal-entity-suffix variants of the same company. This is an
    in-memory reconciliation only; a pure read never rewrites the file — the
    re-keyed map is only persisted the next time ``record()`` (or another
    writer) calls ``save()``.
    """
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
        return _reconcile_keys(boards)
    except (json.JSONDecodeError, OSError):
        return {}


def _reconcile_keys(boards: dict[str, CompanyBoard]) -> dict[str, CompanyBoard]:
    """Re-key ``boards`` onto each entry's identity key, merging any collisions.

    Older data was persisted keyed by plain ``strip().casefold()``, and even
    freshly-normalized keys can still collide once suffix-stripping is in
    play (e.g. a "robco" entry and a "robco gmbh" entry once both re-key to
    "robco"). When two stored entries collapse onto the same identity key,
    one is picked to represent it — preferring the one with a non-empty
    ``careers_url``, then the more recently resolved — and its ``company``
    display field (and every other field) is kept exactly as stored; nothing
    is concatenated or renamed. Idempotent: re-running this on an
    already-reconciled map is a no-op.
    """
    reconciled: dict[str, CompanyBoard] = {}
    for old_key, board in boards.items():
        new_key = company_identity_key(board.company) or old_key
        existing = reconciled.get(new_key)
        reconciled[new_key] = board if existing is None else _pick_richer(existing, board)
    return reconciled


def _pick_richer(a: CompanyBoard, b: CompanyBoard) -> CompanyBoard:
    """Pick the entry to keep when two boards collapse onto one identity key.

    Prefers the one with a non-empty ``careers_url`` (an actual resolution
    beats a placeholder), then the more recently resolved by ``resolved_at``
    string order (ISO-8601 sorts correctly as a string), then falls back to
    the first one seen.
    """
    a_has_url = bool(a.careers_url.strip())
    b_has_url = bool(b.careers_url.strip())
    if a_has_url != b_has_url:
        return a if a_has_url else b
    if a.resolved_at != b.resolved_at:
        return a if a.resolved_at > b.resolved_at else b
    return a


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
    """Normalize a company name to its identity key for use as the store's dict key.

    Delegates to ``screening.company.company_identity_key`` so a
    legal-entity suffix (e.g. "RobCo" vs "RobCo GmbH") does not produce two
    board entries for the same employer. See ``load()``/``_reconcile_keys``
    for how already-persisted entries under the old plain
    ``strip().casefold()`` key are migrated on read.
    """
    return company_identity_key(name)


def record(company: str, careers_url: str, ats: str = "", status: str = "ok") -> None:
    """Record or update a company board entry.

    Merges onto any existing entry rather than replacing it. The agent
    re-records boards every run, and rebuilding from these arguments alone would
    silently drop the resolution stamp of the previous discovery.
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
    )
    save(boards)


def mark_dead(company: str) -> None:
    """Mark a company board as dead (no active careers board)."""
    boards = load()
    normalized = _normalize_company(company)
    if normalized in boards:
        boards[normalized].status = "dead"
        save(boards)


def prune(target_companies: list[str]) -> None:
    """Remove board entries whose company is not in the target watchlist.

    An empty watchlist prunes nothing: it means "no watchlist configured", not
    "drop every board", and reading it the other way emptied the whole store on
    every GET of the agent config.
    """
    if not target_companies:
        return
    boards = load()
    normalized_targets = {_normalize_company(name) for name in target_companies}

    # Filter to only keep boards for companies still on the watchlist
    pruned = {k: v for k, v in boards.items() if k in normalized_targets}

    if len(pruned) != len(boards):
        save(pruned)
