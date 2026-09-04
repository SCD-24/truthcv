"""Preflight must fail fast at boot on real misconfiguration, and must never
treat a missing LLM credential as fatal - daily-apply.sh enforces credentials
per run, not this script at container start.

These tests extract log(), validate_run_at(), report_credentials() and
preflight() straight out of agent/entrypoint.sh (everything from the log()
definition up to, but not including, the "# --- The run" marker) and execute
them under `bash -c` with a controlled environment, without ever running
main() or touching a real daily-apply.sh.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ENTRYPOINT_PATH = Path("agent/entrypoint.sh")
ENTRYPOINT = ENTRYPOINT_PATH.read_text()

_START_MARKER = "log() {"
_END_MARKER = "# --- The run"


def _extract_preflight_functions() -> str:
    start = ENTRYPOINT.index(_START_MARKER)
    end = ENTRYPOINT.index(_END_MARKER)
    assert start < end, "agent/entrypoint.sh markers out of order"
    return ENTRYPOINT[start:end]


PREFLIGHT_FUNCTIONS = _extract_preflight_functions()


def run_preflight(tmp_path: Path, extra_env: dict[str, str]) -> subprocess.CompletedProcess:
    """Run preflight() with a minimal, controlled environment.

    extra_env may set DAILY_APPLY to override the default (a writable, "
    executable dummy script), plus any credential vars under test.
    """
    daily_apply = tmp_path / "daily-apply.sh"
    daily_apply.write_text("#!/usr/bin/env bash\nexit 0\n")
    os.chmod(daily_apply, 0o755)

    env = {
        "PATH": os.environ.get("PATH", ""),
        "RUN_AT": "09:00",
        "AGENT_BROWSER_DRIVER": "browser",
        "DAILY_APPLY": str(daily_apply),
    }
    env.update(extra_env)

    script = PREFLIGHT_FUNCTIONS + "\npreflight\nexit $?\n"
    return subprocess.run(
        ["bash", "-c", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_preflight_no_credential_vars(tmp_path):
    result = run_preflight(tmp_path, {})
    assert result.returncode == 0
    assert "WARN: no LLM credential" in result.stdout


def test_preflight_with_agent_api_token(tmp_path):
    result = run_preflight(tmp_path, {"AGENT_API_TOKEN": "test-token"})
    assert result.returncode == 0
    assert "fetched from app" in result.stdout


def test_preflight_with_agent_llm_api_key(tmp_path):
    result = run_preflight(tmp_path, {"AGENT_LLM_API_KEY": "test-key"})
    assert result.returncode == 0
    assert "container-level" in result.stdout


def test_preflight_with_ollama_base_url(tmp_path):
    result = run_preflight(
        tmp_path,
        {
            "AGENT_LLM_PROVIDER": "ollama",
            "AGENT_LLM_BASE_URL": "http://ollama:11434",
        },
    )
    assert result.returncode == 0
    assert "container-level" in result.stdout


def test_preflight_daily_apply_not_executable(tmp_path):
    result = run_preflight(tmp_path, {"DAILY_APPLY": "/nonexistent/path/daily-apply.sh"})
    assert result.returncode == 1


def test_no_anthropic_api_key_in_script():
    assert "ANTHROPIC_API_KEY" not in ENTRYPOINT
