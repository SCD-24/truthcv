"""TruthCV API package.

Loads `.env` from the repo root into the process environment on import, so local
runs (`uvicorn api.main:app`, `python -m api.main`) pick up ENCRYPTION_KEY and the
provider config without requiring python-dotenv. Anything already set in the real
environment (shell exports, docker-compose `environment:`) wins over the file.
"""

from __future__ import annotations

import os
from pathlib import Path


def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    try:
        text = env_path.read_text(encoding="utf-8")
    except OSError:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        # Real environment wins; the file only fills what's unset.
        os.environ.setdefault(key, value)


_load_dotenv()
