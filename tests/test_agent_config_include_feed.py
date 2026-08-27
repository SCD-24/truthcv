"""agent/agent-config.js asks for the job-board feed on job_config only.

Driven against a real HTTP server rather than grepped for, because the property
under test is which URL the fetch actually requests. The regression it guards:
include_feed on the scheduler's polls (mode/enabled/run_at/run_days), which
would make the app call a third-party API every time the supervisor checks
whether it is time to run.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

SCRIPT = Path("agent/agent-config.js").resolve()

# Resolved rather than spelled "node", because the environment handed to the
# subprocess is not the caller's: on CI node lives in a toolcache directory, so
# a hardcoded PATH finds nothing while shutil.which (which reads the real PATH)
# says it is installed — the skip does not fire and every test errors.
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

CONFIG = {
    "mode": "full",
    "enabled": True,
    "runAt": ["09:00"],
    "runDays": ["mon"],
    "profiles": [{"name": "p"}],
    "targetCompanies": [],
    "companyBoards": [],
    "searchQueries": [],
    "feedPostings": [
        {"profile": "p", "source": "remoterocketship", "title": "T", "url": "https://x.example/1"}
    ],
    "feedError": "boom",
}


@pytest.fixture()
def server():
    """A stub /api/agent/config that records every path it was asked for."""
    paths: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 — BaseHTTPRequestHandler's interface
            paths.append(self.path)
            body = json.dumps(CONFIG).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}", paths
    finally:
        httpd.shutdown()
        httpd.server_close()


def _run(base: str, field: str) -> subprocess.CompletedProcess:
    # The caller's environment is inherited so node finds its own runtime;
    # TRUTHCV_MCP_URL is the only thing this path reads from it.
    env = {**os.environ, "TRUTHCV_MCP_URL": base}
    return subprocess.run(
        [NODE, str(SCRIPT), field],
        env=env,
        capture_output=True,
        text=True,
    )


def test_job_config_requests_the_feed(server):
    base, paths = server
    result = _run(base, "job_config")
    assert result.returncode == 0, result.stderr
    assert paths == ["/api/agent/config?include_feed=true"]


@pytest.mark.parametrize("field", ["mode", "enabled", "run_at", "run_days"])
def test_scheduler_polls_do_not_request_the_feed(server, field):
    base, paths = server
    result = _run(base, field)
    assert result.returncode == 0, result.stderr
    assert paths == ["/api/agent/config"]


def test_job_config_survives_a_response_slower_than_the_scheduler_poll_timeout():
    """job_config is the one field the app may spend time on — it pulls the
    feed, bounded server-side at jobfeeds.remoterocketship.BUDGET_SECONDS. The
    5s the scheduler's polls use would time out on a slow-but-working feed, and
    daily-apply.sh aborts the whole run on a failed config fetch rather than
    losing only the feed. Driven with a real slow server, because the property
    is what the socket does, not what the source says."""
    delay = 6.0

    class Slow(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            time.sleep(delay)
            body = json.dumps(CONFIG).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Slow)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{httpd.server_port}"
        assert _run(base, "job_config").returncode == 0
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_job_config_passes_the_feed_through_to_the_shell(server):
    base, _ = server
    payload = json.loads(_run(base, "job_config").stdout)
    assert payload["feedPostings"][0]["url"] == "https://x.example/1"
    assert payload["feedError"] == "boom"


def test_a_server_that_omits_the_feed_fields_still_yields_valid_job_config(server):
    """An older app image serving no feedPostings must not crash the agent: the
    fields default to empty rather than undefined, so the shell's jq sees a
    shape it can read."""
    base, _ = server
    CONFIG.pop("feedPostings")
    CONFIG.pop("feedError")
    try:
        payload = json.loads(_run(base, "job_config").stdout)
    finally:
        CONFIG["feedPostings"] = [
            {"profile": "p", "source": "remoterocketship", "title": "T", "url": "https://x.example/1"}
        ]
        CONFIG["feedError"] = "boom"
    assert payload["feedPostings"] == []
    assert payload["feedError"] == ""
