"""Background job runner: submit callables to a bounded thread pool and
poll their status through an in-memory registry.

See ``jobs.model`` for the ``Job`` record shape and ``jobs.runner`` for
``submit``/``get``/``list_jobs``.
"""

from __future__ import annotations

from .model import (
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    Job,
)
from .runner import get, job_to_dict, list_jobs, submit

__all__ = [
    "Job",
    "STATUS_PENDING",
    "STATUS_RUNNING",
    "STATUS_DONE",
    "STATUS_FAILED",
    "get",
    "job_to_dict",
    "list_jobs",
    "submit",
]
