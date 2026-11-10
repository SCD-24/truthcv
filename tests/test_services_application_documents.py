"""Unit tests for the edited-document save workflows in services.applications."""

from types import SimpleNamespace

import pytest

import services.applications as svc
from render.pdf import RenderUnavailable
from services.errors import NotFound


def _boom(*_a, **_k):
    raise RenderUnavailable("no backend")


def test_render_to_files_reports_partial_and_none(monkeypatch):
    monkeypatch.setattr(svc._render, "render_pdf", lambda *a: None)
    monkeypatch.setattr(svc._render, "render_docx", _boom)
    assert svc.render_to_files("<p>x</p>", "a.pdf", "a.docx") is True
    monkeypatch.setattr(svc._render, "render_pdf", _boom)
    assert svc.render_to_files("<p>x</p>", "a.pdf", "a.docx") is False


@pytest.fixture
def store(monkeypatch):
    calls = []
    fake = SimpleNamespace(
        get=lambda app_id: None if app_id == "missing" else object(),
        save_cv_document=lambda i, h: calls.append(("cv", i, h)) or "APP",
        save_cover_letter_document=lambda i, t: calls.append(("cl", i, t)) or "APP",
        cv_filenames=lambda i: (f"{i}.pdf", f"{i}.docx"),
        cover_letter_filenames=lambda i: (f"{i}-cl.pdf", f"{i}-cl.docx"),
    )
    monkeypatch.setattr(svc, "app_store", fake)
    rendered = []
    monkeypatch.setattr(
        svc, "render_to_files", lambda h, p, d: rendered.append((h, p, d)) or True
    )
    return calls, rendered


@pytest.mark.parametrize("fn", [svc.save_cv, svc.save_cover_letter])
def test_save_unknown_application_is_not_found(store, fn):
    with pytest.raises(NotFound, match="Application not found."):
        fn("missing", "x")
    assert store[0] == []


def test_save_cv_saves_then_renders(store):
    calls, rendered = store
    assert svc.save_cv("a1", "<p>cv</p>") == ("APP", True)
    assert calls == [("cv", "a1", "<p>cv</p>")]
    assert rendered == [("<p>cv</p>", "a1.pdf", "a1.docx")]


def test_save_cover_letter_renders_letter_html(store, monkeypatch):
    calls, rendered = store
    profile = SimpleNamespace(name="")
    monkeypatch.setattr(
        svc._truth, "load", lambda: SimpleNamespace(profile=profile)
    )
    monkeypatch.setattr(svc, "_contact_line", lambda p: "contact")
    seen = {}

    def fake_letter(text, name, contact):
        seen.update(text=text, name=name, contact=contact)
        return "<html/>"

    monkeypatch.setattr("render.cover_letter.render_letter_html", fake_letter)
    assert svc.save_cover_letter("a1", "Dear") == ("APP", True)
    assert seen == {"text": "Dear", "name": "Your Name", "contact": "contact"}
    assert calls == [("cl", "a1", "Dear")]
    assert rendered == [("<html/>", "a1-cl.pdf", "a1-cl.docx")]
