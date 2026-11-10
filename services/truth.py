"""Truth workflows lifted out of the route handlers: CV upload ingest, LLM
extraction and the partial merge of profile answers.

Names the tests patch (document extraction and the persist_* writers) are
looked up through their source modules at call time.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

import truth.answers as _answers
import truth.document as _document
import truth.pdf as _pdf
import truth.store as _truth_store
from providers.base import LLMProvider, ProviderError
from services.errors import BadGateway, BadRequest
from services.truth_extract import build_truth_from_text
from truth.answers import Answers
from truth.model import Truth
from truth.pdf import DocumentExtractError

# Guards the persist_source_text/persist_source_hash/persist_profile triple below:
# uploads run in asyncio.to_thread, so two concurrent /upload requests could
# otherwise interleave their writes (e.g. source text from one request paired
# with the hash/profile of another).
_UPLOAD_PERSIST_LOCK = threading.Lock()


def ingest_upload(filename: str, data: bytes) -> None:
    """Extract text from an uploaded file and persist it, off the event loop.

    Exists so the route and any other caller share one persist sequence.
    Raises BadRequest (with the extractor's message) on an unsupported or
    unparseable file. The size cap stays in the HTTP handler.
    """
    try:
        ext = _document.extension_for(filename)
        text = _document.extract_document_text(filename, data)
        with _UPLOAD_PERSIST_LOCK:
            _pdf.persist_source_text(text)
            _truth_store.persist_source_hash(text)  # keyed cache: lets /extract skip a repeat LLM pass
            _pdf.persist_profile(data, ext)
    except DocumentExtractError as e:
        raise BadRequest(str(e)) from e


def extract_truth(provider_factory: Callable[[], LLMProvider]) -> Truth:
    """Run the LLM extraction over the stored CV text and return the Truth.

    Exists so the route only chooses the provider. Takes a factory, not a
    provider, so a missing CV is reported (BadRequest) before any provider
    lookup can fail. Raises BadGateway on any provider lookup/LLM failure.
    """
    text = _pdf.load_source_text()
    if not text.strip():
        raise BadRequest("Upload your CV before extracting.")
    try:
        return build_truth_from_text(text, provider_factory())
    except ProviderError as e:
        raise BadGateway(str(e)) from e
    except Exception as e:  # noqa: BLE001 — surface upstream LLM/SDK errors cleanly
        raise BadGateway(
            f"The language model call failed: {type(e).__name__}: {e}"
        ) from e


def update_answers(sent: dict) -> Answers:
    """Merge only the fields the client actually sent onto the stored answers.

    Omitted fields must survive untouched — the wizard's field-by-field save
    flow means most PUTs carry a strict subset of the 21 fields, and treating
    absence the same as "clear this" would silently blank the rest.
    """
    merged = _answers.load().to_dict()
    merged.update(sent)
    return _answers.save(Answers.from_dict(merged))
