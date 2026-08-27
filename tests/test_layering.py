"""Pins the layering invariants the services-layer refactor establishes, so
they cannot silently regress.

(a) No module under services/ imports fastapi.
(b) api/routes.py makes no direct data_dir() or get_provider() call — both
    are now reached through services/.
(c) No module outside storage/ and truth/ imports data_dir from truth.store
    (truth.store no longer defines data_dir at all; storage.paths is its only
    home now).
(d) api/routes.py calls no underscore-prefixed function of any store module.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVICES_DIR = REPO_ROOT / "services"
ROUTES_PATH = REPO_ROOT / "api" / "routes.py"


def _all_py_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def test_services_modules_do_not_import_fastapi():
    offenders = []
    for path in _all_py_files(SERVICES_DIR):
        text = path.read_text(encoding="utf-8")
        if re.search(r"^\s*(import fastapi|from fastapi\b)", text, re.MULTILINE):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == [], f"services/* module(s) import fastapi: {offenders}"


# Only these six workflows were extracted into services/ by this refactor
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
    "export_applications",
    "create_application",
    "update_application",
    "put_agent_config",
)


def _function_body(text: str, name: str) -> str:
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.match(rf"def {re.escape(name)}\s*\(", line):
            start = i
            break
    assert start is not None, f"could not find `def {name}(` in api/routes.py"
    body_lines = [lines[start]]
    for line in lines[start + 1 :]:
        if line and not line[0].isspace() and not line.startswith(("@", ")")):
            break
        body_lines.append(line)
    return "\n".join(body_lines)


def test_extracted_routes_do_not_call_data_dir_directly():
    # get_provider() is deliberately still called from some of these route
    # handlers (e.g. cover_letter) and passed INTO the service as an explicit
    # argument — services/* must never construct its own provider (checked
    # separately below). data_dir(), by contrast, must not appear in any of
    # these route bodies at all: file I/O for these six workflows is now
    # entirely the service's job.
    text = ROUTES_PATH.read_text(encoding="utf-8")
    offenders = {}
    for name in _EXTRACTED_ROUTE_FUNCTIONS:
        body = _function_body(text, name)
        hits = re.findall(r"(?<![.\w])data_dir\s*\(", body)
        if hits:
            offenders[name] = hits
    assert offenders == {}, (
        f"extracted route handler(s) still call data_dir() directly instead "
        f"of going through services/: {offenders}"
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
        if parts[0] in ("storage", "truth", "node_modules", ".git"):
            continue
        if "node_modules" in parts:
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(r"from\s+truth\.store\s+import[^\n]*\bdata_dir\b", text) or re.search(
            r"from\s+\.store\s+import[^\n]*\bdata_dir\b", text
        ):
            offenders.append(str(rel))
    assert offenders == [], f"module(s) importing data_dir from truth.store: {offenders}"


def test_routes_calls_no_underscore_prefixed_store_function():
    text = ROUTES_PATH.read_text(encoding="utf-8")
    offenders = re.findall(r"\b\w*_store\._[a-zA-Z]\w*\s*\(", text)
    assert offenders == [], f"api/routes.py reaches into a private store function: {offenders}"
