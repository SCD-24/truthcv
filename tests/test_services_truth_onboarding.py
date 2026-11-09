"""Unit tests for services.truth, services.onboarding and services.tailor."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import services.onboarding as onboarding
import services.tailor as tailor_svc
import services.truth as truth_svc
from providers.base import ProviderError
from services.errors import BadGateway, BadRequest
from truth.pdf import DocumentExtractError


def test_ingest_upload_persists_in_order(monkeypatch):
    calls = []
    monkeypatch.setattr(truth_svc._document, "extension_for", lambda f: ".pdf")
    monkeypatch.setattr(truth_svc._document, "extract_document_text", lambda f, d: "txt")
    monkeypatch.setattr(truth_svc._pdf, "persist_source_text", lambda t: calls.append(("text", t)))
    monkeypatch.setattr(truth_svc._truth_store, "persist_source_hash", lambda t: calls.append(("hash", t)))
    monkeypatch.setattr(truth_svc._pdf, "persist_profile", lambda d, e: calls.append(("profile", d, e)))
    truth_svc.ingest_upload("cv.pdf", b"x")
    assert calls == [("text", "txt"), ("hash", "txt"), ("profile", b"x", ".pdf")]


def test_ingest_upload_extract_error_is_bad_request(monkeypatch):
    def boom(f, d):
        raise DocumentExtractError("unsupported")

    monkeypatch.setattr(truth_svc._document, "extension_for", lambda f: ".zip")
    monkeypatch.setattr(truth_svc._document, "extract_document_text", boom)
    with pytest.raises(BadRequest, match="unsupported"):
        truth_svc.ingest_upload("a.zip", b"")


def test_extract_truth_empty_source(monkeypatch):
    monkeypatch.setattr(truth_svc._pdf, "load_source_text", lambda: "  ")
    with pytest.raises(BadRequest) as e:
        truth_svc.extract_truth(MagicMock())
    assert str(e.value) == "Upload your CV before extracting."


@pytest.mark.parametrize(
    "exc,text",
    [
        (ProviderError("no key"), "no key"),
        (ValueError("bad"), "The language model call failed: ValueError: bad"),
    ],
)
def test_extract_truth_failure_is_bad_gateway(monkeypatch, exc, text):
    monkeypatch.setattr(truth_svc._pdf, "load_source_text", lambda: "cv")

    def boom(t, p):
        raise exc

    monkeypatch.setattr(truth_svc, "build_truth_from_text", boom)
    with pytest.raises(BadGateway) as e:
        truth_svc.extract_truth(MagicMock())
    assert str(e.value) == text


def test_extract_truth_returns_truth(monkeypatch):
    sentinel = object()
    provider = object()
    monkeypatch.setattr(truth_svc._pdf, "load_source_text", lambda: "cv")
    monkeypatch.setattr(truth_svc, "build_truth_from_text", lambda t, p: sentinel if p is provider else None)
    assert truth_svc.extract_truth(provider) is sentinel


def test_update_answers_merges_only_sent(monkeypatch):
    from truth.answers import Answers

    saved = []
    monkeypatch.setattr(truth_svc._answers, "load", lambda: Answers(phone="1", name="n"))
    monkeypatch.setattr(truth_svc._answers, "save", lambda a: saved.append(a) or a)
    result = truth_svc.update_answers({"phone": "2"})
    assert (result.phone, result.name) == ("2", "n")
    assert saved == [result]


def _fake_store(monkeypatch, provider_ready, reviewed):
    st = onboarding._store
    monkeypatch.setattr(st, "provider_ready", lambda: provider_ready)
    monkeypatch.setattr(st, "ensure_initialized", lambda: None)
    state = {"s": st.OnboardingState(cv_reviewed_at=reviewed)}
    monkeypatch.setattr(st, "load", lambda: state["s"])
    monkeypatch.setattr(st, "save", lambda s: state.update(s=s))
    return state


def test_onboarding_get_state_complete(monkeypatch):
    _fake_store(monkeypatch, True, "2026-01-01")
    monkeypatch.setattr(onboarding._pdf, "has_profile", lambda: True)
    assert onboarding.get_state() == {
        "provider_done": True,
        "has_profile": True,
        "cv_reviewed_at": "2026-01-01",
        "tour_seen_at": None,
        "complete": True,
    }


def test_onboarding_update_merges_and_recomputes(monkeypatch):
    state = _fake_store(monkeypatch, True, None)
    monkeypatch.setattr(onboarding._pdf, "has_profile", lambda: True)
    out = onboarding.update_state({"cv_reviewed_at": "t"})
    assert state["s"].cv_reviewed_at == "t" and state["s"].tour_seen_at is None
    assert out["complete"] is True


def test_tailor_posting_writes_posting_and_shapes(monkeypatch, tmp_path):
    monkeypatch.setattr(tailor_svc, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(tailor_svc._truth, "load", lambda: "T")
    factory = object()

    def fake(posting, truth, f):
        assert (posting, truth, f) == ("job", "T", factory)
        return {"keywords": ["k"], "inferences": [], "extra": 1}

    monkeypatch.setattr(tailor_svc._tailor_engine, "tailor", fake)
    assert tailor_svc.tailor_posting("job", factory) == {"keywords": ["k"], "inferences": []}
    assert (tmp_path / "posting.txt").read_text() == "job"


@pytest.mark.parametrize(
    "exc,text",
    [
        (ProviderError("nope"), "nope"),
        (RuntimeError("x"), "The language model call failed: RuntimeError: x"),
    ],
)
def test_tailor_posting_failure_is_bad_gateway(monkeypatch, tmp_path, exc, text):
    monkeypatch.setattr(tailor_svc, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(tailor_svc._truth, "load", lambda: "T")

    def boom(*a):
        raise exc

    monkeypatch.setattr(tailor_svc._tailor_engine, "tailor", boom)
    with pytest.raises(BadGateway) as e:
        tailor_svc.tailor_posting("job", object())
    assert str(e.value) == text
    assert not (tmp_path / "posting.txt").exists()
