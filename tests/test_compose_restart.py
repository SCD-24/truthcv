"""Every long-running service must survive a host reboot.

Docker only restarts a container on daemon start when it carries a restart
policy, and `depends_on` does not apply — it orders `docker compose up`,
nothing else. A partial recovery is worse than none: `agent` waking on
schedule without `app` does not simply idle, it aborts each run on the
TRUTHCV_MCP_URL precondition, so the failure surfaces as broken runs rather
than an obviously stopped stack.

`ollama` is excluded deliberately: it sits behind a compose profile and is
started on purpose, not as part of the default stack.
"""

from __future__ import annotations

from pathlib import Path

import yaml

COMPOSE = yaml.safe_load(Path("docker-compose.yml").read_text())

ALWAYS_ON = ("app", "browser", "agent")


def test_every_default_service_restarts_after_a_reboot():
    missing = [
        name
        for name in ALWAYS_ON
        if COMPOSE["services"][name].get("restart") != "unless-stopped"
    ]
    assert not missing, f"services without restart: unless-stopped: {missing}"


def test_the_profiled_service_is_not_covered():
    """`ollama` is opt-in; it should not be dragged up by a reboot."""
    assert "profiles" in COMPOSE["services"]["ollama"]
    assert "restart" not in COMPOSE["services"]["ollama"]
