"""daily-apply.sh must abort early, with an explicit reason, when
AGENT_API_TOKEN is empty: the agent gets its credentials only from the app.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "agent" / "daily-apply.sh"


def _run(tmp_path: Path, token: str) -> subprocess.CompletedProcess:
    harness = tmp_path / "cli.js"
    harness.write_text("")
    runbook = tmp_path / "RUNBOOK.md"
    runbook.write_text("")
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HARNESS_CLI": str(harness),
        "RUNBOOK": str(runbook),
        "RUN_LOG_DIR": str(tmp_path),
        "TRUTHCV_RUN_ID": "t1",
        "AGENT_API_TOKEN": token,
    }
    return subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_empty_token_aborts_with_reason(tmp_path):
    result = _run(tmp_path, "")
    assert result.returncode == 1
    assert "AGENT_API_TOKEN" in (tmp_path / "t1.reason").read_text()


def test_token_set_passes_the_token_precondition(tmp_path):
    """With a token the run gets past the precondition: the log shows no
    missing-token abort (it fails later on jq/browser, which is fine)."""
    _run(tmp_path, "tok")
    logs = "".join(p.read_text() for p in tmp_path.iterdir() if p.is_file())
    assert "daily-apply run" in logs
    assert "AGENT_API_TOKEN is not set" not in logs
