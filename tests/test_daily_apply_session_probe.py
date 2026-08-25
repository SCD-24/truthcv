"""The eviction probe must treat a non-2xx response as a failure, not as data.

The four text-presence tests in test_daily_apply_eviction.py cannot catch this:
they pass whether or not the status code is checked. This one runs the actual
node snippet from daily-apply.sh against a real server.
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

SCRIPT = Path("agent/daily-apply.sh").read_text()


def _extract_node_snippet() -> str:
    """Pull the node -e program out of session_request in daily-apply.sh.

    The script also has an earlier, unrelated `node -e '...' "$BROWSER_MCP_URL"`
    snippet (probe_browser); anchoring on `session_request() {` first keeps a
    non-greedy match from spanning both blocks and grabbing the wrong one.
    """
    session_request_start = SCRIPT.index("session_request() {")
    match = re.search(r"node -e '\n(.*?)\n\s*' \"\$1\" \"\$2\"", SCRIPT[session_request_start:], re.S)
    assert match, "could not find the session_request node snippet"
    return match.group(1)


class _Handler(BaseHTTPRequestHandler):
    status = 200
    body = b'{"open":false}'

    def do_GET(self):
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *args):
        pass


@pytest.fixture()
def server():
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()


def _run(port: int) -> subprocess.CompletedProcess:
    snippet = _extract_node_snippet().replace('host: "browser"', 'host: "127.0.0.1"')
    return subprocess.run(
        ["node", "-e", snippet, "GET", "/session"],
        capture_output=True,
        # Inherit the caller's PATH rather than hard-coding one: node is at
        # /usr/local/bin on the CI runner and in the toolcache under
        # actions/setup-node, so "/usr/bin:/bin" would not find it.
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "SESSION_SERVER_PORT": str(port),
            "AGENT_API_TOKEN": "t",
        },
    )


def test_a_200_response_is_forwarded(server):
    _Handler.status = 200
    _Handler.body = b'{"open":true}'
    result = _run(server.server_port)
    assert result.returncode == 0
    assert b'"open":true' in result.stdout


def test_a_403_is_a_failure_not_data(server):
    """A 403 must not read as 'no session open' — that silently skips eviction."""
    _Handler.status = 403
    _Handler.body = b'{"detail":"Forbidden"}'
    result = _run(server.server_port)
    assert result.returncode != 0


def test_a_500_is_a_failure(server):
    _Handler.status = 500
    _Handler.body = b"boom"
    result = _run(server.server_port)
    assert result.returncode != 0
