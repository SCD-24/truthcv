"""Data model for background jobs tracked by ``jobs.runner``."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

# Job lifecycle states. Plain string constants (not an Enum) to match this
# repo's existing style of module-level constants for fixed value sets.
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"

STATUSES = (STATUS_PENDING, STATUS_RUNNING, STATUS_DONE, STATUS_FAILED)


@dataclass
class Job:
    """Tracked state for one background job.

    ``status`` is one of the module-level STATUS_* constants. ``result`` is
    populated only once ``status`` is STATUS_DONE; ``error`` only once it is
    STATUS_FAILED. ``progress`` is a caller-defined 0..1 fraction that a long
    running job can update while it works; it defaults to 0.0 and is not
    otherwise interpreted here.
    """

    id: str
    kind: str
    status: str = STATUS_PENDING
    progress: float = 0.0
    result: Any = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
