"""HTTP client for the agent supervisor.js control server.

Lives in services so the run lifecycle logic can reach the supervisor without
importing the API layer; it raises ``services.errors`` types instead of
``HTTPException`` and the global handler maps them back to the same statuses.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from services.errors import BadGateway, InternalError, Unavailable


def agent_control_url(path: str) -> str:
    """Build the supervisor.js control URL from env, defaulting port 9099."""
    port = os.environ.get("AGENT_CONTROL_PORT", "9099")
    return f"http://agent:{port}{path}"


def forward_to_supervisor(path: str, method: str = "GET") -> dict:
    """Forward a request to the agent supervisor.js control server.

    Raises Unavailable (503) when the agent is unreachable, BadGateway (502)
    when it answered with an error status (403 = token mismatch), and
    InternalError (500) when this service has no AGENT_API_TOKEN to send.
    These are kept distinct on purpose: they have three different fixes and
    used to share one message.
    """
    token = os.environ.get("AGENT_API_TOKEN", "").strip()
    # An unset shared secret is not a network problem and never becomes one by
    # retrying: the supervisor rejects every request and the operator has no
    # way to tell that from a container that is down. Fail here, before the
    # dial, so the message names the actual cause.
    if not token:
        raise InternalError(
            "AGENT_API_TOKEN is not set on the app service, so the agent "
            "will reject every request. Set it in .env (the same value for "
            "app, agent and browser) and restart the stack."
        )

    url = agent_control_url(path)
    req = urllib.request.Request(
        url,
        method=method,
        headers={"X-Agent-Token": token},
        data=b"" if method == "POST" else None,
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        # MUST be caught before URLError: HTTPError subclasses it, so a single
        # URLError handler renders a 403 as "Agent service unreachable" — the
        # one message that sends the operator to look at the network when the
        # supervisor answered perfectly well and refused the token.
        if exc.code in (401, 403):
            raise BadGateway(
                f"Agent service refused the request (HTTP {exc.code}): the app "
                "and the agent container disagree on AGENT_API_TOKEN. Make both "
                "match in .env and restart the stack."
            ) from exc
        raise BadGateway(f"Agent service returned HTTP {exc.code} for {path}") from exc
    except urllib.error.URLError as exc:
        raise Unavailable("Agent service unreachable") from exc
