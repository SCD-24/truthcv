from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class GmailSyncState:
    last_synced_at: float = 0
    processed_message_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict | None) -> "GmailSyncState":
        raw = raw or {}
        return cls(
            last_synced_at=float(raw.get("last_synced_at") or 0),
            processed_message_ids=[str(v) for v in raw.get("processed_message_ids") or []],
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GmailSuggestion:
    id: str = ""
    application_id: str = ""
    application_label: str = ""
    sender: str = ""
    sender_email: str = ""
    subject: str = ""
    date: str = ""
    snippet: str = ""
    classification: str = ""
    suggested_status: str = ""
    match_confidence: str = ""
    match_evidence: list[str] = field(default_factory=list)
    state: str = "pending"

    @classmethod
    def from_dict(cls, raw: dict | None) -> "GmailSuggestion":
        raw = raw or {}
        return cls(
            id=str(raw.get("id", "")),
            application_id=str(raw.get("application_id", "")),
            application_label=str(raw.get("application_label", "")),
            sender=str(raw.get("sender", "")),
            sender_email=str(raw.get("sender_email", "")),
            subject=str(raw.get("subject", "")),
            date=str(raw.get("date", "")),
            snippet=str(raw.get("snippet", "")),
            classification=str(raw.get("classification", "")),
            suggested_status=str(raw.get("suggested_status", "")),
            match_confidence=str(raw.get("match_confidence", "")),
            match_evidence=[str(v) for v in raw.get("match_evidence") or []],
            state=str(raw.get("state", "pending")),
        )

    def to_dict(self) -> dict:
        return asdict(self)
