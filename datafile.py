"""Safe read-modify-write for the JSON records on the shared data volume.

The stores under ``screening/`` and ``applications/`` each hold a whole list in
one JSON file and rewrite it in full. Two things make that unsafe as soon as
more than one writer exists, and both are fixed here rather than in each store:

* **A shared temp name.** Writing through a fixed ``<name>.tmp`` means two
  writers open, truncate and rename the *same* scratch file: the second
  truncates the first's buffer, and whichever renames second gets
  ``FileNotFoundError`` because the source is already gone. Measured on this
  code before the fix: two threads writing 40 records each onto a 20-record
  file finished with 64 of the expected 100 records and 34 raised renames.
  ``atomic_write_text`` gives every write its own temp file in the destination
  directory, so concurrent writers cannot interfere.

* **An unguarded load-modify-write.** Even with per-writer temp files, two
  writers that both load the list, each append one record, and both write back
  leave only one of the two records. ``locked`` serialises the whole
  read-modify-write against an advisory lock on a sidecar file, so a writer
  that starts mid-cycle waits for the current one to finish.

The lock is ``fcntl.flock`` on a ``<name>.lock`` sidecar. It is advisory and
Linux-local, which is exactly the scope needed: every writer is a thread in the
``app`` container or a process sharing that bind mount. It is deliberately not
used for reads — a reader either sees the pre-rename file or the post-rename
one, never a partial write, because ``os.replace`` is atomic.
"""

from __future__ import annotations

import fcntl
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path


def _umask() -> int:
    """The process umask. Readable only by temporarily setting it back."""
    current = os.umask(0)
    os.umask(current)
    return current


def atomic_write_text(path: Path, text: str) -> None:
    """Replace ``path`` with ``text`` via a temp file unique to this write.

    The temp file is created in the destination's own directory so the final
    ``os.replace`` stays on one filesystem and is therefore atomic. It is
    removed on any failure, so a raising write leaves no debris and never
    leaves ``path`` partially written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        # `os.replace` keeps the TEMP file's mode, and `mkstemp` deliberately
        # creates at 0600. Without this the first write silently made the data
        # file owner-only: these live on a bind mount shared with the host, and
        # a 0600 root-owned file is unreadable to the user's own tooling.
        # An existing file's mode is preserved; a new one gets 0644 less umask.
        try:
            os.chmod(tmp_name, os.stat(path).st_mode & 0o7777)
        except FileNotFoundError:
            os.chmod(tmp_name, 0o644 & ~_umask())
        os.replace(tmp_name, path)
    except BaseException:
        # Best-effort cleanup: the replace never happened, so `path` still holds
        # the previous complete contents and only the scratch file is orphaned.
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


@contextmanager
def locked(path: Path):
    """Hold an exclusive advisory lock covering ``path`` for the block's duration.

    Wrap the *whole* load-modify-write, not just the write: the point is that no
    other writer may load the list between this caller's load and its write, or
    that caller's changes are silently dropped.

    The lock lives on a ``<name>.lock`` sidecar rather than on the data file
    itself, so it is never destroyed by the ``os.replace`` that swaps the data
    file underneath it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    handle = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        # Released implicitly by the close, but unlocking first keeps the
        # ordering explicit for anyone reading this.
        try:
            fcntl.flock(handle, fcntl.LOCK_UN)
        finally:
            os.close(handle)
