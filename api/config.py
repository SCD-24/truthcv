"""Runtime configuration, read from the environment per the TruthCV spec."""

from __future__ import annotations

import os
from pathlib import Path


def static_dir() -> Path:
    """Where the built frontend bundle lives (web/ builds to api/static)."""
    return Path(os.environ.get("STATIC_DIR", str(Path(__file__).parent / "static")))


def cors_origins() -> list[str]:
    raw = os.environ.get("CORS_ORIGINS", "http://localhost:5173")
    return [o.strip() for o in raw.split(",") if o.strip()]


def port() -> int:
    return int(os.environ.get("PORT", "8080"))


def encryption_key() -> str:
    """Fernet master key from the environment (empty if unset)."""
    return os.environ.get("ENCRYPTION_KEY", "").strip()


def secrets_path() -> Path:
    from truth.store import data_dir

    return data_dir() / "secrets.enc"


def profile_pdf_path() -> Path:
    from truth.store import data_dir

    return data_dir() / "profile.pdf"
