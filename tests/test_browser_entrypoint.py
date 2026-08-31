"""The viewport must survive a viewer disconnecting.

x11vnc serves one client and exits unless -forever is passed. The viewport is
opened and closed once per attended sign-in, so without it the first Done
leaves nothing listening on 5900 and every later session fails with the app's
relay refusing — for the life of the container, which reports healthy
throughout.
"""

from __future__ import annotations

import re
from pathlib import Path

ENTRYPOINT = Path("browser/entrypoint.sh").read_text()


def x11vnc_command() -> str:
    match = re.search(r"^x11vnc .*$", ENTRYPOINT, re.MULTILINE)
    assert match, "browser/entrypoint.sh no longer starts x11vnc"
    return match.group(0)


def test_x11vnc_serves_more_than_one_viewer():
    assert "-forever" in x11vnc_command()


def test_x11vnc_lets_a_reconnect_join_rather_than_evict():
    assert "-shared" in x11vnc_command()
