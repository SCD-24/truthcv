"""The services layer: framework-free workflows shared by the HTTP and MCP adapters.

Nothing under ``services/`` imports FastAPI (or anything else HTTP-specific).
Each workflow is a plain function taking explicit arguments and returning a
plain result (or raising one of ``services.errors``' domain exceptions); the
adapters in ``api/routes.py`` and ``agenttools/`` translate to and from their
own wire formats.
"""

from __future__ import annotations
