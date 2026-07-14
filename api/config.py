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


# Credential/secret config moved to the neutral `secretstore` package so the
# provider layer can reach it without importing api. Re-exported here for the
# existing `from api.config import encryption_key/secrets_path` callers.
from secretstore import encryption_key, secrets_path  # noqa: E402,F401


def profile_pdf_path() -> Path:
    from truth.store import data_dir

    return data_dir() / "profile.pdf"
