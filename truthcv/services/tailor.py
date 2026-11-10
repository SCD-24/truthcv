"""Posting tailoring, lifted out of the route handler."""

from __future__ import annotations

import truthcv.engines.tailor as _tailor_engine
import truthcv.domain.truth as _truth
from truthcv.integrations.providers.base import ProviderError
from truthcv.services.errors import BadGateway
from truthcv.infra.storage import data_dir


def tailor_posting(posting: str, provider_factory) -> dict:
    """Tailor the stored Truth to ``posting`` and remember the posting text.

    Exists so the route only supplies the provider factory. Raises BadGateway
    on any provider/LLM failure; on success writes ``posting.txt`` and returns
    ``{"keywords", "inferences"}``.
    """
    try:
        result = _tailor_engine.tailor(posting, _truth.load(), provider_factory)
    except ProviderError as e:
        raise BadGateway(str(e)) from e
    except Exception as e:  # noqa: BLE001 — surface upstream LLM/SDK errors cleanly
        raise BadGateway(
            f"The language model call failed: {type(e).__name__}: {e}"
        ) from e
    (data_dir() / "posting.txt").write_text(posting, encoding="utf-8")
    return {"keywords": result["keywords"], "inferences": result["inferences"]}
