"""Paths derived from a module's `__file__` must keep resolving to the same
files now that every package lives under truthcv/: the repo-root ones still
point at the repo root, and the package-relative ones move with their package.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_dotenv_is_read_from_the_repo_root(monkeypatch):
    import truthcv.adapters.http as http_pkg

    read: list[Path] = []

    def fake_read_text(self, *args, **kwargs):
        read.append(self)
        raise OSError("not reading real files in this test")

    monkeypatch.setattr(Path, "read_text", fake_read_text)
    http_pkg._load_dotenv()
    assert read == [REPO_ROOT / ".env"]


def test_local_canonical_cv_default_is_under_the_repo_root_assets():
    from truthcv.domain.truth import answers

    assert answers._LOCAL_CANONICAL_CV == REPO_ROOT / "assets" / "canonical_cv.pdf"


def test_static_dir_sits_next_to_the_http_package_and_is_ignored(monkeypatch):
    from truthcv.adapters.http import config

    monkeypatch.delenv("STATIC_DIR", raising=False)
    expected = REPO_ROOT / "truthcv" / "adapters" / "http" / "static"
    assert config.static_dir().resolve() == expected
    # The built bundle there must never be committed or leak into the image.
    gitignore = (REPO_ROOT / ".gitignore").read_text().splitlines()
    dockerignore = (REPO_ROOT / ".dockerignore").read_text().splitlines()
    assert "/truthcv/adapters/http/static/" in gitignore
    assert "truthcv/adapters/http/static/" in dockerignore


def test_render_templates_dir_moves_with_the_render_package():
    from truthcv.engines.render import html

    assert html._TEMPLATE_DIR.resolve() == REPO_ROOT / "truthcv" / "engines" / "render" / "templates"
    assert (html._TEMPLATE_DIR / "cv.html.j2").is_file()
    assert (html._TEMPLATE_DIR / "cover_letter.html.j2").is_file()
