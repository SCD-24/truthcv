"""Data-volume path helpers shared by every store."""

from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    """The mounted data volume (env DATA_DIR, default ./data)."""
    d = Path(os.environ.get("DATA_DIR", "./data"))
    d.mkdir(parents=True, exist_ok=True)
    return d
