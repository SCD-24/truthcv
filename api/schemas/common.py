"""Request/response models with camelCase JSON aliases.

Python stays snake_case internally; the wire contract matches exactly what the
frontend client (web/src/api/types.ts) expects.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
