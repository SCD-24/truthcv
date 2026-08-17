"""The rendered log must be readable by the human it exists for.

`tempfile.mkstemp` creates 0600 and `os.replace` preserves that mode, so
without an explicit widening the log written by the container (as root) is
unreadable to the user on the host — a plain-text account outside the
application that nobody outside the application can read.
"""

import stat

from applications.log_render import write_log
from applications.model import Application


def test_rendered_log_is_world_readable(tmp_path):
    """0644, not mkstemp's default 0600."""
    target = write_log([Application(id="aaa111aaa111", company="Acme")], tmp_path / "L.md")
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o644, f"expected 0644, got {oct(mode)}"


def test_rendered_log_mode_survives_a_rewrite(tmp_path):
    """Re-rendering over an existing log does not narrow it again."""
    target = tmp_path / "L.md"
    write_log([Application(id="aaa111aaa111", company="Acme")], target)
    write_log([Application(id="bbb222bbb222", company="Beta")], target)
    assert stat.S_IMODE(target.stat().st_mode) == 0o644
