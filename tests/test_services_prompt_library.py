"""Unit tests for truthcv.services.prompt_library and the gmail *_and_count helpers."""

from __future__ import annotations

import pytest

from truthcv.services import gmail as gmail_service
from truthcv.services import prompt_library
from truthcv.services.errors import BadRequest, Forbidden


def test_remove_seeded_or_default_is_forbidden(monkeypatch):
    def boom(_id):
        raise ValueError("cannot delete seeded fragment x")

    monkeypatch.setattr(prompt_library, "delete_fragment", boom)
    with pytest.raises(Forbidden, match="seeded fragment x"):
        prompt_library.remove_fragment("x")

    monkeypatch.setattr(
        prompt_library, "delete_preset", lambda _id: (_ for _ in ()).throw(ValueError("cannot delete default preset"))
    )
    with pytest.raises(Forbidden, match="default preset"):
        prompt_library.remove_preset("p")


def test_remove_other_value_error_is_bad_request(monkeypatch):
    def boom(_id):
        raise ValueError("fragment x is referenced by preset p")

    monkeypatch.setattr(prompt_library, "delete_fragment", boom)
    with pytest.raises(BadRequest, match="referenced by preset p"):
        prompt_library.remove_fragment("x")


def test_remove_unknown_id_keeps_key_error(monkeypatch):
    monkeypatch.setattr(prompt_library, "delete_preset", lambda _id: (_ for _ in ()).throw(KeyError(_id)))
    with pytest.raises(KeyError):
        prompt_library.remove_preset("nope")


def test_save_rejected_write_is_forbidden(monkeypatch):
    def boom(_obj):
        raise ValueError("cannot edit seeded fragment x")

    monkeypatch.setattr(prompt_library, "upsert_fragment", boom)
    with pytest.raises(Forbidden, match="cannot edit seeded fragment x"):
        prompt_library.save_fragment("x", "tone", "T", "text")

    monkeypatch.setattr(prompt_library, "upsert_preset", boom)
    with pytest.raises(Forbidden):
        prompt_library.save_preset("p", "P", [], False)


def test_dismiss_and_count_reads_pending_after_dismissal(monkeypatch):
    from truthcv.domain.gmailsync import service as gs

    calls = []
    monkeypatch.setattr(gs, "dismiss", lambda ids: calls.append(("dismiss", ids)) or 2)
    monkeypatch.setattr(gs, "list_pending", lambda limit, offset: calls.append(("pending", limit, offset)) or ([], 5))
    assert gmail_service.dismiss_and_count(["a", "b"]) == (2, 5)
    assert calls == [("dismiss", ["a", "b"]), ("pending", 1, 0)]


def test_accept_and_count_propagates_not_found(monkeypatch):
    from truthcv.domain.gmailsync import service as gs

    def boom(_id):
        raise gs.SuggestionNotFound(_id)

    monkeypatch.setattr(gs, "accept", boom)
    with pytest.raises(gs.SuggestionNotFound):
        gmail_service.accept_and_count("zzz")


def test_accept_and_count_returns_accepted_and_pending(monkeypatch):
    from truthcv.domain.gmailsync import service as gs

    monkeypatch.setattr(gs, "accept", lambda _id: "ACC")
    monkeypatch.setattr(gs, "list_pending", lambda limit, offset: ([], 3))
    assert gmail_service.accept_and_count("s1") == ("ACC", 3)
