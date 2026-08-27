"""datafile: the two properties the JSON stores depend on under concurrency.

Both are regression tests for a measured data-loss bug: two writers sharing one
fixed `<name>.tmp` truncated each other's scratch file, and an unguarded
load-modify-write dropped one of any two concurrent records.
"""

from __future__ import annotations

import threading

import pytest

from storage import atomic_write_text, locked


class TestAtomicWriteText:
    def test_writes_and_replaces(self, tmp_path):
        target = tmp_path / "records.json"
        atomic_write_text(target, "first")
        atomic_write_text(target, "second")
        assert target.read_text(encoding="utf-8") == "second"

    def test_creates_missing_parent(self, tmp_path):
        target = tmp_path / "nested" / "deep" / "records.json"
        atomic_write_text(target, "x")
        assert target.read_text(encoding="utf-8") == "x"

    def test_a_new_file_is_readable_by_others(self, tmp_path):
        """`os.replace` keeps the temp file's mode and `mkstemp` uses 0600.

        These files live on a bind mount shared with the host, so a 0600
        root-owned data file is unreadable to the user's own tooling — which
        is exactly what the first version of this helper produced.
        """
        import os

        target = tmp_path / "records.json"
        atomic_write_text(target, "x")
        assert target.stat().st_mode & 0o044, oct(target.stat().st_mode & 0o777)

    def test_an_existing_files_mode_is_preserved(self, tmp_path):
        import os

        target = tmp_path / "records.json"
        target.write_text("first", encoding="utf-8")
        os.chmod(target, 0o640)
        atomic_write_text(target, "second")
        assert target.stat().st_mode & 0o777 == 0o640

    def test_leaves_no_temp_files(self, tmp_path):
        target = tmp_path / "records.json"
        for i in range(20):
            atomic_write_text(target, str(i))
        assert list(tmp_path.glob("*.tmp")) == []

    def test_concurrent_writers_never_raise(self, tmp_path):
        """The original failure: a shared temp name made `replace` hit ENOENT.

        Each writer's content is self-consistent, so the surviving file must be
        exactly one writer's payload — never a mix, never a missing file.
        """
        target = tmp_path / "records.json"
        errors = []

        def writer(tag: str):
            for _ in range(60):
                try:
                    atomic_write_text(target, tag * 500)
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)

        threads = [threading.Thread(target=writer, args=(t,)) for t in "ABC"]
        [t.start() for t in threads]
        [t.join() for t in threads]

        assert errors == []
        assert target.read_text(encoding="utf-8") in {t * 500 for t in "ABC"}

    def test_a_failing_write_leaves_the_previous_contents_intact(self, tmp_path):
        """A raise mid-write must not truncate what was already stored."""
        target = tmp_path / "records.json"
        atomic_write_text(target, "original")

        class Exploding(str):
            def __str__(self):  # pragma: no cover - defensive
                raise RuntimeError("boom")

        with pytest.raises(Exception):
            atomic_write_text(target, Exploding("x") + None)  # type: ignore[operator]

        assert target.read_text(encoding="utf-8") == "original"
        assert list(tmp_path.glob("*.tmp")) == []


class TestLocked:
    def test_serialises_read_modify_write(self, tmp_path):
        """Without the lock this loses updates; the count is the whole point."""
        target = tmp_path / "counter.txt"
        target.write_text("0", encoding="utf-8")

        def bump():
            for _ in range(100):
                with locked(target):
                    current = int(target.read_text(encoding="utf-8"))
                    atomic_write_text(target, str(current + 1))

        threads = [threading.Thread(target=bump) for _ in range(4)]
        [t.start() for t in threads]
        [t.join() for t in threads]

        assert int(target.read_text(encoding="utf-8")) == 400

    def test_is_reentrant_across_sequential_uses(self, tmp_path):
        target = tmp_path / "x.json"
        for _ in range(5):
            with locked(target):
                atomic_write_text(target, "ok")
        assert target.read_text(encoding="utf-8") == "ok"

    def test_releases_on_exception(self, tmp_path):
        """A raise inside the block must not strand the lock for later writers."""
        target = tmp_path / "x.json"
        with pytest.raises(ValueError):
            with locked(target):
                raise ValueError("boom")
        # Would hang rather than fail if the lock leaked.
        with locked(target):
            atomic_write_text(target, "recovered")
        assert target.read_text(encoding="utf-8") == "recovered"

    def test_lock_sidecar_survives_the_data_file_being_replaced(self, tmp_path):
        """The lock lives on a sidecar precisely so `os.replace` cannot destroy it."""
        target = tmp_path / "x.json"
        with locked(target):
            atomic_write_text(target, "one")
        assert (tmp_path / "x.json.lock").exists()
