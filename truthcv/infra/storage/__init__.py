"""The storage leaf: owns the data path and safe file I/O for the volume."""

from __future__ import annotations

from .atomic import atomic_write_text, locked
from .paths import data_dir

__all__ = ["data_dir", "atomic_write_text", "locked"]
