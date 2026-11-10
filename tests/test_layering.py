"""Pins the layering invariants the services-layer refactor establishes, so
they cannot silently regress.

(a) No module under truthcv/services/ imports fastapi.
(b) The route handlers named in _EXTRACTED_ROUTE_FUNCTIONS make no direct
    data_dir() call, wherever the Phase 4 split of truthcv/adapters/http/routes.py now defines
    them (truthcv/adapters/http/routes.py or one of its split-out modules) — file I/O is reached
    through truthcv/services/. Each name must be found in exactly one of those files.
(c) No module outside truthcv/infra/storage/ and truthcv/domain/truth/ imports data_dir from truthcv.domain.truth.store
    (truthcv.domain.truth.store no longer defines data_dir at all; truthcv.infra.storage.paths is its only
    home now).
(d) None of the files in the Phase 4 split of truthcv/adapters/http/routes.py calls an
    underscore-prefixed function of any store module.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVICES_DIR = REPO_ROOT / "truthcv" / "services"
HTTP_DIR = REPO_ROOT / "truthcv" / "adapters" / "http"

# The Phase 4 split of truthcv/adapters/http/routes.py: the code that used to live in routes.py is
# moving, one resource at a time, into flat modules (plus shared helpers in
# route_support.py). These are the files the routes.py invariants apply to.
# Named explicitly, not globbed: prompt_routes, job_routes and
# gmail_suggestion_routes were never under this invariant.
_PHASE4_ROUTE_FILE_NAMES = (
    "routes.py",
    "route_support.py",
    "screening_routes.py",
    "run_routes.py",
    "company_finding_routes.py",
    "truth_routes.py",
    "cv_routes.py",
    "application_routes.py",
    "settings_routes.py",
    "job_board_routes.py",
    "agent_routes.py",
    "browser_routes.py",
    "auth_routes.py",
    "gmail_routes.py",
)


def _phase4_route_files() -> list[Path]:
    paths = [HTTP_DIR / name for name in _PHASE4_ROUTE_FILE_NAMES]
    missing = [p.name for p in paths if not p.exists()]
    assert not missing, f"listed Phase 4 route files do not exist: {missing}"
    return paths


def _all_py_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def test_services_modules_do_not_import_fastapi():
    offenders = []
    for path in _all_py_files(SERVICES_DIR):
        text = path.read_text(encoding="utf-8")
        if re.search(r"^\s*(import fastapi|from fastapi\b)", text, re.MULTILINE):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == [], f"services/* module(s) import fastapi: {offenders}"


# Only these six workflows were extracted into truthcv/services/ by this refactor
# (per the plan's explicit out-of-scope note: "All 63 routes — only the six
# workflows carrying substantial inline logic ... are extracted; the rest
# are already thin"). Route handlers outside this list may still legitimately
# call data_dir()/get_provider() directly — that was never in scope.
_EXTRACTED_ROUTE_FUNCTIONS = (
    "render_route",
    "cover_letter",
    "confirm_inferences",
    "create_screening",
    "mark_screening_applied",
    "list_applications",
    "list_applications_page",
    "export_applications",
    "create_application",
    "update_application",
    "put_agent_config",
)


def _function_body(text: str, name: str) -> str | None:
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.match(rf"def {re.escape(name)}\s*\(", line):
            start = i
            break
    if start is None:
        return None
    body_lines = [lines[start]]
    for line in lines[start + 1 :]:
        if line and not line[0].isspace() and not line.startswith(("@", ")")):
            break
        body_lines.append(line)
    return "\n".join(body_lines)


def test_extracted_routes_do_not_call_data_dir_directly():
    # get_provider() is deliberately still called from some of these route
    # handlers (e.g. cover_letter) and passed INTO the service as an explicit
    # argument — truthcv/services/* must never construct its own provider (checked
    # separately below). data_dir(), by contrast, must not appear in any of
    # these route bodies at all: file I/O for these six workflows is now
    # entirely the service's job.
    texts = {p: p.read_text(encoding="utf-8") for p in _phase4_route_files()}
    offenders = {}
    for name in _EXTRACTED_ROUTE_FUNCTIONS:
        found = [
            (p, body)
            for p, text in texts.items()
            if (body := _function_body(text, name)) is not None
        ]
        assert len(found) == 1, (
            f"`def {name}(` must be defined in exactly one Phase 4 route file, "
            f"found in: {[str(p.relative_to(REPO_ROOT)) for p, _ in found]}"
        )
        path, body = found[0]
        hits = re.findall(r"(?<![.\w])data_dir\s*\(", body)
        if hits:
            offenders[f"{path.relative_to(REPO_ROOT)}::{name}"] = hits
    assert offenders == {}, (
        f"extracted route handler(s) in the Phase 4 route files still call "
        f"data_dir() directly instead of going through services/: {offenders}"
    )


def test_services_modules_do_not_call_get_provider():
    # A service must receive its LLM provider as an explicit argument from
    # its caller, never construct one itself — that keeps the provider
    # selection (env/config driven) entirely on the adapter side.
    offenders = []
    for path in _all_py_files(SERVICES_DIR):
        text = path.read_text(encoding="utf-8")
        if re.search(r"(?<![.\w])get_provider\s*\(", text):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == [], f"services/* module(s) call get_provider() themselves: {offenders}"


def test_no_module_outside_storage_and_truth_imports_data_dir_from_truth_store():
    offenders = []
    for path in _all_py_files(REPO_ROOT):
        rel = path.relative_to(REPO_ROOT)
        parts = rel.parts
        if parts[0] in ("node_modules", ".git"):
            continue
        if parts[:3] in (("truthcv", "infra", "storage"), ("truthcv", "domain", "truth")):
            continue
        if "node_modules" in parts:
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(r"from\s+truthcv\.domain\.truth\.store\s+import[^\n]*\bdata_dir\b", text) or re.search(
            r"from\s+\.store\s+import[^\n]*\bdata_dir\b", text
        ):
            offenders.append(str(rel))
    assert offenders == [], f"module(s) importing data_dir from truth.store: {offenders}"


def test_routes_calls_no_underscore_prefixed_store_function():
    offenders = {}
    for path in _phase4_route_files():
        text = path.read_text(encoding="utf-8")
        hits = re.findall(r"\b\w*_store\._[a-zA-Z]\w*\s*\(", text)
        if hits:
            offenders[str(path.relative_to(REPO_ROOT))] = hits
    assert offenders == {}, f"Phase 4 route file(s) reach into a private store function: {offenders}"
